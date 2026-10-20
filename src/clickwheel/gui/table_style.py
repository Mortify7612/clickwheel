"""Shared look for song tables: one-line rows, quiet secondary text, soft rows.

A delegate paints every cell so all song tables share the same hierarchy:
the title stands out (with its cover), artist/album are quieter, numbers use
the monospace font. Colours come from the widget palette, so it works with
the retro skin and the system theme alike.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPalette
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTableWidget

from .fonts import label_font, mono_font, ui_font
from .theme import is_retro

TITLE, TEXT, MUTED, NUMBER = "title", "text", "muted", "number"
ROW_HEIGHT = 46
COVER = 36
# Retro skin: phosphor greens, brightest for titles, dimmer for supporting text.
RETRO_TIERS = {TITLE: QColor("#5dff96"), TEXT: QColor("#2fd36c"), MUTED: QColor("#1d9a4c"), NUMBER: QColor("#1d9a4c")}


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """``a`` blended toward ``b`` by ``t`` (0..1)."""
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


class TrackDelegate(QStyledItemDelegate):
    def __init__(self, kinds: dict[int, str], parent=None):
        super().__init__(parent)
        self.kinds = kinds
        self._title_font = ui_font(9.5, QFont.Medium)
        self._text_font = ui_font(9)
        self._number_font = mono_font(9)

    def sizeHint(self, option, index) -> QSize:
        return QSize(super().sizeHint(option, index).width(), ROW_HEIGHT)

    def _row_ends(self, column: int) -> tuple[bool, bool]:
        """Whether ``column`` is the first / last visible column (for rounding row ends)."""
        table = self.parent()
        header = table.horizontalHeader()
        visible = [header.logicalIndex(v) for v in range(header.count())
                   if not header.isSectionHidden(header.logicalIndex(v))]
        return (bool(visible) and column == visible[0], bool(visible) and column == visible[-1])

    @staticmethod
    def _pill(rect: QRect, first: bool, last: bool, radius: float = 8) -> QPainterPath:
        """A rounded bar spanning the row: cells round only their outer ends."""
        r = QRectF(rect).adjusted(4 if first else 0, 3, -4 if last else 0, -3)
        # Extend inner edges past the cell so neighbouring cells join seamlessly.
        wide = r.adjusted(0 if first else -radius * 2, 0, 0 if last else radius * 2, 0)
        path = QPainterPath()
        path.addRoundedRect(wide, radius, radius)
        clip = QPainterPath()
        clip.addRect(QRectF(rect))
        return path.intersected(clip)

    def paint(self, p, option, index) -> None:
        kind = self.kinds.get(index.column(), TEXT)
        retro = is_retro()
        pal = option.palette
        base, text = pal.color(QPalette.Base), pal.color(QPalette.Text)
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        first, last = self._row_ends(index.column())
        p.save()
        p.setRenderHint(QPainter.Antialiasing)

        # Row background: soft bands (+ faint scanlines in retro), rounded hover / selection bars.
        p.fillRect(rect, _mix(base, text, 0.035) if index.row() % 2 else base)
        if retro:
            p.setPen(QColor(57, 255, 122, 7))
            for y in range(rect.top() + 1, rect.bottom(), 3):
                p.drawLine(rect.left(), y, rect.right(), y)
        if selected:
            hi = pal.color(QPalette.Highlight)
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0, hi.lighter(125))
            grad.setColorAt(1, hi.darker(110))
            p.fillPath(self._pill(rect, first, last), grad)
        elif hovered:
            p.fillPath(self._pill(rect, first, last), QColor(text.red(), text.green(), text.blue(), 20))
        if not selected:
            p.setPen(_mix(base, text, 0.07))
            p.drawLine(rect.bottomLeft(), rect.bottomRight())

        # Foreground: now-playing / status colours win, then the column's tier.
        override = index.data(Qt.ForegroundRole)
        if selected:
            color = pal.color(QPalette.HighlightedText)
        elif override is not None:
            color = override.color() if hasattr(override, "color") else QColor(override)
        elif retro:
            color = RETRO_TIERS.get(kind, RETRO_TIERS[TEXT])
        elif kind == TITLE:
            color = text
        else:
            color = _mix(text, base, {TEXT: 0.22, MUTED: 0.45, NUMBER: 0.5}.get(kind, 0.3))
        font = QFont(self._number_font if kind == NUMBER else self._title_font if kind == TITLE else self._text_font)
        item_font = index.data(Qt.FontRole)
        if item_font is not None and item_font.bold():
            font.setWeight(QFont.DemiBold if kind != NUMBER else QFont.Bold)
        if retro:
            font.setCapitalization(QFont.AllUppercase)
            font.setLetterSpacing(QFont.PercentageSpacing, 104)
        p.setFont(font)

        inner = rect.adjusted(12, 0, -12, 0)
        icon = index.data(Qt.DecorationRole)
        if kind == TITLE and icon is not None:
            pix = icon.pixmap(COVER, COVER)
            top = rect.top() + (rect.height() - COVER) // 2
            p.drawPixmap(QRect(inner.left() - 4, top, COVER, COVER), pix)
            inner.setLeft(inner.left() - 4 + COVER + 10)

        value = index.data(Qt.DisplayRole)
        label = "" if value is None else str(value)
        align = (Qt.AlignRight if kind == NUMBER else Qt.AlignLeft) | Qt.AlignVCenter
        shown = QFontMetrics(font).elidedText(label.upper() if retro else label, Qt.ElideRight, inner.width())
        if retro and kind == TITLE and not selected:
            # Phosphor glow: a faint halo behind bright text.
            p.setPen(QColor(color.red(), color.green(), color.blue(), 55))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(inner.translated(dx, dy), align, shown)
        p.setPen(color)
        p.drawText(inner, align, shown)
        p.restore()


class _ProportionalColumns(QObject):
    """Share the width left over by fixed columns between weighted ones on every resize."""

    def __init__(self, table: QTableWidget, weights: dict[int, int]):
        super().__init__(table)
        self.table, self.weights = table, weights
        table.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Resize:
            self.apply()
        return False

    def apply(self) -> None:
        t = self.table
        fixed = sum(t.columnWidth(c) for c in range(t.columnCount()) if c not in self.weights and not t.isColumnHidden(c))
        free = max(0, t.viewport().width() - fixed - 1)
        total = sum(self.weights.values())
        cols = sorted(self.weights)
        for c in cols[:-1]:
            t.setColumnWidth(c, max(80, free * self.weights[c] // total))
        used = sum(t.columnWidth(c) for c in cols[:-1])
        t.setColumnWidth(cols[-1], max(80, free - used))


def style_header(table: QTableWidget, kinds: dict[int, str]) -> None:
    """Spaced caps labels. Set per item: a header item's own font overrides the header's."""
    font = label_font()
    for col in range(table.columnCount()):
        item = table.horizontalHeaderItem(col)
        if item is None:
            continue
        item.setFont(font)
        right = kinds.get(col) == NUMBER
        item.setTextAlignment((Qt.AlignRight if right else Qt.AlignLeft) | Qt.AlignVCenter)


def style_track_table(table: QTableWidget, kinds: dict[int, str], widths: dict[int, int],
                      weights: dict[int, int]) -> None:
    """Apply the shared song-table look. ``widths``: fixed-ish columns; ``weights``: share the rest."""
    table.setItemDelegate(TrackDelegate(kinds, table))
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setMouseTracking(True)
    table.viewport().setAttribute(Qt.WA_Hover)
    table.setIconSize(QSize(COVER, COVER))
    table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    header = table.horizontalHeader()
    header.setFont(label_font())
    header.setHighlightSections(False)
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    header.setMinimumSectionSize(40)
    header.setFixedHeight(30)
    header.setStretchLastSection(False)
    for col in range(table.columnCount()):
        header.setSectionResizeMode(col, QHeaderView.Interactive)
        if col in widths:
            table.setColumnWidth(col, widths[col])
    style_header(table, kinds)
    _ProportionalColumns(table, weights)
