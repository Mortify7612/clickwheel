"""Zune HD sync against a simulated MTP device (no hardware or MTPZ keys needed)."""

import hashlib
import os
import struct

import pytest
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA1
from Crypto.PublicKey import RSA
from Crypto.Signature import pss

from clickwheel.devices import mtp, mtpz, zune
from clickwheel.devices.zune import (ALBUM, ALBUM_LINK, ALBUM_NAME, ARTIST, ARTIST_LINK, ARTIST_NAME, FILE_NAME,
                                     FOLDER, FORMAT, NAME, PARENT, PLAYLIST, SAMPLE_DATA)

GENERIC = {FORMAT, PARENT, FILE_NAME}  # the only properties a Zune lets you query across all formats
GROUP_3 = {NAME, ARTIST_NAME, ALBUM_NAME, 0xDC8B, 0xDC8C}


class FakeZune:
    """In-memory stand-in for ``mtp.MtpDevice`` that behaves like a Zune HD where Clickwheel relies on it."""

    def __init__(self):
        self.dev = None
        self.objects: dict[int, dict[int, object]] = {}
        self.data: dict[int, bytes] = {}
        self.refs: dict[int, list[int]] = {}
        self.next_handle = 1000
        self.calls = []
        self.battery = 57
        for name in ("Music", "Artists", "Albums", "Playlists"):
            self._new(FOLDER, 0, {FILE_NAME: name})

    def _new(self, fmt: int, parent: int, props: dict) -> int:
        self.next_handle += 1
        self.objects[self.next_handle] = {FORMAT: fmt, PARENT: parent, **props}
        return self.next_handle

    def root(self, name: str) -> int:
        return next(h for h, p in self.objects.items() if p[PARENT] == 0 and p.get(FILE_NAME) == name)

    # The parts of MtpDevice the backend uses.
    def open(self):
        pass

    def close(self):
        pass

    def storage_ids(self):
        return [0x10001]

    def get_device_prop(self, code, type_):
        return {zune.BATTERY_LEVEL: self.battery, zune.FRIENDLY_NAME: "Test Zune"}[code]

    def storage_space(self, storage):
        used = sum(len(d) for d in self.data.values())
        return 10**9 - used, 10**9

    def object_handles(self, storage=0xFFFFFFFF, fmt=0, parent=0):
        return list(self.objects)

    def prop_list(self, handle=0xFFFFFFFF, code=0xFFFFFFFF, fmt=0, depth=0, group=0):
        self.calls.append(("prop_list", handle, code, fmt, group))
        if handle == 0xFFFFFFFF:
            if fmt == 0 and code not in GENERIC:
                raise mtp.MtpError("unsupported", 0xA801)
            handles = [h for h, p in self.objects.items() if fmt == 0 or p[FORMAT] == fmt]
        else:
            handles = [handle]
        codes = None if code == 0xFFFFFFFF else ({c for c in GROUP_3} if code == 0 and group == 3 else {code})
        out = []
        for h in handles:
            for c, v in self._props(h).items():
                if codes is None or c in codes:
                    out.append(mtp.Prop(h, c, mtp.STR if isinstance(v, str) else mtp.UINT32, v))
        return out

    def _props(self, handle: int) -> dict:
        props = dict(self.objects[handle])
        if props[FORMAT] in zune.AUDIO and props.get(ALBUM_LINK) in self.objects:  # derived by the Zune
            props[ALBUM_NAME] = self.objects[props[ALBUM_LINK]].get(NAME, "")
        return props

    def get_prop(self, handle, code, type_):
        if code == SAMPLE_DATA:
            return self.objects[handle].get(SAMPLE_DATA, b"")
        return self._props(handle).get(code, 0)

    def set_prop(self, handle, code, type_, value):
        self.objects[handle][code] = value

    def send_object(self, storage, parent, fmt, props, data=b"", progress=None, send_data=True):
        handle = self._new(fmt, parent, {code: value for code, _, value in props})
        self.data[handle] = data
        return handle

    def delete(self, handle):
        del self.objects[handle]
        self.data.pop(handle, None)
        for refs in self.refs.values():  # the Zune drops deleted tracks from albums and playlists
            if handle in refs:
                refs.remove(handle)

    def references(self, handle):
        return list(self.refs.get(handle, []))

    def set_references(self, handle, refs):
        self.refs[handle] = list(refs)
        if self.objects[handle][FORMAT] == ALBUM:
            for track in refs:
                self.objects[track][ALBUM_LINK] = handle

    # Helpers for the tests
    def path(self, handle: int) -> str:
        parts = []
        while handle:
            parts.append(self.objects[handle].get(FILE_NAME, ""))
            handle = self.objects[handle][PARENT]
        return "/" + "/".join(reversed(parts))

    def of_format(self, fmt: int) -> dict[int, dict]:
        return {h: p for h, p in self.objects.items() if p[FORMAT] == fmt}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    device = FakeZune()
    monkeypatch.setattr(zune, "MANIFEST_DIR", tmp_path / "zune-data")
    monkeypatch.setattr(zune.mtp.MtpDevice, "find", classmethod(lambda cls, v, p: device))
    monkeypatch.setattr(zune, "_usb_serial", lambda dev: "TESTSERIAL")
    monkeypatch.setattr(zune.mtpz, "load_keys", lambda path=None: object())
    monkeypatch.setattr(zune.mtpz, "handshake", lambda dev, keys: None)
    return device


def backend():
    return zune.ZuneSync(zune.ZuneInfo(serial="TESTSERIAL"))


# ── MTP encoding ───────────────────────────────────────────────────────────────

def test_mtp_values_roundtrip():
    for type_, value in [(mtp.STR, "Sigur Rós ✓"), (mtp.STR, ""), (mtp.UINT16, 0xB215), (mtp.UINT32, 123456789),
                         (mtp.UINT64, 2**40), (mtp.UINT128, 2**100), (mtp.AUINT8, b"\x01\x02\xff"),
                         (mtp.AUINT16, [1, 2, 65535])]:
        data = mtp.pack_value(type_, value)
        assert mtp.unpack_value(type_, data + b"tail") == (value, len(data))
    packed = mtp.pack_prop_list([(NAME, mtp.STR, "Joji"), (ARTIST_LINK, mtp.UINT32, 7)])
    # SendObjectPropList's dataset has handle 0 for the object being created.
    assert mtp.unpack_prop_list(packed) == [mtp.Prop(0, NAME, mtp.STR, "Joji"), mtp.Prop(0, ARTIST_LINK, mtp.UINT32, 7)]


# ── MTPZ crypto, checked against standard RSA-PSS / RSA-OAEP with a throwaway key ──

@pytest.fixture(scope="module")
def rsa_key():
    return RSA.generate(1024, e=65537)


def _keys(rsa_key) -> mtpz.Keys:
    return mtpz.Keys(rsa_key.e, rsa_key.n, rsa_key.d, os.urandom(629))


def test_certificate_message_is_a_valid_pss_signature(rsa_key):
    keys = _keys(rsa_key)
    random = os.urandom(16)
    message = mtpz.certificate_message(keys, random)
    assert message[:7] == b"\x02\x01\x01\x00\x00\x02\x75" and message[7:636] == keys.certificates
    assert message[636:654] == b"\x00\x10" + random and message[654:657] == b"\x01\x00\x80"
    signed = message[2:654]
    pss.new(rsa_key.public_key(), salt_bytes=0).verify(SHA1.new(signed), message[657:])  # raises if wrong


def test_session_hash_unwraps_a_device_reply(rsa_key):
    keys = _keys(rsa_key)
    random, session = os.urandom(16), os.urandom(32)
    aes_key = os.urandom(16)
    # What a Zune sends back: an RSA-OAEP wrapped AES key, then AES-CBC over
    # its certificates, our random, its random, a signature and the session hash.
    wrapped = PKCS1_OAEP.new(rsa_key.public_key(), hashAlgo=SHA1).encrypt(aes_key)
    body = (b"\x01" + struct.pack(">I", 5) + b"certs" + struct.pack(">H", 16) + random
            + struct.pack(">H", 16) + os.urandom(16) + b"\x01" + struct.pack(">H", 128) + os.urandom(128)
            + b"\x01" + struct.pack(">H", 32) + session)
    body += bytes(832 - len(body))
    reply = b"\x02\x02\x00\x80" + wrapped + b"\x00\x00\x03\x40" + AES.new(aes_key, AES.MODE_CBC, bytes(16)).encrypt(body)
    assert mtpz.session_hash(keys, reply, random) == session
    with pytest.raises(mtpz.MtpzError):
        mtpz.session_hash(keys, reply, os.urandom(16))


def test_mgf1_matches_the_standard():
    seed = b"seed"
    expected = hashlib.sha1(seed + b"\0\0\0\0").digest() + hashlib.sha1(seed + b"\0\0\0\1").digest()
    assert mtpz.mgf1(seed, 30) == expected[:30]


def test_missing_key_file(tmp_path):
    assert mtpz.load_keys(tmp_path / "nope") is None
    (tmp_path / "bad").write_text("zz\n")
    assert mtpz.load_keys(tmp_path / "bad") is None


# ── Sync ───────────────────────────────────────────────────────────────────────

def test_sync_files_songs_under_their_artist_and_album(library, fake):
    summary = backend().sync(library.root)
    assert summary.ok and summary.added == 3 and summary.playlists == 1

    tracks = fake.of_format(zune.M4A)
    assert sorted(fake.path(h) for h in tracks) == [
        "/Music/Solo Act/Single/01 Other Single.m4a",
        "/Music/The Testers/Debut/01 First Song.m4a",
        "/Music/The Testers/Debut/02 Second_ Song_.m4a",
    ]
    artists = {p[NAME]: h for h, p in fake.of_format(ARTIST).items()}
    albums = {p[NAME]: h for h, p in fake.of_format(ALBUM).items()}
    assert set(albums) == {"Debut", "Single"}
    for h, p in tracks.items():
        # Each song links to its own artist and to its album, which carries the cover.
        assert fake.objects[p[ARTIST_LINK]][NAME] == p[ARTIST_NAME]
        assert p[ALBUM_LINK] == albums["Single" if "Single" in fake.path(h) else "Debut"]
    assert set(artists) == {"The Testers", "The Testers, Guest", "Solo Act"}
    for h in albums.values():
        assert fake.objects[h][SAMPLE_DATA][:2] == b"\xff\xd8"  # a JPEG
        assert fake.objects[fake.objects[h][ARTIST_LINK]][NAME] == fake.objects[h][ARTIST_NAME]
    assert len(fake.references(albums["Debut"])) == 2

    (playlist,) = fake.of_format(PLAYLIST)
    assert fake.path(playlist) == "/Playlists/Road Trip.pla"
    assert [fake.objects[t][NAME] for t in fake.references(playlist)] == ["Other Single", "First Song"]

    again = backend().sync(library.root)
    assert again.ok and (again.added, again.updated, again.removed) == (0, 0, 0)
    assert len(fake.of_format(zune.M4A)) == 3


def test_mirror_removes_only_its_own_songs_and_cleans_up(library, fake):
    # A song the Zune software put there, with its own artist and album.
    music = fake.root("Music")
    folder = fake._new(FOLDER, fake._new(FOLDER, music, {FILE_NAME: "Keane"}), {FILE_NAME: "Hopes and Fears"})
    keane = fake._new(ARTIST, fake.root("Artists"), {FILE_NAME: "Keane.art", NAME: "Keane"})
    theirs = fake._new(zune.MP3, folder, {FILE_NAME: "01 Somewhere.mp3", NAME: "Somewhere", ARTIST_NAME: "Keane",
                                          ARTIST_LINK: keane})
    fake.set_references(fake._new(ALBUM, fake.root("Albums"), {NAME: "Hopes and Fears", ARTIST_NAME: "Keane",
                                                                 ARTIST_LINK: keane}), [theirs])
    backend().sync(library.root)

    debut = {library.root / t.relpath for t in library.tracks() if t.album == "Debut"}
    summary = backend().sync(library.root, allowed=debut, playlists=set())
    assert summary.ok and summary.removed == 1 and summary.playlists == 0

    paths = {fake.path(h) for h in fake.objects}
    assert "/Music/Solo Act/Single/01 Other Single.m4a" not in paths
    assert not any("Solo Act" in p or "Single" in p for p in paths)  # its album, artist and folders went too
    assert "/Playlists/Road Trip.pla" not in paths
    assert "/Music/Keane/Hopes and Fears/01 Somewhere.mp3" in paths and keane in fake.objects


def test_add_selected_songs_keeps_everything_else(library, fake):
    backend().sync(library.root)
    single = {library.root / t.relpath for t in library.tracks() if t.album == "Single"}
    summary = backend().add_tracks(library.root, single)
    assert summary.ok and summary.added == 0
    assert len(fake.of_format(zune.M4A)) == 3


def test_browse_delete_and_reorder(library, fake):
    sync = backend()
    sync.sync(library.root)
    contents = sync.browse()
    assert sorted((t.title, t.artist, t.album) for t in contents.tracks) == [
        ("First Song", "The Testers", "Debut"),
        ("Other Single", "Solo Act", "Single"),
        ("Second: Song?", "The Testers, Guest", "Debut"),
    ]
    assert all(t.artwork is not None and t.artwork.load_png()[:2] == b"\xff\xd8" for t in contents.tracks)
    assert all(t.duration > 0 for t in contents.tracks)
    (road_trip,) = contents.playlists
    assert road_trip.name == "Road Trip" and road_trip.id == "/Playlists/Road Trip.pla"

    order = [contents.tracks[i].location for i in reversed(road_trip.track_indices)]
    sync.reorder(road_trip.id, order)
    assert [contents.tracks[i].title for i in sync.browse().playlists[0].track_indices] == [
        "First Song", "Other Single"]
    with pytest.raises(RuntimeError):
        sync.reorder(None, order)

    first = next(t.location for t in contents.tracks if t.title == "First Song")
    assert sync.delete_tracks({first}) == 1
    after = sync.browse()
    assert [t.title for t in after.tracks if t.album == "Debut"] == ["Second: Song?"]
    assert [after.tracks[i].title for i in after.playlists[0].track_indices] == ["Other Single"]
    # Deleting it also forgets it, so the next mirror sync puts it back.
    assert backend().sync(library.root).added == 1


def test_object_cache_avoids_rereading_the_zune(library, fake):
    backend().sync(library.root)
    with zune.Zune.connect() as first:
        known = dict(first.objects)
    fake.calls.clear()
    with zune.Zune.connect() as second:
        assert second.objects == known
    assert not [c for c in fake.calls if c[0] == "prop_list"]  # nothing new: no metadata reads at all

    # An object added behind Clickwheel's back is read on its own.
    fake._new(FOLDER, fake.root("Music"), {FILE_NAME: "New"})
    fake.calls.clear()
    with zune.Zune.connect() as third:
        assert third.find("/Music/New") is not None
    assert [c[1] for c in fake.calls] == [max(fake.objects)]


def test_writing_needs_keys_but_browsing_does_not(library, fake, monkeypatch):
    backend().sync(library.root)
    monkeypatch.setattr(zune.mtpz, "load_keys", lambda path=None: None)
    contents = backend().browse()
    assert len(contents.tracks) == 3 and "MTPZ key file" in contents.notice
    with pytest.raises(mtpz.MtpzError):
        backend().sync(library.root)
    assert not zune.LOCK.locked()


def test_zune_device_entry():
    from pathlib import Path

    from clickwheel.devices import Device

    info = zune.ZuneInfo(serial="X", name="My Zune", free=5, total=10)
    dev = Device(Path("zune:X"), info.name, "Zune HD", "zune", False, zune=info)
    assert dev.label == "My Zune — Zune HD" and dev.free_space() == (5, 10) and not dev.read_only
    assert isinstance(dev.backend(), zune.ZuneSync)
    assert dev.eject() == "Safe to unplug"
    info.busy = True
    assert "in use" in dev.label
    with pytest.raises(RuntimeError):
        dev.backend()


def test_battery_and_space_follow_each_session(library, fake):
    sync = backend()
    sync.sync(library.root)
    assert sync.info.battery == 57 and sync.info.name == "Test Zune"
    assert sync.info.free == 10**9 - sum(len(d) for d in fake.data.values()) and sync.info.total == 10**9
    fake.battery = 12
    sync.browse()
    assert sync.info.battery == 12 and sync.info.checked > 0

    info = zune.ZuneInfo(serial="TESTSERIAL")
    fake.battery = 80
    zune.refresh(info)
    assert info.battery == 80 and not zune.LOCK.locked()


def test_battery_label():
    from clickwheel.gui.zune_page import battery_text

    assert battery_text(None) == "—"
    assert battery_text(57) == "57%"
    assert battery_text(9) == "9% — low, charge it soon"
