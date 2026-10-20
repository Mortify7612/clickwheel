"""Read-only view of what is already on a device."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeviceTrack:
    title: str
    artist: str
    album: str
    track_number: int = 0
    duration: int = 0  # seconds
    play_count: int = 0
    location: str = ""


@dataclass
class DevicePlaylist:
    name: str
    track_indices: list[int] = field(default_factory=list)


@dataclass
class DeviceContents:
    tracks: list[DeviceTrack]
    playlists: list[DevicePlaylist]
