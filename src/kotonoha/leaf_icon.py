"""Generate the Kotonoha leaf tray icon in three styles, on demand.

The bundled ``logo.svg`` (bare leaf) and ``logo-tile.svg`` (leaf on a rounded
tile) are re-coloured at runtime so the tray/window icon can follow the custom
accent or adapt to the system light/dark theme, instead of shipping a fixed
pixmap per variant. Keys are prefixed ``@`` so they never collide with the
file-based icon choices.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QByteArray, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
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
WHITE = "@leaf-white"     # solid white leaf (for a dark tray/taskbar)
BLACK = "@leaf-black"     # solid black leaf (for a light tray/taskbar)
TILE = "@leaf-tile"       # white leaf on a full-accent rounded tile
SOFT = "@leaf-soft"       # accent leaf on a pastel (light-accent gradient) tile
PLATE = "@leaf-plate"     # accent leaf on a plain white tile
FRAME = "@leaf-frame"     # accent leaf on a white tile with an accent border

# Everything renderable on the fly (used by is_generated / load_icon). MONO stays
# for configs saved before the explicit black/white styles existed.
GENERATED: tuple[str, ...] = (ACCENT, MONO, WHITE, BLACK, TILE, SOFT, PLATE, FRAME)
# The order and set the settings picker offers: the three bare leaves, then the
# four tile treatments (full accent, soft pastel, white plate, white + frame).
# Adaptive MONO is not offered — black and white are clearer to choose.
PICKER_STYLES: tuple[str, ...] = (ACCENT, WHITE, BLACK, TILE, SOFT, PLATE, FRAME)
_TILE_STYLES = frozenset({TILE, SOFT, PLATE, FRAME})

# Monochrome leaves keep the leaf's depth instead of going flat: the three leaf
# shades (vein, body, underside fold) map to a grey ramp, and the fold inverts
# against the body so the bottom wedge stays visible — a darker wedge on the white
# leaf, a lighter one on the black leaf. The trailing value recolours the lyrics
# motif so it reads against the body. White suits a dark panel, black a light one.
_MONO_RAMPS = {
    #        vein (cls-3)  body (cls-2)  fold (cls-1)  motif (cls-4)
    WHITE: ("#C0C5CD", "#F4F5F6", "#A7ADB7", "#979DA5"),
    BLACK: ("#4A4B51", "#232327", "#5C5D64", "#8A9098"),
}


def is_generated(key: str) -> bool:
    return key in GENERATED


def system_is_dark() -> bool:
    """True when the system colour scheme is dark (so a light tray icon suits the
    panel). Defaults to dark when the scheme is unknown or before the app exists."""
    app = QGuiApplication.instance()
    hints = app.styleHints() if app is not None else None
    scheme = hints.colorScheme() if hints is not None else None
    return scheme != Qt.ColorScheme.Light


def _mix_over_white(color: QColor, frac: float) -> str:
    """Blend `frac` of `color` into white — a light tint used to give the white
    tile leaf faint depth in the family of the tile colour."""
    red = round(255 * (1.0 - frac) + color.red() * frac)
    green = round(255 * (1.0 - frac) + color.green() * frac)
    blue = round(255 * (1.0 - frac) + color.blue() * frac)
    return QColor(red, green, blue).name()


def _leaf_svg(style: str, accent: str, dark_panel: bool) -> str:
    """The bare leaf SVG re-coloured for a style: accent-shaded, an explicit or
    theme-adaptive monochrome, or white-with-accent-motif for use on a tile."""
    svg = _LEAF.read_text(encoding="utf-8")
    if style == TILE:
        # White leaf on the accent tile, but not a flat blob: the vein and fold take
        # a faint wash of the tile colour so the leaf reads with depth (the tile hue
        # showing "through" it); the lyrics motif is the full accent.
        tone = QColor(accent)
        ramp = {
            "#60a65a": _mix_over_white(tone, 0.17),  # vein: light tint (soft shadow)
            "#a4d382": "#ffffff",                     # body: pure white
            "#def1d3": _mix_over_white(tone, 0.09),  # underside fold: fainter still
        }
        for shade, tint in ramp.items():
            svg = svg.replace(shade, tint)
        return svg.replace(_WHITE, tone.name())
    if style == MONO:  # legacy adaptive flat mono (configs saved before white/black)
        leaf, motif = ("#ECECEC", "#9AA0A6") if dark_panel else ("#3A3A3A", "#8A8A8A")
        for shade in _LEAF_SHADES:
            svg = svg.replace(shade, leaf)
        return svg.replace(_WHITE, motif)
    if style in _MONO_RAMPS:
        vein, body, fold, motif = _MONO_RAMPS[style]
        for shade, tone in zip(_LEAF_SHADES, (vein, body, fold), strict=True):
            svg = svg.replace(shade, tone)
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


def _draw_tile(painter: QPainter, accent: str, size: int, style: str) -> None:
    """Paint the rounded tile background for a tile style. TILE is the full accent;
    SOFT is a pale-accent vertical gradient; PLATE is plain white; FRAME is white
    with an accent border."""
    tone = QColor(accent)
    radius = size * 0.22
    if style == FRAME:
        border = max(1.5, size * 0.05)
        inset = 1.0 + border / 2.0
        rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
        pen = QPen(tone)
        pen.setWidthF(border)
        painter.setPen(pen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, radius, radius)
        return
    rect = QRectF(1, 1, size - 2, size - 2)
    painter.setPen(Qt.PenStyle.NoPen)
    if style == TILE:
        painter.setBrush(tone)
    elif style == PLATE:
        painter.setBrush(QColor("#ffffff"))
    else:  # SOFT: near-white at the top easing into a light wash of the accent
        gradient = QLinearGradient(QPointF(0.0, 0.0), QPointF(0.0, float(size)))
        gradient.setColorAt(0.0, QColor(_mix_over_white(tone, 0.05)))
        gradient.setColorAt(1.0, QColor(_mix_over_white(tone, 0.26)))
        painter.setBrush(QBrush(gradient))
    painter.drawRoundedRect(rect, radius, radius)


def render_leaf(style: str, accent: str = "#FF4FA3", *, dark_panel: bool = True, size: int = 64) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if style in _TILE_STYLES:
        _draw_tile(painter, accent, size, style)
        # The full-accent tile carries a white leaf; the light tiles carry the
        # accent-shaded leaf (a coloured leaf on a pale/white ground).
        leaf_style = TILE if style == TILE else ACCENT
        renderer = QSvgRenderer(QByteArray(_leaf_svg(leaf_style, accent, dark_panel).encode("utf-8")))
        _blit_leaf(painter, renderer, size, margin_frac=0.24)
    else:
        renderer = QSvgRenderer(QByteArray(_leaf_svg(style, accent, dark_panel).encode("utf-8")))
        _blit_leaf(painter, renderer, size, margin_frac=0.10)
    painter.end()
    return pixmap


def leaf_qicon(style: str, accent: str = "#FF4FA3", *, dark_panel: bool = True) -> QIcon:
    return QIcon(render_leaf(style, accent, dark_panel=dark_panel, size=128))
