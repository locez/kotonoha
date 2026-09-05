"""The lyrics overlay window.

A frameless, translucent, top-most window that floats above fullscreen apps via
the Wayland layer-shell bridge (with graceful fallback). It shows the previous
line, the current line with a karaoke sweep, an optional translation, and the
next line. The application display coordinator supplies the current media time;
the widget only applies presentation settings and paints it.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QCloseEvent,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QToolButton,
    QWidget,
)

from ...app.intents import ChangePosition, ChangeTrackOffset
from ...config import Config
from ...display.models import DisplayFrame
from ...display.offsets import EMPTY_TRACK_OFFSETS, TrackOffsetKey, TrackOffsetReader
from ...lyrics.match import TrackMetadata
from ...platform import OverlayPlatformFactory, QtWindowHost
from ...platform.overlay_contracts import DragMode, SurfacePort, SurfaceResult
from ...strings import Translator
from .chrome import OverlayChromeController
from .content import OverlayContentController
from .geometry import ScreenLike
from .presentation import OverlayPresentationController
from .state import LyricsState
from .surface import OverlaySurfaceController, PositionCommit
from .view import OverlayViewBuilder

logger = logging.getLogger(__name__)


class LyricsOverlay(QWidget):
    # Emitted when the on-HUD lock button is clicked (controller flips passthrough).
    passthrough_toggle_requested = pyqtSignal()
    # Emitted when the on-HUD gear button is clicked.
    settings_requested = pyqtSignal()
    # Emitted with the current normalized track when manual lyric search is requested.
    lyrics_search_requested = pyqtSignal(object)
    # Emitted after a drag, with the edge margin, horizontal offset relative to
    # the target output's center, and output name. The offset is output-local;
    # virtual-desktop origins are deliberately excluded.
    position_changed = pyqtSignal(object)
    track_offset_changed = pyqtSignal(object)

    _container: QWidget
    _feedback: QLabel
    _control_bar: QWidget
    _search_btn: QToolButton
    _lock_btn: QToolButton
    _earlier_btn: QToolButton
    _later_btn: QToolButton
    _settings_btn: QToolButton
    _chrome: OverlayChromeController
    _content: OverlayContentController
    _presentation: OverlayPresentationController
    _activation_timer: QTimer
    _activation_retry_timer: QTimer
    _input_region_timer: QTimer
    _blur_timer: QTimer
    _control_click_timer: QTimer
    _track_offsets: TrackOffsetReader
    _closed: bool
    _closing: bool
    _suppress_control_click: bool

    def __init__(
        self,
        state: LyricsState,
        config: Config,
        *,
        platform_factory: OverlayPlatformFactory,
        translator: Translator | None = None,
        track_offsets: TrackOffsetReader = EMPTY_TRACK_OFFSETS,
    ) -> None:
        super().__init__()
        self._state = state
        self._config = config
        self._track_offsets = track_offsets
        self._translator = translator if translator is not None else Translator(config.ui_language)
        self._closed = False
        self._closing = False
        self._suppress_control_click = False
        self._passthrough = config.passthrough
        self._chrome = OverlayChromeController(self, self._translator)
        app = QApplication.instance()
        self._activation_timer = QTimer(self)
        self._activation_timer.setSingleShot(True)
        self._activation_timer.timeout.connect(self._activate_deferred)
        self._activation_retry_timer = QTimer(self)
        self._activation_retry_timer.setSingleShot(True)
        self._activation_retry_timer.timeout.connect(self._activate_deferred)
        self._input_region_timer = QTimer(self)
        self._input_region_timer.setSingleShot(True)
        self._input_region_timer.timeout.connect(self._apply_input_region)
        self._blur_timer = QTimer(self)
        self._blur_timer.setSingleShot(True)
        self._blur_timer.timeout.connect(self._apply_blur)
        self._control_click_timer = QTimer(self)
        self._control_click_timer.setSingleShot(True)
        self._control_click_timer.timeout.connect(self._clear_control_click_suppression)
        self._surface = OverlaySurfaceController(
            self,
            config,
            platform_factory=platform_factory,
            band_height=self._band_height,
            container_geometry=self._container_geometry,
        )
        self.setWindowTitle("Kotonoha")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._build_ui()
        self._surface.set_rebuild_complete_handler(self.show)
        self._surface.set_position_commit_handler(self._emit_position_commit)
        self._surface.prepare()
        self.apply_config(config)

        self._state.frame_changed.connect(self._on_frame)
        if isinstance(app, QGuiApplication):
            app.screenAdded.connect(self._on_screen_added)
            app.screenRemoved.connect(self._on_screen_removed)

        self._on_frame(self._state.frame)

    @property
    def _host(self) -> QtWindowHost:
        """Expose the toolkit host for platform adapter tests."""
        return self._surface.host

    @property
    def _platform(self) -> SurfacePort:
        """Expose the selected surface port for focused platform tests."""
        return self._surface.platform.surface

    @property
    def _layer_pos(self) -> QPoint:
        """Expose the surface-local position to existing placement tests."""
        return self._surface.layer_pos

    @_layer_pos.setter
    def _layer_pos(self, value: QPoint) -> None:
        self._surface.layer_pos = value

    @property
    def _active_screen(self) -> ScreenLike | None:
        """Expose the active output to existing placement tests."""
        return self._surface.active_screen

    @_active_screen.setter
    def _active_screen(self, value: ScreenLike | None) -> None:
        self._surface.active_screen = value

    @property
    def _dragging(self) -> bool:
        """Expose drag state owned by the platform surface."""
        return self._surface.dragging

    @_dragging.setter
    def _dragging(self, value: bool) -> None:
        self._surface.dragging = value

    @property
    def _drag_moved(self) -> bool:
        """Expose drag state owned by the platform surface."""
        return self._surface.drag_moved

    @_drag_moved.setter
    def _drag_moved(self, value: bool) -> None:
        self._surface.drag_moved = value

    @property
    def _drag_applied(self) -> bool:
        """Expose drag state owned by the platform surface."""
        return self._surface.drag_applied

    @_drag_applied.setter
    def _drag_applied(self, value: bool) -> None:
        self._surface.drag_applied = value

    @property
    def _drag_local(self) -> QPoint:
        """Expose the last local pointer coordinate to placement tests."""
        return self._surface.drag_local

    @_drag_local.setter
    def _drag_local(self, value: QPoint) -> None:
        self._surface.drag_local = value

    def _container_geometry(self) -> QRect:
        """Return the current pill geometry for the platform surface boundary."""
        return self._container.geometry()

    def shutdown(self) -> SurfaceResult:
        """Stop owned timers and release the platform surface explicitly."""
        if self._closed:
            return SurfaceResult.applied()
        self._closing = True
        self._activation_timer.stop()
        self._activation_retry_timer.stop()
        self._input_region_timer.stop()
        self._blur_timer.stop()
        self._control_click_timer.stop()
        self._content.stop()
        result = self._surface.close()
        if result.succeeded:
            self._closed = True
            self._closing = False
        return result

    # --- UI ---

    def _build_ui(self) -> None:
        widgets = OverlayViewBuilder(self, self._chrome).build()
        self._container = widgets.container
        self._container.installEventFilter(self)
        self._prev_label = widgets.previous
        self._current = widgets.current
        self._feedback = widgets.feedback
        self._translation = widgets.translation
        self._next_label = widgets.next
        self._presentation = OverlayPresentationController(
            self._config,
            self._container,
            self._prev_label,
            self._current,
            self._feedback,
            self._translation,
            self._next_label,
            window_size=self._window_size,
        )
        self._content = OverlayContentController(
            self._state,
            self._config,
            self._prev_label,
            self._current,
            self._feedback,
            self._translation,
            self._next_label,
            self._container,
            timer_parent=self,
            on_input_region_refresh=self._refresh_input_region,
            on_offset_changed=self._emit_track_offset_changed,
            track_offsets=self._track_offsets,
            translator=self._translator,
        )

    def _update_lock_icon(self) -> None:
        self._chrome.update_icons()

    def _update_chrome(self) -> None:
        """Locking only hides the interactive controls (you can't click them once
        the surface is click-through). The panel background is governed by the
        panel-style setting, NOT the lock state — see paintEvent."""
        self._chrome.update_visibility()

    def _request_lyrics_search(self) -> None:
        """Publish the current track as an editable manual-search starting point."""
        track = self._state.frame.track
        if track is None or not track.title.strip():
            return
        self.lyrics_search_requested.emit(
            TrackMetadata(track.title, track.artist, track.album, track.duration_s)
        )

    # --- config ---

    def apply_config(self, config: Config) -> None:
        """Apply configuration to the surface, presentation, and overlay chrome."""
        if self._closed or self._closing:
            return
        self._config = config
        self._surface.update_config(config)
        self._content.update_config(config)
        self._surface.set_input_mode(config.passthrough)
        self._passthrough = config.passthrough
        screen = self._configured_screen()
        if screen is None:
            screen = self._active_screen
        if screen is None:
            screen = self.screen()
        self._surface.set_active_screen(screen)
        self._update_lock_icon()
        self._presentation.apply_config(config)

        # Opacity is the panel's own fill translucency (see the presentation owner),
        # so the window itself stays fully opaque — the lyric text is always crisp and
        # lowering opacity (even to 0) only fades the panel, never the text. (We do NOT
        # call setWindowOpacity: the Qt Wayland plugin ignores it and just warns.)
        self._update_chrome()
        self._apply_window_geometry()
        self.update()
        self._schedule_blur()  # panel_style may have changed

    # --- geometry (fixed-size, margin-positioned panel) ---

    def _band_height(self) -> int:
        """Return the stable surface height from the presentation owner."""
        return self._presentation.band_height()

    def _configured_screen(self) -> ScreenLike | None:
        """Return the configured screen through the platform surface owner."""
        return self._surface.configured_screen(QGuiApplication.screens())

    def _target_screen(self) -> ScreenLike | None:
        """Select a usable output for view geometry and platform operations."""
        screens = QGuiApplication.screens()
        return self._surface.target_screen(
            screens,
            configured=self._configured_screen(),
            widget_screen=self.screen(),
            primary=QApplication.primaryScreen(),
        )

    def _on_screen_removed(self, screen: ScreenLike) -> None:
        """Forward screen removal to the surface lifecycle owner."""
        self._surface.screen_removed(screen, QGuiApplication.screens())

    def _on_screen_added(self, screen: ScreenLike) -> None:
        """Forward screen addition to the surface lifecycle owner."""
        del screen
        self._surface.screen_added(QGuiApplication.screens())

    def _window_size(self) -> tuple[int, int]:
        """Return the stable surface size for the active output."""
        return self._surface.window_size(self._target_screen())

    def _apply_window_geometry(self, *, reset_position: bool = True) -> None:
        """Delegate sizing and placement to the platform surface owner."""
        self._surface.apply_window_geometry(QGuiApplication.screens(), reset_position=reset_position)

    # --- frame handling ---

    def _on_frame(self, frame: DisplayFrame) -> None:
        if not self._closed and not self._closing:
            self._chrome.update_track(frame.track is not None and bool(frame.track.title.strip()))
            self._content.on_frame(frame)

    # --- layer shell / placement ---

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        if self._closed or self._closing:
            return
        # A rebuild has already computed the position; recomputing it here would
        # throw away the output the surface was just put back on.
        self._apply_window_geometry(reset_position=not self._surface.consume_preserve_position())
        self._activation_timer.start(0)
        self._activation_retry_timer.start(100)

    def _activate_deferred(self) -> None:
        """Run an owned activation retry while the widget is still alive."""
        if not self._closed and not self._closing:
            self.activate_layer_shell()

    def activate_layer_shell(self) -> bool:
        """Promote to a layer surface. MUST be called before the first show().

        Returns whether the surface is now a layer surface, so a caller that is
        rebuilding one can tell a real rebuild from a fallback."""
        if self._closed or self._closing:
            return False
        return self._surface.activate(QGuiApplication.screens(), fallback=self._fallback_position)

    def _fallback_position(self, screen: ScreenLike | None = None) -> None:
        """Position as an ordinary window, for X11 and for a failed activation.

        Through the host rather than the platform: this runs when Layer Shell is
        unavailable *or* when it is available and activation failed, and in the
        second case the Layer Shell adapter is still in place — asking it to move
        would set a native anchor on a surface that was never promoted, which is
        not a fallback at all.
        """
        self._surface.fallback_position(screen if screen is not None else self._target_screen())

    def set_passthrough(self, enabled: bool) -> None:
        if self._closed or self._closing:
            return
        self._passthrough = enabled
        self._surface.set_input_mode(enabled)
        self._update_lock_icon()
        self._update_chrome()
        # Chrome visibility just changed the pill size; lay out, then set the region.
        self._schedule_input_region()

    def _apply_input_region(self) -> None:
        """Locked -> full click-through. Unlocked -> only the visible pill catches
        clicks, so the big transparent band around it stays click-through."""
        if not self._closed and not self._closing:
            self._surface.set_input_mode(self._passthrough)

    def _schedule_input_region(self) -> None:
        """Schedule one owned input-region update after Qt layout settles."""
        if not self._closed and not self._closing:
            self._input_region_timer.start(0)

    def _refresh_input_region(self) -> None:
        if not self._passthrough:
            self._schedule_input_region()

    def _nudge_earlier(self) -> None:
        """Delegate an earlier offset intent to the content owner."""
        if not self._closed and not self._closing:
            self._content.nudge_earlier()

    def _nudge_later(self) -> None:
        """Delegate a later offset intent to the content owner."""
        if not self._closed and not self._closing:
            self._content.nudge_later()

    def _on_lock_clicked(self) -> None:
        """Suppress a lock click retargeted from a completed window drag."""
        if not self._finish_control_drag_if_needed():
            self.passthrough_toggle_requested.emit()

    def _on_earlier_clicked(self) -> None:
        """Suppress an offset click retargeted from a completed window drag."""
        if not self._finish_control_drag_if_needed():
            self._nudge_earlier()

    def _on_later_clicked(self) -> None:
        """Suppress an offset click retargeted from a completed window drag."""
        if not self._finish_control_drag_if_needed():
            self._nudge_later()

    def _on_settings_clicked(self) -> None:
        """Suppress a settings click retargeted from a completed window drag."""
        if not self._finish_control_drag_if_needed():
            self.settings_requested.emit()

    def _finish_control_drag_if_needed(self) -> bool:
        """Finish a release delivered to a moving child without activating it."""
        if self._dragging and self._drag_moved:
            self._finish_drag(None)
        return self._suppress_control_click

    def _clear_control_click_suppression(self) -> None:
        self._suppress_control_click = False

    def _emit_track_offset_changed(self, track_key: TrackOffsetKey, offset_ms: int) -> None:
        """Publish an offset applied by the content owner."""
        self.track_offset_changed.emit(ChangeTrackOffset(track_key, offset_ms))

    def _apply_blur(self) -> None:
        """Blur the compositor content behind the pill for the frosted-glass style;
        no-op where no blur protocol exists, leaving the translucent fill."""
        if not self._closed and not self._closing:
            self._surface.apply_blur()

    def _schedule_blur(self) -> None:
        """Schedule one owned blur update after the pill geometry settles."""
        if not self._closed and not self._closing:
            self._blur_timer.start(0)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        # The container resizes as the pill/lyric changes size; keep the input
        # region matched to it. This fixes the initially oversized region before
        # the first frame shrinks the pill to its real size.
        if a0 is self._container and a1 is not None:
            if a1.type() in {QEvent.Type.Move, QEvent.Type.Resize}:
                # The rounded panel antialiases one pixel beyond the container's
                # geometry. Repaint the full translucent surface so an old edge
                # cannot survive a layout-driven move or resize.
                self.update()
            if a1.type() == QEvent.Type.Resize:
                self._refresh_input_region()
                self._schedule_blur()  # keep the blur region on the pill
        return super().eventFilter(a0, a1)

    # --- drag to reposition (only while unlocked) ---
    #
    # An ordinary Wayland window delegates the entire gesture to the compositor via
    # startSystemMove(), so it never enters the manual update/persistence path.
    # Layer Shell and X11 use the selected platform drag port's manual model:
    # press-relative feedback for KWin and incremental global feedback for niri.
    # Manual strategies return the position actually applied after coordinate
    # conversion, so persistence never reconstructs movement from a second source.

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and not self._passthrough and a0.button() == Qt.MouseButton.LeftButton:
            local = a0.position().toPoint()
            global_position = a0.globalPosition().toPoint()
            mode = self._surface.begin_drag(local, global_position)
            if mode is DragMode.SYSTEM:
                a0.accept()
                return
            if mode is not DragMode.MANUAL:
                super().mousePressEvent(a0)
                return
            a0.accept()
        else:
            super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and self._dragging and a0.buttons() & Qt.MouseButton.LeftButton:
            screen = self._target_screen()
            if screen is None:
                a0.accept()
                return
            local = a0.position().toPoint()
            # Keep the surface alive for the entire pointer grab. Recreating it
            # at an output boundary destroys the Wayland pointer grab and makes
            # the next mouse event disappear; the selected platform strategy
            # decides whether the panel is bounded or can continue across outputs.
            global_position = a0.globalPosition().toPoint()
            moved = self._surface.update_drag(local, global_position)
            if not moved.succeeded:
                # The surface is where it was, so the drag has not taken effect.
                # Remember that, or the release would save a position the visible
                # window never reached.
                logger.debug("Drag update was not applied: %s", moved.reason)
            # The platform commits the surface, so avoid repainting heavy lyric text.
            a0.accept()
        else:
            super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        if self._dragging:
            cursor_local = a0.position().toPoint() if a0 is not None else None
            self._finish_drag(cursor_local)
            if a0 is not None:
                a0.accept()
        else:
            super().mouseReleaseEvent(a0)

    def _finish_drag(self, cursor_local: QPoint | None) -> None:
        """End, persist, and restore native state for one manual drag."""
        release = self._surface.end_drag()
        if release.should_commit:
            self._commit_drag_position(cursor_local)
        elif release.moved:
            # The window never went where the drag asked, so saving that position
            # would put the config and the visible window out of step.
            logger.info(
                "Not saving the dragged position: %s",
                self._platform.capabilities.client_positioning_reason,
            )
        if not release.moved:
            return
        # A compositor may reconfigure or crop the transparent surface at an output
        # edge. Re-submit the panel's input rectangle after the final placement so
        # the next grab remains live.
        self._apply_input_region()
        self._suppress_control_click = True
        self._control_click_timer.start(0)

    def _commit_drag_position(self, cursor_local: QPoint | None = None) -> None:
        """Persist the output and edge placement after a drag.

        The selected drag strategy may keep a surface inside its bound output while
        it is grabbed. For strategies that allow crossing, only after release do we
        select the output under the cursor and remap the surface, when necessary,
        so the next drag starts with that output as its local coordinate system.
        """
        result = self._surface.commit_drag_position(
            cursor_local,
            surface_screen=self._target_screen(),
            screens=QGuiApplication.screens(),
            window_size=self._window_size(),
        )
        if result is not None:
            self._emit_position_commit(result)

    def _emit_position_commit(self, commit: PositionCommit) -> None:
        """Emit a completed placement commit from the lifecycle callback."""
        self.position_changed.emit(
            ChangePosition(
                commit.margin_edge,
                commit.margin_x,
                commit.screen_name,
                commit.screen_width,
                commit.screen_height,
            )
        )

    @property
    def passthrough(self) -> bool:
        return self._passthrough

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Stop owned timers and release the platform surface before destruction."""
        result = self.shutdown()
        if not result.succeeded:
            logger.warning("Overlay surface shutdown was incomplete: %s", result.reason)
            if a0 is not None:
                a0.ignore()
            return
        super().closeEvent(a0)

    # --- painting ---

    def paintEvent(self, a0: QPaintEvent | None) -> None:  # noqa: ARG002
        painter = QPainter(self)
        self._presentation.paint_panel(painter, self._container.geometry())

    def reset(self) -> None:
        self._content.reset()
