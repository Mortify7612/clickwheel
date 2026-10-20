"""App themes: original skins (retro player, Y2K bubblegum, XP Bliss, Aqua G3, Halo), or the system look."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QBrush, QColor, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QStyleFactory

from .fonts import ui_font, use_theme_fonts

THEMES = {"retro": "Retro player", "y2k": "Y2K bubblegum", "bliss": "XP Bliss", "aqua": "Aqua G3", "halo": "Halo", "system": "System"}

# Palette for the retro skin: a classic Winamp-style player (charcoal-blue frame, boxy
# bevelled buttons, gold ribs) around phosphor-green "matrix" song lists.
WINDOW = "#262636"
PANEL = "#2f2f46"
BEVEL_LIGHT = "#6e6e94"
BEVEL_DARK = "#08080f"
LCD_BG = "#000000"
LCD_TEXT = "#00ff00"
LIST_TEXT = "#c4f2d2"  # softer than LCD green so the quieter text tiers can fade from it
LCD_DIM = "#0a6a0a"
SELECT_BG = "#1f3bbd"
SELECT_TEXT = "#ffffff"
ACCENT = "#e8c447"  # the gold of the title-bar ribs
TEXT = "#d8d8e4"
MUTED = "#8888a0"
MONO = '"JetBrains Mono", "DejaVu Sans Mono", "Menlo", "Consolas", monospace'

RAISED = f"border: 1px solid; border-color: {BEVEL_LIGHT} {BEVEL_DARK} {BEVEL_DARK} {BEVEL_LIGHT};"
SUNKEN = f"border: 1px solid; border-color: {BEVEL_DARK} {BEVEL_LIGHT} {BEVEL_LIGHT} {BEVEL_DARK};"
R_BUTTON = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #62627e, stop:0.5 #4a4a64, stop:1 #383850)"
R_BUTTON_HOVER = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #727290, stop:0.5 #565672, stop:1 #42425c)"
R_POSITION = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f6eab8, stop:0.5 #d9c272, stop:1 #a48a3a)"

RETRO_QSS = f"""
QWidget {{ background: {WINDOW}; color: {TEXT}; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QToolTip {{ background: {LCD_BG}; color: {LCD_TEXT}; border: 1px solid {LCD_TEXT}; padding: 3px 5px;
            font-family: {MONO}; }}

QMenuBar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a3a56, stop:1 #24243a);
            border-bottom: 1px solid {BEVEL_DARK}; }}
QMenuBar::item {{ background: transparent; padding: 3px 10px; color: {TEXT}; }}
QMenuBar::item:selected {{ background: {SELECT_BG}; color: {SELECT_TEXT}; }}
QMenu {{ background: {PANEL}; {RAISED} padding: 2px; }}
QMenu::item {{ padding: 4px 22px; }}
QMenu::item:selected {{ background: {SELECT_BG}; color: {SELECT_TEXT}; }}

QTabWidget::pane {{ {RAISED} background: {WINDOW}; top: -1px; }}
QTabBar::tab {{ background: {R_BUTTON}; color: {MUTED}; padding: 5px 16px; margin-right: 2px; {RAISED}
                border-bottom: none; border-top-left-radius: 2px; border-top-right-radius: 2px; font-weight: bold; }}
QTabBar::tab:selected {{ background: {WINDOW}; color: {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}

QGroupBox {{ background: {PANEL}; {RAISED} border-radius: 2px; margin-top: 16px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {ACCENT}; font-weight: bold; }}

QPushButton {{ background: {R_BUTTON}; color: #ececf4; {RAISED} border-radius: 2px; padding: 3px 12px;
               min-height: 18px; }}
QPushButton:hover {{ background: {R_BUTTON_HOVER}; }}
QPushButton:pressed {{ background: #1e1e2e; {SUNKEN} padding: 4px 11px 2px 13px; }}
QPushButton:disabled {{ color: #66667a; background: #2c2c40; border-color: #45455e #14141e #14141e #45455e; }}
QPushButton:default {{ color: {ACCENT}; }}
QPushButton:checked {{ background: #1a1a2a; {SUNKEN} color: {LCD_TEXT}; }}

QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QComboBox {{
    background: {LCD_BG}; color: {LCD_TEXT}; {SUNKEN} border-radius: 1px; padding: 3px 6px;
    selection-background-color: {SELECT_BG}; selection-color: {SELECT_TEXT}; }}
QPlainTextEdit {{ font-family: {MONO}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {LCD_DIM}; }}
QComboBox::drop-down {{ background: {R_BUTTON}; width: 18px; border-left: 1px solid {BEVEL_DARK}; }}
QComboBox QAbstractItemView {{ background: {LCD_BG}; color: {LCD_TEXT}; selection-background-color: {SELECT_BG};
                               {RAISED} padding: 2px; }}

/* Song lists keep the phosphor "matrix" look: soft green on black, rounded glowing bars. */
QTableView, QTableWidget, QListView, QListWidget {{
    background: {LCD_BG}; alternate-background-color: #050a06; color: {LIST_TEXT};
    gridline-color: #10261a; {SUNKEN} border-radius: 10px; padding: 3px;
    selection-background-color: {SELECT_BG}; selection-color: {SELECT_TEXT}; outline: 0; }}
QListView::item, QListWidget::item {{ padding: 6px 10px; margin: 1px 3px; border-radius: 7px; }}
QListView::item:hover, QListWidget::item:hover {{ background: #0e1a12; }}
QListView::item:selected, QListWidget::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3553d6, stop:1 #1a32a8); color: {SELECT_TEXT}; }}
QTableView:disabled, QListView:disabled {{ color: {LCD_DIM}; }}
QTableCornerButton::section {{ background: #20202e; border: 1px solid {BEVEL_DARK}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #24243a, stop:1 #14141f);
                        color: {ACCENT}; border: none; border-bottom: 1px solid #3c3c58;
                        border-right: 1px solid #1a1a28; padding: 0 10px; }}
QHeaderView::section:first {{ border-top-left-radius: 8px; }}
QHeaderView::section:last {{ border-top-right-radius: 8px; border-right: none; }}
QHeaderView::section:hover {{ color: #ffe27a; }}

QProgressBar {{ background: {LCD_BG}; {SUNKEN} border-radius: 1px; color: #f2fff2; text-align: center;
                min-height: 16px; font-family: {MONO}; font-weight: bold; }}
/* Darker LEDs so the white caption stays readable over lit segments. */
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1fa81f, stop:1 #0a5c0a);
                       width: 6px; margin: 2px 1px; }}

QScrollBar:vertical {{ background: #14141f; width: 12px; margin: 0; }}
QScrollBar:horizontal {{ background: #14141f; height: 12px; margin: 0; }}
QScrollBar::handle {{ background: {R_BUTTON}; {RAISED} min-height: 24px; min-width: 24px; margin: 1px; }}
QScrollBar::handle:hover {{ background: {R_BUTTON_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QRadioButton::indicator, QCheckBox::indicator, QAbstractItemView::indicator {{
    width: 11px; height: 11px; background: {LCD_BG}; {SUNKEN} }}
QRadioButton::indicator {{ border-radius: 6px; }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                     stop:0 #b0ffb0, stop:0.45 {LCD_TEXT}, stop:0.55 {LCD_BG}); }}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8aff8a, stop:1 #00a800); }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ background: #101018; }}

/* Winamp's position bar: a dark slot with a wide beige grip; the volume slot runs green to red. */
QSlider:horizontal {{ min-height: 20px; }}  /* room for the grip: overhang is clipped */
QSlider::groove:horizontal {{ background: #0c0c14; {SUNKEN} height: 6px; }}
QSlider::sub-page:horizontal {{ background: #0c0c14; {SUNKEN} height: 6px; }}
QSlider::handle:horizontal {{ background: {R_POSITION}; border: 1px solid #3a2e10; width: 26px; margin: -4px 0;
                              border-radius: 2px; }}
QSlider::handle:horizontal:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fff6d0,
                                                                 stop:0.5 #ead486, stop:1 #b89a48); }}
QSlider#VolumeSlider::groove:horizontal, QSlider#VolumeSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1c9c1c, stop:0.55 #d4cc1c, stop:1 #e0301c); }}
QSlider#VolumeSlider::handle:horizontal {{ width: 12px; }}

QSplitter::handle {{ background: {WINDOW}; }}
QStatusBar {{ background: {LCD_BG}; color: {LCD_TEXT}; font-family: {MONO}; border-top: 1px solid {BEVEL_LIGHT};
              padding: 2px 6px; }}
QStatusBar QLabel {{ color: {LCD_TEXT}; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}

/* Transport: a row of boxy bevelled buttons, as on the classic main window. The extra
   QFrame#PlayerDeck in each selector outranks the shared round deck shapes. */
QFrame#PlayerDeck {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #36364f, stop:1 #222234);
                     {RAISED} border-radius: 2px; }}
QFrame#PlayerDeck QPushButton#DeckButton, QFrame#PlayerDeck QPushButton#PlayButton {{
    background: {R_BUTTON}; {RAISED} border-radius: 2px; color: #d8d8e4; }}
QFrame#PlayerDeck QPushButton#DeckButton:hover, QFrame#PlayerDeck QPushButton#PlayButton:hover {{
    background: {R_BUTTON_HOVER}; }}
QFrame#PlayerDeck QPushButton#DeckButton:pressed, QFrame#PlayerDeck QPushButton#PlayButton:pressed,
QFrame#PlayerDeck QPushButton#DeckButton:checked {{ background: #1a1a2a; {SUNKEN} }}
QFrame#PlayerDeck QPushButton#DeckButton:disabled {{ background: #2c2c40; }}
QFrame#PlayerDeck QPushButton#DeckButton {{ min-width: 32px; max-width: 32px; min-height: 26px; max-height: 26px; }}
QFrame#PlayerDeck QPushButton#PlayButton {{ min-width: 44px; max-width: 44px; min-height: 30px; max-height: 30px;
                                           color: {LCD_TEXT}; }}
"""


# ── Y2K bubblegum: pastel dream gradient, frosted-glass panels, jelly candy gloss ─
# Panels are see-through so the bubbles and sparkles painted behind them show
# (see sparkle.Backdrop). Glass is white at partial opacity with a bright white rim.

Y_TEXT = "#4a2a7a"       # deep plum
Y_MUTED = "#9a86c0"
Y_PINK = "#ff5fb4"
Y_PINK_SOFT = "#ffc2e2"
Y_LILAC = "#a98bff"
Y_SELECT = "#ff6fbf"
Y_GLASS = "rgba(255, 255, 255, 115)"
Y_RIM = "rgba(255, 255, 255, 225)"
# Jelly gloss: a bright top half, a hard edge, then a glowing bottom.
Y_PINK_GEL = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fff0f8, stop:0.44 #ffb3da, stop:0.5 #ff6fbf, stop:1 #ffb0dc)"
Y_LILAC_GEL = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f6f0ff, stop:0.44 #d6c4ff, stop:0.5 #a98bff, stop:1 #d6c8ff)"
Y_JELLY = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255, 255, 255, 240), stop:0.46 rgba(255, 242, 250, 175), "
           "stop:0.52 rgba(255, 214, 236, 150), stop:1 rgba(255, 238, 248, 210))")
Y_JELLY_HOVER = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255, 255, 255, 250), stop:0.46 rgba(255, 228, 243, 210), "
                 "stop:0.52 rgba(255, 190, 225, 200), stop:1 rgba(255, 226, 242, 230))")
Y_CANDY = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff8fcf, stop:0.5 #b79cff, stop:1 #6fc6ff)"
Y_PEARL = ("qradialgradient(cx:0.5, cy:0.5, radius:0.6, fx:0.35, fy:0.28, stop:0 #ffffff, stop:0.3 #ffe6f4, "
           "stop:0.75 #ff9fd4, stop:1 #e86aaf)")

Y2K_QSS = f"""
QMainWindow, QDialog {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffd6ec, stop:0.35 #eadcff,
                                                     stop:0.7 #cfe8ff, stop:1 #d6fbef); }}
QWidget {{ color: {Y_TEXT}; }}
QToolTip {{ background: rgba(255, 255, 255, 235); color: {Y_TEXT}; border: 2px solid {Y_PINK_SOFT};
            border-radius: 12px; padding: 4px 9px; }}

QMenuBar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255, 255, 255, 200),
                                        stop:1 rgba(255, 255, 255, 90));
            border-bottom: 2px solid {Y_RIM}; }}
QMenuBar::item {{ background: transparent; padding: 3px 12px; border-radius: 10px; }}
QMenuBar::item:selected {{ background: {Y_PINK_GEL}; color: #ffffff; }}
QMenu {{ background: rgba(255, 255, 255, 235); border: 2px solid {Y_PINK_SOFT}; border-radius: 14px; padding: 6px; }}
QMenu::item {{ padding: 5px 22px; border-radius: 10px; }}
QMenu::item:selected {{ background: {Y_CANDY}; color: #ffffff; }}

QTabWidget::pane {{ background: rgba(255, 255, 255, 80); border: 2px solid {Y_RIM}; border-radius: 22px; }}
QTabBar::tab {{ background: {Y_JELLY}; color: #7a5aa8; border: 2px solid {Y_RIM}; border-radius: 14px;
                padding: 4px 20px; margin: 3px 3px 6px 3px; font-weight: bold; }}
QTabBar::tab:selected {{ background: {Y_PINK_GEL}; color: #ffffff; border-color: #ffe0f0; }}
QTabBar::tab:hover:!selected {{ background: {Y_JELLY_HOVER}; color: {Y_TEXT}; }}

QGroupBox {{ background: {Y_GLASS}; border: 2px solid {Y_RIM}; border-radius: 20px;
             margin-top: 16px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 4px; color: #e0449a; font-weight: bold; }}

QPushButton {{ background: {Y_JELLY}; color: {Y_TEXT}; border: 2px solid {Y_RIM}; border-radius: 13px;
               padding: 3px 14px; min-height: 18px; font-weight: bold; }}
QPushButton:hover {{ background: {Y_JELLY_HOVER}; border-color: #ffe0f0; }}
QPushButton:pressed, QPushButton:checked {{ background: {Y_PINK_GEL}; color: #ffffff; border-color: #ffe0f0; }}
QPushButton:default {{ background: {Y_LILAC_GEL}; color: #ffffff; border-color: #efe6ff; }}
QPushButton:default:hover {{ background: {Y_PINK_GEL}; }}
QPushButton:disabled {{ color: #c4b6dc; background: rgba(255, 255, 255, 80); border-color: rgba(255, 255, 255, 140); }}

QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QComboBox {{
    background: rgba(255, 255, 255, 175); color: {Y_TEXT}; border: 2px solid {Y_RIM}; border-radius: 13px;
    padding: 3px 11px; selection-background-color: {Y_PINK}; selection-color: #ffffff; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {Y_PINK_SOFT}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: #c4b6dc; }}
QComboBox::drop-down {{ background: {Y_PINK_GEL}; width: 22px; border: none;
                        border-top-right-radius: 11px; border-bottom-right-radius: 11px; }}
QComboBox QAbstractItemView {{ background: rgba(255, 255, 255, 240); color: {Y_TEXT};
                               selection-background-color: {Y_SELECT}; border: 2px solid {Y_PINK_SOFT};
                               border-radius: 12px; padding: 4px; }}

QTableView, QTableWidget, QListView, QListWidget {{
    background: {Y_GLASS}; alternate-background-color: rgba(255, 255, 255, 40); color: {Y_TEXT};
    gridline-color: rgba(255, 255, 255, 120); border: 2px solid {Y_RIM}; border-radius: 18px; padding: 3px;
    selection-background-color: {Y_SELECT}; selection-color: #ffffff; outline: 0; }}
/* Song rows are glass: the view's own square selection would show round the candy bar. */
QTableView, QTableWidget {{ selection-background-color: transparent; }}
QListView::item, QListWidget::item {{ padding: 6px 10px; margin: 1px 3px; border-radius: 12px; }}
QListView::item:hover, QListWidget::item:hover {{ background: rgba(255, 182, 220, 70); }}
QListView::item:selected, QListWidget::item:selected {{ background: {Y_CANDY}; color: #ffffff; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255, 255, 255, 210),
                                                    stop:1 rgba(255, 214, 236, 140));
                        color: #e0449a; border: none; border-bottom: 2px solid rgba(255, 182, 220, 190);
                        border-right: 1px solid rgba(255, 255, 255, 200); padding: 0 10px; }}
QHeaderView::section:first {{ border-top-left-radius: 15px; }}
QHeaderView::section:last {{ border-top-right-radius: 15px; border-right: none; }}
QHeaderView::section:hover {{ color: {Y_PINK}; }}

/* A string of shiny candy beads. */
QProgressBar {{ background: rgba(255, 255, 255, 150); border: 2px solid {Y_RIM}; border-radius: 11px;
                color: {Y_TEXT}; text-align: center; min-height: 16px; font-weight: bold; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fff3fa, stop:0.45 #ffa6d6,
                                                   stop:1 #ff6fbf);
                       width: 11px; margin: 3px 1px; border-radius: 5px; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 6px 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px 6px; }}
QScrollBar::handle {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f3ecff, stop:0.5 #cdb9ff,
                                                  stop:1 #a98bff);
                      border: 1px solid {Y_RIM}; border-radius: 5px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {Y_PINK_GEL}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* Checkboxes and radio buttons are both little bubbles. */
QRadioButton::indicator, QCheckBox::indicator, QAbstractItemView::indicator {{
    width: 13px; height: 13px; background: rgba(255, 255, 255, 200); border: 2px solid #c9b6ff; border-radius: 8px; }}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked, QRadioButton::indicator:checked {{
    background: {Y_PEARL}; border-color: #ff8fcf; }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ background: rgba(255, 255, 255, 90);
                                                                   border-color: #e6dcf6; }}

QSlider:horizontal {{ min-height: 26px; }}
QSlider::groove:horizontal {{ background: rgba(255, 255, 255, 170); border: 2px solid {Y_RIM}; height: 6px;
                              border-radius: 5px; }}
QSlider::sub-page:horizontal {{ background: {Y_CANDY}; border: 2px solid {Y_RIM}; height: 6px; border-radius: 5px; }}
QSlider::handle:horizontal {{ background: {Y_PEARL}; border: 1px solid rgba(255, 255, 255, 240);
                              width: 18px; height: 18px; margin: -6px 0; border-radius: 9px; }}
QSlider::handle:horizontal:hover {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.6, fx:0.35, fy:0.28,
                                    stop:0 #ffffff, stop:0.3 #eee6ff, stop:0.75 #b79cff, stop:1 #8a63e8); }}

QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: rgba(255, 255, 255, 120); color: {Y_TEXT}; border-top: 2px solid {Y_RIM}; padding: 2px 6px; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}

QFrame#PlayerDeck {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255, 255, 255, 170),
                                                 stop:1 rgba(255, 255, 255, 85));
                     border: 2px solid {Y_RIM}; border-radius: 24px; }}
QPushButton#DeckButton {{ color: #8a63e8; }}
QPushButton#DeckButton:hover {{ background: rgba(255, 255, 255, 150); }}
QPushButton#DeckButton:checked {{ background: rgba(255, 182, 220, 120); }}
/* A big glossy candy: a white shine near the top over a pink jelly body. */
QPushButton#PlayButton {{ background: qradialgradient(cx:0.5, cy:0.32, radius:0.75, fx:0.5, fy:0.12,
                                                      stop:0 #ffffff, stop:0.32 #ffbfe0, stop:0.72 #ff5fb4,
                                                      stop:1 #e0408f);
                          border: 2px solid rgba(255, 255, 255, 240); color: #ffffff; }}
QPushButton#PlayButton:hover {{ background: qradialgradient(cx:0.5, cy:0.32, radius:0.75, fx:0.5, fy:0.12,
                                                            stop:0 #ffffff, stop:0.32 #e6dcff, stop:0.72 #a98bff,
                                                            stop:1 #7c5ae0); }}
"""

Y2K_ROLES = {
    # Base and AlternateBase are see-through, so the song tables paint as glass too.
    QPalette.Window: "#f3e9ff", QPalette.WindowText: Y_TEXT, QPalette.Base: "#00ffffff",
    QPalette.AlternateBase: "#28ffffff", QPalette.Text: Y_TEXT, QPalette.Button: "#ffe6f4",
    QPalette.ButtonText: Y_TEXT, QPalette.Highlight: Y_SELECT, QPalette.HighlightedText: "#ffffff",
    QPalette.ToolTipBase: "#ffffff", QPalette.ToolTipText: Y_TEXT, QPalette.PlaceholderText: Y_MUTED,
    QPalette.Light: "#ffffff", QPalette.Dark: "#c9b6e8", QPalette.Mid: "#e6dcf6",
    QPalette.Link: "#ff3d9a", QPalette.BrightText: Y_PINK,
}

# ── XP Bliss: Luna blue bars, beige dialogs, green progress blocks ───────────

X_FACE = "#ece9d8"
X_TEXT = "#000000"
X_BORDER = "#7f9db9"
X_SELECT = "#316ac5"
X_LUNA = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3d95ff, stop:0.1 #0a6af3, stop:0.45 #0058e6, "
          "stop:0.85 #0052d6, stop:1 #003fb8)")
X_BUTTON = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:0.8 #f0efe9, stop:1 #d8d3c6)"
X_GREEN = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #c4f5b4, stop:0.35 #3dd23d, stop:0.65 #2fbf2f, stop:1 #a5ea96)"

BLISS_QSS = f"""
QMainWindow, QDialog {{ background: {X_FACE}; }}
QWidget {{ color: {X_TEXT}; }}
QToolTip {{ background: #ffffe1; color: {X_TEXT}; border: 1px solid #000000; padding: 2px 4px; }}

QMenuBar {{ background: {X_LUNA}; border-bottom: 1px solid #002d8a; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; color: #ffffff; font-weight: bold; }}
QMenuBar::item:selected {{ background: rgba(255, 255, 255, 50); border-radius: 3px; }}
QMenu {{ background: #ffffff; border: 1px solid #aca899; padding: 2px; }}
QMenu::item {{ padding: 4px 22px; }}
QMenu::item:selected {{ background: {X_SELECT}; color: #ffffff; }}

QTabWidget::pane {{ background: #fcfcfe; border: 1px solid #919b9c; top: -1px; }}
QTabBar::tab {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #ecebe6);
                color: {X_TEXT}; border: 1px solid #919b9c; border-bottom: none; padding: 4px 16px;
                margin-right: 1px; margin-top: 2px; border-top-left-radius: 3px; border-top-right-radius: 3px; }}
QTabBar::tab:selected {{ background: #fcfcfe; border-top: 3px solid #e68b2c; margin-top: 0; }}
QTabBar::tab:hover:!selected {{ border-top: 3px solid #ffc83c; }}

QGroupBox {{ border: 1px solid #d0d0bf; border-radius: 4px; margin-top: 16px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 3px; color: #0046d5; }}

QPushButton {{ background: {X_BUTTON}; color: {X_TEXT}; border: 1px solid #003c74; border-radius: 3px;
               padding: 3px 12px; min-height: 18px; }}
QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fffdf6, stop:0.8 #fdeccb,
                                                 stop:1 #f8b84e); }}
QPushButton:pressed, QPushButton:checked {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #dedcd2, stop:1 #f4f3ee); }}
QPushButton:default {{ border: 2px solid #3c7fe2; padding: 2px 11px; }}
QPushButton:disabled {{ color: #aca899; background: #f5f4ea; border-color: #c9c7ba; }}

QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QComboBox {{
    background: #ffffff; color: {X_TEXT}; border: 1px solid {X_BORDER}; padding: 3px 5px;
    selection-background-color: {X_SELECT}; selection-color: #ffffff; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: #aca899; background: #f5f4ea; }}
QComboBox::drop-down {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #dfe9fe, stop:1 #b2c9f8);
                        width: 17px; border: 1px solid #b8cdf7; border-radius: 2px; margin: 1px; }}
QComboBox QAbstractItemView {{ background: #ffffff; color: {X_TEXT}; selection-background-color: {X_SELECT};
                               border: 1px solid #000000; }}

QTableView, QTableWidget, QListView, QListWidget {{
    background: #ffffff; alternate-background-color: #f6f8fc; color: {X_TEXT}; gridline-color: {X_FACE};
    border: 1px solid {X_BORDER}; selection-background-color: {X_SELECT}; selection-color: #ffffff; outline: 0; }}
QListView::item, QListWidget::item {{ padding: 4px 8px; }}
QListView::item:hover, QListWidget::item:hover {{ background: #eef3fc; }}
QListView::item:selected, QListWidget::item:selected {{ background: {X_SELECT}; color: #ffffff; }}
QTableCornerButton::section {{ background: {X_FACE}; border: none; }}
QHeaderView {{ background: #ffffff; }}
QHeaderView::section {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #ebeadb);
                        color: {X_TEXT}; border: none; border-bottom: 3px solid #d6d2c2;
                        border-right: 1px solid #c7c5b2; padding: 0 8px; }}
QHeaderView::section:hover {{ border-bottom: 3px solid #f9b119; }}

QProgressBar {{ background: #ffffff; border: 1px solid #686868; border-radius: 3px; color: {X_TEXT};
                text-align: center; min-height: 16px; }}
QProgressBar::chunk {{ background: {X_GREEN}; width: 7px; margin: 2px 1px; }}

QScrollBar:vertical {{ background: #f4f3ef; width: 16px; margin: 0; }}
QScrollBar:horizontal {{ background: #f4f3ef; height: 16px; margin: 0; }}
QScrollBar::handle {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #cbdafc, stop:1 #b5c9f9);
                      border: 1px solid #93acec; border-radius: 3px; min-height: 28px; min-width: 28px; margin: 1px; }}
QScrollBar::handle:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #dce7fd, stop:1 #c6d7fb); }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QRadioButton::indicator, QCheckBox::indicator, QAbstractItemView::indicator {{
    width: 11px; height: 11px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #dcdcd7, stop:1 #ffffff);
    border: 1px solid #1c5180; }}
QRadioButton::indicator {{ border-radius: 6px; }}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.6, fx:0.4, fy:0.4,
                                stop:0 #5ae35a, stop:0.5 #21a121, stop:0.62 #ffffff); }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.4, fy:0.4,
                                     stop:0 #7cf07c, stop:0.4 #21a121, stop:0.55 #ffffff); }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ background: #f5f4ea; border-color: #cac8bb; }}

QSlider:horizontal {{ min-height: 26px; }}
QSlider::groove:horizontal {{ background: #f0efe7; border: 1px solid #9d9c99; height: 3px; border-radius: 1px; }}
QSlider::sub-page:horizontal {{ background: {X_SELECT}; border: 1px solid #22509a; height: 3px; border-radius: 1px; }}
QSlider::handle:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #e1e0d6);
                              border: 1px solid #7d9ec0; border-bottom: 3px solid #3fbf3f;
                              width: 10px; margin: -8px 0; border-radius: 2px; }}
QSlider::handle:horizontal:hover {{ border-bottom-color: #f9b119; }}

QSplitter::handle {{ background: {X_FACE}; }}
QStatusBar {{ background: {X_FACE}; color: {X_TEXT}; border-top: 1px solid #c7c5b2; padding: 2px 6px; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}

QFrame#PlayerDeck {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #e3e0cf);
                     border: 1px solid #aca899; border-radius: 6px; }}
QPushButton#DeckButton {{ color: #0b3d91; }}
/* The Start button's green. */
QPushButton#PlayButton {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8fd47f, stop:0.45 #3fa531,
                                                      stop:0.55 #2f8c24, stop:1 #57b847);
                          border: 1px solid #1d5e14; color: #ffffff; }}
QPushButton#PlayButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #a6e396,
                                                            stop:0.45 #4fb840, stop:0.55 #3a9e2e, stop:1 #6cc95c); }}
QPushButton#PlayButton:pressed {{ background: #2f8c24; }}
"""

BLISS_ROLES = {
    QPalette.Window: X_FACE, QPalette.WindowText: X_TEXT, QPalette.Base: "#ffffff",
    QPalette.AlternateBase: "#f6f8fc", QPalette.Text: X_TEXT, QPalette.Button: X_FACE,
    QPalette.ButtonText: X_TEXT, QPalette.Highlight: X_SELECT, QPalette.HighlightedText: "#ffffff",
    QPalette.ToolTipBase: "#ffffe1", QPalette.ToolTipText: X_TEXT, QPalette.PlaceholderText: "#7a7a7a",
    QPalette.Light: "#ffffff", QPalette.Dark: "#aca899", QPalette.Mid: "#c7c5b2",
    QPalette.Link: "#0046d5", QPalette.BrightText: "#e68b2c",
}

# ── Aqua G3: Mac OS X pinstripes, blue gel, iTunes stripes, Bondi blue plastic ─

A_TEXT = "#000000"
A_SELECT = "#3875d7"
A_BONDI = "#0095b6"
A_EDGE = "#8c8c8c"
A_GEL = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #cfe6fb, stop:0.49 #7cbaf0, stop:0.5 #3d8fdc, "
         "stop:1 #a9daff)")
A_GEL_SIDE = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #cfe6fb, stop:0.49 #7cbaf0, stop:0.5 #3d8fdc, "
              "stop:1 #a9daff)")
A_CLEAR = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:0.49 #f1f1f1, stop:0.5 #e2e2e2, "
           "stop:1 #fbfbfb)")
A_PRESSED = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #b4b4b4, stop:0.49 #d0d0d0, stop:0.5 #c2c2c2, "
             "stop:1 #e6e6e6)")

# No window background rule: top-level windows fill with the pinstripe palette brush.
AQUA_QSS = f"""
QWidget {{ color: {A_TEXT}; }}
QToolTip {{ background: #ffffc7; color: {A_TEXT}; border: 1px solid #a0a0a0; padding: 2px 5px; }}

QMenuBar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #e8e8e8);
            border-bottom: 1px solid #a8a8a8; }}
QMenuBar::item {{ background: transparent; padding: 3px 10px; }}
QMenuBar::item:selected {{ background: {A_SELECT}; color: #ffffff; }}
QMenu {{ background: rgba(250, 250, 250, 242); border: 1px solid #a8a8a8; border-radius: 5px; padding: 4px 0; }}
QMenu::item {{ padding: 4px 22px; }}
QMenu::item:selected {{ background: {A_GEL}; color: #ffffff; }}

QTabWidget::tab-bar {{ alignment: center; }}
QTabWidget::pane {{ background: rgba(0, 0, 0, 14); border: 1px solid #a8a8a8; border-radius: 6px; top: -11px;
                    padding-top: 10px; }}
QTabBar::tab {{ background: {A_CLEAR}; color: {A_TEXT}; border: 1px solid {A_EDGE}; border-left: none;
                padding: 3px 18px; min-height: 16px; }}
QTabBar::tab:first {{ border-left: 1px solid {A_EDGE}; border-top-left-radius: 10px; border-bottom-left-radius: 10px; }}
QTabBar::tab:last {{ border-top-right-radius: 10px; border-bottom-right-radius: 10px; }}
QTabBar::tab:only-one {{ border-left: 1px solid {A_EDGE}; border-radius: 10px; }}
QTabBar::tab:selected {{ background: {A_GEL}; color: #ffffff; border-color: #3a6aa8; }}
QTabBar::tab:hover:!selected {{ background: {A_PRESSED}; }}

QGroupBox {{ background: rgba(0, 0, 0, 14); border: 1px solid #b4b4b4; border-radius: 6px;
             margin-top: 16px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 3px; color: {A_TEXT}; }}

QPushButton {{ background: {A_CLEAR}; color: {A_TEXT}; border: 1px solid {A_EDGE}; border-radius: 11px;
               padding: 3px 14px; min-height: 16px; }}
QPushButton:pressed, QPushButton:checked {{ background: {A_PRESSED}; border-color: #6a6a6a; }}
QPushButton:default {{ background: {A_GEL}; border-color: #2a5f9e; }}
QPushButton:default:pressed {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #9cc8ef,
                               stop:0.49 #4f97da, stop:0.5 #2470bd, stop:1 #7fbaf0); }}
QPushButton:disabled {{ color: #a8a8a8; background: rgba(255, 255, 255, 120); border-color: #c4c4c4; }}

QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QComboBox {{
    background: #ffffff; color: {A_TEXT}; border: 1px solid #9a9a9a; border-top-color: #6e6e6e; padding: 3px 5px;
    selection-background-color: #b5d5ff; selection-color: {A_TEXT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{ border: 2px solid #7eaee8; padding: 2px 4px; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: #a8a8a8; background: #f4f4f4; }}
QComboBox {{ background: {A_CLEAR}; border: 1px solid {A_EDGE}; border-radius: 9px; padding: 3px 10px; }}
QComboBox::drop-down {{ background: {A_GEL}; width: 20px; border: none; border-left: 1px solid #2a5f9e;
                        border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
QComboBox QAbstractItemView {{ background: rgba(250, 250, 250, 245); color: {A_TEXT};
                               selection-background-color: {A_SELECT}; selection-color: #ffffff;
                               border: 1px solid #a8a8a8; }}

QTableView, QTableWidget, QListView, QListWidget {{
    background: #ffffff; alternate-background-color: #edf3fe; color: {A_TEXT}; gridline-color: #d9d9d9;
    border: 1px solid #9a9a9a; selection-background-color: {A_SELECT}; selection-color: #ffffff; outline: 0; }}
QListView::item, QListWidget::item {{ padding: 4px 8px; }}
QListView::item:alternate, QListWidget::item:alternate {{ background: #edf3fe; }}
QListView::item:selected, QListWidget::item:selected {{ background: {A_SELECT}; color: #ffffff; }}
QTableCornerButton::section {{ background: {A_CLEAR}; border: none; border-bottom: 1px solid #a5a5a5; }}
QHeaderView {{ background: #ffffff; }}
QHeaderView::section {{ background: {A_CLEAR}; color: {A_TEXT}; border: none; border-bottom: 1px solid #a5a5a5;
                        border-right: 1px solid #c8c8c8; padding: 0 8px; }}
QHeaderView::section:hover {{ background: {A_PRESSED}; }}

QProgressBar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #c8c8c8, stop:0.5 #f0f0f0, stop:1 #fafafa);
                border: 1px solid #8c8c8c; border-radius: 8px; color: {A_TEXT}; text-align: center; min-height: 14px; }}
QProgressBar::chunk {{ background: {A_GEL}; border-radius: 7px; }}

QScrollBar:vertical {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #c8c8c8, stop:0.3 #ececec,
                                                   stop:1 #fafafa); width: 15px; margin: 0; }}
QScrollBar:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #c8c8c8, stop:0.3 #ececec,
                                                     stop:1 #fafafa); height: 15px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {A_GEL_SIDE}; }}
QScrollBar::handle:horizontal {{ background: {A_GEL}; }}
QScrollBar::handle {{ border: 1px solid #3a6aa8; border-radius: 6px; min-height: 28px; min-width: 28px; margin: 1px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QRadioButton::indicator, QCheckBox::indicator, QAbstractItemView::indicator {{
    width: 12px; height: 12px; background: {A_CLEAR}; border: 1px solid {A_EDGE}; border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{ background: {A_GEL}; border-color: #2a5f9e; }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                     stop:0 #10305e, stop:0.3 #10305e, stop:0.4 #3d8fdc, stop:1 #a9daff);
                                   border-color: #2a5f9e; }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ background: #f0f0f0; border-color: #c4c4c4; }}

QSlider:horizontal {{ min-height: 21px; }}
QSlider::groove:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #9a9a9a, stop:1 #e8e8e8);
                              border: 1px solid #8c8c8c; height: 4px; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {A_GEL}; border: 1px solid #2a5f9e; height: 4px; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: qradialgradient(cx:0.5, cy:0.6, radius:0.6, fx:0.5, fy:0.25,
                                                           stop:0 #ffffff, stop:0.4 #9fcdf6, stop:1 #2f7fd0);
                              border: 1px solid #2a5f9e; width: 15px; height: 15px; margin: -7px 0; border-radius: 8px; }}

QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e4e4e4, stop:1 #c9c9c9);
              color: {A_TEXT}; border-top: 1px solid #a0a0a0; padding: 2px 6px; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}

/* iTunes-style metal deck with a round clear play button. */
QFrame#PlayerDeck {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f4f4f4, stop:0.5 #dadada,
                                                 stop:1 #c2c2c2);
                     border: 1px solid #8c8c8c; border-radius: 8px; }}
QPushButton#DeckButton {{ color: #2b2b2b; }}
QPushButton#PlayButton {{ background: {A_CLEAR}; border: 1px solid #6a6a6a; color: #1a1a1a; }}
QPushButton#PlayButton:pressed {{ background: {A_PRESSED}; }}
"""


def _pinstripes() -> QBrush:
    """Mac OS X 10.0-style horizontal pinstripes, as a tiling texture."""
    tile = QPixmap(1, 4)
    p = QPainter(tile)
    p.fillRect(0, 0, 1, 2, QColor("#f4f4f4"))
    p.fillRect(0, 2, 1, 2, QColor("#e6e6e6"))
    p.end()
    return QBrush(tile)


AQUA_ROLES = {
    QPalette.Window: _pinstripes, QPalette.WindowText: A_TEXT, QPalette.Base: "#ffffff",
    QPalette.AlternateBase: "#edf3fe", QPalette.Text: A_TEXT, QPalette.Button: "#ececec",
    QPalette.ButtonText: A_TEXT, QPalette.Highlight: A_SELECT, QPalette.HighlightedText: "#ffffff",
    QPalette.ToolTipBase: "#ffffc7", QPalette.ToolTipText: A_TEXT, QPalette.PlaceholderText: "#808080",
    QPalette.Light: "#ffffff", QPalette.Dark: "#9a9a9a", QPalette.Mid: "#c8c8c8",
    QPalette.Link: "#00799a", QPalette.BrightText: A_BONDI,
}

# ── Halo: a UNSC heads-up display. Deep space navy, holographic cyan lines, square edges ─

H_TEXT = "#d4eefc"
H_MUTED = "#6f93ab"
H_CYAN = "#5fd4ff"
H_GLOW = "#9be8ff"
H_LINE = "#2a6f96"   # dim hologram line
H_DEEP = "#12304a"
H_SELECT = "#1b7fb8"
H_AMBER = "#ffb43a"  # HUD warnings
H_BUTTON = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(30, 72, 104, 210), stop:1 rgba(9, 28, 48, 230))"
H_HOVER = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(95, 212, 255, 70), stop:1 rgba(20, 70, 105, 220))"
H_SHIELD = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #b8f0ff, stop:0.45 #4cc4f2, stop:1 #1a78b0)"

HALO_QSS = f"""
QMainWindow, QDialog {{ background: qradialgradient(cx:0.5, cy:0, radius:1.1, fx:0.5, fy:0,
                         stop:0 #12324e, stop:0.55 #08182a, stop:1 #03070d); }}
QWidget {{ color: {H_TEXT}; }}
QToolTip {{ background: #08182a; color: {H_GLOW}; border: 1px solid {H_CYAN}; padding: 3px 6px; }}

QMenuBar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0d2238, stop:1 #071321);
            border-bottom: 1px solid {H_LINE}; }}
QMenuBar::item {{ background: transparent; padding: 4px 12px; }}
QMenuBar::item:selected {{ background: rgba(95, 212, 255, 45); color: {H_GLOW}; }}
QMenu {{ background: #081626; border: 1px solid {H_CYAN}; padding: 3px; }}
QMenu::item {{ padding: 5px 22px; }}
QMenu::item:selected {{ background: {H_SELECT}; color: #ffffff; }}

/* Menu-style tabs: the active one lit from below with a cyan bar. */
QTabWidget::pane {{ background: rgba(6, 18, 32, 150); border: 1px solid {H_LINE}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {H_MUTED}; padding: 6px 22px; border: none;
                border-bottom: 2px solid transparent; font-weight: bold; }}
QTabBar::tab:selected {{ color: {H_GLOW}; border-bottom: 2px solid {H_CYAN};
                         background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(95, 212, 255, 0),
                                                     stop:1 rgba(95, 212, 255, 55)); }}
QTabBar::tab:hover:!selected {{ color: {H_TEXT}; }}

QGroupBox {{ background: rgba(10, 30, 50, 140); border: 1px solid {H_LINE}; border-top: 2px solid {H_CYAN};
             margin-top: 16px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {H_CYAN}; font-weight: bold; }}

QPushButton {{ background: {H_BUTTON}; color: {H_TEXT}; border: 1px solid {H_LINE}; border-radius: 0;
               padding: 3px 14px; min-height: 18px; font-weight: bold; }}
QPushButton:hover {{ background: {H_HOVER}; border-color: {H_CYAN}; color: {H_GLOW}; }}
QPushButton:pressed, QPushButton:checked {{ background: {H_CYAN}; color: #03101c; border-color: {H_GLOW}; }}
QPushButton:default {{ border-color: {H_CYAN}; }}
QPushButton:disabled {{ color: #3c5568; background: rgba(10, 25, 40, 150); border-color: #183247; }}

QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QComboBox {{
    background: rgba(3, 10, 18, 220); color: {H_GLOW}; border: 1px solid {H_LINE}; padding: 3px 8px;
    selection-background-color: {H_SELECT}; selection-color: #ffffff; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {H_CYAN}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: #3c5568; }}
QComboBox::drop-down {{ background: rgba(95, 212, 255, 40); width: 20px; border-left: 1px solid {H_LINE}; }}
QComboBox QAbstractItemView {{ background: #081626; color: {H_TEXT}; selection-background-color: {H_SELECT};
                               border: 1px solid {H_CYAN}; }}

QTableView, QTableWidget, QListView, QListWidget {{
    background: rgba(4, 12, 22, 215); alternate-background-color: #0a1826; color: {H_TEXT};
    gridline-color: {H_DEEP}; border: 1px solid {H_LINE}; selection-background-color: {H_SELECT};
    selection-color: #ffffff; outline: 0; }}
QTableView, QTableWidget {{ selection-background-color: transparent; }}  /* glass rows: see the delegate */
QListView::item, QListWidget::item {{ padding: 5px 10px; border-left: 3px solid transparent; }}
QListView::item:hover, QListWidget::item:hover {{ background: rgba(95, 212, 255, 25); }}
QListView::item:selected, QListWidget::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2aa6e0, stop:1 rgba(42, 166, 224, 50));
    color: #ffffff; border-left: 3px solid {H_GLOW}; }}
QTableCornerButton::section {{ background: #0b2034; border: none; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0f2a42, stop:1 #081a2c);
                        color: {H_CYAN}; border: none; border-bottom: 1px solid {H_CYAN};
                        border-right: 1px solid {H_DEEP}; padding: 0 10px; }}
QHeaderView::section:last {{ border-right: none; }}
QHeaderView::section:hover {{ color: {H_GLOW}; }}

/* The shield meter. */
QProgressBar {{ background: rgba(3, 10, 18, 220); border: 1px solid {H_LINE}; color: {H_GLOW}; text-align: center;
                min-height: 16px; font-weight: bold; }}
QProgressBar::chunk {{ background: {H_SHIELD}; width: 8px; margin: 2px 1px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: rgba(95, 212, 255, 80); min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {H_CYAN}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QRadioButton::indicator, QCheckBox::indicator, QAbstractItemView::indicator {{
    width: 11px; height: 11px; background: rgba(3, 10, 18, 220); border: 1px solid {H_CYAN}; }}
QRadioButton::indicator {{ border-radius: 6px; }}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.7, fx:0.5, fy:0.5, stop:0 {H_GLOW}, stop:0.5 {H_CYAN},
                                stop:0.56 rgba(3, 10, 18, 220)); }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                     stop:0 {H_GLOW}, stop:0.45 {H_CYAN}, stop:0.55 rgba(3, 10, 18, 220)); }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ border-color: #183247; }}

/* A thin HUD line with a notch marker. */
QSlider:horizontal {{ min-height: 20px; }}
QSlider::groove:horizontal {{ background: rgba(95, 212, 255, 45); height: 2px; }}
QSlider::sub-page:horizontal {{ background: {H_CYAN}; height: 2px; }}
QSlider::handle:horizontal {{ background: {H_GLOW}; border: 1px solid #ffffff; width: 5px; margin: -7px 0; }}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}

QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: rgba(3, 10, 18, 230); color: {H_CYAN}; border-top: 1px solid {H_LINE}; padding: 2px 6px; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}

QFrame#PlayerDeck {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(16, 44, 70, 200),
                                                 stop:1 rgba(6, 18, 32, 220));
                     border: 1px solid {H_LINE}; border-top: 2px solid {H_CYAN}; }}
QPushButton#DeckButton {{ color: {H_CYAN}; }}
QPushButton#PlayButton {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                                      stop:0 rgba(95, 212, 255, 110), stop:0.85 rgba(10, 40, 66, 230),
                                                      stop:1 rgba(10, 40, 66, 230));
                          border: 2px solid {H_CYAN}; color: {H_GLOW}; }}
QPushButton#PlayButton:hover {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                                            stop:0 rgba(155, 232, 255, 170), stop:0.85 rgba(14, 56, 90, 230),
                                                            stop:1 rgba(14, 56, 90, 230)); }}
"""

HALO_ROLES = {
    QPalette.Window: "#07111d", QPalette.WindowText: H_TEXT, QPalette.Base: "#06111d",
    QPalette.AlternateBase: "#0a1826", QPalette.Text: H_TEXT, QPalette.Button: "#0f2a42",
    QPalette.ButtonText: H_TEXT, QPalette.Highlight: H_SELECT, QPalette.HighlightedText: "#ffffff",
    QPalette.ToolTipBase: "#08182a", QPalette.ToolTipText: H_GLOW, QPalette.PlaceholderText: H_MUTED,
    QPalette.Light: H_LINE, QPalette.Dark: "#02060b", QPalette.Mid: H_DEEP,
    QPalette.Link: H_CYAN, QPalette.BrightText: H_AMBER,
}

RETRO_ROLES = {
    QPalette.Window: WINDOW, QPalette.WindowText: TEXT, QPalette.Base: LCD_BG,
    QPalette.AlternateBase: "#050a06", QPalette.Text: LCD_TEXT, QPalette.Button: "#4a4a64",
    QPalette.ButtonText: "#ececf4", QPalette.Highlight: SELECT_BG, QPalette.HighlightedText: SELECT_TEXT,
    QPalette.ToolTipBase: LCD_BG, QPalette.ToolTipText: LCD_TEXT, QPalette.PlaceholderText: MUTED,
    QPalette.Light: BEVEL_LIGHT, QPalette.Dark: BEVEL_DARK, QPalette.Mid: "#3a3a52",
    QPalette.Link: ACCENT, QPalette.BrightText: ACCENT,
}

# Shapes shared by every skin's player deck (colours come from each skin above). Sizes
# live here too: a stylesheet's min/max sizes override setFixedSize().
DECK_QSS = """
QPushButton#DeckButton { background: transparent; border: none; border-radius: 16px; padding: 0;
                         min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; }
QPushButton#DeckButton:hover { background: rgba(128, 128, 128, 45); }
QPushButton#DeckButton:pressed { background: rgba(128, 128, 128, 85); }
QPushButton#DeckButton:checked { background: rgba(128, 128, 128, 60); }
QPushButton#DeckButton:disabled { background: transparent; }
QPushButton#PlayButton { border-radius: 21px; padding: 0;
                         min-width: 42px; max-width: 42px; min-height: 42px; max-height: 42px; }
"""

# Per skin: palette roles (a colour, or a function returning a brush), stylesheet, colour for disabled text.
SKINS = {
    "retro": (RETRO_ROLES, RETRO_QSS, "#5a5a64"),
    "y2k": (Y2K_ROLES, Y2K_QSS, "#b4b2d0"),
    "bliss": (BLISS_ROLES, BLISS_QSS, "#aca899"),
    "aqua": (AQUA_ROLES, AQUA_QSS, "#a8a8a8"),
    "halo": (HALO_ROLES, HALO_QSS, "#3c5568"),
}


def _palette(roles: dict, disabled: str) -> QPalette:
    p = QPalette()
    for role, color in roles.items():
        if callable(color):
            p.setBrush(role, color())
        else:
            p.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(disabled))
    return p


@dataclass(frozen=True)
class LcdSkin:
    """Colours for the dot-matrix strip; ``scene`` paints a picture behind the dots."""

    lit: str = "#39ff7a"
    mid: str = "#ffc233"     # busy lamp
    # Level meter colours, bottom to top, blended smoothly up each bar.
    meter: tuple = ("#39ff7a", "#b8ff3a", "#ffe033", "#ff9a2e", "#ff3d5a")
    peak: str = "#d9ffe6"
    unlit: tuple = (16, 48, 26, 255)
    screen: tuple = ("#020805", "#020805")  # top, bottom
    bezel: tuple = ("#62626f", "#3a3a44", "#18181d")
    scene: str | None = None
    text_left: int = 2  # dots before the text starts (room for a scene's instrument)


LCD_SKINS = {
    # A HUD readout over Installation 04 orbiting its gas giant; the meter drains like
    # shields, from blue through amber to red.
    "halo": LcdSkin(lit="#8fe6ff", mid="#ffb43a", peak="#ffffff", unlit=(90, 170, 210, 30),
                    meter=("#1a78b0", "#3fb8ee", "#8fe6ff", "#ffb43a", "#ff4a3a"),
                    screen=("#02060d", "#071426"), bezel=("#5a6874", "#2b343c", "#0d1216"), scene="halo",
                    text_left=24),  # clear of the motion tracker
    # Winamp's display: green on black, a green-yellow-red analyser with grey peaks,
    # and the logo's lightning bolt glowing faintly behind it all.
    "retro": LcdSkin(lit="#2cf02c", mid="#f0d02c", peak="#a0a0b0", unlit=(10, 34, 10, 255),
                     meter=("#18a018", "#3cd23c", "#d8d820", "#ec8c1c", "#f0281c"),
                     screen=("#000000", "#000000"), bezel=("#50506e", "#2a2a40", "#0e0e18"),
                     scene="lightning"),
    # A pastel Tamagotchi screen in a glossy candy shell, bubbles drifting up behind the dots.
    "y2k": LcdSkin(lit="#b0389b", mid="#7c4fe0", peak="#4a2a7a", unlit=(176, 120, 200, 55),
                   meter=("#5ab8ff", "#8f7bff", "#c86bff", "#ff5fb4", "#ff2d6f"),
                   screen=("#fff3fa", "#e9e0ff"), bezel=("#ffffff", "#ffc2e2", "#d58ae0"), scene="bubbles"),
    "bliss": LcdSkin(lit="#ffffff", mid="#ffe14d", peak="#ffffff",
                     meter=("#8ff03a", "#e3f53a", "#ffd23a", "#ff9a2e", "#ff4b2b"), unlit=(255, 255, 255, 34),
                     bezel=("#3d95ff", "#0058e6", "#003fb8"), scene="bliss"),
    # iTunes' pale status display in a translucent Bondi-blue iMac shell; the meter
    # climbs through the iMac G3 flavours (Lime, Tangerine, Strawberry, Grape, Blueberry).
    "aqua": LcdSkin(lit="#24301c", mid="#3e5a2a", peak="#0f1a0c",
                    meter=("#5fae2e", "#f08a1c", "#e2457a", "#7b4fa0", "#0083c9"), unlit=(40, 60, 20, 22),
                    screen=("#e4ebcd", "#c9d3a9"), bezel=("#9be3f2", "#0095b6", "#00627a")),
}

_system_style: str | None = None
_current = "system"


def is_retro() -> bool:
    return _current == "retro"


def current_theme() -> str:
    return _current


def lcd_skin() -> LcdSkin:
    """The LCD strip's colours; the system theme keeps the classic green."""
    return LCD_SKINS.get(_current, LcdSkin())


def apply_theme(app: QApplication, name: str) -> None:
    global _system_style, _current
    _current = name if name in THEMES else "retro"
    if _system_style is None:
        _system_style = app.style().name()
    use_theme_fonts(_current)
    app.setFont(ui_font(9.5))
    if _current in SKINS:
        roles, qss, disabled = SKINS[_current]
        app.setStyle(QStyleFactory.create("Fusion"))
        app.setPalette(_palette(roles, disabled))
        app.setStyleSheet(qss + DECK_QSS)
    else:
        app.setStyleSheet("")
        app.setStyle(QStyleFactory.create(_system_style) or QStyleFactory.create("Fusion"))
        app.setPalette(app.style().standardPalette())
