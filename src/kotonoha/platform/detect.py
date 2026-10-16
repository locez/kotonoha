"""Locate and gate the Wayland layer-shell native library.

Mirrors BiliHUD's layer_shell_loader.py. Pure logic (no Qt/ctypes here) so it
can be unit-tested without a display.
"""

from __future__ import annotations

import os
from pathlib import Path

LAYER_SHELL_LIBRARY_NAME = "libkoto-layer.so"
LAYER_SHELL_LIBRARY_PREFIX = "libkoto-layer."
LAYER_SHELL_LIBRARY_SUFFIX = ".so"


def current_desktop() -> str:
    """Return the desktop identifier published by the current session."""
    return os.environ.get("XDG_CURRENT_DESKTOP", "")


def session_desktop() -> str:
    """Return the desktop identifier published by the session manager."""
    return os.environ.get("XDG_SESSION_DESKTOP", "")


def niri_socket() -> str:
    """Return niri's IPC socket path, which niri exports to every client it spawns.

    niri sets XDG_CURRENT_DESKTOP=niri only when it runs as a session (src/main.rs);
    started nested or without the session wrapper it leaves whatever the parent had,
    so the desktop name alone misses a real niri. This variable does not.
    """
    return os.environ.get("NIRI_SOCKET", "")


def should_disable_layer_shell(platform_name: str, current_desktop: str) -> bool:
    """GNOME/Mutter Wayland does not implement wlr-layer-shell -> disable it."""
    desktops = {part.strip().lower() for part in current_desktop.split(":")}
    return platform_name.startswith("wayland") and "gnome" in desktops


def overlay_mode_available(platform_name: str, has_layer_shell: bool, layer_shell_disabled: bool) -> bool:
    """Whether floating above fullscreen apps is achievable.

    True when the native library loaded, or when we are not on a Wayland
    session that had layer-shell disabled (e.g. X11, which can still stay on
    top via normal window flags).
    """
    return has_layer_shell or not (platform_name.startswith("wayland") and layer_shell_disabled)


def find_layer_shell_library(package_dir: str | Path) -> str | None:
    """Find libkoto-layer.so in the package dir, tolerating ABI-suffixed names."""
    package_path = Path(package_dir)
    exact_path = package_path / LAYER_SHELL_LIBRARY_NAME
    # is_file, not exists: the ABI-suffixed candidates below already require it, and
    # a FIFO or device node at the exact name was handed to ctypes.CDLL, where dlopen
    # blocks on the open. Startup has nothing to fall back to while that waits.
    if exact_path.is_file():
        return str(exact_path)

    candidates = sorted(
        path
        for path in package_path.glob(f"{LAYER_SHELL_LIBRARY_PREFIX}*{LAYER_SHELL_LIBRARY_SUFFIX}")
        if path.is_file()
    )
    if candidates:
        return str(candidates[0])

    return None
