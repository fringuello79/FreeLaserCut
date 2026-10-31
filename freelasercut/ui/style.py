# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Stile professionale: font Inter + JetBrains Mono, icone vettoriali Lucide ricolorate al volo."""
import os
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..theme import C
from freelasercut.i18n import tr  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
UI_FONT = "Inter"
MONO_FONT = "JetBrains Mono"
_loaded = False


def load_fonts():
    global _loaded, UI_FONT, MONO_FONT
    if _loaded:
        return
    fams = set()
    fdir = os.path.join(ASSETS, "fonts")
    for f in sorted(os.listdir(fdir)) if os.path.isdir(fdir) else []:
        if f.lower().endswith((".ttf", ".otf")):
            fid = QFontDatabase.addApplicationFont(os.path.join(fdir, f))
            if fid >= 0:
                fams.update(QFontDatabase.applicationFontFamilies(fid))
    import sys

    if "Inter" not in fams or sys.platform == "win32":
        UI_FONT = tr("Segoe UI")  # su Windows il carattere di sistema è il più nitido (hinting ClearType)
    if "JetBrains Mono" not in fams:
        MONO_FONT = "Consolas"
    _loaded = True


def ui_font(size=9.0, weight=QFont.Weight.Normal):
    f = QFont(UI_FONT)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def mono_font(size=9.0):
    f = QFont(MONO_FONT)
    f.setPointSizeF(size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


@lru_cache(maxsize=512)
def _svg(name):
    path = os.path.join(ASSETS, "icons", f"{name}.svg")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _render(name, color, size, stroke=None):
    src = _svg(name)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    if src is None:
        return pm
    data = src.replace("currentColor", color)
    if stroke is not None:
        data = data.replace('stroke-width="2"', f'stroke-width="{stroke}"')
    r = QSvgRenderer(QByteArray(data.encode()))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


@lru_cache(maxsize=1024)
def icon(name, color=None, size=20, active=None):
    """Icona con stati: normale, disabilitata, attiva (checked). Nitida a ogni DPI (renderizzata a 2×)."""
    color = color or C["text"]
    ic = QIcon()
    for scale in (1, 2):
        s = size * scale
        ic.addPixmap(_render(name, color, s, 1.75), QIcon.Mode.Normal, QIcon.State.Off)
        ic.addPixmap(_render(name, "#55627E", s, 1.75), QIcon.Mode.Disabled, QIcon.State.Off)
        ic.addPixmap(_render(name, active or "#FFFFFF", s, 1.75), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(_render(name, "#55627E", s, 1.75), QIcon.Mode.Disabled, QIcon.State.On)
    return ic


def pixmap(name, color=None, size=20):
    return _render(name, color or C["text"], size, 1.75)


QSS_EXTRA = f"""
QMainWindow::separator {{ background: {C['border']}; width: 1px; height: 1px; }}
QMenuBar {{ background: {C['panel']}; border-bottom: 1px solid {C['border']}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 6px; background: transparent; }}
QMenuBar::item:selected {{ background: {C['panel2']}; }}
QMenu {{ background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 26px; border-radius: 6px; }}
QMenu::item:selected {{ background: {C['accent_lo']}; }}
QMenu::item:disabled {{ color: #55627E; }}
QMenu::separator {{ height: 1px; background: {C['border']}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}
QToolBar {{ background: {C['panel']}; border: none; spacing: 2px; padding: 3px 6px; }}
QToolBar#tools {{ border-right: 1px solid {C['border']}; padding: 6px 4px; }}
QToolBar#main {{ border-bottom: 1px solid {C['border']}; }}
QToolBar#numeric {{ border-bottom: 1px solid {C['border']}; }}
QToolBar#palette {{ border-top: 1px solid {C['border']}; padding: 4px 8px; }}
QToolBar QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 5px; min-height: 0; }}
QToolBar QToolButton:hover {{ background: {C['panel2']}; border-color: {C['border']}; }}
QToolBar QToolButton:checked {{ background: {C['accent']}; border-color: {C['accent_hi']}; }}
QToolBar QToolButton:pressed {{ background: {C['accent_lo']}; }}
QToolBar::separator {{ background: {C['border']}; width: 1px; height: 1px; margin: 4px 6px; }}
QDockWidget {{ titlebar-close-icon: none; font-weight: 600; }}
QDockWidget::title {{ background: {C['panel']}; padding: 7px 10px; border-bottom: 1px solid {C['border']}; text-align: left; }}
QDockWidget > QWidget {{ background: {C['panel']}; }}
QScrollArea {{ background: {C['panel']}; border: none; }}
QScrollArea > QWidget > QWidget {{ background: {C['panel']}; }}
QTabBar::tab {{ min-width: 64px; }}
QTabBar#docktabs::tab {{ padding: 6px 12px; }}
QLineEdit#num {{ font-family: '{MONO_FONT}'; padding: 3px 6px; min-width: 64px; max-width: 86px; }}
QLabel#numlabel {{ color: {C['muted']}; font-weight: 600; padding: 0 2px 0 8px; }}
QDoubleSpinBox, QSpinBox {{ font-family: '{UI_FONT}'; }}
QHeaderView::section {{ font-size: 8.5pt; }}
QTreeWidget, QListWidget {{ background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 8px; }}
QTreeWidget::item, QListWidget::item {{ padding: 4px; }}
QTableWidget {{ background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 8px; gridline-color: {C['border']}; }}
QTableWidget QTableCornerButton::section, QHeaderView {{ background: {C['panel2']}; }}
QHeaderView::section {{ background: {C['panel2']}; border: none; border-right: 1px solid {C['border']}; padding: 4px 6px; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {C['accent_lo']}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {C['border']}; background: {C['bg']}; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent_hi']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {C['border']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {C['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; background: {C['text']}; }}
QGroupBox {{ border: 1px solid {C['border']}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {C['muted']}; }}
QDialog {{ background: {C['panel']}; }}
QTextEdit, QPlainTextEdit#textedit {{ background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 8px; font-family: '{UI_FONT}'; font-size: 10.5pt; }}
"""

# Campi in cui si scrivono valori: bianchi con testo scuro (si leggono meglio e si distinguono dai pulsanti)
_Q = os.path.join(ASSETS, "qss").replace("\\", "/")
FIELD_BG, FIELD_TX, FIELD_BD = "#FFFFFF", "#0E1526", "#B9C4D8"
QSS_EXTRA += f"""
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit#textedit {{
    background: {FIELD_BG}; color: {FIELD_TX}; border: 1px solid {FIELD_BD};
    selection-background-color: {C['accent']}; selection-color: #FFFFFF;
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QTextEdit:hover, QPlainTextEdit#textedit:hover {{
    border-color: {C['accent_hi']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit#textedit:focus {{
    border: 1px solid {C['accent']}; background: #FFFFFF;
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QTextEdit:disabled {{
    background: #D5DBE6; color: #7D889E; border-color: #AEB8CA;
}}
QLineEdit#num {{ color: {FIELD_TX}; }}
QComboBox QAbstractItemView {{ background: #FFFFFF; color: {FIELD_TX}; border: 1px solid {FIELD_BD};
    selection-background-color: {C['accent']}; selection-color: #FFFFFF; outline: none; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({_Q}/down.svg); width: 10px; height: 6px; }}
QComboBox::down-arrow:disabled {{ image: url({_Q}/down_dis.svg); }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ background: #EEF2F8; border: none;
    border-left: 1px solid {FIELD_BD}; width: 18px; }}
QAbstractSpinBox::up-button {{ border-top-right-radius: 7px; }}
QAbstractSpinBox::down-button {{ border-bottom-right-radius: 7px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: #DCE6F8; }}
QAbstractSpinBox::up-arrow {{ image: url({_Q}/up.svg); width: 10px; height: 6px; }}
QAbstractSpinBox::down-arrow {{ image: url({_Q}/down.svg); width: 10px; height: 6px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{ image: none; }}
QToolButton#snapbtn {{ padding: 3px 8px; border-radius: 6px; font-size: 8.5pt; }}
"""

# Densità "da software professionale": caratteri di sistema a 9 pt, controlli bassi, margini stretti
QSS_EXTRA += f"""
* {{ font-family: '{UI_FONT}', 'Segoe UI', 'Inter', Arial; font-size: 9pt; }}
QPushButton, QToolButton {{ padding: 3px 9px; min-height: 17px; border-radius: 4px; }}
QPushButton#primary, QPushButton#danger {{ font-weight: 600; }}
QToolBar QToolButton {{ padding: 3px; border-radius: 4px; }}
QToolBar {{ spacing: 1px; padding: 2px 4px; }}
QToolBar#tools {{ padding: 4px 3px; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ padding: 1px 5px; min-height: 18px; border-radius: 3px; }}
QTextEdit, QPlainTextEdit#textedit {{ border-radius: 3px; font-size: 9.5pt; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 15px; }}
QAbstractSpinBox::up-button {{ border-top-right-radius: 3px; }}
QAbstractSpinBox::down-button {{ border-bottom-right-radius: 3px; }}
QLineEdit#num {{ padding: 1px 4px; min-width: 58px; max-width: 74px; }}
QLabel#numlabel {{ padding: 0 2px 0 6px; }}
QTabBar::tab {{ padding: 4px 10px; min-width: 40px; }}
QTabBar#docktabs::tab {{ padding: 4px 9px; }}
QDockWidget::title {{ padding: 4px 8px; }}
QTreeWidget::item, QListWidget::item {{ padding: 1px 2px; }}
QHeaderView::section {{ padding: 3px 4px; font-size: 8.5pt; }}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border-radius: 3px; }}
QGroupBox {{ margin-top: 10px; padding: 6px 6px 6px 6px; border-radius: 4px; }}
QMenuBar::item {{ padding: 3px 8px; border-radius: 3px; }}
QMenu {{ padding: 4px; border-radius: 4px; }}
QMenu::item {{ padding: 4px 22px 4px 22px; border-radius: 3px; }}
QStatusBar {{ font-size: 8.5pt; }}
QStatusBar QLabel {{ padding: 0 4px; }}
QToolButton#jog {{ font-size: 12pt; min-width: 40px; min-height: 32px; border-radius: 6px; }}
QToolButton#jogcenter {{ font-size: 10pt; min-width: 40px; min-height: 32px; border-radius: 6px; }}
QFrame#card {{ border-radius: 5px; }}
QTreeWidget, QListWidget, QTableWidget {{ border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; }}
"""

QSS_EXTRA += f"""
QFrame#connbar {{ background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 4px; }}
QStatusBar QPushButton {{ background: transparent; border: none; padding: 1px 8px; min-height: 0; }}
QStatusBar QPushButton:hover {{ background: {C['panel2']}; }}
QMainWindow QTabBar::tab {{ padding: 5px 8px; }}
"""

# Campi compatti: carattere dell'interfaccia (cifre a larghezza fissa), altezza ridotta, frecce piccole
QSS_EXTRA += f"""
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    font-family: '{UI_FONT}'; font-size: 8.5pt; padding: 0px 4px; min-height: 16px; max-height: 20px;
}}
QLineEdit#num {{ font-family: '{UI_FONT}'; font-size: 8.5pt; padding: 0px 4px; min-width: 52px; max-width: 66px; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: #EDF0F4; color: #97A0B2; border-color: #CDD4DF;
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 12px; background: #F1F4F8; }}
QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow {{ width: 7px; height: 4px; }}
QComboBox::drop-down {{ width: 16px; }}
QComboBox::down-arrow {{ width: 8px; height: 5px; }}
QLabel {{ font-size: 8.5pt; }}
QPushButton, QToolButton {{ font-size: 8.5pt; padding: 2px 8px; min-height: 16px; }}
QCheckBox, QRadioButton {{ font-size: 8.5pt; }}
"""

# Barra numerica (0.5): campi bassi con l'unità scritta dentro, lucchetto piccolo, menu livello compatto
QSS_EXTRA += f"""
QToolBar#numeric {{ padding: 1px 4px; spacing: 1px; }}
QToolBar#numeric QLabel {{ font-size: 8pt; }}
QToolBar#numeric QLabel#numlabel {{ padding: 0 2px 0 5px; }}
QLineEdit#numbar {{
    font-family: '{UI_FONT}'; font-size: 8pt; padding: 0px 3px; border-radius: 2px;
    min-height: 0px; max-height: 18px;
}}
QComboBox#numcombo {{ font-size: 8pt; padding: 0px 3px; min-height: 0px; max-height: 20px; border-radius: 2px; }}
QToolBar QToolButton#minilock {{ padding: 0px; margin: 0px 1px; border-radius: 3px; }}
QToolBar QToolButton#minilock:checked {{ background: transparent; border-color: transparent; }}
QToolBar QToolButton#minilock:hover {{ background: {C['panel2']}; border-color: {C['border']}; }}
QToolBar#numeric QToolButton {{ padding: 2px; }}
"""

# Modalità guida "?" (0.5)
QSS_EXTRA += f"""
QFrame#helpcard {{ background: {C['panel2']}; border: 1px solid {C['accent']}; border-radius: 6px; }}
QFrame#helpcard QLabel {{ font-size: 8.5pt; color: {C['text']}; }}
QToolButton#helpbtn:checked {{ background: {C['accent']}; border-color: {C['accent_hi']}; }}
"""

QSS_EXTRA += """
QToolButton#supportbtn { background: #FFFFFF; color: #0E1734; border: 1px solid #FFFFFF; border-radius: 8px;
    padding: 3px 12px 3px 9px; font-weight: 600; }
QToolButton#supportbtn:hover { background: #FFF3EA; border-color: #FF9A4D; }
QToolButton#supportbtn:pressed { background: #FFE2CC; }
"""
