"""Behavioral coverage for fixed-width lyric wrapping."""


from kotonoha.config import Config, PanelOverflowMode, PanelWidthMode
from kotonoha.ui.settings.dialog import SettingsDialog
from kotonoha.ui.settings.form_state import SettingsFormState


def test_overflow_config_validation_roundtrip_and_reset():
    assert Config.from_dict({}).panel_overflow_mode is PanelOverflowMode.SCROLL
    assert Config.from_dict({"panel_overflow_mode": "bad"}).panel_overflow_mode is PanelOverflowMode.SCROLL
    config = Config(panel_overflow_mode=PanelOverflowMode.WRAP)
    assert Config.from_dict(config.to_dict()).panel_overflow_mode is PanelOverflowMode.WRAP
    state = SettingsFormState(Config())
    state.replace(config)
    assert "panel_overflow_mode" in state.changed_fields()
    state.mark_applied()
    assert not state.changed_fields()
    assert state.reset_page(3).panel_overflow_mode is PanelOverflowMode.SCROLL


def test_settings_preserve_wrapping_while_fit_mode_disables_it(_session_qapp):
    dialog = SettingsDialog(Config(panel_width_mode=PanelWidthMode.FIXED))
    controls = dialog.form_widgets
    assert controls.panel_overflow_mode.isEnabled()
    controls.panel_overflow_mode.setCurrentIndex(controls.panel_overflow_mode.findData("wrap"))
    assert dialog.current_config().panel_overflow_mode is PanelOverflowMode.WRAP
    controls.panel_width_mode.setCurrentIndex(controls.panel_width_mode.findData("fit"))
    assert not controls.panel_overflow_mode.isEnabled()
    assert dialog.current_config().panel_overflow_mode is PanelOverflowMode.WRAP
    controls.panel_width_mode.setCurrentIndex(controls.panel_width_mode.findData("fixed"))
    assert controls.panel_overflow_mode.isEnabled()
    dialog.close()
