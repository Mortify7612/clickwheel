"""Theme flourishes for headings: Winamp-style gold ribbed bars (retro), sparkles (Y2K)."""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QWidget

from .fonts import label_font
from .sparkle import paint_sparkle
from .theme import current_theme, is_retro

RIB_LIGHT = QColor("#f2d469")
RIB_DARK = QColor("#5e4a12")
RIBS = 4  # each rib is a lit line over a shadow line


def paint_ribs(p: QPainter, rect: QRect) -> None:
    """Gold ribs filling ``rect`` horizontally, centred vertically in it."""
    if rect.width() < 4:
        return
    top = rect.center().y() - RIBS + 1
    for i in range(RIBS):
        y = top + i * 2
        p.fillRect(QRect(rect.left(), y, rect.width(), 1), RIB_LIGHT)
        p.fillRect(QRect(rect.left() + 1, y + 1, rect.width() - 1, 1), RIB_DARK)


class TitleBar(QWidget):
    """A window title strip: a caps label between two runs of ribs (only shown in the retro skin)."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self.setFixedHeight(16)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        font = label_font(8)
        p.setFont(font)
        width = QFontMetrics(font).horizontalAdvance(self.text)
        left = (self.width() - width) // 2
        paint_ribs(p, QRect(4, 0, left - 12, self.height()))
        paint_ribs(p, QRect(left + width + 8, 0, self.width() - left - width - 12, self.height()))
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(self.rect(), Qt.AlignCenter, self.text)


class SectionLabel(QLabel):
    """A panel heading. Retro skin: caps text trailed by gold ribs; Y2K: a twinkling sparkle
    before it; other skins: the plain label."""

    SPARKLE_ROOM = 18

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.StyleChange:  # the theme changed
            self.setIndent(self.SPARKLE_ROOM if current_theme() == "y2k" else -1)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(hint.width(), max(hint.height(), 18))

    def minimumSizeHint(self) -> QSize:
        return QSize(20, max(super().minimumSizeHint().height(), 18))

    def paintEvent(self, event) -> None:
        if current_theme() == "y2k":
            super().paintEvent(event)
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            paint_sparkle(p, QPointF(8, self.height() / 2), 6.5, QColor(255, 95, 180, 220))
            return
        if not is_retro():
            super().paintEvent(event)
            return
        p = QPainter(self)
        font: QFont = label_font(8)
        p.setFont(font)
        text = re.sub(r"<[^>]+>", "", self.text())
        shown = QFontMetrics(font).elidedText(text, Qt.ElideRight, self.width() - 30)
        width = QFontMetrics(font).horizontalAdvance(shown)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(self.rect().adjusted(2, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, shown)
        paint_ribs(p, QRect(width + 10, 0, self.width() - width - 12, self.height()))
