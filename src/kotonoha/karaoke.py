"""Pure karaoke timing math.

Given the media playback time, work out how much of a line (or each word) has
been "sung", so the renderer can sweep a highlight across the text. Kept free of
Qt so it is trivially unit-testable.
"""

from __future__ import annotations

from .model import LyricLine, LyricWord


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
