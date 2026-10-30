"""Application workflow for the independently opened lyric-cache manager."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

from ..config import Config
from ..display.models import LyricsDisplayStatus
from ..lyrics.cache import (
    CacheDeleteResult,
    LyricsCacheEntry,
    LyricsCacheError,
    LyricsCacheKey,
    LyricsCacheQuery,
)
from .intents import ClearCache, DeleteCacheEntries, SearchCache
from .lifecycle import TaskSupervisor
from .settings_port import CacheManagementDialogFactory, CacheManagementDialogPort

logger = logging.getLogger(__name__)


class LyricsCacheManagementPort(Protocol):
    """Cache operations required by the manager, without owning cache lifecycle."""

    async def search(self, query: LyricsCacheQuery, /) -> tuple[LyricsCacheEntry, ...]:
        """Search persisted lyric metadata."""
        ...

    async def delete_many(
        self, keys: tuple[LyricsCacheKey, ...], /
    ) -> tuple[CacheDeleteResult, ...]:
        """Delete exact cache entries and report each actual outcome."""
        ...

    async def clear(self) -> None:
        """Clear all persisted lyric cache entries."""
        ...


class CacheManagementController:
    """Own cache-manager presentation state and its cancellable async commands."""

    def __init__(
        self, cache: LyricsCacheManagementPort, factory: CacheManagementDialogFactory,
        *, status_provider: Callable[[], LyricsDisplayStatus],
    ) -> None:
        """Create a cache workflow from explicit cache and presentation ports."""
        self._cache = cache
        self._factory = factory
        self._status_provider: Callable[[], LyricsDisplayStatus] = status_provider
        # Active display facts are independent of the persisted candidate list.
        self._current_status: LyricsDisplayStatus | None = None
        self._tasks = TaskSupervisor("lyrics-cache")
        self._dialog: CacheManagementDialogPort | None = None
        self._search_task: asyncio.Task[None] | None = None
        self._delete_task: asyncio.Task[None] | None = None
        self._clear_task: asyncio.Task[None] | None = None
        self._search_owner: CacheManagementDialogPort | None = None
        self._delete_owner: CacheManagementDialogPort | None = None
        self._clear_owner: CacheManagementDialogPort | None = None
        self._query = LyricsCacheQuery()
        self._search_generation = 0
        self._closed = False

    def retheme(self, config: Config) -> None:
        """Pass a newly applied theme to the cache window, when one is open."""
        if self._dialog is not None:
            self._dialog.retheme(config)

    def open(self, config: Config) -> None:
        """Open or focus the one cache manager window owned by this workflow."""
        if self._closed:
            return
        dialog = self._dialog
        if dialog is not None:
            self.refresh_current_status()
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = self._factory.create(config)
        dialog.intent_requested.connect(self._handle_intent)
        dialog.finished.connect(self._clear_dialog)
        self._dialog = dialog
        self._current_status = None
        self.refresh_current_status()
        dialog.show()

    def refresh_current_status(self) -> None:
        """Update an open manager when the displayed lyric source changes."""
        dialog = self._dialog
        if dialog is None or self._closed:
            return
        status = self._status_provider()
        if status != self._current_status:
            self._current_status = status
            dialog.set_current_status(status)

    def search(self, query: LyricsCacheQuery) -> None:
        """Schedule one fuzzy metadata query and discard stale results."""
        dialog = self._dialog
        if dialog is None or self._operation_active(dialog):
            return
        previous = self._search_task
        if previous is not None and not previous.done():
            previous.cancel()
        self._query = query
        self._search_generation += 1
        generation = self._search_generation
        dialog.set_busy(True)
        task = self._tasks.create(
            self._search_async(dialog, query, generation),
            name="kotonoha-search-lyrics-cache",
        )
        self._search_task = task
        self._search_owner = dialog
        task.add_done_callback(self._search_finished)

    def delete(self, keys: tuple[LyricsCacheKey, ...]) -> None:
        """Schedule deletion of exact rows selected in the manager."""
        dialog = self._dialog
        if dialog is None or not keys or self._operation_active(dialog):
            return
        if self._search_task is not None and not self._search_task.done():
            self._search_task.cancel()
        dialog.set_busy(True)
        task = self._tasks.create(
            self._delete_async(dialog, keys),
            name="kotonoha-delete-lyrics-cache",
        )
        self._delete_task = task
        self._delete_owner = dialog
        task.add_done_callback(self._delete_finished)

    def clear(self) -> None:
        """Schedule a full cache clear requested by Settings or the manager."""
        dialog = self._dialog
        if dialog is not None and self._operation_active(dialog):
            return
        if dialog is None and any(
            task is not None and not task.done() and owner is None
            for task, owner in (
                (self._clear_task, self._clear_owner),
                (self._delete_task, self._delete_owner),
            )
        ):
            return
        if self._search_task is not None and not self._search_task.done():
            self._search_task.cancel()
        if dialog is not None:
            dialog.set_busy(True)
        task = self._tasks.create(
            self._clear_async(dialog),
            name="kotonoha-clear-lyrics-cache",
        )
        self._clear_task = task
        self._clear_owner = dialog
        task.add_done_callback(self._clear_finished)

    async def stop(self) -> None:
        """Close the manager, cancel its commands, and close its task owner."""
        if self._closed:
            return
        dialog = self._dialog
        if dialog is not None:
            try:
                dialog.close()
            except (OSError, RuntimeError) as exc:
                logger.warning("Could not close lyrics cache manager: %s", exc)
            finally:
                self._dialog = None
        for task in (self._clear_task, self._search_task, self._delete_task):
            if task is not None and not task.done():
                task.cancel()
        await self._tasks.wait()
        self._clear_task = None
        self._search_task = None
        self._delete_task = None
        self._clear_owner = None
        self._search_owner = None
        self._delete_owner = None
        self._tasks.close()
        self._closed = True

    def _operation_active(self, dialog: CacheManagementDialogPort) -> bool:
        """Return whether a mutating cache command currently owns the manager."""
        return any(
            task is not None and not task.done() and owner is dialog
            for task, owner in (
                (self._clear_task, self._clear_owner),
                (self._delete_task, self._delete_owner),
            )
        )

    def _handle_intent(self, intent: object) -> None:
        """Route manager-emitted commands back to this workflow owner."""
        if isinstance(intent, SearchCache):
            self.search(intent.query)
        elif isinstance(intent, DeleteCacheEntries):
            self.delete(intent.keys)
        elif isinstance(intent, ClearCache):
            self.clear()

    def _clear_dialog(self, _result: int | None = None) -> None:
        """End the dialog session and cancel work that can no longer update it."""
        dialog = self._dialog
        self._dialog = None
        if dialog is None:
            return
        for task, owner in (
            (self._search_task, self._search_owner),
            (self._delete_task, self._delete_owner),
            (self._clear_task, self._clear_owner),
        ):
            if task is not None and not task.done() and owner is dialog:
                task.cancel()

    async def _search_async(
        self,
        dialog: CacheManagementDialogPort,
        query: LyricsCacheQuery,
        generation: int,
    ) -> None:
        """Load one query and publish it only while it remains current."""
        entries = await self._cache.search(query)
        if self._dialog is dialog and generation == self._search_generation:
            self.refresh_current_status()
            dialog.set_entries(query, entries)
            dialog.set_busy(False)

    def _search_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        current = self._search_task is task
        if current:
            self._search_task = None
            self._search_owner = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except (LyricsCacheError, RuntimeError, TimeoutError) as exc:
            if current and self._dialog is not None:
                self._dialog.set_busy(False)
                self._dialog.show_error(f"Search failed: {exc}")

    async def _delete_async(self, dialog: CacheManagementDialogPort, keys: tuple[LyricsCacheKey, ...]) -> None:
        """Delete selected rows, refresh the current query, and report the result."""
        results = await self._cache.delete_many(keys)
        if self._dialog is not dialog:
            return
        query = self._query
        try:
            entries = await self._cache.search(query)
        except (LyricsCacheError, RuntimeError, TimeoutError) as exc:
            dialog.show_delete_result(results)
            dialog.set_busy(False)
            dialog.show_error(f"Refresh failed: {exc}")
            return
        dialog.set_entries(query, entries)
        dialog.show_delete_result(results)
        dialog.set_busy(False)

    def _delete_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        current = self._delete_task is task
        if current:
            self._delete_task = None
            self._delete_owner = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except (LyricsCacheError, RuntimeError, TimeoutError) as exc:
            if current and self._dialog is not None:
                self._dialog.set_busy(False)
                self._dialog.show_error(f"Delete failed: {exc}")

    async def _clear_async(self, dialog: CacheManagementDialogPort | None) -> None:
        """Clear the cache and refresh the manager if one is still open."""
        await self._cache.clear()
        if dialog is None or self._dialog is not dialog:
            return
        query = self._query
        try:
            entries = await self._cache.search(query)
        except (LyricsCacheError, RuntimeError, TimeoutError) as exc:
            dialog.set_busy(False)
            dialog.show_error(f"Refresh failed: {exc}")
            return
        dialog.set_entries(query, entries)
        dialog.show_clear_result()
        dialog.set_busy(False)

    def _clear_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        current = self._clear_task is task
        if current:
            self._clear_task = None
            self._clear_owner = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except (LyricsCacheError, RuntimeError, TimeoutError) as exc:
            if current and self._dialog is not None:
                self._dialog.set_busy(False)
                self._dialog.show_error(f"Clear failed: {exc}")


__all__ = ["CacheManagementController", "LyricsCacheManagementPort"]
