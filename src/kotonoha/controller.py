"""Application controller: owns the long-lived objects and wires interactions.

Separated from main.py so the wiring is import-testable without spinning up a
real Qt event loop.
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import QApplication

from .config import Config, save_config
from .i18n import resolve_translation_language
from .overlay import LyricsOverlay
from .providers.gate import SourceGate
from .providers.mpris import MprisProvider
from .receiver import LyricsReceiver
from .settings_dialog import SettingsDialog
from .state import LyricsState
from .tray import KotonohaTray

logger = logging.getLogger(__name__)


class AppController:
    def __init__(self, app: QApplication, config: Config) -> None:
        self._app = app
        cli_port = app.property("cli_port")
        if isinstance(cli_port, int):
            config = config.clamped()
            config.port = cli_port
        self._config = config

        self._state = LyricsState()
        self._overlay = LyricsOverlay(self._state, config)
        self._gate = SourceGate()
        self._receiver = LyricsReceiver(
            self._state,
            port=config.port,
            translation_language=resolve_translation_language(config.translation_language),
            gate=self._gate,
        )
        self._mpris = MprisProvider(self._state, lyrics_sources=config.lyrics_sources, gate=self._gate)
        self._settings_dialog: SettingsDialog | None = None

        self._tray = KotonohaTray(
            passthrough=config.passthrough,
            on_toggle_passthrough=self._on_toggle_passthrough,
            on_open_settings=self._open_settings,
            on_quit=self._app.quit,
        )

        self._overlay.passthrough_toggle_requested.connect(self._toggle_passthrough)
        self._overlay.settings_requested.connect(self._open_settings)
        self._overlay.position_changed.connect(self._on_position_changed)

    async def start(self) -> None:
        # Promote to a layer surface BEFORE show(): once the window is mapped as a
        # normal xdg surface, LayerShellQt can no longer convert it.
        self._overlay.activate_layer_shell()
        self._overlay.show()
        self._tray.show()
        await self._receiver.start()
        # MPRIS is best-effort: a missing session bus / dbus must not stop the app.
        try:
            await self._mpris.start()
        except Exception as exc:  # noqa: BLE001 - dbus may be unavailable
            logger.warning("MPRIS provider unavailable: %s", exc)
        logger.info("Kotonoha started on port %d", self._config.port)

    async def stop(self) -> None:
        await self._mpris.stop()
        await self._receiver.stop()

    # --- passthrough / lock ---

    def _toggle_passthrough(self) -> None:
        self._on_toggle_passthrough(not self._config.passthrough)

    def _on_toggle_passthrough(self, checked: bool) -> None:
        if checked == self._config.passthrough:
            self._overlay.set_passthrough(checked)
            return
        self._overlay.set_passthrough(checked)
        self._tray.set_passthrough_checked(checked)
        self._config.passthrough = checked
        self._persist()

    def _on_position_changed(self, margin_edge: int, margin_x: int) -> None:
        self._config.margin_edge = margin_edge
        self._config.margin_x = margin_x
        self._persist()

    # --- settings ---

    def _open_settings(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(self._config)
        dialog.applied.connect(self._apply_config)
        dialog.finished.connect(lambda _: self._clear_dialog())
        self._settings_dialog = dialog
        dialog.show()

    def _clear_dialog(self) -> None:
        self._settings_dialog = None

    def _apply_config(self, config: Config) -> None:
        previous_language = resolve_translation_language(self._config.translation_language)
        self._config = config
        self._overlay.apply_config(config)
        # Push new anchor/margins/passthrough through the layer-shell bridge.
        self._overlay.activate_layer_shell()
        self._tray.set_passthrough_checked(config.passthrough)
        self._mpris.set_lyrics_sources(config.lyrics_sources)

        new_language = resolve_translation_language(config.translation_language)
        if new_language != previous_language:
            self._receiver.update_translation_language(new_language)

        self._persist()

    def _persist(self) -> None:
        try:
            save_config(self._config)
        except OSError as exc:
            logger.warning("Could not save config: %s", exc)

    # --- accessors for tests ---

    @property
    def overlay(self) -> LyricsOverlay:
        return self._overlay

    @property
    def state(self) -> LyricsState:
        return self._state

    @property
    def receiver(self) -> LyricsReceiver:
        return self._receiver
