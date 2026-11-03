# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.12.3: cambiando il punto di riferimento (9 pallini) o la partenza, l'anteprima sul piano si sposta
subito; puntino fino al 20% con un avviso chiaro quando si supera il 5%."""
import sys, os, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ.pop("FLC_SIM_NEGATIVE", None)
os.environ.pop("FLC_NO_DIALOGS", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
answers, shown = [], []
def fake_exec(self):
    shown.append(self.text())
    want = answers.pop(0) if answers else False
    btn = self.buttons()[0] if want else self.buttons()[-1]  # primo = «Sì, uso…», ultimo = «No, resto al 5%»
    self._clicked = btn
    return 0
QMessageBox.exec = fake_exec
QMessageBox.clickedButton = lambda self: getattr(self, "_clicked", None)
from freelasercut.grbl import SIM_PORT, POINTER_MAX
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
r = RectShape(20, 10)
r.apply(QTransform.fromTranslate(30, 40))
w.editor.doc.add(r)
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings and w.canvas.head_pos() is not None)
w.ctl.goto_machine(200, 150, 6000)
until(lambda: w.canvas.head_pos() is not None and abs(w.canvas.head_pos().x() - 200) < 0.1 and
      w.ctl.last_status.get("state") == "Idle", 10)
lp = w.laser
lp.start_from.setCurrentIndex(lp.start_from.findData("current"))
check("partenza «posizione della testa»: l'anteprima compare sulla testa", until(lambda: w.job is not None, 3) and
      w.job.bounds is not None and abs(w.job.bounds.left() - 200) < 0.5 and abs(w.job.bounds.top() - 150) < 0.5,
      w.job.bounds if w.job else None)
lp.anchor.value = 8  # alto a destra
lp.anchor.changed.emit(8)
check("punto di riferimento in alto a destra: l'anteprima si sposta subito, l'angolo alto-destra sulla testa",
      until(lambda: w.job is not None and abs(w.job.bounds.right() - 200) < 0.5, 3) and
      abs(w.job.bounds.bottom() - 150) < 0.5, w.job.bounds)
lp.anchor.value = 4
lp.anchor.changed.emit(4)
check("al centro: il centro del lavoro sulla testa", until(lambda: abs(w.job.bounds.center().x() - 200) < 0.5, 3) and
      abs(w.job.bounds.center().y() - 150) < 0.5, w.job.bounds)
check("la barra di stato dice dove va il lavoro", "al centro" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
lp.start_from.setCurrentIndex(lp.start_from.findData("absolute"))
check("tornando alle coordinate assolute il lavoro torna dove lo vedi", until(lambda: abs(w.job.bounds.left() - 30) < 0.5, 3),
      w.job.bounds)

# ================================================================== puntino fino al 20 %
check("puntino: massimo 20%", lp.fire_pct.maximum() == POINTER_MAX == 20.0)
lp.fire_pct.setValue(3.0)
shown.clear()
answers[:] = [False]
lp.fire_pct.setValue(8.0)
check("oltre il 5%: avviso; rispondendo «No» resta al 5%", shown and "5%" in shown[0] and lp.fire_pct.value() == 5.0,
      lp.fire_pct.value())
check("l'avviso spiega il rischio (segna, brucia, occhiali, 20 secondi, contorno)", shown and all(
    k in shown[0] for k in ("brucia", "450 nm", "20 secondi", "Contorno")))
answers[:] = [True]
lp.fire_pct.setValue(12.0)
check("rispondendo «Sì» resta al 12% e il campo diventa arancione", lp.fire_pct.value() == 12.0 and
      "FFB020" in lp.fire_pct.styleSheet().upper())
n = len(shown)
lp.fire_pct.setValue(15.0)
check("salendo ancora (già sopra il 5%) non lo richiede di nuovo", len(shown) == n)
sent = []
w.ctl.line_sent.connect(lambda l: sent.append(l))
lp.fire_changed(True)
check("il puntino al 15% manda davvero S150 (scala 0–1000)", until(lambda: any(l.startswith("M3 S150") for l in sent), 3), sent[:3])
lp.fire_changed(False)
lp.fire_pct.setValue(3.0)
check("tornando sotto il 5%: colore normale", lp.fire_pct.styleSheet() == "")
from freelasercut.ui.panels_machine import PointerDialog
d = PointerDialog(w.ctl, 4.9, 1000, w)
answers[:] = [False]
d._step(0.2)
check("«Regola il puntino»: anche qui oltre il 5% chiede conferma (No → resta al 4,9%)", d.pct == 4.9 and len(shown) == n + 1)
answers[:] = [True]
d._step(0.2)
check("…con «Sì» sale al 5,1% e si può arrivare al 20%", d.pct == 5.1 and (setattr(d, "pct", 19.9), d._step(0.5), d.pct)[2] == 20.0)
d.reject()
w.ctl.disconnect_port()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
