import struct

import pytest
from mutagen.mp4 import MP4

from clickwheel.devices import itunessd
from clickwheel.tagger import read_video_id, safe_component
from clickwheel.ytm import _big_cover, parse_url

from .conftest import SONGS


@pytest.mark.parametrize("url, expected", [
    ("https://music.youtube.com/playlist?list=PLabc123", ("playlist", "PLabc123")),
    ("https://www.youtube.com/playlist?list=VLPLabc", ("playlist", "PLabc")),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=PLxyz", ("playlist", "PLxyz")),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVMdQw4w9WgXcQ", ("track", "dQw4w9WgXcQ")),
    ("https://youtu.be/dQw4w9WgXcQ", ("track", "dQw4w9WgXcQ")),
    ("dQw4w9WgXcQ", ("track", "dQw4w9WgXcQ")),
    ("https://music.youtube.com/playlist?list=OLAK5uy_abc", ("album", "OLAK5uy_abc")),
    ("https://music.youtube.com/browse/MPREb_abc", ("album", "MPREb_abc")),
    ("music.youtube.com/watch?v=dQw4w9WgXcQ", ("track", "dQw4w9WgXcQ")),
])
def test_parse_url(url, expected):
    assert parse_url(url) == expected


def test_parse_url_rejects_other_sites():
    with pytest.raises(ValueError):
        parse_url("https://example.com/watch?v=dQw4w9WgXcQ")


def test_big_cover_rewrites_size():
    thumbs = [{"url": "https://lh3.googleusercontent.com/abc=w60-h60-l90-rj", "width": 60},
              {"url": "https://lh3.googleusercontent.com/abc=w544-h544-l90-rj", "width": 544}]
    assert _big_cover(thumbs, 1000).endswith("=w1000-h1000-l90-rj")


def test_safe_component_is_fat32_and_windows_safe():
    assert safe_component('AC/DC: "Live"?') == "AC_DC_ _Live__"
    assert safe_component("CON") == "_CON"
    assert safe_component("trailing. ") == "trailing"


def test_library_files_are_tagged(library):
    tracks = library.tracks()
    assert [t.title for t in tracks] == ["Other Single", "First Song", "Second: Song?"]
    second = next(t for t in tracks if t.video_id == "aaaaaaaaaa2")
    path = library.root / second.relpath
    assert path.name == "02 Second_ Song_.m4a"
    tags = MP4(path).tags
    assert tags["\xa9ART"] == ["The Testers, Guest"]
    assert tags["aART"] == ["The Testers"]
    assert tags["trkn"] == [(2, 3)]
    assert tags["soaa"] == ["Testers"]
    assert tags["covr"]
    assert read_video_id(path) == "aaaaaaaaaa2"


def test_playlist_m3u_uses_relative_paths(library):
    m3u = library.m3u_path("Road Trip", "PLtest123456")
    lines = [line for line in m3u.read_text().splitlines() if not line.startswith("#")]
    assert lines == ["../Solo Act/Single/01 Other Single.m4a", "../The Testers/Debut/01 First Song.m4a"]
    assert all((m3u.parent / line).resolve().exists() for line in lines)


def test_alias_and_delete(library):
    meta = SONGS[0]
    meta2 = type(meta)(**{**meta.__dict__, "source_video_id": "musicvideo1"})
    library.add_track(meta2, library.root / library.track(meta.video_id).relpath)
    assert library.resolve_id("musicvideo1") == meta.video_id
    library.delete_track(meta.video_id)
    assert library.resolve_id("musicvideo1") is None
    assert [t.video_id for t in library.playlist_tracks("PLtest123456")] == [SONGS[2].video_id]


def test_itunessd_v2_layout():
    tracks = [itunessd.SdTrack("/iPod_Control/Music/F00/A.m4a", dbid=7, track_number=3),
              itunessd.SdTrack("/iPod_Control/Music/F01/B.mp3", dbid=8)]
    data = itunessd.build_v2(tracks, [itunessd.SdPlaylist("Mix", [1])])
    magic, _ver, hlen, ntracks, nlists = struct.unpack_from("<4sIIII", data)
    assert (magic, hlen, ntracks, nlists) == (b"bdhs", 64, 2, 2)
    track_off, playlist_off = struct.unpack_from("<II", data, 36)
    assert data[track_off:track_off + 4] == b"hths"
    first = struct.unpack_from("<I", data, track_off + 20)[0]
    assert data[first:first + 4] == b"rths"
    assert struct.unpack_from("<I", data, first + 20)[0] == 2  # AAC
    assert data[first + 24:first + 24 + 29] == b"/iPod_Control/Music/F00/A.m4a"
    assert data[playlist_off:playlist_off + 4] == b"hphs"
    master = struct.unpack_from("<I", data, playlist_off + 20)[0]
    assert struct.unpack_from("<4sIII", data, master)[:3] == (b"lphs", 44 + 8, 2)


def test_itunessd_v1_layout():
    data = itunessd.build_v1([itunessd.SdTrack("/iPod_Control/Music/F00/A.m4a")])
    assert len(data) == 18 + 558
    assert data[:3] == b"\x00\x00\x01"
    entry = data[18:]
    assert entry[:3] == b"\x00\x02\x2e"
    assert entry[33:33 + 58].decode("utf-16-le") == "/iPod_Control/Music/F00/A.m4a"


@pytest.mark.parametrize("raw, clean", [
    ("Daft Punk - Get Lucky (Official Video) ft. Pharrell Williams", "get lucky"),
    ("Instant Crush (feat. Julian Casablancas)", "instant crush"),
    ("Song Name [Official Lyric Video]", "song name"),
    ("Song Name (Live)", "song name live"),  # different recordings must not match
])
def test_clean_title(raw, clean):
    from clickwheel.ytm import _clean_title

    assert _clean_title(raw) == clean


def test_device_syncs_skip_podcasts_and_videos(tmp_path):
    from clickwheel.library import is_music_path

    root = tmp_path / "lib"
    for rel in ("A/B/01 Song.m4a", "Podcasts/Show/2026-10-01 Ep.m4a", "Music Videos/A/Song.mp4",
                "Playlists/x.m3u8", "Podcasts Weekly/Album/01 Real Song.m4a"):
        assert is_music_path(root, root / rel) == (rel.startswith(("A/", "Podcasts Weekly/")))
