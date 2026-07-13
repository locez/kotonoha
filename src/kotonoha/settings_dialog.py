"""Tabbed settings panel.

Frameless, translucent, dark "glass" styling to match the overlay. Edits a
working copy of :class:`~kotonoha.config.Config` across grouped tabs and emits
``applied`` with the new config when the user applies/accepts. UI strings come
from :mod:`kotonoha.strings`.
"""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QMouseEvent, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import ACCENT_PRESETS, DEFAULT_ICON_NAME, VALID_LYRICS_SOURCES, Config
from .strings import UI_LANGUAGES, t
from .tray import discover_icon_paths

_STYLE = """
QWidget {
    color: #E6E6E8;
    font-family: 'Inter', 'Segoe UI', 'Microsoft YaHei', sans-serif;
    font-size: 13px;
}
QTabWidget::pane {
    border: 1px solid rgba(255,255,255,25);
    border-radius: 10px;
    background: rgba(255,255,255,10);
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: rgba(255,255,255,140);
    padding: 6px 16px;
    margin-right: 2px;
    border: none;
}
QTabBar::tab:selected { color: #FFFFFF; border-bottom: 2px solid %ACCENT%; }
QTabBar::tab:hover { color: #FFFFFF; }
QLabel { background: transparent; }
QCheckBox { background: transparent; spacing: 8px; }
QCheckBox::indicator, QListWidget::indicator {
    width: 16px; height: 16px;
    border: 1px solid rgba(255,255,255,60);
    border-radius: 4px;
    background: rgba(255,255,255,15);
}
/* Once the indicator is custom-styled, Qt no longer paints the native tick, so
   the checkmark must be supplied explicitly — otherwise checked boxes rendered
   as a bare filled square with no glyph, inconsistently across the dialog. */
QCheckBox::indicator:checked, QListWidget::indicator:checked {
    background: %ACCENT%;
    border-color: %ACCENT%;
    image: url(%CHECK%);
}
QSpinBox, QComboBox {
    background: rgba(255,255,255,18);
    border: 1px solid rgba(255,255,255,30);
    border-radius: 6px;
    padding: 4px 8px;
    color: #FFFFFF;
    min-height: 20px;
}
QSpinBox:hover, QComboBox:hover { border-color: rgba(255,255,255,70); }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background: #1a1c22;
    color: #E6E6E8;
    border: 1px solid rgba(255,255,255,30);
    selection-background-color: %ACCENT%;
    outline: none;
}
QListWidget {
    background: rgba(255,255,255,12);
    border: 1px solid rgba(255,255,255,25);
    border-radius: 8px;
    outline: none;
    padding: 4px;
}
QListWidget::item { padding: 7px 8px; border-radius: 5px; }
QListWidget::item:selected { background: rgba(255,255,255,28); color: #FFFFFF; }
QListWidget#iconPicker { padding: 3px; }
QListWidget#iconPicker::item {
    padding: 0;
    margin: 2px;
    border: 1px solid transparent;
    border-radius: 6px;
}
QListWidget#iconPicker::item:selected {
    background: rgba(255,255,255,26);
    border-color: %ACCENT%;
}
QPushButton {
    background: rgba(255,255,255,22);
    border: 1px solid rgba(255,255,255,40);
    border-radius: 6px;
    padding: 5px 16px;
    color: #FFFFFF;
}
QPushButton:hover { background: rgba(255,255,255,42); }
QPushButton:pressed { background: rgba(255,255,255,60); }
"""

_CLOSE_STYLE = (
    "QPushButton{background:transparent;border:none;color:rgba(255,255,255,140);"
    "font-size:16px;padding:0;} QPushButton:hover{color:#FFFFFF;}"
)

# White checkmark (inline SVG data URI) painted over a checked indicator; kept out
# of the QSS block so the long line can carry its own noqa.
_CHECKMARK_ICON = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiIgdmlld0JveD0iMCAwIDE2IDE2Ij48cGF0aCBkPSJNMy41IDguNSBMNi41IDExLjUgTDEyLjUgNC41IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIuMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+PC9zdmc+"  # noqa: E501


def _skin(accent: str) -> str:
    """Fill the QSS template with the accent colour and the checkmark glyph."""
    return _STYLE.replace("%ACCENT%", accent).replace("%CHECK%", _CHECKMARK_ICON)


class SettingsDialog(QDialog):
    applied = pyqtSignal(object)  # emits Config
    clear_cache_requested = pyqtSignal()

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_skin(config.accent_start))
        self.setMinimumWidth(440)

        tabs = QTabWidget()
        tabs.addTab(self._general_tab(), t("tab.general"))
        tabs.addTab(self._appearance_tab(), t("tab.appearance"))
        tabs.addTab(self._lyrics_tab(), t("tab.lyrics"))
        tabs.addTab(self._position_tab(), t("tab.position"))
        tabs.addTab(self._sources_tab(), t("tab.sources"))
        tabs.addTab(self._connection_tab(), t("tab.connection"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        for std, key in (
            (QDialogButtonBox.StandardButton.Ok, "btn.ok"),
            (QDialogButtonBox.StandardButton.Cancel, "btn.cancel"),
            (QDialogButtonBox.StandardButton.Apply, "btn.apply"),
        ):
            btn = buttons.button(std)
            if btn is not None:
                btn.setText(t(key))
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_button is not None:
            apply_button.clicked.connect(self._emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(12)
        layout.addLayout(self._title_bar())
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    # --- chrome ---

    def _title_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        title = QLabel(t("settings.title"))
        title.setStyleSheet("font-size: 15px; font-weight: 600; color: #FFFFFF;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(_CLOSE_STYLE)
        close_btn.clicked.connect(self.reject)
        bar.addWidget(title)
        bar.addStretch(1)
        bar.addWidget(close_btn)
        return bar

    def paintEvent(self, a0: QPaintEvent | None) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(18, 20, 26, 236))
        painter.setPen(QPen(QColor(255, 255, 255, 28)))
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.drawRoundedRect(rect, 14.0, 14.0)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        # Wayland forbids client-side move(); use the compositor's system move.
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                a0.accept()
                return
        super().mousePressEvent(a0)

    # --- tabs ---

    def _general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self._ui_language = QComboBox()
        for value, label in UI_LANGUAGES:
            self._ui_language.addItem(label, value)
        idx = self._ui_language.findData(self._config.ui_language)
        self._ui_language.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(t("set.language"), self._ui_language)
        form.addRow(self._hint(t("set.language_hint")))
        return page

    def _appearance_tab(self) -> QWidget:
        c = self._config
        page = QWidget()
        form = QFormLayout(page)

        self._icon_list = QListWidget()
        self._icon_list.setObjectName("iconPicker")
        self._icon_list.setViewMode(QListView.ViewMode.IconMode)
        self._icon_list.setFlow(QListView.Flow.LeftToRight)
        self._icon_list.setMovement(QListView.Movement.Static)
        self._icon_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._icon_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._icon_list.setWrapping(True)
        self._icon_list.setIconSize(QSize(42, 42))
        self._icon_list.setGridSize(QSize(56, 56))
        self._icon_list.setFixedHeight(68)
        self._icon_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        selected_item: QListWidgetItem | None = None
        default_item: QListWidgetItem | None = None
        for choice in discover_icon_paths():
            icon = QIcon(str(choice.path))
            if icon.isNull():
                continue
            item = QListWidgetItem(icon, "")
            item.setData(Qt.ItemDataRole.UserRole, choice.key)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._icon_list.addItem(item)
            if choice.key == c.icon_name:
                selected_item = item
            if choice.key == DEFAULT_ICON_NAME:
                default_item = item
        self._icon_list.setCurrentItem(selected_item or default_item)
        form.addRow(t("set.app_icon"), self._icon_list)

        self._font_size = self._spin(8, 120, c.font_size, " px")
        form.addRow(t("set.font_size"), self._font_size)

        self._opacity = self._spin(30, 100, int(round(c.opacity * 100)), " %")
        form.addRow(t("set.opacity"), self._opacity)

        self._panel = QComboBox()
        self._panel.addItem(t("set.panel.pill"), "pill")
        self._panel.addItem(t("set.panel.text"), "text")
        self._panel.setCurrentIndex(0 if c.panel_style == "pill" else 1)
        form.addRow(t("set.panel_style"), self._panel)

        self._accent = QComboBox()
        matched = False
        for key, start, end, sweep in ACCENT_PRESETS:
            self._accent.addItem(t(f"accent.{key}"), (start, end, sweep))
            if start.lower() == c.accent_start.lower():
                self._accent.setCurrentIndex(self._accent.count() - 1)
                matched = True
        if not matched:
            self._accent.addItem(t("set.accent.custom"), (c.accent_start, c.accent_end, c.accent_sweep))
            self._accent.setCurrentIndex(self._accent.count() - 1)
        form.addRow(t("set.accent"), self._accent)
        return page

    def _lyrics_tab(self) -> QWidget:
        c = self._config
        page = QWidget()
        form = QFormLayout(page)

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
        return page

    def _position_tab(self) -> QWidget:
        c = self._config
        page = QWidget()
        form = QFormLayout(page)

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

    def _connection_tab(self) -> QWidget:
        c = self._config
        page = QWidget()
        form = QFormLayout(page)

        self._port = self._spin(1, 65535, c.port, "")
        self._port.setGroupSeparatorShown(False)
        form.addRow(t("set.port"), self._port)
        form.addRow(self._hint(t("set.port_hint")))
        return page

    # --- helpers ---

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: rgba(255,255,255,120);")
        return label

    def _spin(self, low: int, high: int, value: int, suffix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    def current_config(self) -> Config:
        accent_start, accent_end, accent_sweep = self._accent.currentData()
        icon_item = self._icon_list.currentItem()
        icon_name = (
            str(icon_item.data(Qt.ItemDataRole.UserRole))
            if icon_item is not None
            else DEFAULT_ICON_NAME
        )
        return replace(
            self._config,
            ui_language=str(self._ui_language.currentData()),
            icon_name=icon_name,
            font_size=self._font_size.value(),
            opacity=self._opacity.value() / 100.0,
            panel_style=str(self._panel.currentData()),
            accent_start=accent_start,
            accent_end=accent_end,
            accent_sweep=accent_sweep,
            karaoke=self._karaoke.isChecked(),
            lead_ms=self._lead.value(),
            show_translation=self._translation.isChecked(),
            anchor_top=bool(self._anchor.currentData()),
            margin_edge=self._margin_edge.value(),
            margin_x=self._margin_x.value(),
            passthrough=self._passthrough.isChecked(),
            port=self._port.value(),
            lyrics_sources=self._selected_sources(),
            cache_enabled=self._cache_enabled.isChecked(),
        ).clamped()

    def _emit(self) -> None:
        self._config = self.current_config()
        # Re-skin the dialog itself so an accent change is visible right away
        # (tab underline, checkbox fill, list selection) rather than only after
        # Settings is closed and reopened.
        self.setStyleSheet(_skin(self._config.accent_start))
        self.applied.emit(self._config)

    def _accept(self) -> None:
        self._emit()
        self.accept()
