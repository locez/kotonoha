"""Cached Qt shaping and geometry for wrapped karaoke text."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QFont, QFontMetrics, QTextLayout, QTextLine, QTextOption

from ...lyrics.models import LyricLine


@dataclass(frozen=True)
class TextRow:
    """One shaped row and its distance along the complete lyric."""

    line: QTextLine
    offset: float
    width: float
    top: float


class WrappedTextLayout:
    """Own shaped rows and map timed words onto their cumulative visual advance."""

    def __init__(self, lyric: LyricLine, font: QFont, width: int) -> None:
        """Shape one lyric at a bounded width, retaining the Qt layout owner."""
        self.layout: QTextLayout = QTextLayout(lyric.text, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.layout.setTextOption(option)
        self.rows: list[TextRow] = []
        self.width: float = float(width)
        self.height: float = 0.0
        self.advance: float = 0.0
        self.word_offsets: list[float] = []
        self.word_widths: list[float] = []
        self.layout.beginLayout()
        while True:
            line = self.layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            row_width = line.horizontalAdvance()
            self.rows.append(TextRow(line, self.advance, row_width, self.height))
            self.advance += row_width
            self.height += line.height()
        self.layout.endLayout()
        cursor = 0
        for word in lyric.words:
            found = lyric.text.find(word.text, cursor) if word.text else cursor
            if found < 0:
                found = cursor
            end = min(len(lyric.text), found + len(word.text))
            start_distance = self.distance(found)
            self.word_offsets.append(start_distance)
            self.word_widths.append(max(0.0, self.distance(end) - start_distance))
            cursor = end

    def distance(self, index: int) -> float:
        """Map a Python text offset to cumulative shaped advance (Qt uses UTF-16)."""
        qt_index = len(self.layout.text()[:index].encode("utf-16-le")) // 2
        for row in self.rows:
            end = row.line.textStart() + row.line.textLength()
            if qt_index < end:
                x, _ = row.line.cursorToX(qt_index)
                return row.offset + x
        return self.advance


def measure_word_offsets(line: LyricLine | None, metrics: QFontMetrics) -> list[float]:
    """Return each word's x offset, measured from the text as it is drawn.

    The sweep used to assume one space between every pair of words. The KRC and
    YRC parsers build the line by concatenating word texts with no separator, so
    on a CJK line the sweep gained a space width per word and ran ahead of the
    characters: nine characters drifted 24px past a 108px line. Locating each
    word in the rendered string instead is right for a separator of any width,
    including none.
    """
    if line is None or not line.words:
        return []
    text = line.text
    offsets: list[float] = []
    cursor = 0
    for word in line.words:
        found = text.find(word.text, cursor) if word.text else cursor
        if found < 0:
            # The words and the drawn text disagree — a converted script, say.
            # Fall back to laying them out end to end, which is what the parsers
            # produce and is closer than assuming separators that are not there.
            found = cursor
        offsets.append(metrics.horizontalAdvance(text[:found]))
        cursor = found + len(word.text)
    return offsets
