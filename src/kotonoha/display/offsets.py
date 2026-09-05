"""Structured per-track timing corrections for lyric presentation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from ..lyrics.models import LyricsDocument
from ..playback.models import TrackIdentity

TRACK_OFFSET_LIMIT_MS = 10_000
TRACK_OFFSET_STEP_MS = 100
MAX_OFFSET_IDENTITY_TEXT = 2048


def clamp_track_offset(offset_ms: int) -> int:
    """Return a display timing correction constrained to plus or minus ten seconds."""
    if isinstance(offset_ms, bool) or not isinstance(offset_ms, int):
        raise TypeError("track offset must be an integer number of milliseconds")
    return max(-TRACK_OFFSET_LIMIT_MS, min(TRACK_OFFSET_LIMIT_MS, offset_ms))


@dataclass(frozen=True, slots=True)
class TrackOffsetKey:
    """Identify one lyric timeline for one normalized recording.

    The key is built by :func:`track_offset_key`; callers do not provide an
    opaque concatenated string. The lyric digest distinguishes changed content
    even when a provider reuses the same song identifier.
    """

    track_title: str
    track_artist: str
    track_album: str
    track_duration_s: int | None
    lyrics_source_id: str
    lyrics_song_id: str | None
    lyrics_digest: str

    def __post_init__(self) -> None:
        """Normalize and validate every identity component at the domain boundary."""
        title = _identity_text(self.track_title, "track title", casefold=True)
        artist = _identity_text(self.track_artist, "track artist", casefold=True)
        album = _identity_text(self.track_album, "track album", casefold=True)
        source_id = _identity_text(self.lyrics_source_id, "lyrics source", casefold=True)
        song_id = _optional_identity_text(self.lyrics_song_id, "lyrics song id")
        if not title and not artist:
            raise ValueError("track offset key requires a title or artist")
        if not source_id:
            raise ValueError("track offset key requires a lyrics source")
        if self.track_duration_s is not None and (
            isinstance(self.track_duration_s, bool)
            or not isinstance(self.track_duration_s, int)
            or self.track_duration_s < 0
        ):
            raise ValueError("track offset key duration must be a non-negative integer")
        if (
            not isinstance(self.lyrics_digest, str)
            or len(self.lyrics_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.lyrics_digest.casefold())
        ):
            raise ValueError("track offset key requires a SHA-256 lyrics digest")
        object.__setattr__(self, "track_title", title)
        object.__setattr__(self, "track_artist", artist)
        object.__setattr__(self, "track_album", album)
        object.__setattr__(self, "lyrics_source_id", source_id)
        object.__setattr__(self, "lyrics_song_id", song_id)
        object.__setattr__(self, "lyrics_digest", self.lyrics_digest.casefold())


@dataclass(frozen=True, slots=True)
class TrackOffsetEntry:
    """Associate one structured lyric timeline identity with its correction."""

    key: TrackOffsetKey
    offset_ms: int

    def __post_init__(self) -> None:
        """Keep values valid before they can reach display or persistence code."""
        if not isinstance(self.key, TrackOffsetKey):
            raise TypeError("track offset entry requires a TrackOffsetKey")
        object.__setattr__(self, "offset_ms", clamp_track_offset(self.offset_ms))


@dataclass(frozen=True, slots=True)
class TrackOffsetSnapshot:
    """Immutable collection of user timing corrections."""

    entries: tuple[TrackOffsetEntry, ...] = ()
    _by_key: Mapping[TrackOffsetKey, int] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Reject duplicate identities so the in-memory and SQL keys agree."""
        if not isinstance(self.entries, tuple):
            raise TypeError("track offset entries must be a tuple")
        keys: set[TrackOffsetKey] = set()
        for entry in self.entries:
            if not isinstance(entry, TrackOffsetEntry):
                raise TypeError("track offset snapshots require TrackOffsetEntry values")
            if entry.key in keys:
                raise ValueError("track offset snapshot contains duplicate identities")
            keys.add(entry.key)
        object.__setattr__(
            self,
            "_by_key",
            MappingProxyType({entry.key: entry.offset_ms for entry in self.entries}),
        )

    def offset_for(self, key: TrackOffsetKey) -> int:
        """Return the correction for ``key``, or zero when it has not been tuned."""
        return self._by_key.get(key, 0)

    def as_mapping(self) -> Mapping[TrackOffsetKey, int]:
        """Return a detached immutable mapping for the display option boundary."""
        return self._by_key

    def with_offset(self, key: TrackOffsetKey, offset_ms: int) -> TrackOffsetSnapshot:
        """Return a snapshot with one correction inserted or replaced."""
        if not isinstance(key, TrackOffsetKey):
            raise TypeError("track offset updates require a TrackOffsetKey")
        return self.with_entry(TrackOffsetEntry(key, offset_ms))

    def with_entry(self, entry: TrackOffsetEntry) -> TrackOffsetSnapshot:
        """Return a snapshot with one validated correction inserted or replaced."""
        if not isinstance(entry, TrackOffsetEntry):
            raise TypeError("track offset snapshots require a TrackOffsetEntry")
        updated = [current for current in self.entries if current.key != entry.key]
        updated.append(entry)
        return TrackOffsetSnapshot(tuple(updated))


class TrackOffsetReader(Protocol):
    """Read-only capability used by the HUD to calculate the next correction."""

    def offset_for(self, key: TrackOffsetKey) -> int:
        """Return the current correction for one lyric timeline."""
        ...


class TrackOffsetKeyResolver:
    """Memoize one display document's correction identity across frame ticks."""

    def __init__(self) -> None:
        self._document: LyricsDocument | None = None
        self._track: TrackIdentity | None = None
        self._key: TrackOffsetKey | None = None

    def resolve(self, track: TrackIdentity | None, document: LyricsDocument | None) -> TrackOffsetKey | None:
        """Return the key for the current inputs, hashing a document only when they change."""
        if document is self._document and track == self._track:
            return self._key
        self._document = document
        self._track = track
        self._key = track_offset_key(track, document)
        return self._key


def track_offset_key(track: TrackIdentity | None, document: LyricsDocument | None) -> TrackOffsetKey | None:
    """Build the canonical correction identity for the currently displayed document."""
    if document is None or not document.lines:
        return None
    title = track.title if track is not None and track.title.strip() else document.title or ""
    artist = track.artist if track is not None and track.artist.strip() else document.artist or ""
    album = track.album if track is not None and track.album.strip() else document.album or ""
    duration_s = track.duration_s if track is not None and track.duration_s is not None else document.duration_s
    duration_s_normalized = _duration_seconds(duration_s)
    if not title.strip() and not artist.strip():
        return None
    return TrackOffsetKey(
        title,
        artist,
        album,
        duration_s_normalized,
        document.source_id,
        document.song_id,
        _lyrics_digest(document),
    )


def _identity_text(value: str, field_name: str, *, casefold: bool) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if len(normalized) > MAX_OFFSET_IDENTITY_TEXT:
        raise ValueError(f"{field_name} is too long")
    return normalized.casefold() if casefold else normalized


def _optional_identity_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = _identity_text(value, field_name, casefold=False)
    return normalized or None


def _duration_seconds(value: float | None) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or value < 0.0:
        return None
    return round(float(value))


def _lyrics_digest(document: LyricsDocument) -> str:
    """Hash source lyric content without persisting the lyric text in offset state."""
    payload = {
        "timing": document.timing.value if document.timing is not None else None,
        "language": document.language,
        "lines": [
            {
                "start": line.start,
                "end": line.end,
                "text": line.text,
                "translation": line.translation,
                "words": [
                    {"start": word.start, "end": word.end, "text": word.text}
                    for word in line.words
                ],
            }
            for line in document.lines
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


EMPTY_TRACK_OFFSETS = TrackOffsetSnapshot()


__all__ = [
    "EMPTY_TRACK_OFFSETS",
    "MAX_OFFSET_IDENTITY_TEXT",
    "TRACK_OFFSET_LIMIT_MS",
    "TRACK_OFFSET_STEP_MS",
    "TrackOffsetEntry",
    "TrackOffsetKey",
    "TrackOffsetKeyResolver",
    "TrackOffsetReader",
    "TrackOffsetSnapshot",
    "clamp_track_offset",
    "track_offset_key",
]
