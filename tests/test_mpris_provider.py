import asyncio

from kotonoha.lyrics.resolver import ResolvedLyrics
from kotonoha.model import LyricsSnapshot
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
    def __init__(self, metadata, *, position_error=None):
        self.metadata = metadata
        self.position_error = position_error

    async def get_playback_status(self):
        return "Playing"

    async def get_metadata(self):
        return self.metadata

    async def get_position(self):
        if self.position_error is not None:
            raise self.position_error
        return 0


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


async def test_external_result_uses_actual_provider_label():
    state = LyricsState()
    resolver = RecordingResolver(ResolvedLyrics(source="lrclib", lines=()))
    provider = MprisProvider(state, resolver=resolver)
    provider._schedule_load(track_commit(1, "Song", "Artist"))
    assert provider._load_task is not None
    await provider._load_task

    provider._emit(track_commit(1, "Song", "Artist").info, 0.0, True)
    assert state.snapshot.provider == "MPRIS:lrclib"
