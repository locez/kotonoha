"""LRCLIB synchronized-lyrics provider."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass

import aiohttp

from ..model import LyricLine
from .artifact import LyricsArtifact
from .lrc_parser import parse_lrc
from .match import (
    Candidate,
    TrackMetadata,
    base_title,
    best_match,
    noisy_title_queries,
    primary_artist,
)

logger = logging.getLogger(__name__)

GET_URL = "https://lrclib.net/api/get"
SEARCH_URL = "https://lrclib.net/api/search"
HEADERS = {"User-Agent": "kotonoha/0.1 (https://github.com/locez/kotonoha)"}
# lrclib's backend is routinely slow (measured 7-12s round trips, occasional
# 502s), so it needs a much longer budget than netease or it times out on every
# request and the whole source looks dead. This runs off the UI thread, so
# waiting is fine; the session-wide safety net (20s) still bounds a true hang.
TIMEOUT = aiohttp.ClientTimeout(total=15.0, connect=5.0)


@dataclass(frozen=True)
class Record:
    song_id: str
    title: str
    artist: str
    album: str
    duration_s: float | None
    synced_lyrics: str


def _record(data: object) -> Record | None:
    if not isinstance(data, dict):
        return None
    song_id = data.get("id")
    if song_id is None:
        return None
    synced = data.get("syncedLyrics")
    if not isinstance(synced, str) or not synced.strip():
        return None
    duration = data.get("duration")
    return Record(
        song_id=str(song_id),
        title=str(data.get("trackName", "")),
        artist=str(data.get("artistName", "")),
        album=str(data.get("albumName", "")),
        duration_s=float(duration) if isinstance(duration, (int, float)) else None,
        synced_lyrics=synced,
    )


async def get_exact(session: aiohttp.ClientSession, track: TrackMetadata) -> Record | None:
    params = {"track_name": track.title, "artist_name": track.artist}
    if track.duration_s is not None:
        params["duration"] = str(int(round(track.duration_s)))
    async with session.get(GET_URL, params=params, headers=HEADERS, timeout=TIMEOUT) as response:
        if response.status == 404:
            return None
        response.raise_for_status()
        data = await response.json(content_type=None)
    if not isinstance(data, dict):
        raise ValueError("LRCLIB exact response is not an object")
    return _record(data)


async def _search(session: aiohttp.ClientSession, track_name: str, artist_name: str) -> list[Record]:
    params = {"track_name": track_name}
    if artist_name:
        params["artist_name"] = artist_name
    async with session.get(SEARCH_URL, params=params, headers=HEADERS, timeout=TIMEOUT) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)
    if not isinstance(data, list):
        raise ValueError("LRCLIB search response is not a list")
    return [record for item in data if (record := _record(item)) is not None]


async def search_records(session: aiohttp.ClientSession, track: TrackMetadata) -> list[Record]:
    return await _search(session, base_title(track.title), primary_artist(track.artist))


def parse_payload(payload: Mapping[str, str]) -> tuple[LyricLine, ...]:
    return tuple(parse_lrc(payload.get("syncedLyrics", "")))


async def fetch_artifact(
    session: aiohttp.ClientSession,
    track: TrackMetadata,
    *,
    fuzzy: bool = False,
) -> LyricsArtifact | None:
    async def exact_records() -> list[Record]:
        exact = await get_exact(session, track)
        return [exact] if exact is not None else []

    pending: dict[asyncio.Task[list[Record]], str] = {
        asyncio.create_task(exact_records()): "exact",
        asyncio.create_task(search_records(session, track)): "search",
    }
    if fuzzy:
        # Salvage noisy browser titles: search each cleaned CJK/Latin run on its own
        # (no artist, since a YouTube "artist" is usually the channel), so a
        # bracket-and-channel-laden title still finds the track.
        for cleaned in noisy_title_queries(track):
            pending[asyncio.create_task(_search(session, cleaned, ""))] = "fuzzy"
    records: list[Record] = []
    errors: list[Exception] = []
    successful_requests = 0
    try:
        while pending:
            done, _remaining = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                stage = pending.pop(task)
                try:
                    records.extend(task.result())
                    successful_requests += 1
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                    errors.append(exc)
                    logger.debug("LRCLIB %s lookup failed: %s: %s", stage, type(exc).__name__, exc)

            artifact = _artifact_from_records(records, track, fuzzy=fuzzy)
            if artifact is not None and artifact.confidence.value == "high":
                return artifact

        artifact = _artifact_from_records(records, track, fuzzy=fuzzy)
        if artifact is not None:
            return artifact
        if successful_requests == 0 and errors:
            raise errors[0]
        return None
    finally:
        remaining = tuple(pending)
        for task in remaining:
            task.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)


def _artifact_from_records(
    records: list[Record], track: TrackMetadata, *, fuzzy: bool = False
) -> LyricsArtifact | None:
    candidates = [
        Candidate(record.song_id, record.title, record.artist, record.duration_s, album=record.album)
        for record in records
    ]
    match = best_match(candidates, track, fuzzy=fuzzy)
    if match is None:
        return None
    record = next(
        item
        for item in records
        if Candidate(item.song_id, item.title, item.artist, item.duration_s, album=item.album) == match.candidate
    )
    payload = {"syncedLyrics": record.synced_lyrics}
    lines = parse_payload(payload)
    if not lines:
        return None
    return LyricsArtifact(
        provider="lrclib",
        provider_song_id=record.song_id,
        title=record.title,
        artist=record.artist,
        album=record.album,
        duration_s=record.duration_s,
        payload=payload,
        lines=lines,
        confidence=match.confidence,
    )
