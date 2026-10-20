"""Sign-in dialog: import a YouTube Music session."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .. import auth
from . import workers


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in to YouTube Music")
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
        self.browser.addItems([b.capitalize() for b in auth.BROWSERS])
        self.profile = QLineEdit()
        self.profile.setPlaceholderText("Default profile")
        form.addRow("Browser", self.browser)
        form.addRow("Profile (optional)", self.profile)
        hint = QLabel("Firefox works on every platform. On Windows, Chrome/Edge may need to be closed first, "
                      "and newer Chrome versions block cookie access entirely; use Firefox or another tab then.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        form.addRow(hint)
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
        self.cookie_path = QLineEdit()
        self.cookie_path.setPlaceholderText("cookies.txt exported with a browser extension")
        browse = QPushButton("Choose…")
        browse.clicked.connect(self._pick_file)
        h.addWidget(self.cookie_path)
        h.addWidget(browse)
        self.tabs.addTab(file_tab, "Cookies file")

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Sign in")
        self.buttons.accepted.connect(self._submit)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.tabs)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Cookie file", "", "Cookie files (*.txt);;All files (*)")
        if path:
            self.cookie_path.setText(path)

    def _submit(self) -> None:
        tab = self.tabs.currentIndex()
        if tab == 0:
            fn, args = auth.sign_in_from_browser, (auth.BROWSERS[self.browser.currentIndex()],
                                                   self.profile.text().strip() or None)
        elif tab == 1:
            fn, args = auth.sign_in_from_headers, (self.headers.toPlainText(),)
        else:
            fn, args = auth.sign_in_from_cookies_file, (self.cookie_path.text().strip(),)

        def sign_in_and_verify():
            fn(*args)
            from ..ytm import Resolver

            try:
                return Resolver(auth.client()).account_name()
            except Exception as exc:
                auth.sign_out()
                raise auth.AuthError(f"YouTube Music rejected the session: {exc}") from exc

        self.buttons.setEnabled(False)
        self.status.setText("Signing in…")
        workers.run(sign_in_and_verify, on_done=self._ok, on_error=self._fail)

    def _ok(self, name: str) -> None:
        self.account_name = name
        self.accept()

    def _fail(self, message: str) -> None:
        self.buttons.setEnabled(True)
        self.status.setText(f"<span style='color:#c0392b'>{message}</span>")
