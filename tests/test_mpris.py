from kotonoha.providers.mpris import (
    TrackInfo,
    TrackObservation,
    TrackStabilizer,
    _unwrap,
    parse_metadata,
)


def observation(track_id, title, artist, *, at, duration=180.0):
    return TrackObservation(
        player_name="org.mpris.MediaPlayer2.test",
        info=TrackInfo(title, artist, "", duration, track_id),
        playback_status="Playing",
        position_s=0.0,
        observed_at=at,
    )


def test_parse_basic():
    info = parse_metadata(
        {
            "xesam:title": "Bloom",
            "xesam:artist": ["Radwimps"],
            "xesam:album": "Your Name",
            "mpris:length": 215_000_000,
            "mpris:trackid": "/track/1",
        }
    )
    assert info.title == "Bloom"
    assert info.artist == "Radwimps"
    assert info.album == "Your Name"
    assert info.length_s == 215.0
    assert info.track_id == "/track/1"


def test_parse_multiple_artists_joined():
    assert parse_metadata({"xesam:artist": ["A", "B"]}).artist == "A / B"


def test_parse_artist_as_plain_string():
    assert parse_metadata({"xesam:artist": "Solo"}).artist == "Solo"


def test_parse_strips_chrome_badge_and_youtube_suffix():
    info = parse_metadata({"xesam:title": "(309) 志铭 | YouTube Music", "xesam:artist": [""]})
    assert info.title == "志铭"


def test_parse_strips_trailing_dash_youtube():
    assert parse_metadata({"xesam:title": "Song - YouTube"}).title == "Song"


def test_parse_keeps_clean_title_and_never_empties():
    assert parse_metadata({"xesam:title": "Normal Song"}).title == "Normal Song"
    # "YouTube" alone has no separator to strip, so it must survive intact.
    assert parse_metadata({"xesam:title": "YouTube"}).title == "YouTube"


def test_parse_missing_fields():
    info = parse_metadata({"xesam:title": "T"})
    assert info.title == "T"
    assert info.artist == ""
    assert info.album == ""
    assert info.length_s is None
    assert info.track_id == ""


def test_parse_length_bool_rejected():
    assert parse_metadata({"mpris:length": True}).length_s is None


def test_parse_int64_max_length_sentinel_rejected():
    assert parse_metadata({"mpris:length": (1 << 63) - 1}).length_s is None


def test_parse_non_finite_lengths_rejected():
    for value in (float("inf"), float("-inf"), float("nan")):
        assert parse_metadata({"mpris:length": value}).length_s is None


def test_parse_non_positive_lengths_rejected():
    assert parse_metadata({"mpris:length": 0}).length_s is None
    assert parse_metadata({"mpris:length": -1}).length_s is None


def test_parse_lengths_above_24_hours_rejected():
    assert parse_metadata({"mpris:length": 86_400_000_001}).length_s is None


def test_unwrap_variants():
    class FakeVariant:
        def __init__(self, value):
            self.value = value

    raw = {"a": FakeVariant(5), "b": FakeVariant("x")}
    assert _unwrap(raw) == {"a": 5, "b": "x"}


def test_empty_metadata_never_commits_and_same_track_id_can_recover():
    stabilizer = TrackStabilizer()
    assert stabilizer.observe(observation("/track/1", "", "", at=0.0)) is None
    assert stabilizer.observe(observation("/track/1", "Song", "Artist", at=0.2)) is None
    commit = stabilizer.observe(observation("/track/1", "Song", "Artist", at=0.6))
    assert commit is not None
    assert commit.info.title == "Song"


def test_new_title_old_artist_does_not_commit_before_stable_pair():
    stabilizer = TrackStabilizer()
    stabilizer.observe(observation("/old", "Old", "Old Artist", at=0.0))
    assert stabilizer.observe(observation("/new", "New", "Old Artist", at=1.0)) is None
    assert stabilizer.observe(observation("/new", "New", "New Artist", at=1.1)) is None
    commit = stabilizer.observe(observation("/new", "New", "New Artist", at=1.5))
    assert commit is not None
    assert commit.info.artist == "New Artist"


def test_new_title_with_previous_artist_uses_longer_settle_window():
    stabilizer = TrackStabilizer()
    assert stabilizer.observe(observation("/old", "Old", "Artist", at=0.0)) is None
    assert stabilizer.observe(observation("/old", "Old", "Artist", at=0.4)) is not None

    assert stabilizer.observe(observation("/new", "New", "Artist", at=1.0)) is None
    assert stabilizer.observe(observation("/new", "New", "Artist", at=1.4)) is None
    assert stabilizer.observe(observation("/new", "New", "Artist", at=1.81)) is not None


def test_missing_artist_commits_after_longer_window():
    stabilizer = TrackStabilizer()
    assert stabilizer.observe(observation("/1", "Instrumental", "", at=0.0)) is None
    assert stabilizer.observe(observation("/1", "Instrumental", "", at=0.5)) is None
    assert stabilizer.observe(observation("/1", "Instrumental", "", at=0.9)) is not None


def test_duration_drift_does_not_create_a_new_track_transition():
    stabilizer = TrackStabilizer()
    assert stabilizer.observe(observation("/1", "Song", "Artist", at=0.0, duration=180.0)) is None
    assert stabilizer.observe(observation("/1", "Song", "Artist", at=0.4, duration=181.0)) is not None

    assert stabilizer.observe(observation("/1", "Song", "Artist", at=1.0, duration=190.0)) is None
    assert stabilizer.transitioning is False
