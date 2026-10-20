"""Audio downloads via yt-dlp."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import yt_dlp

ProgressFn = Callable[[float], None]


class DownloadError(Exception):
    pass


def _js_runtimes() -> dict[str, dict]:
    """yt-dlp needs a JS runtime to solve YouTube's player challenges.

    The ``deno`` wheel ships a binary for every desktop platform, so prefer it
    and fall back to whatever the user has installed.
    """
    bundle = getattr(sys, "_MEIPASS", None)  # PyInstaller app: deno is shipped alongside
    if bundle:
        bundled = Path(bundle) / ("deno.exe" if sys.platform == "win32" else "deno")
        if bundled.is_file():
            return {"deno": {"path": str(bundled)}}
    try:
        import deno

        return {"deno": {"path": deno.find_deno_bin()}}
    except Exception:
        pass
    for name in ("deno", "node", "bun", "quickjs"):
        if path := shutil.which("qjs" if name == "quickjs" else name):
            return {name: {"path": path}}
    return {}


def ffmpeg_location() -> str | None:
    if path := shutil.which("ffmpeg"):
        return path
    try:  # pyPodLib can fetch a static ffmpeg build on Windows/macOS.
        from pypodlib.sync.dependency_manager import download_ffmpeg, get_bundled_ffmpeg

        return get_bundled_ffmpeg() or download_ffmpeg()
    except Exception:
        return None


def download_audio(video_id: str, staging: Path, on_progress: ProgressFn | None = None,
                   cookies: str | None = None) -> Path:
    """Download one track as AAC/M4A into ``staging`` and return the file path.

    YouTube serves AAC in an MP4 container (128 kbps, or 256 kbps for Premium
    sessions), which every iPod plays natively, so no re-encoding is needed in
    the common case.
    """
    staging.mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        if on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                on_progress(min(d.get("downloaded_bytes", 0) / total, 1.0))

    opts: dict = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(staging / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "js_runtimes": _js_runtimes(),
        "overwrites": True,
        # Only kicks in when no AAC stream exists (e.g. some uploads are Opus-only).
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "256"}],
    }
    if cookies:
        opts["cookiefile"] = cookies
    if ffmpeg := ffmpeg_location():
        opts["ffmpeg_location"] = ffmpeg

    url = f"https://music.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc).removeprefix("ERROR: ")) from exc

    out = staging / f"{video_id}.m4a"
    if not out.exists():
        raise DownloadError("yt-dlp finished but produced no M4A file")
    return out
