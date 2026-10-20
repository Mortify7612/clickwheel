"""YouTube Music tab: account, link box, library playlists, download queue."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QClipboard, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import auth
from ..pipeline import Status, TrackEvent
from ..ytm import Collection, PlaylistRef, Resolver, TrackMeta, parse_url
from . import workers
from .table_style import MUTED, SECTION, SECTION_HEIGHT, TEXT, TITLE, style_track_table
from .login import LoginDialog
from .ribbon import SectionLabel

STATUS_COLORS = {Status.DONE: "#27ae60", Status.SKIPPED: "#7f8c8d", Status.FAILED: "#c0392b"}
FINAL = (Status.DONE, Status.SKIPPED, Status.FAILED, Status.CANCELLED)
NOT_QUEUED = "Not queued"


@dataclass(eq=False)  # compared by identity: two sections can look alike
class _Section:
    """One group of rows in the downloads table: a ticked playlist, or a queued job."""

    title: str
    state: str  # loading | preview | waiting | downloading | finished | failed | cancelled
    tracks: list[TrackMeta] = field(default_factory=list)
    statuses: list[tuple[str, str | None, str]] = field(default_factory=list)  # text, colour, tooltip
    collection: Collection | None = None
    job: int | None = None
    ended: set[int] = field(default_factory=set)  # tracks that reached a final status
    note: str = ""    # finished counts, or why it failed

    def set_collection(self, collection: Collection, status: str) -> None:
        self.collection, self.title = collection, collection.title
        self.tracks = list(collection.tracks)
        self.statuses = [(status, None, "")] * len(self.tracks)
        self.ended.clear()

    @property
    def active(self) -> bool:
        return self.state in ("waiting", "downloading")

    def header(self) -> str:
        n = len(self.tracks)
        songs = f"{n} song{'' if n == 1 else 's'}"
        if self.collection and self.collection.skipped:
            songs += f" ({self.collection.skipped} unavailable)"
        detail = {
            "loading": "loading songs…",
            "preview": f"{songs} · ticked, not queued yet",
            "waiting": f"{songs} · waiting" if self.collection else "waiting",
            "downloading": f"{len(self.ended)} / {songs}",
            "finished": self.note,
            "failed": f"couldn't load: {self.note}",
            "cancelled": "cancelled",
        }[self.state]
        return f"{self.title}  ·  {detail}"


class YtmPage(QWidget):
    def __init__(self, manager: workers.DownloadManager, status_bar):
        super().__init__()
        self.manager = manager
        self.status_bar = status_bar
        self._sections: list[_Section] = []
        self._previews: dict[str, _Section] = {}  # ticked playlists, by playlist id
        self._jobs: dict[int, _Section] = {}
        self._pasted_songs: set[int] = set()  # jobs for single-song links, to flag ones already owned

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
        self.url.setPlaceholderText("Paste YouTube Music links (playlist, album or song) to queue them…")
        self.url.setToolTip("Pasting queues straight away; paste several links at once to queue them all")
        self.url.returnPressed.connect(self._add_url)
        self.url.textEdited.connect(self._on_url_edited)
        add = QPushButton("Download")
        add.clicked.connect(lambda: self._add_url())
        url_bar = QHBoxLayout()
        url_bar.addWidget(self.url, 1)
        url_bar.addWidget(add)

        # Playlists
        self.playlists = QListWidget()
        self.playlists.setSelectionMode(QAbstractItemView.NoSelection)
        self.playlists.itemChanged.connect(self._on_playlist_toggled)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.load_playlists)
        self.download_sel = QPushButton("Download checked")
        self.download_sel.clicked.connect(self._download_checked)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(SectionLabel("<b>Your playlists</b>"))
        lv.addWidget(self.playlists, 1)
        row = QHBoxLayout()
        row.addWidget(self.refresh_btn)
        row.addWidget(self.download_sel, 1)
        lv.addLayout(row)

        # Queue
        self.queue_title = SectionLabel("<b>Downloads</b>")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Title", "Artist", "Album", "Status"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        style_track_table(self.table, {0: TITLE, 1: TEXT, 2: MUTED, 3: TEXT}, {3: 190}, weights={0: 4, 1: 3, 2: 3})
        self.overall = QProgressBar()
        self.overall.setFormat("%v / %m")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setToolTip("Stop the current download and empty the queue")
        self.cancel_btn.clicked.connect(self._cancel)
        self.clear_btn = QPushButton("Clear finished")
        self.clear_btn.clicked.connect(self._clear_finished)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.queue_title)
        rv.addLayout(url_bar)  # new links join the queue below
        rv.addWidget(self.table, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(self.overall, 1)
        bottom.addWidget(self.clear_btn)
        bottom.addWidget(self.cancel_btn)
        rv.addLayout(bottom)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([280, 720])

        layout = QVBoxLayout(self)
        layout.addLayout(account_bar)
        layout.addWidget(split, 1)

        manager.queued.connect(self._on_queued)
        manager.resolving.connect(lambda label: self.status_bar.showMessage(f"Looking up {label}…"))
        manager.started.connect(self._on_started)
        manager.track_event.connect(self._on_event)
        manager.finished.connect(self._on_finished)
        manager.error.connect(self._on_error)
        self._render()

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
        self._drop_previews()
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

    # ── Ticked playlists: preview their songs ────────────────────────────

    def _on_playlist_toggled(self, item: QListWidgetItem) -> None:
        ref = item.data(Qt.UserRole)
        if not isinstance(ref, PlaylistRef):
            return
        pid = ref.playlist_id
        if item.checkState() != Qt.Checked:
            section = self._previews.pop(pid, None)
            if section is not None:
                self._sections.remove(section)
                self._render()
            return
        if pid in self._previews:
            return
        section = _Section(ref.title, "loading")
        self._previews[pid] = section
        self._sections.append(section)
        self._render()
        profile = auth.get_profile(self._playlists_for)

        def show(collection: Collection) -> None:
            if self._previews.get(pid) is section:  # still ticked and not queued yet
                section.set_collection(collection, NOT_QUEUED)
                section.state = "preview"
                self._render()

        def failed(message: str) -> None:
            if self._previews.get(pid) is section:
                section.state, section.note = "failed", message.splitlines()[0][:120]
                self._render()

        workers.run(lambda: self.manager.resolver(profile).playlist_collection(pid), on_done=show, on_error=failed)

    def _drop_previews(self) -> None:
        for section in self._previews.values():
            self._sections.remove(section)
        self._previews.clear()
        self._render()

    # ── Queueing ─────────────────────────────────────────────────────────

    def _on_url_edited(self, text: str) -> None:
        """Pasting (keyboard, menu or middle-click) queues the links straight away."""
        clip = QApplication.clipboard()
        pasted = {clip.text().strip(), clip.text(QClipboard.Selection).strip()}
        if any(len(c) > 1 and c in text for c in pasted):
            self._add_url()

    def _add_url(self) -> None:
        """Queue every link in the box (separated by spaces or new lines)."""
        words = self.url.text().split()
        if not words:
            return
        links, bad, owned = [], [], []
        for word in words:
            try:
                kind, ident = parse_url(word)
            except ValueError:
                bad.append(word)
                continue
            track = self._owned(ident) if kind == "track" else None
            if track is not None:
                owned.append(f"{track.artist} – {track.title}" if track.artist else track.title)
            elif word not in [link for link, _kind in links]:
                links.append((word, kind))
        if not links and not owned:
            self.status_bar.showMessage("That doesn't look like a YouTube or YouTube Music link.", 8000)
            return
        for link, kind in links:
            job = self.manager.enqueue_url(link)
            if kind == "track":
                self._pasted_songs.add(job)
        # Keep whatever wasn't a link, so it can be fixed.
        self.url.setText(" ".join(bad))
        parts = [f"Queued {len(links)} link{'' if len(links) == 1 else 's'}"] if links else []
        if owned:
            parts.append(f"{len(owned)} already in your library")
        if bad:
            parts.append(f"{len(bad)} not recognised")
        self.status_bar.showMessage("; ".join(parts), 5000)
        if owned:
            self._alert_owned(owned)

    def _owned(self, video_id: str):
        """The library's copy of a song (also matching the video it was swapped from), if any."""
        library = self.manager.library
        found = library.resolve_id(video_id)
        return library.track(found) if found else None

    def _alert_owned(self, songs: list[str]) -> None:
        shown = songs[:8] + ([f"…and {len(songs) - 8} more"] if len(songs) > 8 else [])
        one = len(songs) == 1
        QMessageBox.information(
            self, "Already in your library",
            ("This song is" if one else "These songs are") + " already in your library, so "
            + ("it wasn't" if one else "they weren't") + " downloaded again:\n\n" + "\n".join(shown))

    def _download_checked(self) -> None:
        n = 0
        for i in range(self.playlists.count()):
            item = self.playlists.item(i)
            if item.checkState() != Qt.Checked:
                continue
            ref = item.data(Qt.UserRole)
            section = self._previews.pop(ref.playlist_id, None)
            job = self.manager.new_job()
            section = section or _Section(ref.title, "waiting")
            section.job, section.state = job, "waiting"
            self._place_job(section)
            if section.collection is not None:  # already looked up for the preview
                section.statuses = [(Status.QUEUED.value, None, "")] * len(section.tracks)
                self.manager.enqueue_collection(section.collection, self._playlists_for, job=job)
            else:
                self.manager.enqueue_playlist(ref.playlist_id, ref.title, self._playlists_for, job=job)
            item.setCheckState(Qt.Unchecked)
            n += 1
        self._render()
        self.status_bar.showMessage(f"Queued {n} playlist(s)" if n else "Tick some playlists first", 4000)

    def _cancel(self) -> None:
        self.manager.cancel()
        # The running job reports its own cancellations; the rest never start.
        for section in self._sections:
            if section.state == "waiting":
                section.state = "cancelled"
                section.statuses = [(Status.CANCELLED.value, None, "")] * len(section.tracks)
        self._render()

    def _clear_finished(self) -> None:
        self._sections = [s for s in self._sections if s.job is None or s.active]
        self._jobs = {job: s for job, s in self._jobs.items() if s in self._sections}
        self._render()

    # ── Progress ─────────────────────────────────────────────────────────

    def _on_queued(self, job: int, label: str) -> None:
        if job not in self._jobs:  # queued elsewhere (links, the Library tab's playlist updates)
            self._place_job(_Section(label, "waiting", job=job))
            self._render()

    def _place_job(self, section: _Section) -> None:
        """List jobs in the order they'll run, above the ticked-playlist previews."""
        if section in self._sections:
            self._sections.remove(section)
        previews = [i for i, s in enumerate(self._sections) if s.job is None]
        self._sections.insert(previews[0] if previews else len(self._sections), section)
        self._jobs[section.job] = section

    def _on_started(self, job: int, collection: Collection) -> None:
        section = self._jobs.get(job)
        if section is None:
            return
        section.set_collection(collection, Status.QUEUED.value)
        section.state = "downloading"
        self._render()

    def _on_event(self, job: int, ev: TrackEvent) -> None:
        section = self._jobs.get(job)
        if section is None or ev.index >= len(section.tracks):
            return
        text = ev.status.value
        if ev.status == Status.DOWNLOADING and ev.progress:
            text = f"Downloading {ev.progress:.0%}"
        if ev.status == Status.FAILED:
            text = f"Failed: {ev.error.splitlines()[0][:120]}"
        if ev.status in FINAL:
            section.ended.add(ev.index)
        section.statuses[ev.index] = (text, STATUS_COLORS.get(ev.status), ev.error)
        row = self._first_row(section)
        if row is None:
            return
        self._set_status(row + 1 + ev.index, section.statuses[ev.index])
        self.table.item(row, 0).setText(section.header())
        self._update_progress()

    def _on_finished(self, job: int, collection: Collection, counts) -> None:
        parts = [f"{n} {status.value.lower()}" for status, n in counts.items()]
        self.status_bar.showMessage(f"{collection.title}: " + ", ".join(parts), 15000)
        section = self._jobs.get(job)
        if section is not None:
            section.state, section.note = "finished", ", ".join(parts) or "nothing to do"
            self._render()
        # A pasted song can turn out to be owned only once looked up (e.g. a music video
        # whose album version is in the library).
        if job in self._pasted_songs:
            self._pasted_songs.discard(job)
            if counts and set(counts) == {Status.SKIPPED}:
                self._alert_owned([collection.title])

    def _on_error(self, job: int, what: str, message: str) -> None:
        self._pasted_songs.discard(job)
        self.status_bar.showMessage(f"{what}: {message}", 15000)
        section = self._jobs.get(job)
        if section is not None:
            section.state, section.note = "failed", message.splitlines()[0][:120] if message else "error"
            self._render()

    # ── Table ────────────────────────────────────────────────────────────

    def _first_row(self, section: _Section) -> int | None:
        row = 0
        for s in self._sections:
            if s is section:
                return row
            row += 1 + len(s.tracks)
        return None

    def _set_status(self, row: int, status: tuple[str, str | None, str]) -> None:
        text, color, tip = status
        item = QTableWidgetItem(text)
        if color:
            item.setForeground(QColor(color))
        if tip:
            item.setToolTip(tip)
        self.table.setItem(row, 3, item)

    def _render(self) -> None:
        """Rebuild the table from the sections: a header row, then each song."""
        table = self.table
        scroll = table.verticalScrollBar().value()
        table.clearSpans()
        table.setRowCount(sum(1 + len(s.tracks) for s in self._sections))
        row = 0
        for section in self._sections:
            header = QTableWidgetItem(section.header())
            header.setData(SECTION, True)
            header.setFlags(Qt.ItemIsEnabled)
            table.setItem(row, 0, header)
            for col in (1, 2, 3):
                table.setItem(row, col, None)
            table.setSpan(row, 0, 1, table.columnCount())
            table.setRowHeight(row, SECTION_HEIGHT)
            row += 1
            for meta, status in zip(section.tracks, section.statuses):
                for col, text in enumerate([meta.title, meta.artist, meta.album]):
                    table.setItem(row, col, QTableWidgetItem(text))
                self._set_status(row, status)
                table.setRowHeight(row, table.verticalHeader().defaultSectionSize())
                row += 1
        table.verticalScrollBar().setValue(scroll)
        self.queue_title.setText("<b>Downloads</b>" + (
            "" if self._sections else " — paste links below, or tick playlists to see their songs"))
        self._update_progress()

    def _update_progress(self) -> None:
        """Overall progress across every queued, running and finished job still listed."""
        jobs = [s for s in self._sections if s.job is not None]
        total = sum(len(s.tracks) for s in jobs if s.state != "failed")
        self.overall.setFormat("%v / %m songs" if total else "Nothing queued")
        self.overall.setRange(0, max(1, total))
        self.overall.setValue(sum(len(s.ended) for s in jobs if s.state != "failed"))
        self.clear_btn.setEnabled(any(not s.active for s in jobs))
