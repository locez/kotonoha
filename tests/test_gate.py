from kotonoha.config import Config
from kotonoha.lyrics.match import TrackMetadata
from kotonoha.model import LyricsSnapshot
from kotonoha.providers.gate import SourceGate


def test_gate_default_accepts_ws():
    # With no external source consulted (e.g. dbus down), Cider keeps working.
    assert SourceGate().accept_ws is True


def test_gate_set():
    gate = SourceGate()
    gate.set_accept_ws(False)
    assert gate.accept_ws is False
    gate.set_accept_ws(True)
    assert gate.accept_ws is True


def test_closed_gate_retains_matching_snapshot_without_publishing():
    gate = SourceGate()
    gate.select_external()
    snapshot = LyricsSnapshot(found=True, title="Song", artist="Artist", song_id="am-1")
    gate.observe_snapshot(10, snapshot)

    match = gate.current_match(TrackMetadata("Song", "Artist"))

    assert match is not None
    assert match.client_id == 10
    assert gate.accepts(10) is False


def test_select_cider_binds_one_connection_and_ticks_follow_binding():
    gate = SourceGate()
    gate.observe_snapshot(10, LyricsSnapshot(found=True, title="Song", artist="Artist"))
    gate.select_cider(10)
    assert gate.accepts(10) is True
    assert gate.accepts(20) is False
    assert gate.cider_active is True
    gate.drop_client(10)
    assert gate.cider_active is False


def test_selected_cider_becomes_inactive_when_snapshot_has_no_lyrics():
    gate = SourceGate()
    gate.observe_snapshot(10, LyricsSnapshot(found=True, title="Song", artist="Artist"))
    gate.select_cider(10)
    gate.observe_snapshot(10, LyricsSnapshot(found=False, title="Song", artist="Artist"))
    assert gate.cider_active is False


def test_cider_match_rejects_different_track():
    gate = SourceGate()
    gate.observe_snapshot(10, LyricsSnapshot(found=True, title="Other", artist="Artist"))
    assert gate.current_match(TrackMetadata("Song", "Artist")) is None


def test_matching_cider_tick_is_available_without_selecting_cider_lyrics():
    gate = SourceGate()
    gate.observe_snapshot(10, LyricsSnapshot(found=False, title="Song", artist="Artist"))
    gate.observe_tick(10, 12.5, True)
    gate.select_external()

    timing = gate.current_timing(TrackMetadata("Song", "Artist"))

    assert timing is not None
    assert timing.client_id == 10
    assert timing.current_time == 12.5
    assert timing.is_playing is True
    assert gate.accepts(10) is False


def test_cider_tick_rejects_a_different_track():
    gate = SourceGate()
    gate.observe_snapshot(10, LyricsSnapshot(found=False, title="Other", artist="Artist"))
    gate.observe_tick(10, 12.5, True)

    assert gate.current_timing(TrackMetadata("Song", "Artist")) is None


def test_cider_exact_title_can_cover_transient_missing_mpris_artist():
    gate = SourceGate()
    gate.observe_snapshot(10, LyricsSnapshot(found=True, title="Song", artist="Artist"))
    assert gate.current_match(TrackMetadata("Song", "")) is not None


def test_lyrics_sources_default():
    assert Config().lyrics_sources == ["netease", "lrclib", "cider"]


def test_lyrics_sources_cleaned():
    cfg = Config(lyrics_sources=["cider", "bogus", "netease", "netease"]).clamped()
    assert cfg.lyrics_sources == ["cider", "netease"]  # unknown dropped, deduped, order kept


def test_lyrics_sources_empty_falls_back():
    assert Config(lyrics_sources=[]).clamped().lyrics_sources == ["netease", "lrclib", "cider"]
    assert Config(lyrics_sources=["nope"]).clamped().lyrics_sources == ["netease", "lrclib", "cider"]


def test_lyrics_sources_roundtrip():
    cfg = Config.from_dict({"lyrics_sources": ["lrclib", "netease"]})
    assert cfg.lyrics_sources == ["lrclib", "netease"]
