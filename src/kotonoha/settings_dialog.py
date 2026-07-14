"""Tabbed settings panel.

Frameless, translucent, dark "glass" styling to match the overlay. Edits a
working copy of :class:`~kotonoha.config.Config` across grouped tabs and emits
``applied`` with the new config when the user applies/accepts. UI strings come
from :mod:`kotonoha.strings`.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import cast

from PyQt6 import sip
from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QModelIndex,
    QPropertyAnimation,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QHideEvent,
    QIcon,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import leaf_icon
from .config import ACCENT_PRESETS, DEFAULT_ICON_NAME, VALID_LYRICS_SOURCES, Config
from .native import LayerShellController, default_package_dir
from .strings import UI_LANGUAGES, t
from .tray import discover_icon_paths

# Dialog corner radius, shared by the painted background and the KWin blur region.
_RADIUS = 14

# Sensible, widely-installed families to show in the font picker when nothing in the
# configured list is present — a clean CJK-capable font beats a fontconfig substitute.
_FONT_FALLBACKS = (
    "Noto Sans CJK SC", "Noto Sans CJK TC", "Noto Sans CJK JP", "Source Han Sans SC",
    "Microsoft YaHei", "PingFang SC", "Noto Sans", "DejaVu Sans",
)


class _FontNameDelegate(QStyledItemDelegate):
    """Font-list delegate that previews each family name in its own font but drops
    the file-type 'T' icon QFontComboBox normally draws on the left."""

    def initStyleOption(self, option: QStyleOptionViewItem | None, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        if option is None:
            return
        family = index.data()
        if isinstance(family, str) and family:
            option.font = QFont(family)  # render the name in its own font


class _IconStrip(QListWidget):
    """Icon grid that keeps its height equal to exactly the rows its items wrap
    into, so there is never a scrollbar and the hint below sits right under the
    icons. It refits whenever its width changes (theme swap, window resize),
    reading the real laid-out geometry instead of guessing the columns."""

    def resizeEvent(self, e: QResizeEvent | None) -> None:
        super().resizeEvent(e)
        self._refit_height()

    def _refit_height(self) -> None:
        if self.count() == 0:
            return
        last = self.visualItemRect(self.item(self.count() - 1))
        wanted = last.bottom() + 8
        if self.height() != wanted:
            self.setFixedHeight(wanted)


# One QSS template, filled from a light or dark palette below. Spacing and radii
# are generous and the inner borders are soft so the panels don't read as boxes
# stacked inside boxes.
_QSS = """
QWidget { color: %TEXT%; font-family: 'Inter', 'Segoe UI', 'Microsoft YaHei', sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QLabel#hint { color: %HINT%; }
QLabel#dialogTitle { color: %TEXT_STRONG%; font-size: 15px; font-weight: 600; }
QPushButton#closeButton {
    background: transparent; border: none; color: %TEXT_DIM%; font-size: 15px; border-radius: 13px;
}
QPushButton#closeButton:hover { color: %TEXT_STRONG%; background: %ITEM_SEL%; }
/* Left sidebar navigation (a QListWidget#nav) + a stacked content area, instead
   of top tabs — a cleaner settings layout with no tab/box corner clashes. */
QListWidget#nav {
    background: transparent;
    border: none;
    outline: none;
    padding: 2px;
}
QListWidget#nav::item {
    color: %TEXT_DIM%;
    padding: 9px 12px;
    border-radius: 8px;
    margin: 2px 0;
}
QListWidget#nav::item:hover { color: %TEXT_STRONG%; background: %NAV_HOVER%; }
QListWidget#nav::item:selected { color: %TEXT_STRONG%; background: %ACCENT_SOFT%; }
/* Raised content surface (a card) for depth over the base dialog + sidebar. */
QWidget#contentCard { background: %CARD_BG%; border: 1px solid %CARD_BORDER%; border-radius: 12px; }
QCheckBox { background: transparent; spacing: 8px; }
QCheckBox::indicator, QListWidget::indicator {
    width: 16px; height: 16px;
    border: 1px solid %IND_BORDER%;
    border-radius: 5px;
    background: %IND_BG%;
}
/* Once the indicator is custom-styled, Qt no longer paints the native tick, so
   the checkmark must be supplied explicitly — otherwise checked boxes rendered
   as a bare filled square with no glyph, inconsistently across the dialog. */
QCheckBox::indicator:checked, QListWidget::indicator:checked {
    background: %ACCENT%;
    border-color: %ACCENT%;
    image: url(%CHECK%);
}
/* One field style for every input so combos, spin boxes and the font picker are
   the same height and look uniform. */
QSpinBox, QComboBox, QFontComboBox {
    background: %FIELD_BG%;
    border: 1px solid %FIELD_BORDER%;
    border-radius: 7px;
    padding: 4px 9px;
    color: %TEXT%;
    min-height: 24px;
    max-height: 24px;  /* combos and spin boxes end up exactly the same height (~34px) */
}
QSpinBox:hover, QComboBox:hover, QFontComboBox:hover { border-color: %FIELD_BORDER_HOVER%; }
/* Accent focus ring — clear interactive feedback on the control you're editing. */
QSpinBox:focus, QComboBox:focus, QFontComboBox:focus { border: 1px solid %ACCENT%; }
QSpinBox:disabled, QComboBox:disabled { color: %TEXT_DIM%; }
QComboBox::drop-down, QFontComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: center right;
    border: none; width: 22px;
}
QComboBox::down-arrow, QFontComboBox::down-arrow { image: url(%CHEV_DOWN%); width: 12px; height: 12px; }
/* Compact, borderless spin buttons with the same chevrons, so a spin box is the
   same height as a combo instead of a tall two-button control. */
QSpinBox::up-button, QSpinBox::down-button {
    subcontrol-origin: border; border: none; background: transparent; width: 20px;
}
QSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-arrow { image: url(%CHEV_UP%); width: 11px; height: 11px; }
QSpinBox::down-arrow { image: url(%CHEV_DOWN%); width: 11px; height: 11px; }
QComboBox QAbstractItemView {
    background: %POPUP_BG%;
    color: %TEXT%;
    border: 1px solid %FIELD_BORDER%;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: %ACCENT%;
    selection-color: #FFFFFF;
    outline: none;
}
QListWidget {
    background: %LIST_BG%;
    border: 1px solid %LIST_BORDER%;
    border-radius: 10px;
    outline: none;
    padding: 6px;
}
QListWidget::item { padding: 8px 10px; border-radius: 7px; }
QListWidget::item:selected { background: %ITEM_SEL%; color: %TEXT_STRONG%; }
/* De-boxed: no list border/background so the icons don't read as a nested panel.
   Selection is a clean accent ring around the chosen icon, not a grey slab. */
QListWidget#iconPicker { background: transparent; border: none; padding: 2px; }
QListWidget#iconPicker::item {
    padding: 0;
    margin: 4px;
    border: 2px solid transparent;
    border-radius: 12px;
}
QListWidget#iconPicker::item:hover { border-color: %FIELD_BORDER_HOVER%; }
QListWidget#iconPicker::item:selected { background: transparent; border: 2px solid %ACCENT%; }
QPushButton {
    background: %BTN_BG%;
    border: 1px solid %FIELD_BORDER%;
    border-radius: 7px;
    padding: 6px 18px;
    color: %TEXT_STRONG%;
}
QPushButton:hover { background: %BTN_HOVER%; }
QPushButton:pressed { background: %BTN_PRESSED%; }
"""

# Colour tokens per theme. String values fill %TOKEN% in the QSS; the window_* RGBA
# tuples paint the frameless dialog background in paintEvent.
_PALETTES: dict[str, dict[str, object]] = {
    "dark": {
        "TEXT": "#E6E6E8", "TEXT_STRONG": "#FFFFFF", "TEXT_DIM": "rgba(255,255,255,140)",
        "HINT": "rgba(255,255,255,120)",
        "PANE_BG": "rgba(255,255,255,8)", "PANE_BORDER": "rgba(255,255,255,20)",
        # Raised content surface (a card) over the base dialog + sidebar, for depth.
        "CARD_BG": "rgba(255,255,255,7)", "CARD_BORDER": "rgba(255,255,255,14)",
        "NAV_HOVER": "rgba(255,255,255,12)",
        "FIELD_BG": "rgba(255,255,255,18)", "FIELD_BORDER": "rgba(255,255,255,32)",
        "FIELD_BORDER_HOVER": "rgba(255,255,255,80)", "POPUP_BG": "#1e2027",
        "IND_BORDER": "rgba(255,255,255,60)", "IND_BG": "rgba(255,255,255,15)",
        "LIST_BG": "rgba(255,255,255,10)", "LIST_BORDER": "rgba(255,255,255,18)",
        "ITEM_SEL": "rgba(255,255,255,26)",
        "BTN_BG": "rgba(255,255,255,20)", "BTN_HOVER": "rgba(255,255,255,40)",
        "BTN_PRESSED": "rgba(255,255,255,60)",
        "window_bg": (20, 22, 28, 240), "window_border": (255, 255, 255, 30),
    },
    "light": {
        "TEXT": "#24272B", "TEXT_STRONG": "#0E1013", "TEXT_DIM": "rgba(0,0,0,135)",
        "HINT": "rgba(0,0,0,115)",
        "PANE_BG": "rgba(0,0,0,4)", "PANE_BORDER": "rgba(0,0,0,14)",
        # A white content card over the light-grey dialog + sidebar, for depth.
        "CARD_BG": "#FFFFFF", "CARD_BORDER": "rgba(0,0,0,12)",
        "NAV_HOVER": "rgba(0,0,0,7)",
        "FIELD_BG": "rgba(0,0,0,6)", "FIELD_BORDER": "rgba(0,0,0,28)",
        "FIELD_BORDER_HOVER": "rgba(0,0,0,65)", "POPUP_BG": "#FFFFFF",
        "IND_BORDER": "rgba(0,0,0,50)", "IND_BG": "rgba(0,0,0,6)",
        "LIST_BG": "rgba(0,0,0,4)", "LIST_BORDER": "rgba(0,0,0,14)",
        "ITEM_SEL": "rgba(0,0,0,12)",
        "BTN_BG": "rgba(0,0,0,7)", "BTN_HOVER": "rgba(0,0,0,14)",
        "BTN_PRESSED": "rgba(0,0,0,22)",
        "window_bg": (245, 246, 249, 243), "window_border": (0, 0, 0, 32),
    },
}

# White checkmark painted over a checked indicator. Qt's stylesheet url() does
# NOT decode data: URIs (it only loads file/resource paths), so this must be a
# real bundled file — an inline data URI silently renders nothing, leaving a bare
# filled square. Qt's SVG image plugin renders it. (White reads fine on every
# accent colour, in both themes, since the checked box is filled with the accent.)
_CHECKMARK_PATH = Path(__file__).with_name("assets") / "checkmark.svg"
# Mid-grey chevrons for combo/spin arrows — one asset reads fine on both themes.
_CHEVRON_DOWN_PATH = Path(__file__).with_name("assets") / "chevron-down.svg"
_CHEVRON_UP_PATH = Path(__file__).with_name("assets") / "chevron-up.svg"



def _resolve_theme(value: str) -> str:
    """Map the config theme ("auto"/"light"/"dark") to a concrete "light"/"dark".
    "auto" follows the system colour scheme (Qt 6.5+), defaulting to dark."""
    if value in ("light", "dark"):
        return value
    app = cast(QGuiApplication | None, QGuiApplication.instance())
    hints = app.styleHints() if app is not None else None
    scheme = hints.colorScheme() if hints is not None else None
    return "light" if scheme == Qt.ColorScheme.Light else "dark"


def _skin(accent: str, theme: str = "dark", frosted: bool = False, opacity: float = 1.0) -> str:
    """Fill the QSS template from the theme palette, accent colour and checkmark.
    When `frosted`, the content card is made translucent so the KWin backdrop-blur
    shows through it instead of reading as a solid block on the frosted window.
    `opacity` (<1) makes the window see-through: the light theme's opaque white card
    is thinned so the desktop shows through it (dark's card is already translucent,
    so its window fill — painted in paintEvent — carries the effect)."""
    palette = dict(_PALETTES.get(theme, _PALETTES["dark"]))
    if frosted:
        palette["CARD_BG"] = "rgba(255, 255, 255, 120)" if theme == "light" else "rgba(255, 255, 255, 16)"
    elif opacity < 0.999 and theme == "light":
        palette["CARD_BG"] = f"rgba(255, 255, 255, {max(0, min(255, round(255 * opacity)))})"
    qss = _QSS
    for token, value in palette.items():
        if isinstance(value, str):
            qss = qss.replace(f"%{token}%", value)
    c = QColor(accent)
    accent_soft = f"rgba({c.red()}, {c.green()}, {c.blue()}, 42)"  # tinted sidebar selection
    return (
        qss.replace("%ACCENT_SOFT%", accent_soft)
        .replace("%ACCENT%", accent)
        .replace("%CHECK%", _CHECKMARK_PATH.as_posix())
        .replace("%CHEV_DOWN%", _CHEVRON_DOWN_PATH.as_posix())
        .replace("%CHEV_UP%", _CHEVRON_UP_PATH.as_posix())
    )


# The Config fields each sidebar page owns, in nav order. Used by "Reset this tab"
# to restore just the current page's fields to their defaults, leaving the rest.
_PAGE_FIELDS: tuple[tuple[str, ...], ...] = (
    ("ui_language", "theme", "frost_window", "settings_opacity"),                         # General
    ("icon_name", "window_icon_name"),                                                   # Icon
    ("font_family", "font_style", "font_size", "context_font_size", "translation_font_size"),  # Text
    ("panel_style", "panel_width_mode", "panel_width", "opacity", "frost_opacity", "panel_accent_tint"),  # Panel
    ("accent_start", "accent_end", "accent_sweep", "fx_animate", "fx_transition",
     "fx_glow", "fx_word_pop", "fx_intensity"),                                          # Effects
    ("karaoke", "lead_ms", "show_translation", "lyrics_script"),                         # Lyrics
    ("anchor_top", "margin_edge", "margin_x", "passthrough"),                            # Position
    ("lyrics_sources", "prefer_best_lyrics", "fuzzy_match", "cache_enabled"),             # Sources
)


class SettingsDialog(QDialog):
    applied = pyqtSignal(object)  # emits Config
    clear_cache_requested = pyqtSignal()
    restart_requested = pyqtSignal()

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        # Every icon strip built (tray + window), each with its own {key: item} map,
        # so accent re-renders can refresh all of them. Populated by _build_icon_picker.
        self._icon_pickers: list[tuple[_IconStrip, dict[str, QListWidgetItem]]] = []
        # The UI language only takes effect on restart, so remember what is in
        # effect now to decide when to offer the restart button.
        self._initial_ui_language = config.ui_language
        self._theme = _resolve_theme(config.theme)
        self._did_fade_in = False
        # Real KWin backdrop-blur behind the whole window (frosted glass), but only
        # on KDE *Wayland* — that is where org_kde_kwin_blur applies. Anywhere else
        # (X11, GNOME, offscreen) the window stays a solid panel, so we never turn it
        # see-through where the blur would not actually happen.
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
        platform = QGuiApplication.platformName() or ""
        self._blur = LayerShellController(default_package_dir(), platform, desktop)
        self._blur_capable = self._blur.available and "wayland" in platform.lower() and "KDE" in desktop.upper()
        # Wayland has no client-side window-opacity protocol, so animating/setting
        # windowOpacity there does nothing but spam "plugin does not support…".
        self._window_opacity_ok = "wayland" not in platform.lower()
        self._frosted = self._blur_capable and config.frost_window
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # See-through level for the window surfaces. NOT setWindowOpacity — the Qt
        # Wayland plugin ignores that (no client-side opacity protocol); instead the
        # painted window fill + card alpha carry it, so it works under KWin.
        self._win_opacity = config.settings_opacity
        self.setStyleSheet(_skin(config.accent_start, self._theme, self._frosted, self._win_opacity))

        # Sidebar categories drive a stacked content area (replaces top tabs).
        self._stack = QStackedWidget()
        self._nav = QListWidget()
        self._nav.setObjectName("nav")
        self._nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Builders kept so "Reset this tab" can rebuild a single page from defaults.
        self._page_builders = (
            self._general_tab,
            self._icon_tab,
            self._text_tab,
            self._panel_tab,
            self._effects_tab,
            self._lyrics_tab,
            self._position_tab,
            self._sources_tab,
        )
        for key, builder in zip(
            ("tab.general", "tab.icon", "tab.text", "tab.panel", "tab.effects",
             "tab.lyrics", "tab.position", "tab.sources"),
            self._page_builders,
            strict=True,
        ):
            self._nav.addItem(QListWidgetItem(t(key)))
            self._stack.addWidget(builder())
        self._nav.setCurrentRow(0)
        self._stack.setCurrentIndex(0)
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self.setMinimumWidth(560)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        for std, key in (
            (QDialogButtonBox.StandardButton.Ok, "btn.ok"),
            (QDialogButtonBox.StandardButton.Cancel, "btn.cancel"),
            (QDialogButtonBox.StandardButton.Apply, "btn.apply"),
            (QDialogButtonBox.StandardButton.RestoreDefaults, "btn.reset_tab"),
        ):
            btn = buttons.button(std)
            if btn is not None:
                btn.setText(t(key))
                btn.setIcon(QIcon())  # drop the platform ✓/✕ glyphs; text-only, theme-safe
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_button is not None:
            apply_button.clicked.connect(self._emit)
        reset_button = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        if reset_button is not None:
            # ResetRole sits on the left of the box, away from OK/Apply — a reset is
            # per-tab (just this page's fields), not the whole config.
            reset_button.clicked.connect(self._reset_current_page)

        # The content sits in a raised "card" surface while the sidebar stays on the
        # base dialog colour, so the two read as distinct layers (depth) without a
        # hard divider line between them.
        card = QWidget()
        card.setObjectName("contentCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.addWidget(self._stack)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(self._nav)
        body.addWidget(card, 1)

        header_line = QWidget()
        header_line.setObjectName("navDivider")
        header_line.setFixedHeight(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addLayout(self._title_bar())
        layout.addWidget(header_line)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)

    # --- chrome ---

    def _title_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(9)
        self._logo_badge = QLabel()
        self._update_logo_badge()  # accent-tinted leaf logo (falls back to the app icon)
        bar.addWidget(self._logo_badge)
        title = QLabel(t("settings.title"))
        title.setObjectName("dialogTitle")  # styled by the theme QSS
        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeButton")
        close_btn.setFixedSize(26, 26)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(close_btn)
        return bar

    def paintEvent(self, a0: QPaintEvent | None) -> None:  # noqa: ARG002
        palette = _PALETTES[self._theme]
        rgba = cast("dict[str, tuple[int, int, int, int]]", palette)
        bg = rgba["window_bg"]
        if self._frosted:
            # Translucent so the KWin blur behind the window shows through as frost.
            bg = (bg[0], bg[1], bg[2], 165)
        else:
            # Opacity drives the window fill directly: 100% is fully opaque (alpha
            # 255, not the palette's slightly-translucent default), 0% invisible.
            bg = (bg[0], bg[1], bg[2], max(0, min(255, round(255 * self._win_opacity))))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(*bg))
        painter.setPen(QPen(QColor(*rgba["window_border"])))
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.drawRoundedRect(rect, float(_RADIUS), float(_RADIUS))

    def _window_ptr(self) -> int | None:
        self.winId()  # force native handle creation
        handle = self.windowHandle()
        return sip.unwrapinstance(handle) if handle is not None else None

    def _apply_blur(self) -> None:
        if not self._frosted:
            return
        ptr = self._window_ptr()
        if ptr is not None:
            self._blur.set_blur_region(ptr, 0, 0, self.width(), self.height(), _RADIUS)

    def hideEvent(self, a0: QHideEvent | None) -> None:
        if self._frosted:
            ptr = self._window_ptr()
            if ptr is not None:
                self._blur.clear_blur(ptr)
        super().hideEvent(a0)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        super().resizeEvent(a0)
        self._apply_blur()  # keep the blur region matched to the window size

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        # Wayland forbids client-side move(); use the compositor's system move.
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                a0.accept()
                return
        super().mousePressEvent(a0)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        # Now the stylesheet metrics are active: size the sidebar to its widest
        # label (in any language) and the content to the tallest page, so switching
        # sections never resizes the window and the nav never truncates.
        self._nav.setFixedWidth(self._nav.sizeHintForColumn(0) + 30)
        self._stack.setMinimumWidth(400)
        widgets = (self._stack.widget(i) for i in range(self._stack.count()))
        tallest = max((widget.sizeHint().height() for widget in widgets if widget is not None), default=0)
        self._stack.setMinimumHeight(tallest)
        needed = self._nav.width() + 1 + 400 + 46  # nav + divider + content + margins/spacing
        if self.minimumWidth() < needed:
            self.setMinimumWidth(needed)
        if self.width() < needed:
            self.resize(needed, self.height())
        # Gentle fade-in on first show (once), if animations are enabled. Skipped on
        # Wayland, where windowOpacity is a no-op that only logs a warning per frame.
        if self._config.fx_animate and not self._did_fade_in and self._window_opacity_ok:
            self._did_fade_in = True
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(160)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._apply_blur()  # frost the window backdrop once it is shown + sized

    # --- tabs ---

    def _general_tab(self) -> QWidget:
        page, form = self._form_page()
        self._ui_language = QComboBox()
        for value, label in UI_LANGUAGES:
            self._ui_language.addItem(label, value)
        idx = self._ui_language.findData(self._config.ui_language)
        self._ui_language.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(t("set.language"), self._ui_language)
        form.addRow(self._hint(t("set.language_hint")))

        # Settings-window theme: follow the system light/dark scheme, or force one.
        self._theme_combo = QComboBox()
        for value, key in (("auto", "theme.auto"), ("light", "theme.light"), ("dark", "theme.dark")):
            self._theme_combo.addItem(t(key), value)
        theme_idx = self._theme_combo.findData(self._config.theme)
        self._theme_combo.setCurrentIndex(theme_idx if theme_idx >= 0 else 0)
        form.addRow(t("set.theme"), self._theme_combo)

        # Frosted-glass settings window (real KWin blur; no effect off KDE Wayland).
        self._frost_window = QCheckBox(t("set.frost_window"))
        self._frost_window.setChecked(self._config.frost_window)
        form.addRow(self._frost_window)
        if not self._blur_capable:
            form.addRow(self._hint(t("set.frost_window_hint")))

        # How see-through this settings window is (whole window; text stays legible).
        self._settings_opacity = self._spin(0, 100, round(self._config.settings_opacity * 100), " %")
        self._settings_opacity.valueChanged.connect(self._preview_window_opacity)  # live while changing
        form.addRow(t("set.settings_opacity"), self._settings_opacity)

        # Hidden until the language selection differs from what is running; the UI
        # is only rebuilt on restart, so offer to do it right here.
        self._restart_btn = QPushButton(t("btn.restart"))
        self._restart_btn.setVisible(False)
        self._restart_btn.clicked.connect(self._request_restart)
        form.addRow(self._restart_btn)
        # Connect after the button exists so the handler never runs before it.
        self._ui_language.currentIndexChanged.connect(self._update_restart_hint)
        return page

    def _icon_tab(self) -> QWidget:
        # Tray and window/taskbar icons are chosen separately (their own tab so the
        # two full-width strips don't stretch General). Each picker spans the width
        # with its label above, so the styles fit a row and the hint sits under them.
        page, form = self._form_page()
        self._tray_icon_list = self._build_icon_picker(self._config.icon_name)
        form.addRow(QLabel(t("set.tray_icon")))
        form.addRow(self._tray_icon_list)
        form.addRow(self._hint(t("set.tray_icon_hint")))

        self._window_icon_list = self._build_icon_picker(self._config.window_icon_name)
        form.addRow(QLabel(t("set.window_icon")))
        form.addRow(self._window_icon_list)
        form.addRow(self._hint(t("set.window_icon_hint")))
        return page

    def _update_logo_badge(self) -> None:
        """Set the title-bar badge to the accent-tinted leaf logo (centred, crisp)."""
        pixmap = leaf_icon.render_leaf(leaf_icon.ACCENT, self._config.accent_start, size=44)
        pixmap.setDevicePixelRatio(2.0)  # 44px @2x -> a crisp 22px badge
        self._logo_badge.setPixmap(pixmap)

    def _update_restart_hint(self) -> None:
        self._restart_btn.setVisible(self._ui_language.currentData() != self._initial_ui_language)

    def _request_restart(self) -> None:
        self._emit()  # persist the new language before relaunching
        self.restart_requested.emit()

    def _preview_window_opacity(self, percent: int) -> None:
        """Live see-through preview: re-thin the window fill (repaint) and, in the
        light theme, the card (re-skin), so dragging the spin box shows immediately."""
        self._win_opacity = percent / 100.0
        self.setStyleSheet(_skin(self._config.accent_start, self._theme, self._frosted, self._win_opacity))
        self.update()

    @staticmethod
    def _resolve_font_family(font_family: str) -> str:
        """The family to show in the picker: the first family in the configured list
        that is actually installed, else the first installed CJK-capable fallback.
        Without this, a configured-but-absent family (the default "Inter" on a box
        that lacks it) lets fontconfig substitute an arbitrary, often odd font
        ("Noto Sans Myanmar SemiCondensed") into the picker."""
        installed = set(QFontDatabase.families())
        requested = [name.strip().strip("'\"") for name in font_family.split(",")]
        for name in requested:
            if name and name in installed:
                return name
        for fallback in _FONT_FALLBACKS:
            if fallback in installed:
                return fallback
        return next((name for name in requested if name), "")

    def _text_tab(self) -> QWidget:
        c = self._config
        page, form = self._form_page()
        self._font_family = QFontComboBox()
        # Selection, not a text box: clicking anywhere opens the font list. The
        # custom delegate previews each name in its own font without the "T" icon.
        self._font_family.setEditable(False)
        self._font_family.setIconSize(QSize(0, 0))
        self._font_family.setItemDelegate(_FontNameDelegate(self._font_family))
        self._font_family.setCurrentFont(QFont(self._resolve_font_family(c.font_family)))
        form.addRow(t("set.font_family"), self._font_family)

        # KDE-style style picker (Regular / Bold / Light / Italic / Condensed …) fed
        # by the chosen family's real styles — no numeric weight, no faux styling.
        self._font_style = QComboBox()
        self._rebuild_style_options(self._font_family.currentFont().family(), prefer=c.font_style)
        self._font_family.currentFontChanged.connect(lambda font: self._rebuild_style_options(font.family()))
        form.addRow(t("set.font_style"), self._font_style)

        self._font_size = self._spin(8, 120, c.font_size, " px")
        form.addRow(t("set.font_size"), self._font_size)
        self._context_font_size = self._spin(8, 120, c.context_font_size, " px")
        form.addRow(t("set.context_font_size"), self._context_font_size)
        self._translation_font_size = self._spin(8, 120, c.translation_font_size, " px")
        form.addRow(t("set.translation_font_size"), self._translation_font_size)
        return page

    def _panel_tab(self) -> QWidget:
        c = self._config
        page, form = self._form_page()
        self._panel = QComboBox()
        self._panel.addItem(t("set.panel.pill"), "pill")
        self._panel.addItem(t("set.panel.white"), "white")
        self._panel.addItem(t("set.panel.frost"), "frost")
        self._panel.addItem(t("set.panel.text"), "text")
        panel_index = self._panel.findData(c.panel_style)
        self._panel.setCurrentIndex(panel_index if panel_index >= 0 else 0)
        form.addRow(t("set.panel_style"), self._panel)

        self._panel_width_mode = QComboBox()
        self._panel_width_mode.addItem(t("panelsize.fit"), "fit")
        self._panel_width_mode.addItem(t("panelsize.fixed"), "fixed")
        width_index = self._panel_width_mode.findData(c.panel_width_mode)
        self._panel_width_mode.setCurrentIndex(width_index if width_index >= 0 else 0)
        form.addRow(t("set.panel_size"), self._panel_width_mode)

        self._panel_width = self._spin(240, 2400, c.panel_width, " px")
        self._panel_width.setSingleStep(20)
        form.addRow(t("set.panel_width"), self._panel_width)
        form.addRow(self._hint(t("set.panel_size_hint")))
        self._panel_width_mode.currentIndexChanged.connect(self._update_panel_width_enabled)
        self._update_panel_width_enabled()

        # Each panel style keeps its own opacity (0..100%); the black panel can go
        # fully transparent, the frosted one to pure blur.
        self._panel_opacity = {"opacity": c.opacity, "frost_opacity": c.frost_opacity}
        self._opacity_active_key = self._opacity_key()
        self._opacity = self._spin(0, 100, round(self._panel_opacity[self._opacity_active_key] * 100), " %")
        form.addRow(t("set.opacity"), self._opacity)
        self._panel.currentIndexChanged.connect(self._on_panel_style_changed)

        self._panel_tint = QCheckBox(t("set.panel_tint"))
        self._panel_tint.setChecked(c.panel_accent_tint)
        form.addRow(self._panel_tint)
        form.addRow(self._hint(t("set.panel_hint")))
        return page

    def _effects_tab(self) -> QWidget:
        c = self._config
        page, form = self._form_page()
        self._accent = QComboBox()
        self._custom_index = -1  # single reusable slot for a picked colour
        matched = False
        for key, start, end, sweep in ACCENT_PRESETS:
            self._accent.addItem(t(f"accent.{key}"), (start, end, sweep))
            if start.lower() == c.accent_start.lower():
                self._accent.setCurrentIndex(self._accent.count() - 1)
                matched = True
        if not matched:  # a saved custom colour -> one labelled slot
            self._set_custom_accent((c.accent_start, c.accent_end, c.accent_sweep))
        # A trailing picker entry (data=None) opens a full colour picker.
        self._accent.addItem(t("set.accent.pick"), None)
        self._accent_last_index = self._accent.currentIndex()
        self._accent.activated.connect(self._on_accent_activated)
        form.addRow(t("set.accent"), self._accent)

        self._fx_animate = QCheckBox(t("set.fx_animate"))
        self._fx_animate.setChecked(c.fx_animate)
        form.addRow(self._fx_animate)
        # Line-change transition style; only bites while "Animate" is on.
        self._fx_transition = QComboBox()
        for value, key in (
            ("fade", "fxtrans.fade"),
            ("rise", "fxtrans.rise"),
            ("slide", "fxtrans.slide"),
            ("zoom", "fxtrans.zoom"),
        ):
            self._fx_transition.addItem(t(key), value)
        trans_idx = self._fx_transition.findData(c.fx_transition)
        self._fx_transition.setCurrentIndex(trans_idx if trans_idx >= 0 else 1)
        form.addRow(t("set.fx_transition"), self._fx_transition)
        self._fx_glow = QCheckBox(t("set.fx_glow"))
        self._fx_glow.setChecked(c.fx_glow)
        form.addRow(self._fx_glow)
        self._fx_word_pop = QCheckBox(t("set.fx_word_pop"))
        self._fx_word_pop.setChecked(c.fx_word_pop)
        form.addRow(self._fx_word_pop)
        self._fx_intensity = QComboBox()
        for value, key in (("subtle", "fxintensity.subtle"), ("expressive", "fxintensity.expressive")):
            self._fx_intensity.addItem(t(key), value)
        fx_idx = self._fx_intensity.findData(c.fx_intensity)
        self._fx_intensity.setCurrentIndex(fx_idx if fx_idx >= 0 else 0)
        form.addRow(t("set.fx_intensity"), self._fx_intensity)
        return page

    def _set_custom_accent(self, triple: tuple[str, str, str]) -> None:
        """Show the picked colour in a single reusable slot, labelled with its hex
        (so different customs are distinguishable) instead of piling up entries."""
        label = f"{t('set.accent.custom')} {triple[0].upper()}"
        if self._custom_index >= 0:
            self._accent.setItemText(self._custom_index, label)
            self._accent.setItemData(self._custom_index, triple)
        else:
            picker = self._accent.findData(None)  # insert before the trailing picker, if present
            insert_at = picker if picker >= 0 else self._accent.count()
            self._accent.insertItem(insert_at, label, triple)
            self._custom_index = insert_at
        self._accent.setCurrentIndex(self._custom_index)

    def _update_panel_width_enabled(self) -> None:
        # The width value only applies to the "Fixed width" mode.
        self._panel_width.setEnabled(str(self._panel_width_mode.currentData()) == "fixed")

    def _opacity_key(self) -> str:
        return "frost_opacity" if str(self._panel.currentData()) == "frost" else "opacity"

    def _on_panel_style_changed(self) -> None:
        # Remember the outgoing style's opacity, then load the incoming style's, so
        # the black panel and the frosted panel keep independent opacity values.
        self._panel_opacity[self._opacity_active_key] = self._opacity.value() / 100.0
        self._opacity_active_key = self._opacity_key()
        self._opacity.setValue(round(self._panel_opacity[self._opacity_active_key] * 100))

    def _on_accent_activated(self, index: int) -> None:
        if self._accent.itemData(index) is not None:
            self._accent_last_index = index  # a preset / the custom slot
            return
        # The "Custom…" entry: pick a colour and derive the gradient + sweep from it.
        chosen = QColorDialog.getColor(QColor(self._config.accent_start), self, t("set.accent"))
        if not chosen.isValid():
            self._accent.setCurrentIndex(self._accent_last_index)  # cancelled -> revert
            return
        self._set_custom_accent((chosen.name(), chosen.lighter(140).name(), chosen.lighter(120).name()))
        self._accent_last_index = self._accent.currentIndex()

    def _lyrics_tab(self) -> QWidget:
        c = self._config
        page, form = self._form_page()

        self._karaoke = QCheckBox(t("set.karaoke"))
        self._karaoke.setChecked(c.karaoke)
        form.addRow(self._karaoke)

        self._lead = self._spin(-1000, 1000, c.lead_ms, " ms")
        self._lead.setSingleStep(20)
        self._lead.setToolTip(t("set.lead.tip"))
        form.addRow(t("set.lead"), self._lead)

        self._translation = QCheckBox(t("set.show_translation"))
        self._translation.setChecked(c.show_translation)
        form.addRow(self._translation)

        # Display-side 簡/繁 conversion of the shown lyrics (belongs with the lyrics,
        # not with the app-wide General options where it used to sit).
        self._lyrics_script = QComboBox()
        for value, key in (
            ("off", "lyricscript.off"),
            ("zh-Hans", "lyricscript.hans"),
            ("zh-Hant", "lyricscript.hant"),
        ):
            self._lyrics_script.addItem(t(key), value)
        script_idx = self._lyrics_script.findData(c.lyrics_script)
        self._lyrics_script.setCurrentIndex(script_idx if script_idx >= 0 else 0)
        form.addRow(t("set.lyrics_script"), self._lyrics_script)
        form.addRow(self._hint(t("set.lyrics_script_hint")))
        return page

    def _position_tab(self) -> QWidget:
        c = self._config
        page, form = self._form_page()

        self._anchor = QComboBox()
        self._anchor.addItem(t("set.top"), True)
        self._anchor.addItem(t("set.bottom"), False)
        self._anchor.setCurrentIndex(0 if c.anchor_top else 1)
        form.addRow(t("set.position"), self._anchor)

        self._margin_edge = self._spin(0, 4000, c.margin_edge, " px")
        form.addRow(t("set.margin_edge"), self._margin_edge)

        self._margin_x = self._spin(-2000, 2000, c.margin_x, " px")
        form.addRow(t("set.margin_x"), self._margin_x)

        self._passthrough = QCheckBox(t("set.passthrough"))
        self._passthrough.setChecked(c.passthrough)
        form.addRow(self._passthrough)
        form.addRow(self._hint(t("set.box_hint")))
        return page

    def _sources_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self._hint(t("set.sources_hint")))

        self._sources_list = QListWidget()
        self._sources_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        enabled = self._config.lyrics_sources
        ordered = enabled + [s for s in VALID_LYRICS_SOURCES if s not in enabled]
        for source in ordered:
            item = QListWidgetItem(t(f"src.{source}"))
            item.setData(Qt.ItemDataRole.UserRole, source)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if source in enabled else Qt.CheckState.Unchecked)
            self._sources_list.addItem(item)
        layout.addWidget(self._sources_list)

        self._prefer_best = QCheckBox(t("set.prefer_best"))
        self._prefer_best.setChecked(self._config.prefer_best_lyrics)
        layout.addWidget(self._prefer_best)
        layout.addWidget(self._hint(t("set.prefer_best_hint")))

        self._fuzzy_match = QCheckBox(t("set.fuzzy_match"))
        self._fuzzy_match.setChecked(self._config.fuzzy_match)
        layout.addWidget(self._fuzzy_match)
        layout.addWidget(self._hint(t("set.fuzzy_match_hint")))

        self._cache_enabled = QCheckBox(t("set.cache_enabled"))
        self._cache_enabled.setChecked(self._config.cache_enabled)
        layout.addWidget(self._cache_enabled)

        self._clear_cache = QPushButton(t("btn.clear_cache"))
        self._clear_cache.clicked.connect(lambda _checked=False: self.clear_cache_requested.emit())
        layout.addWidget(self._clear_cache)
        return page

    def _selected_sources(self) -> list[str]:
        sources: list[str] = []
        for i in range(self._sources_list.count()):
            item = self._sources_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                sources.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return sources

    # --- helpers ---

    def _form_page(self) -> tuple[QWidget, QFormLayout]:
        """A tab page whose form has roomy, consistent spacing. A trailing stretch
        pins the rows to the top so a sparse tab (or a wrapping hint) never spreads
        its rows down the whole panel."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(0)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        outer.addLayout(form)
        outer.addStretch(1)
        return page, form

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hint")  # dimmed by the theme QSS
        label.setWordWrap(True)
        return label

    @staticmethod
    def _picked_icon(icon_list: _IconStrip) -> str:
        item = icon_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else DEFAULT_ICON_NAME

    def _build_icon_picker(self, selected_key: str) -> _IconStrip:
        """One icon strip: the generated leaf styles (accent / white / black / tile)
        then the bundled files, with `selected_key` pre-selected. Tray and window
        each get their own strip so they can be chosen independently."""
        icon_list = _IconStrip()
        icon_list.setObjectName("iconPicker")
        icon_list.setViewMode(QListView.ViewMode.IconMode)
        icon_list.setFlow(QListView.Flow.LeftToRight)
        icon_list.setMovement(QListView.Movement.Static)
        icon_list.setResizeMode(QListView.ResizeMode.Adjust)
        icon_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        icon_list.setWrapping(True)
        icon_list.setIconSize(QSize(40, 40))
        icon_list.setGridSize(QSize(54, 54))
        icon_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        icon_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        items: dict[str, QListWidgetItem] = {}
        selected_item: QListWidgetItem | None = None
        default_item: QListWidgetItem | None = None

        def add(key: str, pixmap: QPixmap) -> QListWidgetItem:
            item = QListWidgetItem(self._no_tint_icon(pixmap), "")
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_list.addItem(item)
            items[key] = item
            return item

        # Generated leaf styles first (accent / white / black / tile), then the files.
        # A saved generated key that isn't offered (a legacy "@leaf-mono") is still
        # shown so choosing it stays representable and Apply doesn't silently reset it.
        dark = self._theme == "dark"
        offered = leaf_icon.PICKER_STYLES
        if leaf_icon.is_generated(selected_key) and selected_key not in offered:
            offered = (*offered, selected_key)
        for key in offered:
            item = add(key, leaf_icon.render_leaf(key, self._config.accent_start, dark_panel=dark, size=64))
            if key == selected_key:
                selected_item = item
        for choice in discover_icon_paths():
            source = QIcon(str(choice.path))
            if source.isNull():
                continue
            item = add(choice.key, source.pixmap(QSize(64, 64)))
            if choice.key == selected_key:
                selected_item = item
            if choice.key == DEFAULT_ICON_NAME:
                default_item = item
        icon_list.setCurrentItem(selected_item or default_item)
        self._icon_pickers.append((icon_list, items))
        return icon_list

    def _no_tint_icon(self, pixmap: QPixmap) -> QIcon:
        """A QIcon whose Selected/Active modes reuse the Normal pixmap, so Qt never
        blue-tints the chosen icon; the accent ring alone marks the selection."""
        icon = QIcon()
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
            icon.addPixmap(pixmap, mode)
        return icon

    def _refresh_generated_icons(self) -> None:
        """Re-render the accent/tile leaf previews to the current accent (called on
        Apply so both pickers keep up with an accent change)."""
        dark = self._theme == "dark"
        for _list, items in self._icon_pickers:
            for key in leaf_icon.PICKER_STYLES:
                item = items.get(key)
                if item is not None:
                    pixmap = leaf_icon.render_leaf(key, self._config.accent_start, dark_panel=dark, size=64)
                    item.setIcon(self._no_tint_icon(pixmap))

    def _available_styles(self, family: str) -> list[str]:
        """The family's real styles (Regular/Bold/Light/Italic/Condensed …), plain
        styles first; falls back to a single "Regular" when a family reports none."""
        styles = QFontDatabase.styles(family)
        if not styles:
            return ["Regular"]
        return sorted(styles, key=lambda s: (0 if s in ("Regular", "Book", "Normal") else 1, s))

    def _rebuild_style_options(self, family: str, prefer: str | None = None) -> None:
        """Repopulate the style picker for the chosen family, keeping the selection
        (or `prefer`) if the family still offers it, else defaulting to the first."""
        target = prefer if prefer is not None else self._font_style.currentText()
        styles = self._available_styles(family)
        self._font_style.blockSignals(True)
        self._font_style.clear()
        self._font_style.addItems(styles)
        index = self._font_style.findText(target)
        self._font_style.setCurrentIndex(index if index >= 0 else 0)
        self._font_style.blockSignals(False)

    def _spin(self, low: int, high: int, value: int, suffix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    def current_config(self) -> Config:
        accent_data = self._accent.currentData()
        if accent_data is None:  # the picker entry left selected — keep the current accent
            accent_data = (self._config.accent_start, self._config.accent_end, self._config.accent_sweep)
        accent_start, accent_end, accent_sweep = accent_data
        self._panel_opacity[self._opacity_active_key] = self._opacity.value() / 100.0  # save the active slider
        return replace(
            self._config,
            ui_language=str(self._ui_language.currentData()),
            theme=str(self._theme_combo.currentData()),
            frost_window=self._frost_window.isChecked(),
            settings_opacity=self._settings_opacity.value() / 100.0,
            lyrics_script=str(self._lyrics_script.currentData()),
            icon_name=self._picked_icon(self._tray_icon_list),
            window_icon_name=self._picked_icon(self._window_icon_list),
            font_family=self._font_family.currentFont().family(),
            font_style=self._font_style.currentText(),
            font_size=self._font_size.value(),
            context_font_size=self._context_font_size.value(),
            translation_font_size=self._translation_font_size.value(),
            opacity=self._panel_opacity["opacity"],
            frost_opacity=self._panel_opacity["frost_opacity"],
            panel_style=str(self._panel.currentData()),
            panel_width_mode=str(self._panel_width_mode.currentData()),
            panel_width=self._panel_width.value(),
            panel_accent_tint=self._panel_tint.isChecked(),
            accent_start=accent_start,
            accent_end=accent_end,
            accent_sweep=accent_sweep,
            fx_animate=self._fx_animate.isChecked(),
            fx_transition=str(self._fx_transition.currentData()),
            fx_glow=self._fx_glow.isChecked(),
            fx_word_pop=self._fx_word_pop.isChecked(),
            fx_intensity=str(self._fx_intensity.currentData()),
            karaoke=self._karaoke.isChecked(),
            lead_ms=self._lead.value(),
            show_translation=self._translation.isChecked(),
            anchor_top=bool(self._anchor.currentData()),
            margin_edge=self._margin_edge.value(),
            margin_x=self._margin_x.value(),
            passthrough=self._passthrough.isChecked(),
            lyrics_sources=self._selected_sources(),
            prefer_best_lyrics=self._prefer_best.isChecked(),
            fuzzy_match=self._fuzzy_match.isChecked(),
            cache_enabled=self._cache_enabled.isChecked(),
        ).clamped()

    def _reset_current_page(self) -> None:
        """Restore only the current page's fields to their defaults, keeping every
        other page's edits, then rebuild that page from the reset config. The change
        is staged like any other edit — the user still applies or cancels it."""
        idx = self._nav.currentRow()
        if not 0 <= idx < len(self._page_builders):
            return
        defaults = Config()
        reset_fields = {field: getattr(defaults, field) for field in _PAGE_FIELDS[idx]}
        self._config = replace(self.current_config(), **reset_fields).clamped()
        # Drop the icon strips the page being rebuilt had registered, so _icon_tab
        # re-adding them doesn't leave stale duplicates. (Compare the underlying
        # function — a bound method is a fresh object on every attribute access.)
        if self._page_builders[idx].__func__ is SettingsDialog._icon_tab:
            self._icon_pickers.clear()
        new_page = self._page_builders[idx]()
        old_page = self._stack.widget(idx)
        self._stack.insertWidget(idx, new_page)
        if old_page is not None:
            self._stack.removeWidget(old_page)
            old_page.deleteLater()
        self._stack.setCurrentIndex(idx)

    def _emit(self) -> None:
        self._config = self.current_config()
        # Toggle the frosted backdrop live: apply/clear the KWin blur to match the
        # new setting, so the re-skin below can pick the right (translucent) card.
        frosted = self._blur_capable and self._config.frost_window
        if frosted != self._frosted:
            self._frosted = frosted
            ptr = self._window_ptr()
            if ptr is not None:
                if frosted:
                    self._apply_blur()
                else:
                    self._blur.clear_blur(ptr)
        # Re-skin the dialog itself so an accent OR theme change is visible right
        # away (tab underline, checkbox fill, light/dark palette) rather than only
        # after Settings is closed and reopened.
        self._theme = _resolve_theme(self._config.theme)
        self._win_opacity = self._config.settings_opacity  # commit the see-through level
        self.setStyleSheet(_skin(self._config.accent_start, self._theme, self._frosted, self._win_opacity))
        self._update_logo_badge()  # re-tint the leaf logo to the new accent
        self._refresh_generated_icons()  # re-tint the accent/tile icon previews
        self.update()  # repaint the frameless background (theme / frost)
        self.applied.emit(self._config)

    def _accept(self) -> None:
        self._emit()
        self.accept()
