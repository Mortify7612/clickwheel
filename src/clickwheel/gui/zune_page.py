"""Zune tab (Linux): the Zune HD's own page, on top of the iPod tab's sync machinery."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton

from ..config import Settings
from ..devices import Device, scan_zune
from ..library import Library
from ..podcasts import Podcasts
from ..video import MusicVideos
from . import workers
from .device_page import DevicePage, _gb


LOW = 15  # percent


def battery_text(level: int | None) -> str:
    if level is None:
        return "—"
    return f"{level}% — low, charge it soon" if level <= LOW else f"{level}%"


class ZunePage(DevicePage):
    present = Signal(bool)  # a Zune is plugged in (or was unplugged)
    podcasts_changed = Signal()  # a sync brought back where episodes were left on the Zune

    def __init__(self, library: Library, settings: Settings, podcasts: Podcasts, videos: MusicVideos):
        self.release_btn = None  # the base class shows the (empty) device before these exist
        self.battery = None
        self._present = False
        self.podcasts = podcasts
        self.videos = videos
        super().__init__(library, settings, noun="Zune")
        self.manual_btn.hide()  # an MTP player has no folder to point at
        self.eject_btn.hide()  # ...and nothing to flush: it's safe to unplug when idle
        self.battery = QLabel("—")
        self.info_form.insertRow(3, "Battery", self.battery)  # after Model, Firmware, Storage
        self.release_btn = QPushButton("Release it")
        self.release_btn.setToolTip("Ask KDE's file service to let go of the Zune; it restarts by itself when needed")
        self.release_btn.clicked.connect(self._release)
        self.release_btn.hide()
        self.info_form.addRow(self.release_btn)
        self.videos_box = QCheckBox("Music videos (for the songs synced)")
        self.videos_box.setToolTip("Get them on the Library tab: select songs, right-click, “Get music videos”")
        self.podcasts_box = QCheckBox("Podcasts (downloaded episodes)")
        self.videos_box.setChecked(settings.zune_sync_videos)
        self.podcasts_box.setChecked(settings.zune_sync_podcasts)
        for box, key in ((self.videos_box, "zune_sync_videos"), (self.podcasts_box, "zune_sync_podcasts")):
            box.toggled.connect(lambda on, key=key: (setattr(settings, key, on), settings.save()))
            self.what_layout.insertWidget(self.what_layout.count() - 1, box)  # above the note

    def _scan(self) -> list[Device]:
        dev = scan_zune()
        return [dev] if dev else []

    def _poll(self) -> None:
        # Unlike the iPod tab, keep watching while hidden: the Library tab's
        # "Sync selected to Zune" button follows whether one is plugged in.
        if not self._syncing and not self._editing:
            self.rescan()

    def _no_device_text(self) -> str:
        return "No Zune HD found — plug one in"

    def _set_devices(self, devices: list[Device], keep=None) -> None:
        super()._set_devices(devices, keep)
        if bool(self.devices) != self._present:
            self._present = bool(self.devices)
            self.present.emit(self._present)
        if self.current is not None and not self._syncing:
            self._show_device()  # battery and free space change while the device list doesn't

    def _show_device(self) -> None:
        super()._show_device()
        if self.release_btn is not None and self.current is None:
            self.release_btn.hide()
            self.battery.setText("—")

    def _describe(self, dev: Device) -> str:
        info = dev.zune
        self.firmware.setText("Zune HD (MTP)")
        self.space.setText(f"{_gb(info.free)} free of {_gb(info.total)}" if info.total else "—")
        if self.release_btn is not None:
            self.release_btn.setVisible(info.busy)
            self.battery.setText(battery_text(info.battery))
            self.battery.setStyleSheet("color: #c0392b;" if info.battery is not None and info.battery <= LOW else "")
        if info.busy:
            return ("Another program has the Zune open — on KDE that's its file service, which grabs MTP players "
                    "when they're plugged in.")
        if not info.has_keys:
            from ..devices.mtpz import KEY_FILE

            return f"Clickwheel can show what's on the Zune, but changing it needs the MTPZ key file at {KEY_FILE}."
        return ""

    def _release(self) -> None:
        from ..devices.zune import release_from_kde

        def done(ok: bool) -> None:
            self._log("Asked KDE's file service to release the Zune" if ok
                      else "Couldn't reach KDE's file service; close any file manager window showing the Zune")
            QTimer.singleShot(1500, self.rescan)

        self.release_btn.setEnabled(False)
        QTimer.singleShot(3000, lambda: self.release_btn.setEnabled(True))
        workers.run(release_from_kde, on_done=done, on_error=lambda m: self._log(f"Release failed: {m}"))

    # ── Videos and podcasts ──────────────────────────────────────────────

    def _sync_extras(self, allowed: set[Path] | None) -> dict:
        from ..devices.zune import EpisodeItem, VideoItem
        from ..video import video_duration_ms

        extras: dict = {}
        if self.videos_box.isChecked():
            tracks = {t.video_id: t for t in self.library.tracks()}
            items = []
            for video in self.videos.all():
                track = tracks.get(video.track_id)
                if track is None or (allowed is not None and self.library.root / track.relpath not in allowed):
                    continue
                path, thumb = self.videos.path(video), self.videos.thumb_path(video)
                items.append(VideoItem(video.track_id, path, track.title, track.artist,
                                       video_duration_ms(path) or track.duration * 1000,
                                       thumb.read_bytes() if thumb.exists() else None))
            extras["videos"] = items
        if self.podcasts_box.isChecked():
            shows = {p.id: p for p in self.podcasts.podcasts()}
            items = []
            for e in self.podcasts.episodes(downloaded=True):
                show, path = shows.get(e.podcast_id), self.podcasts.path(e)
                if show is None or not path.exists():
                    continue
                feed = show.source if show.kind == "rss" else f"https://music.youtube.com/playlist?list={show.source}"
                items.append(EpisodeItem(e.id, path, show.title, e.title, author=show.author, feed_url=feed,
                                         cover=self.podcasts.cover(show), description=e.description,
                                         published=e.published, duration_ms=e.duration * 1000,
                                         position_ms=e.position, played=e.played))
            extras["episodes"] = items
            extras["on_episode_state"] = self._episode_state
        return extras

    def _episode_state(self, key: str, position: int, finished: bool) -> None:
        """Called from the sync thread: where an episode was left on the Zune."""
        if finished:
            self.podcasts.set_played(key)
        else:
            self.podcasts.set_position(key, position)

    def _on_synced(self, summary) -> None:
        super()._on_synced(summary)
        self.podcasts_changed.emit()
