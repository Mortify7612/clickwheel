import io
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from clickwheel.library import Library
from clickwheel.tagger import library_relpath, write_tags
from clickwheel.ytm import TrackMeta


def make_cover() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), (30, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def make_m4a(path: Path, seconds: int, freq: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
         "-c:a", "aac", "-b:a", "96k", str(path)],
        check=True,
    )


SONGS = [
    TrackMeta("aaaaaaaaaa1", "First Song", ["The Testers"], "Debut", "The Testers", "MPREb_x", 1, 3, 1, "2021", 4),
    TrackMeta("aaaaaaaaaa2", "Second: Song?", ["The Testers", "Guest"], "Debut", "The Testers", "MPREb_x", 2, 3, 1, "2021", 5),
    TrackMeta("bbbbbbbbbb1", "Other Single", ["Solo Act"], "Single", "Solo Act", "MPREb_y", 1, 1, 1, "2023", 6),
]


@pytest.fixture
def library(tmp_path) -> Library:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required")
    lib = Library(tmp_path / "library", tmp_path / "db.sqlite3")
    cover = make_cover()
    for i, meta in enumerate(SONGS):
        rel = library_relpath(meta)
        make_m4a(lib.root / rel, meta.duration, 300 + 100 * i)
        write_tags(lib.root / rel, meta, cover)
        lib.add_track(meta, rel)
    lib.save_playlist("PLtest123456", "Road Trip", "playlist", "", [SONGS[2].video_id, SONGS[0].video_id])
    return lib
