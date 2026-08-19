"""User configuration: load/save to XDG config dir.

Pure dataclass + (de)serialization so it can be unit-tested without touching the
real home directory. Unknown keys in the file are ignored; missing keys fall
back to defaults, so config files survive version upgrades.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

APP_DIR_NAME = "kotonoha"
CONFIG_FILE_NAME = "config.json"

# Lyric sources in priority order; first one with lyrics for the song wins.
# "cider" = the Apple Music lyrics the Cider probe pushes over WebSocket.
VALID_LYRICS_SOURCES = ("netease", "lrclib", "kugou", "qqmusic", "cider")
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
TRACK_OFFSET_CAP = 100
TRACK_OFFSET_STEP_MS = 50


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
    track_offsets: dict[str, int] = field(default_factory=dict)
    show_translation: bool = True    # bilingual
    current_line_only: bool = False  # hide the previous and next context lines
    translation_language: str = "auto"  # "auto" -> from system locale, else an Apple tag (zh-Hans/en/ja/...)
    lyrics_sources: list[str] = field(default_factory=lambda: list(DEFAULT_LYRICS_SOURCES))
    player_lock: str = ""
    prefer_best_lyrics: bool = True  # query sources concurrently and pick the best-quality match
    fuzzy_match: bool = True          # salvage noisy browser titles (strip 【HD】/[歌詞]/channel tails)
    cache_enabled: bool = True
    ui_language: str = "auto"        # UI language: "auto" -> system locale, else zh-Hans/zh-Hant/ja/en
    theme: str = "auto"              # settings-window theme: "auto" (follow system) | "light" | "dark"
    frost_window: bool = True        # frosted-glass settings window (needs a blur-capable compositor)
    settings_opacity: float = 0.95   # settings-window opacity 0.0..1.0 (a touch see-through by default)
    lyrics_script: str = "off"       # display-convert lyrics: "off" | "zh-Hans" | "zh-Hant"
    # An intro or an instrumental break has no line to show. What stands in for one:
    # "dots" fills three dots as the wait runs, "symbol" holds a still note.
    interlude_style: str = "dots"
    # Whether the wait also counts itself down, and in what: "off" | "percent" | "seconds".
    interlude_countdown: str = "off"
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
            panel_style=self.panel_style if self.panel_style in ("pill", "white", "frost", "text") else "pill",
            panel_width_mode=self.panel_width_mode if self.panel_width_mode in ("fit", "fixed") else "fit",
            panel_width=_clamp_int(self.panel_width, 240, 2400, 720),
            panel_accent_tint=bool(self.panel_accent_tint),
            icon_name=_clean_icon_name(self.icon_name),
            window_icon_name=_clean_icon_name(self.window_icon_name),
            passthrough=bool(self.passthrough),
            karaoke=bool(self.karaoke),
            lead_ms=_clamp_int(self.lead_ms, -LEAD_MS_LIMIT, LEAD_MS_LIMIT, 120),
            track_offsets=_clean_track_offsets(self.track_offsets),
            show_translation=bool(self.show_translation),
            current_line_only=bool(self.current_line_only),
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
            player_lock=self.player_lock if isinstance(self.player_lock, str) else "",
            prefer_best_lyrics=bool(self.prefer_best_lyrics),
            fuzzy_match=bool(self.fuzzy_match),
            cache_enabled=bool(self.cache_enabled),
            ui_language=str(self.ui_language),
            theme=self.theme if self.theme in ("auto", "light", "dark") else "auto",
            frost_window=bool(self.frost_window),
            settings_opacity=_clamp_float(self.settings_opacity, 0.0, 1.0, 0.95),
            lyrics_script=self.lyrics_script if self.lyrics_script in ("off", "zh-Hans", "zh-Hant") else "off",
            interlude_style=self.interlude_style if self.interlude_style in ("dots", "symbol") else "dots",
            interlude_countdown=(
                self.interlude_countdown if self.interlude_countdown in ("off", "percent", "seconds") else "off"
            ),
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


#: A settings file is a few kilobytes. The read is bounded because this path is
#: reachable by anything with write access to the user's config directory.
MAX_CONFIG_BYTES: Final[int] = 4 * 1024 * 1024


def _read_config_bytes(target: Path) -> bytes | None:
    """Return the file's bytes, or None when there is nothing usable to read.

    Opened non-blocking and checked through the descriptor: this runs on the
    startup path, and a FIFO left at the config path blocked it forever while a
    non-regular file would have been followed wherever it led.
    """
    try:
        descriptor = os.open(target, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("Could not read config %s: %s", target, exc)
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            logger.warning("Config %s is not an ordinary file; using defaults", target)
            return None
        chunks: list[bytes] = []
        remaining = MAX_CONFIG_BYTES
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 1 << 16))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError as exc:
        logger.warning("Could not read config %s: %s", target, exc)
        return None
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def load_config(path: Path | None = None) -> Config:
    """Return the stored configuration, or defaults when there is none to trust.

    Never raises: this runs before there is any window to report a problem in, so
    a missing, unreadable, non-regular or unparseable file yields defaults instead
    of ending startup. A file that exists but cannot be understood is moved to
    ``<name>.corrupt`` first, so the values in it survive the next save.
    """
    target = path or config_path()
    data = _read_config_bytes(target)
    if data is None:
        return Config()
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        # Left to escape, this ended startup: the file is read before there is any
        # window to report it in, so a config that is not UTF-8 took the whole
        # application down rather than costing the settings in it.
        raw = ""
    try:
        return Config.from_dict(json.loads(raw))
    except (json.JSONDecodeError, ValueError):
        # Defaults are returned so the app still starts, but the unreadable file is
        # moved aside first. It used to be left in place, and the next save — a drag
        # release is enough — wrote the defaults over it, so a single interrupted
        # write turned into permanent loss of every setting the user had chosen.
        salvaged = target.with_suffix(target.suffix + ".corrupt")
        try:
            target.replace(salvaged)
        except OSError as exc:
            logger.warning("Config %s is unreadable and could not be set aside: %s", target, exc)
        else:
            logger.warning("Config %s is not valid JSON; kept as %s and using defaults", target, salvaged)
        return Config()


def save_config(config: Config, path: Path | None = None) -> None:
    """Persist the configuration, leaving no half-written file behind.

    Written to a sibling temporary file and renamed over the target, because a
    rename within one directory is atomic: a reader either sees the whole previous
    file or the whole new one. Writing in place meant a logout, an OOM kill or a
    full disk during any of the writes this makes — one per settings apply and one
    per drag release — could leave truncated JSON that the loader then discarded.
    """
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
    # Created exclusively under an unpredictable name: a fixed one is a file another
    # process can put a symlink at first, and this write would follow it.
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".new"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            # The rename is atomic, but only orders against data the filesystem has
            # actually taken: without this, ext4's delayed allocation can record the
            # rename first and leave an empty file after a crash. Measured here at a
            # median 0.4 ms, on a path reached by discrete user actions — a drag
            # release, an offset nudge, a settings apply — not per frame.
            os.fsync(handle.fileno())
        temporary.replace(target)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


#: Bound on the global sync offset, shared with the control that edits it so the
#: settings window cannot narrow what the configuration accepts.
LEAD_MS_LIMIT = 2000


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        n = int(value)
    except (OverflowError, TypeError, ValueError):
        # OverflowError too: JSON accepts 1e400, int() refuses it, and this runs on
        # the startup path — an unhandled one meant the application did not start
        # rather than falling back to the default for that field.
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


def _clean_track_offsets(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, int] = {}
    for key, offset in value.items():
        if isinstance(key, str) and key:
            cleaned[key] = _clamp_int(offset, -10_000, 10_000, 0)
    return dict(list(cleaned.items())[-TRACK_OFFSET_CAP:])


def track_identity_key(title: str, artist: str, duration_s: float | None = None) -> str:
    del duration_s  # Source-specific duration reporting must not split one recording's key.
    return "\x1f".join((title.strip().casefold(), artist.strip().casefold()))


def set_track_offset(config: Config, key: str, offset_ms: int) -> int:
    """Store a recent track offset and return its clamped value."""
    offset = _clamp_int(offset_ms, -10_000, 10_000, 0)
    config.track_offsets.pop(key, None)
    config.track_offsets[key] = offset
    while len(config.track_offsets) > TRACK_OFFSET_CAP:
        config.track_offsets.pop(next(iter(config.track_offsets)))
    return offset


def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, n))
