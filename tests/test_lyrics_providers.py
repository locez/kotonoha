import asyncio
import json
from typing import cast

import aiohttp
import pytest

from kotonoha.lyrics import kugou, lrclib, netease
from kotonoha.lyrics.match import Candidate, MatchConfidence, TrackMetadata

SESSION = cast(aiohttp.ClientSession, None)


def async_return(value):
    async def result(*_args, **_kwargs):
        return value

    return result


class _Content:
    """The streaming half of a response, which is what the providers read.

    They cap how much of a body they will buffer, so they go through
    content.read(limit) rather than json(); a fake offering only the convenience
    method would leave the cap untested.
    """

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._cursor = 0

    async def read(self, limit: int) -> bytes:
        """Hand back at most `limit` bytes, as a real socket does.

        A fake that returned the whole body in one call could not catch a reader
        that stops after its first read — which is exactly what the first version
        of the cap did, truncating a 307KB response to 114KB.
        """
        chunk = self._payload[self._cursor : self._cursor + min(limit, 8192)]
        self._cursor += len(chunk)
        return chunk


class _Resp:
    def __init__(self, data):
        self._data = data
        self.status = 200
        self.content = _Content(json.dumps(data).encode() if not isinstance(data, (bytes, str)) else
                                (data.encode() if isinstance(data, str) else data))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    def raise_for_status(self):
        return None

    async def json(self, content_type=None):
        return self._data


class _RecordingSession:
    """Captures the per-request timeout each provider passes to session.get."""

    def __init__(self, data):
        self._data = data
        self.timeouts = []

    def get(self, _url, params=None, headers=None, timeout=None):
        self.timeouts.append(timeout)
        return _Resp(self._data)


def test_provider_timeouts_are_per_provider_and_generous_enough():
    # The old shared 3s budget killed every lrclib fetch (its backend takes 7-9s).
    assert netease.TIMEOUT.total is not None and netease.TIMEOUT.total >= 5.0
    assert lrclib.TIMEOUT.total is not None and lrclib.TIMEOUT.total >= 10.0
    assert lrclib.TIMEOUT.total > netease.TIMEOUT.total


async def test_netease_search_uses_provider_timeout():
    session = _RecordingSession({"result": {"songs": []}})
    await netease.search(cast(aiohttp.ClientSession, session), "query")
    assert session.timeouts == [netease.TIMEOUT]


async def test_lrclib_search_uses_provider_timeout():
    session = _RecordingSession([])
    await lrclib.search_records(cast(aiohttp.ClientSession, session), TrackMetadata("Song", "Artist"))
    assert session.timeouts == [lrclib.TIMEOUT]


async def test_netease_search_captures_aliases_and_trans_names():
    payload = {
        "result": {
            "songs": [
                {
                    "id": 1,
                    "name": "生如夏花",
                    "artists": [{"name": "朴树"}],
                    "album": {"name": "生如夏花"},
                    "duration": 272000,
                    "alias": ["生如夏花 现场版"],
                    "transNames": ["Life Like Summer Flowers"],
                }
            ]
        }
    }
    session = _RecordingSession(payload)
    candidates = await netease.search(cast(aiohttp.ClientSession, session), "q")
    assert len(candidates) == 1
    assert "Life Like Summer Flowers" in candidates[0].aliases
    assert "生如夏花 现场版" in candidates[0].aliases


async def test_netease_empty_parsed_yrc_falls_back_to_lrc(monkeypatch):
    async def fake_search(_session, _query, limit=10):
        return [Candidate("42", "Song", "Artist", 180.0, album="Album")]

    async def fake_payload(_session, _song_id):
        return {"yrc": "not valid yrc", "lrc": "[00:01.00]line", "tlyric": ""}

    monkeypatch.setattr(netease, "search", fake_search)
    monkeypatch.setattr(netease, "fetch_payload", fake_payload)

    artifact = await netease.fetch_artifact(SESSION, TrackMetadata("Song", "Artist", "Album", 180.0))

    assert artifact is not None
    assert artifact.provider_song_id == "42"
    assert artifact.confidence is MatchConfidence.HIGH
    assert [line.text for line in artifact.lines] == ["line"]


async def test_netease_tries_normalized_query_before_accepting_medium_match(monkeypatch):
    queries = []

    async def fake_search(_session, query, limit=10):
        queries.append(query)
        if query == "Song (Remastered 2011) Artist feat. Guest":
            return [Candidate("medium", "Song (Remastered 2011)", "", None)]
        return [Candidate("high", "Song (Remastered 2011)", "Artist", 180.0)]

    monkeypatch.setattr(netease, "search", fake_search)
    monkeypatch.setattr(
        netease,
        "fetch_payload",
        async_return({"yrc": "", "lrc": "[00:01.00]line", "tlyric": ""}),
    )

    track = TrackMetadata("Song (Remastered 2011)", "Artist feat. Guest", duration_s=180.0)
    artifact = await netease.fetch_artifact(SESSION, track)

    # The reported reading goes alone, so the common case still costs one request.
    # The rest are searched a batch at a time, which is why the reading after the one
    # that hit was sent too: the batch buys a round trip and pays for it in requests.
    assert queries == ["Song (Remastered 2011) Artist feat. Guest", "Song", "Song Artist"]
    assert artifact is not None
    assert artifact.provider_song_id == "high"
    assert artifact.confidence is MatchConfidence.HIGH


async def test_netease_can_upgrade_same_song_id_to_high_confidence(monkeypatch):
    async def fake_search(_session, query, limit=10):
        if query == "Song (Remastered 2011) Artist feat. Guest":
            return [Candidate("same", "Song (Remastered 2011)", "", None)]
        return [Candidate("same", "Song (Remastered 2011)", "Artist", 180.0)]

    monkeypatch.setattr(netease, "search", fake_search)
    monkeypatch.setattr(
        netease,
        "fetch_payload",
        async_return({"yrc": "", "lrc": "[00:01.00]line", "tlyric": ""}),
    )

    track = TrackMetadata("Song (Remastered 2011)", "Artist feat. Guest", duration_s=180.0)
    result = await netease.fetch_artifact(SESSION, track)

    assert result is not None
    assert result.provider_song_id == "same"
    assert result.confidence is MatchConfidence.HIGH


async def test_lrclib_search_ranks_results_instead_of_taking_first(monkeypatch):
    monkeypatch.setattr(lrclib, "get_exact", async_return(None))
    monkeypatch.setattr(
        lrclib,
        "search_records",
        async_return(
            [
                lrclib.Record("wrong", "Song (Live)", "Artist", "", 240.0, "[00:01]wrong"),
                lrclib.Record("right", "Song", "Artist", "Album", 180.0, "[00:01]right"),
            ]
        ),
    )

    artifact = await lrclib.fetch_artifact(SESSION, TrackMetadata("Song", "Artist", "Album", 180.0))

    assert artifact is not None
    assert artifact.provider_song_id == "right"
    assert [line.text for line in artifact.lines] == ["right"]


async def test_lrclib_exact_failure_still_uses_search(monkeypatch):
    async def failed_exact(_session, _track):
        raise ValueError("bad exact payload")

    monkeypatch.setattr(lrclib, "get_exact", failed_exact)
    monkeypatch.setattr(
        lrclib,
        "search_records",
        async_return([lrclib.Record("right", "Song", "Artist", "", 180.0, "[00:01]right")]),
    )

    artifact = await lrclib.fetch_artifact(SESSION, TrackMetadata("Song", "Artist", duration_s=180.0))

    assert artifact is not None
    assert artifact.provider_song_id == "right"


async def test_lrclib_duplicate_id_uses_the_better_search_record(monkeypatch):
    monkeypatch.setattr(
        lrclib,
        "get_exact",
        async_return(lrclib.Record("same", "Song", "", "", None, "[00:01]medium")),
    )
    monkeypatch.setattr(
        lrclib,
        "search_records",
        async_return([lrclib.Record("same", "Song", "Artist", "Album", 180.0, "[00:01]high")]),
    )

    result = await lrclib.fetch_artifact(SESSION, TrackMetadata("Song", "Artist", "Album", 180.0))

    assert result is not None
    assert result.artist == "Artist"
    assert result.confidence is MatchConfidence.HIGH
    assert [line.text for line in result.lines] == ["high"]


async def test_lrclib_slow_exact_does_not_block_high_search(monkeypatch):
    exact_cancelled = asyncio.Event()

    async def slow_exact(_session, _track):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            exact_cancelled.set()
            raise

    monkeypatch.setattr(lrclib, "get_exact", slow_exact)
    monkeypatch.setattr(
        lrclib,
        "search_records",
        async_return([lrclib.Record("right", "Song", "Artist", "Album", 180.0, "[00:01]right")]),
    )

    result = await asyncio.wait_for(
        lrclib.fetch_artifact(SESSION, TrackMetadata("Song", "Artist", "Album", 180.0)),
        timeout=0.1,
    )

    assert result is not None
    assert result.provider_song_id == "right"
    assert exact_cancelled.is_set()


class _KugouSession:
    """Dispatches Kugou's two endpoints (search, download) to canned responses."""

    def __init__(self, search_data, download_data):
        self._search = search_data
        self._download = download_data

    def get(self, url, params=None, headers=None, timeout=None):
        return _Resp(self._search if "search" in url else self._download)


async def test_kugou_matches_by_title_and_duration_and_decodes_lrc():
    import base64

    lrc = "[00:01.00]line one\n[00:02.00]line two"
    search = {
        "candidates": [
            # The "singer" field is wrong (Kugou often mislabels it), but the title
            # and duration still identify the song.
            {"id": "1", "accesskey": "K", "song": "晴天", "singer": "晴天", "duration": 269000},
        ]
    }
    download = {"fmt": "lrc", "content": base64.b64encode(lrc.encode()).decode()}
    session = cast(aiohttp.ClientSession, _KugouSession(search, download))
    art = await kugou.fetch_artifact(session, TrackMetadata("晴天", "周杰伦", "", 269.0))
    assert art is not None
    assert art.provider == "kugou"
    assert art.confidence is MatchConfidence.HIGH  # exact title + matching duration
    assert [line.text for line in art.lines] == ["line one", "line two"]


async def test_kugou_skips_a_candidate_whose_lyrics_are_empty():
    search = {"candidates": [{"id": "1", "accesskey": "K", "song": "晴天", "singer": "x", "duration": 269000}]}
    download = {"fmt": "lrc", "content": ""}  # no lyrics to decode
    session = cast(aiohttp.ClientSession, _KugouSession(search, download))
    art = await kugou.fetch_artifact(session, TrackMetadata("晴天", "周杰伦", "", 269.0))
    assert art is None


class _KugouMultiSession:
    """Kugou mock that returns a per-id download body, so an empty first candidate
    and a good second candidate can be distinguished."""

    def __init__(self, search_data, downloads):
        self._search = search_data
        self._downloads = downloads
        self.download_ids = []

    def get(self, url, params=None, headers=None, timeout=None):
        if "search" in url:
            return _Resp(self._search)
        cand_id = (params or {}).get("id")
        self.download_ids.append(cand_id)
        return _Resp({"fmt": "lrc", "content": self._downloads.get(cand_id, "")})


async def test_kugou_falls_through_to_the_next_candidate_when_the_first_is_empty():
    import base64

    lrc = "[00:01.00]real line"
    search = {
        "candidates": [
            {"id": "1", "accesskey": "A", "song": "晴天", "singer": "x", "duration": 269000},
            {"id": "2", "accesskey": "B", "song": "晴天", "singer": "y", "duration": 269000},
        ]
    }
    downloads = {"1": "", "2": base64.b64encode(lrc.encode()).decode()}
    session = _KugouMultiSession(search, downloads)
    art = await kugou.fetch_artifact(cast(aiohttp.ClientSession, session), TrackMetadata("晴天", "周杰伦", "", 269.0))
    assert art is not None
    assert art.provider_song_id == "2"  # skipped the empty "1", used "2"
    assert session.download_ids == ["1", "2"]


async def test_kugou_caps_the_number_of_downloads():
    search = {
        "candidates": [
            {"id": str(i), "accesskey": "A", "song": "晴天", "singer": "x", "duration": 269000}
            for i in range(8)
        ]
    }
    session = _KugouMultiSession(search, {})  # every download is empty
    art = await kugou.fetch_artifact(cast(aiohttp.ClientSession, session), TrackMetadata("晴天", "周杰伦", "", 269.0))
    assert art is None
    assert len(session.download_ids) == kugou._MAX_FETCHES  # capped, not all 8


async def test_netease_caps_total_lyric_fetches(monkeypatch):
    async def fake_search(_session, _query, limit=10):
        return [Candidate(str(i), "Song", "Artist", 180.0) for i in range(8)]

    fetched = []

    async def fake_payload(_session, song_id):
        fetched.append(song_id)
        return {"yrc": "", "lrc": "", "tlyric": ""}  # no timed lyrics -> keep trying

    monkeypatch.setattr(netease, "search", fake_search)
    monkeypatch.setattr(netease, "fetch_payload", fake_payload)
    result = await netease.fetch_artifact(SESSION, TrackMetadata("Song", "Artist", duration_s=180.0))
    assert result is None
    assert len(fetched) == 6  # the shared fetch budget, not all 8 HIGH candidates


async def test_kugou_also_queries_the_title_with_the_performer():
    # Kugou answers 200/OK with no candidates for titles it holds under another
    # keyword, and neither form wins consistently: over twelve tracks the title
    # alone found 3 and the title with the performer found 4, both together 6.
    import base64

    seen: list[str] = []

    class _RecordingSession:
        def get(self, url, params=None, headers=None, timeout=None):
            if "search" in url:
                seen.append((params or {}).get("keyword", ""))
                data = (
                    {"candidates": [{"id": "1", "accesskey": "K", "song": "晴天", "duration": 269000}]}
                    if (params or {}).get("keyword") == "晴天 周杰伦"
                    else {"candidates": []}
                )
                return _Resp(data)
            lrc = "[00:01.00]found by the second keyword"
            return _Resp({"fmt": "lrc", "content": base64.b64encode(lrc.encode()).decode()})

    session = cast(aiohttp.ClientSession, _RecordingSession())
    art = await kugou.fetch_artifact(session, TrackMetadata("晴天", "周杰伦", "", 269.0))

    # Both forms, in the ladder's order — which of them wins is the point, not when.
    assert set(seen) == {"晴天", "晴天 周杰伦"}
    assert art is not None
    assert [line.text for line in art.lines] == ["found by the second keyword"]


def test_kugou_parses_the_payload_shape_it_caches():
    # A word-timed hit is stored as base64 KRC. The cache deletes any row its
    # parser cannot read, so a parser that only knows the LRC key made the
    # word-timed path refetch on every single lookup.
    import base64
    import zlib

    from kotonoha.lyrics.krc_parser import KRC_XOR_KEY

    body = b"[0,1000]<0,500,0>word <500,500,0>two\n"
    packed = zlib.compress(body)
    encrypted = bytes(byte ^ KRC_XOR_KEY[index % len(KRC_XOR_KEY)] for index, byte in enumerate(packed))
    payload = {"krc": base64.b64encode(b"krc1" + encrypted).decode("ascii")}

    lines = kugou.parse_payload(payload)

    assert lines, "the cached KRC payload produced no lines"
    assert lines[0].words, "word timing was lost on the way through the cache"
    assert kugou.parse_payload({"krc": "not base64 %%%"}) == ()


async def test_every_provider_refuses_an_unbounded_response():
    # A timeout bounds how long a response may take, not how large it may become.
    # Only QQ Music had a ceiling; the other three buffered whatever arrived.
    from kotonoha.lyrics.payload import MAX_RESPONSE_BYTES

    oversized = b'{"padding":"' + b"x" * (MAX_RESPONSE_BYTES + 64) + b'"}'

    class _OversizedSession:
        def get(self, _url, **_kwargs):
            return _Resp(oversized)

        def post(self, _url, **_kwargs):
            return _Resp(oversized)

    session = cast(aiohttp.ClientSession, _OversizedSession())
    track = TrackMetadata("Song", "Artist", "", 180.0)

    for name, call in (
        ("netease", netease.fetch_artifact(session, track)),
        ("kugou", kugou.fetch_artifact(session, track)),
        ("lrclib", lrclib.fetch_artifact(session, track)),
    ):
        try:
            await call
        except ValueError as exc:
            assert "exceeded" in str(exc), f"{name}: {exc}"
        else:
            raise AssertionError(f"{name} buffered a body past the limit")


async def test_a_body_larger_than_one_read_arrives_whole():
    # content.read(n) returns what has arrived, not n bytes. Reading once truncated
    # a 307KB response to 114KB against a real server, and the fragment then failed
    # to parse — a long lyric or a large search result would have been lost rather
    # than capped.
    from kotonoha.lyrics.payload import MAX_RESPONSE_BYTES, read_capped

    body = b'{"padding":"' + b"x" * (300 * 1024) + b'"}'
    assert len(body) < MAX_RESPONSE_BYTES, "this body is legitimate, not oversized"

    got = await read_capped(cast(aiohttp.ClientResponse, _Resp(body)), "test")

    assert got == body


def test_the_reported_reading_is_searched_on_its_own():
    # It is right most of the time, so batching it with the salvage would make every
    # ordinary lookup pay for readings nobody needed.
    from kotonoha.lyrics.match import QueryVariant
    from kotonoha.lyrics.netease import _ladder_batches

    rungs = tuple(QueryVariant(f"t{i}", "", "r") for i in range(7))

    batches = [tuple(v.title for v in batch) for batch in _ladder_batches(rungs)]

    assert batches[0] == ("t0",)
    assert [len(b) for b in batches] == [1, 4, 2]
    assert [title for batch in batches for title in batch] == [f"t{i}" for i in range(7)]
    assert list(_ladder_batches(())) == []


async def test_one_failed_reading_does_not_abandon_its_batch(monkeypatch):
    # The rungs of a batch are independent readings of the same track; a request that
    # fails says nothing about the others, which may hold the song.
    from kotonoha.lyrics import netease
    from kotonoha.lyrics.match import QueryVariant

    async def flaky(_session, query, limit=10):
        if query == "bad":
            raise aiohttp.ClientError("boom")
        return [Candidate("1", query, "Artist", None)]

    monkeypatch.setattr(netease, "search", flaky)
    pages = await netease._search_batch(SESSION, (QueryVariant("bad", "", "r"), QueryVariant("good", "", "r")))

    assert [c.title for page in pages for c in page] == ["good"]


async def test_a_batch_that_fails_entirely_still_reports(monkeypatch):
    from kotonoha.lyrics import netease
    from kotonoha.lyrics.match import QueryVariant

    async def always_fails(_session, _query, limit=10):
        raise aiohttp.ClientError("boom")

    monkeypatch.setattr(netease, "search", always_fails)
    with pytest.raises(aiohttp.ClientError):
        await netease._search_batch(SESSION, (QueryVariant("a", "", "r"), QueryVariant("b", "", "r")))
