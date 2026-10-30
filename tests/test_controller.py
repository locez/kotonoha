import asyncio
import os
from collections.abc import Callable, Sequence

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from kotonoha.app.application_controller import AppController
from kotonoha.app.cache_management import CacheManagementController
from kotonoha.app.components import ApplicationComponents
from kotonoha.app.config_service import ConfigService
from kotonoha.app.intents import ChangeTrackOffset, SearchCache
from kotonoha.app.track_offset_service import TrackOffsetService
from kotonoha.async_worker import BlockingCallRunner
from kotonoha.config import Config
from kotonoha.display.models import DisplayOptions, LyricsDisplayStatus
from kotonoha.display.offsets import TrackOffsetEntry, TrackOffsetKey, TrackOffsetSnapshot
from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.cache import (
    CacheDeleteResult,
    CacheDeleteStatus,
    CacheWriteResult,
    CacheWriteStatus,
    LyricsCacheEntry,
    LyricsCacheKey,
    LyricsCacheMode,
    LyricsCacheQuery,
)
from kotonoha.lyrics.match import TrackMetadata
from kotonoha.lyrics.search import LyricsSearchQuery, LyricsSearchResponse
from kotonoha.platform.overlay_contracts import SurfaceResult
from kotonoha.players import PlayerInfo
from kotonoha.ui.settings.dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Signal:
    """Small signal fake that preserves the connect/emit contract."""

    def __init__(self) -> None:
        self._slots: list[Callable[..., object]] = []

    def connect(self, slot: Callable[..., object]) -> None:
        self._slots.append(slot)

    def emit(self, *args: object) -> None:
        for slot in tuple(self._slots):
            slot(*args)


class _FakeOverlay:
    def __init__(self, events: list[str] | None = None) -> None:
        self._events = events
        self.passthrough_toggle_requested = _Signal()
        self.quit_requested = _Signal()
        self.settings_requested = _Signal()
        self.lyrics_search_requested = _Signal()
        self.position_changed = _Signal()
        self.track_offset_changed = _Signal()
        self.visible = False
        self.passthrough = False
        self.configs: list[Config] = []

    def activate_layer_shell(self) -> bool:
        return True

    def show(self) -> None:
        self.visible = True

    def shutdown(self) -> SurfaceResult:
        if self._events is not None:
            self._events.append("overlay.shutdown")
        self.visible = False
        return SurfaceResult.applied()

    def set_passthrough(self, enabled: bool) -> None:
        self.passthrough = enabled

    def apply_config(self, config: Config) -> None:
        self.configs.append(config)


class _FakeDisplay:
    def __init__(self, events: list[str] | None = None, *, fail_start: bool = False) -> None:
        self._events = events
        self._fail_start = fail_start
        self.started = False
        self.start_calls = 0
        self.stop_calls = 0
        self.options: DisplayOptions | None = None
        self.status = LyricsDisplayStatus()

    async def start(self) -> None:
        self.start_calls += 1
        self.started = True
        if self._fail_start:
            raise RuntimeError("display start failed")

    async def stop(self) -> None:
        if self._events is not None:
            self._events.append("display.stop")
        self.stop_calls += 1
        self.started = False

    def set_options(self, options: DisplayOptions) -> None:
        self.options = options

    def apply_manual_artifact(self, artifact: LyricsArtifact, expected_track: TrackMetadata) -> bool:
        del artifact, expected_track
        return True

    def current_lyrics_status(self) -> LyricsDisplayStatus:
        return self.status


class _FakeLyricsSearch:
    def __init__(self) -> None:
        self.started = False
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1
        self.started = True

    async def stop(self) -> None:
        self.stop_calls += 1
        self.started = False

    async def search(
        self,
        query: LyricsSearchQuery,
        sources: Sequence[str],
    ) -> LyricsSearchResponse:
        del query, sources
        return LyricsSearchResponse(())


class _FakeLyricsSearchDialog:
    def __init__(self) -> None:
        self.themes: list[str] = []
        self.intent_requested = _Signal()
        self.finished = _Signal()

    def retheme(self, config: Config) -> None:
        """Accept a theme change the way the real window does."""
        self.themes.append(config.theme)

    def show(self) -> None:
        return None

    def close(self) -> None:
        self.finished.emit(0)

    def raise_(self) -> None:
        return None

    def activateWindow(self) -> None:
        return None

    def set_results(self, query: LyricsSearchQuery, response: LyricsSearchResponse) -> None:
        del query, response

    def set_busy(self, busy: bool) -> None:
        del busy

    def show_error(self, message: str) -> None:
        del message

    def show_apply_result(self, result: CacheWriteResult, displayed: bool) -> None:
        del result, displayed

    def set_current_status(self, status: LyricsDisplayStatus) -> None:
        del status


class _FakeLyricsSearchDialogFactory:
    def __init__(self) -> None:
        self.created: list[_FakeLyricsSearchDialog] = []

    def create(
        self,
        config: Config,
        query: LyricsSearchQuery,
        status: LyricsDisplayStatus,
    ) -> _FakeLyricsSearchDialog:
        del config, query, status
        dialog = _FakeLyricsSearchDialog()
        self.created.append(dialog)
        return dialog


class _FakeReceiver:
    def __init__(self, *, fail_start: bool = False, events: list[str] | None = None) -> None:
        self._fail_start = fail_start
        self._events = events
        self.started = False
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1
        if self._fail_start:
            raise OSError(98, "Address already in use")
        self.started = True

    async def stop(self) -> None:
        if self._events is not None:
            self._events.append("receiver.stop")
        self.stop_calls += 1
        self.started = False


class _FakeMpris:
    def __init__(
        self,
        *,
        available_started: asyncio.Event | None = None,
        available_release: asyncio.Event | None = None,
        fail_stop: bool = False,
        stop_started: asyncio.Event | None = None,
        stop_release: asyncio.Event | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.started = False
        self.start_calls = 0
        self.stop_calls = 0
        self._available_started = available_started
        self._available_release = available_release
        self._fail_stop = fail_stop
        self._stop_started = stop_started
        self._stop_release = stop_release
        self._events = events
        self.cache_entries: tuple[LyricsCacheEntry, ...] = ()
        self.cache_queries: list[LyricsCacheQuery] = []
        self.deleted_cache_keys: list[LyricsCacheKey] = []

    async def start(self) -> None:
        self.start_calls += 1
        self.started = True

    async def stop(self) -> None:
        if self._events is not None:
            self._events.append("mpris.stop")
        self.stop_calls += 1
        if self._stop_started is not None:
            self._stop_started.set()
        try:
            if self._stop_release is not None:
                await self._stop_release.wait()
        finally:
            self.started = False
        if self._fail_stop:
            raise RuntimeError("MPRIS cleanup failed")

    async def available_players(self) -> list[PlayerInfo]:
        if self._available_started is not None:
            self._available_started.set()
        if self._available_release is not None:
            await self._available_release.wait()
        return []

    async def clear_cache(self) -> None:
        return None

    async def search_cache(self, query: LyricsCacheQuery) -> tuple[LyricsCacheEntry, ...]:
        self.cache_queries.append(query)
        return self.cache_entries

    async def get_cache(self, key: LyricsCacheKey) -> LyricsCacheEntry | None:
        del key
        return None

    async def upsert_cache(
        self,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        del mode
        return CacheWriteResult(LyricsCacheKey(artifact.provider, artifact.provider_song_id), CacheWriteStatus.CREATED)

    async def update_cache(
        self,
        key: LyricsCacheKey,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        del artifact, mode
        return CacheWriteResult(key, CacheWriteStatus.UPDATED)

    async def delete_cache(self, key: LyricsCacheKey) -> CacheDeleteResult:
        self.deleted_cache_keys.append(key)
        return CacheDeleteResult(key, CacheDeleteStatus.DELETED)

    async def delete_cache_many(self, keys: tuple[LyricsCacheKey, ...]) -> tuple[CacheDeleteResult, ...]:
        self.deleted_cache_keys.extend(keys)
        return tuple(CacheDeleteResult(key, CacheDeleteStatus.DELETED) for key in keys)


class _FakeLyricsCache:
    """Minimal cache-management port used to keep MPRIS out of the workflow test."""

    def __init__(self) -> None:
        self.cache_entries: tuple[LyricsCacheEntry, ...] = ()
        self.cache_queries: list[LyricsCacheQuery] = []
        self.deleted_cache_keys: list[LyricsCacheKey] = []

    async def search(self, query: LyricsCacheQuery) -> tuple[LyricsCacheEntry, ...]:
        self.cache_queries.append(query)
        return self.cache_entries

    async def delete_many(self, keys: tuple[LyricsCacheKey, ...]) -> tuple[CacheDeleteResult, ...]:
        self.deleted_cache_keys.extend(keys)
        return tuple(CacheDeleteResult(key, CacheDeleteStatus.DELETED) for key in keys)

    async def clear(self) -> None:
        return None

    async def select(self, track: TrackMetadata, artifact: LyricsArtifact) -> CacheWriteResult:
        del track
        return CacheWriteResult(
            LyricsCacheKey(artifact.provider, artifact.provider_song_id),
            CacheWriteStatus.CREATED,
        )


class _BlockingLyricsCache(_FakeLyricsCache):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()

    async def search(self, query: LyricsCacheQuery) -> tuple[LyricsCacheEntry, ...]:
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return await super().search(query)


class _FakeCider:
    def __init__(self, events: list[str] | None = None) -> None:
        self._events = events
        self.started = False
        self.start_calls = 0
        self.stop_calls = 0
        self.token: str | None = None

    async def start(self) -> None:
        self.start_calls += 1
        self.started = True

    async def stop(self) -> None:
        if self._events is not None:
            self._events.append("cider.stop")
        self.stop_calls += 1
        self.started = False

    def set_token(self, token: str | None) -> None:
        self.token = token


class _FakeTray:
    def __init__(self) -> None:
        self.visible = False
        self.passthrough = False
        self.show_calls = 0

    def show(self) -> None:
        self.show_calls += 1
        self.visible = True

    def set_passthrough_checked(self, checked: bool) -> None:
        self.passthrough = checked


class _FakeConfigWriter:
    def __init__(self) -> None:
        self.saved: list[Config] = []

    def save(self, config: Config) -> None:
        self.saved.append(config)


class _FakeTrackOffsetWriter:
    def __init__(self) -> None:
        self.saved: list[TrackOffsetEntry] = []

    def upsert(self, entry: TrackOffsetEntry) -> None:
        self.saved.append(entry)


class _FakeRestartLauncher:
    def __init__(self, started: bool = True) -> None:
        self.started = started
        self.calls: list[tuple[str, Sequence[str]]] = []

    def start(self, executable: str, arguments: Sequence[str]) -> bool:
        self.calls.append((executable, arguments))
        return self.started


class _SettingsFactory:
    def __init__(self) -> None:
        self.created: list[SettingsDialog] = []
        self.created_event = asyncio.Event()

    def create(self, config: Config, players: list[PlayerInfo]) -> SettingsDialog:
        dialog = SettingsDialog(config, players=players)
        self.created.append(dialog)
        self.created_event.set()
        return dialog


class _FakeCacheDialog:
    def retheme(self, config: Config) -> None:
        """Accept a theme change the way the real window does."""
        self.themes.append(config.theme)

    def __init__(self) -> None:
        self.themes: list[str] = []
        self.intent_requested = _Signal()
        self.finished = _Signal()
        self.visible = False
        self.busy = False
        self.entries: tuple[LyricsCacheEntry, ...] = ()
        self.query: LyricsCacheQuery | None = None
        self.entries_event = asyncio.Event()
        self.errors: list[str] = []

    def show(self) -> None:
        self.visible = True

    def close(self) -> None:
        self.visible = False
        self.finished.emit(0)

    def raise_(self) -> None:
        return None

    def activateWindow(self) -> None:
        return None

    def set_entries(self, query: LyricsCacheQuery, entries: tuple[LyricsCacheEntry, ...]) -> None:
        self.query = query
        self.entries = entries
        self.entries_event.set()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy

    def show_error(self, message: str) -> None:
        self.errors.append(message)

    def show_delete_result(self, results: tuple[CacheDeleteResult, ...]) -> None:
        del results
        return None

    def show_clear_result(self) -> None:
        return None


class _CacheManagementFactory:
    def __init__(self) -> None:
        self.created: list[_FakeCacheDialog] = []

    def create(self, config: Config) -> _FakeCacheDialog:
        del config
        dialog = _FakeCacheDialog()
        self.created.append(dialog)
        return dialog


class _FakeRuntimeConfig:
    def __init__(self) -> None:
        self.calls: list[tuple[Config, Config]] = []

    def apply(self, previous: Config, current: Config) -> None:
        self.calls.append((previous, current))


class _ControllerGraph:
    """Build a controller from ports so lifecycle tests do not own a real graph."""

    def __init__(
        self,
        qapp: QApplication,
        *,
        config: Config | None = None,
        receiver: _FakeReceiver | None = None,
        mpris: _FakeMpris | None = None,
        cache: _FakeLyricsCache | None = None,
        display: _FakeDisplay | None = None,
        restart_launcher: _FakeRestartLauncher | None = None,
        settings_factory: _SettingsFactory | None = None,
        cache_management_factory: _CacheManagementFactory | None = None,
        lyrics_search: _FakeLyricsSearch | None = None,
    ) -> None:
        self.events: list[str] = []
        self.writer = _FakeConfigWriter()
        self.config_service = ConfigService(
            Config() if config is None else config,
            writer=self.writer,
            worker=BlockingCallRunner("test-config-service"),
        )
        self.offset_writer = _FakeTrackOffsetWriter()
        self.track_offsets = TrackOffsetService(
            TrackOffsetSnapshot(),
            writer=self.offset_writer,
            worker=BlockingCallRunner("test-track-offset-service"),
        )
        self.overlay = _FakeOverlay(self.events)
        self.display = display if display is not None else _FakeDisplay(self.events)
        self.receiver = receiver if receiver is not None else _FakeReceiver(events=self.events)
        self.mpris = mpris if mpris is not None else _FakeMpris(events=self.events)
        self.cache = cache if cache is not None else _FakeLyricsCache()
        self.cider = _FakeCider(self.events)
        self.tray = _FakeTray()
        self.settings_factory = settings_factory if settings_factory is not None else _SettingsFactory()
        self.cache_management_factory = (
            cache_management_factory if cache_management_factory is not None else _CacheManagementFactory()
        )
        self.lyrics_search = lyrics_search if lyrics_search is not None else _FakeLyricsSearch()
        self.lyrics_search_factory = _FakeLyricsSearchDialogFactory()
        self.runtime_config = _FakeRuntimeConfig()
        self.controller = AppController(
            qapp,
            ApplicationComponents(
                config_service=self.config_service,
                track_offsets=self.track_offsets,
                restart_launcher=restart_launcher if restart_launcher is not None else _FakeRestartLauncher(),
                display=self.display,
                overlay=self.overlay,
                settings_factory=self.settings_factory,
                cache_management_factory=self.cache_management_factory,
                lyrics_search_factory=self.lyrics_search_factory,
                lyrics_cache=self.cache,
                lyrics_cache_writer=self.cache,
                lyrics_search=self.lyrics_search,
                receiver=self.receiver,
                cider=self.cider,
                mpris=self.mpris,
                tray=self.tray,
                runtime_config=self.runtime_config,
            ),
        )

    async def close(self) -> None:
        await self.controller.stop()
        for dialog in self.settings_factory.created:
            dialog.deleteLater()


async def test_start_survives_optional_receiver_bind_failure(qapp):
    # A stale instance / double-launch holding the adapter port must only disable
    # external WS adapters, not take down the already-shown overlay and tray.
    graph = _ControllerGraph(
        qapp,
        config=Config(cider_api_token="loaded-token"),
        receiver=_FakeReceiver(fail_start=True),
        mpris=_FakeMpris(),
    )
    await graph.controller.start()

    assert graph.mpris.started is True
    assert graph.config_service.config.cider_api_token == "loaded-token"
    assert graph.overlay.visible is True
    await graph.close()
    qapp.processEvents()


async def test_controller_start_and_stop_are_idempotent(qapp):
    graph = _ControllerGraph(qapp)

    await graph.controller.start()
    await graph.controller.start()
    await graph.controller.stop()
    await graph.controller.stop()

    assert graph.display.start_calls == 1
    assert graph.display.stop_calls == 1
    assert graph.receiver.start_calls == 1
    assert graph.receiver.stop_calls == 1
    assert graph.cider.start_calls == 1
    assert graph.cider.stop_calls == 1
    assert graph.mpris.start_calls == 1
    assert graph.mpris.stop_calls == 1
    assert graph.tray.show_calls == 1
    qapp.processEvents()


async def test_controller_rolls_back_required_components_when_startup_fails(qapp):
    graph = _ControllerGraph(qapp, display=_FakeDisplay(fail_start=True))

    with pytest.raises(RuntimeError, match="display start failed"):
        await graph.controller.start()

    assert graph.display.stop_calls == 1
    assert graph.mpris.stop_calls == 1
    assert graph.cider.stop_calls == 1
    assert graph.receiver.stop_calls == 1
    assert graph.overlay.visible is False
    await graph.close()
    qapp.processEvents()


async def test_controller_shutdown_continues_after_provider_failure(qapp, caplog):
    graph = _ControllerGraph(qapp, mpris=_FakeMpris(fail_stop=True))

    await graph.controller.start()
    await graph.controller.stop()

    assert graph.mpris.stop_calls == 1
    assert graph.cider.stop_calls == 1
    assert graph.receiver.stop_calls == 1
    assert graph.display.stop_calls == 1
    assert "Could not stop MPRIS provider cleanly" in caplog.text
    qapp.processEvents()


async def test_controller_shutdown_continues_after_cancellation(qapp):
    stop_started = asyncio.Event()
    stop_release = asyncio.Event()
    mpris = _FakeMpris(stop_started=stop_started, stop_release=stop_release)
    graph = _ControllerGraph(qapp, mpris=mpris)

    await graph.controller.start()
    stop_task = asyncio.create_task(graph.controller.stop())
    await stop_started.wait()
    stop_task.cancel()
    await asyncio.sleep(0)
    assert not stop_task.done()
    stop_release.set()

    with pytest.raises(asyncio.CancelledError):
        await stop_task

    assert mpris.started is False
    assert graph.cider.stop_calls == 1
    assert graph.receiver.stop_calls == 1
    assert graph.display.stop_calls == 1
    assert graph.overlay.visible is False
    await graph.close()
    qapp.processEvents()


async def test_controller_keeps_overlay_alive_until_publishers_stop(qapp):
    graph = _ControllerGraph(qapp)

    await graph.controller.start()
    graph.events.clear()
    await graph.controller.stop()

    assert graph.events.index("mpris.stop") < graph.events.index("overlay.shutdown")
    assert graph.events.index("cider.stop") < graph.events.index("overlay.shutdown")
    assert graph.events.index("receiver.stop") < graph.events.index("overlay.shutdown")
    assert graph.events.index("display.stop") < graph.events.index("overlay.shutdown")
    qapp.processEvents()


async def test_run_stops_controller_when_startup_fails(qapp, monkeypatch):
    from kotonoha import main as main_module

    class _StartupFailureController:
        def __init__(self) -> None:
            self.stopped = False

        async def start(self) -> None:
            raise RuntimeError("startup failed")

        async def stop(self) -> None:
            self.stopped = True

    controller = _StartupFailureController()
    async def build_app_objects(_app, _cli_port):
        return controller

    monkeypatch.setattr(main_module, "_build_app_objects", build_app_objects)

    with pytest.raises(RuntimeError, match="startup failed"):
        await main_module._run(qapp)

    assert controller.stopped is True


async def test_main_task_failure_is_logged_and_quits(caplog):
    from kotonoha import main as main_module

    async def fail() -> None:
        raise RuntimeError("startup task failed")

    task = asyncio.create_task(fail())
    with pytest.raises(RuntimeError, match="startup task failed"):
        await task
    quit_calls: list[bool] = []
    main_module._main_task_finished(task, lambda: quit_calls.append(True))

    assert quit_calls == [True]
    assert "Kotonoha application task failed: startup task failed" in caplog.text


def test_out_of_range_cli_port_is_clamped(qapp):
    # argparse accepts any int; an unclamped 70000 reaches socket.bind() and raises
    # OverflowError (not an OSError), crashing startup. It must be clamped instead.
    from kotonoha.app.composition import apply_cli_port

    assert apply_cli_port(Config(), 70000).port == 65535


async def test_settings_discovery_does_not_open_two_dialogs(qapp):
    started = asyncio.Event()
    release = asyncio.Event()
    mpris = _FakeMpris(available_started=started, available_release=release)
    factory = _SettingsFactory()
    graph = _ControllerGraph(qapp, mpris=mpris, settings_factory=factory)
    try:
        graph.controller.open_settings()
        await asyncio.wait_for(started.wait(), timeout=1.0)
        graph.controller.open_settings()
        release.set()
        await asyncio.wait_for(factory.created_event.wait(), timeout=1.0)
        assert len(factory.created) == 1
    finally:
        await graph.close()
        qapp.processEvents()


async def test_settings_action_opens_a_normal_visible_dialog(qapp):
    graph = _ControllerGraph(qapp)
    try:
        graph.controller.open_settings()
        await asyncio.wait_for(graph.settings_factory.created_event.wait(), timeout=1.0)

        dialog = graph.settings_factory.created[-1]
        assert dialog.isVisible()
        assert not dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert dialog.windowFlags() & Qt.WindowType.Dialog
    finally:
        await graph.close()
        qapp.processEvents()


async def test_cache_management_opens_a_separate_window_and_returns_multiple_matches(qapp):
    factory = _CacheManagementFactory()
    cache = _FakeLyricsCache()
    mpris = _FakeMpris()
    cache.cache_entries = (
        LyricsCacheEntry(
            LyricsCacheKey("netease", "1"),
            "Song One",
            "Artist",
            "Album",
            180.0,
            1.0,
            2.0,
        ),
        LyricsCacheEntry(
            LyricsCacheKey("lrclib", "2"),
            "Song Two",
            "Artist",
            "Album",
            181.0,
            3.0,
            4.0,
        ),
    )
    graph = _ControllerGraph(qapp, mpris=mpris, cache=cache, cache_management_factory=factory)
    try:
        graph.controller.open_settings()
        await asyncio.wait_for(graph.settings_factory.created_event.wait(), timeout=1.0)
        settings = graph.settings_factory.created[-1]
        settings.form_widgets.manage_cache.click()
        dialog = factory.created[-1]
        assert dialog.visible is True

        query = LyricsCacheQuery(keyword="song")
        dialog.intent_requested.emit(SearchCache(query))
        await asyncio.wait_for(dialog.entries_event.wait(), timeout=1.0)

        assert cache.cache_queries == [query]
        assert dialog.entries == cache.cache_entries
        assert mpris.cache_queries == []
        settings.form_widgets.manage_cache.click()
        assert len(factory.created) == 1
    finally:
        await graph.close()
        qapp.processEvents()


async def test_cache_management_cancels_closed_dialog_search_before_reopening():
    cache = _BlockingLyricsCache()
    factory = _CacheManagementFactory()
    controller = CacheManagementController(cache, factory)
    query = LyricsCacheQuery(keyword="song")

    controller.open(Config())
    first = factory.created[0]
    controller.search(query)
    await asyncio.wait_for(cache.started.wait(), timeout=1.0)

    first.close()
    await asyncio.wait_for(cache.cancelled.wait(), timeout=1.0)
    controller.open(Config())
    second = factory.created[1]
    cache.release.set()
    controller.search(query)
    await asyncio.wait_for(second.entries_event.wait(), timeout=1.0)

    assert len(factory.created) == 2
    assert second.query == query
    await controller.stop()


async def test_controller_persists_track_offset(qapp):
    graph = _ControllerGraph(qapp)
    key = TrackOffsetKey("track", "artist", "album", 180, "test", "song", "a" * 64)
    graph.overlay.track_offset_changed.emit(ChangeTrackOffset(key, 50))
    await graph.close()

    assert graph.track_offsets.offset_for(key) == 50
    assert graph.offset_writer.saved[-1] == TrackOffsetEntry(key, 50)
    assert graph.display.options is not None
    assert graph.display.options.track_offsets_ms[key] == 50
    assert graph.writer.saved == []
    qapp.processEvents()


async def test_a_restart_that_cannot_start_the_replacement_stays_up(qapp):
    # A failed replacement launch must not quit the current process.
    launcher = _FakeRestartLauncher(started=False)
    graph = _ControllerGraph(qapp, restart_launcher=launcher)
    try:
        graph.controller._restart()
        assert launcher.calls
        assert graph.overlay.visible is False
    finally:
        await graph.close()
        qapp.processEvents()


@pytest.mark.parametrize("error_type", (RuntimeError, KeyError))
def test_composition_closes_workers_when_graph_construction_fails(qapp, monkeypatch, error_type):
    from kotonoha.app import composition as composition_module

    closed: list[str] = []

    class _RecordingWorker(BlockingCallRunner):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            self.name = name

        def close(self) -> None:
            closed.append(self.name)
            super().close()

    def worker_factory(name: str) -> _RecordingWorker:
        return _RecordingWorker(name)

    def fail_overlay(*_args: object, **_kwargs: object) -> None:
        raise error_type("overlay construction failed")

    monkeypatch.setattr(composition_module, "BlockingCallRunner", worker_factory)
    monkeypatch.setattr(composition_module, "LyricsOverlay", fail_overlay)
    composition = composition_module.ApplicationComposition(
        qapp,
        Config(),
        config_writer=_FakeConfigWriter(),
        config_worker=_RecordingWorker("configuration"),
        track_offsets=TrackOffsetSnapshot(),
        track_offset_writer=_FakeTrackOffsetWriter(),
        track_offset_worker=_RecordingWorker("track offsets"),
        restart_launcher=_FakeRestartLauncher(),
    )

    with pytest.raises(error_type, match="overlay construction failed"):
        composition.build()

    assert sorted(closed) == [
        "configuration",
        "kotonoha-amll-catalog",
        "kotonoha-local-lyrics",
        "kotonoha-lyrics-cache",
        "track offsets",
    ]


async def test_applying_settings_reaches_the_windows_that_are_already_open(qapp):
    from kotonoha.app.intents import ApplyConfig
    from kotonoha.config import ThemeMode

    cache_factory = _CacheManagementFactory()
    graph = _ControllerGraph(qapp, cache_management_factory=cache_factory)
    try:
        graph.controller.open_settings()
        await asyncio.wait_for(graph.settings_factory.created_event.wait(), timeout=1.0)
        settings = graph.settings_factory.created[-1]
        settings.form_widgets.manage_cache.click()
        graph.overlay.lyrics_search_requested.emit(TrackMetadata("Song", "Artist", "Album", 180.0))

        settings.intent_requested.emit(
            ApplyConfig(Config(theme=ThemeMode.LIGHT), frozenset({"theme"}))
        )
        await asyncio.sleep(0)

        # A window already open has no other way to learn the theme changed: the
        # settings window is the only one that restyles itself when it applies.
        assert cache_factory.created[-1].themes == [ThemeMode.LIGHT]
        assert graph.lyrics_search_factory.created[-1].themes == [ThemeMode.LIGHT]
    finally:
        await graph.close()
        qapp.processEvents()
