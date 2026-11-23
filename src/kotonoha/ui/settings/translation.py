"""Lyrics API translation section builder for the Lyrics settings page."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...config import DEFAULT_TRANSLATION_PROMPT, Config, TranslationPolicy, TranslationProvider
from ...i18n import TRANSLATION_LANGUAGES
from ...strings import Translator
from ...translation.presets import OPENAI_PRESETS, match_preset_id, preset_by_id
from .controls import SettingsWidgets

if TYPE_CHECKING:
    from .dialog import SettingsDialog


class SettingsTranslationSectionBuilder:
    """Own lyrics translation controls and progressive row visibility."""

    def __init__(
        self,
        dialog: SettingsDialog,
        widgets: SettingsWidgets,
        *,
        on_clear_translation_key: Callable[[], None],
        on_manage_translation_cache: Callable[[], None],
        on_clear_translation_cache: Callable[[], None],
        translator: Translator,
    ) -> None:
        self._dialog = dialog
        self._widgets = widgets
        self._on_clear_translation_key = on_clear_translation_key
        self._on_manage_translation_cache = on_manage_translation_cache
        self._on_clear_translation_cache = on_clear_translation_cache
        self._translator = translator
        self._form: QFormLayout | None = None
        self._actions_row: QWidget | None = None
        self._connect_signals()

    def _connect_signals(self) -> None:
        """Connect translation controls once so page resets never duplicate callbacks."""
        w = self._widgets
        w.translation.toggled.connect(self.on_show_translation_toggled)
        w.translation_policy.currentIndexChanged.connect(self.on_policy_changed)
        w.translation_provider.currentIndexChanged.connect(self.on_provider_changed)
        w.translation_preset.currentIndexChanged.connect(self.on_preset_changed)
        w.clear_translation_key.clicked.connect(self.emit_clear_translation_key)
        w.manage_translation_cache.clicked.connect(self.emit_manage_translation_cache)
        w.clear_translation_cache.clicked.connect(self.emit_clear_translation_cache)

    @property
    def _config(self) -> Config:
        return self._dialog.staged_config

    def build_into(self, form: QFormLayout) -> None:
        """Populate and append the lyrics translation controls to ``form``."""
        t = self._translator.text
        w = self._widgets
        self._form = form

        w.translation_policy.blockSignals(True)
        w.translation_policy.clear()
        self._configure_shrinking_combo(w.translation_policy)
        for value, key in (
            (TranslationPolicy.OFF.value, "transpolicy.off"),
            (TranslationPolicy.MISSING_ONLY.value, "transpolicy.missing"),
            (TranslationPolicy.REPLACE.value, "transpolicy.replace"),
        ):
            w.translation_policy.addItem(t(key), value)
        policy_idx = w.translation_policy.findData(self._config.translation_policy.value)
        w.translation_policy.setCurrentIndex(policy_idx if policy_idx >= 0 else 0)
        w.translation_policy.blockSignals(False)
        form.addRow(t("set.translation_policy"), w.translation_policy)

        w.translation_language.blockSignals(True)
        w.translation_language.clear()
        self._configure_shrinking_combo(w.translation_language)
        for value, label in TRANSLATION_LANGUAGES:
            display = t("set.translation_language_auto") if value == "auto" else label
            w.translation_language.addItem(display, value)
        configured_lang = self._config.translation_language
        lang_idx = w.translation_language.findData(configured_lang)
        if lang_idx < 0 and configured_lang:
            w.translation_language.addItem(configured_lang, configured_lang)
            lang_idx = w.translation_language.count() - 1
        w.translation_language.setCurrentIndex(lang_idx if lang_idx >= 0 else 0)
        w.translation_language.blockSignals(False)
        form.addRow(t("set.translation_language"), w.translation_language)

        w.translation_provider.blockSignals(True)
        w.translation_provider.clear()
        self._configure_shrinking_combo(w.translation_provider)
        for value, key in (
            (TranslationProvider.OPENAI_COMPATIBLE.value, "transprovider.openai"),
            (TranslationProvider.DEEPL.value, "transprovider.deepl"),
        ):
            w.translation_provider.addItem(t(key), value)
        provider_idx = w.translation_provider.findData(self._config.translation_provider.value)
        w.translation_provider.setCurrentIndex(provider_idx if provider_idx >= 0 else 0)
        w.translation_provider.blockSignals(False)
        form.addRow(t("set.translation_provider"), w.translation_provider)

        w.translation_preset.blockSignals(True)
        w.translation_preset.clear()
        self._configure_shrinking_combo(w.translation_preset)
        for preset in OPENAI_PRESETS:
            w.translation_preset.addItem(t(f"transpreset.{preset.preset_id}"), preset.preset_id)
        preset_id = match_preset_id(self._config.translation_base_url)
        preset_idx = w.translation_preset.findData(preset_id)
        w.translation_preset.setCurrentIndex(preset_idx if preset_idx >= 0 else 0)
        w.translation_preset.blockSignals(False)
        form.addRow(t("set.translation_preset"), w.translation_preset)

        w.translation_base_url.setText(self._config.translation_base_url)
        w.translation_base_url.setClearButtonEnabled(True)
        form.addRow(t("set.translation_base_url"), w.translation_base_url)

        w.translation_model.setText(self._config.translation_model)
        w.translation_model.setClearButtonEnabled(True)
        form.addRow(t("set.translation_model"), w.translation_model)

        w.translation_prompt.setPlainText(self._config.translation_prompt)
        w.translation_prompt.setPlaceholderText(DEFAULT_TRANSLATION_PROMPT)
        w.translation_prompt.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        w.translation_prompt.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w.translation_prompt.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        w.translation_prompt.setFixedHeight(108)
        form.addRow(t("set.translation_prompt"), w.translation_prompt)

        w.translation_prompt_hint.setObjectName("hint")
        w.translation_prompt_hint.setWordWrap(True)
        w.translation_prompt_hint.setText(t("set.translation_prompt_hint"))
        form.addRow("", w.translation_prompt_hint)

        w.translation_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        w.translation_api_key.setClearButtonEnabled(True)
        w.translation_api_key.setText("")
        form.addRow(t("set.translation_api_key"), w.translation_api_key)

        w.translation_key_status.setObjectName("hint")
        w.translation_key_status.setWordWrap(True)
        form.addRow("", w.translation_key_status)

        actions_row = QWidget()
        actions_layout = QVBoxLayout(actions_row)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        w.clear_translation_key.setText(t("btn.clear_translation_key"))
        w.manage_translation_cache.setText(t("btn.manage_translation_cache"))
        w.clear_translation_cache.setText(t("btn.clear_translation_cache"))
        actions_layout.addWidget(w.clear_translation_key)
        actions_layout.addWidget(w.manage_translation_cache)
        actions_layout.addWidget(w.clear_translation_cache)
        form.addRow("", actions_row)
        self._actions_row = actions_row

        self.refresh_secret_status()

    @staticmethod
    def _configure_shrinking_combo(combo: QComboBox) -> None:
        """Let long combo labels elide instead of widening the whole form page."""
        combo.setMinimumContentsLength(10)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def on_show_translation_toggled(self, _checked: bool = False) -> None:
        """Show or hide translation settings when the display toggle changes."""
        del _checked
        self.update_controls_visibility()

    def on_policy_changed(self, _index: int = -1) -> None:
        """Show or hide service settings when online translation policy changes."""
        del _index
        self.update_controls_visibility()

    def on_provider_changed(self, _index: int = -1) -> None:
        """Refresh keyring status and provider-specific rows when service changes."""
        del _index
        self.refresh_secret_status()

    def on_preset_changed(self, _index: int = -1) -> None:
        """Fill base URL and default model when the user picks a built-in preset."""
        del _index
        preset_id = str(self._widgets.translation_preset.currentData() or "")
        preset = preset_by_id(preset_id)
        if preset is not None and preset.base_url:
            self._widgets.translation_base_url.setText(preset.base_url)
            if preset.default_model:
                self._widgets.translation_model.setText(preset.default_model)
        self.refresh_secret_status()

    def refresh_secret_status(self) -> None:
        """Update API key placeholder, provider-specific hint, and row visibility."""
        t = self._translator.text
        w = self._widgets
        secrets = self._dialog.translation_secrets
        provider = self._selected_provider()
        needs_key = self._needs_api_key()
        has_saved = secrets.has_key(provider)

        if not needs_key:
            w.translation_key_status.setText(t("set.translation_key.ollama"))
        elif not secrets.available:
            reason = secrets.reason or "unavailable"
            w.translation_api_key.setPlaceholderText(t("set.translation_api_key.placeholder"))
            w.translation_key_status.setText(t("set.translation_key.unavailable").format(reason=reason))
        elif has_saved:
            w.translation_api_key.setPlaceholderText(t("set.translation_api_key.saved_placeholder"))
            w.translation_key_status.setText(t("set.translation_key.saved"))
        else:
            w.translation_api_key.setPlaceholderText(t("set.translation_api_key.placeholder"))
            hint_key = (
                "set.translation_key.not_saved.deepl"
                if provider == TranslationProvider.DEEPL.value
                else "set.translation_key.not_saved.openai"
            )
            w.translation_key_status.setText(t(hint_key))
        self.update_controls_visibility()

    def update_controls_visibility(self) -> None:
        """Show only rows belonging to the active policy, service, and preset."""
        w = self._widgets
        show_translation = w.translation.isChecked()
        enabled = show_translation and str(w.translation_policy.currentData()) != TranslationPolicy.OFF.value
        provider = self._selected_provider()
        is_openai = provider == TranslationProvider.OPENAI_COMPATIBLE.value
        needs_key = self._needs_api_key()
        secrets = self._dialog.translation_secrets

        show_openai = enabled and is_openai
        show_api_key = enabled and needs_key

        form = self._form
        if form is not None:
            form.setRowVisible(w.translation_policy, show_translation)
            form.setRowVisible(w.translation_language, enabled)
            form.setRowVisible(w.translation_provider, enabled)
            form.setRowVisible(w.translation_preset, show_openai)
            form.setRowVisible(w.translation_base_url, show_openai)
            form.setRowVisible(w.translation_model, show_openai)
            form.setRowVisible(w.translation_prompt, show_openai)
            form.setRowVisible(w.translation_prompt_hint, show_openai)
            form.setRowVisible(w.translation_api_key, show_api_key)
            form.setRowVisible(w.translation_key_status, enabled)
            if self._actions_row is not None:
                form.setRowVisible(self._actions_row, enabled)

        w.translation_api_key.setEnabled(show_api_key and secrets.available)
        can_clear_key = show_api_key and secrets.available and secrets.has_key(provider)
        w.clear_translation_key.setVisible(can_clear_key)
        w.clear_translation_key.setEnabled(can_clear_key)

    def _selected_provider(self) -> str:
        """Return the currently selected translation provider identifier."""
        return str(self._widgets.translation_provider.currentData() or TranslationProvider.OPENAI_COMPATIBLE.value)

    def _needs_api_key(self) -> bool:
        """Return whether the currently selected provider/preset uses an API key."""
        if self._selected_provider() != TranslationProvider.OPENAI_COMPATIBLE.value:
            return True
        preset_id = str(self._widgets.translation_preset.currentData() or "")
        preset = preset_by_id(preset_id)
        return True if preset is None else preset.requires_api_key

    def emit_clear_translation_key(self, _checked: bool = False) -> None:
        """Forward the delete-saved-key action through the dialog owner."""
        del _checked
        self._on_clear_translation_key()

    def emit_manage_translation_cache(self, _checked: bool = False) -> None:
        """Open the standalone translation-cache window through the dialog owner."""
        del _checked
        self._on_manage_translation_cache()

    def emit_clear_translation_cache(self, _checked: bool = False) -> None:
        """Forward the clear-translation-cache action through the dialog owner."""
        del _checked
        self._on_clear_translation_cache()


__all__ = ["SettingsTranslationSectionBuilder"]
