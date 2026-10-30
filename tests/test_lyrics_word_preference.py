"""Word timing must compete across live, cached, hinted, and network lyrics."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from test_lyrics_resolver import (
    SESSION,
    TRACK,
    FakeCache,
    FakeGate,
    artifact,
    catalog_for,
    live_match,
    resolver_with_fakes,
)

from kotonoha.async_worker import BlockingCallRunner
from kotonoha.lyrics import netease
from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.cache import LyricsCache, LyricsCacheHit, LyricsCacheMode
from kotonoha.lyrics.hint import LyricsHint
from kotonoha.lyrics.http import LyricsSession
from kotonoha.lyrics.match import MatchConfidence, TrackMetadata
from kotonoha.lyrics.models import LyricLine, LyricsCacheState, LyricWord, TimingKind
from kotonoha.lyrics.network_sources import NetworkLyricsSource
from kotonoha.lyrics.resolver import LyricsResolver


def word_artifact(
    provider: str = "lrclib", confidence: MatchConfidence = MatchConfidence.HIGH,
) -> LyricsArtifact:
    """Use Enhanced LRC to prove selection depends on timings, not format names."""
    return replace(
        artifact(provider=provider, confidence=confidence),
        payload={"lrc": "[00:01]<00:01>word<00:02> lyrics<00:03>"},
        lines=(LyricLine(0, "L0", 1.0, 3.0, "word lyrics", "", (
            LyricWord(1.0, 2.0, "word"), LyricWord(2.0, 3.0, " lyrics"),
        )),),
    )


@pytest.mark.parametrize("line_source", ["network", "cache", "live"])
async def test_word_lyrics_beat_equally_confident_line_lyrics(line_source: str) -> None:
    calls: list[str] = []
    resolver = resolver_with_fakes(
        calls,
        prefer_best=True,
        cache_hits={"netease": artifact()} if line_source == "cache" else {},
        network_hits={
            "netease": artifact() if line_source == "network" else None,
            "lrclib": word_artifact(),
        },
        cider_match=live_match() if line_source == "live" else None,
    )
    try:
        result = await resolver.resolve(SESSION, TRACK, ["cider", "netease", "lrclib"])
        assert result is not None and result.source_id == "lrclib"
        assert result.document.has_word_timing
    finally:
        await resolver.close()


async def test_cached_words_beat_earlier_live_line_lyrics() -> None:
    resolver = resolver_with_fakes(
        [], prefer_best=True, cider_match=live_match(), cache_hits={"lrclib": word_artifact()},
    )
    try:
        result = await resolver.resolve(SESSION, TRACK, ["cider", "lrclib"])
        assert result is not None and result.source_id == "lrclib"
        assert result.document.cache_state is LyricsCacheState.FROM_CACHE
    finally:
        await resolver.close()


@pytest.mark.parametrize("scenario", ["lower-confidence", "sequential", "manual", "no-word-spans"])
async def test_word_preference_preserves_identity_and_explicit_choices(scenario: str) -> None:
    words = word_artifact(confidence=MatchConfidence.MEDIUM if scenario == "lower-confidence" else MatchConfidence.HIGH)
    match = live_match()
    if scenario == "no-word-spans":
        # A claimed Word format with no spans cannot beat real line timing.
        match = replace(match, document=replace(match.document, timing=TimingKind.WORD))
    cache = FakeCache([], manual_hit=LyricsCacheHit(artifact(), LyricsCacheMode.MANUAL))
    resolver = resolver_with_fakes(
        [], prefer_best=scenario != "sequential",
        cache=cache if scenario == "manual" else None,
        network_hits={"netease": artifact(), "lrclib": words},
        cider_match=match if scenario == "no-word-spans" else None,
    )
    try:
        sources = ["netease", "cider"] if scenario == "no-word-spans" else ["netease", "lrclib"]
        result = await resolver.resolve(SESSION, TRACK, sources)
        assert result is not None and result.source_id == "netease"
    finally:
        await resolver.close()


async def test_line_result_does_not_cancel_a_pending_word_candidate() -> None:
    line_returned = asyncio.Event()
    release_words = asyncio.Event()
    words_started = asyncio.Event()
    words_cancelled = asyncio.Event()

    async def line_fetch(session: LyricsSession, track: TrackMetadata, *, fuzzy: bool) -> LyricsArtifact:
        await words_started.wait()
        line_returned.set()
        return artifact()

    async def word_fetch(session: LyricsSession, track: TrackMetadata, *, fuzzy: bool) -> LyricsArtifact:
        words_started.set()
        try:
            await release_words.wait()
        except asyncio.CancelledError:
            words_cancelled.set()
            raise
        return word_artifact()

    resolver = LyricsResolver(
        catalog=catalog_for({
            "netease": NetworkLyricsSource("netease", line_fetch, netease.parse_payload),
            "lrclib": NetworkLyricsSource("lrclib", word_fetch, netease.parse_payload),
        }, FakeGate([])),
        cache=FakeCache([]), cache_enabled=False,
    )
    request = asyncio.create_task(resolver.resolve(SESSION, TRACK, ["netease", "lrclib"]))
    try:
        await asyncio.wait_for(line_returned.wait(), 1.0)
        # A sentinel source request ensures the resolver has handled ready tasks.
        await resolver.resolve(SESSION, TRACK, [])
        release_words.set()
        result = await request
        assert not words_cancelled.is_set()
        assert result is not None and result.source_id == "lrclib"
    finally:
        release_words.set()
        await resolver.close()
        await asyncio.gather(request, return_exceptions=True)


async def test_exact_line_hint_can_be_upgraded_by_matching_words(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exact(session: LyricsSession, song_id: str) -> dict[str, str]:
        return {"lrc": "[00:01]exact line"}

    monkeypatch.setattr(netease, "fetch_payload", exact)
    resolver = resolver_with_fakes([], prefer_best=True, network_hits={"lrclib": word_artifact()})
    try:
        result = await resolver.resolve_hint(SESSION, TRACK, ["netease", "lrclib"], LyricsHint("netease", "42"))
        assert result is not None and result.source_id == "lrclib"
        assert result.document.has_word_timing
    finally:
        await resolver.close()


@pytest.mark.parametrize("location", ["cache", "live"])
async def test_top_priority_words_keep_the_no_network_fast_path(location: str) -> None:
    calls: list[str] = []
    match = live_match()
    match = replace(match, document=replace(match.document, timing=TimingKind.WORD, lines=word_artifact().lines))
    resolver = resolver_with_fakes(
        calls, prefer_best=True,
        cache_hits={"netease": word_artifact("netease")} if location == "cache" else {},
        cider_match=match if location == "live" else None,
    )
    try:
        result = await resolver.resolve(SESSION, TRACK, ["cider", "netease", "lrclib"])
        assert result is not None and result.document.has_word_timing
        assert not any(call.startswith("network:") for call in calls)
    finally:
        await resolver.close()


@pytest.mark.parametrize("prefer_best", [True, False])
async def test_hint_keeps_exact_line_when_no_eligible_word_upgrade_exists(
    monkeypatch: pytest.MonkeyPatch, prefer_best: bool,
) -> None:
    async def exact(session: LyricsSession, song_id: str) -> dict[str, str]:
        return {"lrc": "[00:01]exact line"}

    monkeypatch.setattr(netease, "fetch_payload", exact)
    resolver = resolver_with_fakes(
        [], prefer_best=prefer_best,
        network_hits={"lrclib": word_artifact(confidence=MatchConfidence.MEDIUM)},
    )
    try:
        result = await resolver.resolve_hint(SESSION, TRACK, ["netease", "lrclib"], LyricsHint("netease", "42"))
        assert result is not None and result.document.song_id == "42"
        assert result.document.lines[0].text == "exact line"
    finally:
        await resolver.close()


async def test_real_cache_restores_words_and_wins_over_earlier_lines(tmp_path: Path) -> None:
    cache = LyricsCache(tmp_path / "lyrics.sqlite3", worker=BlockingCallRunner("test-word-cache"))
    resolver = LyricsResolver(
        catalog=catalog_for({
            "netease": NetworkLyricsSource("netease", netease.fetch_artifact, netease.parse_payload),
        }, FakeGate([], live_match())), cache=cache,
    )
    try:
        await cache.store(word_artifact("netease"))
        result = await resolver.resolve(None, TRACK, ["cider", "netease"])
        assert result is not None and result.source_id == "netease"
        assert result.document.has_word_timing
        assert result.document.lines[0].text == "word lyrics"
        assert result.document.lines[0].words == (
            LyricWord(1.0, 2.0, "word"), LyricWord(2.0, 3.0, " lyrics"),
        )
        assert result.document.cache_state is LyricsCacheState.FROM_CACHE
    finally:
        await resolver.close()


async def test_local_line_hint_can_be_upgraded_by_matching_network_words(tmp_path: Path) -> None:
    audio = tmp_path / "song.flac"
    audio.with_suffix(".lrc").write_text("[00:01]local line", encoding="utf-8")
    resolver = resolver_with_fakes([], prefer_best=True, network_hits={"lrclib": word_artifact()})
    try:
        result = await resolver.resolve_hint(SESSION, TRACK, ["lrclib"], LyricsHint("local", local_path=audio))
        assert result is not None and result.source_id == "lrclib"
        assert result.document.has_word_timing
    finally:
        await resolver.close()
