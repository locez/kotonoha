import asyncio

from kotonoha.lyrics.resolver import ResolvedLyrics
from kotonoha.model import LyricLine, LyricsSnapshot
from kotonoha.providers.gate import SourceGate
from kotonoha.providers.mpris import PLAYER_IFACE, MprisProvider, TrackCommit, TrackInfo
from kotonoha.state import LyricsState

VALID_METADATA = {
    "xesam:title": "Song",
    "xesam:artist": ["Artist"],
    "xesam:album": "Album",
    "mpris:length": 180_000_000,
    "mpris:trackid": "/track/1",
}


class FakePlayer:
    def __init__(self, metadata, *, position=0, position_error=None):
        self.metadata = metadata
        self.position = position
        self.position_error = position_error

    async def get_playback_status(self):
        return "Playing"

    async def get_metadata(self):
        return self.metadata

    async def get_position(self):
        if self.position_error is not None:
            raise self.position_error
        return self.position


class SequencedMetadataPlayer(FakePlayer):
    def __init__(self, metadata_sequence):
        super().__init__(metadata={})
        self.metadata_sequence = iter(metadata_sequence)

    async def get_metadata(self):
        return next(self.metadata_sequence)


class RecordingResolver:
    def __init__(self, result=None):
        self.tracks = []
        self.result = result

    async def resolve(self, _session, track, _sources):
        self.tracks.append(track)
        return self.result

    def reset_memory(self):
        return None

    def set_cache_enabled(self, _enabled):
        return None

    async def clear_cache(self):
        return None


class BlockingResolver(RecordingResolver):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled_generations = []

    async def resolve(self, _session, track, _sources):
        self.tracks.append(track)
        if track.title != "A":
            return None
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled_generations.append(1)
            raise


class DeferredResolver(RecordingResolver):
    def __init__(self, result=None):
        super().__init__(result)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def resolve(self, _session, track, _sources):
        self.tracks.append(track)
        self.started.set()
        await self.release.wait()
        return self.result


def track_commit(generation, title, artist):
    return TrackCommit(
        generation=generation,
        player_name="org.mpris.MediaPlayer2.test",
        info=TrackInfo(title, artist, "", 180.0, f"/{generation}"),
    )


def prepare_poll(provider, player):
    async def active_player():
        return player, "org.mpris.MediaPlayer2.test"

    async def subscribed(_name):
        return None

    provider._active_player = active_player
    provider._ensure_subscribed = subscribed


async def test_position_failure_does_not_block_lyric_resolution():
    player = FakePlayer(metadata=VALID_METADATA, position_error=RuntimeError("unsupported"))
    resolver = RecordingResolver()
    provider = MprisProvider(LyricsState(), resolver=resolver, poll_interval=0.01)
    prepare_poll(provider, player)

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)
    assert provider._load_task is not None
    await provider._load_task

    assert resolver.tracks[0].title == "Song"


async def test_empty_metadata_never_reaches_resolver():
    resolver = RecordingResolver()
    provider = MprisProvider(LyricsState(), resolver=resolver)
    prepare_poll(provider, FakePlayer(metadata={"mpris:trackid": "/track/1"}))

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=1.0)

    assert resolver.tracks == []
    assert provider._load_task is None


async def test_metadata_changed_during_sample_is_discarded():
    mixed = dict(VALID_METADATA, **{"xesam:artist": ["Old Artist"]})
    player = SequencedMetadataPlayer([mixed, VALID_METADATA, VALID_METADATA, VALID_METADATA])
    resolver = RecordingResolver()
    provider = MprisProvider(LyricsState(), resolver=resolver)
    prepare_poll(provider, player)

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)

    assert resolver.tracks == []


async def test_duration_drift_during_metadata_sample_does_not_block_resolution():
    samples = [
        dict(VALID_METADATA, **{"mpris:length": duration})
        for duration in (180_000_000, 181_000_000, 182_000_000, 183_000_000)
    ]
    player = SequencedMetadataPlayer(samples)
    resolver = RecordingResolver()
    provider = MprisProvider(LyricsState(), resolver=resolver)
    prepare_poll(provider, player)

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)
    assert provider._load_task is not None
    await provider._load_task

    assert len(resolver.tracks) == 1


def test_metadata_signal_only_wakes_sampler():
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider._subscribed_name = "org.mpris.MediaPlayer2.test"

    provider._on_props_changed(PLAYER_IFACE, {"Metadata": object()}, [])

    assert provider._poll_wakeup.is_set()
    assert provider._load_task is None


async def test_new_generation_cancels_old_fetch():
    resolver = BlockingResolver()
    state = LyricsState()
    provider = MprisProvider(state, resolver=resolver)
    provider._schedule_load(track_commit(1, "A", "Artist A"))
    await resolver.started.wait()
    provider._schedule_load(track_commit(2, "B", "Artist B"))
    assert provider._load_task is not None
    await provider._load_task

    assert resolver.cancelled_generations == [1]
    assert state.snapshot.title == "B"


async def test_cider_disconnect_forces_ordered_resolution_again():
    resolver = RecordingResolver()
    gate = SourceGate()
    state = LyricsState()
    provider = MprisProvider(state, resolver=resolver, gate=gate)
    provider._current_commit = track_commit(1, "Song", "Artist")
    provider._content_owner = "cider"
    gate.observe_snapshot(10, LyricsSnapshot(found=True, title="Song", artist="Artist"))
    gate.select_cider(10)
    gate.drop_client(10)

    provider._ensure_content_owner()
    assert provider._load_task is not None
    await provider._load_task

    assert len(resolver.tracks) == 1


async def test_late_cider_snapshot_takes_over_after_ordered_miss():
    resolver = DeferredResolver()
    gate = SourceGate()
    state = LyricsState()
    provider = MprisProvider(state, resolver=resolver, gate=gate)
    provider._schedule_load(track_commit(1, "Song", "Artist"))
    await resolver.started.wait()

    snapshot = LyricsSnapshot(found=True, title="Song", artist="Artist")
    gate.observe_snapshot(10, snapshot)
    resolver.release.set()
    assert provider._load_task is not None
    await provider._load_task

    assert provider._content_owner == "cider"
    assert gate.accepts(10) is True
    assert state.snapshot is snapshot


async def test_late_higher_priority_cider_beats_lower_external_result():
    resolver = DeferredResolver(ResolvedLyrics(source="netease", lines=()))
    gate = SourceGate()
    state = LyricsState()
    provider = MprisProvider(
        state,
        resolver=resolver,
        gate=gate,
        lyrics_sources=["cider", "netease"],
    )
    provider._schedule_load(track_commit(1, "Song", "Artist"))
    await resolver.started.wait()

    snapshot = LyricsSnapshot(found=True, title="Song", artist="Artist")
    gate.observe_snapshot(10, snapshot)
    resolver.release.set()
    assert provider._load_task is not None
    await provider._load_task

    assert provider._content_owner == "cider"
    assert state.snapshot is snapshot


async def test_external_result_uses_actual_provider_label():
    state = LyricsState()
    resolver = RecordingResolver(ResolvedLyrics(source="lrclib", lines=()))
    provider = MprisProvider(state, resolver=resolver)
    provider._schedule_load(track_commit(1, "Song", "Artist"))
    assert provider._load_task is not None
    await provider._load_task

    provider._emit(track_commit(1, "Song", "Artist").info, 0.0, True)
    assert state.snapshot.provider == "MPRIS:lrclib"


async def test_matching_cider_tick_drives_external_line_selection():
    lines = (
        LyricLine(0, "L0", 0.0, 5.0, "first", ""),
        LyricLine(1, "L1", 5.0, 10.0, "second", ""),
    )
    state = LyricsState()
    gate = SourceGate()
    gate.observe_snapshot(10, LyricsSnapshot(found=False, title="Song", artist="Artist"))
    gate.observe_tick(10, 7.5, True)
    resolver = RecordingResolver(ResolvedLyrics(source="netease", lines=lines))
    provider = MprisProvider(state, resolver=resolver, gate=gate)
    prepare_poll(provider, FakePlayer(metadata=VALID_METADATA, position=999_000_000))

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)
    assert provider._load_task is not None
    await provider._load_task
    await provider._poll_once(now=1.0)

    assert state.snapshot.current is not None
    assert state.snapshot.current.text == "second"
    assert state.snapshot.current_time == 7.5


async def test_matching_cider_duration_corrects_mpris_search_metadata():
    gate = SourceGate()
    gate.observe_snapshot(
        10,
        LyricsSnapshot(
            found=False,
            title="Song",
            artist="Artist",
            album="Album",
            duration_s=194.222,
        ),
    )
    gate.observe_tick(10, 50.0, True)
    resolver = RecordingResolver()
    provider = MprisProvider(LyricsState(), resolver=resolver, gate=gate)
    provider._schedule_load(
        TrackCommit(
            generation=1,
            player_name="org.mpris.MediaPlayer2.chromium.test",
            info=TrackInfo("Song", "Artist", "Album", 305.059159, "/track/1"),
        )
    )
    assert provider._load_task is not None
    await provider._load_task

    assert resolver.tracks[0].duration_s == 194.222
