"""Application-facing component ports and the composed runtime bundle."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from ..config import Config, TranslationProvider
from ..display.models import DisplayOptions, LyricsDisplayStatus
from ..display.offsets import TrackOffsetKey, TrackOffsetSnapshot
from ..lyrics.artifact import LyricsArtifact
from ..lyrics.match import TrackMetadata
from ..lyrics.search import LyricsSearchPort
from ..platform.overlay_contracts import SurfaceResult
from ..players import PlayerInfo
from .cache_management import LyricsCacheManagementPort
from .lyrics_search import LyricsCacheWritePort
from .settings_port import (
    CacheManagementDialogFactory,
    LyricsSearchDialogFactory,
    SettingsDialogFactory,
    TranslationCacheDialogFactory,
)
from .translation_cache_management import TranslationCacheManagementPort
from .translation_coordinator import TranslationSecretSnapshot


class ApplicationQuitPort(Protocol):
    """Process-level quit operation owned by the GUI composition root."""

    def quit(self) -> None:
        """Request termination of the host application event loop."""
        ...


class RestartLauncher(Protocol):
    """Start a replacement process and report whether launch was accepted."""

    def start(self, executable: str, arguments: Sequence[str]) -> bool:
        """Start ``executable`` with ``arguments`` without owning its lifetime."""
        ...


class ConfigServicePort(Protocol):
    """Mutable validated configuration state used by the controller."""

    @property
    def config(self) -> Config:
        """Return a detached current configuration view."""
        ...

    async def close(self) -> None:
        """Flush pending persistence and release the config worker."""
        ...

    def apply_settings(self, config: Config, changed_fields: frozenset[str]) -> Config:
        """Merge changed Settings fields and persist the resulting config."""
        ...

    def set_passthrough(self, enabled: bool) -> Config:
        """Update and persist overlay passthrough state."""
        ...

    def set_position(
        self,
        margin_edge: int,
        margin_x: int,
        screen_name: str,
        screen_width: int,
        screen_height: int,
    ) -> Config:
        """Update and persist output-local overlay placement."""
        ...

class SignalPort(Protocol):
    """Minimal signal surface required by controller-owned UI ports."""

    def connect(self, slot: Callable[..., object]) -> object:
        """Connect one application callback to the signal."""
        ...


class OverlayPort(Protocol):
    """Overlay lifecycle and signals used by application orchestration."""

    @property
    def passthrough_toggle_requested(self) -> SignalPort:
        """Return the user-requested passthrough signal."""
        ...

    @property
    def settings_requested(self) -> SignalPort:
        """Return the user-requested Settings signal."""
        ...

    @property
    def quit_requested(self) -> SignalPort:
        """Return the user-requested application exit signal."""
        ...

    @property
    def lyrics_search_requested(self) -> SignalPort:
        """Return the user-requested manual lyric-search signal."""
        ...

    @property
    def position_changed(self) -> SignalPort:
        """Return the output-position change signal."""
        ...

    @property
    def track_offset_changed(self) -> SignalPort:
        """Return the track-offset change signal."""
        ...

    def activate_layer_shell(self) -> bool:
        """Activate the overlay surface before it is shown."""
        ...

    def show(self) -> None:
        """Show the overlay surface."""
        ...

    def shutdown(self) -> SurfaceResult:
        """Release overlay resources and report the platform result."""
        ...

    def set_passthrough(self, enabled: bool) -> None:
        """Apply click-through input policy."""
        ...

    def apply_config(self, config: Config) -> None:
        """Apply presentation settings to the visible overlay."""
        ...


class DisplayLifecyclePort(Protocol):
    """Display coordinator lifecycle, option, and immediate lyric operations."""

    async def start(self) -> None:
        """Start the owned display clock and publication workflow."""
        ...

    async def stop(self) -> None:
        """Cancel and await the display clock."""
        ...

    def set_options(self, options: DisplayOptions) -> None:
        """Replace display options for subsequent projections."""
        ...

    def apply_manual_artifact(self, artifact: LyricsArtifact, expected_track: TrackMetadata) -> bool:
        """Replace the active lyric document immediately when the expected track is still playing."""
        ...

    def current_lyrics_status(self) -> LyricsDisplayStatus:
        """Return the source facts for the document currently visible in the overlay."""
        ...


class ReceiverPort(Protocol):
    """External adapter receiver lifecycle."""

    async def start(self) -> None:
        """Start listening for generic adapter messages."""
        ...

    async def stop(self) -> None:
        """Close the adapter listener and await its client tasks."""
        ...


class CiderPort(Protocol):
    """Cider provider lifecycle and runtime configuration operations."""

    async def start(self) -> None:
        """Start Cider HTTP polling when the provider is enabled."""
        ...

    async def stop(self) -> None:
        """Cancel Cider polling and close its HTTP session."""
        ...

    def set_token(self, token: str | None) -> None:
        """Apply an optional runtime API token."""
        ...


class MprisPort(Protocol):
    """MPRIS provider lifecycle and settings operations."""

    async def start(self) -> None:
        """Start MPRIS discovery, polling, and lyric workflows."""
        ...

    async def stop(self) -> None:
        """Cancel MPRIS tasks and close the session bus."""
        ...

    async def available_players(self) -> list[PlayerInfo]:
        """Return players visible on the current session bus."""
        ...

class TrayPort(Protocol):
    """Tray operations owned by the application controller."""

    def show(self) -> None:
        """Show the tray icon and its menu."""
        ...

    def set_passthrough_checked(self, checked: bool) -> None:
        """Synchronize the menu check state with the runtime setting."""
        ...


class RuntimeConfigPort(Protocol):
    """Apply validated configuration to the composed runtime graph."""

    def apply(self, previous: Config, current: Config) -> None:
        """Apply changed settings to all affected runtime collaborators."""
        ...


class TrackOffsetPort(Protocol):
    """Application-owned timing-correction state used by display and HUD."""

    def snapshot(self) -> TrackOffsetSnapshot:
        """Return the immutable corrections currently active in display projection."""
        ...

    def offset_for(self, key: TrackOffsetKey) -> int:
        """Return the correction for one structured lyric timeline identity."""
        ...

    def set_offset(self, key: TrackOffsetKey, offset_ms: int) -> TrackOffsetSnapshot:
        """Update one correction and schedule its persistence."""
        ...

    async def close(self) -> None:
        """Flush pending persistence and release the offset worker."""
        ...


class TranslationCoordinatorPort(Protocol):
    """Lifecycle and command boundary for optional lyrics API translation."""

    async def start(self) -> None:
        """Start the translation service and secret worker."""
        ...

    async def stop(self) -> None:
        """Cancel in-flight translations and release owned resources."""
        ...

    async def secret_snapshot(self) -> TranslationSecretSnapshot:
        """Return keyring availability and saved-key status for Settings."""
        ...

    def save_api_key(self, provider: TranslationProvider, api_key: str) -> None:
        """Persist one provider API key in the system keyring."""
        ...

    def delete_api_key(self, provider: TranslationProvider) -> None:
        """Remove one provider API key from the system keyring."""
        ...

    def clear_cache(self) -> None:
        """Delete persisted translation cache rows."""
        ...

    def refresh_active_document(self) -> None:
        """Re-apply cached translations to the active track after an edit."""
        ...


@dataclass(frozen=True, slots=True)
class ApplicationComponents:
    """All long-lived collaborators that the application controller owns.

    The fields are ports rather than concrete providers. The composition root is
    the only place that chooses concrete implementations.
    """

    config_service: ConfigServicePort
    track_offsets: TrackOffsetPort
    restart_launcher: RestartLauncher
    display: DisplayLifecyclePort
    overlay: OverlayPort
    settings_factory: SettingsDialogFactory
    cache_management_factory: CacheManagementDialogFactory
    lyrics_search_factory: LyricsSearchDialogFactory
    lyrics_cache: LyricsCacheManagementPort
    lyrics_cache_writer: LyricsCacheWritePort
    lyrics_search: LyricsSearchPort
    receiver: ReceiverPort
    cider: CiderPort
    mpris: MprisPort
    tray: TrayPort
    runtime_config: RuntimeConfigPort
    translation: TranslationCoordinatorPort | None = None
    translation_cache: TranslationCacheManagementPort | None = None
    translation_cache_factory: TranslationCacheDialogFactory | None = None


__all__ = [
    "ApplicationComponents",
    "ApplicationQuitPort",
    "CiderPort",
    "ConfigServicePort",
    "DisplayLifecyclePort",
    "LyricsCacheManagementPort",
    "LyricsCacheWritePort",
    "LyricsSearchPort",
    "MprisPort",
    "OverlayPort",
    "ReceiverPort",
    "RuntimeConfigPort",
    "TrackOffsetPort",
    "TranslationCoordinatorPort",
    "RestartLauncher",
    "SignalPort",
    "TrayPort",
]
