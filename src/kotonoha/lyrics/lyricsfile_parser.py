"""Read bounded Lyricsfile 1.0 YAML into canonical lyric timing.

Format: https://github.com/tranxuanthang/lyricsfile/blob/main/SPECIFICATION.md
The draft leaves end-time inference to readers. Missing word ends use the next
word start or line end. Missing line ends use complete word ends, the next later
line, track duration, or five seconds after the last start, in that order.
Explicit ends, overlaps, whitespace, and the original cached YAML are preserved.
Nonzero offset_ms is unsupported because its semantics are not yet specified.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass

from yaml import SafeLoader, YAMLError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node

from .models import LyricLine, LyricWord
from .payload import MAX_DECOMPRESSED_BYTES

_MAX_TIME_MS = 7 * 24 * 3600 * 1000
_CORE_TAGS = frozenset(f"tag:yaml.org,2002:{name}" for name in ("map", "seq", "str", "int", "bool", "null"))


class LyricsFileError(ValueError):
    """The YAML document is unsafe, malformed, or outside the supported profile."""


class _BoundedLoader(SafeLoader):
    """Own YAML parse budgets and reject aliases, custom types, and duplicate keys."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._depth: int = 0
        self._nodes: int = 0

    def compose_node(self, parent: Node | None, index: Node | int | None) -> Node:
        """Bound the tree before construction or recursive alias expansion."""
        if self.check_event(AliasEvent):
            raise LyricsFileError("Lyricsfile aliases are unsupported")
        self._depth += 1
        self._nodes += 1
        if self._depth > 32 or self._nodes > 50000:
            raise LyricsFileError("Lyricsfile exceeds the YAML tree budget")
        try:
            node = super().compose_node(parent, index)
            if node.tag not in _CORE_TAGS:
                raise LyricsFileError("Lyricsfile contains an unsupported YAML type")
            return node
        finally:
            self._depth -= 1

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[str, object]:
        """Require unambiguous string keys before decoding any document fields."""
        result: dict[str, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise LyricsFileError("Lyricsfile mapping keys must be strings")
            if key in result:
                raise LyricsFileError("Lyricsfile contains duplicate keys")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


@dataclass(frozen=True)
class _Word:
    """Validated external word timing before omitted ends are inferred."""

    text: str
    start: int
    end: int | None


@dataclass(frozen=True)
class _Line:
    """Validated external line retaining the source's exact text and word order."""

    text: str
    start: int
    end: int | None
    words: tuple[_Word, ...]


class LyricsFileParser:
    """Own validation and end-time inference for the Lyricsfile 1.0 boundary."""

    def parse(self, text: str) -> tuple[LyricLine, ...]:
        """Return timed lines, or raise LyricsFileError without a partial result.

        Plain-only and instrumental documents return no timed lines. Unknown
        fields with safe core YAML types are tolerated for draft extensions.
        """
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise LyricsFileError("Lyricsfile must contain valid UTF-8 text") from exc
        if size > MAX_DECOMPRESSED_BYTES:
            raise LyricsFileError("Lyricsfile exceeds the byte limit")
        try:
            loader = _BoundedLoader(text)
            try:
                raw: object = loader.get_single_data()
            finally:
                loader.dispose()
        except LyricsFileError:
            raise
        except (YAMLError, ValueError) as exc:
            raise LyricsFileError("Lyricsfile is not valid safe YAML") from exc
        root = _mapping(raw)
        if root.get("version") != "1.0":
            raise LyricsFileError("unsupported Lyricsfile version")
        metadata = _mapping(root.get("metadata"))
        _text(metadata.get("title"))
        _text(metadata.get("artist"))
        for name in ("album", "language"):
            if name in metadata:
                _text(metadata[name])
        duration = _optional_time(metadata, "duration_ms")
        if "offset_ms" in metadata and (type(metadata["offset_ms"]) is not int or metadata["offset_ms"] != 0):
            raise LyricsFileError("Lyricsfile offset_ms semantics are unsupported")
        instrumental = metadata.get("instrumental", False)
        if not isinstance(instrumental, bool):
            raise LyricsFileError("Lyricsfile instrumental must be boolean")
        plain = _text(root["plain"]) if "plain" in root else ""
        entries = _sequence(root["lines"], 5000) if "lines" in root else []
        if instrumental and (entries or plain):
            raise LyricsFileError("instrumental Lyricsfile contains lyrics")
        lines = sorted((self._line(entry) for entry in entries), key=lambda line: line.start)
        starts = tuple(line.start for line in lines)
        return tuple(
            self._materialize(line, index, starts, duration)
            for index, line in enumerate(lines)
            if line.text.strip()
        )

    def _line(self, raw: object) -> _Line:
        """Validate word order without changing source whitespace or explicit ends."""
        value = _mapping(raw)
        text = _text(value.get("text"))
        start, end = _span(value)
        words: list[_Word] = []
        entries = _sequence(value["words"], 4096) if "words" in value else []
        previous = start
        for entry in entries:
            word = _mapping(entry)
            word_start, word_end = _span(word)
            if word_start < previous or (end is not None and (
                word_start > end or word_end is not None and word_end > end
            )):
                raise LyricsFileError("Lyricsfile word timing is unordered or outside its line")
            words.append(_Word(_text(word.get("text")), word_start, word_end))
            previous = word_start
        if words and "".join(word.text for word in words) != text:
            raise LyricsFileError("Lyricsfile words do not reconstruct the line text")
        return _Line(text, start, end, tuple(words))

    def _materialize(self, line: _Line, index: int, starts: tuple[int, ...], duration: int | None) -> LyricLine:
        """Infer omitted ends only in the display model, retaining the source payload."""
        end = line.end
        if end is None:
            last_start = max((word.start for word in line.words), default=line.start)
            explicit_ends = [word.end for word in line.words if word.end is not None]
            if line.words and line.words[-1].end is not None:
                end = max(explicit_ends)
            else:
                following = bisect_right(starts, last_start)
                end = starts[following] if following < len(starts) else None
                if end is None:
                    end = duration if duration is not None and duration > last_start else last_start + 5000
                end = max(end, *explicit_ends) if explicit_ends else end
        words: list[LyricWord] = []
        for word_index, word in enumerate(line.words):
            word_end = word.end
            if word_end is None:
                word_end = line.words[word_index + 1].start if word_index + 1 < len(line.words) else end
            words.append(LyricWord(word.start / 1000.0, word_end / 1000.0, word.text))
        return LyricLine(index, f"L{index}", line.start / 1000.0, end / 1000.0, line.text, "", tuple(words))


def _mapping(value: object) -> Mapping[str, object]:
    """Narrow untrusted YAML into a string-keyed boundary object."""
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise LyricsFileError("Lyricsfile expected a mapping")
    return value


def _sequence(value: object, limit: int) -> list[object]:
    """Bound a source collection before normalizing its members."""
    if not isinstance(value, list) or len(value) > limit:
        raise LyricsFileError("Lyricsfile expected a bounded sequence")
    return value


def _text(value: object) -> str:
    """Preserve spacing while rejecting escaped surrogate code points before Qt."""
    if not isinstance(value, str):
        raise LyricsFileError("Lyricsfile expected text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LyricsFileError("Lyricsfile text contains an invalid Unicode scalar") from exc
    return value


def _time(value: object) -> int:
    """Reject booleans, fractions, negative values, and unbounded timestamps."""
    if type(value) is not int or not 0 <= value <= _MAX_TIME_MS:
        raise LyricsFileError("Lyricsfile timestamp must be bounded nonnegative integer milliseconds")
    return value


def _optional_time(value: Mapping[str, object], field: str) -> int | None:
    """Distinguish an omitted optional field from a malformed explicit null."""
    return _time(value[field]) if field in value else None


def _span(value: Mapping[str, object]) -> tuple[int, int | None]:
    """Validate optional end ordering while preserving zero-length intervals."""
    start = _time(value.get("start_ms"))
    end = _optional_time(value, "end_ms")
    if end is not None and end < start:
        raise LyricsFileError("Lyricsfile end precedes its start")
    return start, end
