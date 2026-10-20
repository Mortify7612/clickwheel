"""YouTube Music tab: account, link box, library playlists, download queue."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import auth
from ..pipeline import Status, TrackEvent
from ..ytm import Collection, Resolver
from . import workers
from .table_style import MUTED, TEXT, TITLE, style_track_table
from .login import LoginDialog

STATUS_COLORS = {Status.DONE: "#27ae60", Status.SKIPPED: "#7f8c8d", Status.FAILED: "#c0392b"}


class YtmPage(QWidget):
    def __init__(self, manager: workers.DownloadManager, status_bar):
        super().__init__()
        self.manager = manager
        self.status_bar = status_bar
        self._rows: dict[tuple[str, int], int] = {}
        self._current: Collection | None = None

        # Account bar: saved profiles
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(260)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_chosen)
        self.add_btn = QPushButton("Add account…")
        self.add_btn.clicked.connect(self._add_account)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setToolTip("Forget this account's saved session on this computer")
        self.remove_btn.clicked.connect(self._remove_account)
        self.account = QLabel()
        self.account.setStyleSheet("color: palette(placeholder-text);")
        account_bar = QHBoxLayout()
        account_bar.addWidget(QLabel("Account"))
        account_bar.addWidget(self.profile_combo)
        account_bar.addWidget(self.add_btn)
        account_bar.addWidget(self.remove_btn)
        account_bar.addWidget(self.account, 1)
        self._playlists_for: str | None = None

        # Link box
        self.url = QLineEdit()
        self.url.setPlaceholderText("Paste a YouTube Music playlist, album or song link…")
        self.url.returnPressed.connect(self._add_url)
        add = QPushButton("Download")
        add.clicked.connect(self._add_url)
        url_bar = QHBoxLayout()
        url_bar.addWidget(self.url, 1)
        url_bar.addWidget(add)

        # Playlists
        self.playlists = QListWidget()
        self.playlists.setSelectionMode(QAbstractItemView.NoSelection)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.load_playlists)
        self.download_sel = QPushButton("Download checked")
        self.download_sel.clicked.connect(self._download_checked)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>Your playlists</b>"))
        lv.addWidget(self.playlists, 1)
        row = QHBoxLayout()
        row.addWidget(self.refresh_btn)
        row.addWidget(self.download_sel, 1)
        lv.addLayout(row)

        # Queue
        self.queue_title = QLabel("<b>Downloads</b>")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Title", "Artist", "Album", "Status"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        style_track_table(self.table, {0: TITLE, 1: TEXT, 2: MUTED, 3: TEXT}, {3: 190}, weights={0: 4, 1: 3, 2: 3})
        self.overall = QProgressBar()
        self.overall.setFormat("%v / %m")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(manager.cancel)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.queue_title)
        rv.addWidget(self.table, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(self.overall, 1)
        bottom.addWidget(self.cancel_btn)
        rv.addLayout(bottom)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([280, 720])

        layout = QVBoxLayout(self)
        layout.addLayout(account_bar)
        layout.addLayout(url_bar)
        layout.addWidget(split, 1)

        manager.resolving.connect(lambda label: self.status_bar.showMessage(f"Looking up {label}…"))
        manager.started.connect(self._on_started)
        manager.track_event.connect(self._on_event)
        manager.finished.connect(self._on_finished)
        manager.error.connect(lambda what, msg: self.status_bar.showMessage(f"{what}: {msg}", 15000))

        self.refresh_profiles()

    # ── Accounts ─────────────────────────────────────────────────────────

    def refresh_profiles(self) -> None:
        profiles = auth.profiles()
        active = auth.active_profile()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in profiles:
            self.profile_combo.addItem(p.label, p.id)
        if not profiles:
            self.profile_combo.addItem("Not signed in", None)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(active.id if active else None)))
        self.profile_combo.blockSignals(False)
        self.remove_btn.setEnabled(bool(profiles))
        self.refresh_btn.setEnabled(bool(profiles))
        self.account.setText("" if profiles else "Public links still work without an account.")
        self.load_playlists()

    def _on_profile_chosen(self, _index: int) -> None:
        profile_id = self.profile_combo.currentData()
        if profile_id:
            auth.set_active(profile_id)
            self.load_playlists()

    def _add_account(self) -> None:
        dlg = LoginDialog(self)
        if dlg.exec():
            self.status_bar.showMessage(f"Added {dlg.profile_added.label}", 5000)
            self.refresh_profiles()

    def _remove_account(self) -> None:
        profile = auth.get_profile(self.profile_combo.currentData())
        if profile is None:
            return
        if QMessageBox.question(
                self, "Remove account",
                f"Forget {profile.label} on this computer? Downloaded songs stay in your library.") == QMessageBox.Yes:
            auth.remove_profile(profile.id)
            remaining = auth.profiles()
            if remaining:
                auth.set_active(remaining[0].id)
            self.refresh_profiles()

    def load_playlists(self) -> None:
        profile = auth.active_profile()
        self._playlists_for = profile.id if profile else None
        self.playlists.clear()
        if profile is None:
            return
        self.playlists.addItem("Loading…")
        wanted = profile.id

        def show(refs):
            if self._playlists_for == wanted:  # ignore results for an account we've switched away from
                self._show_playlists(refs)

        def failed(message):
            if self._playlists_for == wanted:
                self.playlists.clear()
                self.playlists.addItem("Couldn't load playlists")
                self.account.setText(f"Session problem: {message.splitlines()[0][:120]} — try Add account again")

        self.account.setText("")
        workers.run(lambda: Resolver(auth.client(profile)).library_playlists(), on_done=show, on_error=failed)

    def _show_playlists(self, refs) -> None:
        self.playlists.clear()
        for ref in refs:
            label = ref.title + (f"  ({ref.count})" if ref.count is not None else "")
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, ref)
            self.playlists.addItem(item)

    # ── Queueing ─────────────────────────────────────────────────────────

    def _add_url(self) -> None:
        url = self.url.text().strip()
        if not url:
            return
        try:
            from ..ytm import parse_url

            parse_url(url)
        except ValueError as exc:
            self.status_bar.showMessage(str(exc), 8000)
            return
        self.manager.enqueue_url(url)
        self.url.clear()
        self.status_bar.showMessage("Added to queue", 3000)

    def _download_checked(self) -> None:
        n = 0
        for i in range(self.playlists.count()):
            item = self.playlists.item(i)
            if item.checkState() == Qt.Checked:
                ref = item.data(Qt.UserRole)
                self.manager.enqueue_playlist(ref.playlist_id, ref.title, self._playlists_for)
                item.setCheckState(Qt.Unchecked)
                n += 1
        self.status_bar.showMessage(f"Queued {n} playlist(s)" if n else "Tick some playlists first", 4000)

    # ── Progress ─────────────────────────────────────────────────────────

    def _on_started(self, collection: Collection) -> None:
        self._current = collection
        self._rows.clear()
        self.table.setRowCount(len(collection.tracks))
        for i, meta in enumerate(collection.tracks):
            for col, text in enumerate([meta.title, meta.artist, meta.album, Status.QUEUED.value]):
                self.table.setItem(i, col, QTableWidgetItem(text))
        extra = f" — {collection.skipped} unavailable" if collection.skipped else ""
        self.queue_title.setText(f"<b>{collection.title}</b> ({len(collection.tracks)} songs{extra})")
        self.overall.setRange(0, max(1, len(collection.tracks)))
        self.overall.setValue(0)
        self._finished = 0

    def _on_event(self, ev: TrackEvent) -> None:
        if ev.index >= self.table.rowCount():
            return
        text = ev.status.value
        if ev.status == Status.DOWNLOADING and ev.progress:
            text = f"Downloading {ev.progress:.0%}"
        if ev.status == Status.FAILED:
            text = f"Failed: {ev.error.splitlines()[0][:120]}"
        item = QTableWidgetItem(text)
        if ev.status in STATUS_COLORS:
            item.setForeground(QColor(STATUS_COLORS[ev.status]))
        if ev.error:
            item.setToolTip(ev.error)
        self.table.setItem(ev.index, 3, item)
        if ev.status in (Status.DONE, Status.SKIPPED, Status.FAILED, Status.CANCELLED):
            self._finished += 1
            self.overall.setValue(self._finished)

    def _on_finished(self, collection: Collection, counts) -> None:
        parts = [f"{n} {status.value.lower()}" for status, n in counts.items()]
        self.status_bar.showMessage(f"{collection.title}: " + ", ".join(parts), 15000)
