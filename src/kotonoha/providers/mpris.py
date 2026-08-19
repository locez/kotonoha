"""Stable MPRIS sampling and ordered external-lyrics resolution."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable
from dataclasses import replace
from typing import Any, Protocol, TypeVar

import aiohttp

from ..config import DEFAULT_LYRICS_SOURCES
from ..lyrics.hint import LyricsHint, from_player
from ..lyrics.match import TrackMetadata
from ..lyrics.resolver import LyricsResolver, ResolvedLyrics
from ..lyrics.select import build_snapshot, find_current_index
from ..model import LyricLine
from ..players import PlayerInfo
from ..state import LyricsState
from .gate import SourceGate
from .mpris_session import MprisSession
from .mpris_track import (
    CumulativeLengthDetector,
    TrackCommit,
    TrackInfo,
    TrackObservation,
    TrackStabilizer,
    lyrics_lookup_reason,
    parse_metadata,
)
from .mpris_track import (
    unwrap as _unwrap,
)
from .player_selection import PlayerRecord, PlayerSelector

logger = logging.getLogger(__name__)

#: How long one D-Bus reply may take. A local method call answers in milliseconds;
#: this is a deadline for a player that never answers at all.
DBUS_CALL_TIMEOUT = 2.0

_T = TypeVar("_T")

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
DBUS_NAME = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
# One second filters out same-poll observation jitter without delaying a deliberate new start.

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


class ResolverLike(Protocol):
    async def resolve(
        self,
        session: Any,
        track: TrackMetadata,
        sources: list[str],
        /,
    ) -> ResolvedLyrics | None: ...

    def reset_memory(self) -> None: ...

    def set_cache_enabled(self, enabled: bool, /) -> None: ...

    def set_prefer_best(self, enabled: bool, /) -> None: ...

    def set_fuzzy(self, enabled: bool, /) -> None: ...

    async def clear_cache(self) -> None: ...

    async def resolve_hint(
        self, session: Any, track: TrackMetadata, sources: list[str], hint: LyricsHint, /
    ) -> ResolvedLyrics | None: ...


def new_lyrics_session() -> aiohttp.ClientSession:
    """The one HTTP session every lyric provider shares.

    Generous session-wide timeout only: each provider sets its own tighter
    per-request budget (netease is fast, lrclib is routinely slow), because a
    single short shared one killed every lrclib fetch — its backend often takes
    7-9s to answer — leaving that whole fallback source silently dead.

    No cookie jar. NetEase sets a cookie on its first search reply, and a request
    carrying it back is answered with an unrelated popular-songs list instead of
    the query's own results. This session lives for the process, so only the first
    search of a run was answered honestly: measured over five identical queries
    for a song that exists, 1/5 with the jar and 5/5 without. No provider here
    authenticates, so nothing needs it.
    """
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20.0, connect=5.0),
        cookie_jar=aiohttp.DummyCookieJar(),
    )


class MprisProvider:
    def __init__(
        self,
        state: LyricsState,
        poll_interval: float = 0.2,
        *,
        lyrics_sources: list[str] | None = None,
        gate: SourceGate | None = None,
        resolver: ResolverLike | None = None,
    ) -> None:
        self._state = state
        self._poll_interval = poll_interval
        self._lyrics_sources = lyrics_sources if lyrics_sources is not None else list(DEFAULT_LYRICS_SOURCES)
        self._gate = gate or SourceGate()
        self._resolver: ResolverLike = resolver or LyricsResolver(gate=self._gate)
        #: Every read of the session bus, each with its own deadline.
        self._session_bus = MprisSession()
        self._session: aiohttp.ClientSession | None = None
        self._task: asyncio.Task[None] | None = None
        self._poll_wakeup = asyncio.Event()
        self._stabilizer = TrackStabilizer()
        self._length_detector = CumulativeLengthDetector()
        self._empty_since: float | None = None
        self._song_offset = 0.0  # subtract from a cumulative playlist/video position
        #: The last Position the player reported, before the offset is taken off it.
        #: Kept so a song that turns out to be placed past its own last line can say
        #: where the player actually thinks it is.
        self._last_raw_position: float | None = None
        self._lines: list[LyricLine] = []
        self._last_index = -2
        #: Which player to follow, and the history that decision needs.
        self._selector = PlayerSelector()
        self._props_iface: Any = None
        self._subscribed_name: str | None = None
        self._load_task: asyncio.Task[None] | None = None
        self._load_tasks: set[asyncio.Task[None]] = set()
        self._current_commit: TrackCommit | None = None
        self._content_owner = "none"
        self._provider_name = ""
        self._cache_enabled = True
        self._prefer_best = True
        self._fuzzy = True
        self._gate_revision = self._gate.revision
        self._calibration_generation: int | None = None
        self._calibration_until: float = 0.0
        self._calibration_offset: float | None = None

    def set_lyrics_sources(self, sources: list[str]) -> None:
        updated = list(sources)
        if updated == self._lyrics_sources:
            return
        self._lyrics_sources = updated
        self._resolver.reset_memory()
        self._force_reload()

    def set_player_lock(self, bus_name: str) -> None:
        updated = bus_name if isinstance(bus_name, str) else ""
        if updated == self._selector.lock:
            return
        self._selector.lock = updated
        self._poll_wakeup.set()

    async def available_players(self) -> list[PlayerInfo]:
        if not self._session_bus.connected:
            return []
        result: list[PlayerInfo] = []
        records: list[PlayerRecord] = []
        for name in await self._session_bus.player_names():
            try:
                identity, status, info = await self._session_bus.describe(name)
            except LookupError:
                continue
            records.append(PlayerRecord(None, name, status, info))
            result.append(PlayerInfo(name, identity, info.title, info.artist, status))
        automatic_name = self._selector.automatic_name(records)
        return [
            PlayerInfo(p.bus_name, p.identity, p.title, p.artist, p.playback_status, p.bus_name == automatic_name)
            for p in result
        ]

    def set_cache_enabled(self, enabled: bool) -> None:
        updated = bool(enabled)
        if updated == self._cache_enabled:
            return
        self._cache_enabled = updated
        self._resolver.set_cache_enabled(updated)
        self._force_reload()

    def set_prefer_best(self, enabled: bool) -> None:
        updated = bool(enabled)
        if updated == self._prefer_best:
            return
        self._prefer_best = updated
        self._resolver.set_prefer_best(updated)
        self._force_reload()

    def set_fuzzy(self, enabled: bool) -> None:
        updated = bool(enabled)
        if updated == self._fuzzy:
            return
        self._fuzzy = updated
        self._resolver.set_fuzzy(updated)
        self._force_reload()

    async def clear_cache(self) -> None:
        await self._resolver.clear_cache()

    async def start(self) -> None:
        await self._session_bus.connect()
        self._session = new_lyrics_session()
        self._task = asyncio.create_task(self._run())
        logger.info("MPRIS provider started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        tasks = tuple(self._load_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._load_task = None

        if self._session is not None:
            await self._session.close()
            self._session = None
        self._session_bus.close()

    async def _run(self) -> None:
        try:
            while True:
                self._poll_wakeup.clear()
                try:
                    await self._poll_once()
                except Exception as exc:  # noqa: BLE001 - D-Bus boundary; keep polling
                    logger.debug("MPRIS poll error: %s", exc)
                try:
                    await asyncio.wait_for(self._poll_wakeup.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass

    async def _ask(what: str, call: Awaitable[Any], default: _T) -> Any | _T:
        """Await one D-Bus reply, giving up rather than waiting for ever.

        Catching exceptions is not enough on this boundary: a player that owns its
        bus name and simply never answers is not an error, it is silence, and this
        provider has exactly one poll task. Without a deadline that task waits
        inside the call and every other player stops being looked at too.
        """
        try:
            return await asyncio.wait_for(call, timeout=DBUS_CALL_TIMEOUT)
        except TimeoutError:
            logger.debug("%s did not answer within %.1fs", what, DBUS_CALL_TIMEOUT)
            return default
        except Exception as exc:  # noqa: BLE001 - D-Bus boundary
            logger.debug("%s failed: %s", what, exc)
            return default

    async def _safe_status(player: Any) -> str:
        return await MprisProvider._ask("status read", player.get_playback_status(), "")

    async def _safe_info(player: Any) -> TrackInfo | None:
        metadata = await MprisProvider._ask("metadata read", player.get_metadata(), None)
        if metadata is None:
            return None
        try:
            return parse_metadata(_unwrap(metadata))
        except Exception as exc:  # noqa: BLE001 - D-Bus boundary
            logger.debug("metadata parse failed while selecting player: %s", exc)
            return None

    async def _active_player(self, *, now: float | None = None) -> tuple[Any, str] | None:
        observed_at = time.monotonic() if now is None else now
        names = await self._session_bus.player_names()
        self._selector.forget_absent(set(names))
        ordered = self._selector.order_to_poll(names)

        collected: list[PlayerRecord] = []
        for name in ordered:
            player = await self._session_bus.player(name)
            if player is None:
                self._selector.observe(name, "", observed_at)
                continue
            status = await self._session_bus.status(player)
            self._selector.observe(name, status, observed_at)
            if status not in {"Playing", "Paused"}:
                continue
            info = await self._session_bus.track(player)
            if info is None and name != self._selector.lock:
                continue
            if info is None:
                info = TrackInfo("", "", "", None, "")
            # Collected in poll order, with the current player already moved to the
            # front, so the shared policy sees the same ordering the picker gives it.
            collected.append(PlayerRecord(player, name, status, info))

        selected = self._selector.choose(collected)
        if selected is None:
            self._selector.current_name = None
            return None
        self._selector.current_name = selected.bus_name
        return selected.player, selected.bus_name

    async def _ensure_subscribed(self, name: str) -> None:
        await self._session_bus.subscribe(name, self._on_props_changed)

    def _on_props_changed(self, interface: str, changed: dict[str, Any], invalidated: list[str]) -> None:
        if interface != PLAYER_IFACE:
            return
        interesting = {"Metadata", "PlaybackStatus"}
        if interesting.intersection(changed) or interesting.intersection(invalidated):
            self._poll_wakeup.set()

    async def _poll_once(self, *, now: float | None = None) -> None:
        observed_at = time.monotonic() if now is None else now
        active = await self._active_player(now=observed_at)
        if active is None:
            self._handle_no_player(observed_at)
            return

        player, name = active
        await self._ensure_subscribed(name)
        status = await self._session_bus.status(player)
        if status not in {"Playing", "Paused"}:
            self._handle_no_player(observed_at)
            return

        try:
            identity = await self._session_bus.identity()
            first_info = parse_metadata(_unwrap(await player.get_metadata()))
        except Exception as exc:  # noqa: BLE001 - D-Bus boundary
            logger.debug("metadata sample failed: %s", exc)
            return

        position: float | None = None
        try:
            raw_position = await player.get_position()
            if isinstance(raw_position, (int, float)) and not isinstance(raw_position, bool):
                position = float(raw_position) / 1_000_000.0
                self._last_raw_position = position
        except Exception as exc:  # noqa: BLE001 - Position is optional
            logger.debug("position read failed: %s", exc)

        try:
            second_info = parse_metadata(_unwrap(await player.get_metadata()))
        except Exception as exc:  # noqa: BLE001 - D-Bus boundary
            logger.debug("metadata verification failed: %s", exc)
            return
        if first_info.identity_key != second_info.identity_key:
            self._stabilizer.observe(
                TrackObservation(
                    player_name=name,
                    info=TrackInfo("", "", "", None, ""),
                    playback_status=status,
                    position_s=position,
                    observed_at=observed_at,
                )
            )
            self._poll_wakeup.set()
            return

        info = second_info
        observation = TrackObservation(name, info, status, position, observed_at, identity)
        commit = self._stabilizer.observe(observation)
        if not info.title and not info.artist:
            if status == "Playing":
                self._empty_since = None
            return
        self._empty_since = None

        if commit is not None:
            self._schedule_load(commit)

        if position is not None and not self._stabilizer.transitioning:
            current = self._current_commit
            if current is not None:
                self._calibrate_offset(current, position, observed_at)

        if not self._stabilizer.transitioning:
            self._ensure_content_owner()
        if self._stabilizer.transitioning or self._content_owner != "external":
            return

        current = self._current_commit
        if current is None:
            return
        playing = status == "Playing"
        if position is not None:
            position = max(0.0, position - self._song_offset)  # song-relative (no-op when offset ~0)
        cider_timing = self._gate.current_timing(current.info.metadata())
        if cider_timing is not None and cider_timing.current_time is not None:
            position = cider_timing.current_time  # already song-relative; ignore the offset
            if cider_timing.is_playing is not None:
                playing = cider_timing.is_playing
        if position is None:
            return
        self._state.tick(position, playing)
        index = find_current_index(self._lines, position)
        if index != self._last_index:
            self._last_index = index
            self._emit(current.info, position, playing)

    def _handle_no_player(self, now: float) -> None:
        if self._current_commit is None and self._content_owner == "none":
            return
        if self._empty_since is None:
            self._empty_since = now
            return
        if now - self._empty_since >= 0.35:
            self._reset()

    def _schedule_load(self, commit: TrackCommit) -> None:
        current = self._current_commit
        if current is not None and commit != current and commit.generation <= current.generation:
            commit = TrackCommit(
                current.generation + 1,
                commit.player_name,
                commit.info,
                commit.start_position,
                commit.player_identity,
            )
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        # A transition carries the song's start position; adopt it as the offset so
        # the sweep uses song-relative time. Reloads of the same song (start_position
        # None, e.g. a source/cache change) keep the current offset.
        if commit.start_position is not None:
            self._song_offset = commit.start_position
            # For song-relative players, the Position reset may arrive after the stabilizer's
            # settle window has closed. Open a generation-bound short window to continue
            # observing raw Position; if it drops below the offset threshold within this
            # window, it means the committed offset was captured from the previous song's
            # stale position — so correct the offset to 0.
            if commit.start_position > 0.0:
                self._calibration_generation = commit.generation
                self._calibration_until = time.monotonic() + 2.0
                self._calibration_offset = commit.start_position
            else:
                self._calibration_generation = None
                self._calibration_offset = None
        self._current_commit = commit
        self._content_owner = "resolving"
        task = asyncio.create_task(self._load_song(commit))
        self._load_task = task
        self._load_tasks.add(task)
        task.add_done_callback(self._load_finished)

    def _load_finished(self, task: asyncio.Task[None]) -> None:
        self._load_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning("MPRIS lyrics load failed: %s", error)

    async def _load_song(self, commit: TrackCommit) -> None:
        self._lines = []
        self._last_index = -2
        self._provider_name = ""
        self._gate.select_external()
        self._state.update(
            build_snapshot(
                [],
                0.0,
                provider="MPRIS",
                song_id=None,
                title=commit.info.title,
                artist=commit.info.artist,
                is_playing=True,
            )
        )
        # Resolve the duration before the gate, not after: a browser often reports
        # none at all while Cider knows the real length, and running the gate first
        # let a 2-hour stream through on a missing MPRIS length.
        info = commit.info
        # Judge the player's own reading before any correction: the evidence for a
        # session counter is how that number moves, not what another source knows.
        length_trusted = self._length_detector.observe(
            commit.player_identity, info.track_id, info.length_s, time.monotonic()
        )
        cider_timing = self._gate.current_timing(info.metadata())
        if cider_timing is not None and cider_timing.duration_s is not None:
            if cider_timing.duration_s != info.length_s:
                logger.debug(
                    "Using matching Cider duration %.3fs instead of MPRIS %s",
                    cider_timing.duration_s,
                    info.length_s,
                )
            info = replace(info, length_s=cider_timing.duration_s)
        elif not length_trusted and info.length_s is not None:
            logger.info(
                "Ignoring %r's length %.0fs for %r: it advances with the clock, so it "
                "counts session playtime rather than this track",
                commit.player_name,
                info.length_s,
                info.title,
            )
            info = replace(info, length_s=None)

        skip_reason = lyrics_lookup_reason(info)
        if skip_reason is not None:
            # A 14-hour compilation is not a song; querying every provider for it
            # costs traffic and can match a title that merely appears inside it.
            logger.info("Skipping lyric lookup for %r: %s", info.title, skip_reason)
            self._content_owner = "none"
            return
        track = info.metadata()
        try:
            hint = from_player(
                commit.player_identity, commit.player_name, commit.info.track_id, commit.info.url
            )
            result = (
                await self._resolver.resolve_hint(self._session, track, self._lyrics_sources, hint)
                if hint is not None
                else None
            )
            if result is None:
                result = await self._resolver.resolve(self._session, track, self._lyrics_sources)
        except asyncio.CancelledError:
            raise
        if self._current_commit != commit:
            return
        if result is None:
            self._content_owner = "none"
            if not self._select_late_cider():
                # A miss left no trace at all: one night's log held 47 hits and 176
                # skips and nothing for the songs that were asked for and not found,
                # so "never queried" and "queried and absent" looked identical from
                # the outside. They call for opposite fixes.
                logger.info(
                    "MPRIS %r / %r -> no lyrics from %s",
                    commit.info.title,
                    commit.info.artist,
                    ", ".join(self._lyrics_sources) or "no source",
                )
            return
        if result.source == "cider" and result.live_snapshot is not None:
            self._content_owner = "cider"
            self._provider_name = "cider"
            self._gate_revision = self._gate.revision
            self._state.update(result.live_snapshot)
            return
        if self._select_late_cider(before_source=result.source):
            return
        self._content_owner = "external"
        self._provider_name = result.source
        self._gate_revision = self._gate.revision
        self._lines = list(result.lines)
        self._recalibrate_against(commit, result.lines, result.duration_s)
        logger.info(
            "MPRIS %r / %r -> %d %s lines",
            commit.info.title,
            commit.info.artist,
            len(self._lines),
            result.source,
        )

    def _recalibrate_against(
        self, commit: TrackCommit, lines: tuple[LyricLine, ...], song_length: float | None = None
    ) -> None:
        """Place a song whose player counts the whole session, not the track.

        The first track after start has no join point to subtract — the stabilizer
        finds one by comparing a track against the one before it, and there is none —
        so a player whose Position runs across the queue, as the Plasma browser
        bridge does, puts a song that has just begun tens of minutes into its own
        lyrics. There it reads as finished: no line is current, and the marker for
        after the last line has nothing left to count.

        Such a player shifts its Position and its Length by the same amount, so what
        remains of the track is right even when neither number is: 3776.7s against
        3745.4s reported, for a song 207s long playing at 176s. The shift is
        therefore the difference between the length claimed and the length the song
        actually is, and the last line is the closest the lyrics can say — two
        seconds out on that track, against the whole song by starting from here.
        """
        if self._song_offset != 0.0 or not lines:
            return
        position, claimed = self._last_raw_position, commit.info.length_s
        if position is None or position <= lines[-1].end:
            return
        if claimed is None or claimed <= lines[-1].end:
            # Nothing to measure the shift against; leaving the offset alone keeps a
            # song that cannot be placed from being placed wrongly.
            logger.info(
                "MPRIS position %.0fs is past the last line at %.0fs and the reported "
                "length cannot say by how much; leaving the song unplaced",
                position,
                lines[-1].end,
            )
            return
        # The catalogue knows how long the recording is; the last line only knows
        # where the words stop, which is short by however long the outro runs — and
        # every line is then out by that much.
        actual = song_length if song_length is not None and song_length > lines[-1].end else lines[-1].end
        shift = claimed - actual
        logger.info(
            "MPRIS reports %.0fs of %.0fs for a %.0fs song; treating both as running "
            "totals and shifting by %.0fs",
            position,
            claimed,
            actual,
            shift,
        )
        self._song_offset = shift
        self._last_index = -2

    def _force_reload(self) -> None:
        current = self._current_commit
        if current is None:
            return
        self._schedule_load(
            TrackCommit(
                current.generation + 1,
                current.player_name,
                current.info,
                player_identity=current.player_identity,
            )
        )

    def _ensure_content_owner(self) -> None:
        if self._content_owner == "cider" and not self._gate.cider_active:
            self._force_reload()
            return
        if self._content_owner != "none" or self._current_commit is None:
            return
        self._select_late_cider()

    def _select_late_cider(self, *, before_source: str | None = None) -> bool:
        if self._current_commit is None:
            return False
        revision = self._gate.revision
        if revision == self._gate_revision:
            return False
        self._gate_revision = revision
        if "cider" not in self._lyrics_sources:
            return False
        if before_source is not None:
            try:
                if self._lyrics_sources.index("cider") >= self._lyrics_sources.index(before_source):
                    return False
            except ValueError:
                return False
        match = self._gate.current_match(self._current_commit.info.metadata())
        if match is None:
            return False
        self._gate.select_cider(match.client_id)
        self._content_owner = "cider"
        self._provider_name = "cider"
        self._state.update(match.snapshot)
        return True

    def _emit(self, info: TrackInfo, position: float, playing: bool) -> None:
        provider = f"MPRIS:{self._provider_name}" if self._provider_name else "MPRIS"
        self._state.update(
            build_snapshot(
                self._lines,
                position,
                provider=provider,
                song_id=None,
                title=info.title,
                artist=info.artist,
                is_playing=playing,
                duration_s=info.length_s,
            )
        )

    def _calibrate_offset(self, commit: TrackCommit, raw_position: float, observed_at: float) -> None:
        if (
            self._calibration_generation == commit.generation
            and observed_at <= self._calibration_until
            and self._calibration_offset is not None
            and raw_position < self._calibration_offset - 0.5
        ):
            logger.debug(
                "MPRIS calibration: offset %.3fs -> 0.0 (raw %.3fs, gen %d)",
                self._calibration_offset,
                raw_position,
                commit.generation,
            )
            self._song_offset = 0.0
            self._last_index = -2
            self._calibration_generation = None
            self._calibration_offset = None

    def _reset(self) -> None:
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        self._stabilizer.reset()
        self._current_commit = None
        self._lines = []
        self._last_index = -2
        self._content_owner = "none"
        self._provider_name = ""
        self._empty_since = None
        self._song_offset = 0.0
        self._calibration_generation = None
        self._calibration_offset = None
        self._gate.select_standalone()
        self._gate_revision = self._gate.revision
        self._state.clear()


async def probe() -> None:
    session = MprisSession()
    await session.connect()
    players = await session.player_names()
    if not players:
        print("No MPRIS players found. Start a player (browser YTM / Spotify / VLC) and retry.")
        return

    print(f"Found {len(players)} MPRIS player(s): {', '.join(players)}")
    for name in players:
        print(f"\n=== {name} ===")
        try:
            player = await session.player(name)
            status = await player.get_playback_status()
            info = parse_metadata(_unwrap(await player.get_metadata()))
            print(f"  status   = {status}")
            print(f"  title    = {info.title!r}")
            print(f"  artist   = {info.artist!r}")
            print(f"  length   = {info.length_s}s")
            print("  Position once/sec - does delta advance about 1.0 while playing?")
            last: float | None = None
            for _ in range(6):
                try:
                    pos_s = (await player.get_position()) / 1_000_000.0
                except Exception as exc:  # noqa: BLE001 - diagnostic command
                    print(f"    Position read failed: {exc}")
                    break
                delta = "" if last is None else f"   delta = {pos_s - last:+.3f}"
                print(f"    position = {pos_s:8.3f}s{delta}")
                last = pos_s
                await asyncio.sleep(1.0)
        except Exception as exc:  # noqa: BLE001 - diagnostic command
            print(f"  error reading player: {exc}")


def main() -> None:
    asyncio.run(probe())


if __name__ == "__main__":
    main()
