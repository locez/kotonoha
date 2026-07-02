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
VALID_LYRICS_SOURCES = ("netease", "lrclib", "cider")
DEFAULT_LYRICS_SOURCES = ["netease", "lrclib", "cider"]

# Accent presets: (key, start, end, sweep). The key is translated in the UI
# (see strings.py "accent.*"); the first entry is the default pink.
ACCENT_PRESETS: tuple[tuple[str, str, str, str], ...] = (
    ("pink", "#FF4FA3", "#FF8FCB", "#FF6EC7"),
    ("cyan", "#4FACFE", "#00F2FE", "#38E1FF"),
    ("purple", "#B14FFF", "#E29BFF", "#C97BFF"),
    ("green", "#34E89E", "#A7F3D0", "#5BF0B0"),
    ("orange", "#FF8A4F", "#FFC58F", "#FFA56E"),
)


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
    font_size: int = 24             # current-line size (px)
    opacity: float = 1.0            # whole-window opacity 0.3..1.0
    panel_style: str = "pill"        # "pill" (glass panel) | "text" (text only)
    # Behaviour
    passthrough: bool = False        # start unlocked (interactive) so first-run positioning is easy
    karaoke: bool = True             # per-word sweep when timing == "Word"
    lead_ms: int = 120               # advance the sweep by this many ms (compensate pipeline latency)
    show_translation: bool = True    # bilingual
    translation_language: str = "auto"  # "auto" -> from system locale, else an Apple tag (zh-Hans/en/ja/...)
    lyrics_sources: list[str] = field(default_factory=lambda: list(DEFAULT_LYRICS_SOURCES))
    ui_language: str = "auto"        # UI language: "auto" -> system locale, else zh-Hans/zh-Hant/ja/en
    # Pink accent (sung text gradient + sweep highlight)
    accent_start: str = "#FF4FA3"
    accent_end: str = "#FF8FCB"
    accent_sweep: str = "#FF6EC7"

    def clamped(self) -> Config:
        """Return a copy with values forced into sane ranges."""
        return Config(
            port=_clamp_int(self.port, 1, 65535, 28745),
            anchor_top=bool(self.anchor_top),
            margin_edge=_clamp_int(self.margin_edge, 0, 4000, 64),
            margin_x=_clamp_int(self.margin_x, -4000, 4000, 0),
            font_family=str(self.font_family),
            font_size=_clamp_int(self.font_size, 8, 200, 24),
            opacity=_clamp_float(self.opacity, 0.3, 1.0, 1.0),
            panel_style=self.panel_style if self.panel_style in ("pill", "text") else "pill",
            passthrough=bool(self.passthrough),
            karaoke=bool(self.karaoke),
            lead_ms=_clamp_int(self.lead_ms, -2000, 2000, 120),
            show_translation=bool(self.show_translation),
            translation_language=str(self.translation_language),
            accent_start=str(self.accent_start),
            accent_end=str(self.accent_end),
            accent_sweep=str(self.accent_sweep),
            lyrics_sources=_clean_sources(self.lyrics_sources),
            ui_language=str(self.ui_language),
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


def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, n))
