"""Read-only browser for the songs and playlists already on a device."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..devices.contents import DeviceContents
from . import workers
from .artwork import THUMB, ArtPanel, CoverCache, album_key

ALL = -1
ART_KEY, ART_PATH = 257, 258  # item data roles on the Title cell


def _length(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else ""


class DeviceBrowser(QWidget):
    def __init__(self):
        super().__init__()
        self._contents = DeviceContents([], [])
        self._loader = None
        self._device = None
        self.covers = CoverCache(self)
        self.covers.loaded.connect(self._on_cover)
        self._art_items: dict[str, list[QTableWidgetItem]] = {}

        self.lists = QListWidget()
        self.lists.currentRowChanged.connect(lambda _row: self._show_tracks())
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(lambda: self.load(self._device))
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.lists, 1)
        lv.addWidget(self.refresh_btn)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter…")
        self.filter.textChanged.connect(self._apply_filter)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["#", "Title", "Artist", "Album", "Time", "Plays"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setIconSize(QSize(THUMB, THUMB))
        self.table.verticalHeader().setDefaultSectionSize(THUMB + 6)
        self.table.currentCellChanged.connect(lambda row, *_: self._show_selected(row))
        hh = self.table.horizontalHeader()
        for col in (1, 2, 3):
            hh.setSectionResizeMode(col, QHeaderView.Stretch)
        self.summary = QLabel()
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.filter)
        rv.addWidget(self.table, 1)
        rv.addWidget(self.summary)

        self.art = ArtPanel(self.covers)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.addWidget(self.art)
        split.setSizes([200, 640, 250])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

    def load(self, device, prefer_rockbox_files: bool = True) -> None:
        self._device = device
        if device is None:
            self._set_contents(DeviceContents([], []), "No device")
            return
        self.summary.setText("Reading device…")
        self.refresh_btn.setEnabled(False)
        try:
            backend = device.backend(prefer_rockbox_files)
        except RuntimeError as exc:
            self._set_contents(DeviceContents([], []), str(exc))
            return
        path = device.path

        def done(contents):
            if self._device is not None and self._device.path == path:  # ignore stale loads
                self._set_contents(contents)

        def failed(message):
            self._set_contents(DeviceContents([], []), f"Couldn't read the device: {message}")

        self._loader = workers.run(backend.browse, on_done=done, on_error=failed)

    def _set_contents(self, contents: DeviceContents, note: str = "") -> None:
        self._contents = contents
        self.covers.clear()  # a different device (or a re-sync) may have different art
        self.refresh_btn.setEnabled(True)
        self.lists.blockSignals(True)
        self.lists.clear()
        everything = QListWidgetItem(f"All songs ({len(contents.tracks)})")
        everything.setData(256, ALL)
        self.lists.addItem(everything)
        for i, p in enumerate(contents.playlists):
            item = QListWidgetItem(f"{p.name} ({len(p.track_indices)})")
            item.setData(256, i)
            self.lists.addItem(item)
        self.lists.setCurrentRow(0)
        self.lists.blockSignals(False)
        self._show_tracks(note)

    def _show_tracks(self, note: str = "") -> None:
        item = self.lists.currentItem()
        which = item.data(256) if item else ALL
        if which == ALL:
            tracks = sorted(self._contents.tracks,
                            key=lambda t: (t.artist.casefold(), t.album.casefold(), t.track_number))
        else:
            tracks = [self._contents.tracks[i] for i in self._contents.playlists[which].track_indices]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(tracks))
        self._art_items = {}
        root = self._device.path if self._device is not None else None
        for row, t in enumerate(tracks):
            num = QTableWidgetItem()
            num.setData(0, t.track_number or None)
            self.table.setItem(row, 0, num)
            for col, text in enumerate([t.title, t.artist, t.album, _length(t.duration)], start=1):
                cell = QTableWidgetItem(text)
                cell.setToolTip(t.location)
                self.table.setItem(row, col, cell)
            plays = QTableWidgetItem()
            plays.setData(0, t.play_count)
            self.table.setItem(row, 5, plays)
            key = album_key(t.artist, t.album)
            title = self.table.item(row, 1)
            title.setData(ART_KEY, key)
            title.setIcon(QIcon(self.covers.thumb(key)))
            self._art_items.setdefault(key, []).append(title)
            source = t.artwork or (root / t.location.lstrip("/") if root is not None and t.location else None)
            if source is not None:
                title.setData(ART_PATH, source)
                self.covers.request(key, source)
        self.table.setSortingEnabled(which == ALL)
        self._show_selected(self.table.currentRow())
        minutes = sum(t.duration for t in tracks) // 60
        self.summary.setText(note or f"{len(tracks)} songs · {minutes // 60} h {minutes % 60} min")
        self._apply_filter(self.filter.text())

    def _on_cover(self, key: str) -> None:
        icon = QIcon(self.covers.thumb(key))
        for item in self._art_items.get(key, []):
            item.setIcon(icon)

    def _show_selected(self, row: int) -> None:
        title = self.table.item(row, 1) if row >= 0 else None
        if title is None:
            self.art.show_track(None)
            return
        self.art.show_track(title.data(ART_KEY), title.text(), self.table.item(row, 2).text(),
                            self.table.item(row, 3).text(), title.data(ART_PATH))

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold()
        for row in range(self.table.rowCount()):
            hay = " ".join(self.table.item(row, c).text() for c in (1, 2, 3)).casefold()
            self.table.setRowHidden(row, bool(needle) and needle not in hay)
