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


@pytest.fixture
def player():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication

    from clickwheel.gui.player import Player

    QCoreApplication.instance() or QCoreApplication([])
    player = Player(16)
    yield player
    import shiboken6

    player.stop()
    shiboken6.delete(player)  # the media player has threads: tear it down now, not at exit


def saved_state(library, position=61_000):
    tracks = library.tracks()
    return {
        "queue": [{"path": str(library.root / t.relpath), "title": t.title, "artist": t.artist, "album": t.album}
                  for t in tracks],
        "order": [2, 0, 1], "pos": 1, "position": position, "duration": 200_000,
        "shuffle": True, "repeat": True, "volume": 0.4,
    }


def test_restore_picks_up_the_saved_song_and_place(library, player):
    state = saved_state(library)
    assert player.restore(state)
    assert player.current.title == library.tracks()[0].title  # order[pos] == 0
    assert (player.shuffle, player.repeat) == (True, True)
    assert player.volume == pytest.approx(0.4, abs=0.01)
    snap = player.snapshot()
    # Saving again before the song has loaded keeps the restored place, not 0.
    assert snap["position"] == 61_000
    assert (snap["order"], snap["pos"]) == ([2, 0, 1], 1)
    assert [i["path"] for i in snap["queue"]] == [i["path"] for i in state["queue"]]


def test_restore_refuses_stale_or_broken_saves(library, player):
    assert not player.restore({})
    assert not player.restore({**saved_state(library), "order": [0, 0, 1]})
    assert not player.restore({**saved_state(library), "pos": 7})
    gone = saved_state(library)
    gone["queue"][0]["path"] = str(library.root / "deleted.m4a")
    assert not player.restore(gone)
    assert player.current is None and player.snapshot() is None


def run_events(ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_equalizer_plays_through_the_sound_card(library, player):
    from PySide6.QtMultimedia import QMediaDevices

    from clickwheel.equalizer import PRESETS
    from clickwheel.gui.player import PlayItem

    if QMediaDevices.defaultAudioOutput().isNull():
        pytest.skip("no sound device")
    player.set_volume(0.0)  # silent: this runs on real speakers
    levels = []
    player.spectrum.connect(levels.append)
    items = [PlayItem(library.root / t.relpath, t.title, t.artist) for t in library.tracks()]
    player.play_queue(items, 0)
    run_events(400)
    player.set_equalizer(True, PRESETS["Rock"], -3)  # switched on mid-song
    run_events(1200)
    assert player.is_playing and player._sink is not None
    assert player._sink.processedUSecs() > 600_000
    assert levels  # the meter keeps running (flat at volume 0)
    player.seek(0)
    assert not player._backlog
    run_events(300)
    player.set_equalizer(False, PRESETS["Rock"], -3)
    assert player._sink is None
    run_events(300)
    assert player.is_playing
    player.stop()
