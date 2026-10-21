"""Connected-device discovery (iPods, Rockbox players, a Zune HD) and the sync backend for each one."""

from __future__ import annotations

import json
import plistlib
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass
class Device:
    path: Path
    name: str
    model: str
    firmware: str  # "apple" | "rockbox" | "zune"
    has_apple_db: bool
    ipod: object | None = None  # pypodlib.IPod when the Apple layout is present
    zune: object | None = None  # zune.ZuneInfo for a Zune HD (an MTP device: ``path`` is only an identifier)

    @property
    def label(self) -> str:
        if self.zune is not None:
            return f"{self.name} — {self.model}" + (" (in use by another program)" if self.zune.busy else "")
        tag = " · Rockbox" if self.firmware == "rockbox" else ""
        return f"{self.name} — {self.model}{tag} ({self.path})"

    @property
    def read_only(self) -> bool:
        from ._session import is_read_only

        return is_read_only(self.path)

    def free_space(self) -> tuple[int, int]:
        if self.zune is not None:
            return self.zune.free, self.zune.total
        usage = shutil.disk_usage(self.path)
        return usage.free, usage.total

    @property
    def is_shuffle(self) -> bool:
        return bool(self.ipod and getattr(self.ipod.capabilities, "is_shuffle", False))

    def backend(self, prefer_rockbox_files: bool = True):
        if self.zune is not None:
            from .zune import ZuneSync

            if self.zune.busy:
                raise RuntimeError("Another program is using the Zune. On KDE, release it from the iPod tab.")
            return ZuneSync(self.zune)
        if self.firmware == "rockbox" and (prefer_rockbox_files or self.ipod is None):
            from .rockbox import RockboxSync

            return RockboxSync(self.path)
        from .apple import AppleSync

        if self.ipod is None:
            raise RuntimeError("This device has no iPod_Control folder; restore it with iTunes/Finder first.")
        return AppleSync(self.ipod)

    def eject(self) -> str:
        if self.zune is not None:
            return "Safe to unplug"  # MTP: nothing is cached on this side
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
        from pypodlib.device.info import get_current_device, set_current_device

        from ._session import DEVICE_LOCK

        # pypodlib.connect() makes this iPod the process-wide current device;
        # don't let a scan swap it out from under a sync in progress.
        with DEVICE_LOCK:
            previous = get_current_device()
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
            finally:
                try:
                    set_current_device(previous)
                except Exception:
                    set_current_device(None)
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


def macos_mount_point(mount: Path) -> Path:
    """``mount`` spelled the way diskutil spells it.

    Accented letters in a volume name can come back composed from the mount
    table and decomposed from diskutil (or the other way round). Both name the
    same folder, but pyPodLib compares the two byte for byte before writing and
    refuses with "not mounted as its own volume".
    """
    try:
        out = subprocess.run(["diskutil", "info", "-plist", str(mount)], capture_output=True, timeout=10).stdout
        spelled = str(plistlib.loads(out).get("MountPoint") or "")
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, ValueError, AttributeError):
        return mount
    if spelled and unicodedata.normalize("NFC", spelled) == unicodedata.normalize("NFC", str(mount)):
        return Path(spelled)
    return mount


_zune_device: Device | None = None  # last seen Zune; probing it opens an MTP session
ZUNE_STATUS_EVERY_S = 60


def scan_zune() -> Device | None:
    """The plugged-in Zune HD (Linux only), reusing what an earlier scan learned."""
    global _zune_device
    if not sys.platform.startswith("linux"):
        return None
    try:
        import usb.core

        from . import zune
    except ImportError:
        return None
    try:
        present = usb.core.find(idVendor=zune.VENDOR, idProduct=zune.PRODUCT) is not None
    except usb.core.NoBackendError:
        return None
    if not present:
        _zune_device = None
    elif _zune_device is None or _zune_device.zune.busy:
        try:
            info = zune.probe()
        except Exception:
            info = None
        if info is not None:  # None also while a session is open: keep what we had
            _zune_device = Device(Path(f"zune:{info.serial}"), info.name, "Zune HD", "zune", False, zune=info)
    elif time.monotonic() - _zune_device.zune.checked > ZUNE_STATUS_EVERY_S:
        zune.refresh(_zune_device.zune)  # battery and free space drift while it sits there
    return _zune_device


def scan() -> list[Device]:
    """Find iPods on every mounted volume (works on Linux, macOS and Windows). See ``scan_zune`` for a Zune."""
    mount_unmounted_ipods()
    found: dict[Path, Device] = {}
    for part in psutil.disk_partitions(all=False):
        mount = Path(part.mountpoint)
        if sys.platform == "darwin" and not part.mountpoint.isascii():
            mount = macos_mount_point(mount)
        try:
            dev = identify(mount)
        except (OSError, PermissionError):
            continue
        if dev:
            found[mount] = dev
    return list(found.values())
