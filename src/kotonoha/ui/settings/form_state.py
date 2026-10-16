"""Typed staged state and page reset rules for the settings dialog."""

from __future__ import annotations

from dataclasses import replace

from ...config import Config
from ...config.schema import SETTINGS_CONFIG_FIELDS


class SettingsFormState:
    """Own the editable configuration staged by one settings dialog."""

    def __init__(self, config: Config) -> None:
        self._config = config.clamped()
        self._applied_config = self._config

    @property
    def config(self) -> Config:
        """Return the current staged configuration."""
        return self._config

    def replace(self, config: Config) -> Config:
        """Replace staged values after applying the configuration contract."""
        self._config = config.clamped()
        return self._config

    def changed_fields(self) -> frozenset[str]:
        """Return Settings fields changed since the last successful Apply."""
        before = self._applied_config.settings_values()
        after = self._config.settings_values()
        return frozenset(
            name
            for name, old_value, new_value in zip(
                SETTINGS_CONFIG_FIELDS,
                before,
                after,
                strict=True,
            )
            if old_value != new_value
        )

    def mark_applied(self) -> None:
        """Make the current staged values the baseline for the next Apply."""
        self._applied_config = self._config

    def reset_page(self, index: int, defaults: Config | None = None) -> Config:
        """Reset one page while preserving staged values from every other page."""
        baseline = Config() if defaults is None else defaults.clamped()
        self._config = _reset_page_values(self._config, baseline, index)
        return self._config


def _reset_page_values(current: Config, defaults: Config, index: int) -> Config:
    """Reset explicit fields for one settings page without reflective access."""
    if index == 0:
        return replace(
            current,
            ui_language=defaults.ui_language,
            theme=defaults.theme,
            frost_window=defaults.frost_window,
            settings_opacity=defaults.settings_opacity,
        ).clamped()
    if index == 1:
        return replace(current, icon_name=defaults.icon_name, window_icon_name=defaults.window_icon_name).clamped()
    if index == 2:
        return replace(
            current,
            font_family=defaults.font_family,
            font_style=defaults.font_style,
            font_size=defaults.font_size,
            context_font_size=defaults.context_font_size,
            translation_font_size=defaults.translation_font_size,
        ).clamped()
    if index == 3:
        return replace(
            current,
            panel_style=defaults.panel_style,
            panel_width_mode=defaults.panel_width_mode,
            panel_width=defaults.panel_width,
            panel_overflow_mode=defaults.panel_overflow_mode,
            opacity=defaults.opacity,
            frost_opacity=defaults.frost_opacity,
            panel_accent_tint=defaults.panel_accent_tint,
        ).clamped()
    if index == 4:
        return replace(
            current,
            accent_start=defaults.accent_start,
            accent_end=defaults.accent_end,
            accent_sweep=defaults.accent_sweep,
            fx_animate=defaults.fx_animate,
            fx_transition=defaults.fx_transition,
            fx_glow=defaults.fx_glow,
            fx_word_pop=defaults.fx_word_pop,
            fx_intensity=defaults.fx_intensity,
        ).clamped()
    if index == 5:
        return replace(
            current,
            karaoke=defaults.karaoke,
            lead_ms=defaults.lead_ms,
            show_translation=defaults.show_translation,
            current_line_only=defaults.current_line_only,
            lyrics_script=defaults.lyrics_script,
            interlude_style=defaults.interlude_style,
            interlude_countdown=defaults.interlude_countdown,
        ).clamped()
    if index == 6:
        return replace(
            current,
            anchor_top=defaults.anchor_top,
            margin_edge=defaults.margin_edge,
            margin_x=defaults.margin_x,
            passthrough=defaults.passthrough,
        ).clamped()
    if index == 7:
        return replace(
            current,
            lyrics_sources=defaults.lyrics_sources,
            display_sources=defaults.display_sources,
            player_lock=defaults.player_lock,
            prefer_best_lyrics=defaults.prefer_best_lyrics,
            fuzzy_match=defaults.fuzzy_match,
            cache_enabled=defaults.cache_enabled,
            cider_api_token=defaults.cider_api_token,
        ).clamped()
    raise ValueError(f"unknown settings page index: {index}")


__all__ = ["SettingsFormState"]
