"""Transport icons drawn as vectors, so they never depend on a font having the glyph.

Shapes live on a 24 x 24 grid and are rendered at 2x for sharp edges on any
screen, in whatever colour the theme asks for.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

SCALE = 2


def _poly(*points: tuple[float, float]) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def _arrow_head(p: QPainter, tip: tuple[float, float], direction: int) -> None:
    """A small filled head at ``tip``, pointing right (1) or left (-1)."""
    x, y = tip
    p.drawPolygon(_poly((x, y), (x - 4.5 * direction, y - 3.5), (x - 4.5 * direction, y + 3.5)))


def _draw(p: QPainter, name: str) -> None:
    if name == "play":
        p.drawPolygon(_poly((7, 4.5), (20, 12), (7, 19.5)))
    elif name == "pause":
        p.drawRoundedRect(QRectF(6, 5, 4.2, 14), 1.2, 1.2)
        p.drawRoundedRect(QRectF(13.8, 5, 4.2, 14), 1.2, 1.2)
    elif name in ("previous", "next"):
        if name == "next":
            p.translate(24, 0)
            p.scale(-1, 1)
        p.drawRoundedRect(QRectF(5, 6, 2.6, 12), 0.8, 0.8)
        p.drawPolygon(_poly((8.5, 12), (19, 5.5), (19, 18.5)))
    elif name == "shuffle":
        pen = p.pen()
        stroke = QPainterPath(QPointF(3, 7.5))
        stroke.cubicTo(QPointF(10, 7.5), QPointF(12, 16.5), QPointF(17.5, 16.5))
        stroke.moveTo(3, 16.5)
        stroke.cubicTo(QPointF(10, 16.5), QPointF(12, 7.5), QPointF(17.5, 7.5))
        p.setBrush(Qt.NoBrush)
        p.drawPath(stroke)
        p.setPen(Qt.NoPen)
        p.setBrush(pen.color())
        _arrow_head(p, (21.5, 7.5), 1)
        _arrow_head(p, (21.5, 16.5), 1)
    elif name == "repeat":
        pen = p.pen()
        stroke = QPainterPath(QPointF(4, 13))
        stroke.lineTo(4, 10.5)
        stroke.quadTo(4, 7.5, 7, 7.5)
        stroke.lineTo(17, 7.5)
        stroke.moveTo(20, 11)
        stroke.lineTo(20, 13.5)
        stroke.quadTo(20, 16.5, 17, 16.5)
        stroke.lineTo(7, 16.5)
        p.setBrush(Qt.NoBrush)
        p.drawPath(stroke)
        p.setPen(Qt.NoPen)
        p.setBrush(pen.color())
        _arrow_head(p, (21, 7.5), 1)
        _arrow_head(p, (3, 16.5), -1)
    elif name in ("volume", "muted"):
        pen = p.pen()
        p.setPen(Qt.NoPen)
        p.drawPolygon(_poly((3, 9), (7, 9), (12, 4.5), (12, 19.5), (7, 15), (3, 15)))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if name == "volume":
            p.drawArc(QRectF(9, 8, 8, 8), -50 * 16, 100 * 16)
            p.drawArc(QRectF(8, 4.5, 13, 15), -50 * 16, 100 * 16)
        else:
            p.drawLine(QPointF(15.5, 9), QPointF(21, 15))
            p.drawLine(QPointF(21, 9), QPointF(15.5, 15))


def pixmap(name: str, color: QColor, size: int = 20) -> QPixmap:
    pix = QPixmap(size * SCALE, size * SCALE)
    pix.fill(Qt.transparent)
    pix.setDevicePixelRatio(SCALE)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24, size / 24)
    pen = QPen(color, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(color)
    if name in ("play", "pause", "previous", "next"):
        p.setPen(Qt.NoPen)
    _draw(p, name)
    p.end()
    return pix


def icon(name: str, color: QColor, on_color: QColor | None = None, size: int = 20) -> QIcon:
    """``on_color`` colours the checked state of toggle buttons."""
    result = QIcon(pixmap(name, color, size))
    if on_color is not None:
        result.addPixmap(pixmap(name, on_color, size), QIcon.Normal, QIcon.On)
    return result
