from kotonoha.karaoke import (
    active_word_index,
    line_fill_fraction,
    line_progress,
    word_fill_fractions,
)
from kotonoha.model import LyricLine, LyricWord


def test_line_fill_fraction_basic():
    assert line_fill_fraction(10.0, 20.0, 5.0) == 0.0
    assert line_fill_fraction(10.0, 20.0, 15.0) == 0.5
    assert line_fill_fraction(10.0, 20.0, 25.0) == 1.0


def test_line_fill_fraction_zero_width():
    assert line_fill_fraction(10.0, 10.0, 9.0) == 0.0
    assert line_fill_fraction(10.0, 10.0, 10.0) == 1.0


def _words():
    return (
        LyricWord(start=0.0, end=1.0, text="a"),
        LyricWord(start=1.0, end=2.0, text="b"),
        LyricWord(start=2.0, end=3.0, text="c"),
    )


def test_word_fill_fractions():
    fracs = word_fill_fractions(_words(), 1.5)
    assert fracs == (1.0, 0.5, 0.0)


def test_active_word_index_midword():
    assert active_word_index(_words(), 1.5) == 1


def test_active_word_index_before_all():
    assert active_word_index(_words(), -1.0) == -1


def test_active_word_index_after_all():
    assert active_word_index(_words(), 99.0) == 2


def test_word_without_timing_is_not_blocking():
    words = (LyricWord(start=None, end=None, text="?"), LyricWord(start=1.0, end=2.0, text="b"))
    assert word_fill_fractions(words, 1.5) == (0.0, 0.5)


def test_line_progress_prefers_word_timing():
    line = LyricLine(index=0, id="L", start=0.0, end=10.0, text="abc", translation="", words=_words())
    # Words span 0..3, so t=1.5 is halfway through the *words*, not the line.
    assert line_progress(line, 1.5) == 0.5


def test_line_progress_falls_back_to_line_span():
    line = LyricLine(index=0, id="L", start=0.0, end=10.0, text="abc", translation="", words=())
    assert line_progress(line, 5.0) == 0.5
