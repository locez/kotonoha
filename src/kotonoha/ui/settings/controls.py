"""Explicit Qt controls owned by one settings form instance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PyQt6.QtWidgets import (
    QCheckBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
)

from .widgets import IconStrip, SettingsComboBox, SettingsFontComboBox

IconPicker = tuple[IconStrip, dict[str, QListWidgetItem]]
OpacityKey = Literal["opacity", "frost_opacity"]


@dataclass
class PanelOpacityState:
    """Keep the independent opacity values for the two panel styles."""

    opacity: float = 0.0
    frost_opacity: float = 0.0

    def value_for(self, key: OpacityKey) -> float:
        """Return the value represented by one panel-style selector."""
        if key == "opacity":
            return self.opacity
        return self.frost_opacity

    def set_value(self, key: OpacityKey, value: float) -> None:
        """Update the value represented by one panel-style selector."""
        if key == "opacity":
            self.opacity = value
        else:
            self.frost_opacity = value


class SettingsWidgets:
    """Own every mutable Qt control and UI-only form value for one dialog.

    Page builders receive this object explicitly. The dialog never needs to
    discover controls dynamically, and page rebuilds can reuse the same typed
    control set without creating a second source of staged configuration.
    """

    def __init__(self) -> None:
        self.ui_language = SettingsComboBox()
        self.theme_combo = SettingsComboBox()
        self.frost_window = QCheckBox()
        self.settings_opacity = QSpinBox()
        self.restart_button = QPushButton()

        self.tray_icon_list = IconStrip()
        self.window_icon_list = IconStrip()
        self.icon_pickers: list[IconPicker] = []

        self.font_family = SettingsFontComboBox()
        self.font_style = SettingsComboBox()
        self.font_style_configured = ""
        self.font_style_user_changed = False
        self.font_family_shown = ""
        self.font_family_configured = ""
        self.font_size = QSpinBox()
        self.context_font_size = QSpinBox()
        self.translation_font_size = QSpinBox()

        self.panel = SettingsComboBox()
        self.panel_width_mode = SettingsComboBox()
        self.panel_width = QSpinBox()
        self.panel_overflow_mode: SettingsComboBox = SettingsComboBox()
        self.panel_opacity = PanelOpacityState()
        self.opacity_active_key: OpacityKey = "opacity"
        self.opacity = QSpinBox()
        self.panel_tint = QCheckBox()

        self.accent = SettingsComboBox()
        self.custom_index = -1
        self.accent_last_index = -1
        self.fx_animate = QCheckBox()
        self.fx_transition = SettingsComboBox()
        self.fx_glow = QCheckBox()
        self.fx_word_pop = QCheckBox()
        self.fx_intensity = SettingsComboBox()

        self.karaoke = QCheckBox()
        self.lead = QSpinBox()
        self.translation = QCheckBox()
        self.current_line_only = QCheckBox()
        self.lyrics_script = SettingsComboBox()
        self.interlude_style = SettingsComboBox()
        self.interlude_countdown = SettingsComboBox()

        self.anchor = SettingsComboBox()
        self.margin_edge = QSpinBox()
        self.margin_x = QSpinBox()
        self.passthrough = QCheckBox()

        self.player_combo = SettingsComboBox()
        self.sources_list = QListWidget()
        self.display_sources_list = QListWidget()
        self.prefer_best = QCheckBox()
        self.fuzzy_match = QCheckBox()
        self.cache_enabled = QCheckBox()
        self.manage_cache = QPushButton()
        self.cider_token = QLineEdit()
        self.clear_cache = QPushButton()


__all__ = ["IconPicker", "OpacityKey", "PanelOpacityState", "SettingsWidgets"]
