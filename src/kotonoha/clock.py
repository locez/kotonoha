"""Local media clock.

The probe sends ``currentTime`` only on change + heartbeat (~1s). To drive a
smooth ~60fps word sweep between those updates, we advance a local estimate of
the media time from the last sync point using wall-clock deltas. Each incoming
frame re-anchors the clock, correcting any drift.

Crucially, playback state is inferred from whether the *reported time is moving
forward*, NOT from the probe's ``isPlaying`` flag — that flag has proven
unreliable (it can arrive as False while audio plays), and trusting it froze the
clock so the sweep jumped once per update instead of flowing. Forward motion of
``currentTime`` is the ground truth.

The estimation math is a pure function; :class:`MediaClock` adds the small bit
of mutable wall-clock state around it.
"""

from __future__ import annotations

import time

# Below this drift (seconds) we correct the clock smoothly instead of snapping,
# so an idle ~1s heartbeat whose currentTime disagrees slightly with our local
# estimate does not yank the karaoke sweep forward/back every second.
SNAP_THRESHOLD = 0.35

# Reported time must move by at least this (seconds) between syncs to count as
# forward motion. Forward motion is the ground truth for "playing".
ADVANCE_EPSILON = 0.01

# Players report Position coarsely: e.g. Plasma Browser Integration updates it
# about every 0.26s while we poll every 0.2s, so ~1 in 4 polls repeats the same
# value even though playback is advancing. Keep interpolating through a stall this
# long before treating it as a real pause, so the sweep flows instead of freezing
# and snapping back to the stale report every few frames.
STALL_GRACE = 1.5


def estimate_media_time(anchor_media: float, anchor_wall: float, now_wall: float, playing: bool) -> float:
    """Media time at ``now_wall`` given an anchor sample.

    While playing, media time advances with wall time; while paused it stays put.
    Never runs backwards relative to the anchor.
    """
    if not playing:
        return anchor_media
    elapsed = now_wall - anchor_wall
    if elapsed <= 0.0:
        return anchor_media
    return anchor_media + elapsed


class MediaClock:
    def __init__(self, monotonic=time.monotonic) -> None:
        self._monotonic = monotonic
        self._anchor_media: float | None = None
        self._anchor_wall: float = 0.0
        self._paused: bool = False
        self._last_report: float | None = None
        self._last_advance_wall: float = 0.0

    @property
    def has_anchor(self) -> bool:
        return self._anchor_media is not None

    @property
    def playing(self) -> bool:
        return self._anchor_media is not None and not self._paused

    def sync(self, media_time: float | None, playing: bool) -> None:
        """Re-anchor from a freshly received frame.

        The sweep only ever moves forward while playing: a small drift from our
        running estimate is absorbed smoothly, a large forward gap catches up, and
        a stale/coarse report that lags the estimate is ignored rather than
        yanking the sweep backward. A confirmed large backward jump is a seek and
        snaps. Playback is considered active until the reported time has stalled
        longer than ``STALL_GRACE`` (coarse Position repeats a value between
        polls), so the sweep does not freeze-and-snap every few frames.
        """
        if media_time is None:
            return  # nothing to anchor to; keep interpolating

        now_wall = self._monotonic()

        if self._anchor_media is None:  # first sync
            self._anchor_media = media_time
            self._anchor_wall = now_wall
            self._last_report = media_time
            self._last_advance_wall = now_wall
            self._paused = not playing
            return

        advanced = media_time - (self._last_report if self._last_report is not None else media_time)
        self._last_report = media_time
        # Where the smooth clock is right now, using the play state before this sync.
        running = estimate_media_time(self._anchor_media, self._anchor_wall, now_wall, not self._paused)

        # A large backward jump the player confirms is a seek: snap to it (the one
        # case the sweep is allowed to move backward).
        if advanced <= -SNAP_THRESHOLD and playing:
            self._anchor_media = media_time
            self._anchor_wall = now_wall
            self._last_advance_wall = now_wall
            self._paused = False
            return

        moved = advanced > ADVANCE_EPSILON
        # Stay "playing" while the reported time advances OR the player asserts it
        # is playing. MPRIS PlaybackStatus is reliable when it says Playing, yet
        # Position can sit still for several seconds between coarse updates — so a
        # stall alone must NOT pause the sweep. Only a stall sustained past the
        # grace window while the player is NOT reporting playback is a real pause.
        if moved or playing:
            self._last_advance_wall = now_wall
        self._paused = (now_wall - self._last_advance_wall) >= STALL_GRACE

        if self._paused:
            # Freeze where the sweep is; never roll back to a lagging report.
            self._anchor_media = max(media_time, running)
        elif moved and media_time - running >= SNAP_THRESHOLD:
            self._anchor_media = media_time  # a real forward jump: catch up
        else:
            # Absorb small drift and stale/coarse reports without moving backward.
            self._anchor_media = max(running, media_time)
        self._anchor_wall = now_wall

    def now(self) -> float | None:
        """Current estimated media time, or None if never synced."""
        if self._anchor_media is None:
            return None
        return estimate_media_time(self._anchor_media, self._anchor_wall, self._monotonic(), not self._paused)

    def reset(self) -> None:
        self._anchor_media = None
        self._anchor_wall = 0.0
        self._paused = False
        self._last_report = None
        self._last_advance_wall = 0.0
