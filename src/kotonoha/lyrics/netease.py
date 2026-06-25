"""Netease Cloud Music lyrics source (no cookie, no encryption required).

The public ``api/search/get`` + ``api/song/lyric/v1`` endpoints return, for many
songs, word-timed ``yrc`` lyrics plus a standard ``lrc`` fallback and ``tlyric``
translation — all without authentication. We search by "title artist", pick the
best candidate by duration (see match.py), then fetch + parse the lyrics.
"""

from __future__ import annotations

import logging

import aiohttp

from ..model import LyricLine
from .lrc_parser import merge_translation, parse_lrc
from .match import Candidate, best_match
from .yrc_parser import parse_yrc

logger = logging.getLogger(__name__)

SEARCH_URL = "https://music.163.com/api/search/get"
LYRIC_URL = "https://music.163.com/api/song/lyric/v1"
HEADERS = {"Referer": "https://music.163.com", "User-Agent": "Mozilla/5.0"}


async def search(session: aiohttp.ClientSession, query: str, limit: int = 10) -> list[Candidate]:
    params = {"s": query, "type": "1", "limit": str(limit)}
    async with session.get(SEARCH_URL, params=params, headers=HEADERS) as resp:
        data = await resp.json(content_type=None)
    songs = ((data or {}).get("result") or {}).get("songs") or []
    candidates: list[Candidate] = []
    for song in songs:
        duration = song.get("duration")
        candidates.append(
            Candidate(
                song_id=str(song.get("id")),
                title=str(song.get("name", "")),
                artist=" / ".join(str(a.get("name", "")) for a in (song.get("artists") or [])),
                duration_s=duration / 1000.0 if isinstance(duration, (int, float)) else None,
            )
        )
    return candidates


async def fetch_lyrics(session: aiohttp.ClientSession, song_id: str) -> list[LyricLine]:
    params = {"id": str(song_id), "lv": "1", "kv": "0", "tv": "1", "yv": "1"}
    async with session.get(LYRIC_URL, params=params, headers=HEADERS) as resp:
        data = await resp.json(content_type=None)
    yrc = ((data or {}).get("yrc") or {}).get("lyric") or ""
    lrc = ((data or {}).get("lrc") or {}).get("lyric") or ""
    tlyric = ((data or {}).get("tlyric") or {}).get("lyric") or ""

    base = parse_yrc(yrc) if yrc.strip() else parse_lrc(lrc)
    if tlyric.strip():
        base = merge_translation(base, parse_lrc(tlyric))
    return base


async def fetch(
    session: aiohttp.ClientSession, title: str, artist: str, duration_s: float | None
) -> list[LyricLine] | None:
    """Search + match + fetch lyrics for a now-playing track. None if no good match."""
    query = f"{title} {artist}".strip()
    if not query:
        return None
    try:
        candidates = await search(session, query)
        best = best_match(candidates, title, artist, duration_s)
        if best is None:
            logger.info("Netease: no confident match for %r / %r", title, artist)
            return None
        lines = await fetch_lyrics(session, best.song_id)
        return lines or None
    except (aiohttp.ClientError, ValueError) as exc:
        logger.warning("Netease fetch failed: %s", exc)
        return None
