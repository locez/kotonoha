"""Coordinate typed lyric sources in the configured order."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, TypeAlias

from ..async_task import create_owned_task, wait_for_owned
from .artifact import LyricsArtifact
from .artist_grammar import artist_tokens
from .cache import (
    CacheWriteResult,
    LyricsCacheError,
    LyricsCacheHit,
    LyricsCacheMode,
)
from .catalog import LyricsSourceCatalog
from .hint import LyricsHint
from .http import LyricsSession
from .match import MatchConfidence, TrackMetadata
from .models import LyricLine, LyricsCacheState, LyricsOrigin
from .sources import (
    LyricsSource,
    LyricsSourceError,
    LyricsSourceResult,
)
from .title_grammar import normalize, split_title
from .workflow import ResolverLookup

logger = logging.getLogger(__name__)

ResolutionCacheKey: TypeAlias = tuple[str, tuple[str, ...], tuple[str, ...], str, float | None]
RequestKey: TypeAlias = tuple[TrackMetadata, tuple[str, ...], bool, bool, bool]

_CONF_RANK = {MatchConfidence.NONE: 0, MatchConfidence.MEDIUM: 1, MatchConfidence.HIGH: 2}


class ResolverCachePort(Protocol):
    """Cache capability used by resolution, separate from cache management."""

    def start(self) -> None: ...

    async def lookup(
        self,
        provider: str,
        track: TrackMetadata,
        parser: Callable[[Mapping[str, str]], tuple[LyricLine, ...]],
        /,
    ) -> LyricsCacheHit | None: ...

    async def lookup_manual(
        self,
        track: TrackMetadata,
        parsers: Mapping[str, Callable[[Mapping[str, str]], tuple[LyricLine, ...]]],
        /,
    ) -> LyricsCacheHit | None: ...

    async def store(self, artifact: LyricsArtifact, /) -> CacheWriteResult | None: ...

    def close(self) -> None: ...


def _resolution_cache_key(track: TrackMetadata) -> ResolutionCacheKey:
    base, tags = split_title(track.title)
    duration = round(track.duration_s, 1) if track.duration_s is not None else None
    return (
        normalize(base),
        tuple(sorted(artist_tokens(track.artist))),
        tuple(sorted(tags)),
        normalize(track.album),
        duration,
    )


class LyricsResolver:
    """Apply source ordering, cache policy, and shared lookup lifecycle rules."""

    def __init__(
        self,
        *,
        catalog: LyricsSourceCatalog,
        cache: ResolverCachePort,
        cache_enabled: bool = True,
        negative_ttl: float = 30.0,
        prefer_best: bool = True,
        fuzzy: bool = True,
    ) -> None:
        """Create a resolver from an explicit source graph and cache policy."""
        self._cache = cache
        self._catalog = catalog
        self._sources: dict[str, LyricsSource] = dict(catalog.sources)
        self._live_source_id = catalog.live_source_id
        self._exact_source = catalog.exact_source
        self._cache_enabled = cache_enabled
        self._prefer_best = prefer_best
        self._fuzzy = fuzzy
        self._negative_ttl = negative_ttl
        self._negative_until: dict[tuple[str, ResolutionCacheKey], float] = {}
        self._inflight: dict[RequestKey, asyncio.Task[ResolverLookup]] = {}

    def start(self) -> None:
        """Reopen resolver-owned workers after a previous close.

        Lookup policy remains in memory; only the cache and source workers
        need to be reopened. The method is synchronous because no I/O occurs
        until the next lookup.
        """
        self._cache.start()
        self._catalog.start()

    @property
    def live_source_id(self) -> str:
        """Return the configured source slot for live adapter candidates."""
        return self._live_source_id

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        sources: Sequence[str],
    ) -> LyricsSourceResult | None:
        """Resolve one track and discard request diagnostics for simple callers."""
        lookup = await self.resolve_with_diagnostics(session, track, sources)
        return lookup.result

    async def resolve_with_diagnostics(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        sources: Sequence[str],
    ) -> ResolverLookup:
        """Resolve one track while preserving failures for that request."""
        ordered_sources = tuple(sources)
        key = (track, ordered_sources, self._cache_enabled, self._prefer_best, self._fuzzy)
        task = self._inflight.get(key)
        if task is None:
            task = create_owned_task(
                self._resolve_once(session, track, ordered_sources),
                name="kotonoha-lyrics-resolver",
            )
            self._inflight[key] = task
        try:
            # Shielded: the task is shared, and awaiting it directly made one
            # caller's cancellation cancel it for everyone — a second request for
            # the same track raised CancelledError without ever having asked. The
            # work continues for whoever is still waiting, and its result still
            # reaches the cache; cancel_inflight is the owner's path to stop it.
            return await asyncio.shield(task)
        finally:
            if task.done() and self._inflight.get(key) is task:
                self._inflight.pop(key, None)

    async def cancel_inflight(self) -> None:
        """Cancel and await every shared lookup this resolver started.

        The owner's cancellation path for the tasks created above, which outlive
        any single caller by design.
        """
        tasks = list(self._inflight.values())
        self._inflight.clear()
        for task in tasks:
            task.cancel()
        if not tasks:
            return
        joined = asyncio.gather(*tasks, return_exceptions=True)
        cancellation_requested = await wait_for_owned(joined)
        for task in tasks:
            if task.cancelled():
                continue
            error = task.exception()
            if isinstance(error, (LyricsSourceError, LyricsCacheError, TimeoutError, ValueError)):
                logger.debug("lyrics resolver task ended during shutdown: %s", error)
        if cancellation_requested:
            raise asyncio.CancelledError

    async def close(self) -> None:
        """Cancel owned lookups and release cache/source workers."""
        await self.cancel_inflight()
        self._cache.close()
        self._catalog.close()

    async def resolve_hint(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        sources: Sequence[str],
        hint: LyricsHint,
    ) -> LyricsSourceResult | None:
        """Restore manual lyrics, then resolve a hint and seek word timing in best mode."""
        manual = await self._lookup_manual(track)
        if manual is not None:
            return self._result_from_cache(manual)
        try:
            exact = await self._exact_source.resolve(
                session,
                track,
                hint,
                enabled_sources=tuple(sources),
                prefer_best=self._prefer_best,
            )
        # asyncio.TimeoutError is the builtin TimeoutError from 3.11, which this
        # project now requires, so naming both was one exception written twice.
        except (LyricsSourceError, TimeoutError, ValueError, RuntimeError) as exc:
            logger.warning("%s exact lyrics fetch failed: %s: %s", hint.provider, type(exc).__name__, exc)
            return None
        if exact is None:
            return None
        await self._store_result(exact)
        if not self._prefer_best or exact.document.has_word_timing:
            return exact
        # An exact hint establishes identity, but does not guarantee word
        # timing. Search the other enabled slots without refetching the hinted id.
        alternative = await self.resolve(
            session, track, [source for source in sources if source not in {hint.provider, exact.source_id}],
        )
        if alternative is not None and (
            _CONF_RANK[alternative.confidence], alternative.document.has_word_timing
        ) > (_CONF_RANK[exact.confidence], exact.document.has_word_timing):
            return alternative
        return exact

    async def _resolve_once(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        sources: tuple[str, ...],
    ) -> ResolverLookup:
        failures: set[str] = set()
        track_key = _resolution_cache_key(track)
        logger.debug(
            "lyrics lookup started: track=%r / %r sources=%s mode=%s cache=%s fuzzy=%s",
            track.title,
            track.artist,
            ",".join(sources) or "-",
            "best" if self._prefer_best else "sequential",
            self._cache_enabled,
            self._fuzzy,
        )
        manual = await self._lookup_manual(track)
        if manual is not None:
            return ResolverLookup(self._result_from_cache(manual), frozenset())
        if self._prefer_best:
            result = await self._resolve_best(session, track, sources, track_key, failures)
        else:
            result = await self._resolve_sequential(session, track, sources, track_key, failures)
        if result is None:
            logger.debug(
                "lyrics lookup finished: track=%r / %r selected=none failed=%s",
                track.title,
                track.artist,
                ",".join(sorted(failures)) or "-",
            )
        else:
            _log_candidate("selected", result.source_id, result)
        return ResolverLookup(result, frozenset(failures))

    async def _resolve_sequential(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        sources: tuple[str, ...],
        track_key: ResolutionCacheKey,
        failures: set[str],
    ) -> LyricsSourceResult | None:
        """Strict first-match in the configured order (cache then network per
        source at its position). Fewer network requests; the default 'best'
        mode below is faster on a miss and picks higher-confidence lyrics."""
        for source in sources:
            adapter = self._sources.get(source)
            if adapter is None:
                continue
            parser = adapter.cache_parser
            if self._cache_enabled and parser is not None:
                try:
                    cached = await self._cache.lookup(source, track, parser)
                except LyricsCacheError as exc:
                    logger.warning("%s lyrics cache lookup failed: %s", source, exc)
                else:
                    if cached is not None:
                        result = self._result_from_cache(cached)
                        _log_candidate("cache", source, result)
                        return result

            negative_key = source, track_key
            if parser is not None and self._negative_until.get(negative_key, 0.0) > time.monotonic():
                logger.debug("lyrics source skipped: slot=%r reason=negative-cache", source)
                continue
            try:
                result = await adapter.resolve(session, track, fuzzy=self._fuzzy)
            except (LyricsSourceError, TimeoutError, ValueError) as exc:
                logger.warning("%s lyrics fetch failed: %s: %s", source, type(exc).__name__, exc)
                failures.add(source)
                continue
            if result is None or not result.document.lines:
                logger.debug("lyrics source missed: slot=%r reason=no-timed-lines", source)
                self._negative_until[negative_key] = time.monotonic() + self._negative_ttl
                continue
            await self._store_result(result)
            _log_candidate("network", source, result)
            return result
        return None

    async def _store_result(self, result: LyricsSourceResult) -> None:
        """Persist automatic and exact artifacts without losing lyrics on cache failure."""
        if self._cache_enabled and result.cache_artifact is not None:
            try:
                await self._cache.store(result.cache_artifact)
            except LyricsCacheError as exc:
                logger.warning("%s lyrics cache write failed: %s", result.source_id, exc)

    async def _resolved_source(
        self,
        source: str,
        track_key: ResolutionCacheKey,
        task: asyncio.Task[LyricsSourceResult | None],
        failures: set[str],
    ) -> LyricsSourceResult | None:
        """Await one source task and apply resolver-owned miss/cache policy."""
        try:
            result = await task
        except asyncio.CancelledError:
            raise
        except (LyricsSourceError, TimeoutError, ValueError) as exc:
            logger.warning("%s lyrics fetch failed: %s: %s", source, type(exc).__name__, exc)
            failures.add(source)
            return None
        if result is None or not result.document.lines:
            logger.debug("lyrics source missed: slot=%r reason=no-timed-lines", source)
            self._negative_until[source, track_key] = time.monotonic() + self._negative_ttl
            return None
        await self._store_result(result)
        _log_candidate("network", source, result)
        return result

    async def _resolve_best(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        sources: tuple[str, ...],
        track_key: ResolutionCacheKey,
        failures: set[str],
    ) -> LyricsSourceResult | None:
        """Pick by confidence, actual word timing, then configured order.
        Free (no-network) candidates — live adapters and cache hits
        — are collected first, then network sources are fetched CONCURRENTLY,
        but only when a HIGH from that source could still beat what we already hold.
        So a cached/cider word-timed HIGH at the top costs no network, latency is
        the slowest single needed source (not the sum). Source order breaks ties
        only after matching confidence and timing quality are equal."""
        best: LyricsSourceResult | None = None
        best_score: tuple[int, bool, int] | None = None
        resolved: set[str] = set()  # sources already answered without a network fetch

        # 1) Free candidates in configured order: live adapters and cache hits.
        for index, source in enumerate(sources):
            candidate: LyricsSourceResult | None = None
            adapter = self._sources.get(source)
            if adapter is None:
                continue
            parser = adapter.cache_parser
            if parser is None:
                candidate = await adapter.resolve(None, track, fuzzy=self._fuzzy)
            elif self._cache_enabled:
                try:
                    cached = await self._cache.lookup(source, track, parser)
                except LyricsCacheError as exc:
                    logger.warning("%s lyrics cache lookup failed: %s", source, exc)
                    cached = None
                if cached is not None:
                    candidate = self._result_from_cache(cached)
            if candidate is not None and candidate.document.lines:
                resolved.add(source)
                _log_candidate("cache-or-live", source, candidate)
                score = (_CONF_RANK[candidate.confidence], candidate.document.has_word_timing, -index)
                if best_score is None or score > best_score:
                    best, best_score = candidate, score

        # 2) Fetch only the network sources that could still change the answer: a
        #    A word-timed HIGH at index i is that source's optimistic ceiling.
        now = time.monotonic()
        tasks: dict[str, asyncio.Task[LyricsSourceResult | None]] = {}
        try:
            for index, source in enumerate(sources):
                # `source in tasks` guards a duplicated source: a second task would
                # overwrite (and orphan) the first, double-fetching and leaking it.
                adapter = self._sources.get(source)
                if source in resolved or source in tasks or adapter is None or adapter.cache_parser is None:
                    continue
                if self._negative_until.get((source, track_key), 0.0) > now:
                    continue
                if best_score is not None and (_CONF_RANK[MatchConfidence.HIGH], True, -index) <= best_score:
                    continue
                if session is None:
                    raise LyricsSourceError(f"network source {source!r} requires an HTTP session")
                logger.debug("lyrics source requested: slot=%r transport=network", source)
                tasks[source] = create_owned_task(
                    adapter.resolve(session, track, fuzzy=self._fuzzy),
                    name=f"kotonoha-lyrics-source-{source}",
                )
            pending = dict(tasks)
            while pending:
                done, _ = await asyncio.wait(pending.values(), return_when=asyncio.FIRST_COMPLETED)
                for source in [s for s, t in pending.items() if t in done]:
                    result = await self._resolved_source(source, track_key, pending.pop(source), failures)
                    if result is None:
                        continue
                    score = (_CONF_RANK[result.confidence], result.document.has_word_timing, -sources.index(source))
                    if best_score is None or score > best_score:
                        best_score = score
                        best = result
                if best_score is not None and pending:
                    # Only word-timed HIGH lyrics can make later slots irrelevant.
                    ceiling = (_CONF_RANK[MatchConfidence.HIGH], True, -min(sources.index(s) for s in pending))
                    if best_score >= ceiling:
                        break
            return best
        finally:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks.values(), return_exceptions=True)

    def set_prefer_best(self, enabled: bool) -> None:
        self._prefer_best = bool(enabled)
        self.reset_memory()  # a wider search could now succeed where a miss was cached

    def set_fuzzy(self, enabled: bool) -> None:
        self._fuzzy = bool(enabled)
        self.reset_memory()  # the negative cache ignores the fuzzy flag; let it retry

    def set_cache_enabled(self, enabled: bool) -> None:
        self._cache_enabled = bool(enabled)
        self.reset_memory()

    def reset_memory(self) -> None:
        self._negative_until.clear()

    async def _lookup_manual(
        self,
        track: TrackMetadata,
    ) -> LyricsCacheHit | None:
        """Look up an explicit selection before exact hints or automatic sources."""
        if not self._cache_enabled:
            return None
        parsers: dict[str, Callable[[Mapping[str, str]], tuple[LyricLine, ...]]] = {}
        for source, adapter in self._sources.items():
            parser = adapter.cache_parser
            if parser is not None:
                parsers[source] = parser
        if not parsers:
            return None
        try:
            return await self._cache.lookup_manual(track, parsers)
        except LyricsCacheError as exc:
            logger.warning("Manual lyrics cache lookup failed: %s", exc)
            return None

    @staticmethod
    def _result_from_cache(hit: LyricsCacheHit) -> LyricsSourceResult:
        """Project a cache hit while preserving whether it was manually confirmed."""
        if hit.mode is LyricsCacheMode.MANUAL:
            origin = LyricsOrigin.MANUAL
            cache_state = LyricsCacheState.MANUAL
        else:
            origin = LyricsOrigin.CACHE
            cache_state = LyricsCacheState.FROM_CACHE
        artifact = hit.artifact
        return LyricsSourceResult(
            artifact.provider,
            document=LyricsSourceResult.from_artifact(
                artifact,
                origin=origin,
                cache_state=cache_state,
            ).document,
            confidence=artifact.confidence,
            duration_s=artifact.duration_s,
        )


def _log_candidate(stage: str, source_slot: str, result: LyricsSourceResult) -> None:
    """Log one resolver candidate or selected result without implying display ownership."""
    document = result.document
    source_label = document.source_name if document.source_name is not None else document.source_id
    if stage == "selected":
        logger.debug(
            "lyrics resolution selected: source_slot=%r lyric_source=%r source_id=%r "
            "kind=%s timing=%s lines=%d confidence=%s duration=%s",
            source_slot,
            source_label,
            document.source_id,
            result.source_kind,
            document.timing,
            len(document.lines),
            result.confidence,
            "-" if result.duration_s is None else f"{result.duration_s:.3f}s",
        )
        return
    logger.debug(
        "lyrics resolution candidate: origin=%s source_slot=%r lyric_source=%r source_id=%r "
        "kind=%s timing=%s lines=%d confidence=%s duration=%s",
        stage,
        source_slot,
        source_label,
        document.source_id,
        result.source_kind,
        document.timing,
        len(document.lines),
        result.confidence,
        "-" if result.duration_s is None else f"{result.duration_s:.3f}s",
    )
