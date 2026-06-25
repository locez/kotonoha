"""Decides whether the WS-pushed (Cider) lyric source is accepted.

Priority: external lyrics (MPRIS + Netease) over the Cider WS push. When the
external source has lyrics for the current song, the WS-pushed lyrics are
ignored; only when it has none do we accept the WS lyrics. Progress ticks are
never gated (an extra, consistent calibration never hurts).

Default is "accept" so that, with no external source running (Netease never
consulted, e.g. dbus unavailable), the Cider probe keeps working exactly as
before.
"""

from __future__ import annotations


class SourceGate:
    def __init__(self) -> None:
        self._accept_ws = True

    @property
    def accept_ws(self) -> bool:
        return self._accept_ws

    def set_accept_ws(self, value: bool) -> None:
        """Set by the MPRIS path per song: True when the priority order reaches
        the 'cider' source before any pull source (Netease/lrclib) had lyrics."""
        self._accept_ws = value
