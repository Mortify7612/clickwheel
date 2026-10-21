"""Sign-in dialog: import a YouTube Music session."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .. import auth
from . import workers


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add a YouTube Music account")
        self.setMinimumWidth(560)

        intro = QLabel(
            "Clickwheel uses the YouTube Music session from your web browser. "
            "Sign in at <b>music.youtube.com</b> in your browser first, then pick one option below."
        )
        intro.setWordWrap(True)

        self.tabs = QTabWidget()

        # Browser import (easiest)
        browser_tab = QWidget()
        form = QFormLayout(browser_tab)
        self.browser = QComboBox()
        self.browser.addItems([auth.browser_name(b) for b in auth.BROWSERS])
        self.profile = QLineEdit()
        self.profile.setPlaceholderText("Default profile")
        self.authuser = QSpinBox(minimum=0, maximum=9)
        self.authuser.setToolTip("If the browser is signed in to several Google accounts, 0 is the first one, "
                                 "1 the second, and so on (the order in Google's account switcher).")
        form.addRow("Browser", self.browser)
        form.addRow("Browser profile (optional)", self.profile)
        form.addRow("Google account #", self.authuser)
        if sys.platform == "darwin":
            hint = QLabel("Chrome, Arc, Brave, Edge, Vivaldi and Opera keep their cookies locked in your keychain: "
                          "when macOS asks, enter your login password and click Always Allow.")
        elif sys.platform == "win32":
            hint = QLabel("Firefox works best. Chrome/Edge may need to be closed first, and newer Chrome versions "
                          "block cookie access entirely; use Firefox or another tab then.")
        else:
            hint = QLabel("Firefox works best. Chromium-based browsers may ask you to unlock your keyring first.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        form.addRow(hint)
        self.safari_hint = QLabel(
            "On macOS, reading Safari's cookies needs "
            f"<a href='{auth.FULL_DISK_ACCESS_URL}'>Full Disk Access</a> for Clickwheel "
            "(System Settings → Privacy &amp; Security). Quit and reopen Clickwheel after turning it on."
        )
        self.safari_hint.setWordWrap(True)
        self.safari_hint.setOpenExternalLinks(True)
        form.addRow(self.safari_hint)
        self.browser.currentIndexChanged.connect(self._browser_changed)
        self._browser_changed()
        self.tabs.addTab(browser_tab, "From browser")

        # Raw request headers
        headers_tab = QWidget()
        v = QVBoxLayout(headers_tab)
        steps = QLabel(
            "1. Open music.youtube.com, press F12 and go to the <b>Network</b> tab.<br>"
            "2. Filter by <code>browse</code> and click any request (scroll your library if none show up).<br>"
            "3. Copy its <b>Request Headers</b> (Firefox: Raw toggle; Chrome: \"view source\") and paste below."
        )
        steps.setWordWrap(True)
        self.headers = QPlainTextEdit()
        self.headers.setPlaceholderText("accept: */*\ncookie: ...\nx-goog-authuser: 0\n...")
        v.addWidget(steps)
        v.addWidget(self.headers)
        self.tabs.addTab(headers_tab, "Paste headers")

        # cookies.txt
        file_tab = QWidget()
        h = QHBoxLayout(file_tab)
        self.file_authuser = QSpinBox(minimum=0, maximum=9, prefix="Account #")
        self.cookie_path = QLineEdit()
        self.cookie_path.setPlaceholderText("cookies.txt exported with a browser extension")
        browse = QPushButton("Choose…")
        browse.clicked.connect(self._pick_file)
        h.addWidget(self.cookie_path)
        h.addWidget(browse)
        h.addWidget(self.file_authuser)
        self.tabs.addTab(file_tab, "Cookies file")

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Add account")
        self.buttons.accepted.connect(self._submit)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.tabs)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)

    def _browser_changed(self) -> None:
        safari = auth.BROWSERS[self.browser.currentIndex()] == "safari"
        self.safari_hint.setVisible(safari and sys.platform == "darwin")

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Cookie file", "", "Cookie files (*.txt);;All files (*)")
        if path:
            self.cookie_path.setText(path)

    def _submit(self) -> None:
        tab = self.tabs.currentIndex()
        if tab == 0:
            fn, args = auth.sign_in_from_browser, (auth.BROWSERS[self.browser.currentIndex()],
                                                   self.profile.text().strip() or None,
                                                   str(self.authuser.value()))
        elif tab == 1:
            fn, args = auth.sign_in_from_headers, (self.headers.toPlainText(),)
        else:
            fn, args = auth.sign_in_from_cookies_file, (self.cookie_path.text().strip(),
                                                        str(self.file_authuser.value()))

        self.buttons.setEnabled(False)
        self.status.setText("Signing in…")
        workers.run(fn, *args, on_done=self._ok, on_error=self._fail)

    def _ok(self, profile: auth.Profile) -> None:
        self.profile_added = profile
        self.accept()

    def _fail(self, message: str) -> None:
        self.buttons.setEnabled(True)
        self.status.setText(f"<span style='color:#c0392b'>{message}</span>")
