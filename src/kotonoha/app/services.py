"""Application services that apply configuration to runtime collaborators."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..config import Config
from ..display.models import (
    DisplayOptions,
    DisplayScript,
    InterludeCountdown,
    InterludeMarkerStyle,
)
from ..display.offsets import TrackOffsetSnapshot
from ..i18n import resolve_translation_language


class UiRuntimePort(Protocol):
    """Application-facing UI operations affected by runtime configuration."""

    def set_language(self, value: str | None) -> None: ...

    def set_window_icon(self, icon_name: str, accent: str) -> None: ...


class DisplayRuntimePort(Protocol):
    """Display option operation needed during a live config update."""

    def set_options(self, options: DisplayOptions) -> None: ...


class OverlayRuntimePort(Protocol):
    """Overlay operations needed during a live config update."""

    def activate_layer_shell(self) -> bool: ...

    def apply_config(self, config: Config) -> None: ...


class TrayRuntimePort(Protocol):
    """Tray operations needed during a live config update."""

    def set_icon_name(self, icon_name: str, accent: str) -> None: ...

    def set_passthrough_checked(self, checked: bool) -> None: ...


class MprisRuntimePort(Protocol):
    """MPRIS policy operations needed during a live config update."""

    def set_lyrics_sources(self, sources: list[str]) -> None: ...

    def set_player_lock(self, bus_name: str) -> None: ...

    def set_cache_enabled(self, enabled: bool) -> None: ...

    def set_prefer_best(self, enabled: bool) -> None: ...

    def set_fuzzy(self, enabled: bool) -> None: ...


class CiderRuntimePort(Protocol):
    """Cider policy operations needed during a live config update."""

    def set_enabled(self, enabled: bool) -> None: ...

    def set_token(self, token: str | None) -> None: ...

    def set_translation_language(self, language: str | None) -> None: ...


class SourceRuntimePort(Protocol):
    """Display-source policy operation needed during a live config update."""

    def set_display_sources(self, sources: Sequence[str]) -> None: ...


class TrackOffsetSnapshotPort(Protocol):
    """Read-only snapshot capability needed when Settings are applied."""

    def snapshot(self) -> TrackOffsetSnapshot:
        """Return the current structured track-offset state."""
        ...


class TranslationRuntimePort(Protocol):
    """Live configuration update boundary for optional lyrics API translation."""

    def apply_config(self, config: Config) -> None:
        """Update translation settings and re-evaluate active lyrics."""
        ...


class RuntimeConfigApplier:
    """Apply one validated config to all already-composed runtime collaborators."""

    def __init__(
        self,
        ui: UiRuntimePort,
        display: DisplayRuntimePort,
        overlay: OverlayRuntimePort,
        tray: TrayRuntimePort,
        mpris: MprisRuntimePort,
        cider: CiderRuntimePort,
        ownership: SourceRuntimePort,
        track_offsets: TrackOffsetSnapshotPort,
        translation: TranslationRuntimePort | None = None,
    ) -> None:
        self._ui = ui
        self._display = display
        self._overlay = overlay
        self._tray = tray
        self._mpris = mpris
        self._cider = cider
        self._ownership = ownership
        self._track_offsets = track_offsets
        self._translation = translation

    def apply(self, previous: Config, current: Config) -> None:
        """Refresh runtime collaborators from the latest validated config."""
        self._display.set_options(display_options(current, self._track_offsets.snapshot()))
        self._overlay.apply_config(current)
        self._overlay.activate_layer_shell()
        self._tray.set_passthrough_checked(current.passthrough)
        self._ui.set_window_icon(current.window_icon_name, current.accent_start)
        self._tray.set_icon_name(current.icon_name, current.accent_start)
        self._mpris.set_lyrics_sources(current.lyrics_sources)
        self._cider.set_enabled("cider" in current.lyrics_sources)
        self._cider.set_token(current.cider_api_token)
        self._mpris.set_player_lock(current.player_lock)
        self._mpris.set_cache_enabled(current.cache_enabled)
        self._mpris.set_prefer_best(current.prefer_best_lyrics)
        self._mpris.set_fuzzy(current.fuzzy_match)
        self._ownership.set_display_sources(current.display_sources)
        self._ui.set_language(current.ui_language)

        previous_language = resolve_translation_language(previous.translation_language)
        current_language = resolve_translation_language(current.translation_language)
        if current_language != previous_language:
            self._cider.set_translation_language(current_language)
        if self._translation is not None:
            self._translation.apply_config(current)
def display_options(config: Config, track_offsets: TrackOffsetSnapshot) -> DisplayOptions:
    """Build immutable display options from settings and runtime offset state."""
    return DisplayOptions(
        lead_ms=config.lead_ms,
        track_offsets_ms=track_offsets.as_mapping(),
        lyrics_script=DisplayScript(config.lyrics_script.value),
        interlude_style=InterludeMarkerStyle(config.interlude_style.value),
        interlude_countdown=InterludeCountdown(config.interlude_countdown.value),
    )


__all__ = [
    "CiderRuntimePort",
    "DisplayRuntimePort",
    "MprisRuntimePort",
    "OverlayRuntimePort",
    "RuntimeConfigApplier",
    "SourceRuntimePort",
    "TrackOffsetSnapshotPort",
    "TranslationRuntimePort",
    "TrayRuntimePort",
    "UiRuntimePort",
    "display_options",
]
