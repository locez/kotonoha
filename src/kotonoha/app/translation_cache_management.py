"""Application workflow for the standalone translation-cache management window."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

from ..config import Config
from ..translation import (
    TranslationCacheDeleteResult,
    TranslationCacheEntry,
    TranslationCacheError,
    TranslationCacheKey,
    TranslationCacheQuery,
    TranslationCacheRecord,
)
from .intents import (
    ClearTranslationCache,
    DeleteTranslationCacheEntries,
    LoadTranslationCacheRecord,
    SearchTranslationCache,
    UpdateTranslationCacheEntry,
)
from .lifecycle import TaskSupervisor
from .settings_port import TranslationCacheDialogFactory, TranslationCacheDialogPort

logger = logging.getLogger(__name__)


class TranslationCacheManagementPort(Protocol):
    """Cache operations required by the translation-cache manager."""

    async def search(
        self,
        query: TranslationCacheQuery,
        /,
    ) -> tuple[TranslationCacheEntry, ...]: ...

    async def get_record(
        self,
        key: TranslationCacheKey,
        /,
    ) -> TranslationCacheRecord | None: ...

    async def update_translations(
        self,
        key: TranslationCacheKey,
        translations: tuple[str, ...],
        /,
    ) -> bool: ...

    async def delete_many(
        self,
        keys: tuple[TranslationCacheKey, ...],
        /,
    ) -> tuple[TranslationCacheDeleteResult, ...]: ...

    async def clear(self) -> None: ...


class TranslationCacheManagementController:
    """Own translation-cache manager presentation state and cancellable async commands."""

    def __init__(
        self,
        cache: TranslationCacheManagementPort,
        factory: TranslationCacheDialogFactory,
        *,
        on_mutated: Callable[[], None] | None = None,
    ) -> None:
        self._cache = cache
        self._factory = factory
        self._on_mutated = on_mutated
        self._tasks = TaskSupervisor("translation-cache")
        self._dialog: TranslationCacheDialogPort | None = None
        self._search_task: asyncio.Task[None] | None = None
        self._delete_task: asyncio.Task[None] | None = None
        self._clear_task: asyncio.Task[None] | None = None
        self._edit_task: asyncio.Task[None] | None = None
        self._search_owner: TranslationCacheDialogPort | None = None
        self._delete_owner: TranslationCacheDialogPort | None = None
        self._clear_owner: TranslationCacheDialogPort | None = None
        self._edit_owner: TranslationCacheDialogPort | None = None
        self._query = TranslationCacheQuery()
        self._search_generation = 0
        self._closed = False

    def retheme(self, config: Config) -> None:
        """Pass a newly applied theme to the translation-cache window when open."""
        if self._dialog is not None:
            self._dialog.retheme(config)

    def open(self, config: Config) -> None:
        """Open or focus the single translation-cache window owned by this workflow."""
        if self._closed:
            return
        dialog = self._dialog
        if dialog is not None:
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = self._factory.create(config)
        dialog.intent_requested.connect(self._handle_intent)
        dialog.finished.connect(self._clear_dialog)
        self._dialog = dialog
        dialog.show()

    def search(self, query: TranslationCacheQuery) -> None:
        """Schedule one metadata query and discard stale responses."""
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
            name="kotonoha-search-translation-cache",
        )
        self._search_task = task
        self._search_owner = dialog
        task.add_done_callback(self._search_finished)

    def load_record(self, key: TranslationCacheKey) -> None:
        """Load one cached entry's lines and open the non-blocking editor."""
        dialog = self._dialog
        if dialog is None or self._operation_active(dialog):
            return
        dialog.set_busy(True)
        task = self._tasks.create(
            self._load_record_async(dialog, key),
            name="kotonoha-load-translation-record",
        )
        self._edit_task = task
        self._edit_owner = dialog
        task.add_done_callback(self._edit_finished)

    def update_entry(self, key: TranslationCacheKey, translations: tuple[str, ...]) -> None:
        """Persist edited translation lines and refresh the open list."""
        dialog = self._dialog
        if dialog is None or self._operation_active(dialog):
            return
        dialog.set_busy(True)
        task = self._tasks.create(
            self._update_entry_async(dialog, key, translations),
            name="kotonoha-update-translation-record",
        )
        self._edit_task = task
        self._edit_owner = dialog
        task.add_done_callback(self._edit_finished)

    def delete(self, keys: tuple[TranslationCacheKey, ...]) -> None:
        """Schedule deletion of selected translation cache entries."""
        dialog = self._dialog
        if dialog is None or not keys or self._operation_active(dialog):
            return
        if self._search_task is not None and not self._search_task.done():
            self._search_task.cancel()
        dialog.set_busy(True)
        task = self._tasks.create(
            self._delete_async(dialog, keys),
            name="kotonoha-delete-translation-cache",
        )
        self._delete_task = task
        self._delete_owner = dialog
        task.add_done_callback(self._delete_finished)

    def clear(self) -> None:
        """Schedule a full translation-cache clear from Settings or the manager."""
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
            name="kotonoha-clear-translation-cache",
        )
        self._clear_task = task
        self._clear_owner = dialog
        task.add_done_callback(self._clear_finished)

    async def stop(self) -> None:
        """Close the manager, cancel pending tasks, and close its supervisor."""
        if self._closed:
            return
        dialog = self._dialog
        if dialog is not None:
            try:
                dialog.close()
            except (OSError, RuntimeError) as exc:
                logger.warning("Could not close translation cache manager: %s", exc)
            finally:
                self._dialog = None
        for task in (self._clear_task, self._search_task, self._delete_task, self._edit_task):
            if task is not None and not task.done():
                task.cancel()
        await self._tasks.wait()
        self._clear_task = None
        self._search_task = None
        self._delete_task = None
        self._edit_task = None
        self._clear_owner = None
        self._search_owner = None
        self._delete_owner = None
        self._edit_owner = None
        self._tasks.close()
        self._closed = True

    def _operation_active(self, dialog: TranslationCacheDialogPort) -> bool:
        return any(
            task is not None and not task.done() and owner is dialog
            for task, owner in (
                (self._clear_task, self._clear_owner),
                (self._delete_task, self._delete_owner),
                (self._edit_task, self._edit_owner),
            )
        )

    def _handle_intent(self, intent: object) -> None:
        if isinstance(intent, SearchTranslationCache):
            self.search(intent.query)
        elif isinstance(intent, LoadTranslationCacheRecord):
            self.load_record(intent.key)
        elif isinstance(intent, UpdateTranslationCacheEntry):
            self.update_entry(intent.key, intent.translations)
        elif isinstance(intent, DeleteTranslationCacheEntries):
            self.delete(intent.keys)
        elif isinstance(intent, ClearTranslationCache):
            self.clear()

    def _clear_dialog(self, _result: int | None = None) -> None:
        dialog = self._dialog
        self._dialog = None
        if dialog is None:
            return
        for task, owner in (
            (self._search_task, self._search_owner),
            (self._delete_task, self._delete_owner),
            (self._clear_task, self._clear_owner),
            (self._edit_task, self._edit_owner),
        ):
            if task is not None and not task.done() and owner is dialog:
                task.cancel()

    async def _search_async(
        self,
        dialog: TranslationCacheDialogPort,
        query: TranslationCacheQuery,
        generation: int,
    ) -> None:
        entries = await self._cache.search(query)
        if self._dialog is dialog and generation == self._search_generation:
            dialog.set_entries(query, entries)
            dialog.set_busy(False)

    async def _load_record_async(
        self,
        dialog: TranslationCacheDialogPort,
        key: TranslationCacheKey,
    ) -> None:
        record = await self._cache.get_record(key)
        if self._dialog is not dialog:
            return
        dialog.set_busy(False)
        if record is None:
            dialog.show_save_result(False)
            return
        dialog.open_editor(record)

    async def _update_entry_async(
        self,
        dialog: TranslationCacheDialogPort,
        key: TranslationCacheKey,
        translations: tuple[str, ...],
    ) -> None:
        updated = await self._cache.update_translations(key, translations)
        if updated and self._on_mutated is not None:
            self._on_mutated()
        if self._dialog is not dialog:
            return
        query = self._query
        try:
            entries = await self._cache.search(query)
        except (TranslationCacheError, RuntimeError, TimeoutError) as exc:
            dialog.show_save_result(updated)
            dialog.set_busy(False)
            dialog.show_error(f"Refresh failed: {exc}")
            return
        dialog.set_entries(query, entries)
        dialog.show_save_result(updated)
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
        except (TranslationCacheError, RuntimeError, TimeoutError) as exc:
            if current and self._dialog is not None:
                self._dialog.set_busy(False)
                self._dialog.show_error(f"Search failed: {exc}")

    def _edit_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        current = self._edit_task is task
        if current:
            self._edit_task = None
            self._edit_owner = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except (TranslationCacheError, RuntimeError, TimeoutError, ValueError) as exc:
            if current and self._dialog is not None:
                self._dialog.set_busy(False)
                self._dialog.show_error(f"Edit failed: {exc}")

    async def _delete_async(
        self,
        dialog: TranslationCacheDialogPort,
        keys: tuple[TranslationCacheKey, ...],
    ) -> None:
        results = await self._cache.delete_many(keys)
        if self._on_mutated is not None:
            self._on_mutated()
        if self._dialog is not dialog:
            return
        query = self._query
        try:
            entries = await self._cache.search(query)
        except (TranslationCacheError, RuntimeError, TimeoutError) as exc:
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
        except (TranslationCacheError, RuntimeError, TimeoutError) as exc:
            if current and self._dialog is not None:
                self._dialog.set_busy(False)
                self._dialog.show_error(f"Delete failed: {exc}")

    async def _clear_async(self, dialog: TranslationCacheDialogPort | None) -> None:
        await self._cache.clear()
        if self._on_mutated is not None:
            self._on_mutated()
        if dialog is None or self._dialog is not dialog:
            return
        query = self._query
        try:
            entries = await self._cache.search(query)
        except (TranslationCacheError, RuntimeError, TimeoutError) as exc:
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
        except (TranslationCacheError, RuntimeError, TimeoutError) as exc:
            if current and self._dialog is not None:
                self._dialog.set_busy(False)
                self._dialog.show_error(f"Clear failed: {exc}")


__all__ = ["TranslationCacheManagementController", "TranslationCacheManagementPort"]
