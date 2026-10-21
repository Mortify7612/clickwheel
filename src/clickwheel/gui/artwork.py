"""Album art for the song tables: background loading, caching, placeholders."""

from __future__ import annotations

import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

THUMB = 40
LARGE = 240


def embedded_art(path: Path) -> bytes | None:
    """The first embedded cover image of an MP4/MP3/FLAC/Ogg file."""
    import mutagen

    try:
        audio = mutagen.File(path)
    except Exception:
        return None
    if audio is None:
        return None
    tags = audio.tags
    if tags is not None:
        if "covr" in tags and tags["covr"]:  # MP4
            return bytes(tags["covr"][0])
        for key in tags.keys():  # ID3 "APIC:..." frames
            if str(key).startswith("APIC"):
                return tags[key].data
    pictures = getattr(audio, "pictures", None)  # FLAC
    return pictures[0].data if pictures else None


def _rounded(image: QImage, size: int, radius: float) -> QPixmap:
    """Scale/crop to a square and round the corners."""
    scaled = image.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(clip)
    p.drawImage(QPointF((size - scaled.width()) / 2, (size - scaled.height()) / 2), scaled)
    p.end()
    return out


def placeholder(key: str, size: int) -> QPixmap:
    """A two-tone tile coloured from the album name, with a note glyph."""
    hue = zlib.crc32(key.encode()) % 360
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor.fromHsv(hue, 120, 210))
    grad.setColorAt(1, QColor.fromHsv((hue + 40) % 360, 170, 130))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.12, size * 0.12)
    p.fillPath(path, grad)
    font = QFont()
    font.setPixelSize(int(size * 0.5))
    p.setFont(font)
    p.setPen(QColor(255, 255, 255, 200))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "♪")
    p.end()
    return QPixmap.fromImage(img)


class CoverCache(QObject):
    """Loads covers off the GUI thread, one decode per album.

    ``loaded`` fires with the album key once its thumbnail and large image are
    ready; callers then ask for them with :meth:`thumb` / :meth:`large`.
    """

    loaded = Signal(str)
    _decoded = Signal(str, object)  # worker -> GUI thread hand-off (QImage or None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="covers")
        self._thumbs: dict[str, QPixmap] = {}
        self._large: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._missing: set[str] = set()  # no art found last time; worth retrying later
        self._decoded.connect(self._store)

    def request(self, key: str, source) -> None:
        """``source`` is an audio file path, or anything with ``load_png()``
        (an iPod ArtworkDB reference)."""
        if key in self._pending or (key in self._thumbs and key not in self._missing):
            return
        self._missing.discard(key)
        self._pending.add(key)
        self._pool.submit(self._load, key, source)

    def _load(self, key: str, source) -> None:
        try:
            data = source.load_png() if hasattr(source, "load_png") else embedded_art(Path(source))
        except Exception:
            data = None
        image = QImage()
        # QImage (unlike QPixmap) is safe to build off the GUI thread.
        if data and image.loadFromData(data):
            image = image.scaled(LARGE * 2, LARGE * 2, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        else:
            image = None
        self._decoded.emit(key, image)

    def _store(self, key: str, image) -> None:
        self._pending.discard(key)
        if image is None:
            self._thumbs[key] = placeholder(key, THUMB)
            self._large[key] = placeholder(key, LARGE)
            self._missing.add(key)  # the file may gain art later (re-download, retag)
        else:
            self._thumbs[key] = _rounded(image, THUMB, 5)
            self._large[key] = _rounded(image, LARGE, 14)
        self.loaded.emit(key)

    def thumb(self, key: str) -> QPixmap:
        return self._thumbs.get(key) or placeholder(key, THUMB)

    def large(self, key: str) -> QPixmap:
        return self._large.get(key) or placeholder(key, LARGE)

    def has(self, key: str) -> bool:
        return key in self._thumbs

    def clear(self) -> None:
        self._thumbs.clear()
        self._large.clear()
        self._missing.clear()


class RemoteArt:
    """A cover on the web, for :meth:`CoverCache.request` (fetched on its worker threads)."""

    def __init__(self, url: str):
        self.url = url

    def load_png(self) -> bytes | None:
        import requests

        if not self.url:
            return None
        response = requests.get(self.url, timeout=20)
        response.raise_for_status()
        return response.content


def album_key(album_artist: str, album: str) -> str:
    return f"{album_artist.casefold()}\x1f{album.casefold()}"


class ArtPanel(QWidget):
    """Large cover plus title / artist / album for the selected song.

    The cover shrinks to whatever room is left above the caption, so the two
    never overlap in short panels (like the iPod tab).
    """

    def __init__(self, cache: CoverCache, parent=None):
        super().__init__(parent)
        self.cache = cache
        self._key: str | None = None
        self._pixmap = placeholder("", LARGE)
        self.cover = QLabel()
        self.cover.setAlignment(Qt.AlignCenter)
        self.title = QLabel()
        font = QFont()  # size and weight only, so the family follows the theme
        font.setPointSizeF(11.5)
        font.setBold(True)
        self.title.setFont(font)
        self.artist = QLabel()
        self.album = QLabel()
        self.album.setStyleSheet("color: palette(placeholder-text);")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.cover, 0, Qt.AlignHCenter)
        layout.addSpacing(8)
        for label in (self.title, self.artist, self.album):
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            layout.addWidget(label)
        self.footer = QVBoxLayout()  # room for a page's own extras under the caption
        layout.addSpacing(6)
        layout.addLayout(self.footer)
        layout.addStretch(1)
        self.setFixedWidth(LARGE + 8)
        self.setMinimumHeight(120)
        cache.loaded.connect(self._on_loaded)
        self.show_track(None)

    def show_track(self, key: str | None, title: str = "", artist: str = "", album: str = "",
                   path=None) -> None:
        self._key = key
        self.title.setText(title or ("" if key else "Nothing selected"))
        self.artist.setText(artist)
        self.album.setText(album)
        self.artist.setVisible(bool(artist))
        self.album.setVisible(bool(album))
        if key is None:
            self._set_pixmap(placeholder("", LARGE))
            return
        if path is not None:
            self.cache.request(key, path)
        self._set_pixmap(self.cache.large(key))

    def _on_loaded(self, key: str) -> None:
        if key == self._key:
            self._set_pixmap(self.cache.large(key))

    def _set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._fit_cover()

    def _fit_cover(self) -> None:
        width = self.width() - 8
        extras = [self.footer.itemAt(i).widget() for i in range(self.footer.count())]
        caption = sum(w.sizeHint().height() for w in (self.title, self.artist, self.album, *extras)
                      if w is not None and not w.isHidden()) + 30
        side = max(48, min(LARGE, width, self.height() - caption))
        self.cover.setFixedSize(side, side)
        self.cover.setPixmap(self._pixmap if side == self._pixmap.width()
                             else self._pixmap.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_cover()
