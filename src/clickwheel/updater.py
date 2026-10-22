"""Self-update from this repo's GitHub releases.

Each release carries one package per platform plus ``SHA256SUMS.txt``. Updating
a frozen app works by downloading and verifying the new build, unpacking it next to the
installed one, and handing off to a tiny script that waits for this process to
exit, swaps the folders/bundle, and relaunches.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from ._version import __version__

RELEASES_REPO = "Mortify7612/clickwheel"
LATEST_API = f"https://api.github.com/repos/{RELEASES_REPO}/releases/latest"  # never a pre-release
RELEASES_API = f"https://api.github.com/repos/{RELEASES_REPO}/releases?per_page=30"
RELEASES_PAGE = f"https://github.com/{RELEASES_REPO}/releases/latest"
CHECKSUMS = "SHA256SUMS.txt"
# Stable follows full releases only; beta also takes pre-releases (tags like v0.2.0-beta.1),
# whichever is newest. A beta build follows the beta channel until told otherwise.
CHANNELS = {"stable": "Stable", "beta": "Beta"}

ProgressFn = Callable[[int, int], None]


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    asset_size: int
    sha256: str
    prerelease: bool = False


PRE_RANKS = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2}
STABLE_RANK = 9


def parse_version(text: str) -> tuple[int, ...]:
    """Sortable: 0.2.0-beta.1 < 0.2.0-beta.2 < 0.2.0-rc.1 < 0.2.0."""
    base, _, pre = text.strip().lstrip("v").partition("-")
    nums = [int(n) for n in re.findall(r"\d+", base)[:3]]
    nums += [0] * (3 - len(nums))
    if not pre:
        return (*nums, STABLE_RANK, 0)
    word = re.match(r"[a-z]*", pre.lower()).group()
    number = re.findall(r"\d+", pre)
    return (*nums, PRE_RANKS.get(word, 0), int(number[0]) if number else 0)


def is_prerelease(version: str) -> bool:
    return parse_version(version)[3] != STABLE_RANK


def default_channel(current: str = __version__) -> str:
    return "beta" if is_prerelease(current) else "stable"


def platform_key(system: str = sys.platform, machine: str | None = None) -> str:
    machine = (machine or platform.machine()).lower()
    if system == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else "macos-intel"
    if system == "win32":
        return "windows-x64"
    return "linux-x64"


def asset_for(assets: list[dict], key: str) -> dict | None:
    return next((a for a in assets if a.get("name", "").startswith(f"Clickwheel-{key}.")), None)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/vnd.github+json", "User-Agent": f"Clickwheel/{__version__}"})
    return s


def check(current: str = __version__, channel: str | None = None) -> Release | None:
    """Return the newest release on ``channel`` if it is newer than ``current``, else None."""
    s = _session()
    beta = (channel or default_channel(current)) == "beta"
    try:
        resp = s.get(RELEASES_API if beta else LATEST_API, timeout=15)
    except requests.RequestException as exc:
        raise UpdateError(f"Couldn't reach GitHub: {exc}") from exc
    if resp.status_code == 404:
        return None  # nothing published yet
    if not resp.ok:
        raise UpdateError(f"GitHub returned {resp.status_code} while checking for updates")
    if beta:
        # The newest release, pre-release or not, that has a build for this platform.
        candidates = [r for r in resp.json() if not r.get("draft") and asset_for(r.get("assets", []), platform_key())]
        if not candidates:
            return None
        data = max(candidates, key=lambda r: parse_version(r.get("tag_name", "")))
    else:
        data = resp.json()
    version = data.get("tag_name", "").lstrip("v")
    if parse_version(version) <= parse_version(current):
        return None
    assets = data.get("assets", [])
    asset = asset_for(assets, platform_key())
    if asset is None:
        raise UpdateError(f"Version {version} has no download for this platform ({platform_key()}).")
    sums = next((a for a in assets if a.get("name") == CHECKSUMS), None)
    sha = ""
    if sums:
        text = s.get(sums["browser_download_url"], timeout=15).text
        sha = parse_checksums(text).get(asset["name"], "")
    if not sha:
        raise UpdateError("The release is missing its checksum file, so it can't be verified.")
    return Release(version, data.get("body") or "", data.get("html_url") or RELEASES_PAGE,
                   asset["name"], asset["browser_download_url"], int(asset.get("size") or 0), sha,
                   bool(data.get("prerelease")) or is_prerelease(version))


def parse_checksums(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            out[parts[1].lstrip("*")] = parts[0].lower()
    return out


# ── Installing ───────────────────────────────────────────────────────────────

def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_target() -> Path:
    """The folder (Windows/Linux) or .app bundle (macOS) to replace."""
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        bundle = exe.parents[2]  # Clickwheel.app/Contents/MacOS/Clickwheel
        if bundle.suffix == ".app":
            return bundle
    return exe.parent


def self_update_blocker() -> str | None:
    """Why this copy can't replace itself, or None if it can."""
    if not is_frozen():
        return "You're running Clickwheel from source; update with git pull instead."
    if os.environ.get("APPIMAGE"):
        return "This is the AppImage build. Download the new AppImage and replace the old one."
    target = install_target()
    if not os.access(target.parent, os.W_OK):
        return f"Clickwheel is installed in a folder it can't write to ({target.parent})."
    if sys.platform == "darwin" and "/AppTranslocation/" in str(target):
        return "macOS is running Clickwheel from a temporary copy. Move it to Applications, then try again."
    return None


def download(release: Release, dest_dir: Path, progress: ProgressFn | None = None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / release.asset_name
    digest = hashlib.sha256()
    done = 0
    try:
        with _session().get(release.asset_url, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or release.asset_size or 0)
            with open(path, "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    fh.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    except requests.RequestException as exc:
        raise UpdateError(f"Download failed: {exc}") from exc
    if digest.hexdigest() != release.sha256:
        path.unlink(missing_ok=True)
        raise UpdateError("The download didn't match its published checksum and was discarded.")
    return path


def unpack(archive: Path, staging: Path) -> Path:
    """Extract the new build into ``staging``; return the new app folder/bundle."""
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    name = archive.name
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            _check_members(zf.namelist(), staging)
            zf.extractall(staging)
        new = staging / "Clickwheel"
    elif name.endswith(".tar.gz"):
        with tarfile.open(archive) as tf:
            tf.extractall(staging, filter="data")
        new = staging / "Clickwheel"
    elif name.endswith(".dmg"):
        mount = staging / "mnt"
        mount.mkdir()
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(archive)],
                       check=True, capture_output=True)
        try:
            subprocess.run(["ditto", str(mount / "Clickwheel.app"), str(staging / "Clickwheel.app")],
                           check=True, capture_output=True)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount), "-quiet"], capture_output=True)
        mount.rmdir()
        new = staging / "Clickwheel.app"
    else:
        raise UpdateError(f"Don't know how to unpack {name}")
    if not new.exists():
        raise UpdateError("The downloaded package doesn't contain Clickwheel.")
    return new


def _check_members(names: list[str], root: Path) -> None:
    root = root.resolve()
    for n in names:
        if not (root / n).resolve().is_relative_to(root):
            raise UpdateError("The update archive contains unsafe paths.")


def swap_script(new: Path, target: Path, staging: Path, pid: int, system: str = sys.platform) -> tuple[str, str]:
    """Return (filename, contents) of the hand-off script for ``system``."""
    if system == "win32":
        exe = target / "Clickwheel.exe"
        return "clickwheel-update.cmd", "\r\n".join([
            "@echo off",
            ":wait",
            f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL && (timeout /t 1 /nobreak >NUL & goto wait)',
            # /XF keeps the installer's uninstaller, which isn't in the new build.
            f'robocopy "{new}" "{target}" /MIR /XF unins*.exe unins*.dat /NFL /NDL /NJH /NJS /NP >NUL',
            f'start "" "{exe}"',
            f'rmdir /s /q "{staging}"',
            '(goto) 2>nul & del "%~f0"',
            "",
        ])
    q = shlex.quote
    old = target.with_name(target.name + ".old")
    relaunch = f"open {q(str(target))}" if system == "darwin" else f"{q(str(target / 'Clickwheel'))} &"
    return "clickwheel-update.sh", "\n".join([
        "#!/bin/sh",
        f"while kill -0 {pid} 2>/dev/null; do sleep 0.5; done",
        f"rm -rf {q(str(old))}",
        # Keep the old copy until the new one is in place, and roll back on failure.
        f"if mv {q(str(target))} {q(str(old))} && mv {q(str(new))} {q(str(target))}; then",
        f"  rm -rf {q(str(old))}",
        "else",
        f"  [ -e {q(str(target))} ] || mv {q(str(old))} {q(str(target))}",
        "fi",
        f"rm -rf {q(str(staging))}",
        relaunch,
        'rm -f "$0"',
        "",
    ])


def apply(release: Release, progress: ProgressFn | None = None) -> None:
    """Download, verify and stage ``release``, then start the swap script.

    The caller must quit the app right after this returns.
    """
    if reason := self_update_blocker():
        raise UpdateError(reason)
    target = install_target()
    staging = target.parent / ".clickwheel-update"  # same filesystem -> rename, not copy
    with tempfile.TemporaryDirectory(prefix="clickwheel-dl-") as tmp:
        archive = download(release, Path(tmp), progress)
        new = unpack(archive, staging)
    name, body = swap_script(new, target, staging, os.getpid())
    script = Path(tempfile.gettempdir()) / name
    script.write_text(body, encoding="utf-8")
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=flags, close_fds=True)
    else:
        script.chmod(0o700)
        subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
