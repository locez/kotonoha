"""Typed transformations for the public AMLL TTML DB JSONL catalog.

The upstream index contains historical submissions, oldest first. Raw filenames
identify immutable submissions; platform IDs link revisions of the same song.
All helpers here are stateless parsing, validation or matching transformations.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .hanzi_fold import fold_to_simplified
from .match import Candidate, MatchConfidence, TrackMetadata, evaluate_match, ranked_matches
from .title_grammar import normalize

MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_INDEX_RECORDS = 20000
_FILE = re.compile(r"[0-9]{10,16}-[A-Za-z0-9,_-]{1,100}-[A-Za-z0-9]{8}\.ttml", re.ASCII)
_PLATFORMS = {"ncmMusicId": "netease", "qqMusicId": "qqmusic", "appleMusicId": "apple-music", "spotifyId": "spotify"}
_NUMERIC_ID = re.compile(r"[0-9]{1,20}", re.ASCII)
_TEXT_ID = re.compile(r"[A-Za-z0-9]{1,64}", re.ASCII)


@dataclass(frozen=True)
class AmllSongId:
    """A platform-scoped ID, including QQ song mids rather than numeric song IDs."""

    provider: str
    value: str


@dataclass(frozen=True)
class AmllRecord:
    """One immutable TTML submission and the song identities it applies to."""

    candidate: Candidate
    identities: frozenset[AmllSongId]


@dataclass(frozen=True)
class AmllMatch:
    """A catalog submission paired with the shared matcher's confidence."""

    record: AmllRecord
    confidence: MatchConfidence


def song_reference(provider: str, value: str) -> AmllSongId | None:
    """Validate an external song ID before considering it for exact lookup."""
    if provider not in _PLATFORMS.values():
        return None
    pattern = _NUMERIC_ID if provider in {"netease", "apple-music"} else _TEXT_ID
    return AmllSongId(provider, value) if pattern.fullmatch(value) is not None else None


def _record(value: object) -> AmllRecord | None:
    """Normalize one JSONL row; no external filename can become a URL path."""
    if not isinstance(value, dict):
        return None
    file_name = value.get("rawLyricFile")
    if not isinstance(file_name, str) or _FILE.fullmatch(file_name) is None:
        return None
    metadata = value.get("metadata")
    if not isinstance(metadata, list) or len(metadata) > 128:
        return None
    fields: dict[str, tuple[str, ...]] = {}
    for item in metadata:
        if not isinstance(item, list) or len(item) != 2:
            return None
        key, values = item
        if not isinstance(key, str) or not isinstance(values, list) or len(values) > 64:
            return None
        if not all(isinstance(text, str) and len(text) <= 2048 for text in values):
            return None
        fields[key] = tuple(text.strip() for text in values if isinstance(text, str) and text.strip())
    titles = fields.get("musicName", ())
    if not titles:
        return None
    identities = frozenset(
        identity for key, provider in _PLATFORMS.items() for value in fields.get(key, ())
        if (identity := song_reference(provider, value)) is not None
    )
    if not identities:
        return None
    albums = fields.get("album", ())
    return AmllRecord(
        Candidate(file_name, titles[0], " / ".join(fields.get("artists", ())), None,
                  album=albums[0] if albums else "", aliases=titles[1:]),
        identities,
    )


def parse_index(body: bytes) -> tuple[AmllRecord, ...]:
    """Decode a bounded index, skipping unusable rows and preferring recent revisions.

    Malformed JSON or a wholly unusable index raises ValueError, so an upstream
    error page cannot be cached as an empty catalog. A lyric end is never used as
    song duration: the upstream metadata does not promise an audio duration.
    """
    if len(body) > MAX_INDEX_BYTES:
        raise ValueError("AMLL index exceeds its byte limit")
    rows = body.splitlines()
    if len(rows) > MAX_INDEX_RECORDS:
        raise ValueError("AMLL index exceeds its record limit")
    records: dict[str, AmllRecord] = {}
    for row in rows:
        if not row.strip():
            continue
        try:
            raw = json.loads(row)
        except (ValueError, RecursionError) as exc:
            # Older Python JSON decoders reject deep input with RecursionError.
            raise ValueError("AMLL index is not valid JSONL") from exc
        record = _record(raw)
        if record is not None:
            records[record.candidate.song_id] = record
    if not records:
        raise ValueError("AMLL index has no valid song records")
    return tuple(sorted(
        records.values(), key=lambda record: int(record.candidate.song_id.split("-", 1)[0]), reverse=True,
    ))


def _contains(query: str, values: tuple[str, ...]) -> bool:
    """Match manual-search keywords using the existing title and script normalization."""
    needle = normalize(fold_to_simplified(query))
    return not needle or any(needle in normalize(fold_to_simplified(value)) for value in values)


def match_records(
    records: tuple[AmllRecord, ...], track: TrackMetadata, *, fuzzy: bool, manual: bool = False,
) -> tuple[AmllMatch, ...]:
    """Use shared automatic identity gates, or explicit manual-search keywords.

    Within equal evidence, the newest submission wins. Revisions sharing a
    platform song ID are shown once; different recordings remain separate.
    """
    if manual:
        selected = [record for record in records if (
            _contains(track.title, (record.candidate.title, *record.candidate.aliases))
            and _contains(track.artist, (record.candidate.artist,))
            and _contains(track.album, (record.candidate.album,))
        )]
        matches = [AmllMatch(record, evaluate_match(record.candidate, track).confidence) for record in selected]
        matches.sort(key=lambda match: (match.confidence is MatchConfidence.HIGH,
                                       match.confidence is MatchConfidence.MEDIUM), reverse=True)
    else:
        by_id = {record.candidate.song_id: record for record in records}
        matches = [AmllMatch(by_id[evidence.candidate.song_id], evidence.confidence) for evidence in ranked_matches(
            [record.candidate for record in records], track, fuzzy=fuzzy,
        )]
    seen: set[AmllSongId] = set()
    unique: list[AmllMatch] = []
    for match in matches:
        if seen & match.record.identities:
            continue
        seen.update(match.record.identities)
        unique.append(match)
    return tuple(unique)


__all__ = ["AmllMatch", "AmllRecord", "AmllSongId", "MAX_INDEX_BYTES", "match_records", "parse_index", "song_reference"]
