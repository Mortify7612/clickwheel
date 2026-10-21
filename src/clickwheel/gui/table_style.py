"""Shared look for song tables: one-line rows, quiet secondary text, soft rows.

A delegate paints every cell so all song tables share the same hierarchy:
the title stands out (with its cover), artist/album are quieter, numbers use
the monospace font. Colours come from the widget palette, so it works with
the retro skin and the system theme alike.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHeaderView, QStyle, QStyledItemDelegate, QTableWidget,
)

from .fonts import label_font, mono_font, ui_font, ui_font_key
from .ribbon import paint_ribs
from .theme import current_theme, is_retro

TITLE, TEXT, MUTED, NUMBER = "title", "text", "muted", "number"
MARK = "mark"  # a dot in the accent colour when the cell has any text (e.g. "on the iPod")
SECTION = Qt.UserRole + 40  # truthy on a group header row (span it across the table)
PROGRESS = Qt.UserRole + 41  # 0..1 on a cell: a thin progress bar under its text
ROW_HEIGHT = 46
SECTION_HEIGHT = 32
COVER = 36
# Retro skin: phosphor greens, brightest for titles, dimmer for supporting text.
RETRO_TIERS = {TITLE: QColor("#5dff96"), TEXT: QColor("#2fd36c"), MUTED: QColor("#1d9a4c"), NUMBER: QColor("#1d9a4c")}


def _tint(color: QColor, alpha: int) -> QColor:
    return QColor(color.red(), color.green(), color.blue(), alpha)


def _base(pal: QPalette) -> tuple[QColor, bool]:
    """The row background colour, and whether rows are glass (see-through).

    A stylesheet giving a view a see-through background leaves the view's Base as "no brush",
    whose colour reads as black; the theme's own Base is then the colour to mix with.
    """
    brush = pal.brush(QPalette.Base)
    base = pal.color(QPalette.Base) if brush.style() != Qt.NoBrush else QApplication.palette().color(QPalette.Base)
    return base, brush.style() == Qt.NoBrush or base.alpha() < 255


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """``a`` blended toward ``b`` by ``t`` (0..1)."""
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def tier_color(pal: QPalette, kind: str) -> QColor:
    """Text colour for a column kind: titles full strength, supporting text quieter."""
    if is_retro():
        return RETRO_TIERS.get(kind, RETRO_TIERS[TEXT])
    (base, _glass), text = _base(pal), pal.color(QPalette.Text)
    if kind == TITLE:
        return text
    return _mix(text, base, {TEXT: 0.22, MUTED: 0.45, NUMBER: 0.5}.get(kind, 0.3))


class TrackDelegate(QStyledItemDelegate):
    def __init__(self, kinds: dict[int, str], parent=None):
        super().__init__(parent)
        self.kinds = kinds
        self._fonts_for: tuple | None = None

    def _fonts(self, retro: bool) -> None:
        """(Re)build the cell fonts when the theme's typeface changes."""
        key = (ui_font_key(), retro)
        if key == self._fonts_for:
            return
        self._fonts_for = key
        self._title_font = ui_font(9.5, QFont.Medium)
        self._text_font = ui_font(9)
        self._number_font = mono_font(9) if retro else ui_font(9)

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
        self._fonts(retro)
        if index.data(SECTION):
            self._paint_section(p, option, index)
            return
        pal = option.palette
        (base, glass), text = _base(pal), pal.color(QPalette.Text)
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        first, last = self._row_ends(index.column())
        p.save()
        p.setRenderHint(QPainter.Antialiasing)

        # Row background: soft bands (+ faint scanlines in retro), rounded hover / selection bars.
        # Glass rows get translucent bands over whatever is behind.
        if glass:
            if index.row() % 2:
                p.fillRect(rect, _tint(text, 9))
        else:
            p.fillRect(rect, _mix(base, text, 0.035) if index.row() % 2 else base)
        if retro:
            p.setPen(QColor(57, 255, 122, 7))
            for y in range(rect.top() + 1, rect.bottom(), 3):
                p.drawLine(rect.left(), y, rect.right(), y)
        if selected and current_theme() == "y2k":
            self._paint_candy(p, option, rect, first, last)
        elif selected:
            # Glass skins blank the view's own square selection (it would show round the
            # bar), so take the highlight from the theme instead.
            hi = QApplication.palette().color(QPalette.Highlight) if glass else pal.color(QPalette.Highlight)
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0, hi.lighter(125))
            grad.setColorAt(1, hi.darker(110))
            p.fillPath(self._pill(rect, first, last), grad)
        elif hovered:
            p.fillPath(self._pill(rect, first, last), _tint(text, 20))
        if not selected:
            p.setPen(_tint(text, 18) if glass else _mix(base, text, 0.07))
            p.drawLine(rect.bottomLeft(), rect.bottomRight())

        # Foreground: now-playing / status colours win, then the column's tier.
        override = index.data(Qt.ForegroundRole)
        if selected:
            color = pal.color(QPalette.HighlightedText)
        elif override is not None:
            color = override.color() if hasattr(override, "color") else QColor(override)
        elif kind == MARK:
            color = pal.color(QPalette.Link)
        else:
            color = tier_color(pal, kind)
        font = QFont(self._number_font if kind == NUMBER else self._title_font if kind == TITLE else self._text_font)
        item_font = index.data(Qt.FontRole)
        if item_font is not None and item_font.bold():
            font.setWeight(QFont.DemiBold if kind != NUMBER else QFont.Bold)
        if retro:
            font.setCapitalization(QFont.AllUppercase)
            font.setLetterSpacing(QFont.PercentageSpacing, 104)
        p.setFont(font)

        inner = rect.adjusted(12, 0, -12, 0)
        if kind == MARK:
            if index.data(Qt.DisplayRole):
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawEllipse(QRectF(rect).center(), 3.5, 3.5)
            p.restore()
            return
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
        progress = index.data(PROGRESS)
        if progress is not None:
            bar = QRectF(inner.left(), rect.bottom() - 11, inner.width(), 4)
            track = QPainterPath()
            track.addRoundedRect(bar, 2, 2)
            p.fillPath(track, _tint(color, 45))
            done = QPainterPath()
            done.addRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * max(0.0, min(1.0, progress)), bar.height()),
                                2, 2)
            p.fillPath(done, pal.color(QPalette.Link) if not selected else color)
        p.restore()


    def _paint_candy(self, p, option, rect: QRect, first: bool, last: bool) -> None:
        """Y2K selection: one pink-lilac-blue candy bar across the whole row, with a gloss on top."""
        width = option.widget.viewport().width() if option.widget is not None else rect.width()
        pill = self._pill(rect, first, last, 12)
        candy = QLinearGradient(0, 0, width, 0)
        candy.setColorAt(0, QColor("#ff8fcf"))
        candy.setColorAt(0.5, QColor("#b79cff"))
        candy.setColorAt(1, QColor("#6fc6ff"))
        p.fillPath(pill, candy)
        bar = pill.boundingRect()
        shine = QLinearGradient(bar.topLeft(), bar.bottomLeft())
        shine.setColorAt(0, QColor(255, 255, 255, 150))
        shine.setColorAt(0.48, QColor(255, 255, 255, 40))
        shine.setColorAt(0.52, QColor(255, 255, 255, 0))
        p.fillPath(pill, shine)

    @staticmethod
    def _paint_section(p, option, index) -> None:
        """A group header: a soft band with a small caps label in the accent colour
        (retro: the label trailed by Winamp's gold ribs)."""
        pal = option.palette
        (base, glass), text = _base(pal), pal.color(QPalette.Text)
        rect = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if not glass:
            p.fillRect(rect, base)
        retro = is_retro()
        if not retro:
            band = QPainterPath()
            band.addRoundedRect(QRectF(rect).adjusted(4, 4, -4, -2), 7, 7)
            p.fillPath(band, _tint(text, 18) if glass else _mix(base, text, 0.07))
        font = label_font(8)
        p.setFont(font)
        p.setPen(pal.color(QPalette.Link))
        inner = rect.adjusted(14, 2, -14, 0)
        metrics = QFontMetrics(font)
        label = metrics.elidedText(str(index.data(Qt.DisplayRole) or ""), Qt.ElideRight, inner.width() - 30)
        p.drawText(inner, Qt.AlignLeft | Qt.AlignVCenter, label)
        if retro:
            p.setRenderHint(QPainter.Antialiasing, False)
            start = inner.left() + metrics.horizontalAdvance(label) + 10
            paint_ribs(p, QRect(start, rect.top() + 1, inner.right() - start, rect.height()))
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
        cols = [c for c in sorted(self.weights) if not t.isColumnHidden(c)]
        if not cols:
            return
        total = sum(self.weights[c] for c in cols)
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


def restyle_table(table: QTableWidget) -> None:
    """Pick up a theme change: header fonts are set per item, so refresh them."""
    table.horizontalHeader().setFont(label_font())
    delegate = table.itemDelegate()
    if isinstance(delegate, TrackDelegate):
        style_header(table, delegate.kinds)
    table.viewport().update()


def style_track_table(table: QTableWidget, kinds: dict[int, str], widths: dict[int, int],
                      weights: dict[int, int]) -> _ProportionalColumns:
    """Apply the shared song-table look. ``widths``: fixed-ish columns; ``weights``: share the rest.

    Call ``apply()`` on the result after showing or hiding columns."""
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
    return _ProportionalColumns(table, weights)
