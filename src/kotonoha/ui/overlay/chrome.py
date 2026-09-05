"""Interactive controls rendered inside the lyrics overlay."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from ...icons import earlier_icon, later_icon, lock_icon, search_icon, settings_icon
from ...strings import Translator

if TYPE_CHECKING:
    from .window import LyricsOverlay

CONTROL_ICON_COLOR = "#9AA0A6"
CONTROL_BUTTON_STYLE = """
QToolButton {
    background: rgba(255, 255, 255, 28);
    color: rgba(255, 255, 255, 210);
    border: none;
    border-radius: 11px;
    font-size: 13px;
}
QToolButton:hover { background: rgba(255, 255, 255, 60); }
QToolButton:pressed { background: rgba(255, 255, 255, 90); }
"""


class IconFactory(Protocol):
    """Create one monochrome control icon for a requested color."""

    def __call__(self, color: str) -> QIcon:
        """Return an icon rendered with ``color``."""
        ...


class OverlayChromeController:
    """Own construction, icon refresh, and visibility of overlay controls."""

    def __init__(self, overlay: LyricsOverlay, translator: Translator) -> None:
        self._overlay = overlay
        self._translator = translator

    def build(self, container: QWidget) -> QWidget:
        """Build the control bar inside the supplied overlay container."""
        overlay = self._overlay
        overlay._control_bar = QWidget(container)
        bar = QHBoxLayout(overlay._control_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)
        bar.addStretch(1)

        overlay._search_btn = QToolButton(container)
        overlay._search_btn.setFixedSize(22, 22)
        overlay._search_btn.setIconSize(QSize(15, 15))
        overlay._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        overlay._search_btn.setStyleSheet(CONTROL_BUTTON_STYLE)
        overlay._search_btn.setToolTip(self._translator.text("overlay.search_lyrics"))
        overlay._search_btn.clicked.connect(overlay._request_lyrics_search)
        bar.addWidget(overlay._search_btn)

        overlay._lock_btn = QToolButton(container)
        overlay._lock_btn.setFixedSize(22, 22)
        overlay._lock_btn.setIconSize(QSize(15, 15))
        overlay._lock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        overlay._lock_btn.setStyleSheet(CONTROL_BUTTON_STYLE)
        overlay._lock_btn.clicked.connect(overlay._on_lock_clicked)
        bar.addWidget(overlay._lock_btn)

        # The arrows describe the direction the lyrics should move on the
        # timeline: the left arrow delays lyrics, while the right arrow advances
        # them. Keep the action-owned fields named for their timing effect.
        overlay._later_btn = self._make_offset_button(container, earlier_icon, "overlay.offset.later")
        overlay._later_btn.clicked.connect(overlay._on_later_clicked)
        bar.addWidget(overlay._later_btn)
        overlay._earlier_btn = self._make_offset_button(container, later_icon, "overlay.offset.earlier")
        overlay._earlier_btn.clicked.connect(overlay._on_earlier_clicked)
        bar.addWidget(overlay._earlier_btn)

        overlay._settings_btn = QToolButton(container)
        overlay._settings_btn.setFixedSize(22, 22)
        overlay._settings_btn.setIconSize(QSize(15, 15))
        overlay._settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        overlay._settings_btn.setStyleSheet(CONTROL_BUTTON_STYLE)
        overlay._settings_btn.setToolTip(self._translator.text("overlay.settings"))
        overlay._settings_btn.clicked.connect(overlay._on_settings_clicked)
        bar.addWidget(overlay._settings_btn)
        self.update_icons()
        return overlay._control_bar

    def update_icons(self) -> None:
        """Refresh all control icons after lock state or panel style changes."""
        overlay = self._overlay
        color = self._control_icon_color()
        overlay._search_btn.setIcon(search_icon(color))
        overlay._lock_btn.setIcon(lock_icon(overlay._passthrough, color))
        overlay._lock_btn.setToolTip(
            self._translator.text("overlay.locked")
            if overlay._passthrough
            else self._translator.text("overlay.unlocked")
        )
        overlay._earlier_btn.setIcon(later_icon(color))
        overlay._later_btn.setIcon(earlier_icon(color))
        overlay._settings_btn.setIcon(settings_icon(color))

    def update_track(self, has_track: bool) -> None:
        """Enable lyric search only while the display has a searchable track."""
        self._overlay._search_btn.setEnabled(has_track)

    def update_visibility(self) -> None:
        """Hide controls while click-through mode is active."""
        overlay = self._overlay
        visible = not overlay._passthrough
        overlay._control_bar.setVisible(visible)
        overlay._search_btn.setVisible(visible)
        overlay._earlier_btn.setVisible(visible)
        overlay._later_btn.setVisible(visible)
        overlay.update()

    def _control_icon_color(self) -> str:
        return "#5F6368" if self._overlay._config.panel_style == "white" else CONTROL_ICON_COLOR

    def _make_offset_button(self, container: QWidget, icon_factory: IconFactory, tooltip_key: str) -> QToolButton:
        button = QToolButton(container)
        button.setFixedSize(22, 22)
        button.setIconSize(QSize(15, 15))
        button.setIcon(icon_factory(CONTROL_ICON_COLOR))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(CONTROL_BUTTON_STYLE)
        button.setToolTip(self._translator.text(tooltip_key))
        return button


__all__ = ["OverlayChromeController"]
