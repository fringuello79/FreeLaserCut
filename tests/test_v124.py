# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.12.4: pannello Laser → «Porta la testa qui»: la testa va, a laser spento, sul punto del disegno scelto
con i 9 pallini (com'è disegnato sul piano)."""
import sys, os, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.grbl import SIM_PORT
from freelasercut.core.document import RectShape

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()

from freelasercut.ui.main_window import MainWindow
w = MainWindow()
lp = w.laser
check("pulsante «Porta la testa qui» accanto ai 9 pallini, spento senza macchina", hasattr(lp, "b_goto_anchor") and
      not lp.b_goto_anchor.isEnabled())
lp.start_from.setCurrentIndex(lp.start_from.findData("absolute"))
check("in coordinate assolute i pallini restano attivi (servono al pulsante)", lp.anchor.isEnabled())
r = RectShape(20, 10)
r.apply(QTransform.fromTranslate(30, 40))
w.editor.doc.add(r)
r2 = RectShape(10, 10)
r2.apply(QTransform.fromTranslate(200, 200))
w.editor.doc.add(r2)
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings and w.canvas.head_pos() is not None)
check("connessi: pulsante attivo", lp.b_goto_anchor.isEnabled())
def head_at(x, y):
    return until(lambda: w.canvas.head_pos() is not None and abs(w.canvas.head_pos().x() - x) < 0.1 and
                 abs(w.canvas.head_pos().y() - y) < 0.1 and w.ctl.last_status.get("state") == "Idle", 10)
lp.anchor.value = 0
check("pallino in basso a sinistra: la testa va all'angolo in basso a sinistra di tutto il disegno",
      w.goto_anchor() == (30.0, 40.0) and head_at(30, 40), w.canvas.head_pos())
lp.anchor.value = 8
check("pallino in alto a destra: angolo in alto a destra (210, 210)", w.goto_anchor() == (210.0, 210.0) and head_at(210, 210))
lp.anchor.value = 4
lp.only_sel.setChecked(True)
w.editor.select([r])
check("«Solo gli oggetti selezionati»: centro della selezione (40, 45)", w.goto_anchor() == (40.0, 45.0) and head_at(40, 45))
check("la barra di stato dice dove va la testa", "al centro" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
sent = []
w.ctl.line_sent.connect(lambda l: sent.append(l))
lp.anchor.value = 6
w.goto_anchor()
check("lo spostamento è a laser spento (jog, nessun M3/M4)", until(lambda: sent, 3) and all(
    l.startswith("$J=") for l in sent), sent)
lp.only_sel.setChecked(False)
w.editor.select([])
w.ctl.disconnect_port()
check("senza macchina: nessun movimento, solo un messaggio", w.goto_anchor() is not None and
      "Connetti" in w.statusBar().currentMessage())
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
