"""Local playback with a live spectrum for the LCD level meter, and an optional equalizer.

Without the equalizer Qt plays the file itself. With it, Qt only decodes: the
audio comes back block by block, goes through the equalizer and is queued to
the sound card through a QAudioSink.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import (
    QAudioBuffer, QAudioBufferOutput, QAudioFormat, QAudioOutput, QAudioSink, QMediaDevices, QMediaPlayer,
)

from ..equalizer import Equalizer

FFT_SIZE = 2048
SINK_SECONDS = 0.2  # equalized audio waiting in the sound card's buffer
# Qt decodes by the system clock and the sound card plays by its own; if decoding runs
# ahead by more than this, the excess is dropped (a few milliseconds every few hours).
BACKLOG_SECONDS = 0.3
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


def buffer_to_frames(buffer: QAudioBuffer) -> tuple[np.ndarray, int] | None:
    """The buffer as float32 ``(frames, channels)`` in -1..1, and its sample rate."""
    fmt = buffer.format()
    kind = _DTYPES.get(fmt.sampleFormat())
    data = buffer.constData()
    channels = fmt.channelCount()
    if kind is None or data is None or not channels:
        return None
    dtype, scale = kind
    samples = scale(np.frombuffer(bytes(data), dtype=dtype))
    return samples[: len(samples) // channels * channels].reshape(-1, channels), fmt.sampleRate()


def buffer_to_mono(buffer: QAudioBuffer) -> tuple[np.ndarray, int] | None:
    converted = buffer_to_frames(buffer)
    if converted is None:
        return None
    frames, rate = converted
    return frames.mean(axis=1), rate


class Player(QObject):
    track_changed = Signal(object)        # PlayItem | None
    state_changed = Signal(str)           # "playing" | "paused" | "stopped"
    position_changed = Signal(int, int)   # position ms, duration ms
    spectrum = Signal(list)               # band levels 0..1
    error = Signal(str)
    equalizer_failed = Signal(str)        # the sound device can't take the equalized audio; it's off again

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
        self._start_at: int | None = None  # play from here once loaded (a podcast episode's place)
        self._resume_duration = 0
        self.equalizer = Equalizer()
        self._eq_on = False
        self._sink: QAudioSink | None = None
        self._sink_io = None
        self._sink_shape: tuple[int, int] | None = None  # (rate, channels) it was opened for
        self._sink_float = True
        self._frame_bytes = 8
        self._backlog = bytearray()  # equalized audio the sink had no room for yet
        self._feeder = QTimer(self, interval=10, timeout=self._feed_sink)
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

    def play_queue(self, items: list[PlayItem], start: int = 0, position: int = 0) -> None:
        """Play ``items`` from ``start``, ``position`` ms into it (to resume an episode)."""
        if not items:
            return
        self._queue = list(items)
        self._reorder(first=start)
        self._load_current()
        self._start_at = position or None

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

    def _load_current(self, flush: bool = True) -> None:
        """``flush=False`` when one song runs into the next, so the end of the last one still plays."""
        item = self.current
        if item is None:
            self.stop()
            return
        self._resume_at = self._start_at = None
        self._analyzer.reset()
        if flush:
            self._flush_sink()
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
        self._flush_sink()
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
        self._load_current(flush=not auto)

    def previous(self) -> None:
        if not self._order:
            return
        # Like most players: restart the song unless we're right at its start.
        if self._player.position() > 3000 or self._pos == 0:
            self._player.setPosition(0)
            self._flush_sink()
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
        self._flush_sink()

    def set_volume(self, fraction: float) -> None:
        self._output.setVolume(max(0.0, min(1.0, fraction)))
        if self._sink is not None:
            self._sink.setVolume(self._output.volume())

    @property
    def volume(self) -> float:
        return self._output.volume()

    @property
    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlayingState

    # ── Equalizer ────────────────────────────────────────────────────────

    @property
    def equalizer_on(self) -> bool:
        return self._eq_on

    def set_equalizer(self, enabled: bool, gains, preamp_db: float) -> None:
        self.equalizer.set(gains, preamp_db)
        if enabled == self._eq_on:
            return
        self._eq_on = enabled
        if enabled:
            self._player.setAudioOutput(None)  # Qt now only decodes; _on_buffer plays the result
        else:
            self._close_sink()
            self.equalizer.reset()
            self._player.setAudioOutput(self._output)

    def _give_up_equalizer(self, message: str) -> None:
        self.set_equalizer(False, self.equalizer.gains, self.equalizer.preamp)
        self.equalizer_failed.emit(message)

    def _open_sink(self, rate: int, channels: int) -> bool:
        self._close_sink()
        device = QMediaDevices.defaultAudioOutput()
        fmt = QAudioFormat()
        fmt.setSampleRate(rate)
        fmt.setChannelCount(channels)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        self._sink_float = device.isFormatSupported(fmt)
        if not self._sink_float:
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not device.isFormatSupported(fmt):
                self._give_up_equalizer(f"{device.description() or 'The sound device'} can't play through the "
                                        "equalizer, so it's off.")
                return False
        self._frame_bytes = channels * (4 if self._sink_float else 2)
        self._sink = QAudioSink(device, fmt, self)
        self._sink.setBufferSize(int(rate * SINK_SECONDS) * self._frame_bytes)
        self._sink.setVolume(self._output.volume())
        self._sink_io = self._sink.start()
        self._sink_shape = (rate, channels)
        self._feeder.start()
        return True

    def _close_sink(self) -> None:
        self._feeder.stop()
        self._backlog.clear()
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
        self._sink, self._sink_io, self._sink_shape = None, None, None

    def _flush_sink(self) -> None:
        """Drop queued audio that's no longer wanted (after a seek, a skip or a stop)."""
        self._backlog.clear()
        self.equalizer.reset()
        if self._sink is not None:
            self._sink.reset()
            self._sink_io = self._sink.start()

    def _queue_audio(self, frames: np.ndarray, rate: int) -> None:
        if (rate, frames.shape[1]) != self._sink_shape and not self._open_sink(rate, frames.shape[1]):
            return
        if self._sink_float:
            self._backlog += frames.astype("<f4", copy=False).tobytes()
        else:
            self._backlog += (frames * 32767).astype("<i2").tobytes()
        limit = int(rate * BACKLOG_SECONDS) * self._frame_bytes
        if len(self._backlog) > limit:
            del self._backlog[:len(self._backlog) - limit]
        self._feed_sink()

    def _feed_sink(self) -> None:
        # (Polled here: PySide can't pass QAudioSink.stateChanged's argument to Python.)
        if self._sink is not None and self._sink.error().name in ("OpenError", "FatalError"):
            self._give_up_equalizer("The sound device stopped taking the equalized audio, so the equalizer is off.")
            return
        if self._sink_io is None or not self._backlog:
            return
        room = min(self._sink.bytesFree(), len(self._backlog)) // self._frame_bytes * self._frame_bytes
        if room > 0:
            written = self._sink_io.write(bytes(self._backlog[:room]))
            if written > 0:
                del self._backlog[:written]

    # ── Qt callbacks ─────────────────────────────────────────────────────

    def _on_buffer(self, buffer: QAudioBuffer) -> None:
        if self._eq_on:
            converted = buffer_to_frames(buffer)
            if converted is None:
                return
            frames, rate = converted
            frames = np.clip(self.equalizer.process(frames, rate), -1.0, 1.0)
            self._queue_audio(frames, rate)
            if not self.is_playing:
                return
            samples = frames.mean(axis=1)
        else:
            if not self.is_playing:
                return
            converted = buffer_to_mono(buffer)
            if converted is None:
                return
            samples, rate = converted
        # Apply the output volume so the meter matches what you hear.
        self.spectrum.emit(self._analyzer.feed(samples * self._output.volume(), rate))

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.LoadedMedia and self._resume_at is not None:
            # A restored song: hold it paused where it was.
            position, self._resume_at = self._resume_at, None
            self._player.pause()
            self._player.setPosition(position)
        elif status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia) and self._start_at is not None:
            position, self._start_at = self._start_at, None
            self._player.setPosition(position)
        elif status == QMediaPlayer.EndOfMedia:
            self.next(auto=True)
        elif status == QMediaPlayer.InvalidMedia:
            self.error.emit(f"Can't play {self.current.path.name if self.current else 'this file'}")
            self.next(auto=True)

    def _on_state(self, state) -> None:
        name = {QMediaPlayer.PlayingState: "playing", QMediaPlayer.PausedState: "paused"}.get(state, "stopped")
        if self._sink is not None:  # hold what's queued while paused, so it carries on seamlessly
            if name == "paused":
                self._sink.suspend()
            elif name == "playing" and self._sink.state().name == "SuspendedState":
                self._sink.resume()
        if name != "playing":
            self.spectrum.emit([0.0] * self._analyzer.bands)
        self.state_changed.emit(name)
