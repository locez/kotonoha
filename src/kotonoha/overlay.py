"""The lyrics overlay window.

A frameless, translucent, top-most window that floats above fullscreen apps via
the Wayland layer-shell bridge (with graceful fallback). It shows the previous
line, the current line with a karaoke sweep, an optional translation, and the
next line. A ~60fps timer advances the local media clock so the sweep stays
smooth between probe heartbeats.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from PyQt6 import sip
from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QMouseEvent, QPainter, QPaintEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .clock import MediaClock
from .config import Config
from .icons import lock_icon, settings_icon
from .karaoke_label import KaraokeLabel
from .model import EMPTY_SNAPSHOT, LyricLine, LyricsSnapshot
from .native import LayerShellController, default_package_dir
from .state import LyricsState

logger = logging.getLogger(__name__)

RENDER_INTERVAL_MS = 16  # ~60fps


CONTROL_BUTTON_STYLE = """
QToolButton {
    background: rgba(255, 255, 255, 28);
    color: rgba(255, 255, 255, 210);
    border: none;
    border-radius: 11px;
    font-size: 13px;
}
QToolButton:hover { background: rgba(255, 255, 255, 60); }
QToolButton:pressed { background: rgba(255, 255, 255, 90); }
"""


class LyricsOverlay(QWidget):
    # Emitted when the on-HUD lock button is clicked (controller flips passthrough).
    passthrough_toggle_requested = pyqtSignal()
    # Emitted when the on-HUD gear button is clicked.
    settings_requested = pyqtSignal()
    # Emitted after a drag, with the new (margin_edge, margin_x) so config can persist.
    position_changed = pyqtSignal(int, int)

    def __init__(self, state: LyricsState, config: Config, controller: LayerShellController | None = None) -> None:
        super().__init__()
        self._state = state
        self._config = config
        self._clock = MediaClock()
        self._passthrough = config.passthrough
        self._layer_pos = QPoint()  # screen-local top-left of the surface
        self._dragging = False
        self._drag_local = QPoint()
        app = QApplication.instance()
        desktop = app.property("xdg_current_desktop") if app is not None else ""
        self._controller = controller or LayerShellController(
            default_package_dir(),
            QGuiApplication.platformName(),
            desktop or "",
        )

        self.setWindowTitle("Kotonoha")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._build_ui()
        self.apply_config(config)

        self._state.snapshot_changed.connect(self._on_snapshot)
        self._state.time_ticked.connect(self._on_tick)

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(RENDER_INTERVAL_MS)
        self._render_timer.timeout.connect(self._render_tick)
        self._render_timer.start()

        self._on_snapshot(self._state.snapshot)

    # --- UI ---

    def _build_ui(self) -> None:
        self._container = QWidget(self)
        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(22, 10, 22, 14)
        layout.setSpacing(4)

        layout.addWidget(self._build_control_bar())

        self._prev_label = self._make_context_label()
        self._current = KaraokeLabel(self._container)
        # Translation is a KaraokeLabel too: no per-word timing -> it sweeps the
        # whole line following the current line's progress (the user's choice).
        self._translation = KaraokeLabel(self._container)
        self._next_label = self._make_context_label()

        for w in (self._prev_label, self._current, self._translation, self._next_label):
            layout.addWidget(w, alignment=Qt.AlignmentFlag.AlignHCenter)
        # Cheap readability shadows on the context labels (they repaint only on
        # snapshot changes, so a blur effect here costs nothing per frame; the
        # karaoke labels draw their own offset shadow instead).
        for label in (self._prev_label, self._next_label):
            label.setGraphicsEffect(self._make_text_shadow())

        # Fixed-size, draggable window (positioned via layer-shell margins); the
        # content container hugs its text and sits centered inside it.
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addStretch(1)
        self._root.addWidget(self._container, 0, Qt.AlignmentFlag.AlignHCenter)
        self._root.addStretch(1)

    def _make_text_shadow(self) -> QGraphicsDropShadowEffect:
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(0, 0, 0, 200))
        return shadow

    def _build_control_bar(self) -> QWidget:
        self._control_bar = QWidget(self._container)
        bar = QHBoxLayout(self._control_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)
        bar.addStretch(1)

        self._lock_btn = QToolButton(self._container)
        self._lock_btn.setFixedSize(22, 22)
        self._lock_btn.setIconSize(QSize(15, 15))
        self._lock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lock_btn.setStyleSheet(CONTROL_BUTTON_STYLE)
        self._lock_btn.clicked.connect(self.passthrough_toggle_requested.emit)
        bar.addWidget(self._lock_btn)

        self._settings_btn = QToolButton(self._container)
        self._settings_btn.setFixedSize(22, 22)
        self._settings_btn.setIconSize(QSize(15, 15))
        self._settings_btn.setIcon(settings_icon())
        self._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_btn.setStyleSheet(CONTROL_BUTTON_STYLE)
        self._settings_btn.setToolTip("设置")
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        bar.addWidget(self._settings_btn)

        self._update_lock_icon()
        return self._control_bar

    def _update_lock_icon(self) -> None:
        self._lock_btn.setIcon(lock_icon(closed=self._passthrough))
        if self._passthrough:
            self._lock_btn.setToolTip("已锁定（鼠标穿透）— 点击解锁可拖动")
        else:
            self._lock_btn.setToolTip("已解锁（可拖动）— 点击锁定并穿透")

    def _update_chrome(self) -> None:
        """Locked = immersive (text only): hide controls and the pill background.

        Unlocked = editable: show the control bar and pill so it can be grabbed."""
        self._control_bar.setVisible(not self._passthrough)
        self.update()  # repaint to add/drop the pill background

    def _make_context_label(self) -> QLabel:
        label = QLabel("")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        return label

    # --- config ---

    def apply_config(self, config: Config) -> None:
        self._config = config
        self._passthrough = config.passthrough
        self._update_lock_icon()

        current_font = QFont()
        current_font.setFamily(config.font_family.split(",")[0].strip().strip("'\""))
        current_font.setPixelSize(config.font_size)
        current_font.setWeight(QFont.Weight.ExtraBold)
        self._current.set_style(current_font, config.accent_start, config.accent_end, config.accent_sweep)

        context_size = max(10, int(config.font_size * 0.6))
        for label in (self._prev_label, self._next_label):
            label.setStyleSheet(
                f"color: rgba(255,255,255,120); font-size: {context_size}px; "
                f"font-family: {config.font_family};"
            )

        trans_font = QFont()
        trans_font.setFamily(config.font_family.split(",")[0].strip().strip("'\""))
        trans_font.setPixelSize(max(10, int(config.font_size * 0.55)))
        trans_font.setItalic(True)
        self._translation.set_style(trans_font, config.accent_start, config.accent_end, config.accent_sweep)
        self._translation.setVisible(config.show_translation)

        self.setWindowOpacity(config.opacity)
        self._update_chrome()
        self._apply_window_geometry()
        self.update()

    # --- geometry (fixed-size, margin-positioned panel) ---

    def _band_height(self) -> int:
        fs = self._config.font_size
        lines = int(fs * 1.5) + 3 * max(14, int(fs * 0.7))
        chrome = 22 + 24 + 30  # control bar + container v-margins + spacing/slack
        return max(140, lines + chrome)

    def _target_screen(self):
        return self.screen() or QApplication.primaryScreen()

    def _window_size(self) -> tuple[int, int]:
        screen = self._target_screen()
        screen_w = screen.geometry().width() if screen else 1280
        width = min(int(screen_w * 0.9), 1100)
        return width, self._band_height()

    def _compute_layer_pos(self, width: int, height: int) -> QPoint:
        """Screen-local top-left position from the config (centered + offsets)."""
        screen = self._target_screen()
        geo = screen.geometry() if screen else None
        screen_w = geo.width() if geo else 1280
        screen_h = geo.height() if geo else 720
        x = (screen_w - width) // 2 + self._config.margin_x
        y = self._config.margin_edge if self._config.anchor_top else (screen_h - height - self._config.margin_edge)
        return QPoint(x, max(0, y))

    def _apply_window_geometry(self) -> None:
        """Fix the surface size and compute its position.

        In layer-shell mode the position is applied as left/top margins by
        ``activate_layer_shell``; on the X11/GNOME fallback the window is moved
        directly. Either way the explicit, non-tiny fixed size is what keeps the
        surface visible (an auto-shrunk window produced a near-invisible one)."""
        screen = self._target_screen()
        if screen is None:
            return
        width, height = self._window_size()
        self.setFixedSize(width, height)
        self._layer_pos = self._compute_layer_pos(width, height)
        if not self._controller.available:
            geo = screen.geometry()
            self.move(geo.x() + self._layer_pos.x(), geo.y() + self._layer_pos.y())

    # --- snapshot handling ---

    def _on_tick(self, current_time: float | None, is_playing: bool | None) -> None:
        # High-frequency calibration from the audio element. Forward motion decides
        # play state, so a missing flag is fine.
        if current_time is not None:
            self._clock.sync(current_time, is_playing if isinstance(is_playing, bool) else True)

    def _on_snapshot(self, snapshot: LyricsSnapshot) -> None:
        # Baseline clock calibration from the full frame, so the sweep works even
        # before/without the high-frequency tick (e.g. an un-upgraded probe). The
        # tick, when present, just calibrates more often; small disagreements
        # between the two time sources are absorbed by the clock's smoothing.
        if snapshot.current_time is not None:
            self._clock.sync(snapshot.current_time, snapshot.is_playing)

        if not snapshot.found or snapshot.current is None:
            self._show_empty(snapshot)
            return

        self._container.setVisible(True)
        self._prev_label.setText(snapshot.previous.text if snapshot.previous else "")
        self._next_label.setText(snapshot.next.text if snapshot.next else "")
        self._current.set_line(snapshot.current, snapshot.word_karaoke)

        if self._config.show_translation and snapshot.current.translation:
            # Reuse the current line's time range so the translation sweeps in sync.
            trans_line = replace(
                snapshot.current, text=snapshot.current.translation, translation="", words=()
            )
            self._translation.set_line(trans_line, False)
            self._translation.setVisible(True)
        else:
            self._translation.set_line(None, False)
            self._translation.setVisible(False)

    def _show_empty(self, snapshot: LyricsSnapshot) -> None:
        self._current.set_line(None, False)
        self._prev_label.setText("")
        self._next_label.setText("")
        if snapshot.title:
            artist = f" — {snapshot.artist}" if snapshot.artist else ""
            # end far in the future so it stays un-swept (plain) while idle.
            title_line = LyricLine(
                index=0, id="title", start=0.0, end=1e9, text=f"♪ {snapshot.title}{artist}", translation="", words=()
            )
            self._translation.set_line(title_line, False)
            self._translation.setVisible(True)
        else:
            self._translation.set_line(None, False)
            self._translation.setVisible(False)

    def _render_tick(self) -> None:
        t = self._clock.now()
        if t is not None:
            t += self._config.lead_ms / 1000.0  # advance the sweep to compensate latency
        self._current.set_media_time(t)
        self._translation.set_media_time(t)

    # --- layer shell / placement ---

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        self._apply_window_geometry()
        QTimer.singleShot(0, self.activate_layer_shell)
        QTimer.singleShot(100, self.activate_layer_shell)

    def _window_ptr(self) -> int | None:
        self.winId()  # force native handle creation
        handle = self.windowHandle()
        if handle is None:
            return None
        return sip.unwrapinstance(handle)

    def activate_layer_shell(self) -> None:
        """Promote to a layer surface. MUST be called before the first show()."""
        ptr = self._window_ptr()
        if ptr is None:
            return
        if self._controller.available:
            self._controller.make_overlay(ptr)
            self._controller.set_anchor_position(ptr, self._layer_pos.x(), self._layer_pos.y())
            self._controller.set_passthrough(ptr, self._passthrough)
        else:
            self._fallback_position()

    def _fallback_position(self) -> None:
        """Position manually when layer-shell is unavailable (X11 / GNOME)."""
        screen = self._target_screen()
        if screen is None:
            return
        geo = screen.geometry()
        self.move(geo.x() + self._layer_pos.x(), geo.y() + self._layer_pos.y())

    def set_passthrough(self, enabled: bool) -> None:
        self._passthrough = enabled
        self._update_lock_icon()
        self._update_chrome()
        ptr = self._window_ptr()
        if ptr is not None and self._controller.available:
            self._controller.set_passthrough(ptr, enabled)

    # --- drag to reposition (only while unlocked) ---
    #
    # Wayland forbids client-side self.move(); a layer surface is moved by
    # updating its margins. We track the grab point in *local* (window) coords so
    # that as the window follows the cursor the delta naturally settles to zero
    # each frame (1:1 feel), mirroring BiliHUD.

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and not self._passthrough and a0.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_local = a0.position().toPoint()
            a0.accept()
        else:
            super().mousePressEvent(a0)

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and self._dragging and a0.buttons() & Qt.MouseButton.LeftButton:
            diff = a0.position().toPoint() - self._drag_local
            self._layer_pos = self._clamp_to_screen(self._layer_pos + diff)
            if self._controller.available:
                ptr = self._window_ptr()
                if ptr is not None:
                    self._controller.set_anchor_position(ptr, self._layer_pos.x(), self._layer_pos.y())
                    self.update()  # triggers wl_surface.commit so the move applies
            else:
                screen = self._target_screen()
                if screen is not None:
                    geo = screen.geometry()
                    self.move(geo.x() + self._layer_pos.x(), geo.y() + self._layer_pos.y())
            a0.accept()
        else:
            super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        if self._dragging:
            self._dragging = False
            self._commit_drag_position()
            if a0 is not None:
                a0.accept()
        else:
            super().mouseReleaseEvent(a0)

    def _clamp_to_screen(self, pos: QPoint) -> QPoint:
        screen = self._target_screen()
        if screen is None:
            return pos
        geo = screen.geometry()
        width, height = self._window_size()
        x = max(-width + 80, min(pos.x(), geo.width() - 80))
        y = max(0, min(pos.y(), geo.height() - 60))
        return QPoint(x, y)

    def _commit_drag_position(self) -> None:
        """Persist the dragged position back into config margins/offsets."""
        screen = self._target_screen()
        if screen is None:
            return
        geo = screen.geometry()
        width, height = self._window_size()
        self._config.margin_x = self._layer_pos.x() - (geo.width() - width) // 2
        if self._config.anchor_top:
            self._config.margin_edge = max(0, self._layer_pos.y())
        else:
            self._config.margin_edge = max(0, geo.height() - height - self._layer_pos.y())
        self.position_changed.emit(self._config.margin_edge, self._config.margin_x)

    @property
    def passthrough(self) -> bool:
        return self._passthrough

    @property
    def controller(self) -> LayerShellController:
        return self._controller

    # --- painting ---

    def paintEvent(self, a0: QPaintEvent | None) -> None:  # noqa: ARG002
        # Locked -> immersive, no background. Unlocked -> pill so it's grabbable.
        if self._passthrough or self._config.panel_style != "pill":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(15, 17, 22, 150))
        painter.setPen(Qt.PenStyle.NoPen)
        rect = self._container.geometry()
        painter.drawRoundedRect(rect, 16, 16)

    def reset(self) -> None:
        self._clock.reset()
        self._on_snapshot(EMPTY_SNAPSHOT)
