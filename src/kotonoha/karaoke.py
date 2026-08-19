"""Pure karaoke timing math.

Given the media playback time, work out how much of a line (or each word) has
been "sung", so the renderer can sweep a highlight across the text. Kept free of
Qt so it is trivially unit-testable.
"""

from __future__ import annotations

import math

from .model import Interlude, LyricLine, LyricWord


def _clamp01(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return value


def line_fill_fraction(start: float, end: float, t: float) -> float:
    """Fraction [0,1] of a line spanning [start, end] that is sung at time t."""
    if end <= start:
        return 1.0 if t >= end else 0.0
    return _clamp01((t - start) / (end - start))


def word_fill_fraction(word: LyricWord, t: float) -> float:
    """Fraction [0,1] of a single word that is sung at time t.

    Words without timing are treated as fully sung once we are at/after them,
    which keeps untimed segments from blocking the sweep.
    """
    if word.start is None or word.end is None:
        return 0.0
    return line_fill_fraction(word.start, word.end, t)


def word_fill_fractions(words: tuple[LyricWord, ...], t: float) -> tuple[float, ...]:
    return tuple(word_fill_fraction(w, t) for w in words)


def active_word_index(words: tuple[LyricWord, ...], t: float) -> int:
    """Index of the word currently being sung, or -1 if none/blank.

    "Currently" = the first word whose fill is in (0, 1). If we are past every
    timed word, returns the last timed word's index; before all, returns -1.
    """
    last_started = -1
    for i, w in enumerate(words):
        frac = word_fill_fraction(w, t)
        if 0.0 < frac < 1.0:
            return i
        if frac >= 1.0:
            last_started = i
    return last_started


def line_progress(line: LyricLine, t: float) -> float:
    """Overall progress through a line, preferring word timing when available.

    Called every frame, so it locates the first and last fully-timed words directly
    instead of materialising a filtered list of them.
    """
    if line.has_word_timing and line.words:
        timed = (w for w in line.words if w.start is not None and w.end is not None)
        first = next(timed, None)
        if first is not None:
            last = next((w for w in reversed(line.words) if w.start is not None and w.end is not None), first)
            return line_fill_fraction(first.start or line.start, last.end or line.end, t)
    return line_fill_fraction(line.start, line.end, t)


# The marker is handed to the sweep, so the accent runs across it as the wait does:
# the dots are what the colour moves over, not a counter of their own.
_INTERLUDE_DOTS = "\u25cf\u2003\u25cf\u2003\u25cf"  # em spaces: the dots need air between them
_STILL_NOTE = "\u266a"


def interlude_text(interlude: Interlude, position: float, *, style: str, countdown: str) -> str:
    """What stands in for a lyric while the music has no words.

    ``style`` is "dots" (a row the sweep runs across) or "symbol" (a still note);
    ``countdown``
    adds "percent" or "seconds" remaining, or "off" for neither. An unknown value
    of either falls back to the default rather than showing nothing, since this is
    the only thing on screen at the time.
    """
    indicator = _STILL_NOTE if style == "symbol" else _INTERLUDE_DOTS
    if countdown == "percent":
        return f"{indicator}\u2003\u2003{round(interlude.progress(position) * 100)}%"
    if countdown == "seconds":
        # Rounded up, so the last whole second still reads as 1 rather than 0.
        return f"{indicator}\u2003\u2003{max(0, math.ceil(interlude.end - position))}s"
    return indicator
