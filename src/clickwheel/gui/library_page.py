"""Library tab: local songs, browsed by song, album, artist, recent additions or playlist."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDateTime, QLocale, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QIcon, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractScrollArea, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QPushButton, QSizePolicy, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..library import Library, LibraryPlaylist, LibraryTrack
from . import icons, workers
from .artwork import ArtPanel, CoverCache, album_key
from .collection_header import CollectionHeader
from .cover_grid import CoverGrid, Tile
from .fonts import ui_font
from .ribbon import SectionLabel
from .table_style import (
    MARK, MUTED, NUMBER, ROW_HEIGHT, SECTION, SECTION_HEIGHT, TEXT, TITLE, style_header, style_track_table,
)

TRACK_ID, ART_KEY, ART_PATH = 256, 257, 258  # item data roles: on the # cell, then on the Title cell
VIEW, LIST_ICON = Qt.UserRole + 1, Qt.UserRole + 2  # sidebar item data: the view it opens, its icon
NUM, NAME, ARTIST, ALBUM, YEAR, TIME, ADDED, ON_DEVICE = range(8)
RECENT = 100  # songs shown under Recently added
LINK = '<a href="{}" style="text-decoration: none;">{}</a>'
SIDEBAR = (("songs", "Songs", "songs"), ("albums", "Albums", "album"), ("artists", "Artists", "artist"),
           ("recent", "Recently added", "recent"))


class SortKeyItem(QTableWidgetItem):
    """Shows friendly text but sorts by a hidden key (Qt.UserRole)."""

    def __init__(self, text: str, key=None):
        super().__init__(text)
        if key is not None:
            self.setData(Qt.UserRole, key)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        mine, theirs = self.data(Qt.UserRole), other.data(Qt.UserRole)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return mine < theirs


@dataclass
class Album:
    key: str
    title: str
    artist: str
    year: str = ""
    tracks: list[LibraryTrack] = field(default_factory=list)


def group_albums(tracks: list[LibraryTrack]) -> list[Album]:
    """Albums by album artist, then year, each with its songs in track order."""
    albums: dict[str, Album] = {}
    for t in tracks:
        key = album_key(t.album_artist, t.album)
        album = albums.setdefault(key, Album(key, t.album, t.album_artist))
        album.year = album.year or t.year
        album.tracks.append(t)
    for album in albums.values():
        album.tracks.sort(key=lambda t: (t.track_number or 999, t.title.casefold()))
    return sorted(albums.values(), key=lambda a: (a.artist.casefold(), a.year, a.title.casefold()))


def song_count(n: int) -> str:
    return f"{n} song" if n == 1 else f"{n} songs"


def length(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def total_time(seconds: int) -> str:
    minutes = seconds // 60
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def days_ago(when: float, today: date | None = None) -> int:
    return ((today or date.today()) - date.fromtimestamp(when)).days


def updated_text(when: float) -> str:
    days = days_ago(when)
    if days <= 0:
        return "updated today"
    if days == 1:
        return "updated yesterday"
    if days < 30:
        return f"updated {days} days ago"
    return "updated " + QLocale.system().toString(QDateTime.fromSecsSinceEpoch(int(when)).date(), QLocale.ShortFormat)


def added_group(when: float, today: date | None = None) -> str:
    """The Recently added heading a song falls under."""
    days = days_ago(when, today)
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 7:
        return "This week"
    if days < 30:
        return "This month"
    return QLocale.system().toString(QDateTime.fromSecsSinceEpoch(int(when)).date(), "MMMM yyyy")


class LibraryPage(QWidget):
    sync_requested = Signal(list)  # library file paths to add to the current iPod
    play_requested = Signal(list, int)  # PlayItems in view order, index to start at
    shuffle_requested = Signal(list)  # PlayItems to play in random order
    browse_requested = Signal()  # the library is empty: go and find music

    def __init__(self, library: Library, manager: workers.DownloadManager):
        super().__init__()
        self.library = library
        self.manager = manager
        self.covers = CoverCache(self)
        self.covers.loaded.connect(self._on_cover)
        self._art_items: dict[str, list[QTableWidgetItem]] = {}
        self._now_path: str | None = None
        self._tracks: list[LibraryTrack] = []
        self._playlists: list[LibraryPlaylist] = []
        self._view: tuple[str, str] = ("songs", "")
        self._back: tuple[str, str] | None = None  # where the header's back link goes
        self._noun = "songs"  # what the current view lists, for the filter count
        self._art_track: LibraryTrack | None = None  # the song in the art panel
        self._device_name = ""
        self._on_device: set[tuple[str, str, str]] = set()
        self._shown: tuple[int, int] | None = None  # (visible, total) while a filter is typed

        # ── Sidebar ──
        self.nav = QListWidget()
        for key, label, _icon in SIDEBAR:
            item = QListWidgetItem(label)
            item.setData(VIEW, key)
            item.setData(LIST_ICON, _icon)
            self.nav.addItem(item)
        self.nav.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.nav.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.currentItemChanged.connect(self._nav_chosen)
        self.lists = QListWidget()
        self.lists.currentItemChanged.connect(self._list_chosen)
        self.lists_hint = QLabel("Playlists and albums you download from YouTube Music show up here.")
        self.lists_hint.setWordWrap(True)
        self.lists_hint.setStyleSheet("color: palette(placeholder-text); padding: 4px;")
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(SectionLabel("<b>Library</b>"))
        lv.addWidget(self.nav)
        lv.addSpacing(6)
        lv.addWidget(SectionLabel("<b>Collections</b>"))
        lv.addWidget(self.lists, 1)
        lv.addWidget(self.lists_hint)

        # ── Header ──
        self.header = CollectionHeader(self.covers)
        self.header.play_clicked.connect(lambda: self._play_from(self._first_track_row()))
        self.header.shuffle_clicked.connect(self._shuffle)
        self.header.link_clicked.connect(self._on_link)
        self.update_btn = QPushButton("Update from YouTube Music")
        self.update_btn.setToolTip("Download songs added to this playlist since the last time")
        self.update_btn.setAutoDefault(False)
        self.update_btn.clicked.connect(self._update_playlist)
        self.more_btn = QPushButton()
        self.more_btn.setToolTip("More")
        self.more_btn.setAutoDefault(False)
        self.more_btn.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0; }")
        more = QMenu(self.more_btn)
        self.remove_action = more.addAction("Remove playlist…", self._remove_playlist)
        more.addAction("Open library folder",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.root))))
        self.more_btn.setMenu(more)
        self.header.actions.addWidget(self.update_btn)
        self.header.actions.addWidget(self.more_btn)
        self.header.actions.addStretch(1)

        # ── Filter, status, sync ──
        self.filter = QLineEdit()
        self.filter.setClearButtonEnabled(True)
        self.filter.setMaximumWidth(320)
        self._search_action = self.filter.addAction(QIcon(), QLineEdit.LeadingPosition)
        self.filter.textChanged.connect(self._apply_filter)
        self.status = QLabel()
        self.status.setStyleSheet("color: palette(placeholder-text);")
        self.sync_btn = QPushButton("Sync to iPod")
        self.sync_btn.setToolTip("Add the selected songs to the iPod without removing anything")
        self.sync_btn.setAutoDefault(False)
        self.sync_btn.clicked.connect(self._sync_selected)
        tools = QHBoxLayout()
        tools.addWidget(self.filter)
        tools.addStretch(1)
        tools.addWidget(self.status)
        tools.addWidget(self.sync_btn)

        # ── Song table ──
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["#", "Title", "Artist", "Album", "Year", "Time", "Added", ""])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.setSortingEnabled(True)
        self._columns = style_track_table(
            self.table, {NUM: NUMBER, NAME: TITLE, ARTIST: TEXT, ALBUM: MUTED, YEAR: NUMBER, TIME: NUMBER,
                         ADDED: MUTED, ON_DEVICE: MARK},
            {NUM: 44, YEAR: 58, TIME: 58, ADDED: 92, ON_DEVICE: 30}, weights={NAME: 6, ARTIST: 3, ALBUM: 3})
        self.table.setColumnHidden(ON_DEVICE, True)
        self.table.currentCellChanged.connect(lambda row, *_: self._show_selected(row))
        self.table.itemSelectionChanged.connect(self._update_status)
        self.table.doubleClicked.connect(lambda index: self._play_from(index.row()))
        for keys, slot in ((QKeySequence(Qt.Key_Return), lambda: self._play_from(self.table.currentRow())),
                           (QKeySequence.Delete, self._delete_selected)):
            QShortcut(keys, self.table, slot, context=Qt.WidgetWithChildrenShortcut)

        # ── Album and artist walls ──
        self.albums_grid = CoverGrid(self.covers)
        self.albums_grid.opened.connect(lambda key: self._go(("album", key), back=("albums", "")))
        self.artists_grid = CoverGrid(self.covers, round_covers=True)
        self.artists_grid.opened.connect(lambda key: self._go(("artist", key), back=("artists", "")))

        self.empty = self._empty_state()
        self.stack = QStackedWidget()
        for page in (self.table, self.albums_grid, self.artists_grid, self.empty):
            self.stack.addWidget(page)

        middle = QWidget()
        mv = QVBoxLayout(middle)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addWidget(self.header)
        mv.addLayout(tools)
        mv.addWidget(self.stack, 1)
        self._tools = [self.filter, self.status, self.sync_btn]

        # ── Art panel ──
        self.art = ArtPanel(self.covers)
        self.art_links = QLabel(f'{LINK.format("art-album", "Show album")} · {LINK.format("art-artist", "Show artist")}')
        self.art_links.setAlignment(Qt.AlignHCenter)
        self.art_links.linkActivated.connect(self._on_link)
        self.art.footer.addWidget(self.art_links)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(middle)
        split.addWidget(self.art)
        split.setStretchFactor(1, 1)
        split.setSizes([210, 680, 250])
        QVBoxLayout(self).addWidget(split)

        manager.library_changed.connect(self.refresh)
        self.restyle()
        self.refresh()

    def _empty_state(self) -> QWidget:
        page = QWidget()
        self._empty_icon = QLabel()
        self._empty_icon.setAlignment(Qt.AlignCenter)
        self._empty_title = QLabel("Your library is empty")
        self._empty_title.setAlignment(Qt.AlignCenter)
        text = QLabel("Download songs, albums or playlists from the YouTube Music tab.\n"
                      "They'll show up here, ready to play and to sync to your iPod.")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        text.setStyleSheet("color: palette(placeholder-text);")
        go = QPushButton("Go to YouTube Music")
        go.setDefault(True)
        go.setAutoDefault(False)
        go.clicked.connect(self.browse_requested)
        v = QVBoxLayout(page)
        v.addStretch(1)
        v.addWidget(self._empty_icon)
        v.addSpacing(6)
        v.addWidget(self._empty_title)
        v.addWidget(text)
        v.addSpacing(10)
        v.addWidget(go, 0, Qt.AlignCenter)
        v.addStretch(2)
        return page

    # ── Theme ────────────────────────────────────────────────────────────

    def restyle(self) -> None:
        """Icons and fonts for the current theme (call after a theme change)."""
        self._paint_sidebar_icons()
        muted = self.palette().color(QPalette.PlaceholderText)
        self._search_action.setIcon(QIcon(icons.pixmap("search", muted, 16)))
        self.more_btn.setIcon(icons.icon("more", self.more_btn.palette().color(QPalette.ButtonText), size=16))
        self._empty_icon.setPixmap(icons.pixmap("songs", muted, 56))
        self._empty_title.setFont(ui_font(14, QFont.Bold))
        self.header.restyle()
        links = self.art_links.text()  # QLabel keeps link colours from when its text was set
        self.art_links.clear()
        self.art_links.setText(links)
        style_header(self.table, self.table.itemDelegate().kinds)

    def _paint_sidebar_icons(self) -> None:
        for view in (self.nav, self.lists):
            pal = view.palette()
            view.setIconSize(QSize(16, 16))
            for i in range(view.count()):
                item = view.item(i)
                name = item.data(LIST_ICON)
                icon = QIcon(icons.pixmap(name, pal.color(QPalette.Text), 16))
                icon.addPixmap(icons.pixmap(name, pal.color(QPalette.HighlightedText), 16), QIcon.Selected)
                item.setIcon(icon)

    # ── Loading and navigation ───────────────────────────────────────────

    def refresh(self) -> None:
        """Re-read the library and redraw the current view."""
        self._tracks = self.library.tracks()
        self._playlists = self.library.playlists()
        self.lists.blockSignals(True)
        self.lists.clear()
        for p in self._playlists:
            item = QListWidgetItem(p.title)
            item.setData(VIEW, p.id)
            item.setData(LIST_ICON, "album" if p.kind == "album" else "playlist")
            item.setToolTip(f"{p.title}\n{song_count(p.track_count)}")
            self.lists.addItem(item)
        self.lists.blockSignals(False)
        self.lists_hint.setVisible(not self._playlists)
        self._paint_sidebar_icons()
        if not self._exists(self._view):
            self._view, self._back = ("songs", ""), None
        self._render()

    def _exists(self, view: tuple[str, str]) -> bool:
        kind, key = view
        if kind == "playlist":
            return any(p.id == key for p in self._playlists)
        if kind == "album":
            return any(album_key(t.album_artist, t.album) == key for t in self._tracks)
        if kind == "artist":
            return any(t.album_artist.casefold() == key for t in self._tracks)
        return True

    def _nav_chosen(self, item: QListWidgetItem | None, _previous=None) -> None:
        if item is not None:
            self._go((item.data(VIEW), ""))

    def _list_chosen(self, item: QListWidgetItem | None, _previous=None) -> None:
        if item is not None:
            self._go(("playlist", item.data(VIEW)))

    def _go(self, view: tuple[str, str], back: tuple[str, str] | None = None) -> None:
        if view == self._view and back == self._back:
            return
        self._view, self._back = view, back
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.blockSignals(False)
        self._render()

    def _select_in_sidebar(self) -> None:
        """Highlight the sidebar entry the current view belongs to."""
        kind, key = self._view
        came_from = self._back[0] if self._back else ""
        if kind == "artist" or (kind == "album" and came_from in ("artist", "artists")):
            kind = "artists"
        elif kind == "album":
            kind = "albums"
        for view, target in ((self.nav, kind if kind != "playlist" else None),
                             (self.lists, key if kind == "playlist" else None)):
            view.blockSignals(True)
            match = next((view.item(i) for i in range(view.count()) if view.item(i).data(VIEW) == target), None)
            view.setCurrentItem(match)
            if match is None:
                view.clearSelection()
            view.blockSignals(False)

    def _render(self) -> None:
        self._select_in_sidebar()
        if not self._tracks:
            self.header.hide()
            for widget in self._tools:
                widget.hide()
            self.stack.setCurrentWidget(self.empty)
            self.art.show_track(None)
            self.art_links.hide()
            return
        self.header.show()
        for widget in self._tools:
            widget.show()
        kind, key = self._view
        self.update_btn.setVisible(kind == "playlist")
        self.remove_action.setVisible(kind == "playlist")
        getattr(self, f"_show_{kind}")(key)
        self._apply_filter(self.filter.text())

    def _back_link(self) -> str:
        if self._back is None:
            return ""
        kind, key = self._back
        if kind == "artist":
            label = next((t.album_artist for t in self._tracks if t.album_artist.casefold() == key), "Artist")
        elif kind == "album":
            label = next((t.album for t in self._tracks if album_key(t.album_artist, t.album) == key), "Album")
        else:
            label = {"albums": "Albums", "artists": "Artists"}.get(kind, "Back")
        return LINK.format("back", f"‹ {html.escape(label)}")

    # ── Views ────────────────────────────────────────────────────────────

    def _show_songs(self, _key: str) -> None:
        tracks = self._tracks
        newest = sorted(tracks, key=lambda t: -t.added_at)
        albums = group_albums(tracks)
        artists = {t.album_artist.casefold() for t in tracks}
        self.header.show_collection(
            kind="Library", title="Songs", art=self._mosaic(newest), art_style="mosaic",
            meta=" · ".join([song_count(len(tracks)), total_time(sum(t.duration for t in tracks)),
                             f"{len(albums)} albums", f"{len(artists)} artists"]))
        self._show_table(tracks, sortable=True)

    def _show_recent(self, _key: str) -> None:
        tracks = sorted(self._tracks, key=lambda t: -t.added_at)[:RECENT]
        rows: list[LibraryTrack | str] = []
        today, group = date.today(), None
        for t in tracks:  # newest first, so each heading's songs are together
            if added_group(t.added_at, today) != group:
                group = added_group(t.added_at, today)
                rows.append(group)
            rows.append(t)
        self.header.show_collection(
            kind="Library", title="Recently added", art=self._mosaic(tracks), art_style="mosaic",
            meta=(f"Your {RECENT} newest songs" if len(tracks) == RECENT else song_count(len(tracks)))
            + ", newest first")
        self._show_table(rows)

    def _show_albums(self, _key: str) -> None:
        albums = group_albums(self._tracks)
        self.albums_grid.set_tiles([
            Tile(a.key, a.title, " · ".join(x for x in (a.artist, a.year) if x), a.key,
                 self.library.root / a.tracks[0].relpath) for a in albums])
        self.header.show_collection(kind="Library", title="Albums", playable=False,
                                    meta=f"{len(albums)} albums · {song_count(len(self._tracks))}")
        self._show_grid(self.albums_grid, "albums")

    def _show_artists(self, _key: str) -> None:
        by_artist: dict[str, list[Album]] = {}
        for album in group_albums(self._tracks):
            by_artist.setdefault(album.artist.casefold(), []).append(album)
        tiles = []
        for key, albums in sorted(by_artist.items()):
            songs = sum(len(a.tracks) for a in albums)
            newest = max(albums, key=lambda a: a.year)
            summary = f"{len(albums)} albums" if len(albums) > 1 else song_count(songs)
            tiles.append(Tile(key, albums[0].artist, summary, newest.key,
                              self.library.root / newest.tracks[0].relpath))
        self.artists_grid.set_tiles(tiles)
        self.header.show_collection(kind="Library", title="Artists", playable=False,
                                    meta=f"{len(tiles)} artists · {song_count(len(self._tracks))}")
        self._show_grid(self.artists_grid, "artists")

    def _show_playlist(self, pid: str) -> None:
        playlist = next(p for p in self._playlists if p.id == pid)
        tracks = self.library.playlist_tracks(pid)
        is_album = playlist.kind == "album"
        meta = [song_count(len(tracks)), total_time(sum(t.duration for t in tracks))]
        if playlist.updated_at:
            meta.append(updated_text(playlist.updated_at))
        self.header.show_collection(
            kind="Downloaded album" if is_album else "Playlist", title=playlist.title, meta=" · ".join(meta),
            art=self._mosaic(tracks), art_style="square" if is_album else "mosaic")
        self._show_table(tracks, numbered=not is_album)

    def _show_album(self, key: str) -> None:
        album = next(a for a in group_albums(self._tracks) if a.key == key)
        meta = [LINK.format("album-artist", html.escape(album.artist))]
        meta += [x for x in (album.year, song_count(len(album.tracks)),
                             total_time(sum(t.duration for t in album.tracks))) if x]
        self.header.show_collection(
            kind="Album", title=album.title, meta=" · ".join(meta), back=self._back_link(),
            art=[(album.key, self.library.root / album.tracks[0].relpath)])
        self._show_table(album.tracks, sortable=True, hide=self._same_artist(album.tracks, ALBUM, YEAR))

    def _show_artist(self, key: str) -> None:
        albums = [a for a in group_albums(self._tracks) if a.artist.casefold() == key]
        albums.sort(key=lambda a: (a.year, a.title.casefold()), reverse=True)  # newest first
        rows: list[LibraryTrack | str] = []
        for a in albums:
            rows.append(" · ".join(x for x in (a.title, a.year) if x))
            rows.extend(a.tracks)
        songs = [r for r in rows if not isinstance(r, str)]
        meta = [f"{len(albums)} albums" if len(albums) > 1 else "1 album", song_count(len(songs)),
                total_time(sum(t.duration for t in songs))]
        self.header.show_collection(
            kind="Artist", title=albums[0].artist, meta=" · ".join(meta), back=self._back_link(),
            art=[(albums[0].key, self.library.root / albums[0].tracks[0].relpath)], art_style="round")
        self._show_table(rows, hide=self._same_artist(songs, ALBUM, YEAR))

    @staticmethod
    def _same_artist(tracks: list[LibraryTrack], *hide: int) -> tuple[int, ...]:
        """``hide``, plus the Artist column when every song is by the album's artist (no features)."""
        alone = all(t.artist.casefold() == t.album_artist.casefold() for t in tracks)
        return (*hide, ARTIST) if alone else hide

    def _mosaic(self, tracks: list[LibraryTrack]) -> list[tuple[str, Path]]:
        """Covers of the first four different albums among ``tracks``."""
        seen: dict[str, Path] = {}
        for t in tracks:
            seen.setdefault(album_key(t.album_artist, t.album), self.library.root / t.relpath)
            if len(seen) == 4:
                break
        return list(seen.items())

    def _show_grid(self, grid: CoverGrid, noun: str) -> None:
        self._noun = noun
        self.filter.setPlaceholderText(f"Filter {noun}")
        self.sync_btn.hide()
        self.more_btn.hide()
        self.stack.setCurrentWidget(grid)
        self._show_selected(-1)

    def _show_table(self, rows: list[LibraryTrack | str], *, sortable: bool = False, numbered: bool = False,
                    hide: tuple[int, ...] = ()) -> None:
        """Fill the song table. ``rows`` may hold headings (strings) between songs;
        ``numbered`` shows the position in the list instead of the album track number."""
        self._noun = "songs"
        self.filter.setPlaceholderText("Filter songs")
        self.sync_btn.show()
        self.more_btn.show()
        self.stack.setCurrentWidget(self.table)
        t = self.table
        t.setSortingEnabled(False)
        t.clearSelection()
        t.clearSpans()
        t.setRowCount(0)
        t.setRowCount(len(rows))
        self._art_items = {}
        locale = QLocale.system()
        position = 0
        for row, entry in enumerate(rows):
            if isinstance(entry, str):
                heading = QTableWidgetItem(entry)
                heading.setData(SECTION, True)
                heading.setFlags(Qt.ItemIsEnabled)
                t.setItem(row, 0, heading)
                t.setSpan(row, 0, 1, t.columnCount())
                t.setRowHeight(row, SECTION_HEIGHT)
                continue
            track, position = entry, position + 1
            t.setRowHeight(row, ROW_HEIGHT)
            num = QTableWidgetItem()
            num.setData(Qt.DisplayRole, position if numbered else (track.track_number or None))
            num.setData(TRACK_ID, track.video_id)
            when = QDateTime.fromSecsSinceEpoch(int(track.added_at))
            added = SortKeyItem(locale.toString(when.date(), QLocale.ShortFormat), track.added_at)
            added.setToolTip(locale.toString(when, QLocale.LongFormat))
            title = QTableWidgetItem(track.title)
            key = album_key(track.album_artist, track.album)
            title.setData(ART_KEY, key)
            title.setData(ART_PATH, str(self.library.root / track.relpath))
            title.setIcon(QIcon(self.covers.thumb(key)))
            self._art_items.setdefault(key, []).append(title)
            self.covers.request(key, self.library.root / track.relpath)
            album_order = (track.album.casefold(), track.track_number)
            cells = {
                NUM: num, NAME: title,
                ARTIST: SortKeyItem(track.artist, (track.artist.casefold(), *album_order)),
                ALBUM: SortKeyItem(track.album, album_order),
                YEAR: SortKeyItem(track.year, (track.year, *album_order)),
                TIME: SortKeyItem(length(track.duration), track.duration),
                ADDED: added, ON_DEVICE: QTableWidgetItem(),
            }
            for col, item in cells.items():
                t.setItem(row, col, item)
        for col in (ARTIST, ALBUM, YEAR):
            t.setColumnHidden(col, col in hide)
        self._mark_on_device()
        if sortable:  # start in the order given, until a heading is clicked
            t.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        t.setSortingEnabled(sortable)
        t.scrollToTop()
        self._mark_now_playing()
        self._show_selected(-1)

    # ── Table rows ───────────────────────────────────────────────────────

    def _row_track(self, row: int) -> LibraryTrack | None:
        item = self.table.item(row, NUM) if row >= 0 else None
        if item is None or item.data(SECTION):
            return None
        return self.library.track(item.data(TRACK_ID))

    def _row_path(self, row: int) -> str | None:
        title = self.table.item(row, NAME)
        return title.data(ART_PATH) if title is not None else None

    def _track_rows(self, visible_only: bool = True) -> list[int]:
        t = self.table
        return [r for r in range(t.rowCount())
                if not (visible_only and t.isRowHidden(r)) and t.item(r, NUM) is not None
                and not t.item(r, NUM).data(SECTION)]

    def _first_track_row(self) -> int:
        rows = self._track_rows()
        return rows[0] if rows else -1

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()} & set(self._track_rows()))

    def _on_cover(self, key: str) -> None:
        icon = QIcon(self.covers.thumb(key))
        for item in self._art_items.get(key, []):
            item.setIcon(icon)

    def _show_selected(self, row: int) -> None:
        track = self._row_track(row) if row >= 0 else None
        if track is None and self._now_path:  # nothing selected: show what's playing
            track = self._row_track(self._now_playing_row())
            if track is None:
                track = next((t for t in self._tracks if str(self.library.root / t.relpath) == self._now_path), None)
        self._art_track = track
        self.art_links.setVisible(track is not None)
        if track is None:
            self.art.show_track(None)
            return
        self.art.show_track(album_key(track.album_artist, track.album), track.title, track.artist, track.album,
                            self.library.root / track.relpath)

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold()
        grid = self.stack.currentWidget()
        if isinstance(grid, CoverGrid):
            shown, total = grid.apply_filter(text), grid.count()
        else:
            t = self.table
            heading, heading_used, shown, total = -1, False, 0, 0
            for row in range(t.rowCount()):
                item = t.item(row, NUM)
                if item is not None and item.data(SECTION):
                    if heading >= 0:
                        t.setRowHidden(heading, not heading_used)
                    heading, heading_used = row, False
                    continue
                hay = " ".join(t.item(row, c).text() for c in (NAME, ARTIST, ALBUM)).casefold()
                hidden = bool(needle) and needle not in hay
                t.setRowHidden(row, hidden)
                heading_used |= not hidden
                shown += not hidden
                total += 1
            if heading >= 0:
                t.setRowHidden(heading, not heading_used)
        self._shown = (shown, total) if needle else None
        self._update_status()

    def _update_status(self) -> None:
        parts = []
        if self._shown:
            shown, total = self._shown
            parts.append(f"{shown} of {total} {self._noun}")
        selected = len(self._selected_rows()) if self.stack.currentWidget() is self.table else 0
        if selected > 1:
            parts.append(f"{selected} selected")
        self.status.setText(" · ".join(parts))
        self.sync_btn.setEnabled(selected > 0)
        self.sync_btn.setText(f"Sync {selected} songs to iPod" if selected > 1 else "Sync to iPod")

    # ── Playing ──────────────────────────────────────────────────────────

    def _play_items(self, rows: list[int]):
        from .player import PlayItem

        items = []
        for r in rows:
            track = self._row_track(r)
            if track is not None:
                items.append((r, PlayItem(self.library.root / track.relpath, track.title, track.artist, track.album)))
        return items

    def _play_from(self, row: int) -> None:
        """Queue every visible song in the order shown, starting at ``row``."""
        if row < 0 or self._row_track(row) is None:
            return
        items = self._play_items(self._track_rows())
        start = next((i for i, (r, _item) in enumerate(items) if r == row), 0)
        if items:
            self.play_requested.emit([item for _r, item in items], start)

    def _shuffle(self) -> None:
        items = [item for _r, item in self._play_items(self._track_rows())]
        if items:
            self.shuffle_requested.emit(items)

    def set_now_playing(self, path) -> None:
        self._now_path = str(path) if path else None
        self._mark_now_playing()
        if self.table.currentRow() < 0 or not self.table.selectedIndexes():
            self._show_selected(-1)

    def _mark_now_playing(self) -> None:
        accent = self.palette().color(QPalette.Link)
        for row in self._track_rows(visible_only=False):
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
        return next((r for r in self._track_rows(visible_only=False) if self._row_path(r) == self._now_path), -1)

    # ── On the iPod ──────────────────────────────────────────────────────

    def set_device_contents(self, name: str, contents) -> None:
        """Mark the songs the plugged-in iPod already has (``contents`` None: no iPod)."""
        self._device_name = name if contents is not None else ""
        self._on_device = {(t.title.casefold(), t.artist.casefold(), t.album.casefold())
                           for t in (contents.tracks if contents is not None else [])}
        self._mark_on_device()

    def _mark_on_device(self) -> None:
        t = self.table
        t.setColumnHidden(ON_DEVICE, not self._device_name)
        t.horizontalHeaderItem(ON_DEVICE).setToolTip(f"On {self._device_name}" if self._device_name else "")
        for row in self._track_rows(visible_only=False):
            on = (t.item(row, NAME).text().casefold(), t.item(row, ARTIST).text().casefold(),
                  t.item(row, ALBUM).text().casefold()) in self._on_device
            mark = t.item(row, ON_DEVICE)
            mark.setText("on" if on else "")
            mark.setToolTip(f"On {self._device_name}" if on else f"Not on {self._device_name} yet")
        self._columns.apply()

    # ── Actions ──────────────────────────────────────────────────────────

    def _context_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        track = self._row_track(row)
        if track is None:
            return
        if row not in self._selected_rows():
            self.table.selectRow(row)
        menu = QMenu(self)
        menu.addAction("Play", lambda: self._play_from(row))
        menu.addSeparator()
        menu.addAction("Sync to iPod", self._sync_selected)
        menu.addAction("Show in folder", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str((self.library.root / track.relpath).parent))))
        if self._view[0] != "album":
            menu.addAction("Go to album", lambda: self._open_album_of(track))
        if self._view[0] != "artist":
            menu.addAction("Go to artist", lambda: self._open_artist_of(track))
        menu.addSeparator()
        delete = QAction("Delete from library…", menu)
        delete.triggered.connect(self._delete_selected)
        menu.addAction(delete)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _open_album_of(self, track: LibraryTrack) -> None:
        """Open the song's album; the back link returns to the artist page it was opened from."""
        back = self._view if self._view[0] == "artist" else ("albums", "")
        self._go(("album", album_key(track.album_artist, track.album)), back=back)

    def _open_artist_of(self, track: LibraryTrack) -> None:
        back = self._view if self._view[0] == "album" else ("artists", "")
        self._go(("artist", track.album_artist.casefold()), back=back)

    def _on_link(self, href: str) -> None:
        kind, key = self._view
        if href == "back" and self._back is not None:
            back = self._back
            self._go(back, back={"artist": ("artists", ""), "album": ("albums", "")}.get(back[0]))
        elif href == "album-artist" and kind == "album":
            artist = next(a.artist for a in group_albums(self._tracks) if a.key == key)
            self._go(("artist", artist.casefold()), back=("album", key))
        elif href == "art-album" and self._art_track is not None:
            self._open_album_of(self._art_track)
        elif href == "art-artist" and self._art_track is not None:
            self._open_artist_of(self._art_track)

    def _sync_selected(self) -> None:
        paths = []
        for row in self._selected_rows():
            track = self._row_track(row)
            if track is not None:
                paths.append(self.library.root / track.relpath)
        if paths:
            self.sync_requested.emit(paths)

    def _delete_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        if QMessageBox.question(self, "Delete songs",
                                f"Delete {song_count(len(rows))} from your library and disk? "
                                "They'll be removed from the iPod on the next sync.") != QMessageBox.Yes:
            return
        for row in rows:
            self.library.delete_track(self.table.item(row, NUM).data(TRACK_ID))
        self.refresh()

    def _update_playlist(self) -> None:
        kind, pid = self._view
        playlist = next((p for p in self._playlists if p.id == pid), None) if kind == "playlist" else None
        if playlist is None:
            return
        # Private playlists only resolve with the account they were downloaded from.
        profile = playlist.profile or None
        if playlist.url:
            self.manager.enqueue_url(playlist.url, profile)
        else:
            self.manager.enqueue_playlist(pid, playlist.title, profile)

    def _remove_playlist(self) -> None:
        kind, pid = self._view
        if kind == "playlist" and QMessageBox.question(
                self, "Remove playlist", "Remove this playlist? Its songs stay in your library.") == QMessageBox.Yes:
            self.library.delete_playlist(pid)
            self.refresh()
