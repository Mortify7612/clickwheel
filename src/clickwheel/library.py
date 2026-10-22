"""Local music library index (SQLite) and playlist files."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .tagger import safe_component
from .ytm import TrackMeta

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    video_id     TEXT PRIMARY KEY,
    relpath      TEXT NOT NULL,
    title        TEXT NOT NULL,
    artist       TEXT NOT NULL,
    album        TEXT NOT NULL,
    album_artist TEXT NOT NULL,
    track_number INTEGER NOT NULL DEFAULT 0,
    year         TEXT NOT NULL DEFAULT '',
    duration     INTEGER NOT NULL DEFAULT 0,
    added_at     REAL NOT NULL
);
-- A music video and its album version resolve to the same file.
CREATE TABLE IF NOT EXISTS aliases (
    source_id TEXT PRIMARY KEY,
    video_id  TEXT NOT NULL REFERENCES tracks(video_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS playlists (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    url        TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL,
    profile    TEXT NOT NULL DEFAULT ''  -- saved YouTube profile it came from
);
CREATE TABLE IF NOT EXISTS playlist_items (
    playlist_id TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    video_id    TEXT NOT NULL,
    PRIMARY KEY (playlist_id, position)
);
"""

# Top-level library folders holding things other than songs; device music syncs skip them.
NON_MUSIC_DIRS = {"Playlists", "Podcasts", "Music Videos"}


def is_music_path(root: Path, path: Path) -> bool:
    """Whether a file under the library root is a song (not a podcast, video or playlist)."""
    parts = path.relative_to(root).parts
    return "Playlists" not in parts and parts[0] not in NON_MUSIC_DIRS


@dataclass
class LibraryTrack:
    video_id: str
    relpath: str
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: int
    year: str
    duration: int
    added_at: float = 0.0  # unix time the song was downloaded


@dataclass
class LibraryPlaylist:
    id: str
    title: str
    kind: str
    url: str
    track_count: int
    profile: str = ""
    updated_at: float = 0.0  # unix time it was last downloaded or updated


class Library:
    def __init__(self, root: Path, db_path: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        columns = {r[1] for r in self._db.execute("PRAGMA table_info(playlists)")}
        if "profile" not in columns:  # libraries created before multi-profile support
            self._db.execute("ALTER TABLE playlists ADD COLUMN profile TEXT NOT NULL DEFAULT ''")

    @property
    def playlists_dir(self) -> Path:
        return self.root / "Playlists"

    # ── Tracks ───────────────────────────────────────────────────────────

    def resolve_id(self, video_id: str) -> str | None:
        """Return the library track ID for a video ID (or its alias), if downloaded."""
        with self._lock:
            row = self._db.execute(
                "SELECT video_id FROM tracks WHERE video_id = ? "
                "UNION SELECT video_id FROM aliases WHERE source_id = ?",
                (video_id, video_id),
            ).fetchone()
        if row is None:
            return None
        track = self.track(row[0])
        if track is None or not (self.root / track.relpath).exists():
            return None
        return row[0]

    def add_track(self, meta: TrackMeta, relpath: Path) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO tracks VALUES (?,?,?,?,?,?,?,?,?,?)",
                (meta.video_id, relpath.as_posix(), meta.title, meta.artist, meta.album,
                 meta.album_artist or meta.artist, meta.track_number, meta.year, meta.duration, time.time()),
            )
            if meta.source_video_id and meta.source_video_id != meta.video_id:
                self._db.execute("INSERT OR REPLACE INTO aliases VALUES (?,?)",
                                 (meta.source_video_id, meta.video_id))

    def track(self, video_id: str) -> LibraryTrack | None:
        with self._lock:
            row = self._db.execute(
                "SELECT video_id, relpath, title, artist, album, album_artist, track_number, year, duration, added_at "
                "FROM tracks WHERE video_id = ?", (video_id,)).fetchone()
        return LibraryTrack(*row) if row else None

    def tracks(self) -> list[LibraryTrack]:
        with self._lock:
            rows = self._db.execute(
                "SELECT video_id, relpath, title, artist, album, album_artist, track_number, year, duration, added_at "
                "FROM tracks ORDER BY album_artist COLLATE NOCASE, album COLLATE NOCASE, track_number"
            ).fetchall()
        return [LibraryTrack(*r) for r in rows]

    def delete_track(self, video_id: str) -> None:
        track = self.track(video_id)
        if track is None:
            return
        path = self.root / track.relpath
        path.unlink(missing_ok=True)
        for parent in (path.parent, path.parent.parent):
            try:
                parent.rmdir()  # only succeeds when empty
            except OSError:
                break
        with self._lock, self._db:
            self._db.execute("DELETE FROM tracks WHERE video_id = ?", (video_id,))
            affected = [r[0] for r in self._db.execute(
                "SELECT DISTINCT playlist_id FROM playlist_items WHERE video_id = ?", (video_id,))]
            self._db.execute("DELETE FROM playlist_items WHERE video_id = ?", (video_id,))
        for pid in affected:
            self._renumber(pid)
            self.write_m3u(pid)

    # ── Playlists ────────────────────────────────────────────────────────

    def save_playlist(self, pid: str, title: str, kind: str, url: str, video_ids: list[str],
                      profile: str = "") -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO playlists (id, title, kind, url, updated_at, profile) "
                             "VALUES (?,?,?,?,?,?)", (pid, title, kind, url, time.time(), profile))
            self._db.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (pid,))
            self._db.executemany("INSERT INTO playlist_items VALUES (?,?,?)",
                                 [(pid, i, vid) for i, vid in enumerate(video_ids)])
        self.write_m3u(pid)

    def playlists(self) -> list[LibraryPlaylist]:
        with self._lock:
            rows = self._db.execute(
                "SELECT p.id, p.title, p.kind, p.url, COUNT(i.video_id), p.profile, p.updated_at FROM playlists p "
                "LEFT JOIN playlist_items i ON i.playlist_id = p.id GROUP BY p.id "
                "ORDER BY p.title COLLATE NOCASE").fetchall()
        return [LibraryPlaylist(*r) for r in rows]

    def playlist_tracks(self, pid: str) -> list[LibraryTrack]:
        with self._lock:
            rows = self._db.execute(
                "SELECT t.video_id, t.relpath, t.title, t.artist, t.album, t.album_artist, t.track_number, "
                "t.year, t.duration, t.added_at FROM playlist_items i JOIN tracks t ON t.video_id = i.video_id "
                "WHERE i.playlist_id = ? ORDER BY i.position", (pid,)).fetchall()
        return [LibraryTrack(*r) for r in rows]

    def reorder_playlist(self, pid: str, ordered_ids: list[str]) -> None:
        """Put ``ordered_ids`` first, in that order; other songs keep their relative order after."""
        playlist = next((p for p in self.playlists() if p.id == pid), None)
        if playlist is None:
            return
        current = [t.video_id for t in self.playlist_tracks(pid)]
        wanted = [v for v in dict.fromkeys(ordered_ids) if v in set(current)]
        rest = [v for v in current if v not in set(wanted)]
        self.save_playlist(pid, playlist.title, playlist.kind, playlist.url, wanted + rest, playlist.profile)

    def find_track(self, title: str, artist: str, album: str) -> LibraryTrack | None:
        """Match a song seen on a device back to the library by its tags."""
        key = (title.casefold(), artist.casefold(), album.casefold())
        return next((t for t in self.tracks() if (t.title.casefold(), t.artist.casefold(), t.album.casefold()) == key),
                    None)

    def delete_playlist(self, pid: str) -> None:
        playlist = next((p for p in self.playlists() if p.id == pid), None)
        with self._lock, self._db:
            self._db.execute("DELETE FROM playlists WHERE id = ?", (pid,))
        if playlist:
            self.m3u_path(playlist.title, pid).unlink(missing_ok=True)

    def m3u_path(self, title: str, pid: str) -> Path:
        return self.playlists_dir / f"{safe_component(title)} [{safe_component(pid[-6:])}].m3u8"

    def write_m3u(self, pid: str) -> None:
        playlist = next((p for p in self.playlists() if p.id == pid), None)
        if playlist is None:
            return
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
        lines = ["#EXTM3U", f"#PLAYLIST:{playlist.title}"]
        for t in self.playlist_tracks(pid):
            lines.append(f"#EXTINF:{t.duration},{t.artist} - {t.title}")
            # Relative paths keep the library portable between machines.
            lines.append(os.path.relpath(self.root / t.relpath, self.playlists_dir).replace(os.sep, "/"))
        self.m3u_path(playlist.title, pid).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _renumber(self, pid: str) -> None:
        with self._lock, self._db:
            ids = [r[0] for r in self._db.execute(
                "SELECT video_id FROM playlist_items WHERE playlist_id = ? ORDER BY position", (pid,))]
            self._db.execute("DELETE FROM playlist_items WHERE playlist_id = ?", (pid,))
            self._db.executemany("INSERT INTO playlist_items VALUES (?,?,?)",
                                 [(pid, i, vid) for i, vid in enumerate(ids)])
