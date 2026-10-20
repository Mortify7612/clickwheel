"""YouTube Music sign-in.

There is no public OAuth flow for YouTube Music that a desktop app can ship, so
we reuse the session the user already has in a browser.  Every sign-in method
ends with the same two files in the config dir:

* ``ytm_headers.json`` - browser-auth headers for ytmusicapi (library browsing)
* ``cookies.txt``      - Netscape cookie jar for yt-dlp (private/Premium downloads)
"""

from __future__ import annotations

import http.cookiejar
import json
import time
from http.cookies import SimpleCookie

from ytmusicapi import YTMusic
from ytmusicapi.helpers import initialize_headers

from .config import COOKIES_FILE, HEADERS_FILE, write_private

BROWSERS = ["firefox", "chrome", "chromium", "brave", "edge", "vivaldi", "opera", "safari"]
YT_DOMAINS = (".youtube.com", "youtube.com", "music.youtube.com", ".google.com")
REQUIRED_COOKIE = "__Secure-3PAPISID"
ORIGIN = "https://music.youtube.com"


class AuthError(Exception):
    pass


def _headers_from_cookie_header(cookie_header: str, authuser: str = "0") -> dict[str, str]:
    if REQUIRED_COOKIE not in cookie_header:
        raise AuthError(
            "No YouTube Music login found. Open music.youtube.com in that browser, "
            "sign in, then try again."
        )
    headers = dict(initialize_headers())
    headers.update({
        "cookie": cookie_header,
        "x-goog-authuser": authuser,
        "origin": ORIGIN,
        # ytmusicapi regenerates this per request from the SAPISID cookie.
        "authorization": "SAPISIDHASH placeholder",
    })
    return headers


def _save(headers: dict[str, str], jar: http.cookiejar.CookieJar) -> None:
    write_private(HEADERS_FILE, json.dumps(headers, indent=2))
    lines = ["# Netscape HTTP Cookie File"]
    for c in jar:
        if not c.domain.endswith(YT_DOMAINS):
            continue
        lines.append("\t".join([
            c.domain,
            "TRUE" if c.domain.startswith(".") else "FALSE",
            c.path or "/",
            "TRUE" if c.secure else "FALSE",
            str(int(c.expires or time.time() + 365 * 86400)),
            c.name,
            c.value or "",
        ]))
    write_private(COOKIES_FILE, "\n".join(lines) + "\n")


def _jar_from_cookie_header(cookie_header: str) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    parsed = SimpleCookie()
    parsed.load(cookie_header)
    for name, morsel in parsed.items():
        jar.set_cookie(http.cookiejar.Cookie(
            0, name, morsel.value, None, False, ".youtube.com", True, True, "/", True,
            True, None, False, None, None, {},
        ))
    return jar


def sign_in_from_browser(browser: str, profile: str | None = None) -> None:
    """Import the YouTube session from an installed browser's cookie store."""
    from yt_dlp.cookies import extract_cookies_from_browser

    try:
        jar = extract_cookies_from_browser(browser, profile)
    except Exception as exc:
        raise AuthError(f"Couldn't read {browser} cookies: {exc}") from exc
    yt = [c for c in jar if c.domain.endswith((".youtube.com", "youtube.com"))]
    cookie_header = "; ".join(f"{c.name}={c.value}" for c in yt)
    _save(_headers_from_cookie_header(cookie_header), jar)


def sign_in_from_headers(raw_headers: str) -> None:
    """Accept request headers copied from the browser's network inspector."""
    from ytmusicapi.auth.browser import setup_browser

    try:
        headers = json.loads(setup_browser(headers_raw=raw_headers))
    except Exception as exc:
        raise AuthError(str(exc)) from exc
    cookie_header = headers.get("cookie") or headers.get("Cookie") or ""
    full = _headers_from_cookie_header(cookie_header, headers.get("x-goog-authuser", "0"))
    _save(full, _jar_from_cookie_header(cookie_header))


def sign_in_from_cookies_file(path: str) -> None:
    """Accept a Netscape cookies.txt exported by a browser extension."""
    jar = http.cookiejar.MozillaCookieJar(path)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, http.cookiejar.LoadError) as exc:
        raise AuthError(f"Couldn't read cookie file: {exc}") from exc
    yt = [c for c in jar if c.domain.endswith((".youtube.com", "youtube.com"))]
    cookie_header = "; ".join(f"{c.name}={c.value}" for c in yt)
    _save(_headers_from_cookie_header(cookie_header), jar)


def is_signed_in() -> bool:
    return HEADERS_FILE.exists()


def sign_out() -> None:
    HEADERS_FILE.unlink(missing_ok=True)
    COOKIES_FILE.unlink(missing_ok=True)


def client() -> YTMusic:
    """An authenticated client when signed in, anonymous otherwise."""
    if is_signed_in():
        return YTMusic(str(HEADERS_FILE))
    return YTMusic()


def cookies_file() -> str | None:
    return str(COOKIES_FILE) if COOKIES_FILE.exists() else None
