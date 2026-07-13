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


@dataclass(frozen=True)
class MatchEvidence:
    candidate: Candidate
    confidence: MatchConfidence
    title_exact: bool
    artist_overlap: bool
    album_match: bool
    duration_delta: float | None
    version_conflict: bool


def normalize(text: str) -> str:
    """Return a comparison form without changing version semantics elsewhere.

    Traditional Chinese is folded to Simplified so a traditional-tagged track
    (李榮浩 / 麻雀 from a zh-Hant browser) compares equal to Netease's simplified
    catalogue (李荣浩). The fold is applied to both the track and the candidate,
    so it is symmetric and only ever affects this comparison key."""
    value = fold_to_simplified(unicode_normalize("NFKC", text).casefold())
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
    return {
        tag
        for tag, markers in _VERSION_TAGS.items()
        if any(re.search(rf"\b{re.escape(marker)}\b", normalized_value) for marker in markers)
    }


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


def evaluate_match(candidate: Candidate, track: TrackMetadata) -> MatchEvidence:
    track_base, track_tags = split_title(track.title)
    candidate_base, candidate_tags = split_title(candidate.title)
    normalized_track = normalize(track_base)
    normalized_candidate = normalize(candidate_base)
    title_exact = bool(normalized_track) and normalized_track == normalized_candidate
    # SequenceMatcher("", "") is 1.0, so two titles that normalize to empty (all
    # punctuation / parenthetical like "(intro)") would score a perfect fuzzy
    # ratio and wrongly match. Only trust the ratio when both sides are non-empty.
    title_ratio = (
        SequenceMatcher(None, normalized_track, normalized_candidate).ratio()
        if normalized_track and normalized_candidate
        else 0.0
    )
    title_strong = title_exact or (
        min(len(normalized_track), len(normalized_candidate)) >= 4 and title_ratio >= 0.88
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
    version_conflict = bool(track_tags or candidate_tags) and track_tags != candidate_tags
    catalog_identity = title_exact and artist_identity and album_match

    confidence = MatchConfidence.NONE
    if not version_conflict and artist_overlap:
        supporting_identity = artist_evidence or album_match or (
            duration_delta is not None and duration_delta <= 3.0
        )
        if title_strong and supporting_identity and (duration_delta is None or duration_delta <= 3.0):
            confidence = MatchConfidence.HIGH
        elif catalog_identity:
            confidence = MatchConfidence.MEDIUM
        elif title_strong and (duration_delta is None or duration_delta <= 8.0):
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
        album_match=album_match,
        duration_delta=duration_delta,
        version_conflict=version_conflict,
    )


def _evidence_sort_key(evidence: MatchEvidence) -> tuple[int, bool, bool, bool, float]:
    confidence_rank = {
        MatchConfidence.NONE: 0,
        MatchConfidence.MEDIUM: 1,
        MatchConfidence.HIGH: 2,
    }
    duration_rank = -evidence.duration_delta if evidence.duration_delta is not None else float("-inf")
    return (
        confidence_rank[evidence.confidence],
        evidence.title_exact,
        evidence.artist_overlap,
        evidence.album_match,
        duration_rank,
    )


def best_match(candidates: list[Candidate], track: TrackMetadata) -> MatchEvidence | None:
    matches = [evaluate_match(candidate, track) for candidate in candidates]
    usable = [match for match in matches if match.confidence is not MatchConfidence.NONE]
    return max(usable, key=_evidence_sort_key, default=None)


def query_variants(track: TrackMetadata) -> tuple[str, ...]:
    raw = f"{track.title} {track.artist}".strip()
    fallback = f"{base_title(track.title)} {primary_artist(track.artist)}".strip()
    # A simplified-folded query is a fallback for any endpoint whose search is
    # script-sensitive; deduped away when the text is already simplified.
    folded = fold_to_simplified(raw)
    return tuple(dict.fromkeys(value for value in (raw, fallback, folded) if value))
