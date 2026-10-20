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
)
# wasmtime loads its native lib from wasmtime/<platform>/ via ctypes; PyInstaller's
# dynamic-lib collector skips it, so ship it at the same relative path.
_wasmtime_dir = os.path.dirname(wasmtime.__file__)
binaries = [
    (os.path.join(root, f), os.path.join("wasmtime", os.path.relpath(root, _wasmtime_dir)))
    for root, _dirs, files in os.walk(_wasmtime_dir)
    for f in files if f.endswith((".so", ".dylib", ".dll"))
] + [(deno.find_deno_bin(), ".")]
# pyPodLib imports most of its modules lazily inside functions.
hiddenimports = collect_submodules("pypodlib") + collect_submodules("ytmusicapi") + collect_submodules("yt_dlp_ejs")

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
)
coll = COLLECT(exe, a.binaries, a.datas, name="Clickwheel", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Clickwheel.app",
        bundle_identifier="io.github.captainslow48.clickwheel",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
