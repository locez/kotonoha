"""Generate the Kotonoha leaf tray icon in three styles, on demand.

The bundled ``logo.svg`` (bare leaf) and ``logo-tile.svg`` (leaf on a rounded
tile) are re-coloured at runtime so the tray/window icon can follow the custom
accent or adapt to the system light/dark theme, instead of shipping a fixed
pixmap per variant. Keys are prefixed ``@`` so they never collide with the
file-based icon choices.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_ASSETS = Path(__file__).with_name("assets")
_LEAF = _ASSETS / "logo.svg"        # bare leaf: 3 green shades + a white "lyrics" motif
_LEAF_SHADES = ("#60a65a", "#a4d382", "#def1d3")  # dark, mid, light
_WHITE = "#fcfcfc"
# Tight bounds of the leaf inside logo.svg's 1254x1254 viewBox (the leaf sits high
# and doesn't fill the box, so rendering the whole viewBox looks tilted upward).
_VIEWBOX = 1254.0
_LEAF_BBOX = (242.0, 134.0, 770.0, 711.0)  # x, y, w, h

ACCENT = "@leaf-accent"   # leaf recoloured to the accent
MONO = "@leaf-mono"       # black/white leaf, adapts to the system theme
TILE = "@leaf-tile"       # white leaf on an accent-coloured rounded tile
GENERATED: tuple[str, ...] = (ACCENT, MONO, TILE)


def is_generated(key: str) -> bool:
    return key in GENERATED


def system_is_dark() -> bool:
    """True when the system colour scheme is dark (so a light tray icon suits the
    panel). Defaults to dark when the scheme is unknown or before the app exists."""
    app = QGuiApplication.instance()
    hints = app.styleHints() if app is not None else None
    scheme = hints.colorScheme() if hints is not None else None
    return scheme != Qt.ColorScheme.Light


def _leaf_svg(accent: str, dark_panel: bool, *, mono: bool = False, on_tile: bool = False) -> str:
    """The bare leaf SVG re-coloured for a style: accent-shaded, flat mono (theme
    adaptive), or white-with-accent-motif for use on a tile."""
    svg = _LEAF.read_text(encoding="utf-8")
    if on_tile:
        for shade in _LEAF_SHADES:  # white leaf, accent lyrics-motif, sits on the tile
            svg = svg.replace(shade, "#ffffff")
        return svg.replace(_WHITE, QColor(accent).name())
    if mono:
        leaf, motif = ("#ECECEC", "#9AA0A6") if dark_panel else ("#3A3A3A", "#8A8A8A")
        for shade in _LEAF_SHADES:
            svg = svg.replace(shade, leaf)
        return svg.replace(_WHITE, motif)
    tone = QColor(accent)  # accent dark/mid/light, keep the white motif
    for old, new in zip(_LEAF_SHADES, (tone.darker(135).name(), tone.name(), tone.lighter(158).name()), strict=True):
        svg = svg.replace(old, new)
    return svg


def _blit_leaf(painter: QPainter, renderer: QSvgRenderer, size: int, margin_frac: float) -> None:
    """Render the leaf so its OWN bounding box (not the whole viewBox) is centred in
    the pixmap with a margin, so it never looks shifted up or crooked."""
    _bx, _by, bw, bh = _LEAF_BBOX
    scale = (size * (1.0 - 2.0 * margin_frac)) / max(bw, bh)
    leaf_cx = (_bx + bw / 2.0) * scale
    leaf_cy = (_by + bh / 2.0) * scale
    renderer.render(
        painter,
        QRectF(size / 2.0 - leaf_cx, size / 2.0 - leaf_cy, _VIEWBOX * scale, _VIEWBOX * scale),
    )


def render_leaf(style: str, accent: str = "#FF4FA3", *, dark_panel: bool = True, size: int = 64) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if style == TILE:
        # A rounded accent tile with a white (accent-motif) leaf centred on top.
        painter.setBrush(QColor(accent))
        painter.setPen(Qt.PenStyle.NoPen)
        radius = size * 0.22
        painter.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), radius, radius)
        renderer = QSvgRenderer(QByteArray(_leaf_svg(accent, dark_panel, on_tile=True).encode("utf-8")))
        _blit_leaf(painter, renderer, size, margin_frac=0.24)
    else:
        renderer = QSvgRenderer(QByteArray(_leaf_svg(accent, dark_panel, mono=(style == MONO)).encode("utf-8")))
        _blit_leaf(painter, renderer, size, margin_frac=0.10)
    painter.end()
    return pixmap


def leaf_qicon(style: str, accent: str = "#FF4FA3", *, dark_panel: bool = True) -> QIcon:
    return QIcon(render_leaf(style, accent, dark_panel=dark_panel, size=128))
