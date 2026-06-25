"""Thin ctypes wrapper around libkoto-layer.so (the Wayland layer-shell bridge).

All methods are safe no-ops when the native library is unavailable (library not
built, X11 session, or GNOME/Mutter Wayland), so the overlay can call them
unconditionally and simply lose the "float above fullscreen" capability while
remaining a normal top-most window.
"""

from __future__ import annotations

import ctypes
import logging
import os

from .lyrics_loader import find_layer_shell_library, overlay_mode_available, should_disable_layer_shell

logger = logging.getLogger(__name__)


class LayerShellController:
    def __init__(self, package_dir: str, platform_name: str, current_desktop: str) -> None:
        self._platform = platform_name
        self._lib: ctypes.CDLL | None = None
        self._disabled_reason: str | None = None

        if should_disable_layer_shell(platform_name, current_desktop):
            self._disabled_reason = (
                "GNOME/Mutter Wayland does not implement wlr-layer-shell; "
                "falling back to a normal top-most window."
            )
            logger.info("%s", self._disabled_reason)
            return

        lib_path = find_layer_shell_library(package_dir)
        if not lib_path:
            self._disabled_reason = "libkoto-layer.so not found; run build_bridge.sh."
            logger.info("%s", self._disabled_reason)
            return

        try:
            self._lib = self._load(lib_path)
        except OSError as exc:
            self._disabled_reason = f"Failed to load layer-shell library: {exc}"
            logger.warning("%s", self._disabled_reason)

    @staticmethod
    def _load(lib_path: str) -> ctypes.CDLL:
        lib = ctypes.CDLL(lib_path)
        lib.make_overlay.argtypes = [ctypes.c_void_p]
        lib.set_passthrough.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        lib.set_anchor_position.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        lib.set_keyboard_interactivity.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        return lib

    @property
    def available(self) -> bool:
        return self._lib is not None

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    def overlay_mode_available(self) -> bool:
        return overlay_mode_available(
            self._platform, has_layer_shell=self.available, layer_shell_disabled=self._disabled_reason is not None
        )

    # --- bridge calls (no-op when unavailable) ---

    def make_overlay(self, window_ptr: int) -> None:
        if self._lib:
            self._lib.make_overlay(ctypes.c_void_p(window_ptr))

    def set_passthrough(self, window_ptr: int, enabled: bool) -> None:
        if self._lib:
            self._lib.set_passthrough(ctypes.c_void_p(window_ptr), enabled)

    def set_anchor_position(self, window_ptr: int, x: int, y: int) -> None:
        if self._lib:
            self._lib.set_anchor_position(ctypes.c_void_p(window_ptr), x, y)

    def set_keyboard_interactivity(self, window_ptr: int, enabled: bool) -> None:
        if self._lib:
            self._lib.set_keyboard_interactivity(ctypes.c_void_p(window_ptr), enabled)


def default_package_dir() -> str:
    return os.path.dirname(__file__)
