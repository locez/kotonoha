"""Typed lyric-source contracts and concrete local/network adapters."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..async_worker import BlockingWorkerPort
from .adapter import LyricsDocumentAdapter
from .artifact import LyricsArtifact
from .hint import LyricsHint
from .http import LyricsSession
from .local import load_embedded_lyrics, load_sidecar_lyrics
from .match import MatchConfidence, TrackMetadata
from .models import LyricLine, LyricsCacheState, LyricsDocument, LyricsOrigin

PayloadParser = Callable[[Mapping[str, str]], tuple[LyricLine, ...]]
logger = logging.getLogger(__name__)


class LyricsSourceKind(StrEnum):
    """Describe how a normalized lyric document entered the application."""

    NETWORK = "network"
    LIVE = "live"
    LOCAL = "local"


class LyricsSourceError(RuntimeError):
    """A source could not complete its lookup at its external boundary."""


@dataclass(frozen=True)
class LyricsSourceResult:
    """One normalized source result before display projection.

    ``cache_artifact`` is a persistence hand-off for cacheable network sources.
    It is excluded from equality because callers compare normalized source data,
    not a provider's raw payload. The document is deliberately the only lyric
    content crossing this boundary; display frames belong to the display layer.
    """

    source_id: str
    document: LyricsDocument
    confidence: MatchConfidence = MatchConfidence.NONE
    duration_s: float | None = None
    cache_artifact: LyricsArtifact | None = field(default=None, repr=False, compare=False)
    source_kind: LyricsSourceKind = LyricsSourceKind.NETWORK

    @classmethod
    def from_artifact(
        cls,
        artifact: LyricsArtifact,
        *,
        origin: LyricsOrigin = LyricsOrigin.NETWORK,
        cache_state: LyricsCacheState = LyricsCacheState.NONE,
    ) -> LyricsSourceResult:
        """Convert a provider artifact into the source contract."""
        return cls(
            source_id=artifact.provider,
            document=LyricsDocumentAdapter().adapt(
                artifact.lines,
                source_id=artifact.provider,
                song_id=artifact.provider_song_id,
                title=artifact.title,
                artist=artifact.artist,
                album=artifact.album,
                duration_s=artifact.duration_s,
                origin=origin,
                cache_state=cache_state,
            ),
            confidence=artifact.confidence,
            duration_s=artifact.duration_s,
            cache_artifact=artifact,
        )


class LyricsSource(Protocol):
    """Structural contract implemented by automatic and exact lyric sources."""

    @property
    def source_id(self) -> str: ...

    @property
    def cache_parser(self) -> PayloadParser | None: ...

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        *,
        fuzzy: bool,
    ) -> LyricsSourceResult | None: ...

    async def resolve_exact(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        hint: LyricsHint,
    ) -> LyricsSourceResult | None: ...


class SidecarLyricsSource:
    """Read the timed lyric file adjacent to a local audio file."""

    @property
    def source_id(self) -> str:
        """Return the canonical sidecar source identifier."""
        return "sidecar"

    @property
    def cache_parser(self) -> PayloadParser | None:
        """Sidecar files are not persisted through the network cache."""
        return None

    def read(self, audio_path: Path) -> list[LyricLine]:
        """Read sidecar lines synchronously inside an owned worker."""
        return load_sidecar_lyrics(audio_path)


class EmbeddedLyricsSource:
    """Read timed lyric tags embedded in a local audio file."""

    @property
    def source_id(self) -> str:
        """Return the canonical embedded source identifier."""
        return "embedded"

    @property
    def cache_parser(self) -> PayloadParser | None:
        """Embedded tags are not persisted through the network cache."""
        return None

    def read(self, audio_path: Path) -> list[LyricLine]:
        """Read embedded lines synchronously inside an owned worker."""
        return load_embedded_lyrics(audio_path)


class LocalLyricsSource:
    """Compose sidecar and embedded sources for an exact local-file hint."""

    def __init__(
        self,
        sidecar: SidecarLyricsSource,
        embedded: EmbeddedLyricsSource,
        *,
        worker: BlockingWorkerPort,
    ) -> None:
        self._sidecar = sidecar
        self._embedded = embedded
        self._worker = worker

    def start(self) -> None:
        """Reopen the local reader worker after a previous provider shutdown."""
        self._worker.reopen()

    def close(self) -> None:
        """Release the local-file worker without blocking the event loop."""
        self._worker.close()

    @property
    def source_id(self) -> str:
        """Return the exact-hint source identifier."""
        return "local"

    @property
    def cache_parser(self) -> PayloadParser | None:
        """Local file reads do not have a provider payload cache."""
        return None

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        *,
        fuzzy: bool,
    ) -> LyricsSourceResult | None:
        """Local files are opt-in through an exact player hint."""
        del session, track, fuzzy
        return None

    async def resolve_exact(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        hint: LyricsHint,
    ) -> LyricsSourceResult | None:
        """Prefer local word timing, retaining sidecar priority on a timing tie."""
        del session
        local_path = hint.local_path
        if hint.provider != self.source_id or local_path is None:
            return None

        def read() -> tuple[str, tuple[LyricLine, ...]]:
            sidecar = tuple(self._sidecar.read(local_path))
            if any(line.has_word_timing for line in sidecar):
                return self._sidecar.source_id, sidecar
            embedded = tuple(self._embedded.read(local_path))
            if any(line.has_word_timing for line in embedded) or not sidecar:
                return self._embedded.source_id, embedded
            return self._sidecar.source_id, sidecar

        source_id, lines = await self._worker.run(read)
        if not lines:
            return None
        return LyricsSourceResult(
            source_id=source_id,
            document=LyricsDocumentAdapter().adapt(
                lines,
                source_id=source_id,
                title=track.title,
                artist=track.artist,
                album=track.album,
                duration_s=track.duration_s,
                origin=LyricsOrigin.SIDECAR if source_id == self._sidecar.source_id else LyricsOrigin.EMBEDDED,
            ),
            confidence=MatchConfidence.HIGH,
            duration_s=track.duration_s,
            source_kind=LyricsSourceKind.LOCAL,
        )


class ExactLyricsSource:
    """Route a player-provided exact hint to the matching source adapter."""

    def __init__(self, sources: Mapping[str, LyricsSource], local: LocalLyricsSource) -> None:
        self._sources = dict(sources)
        self._local = local

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        hint: LyricsHint,
        *,
        enabled_sources: tuple[str, ...],
        prefer_best: bool = True,
    ) -> LyricsSourceResult | None:
        """Try enabled adapters that understand the ID, including cross-platform catalogs.

        Exact identity is retained across provider failures. In best mode word
        timing wins; otherwise the configured first successful source wins.
        """
        if hint.provider == self._local.source_id:
            return await self._local.resolve_exact(session, track, hint)
        best: LyricsSourceResult | None = None
        for name in dict.fromkeys(enabled_sources):
            source = self._sources.get(name)
            if source is None:
                continue
            try:
                result = await source.resolve_exact(session, track, hint)
            except (LyricsSourceError, TimeoutError, ValueError) as exc:
                logger.warning("%s exact lyrics fetch failed: %s: %s", name, type(exc).__name__, exc)
                continue
            if result is None or not result.document.lines:
                continue
            if not prefer_best or result.document.has_word_timing:
                return result
            if best is None:
                best = result
        return best


__all__ = [
    "EmbeddedLyricsSource",
    "ExactLyricsSource",
    "LocalLyricsSource",
    "LyricsSource",
    "LyricsSourceError",
    "LyricsSourceKind",
    "LyricsSourceResult",
    "PayloadParser",
    "SidecarLyricsSource",
]
