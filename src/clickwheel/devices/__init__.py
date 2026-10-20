"""Connected-iPod discovery and the sync backend for each one."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass
class Device:
    path: Path
    name: str
    model: str
    firmware: str  # "apple" | "rockbox"
    has_apple_db: bool
    ipod: object | None = None  # pypodlib.IPod when the Apple layout is present

    @property
    def label(self) -> str:
        tag = " · Rockbox" if self.firmware == "rockbox" else ""
        return f"{self.name} — {self.model}{tag} ({self.path})"

    def free_space(self) -> tuple[int, int]:
        usage = shutil.disk_usage(self.path)
        return usage.free, usage.total

    @property
    def is_shuffle(self) -> bool:
        return bool(self.ipod and getattr(self.ipod.capabilities, "is_shuffle", False))

    def backend(self, prefer_rockbox_files: bool = True):
        if self.firmware == "rockbox" and (prefer_rockbox_files or self.ipod is None):
            from .rockbox import RockboxSync

            return RockboxSync(self.path)
        from .apple import AppleSync

        if self.ipod is None:
            raise RuntimeError("This device has no iPod_Control folder; restore it with iTunes/Finder first.")
        return AppleSync(self.ipod)

    def eject(self) -> str:
        from pypodlib.device.eject import eject_ipod

        ok, message = eject_ipod(str(self.path))
        if not ok:
            raise RuntimeError(message or "Eject failed")
        return message or "Safe to unplug"


def identify(path: Path) -> Device | None:
    """Describe the iPod (or Rockbox player) mounted at ``path``."""
    path = Path(path)
    rockbox = (path / ".rockbox").is_dir()
    apple_db = (path / "iPod_Control").is_dir()
    if not (rockbox or apple_db):
        return None
    ipod = None
    name, model = path.name or str(path), "Rockbox player"
    if apple_db:
        try:
            import pypodlib

            ipod = pypodlib.connect(path)
            model = f"{ipod.model_family} {ipod.generation} {ipod.capacity}".strip()
            try:
                name = ipod.library().master_playlist.name or name
            except Exception:
                pass
        except Exception:
            model = "iPod (unrecognised model)"
    return Device(path, name, model, "rockbox" if rockbox else "apple", apple_db, ipod)


MOUNTABLE_FS = {"vfat", "hfsplus"}
_mount_failed: set[str] = set()  # don't retry a device every poll


def unmounted_ipod_volumes(lsblk_json: dict) -> list[str]:
    """Block-device paths of iPod music volumes that aren't mounted.

    Shuffles put the filesystem on the whole disk; other iPods have a
    partition table with the music volume as a child of the Apple disk.
    """
    paths = []
    for disk in lsblk_json.get("blockdevices", []):
        if (disk.get("vendor") or "").strip() != "Apple" or "ipod" not in (disk.get("model") or "").lower():
            continue
        if disk.get("tran") not in (None, "usb"):
            continue
        for vol in [disk, *disk.get("children", [])]:
            if vol.get("fstype") in MOUNTABLE_FS and not vol.get("mountpoint") and not vol.get("mountpoints", [None])[0]:
                paths.append(vol["path"])
    return paths


def mount_unmounted_ipods() -> list[str]:
    """Linux: mount plugged-in iPods the desktop didn't automount.

    Uses udisks, the same unprivileged mechanism file managers use. macOS and
    Windows always mount these volumes themselves.
    """
    if not sys.platform.startswith("linux") or not shutil.which("lsblk") or not shutil.which("udisksctl"):
        return []
    try:
        out = subprocess.run(["lsblk", "-J", "-o", "NAME,PATH,FSTYPE,MOUNTPOINT,VENDOR,MODEL,TRAN,TYPE"],
                             capture_output=True, text=True, timeout=10, check=True).stdout
        candidates = unmounted_ipod_volumes(json.loads(out))
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    _mount_failed.intersection_update(candidates)  # forget devices that were unplugged
    mounted = []
    for path in candidates:
        if path in _mount_failed:
            continue
        result = subprocess.run(["udisksctl", "mount", "-b", path, "--no-user-interaction"],
                                capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            mounted.append(path)
        else:
            _mount_failed.add(path)
    return mounted


def scan() -> list[Device]:
    """Find iPods on every mounted volume (works on Linux, macOS and Windows)."""
    mount_unmounted_ipods()
    found: dict[Path, Device] = {}
    for part in psutil.disk_partitions(all=False):
        mount = Path(part.mountpoint)
        try:
            dev = identify(mount)
        except (OSError, PermissionError):
            continue
        if dev:
            found[mount] = dev
    return list(found.values())
