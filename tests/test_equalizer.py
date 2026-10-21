import numpy as np
import pytest

from clickwheel.equalizer import BANDS, PRESETS, Equalizer, curve_db, design


def response_db(h: np.ndarray, rate: int, freq: float) -> float:
    n = 1 << 18
    spectrum = np.abs(np.fft.rfft(h, n))
    return float(20 * np.log10(spectrum[round(freq * n / rate)]))


@pytest.mark.parametrize("rate", [44100, 48000, 96000])
def test_each_band_lands_where_it_is_set(rate):
    gains = (6, -6, 3, -3, 9, -9, 4, -4, 2, -2)
    h = design(gains, 0, rate)
    for freq, gain in zip(BANDS, gains):
        assert response_db(h, rate, freq) == pytest.approx(gain, abs=0.6), freq


def test_preamp_shifts_everything():
    h = design(PRESETS["Flat"], -6, 44100)
    for freq in (40, 1000, 18000):
        assert response_db(h, 44100, freq) == pytest.approx(-6, abs=0.1)


def test_curve_is_level_beyond_the_outer_bands():
    gains = (5, 0, 0, 0, 0, 0, 0, 0, 0, -3)
    assert curve_db(np.array([20, 60, 16000, 20000]), gains).tolist() == pytest.approx([5, 5, -3, -3])


def test_flat_passes_audio_through():
    rng = np.random.default_rng(1)
    audio = rng.uniform(-0.5, 0.5, (4096, 2)).astype(np.float32)
    out = Equalizer().process(audio, 44100)
    np.testing.assert_allclose(out, audio, atol=1e-4)


def test_blocks_join_up_like_one_long_filter():
    rng = np.random.default_rng(2)
    audio = rng.uniform(-0.5, 0.5, (20000, 2)).astype(np.float32)
    eq = Equalizer()
    eq.set(PRESETS["Rock"], -3)
    sizes = [1024, 777, 4096, 1, 3000]
    pieces, start = [], 0
    while start < len(audio):
        size = sizes[len(pieces) % len(sizes)]
        pieces.append(eq.process(audio[start:start + size], 44100))
        start += size
    whole = np.stack([np.convolve(audio[:, c], design(PRESETS["Rock"], -3, 44100))[:len(audio)]
                      for c in range(2)], axis=1)
    np.testing.assert_allclose(np.concatenate(pieces), whole, atol=1e-4)


def test_settings_are_clamped_and_checked():
    eq = Equalizer()
    eq.set([30] * 10, -40)
    assert eq.gains == (12,) * 10 and eq.preamp == -12
    with pytest.raises(ValueError):
        eq.set([0] * 3, 0)
