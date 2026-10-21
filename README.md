# Clickwheel

Download your YouTube Music playlists into a properly tagged local library, then sync it to an iPod.
Runs on Linux, Windows and macOS (Python + Qt).

```
YouTube Music ──ytmusicapi──▶ metadata (album, track #, year, art)
             └──yt-dlp─────▶ AAC .m4a ──mutagen──▶ ~/Music/Clickwheel/Artist/Album/01 Title.m4a
                                                    Playlists/*.m3u8
                                     ──pyPodLib──▶ iPod (iTunesDB/CDB + artwork, signed per model)
                                     ──iTunesSD──▶ iPod Shuffle
                                     ──file copy─▶ Rockbox
```

## Run

```sh
uv sync
uv run clickwheel            # GUI
uv run clickwheel --help     # CLI: login / download / devices / sync
uv run pytest                # tests (uses virtual iPods, no hardware needed)
```

`ffmpeg` must be on PATH (on Windows/macOS it is fetched automatically if missing).
yt-dlp's JavaScript runtime comes from the bundled `deno` wheel, so nothing else to install.

## Installers

Download the latest build from [Releases](https://github.com/Mortify7612/clickwheel/releases/latest):
`Clickwheel-windows-x64-setup.exe` (Windows), the `.dmg` for your Mac (Apple Silicon or Intel), or
`Clickwheel-linux-x86_64.AppImage` (Linux).

GitHub Actions builds the installers, plus the `.zip`/`.tar.gz`/`.dmg` packages the updater uses. Starting the **Build** workflow from the Actions tab produces test builds (artifacts on the
run page). Tests alone run on every push.

### Releasing and in-app updates

Pushing a version tag publishes a release here with the installers and `SHA256SUMS.txt`.
Clickwheel checks for a newer release once a day (and via Help ▸ Check for updates),
downloads the build for your platform, verifies its checksum, swaps itself out and restarts.

To publish a version:

```sh
# CI stamps the version from the tag; no file to bump
git tag -a v0.2.0 -m "What's new in this version (shown in the update dialog)"
git push origin v0.2.0
```

To build locally for the current OS: `uv run pyinstaller packaging/clickwheel.spec` → `dist/`.

The builds aren't code-signed, so the OS warns the first time you open them:

- **macOS:** open the app once, then System Settings ▸ Privacy & Security ▸ **Open Anyway**
  (or run `xattr -dr com.apple.quarantine /Applications/Clickwheel.app`).
- **Windows:** SmartScreen ▸ **More info** ▸ **Run anyway**.

## Signing in

YouTube Music has no OAuth flow a desktop app can ship, so Clickwheel reuses your browser session.
Sign in at music.youtube.com in a browser, then in Clickwheel choose **Sign in…** and either:

- **From browser:** reads the cookies directly. Firefox works everywhere. Recent Chrome on Windows
  encrypts cookies so other apps can't read them; use Firefox or one of the other two options there.
- **Paste headers:** copy the request headers of a `browse` request from DevTools ▸ Network.
- **Cookies file:** a `cookies.txt` exported by a browser extension.

Credentials are stored with user-only permissions in the platform config dir
(`~/.config/Clickwheel` on Linux). Public playlist/album/song links work without signing in;
signing in adds your library playlists, private playlists and (with Premium) 256 kbps audio.

## What you get

- Audio is YouTube's native AAC stream (128 kbps, 256 kbps with Premium), so it isn't re-encoded and every iPod plays it.
- Tags come from YouTube Music's album pages: title, artists, album artist, album, track n/N, year,
  explicit flag, "The …" sort names, and 1000 px square cover art. Each file also stores its YouTube ID.
- Music videos in a playlist are swapped for the matching album track when there is one. Matching uses
  the same artist, the same title and a length within 30 s, so covers and karaoke versions are never substituted.
  Turn this off in Settings.
- File and folder names are safe on FAT32 and Windows.
- Re-running a playlist ("Update from YouTube Music") downloads only new songs.

## iPod support

| Device | Method | Notes |
|---|---|---|
| iPod 1G–5.5G, Mini, Photo, Nano 1G–2G | iTunesDB | no signature needed |
| Classic 6G/6.5G/7G, Nano 3G–4G | iTunesDB + hash58 | key derived from the device's FireWire ID automatically |
| Nano 5G | iTunesCDB + hash72 | **needs one iTunes/Finder sync first** so the device has a `HashInfo` file |
| Nano 6G/7G | SQLite + hashAB | supported by pyPodLib; least tested on real hardware |
| Shuffle 1G–4G | iTunesDB + iTunesSD | Clickwheel writes iTunesSD itself (pyPodLib doesn't) |
| Any iPod with Rockbox | file mirror | `/Music/...` + `/Playlists/*.m3u8`; only files Clickwheel copied are ever deleted |
| iPod touch | — | not possible: iOS only accepts music from Finder/iTunes |

Sync is one-way: library ➜ iPod. Songs you delete from the library are removed from the iPod on the
next sync. Songs that were already on the iPod from iTunes are left alone.

**Filesystem:** a Windows-formatted (FAT32) iPod works on every OS. A Mac-formatted (HFS+) iPod
works on macOS and, if journaling is off, on Linux; Windows can't write to it.

## Implementation notes

- `devices/apple.py` patches two pyPodLib 0.1.0 issues at import time: the missing `podcasts`
  subpackage (it would break every sync), and playlist names derived from file names (we read
  `#PLAYLIST:` instead). pyPodLib is pinned to `==0.1.0` for this reason. Re-check both patches before upgrading.
- `devices/itunessd.py` implements both iTunesSD formats (v1 big-endian 558-byte entries for 1G/2G,
  v2 `bdhs` chunks for 3G/4G).

Downloading from YouTube is against YouTube's Terms of Service. This is meant for personal
listening of music you have access to.
