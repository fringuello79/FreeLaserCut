# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Lingue dell'interfaccia: inglese, italiano, spagnolo, francese, portoghese.

I testi nel codice sono scritti in italiano e passano da tr(). I cataloghi in freelasercut/locale/<lingua>.json
associano a ogni testo italiano la traduzione; se una traduzione manca si usa l'inglese, poi l'italiano.
La lingua si sceglie all'avvio (preferenza salvata, altrimenti quella di Windows, altrimenti l'inglese)
e si cambia dal menu: vale dal riavvio successivo. Nessuna dipendenza da Qt, tranne install_qt_translations().
"""
import json
import os
import re
import string

LANGUAGES = {  # codice: nome nella propria lingua
    "en": "English",
    "it": "Italiano",
    "es": "Español",
    "fr": "Français",
    "pt": "Português",
}
DEFAULT = "en"
QT_FILES = {"pt": "pt_BR"}  # Qt ha solo il portoghese brasiliano per i pulsanti standard
SOURCE = "it"  # lingua dei testi scritti nel codice
LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locale")

_lang = os.environ.get("FLC_LANG", SOURCE) if os.environ.get("FLC_LANG", SOURCE) in LANGUAGES else SOURCE
_catalog = {}
_fallback = {}
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _fields(text):
    try:
        return sorted(f[1] or "" for f in string.Formatter().parse(text) if f[1] is not None)
    except ValueError:
        return None


def _load(lang):
    if lang == SOURCE:
        return {}
    path = os.path.join(LOCALE_DIR, f"{lang}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    good = {}
    for src, dst in data.items():
        if not isinstance(dst, str) or not dst.strip():
            continue
        if ("{" in src or "{" in dst) and _fields(src) != _fields(dst):
            continue  # segnaposto diversi: meglio il testo originale che un errore
        good[src] = dst
    return good


def set_language(lang):
    """Imposta la lingua (da chiamare prima di importare le finestre)."""
    global _lang, _catalog, _fallback
    _lang = lang if lang in LANGUAGES else DEFAULT
    _catalog = _load(_lang)
    _fallback = _load(DEFAULT) if _lang not in (DEFAULT, SOURCE) else {}
    return _lang


def language():
    return _lang


def tr(text, *args):
    """Testo nella lingua scelta. Con argomenti è un modello: tr("Porta {0}", nome)."""
    out = _catalog.get(text) or _fallback.get(text) or text
    if not args:
        return out
    try:
        return out.format(*args)
    except (IndexError, KeyError, ValueError):
        return text.format(*args)


def system_language():
    """Lingua del sistema se è tra quelle disponibili, altrimenti l'inglese."""
    code = ""
    try:
        from PySide6.QtCore import QLocale

        code = QLocale.system().name()[:2].lower()
    except Exception:  # noqa: BLE001
        pass
    return code if code in LANGUAGES else DEFAULT


def saved_language():
    try:
        from .settings_store import app_settings

        v = app_settings().value("language")
        return v if v in LANGUAGES else None
    except Exception:  # noqa: BLE001
        return None


def save_language(lang):
    from .settings_store import app_settings

    qs = app_settings()
    qs.setValue("language", lang)
    qs.sync()


def startup_language():
    """Lingua da usare all'avvio: variabile FLC_LANG, preferenza salvata, lingua di Windows, inglese."""
    env = os.environ.get("FLC_LANG")
    if env in LANGUAGES:
        return env
    return saved_language() or system_language()


def install_qt_translations(app):
    """Traduce anche i pulsanti standard di Qt (OK, Annulla, Salva…) nella lingua scelta."""
    if _lang == "en":
        return []
    from PySide6.QtCore import QLibraryInfo, QTranslator

    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    out = []
    for name in ("qtbase", "qt"):
        t = QTranslator(app)
        if t.load(f"{name}_{QT_FILES.get(_lang, _lang)}", path):
            app.installTranslator(t)
            out.append(t)
            break
    return out
