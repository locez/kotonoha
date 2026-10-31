"""Contracts for configurable context, focus depth, and owned scrolling."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from overlay_helpers import build_overlay
from PyQt6.QtCore import QAbstractAnimation, QVariantAnimation
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication
from test_overlay import project_document

from kotonoha.app.config_merge import merge_settings
from kotonoha.config import Config, load_config, save_config
from kotonoha.lyrics.models import LyricLine, LyricsDocument, TimingKind
from kotonoha.ui.overlay.state import LyricsState
from kotonoha.ui.settings.dialog import SettingsDialog
from kotonoha.ui.settings.form_state import SettingsFormState

if TYPE_CHECKING:
    from kotonoha.ui.overlay.context_label import ContextLabel


def _lines(start: int, stop: int, *, repeated_text: bool = False) -> tuple[LyricLine, ...]:
    """Build canonical rows with distinct identities even when lyrics repeat."""
    return tuple(
        LyricLine(i, str(i), i * 10.0, (i + 1) * 10.0, "HHHHHH" if repeated_text else f"Lyric {i}", "", ())
        for i in range(start, stop)
    )


@pytest.fixture
def context(qapp: QApplication) -> Iterator[ContextLabel]:
    """Use actual Qt text with enough space to exercise user-selected counts."""
    from kotonoha.ui.overlay.context_label import ContextLabel

    label = ContextLabel(previous=False)
    label.setStyleSheet("color: white; font-family: monospace; font-size: 24px;")
    label.setMaximumHeight(2000)
    label.configure(count=3, animate=True)
    yield label
    label.stop()
    label.close()
    label.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("count", [1, 3, 10, 25])
def test_context_count_survives_settings_merge_and_persistence(tmp_path: Path, count: int) -> None:
    """Neither settings nor persistence may silently truncate a chosen count."""
    candidate = Config.from_dict({"context_lines": count})
    state = SettingsFormState(Config())
    state.replace(candidate)
    merged = merge_settings(Config(margin_x=84), state.config, state.changed_fields())
    path = tmp_path / "config.json"
    save_config(merged, path)
    assert load_config(path).context_lines == count
    assert load_config(path).margin_x == 84
    assert state.reset_page(5).context_lines == 1
    assert Config.from_dict({"context_lines": 0}).context_lines == 1


def test_settings_accept_ten_or_more_context_rows_and_preserve_hidden_choice(qapp: QApplication) -> None:
    """The input must allow more than a few rows, including with context hidden."""
    dialog = SettingsDialog(Config(context_lines=10, current_line_only=True))
    try:
        assert dialog.form_widgets.context_lines.value() == 10
        dialog.form_widgets.context_lines.setValue(25)
        assert dialog.current_config().context_lines == 25
        dialog.form_widgets.current_line_only.setChecked(False)
        assert dialog.current_config().context_lines == 25
    finally:
        dialog.close()


def test_ten_rows_render_with_progressive_depth(context: ContextLabel) -> None:
    """More distant copies of the same text must be dimmer and less sharply edged."""
    context.configure(count=10, animate=False)
    context.set_lines(_lines(0, 12, repeated_text=True))
    context.resize(context.sizeHint())
    image = context.grab().toImage()
    third = image.height() // 3
    first = image.copy(0, 0, image.width(), third)
    last = image.copy(0, image.height() - third, image.width(), third)

    def contrast(sample: QImage) -> tuple[int, float]:
        alphas = [[sample.pixelColor(x, y).alpha() for x in range(sample.width())] for y in range(sample.height())]
        peak = max(max(row) for row in alphas)
        energy = sum(sum(row) for row in alphas)
        edges = sum(sum(abs(a - b) for a, b in zip(row, row[1:], strict=False)) for row in alphas)
        # Compare at the same letter size: smaller glyphs have more perimeter
        # per unit of ink even when their edges are softer. Ignore faint tails.
        ink_height = sum(any(alpha > peak * 0.1 for alpha in row) for row in alphas)
        return peak, edges * ink_height / energy

    near_peak, near_edges = contrast(first)
    far_peak, far_edges = contrast(last)
    assert 0 < far_peak < near_peak
    assert far_edges < near_edges
    tall = context.sizeHint().height()
    context.configure(count=1, animate=False)
    assert tall > 6 * context.sizeHint().height()


def test_viewport_bounds_work_without_losing_requested_count(context: ContextLabel) -> None:
    """Large settings must not create giant surfaces or render offscreen rows."""
    context.configure(count=10_000, animate=False)
    context.set_lines(_lines(0, 200))
    context.setMaximumHeight(140)
    context.resize(context.sizeHint())
    small = context.grab().toImage()
    assert small.height() <= 140 * small.devicePixelRatio()
    context.setMaximumHeight(800)
    context.resize(context.sizeHint())
    large = context.grab().toImage()
    assert large.height() > small.height() * 4
    assert large.height() <= 800 * large.devicePixelRatio()


@pytest.mark.parametrize("direction", [-1, 1])
def test_context_scrolls_and_repeated_frames_do_not_restart_it(context: ContextLabel, direction: int) -> None:
    """A lyric step has intermediate pixels and settles on the same static layout."""
    context.set_lines(_lines(4, 7))
    context.resize(context.sizeHint())
    start = context.grab().toImage()
    target = _lines(4 + direction, 7 + direction)
    context.set_lines(target, direction=direction)
    animation = context.findChild(QVariantAnimation)
    assert animation is not None
    animation.pause()
    animation.setCurrentTime(120)
    midway = context.grab().toImage()
    context.set_lines(target, direction=direction)
    assert animation.currentTime() == 120
    animation.setCurrentTime(animation.duration())
    finished = context.grab().toImage()
    assert start != midway != finished
    context.configure(count=3, animate=False)
    assert context.grab().toImage() == finished
    assert animation.state() is QAbstractAnimation.State.Stopped


@pytest.mark.parametrize("interruption", ["clear", "disable", "hide", "stop", "seek"])
def test_context_animation_settles_on_interruption(context: ContextLabel, interruption: str) -> None:
    """Clearing, hiding, seeking, and shutdown cannot leave ghost rows or timers."""
    context.show()
    context.set_lines(_lines(2, 5))
    context.resize(context.sizeHint())
    context.set_lines(_lines(3, 6), direction=1)
    animation = context.findChild(QVariantAnimation)
    assert animation is not None and animation.state() is QAbstractAnimation.State.Running
    if interruption == "clear":
        context.set_lines(())
        image = context.grab().toImage()
        assert all(image.pixelColor(x, y).alpha() == 0 for y in range(image.height()) for x in range(image.width()))
    elif interruption == "disable":
        context.configure(count=3, animate=False)
    elif interruption == "hide":
        context.hide()
    elif interruption == "seek":
        context.set_lines(_lines(12, 15))
        assert context.text() == "Lyric 12"
    else:
        context.stop()
    assert animation.state() is QAbstractAnimation.State.Stopped


def test_overlay_binds_adjacent_steps_seeks_and_context_visibility(qapp: QApplication) -> None:
    """Use canonical frames so scrolling cannot be triggered by every clock tick."""
    document = LyricsDocument(source_id="test", song_id="depth", timing=TimingKind.LINE, lines=_lines(0, 30))
    overlay = build_overlay(LyricsState(), Config(context_lines=10))
    try:
        overlay._on_frame(project_document(document, 125.0))
        overlay._on_frame(project_document(document, 135.0))
        animation = overlay._next_label.findChild(QVariantAnimation)
        assert animation is not None and animation.state() is QAbstractAnimation.State.Running
        assert overlay._prev_label.text() == "Lyric 12"
        assert overlay._next_label.text() == "Lyric 14"
        animation.pause()
        animation.setCurrentTime(120)
        overlay._on_frame(project_document(document, 135.1))
        assert animation.currentTime() == 120
        overlay._on_frame(project_document(document, 225.0))
        assert animation.state() is QAbstractAnimation.State.Stopped
        assert overlay._next_label.text() == "Lyric 23"
        overlay.apply_config(replace(overlay._config, current_line_only=True))
        assert overlay._prev_label.isHidden() and overlay._next_label.isHidden()
        assert overlay._config.context_lines == 10
    finally:
        overlay.close()
