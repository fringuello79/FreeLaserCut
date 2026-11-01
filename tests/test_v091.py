# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.9.1: con la macchina connessa il pannello Laser non si allarga; dopo un lavoro, eliminando le forme
non resta nulla sul piano (anteprima e traccia del laser). Prova il flusso completo sul simulatore:
connessione, homing, verifica $C, lavoro, fine lavoro, eliminazione, annulla."""
import sys, os, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ.setdefault("FLC_SIM_GLITCH", "0")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox
from freelasercut.ui import style
from freelasercut.theme import QSS
app = QApplication([]); app.setStyle("Fusion"); style.load_fonts(); app.setFont(style.ui_font(9.5))
app.setStyleSheet(QSS + style.QSS_EXTRA)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
# finestra di avvio del lavoro: sceglie il primo pulsante («Verifica e avvia»)
QMessageBox.exec = lambda self: (setattr(self, "_auto", self.buttons()[0] if self.buttons() else None), 0)[1]
QMessageBox.clickedButton = lambda self: getattr(self, "_auto", None)
from freelasercut.grbl import SIM_PORT
from freelasercut.core.document import RectShape
from freelasercut.ui.main_window import MainWindow

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.005)
def wait(cond, t):
    e = time.time() + t
    while time.time() < e and not cond():
        spin(0.05)
    return cond()

ui = os.environ["FLC_UI"]
print(f"Interfaccia: {ui}")
w = MainWindow(); w.resize(1600, 980); w.show(); spin(0.8)
cv, ed, ctl = w.canvas, w.editor, w.ctl

# ------------------------------------------------------------------ connessione
w.port_combo.setCurrentIndex(w.port_combo.findData(SIM_PORT)); w.toggle_connection(quiet=True)
check("connessione al simulatore", wait(lambda: ctl.connected and ctl.last_status.get("state") == "Idle", 6))
widths = []
for _ in range(8):
    spin(0.5); widths.append((w.pill.minimumWidth(), w.laser.b_start.width(), w.docks["laser"].width()))
check("pastiglia di stato: larghezza ferma con gli aggiornamenti della macchina", len(set(widths)) == 1, str(widths[0]))
fm = w.pill.fontMetrics()
check("pastiglia di stato: il testo ci sta", w.pill.minimumWidth() >= fm.horizontalAdvance(w.pill.text()) + 16, w.pill.text())
ctl.home()
check("homing", wait(lambda: ctl.homed and ctl.last_status.get("state") == "Idle", 15))

# ------------------------------------------------------------------ lavoro completo
a, b = RectShape(80, 60), RectShape(60, 40)
a.x, a.y, b.x, b.y = 40, 40, 50, 50
ed.add([a, b]); spin(0.2)
check("due forme sul piano", len(ed.doc.shapes) == 2 and len(cv.items_by_id) == 2)
w.laser.verify_first.setChecked(True)
seen = {"check": False, "job": False, "stop": False}
def sample():
    seen["check"] |= ctl.checking; seen["job"] |= ctl.job_active; seen["stop"] |= w.laser.b_stop.isEnabled()
    return not ctl.checking and not ctl.job_active and "completato" in w.laser.eta.text()
ctl.check_finished.connect(lambda errs: seen.__setitem__("check", True))  # la verifica può durare pochi ms
w.start_job(); sample()
e = time.time() + 90
while time.time() < e and not sample():
    app.processEvents(); time.sleep(0.002)
ok = sample()
check("dopo l'avvio parte la verifica con la scheda, poi il lavoro", seen["check"] and seen["job"], str(seen))
check("Stop acceso durante il lavoro", seen["stop"])
check("verifica e lavoro arrivano alla fine", ok, w.laser.eta.text())
st0 = dict(ctl.last_status); p0 = tuple(st0.get("MPos", ())[:2])
spin(1.0)
p1 = tuple(ctl.last_status.get("MPos", ())[:2])
check("il lavoro risulta finito solo a testa ferma", st0.get("state") == "Idle" and p0 == p1, f"{st0.get('state')} {p0} -> {p1}")
check("a fine lavoro Stop si spegne e Avvia si riaccende", not w.laser.b_stop.isEnabled() and w.laser.b_start.isEnabled())
check("durante il lavoro il piano mostra la traccia del laser", not cv._trail_path.isEmpty())

# ------------------------------------------------------------------ eliminazione dopo il lavoro
w.build_job(); spin(0.1)
check("anteprima del lavoro sul piano", len(cv._preview_items) > 0)
ed.select_all(); ed.delete(); spin(0.3)
check("forme eliminate dal documento", len(ed.doc.shapes) == 0)
check("forme eliminate dal piano", len(cv.items_by_id) == 0)
check("livelli spariti dal pannello", w.layers.tree.topLevelItemCount() == 0)
check("anteprima del lavoro cancellata", len(cv._preview_items) == 0)
check("traccia del laser cancellata", cv._trail_path.isEmpty() and cv._trail_item.path().isEmpty(), f"job={ctl.job_active} check={ctl.checking} n={cv._trail_path.elementCount()}")
vis = [it for it in cv.scene().items() if it.isVisible() and it.zValue() >= 800 and hasattr(it, "path") and not it.path().isEmpty()]
check("sul piano non resta nessuna linea del lavoro", not vis, str(len(vis)))
ed.undo(); spin(0.3)
check("Annulla riporta le forme", len(ed.doc.shapes) == 2 and len(cv.items_by_id) == 2)

ctl.disconnect_port(); spin(0.3)
w.close(); spin(0.2)
print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
