"""YouTube Music tab: search, your playlists, albums and artists to open, and the download queue.

Browsing is fast: an opened playlist, album or artist is listed straight from
YouTube Music without resolving anything. Songs are only resolved (album
versions, full tags) once they're queued for download.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QClipboard, QColor, QDesktopServices, QIcon, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import auth
from ..pipeline import Status, TrackEvent
from ..ytm import Card, Collection, Listing, Page, PlaylistRef, TrackMeta, parse_url, small_cover
from . import icons, workers
from .artwork import CoverCache, RemoteArt
from .collection_header import CollectionHeader
from .cover_grid import CoverGrid, Tile
from .login import LoginDialog
from .progress_strip import ProgressStrip
from .ribbon import SectionLabel
from .table_style import (
    MUTED, NUMBER, PROGRESS, ROW_HEIGHT, SECTION, SECTION_HEIGHT, TEXT, TITLE, restyle_table, style_track_table,
)
from .theme import current_theme

FINAL = (Status.DONE, Status.SKIPPED, Status.FAILED, Status.CANCELLED)
BUSY = (Status.QUEUED, Status.DOWNLOADING, Status.TAGGING)
FAILED_RED = QColor("#e0533d")  # reads on every skin's song lists, dark or light
KEY, NOTE, NOTE_LIT, ICON = Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3, Qt.UserRole + 4  # sidebar roles
SONG = Qt.UserRole + 5  # on a song row's # cell: the Listing
SEARCH_KINDS = (("songs", "Songs"), ("albums", "Albums"), ("artists", "Artists"), ("playlists", "Playlists"))
NUM, NAME, ARTIST, ALBUM, TIME, STATE = range(6)
# Room for the account menu's arrow (the skins' button padding doesn't leave any; the system style does).
ACCOUNT_QSS = ("QPushButton::menu-indicator { subcontrol-position: right center; right: 6px; }"
               "QPushButton { padding-right: 22px; }")


def song_count(n: int) -> str:
    return f"{n} song" if n == 1 else f"{n} songs"


def length(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else ""


def total_time(seconds: int) -> str:
    minutes = seconds // 60
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


@dataclass(eq=False)  # compared by identity: two sections can look alike
class _Section:
    """One queued job in the downloads list: a heading, then its songs."""

    title: str
    state: str  # waiting | downloading | finished | failed | cancelled
    job: int | None = None
    tracks: list[TrackMeta] = field(default_factory=list)
    statuses: list[tuple[Status, float, str]] = field(default_factory=list)  # status, progress, error
    collection: Collection | None = None
    ended: set[int] = field(default_factory=set)  # tracks that reached a final status
    note: str = ""  # finished counts, or why it failed

    def set_collection(self, collection: Collection) -> None:
        self.collection, self.title = collection, collection.title
        self.tracks = list(collection.tracks)
        self.statuses = [(Status.QUEUED, 0.0, "")] * len(self.tracks)
        self.ended.clear()

    @property
    def active(self) -> bool:
        return self.state in ("waiting", "downloading")

    def header(self) -> str:
        songs = song_count(len(self.tracks))
        if self.collection and self.collection.skipped:
            songs += f" ({self.collection.skipped} unavailable)"
        detail = {
            "waiting": f"{songs} · waiting" if self.collection else "waiting",
            "downloading": f"{len(self.ended)} of {songs}",
            "finished": self.note,
            "failed": f"couldn't download: {self.note}",
            "cancelled": "cancelled",
        }[self.state]
        return f"{self.title}  ·  {detail}"


class _NoteDelegate(QStyledItemDelegate):
    """Sidebar items with a short note at the right edge ("12 new", "✓", "3 of 18")."""

    def paint(self, p, option, index) -> None:
        note = index.data(NOTE)
        if not note:
            super().paint(p, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        metrics = opt.fontMetrics
        room = metrics.horizontalAdvance(note) + 16
        icon = opt.decorationSize.width() + 10 if index.data(Qt.DecorationRole) is not None else 0
        opt.text = metrics.elidedText(opt.text, Qt.ElideRight, max(20, opt.rect.width() - room - icon - 24))
        widget = option.widget
        (widget.style() if widget else QApplication.style()).drawControl(QStyle.CE_ItemViewItem, opt, p, widget)
        selected = bool(option.state & QStyle.State_Selected)
        p.save()
        p.setFont(opt.font)
        p.setPen(opt.palette.color(QPalette.HighlightedText) if selected
                 else opt.palette.color(QPalette.Link) if index.data(NOTE_LIT)
                 else opt.palette.color(QPalette.PlaceholderText))
        p.drawText(opt.rect.adjusted(0, 0, -12, 0), Qt.AlignRight | Qt.AlignVCenter, note)
        p.restore()


class YtmPage(QWidget):
    def __init__(self, manager: workers.DownloadManager, status_bar):
        super().__init__()
        self.manager = manager
        self.library = manager.library
        self.status_bar = status_bar
        self.covers = CoverCache(self)
        self.covers.loaded.connect(self._on_cover)
        self._art_items: dict[str, list[QTableWidgetItem]] = {}
        self._sections: list[_Section] = []
        self._jobs: dict[int, _Section] = {}
        self._page_jobs: dict[str, int] = {}  # page id -> its download job
        self._pasted_songs: set[int] = set()  # jobs for single-song links, to flag ones already owned
        self._live: dict[str, tuple[Status, float]] = {}  # video id -> latest download status
        self._playlist_refs: list[PlaylistRef] = []
        self._missing: dict[str, int] = {}  # playlist id -> songs not yet in the library, once opened
        self._playlists_for: str | None = None
        self._pages: dict[tuple[str, str], Page] = {}  # opened pages, for going back
        self._view: tuple = ("downloads",)
        self._history: list[tuple[tuple, str]] = []  # (view, label) to go back to
        self._page: Page | None = None
        self._query = ""
        self._search_kind = "songs"
        self._results: dict[str, list] = {}  # search results by kind, for the current query
        self._grid_cards: list[Card] = []
        self._queue_art: dict[str, list[QTableWidgetItem]] = {}  # covers in the download queue
        self._shown: tuple[int, int, str] | None = None  # (visible, total, noun) while a filter is typed

        # ── Top bar: search (or paste links) and the account ──
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search YouTube Music, or paste a link to download it")
        self.search.setClearButtonEnabled(True)
        self._search_icon = self.search.addAction(QIcon(), QLineEdit.LeadingPosition)
        self.search.returnPressed.connect(self._submit)
        self.search.textEdited.connect(self._on_search_edited)
        self.account_btn = QPushButton()
        self.account_btn.setAutoDefault(False)
        self.account_menu = QMenu(self.account_btn)
        self.account_btn.clicked.connect(lambda: auth.profiles() or self._add_account())  # (signed out: no menu)
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.account_btn)

        # ── Sidebar ──
        self.nav = QListWidget()
        self.nav.setItemDelegate(_NoteDelegate(self.nav))
        for key, label, icon in (("search", "Search results", "search"), ("downloads", "Downloads", "download")):
            item = QListWidgetItem(label)
            item.setData(KEY, key)
            item.setData(ICON, icon)
            self.nav.addItem(item)
        self.nav.item(0).setHidden(True)  # until something has been searched for
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.itemClicked.connect(self._nav_clicked)
        self.lists = QListWidget()
        self.lists.setItemDelegate(_NoteDelegate(self.lists))
        self.lists.itemClicked.connect(self._list_clicked)
        self.lists_hint = QLabel()
        self.lists_hint.setWordWrap(True)
        self.lists_hint.setStyleSheet("color: palette(placeholder-text); padding: 4px;")
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(SectionLabel("<b>YouTube Music</b>"))
        lv.addWidget(self.nav)
        lv.addSpacing(6)
        lv.addWidget(SectionLabel("<b>Your playlists</b>"))
        lv.addWidget(self.lists, 1)
        lv.addWidget(self.lists_hint)

        # ── Header ──
        self.header = CollectionHeader(self.covers)
        self.header.link_clicked.connect(self._on_link)
        self.get_btn = QPushButton()
        self.get_btn.setDefault(True)  # the skins give the default button their accent
        self.get_btn.setAutoDefault(False)
        self.get_btn.clicked.connect(self._download_page)
        self.more_btn = QPushButton()
        self.more_btn.setToolTip("More")
        self.more_btn.setAutoDefault(False)
        self.more_btn.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0; }")
        more = QMenu(self.more_btn)
        more.addAction("Copy link", lambda: self._page and QApplication.clipboard().setText(self._page.url))
        more.addAction("Open on YouTube Music",
                       lambda: self._page and QDesktopServices.openUrl(QUrl(self._page.url)))
        more.addAction("Reload", self._reload_page)
        self.more_btn.setMenu(more)
        self.cancel_btn = QPushButton("Cancel all")
        self.cancel_btn.setToolTip("Stop the current download and empty the queue")
        self.cancel_btn.setAutoDefault(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.clear_btn = QPushButton("Clear finished")
        self.clear_btn.setAutoDefault(False)
        self.clear_btn.clicked.connect(self._clear_finished)
        for button in (self.get_btn, self.more_btn, self.cancel_btn, self.clear_btn):
            self.header.actions.addWidget(button)
        self.header.actions.addStretch(1)

        # A row of toggle chips: search result kinds, or an artist's releases / top songs.
        self.chips = QWidget()
        self._chip_row = QHBoxLayout(self.chips)
        self._chip_row.setContentsMargins(0, 0, 0, 0)
        self._chip_group = QButtonGroup(self)
        self._chip_group.buttonClicked.connect(lambda b: self._chip_handler(b.property("kind")))
        self._chip_handler = lambda _kind: None

        # Filter, count, download the selection.
        self.filter = QLineEdit()
        self.filter.setClearButtonEnabled(True)
        self.filter.setMaximumWidth(320)
        self._filter_icon = self.filter.addAction(QIcon(), QLineEdit.LeadingPosition)
        self.filter.textChanged.connect(self._apply_filter)
        self.status = QLabel()
        self.status.setStyleSheet("color: palette(placeholder-text);")
        self.get_sel_btn = QPushButton("Download selected")
        self.get_sel_btn.setAutoDefault(False)
        self.get_sel_btn.clicked.connect(self._download_selected)
        self.tools = QWidget()
        tools = QHBoxLayout(self.tools)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.addWidget(self.filter)
        tools.addStretch(1)
        tools.addWidget(self.status)
        tools.addWidget(self.get_sel_btn)

        # ── Content: songs, a wall of covers, the queue, or a message ──
        self.songs = QTableWidget(0, 6)
        self.songs.setHorizontalHeaderLabels(["#", "Title", "Artist", "Album", "Time", "Status"])
        self.songs.verticalHeader().hide()
        self.songs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.songs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.songs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.songs.customContextMenuRequested.connect(self._song_menu)
        self.songs.itemSelectionChanged.connect(self._update_status)
        self._song_columns = style_track_table(
            self.songs, {NUM: NUMBER, NAME: TITLE, ARTIST: TEXT, ALBUM: MUTED, TIME: NUMBER, STATE: MUTED},
            {NUM: 44, TIME: 58, STATE: 150}, weights={NAME: 5, ARTIST: 3, ALBUM: 3})
        self.grid = CoverGrid(self.covers)
        self.grid.opened.connect(self._open_card)
        self.table = QTableWidget(0, 4)  # the download queue
        self.table.setHorizontalHeaderLabels(["Title", "Artist", "Album", "Status"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        style_track_table(self.table, {0: TITLE, 1: TEXT, 2: MUTED, 3: MUTED}, {3: 190}, weights={0: 4, 1: 3, 2: 3})
        self.message = QLabel()
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: palette(placeholder-text); padding: 30px;")
        self.overall = ProgressStrip("%v / %m songs")

        browser = QVBoxLayout()
        browser.setContentsMargins(0, 0, 0, 0)
        browser.addWidget(self.header)
        browser.addWidget(self.chips)
        browser.addWidget(self.tools)
        for widget in (self.songs, self.grid, self.table, self.message):
            browser.addWidget(widget, 1)
        browser.addWidget(self.overall)
        middle = QWidget()
        middle.setLayout(browser)
        self._content = (self.songs, self.grid, self.table, self.message)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(middle)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 900])
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(split, 1)

        manager.queued.connect(self._on_queued)
        manager.resolving.connect(lambda label: self.status_bar.showMessage(f"Looking up {label}…"))
        manager.started.connect(self._on_started)
        manager.track_event.connect(self._on_event)
        manager.finished.connect(self._on_finished)
        manager.error.connect(self._on_error)
        manager.library_changed.connect(self._on_library_changed)
        self.restyle()
        self.refresh_profiles()
        self._show_downloads()

    # ── Theme ────────────────────────────────────────────────────────────

    def restyle(self) -> None:
        """Icons, fonts and table headers for the current theme (call after a theme change)."""
        muted = self.palette().color(QPalette.PlaceholderText)
        for action in (self._search_icon, self._filter_icon):
            action.setIcon(QIcon(icons.pixmap("search", muted, 16)))
        button_text = self.more_btn.palette().color(QPalette.ButtonText)
        self.more_btn.setIcon(icons.icon("more", button_text, size=16))
        self.get_btn.setIcon(icons.icon("download", self.get_btn.palette().color(QPalette.ButtonText), size=14))
        self._paint_sidebar_icons()
        self.account_btn.setStyleSheet(ACCOUNT_QSS if current_theme() != "system" else "")
        self.header.restyle()
        for table in (self.songs, self.table):
            restyle_table(table)
        self._fit_nav()

    def _paint_sidebar_icons(self) -> None:
        for view in (self.nav, self.lists):
            pal = view.palette()
            view.setIconSize(QSize(16, 16))
            for i in range(view.count()):
                item = view.item(i)
                name = item.data(ICON)
                if not name:
                    continue
                icon = QIcon(icons.pixmap(name, pal.color(QPalette.Text), 16))
                icon.addPixmap(icons.pixmap(name, pal.color(QPalette.HighlightedText), 16), QIcon.Selected)
                item.setIcon(icon)

    # ── Accounts ─────────────────────────────────────────────────────────

    def refresh_profiles(self) -> None:
        profiles = auth.profiles()
        active = auth.active_profile()
        menu = self.account_menu
        menu.clear()
        if not profiles:
            self.account_btn.setText("Sign in…")
            self.account_btn.setMenu(None)
        else:
            self.account_btn.setText(active.label if active else profiles[0].label)
            for profile in profiles:
                action = menu.addAction(profile.label, lambda pid=profile.id: self._choose_profile(pid))
                action.setCheckable(True)
                action.setChecked(active is not None and profile.id == active.id)
            menu.addSeparator()
            menu.addAction("Reload playlists", self.load_playlists)
            menu.addAction("Add account…", self._add_account)
            if active is not None:
                menu.addAction(f"Remove {active.label}…", self._remove_account)
            self.account_btn.setMenu(menu)
        self.load_playlists()

    def _choose_profile(self, profile_id: str) -> None:
        auth.set_active(profile_id)
        self.refresh_profiles()

    def _add_account(self) -> None:
        dlg = LoginDialog(self)
        if dlg.exec():
            self.status_bar.showMessage(f"Added {dlg.profile_added.label}", 5000)
            self.refresh_profiles()

    def _remove_account(self) -> None:
        profile = auth.active_profile()
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

    # ── Your playlists ───────────────────────────────────────────────────

    def load_playlists(self) -> None:
        profile = auth.active_profile()
        self._playlists_for = profile.id if profile else None
        self._playlist_refs = []
        self.lists.clear()
        if profile is None:
            self.lists_hint.setText("Sign in (top right) to see your playlists here. "
                                    "Search and public links work without an account.")
            self.lists_hint.show()
            return
        self.lists_hint.setText("Loading your playlists…")
        self.lists_hint.show()
        wanted = profile.id

        def show(refs):
            if self._playlists_for == wanted:  # ignore results for an account we've switched away from
                self._playlist_refs = refs
                self.lists_hint.hide()
                self._show_playlists()

        def failed(message):
            if self._playlists_for == wanted:
                self.lists_hint.setText(f"Couldn't load your playlists ({message.splitlines()[0][:100]}). "
                                        "Try Add account again from the account menu.")

        workers.run(lambda: self.manager.resolver(profile).library_playlists(), on_done=show, on_error=failed)

    def _show_playlists(self) -> None:
        current = self._view[2] if self._view[0] == "page" and self._view[1] == "playlist" else None
        self.lists.clear()
        for ref in self._playlist_refs:
            item = QListWidgetItem(ref.title)
            item.setData(KEY, ref.playlist_id)
            item.setData(ICON, "playlist")
            self.lists.addItem(item)
            if ref.playlist_id == current:
                item.setSelected(True)
        self._paint_sidebar_icons()
        self._update_playlist_notes()

    def _update_playlist_notes(self) -> None:
        """✓ for playlists fully in the library, "N new" where songs are missing."""
        local = {p.id: p for p in self.library.playlists()}
        refs = {r.playlist_id: r for r in self._playlist_refs}
        for i in range(self.lists.count()):
            item = self.lists.item(i)
            pid = item.data(KEY)
            ref, have = refs.get(pid), local.get(pid)
            missing = self._missing.get(pid)
            if missing is None and have is not None and ref is not None and ref.count is not None:
                missing = max(0, ref.count - have.track_count)
            if have is None and missing is None:
                note = ""
            elif missing:
                note = f"{missing} new"
            else:
                note = "✓"
            item.setData(NOTE, note)
            item.setData(NOTE_LIT, bool(missing))
            tip = ("Not downloaded yet" if have is None and not missing
                   else f"{song_count(missing)} not in your library yet" if missing else "In your library")
            item.setToolTip(f"{ref.title if ref else pid}\n{tip}")

    # ── Navigation ───────────────────────────────────────────────────────

    def _nav_clicked(self, item: QListWidgetItem) -> None:
        self._history.clear()
        if item.data(KEY) == "downloads":
            self._show_downloads()
        else:
            self._show_search(self._query)

    def _list_clicked(self, item: QListWidgetItem) -> None:
        self._history.clear()
        self._open("playlist", item.data(KEY), item.text())

    def _select_sidebar(self, nav_key: str | None, list_key: str | None) -> None:
        for view, key in ((self.nav, nav_key), (self.lists, list_key)):
            view.blockSignals(True)
            view.clearSelection()
            match = next((view.item(i) for i in range(view.count()) if view.item(i).data(KEY) == key), None)
            if match is not None:
                view.setCurrentItem(match)
                match.setSelected(True)
            view.blockSignals(False)

    def _set_chips(self, options, current: str, handler) -> None:
        for chip in self._chip_group.buttons():
            self._chip_group.removeButton(chip)
            chip.deleteLater()
        while self._chip_row.count():
            self._chip_row.takeAt(0)
        for key, label in options:
            chip = QPushButton(label)
            chip.setCheckable(True)
            chip.setAutoDefault(False)
            chip.setProperty("kind", key)
            chip.setChecked(key == current)
            self._chip_group.addButton(chip)
            self._chip_row.addWidget(chip)
        self._chip_row.addStretch(1)
        self._chip_handler = handler
        self.chips.show()

    def _fit_nav(self) -> None:
        """The Search results / Downloads box is exactly as tall as its visible rows."""
        rows = [i for i in range(self.nav.count()) if not self.nav.item(i).isHidden()]
        height = sum(self.nav.sizeHintForRow(i) for i in rows) + 2 * self.nav.frameWidth() + 8
        self.nav.setFixedHeight(height)

    def _show_only(self, *widgets) -> None:
        for widget in self._content:
            widget.setVisible(widget in widgets)

    def _back_link(self) -> str:
        if not self._history:
            return ""
        label = self._history[-1][1]
        return f'<a href="back" style="text-decoration: none;">‹ {label}</a>'

    def _remember(self, label: str) -> None:
        """Note the current view as the place to come back to."""
        self._history.append((self._view, label))

    def _current_label(self) -> str:
        kind = self._view[0]
        if kind == "search":
            return "Search results"
        if kind == "page" and self._page is not None:
            return self._page.title
        return "Downloads"

    def _on_link(self, href: str) -> None:
        if href != "back" or not self._history:
            return
        view, _label = self._history.pop()
        if view[0] == "search":
            self._show_search(view[1])
        elif view[0] == "page":
            self._open(view[1], view[2], "", remember=False)
        else:
            self._show_downloads()

    def _clear_filter(self) -> None:
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.blockSignals(False)

    # ── Search, and pasting links ────────────────────────────────────────

    def _on_search_edited(self, text: str) -> None:
        """Pasting a link (keyboard, menu or middle-click) queues it straight away."""
        clip = QApplication.clipboard()
        pasted = {clip.text().strip(), clip.text(QClipboard.Selection).strip()}
        if any(len(c) > 1 and c in text for c in pasted) and self._links_only(text):
            self._queue_links()

    @staticmethod
    def _links_only(text: str) -> bool:
        """Whether every word is a YouTube link (anything else in the box is a search)."""
        words = text.split()
        if not words or not all("youtube.com" in w or "youtu.be" in w for w in words):
            return False
        try:
            return all(parse_url(w) for w in words)
        except ValueError:
            return False

    def _submit(self) -> None:
        text = self.search.text().strip()
        if not text:
            return
        if self._links_only(text):
            self._queue_links()
            return
        self._history.clear()
        self._show_search(text)

    def _show_search(self, query: str) -> None:
        if not query:
            self._show_downloads()
            return
        if query != self._query:
            self._query, self._results = query, {}
        self._view, self._page = ("search", query), None
        self.nav.item(0).setHidden(False)
        self._fit_nav()
        self._select_sidebar("search", None)
        self.header.show_collection(kind="Search", title=f"“{query}”", playable=False)
        self.header.back.hide()
        self._set_header_buttons()
        self._set_chips(SEARCH_KINDS, self._search_kind, self._show_search_kind)
        self._show_search_kind(self._search_kind)

    def _show_search_kind(self, kind: str) -> None:
        self._search_kind = kind
        for chip in self._chip_group.buttons():
            chip.setChecked(chip.property("kind") == kind)
        self._clear_filter()
        results = self._results.get(kind)
        if results is None:
            self.tools.hide()
            self.message.setText("Searching…")
            self._show_only(self.message)
            query = self._query
            profile = auth.active_profile()

            def done(found):
                self._results[kind] = found
                if self._view == ("search", query) and self._search_kind == kind:
                    self._show_search_kind(kind)

            def failed(message):
                if self._view == ("search", query) and self._search_kind == kind:
                    self.message.setText(f"Couldn't search YouTube Music: {message.splitlines()[0][:160]}")

            workers.run(lambda: self.manager.resolver(profile).search(query, kind), on_done=done, on_error=failed)
            return
        if not results:
            self.tools.hide()
            self.message.setText(f"No {kind} found for “{self._query}”.")
            self._show_only(self.message)
            return
        self.tools.show()
        if kind == "songs":
            self._fill_songs(results, numbered=False)
            self._show_only(self.songs)
        else:
            self._fill_grid(results, round_covers=kind == "artists")
            self._show_only(self.grid)
        self._apply_filter("")

    # ── Opening playlists, albums and artists ────────────────────────────

    def _open_card(self, key: str) -> None:
        kind, ident = key.split(":", 1)
        card = next((c for c in self._grid_cards if f"{c.kind}:{c.id}" == key), None)
        self._open(kind, ident, card.title if card else "")

    def _open(self, kind: str, ident: str, title: str, remember: bool = True) -> None:
        if remember and self._view[0] in ("search", "page"):
            self._remember(self._current_label())
        self._view = ("page", kind, ident)
        self._clear_filter()
        self.chips.hide()
        self._select_sidebar(None, ident if kind == "playlist" and any(
            r.playlist_id == ident for r in self._playlist_refs) else None)
        page = self._pages.get((kind, ident))
        if page is not None:
            self._show_page(page)
            return
        self._page = None
        self.header.show_collection(kind=kind.capitalize(), title=title or "Loading…", back=self._back_link(),
                                    playable=False)
        self._set_header_buttons()
        self.tools.hide()
        self.message.setText("Loading…")
        self._show_only(self.message)
        profile = auth.active_profile()
        view = self._view

        def done(page: Page):
            self._pages[(kind, ident)] = page
            if self._view == view:
                self._show_page(page)

        def failed(message):
            if self._view == view:
                self.message.setText(f"Couldn't open this {kind}: {message.splitlines()[0][:160]}")

        fetch = {"playlist": "playlist_page", "album": "album_page", "artist": "artist_page"}[kind]
        workers.run(lambda: getattr(self.manager.resolver(profile), fetch)(ident), on_done=done, on_error=failed)

    def _reload_page(self) -> None:
        if self._view[0] == "page":
            _page, kind, ident = self._view
            self._pages.pop((kind, ident), None)
            self._open(kind, ident, self._page.title if self._page else "", remember=False)

    def _show_page(self, page: Page) -> None:
        self._page = page
        art = [(page.thumbnail, RemoteArt(page.thumbnail))] if page.thumbnail else []
        self.header.show_collection(
            kind={"playlist": "Playlist", "album": "Album", "artist": "Artist"}[page.kind], title=page.title,
            meta=self._page_meta(page), art=art, art_style="round" if page.kind == "artist" else "square",
            back=self._back_link(), playable=False)
        self.tools.show()
        if page.kind == "artist":
            parts = [(k, label) for k, label, have in (("releases", "Albums and singles", page.releases),
                                                       ("songs", "Top songs", page.songs)) if have]
            if parts:
                self._set_chips(parts, parts[0][0], self._show_artist_part)
                self._show_artist_part(parts[0][0])
            else:
                self.chips.hide()
                self.tools.hide()
                self.message.setText("Nothing to download from this artist on YouTube Music.")
                self._show_only(self.message)
        else:
            self._fill_songs(page.songs, numbered=True)
            self._show_only(self.songs)
        if page.kind == "playlist":
            self._missing[page.id] = sum(1 for s in page.songs if not self._have(s.video_id))
            self._update_playlist_notes()
        self._set_header_buttons()
        self._apply_filter("")

    def _show_artist_part(self, part: str) -> None:
        page = self._page
        if page is None or page.kind != "artist":
            return
        self._clear_filter()
        if part == "songs":
            self._fill_songs(page.songs, numbered=True)
            self._show_only(self.songs)
        else:
            self._fill_grid(page.releases, round_covers=False)
            self._show_only(self.grid)
        self._apply_filter("")

    def _page_meta(self, page: Page) -> str:
        parts = [page.subtitle] if page.subtitle else []
        if page.kind == "artist":
            if page.releases:
                parts.append(f"{len(page.releases)} albums and singles")
            return " · ".join(parts)
        parts.append(song_count(len(page.songs)))
        seconds = sum(s.duration for s in page.songs)
        if seconds:
            parts.append(total_time(seconds))
        have = sum(1 for s in page.songs if self._have(s.video_id))
        if have:
            parts.append("all in your library" if have == len(page.songs) else f"{have} in your library")
        return " · ".join(parts)

    def _set_header_buttons(self) -> None:
        downloads = self._view[0] == "downloads"
        page = self._page
        self.cancel_btn.setVisible(downloads and any(s.active for s in self._sections))
        self.clear_btn.setVisible(downloads and any(s.job is not None and not s.active for s in self._sections))
        self.more_btn.setVisible(page is not None)
        if page is None or page.kind == "artist" or not page.songs:
            self.get_btn.hide()
            return
        self.get_btn.show()
        section = self._jobs.get(self._page_jobs.get(page.id, -1))
        missing = sum(1 for s in page.songs if not self._have(s.video_id))
        if section is not None and section.active:
            text, enabled = ("Downloading…" if section.state == "downloading" else "Queued…"), False
        elif not missing:
            text, enabled = "In your library", False
        elif missing == len(page.songs):
            text, enabled = ("Download album" if page.kind == "album" else f"Download {song_count(missing)}"), True
        else:
            text, enabled = f"Download {missing} new", True
        self.get_btn.setText(text)
        self.get_btn.setEnabled(enabled)
        self.get_btn.setToolTip("" if enabled else "Everything here is already in your library" if not missing else "")

    # ── Song lists ───────────────────────────────────────────────────────

    def _have(self, video_id: str) -> bool:
        live = self._live.get(video_id)
        return (live is not None and live[0] in (Status.DONE, Status.SKIPPED)) or bool(self.library.resolve_id(video_id))

    def _fill_songs(self, songs: list[Listing], numbered: bool) -> None:
        t = self.songs
        t.clearSelection()
        t.setRowCount(0)
        t.setRowCount(len(songs))
        self._art_items = {}
        for row, song in enumerate(songs):
            num = QTableWidgetItem()
            num.setData(Qt.DisplayRole, row + 1 if numbered else None)
            num.setData(SONG, song)
            title = QTableWidgetItem(song.title)
            if song.thumbnail:
                title.setIcon(QIcon(self.covers.thumb(song.thumbnail)))
                self._art_items.setdefault(song.thumbnail, []).append(title)
                self.covers.request(song.thumbnail, RemoteArt(small_cover(song.thumbnail)))
            for col, item in ((NUM, num), (NAME, title), (ARTIST, QTableWidgetItem(song.artist)),
                              (ALBUM, QTableWidgetItem(song.album)), (TIME, QTableWidgetItem(length(song.duration))),
                              (STATE, QTableWidgetItem())):
                t.setItem(row, col, item)
            self._set_song_state(row)
        hide_album = self._page is not None and self._page.kind == "album"
        t.setColumnHidden(ALBUM, hide_album)
        self._song_columns.apply()
        t.scrollToTop()

    def _song_at(self, row: int) -> Listing | None:
        item = self.songs.item(row, NUM)
        return item.data(SONG) if item is not None else None

    def _set_song_state(self, row: int) -> None:
        song = self._song_at(row)
        cell = self.songs.item(row, STATE)
        if song is None or cell is None:
            return
        status, progress = self._live.get(song.video_id, (None, 0.0))
        text, color, bar = "", None, None
        if status == Status.DOWNLOADING:
            text, bar = (f"Downloading {progress:.0%}" if progress else "Downloading"), progress or 0.0
        elif status in (Status.QUEUED, Status.TAGGING):
            text = status.value
        elif status == Status.FAILED:
            text, color = "Failed", FAILED_RED
        elif self._have(song.video_id):
            text, color = "✓ In library", self.palette().color(QPalette.Link)
        cell.setText(text)
        cell.setData(Qt.ForegroundRole, color)
        cell.setData(PROGRESS, bar)

    def _refresh_song_states(self) -> None:
        for row in range(self.songs.rowCount()):
            self._set_song_state(row)

    def _selected_songs(self) -> list[Listing]:
        rows = sorted({i.row() for i in self.songs.selectedIndexes()})
        return [s for s in (self._song_at(r) for r in rows if not self.songs.isRowHidden(r)) if s is not None]

    def _song_menu(self, pos) -> None:
        row = self.songs.rowAt(pos.y())
        song = self._song_at(row)
        if song is None:
            return
        if row not in {i.row() for i in self.songs.selectedIndexes()}:
            self.songs.selectRow(row)
        chosen = self._selected_songs()
        wanted = [s for s in chosen if not self._have(s.video_id)]
        menu = QMenu(self)
        get = menu.addAction(f"Download {song_count(len(wanted))}" if len(chosen) > 1 else "Download",
                             self._download_selected)
        get.setEnabled(bool(wanted))
        menu.addSeparator()
        menu.addAction("Copy link", lambda: QApplication.clipboard().setText(song.url))
        menu.addAction("Open on YouTube Music", lambda: QDesktopServices.openUrl(QUrl(song.url)))
        menu.exec(self.songs.viewport().mapToGlobal(pos))

    def _fill_grid(self, cards: list[Card], round_covers: bool) -> None:
        self._grid_cards = cards
        self.grid.round_covers = round_covers
        self.grid.set_tiles([Tile(f"{c.kind}:{c.id}", c.title, c.subtitle, c.thumbnail or c.id,
                                  RemoteArt(c.thumbnail)) for c in cards])

    def _on_cover(self, key: str) -> None:
        icon = QIcon(self.covers.thumb(key))
        for item in self._art_items.get(key, []) + self._queue_art.get(key, []):
            item.setIcon(icon)

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold()
        if self.grid.isVisibleTo(self) and not self.songs.isVisibleTo(self):
            shown, total, noun = self.grid.apply_filter(text), self.grid.count(), "results"
        else:
            shown = total = 0
            for row in range(self.songs.rowCount()):
                song = self._song_at(row)
                hidden = bool(needle) and song is not None and \
                    needle not in f"{song.title} {song.artist} {song.album}".casefold()
                self.songs.setRowHidden(row, hidden)
                shown += not hidden
                total += 1
            noun = "songs"
        self.filter.setPlaceholderText(f"Filter {noun}")
        self._shown = (shown, total, noun) if needle else None
        self._update_status()

    def _update_status(self) -> None:
        parts = []
        if self._shown:
            shown, total, noun = self._shown
            parts.append(f"{shown} of {total} {noun}")
        chosen = self._selected_songs() if self.songs.isVisibleTo(self) else []
        wanted = [s for s in chosen if not self._have(s.video_id)]
        if len(chosen) > 1:
            parts.append(f"{len(chosen)} selected")
        self.status.setText(" · ".join(parts))
        self.get_sel_btn.setVisible(self.songs.isVisibleTo(self))
        self.get_sel_btn.setEnabled(bool(wanted))
        self.get_sel_btn.setText(f"Download {len(wanted)} selected" if len(wanted) > 1 else "Download selected")

    # ── Queueing ─────────────────────────────────────────────────────────

    def _download_page(self) -> None:
        page = self._page
        if page is None or page.kind == "artist":  # an artist is opened, not downloaded whole
            return
        job = self.manager.new_job()
        section = _Section(page.title, "waiting", job=job)
        self._place_job(section)
        self._page_jobs[page.id] = job
        if page.kind == "playlist":
            self.manager.enqueue_playlist(page.id, page.title, self._playlists_for, job=job)
        else:
            self.manager.enqueue_url(page.url, job=job)
        self._after_queueing(f"Queued {page.title}")

    def _download_selected(self) -> None:
        wanted = [s for s in self._selected_songs() if not self._have(s.video_id)]
        for song in wanted:
            job = self.manager.new_job()
            self._place_job(_Section(f"{song.artist} - {song.title}" if song.artist else song.title, "waiting",
                                     job=job))
            self.manager.enqueue_url(song.url, job=job)
            self._live[song.video_id] = (Status.QUEUED, 0.0)
        if wanted:
            self._after_queueing(f"Queued {song_count(len(wanted))}")
            self._refresh_song_states()

    def _after_queueing(self, message: str) -> None:
        self.status_bar.showMessage(message, 4000)
        self._render()
        self._set_header_buttons()

    def _queue_links(self) -> None:
        """Queue every link in the search box (separated by spaces or new lines)."""
        words = self.search.text().split()
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
        self.search.setText(" ".join(bad))  # keep whatever wasn't a link, so it can be fixed
        parts = [f"Queued {len(links)} link{'' if len(links) == 1 else 's'}"] if links else []
        if owned:
            parts.append(f"{len(owned)} already in your library")
        if bad:
            parts.append(f"{len(bad)} not recognised")
        self.status_bar.showMessage("; ".join(parts), 5000)
        if links:
            self._history.clear()
            self._show_downloads()
        if owned:
            self._alert_owned(owned)

    def _owned(self, video_id: str):
        """The library's copy of a song (also matching the video it was swapped from), if any."""
        found = self.library.resolve_id(video_id)
        return self.library.track(found) if found else None

    def _alert_owned(self, songs: list[str]) -> None:
        shown = songs[:8] + ([f"…and {len(songs) - 8} more"] if len(songs) > 8 else [])
        one = len(songs) == 1
        QMessageBox.information(
            self, "Already in your library",
            ("This song is" if one else "These songs are") + " already in your library, so "
            + ("it wasn't" if one else "they weren't") + " downloaded again:\n\n" + "\n".join(shown))

    def _cancel(self) -> None:
        self.manager.cancel()
        # The running job reports its own cancellations; the rest never start.
        for section in self._sections:
            if section.state == "waiting":
                section.state = "cancelled"
                section.statuses = [(Status.CANCELLED, 0.0, "")] * len(section.tracks)
        self._live = {k: v for k, v in self._live.items() if v[0] not in BUSY}
        self._render()
        self._refresh_song_states()
        self._set_header_buttons()

    def _clear_finished(self) -> None:
        self._sections = [s for s in self._sections if s.active]
        self._jobs = {job: s for job, s in self._jobs.items() if s in self._sections}
        self._render()
        self._set_header_buttons()

    # ── Downloads view ───────────────────────────────────────────────────

    def _show_downloads(self) -> None:
        self._view, self._page = ("downloads",), None
        self._select_sidebar("downloads", None)
        self.chips.hide()
        self.tools.hide()
        self._render()

    def _downloads_meta(self) -> str:
        jobs = [s for s in self._sections if s.job is not None]
        active = [s for s in jobs if s.active]
        failed = sum(1 for s in jobs for status, _p, _e in s.statuses if status == Status.FAILED)
        parts = []
        if active:
            total = sum(len(s.tracks) for s in active)
            done = sum(len(s.ended) for s in active)
            parts.append(f"{done} of {song_count(total)}" if total else "starting…")
            waiting = sum(1 for s in active if s.state == "waiting")
            if waiting:
                parts.append(f"{waiting} more waiting")
        elif jobs:
            parts.append("All done")
        if failed:
            parts.append(f"{failed} failed")
        return " · ".join(parts)

    def _render(self) -> None:
        """Rebuild the queue table, and the Downloads view around it when that's showing."""
        table = self.table
        scroll = table.verticalScrollBar().value()
        table.clearSpans()
        table.setRowCount(sum(1 + len(s.tracks) for s in self._sections))
        self._queue_art = {}
        row = 0
        for section in self._sections:
            heading = QTableWidgetItem(section.header())
            heading.setData(SECTION, True)
            heading.setFlags(Qt.ItemIsEnabled)
            table.setItem(row, 0, heading)
            for col in (1, 2, 3):
                table.setItem(row, col, None)
            table.setSpan(row, 0, 1, table.columnCount())
            table.setRowHeight(row, SECTION_HEIGHT)
            row += 1
            for meta, status in zip(section.tracks, section.statuses):
                title = QTableWidgetItem(meta.title)
                if meta.cover_url:
                    thumb = small_cover(meta.cover_url)
                    title.setIcon(QIcon(self.covers.thumb(thumb)))
                    self._queue_art.setdefault(thumb, []).append(title)
                    self.covers.request(thumb, RemoteArt(thumb))
                table.setItem(row, 0, title)
                table.setItem(row, 1, QTableWidgetItem(meta.artist))
                table.setItem(row, 2, QTableWidgetItem(meta.album))
                self._set_queue_status(row, status)
                table.setRowHeight(row, ROW_HEIGHT)
                row += 1
        table.verticalScrollBar().setValue(scroll)
        self._update_progress()
        self._update_downloads_note()
        if self._view[0] != "downloads":
            return
        self.header.show_collection(kind="Queue", title="Downloads", meta=self._downloads_meta(), playable=False)
        self._set_header_buttons()
        if self._sections:
            self._show_only(self.table)
        else:
            self.message.setText(
                "Nothing downloading.\n\nSearch above or open one of your playlists,\n"
                "or paste a YouTube Music link into the search box.")
            self._show_only(self.message)

    def _set_queue_status(self, row: int, status: tuple[Status, float, str]) -> None:
        state, progress, error = status
        text = state.value
        if state == Status.DOWNLOADING and progress:
            text = f"Downloading {progress:.0%}"
        elif state == Status.FAILED:
            text = f"Failed: {error.splitlines()[0][:120]}" if error else "Failed"
        item = QTableWidgetItem(text)
        item.setData(Qt.ForegroundRole, FAILED_RED if state == Status.FAILED
                     else self.palette().color(QPalette.Link) if state == Status.DONE else None)
        item.setData(PROGRESS, progress if state == Status.DOWNLOADING else None)
        if error:
            item.setToolTip(error)
        self.table.setItem(row, 3, item)

    def _update_progress(self) -> None:
        """Overall progress across the queued and running jobs; hidden when idle."""
        active = [s for s in self._sections if s.active]
        total = sum(len(s.tracks) for s in active)
        self.overall.setVisible(bool(active))
        running = next((s for s in active if s.state == "downloading"), None)
        waiting = len(active) - (running is not None)
        text = f"Downloading {running.title}" if running else "Waiting to start"
        if running and waiting:
            text += f" · {waiting} more queued"
        self.overall.setText(text)
        self.overall.setRange(0, max(1, total))
        self.overall.setValue(sum(len(s.ended) for s in active))

    def _update_downloads_note(self) -> None:
        item = self.nav.item(1)
        active = [s for s in self._sections if s.active]
        total = sum(len(s.tracks) for s in active)
        item.setData(NOTE, f"{sum(len(s.ended) for s in active)} / {total}" if total else "…" if active else "")
        item.setData(NOTE_LIT, bool(active))

    # ── Progress from the download manager ───────────────────────────────

    def _on_queued(self, job: int, label: str) -> None:
        if job not in self._jobs:  # queued elsewhere (pasted links, the Library tab's playlist updates)
            self._place_job(_Section(label, "waiting", job=job))
            self._render()

    def _place_job(self, section: _Section) -> None:
        """List jobs in the order they'll run."""
        if section in self._sections:
            self._sections.remove(section)
        self._sections.append(section)
        self._jobs[section.job] = section

    def _on_started(self, job: int, collection: Collection) -> None:
        section = self._jobs.get(job)
        if section is None:
            return
        section.set_collection(collection)
        section.state = "downloading"
        for meta in collection.tracks:
            for vid in (meta.video_id, meta.source_video_id):
                if vid and vid not in self._live:
                    self._live[vid] = (Status.QUEUED, 0.0)
        self._render()
        self._refresh_song_states()
        self._set_header_buttons()

    def _on_event(self, job: int, ev: TrackEvent) -> None:
        for vid in (ev.meta.video_id, ev.meta.source_video_id):
            if vid:
                self._live[vid] = (ev.status, ev.progress)
        self._update_song_rows({ev.meta.video_id, ev.meta.source_video_id})
        section = self._jobs.get(job)
        if section is None or ev.index >= len(section.tracks):
            return
        if ev.status in FINAL:
            section.ended.add(ev.index)
        section.statuses[ev.index] = (ev.status, ev.progress, ev.error)
        row = self._first_row(section)
        if row is None:
            return
        self._set_queue_status(row + 1 + ev.index, section.statuses[ev.index])
        self.table.item(row, 0).setText(section.header())
        self._update_progress()
        self._update_downloads_note()
        if self._view[0] == "downloads":
            self.header.meta.setText(self._downloads_meta())
            self.header.meta.setVisible(bool(self.header.meta.text()))

    def _update_song_rows(self, video_ids: set[str]) -> None:
        for row in range(self.songs.rowCount()):
            song = self._song_at(row)
            if song is not None and song.video_id in video_ids:
                self._set_song_state(row)

    def _on_finished(self, job: int, collection: Collection, counts) -> None:
        parts = [f"{n} {status.value.lower()}" for status, n in counts.items()]
        self.status_bar.showMessage(f"{collection.title}: " + ", ".join(parts), 15000)
        section = self._jobs.get(job)
        if section is not None:
            section.state, section.note = "finished", ", ".join(parts) or "nothing to do"
            self._render()
        self._set_header_buttons()
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
        self._set_header_buttons()

    def _on_library_changed(self) -> None:
        self._missing = {pid: sum(1 for s in page.songs if not self._have(s.video_id))
                         for (kind, pid), page in self._pages.items() if kind == "playlist"}
        self._update_playlist_notes()
        self._refresh_song_states()
        if self._page is not None and self._view[0] == "page":
            self.header.meta.setText(self._page_meta(self._page))
        self._set_header_buttons()

    def _first_row(self, section: _Section) -> int | None:
        row = 0
        for s in self._sections:
            if s is section:
                return row
            row += 1 + len(s.tracks)
        return None
