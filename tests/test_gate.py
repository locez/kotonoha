from kotonoha.app.source_gate import SourceOwnershipCoordinator
from kotonoha.config import Config
from kotonoha.lyrics.match import MatchConfidence, TrackMetadata
from kotonoha.lyrics.models import LyricLine, LyricsDocument, TimingKind
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity


def source_facts(
    *,
    found=True,
    title="Song",
    artist="Artist",
    album="",
    duration_s=None,
    adapter_id="cider",
):
    lines = (LyricLine(0, "L0", 0.0, 5.0, title, ""),) if found else ()
    document = LyricsDocument(
        source_id="apple-music",
        title=title,
        artist=artist,
        album=album,
        duration_s=duration_s,
        timing=TimingKind.LINE if lines else None,
        lines=lines,
    )
    track = TrackIdentity(
        adapter_id,
        adapter_id,
        stable_id="song-1",
        title=title,
        artist=artist,
        album=album,
        duration_s=duration_s,
    )
    observation = PlaybackObservation(
        adapter_id, adapter_id, track, PlaybackStatus.PLAYING, 12.5, duration_s, 1.0
    )
    return observation, document


def observe(coordinator, client_id=10, **kwargs):
    observation, document = source_facts(**kwargs)
    coordinator.observe(client_id, observation, document)
    return observation


def test_closed_ownership_retains_matching_document_without_publishing():
    coordinator = SourceOwnershipCoordinator()
    coordinator.select_external()
    observe(coordinator)

    match = coordinator.current_match(TrackMetadata("Song", "Artist"))

    assert match is not None
    assert match.client_id == 10
    assert match.document.source_id == "apple-music"
    assert coordinator.accepts(10) is False


def test_select_live_binds_one_connection_and_ticks_follow_binding():
    coordinator = SourceOwnershipCoordinator()
    observation = observe(coordinator)
    coordinator.select_live(10)
    assert coordinator.accepts(10) is True
    assert coordinator.accepts(20) is False
    assert coordinator.live_active is True
    assert coordinator.observe_clock(10, observation.track.track_ref, 12.5, True) is True
    coordinator.drop_client(10)
    assert coordinator.live_active is False


def test_selected_live_source_becomes_inactive_when_document_has_no_lyrics():
    coordinator = SourceOwnershipCoordinator()
    observe(coordinator)
    coordinator.select_live(10)
    observe(coordinator, found=False)
    assert coordinator.live_active is False


def test_live_match_rejects_different_track():
    coordinator = SourceOwnershipCoordinator()
    observe(coordinator, title="Other")
    assert coordinator.current_match(TrackMetadata("Song", "Artist")) is None


def test_matching_live_clock_is_available_without_selecting_live_lyrics():
    coordinator = SourceOwnershipCoordinator()
    observation = observe(coordinator, found=False, duration_s=194.222)
    assert coordinator.observe_clock(10, observation.track.track_ref, 12.5, True) is True
    coordinator.select_external()

    timing = coordinator.current_timing(TrackMetadata("Song", "Artist"))

    assert timing is not None
    assert timing.client_id == 10
    assert timing.current_time == 12.5
    assert timing.is_playing is True
    assert timing.duration_s == 194.222
    assert coordinator.accepts(10) is False


def test_live_clock_rejects_a_different_track_reference():
    coordinator = SourceOwnershipCoordinator()
    observe(coordinator, found=False, title="Other")

    assert coordinator.observe_clock(10, "cider:cider:other-song", 12.5, True) is False
    assert coordinator.current_timing(TrackMetadata("Song", "Artist")) is None


def test_live_exact_title_can_cover_transient_missing_mpris_artist():
    coordinator = SourceOwnershipCoordinator()
    observe(coordinator)
    assert coordinator.current_match(TrackMetadata("Song", "")) is not None


def test_current_match_reports_high_confidence_for_a_full_identity():
    coordinator = SourceOwnershipCoordinator()
    observe(coordinator)
    match = coordinator.current_match(TrackMetadata("Song", "Artist"))
    assert match is not None
    assert match.confidence is MatchConfidence.HIGH


def test_current_match_reports_medium_confidence_for_a_title_only_match():
    coordinator = SourceOwnershipCoordinator()
    observe(coordinator, artist="Someone Else")
    match = coordinator.current_match(TrackMetadata("Song", ""))
    assert match is not None
    assert match.confidence is MatchConfidence.MEDIUM


def test_standalone_owner_follows_display_priority_instead_of_latest_event():
    coordinator = SourceOwnershipCoordinator(display_sources=["adapter", "cider"])
    observe(coordinator, client_id="cider-api", adapter_id="cider")
    observe(coordinator, client_id=20, adapter_id="adapter")

    match = coordinator.current_match(TrackMetadata("Song", "Artist"))

    assert match is not None
    assert match.client_id == 20
    assert coordinator.accepts(20) is True
    assert coordinator.accepts("cider-api") is False


def test_disabled_display_source_cannot_become_owner_or_match():
    coordinator = SourceOwnershipCoordinator(display_sources=["adapter"])
    observe(coordinator, client_id="cider-api", adapter_id="cider")

    assert coordinator.current_match(TrackMetadata("Song", "Artist")) is None
    assert coordinator.accepts("cider-api") is False


def test_display_sources_default():
    assert Config().display_sources == ["mpris", "cider", "adapter"]


def test_display_sources_cleaned_and_roundtripped():
    cfg = Config.from_dict({"display_sources": ["adapter", "bogus", "adapter", "cider"]})

    assert cfg.display_sources == ["adapter", "cider"]


def test_lyrics_sources_default() -> None:
    """The initial source order contains network providers without Cider polling."""
    assert Config().lyrics_sources == ["amll", "netease", "kugou", "lrclib"]


def test_best_lyrics_matching_is_enabled_by_default():
    assert Config().prefer_best_lyrics is True


def test_lyrics_sources_cleaned():
    cfg = Config(lyrics_sources=["cider", "bogus", "netease", "netease"]).clamped()
    assert cfg.lyrics_sources == ["cider", "netease"]


def test_lyrics_sources_empty_falls_back() -> None:
    """Invalid source selections restore defaults without enabling Cider."""
    assert Config(lyrics_sources=[]).clamped().lyrics_sources == ["amll", "netease", "kugou", "lrclib"]
    assert Config(lyrics_sources=["nope"]).clamped().lyrics_sources == [
        "amll",
        "netease",
        "kugou",
        "lrclib",
    ]


def test_lyrics_sources_roundtrip():
    cfg = Config.from_dict({"lyrics_sources": ["lrclib", "netease"]})
    assert cfg.lyrics_sources == ["lrclib", "netease"]
