from kotonoha.lyrics.lrc_parser import merge_translation, parse_lrc
from kotonoha.lyrics.match import Candidate, best_match, normalize
from kotonoha.lyrics.yrc_parser import parse_yrc

# Real lines from the live Netease api/song/lyric/v1 response (id=299981).
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


def test_normalize_strips_notes_and_punctuation():
    assert normalize("暧昧 (Live)") == "暧昧"
    assert normalize("Song feat. X") == "song"
    assert normalize("A - B!") == "ab"


def test_best_match_prefers_duration():
    cands = [
        Candidate("1", "暧昧", "王菲", 282.0),   # right duration
        Candidate("2", "暧昧 (Live)", "王菲", 350.0),  # wrong duration
    ]
    best = best_match(cands, "曖昧", "王菲", duration_s=281.0)
    assert best is not None and best.song_id == "1"


def test_best_match_rejects_when_nothing_close():
    cands = [Candidate("9", "totally other", "someone", 999.0)]
    assert best_match(cands, "暧昧", "王菲", duration_s=281.0) is None


def test_best_match_empty():
    assert best_match([], "t", "a", 100.0) is None
