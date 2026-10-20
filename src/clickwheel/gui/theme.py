"""App themes: an original retro media-player skin, or the system look."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

THEMES = {"retro": "Retro player", "system": "System"}

# Palette for the retro skin.
WINDOW = "#23232b"
PANEL = "#2c2c36"
BEVEL_LIGHT = "#767684"
BEVEL_DARK = "#0a0a0e"
LCD_BG = "#000000"
LCD_TEXT = "#00e64d"
LIST_TEXT = "#c4f2d2"  # softer than LCD green so the quieter text tiers can fade from it
LCD_DIM = "#0b5c24"
SELECT_BG = "#1f3bbd"
SELECT_TEXT = "#ffffff"
ACCENT = "#e8b923"
TEXT = "#d6d6de"
MUTED = "#8a8a96"
MONO = '"JetBrains Mono", "DejaVu Sans Mono", "Menlo", "Consolas", monospace'

RAISED = f"border: 1px solid; border-color: {BEVEL_LIGHT} {BEVEL_DARK} {BEVEL_DARK} {BEVEL_LIGHT};"
SUNKEN = f"border: 1px solid; border-color: {BEVEL_DARK} {BEVEL_LIGHT} {BEVEL_LIGHT} {BEVEL_DARK};"

RETRO_QSS = f"""
QWidget {{ background: {WINDOW}; color: {TEXT}; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QToolTip {{ background: {LCD_BG}; color: {LCD_TEXT}; border: 1px solid {LCD_TEXT}; font-family: {MONO}; }}

QMenuBar {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3c3c48, stop:1 #26262e);
            border-bottom: 1px solid {BEVEL_DARK}; }}
QMenuBar::item {{ background: transparent; padding: 3px 10px; color: {TEXT}; }}
QMenuBar::item:selected {{ background: {SELECT_BG}; color: {SELECT_TEXT}; }}
QMenu {{ background: {PANEL}; {RAISED} }}
QMenu::item {{ padding: 4px 22px; }}
QMenu::item:selected {{ background: {SELECT_BG}; color: {SELECT_TEXT}; }}

QTabWidget::pane {{ {RAISED} background: {WINDOW}; top: -1px; }}
QTabBar::tab {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #41414e, stop:1 #2a2a33);
                color: {MUTED}; padding: 5px 16px; margin-right: 2px; {RAISED} border-bottom: none;
                font-weight: bold; }}
QTabBar::tab:selected {{ background: {WINDOW}; color: {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}

QGroupBox {{ background: {PANEL}; {RAISED} margin-top: 16px; padding: 8px 6px 6px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ACCENT}; font-weight: bold; }}

QPushButton {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5c5c6a, stop:0.5 #45454f, stop:1 #33333c);
               color: #ececf2; {RAISED} padding: 4px 12px; min-height: 18px; }}
QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6c6c7a, stop:0.5 #52525d, stop:1 #3b3b45); }}
QPushButton:pressed {{ background: #24242b; {SUNKEN} padding: 5px 11px 3px 13px; }}
QPushButton:disabled {{ color: #64646e; background: #2d2d35; border-color: #44444e #18181d #18181d #44444e; }}
QPushButton:default {{ color: {ACCENT}; }}

QLineEdit, QPlainTextEdit, QTextBrowser, QSpinBox, QComboBox {{
    background: {LCD_BG}; color: {LCD_TEXT}; {SUNKEN} padding: 4px 6px;
    selection-background-color: {SELECT_BG}; selection-color: {SELECT_TEXT}; }}
QPlainTextEdit {{ font-family: {MONO}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {LCD_DIM}; }}
QComboBox::drop-down {{ background: #3e3e49; width: 18px; border-left: 1px solid {BEVEL_DARK}; }}
QComboBox QAbstractItemView {{ background: {LCD_BG}; color: {LCD_TEXT}; selection-background-color: {SELECT_BG};
                               {RAISED} }}

QTableView, QTableWidget, QListView, QListWidget {{
    background: {LCD_BG}; alternate-background-color: #050a06; color: {LIST_TEXT};
    gridline-color: #10261a; {SUNKEN}
    selection-background-color: {SELECT_BG}; selection-color: {SELECT_TEXT}; outline: 0; }}
QListView::item, QListWidget::item {{ padding: 6px 8px; margin: 1px 3px; border-radius: 3px; }}
QListView::item:hover, QListWidget::item:hover {{ background: #0e1a12; }}
QListView::item:selected, QListWidget::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3553d6, stop:1 #1a32a8); color: {SELECT_TEXT}; }}
QTableView:disabled, QListView:disabled {{ color: {LCD_DIM}; }}
QTableCornerButton::section {{ background: #2a2a33; border: 1px solid {BEVEL_DARK}; }}
QHeaderView {{ background: #111116; }}
QHeaderView::section {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #22222a, stop:1 #15151b);
                        color: {ACCENT}; border: none; border-bottom: 1px solid #3a3a46;
                        border-right: 1px solid #1c1c23; padding: 0 10px; }}
QHeaderView::section:hover {{ color: #ffd866; }}

QProgressBar {{ background: {LCD_BG}; {SUNKEN} color: #f2fff5; text-align: center; min-height: 16px;
                font-family: {MONO}; font-weight: bold; }}
/* Darker LEDs so the white caption stays readable over lit segments. */
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #27a552, stop:1 #0d5f29);
                       width: 6px; margin: 2px 1px; }}

QScrollBar:vertical {{ background: #17171c; width: 14px; margin: 0; }}
QScrollBar:horizontal {{ background: #17171c; height: 14px; margin: 0; }}
QScrollBar::handle {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5c5c6a, stop:1 #3a3a44);
                      {RAISED} min-height: 24px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QRadioButton::indicator, QCheckBox::indicator, QAbstractItemView::indicator {{
    width: 11px; height: 11px; background: {LCD_BG}; {SUNKEN} }}
QRadioButton::indicator {{ border-radius: 7px; }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                     stop:0 #9dffbd, stop:0.45 {LCD_TEXT}, stop:0.55 {LCD_BG}); }}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7dffa6, stop:1 #00a83a); }}
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{ background: #101014; }}

QSlider::groove:horizontal {{ background: {LCD_BG}; {SUNKEN} height: 6px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #27a552, stop:1 #0d5f29);
                                 {SUNKEN} height: 6px; }}
QSlider::handle:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #8a8a98, stop:1 #4a4a55);
                              {RAISED} width: 12px; margin: -5px 0; }}
QSlider::handle:horizontal:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #a0a0ae, stop:1 #55555f); }}
QSlider:disabled {{ }}
QPushButton:checked {{ background: #1c1c22; {SUNKEN} color: {LCD_TEXT}; }}

QSplitter::handle {{ background: {WINDOW}; }}
QStatusBar {{ background: {LCD_BG}; color: {LCD_TEXT}; font-family: {MONO}; border-top: 1px solid {BEVEL_LIGHT}; }}
QStatusBar QLabel {{ color: {LCD_TEXT}; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}
"""


def _retro_palette() -> QPalette:
    p = QPalette()
    roles = {
        QPalette.Window: WINDOW, QPalette.WindowText: TEXT, QPalette.Base: LCD_BG,
        QPalette.AlternateBase: "#050a06", QPalette.Text: LCD_TEXT, QPalette.Button: "#45454f",
        QPalette.ButtonText: "#ececf2", QPalette.Highlight: SELECT_BG, QPalette.HighlightedText: SELECT_TEXT,
        QPalette.ToolTipBase: LCD_BG, QPalette.ToolTipText: LCD_TEXT, QPalette.PlaceholderText: MUTED,
        QPalette.Light: BEVEL_LIGHT, QPalette.Dark: BEVEL_DARK, QPalette.Mid: "#3a3a44",
        QPalette.Link: ACCENT, QPalette.BrightText: ACCENT,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#5a5a64"))
    return p


_system_style: str | None = None


def apply_theme(app: QApplication, name: str) -> None:
    global _system_style
    if _system_style is None:
        _system_style = app.style().name()
    if name == "retro":
        app.setStyle(QStyleFactory.create("Fusion"))
        app.setPalette(_retro_palette())
        app.setStyleSheet(RETRO_QSS)
    else:
        app.setStyleSheet("")
        app.setStyle(QStyleFactory.create(_system_style) or QStyleFactory.create("Fusion"))
        app.setPalette(app.style().standardPalette())
