"""Application-owned display projection and timing workflow."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from ..async_task import create_owned_task, wait_for_owned
from ..display.contracts import DisplayPublisher
from ..display.models import (
    DisplayFrame,
    DisplayOptions,
    DisplayState,
    LyricsDisplayStatus,
    ResolutionState,
    TranslationDisplayState,
)
from ..display.presentation import DisplayEngine
from ..display.timeline import TimelineEngine
from ..lyrics.adapter import LyricsDocumentAdapter
from ..lyrics.artifact import LyricsArtifact
from ..lyrics.match import Candidate, MatchConfidence, TrackMetadata, evaluate_match
from ..lyrics.models import LyricsCacheState, LyricsDocument, LyricsOrigin
from ..playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity

DISPLAY_TICK_INTERVAL_S = 1.0 / 60.0
logger = logging.getLogger(__name__)


class DisplayCoordinator:
    """Own the normalized-frame workflow without knowing the presentation toolkit.

    Player and source adapters depend on this application boundary instead of
    importing ``LyricsState`` or constructing a concrete publisher. The
    composition root supplies the sole publisher implementation.
    """

    def __init__(
        self,
        publisher: DisplayPublisher,
        *,
        presenter: DisplayEngine,
        timeline: TimelineEngine,
    ) -> None:
        self._presenter = presenter
        self._publisher = publisher
        self._timeline = timeline
        self._source_document: LyricsDocument | None = None
        self._document: LyricsDocument | None = None
        self._translation_status: TranslationDisplayState = TranslationDisplayState.IDLE
        self._suppress_publish: bool = False
        self._document_listener: Callable[[LyricsDocument | None], None] | None = None
        self._resolution = ResolutionState.NO_TRACK
        self._manual_document: LyricsDocument | None = None
        self._manual_track: TrackIdentity | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None
        self._reported_task_failure: asyncio.Task[None] | None = None
        self._last_logged_display_key: tuple[object, ...] | None = None

    async def start(self) -> None:
        """Start the owned smooth-display task; repeated calls are harmless."""
        task = self._task
        if task is not None:
            if not task.done():
                return
            self._observe_task_failure(task)
        self._wake_event = asyncio.Event()
        task = create_owned_task(self._run(), name="kotonoha-display-clock")
        self._task = task
        task.add_done_callback(self._display_task_finished)

    async def stop(self) -> None:
        """Cancel and await the smooth-display task owned by this coordinator."""
        task = self._task
        self._task = None
        self._wake_event = None
        if task is None:
            return
        if task.done():
            # The done callback already reported any failure. Stopping a clock
            # that failed before shutdown remains an idempotent cleanup action.
            self._observe_task_failure(task)
            return
        task.cancel()
        cancellation_requested = await wait_for_owned(task)
        self._observe_task_failure(task)
        if cancellation_requested:
            raise asyncio.CancelledError

    def project(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
    ) -> DisplayFrame:
        """Build an ordinary completed frame without publishing it."""
        resolution = ResolutionState.from_facts(playback, document)
        return self._presenter.project_observation(playback, document, resolution)

    def project_resolution(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
        resolution: ResolutionState,
    ) -> DisplayFrame:
        """Build a frame from explicit resolution facts without publishing it."""
        return self._presenter.project_observation(playback, document, resolution)

    def set_options(self, options: DisplayOptions) -> None:
        """Replace display options and immediately reproject the active frame."""
        self._presenter.set_options(options)
        playback = self._timeline.advance()
        if playback is not None:
            self.publish_frame(self._project_observation(playback))

    def publish(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
    ) -> DisplayFrame:
        """Project and publish one ordinary completed playback/document pair."""
        return self.publish_resolution(
            playback,
            document,
            ResolutionState.from_facts(playback, document),
        )

    def publish_resolution(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
        resolution: ResolutionState,
    ) -> DisplayFrame:
        """Publish a playback/document pair with explicit source resolution."""
        self._clear_manual_override_if_track_changed(playback.track)
        manual_document = self._manual_document
        next_source = manual_document if manual_document is not None else document
        source_changed = next_source != self._source_document
        if source_changed:
            self._source_document = next_source
            self._document = next_source
            self._translation_status = TranslationDisplayState.IDLE
        self._resolution = ResolutionState.AVAILABLE if manual_document is not None else resolution
        playback = self._timeline.set_observation(playback)
        if source_changed:
            self._suppress_publish = True
            try:
                self._notify_document_listener(next_source)
            finally:
                self._suppress_publish = False
        frame = self._project_observation(playback)
        self.publish_frame(frame)
        self._wake()
        return frame

    def set_document_listener(
        self,
        listener: Callable[[LyricsDocument | None], None] | None,
    ) -> None:
        """Attach an optional observer notified when the active source document changes."""
        self._document_listener = listener

    def current_source_document(self) -> LyricsDocument | None:
        """Return the untranslated source document currently backing the display."""
        return self._source_document

    def apply_translated_document(
        self,
        source: LyricsDocument,
        translated: LyricsDocument,
    ) -> bool:
        """Replace the active display document if ``source`` is still current."""
        if self._source_document != source:
            return False
        self._document = translated
        self._translation_status = TranslationDisplayState.READY
        self._republish_current_frame()
        return True

    def set_translation_status(
        self,
        source: LyricsDocument,
        status: TranslationDisplayState,
    ) -> bool:
        """Update translation status when ``source`` is still the active document."""
        if self._source_document != source:
            return False
        next_document = self._document if status is TranslationDisplayState.READY else self._source_document
        if self._translation_status is status and self._document == next_document:
            return True
        self._document = next_document
        self._translation_status = status
        self._republish_current_frame()
        return True

    def reset_translated_document(self) -> None:
        """Restore the active source document when translation settings change."""
        if self._document == self._source_document and self._translation_status is TranslationDisplayState.IDLE:
            return
        self._document = self._source_document
        self._translation_status = TranslationDisplayState.IDLE
        self._republish_current_frame()

    def _republish_current_frame(self) -> None:
        """Reproject the active frame unless batched inside ``publish_resolution``."""
        if self._suppress_publish:
            return
        playback = self._timeline.advance()
        if playback is not None:
            self.publish_frame(self._project_observation(playback))

    def apply_manual_artifact(self, artifact: LyricsArtifact, expected_track: TrackMetadata) -> bool:
        """Replace the active document immediately while the expected track remains active."""
        playback = self._timeline.advance()
        if playback is None or playback.track is None or not self._matches_track(playback.track, expected_track):
            return False
        document = LyricsDocumentAdapter().adapt(
            artifact.lines,
            source_id=artifact.provider,
            source_name=artifact.provider,
            song_id=artifact.provider_song_id,
            title=artifact.title,
            artist=artifact.artist,
            album=artifact.album,
            duration_s=artifact.duration_s,
            origin=LyricsOrigin.MANUAL,
            cache_state=LyricsCacheState.MANUAL,
        )
        self._manual_track = playback.track
        self._manual_document = document
        self.publish_resolution(playback, document, ResolutionState.AVAILABLE)
        return True

    def current_lyrics_status(self) -> LyricsDisplayStatus:
        """Return the source facts for the document currently shown to the user."""
        observation = self._timeline.observation
        track = observation.track if observation is not None else None
        document = self._document
        return LyricsDisplayStatus(
            playback_source=observation.adapter_id if track is not None and observation is not None else None,
            lyrics_source_id=document.source_id if document is not None else None,
            lyrics_source_name=document.source_name if document is not None else None,
            origin=document.origin if document is not None else None,
            cache_state=document.cache_state if document is not None else LyricsCacheState.NONE,
            lyrics_song_id=document.song_id if document is not None else None,
            lyrics_title=document.title if document is not None else None,
            lyrics_artist=document.artist if document is not None else None,
            lyrics_album=document.album if document is not None else None,
        )

    def publish_frame(self, frame: DisplayFrame) -> bool:
        """Publish an already projected frame through the sole Qt bridge."""
        self._log_display_source(frame)
        cleared_source = False
        if frame.state is DisplayState.NO_TRACK and frame.track is None:
            cleared_source = self._source_document is not None
            self._source_document = None
            self._document = None
            self._translation_status = TranslationDisplayState.IDLE
            self._resolution = ResolutionState.NO_TRACK
            self._manual_document = None
            self._manual_track = None
            self._timeline.reset()
        published = self._publisher.publish(frame)
        if cleared_source:
            self._notify_document_listener(None)
        return published

    def _notify_document_listener(self, document: LyricsDocument | None) -> None:
        listener = self._document_listener
        if listener is not None:
            listener(document)

    def tick(self, position_s: float | None, status: PlaybackStatus) -> None:
        """Apply a clock calibration and publish the resulting display frame."""
        playback = self._timeline.observe(position_s, status)
        if playback is None:
            return
        self.publish_frame(self._project_observation(playback))
        self._wake()

    def _project_observation(self, playback: PlaybackObservation) -> DisplayFrame:
        return self._presenter.project_observation(
            playback,
            self._document,
            self._resolution,
            translation_status=self._translation_status,
        )

    def _clear_manual_override_if_track_changed(self, track: TrackIdentity | None) -> None:
        """Drop the manual document when a publication belongs to another track."""
        if self._manual_document is not None and not self._same_track(self._manual_track, track):
            self._manual_document = None
            self._manual_track = None

    @staticmethod
    def _same_track(expected: TrackIdentity | None, actual: TrackIdentity | None) -> bool:
        """Compare normalized track identity across adapters without requiring shared IDs."""
        if expected is None or actual is None:
            return False
        if expected.track_ref is not None and actual.track_ref is not None:
            if expected.adapter_id == actual.adapter_id and expected.player_id == actual.player_id:
                return expected.track_ref == actual.track_ref
        return (
            expected.title == actual.title
            and expected.artist == actual.artist
            and expected.album == actual.album
        )

    @staticmethod
    def _matches_track(track: TrackIdentity, expected: TrackMetadata) -> bool:
        """Ensure a delayed apply cannot replace lyrics for a later track."""
        candidate = TrackMetadata(
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_s=track.duration_s,
        )
        evidence = evaluate_match(
            candidate=Candidate(
                song_id="current-track",
                title=expected.title,
                artist=expected.artist,
                album=expected.album,
                duration_s=expected.duration_s,
            ),
            track=candidate,
        )
        return evidence.confidence is not MatchConfidence.NONE

    async def _run(self) -> None:
        wake_event = self._wake_event
        if wake_event is None:
            return
        try:
            while True:
                playback = self._timeline.advance()
                if playback is not None:
                    self.publish_frame(self._project_observation(playback))
                wake_event.clear()
                if not self._timeline.playing:
                    await wake_event.wait()
                    continue
                try:
                    await asyncio.wait_for(wake_event.wait(), DISPLAY_TICK_INTERVAL_S)
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise

    def _display_task_finished(self, task: asyncio.Task[None]) -> None:
        """Observe a failed clock task even when no later shutdown occurs."""
        self._observe_task_failure(task)

    def _observe_task_failure(self, task: asyncio.Task[None]) -> None:
        """Read and report an unexpected task failure exactly once."""
        if task.cancelled() or self._reported_task_failure is task:
            return
        error = task.exception()
        if error is None:
            return
        self._reported_task_failure = task
        logger.error("Display clock task failed: %s", error)

    def _wake(self) -> None:
        if self._wake_event is not None:
            self._wake_event.set()

    def _log_display_source(self, frame: DisplayFrame) -> None:
        """Log one authoritative source record per displayed lyric document."""
        document = frame.document
        if document is None:
            self._last_logged_display_key = None
            return
        key = self._display_log_key(frame)
        previous = self._last_logged_display_key
        if previous == key:
            return
        self._last_logged_display_key = key

        track = frame.track
        lyric_source = document.source_name if document.source_name is not None else document.source_id
        playback_source = track.adapter_id if track is not None else "none"
        logger.info(
            "LYRICS DISPLAY ACTIVE: lyric_source=%r source_id=%r playback_source=%r "
            "state=%s track=%r artist=%r ref=%r song_id=%r timing=%s lines=%d duration=%s",
            lyric_source,
            document.source_id,
            playback_source,
            frame.state,
            track.title if track is not None else "",
            track.artist if track is not None else "",
            track.track_ref if track is not None else None,
            document.song_id,
            document.timing,
            len(document.lines),
            "-" if document.duration_s is None else f"{document.duration_s:.3f}s",
        )

    @staticmethod
    def _display_log_key(frame: DisplayFrame) -> tuple[object, ...]:
        """Return stable display facts that matter when diagnosing source changes."""
        track = frame.track
        document = frame.document
        if document is None:
            raise ValueError("display log key requires a lyric document")
        return (
            frame.state,
            track.adapter_id if track is not None else None,
            track.track_ref if track is not None else None,
            track.title if track is not None else "",
            track.artist if track is not None else "",
            document.source_id,
            document.source_name,
            document.song_id,
            document.timing,
            document.duration_s,
            len(document.lines),
        )


__all__ = ["DisplayCoordinator"]
