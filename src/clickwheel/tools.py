"""Build helpers: `python -m clickwheel.tools fetch-fpcalc`."""

import sys


def main() -> int:
    if sys.argv[1:] != ["fetch-fpcalc"]:
        print("usage: python -m clickwheel.tools fetch-fpcalc", file=sys.stderr)
        return 2
    from pypodlib.sync.dependency_manager import download_fpcalc, get_bundled_fpcalc

    path = get_bundled_fpcalc() or download_fpcalc()
    if not path:
        print("Failed to download fpcalc", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
