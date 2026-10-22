"""The banner above a Library view: cover, what it is, its name, totals, Play / Shuffle."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import icons
from .artwork import CoverCache, placeholder
from .fonts import label_font, ui_font
from .theme import is_retro

COVER = 116
GAP = 3  # between the quarters of a mosaic


def compose_cover(covers: CoverCache, keys: list[str], side: int, style: str) -> QPixmap:
    """One cover (``square`` / ``round``), or a 2 x 2 ``mosaic`` of the first four albums."""
    if not keys:
        return placeholder("", side)
    out = QPixmap(side, side)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    if style == "mosaic" and len(keys) >= 4:
        half = (side - GAP) / 2
        for i, key in enumerate(keys[:4]):
            x, y = (i % 2) * (half + GAP), (i // 2) * (half + GAP)
            p.drawPixmap(QRectF(x, y, half, half), covers.large(key), QRectF(covers.large(key).rect()))
    else:
        if style == "round":
            clip = QPainterPath()
            clip.addEllipse(QRectF(0, 0, side, side))
            p.setClipPath(clip)
        large = covers.large(keys[0])
        p.drawPixmap(QRectF(0, 0, side, side), large, QRectF(large.rect()))
    p.end()
    return out


class _ElidedLabel(QLabel):
    """A one-line label that ends in "…" when it runs out of room (the full text is its tooltip)."""

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:
        return QSize(40, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:
        return QSize(40, super().sizeHint().height())

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter,
                   self.fontMetrics().elidedText(self.text(), Qt.ElideRight, rect.width()))


class CollectionHeader(QFrame):
    play_clicked = Signal()
    shuffle_clicked = Signal()
    link_clicked = Signal(str)  # the href of a link in the back line or the details

    def __init__(self, covers: CoverCache, parent=None):
        super().__init__(parent)
        self.setObjectName("CollectionHeader")
        self.covers = covers
        self._keys: list[str] = []
        self._style = "square"
        self._title = ""
        covers.loaded.connect(lambda key: key in self._keys[:4] and self._paint_cover())

        self.cover = QLabel()
        self.cover.setFixedSize(COVER, COVER)
        self.back = QLabel()
        self.back.linkActivated.connect(self.link_clicked)
        self.kind = QLabel()
        self.title = _ElidedLabel()
        self.meta = QLabel()
        self.meta.setTextFormat(Qt.RichText)
        self.meta.linkActivated.connect(self.link_clicked)
        self.play_btn = QPushButton("Play")
        self.play_btn.setDefault(True)  # the skins give the default button their accent
        self.play_btn.setAutoDefault(False)
        self.play_btn.clicked.connect(self.play_clicked)
        self.shuffle_btn = QPushButton("Shuffle")
        self.shuffle_btn.setAutoDefault(False)
        self.shuffle_btn.clicked.connect(self.shuffle_clicked)
        self.actions = QHBoxLayout()  # the page adds its own buttons after Play / Shuffle
        self.actions.setSpacing(6)
        self.actions.addWidget(self.play_btn)
        self.actions.addWidget(self.shuffle_btn)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addStretch(1)
        for widget in (self.back, self.kind, self.title, self.meta):
            text.addWidget(widget)
        text.addSpacing(8)
        text.addLayout(self.actions)
        text.addStretch(1)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 8)
        row.setSpacing(16)
        row.addWidget(self.cover, 0, Qt.AlignTop)
        row.addLayout(text, 1)
        self.restyle()

    def show_collection(self, *, kind: str, title: str, meta: str = "", art: list[tuple[str, Path]] | None = None,
                        art_style: str = "square", back: str = "", playable: bool = True) -> None:
        """``meta`` is rich text (links go to ``link_clicked``); ``back`` a link line above it all."""
        self.back.setText(back)
        self.back.setVisible(bool(back))
        self.kind.setText(kind)
        self._title = title
        self.title.setText(title.upper() if is_retro() else title)
        self.meta.setText(meta)
        self.meta.setVisible(bool(meta))
        for button in (self.play_btn, self.shuffle_btn):
            button.setVisible(playable)
        self.cover.setVisible(art is not None)
        self._keys = [key for key, _path in art or []]
        self._style = art_style
        for key, path in art or []:
            self.covers.request(key, path)
        self._paint_cover()

    def _paint_cover(self) -> None:
        if self.cover.isVisibleTo(self):
            self.cover.setPixmap(compose_cover(self.covers, self._keys, COVER, self._style))

    def restyle(self) -> None:
        """Fonts and icon colours for the current theme."""
        self.kind.setFont(label_font(7.5))
        self.kind.setStyleSheet("color: palette(link);")
        title_font = ui_font(18, QFont.Bold)
        self.title.setFont(title_font)
        self.title.setText(self._title.upper() if is_retro() else self._title)
        self.meta.setStyleSheet("color: palette(placeholder-text);")
        for label in (self.back, self.meta):  # QLabel keeps link colours from when its text was set
            text = label.text()
            label.clear()
            label.setText(text)
        for button, name in ((self.play_btn, "play"), (self.shuffle_btn, "shuffle")):
            button.setIcon(icons.icon(name, button.palette().color(QPalette.ButtonText), size=14))
        self._paint_cover()
