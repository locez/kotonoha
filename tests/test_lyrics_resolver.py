import asyncio
import contextlib
import logging
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from kotonoha.app.source_gate import SourceOwnershipCoordinator
from kotonoha.async_worker import BlockingCallRunner
from kotonoha.lyrics import netease, qqmusic
from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.cache import (
    CacheDeleteResult,
    CacheDeleteStatus,
    CacheWriteResult,
    CacheWriteStatus,
    LyricsCache,
    LyricsCacheEntry,
    LyricsCacheError,
    LyricsCacheHit,
    LyricsCacheKey,
    LyricsCacheMode,
    LyricsCacheQuery,
)
from kotonoha.lyrics.catalog import LyricsSourceCatalog
from kotonoha.lyrics.hint import LyricsHint
from kotonoha.lyrics.http import LyricsSession
from kotonoha.lyrics.live_contracts import LiveSourceMatch
from kotonoha.lyrics.live_source import LiveLyricsSource, LiveSourcePort
from kotonoha.lyrics.match import MatchConfidence, TrackMetadata
from kotonoha.lyrics.models import LyricLine, LyricsCacheState, LyricsDocument, LyricsOrigin, TimingKind
from kotonoha.lyrics.network_sources import NetworkLyricsSource
from kotonoha.lyrics.resolver import LyricsResolver
from kotonoha.lyrics.sources import (
    EmbeddedLyricsSource,
    LocalLyricsSource,
    LyricsSource,
    LyricsSourceKind,
    SidecarLyricsSource,
)
from kotonoha.lyrics.workflow import ResolverLookup
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity

TRACK = TrackMetadata("Song", "Artist", "Album", 180.0)
SESSION = cast(LyricsSession, object())


def live_match(*, artist: str = "Artist", confidence: MatchConfidence = MatchConfidence.HIGH) -> LiveSourceMatch:
    line = LyricLine(0, "L0", 0.0, 5.0, "Song", "")
    document = LyricsDocument("apple-music", timing=TimingKind.LINE, title="Song", artist=artist, lines=(line,))
    track = TrackIdentity("cider", "cider", stable_id="song-1", title="Song", artist=artist)
    observation = PlaybackObservation("cider", "cider", track, PlaybackStatus.PLAYING, 1.0, 180.0, 1.0)
    return LiveSourceMatch(12, observation, document, confidence)


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
    def __init__(self, calls, hits=None, *, lookup_error=None, manual_hit=None):
        self.calls = calls
        self.hits = hits or {}
        self.lookup_error = lookup_error
        self.manual_hit = manual_hit

    def start(self):
        self.calls.append("start")

    async def lookup(self, provider, _track, _parser):
        self.calls.append(f"cache:{provider}")
        if self.lookup_error is not None:
            raise self.lookup_error
        hit = self.hits.get(provider)
        return None if hit is None else LyricsCacheHit(hit, LyricsCacheMode.AUTO)

    async def lookup_manual(self, _track, _parsers):
        return self.manual_hit

    async def store(self, value: LyricsArtifact) -> CacheWriteResult:
        self.calls.append(f"store:{value.provider}")
        return CacheWriteResult(
            LyricsCacheKey(value.provider, value.provider_song_id),
            CacheWriteStatus.CREATED,
        )

    async def search(self, query: LyricsCacheQuery) -> tuple[LyricsCacheEntry, ...]:
        del query
        return ()

    async def get(self, key: LyricsCacheKey) -> LyricsCacheEntry | None:
        del key
        return None

    async def upsert(
        self,
        value: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        del mode
        return CacheWriteResult(
            LyricsCacheKey(value.provider, value.provider_song_id),
            CacheWriteStatus.CREATED,
        )

    async def update(
        self,
        key: LyricsCacheKey,
        value: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        del value, mode
        return CacheWriteResult(key, CacheWriteStatus.UPDATED)

    async def delete(self, key: LyricsCacheKey) -> CacheDeleteResult:
        return CacheDeleteResult(key, CacheDeleteStatus.DELETED)

    async def delete_many(self, keys: tuple[LyricsCacheKey, ...]) -> tuple[CacheDeleteResult, ...]:
        return tuple(CacheDeleteResult(key, CacheDeleteStatus.DELETED) for key in keys)

    async def clear(self):
        self.calls.append("clear")

    def close(self):
        self.calls.append("close")


class FakeGate:
    def __init__(self, calls, match=None):
        self.calls = calls
        self.match = match

    def select_external(self):
        return None

    def current_match(self, _track):
        self.calls.append("cider")
        return self.match

    def select_live(self, _client_id):
        return None


def catalog_for(providers: Mapping[str, LyricsSource], ownership: LiveSourcePort) -> LyricsSourceCatalog:
    """Build an explicit resolver catalog for tests without hidden defaults."""
    return LyricsSourceCatalog(
        providers,
        live_source=LiveLyricsSource(ownership),
        local_source=LocalLyricsSource(
            SidecarLyricsSource(),
            EmbeddedLyricsSource(),
            worker=BlockingCallRunner("test-local-lyrics"),
        ),
    )


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
        async def fetch(session, track, *, fuzzy=False):
            calls.append(f"network:{name}")
            return network_hits.get(name)

        exact_fetch = {
            "netease": netease.fetch_artifact_for_song_id,
            "qqmusic": qqmusic.fetch_artifact_for_song_id,
        }.get(name)
        return NetworkLyricsSource(
            source_id=name,
            fetch=fetch,
            parse_payload=lambda _payload: (),
            exact_fetch=exact_fetch,
        )

    gate = FakeGate(calls, cider_match)
    selected_cache = cache if cache is not None else FakeCache(calls, cache_hits)
    return LyricsResolver(
        catalog=catalog_for({name: adapter(name) for name in ("netease", "qqmusic", "lrclib")}, gate),
        cache=selected_cache,
        cache_enabled=cache_enabled,
        negative_ttl=30.0,
        prefer_best=prefer_best,
    )


async def test_set_fuzzy_clears_the_negative_cache_so_a_miss_can_retry():
    calls = []
    resolver = resolver_with_fakes(calls, cache_enabled=False)  # providers miss (no network_hits)

    assert await resolver.resolve(SESSION, TRACK, ["netease"]) is None
    first = calls.count("network:netease")
    assert first == 1
    # Re-resolving is short-circuited by the negative cache — the provider isn't hit.
    assert await resolver.resolve(SESSION, TRACK, ["netease"]) is None
    assert calls.count("network:netease") == first
    # Toggling fuzzy clears the negative cache, so the (now wider) search runs again.
    resolver.set_fuzzy(True)
    assert await resolver.resolve(SESSION, TRACK, ["netease"]) is None
    assert calls.count("network:netease") == first + 1


async def test_resolver_logs_source_candidates_and_final_selection(caplog):
    calls = []
    resolver = resolver_with_fakes(
        calls,
        network_hits={"lrclib": artifact(provider="lrclib")},
        cache_enabled=False,
        prefer_best=True,
    )

    with caplog.at_level(logging.DEBUG):
        result = await resolver.resolve(SESSION, TRACK, ["lrclib"])

    assert result is not None
    messages = [record.getMessage() for record in caplog.records]
    assert any("lyrics resolution candidate: origin=network source_slot='lrclib'" in message for message in messages)
    assert any("lyrics resolution selected: source_slot='lrclib'" in message for message in messages)


async def test_resolver_does_not_change_display_ownership():
    ownership = SourceOwnershipCoordinator()
    resolver = LyricsResolver(
        catalog=catalog_for({}, ownership),
        cache=FakeCache([]),
        cache_enabled=False,
    )

    assert await resolver.resolve(SESSION, TRACK, ["unknown"]) is None

    assert ownership.mode == "standalone"
    assert ownership.accepts("external-player") is False


async def test_exact_netease_hint_bypasses_matching(monkeypatch):
    calls = []

    async def exact(_session, song_id):
        calls.append(song_id)
        return {"lrc": "[00:01.00]exact", "yrc": "", "tlyric": ""}

    monkeypatch.setattr("kotonoha.lyrics.netease.fetch_payload", exact)
    resolver = resolver_with_fakes(calls, cache_enabled=False)
    result = await resolver.resolve_hint(
        SESSION, TrackMetadata("Wrong", "Wrong"), ["netease"], LyricsHint("netease", "42")
    )
    assert result is not None and result.source_id == "netease"
    assert calls == ["42"]


async def test_exact_qqmusic_hint_fetches_only_when_source_is_enabled(monkeypatch):
    calls = []

    async def exact(_session, song_id):
        calls.append(song_id)
        return {"lyric": "[00:01.00]exact", "trans": ""}

    monkeypatch.setattr("kotonoha.lyrics.qqmusic.fetch_payload_for_song_id", exact)
    resolver = resolver_with_fakes(calls, cache_enabled=False)
    hint = LyricsHint("qqmusic", "003aAYrm3GE0Ac")

    assert await resolver.resolve_hint(SESSION, TRACK, ["netease"], hint) is None
    assert calls == []

    result = await resolver.resolve_hint(SESSION, TRACK, ["qqmusic"], hint)
    assert result is not None and result.source_id == "qqmusic"
    assert [line.text for line in result.document.lines] == ["exact"]
    assert calls == ["003aAYrm3GE0Ac"]


async def test_manual_cache_selection_precedes_exact_hint_and_network():
    calls = []
    selected = artifact(provider="lrclib")
    cache = FakeCache(calls, manual_hit=LyricsCacheHit(selected, LyricsCacheMode.MANUAL))
    resolver = resolver_with_fakes(
        calls,
        cache=cache,
        network_hits={"netease": artifact(provider="netease")},
    )

    result = await resolver.resolve_hint(
        SESSION,
        TRACK,
        ["netease"],
        LyricsHint("netease", "42"),
    )

    assert result is not None
    assert result.source_id == "lrclib"
    assert result.document.origin is LyricsOrigin.MANUAL
    assert result.document.cache_state is LyricsCacheState.MANUAL
    assert calls == []


async def test_manual_cache_selection_is_used_by_ordinary_resolution():
    calls = []
    selected = artifact(provider="lrclib")
    cache = FakeCache(calls, manual_hit=LyricsCacheHit(selected, LyricsCacheMode.MANUAL))
    resolver = resolver_with_fakes(
        calls,
        cache=cache,
        network_hits={"netease": artifact(provider="netease")},
    )

    result = await resolver.resolve(SESSION, TRACK, ["netease"])

    assert result is not None
    assert result.source_id == "lrclib"
    assert result.document.origin is LyricsOrigin.MANUAL
    assert result.document.cache_state is LyricsCacheState.MANUAL
    assert calls == []


async def test_persistent_playback_selection_precedes_matching_and_exact_hint(tmp_path: Path) -> None:
    """Real cache restoration must bypass conflicting provider metadata without HTTP."""
    cache = LyricsCache(tmp_path / "lyrics.sqlite3", worker=BlockingCallRunner("test-selection-resolver"))
    track = TrackMetadata("Playback song (Live)", "Uploader", "Playback album", 200.0)
    selected = artifact()
    resolver = LyricsResolver(
        catalog=catalog_for(
            {"netease": NetworkLyricsSource(
                "netease", netease.fetch_artifact, netease.parse_payload,
                exact_fetch=netease.fetch_artifact_for_song_id,
            )},
            FakeGate([]),
        ),
        cache=cache,
    )
    try:
        await cache.select(track, selected)
        ordinary = await resolver.resolve(None, track, ["netease"])
        hinted = await resolver.resolve_hint(None, track, ["netease"], LyricsHint("netease", "other"))
        for result in (ordinary, hinted):
            assert result is not None
            assert result.document.song_id == selected.provider_song_id
            assert result.document.origin is LyricsOrigin.MANUAL
            assert result.document.cache_state is LyricsCacheState.MANUAL
            assert result.confidence is MatchConfidence.HIGH
        second_track = replace(track, title=track.title.upper())
        await cache.select(second_track, replace(selected, provider_song_id="second"))
        results = await asyncio.gather(
            resolver.resolve(None, track, ["netease"]),
            resolver.resolve(None, second_track, ["netease"]),
        )
        assert results[0] is not None and results[0].document.song_id == selected.provider_song_id
        assert results[1] is not None and results[1].document.song_id == "second"
    finally:
        await resolver.close()


async def test_local_hint_wins_without_using_sources_or_network(monkeypatch, tmp_path: Path):
    audio = tmp_path / "song.flac"

    def sidecar(_audio_path: Path) -> list[LyricLine]:
        return [LyricLine(0, "L0", 1.0, 6.0, "local", "")]

    from kotonoha.lyrics import sources as sources_module

    monkeypatch.setattr(sources_module, "load_sidecar_lyrics", sidecar)
    calls = []
    resolver = resolver_with_fakes(calls, cache_enabled=False, network_hits={"netease": artifact()})

    result = await resolver.resolve_hint(SESSION, TRACK, ["netease"], LyricsHint("local", local_path=audio))

    assert result is not None and result.source_id == "sidecar"
    assert result.confidence is MatchConfidence.HIGH
    assert [line.text for line in result.document.lines] == ["local"]
    assert calls == []


async def test_local_hint_falls_back_to_normal_resolution_when_sidecar_is_empty(monkeypatch, tmp_path: Path):
    audio = tmp_path / "song.flac"
    from kotonoha.lyrics import sources as sources_module

    monkeypatch.setattr(sources_module, "load_sidecar_lyrics", lambda _audio_path: [])
    monkeypatch.setattr(sources_module, "load_embedded_lyrics", lambda _audio_path: [])
    calls = []
    resolver = resolver_with_fakes(calls, cache_enabled=False, network_hits={"netease": artifact()})

    assert await resolver.resolve_hint(SESSION, TRACK, ["netease"], LyricsHint("local", local_path=audio)) is None
    result = await resolver.resolve(SESSION, TRACK, ["netease"])

    assert result is not None and result.source_id == "netease"
    assert calls == ["network:netease"]


async def test_failed_exact_hint_falls_back_to_search(monkeypatch):
    calls = []

    async def exact(_session, _song_id):
        raise TimeoutError

    monkeypatch.setattr("kotonoha.lyrics.netease.fetch_payload", exact)
    resolver = resolver_with_fakes(calls, cache_enabled=False, network_hits={"netease": artifact()})
    hinted = await resolver.resolve_hint(SESSION, TRACK, ["netease"], LyricsHint("netease", "42"))
    assert hinted is None
    result = await resolver.resolve(SESSION, TRACK, ["netease"])
    assert result is not None
    assert calls == ["network:netease"]


async def test_default_order_is_cache_network_per_provider_then_cider():
    calls = []
    resolver = resolver_with_fakes(
        calls,
        cache_hits={},
        network_hits={"lrclib": artifact(provider="lrclib")},
    )

    result = await resolver.resolve(SESSION, TRACK, ["netease", "lrclib", "cider"])

    assert result is not None and result.source_id == "lrclib"
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
    resolver = resolver_with_fakes(calls, cider_match=live_match())

    result = await resolver.resolve(SESSION, TRACK, ["cider", "netease"])

    assert result is not None
    assert result.source_id == "cider"
    assert result.source_kind is LyricsSourceKind.LIVE
    assert result.document.source_id == "apple-music"
    assert calls == ["cider"]


async def test_cache_disabled_skips_reads_and_writes():
    calls = []
    resolver = resolver_with_fakes(calls, cache_enabled=False, network_hits={"netease": artifact()})
    await resolver.resolve(SESSION, TRACK, ["netease"])
    assert calls == ["network:netease"]


async def test_cache_failure_does_not_block_same_provider_network():
    calls = []
    cache = FakeCache(calls, lookup_error=LyricsCacheError("locked"))
    resolver = resolver_with_fakes(calls, cache=cache, network_hits={"netease": artifact()})

    result = await resolver.resolve(SESSION, TRACK, ["netease"])

    assert result is not None and result.source_id == "netease"
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

    async def fetch(session, track, *, fuzzy=False):
        calls.append("network:netease")
        started.set()
        await release.wait()
        return artifact()

    gate = FakeGate(calls)
    resolver = LyricsResolver(
        catalog=catalog_for({"netease": NetworkLyricsSource("netease", fetch, lambda _payload: ())}, gate),
        cache=FakeCache(calls),
        cache_enabled=False,
    )
    first = asyncio.create_task(resolver.resolve(SESSION, TRACK, ["netease"]))
    await started.wait()
    second = asyncio.create_task(resolver.resolve(SESSION, TRACK, ["netease"]))
    release.set()

    first_result, second_result = await asyncio.gather(first, second)

    assert first_result == second_result
    assert calls == ["network:netease"]


async def test_resolver_cancels_shared_network_work_on_shutdown():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fetch(
        session: LyricsSession,
        track: TrackMetadata,
        *,
        fuzzy: bool = False,
    ) -> LyricsArtifact | None:
        del session, track, fuzzy
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    ownership = SourceOwnershipCoordinator()
    resolver = LyricsResolver(
        catalog=catalog_for(
            {"netease": NetworkLyricsSource("netease", fetch, lambda _payload: ())}, ownership
        ),
        cache=FakeCache([]),
        cache_enabled=False,
    )
    request = asyncio.create_task(resolver.resolve(SESSION, TRACK, ["netease"]))
    await started.wait()

    await resolver.cancel_inflight()

    assert cancelled.is_set()
    with pytest.raises(asyncio.CancelledError):
        await request


async def test_network_timeout_log_includes_exception_type(caplog):
    async def timeout(session, track, *, fuzzy=False):
        raise TimeoutError

    gate = FakeGate([])
    resolver = LyricsResolver(
        catalog=catalog_for({"netease": NetworkLyricsSource("netease", timeout, lambda _payload: ())}, gate),
        cache=FakeCache([]),
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
    assert result.source_id == "lrclib"
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
    assert result.source_id == "netease"


async def test_best_mode_line_cider_at_top_allows_network_word_search():
    # A line-timed HIGH may still be improved by words from another source.
    calls = []
    resolver = resolver_with_fakes(calls, prefer_best=True, cider_match=live_match())

    result = await resolver.resolve(SESSION, TRACK, ["cider", "netease"])

    assert result is not None
    assert result.source_id == "cider"
    assert result.document.source_id == "apple-music"
    assert "network:netease" in calls


async def test_best_mode_line_cache_hit_allows_other_sources_to_supply_words():
    # Retain the cache hit when no word upgrade exists, without refetching its source.
    calls = []
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        cache_hits={"netease": artifact(provider="netease")},
    )

    result = await resolver.resolve(SESSION, TRACK, ["netease", "lrclib"])

    assert result is not None
    assert result.source_id == "netease"
    assert "network:netease" not in calls
    assert "network:lrclib" in calls
    assert result.document.origin is LyricsOrigin.CACHE
    assert result.document.cache_state is LyricsCacheState.FROM_CACHE


async def test_best_mode_cider_beats_lower_priority_cache_hit():
    # cider is configured above netease and has a live HIGH match; it must win the
    # HIGH tie over a netease cache hit (configured order breaks the tie), no network.
    calls = []
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        cider_match=live_match(confidence=MatchConfidence.HIGH),
        cache_hits={"netease": artifact(provider="netease")},
    )

    result = await resolver.resolve(SESSION, TRACK, ["cider", "netease"])

    assert result is not None
    assert result.source_id == "cider"
    assert "network:netease" not in calls


async def test_best_mode_medium_cider_does_not_block_a_network_high():
    # A MEDIUM cider match must not short-circuit the network: a genuine network
    # HIGH beats it regardless of cider's position.
    calls = []
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        cider_match=live_match(artist="", confidence=MatchConfidence.MEDIUM),
        network_hits={"netease": artifact(provider="netease", confidence=MatchConfidence.HIGH)},
    )

    result = await resolver.resolve(SESSION, TRACK, ["cider", "netease"])

    assert result is not None
    assert result.source_id == "netease"
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
    assert result.source_id == "netease"
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
    assert result.source_id == "netease"
    assert calls.count("network:netease") == 1


async def test_best_mode_cleans_tasks_when_network_task_creation_fails(monkeypatch):
    from kotonoha.lyrics import resolver as resolver_module

    async def pending_fetch(
        session: LyricsSession,
        track: TrackMetadata,
        *,
        fuzzy: bool,
    ) -> LyricsArtifact | None:
        del session, track, fuzzy
        await asyncio.Event().wait()
        return None

    gate = FakeGate([])
    resolver = LyricsResolver(
        catalog=catalog_for(
            {
                "netease": NetworkLyricsSource("netease", pending_fetch, lambda _payload: ()),
                "lrclib": NetworkLyricsSource("lrclib", pending_fetch, lambda _payload: ()),
            },
            gate,
        ),
        cache=FakeCache([]),
        cache_enabled=False,
        prefer_best=True,
    )
    original_create_owned_task = resolver_module.create_owned_task
    created: list[asyncio.Task[object]] = []
    calls = 0

    def create_with_failure(coroutine, *, name):
        nonlocal calls
        calls += 1
        if calls == 3:
            coroutine.close()
            raise RuntimeError("network task creation failed")
        task = original_create_owned_task(coroutine, name=name)
        created.append(task)
        return task

    monkeypatch.setattr(resolver_module, "create_owned_task", create_with_failure)
    try:
        with pytest.raises(RuntimeError, match="network task creation failed"):
            await resolver.resolve(SESSION, TRACK, ["netease", "lrclib"])
    finally:
        await resolver.close()

    assert len(created) == 2
    assert created[0].done()
    assert created[1].cancelled()


async def test_a_local_lyric_read_does_not_hold_the_event_loop(monkeypatch):
    # The sidecar read and the mutagen tag parse are filesystem and CPU work on the
    # qasync loop that also drives the UI and the MPRIS poll. Called inline they held
    # it for the whole read; the loop must keep running instead.
    import time

    from kotonoha.lyrics import sources as sources_module

    ticks: list[int] = []

    async def ticker() -> None:
        while True:
            await asyncio.sleep(0.01)
            ticks.append(1)

    def blocking_load(audio_path: Path) -> list[LyricLine]:
        del audio_path
        time.sleep(0.2)
        return [LyricLine(0, "L0", 1.0, 6.0, "hello", "")]

    monkeypatch.setattr(sources_module, "load_sidecar_lyrics", blocking_load)
    beat = asyncio.create_task(ticker())
    try:
        resolved = await LyricsResolver(
            catalog=catalog_for({}, SourceOwnershipCoordinator()),
            cache=FakeCache([]),
        ).resolve_hint(
            SESSION, TRACK, ("netease",), LyricsHint("local", local_path=Path("/music/song.flac"))
        )
    finally:
        beat.cancel()

    assert resolved is not None and resolved.document.lines
    assert len(ticks) > 5, f"the loop was blocked for the whole read: {len(ticks)} ticks"


async def test_one_caller_leaving_does_not_cancel_the_other():
    # Identical requests share one task. Awaiting it directly made a cancelled
    # caller cancel it for everyone: the second request raised CancelledError
    # without ever having asked to be cancelled.
    started = asyncio.Event()

    class SlowResolver(LyricsResolver):
        """Stands in for a lookup that is still running when a caller leaves."""

        async def _resolve_once(
            self, session: LyricsSession | None, track: TrackMetadata, sources: tuple[str, ...]
        ) -> ResolverLookup:
            del session, track, sources
            started.set()
            await asyncio.sleep(0.2)
            return ResolverLookup(None)

    resolver = SlowResolver(
        catalog=catalog_for({}, SourceOwnershipCoordinator()),
        cache=FakeCache([]),
    )
    first = asyncio.create_task(resolver.resolve(SESSION, TRACK, ("netease",)))
    await started.wait()
    second = asyncio.create_task(resolver.resolve(SESSION, TRACK, ("netease",)))
    await asyncio.sleep(0)

    first.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await first

    assert await asyncio.wait_for(second, timeout=2) is None


async def test_the_resolver_can_stop_the_work_it_started():
    # The shared task outlives any one caller by design, so its creator needs a
    # cancellation path of its own.
    started = asyncio.Event()

    class NeverResolver(LyricsResolver):
        """Stands in for a lookup that never finishes on its own."""

        async def _resolve_once(
            self, session: LyricsSession | None, track: TrackMetadata, sources: tuple[str, ...]
        ) -> ResolverLookup:
            del session, track, sources
            started.set()
            await asyncio.Event().wait()
            return ResolverLookup(None)

    resolver = NeverResolver(
        catalog=catalog_for({}, SourceOwnershipCoordinator()),
        cache=FakeCache([]),
    )
    caller = asyncio.create_task(resolver.resolve(SESSION, TRACK, ("netease",)))
    await started.wait()

    await resolver.cancel_inflight()

    assert resolver._inflight == {}
    caller.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await caller
