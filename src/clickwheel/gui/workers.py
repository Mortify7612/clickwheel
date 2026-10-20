"""Background work for the GUI. Signals emitted from worker threads are
delivered on the GUI thread by Qt's queued connections."""

from __future__ import annotations

import queue
import threading
import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .. import auth
from ..config import Settings
from ..library import Library
from ..pipeline import Pipeline, TrackEvent
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
    """Serial queue of links/playlists to resolve and download."""

    resolving = Signal(str)
    started = Signal(object)          # Collection
    track_event = Signal(object)      # TrackEvent
    finished = Signal(object, object)  # Collection, counts
    error = Signal(str, str)          # what, message
    library_changed = Signal()
    idle = Signal()

    def __init__(self, library: Library, settings: Settings):
        super().__init__()
        self.library = library
        self.settings = settings
        self._queue: queue.Queue[tuple[str, str, str]] = queue.Queue()
        self._pipeline: Pipeline | None = None
        self._cancel_all = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def enqueue_url(self, url: str) -> None:
        self._queue.put(("url", url, url))

    def enqueue_playlist(self, playlist_id: str, title: str) -> None:
        self._queue.put(("playlist", playlist_id, title))

    def cancel(self) -> None:
        self._cancel_all.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        if self._pipeline:
            self._pipeline.cancel()

    def _resolver(self) -> Resolver:
        return Resolver(auth.client(), cover_size=self.settings.cover_size,
                        prefer_album_versions=self.settings.prefer_album_versions)

    def _loop(self) -> None:
        while True:
            kind, ident, label = self._queue.get()
            self._cancel_all.clear()
            try:
                self.resolving.emit(label)
                resolver = self._resolver()
                collection: Collection = (
                    resolver.resolve_url(ident) if kind == "url" else resolver.playlist_collection(ident)
                )
                if self._cancel_all.is_set():
                    continue
                self.started.emit(collection)
                self._pipeline = Pipeline(self.library, workers=self.settings.parallel_downloads,
                                          cover_size=self.settings.cover_size)
                counts = self._pipeline.run(collection, self._on_event)
                self.finished.emit(collection, counts)
                self.library_changed.emit()
            except Exception as exc:
                traceback.print_exc()
                self.error.emit(label, str(exc) or type(exc).__name__)
            finally:
                self._pipeline = None
                if self._queue.empty():
                    self.idle.emit()

    def _on_event(self, event: TrackEvent) -> None:
        self.track_event.emit(event)
