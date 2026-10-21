"""Podcast subscriptions (YouTube Music shows and RSS feeds), their episodes and downloads.

Episodes are filed under ``<library>/Podcasts/<Show>/`` with the show,
author, date and description in their tags; a Zune shows an audio episode's
description only from the file's own tags.
"""

from __future__ import annotations

import email.utils
import hashlib
import html
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .downloader import DownloadError, download_audio
from .tagger import safe_component

ProgressFn = Callable[[float], None]

PODCASTS_DIR = "Podcasts"
DEFAULT_KEEP = 3  # newest episodes downloaded automatically
AUDIO_KEEP = {".mp3", ".m4a", ".aac"}  # played by iPods and Zunes as they are
VIDEO_EXTS = {".mp4", ".m4v", ".mov"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS podcasts (
    id          TEXT PRIMARY KEY,     -- "ytm:<playlist id>" or "rss:<hash of the feed URL>"
    kind        TEXT NOT NULL,        -- "ytm" | "rss"
    source      TEXT NOT NULL,        -- playlist id or feed URL
    title       TEXT NOT NULL,
    author      TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    cover_url   TEXT NOT NULL DEFAULT '',
    keep        INTEGER NOT NULL DEFAULT 3,
    added_at    REAL NOT NULL,
    refreshed_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS episodes (
    id          TEXT PRIMARY KEY,     -- podcast id + "|" + guid
    podcast_id  TEXT NOT NULL REFERENCES podcasts(id) ON DELETE CASCADE,
    guid        TEXT NOT NULL,
    seq         INTEGER NOT NULL,     -- position in the feed, 0 = newest
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    published   REAL NOT NULL DEFAULT 0,   -- unix time, 0 if unknown
    duration    INTEGER NOT NULL DEFAULT 0,  -- seconds
    media       TEXT NOT NULL DEFAULT '',  -- enclosure URL, or the YouTube video id
    video       INTEGER NOT NULL DEFAULT 0,
    relpath     TEXT NOT NULL DEFAULT '',  -- downloaded file under the library root
    position    INTEGER NOT NULL DEFAULT 0,  -- resume point, milliseconds
    played      INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class EpisodeInfo:
    guid: str
    title: str
    description: str = ""
    published: float = 0
    duration: int = 0
    media: str = ""
    video: bool = False


@dataclass
class ShowInfo:
    title: str
    author: str = ""
    description: str = ""
    cover_url: str = ""
    episodes: list[EpisodeInfo] = field(default_factory=list)


@dataclass
class Podcast:
    id: str
    kind: str
    source: str
    title: str
    author: str
    description: str
    cover_url: str
    keep: int
    added_at: float
    refreshed_at: float


@dataclass
class Episode:
    id: str
    podcast_id: str
    guid: str
    seq: int
    title: str
    description: str
    published: float
    duration: int
    media: str
    video: bool
    relpath: str
    position: int
    played: bool

    @property
    def downloaded(self) -> bool:
        return bool(self.relpath)


# ── Parsing ────────────────────────────────────────────────────────────────────

class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "div"):
            self.parts.append("\n\n")
        elif tag in ("br", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(text: str) -> str:
    """Show notes are often HTML; the Zune and the tags want plain text."""
    if "<" not in text:
        return html.unescape(text).strip()
    parser = _Text()
    parser.feed(text)
    return re.sub(r"\n[ \t]*(\n[ \t]*)+", "\n\n", "".join(parser.parts)).strip()


def _duration(text: str | None) -> int:
    """Seconds from "1:02:03", "62:03", "3723" or "3 hr 36 min"."""
    text = (text or "").strip()
    if not text:
        return 0
    if units := re.findall(r"(\d+)\s*(hr|hour|min|sec|s)\b", text):
        scale = {"hr": 3600, "hour": 3600, "min": 60, "sec": 1, "s": 1}
        return sum(int(n) * scale[u] for n, u in units)
    total = 0
    for part in re.findall(r"\d+", text)[-3:]:
        total = total * 60 + int(part)
    return total


def _date(text: str | None) -> float:
    try:
        return email.utils.parsedate_to_datetime(text).timestamp() if text else 0
    except (TypeError, ValueError):
        return 0


ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


def parse_feed(xml: bytes) -> ShowInfo:
    """A podcast's RSS feed (RSS 2.0 with iTunes tags)."""
    try:
        channel = ET.fromstring(xml).find("channel")
    except ET.ParseError as exc:
        raise ValueError(f"That isn't a podcast feed ({exc})") from exc
    if channel is None:
        raise ValueError("That isn't a podcast feed (no RSS channel)")

    def text(node, *tags) -> str:
        for tag in tags:
            found = node.find(tag)
            if found is not None and (found.text or "").strip():
                return found.text.strip()
        return ""

    image = channel.find(f"{ITUNES}image")
    cover = image.get("href", "") if image is not None else text(channel, "image/url")
    show = ShowInfo(title=text(channel, "title") or "Untitled podcast",
                    author=text(channel, f"{ITUNES}author", "managingEditor"),
                    description=plain_text(text(channel, f"{ITUNES}summary", "description")), cover_url=cover)
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        if enclosure is None or not enclosure.get("url"):
            continue
        url = enclosure.get("url")
        kind = enclosure.get("type", "")
        video = kind.startswith("video/") or Path(urlparse(url).path).suffix.lower() in VIDEO_EXTS
        show.episodes.append(EpisodeInfo(
            guid=text(item, "guid") or url, title=text(item, "title") or "Untitled episode",
            description=plain_text(text(item, f"{CONTENT}encoded", f"{ITUNES}summary", "description")),
            published=_date(text(item, "pubDate")), duration=_duration(text(item, f"{ITUNES}duration")),
            media=url, video=video))
    show.episodes.sort(key=lambda e: e.published, reverse=True)
    return show


def ytm_show(yt, playlist_id: str) -> ShowInfo:
    """A YouTube Music podcast; episodes are YouTube videos (downloaded as audio)."""
    data = yt.get_podcast(playlist_id, limit=None)
    author = data.get("author") or {}
    thumbs = data.get("thumbnails") or []
    show = ShowInfo(title=data.get("title") or "Untitled podcast",
                    author=author.get("name", "") if isinstance(author, dict) else str(author),
                    description=plain_text(data.get("description") or ""),
                    cover_url=thumbs[-1]["url"] if thumbs else "")
    for ep in data.get("episodes") or []:
        if not ep.get("videoId"):
            continue
        show.episodes.append(EpisodeInfo(
            guid=ep["videoId"], title=ep.get("title") or "Untitled episode",
            description=plain_text(ep.get("description") or ""), published=_ytm_date(ep.get("date")),
            duration=_duration(ep.get("duration")), media=ep["videoId"]))
    return show


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                        "dec"), start=1)}


def _ytm_date(text: str | None) -> float:
    """YouTube Music shows "Oct 15, 2026" (or a view count, which isn't a date).

    Parsed by hand: strptime's %b follows the locale, which Qt sets from the
    desktop (so it would expect e.g. Vietnamese month names).
    """
    match = re.fullmatch(r"([A-Za-z]{3})[a-z]*\.? (\d{1,2}), (\d{4})", (text or "").strip())
    if not match or match.group(1).lower() not in _MONTHS:
        return 0
    month, day, year = _MONTHS[match.group(1).lower()], int(match.group(2)), int(match.group(3))
    return time.mktime((year, month, day, 0, 0, 0, 0, 0, -1))


def parse_subscription(text: str) -> tuple[str, str]:
    """("ytm", playlist id) for a YouTube Music podcast link or id, else ("rss", feed URL)."""
    text = text.strip()
    if not text:
        raise ValueError("Paste a podcast's RSS feed URL or YouTube Music link")
    url = urlparse(text)
    if url.scheme in ("http", "https") and "youtube.com" not in url.netloc:
        return "rss", text
    if url.scheme in ("http", "https"):
        query = parse_qs(url.query)
        if "list" in query:
            return "ytm", query["list"][0]
        last = url.path.rstrip("/").rsplit("/", 1)[-1]
        if last.startswith("MPSP"):
            return "ytm", last[4:]
        raise ValueError("That YouTube link isn't a podcast; open the podcast on music.youtube.com and copy its link")
    if text.startswith("MPSP"):
        return "ytm", text[4:]
    if re.fullmatch(r"(PL|OLAK)[\w-]{10,}", text):
        return "ytm", text
    raise ValueError("Paste a podcast's RSS feed URL or YouTube Music link")


def podcast_id(kind: str, source: str) -> str:
    return f"ytm:{source}" if kind == "ytm" else "rss:" + hashlib.sha1(source.encode()).hexdigest()[:16]


# ── Tags ────────────────────────────────────────────────────────────────────────

def tag_episode(path: Path, podcast: Podcast, episode: Episode, cover: bytes | None) -> None:
    year = time.strftime("%Y-%m-%d", time.localtime(episode.published)) if episode.published else ""
    artist = podcast.author or podcast.title
    if path.suffix.lower() == ".mp3":
        from mutagen.id3 import APIC, COMM, ID3, TALB, TCON, TDRC, TIT2, TIT3, TPE1, ID3NoHeaderError

        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("COMM")
        for frame in (TIT2(encoding=1, text=episode.title), TPE1(encoding=1, text=artist),
                      TALB(encoding=1, text=podcast.title), TCON(encoding=1, text="Podcast"),
                      TIT3(encoding=1, text=episode.description[:1000]),
                      COMM(encoding=1, lang="eng", desc="", text=episode.description)):
            tags.setall(frame.FrameID, [frame])
        if year:
            tags.setall("TDRC", [TDRC(encoding=1, text=year[:4])])
        if cover:
            tags.setall("APIC", [APIC(encoding=0, mime="image/jpeg", type=3, desc="", data=cover)])
        tags.save(path, v2_version=3)  # the Zune ignores ID3v2.4
        return
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(path)
    tags = audio.tags if audio.tags is not None else audio.add_tags() or audio.tags
    tags["\xa9nam"] = episode.title
    tags["\xa9ART"] = artist
    tags["\xa9alb"] = podcast.title
    tags["\xa9gen"] = "Podcast"
    for key in ("desc", "\xa9des", "ldes"):  # short, iTunes and long description
        tags[key] = episode.description
    if year:
        tags["\xa9day"] = year
    tags["pcst"] = True
    tags["stik"] = [21]  # media kind: podcast
    if cover:
        tags["covr"] = [MP4Cover(cover, MP4Cover.FORMAT_JPEG)]
    audio.save()


# ── Store ─────────────────────────────────────────────────────────────────────

def http_get(url: str, *, stream: bool = False, timeout: int = 30):
    import requests

    response = requests.get(url, stream=stream, timeout=timeout, headers={"User-Agent": "Clickwheel podcasts"})
    response.raise_for_status()
    return response


class Podcasts:
    def __init__(self, root: Path, db_path: Path):
        self.root = root
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)

    # -- queries -------------------------------------------------------------------

    def podcasts(self) -> list[Podcast]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM podcasts ORDER BY title COLLATE NOCASE").fetchall()
        return [Podcast(*r) for r in rows]

    def podcast(self, pid: str) -> Podcast | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM podcasts WHERE id = ?", (pid,)).fetchone()
        return Podcast(*row) if row else None

    def episodes(self, pid: str | None = None, *, downloaded: bool = False) -> list[Episode]:
        query, args = "SELECT * FROM episodes", []
        clauses = []
        if pid is not None:
            clauses.append("podcast_id = ?")
            args.append(pid)
        if downloaded:
            clauses.append("relpath != ''")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self._lock:
            rows = self._db.execute(query + " ORDER BY podcast_id, seq", args).fetchall()
        return [Episode(*r) for r in rows]

    def episode(self, eid: str) -> Episode | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM episodes WHERE id = ?", (eid,)).fetchone()
        return Episode(*row) if row else None

    def episode_at(self, path: Path) -> Episode | None:
        """The downloaded episode stored at ``path``, if it is one."""
        try:
            rel = Path(path).relative_to(self.root).as_posix()
        except ValueError:
            return None
        with self._lock:
            row = self._db.execute("SELECT * FROM episodes WHERE relpath = ?", (rel,)).fetchone()
        return Episode(*row) if row else None

    def path(self, episode: Episode) -> Path:
        return self.root / episode.relpath

    def show_dir(self, podcast: Podcast) -> Path:
        return self.root / PODCASTS_DIR / safe_component(podcast.title)

    def cover(self, podcast: Podcast) -> bytes | None:
        try:
            return (self.show_dir(podcast) / "cover.jpg").read_bytes()
        except OSError:
            return None

    # -- subscribing -----------------------------------------------------------------

    def fetch_show(self, kind: str, source: str, yt=None) -> ShowInfo:
        if kind == "ytm":
            if yt is None:
                from ytmusicapi import YTMusic

                yt = YTMusic()
            return ytm_show(yt, source)
        return parse_feed(http_get(source).content)

    def subscribe(self, text: str, yt=None) -> Podcast:
        kind, source = parse_subscription(text)
        pid = podcast_id(kind, source)
        if self.podcast(pid) is None:
            show = self.fetch_show(kind, source, yt)
            with self._lock, self._db:
                self._db.execute("INSERT INTO podcasts VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (pid, kind, source, show.title, show.author, show.description, show.cover_url,
                                  DEFAULT_KEEP, time.time(), 0))
            self._store(pid, show)
        return self.podcast(pid)

    def unsubscribe(self, pid: str) -> None:
        podcast = self.podcast(pid)
        if podcast is None:
            return
        for episode in self.episodes(pid, downloaded=True):
            self.path(episode).unlink(missing_ok=True)
        shutil.rmtree(self.show_dir(podcast), ignore_errors=True)
        with self._lock, self._db:
            self._db.execute("DELETE FROM podcasts WHERE id = ?", (pid,))

    def set_keep(self, pid: str, keep: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE podcasts SET keep = ? WHERE id = ?", (max(0, keep), pid))

    def refresh(self, pid: str, yt=None) -> list[Episode]:
        """Re-read the show's episode list; returns the episodes that are new."""
        podcast = self.podcast(pid)
        known = {e.guid for e in self.episodes(pid)}
        show = self.fetch_show(podcast.kind, podcast.source, yt)
        with self._lock, self._db:
            self._db.execute("UPDATE podcasts SET title=?, author=?, description=?, cover_url=?, refreshed_at=? "
                             "WHERE id=?", (show.title, show.author, show.description, show.cover_url, time.time(), pid))
        self._store(pid, show)
        return [e for e in self.episodes(pid) if e.guid not in known]

    def _store(self, pid: str, show: ShowInfo) -> None:
        with self._lock, self._db:
            for seq, ep in enumerate(show.episodes):
                eid = f"{pid}|{ep.guid}"
                # New episodes are inserted; known ones keep their download, position and played state.
                self._db.execute(
                    "INSERT INTO episodes (id, podcast_id, guid, seq, title, description, published, duration, media,"
                    " video) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET seq=excluded.seq,"
                    " title=excluded.title, description=excluded.description,"
                    " published=CASE WHEN excluded.published > 0 THEN excluded.published ELSE episodes.published END,"
                    " duration=CASE WHEN excluded.duration > 0 THEN excluded.duration ELSE episodes.duration END",
                    (eid, pid, ep.guid, seq, ep.title, ep.description, ep.published, ep.duration, ep.media,
                     int(ep.video)))

    def to_download(self, pid: str) -> list[Episode]:
        """The newest ``keep`` episodes not yet downloaded or played."""
        podcast = self.podcast(pid)
        newest = self.episodes(pid)[:podcast.keep] if podcast else []
        return [e for e in newest if not e.downloaded and not e.played]

    # -- downloading -----------------------------------------------------------------

    def download(self, eid: str, staging: Path, *, on_progress: ProgressFn | None = None,
                 cookies: str | None = None) -> Episode:
        episode = self.episode(eid)
        podcast = self.podcast(episode.podcast_id)
        if episode.downloaded and self.path(episode).exists():
            return episode
        staging.mkdir(parents=True, exist_ok=True)
        cover = self._ensure_cover(podcast)
        published = episode.published
        if podcast.kind == "ytm":
            info: dict = {}
            source = download_audio(episode.media, staging, on_progress, cookies=cookies, info=info)
            if not published and info.get("upload_date"):
                published = time.mktime(time.strptime(info["upload_date"], "%Y%m%d"))
            if not episode.description and info.get("description"):
                episode.description = plain_text(info["description"])
        else:
            source = self._fetch_enclosure(episode, staging, on_progress)
        if episode.video:
            from .video import zune_video

            source = zune_video(source, staging / "converted.mp4")
        elif source.suffix.lower() not in AUDIO_KEEP:
            source = _to_m4a(source, staging / "converted.m4a")
        episode.published = published
        day = time.strftime("%Y-%m-%d ", time.localtime(published)) if published else ""
        rel = Path(PODCASTS_DIR, safe_component(podcast.title),
                   f"{day}{safe_component(episode.title, 100)}{source.suffix.lower()}")
        tag_episode(source, podcast, episode, cover)
        dest = self.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, dest)
        with self._lock, self._db:
            self._db.execute("UPDATE episodes SET relpath=?, published=?, description=? WHERE id=?",
                             (rel.as_posix(), published, episode.description, eid))
        return self.episode(eid)

    def _fetch_enclosure(self, episode: Episode, staging: Path, on_progress: ProgressFn | None) -> Path:
        suffix = Path(urlparse(episode.media).path).suffix.lower() or (".mp4" if episode.video else ".mp3")
        target = staging / f"episode{suffix}"
        try:
            response = http_get(episode.media, stream=True, timeout=60)
        except Exception as exc:
            raise DownloadError(f"Couldn't download the episode: {exc}") from exc
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with open(target, "wb") as out:
            for chunk in response.iter_content(256 * 1024):
                out.write(chunk)
                done += len(chunk)
                if on_progress and total:
                    on_progress(min(done / total, 1.0))
        return target

    def _ensure_cover(self, podcast: Podcast) -> bytes | None:
        if (cover := self.cover(podcast)) is not None or not podcast.cover_url:
            return cover
        from .tagger import fetch_cover

        data = fetch_cover(podcast.cover_url, 600)
        if data:
            self.show_dir(podcast).mkdir(parents=True, exist_ok=True)
            (self.show_dir(podcast) / "cover.jpg").write_bytes(data)
        return data

    def delete_download(self, eid: str) -> None:
        episode = self.episode(eid)
        if episode and episode.relpath:
            self.path(episode).unlink(missing_ok=True)
        with self._lock, self._db:
            self._db.execute("UPDATE episodes SET relpath='' WHERE id=?", (eid,))

    def set_played(self, eid: str, played: bool = True) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE episodes SET played=?, position=CASE WHEN ? THEN 0 ELSE position END WHERE id=?",
                             (int(played), int(played), eid))

    def set_position(self, eid: str, ms: int) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE episodes SET position=? WHERE id=?", (max(0, ms), eid))


def _to_m4a(src: Path, dst: Path) -> Path:
    from .video import _ffmpeg

    result = subprocess.run([_ffmpeg(), "-loglevel", "error", "-y", "-i", str(src), "-vn", "-c:a", "aac",
                             "-b:a", "128k", str(dst)], capture_output=True, text=True)
    if result.returncode != 0:
        raise DownloadError(f"Couldn't convert the episode: {result.stderr.strip()[-300:]}")
    return dst
