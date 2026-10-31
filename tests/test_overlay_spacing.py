"""Rendered grouping and clipping contracts for the compact lyric panel."""

from __future__ import annotations

from dataclasses import replace

import pytest
from overlay_helpers import build_overlay
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication
from test_overlay import display_frame

from kotonoha.config import Config, PanelWidthMode
from kotonoha.display.models import LineProgress
from kotonoha.lyrics.models import LyricLine
from kotonoha.ui.overlay.karaoke_label import KaraokeLabel
from kotonoha.ui.overlay.state import LyricsState


def _foreground_rows(label: KaraokeLabel) -> tuple[float, float]:
    """Measure solid accent glyphs, excluding the faint halo and dark shadow."""
    image = label.grab().toImage()
    rows = [
        y for y in range(image.height())
        if any(
            (color := image.pixelColor(x, y)).alpha() > 180
            and color.red() - color.green() > 60
            for x in range(image.width())
        )
    ]
    assert rows, "The active lyric must remain visible"
    ratio = image.devicePixelRatio()
    return rows[0] / ratio, (rows[-1] + 1) / ratio


@pytest.mark.parametrize("font_size,glow", [(20, False), (24, False), (20, True), (24, True), (32, True)])
def test_active_lyric_and_translation_form_a_compact_group_without_clipping(
    qapp: QApplication, font_size: int, glow: bool,
) -> None:
    """The translation stays close to the lyric while both keep their full paint area."""
    config = Config(
        font_family="Noto Sans CJK SC", font_size=font_size,
        translation_font_size=13, context_lines=1, fx_glow=glow, fx_animate=False,
        panel_width_mode=PanelWidthMode.FIXED, panel_width=600,
    )
    state = LyricsState()
    overlay = build_overlay(state, config)
    line = LyricLine(1, "current", 10.0, 20.0, "Now flying backwards", "现在正倒飞回往年冬天", ())
    state.update(replace(
        display_frame(has_lyrics=True, current=line),
        line_progress=LineProgress(line.id, 1.0),
    ))
    try:
        overlay.show()
        qapp.processEvents()
        labels = overlay.findChildren(KaraokeLabel)
        current = next(label for label in labels if label.text == line.text)
        translation = next(label for label in labels if label.text == line.translation)
        _, main_bottom = _foreground_rows(current)
        translation_top, _ = _foreground_rows(translation)
        gap = (
            translation.mapTo(overlay, QPoint()).y() + translation_top
            - current.mapTo(overlay, QPoint()).y() - main_bottom
        )

        # Fractional display scaling can move the hinted glyph edges by a pixel.
        assert 2 <= gap <= font_size * 0.6
        assert current.height() >= current.sizeHint().height()
        assert translation.height() >= translation.sizeHint().height()
    finally:
        overlay.close()
