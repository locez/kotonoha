"""Page construction and page-local interactions for the settings dialog."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QColorDialog,
    QFormLayout,
    QLabel,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...config import ACCENT_PRESETS, LEAD_MS_LIMIT, Config
from ...strings import UI_LANGUAGES, Translator
from .controls import OpacityKey, PanelOpacityState, SettingsWidgets
from .delegates import FontNameDelegate
from .icons import SettingsIconPageBuilder
from .sources import SettingsSourcesPageBuilder
from .widgets import available_font_styles, resolve_font_family

if TYPE_CHECKING:
    from .dialog import SettingsDialog


class SettingsPageBuilder:
    """Own construction and local signal handlers for all settings pages.

    The explicit widget adapter owns controls while the dialog owns window
    chrome, staged configuration, and commit behavior.
    """

    def __init__(
        self,
        dialog: SettingsDialog,
        widgets: SettingsWidgets,
        *,
        on_clear_cache: Callable[[], None],
        on_manage_cache: Callable[[], None],
        translator: Translator,
    ) -> None:
        self._dialog = dialog
        self._widgets = widgets
        self._translator = translator
        self._sources = SettingsSourcesPageBuilder(
            dialog,
            widgets,
            on_clear_cache=on_clear_cache,
            on_manage_cache=on_manage_cache,
            translator=translator,
        )
        self._icons = SettingsIconPageBuilder(dialog, widgets, translator=translator)
        self._connect_signals()

    def _connect_signals(self) -> None:
        """Connect reusable controls once; page rebuilds only refresh their values."""
        d = self._dialog
        w = self._widgets
        w.restart_button.clicked.connect(d._request_restart)
        w.ui_language.currentIndexChanged.connect(d._update_restart_hint)
        w.font_family.currentFontChanged.connect(self.on_font_family_changed)
        w.font_style.currentTextChanged.connect(self.on_font_style_changed)
        w.panel_width_mode.currentIndexChanged.connect(self.update_panel_width_enabled)
        w.panel.currentIndexChanged.connect(self.on_panel_style_changed)
        w.accent.activated.connect(self.on_accent_activated)

    @property
    def _config(self) -> Config:
        return self._dialog.staged_config

    def general_page(self) -> QWidget:
        """Build the language, theme, blur, and settings-opacity page."""
        t = self._translator.text
        d = self._dialog
        w = self._widgets
        page, form = self._form_page()
        for value, label in UI_LANGUAGES:
            w.ui_language.addItem(label, value)
        idx = w.ui_language.findData(self._config.ui_language.value)
        w.ui_language.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(t("set.language"), w.ui_language)
        form.addRow(self._hint(t("set.language_hint")))

        for value, key in (("auto", "theme.auto"), ("light", "theme.light"), ("dark", "theme.dark")):
            w.theme_combo.addItem(t(key), value)
        theme_idx = w.theme_combo.findData(self._config.theme.value)
        w.theme_combo.setCurrentIndex(theme_idx if theme_idx >= 0 else 0)
        form.addRow(t("set.theme"), w.theme_combo)

        w.frost_window.setText(t("set.frost_window"))
        w.frost_window.setChecked(self._config.frost_window)
        w.frost_window.setEnabled(d.blur_capable)
        form.addRow(w.frost_window)
        reason_key = {
            "session": "set.frost_window.no_session",
            "bridge": "set.frost_window.no_bridge",
            "protocol": "set.frost_window.no_protocol",
            "build": "set.frost_window.no_build",
        }.get(d.blur_reason or "")
        form.addRow(self._hint(t(reason_key) if reason_key else t("set.frost_window_hint")))

        self._configure_spin(w.settings_opacity, 0, 100, round(self._config.settings_opacity * 100), " %")
        form.addRow(t("set.settings_opacity"), w.settings_opacity)

        w.restart_button.setText(t("btn.restart"))
        w.restart_button.setVisible(False)
        form.addRow(w.restart_button)
        return page

    def icon_page(self) -> QWidget:
        """Build the independent tray and window icon pickers."""
        return self._icons.build()

    def text_page(self) -> QWidget:
        """Build font-family, font-style, and size controls."""
        t = self._translator.text
        w = self._widgets
        page, form = self._form_page()
        w.font_family.setEditable(False)
        w.font_family.setIconSize(QSize(0, 0))
        w.font_family.setItemDelegate(FontNameDelegate(w.font_family))
        w.font_family_shown = resolve_font_family(self._config.font_family)
        w.font_family_configured = self._config.font_family
        w.font_family.setCurrentFont(QFont(w.font_family_shown))
        # QFontComboBox can normalize a family that is absent from its own list;
        # compare against what the control actually shows, not the requested name.
        w.font_family_shown = w.font_family.currentFont().family()
        form.addRow(t("set.font_family"), w.font_family)

        w.font_style_configured = self._config.font_style
        w.font_style_user_changed = False
        self.rebuild_style_options(w.font_family.currentFont().family(), prefer=self._config.font_style)
        form.addRow(t("set.font_style"), w.font_style)

        self._configure_spin(w.font_size, 8, 120, self._config.font_size, " px")
        form.addRow(t("set.font_size"), w.font_size)
        self._configure_spin(w.context_font_size, 8, 120, self._config.context_font_size, " px")
        form.addRow(t("set.context_font_size"), w.context_font_size)
        self._configure_spin(w.translation_font_size, 8, 120, self._config.translation_font_size, " px")
        form.addRow(t("set.translation_font_size"), w.translation_font_size)
        return page

    def panel_page(self) -> QWidget:
        """Build panel style, width, opacity, and tint controls."""
        t = self._translator.text
        w = self._widgets
        page, form = self._form_page()
        w.panel.clear()
        for label, value in (
            ("set.panel.pill", "pill"), ("set.panel.white", "white"),
            ("set.panel.frost", "frost"), ("set.panel.text", "text"),
        ):
            w.panel.addItem(t(label), value)
        panel_index = w.panel.findData(self._config.panel_style.value)
        w.panel.setCurrentIndex(panel_index if panel_index >= 0 else 0)
        form.addRow(t("set.panel_style"), w.panel)

        w.panel_width_mode.clear()
        w.panel_width_mode.addItem(t("panelsize.fit"), "fit")
        w.panel_width_mode.addItem(t("panelsize.fixed"), "fixed")
        width_index = w.panel_width_mode.findData(self._config.panel_width_mode.value)
        w.panel_width_mode.setCurrentIndex(width_index if width_index >= 0 else 0)
        form.addRow(t("set.panel_size"), w.panel_width_mode)

        self._configure_spin(w.panel_width, 240, 2400, self._config.panel_width, " px")
        w.panel_width.setSingleStep(20)
        form.addRow(t("set.panel_width"), w.panel_width)
        form.addRow(self._hint(t("set.panel_size_hint")))
        self.update_panel_width_enabled()

        w.panel_opacity = PanelOpacityState(self._config.opacity, self._config.frost_opacity)
        w.opacity_active_key = self.opacity_key()
        self._configure_spin(w.opacity, 0, 100, round(w.panel_opacity.value_for(w.opacity_active_key) * 100), " %")
        form.addRow(t("set.opacity"), w.opacity)
        w.panel_tint.setText(t("set.panel_tint"))
        w.panel_tint.setChecked(self._config.panel_accent_tint)
        form.addRow(w.panel_tint)
        form.addRow(self._hint(t("set.panel_hint")))
        return page

    def effects_page(self) -> QWidget:
        """Build accent and visual-effect controls."""
        t = self._translator.text
        w = self._widgets
        page, form = self._form_page()
        w.accent.clear()
        w.custom_index = -1
        matched = False
        for key, start, end, sweep in ACCENT_PRESETS:
            w.accent.addItem(t(f"accent.{key}"), (start, end, sweep))
            if (start.lower(), end.lower(), sweep.lower()) == (
                self._config.accent_start.lower(), self._config.accent_end.lower(), self._config.accent_sweep.lower()
            ):
                w.accent.setCurrentIndex(w.accent.count() - 1)
                matched = True
        if not matched:
            self.set_custom_accent((self._config.accent_start, self._config.accent_end, self._config.accent_sweep))
        w.accent.addItem(t("set.accent.pick"), None)
        w.accent_last_index = w.accent.currentIndex()
        form.addRow(t("set.accent"), w.accent)

        w.fx_animate.setText(t("set.fx_animate"))
        w.fx_animate.setChecked(self._config.fx_animate)
        form.addRow(w.fx_animate)
        w.fx_transition.clear()
        for value, key in (
            ("fade", "fxtrans.fade"), ("rise", "fxtrans.rise"),
            ("slide", "fxtrans.slide"), ("zoom", "fxtrans.zoom"),
        ):
            w.fx_transition.addItem(t(key), value)
        trans_idx = w.fx_transition.findData(self._config.fx_transition.value)
        w.fx_transition.setCurrentIndex(trans_idx if trans_idx >= 0 else 1)
        form.addRow(t("set.fx_transition"), w.fx_transition)
        w.fx_glow.setText(t("set.fx_glow"))
        w.fx_glow.setChecked(self._config.fx_glow)
        form.addRow(w.fx_glow)
        w.fx_word_pop.setText(t("set.fx_word_pop"))
        w.fx_word_pop.setChecked(self._config.fx_word_pop)
        form.addRow(w.fx_word_pop)
        w.fx_intensity.clear()
        for value, key in (("subtle", "fxintensity.subtle"), ("expressive", "fxintensity.expressive")):
            w.fx_intensity.addItem(t(key), value)
        fx_idx = w.fx_intensity.findData(self._config.fx_intensity.value)
        w.fx_intensity.setCurrentIndex(fx_idx if fx_idx >= 0 else 0)
        form.addRow(t("set.fx_intensity"), w.fx_intensity)
        return page

    def lyrics_page(self) -> QWidget:
        """Build lyric timing, translation, script, and interlude controls."""
        t = self._translator.text
        page, form = self._form_page()
        w = self._widgets
        w.karaoke.setText(t("set.karaoke"))
        w.karaoke.setChecked(self._config.karaoke)
        form.addRow(w.karaoke)
        self._configure_spin(w.lead, -LEAD_MS_LIMIT, LEAD_MS_LIMIT, self._config.lead_ms, " ms")
        w.lead.setSingleStep(20)
        w.lead.setToolTip(t("set.lead.tip"))
        form.addRow(t("set.lead"), w.lead)
        w.translation.setText(t("set.show_translation"))
        w.translation.setChecked(self._config.show_translation)
        form.addRow(w.translation)
        w.current_line_only.setText(t("set.current_line_only"))
        w.current_line_only.setChecked(self._config.current_line_only)
        form.addRow(w.current_line_only)
        form.addRow(self._hint(t("set.current_line_only_hint")))

        w.lyrics_script.clear()
        for value, key in (
            ("off", "lyricscript.off"), ("zh-Hans", "lyricscript.hans"),
            ("zh-Hant", "lyricscript.hant"),
        ):
            w.lyrics_script.addItem(t(key), value)
        script_idx = w.lyrics_script.findData(self._config.lyrics_script.value)
        w.lyrics_script.setCurrentIndex(script_idx if script_idx >= 0 else 0)
        form.addRow(t("set.lyrics_script"), w.lyrics_script)
        form.addRow(self._hint(t("set.lyrics_script_hint")))

        w.interlude_style.clear()
        w.interlude_style.addItem(t("set.interlude.dots"), "dots")
        w.interlude_style.addItem(t("set.interlude.symbol"), "symbol")
        style_idx = w.interlude_style.findData(self._config.interlude_style.value)
        w.interlude_style.setCurrentIndex(style_idx if style_idx >= 0 else 0)
        form.addRow(t("set.interlude_style"), w.interlude_style)
        w.interlude_countdown.clear()
        w.interlude_countdown.addItem(t("set.interlude.count_off"), "off")
        w.interlude_countdown.addItem(t("set.interlude.count_percent"), "percent")
        w.interlude_countdown.addItem(t("set.interlude.count_seconds"), "seconds")
        count_idx = w.interlude_countdown.findData(self._config.interlude_countdown.value)
        w.interlude_countdown.setCurrentIndex(count_idx if count_idx >= 0 else 0)
        form.addRow(t("set.interlude_countdown"), w.interlude_countdown)
        form.addRow(self._hint(t("set.interlude_hint")))
        return page

    def position_page(self) -> QWidget:
        """Build edge anchor, margin, and input-mode controls."""
        t = self._translator.text
        page, form = self._form_page()
        w = self._widgets
        w.anchor.clear()
        w.anchor.addItem(t("set.top"), True)
        w.anchor.addItem(t("set.bottom"), False)
        w.anchor.setCurrentIndex(0 if self._config.anchor_top else 1)
        form.addRow(t("set.position"), w.anchor)
        self._configure_spin(w.margin_edge, 0, 4000, self._config.margin_edge, " px")
        form.addRow(t("set.margin_edge"), w.margin_edge)
        self._configure_spin(w.margin_x, -2000, 2000, self._config.margin_x, " px")
        form.addRow(t("set.margin_x"), w.margin_x)
        w.passthrough.setText(t("set.passthrough"))
        w.passthrough.setChecked(self._config.passthrough)
        form.addRow(w.passthrough)
        form.addRow(self._hint(t("set.box_hint")))
        return page

    def sources_page(self) -> QWidget:
        """Build the source page through its dedicated page owner."""
        return self._sources.build()

    def refresh_generated_icons(self) -> None:
        """Re-render accent-dependent icon previews after Apply."""
        self._icons.refresh_generated_icons()

    def set_custom_accent(self, triple: tuple[str, str, str]) -> None:
        """Show a picked accent in the reusable custom combo entry."""
        w = self._widgets
        label = f"{self._translator.text('set.accent.custom')} {triple[0].upper()}"
        if w.custom_index >= 0:
            w.accent.setItemText(w.custom_index, label)
            w.accent.setItemData(w.custom_index, triple)
        else:
            picker = w.accent.findData(None)
            insert_at = picker if picker >= 0 else w.accent.count()
            w.accent.insertItem(insert_at, label, triple)
            w.custom_index = insert_at
        w.accent.setCurrentIndex(w.custom_index)

    def update_panel_width_enabled(self) -> None:
        """Enable the width value only when fixed-width mode is selected."""
        w = self._widgets
        w.panel_width.setEnabled(str(w.panel_width_mode.currentData()) == "fixed")

    def opacity_key(self) -> OpacityKey:
        """Return the opacity slot represented by the selected panel style."""
        return "frost_opacity" if str(self._widgets.panel.currentData()) == "frost" else "opacity"

    def on_panel_style_changed(self) -> None:
        """Preserve separate opacity values while switching panel styles."""
        w = self._widgets
        w.panel_opacity.set_value(w.opacity_active_key, w.opacity.value() / 100.0)
        w.opacity_active_key = self.opacity_key()
        w.opacity.setValue(round(w.panel_opacity.value_for(w.opacity_active_key) * 100))

    def on_accent_activated(self, index: int) -> None:
        """Open the custom color picker when its combo entry is activated."""
        w = self._widgets
        if w.accent.itemData(index) is not None:
            w.accent_last_index = index
            return
        chosen = QColorDialog.getColor(
            QColor(self._config.accent_start),
            self._dialog,
            self._translator.text("set.accent"),
        )
        if not chosen.isValid():
            w.accent.setCurrentIndex(w.accent_last_index)
            return
        self.set_custom_accent((chosen.name(), chosen.lighter(140).name(), chosen.lighter(120).name()))
        w.accent_last_index = w.accent.currentIndex()

    def on_font_family_changed(self, font: QFont) -> None:
        """Refresh the style picker after a family selection."""
        self.rebuild_style_options(font.family())

    def on_font_style_changed(self, _style: str) -> None:
        """Remember an explicit style selection separately from list rebuilding."""
        self._widgets.font_style_user_changed = True

    def emit_clear_cache(self, _checked: bool = False) -> None:
        """Forward the clear-cache action through the source-page owner."""
        self._sources.emit_clear_cache(_checked)

    def keep_one_source_checked(self, _item: QListWidgetItem | None = None) -> None:
        """Ensure the staged configuration has one enabled source."""
        self._sources.keep_one_source_checked(_item)

    def selected_sources(self) -> list[str]:
        """Return checked source identifiers in their current list order."""
        return self._sources.selected_sources()

    def selected_display_sources(self) -> list[str]:
        """Return checked display source identifiers in their current list order."""
        return self._sources.selected_display_sources()

    def chosen_font_family(self) -> str:
        """Preserve an untouched configured fallback chain when applying settings."""
        w = self._widgets
        selected = w.font_family.currentFont().family()
        return w.font_family_configured if selected == w.font_family_shown else selected

    def chosen_font_style(self) -> str:
        """Preserve an untouched style when the platform normalizes its font list."""
        w = self._widgets
        selected_family = w.font_family.currentFont().family()
        selected_style = w.font_style.currentText()
        if selected_family == w.font_family_shown and not w.font_style_user_changed:
            return w.font_style_configured
        return selected_style

    def rebuild_style_options(self, family: str, prefer: str | None = None) -> None:
        """Repopulate styles and retain the current choice where possible."""
        font_style = self._widgets.font_style
        target = prefer if prefer is not None else font_style.currentText()
        styles = available_font_styles(family)
        font_style.blockSignals(True)
        font_style.clear()
        font_style.addItems(styles)
        index = font_style.findText(target)
        font_style.setCurrentIndex(index if index >= 0 else 0)
        font_style.blockSignals(False)

    def _form_page(self) -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        page.setObjectName("settingsPage")
        page.setAutoFillBackground(False)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(0)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(18)  # a settings page is read a row at a time
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        outer.addLayout(form)
        outer.addStretch(1)
        return page, form

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _configure_spin(spin: QSpinBox, low: int, high: int, value: int, suffix: str) -> None:
        """Apply one numeric control's range, value, and display suffix."""
        spin.setRange(low, high)
        spin.setValue(value)
        if suffix:
            spin.setSuffix(suffix)

__all__ = ["SettingsPageBuilder"]
