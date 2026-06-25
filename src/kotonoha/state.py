"""Shared lyrics state with Qt change notification.

:class:`LyricsState` is the single source of truth between the WebSocket
receiver (writer) and the overlay/tray (readers). It stores the latest
:class:`~kotonoha.model.LyricsSnapshot` and emits ``snapshot_changed`` whenever
a genuinely different snapshot arrives, so an idle/paused heartbeat that carries
no new information does not churn the UI.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from .model import EMPTY_SNAPSHOT, LyricsSnapshot


class LyricsState(QObject):
    snapshot_changed = pyqtSignal(object)  # emits LyricsSnapshot (lyric content changed)
    time_ticked = pyqtSignal(object, object)  # emits (current_time: float|None, is_playing: bool|None)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._snapshot: LyricsSnapshot = EMPTY_SNAPSHOT

    @property
    def snapshot(self) -> LyricsSnapshot:
        return self._snapshot

    def update(self, snapshot: LyricsSnapshot) -> bool:
        """Store ``snapshot`` and notify listeners if it changed.

        Returns True if the snapshot differed and a signal was emitted.
        """
        if snapshot == self._snapshot:
            return False
        self._snapshot = snapshot
        self.snapshot_changed.emit(snapshot)
        return True

    def tick(self, current_time: float | None, is_playing: bool | None) -> None:
        """High-frequency clock calibration; does not touch lyric content."""
        self.time_ticked.emit(current_time, is_playing)

    def clear(self) -> bool:
        return self.update(EMPTY_SNAPSHOT)
