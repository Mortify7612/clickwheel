"""Clickwheel: YouTube Music -> tagged local library -> iPod."""

import argparse
import sys


def _progress(msg: str, cur: int, total: int) -> None:
    print(f"\r[{cur}/{total}] {msg[:70]:<70}" if total else f"\r{msg[:80]:<80}", end="", flush=True)


def cli(argv: list[str]) -> int:
    from . import auth
    from .config import DB_FILE, Settings
    from .library import Library

    parser = argparse.ArgumentParser(prog="clickwheel", description="YouTube Music to iPod")
    sub = parser.add_subparsers(dest="cmd", required=True)
    login = sub.add_parser("login", help="add a YouTube Music account (or refresh its session)")
    login.add_argument("--browser", choices=auth.BROWSERS)
    login.add_argument("--browser-profile")
    login.add_argument("--account", default="0", help="Google account # in that browser (0 = first)")
    login.add_argument("--cookies", help="Netscape cookies.txt file")
    sub.add_parser("accounts", help="list saved accounts (* = active)")
    use = sub.add_parser("use", help="switch the active account")
    use.add_argument("account", help="account name, handle or id")
    logout = sub.add_parser("logout", help="forget an account (default: the active one)")
    logout.add_argument("account", nargs="?")
    dl = sub.add_parser("download", help="download a playlist/album/song link")
    dl.add_argument("url", nargs="+")
    dl.add_argument("--account", help="account to use (default: the active one)")
    sub.add_parser("devices", help="list connected iPods")
    sync = sub.add_parser("sync", help="sync the library to an iPod")
    sync.add_argument("--device", help="mount path (default: first detected)")
    args = parser.parse_args(argv)

    settings = Settings.load()
    def find_account(query: str | None) -> auth.Profile | None:
        if not query:
            return auth.active_profile()
        q = query.casefold().lstrip("@")
        match = next((p for p in auth.profiles()
                      if q in (p.id, p.name.casefold(), p.handle.casefold().lstrip("@"))), None)
        if match is None:
            raise SystemExit(f"No saved account matches {query!r}. See: clickwheel accounts")
        return match

    if args.cmd == "login":
        if args.cookies:
            profile = auth.sign_in_from_cookies_file(args.cookies, args.account)
        elif args.browser:
            profile = auth.sign_in_from_browser(args.browser, args.browser_profile, args.account)
        else:
            print("Paste request headers from music.youtube.com, then Ctrl-D:")
            profile = auth.sign_in_from_headers(sys.stdin.read())
        print("Signed in as", profile.label)
    elif args.cmd == "accounts":
        active = auth.active_profile()
        for p in auth.profiles():
            print(f"{'*' if active and p.id == active.id else ' '} {p.label}  [{p.id}, Google account #{p.authuser}]")
    elif args.cmd == "use":
        profile = find_account(args.account)
        auth.set_active(profile.id)
        print("Active account:", profile.label)
    elif args.cmd == "logout":
        profile = find_account(args.account)
        if profile:
            auth.remove_profile(profile.id)
            print("Removed", profile.label)
    elif args.cmd == "download":
        from .pipeline import Pipeline, Status
        from .ytm import Resolver

        library = Library(settings.library_path, DB_FILE)
        profile = find_account(args.account)
        resolver = Resolver(auth.client(profile), cover_size=settings.cover_size,
                            prefer_album_versions=settings.prefer_album_versions)
        for url in args.url:
            collection = resolver.resolve_url(url)
            print(f"{collection.title}: {len(collection.tracks)} songs")

            def show(ev):
                if ev.status in (Status.DONE, Status.SKIPPED, Status.FAILED):
                    extra = f" ({ev.error.splitlines()[0]})" if ev.error else ""
                    print(f"  {ev.status.value:<10} {ev.meta.artist} - {ev.meta.title}{extra}")

            counts = Pipeline(library, workers=settings.parallel_downloads, cover_size=settings.cover_size,
                              cookies=auth.cookies_file(profile),
                              profile_id=profile.id if profile else "").run(collection, show)
            print("  " + ", ".join(f"{n} {s.value.lower()}" for s, n in counts.items()))
    elif args.cmd == "devices":
        from .devices import scan

        for dev in scan():
            print(dev.label)
    elif args.cmd == "sync":
        from pathlib import Path

        from .devices import identify, scan

        dev = identify(Path(args.device)) if args.device else next(iter(scan()), None)
        if dev is None:
            print("No iPod found.", file=sys.stderr)
            return 1
        print("Syncing to", dev.label)
        summary = dev.backend(settings.rockbox_prefers_files).sync(settings.library_path, progress=_progress)
        counts = (f"added {summary.added}, removed {summary.removed}, updated {summary.updated}, "
                  f"playlists {summary.playlists}")
        print(f"\nDone: {counts}" if summary.ok else f"\nSync failed (planned: {counts})")
        for err in summary.errors:
            print("ERROR:", err, file=sys.stderr)
        return 0 if summary.ok else 1
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        return cli(sys.argv[1:])
    from .gui.app import main as gui_main

    return gui_main()
