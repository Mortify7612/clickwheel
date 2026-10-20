"""Serialise access to pyPodLib's process-wide "current device".

pyPodLib reads device-specific settings (artwork formats, checksum material,
...) from a single global that every ``pypodlib.connect`` overwrites. A device
scan running while another iPod syncs would otherwise make the sync use the
wrong model's profile. All pyPodLib work happens under this lock with the
intended device selected.
"""

from __future__ import annotations

import functools
import os
import threading
from contextlib import contextmanager

DEVICE_LOCK = threading.RLock()


@contextmanager
def active_device(info):
    from pypodlib.device.info import get_current_device, set_current_device

    with DEVICE_LOCK:
        previous = get_current_device()
        set_current_device(info)
        try:
            yield
        finally:
            try:
                set_current_device(previous)
            except Exception:  # previous device unplugged / no longer valid
                set_current_device(None)


def on_device(method):
    """Run an ``AppleSync`` method with its own iPod as pyPodLib's current device."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with active_device(self.ipod.info):
            return method(self, *args, **kwargs)

    return wrapper


def is_read_only(path) -> bool:
    """True when the volume is mounted read-only (e.g. the kernel found FAT errors)."""
    try:
        return bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    except (OSError, AttributeError):  # AttributeError: no statvfs on Windows
        return False
