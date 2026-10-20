"""Background work for the GUI. Signals emitted from worker threads are
delivered on the GUI thread by Qt's queued connections."""

from __future__ import annotations

import itertools
import queue
import threading
import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .. import auth
from ..config import Settings
from ..library import Library
from ..pipeline import Pipeline
from ..ytm import Collection, Resolver


class Task(QObject):
    """Run ``fn`` on a daemon thread; report the result or error back."""

    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    _alive: set[Task] = set()  # keep Python wrappers alive until finished

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs
        # Release on the GUI thread, after every queued slot has run. Dropping
        # the last reference on the worker thread would destroy this QObject
        # while its done/failed events are still pending -> segfault.
        self.done.connect(self._release)
        self.failed.connect(self._release)

    def start(self) -> Task:
        Task._alive.add(self)
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _release(self, *_args) -> None:
        QTimer.singleShot(0, lambda: Task._alive.discard(self))

    def _run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.done.emit(result)


def run(fn: Callable, *args, on_done=None, on_error=None, **kwargs) -> Task:
    task = Task(fn, *args, **kwargs)
    if on_done:
        task.done.connect(on_done)
    if on_error:
        task.failed.connect(on_error)
    return task.start()


class DownloadManager(QObject):
    """Serial queue of links/playlists to resolve and download.

    Every queued item is a job with an id, so views can follow each one from
    "waiting" through to its finished counts.
    """

    queued = Signal(int, str)              # job, label
    resolving = Signal(str)
    started = Signal(int, object)          # job, Collection
    track_event = Signal(int, object)      # job, TrackEvent
    finished = Signal(int, object, object)  # job, Collection, counts
    error = Signal(int, str, str)          # job, what, message
    library_changed = Signal()
    idle = Signal()

    def __init__(self, library: Library, settings: Settings):
        super().__init__()
        self.library = library
        self.settings = settings
        self._queue: queue.Queue[tuple[int, str, object, str, str | None]] = queue.Queue()
        self._ids = itertools.count(1)
        self._pipeline: Pipeline | None = None
        self._cancel_all = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def new_job(self) -> int:
        """Reserve a job id, for callers that want to track a job before it's queued."""
        return next(self._ids)

    # ``profile_id`` None means "whichever profile is active right now".
    def enqueue_url(self, url: str, profile_id: str | None = None, job: int | None = None) -> int:
        return self._put("url", url, url, profile_id, job)

    def enqueue_playlist(self, playlist_id: str, title: str, profile_id: str | None = None,
                         job: int | None = None) -> int:
        return self._put("playlist", playlist_id, title, profile_id, job)

    def enqueue_collection(self, collection: Collection, profile_id: str | None = None,
                           job: int | None = None) -> int:
        """Queue an already-resolved collection (e.g. a previewed playlist)."""
        return self._put("collection", collection, collection.title, profile_id, job)

    def _put(self, kind: str, ident, label: str, profile_id: str | None, job: int | None) -> int:
        job = job or self.new_job()
        self._queue.put((job, kind, ident, label, profile_id or self._active_id()))
        self.queued.emit(job, label)
        return job

    @staticmethod
    def _active_id() -> str | None:
        profile = auth.active_profile()
        return profile.id if profile else None

    def cancel(self) -> None:
        self._cancel_all.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        if self._pipeline:
            self._pipeline.cancel()

    def resolver(self, profile: auth.Profile | None) -> Resolver:
        return Resolver(auth.client(profile), cover_size=self.settings.cover_size,
                        prefer_album_versions=self.settings.prefer_album_versions)

    def _loop(self) -> None:
        while True:
            job, kind, ident, label, profile_id = self._queue.get()
            # A profile removed while its download was queued falls back to the active one.
            profile = auth.get_profile(profile_id) or auth.active_profile()
            self._cancel_all.clear()
            try:
                self.resolving.emit(label)
                resolver = self.resolver(profile)
                collection: Collection = (
                    ident if kind == "collection"
                    else resolver.resolve_url(ident) if kind == "url" else resolver.playlist_collection(ident)
                )
                if self._cancel_all.is_set():
                    continue
                self.started.emit(job, collection)
                self._pipeline = Pipeline(self.library, workers=self.settings.parallel_downloads,
                                          cover_size=self.settings.cover_size,
                                          cookies=auth.cookies_file(profile),
                                          profile_id=profile.id if profile else "")
                counts = self._pipeline.run(collection, lambda event: self.track_event.emit(job, event))
                self.finished.emit(job, collection, counts)
                self.library_changed.emit()
            except Exception as exc:
                traceback.print_exc()
                self.error.emit(job, label, str(exc) or type(exc).__name__)
            finally:
                self._pipeline = None
                if self._queue.empty():
                    self.idle.emit()
