"""Main window."""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QTabWidget, QWidget,
)

from .._version import __version__
from ..config import APP_NAME, DB_FILE, Settings
from ..library import Library
from .device_page import DevicePage
from .library_page import LibraryPage
from .update_dialog import check_for_updates
from .workers import DownloadManager
from .ytm_page import YtmPage


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.settings = settings
        form = QFormLayout(self)

        self.folder = QLineEdit(settings.library_dir)
        browse = QPushButton("Choose…")
        browse.clicked.connect(self._browse)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.folder, 1)
        h.addWidget(browse)
        form.addRow("Music library folder", row)

        self.album_versions = QCheckBox("Replace music videos with the album version when available")
        self.album_versions.setChecked(settings.prefer_album_versions)
        form.addRow(self.album_versions)
        self.rockbox_files = QCheckBox("Sync Rockbox iPods as plain files (instead of the Apple database)")
        self.rockbox_files.setChecked(settings.rockbox_prefers_files)
        form.addRow(self.rockbox_files)
        self.auto_update = QCheckBox("Check for Clickwheel updates once a day")
        self.auto_update.setChecked(settings.check_for_updates)
        form.addRow(self.auto_update)
        self.parallel = QSpinBox(minimum=1, maximum=6, value=settings.parallel_downloads)
        form.addRow("Simultaneous downloads", self.parallel)
        self.cover = QSpinBox(minimum=300, maximum=2000, singleStep=100, value=settings.cover_size)
        form.addRow("Album art size (px)", self.cover)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Music library folder", self.folder.text())
        if path:
            self.folder.setText(path)

    def apply(self) -> bool:
        """Save; returns True if the library folder changed (needs restart)."""
        changed = self.folder.text() != self.settings.library_dir
        self.settings.library_dir = self.folder.text()
        self.settings.prefer_album_versions = self.album_versions.isChecked()
        self.settings.rockbox_prefers_files = self.rockbox_files.isChecked()
        self.settings.check_for_updates = self.auto_update.isChecked()
        self.settings.parallel_downloads = self.parallel.value()
        self.settings.cover_size = self.cover.value()
        self.settings.save()
        return changed


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.library = Library(self.settings.library_path, DB_FILE)
        self.manager = DownloadManager(self.library, self.settings)

        self.setWindowTitle(APP_NAME)
        self.resize(1100, 720)
        status = self.statusBar()

        self.ytm_page = YtmPage(self.manager, status)
        self.library_page = LibraryPage(self.library, self.manager)
        self.device_page = DevicePage(self.library, self.settings)
        self.manager.library_changed.connect(self.device_page.refresh_choices)
        # Edits on the iPod tab can also change the library (mirrored order, deletions).
        self.device_page.browser.library_edited.connect(self.library_page.refresh)
        self.device_page.browser.library_edited.connect(self.device_page.refresh_choices)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self.ytm_page, "YouTube Music")
        tabs.addTab(self.library_page, "Library")
        tabs.addTab(self.device_page, "iPod")
        tabs.currentChanged.connect(lambda i: i == 2 and self.device_page.refresh_choices())
        self.setCentralWidget(tabs)

        menu = self.menuBar().addMenu("&File")
        prefs = QAction("Settings…", self)
        prefs.triggered.connect(self._settings)
        menu.addAction(prefs)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        updates = QAction("Check for updates…", self)
        updates.triggered.connect(lambda: check_for_updates(self, self.settings, manual=True))
        help_menu.addAction(updates)
        about = QAction("About Clickwheel", self)
        about.triggered.connect(lambda: QMessageBox.about(
            self, "About Clickwheel", f"<b>Clickwheel {__version__}</b><br>YouTube Music to iPod."))
        help_menu.addAction(about)

        status.showMessage(f"Library: {self.library.root}")
        QTimer.singleShot(3000, lambda: check_for_updates(self, self.settings, manual=False))

    def _settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() and dlg.apply():
            QMessageBox.information(self, "Restart needed",
                                    "The new library folder will be used the next time Clickwheel starts.")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("clickwheel")
    window = MainWindow()
    window.show()
    return app.exec()
