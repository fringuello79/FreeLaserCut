# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: moduli aggiuntivi.

Un modulo aggiuntivo è una cartella dentro «moduli», nella cartella dei dati di FreeLaserCut (config_dir()), con:
- `modulo.json`: {"id": "...", "nome": "...", "versione": "1.0", "api": 1, "flc_min": "0.21.2", "flc_max": "",
  "autore": "...", "descrizione": "..."} («flc_max» vuoto = nessun limite);
- `__init__.py` con la funzione `registra(api)`, che riceve un oggetto Api (sotto) e aggiunge i suoi comandi.

FreeLaserCut non contiene moduli, non li scarica e non li installa: la cartella «moduli» non esiste finché qualcuno non
ce la mette. Un modulo è codice che gira con gli stessi permessi del programma: va installato solo se ci si fida di chi
lo ha scritto. Nella versione del Microsoft Store i moduli sono spenti.

Ogni errore di un modulo resta suo: modulo.json mancante o rovinato, versione di FreeLaserCut non adatta, errore
mentre si carica o dentro un comando → il modulo si ferma con un messaggio e una riga nel registro, il programma
continua come se non ci fosse.
"""
import importlib.util
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass

API = 1  # versione dell'interfaccia offerta ai moduli (classe Api)
FOLDER = "moduli"
MANIFEST = "modulo.json"
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")

LOADED = []  # Info dei moduli trovati all'ultimo load_all (caricati e no)


@dataclass
class Info:
    id: str
    name: str = ""
    version: str = ""
    path: str = ""
    author: str = ""
    description: str = ""
    loaded: bool = False
    error: str = ""  # perché non è stato caricato, o l'ultimo errore di un suo comando


def folder():
    """Cartella dei moduli (può non esistere). FLC_MODULI_DIR la sposta: serve alle prove."""
    env = os.environ.get("FLC_MODULI_DIR")
    if env:
        return env
    from .profile import config_dir

    return os.path.join(config_dir(), FOLDER)


def enabled(executable=None):
    """I moduli si caricano? No nella versione dello Store e con FLC_NO_MODULI=1."""
    if os.environ.get("FLC_NO_MODULI") == "1":
        return False
    from . import diag

    return "Store" not in diag.launch_kind(executable)


def _ver(text):
    return tuple(int(n) for n in re.findall(r"\d+", str(text or ""))[:4])


def read_manifest(path):
    """Info del modulo in quella cartella. Con `error` pieno il modulo non è valido e non si carica."""
    info = Info(id=os.path.basename(os.path.normpath(path)), path=path)
    try:
        with open(os.path.join(path, MANIFEST), encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("non è un oggetto")
    except OSError:
        info.error = f"manca {MANIFEST}"
        return info
    except ValueError as ex:
        info.error = f"{MANIFEST} rovinato ({ex})"
        return info
    info.name = str(data.get("nome") or info.id)
    info.version = str(data.get("versione") or "")
    info.author = str(data.get("autore") or "")
    info.description = str(data.get("descrizione") or "")
    mid = str(data.get("id") or "")
    if not _ID.match(mid) or mid != info.id:
        info.error = "identificativo non valido o diverso dal nome della cartella"
    elif data.get("api") != API:
        info.error = f"scritto per un'altra versione dell'interfaccia dei moduli ({data.get('api')!r}, qui {API})"
    elif not os.path.isfile(os.path.join(path, "__init__.py")):
        info.error = "manca __init__.py"
    else:
        from . import __version__

        lo, hi, here = _ver(data.get("flc_min")), _ver(data.get("flc_max")), _ver(__version__)
        if lo and here < lo:
            info.error = f"chiede FreeLaserCut {data.get('flc_min')} o più recente"
        elif hi and here > hi:
            info.error = f"non è stato provato oltre FreeLaserCut {data.get('flc_max')}"
    return info


def scan():
    """Info di ogni cartella trovata in «moduli», in ordine di nome."""
    root = folder()
    try:
        names = sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)) and not n.startswith(("_", ".")))
    except OSError:
        return []
    return [read_manifest(os.path.join(root, n)) for n in names]


def _log(text):
    try:
        from . import startup_guard

        with open(os.path.join(startup_guard.log_dir(), "moduli.log"), "a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n")
    except Exception:  # noqa: BLE001 - il registro non deve mai fermare il programma
        pass


class Api:
    """Quello che un modulo può fare. Piccola apposta: quello che non passa di qui può cambiare a ogni versione."""

    version = API

    def __init__(self, win, info):
        self.window = win
        self.info = info
        from . import __version__

        self.flc_version = __version__

    def add_translations(self, tables):
        """tables = {"en": {"testo italiano": "translation"}, "es": {...}, ...}: da chiamare prima di usare tr()."""
        from . import i18n

        i18n.extend(tables)

    def add_action(self, key, text, slot, icon=None, tip=None, menu="file", after=None, help=None, shortcut=None):  # noqa: A002
        """Aggiunge un comando: voce di menu (dopo il comando `after`, o in fondo), ricerca dei comandi, aiuto.
        help = (titolo, testo). Non può prendere il posto di un comando che c'è già. -> QAction"""
        win = self.window
        if key in win.acts:
            raise ValueError(f"il comando «{key}» c'è già")
        act = win._a(text, self._guard(slot, text), shortcut, icon, tip)
        win.acts[key] = act
        if help:
            from .ui import help_texts

            help_texts.HELP[key] = (help[0], help[1], None)
        m = {"file": "m_file", "laser": "m_laser", "help": "m_help"}.get(menu)
        m = getattr(win, m, None) if m else None
        if m is not None:
            acts = m.actions()
            ref = win.acts.get(after)
            before = acts[acts.index(ref) + 1] if ref in acts and acts.index(ref) + 1 < len(acts) else None
            if before is not None:
                m.insertAction(before, act)
            else:
                m.addAction(act)
        return act

    def _guard(self, slot, text):
        info = self.info

        def run(*_a):
            try:
                return slot()
            except Exception as ex:  # noqa: BLE001 - l'errore di un modulo non deve fermare il programma
                info.error = f"{type(ex).__name__}: {ex}"
                _log(f"[{info.id} {info.version}] {text}\n{traceback.format_exc()}")
                self._tell(f"{info.name}: {info.error}")
                return None

        return run

    def _tell(self, text):
        from .i18n import tr

        msg = tr("Modulo aggiuntivo, errore: {0}", text)
        try:
            self.window.statusBar().showMessage(msg, 12000)
            if not os.environ.get("FLC_NO_DIALOGS"):
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self.window, tr("Moduli aggiuntivi"), msg)
        except Exception:  # noqa: BLE001
            pass


def _name(info):
    return "flc_modulo_" + info.id.replace("-", "_")


def _forget(info):
    name = _name(info)
    for k in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
        del sys.modules[k]


def _import(info):
    name = _name(info)
    spec = importlib.util.spec_from_file_location(name, os.path.join(info.path, "__init__.py"),
                                                  submodule_search_locations=[info.path])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        _forget(info)
        raise
    return mod


def load_all(win):
    """Carica i moduli validi e chiama il loro registra(api). -> elenco di Info (anche di quelli non caricati)."""
    LOADED.clear()
    if not enabled():
        return LOADED
    for info in scan():
        LOADED.append(info)
        if info.error:
            _log(f"[{info.id}] non caricato: {info.error}")
            continue
        before = set(win.acts)
        try:
            mod = _import(info)
            mod.registra(Api(win, info))
            info.loaded = True
        except Exception as ex:  # noqa: BLE001 - un modulo che non parte non deve fermare il programma
            info.error = f"{type(ex).__name__}: {ex}"
            _log(f"[{info.id} {info.version}] non caricato\n{traceback.format_exc()}")
            _forget(info)
            from .ui import help_texts

            for k in set(win.acts) - before:  # niente comandi a metà
                act = win.acts.pop(k)
                help_texts.HELP.pop(k, None)
                for w in list(act.associatedObjects()):
                    w.removeAction(act)
                act.deleteLater()
    bad = [i for i in LOADED if not i.loaded]
    if bad:
        from .i18n import tr

        try:
            win.statusBar().showMessage(tr("Moduli aggiuntivi non caricati: {0}",
                                           ", ".join(f"{i.id} ({i.error})" for i in bad)), 15000)
        except Exception:  # noqa: BLE001
            pass
    return LOADED


def summary():
    """Una riga per i rapporti, o "" se non ci sono moduli."""
    if not LOADED:
        return ""
    return "Moduli aggiuntivi: " + ", ".join(
        f"{i.id} {i.version}".strip() + ("" if i.loaded else f" (non caricato: {i.error})") for i in LOADED)
