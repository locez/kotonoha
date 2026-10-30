"""AMLL public HTTP, matching, caching, and cancellation contracts."""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import pytest
from test_lyrics_resolver import FakeCache, FakeGate, artifact, catalog_for

from kotonoha.async_worker import BlockingCallRunner
from kotonoha.config import Config, load_config, save_config
from kotonoha.lyrics.amll import INDEX_URL, RAW_URL, AmllLyricsSource, parse_payload
from kotonoha.lyrics.amll_catalog import MAX_INDEX_BYTES, match_records, parse_index
from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.cache import LyricsCache
from kotonoha.lyrics.catalog import LyricsSourceCatalog
from kotonoha.lyrics.hint import LyricsHint
from kotonoha.lyrics.http import LyricsHttpError, LyricsResponse, LyricsSession
from kotonoha.lyrics.live_source import LiveLyricsSource
from kotonoha.lyrics.match import MatchConfidence, TrackMetadata
from kotonoha.lyrics.models import LyricsCacheState
from kotonoha.lyrics.network_sources import NetworkLyricsSource
from kotonoha.lyrics.resolver import LyricsResolver
from kotonoha.lyrics.search import LyricsSearchResult, LyricsTiming
from kotonoha.lyrics.sources import EmbeddedLyricsSource, LocalLyricsSource, SidecarLyricsSource

OLD_FILE = "1689087424000-39523898-47876155.ttml"
NEW_FILE = "1792065160765-103079805-x67ItPp4.ttml"
OTHER_FILE = "1791890273362-103079805-9zShDBSv.ttml"
TRACK = TrackMetadata("Song", "Artist", "Album", 180.0)
WORDS = (
    '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata">'
    '<body><div><p begin="1s" end="3s"><span begin="1s" end="2s">Hello</span> '
    '<span begin="2s" end="3s">world</span><span ttm:role="x-translation">你好</span>'
    '</p></div></body></tt>'
)


def row(
    file: str = NEW_FILE, title: str = "Song", artist: str = "Artist", song_id: str = "42",
    *, aliases: tuple[str, ...] = (),
) -> bytes:
    """Encode the documented JSONL metadata shape without relying on implementation."""
    return json.dumps({"rawLyricFile": file, "metadata": [
        ["musicName", [title, *aliases]], ["artists", [artist]], ["album", ["Album"]],
        ["ncmMusicId", [song_id]], ["qqMusicId", ["mid" + song_id]],
    ]}, ensure_ascii=False).encode() + b"\n"


@dataclass
class Body:
    data: bytes
    offset: int = 0

    async def read(self, size: int = -1, /) -> bytes:
        end = len(self.data) if size < 0 else self.offset + size
        chunk = self.data[self.offset:end]
        self.offset += len(chunk)
        return chunk


class Response:
    def __init__(self, data: bytes, status: int = 200) -> None:
        self.status: int = status
        self.content: Body = Body(data)
        self.closed: bool = False

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise LyricsHttpError(f"HTTP {self.status}")

    async def __aenter__(self) -> LyricsResponse:
        return self

    async def __aexit__(
        self, kind: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        self.closed = True


class Session:
    def __init__(self, index: bytes, files: Mapping[str, bytes] | None = None) -> None:
        self.index: bytes = index
        self.files: Mapping[str, bytes] = {NEW_FILE: WORDS.encode()} if files is None else files
        self.urls: list[str] = []
        self.responses: list[Response] = []
        self.index_started: asyncio.Event = asyncio.Event()
        self.index_release: asyncio.Event = asyncio.Event()
        self.index_release.set()
        self.index_failure: Exception | None = None
        self.files_started: asyncio.Event = asyncio.Event()
        self.files_release: asyncio.Event = asyncio.Event()
        self.files_release.set()
        self.open_files: int = 0

    @asynccontextmanager
    async def get(
        self, url: str, *, params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None, timeout: object | None = None,
    ) -> AsyncIterator[LyricsResponse]:
        self.urls.append(url)
        if url == INDEX_URL:
            self.index_started.set()
            await self.index_release.wait()
            if self.index_failure is not None:
                raise self.index_failure
            response = Response(self.index)
        else:
            file = url.removeprefix(RAW_URL)
            if not url.startswith(RAW_URL):
                raise AssertionError(f"unexpected URL {url}")
            response = Response(self.files.get(file, b""), 200 if file in self.files else 404)
        self.responses.append(response)
        async with response:
            if url == INDEX_URL:
                yield response
            else:
                self.open_files += 1
                self.files_started.set()
                try:
                    await self.files_release.wait()
                    yield response
                finally:
                    self.open_files -= 1

    def post(
        self, url: str, *, json: object | None = None, params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None, timeout: object | None = None,
    ) -> Response:
        raise AssertionError("AMLL catalog access uses GET")

    async def close(self) -> None:
        return None


@pytest.fixture
def source() -> Iterator[AmllLyricsSource]:
    provider = AmllLyricsSource(worker=BlockingCallRunner("test-amll"))
    yield provider
    provider.close()


async def test_automatic_search_loads_official_ttml_and_preserves_words(source: AmllLyricsSource) -> None:
    session = Session(row())
    result = await source.resolve(session, TRACK, fuzzy=False)
    assert result is not None and result.source_id == "amll"
    assert result.confidence is MatchConfidence.HIGH
    assert result.document.has_word_timing
    assert result.document.lines[0].text == "Hello world"
    assert result.document.lines[0].translation == "你好"
    assert result.duration_s is None, "lyric end is not the audio duration"
    assert result.cache_artifact is not None
    assert parse_payload(result.cache_artifact.payload) == result.document.lines
    version = LyricsSearchResult.from_artifact(result.cache_artifact).version
    assert version.format_id == "ttml" and version.timing is LyricsTiming.WORD and version.has_translation
    assert all(response.closed for response in session.responses)


async def test_index_is_shared_between_automatic_and_manual_search(source: AmllLyricsSource) -> None:
    session = Session(row())
    await source.resolve(session, TRACK, fuzzy=False)
    results = await source.search_artifacts(session, TrackMetadata("So", "Art"))
    assert len(results) == 1 and results[0].provider == "amll"
    assert session.urls.count(INDEX_URL) == 1


async def test_version_and_artist_mismatch_never_fetch_automatic_lyrics(source: AmllLyricsSource) -> None:
    session = Session(row(title="Song (Live)") + row(OTHER_FILE, artist="Another", song_id="99"))
    assert await source.resolve(session, TRACK, fuzzy=False) is None
    assert session.urls == [INDEX_URL]


async def test_exact_platform_id_uses_catalog_identity_and_latest_revision(source: AmllLyricsSource) -> None:
    session = Session(row(OLD_FILE) + row())
    result = await source.resolve_exact(
        session, TrackMetadata("Noisy player title", "Uploader"), LyricsHint("netease", "42"),
    )
    assert result is not None and result.document.song_id == NEW_FILE
    assert result.document.title == "Song" and result.confidence is MatchConfidence.HIGH
    assert RAW_URL + OLD_FILE not in session.urls


@pytest.mark.parametrize("hint", [
    LyricsHint("local"), LyricsHint("netease", "../private"), LyricsHint("unknown", "42"),
])
async def test_invalid_or_unrelated_hints_do_not_start_network(source: AmllLyricsSource, hint: LyricsHint) -> None:
    session = Session(row())
    assert await source.resolve_exact(session, TRACK, hint) is None
    assert session.urls == []


def test_catalog_aliases_and_latest_revisions_use_shared_matching() -> None:
    records = parse_index(row(OLD_FILE) + row(title="歌曲", aliases=("Song",)))
    matches = match_records(records, TRACK, fuzzy=False)
    assert len(matches) == 1 and matches[0].record.candidate.song_id == NEW_FILE
    assert matches[0].confidence is MatchConfidence.HIGH
    assert match_records(records, TrackMetadata("Song (Live)", "Artist"), fuzzy=False) == ()


@pytest.mark.parametrize("file", ["../song.ttml", "https://evil.test/song.ttml", "x/../../song.ttml", "%2e%2e.ttml"])
def test_external_paths_cannot_enter_the_catalog(file: str) -> None:
    with pytest.raises(ValueError):
        parse_index(row(file))


@pytest.mark.parametrize("body", [
    b"[]", b"<html>Error</html>", b"{}", b"x" * (MAX_INDEX_BYTES + 1), b"[" * 2000 + b"]" * 2000,
], ids=["nonobject", "error-page", "missing-metadata", "oversized", "deeply-nested"])
def test_invalid_or_oversized_catalogs_are_not_empty_success(body: bytes) -> None:
    with pytest.raises(ValueError):
        parse_index(body)


@pytest.mark.parametrize("file", [
    "1737669191768-ljy6-6-6-l48qk4b9.ttml", "1766419644119-207428447,45750526-ehjthdko.ttml",
])
def test_legacy_author_names_and_multiple_authors_are_valid_catalog_files(file: str) -> None:
    assert parse_index(row(file))[0].candidate.song_id == file


async def test_cancelling_index_owner_releases_waiter_and_all_responses(source: AmllLyricsSource) -> None:
    session = Session(row())
    session.index_release.clear()
    first = asyncio.create_task(source.resolve(session, TRACK, fuzzy=False))
    await session.index_started.wait()
    second = asyncio.create_task(source.search_artifacts(session, TRACK))
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    session.index_release.set()
    results = await asyncio.wait_for(second, 2.0)
    assert len(results) == 1
    assert all(response.closed for response in session.responses)


async def test_concurrent_requests_download_the_catalog_once(source: AmllLyricsSource) -> None:
    session = Session(row())
    first, second = await asyncio.gather(
        source.resolve(session, TRACK, fuzzy=False), source.search_artifacts(session, TRACK),
    )
    assert first is not None and second
    assert session.urls.count(INDEX_URL) == 1


async def test_timeout_does_not_poison_the_index_cache(source: AmllLyricsSource) -> None:
    session = Session(row())
    session.index_failure = TimeoutError("offline")
    with pytest.raises(TimeoutError):
        await source.search_artifacts(session, TRACK)
    session.index_failure = None
    assert await source.search_artifacts(session, TRACK)


async def test_missing_ttml_is_a_miss_and_invalid_ttml_is_not_cached(source: AmllLyricsSource) -> None:
    for body in ({}, {NEW_FILE: b"<!DOCTYPE tt><tt/>"}):
        result = await source.resolve(Session(row(), body), TRACK, fuzzy=False)
        assert result is None


def test_amll_is_default_and_saved_source_choices_remain_explicit(tmp_path: Path) -> None:
    assert Config().lyrics_sources == ["amll", "netease", "lrclib", "kugou"]
    path = tmp_path / "config.json"
    for sources in (["netease", "cider"], ["amll", "kugou"]):
        save_config(Config(lyrics_sources=sources), path)
        assert load_config(path).lyrics_sources == sources


async def test_resolver_routes_platform_hint_to_enabled_amll(source: AmllLyricsSource) -> None:
    session = Session(row())
    resolver = LyricsResolver(catalog=catalog_for({"amll": source}, FakeGate([])), cache=FakeCache([]))
    try:
        result = await resolver.resolve_hint(session, TRACK, ["amll"], LyricsHint("netease", "42"))
        assert result is not None and result.source_id == "amll"
        assert await resolver.resolve_hint(session, TRACK, [], LyricsHint("netease", "42")) is None
        assert session.urls.count(INDEX_URL) == 1
    finally:
        await resolver.close()


async def test_exact_hint_survives_amll_outage_and_uses_original_provider(source: AmllLyricsSource) -> None:
    session = Session(row())
    session.index_failure = LyricsHttpError("offline")

    async def exact(session: LyricsSession, track: TrackMetadata, song_id: str) -> LyricsArtifact:
        assert song_id == "42"
        return artifact()

    async def missed(session: LyricsSession, track: TrackMetadata, *, fuzzy: bool) -> LyricsArtifact | None:
        return None

    resolver = LyricsResolver(catalog=catalog_for({
        "amll": source,
        "netease": NetworkLyricsSource("netease", missed, lambda payload: (), exact_fetch=exact),
    }, FakeGate([])), cache=FakeCache([]))
    try:
        result = await resolver.resolve_hint(session, TRACK, ["amll", "netease"], LyricsHint("netease", "42"))
        assert result is not None and result.source_id == "netease"
        assert session.index_started.is_set()
    finally:
        await resolver.close()


@pytest.mark.parametrize("prefer_best", [True, False])
async def test_exact_sources_follow_word_preference_or_sequential_order(
    source: AmllLyricsSource, prefer_best: bool,
) -> None:
    async def exact(session: LyricsSession, track: TrackMetadata, song_id: str) -> LyricsArtifact:
        return artifact()

    async def missed(session: LyricsSession, track: TrackMetadata, *, fuzzy: bool) -> LyricsArtifact | None:
        return None

    resolver = LyricsResolver(catalog=catalog_for({
        "amll": source,
        "netease": NetworkLyricsSource("netease", missed, lambda payload: (), exact_fetch=exact),
    }, FakeGate([])), cache=FakeCache([]), prefer_best=prefer_best)
    session = Session(row())
    try:
        result = await resolver.resolve_hint(session, TRACK, ["netease", "amll"], LyricsHint("netease", "42"))
        assert result is not None and result.source_id == ("amll" if prefer_best else "netease")
        assert session.index_started.is_set() == prefer_best
    finally:
        await resolver.close()


async def test_index_refreshes_after_expiry_and_can_restart() -> None:
    now = [0.0]
    provider = AmllLyricsSource(worker=BlockingCallRunner("test-amll-expiry"), clock=lambda: now[0], index_ttl_s=60.0)
    session = Session(row())
    try:
        assert await provider.resolve(session, TRACK, fuzzy=False) is not None
        now[0] = 59.0
        provider.close()
        provider.close()
        provider.start()
        assert await provider.resolve(session, TRACK, fuzzy=False) is not None
        assert session.urls.count(INDEX_URL) == 1
        now[0] = 60.0
        session.index = row(OTHER_FILE, title="Different", song_id="99")
        assert await provider.resolve(session, TRACK, fuzzy=False) is None
        assert session.urls.count(INDEX_URL) == 2
    finally:
        provider.close()


async def test_cancelled_manual_search_closes_all_active_downloads(source: AmllLyricsSource) -> None:
    session = Session(row() + row(OTHER_FILE, song_id="99"), {NEW_FILE: WORDS.encode(), OTHER_FILE: WORDS.encode()})
    session.files_release.clear()
    request = asyncio.create_task(source.search_artifacts(session, TRACK))
    try:
        await asyncio.wait_for(session.files_started.wait(), 2.0)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert session.open_files == 0
        assert all(response.closed for response in session.responses)
    finally:
        session.files_release.set()
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)


async def test_http_body_limits_are_enforced_before_parsing(source: AmllLyricsSource) -> None:
    from kotonoha.lyrics.payload import MAX_RESPONSE_BYTES

    session = Session(row(), {NEW_FILE: b"x" * (MAX_RESPONSE_BYTES + 1)})
    with pytest.raises(ValueError, match="exceeded"):
        await source.search_artifacts(session, TRACK)
    assert all(response.closed for response in session.responses)


async def test_manual_results_are_bounded_and_partial_download_failure_isolated(source: AmllLyricsSource) -> None:
    from kotonoha.lyrics.search_policy import MANUAL_SEARCH_RESULTS_PER_PROVIDER

    files = [f"1792065160{index:03}-103079805-x67ItPp4.ttml" for index in range(35)]
    index = b"".join(row(file, song_id=str(number)) for number, file in enumerate(files))
    # The latest entry has invalid UTF-8; the other selections remain usable.
    payloads = {file: WORDS.encode() for file in files}
    payloads[files[-1]] = b"\xff"
    session = Session(index, payloads)
    results = await source.search_artifacts(session, TRACK)
    assert len(results) == MANUAL_SEARCH_RESULTS_PER_PROVIDER - 1
    assert len([url for url in session.urls if url.startswith(RAW_URL)]) == MANUAL_SEARCH_RESULTS_PER_PROVIDER


async def test_word_timing_wins_over_line_ttml_at_equal_identity(source: AmllLyricsSource) -> None:
    session = Session(row() + row(OTHER_FILE, song_id="99"), {
        NEW_FILE: b'<tt><body><p begin="1s" end="3s">line</p></body></tt>',
        OTHER_FILE: WORDS.encode(),
    })
    result = await source.resolve(session, TRACK, fuzzy=False)
    assert result is not None and result.document.has_word_timing
    assert result.document.song_id == OTHER_FILE


@pytest.mark.parametrize("broken_first", [True, False])
async def test_automatic_search_keeps_valid_candidate_when_another_is_broken(
    source: AmllLyricsSource, broken_first: bool,
) -> None:
    files = {
        NEW_FILE: b"\xff" if broken_first else b'<tt><body><p begin="1s" end="3s">line</p></body></tt>',
        OTHER_FILE: WORDS.encode() if broken_first else b"\xff",
    }
    session = Session(row() + row(OTHER_FILE, song_id="99"), files)
    result = await source.resolve(session, TRACK, fuzzy=False)
    assert result is not None
    assert result.document.song_id == (OTHER_FILE if broken_first else NEW_FILE)


async def test_line_ttml_search_is_labelled_line_timing(source: AmllLyricsSource) -> None:
    session = Session(row(), {NEW_FILE: b'<tt><body><p begin="1s" end="3s">line</p></body></tt>'})
    artifacts = await source.search_artifacts(session, TRACK)
    assert LyricsSearchResult.from_artifact(artifacts[0]).version.timing is LyricsTiming.LINE


@pytest.mark.parametrize("exact", [False, True])
async def test_amll_auto_cache_restores_ttml_offline(source: AmllLyricsSource, tmp_path: Path, exact: bool) -> None:
    cache = LyricsCache(tmp_path / "lyrics.sqlite3", worker=BlockingCallRunner("test-amll-cache"))
    resolver = LyricsResolver(catalog=catalog_for({"amll": source}, FakeGate([])), cache=cache)
    try:
        if exact:
            first = await resolver.resolve_hint(Session(row()), TRACK, ["amll"], LyricsHint("netease", "42"))
        else:
            first = await resolver.resolve(Session(row()), TRACK, ["amll"])
        cached = await resolver.resolve(None, TRACK, ["amll"])
        assert first is not None and cached is not None
        assert cached.document.lines == first.document.lines
        assert cached.document.cache_state is LyricsCacheState.FROM_CACHE
        await cache.select(TRACK, (await source.search_artifacts(Session(row()), TRACK))[0])
        manual = await resolver.resolve(None, TRACK, ["amll"])
        assert manual is not None and manual.document.cache_state is LyricsCacheState.MANUAL
    finally:
        await resolver.close()


async def test_catalog_closes_and_reopens_shared_provider_worker() -> None:
    worker = BlockingCallRunner("test-amll-owned")
    provider = AmllLyricsSource(worker=worker)
    catalog = LyricsSourceCatalog(
        {"amll": provider}, live_source=LiveLyricsSource(FakeGate([])),
        local_source=LocalLyricsSource(
            SidecarLyricsSource(), EmbeddedLyricsSource(), worker=BlockingCallRunner("test-amll-local"),
        ),
        managed_sources=(provider,),
    )
    try:
        assert await provider.resolve(Session(row()), TRACK, fuzzy=False) is not None
        catalog.close()
        catalog.close()
        with pytest.raises(RuntimeError, match="closed"):
            await provider.resolve(Session(row()), TRACK, fuzzy=False)
        catalog.start()
        assert await provider.search_artifacts(Session(row()), TRACK)
    finally:
        catalog.close()
