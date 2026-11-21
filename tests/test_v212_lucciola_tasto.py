# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: Lucciola dalla tastiera, Alt+Maiusc+L (richiesta di un amico di Ale che usa un comando a distanza con le
scorciatoie della 0.21.0). Alt+L resta al menu Laser.

Fa esattamente quello che fa il pulsante della scheda Laser: stessa potenza con il tetto del laser, stessi controlli,
pulsante che segue; niente raggio senza macchina, durante un lavoro o in allarme; Stop la spegne; vale anche con la
finestra Stampa e taglia davanti.
Uso: python tests/test_v212_lucciola_tasto.py [classica|banco]
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info else ""), flush=True)


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def until(fn, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        spin(0.02)
    return bool(fn())


w = mw.MainWindow()
w.show()
spin(0.2)
act = w.acts.get("kb_glow")
lz = w.laser
check("comando «Lucciola: accendi / spegni» con Alt+Maiusc+L, valido in tutte le finestre",
      act is not None and act.shortcut() == QKeySequence("Alt+Shift+L") and act.shortcutContext() == Qt.ApplicationShortcut
      and not act.autoRepeat(), act and act.shortcut().toString())
check("nel menu «Muovi la testa con la tastiera», con la sua scheda d'aiuto", act in w.m_kb.actions() and "kb_glow" in help_texts.HELP)
taken = [k for k, a in w.acts.items() if k != "kb_glow" and a.shortcut() == act.shortcut()]
mnem = [m.title() for m in w.menuBar().findChildren(type(w.m_kb)) if "&L" in m.title()]
check("nessun altro comando usa Alt+Maiusc+L (Alt+L resta alla lettera del menu Laser)", not taken, taken)

print("--- senza macchina")
sent = []
w.ctl.line_sent.connect(sent.append)
act.trigger()
spin(0.1)
check("non collegata: niente raggio, il motivo nella barra", not lz._glow_on and not lz.b_glow.isChecked()
      and "collegato" in w.statusBar().currentMessage(), w.statusBar().currentMessage())

w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.board_settings.get(130) is not None, 8)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
spin(0.3)
print("--- accesa e spenta")
lz.glow_pct.setValue(50.0)  # più del tetto: deve restare sotto
del sent[:]
on = act.trigger() or lz._glow_on
spin(0.3)
cap = lz.glow_cap
fires = [s for s in sent if s.startswith(("M3", "M4")) or " S" in s]
check("Alt+Maiusc+L accende: il pulsante della scheda Laser segue", lz._glow_on and lz.b_glow.isChecked(), sent[-3:])
check("potenza mai oltre il tetto del laser", w.ctl.fire_active and w.ctl.sim.power <= lz.s_max * cap / 100.0 + 0.5,
      (w.ctl.sim.power, cap, lz.s_max))
if w.move.pad.laser is lz:
    check("…e anche il pulsante della croce delle frecce", w.move.pad.b_glow.styleSheet() == w.move.pad._GLOW_ON_CSS or
          w.move.pad.b_glow.isChecked())
act.trigger()
spin(0.3)
check("di nuovo Alt+Maiusc+L: spenta, raggio a zero, pulsante spento", not lz._glow_on and not lz.b_glow.isChecked()
      and not w.ctl.fire_active and w.ctl.sim.power == 0, w.ctl.sim.power)

print("--- Stop, allarme, lavoro")
act.trigger()
spin(0.3)
w.ctl.stop_job()
check("Stop la spegne", until(lambda: not lz._glow_on and not lz.b_glow.isChecked(), 3) and w.ctl.sim.power == 0)
until(lambda: w.ctl.last_status.get("state") in ("Idle", "Alarm"), 5)
w.ctl.sim.state = "Alarm"
until(lambda: w.ctl.last_status.get("state") == "Alarm", 3)
act.trigger()
spin(0.2)
check("in allarme: niente raggio, il motivo nella barra", not lz._glow_on and w.ctl.sim.power == 0
      and "allarme" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
w.ctl.sim.state = "Idle"
until(lambda: w.ctl.last_status.get("state") == "Idle", 3)
real = w.ctl.job_active
type(w.ctl).job_active = property(lambda self: True)
try:
    act.trigger()
    spin(0.1)
    check("durante un lavoro: niente raggio", not lz._glow_on)
finally:
    del type(w.ctl).job_active
    w.ctl.job_active = real

print("--- con Stampa e taglia davanti")
d = w.print_cut_dialog()
spin(0.3)
d.activateWindow()
act.trigger()
spin(0.3)
check("con la finestra Stampa e taglia aperta accende lo stesso, e la sua croce segue", lz._glow_on and d.pad.laser is lz)
act.trigger()
spin(0.2)
check("…e la spegne", not lz._glow_on and w.ctl.sim.power == 0)
d.close()
spin(0.2)
w.ctl.disconnect_port()

w.editor.dirty = False
ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
