"""Contracts describing platform features available to the overlay."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OverlayCapabilities:
    """Platform features and the reasons individual features are unavailable."""

    layer_shell: bool
    blur: bool
    input_region: bool = False
    output_rebinding: bool = False
    layer_shell_reason: str | None = None
    blur_reason: str | None = None
    input_region_reason: str | None = None
    output_rebinding_reason: str | None = None
    # Whether the client can place its own window. Layer Shell positions by anchor
    # and X11 by the window manager; a Wayland compositor without Layer Shell
    # ignores a client-side move of a toplevel, and no readback can tell — Qt
    # reports the requested position either way, measured on KWin — so this is
    # stated from the protocol rather than observed.
    client_positioning: bool = True
    client_positioning_reason: str | None = None
    system_move: bool = False
    system_move_reason: str | None = None
    # Whether setting the window's opacity does anything. Wayland has no client-side
    # window-opacity protocol, so animating it there only logs "plugin does not
    # support setting window opacity" once per frame. Which session this is remains a
    # platform fact: presentation asks, the adapter answers.
    window_opacity: bool = True
    window_opacity_reason: str | None = None

    @classmethod
    def from_controller(cls, controller: LayerShellBridge, *, window_opacity: bool = True) -> OverlayCapabilities:
        layer_shell = controller.available
        blur = controller.blur_available
        return cls(
            layer_shell=layer_shell,
            blur=blur,
            input_region=layer_shell,
            output_rebinding=layer_shell,
            layer_shell_reason=controller.disabled_reason,
            # The controller already reports which cause it is — session, bridge,
            # protocol or build — and the UI translates that. Replacing it with one
            # sentence here would collapse four distinct situations into one.
            blur_reason=controller.blur_disabled_reason,
            # Both ride on Layer Shell, so they are unavailable for the same reason
            # it is. Leaving these None gave the UI a disabled capability it could
            # not explain, which is the one thing this value object exists to avoid.
            input_region_reason=None if layer_shell else (controller.disabled_reason or "Layer Shell is unavailable."),
            output_rebinding_reason=None
            if layer_shell
            else (controller.disabled_reason or "Layer Shell is unavailable."),
            window_opacity=window_opacity,
            window_opacity_reason=None if window_opacity else _NO_WINDOW_OPACITY,
        )


_NO_WINDOW_OPACITY = "Wayland has no client-side window-opacity protocol."


@dataclass(frozen=True, slots=True)
class WindowPoint:
    """A screen or window-local point without a GUI toolkit dependency."""

    x: int
    y: int


@dataclass(frozen=True, slots=True)
class WindowRectangle:
    """A rectangle used for window and output geometry."""

    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Output:
    """A connected output described without a GUI toolkit dependency."""

    name: str
    geometry: WindowRectangle


@dataclass(frozen=True, slots=True)
class WindowPolicy:
    """Toolkit-neutral window flags and input attributes."""

    transparent_for_input: bool = False
    does_not_accept_focus: bool = False
    show_without_activating: bool = False
    mouse_events_transparent: bool = False
    recreate_surface: bool = True


class SurfaceState(Enum):
    """Lifecycle state of the mapped overlay surface."""

    UNPREPARED = "unprepared"
    PREPARED = "prepared"
    ACTIVE = "active"
    REBINDING = "rebinding"
    DEGRADED = "degraded"
    CLOSING = "closing"
    CLOSED = "closed"


class SurfaceResultStatus(Enum):
    """Outcome categories returned by a platform operation."""

    APPLIED = "applied"
    NOT_SUPPORTED = "not-supported"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SurfaceResult:
    """Result of a platform operation, including retryability and failure reason."""

    status: SurfaceResultStatus
    reason: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.status is SurfaceResultStatus.APPLIED:
            if self.reason is not None:
                raise ValueError("Applied results cannot contain a failure reason")
            if self.retryable:
                raise ValueError("Applied results cannot be retryable")
            return
        if not self.reason:
            raise ValueError("Non-applied results must contain a reason")
        if self.retryable and self.status is not SurfaceResultStatus.FAILED:
            raise ValueError("Only failed results can be retryable")

    @property
    def succeeded(self) -> bool:
        """Whether the operation was applied by the platform."""
        return self.status is SurfaceResultStatus.APPLIED

    @classmethod
    def applied(cls) -> SurfaceResult:
        """Report that the requested operation was applied."""
        return cls(SurfaceResultStatus.APPLIED)

    @classmethod
    def not_supported(cls, reason: str) -> SurfaceResult:
        """Report that the selected platform has no such capability."""
        return cls(SurfaceResultStatus.NOT_SUPPORTED, reason=reason)

    @classmethod
    def rejected(cls, reason: str) -> SurfaceResult:
        """Report that the platform refused an otherwise supported operation."""
        return cls(SurfaceResultStatus.REJECTED, reason=reason)

    @classmethod
    def failed(cls, reason: str, *, retryable: bool = False) -> SurfaceResult:
        """Report an operation failure and whether retrying may succeed."""
        return cls(SurfaceResultStatus.FAILED, reason=reason, retryable=retryable)

class DragMode(Enum):
    """Movement mechanism selected for one press gesture."""

    SYSTEM = "system"
    MANUAL = "manual"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DragStartResult:
    """Result of starting a drag."""

    mode: DragMode
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.mode is DragMode.UNAVAILABLE and not self.reason:
            raise ValueError("Unavailable drag results must include a reason")
        if self.mode is not DragMode.UNAVAILABLE and self.reason is not None:
            raise ValueError("Available drag results cannot include a failure reason")


@dataclass(frozen=True, slots=True)
class DragGeometry:
    """Describe the surface and visible panel in one coordinate space.

    ``panel`` is relative to the transparent surface. The panel is deliberately
    not bounded here: each platform strategy owns any compositor-specific output
    constraint while the shared drag controller keeps the geometry toolkit-free.
    """

    surface_position: WindowPoint
    panel: WindowRectangle

    def __post_init__(self) -> None:
        if self.panel.width <= 0 or self.panel.height <= 0:
            raise ValueError("Drag panel geometry must be positive")

    def surface_for_panel(self, position: WindowPoint) -> WindowPoint:
        """Translate a visible-panel position into a surface position."""
        return WindowPoint(position.x - self.panel.x, position.y - self.panel.y)


@dataclass(frozen=True, slots=True)
class DragUpdateResult:
    """Return the platform result together with the position actually applied."""

    operation: SurfaceResult
    position: WindowPoint

    @property
    def succeeded(self) -> bool:
        """Whether the platform applied this drag step."""
        return self.operation.succeeded

    @property
    def reason(self) -> str | None:
        """Return the platform failure reason, when present."""
        return self.operation.reason


class WindowHost(Protocol):
    """Toolkit-neutral surface used by platform adapters."""

    def apply_window_policy(self, policy: WindowPolicy) -> None: ...
    def is_alive(self) -> bool: ...
    def native_window_pointer(self) -> int | None: ...
    def geometry(self) -> WindowRectangle: ...
    def window_position(self) -> WindowPoint | None: ...
    def screen_geometry(self) -> WindowRectangle | None: ...
    def bind_output(self, output: WindowRectangle) -> None: ...
    def hide_window(self) -> None: ...
    def destroy_surface(self) -> None: ...
    def move_window(self, position: WindowPoint) -> None: ...
    def start_system_move(self) -> bool:
        """Ask the compositor to own the move begun by the current press event."""
        ...
    # Shape where an ordinary window accepts input. Two calls rather than one
    # nullable argument: the public operation uses None to mean "click through
    # everywhere", and a mask of None conventionally means "no shaping at all",
    # which is its opposite. Keeping them apart leaves nothing to interpret.
    def set_input_mask(self, region: WindowRectangle) -> None: ...
    def clear_input_mask(self) -> None: ...
    def refresh(self) -> None: ...


class SurfacePort(Protocol):
    """Lifecycle operations for the mapped surface itself."""

    @property
    def capabilities(self) -> OverlayCapabilities:
        """Describe the operations supported by this surface adapter."""
        ...

    def prepare(self) -> SurfaceResult:
        """Create or configure native resources without mapping the surface."""
        ...

    def activate(self) -> SurfaceResult:
        """Map the prepared surface and make it available for presentation."""
        ...

    def release_surface(self) -> SurfaceResult:
        """Release resources attached to the current native surface."""
        ...

    def close(self) -> SurfaceResult:
        """Release the surface and reject future platform operations."""
        ...


class InputRegionPort(Protocol):
    """Capability for changing the surface input region."""

    def set_input_region(self, region: WindowRectangle | None) -> SurfaceResult:
        """Apply a region, or make the entire surface click-through when absent."""
        ...


class BlurPort(Protocol):
    """Capability for applying compositor blur to a surface region."""

    def set_blur_region(self, region: WindowRectangle | None, radius: int = 0) -> SurfaceResult:
        """Apply or clear compositor blur for the supplied surface region."""
        ...


class PlacementPort(Protocol):
    """Capability for moving a mapped surface or ordinary window."""

    def move_to(self, position: WindowPoint) -> SurfaceResult:
        """Request a platform-specific movement and report whether it applied."""
        ...


class OutputBindingPort(Protocol):
    """Capability that releases a surface before it is recreated on another output."""

    def release_for_output_rebind(self) -> SurfaceResult:
        """Release the current output-bound resources while keeping the adapter alive."""
        ...


class DragPort(Protocol):
    """Optional strategy boundary for platform-specific dragging."""

    @property
    def client_positioning(self) -> bool:
        """Whether a client-side movement can be trusted for persistence."""
        ...

    @property
    def system_move(self) -> bool:
        """Whether a press can delegate movement to the compositor."""
        ...

    @property
    def can_rebind_output(self) -> bool:
        """Whether release coordinates can safely select another output."""
        ...

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
        geometry: DragGeometry,
    ) -> DragStartResult:
        """Start a manual or compositor-owned gesture from the pointer coordinates."""
        ...

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
        geometry: DragGeometry,
    ) -> DragUpdateResult:
        """Apply one drag update and report the resulting position."""
        ...

    def end_drag(self) -> None:
        """Release the platform-specific gesture state."""
        ...

    def set_position(self, position: WindowPoint) -> None:
        """Synchronize the strategy with a position committed elsewhere."""
        ...

class OverlayPlatform(Protocol):
    """Typed composition of independent platform capability ports."""

    @property
    def capabilities(self) -> OverlayCapabilities:
        """Return the selected session capability model."""
        ...

    @property
    def surface(self) -> SurfacePort:
        """Return lifecycle operations for the selected surface."""
        ...

    @property
    def input_region(self) -> InputRegionPort | None:
        """Return input-region operations when the adapter provides them."""
        ...

    @property
    def blur(self) -> BlurPort | None:
        """Return compositor-blur operations when the adapter provides them."""
        ...

    @property
    def placement(self) -> PlacementPort | None:
        """Return placement operations when client movement is meaningful."""
        ...

    @property
    def output_binding(self) -> OutputBindingPort | None:
        """Return output-rebind operations when the surface is output-bound."""
        ...

    @property
    def drag(self) -> DragPort:
        """Return the platform-specific drag strategy."""
        ...


@dataclass(frozen=True, slots=True)
class OverlayPlatformAdapters:
    """Wire independent platform ports selected for one Qt surface."""

    surface: SurfacePort
    input_region: InputRegionPort | None
    blur: BlurPort | None
    placement: PlacementPort | None
    output_binding: OutputBindingPort | None
    drag: DragPort

    @property
    def capabilities(self) -> OverlayCapabilities:
        """Return the live capability snapshot supplied by the surface adapter."""
        return self.surface.capabilities


class OverlayPlatformFactory(Protocol):
    """Factory for an adapter bound to one window host."""

    def __call__(self, host: WindowHost) -> OverlayPlatform:
        """Compose platform capability ports for a specific window host."""
        ...


class LayerShellBridge(Protocol):
    """What an overlay adapter needs from the native bridge.

    Adapters and the provider registry depend on this rather than on
    ``LayerShellController`` itself, so a session can be described in a test
    without constructing the real ctypes wrapper."""

    @property
    def available(self) -> bool: ...

    @property
    def blur_available(self) -> bool: ...

    @property
    def disabled_reason(self) -> str | None: ...

    @property
    def blur_disabled_reason(self) -> str | None: ...

    def make_overlay(self, window_ptr: int) -> None: ...

    def set_passthrough(self, window_ptr: int, enabled: bool) -> None: ...

    def set_input_rect(self, window_ptr: int, x: int, y: int, w: int, h: int) -> None: ...

    def set_anchor_position(self, window_ptr: int, x: int, y: int) -> None: ...

    def set_blur_region(self, window_ptr: int, x: int, y: int, w: int, h: int, radius: int) -> None: ...

    def clear_blur(self, window_ptr: int) -> None: ...
