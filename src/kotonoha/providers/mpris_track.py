"""Pure MPRIS metadata parsing and transition stabilization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..lyrics.match import TrackMetadata


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " / ".join(str(item) for item in value if isinstance(item, str))
    return ""


@dataclass(frozen=True)
class TrackInfo:
    title: str
    artist: str
    album: str
    length_s: float | None
    track_id: str

    def metadata(self) -> TrackMetadata:
        return TrackMetadata(self.title, self.artist, self.album, self.length_s)


def parse_metadata(raw: dict[str, Any]) -> TrackInfo:
    length_us = raw.get("mpris:length")
    length_s = (
        float(length_us) / 1_000_000.0
        if isinstance(length_us, (int, float)) and not isinstance(length_us, bool)
        else None
    )
    return TrackInfo(
        title=_as_text(raw.get("xesam:title")),
        artist=_as_text(raw.get("xesam:artist")),
        album=_as_text(raw.get("xesam:album")),
        length_s=length_s,
        track_id=str(raw.get("mpris:trackid") or ""),
    )


def unwrap(metadata: object) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {key: getattr(variant, "value", variant) for key, variant in metadata.items()}


@dataclass(frozen=True)
class TrackObservation:
    player_name: str
    info: TrackInfo
    playback_status: str
    position_s: float | None
    observed_at: float


@dataclass(frozen=True)
class TrackCommit:
    generation: int
    player_name: str
    info: TrackInfo


class TrackStabilizer:
    def __init__(self) -> None:
        self._candidate_key: tuple[object, ...] | None = None
        self._candidate: TrackObservation | None = None
        self._changed_at = 0.0
        self._committed_key: tuple[object, ...] | None = None
        self._generation = 0
        self._transitioning = False

    def observe(self, observation: TrackObservation) -> TrackCommit | None:
        info = observation.info
        if not info.title and not info.artist:
            self._transitioning = self._committed_key is not None
            self._candidate_key = None
            self._candidate = None
            return None

        key = (
            observation.player_name,
            info.track_id,
            info.title,
            info.artist,
            info.album,
            info.length_s,
        )
        if key != self._candidate_key:
            self._candidate_key = key
            self._candidate = observation
            self._changed_at = observation.observed_at
            self._transitioning = key != self._committed_key
            return None

        settle_seconds = 0.35 if info.artist else 0.8
        if observation.observed_at - self._changed_at < settle_seconds:
            return None
        if key == self._committed_key:
            self._transitioning = False
            return None

        self._committed_key = key
        self._generation += 1
        self._transitioning = False
        return TrackCommit(self._generation, observation.player_name, info)

    @property
    def transitioning(self) -> bool:
        return self._transitioning

    def reset(self) -> None:
        self._candidate_key = None
        self._candidate = None
        self._changed_at = 0.0
        self._committed_key = None
        self._transitioning = False
