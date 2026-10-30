"""Manual search keeps release metadata from hiding usable word-timed lyrics."""

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton
from test_lyrics_amll import NEW_FILE, Session, row

from kotonoha.app.intents import SearchLyrics
from kotonoha.async_worker import BlockingCallRunner
from kotonoha.config import Config
from kotonoha.display.models import LyricsDisplayStatus
from kotonoha.lyrics.amll import AmllLyricsSource
from kotonoha.lyrics.match import MatchConfidence
from kotonoha.lyrics.search import LyricsSearchQuery
from kotonoha.strings import Translator
from kotonoha.ui.settings.lyrics_search_dialog import LyricsSearchDialog


@pytest.mark.parametrize(
    ("player_album", "lyrics_album", "displayed_album"),
    [
        ("Soundtrack - EP", "Single", "Soundtrack - EP"),
        ("", "Single", "Single"),
    ],
    ids=["player-album", "lyrics-album"],
)
async def test_search_uses_album_only_when_explicitly_entered(
    qapp: QApplication, player_album: str, lyrics_album: str, displayed_album: str,
) -> None:
    """Opening search finds other releases; entering an album still narrows AMLL."""
    translator = Translator("zh-Hans")
    dialog = LyricsSearchDialog(
        Config(), LyricsSearchQuery("Song", "Artist", player_album, 180.0),
        status=LyricsDisplayStatus(lyrics_album=lyrics_album), translator=translator,
    )
    intents: list[object] = []
    dialog.intent_requested.connect(intents.append)
    source = AmllLyricsSource(worker=BlockingCallRunner("test-search-album"))
    # The catalog identifies the same performance under a different release name.
    session = Session(row())
    try:
        dialog.show()
        qapp.processEvents()
        assert len(intents) == 1
        request = intents[0]
        assert isinstance(request, SearchLyrics)
        results = await source.search_artifacts(session, request.query.track_metadata())
        assert len(results) == 1
        assert results[0].provider_song_id == NEW_FILE
        assert results[0].confidence is MatchConfidence.HIGH
        assert any(line.has_word_timing for line in results[0].lines)
        assert request.query == LyricsSearchQuery("Song", "Artist", "", 180.0)

        # The current release remains visible as context above the search fields.
        album_label = dialog.findChild(QLabel, "trackAlbum")
        assert album_label is not None and album_label.text() == displayed_album
        album_edit = next(
            editor for editor in dialog.findChildren(QLineEdit)
            if editor.placeholderText() == translator.text("search.placeholder.album")
        )
        search_button = dialog.findChild(QPushButton, "searchButton")
        assert search_button is not None
        for album, expected_ids in (
            ("Other edition", ()), ("Album", (NEW_FILE,)), ("", (NEW_FILE,)),
        ):
            album_edit.setText(album)
            search_button.click()
            request = intents[-1]
            assert isinstance(request, SearchLyrics)
            assert request.query == LyricsSearchQuery("Song", "Artist", album, 180.0)
            results = await source.search_artifacts(session, request.query.track_metadata())
            assert tuple(result.provider_song_id for result in results) == expected_ids
    finally:
        dialog.close()
        await session.close()
        source.close()
