"""Locate and gate the Wayland layer-shell native library.

Mirrors BiliHUD's layer_shell_loader.py. Pure logic (no Qt/ctypes here) so it
can be unit-tested without a display.
"""

from __future__ import annotations

from pathlib import Path

LAYER_SHELL_LIBRARY_NAME = "libkoto-layer.so"
LAYER_SHELL_LIBRARY_PREFIX = "libkoto-layer."
LAYER_SHELL_LIBRARY_SUFFIX = ".so"


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
    if exact_path.exists():
        return str(exact_path)

    candidates = sorted(
        path
        for path in package_path.glob(f"{LAYER_SHELL_LIBRARY_PREFIX}*{LAYER_SHELL_LIBRARY_SUFFIX}")
        if path.is_file()
    )
    if candidates:
        return str(candidates[0])

    return None
