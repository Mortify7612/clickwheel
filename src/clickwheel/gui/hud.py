"""Halo-style HUD corner brackets, drawn over a panel's corners (Halo skin only)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

BRACKET = QColor("#5fd4ff")
GLOW = QColor(95, 212, 255, 60)
ARM = 14     # length of each bracket arm
CHAMFER = 4  # the clipped corner


class HudBrackets(QWidget):
    """A transparent overlay that tracks its panel's size and draws a bracket at each corner."""

    def __init__(self, target: QWidget):
        super().__init__(target)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self._follow = _Follow(self, target)
        target.installEventFilter(self._follow)
        self.setGeometry(target.rect())
        self.hide()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width() - 1, self.height() - 1
        corner = QPainterPath(QPointF(1, ARM))
        corner.lineTo(1, 1 + CHAMFER)
        corner.lineTo(1 + CHAMFER, 1)
        corner.lineTo(ARM, 1)
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            p.save()
            p.translate(0 if sx > 0 else w, 0 if sy > 0 else h)
            p.scale(sx, sy)
            p.strokePath(corner, QPen(GLOW, 5, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
            p.strokePath(corner, QPen(BRACKET, 2, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
            p.restore()


class _Follow(QObject):
    """Keeps the overlay covering its panel, and on top of the panel's own children."""

    def __init__(self, overlay: HudBrackets, target: QWidget):
        super().__init__(overlay)
        self.overlay = overlay

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Resize, QEvent.Show, QEvent.ChildAdded):
            self.overlay.setGeometry(obj.rect())
            self.overlay.raise_()
        return False
