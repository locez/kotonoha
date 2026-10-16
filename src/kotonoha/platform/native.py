"""Thin ctypes wrapper around libkoto-layer.so (the Wayland layer-shell bridge).

All methods are safe no-ops when the bridge is unavailable — not built, a
non-Wayland (X11) session, or a Wayland compositor that does not implement
wlr-layer-shell (GNOME/Mutter, Weston, Cinnamon). In those cases the overlay
degrades: on X11 it is a normal top-most window (``_NET_WM_STATE_ABOVE``) that
the WM positions; on a layer-shell-less Wayland session it is an ordinary window
the compositor places and stacks — it cannot stay above other apps and cannot be
positioned precisely (``self.move()`` is a no-op on Wayland).

Backdrop blur is tracked separately from layer-shell (``blur_available`` vs
``available``): it rides on the same library but on its own protocols, so a
Wayland compositor without layer-shell can still frost the panel.
"""

from __future__ import annotations

import ctypes
import logging
import sysconfig
from pathlib import Path

from .detect import find_layer_shell_library, overlay_mode_available, should_disable_layer_shell
from .overlay_contracts import OverlayCapabilities

logger = logging.getLogger(__name__)


class LayerShellController:
    def __init__(self, package_dir: str, platform_name: str, current_desktop: str) -> None:
        self._platform = platform_name
        self._lib: ctypes.CDLL | None = None
        self._layer_shell = False
        self._blur_reason: str | None = None
        self._disabled_reason: str | None = None

        # wlr-layer-shell is Wayland-only. On X11 the .so still dlopens (its Qt /
        # wayland deps are present regardless of session), but every bridge call
        # no-ops on an xcb surface, silently killing the self.move()/top-most
        # fallback. Refuse it up front so the overlay takes its top-most path.
        if not platform_name.startswith("wayland"):
            self._disabled_reason = "Non-Wayland session; shown as a top-most window positioned by the WM."
            logger.info("%s", self._disabled_reason)
            return

        lib_path = find_layer_shell_library(package_dir)
        if not lib_path:
            self._disabled_reason = "libkoto-layer.so not found; run uv sync or build the wheel."
            logger.info("%s", self._disabled_reason)
            return

        try:
            lib = self._load(lib_path)
        except OSError as exc:
            self._disabled_reason = f"Failed to load layer-shell library: {exc}"
            logger.warning("%s", self._disabled_reason)
            return

        # The bridge is kept even without layer-shell: background blur rides on the
        # same library, and ext-background-effect-v1 works on compositors (Mutter)
        # that have no layer-shell at all.
        self._lib = lib

        # Ask the compositor first. The runtime registry probe answers for THIS
        # session — it catches every layer-shell-less compositor a name match misses
        # (Weston, Cinnamon, GNOME under any XDG value), avoids the Budgie/wlroots
        # false positive, and lets a GNOME-branded session that does advertise
        # zwlr_layer_shell_v1 use it. The desktop name decides nothing while the
        # probe is available; it is only the fallback for a bridge too old to have
        # the symbol.
        probe = getattr(lib, "koto_has_layer_shell", None)
        if probe is not None:
            if not probe():
                self._disabled_reason = (
                    "Compositor does not implement wlr-layer-shell; shown as an ordinary "
                    "window the compositor places and stacks."
                )
                logger.info("%s", self._disabled_reason)
                return
        elif should_disable_layer_shell(platform_name, current_desktop):
            self._disabled_reason = (
                "GNOME/Mutter Wayland does not implement wlr-layer-shell; "
                "falling back to a normal top-most window."
            )
            logger.info("%s", self._disabled_reason)
            return

        self._layer_shell = True

    @staticmethod
    def _load(lib_path: str) -> ctypes.CDLL:
        lib = ctypes.CDLL(lib_path)
        # Qt ABI handshake when the bridge exposes it: the bridge links Qt private /
        # QPA API, which has no cross-minor ABI guarantee, so refuse a bridge built
        # against a different Qt minor than the PyQt6 runtime. This only bites a
        # mismatched prebuilt wheel (manual pip); a distro build shares one system
        # Qt, and an older bridge without the symbol simply skips the check.
        if hasattr(lib, "koto_layer_qt_version"):
            from PyQt6.QtCore import QT_VERSION_STR

            lib.koto_layer_qt_version.restype = ctypes.c_char_p
            built = lib.koto_layer_qt_version().decode()
            if built.split(".")[:2] != QT_VERSION_STR.split(".")[:2]:
                raise OSError(f"bridge built against Qt {built}, PyQt6 runtime is Qt {QT_VERSION_STR}")
        if hasattr(lib, "koto_has_layer_shell"):
            lib.koto_has_layer_shell.restype = ctypes.c_int
        if hasattr(lib, "koto_has_blur"):
            lib.koto_has_blur.restype = ctypes.c_int
        lib.make_overlay.argtypes = [ctypes.c_void_p]
        lib.set_passthrough.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        lib.set_input_rect.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.set_anchor_position.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        lib.set_keyboard_interactivity.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        # Blur is newer than the other symbols; tolerate an older .so without it.
        if hasattr(lib, "set_blur_region"):
            lib.set_blur_region.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 5
        if hasattr(lib, "clear_blur"):
            lib.clear_blur.argtypes = [ctypes.c_void_p]
        if hasattr(lib, "koto_blur_object_count"):
            lib.koto_blur_object_count.restype = ctypes.c_int
        return lib

    @property
    def available(self) -> bool:
        """Whether the surface can be promoted to a wlr-layer-shell surface."""
        return self._layer_shell

    @property
    def blur_available(self) -> bool:
        """Whether the compositor can blur a surface's backdrop, over either
        ext-background-effect-v1 (KWin 6.7+, Mutter) or org_kde_kwin_blur (Plasma
        <= 6.6). Independent of layer-shell, so the frosted-glass options can be
        offered wherever the blur actually renders instead of being guessed from
        the desktop name.

        Read live, not cached. ext-background-effect-v1 sends its `capabilities`
        event again whenever the answer changes, and the bridge keeps a listener on
        the bound manager, so a cached Python answer was the one thing that could
        still report blur after the compositor withdrew it — or keep the options
        disabled after it gained it, until the process restarted."""
        if self._lib is None:
            # A non-Wayland session skips loading the bridge on purpose, which is
            # not the same as a load that failed — the settings window would
            # otherwise report a broken install on every X11 desktop.
            self._blur_reason = "session" if not self._platform.startswith("wayland") else "bridge"
            return False
        if not hasattr(self._lib, "koto_has_blur"):
            self._blur_reason = "build"
            return False
        if bool(self._lib.koto_has_blur()):
            self._blur_reason = None
            return True
        self._blur_reason = "protocol"
        return False

    @property
    def blur_disabled_reason(self) -> str | None:
        """Why blur is unavailable, as a stable cause the UI can translate.

        "session" — not a Wayland session, so the bridge is skipped on purpose.
        "bridge" — the native library did not load at all.
        "protocol" — the compositor advertises neither blur protocol.
        "build" — this build has no blur support compiled in.
        None when blur is available. A cause code rather than a sentence, so the
        settings window can say which one it is in the user's language instead of
        showing the same generic hint for every case.
        """
        if self.blur_available:
            return None
        return self._blur_reason

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    @property
    def capabilities(self) -> OverlayCapabilities:
        return OverlayCapabilities.from_controller(self)

    def overlay_mode_available(self) -> bool:
        return overlay_mode_available(
            self._platform, has_layer_shell=self.available, layer_shell_disabled=self._disabled_reason is not None
        )

    # --- bridge calls (no-op when unavailable) ---
    #
    # The layer-shell calls also require the protocol itself, not just a loaded
    # bridge: the library stays loaded for blur on compositors without layer-shell.

    def make_overlay(self, window_ptr: int) -> None:
        if self._lib and self._layer_shell:
            self._lib.make_overlay(ctypes.c_void_p(window_ptr))

    def set_passthrough(self, window_ptr: int, enabled: bool) -> None:
        if self._lib:
            self._lib.set_passthrough(ctypes.c_void_p(window_ptr), enabled)

    def set_input_rect(self, window_ptr: int, x: int, y: int, w: int, h: int) -> None:
        if self._lib:
            self._lib.set_input_rect(ctypes.c_void_p(window_ptr), x, y, w, h)

    def set_anchor_position(self, window_ptr: int, x: int, y: int) -> None:
        if self._lib and self._layer_shell:
            self._lib.set_anchor_position(ctypes.c_void_p(window_ptr), x, y)

    def set_keyboard_interactivity(self, window_ptr: int, enabled: bool) -> None:
        if self._lib and self._layer_shell:
            self._lib.set_keyboard_interactivity(ctypes.c_void_p(window_ptr), enabled)

    def set_blur_region(self, window_ptr: int, x: int, y: int, w: int, h: int, radius: int) -> None:
        if self._lib and hasattr(self._lib, "set_blur_region"):
            self._lib.set_blur_region(ctypes.c_void_p(window_ptr), x, y, w, h, radius)

    def clear_blur(self, window_ptr: int) -> None:
        if self._lib and hasattr(self._lib, "clear_blur"):
            self._lib.clear_blur(ctypes.c_void_p(window_ptr))

    @property
    def blur_object_count(self) -> int:
        """Compositor-side blur objects this process is holding.

        The bridge keys them on the wl_surface, so one left behind when a surface
        is rebuilt can never be found again. Exported so a test can assert that
        repeated rebuilds do not accumulate them; -1 when the bridge is too old to
        report it."""
        if self._lib is None or not hasattr(self._lib, "koto_blur_object_count"):
            return -1
        return int(self._lib.koto_blur_object_count())


def default_package_dir() -> str:
    source_dir = Path(__file__).parent
    if source_dir.name == "platform":
        source_dir = source_dir.parent
    installed_dir = Path(sysconfig.get_path("platlib")) / source_dir.name
    if find_layer_shell_library(installed_dir) is not None:
        return str(installed_dir)
    return str(source_dir)
