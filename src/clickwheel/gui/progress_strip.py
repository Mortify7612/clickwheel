"""A progress bar with its caption above it rather than painted over it.

The themes draw the bar as beads, LEDs or segments; text laid over those is
hard to read wherever the bar has filled, so the words get their own line.
"""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QProgressBar, QWidget

from .collection_header import _ElidedLabel


class ProgressStrip(QWidget):
    """``text`` on the left, a count such as "21 / 300" on the right, the bar underneath.

    ``count`` is a format like QProgressBar's (``%v``, ``%m``, ``%p``); it shows only
    while the bar has a real range, not while it is busy (range 0..0).
    """

    def __init__(self, count: str = "%v / %m", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._count = count
        self.caption = _ElidedLabel()
        self.counter = QLabel()
        self.counter.setStyleSheet("color: palette(placeholder-text);")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.valueChanged.connect(self._show_count)
        layout = QGridLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(3)
        layout.addWidget(self.caption, 0, 0)
        layout.addWidget(self.counter, 0, 1)
        layout.addWidget(self.bar, 1, 0, 1, 2)
        layout.setColumnStretch(0, 1)

    def setText(self, text: str) -> None:
        self.caption.setText(text)

    def text(self) -> str:
        return self.caption.text()

    def setCount(self, count: str) -> None:
        """The count's format; "" hides it."""
        self._count = count
        self._show_count()

    def setRange(self, low: int, high: int) -> None:
        self.bar.setRange(low, high)
        self._show_count()

    def setValue(self, value: int) -> None:
        self.bar.setValue(value)

    def value(self) -> int:
        return self.bar.value()

    def maximum(self) -> int:
        return self.bar.maximum()

    def _show_count(self) -> None:
        low, high, value = self.bar.minimum(), self.bar.maximum(), self.bar.value()
        busy = high <= low or value < low
        percent = round(100 * (value - low) / (high - low)) if not busy else 0
        text = "" if busy or not self._count else (
            self._count.replace("%v", str(value)).replace("%m", str(high)).replace("%p", str(percent)))
        self.counter.setText(text)
        self.counter.setVisible(bool(text))
