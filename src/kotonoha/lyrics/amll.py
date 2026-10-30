"""AMLL TTML DB source using the upstream catalog and immutable lyric files.

Catalog and raw-file contracts are documented at
https://github.com/amll-dev/amll-ttml-db#接入到其他项目 . The source owns its
bounded worker and in-memory catalog, but borrows HTTP sessions from callers.
All requests run in caller-owned tasks; no background refresh is started.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable, Mapping
from typing import TypeAlias

import aiohttp

from ..async_task import create_owned_task
from ..async_worker import BlockingWorkerPort
from .amll_catalog import MAX_INDEX_BYTES, AmllMatch, AmllRecord, AmllSongId, match_records, parse_index, song_reference
from .artifact import LyricsArtifact
from .hint import LyricsHint
from .http import LyricsHttpError, LyricsSession
from .match import MatchConfidence, TrackMetadata
from .models import LyricLine
from .payload import read_capped
from .search_policy import MANUAL_SEARCH_RESULTS_PER_PROVIDER
from .sources import LyricsSourceError, LyricsSourceResult, PayloadParser
from .ttml_parser import parse_ttml

INDEX_URL = "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/main/metadata/raw-lyrics-index.jsonl"
RAW_URL = "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/main/raw-lyrics/"
_INDEX_TIMEOUT = aiohttp.ClientTimeout(total=15.0, connect=5.0)
_LYRIC_TIMEOUT = aiohttp.ClientTimeout(total=8.0, connect=3.0)
_HEADERS = {"User-Agent": "Kotonoha/lyrics", "Accept": "text/plain, application/xml"}
logger = logging.getLogger(__name__)
DownloadFailure: TypeAlias = LyricsHttpError | TimeoutError | ValueError


def parse_payload(payload: Mapping[str, str]) -> tuple[LyricLine, ...]:
    """Reconstruct canonical lyrics from the same TTML text stored in SQLite."""
    return tuple(parse_ttml(payload.get("ttml", "")))


class AmllLyricsSource:
    """Own catalog caching, matching and bounded downloads for automatic/manual use."""

    def __init__(
        self, *, worker: BlockingWorkerPort, clock: Callable[[], float] = time.monotonic,
        index_ttl_s: float = 3600.0,
    ) -> None:
        if not math.isfinite(index_ttl_s) or index_ttl_s <= 0:
            raise ValueError("AMLL catalog lifetime must be positive and finite")
        # The catalog owner starts/closes this worker after its lookup and manual
        # search callers stop. Cancelled parsing can finish, but cannot publish state.
        self._worker: BlockingWorkerPort = worker
        self._clock: Callable[[], float] = clock
        self._index_ttl_s: float = index_ttl_s
        self._records: tuple[AmllRecord, ...] | None = None
        self._expires_at: float = 0.0
        self._index_lock: asyncio.Lock = asyncio.Lock()

    @property
    def source_id(self) -> str:
        """Return the stable source slot used by settings, cache and search."""
        return "amll"

    @property
    def cache_parser(self) -> PayloadParser:
        """Return the offline parser used by persistent lyric restoration."""
        return parse_payload

    def start(self) -> None:
        """Reopen the owned parsing/matching worker without performing I/O."""
        self._worker.reopen()

    def close(self) -> None:
        """Release worker resources after the owner cancels and awaits its callers."""
        self._worker.close()

    async def _catalog(self, session: LyricsSession) -> tuple[AmllRecord, ...]:
        """Serialize refreshes; publish only a fully parsed, valid catalog."""
        async with self._index_lock:
            if self._records is not None and self._clock() < self._expires_at:
                return self._records
            async with session.get(INDEX_URL, headers=_HEADERS, timeout=_INDEX_TIMEOUT) as response:
                response.raise_for_status()
                body = await read_capped(response, "AMLL catalog", max_bytes=MAX_INDEX_BYTES)
            records = await self._worker.run(parse_index, body)
            self._records = records
            self._expires_at = self._clock() + self._index_ttl_s
            return records

    async def resolve(
        self, session: LyricsSession | None, track: TrackMetadata, *, fuzzy: bool,
    ) -> LyricsSourceResult | None:
        """Automatically match identity, then prefer words within the best confidence."""
        if session is None:
            raise LyricsSourceError("AMLL requires an HTTP session")
        try:
            async with asyncio.timeout(25.0):
                records = await self._catalog(session)
                matches = await self._worker.run(match_records, records, track, fuzzy=fuzzy)
                best: LyricsArtifact | None = None
                failure: DownloadFailure | None = None
                for match in matches[:3]:
                    if best is not None and best.confidence is not match.confidence:
                        break
                    artifact = await self._candidate(session, match)
                    if isinstance(artifact, (LyricsHttpError, TimeoutError, ValueError)):
                        failure = artifact
                        continue
                    if artifact is None:
                        continue
                    if any(line.has_word_timing for line in artifact.lines):
                        return LyricsSourceResult.from_artifact(artifact)
                    if best is None:
                        best = artifact
                if best is None and failure is not None:
                    raise failure
                return None if best is None else LyricsSourceResult.from_artifact(best)
        except LyricsHttpError as exc:
            raise LyricsSourceError("AMLL HTTP lookup failed") from exc

    async def resolve_exact(
        self, session: LyricsSession | None, track: TrackMetadata, hint: LyricsHint,
    ) -> LyricsSourceResult | None:
        """Resolve a known platform ID against the newest usable submission.

        QQ metadata contains song mids. A numeric QQ ID cannot be equated to a
        mid; if it is absent, ordinary metadata matching remains available.
        Try at most three applicable revisions within the existing timeout.
        """
        del track
        if hint.song_id is None:
            return None
        identity = song_reference(hint.provider, hint.song_id)
        if identity is None:
            return None
        if session is None:
            raise LyricsSourceError("AMLL exact lookup requires an HTTP session")
        try:
            async with asyncio.timeout(25.0):
                records = await self._catalog(session)
                revisions = [record for record in records if identity in record.identities]
                failure: DownloadFailure | None = None
                for record in revisions[:3]:
                    artifact = await self._candidate(session, AmllMatch(record, MatchConfidence.HIGH))
                    if isinstance(artifact, (LyricsHttpError, TimeoutError, ValueError)):
                        failure = artifact
                    elif artifact is not None:
                        return LyricsSourceResult.from_artifact(artifact)
                if failure is not None:
                    raise failure
                return None
        except LyricsHttpError as exc:
            raise LyricsSourceError("AMLL exact HTTP lookup failed") from exc

    async def _download(self, session: LyricsSession, match: AmllMatch) -> LyricsArtifact | None:
        """Read one validated catalog filename from a fixed host, preserving raw TTML."""
        candidate = match.record.candidate
        async with session.get(RAW_URL + candidate.song_id, headers=_HEADERS, timeout=_LYRIC_TIMEOUT) as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            body = await read_capped(response, "AMLL TTML")
        payload = {"ttml": body.decode("utf-8-sig")}
        lines = await self._worker.run(parse_payload, payload)
        if not lines:
            logger.debug("AMLL candidate %s has no usable timed lyrics", candidate.song_id)
            return None
        return LyricsArtifact(
            self.source_id, candidate.song_id, candidate.title, candidate.artist,
            candidate.album, candidate.duration_s, payload, lines, match.confidence,
        )

    async def search_artifacts(self, session: LyricsSession, track: TrackMetadata) -> tuple[LyricsArtifact, ...]:
        """Prepare bounded manual choices, retaining usable results if a download fails."""
        async with asyncio.timeout(45.0):
            records = await self._catalog(session)
            matches = (await self._worker.run(match_records, records, track, fuzzy=False, manual=True))[
                :MANUAL_SEARCH_RESULTS_PER_PROVIDER
            ]
            gate = asyncio.Semaphore(4)
            tasks: list[asyncio.Task[LyricsArtifact | DownloadFailure | None]] = []
            try:
                for match in matches:
                    tasks.append(create_owned_task(
                        self._manual_download(session, match, gate), name="kotonoha-amll-manual-download",
                    ))
                results = await asyncio.gather(*tasks)
                # A catalog ID links revisions, but only a usable file can claim
                # that identity. Earlier failures leave older submissions eligible.
                seen: set[AmllSongId] = set()
                artifacts: list[LyricsArtifact] = []
                for match, result in zip(matches, results, strict=True):
                    if isinstance(result, LyricsArtifact) and not seen & match.record.identities:
                        artifacts.append(result)
                        seen.update(match.record.identities)
                failures = [result for result in results if isinstance(result, Exception)]
                if failures and not artifacts:
                    raise failures[0]
                return tuple(artifacts)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

    async def _manual_download(
        self, session: LyricsSession, match: AmllMatch, gate: asyncio.Semaphore,
    ) -> LyricsArtifact | DownloadFailure | None:
        """Limit simultaneous requests while the caller owns cancellation and joins."""
        async with gate:
            return await self._candidate(session, match)

    async def _candidate(self, session: LyricsSession, match: AmllMatch) -> LyricsArtifact | DownloadFailure | None:
        """Keep expected candidate failures observable without discarding other hits."""
        try:
            return await self._download(session, match)
        except (LyricsHttpError, TimeoutError, ValueError) as exc:
            logger.debug("AMLL candidate %s failed: %s", match.record.candidate.song_id, exc)
            return exc


__all__ = ["AmllLyricsSource", "parse_payload"]
