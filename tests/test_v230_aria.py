# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.0: il pulsante Aria spegne (e accende) l'aria subito, anche con un lavoro in corso o in pausa
(rapporto FLC-20261124-1157-8595, Sculpfun S9, GRBL 1.1h: «l'aria non si spegne dal tasto»).

Causa: le righe di un lavoro vanno tutte in coda appena parte, e il comando del pulsante (M9) finiva dietro all'ultima:
l'aria si spegneva solo a fine lavoro, in pausa mai. Ora, con righe in coda, si usano i due comandi immediati di
GRBL 1.1 (0xA0 inverte l'aria M8, 0xA1 la nebbia M7), validi a macchina ferma, in lavoro e in pausa; a macchina libera
resta M8/M9 come sempre. Il pulsante segue quello che la scheda dice dell'aria (campo A: del report), senza mandare
niente.
Uso: python tests/test_v230_aria.py [banco]
"""
import os
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
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.grbl import SIM_PORT, parse_status  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def until(fn, t=8.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def spin(t):
    until(lambda: False, t)


# ------------------------------------------------------------------ lettura del campo A: del report
st = parse_status("<Run|MPos:1,2,0|FS:100,0|Ov:100,100,100|A:SF>", [0, 0, 0])
check("report con A:SF: aria (F) accesa letta", st.get("acc") == "SF")
st = parse_status("<Idle|MPos:1,2,0|FS:0,0|Ov:100,100,100>", [0, 0, 0])
check("report con Ov e senza A: tutto spento", "ov" in st and "acc" not in st)

w = MainWindow()
w.resize(1300, 850)
w.show()
ctl = w.ctl
ctl.connect_port(SIM_PORT)
check("collegato al simulatore", until(lambda: ctl.connected and ctl.last_status.get("state") == "Idle", 10))
ctl.sim.speedup = 1.0
w.profile.air_on, w.profile.air_off = "M8", "M9"
w._sync_axes()
b = w.laser.b_air
sent, rt = [], []
ctl.line_sent.connect(sent.append)
real_rt = ctl.realtime


def spy_rt(byte):
    rt.append(byte if isinstance(byte, int) else byte[0])
    real_rt(byte)


ctl.realtime = spy_rt


def air_of_sim():
    return "F" in getattr(ctl.sim, "coolant", set())


# ------------------------------------------------------------------ macchina libera: come sempre
b.setChecked(True)
check("macchina libera, Aria accesa: M8 in coda come sempre", until(lambda: "M8" in sent, 3) and until(air_of_sim, 3))
check("…il report lo dice (A:F) e il pulsante resta acceso", until(lambda: ctl.air_board is True, 3) and b.isChecked())
del sent[:]
b.setChecked(False)
check("macchina libera, Aria spenta: M9", until(lambda: "M9" in sent, 3) and until(lambda: not air_of_sim(), 3))
check("…niente comandi immediati a macchina libera", not [x for x in rt if x in (0xA0, 0xA1)], rt)
until(lambda: ctl.air_board is False, 3)

# ------------------------------------------------------------------ lavoro in corso: il caso del rapporto
JOB = ["G90 G21", "M8", "M4 S0"] + [f"G1 X{10 + (i % 2) * 60} Y{10 + i * 0.5:.1f} S0 F1200" for i in range(120)] + \
      ["M5 S0", "M9"]
del sent[:]
ctl.stream_job(JOB)
check("lavoro partito, il G-code accende l'aria (M8 del lavoro)", until(air_of_sim, 5))
check("…il pulsante si accende da solo, seguendo la scheda", until(lambda: b.isChecked(), 4))
check("…allinearsi alla scheda non manda niente (nessun M8 dal pulsante)", "M8" not in sent and "M9" not in sent, sent[-4:])
n_sent = len([s for s in sent if s in ("M8", "M9")])
del rt[:]
b.setChecked(False)
check("durante il lavoro, Aria spenta: comando immediato 0xA0 (non M9 in coda)", 0xA0 in rt and
      len([s for s in sent if s in ("M8", "M9")]) == n_sent, (rt, sent[-3:]))
check("…l'aria si spegne SUBITO, con il lavoro ancora in corso", until(lambda: not air_of_sim(), 1.5)
      and ctl.job_active)
with ctl._lock:
    tail = [c.line for c in ctl._pending][-2:]
check("…in coda niente M9 aggiunto dal pulsante (restano solo le righe del lavoro)", tail == ["M5 S0", "M9"], tail)
del rt[:]
b.setChecked(True)
check("durante il lavoro, Aria accesa: 0xA0 e l'aria si riaccende subito", 0xA0 in rt and until(air_of_sim, 1.5))

# ------------------------------------------------------------------ in pausa
ctl.feed_hold()
check("pausa: la macchina è ferma (Hold)", until(lambda: ctl.last_status.get("state") == "Hold", 3))
del rt[:]
b.setChecked(False)
check("in pausa, Aria spenta: si spegne subito (prima restava accesa fino alla fine)", 0xA0 in rt and
      until(lambda: not air_of_sim(), 1.5))
del rt[:]
b.setChecked(False)
check("già spenta: nessun comando in più", not rt)
ctl.resume()
spin(0.3)

# ------------------------------------------------------------------ Stop: il pulsante segue la scheda
b.setChecked(True)
until(air_of_sim, 2)
ctl.stop_job()
check("Stop: la scheda spegne l'aria e il pulsante la segue", until(lambda: not air_of_sim(), 3)
      and until(lambda: not b.isChecked(), 4))
until(lambda: not ctl.job_active and ctl.last_status.get("state") in ("Idle", "Alarm"), 8)
if ctl.last_status.get("state") == "Alarm":
    ctl.send_line("$X")
    until(lambda: ctl.last_status.get("state") == "Idle", 4)

# ------------------------------------------------------------------ aria con M7
w.profile.air_on, w.profile.air_off = "M7", "M9"
w._sync_axes()
ctl.stream_job(["G90 G21", "M7"] + [f"G1 X{10 + (i % 2) * 60} Y{10 + i:.1f} S0 F1200" for i in range(60)] + ["M9"])
check("profilo con M7: il lavoro accende la nebbia", until(lambda: "M" in ctl.sim.coolant, 5))
del rt[:]
b.setChecked(False) if b.isChecked() else None
until(lambda: ctl.air_board is True, 3)
if not b.isChecked():
    b.blockSignals(True)
    b.setChecked(True)
    b.blockSignals(False)
del rt[:]
b.setChecked(False)
check("…Aria spenta durante il lavoro: comando immediato 0xA1 (quello di M7)", 0xA1 in rt and 0xA0 not in rt
      and until(lambda: "M" not in ctl.sim.coolant, 1.5), rt)
del rt[:]
b.setChecked(True)
check("…e riaccesa: 0xA1 di nuovo, non 0xA0", rt == [0xA1] and until(lambda: "M" in ctl.sim.coolant, 1.5)
      and "F" not in ctl.sim.coolant, rt)
ctl.stop_job()
until(lambda: not ctl.job_active, 8)
if ctl.last_status.get("state") == "Alarm":
    ctl.send_line("$X")
    until(lambda: ctl.last_status.get("state") == "Idle", 4)

# ------------------------------------------------------------------ stato non ancora noto, nessun comando
w.profile.air_on, w.profile.air_off = "M8", "M9"
w._sync_axes()
ctl.air_board = ctl.air_acc = None
with ctl._lock:
    ctl._job_active_saved = ctl._job_active
ctl._job_active = True  # come con un lavoro in corso, senza report dell'aria ancora arrivato
del rt[:]
ctl._air_realtime(False)
check("stato dell'aria non noto: si inverte quella del profilo (0xA0 per M8)", rt == [0xA0], rt)
ctl._job_active = ctl._job_active_saved
w.profile.air_on, w.profile.air_off = "", ""
w._sync_axes()
msgs = []
ctl.message.connect(msgs.append)
ctl.air(False)
check("profilo «nessun comando»: lo dice come prima", any("nessun comando" in m for m in msgs))

ctl.realtime = real_rt
ctl.disconnect_port()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
ok = sum(results)
print(f"\n{ok}/{len(results)} verifiche superate")
sys.exit(0 if ok == len(results) else 1)
