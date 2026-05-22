"""Koyu tema (kullanıcının ekran görüntülerine yakın)."""
from __future__ import annotations

# Renk paleti
BG_DARK = "#0e0e10"
BG_PANEL = "#1a1a1f"
BG_ROW_ALT = "#15151a"
BORDER = "#2a2a32"
TEXT = "#e6e6ea"
TEXT_DIM = "#888894"
ACCENT_GOLD = "#d4a72c"
GREEN = "#4caf50"
RED = "#ef5350"
BLUE = "#42a5f5"
ORANGE = "#ff9800"

QSS = f"""
QWidget {{
    background-color: {BG_DARK};
    color: {TEXT};
    font-family: 'Segoe UI', 'SF Pro Text', sans-serif;
    font-size: 12px;
}}
QMainWindow, QFrame {{
    background-color: {BG_DARK};
}}
QToolBar, QStatusBar {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
    spacing: 12px;
    padding: 6px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {BG_PANEL};
}}
QTabBar::tab {{
    background-color: {BG_DARK};
    color: {TEXT_DIM};
    padding: 8px 16px;
    margin-right: 1px;
    border: 1px solid {BORDER};
}}
QTabBar::tab:selected {{
    background-color: {BG_PANEL};
    color: {ACCENT_GOLD};
    border-bottom: 2px solid {ACCENT_GOLD};
}}
QTableView, QTreeView {{
    background-color: {BG_PANEL};
    alternate-background-color: {BG_ROW_ALT};
    gridline-color: {BORDER};
    selection-background-color: {ACCENT_GOLD};
    selection-color: {BG_DARK};
}}
QHeaderView::section {{
    background-color: {BG_DARK};
    color: {TEXT_DIM};
    padding: 6px;
    border: 1px solid {BORDER};
    font-weight: bold;
}}
QLabel#StatusCard {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px 14px;
    min-width: 60px;
}}
QLabel#StatusLabel {{
    color: {TEXT_DIM};
    font-size: 10px;
    text-transform: uppercase;
}}
QLabel#StatusValue {{
    color: {TEXT};
    font-size: 18px;
    font-weight: bold;
}}
QPushButton {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px 14px;
    border-radius: 4px;
}}
QPushButton:hover {{
    background-color: {ACCENT_GOLD};
    color: {BG_DARK};
}}
QLineEdit, QComboBox {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    padding: 4px;
    border-radius: 3px;
}}
"""
