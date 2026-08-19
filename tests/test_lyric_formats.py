"""Turning a provider's payload into timed lines.

The formats are the deterministic half of the pipeline: given the same bytes they
must always yield the same lines, including for the malformed and hostile inputs a
real catalogue serves.
"""

from kotonoha.lyrics.krc_parser import parse_krc
from kotonoha.lyrics.lrc_parser import merge_translation, parse_lrc
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

    from kotonoha.model import LyricLine

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
