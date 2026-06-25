"""System tray icon and menu.

Deliberately lean: the detailed configuration lives in the tabbed settings panel
(see settings_dialog.py). The tray offers only the quick toggle most useful while
the overlay is click-through (lock/unlock), plus Settings and Quit. Left-clicking
the tray icon also toggles the lock, since that is the one action you cannot
perform on the HUD itself while it is passing clicks through.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


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


def load_icon() -> QIcon:
    asset = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
    if os.path.exists(asset):
        icon = QIcon(asset)
        if not icon.isNull():
            return icon
    return _fallback_icon()


class KotonohaTray(QSystemTrayIcon):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        passthrough: bool,
        on_toggle_passthrough: Callable[[bool], None],
        on_open_settings: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._on_toggle_passthrough = on_toggle_passthrough
        self.setIcon(load_icon())
        self.setToolTip("Kotonoha — lyrics overlay")

        menu = QMenu()

        self._lock_action = QAction("锁定 / 鼠标穿透", menu)
        self._lock_action.setCheckable(True)
        self._lock_action.setChecked(passthrough)
        self._lock_action.toggled.connect(on_toggle_passthrough)
        menu.addAction(self._lock_action)

        menu.addSeparator()

        settings_action = QAction("设置…", menu)
        settings_action.triggered.connect(lambda: on_open_settings())
        menu.addAction(settings_action)

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(lambda: on_quit())
        menu.addAction(quit_action)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left-click toggles the lock — the quick unlock affordance for a
        # click-through overlay.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_toggle_passthrough(not self._lock_action.isChecked())

    def set_passthrough_checked(self, checked: bool) -> None:
        self._lock_action.setChecked(checked)
