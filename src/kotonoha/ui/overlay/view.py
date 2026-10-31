"""Build the overlay's Qt controls without owning its application state."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .chrome import OverlayChromeController
from .context_label import ContextLabel
from .karaoke_label import KaraokeLabel
from .lyric_pair import LyricPair


@dataclass(frozen=True, slots=True)
class OverlayWidgets:
    """Controls assembled for one overlay window."""

    container: QWidget
    lyric_pair: LyricPair
    previous: ContextLabel
    current: KaraokeLabel
    feedback: QLabel
    translation: KaraokeLabel
    next: ContextLabel


class OverlayViewBuilder:
    """Assemble the overlay view and return its owned controls."""

    def __init__(self, owner: QWidget, chrome: OverlayChromeController) -> None:
        """Bind construction to the overlay widget and its chrome owner."""
        self._owner = owner
        self._chrome = chrome

    def build(self) -> OverlayWidgets:
        """Create the pill, lyric labels, controls, and stable root layout."""
        container = QWidget(self._owner)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(22, 10, 22, 8)
        layout.setSpacing(2)
        layout.addWidget(self._chrome.build(container))

        previous = ContextLabel(previous=True, parent=container)
        lyric_group = QWidget(container)
        lyric_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        lyric_pair = LyricPair(lyric_group)
        feedback = self._feedback_label()
        next_label = ContextLabel(previous=False, parent=container)
        for widget in (previous, lyric_group, next_label, feedback):
            layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignHCenter)
        for label in (previous, feedback, next_label):
            label.setGraphicsEffect(self._text_shadow())

        root = QVBoxLayout(self._owner)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addStretch(1)
        root.addWidget(container, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(1)
        return OverlayWidgets(
            container, lyric_pair, previous, lyric_pair.current, feedback, lyric_pair.translation, next_label,
        )

    def _context_label(self) -> QLabel:
        """Create a centered translucent label for surrounding lyric context."""
        label = QLabel("")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        return label

    def _feedback_label(self) -> QLabel:
        """Create a reserved status row that cannot replace the current lyric."""
        label = self._context_label()
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        label.setFixedHeight(20)
        return label

    def _text_shadow(self) -> QGraphicsDropShadowEffect:
        """Create the low-cost halo used by context labels."""
        shadow = QGraphicsDropShadowEffect(self._owner)
        shadow.setBlurRadius(8)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(0, 0, 0, 200))
        return shadow

__all__ = ["OverlayViewBuilder", "OverlayWidgets"]
