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


def test_checked_indicator_supplies_an_explicit_checkmark_image(qapp):
    dialog = SettingsDialog(Config())
    qss = dialog.styleSheet()
    # Without an explicit image the custom-styled indicator drew a blank square.
    assert "indicator:checked" in qss
    assert "image: url(data:image/svg+xml;base64," in qss
    dialog.close()


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
