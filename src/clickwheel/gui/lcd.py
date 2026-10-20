"""Retro dot-matrix LCD strip: app title, scrolling status ticker, level meter.

Everything is drawn into a low-resolution "virtual LCD" (one pixel per dot)
with antialiasing off, then blown up so each pixel becomes a square dot with a
gap around it, over a grid of faint unlit dots, plus a soft glow. Text comes
from the system font rasterised at dot resolution, so accented and non-Latin
song titles still render.
"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap,
)
from PySide6.QtWidgets import QWidget

PITCH = 3        # screen pixels per dot (dot + gap)
DOT = 2          # lit square size within a pitch cell
LIT = QColor("#39ff7a")
AMBER = QColor("#ffc233")
RED = QColor("#ff5533")
UNLIT = QColor(16, 48, 26)
SCREEN_BG = QColor("#020805")
BARS = 16
TITLE = "CLICKWHEEL"


def _dot_font(pixel_size: int, bold: bool = False) -> QFont:
    font = QFont()
    font.setFamilies(["DejaVu Sans Mono", "Menlo", "Consolas", "Liberation Mono", "monospace"])
    font.setStyleHint(QFont.Monospace)
    font.setPixelSize(pixel_size)
    font.setBold(bold)
    # Crisp on/off pixels: every pixel becomes a whole dot.
    font.setStyleStrategy(QFont.StyleStrategy(QFont.NoAntialias | QFont.PreferBitmap))
    font.setHintingPreference(QFont.PreferFullHinting)
    return font


def _tile(color: QColor) -> QPixmap:
    """One PITCH x PITCH cell with a DOT x DOT square, for tiling the grid."""
    tile = QPixmap(PITCH, PITCH)
    tile.fill(Qt.transparent)
    p = QPainter(tile)
    p.fillRect(0, 0, DOT, DOT, color)
    p.end()
    return tile


class LcdDisplay(QWidget):
    """Dot-matrix panel with a marquee and a bouncing level meter while busy."""

    TITLE_FONT = 11   # in dots
    TICKER_FONT = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(84)
        self._status = ""            # latest status message (downloads, sync, ...)
        self._status_until = 0.0     # show it until then, unless something is busy
        self._now_playing = ""
        self._play_state = "stopped"
        self._clock = ""             # "1:23 / 3:45"
        self._spectrum: list[float] | None = None  # live levels while music plays
        self._message = "READY"      # what the ticker currently shows
        self._offset = 0      # marquee scroll, in whole dots
        self._busy: set[str] = set()  # e.g. {"downloads", "sync"}
        self._levels = [0.05] * BARS
        self._peaks = [0.05] * BARS
        self._phase = 0.0
        self._blink = 0
        self._title_font = _dot_font(self.TITLE_FONT, bold=True)
        self._ticker_font = _dot_font(self.TICKER_FONT)
        self._unlit_brush = QBrush(_tile(UNLIT))
        self._mask_brush = QBrush(_tile(QColor("white")))
        self._timer = QTimer(self, interval=60, timeout=self._tick)
        self._timer.start()

    # ── API ──────────────────────────────────────────────────────────────

    def set_message(self, text: str) -> None:
        """Show a status message; it gives way to the playing song after a few seconds."""
        self._status = " ".join((text or "").split()).upper()
        self._status_until = time.monotonic() + 6

    def set_now_playing(self, label: str, state: str) -> None:
        label = " ".join((label or "").split()).upper()
        if state == "playing" and label != self._now_playing:
            self._status_until = 0.0  # a new song takes over the ticker straight away
        self._now_playing = label
        self._play_state = state
        if state != "playing":
            self._spectrum = None

    def set_clock(self, position_ms: int, duration_ms: int) -> None:
        def fmt(ms: int) -> str:
            s = max(0, ms // 1000)
            return f"{s // 60}:{s % 60:02d}"

        self._clock = f"{fmt(position_ms)} / {fmt(duration_ms)}" if duration_ms > 0 else fmt(position_ms)

    def set_spectrum(self, levels: list[float]) -> None:
        self._spectrum = list(levels) if self._play_state == "playing" and any(levels) else None

    def _ticker_text(self) -> str:
        if self._status and (self._busy or time.monotonic() < self._status_until):
            return self._status
        if self._now_playing:
            return self._now_playing
        return self._status or "READY"

    def set_busy(self, source: str, busy: bool) -> None:
        if busy:
            self._busy.add(source)
        else:
            self._busy.discard(source)

    @property
    def _active(self) -> bool:
        return bool(self._busy)

    # ── Layout (all in dots) ─────────────────────────────────────────────

    def _screen(self) -> QRect:
        return self.rect().adjusted(7, 6, -7, -6)

    def _grid(self) -> tuple[int, int]:
        s = self._screen()
        return max(1, s.width() // PITCH), max(1, s.height() // PITCH)

    def _meter_cols(self) -> int:
        return BARS * 3  # 2-dot bars with a 1-dot gap

    def _ticker_cols(self) -> int:
        cols, _rows = self._grid()
        return cols - self._meter_cols() - 8

    # ── Animation ────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._phase += 0.25
        self._blink = (self._blink + 1) % 16
        message = self._ticker_text()
        if message != self._message:
            self._message, self._offset = message, 0
        spectrum = self._spectrum
        for i in range(BARS):
            if spectrum is not None:
                target = spectrum[i] if i < len(spectrum) else 0.0
                # Real meters jump up fast and fall back slowly.
                rate = 0.7 if target > self._levels[i] else 0.18
                self._levels[i] += (target - self._levels[i]) * rate
                self._peaks[i] = max(self._levels[i], self._peaks[i] - 0.02)
                continue
            if self._active:
                # Wandering bands of energy, so it looks lively without real audio.
                target = 0.2 + 0.6 * abs(math.sin(self._phase * 0.5 + i * 0.5)) * random.uniform(0.55, 1.0)
                target = min(1.0, max(0.0, target + random.uniform(-0.15, 0.2)))
            else:
                target = 0.0
            self._levels[i] += (target - self._levels[i]) * (0.5 if self._active else 0.2)
            self._peaks[i] = max(self._levels[i], self._peaks[i] - 0.03)
        width = QFontMetrics(self._ticker_font).horizontalAdvance(self._message)
        if width > self._ticker_cols():
            self._offset = (self._offset + 1) % (width + 24)
        self.update()

    # ── Painting ─────────────────────────────────────────────────────────

    def _render_dots(self, cols: int, rows: int) -> QImage:
        """Draw the display content at one pixel per dot."""
        img = QImage(cols, rows, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setRenderHint(QPainter.TextAntialiasing, False)

        top_h = rows // 2
        p.setFont(self._title_font)
        p.setPen(LIT)
        p.drawText(QRect(2, 0, cols, top_h), Qt.AlignLeft | Qt.AlignVCenter, TITLE)
        title_w = QFontMetrics(self._title_font).horizontalAdvance(TITLE)
        small = _dot_font(8, bold=True)
        p.setFont(small)
        if self._active and self._blink < 11:  # blinking busy lamp
            p.setPen(AMBER)
            p.drawText(QRect(title_w + 8, 0, 60, top_h), Qt.AlignLeft | Qt.AlignVCenter, "◆ BUSY")
        if self._play_state != "stopped" or self._clock:
            icon = {"playing": "▶", "paused": "❚❚"}.get(self._play_state, "■")
            # Paused: blink the clock, like a hardware deck.
            if self._play_state != "paused" or self._blink < 10:
                p.setPen(LIT)
                p.drawText(QRect(0, 0, self._ticker_cols(), top_h), Qt.AlignRight | Qt.AlignVCenter,
                           f"{icon} {self._clock}")

        # Marquee on the bottom line, clipped to the area left of the meter.
        ticker = QRect(2, top_h, self._ticker_cols(), rows - top_h)
        p.save()
        p.setClipRect(ticker)
        p.setFont(self._ticker_font)
        p.setPen(LIT)
        width = QFontMetrics(self._ticker_font).horizontalAdvance(self._message)
        if width > ticker.width():
            gap = 24
            for start in (ticker.left() - self._offset, ticker.left() - self._offset + width + gap):
                p.drawText(QRect(start, ticker.top(), width + gap, ticker.height()),
                           Qt.AlignLeft | Qt.AlignVCenter, self._message)
        else:
            p.drawText(ticker, Qt.AlignLeft | Qt.AlignVCenter, self._message)
        p.restore()

        # Level meter: each row of dots is one segment; green -> amber -> red.
        left = cols - self._meter_cols() - 1
        meter_rows = rows - 2
        for i, level in enumerate(self._levels):
            x = left + i * 3
            lit = max(1, int(round(level * meter_rows)))  # idle: a one-dot resting baseline
            for r in range(lit):
                frac = r / max(1, meter_rows - 1)
                color = RED if frac > 0.82 else AMBER if frac > 0.62 else LIT
                p.fillRect(x, rows - 2 - r, 2, 1, color)
            if self._active or self._spectrum is not None:
                peak = min(meter_rows - 1, int(self._peaks[i] * meter_rows))
                p.fillRect(x, rows - 2 - peak, 2, 1, QColor("#d9ffe6"))
        p.end()
        return img

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        outer_r = QRectF(self.rect()).adjusted(2, 1, -2, -1)

        # Bevelled plastic bezel.
        bezel = QLinearGradient(outer_r.topLeft(), outer_r.bottomLeft())
        bezel.setColorAt(0, QColor("#62626f"))
        bezel.setColorAt(0.5, QColor("#3a3a44"))
        bezel.setColorAt(1, QColor("#18181d"))
        outer = QPainterPath()
        outer.addRoundedRect(outer_r, 7, 7)
        p.fillPath(outer, bezel)
        screen = self._screen()
        glass = QPainterPath()
        glass.addRoundedRect(QRectF(screen).adjusted(-2, -2, 2, 2), 4, 4)
        p.fillPath(glass, SCREEN_BG)

        cols, rows = self._grid()
        origin = screen.topLeft()
        size_px = QRect(origin, QPoint(origin.x() + cols * PITCH - 1, origin.y() + rows * PITCH - 1))
        p.setRenderHint(QPainter.Antialiasing, False)

        # Unlit dots everywhere.
        p.setBrushOrigin(origin)
        p.fillRect(size_px, self._unlit_brush)

        content = self._render_dots(cols, rows)
        # Glow: the content smoothly upscaled behind the dots.
        glow = content.scaled(cols * PITCH, rows * PITCH, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        p.setOpacity(0.28)
        p.drawImage(origin + QPoint(-1, -1), glow.scaled(glow.width() + 2, glow.height() + 2,
                                                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        p.setOpacity(1.0)

        # Lit dots: nearest-neighbour upscale, then punch the gaps between dots.
        dots = content.scaled(cols * PITCH, rows * PITCH, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        mp = QPainter(dots)
        mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mp.fillRect(dots.rect(), self._mask_brush)
        mp.end()
        p.drawImage(origin, dots)

        # A faint glass highlight across the top.
        sheen = QLinearGradient(QRectF(screen).topLeft(), QRectF(screen).bottomLeft())
        sheen.setColorAt(0, QColor(255, 255, 255, 18))
        sheen.setColorAt(0.45, QColor(255, 255, 255, 0))
        p.fillRect(screen, sheen)
        p.end()
