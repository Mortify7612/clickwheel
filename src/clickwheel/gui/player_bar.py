"""Transport controls under the LCD: prev / play / stop / next, seek, volume."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

from .player import Player


class PlayerBar(QWidget):
    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
        self.player = player
        self._dragging = False

        def button(text: str, tip: str, slot, width: int = 36) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(width)
            b.clicked.connect(slot)
            return b

        self.prev_btn = button("⏮", "Previous", player.previous)
        self.play_btn = button("▶", "Play / pause", player.toggle, 44)
        self.stop_btn = button("■", "Stop", player.stop)
        self.next_btn = button("⏭", "Next", lambda: player.next())
        self.shuffle_btn = button("🔀", "Shuffle", lambda: player.set_shuffle(self.shuffle_btn.isChecked()))
        self.repeat_btn = button("🔁", "Repeat the queue", lambda: setattr(player, "repeat", self.repeat_btn.isChecked()))
        for b in (self.shuffle_btn, self.repeat_btn):
            b.setCheckable(True)

        self.seek = QSlider(Qt.Horizontal)
        self.seek.setToolTip("Seek")
        self.seek.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.seek.sliderReleased.connect(self._seek_released)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(player.volume * 100))
        self.volume.setFixedWidth(110)
        self.volume.setToolTip("Volume")
        self.volume.valueChanged.connect(lambda v: player.set_volume(v / 100))
        self.hint = QLabel("Double-click a song to play it")
        self.hint.setStyleSheet("color: palette(placeholder-text);")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for w in (self.prev_btn, self.play_btn, self.stop_btn, self.next_btn):
            layout.addWidget(w)
        layout.addSpacing(8)
        layout.addWidget(self.seek, 1)
        layout.addWidget(self.hint)
        layout.addSpacing(8)
        layout.addWidget(self.shuffle_btn)
        layout.addWidget(self.repeat_btn)
        layout.addWidget(QLabel("Vol"))
        layout.addWidget(self.volume)

        player.state_changed.connect(self._on_state)
        player.position_changed.connect(self._on_position)
        player.track_changed.connect(lambda item: self.hint.setVisible(item is None))
        self._on_state("stopped")

    def _on_state(self, state: str) -> None:
        self.play_btn.setText("❚❚" if state == "playing" else "▶")
        has_track = self.player.current is not None
        for b in (self.prev_btn, self.next_btn, self.stop_btn):
            b.setEnabled(has_track)
        self.seek.setEnabled(has_track)

    def _on_position(self, ms: int, duration: int) -> None:
        if duration > 0 and self.seek.maximum() != duration:
            self.seek.setRange(0, duration)
        if not self._dragging:
            self.seek.setValue(ms)

    def _seek_released(self) -> None:
        self._dragging = False
        self.player.seek(self.seek.value())
