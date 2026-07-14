"""User configuration: load/save to XDG config dir.

Pure dataclass + (de)serialization so it can be unit-tested without touching the
real home directory. Unknown keys in the file are ignored; missing keys fall
back to defaults, so config files survive version upgrades.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

APP_DIR_NAME = "kotonoha"
CONFIG_FILE_NAME = "config.json"

# Lyric sources in priority order; first one with lyrics for the song wins.
# "cider" = the Apple Music lyrics the Cider probe pushes over WebSocket.
VALID_LYRICS_SOURCES = ("netease", "lrclib", "kugou", "cider")
DEFAULT_LYRICS_SOURCES = ["netease", "lrclib", "kugou", "cider"]

# Accent presets: (key, start, end, sweep). The key is translated in the UI
# (see strings.py "accent.*"); the first entry is the default pink.
# A few representative examples; anything else is picked via the custom colour
# picker in Settings (keeps the dropdown short).
ACCENT_PRESETS: tuple[tuple[str, str, str, str], ...] = (
    ("pink", "#FF4FA3", "#FF8FCB", "#FF6EC7"),
    ("orange", "#FF8A4F", "#FFC58F", "#FFA56E"),
    ("green", "#34E89E", "#A7F3D0", "#5BF0B0"),
    ("cyan", "#4FACFE", "#00F2FE", "#38E1FF"),
    ("purple", "#B14FFF", "#E29BFF", "#C97BFF"),
)

DEFAULT_ICON_NAME = "default"


@dataclass
class Config:
    # Transport
    port: int = 28745
    # Placement
    anchor_top: bool = True          # True -> top edge, False -> bottom edge
    margin_edge: int = 64            # distance from the anchored edge (px)
    margin_x: int = 0                # horizontal nudge (px)
    # Typography / appearance
    font_family: str = "Inter, 'Segoe UI', 'Microsoft YaHei', sans-serif"
    font_style: str = "Regular"     # named style/weight for the family (e.g. "Bold", "Light Italic")
    font_size: int = 20             # main (current) line size (px)
    context_font_size: int = 14      # previous/next line size (px)
    translation_font_size: int = 13  # translation line size (px)
    opacity: float = 0.8            # black-panel fill opacity 0.0..1.0 (fully opaque reads harsh)
    frost_opacity: float = 0.6       # frosted-panel fill opacity 0.0..1.0 (0 = pure blur)
    panel_style: str = "pill"        # "pill" (black) | "white" | "frost" (frosted glass) | "text" (no panel)
    panel_width_mode: str = "fit"    # "fit" (hug the text) | "fixed" (constant width)
    panel_width: int = 720           # panel width in px when panel_width_mode == "fixed"
    panel_accent_tint: bool = False  # tint the black panel toward the accent colour
    icon_name: str = "@leaf-accent"  # system-tray icon; accent-following leaf by default (see leaf_icon.py)
    window_icon_name: str = "@leaf-accent"  # taskbar/window icon; chosen separately from the tray
    # Behaviour
    passthrough: bool = False        # start unlocked (interactive) so first-run positioning is easy
    karaoke: bool = True             # per-word sweep when timing == "Word"
    lead_ms: int = 120               # advance the sweep by this many ms (compensate pipeline latency)
    show_translation: bool = True    # bilingual
    translation_language: str = "auto"  # "auto" -> from system locale, else an Apple tag (zh-Hans/en/ja/...)
    lyrics_sources: list[str] = field(default_factory=lambda: list(DEFAULT_LYRICS_SOURCES))
    prefer_best_lyrics: bool = True  # query sources concurrently and pick the best-quality match
    fuzzy_match: bool = True          # salvage noisy browser titles (strip 【HD】/[歌詞]/channel tails)
    cache_enabled: bool = True
    ui_language: str = "auto"        # UI language: "auto" -> system locale, else zh-Hans/zh-Hant/ja/en
    theme: str = "auto"              # settings-window theme: "auto" (follow system) | "light" | "dark"
    frost_window: bool = True        # frosted-glass settings window (KDE Wayland only)
    settings_opacity: float = 0.95   # settings-window opacity 0.0..1.0 (a touch see-through by default)
    lyrics_script: str = "off"       # display-convert lyrics: "off" | "zh-Hans" | "zh-Hant"
    # Pink accent (sung text gradient + sweep highlight)
    accent_start: str = "#FF4FA3"
    accent_end: str = "#FF8FCB"
    accent_sweep: str = "#FF6EC7"
    # Visual effects (all user-toggleable). Default to a calm look: animations on,
    # the flashier glow / word-pop off.
    fx_animate: bool = True          # master switch: line-change + settings fade-in animations
    fx_transition: str = "rise"      # line-change style when fx_animate: "fade"|"rise"|"slide"|"zoom"
    fx_glow: bool = False            # soft accent glow behind the current line
    fx_word_pop: bool = False        # brighten the word currently being sung
    fx_intensity: str = "subtle"     # "subtle" | "expressive"

    def clamped(self) -> Config:
        """Return a copy with values forced into sane ranges."""
        return Config(
            port=_clamp_int(self.port, 1, 65535, 28745),
            anchor_top=bool(self.anchor_top),
            margin_edge=_clamp_int(self.margin_edge, 0, 4000, 64),
            margin_x=_clamp_int(self.margin_x, -4000, 4000, 0),
            font_family=str(self.font_family),
            font_style=str(self.font_style),
            # All three ranges match the Appearance spin boxes (8..120), so opening
            # Settings and pressing Apply can never silently truncate a saved size.
            font_size=_clamp_int(self.font_size, 8, 120, 20),
            context_font_size=_clamp_int(self.context_font_size, 8, 120, 14),
            translation_font_size=_clamp_int(self.translation_font_size, 8, 120, 13),
            opacity=_clamp_float(self.opacity, 0.0, 1.0, 0.8),
            frost_opacity=_clamp_float(self.frost_opacity, 0.0, 1.0, 0.6),
            panel_style=self.panel_style if self.panel_style in ("pill", "white", "frost", "text") else "pill",
            panel_width_mode=self.panel_width_mode if self.panel_width_mode in ("fit", "fixed") else "fit",
            panel_width=_clamp_int(self.panel_width, 240, 2400, 720),
            panel_accent_tint=bool(self.panel_accent_tint),
            icon_name=_clean_icon_name(self.icon_name),
            window_icon_name=_clean_icon_name(self.window_icon_name),
            passthrough=bool(self.passthrough),
            karaoke=bool(self.karaoke),
            lead_ms=_clamp_int(self.lead_ms, -2000, 2000, 120),
            show_translation=bool(self.show_translation),
            translation_language=str(self.translation_language),
            accent_start=str(self.accent_start),
            accent_end=str(self.accent_end),
            accent_sweep=str(self.accent_sweep),
            fx_animate=bool(self.fx_animate),
            fx_transition=self.fx_transition if self.fx_transition in ("fade", "rise", "slide", "zoom") else "rise",
            fx_glow=bool(self.fx_glow),
            fx_word_pop=bool(self.fx_word_pop),
            fx_intensity=self.fx_intensity if self.fx_intensity in ("subtle", "expressive") else "subtle",
            lyrics_sources=_clean_sources(self.lyrics_sources),
            prefer_best_lyrics=bool(self.prefer_best_lyrics),
            fuzzy_match=bool(self.fuzzy_match),
            cache_enabled=bool(self.cache_enabled),
            ui_language=str(self.ui_language),
            theme=self.theme if self.theme in ("auto", "light", "dark") else "auto",
            frost_window=bool(self.frost_window),
            settings_opacity=_clamp_float(self.settings_opacity, 0.0, 1.0, 0.95),
            lyrics_script=self.lyrics_script if self.lyrics_script in ("off", "zh-Hans", "zh-Hant") else "off",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Config:
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        try:
            return cls(**filtered).clamped()
        except (TypeError, ValueError):
            logger.warning("Invalid config contents; using defaults")
            return cls()


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / APP_DIR_NAME


def config_path() -> Path:
    return config_dir() / CONFIG_FILE_NAME


def load_config(path: Path | None = None) -> Config:
    target = path or config_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config()
    except OSError as exc:
        logger.warning("Could not read config %s: %s", target, exc)
        return Config()
    try:
        return Config.from_dict(json.loads(raw))
    except (json.JSONDecodeError, ValueError):
        logger.warning("Config %s is not valid JSON; using defaults", target)
        return Config()


def save_config(config: Config, path: Path | None = None) -> None:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, n))


def _clean_sources(value: Any) -> list[str]:
    """Keep only known sources, de-duplicated, order preserved; never empty."""
    if not isinstance(value, list):
        return list(DEFAULT_LYRICS_SOURCES)
    cleaned: list[str] = []
    for source in value:
        if source in VALID_LYRICS_SOURCES and source not in cleaned:
            cleaned.append(source)
    return cleaned or list(DEFAULT_LYRICS_SOURCES)


def _clean_icon_name(value: Any) -> str:
    if not isinstance(value, str) or not value or value == DEFAULT_ICON_NAME:
        return DEFAULT_ICON_NAME
    return value if Path(value).name == value else DEFAULT_ICON_NAME


def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, n))
