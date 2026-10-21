"""Read-only view of what is already on a device."""

from __future__ import annotations

import io
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArtworkRef:
    """One cover image inside an Apple-firmware iPod's .ithmb files."""

    path: str
    offset: int
    size: int
    width: int
    height: int
    format_id: int
    hpad: int = 0
    vpad: int = 0

    def load_png(self) -> bytes | None:
        from pypodlib.artworkdb_writer.ithmb_codecs import decode_pixels_for_format

        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                pixels = fh.read(self.size)
            image = decode_pixels_for_format(self.format_id, pixels, self.width, self.height, self.hpad, self.vpad)
        except Exception:
            return None
        if image is None:
            return None
        out = io.BytesIO()
        image.save(out, "PNG")
        return out.getvalue()


@dataclass
class DeviceTrack:
    title: str
    artist: str
    album: str
    track_number: int = 0
    duration: int = 0  # seconds
    play_count: int = 0
    location: str = ""
    # Apple firmware keeps art in ArtworkDB (pyPodLib strips it from the copied
    # files); Rockbox reads art embedded in the file at ``location``.
    artwork: ArtworkRef | None = None
    kind: str = "song"  # "song" | "video" | "episode" (a Zune also holds music videos and podcasts)


@dataclass
class DevicePlaylist:
    name: str
    track_indices: list[int] = field(default_factory=list)
    id: str = ""  # backend-specific: Apple playlist id, Rockbox .m3u8 file name
    fixed: bool = False  # a list the device keeps in its own order (a Zune's videos, a podcast show)


@dataclass
class DeviceContents:
    # Device order: on a Shuffle this is the play order when shuffle is off.
    tracks: list[DeviceTrack]
    playlists: list[DevicePlaylist]
    # Whether the order of the full song list means anything on this device
    # (Shuffle play order); other iPods always list songs alphabetically.
    ordered_library: bool = False
    notice: str = ""  # something the browser fixed while reading, worth telling the user
