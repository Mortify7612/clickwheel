import os
import time

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from clickwheel import auth  # noqa: E402
from clickwheel.gui import workers, ytm_page  # noqa: E402
from clickwheel.gui.ytm_page import NOTE, STATE, YtmPage  # noqa: E402
from clickwheel.pipeline import Status, TrackEvent  # noqa: E402
from clickwheel.ytm import Card, Collection, Listing, Page, PlaylistRef, TrackMeta  # noqa: E402

OWNED = "aaaaaaaaaa1"  # "First Song" in the test library


class FakeResolver:
    def search(self, query, kind):
        if kind == "songs":
            return [Listing(OWNED, "First Song", ["The Testers"], "Debut", 4),
                    Listing("newsong0001", "Brand New", ["Someone"], "Fresh", 200)]
        return [Card("album", "MPREb_new", "Fresh", "Someone · Album · 2026")] if kind == "albums" else []

    def album_page(self, browse_id):
        return Page("album", browse_id, "Fresh", "Someone", "", [
            Listing("newsong0001", "Brand New", ["Someone"], "Fresh", 200),
            Listing("newsong0002", "Also New", ["Someone"], "Fresh", 180)],
            url=f"https://music.youtube.com/browse/{browse_id}")

    def playlist_page(self, pid):
        return Page("playlist", pid, "Road Trip", "me", "", [
            Listing("bbbbbbbbbb1", "Other Single", ["Solo Act"], "Single", 6),
            Listing(OWNED, "First Song", ["The Testers"], "Debut", 4),
            Listing("newsong0003", "Added Later", ["Solo Act"], "Single", 100)],
            url=f"https://music.youtube.com/playlist?list={pid}")

    def library_playlists(self):
        return [PlaylistRef("PLtest123456", "Road Trip", 3), PlaylistRef("PLother", "Not Mine Yet", 5)]


class FakeManager(QObject):
    queued = Signal(int, str)
    resolving = Signal(str)
    started = Signal(int, object)
    track_event = Signal(int, object)
    finished = Signal(int, object, object)
    error = Signal(int, str, str)
    library_changed = Signal()
    idle = Signal()

    def __init__(self, library):
        super().__init__()
        self.library = library
        self.jobs = 0
        self.queue = []

    def new_job(self):
        self.jobs += 1
        return self.jobs

    def enqueue_url(self, url, profile_id=None, job=None):
        job = job or self.new_job()
        self.queue.append(url)
        self.queued.emit(job, url)
        return job

    def enqueue_playlist(self, pid, title, profile_id=None, job=None):
        return self.enqueue_url(f"playlist:{pid}", job=job)

    def resolver(self, profile):
        return FakeResolver()

    def cancel(self):
        pass


class Profile:
    id, label = "me", "Me (@me)"


def wait_for(condition, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


@pytest.fixture
def page(library, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(auth, "profiles", lambda: [Profile()])
    monkeypatch.setattr(auth, "active_profile", lambda: Profile())
    monkeypatch.setattr(ytm_page.RemoteArt, "load_png", lambda self: None)  # no network for covers
    page = YtmPage(FakeManager(library), type("Bar", (), {"showMessage": lambda *a: None})())
    page.resize(1100, 700)
    page.show()
    wait_for(lambda: page.lists.count() == 2)
    yield page
    page.close()
    page.covers.shutdown()  # let cover threads finish before the page goes
    wait_for(lambda: not workers.Task._alive)  # and background lookups
    QApplication.processEvents()
    shiboken6.delete(page)  # now, not whenever Python gets round to it (at exit, Qt may be half gone)


def states(page):
    return [page.songs.item(r, STATE).text() for r in range(page.songs.rowCount())]


def test_words_search_and_links_download():
    assert not YtmPage._links_only("radiohead")
    assert not YtmPage._links_only("radioheadxx")  # 11 characters: not taken for a video id
    assert YtmPage._links_only("https://music.youtube.com/watch?v=aaaaaaaaaa1")
    assert not YtmPage._links_only("https://music.youtube.com/watch?v=aaaaaaaaaa1 and words")


def test_playlists_show_what_is_missing(page):
    notes = {page.lists.item(i).text(): page.lists.item(i).data(NOTE) for i in range(page.lists.count())}
    assert notes == {"Road Trip": "1 new", "Not Mine Yet": ""}  # 3 on YouTube Music, 2 downloaded
    page._list_clicked(page.lists.item(0))
    wait_for(lambda: page.songs.rowCount() == 3)
    assert states(page) == ["✓ In library", "✓ In library", ""]
    assert page.get_btn.text() == "Download 1 new"
    page.get_btn.click()
    assert page.manager.queue == ["playlist:PLtest123456"] and page.get_btn.text() == "Queued…"


def test_search_open_album_and_download(page):
    page.search.setText("someone")
    page._submit()
    wait_for(lambda: page.songs.rowCount() == 2)
    assert states(page) == ["✓ In library", ""]
    page._show_search_kind("albums")
    wait_for(lambda: page.grid.count() == 1)
    page.grid.opened.emit("album:MPREb_new")
    wait_for(lambda: page._page is not None and page._page.id == "MPREb_new")  # (the title shows while loading)
    assert "Search results" in page.header.back.text()
    assert page.get_btn.text() == "Download album"
    page.get_btn.click()
    assert page.manager.queue == ["https://music.youtube.com/browse/MPREb_new"]
    # The download runs: rows follow it, then the button settles.
    job = page.manager.jobs
    tracks = [TrackMeta("newsong0001", "Brand New", ["Someone"]), TrackMeta("newsong0002", "Also New", ["Someone"])]
    page.manager.started.emit(job, Collection("MPREb_new", "Someone - Fresh", "album", tracks))
    page.manager.track_event.emit(job, TrackEvent(0, tracks[0], Status.DOWNLOADING, 0.5))
    page.manager.track_event.emit(job, TrackEvent(1, tracks[1], Status.FAILED, error="403"))
    assert states(page) == ["Downloading 50%", "Failed"]
    assert page.nav.item(1).data(NOTE) == "1 / 2"
    page.manager.track_event.emit(job, TrackEvent(0, tracks[0], Status.DONE, 1.0))
    page.manager.finished.emit(job, Collection("MPREb_new", "Someone - Fresh", "album", tracks), {Status.DONE: 1})
    assert states(page) == ["✓ In library", "Failed"]
    assert page.get_btn.text() == "Download 1 new"
    page._on_link("back")
    assert page._view == ("search", "someone")


def test_pasting_a_link_queues_it(page, monkeypatch):
    link = "https://music.youtube.com/watch?v=newsong0009"
    monkeypatch.setattr(QApplication.clipboard(), "text", lambda *a: link)
    page.search.setText(link)
    page.search.textEdited.emit(link)
    assert page.manager.queue == [link]
    assert page._view == ("downloads",) and page.search.text() == ""
    assert page.table.rowCount() == 1  # the job's heading, until it starts
