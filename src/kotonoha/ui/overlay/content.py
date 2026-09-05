"""Bind canonical display frames to the overlay's lyric widgets."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QWidget

from ...config import Config
from ...display.models import EMPTY_FRAME, DisplayFrame, DisplayState
from ...display.offsets import (
    TRACK_OFFSET_STEP_MS,
    TrackOffsetKey,
    TrackOffsetReader,
    clamp_track_offset,
)
from ...lyrics.models import LyricLine
from ...strings import Translator
from .karaoke_label import KaraokeLabel
from .state import LyricsState

INTERLUDE_SCALE = 0.62


class OverlayContentController:
    """Own frame projection, lyric labels, track offset feedback, and its timer."""

    def __init__(
        self,
        state: LyricsState,
        config: Config,
        previous: QLabel,
        current: KaraokeLabel,
        feedback: QLabel,
        translation: KaraokeLabel,
        next_label: QLabel,
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

    def stop(self) -> None:
        """Stop feedback work owned by this content controller."""
        self._feedback_timer.stop()

    def on_frame(self, frame: DisplayFrame) -> None:
        """Render one canonical frame and request input-region recalculation."""
        self._frame = frame
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
        previous = frame.previous
        next_line = frame.next
        self._set_context_text(self._previous, previous.text if previous else "")
        self._set_context_text(self._next, next_line.text if next_line else "")
        word_mode = document is not None and document.has_word_timing and current.has_word_timing
        self._current.set_line(current, word_mode and self._config.karaoke)

        if self._config.show_translation and frame.translation is not None:
            self._translation.set_line(frame.translation, False)
            self._translation.setVisible(True)
        else:
            self._translation.set_line(None, False)
            self._translation.setVisible(False)
        self._current.set_progress(frame.line_progress, frame.word_progress)
        self._translation.set_progress(frame.line_progress, None)
        self._on_input_region_refresh()

    def refresh_media_time(self) -> None:
        """Reapply frame-owned progress after a display setting changes."""
        self._current.set_progress(self._frame.line_progress, self._frame.word_progress)
        self._translation.set_progress(self._frame.line_progress, None)

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
        previous = frame.previous
        next_line = frame.next
        self._set_context_text(self._previous, previous.text if previous else "")
        self._set_context_text(self._next, next_line.text if next_line else "")
        self._translation.set_line(None, False)
        self._translation.setVisible(False)
        interlude_line = frame.interlude_line
        if interlude_line is None:
            return
        self._interlude_active = True
        self._current.set_line(interlude_line, False)
        self._current.set_progress(frame.line_progress, None)

    def _show_empty(self, frame: DisplayFrame) -> None:
        self._track_key = None
        self._previous.setText("")
        self._next.setText("")
        self._translation.set_line(None, False)
        self._translation.setVisible(False)
        self._current.set_progress(None, None)
        title_line = frame.fallback
        if title_line is None:
            title_line = LyricLine(0, "title", 0.0, 1e9, self._translator.text("overlay.idle"), "", ())
        self._current.set_line(title_line, False)
        self._current.set_media_time(None)

    @staticmethod
    def _set_context_text(label: QLabel, text: str) -> None:
        """Set context text while eliding it to the label's fixed width."""
        width = label.maximumWidth()
        if text and 0 < width < 16_777_215:
            text = label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width)
        if label.text() == text:
            return
        label.setText(text)


__all__ = ["OverlayContentController"]
