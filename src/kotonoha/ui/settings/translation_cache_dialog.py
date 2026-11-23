"""Standalone translation-cache management dialog."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...app.intents import (
    ClearTranslationCache,
    DeleteTranslationCacheEntries,
    LoadTranslationCacheRecord,
    SearchTranslationCache,
    UpdateTranslationCacheEntry,
)
from ...config import Config
from ...i18n import translation_language_display_name
from ...platform import OverlayPlatformFactory
from ...strings import Translator
from ...translation import (
    TranslationCacheDeleteResult,
    TranslationCacheDeleteStatus,
    TranslationCacheEntry,
    TranslationCacheKey,
    TranslationCacheQuery,
    TranslationCacheRecord,
)
from . import theme
from .surface import SettingsTitleBar, ThemedSettingsDialog
from .translation_edit_dialog import TranslationEditDialog


class TranslationCacheTableModel(QAbstractTableModel):
    """Present persisted translation metadata while retaining exact keys."""

    def __init__(self, translator: Translator) -> None:
        super().__init__()
        self._translator = translator
        self._entries: tuple[TranslationCacheEntry, ...] = ()

    def set_entries(self, entries: tuple[TranslationCacheEntry, ...]) -> None:
        """Replace all visible rows with one completed search result."""
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._entries)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        del parent
        return 7

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                translation_language_display_name(entry.key.target_language),
                entry.title or "-",
                entry.artist or "-",
                entry.provider,
                entry.model,
                str(entry.line_count),
                _format_time(entry.last_accessed),
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{entry.key.target_language} · {entry.provider}/{entry.model} · {entry.key.content_hash[:12]}"
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if orientation is not Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        headers = (
            "tcache.column.language",
            "cache.column.title",
            "cache.column.artist",
            "cache.column.provider",
            "tcache.column.model",
            "tcache.column.lines",
            "cache.column.accessed",
        )
        return self._translator.text(headers[section]) if 0 <= section < len(headers) else None

    def entry_at(self, row: int) -> TranslationCacheEntry | None:
        return self._entries[row] if 0 <= row < len(self._entries) else None


class TranslationCacheDialog(ThemedSettingsDialog):
    """Search, inspect, and delete persisted API translation cache entries."""

    intent_requested = pyqtSignal(object)

    def __init__(
        self,
        config: Config,
        parent: QWidget | None = None,
        *,
        translator: Translator | None = None,
        platform_factory: OverlayPlatformFactory | None = None,
    ) -> None:
        super().__init__(config, parent, platform_factory=platform_factory)
        self._config_snapshot = config
        self._platform_factory = platform_factory
        self._translator = translator if translator is not None else Translator(config.ui_language)
        self._confirmation: QMessageBox | None = None
        self._editor: TranslationEditDialog | None = None
        self._pending_delete: tuple[TranslationCacheKey, ...] = ()
        self._logo_badge: QLabel = QLabel()
        self._busy = False

        self.setObjectName("translationCacheDialog")
        self.setWindowTitle(self._translator.text("tcache.title"))
        self.setMinimumSize(760, 460)
        self.resize(960, 580)
        self._apply_surface_style()
        self._mark_surface_style_ready()

        self._model = TranslationCacheTableModel(self._translator)
        self._keyword = QLineEdit()
        self._keyword.setPlaceholderText(self._translator.text("tcache.search_placeholder"))
        self._keyword.returnPressed.connect(self._request_search)
        self._search_button = QPushButton(self._translator.text("btn.search_cache"))
        self._search_button.setIcon(QIcon.fromTheme("system-search"))
        self._search_button.clicked.connect(self._request_search)

        self._table = QTableView()
        self._table.setObjectName("translationCacheTable")
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        table_viewport = self._table.viewport()
        if table_viewport is not None:
            table_viewport.setAutoFillBackground(False)
        vertical_header = self._table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)
        horizontal_header = self._table.horizontalHeader()
        if horizontal_header is not None:
            horizontal_header.setAutoFillBackground(False)
            header_viewport = horizontal_header.viewport()
            if header_viewport is not None:
                header_viewport.setAutoFillBackground(False)
            horizontal_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            horizontal_header.setStretchLastSection(False)
            horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            for section in (1, 2):
                horizontal_header.setSectionResizeMode(section, QHeaderView.ResizeMode.Stretch)
            for section in (3, 4, 5, 6):
                horizontal_header.setSectionResizeMode(section, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._table.doubleClicked.connect(self._request_edit_index)
        selection_model = self._table.selectionModel()
        if selection_model is None:
            raise RuntimeError("translation cache table selection model is unavailable")
        selection_model.selectionChanged.connect(self._update_action_state)

        self._status = QLabel(self._translator.text("cache.loading"))
        self._status.setObjectName("cacheStatus")
        self._edit_button = QPushButton(self._translator.text("btn.edit_translation"))
        self._edit_button.clicked.connect(self._request_edit_selected)
        self._delete_button = QPushButton(self._translator.text("btn.delete_cache"))
        widget_style = self.style()
        if widget_style is not None:
            self._delete_button.setIcon(widget_style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self._delete_button.setToolTip(self._translator.text("cache.delete_tooltip"))
        self._delete_button.clicked.connect(self._confirm_delete)
        self._clear_button = QPushButton(self._translator.text("btn.clear_translation_cache"))
        self._clear_button.clicked.connect(self._confirm_clear)
        close_button = QPushButton(self._translator.text("btn.close"))
        close_button.clicked.connect(self.close)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(self._keyword, 1)
        search_row.addWidget(self._search_button)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(self._status, 1)
        footer.addWidget(self._edit_button)
        footer.addWidget(self._delete_button)
        footer.addWidget(self._clear_button)
        footer.addWidget(close_button)

        subtitle = QLabel(self._translator.text("tcache.subtitle"))
        subtitle.setObjectName("hint")
        subtitle.setWordWrap(True)

        header_line = QWidget()
        header_line.setObjectName("navDivider")
        header_line.setFixedHeight(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(self._title_bar())
        layout.addWidget(header_line)
        layout.addWidget(subtitle)
        layout.addLayout(search_row)
        layout.addWidget(self._table, 1)
        layout.addLayout(footer)
        self._update_action_state()

    def _apply_surface_style(self) -> None:
        self.setStyleSheet(self._style_sheet())

    def _refresh_themed_icons(self) -> None:
        self._paint_leaf_badge(self._logo_badge)

    def _title_bar(self) -> QWidget:
        title_bar = SettingsTitleBar()
        bar = QHBoxLayout(title_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(9)
        logo_badge = self._logo_badge
        logo_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._paint_leaf_badge(logo_badge)
        bar.addWidget(logo_badge)
        title = QLabel(self._translator.text("tcache.title"))
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

    def show(self) -> None:
        """Show the manager and trigger its initial unfiltered search."""
        super().show()
        self._request_search()

    def set_entries(
        self,
        query: TranslationCacheQuery,
        entries: tuple[TranslationCacheEntry, ...],
    ) -> None:
        """Display all cached translations returned for ``query``."""
        del query
        self._model.set_entries(entries)
        self._status.setText(
            self._translator.text("cache.results").format(count=len(entries))
            if entries
            else self._translator.text("cache.no_results")
        )
        self._update_action_state()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._keyword.setEnabled(not busy)
        self._search_button.setEnabled(not busy)
        self._clear_button.setEnabled(not busy)
        self._update_action_state()
        if busy:
            self._status.setText(self._translator.text("cache.loading"))

    def show_error(self, message: str) -> None:
        self._status.setObjectName("cacheError")
        self._status.setText(message)
        self._refresh_status_style()

    def show_message(self, message: str) -> None:
        self._status.setObjectName("cacheStatus")
        self._status.setText(message)
        self._refresh_status_style()

    def show_delete_result(self, results: tuple[TranslationCacheDeleteResult, ...]) -> None:
        deleted = sum(result.status is TranslationCacheDeleteStatus.DELETED for result in results)
        missing = len(results) - deleted
        if missing:
            message = self._translator.text("cache.deleted_partial").format(deleted=deleted, missing=missing)
        else:
            message = self._translator.text("cache.deleted").format(count=deleted)
        self.show_message(message)

    def retheme(self, config: Config) -> None:
        self._config_snapshot = config
        super().retheme(config)
        if self._editor is not None:
            self._editor.retheme(config)

    def show_clear_result(self) -> None:
        self.show_message(self._translator.text("tcache.clear_done"))

    def open_editor(self, record: TranslationCacheRecord) -> None:
        """Open a non-blocking editor for ``record``."""
        if self._editor is not None:
            self._editor.close()
        editor = TranslationEditDialog(
            self._config_snapshot,
            record,
            parent=self,
            translator=self._translator,
            platform_factory=self._platform_factory,
        )
        editor.saved.connect(self._handle_editor_saved)
        editor.finished.connect(self._clear_editor)
        self._editor = editor
        editor.show()

    def show_save_result(self, updated: bool) -> None:
        if updated:
            self.show_message(self._translator.text("tcache.saved"))
        else:
            self.show_error(self._translator.text("tcache.save_missing"))

    def _request_search(self) -> None:
        if self._busy:
            return
        self.intent_requested.emit(SearchTranslationCache(TranslationCacheQuery(keyword=self._keyword.text())))

    def _request_edit_selected(self) -> None:
        keys = self._selected_keys()
        if self._busy or len(keys) != 1:
            return
        self.intent_requested.emit(LoadTranslationCacheRecord(keys[0]))

    def _request_edit_index(self, index: QModelIndex) -> None:
        if self._busy:
            return
        entry = self._model.entry_at(index.row())
        if entry is not None:
            self.intent_requested.emit(LoadTranslationCacheRecord(entry.key))

    def _handle_editor_saved(self, key: object, translations: object) -> None:
        if (
            isinstance(key, TranslationCacheKey)
            and isinstance(translations, tuple)
            and all(isinstance(line, str) for line in translations)
        ):
            self.intent_requested.emit(UpdateTranslationCacheEntry(key, translations))

    def _clear_editor(self, _result: int | None = None) -> None:
        editor = self._editor
        self._editor = None
        if editor is not None:
            editor.deleteLater()

    def _selected_keys(self) -> tuple[TranslationCacheKey, ...]:
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return ()
        keys: list[TranslationCacheKey] = []
        for index in selection_model.selectedRows():
            entry = self._model.entry_at(index.row())
            if entry is not None and entry.key not in keys:
                keys.append(entry.key)
        return tuple(keys)

    def _update_action_state(self) -> None:
        selected = self._selected_keys()
        self._edit_button.setEnabled(not self._busy and len(selected) == 1)
        self._delete_button.setEnabled(not self._busy and bool(selected))

    def _refresh_status_style(self) -> None:
        status_style = self._status.style()
        if status_style is not None:
            status_style.unpolish(self._status)
            status_style.polish(self._status)

    def _confirm_delete(self) -> None:
        keys = self._selected_keys()
        if self._busy or not keys or self._confirmation is not None:
            return
        self._pending_delete = keys
        self._confirmation = QMessageBox(
            QMessageBox.Icon.Warning,
            self._translator.text("tcache.title"),
            self._translator.text("cache.delete_confirm").format(count=len(keys)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self,
        )
        self._confirmation.finished.connect(self._delete_confirmation_finished)
        self._confirmation.open()

    def _delete_confirmation_finished(self, result: int) -> None:
        box = self._confirmation
        self._confirmation = None
        keys = self._pending_delete
        self._pending_delete = ()
        if box is not None:
            box.deleteLater()
        if result == int(QMessageBox.StandardButton.Yes) and keys:
            self.intent_requested.emit(DeleteTranslationCacheEntries(keys))

    def _confirm_clear(self) -> None:
        if self._busy or self._confirmation is not None:
            return
        self._confirmation = QMessageBox(
            QMessageBox.Icon.Warning,
            self._translator.text("tcache.title"),
            self._translator.text("tcache.clear_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self,
        )
        self._confirmation.finished.connect(self._clear_confirmation_finished)
        self._confirmation.open()

    def _clear_confirmation_finished(self, result: int) -> None:
        box = self._confirmation
        self._confirmation = None
        if box is not None:
            box.deleteLater()
        if result == int(QMessageBox.StandardButton.Yes):
            self.intent_requested.emit(ClearTranslationCache())

    def _style_sheet(self) -> str:
        palette = theme._PALETTES[self._theme]
        list_bg = palette["LIST_BG"]
        list_border = palette["LIST_BORDER"]
        field_border = palette["FIELD_BORDER"]
        accent_color = QColor(self._accent)
        accent_soft = f"rgba({accent_color.red()}, {accent_color.green()}, {accent_color.blue()}, 42)"
        return theme._skin(self._accent, self._theme, self._frosted, self._win_opacity) + f"""
QDialog#translationCacheDialog {{ background: transparent; }}
QTableView#translationCacheTable,
QTableView#translationCacheTable > QWidget#qt_scrollarea_viewport {{
    background: {list_bg};
    border: 1px solid {list_border};
    border-radius: 10px;
    color: {palette["TEXT"]};
    outline: none;
    selection-background-color: {accent_soft};
    selection-color: {palette["TEXT_STRONG"]};
    alternate-background-color: {palette["FIELD_BG"]};
}}
QTableView#translationCacheTable::item {{ padding: 7px 8px; border: none; }}
QHeaderView::section {{
    background: {palette["FIELD_BG"]};
    color: {palette["TEXT_DIM"]};
    border: none;
    border-bottom: 1px solid {field_border};
    padding: 8px;
    font-weight: 600;
}}
QHeaderView {{ background: transparent; }}
QLabel#cacheError {{ color: #E56B6F; }}
"""


def _format_time(value: float) -> str:
    try:
        return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "-"


__all__ = ["TranslationCacheDialog", "TranslationCacheTableModel"]
