"""iTunesSD writers for the iPod Shuffle.

Shuffles ignore iTunesDB and play only what iTunesSD lists:

* Shuffle 1G/2G read a big-endian table of fixed 558-byte entries
  (format documented on the iPodLinux wiki / implemented in libgpod).
* Shuffle 3G/4G read the little-endian "bdhs" format with track ("rths")
  and playlist ("lphs") chunks.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

FILETYPE = {".mp3": 1, ".m4a": 2, ".m4b": 2, ".aac": 2, ".wav": 4}


@dataclass
class SdTrack:
    location: str  # iPod path, e.g. "/iPod_Control/Music/F00/ABCD.m4a"
    dbid: int = 0
    track_number: int = 0
    disc_number: int = 0
    album_id: int = 0
    artist_id: int = 0
    start_ms: int = 0
    stop_ms: int = 0
    volume: int = 0  # -100..100
    remember_position: bool = False
    skip_when_shuffling: bool = False

    @property
    def filetype(self) -> int:
        return FILETYPE.get(Path(self.location).suffix.lower(), 1)


@dataclass
class SdPlaylist:
    name: str
    track_indices: list[int]
    dbid: int = 0


def _u24be(value: int) -> bytes:
    return (value & 0xFFFFFF).to_bytes(3, "big")


def build_v1(tracks: list[SdTrack]) -> bytes:
    """Shuffle 1G/2G (no playlist support; the device plays the master list)."""
    out = bytearray()
    out += _u24be(len(tracks)) + _u24be(0x010800) + _u24be(0x12) + bytes(9)
    for t in tracks:
        name = t.location.encode("utf-16-le")[:522].ljust(522, b"\0")
        out += b"".join([
            _u24be(0x22E), _u24be(0x5AA501),
            _u24be(t.start_ms // 256), _u24be(0), _u24be(0),
            _u24be(t.stop_ms // 256), _u24be(0), _u24be(0),
            _u24be(t.volume + 0x64), _u24be(t.filetype), _u24be(0x200),
            name,
            bytes([0 if t.skip_when_shuffling else 1, 1 if t.remember_position else 0, 0]),
        ])
    return bytes(out)


def build_v2(tracks: list[SdTrack], playlists: list[SdPlaylist]) -> bytes:
    """Shuffle 3G/4G. A master playlist (all tracks) is always written first."""
    master = SdPlaylist("", list(range(len(tracks))))
    lists = [master, *[p for p in playlists if p.track_indices]]

    track_chunks = []
    for t in tracks:
        name = t.location.encode("utf-8")[:255].ljust(256, b"\0")
        chunk = (
            b"rths" + struct.pack("<IIIiI", 0x174, t.start_ms, t.stop_ms, t.volume, t.filetype) + name
            + struct.pack("<IBBBB", 0, 0 if t.skip_when_shuffling else 1, int(t.remember_position), 0, 0)
            + struct.pack("<IIIIIII", 0x200, 0, 0, 0, 0, 0, t.album_id)
            + struct.pack("<HH", t.track_number, t.disc_number) + bytes(8)
            + struct.pack("<QI", t.dbid, t.artist_id) + bytes(32)
        )
        assert len(chunk) == 0x174
        track_chunks.append(chunk)

    playlist_chunks = []
    for i, p in enumerate(lists):
        body = b"".join(struct.pack("<I", idx) for idx in p.track_indices)
        playlist_chunks.append(
            b"lphs" + struct.pack("<IIIQI", 44 + len(body), len(p.track_indices), len(p.track_indices),
                                  p.dbid or (i + 1), 1 if i == 0 else 2) + bytes(16) + body
        )

    header_len = 64
    hths_len = 20 + 4 * len(track_chunks)
    tracks_start = header_len + hths_len
    offsets, pos = [], tracks_start
    for c in track_chunks:
        offsets.append(pos)
        pos += len(c)
    hths = b"hths" + struct.pack("<II", hths_len, len(track_chunks)) + bytes(8) \
        + b"".join(struct.pack("<I", o) for o in offsets)

    hphs_start = pos
    hphs_len = 20 + 4 * len(playlist_chunks)
    p_offsets, ppos = [], hphs_start + hphs_len
    for c in playlist_chunks:
        p_offsets.append(ppos)
        ppos += len(c)
    n = len(playlist_chunks)
    hphs = b"hphs" + struct.pack("<II", hphs_len, n) + struct.pack("<HHHH", n, 1, n, 0) \
        + b"".join(struct.pack("<I", o) for o in p_offsets)

    header = b"bdhs" + struct.pack("<IIII", 0x02000003, header_len, len(tracks), n) + bytes(8) \
        + bytes([0, 0]) + bytes(2) + struct.pack("<III", len(tracks), header_len, hphs_start) + bytes(20)
    assert len(header) == header_len
    return header + hths + b"".join(track_chunks) + hphs + b"".join(playlist_chunks)


def write(ipod_root: Path, version: int, tracks: list[SdTrack], playlists: list[SdPlaylist]) -> Path:
    itunes = ipod_root / "iPod_Control" / "iTunes"
    itunes.mkdir(parents=True, exist_ok=True)
    data = build_v1(tracks) if version == 1 else build_v2(tracks, playlists)
    target = itunes / "iTunesSD"
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
    # The shuffle order / resume state index into the old track table; the
    # firmware rebuilds them on next boot.
    for stale in ("iTunesShuffle", "iTunesPState"):
        (itunes / stale).unlink(missing_ok=True)
    return target
