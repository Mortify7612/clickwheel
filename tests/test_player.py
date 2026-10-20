import numpy as np
import pytest

pytest.importorskip("PySide6.QtMultimedia")

from clickwheel.gui.player import SpectrumAnalyzer  # noqa: E402


def tone(freq: float, rate: int = 44100, seconds: float = 0.1, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(rate * seconds)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


@pytest.mark.parametrize("freq", [100, 1000, 6000])
def test_tone_lights_its_own_band(freq):
    analyzer = SpectrumAnalyzer(16)
    levels = analyzer.feed(tone(freq), 44100)
    edges = np.geomspace(analyzer.low_hz, analyzer.high_hz, 17)
    expected = int(np.searchsorted(edges, freq) - 1)
    assert int(np.argmax(levels)) == expected
    assert levels[expected] > 0.6


def test_silence_is_flat():
    assert max(SpectrumAnalyzer(16).feed(np.zeros(4096, np.float32), 48000)) == 0.0


def test_quieter_is_lower():
    analyzer = SpectrumAnalyzer(16)
    loud = max(analyzer.feed(tone(1000, amp=0.8), 44100))
    analyzer.reset()
    quiet = max(analyzer.feed(tone(1000, amp=0.02), 44100))
    assert loud > quiet


def test_stereo_int16_buffer_becomes_mono_float():
    from PySide6.QtCore import QByteArray
    from PySide6.QtMultimedia import QAudioBuffer, QAudioFormat

    from clickwheel.gui.player import buffer_to_mono

    fmt = QAudioFormat()
    fmt.setSampleRate(48000)
    fmt.setChannelCount(2)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    left_right = np.array([16384, -16384, 8192, 8192], dtype=np.int16)  # two stereo frames
    samples, rate = buffer_to_mono(QAudioBuffer(QByteArray(left_right.tobytes()), fmt))
    assert rate == 48000
    np.testing.assert_allclose(samples, [0.0, 0.25])
