"""User configuration: load/save to XDG config dir.

Pure dataclass + (de)serialization so it can be unit-tested without touching the
real home directory. Unknown keys in the file are ignored; missing keys fall
back to defaults, so config files survive version upgrades.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

from .schema import SETTINGS_CONFIG_FIELDS

logger = logging.getLogger(__name__)

# Lyric source order breaks confidence/timing ties, or controls sequential lookup.
# "cider" = lyrics exposed by Cider's public API.
VALID_LYRICS_SOURCES = ("amll", "netease", "lrclib", "kugou", "qqmusic", "cider")
DEFAULT_LYRICS_SOURCES: list[str] = ["amll", "netease", "lrclib", "kugou"]

# Display sources provide playback facts and a candidate lyric document. They
# are ordered by preference independently from lyric lookup providers.
VALID_DISPLAY_SOURCES = ("mpris", "cider", "adapter")
DEFAULT_DISPLAY_SOURCES = ["mpris", "cider", "adapter"]

# Accent presets: (key, start, end, sweep). The key is translated in the UI
# (see strings/__init__.py "accent.*"); the first entry is the default pink.
# A few representative examples; anything else is picked via the custom colour
# picker in Settings (keeps the dropdown short).
ACCENT_PRESETS: tuple[tuple[str, str, str, str], ...] = (
    ("pink", "#FF5EB5", "#FFA3D8", "#FF7FC7"),
    ("orange", "#FF8A4F", "#FFC58F", "#FFA56E"),
    ("green", "#34E89E", "#A7F3D0", "#5BF0B0"),
    ("cyan", "#4FACFE", "#00F2FE", "#38E1FF"),
    ("purple", "#B14FFF", "#E29BFF", "#C97BFF"),
)

DEFAULT_ICON_NAME = "default"


class PanelStyle(StrEnum):
    """Supported overlay panel presentations."""

    PILL = "pill"
    WHITE = "white"
    FROST = "frost"
    TEXT = "text"


class PanelOverflowMode(StrEnum):
    """Presentation of long lyrics within a fixed-width panel."""

    SCROLL = "scroll"
    WRAP = "wrap"


class PanelWidthMode(StrEnum):
    """Whether the overlay follows lyric width or uses a fixed width."""

    FIT = "fit"
    FIXED = "fixed"


class UiLanguage(StrEnum):
    """Languages exposed by the settings UI."""

    AUTO = "auto"
    ZH_HANS = "zh-Hans"
    ZH_HANT = "zh-Hant"
    JA = "ja"
    EN = "en"


class ThemeMode(StrEnum):
    """Settings-window theme selection."""

    AUTO = "auto"
    LIGHT = "light"
    DARK = "dark"


class LyricsScript(StrEnum):
    """Display-only Chinese script conversion mode."""

    OFF = "off"
    ZH_HANS = "zh-Hans"
    ZH_HANT = "zh-Hant"


class InterludeStyle(StrEnum):
    """Marker used while a lyric document is between sung lines."""

    DOTS = "dots"
    SYMBOL = "symbol"


class InterludeCountdown(StrEnum):
    """Optional progress representation for an instrumental gap."""

    OFF = "off"
    PERCENT = "percent"
    SECONDS = "seconds"


class FxTransition(StrEnum):
    """Line-change animation choices."""

    FADE = "fade"
    RISE = "rise"
    SLIDE = "slide"
    ZOOM = "zoom"


class FxIntensity(StrEnum):
    """Visual effect intensity choices."""

    SUBTLE = "subtle"
    EXPRESSIVE = "expressive"


EnumValue = TypeVar("EnumValue", bound=StrEnum)

@dataclass
class Config:
    # Transport
    port: int = 28745
    # Placement
    anchor_top: bool = True          # True -> top edge, False -> bottom edge
    margin_edge: int = 64            # distance from the anchored edge (px)
    margin_x: int = 0                # horizontal nudge (px)
    screen_name: str = ""            # Qt output name; empty means choose the current/primary screen
    # Size of the output the offsets above were measured against. 0 means unknown
    # (a config from before this field, or one never dragged). A saved offset is
    # only meaningful on the geometry it was taken on, so this is what tells a
    # deliberate edge park apart from an offset stranded by a resolution change.
    screen_width: int = 0
    screen_height: int = 0
    # Typography / appearance
    font_family: str = "Inter, 'Segoe UI', 'Microsoft YaHei', sans-serif"
    font_style: str = "Regular"     # named style/weight for the family (e.g. "Bold", "Light Italic")
    font_size: int = 20             # main (current) line size (px)
    context_font_size: int = 14      # previous/next line size (px)
    translation_font_size: int = 13  # translation line size (px)
    opacity: float = 0.8            # black-panel fill opacity 0.0..1.0 (fully opaque reads harsh)
    frost_opacity: float = 0.6       # frosted-panel fill opacity 0.0..1.0 (0 = pure blur)
    panel_style: PanelStyle = PanelStyle.PILL
    panel_width_mode: PanelWidthMode = PanelWidthMode.FIT
    panel_overflow_mode: PanelOverflowMode = PanelOverflowMode.SCROLL
    panel_width: int = 720           # panel width in px when panel_width_mode == "fixed"
    panel_accent_tint: bool = False  # tint the black panel toward the accent colour
    icon_name: str = "@leaf-accent"  # system-tray icon; accent-following leaf by default (see leaf_icon.py)
    window_icon_name: str = "@leaf-accent"  # taskbar/window icon; chosen separately from the tray
    # Behaviour
    passthrough: bool = False        # start unlocked (interactive) so first-run positioning is easy
    karaoke: bool = True             # per-word sweep when timing == "Word"
    lead_ms: int = 120               # advance the sweep by this many ms (compensate pipeline latency)
    show_translation: bool = True    # bilingual
    context_lines: int = 1          # rows per side; 0 hides context, excess rows are clipped to the viewport
    context_blur: float = 0.0       # context defocus strength 0.0..1.0; clear text by default
    translation_language: str = "auto"  # "auto" -> from system locale, else an Apple tag (zh-Hans/en/ja/...)
    lyrics_sources: list[str] = field(default_factory=lambda: list(DEFAULT_LYRICS_SOURCES))
    display_sources: list[str] = field(default_factory=lambda: list(DEFAULT_DISPLAY_SOURCES))
    # Kept out of repr output, but persisted with the rest of config.json.
    cider_api_token: str = field(default="", repr=False, kw_only=True)
    player_lock: str = ""
    prefer_best_lyrics: bool = True  # query sources concurrently and pick the best-quality match
    fuzzy_match: bool = True          # salvage noisy browser titles (strip 【HD】/[歌詞]/channel tails)
    cache_enabled: bool = True
    ui_language: UiLanguage = UiLanguage.AUTO
    theme: ThemeMode = ThemeMode.AUTO
    frost_window: bool = True        # frosted-glass settings window (needs a blur-capable compositor)
    settings_opacity: float = 0.80   # settings-window opacity 0.0..1.0
    lyrics_script: LyricsScript = LyricsScript.OFF
    # An intro or an instrumental break has no line to show. What stands in for one:
    # "dots" fills three dots as the wait runs, "symbol" holds a still note.
    interlude_style: InterludeStyle = InterludeStyle.DOTS
    # Whether the wait also counts itself down, and in what: "off" | "percent" | "seconds".
    interlude_countdown: InterludeCountdown = InterludeCountdown.OFF
    # Pink accent (sung text gradient + sweep highlight)
    accent_start: str = "#FF5EB5"
    accent_end: str = "#FFA3D8"
    accent_sweep: str = "#FF7FC7"
    # Visual effects (all user-toggleable). Default to a calm look: animations on,
    # the flashier glow / word-pop off.
    fx_animate: bool = True          # master switch: line-change + settings fade-in animations
    fx_transition: FxTransition = FxTransition.RISE
    fx_glow: bool = False            # soft accent glow behind the current line
    fx_word_pop: bool = False        # brighten the word currently being sung
    fx_intensity: FxIntensity = FxIntensity.SUBTLE

    def clamped(self) -> Config:
        """Return a copy with values forced into sane ranges."""
        return Config(
            port=clamp_port(self.port),
            anchor_top=_clean_bool(self.anchor_top, True),
            margin_edge=_clamp_int(self.margin_edge, 0, 4000, 64),
            margin_x=_clamp_int(self.margin_x, -4000, 4000, 0),
            screen_name=str(self.screen_name),
            screen_width=_clamp_int(self.screen_width, 0, 65535, 0),
            screen_height=_clamp_int(self.screen_height, 0, 65535, 0),
            font_family=str(self.font_family),
            font_style=str(self.font_style),
            # All three ranges match the Appearance spin boxes (8..120), so opening
            # Settings and pressing Apply can never silently truncate a saved size.
            font_size=_clamp_int(self.font_size, 8, 120, 20),
            context_font_size=_clamp_int(self.context_font_size, 8, 120, 14),
            translation_font_size=_clamp_int(self.translation_font_size, 8, 120, 13),
            opacity=_clamp_float(self.opacity, 0.0, 1.0, 0.8),
            frost_opacity=_clamp_float(self.frost_opacity, 0.0, 1.0, 0.6),
            panel_style=_enum_or_default(self.panel_style, PanelStyle, PanelStyle.PILL),
            panel_width_mode=_enum_or_default(self.panel_width_mode, PanelWidthMode, PanelWidthMode.FIT),
            panel_overflow_mode=_enum_or_default(
                self.panel_overflow_mode, PanelOverflowMode, PanelOverflowMode.SCROLL
            ),
            panel_width=_clamp_int(self.panel_width, 240, 2400, 720),
            panel_accent_tint=_clean_bool(self.panel_accent_tint, False),
            icon_name=_clean_icon_name(self.icon_name),
            window_icon_name=_clean_icon_name(self.window_icon_name),
            passthrough=_clean_bool(self.passthrough, False),
            karaoke=_clean_bool(self.karaoke, True),
            lead_ms=_clamp_int(self.lead_ms, -LEAD_MS_LIMIT, LEAD_MS_LIMIT, 120),
            show_translation=_clean_bool(self.show_translation, True),
            # QSpinBox uses a signed 32-bit integer; do not impose a smaller UX cap.
            context_lines=_clamp_int(self.context_lines, 0, 2_147_483_647, 1),
            context_blur=_clamp_float(self.context_blur, 0.0, 1.0, 0.0),
            translation_language=str(self.translation_language),
            accent_start=str(self.accent_start),
            accent_end=str(self.accent_end),
            accent_sweep=str(self.accent_sweep),
            fx_animate=_clean_bool(self.fx_animate, True),
            fx_transition=_enum_or_default(self.fx_transition, FxTransition, FxTransition.RISE),
            fx_glow=_clean_bool(self.fx_glow, False),
            fx_word_pop=_clean_bool(self.fx_word_pop, False),
            fx_intensity=_enum_or_default(self.fx_intensity, FxIntensity, FxIntensity.SUBTLE),
            lyrics_sources=_clean_sources(self.lyrics_sources),
            cider_api_token=_clean_token(self.cider_api_token),
            player_lock=self.player_lock if isinstance(self.player_lock, str) else "",
            prefer_best_lyrics=_clean_bool(self.prefer_best_lyrics, True),
            fuzzy_match=_clean_bool(self.fuzzy_match, True),
            cache_enabled=_clean_bool(self.cache_enabled, True),
            ui_language=_enum_or_default(self.ui_language, UiLanguage, UiLanguage.AUTO),
            theme=_enum_or_default(self.theme, ThemeMode, ThemeMode.AUTO),
            frost_window=_clean_bool(self.frost_window, True),
            settings_opacity=_clamp_float(self.settings_opacity, 0.0, 1.0, 0.80),
            lyrics_script=_enum_or_default(self.lyrics_script, LyricsScript, LyricsScript.OFF),
            interlude_style=_enum_or_default(self.interlude_style, InterludeStyle, InterludeStyle.DOTS),
            interlude_countdown=_enum_or_default(
                self.interlude_countdown, InterludeCountdown, InterludeCountdown.OFF
            ),
            display_sources=_clean_display_sources(self.display_sources),
        )

    def settings_values(self) -> tuple[object, ...]:
        """Return Settings-owned values in ``SETTINGS_CONFIG_FIELDS`` order."""
        values = asdict(self)
        return tuple(values[field_name] for field_name in SETTINGS_CONFIG_FIELDS)

    def to_dict(self) -> dict[str, object]:
        """Serialize the validated configuration into the external JSON shape."""
        data: dict[str, object] = asdict(self)
        for key in _ENUM_FIELDS:
            value = data[key]
            if isinstance(value, StrEnum):
                data[key] = value.value
        return data

    @classmethod
    def from_dict(cls, data: object) -> Config:
        """Parse an untrusted JSON object, ignoring unknown configuration keys."""
        if not isinstance(data, Mapping):
            return cls()
        known = {f.name for f in fields(cls)}
        # ``Any`` is isolated to this JSON boundary: decoded values are
        # deliberately untyped until ``clamped`` validates every field.
        filtered: dict[str, Any] = {
            k: v for k, v in data.items() if isinstance(k, str) and k in known
        }
        # Old files can contain both a count and a visibility override. Preserve
        # the effective choice, then write only the single context-lines setting.
        # TODO: Remove when configurations predating context_lines=0 are no longer supported.
        if _clean_bool(data.get("current_line_only"), False):
            filtered["context_lines"] = 0
        try:
            return cls(**filtered).clamped()
        except (TypeError, ValueError):
            logger.warning("Invalid config contents; using defaults")
            return cls()


_ENUM_FIELDS = frozenset(
    {
        "panel_style",
        "panel_width_mode",
        "panel_overflow_mode",
        "ui_language",
        "theme",
        "lyrics_script",
        "interlude_style",
        "interlude_countdown",
        "fx_transition",
        "fx_intensity",
    }
)


#: Bound on the global sync offset, shared with the control that edits it so the
#: settings window cannot narrow what the configuration accepts.
LEAD_MS_LIMIT = 2000


def _enum_or_default(
    value: object,
    enum_type: type[EnumValue],
    default: EnumValue,
) -> EnumValue:
    """Normalize one persisted string enum without accepting arbitrary values."""
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError:
            pass
    return default


def _clean_bool(value: object, default: bool) -> bool:
    """Accept only actual booleans and the legacy JSON 0/1 representation."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return default


def _clamp_int(value: object, low: int, high: int, default: int) -> int:
    if not isinstance(value, (str, int, float, bool)):
        return default
    try:
        n = int(value)
    except (OverflowError, TypeError, ValueError):
        # OverflowError too: JSON accepts 1e400, int() refuses it, and this runs on
        # the startup path — an unhandled one meant the application did not start
        # rather than falling back to the default for that field.
        return default
    return max(low, min(high, n))


def _clean_sources(value: object) -> list[str]:
    """Keep only known sources, de-duplicated, order preserved; never empty."""
    if not isinstance(value, list):
        return list(DEFAULT_LYRICS_SOURCES)
    cleaned: list[str] = []
    for source in value:
        if source in VALID_LYRICS_SOURCES and source not in cleaned:
            cleaned.append(source)
    return cleaned or list(DEFAULT_LYRICS_SOURCES)


def _clean_display_sources(value: object) -> list[str]:
    """Keep known display adapters enabled, ordered, and never empty."""
    if not isinstance(value, list):
        return list(DEFAULT_DISPLAY_SOURCES)
    cleaned: list[str] = []
    for source in value:
        if source in VALID_DISPLAY_SOURCES and source not in cleaned:
            cleaned.append(source)
    return cleaned or list(DEFAULT_DISPLAY_SOURCES)


def _clean_token(value: object) -> str:
    """Normalize the in-memory token without ever treating it as config data."""
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _clean_icon_name(value: object) -> str:
    if not isinstance(value, str) or not value or value == DEFAULT_ICON_NAME:
        return DEFAULT_ICON_NAME
    return value if Path(value).name == value else DEFAULT_ICON_NAME


def clamp_port(port: int) -> int:
    """Return a receiver port constrained to the valid TCP range."""
    return _clamp_int(port, 1, 65535, 28745)


def _clamp_float(value: object, low: float, high: float, default: float) -> float:
    if not isinstance(value, (str, int, float, bool)):
        return default
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, n))
