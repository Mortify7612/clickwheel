"""Bundled fonts (free licences; each licence ships alongside its files).

Each theme has its own interface font. Where the period font is proprietary
(Tahoma, Lucida Grande) the system copy is used when present, with a bundled
look-alike as the fallback. Fredoka ships as static Regular / SemiBold
instances cut from the variable font, the SemiBold style-linked as bold.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
MONO_FAMILY = "JetBrains Mono"
THEME_FAMILIES = {
    "retro": [MONO_FAMILY],  # all-monospace look, in keeping with the retro hardware skin
    "y2k": ["Fredoka"],
    # XP's Tahoma; Verdana and DejaVu Sans (from Bitstream Vera) are its closest relatives.
    "bliss": ["Tahoma", "Verdana", "DejaVu Sans", "Bitstream Vera Sans"],
    # Mac OS X's Lucida Grande; Go is by Bigelow & Holmes, Lucida's designers.
    "aqua": ["Lucida Grande", "Lucida Sans Unicode", "Go"],
    # Halo's menus use Conduit ITC; Rajdhani is a free, similarly squared-off sci-fi face.
    "halo": ["Rajdhani"],
}
# Faces that read small at the shared point sizes get scaled up a little.
THEME_SCALE = {"halo": 1.18}
_families = [MONO_FAMILY]
_scale = 1.0
_loaded = False


def load_fonts() -> None:
    """Register the bundled fonts with Qt (call once a QGuiApplication exists)."""
    global _loaded
    if _loaded:
        return
    for path in sorted(FONT_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))
    _loaded = True


def use_theme_fonts(theme: str) -> None:
    """Make :func:`ui_font` use ``theme``'s typeface (the system theme keeps the default)."""
    global _families, _scale
    _families = THEME_FAMILIES.get(theme, [MONO_FAMILY])
    _scale = THEME_SCALE.get(theme, 1.0)


def ui_font_key() -> tuple:
    """Changes whenever the theme's typeface or size does (for caching fonts)."""
    return (*_families, _scale)


def ui_font(point_size: float = 9.5, weight: QFont.Weight = QFont.Normal) -> QFont:
    font = QFont()
    font.setFamilies(_families)
    font.setStyleHint(QFont.Monospace if _families[0] == MONO_FAMILY else QFont.SansSerif)
    font.setPointSizeF(point_size * _scale)
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
