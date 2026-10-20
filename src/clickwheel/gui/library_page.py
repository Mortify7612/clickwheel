"""Library tab: local songs and playlists."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..library import Library
from . import workers

ALL = "__all__"


class LibraryPage(QWidget):
    def __init__(self, library: Library, manager: workers.DownloadManager):
        super().__init__()
        self.library = library
        self.manager = manager

        self.lists = QListWidget()
        self.lists.currentItemChanged.connect(lambda *_: self._show_tracks())
        self.update_btn = QPushButton("Update from YouTube Music")
        self.update_btn.setToolTip("Download songs added to this playlist since the last time")
        self.update_btn.clicked.connect(self._update_playlist)
        self.remove_list_btn = QPushButton("Remove playlist")
        self.remove_list_btn.clicked.connect(self._remove_playlist)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>Collections</b>"))
        lv.addWidget(self.lists, 1)
        lv.addWidget(self.update_btn)
        lv.addWidget(self.remove_list_btn)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter…")
        self.filter.textChanged.connect(self._apply_filter)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Title", "Artist", "Album", "Year"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSortingEnabled(True)
        hh = self.table.horizontalHeader()
        for col in (1, 2, 3):
            hh.setSectionResizeMode(col, QHeaderView.Stretch)
        open_btn = QPushButton("Open library folder")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.root))))
        delete_btn = QPushButton("Delete selected songs")
        delete_btn.clicked.connect(self._delete_selected)
        self.summary = QLabel()
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.filter)
        rv.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(self.summary, 1)
        row.addWidget(open_btn)
        row.addWidget(delete_btn)
        rv.addLayout(row)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([260, 740])
        QVBoxLayout(self).addWidget(split)

        manager.library_changed.connect(self.refresh)
        self.refresh()

    def _selected_list(self) -> str:
        item = self.lists.currentItem()
        return item.data(256) if item else ALL

    def refresh(self) -> None:
        current = self._selected_list()
        self.lists.blockSignals(True)
        self.lists.clear()
        everything = QListWidgetItem(f"All songs ({len(self.library.tracks())})")
        everything.setData(256, ALL)
        self.lists.addItem(everything)
        for p in self.library.playlists():
            icon = {"album": "💿", "playlist": "🎵"}.get(p.kind, "")
            item = QListWidgetItem(f"{icon} {p.title} ({p.track_count})")
            item.setData(256, p.id)
            self.lists.addItem(item)
            if p.id == current:
                self.lists.setCurrentItem(item)
        if self.lists.currentItem() is None:
            self.lists.setCurrentRow(0)
        self.lists.blockSignals(False)
        self._show_tracks()

    def _show_tracks(self) -> None:
        pid = self._selected_list()
        tracks = self.library.tracks() if pid == ALL else self.library.playlist_tracks(pid)
        self.update_btn.setEnabled(pid != ALL)
        self.remove_list_btn.setEnabled(pid != ALL)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(tracks))
        for row, t in enumerate(tracks):
            num = QTableWidgetItem()
            num.setData(0, t.track_number or None)
            num.setData(256, t.video_id)
            self.table.setItem(row, 0, num)
            for col, text in enumerate([t.title, t.artist, t.album, t.year], start=1):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.table.setSortingEnabled(pid == ALL)
        minutes = sum(t.duration for t in tracks) // 60
        self.summary.setText(f"{len(tracks)} songs · {minutes // 60} h {minutes % 60} min")
        self._apply_filter(self.filter.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold()
        for row in range(self.table.rowCount()):
            hay = " ".join(self.table.item(row, c).text() for c in (1, 2, 3)).casefold()
            self.table.setRowHidden(row, bool(needle) and needle not in hay)

    def _delete_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        if QMessageBox.question(self, "Delete songs",
                                f"Delete {len(rows)} song(s) from your library and disk? "
                                "They'll be removed from the iPod on the next sync.") != QMessageBox.Yes:
            return
        for row in rows:
            self.library.delete_track(self.table.item(row, 0).data(256))
        self.refresh()

    def _update_playlist(self) -> None:
        pid = self._selected_list()
        playlist = next((p for p in self.library.playlists() if p.id == pid), None)
        if playlist is None:
            return
        if playlist.url:
            self.manager.enqueue_url(playlist.url)
        else:
            self.manager.enqueue_playlist(pid, playlist.title)

    def _remove_playlist(self) -> None:
        pid = self._selected_list()
        if pid != ALL and QMessageBox.question(
                self, "Remove playlist", "Remove this playlist? Its songs stay in your library.") == QMessageBox.Yes:
            self.library.delete_playlist(pid)
            self.refresh()
