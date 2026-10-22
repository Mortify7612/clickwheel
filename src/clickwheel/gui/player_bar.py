"""The player deck under the LCD: now playing, transport controls, seek, volume.

Three zones, like a hardware deck: what's playing on the left (cover, title,
artist), the transport in the middle with the seek bar under it, volume on
the right. Theme stylesheets dress it through the ``PlayerDeck``,
``PlayButton`` and ``DeckButton`` object names.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QStyle, QStyleOptionSlider, QVBoxLayout,
)

from . import icons
from .artwork import CoverCache, album_key, placeholder
from .player import PlayItem, Player

ART = 52


class _ElidedLabel(QLabel):
    """One line of text that ends in "…" rather than pushing the layout wider."""

    def minimumSizeHint(self) -> QSize:
        return QSize(20, super().minimumSizeHint().height())

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        p.drawText(self.rect(), int(self.alignment()), text)


class _ClickSlider(QSlider):
    """A slider that jumps to wherever you click on it, then drags from there."""

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.maximum() > self.minimum():
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            style = self.style()
            handle = style.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
            pos = event.position().toPoint()
            if not handle.contains(pos):
                groove = style.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
                x = pos.x() - groove.x() - handle.width() // 2
                span = max(1, groove.width() - handle.width())
                self.setValue(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), x, span,
                                                             opt.upsideDown))
        # With the handle now under the pointer, the normal press starts a drag.
        super().mousePressEvent(event)


def _time(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


class PlayerBar(QFrame):
    equalizer_toggled = Signal(bool)  # show / hide the equalizer panel

    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
        self.setObjectName("PlayerDeck")
        self.setFrameShape(QFrame.StyledPanel)
        self.player = player
        self._dragging = False
        self._unmuted = player.volume or 0.7
        self.covers = CoverCache(self)
        self.covers.loaded.connect(self._on_cover)
        self._cover_key: str | None = None

        # Now playing
        self.art = QLabel()
        self.art.setFixedSize(ART, ART)
        self.title = _ElidedLabel()
        title_font = QFont()  # size and weight only, so the family follows the theme
        title_font.setPointSizeF(10.5)
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.subtitle = _ElidedLabel()
        self.subtitle.setStyleSheet("color: palette(placeholder-text);")
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addStretch(1)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        text.addStretch(1)
        now = QHBoxLayout()
        now.setSpacing(10)
        now.addWidget(self.art)
        now.addLayout(text, 1)

        # Transport
        def button(name: str, tip: str, slot, checkable: bool = False) -> QPushButton:
            b = QPushButton()
            b.setObjectName("DeckButton")
            b.setFlat(True)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFixedSize(34, 34)
            b.setIconSize(QSize(20, 20))
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            b.setProperty("icon_name", name)
            return b

        self.shuffle_btn = button("shuffle", "Shuffle", lambda on: player.set_shuffle(on), checkable=True)
        self.prev_btn = button("previous", "Previous", player.previous)
        self.next_btn = button("next", "Next", lambda: player.next())
        self.repeat_btn = button("repeat", "Repeat the queue", lambda on: setattr(player, "repeat", on), checkable=True)
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("PlayButton")
        self.play_btn.setToolTip("Play / pause")
        self.play_btn.setFixedSize(42, 42)
        self.play_btn.setIconSize(QSize(22, 22))
        self.play_btn.setFocusPolicy(Qt.NoFocus)
        self.play_btn.clicked.connect(player.toggle)
        transport = QHBoxLayout()
        transport.setSpacing(6)
        transport.addStretch(1)
        for w in (self.shuffle_btn, self.prev_btn, self.play_btn, self.next_btn, self.repeat_btn):
            transport.addWidget(w, 0, Qt.AlignVCenter)
        transport.addStretch(1)

        self.elapsed = QLabel("0:00")
        self.remaining = QLabel("-0:00")
        for label, align in ((self.elapsed, Qt.AlignRight), (self.remaining, Qt.AlignLeft)):
            label.setAlignment(align | Qt.AlignVCenter)
            label.setStyleSheet("color: palette(placeholder-text);")
        self.seek = _ClickSlider(Qt.Horizontal)
        self.seek.setObjectName("SeekSlider")
        self.seek.setToolTip("Click or drag to seek")
        self.seek.sliderPressed.connect(self._seek_pressed)
        self.seek.sliderReleased.connect(self._seek_released)
        self.seek.sliderMoved.connect(lambda ms: self._show_time(ms, self.seek.maximum()))
        seek_row = QHBoxLayout()
        seek_row.setSpacing(8)
        seek_row.addWidget(self.elapsed)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.remaining)
        middle = QVBoxLayout()
        middle.setSpacing(2)
        middle.addLayout(transport)
        middle.addLayout(seek_row)

        # Volume
        self.mute_btn = button("volume", "Mute", self._toggle_mute)
        # (A lambda: PySide passes no arguments when the slot is a signal's own emit.)
        self.eq_btn = button("eq", "Equalizer", lambda on: self.equalizer_toggled.emit(on), checkable=True)
        self.volume = _ClickSlider(Qt.Horizontal)
        self.volume.setObjectName("VolumeSlider")
        self.volume.setRange(0, 100)
        self.volume.setValue(int(player.volume * 100))
        self.volume.setFixedWidth(110)
        self.volume.setToolTip("Volume")
        self.volume.valueChanged.connect(self._on_volume)
        volume = QHBoxLayout()
        volume.setSpacing(4)
        volume.addStretch(1)
        volume.addWidget(self.eq_btn)
        volume.addSpacing(6)
        volume.addWidget(self.mute_btn)
        volume.addWidget(self.volume)

        grid = QGridLayout(self)
        grid.setContentsMargins(10, 8, 14, 8)
        grid.setHorizontalSpacing(18)
        grid.addLayout(now, 0, 0)
        grid.addLayout(middle, 0, 1)
        grid.addLayout(volume, 0, 2)
        # Side zones share the width equally, so the transport stays centred.
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 4)
        grid.setColumnStretch(2, 3)

        player.state_changed.connect(self._on_state)
        player.position_changed.connect(self._on_position)
        player.track_changed.connect(self._on_track)
        self._on_track(None)
        self._on_state("stopped")
        self.refresh_icons()

    def sync_from_player(self) -> None:
        """Match the toggles and volume to the player (after it restores a saved session)."""
        self.shuffle_btn.setChecked(self.player.shuffle)
        self.repeat_btn.setChecked(self.player.repeat)
        self.volume.setValue(round(self.player.volume * 100))
        self._on_state("paused" if self.player.current is not None else "stopped")

    # ── Theme ────────────────────────────────────────────────────────────

    def refresh_icons(self) -> None:
        """Repaint the icons in the current theme's colours (call after a theme change)."""
        accent = self.palette().color(QPalette.Link)
        for b in (self.shuffle_btn, self.prev_btn, self.next_btn, self.repeat_btn, self.mute_btn, self.eq_btn):
            name = b.property("icon_name")
            if b is self.mute_btn and self.volume.value() == 0:
                name = "muted"
            color = b.palette().color(QPalette.ButtonText)
            b.setIcon(icons.icon(name, color, accent if b.isCheckable() else None))
        playing = self.player.is_playing
        self.play_btn.setIcon(icons.icon("pause" if playing else "play",
                                         self.play_btn.palette().color(QPalette.ButtonText), size=22))
        self._show_art()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.PaletteChange):
            self.refresh_icons()

    # ── Player ───────────────────────────────────────────────────────────

    def _on_state(self, state: str) -> None:
        has_track = self.player.current is not None
        for b in (self.prev_btn, self.next_btn):
            b.setEnabled(has_track)
        self.seek.setEnabled(has_track)
        self.play_btn.setToolTip("Pause" if state == "playing" else "Play")
        self.refresh_icons()

    def _on_track(self, item: PlayItem | None) -> None:
        if item is None:
            self.title.setText("Not playing")
            self.subtitle.setText("Double-click a song to play it")
            self._cover_key = None
            self._show_time(0, 0)
        else:
            self.title.setText(item.title)
            self.subtitle.setText(" · ".join(part for part in (item.artist, item.album) if part))
            self._cover_key = album_key(item.artist, item.album) if item.album else str(item.path)
            self.covers.request(self._cover_key, item.path)
        self.title.update()
        self.subtitle.update()
        self._show_art()

    def _on_cover(self, key: str) -> None:
        if key == self._cover_key:
            self._show_art()

    def _show_art(self) -> None:
        key = self._cover_key
        pix = self.covers.large(key) if key and self.covers.has(key) else placeholder(key or "", ART)
        self.art.setPixmap(pix.scaled(ART, ART, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _on_position(self, ms: int, duration: int) -> None:
        if duration > 0 and self.seek.maximum() != duration:
            self.seek.setRange(0, duration)
        if not self._dragging:
            self.seek.setValue(ms)
            self._show_time(ms, duration)

    def _show_time(self, ms: int, duration: int) -> None:
        self.elapsed.setText(_time(ms))
        self.remaining.setText(f"-{_time(max(0, duration - ms))}")

    def _seek_pressed(self) -> None:
        self._dragging = True
        self._show_time(self.seek.value(), self.seek.maximum())

    def _seek_released(self) -> None:
        self._dragging = False
        self.player.seek(self.seek.value())

    # ── Volume ───────────────────────────────────────────────────────────

    def _on_volume(self, value: int) -> None:
        self.player.set_volume(value / 100)
        self.mute_btn.setToolTip("Unmute" if value == 0 else "Mute")
        self.refresh_icons()

    def _toggle_mute(self) -> None:
        if self.volume.value():
            self._unmuted = self.volume.value() / 100
            self.volume.setValue(0)
        else:
            self.volume.setValue(int((self._unmuted or 0.7) * 100))
