"""A wall of covers for the Albums and Artists views."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

from .artwork import CoverCache
from .fonts import ui_font
from .table_style import MUTED, TITLE, _tint, tier_color
from .theme import is_retro

TILE = Qt.UserRole + 1  # the item's Tile
MIN_WIDTH = 168  # tiles grow from this to fill each row exactly
PAD = 10
CAPTION = 44  # two lines under the cover


@dataclass
class Tile:
    key: str          # what the page opens when the tile is clicked
    title: str
    subtitle: str
    art_key: str      # album key of the cover to show
    art_path: Path


class _TileDelegate(QStyledItemDelegate):
    def __init__(self, grid: CoverGrid):
        super().__init__(grid)
        self.grid = grid
        self._scaled: dict[tuple[str, int], QPixmap] = {}

    def forget(self, art_key: str | None = None) -> None:
        self._scaled = {} if art_key is None else {k: v for k, v in self._scaled.items() if k[0] != art_key}

    def _cover(self, art_key: str, side: int) -> QPixmap:
        pix = self._scaled.get((art_key, side))
        if pix is None:
            large = self.grid.covers.large(art_key)
            pix = large.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if self.grid.covers.has(art_key):  # keep placeholders out, so real art replaces them
                self._scaled[(art_key, side)] = pix
        return pix

    def sizeHint(self, option, index) -> QSize:
        return self.grid.gridSize()

    def paint(self, p: QPainter, option, index) -> None:
        tile: Tile = index.data(TILE)
        if tile is None:
            return
        pal = option.palette
        rect = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        hovered = bool(option.state & QStyle.State_MouseOver)
        focused = bool(option.state & QStyle.State_Selected) and self.grid.hasFocus()
        if hovered or focused:
            back = QPainterPath()
            back.addRoundedRect(QRectF(rect).adjusted(3, 3, -3, -3), 10, 10)
            p.fillPath(back, _tint(pal.color(QPalette.Text), 34 if focused else 20))

        side = rect.width() - 2 * PAD
        cover = QRect(rect.left() + PAD, rect.top() + PAD, side, side)
        pix = self._cover(tile.art_key, side)
        outline = QPainterPath()  # a faint edge, so white covers don't melt into light skins
        if self.grid.round_covers:
            outline.addEllipse(QRectF(cover).adjusted(0.5, 0.5, -0.5, -0.5))
            p.setClipPath(outline)
            p.drawPixmap(cover, pix)
            p.setClipping(False)
        else:
            p.drawPixmap(cover, pix)
            outline.addRoundedRect(QRectF(cover).adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        p.setPen(_tint(pal.color(QPalette.Text), 40))
        p.setBrush(Qt.NoBrush)
        p.drawPath(outline)

        retro = is_retro()
        align = Qt.AlignHCenter if self.grid.round_covers else Qt.AlignLeft
        text_rect = QRect(cover.left() + 2, cover.bottom() + 8, side - 4, 18)
        for text, font, kind in ((tile.title, ui_font(9.5, QFont.DemiBold), TITLE),
                                 (tile.subtitle, ui_font(8.5), MUTED)):
            if retro:
                font.setCapitalization(QFont.AllUppercase)
                text = text.upper()
            p.setFont(font)
            color = tier_color(pal, kind)
            p.setPen(QColor(color))
            p.drawText(text_rect, align | Qt.AlignVCenter,
                       QFontMetrics(font).elidedText(text, Qt.ElideRight, text_rect.width()))
            text_rect.translate(0, 18)
        p.restore()


class CoverGrid(QListWidget):
    """Tiles of cover + two-line caption; ``opened`` fires with the clicked tile's key."""

    opened = Signal(str)

    def __init__(self, covers: CoverCache, round_covers: bool = False, parent=None):
        super().__init__(parent)
        self.covers = covers
        self.round_covers = round_covers
        self._items: dict[str, list[QListWidgetItem]] = {}
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setWordWrap(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover)
        self._delegate = _TileDelegate(self)
        self.setItemDelegate(self._delegate)
        self.clicked.connect(lambda index: self._open(index))
        covers.loaded.connect(self._on_cover)
        self._fit()

    def set_tiles(self, tiles: list[Tile]) -> None:
        self.clear()
        self._items = {}
        for tile in tiles:
            item = QListWidgetItem()
            item.setData(TILE, tile)
            item.setToolTip(f"{tile.title}\n{tile.subtitle}")
            self.addItem(item)
            self._items.setdefault(tile.art_key, []).append(item)
            self.covers.request(tile.art_key, tile.art_path)

    def apply_filter(self, needle: str) -> int:
        """Hide tiles whose caption lacks ``needle``; returns how many stay visible."""
        needle = needle.casefold()
        shown = 0
        for i in range(self.count()):
            tile: Tile = self.item(i).data(TILE)
            hidden = bool(needle) and needle not in f"{tile.title} {tile.subtitle}".casefold()
            self.item(i).setHidden(hidden)
            shown += not hidden
        return shown

    def _open(self, index) -> None:
        tile = index.data(TILE)
        if tile is not None:
            self.opened.emit(tile.key)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentIndex().isValid():
            self._open(self.currentIndex())
            return
        super().keyPressEvent(event)

    def _on_cover(self, key: str) -> None:
        if key in self._items:
            self._delegate.forget(key)
            self.viewport().update()

    def _fit(self) -> None:
        """Share each row's width between as many tiles as fit, so rows end flush."""
        # Qt wraps a row against the style's nominal scroll bar width, which can be wider than
        # the bar a skin draws; measure the same way so the last tile doesn't wrap.
        extent = self.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, self.verticalScrollBar())
        width = max(MIN_WIDTH, min(self.viewport().width(), self.contentsRect().width() - extent) - 1)
        columns = max(1, width // MIN_WIDTH)
        tile = width // columns
        size = QSize(tile, tile + CAPTION)
        if size != self.gridSize():
            self._delegate.forget()
            self.setGridSize(size)

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Resize:  # also when the scroll bar comes and goes
            self._fit()
        return super().viewportEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.PaletteChange, QEvent.FontChange):
            self.viewport().update()
