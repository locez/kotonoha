"""Device-scaled, stateless raster transformations shared by lyric effects."""

from math import ceil, exp

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QImage, QPainter


def blur_image(source: QImage, sigma: float) -> QImage:
    """Return a Gaussian blur with sigma measured in logical pixels.

    This is a stateless image transformation. Sixteen-bit channels retain faint
    tails while accumulating weighted samples; only the result uses eight bits.
    Callers cache the result instead of convolving on animation/progress ticks.
    """
    if sigma <= 0.0:
        return source.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    ratio = source.devicePixelRatioF()
    device_sigma = sigma * ratio
    radius = ceil(3.0 * device_sigma)
    weights = [exp(-0.5 * (offset / device_sigma) ** 2) for offset in range(-radius, radius + 1)]
    total = sum(weights)
    for horizontal in (True, False):
        target = QImage(source.size(), source.format())
        target.setDevicePixelRatio(ratio)
        target.fill(Qt.GlobalColor.transparent)
        with QPainter(target) as painter:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            for offset, weight in zip(range(-radius, radius + 1), weights, strict=True):
                painter.setOpacity(weight / total)
                shift = offset / ratio
                painter.drawImage(QPointF(shift, 0.0) if horizontal else QPointF(0.0, shift), source)
        source = target
    return source.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
