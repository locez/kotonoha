"""Qt binding for overlay geometry and the platform surface lifecycle."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QApplication, QWidget

from ...config import Config
from ...platform.overlay_contracts import (
    DragMode,
    Output,
    OverlayPlatform,
    OverlayPlatformFactory,
    SurfaceResult,
    SurfaceResultStatus,
    SurfaceState,
    WindowPoint,
    WindowRectangle,
)
from ...platform.qt_host import QtWindowHost
from ...platform.surface_lifecycle import SurfaceLifecycleOwner
from .drag import DragRelease
from .geometry import OverlayGeometry, ScreenLike
from .position import OverlayPositionController, PositionCommit

logger = logging.getLogger(__name__)


class OverlaySurfaceController:
    """Own Qt geometry binding while delegating resource lifecycle to one owner."""

    def __init__(
        self,
        widget: QWidget,
        config: Config,
        *,
        platform_factory: OverlayPlatformFactory,
        band_height: Callable[[], int],
        container_geometry: Callable[[], QRect],
    ) -> None:
        """Create the Qt binding and its explicit platform lifecycle owner."""
        self._widget = widget
        self._config = config
        self._container_geometry = container_geometry
        self._geometry = OverlayGeometry(config, band_height)
        self._passthrough = config.passthrough
        self._host = QtWindowHost(widget)
        self._platform: OverlayPlatform = platform_factory(self._host)
        self._rebuild_complete_handler: Callable[[], None] | None = None
        self._lifecycle = SurfaceLifecycleOwner(
            self._platform.surface,
            output_binding=self._platform.output_binding,
            timer_parent=widget,
            rebuild_surface=self._rebuild_surface,
            on_rebind_applied=self._complete_rebind,
        )
        self._position = OverlayPositionController(config, self._geometry, self._platform, self._lifecycle)

    @property
    def host(self) -> QtWindowHost:
        """Return the Qt host adapter owned by this surface."""
        return self._host

    @property
    def platform(self) -> OverlayPlatform:
        """Return the composed capability ports for this surface."""
        return self._platform

    @property
    def layer_pos(self) -> QPoint:
        """Return the screen-local top-left position of the surface."""
        return self._position.layer_pos

    @layer_pos.setter
    def layer_pos(self, value: QPoint) -> None:
        self._position.layer_pos = value

    @property
    def active_screen(self) -> ScreenLike | None:
        """Return the output whose activation or rebuild was committed."""
        return self._position.active_screen

    @active_screen.setter
    def active_screen(self, value: ScreenLike | None) -> None:
        # Test harnesses inject an active output directly; production selection
        # commits it only through select_screen() after a SurfaceResult.
        self._position.active_screen = value

    @property
    def dragging(self) -> bool:
        """Whether a manual drag gesture is active."""
        return self._position.dragging

    @dragging.setter
    def dragging(self, value: bool) -> None:
        self._position.dragging = value

    @property
    def drag_moved(self) -> bool:
        """Whether the active gesture changed the requested position."""
        return self._position.drag_moved

    @drag_moved.setter
    def drag_moved(self, value: bool) -> None:
        self._position.drag_moved = value

    @property
    def drag_applied(self) -> bool:
        """Whether every requested movement was accepted by the platform."""
        return self._position.drag_applied

    @drag_applied.setter
    def drag_applied(self, value: bool) -> None:
        self._position.drag_applied = value

    @property
    def drag_local(self) -> QPoint:
        """Return the last pointer position in widget coordinates."""
        return self._position.drag_local

    @drag_local.setter
    def drag_local(self, value: QPoint) -> None:
        self._position.drag_local = value

    @property
    def state(self) -> SurfaceState:
        """Return the platform lifecycle state."""
        return self._lifecycle.state

    @property
    def active_output(self) -> Output | None:
        """Return the last output with a successfully rebuilt surface."""
        return self._lifecycle.active_output

    @property
    def pending_output(self) -> Output | None:
        """Return the output retained for a later rebuild attempt."""
        return self._lifecycle.pending_output

    def update_config(self, config: Config) -> None:
        """Use the current placement and platform settings for later operations."""
        self._config = config
        self._geometry.update_config(config)
        self._position.update_config(config)

    def prepare(self) -> SurfaceResult:
        """Prepare the platform surface and report the real operation result."""
        result = self._lifecycle.prepare()
        if not result.succeeded:
            logger.warning("Overlay surface preparation failed: %s", result.reason or "unknown reason")
        self._log_capabilities()
        return result

    def close(self) -> SurfaceResult:
        """Stop deferred rebuilds and release the native surface resources."""
        return self._lifecycle.close()

    def set_rebuild_complete_handler(self, handler: Callable[[], None]) -> None:
        """Register the presentation callback after a surface is rebuilt."""
        self._rebuild_complete_handler = handler

    def set_position_commit_handler(self, handler: Callable[[PositionCommit], None]) -> None:
        """Register the application callback for an asynchronously completed drag."""
        self._position.set_position_commit_handler(handler)

    def _log_capabilities(self) -> None:
        capabilities = self._platform.capabilities
        unavailable = (
            ("layer shell", capabilities.layer_shell, capabilities.layer_shell_reason),
            ("blur", capabilities.blur, capabilities.blur_reason),
            ("input regions", capabilities.input_region, capabilities.input_region_reason),
            ("output rebinding", capabilities.output_rebinding, capabilities.output_rebinding_reason),
        )
        for name, available, reason in unavailable:
            if not available:
                logger.warning("Overlay %s unavailable: %s", name, reason or "no reason provided")

    def configured_screen(self, screens: Sequence[ScreenLike]) -> ScreenLike | None:
        """Find the configured output among the currently reported screens."""
        return self._geometry.configured_screen(screens)

    def select_screen(self, screen: ScreenLike | None) -> None:
        """Select an output for geometry without claiming its platform binding."""
        self._position.select_screen(screen)

    def set_active_screen(self, screen: ScreenLike | None) -> None:
        """Compatibility spelling for selecting a screen during view setup."""
        self.select_screen(screen)

    def target_screen(
        self,
        screens: Sequence[ScreenLike],
        *,
        configured: ScreenLike | None,
        widget_screen: ScreenLike | None,
        primary: ScreenLike | None,
    ) -> ScreenLike | None:
        """Choose a usable output without mutating the committed active output."""
        active_screen = self._position.active_screen
        if active_screen is None:
            active_screen = self._position.selected_screen
        screen = self._geometry.target_screen(
            screens,
            active=active_screen,
            configured=configured,
            widget_screen=widget_screen,
            primary=primary,
        )
        self._position.select_screen(screen)
        return screen

    @staticmethod
    def usable_screen(screen: ScreenLike | None) -> ScreenLike | None:
        """Return a screen with non-empty geometry, tolerating deleted Qt objects."""
        return OverlayGeometry.usable_screen(screen)

    @staticmethod
    def output(screen: ScreenLike | None) -> Output | None:
        """Convert a toolkit screen into the platform output contract."""
        return OverlayGeometry.output(screen)

    def connected_outputs(self, screens: Sequence[ScreenLike]) -> tuple[Output, ...]:
        """Return all usable outputs currently reported by Qt."""
        return self._geometry.connected_outputs(screens)

    def screen_removed(self, screen: ScreenLike, screens: Sequence[ScreenLike]) -> None:
        """Forward a typed output removal to the lifecycle owner."""
        removed = self.output(screen)
        if removed is None:
            return
        connected = self.connected_outputs(screens)
        replacement = self._select_output(connected, self._config.screen_name or None)
        self._lifecycle.output_removed(removed, replacement)

    def screen_added(self, screens: Sequence[ScreenLike]) -> None:
        """Forward the best connected output to a pending lifecycle intent."""
        connected = self.connected_outputs(screens)
        if not connected:
            return
        candidate = self._select_output(connected, self._config.screen_name or None)
        if candidate is not None:
            self._lifecycle.output_added(candidate)

    @staticmethod
    def _select_output(outputs: tuple[Output, ...], configured_name: str | None) -> Output | None:
        """Prefer the configured output, then the first connected output."""
        if configured_name:
            configured = next((output for output in outputs if output.name == configured_name), None)
            if configured is not None:
                return configured
        return outputs[0] if outputs else None

    def window_size(self, screen: ScreenLike | None) -> tuple[int, int]:
        """Return the stable surface dimensions for the current output and config."""
        return self._geometry.window_size(screen)

    def compute_layer_pos(self, width: int, height: int, screen: ScreenLike | None) -> QPoint:
        """Compute and clamp the configured screen-local position."""
        return self._geometry.compute_layer_pos(width, height, screen)

    def apply_window_geometry(self, screens: Sequence[ScreenLike], *, reset_position: bool = True) -> None:
        """Size the widget and position it through the selected placement port."""
        screen = self.target_screen(
            screens,
            configured=self.configured_screen(screens),
            widget_screen=self._widget.screen(),
            primary=QApplication.primaryScreen(),
        )
        if screen is None:
            return
        self._apply_widget_geometry(screen, reset_position=reset_position)
        if self._platform.capabilities.layer_shell:
            return
        placement = self._platform.placement
        if placement is None:
            return
        geometry = screen.geometry()
        result = placement.move_to(
            WindowPoint(geometry.x() + self._position.layer_pos.x(), geometry.y() + self._position.layer_pos.y())
        )
        self._log_result("ordinary-window placement", result)

    def _apply_widget_geometry(self, screen: ScreenLike, *, reset_position: bool) -> None:
        """Apply Qt size/screen binding while keeping placement policy outside Qt widgets."""
        width, height = self.window_size(screen)
        self._widget.setFixedSize(width, height)
        self.bind_widget_screen(screen)
        if reset_position:
            self._position.layer_pos = self.compute_layer_pos(width, height, screen)

    def bind_widget_screen(self, screen: ScreenLike | None) -> None:
        """Bind both Qt window objects to the selected screen when possible."""
        if screen is None:
            return
        if isinstance(screen, QScreen):
            self._widget.setScreen(screen)
        handle = self._widget.windowHandle()
        if handle is not None and isinstance(screen, QScreen):
            handle.setScreen(screen)

    def activate(self, screens: Sequence[ScreenLike], *, fallback: Callable[[], None] | None = None) -> bool:
        """Activate the selected surface or use the ordinary-window fallback."""
        screen = self.target_screen(
            screens,
            configured=self.configured_screen(screens),
            widget_screen=self._widget.screen(),
            primary=QApplication.primaryScreen(),
        )
        self.bind_widget_screen(screen)
        result = self._lifecycle.activate(self.output(screen))
        capabilities = self._platform.capabilities
        if capabilities.layer_shell and result.succeeded:
            self._position.active_screen = screen
            placement = self._platform.placement
            if placement is not None:
                placed = placement.move_to(
                    WindowPoint(self._position.layer_pos.x(), self._position.layer_pos.y())
                )
                self._log_result("Layer Shell placement", placed)
            self.apply_input_region()
            self.apply_blur()
            return True
        if capabilities.layer_shell:
            logger.warning("Layer Shell activation failed: %s", result.reason or "no reason given")
        if fallback is None:
            self.fallback_position(screen)
        else:
            fallback()
        self.apply_input_region()
        return False

    def fallback_position(self, screen: ScreenLike | None) -> SurfaceResult:
        """Position an ordinary window through its host when Layer Shell fails."""
        if screen is None:
            return SurfaceResult.rejected("No usable output is available.")
        geometry = screen.geometry()
        position = WindowPoint(
            geometry.x() + self._position.layer_pos.x(), geometry.y() + self._position.layer_pos.y()
        )
        try:
            self._host.move_window(position)
        except RuntimeError as exc:
            result = SurfaceResult.failed(f"Ordinary-window positioning failed: {exc}", retryable=True)
            self._log_result("ordinary-window fallback placement", result)
            return result
        return SurfaceResult.applied()

    def set_input_mode(self, passthrough: bool) -> SurfaceResult:
        """Set the input mode and immediately report the port result."""
        self._passthrough = passthrough
        return self.apply_input_region()

    def apply_input_region(self) -> SurfaceResult:
        """Apply the visible pill region or full click-through to the input port."""
        input_region = self._platform.input_region
        if input_region is None:
            result = SurfaceResult.not_supported(
                self._platform.capabilities.input_region_reason or "Input regions are unavailable."
            )
            self._log_result("input region", result, debug=True)
            return result
        if self._passthrough:
            result = input_region.set_input_region(None)
        else:
            rect = self._container_geometry()
            result = input_region.set_input_region(WindowRectangle(rect.x(), rect.y(), rect.width(), rect.height()))
        self._log_result("input region", result)
        return result

    def apply_blur(self) -> SurfaceResult:
        """Apply frosted-panel blur when the selected platform supports it."""
        blur = self._platform.blur
        if blur is None:
            result = SurfaceResult.not_supported(self._platform.capabilities.blur_reason or "Blur is unavailable.")
            self._log_result("blur", result, debug=True)
            return result
        if self._config.panel_style == "frost":
            rect = self._container_geometry()
            result = blur.set_blur_region(WindowRectangle(rect.x(), rect.y(), rect.width(), rect.height()), 16)
        else:
            result = blur.set_blur_region(None)
        self._log_result("blur", result)
        return result

    def begin_drag(self, local: QPoint, global_position: QPoint) -> DragMode:
        """Start a manual or compositor-owned drag through the selected port."""
        return self._position.begin_drag(
            local,
            global_position,
            self._container_geometry(),
        )

    def update_drag(self, local: QPoint, global_position: QPoint) -> SurfaceResult:
        """Apply one visible-panel drag step and retain the platform result."""
        return self._position.update_drag(
            local,
            global_position,
            self._container_geometry(),
        )

    def end_drag(self) -> DragRelease:
        """End the gesture and state whether persistence is safe."""
        return self._position.end_drag()

    def clamp_to_screen(
        self,
        pos: QPoint,
        *,
        screen: ScreenLike | None,
        width: int,
        height: int,
        allow_partial: bool,
    ) -> QPoint:
        """Clamp a position for startup or release-time visibility."""
        return self._position.clamp_to_screen(
            pos,
            screen=screen,
            width=width,
            height=height,
            allow_partial=allow_partial,
        )

    def commit_drag_position(
        self,
        cursor_local: QPoint | None,
        *,
        surface_screen: ScreenLike | None,
        screens: Sequence[ScreenLike],
        window_size: tuple[int, int],
    ) -> PositionCommit | None:
        """Commit output-local placement only after its platform operation succeeds."""
        return self._position.commit_drag_position(
            cursor_local,
            surface_screen=surface_screen,
            screens=screens,
            window_size=window_size,
        )

    def _rebuild_surface(self, output: Output) -> SurfaceResult:
        """Recreate a surface on one current Qt output for the lifecycle owner."""
        if not self._host.is_alive():
            return SurfaceResult.failed("The overlay window is gone.", retryable=False)
        screens = QApplication.screens()
        screen = next((candidate for candidate in screens if candidate.name() == output.name), None)
        if screen is None or self.usable_screen(screen) is None:
            return SurfaceResult.rejected("The requested output is not connected.")
        position = self._position.begin_rebuild(screen)
        try:
            self._widget.setFixedSize(*self.window_size(screen))
            self.bind_widget_screen(screen)
            result = self._platform.surface.activate()
        except RuntimeError as exc:
            return self._release_failed_rebuild(SurfaceResult.failed(f"Surface rebuild failed: {exc}", retryable=True))
        if not result.succeeded:
            return self._release_failed_rebuild(result)
        if self._platform.capabilities.layer_shell:
            placement = self._platform.placement
            if placement is None:
                return self._release_failed_rebuild(
                    SurfaceResult.not_supported("Layer Shell placement is unavailable.")
                )
            placed = placement.move_to(WindowPoint(position.x(), position.y()))
            if not placed.succeeded:
                return self._release_failed_rebuild(placed)
        input_result = self.apply_input_region()
        if not input_result.succeeded and input_result.status is not SurfaceResultStatus.NOT_SUPPORTED:
            return self._release_failed_rebuild(input_result)
        blur_result = self.apply_blur()
        if not blur_result.succeeded and blur_result.status is not SurfaceResultStatus.NOT_SUPPORTED:
            return self._release_failed_rebuild(blur_result)
        return SurfaceResult.applied()

    def _release_failed_rebuild(self, result: SurfaceResult) -> SurfaceResult:
        """Leave a failed rebuild released before the owner schedules another try."""
        self._position.rebuild_failed()
        released = self._platform.surface.release_surface()
        if released.succeeded:
            return result
        reasons = [reason for reason in (result.reason, released.reason) if reason]
        return SurfaceResult.failed("; ".join(reasons), retryable=True)

    def _complete_rebind(self, output: Output) -> None:
        """Commit logical output and pending placement after a rebuilt surface is active."""
        self._position.complete_rebind(output)
        if self._rebuild_complete_handler is not None:
            self._rebuild_complete_handler()

    @staticmethod
    def _log_result(name: str, result: SurfaceResult, *, debug: bool = False) -> None:
        """Make ignored platform failures observable without changing UI policy."""
        if result.succeeded:
            return
        message = "%s was not applied: %s"
        if debug:
            logger.debug(message, name, result.reason or "unknown reason")
        else:
            logger.warning(message, name, result.reason or "unknown reason")

    def consume_preserve_position(self) -> bool:
        """Return and clear the one-shot position-preservation flag for showEvent."""
        return self._position.consume_preserve_position()


__all__ = ["OverlaySurfaceController", "PositionCommit", "ScreenLike"]
