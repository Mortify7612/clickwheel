import json
import sqlite3
import sys

import pytest

from clickwheel import auth
from clickwheel.library import Library

COOKIE = "SID=abc; __Secure-3PAPISID=xyz; HSID=def"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(auth, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(auth, "ACTIVE_FILE", tmp_path / "active_profile")
    monkeypatch.setattr(auth, "HEADERS_FILE", tmp_path / "ytm_headers.json")
    monkeypatch.setattr(auth, "COOKIES_FILE", tmp_path / "cookies.txt")
    accounts = {"0": ("Alex", "@alex"), "1": ("Sam", "@sam")}
    monkeypatch.setattr(auth, "_account_identity",
                        lambda p: accounts[json.loads(p.headers_file.read_text())["x-goog-authuser"]])
    return tmp_path


def add(authuser: str) -> auth.Profile:
    headers = auth._headers_from_cookie_header(COOKIE, authuser)
    return auth._store(headers, auth._jar_from_cookie_header(COOKIE), authuser)


def test_multiple_accounts_and_switching(store):
    alex, sam = add("0"), add("1")
    assert [p.name for p in auth.profiles()] == ["Alex", "Sam"]
    assert auth.active_profile().id == sam.id  # newest sign-in becomes active
    auth.set_active(alex.id)
    assert auth.active_profile().id == alex.id
    assert auth.cookies_file(sam) != auth.cookies_file(alex)
    assert "__Secure-3PAPISID\txyz" in (sam.dir / "cookies.txt").read_text()
    if sys.platform != "win32":  # Windows relies on the user-profile ACLs instead
        assert (sam.dir / "cookies.txt").stat().st_mode & 0o077 == 0  # private to the user


def test_signing_in_again_refreshes_instead_of_duplicating(store):
    first = add("0")
    auth.rename_profile(first.id, "Me")
    again = add("0")
    assert again.id == first.id
    assert [p.name for p in auth.profiles()] == ["Me"]  # custom name kept
    assert len(list((store / "profiles").iterdir())) == 1


def test_remove_falls_back_to_remaining(store):
    alex, sam = add("0"), add("1")
    auth.remove_profile(sam.id)
    assert auth.active_profile().id == alex.id
    auth.remove_profile(alex.id)
    assert auth.active_profile() is None and not auth.is_signed_in()


def test_rejected_session_leaves_nothing_behind(store, monkeypatch):
    def reject(_p):
        raise RuntimeError("401")

    monkeypatch.setattr(auth, "_account_identity", reject)
    with pytest.raises(auth.AuthError):
        add("0")
    assert auth.profiles() == []
    assert not list((store / "profiles").iterdir())


def test_missing_login_cookie_is_reported(store):
    with pytest.raises(auth.AuthError, match="No YouTube Music login"):
        auth._headers_from_cookie_header("SID=abc", "0")


def test_legacy_single_account_is_migrated(store):
    (store / "ytm_headers.json").write_text(json.dumps(auth._headers_from_cookie_header(COOKIE, "0")))
    (store / "cookies.txt").write_text("# Netscape HTTP Cookie File\n")
    [profile] = auth.profiles()
    assert profile.name == "Alex"
    assert auth.active_profile().id == profile.id
    assert not (store / "ytm_headers.json").exists()


def test_old_library_gains_profile_column(tmp_path):
    db = tmp_path / "db.sqlite3"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE playlists (id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, "
                "url TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL)")
    con.execute("INSERT INTO playlists VALUES ('PL1', 'Old', 'playlist', '', 0)")
    con.commit()
    con.close()
    lib = Library(tmp_path / "lib", db)
    assert [(p.title, p.profile) for p in lib.playlists()] == [("Old", "")]
    lib.save_playlist("PL2", "New", "playlist", "", [], profile="abc123")
    assert {p.title: p.profile for p in lib.playlists()} == {"Old": "", "New": "abc123"}


@pytest.mark.skipif(sys.platform == "win32", reason="relies on POSIX file permissions")
def test_safari_cookies_blocked_by_macos_privacy(store, tmp_path, monkeypatch):
    sandboxed, legacy = tmp_path / "container" / "Cookies.binarycookies", tmp_path / "Cookies.binarycookies"
    monkeypatch.setattr(auth, "SAFARI_COOKIES", (str(sandboxed), str(legacy)))
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(auth.AuthError, match="Couldn't find Safari's cookies"):
        auth.sign_in_from_browser("safari")

    # Without Full Disk Access, macOS refuses even to stat Safari's sandbox; the
    # stale shared file next to it must not be read instead.
    legacy.write_bytes(b"cook")
    sandboxed.parent.mkdir()
    sandboxed.write_bytes(b"cook")
    sandboxed.parent.chmod(0)
    try:
        if not _readable(sandboxed):  # root reads it anyway
            with pytest.raises(auth.AuthError, match="Full Disk Access"):
                auth.sign_in_from_browser("safari")
    finally:
        sandboxed.parent.chmod(0o755)

    import yt_dlp.cookies
    asked = []
    monkeypatch.setattr(yt_dlp.cookies, "extract_cookies_from_browser",
                        lambda browser, profile, logger: asked.append(profile) or auth._jar_from_cookie_header(COOKIE))
    assert auth.sign_in_from_browser("safari").name == "Alex"
    assert asked == [str(sandboxed)]


def _readable(path) -> bool:
    try:
        path.read_bytes()
        return True
    except PermissionError:
        return False


# ── Every browser, as macOS lays them out ────────────────────────────────────

MAC_CHROMIUM = {  # browser: (data folder under ~/Library/Application Support, keychain name)
    "chrome": ("Google/Chrome/Default", "Chrome"),
    "chromium": ("Chromium/Default", "Chromium"),
    "brave": ("BraveSoftware/Brave-Browser/Default", "Brave"),
    "edge": ("Microsoft Edge/Default", "Microsoft Edge"),
    "vivaldi": ("Vivaldi/Default", "Vivaldi"),
    "opera": ("com.operasoftware.Opera", "Opera"),
    "arc": ("Arc/User Data/Default", "Arc"),
}
YT_COOKIES = [(".youtube.com", "SID", "abc"), (".youtube.com", "__Secure-3PAPISID", "xyz"),
              (".example.com", "other", "1")]


def _chromium_store(folder, password: bytes) -> None:
    """A Chrome cookie database (schema 24) encrypted the way Chrome on macOS does it."""
    import hashlib

    from yt_dlp.aes import aes_cbc_encrypt_bytes

    key = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16)
    folder.mkdir(parents=True)
    db = sqlite3.connect(folder / "Cookies")
    db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    db.execute("INSERT INTO meta VALUES ('version', '24')")
    db.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, path TEXT, "
               "expires_utc INTEGER, is_secure INTEGER)")
    for host, name, value in YT_COOKIES:
        plain = hashlib.sha256(host.encode()).digest() + value.encode()
        db.execute("INSERT INTO cookies VALUES (?, ?, '', ?, '/', 0, 1)",
                   (host, name, b"v10" + aes_cbc_encrypt_bytes(plain, key, b" " * 16)))
    db.commit()
    db.close()


def _firefox_store(folder) -> None:
    folder.mkdir(parents=True)
    db = sqlite3.connect(folder / "cookies.sqlite")
    db.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT, path TEXT, expiry INTEGER, "
               "isSecure INTEGER, originAttributes TEXT)")
    db.executemany("INSERT INTO moz_cookies VALUES (?, ?, ?, '/', 2000000000, 1, '')", YT_COOKIES)
    db.commit()
    db.close()


def _safari_store(path) -> None:
    """Safari's Cookies.binarycookies: one page of little-endian records."""
    import struct

    records = []
    for host, name, value in YT_COOKIES:
        strings = b"".join(s.encode() + b"\0" for s in (host, name, "/", value))
        offsets, at = [], 56
        for s in (host, name, "/"):
            offsets.append(at)
            at += len(s.encode()) + 1
        offsets.append(at)
        size = 56 + len(strings)
        records.append(struct.pack("<IIII4I8sdd", size, 0, 1, 0, *offsets, b"\0" * 8, 1e9, 7e8) + strings)
    header = struct.pack("<4sI", b"\0\0\1\0", len(records))
    at = len(header) + 4 * len(records) + 4
    offsets = []
    for r in records:
        offsets.append(at)
        at += len(r)
    page = header + struct.pack(f"<{len(records)}I", *offsets) + b"\0" * 4 + b"".join(records)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"cook" + struct.pack(">II", 1, len(page)) + page + b"\0" * 8)


@pytest.fixture
def mac_home(store, tmp_path, monkeypatch):
    import yt_dlp.cookies

    home = tmp_path / "home"
    support = home / "Library/Application Support"
    for browser, (folder, keychain) in MAC_CHROMIUM.items():
        _chromium_store(support / folder, f"pw-{keychain}".encode())
    _firefox_store(support / "Firefox/Profiles/abcd.default-release")
    _safari_store(home / "Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sys, "platform", "darwin")
    keychain = {"asked": [], "allow": True}

    def keychain_password(name, logger):
        keychain["asked"].append(name)
        if keychain["allow"]:
            return f"pw-{name}".encode()
        logger.warning("find-generic-password failed")
        return None

    monkeypatch.setattr(yt_dlp.cookies, "_get_mac_keyring_password", keychain_password)
    return keychain


@pytest.mark.parametrize("browser", [*MAC_CHROMIUM, "firefox", "safari"])
def test_every_browser_signs_in_on_macos(mac_home, browser):
    profile = auth.sign_in_from_browser(browser)
    assert profile.name == "Alex"
    cookies = (profile.dir / "cookies.txt").read_text()
    assert "__Secure-3PAPISID\txyz" in cookies and "other" not in cookies
    assert mac_home["asked"] == ([MAC_CHROMIUM[browser][1]] if browser in MAC_CHROMIUM else [])


def test_keychain_refusal_and_missing_browser_on_macos(mac_home, tmp_path):
    mac_home["allow"] = False
    with pytest.raises(auth.AuthError, match="Always Allow"):
        auth.sign_in_from_browser("arc")
    import shutil
    shutil.rmtree(tmp_path / "home/Library/Application Support/Arc")
    with pytest.raises(auth.AuthError, match="Couldn't find Arc's cookies"):
        auth.sign_in_from_browser("arc")
