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

from PyQt6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QShowEvent,
)
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
from .config import TRACK_OFFSET_STEP_MS, Config, set_track_offset, track_identity_key
from .icons import earlier_icon, later_icon, lock_icon, settings_icon
from .karaoke import interlude_text
from .karaoke_label import KaraokeLabel
from .lyrics.hanzi_fold import convert_script
from .model import EMPTY_SNAPSHOT, Interlude, LyricLine, LyricsSnapshot
from .platform import (
    DefaultOverlayPlatformFactory,
    LayerShellController,
    QtWindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
    default_package_dir,
)
from .platform.overlay_contracts import DragMode, Output
from .state import LyricsState
from .strings import t

logger = logging.getLogger(__name__)

RENDER_INTERVAL_MS = 16  # ~60fps
CONTROL_ICON_COLOR = "#9AA0A6"  # soft grey so the lock/gear don't glare against the panel
#: The marker stands in for a lyric, so it is drawn under the lyric size — but it
#: still has to read as part of the same panel, which at 0.42 it did not: it sat
#: small and crowded against the lines above and below.
INTERLUDE_SCALE = 0.62
PILL_RADIUS = 16  # corner radius shared by the pill paint and the input region
# How many CJK characters wide a line may grow before it scrolls with the sweep;
# latin text fits roughly twice as many. Fit mode sizes the window from this and
# the font, because the room a line needs follows the font size.
FIT_LINE_CHARS = 28

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
    # Emitted after a drag, with the edge margin, horizontal offset relative to
    # the target output's center, and output name. The offset is output-local;
    # virtual-desktop origins are deliberately excluded.
    position_changed = pyqtSignal(int, int, str)
    track_offset_changed = pyqtSignal(str, int)

    def __init__(self, state: LyricsState, config: Config, controller: LayerShellController | None = None) -> None:
        super().__init__()
        self._state = state
        self._config = config
        self._clock = MediaClock()
        self._passthrough = config.passthrough
        self._layer_pos = QPoint()  # screen-local top-left of the surface
        self._active_screen = None
        self._preserve_layer_pos_on_show = False
        self._dragging = False
        self._drag_moved = False
        self._drag_applied = True
        self._drag_local = QPoint()
        self._track_key = ""
        # The wait currently on screen; None whenever a line is being sung.
        self._interlude: Interlude | None = None
        #: What the marker last read, so the layout is rebuilt only when it changes.
        self._interlude_text = ""
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._restore_after_offset_feedback)
        app = QApplication.instance()
        desktop = app.property("xdg_current_desktop") if app is not None else ""
        self._controller = controller or LayerShellController(
            default_package_dir(),
            QGuiApplication.platformName(),
            desktop or "",
        )
        self._host = QtWindowHost(self)
        self._platform = DefaultOverlayPlatformFactory(self._controller)(self._host)
        self._platform.prepare()
        self._host.apply_window_policy(self._platform_policy())
        for name, available, reason in (
            (
                "layer shell",
                self._platform.capabilities.layer_shell,
                self._platform.capabilities.layer_shell_reason,
            ),
            ("blur", self._platform.capabilities.blur, self._platform.capabilities.blur_reason),
            (
                "input regions",
                self._platform.capabilities.input_region,
                self._platform.capabilities.input_region_reason,
            ),
            (
                "output rebinding",
                self._platform.capabilities.output_rebinding,
                self._platform.capabilities.output_rebinding_reason,
            ),
        ):
            if not available:
                logger.warning("Overlay %s unavailable: %s", name, reason or "no reason provided")
        self.setWindowTitle("Kotonoha")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._build_ui()
        self.apply_config(config)

        self._state.snapshot_changed.connect(self._on_snapshot)
        self._state.time_ticked.connect(self._on_tick)
        if isinstance(app, QGuiApplication):
            app.screenAdded.connect(self._on_screen_added)
            app.screenRemoved.connect(self._on_screen_removed)
        self._platform.set_output_handler(self._restore_output)

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(RENDER_INTERVAL_MS)
        self._render_timer.timeout.connect(self._render_tick)
        self._render_timer.start()

        self._on_snapshot(self._state.snapshot)

    # --- UI ---

    def _platform_policy(self) -> WindowPolicy:
        """Keep the overlay's non-activating top-level window policy explicit."""
        return WindowPolicy(does_not_accept_focus=True, recreate_surface=True)

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

        self._earlier_btn = self._make_offset_button(earlier_icon, "overlay.offset.earlier")
        self._earlier_btn.clicked.connect(self._nudge_earlier)
        bar.addWidget(self._earlier_btn)

        self._later_btn = self._make_offset_button(later_icon, "overlay.offset.later")
        self._later_btn.clicked.connect(self._nudge_later)
        bar.addWidget(self._later_btn)

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

    def _make_offset_button(self, icon_factory, tooltip_key: str) -> QToolButton:
        button = QToolButton(self._container)
        button.setFixedSize(22, 22)
        button.setIconSize(QSize(15, 15))
        button.setIcon(icon_factory(CONTROL_ICON_COLOR))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(CONTROL_BUTTON_STYLE)
        button.setToolTip(t(tooltip_key))
        return button

    def _control_icon_color(self) -> str:
        """Darken the lock/gear icons on the light (white) panel so they stay
        visible; every other panel is dark, where the soft grey reads fine."""
        return "#5F6368" if self._config.panel_style == "white" else CONTROL_ICON_COLOR

    def _update_lock_icon(self) -> None:
        self._lock_btn.setIcon(lock_icon(self._passthrough, self._control_icon_color()))
        self._lock_btn.setToolTip(t("overlay.locked") if self._passthrough else t("overlay.unlocked"))
        color = self._control_icon_color()
        self._earlier_btn.setIcon(earlier_icon(color))
        self._later_btn.setIcon(later_icon(color))

    def _update_chrome(self) -> None:
        """Locking only hides the interactive controls (you can't click them once
        the surface is click-through). The panel background is governed by the
        panel-style setting, NOT the lock state — see paintEvent."""
        self._control_bar.setVisible(not self._passthrough)
        self._earlier_btn.setVisible(not self._passthrough)
        self._later_btn.setVisible(not self._passthrough)
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
        self._set_active_screen(self._configured_screen() or self._active_screen or self.screen())
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
        if config.font_style:
            current_font.setStyleName(config.font_style)  # e.g. "Bold", "Light Italic"
        self._current.set_style(
            current_font, config.accent_start, config.accent_end, config.accent_sweep, base, shadow
        )
        self._current.set_effects(
            glow=config.fx_glow, word_pop=config.fx_word_pop,
            intensity=config.fx_intensity, animate=config.fx_animate,
            transition=config.fx_transition,
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
        # Secondary line: no glow/pop, but honour the animation toggle + style.
        self._translation.set_effects(
            glow=False, word_pop=False, intensity=config.fx_intensity,
            animate=config.fx_animate, transition=config.fx_transition,
        )
        self._translation.set_max_width(avail)
        self._translation.setVisible(config.show_translation)
        self._update_context_visibility()

        # Opacity is the panel's own fill translucency (see paintEvent / _panel_alpha),
        # so the window itself stays fully opaque — the lyric text is always crisp and
        # lowering opacity (even to 0) only fades the panel, never the text. (We do NOT
        # call setWindowOpacity: the Qt Wayland plugin ignores it and just warns.)
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
        context = 0 if self._config.current_line_only else self._config.context_font_size
        translation = self._config.translation_font_size if self._config.show_translation else 0
        lines = int(main * 1.6) + 2 * int(context * 1.4) + int(translation * 1.6)
        chrome = 22 + 24 + 34  # control bar + container v-margins + spacing/slack
        return max(140, lines + chrome)

    def _update_context_visibility(self) -> None:
        visible = not self._config.current_line_only
        self._prev_label.setVisible(visible)
        self._next_label.setVisible(visible)

    def _configured_screen(self):
        if not self._config.screen_name:
            return None
        return next(
            (screen for screen in QGuiApplication.screens() if screen.name() == self._config.screen_name),
            None,
        )

    def _set_active_screen(self, screen) -> None:
        """Record the output the overlay is on, and tell the platform.

        One entry point for all of them: apply_config set the attribute directly
        and ran before _target_screen ever did, so the early return there meant the
        adapter was never told at startup. Its _active_output stayed None, and the
        output lifecycle keyed on it — recognising the active monitor going away,
        choosing where to rebuild — could not fire for the whole session.
        """
        self._active_screen = screen
        self._platform.set_active_output(self._output(screen))

    def _target_screen(self):
        screens = QGuiApplication.screens()
        active = self._active_screen
        if active is not None and active in screens and self._usable_screen(active):
            return active
        screen = (
            self._usable_screen(self._configured_screen())
            or self._usable_screen(self.screen())
            or self._usable_screen(QApplication.primaryScreen())
            or next((candidate for candidate in screens if self._usable_screen(candidate)), None)
        )
        self._set_active_screen(screen)
        return screen

    @staticmethod
    def _usable_screen(screen):
        if screen is None:
            return None
        try:
            return screen if not screen.geometry().isEmpty() else None
        except RuntimeError:
            return None

    @staticmethod
    def _output(screen) -> Output | None:
        if screen is None:
            return None
        try:
            geometry = screen.geometry()
        except RuntimeError:
            return None
        if geometry.isEmpty():
            return None
        return Output(screen.name(), WindowRectangle(geometry.x(), geometry.y(), geometry.width(), geometry.height()))

    def _connected_outputs(self) -> tuple[Output, ...]:
        return tuple(output for screen in QGuiApplication.screens() if (output := self._output(screen)) is not None)

    def _on_screen_removed(self, screen) -> None:
        output = self._output(screen)
        if output is not None:
            self._platform.output_removed(output, self._connected_outputs(), self._config.screen_name or None)

    def _on_screen_added(self, screen) -> None:
        if self._output(screen) is not None:
            self._platform.output_added(self._connected_outputs(), self._config.screen_name or None)

    def _restore_output(self, output: Output) -> bool:
        """Rebuild on a returning output, reporting whether a surface now exists."""
        # Matched on name, not on the whole Output. The geometry recorded when the
        # screen appeared can be a mode Qt has since replaced — screenAdded and
        # geometryChanged are separate signals, and a mode change does not fire the
        # former again — so full equality rejected the very output it was waiting
        # for and left the surface unbuilt. The live geometry is read below.
        screen = next(
            (candidate for candidate in QGuiApplication.screens() if candidate.name() == output.name), None
        )
        if screen is None:
            return False
        self._set_active_screen(screen)
        self._bind_widget_screen(screen)
        self._apply_window_geometry()  # the returning output may have a new mode
        self._preserve_layer_pos_on_show = True  # showEvent must keep what we just computed
        rebuilt = self.activate_layer_shell()  # must precede show(): see the bridge's make_overlay
        self.show()
        return rebuilt

    @staticmethod
    def _same_screen(first, second) -> bool:
        if first is second:
            return True
        if first is None or second is None:
            return False
        return first.name() == second.name() and first.geometry() == second.geometry()

    @staticmethod
    def _screen_for_global_point(point: QPoint, screens, fallback):
        for screen in screens:
            if screen.geometry().contains(point):
                return screen
        if not screens:
            return fallback

        # Multi-monitor layouts can leave a small gap between outputs. Keep the
        # drag attached to the nearest output instead of losing the target screen
        # while the pointer crosses that gap.
        def distance_squared(screen) -> int:
            geo = screen.geometry()
            dx = max(geo.left() - point.x(), 0, point.x() - geo.right())
            dy = max(geo.top() - point.y(), 0, point.y() - geo.bottom())
            return dx * dx + dy * dy

        return min(screens, key=distance_squared)

    def _window_size(self) -> tuple[int, int]:
        screen = self._target_screen()
        screen_w = screen.geometry().width() if screen else 1280
        if self._config.panel_width_mode == "fixed":
            pill = max(240, min(self._config.panel_width, int(screen_w * 0.98)))
            width = min(int(screen_w * 0.98), pill + 48)  # small transparent drag margin
        else:
            # The pill hugs its text here, so the window only has to be wide enough
            # to hold a line. A flat 1100 stopped scaling once the font grew: at
            # font_size 80 an ordinary English line measures about 2000px against
            # 1044px of room, so half of every line sat outside the window. The
            # floor keeps the previous width for the default font sizes.
            width = min(int(screen_w * 0.9), max(1100, self._config.font_size * FIT_LINE_CHARS))
        return width, self._band_height()

    def _compute_layer_pos(self, width: int, height: int) -> QPoint:
        """Screen-local top-left position from the config (centered + offsets)."""
        screen = self._target_screen()
        geo = screen.geometry() if screen else None
        screen_w = geo.width() if geo else 1280
        screen_h = geo.height() if geo else 720
        x = (screen_w - width) // 2 + self._config.margin_x
        y = self._config.margin_edge if self._config.anchor_top else (screen_h - height - self._config.margin_edge)
        # A drag may legitimately park the panel past the edge — the surface is
        # wider than the visible pill, so a right-hand park is stored as a large
        # negative x. Honour that only on the output it was measured on: clamping
        # it fully there would yank the panel back on the next geometry pass, and
        # trusting it on a *smaller* output leaves 80x60 px of panel on screen.
        same_output = (
            geo is not None
            and screen is not None
            and screen.name() == self._config.screen_name
            and (geo.width(), geo.height()) == (self._config.screen_width, self._config.screen_height)
        )
        return self._clamp_to_screen(
            QPoint(x, y), screen=screen, width=width, height=height, allow_partial=same_output
        )

    def _apply_window_geometry(self, *, reset_position: bool = True) -> None:
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
        self._bind_widget_screen(screen)
        if reset_position:
            self._layer_pos = self._compute_layer_pos(width, height)
        if not self._platform.capabilities.layer_shell:
            geo = screen.geometry()
            self._platform.move_to(
                WindowPoint(geo.x() + self._layer_pos.x(), geo.y() + self._layer_pos.y())
            )

    def _bind_widget_screen(self, screen) -> None:
        if screen is None:
            return
        self.setScreen(screen)
        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(screen)

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

        if snapshot.found and snapshot.current is None and snapshot.interlude is not None:
            self._show_interlude(snapshot)
            self._refresh_input_region()
            return

        if self._interlude is not None:
            self._interlude = None
            self._current.set_scale(1.0)
        if not snapshot.found or snapshot.current is None:
            self._show_empty(snapshot)
            self._refresh_input_region()
            return

        self._container.setVisible(True)
        self._track_key = track_identity_key(snapshot.title or "", snapshot.artist or "", snapshot.duration_s)
        current = self._convert_line(snapshot.current)
        assert current is not None  # snapshot.current is non-None here (checked above)
        previous = self._convert_line(snapshot.previous)
        next_line = self._convert_line(snapshot.next)
        self._set_context_text(self._prev_label, previous.text if previous else "")
        self._set_context_text(self._next_label, next_line.text if next_line else "")
        # The snapshot says the timing exists; the setting says whether to use it.
        # Only the snapshot was consulted, so "Word-by-word highlight" had no
        # effect at all — it saved, it translated, and it changed nothing.
        self._current.set_line(current, snapshot.word_karaoke and self._config.karaoke)

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

    def _show_interlude(self, snapshot: LyricsSnapshot) -> None:
        """Stand in for the line while an intro or a break is playing.

        The surrounding lines stay put: the panel is mid-song, and collapsing it to
        the idle state would read as though playback had stopped.
        """
        self._interlude = snapshot.interlude
        self._interlude_text = ""
        # A marker stands in for the words; drawn at the lyric size it dwarfs them.
        self._current.set_scale(INTERLUDE_SCALE)
        self._container.setVisible(True)
        previous = self._convert_line(snapshot.previous)
        next_line = self._convert_line(snapshot.next)
        self._set_context_text(self._prev_label, previous.text if previous else "")
        self._set_context_text(self._next_label, next_line.text if next_line else "")
        self._translation.set_line(None, False)
        self._translation.setVisible(False)
        self._paint_interlude(snapshot.current_time or 0.0)

    def _paint_interlude(self, position: float) -> None:
        """Redraw the marker for where the wait has got to.

        The marker is handed to the sweep as a line spanning the wait, so the accent
        runs across it exactly as it runs across a sung line — the wait shows its own
        progress in the same language as the rest of the panel. Only the text is
        rebuilt, and only when it changes: the sweep itself is a per-frame paint.
        """
        interlude = self._interlude
        if interlude is None:
            return
        text = interlude_text(
            interlude,
            position,
            style=self._config.interlude_style,
            countdown=self._config.interlude_countdown,
        )
        if text != self._interlude_text:
            self._interlude_text = text
            self._current.set_line(
                LyricLine(
                    index=0, id="interlude", start=interlude.start, end=interlude.end,
                    text=text, translation="", words=(),
                ),
                False,
            )
        self._current.set_media_time(position)

    def _show_empty(self, snapshot: LyricsSnapshot) -> None:
        self._track_key = ""
        self._prev_label.setText("")
        self._next_label.setText("")
        # No translation line while idle; the title carries the whole message.
        self._translation.set_line(None, False)
        self._translation.setVisible(False)
        if snapshot.title:
            artist = f" — {snapshot.artist}" if snapshot.artist else ""
            # Show the now-playing title in the main line at full size (it used to
            # go in the tiny translation label, which read as uncomfortably small).
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
            offset = self._config.track_offsets.get(self._track_key, 0)
            t += (self._config.lead_ms + offset) / 1000.0  # global latency plus recording-specific correction
        if self._interlude is not None:
            if t is not None:
                self._paint_interlude(t)
            return
        self._current.set_media_time(t)
        self._translation.set_media_time(t)

    # --- layer shell / placement ---

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        # A rebuild has already computed the position; recomputing it here would
        # throw away the output the surface was just put back on.
        self._apply_window_geometry(reset_position=not self._preserve_layer_pos_on_show)
        self._preserve_layer_pos_on_show = False
        QTimer.singleShot(0, self.activate_layer_shell)
        QTimer.singleShot(100, self.activate_layer_shell)

    def activate_layer_shell(self) -> bool:
        """Promote to a layer surface. MUST be called before the first show().

        Returns whether the surface is now a layer surface, so a caller that is
        rebuilding one can tell a real rebuild from a fallback."""
        self._bind_widget_screen(self._target_screen())
        result = self._platform.activate()
        capabilities = self._platform.capabilities
        if capabilities.layer_shell and result.succeeded:
            placement = self._platform.move_to(WindowPoint(self._layer_pos.x(), self._layer_pos.y()))
            if not placement.succeeded:
                # Activation succeeded, so the surface is mapped and the return value
                # stays True; only the saved position was not applied. Dropping this
                # left the overlay at the compositor's default anchor with nothing said.
                logger.warning("Layer Shell placement failed: %s", placement.reason or "no reason given")
            self._apply_input_region()
            self._apply_blur()
            return True
        if capabilities.layer_shell:
            # The capability is there but activation failed — a missing window
            # handle, or the bridge raising. Falling through silently left an
            # already-mapped ordinary window unpositioned and with no input region,
            # and said nothing about why.
            logger.warning("Layer Shell activation failed: %s", result.reason or "no reason given")
        self._fallback_position()
        # An ordinary window still needs its input region: without this a config
        # with passthrough on stayed clickable, so a locked overlay swallowed the
        # pointer.
        self._apply_input_region()
        return False

    def _fallback_position(self) -> None:
        """Position as an ordinary window, for X11 and for a failed activation.

        Through the host rather than the platform: this runs when Layer Shell is
        unavailable *or* when it is available and activation failed, and in the
        second case the Layer Shell adapter is still in place — asking it to move
        would set a native anchor on a surface that was never promoted, which is
        not a fallback at all.
        """
        screen = self._target_screen()
        if screen is None:
            return
        geo = screen.geometry()
        position = WindowPoint(geo.x() + self._layer_pos.x(), geo.y() + self._layer_pos.y())
        try:
            self._host.move_window(position)
        except RuntimeError as exc:
            logger.debug("Ordinary-window positioning failed: %s", exc)

    def set_passthrough(self, enabled: bool) -> None:
        self._passthrough = enabled
        self._update_lock_icon()
        self._update_chrome()
        # Chrome visibility just changed the pill size; lay out, then set the region.
        QTimer.singleShot(0, self._apply_input_region)

    def _apply_input_region(self) -> None:
        """Locked -> full click-through. Unlocked -> only the visible pill catches
        clicks, so the big transparent band around it stays click-through."""
        if self._passthrough:
            self._platform.set_input_region(None)
        else:
            rect = self._container.geometry()
            self._platform.set_input_region(
                WindowRectangle(rect.x(), rect.y(), rect.width(), rect.height())
            )

    def _refresh_input_region(self) -> None:
        if not self._passthrough:
            QTimer.singleShot(0, self._apply_input_region)

    def _nudge_earlier(self) -> None:
        """Move this track's lyrics earlier by one step.

        A bound method per direction rather than a lambda closing over the step:
        PyQt holds a bound method's receiver weakly, so the connection dies with the
        widget instead of firing into a deleted C++ object.
        """
        self._nudge_offset(TRACK_OFFSET_STEP_MS)

    def _nudge_later(self) -> None:
        """Move this track's lyrics later by one step."""
        self._nudge_offset(-TRACK_OFFSET_STEP_MS)

    def _nudge_offset(self, delta_ms: int) -> None:
        if not self._track_key:
            return
        current = self._config.track_offsets.get(self._track_key, 0)
        offset = set_track_offset(self._config, self._track_key, current + delta_ms)
        self.track_offset_changed.emit(self._track_key, offset)
        self._show_offset_feedback(offset)
        self._render_tick()

    def _restore_after_offset_feedback(self) -> None:
        """Put the lyric back after the offset readout.

        A bound method, not a lambda: PyQt holds the receiver weakly for a bound
        method, so the connection dies with the widget. A lambda is held strongly
        and keeps firing into a deleted C++ object, which segfaults."""
        self._on_snapshot(self._state.snapshot)

    def _show_offset_feedback(self, offset_ms: int) -> None:
        line = LyricLine(0, "offset-feedback", 0.0, 1e9, t("overlay.offset.value").format(offset=offset_ms), "", ())
        self._current.set_line(line, False)
        self._feedback_timer.start(1200)


    def _apply_blur(self) -> None:
        """Blur the compositor content behind the pill for the frosted-glass style;
        no-op where no blur protocol exists, leaving the translucent fill."""
        if not self._platform.capabilities.blur:
            return
        if self._config.panel_style == "frost":
            rect = self._container.geometry()
            region = WindowRectangle(rect.x(), rect.y(), rect.width(), rect.height())
            self._platform.set_blur_region(region, PILL_RADIUS)
        else:
            self._platform.set_blur_region(None)

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
            local = a0.position().toPoint()
            global_position = a0.globalPosition().toPoint()
            result = self._platform.begin_drag(
                WindowPoint(local.x(), local.y()),
                WindowPoint(global_position.x(), global_position.y()),
            )
            if result.mode is not DragMode.MANUAL:
                super().mousePressEvent(a0)
                return
            self._dragging = True
            self._drag_moved = False
            self._drag_applied = True
            self._drag_local = local
            self._render_timer.stop()  # pause the sweep so it isn't repainted mid-drag
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
            diff = local - self._drag_local
            if not diff.isNull():
                self._drag_moved = True

            # Keep the surface alive for the entire pointer grab. Recreating it
            # at an output boundary destroys the Wayland pointer grab and makes
            # the next mouse event disappear.
            self._layer_pos += diff
            global_position = a0.globalPosition().toPoint()
            moved = self._platform.update_drag(
                WindowPoint(local.x(), local.y()),
                WindowPoint(global_position.x(), global_position.y()),
            )
            if not moved.succeeded:
                # The surface is where it was, so the drag has not taken effect.
                # Remember that, or the release would save a position the visible
                # window never reached.
                self._drag_applied = False
                logger.debug("Drag update was not applied: %s", moved.reason)
            # The platform commits the surface, so avoid repainting heavy lyric text.
            a0.accept()
        else:
            super().mouseMoveEvent(a0)

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        if self._dragging:
            moved = self._drag_moved
            applied = self._drag_applied
            self._dragging = False
            self._drag_moved = False
            self._drag_applied = True
            self._platform.end_drag()
            self._render_timer.start()  # resume the sweep
            if moved and applied and self._platform.capabilities.client_positioning:
                self._commit_drag_position(a0.position().toPoint() if a0 is not None else None)
            elif moved:
                # The window never went where the drag asked, so saving that
                # position would put the config and the visible window out of step.
                logger.info(
                    "Not saving the dragged position: %s",
                    self._platform.capabilities.client_positioning_reason,
                )
            if a0 is not None:
                a0.accept()
        else:
            super().mouseReleaseEvent(a0)

    def _clamp_to_screen(
        self,
        pos: QPoint,
        *,
        screen=None,
        width: int | None = None,
        height: int | None = None,
        allow_partial: bool = True,
    ) -> QPoint:
        screen = screen or self._target_screen()
        if screen is None:
            return pos
        geo = screen.geometry()
        if width is None or height is None:
            width, height = self._window_size()
        if allow_partial:
            # Keep enough of the original local-margin range for the pointer and
            # surface to cross an adjacent output during a grab. The position is
            # normalized back to the target output when the button is released.
            min_x, max_x = -width + 80, geo.width() - 80
            min_y, max_y = 0, geo.height() - 60
        else:
            # Fully visible, both axes. This is the startup and rebuild path: the
            # saved margins were computed against whatever output they were
            # dragged on, and a smaller one must not leave the panel hanging off
            # an edge where the user cannot see or reach it.
            min_x, max_x = 0, max(0, geo.width() - width)
            min_y, max_y = 0, max(0, geo.height() - height)
        x = max(min_x, min(pos.x(), max_x))
        y = max(min_y, min(pos.y(), max_y))
        return QPoint(x, y)

    def _commit_drag_position(self, cursor_local: QPoint | None = None) -> None:
        """Persist the output and edge placement after a drag.

        The layer surface can cross output boundaries while it is grabbed. Only
        after release do we select the output under the cursor and remap the
        surface, when necessary, so the next drag starts with that output as its
        local coordinate system.
        """
        surface_screen = self._target_screen()
        if surface_screen is None:
            return
        surface_geo = surface_screen.geometry()
        surface_top_left = QPoint(
            surface_geo.x() + self._layer_pos.x(),
            surface_geo.y() + self._layer_pos.y(),
        )
        local = cursor_local if cursor_local is not None else self._drag_local
        cursor_global = QPoint(surface_top_left.x() + local.x(), surface_top_left.y() + local.y())
        target_screen = self._screen_for_global_point(cursor_global, QGuiApplication.screens(), surface_screen)
        if target_screen is None:
            target_screen = surface_screen

        # Work in the target output's local coordinates only after the pointer
        # grab has ended. This keeps the live drag independent of output origins.
        target_geo = target_screen.geometry()
        global_pos = surface_top_left
        self._set_active_screen(target_screen)
        width, height = self._window_size()
        self._layer_pos = self._clamp_to_screen(
            QPoint(global_pos.x() - target_geo.x(), global_pos.y() - target_geo.y()),
            screen=target_screen,
            width=width,
            height=height,
            allow_partial=True,
        )
        if self._config.anchor_top:
            self._config.margin_edge = max(0, self._layer_pos.y())
        else:
            self._config.margin_edge = max(0, target_geo.height() - height - self._layer_pos.y())
        # Persist the target output's local horizontal offset using the same
        # center-relative coordinate system used by _compute_layer_pos().
        self._config.margin_x = self._layer_pos.x() - (target_geo.width() - width) // 2
        self._config.screen_name = target_screen.name()
        # Record the geometry this offset was measured against, so loading it back
        # can tell a deliberate park from one stranded by a resolution change.
        self._config.screen_width = target_geo.width()
        self._config.screen_height = target_geo.height()
        if not self._same_screen(surface_screen, target_screen):
            # The platform owns any protocol-specific output rebinding. Recording
            # the output is not enough on layer shell: the surface stays on the
            # output it was dragged away from until it is rebuilt.
            output = self._output(target_screen)
            if output is not None:
                moved = self._platform.move_to_output(output)
                if not moved.succeeded:
                    logger.warning("Output change failed: %s", moved.reason or "no reason given")
        elif self._platform.capabilities.layer_shell:
            self._platform.move_to(WindowPoint(self._layer_pos.x(), self._layer_pos.y()))
        self.position_changed.emit(
            self._config.margin_edge,
            self._config.margin_x,
            self._config.screen_name,
        )

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

        "Panel follows accent" tints whatever style is active toward the accent —
        a dark accent slab (black), a very light accent wash (white), or an
        accent-cool tint (frosted) — so the option is independent of the black
        style. Otherwise: near-black, near-white, or a cool frosted dark."""
        accent = QColor(self._config.accent_start)
        tint = self._config.panel_accent_tint
        if self._config.panel_style == "white":
            return accent.lighter(190) if tint else QColor(244, 245, 248)
        if self._config.panel_style == "frost":
            if tint:
                return QColor(
                    accent.red() * 22 // 100 + 8, accent.green() * 22 // 100 + 10, accent.blue() * 22 // 100 + 16
                )
            return QColor(26, 30, 40)
        if tint:  # black panel
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
