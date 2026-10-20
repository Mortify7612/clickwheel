"""Shared look for song tables: one-line rows, quiet secondary text, soft rows.

A delegate paints every cell so all song tables share the same hierarchy:
the title stands out (with its cover), artist/album are quieter, numbers use
the monospace font. Colours come from the widget palette, so it works with
the retro skin and the system theme alike.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPalette
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTableWidget

from .fonts import label_font, mono_font, ui_font

TITLE, TEXT, MUTED, NUMBER = "title", "text", "muted", "number"
ROW_HEIGHT = 46
COVER = 36


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """``a`` blended toward ``b`` by ``t`` (0..1)."""
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


class TrackDelegate(QStyledItemDelegate):
    def __init__(self, kinds: dict[int, str], parent=None):
        super().__init__(parent)
        self.kinds = kinds
        self._title_font = ui_font(10, QFont.Medium)
        self._text_font = ui_font(9.5)
        self._number_font = mono_font(9)

    def sizeHint(self, option, index) -> QSize:
        return QSize(super().sizeHint(option, index).width(), ROW_HEIGHT)

    def paint(self, p, option, index) -> None:
        kind = self.kinds.get(index.column(), TEXT)
        pal = option.palette
        base, text = pal.color(QPalette.Base), pal.color(QPalette.Text)
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        p.save()

        # Row background: soft alternating bands, hover lift, gradient selection bar.
        if selected:
            hi = pal.color(QPalette.Highlight)
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0, hi.lighter(122))
            grad.setColorAt(1, hi.darker(108))
            p.fillRect(rect, grad)
        else:
            p.fillRect(rect, _mix(base, text, 0.035) if index.row() % 2 else base)
            if hovered:
                p.fillRect(rect, QColor(text.red(), text.green(), text.blue(), 16))
        p.setPen(_mix(base, text, 0.08))
        p.drawLine(rect.bottomLeft(), rect.bottomRight())

        # Foreground: now-playing / status colours win, then the column's tier.
        override = index.data(Qt.ForegroundRole)
        if selected:
            color = pal.color(QPalette.HighlightedText)
        elif override is not None:
            color = override.color() if hasattr(override, "color") else QColor(override)
        elif kind == TITLE:
            color = text
        else:
            color = _mix(text, base, {TEXT: 0.22, MUTED: 0.45, NUMBER: 0.5}.get(kind, 0.3))
        font = QFont(self._number_font if kind == NUMBER else self._title_font if kind == TITLE else self._text_font)
        item_font = index.data(Qt.FontRole)
        if item_font is not None and item_font.bold():
            font.setWeight(QFont.DemiBold if kind != NUMBER else QFont.Bold)
        p.setFont(font)
        p.setPen(color)

        inner = rect.adjusted(10, 0, -10, 0)
        icon = index.data(Qt.DecorationRole)
        if kind == TITLE and icon is not None:
            pix = icon.pixmap(COVER, COVER)
            top = rect.top() + (rect.height() - COVER) // 2
            p.drawPixmap(QRect(inner.left() - 4, top, COVER, COVER), pix)
            inner.setLeft(inner.left() - 4 + COVER + 10)

        value = index.data(Qt.DisplayRole)
        label = "" if value is None else str(value)
        align = (Qt.AlignRight if kind == NUMBER else Qt.AlignLeft) | Qt.AlignVCenter
        p.drawText(inner, align, QFontMetrics(font).elidedText(label, Qt.ElideRight, inner.width()))
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
