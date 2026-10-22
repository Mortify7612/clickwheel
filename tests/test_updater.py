import hashlib
import io
import subprocess
import sys
import tarfile
import zipfile

import pytest

from clickwheel import updater


def test_versions_and_platforms():
    assert updater.parse_version("v1.10.2") > updater.parse_version("1.9.9")
    assert updater.parse_version("0.1") == updater.parse_version("0.1.0")
    assert updater.platform_key("darwin", "arm64") == "macos-arm64"
    assert updater.platform_key("darwin", "x86_64") == "macos-intel"
    assert updater.platform_key("win32", "AMD64") == "windows-x64"
    assert updater.platform_key("linux", "x86_64") == "linux-x64"


def test_checksums_parse():
    text = f"{'a' * 64}  Clickwheel-linux-x64.tar.gz\n{'B' * 64} *Clickwheel-windows-x64.zip\njunk\n"
    assert updater.parse_checksums(text) == {"Clickwheel-linux-x64.tar.gz": "a" * 64,
                                              "Clickwheel-windows-x64.zip": "b" * 64}


class FakeResponse:
    def __init__(self, status=200, json_data=None, text="", content=b""):
        self.status_code, self.ok = status, status < 400
        self._json, self.text, self._content = json_data, text, content
        self.headers = {"content-length": str(len(content))}

    def json(self):
        return self._json

    def raise_for_status(self):
        if not self.ok:
            raise updater.requests.HTTPError(str(self.status_code))

    def iter_content(self, _size):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_release(monkeypatch, tag="v9.0.0", payload=b"new build", sha=None):
    key = updater.platform_key()
    name = f"Clickwheel-{key}.zip"
    sums = f"{sha or hashlib.sha256(payload).hexdigest()}  {name}\n"
    release = {"tag_name": tag, "body": "Notes", "html_url": "https://example/rel", "assets": [
        {"name": name, "browser_download_url": "https://dl/app", "size": len(payload)},
        {"name": updater.CHECKSUMS, "browser_download_url": "https://dl/sums"},
    ]}

    class Session:
        headers: dict = {}

        def get(self, url, **_kw):
            return {updater.LATEST_API: FakeResponse(json_data=release), "https://dl/sums": FakeResponse(text=sums),
                    "https://dl/app": FakeResponse(content=payload)}[url]

    monkeypatch.setattr(updater, "_session", lambda: Session())


def test_check_finds_newer_release(monkeypatch):
    fake_release(monkeypatch)
    rel = updater.check("0.1.0")
    assert rel.version == "9.0.0" and rel.notes == "Notes" and len(rel.sha256) == 64
    assert updater.check("9.0.0") is None


def test_download_verifies_checksum(monkeypatch, tmp_path):
    fake_release(monkeypatch)
    rel = updater.check("0.1.0")
    assert updater.download(rel, tmp_path).read_bytes() == b"new build"
    fake_release(monkeypatch, sha="0" * 64)
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.download(updater.check("0.1.0"), tmp_path / "bad")
    assert not (tmp_path / "bad" / rel.asset_name).exists()


def test_unpack_zip_tar_and_reject_traversal(tmp_path):
    z = tmp_path / "Clickwheel-windows-x64.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("Clickwheel/Clickwheel.exe", "exe")
    assert (updater.unpack(z, tmp_path / "s1") / "Clickwheel.exe").read_text() == "exe"

    t = tmp_path / "Clickwheel-linux-x64.tar.gz"
    with tarfile.open(t, "w:gz") as tf:
        data = b"bin"
        info = tarfile.TarInfo("Clickwheel/Clickwheel")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    assert (updater.unpack(t, tmp_path / "s2") / "Clickwheel").read_bytes() == b"bin"

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escape.txt", "x")
    with pytest.raises(updater.UpdateError, match="unsafe"):
        updater.unpack(evil, tmp_path / "s3")


def test_windows_script_mirrors_and_relaunches(tmp_path):
    name, body = updater.swap_script(tmp_path / "new", tmp_path / "app", tmp_path / "stage", 1234, "win32")
    assert name.endswith(".cmd")
    assert 'PID eq 1234' in body and "robocopy" in body and "Clickwheel.exe" in body
    assert "/XF unins*.exe" in body  # keep the installer's uninstaller


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX hand-off script")
def test_posix_swap_script_replaces_and_relaunches(tmp_path):
    target = tmp_path / "Clickwheel"
    target.mkdir()
    (target / "old.txt").write_text("old")
    staging = tmp_path / ".clickwheel-update"
    new = staging / "Clickwheel"
    new.mkdir(parents=True)
    marker = tmp_path / "relaunched"
    launcher = new / "Clickwheel"
    launcher.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    launcher.chmod(0o755)

    dead = subprocess.Popen(["true"])
    dead.wait()
    _name, body = updater.swap_script(new, target, staging, dead.pid, "linux")
    script = tmp_path / "swap.sh"
    script.write_text(body)
    subprocess.run(["/bin/sh", str(script)], check=True, timeout=20)
    for _ in range(50):
        if marker.exists():
            break
        subprocess.run(["sleep", "0.1"])

    assert (target / "Clickwheel").exists() and not (target / "old.txt").exists()
    assert not staging.exists() and not (tmp_path / "Clickwheel.old").exists()
    assert marker.exists() and not script.exists()


def test_running_from_source_cannot_self_update():
    assert "source" in updater.self_update_blocker()


def test_appimage_points_to_download_page(monkeypatch):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setenv("APPIMAGE", "/home/me/Clickwheel.AppImage")
    assert "AppImage" in updater.self_update_blocker()


def test_prerelease_versions_sort_before_the_release():
    order = ["0.1.5", "0.1.6", "0.2.0-alpha.3", "0.2.0-beta.1", "0.2.0-beta.2", "0.2.0-beta.10",
             "0.2.0-rc.1", "v0.2.0", "0.2.1"]
    assert sorted(order, key=updater.parse_version) == order
    assert updater.is_prerelease("v0.2.0-beta.1") and not updater.is_prerelease("0.2.0")
    assert updater.default_channel("0.2.0-beta.1") == "beta" and updater.default_channel("0.1.6") == "stable"


def fake_releases(monkeypatch, releases):
    sums = "".join(f"{'a' * 64}  {a['name']}\n" for r in releases for a in r["assets"])
    for r in releases:
        r["assets"].append({"name": updater.CHECKSUMS, "browser_download_url": "https://dl/sums"})
    latest = next(r for r in releases if not r.get("prerelease"))

    class Session:
        headers: dict = {}

        def get(self, url, **_kw):
            return {updater.LATEST_API: FakeResponse(json_data=latest), updater.RELEASES_API: FakeResponse(json_data=releases),
                    "https://dl/sums": FakeResponse(text=sums)}[url]

    monkeypatch.setattr(updater, "_session", lambda: Session())


def release(tag, prerelease=False, platforms=None):
    keys = platforms or [updater.platform_key()]
    return {"tag_name": tag, "prerelease": prerelease, "body": "", "html_url": "", "assets": [
        {"name": f"Clickwheel-{k}.zip", "browser_download_url": f"https://dl/{k}", "size": 1} for k in keys]}


def test_channels(monkeypatch):
    other = "windows-x64" if updater.platform_key() != "windows-x64" else "linux-x64"
    fake_releases(monkeypatch, [release("v0.3.0-beta.1", True, [other]), release("v0.2.0-beta.2", True),
                                release("v0.1.6"), release("v0.2.0-beta.1", True)])
    assert updater.check("0.1.5", "stable").version == "0.1.6"
    assert updater.check("0.1.6", "stable") is None
    beta = updater.check("0.1.5", "beta")  # the newest with a build for this platform
    assert beta.version == "0.2.0-beta.2" and beta.prerelease
    assert updater.check("0.2.0-beta.2") is None  # a beta build follows the beta channel
    assert updater.check("0.2.0-beta.1").version == "0.2.0-beta.2"
