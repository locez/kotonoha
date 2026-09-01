"""Turning a provider's payload into timed lines.

The formats are the deterministic half of the pipeline: given the same bytes they
must always yield the same lines, including for the malformed and hostile inputs a
real catalogue serves.
"""

import pytest

from kotonoha.lyrics.krc_parser import parse_krc
from kotonoha.lyrics.lrc_parser import merge_translation, parse_lrc
from kotonoha.lyrics.models import LyricLine, LyricsDocument, LyricWord
from kotonoha.lyrics.translation import TranslationMerger
from kotonoha.lyrics.yrc_parser import parse_yrc

YRC_SAMPLE = (
    '{"t":0,"c":[{"tx":"作词: "},{"tx":"林夕"}]}\n'
    "[1300,1950](1300,243,0)眉(1543,243,0)目(1786,243,0)里(2029,243,0)似(2272,243,0)哭(2515,243,0)不(2758,243,0)似(3001,249,0)哭\n"
    "[3440,6530](3440,240,0)还(3680,450,0)祈(4130,2660,0)求\n"
)


def test_parse_yrc_word_timing():
    lines = parse_yrc(YRC_SAMPLE)
    assert len(lines) == 2  # JSON metadata line skipped
    first = lines[0]
    assert first.text == "眉目里似哭不似哭"
    assert first.start == 1.3
    assert first.end == 3.25  # 1300 + 1950 ms
    assert len(first.words) == 8
    assert first.words[0].text == "眉"
    assert first.words[0].start == 1.3
    assert first.words[0].end == 1.543
    assert first.has_word_timing


def test_parse_yrc_skips_metadata_and_blank():
    assert parse_yrc('{"t":0,"c":[{"tx":"x"}]}\n\n   \n') == []


def test_parse_krc_is_exported_for_lyric_tests():
    assert parse_krc(b"not krc") == []


LRC_SAMPLE = "[00:01.30]眉目里似哭不似哭\n[00:03.44]还祈求什么说不出\n[00:10.560]陪着你轻呼着烟圈\n"


def test_parse_lrc_lines_and_end_times():
    lines = parse_lrc(LRC_SAMPLE)
    assert [round(line.start, 2) for line in lines] == [1.3, 3.44, 10.56]
    assert lines[0].end == 3.44  # next line's start
    assert lines[0].text == "眉目里似哭不似哭"
    assert not lines[0].has_word_timing  # line-timed only


def test_parse_lrc_multiple_tags_same_line():
    lines = parse_lrc("[00:01.00][00:05.00]repeat\n")
    assert len(lines) == 2
    assert all(line.text == "repeat" for line in lines)


def test_parse_lrc_enhanced_inline_timestamps_into_word_spans():
    lines = parse_lrc(
        "[00:00.000]<00:00.000>堕<00:00.155><00:00.156> - <00:00.311>Zyboy"
        "<00:00.466><00:00.467>忠<00:00.622>\n[00:01.000]next\n"
    )

    assert lines[0].text == "堕 - Zyboy忠"
    assert lines[0].end == 1.0
    assert lines[0].words == (
        LyricWord(0.0, 0.155, "堕"),
        LyricWord(0.156, 0.311, " - "),
        LyricWord(0.311, 0.466, "Zyboy"),
        LyricWord(0.467, 0.622, "忠"),
    )
    assert lines[0].has_word_timing


def test_parse_lrc_enhanced_applies_offset_to_line_and_word_timestamps():
    lines = parse_lrc("[offset:+100]\n[00:01.000]<00:01.000>hello<00:01.500>\n")

    assert lines[0].start == 0.9
    assert lines[0].words == (LyricWord(0.9, 1.4, "hello"),)


def test_merge_translation_by_nearest_time():
    base = parse_lrc("[00:01.00]hello\n[00:05.00]world\n")
    trans = parse_lrc("[00:01.05]你好\n[00:05.10]世界\n")
    merged = merge_translation(base, trans)
    assert merged[0].translation == "你好"
    assert merged[1].translation == "世界"


def test_merge_translation_out_of_tolerance_left_blank():
    base = parse_lrc("[00:01.00]hello\n")
    trans = parse_lrc("[00:09.00]too far\n")
    assert merge_translation(base, trans)[0].translation == ""


def test_translation_transform_exposes_timestamp_and_positional_alignment():
    base = parse_lrc("[00:01.00]hello\n[00:05.00]world\n")
    translated = parse_lrc("[00:01.05]你好\n[00:05.10]世界\n")
    document = LyricsDocument("test", lines=tuple(base))
    merger = TranslationMerger()

    timestamp = merger.merge_by_timestamp(base, translated)
    positional = merger.merge_by_index(document, ("你好", "世界"))

    assert [line.translation for line in timestamp] == ["你好", "世界"]
    assert [line.translation for line in positional.lines] == ["你好", "世界"]
    assert all(line.translation == "" for line in document.lines)


def test_translation_transform_rejects_invalid_tolerance():
    import math

    with pytest.raises(ValueError, match="tolerance"):
        TranslationMerger(-0.1)
    with pytest.raises(ValueError, match="tolerance"):
        TranslationMerger(math.inf)


def test_translation_transform_is_deterministic_for_unsorted_duplicates_and_mismatch():
    base = (
        LyricLine(0, "b0", 1.0, 2.0, "one", ""),
        LyricLine(1, "b1", 5.0, 6.0, "two", ""),
        LyricLine(2, "b2", 9.0, 10.0, "three", ""),
    )
    translation = (
        LyricLine(0, "t2", 5.1, 6.0, "two translated", ""),
        LyricLine(1, "t0-second", 1.1, 2.0, "duplicate later", ""),
        LyricLine(2, "t0-first", 1.1, 2.0, "duplicate first", ""),
    )

    merged = TranslationMerger().merge_by_timestamp(base, translation)

    assert [line.translation for line in merged] == ["duplicate later", "two translated", ""]


def test_translation_transform_respects_exact_tolerance_boundary():
    base = (LyricLine(0, "base", 1.0, 2.0, "one", ""),)
    translation = (LyricLine(0, "translation", 1.4, 2.0, "included", ""),)

    assert TranslationMerger(0.4).merge_by_timestamp(base, translation)[0].translation == "included"
    assert TranslationMerger(0.39).merge_by_timestamp(base, translation)[0].translation == ""


def test_a_yrc_timestamp_too_large_for_a_float_skips_its_line():
    # Same conversion, same provider-controlled digits: an unbounded run divided by
    # 1000.0 raised OverflowError out of parsing and out of the resolver with it.
    huge = "[" + "9" * 400 + ",1950](1300,243,0)x\n"
    real = "[1300,1950](1300,243,0)眉(1543,243,0)目\n"

    lines = parse_yrc(huge + real)

    assert [line.text for line in lines] == ["眉目"]


def test_translation_merging_stays_cheap_as_a_provider_sends_more_lines():
    # Both tracks come from a provider and their lengths are its choice. Scanning
    # the whole translation for every base line was quadratic: measured, 500 lines
    # took 8 ms, 2000 took 112 ms and 8000 took 985 ms — a second of synchronous
    # work on the loop that also drives the UI, for a response well inside the size
    # the providers already allow.
    import time

    from kotonoha.lyrics.models import LyricLine

    def pair(count: int) -> tuple[list[LyricLine], list[LyricLine]]:
        base = "".join(f"[{i // 60:02d}:{i % 60:02d}.{i % 100:02d}]line {i}\n" for i in range(count))
        trans = "".join(f"[{i // 60:02d}:{i % 60:02d}.{i % 100:02d}]trans {i}\n" for i in range(count))
        return parse_lrc(base), parse_lrc(trans)

    small_base, small_trans = pair(500)
    large_base, large_trans = pair(4000)
    assert small_base and large_base, "the sample did not parse; the timing would mean nothing"

    start = time.perf_counter()
    merge_translation(small_base, small_trans)
    small = time.perf_counter() - start

    start = time.perf_counter()
    merged = merge_translation(large_base, large_trans)
    large = time.perf_counter() - start

    # Eight times the lines must not cost anything like sixty-four times the work.
    assert large < small * 20 + 0.05, f"merging grew faster than the input: {small:.3f}s -> {large:.3f}s"
    assert merged[0].translation == "trans 0", "the nearest translation is still attached"


def test_a_response_full_of_valid_tags_does_not_become_unbounded_lines():
    # The byte budget upstream still allows tens of thousands of valid tags, and
    # each becomes an object the overlay holds and the cache stores. Measured
    # before the cap: 2 MB of tags produced 174,762 lines in 400 ms on the loop.
    from kotonoha.lyrics.lrc_parser import MAX_LINES

    tag = "[00:01.00]x\n"
    body = tag * (2 * 1024 * 1024 // len(tag))

    lines = parse_lrc(body)

    assert len(lines) == MAX_LINES

    ordinary = "".join(f"[{i // 60:02d}:{i % 60:02d}.00]line {i}\n" for i in range(120))
    assert len(parse_lrc(ordinary)) == 120, "an ordinary lyric sheet must be untouched"
