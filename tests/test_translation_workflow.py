"""Integration tests for display translation enrichment and Settings translation UI."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
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
from kotonoha.config import Config, TranslationPolicy, TranslationProvider
from kotonoha.display.models import ResolutionState
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
        translation_provider=TranslationProvider.DEEPL,
    )
    service = LyricsTranslationService(
        config=translation_config_from_app(config),
        cache=cache,
        secrets=secrets,
        session_factory=_NoopSession,
        translator_factory=lambda _session, _cfg: _GatedTranslator(),
    )
    coordinator = LyricsTranslationCoordinator(service=service, secrets=secrets, target=display)
    display.set_document_listener(coordinator.on_source_document)

    await coordinator.start()
    try:
        doc_a = _doc("A", "Hello world", translation="你好世界")
        display.publish_resolution(_playback("A"), doc_a, ResolutionState.AVAILABLE)
        # Immediate display shows original document without waiting for API.
        assert state.frame.translation is not None
        assert state.frame.translation.text == "你好世界"

        await asyncio.wait_for(started.wait(), timeout=1.0)
        gate.set()
        await coordinator._tasks.wait()
        assert state.frame.translation is not None
        assert state.frame.translation.text == "PT:Hello world"

        # Repeated publication of the same source document keeps the translated view and does not re-call API.
        display.publish_resolution(_playback("A"), doc_a, ResolutionState.AVAILABLE)
        assert state.frame.translation is not None
        assert state.frame.translation.text == "PT:Hello world"
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

        # Turning translation OFF restores the source document's original translation immediately.
        coordinator.apply_config(Config(translation_policy=TranslationPolicy.OFF))
        assert state.frame.translation is not None
        assert state.frame.translation.text == "新译文"
    finally:
        await coordinator.stop()
        cache.close()


def test_settings_translation_controls_presets_and_keyring_intents(qapp) -> None:
    secrets = TranslationSecretSnapshot(available=True, saved_providers=frozenset({"deepl"}))
    dialog = SettingsDialog(
        Config(
            translation_language="pt-PT",
            translation_policy=TranslationPolicy.REPLACE,
            translation_provider=TranslationProvider.OPENAI_COMPATIBLE,
        ),
        translation_secrets=secrets,
    )
    intents: list[object] = []
    dialog.intent_requested.connect(intents.append)
    w = dialog.form_widgets

    assert w.translation_language.currentData() == "pt-PT"
    assert w.translation_api_key.echoMode() == QLineEdit.EchoMode.Password
    assert w.translation_preset.currentData() == "gemini"
    assert w.translation_preset.isHidden() is False
    assert w.translation_base_url.isHidden() is False
    assert w.translation_model.isHidden() is False
    assert w.translation_prompt.isHidden() is False
    assert w.translation_api_key.isHidden() is False
    assert ":fx" not in w.translation_key_status.text()
    assert w.clear_translation_key.isHidden() is True  # only deepl is saved initially

    w.translation_prompt.setPlainText("Translate with poetic rhythm.")
    assert dialog.current_config().translation_prompt == "Translate with poetic rhythm."

    # Selecting DeepSeek preset updates URL and model.
    w.translation_preset.setCurrentIndex(w.translation_preset.findData("deepseek"))
    assert w.translation_base_url.text() == "https://api.deepseek.com/v1"
    assert w.translation_model.text() == "deepseek-flash"

    # Selecting local Ollama hides the API key input.
    w.translation_preset.setCurrentIndex(w.translation_preset.findData("ollama"))
    assert w.translation_base_url.text() == "http://localhost:11434/v1"
    assert w.translation_api_key.isHidden() is True

    # Switching back to DeepSeek restores API key input and emits SaveTranslationApiKey on Apply.
    w.translation_preset.setCurrentIndex(w.translation_preset.findData("deepseek"))
    assert w.translation_api_key.isHidden() is False
    w.translation_api_key.setText("sk-secret-value")
    dialog._emit()
    assert any(isinstance(intent, ApplyConfig) for intent in intents)
    saved = [intent for intent in intents if isinstance(intent, SaveTranslationApiKey)]
    assert len(saved) == 1
    assert saved[0].provider is TranslationProvider.OPENAI_COMPATIBLE
    assert saved[0].api_key == "sk-secret-value"
    assert "sk-secret-value" not in repr(saved[0])
    assert w.translation_api_key.text() == ""
    assert w.clear_translation_key.isHidden() is False

    # Switching to DeepL hides OpenAI-only rows (preset / base URL / model / prompt) and keeps key controls.
    w.translation_provider.setCurrentIndex(w.translation_provider.findData("deepl"))
    assert w.translation_preset.isHidden() is True
    assert w.translation_base_url.isHidden() is True
    assert w.translation_model.isHidden() is True
    assert w.translation_prompt.isHidden() is True
    assert w.translation_api_key.isHidden() is False
    assert w.clear_translation_key.isHidden() is False

    w.clear_translation_key.click()
    assert intents[-1] == DeleteTranslationApiKey(TranslationProvider.DEEPL)
    assert w.clear_translation_key.isHidden() is True
    assert ":fx" in w.translation_key_status.text()

    w.manage_translation_cache.click()
    assert intents[-1] == OpenTranslationCacheManagement()

    w.clear_translation_cache.click()
    assert intents[-1] == ClearTranslationCache()

    # Turning online translation OFF hides target language and all service configuration rows.
    w.translation_policy.setCurrentIndex(w.translation_policy.findData("off"))
    assert w.translation_policy.isHidden() is False
    assert w.translation_language.isHidden() is True
    assert w.translation_provider.isHidden() is True
    assert w.translation_preset.isHidden() is True
    assert w.translation_base_url.isHidden() is True
    assert w.translation_model.isHidden() is True
    assert w.translation_api_key.isHidden() is True
    assert w.translation_key_status.isHidden() is True

    # Unchecking Show translation hides the online translation policy row too.
    w.translation.setChecked(False)
    assert w.translation_policy.isHidden() is True
    dialog.close()


def test_settings_disables_api_key_input_when_keyring_is_unavailable(qapp) -> None:
    dialog = SettingsDialog(
        Config(translation_policy=TranslationPolicy.REPLACE),
        translation_secrets=TranslationSecretSnapshot(available=False, reason="no-backend"),
    )
    assert dialog.form_widgets.translation_api_key.isEnabled() is False
    assert "no-backend" in dialog.form_widgets.translation_key_status.text()
    dialog.close()


def test_lyrics_translation_page_fits_viewport_width_without_clipping(qapp) -> None:
    dialog = SettingsDialog(
        Config(
            translation_policy=TranslationPolicy.MISSING_ONLY,
            translation_provider=TranslationProvider.OPENAI_COMPATIBLE,
        ),
        translation_secrets=TranslationSecretSnapshot(
            available=True,
            saved_providers=frozenset({"openai-compatible"}),
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
