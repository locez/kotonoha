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
