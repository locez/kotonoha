import pytest

from kotonoha.lyrics.select import build_snapshot, find_current_index, song_timing
from kotonoha.model import LyricLine, LyricWord


def _line(i, start, end, text, words=()):
    return LyricLine(index=i, id=f"L{i}", start=start, end=end, text=text, translation="", words=words)


LINES = [
    _line(0, 0.0, 5.0, "one"),
    _line(1, 5.0, 10.0, "two"),
    _line(2, 10.0, 15.0, "three"),
]


def test_find_current_index():
    assert find_current_index(LINES, -1.0) == -1  # before first
    assert find_current_index(LINES, 0.0) == 0
    assert find_current_index(LINES, 7.5) == 1
    assert find_current_index(LINES, 99.0) == 2  # past end -> last


def test_build_snapshot_middle():
    snap = build_snapshot(
        LINES, 7.5, provider="MPRIS", song_id="1", title="T", artist="A", is_playing=True
    )
    assert snap.found is True
    assert snap.current is not None and snap.current.text == "two"
    assert snap.previous is not None and snap.previous.text == "one"
    assert snap.next is not None and snap.next.text == "three"
    assert snap.current_time == 7.5
    assert snap.timing == "Line"
    assert snap.title == "T"


def test_build_snapshot_before_first_line():
    snap = build_snapshot(LINES, -1.0, provider="MPRIS", song_id=None, title=None, artist=None, is_playing=True)
    assert snap.found is True
    assert snap.current is None
    assert snap.next is not None and snap.next.text == "one"


def test_build_snapshot_empty_lines():
    snap = build_snapshot([], 3.0, provider="MPRIS", song_id=None, title="T", artist="A", is_playing=False)
    assert snap.found is False
    assert snap.current is None
    assert snap.current_time == 3.0


def test_song_timing_word_vs_line():
    assert song_timing(LINES) == "Line"
    worded = [_line(0, 0.0, 1.0, "hi", words=(LyricWord(0.0, 0.5, "hi"),))]
    assert song_timing(worded) == "Word"


def test_word_karaoke_flag_via_snapshot():
    worded = [_line(0, 0.0, 2.0, "hi", words=(LyricWord(0.0, 1.0, "hi"),))]
    snap = build_snapshot(worded, 0.5, provider="MPRIS", song_id="1", title=None, artist=None, is_playing=True)
    assert snap.timing == "Word"
    assert snap.word_karaoke is True


# Timings taken from 春夏秋冬的你 / 王宇良 as NetEase serves it: a 35.3s instrumental
# break sits between two verses, and the last line ends 7s before the track does.
_VERSE = [_line(i, 92.9 + 6.66 * i, 92.9 + 6.66 * (i + 1), f"line {i}") for i in range(3)]
BREAK_SONG = [
    *_VERSE,
    _line(3, 106.2, 141.5, "before the break"),
    _line(4, 141.5, 148.2, "after the break"),
    _line(5, 148.2, 153.2, "last"),
]


def test_an_instrumental_break_is_not_the_line_before_it():
    # An LRC has no end times, so the parser gives every line the next line's start
    # and a 35s break was absorbed into the line before it, which then swept for
    # half a minute as though it were still being sung.
    two_seconds_in = build_snapshot(
        BREAK_SONG, 108.2, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )
    deep_in_the_break = build_snapshot(
        BREAK_SONG, 131.2, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )

    assert two_seconds_in.current is not None
    assert two_seconds_in.current.text == "before the break"
    assert deep_in_the_break.current is None
    # The line that just finished is the previous one now, so the overlay keeps its
    # context instead of jumping back to the top of the song.
    assert deep_in_the_break.previous is not None
    assert deep_in_the_break.previous.text == "before the break"
    assert deep_in_the_break.next is not None
    assert deep_in_the_break.next.text == "after the break"


def test_the_last_line_stops_when_the_track_says_where_it_ends():
    still_singing = build_snapshot(
        BREAK_SONG, 150.0, provider="p", song_id=None, title="t", artist="a", is_playing=True,
        duration_s=200.0,
    )
    after_the_words = build_snapshot(
        BREAK_SONG, 160.0, provider="p", song_id=None, title="t", artist="a", is_playing=True,
        duration_s=200.0,
    )

    assert still_singing.current is not None
    assert after_the_words.current is None


def test_without_a_duration_the_last_line_stays():
    # There is nothing to count towards, and a marker that cannot move reads as a
    # wait that never finishes — worse than the last line simply staying put.
    unbounded = build_snapshot(
        BREAK_SONG, 160.0, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )

    assert unbounded.current is not None
    assert unbounded.interlude is None


def test_a_continuously_sung_song_has_no_interlude():
    # The negative control. Every gap here matches the song's own pace, so nothing
    # may be read as a break — otherwise ordinary lines would blank the overlay.
    dense = [_line(i, 2.58 * i, 2.58 * (i + 1), f"line {i}") for i in range(12)]

    for position in (1.0, 5.0, 14.0, 25.0, 30.0):
        snapshot = build_snapshot(
            dense, position, provider="p", song_id=None, title="t", artist="a", is_playing=True
        )
        assert snapshot.current is not None, f"a sung line was hidden at {position}s"


def test_a_merely_longer_phrase_is_not_a_break():
    # A held phrase runs past the song's pace without being an interlude. The
    # threshold has to sit above it, or an ordinary line blanks the overlay in its
    # own second half.
    held = [
        _line(0, 0.0, 4.0, "one"),
        _line(1, 4.0, 8.0, "two"),
        _line(2, 8.0, 14.0, "held for six"),  # 1.5x the 4s pace
        _line(3, 14.0, 18.0, "four"),
    ]

    late_in_the_held_line = build_snapshot(
        held, 13.0, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )

    assert late_in_the_held_line.current is not None
    assert late_in_the_held_line.current.text == "held for six"


def test_the_interlude_span_is_carried_for_the_overlay():
    # The overlay cannot work the span out for itself: an LRC gives every line the
    # next one's start, so the lines show no gap at all.
    intro = build_snapshot(
        BREAK_SONG, 40.0, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )
    mid = build_snapshot(
        BREAK_SONG, 131.2, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )

    assert intro.interlude is not None
    assert intro.interlude.start == 0.0 and intro.interlude.end == BREAK_SONG[0].start
    assert mid.interlude is not None
    assert mid.interlude.end == 141.5
    assert 0.0 < mid.interlude.progress(131.2) < 1.0
    assert mid.interlude.progress(0.0) == 0.0 and mid.interlude.progress(999.0) == 1.0


def test_a_sung_line_carries_no_interlude():
    singing = build_snapshot(
        BREAK_SONG, 108.2, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )

    assert singing.interlude is None


def test_a_breath_in_a_dense_song_is_not_a_break():
    # The ratio alone is not enough. 走马 sits at a 3.15s median, so 2.5x is 7.9s and
    # a breath between two lines crossed it — the panel went blank mid-verse, on a
    # song with no interlude there at all. Measured over nine songs, every real break
    # ran 13.1s or longer and every held line or breath stopped at 11.7s.
    dense = [_line(i, 3.15 * i, 3.15 * (i + 1), f"line {i}") for i in range(10)]
    breath = [
        *dense[:5],
        _line(5, 15.75, 23.7, "held across a breath"),  # 7.95s, over 2.5x the median
        *[_line(i, 23.7 + 3.15 * (i - 6), 23.7 + 3.15 * (i - 5), f"line {i}") for i in range(6, 10)],
    ]

    for position in (17.0, 20.0, 23.0):
        snapshot = build_snapshot(
            breath, position, provider="p", song_id=None, title="t", artist="a", is_playing=True
        )
        assert snapshot.current is not None, f"a breath blanked the panel at {position}s"


def test_a_real_break_in_a_dense_song_is_still_read():
    dense = [_line(i, 3.15 * i, 3.15 * (i + 1), f"line {i}") for i in range(5)]
    with_break = [*dense, _line(5, 15.75, 49.45, "before the break"), _line(6, 49.45, 52.6, "after")]

    mid = build_snapshot(
        with_break, 35.0, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )

    assert mid.current is None
    assert mid.interlude is not None


def test_a_line_stops_sweeping_when_it_has_plainly_been_sung():
    # An LRC gives every line the next one's start, so a line before a pause was swept
    # across the whole pause and crept on long after the words had stopped. Measured
    # on songs that do carry word timings, a line sings for about the song's median
    # span and the longest ran to twice it, so the cap never cuts a line short.
    dense = [_line(i, i * 2.4, (i + 1) * 2.4, f"line {i}") for i in range(5)]
    before_a_pause = [*dense, _line(5, 12.0, 21.6, "before the pause"), _line(6, 21.6, 24.0, "after")]

    swept = build_snapshot(
        before_a_pause, 13.0, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )

    assert swept.current is not None
    assert swept.current.text == "before the pause"
    assert swept.current.end - swept.current.start <= 5.0  # not the 9.6s to the next line


def test_word_timings_say_exactly_when_a_line_stops():
    words = (LyricWord(text="sung ", start=0.0, end=1.4),)
    lines = [
        LyricLine(index=0, id="L0", start=0.0, end=9.0, text="sung", translation="", words=words),
        _line(1, 9.0, 11.0, "next"),
    ]

    snapshot = build_snapshot(
        lines, 1.0, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )

    assert snapshot.current is not None
    assert snapshot.current.end == 1.4


def test_an_ordinary_line_keeps_its_own_end():
    dense = [_line(i, i * 2.4, (i + 1) * 2.4, f"line {i}") for i in range(6)]

    snapshot = build_snapshot(
        dense, 5.0, provider="p", song_id=None, title="t", artist="a", is_playing=True
    )

    assert snapshot.current is not None
    assert snapshot.current.end == pytest.approx(7.2)  # untouched: it runs into the next line
