"""Bundled fonts (SIL Open Font License; licences ship alongside the files)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
MONO_FAMILY = "JetBrains Mono"
UI_FAMILY = MONO_FAMILY  # all-monospace look, in keeping with the retro hardware skin
_loaded = False


def load_fonts() -> None:
    """Register the bundled fonts with Qt (call once a QGuiApplication exists)."""
    global _loaded
    if _loaded:
        return
    for path in sorted(FONT_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))
    _loaded = True


def ui_font(point_size: float = 9.5, weight: QFont.Weight = QFont.Normal) -> QFont:
    font = QFont(UI_FAMILY)
    font.setStyleHint(QFont.Monospace)
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    return font


def mono_font(point_size: float = 9.5, weight: QFont.Weight = QFont.Normal) -> QFont:
    font = QFont(MONO_FAMILY)
    font.setStyleHint(QFont.Monospace)
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    return font


def label_font(point_size: float = 7.5) -> QFont:
    """Small spaced-out caps, for table headers and panel labels."""
    font = ui_font(point_size, QFont.Bold)
    font.setCapitalization(QFont.AllUppercase)
    font.setLetterSpacing(QFont.PercentageSpacing, 106)
    return font
