import sysconfig

import kotonoha.platform.native as native
from kotonoha.platform.detect import (
    find_layer_shell_library,
    overlay_mode_available,
    should_disable_layer_shell,
)


def test_default_package_dir_uses_editable_install_native_library(tmp_path, monkeypatch):
    source_package = tmp_path / "src" / "kotonoha"
    installed_package = tmp_path / "venv" / "site-packages" / "kotonoha"
    source_package.mkdir(parents=True)
    installed_package.mkdir(parents=True)
    (installed_package / "libkoto-layer.so").touch()

    monkeypatch.setattr(native, "__file__", str(source_package / "native.py"))
    monkeypatch.setattr(sysconfig, "get_path", lambda name: str(installed_package.parent))

    assert native.default_package_dir() == str(installed_package)


def test_find_layer_shell_library_prefers_unsuffixed_name(tmp_path):
    suffixed = tmp_path / "libkoto-layer.cpython-314-x86_64-linux-gnu.so"
    exact = tmp_path / "libkoto-layer.so"
    suffixed.touch()
    exact.touch()

    assert find_layer_shell_library(tmp_path) == str(exact)


def test_find_layer_shell_library_accepts_python_abi_suffix(tmp_path):
    suffixed = tmp_path / "libkoto-layer.cpython-314-x86_64-linux-gnu.so"
    suffixed.touch()

    assert find_layer_shell_library(tmp_path) == str(suffixed)


def test_find_layer_shell_library_returns_none_when_missing(tmp_path):
    assert find_layer_shell_library(tmp_path) is None


def test_should_disable_layer_shell_on_gnome_wayland():
    assert should_disable_layer_shell("wayland", "ubuntu:GNOME") is True


def test_should_not_disable_layer_shell_on_kde_wayland():
    assert should_disable_layer_shell("wayland", "KDE") is False


def test_should_not_disable_layer_shell_on_x11():
    assert should_disable_layer_shell("xcb", "GNOME") is False


def test_overlay_mode_unavailable_when_layer_shell_disabled_on_wayland():
    assert overlay_mode_available("wayland", has_layer_shell=False, layer_shell_disabled=True) is False


def test_overlay_mode_available_with_layer_shell():
    assert overlay_mode_available("wayland", has_layer_shell=True, layer_shell_disabled=False) is True


def test_overlay_mode_available_on_x11_without_layer_shell():
    assert overlay_mode_available("xcb", has_layer_shell=False, layer_shell_disabled=False) is True


def test_current_desktop_reads_the_session_environment(monkeypatch):
    from kotonoha.platform.detect import current_desktop

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE:KWin")
    assert current_desktop() == "KDE:KWin"


def test_current_desktop_defaults_to_empty(monkeypatch):
    from kotonoha.platform.detect import current_desktop

    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    assert current_desktop() == ""


def test_session_desktop_reads_the_session_environment(monkeypatch):
    from kotonoha.platform.detect import session_desktop

    monkeypatch.setenv("XDG_SESSION_DESKTOP", "niri")
    assert session_desktop() == "niri"


def test_session_desktop_defaults_to_empty(monkeypatch):
    from kotonoha.platform.detect import session_desktop

    monkeypatch.delenv("XDG_SESSION_DESKTOP", raising=False)
    assert session_desktop() == ""


def test_a_pipe_named_like_the_bridge_is_not_offered_to_dlopen(tmp_path):
    # The ABI-suffixed candidates already require a regular file; the exact name was
    # accepted for merely existing, and ctypes.CDLL blocks in dlopen on a FIFO with
    # nothing for startup to fall back to while it waits.
    import os

    os.mkfifo(tmp_path / "libkoto-layer.so")

    assert find_layer_shell_library(tmp_path) is None


def test_an_ordinary_bridge_is_still_found(tmp_path):
    (tmp_path / "libkoto-layer.so").write_bytes(b"")

    assert find_layer_shell_library(tmp_path) is not None
