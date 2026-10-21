"""Sync to iPods running Apple firmware, via pyPodLib.

pyPodLib writes iTunesDB / iTunesCDB with the right signature for every
click-wheel model (none, hash58, hash72, hashAB) plus ArtworkDB.  Shuffles get
an iTunesSD written on top, which pyPodLib does not produce.
"""

from __future__ import annotations

import dataclasses
import shutil
import sys
import zlib
from collections.abc import Callable
from pathlib import Path

from pypodlib import IPod, Track
from pypodlib.sync import EngineOperation, EngineOptions, EngineRequest, SyncEngine
from pypodlib.sync import playlist_parser
from pypodlib.sync.sync_executor import SyncExecutor

from ..library import is_music_path
from . import itunessd
from ._session import is_read_only, on_device
from .contents import ArtworkRef, DeviceContents, DevicePlaylist, DeviceTrack

ProgressFn = Callable[[str, int, int], None]

_original_download_podcasts = SyncExecutor._download_podcast_episodes


def _download_podcasts_if_any(self, ctx):
    # pyPodLib 0.1.0 ships without its ``podcasts`` subpackage but imports it
    # unconditionally in this stage, so every sync fails.  We never sync
    # podcasts; only defer to the original when the plan actually has some.
    if any(getattr(item.pc_track, "is_podcast", False) for item in ctx.plan.to_add):
        return _original_download_podcasts(self, ctx)
    return None


SyncExecutor._download_podcast_episodes = _download_podcasts_if_any

_original_derive_name = playlist_parser._derive_name


def _playlist_name(filepath: Path) -> str:
    # pyPodLib title-cases the file stem and strips "-"/"_", mangling names.
    # Our .m3u8 files carry the real YouTube Music title in #PLAYLIST.
    try:
        with open(filepath, encoding="utf-8-sig") as fh:
            for line in fh:
                if line.startswith("#PLAYLIST:"):
                    return line.removeprefix("#PLAYLIST:").strip()
    except OSError:
        pass
    return _original_derive_name(filepath)


playlist_parser._derive_name = _playlist_name


@dataclasses.dataclass
class SyncSummary:
    added: int = 0
    removed: int = 0
    updated: int = 0
    playlists: int = 0
    errors: list[str] = dataclasses.field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# pyPodLib's executor stages; the engine collapses all of these into a single
# generic "execute_files" stage, so name them from the underlying event.
_STAGE_LABELS = {
    "add": "Copying songs",
    "remove": "Removing songs",
    "update_file": "Replacing changed songs",
    "update_metadata": "Updating song info",
    "update_artwork": "Updating album art",
    "playlists": "Writing playlists",
    "write_database": "Writing database",
    "sound_check": "Measuring loudness",
    "sync_playcount": "Reading play counts",
    "sync_rating": "Reading ratings",
    # Planning / bookkeeping stages that report one message per file.
    "scan_pc": "Scanning library",
    "fingerprint": "Matching songs with the iPod",
    "lyrics_metadata": "Copying embedded lyrics",
    "backpatch": "Saving sync records",
}
_GENERIC_STAGES = {"load", "migrate", "normalize", "scan", "identify", "plan", "validate", "execute_files",
                   "assemble_commit", "commit", "post_commit", "complete"}


def _item_name(item) -> str:
    if item is None:
        return ""
    pc = getattr(item, "pc_track", None)
    if pc is not None and getattr(pc, "title", ""):
        artist = getattr(pc, "artist", "")
        return f"{artist} – {pc.title}" if artist else pc.title
    if getattr(item, "ipod_track", None):
        t = Track(item.ipod_track)
        return f"{t.artist} – {t.title}" if t.artist else t.title
    return getattr(item, "description", "") or ""


def _describe_progress(ev) -> str:
    """Return "Phase" or "Phase · current item" for a SyncEngine progress event."""
    legacy = ev.legacy_event
    stage = str(getattr(legacy, "stage", "") or "")
    label = _STAGE_LABELS.get(stage)
    if label is None:
        message = ev.message or getattr(legacy, "message", "")
        if message:
            label = message
        elif stage and stage not in _GENERIC_STAGES:
            label = stage.replace("_", " ").capitalize()
        else:
            label = "Working"
    if isinstance(legacy, tuple) and legacy:  # planning events: (stage, current, total, message)
        stage = str(legacy[0])
        label = _STAGE_LABELS.get(stage, label)
    # With a named phase, the event's own message (file name, sub-step) is detail.
    detail = _item_name(getattr(legacy, "current_item", None))
    if not detail and stage in _STAGE_LABELS and ev.message and ev.message != label:
        detail = ev.message
    return f"{label} · {detail}" if detail else label


def find_fpcalc() -> str:
    """Locate Chromaprint's ``fpcalc``, which pyPodLib needs to match songs.

    Order: shipped inside the app, already installed, pyPodLib's earlier
    download, then a one-time download of the static build for this platform.
    """
    exe = "fpcalc.exe" if sys.platform == "win32" else "fpcalc"
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle and (Path(bundle) / exe).is_file():
        return str(Path(bundle) / exe)
    if found := shutil.which("fpcalc"):
        return found
    from pypodlib.sync.dependency_manager import download_fpcalc, get_bundled_fpcalc

    if found := get_bundled_fpcalc() or download_fpcalc():
        return found
    raise RuntimeError(
        "Clickwheel needs Chromaprint's fpcalc to match songs on the iPod and couldn't download it. "
        "Check your internet connection, or install Chromaprint (https://acoustid.org/chromaprint)."
    )


LIBRARY_AUDIO = {".m4a", ".mp3", ".aac", ".wav"}


def _library_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in LIBRARY_AUDIO
            and is_music_path(root, p)]


def _loc(track) -> str:
    return (track.location or "").replace(":", "/")


def _playlist_key(playlist) -> str:
    return str(playlist.playlist_id) if playlist.playlist_id else f"name:{playlist.name}"


def _in_master_order(lib) -> list:
    """Tracks in master-playlist order (the Shuffle's play order), others after."""
    tracks = lib.tracks
    master = lib.master_playlist
    if master is None:
        return tracks
    position = {db_id: n for n, db_id in enumerate(master.track_ids)}
    return sorted(tracks, key=lambda t: position.get(t.db_track_id, len(position)))


def _plan_counts(plan) -> dict[str, int]:
    return {f.name: len(getattr(plan, f.name)) for f in dataclasses.fields(plan)
            if isinstance(getattr(plan, f.name), list)}


class AppleSync:
    def __init__(self, ipod: IPod):
        self.ipod = ipod

    @on_device
    def ensure_database(self) -> None:
        """Create an empty database on a freshly restored/wiped iPod.

        A restore leaves ``iPod_Control`` in place but no iTunesDB until the
        first sync.  pyPodLib refuses (returns None) when the model needs a
        signature it can't produce yet, e.g. a Nano 5G without HashInfo.
        """
        from pypodlib.device.bootstrap import ensure_device_itunes_database
        from pypodlib.device.info import resolve_itdb_path

        if resolve_itdb_path(self.ipod.path):
            return
        if not ensure_device_itunes_database(self.ipod.path, self.ipod.info):
            raise RuntimeError(
                "This iPod has no music database yet and Clickwheel can't create a signed one for this "
                "model. Sync it once with iTunes/Finder (even with no music), then try again."
            )

    def _request(self, operation, library_root: Path, *, plan=None, allowed: set[Path] | None = None,
                 playlists: set[Path] | None = None, progress: ProgressFn | None = None,
                 cancelled: Callable[[], bool] | None = None) -> EngineRequest:
        lib = self.ipod.library(reload=True)
        caps = self.ipod.capabilities
        options = EngineOptions(
            supports_video=bool(getattr(caps, "supports_video", False)),
            supports_podcast=False,
            supports_photo=False,
            fpcalc_path=find_fpcalc(),
            allowed_paths=frozenset(str(p) for p in allowed) if allowed is not None else None,
            selected_playlist_paths=frozenset(str(p) for p in playlists) if playlists is not None else None,
        )

        def on_progress(ev) -> None:
            if progress:
                progress(_describe_progress(ev), ev.current, ev.total)

        return EngineRequest(
            operation=operation,
            ipod_path=self.ipod.path,
            pc_folders=(str(library_root),),
            ipod_tracks=tuple(t.data for t in lib.tracks),
            existing_playlists=tuple(p.data for p in lib.all_playlists),
            plan=plan,
            options=options,
            device_info=self.ipod.info,
            progress_callback=on_progress,
            is_cancelled=cancelled,
        )

    @on_device
    def plan(self, library_root: Path, **kw):
        out = SyncEngine().run(self._request(EngineOperation.PLAN, library_root, **kw))
        if not out.success:
            raise RuntimeError("; ".join(d.message for d in out.diagnostics) or "Planning failed")
        return out.result

    @on_device
    def sync(self, library_root: Path, *, allowed: set[Path] | None = None, playlists: set[Path] | None = None,
             progress: ProgressFn | None = None, cancelled: Callable[[], bool] | None = None) -> SyncSummary:
        kw = dict(allowed=allowed, playlists=playlists, progress=progress, cancelled=cancelled)
        self.ensure_database()
        plan = self.plan(library_root, **kw)
        counts = _plan_counts(plan)
        summary = SyncSummary(
            added=counts.get("to_add", 0),
            removed=counts.get("to_remove", 0),
            updated=sum(counts.get(k, 0) for k in ("to_update_metadata", "to_update_file", "to_update_artwork")),
            playlists=sum(counts.get(k, 0) for k in ("playlists_to_add", "playlists_to_edit", "playlists_to_remove")),
        )
        if any(counts.values()):
            out = SyncEngine().run(self._request(EngineOperation.EXECUTE, library_root, plan=plan, **kw))
            summary.errors = [d.message for d in out.diagnostics if d.fatal]
            if not out.success and not summary.errors:
                summary.errors = ["Sync failed"]
        if summary.ok and getattr(self.ipod.capabilities, "is_shuffle", False):
            self.write_itunessd()
        return summary

    @on_device
    def add_tracks(self, library_root: Path, paths: set[Path], *, progress: ProgressFn | None = None,
                   cancelled: Callable[[], bool] | None = None) -> SyncSummary:
        """Copy ``paths`` to the iPod without removing anything else.

        pyPodLib's selective mode mirrors the selection (unselected songs are
        removed), so widen the selection to every library song that is already
        on the device, and leave playlists as they are.
        """
        self.ensure_database()
        full = self.plan(library_root, progress=progress, cancelled=cancelled)
        missing = {Path(i.pc_track.path).resolve() for i in full.to_add if i.pc_track is not None}
        on_device = {p for p in _library_files(library_root) if p.resolve() not in missing}
        return self.sync(library_root, allowed=on_device | {Path(p) for p in paths}, playlists=set(),
                         progress=progress, cancelled=cancelled)

    @on_device
    def write_itunessd(self) -> Path:
        lib = self.ipod.library(reload=True)
        tracks, index_by_dbid = [], {}
        for t in _in_master_order(lib):
            location = (t.location or "").replace(":", "/")
            if not location:
                continue
            index_by_dbid[t.db_track_id] = len(tracks)
            tracks.append(itunessd.SdTrack(
                location=location, dbid=t.db_track_id, track_number=t.track_number,
                disc_number=t.disc_number, album_id=zlib.crc32(t.album.encode()),
                artist_id=zlib.crc32(t.artist.encode()),
            ))
        playlists = [
            itunessd.SdPlaylist(p.name, [index_by_dbid[i] for i in p.track_ids if i in index_by_dbid],
                                p.playlist_id or 0)
            for p in lib.playlists if not p.master
        ]
        version = getattr(self.ipod.capabilities, "shadow_db_version", 0) or 2
        return itunessd.write(Path(self.ipod.path), version, tracks, playlists)

    @on_device
    def browse(self) -> DeviceContents:
        from pypodlib.device.info import resolve_itdb_path

        if not resolve_itdb_path(self.ipod.path):
            return DeviceContents([], [])
        lib = self.ipod.library(reload=True)
        art = self._artwork_refs()
        tracks, index_by_dbid = [], {}
        for t in _in_master_order(lib):
            index_by_dbid[t.db_track_id] = len(tracks)
            tracks.append(DeviceTrack(
                title=t.title, artist=t.artist, album=t.album, track_number=t.track_number,
                duration=int(t.duration), play_count=t.play_count,
                location=(t.location or "").replace(":", "/"),
                artwork=art.get(t.db_track_id),
            ))
        playlists = [
            DevicePlaylist(p.name, [index_by_dbid[i] for i in p.track_ids if i in index_by_dbid], _playlist_key(p))
            for p in lib.playlists if not p.master
        ]
        shuffle = bool(getattr(self.ipod.capabilities, "is_shuffle", False))
        notice = ""
        if shuffle and not is_read_only(self.ipod.path) and (listed := self._itunessd_track_count()) != len(tracks):
            # Shuffles only play what iTunesSD lists. If a sync was cut off after the
            # database was written (e.g. the app was closed mid-sync), rebuild it.
            self.write_itunessd()
            notice = (f"Repaired the Shuffle's song list: it listed {listed or 0} of {len(tracks)} songs, "
                      "so the Shuffle could only play those.")
        return DeviceContents(tracks, playlists, ordered_library=shuffle, notice=notice)

    def _itunessd_track_count(self) -> int | None:
        path = Path(self.ipod.path) / "iPod_Control" / "iTunes" / "iTunesSD"
        try:
            data = path.read_bytes()
        except OSError:
            return None
        version = getattr(self.ipod.capabilities, "shadow_db_version", 0) or 2
        if version == 1:
            return int.from_bytes(data[:3], "big") if len(data) >= 3 else None
        return int.from_bytes(data[12:16], "little") if data[:4] == b"bdhs" else None

    # ── Editing what's on the device ─────────────────────────────────────

    def _commit(self) -> None:
        if not self.ipod.save(raise_on_error=False):
            raise RuntimeError("Writing the iPod database failed; nothing was changed.")
        if getattr(self.ipod.capabilities, "is_shuffle", False):
            self.write_itunessd()

    @on_device
    def delete_tracks(self, locations: set[str]) -> int:
        """Remove songs (by device location) from the database, then their files."""
        lib = self.ipod.library(reload=True)
        doomed = [t for t in lib.tracks if _loc(t) in locations]
        if not doomed:
            return 0
        for t in doomed:
            lib.remove_track(t)
        self._commit()  # database first: a failed write must not leave entries pointing at deleted files
        root = Path(self.ipod.path)
        for t in doomed:
            (root / _loc(t).lstrip("/")).unlink(missing_ok=True)
        # Drop pyPodLib's sync records for them too, or every later sync reports them as stale.
        from pypodlib.sync.mapping import MappingManager

        manager = MappingManager(self.ipod.path)
        mapping = manager.load()
        if any([mapping.remove_by_db_track_id(t.db_track_id) for t in doomed]):
            manager.save(mapping)
        return len(doomed)

    @on_device
    def reorder(self, playlist_id: str | None, locations: list[str]) -> None:
        """Set a playlist's order, or with ``None`` the master list (Shuffle play order)."""
        lib = self.ipod.library(reload=True)
        id_by_loc = {_loc(t): t.db_track_id for t in lib.tracks}
        ids = [id_by_loc[loc] for loc in locations if loc in id_by_loc]
        if playlist_id is None:
            master = lib.master_playlist
            rest = [i for i in (master.track_ids if master else []) if i not in set(ids)]
            order = {db_id: n for n, db_id in enumerate(ids + rest)}
            # Track rows and master playlist both carry the order; keep them in step.
            lib._tracks_data.sort(key=lambda d: order.get(int(d.get("db_track_id") or d.get("db_id") or 0), len(order)))
            if master is not None:
                master.track_ids = ids + rest
        else:
            playlist = next((p for p in lib.playlists if _playlist_key(p) == playlist_id), None)
            if playlist is None:
                raise RuntimeError("That playlist is no longer on the iPod.")
            playlist.track_ids = ids
        self._commit()

    def _artwork_refs(self) -> dict[int, ArtworkRef]:
        """Largest cover per track, keyed by db_track_id (ArtworkDB ``songId``)."""
        from pypodlib.artworkdb_parser.parser import parse_artworkdb

        art_dir = Path(self.ipod.path) / "iPod_Control" / "Artwork"
        try:
            db = parse_artworkdb(str(art_dir / "ArtworkDB"))
        except Exception:
            return {}
        refs: dict[int, ArtworkRef] = {}
        for entry in db.get("mhli", []):
            song_id = int(entry.get("songId") or 0)
            best = None
            for container in entry.get("_image_containers", []):
                r = (container.get("Thumbnail Image") or {}).get("result") or {}
                name = ((r.get(3) or {}).get("File Name") or "").lstrip(":")
                if not name or not r.get("imgSize"):
                    continue
                ref = ArtworkRef(str(art_dir / name.replace(":", "/")), int(r.get("ithmbOffset") or 0),
                                 int(r["imgSize"]), int(r.get("imageWidth") or 0), int(r.get("imageHeight") or 0),
                                 int(r.get("correlationID") or 0), int(r.get("horizontalPadding") or 0),
                                 int(r.get("verticalPadding") or 0))
                if best is None or ref.width * ref.height > best.width * best.height:
                    best = ref
            if song_id and best:
                refs[song_id] = best
        return refs
