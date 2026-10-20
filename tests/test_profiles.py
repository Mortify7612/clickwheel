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
