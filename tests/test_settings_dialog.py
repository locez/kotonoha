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


def test_frost_only_on_kwin_wayland_and_blur_lifecycle_is_safe(qapp):
    # Frost is gated to KDE Wayland; the offscreen test platform is not Wayland, so
    # the window stays a solid panel. The blur lifecycle (apply on show, re-apply on
    # resize, clear on hide) must be a sequence of safe no-ops that never raise.
    dialog = SettingsDialog(Config())
    assert dialog._frosted is False  # offscreen platform is not "wayland"
    dialog._apply_blur()
    dialog.show()
    qapp.processEvents()
    dialog.resize(dialog.width() + 20, dialog.height())
    qapp.processEvents()
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_frost_window_toggle_roundtrips_and_applies_safely(qapp):
    dialog = SettingsDialog(Config(frost_window=False))
    assert dialog._frost_window.isChecked() is False
    dialog._frost_window.setChecked(True)
    assert dialog.current_config().frost_window is True
    dialog._emit()  # applying the toggle must not raise (blur is a no-op in headless)
    dialog.close()


def test_content_sits_in_a_raised_card_and_page_switch_is_safe(qapp):
    from PyQt6.QtWidgets import QWidget

    # Depth: the content lives in a distinct "card" surface layered over the base.
    dialog = SettingsDialog(Config(fx_animate=False))
    assert dialog.findChild(QWidget, "contentCard") is not None
    # Switching category updates the stack, and with animations off no graphics
    # effect is left on the page (it can never be stuck dim/blank).
    dialog._nav.setCurrentRow(2)
    assert dialog._stack.currentIndex() == 2
    assert dialog._stack.currentWidget().graphicsEffect() is None
    dialog.close()


def test_title_logo_follows_the_accent(qapp):
    from kotonoha.settings_dialog import _accent_logo

    red = _accent_logo("#FF0000", 22)
    green = _accent_logo("#00FF00", 22)
    assert red is not None and green is not None
    assert not red.isNull() and not green.isNull()
    assert red.toImage() != green.toImage()  # the leaf recolours to the accent
    # The title badge re-tints on Apply when the accent changes.
    dialog = SettingsDialog(Config(accent_start="#FF4FA3"))
    before = dialog._logo_badge.pixmap().toImage()
    cyan = next(
        i for i in range(dialog._accent.count())
        if dialog._accent.itemData(i) == ("#4FACFE", "#00F2FE", "#38E1FF")
    )
    dialog._accent.setCurrentIndex(cyan)
    dialog._emit()
    assert dialog._logo_badge.pixmap().toImage() != before
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


def test_connection_section_removed_but_port_preserved(qapp):
    # The WS-port control was dropped; the sidebar no longer lists Connection,
    # and current_config keeps the config's port untouched (still used by the CLI).
    dialog = SettingsDialog(Config(port=41234))
    labels = [dialog._nav.item(i).text() for i in range(dialog._nav.count())]
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


def test_sidebar_lists_every_section_and_drives_the_stack(qapp):
    from kotonoha.strings import current_language, set_language

    previous = current_language()
    set_language("en")
    try:
        dialog = SettingsDialog(Config(ui_language="en"))
        dialog.show()
        qapp.processEvents()
        qapp.processEvents()
        # One sidebar row per content page, and no label is truncated in the sidebar.
        assert dialog._nav.count() == dialog._stack.count() == 7
        assert dialog._nav.width() >= dialog._nav.sizeHintForColumn(0)
        # Selecting a sidebar row switches the stacked content page.
        dialog._nav.setCurrentRow(3)
        assert dialog._stack.currentIndex() == 3
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


def test_icon_picker_includes_generated_leaf_styles(qapp):
    from kotonoha import leaf_icon

    dialog = SettingsDialog(Config(icon_name=leaf_icon.TILE))
    keys = [
        str(dialog._icon_list.item(i).data(Qt.ItemDataRole.UserRole))
        for i in range(dialog._icon_list.count())
    ]
    for style in leaf_icon.GENERATED:  # accent / mono / tile are offered
        assert style in keys
    assert "leaf-pink.svg" in keys  # the bundled files are still offered too
    assert dialog.current_config().icon_name == leaf_icon.TILE
    dialog.close()


def test_selected_icon_is_not_blue_tinted(qapp):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    dialog = SettingsDialog(Config())
    item = dialog._icon_list.item(0)
    assert item is not None
    icon = item.icon()
    size = QSize(48, 48)
    normal = icon.pixmap(size, QIcon.Mode.Normal).toImage()
    selected = icon.pixmap(size, QIcon.Mode.Selected).toImage()
    # The Selected mode reuses the Normal pixmap, so Qt applies no blue highlight
    # tint over the chosen icon — the accent ring alone marks the selection.
    assert not normal.isNull()
    assert selected == normal
    dialog.close()


def test_effects_controls_roundtrip(qapp):
    dialog = SettingsDialog(Config(fx_animate=False, fx_glow=True, fx_word_pop=False, fx_intensity="expressive"))
    assert dialog._fx_animate.isChecked() is False
    assert dialog._fx_glow.isChecked() is True
    assert dialog._fx_word_pop.isChecked() is False
    assert dialog._fx_intensity.currentData() == "expressive"
    dialog._fx_glow.setChecked(False)
    dialog._fx_word_pop.setChecked(True)
    cfg = dialog.current_config()
    assert cfg.fx_animate is False
    assert cfg.fx_glow is False
    assert cfg.fx_word_pop is True
    assert cfg.fx_intensity == "expressive"
    dialog.close()


def test_max_font_sizes_survive_opening_settings(qapp):
    # With the spin range aligned to the config clamp, a config already at the max
    # is not truncated merely by opening the dialog and reading it back.
    dialog = SettingsDialog(Config(font_size=120, context_font_size=120, translation_font_size=120))
    cfg = dialog.current_config()
    assert (cfg.font_size, cfg.context_font_size, cfg.translation_font_size) == (120, 120, 120)
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
