"""iPod tab: detect devices, choose what to sync, sync, eject."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..config import Settings
from ..devices import Device, identify, scan
from ..library import Library
from . import icons, workers
from .device_browser import DeviceBrowser
from .fonts import label_font, ui_font
from .progress_strip import ProgressStrip
from .table_style import _tint
from .theme import is_retro


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


class _StorageBar(QWidget):
    """A thin capacity bar: how full the iPod is."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.used = 0.0
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMaximumWidth(360)

    def set_used(self, fraction: float) -> None:
        self.used = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        track = QPainterPath()
        track.addRoundedRect(rect, 3, 3)
        p.fillPath(track, _tint(self.palette().color(QPalette.WindowText), 40))
        if self.used:
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(rect.left(), rect.top(), rect.width() * self.used, rect.height()), 3, 3)
            p.fillPath(fill, self.palette().color(QPalette.Link))


class DevicePage(QWidget):
    busy = Signal(bool)      # a sync started / finished
    activity = Signal(str)   # current sync phase, for the LCD display
    GLYPH = "ipod"  # the header's device drawing (see icons)
    CAN_CHOOSE_FOLDER = True  # an MTP player has no folder to point at
    CAN_EJECT = True  # ...and nothing to flush: it's safe to unplug when idle

    def __init__(self, library: Library, settings: Settings, noun: str = "iPod"):
        super().__init__()
        self.library = library
        self.settings = settings
        self.noun = noun  # what the user calls the device, in messages
        self.devices: list[Device] = []
        self._cancel = threading.Event()
        self._syncing = False
        self._editing = False  # the browser is writing an edit to the device
        self._phase = ""
        self._browsed_path: Path | None = None

        # ── Header: the iPod, how full it is, and what to do with it ──
        self.icon = QLabel()
        self.icon.setFixedSize(56, 56)
        self.icon.setAlignment(Qt.AlignCenter)
        self.kind = QLabel(noun)
        self.name = QLabel()
        self.meta = QLabel()
        self.meta.setStyleSheet("color: palette(placeholder-text);")
        self.storage = _StorageBar()
        self.plan = QLabel()  # what Sync will do; links to the What to sync tab
        self.plan.linkActivated.connect(lambda _href: self.bottom.setCurrentWidget(self.what))
        self.combo = QComboBox()  # only shown with more than one iPod plugged in
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(24)
        self.combo.currentIndexChanged.connect(self._show_device)
        self.combo.hide()
        self.sync_btn = QPushButton("Sync")
        self.sync_btn.setDefault(True)
        self.sync_btn.setAutoDefault(False)
        self.sync_btn.clicked.connect(self._sync_or_cancel)
        self.eject_btn = QPushButton("Eject")
        self.eject_btn.setAutoDefault(False)
        self.eject_btn.clicked.connect(self._eject)
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.setAutoDefault(False)
        self.rescan_btn.clicked.connect(self.rescan)
        self.more_btn = QPushButton()
        self.more_btn.setToolTip("More")
        self.more_btn.setAutoDefault(False)
        self.more_btn.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0; }")
        more = QMenu(self.more_btn)
        more.addAction("Rescan", self.rescan)
        if self.CAN_CHOOSE_FOLDER:
            more.addAction("Choose folder…", self._choose_folder).setToolTip(
                "Point at an iPod's mount folder if it wasn't detected")
        self.more_btn.setMenu(more)
        self.folder_btn = QPushButton("Choose folder…")
        self.folder_btn.setToolTip("Point at an iPod's mount folder if it wasn't detected")
        self.folder_btn.setAutoDefault(False)
        self.folder_btn.clicked.connect(self._choose_folder)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.kind)
        text.addWidget(self.name)
        text.addWidget(self.meta)
        text.addSpacing(4)
        text.addWidget(self.storage)
        buttons = self.header_buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addStretch(1)
        for w in (self.combo, self.sync_btn, self.eject_btn, self.rescan_btn, self.folder_btn, self.more_btn):
            buttons.addWidget(w)
        side = QVBoxLayout()
        side.setSpacing(4)
        side.addStretch(1)
        side.addLayout(buttons)
        side.addWidget(self.plan, 0, Qt.AlignRight)
        side.addStretch(1)
        header = QHBoxLayout()
        header.setContentsMargins(4, 2, 4, 4)
        header.setSpacing(14)
        header.addWidget(self.icon, 0, Qt.AlignVCenter)
        header.addLayout(text, 1)
        header.addLayout(side)

        self.progress = ProgressStrip()  # only while syncing (and briefly after)
        self.progress.hide()
        self._hide_progress = QTimer(self, singleShot=True, interval=8000, timeout=self.progress.hide)
        self.ro_warning = QLabel()
        self.ro_warning.setWordWrap(True)
        self.ro_warning.setStyleSheet("color: #e0533d;")
        self.ro_warning.hide()

        # ── What to sync (its own tab) ──
        self.what = QWidget()
        wv = self.what_layout = QVBoxLayout(self.what)
        self.all_radio = QRadioButton("Entire library")
        self.some_radio = QRadioButton("Only these playlists / albums:")
        self.all_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.all_radio)
        group.addButton(self.some_radio)
        self.pick = QListWidget()
        self.pick.setSelectionMode(QAbstractItemView.NoSelection)
        self.some_radio.toggled.connect(self.pick.setEnabled)
        self.some_radio.toggled.connect(lambda _on: self._show_plan())
        self.pick.itemChanged.connect(lambda _item: self._show_plan())
        self.pick.setEnabled(False)
        mirror_note = QLabel(f"The {noun} is made to match the selection: other songs Clickwheel synced are "
                             "removed. To add songs without removing any, select them on the Library tab and use "
                             f"“Sync to {noun}” (or right-click them).")
        mirror_note.setWordWrap(True)
        mirror_note.setStyleSheet("color: palette(placeholder-text);")
        wv.addWidget(self.all_radio)
        wv.addWidget(self.some_radio)
        wv.addWidget(self.pick, 1)
        wv.addWidget(mirror_note)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)

        self.browser = DeviceBrowser(library, noun)
        self.browser.editing.connect(self._on_editing)
        self.bottom = QTabWidget()
        self.bottom.addTab(self.browser, f"On this {noun}")
        self.bottom.addTab(self.what, "What to sync")
        self.bottom.addTab(self.log, "Sync log")

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.ro_warning)
        layout.addWidget(self.progress)
        layout.addWidget(self.bottom, 1)
        self.restyle()

        self.refresh_choices()
        self._show_device()
        # Hot-plug: poll quietly for new mounts while idle.
        self._timer = QTimer(self, interval=4000, timeout=self._poll)
        self._timer.start()
        QTimer.singleShot(0, self.rescan)

    def restyle(self) -> None:
        """Fonts and icons for the current theme (call after a theme change)."""
        self.kind.setFont(label_font(7.5))
        self.kind.setStyleSheet("color: palette(link);")
        self.name.setFont(ui_font(16, QFont.Bold))
        self.icon.setPixmap(icons.pixmap(self.GLYPH, self.palette().color(QPalette.WindowText), 52))
        self.more_btn.setIcon(icons.icon("more", self.more_btn.palette().color(QPalette.ButtonText), size=16))
        self.browser.paint_list_icons()
        self._show_device()

    def _show_plan(self) -> None:
        """Say what Sync will do, linking to the tab that changes it."""
        if self.all_radio.isChecked():
            what = "the entire library"
        else:
            n = sum(1 for i in range(self.pick.count()) if self.pick.item(i).checkState() == Qt.Checked)
            what = "nothing yet" if not n else f"{n} playlist{'' if n == 1 else 's'} / album{'' if n == 1 else 's'}"
        self.plan.setText(f'Sync makes the {self.noun} match <a href="what" style="text-decoration: none;">{what}</a>')

    # ── Devices ──────────────────────────────────────────────────────────

    def rescan(self) -> None:
        workers.run(self._scan, on_done=self._set_devices, on_error=lambda m: self._log(f"Scan failed: {m}"))

    def _scan(self) -> list[Device]:
        return scan()

    def _no_device_text(self) -> str:
        return "No iPod found — plug one in, or choose its folder"

    def _no_device_hint(self) -> str:
        return "Plug one in (it's found automatically), or choose its folder if it isn't."

    def _poll(self) -> None:
        if not self._syncing and not self._editing and self.isVisible():
            self.rescan()

    def _set_devices(self, devices: list[Device], keep: Path | None = None) -> None:
        manual = [d for d in self.devices if d.path not in {x.path for x in devices} and d.path.exists()]
        merged = devices + manual
        # Labels too: a device can keep its path but change state (a Zune another program let go of).
        if [(d.path, d.label) for d in merged] == [(d.path, d.label) for d in self.devices] and keep is None:
            return
        current = keep or (self.current.path if self.current else None)
        self.devices = merged
        self.combo.blockSignals(True)
        self.combo.clear()
        for d in self.devices:
            self.combo.addItem(d.label)
        idx = next((i for i, d in enumerate(self.devices) if d.path == current), 0)
        self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)
        self.combo.setVisible(len(self.devices) > 1)
        self._show_device()

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "iPod mount folder")
        if not path:
            return
        dev = identify(Path(path))
        if dev is None:
            QMessageBox.warning(self, "Not an iPod",
                                "That folder has no iPod_Control or .rockbox folder.\n"
                                "If the iPod is brand new or was wiped, restore it once with iTunes/Finder.")
            return
        self.devices = [d for d in self.devices if d.path != dev.path]
        self._set_devices(self.devices + [dev], keep=dev.path)

    @property
    def current(self) -> Device | None:
        i = self.combo.currentIndex()
        return self.devices[i] if 0 <= i < len(self.devices) else None

    def _show_device(self) -> None:
        dev = self.current
        if dev is None or dev.path != self._browsed_path:
            self._browsed_path = dev.path if dev else None
            if not self._syncing:
                self.browser.load(dev, self.settings.rockbox_prefers_files)
        for w in (self.sync_btn, self.more_btn, self.storage, self.plan):
            w.setVisible(dev is not None)
        self.eject_btn.setVisible(dev is not None and self.CAN_EJECT)
        self.rescan_btn.setVisible(dev is None)
        self.folder_btn.setVisible(dev is None and self.CAN_CHOOSE_FOLDER)
        if dev is None:
            self.name.setText(f"No {self.noun} found")
            self.meta.setText(self._no_device_hint())
            self.ro_warning.hide()
            return
        name = dev.name.upper() if is_retro() else dev.name
        self.name.setText(name)
        self.name.setToolTip(dev.label)
        warning = self._describe(dev)
        self.ro_warning.setText(warning)
        self.ro_warning.setVisible(bool(warning))
        read_only = bool(warning)
        self.sync_btn.setEnabled(self._syncing or (not read_only and not self._editing))
        self.eject_btn.setEnabled(not self._syncing and not self._editing)
        self.browser.set_busy(read_only or self._syncing)
        self._show_plan()

    def _describe(self, dev: Device) -> str:
        """Fill in the details line and storage bar; returns why the device can't be changed, if it can't."""
        fw = "Rockbox" if dev.firmware == "rockbox" else "Apple firmware"
        if dev.firmware == "rockbox" and dev.has_apple_db:
            fw += " (dual-boot; " + ("syncing files" if self.settings.rockbox_prefers_files else "syncing Apple DB") + ")"
        if dev.is_shuffle:
            fw += " · Shuffle"
        parts = [dev.model, fw]
        try:
            free, total = dev.free_space()
            parts.append(f"{_gb(free)} free of {_gb(total)}")
            self.storage.set_used(1 - free / total if total else 0)
        except OSError:
            parts.append("storage unavailable")
            self.storage.set_used(0)
        self.meta.setText(" · ".join(parts))
        if not dev.read_only:
            return ""
        return ("This iPod is mounted read-only — usually because the system found filesystem errors "
                "(for example after it was unplugged without ejecting). Syncing and editing are off until "
                "it's repaired: on Linux, eject it, then run  sudo fsck.vfat -a /dev/<device>  and plug it back in.")

    def refresh_choices(self) -> None:
        checked = {self.pick.item(i).data(Qt.UserRole) for i in range(self.pick.count())
                   if self.pick.item(i).checkState() == Qt.Checked}
        self.pick.clear()
        for p in self.library.playlists():
            item = QListWidgetItem(f"{p.title} ({p.track_count})")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if p.id in checked else Qt.Unchecked)
            item.setData(Qt.UserRole, p.id)
            self.pick.addItem(item)
        self._show_plan()

    # ── Sync ─────────────────────────────────────────────────────────────

    def _selection(self) -> tuple[set[Path] | None, set[Path] | None]:
        if self.all_radio.isChecked():
            return None, None
        allowed: set[Path] = set()
        playlists: set[Path] = set()
        for i in range(self.pick.count()):
            item = self.pick.item(i)
            if item.checkState() != Qt.Checked:
                continue
            pid = item.data(Qt.UserRole)
            allowed |= {self.library.root / t.relpath for t in self.library.playlist_tracks(pid)}
            playlist = next((p for p in self.library.playlists() if p.id == pid), None)
            if playlist and playlist.kind == "playlist":
                playlists.add(self.library.m3u_path(playlist.title, pid))
        return allowed, playlists

    def _sync_or_cancel(self) -> None:
        if self._syncing:
            self._cancel.set()
            self.sync_btn.setEnabled(False)
            self._log("Cancelling after the current file…")
            return
        dev = self.current
        if dev is None:
            return
        allowed, playlists = self._selection()
        if allowed is not None and not allowed:
            QMessageBox.information(self, "Nothing selected", "Tick at least one playlist or album.")
            return
        extras = self._sync_extras(allowed)
        self._start_sync(dev, f"Syncing to {dev.label}…",
                         lambda b, **kw: b.sync(self.library.root, allowed=allowed, playlists=playlists,
                                                **extras, **kw))

    def _sync_extras(self, allowed: set[Path] | None) -> dict:
        """More keyword arguments for this device type's ``sync`` (none for an iPod)."""
        return {}

    def sync_songs(self, paths: list[Path]) -> None:
        """Add just these library files to the current device (nothing is removed)."""
        if self._syncing or self._editing:
            QMessageBox.information(self, f"{self.noun} busy", "Wait for the current sync or edit to finish.")
            return
        dev = self.current
        if dev is None:
            QMessageBox.information(self, f"No {self.noun}", self._no_device_text() + ".")
            return
        n = len(paths)
        self._start_sync(dev, f"Adding {n} song{'s' if n != 1 else ''} to {dev.label}…",
                         lambda b, **kw: b.add_tracks(self.library.root, set(paths), **kw))

    def _start_sync(self, dev: Device, title: str, job) -> None:
        try:
            backend = dev.backend(self.settings.rockbox_prefers_files)
        except RuntimeError as exc:
            QMessageBox.warning(self, "Can't sync", str(exc))
            return

        self._syncing = True
        self.busy.emit(True)
        self.activity.emit(title)
        self.browser.set_busy(True)
        self._cancel.clear()
        self.sync_btn.setText("Cancel")
        self.eject_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.setText("Starting…")
        self.progress.setCount("%v / %m")
        self._hide_progress.stop()
        self.progress.show()
        self._phase = ""
        self.bottom.setCurrentWidget(self.log)
        self._log(title)

        task = workers.Task(job, backend, progress=lambda msg, cur, tot: task.progress.emit((msg, cur, tot)),
                            cancelled=self._cancel.is_set)
        task.progress.connect(self._on_progress)
        task.done.connect(self._on_synced)
        task.failed.connect(self._on_sync_failed)
        task.start()

    def _on_progress(self, data) -> None:
        msg, cur, tot = data
        if tot:
            self.progress.setRange(0, tot)
            self.progress.setValue(cur)
        self.progress.setText(msg)
        # Per-song detail goes on the progress bar; the log gets one line per phase.
        phase = msg.split(" · ", 1)[0]
        if msg:
            self.activity.emit(msg)
        if phase and phase != self._phase:
            self._phase = phase
            self._log(phase)

    def _on_editing(self, busy: bool) -> None:
        self._editing = busy
        self.sync_btn.setEnabled(not busy and self.current is not None)
        self.eject_btn.setEnabled(not busy and self.current is not None)

    def _finish(self) -> None:
        self._syncing = False
        self.busy.emit(False)
        self.browser.set_busy(False)
        self.sync_btn.setText("Sync")
        self.sync_btn.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setCount("")
        self._hide_progress.start()  # leave the result up for a few seconds
        self._show_device()

    def _on_synced(self, summary) -> None:
        self._finish()
        self.browser.load(self.current, self.settings.rockbox_prefers_files)
        line = (f"Added {summary.added}, removed {summary.removed}, updated {summary.updated}, "
                f"playlists {summary.playlists}")
        if summary.ok:
            self.progress.setText("Sync complete")
            self._log("✔ " + line)
        else:
            self.progress.setText("Sync failed")
            self._log(f"✖ Sync failed (planned: {line.lower()})")
            for err in summary.errors:
                self._log("   " + err)

    def _on_sync_failed(self, message: str) -> None:
        self._finish()
        self.progress.setText("Sync failed")
        self._log(f"✖ Sync failed: {message}")
        QMessageBox.critical(self, "Sync failed", message)

    def _eject(self) -> None:
        dev = self.current
        if dev is None:
            return
        workers.run(dev.eject, on_done=lambda m: (self._log(f"⏏ {m}"), self.rescan()),
                    on_error=lambda m: self._log(f"Eject failed: {m}"))

    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)
