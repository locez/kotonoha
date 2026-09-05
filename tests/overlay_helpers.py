"""Stubs the overlay tests build an overlay on.

Shared because the overlay is exercised from two files — what the panel looks like,
and what it asks of the platform — and both need the same scaffolding.
"""

from PyQt6.QtCore import QRect

from kotonoha.display.offsets import EMPTY_TRACK_OFFSETS, TrackOffsetReader
from kotonoha.platform.native import LayerShellController
from kotonoha.platform.overlay_contracts import SurfaceResult
from kotonoha.platform.window_platform import DefaultOverlayPlatformFactory
from kotonoha.ui.overlay import LyricsOverlay as ProductionLyricsOverlay
from kotonoha.ui.overlay.state import LyricsState


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
    """Return the Layer Shell surface selected by the test composition root."""
    return overlay._platform

class FakeScreen:
    def __init__(self, name: str, x: int, y: int, width: int, height: int) -> None:
        self._name = name
        self._geometry = QRect(x, y, width, height)

    def name(self) -> str:
        return self._name

    def geometry(self) -> QRect:
        return self._geometry

def _ok():
    return SurfaceResult.applied()


def build_overlay(
    state: LyricsState,
    config,
    controller=None,
    *,
    track_offsets: TrackOffsetReader = EMPTY_TRACK_OFFSETS,
):
    """Build an overlay through the same factory boundary as production."""
    selected_controller = controller if controller is not None else UnavailableController()
    layer_shell = isinstance(selected_controller, LayerShellStub)
    factory = DefaultOverlayPlatformFactory(
        selected_controller,
        platform_name="wayland" if layer_shell else "offscreen",
        current_desktop="KDE" if layer_shell else "GNOME",
        niri_socket_present=False,
    )
    return ProductionLyricsOverlay(
        state,
        config,
        platform_factory=factory,
        track_offsets=track_offsets,
    )
