"""Pixel-level contracts for soft lyric halos and independent word emphasis."""

from collections.abc import Iterator

import pytest
from PyQt6.QtGui import QColor, QFont, QImage
from PyQt6.QtWidgets import QApplication

from kotonoha.config import PanelOverflowMode
from kotonoha.display.models import LineProgress, WordProgress
from kotonoha.lyrics.models import LyricLine, LyricWord
from kotonoha.ui.overlay.karaoke_label import KaraokeLabel


@pytest.fixture
def label(qapp: QApplication) -> Iterator[KaraokeLabel]:
    """Use transparent base/shadow colors to isolate the sung glyphs and halo."""
    widget = KaraokeLabel()
    font = QFont("monospace")
    font.setPixelSize(40)
    widget.set_style(font, "#4080c0", "#4080c0", "#4080c0", QColor(0, 0, 0, 0), QColor(0, 0, 0, 0))
    widget.set_effects(glow=False, word_pop=False, intensity="subtle", animate=False)
    widget.resize(240, 100)
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def _line(text: str, *, words: bool = False) -> LyricLine:
    """Build the same public lyric contract for line- and word-timed cases."""
    return LyricLine(0, "line", 0.0, 10.0, text, "", (LyricWord(0.0, 10.0, text),) if words else ())


def _opaque_bounds(image: QImage) -> tuple[int, int, int, int]:
    """Locate the foreground without assuming a particular installed font."""
    pixels = [
        (x, y) for y in range(image.height()) for x in range(image.width())
        if image.pixelColor(x, y).alpha() >= 240
    ]
    return min(x for x, _ in pixels), min(y for _, y in pixels), max(x for x, _ in pixels), max(y for _, y in pixels)


@pytest.mark.parametrize("intensity", ["subtle", "expressive"])
def test_glow_fades_outside_both_glyph_edges_without_thickening_the_core(
    label: KaraokeLabel, intensity: str,
) -> None:
    """Offset copies used to produce opaque ridges and clip the leading halo."""
    label.set_line(_line("H"), False)
    label.set_progress(LineProgress("line", 1.0), None)
    plain = label.grab().toImage()
    left, top, right, bottom = _opaque_bounds(plain)
    y = (top + bottom) // 2
    label.set_effects(glow=True, word_pop=False, intensity=intensity, animate=False)
    glowing = label.grab().toImage()
    ratio = glowing.devicePixelRatio()

    for edge, direction in ((left, -1), (right, 1)):
        # Near-stroke light must remain restrained enough to preserve clear
        # counters and edges, while the wider bloom stays visible farther out.
        tail = [glowing.pixelColor(edge + direction * round(distance * ratio), y).alpha() for distance in (1.5, 3, 4.5)]
        assert 100 > tail[0] > tail[1] > tail[2] > 0
        if intensity == "expressive":
            # A broad visible tail distinguishes the requested bloom from the
            # previous small halo that mostly looked like heavier lettering.
            assert glowing.pixelColor(edge + direction * round(10 * ratio), y).alpha() > 0
    # A blurred foreground would lose the solid center of each stem.
    assert glowing.pixelColor(left, y) == plain.pixelColor(left, y)
    assert glowing.pixelColor(right, y) == plain.pixelColor(right, y)


@pytest.mark.parametrize("glow", [False, True])
def test_word_emphasis_brightens_glyphs_without_adding_another_outline(label: KaraokeLabel, glow: bool) -> None:
    """Word-pop must not recreate the old eight-copy glow, even with glow off."""
    label.set_effects(glow=glow, word_pop=False, intensity="expressive", animate=False)
    label.set_line(_line("HHHH", words=True), True)
    label.set_progress(None, WordProgress("line", (0.6,), 0))
    plain = label.grab().toImage()
    label.set_effects(glow=glow, word_pop=True, intensity="expressive", animate=False)
    emphasized = label.grab().toImage()

    assert emphasized.convertToFormat(QImage.Format.Format_Alpha8) == plain.convertToFormat(QImage.Format.Format_Alpha8)
    assert any(
        emphasized.pixelColor(x, y).lightness() > plain.pixelColor(x, y).lightness()
        for y in range(plain.height()) for x in range(plain.width())
        if plain.pixelColor(x, y).alpha() == 255
    )


@pytest.mark.parametrize("word_timed", [False, True])
def test_sweep_has_a_soft_halo_boundary_but_leaves_distant_unsung_text_unlit(
    label: KaraokeLabel, word_timed: bool,
) -> None:
    """A rectangular clip previously cut the halo off at the progress edge."""
    label.set_line(_line("HHHHHH", words=word_timed), word_timed)
    label.set_progress(LineProgress("line", 0.5), WordProgress("line", (0.5,), 0) if word_timed else None)
    plain = label.grab().toImage()
    _, top, _, bottom = _opaque_bounds(plain)
    y = (top + bottom) // 2
    label.set_effects(glow=True, word_pop=False, intensity="expressive", animate=False)
    glowing = label.grab().toImage()
    ratio = glowing.devicePixelRatio()
    edge = glowing.width() // 2

    assert 0 < glowing.pixelColor(edge + round(2 * ratio), y).alpha() < 100
    assert glowing.pixelColor(edge + round(16 * ratio), y).alpha() == 0
    # Seeking back before the line starts must also hide a previously cached halo.
    label.set_progress(LineProgress("line", 0.0), WordProgress("line", (0.0,), -1) if word_timed else None)
    reset = label.grab().toImage()
    assert all(reset.pixelColor(x, y).alpha() == 0 for y in range(reset.height()) for x in range(reset.width()))


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("word_timed", [False, True])
@pytest.mark.parametrize("fraction", [0.15, 0.5, 1.0])
def test_progress_colors_do_not_accumulate_glyph_edge_coverage(
    label: KaraokeLabel, wrapped: bool, word_timed: bool, fraction: float,
) -> None:
    """Equal base/accent colors must look identical as line and word fills move.

    Redrawing base, sung, and active-word glyphs used to increase the alpha at
    antialiased edges; opaque glyph centers alone cannot detect this thickening.
    """
    font = QFont("monospace")
    font.setPixelSize(40)
    label.set_style(font, "#4080c0", "#4080c0", "#4080c0", QColor("#4080c0"), QColor(0, 0, 0, 0))
    label.set_max_width(180)
    label.set_overflow_mode(PanelOverflowMode.WRAP if wrapped else PanelOverflowMode.SCROLL)
    text = "HHHH HHHH" if wrapped else "HHHH"
    label.set_line(_line(text, words=word_timed), word_timed)
    label.resize(label.sizeHint())
    label.set_progress(LineProgress("line", 0.0), WordProgress("line", (0.0,), -1) if word_timed else None)
    plain = label.grab().toImage().convertToFormat(QImage.Format.Format_Alpha8)
    label.set_progress(
        LineProgress("line", fraction),
        WordProgress("line", (fraction,), 0 if fraction < 1.0 else -1) if word_timed else None,
    )
    filled = label.grab().toImage().convertToFormat(QImage.Format.Format_Alpha8)

    assert filled == plain
