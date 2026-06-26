"""MPRIS provider — M1: discovery + a Position probe.

Connects to the session bus, enumerates ``org.mpris.MediaPlayer2.*`` players and
reads track metadata + playback position. The ``probe`` entry point
(``python -m kotonoha.providers.mpris``) prints each player's metadata and
samples ``Position`` once a second, so we can verify on the target machine
whether a player — notably browser YouTube Music via Plasma Browser Integration
/ playerctld — reports a Position that actually advances. That ground-truth check
is the foundation of the whole MPRIS lyrics feature.

D-Bus needs a real session bus + a running player, so the live parts are
validated by the user, not in CI. The metadata parsing (`parse_metadata`) is a
pure function and is unit-tested. dbus-fast is imported lazily so the pure parts
import without it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from ..config import DEFAULT_LYRICS_SOURCES
from ..lyrics import lrclib, netease
from ..lyrics.select import build_snapshot, find_current_index
from ..model import LyricLine
from ..state import LyricsState
from .gate import SourceGate

logger = logging.getLogger(__name__)

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
DBUS_NAME = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"

# Some players (Chromium/Edge) don't declare the Player interface in their own
# introspection even though they implement it, so dbus-fast can't find it. We
# supply the standard MPRIS introspection ourselves instead of trusting theirs.
MPRIS_INTROSPECTION = """<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
  <interface name="org.freedesktop.DBus.Properties">
    <method name="Get">
      <arg name="interface_name" type="s" direction="in"/>
      <arg name="property_name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="GetAll">
      <arg name="interface_name" type="s" direction="in"/>
      <arg name="props" type="a{sv}" direction="out"/>
    </method>
    <signal name="PropertiesChanged">
      <arg name="interface_name" type="s"/>
      <arg name="changed_properties" type="a{sv}"/>
      <arg name="invalidated_properties" type="as"/>
    </signal>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Position" type="x" access="read"/>
    <property name="Rate" type="d" access="read"/>
    <signal name="Seeked">
      <arg name="Position" type="x"/>
    </signal>
  </interface>
</node>"""


@dataclass(frozen=True)
class TrackInfo:
    title: str
    artist: str
    album: str
    length_s: float | None
    track_id: str


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " / ".join(str(v) for v in value if isinstance(v, str))
    return ""


def parse_metadata(raw: dict[str, Any]) -> TrackInfo:
    """Build a :class:`TrackInfo` from an MPRIS metadata dict (Variants unwrapped)."""
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


def _unwrap(metadata: dict[str, Any]) -> dict[str, Any]:
    """Unwrap dbus-fast Variant values (each has ``.value``) to plain Python."""
    return {key: getattr(variant, "value", variant) for key, variant in metadata.items()}


# --- live D-Bus (validated by the user) ---


async def _connect() -> Any:
    from dbus_fast.aio import MessageBus
    from dbus_fast.constants import BusType

    return await MessageBus(bus_type=BusType.SESSION).connect()


async def list_players(bus: Any) -> list[str]:
    introspection = await bus.introspect(DBUS_NAME, DBUS_PATH)
    obj = bus.get_proxy_object(DBUS_NAME, DBUS_PATH, introspection)
    iface = obj.get_interface(DBUS_NAME)
    names = await iface.call_list_names()
    return sorted(n for n in names if n.startswith(MPRIS_PREFIX))


async def _player_interface(bus: Any, name: str) -> Any:
    # Use our own standard introspection, not the player's (which may omit Player).
    obj = bus.get_proxy_object(name, MPRIS_PATH, MPRIS_INTROSPECTION)
    return obj.get_interface(PLAYER_IFACE)


class MprisProvider:
    """Drives the overlay from an MPRIS player + external timed lyrics.

    Polls the active player (Playing preferred) every ``poll_interval`` seconds:
    re-calibrates the clock with the real Position (tick), fetches lyrics on a
    track change, and emits a new snapshot only when the current line changes.
    All live D-Bus work is validated by the user; pure parts are tested.
    """

    def __init__(
        self,
        state: LyricsState,
        poll_interval: float = 0.2,
        *,
        lyrics_sources: list[str] | None = None,
        gate: SourceGate | None = None,
    ) -> None:
        self._state = state
        self._poll_interval = poll_interval
        self._lyrics_sources = lyrics_sources if lyrics_sources is not None else list(DEFAULT_LYRICS_SOURCES)
        self._gate = gate
        self._bus: Any = None
        self._session: aiohttp.ClientSession | None = None
        self._task: asyncio.Task[None] | None = None
        self._lines: list[LyricLine] = []
        self._song_key: str | None = None
        self._last_index: int = -2
        self._current_name: str | None = None  # sticky active player
        self._props_iface: Any = None
        self._subscribed_name: str | None = None
        self._load_lock = asyncio.Lock()

    def set_lyrics_sources(self, sources: list[str]) -> None:
        self._lyrics_sources = list(sources)
        self._song_key = None  # force a re-resolve with the new priority on next poll

    async def start(self) -> None:
        self._bus = await _connect()
        self._session = aiohttp.ClientSession()
        self._task = asyncio.ensure_future(self._run())
        logger.info("MPRIS provider started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._session is not None:
            await self._session.close()
            self._session = None
        if self._props_iface is not None:
            with contextlib.suppress(Exception):
                self._props_iface.off_properties_changed(self._on_props_changed)
            self._props_iface = None
            self._subscribed_name = None
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None

    async def _run(self) -> None:
        try:
            while True:
                try:
                    await self._poll_once()
                except Exception as exc:  # noqa: BLE001 - D-Bus calls fail in many ways; keep polling
                    logger.debug("MPRIS poll error: %s", exc)
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            pass

    async def _safe_iface(self, name: str) -> Any:
        try:
            return await _player_interface(self._bus, name)
        except Exception as exc:  # noqa: BLE001 - player may have vanished
            logger.debug("interface %s failed: %s", name, exc)
            return None

    @staticmethod
    async def _safe_status(player: Any) -> str:
        try:
            return await player.get_playback_status()
        except Exception as exc:  # noqa: BLE001
            logger.debug("status read failed: %s", exc)
            return ""

    async def _active_player(self) -> tuple[Any, str] | None:
        """Pick the active player, **stickily**.

        Keep the current player while it is still Playing so that a second player
        (another browser tab, Cider's built-in Chrome) does not cause flip-flop
        switching. Only when the current one is not playing do we move to another
        Playing player; otherwise fall back to the first usable one.
        """
        names = await list_players(self._bus)

        if self._current_name in names:
            player = await self._safe_iface(self._current_name)
            if player is not None and await self._safe_status(player) == "Playing":
                return player, self._current_name

        fallback: tuple[Any, str] | None = None
        for name in names:
            player = await self._safe_iface(name)
            if player is None:
                continue
            if await self._safe_status(player) == "Playing":
                self._current_name = name
                return player, name
            if fallback is None:
                fallback = (player, name)

        if fallback is not None:
            self._current_name = fallback[1]
            return fallback
        self._current_name = None
        return None

    async def _ensure_subscribed(self, name: str) -> None:
        """Subscribe to the active player's PropertiesChanged so metadata/track
        changes arrive immediately, even when Get(Metadata) lags (Spotify, browser
        integrations). Polling stays as a fallback."""
        if name == self._subscribed_name and self._props_iface is not None:
            return
        if self._props_iface is not None:
            with contextlib.suppress(Exception):
                self._props_iface.off_properties_changed(self._on_props_changed)
            self._props_iface = None
        try:
            obj = self._bus.get_proxy_object(name, MPRIS_PATH, MPRIS_INTROSPECTION)
            props = obj.get_interface("org.freedesktop.DBus.Properties")
            props.on_properties_changed(self._on_props_changed)
            self._props_iface = props
            self._subscribed_name = name
        except Exception as exc:  # noqa: BLE001 - signals are best-effort; polling still works
            logger.debug("subscribe failed for %s: %s", name, exc)
            self._props_iface = None
            self._subscribed_name = None

    def _on_props_changed(self, interface: str, changed: dict[str, Any], _invalidated: list[str]) -> None:
        if interface != PLAYER_IFACE or "Metadata" not in changed:
            return
        try:
            info = parse_metadata(_unwrap(changed["Metadata"].value))
        except Exception as exc:  # noqa: BLE001
            logger.debug("signal metadata parse failed: %s", exc)
            return
        name = self._subscribed_name
        if not name:
            return
        key = f"{info.track_id}|{info.title}|{info.artist}"
        if key != self._song_key:
            self._song_key = key  # claim synchronously to dedupe against the poll loop
            asyncio.ensure_future(self._load_song(info, key, name))

    async def _poll_once(self) -> None:
        active = await self._active_player()
        if active is None:
            if self._song_key is not None:
                self._reset()
            return
        player, name = active
        await self._ensure_subscribed(name)
        playing = await self._safe_status(player) == "Playing"
        info = parse_metadata(_unwrap(await player.get_metadata()))
        position = (await player.get_position()) / 1_000_000.0

        # Fallback to the PropertiesChanged signal: keyed on trackid+title+artist
        # so any change counts. Most switches come via the signal, not here.
        key = f"{info.track_id}|{info.title}|{info.artist}"
        if key != self._song_key:
            self._song_key = key
            await self._load_song(info, key, name)

        self._state.tick(position, playing)
        index = find_current_index(self._lines, position)
        if index != self._last_index:
            self._last_index = index
            self._emit(info, position, playing)

    async def _load_song(self, info: TrackInfo, key: str, player_name: str) -> None:
        # song_key is claimed by the caller (poll loop or signal handler). The lock
        # serialises concurrent loads (signal vs poll); the stale check drops a
        # result if a newer switch claimed song_key while we were fetching.
        async with self._load_lock:
            self._lines = []
            self._last_index = -2
            # Ignore WS-pushed lyrics while switching, so a stale push from the
            # previous song can't overwrite the new one during the async fetch.
            if self._gate is not None:
                self._gate.set_accept_ws(False)
            # Show the title immediately while lyrics are fetched.
            self._state.update(
                build_snapshot(
                    [], 0.0, provider="MPRIS", song_id=None,
                    title=info.title, artist=info.artist, is_playing=True,
                )
            )

            lines, accept_ws = await self._resolve_lyrics(info, player_name)
            if self._song_key != key:
                return  # a newer switch claimed the song; this result is stale
            self._lines = lines
            if self._gate is not None:
                self._gate.set_accept_ws(accept_ws)
            logger.info(
                "MPRIS %r / %r -> %d lines (accept_ws=%s)", info.title, info.artist, len(lines), accept_ws
            )

    async def _is_cider(self, name: str) -> bool:
        """Cider is an Electron app whose bus name is often 'chromium…' — so check
        the MPRIS Identity property, not just the bus name."""
        if "cider" in name.lower():
            return True
        try:
            obj = self._bus.get_proxy_object(name, MPRIS_PATH, MPRIS_INTROSPECTION)
            props = obj.get_interface("org.freedesktop.DBus.Properties")
            variant = await props.call_get("org.mpris.MediaPlayer2", "Identity")
            identity = str(getattr(variant, "value", variant))
        except Exception as exc:  # noqa: BLE001 - identity is best-effort
            logger.debug("identity read failed for %s: %s", name, exc)
            return False
        return "cider" in identity.lower()

    async def _resolve_lyrics(self, info: TrackInfo, player_name: str) -> tuple[list[LyricLine], bool]:
        """Walk the priority order; first source with lyrics wins (hit-and-stop).

        Returns (lines, accept_ws). ``accept_ws`` is True when the order reached
        the 'cider' source (its player is the one playing) before any pull source
        had lyrics — meaning the Cider WS push should drive this song.
        """
        if self._session is None or not info.title:
            return [], False
        is_cider = await self._is_cider(player_name)
        for source in self._lyrics_sources:
            if source == "cider":
                if is_cider:
                    return [], True  # hand off to the Cider WS push
                continue  # not the Cider player -> this source isn't available
            if source == "netease":
                lines = await netease.fetch(self._session, info.title, info.artist, info.length_s)
            elif source == "lrclib":
                lines = await lrclib.fetch(self._session, info.title, info.artist, info.length_s)
            else:
                continue
            if lines:
                return lines, False
        return [], False

    def _emit(self, info: TrackInfo, position: float, playing: bool) -> None:
        self._state.update(
            build_snapshot(
                self._lines,
                position,
                provider="MPRIS:netease",
                song_id=None,
                title=info.title,
                artist=info.artist,
                is_playing=playing,
            )
        )

    def _reset(self) -> None:
        self._song_key = None
        self._lines = []
        self._last_index = -2
        self._state.clear()


async def probe() -> None:
    bus = await _connect()
    players = await list_players(bus)
    if not players:
        print("No MPRIS players found. Start a player (browser YTM / Spotify / VLC) and retry.")
        return

    print(f"Found {len(players)} MPRIS player(s): {', '.join(players)}")
    for name in players:
        print(f"\n=== {name} ===")
        try:
            player = await _player_interface(bus, name)
            status = await player.get_playback_status()
            info = parse_metadata(_unwrap(await player.get_metadata()))
            print(f"  status   = {status}")
            print(f"  title    = {info.title!r}")
            print(f"  artist   = {info.artist!r}")
            print(f"  length   = {info.length_s}s")
            print("  Position once/sec — does Δ advance ~1.0 while playing?")
            last: float | None = None
            for _ in range(6):
                try:
                    pos_s = (await player.get_position()) / 1_000_000.0
                except Exception as exc:  # noqa: BLE001 - diagnostic tool, report and move on
                    print(f"    Position read failed: {exc}")
                    break
                delta = "" if last is None else f"   Δ = {pos_s - last:+.3f}"
                print(f"    position = {pos_s:8.3f}s{delta}")
                last = pos_s
                await asyncio.sleep(1.0)
        except Exception as exc:  # noqa: BLE001 - diagnostic tool, report and move on
            print(f"  error reading player: {exc}")


def main() -> None:
    asyncio.run(probe())


if __name__ == "__main__":
    main()
