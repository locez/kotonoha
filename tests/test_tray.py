import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from kotonoha import tray


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_discover_icon_paths_scans_only_supported_top_level_files(tmp_path):
    default_icon = tmp_path / "icon.png"
    default_icon.write_bytes(b"default")
    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    (icon_dir / "duplicate.png").write_bytes(b"default")
    (icon_dir / "leaf.svg").write_text("<svg/>", encoding="utf-8")
    (icon_dir / "badge.PNG").write_bytes(b"png")
    (icon_dir / "notes.txt").write_text("ignore", encoding="utf-8")
    originals = icon_dir / "originals"
    originals.mkdir()
    (originals / "hidden.svg").write_text("<svg/>", encoding="utf-8")

    choices = tray.discover_icon_paths(icon_dir=icon_dir, default_icon=default_icon)

    assert [(choice.key, choice.path.name) for choice in choices] == [
        ("default", "icon.png"),
        ("badge.PNG", "badge.PNG"),
        ("leaf.svg", "leaf.svg"),
    ]


def test_load_icon_falls_back_when_selected_file_is_missing(qapp, tmp_path):
    default_icon = tmp_path / "icon.svg"
    default_icon.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        '<rect width="16" height="16" fill="#ff4fa3"/></svg>',
        encoding="utf-8",
    )
    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()

    icon = tray.load_icon("missing.svg", icon_dir=icon_dir, default_icon=default_icon)

    assert icon.isNull() is False


def test_tray_icon_can_switch_without_restart(qapp):
    tray_icon = tray.KotonohaTray(
        icon_name="leaf-green.svg",
        passthrough=False,
        on_toggle_passthrough=lambda _checked: None,
        on_open_settings=lambda: None,
        on_quit=lambda: None,
    )
    first_key = tray_icon.icon().cacheKey()

    tray_icon.set_icon_name("leaf-pink-circle.png")

    assert tray_icon.icon().cacheKey() != first_key
