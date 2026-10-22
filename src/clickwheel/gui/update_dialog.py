"""Check for, download and install app updates."""

from __future__ import annotations

import time

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox, QProgressBar, QTextBrowser, QVBoxLayout,
)

from .. import updater
from .._version import __version__
from ..config import Settings
from . import workers


class UpdateDialog(QDialog):
    def __init__(self, release: updater.Release, parent=None):
        super().__init__(parent)
        self.release = release
        self.setWindowTitle("Update available")
        self.setMinimumSize(520, 380)

        title = QLabel(f"<b>Clickwheel {release.version}</b> is available — you have {__version__}.")
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(release.notes or "_No release notes._")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)  # the status line above says how far along it is
        self.progress.hide()

        self.buttons = QDialogButtonBox()
        self.blocker = updater.self_update_blocker()
        if self.blocker:
            self.status.setText(self.blocker)
            self.install_btn = self.buttons.addButton("Open download page", QDialogButtonBox.AcceptRole)
            self.install_btn.clicked.connect(self._open_page)
        else:
            self.install_btn = self.buttons.addButton("Install and restart", QDialogButtonBox.AcceptRole)
            self.install_btn.clicked.connect(self._install)
        self.buttons.addButton("Later", QDialogButtonBox.RejectRole).clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(notes, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        layout.addWidget(self.buttons)

    def _open_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self.release.page_url))
        self.accept()

    def _install(self) -> None:
        self.buttons.setEnabled(False)
        self.progress.show()
        self.progress.setRange(0, 0)
        self.status.setText("Downloading…")
        task = workers.Task(updater.apply, self.release,
                            lambda done, total: task.progress.emit((done, total)))
        task.progress.connect(self._on_progress)
        task.done.connect(self._on_installed)
        task.failed.connect(self._on_failed)
        task.start()

    def _on_progress(self, data) -> None:
        done, total = data
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.status.setText(f"Downloading… {done / 1e6:.0f} of {total / 1e6:.0f} MB")

    def _on_installed(self, _result) -> None:
        self.status.setText("Restarting…")
        # The hand-off script waits for this process to exit before swapping files.
        QApplication.quit()

    def _on_failed(self, message: str) -> None:
        self.progress.hide()
        self.buttons.setEnabled(True)
        self.status.setText(f"<span style='color:#c0392b'>{message}</span>")


def check_for_updates(parent, settings: Settings, *, manual: bool) -> None:
    """Look for a newer release in the background; quiet unless ``manual``."""
    if not manual:
        if not settings.check_for_updates or time.time() - settings.last_update_check < 86400:
            return

    def done(release) -> None:
        settings.last_update_check = time.time()
        settings.save()
        if release is not None:
            UpdateDialog(release, parent).exec()
        elif manual:
            QMessageBox.information(parent, "No updates", f"You're on the latest version ({__version__}).")

    def failed(message: str) -> None:
        if manual:
            QMessageBox.warning(parent, "Couldn't check for updates", message)

    workers.run(updater.check, on_done=done, on_error=failed)
