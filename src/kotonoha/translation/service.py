"""Async lyrics translation service with cache, deduplication, and backoff."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TypeAlias

from ..async_task import create_owned_task, wait_for_owned
from ..config.models import TranslationPolicy, TranslationProvider
from ..lyrics.http import LyricsSession
from ..lyrics.models import LyricsDocument
from ..lyrics.translation import TranslationMerger
from ..secrets import SecretStore, SecretStoreError, translation_secret_key
from .cache import TranslationCacheError, TranslationCachePort
from .deepl import DeepLTranslator
from .models import (
    TranslationConfig,
    TranslationError,
    TranslationErrorKind,
    TranslationRequest,
    TranslationResult,
    TranslatorPort,
    content_hash,
    deduplicate_lines,
    detect_primary_language,
    existing_translation_matches_target,
    looks_like_target_language,
    reconstruct_lines,
)
from .openai_compatible import OpenAICompatibleTranslator

logger = logging.getLogger(__name__)

DEFAULT_NEGATIVE_TTL_S = 60.0
TranslatorFactory: TypeAlias = Callable[[LyricsSession, TranslationConfig], TranslatorPort]
_InflightKey: TypeAlias = tuple[str, str, TranslationProvider, str, str]


def default_translator_factory(session: LyricsSession, config: TranslationConfig) -> TranslatorPort:
    """Create the concrete HTTP translator for one configured provider."""
    if config.provider is TranslationProvider.DEEPL:
        return DeepLTranslator(session)
    return OpenAICompatibleTranslator(
        session,
        base_url=config.base_url,
        model=config.model,
        style_prompt=config.prompt,
    )


class LyricsTranslationService:
    """Coordinate cache lookup, line deduplication, secret retrieval, and API calls."""

    def __init__(
        self,
        *,
        config: TranslationConfig,
        cache: TranslationCachePort,
        secrets: SecretStore,
        session_factory: Callable[[], LyricsSession],
        translator_factory: TranslatorFactory = default_translator_factory,
        negative_ttl_s: float = DEFAULT_NEGATIVE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._cache = cache
        self._secrets = secrets
        self._session_factory = session_factory
        self._translator_factory = translator_factory
        self._negative_ttl_s = max(0.0, negative_ttl_s)
        self._clock = clock
        self._merger = TranslationMerger()
        self._session: LyricsSession | None = None
        self._inflight: dict[_InflightKey, asyncio.Task[TranslationResult | None]] = {}
        self._negative_until: dict[_InflightKey, float] = {}

    @property
    def config(self) -> TranslationConfig:
        """Return the immutable translation configuration currently active."""
        return self._config

    async def start(self) -> None:
        """Open the shared HTTP session and reopen worker boundaries."""
        self._cache.start()
        self._secrets.start()
        if self._session is None:
            self._session = self._session_factory()

    async def stop(self) -> None:
        """Cancel in-flight translations and release the owned HTTP session."""
        cancellation_requested = await self._cancel_inflight()
        session = self._session
        self._session = None
        if session is not None:
            await session.close()
        if cancellation_requested:
            raise asyncio.CancelledError

    def configure(self, config: TranslationConfig) -> None:
        """Replace translation settings and clear transient failure backoff."""
        self._config = config
        self._negative_until.clear()

    def clear_backoff(self) -> None:
        """Reset negative cache entries (for example after an API key update)."""
        self._negative_until.clear()

    def should_translate(self, document: LyricsDocument) -> bool:
        """Decide whether ``document`` qualifies for API translation under active policy."""
        config = self._config
        if config.policy is TranslationPolicy.OFF:
            return False
        if not document.lines:
            return False
        if config.policy is TranslationPolicy.MISSING_ONLY:
            existing_translations = tuple(
                line.translation.strip() for line in document.lines if line.translation.strip()
            )
            if existing_translations and existing_translation_matches_target(
                existing_translations,
                config.target_language,
            ):
                logger.debug(
                    "Skipping lyrics translation: track=%r already has %s translation",
                    document.title,
                    config.target_language,
                )
                return False
        texts = tuple(line.text for line in document.lines)
        if not any(text.strip() for text in texts):
            return False
        if looks_like_target_language(texts, config.target_language, document_language=document.language):
            logger.debug(
                "Skipping lyrics translation: track=%r detected=%s matches target=%s",
                document.title,
                detect_primary_language(texts),
                config.target_language,
            )
            return False
        return True

    async def translate_document(self, document: LyricsDocument) -> LyricsDocument | None:
        """Return an enriched copy of ``document``, or ``None`` when skipped/failed."""
        config = self._config
        if not self.should_translate(document):
            return None

        texts = tuple(line.text for line in document.lines)
        timestamps = tuple(line.start for line in document.lines)
        digest = content_hash(texts)
        target_language = config.target_language
        if config.cache_enabled:
            try:
                cached = await self._cache.lookup(
                    digest,
                    target_language,
                    expected_line_count=len(texts),
                    source_lines=texts,
                    timestamps=timestamps,
                )
            except TranslationCacheError as exc:
                logger.warning("Translation cache lookup failed: %s", exc)
            else:
                if cached is not None:
                    return self._merger.merge_by_index(document, cached.translations)

        key: _InflightKey = (
            digest,
            target_language,
            config.provider,
            config.base_url,
            config.model,
        )
        if self._negative_until.get(key, 0.0) > self._clock():
            return None

        task = self._inflight.get(key)
        if task is None:
            task = create_owned_task(
                self._translate_uncached(document, texts, digest, config, key),
                name="kotonoha-lyrics-translate",
            )
            self._inflight[key] = task
        try:
            result = await asyncio.shield(task)
        finally:
            if task.done() and self._inflight.get(key) is task:
                self._inflight.pop(key, None)

        if result is None:
            return None
        return self._merger.merge_by_index(document, result.translations)

    async def clear_cache(self) -> None:
        """Clear persisted translations and reset in-memory backoff."""
        self._negative_until.clear()
        await self._cache.clear()

    async def _translate_uncached(
        self,
        document: LyricsDocument,
        texts: tuple[str, ...],
        digest: str,
        config: TranslationConfig,
        key: _InflightKey,
    ) -> TranslationResult | None:
        session = self._session
        if session is None:
            logger.debug("Skipping lyrics translation because the translation service is stopped")
            return None

        unique_lines, mapping = deduplicate_lines(texts)
        if not unique_lines:
            return None

        secret_key = translation_secret_key(config.provider.value)
        try:
            api_key = (await self._secrets.get_secret(secret_key)) or ""
        except SecretStoreError as exc:
            logger.warning("Could not read translation API key: %s", exc)
            self._negative_until[key] = self._clock() + self._negative_ttl_s
            return None

        translator = self._translator_factory(session, config)
        request = TranslationRequest(
            lines=unique_lines,
            target_language=config.target_language,
            title=document.title or "",
            artist=document.artist or "",
        )
        try:
            raw_result = await translator.translate(request, api_key=api_key)
        except TranslationError as exc:
            logger.warning(
                "Lyrics translation failed (%s/%s): %s",
                config.provider.value,
                exc.kind.value,
                exc,
            )
            if exc.retryable or exc.kind in {
                TranslationErrorKind.AUTH,
                TranslationErrorKind.CONFIG,
                TranslationErrorKind.UNSUPPORTED_LANGUAGE,
            }:
                self._negative_until[key] = self._clock() + self._negative_ttl_s
            return None

        try:
            aligned = reconstruct_lines(raw_result.translations, mapping)
        except ValueError as exc:
            logger.warning("Lyrics translation alignment failed: %s", exc)
            return None

        result = TranslationResult(
            translations=aligned,
            provider=raw_result.provider,
            model=raw_result.model,
            from_cache=False,
        )
        if config.cache_enabled:
            try:
                await self._cache.store(
                    digest,
                    config.target_language,
                    result,
                    source_lines=texts,
                    timestamps=tuple(line.start for line in document.lines),
                    title=document.title or "",
                    artist=document.artist or "",
                )
            except TranslationCacheError as exc:
                logger.warning("Translation cache write failed: %s", exc)
        return result

    async def _cancel_inflight(self) -> bool:
        tasks = tuple(self._inflight.values())
        self._inflight.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if not tasks:
            return False
        joined = asyncio.gather(*tasks, return_exceptions=True)
        return await wait_for_owned(joined)


__all__ = [
    "DEFAULT_NEGATIVE_TTL_S",
    "LyricsTranslationService",
    "TranslatorFactory",
    "default_translator_factory",
]
