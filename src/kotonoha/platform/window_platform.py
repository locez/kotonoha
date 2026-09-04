"""Ordered providers for selecting Kotonoha's overlay platform adapter."""

from __future__ import annotations

from typing import Protocol

from PyQt6.QtGui import QGuiApplication

from .detect import current_desktop, niri_socket, session_desktop
from .layer_shell import LayerShellAnchorDragStrategy, LayerShellPlatform, NiriLayerShellDragStrategy
from .native import LayerShellController, default_package_dir
from .overlay_contracts import (
    BlurPort,
    DragPort,
    InputRegionPort,
    LayerShellBridge,
    OutputBindingPort,
    OverlayPlatform,
    OverlayPlatformAdapters,
    PlacementPort,
    SurfacePort,
    WindowHost,
)
from .qt_window import QtWindowPlatform


class _Provider(Protocol):
    def select(self, platform_name: str, desktop: str, host: WindowHost) -> OverlayPlatform | None: ...

class _LayerShellDragProvider(Protocol):
    """Create a strategy when a Layer Shell compositor is recognized."""

    def create(self, desktop: str, host: WindowHost, controller: LayerShellBridge) -> DragPort | None: ...


class _NiriLayerShellDragProvider:
    """Select global-delta dragging for niri's asynchronous configure behavior."""

    def __init__(self, *, socket_present: bool) -> None:
        # The socket is the reliable half: niri exports NIRI_SOCKET to every client
        # it spawns, but publishes the desktop name only when it runs as a session.
        # It is read once at the composition boundary and handed over here, because
        # reading the process environment from inside selection made the answer
        # depend on whoever happened to launch the test.
        self._socket_present = socket_present

    def create(self, desktop: str, host: WindowHost, controller: LayerShellBridge) -> DragPort | None:
        desktops = {part.strip().lower() for part in desktop.split(":")}
        if "niri" not in desktops and not self._socket_present:
            return None
        return NiriLayerShellDragStrategy(host, controller)


class _DefaultLayerShellDragProvider:
    """Provide the existing local-anchor model for unrecognized compositors."""

    def create(self, desktop: str, host: WindowHost, controller: LayerShellBridge) -> DragPort | None:
        del desktop
        return LayerShellAnchorDragStrategy(host, controller)


class _LayerShellProvider:
    def __init__(
        self,
        controller: LayerShellBridge,
        drag_providers: tuple[_LayerShellDragProvider, ...] | None = None,
        *,
        niri_socket_present: bool | None = None,
    ) -> None:
        self._controller = controller
        # An explicit None, not a falsy check: an empty tuple is a caller asking for
        # no drag providers at all, and the truthiness test silently reinstalled the
        # defaults instead.
        self._drag_providers = (
            drag_providers
            if drag_providers is not None
            else (
                _NiriLayerShellDragProvider(
                    socket_present=bool(niri_socket()) if niri_socket_present is None else niri_socket_present
                ),
                _DefaultLayerShellDragProvider(),
            )
        )

    def select(self, platform_name: str, desktop: str, host: WindowHost) -> OverlayPlatform | None:
        # The controller has already asked the compositor, and its probe outranks the
        # desktop name — checking the name again here demoted a session that does
        # advertise zwlr_layer_shell_v1 to an ordinary window, losing stacking,
        # precise placement and output binding. The name check remains inside the
        # controller as the fallback for a bridge too old to expose the probe.
        #
        # The name still selects the *drag* strategy below: no protocol reports
        # which compositor this is, and the two behaviours differ by compositor.
        if not platform_name.startswith("wayland") or not self._controller.available:
            return None
        for provider in self._drag_providers:
            strategy = provider.create(desktop, host, self._controller)
            if strategy is not None:
                adapter = LayerShellPlatform(host, self._controller, strategy)
                return _compose_adapter(
                    adapter,
                    input_region=adapter,
                    blur=adapter,
                    placement=adapter,
                    output_binding=adapter,
                    drag=adapter,
                )
        adapter = LayerShellPlatform(host, self._controller)
        return _compose_adapter(
            adapter,
            input_region=adapter,
            blur=adapter,
            placement=adapter,
            output_binding=adapter,
            drag=adapter,
        )


class _X11Provider:
    def __init__(self, controller: LayerShellBridge | None = None) -> None:
        self._controller = controller

    def select(self, platform_name: str, desktop: str, host: WindowHost) -> OverlayPlatform | None:
        del desktop
        if platform_name != "xcb":
            return None
        adapter = QtWindowPlatform(
            host, reason="X11 has no Layer Shell overlay capability.", blur=self._controller
        )
        return _compose_adapter(
            adapter,
            input_region=adapter,
            blur=adapter if adapter.capabilities.blur else None,
            placement=adapter if adapter.capabilities.client_positioning else None,
            output_binding=None,
            drag=adapter,
        )


class _WaylandFallbackProvider:
    def __init__(self, controller: LayerShellBridge | None = None) -> None:
        self._controller = controller

    def select(self, platform_name: str, desktop: str, host: WindowHost) -> OverlayPlatform | None:
        del desktop
        if not platform_name.startswith("wayland"):
            return None
        # Still hand over the bridge: a Wayland compositor without Layer Shell can
        # speak a blur protocol, which is exactly the Mutter case.
        adapter = QtWindowPlatform(
            host,
            reason="Wayland compositor does not provide Layer Shell.",
            blur=self._controller,
            # Wayland gives a client no way to place its own toplevel, and no
            # readback can tell: Qt reports the requested position either way.
            client_positioning=False,
            system_move=True,
            # Nor a way to set the window's opacity.
            window_opacity=False,
        )
        return _compose_adapter(
            adapter,
            input_region=adapter,
            blur=adapter if adapter.capabilities.blur else None,
            placement=adapter if adapter.capabilities.client_positioning else None,
            output_binding=None,
            drag=adapter,
        )


class _GenericFallbackProvider:
    def __init__(self, controller: LayerShellBridge | None = None) -> None:
        self._controller = controller

    def select(self, platform_name: str, desktop: str, host: WindowHost) -> OverlayPlatform:
        del platform_name, desktop
        adapter = QtWindowPlatform(
            host, reason="Layer Shell is unavailable on this platform.", blur=self._controller
        )
        return _compose_adapter(
            adapter,
            input_region=adapter,
            blur=adapter if adapter.capabilities.blur else None,
            placement=adapter if adapter.capabilities.client_positioning else None,
            output_binding=None,
            drag=adapter,
        )


def _compose_adapter(
    surface: SurfacePort,
    *,
    input_region: InputRegionPort | None,
    blur: BlurPort | None,
    placement: PlacementPort | None,
    output_binding: OutputBindingPort | None,
    drag: DragPort,
) -> OverlayPlatformAdapters:
    """Compose independent capability ports for one selected surface adapter."""
    return OverlayPlatformAdapters(
        surface=surface,
        input_region=input_region,
        blur=blur,
        placement=placement,
        output_binding=output_binding,
        drag=drag,
    )


class DefaultOverlayPlatformFactory:
    """Select the first claiming provider: Layer Shell, X11, Wayland, generic."""

    def __init__(
        self,
        controller: LayerShellBridge | None = None,
        *,
        platform_name: str | None = None,
        current_desktop: str | None = None,
        providers: tuple[_Provider, ...] | None = None,
        niri_socket_present: bool | None = None,
    ) -> None:
        if controller is None:
            selected_platform = platform_name if platform_name is not None else QGuiApplication.platformName()
            selected_desktop = current_desktop if current_desktop is not None else self._current_desktop()
            self._controller = LayerShellController(default_package_dir(), selected_platform, selected_desktop)
        else:
            self._controller = controller
        self._platform_name = platform_name
        self._current_desktop_value = current_desktop
        self._providers = (
            providers
            if providers is not None
            else (
                # The session is read once here, where the platform name and desktop
                # already come from, rather than from inside provider selection.
                _LayerShellProvider(
                    self._controller,
                    niri_socket_present=bool(niri_socket())
                    if niri_socket_present is None
                    else niri_socket_present,
                ),
                _X11Provider(self._controller),
                _WaylandFallbackProvider(self._controller),
                _GenericFallbackProvider(self._controller),
            )
        )
        # Settings and other ordinary windows share the session's blur facts but
        # must never become Layer Shell surfaces. Keep that role-specific choice
        # beside the overlay provider order instead of making the caller duplicate
        # platform detection.
        self._regular_window_providers = (
            _X11Provider(self._controller),
            _WaylandFallbackProvider(self._controller),
            _GenericFallbackProvider(self._controller),
        )

    @property
    def controller(self) -> LayerShellBridge:
        """Return the bridge retained by the factory for the selected adapters."""
        return self._controller

    def __call__(self, host: WindowHost) -> OverlayPlatform:
        platform_name = (
            self._platform_name if self._platform_name is not None else QGuiApplication.platformName()
        )
        desktop = self._current_desktop_value if self._current_desktop_value is not None else self._current_desktop()
        for provider in self._providers:
            platform = provider.select(platform_name, desktop, host)
            if platform is not None:
                return platform
        raise RuntimeError("No overlay platform provider claimed the session.")

    def for_regular_window(self, host: WindowHost) -> OverlayPlatform:
        """Create a normal Qt window adapter without Layer Shell or top-most flags."""
        platform_name = (
            self._platform_name if self._platform_name is not None else QGuiApplication.platformName()
        )
        desktop = self._current_desktop_value if self._current_desktop_value is not None else self._current_desktop()
        for provider in self._regular_window_providers:
            platform = provider.select(platform_name, desktop, host)
            if platform is not None:
                return platform
        raise RuntimeError("No regular-window platform provider claimed the session.")

    @staticmethod
    def _current_desktop() -> str:
        app = QGuiApplication.instance()
        qt_desktop = str(app.property("xdg_current_desktop") or "") if app is not None else ""
        detected_desktops = (current_desktop(), session_desktop())
        return ":".join(value for value in (qt_desktop, *detected_desktops) if value)
