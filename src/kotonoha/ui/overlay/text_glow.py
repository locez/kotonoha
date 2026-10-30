"""Cache softly blurred lyric rows independently of their moving karaoke sweep."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter

from .text_layout import TextRow
from .text_raster import blur_image


@dataclass(frozen=True)
class _RasterKey:
    """Raster inputs that can change without replacing the shaped lyric."""

    width: float
    height: float
    pixel_ratio: float
    sigma: float
    color: int


@dataclass(frozen=True)
class _GlowRaster:
    """A padded, device-scaled image owned by the current lyric's cache."""

    key: _RasterKey
    image: QImage
    padding: int


class TextGlow:
    """Own one blurred raster per current lyric row; never blur on progress ticks.

    The label supplies its text painter so the halo uses the same shaping as the
    sharp foreground. It must clear the cache when text, font, or layout changes.
    """

    def __init__(self, draw_text: Callable[[QPainter, QRectF, TextRow | None], None]) -> None:
        """Borrow the label's drawing callback; all cached images belong here."""
        self._draw_text: Callable[[QPainter, QRectF, TextRow | None], None] = draw_text
        self._rows: dict[int, _GlowRaster] = {}

    def clear(self) -> None:
        """Release the previous lyric's rasters after a shaping/style change."""
        self._rows.clear()

    def paint(
        self,
        painter: QPainter,
        rect: QRectF,
        row: TextRow | None,
        *,
        sweep: float,
        color: QColor,
        sigma: float,
        opacity: float,
    ) -> None:
        """Paint a feathered sung portion behind the foreground at device scale."""
        if sweep <= 0.0 or opacity <= 0.0:
            return
        device = painter.device()
        if device is None:
            return
        ratio = device.devicePixelRatioF()
        key = _RasterKey(rect.width(), rect.height(), ratio, sigma, color.rgba())
        row_id = row.line.textStart() if row is not None else 0
        raster = self._rows.get(row_id)
        if raster is None or raster.key != key:
            raster = self._rasterize(key, painter.font(), color, row)
            self._rows[row_id] = raster

        origin = QPointF(rect.left() - raster.padding, rect.top() - raster.padding)
        # Copy only the visible, sung part. The expensive blur is cached; masking
        # this small image gives the moving edge a soft falloff without lighting
        # the rest of the line or clipping the halo at the first/last glyph.
        feather = sigma * 2.0
        edge = raster.padding + sweep
        left = max(0, int(-origin.x() * ratio))
        complete = sweep >= rect.width()
        right = raster.image.width() if complete else min(raster.image.width(), ceil((edge + feather) * ratio))
        right = min(right, ceil((painter.viewport().width() - origin.x()) * ratio))
        if right <= left:
            return
        visible = raster.image.copy(left, 0, right - left, raster.image.height())
        visible.setDevicePixelRatio(ratio)
        if not complete:
            mask = QLinearGradient(edge - feather - left / ratio, 0.0, edge + feather - left / ratio, 0.0)
            mask.setColorAt(0.0, QColor(0, 0, 0, 255))
            mask.setColorAt(1.0, QColor(0, 0, 0, 0))
            with QPainter(visible) as mask_painter:
                mask_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
                mask_painter.fillRect(QRectF(0.0, 0.0, visible.width() / ratio, visible.height() / ratio), mask)
        painter.save()
        painter.setOpacity(painter.opacity() * opacity)
        painter.drawImage(origin + QPointF(left / ratio, 0.0), visible)
        painter.restore()

    def _rasterize(self, key: _RasterKey, font: QFont, color: QColor, row: TextRow | None) -> _GlowRaster:
        """Rasterize once with room for the Gaussian tail on all four sides."""
        padding = ceil(3.0 * key.sigma)
        image = QImage(
            ceil((key.width + padding * 2) * key.pixel_ratio),
            ceil((key.height + padding * 2) * key.pixel_ratio),
            QImage.Format.Format_RGBA64_Premultiplied,
        )
        image.setDevicePixelRatio(key.pixel_ratio)
        image.fill(Qt.GlobalColor.transparent)
        with QPainter(image) as painter:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setFont(font)
            painter.setPen(color)
            self._draw_text(painter, QRectF(padding, padding, key.width, key.height), row)
        # A narrow halo keeps the light close to the strokes; the wider bloom
        # supplies the visible falloff. Neither layer replaces the sharp text.
        outer = blur_image(image, key.sigma)
        bloom = outer.copy()
        core = blur_image(image, 2.0)
        with QPainter(bloom) as painter:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            painter.setOpacity(0.65)
            painter.drawImage(QPointF(0.0, 0.0), outer)
            painter.setOpacity(0.85)
            painter.drawImage(QPointF(0.0, 0.0), core)
        return _GlowRaster(key, bloom, padding)
