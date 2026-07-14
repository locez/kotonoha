"""Ownership gate between external lyrics and Cider's live WS snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..lyrics.match import Candidate, MatchConfidence, TrackMetadata, evaluate_match
from ..model import LyricsSnapshot


@dataclass(frozen=True)
class CiderMatch:
    client_id: int
    snapshot: LyricsSnapshot
    confidence: MatchConfidence = MatchConfidence.HIGH


@dataclass(frozen=True)
class CiderTiming:
    client_id: int
    current_time: float | None
    is_playing: bool | None
    duration_s: float | None = None


class SourceGate:
    def __init__(self) -> None:
        self._mode: Literal["standalone", "external", "cider"] = "standalone"
        self._bound_client_id: int | None = None
        self._snapshots: dict[int, tuple[int, LyricsSnapshot]] = {}
        self._sequence = 0
        self._ticks: dict[int, tuple[int, int | None, CiderTiming]] = {}
        self._tick_sequence = 0

    @property
    def accept_ws(self) -> bool:
        return self._mode != "external"

    @property
    def cider_active(self) -> bool:
        retained = self._snapshots.get(self._bound_client_id) if self._bound_client_id is not None else None
        return self._mode == "cider" and retained is not None and retained[1].found

    @property
    def revision(self) -> int:
        return self._sequence

    def select_external(self) -> None:
        self._mode = "external"
        self._bound_client_id = None

    def select_cider(self, client_id: int) -> None:
        self._mode = "cider"
        self._bound_client_id = client_id

    def select_standalone(self) -> None:
        self._mode = "standalone"
        self._bound_client_id = None

    def observe_snapshot(self, client_id: int, snapshot: LyricsSnapshot) -> None:
        self._sequence += 1
        self._snapshots[client_id] = self._sequence, snapshot

    def observe_tick(self, client_id: int, current_time: float | None, is_playing: bool | None) -> None:
        self._tick_sequence += 1
        retained = self._snapshots.get(client_id)
        snapshot_sequence = retained[0] if retained is not None else None
        self._ticks[client_id] = (
            self._tick_sequence,
            snapshot_sequence,
            CiderTiming(client_id, current_time, is_playing),
        )

    @staticmethod
    def _accepted_confidence(
        snapshot: LyricsSnapshot, track: TrackMetadata, *, require_lyrics: bool
    ) -> MatchConfidence | None:
        """Confidence at which this snapshot is accepted as the current track, or
        None if it is not a match. HIGH is always accepted; MEDIUM only when the
        title is exact (a cover/compilation may report a looser artist)."""
        if (require_lyrics and not snapshot.found) or not snapshot.title:
            return None
        candidate = Candidate(
            song_id=snapshot.song_id or "cider",
            title=snapshot.title,
            artist=snapshot.artist or "",
            duration_s=None,
        )
        evidence = evaluate_match(candidate, track)
        if evidence.confidence is MatchConfidence.HIGH:
            return MatchConfidence.HIGH
        if evidence.confidence is MatchConfidence.MEDIUM and evidence.title_exact:
            return MatchConfidence.MEDIUM
        return None

    @staticmethod
    def _snapshot_matches(snapshot: LyricsSnapshot, track: TrackMetadata, *, require_lyrics: bool) -> bool:
        return SourceGate._accepted_confidence(snapshot, track, require_lyrics=require_lyrics) is not None

    def current_match(self, track: TrackMetadata) -> CiderMatch | None:
        ordered = sorted(self._snapshots.items(), key=lambda item: item[1][0], reverse=True)
        for client_id, (_sequence, snapshot) in ordered:
            confidence = self._accepted_confidence(snapshot, track, require_lyrics=True)
            if confidence is not None:
                return CiderMatch(client_id, snapshot, confidence)
        return None

    def current_timing(self, track: TrackMetadata) -> CiderTiming | None:
        ordered = sorted(self._ticks.items(), key=lambda item: item[1][0], reverse=True)
        for client_id, (_tick_sequence, snapshot_sequence, timing) in ordered:
            retained = self._snapshots.get(client_id)
            if retained is None or retained[0] != snapshot_sequence:
                continue
            if self._snapshot_matches(retained[1], track, require_lyrics=False):
                return CiderTiming(
                    timing.client_id,
                    timing.current_time,
                    timing.is_playing,
                    retained[1].duration_s,
                )
        return None

    def accepts(self, client_id: int) -> bool:
        if self._mode == "standalone":
            return True
        if self._mode == "external":
            return False
        return client_id == self._bound_client_id

    def drop_client(self, client_id: int) -> None:
        self._ticks.pop(client_id, None)
        if self._snapshots.pop(client_id, None) is not None:
            self._sequence += 1
        if self._bound_client_id == client_id:
            self.select_external()

    def set_accept_ws(self, value: bool) -> None:
        """Compatibility wrapper for callers not yet migrated to explicit modes."""
        if value:
            self.select_standalone()
        else:
            self.select_external()
