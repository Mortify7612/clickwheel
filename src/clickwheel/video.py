"""Music videos: find a song's official video on YouTube Music, download it and
convert it to what a Zune HD plays (also used for video podcast episodes)."""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .downloader import DownloadError, _js_runtimes, ffmpeg_location
from .library import LibraryTrack
from .tagger import safe_component

ProgressFn = Callable[[float], None]

VIDEOS_DIR = "Music Videos"

# H.264 Constrained Baseline at the Zune HD's 480x272 screen with AAC audio:
# within every published Zune HD limit, and confirmed to play on one.
ZUNE_VIDEO_ARGS = [
    "-vf", "scale=480:272:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30",
    "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0", "-pix_fmt", "yuv420p",
    "-b:v", "1000k", "-maxrate", "1500k", "-bufsize", "2000k",
    "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart",
]


def _ffmpeg() -> str:
    path = ffmpeg_location()
    if path and Path(path).is_dir():
        path = str(Path(path) / "ffmpeg")
    if not path:
        raise DownloadError("ffmpeg is needed to convert videos")
    return path


def zune_video(src: Path, dst: Path) -> Path:
    """Convert ``src`` into an MP4 a Zune HD plays."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part.mp4")
    result = subprocess.run([_ffmpeg(), "-loglevel", "error", "-y", "-i", str(src), *ZUNE_VIDEO_ARGS, str(tmp)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"Couldn't convert the video: {result.stderr.strip()[-300:]}")
    tmp.replace(dst)
    return dst


def thumbnail(video: Path, dst: Path, at_seconds: float = 30) -> Path | None:
    """A JPEG frame from ``video`` (the Zune shows it in its video list)."""
    for seek in (at_seconds, 0):
        result = subprocess.run([_ffmpeg(), "-loglevel", "error", "-y", "-ss", str(seek), "-i", str(video),
                                 "-frames:v", "1", "-q:v", "3", str(dst)], capture_output=True)
        if result.returncode == 0 and dst.exists() and dst.stat().st_size:
            return dst
    return None


def video_duration_ms(path: Path) -> int:
    probe = shutil.which("ffprobe") or str(Path(_ffmpeg()).with_name("ffprobe"))
    try:
        out = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, check=True).stdout
        return int(float(out.strip()) * 1000)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return 0


def _seconds(text: str | None) -> int:
    parts = [int(p) for p in re.findall(r"\d+", text or "")]
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def find_music_video(yt, track: LibraryTrack) -> str | None:
    """The YouTube id of ``track``'s official music video, or None if it has none.

    Only "official music video" results by the same artist with the same
    title count; with several (a short and an extended cut), the one closest
    to the song's length wins.
    """
    results = yt.search(f"{track.artist} {track.title}", filter="videos", limit=10)
    artist, title = _norm(track.artist.split(",")[0]), _norm(track.title)
    candidates = []
    for r in results:
        if r.get("videoType") != "MUSIC_VIDEO_TYPE_OMV" or not r.get("videoId"):
            continue
        names = [_norm(a.get("name", "")) for a in r.get("artists") or []]
        if not any(artist and (artist in n or n in artist) for n in names if n):
            continue
        if title not in _norm(r.get("title", "")):
            continue
        candidates.append((abs(_seconds(r.get("duration")) - track.duration), r["videoId"]))
    return min(candidates)[1] if candidates else None


def download_video(video_id: str, staging: Path, on_progress: ProgressFn | None = None,
                   cookies: str | None = None) -> Path:
    """Download a YouTube video (at most 720p) as an MP4 into ``staging``."""
    import yt_dlp

    staging.mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        if on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                on_progress(min(d.get("downloaded_bytes", 0) / total, 1.0))

    opts: dict = {
        "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
        "merge_output_format": "mp4",
        "outtmpl": str(staging / "%(id)s.%(ext)s"),
        "noplaylist": True, "quiet": True, "no_warnings": True, "noprogress": True,
        "progress_hooks": [hook], "js_runtimes": _js_runtimes(), "overwrites": True,
    }
    if cookies:
        opts["cookiefile"] = cookies
    if ffmpeg := ffmpeg_location():
        opts["ffmpeg_location"] = ffmpeg
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc).removeprefix("ERROR: ")) from exc
    out = next(staging.glob(f"{video_id}.*"), None)
    if out is None:
        raise DownloadError("yt-dlp finished but produced no video file")
    return out


# ── Which library songs have a music video ─────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS music_videos (
    track_id  TEXT PRIMARY KEY,   -- library track video_id
    video_id  TEXT NOT NULL,      -- '' when the song has no official video
    relpath   TEXT NOT NULL DEFAULT '',
    checked_at REAL NOT NULL
);
"""


@dataclass
class MusicVideo:
    track_id: str
    video_id: str
    relpath: str


class MusicVideos:
    def __init__(self, root: Path, db_path: Path):
        self.root = root
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.executescript(SCHEMA)

    def get(self, track_id: str) -> MusicVideo | None:
        with self._lock:
            row = self._db.execute("SELECT track_id, video_id, relpath FROM music_videos WHERE track_id = ?",
                                   (track_id,)).fetchone()
        return MusicVideo(*row) if row else None

    def all(self) -> list[MusicVideo]:
        """Downloaded music videos whose files still exist."""
        with self._lock:
            rows = self._db.execute("SELECT track_id, video_id, relpath FROM music_videos WHERE relpath != ''").fetchall()
        return [MusicVideo(*r) for r in rows if (self.root / r[2]).exists()]

    def path(self, video: MusicVideo) -> Path:
        return self.root / video.relpath

    def thumb_path(self, video: MusicVideo) -> Path:
        return (self.root / video.relpath).with_suffix(".jpg")

    def _save(self, track_id: str, video_id: str, relpath: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO music_videos VALUES (?,?,?,?)",
                             (track_id, video_id, relpath, time.time()))

    def fetch(self, yt, track: LibraryTrack, staging: Path, *, on_progress: ProgressFn | None = None,
              cookies: str | None = None) -> MusicVideo | None:
        """Find, download and convert ``track``'s music video; None if it has none."""
        known = self.get(track.video_id)
        if known and (not known.video_id or (known.relpath and (self.root / known.relpath).exists())):
            return known if known.video_id else None
        video_id = find_music_video(yt, track)
        if video_id is None:
            self._save(track.video_id, "", "")
            return None
        source = download_video(video_id, staging / video_id, on_progress, cookies)
        rel = Path(VIDEOS_DIR, safe_component(track.artist.split(",")[0]), f"{safe_component(track.title, 120)}.mp4")
        dest = zune_video(source, self.root / rel)
        thumbnail(dest, dest.with_suffix(".jpg"))
        shutil.rmtree(staging / video_id, ignore_errors=True)
        self._save(track.video_id, video_id, rel.as_posix())
        return self.get(track.video_id)

    def delete(self, track_id: str) -> None:
        video = self.get(track_id)
        if video and video.relpath:
            path = self.root / video.relpath
            path.unlink(missing_ok=True)
            path.with_suffix(".jpg").unlink(missing_ok=True)
        with self._lock, self._db:
            self._db.execute("DELETE FROM music_videos WHERE track_id = ?", (track_id,))
