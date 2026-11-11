"""Project the user's complete word-timed Arabic sample onto native Qt glyphs."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fixtures.arabic_words import ANA_INDI_HANEEN, ArabicLineCase
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QTextLayout, QTextLine, QTextOption
from PyQt6.QtWidgets import QApplication

from kotonoha.config import PanelOverflowMode
from kotonoha.display.models import ResolutionState
from kotonoha.display.presentation import DisplayEngine
from kotonoha.lyrics.adapter import LyricsDocumentAdapter
from kotonoha.lyrics.lrclib import parse_payload
from kotonoha.lyrics.models import LyricsDocument
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from kotonoha.ui.overlay.karaoke_label import KaraokeLabel


@pytest.fixture(scope="module")
def document() -> LyricsDocument:
    """Exercise the actual LRCLIB YAML-to-display path for all 28 sample lines."""
    sample = Path(__file__).parent / "fixtures" / "ana_indi_haneen.lyricsfile.yaml"
    lines = parse_payload({"lyricsfile": sample.read_text(encoding="utf-8")})
    return LyricsDocumentAdapter().adapt(
        lines, source_id="lrclib", title="Ana Indi Haneen", artist="Fairuz", album="Wahdon",
        language="ar", duration_s=356.0,
    )


@pytest.fixture
def label(qapp: QApplication) -> Iterator[KaraokeLabel]:
    """Use a different color for active, completed, and unsung words."""
    widget = KaraokeLabel()
    widget.set_effects(glow=False, word_pop=False, intensity="subtle", animate=False)
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("case", ANA_INDI_HANEEN, ids=lambda case: str(case.starts_ms[0]))
def test_sample_emphasizes_the_timed_word_in_native_reading_order(
    label: KaraokeLabel, case: ArabicLineCase, wrapped: bool, document: LyricsDocument,
) -> None:
    """Every timestamp must light its own word, including spaces and repetitions."""
    index = ANA_INDI_HANEEN.index(case)
    line = document.lines[index]
    assert line == case.line(index)
    font = QFont("DejaVu Sans")
    font.setPixelSize(32)
    font.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)
    label.set_style(font, "#00ff00", "#00ff00", "#ff0000", QColor("#0000ff"), QColor(0, 0, 0, 0))
    label.set_max_width(160 if wrapped else 0)
    label.set_overflow_mode(PanelOverflowMode.WRAP if wrapped else PanelOverflowMode.SCROLL)
    label.set_line(line, True)
    label.resize(label.sizeHint())

    # Qt is the independent oracle for the actual shaped word's location.
    # Retain the owner while its QTextLines are used, as required by Qt.
    native = QTextLayout(line.text, font)
    option = QTextOption()
    option.setTextDirection(Qt.LayoutDirection.RightToLeft)
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    native.setTextOption(option)
    native.beginLayout()
    rows: list[QTextLine] = []
    while True:
        row = native.createLine()
        if not row.isValid():
            break
        row.setLineWidth(160 if wrapped else 10000)
        rows.append(row)
    native.endLayout()

    track = TrackIdentity("test", "player", title="Ana Indi Haneen", artist="Fairuz")
    engine = DisplayEngine()
    cursor = 0
    for word_index, word in enumerate(line.words):
        assert word.start is not None and word.end is not None
        playback = PlaybackObservation(
            "test", "player", track, PlaybackStatus.PLAYING, (word.start + word.end) / 2, 356.0, 0.0,
        )
        frame = engine.project_observation(playback, document, ResolutionState.AVAILABLE)
        assert frame.current == line
        assert frame.word_progress is not None
        assert frame.word_progress.active_index == word_index
        expected = (1.0,) * word_index + (0.5,) + (0.0,) * (len(line.words) - word_index - 1)
        assert frame.word_progress.fractions == pytest.approx(expected)
        label.set_progress(frame.line_progress, frame.word_progress)

        start = len(line.text[:cursor].encode("utf-16-le")) // 2
        cursor += len(word.text)
        end = len(line.text[:cursor].encode("utf-16-le")) // 2
        bounds: list[QRectF] = []
        top = 3.0
        for row in rows:
            first = max(start, row.textStart())
            last = min(end, row.textStart() + row.textLength())
            if first < last:
                right, _ = row.cursorToX(first)
                left, _ = row.cursorToX(last)
                origin = (label.width() - row.horizontalAdvance()) / 2
                ink = QRectF()
                for run in row.glyphRuns(first, last - first):
                    for glyph, point in zip(run.glyphIndexes(), run.positions(), strict=True):
                        ink = ink.united(run.rawFont().boundingRect(glyph).translated(point))
                # Integer font metrics used by the single-row painter round at
                # most one pixel. Keep that tolerance outside the glyph region.
                # Accents can extend above a font's nominal ascent (DejaVu's
                # hamza does); use glyph ink bounds for the wrapped row's y span.
                # QPainter vertically centers an unwrapped line; QTextLayout
                # places wrapped rows from the top. Only wrapped y positions
                # decide whether a word accidentally lights a different row.
                bounds.append(QRectF(
                    origin + left - 1, top + ink.top() - 1 if wrapped else 0,
                    right - left + 2, ink.height() + 2 if wrapped else label.height(),
                ))
            top += row.height()

        image = label.grab().toImage()
        ratio = image.devicePixelRatio()
        pixels = [
            (x / ratio, y / ratio)
            for y in range(image.height()) for x in range(image.width())
            if image.pixelColor(x, y).red() > 200 and image.pixelColor(x, y).green() < 30
        ]
        assert pixels, (case.starts_ms[0], word_index, word.text)
        assert all(any(rect.contains(x, y) for rect in bounds) for x, y in pixels), (word_index, word.text)
