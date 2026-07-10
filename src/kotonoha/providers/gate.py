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


class SourceGate:
    def __init__(self) -> None:
        self._mode: Literal["standalone", "external", "cider"] = "standalone"
        self._bound_client_id: int | None = None
        self._snapshots: dict[int, tuple[int, LyricsSnapshot]] = {}
        self._sequence = 0

    @property
    def accept_ws(self) -> bool:
        return self._mode != "external"

    @property
    def cider_active(self) -> bool:
        return self._mode == "cider" and self._bound_client_id in self._snapshots

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

    def current_match(self, track: TrackMetadata) -> CiderMatch | None:
        ordered = sorted(self._snapshots.items(), key=lambda item: item[1][0], reverse=True)
        for client_id, (_sequence, snapshot) in ordered:
            if not snapshot.found or not snapshot.title:
                continue
            candidate = Candidate(
                song_id=snapshot.song_id or f"cider:{client_id}",
                title=snapshot.title,
                artist=snapshot.artist or "",
                duration_s=None,
            )
            evidence = evaluate_match(candidate, track)
            if evidence.confidence is MatchConfidence.HIGH or (
                evidence.confidence is MatchConfidence.MEDIUM and evidence.title_exact
            ):
                return CiderMatch(client_id, snapshot)
        return None

    def accepts(self, client_id: int) -> bool:
        if self._mode == "standalone":
            return True
        if self._mode == "external":
            return False
        return client_id == self._bound_client_id

    def drop_client(self, client_id: int) -> None:
        self._snapshots.pop(client_id, None)
        if self._bound_client_id == client_id:
            self.select_external()

    def set_accept_ws(self, value: bool) -> None:
        """Compatibility wrapper for callers not yet migrated to explicit modes."""
        if value:
            self.select_standalone()
        else:
            self.select_external()
