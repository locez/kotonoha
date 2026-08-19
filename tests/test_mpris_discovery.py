"""Finding players on the bus, and choosing between them.

Which player the overlay follows is decided from readings the session hands over,
so these describe the discovery and the picker; the policy itself has its own
tests, and what happens to a track once a player is chosen has another file.
"""


from kotonoha.providers.mpris import MprisProvider, TrackInfo
from kotonoha.providers.mpris_session import MprisSession
from kotonoha.providers.player_selection import RECENT_PLAYER_MARGIN
from kotonoha.state import LyricsState


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

class _Variant:
    """What dbus hands back for a single property read: a Variant, not an a{sv} map."""

    def __init__(self, value):
        self.value = value

class _FakeSession:
    """A session bus with the players a test declares, and nothing else.

    The reads are an object the provider is given rather than module functions to
    patch, so a test states which players exist instead of intercepting D-Bus.
    """

    def __init__(self, players):
        #: {bus_name: (player_obj, status, TrackInfo)}
        self._players = players
        self.connected = True
        self.subscribed_to = None

    async def player_names(self):
        return sorted(self._players)

    async def player(self, name):
        found = self._players.get(name)
        return None if found is None else found[0]

    async def status(self, player):
        return next(status for _p, status, _i in self._players.values() if _p is player)

    async def track(self, player):
        return next(info for _p, _s, info in self._players.values() if _p is player)

    async def identity(self):
        return ""

    async def describe(self, name):
        _player, status, info = self._players[name]
        return "", status, info

    async def subscribe(self, name, _on_change):
        self.subscribed_to = name

    def close(self):
        self.connected = False


def _wire_players(provider, players, monkeypatch):
    """players: {bus_name: (player_obj, status, TrackInfo)}."""
    del monkeypatch
    provider._session_bus = _FakeSession(players)




async def test_active_player_prefers_complete_metadata_over_alphabetical(monkeypatch):
    # Chrome sorts first but reports an empty artist; PBI has the real artist.
    chromium = ("chrome", "Playing", TrackInfo("Song - YouTube", "", "", 180.0, "/c"))
    pbi = ("pbi", "Playing", TrackInfo("Song", "Artist", "Album", 180.0, "/p"))
    players = {
        "org.mpris.MediaPlayer2.chromium.instance1": chromium,
        "org.mpris.MediaPlayer2.plasma-browser-integration": pbi,
    }
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    _wire_players(provider, players, monkeypatch)

    result = await provider._active_player()

    assert result is not None
    assert result[1] == "org.mpris.MediaPlayer2.plasma-browser-integration"
    assert provider._selector.current_name == "org.mpris.MediaPlayer2.plasma-browser-integration"


async def test_active_player_prefers_player_that_started_recently(monkeypatch):
    old = ("old", "Playing", TrackInfo("Song", "Artist", "Album", 180.0, "/old"))
    new = ("new", "Playing", TrackInfo("Song", "Artist", "Album", 180.0, "/new"))
    players = {"org.mpris.MediaPlayer2.old": old}
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    _wire_players(provider, players, monkeypatch)

    first = await provider._active_player(now=0.0)
    assert first is not None
    assert first[1] == "org.mpris.MediaPlayer2.old"

    players["org.mpris.MediaPlayer2.new"] = new
    result = await provider._active_player(now=20.0)

    assert result is not None
    assert result[1] == "org.mpris.MediaPlayer2.new"


async def test_active_player_keeps_current_when_new_player_is_within_recency_margin(monkeypatch):
    old = ("old", "Playing", TrackInfo("Song", "Artist", "Album", 180.0, "/old"))
    new = ("new", "Playing", TrackInfo("Song", "Artist", "Album", 180.0, "/new"))
    players = {"org.mpris.MediaPlayer2.old": old}
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    _wire_players(provider, players, monkeypatch)

    first = await provider._active_player(now=0.0)
    assert first is not None
    assert first[1] == "org.mpris.MediaPlayer2.old"

    players["org.mpris.MediaPlayer2.new"] = new
    result = await provider._active_player(now=RECENT_PLAYER_MARGIN / 2)

    assert result is not None
    assert result[1] == "org.mpris.MediaPlayer2.old"


async def test_active_player_lock_beats_recently_started_rival(monkeypatch):
    locked = ("locked", "Playing", TrackInfo("Song", "", "", 180.0, "/locked"))
    rival = ("rival", "Playing", TrackInfo("Song", "Artist", "Album", 180.0, "/rival"))
    players = {"org.mpris.MediaPlayer2.locked": locked}
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider.set_player_lock("org.mpris.MediaPlayer2.locked")
    _wire_players(provider, players, monkeypatch)

    first = await provider._active_player(now=0.0)
    assert first is not None
    assert first[1] == "org.mpris.MediaPlayer2.locked"

    players["org.mpris.MediaPlayer2.rival"] = rival
    result = await provider._active_player(now=20.0)

    assert result is not None
    assert result[1] == "org.mpris.MediaPlayer2.locked"


async def test_active_player_drops_recency_stamp_for_vanished_player(monkeypatch):
    vanished = ("vanished", "Playing", TrackInfo("Song", "Artist", "Album", 180.0, "/vanished"))
    players = {"org.mpris.MediaPlayer2.vanished": vanished}
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    _wire_players(provider, players, monkeypatch)

    result = await provider._active_player(now=0.0)
    assert result is not None
    assert "org.mpris.MediaPlayer2.vanished" in provider._selector.playing_since

    players.clear()
    assert await provider._active_player(now=20.0) is None
    assert "org.mpris.MediaPlayer2.vanished" not in provider._selector.playing_since


async def test_active_player_lock_beats_more_complete_rival(monkeypatch):
    locked = ("locked", "Playing", TrackInfo("Song", "", "", 180.0, "/locked"))
    rival = ("rival", "Playing", TrackInfo("Song", "Artist", "Album", 180.0, "/rival"))
    players = {
        "org.mpris.MediaPlayer2.locked": locked,
        "org.mpris.MediaPlayer2.rival": rival,
    }
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider.set_player_lock("org.mpris.MediaPlayer2.locked")
    _wire_players(provider, players, monkeypatch)

    result = await provider._active_player()

    assert result is not None
    assert result[1] == "org.mpris.MediaPlayer2.locked"


async def test_active_player_absent_lock_falls_back_to_automatic(monkeypatch):
    rival = ("rival", "Playing", TrackInfo("Song", "Artist", "Album", 180.0, "/rival"))
    players = {"org.mpris.MediaPlayer2.rival": rival}
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider.set_player_lock("org.mpris.MediaPlayer2.closed")
    _wire_players(provider, players, monkeypatch)

    result = await provider._active_player()

    assert result is not None
    assert result[1] == "org.mpris.MediaPlayer2.rival"


async def test_active_player_falls_back_to_only_source(monkeypatch):
    only = ("chrome", "Playing", TrackInfo("Song - YouTube", "", "", 180.0, "/c"))
    players = {"org.mpris.MediaPlayer2.chromium.instance1": only}
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    _wire_players(provider, players, monkeypatch)

    result = await provider._active_player()

    assert result is not None
    assert result[1] == "org.mpris.MediaPlayer2.chromium.instance1"


class _PlayerProperties:
    def __init__(self, identity, status, metadata):
        self.identity = _Variant(identity)
        self.status = _Variant(status)
        self.metadata = _Variant(metadata)

    async def call_get(self, _interface, _property):
        return self.identity

    async def call_get_all(self, _interface):
        return {
            "PlaybackStatus": self.status,
            "Metadata": self.metadata,
        }


class _DetailFailingProperties(_PlayerProperties):
    async def call_get_all(self, _interface):
        raise RuntimeError("optional player detail unavailable")


class _PlayerObject:
    def __init__(self, properties):
        self.properties = properties

    def get_interface(self, interface):
        if interface == "org.freedesktop.DBus.Properties":
            return self.properties
        raise AssertionError(interface)


class _DiscoveryBus:
    """A session bus holding exactly the players a test declares."""

    def __init__(self, players):
        self.players = players

    async def introspect(self, _name, _path):
        return object()

    def get_proxy_object(self, name, _path, _introspection):
        if name == "org.freedesktop.DBus":
            return _NameDirectory(self.players)
        return _PlayerObject(self.players[name])


class _NameDirectory:
    """The bus's own object, which answers who is on it."""

    def __init__(self, players):
        self._players = players

    def get_interface(self, _name):
        return self

    async def call_list_names(self):
        return [*self._players, "org.freedesktop.Notifications"]


async def test_available_players_reports_track_status_and_automatic_choice(monkeypatch):
    playing_metadata = {
        "xesam:title": "Song",
        "xesam:artist": ["Artist"],
        "mpris:trackid": "/playing",
    }
    idle_metadata = {"mpris:trackid": "/idle"}
    players = {
        "org.mpris.MediaPlayer2.firefox.instance_1_298": _PlayerProperties(
            "Mozilla firefox", "Playing", playing_metadata
        ),
        "org.mpris.MediaPlayer2.plasma-browser-integration": _PlayerProperties(
            "Mozilla Firefox", "Stopped", idle_metadata
        ),
    }
    del monkeypatch
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider._session_bus = MprisSession(bus=_DiscoveryBus(players))

    result = await provider.available_players()

    assert result[0].title == "Song"
    assert result[0].artist == "Artist"
    assert result[0].playback_status == "Playing"
    assert result[0].automatic is True
    assert result[1].title == ""
    assert result[1].playback_status == "Stopped"
    assert result[1].automatic is False


def _names(players):
    return sorted(players)


async def test_the_picker_marks_the_player_the_poll_would_follow(monkeypatch):
    # The picker carried its own copy of the selection policy which ordered the last
    # two fallbacks the other way round: a Playing player reporting no metadata beat
    # a Paused one that reports a track, while the poll chose the opposite.
    players = {
        "org.mpris.MediaPlayer2.a-playing-empty": _PlayerProperties("Empty", "Playing", {}),
        "org.mpris.MediaPlayer2.b-paused-song": _PlayerProperties(
            "Paused", "Paused", {"xesam:title": "Song", "xesam:artist": ["Artist"]}
        ),
    }

    del monkeypatch
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    provider._session_bus = MprisSession(bus=_DiscoveryBus(players))

    result = await provider.available_players()

    marked = [p.bus_name for p in result if p.automatic]
    assert marked == ["org.mpris.MediaPlayer2.b-paused-song"], (
        "the picker marked a player the poll would not follow"
    )


async def test_a_source_with_no_artist_never_wins_on_recency(monkeypatch):
    # Measured with both browsers open at once: Chrome and Firefox each publish their
    # own MPRIS service beside the Plasma Browser Integration bridge. The native ones
    # carry the raw tab title, an empty artist and no usable url, and they announce
    # themselves after the bridge, so recency handed the overlay a source that cannot
    # match anything — 'Ed Sheeran - Shape of You' with no artist while the bridge
    # was reporting 薛之谦 / 动物世界.
    bridge = ("bridge", "Playing", TrackInfo("动物世界", "薛之谦", "渡 The Crossing", 230.0, "/b"))
    native = ("native", "Playing", TrackInfo("(86) 动物世界 - YouTube Music", "", "", 230.0, "/n"))
    players = {"org.mpris.MediaPlayer2.plasma-browser-integration": bridge}
    provider = MprisProvider(LyricsState(), resolver=RecordingResolver())
    _wire_players(provider, players, monkeypatch)

    await provider._active_player(now=0.0)
    players["org.mpris.MediaPlayer2.chromium.instance1"] = native
    result = await provider._active_player(now=20.0)

    assert result is not None
    assert result[1] == "org.mpris.MediaPlayer2.plasma-browser-integration"
