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
    current = dialog._stack.currentWidget()
    assert current is not None
    assert current.graphicsEffect() is None
    dialog.close()


def test_title_logo_follows_the_accent(qapp):
    from kotonoha import leaf_icon

    red = leaf_icon.render_leaf(leaf_icon.ACCENT, "#FF0000", size=22)
    green = leaf_icon.render_leaf(leaf_icon.ACCENT, "#00FF00", size=22)
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
    assert cast(str, _PALETTES["dark"]["TEXT"]) in dark.styleSheet()
    assert dark.current_config().theme == "dark"

    light = SettingsDialog(Config(theme="light"))
    assert light._theme == "light"
    assert cast(str, _PALETTES["light"]["TEXT"]) in light.styleSheet()
    # Switching theme on Apply re-skins the dialog live.
    light._theme_combo.setCurrentIndex(light._theme_combo.findData("dark"))
    light._emit()
    assert light._theme == "dark"
    assert cast(str, _PALETTES["dark"]["TEXT"]) in light.styleSheet()
    dark.close()
    light.close()


def test_connection_section_removed_but_port_preserved(qapp):
    # The WS-port control was dropped; the sidebar no longer lists Connection,
    # and current_config keeps the config's port untouched (still used by the CLI).
    dialog = SettingsDialog(Config(port=41234))
    labels = []
    for i in range(dialog._nav.count()):
        item = dialog._nav.item(i)
        assert item is not None
        labels.append(item.text())
    assert not any("onnect" in label or "连接" in label or "連接" in label or "接続" in label for label in labels)
    assert not hasattr(dialog, "_port")
    assert dialog.current_config().port == 41234  # preserved from the config
    dialog.close()


def test_font_picker_is_a_dropdown_not_a_text_box(qapp):
    # Clicking the field should open the font list, not put a text cursor there.
    dialog = SettingsDialog(Config())
    assert dialog._font_family.isEditable() is False
    dialog.close()


def test_typography_controls_roundtrip(qapp):
    # KDE-style: a Family picker + a Style picker (Regular/Bold/…), no numeric weight.
    dialog = SettingsDialog(Config(
        font_family="DejaVu Sans", context_font_size=17, translation_font_size=11,
    ))
    assert dialog._context_font_size.value() == 17
    assert dialog._translation_font_size.value() == 11
    assert not hasattr(dialog, "_font_weight")  # the numeric weight picker is gone
    assert dialog._font_style.count() >= 1  # the style picker always offers something
    assert dialog._font_family.isEditable() is False  # a dropdown, never a text box
    cfg = dialog.current_config()
    assert cfg.context_font_size == 17
    assert cfg.translation_font_size == 11
    assert cfg.font_family  # a concrete family is stored
    assert cfg.font_style  # a concrete style is stored
    dialog.close()


def test_style_picker_lists_the_familys_real_styles(qapp):
    from PyQt6.QtGui import QFontDatabase

    dialog = SettingsDialog(Config())
    # A family with no reported styles still offers a usable default.
    assert dialog._available_styles("___no_such_font___") == ["Regular"]
    # A family that reports styles offers exactly those (Regular sorted first).
    for family in QFontDatabase.families():
        styles = QFontDatabase.styles(family)
        if styles:
            offered = dialog._available_styles(family)
            assert set(offered) == set(styles)
            if "Regular" in styles:
                assert offered[0] == "Regular"
            break
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
        assert dialog._nav.count() == dialog._stack.count() == 8
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
    keys = []
    for i in range(dialog._tray_icon_list.count()):
        item = dialog._tray_icon_list.item(i)
        assert item is not None
        keys.append(str(item.data(Qt.ItemDataRole.UserRole)))
    for style in leaf_icon.PICKER_STYLES:  # accent / white / black / tile are offered
        assert style in keys
    assert leaf_icon.WHITE in keys and leaf_icon.BLACK in keys  # explicit monochromes
    assert "leaf-pink.svg" in keys  # the bundled files are still offered too
    assert dialog.current_config().icon_name == leaf_icon.TILE
    dialog.close()


def test_legacy_mono_icon_stays_selectable_and_is_not_reset(qapp):
    from kotonoha import leaf_icon

    # A config saved before white/black existed uses the adaptive "@leaf-mono", which
    # the picker no longer offers by default. It must still show + stay selected, so
    # Apply preserves it instead of silently resetting to the default icon.
    dialog = SettingsDialog(Config(icon_name=leaf_icon.MONO))
    assert dialog._picked_icon(dialog._tray_icon_list) == leaf_icon.MONO
    assert dialog.current_config().icon_name == leaf_icon.MONO
    dialog.close()


def test_tray_and_window_icons_are_chosen_independently(qapp):
    from kotonoha import leaf_icon

    dialog = SettingsDialog(Config(icon_name=leaf_icon.WHITE, window_icon_name=leaf_icon.TILE))
    # Each picker starts on its own saved style, not a shared one.
    assert dialog._picked_icon(dialog._tray_icon_list) == leaf_icon.WHITE
    assert dialog._picked_icon(dialog._window_icon_list) == leaf_icon.TILE
    # Changing one does not move the other.
    window_keys = []
    for i in range(dialog._window_icon_list.count()):
        item = dialog._window_icon_list.item(i)
        assert item is not None
        window_keys.append(str(item.data(Qt.ItemDataRole.UserRole)))
    dialog._window_icon_list.setCurrentRow(window_keys.index(leaf_icon.BLACK))
    cfg = dialog.current_config()
    assert cfg.icon_name == leaf_icon.WHITE
    assert cfg.window_icon_name == leaf_icon.BLACK
    dialog.close()


def test_reset_tab_restores_only_current_page(qapp):
    dialog = SettingsDialog(
        Config(font_size=90, context_font_size=80, margin_edge=999, karaoke=False)
    )
    dialog._nav.setCurrentRow(2)  # Text page (0 General, 1 Icon, 2 Text)
    dialog._reset_current_page()
    cfg = dialog.current_config()
    defaults = Config()
    # Text fields reset...
    assert cfg.font_size == defaults.font_size
    assert cfg.context_font_size == defaults.context_font_size
    # ...but other pages' edits are untouched.
    assert cfg.margin_edge == 999
    assert cfg.karaoke is False
    dialog.close()


def test_reset_icon_tab_rebuilds_icon_pickers_without_doubling(qapp):
    from kotonoha import leaf_icon

    dialog = SettingsDialog(
        Config(icon_name=leaf_icon.WHITE, window_icon_name=leaf_icon.BLACK, theme="light")
    )
    dialog._nav.setCurrentRow(1)  # Icon page owns the two icon strips
    dialog._reset_current_page()
    cfg = dialog.current_config()
    defaults = Config()
    assert cfg.icon_name == defaults.icon_name
    assert cfg.window_icon_name == defaults.window_icon_name
    assert cfg.theme == "light"  # a different tab's edit is untouched by the Icon reset
    # The strips were rebuilt, not appended a second time.
    assert len(dialog._icon_pickers) == 2
    dialog.close()


def test_selected_icon_is_not_blue_tinted(qapp):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    dialog = SettingsDialog(Config())
    item = dialog._tray_icon_list.item(0)
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


def test_fuzzy_match_toggle_roundtrips(qapp):
    dialog = SettingsDialog(Config(fuzzy_match=False))
    assert dialog._fuzzy_match.isChecked() is False
    dialog._fuzzy_match.setChecked(True)
    assert dialog.current_config().fuzzy_match is True
    dialog.close()


def test_settings_window_opacity_applies_and_roundtrips(qapp):
    # Painted-alpha, not setWindowOpacity (which the Qt Wayland plugin ignores):
    # in the light theme the card is thinned; the window fill is thinned in paintEvent.
    dialog = SettingsDialog(Config(settings_opacity=0.8, theme="light"))
    assert dialog._settings_opacity.value() == 80
    assert dialog._win_opacity == 0.8
    assert "rgba(255, 255, 255, 204)" in dialog.styleSheet()  # 0.8 * 255 card alpha
    dialog._settings_opacity.setValue(70)  # live preview while changing
    assert dialog._win_opacity == 0.7
    assert "rgba(255, 255, 255, 178)" in dialog.styleSheet()  # re-skinned to 0.7
    assert dialog.current_config().settings_opacity == 0.7
    dialog.close()


def test_settings_opacity_100_is_fully_opaque_and_range_is_full(qapp):
    # 100% must be genuinely opaque (the base palette alpha is < 255, which is why a
    # "100%" window still looked see-through before), and the spin allows 0..100.
    dialog = SettingsDialog(Config(settings_opacity=1.0, theme="dark"))
    dialog.resize(200, 200)
    assert dialog._settings_opacity.minimum() == 0
    assert dialog._settings_opacity.maximum() == 100
    opaque = dialog.grab().toImage().pixelColor(100, 100).alpha()
    assert opaque == 255  # fully solid at 100%
    dialog._settings_opacity.setValue(50)
    assert dialog.grab().toImage().pixelColor(100, 100).alpha() < 200  # clearly see-through
    dialog.close()


def test_font_picker_resolves_an_absent_family_to_an_installed_one(qapp):
    from PyQt6.QtGui import QFontDatabase

    installed = QFontDatabase.families()
    # A configured, installed family is kept verbatim.
    assert SettingsDialog._resolve_font_family(installed[0]) == installed[0]
    # A configured family that is NOT installed resolves to an installed fallback
    # rather than being handed to fontconfig (which substitutes an arbitrary font).
    resolved = SettingsDialog._resolve_font_family("__no_such_font__, still fake")
    assert resolved != "__no_such_font__"
    assert resolved == "" or resolved in set(installed)


def test_transition_style_roundtrips(qapp):
    dialog = SettingsDialog(Config(fx_transition="zoom"))
    assert dialog._fx_transition.currentData() == "zoom"
    dialog._fx_transition.setCurrentIndex(dialog._fx_transition.findData("slide"))
    assert dialog.current_config().fx_transition == "slide"
    dialog.close()


def test_reset_effects_tab_also_resets_the_transition_style(qapp):
    dialog = SettingsDialog(Config(fx_transition="zoom"))
    dialog._nav.setCurrentRow(4)  # 0 General,1 Icon,2 Text,3 Panel,4 Effects
    dialog._reset_current_page()
    assert dialog.current_config().fx_transition == Config().fx_transition  # "rise"
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
        cast(QListWidgetItem, dialog._tray_icon_list.item(index))
        for index in range(dialog._tray_icon_list.count())
    ]
    keys = [str(item.data(Qt.ItemDataRole.UserRole)) for item in items]
    assert keys[dialog._tray_icon_list.currentRow()] == "leaf-pink.svg"
    assert all(item.text() == "" for item in items)
    assert "leaf-green.svg" in keys

    dialog._tray_icon_list.setCurrentRow(keys.index("leaf-green.svg"))

    assert dialog.current_config().icon_name == "leaf-green.svg"
    dialog.close()
