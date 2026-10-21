"""A ten-band graphic equalizer for playback (Winamp's bands), in numpy.

The band gains define a smooth curve over log-frequency. That curve becomes a
minimum-phase FIR filter (no added latency, no pre-echo), applied to the audio
block by block with FFT overlap-add, so any block size works and changing the
settings mid-song doesn't click.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

BANDS = (60, 170, 310, 600, 1000, 3000, 6000, 12000, 14000, 16000)
LIMIT_DB = 12.0  # each band and the preamp go from -12 to +12 dB

PRESETS: dict[str, tuple[float, ...]] = {
    "Flat": (0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    "Bass boost": (7, 6, 4, 1.5, 0, 0, 0, 0, 0, 0),
    "Treble boost": (0, 0, 0, 0, 0, 1.5, 4, 6, 6.5, 7),
    "Rock": (5, 3, -2, -3.5, -1.5, 2, 4.5, 5.5, 5.5, 5.5),
    "Pop": (-1, 2.5, 4.5, 5, 3.5, 0, -1.5, -1.5, -1, -1),
    "Dance": (7, 5.5, 2, 0, 0, -3.5, -4.5, -4.5, 0, 0),
    "Jazz": (3.5, 2.5, 1, 2, -1.5, -1.5, 0, 1.5, 2.5, 3.5),
    "Classical": (0, 0, 0, 0, 0, 0, -4, -4, -4, -5.5),
    "Vocal": (-3, -2, 0, 3, 4.5, 4, 2.5, 0, -1, -1.5),
    "Loudness": (6, 4, 0, -1.5, -1, 0, 1, 4, 5, 5),
    "Small speakers": (4, 8, 4, -2, -1.5, 1, 3, 6, 8, 9),
}


def clamp_db(value: float) -> float:
    return max(-LIMIT_DB, min(LIMIT_DB, float(value)))


def curve_db(freqs: np.ndarray, gains: Sequence[float]) -> np.ndarray:
    """The gain in dB at each of ``freqs``: the bands joined by smooth (cosine) steps along
    log-frequency, level beyond the outermost bands."""
    xs = np.log2(np.asarray(BANDS, dtype=np.float64))
    g = np.asarray(gains, dtype=np.float64)
    x = np.log2(np.maximum(np.asarray(freqs, dtype=np.float64), 1.0))
    i = np.clip(np.searchsorted(xs, x), 1, len(xs) - 1)
    t = np.clip((x - xs[i - 1]) / (xs[i] - xs[i - 1]), 0.0, 1.0)
    t = (1 - np.cos(np.pi * t)) / 2
    return g[i - 1] + (g[i] - g[i - 1]) * t


def taps_for(rate: int) -> int:
    """Enough filter length to resolve the 60 Hz band (~10 Hz resolution) at any sample rate."""
    return 1 << max(10, math.ceil(math.log2(rate / 10)))


def design(gains: Sequence[float], preamp_db: float, rate: int, taps: int | None = None) -> np.ndarray:
    """A minimum-phase FIR whose magnitude follows :func:`curve_db` plus the preamp."""
    taps = taps or taps_for(rate)
    n = taps * 4  # a finer grid than the filter, so the cepstrum doesn't alias
    freqs = np.fft.rfftfreq(n, 1 / rate)
    log_mag = (curve_db(freqs, gains) + preamp_db) * (math.log(10) / 20)
    # Homomorphic minimum phase: fold the real cepstrum onto positive time.
    cepstrum = np.fft.irfft(log_mag, n)
    fold = np.zeros(n)
    fold[0] = fold[n // 2] = 1
    fold[1:n // 2] = 2
    h = np.fft.irfft(np.exp(np.fft.rfft(cepstrum * fold)), n)[:taps]
    fade = taps // 4  # taper the (tiny) truncated end
    h[-fade:] *= np.cos(np.linspace(0, np.pi / 2, fade)) ** 2
    return h.astype(np.float32)


class Equalizer:
    """Filters blocks of interleaved-as-columns audio, ``(frames, channels)`` float32."""

    def __init__(self):
        self.gains: tuple[float, ...] = PRESETS["Flat"]
        self.preamp = 0.0
        self._kernel: np.ndarray | None = None
        self._spectra: dict[int, np.ndarray] = {}  # the kernel's FFT, per FFT size
        self._tail: np.ndarray | None = None       # overlap carried into the next block
        self._shape: tuple[int, int] | None = None  # (rate, channels) the state belongs to

    def set(self, gains: Sequence[float], preamp_db: float) -> None:
        gains = tuple(clamp_db(g) for g in gains)
        preamp = clamp_db(preamp_db)
        if len(gains) != len(BANDS):
            raise ValueError(f"expected {len(BANDS)} band gains")
        if (gains, preamp) != (self.gains, self.preamp):
            self.gains, self.preamp = gains, preamp
            self._kernel = None  # redesigned on the next block; the tail carries on smoothly

    @property
    def is_flat(self) -> bool:
        return not any(self.gains) and not self.preamp

    def reset(self) -> None:
        """Forget the overlap (after a seek or a new song, where the audio isn't continuous)."""
        self._tail = None

    def process(self, block: np.ndarray, rate: int) -> np.ndarray:
        frames, channels = block.shape
        if (rate, channels) != self._shape:
            self._shape = (rate, channels)
            self._kernel, self._tail = None, None
        if self._kernel is None:
            self._kernel = design(self.gains, self.preamp, rate)
            self._spectra = {}
        taps = len(self._kernel)
        length = frames + taps - 1
        size = 1 << (length - 1).bit_length()
        spectrum = self._spectra.get(size)
        if spectrum is None:
            spectrum = self._spectra[size] = np.fft.rfft(self._kernel, size)
        out = np.fft.irfft(np.fft.rfft(block, size, axis=0) * spectrum[:, None], size, axis=0)[:length]
        if self._tail is not None:
            out[:len(self._tail)] += self._tail
        self._tail = out[frames:].copy()
        return out[:frames].astype(np.float32, copy=False)
