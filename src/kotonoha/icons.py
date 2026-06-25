"""Monochrome control icons drawn with QPainter.

Avoids the platform colour-emoji font (which renders 🔒 as a yellow glyph) by
painting simple single-colour padlock and settings icons we fully control.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

ICON_SIZE = 44


def _canvas() -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def lock_icon(closed: bool, color: str = "#FFFFFF") -> QIcon:
    """A padlock: closed (shackle down) or open (shackle raised and tilted)."""
    s = ICON_SIZE
    pixmap, painter = _canvas()
    col = QColor(color)

    # Body
    body_w, body_h = s * 0.52, s * 0.40
    body_x, body_y = (s - body_w) / 2.0, s * 0.50
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(col)
    painter.drawRoundedRect(QRectF(body_x, body_y, body_w, body_h), s * 0.06, s * 0.06)

    # Keyhole (punched out as a transparent dot + slot)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    hole = s * 0.10
    painter.setBrush(QColor(0, 0, 0, 0))
    painter.drawEllipse(QRectF(s / 2.0 - hole / 2.0, body_y + body_h * 0.28, hole, hole))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    # Shackle (upper half-ring + two legs)
    shackle_w = body_w * 0.66
    shackle_x = (s - shackle_w) / 2.0
    pen = QPen(col, max(2.0, s * 0.095))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if closed:
        top = body_y - shackle_w * 0.62
        painter.drawArc(QRectF(shackle_x, top, shackle_w, shackle_w), 0, 180 * 16)
        leg = top + shackle_w / 2.0
        painter.drawLine(int(shackle_x), int(leg), int(shackle_x), int(body_y))
        painter.drawLine(int(shackle_x + shackle_w), int(leg), int(shackle_x + shackle_w), int(body_y))
    else:
        # Raised + tilted: rotate the shackle about its lower-right leg.
        painter.save()
        painter.translate(shackle_x + shackle_w, body_y)
        painter.rotate(-22)
        top = -shackle_w * 1.12
        painter.drawArc(QRectF(-shackle_w, top, shackle_w, shackle_w), 0, 180 * 16)
        painter.drawLine(0, 0, 0, int(top + shackle_w / 2.0))
        painter.drawLine(int(-shackle_w), int(top + shackle_w / 2.0), int(-shackle_w), int(-body_h * 0.2))
        painter.restore()

    painter.end()
    return QIcon(pixmap)


def settings_icon(color: str = "#FFFFFF") -> QIcon:
    """A 'sliders' settings glyph: three horizontal rails with knobs."""
    s = ICON_SIZE
    pixmap, painter = _canvas()
    col = QColor(color)

    rail = QPen(col, max(2.0, s * 0.07))
    rail.setCapStyle(Qt.PenCapStyle.RoundCap)
    margin = s * 0.22
    rows = (s * 0.32, s * 0.5, s * 0.68)
    knobs = (s * 0.68, s * 0.36, s * 0.6)  # knob x per row
    for y, knob_x in zip(rows, knobs, strict=True):
        painter.setPen(rail)
        painter.drawLine(int(margin), int(y), int(s - margin), int(y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(col)
        r = s * 0.085
        painter.drawEllipse(QRectF(knob_x - r, y - r, 2 * r, 2 * r))

    painter.end()
    return QIcon(pixmap)
