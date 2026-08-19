"""Every read of the session bus, each with a deadline.

The provider owns what to do with a player; this owns talking to one. Kept apart
because the failure modes are different in kind: a player can vanish between two
calls, own its bus name and never answer, or answer with something unparseable,
and none of those are the provider's business beyond "there is nothing to show".
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from .mpris_track import TrackInfo, parse_metadata
from .mpris_track import unwrap as _unwrap

logger = logging.getLogger(__name__)

DBUS_NAME = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

MPRIS_INTROSPECTION = """<node>
  <interface name="org.mpris.MediaPlayer2.Player">
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Position" type="x" access="read"/>
  </interface>
</node>"""

#: How long any one reply may take. A player that owns its bus name and never
#: answers is not an error, it is silence, and there is one poll task: without a
#: deadline it waits inside that call and every other player stops being looked at.
DBUS_CALL_TIMEOUT = 2.0

_T = TypeVar("_T")


def plain_value(value: Any) -> Any:
    """A property as its own value, whether or not D-Bus wrapped it.

    A single property comes back as a Variant while an a{sv} map arrives already
    unwrapped, and the two reach this module through different calls. Reflection is
    what tells them apart: the wrapper is a third-party type, and asking it for the
    value it carries is the only thing either shape has in common. Passing a Variant
    to the map unwrapper instead yielded "{}" as every player's display name.
    """
    return getattr(value, "value", value)


class MprisSession:
    """A connection to the session bus, and the reads made over it."""

    def __init__(self, bus: Any = None) -> None:
        #: The connection. Passed in only by a test standing in for the session bus;
        #: production builds it in ``connect``.
        self._bus: Any = bus
        #: The properties interface of the player currently subscribed to, if any.
        self._props: Any = None
        self._subscribed_name: str | None = None
        self._on_change: Callable[[str, dict[str, Any], list[str]], None] | None = None

    @property
    def connected(self) -> bool:
        return self._bus is not None

    async def connect(self) -> None:
        from dbus_fast.aio import MessageBus
        from dbus_fast.constants import BusType

        self._bus = await MessageBus(bus_type=BusType.SESSION).connect()

    def close(self) -> None:
        """Release the subscription and the connection. Safe to call twice."""
        self.unsubscribe()
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None

    @staticmethod
    async def ask(what: str, call: Awaitable[Any], default: _T) -> Any | _T:
        """Await one reply, giving up rather than waiting for ever.

        Catching exceptions is not enough on this boundary: silence is not an error
        and would otherwise stall the single poll task indefinitely.
        """
        try:
            return await asyncio.wait_for(call, timeout=DBUS_CALL_TIMEOUT)
        except TimeoutError:
            logger.debug("%s did not answer within %.1fs", what, DBUS_CALL_TIMEOUT)
            return default
        except Exception as exc:  # noqa: BLE001 - D-Bus boundary
            logger.debug("%s failed: %s", what, exc)
            return default

    async def player_names(self) -> list[str]:
        introspection = await self._bus.introspect(DBUS_NAME, DBUS_PATH)
        obj = self._bus.get_proxy_object(DBUS_NAME, DBUS_PATH, introspection)
        names = await obj.get_interface(DBUS_NAME).call_list_names()
        return sorted(name for name in names if name.startswith(MPRIS_PREFIX))

    async def player(self, name: str) -> Any:
        """The Player interface of one player, or None when it cannot be reached."""
        try:
            obj = self._bus.get_proxy_object(name, MPRIS_PATH, MPRIS_INTROSPECTION)
            return obj.get_interface(PLAYER_IFACE)
        except Exception as exc:  # noqa: BLE001 - player may have vanished
            logger.debug("interface %s failed: %s", name, exc)
            return None

    async def status(self, player: Any) -> str:
        return await self.ask("status read", player.get_playback_status(), "")

    async def position(self, player: Any) -> float | None:
        micros = await self.ask("position read", player.get_position(), None)
        return None if micros is None else float(micros) / 1_000_000.0

    async def track(self, player: Any) -> TrackInfo | None:
        metadata = await self.ask("metadata read", player.get_metadata(), None)
        if metadata is None:
            return None
        try:
            return parse_metadata(_unwrap(metadata))
        except Exception as exc:  # noqa: BLE001 - D-Bus boundary
            logger.debug("metadata parse failed while selecting player: %s", exc)
            return None

    async def identity(self) -> str:
        """The display name of the subscribed player, or "" when there is none."""
        if self._props is None:
            return ""
        value = await self.ask("identity read", self._props.call_get(ROOT_IFACE, "Identity"), None)
        return "" if value is None else str(plain_value(value))

    async def describe(self, name: str) -> tuple[str, str, TrackInfo]:
        """Identity, status and track for the picker, each failing on its own.

        The identity read is what makes a player appear in the list at all; the
        status and metadata are only what the row shows beside it. Sharing one
        attempt dropped a reachable player from the picker whenever the optional
        detail failed.
        """
        empty = TrackInfo("", "", "", None, "")
        try:
            obj = self._bus.get_proxy_object(name, MPRIS_PATH, MPRIS_INTROSPECTION)
            props = obj.get_interface(PROPERTIES_IFACE)
            identity = await props.call_get(ROOT_IFACE, "Identity")
        except Exception as exc:  # noqa: BLE001 - player may vanish during discovery
            logger.debug("player identity read failed for %s: %s", name, exc)
            raise LookupError(name) from exc
        identity_text = str(plain_value(identity) or "")
        try:
            values = _unwrap(await props.call_get_all(PLAYER_IFACE))
            return identity_text, str(values.get("PlaybackStatus") or ""), parse_metadata(
                _unwrap(values.get("Metadata", {}))
            )
        except Exception as exc:  # noqa: BLE001 - detail is optional for the row
            logger.debug("player detail read failed for %s: %s", name, exc)
            return identity_text, "", empty

    async def subscribe(
        self, name: str, on_change: Callable[[str, dict[str, Any], list[str]], None]
    ) -> None:
        """Follow one player's property changes, replacing any previous subscription."""
        if name == self._subscribed_name and self._props is not None:
            return
        self.unsubscribe()
        try:
            obj = self._bus.get_proxy_object(name, MPRIS_PATH, MPRIS_INTROSPECTION)
            props = obj.get_interface(PROPERTIES_IFACE)
            props.on_properties_changed(on_change)
            self._props, self._subscribed_name, self._on_change = props, name, on_change
        except Exception as exc:  # noqa: BLE001 - signals are best effort
            logger.debug("subscribe failed for %s: %s", name, exc)
            self._props = self._subscribed_name = self._on_change = None

    def unsubscribe(self) -> None:
        if self._props is not None and self._on_change is not None:
            with contextlib.suppress(Exception):
                self._props.off_properties_changed(self._on_change)
        self._props = self._subscribed_name = self._on_change = None
