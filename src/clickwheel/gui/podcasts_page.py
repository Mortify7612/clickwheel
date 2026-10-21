"""Podcasts tab: subscriptions (YouTube Music and RSS), episodes, downloads.

Podcast and music video downloads share one background queue (``MediaJobs``):
both are slow and go through yt-dlp.
"""

from __future__ import annotations

import queue
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout,
    QWidget,
)

from .. import auth
from ..library import LibraryTrack
from ..podcasts import Episode, Podcasts
from ..video import MusicVideos
from . import workers
from .ribbon import SectionLabel
from .table_style import MUTED, NUMBER, TEXT, TITLE, style_track_table

EPISODE_ID = 256
REFRESH_EVERY_S = 6 * 3600


class MediaJobs(QObject):
    """Serial background queue for podcast and music video work."""

    changed = Signal()       # podcasts or videos in the library changed
    videos_changed = Signal()  # a batch of music videos finished
    status = Signal(str)     # what it's doing, for the status bar and LCD
    busy = Signal(bool)
    failed = Signal(str)

    def __init__(self, podcasts: Podcasts, videos: MusicVideos):
        super().__init__()
        self.podcasts = podcasts
        self.videos = videos
        self._queue: queue.Queue[tuple[str, Callable[[], None]]] = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, label: str, fn: Callable[[], None]) -> None:
        self._queue.put((label, fn))

    def _loop(self) -> None:
        while True:
            label, fn = self._queue.get()
            self.busy.emit(True)
            self.status.emit(label)
            try:
                fn()
            except Exception as exc:
                traceback.print_exc()
                self.failed.emit(f"{label}: {exc}")
            finally:
                self.changed.emit()
                if self._queue.empty():
                    self.busy.emit(False)
                    self.status.emit("Ready")

    # -- podcasts --------------------------------------------------------------------

    def _download(self, eid: str) -> None:
        episode = self.podcasts.episode(eid)
        self.status.emit(f"Downloading “{episode.title}”")
        with tempfile.TemporaryDirectory(prefix="clickwheel-podcast-") as tmp:
            self.podcasts.download(eid, Path(tmp), cookies=auth.cookies_file(),
                                   on_progress=lambda p: self.status.emit(f"Downloading “{episode.title}” {p:.0%}"))

    def _download_new(self, pid: str) -> None:
        for episode in self.podcasts.to_download(pid):
            self._download(episode.id)
            self.changed.emit()

    def subscribe(self, text: str) -> None:
        def job():
            podcast = self.podcasts.subscribe(text, auth.client())
            self.changed.emit()
            self._download_new(podcast.id)
        self.submit("Adding podcast", job)

    def refresh(self, pid: str | None = None) -> None:
        """Re-read one show (or all) and download its newest episodes."""
        def job():
            for podcast in [self.podcasts.podcast(pid)] if pid else self.podcasts.podcasts():
                self.status.emit(f"Checking “{podcast.title}” for new episodes")
                try:
                    self.podcasts.refresh(podcast.id, auth.client())
                except Exception as exc:  # one broken feed shouldn't stop the others
                    self.failed.emit(f"{podcast.title}: {exc}")
                    continue
                self.changed.emit()
                self._download_new(podcast.id)
        self.submit("Checking podcasts", job)

    def download(self, eids: list[str]) -> None:
        def job():
            for eid in eids:
                self._download(eid)
                self.changed.emit()
        self.submit("Downloading episodes", job)

    def import_from_youtube_music(self) -> None:
        def job():
            if not auth.is_signed_in():
                raise RuntimeError("Sign in on the YouTube Music tab first")
            saved = auth.client().get_library_podcasts(limit=None)
            for item in saved:
                browse = item.get("browseId") or ""
                if not browse.startswith("MPSP"):
                    continue
                self.status.emit(f"Adding “{item.get('title', 'podcast')}”")
                podcast = self.podcasts.subscribe(browse, auth.client())
                self.changed.emit()
                self._download_new(podcast.id)
        self.submit("Importing your YouTube Music podcasts", job)

    # -- music videos -------------------------------------------------------------------

    def fetch_videos(self, tracks: list[LibraryTrack]) -> None:
        def job():
            found = missing = 0
            yt = auth.client()
            with tempfile.TemporaryDirectory(prefix="clickwheel-video-") as tmp:
                for i, track in enumerate(tracks, 1):
                    self.status.emit(f"Music video {i}/{len(tracks)}: {track.artist} - {track.title}")
                    def progress(p: float, title=track.title) -> None:
                        self.status.emit(f"Downloading the video for {title} {p:.0%}")

                    video = self.videos.fetch(yt, track, Path(tmp), cookies=auth.cookies_file(),
                                              on_progress=progress)
                    found += video is not None
                    missing += video is None
                    self.changed.emit()
            self.status.emit(f"Music videos: {found} ready" + (f", {missing} songs have none" if missing else ""))
            self.videos_changed.emit()
        self.submit("Getting music videos", job)


class AddPodcastDialog(QDialog):
    """Paste a feed or YouTube Music link, or search YouTube Music's podcasts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add podcast")
        self.resize(560, 420)
        self.link = QLineEdit()
        self.link.setPlaceholderText("RSS feed URL, or a YouTube Music podcast link")
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search YouTube Music podcasts…")
        self.query.returnPressed.connect(self._search)
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._search)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(lambda _: self.accept())
        self.results.currentItemChanged.connect(lambda item, _: item and self.link.setText(item.data(256)))
        self.note = QLabel()
        self.note.setStyleSheet("color: palette(placeholder-text);")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Subscribe")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        search_row = QHBoxLayout()
        search_row.addWidget(self.query, 1)
        search_row.addWidget(search_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Feed or link"))
        layout.addWidget(self.link)
        layout.addSpacing(8)
        layout.addLayout(search_row)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.note)
        layout.addWidget(buttons)

    def _search(self) -> None:
        text = self.query.text().strip()
        if not text:
            return
        self.note.setText("Searching…")
        self.results.clear()

        def search():
            return auth.client().search(text, filter="podcasts", limit=20)

        def done(found):
            self.note.setText("" if found else "No podcasts found")
            for r in found:
                if not (r.get("browseId") or "").startswith("MPSP"):
                    continue
                author = r.get("author")
                author = author.get("name") if isinstance(author, dict) else author
                item = QListWidgetItem(r.get("title", "") + (f" — {author}" if author else ""))
                item.setData(256, r["browseId"])
                self.results.addItem(item)

        workers.run(search, on_done=done, on_error=lambda m: self.note.setText(f"Search failed: {m}"))


def _date(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(timestamp)) if timestamp else ""


def _status(e: Episode) -> str:
    if e.played:
        return "Played"
    if not e.downloaded:
        return ""
    return f"{e.position // 60000} min in" if e.position >= 60000 else "Downloaded"


def _length(seconds: int) -> str:
    if not seconds:
        return ""
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


class PodcastsPage(QWidget):
    play_requested = Signal(list, int, int)  # PlayItems, index to start at, position ms

    def __init__(self, podcasts: Podcasts, jobs: MediaJobs):
        super().__init__()
        self.podcasts = podcasts
        self.jobs = jobs

        add_btn = QPushButton("Add podcast…")
        add_btn.clicked.connect(self._add)
        import_btn = QPushButton("Import from YouTube Music")
        import_btn.setToolTip("Subscribe to the podcasts saved in your YouTube Music library")
        import_btn.clicked.connect(jobs.import_from_youtube_music)
        refresh_btn = QPushButton("Check for new episodes")
        refresh_btn.clicked.connect(lambda: jobs.refresh())
        self.shows = QListWidget()
        self.shows.currentItemChanged.connect(lambda *_: self._show_episodes())
        self.keep = QSpinBox()
        self.keep.setRange(0, 50)
        self.keep.setSuffix(" episodes")
        self.keep.setToolTip("How many of the newest episodes to download automatically")
        self.keep.valueChanged.connect(self._set_keep)
        keep_row = QHBoxLayout()
        keep_row.addWidget(QLabel("Download newest"))
        keep_row.addWidget(self.keep)
        unsubscribe_btn = QPushButton("Unsubscribe…")
        unsubscribe_btn.clicked.connect(self._unsubscribe)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(SectionLabel("<b>Shows</b>"))
        lv.addWidget(self.shows, 1)
        lv.addLayout(keep_row)
        lv.addWidget(add_btn)
        lv.addWidget(import_btn)
        lv.addWidget(refresh_btn)
        lv.addWidget(unsubscribe_btn)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Episode", "Length", "Status"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        style_track_table(self.table, {0: MUTED, 1: TITLE, 2: NUMBER, 3: TEXT}, {0: 96, 2: 72, 3: 150},
                          weights={1: 6})
        self.table.currentCellChanged.connect(lambda row, *_: self._show_notes(row))
        self.table.doubleClicked.connect(lambda index: self._play(index.row()))
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(lambda: self._play(self.table.currentRow()))
        self.download_btn = QPushButton("Download")
        self.download_btn.clicked.connect(self._download)
        self.played_btn = QPushButton("Mark played")
        self.played_btn.clicked.connect(self._toggle_played)
        self.remove_btn = QPushButton("Delete download")
        self.remove_btn.clicked.connect(self._delete_download)
        self.summary = QLabel()
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        self.problem.setStyleSheet("color: #c0392b;")
        buttons = QHBoxLayout()
        buttons.addWidget(self.summary, 1)
        for b in (self.play_btn, self.download_btn, self.played_btn, self.remove_btn):
            buttons.addWidget(b)
        middle = QWidget()
        mv = QVBoxLayout(middle)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addWidget(self.table, 1)
        mv.addWidget(self.problem)
        mv.addLayout(buttons)

        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setMinimumSize(200, 200)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.cover)
        rv.addWidget(self.notes, 1)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(middle)
        split.addWidget(right)
        split.setSizes([240, 640, 280])
        QVBoxLayout(self).addWidget(split)

        self.table.itemSelectionChanged.connect(self._update_buttons)
        jobs.changed.connect(self.refresh)
        # Checks run in the background on a timer, so a failure is noted here, not popped up.
        jobs.failed.connect(lambda m: self.problem.setText(f"⚠ {m.splitlines()[0][:200]}"))
        self.refresh()
        self._update_buttons()
        # Keep shows current while the app is open; the first check shortly after starting.
        self._timer = QTimer(self, interval=REFRESH_EVERY_S * 1000, timeout=lambda: jobs.refresh())
        self._timer.start()
        if self.podcasts.podcasts():
            QTimer.singleShot(15000, lambda: jobs.refresh())

    # ── Shows ────────────────────────────────────────────────────────────

    def _current_show(self) -> str | None:
        item = self.shows.currentItem()
        return item.data(256) if item else None

    def refresh(self) -> None:
        current = self._current_show()
        self.shows.blockSignals(True)
        self.shows.clear()
        for p in self.podcasts.podcasts():
            episodes = self.podcasts.episodes(p.id)
            new = sum(1 for e in episodes if e.downloaded and not e.played)
            item = QListWidgetItem(p.title + (f"  ({new})" if new else ""))
            item.setData(256, p.id)
            item.setToolTip(p.author)
            if cover := self.podcasts.cover(p):
                pixmap = QPixmap()
                if pixmap.loadFromData(cover):
                    item.setIcon(QIcon(pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.shows.addItem(item)
            if p.id == current:
                self.shows.setCurrentItem(item)
        if self.shows.currentItem() is None and self.shows.count():
            self.shows.setCurrentRow(0)
        self.shows.blockSignals(False)
        self._show_episodes()

    def _add(self) -> None:
        self.problem.clear()
        dialog = AddPodcastDialog(self)
        if dialog.exec() and dialog.link.text().strip():
            self.jobs.subscribe(dialog.link.text().strip())

    def _set_keep(self, value: int) -> None:
        if pid := self._current_show():
            self.podcasts.set_keep(pid, value)

    def _unsubscribe(self) -> None:
        pid = self._current_show()
        podcast = self.podcasts.podcast(pid) if pid else None
        if podcast and QMessageBox.question(
                self, "Unsubscribe", f"Unsubscribe from “{podcast.title}” and delete its downloaded episodes?"
                ) == QMessageBox.Yes:
            self.podcasts.unsubscribe(pid)
            self.refresh()

    # ── Episodes ─────────────────────────────────────────────────────────

    def _episodes(self) -> list[Episode]:
        pid = self._current_show()
        return self.podcasts.episodes(pid) if pid else []

    def _show_episodes(self) -> None:
        pid = self._current_show()
        podcast = self.podcasts.podcast(pid) if pid else None
        self.keep.blockSignals(True)
        self.keep.setValue(podcast.keep if podcast else 0)
        self.keep.blockSignals(False)
        selected = {self.table.item(r, 0).data(EPISODE_ID) for r in self._rows()}
        episodes = self._episodes()
        self.table.setRowCount(len(episodes))
        for row, e in enumerate(episodes):
            for col, text in enumerate([_date(e.published), e.title, _length(e.duration), _status(e)]):
                cell = QTableWidgetItem(text)
                if col == 0:
                    cell.setData(EPISODE_ID, e.id)
                if col == 1 and e.video:
                    cell.setText("🎬 " + text)
                self.table.setItem(row, col, cell)
            if e.id in selected:
                self.table.selectRow(row)
        downloaded = sum(1 for e in episodes if e.downloaded)
        self.summary.setText(f"{len(episodes)} episodes · {downloaded} downloaded" if podcast else
                             "Add a podcast to get started")
        self._show_notes(self.table.currentRow())
        self._update_buttons()

    def _rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _selected(self) -> list[Episode]:
        return [e for r in self._rows() if (e := self.podcasts.episode(self.table.item(r, 0).data(EPISODE_ID)))]

    def _update_buttons(self) -> None:
        chosen = self._selected()
        self.play_btn.setEnabled(any(e.downloaded for e in chosen))
        self.download_btn.setEnabled(any(not e.downloaded for e in chosen))
        self.remove_btn.setEnabled(any(e.downloaded for e in chosen))
        self.played_btn.setEnabled(bool(chosen))
        self.played_btn.setText("Mark unplayed" if chosen and all(e.played for e in chosen) else "Mark played")

    def _show_notes(self, row: int) -> None:
        pid = self._current_show()
        podcast = self.podcasts.podcast(pid) if pid else None
        cover = self.podcasts.cover(podcast) if podcast else None
        pixmap = QPixmap()
        if cover and pixmap.loadFromData(cover):
            self.cover.setPixmap(pixmap.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.cover.setText(podcast.title if podcast else "")
        item = self.table.item(row, 0) if row >= 0 else None
        episode = self.podcasts.episode(item.data(EPISODE_ID)) if item else None
        if episode:
            self.notes.setPlainText(f"{episode.title}\n{_date(episode.published)}\n\n{episode.description}")
        elif podcast:
            self.notes.setPlainText(f"{podcast.title}\n{podcast.author}\n\n{podcast.description}")
        else:
            self.notes.clear()

    def _play(self, row: int) -> None:
        from .player import PlayItem

        episodes = [e for e in self._episodes() if e.downloaded]
        item = self.table.item(row, 0) if row >= 0 else None
        if item is None or not episodes:
            return
        podcast = self.podcasts.podcast(self._current_show())
        start = next((i for i, e in enumerate(episodes) if e.id == item.data(EPISODE_ID)), None)
        if start is None:
            return
        items = [PlayItem(self.podcasts.path(e), e.title, podcast.title, podcast.title) for e in episodes]
        self.play_requested.emit(items, start, episodes[start].position)

    def _download(self) -> None:
        self.jobs.download([e.id for e in self._selected() if not e.downloaded])

    def _toggle_played(self) -> None:
        chosen = self._selected()
        played = not all(e.played for e in chosen)
        for e in chosen:
            self.podcasts.set_played(e.id, played)
        self._show_episodes()

    def _delete_download(self) -> None:
        chosen = [e for e in self._selected() if e.downloaded]
        if chosen and QMessageBox.question(
                self, "Delete downloads", f"Delete {len(chosen)} downloaded episode(s)? "
                "They're also removed from the Zune on its next sync.") == QMessageBox.Yes:
            for e in chosen:
                self.podcasts.delete_download(e.id)
            self.refresh()

    # ── Playback position ────────────────────────────────────────────────

    def note_playback(self, path, position: int, duration: int) -> None:
        """Remember where an episode was left (and that it's done, near the end)."""
        episode = self.podcasts.episode_at(path) if path else None
        if episode is None:
            return
        if duration and position >= duration - 30_000:
            self.podcasts.set_played(episode.id)
        else:
            self.podcasts.set_position(episode.id, position)
        if episode.podcast_id == self._current_show():
            self._show_episodes()
