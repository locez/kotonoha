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
from .lyrics.hanzi_fold import convert_script
from .model import EMPTY_SNAPSHOT, LyricLine, LyricsSnapshot
from .native import LayerShellController, default_package_dir
from .state import LyricsState
from .strings import t

logger = logging.getLogger(__name__)

RENDER_INTERVAL_MS = 16  # ~60fps
CONTROL_ICON_COLOR = "#9AA0A6"  # soft grey so the lock/gear don't glare against the panel
PILL_RADIUS = 16  # corner radius shared by the pill paint and the input region

# Appended after the user's chosen family so a Latin-only font (e.g. Inter) still
# renders CJK lyrics via Qt's per-glyph substitution instead of showing tofu.
_FALLBACK_FAMILIES = (
    "Noto Sans CJK SC", "Noto Sans CJK JP", "Noto Sans CJK KR",
    "Source Han Sans SC", "Microsoft YaHei", "PingFang SC", "Segoe UI", "sans-serif",
)


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

    def _control_icon_color(self) -> str:
        """Darken the lock/gear icons on the light (white) panel so they stay
        visible; every other panel is dark, where the soft grey reads fine."""
        return "#5F6368" if self._config.panel_style == "white" else CONTROL_ICON_COLOR

    def _update_lock_icon(self) -> None:
        self._lock_btn.setIcon(lock_icon(self._passthrough, self._control_icon_color()))
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

    def _set_context_text(self, label: QLabel, text: str) -> None:
        """Set a prev/next context line, eliding a too-long line with an ellipsis so
        it never overflows the panel (matters most in fixed-width mode)."""
        width = label.maximumWidth()
        if text and 0 < width < 16_777_215:
            text = label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width)
        label.setText(text)

    # --- config ---

    def apply_config(self, config: Config) -> None:
        self._config = config
        self._passthrough = config.passthrough
        self._update_lock_icon()
        self._settings_btn.setIcon(settings_icon(self._control_icon_color()))
        # Configure the pill width for the fit/fixed mode; `avail` is the inner width
        # the lyric labels may use before a long line scrolls (main) or elides (rest).
        avail = self._configure_panel_width()
        families = self._font_families()
        base, shadow, context_css = self._text_colors()

        current_font = QFont()
        current_font.setFamilies(families)
        current_font.setPixelSize(config.font_size)
        current_font.setWeight(QFont.Weight(config.font_weight))
        self._current.set_style(
            current_font, config.accent_start, config.accent_end, config.accent_sweep, base, shadow
        )
        self._current.set_effects(
            glow=config.fx_glow, word_pop=config.fx_word_pop,
            intensity=config.fx_intensity, animate=config.fx_animate,
        )
        self._current.set_max_width(avail)

        family_stack = ", ".join(f"'{name}'" for name in families)
        for label in (self._prev_label, self._next_label):
            label.setStyleSheet(
                f"color: {context_css}; font-size: {config.context_font_size}px; "
                f"font-family: {family_stack};"
            )
            label.setMaximumWidth(avail)
            # Keep the context halo consistent with the main line: a light halo on
            # the white panel (dark text), a dark halo elsewhere — otherwise the
            # black shadow smudges dark-on-white and vanishes at low white opacity.
            effect = label.graphicsEffect()
            if isinstance(effect, QGraphicsDropShadowEffect):
                effect.setColor(shadow)

        trans_font = QFont()
        trans_font.setFamilies(families)
        trans_font.setPixelSize(config.translation_font_size)
        trans_font.setItalic(True)
        self._translation.set_style(
            trans_font, config.accent_start, config.accent_end, config.accent_sweep, base, shadow
        )
        # Secondary line: no glow/pop, but honour the animation toggle.
        self._translation.set_effects(
            glow=False, word_pop=False, intensity=config.fx_intensity, animate=config.fx_animate
        )
        self._translation.set_max_width(avail)
        self._translation.setVisible(config.show_translation)

        # Opacity is the panel's own fill translucency (see paintEvent / _panel_alpha),
        # so the window itself is always fully opaque — the lyric text stays crisp,
        # and lowering opacity (even to 0) only fades the panel, never the text.
        self.setWindowOpacity(1.0)
        self._update_chrome()
        self._apply_window_geometry()
        self.update()
        QTimer.singleShot(0, self._apply_blur)  # panel_style may have changed

    # --- geometry (fixed-size, margin-positioned panel) ---

    def _font_families(self) -> list[str]:
        """The chosen family first, then the CJK/system fallback chain, so a
        Latin-only pick still renders Chinese/Japanese/Korean lyrics."""
        chosen = self._config.font_family.split(",")[0].strip().strip("'\"")
        families = [chosen] if chosen else []
        for name in _FALLBACK_FAMILIES:
            if name not in families:
                families.append(name)
        return families

    def _configure_panel_width(self) -> int:
        """Set the pill container's width for the current mode and return the inner
        width available to the lyric text. Fixed mode pins the pill so it does not
        resize with the line length; fit mode lets it hug the text as before."""
        window_w = self._window_size()[0]
        if self._config.panel_width_mode == "fixed":
            pill_w = max(240, min(self._config.panel_width, window_w - 8))
            self._container.setFixedWidth(pill_w)
            return max(120, pill_w - 44)  # minus the container's 22+22 h-margins
        # Fit-to-text: release any pinned width so the pill hugs its content again.
        self._container.setMinimumWidth(0)
        self._container.setMaximumWidth(16_777_215)
        return max(200, window_w - 56)

    def _band_height(self) -> int:
        main = self._config.font_size
        context = self._config.context_font_size
        translation = self._config.translation_font_size if self._config.show_translation else 0
        lines = int(main * 1.6) + 2 * int(context * 1.4) + int(translation * 1.6)
        chrome = 22 + 24 + 34  # control bar + container v-margins + spacing/slack
        return max(140, lines + chrome)

    def _target_screen(self):
        return self.screen() or QApplication.primaryScreen()

    def _window_size(self) -> tuple[int, int]:
        screen = self._target_screen()
        screen_w = screen.geometry().width() if screen else 1280
        if self._config.panel_width_mode == "fixed":
            pill = max(240, min(self._config.panel_width, int(screen_w * 0.98)))
            width = min(int(screen_w * 0.98), pill + 48)  # small transparent drag margin
        else:
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
        current = self._convert_line(snapshot.current)
        assert current is not None  # snapshot.current is non-None here (checked above)
        previous = self._convert_line(snapshot.previous)
        next_line = self._convert_line(snapshot.next)
        self._set_context_text(self._prev_label, previous.text if previous else "")
        self._set_context_text(self._next_label, next_line.text if next_line else "")
        self._current.set_line(current, snapshot.word_karaoke)

        if self._config.show_translation and current.translation:
            # Reuse the current line's time range so the translation sweeps in sync.
            trans_line = replace(current, text=current.translation, translation="", words=())
            self._translation.set_line(trans_line, False)
            self._translation.setVisible(True)
        else:
            self._translation.set_line(None, False)
            self._translation.setVisible(False)
        self._refresh_input_region()

    def _convert_line(self, line: LyricLine | None) -> LyricLine | None:
        """Convert a line's displayed text to the configured lyric script (簡/繁).

        Display-only: matching and the cache still use the original text. No-op
        when conversion is off, so playback with conversion disabled is untouched."""
        target = self._config.lyrics_script
        if line is None or target == "off":
            return line
        words = tuple(replace(word, text=convert_script(word.text, target)) for word in line.words)
        return replace(
            line,
            text=convert_script(line.text, target),
            translation=convert_script(line.translation, target),
            words=words,
        )

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
            text = convert_script(f"♪ {snapshot.title}{artist}", self._config.lyrics_script)
        else:
            # Nothing playing: a default line so the panel isn't a blank box.
            text = t("overlay.idle")
        # end far in the future so it stays un-swept (plain) while idle.
        title_line = LyricLine(index=0, id="title", start=0.0, end=1e9, text=text, translation="", words=())
        self._current.set_line(title_line, False)

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
            self._apply_blur()
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

    def _apply_blur(self) -> None:
        """Blur the compositor content behind the pill for the frosted-glass style
        (KWin backdrop-blur); no-op elsewhere, where the translucent fill remains."""
        ptr = self._window_ptr()
        if ptr is None or not self._controller.available:
            return
        if self._config.panel_style == "frost":
            rect = self._container.geometry()
            self._controller.set_blur_region(ptr, rect.x(), rect.y(), rect.width(), rect.height(), PILL_RADIUS)
        else:
            self._controller.clear_blur(ptr)

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
                QTimer.singleShot(0, self._apply_blur)  # keep the blur region on the pill
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
        # Opacity slider drives the fill for every style, including frosted: lower
        # it to let more of the KWin backdrop-blur show through, raise it for a
        # heavier tint. (It used to be capped for frost, so the slider did nothing
        # over its upper range.)
        color.setAlpha(self._panel_alpha())
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self._container.geometry(), PILL_RADIUS, PILL_RADIUS)

    def _text_colors(self) -> tuple[QColor, QColor, str]:
        """(base, shadow, context-CSS) text colours chosen for contrast against the
        panel: the white panel needs dark text with a soft light halo, every other
        style keeps light text with a dark shadow."""
        if self._config.panel_style == "white":
            return QColor(28, 30, 36, 235), QColor(255, 255, 255, 90), "rgba(20,22,28,150)"
        return QColor(255, 255, 255, 95), QColor(0, 0, 0, 170), "rgba(255,255,255,120)"

    def _panel_base_color(self) -> QColor:
        """Fill colour for the panel (alpha applied separately from the slider).

        Black panel is a near-black slab, optionally tinted toward the accent
        colour; white is a near-white slab (dark lyrics ride on top). Frosted is a
        cool translucent dark that the KWin backdrop-blur (when available) shows
        through."""
        if self._config.panel_style == "white":
            return QColor(244, 245, 248)
        if self._config.panel_style == "frost":
            return QColor(26, 30, 40)
        if self._config.panel_accent_tint:
            accent = QColor(self._config.accent_start)
            return QColor(accent.red() * 30 // 100, accent.green() * 30 // 100, accent.blue() * 30 // 100)
        return QColor(15, 17, 22)

    def _should_paint_panel(self) -> bool:
        """The background panel follows the panel-style setting, decoupled from the
        lock state: a black/white/frosted panel stays visible (with its opacity)
        even when locked; "No panel" is the immersive, text-only mode. Locking only
        toggles click-through, so it no longer silently drops the panel to nothing."""
        return self._config.panel_style in ("pill", "white", "frost")

    def _panel_alpha(self) -> int:
        """Panel fill alpha from the opacity slider. The frosted panel has its own
        opacity (0 = pure blur, 100% = solid); the black panel uses the main one
        (0% = fully transparent). 0..100% maps to 0..255."""
        opacity = self._config.frost_opacity if self._config.panel_style == "frost" else self._config.opacity
        return max(0, min(255, round(255 * opacity)))

    def reset(self) -> None:
        self._clock.reset()
        self._on_snapshot(EMPTY_SNAPSHOT)
