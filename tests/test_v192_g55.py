# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.2, dal rapporto FLC-20261112-2308-104A (lo stesso OMTech K40 della 0.18.15, Grbl 1.1h «omtech», ora con la
0.19.0): «con le coordinate assolute tutto sembra a posto, nessun errore, ma il laser resta fermo».

Dal registro: la riga G55 su quella scheda ha tre esiti. Nella verifica: nessuna risposta (l'error:2 arriva solo dopo,
al «$C» di uscita), quindi la correzione della 0.18.15, che aspettava l'errore su G55, non scattava. Nel lavoro
avviato senza verifica: in un lavoro lungo error:2 (e il lavoro restava in pausa), in uno corto nessuna risposta (tre
conferme e poi silenzio, a macchina ferma).

Il dato: riga G55 × dove (verifica / lavoro) × scheda (accetta / errore subito / silenzio) × lavoro di FreeLaserCut o
file G-code esterno × profilo (senza G55 già segnato / no). Una prova per riga della matrice G1…G10 del documento.
"""
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
boxes = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: (boxes.append((a[1], a[2])), QMessageBox.Ok)[1])
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
paused = []
QMessageBox.exec = lambda self: paused.append(self.text()) or 0  # la finestra «Lavoro in pausa»
from freelasercut import grbl  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT, GrblController  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui.dialogs import CheckResultDialog  # noqa: E402

shown = []
CheckResultDialog.exec = lambda self: shown.append(1) or 0
results = []
hidden = []
sys.excepthook = lambda *a: hidden.append(a[1])


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


# le righe del rapporto: lavoro corto, con G55 alla quarta riga
JOB = ["G90 G21", "M5 S0", "G10 L2 P2 X0 Y0", "G55", "M4 S0", "G0 X141.007 Y124.671", "G1 X168.835 S300 F1500",
       "Y102.304", "X141.007", "Y124.671", "M5 S0", "G0 X10 Y190", "G54"]
check("riconoscimento della riga: «G55», « g55 », «G 55» sì; «G55 X1», «G54», «G550» no",
      grbl._is_g55("G55") and grbl._is_g55(" g55 ") and grbl._is_g55("G 55") and not grbl._is_g55("G55 X1")
      and not grbl._is_g55("G54") and not grbl._is_g55("G550") and not grbl._is_g55(""))


def board(**sim):
    c_ = GrblController()
    c_.connect_port(SIM_PORT)
    c_.sim.speedup = 50
    until(lambda: c_.board_settings and c_.last_status.get("state") == "Idle")
    for k, v in sim.items():
        setattr(c_.sim, k, v)
    return c_


# ================================================================== la scheda, senza finestra
c = board(g55_stalls="mute")
done, refused = [], []
c.check_finished.connect(lambda r: done.append(r))
pos0 = list(c.sim.pos)
t0 = time.time()
c.check_job(JOB)
until(lambda: done, 15)
r = done[-1] if done else []
check("G1 verifica, la scheda tace su G55 (nessun errore): la verifica si chiude da sola dopo l'attesa",
      bool(done) and any(e[2] == "NO_RISPOSTA" for e in r) and 5.0 < time.time() - t0 < 12.0, (done, round(time.time() - t0, 1)))
check("G1 …e FreeLaserCut capisce che la colpa è di G55 (prima restava «la scheda ha smesso di rispondere»)", c.no_g55 is True)
check("G1 …la scheda esce dalla modalità di prova (con il reset, dopo l'errore in ritardo) e la testa non si è mossa",
      until(lambda: not c.sim.check_mode and c.last_status.get("state") == "Idle" and not c.stale_check_exit, 12)
      and c.sim.pos == pos0, (c.sim.check_mode, c.last_status.get("state")))
c.disconnect_port()

c = board()
c.sim.drop_check_after = 5  # la scheda tace da una riga che non è G55
done = []
c.check_finished.connect(lambda r: done.append(r))
c.check_job(JOB)
until(lambda: done, 15)
check("G7 verifica, silenzio da una riga che non è G55: resta «ha smesso di rispondere», G55 non c'entra",
      bool(done) and any(e[2] == "NO_RISPOSTA" for e in done[-1]) and c.no_g55 is False, done)
c.disconnect_port()

c = board(g55_stalls="mute")
done = []
c.check_finished.connect(lambda r: done.append(r))
SHORT = ["G90 G21", "M5 S0", "G55", "M5 S0", "G54"]  # dopo G55 restano solo due righe: non sono «risposte perse»
c.check_job(SHORT)
until(lambda: done, 15)
check("G10 verifica corta, G55 fra le ultime tre righe senza risposta: non viene scambiata per «risposte perse»",
      bool(done) and c.no_g55 is True and c.lost_replies == 0 and any(e[2] == "NO_RISPOSTA" for e in done[-1]),
      (done, c.lost_replies))
c.disconnect_port()

c = board()
c.sim.lose_ok_at = {c.sim._oks + 1 + len(SHORT)}  # una scheda normale che perde l'ultima conferma: quella regola deve valere ancora
done = []
c.check_finished.connect(lambda r: done.append(r))
c.check_job(SHORT)
until(lambda: done, 15)
check("G10 …mentre le risposte perse davvero (ultima conferma mancante, G55 accettato) restano tollerate",
      bool(done) and done[-1] == [] and c.no_g55 is False and c.lost_replies == 1, (done, c.lost_replies))
c.disconnect_port()

for how in ("error", "mute"):
    c = board(g55_job=how)
    c.sim.speedup = 1  # velocità vera: fra l'errore e la pausa la scheda fa in tempo a cominciare lo spostamento a vuoto
    c.sim.burn_marks.clear()
    refused, errs, fin = [], [], []
    c.g55_refused.connect(refused.append)
    c.job_error.connect(lambda *a: errs.append(a))
    c.job_finished.connect(lambda ok, msg: fin.append((ok, msg)))
    pos0 = list(c.sim.pos)
    t0 = time.time()
    c.stream_job(JOB)
    until(lambda: refused, 12)
    dt = time.time() - t0
    exp = "error" if how == "error" else "silent"
    row = "G3" if how == "error" else "G4"
    check(f"{row} lavoro, la scheda {'risponde error:2 a' if how == 'error' else 'tace su'} G55: segnale dedicato «{exp}», "
          f"una volta sola, {'subito' if how == 'error' else 'dopo 4 secondi (non 20)'}",
          refused == [exp] and c.no_g55 is True and (dt < 3.0 if how == "error" else 3.5 < dt < 9.0), (refused, round(dt, 1)))
    until(lambda: fin, 8)
    until(lambda: False, 1.0)
    moved = max(abs(c.sim.pos[0] - pos0[0]), abs(c.sim.pos[1] - pos0[1]))
    check(f"{row} …il controllo ferma da solo il lavoro (pausa e reset): niente finestra «Lavoro in pausa», niente "
          "inciso" + (", testa ferma dov'era" if how == "mute" else " (al più l'inizio dello spostamento a vuoto)"),
          not errs and bool(fin) and fin[-1][0] is False and not c.job_active and not c.sim.burn_marks
          and (moved == 0 if how == "mute" else moved < 25.0) and c.last_status.get("state") != "Hold",
          (errs, fin, c.sim.pos, c.last_status.get("state"), len(c.sim.burn_marks)))
    check(f"{row} …e il segnale non si ripete", refused == [exp], refused)
    c.disconnect_port()

c = board()
refused, fin = [], []
c.g55_refused.connect(refused.append)
c.job_finished.connect(lambda ok, msg: fin.append((ok, msg)))
c.stream_job(JOB)
until(lambda: fin, 20)
until(lambda: False, 0.5)
check("G6 scheda normale: G55 accettato, lavoro completo, nessun segnale", bool(fin) and fin[-1][0] is True and not refused
      and c.no_g55 is False, (fin, refused))
c.disconnect_port()

c = board()
real_process = c.sim._process
mute = []
c.sim._process = lambda line, gen: None if (mute or line.strip().upper().startswith("G0")) and (mute.append(1) or True) \
    else real_process(line, gen)
refused = []
c.g55_refused.connect(refused.append)
c.stream_job(JOB)
until(lambda: False, 6.5)
check("G7 lavoro, la scheda tace da una riga che non è G55 (G0): nessun segnale per G55, la scheda non viene segnata",
      not refused and c.no_g55 is False and c.job_acked == 5, (refused, c.job_acked))
c.stop_job()
c.disconnect_port()

c = board()
real_process2 = c.sim._process
c.sim._process = lambda line, gen: c.sim._emit("error:20\r\n") if line.strip().upper() == "M4 S0" else real_process2(line, gen)
refused, errs = [], []
c.g55_refused.connect(refused.append)
c.job_error.connect(lambda *a: errs.append(a))
c.stream_job(JOB)
until(lambda: errs, 8)
check("G8 lavoro, errore su un'altra riga (M4): resta la pausa con la domanda di sempre, G55 non c'entra",
      len(errs) == 1 and errs[0][1] == "M4 S0" and errs[0][2] == 20 and not refused and c.no_g55 is False, (errs, refused))
c.stop_job()
c.disconnect_port()

# ================================================================== la finestra
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
shape = RectShape(20, 10)
shape.tf.translate(141.0, 102.3)  # dov'era il rettangolo dell'utente: prima dell'incisione c'è uno spostamento a vuoto
shape.invalidate()
w.editor.doc.add(shape)
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings)
w.profile.negative_space = False
w.profile.no_g55 = False
w.ctl.homed = True
started = []
real_run = w._run
w._run = lambda lines, plate=None: started.append(list(lines))

w.ctl.sim.g55_stalls = "mute"
job = w.build_job()
check("(il lavoro normale, con le coordinate assolute, usa G55 prima di qualsiasi movimento)",
      "G55" in job.lines and not any(re.match(r"G0*[0123](\s|$)", l) for l in job.lines[:job.lines.index("G55")]), job.lines[:8])
w._pending_start = job  # come «Verifica e avvia»
w.laser.start_progress("check")
t0 = time.time()
w.ctl.check_job(job.lines)
ok = until(lambda: started, 60)
check("G1 «Verifica e avvia» sulla scheda che in verifica tace su G55: FreeLaserCut rifà il lavoro senza G55, lo "
      "verifica di nuovo e lo avvia",
      ok and "G55" not in started[0] and not any(l.startswith("G10 L2") for l in started[0]) and "G54" in started[0],
      (round(time.time() - t0, 1), started[0][:8] if started else None, shown))
check("G1 …senza la finestra dell'errore, e la scelta resta nel profilo della macchina",
      not shown and w.profile.no_g55 is True and MachineProfile.load(w.profile.path()).no_g55 is True, shown)
until(lambda: not w.ctl.sim.check_mode and w.ctl.last_status.get("state") == "Idle" and not w.ctl.stale_check_exit, 12)

w.ctl.sim.g55_stalls = True  # il caso della 0.18.15: error:2 su G55 e poi silenzio
w.profile.no_g55 = False
w.ctl.no_g55 = False
started.clear()
shown.clear()
job = w.build_job()
w._pending_start = job
w.laser.start_progress("check")
w.ctl.check_job(job.lines)
ok = until(lambda: started, 60)
check("G2 il caso di prima (error:2 su G55 e poi silenzio) funziona ancora", ok and "G55" not in started[0] and not shown
      and w.profile.no_g55 is True, (started[0][:6] if started else None, shown))
until(lambda: not w.ctl.sim.check_mode and w.ctl.last_status.get("state") == "Idle" and not w.ctl.stale_check_exit, 12)
w.ctl.sim.g55_stalls = False

for how in ("error", "mute"):
    row = "G3" if how == "error" else "G4"
    w.profile.no_g55 = False
    w.profile.save()
    w.ctl.no_g55 = False
    w.ctl.sim.g55_job = how
    w._run = real_run
    boxes.clear()
    paused.clear()
    fin = []
    w.ctl.job_finished.connect(lambda ok_, msg: fin.append((ok_, msg)))
    job = w.build_job()
    w._job_is_external = False
    w.ctl.sim.speedup = 1
    w.ctl.sim.burn_marks.clear()
    w._run(job.lines, w.editor.doc.plate.uid)
    until(lambda: boxes, 15)
    until(lambda: fin, 10)
    until(lambda: w.ctl.last_status.get("state") in ("Idle", "Alarm"), 8)
    text = boxes[0][1] if boxes else ""
    check(f"{row} lavoro avviato senza verifica, la scheda {'rifiuta' if how == 'error' else 'tace su'} G55: il lavoro "
          "viene fermato (non resta in pausa) e non è stato inciso niente",
          bool(fin) and fin[-1][0] is False and not w.ctl.job_active and not w.ctl.sim.burn_marks
          and w.ctl.last_status.get("state") != "Hold", (fin, w.ctl.last_status.get("state"), len(w.ctl.sim.burn_marks)))
    w.ctl.sim.speedup = 50
    check(f"{row} …lo dice con una finestra: G55, profilo annotato, «premi di nuovo Avvia»; niente «Lavoro in pausa»",
          len(boxes) == 1 and "G55" in text and "Avvia" in text and "profilo" in text and not paused, (boxes, paused))
    check(f"{row} …il profilo della macchina è segnato «senza G55» e salvato",
          w.profile.no_g55 is True and MachineProfile.load(w.profile.path()).no_g55 is True)
    check(f"{row} …e il lavoro fermato non viene offerto per la ripresa (contiene ancora G55)", w._interrupted is None,
          w._interrupted)
    job2 = w.build_job()
    fin.clear()
    boxes.clear()
    w._run(job2.lines, w.editor.doc.plate.uid)
    until(lambda: fin, 30)
    check(f"G5 dopo {row}, di nuovo Avvia: il lavoro è senza G55 e arriva in fondo",
          "G55" not in job2.lines and "G54" in job2.lines and bool(fin) and fin[-1][0] is True and not boxes, (fin, boxes))
    until(lambda: w.ctl.last_status.get("state") == "Idle", 8)
w.ctl.sim.g55_job = None

# file G-code esterno che usa G55, su una scheda che non lo conosce
w.profile.no_g55 = False
w.ctl.no_g55 = False
w.ctl.sim.g55_job = "error"
boxes.clear()
fin = []
w.ctl.job_finished.connect(lambda ok_, msg: fin.append((ok_, msg)))
w._job_is_external = True
w._run(JOB, None)
until(lambda: boxes, 15)
until(lambda: fin, 10)
text = boxes[0][1] if boxes else ""
check("G9 file G-code esterno con G55 rifiutato: fermato, con il messaggio del file (non «premi di nuovo Avvia»)",
      len(boxes) == 1 and "file G-code" in text and "Avvia" not in text and bool(fin) and fin[-1][0] is False
      and w.profile.no_g55 is True, (boxes, fin))
w._job_is_external = False
w.ctl.sim.g55_job = None
until(lambda: w.ctl.last_status.get("state") in ("Idle", "Alarm"), 8)

# ------------------------------------------------------------------ traduzioni
import ast  # noqa: E402
import json  # noqa: E402

src = open(os.path.join(ROOT, "freelasercut", "ui", "main_window.py"), encoding="utf-8").read()
part = src.split("def _g55_refused")[1].split("def _job_finished")[0]
keys = set()
for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', part):
    keys.add("".join(ast.literal_eval(p_) for p_ in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1))))
check("testi nuovi trovati nel codice (3)", len(keys) == 3, sorted(k[:40] for k in keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k[:40] for k in keys if not loc.get(k)]
    check(f"traduzioni {lang}: i tre testi, e G55 resta scritto com'è", not miss
          and all("G55" in loc[k] for k in keys if "G55" in k and loc.get(k)), miss)

check("nessun errore nascosto", not hidden, [repr(e)[:120] for e in hidden[:3]])
w.ctl.disconnect_port()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
