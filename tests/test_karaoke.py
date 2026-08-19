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


def test_the_sweep_follows_a_line_with_no_separators(_session_qapp):
    # KRC and YRC build the line by concatenating word texts, and the sweep assumed
    # one space between every pair: nine characters ran 24px past a 108px line.
    from kotonoha.karaoke_label import KaraokeLabel
    from kotonoha.model import LyricLine, LyricWord

    text = "我曾经跨过山和大海"
    words = tuple(LyricWord(i * 0.5, (i + 1) * 0.5, ch) for i, ch in enumerate(text))
    label = KaraokeLabel(None)
    label.set_line(LyricLine(0, "L0", 0.0, 4.5, text, "", words), True)

    rendered = label.fontMetrics().horizontalAdvance(text)
    end_of_last_word = label._word_offsets[-1] + label._word_widths[-1]

    assert end_of_last_word == rendered, "the sweep geometry is wider than the text it sweeps"


def test_the_interlude_marker_is_a_row_the_sweep_runs_across():
    # The only thing on screen during a break, so it has to say something at every
    # point in the span, including both ends.
    from kotonoha.karaoke import interlude_text
    from kotonoha.model import Interlude

    wait = Interlude(100.0, 130.0)

    # The row is what the sweep runs across, so it does not change with the wait;
    # the accent moving over it is the progress.
    assert interlude_text(wait, 100.0, style="dots", countdown="off") == "●\u2003●\u2003●"
    assert interlude_text(wait, 115.0, style="dots", countdown="off") == "●\u2003●\u2003●"
    assert interlude_text(wait, 115.0, style="symbol", countdown="off") == "♪"


def test_the_interlude_countdown_is_optional_and_typed():
    from kotonoha.karaoke import interlude_text
    from kotonoha.model import Interlude

    wait = Interlude(100.0, 130.0)

    assert interlude_text(wait, 115.0, style="dots", countdown="percent").endswith("50%")
    assert interlude_text(wait, 115.0, style="dots", countdown="seconds").endswith("15s")
    # Rounded up, so the last whole second still reads as 1 rather than 0.
    assert interlude_text(wait, 129.2, style="symbol", countdown="seconds") == "♪\u2003\u20031s"
    assert interlude_text(wait, 131.0, style="symbol", countdown="seconds") == "♪\u2003\u20030s"


def test_an_unknown_marker_setting_still_shows_something():
    # This is the only thing on screen at the time, so an unreadable config value
    # must not blank the panel.
    from kotonoha.karaoke import interlude_text
    from kotonoha.model import Interlude

    assert interlude_text(Interlude(0.0, 10.0), 5.0, style="nonsense", countdown="nonsense") == "●\u2003●\u2003●"
