"""Parse LRC (including Enhanced LRC) lyrics and merge a translation track.

Used as the fallback when a song has no word-timed (YRC) lyrics, and to attach
Netease ``tlyric`` (also LRC) onto the main lines by timestamp. Enhanced LRC
inline timestamps become the optional word spans on each canonical line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import LyricLine, LyricWord
from .translation import TranslationMerger

# [mm:ss], [mm:ss.xx] or [mm:ss.xxx]; a line may carry several time tags.
_TIME = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
# Enhanced LRC word timestamps use the same clock, with angle brackets.
_WORD_TIME = re.compile(r"<(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?>")
# The standard shift tag, in milliseconds and signed. Per the format's own
# wording a "+" value causes the lyrics to appear sooner, so it is subtracted
# from each timestamp rather than added. A sidecar written against a different
# rip is commonly a second or two out without it.
_OFFSET = re.compile(r"(?i)^\s*\[offset:\s*([+-]?\d{1,6})\s*\]\s*$", re.MULTILINE)
_MAX_OFFSET_S = 60.0


def _offset_seconds(text: str) -> float:
    matches = _OFFSET.findall(text)
    if not matches:
        return 0.0
    seconds = int(matches[-1]) / 1000.0  # the last tag wins, as players do
    # A tag far outside plausible correction is junk, not an instruction.
    return seconds if abs(seconds) <= _MAX_OFFSET_S else 0.0


#: More timed lines than any song has. The byte budget upstream still allows a
#: response of tens of thousands of valid tags, and each one becomes an object the
#: overlay holds and the cache stores; a lyric sheet runs to a few hundred.
MAX_LINES = 5000


@dataclass(frozen=True, slots=True)
class _InlineSegment:
    """One text segment introduced by an optional Enhanced LRC timestamp."""

    start: float | None
    text: str


@dataclass(frozen=True, slots=True)
class _LineEntry:
    """One line occurrence before line ends and word ends are materialized."""

    start: float
    text: str
    segments: tuple[_InlineSegment, ...] = ()


def _timestamp_seconds(match: re.Match[str], offset: float) -> float:
    """Convert one LRC timestamp match to a non-negative adjusted position."""
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    fraction = match.group(3) or ""
    millis = int((fraction + "000")[:3]) if fraction else 0
    return max(0.0, minutes * 60 + seconds + millis / 1000.0 - offset)


def _trim_segment_boundaries(segments: list[_InlineSegment]) -> tuple[_InlineSegment, ...]:
    """Trim display-only whitespace at the outer edges without losing markers."""
    normalized = list(segments)
    has_content = False
    for index, segment in enumerate(normalized):
        if has_content:
            continue
        text = segment.text.lstrip()
        normalized[index] = _InlineSegment(segment.start, text)
        has_content = bool(text)

    if not has_content:
        return tuple(normalized)

    for index in range(len(normalized) - 1, -1, -1):
        segment = normalized[index]
        text = segment.text.rstrip()
        normalized[index] = _InlineSegment(segment.start, text)
        if text:
            break
    return tuple(normalized)


def _inline_segments(content: str, offset: float) -> tuple[_InlineSegment, ...] | None:
    """Parse inline timestamps, retaining empty markers as timing boundaries."""
    markers = list(_WORD_TIME.finditer(content))
    if not markers:
        return None

    segments: list[_InlineSegment] = []
    prefix = content[: markers[0].start()]
    if prefix.strip():
        segments.append(_InlineSegment(None, prefix))
    for index, marker in enumerate(markers):
        next_start = markers[index + 1].start() if index + 1 < len(markers) else len(content)
        segments.append(
            _InlineSegment(
                _timestamp_seconds(marker, offset),
                content[marker.end() : next_start],
            )
        )

    normalized = _trim_segment_boundaries(segments)
    return normalized if any(segment.text.strip() for segment in normalized) else ()


def _parse_line_entries(raw: str, offset: float) -> tuple[_LineEntry, ...]:
    """Parse one physical LRC line into one or more timestamped occurrences."""
    tags = list(_TIME.finditer(raw))
    if not tags:
        return ()
    content = raw[tags[-1].end() :].strip()
    if not content:
        return ()

    segments = _inline_segments(content, offset)
    if segments is None:
        text = content
        word_segments: tuple[_InlineSegment, ...] = ()
    else:
        if not segments:
            return ()
        text = "".join(segment.text for segment in segments)
        word_segments = segments

    return tuple(
        _LineEntry(_timestamp_seconds(tag, offset), text, word_segments)
        for tag in tags
    )


def _materialize_words(segments: tuple[_InlineSegment, ...], line_end: float) -> tuple[LyricWord, ...]:
    """Turn inline starts into complete word spans using the next marker or line end."""
    words: list[LyricWord] = []
    for index, segment in enumerate(segments):
        if not segment.text:
            continue
        if segment.start is None:
            words.append(LyricWord(None, None, segment.text))
            continue

        next_start = line_end
        if index + 1 < len(segments):
            following = segments[index + 1].start
            if following is not None:
                next_start = following
        end = max(segment.start, min(line_end, next_start))
        words.append(LyricWord(segment.start, end, segment.text))
    return tuple(words)


def parse_lrc(text: str) -> list[LyricLine]:
    """Return timed lines from standard or Enhanced LRC input."""
    offset = _offset_seconds(text)
    entries: list[_LineEntry] = []
    for raw in text.splitlines():
        if len(entries) >= MAX_LINES:
            break
        line_entries = _parse_line_entries(raw, offset)
        entries.extend(line_entries[: MAX_LINES - len(entries)])

    entries.sort(key=lambda entry: entry.start)
    out: list[LyricLine] = []
    for i, entry in enumerate(entries):
        end = entries[i + 1].start if i + 1 < len(entries) else entry.start + 5.0
        out.append(
            LyricLine(
                index=i,
                id=f"L{i}",
                start=entry.start,
                end=end,
                text=entry.text,
                translation="",
                words=_materialize_words(entry.segments, end),
            )
        )
    return out


def merge_translation(base: list[LyricLine], translation: list[LyricLine], tolerance: float = 0.4) -> list[LyricLine]:
    """Compatibility wrapper for timestamp alignment."""
    return list(TranslationMerger(tolerance).merge_by_timestamp(base, translation))
