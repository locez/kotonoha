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

    @property
    def has_anchor(self) -> bool:
        return self._anchor_media is not None

    @property
    def playing(self) -> bool:
        return self._anchor_media is not None and not self._paused

    def sync(self, media_time: float | None, playing: bool) -> None:
        """Re-anchor from a freshly received frame.

        Playback is treated as active when the isPlaying flag is set OR the
        reported time advanced since the last sync. While active, a small drift
        from our running estimate is absorbed smoothly (no visible jump); a large
        one (seek) snaps. When the reported time stops advancing we freeze.
        """
        if media_time is None:
            return  # nothing to anchor to; keep interpolating

        now_wall = self._monotonic()

        if self._anchor_media is None:  # first sync
            self._anchor_media = media_time
            self._anchor_wall = now_wall
            self._last_report = media_time
            self._paused = not playing
            return

        advanced = media_time - (self._last_report if self._last_report is not None else media_time)
        self._last_report = media_time
        # Forward motion of the reported time is the ground truth: time advancing
        # => playing; time stalled => paused (overrides a stale isPlaying flag);
        # time jumped backward => a seek, trust the flag.
        if advanced > ADVANCE_EPSILON:
            active = True
        elif advanced < -ADVANCE_EPSILON:
            active = playing
        else:
            active = False
        self._paused = not active

        if not active:
            self._anchor_media = media_time
            self._anchor_wall = now_wall
            return

        estimate = estimate_media_time(self._anchor_media, self._anchor_wall, now_wall, True)
        if abs(media_time - estimate) < SNAP_THRESHOLD:
            self._anchor_media = estimate  # smooth correction, time stays continuous
        else:
            self._anchor_media = media_time  # snap (seek / large drift)
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
