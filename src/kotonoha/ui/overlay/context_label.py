"""Scrolling context rows that recede in scale, opacity, and focus."""

from __future__ import annotations

from math import ceil, floor

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QHideEvent, QImage, QPainter, QPaintEvent, QResizeEvent
from PyQt6.QtWidgets import QLabel, QWidget

from ...lyrics.models import LyricLine
from .text_raster import blur_image

_PADDING = 8


class ContextLabel(QLabel):
    """Own visible context rows, their cached rasters, and one transition.

    Lines are supplied nearest-first. QLabel's text remains the nearest line for
    accessibility; painting arranges the rows above or below the active lyric.
    """

    def __init__(self, *, previous: bool, parent: QWidget | None = None) -> None:
        """Create an idle context strip; animations start only on line changes."""
        super().__init__(parent)
        self._previous: bool = previous
        self._lines: tuple[LyricLine, ...] = ()
        self._outgoing: tuple[LyricLine, int] | None = None
        self._count: int = 1
        self._blur: float = 0.0
        self._animate: bool = True
        self._phase: float = 1.0
        self._direction: int = 0
        self._pixel_ratio: float = 0.0
        self._viewport_size: QSize | None = None
        self._sources: dict[str, QImage] = {}
        self._rasters: dict[tuple[str, int], QImage] = {}
        self._animation: QVariantAnimation = QVariantAnimation(self)
        self._animation.setDuration(360)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._advance)
        self._animation.finished.connect(self.stop)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def configure(self, *, count: int, animate: bool, blur: float = 0.0) -> None:
        """Apply row count, motion and 0..1 blur after the label's font and colors."""
        self.ensurePolished()
        self.stop()
        self._count = max(0, count)
        self._blur = max(0.0, min(1.0, blur))
        self._animate = animate
        self._rasters.clear()
        self._sources.clear()
        self.updateGeometry()
        self.update()

    def set_lines(self, lines: tuple[LyricLine, ...], *, direction: int = 0) -> None:
        """Bind nearest-first context; animate adjacent forward/backward steps.

        A zero direction means a seek, track change, or initial binding and is
        shown immediately. Empty rows are retained as space so the current line
        does not jump when the song reaches its first or last line.
        """
        if lines == self._lines:
            return
        count = self._visible_count()
        old = self._lines[:count]
        self.stop()
        self._lines = lines
        super().setText(lines[0].text if lines else "")
        if self._animate and direction in (-1, 1) and old and lines:
            self._direction = direction
            # Preserve the row that leaves the strip so it can slide out instead
            # of disappearing at the start of the transition.
            leaving_near = (direction > 0) != self._previous
            distance = -1 if leaving_near else count
            leaving = old[0] if leaving_near else old[-1]
            if len(old) == count or leaving_near:
                self._outgoing = (leaving, distance)
            self._phase = 0.0
            self._animation.start()
        self._prune_cache()
        self.updateGeometry()
        self.update()

    def stop(self) -> None:
        """Cancel owned animation and settle on the latest context immediately."""
        self._animation.stop()
        self._phase = 1.0
        self._direction = 0
        self._outgoing = None
        self._prune_cache()
        self.update()

    def sizeHint(self) -> QSize:
        """Reserve the configured row count independently of song boundaries."""
        count = self._visible_count()
        if count == 0:
            return QSize(0, 0)
        widths = [self.fontMetrics().horizontalAdvance(line.text) for line in self._lines[:count]]
        width = max(widths, default=0) + 2 * _PADDING
        height = min(self._row_step() * count + 2 * _PADDING, self.maximumHeight())
        return QSize(min(width, self.maximumWidth()), height)

    def minimumSizeHint(self) -> QSize:
        """Keep context rows tall enough for their blur tails."""
        return self.sizeHint()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        """Draw clear glyphs or blend cached blur levels while context scrolls."""
        if not self._lines and self._outgoing is None:
            return
        ratio = self.devicePixelRatioF()
        if ratio != self._pixel_ratio:
            self._pixel_ratio = ratio
            self._rasters.clear()
            self._sources.clear()
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            for distance, line in enumerate(self._lines[:self._visible_count()]):
                self._paint_line(painter, line, distance)
            if self._outgoing is not None:
                self._paint_line(painter, *self._outgoing, leaving=True)

    def hideEvent(self, a0: QHideEvent | None) -> None:
        """Hidden/dismissed overlays must not retain a running transition."""
        self.stop()
        super().hideEvent(a0)

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        """Invalidate elided rasters when the available viewport changes."""
        # Offscreen grabs can report oldSize=(-1,-1) even without a real resize.
        # Track the actual viewport so a repaint neither cancels motion nor
        # discards cached focus levels.
        if a0 is not None and a0.size() != self._viewport_size:
            if self._viewport_size is not None and a0.size().height() != self._viewport_size.height():
                self.stop()
            self._viewport_size = a0.size()
            self._rasters.clear()
            self._sources.clear()
        super().resizeEvent(a0)

    def _advance(self, value: object) -> None:
        """Validate the QVariant value at the Qt signal boundary."""
        if isinstance(value, (float, int)):
            self._phase = float(value)
            self.update()

    def _row_step(self) -> int:
        return self.fontMetrics().height() + 5

    def _visible_count(self) -> int:
        """Bound work by the viewport without changing the user's saved count."""
        capacity = max(0, (self.maximumHeight() - 2 * _PADDING) // self._row_step())
        return min(self._count, capacity)

    def _prune_cache(self) -> None:
        """Retain only rows still visible or leaving in the current transition."""
        rows = [(line, distance) for distance, line in enumerate(self._lines[:self._visible_count()])]
        if self._outgoing is not None:
            rows.append(self._outgoing)
        texts = {line.text for line, _ in rows}
        # A row only blends adjacent depths. Drop its older focus levels as it
        # travels through a large context viewport instead of accumulating them.
        keys = {(line.text, level) for line, distance in rows for level in range(max(0, distance), distance + 3)}
        self._sources = {text: source for text, source in self._sources.items() if text in texts}
        self._rasters = {key: raster for key, raster in self._rasters.items() if key in keys}

    def _paint_line(self, painter: QPainter, line: LyricLine, distance: int, *, leaving: bool = False) -> None:
        motion = self._direction * (1.0 - self._phase)
        depth = max(0.0, distance + 1.0 + (-motion if self._previous else motion))
        row = self._visible_count() - 1 - distance if self._previous else distance
        center_y = _PADDING + (row + motion + 0.5) * self._row_step()
        scale = max(0.60, 1.0 - 0.065 * (depth - 1.0))
        opacity = min(1.4, 0.78 ** (depth - 1.0))
        if leaving:
            opacity *= 1.0 - self._phase
        if opacity * self.palette().windowText().color().alpha() < 1.0:
            return  # The row is below one alpha step; avoid blurring invisible text.
        painter.save()
        painter.translate(self.width() / 2.0, center_y)
        painter.scale(scale, scale)
        if self._blur == 0.0:
            # Raster resampling and blending identical focus levels can soften
            # or dim text even without a Gaussian blur. Shape it at its final
            # position instead, once per row, including during scrolling.
            painter.setOpacity(min(1.0, opacity))
            # Native viewport coordinates preserve Qt's glyph alignment at rest.
            painter.translate(-self.width() / 2.0, -center_y)
            rect = QRectF(0.0, (row + motion) * self._row_step(), self.width(), self._row_step() + 2 * _PADDING)
            self._draw_text(painter, rect, self._elided_text(line.text))
            painter.restore()
            return
        low = floor(depth)
        high = low + 1
        fraction = depth - low
        for level, weight in ((low, 1.0 - fraction), (high, fraction)):
            if weight <= 0.0:
                continue
            key = (line.text, level)
            image = self._rasters.get(key)
            if image is None:
                source = self._sources.get(line.text)
                if source is None:
                    source = self._rasterize(line.text)
                    self._sources[line.text] = source
                # The nearest row must visibly defocus at high slider values.
                # Start at half strength and ease toward full strength with depth.
                depth_blur = 1.0 - 0.5 ** level
                sigma = 3.2 * self._blur * depth_blur
                image = blur_image(source, sigma)
                self._rasters[key] = image
            painter.setOpacity(min(1.0, opacity * weight))
            origin = QPointF(-image.width() / self._pixel_ratio / 2, -image.height() / self._pixel_ratio / 2)
            painter.drawImage(origin, image)
        painter.restore()

    def _rasterize(self, text: str) -> QImage:
        """Shape a visible row once; focus levels are cached lazily as needed."""
        metrics = self.fontMetrics()
        text = self._elided_text(text)
        width = metrics.horizontalAdvance(text) + 2 * _PADDING
        height = metrics.height() + 2 * _PADDING
        image = QImage(
            ceil(width * self._pixel_ratio), ceil(height * self._pixel_ratio),
            QImage.Format.Format_RGBA64_Premultiplied,
        )
        image.setDevicePixelRatio(self._pixel_ratio)
        image.fill(Qt.GlobalColor.transparent)
        with QPainter(image) as painter:
            self._draw_text(painter, QRectF(0.0, 0.0, width, height), text)
        return image

    def _elided_text(self, text: str) -> str:
        """Keep the visible text stable as focus changes its scale or blur."""
        return self.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, max(1, self.width() - 2 * _PADDING),
        )

    def _draw_text(self, painter: QPainter, rect: QRectF, text: str) -> None:
        """Use the same font, color and alignment on the widget and blur rasters."""
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())
        painter.setPen(QColor(self.palette().windowText().color()))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
