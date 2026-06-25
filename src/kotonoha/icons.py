"""Control icons rendered from open-source SVG (Lucide, ISC license).

Lucide <https://lucide.dev> stroke icons, recoloured and rasterised via QtSvg —
crisp monochrome lock / unlock / settings glyphs (no emoji, no hand-drawn paths).
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

ICON_SIZE = 64

_SVG_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
)

# Lucide: lock
_LOCK = _SVG_HEAD + (
    '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
)
# Lucide: lock-open
_UNLOCK = _SVG_HEAD + (
    '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/></svg>'
)
# Lucide: settings-2 (sliders — simpler and robust to render)
_SETTINGS = _SVG_HEAD + (
    '<path d="M20 7h-9"/><path d="M14 17H5"/>'
    '<circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/></svg>'
)


def _render(svg: str, color: str) -> QIcon:
    data = QByteArray(svg.replace("currentColor", color).encode("utf-8"))
    renderer = QSvgRenderer(data)
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def lock_icon(closed: bool, color: str = "#FFFFFF") -> QIcon:
    return _render(_LOCK if closed else _UNLOCK, color)


def settings_icon(color: str = "#FFFFFF") -> QIcon:
    return _render(_SETTINGS, color)
