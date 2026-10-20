"""Download -> tag -> file into library, for a whole playlist/album/track."""

from __future__ import annotations

import shutil
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .downloader import download_audio
from .library import Library
from .tagger import fetch_cover, library_relpath, write_tags
from .ytm import Collection, TrackMeta


class Status(str, Enum):
    QUEUED = "Queued"
    SKIPPED = "In library"
    DOWNLOADING = "Downloading"
    TAGGING = "Tagging"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass
class TrackEvent:
    index: int
    meta: TrackMeta
    status: Status
    progress: float = 0.0
    error: str = ""


EventFn = Callable[[TrackEvent], None]


class Pipeline:
    def __init__(self, library: Library, *, workers: int = 2, cover_size: int = 1000,
                 cookies: str | None = None, profile_id: str = ""):
        self.library = library
        self.cookies = cookies
        self.profile_id = profile_id
        self.workers = max(1, workers)
        self.cover_size = cover_size
        self._cancel = threading.Event()
        self._covers: dict[str, bytes | None] = {}
        self._covers_lock = threading.Lock()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self, collection: Collection, on_event: EventFn | None = None) -> dict[Status, int]:
        self._cancel.clear()
        emit = on_event or (lambda _e: None)
        counts: dict[Status, int] = {}
        resolved: list[str | None] = [None] * len(collection.tracks)

        with tempfile.TemporaryDirectory(prefix="clickwheel-") as tmp:
            def work(index: int, meta: TrackMeta) -> None:
                status = self._process(index, meta, Path(tmp), emit)
                counts[status] = counts.get(status, 0) + 1
                if status in (Status.DONE, Status.SKIPPED):
                    resolved[index] = self.library.resolve_id(meta.video_id) or meta.video_id

            for i, meta in enumerate(collection.tracks):
                emit(TrackEvent(i, meta, Status.QUEUED))
            with ThreadPoolExecutor(self.workers) as pool:
                list(pool.map(lambda args: work(*args), enumerate(collection.tracks)))

        if collection.kind != "track":
            # Keep the original order; drop failures so the playlist is still playable.
            self.library.save_playlist(collection.id, collection.title, collection.kind, collection.url,
                                       list(dict.fromkeys(v for v in resolved if v)), profile=self.profile_id)
        return counts

    def _process(self, index: int, meta: TrackMeta, tmp: Path, emit: EventFn) -> Status:
        if self._cancel.is_set():
            emit(TrackEvent(index, meta, Status.CANCELLED))
            return Status.CANCELLED
        if self.library.resolve_id(meta.video_id) or (
            meta.source_video_id and self.library.resolve_id(meta.source_video_id)
        ):
            emit(TrackEvent(index, meta, Status.SKIPPED, 1.0))
            return Status.SKIPPED
        try:
            emit(TrackEvent(index, meta, Status.DOWNLOADING))
            staged = download_audio(
                meta.video_id, tmp / meta.video_id,
                lambda p: emit(TrackEvent(index, meta, Status.DOWNLOADING, p)),
                cookies=self.cookies,
            )
            emit(TrackEvent(index, meta, Status.TAGGING, 1.0))
            write_tags(staged, meta, self._cover(meta))
            rel = self._unique_relpath(library_relpath(meta), meta.video_id)
            dest = self.library.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(staged, dest)
            self.library.add_track(meta, rel)
        except Exception as exc:
            emit(TrackEvent(index, meta, Status.FAILED, error=str(exc)))
            return Status.FAILED
        emit(TrackEvent(index, meta, Status.DONE, 1.0))
        return Status.DONE

    def _cover(self, meta: TrackMeta) -> bytes | None:
        key = meta.album_id or meta.cover_url
        with self._covers_lock:
            if key in self._covers:
                return self._covers[key]
        data = fetch_cover(meta.cover_url, self.cover_size)
        with self._covers_lock:
            self._covers[key] = data
        return data

    def _unique_relpath(self, rel: Path, video_id: str) -> Path:
        """Two different songs can share artist/album/title (e.g. live vs studio)."""
        if not (self.library.root / rel).exists():
            return rel
        return rel.with_name(f"{rel.stem} [{video_id}]{rel.suffix}")
