"""Object-owned projection from playback and lyric inputs to ``DisplayFrame``."""

from __future__ import annotations

from dataclasses import replace

from ..lyrics.models import LyricLine, LyricsDocument
from ..playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from .karaoke import (
    active_word_index,
    interlude_text,
    line_fill_fraction,
    line_progress,
    word_fill_fractions,
)
from .models import (
    DisplayDiagnostic,
    DisplayFrame,
    DisplayInput,
    DisplayOptions,
    DisplayState,
    Interlude,
    LineProgress,
    ResolutionState,
    TranslationDisplayState,
    WordProgress,
)
from .offsets import TrackOffsetKey, TrackOffsetKeyResolver
from .rules import find_current_index, in_interlude, interlude_at, sweep_end, typical_span
from .text import DisplayTextTransformer, ScriptTextTransformer

_SUPPRESSED_TRANSLATION_STATES = frozenset(
    {
        TranslationDisplayState.TRANSLATING,
        TranslationDisplayState.FAILED,
        TranslationDisplayState.UNAVAILABLE,
        TranslationDisplayState.SKIPPED,
    }
)


class DisplayEngine:
    """Build the single renderer-facing frame shared by every input adapter.

    The engine owns display policy but no wall-clock state.  A caller supplies a
    complete :class:`DisplayInput`; the returned frame contains canonical line
    context plus semantic progress for a renderer to paint.
    """

    def __init__(
        self,
        options: DisplayOptions | None = None,
        *,
        text_transformer: DisplayTextTransformer | None = None,
    ) -> None:
        self._options = options if options is not None else DisplayOptions()
        self._text_transformer = text_transformer if text_transformer is not None else ScriptTextTransformer()
        self._offset_key_resolver = TrackOffsetKeyResolver()

    @property
    def options(self) -> DisplayOptions:
        """Return the immutable presentation options currently in use."""
        return self._options

    def set_options(self, options: DisplayOptions) -> None:
        """Replace presentation options without retaining mutable config state."""
        self._options = options

    def project_input(self, display_input: DisplayInput) -> DisplayFrame:
        """Project one complete normalized input into a display frame."""
        playback = display_input.playback
        options = display_input.options
        source_document = display_input.document
        document = self._display_document(source_document, options)
        offset_key = self._offset_key_resolver.resolve(playback.track, source_document)
        position = self._display_position(playback, offset_key, options)
        state = display_input.resolution.display_state()
        lines = document.lines if document is not None else ()

        diagnostic: DisplayDiagnostic | None = None
        if state is DisplayState.LYRICS_AVAILABLE and not lines:
            state = DisplayState.LYRICS_NOT_FOUND
            diagnostic = DisplayDiagnostic("empty_document", "The lyric source returned no timed lines")

        if state is not DisplayState.LYRICS_AVAILABLE or not lines or position is None:
            return DisplayFrame(
                state=state,
                track=playback.track,
                document=document,
                current_time=position,
                is_playing=playback.status is PlaybackStatus.PLAYING,
                fallback=self._fallback_line(playback.track, document, options),
                diagnostic=diagnostic,
                track_offset_key=offset_key,
            )

        index = find_current_index(lines, position)
        duration_s = document.duration_s if document is not None else None
        quiet = in_interlude(lines, index, position, duration_s)
        current = None if quiet else (lines[index] if 0 <= index < len(lines) else None)
        previous = lines[index] if quiet else (lines[index - 1] if index - 1 >= 0 else None)
        next_line = lines[index + 1] if 0 <= index + 1 < len(lines) else None
        interlude = interlude_at(lines, index, position, duration_s)
        around = tuple(lines[max(0, index - 2) : index + 3])
        interlude_line = self._interlude_line(interlude, position, options)

        line_result: LineProgress | None = None
        word_result: WordProgress | None = None
        translation: LyricLine | None = None
        translation_status = display_input.translation_status
        suppress_translation = translation_status in _SUPPRESSED_TRANSLATION_STATES
        if current is not None:
            line_result = LineProgress(current.id, self._line_fraction(current, position, lines))
            if current.translation and not suppress_translation:
                translation = replace(current, text=current.translation, translation="", words=())
            if current.has_word_timing:
                word_result = WordProgress(
                    current.id,
                    word_fill_fractions(current.words, position),
                    active_word_index(current.words, position),
                )
        elif interlude is not None and interlude_line is not None:
            line_result = LineProgress(interlude_line.id, interlude.progress(position))

        return DisplayFrame(
            state=state,
            track=playback.track,
            document=document,
            current_time=position,
            is_playing=playback.status is PlaybackStatus.PLAYING,
            previous=previous,
            current=current,
            translation=translation,
            fallback=None,
            next=next_line,
            around=around,
            interlude=interlude,
            interlude_line=interlude_line,
            line_progress=line_result,
            word_progress=word_result,
            track_offset_key=offset_key,
            translation_status=translation_status,
        )

    def project_observation(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
        resolution: ResolutionState,
        *,
        translation_status: TranslationDisplayState = TranslationDisplayState.IDLE,
    ) -> DisplayFrame:
        """Project normalized playback, document, and explicit resolution facts."""
        return self.project_input(
            DisplayInput(playback, document, resolution, self._options, translation_status)
        )

    def _display_document(
        self,
        document: LyricsDocument | None,
        options: DisplayOptions,
    ) -> LyricsDocument | None:
        """Apply display-only text conversion without mutating the source document."""
        if document is None:
            return document
        return self._text_transformer.document(document, options.lyrics_script)

    def _interlude_line(
        self,
        interlude: Interlude | None,
        position: float,
        options: DisplayOptions,
    ) -> LyricLine | None:
        """Create the renderer-ready marker for an active semantic interlude."""
        if interlude is None:
            return None
        text = interlude_text(
            interlude,
            position,
            style=options.interlude_style,
            countdown=options.interlude_countdown,
        )
        return LyricLine(0, "interlude", interlude.start, interlude.end, text, "", ())

    def _display_position(
        self,
        playback: PlaybackObservation,
        offset_key: TrackOffsetKey | None,
        options: DisplayOptions,
    ) -> float | None:
        """Apply configured lead and per-track offset at the display boundary."""
        position = playback.position_s
        if position is None:
            return None
        offset_ms = options.track_offsets_ms.get(offset_key, 0) if offset_key is not None else 0
        return position + (options.lead_ms + offset_ms) / 1000.0

    def _fallback_line(
        self,
        track: TrackIdentity | None,
        document: LyricsDocument | None,
        options: DisplayOptions,
    ) -> LyricLine | None:
        """Build the display-only title line used while lyrics are unavailable."""
        title_value = track.title if track is not None else document.title if document is not None else None
        artist_value = track.artist if track is not None else document.artist if document is not None else None
        if not title_value:
            return None
        artist = f" — {artist_value}" if artist_value else ""
        text = self._text_transformer.text(f"♪ {title_value}{artist}", options.lyrics_script)
        return LyricLine(0, "title", 0.0, 1e9, text, "", ())

    def _line_fraction(
        self,
        line: LyricLine,
        position: float,
        lines: tuple[LyricLine, ...],
    ) -> float:
        """Calculate line sweep progress while preserving the source line span."""
        if line.has_word_timing:
            return line_progress(line, position)
        end = sweep_end(line, typical_span(lines))
        return line_fill_fraction(line.start, end, position)


__all__ = ["DisplayEngine"]
