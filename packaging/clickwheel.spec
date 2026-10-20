# PyInstaller spec: `uv run pyinstaller packaging/clickwheel.spec`
# Produces dist/Clickwheel/ (Linux/Windows) or dist/Clickwheel.app (macOS).
import os
import sys

import deno
import wasmtime
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = (
    collect_data_files("ytmusicapi")           # locale files
    + collect_data_files("yt_dlp_ejs")         # YouTube challenge solver scripts
    + collect_data_files("pypodlib")           # calcHashAB.wasm (Nano 6G/7G)
    + [(os.path.join(SPECPATH, "..", "src", "clickwheel", "assets", "clickwheel.png"), "clickwheel/assets")]
)
ICONS = os.path.join(SPECPATH, "icons")
# wasmtime loads its native lib from wasmtime/<platform>/ via ctypes; PyInstaller's
# dynamic-lib collector skips it, so ship it at the same relative path.
_wasmtime_dir = os.path.dirname(wasmtime.__file__)
binaries = [
    (os.path.join(root, f), os.path.join("wasmtime", os.path.relpath(root, _wasmtime_dir)))
    for root, _dirs, files in os.walk(_wasmtime_dir)
    for f in files if f.endswith((".so", ".dylib", ".dll"))
] + [(deno.find_deno_bin(), ".")]

# Chromaprint's fpcalc (song matching during sync). Prefer pyPodLib's static
# download, which CI fetches before building; a distro build would drag in
# system libraries that may not exist on the user's machine.
from pypodlib.sync.dependency_manager import get_bundled_fpcalc  # noqa: E402

_fpcalc = get_bundled_fpcalc()
if not _fpcalc:
    raise SystemExit("fpcalc missing: run `uv run python -m clickwheel.tools fetch-fpcalc` first")
binaries.append((_fpcalc, "."))
# pyPodLib imports most of its modules lazily inside functions.
hiddenimports = collect_submodules("pypodlib") + collect_submodules("ytmusicapi") + collect_submodules("yt_dlp_ejs")

_version = {}
exec(open(os.path.join(SPECPATH, "..", "src", "clickwheel", "_version.py")).read(), _version)
_version = _version["__version__"]

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[os.path.join(SPECPATH, "..", "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Clickwheel",
    console=False,
    upx=False,
    icon=os.path.join(ICONS, "clickwheel.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Clickwheel", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Clickwheel.app",
        bundle_identifier="io.github.captainslow48.clickwheel",
        icon=os.path.join(ICONS, "clickwheel.icns"),
        info_plist={
            "CFBundleShortVersionString": _version,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
