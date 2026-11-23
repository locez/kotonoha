"""Application coordinator linking displayed lyric documents with async API translation."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

from ..config import Config
from ..i18n import resolve_lyrics_translation_language
from ..lyrics.models import LyricsDocument
from ..secrets import SecretStore, SecretStoreError, translation_secret_key
from ..translation import (
    LyricsTranslationService,
    TranslationCacheError,
    TranslationConfig,
)
from .lifecycle import TaskSupervisor

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TranslationSecretSnapshot:
    """Non-secret keyring availability and saved-key status shown in Settings."""

    available: bool = True
    reason: str | None = None
    saved_services: frozenset[str] = frozenset()

    def has_key(self, service_id: str) -> bool:
        """Return whether a key is currently saved for ``service_id``."""
        return service_id in self.saved_services


class TranslationDocumentTarget(Protocol):
    """Display boundary updated asynchronously when a translation finishes."""

    def current_source_document(self) -> LyricsDocument | None:
        """Return the untranslated active lyric document, if any."""
        ...

    def apply_translated_document(
        self,
        source: LyricsDocument,
        translated: LyricsDocument,
    ) -> bool:
        """Replace the active display document when ``source`` is still current."""
        ...

    def reset_translated_document(self) -> None:
        """Drop any active translated overlay and restore the source document."""
        ...


def translation_config_from_app(config: Config) -> TranslationConfig:
    """Project validated application config into immutable translation settings."""
    return TranslationConfig(
        policy=config.translation_policy,
        target_language=resolve_lyrics_translation_language(config.translation_language),
        services=tuple(config.translation_services),
        prompt=config.translation_prompt,
        cache_enabled=config.cache_enabled,
    )


class LyricsTranslationCoordinator:
    """Own active translation tasks, secret commands, and display re-publication."""

    def __init__(
        self,
        *,
        service: LyricsTranslationService,
        secrets: SecretStore,
        target: TranslationDocumentTarget,
    ) -> None:
        self._service = service
        self._secrets = secrets
        self._target = target
        self._tasks = TaskSupervisor("lyrics-translation")
        self._active_task: asyncio.Task[None] | None = None
        self._generation = 0
        self._started = False
        self._closed = False

    async def start(self) -> None:
        """Start the underlying translation service and secret worker."""
        if self._started:
            return
        self._closed = False
        await self._service.start()
        self._started = True
        current = self._target.current_source_document()
        if current is not None:
            self.on_source_document(current)

    async def stop(self) -> None:
        """Cancel active translation work and release service/secret resources."""
        if self._closed:
            return
        self._closed = True
        self._started = False
        self._cancel_active()
        await self._tasks.wait()
        self._tasks.close()
        try:
            await self._service.stop()
        finally:
            self._secrets.close()

    def apply_config(self, config: Config) -> None:
        """Update translation policy/services and re-evaluate the active track."""
        updated = translation_config_from_app(config)
        if updated == self._service.config:
            return
        self._service.configure(updated)
        self._cancel_active()
        self._target.reset_translated_document()
        if self._started:
            self.on_source_document(self._target.current_source_document())

    def on_source_document(self, document: LyricsDocument | None) -> None:
        """Schedule background translation whenever a new source document arrives."""
        self._cancel_active()
        if self._closed or not self._started or document is None:
            return
        if not self._service.should_translate(document):
            return
        self._generation += 1
        generation = self._generation
        task = self._tasks.create(
            self._translate_async(generation, document),
            name=f"kotonoha-translate-doc-{generation}",
        )
        self._active_task = task
        task.add_done_callback(self._translation_finished)

    async def secret_snapshot(self) -> TranslationSecretSnapshot:
        """Probe keyring status and which configured services currently have saved keys."""
        availability = await self._secrets.availability()
        saved: set[str] = set()
        for service in self._service.config.services:
            try:
                value = await self._secrets.get_secret(translation_secret_key(service.id))
            except SecretStoreError as exc:
                logger.debug("Could not inspect saved key for %s: %s", service.id, exc)
                continue
            if value:
                saved.add(service.id)
        return TranslationSecretSnapshot(
            available=availability.available,
            reason=availability.reason,
            saved_services=frozenset(saved),
        )

    def save_api_key(self, service_id: str, api_key: str) -> None:
        """Persist one service API key asynchronously and retry active lyrics."""
        if self._closed:
            return
        task = self._tasks.create(
            self._save_api_key_async(service_id, api_key),
            name=f"kotonoha-save-secret-{service_id}",
        )
        task.add_done_callback(self._command_finished)

    def delete_api_key(self, service_id: str) -> None:
        """Delete one service API key asynchronously from the system keyring."""
        if self._closed:
            return
        task = self._tasks.create(
            self._delete_api_key_async(service_id),
            name=f"kotonoha-delete-secret-{service_id}",
        )
        task.add_done_callback(self._command_finished)

    def clear_cache(self) -> None:
        """Clear persisted translation rows asynchronously."""
        if self._closed:
            return
        task = self._tasks.create(
            self._clear_cache_async(),
            name="kotonoha-clear-translation-cache",
        )
        task.add_done_callback(self._command_finished)

    def refresh_active_document(self) -> None:
        """Re-apply translations for the active track after a manual cache edit."""
        self._service.clear_backoff()
        if not self._started:
            return
        self._cancel_active()
        self._target.reset_translated_document()
        self.on_source_document(self._target.current_source_document())

    def _cancel_active(self) -> None:
        self._generation += 1
        task = self._active_task
        self._active_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _translate_async(self, generation: int, document: LyricsDocument) -> None:
        translated = await self._service.translate_document(document)
        if translated is None or generation != self._generation:
            return
        self._target.apply_translated_document(document, translated)

    async def _save_api_key_async(self, service_id: str, api_key: str) -> None:
        await self._secrets.set_secret(translation_secret_key(service_id), api_key)
        self._service.clear_backoff(service_id)
        if self._started and any(
            service.enabled and service.id == service_id for service in self._service.config.services
        ):
            self.on_source_document(self._target.current_source_document())

    async def _delete_api_key_async(self, service_id: str) -> None:
        await self._secrets.delete_secret(translation_secret_key(service_id))
        self._service.clear_backoff(service_id)

    async def _clear_cache_async(self) -> None:
        await self._service.clear_cache()

    def _translation_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if self._active_task is task:
            self._active_task = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except (OSError, RuntimeError, TimeoutError, TranslationCacheError) as exc:
            logger.warning("Lyrics translation task failed: %s", exc)

    def _command_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except (SecretStoreError, TranslationCacheError, ValueError, RuntimeError, TimeoutError) as exc:
            logger.warning("Translation command failed: %s", exc)


__all__ = [
    "LyricsTranslationCoordinator",
    "TranslationDocumentTarget",
    "TranslationSecretSnapshot",
    "translation_config_from_app",
]
