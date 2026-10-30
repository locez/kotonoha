"""The single concrete object-graph composition root for Kotonoha."""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import QApplication

from ..async_worker import BlockingCallRunner, BlockingWorkerPort
from ..config import Config, ConfigStore, clamp_port
from ..display.models import LyricsDisplayStatus
from ..display.offsets import EMPTY_TRACK_OFFSETS, TrackOffsetSnapshot
from ..display.presentation import DisplayEngine
from ..display.timeline import TimelineEngine
from ..i18n import resolve_translation_language
from ..lyrics import kugou, lrclib, netease, qqmusic
from ..lyrics.amll import AmllLyricsSource
from ..lyrics.cache import LyricsCache
from ..lyrics.catalog import LyricsSourceCatalog
from ..lyrics.http import new_lyrics_session
from ..lyrics.live_source import LiveLyricsSource
from ..lyrics.network_sources import NetworkLyricsSource
from ..lyrics.resolver import LyricsResolver
from ..lyrics.search import LyricsSearchProvider, LyricsSearchQuery, LyricsSearchService
from ..lyrics.sources import EmbeddedLyricsSource, LocalLyricsSource, SidecarLyricsSource
from ..platform import (
    DefaultOverlayPlatformFactory,
    LayerShellController,
    OverlayPlatformFactory,
    default_package_dir,
)
from ..platform.restart import QProcessRestartLauncher
from ..players import PlayerInfo
from ..providers.cider_api import CiderApiProvider
from ..providers.cider_client import CiderApiClient
from ..providers.mpris import MprisProvider
from ..providers.mpris_adapter import MprisPlaybackAdapter
from ..providers.mpris_session import MprisSession
from ..receiver import AdapterReceiver
from ..state import TrackOffsetStore, TrackOffsetStoreError
from ..strings import Translator
from ..tray import KotonohaTray, load_icon
from ..ui.overlay import LyricsOverlay
from ..ui.overlay.publisher import QtDisplayPublisher
from ..ui.overlay.state import LyricsState
from ..ui.settings.cache_dialog import LyricsCacheDialog
from ..ui.settings.dialog import SettingsDialog
from ..ui.settings.lyrics_search_dialog import LyricsSearchDialog
from .application_controller import AppController
from .components import ApplicationComponents, RestartLauncher
from .config_service import ConfigService, ConfigWriter
from .display_coordinator import DisplayCoordinator
from .services import RuntimeConfigApplier, display_options
from .settings_port import CacheManagementDialogFactory, LyricsSearchDialogFactory, SettingsDialogFactory
from .source_gate import SourceOwnershipCoordinator
from .track_offset_service import TrackOffsetService, TrackOffsetWriter

logger = logging.getLogger(__name__)


class _QtRuntimePort:
    """Adapt Qt application state to the application runtime-config port."""

    def __init__(self, app: QApplication, translator: Translator) -> None:
        self._app = app
        self._translator = translator

    def set_language(self, value: str | None) -> None:
        self._translator.set_language(value)

    def set_window_icon(self, icon_name: str, accent: str) -> None:
        self._app.setWindowIcon(load_icon(icon_name, accent=accent))


def apply_cli_port(config: Config, cli_port: int | None) -> Config:
    """Return a clamped configuration with the optional process port override."""
    normalized = config.clamped()
    if cli_port is None:
        return normalized
    clamped = clamp_port(cli_port)
    if clamped != cli_port:
        logger.warning("CLI --port %d is out of range 1..65535; using %d", cli_port, clamped)
    normalized.port = clamped
    return normalized


class _QtSettingsDialogFactory:
    """Adapt the Qt Settings dialog to the application-facing factory contract."""

    def __init__(self, regular_window_factory: OverlayPlatformFactory, translator: Translator) -> None:
        self._regular_window_factory = regular_window_factory
        self._translator = translator

    def create(self, config: Config, players: list[PlayerInfo]) -> SettingsDialog:
        return SettingsDialog(
            config,
            players=players,
            platform_factory=self._regular_window_factory,
            translator=self._translator,
        )


class _QtCacheManagementDialogFactory:
    """Adapt the Qt cache manager to the application-facing factory contract."""

    def __init__(self, regular_window_factory: OverlayPlatformFactory, translator: Translator) -> None:
        self._regular_window_factory = regular_window_factory
        self._translator = translator

    def create(self, config: Config) -> LyricsCacheDialog:
        """Create one standalone cache manager using the shared UI translator."""
        return LyricsCacheDialog(
            config,
            platform_factory=self._regular_window_factory,
            translator=self._translator,
        )


class _QtLyricsSearchDialogFactory:
    """Adapt the Qt manual-search dialog to the application-facing factory."""

    def __init__(self, regular_window_factory: OverlayPlatformFactory, translator: Translator) -> None:
        self._regular_window_factory = regular_window_factory
        self._translator = translator

    def create(self, config: Config, query: LyricsSearchQuery, status: LyricsDisplayStatus) -> LyricsSearchDialog:
        """Create a search dialog with the current theme and track query."""
        return LyricsSearchDialog(
            config,
            query,
            status=status,
            platform_factory=self._regular_window_factory,
            translator=self._translator,
        )


class ApplicationComposition:
    """Build one application graph from explicit external-boundary dependencies."""

    def __init__(
        self,
        app: QApplication,
        config: Config,
        *,
        config_writer: ConfigWriter,
        config_worker: BlockingWorkerPort,
        track_offsets: TrackOffsetSnapshot,
        track_offset_writer: TrackOffsetWriter,
        track_offset_worker: BlockingWorkerPort,
        restart_launcher: RestartLauncher,
    ) -> None:
        self._app = app
        self._config = config.clamped()
        self._config_writer = config_writer
        self._config_worker = config_worker
        self._track_offsets = track_offsets
        self._track_offset_writer = track_offset_writer
        self._track_offset_worker = track_offset_worker
        self._restart_launcher = restart_launcher
        self._controller: AppController | None = None

    @classmethod
    async def production(
        cls,
        app: QApplication,
        config: Config | None = None,
        *,
        cli_port: int | None = None,
    ) -> ApplicationComposition:
        """Create the production graph with concrete process-boundary adapters.

        ``config`` is an explicit test/integration seam. Normal startup loads the
        model through the same ``ConfigStore`` that the ConfigService will later
        use for persistence, so there is one configuration boundary and owner.
        """
        config_store = ConfigStore(Config)
        config_worker = BlockingCallRunner("kotonoha-config")
        track_offset_store = TrackOffsetStore()
        track_offset_worker = BlockingCallRunner("kotonoha-track-offsets")
        workers_transferred = False
        try:
            initial_config = config if config is not None else await config_worker.run(config_store.load)
            try:
                initial_offsets = await track_offset_worker.run(track_offset_store.load)
            except TrackOffsetStoreError as exc:
                logger.warning("Could not load track offsets: %s", exc)
                initial_offsets = EMPTY_TRACK_OFFSETS
            composition = cls(
                app,
                apply_cli_port(initial_config, cli_port),
                config_writer=config_store,
                config_worker=config_worker,
                track_offsets=initial_offsets,
                track_offset_writer=track_offset_store,
                track_offset_worker=track_offset_worker,
                restart_launcher=QProcessRestartLauncher(),
            )
            workers_transferred = True
            return composition
        finally:
            if not workers_transferred:
                config_worker.close()
                track_offset_worker.close()

    def build(self) -> AppController:
        """Build the graph once and return its application lifecycle owner."""
        if self._controller is not None:
            return self._controller

        local_worker = BlockingCallRunner("kotonoha-local-lyrics")
        cache_worker = BlockingCallRunner("kotonoha-lyrics-cache")
        amll_worker = BlockingCallRunner("kotonoha-amll-catalog")
        try:
            controller = self._build_unchecked(local_worker, cache_worker, amll_worker)
        except BaseException:
            # Construction happens before AppController owns the graph, so the
            # composition root must release every worker it allocated itself.
            # This is deliberately a cleanup-only catch: the original build
            # failure is re-raised after the resources are released.
            self._close_build_worker(local_worker, "local lyrics")
            self._close_build_worker(cache_worker, "lyrics cache")
            self._close_build_worker(amll_worker, "AMLL catalog")
            self._close_build_worker(self._track_offset_worker, "track offsets")
            self._close_build_worker(self._config_worker, "configuration")
            raise
        self._controller = controller
        return controller

    def _build_unchecked(
        self,
        local_worker: BlockingWorkerPort,
        cache_worker: BlockingWorkerPort,
        amll_worker: BlockingWorkerPort,
    ) -> AppController:
        """Construct the graph while :meth:`build` owns rollback on failure."""

        config_service = ConfigService(
            self._config,
            writer=self._config_writer,
            worker=self._config_worker,
        )
        config = config_service.config
        track_offsets = TrackOffsetService(
            self._track_offsets,
            writer=self._track_offset_writer,
            worker=self._track_offset_worker,
        )
        translator = Translator(config.ui_language)
        ui_runtime = _QtRuntimePort(self._app, translator)
        ui_runtime.set_language(config.ui_language)
        ui_runtime.set_window_icon(config.window_icon_name, config.accent_start)

        state = LyricsState()
        publisher = QtDisplayPublisher(state)
        display = DisplayCoordinator(
            publisher,
            presenter=DisplayEngine(display_options(config, track_offsets.snapshot())),
            timeline=TimelineEngine(),
        )

        platform_name = self._app.platformName()
        desktop_value = self._app.property("xdg_current_desktop")
        desktop = desktop_value if isinstance(desktop_value, str) else ""
        layer_shell = LayerShellController(default_package_dir(), platform_name, desktop)
        platform_factory = DefaultOverlayPlatformFactory(
            layer_shell,
            platform_name=platform_name,
            current_desktop=desktop,
        )
        overlay = LyricsOverlay(
            state,
            config,
            platform_factory=platform_factory,
            translator=translator,
            track_offsets=track_offsets,
        )

        ownership = SourceOwnershipCoordinator(display_sources=config.display_sources)
        local_source = LocalLyricsSource(
            SidecarLyricsSource(),
            EmbeddedLyricsSource(),
            worker=local_worker,
        )
        amll = AmllLyricsSource(worker=amll_worker)
        lyric_sources = {
            "amll": amll,
            "netease": NetworkLyricsSource(
                "netease",
                netease.fetch_artifact,
                netease.parse_payload,
                exact_fetch=netease.fetch_artifact_for_song_id,
            ),
            "qqmusic": NetworkLyricsSource(
                "qqmusic",
                qqmusic.fetch_artifact,
                qqmusic.parse_payload,
                exact_fetch=qqmusic.fetch_artifact_for_song_id,
            ),
            "lrclib": NetworkLyricsSource("lrclib", lrclib.fetch_artifact, lrclib.parse_payload),
            "kugou": NetworkLyricsSource("kugou", kugou.fetch_artifact, kugou.parse_payload),
        }
        catalog = LyricsSourceCatalog(
            lyric_sources,
            live_source=LiveLyricsSource(ownership),
            local_source=local_source,
            managed_sources=(amll,),
        )
        cache = LyricsCache(worker=cache_worker)
        lyrics_search: LyricsSearchService = LyricsSearchService(
            {
                "amll": LyricsSearchProvider(amll.search_artifacts),
                "netease": LyricsSearchProvider(netease.search_artifacts),
                "lrclib": LyricsSearchProvider(lrclib.search_artifacts),
                "kugou": LyricsSearchProvider(kugou.search_artifacts),
                "qqmusic": LyricsSearchProvider(
                    None,
                    "search.unavailable.qqmusic",
                ),
                "cider": LyricsSearchProvider(
                    None,
                    "search.unavailable.cider",
                ),
            },
            new_lyrics_session,
        )
        resolver = LyricsResolver(
            catalog=catalog,
            cache=cache,
            cache_enabled=config.cache_enabled,
        )
        receiver = AdapterReceiver(display, port=config.port, ownership=ownership)
        cider = CiderApiProvider(
            display=display,
            ownership=ownership,
            client=CiderApiClient(token=config.cider_api_token),
            translation_language=resolve_translation_language(config.translation_language),
            enabled="cider" in config.lyrics_sources,
        )
        mpris = MprisProvider(
            display,
            lyrics_sources=config.lyrics_sources,
            ownership=ownership,
            resolver=resolver,
            playback_adapter=MprisPlaybackAdapter(),
            playback_session=MprisSession(),
        )
        mpris.set_player_lock(config.player_lock)
        mpris.set_cache_enabled(config.cache_enabled)
        mpris.set_prefer_best(config.prefer_best_lyrics)
        mpris.set_fuzzy(config.fuzzy_match)

        tray = KotonohaTray(
            icon_name=config.icon_name,
            accent=config.accent_start,
            passthrough=config.passthrough,
            on_toggle_passthrough=None,
            on_open_settings=None,
            on_quit=self._app.quit,
            translator=translator,
        )
        settings_factory: SettingsDialogFactory = _QtSettingsDialogFactory(
            platform_factory.for_regular_window,
            translator,
        )
        cache_management_factory: CacheManagementDialogFactory = _QtCacheManagementDialogFactory(
            platform_factory.for_regular_window,
            translator,
        )
        lyrics_search_factory: LyricsSearchDialogFactory = _QtLyricsSearchDialogFactory(
            platform_factory.for_regular_window,
            translator,
        )
        runtime_config = RuntimeConfigApplier(
            ui_runtime,
            display,
            overlay,
            tray,
            mpris,
            cider,
            ownership,
            track_offsets,
        )
        components = ApplicationComponents(
            config_service=config_service,
            track_offsets=track_offsets,
            restart_launcher=self._restart_launcher,
            display=display,
            overlay=overlay,
            settings_factory=settings_factory,
            cache_management_factory=cache_management_factory,
            lyrics_search_factory=lyrics_search_factory,
            lyrics_cache=cache,
            lyrics_cache_writer=cache,
            lyrics_search=lyrics_search,
            receiver=receiver,
            cider=cider,
            mpris=mpris,
            tray=tray,
            runtime_config=runtime_config,
        )
        controller = AppController(self._app, components)
        state.frame_changed.connect(controller.refresh_cache_status)
        # The tray callbacks are bound to the controller after construction so the
        # graph remains explicit without giving the tray a controller dependency.
        tray.set_action_handlers(
            on_toggle_passthrough=controller.on_toggle_passthrough,
            on_open_settings=controller.open_settings,
        )
        return controller

    @staticmethod
    def _close_build_worker(worker: BlockingWorkerPort, name: str) -> None:
        """Close one pre-controller worker without masking the construction error."""
        try:
            worker.close()
        except (OSError, RuntimeError) as exc:
            logger.warning("Could not roll back %s worker: %s", name, exc)


__all__ = ["ApplicationComposition", "apply_cli_port"]
