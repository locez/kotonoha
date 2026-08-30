"""System tray icon and menu.

Deliberately lean: the detailed configuration lives in the tabbed settings panel
(see the Settings window). The tray offers only the quick toggle most useful while
the overlay is click-through (lock/unlock), plus Settings and Quit. Left-clicking
the tray icon also toggles the lock, since that is the one action you cannot
perform on the HUD itself while it is passing clicks through.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from . import leaf_icon
from .config import DEFAULT_ICON_NAME
from .strings import Translator

ASSETS_DIR = Path(__file__).with_name("assets")
DEFAULT_ICON_PATH = ASSETS_DIR / "icon.png"
ICON_DIR = ASSETS_DIR / "icons"
SUPPORTED_ICON_SUFFIXES = {".png", ".svg"}


@dataclass(frozen=True)
class IconChoice:
    key: str
    path: Path


def _icon_digest(path: Path) -> bytes | None:
    try:
        return hashlib.sha256(path.read_bytes()).digest()
    except OSError:
        return None


def _fallback_icon() -> QIcon:
    """A pink rounded square with a music note, used when no asset is present."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#FF4FA3"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 16, 16)
    painter.setPen(QColor("white"))
    font = QFont()
    font.setPixelSize(36)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
    painter.end()
    return QIcon(pixmap)


def discover_icon_paths(
    *,
    icon_dir: Path = ICON_DIR,
    default_icon: Path = DEFAULT_ICON_PATH,
) -> tuple[IconChoice, ...]:
    choices: list[IconChoice] = []
    seen: set[bytes] = set()
    if default_icon.is_file():
        choices.append(IconChoice(DEFAULT_ICON_NAME, default_icon))
        digest = _icon_digest(default_icon)
        if digest is not None:
            seen.add(digest)
    try:
        entries = sorted(icon_dir.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        entries = []
    for path in entries:
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_ICON_SUFFIXES:
            continue
        digest = _icon_digest(path)
        if digest is not None and digest in seen:
            continue
        choices.append(IconChoice(path.name, path))
        if digest is not None:
            seen.add(digest)
    return tuple(choices)


def load_icon(
    icon_name: str = DEFAULT_ICON_NAME,
    *,
    accent: str = "#FF4FA3",
    dark_panel: bool | None = None,
    icon_dir: Path = ICON_DIR,
    default_icon: Path = DEFAULT_ICON_PATH,
) -> QIcon:
    # Generated leaf styles (accent / mono / white / black / the tiles) render live.
    if leaf_icon.is_generated(icon_name):
        dark = leaf_icon.system_is_dark() if dark_panel is None else dark_panel
        return leaf_icon.leaf_qicon(icon_name, accent, dark_panel=dark)
    choices = discover_icon_paths(icon_dir=icon_dir, default_icon=default_icon)
    selected = next((choice for choice in choices if choice.key == icon_name), None)
    default = next((choice for choice in choices if choice.key == DEFAULT_ICON_NAME), None)
    for choice in (selected, default):
        if choice is None:
            continue
        icon = QIcon(str(choice.path))
        if not icon.isNull():
            return icon
    return _fallback_icon()


class KotonohaTray(QSystemTrayIcon):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        icon_name: str = DEFAULT_ICON_NAME,
        accent: str = "#FF4FA3",
        passthrough: bool,
        on_toggle_passthrough: Callable[[bool], None] | None = None,
        on_open_settings: Callable[[], None] | None = None,
        on_quit: Callable[[], None],
        translator: Translator | None = None,
    ) -> None:
        super().__init__(parent)
        self._translator = translator if translator is not None else Translator()
        self._on_toggle_passthrough = on_toggle_passthrough
        self._on_open_settings = on_open_settings
        self._handlers_bound = on_toggle_passthrough is not None and on_open_settings is not None
        self._on_quit = on_quit
        self.setIcon(load_icon(icon_name, accent=accent))
        self.setToolTip(self._translator.text("tray.tooltip"))

        menu = QMenu()

        self._lock_action = QAction(self._translator.text("tray.lock"), menu)
        self._lock_action.setCheckable(True)
        self._lock_action.setChecked(passthrough)
        self._lock_action.toggled.connect(self._handle_toggle_passthrough)
        menu.addAction(self._lock_action)

        menu.addSeparator()

        settings_action = QAction(self._translator.text("tray.settings"), menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        quit_action = QAction(self._translator.text("tray.quit"), menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def set_action_handlers(
        self,
        *,
        on_toggle_passthrough: Callable[[bool], None],
        on_open_settings: Callable[[], None],
    ) -> None:
        """Bind application actions once before the tray is shown."""
        if self._handlers_bound:
            raise RuntimeError("tray action handlers are already bound")
        self._on_toggle_passthrough = on_toggle_passthrough
        self._on_open_settings = on_open_settings
        self._handlers_bound = True

    def _handle_toggle_passthrough(self, checked: bool) -> None:
        callback = self._on_toggle_passthrough
        if callback is not None:
            callback(checked)

    def _open_settings(self, checked: bool = False) -> None:
        """Forward the menu action through a bound receiver-owned slot."""
        del checked
        callback = self._on_open_settings
        if callback is not None:
            callback()

    def _quit(self, checked: bool = False) -> None:
        """Forward the quit action through a bound receiver-owned slot."""
        del checked
        self._on_quit()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left-click toggles the lock — the quick unlock affordance for a
        # click-through overlay.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._lock_action.toggle()

    def set_passthrough_checked(self, checked: bool) -> None:
        self._lock_action.setChecked(checked)

    def set_icon_name(self, icon_name: str, accent: str = "#FF4FA3") -> None:
        self.setIcon(load_icon(icon_name, accent=accent))
