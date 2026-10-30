"""Standalone local lyric-cache management dialog."""

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

from ...app.intents import ClearCache, DeleteCacheEntries, SearchCache
from ...config import Config
from ...display.models import LyricsDisplayStatus
from ...lyrics.cache import (
    CacheDeleteResult,
    CacheDeleteStatus,
    LyricsCacheEntry,
    LyricsCacheKey,
    LyricsCacheMode,
    LyricsCacheQuery,
)
from ...lyrics.models import LyricsCacheState
from ...platform import OverlayPlatformFactory
from ...strings import Translator
from . import theme
from .lyrics_status import LyricsStatusBand
from .surface import SettingsTitleBar, ThemedSettingsDialog


class LyricsCacheTableModel(QAbstractTableModel):
    """Present cache metadata while retaining exact keys for deletion."""

    def __init__(self, translator: Translator) -> None:
        super().__init__()
        self._translator = translator
        self._entries: tuple[LyricsCacheEntry, ...] = ()
        # Only cache-backed active documents can mark a stored row as in use.
        self._current_cache_key: LyricsCacheKey | None = None

    def set_entries(self, entries: tuple[LyricsCacheEntry, ...]) -> None:
        """Replace all visible rows with one completed search result."""
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()

    def set_current_status(self, status: LyricsDisplayStatus) -> None:
        """Mark the exact cached document currently supplying the display."""
        key = None
        if (
            status.cache_state in (LyricsCacheState.FROM_CACHE, LyricsCacheState.MANUAL)
            and status.lyrics_source_id is not None and status.lyrics_song_id is not None
        ):
            key = LyricsCacheKey(status.lyrics_source_id, status.lyrics_song_id)
        if key == self._current_cache_key:
            return
        self._current_cache_key = key
        if self._entries:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._entries) - 1, 0), [Qt.ItemDataRole.DisplayRole],
            )

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        """Return the number of cache rows."""
        return 0 if parent is not None and parent.isValid() else len(self._entries)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        """Return the fixed cache metadata column count."""
        del parent
        return 7

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        """Return display or tooltip data for one cache entry cell."""
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            provider = entry.key.provider
            if entry.key == self._current_cache_key:
                provider = f"{provider} · ✓ {self._translator.text('search.in_use')}"
            values = (
                provider,
                entry.title,
                entry.artist,
                entry.album,
                _format_time(entry.fetched_at),
                _format_time(entry.last_accessed),
                self._translator.text(
                    "cache.mode.auto" if entry.mode is LyricsCacheMode.AUTO else "cache.mode.manual"
                ),
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{entry.key.provider}:{entry.key.provider_song_id}"
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        """Return translated table headers."""
        if orientation is not Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.ToolTipRole and section == 5:
            return self._translator.text("cache.accessed_tooltip")
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        headers = (
            "cache.column.provider",
            "cache.column.title",
            "cache.column.artist",
            "cache.column.album",
            "cache.column.fetched",
            "cache.column.accessed",
            "cache.column.mode",
        )
        return self._translator.text(headers[section]) if 0 <= section < len(headers) else None

    def entry_at(self, row: int) -> LyricsCacheEntry | None:
        """Return the row's typed entry, if it is still present."""
        return self._entries[row] if 0 <= row < len(self._entries) else None


class LyricsCacheDialog(ThemedSettingsDialog):
    """Search and delete persistent lyric-cache entries in a separate window."""

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
        self._translator = translator if translator is not None else Translator(config.ui_language)
        self._confirmation: QMessageBox | None = None
        self._pending_delete: tuple[LyricsCacheKey, ...] = ()
        self._query = LyricsCacheQuery()
        self._busy = False

        self.setObjectName("cacheDialog")
        self.setWindowTitle(self._translator.text("cache.title"))
        self.setMinimumSize(760, 480)
        self.resize(960, 600)
        self._apply_surface_style()
        self._mark_surface_style_ready()

        self._model = LyricsCacheTableModel(self._translator)
        self._keyword = QLineEdit()
        self._keyword.setPlaceholderText(self._translator.text("cache.search_placeholder"))
        self._keyword.returnPressed.connect(self._request_search)
        self._search_button = QPushButton(self._translator.text("btn.search_cache"))
        self._search_button.setIcon(QIcon.fromTheme("system-search"))
        self._search_button.clicked.connect(self._request_search)

        self._table = QTableView()
        self._table.setObjectName("cacheTable")
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
            for section in (1, 2, 3):
                horizontal_header.setSectionResizeMode(section, QHeaderView.ResizeMode.Stretch)
            for section in (4, 5, 6):
                horizontal_header.setSectionResizeMode(section, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._table.doubleClicked.connect(self._show_entry_tooltip)
        selection_model = self._table.selectionModel()
        if selection_model is None:
            raise RuntimeError("cache table selection model is unavailable")
        selection_model.selectionChanged.connect(self._update_action_state)

        self._status = QLabel(self._translator.text("cache.loading"))
        self._status.setObjectName("cacheStatus")
        self._delete_button = QPushButton(self._translator.text("btn.delete_cache"))
        widget_style = self.style()
        if widget_style is not None:
            self._delete_button.setIcon(widget_style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self._delete_button.setToolTip(self._translator.text("cache.delete_tooltip"))
        self._delete_button.clicked.connect(self._confirm_delete)
        self._clear_button = QPushButton(self._translator.text("btn.clear_cache"))
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
        footer.addWidget(self._delete_button)
        footer.addWidget(self._clear_button)
        footer.addWidget(close_button)

        subtitle = QLabel(self._translator.text("cache.subtitle"))
        subtitle.setObjectName("hint")
        subtitle.setWordWrap(True)

        current_heading = QLabel(self._translator.text("cache.current_heading"))
        current_heading.setObjectName("sectionTitle")
        self._status_band: LyricsStatusBand = LyricsStatusBand(LyricsDisplayStatus(), self._translator, self)

        header_line = QWidget()
        header_line.setObjectName("navDivider")
        header_line.setFixedHeight(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(self._title_bar())
        layout.addWidget(header_line)
        layout.addWidget(subtitle)
        layout.addWidget(current_heading)
        layout.addWidget(self._status_band)
        layout.addLayout(search_row)
        layout.addWidget(self._table, 1)
        layout.addLayout(footer)

    def _apply_surface_style(self) -> None:
        """Apply the shared settings skin plus the cache table rules."""
        self.setStyleSheet(self._style_sheet())

    def _refresh_themed_icons(self) -> None:
        """Re-tint the one mark this window draws from the palette."""
        self._paint_leaf_badge(self._logo_badge)

    def _title_bar(self) -> QWidget:
        """Build the same draggable title bar used by the main Settings dialog."""
        title_bar = SettingsTitleBar()
        bar = QHBoxLayout(title_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(9)
        logo_badge = QLabel()
        logo_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._logo_badge = logo_badge
        self._paint_leaf_badge(logo_badge)
        bar.addWidget(logo_badge)
        title = QLabel(self._translator.text("cache.title"))
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
        """Show the manager and request its initial unfiltered result set."""
        super().show()
        self._request_search()

    def set_entries(self, query: LyricsCacheQuery, entries: tuple[LyricsCacheEntry, ...]) -> None:
        """Display all entries returned for the latest query."""
        self._query = query
        self._model.set_entries(entries)
        self._status.setText(
            self._translator.text("cache.results").format(count=len(entries))
            if entries
            else self._translator.text("cache.no_results")
        )
        self._update_action_state()

    def set_current_status(self, status: LyricsDisplayStatus) -> None:
        """Show actual display provenance and mark a row only when read from cache."""
        self._status_band.set_status(status)
        self._model.set_current_status(status)

    def set_busy(self, busy: bool) -> None:
        """Disable commands while the application-owned cache task runs."""
        self._busy = busy
        self._keyword.setEnabled(not busy)
        self._search_button.setEnabled(not busy)
        self._clear_button.setEnabled(not busy)
        self._update_action_state()
        if busy:
            self._status.setText(self._translator.text("cache.loading"))

    def show_error(self, message: str) -> None:
        """Show a localized operation failure while retaining the current rows."""
        self._status.setObjectName("cacheError")
        self._status.setText(message)
        self._refresh_status_style()

    def show_message(self, message: str) -> None:
        """Show a completed operation result in the status area."""
        self._status.setObjectName("cacheStatus")
        self._status.setText(message)
        self._refresh_status_style()

    def show_delete_result(self, results: tuple[CacheDeleteResult, ...]) -> None:
        """Render the actual deletion outcome using the active UI language."""
        deleted = sum(result.status is CacheDeleteStatus.DELETED for result in results)
        missing = len(results) - deleted
        if missing:
            message = self._translator.text("cache.deleted_partial").format(deleted=deleted, missing=missing)
        else:
            message = self._translator.text("cache.deleted").format(count=deleted)
        self.show_message(message)

    def show_clear_result(self) -> None:
        """Render a successful full-cache clear operation."""
        self.show_message(self._translator.text("cache.clear_done"))

    def _request_search(self) -> None:
        """Publish one user-entered fuzzy metadata query."""
        if self._busy:
            return
        query = LyricsCacheQuery(keyword=self._keyword.text())
        self.intent_requested.emit(SearchCache(query))

    def _selected_keys(self) -> tuple[LyricsCacheKey, ...]:
        """Read exact stable keys from the currently selected table rows."""
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return ()
        keys: list[LyricsCacheKey] = []
        for index in selection_model.selectedRows():
            entry = self._model.entry_at(index.row())
            if entry is not None and entry.key not in keys:
                keys.append(entry.key)
        return tuple(keys)

    def _update_action_state(self) -> None:
        """Keep row actions aligned with the current selection and operation state."""
        self._delete_button.setEnabled(not self._busy and bool(self._selected_keys()))

    def _refresh_status_style(self) -> None:
        """Reapply the status label selector after changing its object name."""
        status_style = self._status.style()
        if status_style is not None:
            status_style.unpolish(self._status)
            status_style.polish(self._status)

    def _confirm_delete(self) -> None:
        """Ask for confirmation without entering a nested Qt event loop."""
        keys = self._selected_keys()
        if self._busy or not keys or self._confirmation is not None:
            return
        self._pending_delete = keys
        self._confirmation = self._message_box(
            self._translator.text("cache.delete_confirm").format(count=len(keys)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        self._confirmation.finished.connect(self._delete_confirmation_finished)
        self._confirmation.open()

    def _delete_confirmation_finished(self, result: int) -> None:
        """Submit deletion only after the user confirms it."""
        box = self._confirmation
        self._confirmation = None
        keys = self._pending_delete
        self._pending_delete = ()
        if box is not None:
            box.deleteLater()
        if result == int(QMessageBox.StandardButton.Yes) and keys:
            self.intent_requested.emit(DeleteCacheEntries(keys))

    def _confirm_clear(self) -> None:
        """Confirm clearing the entire cache through a non-blocking message box."""
        if self._busy or self._confirmation is not None:
            return
        self._confirmation = self._message_box(
            self._translator.text("cache.clear_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        self._confirmation.finished.connect(self._clear_confirmation_finished)
        self._confirmation.open()

    def _clear_confirmation_finished(self, result: int) -> None:
        """Submit the clear command after the user confirms it."""
        box = self._confirmation
        self._confirmation = None
        if box is not None:
            box.deleteLater()
        if result == int(QMessageBox.StandardButton.Yes):
            self.intent_requested.emit(ClearCache())

    def _message_box(self, text: str, buttons: QMessageBox.StandardButton) -> QMessageBox:
        """Build a confirmation box whose completion is handled asynchronously."""
        box = QMessageBox(QMessageBox.Icon.Warning, self._translator.text("cache.title"), text, buttons, self)
        return box

    def _show_entry_tooltip(self, index: QModelIndex) -> None:
        """Show the provider identity when a row is double-clicked."""
        entry = self._model.entry_at(index.row())
        if entry is not None:
            self._table.setToolTip(f"{entry.key.provider}:{entry.key.provider_song_id}")

    def _style_sheet(self) -> str:
        """Extend the shared settings skin with dense table-management styling."""
        palette = theme._PALETTES[self._theme]
        list_bg = palette["LIST_BG"]
        list_border = palette["LIST_BORDER"]
        field_border = palette["FIELD_BORDER"]
        accent_color = QColor(self._accent)
        accent_soft = f"rgba({accent_color.red()}, {accent_color.green()}, {accent_color.blue()}, 42)"
        return theme._skin(self._accent, self._theme, self._frosted, self._win_opacity) + f"""
QDialog#cacheDialog {{ background: transparent; }}
QTableView#cacheTable,
QTableView#cacheTable > QWidget#qt_scrollarea_viewport {{
    background: {list_bg};
    border: 1px solid {list_border};
    border-radius: 10px;
    color: {palette["TEXT"]};
    outline: none;
    selection-background-color: {accent_soft};
    selection-color: {palette["TEXT_STRONG"]};
    alternate-background-color: {palette["FIELD_BG"]};
}}
QTableView#cacheTable::item {{ padding: 7px 8px; border: none; }}
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
    """Format a cache timestamp in the user's local timezone."""
    try:
        return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "-"


__all__ = ["LyricsCacheDialog", "LyricsCacheTableModel"]
