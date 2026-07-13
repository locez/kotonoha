"""Pure MPRIS metadata parsing and transition stabilization."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from ..lyrics.match import TrackMetadata

_MAX_TRACK_LENGTH_S = 24 * 60 * 60

# Chrome's own MPRIS bridge prefixes the tab's unread-notification count and
# appends the site name to the page title, e.g. "(3) Song - YouTube". Both are
# player noise, not part of the song: the count churns the identity key (forcing
# needless re-resolution) and the suffix wrecks title matching. Strip them so a
# browser-sourced title lines up with the clean one Plasma Browser Integration
# reports for the same track.
_TITLE_BADGE_PREFIX = re.compile(r"^\(\d+\)\s+")
_TITLE_SITE_SUFFIX = re.compile(r"\s*[-|–—]\s*YouTube(?:\s+Music)?\s*$", re.IGNORECASE)


def _clean_title(title: str) -> str:
    cleaned = _TITLE_BADGE_PREFIX.sub("", title)
    cleaned = _TITLE_SITE_SUFFIX.sub("", cleaned)
    # Never strip a title down to nothing (a page literally titled "YouTube").
    return cleaned.strip() or title.strip()


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " / ".join(str(item) for item in value if isinstance(item, str))
    return ""


def _length_seconds(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    length_us = float(value)
    if not math.isfinite(length_us):
        return None
    length_s = length_us / 1_000_000.0
    if length_s <= 0.0 or length_s > _MAX_TRACK_LENGTH_S:
        return None
    return length_s


@dataclass(frozen=True)
class TrackInfo:
    title: str
    artist: str
    album: str
    length_s: float | None
    track_id: str

    def metadata(self) -> TrackMetadata:
        return TrackMetadata(self.title, self.artist, self.album, self.length_s)

    @property
    def identity_key(self) -> tuple[str, str, str, str]:
        return self.track_id, self.title, self.artist, self.album


def parse_metadata(raw: dict[str, Any]) -> TrackInfo:
    length_s = _length_seconds(raw.get("mpris:length"))
    return TrackInfo(
        title=_clean_title(_as_text(raw.get("xesam:title"))),
        artist=_as_text(raw.get("xesam:artist")),
        album=_as_text(raw.get("xesam:album")),
        length_s=length_s,
        track_id=str(raw.get("mpris:trackid") or ""),
    )


def unwrap(metadata: object) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {
        key: getattr(variant, "value", variant)
        for key, variant in metadata.items()
        if isinstance(key, str)
    }


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

        key = (observation.player_name, *info.identity_key)
        if key != self._candidate_key:
            self._candidate_key = key
            self._candidate = observation
            self._changed_at = observation.observed_at
            self._transitioning = key != self._committed_key
            return None

        settle_seconds = 0.35 if info.artist else 0.8
        if self._committed_key is not None:
            previous_title = self._committed_key[2]
            previous_artist = self._committed_key[3]
            if info.title != previous_title and info.artist and info.artist == previous_artist:
                settle_seconds = max(settle_seconds, 0.8)
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
