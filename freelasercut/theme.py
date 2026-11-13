# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Tema grafico di FreeLaserCut: scuro (predefinito) o chiaro, con il colore principale a scelta.

Il tema si sceglie da Impostazioni → Aspetto e vale dal riavvio: i colori si leggono una volta sola, all'avvio,
prima che si costruisca qualsiasi finestra. Variabili d'ambiente per le prove: FLC_THEME (scuro | chiaro | sistema)
e FLC_ACCENT (blu | verde | viola | arancio | rosa).

Molte parti dell'interfaccia sono nate per il tema scuro e hanno colori scritti a mano: css() e tc() li
traducono negli equivalenti chiari (REMAP_LIGHT), così il tema chiaro non lascia pezzi scuri in giro.
"""
import os
import re

THEMES = ("scuro", "chiaro", "sistema")

DARK = {
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

LIGHT = {
    "bg": "#F2F4F8",
    "panel": "#FFFFFF",
    "panel2": "#ECEFF5",
    "border": "#CFD6E2",
    "text": "#1A2233",
    "muted": "#5C6880",
    "accent": "#2E7CF6",
    "accent_hi": "#1F68DB",
    "accent_lo": "#D4E3FD",
    "danger": "#D93A40",
    "success": "#23905C",
    "warn": "#D98A06",
    "bed": "#E8ECF2",
    "grid": "#D8DEE8",
    "grid_major": "#BFC8D6",
}

# colore principale: (base, chiaro/hover, scuro, tinta chiara) — "scuro" serve al tema scuro, "tinta" a quello chiaro
ACCENTS = {
    "blu": ("#2E7CF6", "#4A92FF", "#1B4FA8", "#D4E3FD"),
    "verde": ("#1F9D63", "#2DBA78", "#14663F", "#D2F0E0"),
    "viola": ("#7C5CF0", "#9479FF", "#4B3398", "#E4DCFD"),
    "arancio": ("#E2700B", "#FF8A2A", "#8A4308", "#FDE3CC"),
    "rosa": ("#D6457A", "#EC5E91", "#86264A", "#F9DBE7"),
}

# colori scritti a mano per il tema scuro → equivalenti per il tema chiaro
REMAP_LIGHT = {
    # finestra classica
    "#1C2A47": "#E1E8F4",  # pulsante sotto il mouse
    "#55627E": "#9AA4B6",  # testo e icone disattivati
    "#1A253C": "#DCE1EA",
    "#111A2B": "#EEF1F5",
    "#3A1418": "#FDE7E8",  # allarme: sfondo e testo
    "#FFD9DA": "#8A1C22",
    "#10264D": "#E2ECFD",  # informazione
    "#D6E6FF": "#163A73",
    "#3A2A0A": "#FFF2D6",  # avviso
    "#FFE8B8": "#6B4A00",
    "#080D18": "#F7F9FC",  # console e anteprima camera
    "#B9C4DC": "#3A4660",
    "#FFB347": "#B85F00",
    # interfaccia Banco
    "#0A0E17": "#E9EDF3",
    "#1A2234": "#CFD6E2",
    "#121826": "#FFFFFF",
    "#263048": "#CFD6E2",
    "#161E30": "#F5F8FD",
    "#3A1D08": "#FFE8D8",
    "#94A0B8": "#5C6880",
    "#C9D3E6": "#2C3850",
    "#2E3A56": "#C5CEDC",
    "#1E2638": "#E3E9F2",
    "#172034": "#EDF0F5",
    "#2A3550": "#C9D2E0",
    "#DDE5F3": "#1E2940",
    "#111827": "#FFFFFF",
    "#2A2018": "#E9E2DB",
    "#7A6A5A": "#9A8A7A",
    "#22304D": "#D8E3F7",
    "#E8EDF7": "#1A2233",
    "#1A1410": "#FFF3EA",
    "#141B2B": "#FFFFFF",
    "#0D1320": "#F3F5F9",
    "#FFD3B3": "#8A3A00",
    "#FFE8D6": "#6B3A10",
    "#161B26": "#F0F3F7",
    "#0F2A1E": "#E2F5EA",
    "#1D5A3C": "#9BD3B3",
    "#BFF2D6": "#155A35",
}


def _system_is_light():
    """Windows: «Modalità app» chiara nelle Impostazioni (AppsUseLightTheme = 1)."""
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return int(winreg.QueryValueEx(k, "AppsUseLightTheme")[0]) == 1
    except OSError:
        return False


def chosen():
    """(tema scelto, colore principale) dalle preferenze; le variabili d'ambiente hanno la precedenza."""
    theme, accent = os.environ.get("FLC_THEME"), os.environ.get("FLC_ACCENT")
    if theme is None or accent is None:
        try:
            from .settings_store import app_settings

            qs = app_settings()
            theme = theme or str(qs.value("ui_theme", "scuro"))
            accent = accent or str(qs.value("ui_accent", "blu"))
        except Exception:  # noqa: BLE001
            pass
    theme = theme if theme in THEMES else "scuro"
    accent = accent if accent in ACCENTS else "blu"
    return theme, accent


def build(theme="scuro", accent="blu"):
    """Tavolozza completa per tema e colore principale. «sistema» segue la modalità app di Windows."""
    light = theme == "chiaro" or (theme == "sistema" and _system_is_light())
    c = dict(LIGHT if light else DARK)
    base, hi, lo_dark, tint = ACCENTS.get(accent, ACCENTS["blu"])
    c["accent"] = base
    c["accent_hi"] = hi if not light else base
    c["accent_lo"] = tint if light else lo_dark
    c["light"] = light
    return c


THEME, ACCENT = chosen()
C = build(THEME, ACCENT)
LIGHT_UI = C["light"]
_HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")


def tc(color):
    """Un colore scritto a mano per il tema scuro, nel tema in uso."""
    if not LIGHT_UI or not isinstance(color, str):
        return color
    return REMAP_LIGHT.get(color.upper(), color)


def css(text):
    """Un foglio di stile scritto per il tema scuro, nel tema in uso (traduce i colori scritti a mano)."""
    if not LIGHT_UI:
        return text
    return _HEX.sub(lambda m: REMAP_LIGHT.get(m.group(0).upper(), m.group(0)), text)


QSS = css(f"""
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
QTableWidget::item:selected {{ background: {C['accent_lo']}; color: {C['text']}; }}

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
""")
