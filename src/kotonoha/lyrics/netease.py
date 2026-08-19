"""Netease Cloud Music timed-lyrics provider."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator, Mapping

import aiohttp

from ..model import LyricLine
from .artifact import LyricsArtifact
from .lrc_parser import merge_translation, parse_lrc
from .match import (
    Candidate,
    MatchConfidence,
    MatchEvidence,
    QueryVariant,
    TrackMetadata,
    query_variants,
    ranked_matches,
)
from .payload import read_json_capped
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
        data = await read_json_capped(response, "NetEase")
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
        data = await read_json_capped(response, "NetEase")
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
    *,
    fuzzy: bool = False,
) -> LyricsArtifact | None:
    # A single budget for lyric downloads across HIGH and lower-confidence
    # candidates, so a popular title with a pile of UGC re-uploads (all scoring the
    # same) can't fan out into dozens of separate 6s-timeout fetches.
    max_fetches = 6
    attempted_song_ids: set[str] = set()

    async def try_fetch(match: MatchEvidence) -> LyricsArtifact | None:
        song_id = match.candidate.song_id
        if song_id in attempted_song_ids or len(attempted_song_ids) >= max_fetches:
            return None
        attempted_song_ids.add(song_id)
        return await _artifact_for_match(session, match)

    medium_matches: dict[str, MatchEvidence] = {}
    for batch in _ladder_batches(query_variants(track, fuzzy=fuzzy)):
        for candidates in await _search_batch(session, batch):
            for match in ranked_matches(candidates, track, fuzzy=fuzzy):
                if match.confidence is MatchConfidence.HIGH:
                    artifact = await try_fetch(match)  # a HIGH is almost certainly the song
                    if artifact is not None:
                        return artifact
                else:
                    medium_matches.setdefault(match.candidate.song_id, match)

    # Best-ranked mediums next: try several so a lyric-less top pick doesn't hide a
    # good one just below it. Rank by title/artist evidence, then closest duration.
    def medium_key(match: MatchEvidence) -> tuple[bool, bool, bool, float]:
        delta = match.duration_delta
        return (match.title_exact, match.artist_identity, match.artist_evidence,
                -(delta if delta is not None else 1e9))

    for match in sorted(medium_matches.values(), key=medium_key, reverse=True):
        artifact = await try_fetch(match)
        if artifact is not None:
            return artifact
    return None


#: How many readings are searched at once once the reported one has missed. The
#: ladder was walked a rung at a time, so a title needing all of it waited for nine
#: round trips in a row — 3.55s measured against 0.4s for one.
_LADDER_BATCH = 4


def _ladder_batches(variants: tuple[QueryVariant, ...]) -> Iterator[tuple[QueryVariant, ...]]:
    """The ladder in the order it must be judged, a few rungs at a time.

    The reported reading goes alone: it is right most of the time, and keeping it a
    single request is what stops the common case paying for the salvage. Batching the
    rest still lets a hit end the walk, so a rung nobody needed is never sent.
    """
    if not variants:
        return
    yield variants[:1]
    for start in range(1, len(variants), _LADDER_BATCH):
        yield variants[start : start + _LADDER_BATCH]


async def _search_batch(
    session: aiohttp.ClientSession, variants: tuple[QueryVariant, ...]
) -> list[list[Candidate]]:
    """Search a batch concurrently, keeping the results in the ladder's order.

    A rung that fails is dropped rather than abandoning the batch: the others may
    still hold the song. When every rung in the batch failed the first error is
    raised, so a provider that is simply down still reports as much.
    """
    results = await asyncio.gather(
        *(search(session, variant.text) for variant in variants), return_exceptions=True
    )
    pages = [page for page in results if not isinstance(page, BaseException)]
    if not pages:
        failures = [page for page in results if isinstance(page, BaseException)]
        if failures:
            raise failures[0]
    return pages


async def fetch_lyrics(session: aiohttp.ClientSession, song_id: str) -> list[LyricLine]:
    return list(parse_payload(await fetch_payload(session, song_id)))
