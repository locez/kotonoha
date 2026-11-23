"""Lyrics API translation section builder for the Lyrics settings page."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...config import (
    DEFAULT_TRANSLATION_PROMPT,
    Config,
    TranslationPolicy,
    TranslationProvider,
    TranslationServiceConfig,
)
from ...i18n import TRANSLATION_LANGUAGES
from ...strings import Translator
from ...translation.presets import is_loopback_url, match_preset_id, preset_by_id
from .controls import SettingsWidgets
from .translation_service_dialog import TranslationServiceDialog

if TYPE_CHECKING:
    from .dialog import SettingsDialog


class SettingsTranslationSectionBuilder:
    """Own prioritized translation services list, per-service key staging, and row visibility."""

    def __init__(
        self,
        dialog: SettingsDialog,
        widgets: SettingsWidgets,
        *,
        on_manage_translation_cache: Callable[[], None],
        on_clear_translation_cache: Callable[[], None],
        translator: Translator,
    ) -> None:
        self._dialog = dialog
        self._widgets = widgets
        self._on_manage_translation_cache = on_manage_translation_cache
        self._on_clear_translation_cache = on_clear_translation_cache
        self._translator = translator
        self._form: QFormLayout | None = None
        self._services_panel: QWidget | None = None
        self._actions_row: QWidget | None = None
        self._editor_dialog: TranslationServiceDialog | None = None
        self._services_by_id: dict[str, TranslationServiceConfig] = {}
        self._pending_key_saves: dict[str, str] = {}
        self._pending_key_deletes: set[str] = set()
        self._connect_signals()

    def _connect_signals(self) -> None:
        """Connect translation controls once so page resets never duplicate callbacks."""
        w = self._widgets
        w.translation.toggled.connect(self._on_visibility_changed)
        w.translation_policy.currentIndexChanged.connect(self._on_visibility_changed)
        w.translation_services_list.currentRowChanged.connect(self._update_service_buttons)
        w.translation_services_list.itemChanged.connect(self._on_service_item_changed)
        w.translation_services_list.itemDoubleClicked.connect(self._edit_clicked_item)
        w.add_translation_service.clicked.connect(self.open_add_service_dialog)
        w.edit_translation_service.clicked.connect(self.open_edit_service_dialog)
        w.remove_translation_service.clicked.connect(self.remove_selected_service)
        w.manage_translation_cache.clicked.connect(self._emit_manage_translation_cache)
        w.clear_translation_cache.clicked.connect(self._emit_clear_translation_cache)

    @property
    def _config(self) -> Config:
        return self._dialog.staged_config

    def build_into(self, form: QFormLayout) -> None:
        """Populate and append the lyrics translation controls to ``form``."""
        t = self._translator.text
        w = self._widgets
        self._form = form
        self.close_editor()
        self._pending_key_saves.clear()
        self._pending_key_deletes.clear()

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

        services_panel = QWidget()
        services_layout = QVBoxLayout(services_panel)
        services_layout.setContentsMargins(0, 0, 0, 0)
        services_layout.setSpacing(6)

        w.translation_services_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        w.translation_services_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        w.translation_services_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        w.translation_services_list.setFixedHeight(124)
        self._populate_services_list(self._config.translation_services)
        services_layout.addWidget(w.translation_services_list)

        w.add_translation_service.setText(t("btn.add_translation_service"))
        w.edit_translation_service.setText(t("btn.edit_translation_service"))
        w.remove_translation_service.setText(t("btn.remove_translation_service"))
        services_layout.addLayout(
            self._button_row(w.add_translation_service, w.edit_translation_service, w.remove_translation_service)
        )

        self._configure_hint(w.translation_services_hint, t("set.translation_services_hint"))
        services_layout.addWidget(w.translation_services_hint)
        form.addRow(t("set.translation_services"), services_panel)
        self._services_panel = services_panel

        w.translation_prompt.setPlainText(self._config.translation_prompt)
        w.translation_prompt.setPlaceholderText(DEFAULT_TRANSLATION_PROMPT)
        w.translation_prompt.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        w.translation_prompt.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w.translation_prompt.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        w.translation_prompt.setFixedHeight(108)
        form.addRow(t("set.translation_prompt"), w.translation_prompt)

        self._configure_hint(w.translation_prompt_hint, t("set.translation_prompt_hint"))
        form.addRow("", w.translation_prompt_hint)

        self._configure_hint(w.translation_key_status, "")
        form.addRow("", w.translation_key_status)

        actions_row = QWidget()
        actions_layout = QVBoxLayout(actions_row)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        w.manage_translation_cache.setText(t("btn.manage_translation_cache"))
        w.clear_translation_cache.setText(t("btn.clear_translation_cache"))
        actions_layout.addWidget(w.manage_translation_cache)
        actions_layout.addWidget(w.clear_translation_cache)
        form.addRow("", actions_row)
        self._actions_row = actions_row

        self.refresh_secret_status()

    def current_services(self) -> list[TranslationServiceConfig]:
        """Read the prioritized service list directly from the QListWidget order."""
        list_widget = self._widgets.translation_services_list
        services: list[TranslationServiceConfig] = []
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            base = self._services_by_id.get(self._item_service_id(item))
            if item is not None and base is not None:
                services.append(replace(base, enabled=item.checkState() == Qt.CheckState.Checked))
        return services

    def take_pending_secret_changes(self) -> tuple[dict[str, str], frozenset[str]]:
        """Consume staged per-service API key saves and deletions on Settings Apply."""
        saves = dict(self._pending_key_saves)
        deletes = frozenset(self._pending_key_deletes)
        self._pending_key_saves.clear()
        self._pending_key_deletes.clear()
        return saves, deletes

    def retheme_editor(self, config: Config) -> None:
        """Propagate theme changes to an open service editor dialog."""
        if self._editor_dialog is not None:
            self._editor_dialog.retheme(config)

    def close_editor(self) -> None:
        """Close any open child service editor when Settings closes."""
        editor = self._editor_dialog
        self._editor_dialog = None
        if editor is not None:
            editor.close()

    def open_add_service_dialog(self, _checked: bool = False) -> None:
        """Open the non-blocking service editor to add a new prioritized entry."""
        del _checked
        self._open_service_editor(None)

    def open_edit_service_dialog(self, _checked: bool = False) -> None:
        """Open the non-blocking service editor for the currently selected row."""
        del _checked
        service = self._selected_service()
        if service is not None:
            self._open_service_editor(service)

    def remove_selected_service(self, _checked: bool = False) -> None:
        """Remove the currently selected translation service from the priority list."""
        del _checked
        list_widget = self._widgets.translation_services_list
        row = list_widget.currentRow()
        if row < 0 or list_widget.count() <= 1:
            return
        item = list_widget.takeItem(row)
        if item is not None:
            service_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
            self._services_by_id.pop(service_id, None)
            self._pending_key_saves.pop(service_id, None)
            if self._dialog.translation_secrets.has_key(service_id):
                self._pending_key_deletes.add(service_id)
        next_row = min(row, list_widget.count() - 1)
        if next_row >= 0:
            list_widget.setCurrentRow(next_row)
        self.update_controls_visibility()

    def _on_visibility_changed(self, _value: object = None) -> None:
        del _value
        self.update_controls_visibility()

    def refresh_secret_status(self) -> None:
        """Refresh list row key badges, keyring warning, and control visibility."""
        t = self._translator.text
        w = self._widgets
        secrets = self._dialog.translation_secrets
        w.translation_key_status.setText(
            ""
            if secrets.available
            else t("set.translation_key.unavailable").format(reason=secrets.reason or "unavailable")
        )
        list_widget = w.translation_services_list
        blocked = list_widget.blockSignals(True)
        try:
            for index in range(list_widget.count()):
                item = list_widget.item(index)
                service = self._services_by_id.get(self._item_service_id(item))
                if item is not None and service is not None:
                    item.setText(self._format_service_row(service))
        finally:
            list_widget.blockSignals(blocked)
        self.update_controls_visibility()

    def update_controls_visibility(self) -> None:
        """Show only rows belonging to the active display toggle and policy."""
        w = self._widgets
        show_translation = w.translation.isChecked()
        enabled = show_translation and str(w.translation_policy.currentData()) != TranslationPolicy.OFF.value
        has_openai = any(
            service.provider is TranslationProvider.OPENAI_COMPATIBLE
            for service in self._services_by_id.values()
        )
        show_prompt = enabled and has_openai
        show_keyring_warning = enabled and not self._dialog.translation_secrets.available

        form = self._form
        if form is not None:
            form.setRowVisible(w.translation_policy, show_translation)
            form.setRowVisible(w.translation_language, enabled)
            if self._services_panel is not None:
                form.setRowVisible(self._services_panel, enabled)
            form.setRowVisible(w.translation_prompt, show_prompt)
            form.setRowVisible(w.translation_prompt_hint, show_prompt)
            form.setRowVisible(w.translation_key_status, show_keyring_warning)
            if self._actions_row is not None:
                form.setRowVisible(self._actions_row, enabled)
        self._update_service_buttons()

    def _emit_manage_translation_cache(self, _checked: bool = False) -> None:
        del _checked
        self._on_manage_translation_cache()

    def _emit_clear_translation_cache(self, _checked: bool = False) -> None:
        del _checked
        self._on_clear_translation_cache()

    def _populate_services_list(self, services: list[TranslationServiceConfig]) -> None:
        list_widget = self._widgets.translation_services_list
        blocked = list_widget.blockSignals(True)
        try:
            list_widget.clear()
            self._services_by_id.clear()
            for service in services:
                self._services_by_id[service.id] = service
                list_widget.addItem(self._make_service_item(service))
            if list_widget.count() > 0:
                list_widget.setCurrentRow(0)
        finally:
            list_widget.blockSignals(blocked)

    def _make_service_item(self, service: TranslationServiceConfig) -> QListWidgetItem:
        item = QListWidgetItem(self._format_service_row(service))
        item.setData(Qt.ItemDataRole.UserRole, service.id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if service.enabled else Qt.CheckState.Unchecked)
        return item

    def _format_service_row(self, service: TranslationServiceConfig) -> str:
        parts = [service.name]
        if service.provider is TranslationProvider.OPENAI_COMPATIBLE and service.model:
            parts.append(service.model)
        parts.append(self._key_badge_for(service))
        return " · ".join(parts)

    def _key_badge_for(self, service: TranslationServiceConfig) -> str:
        t = self._translator.text
        if service.id in self._pending_key_saves:
            return t("tservice.badge.key_pending")
        if service.id not in self._pending_key_deletes and self._dialog.translation_secrets.has_key(service.id):
            return t("tservice.badge.key_saved")
        if not self._service_needs_key(service):
            return t("tservice.badge.key_not_needed")
        return t("tservice.badge.key_missing")

    @staticmethod
    def _service_needs_key(service: TranslationServiceConfig) -> bool:
        if service.provider is TranslationProvider.DEEPL:
            return True
        preset = preset_by_id(match_preset_id(service.base_url))
        if preset is not None and not preset.requires_api_key:
            return False
        return not is_loopback_url(service.base_url)

    @staticmethod
    def _item_service_id(item: QListWidgetItem | None) -> str:
        return "" if item is None else str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _selected_service(self) -> TranslationServiceConfig | None:
        return self._services_by_id.get(self._item_service_id(self._widgets.translation_services_list.currentItem()))

    def _edit_clicked_item(self, item: QListWidgetItem) -> None:
        service = self._services_by_id.get(self._item_service_id(item))
        if service is not None:
            self._open_service_editor(service)

    def _open_service_editor(self, service: TranslationServiceConfig | None) -> None:
        self.close_editor()
        secrets = self._dialog.translation_secrets
        has_saved = (
            service is not None
            and service.id not in self._pending_key_deletes
            and secrets.has_key(service.id)
        )
        pending_key = self._pending_key_saves.get(service.id, "") if service is not None else ""
        editor = TranslationServiceDialog(
            self._config,
            service=service,
            existing_ids=tuple(self._services_by_id),
            keyring_available=secrets.available,
            keyring_reason=secrets.reason,
            has_saved_key=has_saved,
            pending_key=pending_key,
            parent=self._dialog,
            translator=self._translator,
        )
        editor.saved.connect(self._handle_service_saved)
        editor.finished.connect(self._clear_editor)
        self._editor_dialog = editor
        editor.show()

    def _handle_service_saved(self, service: object, entered_key: str, delete_key: bool) -> None:
        if not isinstance(service, TranslationServiceConfig):
            return
        existed = service.id in self._services_by_id
        self._services_by_id[service.id] = service
        if entered_key:
            self._pending_key_saves[service.id] = entered_key
            self._pending_key_deletes.discard(service.id)
        elif delete_key:
            self._pending_key_saves.pop(service.id, None)
            self._pending_key_deletes.add(service.id)

        list_widget = self._widgets.translation_services_list
        blocked = list_widget.blockSignals(True)
        try:
            if existed:
                for index in range(list_widget.count()):
                    item = list_widget.item(index)
                    if item is not None and self._item_service_id(item) == service.id:
                        item.setText(self._format_service_row(service))
                        break
            else:
                item = self._make_service_item(service)
                list_widget.addItem(item)
                list_widget.setCurrentItem(item)
        finally:
            list_widget.blockSignals(blocked)
        self.update_controls_visibility()

    def _clear_editor(self, _result: int | None = None) -> None:
        del _result
        editor = self._editor_dialog
        self._editor_dialog = None
        if editor is not None:
            editor.deleteLater()

    def _on_service_item_changed(self, item: QListWidgetItem) -> None:
        service_id = self._item_service_id(item)
        base = self._services_by_id.get(service_id)
        if base is not None:
            enabled = item.checkState() == Qt.CheckState.Checked
            if base.enabled != enabled:
                self._services_by_id[service_id] = replace(base, enabled=enabled)

    def _update_service_buttons(self, _row: int = -1) -> None:
        del _row
        w = self._widgets
        list_widget = w.translation_services_list
        row = list_widget.currentRow()
        count = list_widget.count()
        has_selection = 0 <= row < count
        w.edit_translation_service.setEnabled(has_selection)
        w.remove_translation_service.setEnabled(has_selection and count > 1)

    @staticmethod
    def _button_row(*buttons: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for button in buttons:
            row.addWidget(button, 1)
        return row

    @staticmethod
    def _configure_hint(label: QLabel, text: str) -> None:
        label.setObjectName("hint")
        label.setWordWrap(True)
        if text:
            label.setText(text)

    @staticmethod
    def _configure_shrinking_combo(combo: QComboBox) -> None:
        """Let long combo labels elide instead of widening the whole form page."""
        combo.setMinimumContentsLength(10)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


__all__ = ["SettingsTranslationSectionBuilder"]
