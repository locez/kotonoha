import json

import pytest

pytest.importorskip("PyQt6.QtCore")
pytest.importorskip("aiohttp")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from kotonoha.lyrics.match import TrackMetadata  # noqa: E402
from kotonoha.providers.gate import SourceGate  # noqa: E402
from kotonoha.receiver import CONFIG_FRAME_TYPE, WS_PATH, LyricsReceiver  # noqa: E402
from kotonoha.state import LyricsState  # noqa: E402

FRAME = {
    "lyrics": {
        "found": True,
        "provider": "Apple Music",
        "timing": "Word",
        "currentTime": 3.0,
        "currentLine": {"index": 1, "id": "L1", "start": 2.0, "end": 4.0, "text": "hello", "translation": "hi"},
    },
    "playback": {"isPlaying": True, "nowPlayingItem": {"attributes": {"name": "Song", "artistName": "X"}}},
}


async def _client(state, **kwargs):
    receiver = LyricsReceiver(state, **kwargs)
    server = TestServer(receiver.build_app())
    client = TestClient(server)
    await client.start_server()
    return client, receiver


async def test_websocket_frame_updates_state():
    state = LyricsState()
    client, _ = await _client(state)
    try:
        ws = await client.ws_connect(WS_PATH)
        await ws.receive()  # consume the config frame
        await ws.send_str(json.dumps(FRAME))
        await ws.close()
    finally:
        await client.close()

    assert state.snapshot.found is True
    assert state.snapshot.title == "Song"
    assert state.snapshot.current is not None
    assert state.snapshot.current.text == "hello"


async def test_config_frame_sent_on_connect():
    state = LyricsState()
    client, _ = await _client(state, translation_language="zh-Hans")
    try:
        ws = await client.ws_connect(WS_PATH)
        msg = await ws.receive_json()
        assert msg["type"] == CONFIG_FRAME_TYPE
        assert msg["translationLanguage"] == "zh-Hans"
        await ws.close()
    finally:
        await client.close()


async def test_update_translation_language_broadcasts():
    state = LyricsState()
    client, receiver = await _client(state, translation_language="en")
    try:
        ws = await client.ws_connect(WS_PATH)
        first = await ws.receive_json()
        assert first["translationLanguage"] == "en"
        receiver.update_translation_language("ja")
        second = await ws.receive_json()
        assert second["translationLanguage"] == "ja"
        await ws.close()
    finally:
        await client.close()


async def test_tick_frame_calibrates_clock_only():
    state = LyricsState()
    ticks = []
    state.time_ticked.connect(lambda ct, ip: ticks.append((ct, ip)))
    client, _ = await _client(state)
    try:
        ws = await client.ws_connect(WS_PATH)
        await ws.receive()  # config frame
        await ws.send_str(json.dumps({"reason": "tick", "currentTime": 12.5, "isPlaying": True}))
        await ws.send_str(json.dumps({"reason": "tick", "currentTime": 13.0, "isPlaying": False}))
        await ws.close()
    finally:
        await client.close()

    assert ticks == [(12.5, True), (13.0, False)]
    assert state.snapshot.found is False  # tick never builds a snapshot


async def test_post_debug_bypass_updates_state():
    state = LyricsState()
    client, _ = await _client(state)
    try:
        resp = await client.post(WS_PATH, data=json.dumps(FRAME))
        assert resp.status == 204
    finally:
        await client.close()

    assert state.snapshot.title == "Song"


async def test_post_malformed_frame_returns_400():
    state = LyricsState()
    client, _ = await _client(state)
    try:
        resp = await client.post(WS_PATH, data="not json{")
        assert resp.status == 400
    finally:
        await client.close()

    assert state.snapshot.found is False


def test_build_app_registers_route():
    app = LyricsReceiver(LyricsState()).build_app()
    assert any(getattr(r.resource, "canonical", "") == WS_PATH for r in app.router.routes())


def test_closed_gate_retains_tick_without_publishing_cider_content():
    state = LyricsState()
    ticks = []
    state.time_ticked.connect(lambda current, playing: ticks.append((current, playing)))
    gate = SourceGate()
    gate.select_external()
    receiver = LyricsReceiver(state, gate=gate)

    assert receiver._ingest(json.dumps(FRAME), client_id=10) is True
    assert receiver._ingest(
        json.dumps({"reason": "tick", "currentTime": 3.0, "isPlaying": True}),
        client_id=10,
    )
    assert state.snapshot.found is False
    assert ticks == []
    assert gate.current_match(TrackMetadata("Song", "X")) is not None
    timing = gate.current_timing(TrackMetadata("Song", "X"))
    assert timing is not None
    assert timing.current_time == 3.0
