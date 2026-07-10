import sqlite3

from kotonoha.lyrics import netease
from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.cache import LyricsCache
from kotonoha.lyrics.match import MatchConfidence, TrackMetadata
from kotonoha.model import LyricLine


def artifact(
    *,
    provider: str = "netease",
    provider_song_id: str = "1",
    confidence: MatchConfidence = MatchConfidence.HIGH,
) -> LyricsArtifact:
    payload = (
        {"lrc": "[00:01.00]line", "yrc": "", "tlyric": ""}
        if provider == "netease"
        else {"syncedLyrics": "[00:01.00]line"}
    )
    return LyricsArtifact(
        provider=provider,
        provider_song_id=provider_song_id,
        title="Song",
        artist="Artist",
        album="Album",
        duration_s=180.0,
        payload=payload,
        lines=(LyricLine(0, "L0", 1.0, 6.0, "line", ""),),
        confidence=confidence,
    )


async def test_lookup_is_scoped_to_provider_and_matches_metadata(tmp_path):
    cache = LyricsCache(tmp_path / "lyrics.sqlite3", max_entries=10)
    await cache.store(artifact(provider="netease", provider_song_id="1"))
    await cache.store(artifact(provider="lrclib", provider_song_id="2"))

    track = TrackMetadata("Ｓｏｎｇ", "Artist", "Album", 180.0)
    hit = await cache.lookup("netease", track, netease.parse_payload)

    assert hit is not None
    assert hit.provider == "netease"
    assert hit.provider_song_id == "1"


async def test_lookup_does_not_require_player_track_or_search_key(tmp_path):
    path = tmp_path / "lyrics.sqlite3"
    cache = LyricsCache(path)
    await cache.store(artifact())

    hit = await cache.lookup("netease", TrackMetadata("Song", "Artist", "", 180.0), netease.parse_payload)
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(lyrics)")}

    assert hit is not None
    assert not columns & {"player", "track_id", "search_key", "query", "alias"}


async def test_only_high_confidence_artifacts_are_persisted(tmp_path):
    cache = LyricsCache(tmp_path / "lyrics.sqlite3")
    await cache.store(artifact(confidence=MatchConfidence.MEDIUM))
    assert await cache.count() == 0


async def test_invalid_payload_is_removed(tmp_path):
    path = tmp_path / "lyrics.sqlite3"
    cache = LyricsCache(path)
    await cache.store(artifact())
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE lyrics SET payload_json = ?", ("not json",))

    hit = await cache.lookup("netease", TrackMetadata("Song", "Artist", "Album", 180.0), netease.parse_payload)

    assert hit is None
    assert await cache.count() == 0


async def test_clear_and_lru_pruning(tmp_path):
    cache = LyricsCache(tmp_path / "lyrics.sqlite3", max_entries=2)
    await cache.store(artifact(provider_song_id="1"))
    await cache.store(artifact(provider_song_id="2"))
    await cache.store(artifact(provider_song_id="3"))
    assert await cache.count() == 2
    await cache.clear()
    assert await cache.count() == 0
