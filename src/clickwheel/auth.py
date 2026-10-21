"""YouTube Music sign-in and saved profiles.

There is no public OAuth flow for YouTube Music that a desktop app can ship, so
we reuse the session the user already has in a browser.  Each saved profile is
a folder under ``<config>/profiles/<id>/`` holding:

* ``headers.json`` - browser-auth headers for ytmusicapi (library browsing)
* ``cookies.txt``  - Netscape cookie jar for yt-dlp (private/Premium downloads)
* ``profile.json`` - display name and Google account index
"""

from __future__ import annotations

import contextlib
import glob
import http.cookiejar
import json
import os
import shutil
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from http.cookies import SimpleCookie
from pathlib import Path

from ytmusicapi import YTMusic
from ytmusicapi.helpers import initialize_headers

from .config import CONFIG_DIR, COOKIES_FILE, HEADERS_FILE, write_private

BROWSERS = ["firefox", "chrome", "chromium", "brave", "edge", "vivaldi", "opera"]
if sys.platform in ("darwin", "win32"):
    BROWSERS.append("arc")
if sys.platform == "darwin":
    BROWSERS.append("safari")
BROWSER_NAMES = {"edge": "Microsoft Edge"}
YT_DOMAINS = (".youtube.com", "youtube.com", "music.youtube.com", ".google.com")
REQUIRED_COOKIE = "__Secure-3PAPISID"
ORIGIN = "https://music.youtube.com"
# Safari 13+ keeps its cookies in its sandbox; the old location is still used by
# other WebKit apps, so it can exist without holding any Safari logins.
SAFARI_COOKIES = (
    "~/Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies",
    "~/Library/Cookies/Cookies.binarycookies",
)
# Arc is Chromium under its own folder and keychain entry ("Arc Safe Storage").
ARC_DIRS = {
    "darwin": "~/Library/Application Support/Arc/User Data",
    "win32": "%LOCALAPPDATA%/Packages/TheBrowserCompany.Arc_*/LocalCache/Local/Arc/User Data",
}
FULL_DISK_ACCESS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"

PROFILES_DIR = CONFIG_DIR / "profiles"
ACTIVE_FILE = CONFIG_DIR / "active_profile"


class AuthError(Exception):
    pass


@dataclass
class Profile:
    id: str
    name: str
    # Which Google account in the browser session (0 = first signed-in account).
    authuser: str = "0"
    handle: str = ""

    @property
    def dir(self) -> Path:
        return PROFILES_DIR / self.id

    @property
    def headers_file(self) -> Path:
        return self.dir / "headers.json"

    @property
    def cookies_file(self) -> Path:
        return self.dir / "cookies.txt"

    @property
    def label(self) -> str:
        return f"{self.name} ({self.handle})" if self.handle and self.handle != self.name else self.name

    def save(self) -> None:
        write_private(self.dir / "profile.json", json.dumps(asdict(self), indent=2))


# ── Profile store ────────────────────────────────────────────────────────────

def _migrate_legacy() -> None:
    """Turn the single-account files from earlier versions into a profile."""
    if not HEADERS_FILE.exists():
        return
    profile = Profile(uuid.uuid4().hex[:8], "YouTube Music")
    profile.dir.mkdir(parents=True, exist_ok=True)
    shutil.move(HEADERS_FILE, profile.headers_file)
    if COOKIES_FILE.exists():
        shutil.move(COOKIES_FILE, profile.cookies_file)
    try:
        profile.name, profile.handle = _account_identity(profile)
    except Exception:
        pass
    profile.save()
    set_active(profile.id)


def profiles() -> list[Profile]:
    _migrate_legacy()
    found = []
    for meta in sorted(PROFILES_DIR.glob("*/profile.json")):
        try:
            data = json.loads(meta.read_text())
            found.append(Profile(**{k: v for k, v in data.items() if k in Profile.__dataclass_fields__}))
        except (OSError, ValueError, TypeError):
            continue
    return sorted(found, key=lambda p: p.name.casefold())


def get_profile(profile_id: str | None) -> Profile | None:
    return next((p for p in profiles() if p.id == profile_id), None) if profile_id else None


def active_profile() -> Profile | None:
    all_profiles = profiles()
    try:
        wanted = ACTIVE_FILE.read_text().strip()
    except OSError:
        wanted = ""
    return next((p for p in all_profiles if p.id == wanted), all_profiles[0] if all_profiles else None)


def set_active(profile_id: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_FILE.write_text(profile_id)


def remove_profile(profile_id: str) -> None:
    profile = get_profile(profile_id)
    if profile:
        shutil.rmtree(profile.dir, ignore_errors=True)
    if active_profile() is None:
        ACTIVE_FILE.unlink(missing_ok=True)


def rename_profile(profile_id: str, name: str) -> None:
    profile = get_profile(profile_id)
    if profile and name.strip():
        profile.name = name.strip()
        profile.save()


# ── Sign-in ──────────────────────────────────────────────────────────────────

def _headers_from_cookie_header(cookie_header: str, authuser: str = "0") -> dict[str, str]:
    if REQUIRED_COOKIE not in cookie_header:
        raise AuthError(
            "No YouTube Music login found. Open music.youtube.com in that browser, "
            "sign in, then try again."
        )
    headers = dict(initialize_headers())
    headers.update({
        "cookie": cookie_header,
        "x-goog-authuser": str(authuser),
        "origin": ORIGIN,
        # ytmusicapi regenerates this per request from the SAPISID cookie.
        "authorization": "SAPISIDHASH placeholder",
    })
    return headers


def _write_session(profile: Profile, headers: dict[str, str], jar: http.cookiejar.CookieJar) -> None:
    write_private(profile.headers_file, json.dumps(headers, indent=2))
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
    write_private(profile.cookies_file, "\n".join(lines) + "\n")


def _account_identity(profile: Profile) -> tuple[str, str]:
    info = YTMusic(str(profile.headers_file)).get_account_info()
    name = info.get("accountName") or info.get("channelHandle") or "YouTube Music"
    return name, info.get("channelHandle") or ""


def _store(headers: dict[str, str], jar: http.cookiejar.CookieJar, authuser: str) -> Profile:
    """Verify a session with YouTube Music and save it as a profile.

    Signing in again to an account that already has a profile refreshes that
    profile instead of adding a duplicate.
    """
    staged = Profile(uuid.uuid4().hex[:8], "", str(authuser))
    try:
        _write_session(staged, headers, jar)
        try:
            staged.name, staged.handle = _account_identity(staged)
        except Exception as exc:
            raise AuthError(f"YouTube Music rejected the session: {exc}") from exc
        existing = next((p for p in profiles()
                         if (p.handle and p.handle == staged.handle) or (not p.handle and p.name == staged.name)), None)
        target = existing or staged
        if existing:
            existing.authuser, existing.name = staged.authuser, existing.name or staged.name
            for src, dst in ((staged.headers_file, existing.headers_file), (staged.cookies_file, existing.cookies_file)):
                shutil.copy2(src, dst)
            shutil.rmtree(staged.dir, ignore_errors=True)
        target.save()
        set_active(target.id)
        return target
    except Exception:
        if staged.dir.exists() and not (staged.dir / "profile.json").exists():
            shutil.rmtree(staged.dir, ignore_errors=True)
        raise


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


def _cookie_header(jar: http.cookiejar.CookieJar) -> str:
    return "; ".join(f"{c.name}={c.value}" for c in jar if c.domain.endswith((".youtube.com", "youtube.com")))


def _safari_cookies_path() -> str:
    """Where Safari's cookies are, or why we can't read them.

    macOS hides Safari's data from other apps until the user grants Full Disk
    Access, and then even a stat() fails, which yt-dlp reports as "could not
    find safari cookies database".
    """
    for candidate in SAFARI_COOKIES:
        path = Path(candidate).expanduser()
        try:
            with open(path, "rb"):
                return str(path)
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            who = "Clickwheel" if getattr(sys, "frozen", False) else "the terminal app you run Clickwheel from"
            raise AuthError(
                f"macOS is blocking access to Safari's cookies. Open System Settings → Privacy & Security → "
                f"Full Disk Access and turn on {who} (add it with + if it isn't listed; if it is already on, "
                f"turn it off and on again, as updates can reset it). Then quit and reopen Clickwheel and "
                f"try again."
            ) from exc
    raise AuthError("Couldn't find Safari's cookies. Open music.youtube.com in Safari, sign in, then try again.")


def browser_name(browser: str) -> str:
    return BROWSER_NAMES.get(browser, browser.capitalize())


class _CookieLog:
    """Keeps yt-dlp's warnings so a failed import can say what went wrong."""

    def __init__(self):
        self.warnings: list[str] = []

    def debug(self, message):
        pass

    info = debug

    def warning(self, message, only_once=False):
        self.warnings.append(message)

    def error(self, message):
        self.warnings.append(message)


@contextlib.contextmanager
def _arc_known():
    """Teach yt-dlp where Arc keeps its cookies."""
    from yt_dlp import cookies

    known = cookies._get_chromium_based_browser_settings

    def settings(browser):
        if browser != "arc":
            return known(browser)
        pattern = os.path.expanduser(os.path.expandvars(ARC_DIRS.get(sys.platform, "")))
        found = sorted(glob.glob(pattern))
        return {"browser_dir": found[0] if found else pattern, "keyring_name": "Arc", "supports_profiles": True}

    cookies._get_chromium_based_browser_settings = settings
    try:
        yield
    finally:
        cookies._get_chromium_based_browser_settings = known


def _locked_message(name: str) -> str:
    if sys.platform == "darwin":
        return (f"macOS didn't let Clickwheel unlock {name}'s cookies. Try again and click Always Allow when "
                f"macOS asks to use \"{name} Safe Storage\" from your keychain.")
    if sys.platform == "win32":
        return (f"Couldn't decrypt {name}'s cookies; newer versions block other apps from reading them. "
                "Use Firefox, or the Paste headers or Cookies file tab instead.")
    return f"Couldn't decrypt {name}'s cookies. Unlock your keyring (KWallet or GNOME Keyring) and try again."


def sign_in_from_browser(browser: str, browser_profile: str | None = None, authuser: str = "0") -> Profile:
    """Import the YouTube session from an installed browser's cookie store."""
    from yt_dlp import cookies

    name = browser_name(browser)
    if browser == "safari" and sys.platform == "darwin" and not browser_profile:
        # yt-dlp takes a Safari "profile" to be the cookie file's path.
        browser_profile = _safari_cookies_path()
    log = _CookieLog()
    try:
        if browser == "arc":
            with _arc_known():
                jar = cookies._extract_chrome_cookies("arc", browser_profile, None, log)
        else:
            jar = cookies.extract_cookies_from_browser(browser, browser_profile, log)
    except FileNotFoundError as exc:
        where = f" (profile \"{browser_profile}\")" if browser_profile else ""
        raise AuthError(f"Couldn't find {name}'s cookies{where}. Is {name} installed on this computer?") from exc
    except Exception as exc:
        raise AuthError(f"Couldn't read {name} cookies: {exc}") from exc
    cookie_header = _cookie_header(jar)
    if REQUIRED_COOKIE not in cookie_header and any(
            "decrypt" in w or "find-generic-password" in w or "keyring" in w for w in log.warnings):
        raise AuthError(_locked_message(name))
    return _store(_headers_from_cookie_header(cookie_header, authuser), jar, authuser)


def sign_in_from_headers(raw_headers: str) -> Profile:
    """Accept request headers copied from the browser's network inspector."""
    from ytmusicapi.auth.browser import setup_browser

    try:
        headers = json.loads(setup_browser(headers_raw=raw_headers))
    except Exception as exc:
        raise AuthError(str(exc)) from exc
    cookie_header = headers.get("cookie") or headers.get("Cookie") or ""
    authuser = str(headers.get("x-goog-authuser", "0"))
    return _store(_headers_from_cookie_header(cookie_header, authuser), _jar_from_cookie_header(cookie_header),
                  authuser)


def sign_in_from_cookies_file(path: str, authuser: str = "0") -> Profile:
    """Accept a Netscape cookies.txt exported by a browser extension."""
    jar = http.cookiejar.MozillaCookieJar(path)
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, http.cookiejar.LoadError) as exc:
        raise AuthError(f"Couldn't read cookie file: {exc}") from exc
    return _store(_headers_from_cookie_header(_cookie_header(jar), authuser), jar, authuser)


# ── Use ──────────────────────────────────────────────────────────────────────

def is_signed_in() -> bool:
    return active_profile() is not None


def sign_out() -> None:
    """Forget the active profile."""
    profile = active_profile()
    if profile:
        remove_profile(profile.id)


def client(profile: Profile | None = None) -> YTMusic:
    """A client for ``profile`` (default: the active one), anonymous if none."""
    profile = profile or active_profile()
    if profile and profile.headers_file.exists():
        return YTMusic(str(profile.headers_file))
    return YTMusic()


def cookies_file(profile: Profile | None = None) -> str | None:
    profile = profile or active_profile()
    if profile and profile.cookies_file.exists():
        return str(profile.cookies_file)
    return None
