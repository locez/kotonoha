"""Layout grouping and non-clipping contracts for the active lyric and translation."""

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


@pytest.mark.parametrize("font_size,glow", [(20, False), (24, False), (20, True), (24, True), (32, True)])
def test_active_lyric_and_translation_form_a_compact_group_without_clipping(
    qapp: QApplication, font_size: int, glow: bool,
) -> None:
    """The translation shares vertical margin with the lyric while both keep their full paint area."""
    translation_size = 13
    config = Config(
        font_size=font_size,
        translation_font_size=translation_size,
        context_lines=1,
        fx_glow=glow,
        fx_animate=False,
        panel_width_mode=PanelWidthMode.FIXED,
        panel_width=600,
    )
    state = LyricsState()
    overlay = build_overlay(state, config)
    line = LyricLine(1, "current", 10.0, 20.0, "Now flying backwards", "Translation line", ())
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

        current_top = current.mapTo(overlay, QPoint()).y()
        translation_top = translation.mapTo(overlay, QPoint()).y()
        expected_overlap = min(8, round(min(font_size * 0.3, translation_size * 0.55)))

        assert current.height() >= current.sizeHint().height()
        assert translation.height() >= translation.sizeHint().height()
        assert current_top < translation_top < current_top + current.height()
        assert current_top + current.height() - translation_top == expected_overlap
    finally:
        overlay.close()


def test_hiding_translation_collapses_lyric_pair_to_current_line_height(qapp: QApplication) -> None:
    """Hiding translation releases its height from the lyric group layout."""
    config = Config(
        font_size=24,
        translation_font_size=13,
        show_translation=True,
        fx_animate=False,
        panel_width_mode=PanelWidthMode.FIXED,
        panel_width=600,
    )
    state = LyricsState()
    overlay = build_overlay(state, config)
    line = LyricLine(1, "current", 10.0, 20.0, "Now flying backwards", "Translation line", ())
    state.update(replace(
        display_frame(has_lyrics=True, current=line),
        line_progress=LineProgress(line.id, 1.0),
    ))
    try:
        overlay.show()
        qapp.processEvents()
        with_translation_height = overlay._presentation._lyric_pair.sizeHint().height()

        overlay.apply_config(replace(config, show_translation=False))
        qapp.processEvents()
        without_translation_height = overlay._presentation._lyric_pair.sizeHint().height()

        assert overlay._translation.isHidden() is True
        assert without_translation_height == overlay._current.sizeHint().height()
        assert without_translation_height < with_translation_height
    finally:
        overlay.close()
