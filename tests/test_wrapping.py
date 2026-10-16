"""Behavioral coverage for fixed-width lyric wrapping."""


from dataclasses import replace

import pytest
from PyQt6.QtGui import QFont

from kotonoha.config import Config, PanelOverflowMode, PanelWidthMode
from kotonoha.display.models import LineProgress, WordProgress
from kotonoha.lyrics.models import LyricLine, LyricWord
from kotonoha.ui.overlay.karaoke_label import KaraokeLabel
from kotonoha.ui.overlay.text_layout import WrappedTextLayout
from kotonoha.ui.settings.dialog import SettingsDialog
from kotonoha.ui.settings.form_state import SettingsFormState


def lyric(text: str, *, line_id: str = "line") -> LyricLine:
    return LyricLine(0, line_id, 0.0, 10.0, text, "", ())


def configured_label(text: str) -> KaraokeLabel:
    label = KaraokeLabel()
    font = QFont("DejaVu Sans")
    font.setPixelSize(24)
    label.set_style(font, "#ff0000", "#ff0000", "#ff0000")
    label.set_effects(glow=False, word_pop=False, intensity="subtle", animate=False)
    label.set_max_width(130)
    label.set_line(lyric(text), False)
    return label


def test_overflow_config_validation_roundtrip_and_reset():
    assert Config.from_dict({}).panel_overflow_mode is PanelOverflowMode.SCROLL
    assert Config.from_dict({"panel_overflow_mode": "bad"}).panel_overflow_mode is PanelOverflowMode.SCROLL
    config = Config(panel_overflow_mode=PanelOverflowMode.WRAP)
    assert Config.from_dict(config.to_dict()).panel_overflow_mode is PanelOverflowMode.WRAP
    state = SettingsFormState(Config())
    state.replace(config)
    assert "panel_overflow_mode" in state.changed_fields()
    state.mark_applied()
    assert not state.changed_fields()
    assert state.reset_page(3).panel_overflow_mode is PanelOverflowMode.SCROLL


def test_settings_preserve_wrapping_while_fit_mode_disables_it(_session_qapp):
    dialog = SettingsDialog(Config(panel_width_mode=PanelWidthMode.FIXED))
    controls = dialog.form_widgets
    assert controls.panel_overflow_mode.isEnabled()
    controls.panel_overflow_mode.setCurrentIndex(controls.panel_overflow_mode.findData("wrap"))
    assert dialog.current_config().panel_overflow_mode is PanelOverflowMode.WRAP
    controls.panel_width_mode.setCurrentIndex(controls.panel_width_mode.findData("fit"))
    assert not controls.panel_overflow_mode.isEnabled()
    assert dialog.current_config().panel_overflow_mode is PanelOverflowMode.WRAP
    controls.panel_width_mode.setCurrentIndex(controls.panel_width_mode.findData("fixed"))
    assert controls.panel_overflow_mode.isEnabled()
    dialog.close()


@pytest.mark.parametrize("text", ["one two three four five six", "我曾经跨过山和大海" * 3, "abcdefghij" * 6])
def test_wrapping_grows_and_reflows_without_changing_text(_session_qapp, text):
    label = configured_label(text)
    single = label.sizeHint().height()
    label.set_overflow_mode(PanelOverflowMode.WRAP)
    narrow = label.sizeHint().height()
    assert narrow > single
    assert label.text == text
    label.set_max_width(300)
    assert label.sizeHint().height() < narrow
    label.set_overflow_mode(PanelOverflowMode.SCROLL)
    assert label.sizeHint().height() == single
    label.deleteLater()


@pytest.mark.parametrize("line_id", ["title", "interlude"])
def test_titles_and_interludes_remain_single_row(_session_qapp, line_id):
    label = configured_label("long text " * 20)
    label.set_line(lyric(label.text, line_id=line_id), False)
    single = label.sizeHint()
    label.set_overflow_mode(PanelOverflowMode.WRAP)
    assert label.sizeHint() == single
    label.deleteLater()


def red_pixels(image, y0, y1):
    return sum(
        image.pixelColor(x, y).red() > image.pixelColor(x, y).green() + 50
        for y in range(y0, min(y1, image.height()))
        for x in range(image.width())
    )


def test_line_sweep_moves_to_next_wrapped_row(_session_qapp):
    label = configured_label("MMMM MMMM MMMM MMMM")
    label.set_overflow_mode(PanelOverflowMode.WRAP)
    label.resize(label.sizeHint())
    layout = WrappedTextLayout(lyric(label.text), QFont("DejaVu Sans", 18), 130)
    assert len(layout.rows) > 1
    label.set_progress(LineProgress("line", 0.0), None)
    empty = label.grab().toImage()
    label.set_progress(LineProgress("line", 1.0), None)
    full = label.grab().toImage()
    midpoint = full.height() // 2
    assert red_pixels(empty, 0, empty.height()) == 0
    assert red_pixels(full, 0, midpoint) > 0
    assert red_pixels(full, midpoint, full.height()) > 0
    label.set_progress(LineProgress("line", 0.1), None)
    early = label.grab().toImage()
    assert red_pixels(early, 0, midpoint) > 0
    assert red_pixels(early, midpoint, early.height()) == 0
    label.deleteLater()


def test_timed_word_spanning_rows_uses_whole_word_progress(_session_qapp):
    text = "MMMMMMMMMMMMMMMM"
    label = configured_label(text)
    label.set_overflow_mode(PanelOverflowMode.WRAP)
    label.set_line(replace(lyric(text), words=(LyricWord(0.0, 10.0, text),)), True)
    label.resize(label.sizeHint())
    label.set_progress(None, WordProgress("line", (0.1,), 0))
    early = label.grab().toImage()
    label.set_progress(None, WordProgress("line", (1.0,), -1))
    full = label.grab().toImage()
    midpoint = full.height() // 2
    assert red_pixels(early, midpoint, early.height()) == 0
    assert red_pixels(full, midpoint, full.height()) > 0
    label.deleteLater()


def test_short_wrapped_line_and_font_changes(_session_qapp):
    label = configured_label("short")
    single = label.sizeHint().height()
    label.set_overflow_mode(PanelOverflowMode.WRAP)
    assert label.sizeHint().height() == single
    label.set_line(lyric("more words " * 12), False)
    normal_height = label.sizeHint().height()
    font = QFont("DejaVu Sans")
    font.setPixelSize(36)
    label.set_style(font, "#ff0000", "#ff0000", "#ff0000")
    assert label.sizeHint().height() > normal_height
    label.deleteLater()


@pytest.mark.parametrize("second", [0.0, 0.5, 1.0])
def test_word_boundary_highlight_stays_in_its_row(_session_qapp, second):
    label = configured_label("MMMM MMMM")
    label.set_overflow_mode(PanelOverflowMode.WRAP)
    label.set_line(replace(
        lyric(label.text),
        words=(LyricWord(0.0, 5.0, "MMMM"), LyricWord(5.0, 10.0, "MMMM")),
    ), True)
    label.resize(label.sizeHint())
    label.set_progress(None, WordProgress("line", (1.0, second), 1 if second < 1.0 else -1))
    image = label.grab().toImage()
    midpoint = image.height() // 2
    assert red_pixels(image, 0, midpoint) > 0
    assert (red_pixels(image, midpoint, image.height()) > 0) is (second > 0.0)
    label.deleteLater()
