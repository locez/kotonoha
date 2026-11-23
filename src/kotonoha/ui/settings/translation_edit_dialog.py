"""Non-blocking line-by-line editor for one cached lyric translation."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config import Config
from ...i18n import translation_language_display_name
from ...platform import OverlayPlatformFactory
from ...strings import Translator
from ...translation import TranslationCacheRecord
from . import theme
from .surface import SettingsTitleBar, ThemedSettingsDialog


class TranslationEditDialog(ThemedSettingsDialog):
    """Edit cached translation lines side by side with timestamps and original lyrics."""

    saved = pyqtSignal(object, object)  # (TranslationCacheKey, tuple[str, ...])

    def __init__(
        self,
        config: Config,
        record: TranslationCacheRecord,
        parent: QWidget | None = None,
        *,
        translator: Translator | None = None,
        platform_factory: OverlayPlatformFactory | None = None,
    ) -> None:
        super().__init__(config, parent, platform_factory=platform_factory)
        self._translator = translator if translator is not None else Translator(config.ui_language)
        self._record = record
        self._logo_badge: QLabel = QLabel()
        line_count = len(record.translations)
        self._has_timestamps = len(record.timestamps) == line_count and line_count > 0
        self._has_sources = len(record.source_lines) == line_count and any(
            line.strip() for line in record.source_lines
        )

        headers: list[str] = [self._translator.text("tcache.column.line_no")]
        self._time_col: int | None = None
        self._source_col: int | None = None
        if self._has_timestamps:
            self._time_col = len(headers)
            headers.append(self._translator.text("tcache.column.time"))
        if self._has_sources:
            self._source_col = len(headers)
            headers.append(self._translator.text("tcache.column.source"))
        self._translation_col = len(headers)
        headers.append(self._translator.text("tcache.column.translation"))

        self.setObjectName("translationEditDialog")
        self.setWindowTitle(self._translator.text("tcache.edit_title"))
        self.setMinimumSize(720, 460)
        self.resize(920, 580)
        self._apply_surface_style()
        self._mark_surface_style_ready()

        entry = record.entry
        heading = " — ".join(part for part in (entry.title, entry.artist) if part) or entry.key.content_hash[:12]
        language_label = translation_language_display_name(entry.key.target_language)
        meta = QLabel(f"{heading}  ·  {language_label}  ({entry.provider} / {entry.model})")
        meta.setObjectName("sectionTitle")
        meta.setWordWrap(True)

        hint = QLabel(self._translator.text("tcache.edit_hint"))
        hint.setObjectName("hint")
        hint.setWordWrap(True)

        self._no_source_notice: QLabel | None = None
        if not self._has_sources or not self._has_timestamps:
            notice = QLabel(self._translator.text("tcache.edit_no_source_notice"))
            notice.setObjectName("hint")
            notice.setWordWrap(True)
            self._no_source_notice = notice

        self._table = QTableWidget(line_count, len(headers), self)
        self._table.setObjectName("translationEditTable")
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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
            horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            if self._time_col is not None:
                horizontal_header.setSectionResizeMode(self._time_col, QHeaderView.ResizeMode.ResizeToContents)
            if self._source_col is not None:
                horizontal_header.setSectionResizeMode(self._source_col, QHeaderView.ResizeMode.Stretch)
            horizontal_header.setSectionResizeMode(self._translation_col, QHeaderView.ResizeMode.Stretch)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        for row_idx, translated_line in enumerate(record.translations):
            num_item = QTableWidgetItem(str(row_idx + 1))
            num_item.setFlags(num_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row_idx, 0, num_item)

            if self._time_col is not None:
                time_item = QTableWidgetItem(_format_timestamp(record.timestamps[row_idx]))
                time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row_idx, self._time_col, time_item)

            if self._source_col is not None:
                source_item = QTableWidgetItem(record.source_lines[row_idx])
                source_item.setFlags(source_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row_idx, self._source_col, source_item)

            trans_item = QTableWidgetItem(translated_line)
            self._table.setItem(row_idx, self._translation_col, trans_item)

        save_button = QPushButton(self._translator.text("btn.save"))
        save_button.clicked.connect(self._emit_save)
        cancel_button = QPushButton(self._translator.text("btn.cancel"))
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
        layout.addWidget(self._title_bar())
        layout.addWidget(header_line)
        layout.addWidget(meta)
        layout.addWidget(hint)
        if self._no_source_notice is not None:
            layout.addWidget(self._no_source_notice)
        layout.addWidget(self._table, 1)
        layout.addLayout(footer)

    def edited_translations(self) -> tuple[str, ...]:
        """Return the current edited translation line for every row in order."""
        lines: list[str] = []
        for row_idx in range(self._table.rowCount()):
            item = self._table.item(row_idx, self._translation_col)
            lines.append(item.text().strip() if item is not None else "")
        return tuple(lines)

    def _emit_save(self) -> None:
        self.saved.emit(self._record.entry.key, self.edited_translations())
        self.close()

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
        title = QLabel(self._translator.text("tcache.edit_title"))
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

    def _style_sheet(self) -> str:
        palette = theme._PALETTES[self._theme]
        list_bg = palette["LIST_BG"]
        list_border = palette["LIST_BORDER"]
        field_border = palette["FIELD_BORDER"]
        accent_color = QColor(self._accent)
        accent_soft = f"rgba({accent_color.red()}, {accent_color.green()}, {accent_color.blue()}, 42)"
        return theme._skin(self._accent, self._theme, self._frosted, self._win_opacity) + f"""
QDialog#translationEditDialog {{ background: transparent; }}
QTableWidget#translationEditTable,
QTableWidget#translationEditTable > QWidget#qt_scrollarea_viewport {{
    background: {list_bg};
    border: 1px solid {list_border};
    border-radius: 10px;
    color: {palette["TEXT"]};
    outline: none;
    selection-background-color: {accent_soft};
    selection-color: {palette["TEXT_STRONG"]};
    alternate-background-color: {palette["FIELD_BG"]};
}}
QTableWidget#translationEditTable::item {{ padding: 6px 8px; border: none; }}
QHeaderView::section {{
    background: {palette["FIELD_BG"]};
    color: {palette["TEXT_DIM"]};
    border: none;
    border-bottom: 1px solid {field_border};
    padding: 8px;
    font-weight: 600;
}}
QHeaderView {{ background: transparent; }}
"""


def _format_timestamp(seconds: float) -> str:
    """Format a lyric timestamp in seconds as ``MM:SS.cc``."""
    total_centis = max(0, round(seconds * 100))
    minutes, rem_centis = divmod(total_centis, 6000)
    secs, centis = divmod(rem_centis, 100)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"
    return f"{minutes:02d}:{secs:02d}.{centis:02d}"


__all__ = ["TranslationEditDialog"]
