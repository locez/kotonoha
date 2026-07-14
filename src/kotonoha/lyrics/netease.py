"""Netease Cloud Music timed-lyrics provider."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

import aiohttp

from ..model import LyricLine
from .artifact import LyricsArtifact
from .lrc_parser import merge_translation, parse_lrc
from .match import Candidate, MatchConfidence, MatchEvidence, TrackMetadata, best_match, query_variants
from .yrc_parser import parse_yrc

logger = logging.getLogger(__name__)

SEARCH_URL = "https://music.163.com/api/search/get"
LYRIC_URL = "https://music.163.com/api/song/lyric/v1"
HEADERS = {"Referer": "https://music.163.com", "User-Agent": "Mozilla/5.0"}
# Netease answers quickly; a short per-request budget keeps the fallback chain
# moving on to the next source promptly when it does not.
TIMEOUT = aiohttp.ClientTimeout(total=6.0, connect=3.0)


async def search(session: aiohttp.ClientSession, query: str, limit: int = 10) -> list[Candidate]:
    params = {"s": query, "type": "1", "limit": str(limit)}
    async with session.get(SEARCH_URL, params=params, headers=HEADERS, timeout=TIMEOUT) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)
    if not isinstance(data, dict):
        raise ValueError("Netease search response is not an object")
    result = data.get("result")
    songs = result.get("songs", []) if isinstance(result, dict) else []
    if not isinstance(songs, list):
        raise ValueError("Netease search songs is not a list")

    candidates: list[Candidate] = []
    for song in songs:
        if not isinstance(song, dict) or song.get("id") is None:
            continue
        artists = song.get("artists")
        artist_names = (
            [str(item.get("name", "")) for item in artists if isinstance(item, dict)]
            if isinstance(artists, list)
            else []
        )
        album_data = song.get("album")
        album = str(album_data.get("name", "")) if isinstance(album_data, dict) else ""
        duration = song.get("duration")
        candidates.append(
            Candidate(
                song_id=str(song["id"]),
                title=str(song.get("name", "")),
                artist=" / ".join(name for name in artist_names if name),
                duration_s=duration / 1000.0 if isinstance(duration, (int, float)) else None,
                album=album,
                aliases=_song_aliases(song),
            )
        )
    return candidates


def _song_aliases(song: Mapping[str, object]) -> tuple[str, ...]:
    """Alternate names Netease lists for a song: ``alias`` (same-language akas)
    and ``transNames`` (translated titles, e.g. an English name for a CJK song),
    deduplicated and non-empty."""
    names: list[str] = []
    for key in ("alias", "transNames"):
        value = song.get(key)
        if isinstance(value, list):
            names.extend(str(item) for item in value if isinstance(item, str) and item.strip())
    return tuple(dict.fromkeys(names))


def lyric_text(data: Mapping[str, object], key: str) -> str:
    block = data.get(key)
    if not isinstance(block, dict):
        return ""
    lyric = block.get("lyric")
    return lyric if isinstance(lyric, str) else ""


async def fetch_payload(session: aiohttp.ClientSession, song_id: str) -> dict[str, str]:
    params = {"id": song_id, "lv": "1", "kv": "0", "tv": "1", "yv": "1"}
    async with session.get(LYRIC_URL, params=params, headers=HEADERS, timeout=TIMEOUT) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)
    if not isinstance(data, dict):
        raise ValueError("Netease lyric response is not an object")
    return {
        "yrc": lyric_text(data, "yrc"),
        "lrc": lyric_text(data, "lrc"),
        "tlyric": lyric_text(data, "tlyric"),
    }


def parse_payload(payload: Mapping[str, str]) -> tuple[LyricLine, ...]:
    yrc_lines = parse_yrc(payload.get("yrc", ""))
    base = yrc_lines or parse_lrc(payload.get("lrc", ""))
    translation = parse_lrc(payload.get("tlyric", ""))
    return tuple(merge_translation(base, translation) if translation else base)


async def _artifact_for_match(
    session: aiohttp.ClientSession,
    match: MatchEvidence,
) -> LyricsArtifact | None:
    payload = await fetch_payload(session, match.candidate.song_id)
    lines = parse_payload(payload)
    if not lines:
        logger.debug("Netease song %s matched but had no timed lyrics", match.candidate.song_id)
        return None
    candidate = match.candidate
    return LyricsArtifact(
        provider="netease",
        provider_song_id=candidate.song_id,
        title=candidate.title,
        artist=candidate.artist,
        album=candidate.album,
        duration_s=candidate.duration_s,
        payload=payload,
        lines=lines,
        confidence=match.confidence,
    )


async def fetch_artifact(
    session: aiohttp.ClientSession,
    track: TrackMetadata,
) -> LyricsArtifact | None:
    medium_matches: dict[str, MatchEvidence] = {}
    attempted_song_ids: set[str] = set()
    for query in query_variants(track):
        match = best_match(await search(session, query), track)
        if match is None:
            continue
        song_id = match.candidate.song_id
        if match.confidence is MatchConfidence.HIGH:
            if song_id in attempted_song_ids:
                continue
            attempted_song_ids.add(song_id)
            artifact = await _artifact_for_match(session, match)
            if artifact is not None:
                return artifact
        else:
            medium_matches[song_id] = match

    for song_id, match in medium_matches.items():
        if song_id in attempted_song_ids:
            continue
        artifact = await _artifact_for_match(session, match)
        if artifact is not None:
            return artifact
    return None


async def fetch_lyrics(session: aiohttp.ClientSession, song_id: str) -> list[LyricLine]:
    return list(parse_payload(await fetch_payload(session, song_id)))


async def fetch(
    session: aiohttp.ClientSession,
    title: str,
    artist: str,
    duration_s: float | None,
) -> list[LyricLine] | None:
    """Compatibility wrapper used until all callers consume artifacts."""
    try:
        artifact = await fetch_artifact(session, TrackMetadata(title, artist, duration_s=duration_s))
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning("Netease fetch failed: %s", exc)
        return None
    return list(artifact.lines) if artifact is not None else None
