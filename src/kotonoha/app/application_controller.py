"""Application controller: owns the long-lived objects and wires interactions.

Separated from main.py so the wiring is import-testable without spinning up a
real Qt event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable, Coroutine

from ..async_task import create_owned_task, wait_for_owned
from ..config import Config
from ..lyrics.cache import LyricsCacheError
from ..lyrics.match import TrackMetadata
from ..lyrics.search import LyricsSearchPort, LyricsSearchQuery, LyricsSearchResult
from ..providers.mpris_session import MprisSessionError
from .cache_management import CacheManagementController
from .components import (
    ApplicationComponents,
    ApplicationQuitPort,
    CiderPort,
    ConfigServicePort,
    DisplayLifecyclePort,
    MprisPort,
    OverlayPort,
    ReceiverPort,
    RestartLauncher,
    RuntimeConfigPort,
    TrackOffsetPort,
    TrayPort,
)
from .intents import (
    ApplyConfig,
    ChangePosition,
    ChangeTrackOffset,
    ClearCache,
    DeleteCacheEntries,
    OpenCacheManagement,
    RequestRestart,
    SearchCache,
    SettingsIntent,
)
from .lifecycle import TaskSupervisor
from .lyrics_search import LyricsSearchController
from .services import display_options
from .settings_port import SettingsDialogFactory, SettingsDialogPort

logger = logging.getLogger(__name__)


class AppController:
    """Own one composed application's lifecycle and typed intent routing."""

    def __init__(self, quit_port: ApplicationQuitPort, components: ApplicationComponents) -> None:
        """Own application lifecycle and intent routing for one composed graph."""
        self._quit_port: ApplicationQuitPort = quit_port
        self._restart_launcher: RestartLauncher = components.restart_launcher
        self._config_service: ConfigServicePort = components.config_service
        self._track_offsets: TrackOffsetPort = components.track_offsets
        self._display: DisplayLifecyclePort = components.display
        self._overlay: OverlayPort = components.overlay
        self._receiver: ReceiverPort = components.receiver
        self._cider: CiderPort = components.cider
        self._mpris: MprisPort = components.mpris
        self._tray: TrayPort = components.tray
        self._runtime_config: RuntimeConfigPort = components.runtime_config
        self._settings_factory: SettingsDialogFactory = components.settings_factory
        self._lyrics_search_service: LyricsSearchPort = components.lyrics_search
        self._lyrics_search: LyricsSearchController = LyricsSearchController(
            components.lyrics_search,
            components.lyrics_cache_writer,
            components.lyrics_search_factory,
            on_applied=self._apply_selected_lyrics,
            status_provider=self._display.current_lyrics_status,
        )
        self._cache_management: CacheManagementController = CacheManagementController(
            components.lyrics_cache,
            components.cache_management_factory,
        )
        self._settings_tasks: TaskSupervisor = TaskSupervisor("settings")
        self._config: Config = self._config_service.config
        self._settings_dialog: SettingsDialogPort | None = None
        self._settings_open_task: asyncio.Task[None] | None = None
        self._lifecycle_lock: asyncio.Lock = asyncio.Lock()
        self._started: bool = False
        self._stopped: bool = False

        self._overlay.passthrough_toggle_requested.connect(self._toggle_passthrough)
        self._overlay.settings_requested.connect(self._open_settings)
        self._overlay.lyrics_search_requested.connect(self._open_lyrics_search)
        self._overlay.position_changed.connect(self._handle_intent)
        self._overlay.track_offset_changed.connect(self._handle_intent)

    async def start(self) -> None:
        """Start the composed providers and presentation workflow once."""
        async with self._lifecycle_lock:
            if self._stopped:
                raise RuntimeError("application controller is stopped")
            if self._started:
                return
            startup_succeeded = False
            try:
                # Promote to a layer surface BEFORE show(): once the window is mapped as a
                # normal xdg surface, LayerShellQt can no longer convert it.
                self._overlay.activate_layer_shell()
                self._overlay.show()
                self._tray.show()
                await self._display.start()
                await self._lyrics_search_service.start()
                # The generic adapter receiver is optional: a port bind failure — a stale
                # instance or double-launch already holding 28745 — must only disable
                # external WS adapters, not take down the overlay/tray.
                try:
                    await self._receiver.start()
                except OSError as exc:
                    logger.warning("External adapter receiver unavailable: %s", exc)
                try:
                    await self._cider.start()
                except OSError as exc:
                    logger.warning("Cider API provider unavailable: %s", exc)
                # MPRIS is best-effort: a missing session bus / dbus must not stop the app.
                try:
                    await self._mpris.start()
                except (MprisSessionError, OSError) as exc:
                    logger.warning("MPRIS provider unavailable: %s", exc)
                startup_succeeded = True
            finally:
                if not startup_succeeded:
                    # A startup failure is terminal for this composed graph.
                    # Cleanup runs for every exception and cancellation without
                    # replacing the original failure with a catch-all handler.
                    await self._stop_locked()
            self._started = True
            logger.info("Kotonoha started on port %d", self._config.port)

    async def stop(self) -> None:
        """Stop owned producers in order and release every composed resource."""
        async with self._lifecycle_lock:
            if self._stopped:
                return
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        """Release the graph while the lifecycle lock is already held."""
        cancellation_requested = await self._stop_component("settings tasks", self._finish_settings_open)
        if self._settings_dialog is not None:
            try:
                self._settings_dialog.close()
            except (OSError, RuntimeError) as exc:
                logger.warning("Could not close settings: %s", exc)
            finally:
                self._settings_dialog = None
        cancellation_requested |= await self._stop_component("lyrics search", self._lyrics_search.stop)
        cancellation_requested |= await self._stop_component("lyrics search service", self._lyrics_search_service.stop)
        cancellation_requested |= await self._stop_component("lyrics cache manager", self._cache_management.stop)
        # Producers may publish their final empty frame during shutdown. Keep
        # the Qt surface alive until every publisher and the display clock have
        # stopped, then release the surface-owned platform resources.
        cancellation_requested |= await self._stop_component("MPRIS provider", self._mpris.stop)
        cancellation_requested |= await self._stop_component("Cider provider", self._cider.stop)
        cancellation_requested |= await self._stop_component("adapter receiver", self._receiver.stop)
        cancellation_requested |= await self._stop_component("display coordinator", self._display.stop)
        try:
            surface_result = self._overlay.shutdown()
        except (OSError, RuntimeError) as exc:
            logger.warning("Could not shut down overlay: %s", exc)
        else:
            if not surface_result.succeeded:
                logger.warning("Overlay surface shutdown was incomplete: %s", surface_result.reason)
        cancellation_requested |= await self._stop_component("track offsets", self._track_offsets.close)
        cancellation_requested |= await self._stop_component("configuration service", self._config_service.close)
        self._settings_tasks.close()
        self._started = False
        self._stopped = True
        if cancellation_requested:
            raise asyncio.CancelledError

    async def _stop_component(self, name: str, operation: Callable[[], Coroutine[object, object, None]]) -> bool:
        """Release one owned async resource while preserving the rest of shutdown."""
        operation_task = create_owned_task(
            operation(),
            name=f"kotonoha-stop-{name.lower().replace(' ', '-')}",
        )
        try:
            cancellation_requested = await wait_for_owned(operation_task)
        except (LyricsCacheError, MprisSessionError, OSError, RuntimeError, TimeoutError) as exc:
            logger.warning("Could not stop %s cleanly: %s", name, exc)
            return False
        if cancellation_requested:
            logger.warning("Cancellation requested while stopping %s; continuing shutdown", name)
        return cancellation_requested

    async def _finish_settings_open(self) -> None:
        """Cancel and await settings discovery before the controller is closed."""
        task = self._settings_open_task
        self._settings_open_task = None
        if task is None or task.done():
            await self._settings_tasks.wait()
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await self._settings_tasks.wait()

    # --- passthrough / lock ---

    def open_settings(self) -> None:
        """Open the Settings dialog through the controller-owned workflow."""
        self._open_settings()

    def on_toggle_passthrough(self, checked: bool) -> None:
        """Apply a tray passthrough command through the controller."""
        self._on_toggle_passthrough(checked)

    def _toggle_passthrough(self) -> None:
        self._on_toggle_passthrough(not self._config.passthrough)

    def _open_lyrics_search(self, track: object) -> None:
        """Open manual lyric search from the overlay's current-track snapshot."""
        if not isinstance(track, TrackMetadata):
            logger.warning("Ignoring an invalid lyric-search track payload: %s", type(track).__name__)
            return
        try:
            query = LyricsSearchQuery(
                title=track.title,
                artist=track.artist,
                album=track.album,
                duration_s=track.duration_s,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Ignoring invalid lyric-search track metadata: %s", exc)
            return
        self._lyrics_search.open(self._config, query, self._display.current_lyrics_status())

    def _apply_selected_lyrics(self, result: LyricsSearchResult, expected_track: TrackMetadata) -> bool:
        """Publish a confirmed lyric artifact immediately when playback is still compatible."""
        return self._display.apply_manual_artifact(result.artifact, expected_track)

    def _on_toggle_passthrough(self, checked: bool) -> None:
        """Synchronize click-through state across the overlay, config, and tray."""
        self._overlay.set_passthrough(checked)
        if checked != self._config.passthrough:
            self._config = self._config_service.set_passthrough(checked)
        self._tray.set_passthrough_checked(checked)

    def _handle_intent(self, intent: SettingsIntent) -> None:
        """Route typed UI commands to the owning application workflow."""
        if isinstance(intent, ApplyConfig):
            self._apply_config(intent.config, intent.changed_fields)
            return
        if isinstance(intent, ClearCache):
            self._cache_management.clear()
            return
        if isinstance(intent, OpenCacheManagement):
            self._cache_management.open(self._config)
            return
        if isinstance(intent, SearchCache):
            self._cache_management.search(intent.query)
            return
        if isinstance(intent, DeleteCacheEntries):
            self._cache_management.delete(intent.keys)
            return
        if isinstance(intent, RequestRestart):
            self._restart()
            return
        if isinstance(intent, ChangeTrackOffset):
            self._track_offsets.set_offset(intent.key, intent.offset_ms)
            self._display.set_options(display_options(self._config, self._track_offsets.snapshot()))
            return
        if isinstance(intent, ChangePosition):
            self._config = self._config_service.set_position(
                intent.margin_edge,
                intent.margin_x,
                intent.screen_name,
                intent.screen_width,
                intent.screen_height,
            )
            self._overlay.apply_config(self._config)
            return
        raise TypeError(f"unsupported application intent: {type(intent).__name__}")

    # --- settings ---

    def _open_settings(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        if self._settings_open_task is not None and not self._settings_open_task.done():
            return
        task = self._settings_tasks.create(
            self._open_settings_async(),
            name="kotonoha-settings-open",
        )
        self._settings_open_task = task

        def finished(done: asyncio.Task[None]) -> None:
            self._settings_tasks.discard(done)
            if self._settings_open_task is done:
                self._settings_open_task = None
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except (MprisSessionError, OSError, RuntimeError) as exc:
                logger.warning("Could not open settings: %s", exc)

        task.add_done_callback(finished)

    async def _open_settings_async(self) -> None:
        if self._settings_dialog is not None:
            return
        try:
            players = await self._mpris.available_players()
        except (MprisSessionError, OSError, TimeoutError) as exc:
            logger.debug("MPRIS player discovery failed: %s", exc)
            players = []
        dialog = self._settings_factory.create(self._config, players)
        dialog.intent_requested.connect(self._handle_intent)
        dialog.finished.connect(self._clear_dialog)
        self._settings_dialog = dialog
        dialog.show()

    def _clear_dialog(self, _result: int | None = None) -> None:
        self._settings_dialog = None

    def _restart(self) -> None:
        # Relaunch via `python -m kotonoha` so it works whether we were started as
        # the `kotonoha` console script or with `-m`, preserving the CLI args, then
        # quit this instance so its shutdown runs cleanly and the port is released.
        started = self._restart_launcher.start(sys.executable, ["-m", "kotonoha", *sys.argv[1:]])
        if not started:
            # Quitting here would leave the user with nothing running: the result
            # was discarded and this instance exited regardless, so a replacement
            # that could not be spawned looked exactly like a successful restart.
            logger.error("Could not start the replacement process; staying up")
            return
        logger.info("Restarting to apply settings")
        self._quit_port.quit()

    def _apply_config(self, config: Config, changed_fields: frozenset[str]) -> None:
        previous = self._config
        self._config = self._config_service.apply_settings(config, changed_fields)
        self._runtime_config.apply(previous, self._config)

    # --- accessors for tests ---

    @property
    def overlay(self) -> OverlayPort:
        """Return the injected overlay port for integration callers and tests."""
        return self._overlay

    @property
    def receiver(self) -> ReceiverPort:
        """Return the injected external-adapter receiver port."""
        return self._receiver
