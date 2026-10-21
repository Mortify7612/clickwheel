"""Build helpers: `python -m clickwheel.tools fetch-fpcalc|fetch-ffmpeg`."""

import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FFMPEG_DIR = ROOT / "build" / "ffmpeg"
# Gyan Doshi's static GPL build (LAME, x264), pinned by version and checksum.
WINDOWS_FFMPEG = (
    "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip",
    "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba",
)


def fetch_fpcalc() -> int:
    from pypodlib.sync.dependency_manager import download_fpcalc, get_bundled_fpcalc

    path = get_bundled_fpcalc() or download_fpcalc()
    if not path:
        print("Failed to download fpcalc", file=sys.stderr)
        return 1
    print(path)
    return 0


def fetch_ffmpeg() -> int:
    """Put ffmpeg, ffprobe and their license in build/ffmpeg/ for the Mac and Windows apps."""
    if sys.platform == "darwin":
        return subprocess.call([str(ROOT / "packaging" / "build-ffmpeg-macos.sh")])
    if sys.platform != "win32":
        print("Linux builds use the system's ffmpeg", file=sys.stderr)
        return 2
    import requests

    url, sha256 = WINDOWS_FFMPEG
    FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as archive:
        digest = hashlib.sha256()
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            for chunk in response.iter_content(1 << 20):
                digest.update(chunk)
                archive.write(chunk)
        if digest.hexdigest() != sha256:
            print(f"Checksum mismatch for {url}", file=sys.stderr)
            return 1
        with zipfile.ZipFile(archive) as z:
            wanted = {"bin/ffmpeg.exe": "ffmpeg.exe", "bin/ffprobe.exe": "ffprobe.exe", "LICENSE": "LICENSE-ffmpeg.txt"}
            for member in z.namelist():
                inner = member.split("/", 1)[-1]
                if inner in wanted:
                    (FFMPEG_DIR / wanted.pop(inner)).write_bytes(z.read(member))
    if wanted:
        print(f"Archive lacks {', '.join(wanted)}", file=sys.stderr)
        return 1
    print(FFMPEG_DIR)
    return 0


def main() -> int:
    commands = {"fetch-fpcalc": fetch_fpcalc, "fetch-ffmpeg": fetch_ffmpeg}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print(f"usage: python -m clickwheel.tools {'|'.join(commands)}", file=sys.stderr)
        return 2
    return commands[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
