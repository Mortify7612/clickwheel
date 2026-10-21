"""Zune tab (Linux): the Zune HD's own page, on top of the iPod tab's sync machinery."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QLabel, QPushButton

from ..config import Settings
from ..devices import Device, scan_zune
from ..library import Library
from . import workers
from .device_page import DevicePage, _gb


LOW = 15  # percent


def battery_text(level: int | None) -> str:
    if level is None:
        return "—"
    return f"{level}% — low, charge it soon" if level <= LOW else f"{level}%"


class ZunePage(DevicePage):
    present = Signal(bool)  # a Zune is plugged in (or was unplugged)

    def __init__(self, library: Library, settings: Settings):
        self.release_btn = None  # the base class shows the (empty) device before these exist
        self.battery = None
        self._present = False
        super().__init__(library, settings, noun="Zune")
        self.manual_btn.hide()  # an MTP player has no folder to point at
        self.eject_btn.hide()  # ...and nothing to flush: it's safe to unplug when idle
        self.battery = QLabel("—")
        self.info_form.insertRow(3, "Battery", self.battery)  # after Model, Firmware, Storage
        self.release_btn = QPushButton("Release it")
        self.release_btn.setToolTip("Ask KDE's file service to let go of the Zune; it restarts by itself when needed")
        self.release_btn.clicked.connect(self._release)
        self.release_btn.hide()
        self.info_form.addRow(self.release_btn)

    def _scan(self) -> list[Device]:
        dev = scan_zune()
        return [dev] if dev else []

    def _poll(self) -> None:
        # Unlike the iPod tab, keep watching while hidden: the Library tab's
        # "Sync selected to Zune" button follows whether one is plugged in.
        if not self._syncing and not self._editing:
            self.rescan()

    def _no_device_text(self) -> str:
        return "No Zune HD found — plug one in"

    def _set_devices(self, devices: list[Device], keep=None) -> None:
        super()._set_devices(devices, keep)
        if bool(self.devices) != self._present:
            self._present = bool(self.devices)
            self.present.emit(self._present)
        if self.current is not None and not self._syncing:
            self._show_device()  # battery and free space change while the device list doesn't

    def _show_device(self) -> None:
        super()._show_device()
        if self.release_btn is not None and self.current is None:
            self.release_btn.hide()
            self.battery.setText("—")

    def _describe(self, dev: Device) -> str:
        info = dev.zune
        self.firmware.setText("Zune HD (MTP)")
        self.space.setText(f"{_gb(info.free)} free of {_gb(info.total)}" if info.total else "—")
        if self.release_btn is not None:
            self.release_btn.setVisible(info.busy)
            self.battery.setText(battery_text(info.battery))
            self.battery.setStyleSheet("color: #c0392b;" if info.battery is not None and info.battery <= LOW else "")
        if info.busy:
            return ("Another program has the Zune open — on KDE that's its file service, which grabs MTP players "
                    "when they're plugged in.")
        if not info.has_keys:
            from ..devices.mtpz import KEY_FILE

            return f"Clickwheel can show what's on the Zune, but changing it needs the MTPZ key file at {KEY_FILE}."
        return ""

    def _release(self) -> None:
        from ..devices.zune import release_from_kde

        def done(ok: bool) -> None:
            self._log("Asked KDE's file service to release the Zune" if ok
                      else "Couldn't reach KDE's file service; close any file manager window showing the Zune")
            QTimer.singleShot(1500, self.rescan)

        self.release_btn.setEnabled(False)
        QTimer.singleShot(3000, lambda: self.release_btn.setEnabled(True))
        workers.run(release_from_kde, on_done=done, on_error=lambda m: self._log(f"Release failed: {m}"))
