"""An unusable AMLL revision must not hide another usable submission."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest
from test_lyrics_amll import NEW_FILE, OLD_FILE, TRACK, WORDS, Session, row
from test_lyrics_resolver import FakeGate, artifact, catalog_for

from kotonoha.async_worker import BlockingCallRunner
from kotonoha.lyrics import netease
from kotonoha.lyrics.amll import AmllLyricsSource
from kotonoha.lyrics.cache import LyricsCache, LyricsCacheQuery
from kotonoha.lyrics.hint import LyricsHint
from kotonoha.lyrics.http import LyricsSession
from kotonoha.lyrics.match import TrackMetadata
from kotonoha.lyrics.models import LyricsCacheState
from kotonoha.lyrics.network_sources import NetworkLyricsSource
from kotonoha.lyrics.resolver import LyricsResolver


@dataclass(frozen=True)
class RevisionCase:
    """The latest catalog entry may exist while its lyrics are unusable."""

    name: str
    latest: bytes | None


REVISION_CASES = (
    RevisionCase("missing", None),
    RevisionCase("unsupported", b'<!DOCTYPE tt><tt/>'),
)


@pytest.mark.parametrize("case", REVISION_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("route", ["automatic", "manual", "exact"])
async def test_unusable_latest_revision_keeps_a_usable_older_submission(
    case: RevisionCase, route: Literal["automatic", "manual", "exact"],
) -> None:
    """All lookup routes can recover words while exposing one result per song."""
    source = AmllLyricsSource(worker=BlockingCallRunner("test-amll-revisions"))
    files = {OLD_FILE: WORDS.encode()}
    if case.latest is not None:
        files[NEW_FILE] = case.latest
    session = Session(row(OLD_FILE) + row(), files)
    try:
        if route == "manual":
            results = await source.search_artifacts(session, TRACK)
            assert len(results) == 1
            assert results[0].provider_song_id == OLD_FILE
            assert any(line.has_word_timing for line in results[0].lines)
        else:
            result = (
                await source.resolve(session, TRACK, fuzzy=False)
                if route == "automatic"
                else await source.resolve_exact(session, TRACK, LyricsHint("netease", "42"))
            )
            assert result is not None
            assert result.document.song_id == OLD_FILE
            assert result.document.has_word_timing

        # A working newer revision still wins and manual results remain unique.
        repaired = Session(row(OLD_FILE) + row(), {OLD_FILE: WORDS.encode(), NEW_FILE: WORDS.encode()})
        choices = await source.search_artifacts(repaired, TRACK)
        assert [choice.provider_song_id for choice in choices] == [NEW_FILE]
        exact = await source.resolve_exact(repaired, TRACK, LyricsHint("netease", "42"))
        assert exact is not None and exact.document.song_id == NEW_FILE
    finally:
        source.close()


async def test_amll_revision_words_beat_cached_lines_without_cider(tmp_path: Path) -> None:
    """A line cache is a candidate; recovered AMLL words are selected and reusable."""
    async def cached_provider_fetch(
        session: LyricsSession, track: TrackMetadata, *, fuzzy: bool,
    ) -> None:
        raise AssertionError("the cached provider should not need another fetch")

    amll = AmllLyricsSource(worker=BlockingCallRunner("test-amll-revision-cache"))
    cache = LyricsCache(tmp_path / "lyrics.sqlite3", worker=BlockingCallRunner("test-revision-cache"))
    resolver = LyricsResolver(
        catalog=catalog_for({
            "amll": amll,
            "netease": NetworkLyricsSource("netease", cached_provider_fetch, netease.parse_payload),
        }, FakeGate([])), cache=cache,
    )
    session = Session(row(OLD_FILE) + row(), {OLD_FILE: WORDS.encode(), NEW_FILE: b'<!DOCTYPE tt><tt/>'})
    try:
        await cache.store(artifact())
        result = await resolver.resolve(session, TRACK, ["amll", "netease", "cider"])
        assert result is not None and result.source_id == "amll"
        assert result.document.has_word_timing
        assert {entry.key.provider for entry in await cache.search(LyricsCacheQuery())} == {"amll", "netease"}

        offline = await resolver.resolve(None, TRACK, ["amll", "netease", "cider"])
        assert offline is not None and offline.source_id == "amll"
        assert offline.document.has_word_timing
        assert offline.document.cache_state is LyricsCacheState.FROM_CACHE
    finally:
        await resolver.close()
        amll.close()
