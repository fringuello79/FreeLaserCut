# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Tema grafico di FreeLaserCut: scuro, blu, pulito."""

C = {
    "bg": "#0C1322",
    "panel": "#121B2E",
    "panel2": "#17223A",
    "border": "#22304D",
    "text": "#E6ECF8",
    "muted": "#8A9BBE",
    "accent": "#2E7CF6",
    "accent_hi": "#4A92FF",
    "accent_lo": "#1B4FA8",
    "danger": "#E5484D",
    "success": "#30A46C",
    "warn": "#F5A524",
    "bed": "#0F1A2E",
    "grid": "#1C2A45",
    "grid_major": "#2A3D63",
}

QSS = f"""
* {{ font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', Arial; font-size: 10pt; color: {C['text']}; }}
QMainWindow, QWidget#root {{ background: {C['bg']}; }}
QWidget#topbar {{ background: {C['panel']}; border-bottom: 1px solid {C['border']}; }}
QLabel#brand {{ font-size: 15pt; font-weight: 700; letter-spacing: 0.5px; }}
QLabel#tagline {{ color: {C['muted']}; font-size: 9pt; }}
QLabel#muted, QLabel[muted="true"] {{ color: {C['muted']}; }}
QLabel#h2 {{ font-size: 11pt; font-weight: 600; }}
QLabel#coord {{ font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 12pt; font-weight: 600; }}
QLabel#pill {{ border-radius: 11px; padding: 3px 12px; font-weight: 600; color: white; }}

QFrame#card {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 10px; }}

QPushButton, QToolButton {{
    background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 8px;
    padding: 6px 12px; min-height: 18px;
}}
QPushButton:hover, QToolButton:hover {{ border-color: {C['accent']}; background: #1C2A47; }}
QPushButton:pressed, QToolButton:pressed {{ background: {C['accent_lo']}; }}
QPushButton:disabled, QToolButton:disabled {{ color: #55627E; border-color: #1A253C; background: #111A2B; }}
QPushButton:checked, QToolButton:checked {{ background: {C['accent']}; border-color: {C['accent_hi']}; color: white; }}
QPushButton#primary {{ background: {C['accent']}; border-color: {C['accent_hi']}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {C['accent_hi']}; }}
QPushButton#danger {{ background: #3A1418; border-color: {C['danger']}; color: #FFD9DA; font-weight: 600; }}
QPushButton#danger:hover {{ background: {C['danger']}; color: white; }}
QPushButton#primary:disabled, QPushButton#danger:disabled {{ background: #111A2B; border-color: #1A253C; color: #55627E; }}
QToolButton#jog {{ font-size: 16pt; min-width: 54px; min-height: 46px; border-radius: 10px; }}
QToolButton#jogcenter {{ font-size: 13pt; min-width: 54px; min-height: 46px; border-radius: 10px; color: {C['accent_hi']}; }}
QToolButton#seg {{ border-radius: 6px; padding: 4px 8px; min-width: 34px; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 7px; padding: 5px 8px;
    selection-background-color: {C['accent']};
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {C['accent']}; }}
QComboBox QAbstractItemView {{ background: {C['panel2']}; border: 1px solid {C['border']}; selection-background-color: {C['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}

QTabWidget::pane {{ border: none; background: {C['panel']}; }}
QTabBar::tab {{ background: transparent; color: {C['muted']}; padding: 9px 16px; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {C['text']}; border-bottom: 2px solid {C['accent']}; }}
QTabBar::tab:hover {{ color: {C['text']}; }}

QTableWidget {{ background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 8px; gridline-color: {C['border']}; }}
QHeaderView::section {{ background: {C['panel2']}; color: {C['muted']}; border: none; border-bottom: 1px solid {C['border']}; padding: 6px; font-weight: 600; }}
QTableWidget::item:selected {{ background: {C['accent_lo']}; }}

QPlainTextEdit {{ background: #080D18; border: 1px solid {C['border']}; border-radius: 8px;
    font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 9.5pt; }}
QProgressBar {{ background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 6px; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 5px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QSplitter::handle {{ background: {C['border']}; width: 1px; }}
QStatusBar {{ background: {C['panel']}; border-top: 1px solid {C['border']}; color: {C['muted']}; }}
QToolTip {{ background: {C['panel2']}; color: {C['text']}; border: 1px solid {C['accent']}; padding: 4px; }}
QFrame#alarm {{ background: #3A1418; border: 1px solid {C['danger']}; border-radius: 10px; }}
"""
