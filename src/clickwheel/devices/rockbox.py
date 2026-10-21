"""Sync to Rockbox: plain files plus .m3u8 playlists, no database."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from ..library import is_music_path
from .apple import SyncSummary
from .contents import DeviceContents, DevicePlaylist, DeviceTrack

ProgressFn = Callable[[str, int, int], None]
MANIFEST = ".clickwheel/manifest.json"


class RockboxSync:
    """Mirrors the library into ``/Music`` and playlists into ``/Playlists``.

    Only files this app copied (tracked in a manifest on the device) are ever
    removed, so music the user put there by hand is left alone.
    """

    def __init__(self, mount: Path):
        self.mount = mount
        self.music = mount / "Music"
        self.playlists = mount / "Playlists"

    def browse(self) -> DeviceContents:
        return browse(self.mount)

    def add_tracks(self, library_root: Path, paths: set[Path], *, progress: ProgressFn | None = None,
                   cancelled: Callable[[], bool] | None = None) -> SyncSummary:
        """Copy ``paths`` without removing anything or touching playlists."""
        progress = progress or (lambda *_: None)
        summary = SyncSummary()
        manifest = self._manifest()
        tracks: dict[str, list] = manifest.setdefault("tracks", {})
        wanted = sorted(Path(p) for p in paths)
        for i, src in enumerate(wanted):
            if cancelled and cancelled():
                summary.errors.append("Cancelled")
                break
            rel = src.relative_to(library_root).as_posix()
            st = src.stat()
            sig = [st.st_size, int(st.st_mtime)]
            dest = self.music / rel
            if tracks.get(rel) == sig and dest.exists():
                continue
            progress(f"Copying songs · {src.name}", i, len(wanted))
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            except OSError as exc:
                summary.errors.append(f"{rel}: {exc}")
                continue
            summary.added += rel not in tracks
            summary.updated += rel in tracks
            tracks[rel] = sig
        self._save_manifest(manifest)
        progress("Done", len(wanted), len(wanted))
        return summary

    def delete_tracks(self, locations: set[str]) -> int:
        """Delete songs (device paths like "/Music/A/B/01 X.m4a") and drop them from playlists."""
        removed = 0
        for loc in locations:
            path = self.mount / loc.lstrip("/")
            if path.is_file():
                path.unlink()
                _prune_empty(path, self.music)
                removed += 1
        manifest = self._manifest()
        manifest["tracks"] = {rel: sig for rel, sig in manifest.get("tracks", {}).items()
                              if "/Music/" + rel not in locations}
        self._save_manifest(manifest)
        for m3u in self.playlists.glob("*.m3u*"):
            lines = m3u.read_text(encoding="utf-8", errors="replace").splitlines()
            kept = _without_entries(lines, locations)
            if kept != lines:
                m3u.write_text("\n".join(kept) + "\n", encoding="utf-8")
        return removed

    def reorder(self, playlist_id: str | None, locations: list[str]) -> None:
        if playlist_id is None:
            raise RuntimeError("Rockbox has no fixed song order; reorder a playlist instead.")
        m3u = self.playlists / playlist_id
        header = [line for line in m3u.read_text(encoding="utf-8", errors="replace").splitlines()
                  if line.startswith(("#EXTM3U", "#PLAYLIST"))]
        m3u.write_text("\n".join([*header, *locations]) + "\n", encoding="utf-8")

    def _manifest(self) -> dict:
        try:
            return json.loads((self.mount / MANIFEST).read_text())
        except (OSError, ValueError):
            return {"tracks": {}, "playlists": []}

    def _save_manifest(self, data: dict) -> None:
        path = self.mount / MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)

    def sync(self, library_root: Path, *, allowed: set[Path] | None = None, playlists: set[Path] | None = None,
             progress: ProgressFn | None = None, cancelled: Callable[[], bool] | None = None) -> SyncSummary:
        progress = progress or (lambda *_: None)
        summary = SyncSummary()
        manifest = self._manifest()
        old_tracks: dict[str, list] = manifest.get("tracks", {})

        wanted = sorted(
            p for p in library_root.rglob("*.m4a")
            if is_music_path(library_root, p)
            and (allowed is None or p in allowed)
        )
        new_tracks: dict[str, list] = {}
        for i, src in enumerate(wanted):
            if cancelled and cancelled():
                summary.errors.append("Cancelled")
                break
            rel = src.relative_to(library_root).as_posix()
            st = src.stat()
            sig = [st.st_size, int(st.st_mtime)]
            dest = self.music / rel
            new_tracks[rel] = sig
            if old_tracks.get(rel) == sig and dest.exists():
                continue
            progress(f"Copying {src.name}", i, len(wanted))
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                summary.added += rel not in old_tracks
                summary.updated += rel in old_tracks
            except OSError as exc:
                summary.errors.append(f"{rel}: {exc}")
                new_tracks.pop(rel, None)

        if not summary.errors:
            for rel in set(old_tracks) - set(new_tracks):
                (self.music / rel).unlink(missing_ok=True)
                summary.removed += 1
                _prune_empty(self.music / rel, self.music)

        # Playlists: rewrite library-relative entries as device-absolute paths.
        written = []
        self.playlists.mkdir(parents=True, exist_ok=True)
        for m3u in sorted((library_root / "Playlists").glob("*.m3u8")):
            if playlists is not None and m3u not in playlists:
                continue
            out_lines = []
            for line in m3u.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#"):
                    rel = os.path.normpath(m3u.parent / line).replace(os.sep, "/")
                    rel = Path(rel).relative_to(library_root).as_posix()
                    if rel not in new_tracks:
                        continue
                    line = "/Music/" + rel
                out_lines.append(line)
            (self.playlists / m3u.name).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
            written.append(m3u.name)
        for name in set(manifest.get("playlists", [])) - set(written):
            (self.playlists / name).unlink(missing_ok=True)
        summary.playlists = len(written)

        self._save_manifest({"tracks": new_tracks, "playlists": written})
        progress("Done", len(wanted), len(wanted))
        return summary


def _prune_empty(path: Path, stop: Path) -> None:
    for parent in path.parents:
        if parent == stop or stop not in parent.parents:
            return
        try:
            parent.rmdir()
        except OSError:
            return


AUDIO_EXTS = {".m4a", ".mp3", ".flac", ".ogg", ".opus", ".wav", ".aac", ".wma", ".aiff"}


def _read_tags(path: Path) -> DeviceTrack:
    import mutagen

    title, artist, album, number, duration = path.stem, "", "", 0, 0
    try:
        audio = mutagen.File(path, easy=True)
    except Exception:
        audio = None
    if audio is not None:
        tags = audio.tags or {}

        def first(key: str) -> str:
            value = tags.get(key)
            return str(value[0]) if value else ""

        title = first("title") or title
        artist, album = first("artist"), first("album")
        raw_number = first("tracknumber").split("/")[0]
        number = int(raw_number) if raw_number.isdigit() else 0
        duration = int(getattr(audio.info, "length", 0) or 0)
    return DeviceTrack(title, artist, album, number, duration)


def browse(mount: Path) -> DeviceContents:
    music = mount / "Music"
    files = sorted(p for p in music.rglob("*") if p.suffix.lower() in AUDIO_EXTS) if music.is_dir() else []
    tracks = []
    for p in files:
        t = _read_tags(p)
        t.location = "/" + p.relative_to(mount).as_posix()
        tracks.append(t)
    index = {t.location: i for i, t in enumerate(tracks)}
    playlists = []
    for m3u in sorted((mount / "Playlists").glob("*.m3u*")):
        name, indices = m3u.stem, []
        for line in m3u.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("#PLAYLIST:"):
                name = line.removeprefix("#PLAYLIST:").strip()
            elif line and not line.startswith("#"):
                path = line if line.startswith("/") else "/" + (m3u.parent / line).resolve().relative_to(
                    mount.resolve()).as_posix()
                if path in index:
                    indices.append(index[path])
        playlists.append(DevicePlaylist(name, indices, m3u.name))
    return DeviceContents(tracks, playlists)


def _without_entries(lines: list[str], locations: set[str]) -> list[str]:
    """Drop playlist entries for ``locations`` (and their #EXTINF lines)."""
    out: list[str] = []
    for line in lines:
        if line and not line.startswith("#") and line in locations:
            if out and out[-1].startswith("#EXTINF"):
                out.pop()
            continue
        out.append(line)
    return out
