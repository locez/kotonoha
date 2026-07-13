"""A single lyric line rendered with a left-to-right karaoke sweep.

The "sung" portion is filled with a pink gradient and the rest stays a dim
white; the word currently being sung is brightened with the accent-sweep colour.
The sweep boundary is computed from per-word timing when available (stopping
mid-word), or from the line's overall progress otherwise. The widget is
repainted at ~60fps by the overlay as the media clock advances.

On a line change the text fades in and rises a few pixels (``reveal`` animated
property), driven by a QPropertyAnimation rather than a QGraphicsEffect so it
does not clash with the overlay's drop-shadow glow.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from PyQt6 import QtCore
from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from .karaoke import line_progress, word_fill_fraction
from .model import LyricLine

UNSUNG_COLOR = QColor(255, 255, 255, 95)
SHADOW_COLOR = QColor(0, 0, 0, 170)
SHADOW_OFFSET = 1.5
REVEAL_RISE_PX = 9.0
REVEAL_DURATION_MS = 320

class _PyqtPropertyFactory(Protocol):
    def __call__(self, type_: object, *, fget: object, fset: object) -> Any: ...


pyqt_property = cast(_PyqtPropertyFactory, cast(Any, QtCore).pyqtProperty)



def _scale_alpha(color: QColor, factor: float) -> QColor:
    out = QColor(color)
    out.setAlpha(max(0, min(255, int(color.alpha() * factor))))
    return out


class KaraokeLabel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._line: LyricLine | None = None
        self._word_mode = False
        self._media_time: float | None = None
        self._font = QFont()
        self._accent_start = QColor("#FF4FA3")
        self._accent_end = QColor("#FF8FCB")
        self._accent_sweep = QColor("#FF6EC7")
        self._reveal = 1.0
        self._anim: QPropertyAnimation | None = None
        # Cached text measurements (rebuilt only when font/line changes, never per
        # frame) so the 60fps sweep paint stays cheap.
        self._fm = QFontMetrics(self._font)
        self._word_widths: list[float] = []
        self._space_w = 0.0
        self._total_w = 0.0
        self._max_width = 0  # 0 = unlimited; else cap the width and scroll long lines
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    # --- configuration ---

    def set_style(self, font: QFont, accent_start: str, accent_end: str, accent_sweep: str) -> None:
        self._font = font
        self._accent_start = QColor(accent_start)
        self._accent_end = QColor(accent_end)
        self._accent_sweep = QColor(accent_sweep)
        self._fm = QFontMetrics(self._font)
        self._rebuild_layout()
        self.updateGeometry()
        self.update()

    def set_line(self, line: LyricLine | None, word_mode: bool) -> None:
        prev_id = self._line.id if self._line else None
        new_id = line.id if line else None
        self._line = line
        self._word_mode = word_mode and line is not None and line.has_word_timing
        self._rebuild_layout()
        if new_id is not None and new_id != prev_id:
            self._start_reveal()
        self.updateGeometry()
        self.update()

    def _rebuild_layout(self) -> None:
        text = self.text
        self._total_w = self._fm.horizontalAdvance(text) if text else 0.0
        self._space_w = self._fm.horizontalAdvance(" ")
        self._word_widths = (
            [self._fm.horizontalAdvance(w.text) for w in self._line.words] if self._line else []
        )

    def set_media_time(self, media_time: float | None) -> None:
        self._media_time = media_time
        self.update()

    def set_max_width(self, width: int) -> None:
        """Cap the label width; longer lines scroll horizontally. 0 = unlimited."""
        width = max(0, width)
        if width != self._max_width:
            self._max_width = width
            self.updateGeometry()
            self.update()

    # --- reveal animation ---

    def _get_reveal(self) -> float:
        return self._reveal

    def _set_reveal(self, value: float) -> None:
        self._reveal = value
        self.update()

    reveal = pyqt_property(float, fget=_get_reveal, fset=_set_reveal)

    def _start_reveal(self) -> None:
        # Reuse a single animation instance; creating a new one per line change
        # leaked a stopped QPropertyAnimation (parented to this label) every time.
        if self._anim is None:
            anim = QPropertyAnimation(self, b"reveal", self)
            anim.setDuration(REVEAL_DURATION_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            # OutQuint eases in fast then settles very gently, so the new line
            # glides into place instead of snapping — softer than OutCubic.
            anim.setEasingCurve(QEasingCurve.Type.OutQuint)
            self._anim = anim
        self._anim.stop()
        self._reveal = 0.0
        self._anim.start()

    # --- geometry ---

    @property
    def text(self) -> str:
        return self._line.text if self._line else ""

    def sizeHint(self) -> QSize:
        width = int(self._total_w) + 8
        if self._max_width:
            width = min(width, self._max_width)
        return QSize(max(1, width), self._fm.height() + 6)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # --- sweep geometry ---

    def _compute_sweep(self, text_left: float, total_width: float) -> tuple[float, tuple[float, float] | None]:
        """Return (sweep_x, active_word_range).

        ``sweep_x`` is the absolute x up to which the line is sung. When a word
        is mid-sing, ``active_word_range`` is the (x0, x1) sub-range of that word
        already sung, to be brightened with the accent-sweep colour. Uses cached
        word widths (no per-frame text measurement).
        """
        line = self._line
        if line is None or self._media_time is None:
            return text_left, None
        t = self._media_time

        if not self._word_mode:
            return text_left + total_width * line_progress(line, t), None

        cursor = text_left
        space = self._space_w
        sung = text_left
        for i, word in enumerate(line.words):
            w = self._word_widths[i] if i < len(self._word_widths) else 0.0
            if word.start is not None and word.end is not None:
                frac = word_fill_fraction(word, t)
                if 0.0 < frac < 1.0:
                    edge = cursor + w * frac
                    return edge, (cursor, edge)
                if frac < 1.0:
                    return sung, None  # a timed word not yet reached -> stop here
            # A fully-sung timed word, or an untimed word (transparent to the
            # sweep, e.g. punctuation), extends the sung run so an untimed word
            # mid-line does not freeze the sweep for the rest of the line.
            sung = cursor + w
            cursor += w
            if i < len(line.words) - 1:
                cursor += space
                sung = cursor  # extend through the trailing space
        return sung, None

    # --- painting ---

    def paintEvent(self, a0: QPaintEvent | None) -> None:  # noqa: ARG002
        if not self.text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self._font)
        # Fade in + rise on a line change.
        painter.translate(0.0, (1.0 - self._reveal) * REVEAL_RISE_PX)
        a = self._reveal

        total_width = self._total_w
        avail = float(self.width())
        height = float(self.height())

        # Sweep position relative to the text start (measure with text_left = 0).
        sweep_rel, active_rel = self._compute_sweep(0.0, total_width)

        if total_width <= avail:
            text_left = (avail - total_width) / 2.0  # fits -> centered
        else:
            # Overflow: scroll so the currently-sung position stays near the centre.
            offset = max(0.0, min(sweep_rel - avail / 2.0, total_width - avail))
            text_left = -offset
            painter.setClipRect(QRectF(0.0, 0.0, avail, height))

        sweep_x = sweep_rel + text_left
        rect = QRectF(text_left, 0.0, total_width, height)
        align = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # 0) Cheap drop shadow (single offset dark pass) for readability.
        painter.save()
        painter.translate(SHADOW_OFFSET, SHADOW_OFFSET)
        painter.setPen(QPen(_scale_alpha(SHADOW_COLOR, a)))
        painter.drawText(rect, align, self.text)
        painter.restore()

        # 1) Base (unsung) text.
        painter.setPen(QPen(_scale_alpha(UNSUNG_COLOR, a)))
        painter.drawText(rect, align, self.text)

        # 2) Sung text, clipped to the sweep boundary, filled with the accent gradient.
        if sweep_x > text_left:
            painter.save()
            painter.setClipRect(QRectF(text_left, 0.0, sweep_x - text_left, height), Qt.ClipOperation.IntersectClip)
            gradient = QLinearGradient(text_left, 0.0, text_left + total_width, 0.0)
            gradient.setColorAt(0.0, _scale_alpha(self._accent_start, a))
            gradient.setColorAt(1.0, _scale_alpha(self._accent_end, a))
            painter.setPen(QPen(QBrush(gradient), 0))
            painter.drawText(rect, align, self.text)
            painter.restore()

        # 3) Currently-sung word: brighten its sung sub-range with the sweep colour.
        if active_rel is not None:
            x0 = active_rel[0] + text_left
            x1 = active_rel[1] + text_left
            if x1 > x0:
                painter.save()
                painter.setClipRect(QRectF(x0, 0.0, x1 - x0, height), Qt.ClipOperation.IntersectClip)
                painter.setPen(QPen(_scale_alpha(self._accent_sweep, a)))
                painter.drawText(rect, align, self.text)
                painter.restore()
