"""Provider-neutral manual lyric search contracts and service."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .artifact import LyricsArtifact
from .http import LyricsHttpError, LyricsSession
from .match import MatchConfidence, TrackMetadata
from .search_policy import MANUAL_SEARCH_RESULTS_TOTAL

logger = logging.getLogger(__name__)

_UNCONFIGURED_SOURCE_REASON_KEY = "search.unavailable.unconfigured"


class LyricsSearchError(RuntimeError):
    """A manual search cannot run because its owned search service is unavailable.

    The message is a `strings` catalogue key, not a sentence: the dialog reporting
    it is localized and a phrase written here would arrive in the wrong language.
    """

    def __init__(self, reason_key: str) -> None:
        super().__init__(reason_key)
        self.reason_key = reason_key


SearchArtifacts = Callable[
    [LyricsSession, TrackMetadata], Awaitable[tuple[LyricsArtifact, ...]]
]
SessionFactory = Callable[[], LyricsSession]


@dataclass(frozen=True, slots=True)
class LyricsSearchProvider:
    """Declare whether a configured source supports metadata-based search."""

    search: SearchArtifacts | None
    # A `strings` catalogue key, not a sentence: the dialog resolves it in the
    # user's language, so a provider must not phrase its own explanation.
    unavailable_reason_key: str = ""

    def __post_init__(self) -> None:
        """Require a translated explanation when a source has no manual-search capability."""
        if self.search is None and not self.unavailable_reason_key.strip():
            raise ValueError("an unsupported lyric search provider requires a reason key")


@dataclass(frozen=True, slots=True)
class LyricsSearchQuery:
    """Editable search fields plus immutable playback duration context."""

    title: str
    artist: str
    album: str = ""
    duration_s: float | None = None

    def __post_init__(self) -> None:
        """Validate the typed query before it reaches a provider boundary."""
        if not all(isinstance(value, str) for value in (self.title, self.artist, self.album)):
            raise TypeError("lyrics search fields must be strings")
        if self.duration_s is not None and (
            not isinstance(self.duration_s, (int, float))
            or isinstance(self.duration_s, bool)
            or not math.isfinite(float(self.duration_s))
            or self.duration_s < 0.0
        ):
            raise ValueError("lyrics search duration must be a finite non-negative number")

    def track_metadata(self) -> TrackMetadata:
        """Return the provider-facing track metadata represented by this query."""
        return TrackMetadata(
            title=self.title.strip(),
            artist=self.artist.strip(),
            album=self.album.strip(),
            duration_s=float(self.duration_s) if self.duration_s is not None else None,
        )


# The encodings this module produces, grouped by how finely each times its text.
# The vocabulary belongs beside the adapters that write it: a reader elsewhere
# spelling one of these out again cannot be told when a new format arrives.
_WORD_TIMED = frozenset({"yrc", "krc"})
_LINE_TIMED = frozenset({"lrc"})


class LyricsTiming(Enum):
    """How finely one lyric encoding times its text."""

    WORD = "word"
    LINE = "line"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class LyricsVersion:
    """Describe the lyric encoding and optional translation tracks of one result."""

    format_id: str
    has_translation: bool = False
    # Supplied when content was parsed: formats such as TTML and Enhanced LRC
    # do not imply a fixed timing granularity from their extension alone.
    content_timing: LyricsTiming | None = None

    def __post_init__(self) -> None:
        """Reject empty display metadata from an external provider adapter."""
        if not self.format_id:
            raise ValueError("lyrics version requires a format id")

    @property
    def timing(self) -> LyricsTiming:
        """Say how finely this encoding times its text.

        The difference a listener feels is word, line, or neither; which encoding
        carries it is this module's business, not a reader's.
        """
        if self.content_timing is not None:
            return self.content_timing
        if self.format_id in _WORD_TIMED:
            return LyricsTiming.WORD
        if self.format_id in _LINE_TIMED:
            return LyricsTiming.LINE
        return LyricsTiming.NONE


@dataclass(frozen=True, slots=True)
class LyricsSearchResult:
    """One selectable lyric artifact and its user-facing version facts."""

    artifact: LyricsArtifact
    version: LyricsVersion

    @classmethod
    def from_artifact(cls, artifact: LyricsArtifact) -> LyricsSearchResult:
        """Build a selection result from a validated provider artifact."""
        return cls(artifact, _version_for(artifact))

    @property
    def source_key(self) -> str:
        """Return the stable provider-scoped identity used by the selection UI."""
        return f"{self.artifact.provider}:{self.artifact.provider_song_id}"

    @property
    def confidence(self) -> MatchConfidence:
        """Return the match confidence calculated by the provider adapter."""
        return self.artifact.confidence


@dataclass(frozen=True, slots=True)
class LyricsSearchUnavailable:
    """Explain why one requested source could not answer a manual search."""

    source: str
    # A `strings` catalogue key; see LyricsSearchProvider.unavailable_reason_key.
    reason_key: str

    def __post_init__(self) -> None:
        """Reject unavailable-source details that the UI cannot meaningfully show."""
        if not self.source.strip():
            raise ValueError("unavailable lyric search source must not be empty")
        if not self.reason_key.strip():
            raise ValueError("unavailable lyric search reason key must not be empty")


@dataclass(frozen=True, slots=True)
class LyricsSearchResponse:
    """Search results plus typed explanations for sources that could not answer."""

    results: tuple[LyricsSearchResult, ...]
    unavailable_sources: tuple[LyricsSearchUnavailable, ...] = ()


class LyricsSearchPort(Protocol):
    """Lifecycle and query capability owned by the manual-search application flow."""

    async def start(self) -> None:
        """Create the search service's HTTP session."""
        ...

    async def stop(self) -> None:
        """Close the search service's HTTP session."""
        ...

    async def search(
        self,
        query: LyricsSearchQuery,
        sources: Sequence[str],
    ) -> LyricsSearchResponse:
        """Search the selected provider slots and return all usable candidates."""
        ...


class LyricsSearchService:
    """Search configured lyric providers through one independently owned session."""

    def __init__(
        self,
        providers: Mapping[str, SearchArtifacts | LyricsSearchProvider],
        session_factory: SessionFactory,
    ) -> None:
        """Create a service without opening a network session or performing I/O."""
        self._providers: dict[str, LyricsSearchProvider] = {
            source: provider
            if isinstance(provider, LyricsSearchProvider)
            else LyricsSearchProvider(provider)
            for source, provider in providers.items()
        }
        self._session_factory = session_factory
        self._session: LyricsSession | None = None

    async def start(self) -> None:
        """Create the reusable provider session; repeated calls are harmless."""
        if self._session is None:
            self._session = self._session_factory()

    async def stop(self) -> None:
        """Close the owned provider session and leave the service restartable."""
        session = self._session
        self._session = None
        if session is not None:
            await session.close()

    async def search(
        self,
        query: LyricsSearchQuery,
        sources: Sequence[str],
    ) -> LyricsSearchResponse:
        """Query each known source concurrently while preserving source order."""
        session = self._session
        if session is None:
            raise LyricsSearchError("search.error.not_started")
        track = query.track_metadata()
        if not track.title and not track.artist:
            raise LyricsSearchError("search.error.no_query")

        requested = tuple(dict.fromkeys(source for source in sources if source))
        selected = tuple(source for source in requested if source in self._providers)
        if not selected:
            return LyricsSearchResponse(
                (),
                tuple(LyricsSearchUnavailable(source, _UNCONFIGURED_SOURCE_REASON_KEY) for source in requested),
            )
        responses = await asyncio.gather(
            *(self._search_source(source, self._providers[source], session, track) for source in selected)
        )
        results: list[LyricsSearchResult] = []
        unavailable_by_source: dict[str, LyricsSearchUnavailable] = {
            source: unavailable
            for source, _source_results, unavailable in responses
            if unavailable is not None
        }
        seen: set[str] = set()
        for _source, source_results, _unavailable in responses:
            for result in source_results:
                if result.source_key not in seen:
                    seen.add(result.source_key)
                    results.append(result)
        unavailable = tuple(
            unavailable_by_source[source]
            if source in unavailable_by_source
            else LyricsSearchUnavailable(source, _UNCONFIGURED_SOURCE_REASON_KEY)
            for source in requested
            if source not in self._providers or source in unavailable_by_source
        )
        return LyricsSearchResponse(tuple(results[:MANUAL_SEARCH_RESULTS_TOTAL]), unavailable)

    async def _search_source(
        self,
        source: str,
        provider: LyricsSearchProvider,
        session: LyricsSession,
        track: TrackMetadata,
    ) -> tuple[str, tuple[LyricsSearchResult, ...], LyricsSearchUnavailable | None]:
        """Isolate one provider failure so other configured sources still answer."""
        search = provider.search
        if search is None:
            logger.info("Manual lyric search is unavailable for %s: %s", source, provider.unavailable_reason_key)
            return source, (), LyricsSearchUnavailable(source, provider.unavailable_reason_key)
        try:
            artifacts = await search(session, track)
        except TimeoutError as exc:
            logger.warning("Manual lyric search failed for %s: %s", source, exc)
            return source, (), LyricsSearchUnavailable(source, "search.unavailable.timeout")
        except (LyricsHttpError, OSError) as exc:
            logger.warning("Manual lyric search failed for %s: %s", source, exc)
            return source, (), LyricsSearchUnavailable(source, "search.unavailable.failed")
        except ValueError as exc:
            logger.warning("Manual lyric search failed for %s: %s", source, exc)
            return source, (), LyricsSearchUnavailable(source, "search.unavailable.invalid")
        return source, tuple(LyricsSearchResult.from_artifact(artifact) for artifact in artifacts), None


def _version_for(artifact: LyricsArtifact) -> LyricsVersion:
    """Derive stable version facts from provider payloads at the lyric boundary."""
    payload = artifact.payload
    if artifact.provider == "amll":
        timing = LyricsTiming.WORD if any(line.has_word_timing for line in artifact.lines) else LyricsTiming.LINE
        return LyricsVersion("ttml", any(line.translation for line in artifact.lines), timing)
    if artifact.provider == "netease":
        format_id = "yrc" if payload.get("yrc", "").strip() else "lrc"
        return LyricsVersion(format_id, bool(payload.get("tlyric", "").strip()))
    if artifact.provider == "kugou":
        return LyricsVersion("krc" if payload.get("krc", "").strip() else "lrc")
    if artifact.provider == "lrclib":
        return LyricsVersion("lrc")
    return LyricsVersion("lyrics")


__all__ = [
    "LyricsSearchError",
    "LyricsTiming",
    "LyricsSearchPort",
    "LyricsSearchProvider",
    "LyricsSearchQuery",
    "LyricsSearchResponse",
    "LyricsSearchResult",
    "LyricsSearchUnavailable",
    "LyricsSearchService",
    "LyricsVersion",
    "SearchArtifacts",
]
