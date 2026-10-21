"""Podcast subscriptions, feeds and downloads (no network: HTTP and yt-dlp are faked)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from clickwheel import podcasts
from clickwheel.podcasts import Podcasts, parse_feed, parse_subscription

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
  <title>Test Talk</title>
  <itunes:author>Ada Host</itunes:author>
  <description>A show about &lt;b&gt;tests&lt;/b&gt;.</description>
  <itunes:image href="https://example.com/cover.jpg"/>
  <item>
    <title>Older episode</title>
    <guid>ep-1</guid>
    <pubDate>Wed, 01 Oct 2026 09:00:00 +0000</pubDate>
    <itunes:duration>62:03</itunes:duration>
    <description>Plain notes.</description>
    <enclosure url="https://example.com/ep1.mp3" type="audio/mpeg" length="1"/>
  </item>
  <item>
    <title>Newest episode</title>
    <guid>ep-2</guid>
    <pubDate>Wed, 15 Oct 2026 09:00:00 +0000</pubDate>
    <itunes:duration>1:02:03</itunes:duration>
    <content:encoded><![CDATA[<p>First paragraph.</p><p>Second &amp; last.</p>]]></content:encoded>
    <enclosure url="https://example.com/ep2.mp3" type="audio/mpeg" length="1"/>
  </item>
  <item>
    <title>Video special</title>
    <guid>ep-v</guid>
    <pubDate>Mon, 06 Oct 2026 09:00:00 +0000</pubDate>
    <enclosure url="https://example.com/special.mp4" type="video/mp4" length="1"/>
  </item>
  <item><title>No enclosure, skipped</title><guid>ep-x</guid></item>
</channel>
</rss>"""


def test_parse_feed():
    show = parse_feed(FEED)
    assert (show.title, show.author, show.cover_url) == ("Test Talk", "Ada Host", "https://example.com/cover.jpg")
    assert show.description == "A show about tests."
    assert [e.title for e in show.episodes] == ["Newest episode", "Video special", "Older episode"]
    newest, video, older = show.episodes
    assert newest.duration == 3723 and older.duration == 3723
    assert newest.description == "First paragraph.\n\nSecond & last."
    assert video.video and not newest.video
    assert newest.published > older.published > 0
    with pytest.raises(ValueError):
        parse_feed(b"<html><body>not a feed</body></html>")


def test_parse_subscription():
    assert parse_subscription("https://feeds.example.com/show.xml") == ("rss", "https://feeds.example.com/show.xml")
    assert parse_subscription("https://music.youtube.com/playlist?list=PLrAXtmErZgOdP_8GztsuKi9nrraNbKKp4") == (
        "ytm", "PLrAXtmErZgOdP_8GztsuKi9nrraNbKKp4")
    assert parse_subscription("https://music.youtube.com/browse/MPSPPLrAXtmErZgOdP_8GztsuKi9nrraNbKKp4") == (
        "ytm", "PLrAXtmErZgOdP_8GztsuKi9nrraNbKKp4")
    assert parse_subscription("MPSPPLrAXtmErZgOdP_8GztsuKi9nrraNbKKp4")[0] == "ytm"
    for bad in ("", "hello", "https://www.youtube.com/watch?v=abc"):
        with pytest.raises(ValueError):
            parse_subscription(bad)


def test_durations():
    assert podcasts._duration("3 hr 36 min") == 3 * 3600 + 36 * 60
    assert podcasts._duration("45 min") == 2700
    assert podcasts._duration("3723") == 3723
    assert podcasts._duration("") == 0


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.headers = {"content-length": str(len(content))}

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]


@pytest.fixture
def store(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required")
    mp3 = tmp_path / "tone.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:a", "libmp3lame", "-b:a", "64k", str(mp3)], check=True)
    files = {"https://example.com/feed.xml": FEED, "https://example.com/ep1.mp3": mp3.read_bytes(),
             "https://example.com/ep2.mp3": mp3.read_bytes()}
    monkeypatch.setattr(podcasts, "http_get", lambda url, **kw: FakeResponse(files[url]))
    monkeypatch.setattr("clickwheel.tagger.fetch_cover", lambda url, size: None)
    store = Podcasts(tmp_path / "library", tmp_path / "db.sqlite3")
    store.files = files
    return store


def test_subscribe_refresh_and_download(store, tmp_path):
    show = store.subscribe("https://example.com/feed.xml")
    assert show.title == "Test Talk" and show.keep == podcasts.DEFAULT_KEEP
    assert store.subscribe("https://example.com/feed.xml").id == show.id  # subscribing twice is harmless
    eps = store.episodes(show.id)
    assert [e.title for e in eps] == ["Newest episode", "Video special", "Older episode"]
    # Newest three, minus nothing: all of them; the video one too.
    assert [e.title for e in store.to_download(show.id)] == [e.title for e in eps]

    newest = store.download(eps[0].id, tmp_path / "staging")
    path = store.path(newest)
    assert path.relative_to(store.root).parts[:2] == ("Podcasts", "Test Talk")
    assert path.name == "2026-10-15 Newest episode.mp3"
    from mutagen.id3 import ID3

    tags = ID3(path)
    assert tags.version[:2] == (2, 3)  # the Zune ignores ID3v2.4
    assert str(tags["TIT2"]) == "Newest episode" and str(tags["TALB"]) == "Test Talk"
    assert str(tags["TPE1"]) == "Ada Host" and str(tags["TCON"]) == "Podcast"
    assert tags.getall("COMM")[0].text[0] == "First paragraph.\n\nSecond & last."  # where the Zune reads it
    assert str(tags["TIT3"]).startswith("First paragraph.")

    store.set_position(newest.id, 61000)
    store.set_played(eps[2].id)
    store.files["https://example.com/feed.xml"] = FEED.replace(b"<item>", b"""<item>
    <title>Brand new</title><guid>ep-3</guid><pubDate>Mon, 20 Oct 2026 09:00:00 +0000</pubDate>
    <enclosure url="https://example.com/ep2.mp3" type="audio/mpeg" length="1"/></item><item>""", 1)
    new = store.refresh(show.id)
    assert [e.title for e in new] == ["Brand new"]
    kept = store.episode(newest.id)
    assert kept.downloaded and kept.position == 61000  # refreshing keeps what we knew
    assert store.episode(eps[2].id).played
    assert [e.title for e in store.to_download(show.id)] == ["Brand new", "Video special"]

    store.delete_download(newest.id)
    assert not store.episode(newest.id).downloaded and not path.exists()
    store.unsubscribe(show.id)
    assert store.podcasts() == [] and store.episodes() == []


def test_youtube_music_show(store, tmp_path, monkeypatch):
    class FakeYT:
        def get_podcast(self, playlist_id, limit=None):
            assert playlist_id == "PLshow1234567"
            return {"title": "Tube Talk", "author": {"name": "Tube Host"}, "description": "About tubes.",
                    "thumbnails": [{"url": "https://example.com/small.jpg"}, {"url": "https://example.com/big.jpg"}],
                    "episodes": [{"videoId": "vid2", "title": "Second", "description": "Two", "date": "1.2M views",
                                  "duration": "1 hr 5 min"},
                                 {"videoId": "vid1", "title": "First", "description": "One", "date": "Oct 1, 2026",
                                  "duration": "45 min"}]}

    tone = Path(store.root.parent / "tone.mp3")

    def fake_download(video_id, staging, on_progress=None, cookies=None, info=None):
        out = staging / f"{video_id}.m4a"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(tone), "-c:a", "aac", str(out)], check=True)
        info.update({"upload_date": "20261012", "description": "From yt-dlp"})
        return out

    monkeypatch.setattr(podcasts, "download_audio", fake_download)
    show = store.subscribe("https://music.youtube.com/playlist?list=PLshow1234567", yt=FakeYT())
    assert (show.kind, show.title, show.author, show.cover_url) == ("ytm", "Tube Talk", "Tube Host",
                                                                   "https://example.com/big.jpg")
    second, first = store.episodes(show.id)
    assert (second.duration, second.published) == (3900, 0) and first.published > 0  # a view count isn't a date
    done = store.download(second.id, tmp_path / "staging")
    assert store.path(done).name == "2026-10-12 Second.m4a"  # date from yt-dlp
    from mutagen.mp4 import MP4

    tags = MP4(store.path(done))
    assert tags["\xa9alb"] == ["Tube Talk"] and tags["desc"] == ["Two"] and tags["ldes"] == ["Two"]
    assert tags["pcst"] is True
