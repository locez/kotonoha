"""Provider-scoped persistent cache for validated lyric artifacts."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from ..model import LyricLine
from .artifact import LyricsArtifact
from .match import (
    NORMALIZER_VERSION,
    Candidate,
    MatchConfidence,
    MatchEvidence,
    TrackMetadata,
    evaluate_match,
)

CACHE_SCHEMA_VERSION = 1
DEFAULT_MAX_ENTRIES = 1000

PayloadParser = Callable[[Mapping[str, str]], tuple[LyricLine, ...]]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lyrics (
    provider TEXT NOT NULL,
    provider_song_id TEXT NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL,
    duration_s REAL,
    payload_json TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    last_accessed REAL NOT NULL,
    schema_version INTEGER NOT NULL,
    normalizer_version INTEGER NOT NULL,
    PRIMARY KEY (provider, provider_song_id)
);
CREATE INDEX IF NOT EXISTS lyrics_provider_access
    ON lyrics(provider, last_accessed DESC);
"""


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "kotonoha" / "lyrics.sqlite3"


class LyricsCache:
    def __init__(self, path: Path | None = None, *, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._path = path or cache_path()
        self._max_entries = max(1, max_entries)

    async def lookup(
        self,
        provider: str,
        track: TrackMetadata,
        parser: PayloadParser,
    ) -> LyricsArtifact | None:
        return await asyncio.to_thread(self._lookup_sync, provider, track, parser)

    async def store(self, artifact: LyricsArtifact) -> None:
        if artifact.confidence is MatchConfidence.HIGH:
            await asyncio.to_thread(self._store_sync, artifact)

    async def clear(self) -> None:
        await asyncio.to_thread(self._clear_sync)

    async def count(self) -> int:
        return await asyncio.to_thread(self._count_sync)

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=3.0)
        connection.row_factory = sqlite3.Row
        connection.executescript(_SCHEMA)
        return connection

    def _lookup_sync(
        self,
        provider: str,
        track: TrackMetadata,
        parser: PayloadParser,
    ) -> LyricsArtifact | None:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM lyrics "
                "WHERE provider = ? AND schema_version = ? AND normalizer_version = ?",
                (provider, CACHE_SCHEMA_VERSION, NORMALIZER_VERSION),
            ).fetchall()
            matches: list[tuple[MatchEvidence, sqlite3.Row]] = []
            for row in rows:
                candidate = Candidate(
                    song_id=row["provider_song_id"],
                    title=row["title"],
                    artist=row["artist"],
                    duration_s=row["duration_s"],
                    album=row["album"],
                )
                evidence = evaluate_match(candidate, track)
                if evidence.confidence is MatchConfidence.HIGH:
                    matches.append((evidence, row))
            if not matches:
                return None

            evidence, row = max(matches, key=lambda item: self._match_sort_key(item[0]))
            try:
                raw_payload = json.loads(row["payload_json"])
                if not isinstance(raw_payload, dict) or not all(
                    isinstance(key, str) and isinstance(value, str) for key, value in raw_payload.items()
                ):
                    raise TypeError("cached payload is not a string map")
                payload: dict[str, str] = raw_payload
                lines = parser(payload)
                if not lines:
                    raise ValueError("cached payload has no timed lyrics")
            except (json.JSONDecodeError, TypeError, ValueError):
                connection.execute(
                    "DELETE FROM lyrics WHERE provider = ? AND provider_song_id = ?",
                    (provider, row["provider_song_id"]),
                )
                return None

            connection.execute(
                "UPDATE lyrics SET last_accessed = ? WHERE provider = ? AND provider_song_id = ?",
                (time.time(), provider, row["provider_song_id"]),
            )
            return LyricsArtifact(
                provider=provider,
                provider_song_id=row["provider_song_id"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
                duration_s=row["duration_s"],
                payload=payload,
                lines=lines,
                confidence=evidence.confidence,
            )

    @staticmethod
    def _match_sort_key(evidence: MatchEvidence) -> tuple[bool, bool, bool, float]:
        duration_rank = -evidence.duration_delta if evidence.duration_delta is not None else float("-inf")
        return evidence.title_exact, evidence.artist_overlap, evidence.album_match, duration_rank

    def _store_sync(self, artifact: LyricsArtifact) -> None:
        now = time.time()
        payload_json = json.dumps(artifact.payload, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO lyrics ("
                "provider, provider_song_id, title, artist, album, duration_s, payload_json, "
                "fetched_at, last_accessed, schema_version, normalizer_version"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(provider, provider_song_id) DO UPDATE SET "
                "title = excluded.title, artist = excluded.artist, album = excluded.album, "
                "duration_s = excluded.duration_s, payload_json = excluded.payload_json, "
                "fetched_at = excluded.fetched_at, last_accessed = excluded.last_accessed, "
                "schema_version = excluded.schema_version, normalizer_version = excluded.normalizer_version",
                (
                    artifact.provider,
                    artifact.provider_song_id,
                    artifact.title,
                    artifact.artist,
                    artifact.album,
                    artifact.duration_s,
                    payload_json,
                    now,
                    now,
                    CACHE_SCHEMA_VERSION,
                    NORMALIZER_VERSION,
                ),
            )
            connection.execute(
                "DELETE FROM lyrics WHERE rowid IN ("
                "SELECT rowid FROM lyrics ORDER BY last_accessed DESC LIMIT -1 OFFSET ?)",
                (self._max_entries,),
            )

    def _clear_sync(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM lyrics")

    def _count_sync(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM lyrics").fetchone()
        return int(row["count"]) if row is not None else 0
