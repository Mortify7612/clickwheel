"""Retro LCD display strip: app title, scrolling status ticker, level meter."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

GREEN = QColor("#00e64d")
GREEN_DIM = QColor("#0b3d1c")
AMBER = QColor("#e8b923")
BARS = 18


def _mono(size: int, bold: bool = False) -> QFont:
    font = QFont()
    font.setFamilies(["DejaVu Sans Mono", "Menlo", "Consolas", "Liberation Mono", "monospace"])
    font.setStyleHint(QFont.Monospace)
    font.setPixelSize(size)
    font.setBold(bold)
    return font


class LcdDisplay(QWidget):
    """Black LCD panel with a marquee and a bouncing level meter while busy."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(58)
        self._message = "READY"
        self._offset = 0.0
        self._busy: set[str] = set()  # e.g. {"downloads", "sync"}
        self._levels = [0.05] * BARS
        self._peaks = [0.05] * BARS
        self._phase = 0.0
        self._timer = QTimer(self, interval=40, timeout=self._tick)
        self._timer.start()

    # ── API ──────────────────────────────────────────────────────────────

    def set_message(self, text: str) -> None:
        text = " ".join((text or "").split()).upper() or "READY"
        if text != self._message:
            self._message = text
            self._offset = 0.0
            self.update()

    def set_busy(self, source: str, busy: bool) -> None:
        if busy:
            self._busy.add(source)
        else:
            self._busy.discard(source)

    @property
    def _active(self) -> bool:
        return bool(self._busy)

    # ── Animation ────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._phase += 0.18
        for i in range(BARS):
            if self._active:
                # Wandering bands of energy, so it looks lively without real audio.
                target = 0.25 + 0.55 * abs(math.sin(self._phase * 0.7 + i * 0.45)) * random.uniform(0.6, 1.0)
                target = min(1.0, target + random.uniform(-0.12, 0.2))
            else:
                target = 0.04
            self._levels[i] += (target - self._levels[i]) * (0.45 if self._active else 0.15)
            self._peaks[i] = max(self._levels[i], self._peaks[i] - 0.015)
        if self._marquee_overflow() > 0:
            self._offset += 1.2
        self.update()

    def _marquee_rect(self) -> QRectF:
        return QRectF(14, 32, self.width() - self._meter_width() - 40, 18)

    def _meter_width(self) -> int:
        return BARS * 6 + 8

    def _marquee_overflow(self) -> int:
        return QFontMetrics(_mono(13)).horizontalAdvance(self._message) - int(self._marquee_rect().width())

    # ── Painting ─────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(4, 3, -4, -3)

        # Bevelled bezel around a black screen.
        bezel = QLinearGradient(r.topLeft(), r.bottomLeft())
        bezel.setColorAt(0, QColor("#5c5c6a"))
        bezel.setColorAt(1, QColor("#1a1a20"))
        outer = QPainterPath()
        outer.addRoundedRect(r, 6, 6)
        p.fillPath(outer, bezel)
        screen = r.adjusted(3, 3, -3, -3)
        inner = QPainterPath()
        inner.addRoundedRect(screen, 4, 4)
        p.fillPath(inner, QColor("#000000"))

        # Faint scanlines, like an old LCD.
        p.setPen(QPen(QColor(0, 40, 14, 90), 1))
        y = screen.top() + 1
        while y < screen.bottom():
            p.drawLine(int(screen.left() + 2), int(y), int(screen.right() - 2), int(y))
            y += 3

        # Title with a soft glow.
        title = "CLICKWHEEL"
        p.setFont(_mono(17, bold=True))
        for dx, dy, color in ((1, 1, GREEN_DIM), (0, 0, GREEN)):
            p.setPen(color)
            p.drawText(QRectF(screen.left() + 10 + dx, screen.top() + 2 + dy, 300, 24), Qt.AlignLeft | Qt.AlignVCenter,
                       title)
        p.setFont(_mono(10, bold=True))
        p.setPen(AMBER)
        p.drawText(QRectF(screen.left() + 150, screen.top() + 6, 200, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "● BUSY" if self._active else "")

        # Marquee: scroll long messages, wrapping around with a gap.
        rect = self._marquee_rect()
        p.save()
        p.setClipRect(rect)
        p.setFont(_mono(13))
        p.setPen(GREEN)
        if self._marquee_overflow() > 0:
            gap = 60
            width = QFontMetrics(_mono(13)).horizontalAdvance(self._message) + gap
            x = rect.left() - (self._offset % width)
            for start in (x, x + width):
                p.drawText(QRectF(start, rect.top(), width, rect.height()), Qt.AlignLeft | Qt.AlignVCenter,
                           self._message)
        else:
            p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, self._message)
        p.restore()

        # Level meter: segmented bars, green -> amber -> red, with falling peaks.
        meter_h = screen.height() - 14
        left = screen.right() - self._meter_width()
        bottom = screen.bottom() - 7
        segments = 10
        seg_h = meter_h / segments
        for i, level in enumerate(self._levels):
            x = left + i * 6
            lit = int(round(level * segments))
            for s in range(segments):
                if s < lit:
                    color = QColor("#ff4d2e") if s >= 8 else AMBER if s >= 6 else GREEN
                else:
                    color = GREEN_DIM
                p.fillRect(QRectF(x, bottom - (s + 1) * seg_h + 1, 4, seg_h - 1.5), color)
            peak = min(segments - 1, int(self._peaks[i] * segments))
            if self._active:
                p.fillRect(QRectF(x, bottom - (peak + 1) * seg_h + 1, 4, 1.5), QColor("#d8ffe4"))
        p.end()
