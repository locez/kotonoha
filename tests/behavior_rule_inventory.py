"""Stable grammar and parser rule registrations for the Phase 0 corpus."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleCoverage:
    """Connect one public rule family to its positive and nearest negative case."""

    rule_id: str
    positive_case_id: str
    negative_variant_index: int = 0


# These IDs describe externally observable rule families. They deliberately do not
# mirror private regex names: a future implementation may split or combine regexes
# without changing the public behavior contract.
GRAMMAR_RULE_COVERAGE: tuple[RuleCoverage, ...] = (
    RuleCoverage("title.platform_noise", "title.platform-credit"),
    RuleCoverage("artist.recovery.separator", "title.platform-credit"),
    RuleCoverage("title.version.trailing_marker", "title.version-suffix"),
    RuleCoverage("artist.recovery.title_pair_guard", "title.title-pair-not-credit"),
    RuleCoverage("lrc.timestamp", "lrc.basic-lines"),
    RuleCoverage("lrc.timed_content", "lrc.basic-lines"),
    RuleCoverage("lrc.offset", "lrc.offset-and-bound"),
    RuleCoverage("lrc.offset.bound", "lrc.offset-and-bound"),
    RuleCoverage("lrc.multiple_tags", "lrc.multiple-tags-and-end"),
    RuleCoverage("lrc.line_end", "lrc.multiple-tags-and-end"),
    RuleCoverage("lrc.max_lines", "lrc.max-lines-reject"),
    RuleCoverage("lrc.rejected_not_truncated", "lrc.max-lines-reject"),
    RuleCoverage("lrc.enhanced_timestamp", "lrc.enhanced-inline-word-timing"),
    RuleCoverage("lrc.enhanced_word_end", "lrc.enhanced-inline-word-timing"),
    RuleCoverage("lrc.enhanced_empty_marker", "lrc.enhanced-inline-word-timing"),
    RuleCoverage("yrc.line_head", "yrc.word-timing"),
    RuleCoverage("yrc.word_span", "yrc.word-timing"),
    RuleCoverage("yrc.metadata_skip", "yrc.word-timing"),
    RuleCoverage("yrc.timestamp_bound", "yrc.timestamp-bound"),
    RuleCoverage("krc.magic", "krc.decoded-word-timing"),
    RuleCoverage("krc.word_span", "krc.decoded-word-timing"),
    RuleCoverage("krc.timestamp_bound", "krc.timestamp-bound"),
    RuleCoverage("krc.decompression_budget", "krc.decompression-budget"),
)


__all__ = ["GRAMMAR_RULE_COVERAGE", "RuleCoverage"]
