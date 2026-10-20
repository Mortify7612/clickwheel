"""Linux desktop integration: launcher entry and icon in the user's home.

KDE/GNOME on Wayland take an app's icon from the .desktop file matching its
app id ("clickwheel"), so without one the window shows a generic icon.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ICONS = Path(__file__).resolve().parent.parent.parent / "packaging" / "icons"  # source checkout
ASSET = Path(__file__).resolve().parent / "assets" / "clickwheel.png"


def _launcher() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    script = Path(sys.executable).with_name("clickwheel")  # the venv's entry-point script
    return str(script) if script.exists() else f"{sys.executable} -m clickwheel"


def install_desktop_entry() -> list[Path]:
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    written = []
    sizes = {int(p.stem.split("-")[1]): p for p in ICONS.glob("clickwheel-*.png")} if ICONS.is_dir() else {}
    if not sizes:
        sizes = {256: ASSET}
    for size, src in sorted(sizes.items()):
        if size > 512:
            continue
        dest = data / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "clickwheel.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        written.append(dest)
    entry = data / "applications" / "clickwheel.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=Clickwheel",
        "GenericName=Music downloader and iPod sync",
        "Comment=YouTube Music to iPod",
        f"Exec={_launcher()}",
        "Icon=clickwheel",
        "Terminal=false",
        "Categories=AudioVideo;Audio;Player;",
        "StartupWMClass=clickwheel",
        "",
    ]))
    written.append(entry)
    return written
