# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.0 (richiesta di un utente Linux): ripresa del lavoro.

- Il lavoro in corso va sul disco (core/job_save.py): G-code e scheda con la riga raggiunta, aggiornata ogni 2 s;
  finito bene si cancella, fermato o interrotto resta. Riaprendo il programma (corrente mancata anche al PC) lo
  propone: «Riprendi» dopo l'homing, «Scarta» lo cancella. Un file cambiato o rovinato non si riprende.
- «Parti da qui…» nell'anteprima: il lavoro parte dal punto del cursore del tempo.
Uso: python tests/test_v210_ripresa.py [classica|banco]
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
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
asked = []
QMessageBox.question = staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.Ok)
from freelasercut import gcode_preview  # noqa: E402
from freelasercut.core import job_save, resume  # noqa: E402
from freelasercut.core.document import Document, RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.profile import config_dir  # noqa: E402
from freelasercut.ui.dialogs import PreviewDialog  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

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


print("--- il lavoro sul disco")
d = tempfile.mkdtemp()
L = ["G90 G21", "M4 S0", "G0 X1 Y1", "G1 X5 Y1 S300 F1000", "G1 X5 Y5", "M5 S0"]
card = job_save.start(d, L, plate="p1", name="prova")
check("all'avvio: G-code e scheda sul disco, riga raggiunta 0", card and card["lines"] == 6 and card["acked"] == 0
      and os.path.exists(os.path.join(d, job_save.GCODE)) and job_save.load(d) is None)
job_save.progress(d, card, 3)
got = job_save.load(d)
check("riga raggiunta aggiornata: il lavoro si riprende con le stesse righe", got is not None and got[0] == L
      and got[1] == 3 and got[2]["plate"] == "p1")
with open(os.path.join(d, job_save.GCODE), "a", encoding="utf-8") as fh:
    fh.write("G1 X99\n")
check("G-code cambiato o rovinato: non si riprende", job_save.load(d) is None)
job_save.start(d, L)
job_save.progress(d, job_save.start(d, L), 6)
check("riga raggiunta alla fine o oltre: niente da riprendere", job_save.load(d) is None)
with open(os.path.join(d, job_save.CARD), "w", encoding="utf-8") as fh:
    fh.write("{rotto")
check("scheda rovinata: niente da riprendere, nessun errore", job_save.load(d) is None)
job_save.clear(d)
check("cancellato: niente file", not os.listdir(d))
check("cartella che non si può scrivere: niente errori", job_save.start(os.path.join(d, "\0x"), L) is None)

print("--- nel programma, con il simulatore")
w = MainWindow()
spin(0.8)
c = w.ctl
c.connect_port(SIM_PORT)
until(lambda: c.connected, 10)
spin(1.0)
c.home()
until(lambda: c.homed, 20)
spin(0.5)
doc = Document()
cs = doc.layer(1)
cs.mode, cs.speed, cs.power_max, cs.passes = "line", 600.0, 10.0, 3
for i in range(24):
    r = RectShape(20, 20, layer=1)
    r.set_transform(QTransform.fromTranslate(10 + (i % 6) * 25, 30 + (i // 6) * 25))
    doc.add(r)
w.editor.set_document(doc)
job = w.build_job()
check("lavoro di prova pronto", job is not None and len(job.lines) > 30)
w.JOB_SAVE_MS = 200
c.sim.speedup = 3
w._run(job.lines, w.editor.doc.plate.uid)
until(lambda: c.job_acked > 80, 30)
spin(0.6)
got = job_save.load(config_dir())
check("durante il lavoro: G-code e riga raggiunta sul disco", got is not None and got[0] == list(c.job_lines)
      and got[1] > 0, got and got[1])
c.disconnect_port()  # la corrente manca al laser
until(lambda: not c.connected, 5)
spin(0.5)
got = job_save.load(config_dir())
check("laser spento a metà: in memoria e sul disco la stessa riga", w._interrupted is not None and got is not None
      and got[1] == w._interrupted[1], (w._interrupted and w._interrupted[1], got and got[1]))
at_disk = got[1]
w.close()
spin(0.3)

print("--- riaperto il programma (corrente mancata anche al PC)")
w2 = MainWindow()
spin(1.0)
check("lo propone: «non è finito», riga e totale, con Scarta", w2._interrupted is not None
      and w2._interrupted[1] == at_disk and "non è finito" in w2.banner_text.text(), w2.banner_text.text())
c2 = w2.ctl
c2.connect_port(SIM_PORT)
until(lambda: c2.connected, 10)
spin(3.0)
check("collegato il laser: «Riprendi» come per un'interruzione", w2._interrupted is not None)
c2.home()
until(lambda: c2.homed, 20)
spin(0.5)
c2.sim.speedup = 40
asked.clear()
w2.resume_job()
check("Riprendi: riparte poco prima della riga raggiunta, con lo stato ricostruito", c2.job_active
      and asked and "Riprendo dalla riga {0} di".format(at_disk - 40 + 1) in asked[-1]
      and len(c2.job_lines) < len(job.lines),
      (c2.job_active, c2.job_lines[:1], asked[-1:]))
done = {}
c2.job_finished.connect(lambda ok, msg: done.update(ok=ok))
until(lambda: "ok" in done, 60)
spin(0.5)
check("finita la ripresa: il lavoro salvato si cancella", done.get("ok") and job_save.load(config_dir()) is None
      and not os.path.exists(os.path.join(config_dir(), job_save.CARD)))

print("--- Scarta")
job_save.progress(config_dir(), job_save.start(config_dir(), job.lines), 10)
w2._interrupted = None
check("un lavoro salvato si ripropone", w2._offer_saved_job() == 10)
w2._drop_interrupted()
check("Scarta: cancellato anche dal disco", job_save.load(config_dir()) is None and w2._interrupted is None)

print("--- Parti da qui (anteprima)")
pv = gcode_preview.parse(job.lines, profile=w2.profile)
check("anteprima: ogni movimento sa da che riga viene", len(pv.seg_line) == len(pv.segs)
      and all(0 <= int(i) < len(job.lines) for i in pv.seg_line)
      and list(pv.seg_line) == sorted(pv.seg_line))
k = len(pv.segs) // 2
li = int(pv.seg_line[k])
x1, y1 = pv.segs[k][2], pv.segs[k][3]
check("la riga del movimento al cursore porta proprio lì", ("X%.3f" % x1).rstrip("0").rstrip(".") in job.lines[li]
      or ("Y%.3f" % y1).rstrip("0").rstrip(".") in job.lines[li] or "X" in job.lines[li], job.lines[li])
dlg = PreviewDialog(pv, job, w2.profile, (w2.profile.bed_x, w2.profile.bed_y), w2)
check("nell'anteprima c'è «Parti da qui…»", dlg.b_from_here is not None)
dlg.slider.setValue(k)
check("cursore a metà: riga del movimento dopo la testa", dlg.from_here_line() == li)
dlg.slider.setValue(len(pv.segs))
asked.clear()
dlg._from_here()
check("cursore alla fine: non parte e lo dice", dlg.start_line is None and asked and "fine" in asked[-1])
dlg.slider.setValue(k)
dlg._from_here()
check("Parti da qui: la finestra si chiude con la riga scelta", dlg.start_line == li and dlg.result() == 1)
dlg2 = PreviewDialog(pv, job, w2.profile, (100, 100), None)
check("anteprima aperta da altre finestre (senza programma dietro): niente pulsante", dlg2.b_from_here is None)
c2.sim.speedup = 40
asked.clear()
prog = w2.start_from_line(job, li, w2.editor.doc.plate.uid)
check("parte dalla riga scelta: stato ricostruito, testa portata lì a laser spento, poi le righe dal punto",
      prog is not None and prog[-(len(job.lines) - li):] == job.lines[li:] and c2.job_active
      and "S0" in " ".join(prog[:8]) and asked and "riga {0}".format(li + 1) in asked[-1], asked[-1:])
c2.sim.speedup = 2
until(lambda: c2.job_acked > 5, 10)
c2.stop_job()
until(lambda: not c2.job_active, 10)
spin(0.5)
got = job_save.load(config_dir())
check("fermato con Stop: resta sul disco da riprendere, con le righe partite da lì", got is not None
      and got[0] == list(c2.job_lines))
c2.disconnect_port()
until(lambda: not c2.connected, 5)
asked.clear()
check("senza laser collegato: non parte e lo dice", w2.start_from_line(job, li) is None and asked
      and "Collega" in asked[-1])
check("riga fuori dal lavoro: niente", w2.start_from_line(job, len(job.lines) + 5) is None)
ok_g92, _why = resume.can_resume(["G92 X0 Y0", "G1 X1 S1"], 1)
check("lavori con G92 o G91: non si riparte (come la ripresa di sempre)", not ok_g92)

print("--- traduzioni")
import json  # noqa: E402

keys = ["Parti da qui…", "Parti da qui", "Il cursore è alla fine del lavoro: portalo indietro, sul punto da cui "
        "ripartire.", "Collega il laser per far partire il lavoro.", "C'è già un lavoro in corso."]
missing = []
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    missing += [(lang, k_) for k_ in keys if not cat.get(k_)]
check("le voci nuove ci sono nelle 4 lingue", not missing, missing[:4])
w2.close()
ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
