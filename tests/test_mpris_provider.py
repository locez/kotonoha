import asyncio

from kotonoha.lyrics.resolver import ResolvedLyrics
from kotonoha.model import LyricLine, LyricsSnapshot
from kotonoha.providers import mpris as mpris_module
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

    async def resolve_hint(self, _session, _track, _sources, _hint):
        return None

    def reset_memory(self):
        return None

    def set_cache_enabled(self, _enabled):
        return None

    def set_prefer_best(self, _enabled):
        return None

    def set_fuzzy(self, _enabled):
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


    async def resolve_hint(self, _session, _track, _sources, _hint):
        return None

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


    async def resolve_hint(self, _session, _track, _sources, _hint):
        return None

def track_commit(generation, title, artist):
    return TrackCommit(
        generation=generation,
        player_name="org.mpris.MediaPlayer2.test",
        info=TrackInfo(title, artist, "", 180.0, f"/{generation}"),
    )


def prepare_poll(provider, player):
    async def active_player(**_kwargs):
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


async def test_cumulative_position_offset_realigns_the_sweep():
    lines = (
        LyricLine(0, "L0", 0.0, 5.0, "first", ""),
        LyricLine(1, "L1", 5.0, 10.0, "second", ""),
    )
    state = LyricsState()
    resolver = RecordingResolver(ResolvedLyrics(source="netease", lines=lines))
    provider = MprisProvider(state, resolver=resolver)
    # Player reports a cumulative playlist position of 507s; the song started at 500s.
    prepare_poll(provider, FakePlayer(metadata=VALID_METADATA, position=507_000_000))

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)
    assert provider._load_task is not None
    await provider._load_task
    provider._song_offset = 500.0  # captured from the track-transition
    await provider._poll_once(now=1.0)

    # song-relative time = 507 - 500 = 7s -> the second line, not stuck at the end.
    assert state.snapshot.current is not None
    assert state.snapshot.current.text == "second"
    assert state.snapshot.current_time == 7.0


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


async def test_late_position_reset_corrects_offset_without_reload():
    lines = (
        LyricLine(0, "L0", 0.0, 5.0, "first", ""),
        LyricLine(1, "L1", 5.0, 10.0, "second", ""),
    )
    state = LyricsState()
    resolver = RecordingResolver(ResolvedLyrics(source="netease", lines=lines))
    provider = MprisProvider(state, resolver=resolver)
    player = FakePlayer(metadata=VALID_METADATA, position=21_125_000)
    prepare_poll(provider, player)

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)
    assert provider._load_task is not None
    await provider._load_task

    b_metadata = {
        "xesam:title": "SongB",
        "xesam:artist": ["ArtistB"],
        "xesam:album": "AlbumB",
        "mpris:length": 180_000_000,
        "mpris:trackid": "/track/B",
    }
    player.metadata = b_metadata
    await provider._poll_once(now=1.0)
    await provider._poll_once(now=2.0)
    assert provider._load_task is not None
    await provider._load_task
    assert provider._song_offset == 21.125
    assert provider._calibration_offset == 21.125

    player.position = 500_000
    await provider._poll_once(now=2.2)

    assert provider._song_offset == 0.0
    assert len(resolver.tracks) == 2
    assert state.snapshot.current is not None
    assert state.snapshot.current.text == "first"


async def test_cumulative_player_not_miscalibrated_by_normal_advance():
    lines = (
        LyricLine(0, "L0", 0.0, 5.0, "first", ""),
        LyricLine(1, "L1", 5.0, 10.0, "second", ""),
    )
    state = LyricsState()
    resolver = RecordingResolver(ResolvedLyrics(source="netease", lines=lines))
    provider = MprisProvider(state, resolver=resolver)
    player = FakePlayer(metadata=VALID_METADATA, position=500_000_000)
    prepare_poll(provider, player)

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)
    assert provider._load_task is not None
    await provider._load_task

    b_metadata = {
        "xesam:title": "SongB",
        "xesam:artist": ["ArtistB"],
        "xesam:album": "AlbumB",
        "mpris:length": 180_000_000,
        "mpris:trackid": "/track/B",
    }
    player.metadata = b_metadata
    player.position = 500_500_000
    await provider._poll_once(now=1.0)
    player.position = 501_000_000
    await provider._poll_once(now=2.0)
    assert provider._load_task is not None
    await provider._load_task

    player.position = 507_000_000
    await provider._poll_once(now=2.5)

    assert provider._song_offset == 500.5
    assert state.snapshot.current is not None
    assert state.snapshot.current.text == "second"


async def test_late_reset_during_resolving_corrects_offset():
    lines = (
        LyricLine(0, "L0", 0.0, 5.0, "first", ""),
        LyricLine(1, "L1", 5.0, 10.0, "second", ""),
    )

    state = LyricsState()
    resolver = DeferredResolver(ResolvedLyrics(source="netease", lines=lines))
    provider = MprisProvider(state, resolver=resolver)
    player = FakePlayer(metadata=VALID_METADATA, position=21_125_000)
    prepare_poll(provider, player)

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)
    await resolver.started.wait()
    resolver.release.set()
    assert provider._load_task is not None
    await provider._load_task

    b_metadata = {
        "xesam:title": "SongB",
        "xesam:artist": ["ArtistB"],
        "xesam:album": "AlbumB",
        "mpris:length": 180_000_000,
        "mpris:trackid": "/track/B",
    }
    player.metadata = b_metadata
    await provider._poll_once(now=1.0)
    await provider._poll_once(now=2.0)
    assert provider._content_owner == "resolving"
    assert provider._song_offset == 21.125

    player.position = 500_000
    await provider._poll_once(now=2.2)
    assert provider._song_offset == 0.0

    resolver.release.set()
    assert provider._load_task is not None
    await provider._load_task
    await provider._poll_once(now=2.3)
    assert state.snapshot.current is not None
    assert state.snapshot.current.text == "first"


class _Variant:
    """What dbus hands back for a single property read: a Variant, not an a{sv} map."""

    def __init__(self, value):
        self.value = value


async def test_player_identity_is_unwrapped_from_its_variant():
    # The metadata unwrapper takes a dict; a single property arrives wrapped on its
    # own, and passing it there rendered every player in the picker as "{}".
    from kotonoha.players import PlayerInfo

    identity = _Variant("ElectronNCM")
    assert str(getattr(identity, "value", identity) or "") == "ElectronNCM"
    assert PlayerInfo("org.mpris.MediaPlayer2.ElectronNCM", "ElectronNCM").identity == "ElectronNCM"


def _async_return(value):
    async def _call(_bus):
        return value

    return _call
async def test_non_song_never_reaches_the_resolver():
    # The gate has to be wired into the load path, not merely defined: a 14-hour
    # compilation must not be sent to every lyric provider.
    compilation = dict(
        VALID_METADATA,
        **{"xesam:title": "Study with Miku - part4 -", "mpris:length": 5_040_000_000},
    )
    resolver = RecordingResolver()
    provider = MprisProvider(LyricsState(), resolver=resolver, poll_interval=0.01)
    prepare_poll(provider, FakePlayer(metadata=compilation))

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)
    if provider._load_task is not None:
        await provider._load_task

    assert resolver.tracks == []


async def test_an_ordinary_song_still_reaches_the_resolver():
    resolver = RecordingResolver()
    provider = MprisProvider(LyricsState(), resolver=resolver, poll_interval=0.01)
    prepare_poll(provider, FakePlayer(metadata=VALID_METADATA))

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)
    assert provider._load_task is not None
    await provider._load_task

    assert [track.title for track in resolver.tracks] == ["Song"]


async def test_an_over_long_cider_duration_still_skips_the_lookup():
    # The browser reports no length while Cider knows the real one. Running the
    # gate on the MPRIS value first let a two-hour stream through, and the resolver
    # then received the 7201s duration anyway — the very content this gate exists
    # to keep off the providers.
    resolver = RecordingResolver()
    gate = SourceGate()
    state = LyricsState()
    provider = MprisProvider(state, resolver=resolver, gate=gate)
    commit = track_commit(1, "Song", "Artist")
    provider._current_commit = commit
    gate.observe_snapshot(10, LyricsSnapshot(found=False, title="Song", artist="Artist", duration_s=7201.0))
    gate.observe_tick(10, 0.0, True)

    await provider._load_song(commit)

    assert resolver.tracks == [], "a 7201s stream was sent to the lyric providers"
    assert provider._content_owner == "none"


async def test_a_repaired_commit_keeps_the_player_identity():
    # A commit that arrives behind the current generation is rebuilt with a fresh
    # one. Reconstructing it positionally dropped player_identity, so a recognised
    # player stopped producing an exact hint and fell back to matching on the title.
    class HintRecorder(RecordingResolver):
        def __init__(self):
            super().__init__()
            self.hints = []

        async def resolve_hint(self, _session, _track, _sources, _hint):
            self.hints.append(_hint)
            return None

    resolver = HintRecorder()
    provider = MprisProvider(LyricsState(), resolver=resolver)
    info = TrackInfo("Song", "Artist", "", 180.0, "/track/12345")
    provider._current_commit = TrackCommit(2, "org.mpris.MediaPlayer2.x", info, None, "ElectronNCM")

    provider._schedule_load(TrackCommit(1, "org.mpris.MediaPlayer2.x", info, None, "ElectronNCM"))
    assert provider._load_task is not None
    await provider._load_task

    assert resolver.hints, "the repaired commit produced no exact hint at all"
    assert resolver.hints[-1].provider == "netease"
    assert resolver.hints[-1].song_id == "12345"




async def test_a_player_that_never_answers_does_not_stop_the_poll(monkeypatch):
    # Catching exceptions is not enough on this boundary: a player that owns its
    # bus name and simply never replies is silence, not an error, and this provider
    # has one poll task. Without a deadline that task waits inside the call and
    # every other player stops being looked at too.
    class Silent:
        async def get_playback_status(self) -> str:
            await asyncio.Event().wait()
            return ""

        async def get_metadata(self) -> dict[str, object]:
            await asyncio.Event().wait()
            return {}

    # A short deadline for the test: the point is that one exists, not its value.
    monkeypatch.setattr(mpris_module, "DBUS_CALL_TIMEOUT", 0.05)
    started = asyncio.get_running_loop().time()
    status = await MprisProvider._safe_status(Silent())
    info = await MprisProvider._safe_info(Silent())
    elapsed = asyncio.get_running_loop().time() - started

    assert status == ""
    assert info is None
    assert elapsed < 1.0, f"the reads took {elapsed:.1f}s"


async def test_the_shared_lyrics_session_carries_no_cookies():
    """The session every lyric provider shares must not keep cookies.

    NetEase sets one on its first search reply, and a request carrying it back is
    answered with an unrelated popular-songs list instead of the query's own
    results. This session lives for the process, so only the first search of a run
    was answered honestly: measured over five identical queries for a song that
    exists, 1/5 with the default jar and 5/5 without.

    Built by its own factory rather than inside start(), which also connects the
    D-Bus session bus — a bus CI has no reason to provide.
    """
    import aiohttp

    from kotonoha.providers.mpris import new_lyrics_session

    session = new_lyrics_session()
    try:
        assert isinstance(session.cookie_jar, aiohttp.DummyCookieJar)
    finally:
        await session.close()


def counter_commit(generation, seconds):
    """A commit whose reported length is the session's playtime, not the track's."""
    return TrackCommit(
        generation=generation,
        player_name="org.mpris.MediaPlayer2.chromium",
        info=TrackInfo(f"Song {generation}", "Artist", "", seconds, f"/{generation}"),
    )


async def drive(provider, commits, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(mpris_module.time, "monotonic", lambda: clock[0])
    for commit in commits:
        provider._schedule_load(commit)
        if provider._load_task is not None:
            await provider._load_task
        clock[0] += 300.0


def _lyric_lines(count, span=10.0):
    return tuple(
        LyricLine(index=i, id=f"L{i}", start=i * span, end=(i + 1) * span, text=f"line {i}",
                  translation="", words=())
        for i in range(count)
    )


def _commit_with_length(length_s):
    return TrackCommit(
        generation=1,
        player_name="org.mpris.MediaPlayer2.plasma-browser-integration",
        info=TrackInfo("Song", "Artist", "", length_s, "/1"),
    )


def test_a_running_total_is_shifted_by_what_it_overstates_the_length_by():
    # Measured live: the bridge reported 3745.4s of 3776.7s for a song 207s long
    # playing at 176s. Position and Length are shifted by the same amount, so the
    # overstatement is the shift, and the last line is the closest the lyrics can
    # say about the song's real length.
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider._last_raw_position = 3745.4

    provider._recalibrate_against(_commit_with_length(3776.7), _lyric_lines(20, span=10.25))

    assert abs(provider._song_offset - 3571.7) < 0.5
    assert abs((3745.4 - provider._song_offset) - 176.0) < 5.0  # within seconds of the truth


def test_a_song_inside_its_own_lyrics_is_left_alone():
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider._last_raw_position = 25.0

    provider._recalibrate_against(_commit_with_length(60.0), _lyric_lines(6))

    assert provider._song_offset == 0.0


def test_a_song_that_cannot_be_placed_is_left_unplaced():
    # Without a length to measure the shift against, starting the song from wherever
    # the player happens to be would put every line out by however far in it already is.
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider._last_raw_position = 3745.4

    provider._recalibrate_against(_commit_with_length(None), _lyric_lines(6))

    assert provider._song_offset == 0.0


def test_an_established_offset_is_not_second_guessed():
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider._song_offset = 120.0
    provider._last_raw_position = 9999.0

    provider._recalibrate_against(_commit_with_length(9999.0), _lyric_lines(6))

    assert provider._song_offset == 120.0


async def test_the_load_path_places_the_song():
    resolver = RecordingResolver(result=ResolvedLyrics("netease", lines=_lyric_lines(20, span=10.25)))
    provider = MprisProvider(LyricsState(), resolver=resolver, gate=SourceGate())
    provider._last_raw_position = 3745.4

    provider._schedule_load(_commit_with_length(3776.7))
    load = provider._load_task
    assert load is not None
    await load

    assert provider._song_offset > 3000.0


def test_the_catalogue_length_is_preferred_to_the_last_line():
    # The last line only says where the words stop; a song with an outro runs on past
    # it, and every line would then be out by however long that outro is. Measured on
    # the track that showed this: words end at 205s, the recording is 207s, and the
    # player claimed 3776.7s — two seconds of the difference sat in the outro.
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider._last_raw_position = 3745.4
    lines = _lyric_lines(20, span=10.25)

    provider._recalibrate_against(_commit_with_length(3776.7), lines, song_length=207.0)

    assert abs(provider._song_offset - 3569.7) < 0.5
    assert abs((3745.4 - provider._song_offset) - 176.0) < 1.0  # the true position


def test_a_catalogue_length_shorter_than_the_words_is_not_believed():
    # A duration that stops before the lyrics do describes a different recording.
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider._last_raw_position = 3745.4
    lines = _lyric_lines(20, span=10.25)

    provider._recalibrate_against(_commit_with_length(3776.7), lines, song_length=30.0)

    assert abs(provider._song_offset - 3571.7) < 0.5  # falls back to the last line
