"""The equalizer panel under the player deck: on/off, presets, and a ten-band graph to drag."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..equalizer import BANDS, LIMIT_DB, PRESETS, clamp_db
from .fonts import label_font, mono_font
from .ribbon import SectionLabel
from .table_style import _base, _tint
from .theme import is_retro, lcd_skin

CUSTOM = "Custom"
SCALE_WIDTH = 34  # the dB labels on the left
PREAMP_GAP = 16   # between the preamp and the bands
LABEL_HEIGHT = 18  # band names under the graph
KNOB = QSize(20, 9)


def _band_name(hz: int) -> str:
    return f"{hz // 1000}K" if hz >= 1000 else str(hz)


def _snap(db: float) -> float:
    """Half-dB steps, with a little stickiness at 0."""
    db = clamp_db(round(db * 2) / 2)
    return 0.0 if abs(db) < 0.75 else db


class EqGraph(QWidget):
    """A preamp fader, then one fader per band, with the response curve drawn through them.

    Drag a knob (or anywhere in its column), scroll over it for half-dB steps, or
    double-click it to put it back to 0.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gains = [0.0] * len(BANDS)
        self.preamp = 0.0
        self.active = True  # drawn dimmed while the equalizer is off
        self._drag: int | None = None   # -1: preamp, 0..9: a band
        self._hover: int | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(360, 112)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_values(self, gains, preamp: float) -> None:
        self.gains = [clamp_db(g) for g in gains]
        self.preamp = clamp_db(preamp)
        self.update()

    # ── Geometry ─────────────────────────────────────────────────────────

    def _screen(self) -> QRectF:
        return QRectF(self.rect()).adjusted(SCALE_WIDTH, 2, -2, -LABEL_HEIGHT)

    def _column(self, index: int) -> QRectF:
        """Column -1 is the preamp; 0..9 the bands."""
        screen = self._screen()
        width = (screen.width() - PREAMP_GAP) / (len(BANDS) + 1)
        left = screen.left() + (0 if index < 0 else width * (index + 1) + PREAMP_GAP)
        return QRectF(left, screen.top(), width, screen.height())

    def _track(self) -> tuple[float, float]:
        """The y of +12 dB and of -12 dB."""
        screen = self._screen()
        return screen.top() + KNOB.height(), screen.bottom() - KNOB.height()

    def _y(self, db: float) -> float:
        top, bottom = self._track()
        return top + (LIMIT_DB - db) / (2 * LIMIT_DB) * (bottom - top)

    def _db(self, y: float) -> float:
        top, bottom = self._track()
        return LIMIT_DB - (y - top) / max(1.0, bottom - top) * 2 * LIMIT_DB

    def _hit(self, pos: QPointF) -> int | None:
        for index in range(-1, len(BANDS)):
            if self._column(index).adjusted(0, -4, 0, LABEL_HEIGHT).contains(pos):
                return index
        return None

    def _value(self, index: int) -> float:
        return self.preamp if index < 0 else self.gains[index]

    def _set(self, index: int, db: float) -> None:
        db = _snap(db)
        if db == self._value(index):
            return
        if index < 0:
            self.preamp = db
        else:
            self.gains[index] = db
        self.update()
        self.changed.emit()

    # ── Input ────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        index = self._hit(event.position())
        if event.button() == Qt.LeftButton and index is not None:
            self._drag = index
            self._set(index, self._db(event.position().y()))

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            self._set(self._drag, self._db(event.position().y()))
            return
        hover = self._hit(event.position())
        if hover != self._hover:
            self._hover = hover
            self.update()

    def mouseReleaseEvent(self, _event) -> None:
        self._drag = None
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        index = self._hit(event.position())
        if index is not None:
            self._set(index, 0.0)

    def wheelEvent(self, event) -> None:
        index = self._hit(event.position())
        if index is not None and event.angleDelta().y():
            self._set(index, self._value(index) + (0.5 if event.angleDelta().y() > 0 else -0.5))

    def leaveEvent(self, _event) -> None:
        self._hover = None
        self.update()

    # ── Painting ─────────────────────────────────────────────────────────

    def _colors(self) -> tuple[QColor, QColor, QColor, bool]:
        """Screen, text, curve colours, and whether the screen is see-through."""
        pal = self.palette()
        (base, glass), text = _base(pal), pal.color(QPalette.Text)
        curve = QColor(lcd_skin().lit) if is_retro() else pal.color(QPalette.Link)
        return base, text, curve, glass

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base, text, curve_color, glass = self._colors()
        accent = self.palette().color(QPalette.Link)
        screen = self._screen()

        panel = QPainterPath()
        panel.addRoundedRect(screen.adjusted(-4, -2, 2, 2), 8, 8)
        p.fillPath(panel, _tint(text, 14) if glass else base)
        if not self.active:
            p.setOpacity(0.45)

        # dB scale and grid lines
        p.setFont(mono_font(7))
        for db in (12, 6, 0, -6, -12):
            y = self._y(db)
            p.setPen(QPen(_tint(text, 70 if db == 0 else 26), 1, Qt.SolidLine if db == 0 else Qt.DotLine))
            p.drawLine(QPointF(screen.left(), y), QPointF(screen.right(), y))
            if db in (12, 0, -12):
                p.setPen(_tint(text, 150))
                p.drawText(QRectF(0, y - 8, SCALE_WIDTH - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{db:+d}" if db else "0")

        # The curve through the band knobs, filled toward 0 dB.
        centers = [self._column(i).center().x() for i in range(len(BANDS))]
        zero = self._y(0)
        line = QPainterPath()
        steps = 12
        for i in range(len(BANDS) - 1):
            for s in range(steps + (i == len(BANDS) - 2)):
                t = s / steps
                db = self.gains[i] + (self.gains[i + 1] - self.gains[i]) * (1 - math.cos(math.pi * t)) / 2
                point = QPointF(centers[i] + (centers[i + 1] - centers[i]) * t, self._y(db))
                if line.elementCount():
                    line.lineTo(point)
                else:
                    line.moveTo(point)
        fill = QPainterPath(line)
        fill.lineTo(centers[-1], zero)
        fill.lineTo(centers[0], zero)
        fill.closeSubpath()
        shade = QLinearGradient(0, self._y(LIMIT_DB), 0, self._y(-LIMIT_DB))
        shade.setColorAt(0, _tint(curve_color, 90))
        shade.setColorAt(0.5, _tint(curve_color, 20))
        shade.setColorAt(1, _tint(curve_color, 90))
        p.fillPath(fill, shade)
        p.setPen(QPen(curve_color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(line)

        # Preamp divider, tracks, knobs and labels.
        divider = self._column(0).left() - PREAMP_GAP / 2
        p.setPen(QPen(_tint(text, 40), 1))
        p.drawLine(QPointF(divider, screen.top() + 4), QPointF(divider, screen.bottom() - 4))
        names = ["PRE"] + [_band_name(hz) for hz in BANDS]
        top, bottom = self._track()
        font = label_font(7)
        for index, name in zip(range(-1, len(BANDS)), names):
            column = self._column(index)
            x = column.center().x()
            p.setPen(QPen(_tint(text, 55), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
            value = self._value(index)
            knob = QRectF(x - KNOB.width() / 2, self._y(value) - KNOB.height() / 2, KNOB.width(), KNOB.height())
            lit = index in (self._drag, self._hover)
            grip = QLinearGradient(knob.topLeft(), knob.bottomLeft())
            grip.setColorAt(0, accent.lighter(150 if lit else 125))
            grip.setColorAt(1, accent.darker(125 if lit else 140))
            p.setPen(QPen(accent.darker(220), 1))
            p.setBrush(grip)
            p.drawRoundedRect(knob, 3, 3)
            p.setFont(font)
            p.setPen(accent if lit else _tint(text, 170))
            label = QRectF(column.left() - 6, screen.bottom() + 3, column.width() + 12, LABEL_HEIGHT - 3)
            p.drawText(label, Qt.AlignHCenter | Qt.AlignTop, name)
            if lit:  # the exact value, above the knob
                p.setFont(mono_font(7.5))
                p.setPen(text)
                readout = f"{value:+.1f}" if value else "0"
                above = knob.top() - 14 if knob.top() - 14 > screen.top() else knob.bottom() + 2
                p.drawText(QRectF(x - 24, above, 48, 12), Qt.AlignCenter, readout)
        p.end()


class EqPanel(QFrame):
    """Shown under the player deck. ``changed`` fires on any edit, with the panel's values in
    ``enabled``, ``gains``, ``preamp`` and ``preset``."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PlayerDeck")  # dressed like the deck it hangs under
        self.setFrameShape(QFrame.StyledPanel)
        self.preset = "Flat"
        self.graph = EqGraph()
        self.graph.changed.connect(self._edited)
        self.power = QPushButton("Off")
        self.power.setCheckable(True)
        self.power.setToolTip("Play through the equalizer")
        self.power.toggled.connect(self._toggled)
        self.presets = QComboBox()
        self.presets.addItems(list(PRESETS))
        self.presets.setToolTip("Presets")
        self.presets.activated.connect(lambda i: self._choose(self.presets.itemText(i)))
        self.flat = QPushButton("Reset")
        self.flat.setToolTip("Every band and the preamp back to 0 dB")
        self.flat.clicked.connect(lambda: self._choose("Flat", preamp=0.0))
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(SectionLabel("<b>Equalizer</b>"))
        left.addWidget(self.power)
        left.addWidget(self.presets)
        left.addWidget(self.flat)
        left.addStretch(1)
        side = QWidget()
        side.setLayout(left)
        side.setFixedWidth(150)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 14, 8)
        row.setSpacing(16)
        row.addWidget(side)
        row.addWidget(self.graph, 1)
        self._sync_power()

    @property
    def enabled(self) -> bool:
        return self.power.isChecked()

    @property
    def gains(self) -> list[float]:
        return list(self.graph.gains)

    @property
    def preamp(self) -> float:
        return self.graph.preamp

    def set_values(self, enabled: bool, gains, preamp: float, preset: str = "") -> None:
        """Show saved settings (without firing ``changed``)."""
        self.blockSignals(True)
        self.power.setChecked(enabled)
        self.graph.set_values(gains, preamp)
        self.preset = preset if preset in PRESETS and tuple(self.gains) == tuple(map(float, PRESETS[preset])) \
            else self._match()
        self._show_preset()
        self._sync_power()
        self.blockSignals(False)

    def _match(self) -> str:
        """The preset the bands match (the preamp is a separate trim), else Custom."""
        return next((name for name, gains in PRESETS.items() if tuple(map(float, gains)) == tuple(self.gains)),
                    CUSTOM)

    def _show_preset(self) -> None:
        custom = self.presets.findText(CUSTOM)
        if self.preset == CUSTOM and custom < 0:
            self.presets.addItem(CUSTOM)
        elif self.preset != CUSTOM and custom >= 0:
            self.presets.removeItem(custom)
        self.presets.setCurrentText(self.preset)

    def _choose(self, name: str, preamp: float | None = None) -> None:
        """Presets set the bands and leave the preamp; Reset (``preamp=0``) clears that too."""
        if name not in PRESETS:
            return
        self.preset = name
        self.graph.set_values(PRESETS[name], self.preamp if preamp is None else preamp)
        self._show_preset()
        self.changed.emit()

    def _edited(self) -> None:
        self.preset = self._match()
        self._show_preset()
        self.changed.emit()

    def _toggled(self, _on: bool) -> None:
        self._sync_power()
        self.changed.emit()

    def _sync_power(self) -> None:
        on = self.power.isChecked()
        self.power.setText("On" if on else "Off")
        self.graph.active = on
        self.graph.update()
