"""Kugou (酷狗) synchronized-lyrics provider.

Kugou's lyric endpoints are open and return plain timed LRC (with ``fmt=lrc`` the
content is base64 LRC, not the encrypted KRC), so no key handling is needed. The
search matches on the song title alone — passing "artist title" returns nothing —
so we query the cleaned title(s) and let the shared matcher rank the candidates by
artist and duration.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from collections.abc import Mapping
from dataclasses import dataclass

import aiohttp

from ..model import LyricLine
from .artifact import LyricsArtifact
from .lrc_parser import parse_lrc
from .match import (
    Candidate,
    MatchConfidence,
    TrackMetadata,
    base_title,
    noisy_title_queries,
    ranked_matches,
)

logger = logging.getLogger(__name__)

SEARCH_URL = "https://lyrics.kugou.com/search"
DOWNLOAD_URL = "https://lyrics.kugou.com/download"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.kugou.com/"}
TIMEOUT = aiohttp.ClientTimeout(total=8.0, connect=4.0)
# A title search returns many same-title covers; cap how many we actually download
# lyrics for so a common title can't fan out into a pile of requests.
_MAX_FETCHES = 5


@dataclass(frozen=True)
class Record:
    cand_id: str
    accesskey: str
    title: str
    artist: str
    duration_s: float | None


def _records(data: object) -> list[Record]:
    if not isinstance(data, dict):
        raise ValueError("Kugou search response is not an object")
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return []
    records: list[Record] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        cand_id = item.get("id")
        accesskey = item.get("accesskey")
        if cand_id is None or not accesskey:
            continue
        duration = item.get("duration")  # milliseconds
        records.append(
            Record(
                cand_id=str(cand_id),
                accesskey=str(accesskey),
                title=str(item.get("song", "")),
                artist=str(item.get("singer", "")),
                duration_s=duration / 1000.0 if isinstance(duration, (int, float)) else None,
            )
        )
    return records


async def search(session: aiohttp.ClientSession, keyword: str) -> list[Record]:
    params = {"ver": "1", "man": "yes", "client": "pc", "keyword": keyword}
    async with session.get(SEARCH_URL, params=params, headers=HEADERS, timeout=TIMEOUT) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)
    return _records(data)


async def download_lrc(session: aiohttp.ClientSession, record: Record) -> str:
    params = {
        "ver": "1",
        "client": "pc",
        "fmt": "lrc",
        "charset": "utf8",
        "id": record.cand_id,
        "accesskey": record.accesskey,
    }
    async with session.get(DOWNLOAD_URL, params=params, headers=HEADERS, timeout=TIMEOUT) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)
    if not isinstance(data, dict):
        raise ValueError("Kugou download response is not an object")
    content = data.get("content")
    if not isinstance(content, str) or not content:
        return ""
    try:
        return base64.b64decode(content).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return ""


def parse_payload(payload: Mapping[str, str]) -> tuple[LyricLine, ...]:
    return tuple(parse_lrc(payload.get("lrc", "")))


def _query_keywords(track: TrackMetadata, fuzzy: bool) -> tuple[str, ...]:
    """Title-only queries for Kugou. The base title first, then (in fuzzy mode) the
    cleaned CJK/Latin runs salvaged from a noisy browser title."""
    keywords = [base_title(track.title).strip()]
    if fuzzy:
        keywords.extend(noisy_title_queries(track))
    return tuple(dict.fromkeys(keyword for keyword in keywords if len(keyword) >= 2))


async def fetch_artifact(
    session: aiohttp.ClientSession,
    track: TrackMetadata,
    *,
    fuzzy: bool = False,
) -> LyricsArtifact | None:
    by_candidate: dict[str, Record] = {}
    ranked: list[tuple[MatchConfidence, Record]] = []
    seen_ids: set[str] = set()
    for keyword in _query_keywords(track, fuzzy):
        records = await search(session, keyword)
        # Kugou's lyric-search "singer" field is unreliable (often the song name or a
        # nickname), so it is dropped for matching — the title and duration carry the
        # identity here, which is why the track's own duration matters for Kugou.
        candidates = [
            Candidate(record.cand_id, record.title, "", record.duration_s)
            for record in records
        ]
        by_candidate.update(zip((c.song_id for c in candidates), records, strict=True))
        for match in ranked_matches(candidates, track, fuzzy=fuzzy):
            song_id = match.candidate.song_id
            if song_id in seen_ids:
                continue
            seen_ids.add(song_id)
            ranked.append((match.confidence, by_candidate[song_id]))

    # HIGH picks first, then the rest, capped, until one download yields real lines.
    ranked.sort(key=lambda item: item[0] is MatchConfidence.HIGH, reverse=True)
    for attempt, (confidence, record) in enumerate(ranked):
        if attempt >= _MAX_FETCHES:
            break
        lrc = await download_lrc(session, record)
        lines = parse_payload({"lrc": lrc})
        if not lines:
            continue
        return LyricsArtifact(
            provider="kugou",
            provider_song_id=record.cand_id,
            title=record.title,
            artist=record.artist,
            album="",
            duration_s=record.duration_s,
            payload={"lrc": lrc},
            lines=lines,
            confidence=confidence,
        )
    return None


async def fetch(
    session: aiohttp.ClientSession,
    title: str,
    artist: str,
    duration_s: float | None,
) -> list[LyricLine] | None:
    """Compatibility wrapper mirroring the other providers."""
    try:
        artifact = await fetch_artifact(session, TrackMetadata(title, artist, duration_s=duration_s))
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("Kugou fetch failed: %s", exc)
        return None
    return list(artifact.lines) if artifact is not None else None
