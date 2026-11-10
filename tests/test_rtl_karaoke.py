"""Reading-direction contracts exercised through the rendered lyric widget."""

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage
from PyQt6.QtWidgets import QApplication

from kotonoha.config import PanelOverflowMode
from kotonoha.display.models import LineProgress, WordProgress
from kotonoha.lyrics.models import LyricLine, LyricWord
from kotonoha.ui.overlay.karaoke_label import KaraokeLabel
from kotonoha.ui.overlay.text_layout import WrappedTextLayout, measure_word_offsets


@dataclass(frozen=True)
class DirectionCase:
    """Public text inputs with their expected paragraph sweep direction."""

    text: str
    rtl: bool


DIRECTION_CASES = (
    DirectionCase("وحدن بيبقوا متل زهر البيلسان", True),  # Issue #113, Fairuz — Wahdon.
    DirectionCase("  ♪ 123 (مَرْحَبًا بالعالم)", True),
    DirectionCase("۱۲۳ سلام دنیا", True),
    DirectionCase("שלום עולם", True),
    DirectionCase("مرحبا hello 123", True),
    DirectionCase("hello مرحبا 123", False),
    DirectionCase("今天 123 مرحبا", False),
    DirectionCase("123 ♪ 456", False),
    DirectionCase("\u2066hello\u2069 مرحبا", True),
    DirectionCase("\u2067مرحبا\u2069 hello", False),
)


@pytest.fixture
def label(qapp: QApplication) -> Iterator[KaraokeLabel]:
    """Isolate sung pixels from the unsung text and shadow."""
    widget = KaraokeLabel()
    font = QFont("DejaVu Sans")
    font.setPixelSize(36)
    widget.set_style(font, "#ff0000", "#ff0000", "#ff0000", QColor("#0000ff"), QColor(0, 0, 0, 0))
    widget.set_effects(glow=False, word_pop=False, intensity="subtle", animate=False)
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def lyric(text: str, words: tuple[LyricWord, ...] = ()) -> LyricLine:
    """Build a source-independent line with stable timing and identity."""
    return LyricLine(0, "line", 0.0, 10.0, text, "", words)


def sung_pixels(image: QImage, *, top: int = 0, bottom: int | None = None) -> list[tuple[int, int]]:
    """Locate accent pixels without assuming a font's individual glyph shapes."""
    return [
        (x, y)
        for y in range(top, image.height() if bottom is None else bottom)
        for x in range(image.width())
        if image.pixelColor(x, y).red() > image.pixelColor(x, y).blue() + 50
    ]


@pytest.mark.parametrize("case", DIRECTION_CASES, ids=lambda case: case.text)
def test_line_sweep_follows_first_strong_character(label: KaraokeLabel, case: DirectionCase) -> None:
    """Punctuation and numbers must not turn Arabic into an LTR lyric."""
    label.set_line(lyric(case.text), False)
    label.resize(label.sizeHint())
    label.set_progress(LineProgress("line", 0.25), None)
    image = label.grab().toImage()
    pixels = sung_pixels(image)
    assert pixels
    assert all((x > image.width() / 2) if case.rtl else (x < image.width() / 2) for x, _ in pixels)


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("glow", [False, True])
def test_arabic_word_highlight_and_glow_start_on_the_right(
    label: KaraokeLabel, wrapped: bool, glow: bool,
) -> None:
    """Word progress and its cached halo must share the line's reading direction."""
    text = "مرحبا عالم"
    label.set_max_width(400)
    label.set_overflow_mode(PanelOverflowMode.WRAP if wrapped else PanelOverflowMode.SCROLL)
    label.set_effects(glow=glow, word_pop=True, intensity="expressive", animate=False)
    label.set_line(lyric(text, (LyricWord(0.0, 5.0, "مرحبا"), LyricWord(5.0, 10.0, "عالم"))), True)
    label.resize(label.sizeHint())
    label.set_progress(None, WordProgress("line", (0.4, 0.0), 0))
    image = label.grab().toImage()
    pixels = sung_pixels(image)
    assert pixels
    assert all(x > image.width() / 2 for x, _ in pixels)
    label.set_progress(None, WordProgress("line", (0.0, 0.0), -1))
    assert not sung_pixels(label.grab().toImage())


@pytest.mark.parametrize("word_timed", [False, True])
def test_arabic_wrapped_sweep_restarts_at_right_of_each_row(label: KaraokeLabel, word_timed: bool) -> None:
    """Reading continues top to bottom, with a right-to-left sweep in every row."""
    text = "مرحبا مرحبا مرحبا مرحبا"
    words = (LyricWord(0.0, 10.0, text),) if word_timed else ()
    label.set_max_width(100)
    label.set_overflow_mode(PanelOverflowMode.WRAP)
    label.set_line(lyric(text, words), word_timed)
    label.resize(label.sizeHint())
    label.set_progress(LineProgress("line", 0.05), WordProgress("line", (0.05,), 0) if word_timed else None)
    image = label.grab().toImage()
    pixels = sung_pixels(image)
    assert pixels
    assert all(x > image.width() / 2 and y < image.height() / 2 for x, y in pixels)
    label.set_progress(LineProgress("line", 1.0), WordProgress("line", (1.0,), 0) if word_timed else None)
    assert sung_pixels(label.grab().toImage(), top=image.height() // 2)


@pytest.mark.parametrize("glow", [False, True])
def test_long_arabic_line_scrolls_from_its_reading_start(label: KaraokeLabel, glow: bool) -> None:
    """A long RTL line must initially expose its rightmost glyphs and sung region."""
    label.set_max_width(110)
    label.set_effects(glow=glow, word_pop=False, intensity="subtle", animate=False)
    label.set_line(lyric("مرحبا " * 12), False)
    label.resize(label.sizeHint())
    label.set_progress(LineProgress("line", 0.02), None)
    image = label.grab().toImage()
    pixels = sung_pixels(image)
    assert pixels
    assert all(x > image.width() / 2 for x, _ in pixels)
    label.set_progress(LineProgress("line", 1.0), None)
    assert sung_pixels(label.grab().toImage())


def test_direction_is_recomputed_when_replacing_a_line(label: KaraokeLabel) -> None:
    """Reusing a line identity must not retain the preceding lyric's direction."""
    for text, rtl in (("hello world", False), ("مرحبا عالم", True), ("hello world", False)):
        label.set_line(lyric(text), False)
        label.resize(label.sizeHint())
        label.set_progress(LineProgress("line", 0.25), None)
        image = label.grab().toImage()
        pixels = sung_pixels(image)
        assert pixels
        assert all((x > image.width() / 2) if rtl else (x < image.width() / 2) for x, _ in pixels)


def test_wrapped_arabic_word_distances_increase_in_reading_order(qapp: QApplication) -> None:
    """Qt's decreasing RTL x coordinates must not become zero-width timed words."""
    text = "سلام"
    font = QFont("DejaVu Sans")
    font.setPixelSize(36)
    words = tuple(LyricWord(float(i), float(i + 1), char) for i, char in enumerate(text))
    layout = WrappedTextLayout(lyric(text, words), font, 400)
    assert layout.word_offsets[0] == pytest.approx(0.0)
    assert all(width > 0.0 for width in layout.word_widths)
    assert layout.word_offsets == sorted(layout.word_offsets)
    assert sum(layout.word_widths) == pytest.approx(layout.advance)
    # Scrolling must measure characters in their full joining context too;
    # independently shaping each sliced prefix changes Arabic glyph advances.
    row = layout.rows[0]
    expected = [row.width - row.line.cursorToX(index)[0] for index in range(len(text))]
    assert measure_word_offsets(lyric(text, words), QFontMetrics(font)) == pytest.approx(expected, abs=1.0)
