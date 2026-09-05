"""Bind overlay appearance settings to Qt lyric widgets and panel painting."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QWidget

from ...config import Config
from ...display.layout import FontFitPolicy
from .karaoke_label import KaraokeLabel
from .style import OverlayAppearance

PILL_RADIUS = 16
_FONT_FIT_POLICY = FontFitPolicy()


class OverlayPresentationController:
    """Own config-to-widget bindings and panel rendering policy."""

    def __init__(
        self,
        config: Config,
        container: QWidget,
        previous: QLabel,
        current: KaraokeLabel,
        feedback: QLabel,
        translation: KaraokeLabel,
        next_label: QLabel,
        *,
        window_size: Callable[[], tuple[int, int]],
    ) -> None:
        """Create a presentation owner around the already-built lyric widgets."""
        self._config = config
        self._container = container
        self._previous = previous
        self._current = current
        self._feedback = feedback
        self._translation = translation
        self._next = next_label
        self._window_size = window_size
        self._appearance = OverlayAppearance()

    def apply_config(self, config: Config) -> None:
        """Apply appearance, typography, sizing, and visibility settings."""
        self._config = config
        available_width = self._configure_panel_width()
        families = self.font_families()
        base, shadow, context_css = self.text_colors()

        current_font = QFont()
        current_font.setFamilies(families)
        current_font.setPixelSize(config.font_size)
        if config.font_style:
            current_font.setStyleName(config.font_style)
        self._current.set_style(
            current_font, config.accent_start, config.accent_end, config.accent_sweep, base, shadow
        )
        self._current.set_effects(
            glow=config.fx_glow,
            word_pop=config.fx_word_pop,
            intensity=config.fx_intensity,
            animate=config.fx_animate,
            transition=config.fx_transition,
        )
        self._current.set_max_width(available_width)

        family_stack = ", ".join(f"'{name}'" for name in families)
        for label in (self._previous, self._feedback, self._next):
            label.setStyleSheet(
                f"color: {context_css}; font-size: {config.context_font_size}px; "
                f"font-family: {family_stack};"
            )
            label.setMaximumWidth(available_width)
            effect = label.graphicsEffect()
            if isinstance(effect, QGraphicsDropShadowEffect):
                effect.setColor(shadow)

        translation_font = QFont()
        translation_font.setFamilies(families)
        translation_font.setPixelSize(config.translation_font_size)
        translation_font.setItalic(True)
        self._translation.set_style(
            translation_font, config.accent_start, config.accent_end, config.accent_sweep, base, shadow
        )
        self._translation.set_effects(
            glow=False,
            word_pop=False,
            intensity=config.fx_intensity,
            animate=config.fx_animate,
            transition=config.fx_transition,
        )
        self._translation.set_max_width(available_width)
        self._translation.setVisible(config.show_translation)
        self._update_context_visibility()

    def font_families(self) -> list[str]:
        """Return the configured family and the appearance fallback chain."""
        return self._appearance.font_families(self._config)

    def band_height(self) -> int:
        """Return the stable surface height required by the configured text."""
        main = self._config.font_size
        context = 0 if self._config.current_line_only else self._config.context_font_size
        translation = self._config.translation_font_size if self._config.show_translation else 0
        feedback = 20
        lines = int(main * 1.6) + 2 * int(context * 1.4) + int(translation * 1.6) + feedback
        chrome = 22 + 24 + 34
        return max(140, lines + chrome)

    def text_colors(self) -> tuple[QColor, QColor, str]:
        """Return lyric, shadow, and context colors for the current appearance."""
        return self._appearance.text_colors(self._config)

    def panel_base_color(self) -> QColor:
        """Return the configured panel fill color."""
        return self._appearance.panel_base_color(self._config)

    def should_paint_panel(self) -> bool:
        """Return whether the configured panel style includes a fill."""
        return self._appearance.should_paint_panel(self._config)

    def panel_alpha(self) -> int:
        """Return the panel fill alpha selected by the appearance policy."""
        return self._appearance.panel_alpha(self._config)

    def paint_panel(self, painter: QPainter, geometry: QRect) -> None:
        """Paint the configured panel into an already-owned Qt painter."""
        if not self.should_paint_panel():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.panel_base_color()
        color.setAlpha(self.panel_alpha())
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(geometry, PILL_RADIUS, PILL_RADIUS)

    def _configure_panel_width(self) -> int:
        """Set the pill width and return the lyric width available inside it."""
        window_width = self._window_size()[0]
        if self._config.panel_width_mode == "fixed":
            pill_width = max(240, min(self._config.panel_width, window_width - 8))
            self._container.setFixedWidth(pill_width)
            return max(120, pill_width - 44)
        self._container.setMinimumWidth(0)
        self._container.setMaximumWidth(16_777_215)
        return _FONT_FIT_POLICY.content_width(window_width)

    def _update_context_visibility(self) -> None:
        """Show or hide surrounding lyric context according to the current mode."""
        visible = not self._config.current_line_only
        self._previous.setVisible(visible)
        self._next.setVisible(visible)


__all__ = ["OverlayPresentationController"]
