"""Tabbed settings panel.

Frameless, translucent, dark "glass" styling to match the overlay. Edits a
working copy of :class:`~kotonoha.config.Config` across grouped tabs and emits
``applied`` with the new config when the user applies/accepts. UI strings come
from :mod:`kotonoha.strings`.
"""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QGuiApplication,
    QIcon,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ... import leaf_icon
from ...app.intents import ApplyConfig, ClearCache, OpenCacheManagement, RequestRestart
from ...config import Config
from ...icons import nav_icon
from ...platform import OverlayPlatformFactory
from ...players import PlayerInfo
from ...strings import Translator
from . import theme
from .controls import SettingsWidgets
from .delegates import NavIndicatorDelegate
from .form_state import SettingsFormState
from .icons import selected_icon_name
from .pages import SettingsPageBuilder
from .surface import SettingsTitleBar, ThemedSettingsDialog
from .widgets import PopupSkin

_CHECKMARK_PATH = theme._CHECKMARK_PATH
_PALETTES = theme._PALETTES
_resolve_theme = theme._resolve_theme
_skin = theme._skin
_MINIMUM_WIDTH = 560
_DEFAULT_WIDTH = 860
_DEFAULT_HEIGHT = 680
_MINIMUM_HEIGHT = 480
_SCREEN_MARGIN = 48


# Theme generation lives in theme.py; the dialog owns only lifecycle
# and painting of the resulting window.
class SettingsDialog(ThemedSettingsDialog):
    applied = pyqtSignal(object)  # emits Config
    intent_requested = pyqtSignal(object)  # emits an application intent

    def __init__(
        self,
        config: Config,
        parent: QWidget | None = None,
        *,
        players: list[PlayerInfo] | None = None,
        platform_factory: OverlayPlatformFactory | None = None,
        translator: Translator | None = None,
    ) -> None:
        super().__init__(config, parent, platform_factory=platform_factory)
        self._translator = translator if translator is not None else Translator(config.ui_language)
        self._form_state = SettingsFormState(config)
        self._widgets = SettingsWidgets()
        self._players = tuple(players or ())
        # The UI language only takes effect on restart, so remember what is in
        # effect now to decide when to offer the restart button.
        self._initial_ui_language = self.staged_config.ui_language
        self._did_fade_in = False
        self._apply_surface_style()
        self._mark_surface_style_ready()

        # Sidebar categories drive a stacked content area (replaces top tabs).
        self._stack = QStackedWidget()
        self._page_scrolls: list[QScrollArea] = []
        self._nav = QListWidget()
        self._nav.setObjectName("nav")
        self._nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Without this the list draws each glyph at the icon's own 64px and the row
        # height clips it away, which reads as an icon that failed to load.
        self._nav.setIconSize(QSize(16, 16))
        # The rail carries the accent; the surface it sits inside stays neutral, so
        # the colour marks one page rather than tinting a whole row.
        self._nav_delegate = NavIndicatorDelegate(self._accent, self._nav_glyph(), self._nav)
        self._nav.setItemDelegate(self._nav_delegate)
        # The page builder owns controls and page-local handlers; this dialog owns
        # their lifetime and the staged configuration they edit.
        self._page_builder = SettingsPageBuilder(
            self,
            self._widgets,
            on_clear_cache=self._request_clear_cache,
            on_manage_cache=self._request_manage_cache,
            translator=self._translator,
        )
        self._page_builders = (
            self._page_builder.general_page,
            self._page_builder.icon_page,
            self._page_builder.text_page,
            self._page_builder.panel_page,
            self._page_builder.effects_page,
            self._page_builder.lyrics_page,
            self._page_builder.position_page,
            self._page_builder.sources_page,
        )
        # A hex token, not TEXT_DIM: that one is Qt's rgba(r,g,b,0-255), which an
        # SVG stroke does not parse, and an unparsed stroke paints nothing at all.
        self._nav_keys = (
            "tab.general", "tab.icon", "tab.text", "tab.panel", "tab.effects",
            "tab.lyrics", "tab.position", "tab.sources",
        )
        for key, builder in zip(
            ("tab.general", "tab.icon", "tab.text", "tab.panel", "tab.effects",
             "tab.lyrics", "tab.position", "tab.sources"),
            self._page_builders,
            strict=True,
        ):
            item = QListWidgetItem(nav_icon(key, self._nav_glyph()), self._translator.text(key))
            self._nav.addItem(item)
            self._stack.addWidget(self._scroll_page(builder()))
        # After the pages exist, not before: a combo resets its item delegate when
        # the page builder gives it a model, so styling the popups at surface time
        # reached views that were then handed a default delegate again.
        self._apply_combo_popup_styles()
        self._nav.setCurrentRow(0)
        self._stack.setCurrentIndex(0)
        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self.setMinimumWidth(_MINIMUM_WIDTH)
        self.setMinimumHeight(_MINIMUM_HEIGHT)

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
                btn.setText(self._translator.text(key))
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
        layout.addWidget(self._title_bar())
        layout.addWidget(header_line)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)
        self._set_default_size()

    # --- chrome ---

    def _nav_glyph(self) -> str:
        """Return this theme's colour for the sidebar glyphs.

        A hex token, not TEXT_DIM: that one is Qt's rgba(r,g,b,0-255), which an
        SVG stroke does not parse, and a stroke that does not parse paints
        nothing while reporting no error.
        """
        return str(_PALETTES[self._theme]["TEXT_STRONG"])

    def _refresh_themed_icons(self) -> None:
        """Redraw the sidebar glyphs after a theme change."""
        colour = self._nav_glyph()
        for row, key in enumerate(self._nav_keys):
            item = self._nav.item(row)
            if item is not None:
                item.setIcon(nav_icon(key, colour))
        # The rail and the tint behind the current row are the delegate's, not the
        # stylesheet's, so reapplying the skin does not reach them.
        self._nav_delegate.set_colours(self.staged_config.accent_start, colour)
        viewport = self._nav.viewport()
        if viewport is not None:
            viewport.update()

    def _apply_surface_style(self) -> None:
        """Apply the shared settings skin to the current staged surface state."""
        self.setStyleSheet(
            _skin(self.staged_config.accent_start, self._theme, self._frosted, self._win_opacity)
        )
        self._apply_combo_popup_styles()

    def _apply_combo_popup_styles(self) -> None:
        """Hand every dropdown the skin its popup should wear.

        The popup itself is dressed by the combo, not here: a combo rebuilds its
        popup container, so anything applied to the view at this point is gone by
        the time the list opens.
        """
        palette = theme._PALETTES[self._theme]
        skin = PopupSkin(
            stylesheet=theme._popup_skin(self._accent, self._theme),
            background=theme._popup_background(self._theme),
            accent=self._accent,
            text=str(palette["TEXT"]),
            on_accent=str(palette["GLYPH_ON_ACCENT"]),
        )
        for combo in (
            self._widgets.ui_language,
            self._widgets.theme_combo,
            self._widgets.font_family,
            self._widgets.font_style,
            self._widgets.panel,
            self._widgets.panel_width_mode,
            self._widgets.panel_overflow_mode,
            self._widgets.accent,
            self._widgets.fx_transition,
            self._widgets.fx_intensity,
            self._widgets.lyrics_script,
            self._widgets.interlude_style,
            self._widgets.interlude_countdown,
            self._widgets.anchor,
            self._widgets.player_combo,
        ):
            combo.set_popup_skin(skin)

    def _title_bar(self) -> QWidget:
        title_bar = SettingsTitleBar()
        bar = QHBoxLayout(title_bar)
        # The previous title bar was a layout nested directly in the dialog and
        # therefore had no child-widget margins. Keep that geometry while the
        # wrapper gives us a dedicated drag target.
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(9)
        self._logo_badge = QLabel()
        self._logo_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._update_logo_badge()  # accent-tinted leaf logo (falls back to the app icon)
        bar.addWidget(self._logo_badge)
        title = QLabel(self._translator.text("settings.title"))
        title.setObjectName("dialogTitle")  # styled by the theme QSS
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeButton")
        close_btn.setFixedSize(26, 26)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(close_btn)
        return title_bar

    def _scroll_page(self, page: QWidget) -> QScrollArea:
        """Put one settings page behind a bounded, independently scrollable view."""
        scroll = QScrollArea()
        scroll.setObjectName("settingsPageScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        viewport = scroll.viewport()
        if viewport is not None:
            viewport.setAutoFillBackground(False)
        scroll.setWidget(page)
        # QScrollArea reparents the page and may re-polish it; restore the
        # transparent contract after that operation so the default palette cannot
        # paint a light rectangle over the themed card.
        page.setAutoFillBackground(False)
        self._page_scrolls.append(scroll)
        return scroll

    def _set_default_size(self) -> None:
        """Choose a useful initial size without allowing content to fill the screen."""
        width = _DEFAULT_WIDTH
        height = _DEFAULT_HEIGHT
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, max(_MINIMUM_WIDTH, available.width() - _SCREEN_MARGIN))
            height = min(height, max(_MINIMUM_HEIGHT, available.height() - _SCREEN_MARGIN))
        self.resize(width, height)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        # Now the stylesheet metrics are active: size the sidebar to its widest
        # label (in any language), so switching sections never resizes the window and
        # the nav never truncates. Page height belongs to its own scroll area.
        self._nav.setFixedWidth(self._nav.sizeHintForColumn(0) + 30)
        self._stack.setMinimumWidth(400)
        self._stack.setMinimumHeight(0)
        needed = self._nav.width() + 1 + 400 + 46  # nav + divider + content + margins/spacing
        if self.minimumWidth() < needed:
            self.setMinimumWidth(needed)
        if self.width() < needed:
            self.resize(needed, self.height())
        # Gentle fade-in on first show (once), if animations are enabled. Skipped on
        # Wayland, where windowOpacity is a no-op that only logs a warning per frame.
        if self.staged_config.fx_animate and not self._did_fade_in and self._window_opacity_ok:
            self._did_fade_in = True
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(160)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._apply_blur()  # frost the window backdrop once it is shown + sized

    # --- chrome and staged form helpers ---

    def _update_logo_badge(self) -> None:
        """Set the title-bar badge to the accent-tinted leaf logo."""
        pixmap = leaf_icon.render_leaf(leaf_icon.ACCENT, self.staged_config.accent_start, size=44)
        pixmap.setDevicePixelRatio(2.0)
        self._logo_badge.setPixmap(pixmap)

    @property
    def staged_config(self) -> Config:
        """Return the configuration currently staged by this dialog."""
        return self._form_state.config

    @property
    def players(self) -> tuple[PlayerInfo, ...]:
        """Return the discovered players offered by the source page."""
        return self._players

    @property
    def blur_capable(self) -> bool:
        """Return whether the injected platform can blur this settings window."""
        return self._blur_capable

    @property
    def blur_reason(self) -> str | None:
        """Return why blur is unavailable, when the platform supplied a reason."""
        return self._blur_reason

    @property
    def theme_name(self) -> str:
        """Return the active settings-window theme name."""
        return self._theme

    @property
    def form_widgets(self) -> SettingsWidgets:
        """Return the controls owned by this settings form instance."""
        return self._widgets

    def _update_restart_hint(self) -> None:
        """Show restart when the staged UI language differs from the active one."""
        self._widgets.restart_button.setVisible(
            self._widgets.ui_language.currentData() != self._initial_ui_language
        )

    def _request_restart(self) -> None:
        """Persist staged settings before asking the application to restart."""
        self._emit()
        self.intent_requested.emit(RequestRestart())

    def _request_clear_cache(self) -> None:
        """Submit the typed cache action owned by the application controller."""
        self.intent_requested.emit(ClearCache())

    def _request_manage_cache(self) -> None:
        """Submit the request to open the independent cache-management window."""
        self.intent_requested.emit(OpenCacheManagement())

    def current_config(self) -> Config:
        w = self._widgets
        accent_data = w.accent.currentData()
        if accent_data is None:  # the picker entry left selected — keep the current accent
            accent_data = (
                self.staged_config.accent_start,
                self.staged_config.accent_end,
                self.staged_config.accent_sweep,
            )
        accent_start, accent_end, accent_sweep = accent_data
        w.panel_opacity.set_value(w.opacity_active_key, w.opacity.value / 100.0)  # save the active slider
        return replace(
            self.staged_config,
            ui_language=str(w.ui_language.currentData()),
            theme=str(w.theme_combo.currentData()),
            frost_window=w.frost_window.isChecked(),
            settings_opacity=w.settings_opacity.value / 100.0,
            lyrics_script=str(w.lyrics_script.currentData()),
            interlude_style=str(w.interlude_style.currentData()),
            interlude_countdown=str(w.interlude_countdown.currentData()),
            icon_name=selected_icon_name(w.tray_icon_list),
            window_icon_name=selected_icon_name(w.window_icon_list),
            font_family=self._page_builder.chosen_font_family(),
            font_style=self._page_builder.chosen_font_style(),
            font_size=w.font_size.value(),
            context_font_size=w.context_font_size.value(),
            translation_font_size=w.translation_font_size.value(),
            opacity=w.panel_opacity.opacity,
            frost_opacity=w.panel_opacity.frost_opacity,
            panel_style=str(w.panel.currentData()),
            panel_width_mode=str(w.panel_width_mode.currentData()),
            panel_width=w.panel_width.value(),
            panel_overflow_mode=str(w.panel_overflow_mode.currentData()),
            panel_accent_tint=w.panel_tint.isChecked(),
            accent_start=accent_start,
            accent_end=accent_end,
            accent_sweep=accent_sweep,
            fx_animate=w.fx_animate.isChecked(),
            fx_transition=str(w.fx_transition.currentData()),
            fx_glow=w.fx_glow.isChecked(),
            fx_word_pop=w.fx_word_pop.isChecked(),
            fx_intensity=str(w.fx_intensity.currentData()),
            karaoke=w.karaoke.isChecked(),
            lead_ms=w.lead.value(),
            show_translation=w.translation.isChecked(),
            context_lines=w.context_lines.value(),
            context_blur=w.context_blur.value / 100.0,
            anchor_top=bool(w.anchor.currentData()),
            margin_edge=w.margin_edge.value(),
            margin_x=w.margin_x.value(),
            screen_name=self.staged_config.screen_name,
            passthrough=w.passthrough.isChecked(),
            lyrics_sources=self._page_builder.selected_sources(),
            display_sources=self._page_builder.selected_display_sources(),
            prefer_best_lyrics=w.prefer_best.isChecked(),
            fuzzy_match=w.fuzzy_match.isChecked(),
            cache_enabled=w.cache_enabled.isChecked(),
            cider_api_token=w.cider_token.text().strip(),
            player_lock=str(w.player_combo.currentData()),
        ).clamped()

    def _reset_current_page(self) -> None:
        """Restore only the current page's fields to their defaults, keeping every
        other page's edits, then rebuild that page from the reset config. The change
        is staged like any other edit — the user still applies or cancels it."""
        idx = self._nav.currentRow()
        if not 0 <= idx < len(self._page_builders):
            return
        defaults = Config()
        self._form_state.reset_page(idx, defaults)
        # Drop the icon strips the page being rebuilt had registered, so _icon_tab
        # re-adding them doesn't leave stale duplicates. (Compare the underlying
        # page index explicitly: bound-method reflection would hide ownership.
        if idx == 1:
            self._widgets.icon_pickers.clear()
        new_page = self._page_builders[idx]()
        old_page = self._stack.widget(idx)
        self._stack.insertWidget(idx, new_page)
        if old_page is not None:
            self._stack.removeWidget(old_page)
            old_page.deleteLater()
        self._stack.setCurrentIndex(idx)
        # The rebuilt page carries new combos, which start with a default delegate.
        self._apply_combo_popup_styles()

    def _emit(self) -> None:
        self._form_state.replace(self.current_config())
        changed_fields = self._form_state.changed_fields()
        # Toggle the frosted backdrop live: apply/clear the KWin blur to match the
        # new setting, so the re-skin below can pick the right (translucent) card.
        frosted = self._blur_capable and self.staged_config.frost_window
        if frosted != self._frosted and self._platform is not None:
            self._frosted = frosted
            blur = self._platform.blur
            if blur is not None:
                if frosted:
                    self._apply_blur()
                else:
                    blur.set_blur_region(None)
        # Re-skin the dialog itself so an accent OR theme change is visible right
        # away (tab underline, checkbox fill, light/dark palette) rather than only
        # after Settings is closed and reopened.
        self._theme = _resolve_theme(self.staged_config.theme)
        self._accent = self.staged_config.accent_start
        self._win_opacity = self.staged_config.settings_opacity  # commit the see-through level
        self._apply_surface_style()
        # This window restyles itself here rather than through retheme(), so the
        # icons it coloured from the palette have to be redrawn on this path too.
        self._refresh_themed_icons()
        self._update_logo_badge()  # re-tint the leaf logo to the new accent
        self._page_builder.refresh_generated_icons()  # re-tint the accent/tile icon previews
        self.update()  # repaint the frameless background (theme / frost)
        self.applied.emit(self.staged_config)
        self.intent_requested.emit(ApplyConfig(self.staged_config, changed_fields))
        self._form_state.mark_applied()

    def _accept(self) -> None:
        self._emit()
        self.accept()
