"""Ordinary top-most window implementation of the overlay contract."""

from __future__ import annotations

from .overlay_contracts import (
    _NO_WINDOW_OPACITY,
    DragGeometry,
    DragMode,
    DragPort,
    DragStartResult,
    DragUpdateResult,
    LayerShellBridge,
    OverlayCapabilities,
    SurfaceResult,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)

_NO_CLIENT_POSITIONING = "This compositor ignores a client-side move of an ordinary window."


class OrdinaryWindowDragStrategy:
    """Choose compositor-owned or client-side movement for an ordinary window."""

    def __init__(self, host: WindowHost, *, client_positioning: bool = True, system_move: bool = False) -> None:
        self._host = host
        self._client_positioning = client_positioning
        self._system_move = system_move
        self._origin: WindowPoint | None = None
        self._window_origin = WindowPoint(0, 0)
        self._surface_position = WindowPoint(0, 0)
        self._panel_position: WindowPoint | None = None

    @property
    def client_positioning(self) -> bool:
        """Return whether ordinary-window moves can be persisted on this session."""
        return self._client_positioning

    @property
    def can_rebind_output(self) -> bool:
        """Return whether Qt coordinates can safely select another output."""
        return self._client_positioning

    @property
    def system_move(self) -> bool:
        """Whether a press delegates movement to the compositor."""
        return self._system_move

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
        geometry: DragGeometry,
    ) -> DragStartResult:
        del global_position
        if self._system_move:
            # Wayland requires the move request to carry the serial from this
            # press. The host calls QWindow.startSystemMove immediately rather
            # than trying to reconstruct the gesture from later pointer events.
            if self._host.start_system_move():
                return DragStartResult(DragMode.SYSTEM)
            return DragStartResult(DragMode.UNAVAILABLE, "The compositor declined the system window move.")
        current = self._host.window_position()
        if current is None:
            current = self._window_origin
        self._window_origin = current
        self._surface_position = geometry.surface_position
        self._panel_position = WindowPoint(
            geometry.surface_position.x + geometry.panel.x,
            geometry.surface_position.y + geometry.panel.y,
        )
        self._origin = local_position
        return DragStartResult(DragMode.MANUAL)

    def set_position(self, position: WindowPoint) -> None:
        """Synchronize the drag origin after an ordinary-window move."""
        self._window_origin = position

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
        geometry: DragGeometry,
    ) -> DragUpdateResult:
        del global_position
        origin = self._origin
        panel_position = self._panel_position
        if origin is None or panel_position is None:
            return DragUpdateResult(
                SurfaceResult.rejected("Window drag has not started"),
                self._surface_position,
            )
        # move_to already refuses here; the drag path went straight to the host and
        # so reported every update as applied on a compositor that moves nothing.
        # The two paths have to answer the same question the same way.
        if not self._client_positioning:
            return DragUpdateResult(
                SurfaceResult.not_supported(_NO_CLIENT_POSITIONING),
                self._surface_position,
            )
        attempted_panel = WindowPoint(
            panel_position.x + local_position.x - origin.x,
            panel_position.y + local_position.y - origin.y,
        )
        surface_position = geometry.surface_for_panel(attempted_panel)
        displacement = WindowPoint(
            surface_position.x - self._surface_position.x,
            surface_position.y - self._surface_position.y,
        )
        position = WindowPoint(
            self._window_origin.x + displacement.x,
            self._window_origin.y + displacement.y,
        )
        try:
            if displacement != WindowPoint(0, 0):
                self._host.move_window(position)
        except RuntimeError as exc:
            return DragUpdateResult(
                SurfaceResult.failed(f"Window move failed: {exc}", retryable=True),
                self._surface_position,
            )
        # The window origin advances; the press point does not. The window follows
        # the pointer, so the pointer's local position re-settles toward where the
        # press landed — advancing that anchor too counts the settling twice and
        # the window snaps back or stalls. Same model as the Layer Shell anchor.
        self._window_origin = position
        self._surface_position = surface_position
        self._panel_position = attempted_panel
        return DragUpdateResult(SurfaceResult.applied(), surface_position)

    def end_drag(self) -> None:
        self._origin = None
        self._panel_position = None


class QtWindowPlatform:
    """Use toolkit window flags when compositor-specific overlay APIs are absent."""

    def __init__(
        self,
        host: WindowHost,
        *,
        reason: str | None = None,
        blur: LayerShellBridge | None = None,
        client_positioning: bool = True,
        window_opacity: bool = True,
        system_move: bool = False,
    ) -> None:
        self._host = host
        self._reason = reason
        # Wayland without Layer Shell ignores a client-side move of a toplevel, and
        # the client cannot detect it: Qt reports the requested position either way.
        # So the provider states it here instead of the adapter guessing afterwards.
        self._client_positioning = client_positioning
        # Wayland has no client-side window-opacity protocol either, and the same
        # provider knows which session this is.
        self._window_opacity = window_opacity
        self._system_move = system_move
        self._surface_released = False
        self._closed = False
        # Blur is a separate capability from Layer Shell: Mutter offers no
        # layer-shell and does speak ext-background-effect-v1, so hardcoding
        # blur=False here dropped the frosted panel on exactly the compositor the
        # blur work was for. When a bridge is available the answer comes from it.
        self._blur = blur
        self._drag_strategy: DragPort = OrdinaryWindowDragStrategy(
            host, client_positioning=client_positioning, system_move=system_move
        )

    @property
    def capabilities(self) -> OverlayCapabilities:
        blur = self._blur is not None and self._blur.blur_available
        return OverlayCapabilities(
            layer_shell=False,
            blur=blur,
            input_region=True,
            output_rebinding=False,
            layer_shell_reason=self._reason,
            blur_reason=None
            if blur
            else (
                self._blur.blur_disabled_reason
                if self._blur is not None
                else "Ordinary windows have no bridge to request compositor blur."
            ),
            output_rebinding_reason="Ordinary windows cannot rebind a mapped output.",
            client_positioning=self._client_positioning,
            client_positioning_reason=None
            if self._client_positioning
            else _NO_CLIENT_POSITIONING,
            system_move=self._system_move,
            system_move_reason=None if self._system_move else "System window movement is unavailable.",
            window_opacity=self._window_opacity,
            window_opacity_reason=None if self._window_opacity else _NO_WINDOW_OPACITY,
        )

    @property
    def client_positioning(self) -> bool:
        """Expose the drag-relevant placement capability through the drag port."""
        return self._client_positioning

    @property
    def system_move(self) -> bool:
        """Expose whether the ordinary window delegates movement to Wayland."""
        return self._system_move

    @property
    def can_rebind_output(self) -> bool:
        """Delegate release-time output selection to the window drag strategy."""
        return self._drag_strategy.can_rebind_output

    def prepare(self) -> SurfaceResult:
        if self._closed:
            return SurfaceResult.rejected("The ordinary-window adapter is closed.")
        try:
            self._host.apply_window_policy(WindowPolicy(recreate_surface=True))
        except RuntimeError as exc:
            return SurfaceResult.failed(f"Window initialization failed: {exc}", retryable=True)
        return SurfaceResult.applied()

    def activate(self) -> SurfaceResult:
        if self._closed:
            return SurfaceResult.rejected("The ordinary-window adapter is closed.")
        self._surface_released = False
        return SurfaceResult.applied()

    def set_input_region(self, region: WindowRectangle | None) -> SurfaceResult:
        if self._closed:
            return SurfaceResult.rejected("The ordinary-window adapter is closed.")
        try:
            self._host.apply_window_policy(
                WindowPolicy(
                    does_not_accept_focus=region is None,
                    show_without_activating=region is None,
                    mouse_events_transparent=region is None,
                    recreate_surface=False,
                )
            )
            # The rectangle was ignored before: only the whole-window pass-through
            # switch was applied, so an unlocked ordinary window kept accepting
            # clicks across its entire transparent area and swallowed input meant
            # for whatever sits behind it. Click-through is carried by the policy
            # flag above, so the mask is cleared rather than set to nothing —
            # a shaping that fought the flag would be ambiguous.
            if region is None:
                self._host.clear_input_mask()
            else:
                self._host.set_input_mask(region)
            self._host.refresh()
        except RuntimeError as exc:
            return SurfaceResult.failed(f"Input mode update failed: {exc}", retryable=True)
        return SurfaceResult.applied()

    def set_blur_region(self, region: WindowRectangle | None, radius: int = 0) -> SurfaceResult:
        if self._closed:
            return SurfaceResult.rejected("The ordinary-window adapter is closed.")
        # An ordinary window can still carry a compositor blur where the protocol
        # exists — Mutter has no Layer Shell and does speak it — so this is a real
        # operation here, not a permanent failure.
        capabilities = self.capabilities
        if not capabilities.blur or self._blur is None:
            return SurfaceResult.not_supported(capabilities.blur_reason or "Blur is unavailable.")
        pointer = self._host.native_window_pointer()
        if pointer is None:
            return SurfaceResult.failed("The window handle is unavailable.", retryable=True)
        try:
            if region is None:
                self._blur.clear_blur(pointer)
            else:
                self._blur.set_blur_region(pointer, region.x, region.y, region.width, region.height, radius)
        except (OSError, RuntimeError):
            return SurfaceResult.failed("Blur update failed.", retryable=True)
        return SurfaceResult.applied()

    def move_to(self, position: WindowPoint) -> SurfaceResult:
        if self._closed:
            return SurfaceResult.rejected("The ordinary-window adapter is closed.")
        capabilities = self.capabilities
        if not capabilities.client_positioning:
            return SurfaceResult.not_supported(
                capabilities.client_positioning_reason or "This window cannot be positioned by the client."
            )
        try:
            self._host.move_window(position)
        except RuntimeError as exc:
            return SurfaceResult.failed(f"Window move failed: {exc}", retryable=True)
        return SurfaceResult.applied()

    def release_surface(self) -> SurfaceResult:
        """Hide and release the ordinary window before shutdown."""
        if self._surface_released or not self._host.is_alive():
            self._surface_released = True
            return SurfaceResult.applied()
        try:
            self._host.clear_input_mask()
            self._host.hide_window()
            self._host.destroy_surface()
        except RuntimeError as exc:
            self._surface_released = False
            return SurfaceResult.failed(f"Window surface release failed: {exc}", retryable=True)
        self._surface_released = True
        return SurfaceResult.applied()

    def close(self) -> SurfaceResult:
        """Release the ordinary window and reject operations after shutdown."""
        if self._closed:
            return SurfaceResult.applied()
        result = self.release_surface()
        self._drag_strategy.end_drag()
        if result.succeeded:
            self._closed = True
        return result

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
        geometry: DragGeometry,
    ) -> DragStartResult:
        if self._closed:
            return DragStartResult(DragMode.UNAVAILABLE, "The ordinary-window adapter is closed.")
        return self._drag_strategy.begin_drag(local_position, global_position, geometry)

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
        geometry: DragGeometry,
    ) -> DragUpdateResult:
        if self._closed:
            return DragUpdateResult(
                SurfaceResult.rejected("The ordinary-window adapter is closed."),
                geometry.surface_position,
            )
        return self._drag_strategy.update_drag(local_position, global_position, geometry)

    def end_drag(self) -> None:
        self._drag_strategy.end_drag()

    def set_position(self, position: WindowPoint) -> None:
        """Synchronize the drag strategy after a committed window move."""
        self._drag_strategy.set_position(position)
