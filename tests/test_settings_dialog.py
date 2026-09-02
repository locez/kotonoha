import os
from typing import cast
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLineEdit, QListWidgetItem, QPushButton

from kotonoha.app.intents import ApplyConfig, ClearCache, OpenCacheManagement, RequestRestart
from kotonoha.config import (
    SETTINGS_PAGE_FIELDS,
    Config,
    FxIntensity,
    FxTransition,
    PanelStyle,
    PanelWidthMode,
    ThemeMode,
    UiLanguage,
)
from kotonoha.players import PlayerInfo
from kotonoha.ui.settings.dialog import SettingsDialog

PAGE_FIELDS = SETTINGS_PAGE_FIELDS


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_cache_controls_roundtrip_and_clear_signal(qapp):
    dialog = SettingsDialog(Config(cache_enabled=False))
    intents = []
    dialog.intent_requested.connect(intents.append)

    assert dialog.form_widgets.cache_enabled.isChecked() is False
    dialog.form_widgets.cache_enabled.setChecked(True)
    assert dialog.current_config().cache_enabled is True
    dialog.form_widgets.clear_cache.click()
    assert intents == [ClearCache()]
    dialog.close()


def test_cache_management_button_requests_the_separate_window(qapp):
    dialog = SettingsDialog(Config())
    intents = []
    dialog.intent_requested.connect(intents.append)

    dialog.form_widgets.manage_cache.click()

    assert intents == [OpenCacheManagement()]
    dialog.close()


def test_best_lyrics_policy_is_visible_and_roundtrips_on_sources_page(qapp):
    dialog = SettingsDialog(Config())

    assert dialog.form_widgets.prefer_best.isChecked() is True
    dialog.form_widgets.prefer_best.setChecked(False)
    assert dialog.current_config().prefer_best_lyrics is False
    dialog.close()


def test_resetting_sources_page_does_not_duplicate_clear_cache_signal(qapp):
    dialog = SettingsDialog(Config())
    intents = []
    dialog.intent_requested.connect(intents.append)
    sources = next(i for i, fields in enumerate(PAGE_FIELDS) if "lyrics_sources" in fields)
    dialog._nav.setCurrentRow(sources)

    dialog._reset_current_page()
    dialog._reset_current_page()
    dialog.form_widgets.clear_cache.click()

    assert intents == [ClearCache()]
    dialog.close()


def test_apply_intent_reports_only_fields_changed_since_last_apply(qapp):
    dialog = SettingsDialog(Config())
    intents = []
    dialog.intent_requested.connect(intents.append)
    theme = dialog.form_widgets.theme_combo
    theme.setCurrentIndex(theme.findData(ThemeMode.LIGHT.value))

    dialog._emit()

    assert isinstance(intents[-1], ApplyConfig)
    assert intents[-1].changed_fields == frozenset({"theme"})
    dialog.close()


def test_unchanged_font_style_survives_platform_font_normalization(qapp, monkeypatch):
    from kotonoha.ui.settings import pages

    monkeypatch.setattr(pages, "resolve_font_family", lambda _family: "__missing_font_for_test__")
    monkeypatch.setattr(pages, "available_font_styles", lambda _family: ["Book"])
    dialog = SettingsDialog(Config(font_style="Regular"))
    intents = []
    dialog.intent_requested.connect(intents.append)
    theme = dialog.form_widgets.theme_combo
    theme.setCurrentIndex(theme.findData(ThemeMode.LIGHT.value))

    dialog._emit()

    assert isinstance(intents[-1], ApplyConfig)
    assert intents[-1].changed_fields == frozenset({"theme"})
    assert dialog.current_config().font_style == "Regular"
    dialog.close()


def test_cider_token_is_editable_on_sources_page(qapp):
    dialog = SettingsDialog(Config(cider_api_token="test-token"))

    assert dialog.form_widgets.cider_token.echoMode() == QLineEdit.EchoMode.Password
    assert dialog.current_config().cider_api_token == "test-token"
    dialog.form_widgets.cider_token.setText("new-token")
    assert dialog.current_config().cider_api_token == "new-token"
    dialog.close()


def test_display_sources_keep_enabled_order_for_runtime_priority(qapp):
    dialog = SettingsDialog(Config(display_sources=["adapter", "cider"]))
    source_list = dialog.form_widgets.display_sources_list

    identifiers = []
    for index in range(source_list.count()):
        item = source_list.item(index)
        assert item is not None
        identifiers.append(str(item.data(Qt.ItemDataRole.UserRole)))
    assert identifiers == ["adapter", "cider", "mpris"]
    assert dialog.current_config().display_sources == ["adapter", "cider"]

    first = source_list.takeItem(0)
    assert first is not None
    source_list.insertItem(2, first)

    assert dialog.current_config().display_sources == ["cider", "adapter"]
    dialog.close()


def test_unavailable_player_lock_survives_dialog_roundtrip(qapp):
    dialog = SettingsDialog(Config(player_lock="org.mpris.MediaPlayer2.closed"), players=[])

    assert dialog.form_widgets.player_combo.currentData() == "org.mpris.MediaPlayer2.closed"
    assert "unavailable" in dialog.form_widgets.player_combo.currentText().lower()
    assert dialog.current_config().player_lock == "org.mpris.MediaPlayer2.closed"
    dialog.close()


def test_detected_players_are_readable_and_store_bus_name(qapp):
    dialog = SettingsDialog(
        Config(),
        players=[PlayerInfo("org.mpris.MediaPlayer2.youtube", "YouTube Music", "Song", "Artist", "Playing", True)],
    )

    index = dialog.form_widgets.player_combo.findData("org.mpris.MediaPlayer2.youtube")
    assert index > 0
    assert dialog.form_widgets.player_combo.itemText(index) == "Current · YouTube Music · Playing · Song by Artist"
    dialog.form_widgets.player_combo.setCurrentIndex(index)
    assert dialog.current_config().player_lock == "org.mpris.MediaPlayer2.youtube"
    dialog.close()


def test_idle_player_row_has_status_and_unavailable_choice_stays_selected(qapp):
    bus_name = "org.mpris.MediaPlayer2.closed"
    dialog = SettingsDialog(
        Config(player_lock=bus_name),
        players=[PlayerInfo("org.mpris.MediaPlayer2.idle", "Idle player", playback_status="Stopped")],
    )

    idle_index = dialog.form_widgets.player_combo.findData("org.mpris.MediaPlayer2.idle")
    assert dialog.form_widgets.player_combo.itemText(idle_index) == "Idle player · Stopped"
    assert dialog.form_widgets.player_combo.currentData() == bus_name
    assert dialog.form_widgets.player_combo.currentText() == bus_name + " (unavailable)"
    assert dialog.current_config().player_lock == bus_name
    dialog.close()


def test_current_line_only_control_roundtrips(qapp):
    dialog = SettingsDialog(Config(current_line_only=True))
    assert dialog.form_widgets.current_line_only.isChecked() is True
    dialog.form_widgets.current_line_only.setChecked(False)
    assert dialog.current_config().current_line_only is False
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
    from kotonoha.ui.settings.dialog import _CHECKMARK_PATH, _skin

    # The glyph must be a real bundled file: Qt's stylesheet url() does not decode
    # data: URIs, so an inline data URI renders nothing (a bare filled square).
    assert _CHECKMARK_PATH.is_file()
    qss = _skin(Config().accent_start)
    # A checked box draws a white tick the unchecked one lacks.
    assert _indicator_white_pixels(qss, checked=True) > _indicator_white_pixels(qss, checked=False)


def test_cache_dialog_aligns_headers_with_rows_and_localizes_close_button(qapp):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QHeaderView, QPushButton, QTableView

    from kotonoha.lyrics.cache import LyricsCacheEntry, LyricsCacheKey, LyricsCacheMode
    from kotonoha.strings import Translator
    from kotonoha.ui.settings.cache_dialog import LyricsCacheDialog, LyricsCacheTableModel

    dialog = LyricsCacheDialog(Config(ui_language=UiLanguage.ZH_HANS))
    table = dialog.findChild(QTableView)
    assert table is not None
    header = table.horizontalHeader()
    if header is None:
        raise AssertionError("cache table header is unavailable")
    assert header.defaultAlignment() == Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    assert header.sectionResizeMode(4) == QHeaderView.ResizeMode.ResizeToContents
    assert any(button.text() == "关闭" for button in dialog.findChildren(QPushButton))

    model = LyricsCacheTableModel(Translator("zh-Hans"))
    model.set_entries(
        (
            LyricsCacheEntry(
                key=LyricsCacheKey("netease", "manual"),
                title="Song",
                artist="Artist",
                album="Album",
                duration_s=180.0,
                fetched_at=1.0,
                last_accessed=2.0,
                mode=LyricsCacheMode.MANUAL,
            ),
        )
    )
    assert model.columnCount() == 7
    assert model.headerData(6, Qt.Orientation.Horizontal) == "模式"
    assert model.data(model.index(0, 6)) == "手动"
    dialog.close()


def test_dark_cache_dialog_keeps_the_table_header_on_the_dark_surface(qapp):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QTableView

    from kotonoha.ui.settings.cache_dialog import LyricsCacheDialog

    dialog = LyricsCacheDialog(Config(theme=ThemeMode.DARK, frost_window=False, fx_animate=False))
    table = dialog.findChild(QTableView)
    assert table is not None
    header = table.horizontalHeader()
    if header is None:
        raise AssertionError("cache table header is unavailable")
    header_viewport = header.viewport()
    if header_viewport is None:
        raise AssertionError("cache table header viewport is unavailable")
    assert header.autoFillBackground() is False
    assert header_viewport.autoFillBackground() is False

    dialog.show()
    qapp.processEvents()
    image = dialog.grab().toImage()
    point = header_viewport.mapTo(dialog, QPoint(header_viewport.width() - 8, header_viewport.height() // 2))
    assert image.pixelColor(point).lightness() < 100
    dialog.close()


def test_apply_reskins_dialog_with_new_accent(qapp):
    dialog = SettingsDialog(Config(accent_start="#FF4FA3"))
    assert "#FF4FA3" in dialog.styleSheet()
    cyan_index = next(
        i for i in range(dialog.form_widgets.accent.count())
        if dialog.form_widgets.accent.itemData(i) == ("#4FACFE", "#00F2FE", "#38E1FF")
    )
    dialog.form_widgets.accent.setCurrentIndex(cyan_index)
    dialog._emit()
    assert "#4FACFE" in dialog.styleSheet()
    dialog.close()


def test_accent_has_custom_picker_and_panel_tint_roundtrips(qapp):
    dialog = SettingsDialog(Config(panel_accent_tint=True))
    # A trailing "Custom…" picker entry (data None) is present.
    assert any(
        dialog.form_widgets.accent.itemData(i) is None
        for i in range(dialog.form_widgets.accent.count())
    )
    assert dialog.form_widgets.panel_tint.isChecked() is True
    assert dialog.current_config().panel_accent_tint is True
    dialog.close()


def test_custom_accent_slot_is_reused_not_accumulated(qapp, monkeypatch):
    from PyQt6.QtGui import QColor

    from kotonoha.ui.settings import pages

    dialog = SettingsDialog(Config())
    before = dialog.form_widgets.accent.count()
    colours = iter((QColor("#123456"), QColor("#654321")))
    monkeypatch.setattr(pages.QColorDialog, "getColor", lambda *_args: next(colours))
    custom_index = dialog.form_widgets.accent.findData(None)
    dialog.form_widgets.accent.activated.emit(custom_index)
    after_first = dialog.form_widgets.accent.count()
    dialog.form_widgets.accent.activated.emit(dialog.form_widgets.accent.findData(None))
    assert after_first == before + 1  # one slot added
    assert dialog.form_widgets.accent.count() == after_first  # reused, not piling up "自訂" entries
    assert dialog.form_widgets.accent.currentData() is not None
    assert "#654321" in dialog.form_widgets.accent.currentText()  # labelled with its hex
    dialog.close()


def test_opacity_is_independent_per_panel_style(qapp):
    dialog = SettingsDialog(Config(panel_style=PanelStyle.PILL, opacity=1.0, frost_opacity=0.4))
    assert dialog.form_widgets.opacity.value() == 100  # shows the black panel's opacity
    dialog.form_widgets.panel.setCurrentIndex(dialog.form_widgets.panel.findData("frost"))
    assert dialog.form_widgets.opacity.value() == 40  # switches to the frosted panel's opacity
    dialog.form_widgets.opacity.setValue(70)
    dialog.form_widgets.panel.setCurrentIndex(dialog.form_widgets.panel.findData("pill"))
    assert dialog.form_widgets.opacity.value() == 100  # black opacity preserved across the switch
    cfg = dialog.current_config()
    assert cfg.opacity == 1.0
    assert cfg.frost_opacity == 0.70  # the frosted change was kept separately
    dialog.close()


def test_panel_style_has_frosted_option_and_roundtrips(qapp):
    dialog = SettingsDialog(Config(panel_style=PanelStyle.FROST))
    assert dialog.form_widgets.panel.count() == 4  # black / white / frosted / text
    assert dialog.form_widgets.panel.currentData() == "frost"  # selected by data, not index
    assert dialog.current_config().panel_style == "frost"
    dialog.close()


def test_white_panel_option_present_and_roundtrips(qapp):
    dialog = SettingsDialog(Config(panel_style=PanelStyle.WHITE))
    assert dialog.form_widgets.panel.findData("white") >= 0
    assert dialog.form_widgets.panel.currentData() == "white"
    assert dialog.current_config().panel_style == "white"
    dialog.close()


def test_frost_window_toggle_roundtrips_and_lifecycle_is_safe(qapp):
    # Offscreen has no blur protocol, so enabling frost keeps a solid panel while
    # the normal show/resize/hide lifecycle remains safe.
    dialog = SettingsDialog(Config(frost_window=False))
    assert dialog.form_widgets.frost_window.isChecked() is False
    dialog.form_widgets.frost_window.setChecked(True)
    assert dialog.current_config().frost_window is True
    dialog._emit()
    assert dialog._frosted is False
    dialog.show()
    qapp.processEvents()
    dialog.resize(dialog.width() + 20, dialog.height())
    qapp.processEvents()
    dialog.close()
    dialog.deleteLater()
    qapp.processEvents()


def test_frost_checkbox_is_greyed_out_and_noted_when_blur_unavailable(qapp):
    from PyQt6.QtWidgets import QLabel

    from kotonoha.strings import Translator

    # Offscreen has no blur protocol, so frosted glass can't work: the checkbox
    # reads as unavailable (disabled), and the note under it names which of the
    # three causes it is rather than restating the requirement.
    dialog = SettingsDialog(Config())
    assert dialog._blur_capable is False
    assert dialog.form_widgets.frost_window.isEnabled() is False
    hints = [w.text() for w in dialog.findChildren(QLabel) if w.objectName() == "hint"]
    translator = Translator("en")
    causes = {
        translator.text(f"set.frost_window.no_{cause}")
        for cause in ("session", "bridge", "protocol", "build")
    }
    assert causes & set(hints), f"no cause shown for the disabled toggle: {hints}"
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
        i for i in range(dialog.form_widgets.accent.count())
        if dialog.form_widgets.accent.itemData(i) == ("#4FACFE", "#00F2FE", "#38E1FF")
    )
    dialog.form_widgets.accent.setCurrentIndex(cyan)
    dialog._emit()
    assert dialog._logo_badge.pixmap().toImage() != before
    dialog.close()


def test_theme_selector_roundtrips_and_switches_palette(qapp):
    from kotonoha.ui.settings.dialog import _PALETTES

    dark = SettingsDialog(Config(theme=ThemeMode.DARK))
    assert dark._theme == "dark"
    assert cast(str, _PALETTES["dark"]["TEXT"]) in dark.styleSheet()
    assert dark.current_config().theme == "dark"

    light = SettingsDialog(Config(theme=ThemeMode.LIGHT))
    assert light._theme == "light"
    assert cast(str, _PALETTES["light"]["TEXT"]) in light.styleSheet()
    # Switching theme on Apply re-skins the dialog live.
    light.form_widgets.theme_combo.setCurrentIndex(light.form_widgets.theme_combo.findData("dark"))
    light._emit()
    assert light._theme == "dark"
    assert cast(str, _PALETTES["dark"]["TEXT"]) in light.styleSheet()
    dark.close()
    light.close()


def test_switching_settings_to_dark_keeps_scroll_pages_on_the_dark_surface(qapp):
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QScrollArea

    dialog = SettingsDialog(Config(theme=ThemeMode.LIGHT, frost_window=False, fx_animate=False))
    scroll = dialog.findChild(QScrollArea, "settingsPageScroll")
    assert scroll is not None
    page = scroll.widget()
    assert page is not None
    assert page.autoFillBackground() is False
    viewport = scroll.viewport()
    if viewport is None:
        raise AssertionError("settings page viewport is unavailable")
    assert viewport.autoFillBackground() is False

    dialog.show()
    qapp.processEvents()
    dialog.form_widgets.theme_combo.setCurrentIndex(dialog.form_widgets.theme_combo.findData("dark"))
    dialog._emit()
    qapp.processEvents()

    image = dialog.grab().toImage()
    point = page.mapTo(dialog, QPoint(5, 200))
    assert image.pixelColor(point).lightness() < 80
    dialog.close()


def test_combo_popup_viewport_background_follows_active_settings_theme(qapp):
    from PyQt6.QtGui import QColor, QPalette

    from kotonoha.ui.settings import theme

    dialog = SettingsDialog(Config(theme=ThemeMode.LIGHT, frost_window=False, fx_animate=False))
    combo = dialog.form_widgets.font_family
    view = combo.view()
    if view is None:
        raise AssertionError("font combo popup view is unavailable")
    viewport = view.viewport()
    if viewport is None:
        raise AssertionError("font combo popup viewport is unavailable")

    dialog.show()
    combo.showPopup()
    qapp.processEvents()
    assert viewport.palette().color(QPalette.ColorRole.Base) == QColor(
        theme._popup_background(ThemeMode.LIGHT.value)
    )
    popup = view.window()
    if popup is None:
        raise AssertionError("font combo popup frame is unavailable")
    assert view.width() == combo.width()
    assert popup.width() == combo.width()
    combo.hidePopup()

    combo_theme = dialog.form_widgets.theme_combo
    combo_theme.setCurrentIndex(combo_theme.findData(ThemeMode.DARK.value))
    dialog._emit()
    combo.showPopup()
    qapp.processEvents()
    assert viewport.palette().color(QPalette.ColorRole.Base) == QColor(
        theme._popup_background(ThemeMode.DARK.value)
    )
    combo.hidePopup()
    dialog.close()


def test_long_settings_combo_items_do_not_expand_the_popup_frame(qapp):
    from kotonoha.ui.settings.widgets import SettingsComboBox

    combo = SettingsComboBox()
    combo.addItem("long-value-" + "x" * 400)
    combo.resize(180, 34)
    combo.show()
    qapp.processEvents()
    view = combo.view()
    if view is None:
        raise AssertionError("settings combo popup view is unavailable")

    combo.showPopup()
    qapp.processEvents()
    popup = view.window()
    if popup is None:
        raise AssertionError("settings combo popup frame is unavailable")
    assert view.width() == combo.width()
    assert popup.width() == combo.width()
    combo.hidePopup()
    combo.close()


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


def test_typography_controls_roundtrip(qapp):
    # KDE-style: a Family picker + a Style picker (Regular/Bold/…), no numeric weight.
    dialog = SettingsDialog(Config(
        font_family="DejaVu Sans", context_font_size=17, translation_font_size=11,
    ))
    assert dialog.form_widgets.context_font_size.value() == 17
    assert dialog.form_widgets.translation_font_size.value() == 11
    assert not hasattr(dialog, "_font_weight")  # the numeric weight picker is gone
    assert dialog.form_widgets.font_style.count() >= 1  # the style picker always offers something
    assert dialog.form_widgets.font_family.isEditable() is False  # a dropdown, never a text box
    cfg = dialog.current_config()
    assert cfg.context_font_size == 17
    assert cfg.translation_font_size == 11
    assert cfg.font_family  # a concrete family is stored
    assert cfg.font_style  # a concrete style is stored
    dialog.close()


def test_style_picker_lists_the_familys_real_styles(qapp):
    from PyQt6.QtGui import QFontDatabase

    from kotonoha.ui.settings.widgets import available_font_styles

    dialog = SettingsDialog(Config())
    # A family with no reported styles still offers a usable default.
    assert available_font_styles("___no_such_font___") == ["Regular"]
    # A family that reports styles offers exactly those (Regular sorted first).
    for family in QFontDatabase.families():
        styles = QFontDatabase.styles(family)
        if styles:
            offered = available_font_styles(family)
            assert set(offered) == set(styles)
            if "Regular" in styles:
                assert offered[0] == "Regular"
            break
    dialog.close()


def test_panel_width_control_enabled_only_for_fixed_mode(qapp):
    dialog = SettingsDialog(Config(panel_width_mode=PanelWidthMode.FIXED, panel_width=820))
    assert dialog.form_widgets.panel_width.isEnabled() is True
    assert dialog.current_config().panel_width == 820
    # Switching to fit-to-text disables the width value (it no longer applies).
    dialog.form_widgets.panel_width_mode.setCurrentIndex(dialog.form_widgets.panel_width_mode.findData("fit"))
    assert dialog.form_widgets.panel_width.isEnabled() is False
    assert dialog.current_config().panel_width_mode == "fit"
    dialog.close()


def test_sidebar_lists_every_section_and_drives_the_stack(qapp):
    from kotonoha.strings import Translator

    dialog = SettingsDialog(Config(ui_language=UiLanguage.EN), translator=Translator("en"))
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
    qapp.processEvents()


def test_long_settings_page_scrolls_inside_a_bounded_dialog(qapp):
    dialog = SettingsDialog(Config())
    dialog.show()
    qapp.processEvents()
    initial_size = dialog.size()

    dialog._nav.setCurrentRow(7)
    qapp.processEvents()

    scroll = dialog._page_scrolls[7]
    scrollbar = scroll.verticalScrollBar()
    if scrollbar is None:
        raise AssertionError("settings page did not create a vertical scrollbar")
    assert dialog.size() == initial_size
    assert scrollbar.maximum() > 0
    assert scrollbar.isVisible()
    dialog.close()


def test_language_change_reveals_restart_button_and_persists(qapp):
    dialog = SettingsDialog(Config(ui_language=UiLanguage.AUTO))
    assert dialog.form_widgets.restart_button.isHidden() is True  # nothing changed yet

    dialog.form_widgets.ui_language.setCurrentIndex(dialog.form_widgets.ui_language.findData("ja"))
    assert dialog.form_widgets.restart_button.isHidden() is False  # a different language -> offer restart

    applied: list[Config] = []
    intents = []
    dialog.intent_requested.connect(intents.append)
    dialog.applied.connect(applied.append)
    dialog.form_widgets.restart_button.click()

    assert intents[-1] == RequestRestart()
    assert applied and applied[-1].ui_language == "ja"  # persisted before relaunch

    # Reverting to the running language hides it again.
    dialog.form_widgets.ui_language.setCurrentIndex(dialog.form_widgets.ui_language.findData("auto"))
    assert dialog.form_widgets.restart_button.isHidden() is True
    dialog.close()


def test_icon_picker_includes_generated_leaf_styles(qapp):
    from kotonoha import leaf_icon

    dialog = SettingsDialog(Config(icon_name=leaf_icon.TILE))
    keys = []
    for i in range(dialog.form_widgets.tray_icon_list.count()):
        item = dialog.form_widgets.tray_icon_list.item(i)
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
    assert dialog.current_config().icon_name == leaf_icon.MONO
    dialog.close()


def test_tray_and_window_icons_are_chosen_independently(qapp):
    from kotonoha import leaf_icon

    dialog = SettingsDialog(Config(icon_name=leaf_icon.WHITE, window_icon_name=leaf_icon.TILE))
    # Each picker starts on its own saved style, not a shared one.
    current = dialog.current_config()
    assert current.icon_name == leaf_icon.WHITE
    assert current.window_icon_name == leaf_icon.TILE
    # Changing one does not move the other.
    window_keys = []
    for i in range(dialog.form_widgets.window_icon_list.count()):
        item = dialog.form_widgets.window_icon_list.item(i)
        assert item is not None
        window_keys.append(str(item.data(Qt.ItemDataRole.UserRole)))
    dialog.form_widgets.window_icon_list.setCurrentRow(window_keys.index(leaf_icon.BLACK))
    cfg = dialog.current_config()
    assert cfg.icon_name == leaf_icon.WHITE
    assert cfg.window_icon_name == leaf_icon.BLACK
    dialog.close()


def test_reset_tab_restores_only_current_page(qapp):
    dialog = SettingsDialog(
        Config(font_size=90, context_font_size=80, margin_edge=999, karaoke=False, current_line_only=True)
    )
    dialog._nav.setCurrentRow(2)  # Text page (0 General, 1 Icon, 2 Text)
    dialog._reset_current_page()
    cfg = dialog.current_config()
    defaults = Config()
    # Text fields reset...
    assert cfg.font_size == defaults.font_size
    assert cfg.context_font_size == defaults.context_font_size
    assert cfg.current_line_only is True  # Lyrics-page edits survive a Text-page reset.
    # ...but other pages' edits are untouched.
    assert cfg.margin_edge == 999
    assert cfg.karaoke is False
    dialog.close()


def test_reset_lyrics_tab_restores_current_line_only(qapp):
    dialog = SettingsDialog(Config(current_line_only=True, margin_edge=999))
    dialog._nav.setCurrentRow(5)  # Lyrics page
    dialog._reset_current_page()
    cfg = dialog.current_config()
    assert cfg.current_line_only is False
    assert cfg.margin_edge == 999  # Position-page edits survive a Lyrics-page reset.
    dialog.close()


def test_reset_icon_tab_rebuilds_icon_pickers_without_doubling(qapp):
    from kotonoha import leaf_icon

    dialog = SettingsDialog(
        Config(icon_name=leaf_icon.WHITE, window_icon_name=leaf_icon.BLACK, theme=ThemeMode.LIGHT)
    )
    dialog._nav.setCurrentRow(1)  # Icon page owns the two icon strips
    dialog._reset_current_page()
    cfg = dialog.current_config()
    defaults = Config()
    assert cfg.icon_name == defaults.icon_name
    assert cfg.window_icon_name == defaults.window_icon_name
    assert cfg.theme == "light"  # a different tab's edit is untouched by the Icon reset
    # The strips were rebuilt, not appended a second time.
    assert len(dialog.form_widgets.icon_pickers) == 2
    dialog.close()


def test_selected_icon_is_not_blue_tinted(qapp):
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    dialog = SettingsDialog(Config())
    item = dialog.form_widgets.tray_icon_list.item(0)
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
    dialog = SettingsDialog(
        Config(fx_animate=False, fx_glow=True, fx_word_pop=False, fx_intensity=FxIntensity.EXPRESSIVE)
    )
    assert dialog.form_widgets.fx_animate.isChecked() is False
    assert dialog.form_widgets.fx_glow.isChecked() is True
    assert dialog.form_widgets.fx_word_pop.isChecked() is False
    assert dialog.form_widgets.fx_intensity.currentData() == "expressive"
    dialog.form_widgets.fx_glow.setChecked(False)
    dialog.form_widgets.fx_word_pop.setChecked(True)
    cfg = dialog.current_config()
    assert cfg.fx_animate is False
    assert cfg.fx_glow is False
    assert cfg.fx_word_pop is True
    assert cfg.fx_intensity == "expressive"
    dialog.close()


def test_fuzzy_match_toggle_roundtrips(qapp):
    dialog = SettingsDialog(Config(fuzzy_match=False))
    assert dialog.form_widgets.fuzzy_match.isChecked() is False
    dialog.form_widgets.fuzzy_match.setChecked(True)
    assert dialog.current_config().fuzzy_match is True
    dialog.close()


def test_settings_window_opacity_applies_and_roundtrips(qapp):
    # Painted-alpha, not setWindowOpacity (which the Qt Wayland plugin ignores):
    # in the light theme the card is thinned; the window fill is thinned in paintEvent.
    dialog = SettingsDialog(Config(settings_opacity=0.8, theme=ThemeMode.LIGHT))
    assert dialog.form_widgets.settings_opacity.value() == 80
    assert dialog._win_opacity == 0.8
    assert "rgba(255, 255, 255, 204)" in dialog.styleSheet()  # 0.8 * 255 card alpha
    dialog.form_widgets.settings_opacity.setValue(70)  # not applied until OK/Apply (no live preview)
    assert dialog._win_opacity == 0.8  # still the opened value
    dialog._emit()  # Apply
    assert dialog._win_opacity == 0.7
    assert "rgba(255, 255, 255, 178)" in dialog.styleSheet()  # re-skinned to 0.7
    assert dialog.current_config().settings_opacity == 0.7
    dialog.close()


def test_settings_opacity_100_is_fully_opaque_and_range_is_full(qapp):
    # 100% must be genuinely opaque (the base palette alpha is < 255, which is why a
    # "100%" window still looked see-through before), and the spin allows 0..100.
    dialog = SettingsDialog(Config(settings_opacity=1.0, theme=ThemeMode.DARK))
    dialog.resize(200, 200)
    assert dialog.form_widgets.settings_opacity.minimum() == 0
    assert dialog.form_widgets.settings_opacity.maximum() == 100
    # Sampled inside the window's own fill, clear of the panels and their text:
    # the centre of a small dialog lands on a label, whose pixels are opaque
    # whatever the window is set to.
    opaque = dialog.grab().toImage().pixelColor(20, 20).alpha()
    assert opaque == 255  # fully solid at 100%
    dialog.form_widgets.settings_opacity.setValue(50)
    dialog._emit()  # applied on Apply, not live
    assert dialog.grab().toImage().pixelColor(20, 20).alpha() < 200  # clearly see-through
    dialog.close()


def test_font_picker_follows_a_deterministic_fallback_order():
    from kotonoha.ui.settings.widgets import FONT_FALLBACKS, resolve_font_family

    preferred = FONT_FALLBACKS[0]
    cases = (
        (
            "configured",
            "Configured Family, Other Family",
            {"Configured Family", "Other Family"},
            set(),
            "Desktop Family",
            "Configured Family",
        ),
        (
            "preferred",
            "Missing Family",
            {preferred, "Desktop Family"},
            {preferred, "Desktop Family"},
            "Desktop Family",
            preferred,
        ),
        (
            "desktop",
            "Missing Family",
            {"Desktop Family", "Other CJK Family"},
            {"Desktop Family", "Other CJK Family"},
            "Desktop Family",
            "Desktop Family",
        ),
        (
            "sorted",
            "Missing Family",
            {"Zed CJK Family", "Able CJK Family"},
            {"Zed CJK Family", "Able CJK Family"},
            "Desktop Family",
            "Able CJK Family",
        ),
        (
            "no-target-font",
            "Missing Family, Still Missing",
            {"Desktop Family", "Other Family"},
            set(),
            "Desktop Family",
            "Desktop Family",
        ),
        (
            "no-installed-font",
            "Missing Family, Still Missing",
            set(),
            set(),
            "",
            "Missing Family",
        ),
        (
            "desktop-without-font-inventory",
            "Missing Family, Still Missing",
            set(),
            set(),
            "Desktop Family",
            "Desktop Family",
        ),
    )

    for name, configured, installed, supported, desktop, expected in cases:
        assert resolve_font_family(
            configured,
            installed_families=installed,
            supported_families=supported,
            desktop_family=desktop,
        ) == expected, name


def test_transition_style_roundtrips(qapp):
    dialog = SettingsDialog(Config(fx_transition=FxTransition.ZOOM))
    assert dialog.form_widgets.fx_transition.currentData() == "zoom"
    dialog.form_widgets.fx_transition.setCurrentIndex(dialog.form_widgets.fx_transition.findData("slide"))
    assert dialog.current_config().fx_transition == "slide"
    dialog.close()


def test_reset_effects_tab_also_resets_the_transition_style(qapp):
    dialog = SettingsDialog(Config(fx_transition=FxTransition.ZOOM))
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
        cast(QListWidgetItem, dialog.form_widgets.tray_icon_list.item(index))
        for index in range(dialog.form_widgets.tray_icon_list.count())
    ]
    keys = [str(item.data(Qt.ItemDataRole.UserRole)) for item in items]
    assert keys[dialog.form_widgets.tray_icon_list.currentRow()] == "leaf-pink.svg"
    assert all(item.text() == "" for item in items)
    assert "leaf-green.svg" in keys

    dialog.form_widgets.tray_icon_list.setCurrentRow(keys.index("leaf-green.svg"))

    assert dialog.current_config().icon_name == "leaf-green.svg"
    dialog.close()


def test_resetting_the_sources_page_restores_automatic_player_selection(qapp):
    # Reset this tab rebuilds the page from defaults, but the staged config keeps
    # any field the page's reset list omits — so a configured lock survived the
    # reset and Apply persisted it.
    dialog = SettingsDialog(
        Config(player_lock="org.mpris.MediaPlayer2.closed"),
        players=[PlayerInfo("org.mpris.MediaPlayer2.a", "A")],
    )
    sources = next(i for i, fields in enumerate(PAGE_FIELDS) if "lyrics_sources" in fields)
    dialog._nav.setCurrentRow(sources)

    dialog._reset_current_page()

    assert dialog.current_config().player_lock == ""
    dialog.close()


def test_every_field_the_dialog_edits_belongs_to_a_page_reset_list():
    # A field the dialog writes but no page resets cannot be undone by Reset this
    # tab: it stays in the staged config and Apply persists the old value.
    from dataclasses import fields

    covered = {name for page in PAGE_FIELDS for name in page}
    # Not editable here: the port is a CLI/config-file setting, and the position
    # and per-track offsets are written by dragging and by the overlay's buttons.
    not_edited = {"port", "screen_name", "screen_width", "screen_height", "translation_language"}
    missing = {f.name for f in fields(Config)} - covered - not_edited
    assert not missing, f"no page resets these: {sorted(missing)}"


def test_the_settings_window_does_not_import_the_mpris_provider():
    # The row DTO lives in the neutral model module, so describing a player in the
    # UI does not drag in the D-Bus provider.
    import ast
    from pathlib import Path

    source = Path("src/kotonoha/ui/settings/dialog.py").read_text(encoding="utf-8")
    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not {name for name in imported if "providers" in name}, imported


def test_the_player_dto_is_exported_by_the_module_that_defines_it():
    # A type imported from a module but missing from its __all__ is outside the
    # contract that module declares — which is how it ended up appended after the
    # lyrics model's exports, in a module about lyric payloads.
    from kotonoha import players

    assert players.__all__ == ["PlayerInfo"]
    from kotonoha.players import PlayerInfo

    assert PlayerInfo.__module__ == "kotonoha.players"


def test_a_refused_blur_falls_back_to_a_solid_panel(qapp, caplog) -> None:
    # The window is painted translucent because a compositor blur is meant to sit
    # behind it. Discarding the result left the panel see-through over an unblurred
    # backdrop — unreadable — while still reporting frosted glass as on.
    from dataclasses import replace

    from kotonoha.platform.overlay_contracts import (
        OverlayCapabilities,
        OverlayPlatformAdapters,
        SurfaceResult,
    )
    from kotonoha.platform.qt_window import QtWindowPlatform

    class RefusingPlatform(QtWindowPlatform):
        """Advertises blur and then refuses to install it, as a compositor may."""

        @property
        def capabilities(self) -> OverlayCapabilities:
            return replace(super().capabilities, blur=True, blur_reason=None)

        def set_blur_region(self, region, radius: int = 0) -> SurfaceResult:
            del region, radius
            return SurfaceResult.rejected("compositor refused the effect")

    def refusing_factory(host):
        adapter = RefusingPlatform(host)
        return OverlayPlatformAdapters(
            surface=adapter,
            input_region=adapter,
            blur=adapter,
            placement=adapter,
            output_binding=None,
            drag=adapter,
        )

    dialog = SettingsDialog(Config(frost_window=True), platform_factory=refusing_factory)
    assert dialog._frosted is True, "the dialog should start out expecting frosted glass"

    with caplog.at_level("WARNING"):
        dialog._apply_blur()

    assert dialog._frosted is False, "the panel stayed translucent with nothing blurred behind it"
    assert "compositor refused the effect" in caplog.text
    dialog.close()


def test_settings_window_stays_visible_when_a_platform_adapter_is_injected(qapp) -> None:
    """An injected adapter must not recreate or activate the normal Qt dialog."""
    from kotonoha.platform.overlay_contracts import OverlayPlatformAdapters, WindowHost
    from kotonoha.platform.qt_window import QtWindowPlatform

    adapters: list[QtWindowPlatform] = []

    def factory(host: WindowHost) -> OverlayPlatformAdapters:
        adapter = QtWindowPlatform(host)
        adapters.append(adapter)
        return OverlayPlatformAdapters(
            surface=adapter,
            input_region=adapter,
            blur=adapter,
            placement=adapter,
            output_binding=None,
            drag=adapter,
        )

    baseline = SettingsDialog(Config())
    baseline.show()
    qapp.processEvents()

    dialog = SettingsDialog(Config(), platform_factory=factory)
    adapter = adapters[0]
    with (
        patch.object(adapter, "prepare", wraps=adapter.prepare) as prepare,
        patch.object(adapter, "activate", wraps=adapter.activate) as activate,
        patch.object(adapter, "close", wraps=adapter.close) as close,
    ):
        dialog.show()
        qapp.processEvents()

        assert dialog.isVisible()
        assert dialog.size() == baseline.size()
        assert not dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert dialog.windowFlags() & Qt.WindowType.Dialog
        close_button = next(button for button in dialog.findChildren(QPushButton) if button.text() == "✕")
        assert close_button.isVisible()
        prepare.assert_not_called()
        activate.assert_not_called()
        dialog.close()
        close.assert_not_called()
    baseline.close()
    qapp.processEvents()


def test_the_suite_runs_on_the_platform_its_assertions_describe(qapp) -> None:
    # Several tests here assert what an offscreen platform does. conftest used to
    # set QT_QPA_PLATFORM with setdefault, so a Wayland session's value won and
    # those assertions were checked against the real compositor instead.
    import os

    from PyQt6.QtGui import QGuiApplication

    assert QGuiApplication.platformName() == "offscreen"
    assert "WAYLAND_DISPLAY" not in os.environ


def test_opening_settings_does_not_narrow_a_saved_sync_offset(qapp) -> None:
    # The spin box spanned half of what Config accepts, so a valid saved offset was
    # truncated the moment the window was opened and applied — without the user
    # touching the control.
    from kotonoha.config import LEAD_MS_LIMIT

    for value in (LEAD_MS_LIMIT, -LEAD_MS_LIMIT):
        dialog = SettingsDialog(Config(lead_ms=value))
        assert dialog.current_config().lead_ms == value
        dialog.close()


def test_a_custom_accent_sharing_a_preset_start_keeps_its_own_colours(qapp) -> None:
    # Recognition compared only the first colour, so a custom gradient beginning on
    # a preset's start was applied as that preset and lost its end and sweep.
    from kotonoha.config import ACCENT_PRESETS

    _key, start, end, sweep = ACCENT_PRESETS[0]
    custom = Config(accent_start=start, accent_end="#010203", accent_sweep="#040506")

    applied = SettingsDialog(custom).current_config()

    assert (applied.accent_end, applied.accent_sweep) == ("#010203", "#040506")

    preset = SettingsDialog(Config(accent_start=start, accent_end=end, accent_sweep=sweep)).current_config()
    assert (preset.accent_start, preset.accent_end, preset.accent_sweep) == (start, end, sweep)


def test_an_unedited_font_fallback_chain_survives_apply(qapp) -> None:
    # The configured value may be a list, which exists so a family without CJK
    # glyphs still renders the lyrics this program is mostly used for. The picker
    # shows one family, and writing that one back turned the chain into its first
    # member on any apply — including one where nobody touched the control.
    chain = "DejaVu Sans, Noto Sans, sans-serif"

    dialog = SettingsDialog(Config(font_family=chain))

    assert dialog.current_config().font_family == chain
    dialog.close()


def test_the_source_list_shows_what_will_be_saved(qapp) -> None:
    # Unchecking every source was accepted and then quietly undone on apply,
    # because a configuration with no source at all is not storable.
    from PyQt6.QtCore import Qt

    dialog = SettingsDialog(Config())
    for index in range(dialog.form_widgets.sources_list.count()):
        row = dialog.form_widgets.sources_list.item(index)
        assert row is not None
        row.setCheckState(Qt.CheckState.Unchecked)

    shown = dialog.current_config().lyrics_sources

    assert shown, "the panel offered a state that cannot be stored"
    assert shown == dialog.current_config().lyrics_sources
    dialog.close()


def test_every_skin_styles_the_internal_scrollbar_container():
    from kotonoha.ui.settings.theme import _popup_skin, _skin

    for qss in (_skin(Config().accent_start), _popup_skin(Config().accent_start)):
        rule = next(
            (line for line in qss.splitlines() if "qt_scrollarea_vcontainer" in line),
            None,
        )
        assert rule is not None
        assert "background: transparent" in rule


def test_eliding_label_shrinks_instead_of_widening_its_parent(qapp):
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

    from kotonoha.ui.settings.widgets import ElidingLabel

    text = "40 個結果（無法使用的來源：QQ 音樂, Cider 自帶）"

    # A plain QLabel makes its container at least as wide as the whole string, which
    # is what forced the search dialog wider than the screen. This one does not.
    boxed = ElidingLabel()
    boxed.setText(text)
    elided_box, plain_box = QWidget(), QWidget()
    QHBoxLayout(elided_box).addWidget(boxed)
    QHBoxLayout(plain_box).addWidget(QLabel(text))
    assert elided_box.minimumSizeHint().width() < plain_box.minimumSizeHint().width()

    # Given less width than the text needs, it truncates visibly rather than clipping.
    label = ElidingLabel()
    label.setText(text)
    # Qt only delivers the resize to a widget that is on screen, and elision is a
    # property of the painted line, so the label has to be shown to observe it.
    label.show()
    label.resize(60, 20)
    qapp.processEvents()
    assert label.text() != text
    assert label.text().endswith("…")
    # The untruncated string stays available, which is what the tooltip shows.
    assert label.full_text() == text


def test_a_theme_change_redraws_the_sidebar_glyphs(qapp):
    from kotonoha.ui.settings.dialog import SettingsDialog

    dialog = SettingsDialog(Config(theme=ThemeMode.DARK))

    def _glyph_colour() -> str:
        item = dialog._nav.item(0)
        assert item is not None
        image = item.icon().pixmap(16, 16).toImage()
        drawn = [
            image.pixelColor(x, y)
            for x in range(16)
            for y in range(16)
            if image.pixelColor(x, y).alpha() > 128
        ]
        assert drawn, "the sidebar glyph drew nothing"
        return drawn[len(drawn) // 2].name()

    before = _glyph_colour()
    dialog.retheme(Config(theme=ThemeMode.LIGHT))

    # A stylesheet reapplies itself; an icon does not. One left at the old palette
    # reads as inverted against the label beside it, which did follow.
    assert _glyph_colour() != before


def test_changing_the_theme_inside_settings_redraws_its_own_glyphs(qapp):
    from kotonoha.ui.settings.dialog import SettingsDialog

    dialog = SettingsDialog(Config(theme=ThemeMode.DARK))

    def _glyph_colour() -> str:
        item = dialog._nav.item(0)
        assert item is not None
        image = item.icon().pixmap(16, 16).toImage()
        drawn = [
            image.pixelColor(x, y)
            for x in range(16)
            for y in range(16)
            if image.pixelColor(x, y).alpha() > 200
        ]
        assert drawn, "the sidebar glyph drew nothing"
        return drawn[len(drawn) // 2].name()

    before = _glyph_colour()
    combo = dialog.form_widgets.theme_combo
    combo.setCurrentIndex(combo.findData(ThemeMode.LIGHT.value))
    dialog._emit()

    # This window restyles itself on apply instead of going through retheme(), and
    # that path forgot the icons: the sidebar kept white glyphs on a white surface.
    assert _glyph_colour() != before


def test_the_cache_window_leaf_follows_an_applied_accent(qapp):
    from kotonoha.ui.settings.cache_dialog import LyricsCacheDialog

    dialog = LyricsCacheDialog(Config(accent_start="#FF5EB5"))

    def _ink() -> str:
        image = dialog._logo_badge.pixmap().toImage()
        drawn = [
            image.pixelColor(x, y)
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).alpha() > 128
        ]
        assert drawn, "the badge drew nothing"
        return drawn[len(drawn) // 2].name()

    before = _ink()
    dialog.retheme(Config(accent_start="#4FACFE"))

    # The leaf is tinted at render time and this window redrew nothing on the
    # retheme path, so it kept the previous accent beside restyled controls.
    assert _ink() != before


def test_an_applied_accent_reaches_the_row_that_marks_the_current_page(qapp):
    from kotonoha.ui.settings.dialog import SettingsDialog

    dialog = SettingsDialog(Config(accent_start="#3B82F6", theme=ThemeMode.DARK))

    def _rail() -> str:
        return dialog._nav_delegate._rail.name()

    before = _rail()
    accent = dialog.form_widgets.accent
    cyan = next(
        index for index in range(accent.count())
        if accent.itemData(index) == ("#4FACFE", "#00F2FE", "#38E1FF")
    )
    accent.setCurrentIndex(cyan)
    dialog._emit()

    # The rail and the tint are the delegate's QColors, taken once. Reapplying the
    # skin does not reach a delegate, so the current row kept the old accent while
    # every control around it moved to the new one.
    assert _rail() != before
    assert _rail() == "#4facfe"


def test_window_opacity_moves_the_frosted_window_too(qapp):
    from PyQt6.QtGui import QImage, QPainter

    from kotonoha.ui.settings.dialog import SettingsDialog

    def _corner_alpha(opacity: float) -> int:
        dialog = SettingsDialog(Config(settings_opacity=opacity, theme=ThemeMode.DARK))
        dialog._frosted = True
        dialog.resize(200, 120)
        image = QImage(200, 120, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        dialog.render(painter)
        painter.end()
        return image.pixelColor(100, 60).alpha()

    # Frost used to paint one hardcoded alpha, so the control did nothing at any
    # value while still offering to be moved.
    assert _corner_alpha(0.4) < _corner_alpha(1.0)


def test_a_title_that_fits_does_not_move(qapp):
    from kotonoha.ui.settings.widgets import ScrollingLabel

    label = ScrollingLabel()
    # Shown, because Qt delivers a resize only to a widget that is on screen, and
    # the decision to move at all is made from the width it was given.
    label.show()
    label.resize(400, 24)
    label.setText("Realize")
    qapp.processEvents()

    # Motion is expensive attention, so it is spent only where the text cannot be
    # read any other way.
    assert not label._timer.isActive()

    label.setText("忘れじの言の葉 - Forgotten Words [Symphonic Ver.] (合作演出:Inui Toko)")
    label.resize(120, 24)
    qapp.processEvents()

    assert label._timer.isActive()
    assert label.full_text().startswith("忘れじの言の葉")
