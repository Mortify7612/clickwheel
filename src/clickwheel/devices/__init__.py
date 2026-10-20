"""Connected-iPod discovery and the sync backend for each one."""

from __future__ import annotations

import shutil
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


def scan() -> list[Device]:
    """Find iPods on every mounted volume (works on Linux, macOS and Windows)."""
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
