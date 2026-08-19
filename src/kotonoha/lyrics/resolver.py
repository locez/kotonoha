"""Resolve lyrics in the exact provider order configured by the user."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias

import aiohttp

from ..model import LyricLine, LyricsSnapshot
from ..providers.gate import CiderMatch, SourceGate
from . import kugou, lrclib, netease, qqmusic
from .artifact import LyricsArtifact
from .cache import LyricsCache
from .hint import LyricsHint
from .local import load_local_lyrics
from .match import MatchConfidence, TrackMetadata
from .titles import artist_tokens, normalize, split_title

logger = logging.getLogger(__name__)

TrackKey: TypeAlias = tuple[str, tuple[str, ...], tuple[str, ...], str, float | None]
RequestKey: TypeAlias = tuple[TrackKey, tuple[str, ...], bool, bool, bool]

_CONF_RANK = {MatchConfidence.NONE: 0, MatchConfidence.MEDIUM: 1, MatchConfidence.HIGH: 2}


class ProviderFetch(Protocol):
    def __call__(
        self, session: aiohttp.ClientSession, track: TrackMetadata, *, fuzzy: bool = ...
    ) -> Coroutine[Any, Any, LyricsArtifact | None]: ...


@dataclass(frozen=True)
class ResolvedLyrics:
    source: str
    lines: tuple[LyricLine, ...] = ()
    live_snapshot: LyricsSnapshot | None = None
    cider_client_id: int | None = None
    confidence: MatchConfidence = MatchConfidence.NONE
    #: How long the catalogue says this recording is. The player's own figure can be
    #: a running total across a queue; this one is about the song itself.
    duration_s: float | None = None


@dataclass(frozen=True)
class NetworkProvider:
    name: str
    fetch: ProviderFetch
    parse_payload: Callable[[Mapping[str, str]], tuple[LyricLine, ...]]


class CacheLike(Protocol):
    async def lookup(
        self,
        provider: str,
        track: TrackMetadata,
        parser: Callable[[Mapping[str, str]], tuple[LyricLine, ...]],
        /,
    ) -> LyricsArtifact | None: ...

    async def store(self, artifact: LyricsArtifact, /) -> None: ...

    async def clear(self) -> None: ...


class GateLike(Protocol):
    def select_external(self) -> None: ...

    def current_match(self, track: TrackMetadata, /) -> CiderMatch | None: ...

    def select_cider(self, client_id: int, /) -> None: ...


def _track_key(track: TrackMetadata) -> TrackKey:
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
    def __init__(
        self,
        *,
        cache: CacheLike | None = None,
        gate: GateLike | None = None,
        providers: Mapping[str, NetworkProvider] | None = None,
        cache_enabled: bool = True,
        negative_ttl: float = 30.0,
        prefer_best: bool = True,
        fuzzy: bool = True,
    ) -> None:
        self._cache = cache or LyricsCache()
        self._gate = gate or SourceGate()
        self._providers = dict(providers) if providers is not None else {
            "netease": NetworkProvider("netease", netease.fetch_artifact, netease.parse_payload),
            "qqmusic": NetworkProvider("qqmusic", qqmusic.fetch_artifact, qqmusic.parse_payload),
            "lrclib": NetworkProvider("lrclib", lrclib.fetch_artifact, lrclib.parse_payload),
            "kugou": NetworkProvider("kugou", kugou.fetch_artifact, kugou.parse_payload),
        }
        self._cache_enabled = cache_enabled
        self._prefer_best = prefer_best
        self._fuzzy = fuzzy
        self._negative_ttl = negative_ttl
        self._negative_until: dict[tuple[str, TrackKey], float] = {}
        #: Sources whose request failed during the last resolve, as opposed to
        #: answering that they do not have the song. Read straight after a resolve
        #: returns nothing: "no lyrics" and "nobody could be reached" look identical
        #: from the outside and call for opposite responses.
        self._last_failures: set[str] = set()
        self._inflight: dict[RequestKey, asyncio.Task[ResolvedLyrics | None]] = {}

    @property
    def last_failures(self) -> frozenset[str]:
        """The sources that could not be reached during the last resolve."""
        return frozenset(self._last_failures)

    async def resolve(
        self,
        session: aiohttp.ClientSession,
        track: TrackMetadata,
        sources: Sequence[str],
    ) -> ResolvedLyrics | None:
        self._last_failures.clear()
        ordered_sources = tuple(sources)
        key = (_track_key(track), ordered_sources, self._cache_enabled, self._prefer_best, self._fuzzy)
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._resolve_once(session, track, ordered_sources))
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
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - teardown
                pass

    async def resolve_hint(
        self, session: aiohttp.ClientSession, track: TrackMetadata, sources: Sequence[str], hint: LyricsHint
    ) -> ResolvedLyrics | None:
        if hint.provider == "local" and hint.local_path is not None:
            # Filesystem reads and mutagen tag parsing on the qasync loop that also
            # drives the UI and the MPRIS poll: measured with a FIFO in place of the
            # .lrc, the call held the loop for the writer's full delay. Cancelling
            # this task does not cancel the read — the thread finishes and its result
            # is dropped — which is safe here because it takes no lock and writes
            # nothing, and it ends with the interpreter.
            lines = await asyncio.to_thread(load_local_lyrics, hint.local_path)
            return ResolvedLyrics("local", lines=tuple(lines), confidence=MatchConfidence.HIGH) if lines else None
        if hint.song_id is None or hint.provider not in {"netease", "qqmusic"} or hint.provider not in sources:
            return None
        provider = netease if hint.provider == "netease" else qqmusic
        try:
            payload = (
                await netease.fetch_payload(session, hint.song_id)
                if hint.provider == "netease"
                else await qqmusic.fetch_payload_for_song_id(session, hint.song_id)
            )
        # asyncio.TimeoutError is the builtin TimeoutError from 3.11, which this
        # project now requires, so naming both was one exception written twice.
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            logger.warning("%s exact lyrics fetch failed: %s: %s", hint.provider, type(exc).__name__, exc)
            return None
        lines = provider.parse_payload(payload)
        if not lines:
            return None
        return ResolvedLyrics(hint.provider, lines=lines, confidence=MatchConfidence.HIGH)

    async def _resolve_once(
        self,
        session: aiohttp.ClientSession,
        track: TrackMetadata,
        sources: tuple[str, ...],
    ) -> ResolvedLyrics | None:
        self._gate.select_external()
        track_key = _track_key(track)
        if self._prefer_best:
            return await self._resolve_best(session, track, sources, track_key)
        return await self._resolve_sequential(session, track, sources, track_key)

    async def _resolve_sequential(
        self, session: aiohttp.ClientSession, track: TrackMetadata, sources: tuple[str, ...], track_key: TrackKey
    ) -> ResolvedLyrics | None:
        """Strict first-match in the configured order (cache then network per
        source, cider at its position). Fewer network requests; the default 'best'
        mode below is faster on a miss and picks higher-confidence lyrics."""
        for source in sources:
            if source == "cider":
                match = self._gate.current_match(track)
                if match is not None:
                    self._gate.select_cider(match.client_id)
                    return ResolvedLyrics(
                        "cider", live_snapshot=match.snapshot,
                        cider_client_id=match.client_id, confidence=match.confidence,
                    )
                continue

            provider = self._providers.get(source)
            if provider is None:
                continue
            if self._cache_enabled:
                try:
                    cached = await self._cache.lookup(source, track, provider.parse_payload)
                except (OSError, sqlite3.Error) as exc:
                    logger.warning("%s lyrics cache lookup failed: %s", source, exc)
                else:
                    if cached is not None:
                        return ResolvedLyrics(source, lines=cached.lines, confidence=cached.confidence,
                                              duration_s=cached.duration_s)

            negative_key = source, track_key
            if self._negative_until.get(negative_key, 0.0) > time.monotonic():
                continue
            try:
                artifact = await provider.fetch(session, track, fuzzy=self._fuzzy)
            except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                logger.warning("%s lyrics fetch failed: %s: %s", source, type(exc).__name__, exc)
                self._last_failures.add(source)
                continue
            if artifact is None or not artifact.lines:
                self._negative_until[negative_key] = time.monotonic() + self._negative_ttl
                continue
            if self._cache_enabled and artifact.confidence is MatchConfidence.HIGH:
                try:
                    await self._cache.store(artifact)
                except (OSError, sqlite3.Error) as exc:
                    logger.warning("%s lyrics cache write failed: %s", source, exc)
            return ResolvedLyrics(source, lines=artifact.lines, confidence=artifact.confidence,
                                  duration_s=artifact.duration_s)
        return None

    async def _resolved_artifact(
        self, source: str, track_key: TrackKey, task: asyncio.Task[LyricsArtifact | None]
    ) -> LyricsArtifact | None:
        """Await one (already-launched) provider task, negative-caching a miss and
        storing a HIGH hit. Returns the artifact with lines, or None."""
        try:
            artifact = await task
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            logger.warning("%s lyrics fetch failed: %s: %s", source, type(exc).__name__, exc)
            self._last_failures.add(source)
            return None
        if artifact is None or not artifact.lines:
            self._negative_until[source, track_key] = time.monotonic() + self._negative_ttl
            return None
        if self._cache_enabled and artifact.confidence is MatchConfidence.HIGH:
            try:
                await self._cache.store(artifact)
            except (OSError, sqlite3.Error) as exc:
                logger.warning("%s lyrics cache write failed: %s", source, exc)
        return artifact

    async def _resolve_best(
        self, session: aiohttp.ClientSession, track: TrackMetadata, sources: tuple[str, ...], track_key: TrackKey
    ) -> ResolvedLyrics | None:
        """Pick the best result across sources: highest confidence, then the
        configured order. Free (no-network) candidates — cache hits and a live cider
        match — are collected first, then network sources are fetched CONCURRENTLY,
        but only when a HIGH from that source could still beat what we already hold.
        So a cached/cider HIGH at the top of the order costs no network, latency is
        the slowest single needed source (not the sum), and a lower-priority result
        never wins a confidence tie over a higher-priority one."""
        cider_match = self._gate.current_match(track) if "cider" in sources else None

        best: ResolvedLyrics | None = None
        best_score: tuple[int, int] | None = None
        resolved: set[str] = set()  # sources already answered without a network fetch

        # 1) Free candidates in configured order: a live cider match (at its real
        #    confidence) and cache hits (stored only when HIGH).
        for index, source in enumerate(sources):
            candidate: ResolvedLyrics | None = None
            if source == "cider":
                if cider_match is not None:
                    candidate = ResolvedLyrics(
                        "cider", live_snapshot=cider_match.snapshot,
                        cider_client_id=cider_match.client_id, confidence=cider_match.confidence,
                    )
            elif self._cache_enabled and source in self._providers:
                try:
                    cached = await self._cache.lookup(source, track, self._providers[source].parse_payload)
                except (OSError, sqlite3.Error) as exc:
                    logger.warning("%s lyrics cache lookup failed: %s", source, exc)
                    cached = None
                if cached is not None:
                    candidate = ResolvedLyrics(
                        source, lines=cached.lines, confidence=cached.confidence,
                        duration_s=cached.duration_s,
                    )
            if candidate is not None:
                resolved.add(source)
                score = (_CONF_RANK[candidate.confidence], -index)
                if best_score is None or score > best_score:
                    best, best_score = candidate, score

        # 2) Fetch only the network sources that could still change the answer: a
        #    HIGH at index i beats the current best iff (HIGH, -i) > best_score.
        now = time.monotonic()
        tasks: dict[str, asyncio.Task[LyricsArtifact | None]] = {}
        for index, source in enumerate(sources):
            # `source in tasks` guards a duplicated source: a second create_task would
            # overwrite (and orphan) the first, double-fetching and leaking a task.
            if source in resolved or source in tasks or source not in self._providers:
                continue
            if self._negative_until.get((source, track_key), 0.0) > now:
                continue
            if best_score is not None and (_CONF_RANK[MatchConfidence.HIGH], -index) <= best_score:
                continue
            tasks[source] = asyncio.create_task(
                self._providers[source].fetch(session, track, fuzzy=self._fuzzy)
            )

        try:
            pending = dict(tasks)
            while pending:
                done, _ = await asyncio.wait(pending.values(), return_when=asyncio.FIRST_COMPLETED)
                for source in [s for s, t in pending.items() if t in done]:
                    artifact = await self._resolved_artifact(source, track_key, pending.pop(source))
                    if artifact is None:
                        continue
                    score = (_CONF_RANK[artifact.confidence], -sources.index(source))
                    if best_score is None or score > best_score:
                        best_score = score
                        best = ResolvedLyrics(
                            source, lines=artifact.lines, confidence=artifact.confidence,
                            duration_s=artifact.duration_s,
                        )
                if best_score is not None and pending:
                    # Nothing still pending can beat a HIGH from an earlier-ordered source.
                    ceiling = (_CONF_RANK[MatchConfidence.HIGH], -min(sources.index(s) for s in pending))
                    if best_score >= ceiling:
                        break
            if best is not None and best.source == "cider" and cider_match is not None:
                self._gate.select_cider(cider_match.client_id)
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

    async def clear_cache(self) -> None:
        try:
            await self._cache.clear()
        finally:
            self.reset_memory()
