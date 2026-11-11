# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.15, dal rapporto FLC-20261111-2131-0A9C (OMTech K40, Grbl 1.1h «omtech»): in verifica la scheda risponde
error:2 alla riga G55 e poi non risponde più; la verifica falliva sempre e il lavoro non partiva mai.
FreeLaserCut sapeva già lavorare senza G55, ma solo se la scheda rispondeva error:20.
Ora: qualsiasi errore sulla riga G55 = scheda senza G55; il silenzio che segue non conta come un altro errore; il lavoro
viene rifatto in G54, verificato di nuovo e avviato. Un silenzio senza il rifiuto di G55 resta un errore, come prima.
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
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT, GrblController  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui.dialogs import CheckResultDialog  # noqa: E402

shown = []
CheckResultDialog.exec = lambda self: shown.append(1) or 0  # l'esito della verifica non deve fermare la prova
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


JOB = ["G90 G21", "M5 S0", "M9", "G10 L2 P2 X0 Y0", "G55", "M4 S0", "M8", "G0 X29.62 Y32.703", "G1 X35.654 S300 F1500",
       "Y26.669", "X29.62", "Y32.703", "M5 S0", "M9", "G0 X10 Y190", "G54"]  # le righe del rapporto

# ================================================================== collegamento con la scheda
c = GrblController()
c.connect_port(SIM_PORT)
c.sim.speedup = 50
until(lambda: c.board_settings and c.last_status.get("state") == "Idle")
c.sim.g55_stalls = True
done = []
c.check_finished.connect(lambda r: done.append(r))
pos0 = list(c.sim.pos)
c.check_job(JOB)
until(lambda: done, 15)
r = done[-1] if done else []
check("scheda che risponde error:2 a G55 e poi tace: la verifica si chiude da sola", bool(done), done)
check("…l'errore è sulla riga G55, con il codice 2", any(e[1] == "G55" and e[2] == 2 for e in r), r)
check("…e FreeLaserCut capisce che la scheda non ha G55 (prima solo con error:20)", c.no_g55 is True)
check("…la scheda esce dalla modalità di prova e la testa non si è mossa",
      until(lambda: not c.sim.check_mode and c.last_status.get("state") == "Idle", 10) and c.sim.pos == pos0)
c.sim.g55_stalls = False
c.disconnect_port()

# ================================================================== finestra: Verifica e avvia
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.editor.doc.add(RectShape(20, 10))
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings)
w.profile.negative_space = False
w.profile.no_g55 = False
w.ctl.homed = True
started = []
w._run = lambda lines, plate=None: started.append(list(lines))

# un silenzio qualsiasi (senza il rifiuto di G55) resta un errore: niente riavvio da solo
w.ctl.sim.drop_check_after = 6
job = w.build_job()
w._pending_start = job
w.laser.start_progress("check")
w.ctl.check_job(job.lines)
until(lambda: shown, 15)
until(lambda: False, 2.0)
check("silenzio senza rifiuto di G55: resta un errore, il lavoro non parte e il profilo non cambia",
      bool(shown) and not started and not w.profile.no_g55 and not w.ctl.no_g55, (shown, len(started)))
w.ctl.sim.drop_check_after = None
until(lambda: not w.ctl.sim.check_mode and w.ctl.last_status.get("state") == "Idle" and not w.ctl.stale_check_exit, 12)

shown.clear()
w.ctl.sim.g55_stalls = True
job = w.build_job()
check("il lavoro normale usa G55", "G55" in job.lines)
w._pending_start = job  # come «Verifica e avvia»
w.laser.start_progress("check")
t0 = time.time()
w.ctl.check_job(job.lines)
ok = until(lambda: started, 45)
check("Verifica e avvia sulla scheda dell'OMTech: FreeLaserCut rifà il lavoro senza G55, lo verifica e lo avvia",
      ok and "G55" not in started[0] and not any(l.startswith("G10 L2") for l in started[0]) and "G54" in started[0],
      (round(time.time() - t0, 1), started[0][:8] if started else None))
check("…senza mostrare la finestra dell'errore", not shown, shown)
check("…e la scelta resta nel profilo della macchina", w.profile.no_g55 is True
      and MachineProfile.load(w.profile.path()).no_g55 is True)
started.clear()
job = w.build_job()
w._pending_start = job
w.laser.start_progress("check")
w.ctl.check_job(job.lines)
check("la volta dopo la verifica passa subito", until(lambda: started, 15) and "G55" not in job.lines and not shown)
w.ctl.disconnect_port()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
