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
from PyQt6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, pyqtSignal
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
from .strings import t

logger = logging.getLogger(__name__)

RENDER_INTERVAL_MS = 16  # ~60fps
CONTROL_ICON_COLOR = "#9AA0A6"  # soft grey so the lock/gear don't glare against the panel
PILL_RADIUS = 16  # corner radius shared by the pill paint and the input region


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
        self._container.installEventFilter(self)  # track its size for the input region
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
        self._settings_btn.setIcon(settings_icon(CONTROL_ICON_COLOR))
        self._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_btn.setStyleSheet(CONTROL_BUTTON_STYLE)
        self._settings_btn.setToolTip(t("overlay.settings"))
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        bar.addWidget(self._settings_btn)

        self._update_lock_icon()
        return self._control_bar

    def _update_lock_icon(self) -> None:
        self._lock_btn.setIcon(lock_icon(self._passthrough, CONTROL_ICON_COLOR))
        self._lock_btn.setToolTip(t("overlay.locked") if self._passthrough else t("overlay.unlocked"))

    def _update_chrome(self) -> None:
        """Locking only hides the interactive controls (you can't click them once
        the surface is click-through). The panel background is governed by the
        panel-style setting, NOT the lock state — see paintEvent."""
        self._control_bar.setVisible(not self._passthrough)
        self.update()  # repaint in case the control bar changed the pill size

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
        # Long lines scroll instead of overflowing: cap the labels to the panel width.
        avail = max(200, self._window_size()[0] - 56)

        current_font = QFont()
        current_font.setFamily(config.font_family.split(",")[0].strip().strip("'\""))
        current_font.setPixelSize(config.font_size)
        current_font.setWeight(QFont.Weight.ExtraBold)
        self._current.set_style(current_font, config.accent_start, config.accent_end, config.accent_sweep)
        self._current.set_max_width(avail)

        context_size = max(10, int(config.font_size * 0.6))
        for label in (self._prev_label, self._next_label):
            label.setStyleSheet(
                f"color: rgba(255,255,255,120); font-size: {context_size}px; "
                f"font-family: {config.font_family};"
            )
            label.setMaximumWidth(avail)

        trans_font = QFont()
        trans_font.setFamily(config.font_family.split(",")[0].strip().strip("'\""))
        trans_font.setPixelSize(max(10, int(config.font_size * 0.55)))
        trans_font.setItalic(True)
        self._translation.set_style(trans_font, config.accent_start, config.accent_end, config.accent_sweep)
        self._translation.set_max_width(avail)
        self._translation.setVisible(config.show_translation)

        # Panelled modes (glass / frosted): opacity is the panel's fill translucency
        # (see paintEvent), so keep the window fully opaque or the lyric text would
        # fade too and the panel would be dimmed twice. Text-only mode has no panel,
        # so the whole window carries the opacity.
        self.setWindowOpacity(1.0 if config.panel_style in ("pill", "frost") else config.opacity)
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
            self._refresh_input_region()
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
        self._refresh_input_region()

    def _show_empty(self, snapshot: LyricsSnapshot) -> None:
        self._prev_label.setText("")
        self._next_label.setText("")
        # No translation line while idle; the title carries the whole message.
        self._translation.set_line(None, False)
        self._translation.setVisible(False)
        if snapshot.title:
            artist = f" — {snapshot.artist}" if snapshot.artist else ""
            # Show the now-playing title in the main line at full size (it used to
            # go in the tiny translation label, which read as uncomfortably small).
            # end far in the future so it stays un-swept (plain) while idle.
            title_line = LyricLine(
                index=0, id="title", start=0.0, end=1e9, text=f"♪ {snapshot.title}{artist}", translation="", words=()
            )
            self._current.set_line(title_line, False)
        else:
            self._current.set_line(None, False)

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
            self._apply_input_region()
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
        # Chrome visibility just changed the pill size; lay out, then set the region.
        QTimer.singleShot(0, self._apply_input_region)

    def _apply_input_region(self) -> None:
        """Locked -> full click-through. Unlocked -> only the visible pill catches
        clicks, so the big transparent band around it stays click-through."""
        ptr = self._window_ptr()
        if ptr is None or not self._controller.available:
            return
        if self._passthrough:
            self._controller.set_passthrough(ptr, True)
        else:
            rect = self._container.geometry()
            self._controller.set_input_rect(ptr, rect.x(), rect.y(), rect.width(), rect.height())

    def _refresh_input_region(self) -> None:
        if not self._passthrough:
            QTimer.singleShot(0, self._apply_input_region)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        # The container resizes as the pill/lyric changes size; keep the input
        # region matched to it. This fixes the initially oversized region before
        # the first snapshot shrinks the pill to its real size.
        if a0 is self._container and a1 is not None:
            if a1.type() in {QEvent.Type.Move, QEvent.Type.Resize}:
                # The rounded panel antialiases one pixel beyond the container's
                # geometry. Repaint the full translucent surface so an old edge
                # cannot survive a layout-driven move or resize.
                self.update()
            if a1.type() == QEvent.Type.Resize:
                self._refresh_input_region()
        return super().eventFilter(a0, a1)

    # --- drag to reposition (only while unlocked) ---
    #
    # Wayland forbids client-side self.move(); a layer surface is moved by updating
    # its margins. Use BiliHUD's incremental *local* delta — it is accurate ("cursor
    # stops where you release") because the cursor's local position re-settles as the
    # surface follows. (globalPosition() is unreliable for a layer surface on Wayland
    # — it can be off by half a screen — which is why BiliHUD avoids it.) To fix the
    # big-font flicker we commit via the bridge and skip the Qt repaint, so the heavy
    # lyric text isn't re-rendered every frame.

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and not self._passthrough and a0.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_local = a0.position().toPoint()
            self._render_timer.stop()  # pause the sweep so it isn't repainted mid-drag
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
                    # No repaint: the bridge commits the surface, and the compositor
                    # just re-positions the cached buffer — so the heavy lyric text
                    # isn't re-rendered every frame, which is what killed tracking.
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
            self._render_timer.start()  # resume the sweep
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
        if not self._should_paint_panel():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self._panel_base_color()
        color.setAlpha(self._panel_alpha())
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self._container.geometry(), PILL_RADIUS, PILL_RADIUS)

    def _panel_base_color(self) -> QColor:
        """Fill colour for the panel (alpha applied separately from the slider).

        Black panel is a near-black slab, optionally tinted toward the accent
        colour. Frosted is a cool translucent dark that the KWin backdrop-blur
        (when available) shows through."""
        if self._config.panel_style == "frost":
            return QColor(26, 30, 40)
        if self._config.panel_accent_tint:
            accent = QColor(self._config.accent_start)
            return QColor(accent.red() * 30 // 100, accent.green() * 30 // 100, accent.blue() * 30 // 100)
        return QColor(15, 17, 22)

    def _should_paint_panel(self) -> bool:
        """The background panel follows the panel-style setting, decoupled from the
        lock state: a black/frosted panel stays visible (with its opacity) even when
        locked; "No panel" is the immersive, text-only mode. Locking only toggles
        click-through, so it no longer silently drops the panel to nothing."""
        return self._config.panel_style in ("pill", "frost")

    def _panel_alpha(self) -> int:
        """Pill fill opacity from the Opacity slider: 100% -> solid, 30% -> faint.

        Used to be hardcoded at 150/255, so the slider never touched the pill and
        "100%" still rendered ~59% see-through."""
        return max(0, min(255, round(255 * self._config.opacity)))

    def reset(self) -> None:
        self._clock.reset()
        self._on_snapshot(EMPTY_SNAPSHOT)
