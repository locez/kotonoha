import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from kotonoha import leaf_icon as leaf


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_generated_keys_are_recognised(qapp):
    assert leaf.is_generated(leaf.ACCENT)
    assert leaf.is_generated(leaf.MONO)
    assert leaf.is_generated(leaf.TILE)
    assert not leaf.is_generated("leaf-pink.svg")
    assert not leaf.is_generated("default")


def test_accent_leaf_follows_the_accent(qapp):
    red = leaf.render_leaf(leaf.ACCENT, "#FF0000")
    green = leaf.render_leaf(leaf.ACCENT, "#00FF00")
    assert not red.isNull()
    assert red.toImage() != green.toImage()  # the leaf recolours to the accent


def test_mono_leaf_adapts_to_the_panel_theme(qapp):
    on_dark = leaf.render_leaf(leaf.MONO, dark_panel=True)
    on_light = leaf.render_leaf(leaf.MONO, dark_panel=False)
    assert not on_dark.isNull()
    assert on_dark.toImage() != on_light.toImage()  # light leaf vs dark leaf


def test_tile_background_follows_the_accent(qapp):
    red = leaf.render_leaf(leaf.TILE, "#FF0000")
    blue = leaf.render_leaf(leaf.TILE, "#0000FF")
    assert not red.isNull()
    assert red.toImage() != blue.toImage()


def test_load_icon_renders_generated_styles(qapp):
    from kotonoha.tray import load_icon

    assert not leaf.leaf_qicon(leaf.ACCENT, "#FF00FF").isNull()
    assert not load_icon(leaf.MONO, accent="#00FFAA").isNull()
    assert not load_icon(leaf.TILE, accent="#123456").isNull()
