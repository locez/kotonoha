"""Keep the active lyric and its translation together without cropping effects."""

from __future__ import annotations

from PyQt6.QtCore import QRect, QSize
from PyQt6.QtWidgets import QLayout, QLayoutItem, QWidget

from .karaoke_label import KaraokeLabel


class LyricPair(QLayout):
    """Lay out two lyric labels with shared space for their transparent margins.

    The labels retain their full paint area for glow and transitions. Only their
    empty edge space overlaps, so the translation reads as part of the lyric.
    """

    def __init__(self, parent: QWidget) -> None:
        """Create and own the active lyric and translation widgets."""
        self._group: QWidget = parent
        super().__init__(parent)
        self.current: KaraokeLabel = KaraokeLabel(parent)
        self.translation: KaraokeLabel = KaraokeLabel(parent)
        self._items: list[QLayoutItem] = []
        self._overlap: int = 0
        self.setContentsMargins(0, 0, 0, 0)
        self.addWidget(self.current)
        self.addWidget(self.translation)

    def configure(self, main_size: int, translation_size: int) -> None:
        """Scale the shared margin with typography, bounded by the paint insets."""
        self._overlap = min(8, round(min(main_size * 0.3, translation_size * 0.55)))
        self.invalidate()

    def addItem(self, a0: QLayoutItem | None) -> None:
        """Take ownership of a Qt layout item."""
        if a0 is not None:
            self._items.append(a0)
            self.invalidate()

    def invalidate(self) -> None:
        """Make text reflow visible to the surface owner before Qt's next layout pass."""
        super().invalidate()
        self._group.updateGeometry()

    def count(self) -> int:
        """Return the number of owned layout items."""
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        """Expose an item to Qt without transferring ownership."""
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        """Transfer an item's ownership to Qt during layout removal."""
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def sizeHint(self) -> QSize:
        """Measure visible rows, including extra lines from fixed-width wrapping."""
        current = self.current.sizeHint()
        if self.translation.isHidden():
            return current
        translation = self.translation.sizeHint()
        return QSize(
            max(current.width(), translation.width()),
            current.height() + translation.height() - self._overlap,
        )

    def minimumSize(self) -> QSize:
        """Preserve enough space to paint every wrapped row."""
        return self.sizeHint()

    def setGeometry(self, a0: QRect) -> None:
        """Center both labels while sharing their transparent vertical margins."""
        super().setGeometry(a0)
        rect = a0
        current = self.current.sizeHint()
        width = min(rect.width(), current.width())
        self.current.setGeometry(rect.x() + (rect.width() - width) // 2, rect.y(), width, current.height())
        if not self.translation.isHidden():
            translation = self.translation.sizeHint()
            width = min(rect.width(), translation.width())
            self.translation.setGeometry(
                rect.x() + (rect.width() - width) // 2, rect.y() + current.height() - self._overlap,
                width, translation.height(),
            )


__all__ = ["LyricPair"]
