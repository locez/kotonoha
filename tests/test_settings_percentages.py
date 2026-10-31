"""User interaction and apply/reset contracts for percentage sliders."""

from __future__ import annotations

from typing import Literal

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionSlider

from kotonoha.app.config_merge import merge_settings
from kotonoha.app.intents import ApplyConfig, SettingsIntent
from kotonoha.config import Config, PanelStyle
from kotonoha.ui.settings.dialog import SettingsDialog


@pytest.mark.parametrize("field", ["settings_opacity", "opacity", "context_blur"])
def test_percentage_drag_keyboard_and_entry_share_one_value(
    qapp: QApplication, field: Literal["settings_opacity", "opacity", "context_blur"],
) -> None:
    """Dragging, arrow keys, and typed percentages all reach the submitted setting."""
    dialog = SettingsDialog(Config())
    try:
        controls = {
            "settings_opacity": (dialog.form_widgets.settings_opacity, 0),
            "opacity": (dialog.form_widgets.opacity, 3),
            "context_blur": (dialog.form_widgets.context_blur, 5),
        }
        control, page = controls[field]
        dialog._nav.setCurrentRow(page)
        dialog.show()
        control.value = 25
        qapp.processEvents()
        slider = control.slider
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        style = slider.style()
        assert style is not None
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider,
        ).center()
        destination = slider.rect().center()
        for kind, position, button, buttons in (
            (QEvent.Type.MouseButtonPress, handle, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseMove, destination, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseButtonRelease, destination, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(slider, QMouseEvent(
                kind, QPointF(position), QPointF(slider.mapToGlobal(position)),
                button, buttons, Qt.KeyboardModifier.NoModifier,
            ))
        assert control.value > 25
        assert control.number.value() == control.value
        for key, expected in ((Qt.Key.Key_End, 100), (Qt.Key.Key_Left, 99)):
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QApplication.sendEvent(slider, QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier))
            assert control.value == control.number.value() == expected

        editor = control.number.lineEdit()
        assert editor is not None
        editor.setText("37 %")
        control.number.interpretText()
        assert control.value == slider.value() == 37
        current = dialog.current_config()
        submitted = {
            "settings_opacity": current.settings_opacity,
            "opacity": current.opacity,
            "context_blur": current.context_blur,
        }
        assert submitted[field] == 0.37
    finally:
        dialog.close()


def test_blur_apply_and_page_reset_preserve_other_settings(qapp: QApplication) -> None:
    """Blur is staged, emitted and merged; a Lyrics reset restores only that page."""
    baseline = Config(context_lines=3, context_blur=0.25, settings_opacity=0.7)
    dialog = SettingsDialog(baseline)
    intents: list[SettingsIntent] = []
    dialog.intent_requested.connect(intents.append)
    try:
        dialog.form_widgets.context_blur.slider.setValue(68)
        dialog.form_widgets.context_lines.setValue(0)
        assert baseline.context_blur == 0.25
        assert not dialog.form_widgets.context_blur.isEnabled()
        assert dialog.current_config().context_blur == 0.68
        dialog._emit()
        intent = intents[-1]
        assert isinstance(intent, ApplyConfig)
        assert intent.changed_fields == frozenset({"context_blur", "context_lines"})
        merged = merge_settings(baseline, intent.config, intent.changed_fields)
        assert merged.context_blur == 0.68 and merged.context_lines == 0
        assert merged.settings_opacity == 0.7

        dialog._nav.setCurrentRow(5)
        dialog._reset_current_page()
        dialog._reset_current_page()
        assert dialog.form_widgets.context_blur.isEnabled()
        assert dialog.current_config().context_blur == 0.0
        assert dialog.current_config().context_lines == 1
        assert dialog.current_config().settings_opacity == 0.7
    finally:
        dialog.close()


def test_panel_sliders_keep_independent_values_across_style_switches(qapp: QApplication) -> None:
    """Switching the panel style restores both slider and precise percentage."""
    dialog = SettingsDialog(Config(panel_style=PanelStyle.PILL, opacity=0.8, frost_opacity=0.4))
    try:
        widgets = dialog.form_widgets
        widgets.opacity.slider.setValue(23)
        widgets.panel.setCurrentIndex(widgets.panel.findData(PanelStyle.FROST.value))
        assert widgets.opacity.value == widgets.opacity.number.value() == 40
        widgets.opacity.number.setValue(69)
        widgets.panel.setCurrentIndex(widgets.panel.findData(PanelStyle.PILL.value))
        assert widgets.opacity.value == widgets.opacity.number.value() == 23
        assert dialog.current_config().opacity == 0.23
        assert dialog.current_config().frost_opacity == 0.69
    finally:
        dialog.close()
