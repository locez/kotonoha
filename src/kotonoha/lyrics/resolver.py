"""Resolve lyrics in the exact provider order configured by the user."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeAlias

import aiohttp

from ..model import LyricLine, LyricsSnapshot
from ..providers.gate import CiderMatch, SourceGate
from . import lrclib, netease
from .artifact import LyricsArtifact
from .cache import LyricsCache
from .match import MatchConfidence, TrackMetadata, artist_tokens, normalize, split_title

logger = logging.getLogger(__name__)

TrackKey: TypeAlias = tuple[str, tuple[str, ...], tuple[str, ...], str, float | None]
RequestKey: TypeAlias = tuple[TrackKey, tuple[str, ...], bool]


@dataclass(frozen=True)
class ResolvedLyrics:
    source: str
    lines: tuple[LyricLine, ...] = ()
    live_snapshot: LyricsSnapshot | None = None
    cider_client_id: int | None = None


@dataclass(frozen=True)
class NetworkProvider:
    name: str
    fetch: Callable[[aiohttp.ClientSession, TrackMetadata], Awaitable[LyricsArtifact | None]]
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
    ) -> None:
        self._cache = cache or LyricsCache()
        self._gate = gate or SourceGate()
        self._providers = dict(providers) if providers is not None else {
            "netease": NetworkProvider("netease", netease.fetch_artifact, netease.parse_payload),
            "lrclib": NetworkProvider("lrclib", lrclib.fetch_artifact, lrclib.parse_payload),
        }
        self._cache_enabled = cache_enabled
        self._negative_ttl = negative_ttl
        self._negative_until: dict[tuple[str, TrackKey], float] = {}
        self._inflight: dict[RequestKey, asyncio.Task[ResolvedLyrics | None]] = {}

    async def resolve(
        self,
        session: aiohttp.ClientSession,
        track: TrackMetadata,
        sources: Sequence[str],
    ) -> ResolvedLyrics | None:
        ordered_sources = tuple(sources)
        key = (_track_key(track), ordered_sources, self._cache_enabled)
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._resolve_once(session, track, ordered_sources))
            self._inflight[key] = task
        try:
            return await task
        finally:
            if task.done() and self._inflight.get(key) is task:
                self._inflight.pop(key, None)

    async def _resolve_once(
        self,
        session: aiohttp.ClientSession,
        track: TrackMetadata,
        sources: tuple[str, ...],
    ) -> ResolvedLyrics | None:
        self._gate.select_external()
        track_key = _track_key(track)
        for source in sources:
            if source == "cider":
                match = self._gate.current_match(track)
                if match is not None:
                    self._gate.select_cider(match.client_id)
                    return ResolvedLyrics(
                        source="cider",
                        live_snapshot=match.snapshot,
                        cider_client_id=match.client_id,
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
                        return ResolvedLyrics(source=source, lines=cached.lines)

            negative_key = source, track_key
            if self._negative_until.get(negative_key, 0.0) > time.monotonic():
                continue
            try:
                artifact = await provider.fetch(session, track)
            except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, ValueError) as exc:
                logger.warning("%s lyrics fetch failed: %s: %s", source, type(exc).__name__, exc)
                continue
            if artifact is None or not artifact.lines:
                self._negative_until[negative_key] = time.monotonic() + self._negative_ttl
                continue
            if self._cache_enabled and artifact.confidence is MatchConfidence.HIGH:
                try:
                    await self._cache.store(artifact)
                except (OSError, sqlite3.Error) as exc:
                    logger.warning("%s lyrics cache write failed: %s", source, exc)
            return ResolvedLyrics(source=source, lines=artifact.lines)
        return None

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
