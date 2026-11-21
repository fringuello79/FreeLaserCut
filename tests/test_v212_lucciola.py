# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: finestre chiuse che restavano attaccate ai segnali del programma (rapporti 75E8 di leone2805 e ABFC di
Daniel Z., 0.21.1: «Internal C++ object (PySide6.QtWidgets.QToolButton) already deleted» a ogni clic sulla Lucciola).

Causa: la croce delle frecce della finestra «Stampa e taglia» si collegava al pulsante Lucciola della scheda Laser con
una lambda. Chiusa la finestra, la lambda restava attaccata e chiamava pulsanti ormai distrutti. Lo stesso nella finestra
delle copie della scheda (`dialogs_backup.py`, rapporto 3802): lambda su `ctl.connection_changed`.
Correzione: collegamenti a metodi, che Qt stacca da solo quando l'oggetto sparisce; una prova che cerca lo stesso schema
in tutte le finestre.

Uso: python tests/test_v212_lucciola.py [classica|banco]
"""
import ast
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []
errors = []
sys.excepthook = lambda tp, ex, tb: errors.append(f"{tp.__name__}: {ex}")


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info else ""), flush=True)


def settle():
    for _ in range(5):
        app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def toggles(btn):
    """Gli stessi segnali di un clic sulla Lucciola, senza accendere il laser."""
    btn.toggled.emit(True)
    btn.toggled.emit(False)
    settle()


w = MainWindow()
w.show()
settle()
glow = w.laser.b_glow

print("--- Lucciola e Stampa e taglia")
toggles(glow)
check("prima: la Lucciola non dà errori", not errors, errors)
d = w.print_cut_dialog()
settle()
toggles(glow)
check("con Stampa e taglia aperta: nessun errore, la sua croce segue la Lucciola",
      not errors and d.pad.laser is w.laser, errors)
d.close()
settle()
check("chiusa la finestra viene distrutta (come nella 0.21.1)", w._print_cut_dlg is None)
toggles(glow)
check("dopo averla chiusa: nessun errore alla Lucciola (rapporti 75E8 e ABFC)", not errors, errors)
for _ in range(2):
    w.print_cut_dialog()
    settle()
    w._print_cut_dlg.close()
    settle()
toggles(glow)
check("aperta e chiusa altre due volte: ancora nessun errore", not errors, errors)
d = w.print_cut_dialog()
settle()
glow.toggled.emit(True)
settle()
check("riaperta: la croce nuova segue ancora la Lucciola", d.pad.b_glow.styleSheet() == d.pad._GLOW_ON_CSS or
      d.pad.b_glow.isChecked() == w.laser._glow_on, d.pad.b_glow.styleSheet())
glow.toggled.emit(False)
d.close()
settle()
toggles(w.move.pad.laser.b_glow)
check("la croce della scheda Movimento continua a funzionare", not errors and w.move.pad.laser is w.laser, errors)

print("--- copie delle impostazioni della scheda")
bd = w.board_backup_dialog()
settle()
w.ctl.connection_changed.emit(False, "")
settle()
check("finestra aperta: segue il collegamento senza errori", not errors, errors)
bd.close()
settle()
w.ctl.connection_changed.emit(True, SIM_PORT)
w.ctl.connection_changed.emit(False, "")
settle()
check("finestra chiusa e cambio di collegamento: nessun errore (rapporto 3802)", not errors, errors)

print("--- lo stesso schema nel resto del programma")
LONG = {"ctl", "main", "win", "laser"}  # oggetti che vivono più delle finestre che li usano


def root_name(node):
    while isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "self" and node.attr in LONG:
            return node.attr
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


found = []
ui = os.path.join(ROOT, "freelasercut", "ui")
for f in sorted(os.listdir(ui)):
    if not f.endswith(".py") or f == "main_window.py":  # lì «self» è la finestra principale: vive quanto ctl
        continue
    tree = ast.parse(open(os.path.join(ui, f), encoding="utf-8").read())
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "connect" and n.args
                and isinstance(n.args[0], ast.Lambda) and isinstance(n.func.value, ast.Attribute)
                and root_name(n.func.value.value) in LONG):
            found.append(f"{f}:{n.lineno}")
check("nessuna finestra collega lambda ai segnali di controllore, scheda Laser o finestra principale", not found, found)

w.editor.dirty = False
ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
