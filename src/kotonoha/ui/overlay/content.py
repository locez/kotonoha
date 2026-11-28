"""Bind canonical display frames to the overlay's lyric widgets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel, QWidget

from ...config import Config, LyricsDisplayMode
from ...display.models import EMPTY_FRAME, DisplayFrame, DisplayState, LineProgress, TranslationDisplayState
from ...display.offsets import (
    TRACK_OFFSET_STEP_MS,
    TrackOffsetKey,
    TrackOffsetReader,
    clamp_track_offset,
)
from ...lyrics.models import LyricLine, LyricsDocument
from ...strings import Translator
from .context_label import ContextLabel
from .karaoke_label import KaraokeLabel
from .state import LyricsState
from .text_layout import is_right_to_left

INTERLUDE_SCALE = 0.62
_TRANSLATION_STATUS_SPECS: dict[TranslationDisplayState, tuple[str, str]] = {
    TranslationDisplayState.TRANSLATING: ("translating", "overlay.translation.translating"),
    TranslationDisplayState.FAILED: ("failed", "overlay.translation.failed"),
    TranslationDisplayState.UNAVAILABLE: ("unavailable", "overlay.translation.unavailable"),
}


class OverlayContentController:
    """Own frame projection, lyric labels, track offset feedback, and its timer."""

    def __init__(
        self,
        state: LyricsState,
        config: Config,
        previous: ContextLabel,
        current: KaraokeLabel,
        feedback: QLabel,
        translation: KaraokeLabel,
        next_label: ContextLabel,
        container: QWidget,
        *,
        timer_parent: QWidget,
        on_input_region_refresh: Callable[[], None],
        on_offset_changed: Callable[[TrackOffsetKey, int], None],
        track_offsets: TrackOffsetReader,
        translator: Translator,
    ) -> None:
        """Create a content owner around the already-built lyric widgets."""
        self._state = state
        self._config = config
        self._previous = previous
        self._current = current
        self._feedback = feedback
        self._translation = translation
        self._next = next_label
        self._container = container
        self._on_input_region_refresh = on_input_region_refresh
        self._on_offset_changed = on_offset_changed
        self._track_offsets = track_offsets
        self._translator = translator
        self._frame = EMPTY_FRAME
        self._track_key: TrackOffsetKey | None = None
        self._interlude_active = False
        self._showing_translation_status = False
        self._context_use_translation = False
        self._translation_check_doc: LyricsDocument | None = None
        self._translation_check_result = False
        self._feedback_timer = QTimer(timer_parent)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._restore_after_offset_feedback)

    @property
    def frame(self) -> DisplayFrame:
        """Return the last frame accepted for presentation."""
        return self._frame

    def update_config(self, config: Config) -> None:
        """Use a newly applied config for frame projection and offset actions."""
        self._config = config

    def reapply_frame(self) -> None:
        """Re-render the current frame after display mode or appearance settings change."""
        self.on_frame(self._frame)

    def stop(self) -> None:
        """Stop feedback and context transitions owned by this controller."""
        self._feedback_timer.stop()
        self._previous.stop()
        self._next.stop()

    def on_frame(self, frame: DisplayFrame) -> None:
        """Render one canonical frame and request input-region recalculation."""
        old_frame = self._frame
        self._frame = frame
        self._update_context(frame, old_frame)
        has_lyrics = frame.state is DisplayState.LYRICS_AVAILABLE and frame.document is not None
        if has_lyrics and frame.current is None and frame.interlude_line is not None:
            self._show_interlude(frame)
            self._on_input_region_refresh()
            return

        if self._interlude_active:
            self._interlude_active = False
            self._current.set_scale(1.0)
        if not has_lyrics or frame.current is None:
            self._show_empty(frame)
            self._on_input_region_refresh()
            return

        self._container.setVisible(True)
        document = frame.document
        self._set_track_key_from_frame(frame)
        current = frame.current
        if current is None:
            self._show_empty(frame)
            self._on_input_region_refresh()
            return
        mode = self._config.lyrics_display_mode
        if mode is LyricsDisplayMode.TRANSLATION_ONLY and frame.translation is not None:
            # Render the sole translated line on the primary label so typography,
            # effects, and vertical spacing match Original-only mode identically.
            self._current.set_line(frame.translation, False)
            self._current.set_progress(frame.line_progress, None)
            self._hide_translation()
            self._on_input_region_refresh()
            return

        word_mode = document is not None and document.has_word_timing and current.has_word_timing
        self._current.set_line(current, word_mode and self._config.karaoke)
        self._current.set_progress(frame.line_progress, frame.word_progress)
        if mode.shows_translation and frame.translation is not None:
            self._show_translation_line(frame.translation, frame.line_progress)
        elif mode.shows_translation and (status_line := self._translation_status_line(frame)) is not None:
            self._showing_translation_status = True
            self._translation.set_line(status_line, False)
            self._translation.setVisible(True)
            self._translation.set_progress(None, None)
        else:
            self._hide_translation()
        self._on_input_region_refresh()

    def refresh_media_time(self) -> None:
        """Reapply frame-owned progress after a display setting changes."""
        translation_as_primary = (
            self._config.lyrics_display_mode is LyricsDisplayMode.TRANSLATION_ONLY
            and self._frame.translation is not None
        )
        self._current.set_progress(
            self._frame.line_progress,
            None if translation_as_primary else self._frame.word_progress,
        )
        self._translation.set_progress(
            None if self._showing_translation_status else self._frame.line_progress,
            None,
        )

    def nudge_earlier(self) -> None:
        """Move this track's lyrics earlier by one configured step."""
        self._nudge_offset(TRACK_OFFSET_STEP_MS)

    def nudge_later(self) -> None:
        """Move this track's lyrics later by one configured step."""
        self._nudge_offset(-TRACK_OFFSET_STEP_MS)

    def show_offset_feedback(self, offset_ms: int) -> None:
        """Show the applied offset briefly without changing the canonical frame."""
        self._feedback.setText(
            self._translator.text("overlay.offset.value").format(offset=offset_ms)
        )
        self._feedback.setVisible(True)
        self._feedback_timer.start(1200)

    def reset(self) -> None:
        """Render the canonical empty frame."""
        self.on_frame(EMPTY_FRAME)

    def _nudge_offset(self, delta_ms: int) -> None:
        key = self._track_key
        if key is None:
            return
        current = self._track_offsets.offset_for(key)
        offset = clamp_track_offset(current + delta_ms)
        self._on_offset_changed(key, offset)
        self.show_offset_feedback(offset)
        self.refresh_media_time()

    def _restore_after_offset_feedback(self) -> None:
        """Restore the latest canonical frame after the feedback timer expires."""
        self._feedback.clear()

    def _set_track_key_from_frame(self, frame: DisplayFrame) -> None:
        """Use the identity calculated once by the display projection."""
        self._track_key = frame.track_offset_key

    def _show_interlude(self, frame: DisplayFrame) -> None:
        """Keep surrounding lines visible while rendering an intro or break marker."""
        self._current.set_scale(INTERLUDE_SCALE)
        self._container.setVisible(True)
        self._set_track_key_from_frame(frame)
        self._hide_translation()
        interlude_line = frame.interlude_line
        if interlude_line is None:
            return
        self._interlude_active = True
        # Resolve from the timeline, so seeks and track changes need no playback history.
        direction_line = frame.previous if frame.previous is not None else frame.next
        direction_text = self._context_line_text(direction_line, self._use_translation_for_context(frame))
        right_to_left = bool(direction_text) and is_right_to_left(direction_text)
        self._current.set_line(interlude_line, False, right_to_left=right_to_left)
        self._current.set_progress(frame.line_progress, None)

    def _show_empty(self, frame: DisplayFrame) -> None:
        self._track_key = None
        self._previous.set_lines(())
        self._next.set_lines(())
        self._hide_translation()
        self._current.set_progress(None, None)
        title_line = frame.fallback
        if title_line is None:
            title_line = LyricLine(0, "title", 0.0, 1e9, self._translator.text("overlay.idle"), "", ())
        self._current.set_line(title_line, False)
        self._current.set_media_time(None)

    def _update_context(self, frame: DisplayFrame, old: DisplayFrame) -> None:
        """Move context only for adjacent lyric changes, never for clock ticks."""
        use_translation = self._use_translation_for_context(frame)
        if (
            frame.document is old.document
            and frame.previous == old.previous
            and frame.next == old.next
            and use_translation == self._context_use_translation
        ):
            return
        self._context_use_translation = use_translation
        direction = 0
        if frame.document is old.document and old.current is not None:
            if frame.previous == old.current:
                direction = 1
            elif frame.next == old.current:
                direction = -1
        lines = frame.document.lines if frame.document is not None else ()
        for label, anchor, step in ((self._previous, frame.previous, -1), (self._next, frame.next, 1)):
            if anchor is None:
                label.set_lines(())
                continue
            index = next((i for i, line in enumerate(lines) if line.id == anchor.id), None)
            if index is None:
                context = (anchor,)
            else:
                context = tuple(reversed(lines[:index + 1])) if step < 0 else lines[index:]
            if use_translation:
                context = tuple(
                    replace(line, text=line.translation) if line.translation.strip() else line
                    for line in context
                )
            label.set_lines(context, direction=direction)

    def _show_translation_line(self, line: LyricLine, progress: LineProgress | None) -> None:
        self._showing_translation_status = False
        self._translation.set_line(line, False)
        self._translation.setVisible(True)
        self._translation.set_progress(progress, None)

    def _hide_translation(self) -> None:
        self._showing_translation_status = False
        self._translation.set_line(None, False)
        self._translation.setVisible(False)
        self._translation.set_progress(None, None)

    def _translation_status_line(self, frame: DisplayFrame) -> LyricLine | None:
        """Build a steady, non-sweeping status line when translation is pending or unavailable."""
        spec = _TRANSLATION_STATUS_SPECS.get(frame.translation_status)
        if spec is not None:
            return self._status_line(*spec)
        if (
            self._config.lyrics_display_mode is LyricsDisplayMode.TRANSLATION_ONLY
            and frame.translation_status is TranslationDisplayState.IDLE
            and not self._document_has_translations(frame.document)
        ):
            return self._status_line("unavailable", "overlay.translation.unavailable")
        return None

    def _status_line(self, suffix: str, key: str) -> LyricLine:
        return LyricLine(0, f"translation-status-{suffix}", 0.0, 1e9, self._translator.text(key), "", ())

    def _use_translation_for_context(self, frame: DisplayFrame) -> bool:
        """Show translated text in context rows when Translation-only mode has ready translations."""
        return (
            self._config.lyrics_display_mode is LyricsDisplayMode.TRANSLATION_ONLY
            and frame.translation_status in {TranslationDisplayState.IDLE, TranslationDisplayState.READY}
            and self._document_has_translations(frame.document)
        )

    def _document_has_translations(self, document: LyricsDocument | None) -> bool:
        """Cache per-document translation presence so 60fps progress ticks stay O(1)."""
        if document is None:
            return False
        if document is not self._translation_check_doc:
            self._translation_check_doc = document
            self._translation_check_result = any(line.translation.strip() for line in document.lines)
        return self._translation_check_result

    @staticmethod
    def _context_line_text(line: LyricLine | None, use_translation: bool) -> str:
        if line is None:
            return ""
        if use_translation and line.translation.strip():
            return line.translation
        return line.text


__all__ = ["OverlayContentController"]
