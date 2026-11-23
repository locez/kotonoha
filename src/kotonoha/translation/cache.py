"""Async facade over content-addressed SQLite lyric translation storage."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from ..async_worker import BlockingWorkerPort
from ..lyrics.cache.storage import PayloadParser, cache_path
from .cache_storage import (
    DEFAULT_MAX_TRANSLATION_ENTRIES,
    TRANSLATION_PROMPT_VERSION,
    TranslationCacheStorage,
)
from .models import (
    TranslationCacheDeleteResult,
    TranslationCacheEntry,
    TranslationCacheKey,
    TranslationCacheQuery,
    TranslationCacheRecord,
    TranslationResult,
)


class TranslationCacheError(RuntimeError):
    """A persistent translation-cache operation failed."""


class TranslationCachePort(Protocol):
    """Async translation-cache operations used by the translation service."""

    def start(self) -> None: ...

    def close(self) -> None: ...

    async def lookup(
        self,
        content_hash: str,
        target_language: str,
        *,
        expected_line_count: int,
        source_lines: Sequence[str] = (),
        timestamps: Sequence[float] = (),
    ) -> TranslationResult | None: ...

    async def store(
        self,
        content_hash: str,
        target_language: str,
        result: TranslationResult,
        *,
        source_lines: Sequence[str] = (),
        timestamps: Sequence[float] = (),
        title: str = "",
        artist: str = "",
    ) -> None: ...

    async def search(self, query: TranslationCacheQuery, /) -> tuple[TranslationCacheEntry, ...]: ...

    async def get_record(self, key: TranslationCacheKey, /) -> TranslationCacheRecord | None: ...

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

    async def count(self) -> int: ...


class TranslationCache:
    """Async facade running SQLite translation-cache operations on an owned worker."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_entries: int = DEFAULT_MAX_TRANSLATION_ENTRIES,
        worker: BlockingWorkerPort,
        lyrics_parsers: Mapping[str, PayloadParser] | None = None,
    ) -> None:
        self._worker = worker
        self._storage = TranslationCacheStorage(
            path or cache_path(),
            max_entries=max_entries,
            lyrics_parsers=lyrics_parsers,
        )

    def start(self) -> None:
        self._worker.reopen()

    def close(self) -> None:
        self._worker.close()

    async def lookup(
        self,
        content_hash: str,
        target_language: str,
        *,
        expected_line_count: int,
        source_lines: Sequence[str] = (),
        timestamps: Sequence[float] = (),
    ) -> TranslationResult | None:
        try:
            return await self._worker.run(
                self._storage.lookup,
                content_hash,
                target_language,
                expected_line_count,
                source_lines,
                timestamps,
            )
        except (OSError, sqlite3.Error, TimeoutError) as exc:
            raise TranslationCacheError("Translation cache lookup failed") from exc

    async def store(
        self,
        content_hash: str,
        target_language: str,
        result: TranslationResult,
        *,
        source_lines: Sequence[str] = (),
        timestamps: Sequence[float] = (),
        title: str = "",
        artist: str = "",
    ) -> None:
        try:
            await self._worker.run(
                self._storage.store,
                content_hash,
                target_language,
                result.translations,
                provider=result.provider,
                model=result.model,
                source_lines=source_lines,
                timestamps=timestamps,
                title=title,
                artist=artist,
            )
        except (OSError, sqlite3.Error, TimeoutError) as exc:
            raise TranslationCacheError("Translation cache write failed") from exc

    async def search(self, query: TranslationCacheQuery) -> tuple[TranslationCacheEntry, ...]:
        try:
            return await self._worker.run(self._storage.search, query)
        except (OSError, sqlite3.Error, TypeError, ValueError, TimeoutError) as exc:
            raise TranslationCacheError("Translation cache search failed") from exc

    async def get_record(self, key: TranslationCacheKey) -> TranslationCacheRecord | None:
        try:
            return await self._worker.run(self._storage.get_record, key)
        except (OSError, sqlite3.Error, TypeError, ValueError, TimeoutError) as exc:
            raise TranslationCacheError("Translation cache read failed") from exc

    async def update_translations(
        self,
        key: TranslationCacheKey,
        translations: tuple[str, ...],
    ) -> bool:
        try:
            return await self._worker.run(self._storage.update_translations, key, translations)
        except (OSError, sqlite3.Error, ValueError, TimeoutError) as exc:
            raise TranslationCacheError("Translation cache update failed") from exc

    async def delete_many(
        self,
        keys: tuple[TranslationCacheKey, ...],
    ) -> tuple[TranslationCacheDeleteResult, ...]:
        try:
            return await self._worker.run(self._storage.delete_many, keys)
        except (OSError, sqlite3.Error, TimeoutError) as exc:
            raise TranslationCacheError("Translation cache delete failed") from exc

    async def clear(self) -> None:
        try:
            await self._worker.run(self._storage.clear)
        except (OSError, sqlite3.Error, TimeoutError) as exc:
            raise TranslationCacheError("Translation cache clear failed") from exc

    async def count(self) -> int:
        try:
            return await self._worker.run(self._storage.count)
        except (OSError, sqlite3.Error, TimeoutError) as exc:
            raise TranslationCacheError("Translation cache count failed") from exc


__all__ = [
    "DEFAULT_MAX_TRANSLATION_ENTRIES",
    "TRANSLATION_PROMPT_VERSION",
    "TranslationCache",
    "TranslationCacheError",
    "TranslationCachePort",
    "TranslationCacheStorage",
]
