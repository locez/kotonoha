"""Lyrics data model and defensive payload parsing.

The Cider probe (plugins/cider/lyrics) pushes a ``ProbePayload`` JSON object
over WebSocket. This module mirrors the relevant parts of that TypeScript type
(see plugins/cider/lyrics/src/probe/types.ts) as immutable dataclasses and
turns a raw dict into a :class:`LyricsSnapshot`.

Parsing is intentionally tolerant: unknown fields are ignored and malformed
values degrade to ``None``/empty rather than raising, so a single bad frame
never takes down the overlay.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LyricWord:
    start: float | None
    end: float | None
    text: str


@dataclass(frozen=True)
class LyricLine:
    index: int
    id: str
    start: float
    end: float
    text: str
    translation: str
    words: tuple[LyricWord, ...] = ()

    @property
    def has_word_timing(self) -> bool:
        return any(w.start is not None and w.end is not None for w in self.words)


@dataclass(frozen=True)
class LyricsSnapshot:
    found: bool = False
    provider: str = ""
    song_id: str | None = None
    timing: str | None = None
    language: str | None = None
    current_time: float | None = None
    current: LyricLine | None = None
    previous: LyricLine | None = None
    next: LyricLine | None = None
    around: tuple[LyricLine, ...] = ()
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration_s: float | None = None
    is_playing: bool = False
    error: str | None = None

    @property
    def word_karaoke(self) -> bool:
        """Whether per-word sweep should be used for the current line."""
        return self.timing == "Word" and self.current is not None and self.current.has_word_timing


EMPTY_SNAPSHOT = LyricsSnapshot()


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_positive_float(value: Any) -> float | None:
    parsed = _as_float(value)
    return parsed if parsed is not None and math.isfinite(parsed) and parsed > 0.0 else None


def _as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _parse_word(raw: Any) -> LyricWord | None:
    if not isinstance(raw, dict):
        return None
    return LyricWord(
        start=_as_float(raw.get("start")),
        end=_as_float(raw.get("end")),
        text=_as_str(raw.get("text")),
    )


def _parse_line(raw: Any) -> LyricLine | None:
    if not isinstance(raw, dict):
        return None
    words_raw = raw.get("words")
    words: tuple[LyricWord, ...] = ()
    if isinstance(words_raw, list):
        words = tuple(w for w in (_parse_word(item) for item in words_raw) if w is not None)
    return LyricLine(
        index=_as_int(raw.get("index"), -1),
        id=_as_str(raw.get("id")),
        start=_as_float(raw.get("start")) or 0.0,
        end=_as_float(raw.get("end")) or 0.0,
        text=_as_str(raw.get("text")),
        translation=_as_str(raw.get("translation")),
        words=words,
    )


def _parse_lines(raw: Any) -> tuple[LyricLine, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(line for line in (_parse_line(item) for item in raw) if line is not None)


def _now_playing(playback: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Pull track identity from playback.nowPlayingItem (attributes or flat)."""
    item = playback.get("nowPlayingItem")
    if not isinstance(item, dict):
        return None, None, None
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    title = _as_str(attrs.get("name")) or _as_str(item.get("title")) or None
    artist = _as_str(attrs.get("artistName")) or _as_str(item.get("artistName")) or None
    album = _as_str(attrs.get("albumName")) or _as_str(item.get("albumName")) or None
    return title, artist, album


def parse_payload(payload: Any) -> LyricsSnapshot:
    """Convert a raw probe payload dict into a :class:`LyricsSnapshot`.

    Returns :data:`EMPTY_SNAPSHOT` for anything that is not a usable dict.
    """
    if not isinstance(payload, dict):
        return EMPTY_SNAPSHOT

    lyrics = payload.get("lyrics") if isinstance(payload.get("lyrics"), dict) else {}
    playback = payload.get("playback") if isinstance(payload.get("playback"), dict) else {}

    title, artist, album = _now_playing(playback)
    is_playing = bool(playback.get("isPlaying"))

    return LyricsSnapshot(
        found=bool(lyrics.get("found")),
        provider=_as_str(lyrics.get("provider")),
        song_id=lyrics.get("songId") if isinstance(lyrics.get("songId"), str) else None,
        timing=lyrics.get("timing") if isinstance(lyrics.get("timing"), str) else None,
        language=lyrics.get("language") if isinstance(lyrics.get("language"), str) else None,
        current_time=_as_float(lyrics.get("currentTime")),
        current=_parse_line(lyrics.get("currentLine")),
        previous=_parse_line(lyrics.get("previousLine")),
        next=_parse_line(lyrics.get("nextLine")),
        around=_parse_lines(lyrics.get("aroundLines")),
        title=title,
        artist=artist,
        album=album,
        duration_s=_as_positive_float(playback.get("currentPlaybackDuration")),
        is_playing=is_playing,
        error=lyrics.get("error") if isinstance(lyrics.get("error"), str) else None,
    )


__all__ = [
    "LyricWord",
    "LyricLine",
    "LyricsSnapshot",
    "EMPTY_SNAPSHOT",
    "parse_payload",
]
