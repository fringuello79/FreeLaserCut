# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.0 (richiesta di un utente Linux): la testa con la tastiera.

Alt+Maiusc+frecce = jog del passo scelto (anche con oggetti selezionati e con Stampa e taglia davanti), Alt+Maiusc+
PagSu/PagGiù = asse Z, Alt+1 … Alt+5 = passo (0,1 · 1 · 10 · 50 · 100 mm), Alt+Home = origine di lavoro, Ctrl+1 e
Ctrl+2 in Stampa e taglia = crocette. Niente movimenti senza laser o durante il lavoro; tasti tutti diversi.
Uso: python tests/test_v210_tastiera.py [classica|banco]
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(TMP, "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QAction, QKeySequence, QTransform  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core.document import Document, RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui import main_window as MW  # noqa: E402
from freelasercut.ui import shortcuts  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "")


def spin(t):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def until(cond, t=10.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        spin(0.03)
    return cond()


w = MW.MainWindow()
w.show()
w.activateWindow()
spin(0.3)
c = w.ctl
sent = []
c.line_sent.connect(sent.append)
jogs = lambda: [x for x in sent if x.startswith("$J=")]  # noqa: E731

print("--- senza laser")
check("i comandi ci sono, nel menu Laser → Muovi la testa con la tastiera",
      all(k in w.acts for k in ("kb_left", "kb_right", "kb_up", "kb_down", "kb_z_up", "kb_z_down", "kb_goto0",
                                "kb_step_1", "kb_step_5")) and w.m_kb.menuAction() in w.m_laser.actions())
check("tasti: Alt+Maiusc+frecce, Alt+Maiusc+PagSu/PagGiù, Alt+Home, Alt+1 … Alt+5",
      [w.acts[k].shortcut().toString() for k in ("kb_left", "kb_right", "kb_up", "kb_down", "kb_z_up", "kb_z_down",
                                                  "kb_goto0")]
      == ["Alt+Shift+Left", "Alt+Shift+Right", "Alt+Shift+Up", "Alt+Shift+Down", "Alt+Shift+PgUp", "Alt+Shift+PgDown",
          "Alt+Home"] and [w.acts[f"kb_step_{i}"].shortcut().toString() for i in range(1, 6)]
      == [f"Alt+{i}" for i in range(1, 6)])
check("valgono in tutte le finestre del programma e non si ripetono tenendo premuto",
      all(w.acts[k].shortcutContext() == Qt.ApplicationShortcut and not w.acts[k].autoRepeat()
          for k in w.acts if k.startswith("kb_")))
seen, dup = {}, []
for a in w.findChildren(QAction):
    for sc in a.shortcuts():
        t = sc.toString()
        if t in seen and seen[t] is not a:
            dup.append(t)
        seen[t] = a
check("nessun tasto usato da due comandi", not dup, dup)
check("senza laser collegato: niente movimento, lo dice", w.kb_jog(1, 0) is False and not jogs()
      and "collegato" in w.statusBar().currentMessage())
check("passo scelto anche senza laser: Alt+4 = 50 mm, ricordato", w.kb_step(50.0) and w.move.step() == 50.0
      and float(w.qs.value("jog_step")) == 50.0)

print("--- con il simulatore")
c.connect_port(SIM_PORT)
until(lambda: c.connected, 10)
spin(1.0)
c.home()
until(lambda: c.homed, 20)
spin(0.5)
w.kb_step(10.0)
sent.clear()
w.kb_jog(1, 0)
w.kb_jog(0, -1)
check("jog del passo scelto: destra 10 mm e giù 10 mm", until(lambda: len(jogs()) >= 2, 3)
      and "X10.000" in jogs()[0] and "Y-10.000" in jogs()[1], jogs())
w.kb_step(0.1)
sent.clear()
w.kb_jog(-1, 0)
check("passo 0,1 mm: sinistra 0,1", until(lambda: jogs(), 3) and "X-0.100" in jogs()[0], jogs())
doc = Document()
r = RectShape(30, 20, layer=1)
r.set_transform(QTransform.fromTranslate(50, 50))
doc.add(r)
w.editor.set_document(doc)
w.editor.select([r])
box0 = w.editor.doc.shapes[0].bounds() if hasattr(w.editor.doc.shapes[0], "bounds") else None
sent.clear()
w.kb_jog(0, 1)
check("con un oggetto selezionato la testa si muove lo stesso e l'oggetto resta dov'era",
      until(lambda: jogs(), 3) and "Y0.100" in jogs()[0]
      and (box0 is None or w.editor.doc.shapes[0].bounds() == box0))
sent.clear()
w.kb_step(1.0)
w.canvas.setFocus()
QTest.keyClick(w.canvas, Qt.Key_Right, Qt.AltModifier | Qt.ShiftModifier)
spin(0.3)
check("Alt+Maiusc+freccia dalla tastiera, con il piano attivo: jog di 1 mm", until(lambda: jogs(), 3)
      and "X1.000" in jogs()[0], jogs())
sent.clear()
QTest.keyClick(w.canvas, Qt.Key_5, Qt.AltModifier)
spin(0.2)
check("Alt+5 dalla tastiera: passo 100 mm", w.move.step() == 100.0)
w.kb_step(1.0)
sent.clear()
w.kb_goto0()
check("Alt+Home: all'origine di lavoro", until(lambda: jogs(), 3) and "X0 Y0" in jogs()[0], jogs())
w.profile.z_motor = False
sent.clear()
check("Z senza asse motorizzato: niente, lo dice", w.kb_jog_z(1) is False and not jogs()
      and "Z" in w.statusBar().currentMessage())
w.profile.z_motor = True
w.kb_jog_z(-1)
check("Z motorizzato: giù del passo (al massimo 10 mm)", until(lambda: jogs(), 3) and "Z-1.000" in jogs()[0], jogs())
w.profile.z_motor = False
c._job_active = True
sent.clear()
check("durante il lavoro: niente jog, niente origine, lo dice", w.kb_jog(1, 0) is False and w.kb_goto0() is False
      and not jogs() and "lavoro" in w.statusBar().currentMessage())
c._job_active = False

print("--- Stampa e taglia")
idle = lambda: str(c.last_status.get("state", "")).startswith("Idle")  # noqa: E731
until(idle, 10)
dlg = w.print_cut_dialog()
spin(0.5)
until(idle, 10)
dlg.refresh()
check("Stampa e taglia: Ctrl+1 e Ctrl+2 sulle crocette, spiegati nella finestra",
      [s.key().toString() for s in dlg.kb_take] == ["Ctrl+1", "Ctrl+2"]
      and "Ctrl+1" in dlg.b_take[0].toolTip(), (dlg.b_take[0].toolTip(), c.last_status.get("state")))
dlg.pad.set_step(10.0)
w.move.pad.set_step(1.0)
dlg.activateWindow()
spin(0.3)
sent.clear()
if dlg.isActiveWindow():
    w.kb_jog(1, 0)
    ok = until(lambda: jogs(), 3) and "X10.000" in jogs()[0]
else:  # senza gestore delle finestre la finestra può non diventare attiva: si prova il passo direttamente
    dlg.jog(1, 0)
    ok = until(lambda: jogs(), 3) and "X10.000" in jogs()[0]
check("con Stampa e taglia davanti il jog usa il passo scelto lì", ok, jogs())
w.kb_step(50.0)
check("Alt+1 … Alt+5 cambiano il passo anche in Stampa e taglia", dlg.pad.step() == 50.0 and w.move.step() == 50.0)
until(idle, 10)
spin(0.5)
until(idle, 10)
dlg.kb_take[0].activated.emit()
check("Ctrl+1 senza crocette sul disegno: non prende niente e lo dice", dlg.pts[0] is None and dlg.msg.text())
dlg.add_marks()
until(idle, 10)
spin(0.3)
dlg.kb_take[0].activated.emit()
check("Ctrl+1: crocetta 1 presa nel punto della testa", dlg.pts[0] is not None, (dlg.msg.text(), c.last_status))
dlg.kb_take[1].activated.emit()
check("Ctrl+2: crocetta 2 presa", dlg.pts[1] is not None)
dlg.close()
spin(0.3)

print("--- elenco delle scorciatoie e traduzioni")
html, _n = shortcuts.to_html("Alt+1")
check("l'elenco delle scorciatoie (F1) le spiega", "0,1 · 1 · 10 · 50 · 100" in html
      and "Alt+Home" in shortcuts.to_html("Alt+Home")[0])
import json  # noqa: E402

keys = ["Muovi la testa con la tastiera", "Testa a sinistra di un passo", "Passo del jog: {0:g} mm",
        "Durante il lavoro la testa non si muove con la tastiera", "Testa all'origine di lavoro (X0 Y0)",
        "Questo laser non ha l'asse Z motorizzato (Laser → profilo)", "Scorciatoia: Ctrl+{0}",
        "Con la tastiera: Alt+Maiusc+frecce muovono la testa, Alt+1 … Alt+5 scelgono il passo "
        "(0,1 · 1 · 10 · 50 · 100 mm), Ctrl+1 e Ctrl+2 prendono le crocette.", "Prima metti le due crocette"]
missing = []
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    missing += [(lang, k) for k in keys if not cat.get(k)]
check("le voci nuove ci sono nelle 4 lingue", not missing, missing[:4])
c.disconnect_port()
spin(0.3)
ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
