"""App themes: original skins (retro player, Y2K bubblegum, XP Bliss, Aqua G3), or the system look."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QBrush, QColor, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QStyleFactory

from .fonts import ui_font, use_theme_fonts

THEMES = {"retro": "Retro player", "y2k": "Y2K bubblegum", "bliss": "XP Bliss", "aqua": "Aqua G3", "system": "System"}

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


# ── Y2K bubblegum: icy blue and candy pink, glossy gel pills and bubbles ─────

Y_TEXT = "#2a2266"
Y_MUTED = "#7b78a8"
Y_PINK = "#ff4fa8"
Y_PINK_SOFT = "#ffb3dc"
Y_BLUE = "#2f9bff"
Y_BLUE_SOFT = "#9fd2ff"
Y_SELECT = "#3aa0ff"
# Aqua-style gel: a bright highlight on the top half, a hard edge, then a glowing bottom.
Y_BLUE_GEL = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #d2efff, stop:0.48 #74c6ff, stop:0.52 #2f9bff, stop:1 #8fd6ff)"
Y_PINK_GEL = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffe3f2, stop:0.48 #ff94cc, stop:0.52 #ff4fa8, stop:1 #ffa3d6)"
Y_BUBBLE = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:0.48 #eaf5ff, stop:0.52 #cfe8ff, stop:1 #eef8ff)"
Y_CANDY = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5ab8ff, stop:1 #ff6fbf)"

Y2K_QSS = f"""
QMainWindow, QDialog {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                         stop:0 #dcefff, stop:0.55 #f1e9ff, stop:1 #ffe0f1); }}
QWidget {{ color: {Y_TEXT}; }}
QToolTip {{ background: #fff2f9; color: {Y_TEXT}; border: 2px solid {Y_PINK_SOFT}; border-radius: 10px;
            padding: 4px 8px; }}

QMenuBar {{ background: {Y_BUBBLE}; border-bottom: 2px solid {Y_PINK_SOFT}; }}
QMenuBar::item {{ background: transparent; padding: 3px 12px; border-radius: 10px; }}
QMenuBar::item:selected {{ background: {Y_PINK_GEL}; color: #ffffff; }}
QMenu {{ background: #ffffff; border: 2px solid {Y_PINK_SOFT}; border-radius: 12px; padding: 5px; }}
QMenu::item {{ padding: 5px 22px; border-radius: 9px; }}
QMenu::item:selected {{ background: {Y_BLUE_GEL}; color: #ffffff; }}

QTabWidget::pane {{ background: rgba(255, 255, 255, 140); border: 2px solid {Y_PINK_SOFT}; border-radius: 16px; }}
QTabBar::tab {{ background: {Y_BUBBLE}; color: #5a5a9a; border: 2px solid {Y_BLUE_SOFT}; border-radius: 13px;
                padding: 4px 18px; margin: 3px 3px 5px 3px; font-weight: bold; }}
QTabBar::tab:selected {{ background: {Y_PINK_GEL}; color: #ffffff; border-color: {Y_PINK}; }}
QTabBar::tab:hover:!selected {{ border-color: {Y_PINK_SOFT}; color: {Y_TEXT}; }}

QGroupBox {{ background: rgba(255, 255, 255, 170); border: 2px solid #bfe0ff; border-radius: 16px;
             margin-top: 16px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {Y_PINK}; font-weight: bold; }}

QPushButton {{ background: {Y_BUBBLE}; color: {Y_TEXT}; border: 2px solid #7cc0ff; border-radius: 13px;
               padding: 3px 12px; min-height: 18px; font-weight: bold; }}
QPushButton:hover {{ border-color: {Y_PINK}; background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                     stop:0 #ffffff, stop:0.48 #fff0f8, stop:0.52 #ffd6ec, stop:1 #fff2fa); }}
QPushButton:pressed, QPushButton:checked {{ background: {Y_PINK_GEL}; color: #ffffff; border-color: #e0408f; }}
QPushButton:default {{ background: {Y_BLUE_GEL}; color: #ffffff; border-color: #1f7fe0; }}
QPushButton:default:hover {{ border-color: {Y_PINK}; }}
QPushButton:disabled {{ color: #b4b2d0; background: #f4f7fd; border-color: #d6e6f8; }}

QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QComboBox {{
    background: #ffffff; color: {Y_TEXT}; border: 2px solid {Y_BLUE_SOFT}; border-radius: 12px; padding: 3px 10px;
    selection-background-color: {Y_PINK}; selection-color: #ffffff; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {Y_PINK}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: #b4b2d0; background: #f7f9fe; }}
QComboBox::drop-down {{ background: {Y_PINK_GEL}; width: 22px; border: none;
                        border-top-right-radius: 10px; border-bottom-right-radius: 10px; }}
QComboBox QAbstractItemView {{ background: #ffffff; color: {Y_TEXT}; selection-background-color: {Y_SELECT};
                               border: 2px solid {Y_PINK_SOFT}; border-radius: 10px; padding: 4px; }}

QTableView, QTableWidget, QListView, QListWidget {{
    background: #ffffff; alternate-background-color: #f6f9ff; color: {Y_TEXT}; gridline-color: #e8eefc;
    border: 2px solid #bfe0ff; border-radius: 14px; padding: 3px;
    selection-background-color: {Y_SELECT}; selection-color: #ffffff; outline: 0; }}
QListView::item, QListWidget::item {{ padding: 6px 10px; margin: 1px 3px; border-radius: 10px; }}
QListView::item:hover, QListWidget::item:hover {{ background: #fff0f8; }}
QListView::item:selected, QListWidget::item:selected {{ background: {Y_BLUE_GEL}; color: #ffffff; }}
QTableCornerButton::section {{ background: #fff4fa; border: none; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fff6fb, stop:1 #ffdcef);
                        color: #d6338a; border: none; border-bottom: 2px solid {Y_PINK_SOFT};
                        border-right: 1px solid #ffe3f2; padding: 0 10px; }}
QHeaderView::section:first {{ border-top-left-radius: 11px; }}
QHeaderView::section:last {{ border-top-right-radius: 11px; border-right: none; }}
QHeaderView::section:hover {{ color: {Y_PINK}; }}

QProgressBar {{ background: #ffffff; border: 2px solid {Y_BLUE_SOFT}; border-radius: 10px; color: {Y_TEXT};
                text-align: center; min-height: 16px; font-weight: bold; }}
QProgressBar::chunk {{ background: {Y_CANDY}; margin: 2px; border-radius: 7px; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px 4px; }}
QScrollBar::handle {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffc9e6, stop:1 #ff8cc8);
                      border-radius: 4px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {Y_PINK}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QRadioButton::indicator, QCheckBox::indicator, QAbstractItemView::indicator {{
    width: 12px; height: 12px; background: #ffffff; border: 2px solid #7cc0ff; border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{ background: {Y_PINK_GEL}; border-color: #e0408f; }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.4, fy:0.35,
                                     stop:0 #ffd6ec, stop:0.5 {Y_PINK}, stop:0.62 #ffffff); border-color: #e0408f; }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ background: #f4f7fd; border-color: #d6e6f8; }}

QSlider:horizontal {{ min-height: 22px; }}
QSlider::groove:horizontal {{ background: #ffffff; border: 2px solid {Y_BLUE_SOFT}; height: 6px; border-radius: 5px; }}
QSlider::sub-page:horizontal {{ background: {Y_CANDY}; border: 2px solid #7cc0ff; height: 6px; border-radius: 5px; }}
QSlider::handle:horizontal {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.6, fx:0.35, fy:0.3,
                                                           stop:0 #ffffff, stop:0.35 #ffc6e5, stop:1 {Y_PINK});
                              border: 1px solid #e0408f; width: 16px; height: 16px; margin: -6px 0; border-radius: 9px; }}
QSlider::handle:horizontal:hover {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.6, fx:0.35, fy:0.3,
                                                                 stop:0 #ffffff, stop:0.35 #bfe6ff, stop:1 {Y_BLUE}); }}

QSplitter::handle {{ background: transparent; }}
QStatusBar {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #cfe8ff, stop:1 #ffd6ec);
              color: {Y_TEXT}; border-top: 2px solid {Y_PINK_SOFT}; padding: 2px 6px; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}

QFrame#PlayerDeck {{ background: rgba(255, 255, 255, 170); border: 2px solid {Y_PINK_SOFT}; border-radius: 18px; }}
QPushButton#DeckButton {{ color: {Y_TEXT}; }}
QPushButton#PlayButton {{ background: {Y_PINK_GEL}; border: 2px solid #e0408f; color: #ffffff; }}
QPushButton#PlayButton:hover {{ background: {Y_BLUE_GEL}; border-color: #1f7fe0; }}
"""

Y2K_ROLES = {
    QPalette.Window: "#eef4ff", QPalette.WindowText: Y_TEXT, QPalette.Base: "#ffffff",
    QPalette.AlternateBase: "#f6f9ff", QPalette.Text: Y_TEXT, QPalette.Button: "#e3f2ff",
    QPalette.ButtonText: Y_TEXT, QPalette.Highlight: Y_SELECT, QPalette.HighlightedText: "#ffffff",
    QPalette.ToolTipBase: "#fff2f9", QPalette.ToolTipText: Y_TEXT, QPalette.PlaceholderText: Y_MUTED,
    QPalette.Light: "#ffffff", QPalette.Dark: "#9fb8dd", QPalette.Mid: "#c9dcf5",
    QPalette.Link: "#f0328f", QPalette.BrightText: Y_PINK,
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


LCD_SKINS = {
    # Winamp's display: green on black, a green-yellow-red analyser with grey peaks,
    # and the logo's lightning bolt glowing faintly behind it all.
    "retro": LcdSkin(lit="#2cf02c", mid="#f0d02c", peak="#a0a0b0", unlit=(10, 34, 10, 255),
                     meter=("#18a018", "#3cd23c", "#d8d820", "#ec8c1c", "#f0281c"),
                     screen=("#000000", "#000000"), bezel=("#50506e", "#2a2a40", "#0e0e18"),
                     scene="lightning"),
    "y2k": LcdSkin(lit="#86f6ff", mid="#ff8ce0", peak="#ffffff",
                   meter=("#5ff3ff", "#6fa8ff", "#b48cff", "#ff7ad9", "#ff4fa8"), unlit=(70, 42, 130, 255),
                   screen=("#160b44", "#33115c"), bezel=("#ffe3f2", "#ff8fca", "#d9408f")),
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
