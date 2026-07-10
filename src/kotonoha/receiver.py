"""Local WebSocket server that ingests lyric frames from the Cider probe.

The Cider probe (plugins/cider/lyrics) connects as a WebSocket *client* to

    ws://127.0.0.1:28745/kotonoha/cider/lyrics

and pushes one JSON ``ProbePayload`` per frame (on connect, on change, and on a
~500ms heartbeat). Each text frame is parsed into a
:class:`~kotonoha.model.LyricsSnapshot` and written to the shared
:class:`~kotonoha.state.LyricsState`.

Runs on the shared qasync event loop — no extra threads. Bind is localhost-only
for privacy. A single misbehaving client or malformed frame never tears down the
server: it keeps listening so the probe can reconnect at any time.
"""

from __future__ import annotations

import asyncio
import json
import logging

from aiohttp import WSMsgType, web

from .model import parse_payload
from .providers.gate import SourceGate
from .state import LyricsState

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 28745
WS_PATH = "/kotonoha/cider/lyrics"
CONFIG_FRAME_TYPE = "kotonoha/config"


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


class LyricsReceiver:
    def __init__(
        self,
        state: LyricsState,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        translation_language: str = "en",
        gate: SourceGate | None = None,
    ) -> None:
        self._state = state
        self._host = host
        self._port = port
        self._translation_language = translation_language
        self._gate = gate
        self._clients: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None

    def _config_frame(self) -> str:
        return json.dumps({"type": CONFIG_FRAME_TYPE, "translationLanguage": self._translation_language})

    def update_translation_language(self, language: str) -> None:
        """Change the preferred language and push it to connected probes."""
        self._translation_language = language
        for ws in list(self._clients):
            if not ws.closed:
                asyncio.create_task(ws.send_str(self._config_frame()))

    def build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get(WS_PATH, self._handle_ws)
        # Zero-cost debug bypass: `curl -XPOST -d @frame.json ...` to inject a frame.
        app.router.add_post(WS_PATH, self._handle_post)
        return app

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._runner = web.AppRunner(self.build_app())
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("Lyrics receiver listening on ws://%s:%d%s", self._host, self._port, WS_PATH)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def _ingest(self, raw_text: str, *, client_id: int = 0) -> bool:
        """Parse one JSON frame and push it into state. Returns True on success."""
        try:
            payload = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError):
            logger.debug("Dropped non-JSON frame (%d bytes)", len(raw_text))
            return False
        # Lightweight high-frequency tick: only calibrate the clock, do not
        # rebuild lyric content.
        if isinstance(payload, dict) and payload.get("reason") == "tick":
            if self._gate is None or self._gate.accepts(client_id):
                self._state.tick(_coerce_float(payload.get("currentTime")), _coerce_bool(payload.get("isPlaying")))
            return True
        snapshot = parse_payload(payload)
        if self._gate is not None:
            self._gate.observe_snapshot(client_id, snapshot)
            if not self._gate.accepts(client_id):
                return True
        self._state.update(snapshot)
        return True

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        client_id = id(ws)
        self._clients.add(ws)
        logger.debug("Probe connected")
        # Tell the probe which translation language to extract from the TTML.
        await ws.send_str(self._config_frame())
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    self._ingest(msg.data, client_id=client_id)
                elif msg.type == WSMsgType.ERROR:
                    logger.debug("WS connection error: %s", ws.exception())
                    break
        finally:
            self._clients.discard(ws)
            if self._gate is not None:
                self._gate.drop_client(client_id)
        logger.debug("Probe disconnected")
        return ws

    async def _handle_post(self, request: web.Request) -> web.Response:
        body = await request.text()
        ok = self._ingest(body)
        return web.Response(status=204 if ok else 400)
