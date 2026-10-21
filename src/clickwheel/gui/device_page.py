"""iPod tab: detect devices, choose what to sync, sync, eject."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..config import Settings
from ..devices import Device, identify, scan
from ..library import Library
from . import workers
from .device_browser import DeviceBrowser


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


class DevicePage(QWidget):
    busy = Signal(bool)      # a sync started / finished
    activity = Signal(str)   # current sync phase, for the LCD display

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

        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._show_device)
        rescan = QPushButton("Rescan")
        rescan.clicked.connect(self.rescan)
        self.manual_btn = QPushButton("Choose folder…")
        self.manual_btn.setToolTip("Point at an iPod's mount folder if it wasn't detected")
        self.manual_btn.clicked.connect(self._choose_folder)
        top = QHBoxLayout()
        top.addWidget(QLabel("Device"))
        top.addWidget(self.combo, 1)
        top.addWidget(rescan)
        top.addWidget(self.manual_btn)

        info = QGroupBox("Device")
        form = self.info_form = QFormLayout(info)
        self.model = QLabel("—")
        self.firmware = QLabel("—")
        self.space = QLabel("—")
        self.ro_warning = QLabel()
        self.ro_warning.setWordWrap(True)
        self.ro_warning.setStyleSheet("color: #c0392b;")
        self.ro_warning.hide()
        form.addRow("Model", self.model)
        form.addRow("Firmware", self.firmware)
        form.addRow("Storage", self.space)
        form.addRow(self.ro_warning)

        what = QGroupBox("What to sync")
        wv = self.what_layout = QVBoxLayout(what)
        self.all_radio = QRadioButton("Entire library")
        self.some_radio = QRadioButton("Only these playlists / albums:")
        self.all_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.all_radio)
        group.addButton(self.some_radio)
        self.pick = QListWidget()
        self.pick.setSelectionMode(QAbstractItemView.NoSelection)
        self.some_radio.toggled.connect(self.pick.setEnabled)
        self.pick.setEnabled(False)
        mirror_note = QLabel(f"The {noun} is made to match the selection: other songs Clickwheel synced are "
                             "removed. To add songs without removing any, select them on the Library tab and use "
                             f"“Sync selected to {noun}”.")
        mirror_note.setWordWrap(True)
        mirror_note.setStyleSheet("color: palette(placeholder-text);")
        wv.addWidget(self.all_radio)
        wv.addWidget(self.some_radio)
        wv.addWidget(self.pick, 1)
        wv.addWidget(mirror_note)

        self.sync_btn = QPushButton("Sync")
        self.sync_btn.setDefault(True)
        self.sync_btn.clicked.connect(self._sync_or_cancel)
        self.eject_btn = QPushButton("Eject")
        self.eject_btn.clicked.connect(self._eject)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        actions = QHBoxLayout()
        actions.addWidget(self.progress, 1)
        actions.addWidget(self.sync_btn)
        actions.addWidget(self.eject_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        cols = QHBoxLayout()
        cols.addWidget(info, 1)
        cols.addWidget(what, 2)
        layout.addLayout(cols, 2)
        layout.addLayout(actions)
        self.browser = DeviceBrowser(library, noun)
        self.browser.editing.connect(self._on_editing)
        self.bottom = QTabWidget()
        self.bottom.addTab(self.browser, f"On this {noun}")
        self.bottom.addTab(self.log, "Sync log")
        layout.addWidget(self.bottom, 3)

        self.refresh_choices()
        self._show_device()
        # Hot-plug: poll quietly for new mounts while idle.
        self._timer = QTimer(self, interval=4000, timeout=self._poll)
        self._timer.start()
        QTimer.singleShot(0, self.rescan)

    # ── Devices ──────────────────────────────────────────────────────────

    def rescan(self) -> None:
        workers.run(self._scan, on_done=self._set_devices, on_error=lambda m: self._log(f"Scan failed: {m}"))

    def _scan(self) -> list[Device]:
        return scan()

    def _no_device_text(self) -> str:
        return "No iPod found — plug one in, or choose its folder"

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
        if not self.devices:
            self.combo.addItem(self._no_device_text())
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
        enabled = dev is not None and not self._syncing
        self.sync_btn.setEnabled(dev is not None)
        self.eject_btn.setEnabled(enabled)
        if dev is None or dev.path != self._browsed_path:
            self._browsed_path = dev.path if dev else None
            if not self._syncing:
                self.browser.load(dev, self.settings.rockbox_prefers_files)
        if dev is None:
            self.model.setText("—")
            self.firmware.setText("—")
            self.space.setText("—")
            self.ro_warning.hide()
            return
        self.model.setText(dev.model)
        warning = self._describe(dev)
        self.ro_warning.setText(warning)
        self.ro_warning.setVisible(bool(warning))
        read_only = bool(warning)
        self.sync_btn.setEnabled(not read_only and not self._editing)
        self.browser.set_busy(read_only or self._syncing)

    def _describe(self, dev: Device) -> str:
        """Fill in the firmware and storage rows; returns why the device can't be changed, if it can't."""
        fw = "Rockbox" if dev.firmware == "rockbox" else "Apple"
        if dev.firmware == "rockbox" and dev.has_apple_db:
            fw += " (dual-boot; " + ("syncing files" if self.settings.rockbox_prefers_files else "syncing Apple DB") + ")"
        if dev.is_shuffle:
            fw += " · Shuffle"
        self.firmware.setText(fw)
        try:
            free, total = dev.free_space()
            self.space.setText(f"{_gb(free)} free of {_gb(total)}")
        except OSError:
            self.space.setText("unavailable")
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
            self.progress.setFormat(f"{msg} — %v/%m")
        else:
            self.progress.setFormat(msg)
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
        self._show_device()

    def _on_synced(self, summary) -> None:
        self._finish()
        self.browser.load(self.current, self.settings.rockbox_prefers_files)
        line = (f"Added {summary.added}, removed {summary.removed}, updated {summary.updated}, "
                f"playlists {summary.playlists}")
        if summary.ok:
            self.progress.setFormat("Sync complete")
            self._log("✔ " + line)
        else:
            self.progress.setFormat("Sync failed")
            self._log(f"✖ Sync failed (planned: {line.lower()})")
            for err in summary.errors:
                self._log("   " + err)

    def _on_sync_failed(self, message: str) -> None:
        self._finish()
        self.progress.setFormat("Sync failed")
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
