"""Normalize track metadata and rank lyrics-provider candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum
from unicodedata import normalize as unicode_normalize

from .hanzi_fold import fold_to_simplified

_PARENS = re.compile(r"[\(（\[【](.*?)[\)）\]】]")
_DASH_SUFFIX = re.compile(r"\s+[-–—]\s+(.+)$")
_FEAT_SUFFIX = re.compile(r"\b(?:feat(?:uring)?|ft)\b\.?.*$", re.IGNORECASE)
_ARTIST_SEPARATOR = re.compile(
    r"\s*(?:,|/|&|;|、|，|\band\b|\bwith\b|\bfeat(?:uring)?\b\.?|\bft\b\.?)\s*",
    re.IGNORECASE,
)
# "和" is the Chinese "and" and a common artist-list separator in CJK metadata
# ("初音ミク和鏡音リン"). CJK has no word boundaries, so split on it only when it sits
# between two runs of >=2 non-space characters — that separates a genuinely fused
# list without fragmenting a single name that merely contains 和 (山田和樹, 大和).
# NOTE: the katakana middle dot "・" is deliberately NOT a separator here. Unlike 和
# (which joins whole names, so two different people stay distinct tokens), "・"
# separates the forename and surname WITHIN one katakana name (テイラー・スウィフト),
# so splitting it makes two different artists who merely share a given name
# (ジョン・レノン / ジョン・デンバー) collide — a confident wrong-lyrics match.
_AND_SEPARATOR = re.compile(r"(?<=\S\S)和(?=\S\S)")
_KEEP = re.compile(r"[^\w一-鿿]+")
_VERSION_TAGS = {
    "acoustic": ("acoustic", "unplugged"),
    "demo": ("demo",),
    "edit": ("edit",),
    "extended": ("extended",),
    "instrumental": ("instrumental",),
    "karaoke": ("karaoke",),
    "live": ("live",),
    "remaster": ("remaster", "remastered"),
    "remix": ("remix",),
}
# Tags that change the recording but NOT the lyrics: a remaster has the same
# words as the studio take, so it must not force a version conflict that rejects
# the only correct candidate. (live/acoustic/instrumental/remix/etc. can differ.)
_LYRIC_NEUTRAL_TAGS = frozenset({"remaster"})
# One compiled word-boundary matcher per tag, built once — _extract_version_tags
# runs for every candidate, so per-call re.search(f"\\b{marker}\\b") was needless.
_VERSION_TAG_PATTERNS = {
    tag: re.compile(r"\b(?:" + "|".join(re.escape(marker) for marker in markers) + r")\b")
    for tag, markers in _VERSION_TAGS.items()
}

NORMALIZER_VERSION = 1


class MatchConfidence(str, Enum):
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
    duration_delta: float | None


def _fold_latin_accents(text: str) -> str:
    """Strip accents from Latin letters only (é->e, ö->o, ñ->n) so an accented
    title matches its unaccented spelling (Déjà Vu vs Deja Vu, Motörhead vs
    Motorhead). A Japanese dakuten (が = か + U+3099) or any non-Latin base is
    left untouched: only a character whose NFD base is an ASCII letter is folded,
    so kana/hangul/cyrillic/CJK are never mangled."""
    folded: list[str] = []
    for char in text:
        decomposed = unicode_normalize("NFD", char)
        base = decomposed[0]
        folded.append(base if len(decomposed) > 1 and base.isascii() and base.isalpha() else char)
    return "".join(folded)


def normalize(text: str) -> str:
    """Return a comparison form without changing version semantics elsewhere.

    Traditional Chinese is folded to Simplified so a traditional-tagged track
    (李榮浩 / 麻雀 from a zh-Hant browser) compares equal to Netease's simplified
    catalogue (李荣浩), and Latin accents are folded so accented Western titles
    match their plain spelling. Both folds are applied to the track and the
    candidate alike, so they are symmetric and only ever affect this comparison
    key (never display, search queries, or version semantics)."""
    value = _fold_latin_accents(unicode_normalize("NFKC", text).casefold())
    value = fold_to_simplified(value)
    value = _PARENS.sub("", value)
    value = _FEAT_SUFFIX.sub("", value)
    return _KEEP.sub("", value).strip()


def split_title(title: str) -> tuple[str, frozenset[str]]:
    """Split a display title into its base title and known version qualifiers."""
    value = unicode_normalize("NFKC", title)
    tags: set[str] = set()
    for group in _PARENS.findall(value):
        tags.update(_extract_version_tags(group))
    base = _PARENS.sub("", value).strip()
    suffix = _DASH_SUFFIX.search(base)
    if suffix is not None:
        suffix_tags = _extract_version_tags(suffix.group(1))
        if suffix_tags:
            tags.update(suffix_tags)
            base = base[: suffix.start()].strip()
    return base, frozenset(tags)


def _extract_version_tags(value: str) -> set[str]:
    normalized_value = value.casefold()
    return {tag for tag, pattern in _VERSION_TAG_PATTERNS.items() if pattern.search(normalized_value)}


def base_title(title: str) -> str:
    return split_title(title)[0]


def _artist_parts(artist: str) -> tuple[str, ...]:
    value = unicode_normalize("NFKC", artist).strip()
    parts: list[str] = []
    for chunk in _ARTIST_SEPARATOR.split(value):
        parts.extend(_AND_SEPARATOR.split(chunk))
    return tuple(part.strip() for part in parts if part.strip())


def artist_tokens(artist: str) -> frozenset[str]:
    return frozenset(token for token in (normalize(part) for part in _artist_parts(artist)) if token)


def primary_artist(artist: str) -> str:
    parts = _artist_parts(artist)
    return parts[0].strip() if parts else artist.strip()


def _fuzzy_contains(candidate: Candidate, track: TrackMetadata) -> bool:
    """True when the candidate's title AND all its artist tokens appear inside the
    cleaned track title — the fuzzy-mode rescue for a title that fuses artist and
    song ("陳一發兒 童話鎮"). The title must be substantial (>=2 CJK chars or >=5
    letters) so a short common word does not match a longer string by accident."""
    haystack = normalize(track.title)  # brackets already stripped by normalize()
    title = normalize(split_title(candidate.title)[0])
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
    track_base, track_tags = split_title(track.title)
    candidate_base, candidate_tags = split_title(candidate.title)
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
    title_strong = title_exact or (
        min(len(normalized_track), best_form_len) >= 4 and title_ratio >= 0.88
    )

    track_artists = artist_tokens(track.artist)
    candidate_artists = artist_tokens(candidate.artist)
    shared_artists = track_artists & candidate_artists
    artist_overlap = not track_artists or not candidate_artists or bool(shared_artists)
    artist_evidence = bool(track_artists and candidate_artists and shared_artists)
    artist_identity = bool(track_artists and track_artists == candidate_artists)
    album_match = bool(track.album and candidate.album and normalize(track.album) == normalize(candidate.album))
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
        duration_delta=duration_delta,
    )


def _evidence_sort_key(evidence: MatchEvidence) -> tuple[int, bool, bool, bool, bool, float]:
    confidence_rank = {
        MatchConfidence.NONE: 0,
        MatchConfidence.MEDIUM: 1,
        MatchConfidence.HIGH: 2,
    }
    duration_rank = -evidence.duration_delta if evidence.duration_delta is not None else float("-inf")
    # Rank genuine artist evidence (exact set, then shared tokens) above the
    # duration tie-break: artist_overlap is vacuously true when a candidate has no
    # artist, so it must not let a metadata-less candidate tie a real artist match.
    return (
        confidence_rank[evidence.confidence],
        evidence.title_exact,
        evidence.artist_identity,
        evidence.artist_evidence,
        evidence.album_match,
        duration_rank,
    )


def best_match(
    candidates: list[Candidate], track: TrackMetadata, *, fuzzy: bool = False
) -> MatchEvidence | None:
    matches = [evaluate_match(candidate, track, fuzzy=fuzzy) for candidate in candidates]
    usable = [match for match in matches if match.confidence is not MatchConfidence.NONE]
    return max(usable, key=_evidence_sort_key, default=None)


def ranked_matches(
    candidates: list[Candidate], track: TrackMetadata, *, fuzzy: bool = False
) -> list[MatchEvidence]:
    """All usable matches, best first. Lets a provider fall through to the next
    candidate when the top pick turns out to have no timed lyrics (common with
    UGC re-uploads that carry only credits metadata)."""
    matches = [evaluate_match(candidate, track, fuzzy=fuzzy) for candidate in candidates]
    usable = [match for match in matches if match.confidence is not MatchConfidence.NONE]
    return sorted(usable, key=_evidence_sort_key, reverse=True)


def query_variants(track: TrackMetadata, *, fuzzy: bool = False) -> tuple[str, ...]:
    raw = f"{track.title} {track.artist}".strip()
    fallback = f"{base_title(track.title)} {primary_artist(track.artist)}".strip()
    # A simplified-folded query is a fallback for any endpoint whose search is
    # script-sensitive; deduped away when the text is already simplified.
    folded = fold_to_simplified(raw)
    forms = [raw, fallback, folded]
    if fuzzy:
        noisy = noisy_title_queries(track)
        forms.extend(noisy)
        # Simplified folds too, so a Traditional-titled clip still hits a
        # Simplified-only catalogue (deduped when already Simplified).
        forms.extend(fold_to_simplified(query) for query in noisy)
    return tuple(dict.fromkeys(value for value in forms if value))


_BRACKETED = re.compile(r"[【\[（(][^】\]）)]*[】\]）)]")
# Corner/angle quotes and separators usually WRAP the title (「Lemon」《告白气球》)
# rather than junk, so they are flattened to spaces (delimiters), not removed.
_DELIMITERS = re.compile(r"[「」『』《》〈〉|/_~•・\-–—]+")
# Pure upload noise that is never part of a song name — stripped case-insensitively.
# Version words (cover/live/remix/acoustic/…) are deliberately NOT here: they change
# the recording and are handled by the version-tag logic, not thrown away.
# Latin terms use \b so they don't eat substrings of real words; the CJK terms get
# no \b — adjacent Han characters are all \w, so a word boundary never sits between
# them and "官方MV" / "完整版" would otherwise never strip out of a fused title.
_UPLOAD_NOISE_LATIN = re.compile(
    r"\b(?:officical|official|mv|m/v|hd|hq|uhd|sd|4k|8k|60fps|1080p|720p|480p|"
    r"lyrics?|lyric video|audio|music video|official (?:music )?video|official audio|"
    r"visualizer|vevo|topic|full version|hi-?res|high quality)\b",
    re.IGNORECASE,
)
_UPLOAD_NOISE_CJK = re.compile(
    r"完整版|无损|無損|高清|超清|画质|畫質|字幕|歌词|歌詞|官方|试听|試聽|现场|現場|直播"
)
_CJK_CLASS = "㐀-鿿豈-﫿぀-ヿ가-힯"
_CJK_TOKEN = re.compile(rf"[{_CJK_CLASS}]+")
_CJK_ONE = re.compile(rf"[{_CJK_CLASS}]")
_LATIN_TOKEN = re.compile(r"[0-9A-Za-z][0-9A-Za-z'’&.]*")
_WHITESPACE = re.compile(r"\s+")


def noisy_title_queries(track: TrackMetadata) -> tuple[str, ...]:
    """Extra search queries salvaged from a noisy browser/YouTube title, used only
    in fuzzy mode. Strips bracketed junk (【HD】, [歌詞字幕], …) then pulls the
    CJK-only and Latin-only runs as separate queries, so a dual-language,
    channel-tagged title like "【HD】陳一發兒- 童話鎮 [歌詞字幕] Chen Yifa - Fairy Town
    BELLA PING MUSIC CHANNEL" still yields "陳一發兒 童話鎮" and "Chen Yifa Fairy
    Town" to search on. A trailing ALL-CAPS channel/uploader tail is dropped."""
    stripped = _BRACKETED.sub(" ", track.title)
    stripped = _UPLOAD_NOISE_LATIN.sub(" ", stripped)
    stripped = _UPLOAD_NOISE_CJK.sub(" ", stripped)
    stripped = _DELIMITERS.sub(" ", stripped)
    queries: list[str] = []
    # Combined query first (both scripts, cleaned) — the best shot when the title
    # simply fused artist and song across a separator ("米津玄師 Lemon", "周杰倫 晴天").
    combined = _WHITESPACE.sub(" ", stripped).strip()
    if len(combined) >= 2:
        queries.append(combined)
    cjk = _WHITESPACE.sub(" ", " ".join(_CJK_TOKEN.findall(stripped))).strip()
    if len(cjk) >= 2:
        queries.append(cjk)
    latin_tokens = _LATIN_TOKEN.findall(stripped)
    # Drop a trailing ALL-CAPS uploader/channel tail (BELLA PING MUSIC CHANNEL), but
    # not when every remaining token is also caps — that is a genuinely all-caps
    # title (TALK THAT TALK), which we must keep whole.
    while (
        len(latin_tokens) > 2
        and latin_tokens[-1].isupper()
        and len(latin_tokens[-1]) >= 2
        and not all(token.isupper() for token in latin_tokens[:-1])
    ):
        latin_tokens.pop()
    latin = " ".join(latin_tokens).strip()
    if len(latin) >= 2:
        queries.append(latin)
    return tuple(dict.fromkeys(queries))
