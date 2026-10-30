"""Bind canonical display frames to the overlay's lyric widgets."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QTimer
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
from .context_label import ContextLabel
from .karaoke_label import KaraokeLabel
from .state import LyricsState

INTERLUDE_SCALE = 0.62


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
        self._previous.set_lines(())
        self._next.set_lines(())
        self._translation.set_line(None, False)
        self._translation.setVisible(False)
        self._current.set_progress(None, None)
        title_line = frame.fallback
        if title_line is None:
            title_line = LyricLine(0, "title", 0.0, 1e9, self._translator.text("overlay.idle"), "", ())
        self._current.set_line(title_line, False)
        self._current.set_media_time(None)

    def _update_context(self, frame: DisplayFrame, old: DisplayFrame) -> None:
        """Move context only for adjacent lyric changes, never for clock ticks."""
        if frame.document is old.document and frame.previous == old.previous and frame.next == old.next:
            return
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
            label.set_lines(context, direction=direction)


__all__ = ["OverlayContentController"]
