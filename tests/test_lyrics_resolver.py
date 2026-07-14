import asyncio
import logging
import sqlite3
from typing import cast

import aiohttp

from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.match import MatchConfidence, TrackMetadata
from kotonoha.lyrics.resolver import LyricsResolver, NetworkProvider
from kotonoha.model import LyricLine, LyricsSnapshot
from kotonoha.providers.gate import CiderMatch

TRACK = TrackMetadata("Song", "Artist", "Album", 180.0)
SESSION = cast(aiohttp.ClientSession, None)


def artifact(*, provider: str = "netease", confidence: MatchConfidence = MatchConfidence.HIGH) -> LyricsArtifact:
    return LyricsArtifact(
        provider=provider,
        provider_song_id=f"{provider}-1",
        title="Song",
        artist="Artist",
        album="Album",
        duration_s=180.0,
        payload={"lrc": "[00:01.00]line"},
        lines=(LyricLine(0, "L0", 1.0, 6.0, "line", ""),),
        confidence=confidence,
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
    prefer_best=False,
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
        prefer_best=prefer_best,
    )


async def test_default_order_is_cache_network_per_provider_then_cider():
    calls = []
    resolver = resolver_with_fakes(
        calls,
        cache_hits={},
        network_hits={"lrclib": artifact(provider="lrclib")},
    )

    result = await resolver.resolve(SESSION, TRACK, ["netease", "lrclib", "cider"])

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

    await resolver.resolve(SESSION, TRACK, ["lrclib", "cider", "netease"])

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

    result = await resolver.resolve(SESSION, TRACK, ["cider", "netease"])

    assert result is not None
    assert result.source == "cider"
    assert result.live_snapshot is snapshot
    assert calls == ["cider"]


async def test_cache_disabled_skips_reads_and_writes():
    calls = []
    resolver = resolver_with_fakes(calls, cache_enabled=False, network_hits={"netease": artifact()})
    await resolver.resolve(SESSION, TRACK, ["netease"])
    assert calls == ["network:netease"]


async def test_cache_failure_does_not_block_same_provider_network():
    calls = []
    cache = FakeCache(calls, lookup_error=sqlite3.OperationalError("locked"))
    resolver = resolver_with_fakes(calls, cache=cache, network_hits={"netease": artifact()})

    result = await resolver.resolve(SESSION, TRACK, ["netease"])

    assert result is not None and result.source == "netease"
    assert calls == ["cache:netease", "network:netease", "store:netease"]


async def test_normal_provider_miss_is_cached_only_in_memory():
    calls = []
    resolver = resolver_with_fakes(calls)

    assert await resolver.resolve(SESSION, TRACK, ["netease"]) is None
    assert await resolver.resolve(
        SESSION,
        TrackMetadata("Ｓｏｎｇ", "Artist", "Album", 180.0),
        ["netease"],
    ) is None

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
    first = asyncio.create_task(resolver.resolve(SESSION, TRACK, ["netease"]))
    await started.wait()
    second = asyncio.create_task(resolver.resolve(SESSION, TRACK, ["netease"]))
    release.set()

    first_result, second_result = await asyncio.gather(first, second)

    assert first_result == second_result
    assert calls == ["network:netease"]


async def test_network_timeout_log_includes_exception_type(caplog):
    async def timeout(_session, _track):
        raise TimeoutError

    resolver = LyricsResolver(
        cache=FakeCache([]),
        gate=FakeGate([]),
        providers={"netease": NetworkProvider("netease", timeout, lambda _payload: ())},
        cache_enabled=False,
    )
    caplog.set_level(logging.WARNING)

    assert await resolver.resolve(SESSION, TRACK, ["netease"]) is None
    assert "TimeoutError" in caplog.text


async def test_best_mode_prefers_higher_confidence_over_first_source():
    # netease is first but only MEDIUM; lrclib is HIGH. In "best" mode the HIGH
    # result wins even though a lower-ranked source produced it.
    calls = []
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        network_hits={
            "netease": artifact(provider="netease", confidence=MatchConfidence.MEDIUM),
            "lrclib": artifact(provider="lrclib", confidence=MatchConfidence.HIGH),
        },
    )

    result = await resolver.resolve(SESSION, TRACK, ["netease", "lrclib"])

    assert result is not None
    assert result.source == "lrclib"
    assert result.confidence is MatchConfidence.HIGH
    # Both sources are fetched concurrently rather than strictly in order.
    assert "network:netease" in calls
    assert "network:lrclib" in calls


async def test_best_mode_same_confidence_keeps_configured_order():
    # Equal confidence -> the earlier-ordered source wins (respects the user's order).
    calls = []
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        network_hits={
            "netease": artifact(provider="netease", confidence=MatchConfidence.HIGH),
            "lrclib": artifact(provider="lrclib", confidence=MatchConfidence.HIGH),
        },
    )

    result = await resolver.resolve(SESSION, TRACK, ["netease", "lrclib"])

    assert result is not None
    assert result.source == "netease"


async def test_best_mode_cider_at_top_skips_network():
    # A cider match at the top of the order is HIGH and unbeatable, so best mode
    # returns it without launching any network fetch.
    calls = []
    snapshot = LyricsSnapshot(found=True, title="Song", artist="Artist")
    resolver = resolver_with_fakes(calls, prefer_best=True, cider_match=CiderMatch(12, snapshot))

    result = await resolver.resolve(SESSION, TRACK, ["cider", "netease"])

    assert result is not None
    assert result.source == "cider"
    assert result.live_snapshot is snapshot
    assert "network:netease" not in calls


async def test_best_mode_cached_hit_short_circuits_network():
    # A cached hit on any ordered source returns before any network fetch begins.
    calls = []
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        cache_hits={"netease": artifact(provider="netease")},
    )

    result = await resolver.resolve(SESSION, TRACK, ["netease", "lrclib"])

    assert result is not None
    assert result.source == "netease"
    assert "network:netease" not in calls
    assert "network:lrclib" not in calls


async def test_best_mode_cider_beats_lower_priority_cache_hit():
    # cider is configured above netease and has a live HIGH match; it must win the
    # HIGH tie over a netease cache hit (configured order breaks the tie), no network.
    calls = []
    snapshot = LyricsSnapshot(found=True, title="Song", artist="Artist")
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        cider_match=CiderMatch(12, snapshot, MatchConfidence.HIGH),
        cache_hits={"netease": artifact(provider="netease")},
    )

    result = await resolver.resolve(SESSION, TRACK, ["cider", "netease"])

    assert result is not None
    assert result.source == "cider"
    assert "network:netease" not in calls


async def test_best_mode_medium_cider_does_not_block_a_network_high():
    # A MEDIUM cider match must not short-circuit the network: a genuine network
    # HIGH beats it regardless of cider's position.
    calls = []
    snapshot = LyricsSnapshot(found=True, title="Song", artist="")
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        cider_match=CiderMatch(12, snapshot, MatchConfidence.MEDIUM),
        network_hits={"netease": artifact(provider="netease", confidence=MatchConfidence.HIGH)},
    )

    result = await resolver.resolve(SESSION, TRACK, ["cider", "netease"])

    assert result is not None
    assert result.source == "netease"
    assert result.confidence is MatchConfidence.HIGH
    assert "network:netease" in calls


async def test_best_mode_uncached_top_source_wins_over_cached_lower_source():
    # netease (higher priority) is uncached but resolves HIGH from the network;
    # lrclib (lower priority) is a HIGH cache hit. The configured order breaks the
    # HIGH tie, so netease must win even though lrclib was free.
    calls = []
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        cache_hits={"lrclib": artifact(provider="lrclib")},
        network_hits={"netease": artifact(provider="netease", confidence=MatchConfidence.HIGH)},
    )

    result = await resolver.resolve(SESSION, TRACK, ["netease", "lrclib"])

    assert result is not None
    assert result.source == "netease"
    assert "network:netease" in calls
    assert "network:lrclib" not in calls  # lrclib was resolved from cache, no fetch


async def test_best_mode_duplicate_source_fetches_once():
    # resolve() is public with no de-dup precondition; a repeated source must not
    # spawn a second (orphaned) fetch task in best mode.
    calls = []
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        cache_enabled=False,
        network_hits={"netease": artifact(provider="netease")},
    )

    result = await resolver.resolve(SESSION, TRACK, ["netease", "netease", "lrclib"])

    assert result is not None
    assert result.source == "netease"
    assert calls.count("network:netease") == 1
