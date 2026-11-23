"""Synchronous SQLite storage for content-addressed lyric translations."""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..i18n import translation_language_display_name
from ..lyrics.cache.storage import PayloadParser
from .models import (
    TranslationCacheDeleteResult,
    TranslationCacheDeleteStatus,
    TranslationCacheEntry,
    TranslationCacheKey,
    TranslationCacheQuery,
    TranslationCacheRecord,
    TranslationResult,
    content_hash,
)

TRANSLATION_PROMPT_VERSION = 1
DEFAULT_MAX_TRANSLATION_ENTRIES = 2000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lyric_translations (
    content_hash TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    translations_json TEXT NOT NULL,
    source_lines_json TEXT NOT NULL DEFAULT '[]',
    timestamps_json TEXT NOT NULL DEFAULT '[]',
    line_count INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    artist TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    last_accessed REAL NOT NULL,
    PRIMARY KEY (content_hash, target_lang)
);
CREATE INDEX IF NOT EXISTS lyric_translations_access
    ON lyric_translations(last_accessed DESC);
"""


class TranslationCacheStorage:
    """Own synchronous SQLite operations for content-addressed lyric translations."""

    def __init__(
        self,
        path: Path,
        *,
        max_entries: int = DEFAULT_MAX_TRANSLATION_ENTRIES,
        lyrics_parsers: Mapping[str, PayloadParser] | None = None,
    ) -> None:
        self._path = path
        self._max_entries = max(1, max_entries)
        self._lyrics_parsers: dict[str, PayloadParser] = dict(lyrics_parsers or {})

    def lookup(
        self,
        digest: str,
        target_language: str,
        expected_line_count: int,
        source_lines: Sequence[str] = (),
        timestamps: Sequence[float] = (),
    ) -> TranslationResult | None:
        """Return validated cached line translations, backfilling missing reference data."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT translations_json, source_lines_json, timestamps_json, line_count, provider, model "
                "FROM lyric_translations "
                "WHERE content_hash = ? AND target_lang = ? AND prompt_version = ?",
                (digest, target_language, TRANSLATION_PROMPT_VERSION),
            ).fetchone()
            if row is None:
                return None
            translations = self._decode_lines(row["translations_json"], expected_count=expected_line_count)
            if translations is None or row["line_count"] != expected_line_count:
                connection.execute(
                    "DELETE FROM lyric_translations WHERE content_hash = ? AND target_lang = ?",
                    (digest, target_language),
                )
                return None
            self._touch_and_backfill(
                connection,
                row,
                digest=digest,
                target_language=target_language,
                expected_count=expected_line_count,
                source_lines=source_lines,
                timestamps=timestamps,
            )
            return TranslationResult(
                translations=translations,
                provider=str(row["provider"]),
                model=str(row["model"]),
                from_cache=True,
            )

    def store(
        self,
        digest: str,
        target_language: str,
        translations: Sequence[str],
        *,
        provider: str,
        model: str,
        source_lines: Sequence[str] = (),
        timestamps: Sequence[float] = (),
        title: str = "",
        artist: str = "",
    ) -> None:
        """Upsert one validated translation set and apply LRU eviction."""
        now = time.time()
        payload = _encode_lines(translations)
        sources_payload = _encode_lines(source_lines)
        timestamps_payload = _encode_timestamps(timestamps, expected_count=len(translations))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO lyric_translations ("
                "content_hash, target_lang, translations_json, source_lines_json, timestamps_json, "
                "line_count, provider, model, prompt_version, title, artist, created_at, last_accessed"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(content_hash, target_lang) DO UPDATE SET "
                "translations_json = excluded.translations_json, "
                "source_lines_json = excluded.source_lines_json, "
                "timestamps_json = excluded.timestamps_json, "
                "line_count = excluded.line_count, "
                "provider = excluded.provider, "
                "model = excluded.model, "
                "prompt_version = excluded.prompt_version, "
                "title = excluded.title, "
                "artist = excluded.artist, "
                "created_at = excluded.created_at, "
                "last_accessed = excluded.last_accessed",
                (
                    digest,
                    target_language,
                    payload,
                    sources_payload,
                    timestamps_payload,
                    len(translations),
                    provider,
                    model,
                    TRANSLATION_PROMPT_VERSION,
                    title,
                    artist,
                    now,
                    now,
                ),
            )
            connection.execute(
                "DELETE FROM lyric_translations WHERE rowid IN ("
                "SELECT rowid FROM lyric_translations "
                "ORDER BY last_accessed DESC LIMIT -1 OFFSET ?)",
                (self._max_entries,),
            )

    def search(self, query: TranslationCacheQuery) -> tuple[TranslationCacheEntry, ...]:
        """Return translation cache metadata in deterministic recent-use order."""
        keyword = query.keyword.strip().casefold()
        with self._connect() as connection:
            if query.target_language is None:
                rows = connection.execute(
                    "SELECT content_hash, target_lang, title, artist, provider, model, "
                    "line_count, created_at, last_accessed FROM lyric_translations "
                    "ORDER BY last_accessed DESC, target_lang ASC, content_hash ASC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT content_hash, target_lang, title, artist, provider, model, "
                    "line_count, created_at, last_accessed FROM lyric_translations "
                    "WHERE target_lang = ? "
                    "ORDER BY last_accessed DESC, target_lang ASC, content_hash ASC",
                    (query.target_language,),
                ).fetchall()
        entries = tuple(self._entry_from_row(row) for row in rows)
        return entries if not keyword else tuple(e for e in entries if _entry_matches(e, keyword))

    def get_record(self, key: TranslationCacheKey) -> TranslationCacheRecord | None:
        """Return one full record, recovering missing original lines/timestamps from sibling lyrics."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash, target_lang, title, artist, provider, model, line_count, "
                "created_at, last_accessed, translations_json, source_lines_json, timestamps_json "
                "FROM lyric_translations WHERE content_hash = ? AND target_lang = ?",
                (key.content_hash, key.target_language),
            ).fetchone()
            if row is None:
                return None
            entry = self._entry_from_row(row)
            translations = self._decode_lines(row["translations_json"], expected_count=entry.line_count)
            if translations is None:
                raise ValueError("cached translation payload is corrupted")
            source_lines = self._decode_lines(row["source_lines_json"], expected_count=entry.line_count) or ()
            timestamps = self._decode_timestamps(row["timestamps_json"], expected_count=entry.line_count) or ()
            if (not source_lines or not timestamps) and self._lyrics_parsers:
                recovered = self._recover_from_lyrics_table(connection, entry)
                if recovered is not None:
                    recovered_sources, recovered_timestamps = recovered
                    if not source_lines:
                        source_lines = recovered_sources
                    if not timestamps:
                        timestamps = recovered_timestamps
                    connection.execute(
                        "UPDATE lyric_translations SET source_lines_json = ?, timestamps_json = ? "
                        "WHERE content_hash = ? AND target_lang = ?",
                        (
                            _encode_lines(source_lines),
                            _encode_timestamps(timestamps, expected_count=entry.line_count),
                            key.content_hash,
                            key.target_language,
                        ),
                    )
        return TranslationCacheRecord(
            entry=entry,
            source_lines=source_lines,
            translations=translations,
            timestamps=timestamps,
        )

    def update_translations(self, key: TranslationCacheKey, translations: Sequence[str]) -> bool:
        """Replace line translations for one existing entry while preserving line alignment."""
        cleaned = [line.strip() for line in translations]
        with self._connect() as connection:
            row = connection.execute(
                "SELECT line_count FROM lyric_translations WHERE content_hash = ? AND target_lang = ?",
                (key.content_hash, key.target_language),
            ).fetchone()
            if row is None:
                return False
            expected = int(row["line_count"])
            if len(cleaned) != expected:
                raise ValueError(f"expected {expected} translation lines, got {len(cleaned)}")
            payload = _encode_lines(cleaned)
            cursor = connection.execute(
                "UPDATE lyric_translations SET translations_json = ?, last_accessed = ? "
                "WHERE content_hash = ? AND target_lang = ?",
                (payload, time.time(), key.content_hash, key.target_language),
            )
            return bool(cursor.rowcount)

    def delete_many(
        self,
        keys: tuple[TranslationCacheKey, ...],
    ) -> tuple[TranslationCacheDeleteResult, ...]:
        """Delete exact translation entries in one SQLite transaction."""
        with self._connect() as connection:
            results: list[TranslationCacheDeleteResult] = []
            for key in keys:
                cursor = connection.execute(
                    "DELETE FROM lyric_translations WHERE content_hash = ? AND target_lang = ?",
                    (key.content_hash, key.target_language),
                )
                status = (
                    TranslationCacheDeleteStatus.DELETED
                    if cursor.rowcount
                    else TranslationCacheDeleteStatus.NOT_FOUND
                )
                results.append(TranslationCacheDeleteResult(key, status))
        return tuple(results)

    def clear(self) -> None:
        """Delete every persisted lyric translation without touching source lyrics."""
        with self._connect() as connection:
            connection.execute("DELETE FROM lyric_translations")

    def count(self) -> int:
        """Return the number of persisted lyric translations."""
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM lyric_translations").fetchone()
        return int(row["count"]) if row is not None else 0

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=3.0)
        connection.row_factory = sqlite3.Row
        connection.executescript(_SCHEMA)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(lyric_translations)")}
        if "source_lines_json" not in columns:
            connection.execute("ALTER TABLE lyric_translations ADD COLUMN source_lines_json TEXT NOT NULL DEFAULT '[]'")
        if "timestamps_json" not in columns:
            connection.execute("ALTER TABLE lyric_translations ADD COLUMN timestamps_json TEXT NOT NULL DEFAULT '[]'")
        return connection

    def _touch_and_backfill(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        digest: str,
        target_language: str,
        expected_count: int,
        source_lines: Sequence[str],
        timestamps: Sequence[float],
    ) -> None:
        updates = ["last_accessed = ?"]
        params: list[object] = [time.time()]
        if (
            self._decode_lines(row["source_lines_json"], expected_count=expected_count) is None
            and len(source_lines) == expected_count
        ):
            updates.append("source_lines_json = ?")
            params.append(_encode_lines(source_lines))
        if (
            self._decode_timestamps(row["timestamps_json"], expected_count=expected_count) is None
            and len(timestamps) == expected_count
            and all(math.isfinite(ts) and ts >= 0.0 for ts in timestamps)
        ):
            updates.append("timestamps_json = ?")
            params.append(_encode_timestamps(timestamps, expected_count=expected_count))
        params.extend((digest, target_language))
        connection.execute(
            f"UPDATE lyric_translations SET {', '.join(updates)} WHERE content_hash = ? AND target_lang = ?",
            params,
        )

    def _recover_from_lyrics_table(
        self,
        connection: sqlite3.Connection,
        entry: TranslationCacheEntry,
    ) -> tuple[tuple[str, ...], tuple[float, ...]] | None:
        """Recover exact original lines and timestamps via SHA-256 match against sibling lyrics."""
        has_lyrics_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'lyrics'"
        ).fetchone()
        if has_lyrics_table is None:
            return None
        rows = connection.execute(
            "SELECT provider, payload_json FROM lyrics ORDER BY (title = ?) DESC, last_accessed DESC",
            (entry.title,),
        ).fetchall()
        for row in rows:
            parser = self._lyrics_parsers.get(str(row["provider"]))
            if parser is None:
                continue
            try:
                raw_payload = json.loads(row["payload_json"])
                if not isinstance(raw_payload, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in raw_payload.items()
                ):
                    continue
                lines = parser(raw_payload)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if len(lines) != entry.line_count:
                continue
            texts = tuple(line.text for line in lines)
            if content_hash(texts) == entry.key.content_hash:
                return texts, tuple(line.start for line in lines)
        return None

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> TranslationCacheEntry:
        digest = row["content_hash"]
        target_lang = row["target_lang"]
        title = row["title"]
        artist = row["artist"]
        provider = row["provider"]
        model = row["model"]
        line_count = row["line_count"]
        created_at = row["created_at"]
        last_accessed = row["last_accessed"]
        if not all(isinstance(v, str) for v in (digest, target_lang, title, artist, provider, model)):
            raise TypeError("translation cache metadata contains a non-string value")
        if not isinstance(line_count, int) or isinstance(line_count, bool):
            raise TypeError("translation cache line_count is not an integer")
        if not isinstance(created_at, (int, float)) or isinstance(created_at, bool):
            raise TypeError("translation cache created_at is not numeric")
        if not isinstance(last_accessed, (int, float)) or isinstance(last_accessed, bool):
            raise TypeError("translation cache last_accessed is not numeric")
        return TranslationCacheEntry(
            key=TranslationCacheKey(digest, target_lang),
            title=title,
            artist=artist,
            provider=provider,
            model=model,
            line_count=line_count,
            created_at=float(created_at),
            last_accessed=float(last_accessed),
        )

    @staticmethod
    def _decode_lines(raw_json: object, *, expected_count: int) -> tuple[str, ...] | None:
        if not isinstance(raw_json, str):
            return None
        try:
            decoded = json.loads(raw_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(decoded, list) or len(decoded) != expected_count:
            return None
        if not all(isinstance(item, str) for item in decoded):
            return None
        return tuple(decoded)

    @staticmethod
    def _decode_timestamps(raw_json: object, *, expected_count: int) -> tuple[float, ...] | None:
        if not isinstance(raw_json, str):
            return None
        try:
            decoded = json.loads(raw_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(decoded, list) or len(decoded) != expected_count:
            return None
        result: list[float] = []
        for item in decoded:
            if not isinstance(item, (int, float)) or isinstance(item, bool):
                return None
            value = float(item)
            if not math.isfinite(value) or value < 0.0:
                return None
            result.append(value)
        return tuple(result)


def _encode_lines(lines: Sequence[str]) -> str:
    return json.dumps(list(lines), ensure_ascii=False, separators=(",", ":"))


def _encode_timestamps(timestamps: Sequence[float], *, expected_count: int) -> str:
    if len(timestamps) != expected_count or not all(math.isfinite(ts) and ts >= 0.0 for ts in timestamps):
        return "[]"
    return json.dumps([round(float(ts), 3) for ts in timestamps], separators=(",", ":"))


def _entry_matches(entry: TranslationCacheEntry, keyword: str) -> bool:
    fields = (
        entry.title,
        entry.artist,
        entry.key.target_language,
        translation_language_display_name(entry.key.target_language),
        entry.provider,
        entry.model,
        entry.key.content_hash,
    )
    return any(keyword in value.casefold() for value in fields)


__all__ = [
    "DEFAULT_MAX_TRANSLATION_ENTRIES",
    "TRANSLATION_PROMPT_VERSION",
    "TranslationCacheStorage",
]
