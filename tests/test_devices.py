"""End-to-end sync against pyPodLib virtual iPods (no hardware needed)."""

import struct

import pytest
from pypodlib.device import create_virtual_ipod

from clickwheel.devices import identify
from clickwheel.devices.rockbox import RockboxSync

# One model per database signature scheme, plus both Shuffle formats.
MODELS = {
    "MA146": "5G Video (no hash)",
    "MA978": "Nano 3G (hash58)",
    "MC297": "Classic 7G (hash58)",
    "MC062": "Nano 5G (hash72)",
    "MD477": "Nano 7G (hashAB, SQLite)",
    "M9725": "Shuffle 1G (iTunesSD v1)",
    "MA949": "Shuffle 2G (iTunesSD v1)",
    "MC323": "Shuffle 3G (iTunesSD v2)",
    "MC751": "Shuffle 4G (iTunesSD v2)",
}


def _virtual(tmp_path, model):
    root = tmp_path / "ipod"
    root.mkdir()
    create_virtual_ipod(root, model, ipod_name="Test Pod")
    dev = identify(root)
    assert dev is not None and dev.ipod is not None
    return dev


@pytest.mark.parametrize("model", MODELS, ids=MODELS.values())
def test_apple_sync_roundtrip(library, tmp_path, model):
    dev = _virtual(tmp_path, model)
    backend = dev.backend()

    summary = backend.sync(library.root)
    assert summary.ok, summary.errors
    assert summary.added == 3

    lib = dev.ipod.library(reload=True)
    titles = sorted(t.title for t in lib.tracks)
    assert titles == ["First Song", "Other Single", "Second: Song?"]
    road_trip = lib.get_playlist("Road Trip")
    assert road_trip is not None
    by_id = {t.db_track_id: t.title for t in lib.tracks}
    assert [by_id[i] for i in road_trip.track_ids] == ["Other Single", "First Song"]

    # Nothing changed -> nothing to do.
    again = backend.sync(library.root)
    assert (again.added, again.removed) == (0, 0)

    # Deleting from the library removes it from the iPod.
    library.delete_track("bbbbbbbbbb1")
    after = backend.sync(library.root)
    assert after.ok and after.removed == 1
    assert sorted(t.title for t in dev.ipod.library(reload=True).tracks) == ["First Song", "Second: Song?"]

    if dev.is_shuffle:
        sd = (dev.path / "iPod_Control" / "iTunes" / "iTunesSD").read_bytes()
        if dev.ipod.capabilities.shadow_db_version == 1:
            assert int.from_bytes(sd[:3], "big") == 2
            assert len(sd) == 18 + 2 * 558
            paths = {sd[18 + i * 558 + 33:18 + i * 558 + 555].decode("utf-16-le").rstrip("\0") for i in range(2)}
        else:
            assert sd[:4] == b"bdhs"
            assert struct.unpack_from("<I", sd, 12)[0] == 2
            first = struct.unpack_from("<I", sd, 64 + 20)[0]
            paths = {sd[first + 24:first + 280].rstrip(b"\0").decode()}
        assert all((dev.path / p.lstrip("/")).is_file() for p in paths)


def test_selective_sync_only_copies_selected_playlist(library, tmp_path):
    dev = _virtual(tmp_path, "MC297")
    m3u = library.m3u_path("Road Trip", "PLtest123456")
    allowed = {library.root / t.relpath for t in library.playlist_tracks("PLtest123456")}
    summary = dev.backend().sync(library.root, allowed=allowed, playlists={m3u})
    assert summary.ok, summary.errors
    assert sorted(t.title for t in dev.ipod.library(reload=True).tracks) == ["First Song", "Other Single"]


def test_rockbox_mirror(library, tmp_path):
    mount = tmp_path / "rockbox"
    (mount / ".rockbox").mkdir(parents=True)
    (mount / "Music" / "Mine").mkdir(parents=True)
    (mount / "Music" / "Mine" / "keep.mp3").write_bytes(b"x")
    dev = identify(mount)
    assert dev.firmware == "rockbox"
    backend = dev.backend()
    assert isinstance(backend, RockboxSync)

    summary = backend.sync(library.root)
    assert summary.ok and summary.added == 3 and summary.playlists == 1
    playlist = (mount / "Playlists" / "Road Trip [123456].m3u8").read_text().splitlines()
    assert "/Music/Solo Act/Single/01 Other Single.m4a" in playlist

    library.delete_track("bbbbbbbbbb1")
    summary = backend.sync(library.root)
    assert summary.removed == 1
    assert not (mount / "Music" / "Solo Act").exists()
    assert (mount / "Music" / "Mine" / "keep.mp3").exists()  # never touch the user's own files


@pytest.mark.parametrize("model", ["MC751", "MC297"], ids=["Shuffle 4G", "Classic 7G"])
def test_sync_to_ipod_without_database(library, tmp_path, model):
    """A restored/wiped iPod has iPod_Control but no iTunesDB until first sync."""
    dev = _virtual(tmp_path, model)
    itunes = dev.path / "iPod_Control" / "iTunes"
    for f in itunes.iterdir():
        if f.name.startswith(("iTunesDB", "iTunesCDB", "iTunesSD")):
            f.unlink()
    summary = dev.backend().sync(library.root)
    assert summary.ok, summary.errors
    assert summary.added == 3
    assert len(dev.ipod.library(reload=True).tracks) == 3


def test_browse_apple_and_rockbox(library, tmp_path):
    dev = _virtual(tmp_path, "MC297")
    backend = dev.backend()
    assert backend.browse().tracks == []
    backend.sync(library.root)
    contents = backend.browse()
    assert sorted(t.title for t in contents.tracks) == ["First Song", "Other Single", "Second: Song?"]
    assert all(t.duration >= 4 and t.location.startswith("/iPod_Control/Music/") for t in contents.tracks)
    [road_trip] = contents.playlists
    assert [contents.tracks[i].title for i in road_trip.track_indices] == ["Other Single", "First Song"]

    mount = tmp_path / "rockbox"
    (mount / ".rockbox").mkdir(parents=True)
    rb = identify(mount).backend()
    rb.sync(library.root)
    contents = rb.browse()
    assert sorted(t.album for t in contents.tracks) == ["Debut", "Debut", "Single"]
    assert [p.name for p in contents.playlists] == ["Road Trip"]
    assert [contents.tracks[i].title for i in contents.playlists[0].track_indices] == ["Other Single", "First Song"]


def test_progress_descriptions():
    from types import SimpleNamespace as NS

    from clickwheel.devices.apple import _describe_progress

    track = NS(title="Song", artist="Band")
    ev = lambda legacy, message="": NS(legacy_event=legacy, message=message)  # noqa: E731
    assert _describe_progress(ev(NS(stage="add", current_item=NS(pc_track=track), message=""))) == \
        "Copying songs · Band – Song"
    assert _describe_progress(ev(NS(stage="write_database", current_item=None, message=""))) == "Writing database"
    assert _describe_progress(ev(NS(stage="execute_files", current_item=None, message=""))) == "Working"
    assert _describe_progress(ev(("scan_pc", 1, 2, "01 A.m4a"), "01 A.m4a")) == "Scanning library · 01 A.m4a"
    assert _describe_progress(ev(("diff", 0, 0, "Computing"), "Computing differences")) == "Computing differences"
