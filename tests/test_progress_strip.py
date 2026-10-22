import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from clickwheel.gui.progress_strip import ProgressStrip  # noqa: E402


def test_caption_and_count_stay_off_the_bar():
    QApplication.instance() or QApplication([])
    strip = ProgressStrip("%v / %m songs")
    assert not strip.bar.isTextVisible()
    strip.setRange(0, 0)
    strip.setText("Starting…")
    assert strip.text() == "Starting…" and strip.counter.isHidden()  # busy: no count yet
    strip.setRange(0, 300)
    strip.setValue(21)
    assert strip.counter.text() == "21 / 300 songs" and not strip.counter.isHidden()
    strip.setCount("%p%")
    assert strip.counter.text() == "7%"
    strip.setCount("")
    assert strip.counter.isHidden()
    shiboken6.delete(strip)
