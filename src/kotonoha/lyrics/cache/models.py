"""Typed values exchanged by the persistent lyrics-cache boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..artifact import LyricsArtifact


@dataclass(frozen=True, slots=True)
class LyricsCacheKey:
    """Stable provider-scoped identity of one cached lyric artifact."""

    provider: str
    provider_song_id: str


@dataclass(frozen=True, slots=True)
class LyricsCacheQuery:
    """User-facing cache search criteria; an empty keyword lists every entry."""

    keyword: str = ""
    provider: str | None = None


class LyricsCacheMode(StrEnum):
    """Identify automatic candidate storage or a manual choice, not display use."""

    AUTO = "auto"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class LyricsCacheHit:
    """Return one validated artifact together with its persisted storage mode."""

    artifact: LyricsArtifact
    mode: LyricsCacheMode


@dataclass(frozen=True, slots=True)
class LyricsCacheEntry:
    """Metadata exposed to cache management without leaking the raw payload."""

    key: LyricsCacheKey
    title: str
    artist: str
    album: str
    duration_s: float | None
    fetched_at: float
    # Updated on storage and matching reads, even when another candidate wins.
    last_accessed: float
    mode: LyricsCacheMode = LyricsCacheMode.AUTO


class CacheWriteStatus(StrEnum):
    """Outcome of an explicit cache write."""

    CREATED = "created"
    UPDATED = "updated"
    NOT_FOUND = "not-found"


@dataclass(frozen=True, slots=True)
class CacheWriteResult:
    """Report whether a cache write created, updated, or missed a record."""

    key: LyricsCacheKey
    status: CacheWriteStatus


class CacheDeleteStatus(StrEnum):
    """Outcome of deleting one cache record."""

    DELETED = "deleted"
    NOT_FOUND = "not-found"


@dataclass(frozen=True, slots=True)
class CacheDeleteResult:
    """Report whether a requested cache record was actually removed."""

    key: LyricsCacheKey
    status: CacheDeleteStatus


__all__ = [
    "CacheDeleteResult",
    "CacheDeleteStatus",
    "CacheWriteResult",
    "CacheWriteStatus",
    "LyricsCacheEntry",
    "LyricsCacheHit",
    "LyricsCacheKey",
    "LyricsCacheMode",
    "LyricsCacheQuery",
]
