"""Public TTML lyric corpus, including unsafe and unsupported input boundaries."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from kotonoha.display.karaoke import word_fill_fractions
from kotonoha.lyrics.adapter import LyricsDocumentAdapter
from kotonoha.lyrics.local import load_embedded_lyrics, load_local_lyrics, load_sidecar_lyrics
from kotonoha.lyrics.models import LyricLine, LyricWord
from kotonoha.lyrics.ttml_parser import parse_ttml


def ttml(body: str, *, attributes: str = "") -> str:
    """Wrap public lyric markup in a typical Apple/AMLL TTML document."""
    return (
        '<tt xmlns="http://www.w3.org/ns/ttml" '
        'xmlns:ttm="http://www.w3.org/ns/ttml#metadata" '
        f'{attributes}><body><div>{body}</div></body></tt>'
    )


WORD_TTML = ttml(
    '<p begin="00:01.000" end="00:04.000">'
    '<span begin="00:01.000" end="00:02.000">你</span>'
    '<span begin="00:02.000" end="00:03.500">好</span>'
    '<span ttm:role="x-translation">Hello</span>'
    '<span ttm:role="x-roman">Ni hao</span></p>'
)


@dataclass(frozen=True)
class TtmlCase:
    """Canonical line output and the nearest input that must not mean the same thing."""

    name: str
    text: str
    expected: tuple[LyricLine, ...]
    negative: str


CASES = (
    TtmlCase(
        "apple-amll-words-and-translation",
        WORD_TTML,
        (LyricLine(0, "L0", 1.0, 4.0, "你好", "Hello", (
            LyricWord(1.0, 2.0, "你"), LyricWord(2.0, 3.5, "好"),
        )),),
        ttml('<p begin="1s" end="4s">你好</p>'),
    ),
    TtmlCase(
        "line-timing-with-styled-text-and-break",
        ttml('<p begin="00:00:01.25" dur="2s">Hello <span>world</span><br/>again &amp; again</p>'),
        (LyricLine(0, "L0", 1.25, 3.25, "Hello world\nagain & again", ""),),
        ttml('<p>Hello <span>world</span></p>'),
    ),
    TtmlCase(
        "offset-clock-and-duration",
        ttml('<p begin="1m" dur="1500ms"><span begin="60s" dur="1s">One</span>!</p>'),
        (LyricLine(0, "L0", 60.0, 61.5, "One!", "", (
            LyricWord(60.0, 61.0, "One"), LyricWord(None, None, "!"),
        )),),
        ttml('<p begin="1m" dur="-1500ms">One!</p>'),
    ),
    TtmlCase(
        "infer-paragraph-span-from-words",
        ttml('<p><span begin="1s" end="2s">Sing</span></p>'),
        (LyricLine(0, "L0", 1.0, 2.0, "Sing", "", (LyricWord(1.0, 2.0, "Sing"),)),),
        ttml('<p><span begin="1s">Sing</span></p>'),
    ),
    TtmlCase(
        "namespaced-and-sorted",
        '<t:tt xmlns:t="http://www.w3.org/ns/ttml"><t:body><t:div>'
        '<t:p begin="2s" end="3s">Second</t:p><t:p begin="0s" end="1s">First</t:p>'
        '</t:div></t:body></t:tt>',
        (LyricLine(0, "L0", 0.0, 1.0, "First", ""), LyricLine(1, "L1", 2.0, 3.0, "Second", "")),
        '<html><body><p begin="0s" end="1s">First</p></body></html>',
    ),
    TtmlCase(
        "whitespace-and-nested-style",
        ttml('<p begin="1s" end="4s">\n  <span begin="1s" end="2s"><span>Hello</span></span> '
             '<span begin="2s" end="3s">world</span>\n</p>'),
        (LyricLine(0, "L0", 1.0, 4.0, "Hello world", "", (
            LyricWord(1.0, 2.0, "Hello"), LyricWord(None, None, " "), LyricWord(2.0, 3.0, "world"),
        )),),
        ttml('<p begin="1s" end="4s"><span begin="1s" end="2s">Hello</span>'
             '<span begin="2s" end="3s">world</span></p>'),
    ),
    TtmlCase(
        "background-does-not-contaminate-lead",
        ttml('<p begin="1s" end="4s"><span begin="1s" end="2s">Lead</span>'
             '<span ttm:role="x-bg"><span begin="2s" end="3s">(Echo)</span></span></p>'),
        (LyricLine(0, "L0", 1.0, 4.0, "Lead", "", (LyricWord(1.0, 2.0, "Lead"),)),),
        ttml('<p begin="1s" end="4s"><span begin="1s" end="2s">Lead</span>'
             '<span begin="2s" end="3s">(Echo)</span></p>'),
    ),
    TtmlCase(
        "nested-preserved-whitespace",
        ttml('<p begin="1s" end="2s"><span xml:space="preserve">  spaced  </span></p>'),
        (LyricLine(0, "L0", 1.0, 2.0, "  spaced  ", ""),),
        ttml('<p begin="1s" end="2s"><span>  spaced  </span></p>'),
    ),
    TtmlCase(
        "background-translation-stays-out-of-lead",
        ttml('<p begin="1s" end="2s">Lead<span ttm:role="x-translation">主唱</span>'
             '<span ttm:role="x-bg">Echo<span ttm:role="x-translation">和声</span></span></p>'),
        (LyricLine(0, "L0", 1.0, 2.0, "Lead", "主唱"),),
        ttml('<p begin="1s" end="2s">Lead<span ttm:role="x-translation">和声</span></p>'),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_ttml_behavior_corpus(case: TtmlCase) -> None:
    assert tuple(parse_ttml(case.text)) == case.expected
    assert tuple(parse_ttml(case.negative)) != case.expected


@pytest.mark.parametrize("timestamp", ["-1s", "NaN", "inf", "00:60:00", "00:01:60", "1e9s", "9" * 400 + "s"])
def test_invalid_times_never_become_usable_lyrics(timestamp: str) -> None:
    assert parse_ttml(ttml(f'<p begin="{timestamp}" end="10s">Bad</p>')) == []


@pytest.mark.parametrize("body", [
    '<p begin="3s" end="1s">Backwards</p>',
    '<p begin="1s" end="3s"><span begin="2s" end="1s">Bad word</span></p>',
    '<p begin="1s" end="3s"><span begin="2s" end="4s">Outside line</span></p>',
    '<p begin="1s" end="3s"><span begin="2s">Incomplete word</span></p>',
    '<p begin="1s" end="3s"></p>',
])
def test_invalid_spans_and_empty_lines_are_unavailable(body: str) -> None:
    assert parse_ttml(ttml(body)) == []


@pytest.mark.parametrize("text", [
    '<tt><body>',
    '<!DOCTYPE tt [<!ENTITY lyric "expanded">]><tt><body><p begin="0s" end="1s">&lyric;</p></body></tt>',
    '<!DOCTYPE tt SYSTEM "file:///etc/passwd"><tt/>',
    '<tt>' + '<div>' * 100 + '</div>' * 100 + '</tt>',
    ttml('<p begin="0s" end="1s">x</p>') + ' ' * (4 * 1024 * 1024),
    ttml('<p begin="0s" end="1s">' + '<span>x</span>' * 30000 + '</p>'),
    ttml('<div timeContainer="seq"><p begin="0s" end="1s">x</p></div>'),
    ttml('<p begin="0s" end="1s">x</p>', attributes=(
        'xmlns:ttp="http://www.w3.org/ns/ttml#parameter" ttp:timeBase="smpte"'
    )),
])
def test_unsafe_or_unsupported_documents_are_rejected(text: str) -> None:
    assert parse_ttml(text) == []


def test_xml_encoding_and_preserved_spaces() -> None:
    text = '<?xml version="1.0" encoding="UTF-16"?>' + ttml(
        '<p begin="1s" end="2s" xml:space="preserve"> 你好  世界 </p>'
    )
    assert parse_ttml(text.encode("utf-16"))[0].text == " 你好  世界 "


def test_ttml_sidecar_reaches_word_highlighting(tmp_path: Path) -> None:
    audio = tmp_path / "song.flac"
    audio.with_suffix(".ttml").write_text(WORD_TTML, encoding="utf-8")
    document = LyricsDocumentAdapter().adapt(load_sidecar_lyrics(audio), source_id="sidecar")
    assert document.has_word_timing
    assert document.lines[0].translation == "Hello"
    assert word_fill_fractions(document.lines[0].words, 1.5) == (0.5, 0.0)


@pytest.mark.parametrize(("xml", "lrc", "expected"), [
    (WORD_TTML, "[00:01]line", "你好"),
    (ttml('<p begin="1s" end="3s">line</p>'), "[00:01]<00:01>word<00:02> timing<00:03>", "word timing"),
    ('<tt>broken', "[00:01]fallback", "fallback"),
    (WORD_TTML, "[00:01]<00:01>word<00:02> timing<00:03>", "你好"),
])
def test_sidecars_prefer_actual_word_timing_and_fall_back(
    tmp_path: Path, xml: str, lrc: str, expected: str,
) -> None:
    audio = tmp_path / "song.flac"
    audio.with_suffix(".ttml").write_text(xml, encoding="utf-8")
    audio.with_suffix(".lrc").write_text(lrc, encoding="utf-8")
    assert load_sidecar_lyrics(audio)[0].text == expected


def test_ttml_sidecar_obeys_the_existing_local_file_boundary(tmp_path: Path) -> None:
    directory = tmp_path / "audio"
    directory.mkdir()
    outside = tmp_path / "outside.ttml"
    outside.write_text(WORD_TTML, encoding="utf-8")
    audio = directory / "song.flac"
    audio.with_suffix(".ttml").symlink_to(outside)
    assert load_sidecar_lyrics(audio) == []


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_entity_rejection_cannot_be_bypassed_by_xml_encoding(encoding: str) -> None:
    xml = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        '<!DOCTYPE tt [<!ENTITY line "expanded">]>'
        '<tt><body><p begin="1s" end="2s">&line;</p></body></tt>'
    )
    assert parse_ttml(xml.encode(encoding)) == []


def test_ttml_uses_absolute_song_positions_inside_timed_divs() -> None:
    xml = ttml(
        '<div begin="10s" end="20s"><p begin="10s" end="15s">'
        '<span begin="10s" end="11s">Sing</span></p></div>'
    )
    line = parse_ttml(xml)[0]
    assert (line.start, line.end, line.words) == (10.0, 15.0, (LyricWord(10.0, 11.0, "Sing"),))


def test_embedded_ttml_words_beat_line_sidecar_and_first_line_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutagen = pytest.importorskip("mutagen")

    @dataclass
    class TaggedAudio:
        tags: dict[str, list[str]]

    def read_tags(filething: object) -> TaggedAudio:
        return TaggedAudio({"LYRICS": ["[00:01]line tag", WORD_TTML]})

    audio = tmp_path / "song.flac"
    audio.touch()
    audio.with_suffix(".lrc").write_text("[00:01]line sidecar", encoding="utf-8")
    monkeypatch.setattr(mutagen, "File", read_tags)
    assert load_embedded_lyrics(audio)[0].text == "你好"
    assert load_local_lyrics(audio)[0].has_word_timing
