import os
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QListWidgetItem

from kotonoha.config import Config
from kotonoha.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_cache_controls_roundtrip_and_clear_signal(qapp):
    dialog = SettingsDialog(Config(cache_enabled=False))
    emitted = []
    dialog.clear_cache_requested.connect(lambda: emitted.append(True))

    assert dialog._cache_enabled.isChecked() is False
    dialog._cache_enabled.setChecked(True)
    assert dialog.current_config().cache_enabled is True
    dialog._clear_cache.click()
    assert emitted == [True]
    dialog.close()


def _indicator_white_pixels(qss: str, *, checked: bool) -> int:
    from PyQt6.QtWidgets import QCheckBox

    cb = QCheckBox("x")
    cb.setChecked(checked)
    # Dark surround so the only near-white pixels in the indicator area come from
    # the checkmark glyph itself (the checked background is the purple accent).
    cb.setStyleSheet(qss + "\nQCheckBox { background: #101216; }")
    cb.resize(120, 24)
    image = cb.grab().toImage()
    count = 0
    for y in range(image.height()):
        for x in range(min(20, image.width())):
            colour = image.pixelColor(x, y)
            if colour.red() > 200 and colour.green() > 200 and colour.blue() > 200:
                count += 1
    return count


def test_checked_indicator_actually_renders_a_checkmark(qapp):
    from kotonoha.settings_dialog import _CHECKMARK_PATH, _skin

    # The glyph must be a real bundled file: Qt's stylesheet url() does not decode
    # data: URIs, so an inline data URI renders nothing (a bare filled square).
    assert _CHECKMARK_PATH.is_file()
    qss = _skin(Config().accent_start)
    # A checked box draws a white tick the unchecked one lacks.
    assert _indicator_white_pixels(qss, checked=True) > _indicator_white_pixels(qss, checked=False)


def test_apply_reskins_dialog_with_new_accent(qapp):
    dialog = SettingsDialog(Config(accent_start="#FF4FA3"))
    assert "#FF4FA3" in dialog.styleSheet()
    cyan_index = next(
        i for i in range(dialog._accent.count())
        if dialog._accent.itemData(i) == ("#4FACFE", "#00F2FE", "#38E1FF")
    )
    dialog._accent.setCurrentIndex(cyan_index)
    dialog._emit()
    assert "#4FACFE" in dialog.styleSheet()
    dialog.close()


def test_accent_has_custom_picker_and_panel_tint_roundtrips(qapp):
    dialog = SettingsDialog(Config(panel_accent_tint=True))
    # A trailing "Custom…" picker entry (data None) is present.
    assert any(dialog._accent.itemData(i) is None for i in range(dialog._accent.count()))
    assert dialog._panel_tint.isChecked() is True
    assert dialog.current_config().panel_accent_tint is True
    dialog.close()


def test_custom_accent_slot_is_reused_not_accumulated(qapp):
    dialog = SettingsDialog(Config())
    before = dialog._accent.count()
    dialog._set_custom_accent(("#123456", "#223344", "#334455"))
    after_first = dialog._accent.count()
    dialog._set_custom_accent(("#654321", "#556677", "#778899"))
    assert after_first == before + 1  # one slot added
    assert dialog._accent.count() == after_first  # reused, not piling up "自訂" entries
    assert dialog._accent.currentData() == ("#654321", "#556677", "#778899")
    assert "#654321".upper() in dialog._accent.currentText()  # labelled with its hex
    dialog.close()


def test_opacity_is_independent_per_panel_style(qapp):
    dialog = SettingsDialog(Config(panel_style="pill", opacity=1.0, frost_opacity=0.4))
    assert dialog._opacity.value() == 100  # shows the black panel's opacity
    dialog._panel.setCurrentIndex(dialog._panel.findData("frost"))
    assert dialog._opacity.value() == 40  # switches to the frosted panel's opacity
    dialog._opacity.setValue(70)
    dialog._panel.setCurrentIndex(dialog._panel.findData("pill"))
    assert dialog._opacity.value() == 100  # black opacity preserved across the switch
    cfg = dialog.current_config()
    assert cfg.opacity == 1.0
    assert cfg.frost_opacity == 0.70  # the frosted change was kept separately
    dialog.close()


def test_panel_style_has_frosted_option_and_roundtrips(qapp):
    dialog = SettingsDialog(Config(panel_style="frost"))
    assert dialog._panel.count() == 4  # black / white / frosted / text
    assert dialog._panel.currentData() == "frost"  # selected by data, not index
    assert dialog.current_config().panel_style == "frost"
    dialog.close()


def test_white_panel_option_present_and_roundtrips(qapp):
    dialog = SettingsDialog(Config(panel_style="white"))
    assert dialog._panel.findData("white") >= 0
    assert dialog._panel.currentData() == "white"
    assert dialog.current_config().panel_style == "white"
    dialog.close()


def test_theme_selector_roundtrips_and_switches_palette(qapp):
    from kotonoha.settings_dialog import _PALETTES

    dark = SettingsDialog(Config(theme="dark"))
    assert dark._theme == "dark"
    assert _PALETTES["dark"]["TEXT"] in dark.styleSheet()
    assert dark.current_config().theme == "dark"

    light = SettingsDialog(Config(theme="light"))
    assert light._theme == "light"
    assert _PALETTES["light"]["TEXT"] in light.styleSheet()
    # Switching theme on Apply re-skins the dialog live.
    light._theme_combo.setCurrentIndex(light._theme_combo.findData("dark"))
    light._emit()
    assert light._theme == "dark"
    assert _PALETTES["dark"]["TEXT"] in light.styleSheet()
    dark.close()
    light.close()


def test_connection_tab_removed_but_port_preserved(qapp):
    # The WS-port control was dropped; the tab set no longer includes Connection,
    # and current_config keeps the config's port untouched (still used by the CLI).
    dialog = SettingsDialog(Config(port=41234))
    labels = [dialog._tabs.tabText(i) for i in range(dialog._tabs.count())]
    assert not any("onnect" in label or "连接" in label or "連接" in label or "接続" in label for label in labels)
    assert not hasattr(dialog, "_port")
    assert dialog.current_config().port == 41234  # preserved from the config
    dialog.close()


def test_typography_controls_roundtrip(qapp):
    dialog = SettingsDialog(Config(
        font_family="DejaVu Sans", font_weight=600,
        context_font_size=17, translation_font_size=11,
    ))
    assert dialog._context_font_size.value() == 17
    assert dialog._translation_font_size.value() == 11
    # The weight picker offers at least one weight; selecting one round-trips.
    assert dialog._font_weight.count() >= 1
    last = dialog._font_weight.count() - 1
    dialog._font_weight.setCurrentIndex(last)
    chosen = dialog._font_weight.itemData(last)
    cfg = dialog.current_config()
    assert cfg.font_weight == chosen
    assert cfg.context_font_size == 17
    assert cfg.translation_font_size == 11
    assert cfg.font_family  # a concrete family is stored (QFontComboBox resolves it)
    dialog.close()


def test_weight_picker_lists_only_the_fonts_real_weights(qapp):
    from PyQt6.QtGui import QFontDatabase

    from kotonoha.settings_dialog import _FALLBACK_WEIGHTS

    dialog = SettingsDialog(Config())
    # A family with no reported styles falls back to the standard weight ladder,
    # so the user is never left with an empty picker.
    assert dialog._available_weights("___no_such_font___") == list(_FALLBACK_WEIGHTS)
    # A family that DOES report styles is offered exactly its own weights (a subset
    # of the standard ladder) — never a weight Qt would have to synthesize.
    for family in QFontDatabase.families():
        styles = QFontDatabase.styles(family)
        if styles:
            real = sorted({QFontDatabase.weight(family, s) for s in styles} - {0})
            assert dialog._available_weights(family) == real
            break
    dialog.close()


def test_weight_label_names_standard_and_off_ladder_weights(qapp):
    dialog = SettingsDialog(Config())
    assert dialog._weight_label(700)  # a standard weight -> a plain name
    labelled = dialog._weight_label(316)  # DemiLight-ish -> nearest name + the value
    assert "316" in labelled
    dialog.close()


def test_panel_width_control_enabled_only_for_fixed_mode(qapp):
    dialog = SettingsDialog(Config(panel_width_mode="fixed", panel_width=820))
    assert dialog._panel_width.isEnabled() is True
    assert dialog.current_config().panel_width == 820
    # Switching to fit-to-text disables the width value (it no longer applies).
    dialog._panel_width_mode.setCurrentIndex(dialog._panel_width_mode.findData("fit"))
    assert dialog._panel_width.isEnabled() is False
    assert dialog.current_config().panel_width_mode == "fit"
    dialog.close()


def test_all_tabs_fit_without_scroll_arrows(qapp):
    from PyQt6.QtWidgets import QToolButton

    from kotonoha.strings import current_language, set_language

    previous = current_language()
    set_language("en")  # widest labels -> worst case for fitting the tab row
    try:
        dialog = SettingsDialog(Config(ui_language="en"))
        dialog.show()
        qapp.processEvents()
        qapp.processEvents()
        tab_bar = dialog._tabs.tabBar()
        assert dialog._tabs.usesScrollButtons() is False
        assert tab_bar.sizeHint().width() <= dialog._tabs.width()  # every tab fits
        assert not any(b.isVisible() for b in tab_bar.findChildren(QToolButton))
        dialog.close()
    finally:
        set_language(previous)
    qapp.processEvents()


def test_language_change_reveals_restart_button_and_persists(qapp):
    dialog = SettingsDialog(Config(ui_language="auto"))
    assert dialog._restart_btn.isHidden() is True  # nothing changed yet

    dialog._ui_language.setCurrentIndex(dialog._ui_language.findData("ja"))
    assert dialog._restart_btn.isHidden() is False  # a different language -> offer restart

    restarts: list[bool] = []
    applied: list[Config] = []
    dialog.restart_requested.connect(lambda: restarts.append(True))
    dialog.applied.connect(applied.append)
    dialog._restart_btn.click()

    assert restarts == [True]
    assert applied and applied[-1].ui_language == "ja"  # persisted before relaunch

    # Reverting to the running language hides it again.
    dialog._ui_language.setCurrentIndex(dialog._ui_language.findData("auto"))
    assert dialog._restart_btn.isHidden() is True
    dialog.close()


def test_icon_picker_shows_preview_only_and_updates_config(qapp):
    dialog = SettingsDialog(Config(icon_name="leaf-pink.svg"))

    items = [
        cast(QListWidgetItem, dialog._icon_list.item(index))
        for index in range(dialog._icon_list.count())
    ]
    keys = [str(item.data(Qt.ItemDataRole.UserRole)) for item in items]
    assert keys[dialog._icon_list.currentRow()] == "leaf-pink.svg"
    assert all(item.text() == "" for item in items)
    assert "leaf-green.svg" in keys

    dialog._icon_list.setCurrentRow(keys.index("leaf-green.svg"))

    assert dialog.current_config().icon_name == "leaf-green.svg"
    dialog.close()
