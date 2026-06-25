"""Tabbed settings panel.

Edits a working copy of :class:`~kotonoha.config.Config` across grouped tabs and
emits ``applied`` with the new config when the user applies/accepts. Persistence
and live re-styling are the caller's responsibility (see controller.py). UI
strings come from :mod:`kotonoha.strings`.
"""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import ACCENT_PRESETS, VALID_LYRICS_SOURCES, Config
from .strings import UI_LANGUAGES, t


class SettingsDialog(QDialog):
    applied = pyqtSignal(object)  # emits Config

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle(t("settings.title"))
        self.setMinimumWidth(420)

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
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_button is not None:
            apply_button.clicked.connect(self._emit)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

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
        for label, start, end, sweep in ACCENT_PRESETS:
            self._accent.addItem(label, (start, end, sweep))
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
        label.setStyleSheet("color: gray;")
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
        return replace(
            self._config,
            ui_language=str(self._ui_language.currentData()),
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
        ).clamped()

    def _emit(self) -> None:
        self._config = self.current_config()
        self.applied.emit(self._config)

    def _accept(self) -> None:
        self._emit()
        self.accept()
