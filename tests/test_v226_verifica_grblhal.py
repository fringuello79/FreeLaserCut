# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.6 (rapporto FLC-20261123-1214-08D5, Ortur con GrblHAL): con «Verifica il G-code prima di partire» il
lavoro non partiva mai. Uscendo dalla verifica quella scheda risponde «ok» e poi si riavvia per circa 2 secondi; la
finestra partiva dopo 1,2 s, vedeva ancora lo stato «Check», mandava un altro $C, rifiutava il lavoro («la scheda era
ancora in modalità di prova») e prendeva il riavvio per uno inatteso, perdendo l'homing.

Qui: il simulatore fa come quella scheda (check_exit_reboot_s); il lavoro deve partire, intero, senza $C in più e con
l'homing tenuto. Le schede GRBL classiche devono andare come prima.

Uso: python tests/test_v226_verifica_grblhal.py [classica|banco]
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
os.environ["FLC_NO_UPDATE"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.exec = lambda self: 0

from freelasercut import grbl  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def until(fn, t=15.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def spin(t):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.01)


JOB = (["G90 G21", "M5 S0", "G54", "M4 S0", "G0 X10 Y10"]
       + [f"G1 X{10 + (i % 2) * 20} Y{10 + i * 0.2:.1f} S300 F3000" for i in range(60)] + ["M5 S0", "G0 X10 Y10"])


class Job:
    def __init__(self, lines):
        self.lines = list(lines)


def run_case(win, reboot_s, label):
    ctl = win.ctl
    sim = ctl.sim
    sim.speedup = 40
    sim.check_exit_reboot_s = reboot_s
    sent = []
    real = ctl._write_raw

    def spy(data):
        sent.append(bytes(data))
        return real(data)
    ctl._write_raw = spy
    done = {}
    ctl.job_finished.connect(lambda ok, msg: done.setdefault("r", (ok, msg)))
    reboots0 = ctl.reboots
    ctl._reset_asked_t = 0.0  # nessun reset chiesto di recente (come a metà giornata, non subito dopo il collegamento)
    win._pending_start = Job(JOB)
    win._pending_plate = None
    ok = ctl.check_job(JOB)
    check(f"{label}: la verifica parte", ok)
    check(f"{label}: il lavoro finisce, completo", until(lambda: "r" in done, 30.0) and done["r"][0], str(done.get("r")))
    n_c = sum(1 for d in sent if d.strip() == b"$C")
    check(f"{label}: solo i due $C della verifica (entrata e uscita), nessuno in più", n_c == 2, n_c)
    check(f"{label}: nessuna riga del lavoro persa dalla scheda", getattr(sim, "lost_lines", 0) == 0,
          getattr(sim, "lost", []))
    check(f"{label}: il riavvio dopo la verifica non conta come inatteso: l'homing resta", ctl.reboots == reboots0
          and ctl.homed, (ctl.reboots, reboots0, ctl.homed))
    check(f"{label}: il lavoro ha mandato tutte le righe", ctl.job_acked == len(JOB), (ctl.job_acked, len(JOB)))
    ctl._write_raw = real
    try:
        ctl.job_finished.disconnect()
    except (RuntimeError, TypeError):
        pass
    win.ctl.job_finished.connect(win._job_finished) if hasattr(win, "_job_finished") else None
    return sent


win = mw.MainWindow()
win.show()
ctl = win.ctl
ctl.connect_port(SIM_PORT)
check("collegato al simulatore", until(lambda: ctl.last_status.get("state") == "Idle"))
ctl.home()
check("homing fatto", until(lambda: ctl.homed))
spin(3.0)  # le letture automatiche dopo il collegamento ($I, $$) sono finite, come nella realtà
check("letture dopo il collegamento finite", until(lambda: not ctl.busy))

# ------------------------------------------------------------------ A. la scheda del rapporto
print("--- A. scheda che si riavvia dopo la verifica (Ortur con GrblHAL)")
t0 = time.time()
run_case(win, 2.0, "Ortur")
check("Ortur: il lavoro è partito solo dopo il riavvio (più di 2 s dopo la fine della verifica)",
      ctl._check_end_t > 0 and time.time() - t0 > 2.0)

# ------------------------------------------------------------------ B. GRBL classico: come prima
print("--- B. GRBL classico (reset e saluto subito)")
spin(0.5)
run_case(win, 0.0, "classico")

# ------------------------------------------------------------------ C. il controllore da solo
print("--- C. controllore")
c = ctl
c._check_end_t = time.time()
c.last_status = {"state": "Check"}
c.status_time = c._check_end_t - 0.5
check("C stato «Check» letto prima della fine della verifica: la scheda sta ripartendo, non è rimasta in prova",
      c.check_settling() and not c.ready_after_check())
got = {}
c.job_finished.connect(lambda ok, msg: got.setdefault("r", (ok, msg)))
sent = []
real = c._write_raw
c._write_raw = lambda d: sent.append(bytes(d))
c.stream_job(JOB)
c._write_raw = real
check("C in quel momento stream_job non manda un $C in più e lo dice", got.get("r", (True,))[0] is False
      and not any(d.strip() == b"$C" for d in sent) and not c.stale_check_exit, (got, sent[:3]))
c.status_time = time.time()
c.last_status = {"state": "Idle"}
check("C appena arriva uno stato nuovo non «Check»: pronta", c.ready_after_check() and not c.check_settling())
c._check_end_t = time.time() - grbl.CHECK_SETTLE_S - 1
c.last_status = {"state": "Check"}
c.status_time = c._check_end_t - 1
check("C molto tempo dopo una verifica, «Check» vuol dire di nuovo scheda rimasta in prova (comportamento di prima)",
      not c.check_settling())
c.last_status = {"state": "Idle"}
c.status_time = time.time()

# ------------------------------------------------------------------ D. Stop o scollegata durante l'attesa: non parte niente
print("--- D. Stop, o scollegata, mentre aspetta")
calls = []
real_run = win._run
win._run = lambda *a, **k: calls.append(a)
real_ready0 = ctl.ready_after_check
ctl.ready_after_check = lambda: False  # la scheda sta ancora ripartendo
win.CHECK_START_WAIT_S = 1.0
win._run_after_check(JOB, None, None, ctl.reset_count)
spin(0.3)
ctl.stop_job()  # la persona preme Stop mentre «aspetto che la scheda riparta»
ctl.ready_after_check = lambda: True
spin(1.5)
check("D Stop premuto mentre il lavoro aspetta di partire: il lavoro non parte", not calls, calls[:1])
win._run_after_check(JOB, None, None, ctl.reset_count)
spin(0.5)
check("D (senza Stop, con la scheda pronta, parte)", len(calls) == 1, len(calls))
del calls[:]
ctl.ready_after_check = real_ready0
until(lambda: ctl.last_status.get("state") == "Idle", 5.0)
ctl.sim.check_exit_reboot_s = 0.0
real_ready = ctl.ready_after_check
ctl.ready_after_check = lambda: False
win.CHECK_START_WAIT_S = 0.3  # anche oltre l'attesa massima: scollegata, il lavoro non deve partire
win._run_after_check(JOB, None)
ctl.disconnect_port()
spin(1.2)
check("D la macchina si scollega mentre il lavoro aspetta: il lavoro non parte", not calls, calls[:1])
ctl.ready_after_check = real_ready
win._run = real_run

win.close()
print(f"\n{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
