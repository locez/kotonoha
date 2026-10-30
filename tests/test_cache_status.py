"""Cached candidates must not be presented as the active lyric document."""

import asyncio
from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QTableView
from test_controller import _ControllerGraph

from kotonoha.config import Config
from kotonoha.display.models import LyricsDisplayStatus
from kotonoha.lyrics.cache import LyricsCacheEntry, LyricsCacheKey, LyricsCacheMode, LyricsCacheQuery
from kotonoha.lyrics.models import LyricsCacheState, LyricsOrigin
from kotonoha.strings import Translator
from kotonoha.ui.settings.cache_dialog import LyricsCacheDialog, LyricsCacheTableModel
from kotonoha.ui.settings.lyrics_status import LyricsStatusBand

ENTRY = LyricsCacheEntry(LyricsCacheKey("netease", "42"), "Song", "Artist", "Album", 180.0, 1.0, 2.0)
LIVE = LyricsDisplayStatus(
    playback_source="cider", lyrics_source_id="apple-music", lyrics_source_name="Apple Music",
    lyrics_song_id="42", origin=LyricsOrigin.LIVE,
)
CACHED = LyricsDisplayStatus(
    playback_source="mpris", lyrics_source_id="netease", lyrics_song_id="42",
    origin=LyricsOrigin.CACHE, cache_state=LyricsCacheState.FROM_CACHE,
)


def test_cache_labels_describe_storage_and_access_instead_of_playback() -> None:
    """An automatic candidate and a cache read must not claim automatic use."""
    model = LyricsCacheTableModel(Translator("zh-Hans"))
    model.set_entries((ENTRY, replace(ENTRY, mode=LyricsCacheMode.MANUAL)))
    assert model.headerData(5, Qt.Orientation.Horizontal) == "最近访问"
    assert model.headerData(6, Qt.Orientation.Horizontal) == "保存方式"
    assert model.data(model.index(0, 6)) == "自动缓存"
    assert model.data(model.index(1, 6)) == "手动选择"


def test_cache_window_separates_the_active_provider_from_stored_candidates(qapp: QApplication) -> None:
    """Only an exact cache-backed document gets an in-use marker on its row."""
    dialog = LyricsCacheDialog(Config(), translator=Translator("zh-Hans"))
    try:
        dialog.set_entries(LyricsCacheQuery(), (ENTRY,))
        dialog.set_current_status(LIVE)
        band = dialog.findChild(LyricsStatusBand)
        table = dialog.findChild(QTableView, "cacheTable")
        assert band is not None and table is not None
        model = table.model()
        assert model is not None
        values = [label.text() for label in band.findChildren(QLabel, "metaValue")]
        assert "Apple Music (apple-music)" in values
        assert "Cider" in values and "未使用缓存" in values
        assert model.data(model.index(0, 0)) == "netease"

        for status, expected in (
            (CACHED, "netease · ✓ 使用中"),
            (replace(CACHED, lyrics_song_id="other"), "netease"),
            (replace(CACHED, lyrics_source_id="amll"), "netease"),
            (replace(CACHED, cache_state=LyricsCacheState.MANUAL), "netease · ✓ 使用中"),
            (replace(CACHED, origin=LyricsOrigin.LIVE, cache_state=LyricsCacheState.NONE), "netease"),
            (LyricsDisplayStatus(), "netease"),
        ):
            dialog.set_current_status(status)
            assert model.data(model.index(0, 0)) == expected
    finally:
        dialog.close()


async def test_cache_window_status_follows_display_changes_and_reopening(qapp: QApplication) -> None:
    """A manager left open must not keep calling a previous source current."""
    graph = _ControllerGraph(qapp)
    try:
        graph.display.status = LIVE
        graph.controller.open_settings()
        await asyncio.wait_for(graph.settings_factory.created_event.wait(), 1.0)
        settings = graph.settings_factory.created[-1]
        settings.form_widgets.manage_cache.click()
        dialog = graph.cache_management_factory.created[-1]
        assert dialog.statuses == [LIVE]

        graph.display.status = CACHED
        graph.controller.refresh_cache_status()
        graph.controller.refresh_cache_status()
        assert dialog.statuses == [LIVE, CACHED]
        dialog.close()
        graph.display.status = LyricsDisplayStatus()
        graph.controller.refresh_cache_status()
        assert dialog.statuses == [LIVE, CACHED]

        settings.form_widgets.manage_cache.click()
        reopened = graph.cache_management_factory.created[-1]
        assert reopened.statuses == [LyricsDisplayStatus()]
    finally:
        await graph.close()
