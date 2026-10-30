"""Normalize Apple/AMLL TTML lyrics using absolute media timestamps.

This lyric profile uses song positions on paragraphs and spans, including within
timed divs. It is not a subtitle layout engine: sequential containers, frame/tick
clocks and non-media time bases are refused. Secondary voices and romanization
are excluded from the single lead-vocal timeline; inline translations are kept.
The transformation is stateless; only the bounded XML builder owns parse state.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from xml.etree import ElementTree as ET

from .models import LyricLine, LyricWord
from .payload import MAX_DECOMPRESSED_BYTES

_TT = "http://www.w3.org/ns/ttml"
_ROLE = "{http://www.w3.org/ns/ttml#metadata}role"
_TIME_BASE = "{http://www.w3.org/ns/ttml#parameter}timeBase"
_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_CLOCK = re.compile(r"(?:(\d{1,3}):)?(\d{1,2}):([0-5]\d(?:\.\d{1,9})?)", re.ASCII)
_OFFSET = re.compile(r"(\d{1,9}(?:\.\d{1,9})?)(ms|h|m|s)", re.ASCII)
_WHITESPACE = re.compile(r"[ \t\r\n]+")
_SECONDARY_ROLES = frozenset({"x-roman", "x-romanization", "x-transliteration", "x-bg"})


class _BoundedTreeBuilder(ET.TreeBuilder):
    """Reject DTDs before expansion and cap nesting and total XML elements."""

    def __init__(self) -> None:
        super().__init__()
        self._depth: int = 0
        self._elements: int = 0

    def start(self, tag: str, attrs: dict[str, str]) -> ET.Element:
        """Enforce the tree budget before allocating the next element."""
        self._depth += 1
        self._elements += 1
        if self._depth > 32 or self._elements > 25000:
            raise ValueError("TTML exceeds the XML tree budget")
        return super().start(tag, attrs)

    def end(self, tag: str) -> ET.Element:
        """Release one nesting level after the parser closes its element."""
        self._depth -= 1
        return super().end(tag)

    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        """Forbid both internal entities and external document references."""
        raise ValueError("TTML must not contain a DTD")


@dataclass(frozen=True)
class _Span:
    """An absolute media interval; missing bounds may be inferred for a paragraph."""

    start: float | None
    end: float | None


@dataclass(frozen=True)
class _TextPart:
    """One mixed-content fragment with the whitespace policy of its XML owner."""

    word: LyricWord
    preserve: bool


def _time(value: str) -> float:
    """Decode the lyric profile's clocks and offsets, rejecting invalid numbers."""
    clock = _CLOCK.fullmatch(value.strip())
    offset = _OFFSET.fullmatch(value.strip())
    if clock is not None:
        hours = int(clock[1]) if clock[1] is not None else 0
        minutes = int(clock[2])
        if clock[1] is not None and minutes >= 60:
            raise ValueError("invalid TTML clock minutes")
        result = hours * 3600 + minutes * 60 + float(clock[3])
    elif offset is not None:
        result = float(offset[1]) * {"h": 3600, "m": 60, "s": 1, "ms": 0.001}[offset[2]]
    else:
        raise ValueError("unsupported TTML time expression")
    if not math.isfinite(result) or result > 7 * 24 * 3600:
        raise ValueError("TTML time exceeds the media timeline budget")
    return result


def _span(element: ET.Element) -> _Span:
    """Validate explicit times; duration is relative to begin, clocks are absolute."""
    raw_begin, raw_end, raw_duration = (element.get(key) for key in ("begin", "end", "dur"))
    begin = _time(raw_begin) if raw_begin is not None else None
    end = _time(raw_end) if raw_end is not None else None
    if raw_duration is not None:
        duration = _time(raw_duration)
        if begin is not None:
            duration_end = begin + duration
            end = min(end, duration_end) if end is not None else duration_end
    if begin is not None and end is not None and end <= begin:
        raise ValueError("TTML interval must have positive duration")
    return _Span(begin, end)


def _name(element: ET.Element) -> str:
    """Accept the TTML namespace and namespace-free lyric exports only."""
    prefix = f"{{{_TT}}}"
    return element.tag.removeprefix(prefix) if element.tag.startswith(prefix) else element.tag


def _space_mode(element: ET.Element, inherited: bool) -> bool:
    value = element.get(_SPACE)
    if value is None:
        return inherited
    if value not in {"preserve", "default"}:
        raise ValueError("invalid TTML whitespace policy")
    return value == "preserve"


def _text(value: str | None, preserve: bool) -> str:
    if value is None:
        return ""
    return value if preserve else _WHITESPACE.sub(" ", value)


def _segments(element: ET.Element, timing: _Span, preserve: bool) -> list[_TextPart]:
    """Keep mixed XML text in order without synthesizing word timing or spacing."""
    preserve = _space_mode(element, preserve)
    parts: list[_TextPart] = []
    if element.text:
        parts.append(_TextPart(LyricWord(timing.start, timing.end, _text(element.text, preserve)), preserve))
    for child in element:
        role = child.get(_ROLE, "")
        if _name(child) == "br":
            parts.append(_TextPart(LyricWord(timing.start, timing.end, "\n"), True))
        elif _name(child) == "span" and role not in _SECONDARY_ROLES and role != "x-translation":
            child_timing = timing
            if any(child.get(key) is not None for key in ("begin", "end", "dur")):
                child_timing = _span(child)
                if child_timing.start is None or child_timing.end is None:
                    raise ValueError("TTML word has incomplete timing")
                if timing.start is not None and timing.end is not None and (
                    child_timing.start < timing.start or child_timing.end > timing.end
                ):
                    raise ValueError("TTML nested word is outside its parent")
            parts.extend(_segments(child, child_timing, preserve))
        if child.tail:
            parts.append(_TextPart(LyricWord(timing.start, timing.end, _text(child.tail, preserve)), preserve))
    return parts


def _normalize_parts(parts: list[_TextPart]) -> tuple[LyricWord, ...]:
    """Trim layout indentation and collapse spaces across mixed text boundaries."""
    previous_space = True
    for index, part in enumerate(parts):
        text = part.word.text.lstrip(" ") if previous_space and not part.preserve else part.word.text
        if text:
            previous_space = text.endswith((" ", "\n"))
        parts[index] = replace(part, word=replace(part.word, text=text))
    for index in range(len(parts) - 1, -1, -1):
        part = parts[index]
        if part.preserve:
            break
        text = part.word.text.rstrip()
        parts[index] = replace(part, word=replace(part.word, text=text))
        if text:
            break
    return tuple(part.word for part in parts if part.word.text)


def _translations(element: ET.Element, preserve: bool) -> list[str]:
    """Collect lead translations while excluding secondary voices and their text."""
    preserve = _space_mode(element, preserve)
    if element.get(_ROLE, "") in _SECONDARY_ROLES:
        return []
    if element.get(_ROLE) == "x-translation":
        return [_text("".join(element.itertext()), preserve).strip()]
    return [text for child in element for text in _translations(child, preserve)]


def _line(element: ET.Element, preserve: bool) -> LyricLine | None:
    """Project a lead paragraph, preserving translation outside karaoke geometry."""
    preserve = _space_mode(element, preserve)
    span = _span(element)
    words = _normalize_parts(_segments(element, _Span(None, None), preserve))
    text = "".join(word.text for word in words)
    if not text.strip():
        return None
    timed = tuple(word for word in words if word.start is not None and word.end is not None)
    start = span.start
    end = span.end
    if start is None:
        start = min((word.start for word in timed if word.start is not None), default=None)
    if end is None:
        end = max((word.end for word in timed if word.end is not None), default=None)
    if start is None or end is None or end <= start:
        return None
    if any(
        word.start is not None and word.end is not None and (word.start < start or word.end > end)
        for word in timed
    ):
        raise ValueError("TTML word is outside its lyric line")
    translations = _translations(element, preserve)
    return LyricLine(0, "", start, end, text, "\n".join(translations), words if timed else ())


def _lines(element: ET.Element, preserve: bool = False) -> list[LyricLine]:
    """Walk only lyric containers, avoiding metadata paragraphs and other XML."""
    preserve = _space_mode(element, preserve)
    if _name(element) == "p":
        if element.get(_ROLE, "") in _SECONDARY_ROLES | {"x-translation"}:
            return []
        line = _line(element, preserve)
        return [] if line is None else [line]
    lines: list[LyricLine] = []
    for child in element:
        if _name(child) in {"body", "div", "p"}:
            lines.extend(_lines(child, preserve))
    return lines


def parse_ttml(text: str | bytes) -> list[LyricLine]:
    """Return canonical lyrics, or an empty list for invalid/unsupported TTML.

    Bytes honor the XML encoding declaration (including UTF-16). Input, tree,
    line and word budgets are enforced before returning any partial document.
    DTDs are forbidden before entity expansion; XML never accesses files or URLs.
    """
    try:
        size = len(text.encode("utf-8")) if isinstance(text, str) else len(text)
        if size > MAX_DECOMPRESSED_BYTES:
            return []
        root = ET.fromstring(text, parser=ET.XMLParser(target=_BoundedTreeBuilder()))
        if _name(root) != "tt" or root.get(_TIME_BASE, "media") != "media":
            return []
        if any(element.get("timeContainer", "par") != "par" for element in root.iter()):
            return []
        lines = _lines(root)
        if len(lines) > 5000 or any(len(line.words) > 4096 for line in lines):
            return []
        lines.sort(key=lambda line: line.start)
        return [replace(line, index=index, id=f"L{index}") for index, line in enumerate(lines)]
    except (ET.ParseError, ValueError, LookupError):
        return []


__all__ = ["parse_ttml"]
