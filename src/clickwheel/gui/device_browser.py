"""Browse, reorder and delete the songs and playlists already on a device."""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..devices.contents import DeviceContents, DeviceTrack
from ..library import Library
from . import workers
from .artwork import THUMB, ArtPanel, CoverCache, album_key

ALL = -1
ART_KEY, ART_PATH, TRACK_INDEX = 257, 258, 259  # item data roles


def _length(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else ""


class DeleteDialog(QDialog):
    def __init__(self, count: int, in_library: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Delete from iPod")
        text = QLabel(f"Delete {count} song{'s' if count != 1 else ''} from the iPod? "
                      "They're removed from its database and the files are deleted.")
        text.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(text)
        self.also_library = QCheckBox(f"Also delete {in_library} of them from my Clickwheel library")
        if in_library:
            note = QLabel("Songs left in your library come back the next time you sync the entire library.")
            note.setWordWrap(True)
            note.setStyleSheet("color: palette(placeholder-text);")
            layout.addWidget(self.also_library)
            layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.addButton("Delete", QDialogButtonBox.DestructiveRole).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class DeviceBrowser(QWidget):
    editing = Signal(bool)       # an edit is being written to the device
    library_edited = Signal()    # the local library changed as a side effect

    def __init__(self, library: Library | None = None):
        super().__init__()
        self.library = library
        self._contents = DeviceContents([], [])
        self._device = None
        self._backend = None
        self._prefer_rockbox_files = True
        self._busy = False        # a sync (or an edit) is touching the device
        self._view: list[int] = []  # track indices in the order shown
        self._dirty = False       # order changed but not saved
        self.covers = CoverCache(self)
        self.covers.loaded.connect(self._on_cover)
        self._art_items: dict[str, list[QTableWidgetItem]] = {}
        self._list_row = 0
        self._note_after_load = ""  # confirmation to show once the reload finishes

        self.lists = QListWidget()
        self.lists.currentRowChanged.connect(self._on_list_changed)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(lambda: self._confirm_discard() and self.load(self._device,
                                                                                         self._prefer_rockbox_files))
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
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setIconSize(QSize(THUMB, THUMB))
        self.table.verticalHeader().setDefaultSectionSize(THUMB + 6)
        self.table.currentCellChanged.connect(lambda row, *_: self._show_selected(row))
        self.table.itemSelectionChanged.connect(self._update_buttons)
        hh = self.table.horizontalHeader()
        for col in (1, 2, 3):
            hh.setSectionResizeMode(col, QHeaderView.Stretch)

        self.up_btn = QPushButton("Move up")
        self.up_btn.setToolTip("Ctrl+Up")
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton("Move down")
        self.down_btn.setToolTip("Ctrl+Down")
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.save_btn = QPushButton("Save order")
        self.save_btn.clicked.connect(self._save_order)
        self.revert_btn = QPushButton("Revert")
        self.revert_btn.clicked.connect(self._revert)
        self.delete_btn = QPushButton("Delete from iPod…")
        self.delete_btn.setToolTip("Delete key")
        self.delete_btn.clicked.connect(self._delete)
        QShortcut(QKeySequence("Ctrl+Up"), self.table, lambda: self._move(-1))
        QShortcut(QKeySequence("Ctrl+Down"), self.table, lambda: self._move(1))
        QShortcut(QKeySequence.Delete, self.table, self._delete)

        self.summary = QLabel()
        edit_row = QHBoxLayout()
        edit_row.addWidget(self.summary, 1)
        for b in (self.up_btn, self.down_btn, self.save_btn, self.revert_btn, self.delete_btn):
            edit_row.addWidget(b)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.filter)
        rv.addWidget(self.table, 1)
        rv.addLayout(edit_row)

        self.art = ArtPanel(self.covers)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.addWidget(self.art)
        split.setSizes([200, 640, 250])
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)
        self._update_buttons()

    # ── Loading ──────────────────────────────────────────────────────────

    def load(self, device, prefer_rockbox_files: bool = True) -> None:
        self._device = device
        self._prefer_rockbox_files = prefer_rockbox_files
        self._backend = None
        self._dirty = False
        if device is None:
            self._set_contents(DeviceContents([], []), "No device")
            return
        self.summary.setText("Reading device…")
        self.refresh_btn.setEnabled(False)
        try:
            self._backend = device.backend(prefer_rockbox_files)
        except RuntimeError as exc:
            self._set_contents(DeviceContents([], []), str(exc))
            return
        path = device.path

        def done(contents):
            if self._device is not None and self._device.path == path:  # ignore stale loads
                self._set_contents(contents)

        def failed(message):
            self._set_contents(DeviceContents([], []), f"Couldn't read the device: {message}")

        workers.run(self._backend.browse, on_done=done, on_error=failed)

    def set_busy(self, busy: bool) -> None:
        """Called by the iPod tab while a sync is writing to the device."""
        self._busy = busy
        self._update_buttons()

    def _set_contents(self, contents: DeviceContents, note: str = "") -> None:
        self._contents = contents
        self._dirty = False
        note = note or self._note_after_load or contents.notice
        self._note_after_load = ""
        self.covers.clear()  # a different device (or a re-sync) may have different art
        self.refresh_btn.setEnabled(True)
        self.lists.blockSignals(True)
        self.lists.clear()
        label = "Play order" if contents.ordered_library else "All songs"
        everything = QListWidgetItem(f"{label} ({len(contents.tracks)})")
        everything.setData(256, ALL)
        self.lists.addItem(everything)
        for i, p in enumerate(contents.playlists):
            item = QListWidgetItem(f"{p.name} ({len(p.track_indices)})")
            item.setData(256, i)
            self.lists.addItem(item)
        self.lists.setCurrentRow(min(self._list_row, self.lists.count() - 1))
        self.lists.blockSignals(False)
        self._reset_view()
        self._render(note)

    # ── View ─────────────────────────────────────────────────────────────

    def _which(self) -> int:
        item = self.lists.currentItem()
        return item.data(256) if item else ALL

    def _reorderable(self) -> bool:
        return self._which() != ALL or self._contents.ordered_library

    def _reset_view(self) -> None:
        which = self._which()
        if which != ALL:
            self._view = list(self._contents.playlists[which].track_indices)
        elif self._contents.ordered_library:
            self._view = list(range(len(self._contents.tracks)))
        else:
            tracks = self._contents.tracks
            self._view = sorted(range(len(tracks)),
                                key=lambda i: (tracks[i].artist.casefold(), tracks[i].album.casefold(),
                                               tracks[i].track_number))

    def _on_list_changed(self, row: int) -> None:
        if not self._confirm_discard():
            self.lists.blockSignals(True)
            self.lists.setCurrentRow(self._list_row)
            self.lists.blockSignals(False)
            return
        self._list_row = max(row, 0)
        self._dirty = False
        self._reset_view()
        self._render()

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        return QMessageBox.question(self, "Unsaved order",
                                    "Discard the new song order without saving it to the iPod?") == QMessageBox.Yes

    def _render(self, note: str = "", select: list[int] | None = None) -> None:
        tracks = [self._contents.tracks[i] for i in self._view]
        root = self._device.path if self._device is not None else None
        self.table.setSortingEnabled(False)
        self.table.clearSelection()
        self.table.setRowCount(len(tracks))
        self._art_items = {}
        for row, (index, t) in enumerate(zip(self._view, tracks)):
            num = QTableWidgetItem()
            # In an ordered view the first column is the position, not the album track number.
            num.setData(0, (row + 1) if self._reorderable() else (t.track_number or None))
            num.setData(TRACK_INDEX, index)
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
        self.table.setHorizontalHeaderItem(0, QTableWidgetItem("Pos" if self._reorderable() else "#"))
        self.table.setSortingEnabled(not self._reorderable())
        if select:
            for row in select:
                self.table.selectRow(row)
            self.table.setCurrentCell(select[0], 1)
        self._show_selected(self.table.currentRow())
        minutes = sum(t.duration for t in tracks) // 60
        status = note or f"{len(tracks)} songs · {minutes // 60} h {minutes % 60} min"
        if self._dirty:
            status += " · order not saved"
        self.summary.setText(status)
        self._apply_filter(self.filter.text())
        self._update_buttons()

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _selected_tracks(self) -> list[DeviceTrack]:
        return [self._contents.tracks[self.table.item(r, 0).data(TRACK_INDEX)] for r in self._selected_rows()]

    def _update_buttons(self) -> None:
        idle = not self._busy and self._backend is not None
        rows = self._selected_rows()
        can_move = idle and self._reorderable() and bool(rows) and not self.filter.text()
        self.up_btn.setEnabled(can_move and rows[0] > 0)
        self.down_btn.setEnabled(can_move and rows[-1] < self.table.rowCount() - 1)
        self.save_btn.setEnabled(idle and self._dirty)
        self.revert_btn.setEnabled(idle and self._dirty)
        self.delete_btn.setEnabled(idle and bool(rows))
        self.refresh_btn.setEnabled(not self._busy)

    # ── Editing ──────────────────────────────────────────────────────────

    def _move(self, step: int) -> None:
        if not self.up_btn.isEnabled() and step < 0 or not self.down_btn.isEnabled() and step > 0:
            return
        rows = self._selected_rows()
        chosen = set(rows)
        order = list(self._view)
        # Move the whole selection one step, keeping its internal order.
        for r in (rows if step < 0 else reversed(rows)):
            target = r + step
            if 0 <= target < len(order) and target not in chosen:
                order[r], order[target] = order[target], order[r]
                chosen.discard(r)
                chosen.add(target)
        self._view = order
        self._dirty = True
        self._render(select=sorted(chosen))

    def _revert(self) -> None:
        self._dirty = False
        self._reset_view()
        self._render()

    def _start_edit(self, fn, *args, on_done) -> None:
        self._busy = True
        self.editing.emit(True)
        self._update_buttons()
        self.summary.setText("Writing to the iPod…")

        def finished(result):
            self._busy = False
            self.editing.emit(False)
            on_done(result)

        def failed(message):
            self._busy = False
            self.editing.emit(False)
            self._update_buttons()
            QMessageBox.critical(self, "Couldn't change the iPod", message)
            self.load(self._device, self._prefer_rockbox_files)

        workers.run(fn, *args, on_done=finished, on_error=failed)

    def _save_order(self) -> None:
        which = self._which()
        playlist = self._contents.playlists[which] if which != ALL else None
        tracks = [self._contents.tracks[i] for i in self._view]

        def saved(_result):
            note = "Order saved to the iPod"
            if playlist is not None and self._mirror_order(playlist.name, tracks):
                note += f" and to “{playlist.name}” in your library, so syncing keeps it"
            self._note_after_load = note
            self.load(self._device, self._prefer_rockbox_files)

        self._start_edit(self._backend.reorder, playlist.id if playlist else None,
                         [t.location for t in tracks], on_done=saved)

    def _mirror_order(self, name: str, tracks: list[DeviceTrack]) -> bool:
        """Apply a device playlist order to the library playlist it was synced from."""
        if self.library is None:
            return False
        source = next((p for p in self.library.playlists() if p.kind == "playlist" and p.title == name), None)
        if source is None:
            return False
        ids = [m.video_id for t in tracks if (m := self.library.find_track(t.title, t.artist, t.album))]
        self.library.reorder_playlist(source.id, ids)
        self.library_edited.emit()
        return True

    def _delete(self) -> None:
        if not self.delete_btn.isEnabled() or not self._confirm_discard():
            return
        tracks = self._selected_tracks()
        matches = [m for t in tracks if self.library and (m := self.library.find_track(t.title, t.artist, t.album))]
        dlg = DeleteDialog(len(tracks), len(matches), self)
        if not dlg.exec():
            return
        also_library = bool(matches) and dlg.also_library.isChecked()

        def deleted(count):
            if also_library:
                for m in matches:
                    self.library.delete_track(m.video_id)
                self.library_edited.emit()
            self._note_after_load = (f"Deleted {count} song{'s' if count != 1 else ''} from the iPod"
                                     + (" and your library" if also_library else ""))
            self.load(self._device, self._prefer_rockbox_files)

        self._dirty = False
        self._start_edit(self._backend.delete_tracks, {t.location for t in tracks}, on_done=deleted)

    # ── Covers / filter ──────────────────────────────────────────────────

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
        self._update_buttons()
