"""Public behavior corpus and differential-comparison checks."""

from __future__ import annotations

from dataclasses import dataclass

from behavior_corpus import (
    DISPLAY_CASES,
    ENHANCED_LRC_CASES,
    KRC_BUDGET_CASES,
    KRC_CASES,
    LOOKUP_CASES,
    LRC_BUDGET_CASES,
    LRC_CASES,
    MATCH_CASES,
    TITLE_CASES,
    YRC_CASES,
    DisplayInput,
    DisplayOutput,
    KrcInput,
    LineOutput,
    LookupCase,
    LrcBudgetInput,
    MatchInput,
    MatchOutput,
    TitleInput,
    TitleOutput,
    WordLineOutput,
    WordOutput,
    YrcInput,
    compare_to_baseline,
)
from behavior_rule_inventory import GRAMMAR_RULE_COVERAGE
from behavior_runtime_corpus import (
    CLOCK_CASES,
    GATE_CASES,
    PLATFORM_CASES,
    ClockInput,
    ClockOutput,
    GateInput,
    GateOutput,
    GateSnapshotInput,
    GateTickInput,
    PlatformOperationInput,
    PlatformOperationOutput,
)

from kotonoha.app.source_gate import SourceOwnershipCoordinator
from kotonoha.clock import MediaClock
from kotonoha.display.models import ResolutionState
from kotonoha.display.presentation import DisplayEngine
from kotonoha.lyrics.krc_parser import parse_krc
from kotonoha.lyrics.lrc_parser import parse_lrc
from kotonoha.lyrics.match import best_match
from kotonoha.lyrics.models import LyricLine, LyricsDocument, TimingKind
from kotonoha.lyrics.title_grammar import clean_title, recover_artist, split_title
from kotonoha.lyrics.yrc_parser import parse_yrc
from kotonoha.platform.overlay_contracts import SurfaceResult
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus
from kotonoha.providers.mpris_track import lyrics_lookup_reason


def _title_projection(case: TitleInput) -> TitleOutput:
    _, tags = split_title(case.title, case.artist)
    return TitleOutput(
        clean_title(case.title, case.artist),
        recover_artist(case.title, case.artist),
        tuple(sorted(tags)),
    )


def _lrc_projection(body: str) -> tuple[LineOutput, ...]:
    return tuple(LineOutput(line.start, line.end, line.text) for line in parse_lrc(body))


def _lrc_budget_projection(case: LrcBudgetInput) -> int:
    body = "\n".join(f"[00:00.00]line-{index}" for index in range(case.line_count))
    return len(parse_lrc(body))


def _enhanced_lrc_projection(body: str) -> tuple[WordLineOutput, ...]:
    return _word_line_projection(parse_lrc(body))


def _word_line_projection(lines: list[LyricLine]) -> tuple[WordLineOutput, ...]:
    return tuple(
        WordLineOutput(
            line.start,
            line.end,
            line.text,
            tuple(
                WordOutput(word.start, word.end, word.text)
                for word in line.words
                if word.start is not None and word.end is not None
            ),
        )
        for line in lines
    )


def _yrc_projection(case: YrcInput) -> tuple[WordLineOutput, ...]:
    return _word_line_projection(parse_yrc(case.body))


def _krc_projection(case: KrcInput) -> tuple[WordLineOutput, ...]:
    return _word_line_projection(parse_krc(case.body))


def _match_projection(case: MatchInput) -> MatchOutput:
    evidence = best_match(list(case.candidates), case.track, fuzzy=case.fuzzy)
    if evidence is None:
        return MatchOutput(None, None, None)
    return MatchOutput(evidence.candidate.song_id, evidence.confidence.value, evidence.reason)


def _display_projection(case: DisplayInput) -> DisplayOutput:
    document = LyricsDocument(
        "corpus",
        song_id="corpus-song",
        title="Corpus",
        artist="Tester",
        duration_s=case.duration_s,
        timing=(
            TimingKind.WORD
            if any(line.has_word_timing for line in case.lines)
            else TimingKind.LINE
            if case.lines
            else None
        ),
        lines=tuple(case.lines),
    )
    playback = PlaybackObservation(
        "corpus", "corpus", None, PlaybackStatus.PLAYING, case.position, case.duration_s, 0.0
    )
    frame = DisplayEngine().project_observation(playback, document, ResolutionState.AVAILABLE)
    interlude = None if frame.interlude is None else (frame.interlude.start, frame.interlude.end)
    return DisplayOutput(
        frame.state.value,
        None if frame.current is None else frame.current.text,
        interlude,
        None if frame.line_progress is None else frame.line_progress.fraction,
        None if frame.word_progress is None else frame.word_progress.fractions,
        None if frame.diagnostic is None else frame.diagnostic.code,
    )


def _lookup_projection(case: LookupCase) -> str | None:
    return lyrics_lookup_reason(case.track)


def _gate_projection(case: GateInput) -> GateOutput:
    gate = SourceOwnershipCoordinator()
    track_refs: dict[int | str, str | None] = {}
    for event in case.events:
        if isinstance(event, GateSnapshotInput):
            frame = event.frame
            track = frame.track
            observation = PlaybackObservation(
                "cider",
                str(event.client_id),
                track,
                PlaybackStatus.PLAYING,
                0.0,
                track.duration_s if track is not None else None,
                0.0,
            )
            track_refs[event.client_id] = track.track_ref if track is not None else None
            gate.observe(event.client_id, observation, frame.document)
        elif isinstance(event, GateTickInput):
            gate.observe_clock(
                event.client_id,
                track_refs.get(event.client_id),
                event.current_time,
                event.is_playing,
            )
        else:
            raise TypeError(f"unsupported gate event: {event!r}")

    if case.mode == "external":
        gate.select_external()
    else:
        raise ValueError(f"unsupported gate mode: {case.mode}")

    match = gate.current_match(case.track)
    timing = gate.current_timing(case.track)
    return GateOutput(
        None if match is None else match.client_id,
        None if match is None else match.confidence.value,
        None if timing is None else timing.client_id,
        None if timing is None else timing.current_time,
        gate.accepts(0),
    )


@dataclass
class _FakeMonotonic:
    """Deterministic monotonic source for the clock corpus."""

    value: float = 0.0

    def __call__(self) -> float:
        return self.value


def _clock_projection(case: ClockInput) -> ClockOutput:
    monotonic = _FakeMonotonic()
    clock = MediaClock(monotonic=monotonic)
    for sync in case.syncs:
        monotonic.value += sync.wall_delta
        clock.sync(sync.media_time, sync.playing)
    return ClockOutput(clock.now(), clock.playing)


def _platform_projection(case: PlatformOperationInput) -> PlatformOperationOutput:
    if case.succeeded:
        result = SurfaceResult.applied()
    else:
        if case.reason is None:
            raise ValueError("a failed platform case must have a reason")
        result = SurfaceResult.rejected(case.reason)
    return PlatformOperationOutput(result.succeeded, result.reason)


def test_corpus_cases_have_rule_and_nearest_negative_evidence() -> None:
    all_cases = (
        *TITLE_CASES,
        *LRC_CASES,
        *ENHANCED_LRC_CASES,
        *YRC_CASES,
        *KRC_CASES,
        *KRC_BUDGET_CASES,
        *LRC_BUDGET_CASES,
        *MATCH_CASES,
        *DISPLAY_CASES,
        *LOOKUP_CASES,
        *GATE_CASES,
        *CLOCK_CASES,
        *PLATFORM_CASES,
    )
    assert all(case.case_id and case.source.change and case.rule_ids for case in all_cases)
    assert all(case.negative_variants for case in all_cases)


def test_every_grammar_rule_has_a_public_case_and_nearest_negative() -> None:
    grammar_cases = (
        *TITLE_CASES,
        *LRC_CASES,
        *ENHANCED_LRC_CASES,
        *LRC_BUDGET_CASES,
        *YRC_CASES,
        *KRC_CASES,
        *KRC_BUDGET_CASES,
    )
    cases_by_id = {case.case_id: case for case in grammar_cases}
    registered_rule_ids = {coverage.rule_id for coverage in GRAMMAR_RULE_COVERAGE}
    corpus_rule_ids = {rule_id for case in grammar_cases for rule_id in case.rule_ids}

    assert len(cases_by_id) == len(grammar_cases)
    assert registered_rule_ids == corpus_rule_ids
    for coverage in GRAMMAR_RULE_COVERAGE:
        case = cases_by_id[coverage.positive_case_id]
        assert coverage.rule_id in case.rule_ids
        assert 0 <= coverage.negative_variant_index < len(case.negative_variants)


def test_title_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(TITLE_CASES, _title_projection) == ()


def test_lrc_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(LRC_CASES, lambda case: _lrc_projection(case.body)) == ()


def test_enhanced_lrc_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(ENHANCED_LRC_CASES, lambda case: _enhanced_lrc_projection(case.body)) == ()


def test_lrc_budget_corpus_freezes_the_current_truncation_baseline() -> None:
    assert compare_to_baseline(LRC_BUDGET_CASES, _lrc_budget_projection) == ()


def test_yrc_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(YRC_CASES, _yrc_projection) == ()


def test_krc_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(KRC_CASES, _krc_projection) == ()


def test_match_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(MATCH_CASES, _match_projection) == ()


def test_display_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(DISPLAY_CASES, _display_projection) == ()


def test_lookup_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(LOOKUP_CASES, _lookup_projection) == ()


def test_gate_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(GATE_CASES, _gate_projection) == ()


def test_clock_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(CLOCK_CASES, _clock_projection) == ()


def test_platform_corpus_matches_the_current_public_oracle() -> None:
    assert compare_to_baseline(PLATFORM_CASES, _platform_projection) == ()


def test_nearest_negative_cases_do_not_repeat_the_positive_public_result() -> None:
    for case in TITLE_CASES:
        assert all(_title_projection(negative) != case.expected for negative in case.negative_variants)
    for case in LRC_CASES:
        assert all(_lrc_projection(negative.body) != case.expected for negative in case.negative_variants)
    for case in ENHANCED_LRC_CASES:
        assert all(_enhanced_lrc_projection(negative.body) != case.expected for negative in case.negative_variants)
    for case in LRC_BUDGET_CASES:
        assert all(_lrc_budget_projection(negative) != case.expected for negative in case.negative_variants)
    for case in YRC_CASES:
        assert all(_yrc_projection(negative) != case.expected for negative in case.negative_variants)
    for case in KRC_CASES:
        assert all(_krc_projection(negative) != case.expected for negative in case.negative_variants)
    for case in KRC_BUDGET_CASES:
        assert all(_krc_projection(negative) != case.expected for negative in case.negative_variants)
    for case in MATCH_CASES:
        assert all(_match_projection(negative) != case.expected for negative in case.negative_variants)
    for case in DISPLAY_CASES:
        assert all(_display_projection(negative) != case.expected for negative in case.negative_variants)
    for case in LOOKUP_CASES:
        assert all(_lookup_projection(negative) != case.expected for negative in case.negative_variants)
    for case in GATE_CASES:
        assert all(_gate_projection(negative) != case.expected for negative in case.negative_variants)
    for case in CLOCK_CASES:
        assert all(_clock_projection(negative) != case.expected for negative in case.negative_variants)
    for case in PLATFORM_CASES:
        assert all(_platform_projection(negative) != case.expected for negative in case.negative_variants)


def test_comparator_reports_a_public_difference_without_inspecting_implementation() -> None:
    first = TITLE_CASES[0]

    def changed_title(case: TitleInput) -> TitleOutput:
        output = _title_projection(case)
        if case == first.input:
            return TitleOutput(output.clean_title, "wrong artist", output.version_tags)
        return output

    differences = compare_to_baseline(TITLE_CASES, changed_title)
    assert len(differences) == 1
    assert differences[0].case_id == first.case_id
    assert differences[0].expected == first.expected
    assert differences[0].actual == TitleOutput("SWIM", "wrong artist", ())
