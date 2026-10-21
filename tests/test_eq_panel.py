import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from clickwheel.equalizer import PRESETS  # noqa: E402
from clickwheel.gui.eq_panel import CUSTOM, EqPanel  # noqa: E402


@pytest.fixture
def panel():
    QApplication.instance() or QApplication([])
    panel = EqPanel()
    panel.resize(900, 150)
    panel.show()
    edits = []
    panel.changed.connect(lambda: edits.append((panel.enabled, panel.gains, panel.preamp, panel.preset)))
    panel.edits = edits
    yield panel
    panel.close()
    shiboken6.delete(panel)


def knob_point(panel, index: int, db: float) -> QPoint:
    graph = panel.graph
    return QPoint(round(graph._column(index).center().x()), round(graph._y(db)))


def test_dragging_a_band_makes_a_custom_curve(panel):
    graph = panel.graph
    QTest.mousePress(graph, Qt.LeftButton, Qt.NoModifier, knob_point(panel, 0, 0))
    QTest.mouseMove(graph, knob_point(panel, 0, 6))
    QTest.mouseRelease(graph, Qt.LeftButton, Qt.NoModifier, knob_point(panel, 0, 6))
    assert panel.gains[0] == pytest.approx(6, abs=0.5)
    assert panel.preset == CUSTOM and panel.presets.currentText() == CUSTOM
    QTest.mouseDClick(graph, Qt.LeftButton, Qt.NoModifier, knob_point(panel, 0, 6))
    assert panel.gains[0] == 0 and panel.preset == "Flat"
    assert panel.presets.findText(CUSTOM) < 0  # gone again once it matches a preset
    assert panel.edits


def test_preamp_and_presets(panel):
    QTest.mousePress(panel.graph, Qt.LeftButton, Qt.NoModifier, knob_point(panel, -1, -12))
    QTest.mouseRelease(panel.graph, Qt.LeftButton, Qt.NoModifier, knob_point(panel, -1, -12))
    assert panel.preamp == -12
    assert panel.preset == "Flat"  # the preamp is a trim, not part of the preset
    panel.presets.activated.emit(panel.presets.findText("Rock"))
    assert panel.gains == list(map(float, PRESETS["Rock"])) and panel.preamp == -12
    panel.flat.click()
    assert panel.gains == [0.0] * 10 and panel.preamp == 0 and panel.preset == "Flat"


def test_power_and_restoring_saved_values(panel):
    panel.set_values(True, PRESETS["Jazz"], 1.5, "Jazz")
    assert not panel.edits  # restoring isn't an edit
    assert panel.enabled and panel.power.text() == "On" and panel.preset == "Jazz"
    assert panel.preamp == 1.5
    panel.power.click()
    assert panel.edits[-1][0] is False and panel.power.text() == "Off"


def test_deck_button_opens_and_closes_the_panel():
    pytest.importorskip("PySide6.QtMultimedia")
    from clickwheel.gui.player import Player
    from clickwheel.gui.player_bar import PlayerBar

    QApplication.instance() or QApplication([])
    bar = PlayerBar(Player(16))
    toggles = []
    bar.equalizer_toggled.connect(toggles.append)
    QTest.mouseClick(bar.eq_btn, Qt.LeftButton)
    QTest.mouseClick(bar.eq_btn, Qt.LeftButton)
    assert toggles == [True, False]
    player = bar.player
    shiboken6.delete(bar)  # the media player has threads: tear it down now, not at exit
    shiboken6.delete(player)
