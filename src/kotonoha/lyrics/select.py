"""Turn a full lyric line list + playback position into a LyricsSnapshot.

Used by the MPRIS provider: it holds the whole song's lines and, as the polled
Position advances, picks the current/previous/next lines. Pure functions, unit
tested; the provider only emits a new snapshot when the current line index
changes (the clock tick handles smooth progress within a line).
"""

from __future__ import annotations

from ..model import LyricLine, LyricsSnapshot


def find_current_index(lines: list[LyricLine], position: float) -> int:
    """Index of the last line whose start <= position, or -1 if before the first."""
    index = -1
    for i, line in enumerate(lines):
        if line.start <= position:
            index = i
        else:
            break
    return index


def song_timing(lines: list[LyricLine]) -> str:
    return "Word" if any(line.has_word_timing for line in lines) else "Line"


def build_snapshot(
    lines: list[LyricLine],
    position: float,
    *,
    provider: str,
    song_id: str | None,
    title: str | None,
    artist: str | None,
    is_playing: bool,
) -> LyricsSnapshot:
    if not lines:
        return LyricsSnapshot(
            found=False,
            provider=provider,
            song_id=song_id,
            title=title,
            artist=artist,
            is_playing=is_playing,
            current_time=position,
        )
    idx = find_current_index(lines, position)
    current = lines[idx] if 0 <= idx < len(lines) else None
    previous = lines[idx - 1] if idx - 1 >= 0 else None
    nxt = lines[idx + 1] if 0 <= idx + 1 < len(lines) else None
    around = tuple(lines[max(0, idx - 2) : idx + 3])
    return LyricsSnapshot(
        found=True,
        provider=provider,
        song_id=song_id,
        timing=song_timing(lines),
        current_time=position,
        current=current,
        previous=previous,
        next=nxt,
        around=around,
        title=title,
        artist=artist,
        is_playing=is_playing,
    )
