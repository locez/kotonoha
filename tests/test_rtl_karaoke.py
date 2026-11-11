"""Reading-direction contracts exercised through the rendered lyric widget."""

from collections.abc import Iterator
from dataclasses import dataclass, replace

import pytest
from PyQt6.QtGui import QColor, QFont, QImage
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from kotonoha.config import Config, PanelOverflowMode
from kotonoha.display.models import DisplayOptions, InterludeCountdown, LineProgress, ResolutionState, WordProgress
from kotonoha.display.offsets import EMPTY_TRACK_OFFSETS
from kotonoha.display.presentation import DisplayEngine
from kotonoha.lyrics.models import LyricLine, LyricsDocument, LyricWord, TimingKind
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from kotonoha.strings import Translator
from kotonoha.ui.overlay.content import OverlayContentController
from kotonoha.ui.overlay.context_label import ContextLabel
from kotonoha.ui.overlay.karaoke_label import KaraokeLabel
from kotonoha.ui.overlay.state import LyricsState
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


@pytest.mark.parametrize("case", (
    DirectionCase("سلام", True), DirectionCase("لا", True), DirectionCase("لل", True),
    DirectionCase("office", False), DirectionCase("hello", False),
), ids=lambda case: case.text)
def test_word_distances_follow_shaped_cursor_positions(qapp: QApplication, case: DirectionCase) -> None:
    """RTL coordinates and ligatures must not become zero-width timed letters."""
    text = case.text
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
    expected = [
        row.width - row.line.cursorToX(index)[0] if case.rtl else row.line.cursorToX(index)[0]
        for index in range(len(text))
    ]
    assert measure_word_offsets(lyric(text, words), font) == pytest.approx(expected, abs=1.0)


@pytest.fixture
def content(qapp: QApplication, label: KaraokeLabel) -> Iterator[OverlayContentController]:
    """Bind real frames to the tested label without requiring a compositor."""
    container = QWidget()
    previous = ContextLabel(previous=True, parent=container)
    following = ContextLabel(previous=False, parent=container)
    # Direction must work even when the surrounding lyrics are hidden.
    for context in (previous, following):
        context.configure(count=0, animate=False)
    controller = OverlayContentController(
        LyricsState(container), Config(), previous, label, QLabel(container),
        KaraokeLabel(container), following, container, timer_parent=container,
        on_input_region_refresh=container.update, on_offset_changed=lambda _key, _offset: None,
        track_offsets=EMPTY_TRACK_OFFSETS, translator=Translator("en"),
    )
    yield controller
    controller.stop()
    container.close()
    container.deleteLater()
    qapp.processEvents()


@pytest.fixture
def mixed_document() -> LyricsDocument:
    """Alternate Arabic and English verses, separated by twenty-second breaks."""
    texts = ("مرحبا عالم", "مرحبا عالم", "hello world", "hello world", "مرحبا عالم", "مرحبا عالم")
    starts = (20.0, 25.0, 50.0, 55.0, 80.0, 85.0)
    lines = tuple(
        LyricLine(i, str(i), start, start + 5.0, text, "")
        for i, (start, text) in enumerate(zip(starts, texts, strict=True))
    )
    return LyricsDocument("test", song_id="mixed", timing=TimingKind.LINE, duration_s=110.0, lines=lines)


def _show_position(
    content: OverlayContentController, document: LyricsDocument, position: float, options: DisplayOptions,
) -> None:
    """Exercise time-based context selection, including seeks and track changes."""
    track = TrackIdentity("test", "player", stable_id=document.song_id, title="Song")
    playback = PlaybackObservation("test", "player", track, PlaybackStatus.PLAYING, position, 110.0, 0.0)
    frame = DisplayEngine(options).project_observation(playback, document, ResolutionState.AVAILABLE)
    content.on_frame(frame)


def _check_sweep_side(label: KaraokeLabel, *, rtl: bool) -> None:
    """Observe the actual accent pixels, independent of the widget's direction flag."""
    label.resize(label.sizeHint())
    image = label.grab().toImage()
    pixels = sung_pixels(image)
    assert pixels
    assert all((x > image.width() / 2) if rtl else (x < image.width() / 2) for x, _ in pixels)


@pytest.mark.parametrize("countdown", tuple(InterludeCountdown))
@pytest.mark.parametrize("glow", [False, True])
def test_interlude_direction_follows_the_previous_verse_through_seeks(
    content: OverlayContentController, label: KaraokeLabel, mixed_document: LyricsDocument,
    countdown: InterludeCountdown, glow: bool,
) -> None:
    """Neutral markers follow nearby lyrics, regardless of playback history or countdown text."""
    label.set_effects(glow=glow, word_pop=False, intensity="subtle", animate=False)
    options = DisplayOptions(interlude_countdown=countdown)
    # Enter a break directly, seek to the other language and back, then visit
    # the intro, outro and sung lines. A marker's override must not leak into lyrics.
    for position, rtl in ((35, True), (65, False), (35, True), (5, True), (95, True), (51, False), (81, True)):
        _show_position(content, mixed_document, position, options)
        _check_sweep_side(label, rtl=rtl)


def test_identical_interlude_marker_changes_direction_with_the_track(
    content: OverlayContentController, label: KaraokeLabel, mixed_document: LyricsDocument,
) -> None:
    """The same dots and timestamps cannot retain another track's reading direction."""
    english = replace(
        mixed_document, song_id="english",
        lines=tuple(replace(line, text="hello world") for line in mixed_document.lines),
    )
    for document, rtl in ((mixed_document, True), (english, False), (mixed_document, True)):
        _show_position(content, document, 35.0, DisplayOptions())
        assert label.text == "●\u2003●\u2003●"
        _check_sweep_side(label, rtl=rtl)
        # Width changes rebuild geometry during the same interlude.
        label.set_max_width(200 if rtl else 250)
        _check_sweep_side(label, rtl=rtl)
