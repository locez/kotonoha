"""Unit tests for LayerShellController's platform gates and runtime probe.

These cover the fallback logic that decides whether the overlay drives the
wlr-layer-shell bridge or degrades to a top-most ordinary window, without
needing a live Wayland compositor. The gate order under test:

    non-Wayland  ->  GNOME name check  ->  library found  ->  runtime probe
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kotonoha import native
from kotonoha.native import LayerShellController


class _FakeLib:
    """Stand-in for the ctypes CDLL returned by _load, for probe tests."""

    def __init__(self, *, has_layer_shell: bool | None) -> None:
        # has_layer_shell None -> the symbol is absent entirely (older .so).
        if has_layer_shell is not None:
            self.koto_has_layer_shell = lambda: (1 if has_layer_shell else 0)


@pytest.fixture
def stub_load(monkeypatch):
    """Make __init__ find a library and return a chosen fake lib from _load."""

    def _apply(lib: object) -> None:
        monkeypatch.setattr(native, "find_layer_shell_library", lambda _pkg: "/fake/libkoto-layer.so")
        monkeypatch.setattr(LayerShellController, "_load", staticmethod(lambda _path: lib))

    return _apply


def test_non_wayland_session_disables_before_touching_the_library(monkeypatch):
    # X11/xcb must bail out first: the .so would dlopen but every call no-ops on
    # an xcb surface, so we refuse it and take the top-most-window path instead.
    def _boom(_pkg):  # find_layer_shell_library must never be reached
        raise AssertionError("library lookup must not run on a non-Wayland session")

    monkeypatch.setattr(native, "find_layer_shell_library", _boom)
    ctl = LayerShellController("/pkg", "xcb", "KDE")
    assert ctl.available is False
    assert ctl.disabled_reason is not None
    assert "non-wayland" in ctl.disabled_reason.lower()


def test_gnome_wayland_is_disabled_by_the_name_check(monkeypatch):
    monkeypatch.setattr(native, "find_layer_shell_library", lambda _pkg: "/fake/libkoto-layer.so")
    ctl = LayerShellController("/pkg", "wayland", "ubuntu:GNOME")
    assert ctl.available is False
    assert "gnome" in (ctl.disabled_reason or "").lower()


def test_missing_library_disables_with_a_hint(monkeypatch):
    monkeypatch.setattr(native, "find_layer_shell_library", lambda _pkg: None)
    ctl = LayerShellController("/pkg", "wayland", "KDE")
    assert ctl.available is False
    assert "libkoto-layer.so" in (ctl.disabled_reason or "")


def test_runtime_probe_absent_protocol_disables(stub_load):
    # KDE name, library present, but the compositor does not advertise
    # zwlr_layer_shell_v1 -> degrade despite the desktop name.
    stub_load(_FakeLib(has_layer_shell=False))
    ctl = LayerShellController("/pkg", "wayland", "KDE")
    assert ctl.available is False
    assert "layer-shell" in (ctl.disabled_reason or "").lower()


def test_runtime_probe_present_protocol_enables(stub_load):
    stub_load(_FakeLib(has_layer_shell=True))
    ctl = LayerShellController("/pkg", "wayland", "KDE")
    assert ctl.available is True
    assert ctl.disabled_reason is None


def test_older_bridge_without_probe_symbol_still_loads(stub_load):
    # An older .so lacking koto_has_layer_shell must fall through to available,
    # relying on the name check that already passed above it.
    stub_load(_FakeLib(has_layer_shell=None))
    ctl = LayerShellController("/pkg", "wayland", "KDE")
    assert ctl.available is True


_REAL_BRIDGE = Path(native.__file__).parent / "libkoto-layer.so"


@pytest.mark.skipif(not _REAL_BRIDGE.exists(), reason="native bridge not built")
def test_load_real_bridge_declares_argtypes_and_handshake():
    # Integration: the actually-built .so loads, exposes the ABI symbols, and
    # passes the Qt handshake against the running PyQt6 (same system Qt).
    lib = LayerShellController._load(str(_REAL_BRIDGE))
    assert lib.make_overlay.argtypes is not None
    assert hasattr(lib, "koto_layer_qt_version")
    assert hasattr(lib, "koto_has_layer_shell")
