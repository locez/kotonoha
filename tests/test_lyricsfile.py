"""LRCLIB's Lyricsfile representation must survive parsing and caching."""

from pathlib import Path

import pytest
from fixtures.arabic_words import ANA_INDI_HANEEN

from kotonoha.lyrics import lrclib
from kotonoha.lyrics.lyricsfile_parser import LyricsFileError, LyricsFileParser
from kotonoha.lyrics.models import LyricWord
from kotonoha.lyrics.payload import MAX_DECOMPRESSED_BYTES

SAMPLE_PATH = Path(__file__).parent / "fixtures" / "ana_indi_haneen.lyricsfile.yaml"
HEADER = "version: '1.0'\nmetadata: {title: Song, artist: Artist}\n"


def test_lrclib_prefers_complete_lyricsfile_word_timing_over_legacy_lrc() -> None:
    """The real API exposes the word version separately from its old line LRC."""
    lines = lrclib.parse_payload({
        "lyricsfile": SAMPLE_PATH.read_text(encoding="utf-8"),
        "syncedLyrics": "[01:01.35]انا عندي حنين ما بعرف لمين",
    })
    assert lines == tuple(case.line(index) for index, case in enumerate(ANA_INDI_HANEEN))


def test_lrclib_accepts_a_lyricsfile_without_legacy_lrc() -> None:
    """Word timing must not depend on a duplicated legacy representation."""
    lines = lrclib.parse_payload({"lyricsfile": SAMPLE_PATH.read_text(encoding="utf-8")})
    assert len(lines) == 28
    assert all(line.has_word_timing for line in lines)


def test_explicit_overlaps_and_zero_length_words_are_not_clipped() -> None:
    """A later line/word start must not overwrite an explicit source end."""
    lines = LyricsFileParser().parse(HEADER + """
lines:
- text: Hello world!
  start_ms: 1000
  end_ms: 5000
  words:
  - {text: 'Hello ', start_ms: 1000, end_ms: 4000}
  - {text: world, start_ms: 3000}
  - {text: '!', start_ms: 5000, end_ms: 5000}
- {text: other voice, start_ms: 2000, end_ms: 6000}
""")
    assert [(line.start, line.end) for line in lines] == [(1.0, 5.0), (2.0, 6.0)]
    assert lines[0].words == (LyricWord(1.0, 4.0, "Hello "), LyricWord(3.0, 5.0, "world"), LyricWord(5.0, 5.0, "!"))


def test_missing_line_ends_use_word_ends_next_line_duration_then_default() -> None:
    """Inference is explicit reader policy, not a claim made by the draft spec."""
    text = HEADER.replace("artist: Artist", "artist: Artist, duration_ms: 18000") + """
lines:
- text: last
  start_ms: 12000
  words: [{text: last, start_ms: 12000}]
- {text: first, start_ms: 0}
- text: overlapping
  start_ms: 2000
  words: [{text: overlapping, start_ms: 2000, end_ms: 8000}]
- {text: middle, start_ms: 7000}
"""
    lines = LyricsFileParser().parse(text)
    assert [(line.start, line.end) for line in lines] == [(0.0, 2.0), (2.0, 8.0), (7.0, 12.0), (12.0, 18.0)]
    assert lines[-1].words == (LyricWord(12.0, 18.0, "last"),)
    fallback = LyricsFileParser().parse(HEADER + "lines: [{text: last, start_ms: 12000}]\n")
    assert fallback[0].end == 17.0


@pytest.mark.parametrize("content", ["plain: hello\n", "lines: []\n", ""])
def test_plain_only_documents_do_not_invent_timed_lines(content: str) -> None:
    assert LyricsFileParser().parse(HEADER + content) == ()


@pytest.mark.parametrize("document", [
    HEADER + "lines: [",
    HEADER.replace("'1.0'", "'2.0'") + "lines: []",
    HEADER.replace("'1.0'", "1.0") + "lines: []",
    HEADER + "lines: null",
    HEADER + "lines: [{text: hello, start_ms: true}]",
    HEADER + "lines: [{text: hello, start_ms: 1.5}]",
    HEADER + "lines: [{text: hello, start_ms: -1}]",
    HEADER + "lines: [{text: hello, start_ms: 1000, end_ms: 999}]",
    HEADER + "lines: [{text: hello, start_ms: 1000, end_ms: null}]",
    HEADER + "lines: [{text: hello, start_ms: 999999999999999999999999}]",
    HEADER + "lines: [{text: hello, start_ms: " + "9" * 5000 + "}]",
    HEADER + "lines: [{text: hello, start_ms: 0, words: [{text: different, start_ms: 0}]}]",
    HEADER + "lines: [{text: ab, start_ms: 0, words: [{text: a, start_ms: 2}, {text: b, start_ms: 1}]}]",
    HEADER + "lines: [{text: a, start_ms: 0, end_ms: 2, words: [{text: a, start_ms: 1, end_ms: 3}]}]",
    HEADER.replace("artist: Artist", "artist: Artist, offset_ms: 100"),
    HEADER.replace("artist: Artist", "artist: Artist, instrumental: true") + "plain: vocals",
    HEADER + "lines: []\nlines: []",
    HEADER + "plain: !!python/object/apply:os.system ['false']",
    HEADER + "plain: &recursive [*recursive]",
    HEADER + "plain: !!binary ZGF0YQ==",
    HEADER + "extra: " + "[" * 40 + "0" + "]" * 40,
    HEADER + "extra: [" + "0," * 50001 + "]",
    HEADER + "lines: [" + "{}," * 5001 + "]",
    HEADER + "lines: [{text: '', start_ms: 0, words: [" + "{}," * 4097 + "]}]",
    HEADER + "plain: " + "a" * MAX_DECOMPRESSED_BYTES,
    HEADER + "plain: '\ud800'",
    HEADER + 'lines: [{text: "\\uD800", start_ms: 0}]',
    HEADER + "plain: '\x00'",
], ids=lambda value: value[:60])
def test_invalid_or_hostile_lyricsfile_is_rejected_and_lrc_still_works(document: str) -> None:
    """No partial structured timeline, object construction, or unbounded YAML work."""
    with pytest.raises(LyricsFileError):
        LyricsFileParser().parse(document)
    fallback = lrclib.parse_payload({"lyricsfile": document, "syncedLyrics": "[00:01.00]fallback"})
    assert len(fallback) == 1
    assert fallback[0].text == "fallback"
