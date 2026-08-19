"""Decide which MPRIS player the overlay follows.

Policy and its state only: no D-Bus, no Qt, no I/O. The provider reads the bus and
hands the readings here, so the rule that picks a player can be exercised without a
session bus — which is what the rule most needs, since every desktop presents a
different set of players and the interesting cases are the awkward combinations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .mpris_track import TrackInfo

#: How much later a rival must have started before the overlay follows it instead.
#: Two services that wrap the same playback announce themselves moments apart, and
#: without a margin the overlay would flip between them.
RECENT_PLAYER_MARGIN = 1.0

_FOLLOWABLE = frozenset({"Playing", "Paused"})


@dataclass(frozen=True)
class PlayerRecord:
    """One player as it was found on the bus.

    Named rather than a tuple: the bus name and the playback status are both strings
    sitting next to each other, and a positional reading of the pair is a bug that
    type checking cannot see.
    """

    player: Any
    bus_name: str
    status: str
    info: TrackInfo

    @property
    def has_track(self) -> bool:
        return bool(self.info.title or self.info.artist)


class PlayerSelector:
    """Which player to follow, and the little history that decision needs."""

    def __init__(self) -> None:
        self.current_name: str | None = None
        #: The user's pinned player, or "" for automatic.
        self.lock: str = ""
        #: When each player was first seen playing, used for the recency margin.
        self.playing_since: dict[str, float] = {}

    def forget_absent(self, present: set[str]) -> None:
        """Drop the history of players that are no longer on the bus."""
        for name in tuple(self.playing_since):
            if name not in present:
                del self.playing_since[name]

    def observe(self, bus_name: str, status: str, at: float) -> None:
        """Record whether a player is playing, and since when."""
        if status == "Playing":
            self.playing_since.setdefault(bus_name, at)
        else:
            self.playing_since.pop(bus_name, None)

    def order_to_poll(self, names: list[str]) -> list[str]:
        """The bus names to read, current player first so a tie keeps the current one."""
        ordered = list(names)
        if self.current_name in ordered:
            ordered.remove(self.current_name)
            ordered.insert(0, self.current_name)
        return ordered

    def score(self, record: PlayerRecord) -> tuple[int, int, int, int]:
        """Rank a Playing candidate: metadata first, then recency, then continuity.

        A source that names no performer cannot match anything, so it never wins on
        recency: with both browsers open, Chrome and Firefox each publish their own
        MPRIS service beside the Plasma bridge that wraps the same playback, carrying
        the raw tab title and an empty artist, and they announce themselves after it.
        """
        current_started = self.playing_since.get(self.current_name or "")
        candidate_started = self.playing_since.get(record.bus_name)
        started_more_recently = int(
            current_started is not None
            and candidate_started is not None
            and candidate_started - current_started > RECENT_PLAYER_MARGIN
        )
        return (
            1 if record.info.artist else 0,
            started_more_recently,
            1 if record.info.title else 0,
            1 if record.bus_name == self.current_name else 0,
        )

    def choose(self, records: list[PlayerRecord]) -> PlayerRecord | None:
        """Pick the player to follow, or None when nothing qualifies.

        One policy for both the poll and the settings picker. The picker used to carry
        its own copy that ordered the last two fallbacks the other way round, so with a
        Playing player reporting no metadata beside a Paused one that reports a track,
        the settings row marked a player as Current that the poll would not follow.
        """
        eligible = [record for record in records if record.status in _FOLLOWABLE]
        locked = next((record for record in eligible if record.bus_name == self.lock), None)
        if locked is not None:
            return locked
        playing = [r for r in eligible if r.status == "Playing" and r.has_track]
        if playing:
            return max(playing, key=self.score)
        current = next((r for r in eligible if r.bus_name == self.current_name), None)
        if current is not None and current.status == "Paused" and current.has_track:
            return current
        paused = next((r for r in eligible if r.status == "Paused" and r.has_track), None)
        if paused is not None:
            return paused
        return next((r for r in eligible if r.status == "Playing"), None)

    def automatic_name(self, records: list[PlayerRecord]) -> str | None:
        chosen = self.choose(records)
        return chosen.bus_name if chosen is not None else None
