"""Shared Settings field schema used by config and the Qt form."""

from __future__ import annotations

# Page grouping is a presentation-neutral contract: it defines which Settings
# fields are reset together, while the UI still owns how each page is rendered.
SETTINGS_PAGE_FIELDS: tuple[tuple[str, ...], ...] = (
    ("ui_language", "theme", "frost_window", "settings_opacity"),
    ("icon_name", "window_icon_name"),
    ("font_family", "font_style", "font_size", "context_font_size", "translation_font_size"),
    (
        "panel_style", "panel_width_mode", "panel_width", "panel_overflow_mode",
        "opacity", "frost_opacity", "panel_accent_tint",
    ),
    (
        "accent_start",
        "accent_end",
        "accent_sweep",
        "fx_animate",
        "fx_transition",
        "fx_glow",
        "fx_word_pop",
        "fx_intensity",
    ),
    (
        "karaoke",
        "lead_ms",
        "show_translation",
        "current_line_only",
        "lyrics_script",
        "interlude_style",
        "interlude_countdown",
    ),
    ("anchor_top", "margin_edge", "margin_x", "passthrough"),
    (
        "lyrics_sources",
        "display_sources",
        "player_lock",
        "prefer_best_lyrics",
        "fuzzy_match",
        "cache_enabled",
        "cider_api_token",
    ),
)

SETTINGS_CONFIG_FIELDS: tuple[str, ...] = tuple(
    field_name for page in SETTINGS_PAGE_FIELDS for field_name in page
)

__all__ = ["SETTINGS_CONFIG_FIELDS", "SETTINGS_PAGE_FIELDS"]
