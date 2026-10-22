import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from clickwheel.devices.contents import DeviceContents, DeviceTrack  # noqa: E402
from clickwheel.gui.artwork import album_key  # noqa: E402
from clickwheel.gui.library_page import (  # noqa: E402
    ALBUM, ARTIST, NAME, NUM, ON_DEVICE, TIME, YEAR, LibraryPage, added_group,
)
from clickwheel.gui.table_style import SECTION  # noqa: E402
from clickwheel.library import Library  # noqa: E402


class FakeManager(QObject):
    library_changed = Signal()

    def __init__(self):
        super().__init__()
        self.enqueued = []

    def enqueue_url(self, url, profile):
        self.enqueued.append(url)

    def enqueue_playlist(self, pid, title, profile):
        self.enqueued.append(pid)


@pytest.fixture
def page(library):
    QApplication.instance() or QApplication([])
    page = LibraryPage(library, FakeManager())
    page.resize(1100, 700)
    page.show()
    yield page
    dispose(page)


def dispose(page) -> None:
    """Let cover threads finish and their signals land before the page goes."""
    page.close()
    page.covers.shutdown()
    QApplication.processEvents()
    shiboken6.delete(page)  # now, not whenever Python gets round to it (at exit, Qt may be half gone)


def titles(page) -> list[str]:
    t = page.table
    return [t.item(r, NAME).text() for r in page._track_rows()]


def headings(page) -> list[str]:
    t = page.table
    return [t.item(r, NUM).text() for r in range(t.rowCount())
            if t.item(r, NUM).data(SECTION) and not t.isRowHidden(r)]


def test_empty_library_points_to_youtube_music(tmp_path):
    QApplication.instance() or QApplication([])
    page = LibraryPage(Library(tmp_path / "lib", tmp_path / "db.sqlite3"), FakeManager())
    assert page.stack.currentWidget() is page.empty
    assert page.header.isHidden()
    asked = []
    page.browse_requested.connect(lambda: asked.append(True))
    next(b for b in page.empty.findChildren(type(page.sync_btn)) if b.text() == "Go to YouTube Music").click()
    assert asked == [True]
    dispose(page)


def test_songs_start_in_artist_album_track_order(page):
    assert page.nav.currentItem().text() == "Songs"
    assert titles(page) == ["Other Single", "First Song", "Second: Song?"]  # Solo Act, then The Testers
    assert page.table.horizontalHeader().sortIndicatorSection() == -1
    first = page._track_rows()[0]
    assert page.table.item(first, TIME).text() == "0:06"
    page.table.sortByColumn(NAME, Qt.AscendingOrder)
    assert titles(page) == ["First Song", "Other Single", "Second: Song?"]


def test_albums_open_with_a_way_back(page):
    page.nav.setCurrentRow(1)
    assert page.stack.currentWidget() is page.albums_grid
    assert page.albums_grid.count() == 2
    page.albums_grid.opened.emit(album_key("The Testers", "Debut"))
    assert page.header.title.text() == "Debut"
    assert titles(page) == ["First Song", "Second: Song?"]
    hidden = {c for c in range(page.table.columnCount()) if page.table.isColumnHidden(c)}
    assert {ALBUM, YEAR} <= hidden and ARTIST not in hidden  # a guest artist on track 2
    assert page.nav.currentItem().text() == "Albums"  # still where it was opened from
    page._on_link("back")
    assert page.stack.currentWidget() is page.albums_grid


def test_artist_page_groups_songs_under_albums(page):
    page._on_link("art-artist")  # nothing in the art panel yet: ignored
    page._go(("artist", "the testers"), back=("artists", ""))
    assert headings(page) == ["Debut · 2021"]
    page.filter.setText("second")
    assert titles(page) == ["Second: Song?"] and headings(page) == ["Debut · 2021"]
    assert page.status.text() == "1 of 2 songs"
    page.filter.setText("no such song")
    assert titles(page) == [] and headings(page) == []


def test_single_artist_album_hides_the_artist_column(page):
    page._go(("album", album_key("Solo Act", "Single")))
    assert page.table.isColumnHidden(ARTIST)


def test_play_and_shuffle_use_the_songs_shown(page):
    played, shuffled = [], []
    page.play_requested.connect(lambda items, start: played.append(([i.title for i in items], start)))
    page.shuffle_requested.connect(lambda items: shuffled.append([i.title for i in items]))
    page.filter.setText("song")
    page.header.play_btn.click()
    page.header.shuffle_btn.click()
    assert played == [(["First Song", "Second: Song?"], 0)]
    assert shuffled == [["First Song", "Second: Song?"]]


def test_playlist_view_numbers_by_position_and_can_update(page):
    page.lists.setCurrentRow(0)
    assert page.header.title.text() == "Road Trip"
    assert titles(page) == ["Other Single", "First Song"]
    assert [page.table.item(r, NUM).text() for r in page._track_rows()] == ["1", "2"]
    assert not page.update_btn.isHidden() and page.nav.currentItem() is None
    page.update_btn.click()
    assert page.manager.enqueued == ["PLtest123456"]
    page.nav.setCurrentRow(0)
    assert page.update_btn.isHidden() and page.lists.currentItem() is None


def test_marks_songs_already_on_the_ipod(page):
    assert page.table.isColumnHidden(ON_DEVICE)
    page.set_device_contents("Pod", DeviceContents([DeviceTrack("first song", "The Testers", "Debut")], []))
    assert not page.table.isColumnHidden(ON_DEVICE)
    marked = [page.table.item(r, NAME).text() for r in page._track_rows() if page.table.item(r, ON_DEVICE).text()]
    assert marked == ["First Song"]
    page.set_device_contents("", None)
    assert page.table.isColumnHidden(ON_DEVICE)


def test_recently_added_headings():
    from datetime import date, datetime

    today = date(2026, 10, 21)
    stamp = lambda y, m, d: datetime(y, m, d, 12).timestamp()  # noqa: E731
    assert added_group(stamp(2026, 10, 21), today) == "Today"
    assert added_group(stamp(2026, 10, 20), today) == "Yesterday"
    assert added_group(stamp(2026, 10, 16), today) == "This week"
    assert added_group(stamp(2026, 9, 25), today) == "This month"
    assert "2026" in added_group(stamp(2026, 8, 1), today)


def test_music_videos_and_the_zune(library):
    from types import SimpleNamespace

    QApplication.instance() or QApplication([])
    first = next(t for t in library.tracks() if t.title == "First Song")
    videos = SimpleNamespace(all=lambda: [SimpleNamespace(track_id=first.video_id)])
    page = LibraryPage(library, FakeManager(), videos)
    page.resize(1100, 700)
    page.show()
    nav = {page.nav.item(i).text(): page.nav.item(i) for i in range(page.nav.count())}
    assert not nav["Music videos"].isHidden()
    page.nav.setCurrentItem(nav["Music videos"])
    assert titles(page) == ["First Song"]

    synced = []
    page.zune_sync_requested.connect(synced.append)
    assert page.zune_sync_btn.isHidden()
    page.set_zune_available(True)
    assert not page.zune_sync_btn.isHidden()
    page.table.selectRow(page._track_rows()[0])
    page.zune_sync_btn.click()
    assert synced == [[library.root / first.relpath]]
    dispose(page)

    page = LibraryPage(library, FakeManager(), SimpleNamespace(all=lambda: []))
    assert next(page.nav.item(i) for i in range(page.nav.count())
                if page.nav.item(i).text() == "Music videos").isHidden()
    dispose(page)
