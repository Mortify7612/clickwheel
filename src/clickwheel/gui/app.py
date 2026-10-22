"""Main window."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QVBoxLayout, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QAbstractItemView, QGroupBox, QHeaderView, QMainWindow, QMessageBox, QPushButton, QSpinBox, QTabWidget, QWidget,
)

from .. import updater
from .._version import __version__
from ..config import APP_NAME, DB_FILE, PLAYBACK_FILE, Settings
from ..library import Library
from .device_page import DevicePage
from .eq_panel import EqPanel
from .fonts import load_fonts
from .lcd import BARS, LcdDisplay
from .player import Player
from .player_bar import PlayerBar
from .hud import HudBrackets
from .ribbon import TitleBar
from .sparkle import Backdrop
from .table_style import restyle_table
from .library_page import LibraryPage
from .theme import THEMES, apply_theme, current_theme, is_retro
from .update_dialog import check_for_updates
from .workers import DownloadManager
from .ytm_page import YtmPage


ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "clickwheel.png"


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
        self.theme = QComboBox()
        for key, label in THEMES.items():
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        form.addRow("Theme", self.theme)
        self.status_bar = QCheckBox("Show the status bar at the bottom of the window")
        self.status_bar.setChecked(settings.show_status_bar)
        form.addRow(self.status_bar)
        self.auto_update = QCheckBox("Check for Clickwheel updates once a day")
        self.auto_update.setChecked(settings.check_for_updates)
        form.addRow(self.auto_update)
        self.channel = QComboBox()
        self.channel.addItem("Stable", "stable")
        self.channel.addItem("Beta: early builds with new features (may have rough edges)", "beta")
        self.channel.setCurrentIndex(max(0, self.channel.findData(
            settings.update_channel or updater.default_channel())))
        self.channel.setToolTip("Moving back to Stable from a beta takes effect at the next stable release.")
        form.addRow("Updates", self.channel)
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
        self.settings.update_channel = self.channel.currentData()
        self.settings.theme = self.theme.currentData()
        self.settings.show_status_bar = self.status_bar.isChecked()
        apply_theme(QApplication.instance(), self.settings.theme)
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
        # Messages always go through the status bar; the LCD ticker shows them too, so the
        # bar itself is optional.
        status.setVisible(self.settings.show_status_bar)

        self.ytm_page = YtmPage(self.manager, status)
        self.library_page = LibraryPage(self.library, self.manager)
        self.device_page = DevicePage(self.library, self.settings)
        self.manager.library_changed.connect(self.device_page.refresh_choices)
        # Edits on the iPod tab can also change the library (mirrored order, deletions).
        self.device_page.browser.library_edited.connect(self.library_page.refresh)
        self.device_page.browser.library_edited.connect(self.device_page.refresh_choices)
        self.device_page.browser.contents_read.connect(self.library_page.set_device_contents)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self.ytm_page, "YouTube Music")
        tabs.addTab(self.library_page, "Library")
        tabs.addTab(self.device_page, "iPod")
        tabs.currentChanged.connect(lambda i: i == 2 and self.device_page.refresh_choices())
        # Retro LCD strip above the tabs: status ticker plus a level meter while busy.
        self.lcd = LcdDisplay()
        self.player = Player(BARS, self)
        self.player_bar = PlayerBar(self.player)
        self.eq_panel = EqPanel()
        central = Backdrop()  # bubbles and sparkles behind the glass panels (Y2K)
        column = QVBoxLayout(central)
        column.setContentsMargins(6, 4, 6, 6)
        column.setSpacing(6)
        self.title_bar = TitleBar("CLICKWHEEL")  # Winamp-style ribbed strip, retro skin only
        column.addWidget(self.title_bar)
        column.addWidget(self.lcd)
        column.addWidget(self.player_bar)
        column.addWidget(self.eq_panel)
        column.addWidget(tabs, 1)
        self.setCentralWidget(central)
        self._tabs = tabs
        self._wire_lcd(status)
        # HUD corner brackets on the display, the deck and every panel (Halo skin only).
        panels = [self.lcd, self.player_bar, self.eq_panel] + [
            w for w in self.findChildren(QAbstractItemView) + self.findChildren(QGroupBox)
            if not isinstance(w, QHeaderView) and w.window() is self]  # not combo-box popups
        self._hud = [HudBrackets(w) for w in panels]
        self.restyle()
        self._keep_playback()
        self._wire_equalizer()

        def sync_songs(paths):
            tabs.setCurrentWidget(self.device_page)  # show progress where syncs live
            self.device_page.sync_songs(paths)

        self.library_page.sync_requested.connect(sync_songs)
        self.library_page.browse_requested.connect(lambda: tabs.setCurrentWidget(self.ytm_page))

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

    def restyle(self) -> None:
        """Theme-dependent touches a stylesheet can't express (uppercase tab labels, table fonts)."""
        for tabs in (self._tabs, self.device_page.bottom):
            # The stylesheet sets the tab font, so capitalise the labels themselves.
            for i in range(tabs.count()):
                original = tabs.tabBar().tabData(i)
                if original is None:
                    original = tabs.tabText(i)
                    tabs.tabBar().setTabData(i, original)
                tabs.setTabText(i, original.upper() if is_retro() else original)
        for table in (self.library_page.table, self.device_page.browser.table):
            restyle_table(table)
        self.ytm_page.restyle()
        self.player_bar.refresh_icons()
        self.library_page.restyle()
        self.device_page.restyle()
        self.title_bar.setVisible(is_retro())
        for brackets in self._hud:
            brackets.setVisible(current_theme() == "halo")

    def _wire_equalizer(self) -> None:
        s, panel, player = self.settings, self.eq_panel, self.player
        try:
            player.equalizer.set(s.eq_gains, s.eq_preamp)
        except (TypeError, ValueError):  # a hand-edited or older settings file: start flat
            s.eq_gains, s.eq_preamp, s.eq_preset = [0.0] * 10, 0.0, "Flat"
        panel.set_values(s.eq_enabled, s.eq_gains, s.eq_preamp, s.eq_preset)
        player.set_equalizer(s.eq_enabled, s.eq_gains, s.eq_preamp)
        panel.setVisible(s.show_equalizer)
        self.player_bar.eq_btn.setChecked(s.show_equalizer)
        save = QTimer(self, singleShot=True, interval=600, timeout=s.save)  # once a drag settles

        def edited():
            player.set_equalizer(panel.enabled, panel.gains, panel.preamp)
            s.eq_enabled, s.eq_gains, s.eq_preamp, s.eq_preset = panel.enabled, panel.gains, panel.preamp, panel.preset
            save.start()

        def shown(visible: bool):
            panel.setVisible(visible)
            s.show_equalizer = visible
            save.start()

        def failed(message: str):
            panel.set_values(False, panel.gains, panel.preamp, panel.preset)
            s.eq_enabled = False
            save.start()
            self.statusBar().showMessage(message, 10000)

        panel.changed.connect(edited)
        self.player_bar.equalizer_toggled.connect(shown)
        player.equalizer_failed.connect(failed)

    def _wire_lcd(self, status) -> None:
        lcd = self.lcd
        status.messageChanged.connect(lambda text: lcd.set_message(text or "Ready"))
        self.manager.resolving.connect(lambda label: (lcd.set_busy("downloads", True),
                                                      lcd.set_message(f"Looking up {label}")))
        self.manager.idle.connect(lambda: lcd.set_busy("downloads", False))

        def on_track(_job, ev):
            from ..pipeline import Status

            if ev.status == Status.DOWNLOADING:
                pct = f" {ev.progress:.0%}" if ev.progress else ""
                lcd.set_message(f"{ev.meta.artist} - {ev.meta.title}{pct}")

        self.manager.track_event.connect(on_track)
        self.device_page.busy.connect(lambda busy: lcd.set_busy("sync", busy))
        self.device_page.activity.connect(lcd.set_message)

        # Playback drives the ticker, clock and (real) spectrum meter.
        player = self.player
        player.track_changed.connect(
            lambda item: lcd.set_now_playing(item.artist if item else "", item.title if item else "", "playing"))
        player.state_changed.connect(
            lambda state: lcd.set_now_playing(player.current.artist if player.current else "",
                                              player.current.title if player.current else "", state))
        player.position_changed.connect(lcd.set_clock)
        player.spectrum.connect(lcd.set_spectrum)
        player.error.connect(lambda msg: self.statusBar().showMessage(msg, 8000))
        self.library_page.play_requested.connect(player.play_queue)

        def shuffle(items):
            player.set_shuffle(True)
            self.player_bar.shuffle_btn.setChecked(True)
            player.play_queue(items, random.randrange(len(items)))

        self.library_page.shuffle_requested.connect(shuffle)
        for page in (self.library_page, self.device_page.browser):
            player.track_changed.connect(lambda item, page=page: page.set_now_playing(item.path if item else None))
        self.device_page.browser.play_requested.connect(player.play_queue)

    def closeEvent(self, event) -> None:
        # Sync and edit threads die with the process: quitting mid-write can leave a
        # database without its iTunesSD (a Shuffle then plays almost nothing).
        page = self.device_page
        if page._syncing or page._editing:
            answer = QMessageBox.warning(
                self, "Clickwheel is writing to your iPod",
                "Quitting now can leave the iPod's music list half-written. Wait for it to finish?",
                QMessageBox.Ok | QMessageBox.Discard, QMessageBox.Ok)
            if answer != QMessageBox.Discard:
                event.ignore()
                return
        self._save_playback()
        event.accept()

    # ── Picking up where you left off ────────────────────────────────────

    def _keep_playback(self) -> None:
        """Restore the last song (paused where it was) and keep its place saved from now on."""
        try:
            state = json.loads(PLAYBACK_FILE.read_text())
        except (OSError, ValueError):
            state = None
        if isinstance(state, dict) and self.player.restore(state):
            self.player_bar.sync_from_player()
        player = self.player
        player.track_changed.connect(self._save_playback)
        player.state_changed.connect(self._save_playback)
        # While playing, note the position every few seconds, so even a crash loses little.
        self._playback_timer = QTimer(self, interval=5000,
                                      timeout=lambda: player.is_playing and self._save_playback())
        self._playback_timer.start()

    def _save_playback(self, *_args) -> None:
        state = self.player.snapshot()
        try:
            if state is None:
                PLAYBACK_FILE.unlink(missing_ok=True)
                return
            PLAYBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = PLAYBACK_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state))
            tmp.replace(PLAYBACK_FILE)  # never leave a half-written file
        except OSError:
            pass  # remembering the song is a nicety; never get in the way of playing it

    def _settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if not dlg.exec():
            return
        changed_folder = dlg.apply()
        self.statusBar().setVisible(self.settings.show_status_bar)
        self.restyle()
        if changed_folder:
            QMessageBox.information(self, "Restart needed",
                                    "The new library folder will be used the next time Clickwheel starts.")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("clickwheel")
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    load_fonts()
    apply_theme(app, Settings.load().theme)
    window = MainWindow()
    window.show()
    return app.exec()
