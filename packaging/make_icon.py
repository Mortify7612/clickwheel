"""Draw the Clickwheel app icon and write every platform format.

    uv run python packaging/make_icon.py

An original retro-hardware design: a bevelled gunmetal tile with a green
dot-matrix screen showing spectrum bars, above a knurled hi-fi dial.
Outputs packaging/icons/ (PNGs, .ico, .icns) and the runtime copy in
src/clickwheel/assets/, plus the dev variant run from a source checkout
(clickwheel-dev: a cyan screen, an orange dial light and a "DEV" corner tag).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "packaging" / "icons"
ASSETS = ROOT / "src" / "clickwheel" / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]

GREEN, GREEN_DIM, AMBER, RED = QColor("#39ff7a"), QColor(18, 58, 30), QColor("#ffc233"), QColor("#ff5533")
CYAN, CYAN_DIM, ORANGE = QColor("#3ad8ff"), QColor(14, 44, 62), QColor("#ff8a1f")  # the dev build
BARS = [3, 5, 7, 6, 4, 6, 5, 3, 4, 2]  # spectrum heights, in dots (of ROWS)
ROWS = 7


def render(size: int, dev: bool = False) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 1024, size / 1024)  # draw in a 1024 x 1024 design space
    small = size <= 32
    lit_main, unlit, light = (CYAN, CYAN_DIM, ORANGE) if dev else (GREEN, GREEN_DIM, GREEN)

    # Soft shadow, then the tile.
    if not small:
        for i, alpha in enumerate((26, 18, 10)):
            shadow = QPainterPath()
            shadow.addRoundedRect(QRectF(72 - i * 6, 92 - i * 2, 880 + i * 12, 880 + i * 10), 190, 190)
            p.fillPath(shadow, QColor(0, 0, 0, alpha))
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(64, 56, 896, 896), 184, 184)
    body = QLinearGradient(0, 56, 0, 952)
    body.setColorAt(0.0, QColor("#7a7a88"))
    body.setColorAt(0.08, QColor("#5b5b68"))
    body.setColorAt(0.55, QColor("#33333c"))
    body.setColorAt(1.0, QColor("#1b1b21"))
    p.fillPath(tile, body)
    p.setPen(QPen(QColor(255, 255, 255, 60), 10))
    p.drawPath(tile)
    p.setPen(QPen(QColor(0, 0, 0, 160), 6))
    inner = QPainterPath()
    inner.addRoundedRect(QRectF(78, 70, 868, 868), 172, 172)
    p.drawPath(inner)

    tiny = size <= 24  # too small for the dial: a big screen with a few chunky bars instead
    bars, rows = ([3, 5, 4, 5, 2], 5) if tiny else (BARS, ROWS)

    # Dot-matrix screen.
    screen = QRectF(176, 176, 672, 672) if tiny else QRectF(176, 150, 672, 330)
    bezel = QPainterPath()
    bezel.addRoundedRect(screen.adjusted(-18, -18, 18, 18), 54, 54)
    rim = QLinearGradient(0, screen.top() - 18, 0, screen.bottom() + 18)
    rim.setColorAt(0, QColor("#141418"))
    rim.setColorAt(1, QColor("#6a6a76"))
    p.fillPath(bezel, rim)
    glass = QPainterPath()
    glass.addRoundedRect(screen, 38, 38)
    p.fillPath(glass, QColor("#020805"))

    cols = len(bars)
    pad_x, pad_y = 46, 40
    cell_w = (screen.width() - 2 * pad_x) / cols
    cell_h = (screen.height() - 2 * pad_y) / rows
    dot = min(cell_w, cell_h) * (0.86 if small else 0.74)
    for c, height in enumerate(bars):
        for r in range(rows):
            lit = r < height
            color = (RED if r >= rows - 1 else AMBER if r >= rows - 2 else lit_main) if lit else unlit
            x = screen.left() + pad_x + c * cell_w + (cell_w - dot) / 2
            y = screen.bottom() - pad_y - (r + 1) * cell_h + (cell_h - dot) / 2
            if lit and not small:  # glow
                p.fillRect(QRectF(x - dot * 0.18, y - dot * 0.18, dot * 1.36, dot * 1.36),
                           QColor(color.red(), color.green(), color.blue(), 55))
            p.fillRect(QRectF(x, y, dot, dot), color)
    sheen = QLinearGradient(0, screen.top(), 0, screen.center().y())
    sheen.setColorAt(0, QColor(255, 255, 255, 34))
    sheen.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillPath(glass, sheen)

    if tiny:
        p.end()
        return img
    if dev and size >= 48:
        _dev_tag(p)

    # Knurled dial.
    center, radius = QPointF(512, 720), 178
    well = QRadialGradient(center, radius + 34)
    well.setColorAt(0.80, QColor("#0d0d11"))
    well.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(well)
    p.drawEllipse(center, radius + 34, radius + 34)
    ring = QLinearGradient(center.x(), center.y() - radius, center.x(), center.y() + radius)
    ring.setColorAt(0, QColor("#c4c4d0"))
    ring.setColorAt(0.5, QColor("#7c7c8a"))
    ring.setColorAt(1, QColor("#3c3c46"))
    p.setBrush(ring)
    p.drawEllipse(center, radius, radius)
    if not small:
        p.setPen(QPen(QColor(20, 20, 26, 150), 7, Qt.SolidLine, Qt.RoundCap))
        for i in range(60):
            a = 2 * math.pi * i / 60
            outer = QPointF(center.x() + math.cos(a) * (radius - 10), center.y() + math.sin(a) * (radius - 10))
            inner_pt = QPointF(center.x() + math.cos(a) * (radius - 38), center.y() + math.sin(a) * (radius - 38))
            p.drawLine(inner_pt, outer)
        # Indicator notch, lit green like an LED.
        a = math.radians(-120)
        led = QPointF(center.x() + math.cos(a) * (radius - 64), center.y() + math.sin(a) * (radius - 64))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(light.red(), light.green(), light.blue(), 70))
        p.drawEllipse(led, 24, 24)
        p.setBrush(light)
        p.drawEllipse(led, 13, 13)
    # Concave centre button.
    hub_r = radius * 0.42
    hub = QRadialGradient(center + QPointF(0, hub_r * 0.5), hub_r * 1.4)
    hub.setColorAt(0, QColor("#5a5a66"))
    hub.setColorAt(1, QColor("#22222a"))
    p.setPen(QPen(QColor(255, 255, 255, 50), 5))
    p.setBrush(hub)
    p.drawEllipse(center, hub_r, hub_r)
    p.end()
    return img


def _dev_tag(p: QPainter) -> None:
    """An orange "DEV" sash across the bottom-right corner of the tile."""
    p.save()
    p.setClipPath(_tile_path())
    p.translate(800, 800)
    p.rotate(-45)
    band = QRectF(-330, -62, 660, 124)
    fill = QLinearGradient(0, band.top(), 0, band.bottom())
    fill.setColorAt(0, QColor("#ffa64a"))
    fill.setColorAt(1, QColor("#e86a00"))
    p.setPen(Qt.NoPen)
    p.fillRect(band, fill)
    p.fillRect(QRectF(band.left(), band.top(), band.width(), 6), QColor(255, 255, 255, 90))
    font = QFont("DejaVu Sans")
    font.setPixelSize(92)
    font.setWeight(QFont.Black)
    font.setLetterSpacing(QFont.AbsoluteSpacing, 10)
    p.setFont(font)
    p.setPen(QColor("#2a1400"))
    p.drawText(band, Qt.AlignCenter, "DEV")
    p.restore()


def _tile_path() -> QPainterPath:
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(64, 56, 896, 896), 184, 184)
    return tile


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841  (QPainter text/image support)
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    pngs = {}
    for size in SIZES:
        path = OUT / f"clickwheel-{size}.png"
        render(size).save(str(path))
        pngs[size] = path
    render(256).save(str(ASSETS / "clickwheel.png"))
    for size in SIZES:
        if size <= 512:
            render(size, dev=True).save(str(OUT / f"clickwheel-dev-{size}.png"))
    render(256, dev=True).save(str(ASSETS / "clickwheel-dev.png"))

    from PIL import Image

    images = {s: Image.open(pngs[s]).convert("RGBA") for s in SIZES}
    images[256].save(OUT / "clickwheel.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)],
                     append_images=[images[s] for s in (16, 24, 32, 48, 64, 128)])
    images[1024].save(OUT / "clickwheel.icns", append_images=[images[s] for s in (16, 32, 64, 128, 256, 512)])
    print("\n".join(str(p.relative_to(ROOT)) for p in sorted(OUT.iterdir())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
