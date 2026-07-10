import asyncio
from typing import cast

import aiohttp

from kotonoha.lyrics import lrclib, netease
from kotonoha.lyrics.match import Candidate, MatchConfidence, TrackMetadata

SESSION = cast(aiohttp.ClientSession, None)


def async_return(value):
    async def result(*_args, **_kwargs):
        return value

    return result


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

    assert queries == ["Song (Remastered 2011) Artist feat. Guest", "Song Artist"]
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
