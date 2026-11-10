"""The structured LRCLIB field must reach automatic, manual, and cached lyrics."""

import json
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from types import TracebackType

import pytest

from kotonoha.lyrics import lrclib
from kotonoha.lyrics.cache.models import LyricsCacheMode
from kotonoha.lyrics.cache.storage import LyricsCacheStorage
from kotonoha.lyrics.match import TrackMetadata
from kotonoha.lyrics.search import LyricsSearchResult
from kotonoha.strings import Translator
from kotonoha.ui.settings.lyrics_search_model import LyricsSearchTableModel


class _Body:
    """A finite byte stream with the same bounded reads as an HTTP response."""

    def __init__(self, data: object) -> None:
        self._data: bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._cursor: int = 0

    async def read(self, size: int = -1, /) -> bytes:
        """Consume at most the requested bytes, then report EOF."""
        end = len(self._data) if size < 0 else self._cursor + size
        chunk = self._data[self._cursor:end]
        self._cursor += len(chunk)
        return chunk


class _Response(AbstractAsyncContextManager["_Response"]):
    """A successful JSON response scoped to the request's async context."""

    def __init__(self, data: object) -> None:
        self.status: int = 200
        self.content: _Body = _Body(data)

    def raise_for_status(self) -> None:
        """The fixture represents HTTP 200, which does not raise."""

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None,
        traceback: TracebackType | None, /,
    ) -> None:
        return None


class _Session:
    """Serve the distinct exact/search API envelopes without network access."""

    def __init__(self, record: dict[str, object]) -> None:
        self._record: dict[str, object] = record

    def get(
        self, url: str, *, params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None, timeout: object | None = None,
    ) -> _Response:
        """Return fresh streams so concurrent exact and search reads are independent."""
        assert url in {lrclib.GET_URL, lrclib.SEARCH_URL}
        return _Response([self._record] if url == lrclib.SEARCH_URL else self._record)

    def post(
        self, url: str, *, json: object | None = None, params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None, timeout: object | None = None,
    ) -> _Response:
        """LRCLIB lookup must not issue a write request."""
        raise AssertionError("unexpected POST")

    async def close(self) -> None:
        """The in-memory session owns no transport resources."""


@pytest.mark.parametrize("legacy", [None, "[01:01.35]legacy line"])
async def test_word_timings_survive_exact_manual_and_cache_paths(tmp_path: Path, legacy: str | None) -> None:
    raw = (Path(__file__).parent / "fixtures" / "ana_indi_haneen.lyricsfile.yaml").read_text(encoding="utf-8")
    session = _Session({
        "id": 1758054, "trackName": "Ana Indi Haneen", "artistName": "Fairuz", "albumName": "Wahdon",
        "duration": 356.0, "hasWordSync": True, "lyricsfile": raw, "syncedLyrics": legacy,
    })
    track = TrackMetadata("Ana Indi Haneen", "Fairuz", "Wahdon", 356.0)
    try:
        exact = await lrclib.get_exact(session, track)
        assert exact is not None and exact.lyricsfile == raw
        manual = await lrclib.search_artifacts(session, track)
        automatic = await lrclib.fetch_artifact(session, track)
        assert automatic is not None
        assert manual == (automatic,)
        assert len(automatic.lines) == 28
        assert all(line.has_word_timing for line in automatic.lines)
        assert automatic.payload["lyricsfile"] == raw

        path = tmp_path / "lyrics.sqlite3"
        LyricsCacheStorage(path, max_entries=10).upsert(automatic, LyricsCacheMode.AUTO)
        restored = LyricsCacheStorage(path, max_entries=10).lookup("lrclib", track, lrclib.parse_payload)
        assert restored is not None
        assert restored.artifact.lines == automatic.lines
        assert restored.artifact.payload["lyricsfile"] == raw
    finally:
        await session.close()


@pytest.mark.parametrize(("structured", "legacy", "label", "format_id"), [
    (True, "[00:01.00]old", "逐字歌词", "lyricsfile"),
    (False, "[00:01.00]old", "逐行歌词", "lyricsfile"),
    (None, "[00:01.00]<00:01.00>hello<00:02.00>", "逐字歌词", "lrc"),
    (None, "[00:01.00]hello", "逐行歌词", "lrc"),
])
async def test_search_table_reports_parsed_timing_and_selected_format(
    structured: bool | None, legacy: str, label: str, format_id: str,
) -> None:
    """LRCLIB is not inherently line-timed; YAML can contain either granularity."""
    raw = "version: '1.0'\nmetadata: {title: Song, artist: Artist}\nlines:\n"
    raw += "- text: hello\n  start_ms: 1000\n  end_ms: 2000\n"
    if structured is True:
        raw += "  words: [{text: hello, start_ms: 1000}]\n"
    elif structured is None:
        raw = "version: '2.0'"  # Unsupported structure must identify the actual LRC fallback.
    session = _Session({
        "id": 1, "trackName": "Song", "artistName": "Artist", "albumName": "",
        "duration": 180.0, "lyricsfile": raw, "syncedLyrics": legacy,
    })
    try:
        artifacts = await lrclib.search_artifacts(session, TrackMetadata("Song", "Artist", duration_s=180.0))
        results = tuple(LyricsSearchResult.from_artifact(artifact) for artifact in artifacts)
        model = LyricsSearchTableModel(Translator("zh-Hans"), {})
        model.set_results(results)
        assert model.data(model.index(0, 5)) == label
        assert results[0].version.format_id == format_id
    finally:
        await session.close()
