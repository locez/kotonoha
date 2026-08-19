"""Stubs the overlay tests build an overlay on.

Shared because the overlay is exercised from two files — what the panel looks like,
and what it asks of the platform — and both need the same scaffolding.
"""

from PyQt6.QtCore import QRect

from kotonoha.platform.native import LayerShellController
from kotonoha.platform.overlay_contracts import OverlayOperationResult


class UnavailableController(LayerShellController):
    def __init__(self) -> None:
        super().__init__("", "wayland", "GNOME")

class LayerShellStub(LayerShellController):
    """Takes the layer-shell code path; every bridge call stays a no-op (no .so).

    The registry picks an adapter from the Qt platform name, which is "offscreen"
    under test, so an overlay built with this stub is given the ordinary-window
    adapter. Tests that exercise the layer-shell paths use `layer_shell_platform`
    to put the real adapter in place.
    """

    def __init__(self) -> None:
        super().__init__("", "wayland", "KDE")

    @property
    def available(self) -> bool:
        return True

def layer_shell_platform(overlay):
    """Give the overlay the Layer Shell adapter the registry cannot select offscreen."""
    from kotonoha.platform.layer_shell import LayerShellPlatform

    overlay._platform = LayerShellPlatform(overlay._host, overlay._controller)
    return overlay._platform

class FakeScreen:
    def __init__(self, name: str, x: int, y: int, width: int, height: int) -> None:
        self._name = name
        self._geometry = QRect(x, y, width, height)

    def name(self) -> str:
        return self._name

    def geometry(self) -> QRect:
        return self._geometry

def _freeze_media_clock(overlay, value: float) -> None:
    """Pin the media clock so an offset assertion is not racing wall time.

    MediaClock.now is a method and the value it returns comes from wall time, so
    there is no seam to inject; replacing the attribute is the only way to freeze
    it, and ty rejects assigning over a method. The suppression is confined here
    rather than repeated at each call site, and it disappears if MediaClock ever
    takes an injected time source.
    """
    overlay._clock.now = lambda: value  # ty: ignore[invalid-assignment]

def _ok():

    return OverlayOperationResult.success()
