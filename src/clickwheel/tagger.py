"""Write iPod-friendly MP4 tags and choose library file paths."""

from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path

import requests
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from PIL import Image

from .ytm import TrackMeta

ID_ATOM = "----:com.clickwheel:youtube_id"
# FAT32 (every stock iPod) and Windows both reject these in file names.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_component(text: str, limit: int = 100) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _ILLEGAL.sub("_", text).strip().rstrip(". ")
    if text.split(".")[0].upper() in _RESERVED:
        text = "_" + text
    return text[:limit].rstrip(". ") or "_"


def library_relpath(meta: TrackMeta) -> Path:
    artist = safe_component(meta.album_artist or meta.artist)
    album = safe_component(meta.album or "Unknown Album")
    prefix = f"{meta.track_number:02d} " if meta.track_number else ""
    return Path(artist, album, f"{prefix}{safe_component(meta.title, 120)}.m4a")


def fetch_cover(url: str, size: int) -> bytes | None:
    """Download album art as a square JPEG no larger than ``size`` px."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception:
        return None
    # Video thumbnails are 16:9 with the art centred; crop to square.
    w, h = img.size
    if w != h:
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    img.thumbnail((size, size))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def write_tags(path: Path, meta: TrackMeta, cover: bytes | None) -> None:
    audio = MP4(path)
    tags = audio.tags if audio.tags is not None else audio.add_tags() or audio.tags
    tags.clear()
    tags["\xa9nam"] = meta.title
    tags["\xa9ART"] = meta.artist
    tags["aART"] = meta.album_artist or meta.artist
    tags["\xa9alb"] = meta.album or meta.title
    if meta.year:
        tags["\xa9day"] = meta.year
    if meta.track_number:
        tags["trkn"] = [(meta.track_number, meta.track_total or 0)]
    tags["disk"] = [(meta.disc_number or 1, 0)]
    # Lets the iPod sort "The Beatles" under B like iTunes would.
    for sort_key, value in (("soar", meta.artist), ("soaa", meta.album_artist or meta.artist)):
        if value.lower().startswith("the "):
            tags[sort_key] = value[4:]
    tags["rtng"] = [1 if meta.explicit else 0]
    tags[ID_ATOM] = [MP4FreeForm(meta.video_id.encode())]
    if cover:
        tags["covr"] = [MP4Cover(cover, MP4Cover.FORMAT_JPEG)]
    audio.save()


def read_video_id(path: Path) -> str | None:
    try:
        values = MP4(path).tags.get(ID_ATOM)
    except Exception:
        return None
    return bytes(values[0]).decode() if values else None
