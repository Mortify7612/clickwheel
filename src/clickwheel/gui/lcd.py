"""Retro dot-matrix LCD strip: the artist up top, a scrolling ticker below, level meter.

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

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QPolygonF, QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from .sparkle import TINTS, paint_bubble, paint_sparkle
from .theme import LcdSkin, lcd_skin

PITCH = 3        # screen pixels per dot (dot + gap)
DOT = 2          # lit square size within a pitch cell
BARS = 16
GAP = 24  # dots between repeats of a scrolling line


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


def _blend(stops: tuple, t: float) -> QColor:
    """The colour ``t`` (0..1) of the way through evenly spaced ``stops``."""
    pos = min(max(t, 0.0), 1.0) * (len(stops) - 1)
    i = min(int(pos), len(stops) - 2)
    a, b, f = QColor(stops[i]), QColor(stops[i + 1]), pos - i
    return QColor(round(a.red() + (b.red() - a.red()) * f), round(a.green() + (b.green() - a.green()) * f),
                  round(a.blue() + (b.blue() - a.blue()) * f))


# A lightning bolt in a unit box, like the one in Winamp's logo.
BOLT = ((0.56, 0.0), (0.16, 0.58), (0.44, 0.58), (0.30, 1.0), (0.84, 0.36), (0.55, 0.36), (0.74, 0.0))


def _paint_lightning(p: QPainter, rect: QRectF, _t: float) -> None:
    """A faint gold bolt behind the dots, glowing softly, dim enough to read text over."""
    h = rect.height() * 1.45
    w = h * 0.72
    x0, y0 = rect.left() + rect.width() * 0.6 - w / 2, rect.center().y() - h / 2
    bolt = QPainterPath()
    bolt.addPolygon(QPolygonF([QPointF(x0 + x * w, y0 + y * h) for x, y in BOLT]))
    bolt.closeSubpath()
    p.save()
    p.setClipRect(rect)
    for width, alpha in ((14, 10), (8, 18), (4, 30)):  # soft glow, widest and faintest first
        p.strokePath(bolt, QPen(QColor(255, 196, 40, alpha), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    fill = QLinearGradient(QPointF(x0, y0), QPointF(x0 + w, y0 + h))
    fill.setColorAt(0, QColor(255, 226, 90, 70))
    fill.setColorAt(1, QColor(232, 120, 24, 60))
    p.fillPath(bolt, fill)
    p.restore()


# Motion tracker contacts: (angle in degrees, distance from the centre as a fraction).
CONTACTS = ((38, 0.62), (148, 0.8), (205, 0.45), (300, 0.7))
SWEEP_DEG_PER_S = 140


def _paint_tracker(p: QPainter, centre: QPointF, r: float, t: float) -> None:
    """Halo's motion tracker: rings and a crosshair, a rotating sweep, contacts flaring as it passes."""
    cyan = QColor(95, 212, 255)
    disc = QPainterPath()
    disc.addEllipse(centre, r, r)
    p.fillPath(disc, QColor(4, 20, 34, 150))
    lead = -(t * SWEEP_DEG_PER_S) % 360  # clockwise
    sweep = QConicalGradient(centre, lead)  # the tail trails counter-clockwise, where it's been
    sweep.setColorAt(0, QColor(95, 212, 255, 120))
    sweep.setColorAt(0.22, QColor(95, 212, 255, 0))
    sweep.setColorAt(1, QColor(95, 212, 255, 0))
    p.fillPath(disc, sweep)
    p.setBrush(Qt.NoBrush)
    for radius, alpha in ((r, 110), (r * 0.62, 45), (r * 0.28, 35)):
        p.setPen(QPen(QColor(cyan.red(), cyan.green(), cyan.blue(), alpha), 1))
        p.drawEllipse(centre, radius, radius)
    p.setPen(QPen(QColor(cyan.red(), cyan.green(), cyan.blue(), 35), 1))
    p.drawLine(QPointF(centre.x() - r, centre.y()), QPointF(centre.x() + r, centre.y()))
    p.drawLine(QPointF(centre.x(), centre.y() - r), QPointF(centre.x(), centre.y() + r))
    for angle, distance in CONTACTS:
        since = (angle - lead) % 360  # degrees the sweep has turned since it passed
        fade = max(0.0, 1 - since / 320)
        a = math.radians(angle)
        dot = QPointF(centre.x() + math.cos(a) * distance * r, centre.y() - math.sin(a) * distance * r)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 70, 50, int(40 + 160 * fade)))
        p.drawEllipse(dot, 1.6 + 1.4 * fade, 1.6 + 1.4 * fade)
    p.setBrush(cyan)  # you, at the centre
    p.drawPolygon(QPolygonF([centre + QPointF(0, -3), centre + QPointF(2.5, 2.5), centre + QPointF(-2.5, 2.5)]))


def _paint_halo(p: QPainter, rect: QRectF, t: float) -> None:
    """Deep space: stars, a banded gas giant rising in the corner, the ring arcing across,
    and the motion tracker sweeping in the bottom left."""
    w, h, x, y = rect.width(), rect.height(), rect.left(), rect.top()
    stars = random.Random(117)  # the same sky every frame
    for _ in range(int(w // 9)):
        alpha = stars.randint(50, 170)
        size = 1.6 if stars.random() < 0.12 else 1.0
        p.fillRect(QRectF(x + stars.random() * w, y + stars.random() * h, size, size), QColor(220, 236, 255, alpha))

    # The gas giant, lit from the upper right, with faint bands.
    centre, radius = QPointF(x + w * 0.80, y + h * 1.55), h * 1.25
    body = QRadialGradient(centre + QPointF(radius * 0.35, -radius * 0.45), radius * 1.3)
    body.setColorAt(0, QColor(196, 128, 64, 150))
    body.setColorAt(0.6, QColor(110, 62, 30, 130))
    body.setColorAt(1, QColor(30, 16, 10, 120))
    planet = QPainterPath()
    planet.addEllipse(centre, radius, radius)
    p.fillPath(planet, body)
    p.save()
    p.setClipPath(planet)
    for i in range(5):
        band_y = centre.y() - radius * (0.95 - i * 0.12)
        p.fillRect(QRectF(x, band_y, w, radius * 0.05), QColor(240, 190, 120, 22))
    p.restore()
    p.strokePath(planet, QPen(QColor(255, 200, 140, 60), 1.5))

    # The ring: a thin tilted band, its far side dim and its near side bright.
    p.save()
    p.translate(x + w * 0.63, y + h * 0.52)
    p.rotate(-11)
    ring = QRectF(-h * 1.9, -h * 0.36, h * 3.8, h * 0.72)
    p.setPen(QPen(QColor(110, 140, 165, 110), 2.5))
    p.drawArc(ring, 0, 180 * 16)
    p.setPen(QPen(QColor(200, 222, 238, 170), 4))
    p.drawArc(ring, 180 * 16, 180 * 16)
    p.setPen(QPen(QColor(120, 220, 255, 80), 1))  # atmosphere glinting on the inner surface
    p.drawArc(ring.adjusted(3, 3, -3, -3), 185 * 16, 170 * 16)
    p.restore()

    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    _paint_tracker(p, QPointF(x + h * 0.5 + 2, y + h * 0.5), h * 0.42, t)
    p.restore()


def _paint_bubbles(p: QPainter, rect: QRectF, t: float) -> None:
    """Soap bubbles drifting up the screen and sparkles twinkling in and out."""
    w, h, x, y = rect.width(), rect.height(), rect.left(), rect.top()
    rng = random.Random(1999)  # the same bubbles every frame; time moves them
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    for i in range(10):
        r = h * rng.uniform(0.1, 0.3)
        travel = h + 2 * r
        speed = rng.uniform(5, 13)  # px per second
        rise = (t * speed + rng.random() * travel) % travel
        cx = x + rng.random() * w + math.sin(t * 0.7 + i) * 3  # a little wobble
        paint_bubble(p, QPointF(cx, y + h + r - rise), r, TINTS[i % len(TINTS)])
    for i in range(9):
        twinkle = max(0.0, math.sin(t * 2.1 + i * 1.7))
        tint = TINTS[i % len(TINTS)]
        paint_sparkle(p, QPointF(x + rng.random() * w, y + rng.random() * h), rng.uniform(3, 5.5),
                      QColor(tint.red(), tint.green(), tint.blue(), int(200 * twinkle)))
    p.restore()


def _paint_bliss(p: QPainter, rect: QRectF, _t: float) -> None:
    """A rolling green hill under a blue sky with soft clouds."""
    sky = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    sky.setColorAt(0, QColor("#1f5fcf"))
    sky.setColorAt(0.7, QColor("#5aa2ee"))
    sky.setColorAt(1, QColor("#8cc2f4"))
    p.fillRect(rect, sky)
    w, h, x, y = rect.width(), rect.height(), rect.left(), rect.top()
    for cx, cy, rx, ry in ((0.18, 0.22, 0.10, 0.20), (0.27, 0.30, 0.08, 0.16),
                           (0.62, 0.18, 0.12, 0.18), (0.74, 0.26, 0.07, 0.14)):
        centre = QPointF(x + cx * w, y + cy * h)
        cloud = QRadialGradient(centre, rx * w)
        cloud.setColorAt(0, QColor(255, 255, 255, 120))
        cloud.setColorAt(1, QColor(255, 255, 255, 0))
        p.save()
        p.translate(centre)
        p.scale(1, ry * h / (rx * w))  # squash the round puff into a wide one
        p.translate(-centre)
        p.fillRect(QRectF(centre.x() - rx * w, centre.y() - rx * w, 2 * rx * w, 2 * rx * w), cloud)
        p.restore()
    hill = QPainterPath(QPointF(x, y + h * 0.62))
    hill.cubicTo(QPointF(x + w * 0.22, y + h * 0.30), QPointF(x + w * 0.45, y + h * 0.38),
                 QPointF(x + w * 0.62, y + h * 0.55))
    hill.cubicTo(QPointF(x + w * 0.78, y + h * 0.70), QPointF(x + w * 0.90, y + h * 0.52), QPointF(x + w, y + h * 0.56))
    hill.lineTo(rect.bottomRight())
    hill.lineTo(rect.bottomLeft())
    hill.closeSubpath()
    grass = QLinearGradient(QPointF(x, y + h * 0.35), rect.bottomLeft())
    grass.setColorAt(0, QColor("#64b52c"))
    grass.setColorAt(1, QColor("#2b7413"))
    p.fillPath(hill, grass)


class LcdDisplay(QWidget):
    """Dot-matrix panel: the playing artist as the feature line, the song (or status) scrolling
    underneath, and a level meter. With nothing playing, the status takes the feature line."""

    FEATURE_FONT = 11   # in dots
    TICKER_FONT = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(84)
        self._status = ""            # latest status message (downloads, sync, ...)
        self._status_until = 0.0     # show it until then, unless something is busy
        self._artist = ""
        self._song = ""
        self._play_state = "stopped"
        self._clock = ""             # "1:23 / 3:45"
        self._spectrum: list[float] | None = None  # live levels while music plays
        # What each line currently shows, and its marquee scroll in whole dots.
        self._feature, self._feature_offset = "READY", 0
        self._message, self._offset = "", 0
        self._busy: set[str] = set()  # e.g. {"downloads", "sync"}
        self._levels = [0.05] * BARS
        self._peaks = [0.05] * BARS
        self._phase = 0.0
        self._blink = 0
        self._feature_font = _dot_font(self.FEATURE_FONT, bold=True)
        self._ticker_font = _dot_font(self.TICKER_FONT)
        self._small_font = _dot_font(8, bold=True)
        self._skin: LcdSkin | None = None
        self._unlit_brush = QBrush()
        self._mask_brush = QBrush(_tile(QColor("white")))
        self._timer = QTimer(self, interval=60, timeout=self._tick)
        self._timer.start()

    # ── API ──────────────────────────────────────────────────────────────

    def set_message(self, text: str) -> None:
        """Show a status message; it gives way to the playing song after a few seconds."""
        self._status = " ".join((text or "").split()).upper()
        self._status_until = time.monotonic() + 6

    def set_now_playing(self, artist: str, title: str, state: str) -> None:
        artist = " ".join((artist or "").split()).upper()
        title = " ".join((title or "").split()).upper()
        if state == "playing" and (artist, title) != (self._artist, self._song):
            self._status_until = 0.0  # a new song takes over the ticker straight away
        self._artist, self._song = artist, title
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

    def _lines(self) -> tuple[str, str]:
        """(feature line, ticker line)."""
        if not (self._artist or self._song):
            return self._status or "READY", ""
        song = self._song if self._artist else ""  # no artist tag: the title is the feature
        if self._status and (self._busy or time.monotonic() < self._status_until):
            return self._artist or self._song, self._status
        return self._artist or self._song, song

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

    def _clock_text(self) -> str:
        if self._play_state == "stopped" and not self._clock:
            return ""
        icon = {"playing": "▶", "paused": "❚❚"}.get(self._play_state, "■")
        return f"{icon} {self._clock}"

    def _feature_cols(self) -> int:
        """Room for the feature line: left of the busy lamp and clock."""
        metrics = QFontMetrics(self._small_font)
        right = metrics.horizontalAdvance(self._clock_text())
        if self._active:
            right += metrics.horizontalAdvance("◆ BUSY") + 8
        return self._ticker_cols() - right - (8 if right else 0) - self._text_left()

    def _text_left(self) -> int:
        return (self._skin or lcd_skin()).text_left

    def _ticker_width(self) -> int:
        """Room for the ticker: from the text margin to the meter."""
        return self._ticker_cols() - self._text_left()

    # ── Animation ────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._phase += 0.25
        self._blink = (self._blink + 1) % 16
        feature, message = self._lines()
        if feature != self._feature:
            self._feature, self._feature_offset = feature, 0
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
        width = QFontMetrics(self._feature_font).horizontalAdvance(self._feature)
        if width > self._feature_cols():
            self._feature_offset = (self._feature_offset + 1) % (width + GAP)
        width = QFontMetrics(self._ticker_font).horizontalAdvance(self._message)
        if width > self._ticker_width():
            self._offset = (self._offset + 1) % (width + GAP)
        self.update()

    # ── Painting ─────────────────────────────────────────────────────────

    def _render_dots(self, cols: int, rows: int, skin: LcdSkin) -> QImage:
        """Draw the display content at one pixel per dot."""
        lit, mid, peak_color = QColor(skin.lit), QColor(skin.mid), QColor(skin.peak)
        img = QImage(cols, rows, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setRenderHint(QPainter.TextAntialiasing, False)

        top_h = rows // 2
        p.setPen(lit)
        # Feature line (the artist), then the busy lamp and clock at its right.
        self._marquee(p, QRect(self._text_left(), 0, self._feature_cols(), top_h), self._feature_font,
                      self._feature, self._feature_offset)
        p.setFont(self._small_font)
        clock = self._clock_text()
        clock_w = QFontMetrics(self._small_font).horizontalAdvance(clock)
        if self._active and self._blink < 11:  # blinking busy lamp
            p.setPen(mid)
            p.drawText(QRect(0, 0, self._ticker_cols() - clock_w - (8 if clock else 0), top_h),
                       Qt.AlignRight | Qt.AlignVCenter, "◆ BUSY")
        # Paused: blink the clock, like a hardware deck.
        if clock and (self._play_state != "paused" or self._blink < 10):
            p.setPen(lit)
            p.drawText(QRect(0, 0, self._ticker_cols(), top_h), Qt.AlignRight | Qt.AlignVCenter, clock)

        # Ticker on the bottom line (the song, or a status message), left of the meter.
        p.setPen(lit)
        self._marquee(p, QRect(self._text_left(), top_h, self._ticker_width(), rows - top_h), self._ticker_font,
                      self._message, self._offset)

        # Level meter: each row of dots is one segment, coloured by height.
        left = cols - self._meter_cols() - 1
        meter_rows = rows - 2
        segment = [_blend(skin.meter, r / max(1, meter_rows - 1)) for r in range(meter_rows)]
        for i, level in enumerate(self._levels):
            x = left + i * 3
            height = max(1, int(round(level * meter_rows)))  # idle: a one-dot resting baseline
            for r in range(min(height, meter_rows)):
                p.fillRect(x, rows - 2 - r, 2, 1, segment[r])
            if self._active or self._spectrum is not None:
                peak = min(meter_rows - 1, int(self._peaks[i] * meter_rows))
                p.fillRect(x, rows - 2 - peak, 2, 1, peak_color)
        p.end()
        return img

    @staticmethod
    def _marquee(p: QPainter, rect: QRect, font: QFont, text: str, offset: int) -> None:
        """``text`` in ``rect``, scrolling round when it doesn't fit."""
        if not text or rect.width() <= 0:
            return
        p.save()
        p.setClipRect(rect)
        p.setFont(font)
        width = QFontMetrics(font).horizontalAdvance(text)
        if width > rect.width():
            for start in (rect.left() - offset, rect.left() - offset + width + GAP):
                p.drawText(QRect(start, rect.top(), width + GAP, rect.height()), Qt.AlignLeft | Qt.AlignVCenter, text)
        else:
            p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        p.restore()

    def paintEvent(self, _event) -> None:
        skin = lcd_skin()
        if skin != self._skin:
            self._skin = skin
            self._unlit_brush = QBrush(_tile(QColor(*skin.unlit)))
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        outer_r = QRectF(self.rect()).adjusted(2, 1, -2, -1)

        # Bevelled plastic bezel.
        bezel = QLinearGradient(outer_r.topLeft(), outer_r.bottomLeft())
        for stop, color in zip((0, 0.5, 1), skin.bezel):
            bezel.setColorAt(stop, QColor(color))
        outer = QPainterPath()
        outer.addRoundedRect(outer_r, 7, 7)
        p.fillPath(outer, bezel)
        screen = self._screen()
        glass = QPainterPath()
        glass.addRoundedRect(QRectF(screen).adjusted(-2, -2, 2, 2), 4, 4)
        screen_bg = QLinearGradient(QRectF(screen).topLeft(), QRectF(screen).bottomLeft())
        screen_bg.setColorAt(0, QColor(skin.screen[0]))
        screen_bg.setColorAt(1, QColor(skin.screen[1]))
        p.fillPath(glass, screen_bg)
        scene = {"bliss": _paint_bliss, "lightning": _paint_lightning, "halo": _paint_halo,
                 "bubbles": _paint_bubbles}.get(skin.scene)
        if scene is not None:
            p.save()
            p.setClipPath(glass)
            scene(p, glass.boundingRect(), time.monotonic())
            p.restore()

        cols, rows = self._grid()
        origin = screen.topLeft()
        size_px = QRect(origin, QPoint(origin.x() + cols * PITCH - 1, origin.y() + rows * PITCH - 1))
        p.setRenderHint(QPainter.Antialiasing, False)

        # Unlit dots everywhere.
        p.setBrushOrigin(origin)
        p.fillRect(size_px, self._unlit_brush)

        content = self._render_dots(cols, rows, skin)
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
