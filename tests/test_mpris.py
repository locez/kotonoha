from fixtures.mpris_titles import MPRIS_TITLE_CASES

from kotonoha.providers.mpris import (
    TrackInfo,
    TrackObservation,
    TrackStabilizer,
    _unwrap,
    parse_metadata,
)
from kotonoha.providers.mpris_track import CumulativeLengthDetector, lyrics_lookup_reason


def observation(track_id, title, artist, *, at, duration=180.0, pos=0.0):
    return TrackObservation(
        player_name="org.mpris.MediaPlayer2.test",
        info=TrackInfo(title, artist, "", duration, track_id),
        playback_status="Playing",
        position_s=pos,
        observed_at=at,
    )


def test_transition_captures_song_start_position():
    stab = TrackStabilizer()
    stab.observe(observation("/a", "A", "Artist", at=0.0, pos=100.0))
    first = stab.observe(observation("/a", "A", "Artist", at=1.0, pos=101.0))
    assert first is not None
    assert first.start_position is None  # first track: join point unknown

    # Transition A -> B; the browser reports a cumulative position of 500s.
    stab.observe(observation("/b", "B", "Artist", at=2.0, pos=500.0))
    second = stab.observe(observation("/b", "B", "Artist", at=3.0, pos=501.0))
    assert second is not None
    assert second.start_position == 500.0  # captured at B's first sighting

def test_song_relative_player_reset_detected_uses_zero_offset():
    stab = TrackStabilizer()
    stab.observe(observation("/a", "A", "Artist", at=0.0, pos=0.0))
    stab.observe(observation("/a", "A", "Artist", at=1.0, pos=21.0))
    # When next song's metadata appears, current position is stale (= A's pos: 21.125s)
    stab.observe(observation("/b", "B", "Artist", at=2.0, pos=21.125))
    # Then the player resets its position to ~0.0, but the track ID is still B.
    commit = stab.observe(observation("/b", "B", "Artist", at=3.0, pos=0.5))
    # The stabilizer should detect the reset and use 0
    assert commit is not None
    assert commit.start_position == 0.0

def test_parse_basic():
    info = parse_metadata(
        {
            "xesam:title": "Bloom",
            "xesam:artist": ["Radwimps"],
            "xesam:album": "Your Name",
            "mpris:length": 215_000_000,
            "mpris:trackid": "/track/1",
            "xesam:url": "https://music.example/1",
        }
    )
    assert info.title == "Bloom"
    assert info.artist == "Radwimps"
    assert info.album == "Your Name"
    assert info.length_s == 215.0
    assert info.track_id == "/track/1"
    assert info.url == "https://music.example/1"


def test_parse_multiple_artists_joined():
    assert parse_metadata({"xesam:artist": ["A", "B"]}).artist == "A / B"


def test_parse_artist_as_plain_string():
    assert parse_metadata({"xesam:artist": "Solo"}).artist == "Solo"


def test_parse_recovers_artist_from_title_without_splitting_artist_field():
    info = parse_metadata(
        {
            "xesam:title": "BTS (방탄소년단) '2.0' Official MV",
            "xesam:artist": ["HYBE LABELS"],
        }
    )
    assert info.title == "2.0"
    assert info.artist == "BTS"


def test_parse_keeps_title_pair_as_one_title():
    info = parse_metadata({"xesam:title": "螺旋 - RASEN", "xesam:artist": ["9Lana"]})
    assert info.title == "螺旋 - RASEN"
    assert info.artist == "9Lana"


def test_parse_strips_chrome_badge_and_youtube_suffix():
    info = parse_metadata({"xesam:title": "(309) 志铭 | YouTube Music", "xesam:artist": [""]})
    assert info.title == "志铭"


def test_parse_strips_trailing_dash_youtube():
    assert parse_metadata({"xesam:title": "Song - YouTube"}).title == "Song"


def test_parse_cleans_platform_grammar_from_mpris_title():
    info = parse_metadata(
        {
            "xesam:title": "BTS (방탄소년단) ‘SWIM’ Official MV",
            "xesam:artist": ["HYBE LABELS"],
        }
    )
    assert info.title == "SWIM"


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


def test_lyrics_lookup_gate_matches_classified_corpus():
    # Driven from the raw MPRIS fields through parse_metadata, the way production
    # reaches this gate. Feeding it the hand-written clean_title instead hid a rule
    # that skipped legitimate songs whose raw titles still carried upload grammar.
    results = {
        case.raw_title: lyrics_lookup_reason(
            parse_metadata(
                {
                    "xesam:title": case.raw_title,
                    "xesam:artist": [case.raw_artist] if case.raw_artist else [],
                }
            )
        )
        for case in MPRIS_TITLE_CASES
    }

    skipped = {title for title, reason in results.items() if reason}
    expected = {case.raw_title for case in MPRIS_TITLE_CASES if case.category == "not_music"}
    assert skipped - expected == set(), f"songs the gate would skip: {sorted(skipped - expected)}"
    assert expected - skipped == set(), f"non-songs the gate would query: {sorted(expected - skipped)}"


def test_lyrics_lookup_gate_explains_duration_and_keeps_song_lengths():
    long_track = TrackInfo("Long video", "Uploader", "", 2 * 60 * 60 + 1, "")
    song = TrackInfo("Long song", "Artist", "", 2 * 60 * 60, "")

    assert lyrics_lookup_reason(long_track) == "duration 7201s is longer than a normal song"
    assert lyrics_lookup_reason(song) is None


def test_the_non_song_gate_reads_what_the_player_reported():
    # Title cleaning strips the very markers that identify a non-song upload, so a
    # gate reading the cleaned title lets a one-hour compilation through. Both PRs
    # were green alone; together the cleaner removed the evidence the gate needs.
    raw = (
        "路小雨 Lu Xiao Yu｜不能說的秘密 Secret OST | One hour 一小時放鬆音樂｜"
        "周杰倫 Jay Chou｜Played by Elvis Piano 維敏彈鋼琴"
    )
    info = parse_metadata({"xesam:title": raw, "xesam:artist": ["Elvis Piano 維敏彈鋼琴"]})

    assert info.title == "不能說的秘密 Secret OST", "the cleaner should still tidy the title"
    assert info.reported_title == raw
    assert lyrics_lookup_reason(info) is not None, "a one-hour compilation reached the providers"


def test_a_bar_separated_remix_medley_is_not_queried():
    # The marker is found in the reported title, so the word and CJK counts have to
    # come from the same text: cleaning keeps only the first song, and counting
    # there let a three-song medley through to the providers.
    info = parse_metadata({"xesam:title": "春天里 | 晴天 | 走马 Remix", "xesam:artist": ["X"]})

    assert info.title == "春天里", "the cleaner should still tidy the title"
    assert lyrics_lookup_reason(info) == "title combines several song names"


def test_a_length_that_advances_with_the_clock_is_not_a_track_duration():
    # Recorded from plasma-browser-integration on a YouTube Music radio: the
    # reported length is the session's playtime, growing by the wall-clock gap at
    # every track change. By the third song it is past the two-hour gate, so the
    # lookup is skipped -- 88 of one night's 140 songs were never queried.
    detector = CumulativeLengthDetector()
    session = [(0.0, 319.0), (309.0, 628.0), (604.0, 923.0), (900.0, 1219.0)]

    verdicts = [detector.observe("browser", f"/track/{i}", length, at) for i, (at, length) in enumerate(session)]

    assert verdicts[:2] == [True, True], "one rising length is not yet evidence of a counter"
    assert verdicts[2:] == [False, False], "a length tracking the clock stayed trusted"


def test_an_ordinary_playlist_keeps_its_durations():
    # The negative control: real tracks played end to end. Each length is unrelated
    # to the gap before it, which is what separates a duration from a counter.
    detector = CumulativeLengthDetector()
    playlist = [(0.0, 319.0), (319.0, 214.0), (533.0, 402.0), (935.0, 187.0), (1122.0, 250.0)]

    verdicts = [detector.observe("browser", f"/track/{i}", length, at) for i, (at, length) in enumerate(playlist)]

    assert all(verdicts), "an ordinary playlist was mistaken for a session counter"


def test_a_reloaded_page_is_trusted_again():
    detector = CumulativeLengthDetector()
    for i, (at, length) in enumerate([(0.0, 319.0), (309.0, 628.0), (604.0, 923.0)]):
        detector.observe("browser", f"/track/{i}", length, at)
    assert not detector.trusted

    # The counter starts over, and the next lengths are ordinary durations again.
    detector.observe("browser", "/track/9", 240.0, 900.0)

    assert detector.trusted


def test_back_to_back_videos_keep_their_durations():
    # youtube.com and Bilibili play one video after another with no gap, so the time
    # between track changes is the previous video's length. A rule that only asked
    # whether the length grew by *at most* the elapsed time flagged this: every clip
    # longer than the last one looked like a counter advancing.
    detector = CumulativeLengthDetector()
    videos = [(0.0, 180.0), (180.0, 300.0), (480.0, 520.0), (1000.0, 610.0)]

    verdicts = [detector.observe("browser", f"/video/{i}", length, at) for i, (at, length) in enumerate(videos)]

    assert all(verdicts), "consecutive videos of rising length were read as a session counter"


def test_a_topic_channel_is_the_performer_without_the_suffix():
    # YouTube names an auto-generated artist channel "<Artist> - Topic" and Plasma
    # passes it on as the performer, so the artist reached the catalogues in a form
    # none of them lists: 富士山下 found nothing under "Eason Chan - Topic" and 41
    # lines under "Eason Chan".
    info = parse_metadata({"xesam:title": "富士山下", "xesam:artist": "Eason Chan - Topic"})

    assert info.artist == "Eason Chan"


def test_a_hyphen_in_a_real_name_survives():
    info = parse_metadata({"xesam:title": "Song", "xesam:artist": "Jay-Z"})

    assert info.artist == "Jay-Z"


def test_the_bilibili_site_suffix_leaves_the_title():
    # Bilibili reports no artist at all, so the page title is all there is and the
    # site name rode into every query.
    info = parse_metadata({"xesam:title": "周深-大鱼_哔哩哔哩_bilibili", "xesam:artist": ""})

    assert info.title == "周深-大鱼"


def test_a_televised_gala_is_not_a_song():
    # One page title covers a whole night of performances, which is why 演唱會 is
    # already refused; the New Year gala publishes the same shape.
    gala = parse_metadata({"xesam:title": "2026最美的夜bilibili跨年晚会_哔哩哔哩_bilibili", "xesam:artist": ""})
    song = parse_metadata({"xesam:title": "告白氣球", "xesam:artist": "周杰倫"})

    assert lyrics_lookup_reason(gala) == "title contains non-song marker '晚会'"
    assert lyrics_lookup_reason(song) is None
