import asyncio
import sqlite3

from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.match import MatchConfidence, TrackMetadata
from kotonoha.lyrics.resolver import LyricsResolver, NetworkProvider
from kotonoha.model import LyricLine, LyricsSnapshot
from kotonoha.providers.gate import CiderMatch

TRACK = TrackMetadata("Song", "Artist", "Album", 180.0)


def artifact(*, provider: str = "netease") -> LyricsArtifact:
    return LyricsArtifact(
        provider=provider,
        provider_song_id=f"{provider}-1",
        title="Song",
        artist="Artist",
        album="Album",
        duration_s=180.0,
        payload={"lrc": "[00:01.00]line"},
        lines=(LyricLine(0, "L0", 1.0, 6.0, "line", ""),),
        confidence=MatchConfidence.HIGH,
    )


class FakeCache:
    def __init__(self, calls, hits=None, *, lookup_error=None):
        self.calls = calls
        self.hits = hits or {}
        self.lookup_error = lookup_error

    async def lookup(self, provider, _track, _parser):
        self.calls.append(f"cache:{provider}")
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.hits.get(provider)

    async def store(self, value):
        self.calls.append(f"store:{value.provider}")

    async def clear(self):
        self.calls.append("clear")


class FakeGate:
    def __init__(self, calls, match=None):
        self.calls = calls
        self.match = match

    def select_external(self):
        return None

    def current_match(self, _track):
        self.calls.append("cider")
        return self.match

    def select_cider(self, _client_id):
        return None


def resolver_with_fakes(
    calls,
    *,
    cache_hits=None,
    network_hits=None,
    cider_match=None,
    cache_enabled=True,
    cache=None,
):
    network_hits = network_hits or {}

    def adapter(name):
        async def fetch(_session, _track):
            calls.append(f"network:{name}")
            return network_hits.get(name)

        return NetworkProvider(name=name, fetch=fetch, parse_payload=lambda _payload: ())

    return LyricsResolver(
        cache=cache or FakeCache(calls, cache_hits),
        gate=FakeGate(calls, cider_match),
        providers={name: adapter(name) for name in ("netease", "lrclib")},
        cache_enabled=cache_enabled,
        negative_ttl=30.0,
    )


async def test_default_order_is_cache_network_per_provider_then_cider():
    calls = []
    resolver = resolver_with_fakes(
        calls,
        cache_hits={},
        network_hits={"lrclib": artifact(provider="lrclib")},
    )

    result = await resolver.resolve(None, TRACK, ["netease", "lrclib", "cider"])

    assert result is not None and result.source == "lrclib"
    assert calls == [
        "cache:netease",
        "network:netease",
        "cache:lrclib",
        "network:lrclib",
        "store:lrclib",
    ]


async def test_cider_runs_at_configured_position_and_continues_when_unavailable():
    calls = []
    resolver = resolver_with_fakes(calls, network_hits={"netease": artifact()})

    await resolver.resolve(None, TRACK, ["lrclib", "cider", "netease"])

    assert calls == [
        "cache:lrclib",
        "network:lrclib",
        "cider",
        "cache:netease",
        "network:netease",
        "store:netease",
    ]


async def test_available_cider_stops_at_its_configured_position():
    calls = []
    snapshot = LyricsSnapshot(found=True, title="Song", artist="Artist")
    resolver = resolver_with_fakes(calls, cider_match=CiderMatch(12, snapshot))

    result = await resolver.resolve(None, TRACK, ["cider", "netease"])

    assert result is not None
    assert result.source == "cider"
    assert result.live_snapshot is snapshot
    assert calls == ["cider"]


async def test_cache_disabled_skips_reads_and_writes():
    calls = []
    resolver = resolver_with_fakes(calls, cache_enabled=False, network_hits={"netease": artifact()})
    await resolver.resolve(None, TRACK, ["netease"])
    assert calls == ["network:netease"]


async def test_cache_failure_does_not_block_same_provider_network():
    calls = []
    cache = FakeCache(calls, lookup_error=sqlite3.OperationalError("locked"))
    resolver = resolver_with_fakes(calls, cache=cache, network_hits={"netease": artifact()})

    result = await resolver.resolve(None, TRACK, ["netease"])

    assert result is not None and result.source == "netease"
    assert calls == ["cache:netease", "network:netease", "store:netease"]


async def test_normal_provider_miss_is_cached_only_in_memory():
    calls = []
    resolver = resolver_with_fakes(calls)

    assert await resolver.resolve(None, TRACK, ["netease"]) is None
    assert await resolver.resolve(None, TrackMetadata("Ｓｏｎｇ", "Artist", "Album", 180.0), ["netease"]) is None

    assert calls == ["cache:netease", "network:netease", "cache:netease"]


async def test_concurrent_identical_requests_share_network_work():
    calls = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch(_session, _track):
        calls.append("network:netease")
        started.set()
        await release.wait()
        return artifact()

    resolver = LyricsResolver(
        cache=FakeCache(calls),
        gate=FakeGate(calls),
        providers={"netease": NetworkProvider("netease", fetch, lambda _payload: ())},
        cache_enabled=False,
    )
    first = asyncio.create_task(resolver.resolve(None, TRACK, ["netease"]))
    await started.wait()
    second = asyncio.create_task(resolver.resolve(None, TRACK, ["netease"]))
    release.set()

    first_result, second_result = await asyncio.gather(first, second)

    assert first_result == second_result
    assert calls == ["network:netease"]
