"""Linux desktop integration: launcher entry and icon in the user's home.

KDE/GNOME on Wayland take an app's icon from the .desktop file matching its
app id ("clickwheel", or "clickwheel-dev" from a source checkout), so without
one the window shows a generic icon.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from .config import APP_ID, DISPLAY_NAME, IS_DEV

ICONS = Path(__file__).resolve().parent.parent.parent / "packaging" / "icons"  # source checkout
ASSET = Path(__file__).resolve().parent / "assets" / f"{APP_ID}.png"


def _launcher() -> str:
    if getattr(sys, "frozen", False):
        # An AppImage runs from a temporary mount; the launcher must start the AppImage file.
        return os.environ.get("APPIMAGE") or sys.executable
    script = Path(sys.executable).with_name("clickwheel")  # the venv's entry-point script
    return str(script) if script.exists() else f"{sys.executable} -m clickwheel"


def install_desktop_entry() -> list[Path]:
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    written = []
    sizes = {}
    if ICONS.is_dir():
        for path in ICONS.glob(f"{APP_ID}-*.png"):
            if match := re.fullmatch(rf"{re.escape(APP_ID)}-(\d+)", path.stem):
                sizes[int(match[1])] = path
    if not sizes:
        sizes = {256: ASSET}
    for size, src in sorted(sizes.items()):
        if size > 512:
            continue
        dest = data / "icons" / "hicolor" / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        written.append(dest)
    launcher = _launcher()
    entry = data / "applications" / f"{APP_ID}.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={DISPLAY_NAME}",
        "GenericName=Music downloader and iPod sync",
        "Comment=YouTube Music to iPod" + (" (run from the source checkout)" if IS_DEV else ""),
        f"Exec={launcher}",
        f"Icon={APP_ID}",
        "Terminal=false",
        "Categories=AudioVideo;Audio;Player;",
        f"StartupWMClass={APP_ID}",
        "",
    ]))
    written.append(entry)
    if IS_DEV:
        # Older versions installed the source checkout as plain "Clickwheel"; that name is
        # the release's now. Only an entry that starts this checkout is removed.
        old = data / "applications" / "clickwheel.desktop"
        if old.exists() and f"Exec={launcher}" in old.read_text().splitlines():
            old.unlink()
    return written
