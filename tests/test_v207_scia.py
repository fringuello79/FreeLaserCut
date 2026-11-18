# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.7 (Ale, 18/11/2026): la scia dell'incisione (il tracciato arancione di quello che il laser ha già inciso, che
compare sul piano durante il lavoro) si può spegnere, e non si vede più guardando un altro piano.

Casi: comando «Scia dell'incisione sul piano» nel menu Visualizza (acceso di partenza, ricordato fra un avvio e
l'altro, con la sua scheda d'aiuto); accesa: la scia raccoglie i punti a laser acceso e si ridisegna al massimo 4 volte
al secondo (non a ogni stato della macchina); spenta: niente punti raccolti e niente disegnato, la scia di prima
sparisce; mentre il laser incide il piano A e si guarda il piano B con «Mostra gli altri piani» spento, anteprima e
scia del lavoro non si vedono; con gli altri piani accesi, tornando sul piano A o a lavoro finito si rivedono.
Uso: python tests/test_v207_scia.py [classica|banco]
"""
import json
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
from freelasercut import grbl  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "", flush=True)


def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.005)


FAKE = {"job": False}
grbl.GrblController.job_active = property(lambda self: FAKE["job"])  # lavoro «in corso» senza laser

w = MainWindow()
w.resize(1400, 900)
w.show()
spin(0.3)
cv, ed = w.canvas, w.editor
act = w.acts["show_trail"]

print("--- comando")
view = w.m_view.actions()
check("«Scia dell'incisione sul piano» nel menu Visualizza, dopo il dithering, acceso di partenza",
      act in view and view.index(act) == view.index(w.acts["dither_prev"]) + 1 and act.isCheckable() and act.isChecked()
      and cv.show_trail)
check("scheda d'aiuto che spiega a che serve spegnerla", "show_trail" in help_texts.HELP
      and "rallenta" in help_texts.HELP["show_trail"][1] and "altro piano" in help_texts.HELP["show_trail"][1])

print("--- accesa: punti raccolti, ridisegno al massimo 4 volte al secondo")
calls = []
orig = cv._trail_item.setPath
cv._trail_item.setPath = lambda p: (calls.append(p.elementCount()), orig(p))[1]
cv.clear_trail()
calls.clear()
t0 = time.time()
for i in range(400):
    cv.set_head(10 + i * 0.1, 20, "Run", 500)
check("400 stati a laser acceso: tutti i punti nella scia", cv._trail_path.elementCount() == 400, cv._trail_path.elementCount())
check("…ma nessun ridisegno immediato (prima: 400)", len(calls) == 0, len(calls))
spin(0.4)
check("entro un quarto di secondo la scia sul piano è aggiornata, con un ridisegno solo",
      len(calls) == 1 and cv._trail_item.path().elementCount() == 400 and cv._trail_item.isVisible(), calls)
cv.set_head(60, 20, "Run", 0)
cv.set_head(70, 20, "Run", 500)
spin(0.4)
check("laser spento in mezzo: la scia riparte da un punto nuovo (non unisce il tratto spento)",
      cv._trail_path.elementCount() == 401 and cv._trail_path.elementAt(400).isMoveTo())
cv.set_head(80, 20, "Idle", 500)
check("macchina ferma: niente punti", cv._trail_path.elementCount() == 401)
_ = t0

print("--- spenta")
act.trigger()
check("spenta: la scia di prima sparisce e la scelta è salvata", not act.isChecked() and not cv.show_trail
      and cv._trail_path.isEmpty() and cv._trail_item.path().isEmpty() and not cv._trail_item.isVisible()
      and w.qs.value("show_trail") in (False, "false"))
calls.clear()
for i in range(300):
    cv.set_head(10 + i * 0.1, 30, "Run", 500)
spin(0.4)
check("spenta: nessun punto raccolto e nessun ridisegno durante il lavoro", cv._trail_path.isEmpty() and not calls,
      (cv._trail_path.elementCount(), len(calls)))
check("la testa del laser si vede e si muove lo stesso", cv._head.isVisible() and abs(cv._head.pos().x() - 39.9) < 1e-6)
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
spin(0.1)
w2 = MainWindow()
check("al riavvio resta spenta", not w2.acts["show_trail"].isChecked() and not w2.canvas.show_trail)
w2.acts["show_trail"].trigger()
check("riaccesa: si rivede e raccoglie di nuovo", w2.canvas.show_trail and w2.canvas._trail_item.isVisible())
w2.canvas.set_head(5, 5, "Run", 300)
w2.canvas.set_head(6, 5, "Run", 300)
check("…punti di nuovo raccolti", w2.canvas._trail_path.elementCount() == 2)
w2.editor.dirty = False
w2.qs.setValue("autosave_pending", False)
w2.close()
w = w2
w.show()
spin(0.2)
cv, ed = w.canvas, w.editor

print("--- altri piani")
r = RectShape(40, 30)
r.x, r.y = 30, 30
ed.add([r])
w.build_job()
spin(0.1)
check("anteprima del lavoro sul piano A", len(cv._preview_items) > 0 and all(it.isVisible() for it in cv._preview_items))
uid_a = ed.doc.plate.uid
FAKE["job"] = True
w._job_plate = uid_a  # come in _run: il laser incide il piano A
cv.set_job_overlay(True)
cv.set_head(30, 30, "Run", 500)
cv.set_head(70, 30, "Run", 500)
spin(0.4)
ghosts = w.plate_bar.ghosts
ghosts.setChecked(False)
ed.add_plate()
spin(0.1)
check("guardo il piano B, «Mostra gli altri piani» spento: anteprima e scia del lavoro non si vedono",
      ed.doc.plate.uid != uid_a and not cv._trail_item.isVisible()
      and cv._preview_items and not any(it.isVisible() for it in cv._preview_items))
cv.set_head(80, 30, "Run", 500)
check("…ma la scia continua a raccogliere i punti (tornando si vede tutta)", cv._trail_path.elementCount() == 3)
ghosts.setChecked(True)
spin(0.1)
check("«Mostra gli altri piani» acceso: si rivedono (come riferimento)",
      cv._trail_item.isVisible() and all(it.isVisible() for it in cv._preview_items))
ghosts.setChecked(False)
spin(0.1)
check("…e rispento: spariscono di nuovo", not cv._trail_item.isVisible())
ed.set_plate(ed.doc.plate_index(uid_a))
spin(0.1)
check("tornato sul piano A: anteprima e scia di nuovo visibili, con i punti presi intanto",
      cv._trail_item.isVisible() and all(it.isVisible() for it in cv._preview_items)
      and cv._trail_path.elementCount() == 3)
ed.set_plate(1 - ed.doc.plate_index(uid_a))
spin(0.1)
check("di nuovo sul piano B: nascoste", not cv._trail_item.isVisible())
FAKE["job"] = False
w._job_finished(True, "Lavoro completato")
spin(0.1)
check("lavoro finito: niente più da nascondere, anche restando sul piano B", cv.job_overlay_shown()
      and cv._trail_item.isVisible())
check("senza lavoro in corso cambiare piano non nasconde niente", w._update_job_overlay() is True)
act2 = w.acts["show_trail"]
act2.trigger()
ed.set_plate(ed.doc.plate_index(uid_a))
spin(0.1)
check("scia spenta: resta spenta anche tornando sul piano del lavoro", not cv._trail_item.isVisible()
      and all(it.isVisible() for it in cv._preview_items))
act2.trigger()

print("--- traduzioni")
missing = []
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    for key in ("Scia dell'incisione sul piano",):
        if not cat.get(key):
            missing.append((lang, key))
check("il comando c'è nelle 4 lingue", not missing, missing)

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
ok = sum(results)
print(f"\n{ok}/{len(results)} superati", flush=True)
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
