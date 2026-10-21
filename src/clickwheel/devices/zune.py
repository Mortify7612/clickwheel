"""Sync to a Zune HD over MTP (Linux only).

The Zune files music by its own artist and album objects, not by the tags
sent with a track: each track links to an artist object (``Artists/<name>.art``)
and an album object (``Albums/<artist>--<album>.alb``), and the album carries
the cover art. Without those links a song plays but is listed under
"Unknown Artist" / "Unknown Album". Files go in ``Music/<artist>/<album>/``,
the same layout the Zune software uses.

Only one program can hold an MTP session, so every session is taken under
``LOCK``; each operation opens one (about a second, handshake included).
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import astuple, dataclass
from pathlib import Path

from ..config import DATA_DIR
from . import mtp, mtpz
from .apple import SyncSummary
from .contents import DeviceContents, DevicePlaylist, DeviceTrack

VENDOR, PRODUCT = 0x045E, 0x063E  # Microsoft Zune HD

LOCK = threading.Lock()

# Object formats
FOLDER = 0x3001
JPEG = 0x3801
MP3 = 0x3009
WMA = 0xB901
M4A = 0xB215
AAC = 0xB903
ALBUM = 0xBA03
PLAYLIST = 0xBA05
ARTIST = 0xB218
AUDIO = {MP3, WMA, M4A, AAC}

# Object properties (the 0xDAxx ones are Zune-specific)
FORMAT = 0xDC02
PARENT = 0xDC0B
FILE_NAME = 0xDC07
NAME = 0xDC44
ARTIST_NAME = 0xDC46
DATE_AUTHORED = 0xDC47
SAMPLE_FORMAT = 0xDC81
SAMPLE_DATA = 0xDC86
DURATION = 0xDC89
TRACK = 0xDC8B
GENRE = 0xDC8C
USE_COUNT = 0xDC91
ALBUM_NAME = 0xDC9A  # read-only on tracks: the Zune derives it from ALBUM_LINK
ARTIST_LINK = 0xDAB9  # handle of the track's (or album's) artist object
ALBUM_LINK = 0xDABB  # handle of the track's album object; set by the Zune

FRIENDLY_NAME = 0xD402  # device properties
BATTERY_LEVEL = 0x5001  # percent

COVER_SIZE = 240  # the Zune software stores covers that fit 240x240
MANIFEST_DIR = DATA_DIR / "zune"

ProgressFn = Callable[[str, int, int], None]


@dataclass
class TrackInfo:
    path: Path
    title: str
    artist: str
    album: str
    album_artist: str
    track_number: int = 0
    year: str = ""
    genre: str = ""
    duration_ms: int = 0
    cover: bytes | None = None


def read_track(path: Path) -> TrackInfo:
    from mutagen.mp4 import MP4

    tags = MP4(path)

    def first(key: str) -> str:
        value = tags.get(key)
        return str(value[0]) if value else ""

    artist = first("\xa9ART") or "Unknown Artist"
    track = tags.get("trkn")
    cover = tags.get("covr")
    return TrackInfo(path=path, title=first("\xa9nam") or path.stem, artist=artist,
                     album=first("\xa9alb") or "Unknown Album", album_artist=first("aART") or artist,
                     track_number=track[0][0] if track else 0, year=first("\xa9day")[:4],
                     genre=first("\xa9gen"), duration_ms=int(tags.info.length * 1000),
                     cover=bytes(cover[0]) if cover else None)


def zune_cover(image: bytes) -> bytes | None:
    """``image`` re-encoded as a JPEG that fits the Zune's 240x240 album art."""
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(image)).convert("RGB")
    except Exception:
        return None
    im.thumbnail((COVER_SIZE, COVER_SIZE), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=90)
    return out.getvalue()


def _date(year: str) -> str:
    return f"{year}0101T000000.0" if year.isdigit() else ""


def safe_name(text: str) -> str:
    """A file or folder name the Zune accepts."""
    cleaned = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in text).strip(" .")
    return cleaned[:100] or "_"


@dataclass(frozen=True)
class ZuneCover:
    """Album art read from the Zune, in the shape the cover cache expects."""

    data: bytes

    def load_png(self) -> bytes:  # any image format works; the cache decodes it
        return self.data


@dataclass
class Obj:
    """One object on the Zune with the metadata Clickwheel uses; cached between sessions."""

    handle: int
    format: int
    parent: int
    file_name: str
    name: str = ""
    artist: str = ""
    album: str = ""
    track: int = 0
    duration: int = 0  # milliseconds
    plays: int = 0
    album_link: int = 0
    artist_link: int = 0


# Where each property lands in an ``Obj``.
_ATTRS = {NAME: "name", ARTIST_NAME: "artist", ALBUM_NAME: "album", TRACK: "track", DURATION: "duration",
          USE_COUNT: "plays", ALBUM_LINK: "album_link", ARTIST_LINK: "artist_link"}

# Reading one value costs the Zune about a millisecond, so a full read of a
# full Zune takes ~20 s. Object handles survive replugs, so what was read is
# cached on this computer and only new objects are fetched (~25 ms each).
BULK_READ_OVER = 300


def _usb_serial(usb_device) -> str:
    import usb.core
    import usb.util

    try:
        return usb.util.get_string(usb_device, usb_device.iSerialNumber) or ""
    except (usb.core.USBError, ValueError):
        return ""


class Zune:
    """An open (and, given keys, authenticated) session with a Zune HD."""

    def __init__(self, device: mtp.MtpDevice, serial: str = ""):
        self.dev = device
        self.storage = 0
        self.can_write = False
        self._holds_lock = False
        self.cache_path = MANIFEST_DIR / f"{safe_name(serial)}.objects.json" if serial else None
        self._dirty = False
        self.objects: dict[int, Obj] = {}
        self._children: dict[tuple[int, str], int] = {}  # (parent, file name casefolded) -> handle
        self._artists: dict[str, int] = {}
        self._albums: dict[tuple[str, str], int] = {}

    @classmethod
    def connect(cls, *, write: bool = True, keys: mtpz.Keys | None = None) -> Zune:
        """Open a session (under ``LOCK``, released by ``close``).

        Reading works without the MTPZ keys; with ``write`` the keys are
        required and the handshake must succeed.
        """
        if not LOCK.acquire(timeout=120):
            raise mtp.MtpError("The Zune is busy with another operation")
        try:
            device = mtp.MtpDevice.find(VENDOR, PRODUCT)
            if device is None:
                raise mtp.MtpError("The Zune HD was unplugged")
            serial = _usb_serial(device.dev)
            device.open()
            zune = cls(device, serial)
            zune._holds_lock = True
            try:
                keys = keys or mtpz.load_keys()
                if keys is not None:
                    mtpz.handshake(device, keys)
                    zune.can_write = True
                elif write:
                    raise mtpz.MtpzError(f"Changing what's on a Zune needs the MTPZ key file {mtpz.KEY_FILE}")
                zune._load()
            except Exception:
                device.close()
                raise
        except Exception:
            LOCK.release()
            raise
        return zune

    def close(self) -> None:
        try:
            self._save_cache()
            self.dev.close()
        finally:
            if self._holds_lock:
                self._holds_lock = False
                LOCK.release()

    def __enter__(self) -> Zune:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- index of what's already there --------------------------------------

    def _query(self, code: int, *formats: int) -> dict[int, object]:
        """One property of every object of the given formats.

        Asking for all properties at once is too slow (the Zune times out),
        and only the generic ones (format, parent, file name) can be asked of
        every object at once (no ``formats``); the rest need a format.
        """
        values = {}
        for fmt in formats or (0,):
            try:
                values.update((p.handle, p.value) for p in self.dev.prop_list(0xFFFFFFFF, code, fmt=fmt))
            except mtp.MtpError:
                if not formats:
                    raise
        return values

    def _load(self) -> None:
        self.storage = self.dev.storage_ids()[0]
        handles = set(self.dev.object_handles(0xFFFFFFFF, 0, 0))
        cached = self._read_cache()
        self.objects = {h: o for h, o in cached.items() if h in handles}
        new = handles - self.objects.keys()
        self._dirty = bool(new) or len(self.objects) != len(cached)
        if len(new) > BULK_READ_OVER:
            self.objects = self._read_all()
        else:
            for handle in new:
                self.objects[handle] = self._read_one(handle)
        self._reindex()

    def _read_one(self, handle: int) -> Obj:
        props = {p.code: p.value for p in self.dev.prop_list(handle)}
        obj = Obj(handle, props.get(FORMAT, 0), props.get(PARENT, 0), props.get(FILE_NAME) or "")
        for code, attr in _ATTRS.items():
            if props.get(code):
                setattr(obj, attr, props[code])
        return obj

    def _read_all(self) -> dict[int, Obj]:
        parents, names = self._query(PARENT), self._query(FILE_NAME)
        objects = {h: Obj(h, fmt, parents.get(h, 0), names.get(h) or "") for h, fmt in self._query(FORMAT).items()}

        def fill(code: int, values: dict) -> None:
            for handle, value in values.items():
                if handle in objects and value:
                    setattr(objects[handle], _ATTRS[code], value)

        for fmt in AUDIO:  # Name, Artist, Album Name, Track and Genre come as one property group
            try:
                for p in self.dev.prop_list(0xFFFFFFFF, 0, fmt=fmt, group=3):
                    if p.code in _ATTRS:
                        fill(p.code, {p.handle: p.value})
            except mtp.MtpError:
                pass
        fill(NAME, self._query(NAME, ARTIST, ALBUM, PLAYLIST))
        fill(ARTIST_NAME, self._query(ARTIST_NAME, ALBUM))
        for code in (DURATION, USE_COUNT, ALBUM_LINK):
            fill(code, self._query(code, *AUDIO))
        fill(ARTIST_LINK, self._query(ARTIST_LINK, *AUDIO, ALBUM))
        return objects

    def _read_cache(self) -> dict[int, Obj]:
        if self.cache_path is None:
            return {}
        try:
            rows = json.loads(self.cache_path.read_text())["objects"]
            return {row[0]: Obj(*row) for row in rows}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _save_cache(self) -> None:
        if self.cache_path is None or not self._dirty:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"objects": [astuple(o) for o in self.objects.values()]}))
            os.replace(tmp, self.cache_path)
            self._dirty = False
        except OSError:
            pass

    def _reindex(self) -> None:
        self._children = {(o.parent, o.file_name.casefold()): h for h, o in self.objects.items() if o.file_name}
        self._artists, self._albums = {}, {}
        for h, o in sorted(self.objects.items()):
            if o.format == ARTIST:
                self._artists.setdefault(o.name.casefold(), h)
            elif o.format == ALBUM:
                self._albums.setdefault((o.artist.casefold(), o.name.casefold()), h)

    def path_of(self, handle: int) -> str:
        parts = []
        seen = set()
        while handle in self.objects and handle not in seen:
            seen.add(handle)
            obj = self.objects[handle]
            parts.append(obj.file_name)
            handle = obj.parent
        return "/" + "/".join(reversed(parts))

    def find(self, path: str) -> int | None:
        """Handle of the object at a device path like "/Music/A/B/01 X.m4a"."""
        handle = 0
        for part in path.strip("/").split("/"):
            handle = self._children.get((handle, part.casefold()))
            if handle is None:
                return None
        return handle

    def _add(self, handle: int, fmt: int, parent: int, file_name: str, **meta) -> int:
        self.objects[handle] = Obj(handle, fmt, parent, file_name, **meta)
        self._children[(parent, file_name.casefold())] = handle
        self._dirty = True
        return handle

    def _forget(self, handle: int) -> None:
        obj = self.objects.pop(handle, None)
        if obj is not None:
            self._children.pop((obj.parent, obj.file_name.casefold()), None)
            self._dirty = True

    def folder(self, *path: str) -> int:
        """Handle of the folder at ``path`` from the root, creating any that are missing."""
        parent = 0  # the root
        for part in path:
            part = safe_name(part)
            handle = self._children.get((parent, part.casefold()))
            if handle is None:
                handle = self._add(self.dev.send_object(self.storage, parent, FOLDER, [(FILE_NAME, mtp.STR, part)],
                                                        send_data=False), FOLDER, parent, part)
            parent = handle
        return parent

    def artist(self, name: str) -> int:
        """Handle of the artist object called ``name``, creating it if needed."""
        key = name.casefold()
        if key not in self._artists:
            parent, file_name = self.folder("Artists"), f"{safe_name(name)}.art"
            handle = self.dev.send_object(self.storage, parent, ARTIST, [(FILE_NAME, mtp.STR, file_name),
                                                                          (NAME, mtp.STR, name)])
            self._artists[key] = self._add(handle, ARTIST, parent, file_name, name=name)
        return self._artists[key]

    # -- writing ---------------------------------------------------------------

    def add_track(self, info: TrackInfo, progress: Callable[[int, int], None] | None = None) -> int:
        """Copy one song and file it under its artist and album; returns the track's handle."""
        parent = self.folder("Music", info.album_artist, info.album)
        file_name = safe_name(info.path.name)
        artist = self.artist(info.artist)
        props = [
            (FILE_NAME, mtp.STR, file_name),
            (NAME, mtp.STR, info.title),
            (ARTIST_NAME, mtp.STR, info.artist),
            (ARTIST_LINK, mtp.UINT32, artist),
            (DURATION, mtp.UINT32, info.duration_ms),
            (TRACK, mtp.UINT16, info.track_number),
        ]
        if info.genre:
            props.append((GENRE, mtp.STR, info.genre))
        if info.year:
            props.append((DATE_AUTHORED, mtp.STR, _date(info.year)))
        handle = self.dev.send_object(self.storage, parent, M4A, props, info.path.read_bytes(), progress)
        self._add(handle, M4A, parent, file_name, name=info.title, artist=info.artist, album=info.album,
                  track=info.track_number, duration=info.duration_ms, artist_link=artist)
        self.objects[handle].album_link = self._add_to_album(info, handle)
        return handle

    def _add_to_album(self, info: TrackInfo, track: int) -> int:
        key = (info.album_artist.casefold(), info.album.casefold())
        album = self._albums.get(key)
        if album is None:
            parent = self.folder("Albums")
            file_name = f"{safe_name(info.album_artist)}--{safe_name(info.album)}.alb"
            artist = self.artist(info.album_artist)
            props = [
                (FILE_NAME, mtp.STR, file_name),
                (NAME, mtp.STR, info.album),
                (ARTIST_NAME, mtp.STR, info.album_artist),
                (ARTIST_LINK, mtp.UINT32, artist),
            ]
            if info.year:
                props.append((DATE_AUTHORED, mtp.STR, _date(info.year)))
            album = self._albums[key] = self._add(self.dev.send_object(self.storage, parent, ALBUM, props), ALBUM,
                                                  parent, file_name, name=info.album, artist=info.album_artist,
                                                  artist_link=artist)
            cover = zune_cover(info.cover) if info.cover else None
            if cover:
                self.dev.set_prop(album, SAMPLE_FORMAT, mtp.UINT16, JPEG)
                self.dev.set_prop(album, SAMPLE_DATA, mtp.AUINT8, cover)
        tracks = self.dev.references(album)
        if track not in tracks:
            self.dev.set_references(album, [*tracks, track])
        return album

    def delete_tracks(self, handles: list[int]) -> int:
        """Delete songs, then any album, artist and folder that only they used."""
        albums, artists, folders = set(), set(), set()
        removed = 0
        for handle in handles:
            obj = self.objects.get(handle)
            if obj is None or obj.format not in AUDIO:
                continue
            albums.add(obj.album_link)
            artists.add(obj.artist_link)
            folders.add(obj.parent)
            self.dev.delete(handle)
            self._forget(handle)
            removed += 1
        for album in albums - {0}:
            if album in self.objects and not any(o.album_link == album for o in self.objects.values()):
                artists.add(self.objects[album].artist_link)
                self._delete_object(album)
        used = {o.artist_link for o in self.objects.values()}
        for artist in artists - used - {0}:
            if artist in self.objects and self.objects[artist].format == ARTIST:
                self._delete_object(artist)
        music = self.find("/Music")
        for folder in folders:
            self._prune(folder, music)
        return removed

    def _delete_object(self, handle: int) -> None:
        self.dev.delete(handle)
        self._forget(handle)
        self._artists = {k: h for k, h in self._artists.items() if h != handle}
        self._albums = {k: h for k, h in self._albums.items() if h != handle}

    def _prune(self, folder: int, stop: int | None) -> None:
        """Delete ``folder`` and its parents while they're empty, up to ``stop``."""
        while folder and folder != stop and folder in self.objects:
            if any(o.parent == folder for o in self.objects.values()):
                return
            parent = self.objects[folder].parent
            self._delete_object(folder)
            folder = parent

    # -- playlists ----------------------------------------------------------------

    def playlists(self) -> dict[int, str]:
        """Handles and names of the user's playlists (not the built-in "now playing")."""
        folder = self.find("/Playlists")
        return {h: o.name for h, o in self.objects.items() if o.format == PLAYLIST and o.parent == folder}

    def set_playlist(self, name: str, tracks: list[int]) -> int:
        """Create or replace the playlist called ``name``."""
        parent = self.folder("Playlists")
        file_name = f"{safe_name(name)}.pla"
        handle = self._children.get((parent, file_name.casefold()))
        if handle is None:
            handle = self._add(self.dev.send_object(self.storage, parent, PLAYLIST, [
                (FILE_NAME, mtp.STR, file_name), (NAME, mtp.STR, name)]), PLAYLIST, parent, file_name, name=name)
        self.dev.set_references(handle, tracks)
        return handle


# ── Backend used by the app ────────────────────────────────────────────────────

@dataclass
class ZuneInfo:
    serial: str
    name: str = "Zune HD"
    free: int = 0
    total: int = 0
    busy: bool = False  # another program (usually KDE's MTP service) holds it
    has_keys: bool = True
    battery: int | None = None  # percent
    checked: float = 0.0  # time.monotonic() of the last status read


def _read_status(device: mtp.MtpDevice, info: ZuneInfo, storage: int | None = None) -> None:
    """Battery and free space (and the name, which can change on the Zune) from an open session."""
    try:
        info.battery = device.get_device_prop(BATTERY_LEVEL, mtp.UINT8)
        info.name = device.get_device_prop(FRIENDLY_NAME, mtp.STR) or info.name
        info.free, info.total = device.storage_space(storage or device.storage_ids()[0])
        info.checked = time.monotonic()
    except mtp.MtpError:
        pass


def probe() -> ZuneInfo | None:
    """Describe the plugged-in Zune HD, if any. Reads only; no keys needed."""
    import usb.core
    import usb.util

    dev = usb.core.find(idVendor=VENDOR, idProduct=PRODUCT)
    if dev is None:
        return None
    try:
        serial = usb.util.get_string(dev, dev.iSerialNumber) or ""
    except (usb.core.USBError, ValueError):
        serial = ""
    info = ZuneInfo(serial=serial or f"{dev.bus}-{dev.address}", has_keys=mtpz.load_keys() is not None)
    if not LOCK.acquire(blocking=False):
        return None  # a session is open; the caller keeps what it knew
    try:
        device = mtp.MtpDevice(dev)
        device.open()
        try:
            _read_status(device, info)
        finally:
            device.close()
    except mtp.DeviceBusy:
        info.busy = True
    finally:
        LOCK.release()
    return info


def refresh(info: ZuneInfo) -> None:
    """Re-read battery and free space with a short session, unless another one is open."""
    if not LOCK.acquire(blocking=False):
        return
    try:
        device = mtp.MtpDevice.find(VENDOR, PRODUCT)
        if device is not None:
            device.open()
            try:
                _read_status(device, info)
            finally:
                device.close()
    except mtp.MtpError:
        pass
    finally:
        LOCK.release()


def release_from_kde() -> bool:
    """Ask KDE's KIO daemon (whose MTP module grabs MTP players) to quit; it restarts on demand."""
    if not shutil.which("busctl"):
        return False
    result = subprocess.run(["busctl", "--user", "call", "org.kde.kiod6", "/MainApplication",
                             "org.qtproject.Qt.QCoreApplication", "quit"], capture_output=True, timeout=10)
    return result.returncode == 0


class ZuneSync:
    """Mirrors the library onto a Zune HD; same interface as ``RockboxSync``.

    Only songs and playlists this app sent (tracked in a manifest on this
    computer, by device path) are ever removed.
    """

    def __init__(self, info: ZuneInfo):
        self.info = info
        self.manifest_path = MANIFEST_DIR / f"{safe_name(info.serial)}.json"

    def _manifest(self) -> dict:
        try:
            return json.loads(self.manifest_path.read_text())
        except (OSError, ValueError):
            return {"tracks": {}, "playlists": {}}

    def _save_manifest(self, data: dict) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        os.replace(tmp, self.manifest_path)

    def _refresh_status(self, zune: Zune) -> None:
        _read_status(zune.dev, self.info, zune.storage)

    # -- reading ---------------------------------------------------------------

    def browse(self) -> DeviceContents:
        with Zune.connect(write=False) as zune:
            for handle, plays in zune._query(USE_COUNT, *AUDIO).items():  # the one thing the Zune changes itself
                if handle in zune.objects and zune.objects[handle].plays != plays:
                    zune.objects[handle].plays = plays
                    zune._dirty = True
            covers: dict[int, ZuneCover | None] = {}
            tracks, index = [], {}
            for h in sorted((h for h, o in zune.objects.items() if o.format in AUDIO), key=zune.path_of):
                o = zune.objects[h]
                if o.album_link and o.album_link not in covers:
                    try:
                        data = zune.dev.get_prop(o.album_link, SAMPLE_DATA, mtp.AUINT8)
                    except mtp.MtpError:
                        data = b""
                    covers[o.album_link] = ZuneCover(bytes(data)) if data else None
                index[h] = len(tracks)
                tracks.append(DeviceTrack(title=o.name or o.file_name, artist=o.artist, album=o.album,
                                          track_number=o.track, duration=o.duration // 1000, play_count=o.plays,
                                          location=zune.path_of(h), artwork=covers.get(o.album_link)))
            playlists = [DevicePlaylist(name, [index[t] for t in zune.dev.references(h) if t in index],
                                        zune.path_of(h))
                         for h, name in sorted(zune.playlists().items(), key=lambda kv: kv[1].casefold())]
            self._refresh_status(zune)
            can_write = zune.can_write
        notice = "" if can_write else f"Read-only: add the MTPZ key file {mtpz.KEY_FILE} to change the Zune"
        return DeviceContents(tracks, playlists, notice=notice)

    # -- writing ---------------------------------------------------------------

    def _send(self, zune: Zune, library_root: Path, src: Path, tracks: dict, summary: SyncSummary,
              on_bytes) -> None:
        """Copy one library song unless the Zune already has this version of it."""
        rel = src.relative_to(library_root).as_posix()
        st = src.stat()
        sig = [st.st_size, int(st.st_mtime)]
        entry = tracks.get(rel)
        existing = zune.find(entry["path"]) if entry else None
        if entry and entry["sig"] == sig and existing:
            return
        info = read_track(src)
        target = f"{zune.path_of(zune.folder('Music', info.album_artist, info.album))}/{safe_name(src.name)}"
        if existing:
            zune.delete_tracks([existing])
        elif zune.find(target) is not None:
            return  # the same file is on the Zune already, put there by something else: leave it be
        handle = zune.add_track(info, on_bytes)
        tracks[rel] = {"sig": sig, "path": zune.path_of(handle)}
        summary.added += entry is None
        summary.updated += entry is not None

    def add_tracks(self, library_root: Path, paths: set[Path], *, progress: ProgressFn | None = None,
                   cancelled: Callable[[], bool] | None = None) -> SyncSummary:
        """Copy ``paths`` without removing anything or touching playlists."""
        progress = progress or (lambda *_: None)
        summary = SyncSummary()
        manifest = self._manifest()
        wanted = sorted(Path(p) for p in paths)
        progress("Connecting to the Zune", 0, 0)
        with Zune.connect() as zune:
            try:
                for i, src in enumerate(wanted):
                    if cancelled and cancelled():
                        summary.errors.append("Cancelled")
                        break
                    progress(f"Copying songs · {src.name}", i, len(wanted))
                    try:
                        self._send(zune, library_root, src, manifest["tracks"], summary, None)
                    except (OSError, mtp.MtpError) as exc:
                        summary.errors.append(f"{src.name}: {exc}")
            finally:
                self._save_manifest(manifest)
            self._refresh_status(zune)
        progress("Done", len(wanted), len(wanted))
        return summary

    def sync(self, library_root: Path, *, allowed: set[Path] | None = None, playlists: set[Path] | None = None,
             progress: ProgressFn | None = None, cancelled: Callable[[], bool] | None = None) -> SyncSummary:
        progress = progress or (lambda *_: None)
        summary = SyncSummary()
        manifest = self._manifest()
        tracks: dict[str, dict] = manifest.setdefault("tracks", {})
        wanted = sorted(
            p for p in library_root.rglob("*.m4a")
            if "Playlists" not in p.relative_to(library_root).parts
            and (allowed is None or p in allowed)
        )
        keep = {p.relative_to(library_root).as_posix() for p in wanted}
        progress("Connecting to the Zune", 0, 0)
        with Zune.connect() as zune:
            try:
                for i, src in enumerate(wanted):
                    if cancelled and cancelled():
                        summary.errors.append("Cancelled")
                        break
                    progress(f"Copying songs · {src.name}", i, len(wanted))
                    try:
                        self._send(zune, library_root, src, tracks, summary, None)
                    except (OSError, mtp.MtpError) as exc:
                        summary.errors.append(f"{src.name}: {exc}")

                if not summary.errors:
                    gone = sorted(set(tracks) - keep)
                    if gone:
                        progress("Removing songs", 0, len(gone))
                        handles = [h for rel in gone if (h := zune.find(tracks[rel]["path"])) is not None]
                        zune.delete_tracks(handles)
                        summary.removed += len(handles)
                        for rel in gone:
                            del tracks[rel]

                    progress("Writing playlists", 0, 0)
                    summary.playlists = self._sync_playlists(zune, library_root, playlists, manifest)
            finally:
                self._save_manifest(manifest)
            self._refresh_status(zune)
        progress("Done", len(wanted), len(wanted))
        return summary

    def _sync_playlists(self, zune: Zune, library_root: Path, chosen: set[Path] | None, manifest: dict) -> int:
        tracks = manifest["tracks"]
        old: dict[str, str] = manifest.setdefault("playlists", {})  # m3u file name -> device path
        written: dict[str, str] = {}
        for m3u in sorted((library_root / "Playlists").glob("*.m3u8")):
            if chosen is not None and m3u not in chosen:
                continue
            name, handles = m3u.stem, []
            for line in m3u.read_text(encoding="utf-8").splitlines():
                if line.startswith("#PLAYLIST:"):
                    name = line.removeprefix("#PLAYLIST:").strip() or name
                elif line and not line.startswith("#"):
                    rel = Path(os.path.normpath(m3u.parent / line)).relative_to(library_root).as_posix()
                    if rel in tracks and (h := zune.find(tracks[rel]["path"])) is not None:
                        handles.append(h)
            previous = zune.find(old[m3u.name]) if m3u.name in old else None
            if previous is not None and zune.path_of(previous) != f"/Playlists/{safe_name(name)}.pla":
                zune._delete_object(previous)  # renamed in the library
            written[m3u.name] = zune.path_of(zune.set_playlist(name, handles))
        for m3u_name, path in old.items():
            if m3u_name not in written and (h := zune.find(path)) is not None:
                zune._delete_object(h)
        manifest["playlists"] = written
        return len(written)

    def delete_tracks(self, locations: set[str]) -> int:
        """Delete songs (device paths like "/Music/A/B/01 X.m4a"); the Zune drops them from playlists itself."""
        with Zune.connect() as zune:
            removed = zune.delete_tracks([h for loc in locations if (h := zune.find(loc)) is not None])
            self._refresh_status(zune)
        manifest = self._manifest()
        manifest["tracks"] = {rel: e for rel, e in manifest.get("tracks", {}).items() if e["path"] not in locations}
        self._save_manifest(manifest)
        return removed

    def reorder(self, playlist_id: str | None, locations: list[str]) -> None:
        if playlist_id is None:
            raise RuntimeError("The Zune sorts its own song list; reorder a playlist instead.")
        with Zune.connect() as zune:
            playlist = zune.find(playlist_id)
            if playlist is None:
                raise RuntimeError("That playlist is no longer on the Zune")
            zune.dev.set_references(playlist, [h for loc in locations if (h := zune.find(loc)) is not None])
