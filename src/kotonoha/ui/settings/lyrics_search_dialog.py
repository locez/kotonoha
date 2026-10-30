"""Themed window for searching and explicitly applying lyric candidates."""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...app.intents import SearchLyrics, SelectLyrics
from ...config import Config
from ...display.models import LyricsDisplayStatus
from ...icons import clear_icon, heading_icon, search_icon
from ...lyrics.cache import CacheWriteResult, CacheWriteStatus
from ...lyrics.match import MatchConfidence
from ...lyrics.models import LyricsCacheState
from ...lyrics.search import LyricsSearchQuery, LyricsSearchResponse, LyricsSearchResult
from ...platform import OverlayPlatformFactory
from ...strings import Translator
from . import theme
from .delegates import SelectionBarDelegate
from .lyrics_search_header import TrackHeader
from .lyrics_search_model import (
    LyricsSearchSortModel,
    LyricsSearchTableModel,
    format_unavailable_details,
    format_unavailable_sources,
)
from .lyrics_search_theme import search_window_skin
from .lyrics_status import LyricsStatusBand
from .surface import SettingsTitleBar, ThemedSettingsDialog
from .widgets import ClearableLineEdit, ElidingLabel, RoundedTableView


class LyricsSearchDialog(ThemedSettingsDialog):
    """Search configured lyric providers and apply one selected result."""

    intent_requested = pyqtSignal(object)

    def __init__(
        self,
        config: Config,
        query: LyricsSearchQuery,
        parent: QWidget | None = None,
        *,
        status: LyricsDisplayStatus | None = None,
        translator: Translator | None = None,
        platform_factory: OverlayPlatformFactory | None = None,
    ) -> None:
        super().__init__(config, parent, platform_factory=platform_factory)
        self._translator = translator if translator is not None else Translator(config.ui_language)
        self._current_query = query
        self._results: tuple[LyricsSearchResult, ...] = ()
        self._busy = False
        self._current_status = status if status is not None else LyricsDisplayStatus()

        self.setObjectName("lyricsSearchDialog")
        self.setWindowTitle(self._translator.text("search.title"))
        self.setMinimumSize(820, 540)
        self.resize(1060, 700)
        self._apply_surface_style()
        self._mark_surface_style_ready()

        self._model = LyricsSearchTableModel(
self._translator, self._confidence_colours())
        self._model.set_current_status(self._current_status)
        # Every query field, so a theme change can redraw their clear marks.
        self._query_edits: list[ClearableLineEdit] = []
        # A player that reports only a page title knows less about the track than
        # the lyrics already chosen for it, so those fill what it left empty.
        self._title_edit = self._query_edit("search.placeholder.title", query.title)
        self._artist_edit = self._query_edit(
            "search.placeholder.artist", query.artist or (self._current_status.lyrics_artist or "")
        )
        # Release names vary between catalogs. Only an explicitly entered album
        # should narrow the search; the current release stays in the track header.
        self._album_edit: ClearableLineEdit = self._query_edit("search.placeholder.album", "")
        for editor in (self._title_edit, self._artist_edit, self._album_edit):
            editor.returnPressed.connect(self._request_search)

        self._search_button = QPushButton(self._translator.text("btn.search_lyrics"))
        self._search_button.setObjectName("searchButton")
        # The button carries the accent fill in both themes, so its glyph takes the
        # token for what sits on the accent rather than the one for the surface.
        self._search_button.setIcon(search_icon(self._on_accent_glyph()))
        self._search_button.clicked.connect(self._request_search)

        self._table = RoundedTableView(10)
        self._table.setObjectName("lyricsSearchTable")
        self._sorted = LyricsSearchSortModel(self._model)
        self._table.setModel(self._sorted)
        self._table.setSortingEnabled(True)
        horizontal = self._table.horizontalHeader()
        if horizontal is not None:
            horizontal.setSortIndicatorShown(False)  # the column name carries it
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setItemDelegate(self._row_delegate())
        self._unavailable = ElidingLabel()
        self._unavailable.setObjectName("hint")
        self._high_only = QCheckBox(self._translator.text("search.high_matches_only"))
        self._high_only.toggled.connect(self._sorted.set_high_only)
        self._high_only.toggled.connect(self._update_action_state)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table_viewport = self._table.viewport()
        if table_viewport is not None:
            table_viewport.setAutoFillBackground(False)
        vertical_header = self._table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)
        horizontal_header = self._table.horizontalHeader()
        if horizontal_header is not None:
            horizontal_header.setAutoFillBackground(False)
            horizontal_header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            horizontal_header.setStretchLastSection(False)
            horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            for section in (1, 2, 3):
                horizontal_header.setSectionResizeMode(section, QHeaderView.ResizeMode.Stretch)
            for section in (4, 5, 6):
                horizontal_header.setSectionResizeMode(section, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._table.doubleClicked.connect(self._request_apply_for_index)
        selection_model = self._table.selectionModel()
        if selection_model is None:
            raise RuntimeError("lyrics search table selection model is unavailable")
        selection_model.selectionChanged.connect(self._update_action_state)

        self._status = ElidingLabel()
        self._status.setObjectName("searchStatus")
        # Persistent completion feedback, separate from transient search counts.
        self._apply_feedback: QLabel = QLabel()
        self._apply_feedback.setObjectName("searchApplyFeedback")
        self._apply_feedback.setWordWrap(True)
        self._apply_feedback.hide()
        self._apply_button = QPushButton(self._translator.text("btn.apply_lyrics"))
        self._apply_button.setObjectName("applyButton")
        self._apply_button.clicked.connect(self._request_apply)
        close_button = QPushButton(self._translator.text("btn.close"))
        close_button.clicked.connect(self.close)
        for button in (self._search_button, self._apply_button, close_button):
            button.setAutoDefault(False)
        close_button.setObjectName("dialogCloseButton")
        subtitle = QLabel(self._translator.text("search.subtitle"))
        subtitle.setObjectName("hint")
        subtitle.setWordWrap(True)
        self._status_band = LyricsStatusBand(self._current_status, self._translator, self)
        current_meta = TrackHeader(query, self._current_status, self._translator, self._status_band)
        query_form = self._query_form()
        header_line = QWidget()
        header_line.setObjectName("navDivider")
        header_line.setFixedHeight(1)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(self._status, 1)
        footer.addWidget(self._apply_button)
        footer.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(self._title_bar())
        layout.addWidget(header_line)
        layout.addWidget(subtitle)
        layout.addWidget(current_meta)
        self._query_mark = QLabel()
        query_title = self._section_title("search.query_heading", self._query_mark)
        query_title.setContentsMargins(6, 0, 6, 0)
        layout.addLayout(query_title)
        layout.addWidget(query_form)
        self._results_mark = QLabel()
        table_tools = QHBoxLayout()
        # Indented to the table's own content, so the title sits over its columns
        # rather than over the window's margin.
        table_tools.setContentsMargins(6, 0, 6, 0)
        table_tools.addLayout(self._section_title("search.results_heading", self._results_mark))
        table_tools.addSpacing(12)
        table_tools.addWidget(self._unavailable, 1)
        table_tools.addWidget(self._high_only)
        layout.addLayout(table_tools)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._apply_feedback)
        layout.addLayout(footer)
        # The marks this window rasterizes from the palette are painted on one
        # path, so opening in a theme and moving to another cannot disagree.
        self._refresh_themed_icons()
        self._update_action_state()

    def _clear_glyph(self) -> str:
        """Return this theme's colour for the field clear glyph."""
        return str(theme._PALETTES[self._theme]["GLYPH_CLEAR"])

    def _refresh_themed_icons(self) -> None:
        """Redraw everything this window coloured from the palette it started in.

        The table's ratings and the delegate's chips take their colours once, so a
        theme change left them reading against a surface that had moved without
        them.
        """
        glyph = clear_icon(self._clear_glyph())
        for editor in self._query_edits:
            editor.set_clear_glyph(glyph)
        heading = self._heading_glyph()
        self._search_button.setIcon(search_icon(self._on_accent_glyph()))
        self._model.set_confidence_colours(self._confidence_colours())
        self._table.setItemDelegate(self._row_delegate())
        self._query_mark.setPixmap(heading_icon("search", heading).pixmap(17, 17))
        self._results_mark.setPixmap(heading_icon("list", heading).pixmap(17, 17))
        self._paint_leaf_badge(self._logo_badge)

    def _apply_surface_style(self) -> None:
        """Apply the shared settings skin plus result-window surface rules."""
        self.setStyleSheet(self._style_sheet())

    def _title_bar(self) -> QWidget:
        """Build the shared draggable title bar with the application mark."""
        title_bar = SettingsTitleBar()
        bar = QHBoxLayout(title_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(9)
        logo_badge = QLabel()
        logo_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._logo_badge = logo_badge
        bar.addWidget(logo_badge)
        title = QLabel(self._translator.text("search.title"))
        title.setObjectName("dialogTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        close_button = QPushButton("✕")
        close_button.setObjectName("closeButton")
        close_button.setAutoDefault(False)
        close_button.setFixedSize(26, 26)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.close)
        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(close_button)
        return title_bar

    def _row_delegate(self) -> SelectionBarDelegate:
        """Build the result-row delegate in the theme currently in effect."""
        chips = theme._PALETTES[self._theme]
        return SelectionBarDelegate(
            self._accent,
            str(chips["CHIP_BG"]),
            str(chips["CHIP_TEXT"]),
            str(chips["CHIP_BORDER"]),
            self._table,
        )

    def _on_accent_glyph(self) -> str:
        """Return the colour a glyph takes when it sits on the accent fill."""
        return str(theme._PALETTES[self._theme]["GLYPH_ON_ACCENT"])

    def _heading_glyph(self) -> str:
        """Return this theme's colour for a section-title glyph.

        A hex token: TEXT_DIM is Qt's rgba(r,g,b,0-255), which an SVG stroke does
        not parse, and a stroke that does not parse paints nothing.
        """
        return str(theme._PALETTES[self._theme]["TEXT"])

    def _section_title(self, key: str, glyph: QLabel) -> QHBoxLayout:
        """Build one titled section header: its glyph, then its name."""
        heading = QLabel(self._translator.text(key))
        heading.setObjectName("sectionTitle")
        titled = QHBoxLayout()
        titled.setSpacing(6)
        titled.addWidget(glyph)
        titled.addWidget(heading, 1)
        return titled

    def _query_form(self) -> QWidget:
        """Build the editable title, artist, album, and search controls."""
        widget = QFrame()
        widget.setObjectName("searchPanel")
        grid = QGridLayout(widget)
        grid.setContentsMargins(12, 10, 12, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        fields = (
            ("search.query_title", self._title_edit),
            ("search.query_artist", self._artist_edit),
            ("search.query_album", self._album_edit),
        )
        for column, (key, editor) in enumerate(fields):
            label = QLabel(self._translator.text(key))
            label.setObjectName("fieldLabel")
            grid.addWidget(label, 1, column * 2)
            grid.addWidget(editor, 2, column * 2, 1, 2)
        grid.addWidget(self._search_button, 2, 6)
        return widget

    def _query_edit(self, placeholder_key: str, value: str) -> ClearableLineEdit:
        """Create one bounded, editable search field."""
        editor = ClearableLineEdit(value, clear_icon(self._clear_glyph()))
        editor.setObjectName("queryField")
        editor.setPlaceholderText(self._translator.text(placeholder_key))
        self._query_edits.append(editor)
        return editor

    def show(self) -> None:
        """Show the window and run the search it was opened to make.

        Title and artist are already filled from the track and the lyrics in use;
        album stays optional. Run that query immediately without an extra click.
        """
        super().show()
        self._title_edit.setFocus()
        self._title_edit.selectAll()
        self._request_search()

    def set_results(self, query: LyricsSearchQuery, response: LyricsSearchResponse) -> None:
        """Display all provider candidates returned for the latest query."""
        self._current_query = query
        self._results = response.results
        self._model.set_results(response.results)
        # Arrival order says nothing about fit; lead with the best match.
        self._table.sortByColumn(6, Qt.SortOrder.DescendingOrder)
        # Which sources could not answer is a footnote about the search, not part of
        # the result count; it sits by the table it qualifies.
        sources = format_unavailable_sources(response.unavailable_sources, self._translator)
        self._unavailable.setText(
            self._translator.text("search.unavailable_prefix").format(sources=sources) if sources else ""
        )
        self._unavailable.setToolTip(
            format_unavailable_details(response.unavailable_sources, self._translator)
        )
        if response.results:
            message = self._translator.text("search.results").format(count=len(response.results))
        else:
            message = self._translator.text("search.no_results")
        self._show_status(message)
        self._select_applied_result()
        self._update_action_state()

    def _select_applied_result(self) -> None:
        """Land the selection on the lyrics already in use, when they came back.

        Opening the window on nothing selected asks the reader to find the row
        they are already listening to before they can compare anything to it.
        """
        wanted = self._current_status.lyrics_song_id
        source = self._current_status.lyrics_source_id
        if not wanted:
            return
        for row in range(self._sorted.rowCount()):
            result = self._sorted.result_at(row)
            if result is None:
                continue
            artifact = result.artifact
            if artifact.provider_song_id == wanted and (source is None or artifact.provider == source):
                self._table.selectRow(row)
                return

    def set_current_status(self, status: LyricsDisplayStatus) -> None:
        """Refresh the active lyric source after a selection is applied."""
        self._current_status = status
        self._status_band.set_status(status)
        self._model.set_current_status(status)
        self._update_action_state()

    def set_busy(self, busy: bool) -> None:
        """Disable query and selection commands while an owned task is active."""
        self._busy = busy
        for editor in (self._title_edit, self._artist_edit, self._album_edit):
            editor.setEnabled(not busy)
        self._search_button.setEnabled(not busy)
        self._table.setEnabled(not busy)
        self._update_action_state()
        if busy:
            self._apply_feedback.hide()
            self._show_status(self._translator.text("search.loading"))

    def show_error(self, message: str) -> None:
        """Show a failed operation without discarding the rows already found.

        The argument is a `strings` key. An unknown key resolves to itself, so a
        caller outside this vocabulary still reports something rather than nothing.
        """
        self._status.setObjectName("searchError")
        self._apply_feedback.hide()
        self._status.setText(self._translator.text(message))
        self._refresh_status_style()

    def show_apply_result(self, result: CacheWriteResult, displayed: bool) -> None:
        """Show the cache outcome and whether the active display changed immediately."""
        key = "search.apply.created" if result.status is CacheWriteStatus.CREATED else "search.apply.updated"
        message = self._translator.text(key)
        if not displayed:
            message = self._translator.text("search.apply.saved")
        self._apply_feedback.setText(f"✓ {message}")
        self._apply_feedback.show()
        self._show_status("")

    def _request_search(self) -> None:
        """Publish one editable provider-search query."""
        if self._busy:
            return
        query = LyricsSearchQuery(
            self._title_edit.text(),
            self._artist_edit.text(),
            self._album_edit.text(),
            self._current_query.duration_s,
        )
        self.intent_requested.emit(SearchLyrics(query))

    def _request_apply(self) -> None:
        """Publish the currently selected result for explicit cache persistence."""
        if self._busy:
            return
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return
        rows = selection_model.selectedRows()
        if not rows:
            return
        result = self._sorted.result_at(rows[0].row())
        if result is not None and self._apply_button.isEnabled():
            self.intent_requested.emit(SelectLyrics(result))

    def _request_apply_for_index(self, index: QModelIndex) -> None:
        """Apply the row activated by a double-click."""
        if not self._busy:
            self._table.selectRow(index.row())
            self._request_apply()

    def _update_action_state(self, *_args: object) -> None:
        """Keep the apply action aligned with current selection and task state."""
        selection_model = self._table.selectionModel()
        rows = selection_model.selectedRows() if selection_model is not None else []
        selected = self._sorted.result_at(rows[0].row()) if rows else None
        applied = (
            selected is not None and self._model.is_current(selected)
            and self._current_status.cache_state is LyricsCacheState.MANUAL
        )
        key = "search.applied" if applied else "btn.apply_lyrics"
        self._apply_button.setText(self._translator.text(key))
        self._apply_button.setEnabled(not self._busy and selected is not None and not applied)

    def _show_status(self, message: str, detail: str = "") -> None:
        """Render a status message, keeping any longer explanation in its tooltip."""
        self._status.setObjectName("searchStatus")
        self._status.setText(message)
        # The line elides, so the per-source reasons have to stay reachable.
        self._status.setToolTip(detail)
        self._refresh_status_style()

    def _refresh_status_style(self) -> None:
        """Reapply the status label selector after changing its object name."""
        status_style = self._status.style()
        if status_style is not None:
            status_style.unpolish(self._status)
            status_style.polish(self._status)

    def _confidence_colours(self) -> dict[MatchConfidence, str]:
        """Map each match rating onto this theme's token for it."""
        palette = theme._PALETTES[self._theme]
        return {
            MatchConfidence.HIGH: str(palette["MATCH_HIGH"]),
            MatchConfidence.MEDIUM: str(palette["MATCH_MEDIUM"]),
            MatchConfidence.NONE: str(palette["MATCH_NONE"]),
        }

    def _style_sheet(self) -> str:
        """Extend the shared theme with this window's own surface rules."""
        return search_window_skin(self._accent, self._theme, self._frosted, self._win_opacity)
