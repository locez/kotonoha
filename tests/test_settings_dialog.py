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


def test_panel_style_has_frosted_option_and_roundtrips(qapp):
    dialog = SettingsDialog(Config(panel_style="frost"))
    assert dialog._panel.count() == 3  # glass / frosted / text
    assert dialog._panel.currentData() == "frost"  # selected by data, not index
    assert dialog.current_config().panel_style == "frost"
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
