"""Rank a provider's candidates against the track that is playing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from enum import StrEnum

from .hanzi_fold import fold_to_simplified
from .titles import (
    _CJK_ONE,
    _LYRIC_NEUTRAL_TAGS,
    _artist_variants,
    _is_bracket_only,
    artist_tokens,
    base_title,
    noisy_title_queries,
    normalize,
    primary_artist,
    split_title,
)


class MatchConfidence(StrEnum):
    NONE = "none"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class TrackMetadata:
    title: str
    artist: str
    album: str = ""
    duration_s: float | None = None


@dataclass(frozen=True)
class Candidate:
    song_id: str
    title: str
    artist: str
    duration_s: float | None
    album: str = ""
    # Alternate/translated names the provider lists for this song (Netease's
    # ``alias`` + ``transNames``), e.g. a song titled 生如夏花 that also carries
    # "Life Like Summer Flowers". Matched alongside the primary title so a track
    # reported under one name still matches a candidate indexed under the other.
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchEvidence:
    candidate: Candidate
    confidence: MatchConfidence
    title_exact: bool
    artist_overlap: bool
    artist_evidence: bool
    artist_identity: bool
    album_match: bool
    similarity_score: float
    duration_delta: float | None


def _similarity(left: str, right: str) -> float:
    normalized_left = normalize(left)
    normalized_right = normalize(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if len(normalized_left) < 2 or len(normalized_right) < 2:
        return float(normalized_left == normalized_right)
    left_bigrams = set(zip(normalized_left, normalized_left[1:], strict=False))
    right_bigrams = set(zip(normalized_right, normalized_right[1:], strict=False))
    return 2.0 * len(left_bigrams & right_bigrams) / (len(left_bigrams) + len(right_bigrams))


def _weighted_similarity(
    title_similarity: float,
    artist_similarity: float,
    album_similarity: float,
    *,
    has_artist: bool,
    has_album: bool,
) -> float:
    if has_artist and has_album:
        return title_similarity * 0.4 + artist_similarity * 0.2 + album_similarity * 0.4
    if has_artist:
        return title_similarity * 0.7 + artist_similarity * 0.3
    if has_album:
        return title_similarity * 0.8 + album_similarity * 0.2
    return title_similarity


def _fuzzy_contains(candidate: Candidate, track: TrackMetadata) -> bool:
    """True when the candidate's title AND all its artist tokens appear inside the
    cleaned track title — the fuzzy-mode rescue for a title that fuses artist and
    song ("陳一發兒 童話鎮"). The title must be substantial (>=2 CJK chars or >=5
    letters) so a short common word does not match a longer string by accident."""
    haystack = normalize(track.title)  # brackets already stripped by normalize()
    title = normalize(split_title(candidate.title, candidate.artist)[0])
    if not haystack or not title or title not in haystack:
        return False
    cjk_chars = len(_CJK_ONE.findall(title))
    if cjk_chars < 2 and len(title) < 5:
        return False
    # At least one substantial artist token must also appear in the title. "Any",
    # not "all", because provider artist fields carry UGC junk co-credits
    # ("周杰伦 / A-LNK") — the real name co-occurring is the evidence we need.
    candidate_artists = artist_tokens(candidate.artist)
    return any(len(token) >= 2 and token in haystack for token in candidate_artists)


def evaluate_match(candidate: Candidate, track: TrackMetadata, *, fuzzy: bool = False) -> MatchEvidence:
    track_base, track_tags = split_title(track.title, track.artist)
    candidate_base, candidate_tags = split_title(candidate.title, candidate.artist)
    normalized_track = normalize(track_base)
    # Compare against the candidate's primary title AND any alias/translated name,
    # keeping the best evidence: a track reported as "Life Like Summer Flowers"
    # matches a candidate named 生如夏花 that lists that English alias.
    candidate_forms = [normalize(candidate_base)]
    candidate_forms += [normalize(alias) for alias in candidate.aliases]
    candidate_forms = [form for form in candidate_forms if form]
    title_exact = bool(normalized_track) and normalized_track in candidate_forms
    # SequenceMatcher("", "") is 1.0, so two titles that normalize to empty (all
    # punctuation / parenthetical like "(intro)") would score a perfect fuzzy
    # ratio and wrongly match. Only trust the ratio when both sides are non-empty.
    # Keep the best-scoring form and gauge the length guard against THAT form.
    title_ratio = 0.0
    best_form_len = 0
    if normalized_track:
        for form in candidate_forms:
            ratio = SequenceMatcher(None, normalized_track, form).ratio()
            if ratio > title_ratio:
                title_ratio = ratio
                best_form_len = len(form)
    title_similarity = max((_similarity(normalized_track, form) for form in candidate_forms), default=0.0)
    title_strong = title_exact or (
        min(len(normalized_track), best_form_len) >= 4 and title_ratio >= 0.88
    )
    # A title that is nothing but a bracketed span ("(intro)", "【七月上】") is kept
    # rather than stripped to nothing, but two such titles must agree exactly:
    # "(intro)" and "(outro)" are different interludes that a ratio would pair up.
    if _is_bracket_only(track.title) and _is_bracket_only(candidate.title) and not title_exact:
        title_strong = False
        title_ratio = 0.0  # no partial credit either: they are different names

    track_artists = artist_tokens(track.artist)
    candidate_artists = artist_tokens(candidate.artist)
    shared_artists = track_artists & candidate_artists
    artist_overlap = not track_artists or not candidate_artists or bool(shared_artists)
    artist_evidence = bool(track_artists and candidate_artists and shared_artists)
    artist_identity = bool(track_artists and track_artists == candidate_artists)
    album_match = bool(track.album and candidate.album and normalize(track.album) == normalize(candidate.album))
    artist_similarity = _similarity(track.artist, candidate.artist)
    album_similarity = _similarity(track.album, candidate.album)
    similarity_score = _weighted_similarity(
        title_similarity,
        artist_similarity,
        album_similarity,
        has_artist=bool(track_artists),
        has_album=bool(normalize(track.album)),
    )
    duration_delta = (
        abs(track.duration_s - candidate.duration_s)
        if track.duration_s is not None and candidate.duration_s is not None
        else None
    )
    # Only lyric-changing tags conflict; a remaster shares the studio lyrics.
    track_lyric_tags = track_tags - _LYRIC_NEUTRAL_TAGS
    candidate_lyric_tags = candidate_tags - _LYRIC_NEUTRAL_TAGS
    version_conflict = bool(track_lyric_tags or candidate_lyric_tags) and track_lyric_tags != candidate_lyric_tags
    catalog_identity = title_exact and artist_identity and album_match
    # Fuzzy containment: for a cluttered browser title that carries both names in one
    # string ("陳一發兒 童話鎮 …"), accept a candidate whose (long-enough) title AND
    # every artist token appear inside the cleaned track title. Requiring the artist
    # to co-occur keeps a short title from matching by coincidence.
    fuzzy_title_hit = fuzzy and not title_strong and _fuzzy_contains(candidate, track)

    confidence = MatchConfidence.NONE
    if not version_conflict and artist_overlap:
        # Duration alone only corroborates a title match when the track actually
        # names an artist. Otherwise (the common empty-artist browser case) a short
        # generic alias like "Lemon"/"Rain" plus a coincidental ±3s duration would
        # promote an unrelated song to HIGH and cache it as authoritative.
        supporting_identity = artist_evidence or album_match or (
            duration_delta is not None and duration_delta <= 3.0 and bool(track_artists)
        )
        if title_exact and artist_identity and (duration_delta is None or duration_delta <= 8.0):
            # Exact title AND the exact same artist set is a strong identity even
            # if the reported duration is a few seconds off (common metadata skew).
            confidence = MatchConfidence.HIGH
        elif title_strong and supporting_identity and (duration_delta is None or duration_delta <= 3.0):
            confidence = MatchConfidence.HIGH
        elif catalog_identity:
            confidence = MatchConfidence.MEDIUM
        elif (
            title_exact
            and artist_identity
            and duration_delta is not None
            and duration_delta > min(track.duration_s or 0.0, candidate.duration_s or 0.0)
        ):
            # Exact title AND exact artist, but the durations differ by more than the
            # whole shorter track (one is >2x the other). That is not a slightly
            # different edit — it is a browser/stream reporting a container length (a
            # 27-min video for a 5-min song). The lyrics are still the right ones, so
            # accept as MEDIUM; a duration-accurate candidate, if any, still outranks
            # it. A merely moderate duration gap stays rejected (it may be a real
            # different recording), preserving the album-identity requirement there.
            confidence = MatchConfidence.MEDIUM
        elif title_strong and (duration_delta is None or duration_delta <= 8.0):
            confidence = MatchConfidence.MEDIUM
        elif fuzzy_title_hit:
            # The candidate's title + artist both sit inside the noisy track title.
            confidence = MatchConfidence.MEDIUM
        elif (
            not title_strong
            and title_ratio >= 0.5
            and track_artists
            and candidate_artists
            and duration_delta is not None
        ):
            if duration_delta <= 3.0 and (album_match or track_artists == candidate_artists):
                confidence = MatchConfidence.MEDIUM

    return MatchEvidence(
        candidate=candidate,
        confidence=confidence,
        title_exact=title_exact,
        artist_overlap=artist_overlap,
        artist_evidence=artist_evidence,
        artist_identity=artist_identity,
        album_match=album_match,
        similarity_score=similarity_score,
        duration_delta=duration_delta,
    )


def _evidence_sort_key(evidence: MatchEvidence) -> tuple[int, float, float]:
    confidence_rank = {
        MatchConfidence.NONE: 0,
        MatchConfidence.MEDIUM: 1,
        MatchConfidence.HIGH: 2,
    }
    duration_rank = -evidence.duration_delta if evidence.duration_delta is not None else float("-inf")
    return (
        confidence_rank[evidence.confidence],
        evidence.similarity_score,
        duration_rank,
    )


def best_match(
    candidates: list[Candidate], track: TrackMetadata, *, fuzzy: bool = False
) -> MatchEvidence | None:
    """The single best usable match, or None.

    Delegates rather than scoring again: this held its own copy of the loop, so the
    salvaged-query rescue reached the providers that rank and not the one that only
    wants the winner.
    """
    ranked = ranked_matches(candidates, track, fuzzy=fuzzy)
    return ranked[0] if ranked else None


def _performer_sits_in_the_title(
    candidates: list[Candidate], track: TrackMetadata, salvaged_titles: tuple[str, ...]
) -> bool:
    """Whether a candidate's performer is named in the title and not in the artist field.

    YouTube fills the artist field with the uploading channel while the performer
    stays in the title ("IU (아이유) _ Good Day (좋은 날) _" credited to "1theK
    (원더케이)"). Requiring the performer to be present somewhere is what separates
    that from a track that simply has no usable artist: judging "Forever" on its
    title alone accepts a different band's song of the same name.
    """
    reported = artist_tokens(track.artist)
    # The salvaged forms, never the reported title: a guest credit has already been
    # ruled out of the song name, and reading the guest there opened this gate for
    # "(特別演出: 派偉俊)【告白氣球…】" and accepted a song actually named 派偉俊.
    titles = [normalize(title) for title in salvaged_titles]
    for candidate in candidates:
        performer = artist_tokens(candidate.artist)
        if not performer or performer & reported:
            continue
        if any(len(name) >= 2 and any(name in title for title in titles) for name in performer):
            return True
    return False


def ranked_matches(
    candidates: list[Candidate], track: TrackMetadata, *, fuzzy: bool = False
) -> list[MatchEvidence]:
    """All usable matches, best first. Lets a provider fall through to the next
    candidate when the top pick turns out to have no timed lyrics (common with
    UGC re-uploads that carry only credits metadata)."""
    matches = [evaluate_match(candidate, track, fuzzy=fuzzy) for candidate in candidates]
    if fuzzy:
        # The salvage widened the search but not the acceptance. Searching for a clip
        # titled "Those Bygone Years 那些年" returns 那些年 / 胡夏 as the first
        # candidate, and the scorer then rejected all ten, because it was still
        # comparing them against the uploader's decorated title. A candidate is
        # judged against the same forms the query was built from, and keeps its best
        # showing; the forms all come from the reported title, so this admits what
        # was searched for rather than anything new.
        titles = (track.title, *(q for q in noisy_title_queries(track.title) if q != track.title))
        artists = [track.artist, *_artist_variants(track.artist)]
        # A reported artist that no candidate shares a single name with is not the
        # performer: YouTube fills the field with the uploading channel ("1theK
        # (원더케이)") or, on a "Song - Film" title, with the song itself — Kesariya
        # arrived as the artist of a track titled Brahmāstra. Judging on the title
        # alone is the only evidence left, and it is tried last, after every reading
        # that does use the reported artist.
        if track.artist and _performer_sits_in_the_title(candidates, track, titles[1:]):
            artists.append("")
        salvaged = [
            replace(track, title=title, artist=artist)
            for title in titles
            for artist in artists
            if (title, artist) != (track.title, track.artist)
        ]
        _, reported_tags = split_title(track.title, track.artist)
        reported_versions = reported_tags - _LYRIC_NEUTRAL_TAGS
        for index, match in enumerate(matches):
            if match.confidence is not MatchConfidence.NONE:
                continue
            # The salvage strips a version marker along with the decoration around it
            # — 不谓侠 (DJ版) is salvaged as 不谓侠 — so without this the rescue hands a
            # DJ cut the studio recording's words, or the studio take a live one's.
            # The version is read from the reported title, never from the salvage.
            _, candidate_tags = split_title(candidates[index].title, candidates[index].artist)
            if reported_versions != candidate_tags - _LYRIC_NEUTRAL_TAGS:
                continue
            for variant in salvaged:
                rescored = evaluate_match(candidates[index], variant, fuzzy=True)
                if rescored.confidence is not MatchConfidence.NONE:
                    matches[index] = rescored
                    break
    usable = [match for match in matches if match.confidence is not MatchConfidence.NONE]
    return sorted(usable, key=_evidence_sort_key, reverse=True)


@dataclass(frozen=True)
class QueryVariant:
    """One reading of the track to search for, and where that reading came from.

    Providers ask for different shapes — one endpoint takes a fused string, another
    takes title and artist apart — so the ladder yields the parts and each provider
    maps them to its own request. Three providers used to assemble their own ladder
    and only one carried the simplified folds, so a Traditional title missed a
    Simplified catalogue on the other two.
    """

    title: str
    artist: str
    #: Which rung produced this, so a log line can say what actually found the song.
    rung: str

    @property
    def text(self) -> str:
        """The fused form, for an endpoint that takes a single search string."""
        return f"{self.title} {self.artist}".strip()


def query_variants(track: TrackMetadata, *, fuzzy: bool = False) -> tuple[QueryVariant, ...]:
    """The readings to search for, most faithful first.

    A salvaged title is paired with no artist on purpose: it is recovered from an
    upload title whose "artist" is usually the channel that posted it.
    """
    base = base_title(track.title).strip()
    rungs = [
        QueryVariant(track.title, track.artist, "reported"),
        QueryVariant(base, "", "title-only"),
        QueryVariant(base, primary_artist(track.artist), "base+primary"),
        QueryVariant(fold_to_simplified(track.title), fold_to_simplified(track.artist), "simplified"),
    ]
    if fuzzy:
        salvaged = noisy_title_queries(track.title)
        rungs.extend(QueryVariant(title, "", "salvaged") for title in salvaged)
        rungs.extend(
            QueryVariant(fold_to_simplified(title), "", "salvaged-simplified") for title in salvaged
        )
    seen: dict[tuple[str, str], QueryVariant] = {}
    for variant in rungs:
        if variant.title and (variant.title, variant.artist) not in seen:
            seen[(variant.title, variant.artist)] = variant
    return tuple(seen.values())
