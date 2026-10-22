"""App paths and persisted settings."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir, user_music_dir

APP_NAME = "Clickwheel"

CONFIG_DIR = Path(user_config_dir(APP_NAME, appauthor=False))
DATA_DIR = Path(user_data_dir(APP_NAME, appauthor=False))

HEADERS_FILE = CONFIG_DIR / "ytm_headers.json"
COOKIES_FILE = CONFIG_DIR / "cookies.txt"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
PLAYBACK_FILE = CONFIG_DIR / "playback.json"  # the song you were on, to pick up after a restart
DB_FILE = DATA_DIR / "library.sqlite3"


@dataclass
class Settings:
    library_dir: str = field(default_factory=lambda: str(Path(user_music_dir()) / APP_NAME))
    # Swap official music videos for the album ("Art Track") version when one exists,
    # so the file gets real album metadata and no video intro/outro noise.
    prefer_album_versions: bool = True
    parallel_downloads: int = 2
    cover_size: int = 1000
    # Rockbox devices: mirror files instead of writing the Apple database.
    rockbox_prefers_files: bool = True
    check_for_updates: bool = True
    update_channel: str = ""  # "stable" | "beta"; "" follows the build (beta builds stay on beta)
    show_status_bar: bool = False  # the LCD ticker already shows status messages
    theme: str = "retro"  # "retro" | "y2k" | "bliss" | "aqua" | "halo" | "system"
    last_update_check: float = 0.0
    # Playback equalizer (see equalizer.BANDS for the ten bands).
    eq_enabled: bool = False
    eq_gains: list[float] = field(default_factory=lambda: [0.0] * 10)
    eq_preamp: float = 0.0
    eq_preset: str = "Flat"
    show_equalizer: bool = False

    @classmethod
    def load(cls) -> Settings:
        try:
            data = json.loads(SETTINGS_FILE.read_text())
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2))

    @property
    def library_path(self) -> Path:
        return Path(self.library_dir).expanduser()

    @property
    def playlists_path(self) -> Path:
        return self.library_path / "Playlists"


def write_private(path: Path, text: str) -> None:
    """Write a credentials file readable only by the current user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
