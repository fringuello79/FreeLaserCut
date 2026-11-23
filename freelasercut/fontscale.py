# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Grandezza dei caratteri dell'interfaccia (0.22.4, chiesta da un utente con un portatile Mac).

Due fattori, moltiplicati fra loro:
- **piattaforma**: FreeLaserCut scrive le grandezze in punti. Su Windows e Linux un punto vale 96/72 di pixel, sul Mac
  un pixel solo: lo stesso «9 punti» lì usciva alto 9 pixel invece di 12, cioè tutto il testo un quarto più piccolo.
  Dove lo schermo dichiara meno di 96 punti per pollice le grandezze in punti si moltiplicano per 96/quel valore, così
  il testo è alto gli stessi pixel su tutti i sistemi;
- **scelta della persona**: Impostazioni → Grandezza dei caratteri (vale dal riavvio).

Le grandezze scritte in pixel seguono solo la scelta della persona (un pixel è uguale dappertutto).
Tutto passa da qui: pt() per i caratteri creati nel codice, css() per fogli di stile e testi con «font-size».
Senza setup() i fattori valgono 1: le prove automatiche e chi usa i moduli da solo vedono le grandezze di sempre.
Nessuna dipendenza da Qt.
"""
import os
import re

KEY = "ui_font_percent"
SIZES = (85, 100, 115, 130, 150)  # scelte possibili, in percento
DEFAULT = 100
BASE_DPI = 96.0

_k_pt = 1.0
_k_px = 1.0
percent = DEFAULT  # scelta in uso da questo avvio
platform = 1.0  # fattore della piattaforma in uso da questo avvio

_FS = re.compile(r"(font-size\s*:\s*)(\d+(?:\.\d+)?)(\s*)(pt|px)")


def clean_percent(value):
    """La scelta salvata, riportata a una di quelle possibili (la più vicina); qualsiasi altra cosa: 100."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT
    if not 50 <= v <= 300:
        return DEFAULT
    return min(SIZES, key=lambda s: abs(s - v))


def saved_percent(qs=None):
    """Scelta salvata: variabile FLC_FONT_PERCENT (per le prove e per chi è rimasto con caratteri troppo grandi),
    poi le preferenze."""
    env = os.environ.get("FLC_FONT_PERCENT")
    if env:
        return clean_percent(env)
    if qs is None:
        return DEFAULT
    return clean_percent(qs.value(KEY, DEFAULT))


def platform_factor(dpi):
    """Quanto ingrandire le grandezze in punti perché valgano gli stessi pixel che a 96 punti per pollice.
    Sopra 96 non si tocca niente: lì è una scelta del sistema o della persona."""
    try:
        dpi = float(dpi)
    except (TypeError, ValueError):
        return 1.0
    if not 48.0 <= dpi < BASE_DPI - 0.5:
        return 1.0
    return BASE_DPI / dpi


def setup(pct=DEFAULT, dpi=BASE_DPI):
    """Da chiamare una volta all'avvio, prima di creare caratteri e fogli di stile. -> (fattore punti, fattore pixel)"""
    global _k_pt, _k_px, percent, platform
    percent = clean_percent(pct)
    platform = platform_factor(dpi)
    _k_px = percent / 100.0
    _k_pt = platform * _k_px
    return _k_pt, _k_px


def reset():
    return setup(DEFAULT, BASE_DPI)


def k_pt():
    return _k_pt


def k_px():
    return _k_px


def pt(size):
    """Una grandezza in punti, come va data a Qt su questo sistema e con la scelta della persona."""
    return round(float(size) * _k_pt, 2)


def px(size):
    """Una grandezza di carattere in pixel, con la scelta della persona."""
    return max(1, int(round(float(size) * _k_px)))


def _num(v):
    return ("%.2f" % v).rstrip("0").rstrip(".")


def css(text):
    """Un foglio di stile (o un testo con stili) con tutte le «font-size» portate alla grandezza giusta."""
    if not isinstance(text, str) or (_k_pt == 1.0 and _k_px == 1.0) or "font-size" not in text:
        return text

    def rep(m):
        k = _k_pt if m.group(4) == "pt" else _k_px
        v = float(m.group(2)) * k
        if m.group(4) == "px":
            v = max(1.0, round(v))
        return m.group(1) + _num(v) + m.group(3) + m.group(4)

    return _FS.sub(rep, text)
