"""Y2K decorations: soap bubbles, twinkling sparkles, and the window backdrop that holds them."""

from __future__ import annotations

import random

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from .theme import current_theme

TINTS = (QColor(255, 143, 207), QColor(183, 156, 255), QColor(111, 198, 255), QColor(127, 230, 200))


def paint_bubble(p: QPainter, centre: QPointF, r: float, tint: QColor, strength: float = 1.0) -> None:
    """A soap bubble: clear middle, a bright rim with a hint of colour, a shine at the top left."""
    body = QRadialGradient(centre, r)
    body.setColorAt(0, QColor(255, 255, 255, int(18 * strength)))
    body.setColorAt(0.78, QColor(tint.red(), tint.green(), tint.blue(), int(30 * strength)))
    body.setColorAt(0.94, QColor(255, 255, 255, int(130 * strength)))
    body.setColorAt(1, QColor(255, 255, 255, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(body)
    p.drawEllipse(centre, r, r)
    shine = QRadialGradient(centre + QPointF(-r * 0.38, -r * 0.42), r * 0.32)
    shine.setColorAt(0, QColor(255, 255, 255, int(200 * strength)))
    shine.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(shine)
    p.drawEllipse(centre + QPointF(-r * 0.38, -r * 0.42), r * 0.32, r * 0.32)


def sparkle_path(centre: QPointF, r: float) -> QPainterPath:
    """A four-pointed twinkle star."""
    pinch = r * 0.2
    path = QPainterPath(centre + QPointF(0, -r))
    for x, y in ((pinch, -pinch), (r, 0), (pinch, pinch), (0, r), (-pinch, pinch), (-r, 0), (-pinch, -pinch)):
        path.lineTo(centre + QPointF(x, y))
    path.closeSubpath()
    return path


def paint_sparkle(p: QPainter, centre: QPointF, r: float, color: QColor) -> None:
    glow = QRadialGradient(centre, r * 0.9)
    glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), min(255, color.alpha())))
    glow.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
    p.setPen(Qt.NoPen)
    p.setBrush(glow)
    p.drawEllipse(centre, r * 0.9, r * 0.9)
    p.setBrush(QColor(255, 255, 255, color.alpha()))
    p.drawPath(sparkle_path(centre, r))


class Backdrop(QWidget):
    """The main window's central widget: paints bubbles and sparkles behind everything (Y2K only).

    The see-through panels on top let them show through. The drawing is cached per size,
    since the LCD repaints many times a second and the backdrop shows round its corners.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: QPixmap | None = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._cache = None

    def paintEvent(self, event) -> None:
        if current_theme() != "y2k":
            return
        if self._cache is None or self._cache.size() != self.size() * self.devicePixelRatioF():
            self._cache = self._render()
        p = QPainter(self)  # clipped to the area being repainted
        p.drawPixmap(0, 0, self._cache)

    def _render(self) -> QPixmap:
        ratio = self.devicePixelRatioF()
        pix = QPixmap(self.size() * ratio)
        pix.setDevicePixelRatio(ratio)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        rng = random.Random(2000)  # the same sky every time
        for _ in range(18):
            r = rng.uniform(14, 70)
            paint_bubble(p, QPointF(rng.uniform(0, w), rng.uniform(0, h)), r, rng.choice(TINTS), rng.uniform(0.6, 1.0))
        for _ in range(int(w * h / 22000) + 10):
            tint = rng.choice(TINTS)
            paint_sparkle(p, QPointF(rng.uniform(0, w), rng.uniform(0, h)), rng.uniform(3, 9),
                          QColor(tint.red(), tint.green(), tint.blue(), rng.randint(110, 210)))
        p.end()
        return pix
