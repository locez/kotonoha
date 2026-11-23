"""Application-facing contract for opening and observing the Settings dialog."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..config import Config
from ..display.models import LyricsDisplayStatus
from ..lyrics.cache import CacheDeleteResult, CacheWriteResult, LyricsCacheEntry, LyricsCacheQuery
from ..lyrics.search import LyricsSearchQuery, LyricsSearchResponse
from ..players import PlayerInfo
from ..translation import (
    TranslationCacheDeleteResult,
    TranslationCacheEntry,
    TranslationCacheQuery,
    TranslationCacheRecord,
)
from .translation_coordinator import TranslationSecretSnapshot


class SignalPort(Protocol):
    """Minimal signal surface needed by application lifecycle code."""

    def connect(self, slot: Callable[..., object]) -> object:
        """Connect one application callback to the signal."""
        ...


class SettingsDialogPort(Protocol):
    """Non-Qt dialog operations used by the application controller."""

    @property
    def intent_requested(self) -> SignalPort:
        """Return the typed intent signal emitted by the dialog."""
        ...

    @property
    def finished(self) -> SignalPort:
        """Return the signal emitted when the dialog closes."""
        ...

    def show(self) -> None:
        """Show the ordinary, user-draggable Settings window."""
        ...

    def close(self) -> object:
        """Close the dialog and release its Qt resources."""
        ...

    def raise_(self) -> object:
        """Raise an already-open dialog without creating another one."""
        ...

    def activateWindow(self) -> object:
        """Request keyboard focus for the existing dialog."""
        ...


class SettingsDialogFactory(Protocol):
    """Create one presentation dialog for the current application state."""

    def create(
        self,
        config: Config,
        players: list[PlayerInfo],
        *,
        translation_secrets: TranslationSecretSnapshot | None = None,
    ) -> SettingsDialogPort:
        """Create one dialog using the current config and player choices."""
        ...


class CacheManagementDialogPort(Protocol):
    """Presentation boundary for the independently opened cache manager."""

    @property
    def intent_requested(self) -> SignalPort:
        """Return typed cache-management intents emitted by the dialog."""
        ...

    @property
    def finished(self) -> SignalPort:
        """Return the signal emitted when the cache manager closes."""
        ...

    def retheme(self, config: Config) -> None:
        """Adopt a newly applied theme while the window stays open."""
        ...

    def show(self) -> None:
        """Show the cache manager window."""
        ...

    def close(self) -> object:
        """Close the cache manager window."""
        ...

    def raise_(self) -> object:
        """Raise an already-open cache manager window."""
        ...

    def activateWindow(self) -> object:
        """Request keyboard focus for the cache manager window."""
        ...

    def set_entries(self, query: LyricsCacheQuery, entries: tuple[LyricsCacheEntry, ...]) -> None:
        """Replace visible rows with the result for ``query``."""
        ...

    def set_current_status(self, status: LyricsDisplayStatus) -> None:
        """Show the active document independently of the stored cache entries."""
        ...

    def set_busy(self, busy: bool) -> None:
        """Enable or disable controls while a cache operation is running."""
        ...

    def show_error(self, message: str) -> None:
        """Show an operation failure in the manager's status area."""
        ...

    def show_delete_result(self, results: tuple[CacheDeleteResult, ...]) -> None:
        """Show which requested cache entries were actually deleted."""
        ...

    def show_clear_result(self) -> None:
        """Show that the complete cache was cleared successfully."""
        ...


class CacheManagementDialogFactory(Protocol):
    """Create one independently owned cache-management window."""

    def create(self, config: Config) -> CacheManagementDialogPort:
        """Create a manager styled for the current application configuration."""
        ...


class TranslationCacheDialogPort(Protocol):
    """Presentation boundary for the independently opened translation-cache manager."""

    @property
    def intent_requested(self) -> SignalPort: ...

    @property
    def finished(self) -> SignalPort: ...

    def retheme(self, config: Config) -> None: ...

    def show(self) -> None: ...

    def close(self) -> object: ...

    def raise_(self) -> object: ...

    def activateWindow(self) -> object: ...

    def set_entries(
        self,
        query: TranslationCacheQuery,
        entries: tuple[TranslationCacheEntry, ...],
    ) -> None: ...

    def set_busy(self, busy: bool) -> None: ...

    def show_error(self, message: str) -> None: ...

    def show_delete_result(self, results: tuple[TranslationCacheDeleteResult, ...]) -> None: ...

    def show_clear_result(self) -> None: ...

    def open_editor(self, record: TranslationCacheRecord) -> None: ...

    def show_save_result(self, updated: bool) -> None: ...


class TranslationCacheDialogFactory(Protocol):
    """Create one independently owned translation-cache management window."""

    def create(self, config: Config) -> TranslationCacheDialogPort: ...


class LyricsSearchDialogPort(Protocol):
    """Presentation boundary for the manually selectable lyric search window."""

    @property
    def intent_requested(self) -> SignalPort:
        """Return typed search intents emitted by the dialog."""
        ...

    @property
    def finished(self) -> SignalPort:
        """Return the signal emitted when the search window closes."""
        ...

    def retheme(self, config: Config) -> None:
        """Adopt a newly applied theme while the window stays open."""
        ...

    def show(self) -> None:
        """Show the editable lyric search window."""
        ...

    def close(self) -> object:
        """Close the search window."""
        ...

    def raise_(self) -> object:
        """Raise an already-open search window."""
        ...

    def activateWindow(self) -> object:
        """Request keyboard focus for the existing search window."""
        ...

    def set_results(self, query: LyricsSearchQuery, response: LyricsSearchResponse) -> None:
        """Replace visible candidates with the response for ``query``."""
        ...

    def set_busy(self, busy: bool) -> None:
        """Enable or disable controls while a search or cache write is running."""
        ...

    def show_error(self, message: str) -> None:
        """Show a failed search or cache-write message."""
        ...

    def show_apply_result(self, result: CacheWriteResult, displayed: bool) -> None:
        """Show the cache write outcome and whether it reached the active display."""
        ...

    def set_current_status(self, status: LyricsDisplayStatus) -> None:
        """Refresh the source facts for the lyric document currently on screen."""
        ...


class LyricsSearchDialogFactory(Protocol):
    """Create one manually selectable lyric-search window."""

    def create(
        self,
        config: Config,
        query: LyricsSearchQuery,
        status: LyricsDisplayStatus,
    ) -> LyricsSearchDialogPort:
        """Create a search window prefilled from the current track."""
        ...


__all__ = [
    "CacheManagementDialogFactory",
    "CacheManagementDialogPort",
    "LyricsSearchDialogFactory",
    "LyricsSearchDialogPort",
    "SettingsDialogFactory",
    "SettingsDialogPort",
    "SignalPort",
    "TranslationCacheDialogFactory",
    "TranslationCacheDialogPort",
]
