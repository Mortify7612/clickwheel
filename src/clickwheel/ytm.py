"""YouTube Music browsing and metadata resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from ytmusicapi import YTMusic

ALBUM_VIDEO_TYPE = "MUSIC_VIDEO_TYPE_ATV"


@dataclass
class TrackMeta:
    video_id: str
    title: str
    artists: list[str]
    album: str = ""
    album_artist: str = ""
    album_id: str = ""
    track_number: int = 0
    track_total: int = 0
    disc_number: int = 1
    year: str = ""
    duration: int = 0
    explicit: bool = False
    cover_url: str = ""
    # The ID the user originally picked (e.g. a music video) if we swapped it.
    source_video_id: str = ""

    @property
    def artist(self) -> str:
        return ", ".join(self.artists) or "Unknown Artist"


@dataclass
class PlaylistRef:
    playlist_id: str
    title: str
    count: int | None = None
    thumbnail: str = ""


@dataclass
class Collection:
    """A resolved playlist, album, or single track ready to download."""

    id: str
    title: str
    kind: str  # "playlist" | "album" | "track"
    tracks: list[TrackMeta] = field(default_factory=list)
    url: str = ""
    skipped: int = 0  # unavailable / region-locked entries


def _big_cover(thumbnails: list[dict] | None, size: int) -> str:
    if not thumbnails:
        return ""
    url = max(thumbnails, key=lambda t: t.get("width", 0)).get("url", "")
    # Google image URLs take the size as a suffix, e.g. "=w120-h120-l90-rj".
    return re.sub(r"=w\d+-h\d+[^/]*$", f"=w{size}-h{size}-l90-rj", url)


def _names(artists: list[dict] | None) -> list[str]:
    return [a["name"] for a in artists or [] if a.get("name")]


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


def parse_url(url: str) -> tuple[str, str]:
    """Classify a YouTube / YouTube Music link.

    Returns (kind, id) with kind in {"playlist", "album", "track"}.
    """
    url = url.strip()
    if re.fullmatch(r"[\w-]{11}", url):
        return "track", url
    parsed = urlparse(url if "://" in url else "https://" + url)
    host = parsed.netloc.lower()
    if not any(h in host for h in ("youtube.com", "youtu.be")):
        raise ValueError("That doesn't look like a YouTube or YouTube Music link.")
    query = parse_qs(parsed.query)
    if parsed.path.startswith("/browse/MPRE"):
        return "album", parsed.path.rsplit("/", 1)[-1]
    playlist = (query.get("list") or [""])[0]
    video = (query.get("v") or [""])[0]
    if "youtu.be" in host:
        video = parsed.path.lstrip("/")
    # Radio/mix lists ("RD...") are generated on the fly and never repeat, so
    # a link from inside one means "this song".
    if playlist and not playlist.startswith("RD"):
        if playlist.startswith("OLAK5uy_"):
            return "album", playlist
        return "playlist", playlist.removeprefix("VL")
    if video:
        return "track", video
    raise ValueError("Couldn't find a playlist, album or song in that link.")


class Resolver:
    """Turns YouTube Music IDs into fully tagged TrackMeta records."""

    def __init__(self, yt: YTMusic, *, cover_size: int = 1000, prefer_album_versions: bool = True):
        self.yt = yt
        self.cover_size = cover_size
        self.prefer_album_versions = prefer_album_versions
        self._albums: dict[str, dict] = {}

    # ── Account ──────────────────────────────────────────────────────────

    def account_name(self) -> str:
        info = self.yt.get_account_info()
        return info.get("accountName") or info.get("channelHandle") or "YouTube Music"

    def library_playlists(self) -> list[PlaylistRef]:
        refs = [PlaylistRef("LM", "Liked Music")]
        for p in self.yt.get_library_playlists(limit=None):
            if p.get("playlistId") == "LM":
                continue
            count = p.get("count")
            refs.append(PlaylistRef(
                p["playlistId"], p.get("title", "Untitled"),
                int(str(count).replace(",", "")) if count and str(count).replace(",", "").isdigit() else None,
                _big_cover(p.get("thumbnails"), 120),
            ))
        return refs

    # ── Collections ──────────────────────────────────────────────────────

    def resolve_url(self, url: str) -> Collection:
        kind, ident = parse_url(url)
        if kind == "album":
            return self.album_collection(ident, url=url)
        if kind == "playlist":
            return self.playlist_collection(ident, url=url)
        track = self.track(ident)
        return Collection(ident, f"{track.artist} - {track.title}", "track", [track], url)

    def playlist_collection(self, playlist_id: str, *, url: str = "") -> Collection:
        data = self.yt.get_playlist(playlist_id, limit=None)
        tracks, skipped = [], 0
        for item in data.get("tracks", []):
            if not item.get("videoId") or item.get("isAvailable") is False:
                skipped += 1
                continue
            tracks.append(self._from_listing(item))
        url = url or f"https://music.youtube.com/playlist?list={playlist_id}"
        return Collection(playlist_id, data.get("title") or playlist_id, "playlist", tracks, url, skipped)

    def album_collection(self, ident: str, *, url: str = "") -> Collection:
        browse_id = ident if ident.startswith("MPRE") else self.yt.get_album_browse_id(ident)
        if not browse_id:
            raise ValueError("Couldn't find that album on YouTube Music.")
        album = self._album(browse_id)
        tracks = [self._from_album(album, browse_id, t) for t in album.get("tracks", []) if t.get("videoId")]
        title = f"{', '.join(_names(album.get('artists')))} - {album.get('title', '')}".strip(" -")
        url = url or f"https://music.youtube.com/browse/{browse_id}"
        return Collection(browse_id, title, "album", tracks, url)

    # ── Tracks ───────────────────────────────────────────────────────────

    def track(self, video_id: str) -> TrackMeta:
        """Resolve a bare video ID via the watch queue (has album + counterpart)."""
        watch = self.yt.get_watch_playlist(video_id, limit=1)
        item = next((t for t in watch.get("tracks", []) if t.get("videoId") == video_id), None)
        if item is None:
            details = self.yt.get_song(video_id).get("videoDetails", {})
            item = {"videoId": video_id, "title": details.get("title", video_id),
                    "artists": [{"name": details.get("author", "")}],
                    "length": details.get("lengthSeconds")}
        return self._from_listing(item)

    def _from_listing(self, item: dict) -> TrackMeta:
        """Build metadata for a playlist / watch-queue entry."""
        if self.prefer_album_versions and item.get("videoType") not in (None, ALBUM_VIDEO_TYPE):
            swapped = self._album_version(item)
            if swapped is not None:
                swapped.source_video_id = item["videoId"]
                return swapped

        album = item.get("album") or {}
        album_id = album.get("id") or ""
        if album_id:
            full = self._album(album_id)
            match = self._find_in_album(full, item)
            if match is not None:
                return self._from_album(full, album_id, match, listing=item)

        return TrackMeta(
            video_id=item["videoId"],
            title=item.get("title", ""),
            artists=_names(item.get("artists")),
            album=album.get("name") or item.get("title", ""),
            album_artist=(_names(item.get("artists")) or [""])[0],
            album_id=album_id,
            year=str(item.get("year") or ""),
            duration=int(item.get("duration_seconds") or _seconds(item.get("length") or item.get("duration"))),
            explicit=bool(item.get("isExplicit")),
            cover_url=_big_cover(item.get("thumbnails") or item.get("thumbnail"), self.cover_size),
        )

    def _from_album(self, album: dict, album_id: str, t: dict, listing: dict | None = None) -> TrackMeta:
        album_tracks = album.get("tracks", [])
        number = t.get("trackNumber") or next(
            (i + 1 for i, a in enumerate(album_tracks) if a.get("videoId") == t.get("videoId")), 0)
        return TrackMeta(
            video_id=(listing or t)["videoId"],
            title=t.get("title") or (listing or {}).get("title", ""),
            artists=_names(t.get("artists")) or _names((listing or {}).get("artists")) or _names(album.get("artists")),
            album=album.get("title", ""),
            album_artist=", ".join(_names(album.get("artists"))),
            album_id=album_id,
            track_number=int(number or 0),
            track_total=int(album.get("trackCount") or len(album_tracks)),
            year=str(album.get("year") or ""),
            duration=int(t.get("duration_seconds") or (listing or {}).get("duration_seconds") or 0),
            explicit=bool(t.get("isExplicit") or album.get("isExplicit")),
            cover_url=_big_cover(album.get("thumbnails"), self.cover_size),
        )

    def _album(self, browse_id: str) -> dict:
        if browse_id not in self._albums:
            self._albums[browse_id] = self.yt.get_album(browse_id)
        return self._albums[browse_id]

    @staticmethod
    def _find_in_album(album: dict, item: dict) -> dict | None:
        tracks = album.get("tracks", [])
        for t in tracks:
            if t.get("videoId") == item.get("videoId"):
                return t
        wanted = _norm(item.get("title", ""))
        return next((t for t in tracks if _norm(t.get("title", "")) == wanted), None)

    def _album_version(self, item: dict) -> TrackMeta | None:
        """Find the album ("Art Track") release of a music video."""
        try:
            watch = self.yt.get_watch_playlist(item["videoId"], limit=1)
        except Exception:
            return None
        head = next((t for t in watch.get("tracks", []) if t.get("videoId") == item["videoId"]), None)
        counterpart = (head or {}).get("counterpart")
        if counterpart and counterpart.get("videoId"):
            counterpart.setdefault("videoType", ALBUM_VIDEO_TYPE)
            if counterpart.get("videoType") == ALBUM_VIDEO_TYPE:
                return self._from_listing(counterpart)
        # Signed-out sessions don't get counterparts; fall back to a strict
        # search so covers and karaoke versions are never substituted.
        match = self._search_album_version(head or item)
        return self._from_listing(match) if match else None

    def _search_album_version(self, item: dict) -> dict | None:
        artists = {_norm(a) for a in _names(item.get("artists"))}
        title = _clean_title(item.get("title", ""))
        length = int(item.get("duration_seconds") or _seconds(item.get("length") or item.get("duration")))
        if not artists or not title:
            return None
        try:
            hits = self.yt.search(f"{next(iter(artists))} {title}", filter="songs", limit=10)
        except Exception:
            return None
        for hit in hits:
            if not hit.get("videoId") or _clean_title(hit.get("title", "")) != title:
                continue
            if not artists & {_norm(a) for a in _names(hit.get("artists"))}:
                continue
            hit_len = int(hit.get("duration_seconds") or 0)
            # Music videos often carry intros/outros, so allow some slack.
            if length and hit_len and abs(hit_len - length) > 30:
                continue
            hit.setdefault("videoType", ALBUM_VIDEO_TYPE)
            return hit
        return None


_VIDEO_NOISE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(official|video|visuali[sz]er|lyrics?|audio|mv|hd|4k|remastered)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_FEATURING = re.compile(r"\s*[\(\[]?\b(feat|ft|featuring)\b\.?.*$", re.IGNORECASE)


def _clean_title(title: str) -> str:
    """Normalise a title for matching: drop "(Official Video)", "feat. X", etc."""
    title = _VIDEO_NOISE.sub("", title)
    title = _FEATURING.sub("", title)
    if " - " in title:  # "Artist - Song" style video titles
        title = title.split(" - ", 1)[1]
    return _norm(title)


def _seconds(text: str | int | None) -> int:
    if not text:
        return 0
    if isinstance(text, int) or str(text).isdigit():
        return int(text)
    total = 0
    for part in str(text).split(":"):
        total = total * 60 + int(part or 0)
    return total
