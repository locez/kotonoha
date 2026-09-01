"""Typed lyric behavior cases and canonical comparison helpers.

The cases in this module are migration evidence for lyrics, matching, and display.
Runtime coordination cases live in :mod:`behavior_runtime_corpus`. Their expected
values are frozen public projections, so a future implementation can run against
the same inputs without depending on private regex groups, task identities, or Qt
objects.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from kotonoha.lyrics.krc_parser import KRC_MAGIC, KRC_XOR_KEY
from kotonoha.lyrics.match import Candidate, MatchConfidence, TrackMetadata
from kotonoha.lyrics.models import LyricLine, LyricWord
from kotonoha.lyrics.payload import MAX_DECOMPRESSED_BYTES
from kotonoha.providers.mpris_track import TrackInfo

TInput = TypeVar("TInput")
TPublicOutput = TypeVar("TPublicOutput")


@dataclass(frozen=True)
class RegressionSource:
    """Identify the historical behavior evidence behind one case."""

    change: str
    note: str


@dataclass(frozen=True)
class BehaviorCase(Generic[TInput, TPublicOutput]):
    """A public input, frozen result, and nearest negative inputs."""

    case_id: str
    input: TInput
    expected: TPublicOutput
    negative_variants: tuple[TInput, ...]
    source: RegressionSource
    rule_ids: tuple[str, ...]


@dataclass(frozen=True)
class BehaviorDifference(Generic[TPublicOutput]):
    """One public-result difference between a baseline and a candidate."""

    case_id: str
    expected: TPublicOutput
    actual: TPublicOutput


def compare_to_baseline(
    cases: tuple[BehaviorCase[TInput, TPublicOutput], ...],
    candidate: Callable[[TInput], TPublicOutput],
) -> tuple[BehaviorDifference[TPublicOutput], ...]:
    """Compare a candidate publisher with the frozen public case results."""
    differences: list[BehaviorDifference[TPublicOutput]] = []
    for case in cases:
        actual = candidate(case.input)
        if actual != case.expected:
            differences.append(BehaviorDifference(case.case_id, case.expected, actual))
    return tuple(differences)


@dataclass(frozen=True)
class TitleInput:
    """Raw title and artist as reported by a player."""

    title: str
    artist: str


@dataclass(frozen=True)
class TitleOutput:
    """Stable title grammar projection used by matching and gate policy."""

    clean_title: str
    recovered_artist: str
    version_tags: tuple[str, ...]


TITLE_CASES: tuple[BehaviorCase[TitleInput, TitleOutput], ...] = (
    BehaviorCase(
        case_id="title.platform-credit",
        input=TitleInput("BTS (방탄소년단) ‘SWIM’ Official MV", "HYBE LABELS"),
        expected=TitleOutput("SWIM", "BTS", ()),
        negative_variants=(TitleInput("BTS SWIM Official MV", "HYBE LABELS"),),
        source=RegressionSource("#26/#42", "raw title credit must remain available to recovery and gate"),
        rule_ids=("title.platform_noise", "artist.recovery.separator"),
    ),
    BehaviorCase(
        case_id="title.version-suffix",
        input=TitleInput("Song (Live)", "Artist"),
        expected=TitleOutput("Song (Live)", "Artist", ("live",)),
        negative_variants=(TitleInput("Live and Learn", "Artist"),),
        source=RegressionSource("#51", "a marker only at the title end is a version qualifier"),
        rule_ids=("title.version.trailing_marker",),
    ),
    BehaviorCase(
        case_id="title.title-pair-not-credit",
        input=TitleInput("螺旋 - RASEN", "9Lana"),
        expected=TitleOutput("螺旋 - RASEN", "9Lana", ()),
        negative_variants=(TitleInput("陳一發兒 - 童話鎮", "BELLA PING MUSIC CHANNEL"),),
        source=RegressionSource("#26", "a bilingual title pair must not be mistaken for a leading credit"),
        rule_ids=("artist.recovery.title_pair_guard",),
    ),
)


@dataclass(frozen=True)
class LrcInput:
    """An LRC body crossing the parser boundary."""

    body: str


@dataclass(frozen=True)
class LineOutput:
    """Canonical line projection independent of LyricLine identity fields."""

    start: float
    end: float
    text: str


LRC_CASES: tuple[BehaviorCase[LrcInput, tuple[LineOutput, ...]], ...] = (
    BehaviorCase(
        case_id="lrc.basic-lines",
        input=LrcInput("[00:01.00]hello\n[00:05.00]bye"),
        expected=(LineOutput(1.0, 5.0, "hello"), LineOutput(5.0, 10.0, "bye")),
        negative_variants=(LrcInput("hello\n[00:01.00]"),),
        source=RegressionSource("#34/#62", "timed lines are displayable; untimed text is not"),
        rule_ids=("lrc.timestamp", "lrc.timed_content"),
    ),
    BehaviorCase(
        case_id="lrc.offset-and-bound",
        input=LrcInput("[offset:+500]\n[00:01.00]shifted"),
        expected=(LineOutput(0.5, 5.5, "shifted"),),
        negative_variants=(LrcInput("[offset:+999999]\n[00:01.00]unchanged"),),
        source=RegressionSource("#34/#49", "bounded offset is applied while an absurd offset is ignored"),
        rule_ids=("lrc.offset", "lrc.offset.bound"),
    ),
    BehaviorCase(
        case_id="lrc.multiple-tags-and-end",
        input=LrcInput("[00:01.00][00:05.00]repeat"),
        expected=(LineOutput(1.0, 5.0, "repeat"), LineOutput(5.0, 10.0, "repeat")),
        negative_variants=(LrcInput("[00:01.00]"),),
        source=RegressionSource(
            "#34/#56", "one content line can have several timestamps and the final line gets a bounded end"
        ),
        rule_ids=("lrc.multiple_tags", "lrc.line_end"),
    ),
)


@dataclass(frozen=True)
class LrcBudgetInput:
    """A fixed-size LRC input used to freeze the current budget boundary."""

    line_count: int


LRC_BUDGET_CASES: tuple[BehaviorCase[LrcBudgetInput, int], ...] = (
    BehaviorCase(
        case_id="lrc.max-lines-reject",
        input=LrcBudgetInput(5001),
        expected=5000,
        negative_variants=(LrcBudgetInput(4999),),
        source=RegressionSource("#62", "the current implementation returns a prefix at the line budget"),
        rule_ids=("lrc.max_lines", "lrc.rejected_not_truncated"),
    ),
)


@dataclass(frozen=True)
class WordOutput:
    """Canonical word timing independent of parser object identity."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class WordLineOutput:
    """Canonical line and word timing exposed by word-timed parsers."""

    start: float
    end: float
    text: str
    words: tuple[WordOutput, ...]


ENHANCED_LRC_CASES: tuple[BehaviorCase[LrcInput, tuple[WordLineOutput, ...]], ...] = (
    BehaviorCase(
        case_id="lrc.enhanced-inline-word-timing",
        input=LrcInput(
            "[00:00.000]<00:00.000>堕<00:00.155><00:00.156> - <00:00.311>Zyboy"
            "<00:00.466><00:00.467>忠<00:00.622>\n"
            "[00:01.000]next"
        ),
        expected=(
            WordLineOutput(
                0.0,
                1.0,
                "堕 - Zyboy忠",
                (
                    WordOutput(0.0, 0.155, "堕"),
                    WordOutput(0.156, 0.311, " - "),
                    WordOutput(0.311, 0.466, "Zyboy"),
                    WordOutput(0.467, 0.622, "忠"),
                ),
            ),
            WordLineOutput(1.0, 6.0, "next", ()),
        ),
        negative_variants=(
            LrcInput("[00:00.000]堕 - Zyboy忠\n[00:01.000]next"),
        ),
        source=RegressionSource(
            "#72", "inline angle timestamps become word spans while ordinary LRC remains line-timed"
        ),
        rule_ids=("lrc.enhanced_timestamp", "lrc.enhanced_word_end", "lrc.enhanced_empty_marker"),
    ),
)


@dataclass(frozen=True)
class YrcInput:
    """A YRC text body crossing the parser boundary."""

    body: str


def _encode_krc(text: str) -> bytes:
    """Build a valid KRC fixture from its format-level decoded text."""
    compressed = zlib.compress(text.encode("utf-8"))
    encrypted = bytes(value ^ KRC_XOR_KEY[index % len(KRC_XOR_KEY)] for index, value in enumerate(compressed))
    return KRC_MAGIC + encrypted


@dataclass(frozen=True)
class KrcInput:
    """A KRC byte body crossing the parser boundary."""

    body: bytes


YRC_CASES: tuple[BehaviorCase[YrcInput, tuple[WordLineOutput, ...]], ...] = (
    BehaviorCase(
        case_id="yrc.word-timing",
        input=YrcInput(
            '{"t":0,"c":[{"tx":"作词: "}]}\n'
            "[1300,1950](1300,243,0)眉(1543,243,0)目(1786,243,0)里\n"
        ),
        expected=(
            WordLineOutput(
                1.3,
                3.25,
                "眉目里",
                (
                    WordOutput(1.3, 1.543, "眉"),
                    WordOutput(1.543, 1.786, "目"),
                    WordOutput(1.786, 2.029, "里"),
                ),
            ),
        ),
        negative_variants=(YrcInput('{"t":0,"c":[{"tx":"metadata"}]}\n'),),
        source=RegressionSource("#40/#56", "YRC word spans are absolute and metadata lines are not lyric content"),
        rule_ids=("yrc.line_head", "yrc.word_span", "yrc.metadata_skip"),
    ),
    BehaviorCase(
        case_id="yrc.timestamp-bound",
        input=YrcInput(
            "[" + "9" * 400 + ",1950](1300,243,0)skip\n"
            "[1300,1950](1300,243,0)眉(1543,243,0)目\n"
        ),
        expected=(
            WordLineOutput(
                1.3,
                3.25,
                "眉目",
                (WordOutput(1.3, 1.543, "眉"), WordOutput(1.543, 1.786, "目")),
            ),
        ),
        negative_variants=(YrcInput("[1300,1950]not word timed"),),
        source=RegressionSource("#56", "an absurd provider timestamp skips only its own line"),
        rule_ids=("yrc.timestamp_bound",),
    ),
)


KRC_CASES: tuple[BehaviorCase[KrcInput, tuple[WordLineOutput, ...]], ...] = (
    BehaviorCase(
        case_id="krc.decoded-word-timing",
        input=KrcInput(_encode_krc("[1200,1000]<0,300,0>先<300,400,0>唱<700,300,0>歌\n")),
        expected=(
            WordLineOutput(
                1.2,
                2.2,
                "先唱歌",
                (
                    WordOutput(1.2, 1.5, "先"),
                    WordOutput(1.5, 1.9, "唱"),
                    WordOutput(1.9, 2.2, "歌"),
                ),
            ),
        ),
        negative_variants=(KrcInput(b"not krc"),),
        source=RegressionSource(
            "#40/#49/#56", "KRC decoding preserves absolute word spans and rejects malformed bodies"
        ),
        rule_ids=("krc.magic", "krc.word_span"),
    ),
    BehaviorCase(
        case_id="krc.timestamp-bound",
        input=KrcInput(
            _encode_krc("[" + "9" * 400 + ",1000]<0,500,0>skip\n[1000,2000]<0,500,0>real\n")
        ),
        expected=(
            WordLineOutput(
                1.0,
                3.0,
                "real",
                (WordOutput(1.0, 1.5, "real"),),
            ),
        ),
        negative_variants=(KrcInput(b"not krc"),),
        source=RegressionSource("#56", "an absurd provider timestamp skips only its own line"),
        rule_ids=("krc.timestamp_bound",),
    ),
)


KRC_BUDGET_CASES: tuple[BehaviorCase[KrcInput, tuple[WordLineOutput, ...]], ...] = (
    BehaviorCase(
        case_id="krc.decompression-budget",
        input=KrcInput(
            _encode_krc("[0,1000]<0,500,0>hello\n" + "A" * (MAX_DECOMPRESSED_BYTES + 1024))
        ),
        expected=(),
        negative_variants=(KrcInput(_encode_krc("[0,1000]<0,500,0>hello\n")),),
        source=RegressionSource("#49/#56", "a compressed body over the expansion budget is rejected before parsing"),
        rule_ids=("krc.decompression_budget",),
    ),
)


@dataclass(frozen=True)
class MatchInput:
    """Track and candidate list passed to the public matcher."""

    track: TrackMetadata
    candidates: tuple[Candidate, ...]
    fuzzy: bool = False


@dataclass(frozen=True)
class MatchOutput:
    """Canonical winner projection used by source workflow policy."""

    song_id: str | None
    confidence: str | None
    reason: str | None


MATCH_CASES: tuple[BehaviorCase[MatchInput, MatchOutput], ...] = (
    BehaviorCase(
        case_id="match.exact-identity",
        input=MatchInput(
            TrackMetadata("Hello", "Artist", "Album", 180.0),
            (Candidate("song-1", "Hello", "Artist", 180.0, "Album"),),
        ),
        expected=MatchOutput("song-1", MatchConfidence.HIGH.value, "title+artist identity"),
        negative_variants=(
            MatchInput(
                TrackMetadata("Hello", "Artist", "Album", 180.0),
                (Candidate("song-live", "Hello (Live)", "Artist", 180.0, "Album"),),
            ),
        ),
        source=RegressionSource("#33/#51", "identity wins while a recording/version conflict is rejected"),
        rule_ids=("match.version_conflict", "match.artist_identity", "match.high_confidence"),
    ),
)


@dataclass(frozen=True)
class DisplayInput:
    """Line timing and playback position passed to the timeline selector."""

    lines: tuple[LyricLine, ...]
    position: float
    duration_s: float | None = None


@dataclass(frozen=True)
class DisplayOutput:
    """Canonical frame facts needed by a renderer."""

    state: str
    current_text: str | None
    interlude: tuple[float, float] | None
    line_progress: float | None
    word_progress: tuple[float, ...] | None
    diagnostic: str | None


DISPLAY_CASES: tuple[BehaviorCase[DisplayInput, DisplayOutput], ...] = (
    BehaviorCase(
        case_id="display.active-line",
        input=DisplayInput(
            (LyricLine(0, "L0", 0.0, 5.0, "hello", ""), LyricLine(1, "L1", 5.0, 10.0, "bye", "")),
            2.0,
        ),
        expected=DisplayOutput("LyricsAvailable", "hello", None, 0.4, None, None),
        negative_variants=(DisplayInput((), 2.0),),
        source=RegressionSource("#64", "a resolved document exposes the active line; an empty document is not active"),
        rule_ids=("display.current_line", "display.not_found"),
    ),
    BehaviorCase(
        case_id="display.interlude",
        input=DisplayInput(
            (
                LyricLine(0, "L0", 0.0, 5.0, "one", ""),
                LyricLine(1, "L1", 5.0, 10.0, "two", ""),
                LyricLine(2, "L2", 10.0, 15.0, "three", ""),
                LyricLine(3, "L3", 40.0, 45.0, "four", ""),
            ),
            20.0,
        ),
        expected=DisplayOutput("LyricsAvailable", None, (15.0, 40.0), 0.2, None, None),
        negative_variants=(
            DisplayInput(
                (LyricLine(0, "L0", 0.0, 5.0, "one", ""), LyricLine(1, "L1", 5.0, 10.0, "two", "")),
                7.0,
            ),
        ),
        source=RegressionSource(
            "#64", "a meaningful instrumental gap clears the active line without losing the document"
        ),
        rule_ids=("display.interlude",),
    ),
    BehaviorCase(
        case_id="display.word-progress",
        input=DisplayInput(
            (
                LyricLine(
                    0,
                    "L0",
                    0.0,
                    5.0,
                    "你好",
                    "",
                    (LyricWord(0.0, 1.0, "你"), LyricWord(1.0, 2.0, "好")),
                ),
            ),
            1.5,
        ),
        expected=DisplayOutput("LyricsAvailable", "你好", None, 0.75, (1.0, 0.5), None),
        negative_variants=(DisplayInput((), 1.5),),
        source=RegressionSource("#58/#64", "word timing is carried as semantic progress instead of UI-owned time math"),
        rule_ids=("display.word_progress", "display.canonical_line"),
    ),
)


@dataclass(frozen=True)
class LookupCase:
    """Player track input used by the non-song lookup gate."""

    track: TrackInfo


LOOKUP_CASES: tuple[BehaviorCase[LookupCase, str | None], ...] = (
    BehaviorCase(
        case_id="lookup.non-song-marker",
        input=LookupCase(TrackInfo("Mix", "Artist", "", 3600.0, "/mix", "一小时 mix")),
        expected="title contains non-song marker '一小时'",
        negative_variants=(LookupCase(TrackInfo("Song", "Artist", "", 180.0, "/song")),),
        source=RegressionSource("#42/#64", "the gate reads reported title and rejects non-song uploads"),
        rule_ids=("lookup.raw_title", "lookup.non_song_marker"),
    ),
)


__all__ = [
    "BehaviorCase",
    "BehaviorDifference",
    "KRC_BUDGET_CASES",
    "KRC_CASES",
    "KrcInput",
    "DisplayInput",
    "DisplayOutput",
    "DISPLAY_CASES",
    "LrcInput",
    "LrcBudgetInput",
    "LRC_BUDGET_CASES",
    "LRC_CASES",
    "LineOutput",
    "LookupCase",
    "LOOKUP_CASES",
    "MatchInput",
    "MatchOutput",
    "MATCH_CASES",
    "RegressionSource",
    "WordLineOutput",
    "WordOutput",
    "YRC_CASES",
    "YrcInput",
    "TitleInput",
    "TitleOutput",
    "TITLE_CASES",
    "compare_to_baseline",
]
