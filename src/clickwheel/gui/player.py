"""Local playback with a live spectrum for the LCD level meter."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioBuffer, QAudioBufferOutput, QAudioFormat, QAudioOutput, QMediaPlayer

FFT_SIZE = 2048
_DTYPES = {
    QAudioFormat.SampleFormat.UInt8: (np.uint8, lambda a: (a.astype(np.float32) - 128) / 128),
    QAudioFormat.SampleFormat.Int16: (np.int16, lambda a: a.astype(np.float32) / 32768),
    QAudioFormat.SampleFormat.Int32: (np.int32, lambda a: a.astype(np.float32) / 2147483648),
    QAudioFormat.SampleFormat.Float: (np.float32, lambda a: a),
}


@dataclass(frozen=True)
class PlayItem:
    path: Path
    title: str
    artist: str
    album: str = ""

    @property
    def label(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title


class SpectrumAnalyzer:
    """Turns PCM buffers into ``bands`` log-spaced levels in 0..1."""

    def __init__(self, bands: int, low_hz: float = 45.0, high_hz: float = 16000.0):
        self.bands = bands
        self.low_hz, self.high_hz = low_hz, high_hz
        self._ring = np.zeros(FFT_SIZE, dtype=np.float32)
        self._window = np.hanning(FFT_SIZE).astype(np.float32)
        self._edges: np.ndarray | None = None
        self._rate = 0

    def reset(self) -> None:
        self._ring[:] = 0

    def feed(self, samples: np.ndarray, rate: int) -> list[float]:
        """``samples``: mono float32 in -1..1."""
        if rate != self._rate:
            self._rate = rate
            freqs = np.geomspace(self.low_hz, min(self.high_hz, rate / 2 - 1), self.bands + 1)
            self._edges = np.clip((freqs / rate * FFT_SIZE).astype(int), 1, FFT_SIZE // 2)
            # Music has far less energy up high; tilt +3 dB/octave around 1 kHz like real analysers.
            centers = np.sqrt(freqs[:-1] * freqs[1:])
            self._tilt = 3.0 * np.log2(centers / 1000.0)
        n = min(len(samples), FFT_SIZE)
        self._ring = np.roll(self._ring, -n)
        self._ring[-n:] = samples[-n:]
        mags = np.abs(np.fft.rfft(self._ring * self._window)) / (FFT_SIZE / 4)
        levels = []
        for (lo, hi), tilt in zip(zip(self._edges[:-1], self._edges[1:]), self._tilt):
            peak = float(mags[lo:max(hi, lo + 1)].max())
            db = 20 * np.log10(peak + 1e-9) + tilt
            levels.append(float(np.clip((db + 68) / 58, 0.0, 1.0)))  # ~-68 dB .. -10 dB
        return levels


def buffer_to_mono(buffer: QAudioBuffer) -> tuple[np.ndarray, int] | None:
    fmt = buffer.format()
    kind = _DTYPES.get(fmt.sampleFormat())
    data = buffer.constData()
    if kind is None or data is None or not fmt.channelCount():
        return None
    dtype, scale = kind
    samples = scale(np.frombuffer(bytes(data), dtype=dtype))
    channels = fmt.channelCount()
    if channels > 1:
        samples = samples[: len(samples) // channels * channels].reshape(-1, channels).mean(axis=1)
    return samples, fmt.sampleRate()


class Player(QObject):
    track_changed = Signal(object)        # PlayItem | None
    state_changed = Signal(str)           # "playing" | "paused" | "stopped"
    position_changed = Signal(int, int)   # position ms, duration ms
    spectrum = Signal(list)               # band levels 0..1
    error = Signal(str)

    def __init__(self, bands: int, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._output = QAudioOutput(self)
        self._buffers = QAudioBufferOutput(self)
        self._player.setAudioOutput(self._output)
        self._player.setAudioBufferOutput(self._buffers)
        self._analyzer = SpectrumAnalyzer(bands)
        self._queue: list[PlayItem] = []
        self._order: list[int] = []   # play order into _queue (shuffled or not)
        self._pos = -1                # index into _order
        self.shuffle = False
        self.repeat = False
        self._resume_at: int | None = None  # restored position, applied once the song has loaded
        self._resume_duration = 0
        self.set_volume(0.7)

        self._buffers.audioBufferReceived.connect(self._on_buffer)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.positionChanged.connect(lambda ms: self.position_changed.emit(ms, self._player.duration()))
        self._player.errorOccurred.connect(lambda _e, msg: self.error.emit(msg or "Playback failed"))

    # ── Queue ────────────────────────────────────────────────────────────

    @property
    def current(self) -> PlayItem | None:
        return self._queue[self._order[self._pos]] if 0 <= self._pos < len(self._order) else None

    def play_queue(self, items: list[PlayItem], start: int = 0) -> None:
        if not items:
            return
        self._queue = list(items)
        self._reorder(first=start)
        self._load_current()

    def _reorder(self, first: int) -> None:
        indices = list(range(len(self._queue)))
        if self.shuffle:
            rest = [i for i in indices if i != first]
            random.shuffle(rest)
            self._order = [first, *rest]
            self._pos = 0
        else:
            self._order = indices
            self._pos = first

    def set_shuffle(self, on: bool) -> None:
        self.shuffle = on
        current = self._order[self._pos] if 0 <= self._pos < len(self._order) else 0
        if self._queue:
            self._reorder(first=current)

    def _load_current(self) -> None:
        item = self.current
        if item is None:
            self.stop()
            return
        self._resume_at = None
        self._analyzer.reset()
        self._player.setSource(QUrl.fromLocalFile(str(item.path)))
        self._player.play()
        self.track_changed.emit(item)

    # ── Saving and restoring (so a restart picks up where you left off) ──

    def snapshot(self) -> dict | None:
        """The queue, the song and how far into it, as plain data (None if nothing is loaded)."""
        if self.current is None:
            return None
        position = self._resume_at if self._resume_at is not None else self._player.position()
        return {
            "queue": [{"path": str(i.path), "title": i.title, "artist": i.artist, "album": i.album}
                      for i in self._queue],
            "order": self._order, "pos": self._pos,
            "position": position, "duration": self._player.duration() or self._resume_duration,
            "shuffle": self.shuffle, "repeat": self.repeat, "volume": self.volume,
        }

    def restore(self, state: dict) -> bool:
        """Load a :meth:`snapshot` paused at its position. False if it no longer makes sense
        (malformed, or the song's file has gone)."""
        try:
            queue = [PlayItem(Path(i["path"]), i["title"], i["artist"], i.get("album", "")) for i in state["queue"]]
            order, pos = [int(i) for i in state["order"]], int(state["pos"])
            position, duration = max(0, int(state.get("position", 0))), max(0, int(state.get("duration", 0)))
        except (KeyError, TypeError, ValueError):
            return False
        if sorted(order) != list(range(len(queue))) or not 0 <= pos < len(order):
            return False
        item = queue[order[pos]]
        if not item.path.exists():
            return False
        self._queue, self._order, self._pos = queue, order, pos
        self.shuffle, self.repeat = bool(state.get("shuffle")), bool(state.get("repeat"))
        if "volume" in state:
            self.set_volume(float(state["volume"]))
        self._resume_at, self._resume_duration = position, duration
        self._analyzer.reset()
        self._player.setSource(QUrl.fromLocalFile(str(item.path)))
        self.track_changed.emit(item)
        self.position_changed.emit(position, duration)
        self.state_changed.emit("paused")
        return True

    # ── Transport ────────────────────────────────────────────────────────

    def toggle(self) -> None:
        state = self._player.playbackState()
        if state == QMediaPlayer.PlayingState:
            self._player.pause()
        elif self.current is not None:
            if self._resume_at is not None:  # pressed play before the restored song finished loading
                self._player.setPosition(self._resume_at)
                self._resume_at = None
            self._player.play()

    def stop(self) -> None:
        self._player.stop()
        self.spectrum.emit([0.0] * self._analyzer.bands)

    def next(self, *, auto: bool = False) -> None:
        if not self._order:
            return
        if self._pos + 1 < len(self._order):
            self._pos += 1
        elif self.repeat:
            if self.shuffle:
                random.shuffle(self._order)
            self._pos = 0
        else:
            if auto:  # ran off the end of the queue
                self.stop()
                self._player.setPosition(0)
                return
            self._pos = len(self._order) - 1
        self._load_current()

    def previous(self) -> None:
        if not self._order:
            return
        # Like most players: restart the song unless we're right at its start.
        if self._player.position() > 3000 or self._pos == 0:
            self._player.setPosition(0)
            if self._player.playbackState() != QMediaPlayer.PlayingState:
                self._player.play()
            return
        self._pos -= 1
        self._load_current()

    def seek(self, ms: int) -> None:
        if self._resume_at is not None:  # still loading a restored song: seek once it's ready
            self._resume_at = ms
            return
        self._player.setPosition(ms)

    def set_volume(self, fraction: float) -> None:
        self._output.setVolume(max(0.0, min(1.0, fraction)))

    @property
    def volume(self) -> float:
        return self._output.volume()

    @property
    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlayingState

    # ── Qt callbacks ─────────────────────────────────────────────────────

    def _on_buffer(self, buffer: QAudioBuffer) -> None:
        if not self.is_playing:
            return
        converted = buffer_to_mono(buffer)
        if converted is not None:
            samples, rate = converted
            # Apply the output volume so the meter matches what you hear.
            self.spectrum.emit(self._analyzer.feed(samples * self._output.volume(), rate))

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.LoadedMedia and self._resume_at is not None:
            # A restored song: hold it paused where it was.
            position, self._resume_at = self._resume_at, None
            self._player.pause()
            self._player.setPosition(position)
        elif status == QMediaPlayer.EndOfMedia:
            self.next(auto=True)
        elif status == QMediaPlayer.InvalidMedia:
            self.error.emit(f"Can't play {self.current.path.name if self.current else 'this file'}")
            self.next(auto=True)

    def _on_state(self, state) -> None:
        name = {QMediaPlayer.PlayingState: "playing", QMediaPlayer.PausedState: "paused"}.get(state, "stopped")
        if name != "playing":
            self.spectrum.emit([0.0] * self._analyzer.bands)
        self.state_changed.emit(name)
