# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10.4: verifica ($C) più robusta.
- un ALARM durante la verifica (es. 2 = limiti software) la chiude con l'errore e la riga colpevole;
- il banner di reset della scheda, Stop e Disconnetti chiudono sempre la verifica;
- il controllo prima dell'avvio usa anche $130/$131 letti dalla scheda quando i limiti software sono attivi;
- il simulatore applica i limiti software anche in modalità verifica, come GRBL."""
import sys, os, time, tempfile, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication, QMessageBox, QListWidget, QLabel
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.exec = lambda self: 0
from freelasercut.grbl import GrblController, SIM_PORT

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.005)
def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()

c = GrblController()
got = {}
alarms = []
c.check_finished.connect(lambda r: got.__setitem__("check", r))
c.alarm_raised.connect(lambda code, t: alarms.append(code))
c.connect_port(SIM_PORT)
c.sim.speedup = 50
check("dopo la connessione FreeLaserCut tiene i $$ letti dalla scheda",
      until(lambda: c.board_settings.get(130) == "450.000"), str(c.board_settings.get(130)))
check("limiti software attivi ($20=1): corsa 450 × 440 dalla scheda", c.soft_limits() == (450.0, 440.0), str(c.soft_limits()))

# ------------------------------------------------------------------ allarme 2 durante la verifica
job = ["G90 G21", "M4 S0"] + [f"G1 X{10 + i} Y20 S300 F3000" for i in range(60)] + ["G0 X470 Y20"] + \
      [f"G1 X{100 + i} Y30" for i in range(40)] + ["M5"]
bad_index = 62
c.check_job(job)
check("verifica: un movimento oltre $130 manda la scheda in allarme e chiude la verifica",
      until(lambda: "check" in got), str(got.get("check")))
errs = got.get("check") or []
last = errs[-1] if errs else (None, None, None, None)
check("la verifica indica la riga colpevole e l'allarme 2", last[0] == bad_index and last[1] == "G0 X470 Y20" and last[2] == "ALARM:2",
      str(errs))
check("non resta nessuna verifica appesa e la coda è vuota", not c.checking and not c.busy)
check("FreeLaserCut fa il reset: la scheda esce dallo stato critico e resta in allarme da sbloccare",
      until(lambda: c.last_status.get("state") == "Alarm" and not c.sim._critical and not c.sim.check_mode),
      f"{c.last_status.get('state')} critico={c.sim._critical} check={c.sim.check_mode}")
check("l'allarme arriva anche al banner dell'interfaccia", 2 in alarms, str(alarms))
c.unlock()
check("sblocco: la scheda torna pronta", until(lambda: c.last_status.get("state") == "Idle"), c.last_status.get("state"))

got.pop("check", None)
c.check_job(job[:62] + job[63:])
check("lo stesso lavoro senza la riga fuori corsa passa la verifica", until(lambda: "check" in got) and got["check"] == [],
      str(got.get("check")))
spin(1.0)

# arco che esce dalla corsa anche se gli estremi sono dentro
got.pop("check", None)
c.check_job(["G90 G21", "G0 X5 Y220", "G2 X5 Y240 I0 J10", "G2 X5 Y220 I0 J-10", "G0 X5 Y5", "G3 X25 Y5 I10 J0"])
check("verifica: un arco che sfora lo zero è fermato dai limiti software (estremi dentro)",
      until(lambda: "check" in got) and (got["check"] or [(0, 0, 0)])[-1][2] == "ALARM:2", str(got.get("check")))
c.unlock(); until(lambda: c.last_status.get("state") == "Idle")

# limiti software spenti: niente allarme
c.write_setting(20, 0); c.request_settings()
check("con $20=0 FreeLaserCut sa che i limiti software sono spenti", until(lambda: c.soft_limits() is None), str(c.board_settings.get(20)))
got.pop("check", None)
c.check_job(job)
check("con $20=0 la stessa riga non dà allarme (la scheda non controlla)", until(lambda: "check" in got) and got["check"] == [],
      str(got.get("check")))
spin(1.0)
c.write_setting(20, 1); c.request_settings(); until(lambda: c.soft_limits() is not None)

# ------------------------------------------------------------------ Stop, reset della scheda, Disconnetti
long_job = ["G90 G21"] + [f"G1 X{10 + (i % 300)} Y{10 + (i % 7)} S300 F3000" for i in range(120000)]

got.pop("check", None)
c.check_job(long_job)
spin(0.05)
was = c.checking
c.stop_job()
check("Stop durante la verifica: verifica chiusa subito come interrotta", was and not c.checking and got.get("check", "x") is None,
      f"in corso={was} esito={str(got.get('check', 'x'))[:60]}")
check("dopo lo Stop la scheda esce dal check mode e torna pronta",
      until(lambda: not c.sim.check_mode and c.last_status.get("state") == "Idle"), c.last_status.get("state"))
spin(0.5)

got.pop("check", None)
c.check_job(long_job)
spin(0.05)
was = c.checking
c.sim._reset()  # la scheda si riavvia da sola (banner "Grbl 1.1h") a metà verifica
check("banner di reset a metà verifica: verifica chiusa come interrotta", was and until(lambda: "check" in got) and got["check"] is None
      and not c.checking, f"in corso={was} esito={str(got.get('check', 'x'))[:60]}")
until(lambda: not c.busy, 3)
spin(0.5)

got.pop("check", None)
c.check_job(long_job)
spin(0.05)
was = c.checking
c.disconnect_port()
check("Disconnetti durante la verifica: verifica chiusa come interrotta", was and not c.checking and got.get("check", "x") is None,
      f"in corso={was}")
c.connect_port(SIM_PORT)
check("riconnessione: nessuna verifica rimasta e $$ letti di nuovo",
      not c.checking and until(lambda: c.board_settings.get(130) == "450.000"))
c.disconnect_port()

# ------------------------------------------------------------------ controllo prima dell'avvio
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui.dialogs import CheckResultDialog

w = MainWindow()
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.soft_limits() is not None)
w.profile.negative_space = None
w.ctl.negative_space = None

def fake_job(x1, y1, warnings=()):
    segs = np.array([[0.0, 0.0, 20.0, 20.0, 0, 0, 6000], [20.0, 20.0, x1, y1, 300, 1, 3000]])
    return types.SimpleNamespace(lines=["G0 X20 Y20", f"G1 X{x1} Y{y1}"], bounds=QRectF(20, 20, x1 - 20, y1 - 20),
                                 warnings=list(warnings), out_to_bed=(0.0, 0.0), motion_bounds=None,
                                 preview=types.SimpleNamespace(segs=segs))

check("lavoro dentro la corsa della scheda: nessun blocco", w._soft_limit_problem(fake_job(300, 300)) is None)
w.ctl.sim.settings[130] = "320.000"
w.ctl.request_settings()
until(lambda: w.ctl.soft_limits() == (320.0, 440.0))
check("la scheda dichiara $130=320 (profilo 450): il controllo usa la corsa della scheda", w.ctl.soft_limits() == (320.0, 440.0)
      and w.profile.bed_x == 450)
msg = w._soft_limit_problem(fake_job(400, 300))
check("lavoro oltre $130 con i limiti software attivi: blocca prima dell'avvio", bool(msg) and "320" in msg and "$20=1" in msg, str(msg))
block, warn = w.preflight(fake_job(400, 300))
check("il controllo pre-avvio lo mette fra i motivi bloccanti", any("$130/$131" in b for b in block), str(block))
block, warn = w.preflight(fake_job(400, 300, ["Il lavoro esce dall'area di lavoro: spostalo o cambia origine"]))
check("se il lavoro esce già dall'area del profilo non ripete il messaggio", sum("$130" in b for b in block) == 0 and
      any("esce dall'area" in b for b in block), str(block))
check("offset di partenza considerato (piano = uscita + offset)", w._soft_limit_problem(
    types.SimpleNamespace(**{**vars(fake_job(300, 100)), "out_to_bed": (50.0, 0.0)})) is not None)
w.profile.negative_space = True
check("coordinate negative: piano 0..450 → macchina −450..0, corsa scheda −320..0 (vicino all'origine fuori)",
      w._soft_limit_problem(fake_job(300, 100)) is not None and w._soft_limit_problem(
          types.SimpleNamespace(**{**vars(fake_job(440, 100)), "out_to_bed": (130.0, 0.0)})) is not None)
segs_ok = types.SimpleNamespace(**{**vars(fake_job(440, 100)), "preview": types.SimpleNamespace(
    segs=np.array([[140.0, 10.0, 440.0, 100.0, 300, 1, 3000]]))})
check("coordinate negative: lavoro fra 130 e 450 sul piano è dentro −320..0", w._soft_limit_problem(segs_ok) is None)
w.profile.negative_space = None
w.ctl.write_setting(20, 0); w.ctl.request_settings()
until(lambda: w.ctl.soft_limits() is None)
check("con $20=0 nessun blocco per la corsa della scheda", w._soft_limit_problem(fake_job(400, 300)) is None)
w.ctl.sim.settings[130] = "450.000"
w.ctl.write_setting(20, 1)

# ------------------------------------------------------------------ esito della verifica
d = CheckResultDialog([(62, "G0 X470 Y20", "ALARM:2", "Limite software superato")], 103, w)
text = " ".join(l.text() for l in d.findChildren(QLabel))
items = [d.findChild(QListWidget).item(i).text() for i in range(d.findChild(QListWidget).count())]
check("esito: dice che la verifica si è fermata per un allarme alla riga 63", "allarme alla riga 63" in text and "$130/$131" in text, text[:160])
check("esito: la riga mostra ALARM:2 (non «error:ALARM:2»)", items and "ALARM:2" in items[0] and "error:ALARM" not in items[0], str(items))
d2 = CheckResultDialog([(5, "G99", 20, "Comando non supportato")], 10, w)
items2 = [d2.findChild(QListWidget).item(0).text()]
check("esito: gli errori normali restano «error:20»", "error:20" in items2[0], str(items2))
w._pending_start = object()
w._check_done(None)
check("verifica interrotta: niente avvio e stato «Verifica interrotta»", w._pending_start is None and "interrotta" in w.laser.eta.text(),
      w.laser.eta.text())

w.ctl.disconnect_port()
w.qs.setValue("autosave_pending", False)
w.editor.dirty = False
w.close()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
