"""Library tab: local songs and playlists."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDateTime, QLocale, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..library import Library
from . import workers
from .artwork import ArtPanel, CoverCache, album_key
from .table_style import MUTED, NUMBER, TEXT, TITLE, style_track_table

ALL = "__all__"
ART_KEY, ART_PATH = 257, 258  # item data roles on the Title cell


class SortKeyItem(QTableWidgetItem):
    """Shows friendly text but sorts by a hidden key (Qt.UserRole)."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine, theirs = self.data(Qt.UserRole), other.data(Qt.UserRole)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return mine < theirs


class LibraryPage(QWidget):
    sync_requested = Signal(list)  # library file paths to add to the current iPod
    play_requested = Signal(list, int)  # PlayItems in view order, index to start at

    def __init__(self, library: Library, manager: workers.DownloadManager):
        super().__init__()
        self.library = library
        self.manager = manager
        self.covers = CoverCache(self)
        self.covers.loaded.connect(self._on_cover)
        self._art_items: dict[str, list[QTableWidgetItem]] = {}
        self._now_path: str | None = None

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
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["#", "Title", "Artist", "Album", "Year", "Added"])
        self.table.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSortingEnabled(True)
        style_track_table(self.table, {0: NUMBER, 1: TITLE, 2: TEXT, 3: MUTED, 4: NUMBER, 5: MUTED},
                          {0: 48, 4: 64, 5: 96}, weights={1: 5, 2: 3, 3: 3})
        self.table.currentCellChanged.connect(lambda row, *_: self._show_selected(row))
        open_btn = QPushButton("Open library folder")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.root))))
        delete_btn = QPushButton("Delete selected songs")
        delete_btn.clicked.connect(self._delete_selected)
        self.sync_btn = QPushButton("Sync selected to iPod")
        self.sync_btn.setToolTip("Add the selected songs to the iPod without removing anything")
        self.sync_btn.clicked.connect(self._sync_selected)
        self.table.itemSelectionChanged.connect(
            lambda: self.sync_btn.setEnabled(bool(self.table.selectedIndexes())))
        self.sync_btn.setEnabled(False)
        self.table.doubleClicked.connect(lambda index: self._play_from(index.row()))
        for label, slot in (("Play", lambda: self._play_from(self.table.currentRow())),
                            ("Sync to iPod", self._sync_selected), ("Delete from library…", self._delete_selected)):
            action = QAction(label, self.table)
            action.triggered.connect(slot)
            self.table.addAction(action)
        self.summary = QLabel()
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.filter)
        rv.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(self.summary, 1)
        row.addWidget(open_btn)
        row.addWidget(self.sync_btn)
        row.addWidget(delete_btn)
        rv.addLayout(row)

        self.art = ArtPanel(self.covers)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.addWidget(self.art)
        split.setSizes([240, 640, 250])
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
        self._art_items = {}
        for row, t in enumerate(tracks):
            num = QTableWidgetItem()
            num.setData(0, t.track_number or None)
            num.setData(256, t.video_id)
            self.table.setItem(row, 0, num)
            for col, text in enumerate([t.title, t.artist, t.album, t.year], start=1):
                self.table.setItem(row, col, QTableWidgetItem(text))
            when = QDateTime.fromSecsSinceEpoch(int(t.added_at))
            added = SortKeyItem(QLocale.system().toString(when.date(), QLocale.ShortFormat))
            added.setData(Qt.UserRole, t.added_at)
            added.setToolTip(QLocale.system().toString(when, QLocale.LongFormat))
            self.table.setItem(row, 5, added)
            key = album_key(t.album_artist, t.album)
            title = self.table.item(row, 1)
            title.setData(ART_KEY, key)
            title.setData(ART_PATH, str(self.library.root / t.relpath))
            title.setIcon(QIcon(self.covers.thumb(key)))
            self._art_items.setdefault(key, []).append(title)
            self.covers.request(key, self.library.root / t.relpath)
        self.table.setSortingEnabled(pid == ALL)
        self._mark_now_playing()
        self._show_selected(self.table.currentRow())
        minutes = sum(t.duration for t in tracks) // 60
        self.summary.setText(f"{len(tracks)} songs · {minutes // 60} h {minutes % 60} min")
        self._apply_filter(self.filter.text())

    def _on_cover(self, key: str) -> None:
        icon = QIcon(self.covers.thumb(key))
        for item in self._art_items.get(key, []):
            item.setIcon(icon)

    def _row_path(self, row: int) -> str | None:
        title = self.table.item(row, 1)
        return title.data(ART_PATH) if title is not None else None

    def _show_selected(self, row: int) -> None:
        if row < 0 and self._now_path:  # nothing selected: show what's playing
            row = self._now_playing_row()
        title = self.table.item(row, 1) if row >= 0 else None
        if title is None:
            self.art.show_track(None)
            return
        self.art.show_track(title.data(ART_KEY), title.text(), self.table.item(row, 2).text(),
                            self.table.item(row, 3).text(), Path(title.data(ART_PATH)))

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold()
        for row in range(self.table.rowCount()):
            hay = " ".join(self.table.item(row, c).text() for c in (1, 2, 3)).casefold()
            self.table.setRowHidden(row, bool(needle) and needle not in hay)

    def _play_from(self, row: int) -> None:
        """Queue every visible song in the order shown, starting at ``row``."""
        from .player import PlayItem

        items, start = [], 0
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            track = self.library.track(self.table.item(r, 0).data(256))
            if track is None:
                continue
            if r == row:
                start = len(items)
            items.append(PlayItem(self.library.root / track.relpath, track.title, track.artist, track.album))
        if items and row >= 0:
            self.play_requested.emit(items, start)

    # ── Now playing ──────────────────────────────────────────────────────

    def set_now_playing(self, path) -> None:
        self._now_path = str(path) if path else None
        self._mark_now_playing()
        if self.table.currentRow() < 0 or not self.table.selectedIndexes():
            self._show_selected(-1)

    def _mark_now_playing(self) -> None:
        accent = self.palette().color(QPalette.Link)
        for row in range(self.table.rowCount()):
            playing = self._now_path is not None and self._row_path(row) == self._now_path
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is None:
                    continue
                font = item.font()
                font.setBold(playing)
                item.setFont(font)
                item.setData(Qt.ForegroundRole, accent if playing else None)

    def _now_playing_row(self) -> int:
        return next((r for r in range(self.table.rowCount()) if self._row_path(r) == self._now_path), -1)

    def _sync_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        paths = []
        for row in rows:
            track = self.library.track(self.table.item(row, 0).data(256))
            if track is not None:
                paths.append(self.library.root / track.relpath)
        if paths:
            self.sync_requested.emit(paths)

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
        # Private playlists only resolve with the account they were downloaded from.
        profile = playlist.profile or None
        if playlist.url:
            self.manager.enqueue_url(playlist.url, profile)
        else:
            self.manager.enqueue_playlist(pid, playlist.title, profile)

    def _remove_playlist(self) -> None:
        pid = self._selected_list()
        if pid != ALL and QMessageBox.question(
                self, "Remove playlist", "Remove this playlist? Its songs stay in your library.") == QMessageBox.Yes:
            self.library.delete_playlist(pid)
            self.refresh()
