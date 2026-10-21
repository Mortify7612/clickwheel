"""Music video lookup and conversion (yt-dlp faked; ffmpeg real)."""

import json
import shutil
import subprocess

import pytest

from clickwheel import video
from clickwheel.library import LibraryTrack
from clickwheel.video import MusicVideos, find_music_video


def _track(artist="System Of A Down", title="Toxicity", duration=219, track_id="trk1"):
    return LibraryTrack(track_id, "x.m4a", title, artist, "Toxicity", artist, 1, "2001", duration)


class FakeYT:
    def __init__(self, results):
        self.results = results

    def search(self, query, filter=None, limit=None):
        assert filter == "videos"
        return self.results


def _r(vid, kind="OMV", title="Toxicity", artists=("System Of A Down",), duration="3:45"):
    return {"videoId": vid, "videoType": f"MUSIC_VIDEO_TYPE_{kind}", "title": title,
            "artists": [{"name": a} for a in artists], "duration": duration}


def test_finds_the_official_video():
    yt = FakeYT([_r("fan", kind="UGC"), _r("cover", artists=("Someone Else",)), _r("omv")])
    assert find_music_video(yt, _track()) == "omv"
    # Two official cuts: the one closest to the song's length.
    yt = FakeYT([_r("long", duration="6:10"), _r("short", duration="3:40")])
    assert find_music_video(yt, _track()) == "short"
    assert find_music_video(FakeYT([_r("x", kind="UGC")]), _track()) is None
    assert find_music_video(FakeYT([_r("x", title="Chop Suey!")]), _track()) is None
    # Featured artists in the library's artist field still match.
    yt = FakeYT([_r("feat", title="Run", artists=("Joji",))])
    assert find_music_video(yt, _track("Joji, Someone", "Run", 276)) == "feat"


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,profile,level,width,height",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"]


def test_fetch_converts_for_the_zune(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required")

    def fake_download(video_id, staging, on_progress=None, cookies=None):
        staging.mkdir(parents=True, exist_ok=True)
        out = staging / f"{video_id}.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-c:v", "libx264", "-c:a", "aac",
                        "-shortest", str(out)], check=True)
        return out

    monkeypatch.setattr(video, "download_video", fake_download)
    store = MusicVideos(tmp_path / "library", tmp_path / "db.sqlite3")
    got = store.fetch(FakeYT([_r("omv")]), _track(), tmp_path / "staging")
    assert got.video_id == "omv" and got.relpath == "Music Videos/System Of A Down/Toxicity.mp4"
    streams = {s["codec_name"]: s for s in _probe(store.path(got))}
    v, a = streams["h264"], streams["aac"]
    assert v["profile"] == "Constrained Baseline" and v["level"] == 30
    assert (v["width"], v["height"]) == (480, 270)  # 16:9 fitted into the 480x272 screen
    assert a["profile"] == "LC"
    assert store.thumb_path(got).read_bytes()[:2] == b"\xff\xd8"
    assert [m.track_id for m in store.all()] == ["trk1"]

    # A song without an official video is remembered, so it isn't searched again.
    assert store.fetch(FakeYT([]), _track("Radiohead", "Weird Fishes", track_id="trk3"), tmp_path / "staging") is None
    assert store.get("trk3").video_id == ""
    calls = []
    yt = FakeYT([])
    yt.search = lambda *a, **k: calls.append(a) or []
    store._save("trk2", "", "")
    assert store.fetch(yt, LibraryTrack("trk2", "y.m4a", "T", "A", "B", "A", 1, "", 1), tmp_path / "s") is None
    assert calls == []

    store.delete("trk1")
    assert store.all() == [] and not (store.root / got.relpath).exists()
