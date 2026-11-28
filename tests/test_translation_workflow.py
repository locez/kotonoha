"""Integration tests for display translation enrichment and Settings translation UI."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLineEdit

from kotonoha.app.display_coordinator import DisplayCoordinator
from kotonoha.app.intents import (
    ApplyConfig,
    ClearTranslationCache,
    DeleteTranslationApiKey,
    DeleteTranslationCacheEntries,
    LoadTranslationCacheRecord,
    OpenTranslationCacheManagement,
    SaveTranslationApiKey,
    SearchTranslationCache,
)
from kotonoha.app.translation_cache_management import TranslationCacheManagementController
from kotonoha.app.translation_coordinator import (
    LyricsTranslationCoordinator,
    TranslationSecretSnapshot,
    translation_config_from_app,
)
from kotonoha.async_worker import BlockingCallRunner
from kotonoha.config import (
    Config,
    LyricsDisplayMode,
    TranslationPolicy,
    TranslationProvider,
    TranslationServiceConfig,
)
from kotonoha.display.models import ResolutionState, TranslationDisplayState
from kotonoha.display.presentation import DisplayEngine
from kotonoha.display.timeline import TimelineEngine
from kotonoha.lyrics.models import LyricLine, LyricsDocument, TimingKind
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from kotonoha.secrets import SecretAvailability, translation_secret_key
from kotonoha.translation import (
    LyricsTranslationService,
    TranslationCache,
    TranslationCacheKey,
    TranslationCacheQuery,
    TranslationError,
    TranslationErrorKind,
    TranslationRequest,
    TranslationResult,
    content_hash,
)
from kotonoha.ui.overlay.publisher import QtDisplayPublisher
from kotonoha.ui.overlay.state import LyricsState
from kotonoha.ui.settings.dialog import SettingsDialog
from kotonoha.ui.settings.translation_cache_dialog import TranslationCacheDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _MemorySecrets:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.values: dict[str, str] = dict(initial or {})

    def start(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def availability(self) -> SecretAvailability:
        return SecretAvailability(True, "memory")

    async def get_secret(self, key: str) -> str | None:
        return self.values.get(key)

    async def set_secret(self, key: str, value: str) -> None:
        self.values[key] = value

    async def delete_secret(self, key: str) -> None:
        self.values.pop(key, None)


class _NoopSession:
    def get(self, *_args: object, **_kwargs: object):
        raise AssertionError("unexpected GET")

    def post(self, *_args: object, **_kwargs: object):
        raise AssertionError("unexpected POST")

    async def close(self) -> None:
        return None


def _doc(song_id: str, text: str, translation: str = "") -> LyricsDocument:
    return LyricsDocument(
        "amll",
        song_id=song_id,
        timing=TimingKind.LINE,
        title=f"Song {song_id}",
        artist="Artist",
        duration_s=10.0,
        lines=(LyricLine(0, "L0", 0.0, 10.0, text, translation),),
    )


def _playback(song_id: str) -> PlaybackObservation:
    track = TrackIdentity("test", "player", stable_id=song_id, title=f"Song {song_id}", artist="Artist")
    return PlaybackObservation("test", "player", track, PlaybackStatus.PLAYING, 1.0, 10.0, 100.0)


async def test_display_coordinator_enriches_asynchronously_and_drops_stale_track(tmp_path: Path) -> None:
    state = LyricsState()
    display = DisplayCoordinator(
        QtDisplayPublisher(state),
        presenter=DisplayEngine(),
        timeline=TimelineEngine(),
    )
    worker = BlockingCallRunner("test-workflow-cache")
    cache = TranslationCache(tmp_path / "lyrics.sqlite3", worker=worker)
    secrets = _MemorySecrets({translation_secret_key("deepl"): "key:fx"})
    gate = asyncio.Event()
    started = asyncio.Event()
    calls: list[tuple[str, ...]] = []

    class _GatedTranslator:
        async def translate(self, request: TranslationRequest, *, api_key: str) -> TranslationResult:
            del api_key
            calls.append(request.lines)
            started.set()
            await gate.wait()
            return TranslationResult(
                translations=tuple(f"PT:{line}" for line in request.lines),
                provider="deepl",
                model="deepl-free",
            )

    config = Config(
        translation_language="pt-PT",
        translation_policy=TranslationPolicy.REPLACE,
        translation_services=[
            TranslationServiceConfig(
                id="deepl",
                name="DeepL API",
                provider=TranslationProvider.DEEPL,
                enabled=True,
            ),
        ],
    )
    service = LyricsTranslationService(
        config=translation_config_from_app(config),
        cache=cache,
        secrets=secrets,
        session_factory=_NoopSession,
        translator_factory=lambda _session, _svc, _prompt, _fb: _GatedTranslator(),
    )
    coordinator = LyricsTranslationCoordinator(service=service, secrets=secrets, target=display)
    display.set_document_listener(coordinator.on_source_document)

    await coordinator.start()
    try:
        doc_a = _doc("A", "Hello world", translation="你好世界")
        display.publish_resolution(_playback("A"), doc_a, ResolutionState.AVAILABLE)
        # Immediate display keeps original text visible without leaking the mismatched Zh translation.
        assert state.frame.current is not None
        assert state.frame.current.text == "Hello world"
        assert state.frame.translation is None
        assert state.frame.translation_status is TranslationDisplayState.TRANSLATING

        await asyncio.wait_for(started.wait(), timeout=1.0)
        gate.set()
        await coordinator._tasks.wait()
        assert state.frame.translation is not None
        assert state.frame.translation.text == "PT:Hello world"
        assert state.frame.translation_status is TranslationDisplayState.READY

        # Repeated publication of the same source document keeps the translated view and does not re-call API.
        display.publish_resolution(_playback("A"), doc_a, ResolutionState.AVAILABLE)
        assert state.frame.translation is not None
        assert state.frame.translation.text == "PT:Hello world"
        assert state.frame.translation_status is TranslationDisplayState.READY
        assert len(calls) == 1

        # Switching to Track B while Track C's stale request is still in-flight must drop the stale result.
        gate.clear()
        started.clear()
        doc_c = _doc("C", "Stale track", translation="旧译文")
        display.publish_resolution(_playback("C"), doc_c, ResolutionState.AVAILABLE)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        doc_b = _doc("B", "Second track", translation="新译文")
        display.publish_resolution(_playback("B"), doc_b, ResolutionState.AVAILABLE)
        gate.set()
        await coordinator._tasks.wait()
        assert state.frame.translation is not None
        assert state.frame.translation.text == "PT:Second track"
        assert state.frame.translation_status is TranslationDisplayState.READY

        # Turning translation OFF restores the source document's original translation immediately.
        coordinator.apply_config(Config(translation_policy=TranslationPolicy.OFF))
        assert state.frame.translation is not None
        assert state.frame.translation.text == "新译文"
        assert state.frame.translation_status is TranslationDisplayState.IDLE

        # Leaving READY via set_translation_status must drop any stale translated document.
        display.apply_translated_document(doc_b, _doc("B", "Second track", translation="PT:Second track"))
        assert state.frame.translation is not None
        assert state.frame.translation.text == "PT:Second track"
        display.set_translation_status(doc_b, TranslationDisplayState.IDLE)
        assert state.frame.translation is not None
        assert state.frame.translation.text == "新译文"
        assert state.frame.translation_status is TranslationDisplayState.IDLE
    finally:
        await coordinator.stop()
        cache.close()


async def test_translation_failure_and_policy_states_never_fall_back_to_mismatched_source_translation(
    tmp_path: Path,
) -> None:
    state = LyricsState()
    display = DisplayCoordinator(
        QtDisplayPublisher(state),
        presenter=DisplayEngine(),
        timeline=TimelineEngine(),
    )
    worker = BlockingCallRunner("test-workflow-failure-cache")
    cache = TranslationCache(tmp_path / "lyrics.sqlite3", worker=worker)
    secrets = _MemorySecrets({translation_secret_key("deepl"): "bad-key:fx"})
    api_calls = 0

    class _FailingTranslator:
        async def translate(self, request: TranslationRequest, *, api_key: str) -> TranslationResult:
            nonlocal api_calls
            del request, api_key
            api_calls += 1
            raise TranslationError("Invalid API key", kind=TranslationErrorKind.AUTH)

    deepl_service = TranslationServiceConfig(
        id="deepl",
        name="DeepL API",
        provider=TranslationProvider.DEEPL,
        enabled=True,
    )
    config = Config(
        translation_language="pt-PT",
        translation_policy=TranslationPolicy.MISSING_ONLY,
        translation_services=[deepl_service],
    )
    service = LyricsTranslationService(
        config=translation_config_from_app(config),
        cache=cache,
        secrets=secrets,
        session_factory=_NoopSession,
        translator_factory=lambda _session, _svc, _prompt, _fb: _FailingTranslator(),
    )
    coordinator = LyricsTranslationCoordinator(service=service, secrets=secrets, target=display)
    display.set_document_listener(coordinator.on_source_document)

    await coordinator.start()
    try:
        # Target pt-PT + failing API key must show FAILED without falling back to Zh source translation.
        doc_en = _doc(
            "EN",
            "When the night is dark and you are far away from home",
            translation="当夜幕降临时你远在天涯海角",
        )
        display.publish_resolution(_playback("EN"), doc_en, ResolutionState.AVAILABLE)
        assert state.frame.translation is None
        assert state.frame.translation_status is TranslationDisplayState.TRANSLATING
        await coordinator._tasks.wait()
        assert api_calls == 1
        assert state.frame.translation is None
        assert state.frame.translation_status is TranslationDisplayState.FAILED

        # Target pt-PT + all translation services disabled reports UNAVAILABLE without leaking Zh.
        coordinator.apply_config(
            Config(
                translation_language="pt-PT",
                translation_policy=TranslationPolicy.MISSING_ONLY,
                translation_services=[
                    TranslationServiceConfig(
                        id="deepl",
                        name="DeepL API",
                        provider=TranslationProvider.DEEPL,
                        enabled=False,
                    )
                ],
            )
        )
        assert state.frame.translation is None
        assert state.frame.translation_status is TranslationDisplayState.UNAVAILABLE
        assert api_calls == 1

        # Target zh-Hans + MISSING_ONLY with matching Simplified Chinese source translation does NOT call API.
        coordinator.apply_config(
            Config(
                translation_language="zh-Hans",
                translation_policy=TranslationPolicy.MISSING_ONLY,
                translation_services=[deepl_service],
            )
        )
        assert state.frame.translation is not None
        assert state.frame.translation.text == "当夜幕降临时你远在天涯海角"
        assert state.frame.translation_status is TranslationDisplayState.IDLE
        assert api_calls == 1

        # Song already in target language marks SKIPPED without calling API or leaking mismatched translations.
        coordinator.apply_config(
            Config(
                translation_language="pt-PT",
                translation_policy=TranslationPolicy.MISSING_ONLY,
                translation_services=[deepl_service],
            )
        )
        await coordinator._tasks.wait()
        calls_before_pt_song = api_calls
        doc_pt = _doc(
            "PT",
            "Quando a noite cai eu não consigo esquecer você agora com tudo o que tenho",
            translation="当夜幕降临时我无法忘记你",
        )
        display.publish_resolution(_playback("PT"), doc_pt, ResolutionState.AVAILABLE)
        assert state.frame.translation is None
        assert state.frame.translation_status is TranslationDisplayState.SKIPPED
        assert api_calls == calls_before_pt_song

        # Original-only display mode disables background API calls even when online policy is enabled.
        coordinator.apply_config(
            Config(
                lyrics_display_mode=LyricsDisplayMode.ORIGINAL_ONLY,
                translation_language="pt-PT",
                translation_policy=TranslationPolicy.REPLACE,
                translation_services=[deepl_service],
            )
        )
        display.publish_resolution(
            _playback("EN2"),
            _doc("EN2", "Hello world again", translation="你好"),
            ResolutionState.AVAILABLE,
        )
        await coordinator._tasks.wait()
        assert api_calls == calls_before_pt_song
    finally:
        await coordinator.stop()
        cache.close()


def test_settings_translation_controls_presets_and_keyring_intents(qapp) -> None:
    secrets = TranslationSecretSnapshot(available=True, saved_services=frozenset({"deepl"}))
    dialog = SettingsDialog(
        Config(
            translation_language="pt-PT",
            translation_policy=TranslationPolicy.REPLACE,
        ),
        translation_secrets=secrets,
    )
    intents: list[object] = []
    dialog.intent_requested.connect(intents.append)
    w = dialog.form_widgets

    assert w.translation_language.currentData() == "pt-PT"
    assert w.translation_services_list.count() == 2
    assert w.translation_services_list.isHidden() is False
    assert w.translation_prompt.isHidden() is False
    assert w.translation_key_status.isHidden() is True  # hidden when keyring is available

    w.translation_prompt.setPlainText("Translate with poetic rhythm.")
    assert dialog.current_config().translation_prompt == "Translate with poetic rhythm."

    # Add two distinct Custom OpenAI-compatible services with separate keyring keys.
    for url, model, name, key in (
        ("https://custom-a.example/v1", "model-a", "Custom A", "sk-custom-a"),
        ("https://custom-b.example/v1", "model-b", "Custom B", "sk-custom-b"),
    ):
        w.add_translation_service.click()
        editor = dialog._page_builder._translation._editor_dialog
        assert editor is not None
        assert editor._api_key.echoMode() == QLineEdit.EchoMode.Password
        editor._preset.setCurrentIndex(editor._preset.findData("custom"))
        editor._name.setText(name)
        editor._base_url.setText(url)
        editor._model.setText(model)
        editor._api_key.setText(key)
        editor._on_save()

    services = dialog.current_config().translation_services
    assert [svc.id for svc in services] == ["gemini", "deepl", "custom", "custom-2"]
    assert services[2].base_url == "https://custom-a.example/v1"
    assert services[3].base_url == "https://custom-b.example/v1"

    # Reorder via list drag/move: move DeepL (row 1) to priority #1 and enable it.
    deepl_item = w.translation_services_list.takeItem(1)
    assert deepl_item is not None
    deepl_item.setCheckState(Qt.CheckState.Checked)
    w.translation_services_list.insertItem(0, deepl_item)
    w.translation_services_list.setCurrentRow(0)
    assert [svc.id for svc in dialog.current_config().translation_services] == [
        "deepl",
        "gemini",
        "custom",
        "custom-2",
    ]
    assert dialog.current_config().translation_services[0].enabled is True

    # Apply emits ApplyConfig plus separate SaveTranslationApiKey intents per custom service.
    dialog._emit()
    assert any(isinstance(intent, ApplyConfig) for intent in intents)
    saved_keys = {
        intent.service_id: intent.api_key
        for intent in intents
        if isinstance(intent, SaveTranslationApiKey)
    }
    assert saved_keys == {"custom": "sk-custom-a", "custom-2": "sk-custom-b"}
    assert all("sk-custom" not in repr(intent) for intent in intents if isinstance(intent, SaveTranslationApiKey))

    # Removing a service with a saved key deletes its keyring entry on Apply.
    w.translation_services_list.setCurrentRow(0)  # deepl
    w.remove_translation_service.click()
    dialog._emit()
    assert DeleteTranslationApiKey("deepl") in intents

    w.manage_translation_cache.click()
    assert intents[-1] == OpenTranslationCacheManagement()

    w.clear_translation_cache.click()
    assert intents[-1] == ClearTranslationCache()

    # Turning online translation OFF hides target language, services panel, and prompt.
    w.translation_policy.setCurrentIndex(w.translation_policy.findData("off"))
    services_panel = dialog._page_builder._translation._services_panel
    assert services_panel is not None
    assert w.translation_policy.isHidden() is False
    assert w.translation_language.isHidden() is True
    assert services_panel.isHidden() is True
    assert w.translation_prompt.isHidden() is True

    # Selecting Original only hides the online translation policy row; Translation only reveals it again.
    w.lyrics_display_mode.setCurrentIndex(
        w.lyrics_display_mode.findData(LyricsDisplayMode.ORIGINAL_ONLY.value)
    )
    assert w.translation_policy.isHidden() is True
    assert dialog.current_config().lyrics_display_mode is LyricsDisplayMode.ORIGINAL_ONLY

    w.lyrics_display_mode.setCurrentIndex(
        w.lyrics_display_mode.findData(LyricsDisplayMode.TRANSLATION_ONLY.value)
    )
    assert w.translation_policy.isHidden() is False
    assert dialog.current_config().lyrics_display_mode is LyricsDisplayMode.TRANSLATION_ONLY
    dialog.close()


def test_settings_disables_api_key_input_when_keyring_is_unavailable(qapp) -> None:
    dialog = SettingsDialog(
        Config(translation_policy=TranslationPolicy.REPLACE),
        translation_secrets=TranslationSecretSnapshot(available=False, reason="no-backend"),
    )
    assert dialog.form_widgets.translation_key_status.isHidden() is False
    assert "no-backend" in dialog.form_widgets.translation_key_status.text()
    dialog.form_widgets.edit_translation_service.click()
    editor = dialog._page_builder._translation._editor_dialog
    assert editor is not None
    assert editor._api_key.isEnabled() is False
    assert "no-backend" in editor._key_status.text()
    dialog.close()


def test_lyrics_translation_page_fits_viewport_width_without_clipping(qapp) -> None:
    dialog = SettingsDialog(
        Config(translation_policy=TranslationPolicy.MISSING_ONLY),
        translation_secrets=TranslationSecretSnapshot(
            available=True,
            saved_services=frozenset({"gemini", "deepl"}),
        ),
    )
    dialog.show()
    dialog._nav.setCurrentRow(5)
    qapp.processEvents()
    scroll = dialog._page_scrolls[5]
    viewport = scroll.viewport()
    page = scroll.widget()
    assert viewport is not None and page is not None
    assert page.width() <= viewport.width()
    assert dialog.form_widgets.translation_services_list.geometry().right() <= page.rect().right()
    assert dialog.form_widgets.translation_prompt.geometry().right() <= page.rect().right()
    dialog.close()


async def test_translation_cache_management_window_searches_deletes_and_clears(qapp, tmp_path: Path) -> None:
    worker = BlockingCallRunner("test-tcache-manager")
    cache = TranslationCache(tmp_path / "lyrics.sqlite3", worker=worker)
    mutated_calls = 0

    class _DialogFactory:
        def __init__(self) -> None:
            self.created: list[TranslationCacheDialog] = []

        def create(self, config: Config) -> TranslationCacheDialog:
            dialog = TranslationCacheDialog(config)
            self.created.append(dialog)
            return dialog

    def _increment() -> None:
        nonlocal mutated_calls
        mutated_calls += 1

    factory = _DialogFactory()
    controller = TranslationCacheManagementController(cache, factory, on_mutated=_increment)

    try:
        h1 = content_hash(("Line 1",))
        h2 = content_hash(("Line 2",))
        await cache.store(
            h1,
            "pt-PT",
            TranslationResult(("Linha 1",), provider="deepl", model="deepl-free"),
            source_lines=("Line 1",),
            timestamps=(4.5,),
            title="Alpha",
            artist="Artist A",
        )
        await cache.store(
            h2,
            "zh-Hans",
            TranslationResult(("第一行",), provider="openai-compatible", model="gemini-3.5-flash-lite"),
            title="Beta",
            artist="Artist B",
        )

        controller.open(Config())
        dialog = factory.created[-1]
        await controller._tasks.wait()
        assert dialog._model.rowCount() == 2
        # Table displays full language names rather than raw BCP-47 tags.
        displayed_langs = {dialog._model.data(dialog._model.index(row, 0)) for row in range(2)}
        assert displayed_langs == {"Português (Portugal)", "简体中文"}

        # Entry WITH timestamps & source lines opens a 4-column editor (# | Time | Original | Translation).
        dialog.intent_requested.emit(LoadTranslationCacheRecord(TranslationCacheKey(h1, "pt-PT")))
        await controller._tasks.wait()
        assert dialog._editor is not None
        editor = dialog._editor
        assert editor._table.columnCount() == 4
        assert editor._no_source_notice is None
        time_cell = editor._table.item(0, 1)
        assert time_cell is not None and time_cell.text() == "00:04.50"
        source_cell = editor._table.item(0, 2)
        assert source_cell is not None and source_cell.text() == "Line 1"
        item = editor._table.item(0, 3)
        assert item is not None
        item.setText("Linha editada")
        editor._emit_save()
        await controller._tasks.wait()
        updated = await cache.lookup(h1, "pt-PT", expected_line_count=1)
        assert updated is not None
        assert updated.translations == ("Linha editada",)
        assert mutated_calls == 1

        # Entry WITHOUT source lines hides the Original column and displays a notice.
        dialog.intent_requested.emit(LoadTranslationCacheRecord(TranslationCacheKey(h2, "zh-Hans")))
        await controller._tasks.wait()
        assert dialog._editor is not None
        assert dialog._editor._table.columnCount() == 2
        assert dialog._editor._no_source_notice is not None
        dialog._editor.close()

        dialog.intent_requested.emit(SearchTranslationCache(TranslationCacheQuery(keyword="Alpha")))
        await controller._tasks.wait()
        assert dialog._model.rowCount() == 1

        dialog.intent_requested.emit(DeleteTranslationCacheEntries((TranslationCacheKey(h1, "pt-PT"),)))
        await controller._tasks.wait()
        assert await cache.count() == 1
        assert mutated_calls == 2

        dialog.intent_requested.emit(ClearTranslationCache())
        await controller._tasks.wait()
        assert await cache.count() == 0
        assert mutated_calls == 3
    finally:
        await controller.stop()
        cache.close()
        qapp.processEvents()
