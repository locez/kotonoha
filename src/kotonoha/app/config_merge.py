"""Pure Settings-to-configuration merge transformation."""

from __future__ import annotations

from dataclasses import replace

from ..config import Config
from ..config.schema import SETTINGS_CONFIG_FIELDS


def merge_settings(
    current: Config,
    candidate: Config,
    changed_fields: frozenset[str],
) -> Config:
    """Return ``current`` with only the submitted Settings fields replaced.

    Detected output geometry is deliberately excluded from the Settings merge.
    This module is stateless on purpose: it owns a field mapping, not
    configuration lifecycle or persistence.

    Raises:
        ValueError: if ``changed_fields`` contains a non-Settings field.
    """
    unknown = changed_fields - frozenset(SETTINGS_CONFIG_FIELDS)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"unknown Settings fields: {names}")
    if not changed_fields:
        return current.clamped()

    submitted = candidate.clamped()
    return replace(
        current,
        ui_language=submitted.ui_language if "ui_language" in changed_fields else current.ui_language,
        theme=submitted.theme if "theme" in changed_fields else current.theme,
        frost_window=submitted.frost_window if "frost_window" in changed_fields else current.frost_window,
        settings_opacity=(
            submitted.settings_opacity
            if "settings_opacity" in changed_fields
            else current.settings_opacity
        ),
        icon_name=submitted.icon_name if "icon_name" in changed_fields else current.icon_name,
        window_icon_name=(
            submitted.window_icon_name
            if "window_icon_name" in changed_fields
            else current.window_icon_name
        ),
        font_family=submitted.font_family if "font_family" in changed_fields else current.font_family,
        font_style=submitted.font_style if "font_style" in changed_fields else current.font_style,
        font_size=submitted.font_size if "font_size" in changed_fields else current.font_size,
        context_font_size=(
            submitted.context_font_size
            if "context_font_size" in changed_fields
            else current.context_font_size
        ),
        translation_font_size=(
            submitted.translation_font_size
            if "translation_font_size" in changed_fields
            else current.translation_font_size
        ),
        panel_style=submitted.panel_style if "panel_style" in changed_fields else current.panel_style,
        panel_width_mode=(
            submitted.panel_width_mode
            if "panel_width_mode" in changed_fields
            else current.panel_width_mode
        ),
        panel_width=submitted.panel_width if "panel_width" in changed_fields else current.panel_width,
        panel_overflow_mode=(
            submitted.panel_overflow_mode
            if "panel_overflow_mode" in changed_fields
            else current.panel_overflow_mode
        ),
        opacity=submitted.opacity if "opacity" in changed_fields else current.opacity,
        frost_opacity=submitted.frost_opacity if "frost_opacity" in changed_fields else current.frost_opacity,
        panel_accent_tint=(
            submitted.panel_accent_tint
            if "panel_accent_tint" in changed_fields
            else current.panel_accent_tint
        ),
        accent_start=submitted.accent_start if "accent_start" in changed_fields else current.accent_start,
        accent_end=submitted.accent_end if "accent_end" in changed_fields else current.accent_end,
        accent_sweep=submitted.accent_sweep if "accent_sweep" in changed_fields else current.accent_sweep,
        fx_animate=submitted.fx_animate if "fx_animate" in changed_fields else current.fx_animate,
        fx_transition=(
            submitted.fx_transition
            if "fx_transition" in changed_fields
            else current.fx_transition
        ),
        fx_glow=submitted.fx_glow if "fx_glow" in changed_fields else current.fx_glow,
        fx_word_pop=submitted.fx_word_pop if "fx_word_pop" in changed_fields else current.fx_word_pop,
        fx_intensity=(
            submitted.fx_intensity
            if "fx_intensity" in changed_fields
            else current.fx_intensity
        ),
        karaoke=submitted.karaoke if "karaoke" in changed_fields else current.karaoke,
        lead_ms=submitted.lead_ms if "lead_ms" in changed_fields else current.lead_ms,
        show_translation=(
            submitted.show_translation
            if "show_translation" in changed_fields
            else current.show_translation
        ),
        context_lines=submitted.context_lines if "context_lines" in changed_fields else current.context_lines,
        context_blur=submitted.context_blur if "context_blur" in changed_fields else current.context_blur,
        lyrics_script=(
            submitted.lyrics_script
            if "lyrics_script" in changed_fields
            else current.lyrics_script
        ),
        interlude_style=(
            submitted.interlude_style
            if "interlude_style" in changed_fields
            else current.interlude_style
        ),
        interlude_countdown=(
            submitted.interlude_countdown
            if "interlude_countdown" in changed_fields
            else current.interlude_countdown
        ),
        anchor_top=submitted.anchor_top if "anchor_top" in changed_fields else current.anchor_top,
        margin_edge=submitted.margin_edge if "margin_edge" in changed_fields else current.margin_edge,
        margin_x=submitted.margin_x if "margin_x" in changed_fields else current.margin_x,
        passthrough=submitted.passthrough if "passthrough" in changed_fields else current.passthrough,
        lyrics_sources=(
            submitted.lyrics_sources
            if "lyrics_sources" in changed_fields
            else current.lyrics_sources
        ),
        display_sources=(
            submitted.display_sources
            if "display_sources" in changed_fields
            else current.display_sources
        ),
        player_lock=submitted.player_lock if "player_lock" in changed_fields else current.player_lock,
        prefer_best_lyrics=(
            submitted.prefer_best_lyrics
            if "prefer_best_lyrics" in changed_fields
            else current.prefer_best_lyrics
        ),
        fuzzy_match=submitted.fuzzy_match if "fuzzy_match" in changed_fields else current.fuzzy_match,
        cache_enabled=submitted.cache_enabled if "cache_enabled" in changed_fields else current.cache_enabled,
        cider_api_token=(
            submitted.cider_api_token
            if "cider_api_token" in changed_fields
            else current.cider_api_token
        ),
    ).clamped()


__all__ = ["merge_settings"]
