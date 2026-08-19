"""The rule that picks a player, exercised without a session bus.

Every desktop presents a different set of players, and the cases that matter are
the awkward combinations — two services wrapping one playback, a locked player that
went quiet, a source with no performer. None of them need D-Bus to describe.
"""

from kotonoha.providers.mpris_track import TrackInfo
from kotonoha.providers.player_selection import RECENT_PLAYER_MARGIN, PlayerRecord, PlayerSelector


def _record(name, status="Playing", title="Song", artist="Artist"):
    return PlayerRecord(object(), name, status, TrackInfo(title, artist, "", 180.0, f"/{name}"))


def test_a_source_with_no_performer_never_wins_on_recency():
    # Chrome and Firefox each publish their own service beside the Plasma bridge that
    # wraps the same playback, carrying the raw tab title and an empty artist, and
    # they announce themselves after it.
    selector = PlayerSelector()
    bridge = _record("bridge", title="动物世界", artist="薛之谦")
    native = _record("native", title="(86) 动物世界 - YouTube Music", artist="")
    selector.current_name = "bridge"
    selector.observe("bridge", "Playing", 0.0)
    selector.observe("native", "Playing", 20.0)

    assert selector.choose([bridge, native]) is bridge


def test_a_newer_player_wins_when_both_name_a_performer():
    # What the recency rule was added for: the listener started something else.
    selector = PlayerSelector()
    old, new = _record("old"), _record("new")
    selector.current_name = "old"
    selector.observe("old", "Playing", 0.0)
    selector.observe("new", "Playing", RECENT_PLAYER_MARGIN * 2)

    assert selector.choose([old, new]) is new


def test_a_rival_inside_the_margin_does_not_steal_the_overlay():
    selector = PlayerSelector()
    old, new = _record("old"), _record("new")
    selector.current_name = "old"
    selector.observe("old", "Playing", 0.0)
    selector.observe("new", "Playing", RECENT_PLAYER_MARGIN / 2)

    assert selector.choose([old, new]) is old


def test_a_locked_player_is_followed_even_while_paused():
    selector = PlayerSelector()
    selector.lock = "pinned"
    pinned = _record("pinned", status="Paused")

    assert selector.choose([_record("loud"), pinned]) is pinned


def test_a_paused_player_with_a_track_beats_a_playing_one_without():
    # One policy for the poll and the settings picker. The picker used to order these
    # the other way round and marked a player as Current that the poll would not follow.
    selector = PlayerSelector()
    silent = _record("silent", status="Playing", title="", artist="")
    paused = _record("paused", status="Paused")

    assert selector.choose([silent, paused]) is paused


def test_nothing_playable_selects_nothing():
    assert PlayerSelector().choose([_record("stopped", status="Stopped")]) is None
    assert PlayerSelector().choose([]) is None


def test_a_vanished_player_loses_its_stamp():
    selector = PlayerSelector()
    selector.observe("gone", "Playing", 1.0)
    selector.observe("here", "Playing", 1.0)

    selector.forget_absent({"here"})

    assert "gone" not in selector.playing_since
    assert "here" in selector.playing_since


def test_the_current_player_is_polled_first():
    # A tie keeps the current source, which only holds if it is seen first.
    selector = PlayerSelector()
    selector.current_name = "b"

    assert selector.order_to_poll(["a", "b", "c"]) == ["b", "a", "c"]
    assert selector.order_to_poll(["a", "c"]) == ["a", "c"]
