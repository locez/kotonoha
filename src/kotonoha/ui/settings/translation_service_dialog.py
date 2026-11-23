"""Non-blocking editor dialog for adding or editing one translation service."""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...config import Config, TranslationProvider, TranslationServiceConfig
from ...config.translation import next_unique_service_id
from ...platform import OverlayPlatformFactory
from ...strings import Translator
from ...translation.models import TranslationError
from ...translation.presets import OPENAI_PRESETS, match_preset_id, preset_by_id, validate_base_url
from . import theme
from .surface import SettingsTitleBar, ThemedSettingsDialog
from .widgets import SettingsComboBox

_DEEPL_PRESET_ID = "deepl"


class TranslationServiceDialog(ThemedSettingsDialog):
    """Configure one prioritized translation service and its per-service API key."""

    # Emits (TranslationServiceConfig, entered_api_key, delete_saved_key)
    saved = pyqtSignal(object, str, bool)

    def __init__(
        self,
        config: Config,
        *,
        service: TranslationServiceConfig | None,
        existing_ids: Sequence[str],
        keyring_available: bool,
        keyring_reason: str | None,
        has_saved_key: bool,
        pending_key: str = "",
        parent: QWidget | None = None,
        translator: Translator | None = None,
        platform_factory: OverlayPlatformFactory | None = None,
    ) -> None:
        super().__init__(config, parent, platform_factory=platform_factory)
        self._translator = translator if translator is not None else Translator(config.ui_language)
        self._editing = service
        self._existing_ids = tuple(existing_ids)
        self._keyring_available = keyring_available
        self._keyring_reason = keyring_reason
        self._has_saved_key = has_saved_key
        self._delete_key = False
        self._logo_badge: QLabel = QLabel()

        t = self._translator.text
        title_text = t("tservice.edit_title") if service is not None else t("tservice.add_title")
        self.setObjectName("translationServiceDialog")
        self.setWindowTitle(title_text)
        self.setMinimumSize(480, 320)
        self.resize(540, 390)
        self._apply_surface_style()
        self._mark_surface_style_ready()

        self._preset = SettingsComboBox()
        self._preset.setMinimumContentsLength(10)
        self._preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._preset.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._populate_presets()

        self._name = QLineEdit()
        self._name.setPlaceholderText(t("tservice.name_placeholder"))
        self._name.setClearButtonEnabled(True)

        self._base_url = QLineEdit()
        self._base_url.setClearButtonEnabled(True)

        self._model = QLineEdit()
        self._model.setClearButtonEnabled(True)

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setClearButtonEnabled(True)
        if pending_key:
            self._api_key.setText(pending_key)

        self._key_status = QLabel()
        self._key_status.setObjectName("hint")
        self._key_status.setWordWrap(True)

        self._remove_key_button = QPushButton(t("btn.clear_translation_key"))
        self._remove_key_button.clicked.connect(self._mark_delete_key)

        self._error = QLabel()
        self._error.setObjectName("serviceError")
        self._error.setWordWrap(True)
        self._error.setVisible(False)

        self._form = QFormLayout()
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setHorizontalSpacing(14)
        self._form.setVerticalSpacing(10)
        self._form.addRow(t("set.translation_preset"), self._preset)
        self._form.addRow(t("tservice.name"), self._name)
        self._form.addRow(t("set.translation_base_url"), self._base_url)
        self._form.addRow(t("set.translation_model"), self._model)
        self._form.addRow(t("set.translation_api_key"), self._api_key)
        self._form.addRow("", self._key_status)
        self._form.addRow("", self._remove_key_button)

        save_button = QPushButton(t("btn.save"))
        save_button.clicked.connect(self._on_save)
        cancel_button = QPushButton(t("btn.cancel"))
        cancel_button.clicked.connect(self.close)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        footer.addWidget(cancel_button)
        footer.addWidget(save_button)

        header_line = QWidget()
        header_line.setObjectName("navDivider")
        header_line.setFixedHeight(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(self._title_bar(title_text))
        layout.addWidget(header_line)
        layout.addLayout(self._form)
        layout.addWidget(self._error)
        layout.addStretch(1)
        layout.addLayout(footer)

        self._load_initial_values()
        self._preset.currentIndexChanged.connect(self._on_preset_changed)
        self._update_visibility()

    def _populate_presets(self) -> None:
        t = self._translator.text
        for preset in OPENAI_PRESETS:
            if preset.preset_id == "custom":
                self._preset.addItem(t("transprovider.deepl"), _DEEPL_PRESET_ID)
            self._preset.addItem(t(f"transpreset.{preset.preset_id}"), preset.preset_id)

    def _load_initial_values(self) -> None:
        service = self._editing
        if service is None:
            idx = self._preset.findData("deepseek")
            self._preset.setCurrentIndex(idx if idx >= 0 else 0)
            self._apply_preset_defaults(str(self._preset.currentData() or "gemini"))
            return

        if service.provider is TranslationProvider.DEEPL:
            preset_id = _DEEPL_PRESET_ID
        else:
            preset_id = match_preset_id(service.base_url)
        idx = self._preset.findData(preset_id)
        self._preset.setCurrentIndex(idx if idx >= 0 else 0)
        self._name.setText(service.name)
        self._base_url.setText(service.base_url)
        self._model.setText(service.model)

    def _on_preset_changed(self, _index: int = -1) -> None:
        del _index
        self._error.setVisible(False)
        preset_id = str(self._preset.currentData() or "custom")
        self._apply_preset_defaults(preset_id)
        self._update_visibility()

    def _apply_preset_defaults(self, preset_id: str) -> None:
        t = self._translator.text
        if preset_id == _DEEPL_PRESET_ID:
            if self._editing is None or not self._name.text().strip():
                self._name.setText("DeepL API")
            self._base_url.setText("")
            self._model.setText("")
            return
        preset = preset_by_id(preset_id)
        if preset is None:
            return
        if self._editing is None or not self._name.text().strip():
            self._name.setText(t(f"transpreset.{preset.preset_id}"))
        if preset.base_url:
            self._base_url.setText(preset.base_url)
        elif self._editing is None:
            self._base_url.setText("")
        if preset.default_model:
            self._model.setText(preset.default_model)
        elif self._editing is None:
            self._model.setText("")

    def _needs_api_key(self) -> bool:
        preset_id = str(self._preset.currentData() or "custom")
        if preset_id == _DEEPL_PRESET_ID:
            return True
        preset = preset_by_id(preset_id)
        return True if preset is None else preset.requires_api_key

    def _update_visibility(self) -> None:
        t = self._translator.text
        preset_id = str(self._preset.currentData() or "custom")
        is_deepl = preset_id == _DEEPL_PRESET_ID
        needs_key = self._needs_api_key()
        key_saved = self._has_saved_key and not self._delete_key

        self._form.setRowVisible(self._base_url, not is_deepl)
        self._form.setRowVisible(self._model, not is_deepl)
        self._form.setRowVisible(self._api_key, needs_key)

        if not needs_key:
            self._key_status.setText(t("set.translation_key.ollama"))
        elif not self._keyring_available:
            reason = self._keyring_reason or "unavailable"
            self._api_key.setPlaceholderText(t("set.translation_api_key.placeholder"))
            self._key_status.setText(t("set.translation_key.unavailable").format(reason=reason))
        elif key_saved:
            self._api_key.setPlaceholderText(t("set.translation_api_key.saved_placeholder"))
            self._key_status.setText(t("set.translation_key.saved"))
        else:
            self._api_key.setPlaceholderText(t("set.translation_api_key.placeholder"))
            hint_key = "set.translation_key.not_saved.deepl" if is_deepl else "set.translation_key.not_saved.openai"
            self._key_status.setText(t(hint_key))

        self._api_key.setEnabled(needs_key and self._keyring_available)
        can_remove = needs_key and self._keyring_available and key_saved
        self._form.setRowVisible(self._remove_key_button, can_remove)
        self._remove_key_button.setEnabled(can_remove)

    def _mark_delete_key(self, _checked: bool = False) -> None:
        del _checked
        self._delete_key = True
        self._api_key.clear()
        self._update_visibility()

    def _on_save(self, _checked: bool = False) -> None:
        del _checked
        t = self._translator.text
        preset_id = str(self._preset.currentData() or "custom")
        is_deepl = preset_id == _DEEPL_PRESET_ID
        provider = TranslationProvider.DEEPL if is_deepl else TranslationProvider.OPENAI_COMPATIBLE

        base_url = ""
        model = ""
        if not is_deepl:
            try:
                base_url = validate_base_url(self._base_url.text())
            except TranslationError as exc:
                self._show_error(str(exc))
                return
            model = self._model.text().strip()
            if not model:
                self._show_error(t("tservice.error.missing_model"))
                return

        default_name = "DeepL API" if is_deepl else t(f"transpreset.{preset_id}")
        name = self._name.text().strip() or default_name
        if self._editing is not None:
            service_id = self._editing.id
            enabled = self._editing.enabled
        else:
            service_id = next_unique_service_id(preset_id, self._existing_ids)
            enabled = True

        result = TranslationServiceConfig(
            id=service_id,
            name=name,
            provider=provider,
            enabled=enabled,
            base_url=base_url,
            model=model,
        )
        entered_key = self._api_key.text().strip() if (self._needs_api_key() and self._keyring_available) else ""
        delete_key = self._delete_key and not entered_key
        self.saved.emit(result, entered_key, delete_key)
        self.close()

    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def _apply_surface_style(self) -> None:
        self.setStyleSheet(
            theme._skin(self._accent, self._theme, self._frosted, self._win_opacity)
            + "\nQDialog#translationServiceDialog { background: transparent; }\n"
            + "QLabel#serviceError { color: #E56B6F; }\n"
        )

    def _refresh_themed_icons(self) -> None:
        self._paint_leaf_badge(self._logo_badge)

    def _title_bar(self, title_text: str) -> QWidget:
        title_bar = SettingsTitleBar()
        bar = QHBoxLayout(title_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(9)
        logo_badge = self._logo_badge
        logo_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._paint_leaf_badge(logo_badge)
        bar.addWidget(logo_badge)
        title = QLabel(title_text)
        title.setObjectName("dialogTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        close_button = QPushButton("✕")
        close_button.setObjectName("closeButton")
        close_button.setFixedSize(26, 26)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.close)
        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(close_button)
        return title_bar


__all__ = ["TranslationServiceDialog"]
