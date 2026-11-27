"""Toolkit-facing screen and placement calculations for the overlay surface."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from PyQt6.QtCore import QPoint, QRect

from ...config import Config, LyricsDisplayMode
from ...display.layout import FontFitPolicy
from ...platform.overlay_contracts import Output, WindowRectangle


class ScreenLike(Protocol):
    """The screen facts needed by surface placement and output selection."""

    def name(self) -> str: ...

    def geometry(self) -> QRect: ...


class OverlayGeometry:
    """Own output selection and screen-local placement calculations."""

    def __init__(self, config: Config, band_height: Callable[[], int]) -> None:
        """Create geometry policy around a live config and height provider."""
        self._config = config
        self._band_height = band_height
        self._fit_policy = FontFitPolicy()
        self._committed_output: tuple[str, int, int] | None = self._output_from_config(config)
        self._committed_position: tuple[str, int, int, int, int] | None = None

    def update_config(self, config: Config) -> None:
        """Use a newly applied config for subsequent calculations."""
        self._config = config
        self._committed_output = self._output_from_config(config)
        self._committed_position = None

    def record_position_commit(
        self,
        screen_name: str,
        width: int,
        height: int,
        margin_edge: int,
        margin_x: int,
    ) -> None:
        """Remember the geometry used by the latest platform-accepted placement."""
        self._committed_output = (screen_name, width, height)
        self._committed_position = (screen_name, width, height, margin_edge, margin_x)

    def configured_screen(self, screens: Sequence[ScreenLike]) -> ScreenLike | None:
        """Find the configured output among the currently reported screens."""
        if not self._config.screen_name:
            return None
        return next((screen for screen in screens if screen.name() == self._config.screen_name), None)

    def target_screen(
        self,
        screens: Sequence[ScreenLike],
        *,
        active: ScreenLike | None,
        configured: ScreenLike | None,
        widget_screen: ScreenLike | None,
        primary: ScreenLike | None,
    ) -> ScreenLike | None:
        """Choose a usable output using active, configured, widget, and primary order."""
        if active is not None and active in screens and self.usable_screen(active) is not None:
            return active
        return (
            self.usable_screen(configured)
            or self.usable_screen(widget_screen)
            or self.usable_screen(primary)
            or next((candidate for candidate in screens if self.usable_screen(candidate) is not None), None)
        )

    @staticmethod
    def usable_screen(screen: ScreenLike | None) -> ScreenLike | None:
        """Return a screen with non-empty geometry, tolerating deleted Qt objects."""
        if screen is None:
            return None
        try:
            return screen if not screen.geometry().isEmpty() else None
        except RuntimeError:
            return None

    @staticmethod
    def output(screen: ScreenLike | None) -> Output | None:
        """Convert a toolkit screen into the platform output contract."""
        if screen is None:
            return None
        try:
            geometry = screen.geometry()
        except RuntimeError:
            return None
        if geometry.isEmpty():
            return None
        return Output(screen.name(), WindowRectangle(geometry.x(), geometry.y(), geometry.width(), geometry.height()))

    def connected_outputs(self, screens: Sequence[ScreenLike]) -> tuple[Output, ...]:
        """Return all usable outputs currently reported by Qt."""
        return tuple(output for screen in screens if (output := self.output(screen)) is not None)

    @staticmethod
    def same_screen(first: ScreenLike | None, second: ScreenLike | None) -> bool:
        """Compare screen identity and geometry without relying on object identity."""
        if first is second:
            return True
        if first is None or second is None:
            return False
        return first.name() == second.name() and first.geometry() == second.geometry()

    @staticmethod
    def screen_for_global_point(
        point: QPoint,
        screens: Sequence[ScreenLike],
        fallback: ScreenLike | None,
    ) -> ScreenLike | None:
        """Find the output under a point, or the nearest output across a layout gap."""
        for screen in screens:
            if screen.geometry().contains(point):
                return screen
        if not screens:
            return fallback

        def distance_squared(screen: ScreenLike) -> int:
            geometry = screen.geometry()
            dx = max(geometry.left() - point.x(), 0, point.x() - geometry.right())
            dy = max(geometry.top() - point.y(), 0, point.y() - geometry.bottom())
            return dx * dx + dy * dy

        return min(screens, key=distance_squared)

    def window_size(self, screen: ScreenLike | None) -> tuple[int, int]:
        """Return the stable surface dimensions for the current output and config."""
        screen_width = screen.geometry().width() if screen is not None else 1280
        if self._config.panel_width_mode == "fixed":
            pill = max(240, min(self._config.panel_width, int(screen_width * 0.98)))
            width = min(int(screen_width * 0.98), pill + 48)
        else:
            width = self._fit_policy.window_width(screen_width, self._fit_font_size())
        return width, self._band_height()

    def _fit_font_size(self) -> int:
        """Return the largest configured font size among active lyric tracks."""
        size = self._config.font_size
        if self._config.lyrics_display_mode is LyricsDisplayMode.BOTH:
            size = max(size, self._config.translation_font_size)
        if self._config.context_lines > 0:
            size = max(size, self._config.context_font_size)
        return size

    def compute_layer_pos(
        self,
        width: int,
        height: int,
        screen: ScreenLike | None,
    ) -> QPoint:
        """Compute and clamp the configured screen-local position."""
        geometry = screen.geometry() if screen is not None else None
        screen_width = geometry.width() if geometry is not None else 1280
        screen_height = geometry.height() if geometry is not None else 720
        committed = self._committed_output
        same_output = (
            geometry is not None
            and screen is not None
            and committed is not None
            and screen.name() == committed[0]
            and (geometry.width(), geometry.height()) == committed[1:]
        )
        committed_position = self._committed_position if same_output else None
        margin_x = self._config.margin_x if committed_position is None else committed_position[4]
        margin_edge = self._config.margin_edge if committed_position is None else committed_position[3]
        x = (screen_width - width) // 2 + margin_x
        y = margin_edge if self._config.anchor_top else screen_height - height - margin_edge
        return self.clamp_to_screen(
            QPoint(x, y),
            screen=screen,
            width=width,
            height=height,
            allow_partial=same_output,
        )

    @staticmethod
    def _output_from_config(config: Config) -> tuple[str, int, int] | None:
        """Return a trusted persisted output geometry when one is available."""
        if not config.screen_name or config.screen_width <= 0 or config.screen_height <= 0:
            return None
        return config.screen_name, config.screen_width, config.screen_height

    @staticmethod
    def clamp_to_screen(
        pos: QPoint,
        *,
        screen: ScreenLike | None,
        width: int,
        height: int,
        allow_partial: bool,
    ) -> QPoint:
        """Clamp a position for startup or release-time visibility."""
        if screen is None:
            return pos
        geometry = screen.geometry()
        if allow_partial:
            min_x, max_x = -width + 80, geometry.width() - 80
            min_y, max_y = 0, geometry.height() - 60
        else:
            min_x, max_x = 0, max(0, geometry.width() - width)
            min_y, max_y = 0, max(0, geometry.height() - height)
        return QPoint(max(min_x, min(pos.x(), max_x)), max(min_y, min(pos.y(), max_y)))


__all__ = ["OverlayGeometry", "ScreenLike"]
