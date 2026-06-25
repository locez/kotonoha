"""lrclib.net lyrics source (free, open, no auth).

Provides synced LRC (line-timed, no per-word, no translation). Used as a
fallback after Netease. Tries the exact ``/api/get`` (matched by duration) then
``/api/search``.
"""

from __future__ import annotations

import logging

import aiohttp

from ..model import LyricLine
from .lrc_parser import parse_lrc

logger = logging.getLogger(__name__)

GET_URL = "https://lrclib.net/api/get"
SEARCH_URL = "https://lrclib.net/api/search"
HEADERS = {"User-Agent": "kotonoha/0.1 (https://github.com/locez/kotonoha)"}


async def _get(session: aiohttp.ClientSession, title: str, artist: str, duration_s: float | None) -> list[LyricLine]:
    params = {"track_name": title, "artist_name": artist}
    if duration_s:
        params["duration"] = str(int(round(duration_s)))
    async with session.get(GET_URL, params=params, headers=HEADERS) as resp:
        if resp.status != 200:
            return []
        data = await resp.json(content_type=None)
    synced = (data or {}).get("syncedLyrics")
    return parse_lrc(synced) if isinstance(synced, str) and synced.strip() else []


async def _search(session: aiohttp.ClientSession, title: str, artist: str) -> list[LyricLine]:
    params = {"track_name": title, "artist_name": artist}
    async with session.get(SEARCH_URL, params=params, headers=HEADERS) as resp:
        if resp.status != 200:
            return []
        results = await resp.json(content_type=None)
    for item in results or []:
        synced = item.get("syncedLyrics") if isinstance(item, dict) else None
        if isinstance(synced, str) and synced.strip():
            return parse_lrc(synced)
    return []


async def fetch(
    session: aiohttp.ClientSession, title: str, artist: str, duration_s: float | None
) -> list[LyricLine] | None:
    if not title:
        return None
    try:
        lines = await _get(session, title, artist, duration_s)
        if not lines:
            lines = await _search(session, title, artist)
        return lines or None
    except (aiohttp.ClientError, ValueError) as exc:
        logger.warning("lrclib fetch failed: %s", exc)
        return None
