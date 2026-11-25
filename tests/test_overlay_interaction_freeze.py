"""Behavior contracts for overlay hover geometry freezing and offset button repeat."""

from __future__ import annotations

import os
from collections.abc import Callable
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from overlay_helpers import FakeScreen, LayerShellStub, UnavailableController, build_overlay
from PyQt6.QtCore import QEvent, QEventLoop, QObject, QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QMouseEvent
from PyQt6.QtWidgets import QApplication
from test_overlay import display_frame

from kotonoha.app.display_coordinator import DisplayCoordinator
from kotonoha.app.intents import ChangeTrackOffset
from kotonoha.config import Config, PanelWidthMode
from kotonoha.display.models import DisplayOptions, ResolutionState
from kotonoha.display.offsets import TrackOffsetKey
from kotonoha.display.presentation import DisplayEngine
from kotonoha.display.timeline import TimelineEngine
from kotonoha.lyrics.models import LyricLine, LyricsDocument, TimingKind
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from kotonoha.ui.overlay.freeze import OverlayInteractionFreezeController
from kotonoha.ui.overlay.publisher import QtDisplayPublisher
from kotonoha.ui.overlay.state import LyricsState


def _settle(qapp: QApplication) -> None:
    """Flush queued zero-delay geometry timers and layout passes."""
    for _ in range(4):
        qapp.processEvents()


def _wait_until(predicate: Callable[[], bool], *, timeout_ms: int = 1500) -> bool:
    """Spin a local Qt event loop until ``predicate()`` becomes true or times out."""
    if predicate():
        return True
    loop = QEventLoop()
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    poll = QTimer()
    poll.setInterval(15)

    def check() -> None:
        if predicate():
            loop.quit()

    poll.timeout.connect(check)
    deadline.start(timeout_ms)
    poll.start()
    loop.exec()
    poll.stop()
    deadline.stop()
    return predicate()


class _MutableTrackOffsets:
    def __init__(self) -> None:
        self._values: dict[TrackOffsetKey, int] = {}

    def offset_for(self, key: TrackOffsetKey) -> int:
        return self._values.get(key, 0)

    def apply(self, change: ChangeTrackOffset) -> None:
        self._values[change.key] = change.offset_ms


def test_freeze_controller_lifecycle_cancels_release_on_reenter_drag_and_stop(qapp: QApplication) -> None:
    """Re-entering, dragging, keep-alive, and stop govern release timing cleanly."""
    parent = QObject()
    transitions: list[tuple[bool, int | None]] = []
    controller = OverlayInteractionFreezeController(
        parent,
        on_state_changed=lambda active, width: transitions.append((active, width)),
        unfreeze_delay_ms=25,
    )
    try:
        controller.enter(320)
        assert transitions == [(True, 320)]
        assert controller.active is True

        # Re-entering before the grace timer fires cancels release.
        controller.leave()
        controller.enter(200)
        assert not _wait_until(lambda: not controller.active, timeout_ms=70)
        assert transitions == [(True, 320)]

        # Dragging holds the freeze across a Leave until the drag ends.
        controller.begin_drag()
        controller.leave()
        assert not _wait_until(lambda: not controller.active, timeout_ms=70)
        controller.end_drag()
        assert _wait_until(lambda: not controller.active, timeout_ms=300)
        assert transitions == [(True, 320), (False, None)]

        # Button keep-alive activates and later releases after idle.
        controller.keep_alive(280)
        assert transitions[-1] == (True, 280)
        assert _wait_until(lambda: not controller.active, timeout_ms=300)
        assert transitions[-1] == (False, None)

        # Stopping during a pending leave cancels the release callback without emitting.
        controller.enter(300)
        controller.leave()
        before_stop = len(transitions)
        controller.stop()
        assert controller.active is False
        assert not _wait_until(lambda: len(transitions) > before_stop, timeout_ms=70)
    finally:
        controller.stop()
        parent.deleteLater()
        _settle(qapp)


def test_hover_freezes_fit_pill_width_and_button_x_across_line_changes(qapp: QApplication) -> None:
    """Hovering the FIT-mode pill keeps control buttons stationary as lyrics change length."""
    screen = FakeScreen("DP-1", 0, 0, 1920, 1080)
    overlay = build_overlay(
        LyricsState(),
        Config(panel_width_mode=PanelWidthMode.FIT, fx_animate=False),
        UnavailableController(),
    )
    medium = LyricLine(0, "m", 0.0, 4.0, "A medium length lyric line here", "", ())
    short = LyricLine(1, "s", 4.0, 8.0, "Hi", "", ())
    very_long = LyricLine(
        2,
        "l",
        8.0,
        12.0,
        "A remarkably long lyric line that would normally expand the adaptive pill significantly wider",
        "",
        (),
    )
    try:
        with patch.object(QGuiApplication, "screens", return_value=[screen]):
            overlay.show()
            overlay._on_frame(display_frame(has_lyrics=True, current=medium, current_time=1.0, is_playing=True))
            _settle(qapp)

            frozen_width = overlay._container.width()
            frozen_button_x = overlay._earlier_btn.mapTo(overlay, QPoint(0, 0)).x()

            QApplication.sendEvent(overlay._container, QEvent(QEvent.Type.Enter))
            _settle(qapp)

            overlay._on_frame(display_frame(has_lyrics=True, current=short, current_time=5.0, is_playing=True))
            _settle(qapp)
            assert overlay._container.width() == frozen_width
            assert overlay._earlier_btn.mapTo(overlay, QPoint(0, 0)).x() == frozen_button_x

            overlay._on_frame(
                display_frame(
                    has_lyrics=True,
                    previous=very_long,
                    current=very_long,
                    next=very_long,
                    current_time=9.0,
                    is_playing=True,
                )
            )
            _settle(qapp)
            assert overlay._container.width() == frozen_width
            assert overlay._earlier_btn.mapTo(overlay, QPoint(0, 0)).x() == frozen_button_x

            QApplication.sendEvent(overlay._container, QEvent(QEvent.Type.Leave))
            _settle(qapp)
            # Still frozen immediately after Leave during the brief grace period.
            assert overlay._container.width() == frozen_width

            assert _wait_until(lambda: overlay._container.width() > frozen_width), (
                "pill did not unfreeze and expand to fit the longer lyric after leaving"
            )
    finally:
        overlay.shutdown()
        overlay.deleteLater()
        _settle(qapp)


def test_bottom_anchored_hover_keeps_top_buttons_stationary_and_restores_bottom_edge(qapp: QApplication) -> None:
    """Bottom-anchored overlays pin the top bar during hover and restore bottom alignment on release."""
    screen = FakeScreen("DP-1", 0, 0, 1920, 1080)
    overlay = build_overlay(
        LyricsState(),
        Config(anchor_top=False, margin_edge=64, panel_width_mode=PanelWidthMode.FIT, fx_animate=False),
        LayerShellStub(),
    )
    with_translation = LyricLine(0, "t", 0.0, 4.0, "First lyric line", "第一句歌词翻译", ())
    without_translation = LyricLine(1, "n", 4.0, 8.0, "Second line", "", ())
    try:
        with patch.object(QGuiApplication, "screens", return_value=[screen]):
            overlay.show()
            overlay._on_frame(
                display_frame(has_lyrics=True, current=with_translation, current_time=1.0, is_playing=True)
            )
            _settle(qapp)

            initial_y = overlay._layer_pos.y()
            initial_height = overlay.height()
            initial_bottom = initial_y + initial_height
            initial_button_screen_y = initial_y + overlay._earlier_btn.mapTo(overlay, QPoint(0, 0)).y()

            QApplication.sendEvent(overlay._container, QEvent(QEvent.Type.Enter))
            _settle(qapp)

            overlay._on_frame(
                display_frame(has_lyrics=True, current=without_translation, current_time=5.0, is_playing=True)
            )
            _settle(qapp)

            assert overlay.height() < initial_height
            current_button_screen_y = overlay._layer_pos.y() + overlay._earlier_btn.mapTo(overlay, QPoint(0, 0)).y()
            assert current_button_screen_y == initial_button_screen_y
            assert overlay._layer_pos.y() == initial_y

            QApplication.sendEvent(overlay._container, QEvent(QEvent.Type.Leave))
            assert _wait_until(lambda: overlay._layer_pos.y() + overlay.height() == initial_bottom), (
                "bottom edge was not restored after leaving the bottom-anchored overlay"
            )
    finally:
        overlay.shutdown()
        overlay.deleteLater()
        _settle(qapp)


def test_offset_buttons_support_auto_repeat_and_keep_position_when_line_jumps(qapp: QApplication) -> None:
    """Offset buttons support hold-to-repeat and stay under the cursor when a click switches lines."""
    screen = FakeScreen("DP-1", 0, 0, 1920, 1080)
    offsets = _MutableTrackOffsets()
    state = LyricsState()
    overlay = build_overlay(
        state,
        Config(panel_width_mode=PanelWidthMode.FIT, fx_animate=False),
        UnavailableController(),
        track_offsets=offsets,
    )
    first = LyricLine(0, "line-0", 0.0, 1.0, "A fairly wide opening line of lyrics", "", ())
    second = LyricLine(1, "line-1", 1.0, 2.0, "Short", "", ())
    document = LyricsDocument("test", title="Song", artist="Artist", timing=TimingKind.LINE, lines=(first, second))
    track = TrackIdentity("test", "player", stable_id="song", title="Song", artist="Artist")
    playback = PlaybackObservation("test", "player", track, PlaybackStatus.PAUSED, 0.95, 2.0, 100.0)
    coordinator = DisplayCoordinator(
        QtDisplayPublisher(state), presenter=DisplayEngine(), timeline=TimelineEngine()
    )
    try:
        assert overlay._earlier_btn.autoRepeat() is True
        assert overlay._later_btn.autoRepeat() is True
        assert overlay._earlier_btn.autoRepeatDelay() > 0
        assert overlay._earlier_btn.autoRepeatInterval() > 0

        with patch.object(QGuiApplication, "screens", return_value=[screen]):
            overlay.show()
            coordinator.publish_resolution(playback, document, ResolutionState.AVAILABLE)
            _settle(qapp)

            def apply_offset(change: ChangeTrackOffset) -> None:
                offsets.apply(change)
                coordinator.set_options(DisplayOptions(track_offsets_ms={change.key: change.offset_ms}))

            overlay.track_offset_changed.connect(apply_offset)
            QApplication.sendEvent(overlay._container, QEvent(QEvent.Type.Enter))
            _settle(qapp)

            button_x_before = overlay._earlier_btn.mapTo(overlay, QPoint(0, 0)).x()
            width_before = overlay._container.width()

            overlay._earlier_btn.click()
            _settle(qapp)

            assert overlay._current.text == "Short"
            assert overlay._container.width() == width_before
            assert overlay._earlier_btn.mapTo(overlay, QPoint(0, 0)).x() == button_x_before
    finally:
        overlay.shutdown()
        overlay.deleteLater()
        _settle(qapp)


def test_config_change_and_lock_release_hover_freeze_immediately(qapp: QApplication) -> None:
    """Explicit config updates and locking release any active hover freeze."""
    screen = FakeScreen("DP-1", 0, 0, 1920, 1080)
    overlay = build_overlay(
        LyricsState(),
        Config(panel_width_mode=PanelWidthMode.FIT, fx_animate=False),
        UnavailableController(),
    )
    medium = LyricLine(0, "m", 0.0, 4.0, "A medium length lyric line here", "", ())
    short = LyricLine(1, "s", 4.0, 8.0, "Hi", "", ())
    try:
        with patch.object(QGuiApplication, "screens", return_value=[screen]):
            overlay.show()
            overlay._on_frame(display_frame(has_lyrics=True, current=medium, current_time=1.0, is_playing=True))
            _settle(qapp)

            frozen_width = overlay._container.width()
            QApplication.sendEvent(overlay._container, QEvent(QEvent.Type.Enter))
            overlay._on_frame(display_frame(has_lyrics=True, current=short, current_time=5.0, is_playing=True))
            _settle(qapp)
            assert overlay._container.width() == frozen_width

            overlay.set_passthrough(True)
            _settle(qapp)
            assert overlay._container.width() < frozen_width

            overlay.set_passthrough(False)
            overlay._on_frame(display_frame(has_lyrics=True, current=medium, current_time=1.0, is_playing=True))
            _settle(qapp)
            frozen_width = overlay._container.width()
            QApplication.sendEvent(overlay._container, QEvent(QEvent.Type.Enter))
            overlay._on_frame(display_frame(has_lyrics=True, current=short, current_time=5.0, is_playing=True))
            _settle(qapp)
            assert overlay._container.width() == frozen_width

            overlay.apply_config(Config(panel_width_mode=PanelWidthMode.FIT, fx_animate=False))
            _settle(qapp)
            assert overlay._container.width() < frozen_width
    finally:
        overlay.shutdown()
        overlay.deleteLater()
        _settle(qapp)


def test_dragging_while_hover_frozen_does_not_snap_back_to_old_bottom_edge(qapp: QApplication) -> None:
    """A drag committed during hover replaces the pre-hover bottom anchor instead of reverting."""
    screen = FakeScreen("DP-1", 0, 0, 1920, 1080)
    overlay = build_overlay(
        LyricsState(),
        Config(anchor_top=False, margin_edge=64, panel_width_mode=PanelWidthMode.FIT, fx_animate=False),
        LayerShellStub(),
    )
    wide_with_translation = LyricLine(0, "t", 0.0, 4.0, "A fairly wide opening line of lyrics", "第一句歌词翻译", ())
    short_without_translation = LyricLine(1, "n", 4.0, 8.0, "Hi", "", ())
    try:
        with patch.object(QGuiApplication, "screens", return_value=[screen]):
            overlay.show()
            overlay._on_frame(
                display_frame(has_lyrics=True, current=wide_with_translation, current_time=1.0, is_playing=True)
            )
            _settle(qapp)
            old_y = overlay._layer_pos.y()
            frozen_width = overlay._container.width()

            QApplication.sendEvent(overlay._container, QEvent(QEvent.Type.Enter))
            _settle(qapp)

            overlay.mousePressEvent(
                QMouseEvent(
                    QEvent.Type.MouseButtonPress,
                    QPointF(20, 20),
                    QPointF(20, 20),
                    QPointF(420, old_y + 20),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
            )
            overlay.mouseMoveEvent(
                QMouseEvent(
                    QEvent.Type.MouseMove,
                    QPointF(20, -100),
                    QPointF(20, -100),
                    QPointF(420, old_y - 100),
                    Qt.MouseButton.NoButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
            )
            overlay.mouseReleaseEvent(
                QMouseEvent(
                    QEvent.Type.MouseButtonRelease,
                    QPointF(20, -100),
                    QPointF(20, -100),
                    QPointF(420, old_y - 100),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                )
            )
            _settle(qapp)
            dragged_y = overlay._layer_pos.y()
            assert dragged_y < old_y - 50

            overlay._on_frame(
                display_frame(has_lyrics=True, current=short_without_translation, current_time=5.0, is_playing=True)
            )
            _settle(qapp)
            assert overlay._container.width() == frozen_width

            QApplication.sendEvent(overlay._container, QEvent(QEvent.Type.Leave))
            # Wait for the unfreeze to actually complete (pill shrinks to "Hi").
            assert _wait_until(lambda: overlay._container.width() < frozen_width)
            assert overlay._layer_pos.y() < old_y - 50
    finally:
        overlay.shutdown()
        overlay.deleteLater()
        _settle(qapp)
