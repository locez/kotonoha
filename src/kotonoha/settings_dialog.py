"""Tabbed settings panel.

Edits a working copy of :class:`~kotonoha.config.Config` across grouped tabs and
emits ``applied`` with the new config when the user applies/accepts. Persistence
and live re-styling are the caller's responsibility (see controller.py).
"""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import ACCENT_PRESETS, Config
from .i18n import AUTO, SUPPORTED_LANGUAGES


class SettingsDialog(QDialog):
    applied = pyqtSignal(object)  # emits Config

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Kotonoha 设置")
        self.setMinimumWidth(420)

        tabs = QTabWidget()
        tabs.addTab(self._appearance_tab(), "外观")
        tabs.addTab(self._lyrics_tab(), "歌词")
        tabs.addTab(self._position_tab(), "位置")
        tabs.addTab(self._connection_tab(), "连接")

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

    def _appearance_tab(self) -> QWidget:
        c = self._config
        page = QWidget()
        form = QFormLayout(page)

        self._font_size = self._spin(8, 120, c.font_size, " px")
        form.addRow("当前行字号", self._font_size)

        self._opacity = self._spin(30, 100, int(round(c.opacity * 100)), " %")
        form.addRow("不透明度", self._opacity)

        self._panel = QComboBox()
        self._panel.addItem("玻璃面板", "pill")
        self._panel.addItem("纯文字", "text")
        self._panel.setCurrentIndex(0 if c.panel_style == "pill" else 1)
        form.addRow("背板样式", self._panel)

        self._accent = QComboBox()
        matched = False
        for label, start, end, sweep in ACCENT_PRESETS:
            self._accent.addItem(label, (start, end, sweep))
            if start.lower() == c.accent_start.lower():
                self._accent.setCurrentIndex(self._accent.count() - 1)
                matched = True
        if not matched:
            # Preserve a custom colour set from the config file.
            self._accent.addItem("自定义", (c.accent_start, c.accent_end, c.accent_sweep))
            self._accent.setCurrentIndex(self._accent.count() - 1)
        form.addRow("强调色", self._accent)
        return page

    def _lyrics_tab(self) -> QWidget:
        c = self._config
        page = QWidget()
        form = QFormLayout(page)

        self._karaoke = QCheckBox("逐字卡拉 OK 高亮")
        self._karaoke.setChecked(c.karaoke)
        form.addRow(self._karaoke)

        self._lead = self._spin(-1000, 1000, c.lead_ms, " ms")
        self._lead.setSingleStep(20)
        self._lead.setToolTip("正值让染色提前（补偿延迟），负值让染色滞后")
        form.addRow("歌词提前", self._lead)

        self._translation = QCheckBox("显示翻译（双语）")
        self._translation.setChecked(c.show_translation)
        form.addRow(self._translation)

        self._language = QComboBox()
        self._language.addItem("自动（跟随系统）", AUTO)
        for tag, label in SUPPORTED_LANGUAGES:
            self._language.addItem(label, tag)
        lang_idx = self._language.findData(c.translation_language)
        self._language.setCurrentIndex(lang_idx if lang_idx >= 0 else 0)
        form.addRow("翻译语言", self._language)
        return page

    def _position_tab(self) -> QWidget:
        c = self._config
        page = QWidget()
        form = QFormLayout(page)

        self._anchor = QComboBox()
        self._anchor.addItem("顶部", True)
        self._anchor.addItem("底部", False)
        self._anchor.setCurrentIndex(0 if c.anchor_top else 1)
        form.addRow("位置", self._anchor)

        self._margin_edge = self._spin(0, 4000, c.margin_edge, " px")
        form.addRow("距边缘", self._margin_edge)

        self._margin_x = self._spin(-2000, 2000, c.margin_x, " px")
        form.addRow("水平偏移", self._margin_x)

        self._passthrough = QCheckBox("默认鼠标穿透（锁定）")
        self._passthrough.setChecked(c.passthrough)
        form.addRow(self._passthrough)
        return page

    def _connection_tab(self) -> QWidget:
        c = self._config
        page = QWidget()
        form = QFormLayout(page)

        self._port = self._spin(1, 65535, c.port, "")
        self._port.setGroupSeparatorShown(False)
        form.addRow("WebSocket 端口", self._port)

        note = QLabel("修改端口需重启 Kotonoha 生效，并同步修改 Cider 探针的 endpoint。")
        note.setWordWrap(True)
        form.addRow(note)
        return page

    # --- helpers ---

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
            font_size=self._font_size.value(),
            opacity=self._opacity.value() / 100.0,
            panel_style=str(self._panel.currentData()),
            accent_start=accent_start,
            accent_end=accent_end,
            accent_sweep=accent_sweep,
            karaoke=self._karaoke.isChecked(),
            lead_ms=self._lead.value(),
            show_translation=self._translation.isChecked(),
            translation_language=str(self._language.currentData()),
            anchor_top=bool(self._anchor.currentData()),
            margin_edge=self._margin_edge.value(),
            margin_x=self._margin_x.value(),
            passthrough=self._passthrough.isChecked(),
            port=self._port.value(),
        ).clamped()

    def _emit(self) -> None:
        self._config = self.current_config()
        self.applied.emit(self._config)

    def _accept(self) -> None:
        self._emit()
        self.accept()
