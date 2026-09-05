import asyncio
import logging

from kotonoha.app.display_coordinator import DisplayCoordinator
from kotonoha.clock import MediaClock
from kotonoha.display.models import DisplayOptions, LyricsDisplayStatus, ResolutionState
from kotonoha.display.offsets import track_offset_key
from kotonoha.display.presentation import DisplayEngine
from kotonoha.display.timeline import TimelineEngine
from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.match import MatchConfidence, TrackMetadata
from kotonoha.lyrics.models import LyricLine, LyricsCacheState, LyricsDocument, LyricsOrigin, TimingKind
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from kotonoha.ui.overlay.publisher import QtDisplayPublisher
from kotonoha.ui.overlay.state import LyricsState


class _FailingTimeline(TimelineEngine):
    def advance(self) -> PlaybackObservation | None:
        raise RuntimeError("timeline failed")


async def test_display_stop_observes_a_completed_clock_task_failure(caplog):
    coordinator = DisplayCoordinator(
        QtDisplayPublisher(LyricsState()),
        presenter=DisplayEngine(),
        timeline=_FailingTimeline(),
    )

    with caplog.at_level(logging.ERROR):
        await coordinator.start()
        await asyncio.sleep(0)
        await coordinator.stop()

    assert "Display clock task failed: timeline failed" in caplog.text


class _FakeMonotonic:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def test_display_tick_does_not_revert_to_a_lagging_polled_line():
    monotonic = _FakeMonotonic()
    timeline = TimelineEngine(MediaClock(monotonic=monotonic))
    state = LyricsState()
    coordinator = DisplayCoordinator(QtDisplayPublisher(state), presenter=DisplayEngine(), timeline=timeline)
    track = TrackIdentity("test", "player", stable_id="song", title="Song", artist="Artist")
    playback = PlaybackObservation("test", "player", track, PlaybackStatus.PLAYING, 4.8, 10.0, 100.0)
    document = LyricsDocument(
        "test",
        timing=TimingKind.LINE,
        duration_s=10.0,
        lines=(
            LyricLine(0, "line-0", 0.0, 5.0, "first", ""),
            LyricLine(1, "line-1", 5.0, 10.0, "second", ""),
        ),
    )

    coordinator.publish_resolution(playback, document, ResolutionState.AVAILABLE)
    monotonic.value = 100.3
    coordinator.tick(5.0, PlaybackStatus.PLAYING)
    assert state.frame.current is not None
    assert state.frame.current.id == "line-1"


    # A coarse player sample can lag the smooth clock just after the boundary.
    monotonic.value = 100.4
    coordinator.tick(4.9, PlaybackStatus.PLAYING)

    assert state.frame.current is not None
    assert state.frame.current.id == "line-1"


def test_set_options_reprojects_the_active_frame_with_a_new_track_offset():
    state = LyricsState()
    coordinator = DisplayCoordinator(
        QtDisplayPublisher(state),
        presenter=DisplayEngine(),
        timeline=TimelineEngine(),
    )
    track = TrackIdentity("test", "player", stable_id="song", title="Song", artist="Artist")
    playback = PlaybackObservation("test", "player", track, PlaybackStatus.PAUSED, 0.0, 10.0, 100.0)
    document = LyricsDocument(
        "test",
        title="Song",
        artist="Artist",
        timing=TimingKind.LINE,
        duration_s=10.0,
        lines=(
            LyricLine(0, "line-0", 0.0, 1.0, "first", ""),
            LyricLine(1, "line-1", 1.0, 2.0, "second", ""),
        ),
    )

    coordinator.publish_resolution(playback, document, ResolutionState.AVAILABLE)
    assert state.frame.current is not None
    assert state.frame.current.id == "line-0"
    key = track_offset_key(track, document)
    assert key is not None

    coordinator.set_options(DisplayOptions(track_offsets_ms={key: 1000}))

    assert state.frame.current_time == 1.0
    assert state.frame.current is not None
    assert state.frame.current.id == "line-1"


def test_display_logs_active_source_once_per_document_and_resets_after_clear(caplog):
    state = LyricsState()
    coordinator = DisplayCoordinator(
        QtDisplayPublisher(state),
        presenter=DisplayEngine(),
        timeline=TimelineEngine(),
    )
    track = TrackIdentity("test", "player", stable_id="song", title="Song", artist="Artist")
    playback = PlaybackObservation("test", "player", track, PlaybackStatus.PLAYING, 1.0, 10.0, 100.0)
    first_document = LyricsDocument(
        "lrclib",
        source_name="LRCLIB",
        song_id="song-1",
        timing=TimingKind.LINE,
        duration_s=10.0,
        lines=(
            LyricLine(0, "line-0", 0.0, 5.0, "first", ""),
            LyricLine(1, "line-1", 5.0, 10.0, "second", ""),
        ),
    )
    second_document = LyricsDocument(
        "netease",
        source_name="Netease",
        song_id="song-1",
        timing=TimingKind.LINE,
        duration_s=10.0,
        lines=first_document.lines,
    )

    with caplog.at_level(logging.DEBUG):
        coordinator.publish_resolution(playback, first_document, ResolutionState.AVAILABLE)
        coordinator.tick(2.0, PlaybackStatus.PLAYING)
        coordinator.tick(6.0, PlaybackStatus.PLAYING)
        coordinator.publish_resolution(playback, first_document, ResolutionState.AVAILABLE)
        coordinator.publish_resolution(playback, second_document, ResolutionState.AVAILABLE)
        coordinator.publish_resolution(playback, None, ResolutionState.NOT_FOUND)
        coordinator.publish_resolution(playback, first_document, ResolutionState.AVAILABLE)

    messages = [record.getMessage() for record in caplog.records]
    active = [message for message in messages if "LYRICS DISPLAY ACTIVE" in message]
    assert len(active) == 3
    assert sum("lyric_source='LRCLIB'" in message for message in active) == 2
    assert any("lyric_source='Netease'" in message and "source_id='netease'" in message for message in active)
    assert all("provider_name" not in message for message in active)
    assert all("display lyric line changed" not in message for message in messages)


def test_manual_lyrics_replace_the_active_document_and_survive_late_provider_results():
    state = LyricsState()
    coordinator = DisplayCoordinator(
        QtDisplayPublisher(state),
        presenter=DisplayEngine(),
        timeline=TimelineEngine(),
    )
    track = TrackIdentity("test", "player", stable_id="song", title="Song", artist="Artist", album="Album")
    playback = PlaybackObservation("test", "player", track, PlaybackStatus.PLAYING, 1.0, 10.0, 100.0)
    automatic_document = LyricsDocument(
        "lrclib",
        source_name="LRCLIB",
        song_id="automatic",
        timing=TimingKind.LINE,
        duration_s=10.0,
        lines=(LyricLine(0, "auto", 0.0, 10.0, "automatic", ""),),
    )
    manual_artifact = LyricsArtifact(
        provider="netease",
        provider_song_id="manual",
        title="Song (selected)",
        artist="Artist",
        album="Album",
        duration_s=10.0,
        payload={"lrc": "[00:00.00]selected"},
        lines=(LyricLine(0, "manual", 0.0, 10.0, "selected", ""),),
        confidence=MatchConfidence.MEDIUM,
    )

    coordinator.publish_resolution(playback, automatic_document, ResolutionState.AVAILABLE)

    assert coordinator.apply_manual_artifact(
        manual_artifact,
        TrackMetadata("Song", "Artist", "Album", 10.0),
    ) is True
    assert state.frame.document is not None
    assert state.frame.document.song_id == "manual"
    status = coordinator.current_lyrics_status()
    assert status == LyricsDisplayStatus(
        playback_source="test",
        lyrics_source_id="netease",
        lyrics_source_name="netease",
        origin=LyricsOrigin.MANUAL,
        cache_state=LyricsCacheState.MANUAL,
        lyrics_song_id=status.lyrics_song_id,
        lyrics_title=status.lyrics_title,
        lyrics_artist=status.lyrics_artist,
        lyrics_album=status.lyrics_album,
    )
    # The status also carries what the document says the track is, which a player
    # reporting only a page title does not know.
    assert status.lyrics_title == "Song (selected)"

    # A provider response that was already in flight must not overwrite the
    # user's choice while the same track remains active.
    coordinator.publish_resolution(playback, automatic_document, ResolutionState.AVAILABLE)
    assert state.frame.document is not None
    assert state.frame.document.song_id == "manual"

    next_track = TrackIdentity("test", "player", stable_id="next", title="Next", artist="Artist", album="Album")
    next_playback = PlaybackObservation(
        "test", "player", next_track, PlaybackStatus.PLAYING, 1.0, 10.0, 101.0
    )
    coordinator.publish_resolution(next_playback, automatic_document, ResolutionState.AVAILABLE)
    assert state.frame.document is automatic_document
    assert coordinator.current_lyrics_status().origin is LyricsOrigin.NETWORK
    assert coordinator.current_lyrics_status().cache_state is LyricsCacheState.NONE


def test_set_options_reprojects_a_small_offset_across_a_line_boundary():
    state = LyricsState()
    coordinator = DisplayCoordinator(
        QtDisplayPublisher(state),
        presenter=DisplayEngine(),
        timeline=TimelineEngine(),
    )
    track = TrackIdentity("test", "player", stable_id="song", title="Song", artist="Artist")
    playback = PlaybackObservation("test", "player", track, PlaybackStatus.PAUSED, 0.98, 2.0, 100.0)
    document = LyricsDocument(
        "test",
        title="Song",
        artist="Artist",
        timing=TimingKind.LINE,
        duration_s=2.0,
        lines=(
            LyricLine(0, "line-0", 0.0, 1.0, "first", ""),
            LyricLine(1, "line-1", 1.0, 2.0, "second", ""),
        ),
    )

    coordinator.publish_resolution(playback, document, ResolutionState.AVAILABLE)
    key = track_offset_key(track, document)
    assert key is not None
    assert state.frame.current_time == 0.98
    assert state.frame.current is not None
    assert state.frame.current.id == "line-0"

    coordinator.set_options(DisplayOptions(track_offsets_ms={key: 50}))

    assert state.frame.current_time == 1.03
    assert state.frame.current is not None
    assert state.frame.current.id == "line-1"
