# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.5: pacchetto per i Mac Intel con macOS 13 Ventura (pull request #29 di istevenep) e le correzioni che
servono con le sue librerie (PySide6 6.9.3, Python 3.13, OpenCV 4.11, senza numba).

Provato facendo girare tutte le prove con quelle librerie:
- con PySide6 6.9 chiedere a un'azione il suo menu e poi lasciar andare l'azione rendeva il menu inservibile
  («Internal C++ object (QMenu) already deleted»): ora le azioni restano vive, solo con PySide6 più vecchio della 6.10;
- ogni tanto un evento arrivava ai filtri di eventi con il tipo sbagliato (per esempio come QStandardItem) e
  chiedergli il tipo faceva chiudere il programma (guida «Che cos'è?», nesting manuale, piano del Banco): ora i
  filtri lasciano passare tutto quello che non è un evento;
- senza numba (tutti i Mac Intel) la linea centrale di Vettorizza restava vuota: i booleani di numpy sommati fanno «o».

Uso: python tests/test_v225_qt69.py [classica|banco]
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


import cv2  # noqa: E402
import numpy as np  # noqa: E402
import PySide6  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QWidget  # noqa: E402

app = QApplication([])
from freelasercut import ui  # noqa: E402

ver = tuple(int(x) for x in PySide6.__version__.split(".")[:2])

# ====================================================================== A. correzione dei menu
if ver >= (6, 10):
    check("A PySide6 recente: la correzione dei menu non si attiva (niente cambia per le versioni normali)",
          ui.QT69_MENU_FIX is False and not getattr(QAction, "_flc_menu_fix", False))
    PySide6.__version__ = "6.9.3"  # da qui come nel pacchetto per Ventura
    applied = ui._qt69_menu_fix()
    PySide6.__version__ = ".".join(map(str, ver)) + ".0"
else:
    applied = ui.QT69_MENU_FIX
check("A PySide6 6.9: la correzione si attiva", applied is True and getattr(QAction, "_flc_menu_fix", False))
check("A attivata una volta sola", ui._qt69_menu_fix() is False)
w = QWidget()
bar_menu = QMenu("Prova", w)
bar_menu.addAction("uno")
holder = QMenu(w)
act = holder.addMenu(bar_menu)
m = act.menu()
check("A QAction.menu() dà sempre lo stesso menu", m is bar_menu and len(m.actions()) == 1)
check("A l'azione e il suo menu restano tenuti", any(v[1] is bar_menu for v in QAction._flc_menu_tenute.values()))
check("A un'azione senza menu: None, niente tenuto in più", QAction("x").menu() is None)

# ====================================================================== B. filtri di eventi
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtGui import QStandardItem  # noqa: E402

from freelasercut.ui import help_mode, nest_manual  # noqa: E402

hm = help_mode.HelpMode(QWidget())


class Strano(QStandardItem):
    """Come arrivava con PySide6 6.9: un QStandardItem al posto dell'evento. Chiedergli il tipo chiudeva il programma:
    qui dà un errore, così si vede se il filtro glielo chiede."""

    def type(self):
        raise RuntimeError("tipo chiesto a un oggetto che non è un evento")


strano = Strano("non sono un evento")
check("B guida «Che cos'è?»: un «evento» che non è un evento passa senza toccarlo",
      hm.eventFilter(QWidget(), strano) is False)
check("B guida: gli eventi veri come prima (Maiusc+F1 la accende)", hm.eventFilter(QWidget(), QEvent(QEvent.Type.None_))
      is False)
src_nm = open(nest_manual.__file__, encoding="utf-8").read()
src_bn = open(os.path.join(ROOT, "freelasercut", "ui", "banco.py"), encoding="utf-8").read()
check("B nesting manuale e piano del Banco: stesso controllo prima di chiedere il tipo dell'evento",
      "if not isinstance(ev, QEvent):" in src_nm and "not isinstance(e, QEvent)" in src_bn)

# ====================================================================== C. linea centrale senza numba
from freelasercut.core import geom, trace  # noqa: E402

img = np.full((200, 400), 255, np.uint8)
cv2.line(img, (40, 100), (360, 100), 0, 14)
m = trace.mask_of(1 - img.astype(np.float32) / 255, 0.5)
pyf = getattr(trace._thin, "py_func", trace._thin)  # la funzione Python, come gira senza numba
a = np.pad(m.astype(np.uint8), 1)
b = a.copy()
pyf(a)
trace._thin(b)
check("C assottigliamento senza numba: stesso scheletro che con numba", np.array_equal(a, b), (int(a.sum()), int(b.sum())))
check("C lo scheletro di un tratto spesso è una linea, non qualche punto", 280 < int(a.sum()) < 340, int(a.sum()))
path, info = trace.trace(1 - img.astype(np.float32) / 255, 40, 20, "centerline")
L = sum(p.length() for p in geom.flatten(path, 0.01))
check("C Vettorizza → Linea centrale: una linea lunga come il tratto", info["curves"] == 1 and abs(L - 31.4) < 1.5, L)

# ====================================================================== D. il pacchetto per Ventura
sys.path.insert(0, os.path.join(ROOT, "build"))
import prepara_mac as pm  # noqa: E402

check("D opzione --ventura: macOS 13, Qt 6.9.3, Python 3.13", pm.VENTURA_MIN_MACOS == "13.0"
      and pm.VENTURA_QT == "6.9.3" and pm.VENTURA_PYTHON.startswith("3.13"))
check("D istruzioni in build/, non nel sito", os.path.exists(os.path.join(ROOT, "build", "ISTRUZIONI-VENTURA.md"))
      and not os.path.exists(os.path.join(ROOT, "docs", "ISTRUZIONI-VENTURA.md")))
txt = open(os.path.join(ROOT, "build", "ISTRUZIONI-VENTURA.md"), encoding="utf-8").read()
check("D istruzioni senza la patch da applicare a mano, con il grazie a istevenep", "git apply" not in txt
      and "istevenep" in txt)
from freelasercut import thanks  # noqa: E402

check("D istevenep fra i ringraziamenti", "istevenep" in thanks.NAMES)

# ====================================================================== E. difetti rimessi apposta
caught = []
src = open(os.path.join(ROOT, "freelasercut", "core", "trace.py"), encoding="utf-8").read()
broken = src.replace("int(p2 == 0 and p3 == 1)", "(p2 == 0 and p3 == 1)").replace(
    "int(p3 == 0 and p4 == 1)", "(p3 == 0 and p4 == 1)").replace("int(", "(")
ns = {}
exec(compile(broken.split("_NB = [")[0].replace("@njit(cache=True)", ""), "trace_rotto", "exec"), ns)  # 1. senza int()
c = np.pad(m.astype(np.uint8), 1)
ns["_thin"](c)
caught.append(int(c.sum()) < 50)
orig_ef = help_mode.HelpMode.eventFilter
src_hm = open(help_mode.__file__, encoding="utf-8").read().replace("if not isinstance(ev, QEvent):", "if False:")
ns2 = {}
try:  # 2. filtro senza il controllo: con un «evento» sbagliato si rompe (in Python un errore, in PySide6 6.9 la chiusura)
    ns2.update({"__name__": "freelasercut.ui.help_mode_rotto", "__package__": "freelasercut.ui"})
    exec(compile(src_hm, help_mode.__file__, "exec"), ns2)
    ns2["HelpMode"](QWidget()).eventFilter(QWidget(), strano)
    caught.append(False)
except (AttributeError, TypeError, ImportError, RuntimeError):
    caught.append(True)
check("E difetti rimessi apposta (somma di booleani, filtro senza controllo): visti", all(caught), caught)

print(f"\n{sum(results)}/{len(results)} prove superate")
os._exit(0 if all(results) else 1)
