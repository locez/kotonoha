"""Presentation facts produced from canonical playback and lyric documents."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from ..lyrics.models import LyricLine, LyricsCacheState, LyricsDocument, LyricsOrigin
from ..playback.models import PlaybackObservation, TrackIdentity
from .offsets import TrackOffsetKey


class DisplayState(StrEnum):
    """The externally meaningful lyric resolution states."""

    NO_TRACK = "NoTrack"
    RESOLVING = "Resolving"
    LYRICS_AVAILABLE = "LyricsAvailable"
    LYRICS_NOT_FOUND = "LyricsNotFound"


class ResolutionState(StrEnum):
    """Resolution facts supplied by an application source before projection."""

    NO_TRACK = "NoTrack"
    RESOLVING = "Resolving"
    AVAILABLE = "LyricsAvailable"
    NOT_FOUND = "LyricsNotFound"

    def display_state(self) -> DisplayState:
        """Return the renderer-facing state represented by this resolution fact."""
        return DisplayState(self.value)

    @classmethod
    def from_facts(
        cls,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
    ) -> ResolutionState:
        """Derive the ordinary source state for a completed snapshot."""
        if document is not None and document.lines:
            return cls.AVAILABLE
        if playback.track is None:
            return cls.NO_TRACK
        return cls.NOT_FOUND


@dataclass(frozen=True)
class LyricsDisplayStatus:
    """Source facts for the lyric document currently visible in the overlay."""

    playback_source: str | None = None
    lyrics_source_id: str | None = None
    lyrics_source_name: str | None = None
    origin: LyricsOrigin | None = None
    cache_state: LyricsCacheState = LyricsCacheState.NONE
    # What the lyric document says the track is. A player that reports only a page
    # title knows less about the song than the lyrics already chosen for it.
    lyrics_song_id: str | None = None
    lyrics_title: str | None = None
    lyrics_artist: str | None = None
    lyrics_album: str | None = None


class DisplayScript(StrEnum):
    """Chinese script conversion applied only to rendered text."""

    OFF = "off"
    ZH_HANS = "zh-Hans"
    ZH_HANT = "zh-Hant"


class InterludeMarkerStyle(StrEnum):
    """Marker shape shown during a semantic interlude."""

    DOTS = "dots"
    SYMBOL = "symbol"


class InterludeCountdown(StrEnum):
    """Optional countdown representation for a semantic interlude."""

    OFF = "off"
    PERCENT = "percent"
    SECONDS = "seconds"


class TranslationDisplayState(StrEnum):
    """User-visible status of lyrics translation for the active document."""

    IDLE = "idle"
    TRANSLATING = "translating"
    READY = "ready"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class DisplayOptions:
    """Pure presentation options injected into the display projection."""

    lead_ms: int = 0
    track_offsets_ms: Mapping[TrackOffsetKey, int] = field(default_factory=lambda: MappingProxyType({}))
    lyrics_script: DisplayScript = DisplayScript.OFF
    interlude_style: InterludeMarkerStyle = InterludeMarkerStyle.DOTS
    interlude_countdown: InterludeCountdown = InterludeCountdown.OFF

    def __post_init__(self) -> None:
        """Freeze the offset mapping so one frame input cannot change underneath it."""
        if type(self.lead_ms) is not int:
            raise TypeError("display lead must be an integer number of milliseconds")
        normalized = dict(self.track_offsets_ms)
        if any(not isinstance(key, TrackOffsetKey) or type(value) is not int for key, value in normalized.items()):
            raise TypeError("track offsets must map structured keys to integers")
        object.__setattr__(self, "track_offsets_ms", MappingProxyType(normalized))
        try:
            object.__setattr__(self, "lyrics_script", DisplayScript(self.lyrics_script))
            object.__setattr__(self, "interlude_style", InterludeMarkerStyle(self.interlude_style))
            object.__setattr__(self, "interlude_countdown", InterludeCountdown(self.interlude_countdown))
        except ValueError as exc:
            raise ValueError("display options contain an unknown enum value") from exc


@dataclass(frozen=True)
class DisplayInput:
    """One complete source-neutral input to the display projection."""

    playback: PlaybackObservation
    document: LyricsDocument | None
    resolution: ResolutionState
    options: DisplayOptions
    translation_status: TranslationDisplayState = TranslationDisplayState.IDLE

    def __post_init__(self) -> None:
        """Reject source facts that cannot describe one coherent display input."""
        if self.resolution is ResolutionState.NO_TRACK:
            if self.playback.track is not None or self.document is not None:
                raise ValueError("NoTrack input cannot contain playback or lyric data")
            return
        if self.resolution is ResolutionState.AVAILABLE and self.document is None:
            raise ValueError("LyricsAvailable input requires a lyric document")
        if self.resolution in {ResolutionState.RESOLVING, ResolutionState.NOT_FOUND} and self.playback.track is None:
            raise ValueError(f"{self.resolution.value} input requires a playback track")
        if self.resolution is ResolutionState.NOT_FOUND and self.document is not None and self.document.lines:
            raise ValueError("LyricsNotFound input cannot contain timed lyric lines")


@dataclass(frozen=True)
class LineProgress:
    """Semantic progress through one displayed line, independent of pixels."""

    line_id: str
    fraction: float

    def __post_init__(self) -> None:
        """Keep renderer progress within its documented semantic range."""
        if not self.line_id:
            raise ValueError("line progress requires a line id")
        _validate_fraction(self.fraction)


@dataclass(frozen=True)
class WordProgress:
    """Per-word temporal progress for a specific lyric line."""

    line_id: str
    fractions: tuple[float, ...]
    active_index: int

    def __post_init__(self) -> None:
        """Validate immutable word progress before it reaches a renderer."""
        if not self.line_id:
            raise ValueError("word progress requires a line id")
        normalized = tuple(self.fractions)
        for fraction in normalized:
            _validate_fraction(fraction)
        if type(self.active_index) is not int or not -1 <= self.active_index < len(normalized):
            raise ValueError("word progress has an invalid active index")
        object.__setattr__(self, "fractions", normalized)


@dataclass(frozen=True)
class Interlude:
    """A timed gap in which a lyric document has no active sung line."""

    start: float
    end: float

    def progress(self, position: float) -> float:
        """Return the clamped progress through this gap."""
        span = self.end - self.start
        if span <= 0.0:
            return 1.0
        return min(1.0, max(0.0, (position - self.start) / span))


@dataclass(frozen=True)
class DisplayDiagnostic:
    """A user-visible or loggable explanation attached to a display frame."""

    code: str
    message: str


@dataclass(frozen=True)
class DisplayFrame:
    """The single source-neutral presentation result consumed by a renderer."""

    state: DisplayState
    track: TrackIdentity | None = None
    document: LyricsDocument | None = None
    current_time: float | None = None
    is_playing: bool = False
    previous: LyricLine | None = None
    current: LyricLine | None = None
    translation: LyricLine | None = None
    fallback: LyricLine | None = None
    next: LyricLine | None = None
    around: tuple[LyricLine, ...] = ()
    interlude: Interlude | None = None
    interlude_line: LyricLine | None = None
    line_progress: LineProgress | None = None
    word_progress: WordProgress | None = None
    diagnostic: DisplayDiagnostic | None = None
    track_offset_key: TrackOffsetKey | None = None
    translation_status: TranslationDisplayState = TranslationDisplayState.IDLE

EMPTY_FRAME = DisplayFrame(state=DisplayState.NO_TRACK)


def _validate_fraction(value: float) -> None:
    """Validate one renderer-independent progress fraction."""
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("progress fraction must be finite and within 0..1")
