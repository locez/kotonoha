"""Turn a full lyric line list + playback position into a LyricsSnapshot.

Used by the MPRIS provider: it holds the whole song's lines and, as the polled
Position advances, picks the current/previous/next lines. Pure functions, unit
tested; the provider only emits a new snapshot when the current line index
changes (the clock tick handles smooth progress within a line).
"""

from __future__ import annotations

from dataclasses import replace
from statistics import median

from ..model import Interlude, LyricLine, LyricsSnapshot

# How far past the song's own pace a span must run before the music after a line
# counts as an interlude rather than a long-held phrase. Measured over four songs:
# every real break ran past 2.5x the median span (35.3s against 6.66s, 35.9s
# against 4.52s, 20.7s against 6.76s) while a continuously sung track produced no
# span over 2.1x and so is left alone.
_INTERLUDE_FACTOR = 2.5
# And an interlude is long in its own right, not only relative to a quick song. A
# dense lyric sheet has a small median — 走马 sits at 3.15s — so the ratio alone
# called a 7.9s breath an interlude and blanked the panel mid-verse. Measured over
# nine songs, every real break ran 13.1s or longer while every held line or breath
# stopped at 11.7s.
_INTERLUDE_FLOOR_S = 12.0
# How far past the song's own pace a line may sweep before it has plainly finished.
# An LRC gives every line the next one's start, so a line before a pause is swept
# across the whole pause and creeps on long after it was sung. Measured on songs
# that do carry word timings, a line sings for about the median span — 0.92 and 0.95
# of it — and the longest ran to 2.01, so a line is never cut short here.
_SWEEP_CAP_FACTOR = 2.0


def find_current_index(lines: list[LyricLine], position: float) -> int:
    """Index of the last line whose start <= position, or -1 if before the first."""
    index = -1
    for i, line in enumerate(lines):
        if line.start <= position:
            index = i
        else:
            break
    return index


def _typical_span(lines: list[LyricLine]) -> float:
    """The song's own median line-to-line span, the yardstick a gap is judged against."""
    spans = [lines[i + 1].start - lines[i].start for i in range(len(lines) - 1)]
    usable = [span for span in spans if span > 0.0]
    return median(usable) if usable else 0.0


def in_interlude(
    lines: list[LyricLine], index: int, position: float, duration_s: float | None = None
) -> bool:
    """Whether the position sits in music after ``index`` was sung, not inside it.

    An LRC carries no end times, so the parser gives every line the next line's
    start; an instrumental break is absorbed into the line before it, which then
    sweeps for half a minute and reads as though it were still being sung. The
    break stands out against the song's own pace, so no fixed duration is needed.
    The final line is bounded by its own end instead, which is what kept it on
    screen until the track stopped.
    """
    if not 0 <= index < len(lines):
        return False
    line = lines[index]
    if index + 1 == len(lines):
        # Only when the track says where it ends. Without that there is nothing to
        # count towards, and a marker that cannot move is worse than the last line
        # staying put: it reads as a wait that never finishes.
        return duration_s is not None and duration_s > line.end and position > line.end
    span = lines[index + 1].start - line.start
    typical = _typical_span(lines)
    if typical <= 0.0 or span <= _INTERLUDE_FACTOR * typical or span < _INTERLUDE_FLOOR_S:
        return False
    return position > line.start + typical


def interlude_at(
    lines: list[LyricLine], index: int, position: float, duration_s: float | None = None
) -> Interlude | None:
    """The stretch of music the position sits in, or ``None`` while a line is sung.

    Covers the run-up to the first line as well as a break between two: both are
    music with nothing to show, and the overlay treats them the same.
    """
    if not lines:
        return None
    if index < 0:
        return Interlude(0.0, lines[0].start) if position < lines[0].start else None
    if not in_interlude(lines, index, position, duration_s):
        return None
    line = lines[index]
    if index + 1 == len(lines):
        # The run-out after the last word, and only when the track says where it ends.
        if duration_s is None or duration_s <= line.end:
            return None
        return Interlude(line.end, duration_s)
    return Interlude(line.start + _typical_span(lines), lines[index + 1].start)


def swept_line(line: LyricLine, typical: float) -> LyricLine:
    """The line as the sweep should treat it: ending when it is plainly sung.

    Word timings say exactly when the words stop; without them the song's own pace
    is the yardstick. Either way the line stays on screen — only the sweep stops.
    """
    if line.has_word_timing:
        sung = max((w.end for w in line.words if w.end is not None), default=None)
        return line if sung is None or sung >= line.end else replace(line, end=sung)
    if typical <= 0.0:
        return line
    capped = line.start + _SWEEP_CAP_FACTOR * typical
    return line if capped >= line.end else replace(line, end=capped)


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
    duration_s: float | None = None,
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
    # During an interlude the line that just finished is the previous one, not the
    # current one, so the surrounding lines still come from idx.
    quiet = in_interlude(lines, idx, position, duration_s)
    current = None if quiet else (lines[idx] if 0 <= idx < len(lines) else None)
    if current is not None:
        current = swept_line(current, _typical_span(lines))
    previous = lines[idx] if quiet else (lines[idx - 1] if idx - 1 >= 0 else None)
    interlude = interlude_at(lines, idx, position, duration_s)
    nxt = lines[idx + 1] if 0 <= idx + 1 < len(lines) else None
    around = tuple(lines[max(0, idx - 2) : idx + 3])
    return LyricsSnapshot(
        found=True,
        provider=provider,
        song_id=song_id,
        timing=song_timing(lines),
        current_time=position,
        duration_s=duration_s,
        interlude=interlude,
        current=current,
        previous=previous,
        next=nxt,
        around=around,
        title=title,
        artist=artist,
        is_playing=is_playing,
    )
