# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.12.1, dal registro di un Acmer S1 (firmware 1.0.4 del 2025):
- una scheda rimasta in modalità di prova ($C) non riceve un altro $C (la farebbe uscire e muovere davvero, a laser
  spento): FreeLaserCut la fa uscire da sola e aspetta il riavvio;
- se in verifica le risposte smettono di arrivare, la verifica si chiude e la comunicazione diventa prudente;
- buffer grande solo per le schede note; schede senza G55: lavoro in G54 con l'offset tolto."""
import sys, os, time, tempfile, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.grbl import GrblController, SIM_PORT, RX_BUFFER
from freelasercut.core import gcode, material_test
from freelasercut.core.document import Document, RectShape
from freelasercut.profile import MachineProfile
from freelasercut import machines

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()

ACMER_INFO = "[VER:1.0.4,20250409:]\r\n[OPT:VMP,31,511]\r\n[MSG:mechine:MST_MINI]\r\n[MSG:Mode=BT]\r\n"
JOB = ["G90 G21", "M5 S0", "G10 L2 P2 X0 Y0", "G55", "M4 S0"] + \
      [f"G1 X{10 + (i % 40)} Y{10 + i // 40} S300 F3000" for i in range(160)] + ["M5 S0", "G54"]

# ================================================================== buffer
c = GrblController()
c.connect_port(SIM_PORT)
c.sim.speedup = 50
until(lambda: c.board_settings)
check("scheda nota (Longer, LGT): buffer dichiarato usato quasi tutto", c.trusted_buffer and c.rx_buffer == 254, c.rx_buffer)
c.sim.info_text = ACMER_INFO
c.request_info()
until(lambda: any("1.0.4" in l for l in c.board_info))
check("scheda non nota (Acmer, [OPT:…,511]): buffer prudente da 127 byte", not c.trusted_buffer and c.rx_buffer == RX_BUFFER,
      c.rx_buffer)

# ================================================================== scheda rimasta in modalità di prova
c.sim.check_mode = True
c.sim.state = "Check"
sent = []
c.line_sent.connect(lambda l: sent.append(l))
check("scheda trovata in «Check»: FreeLaserCut la fa uscire da sola ($C, riavvio, Idle)",
      until(lambda: not c.sim.check_mode and c.last_status.get("state") == "Idle" and not c.stale_check_exit, 8)
      and sent.count("$C") == 1, sent)
c.sim.check_mode = True
c.sim.state = "Check"
c.stale_check_exit = True  # uscita già in corso
n0 = sent.count("$C")
check("verifica chiesta mentre la scheda è ancora in prova: rifiutata, nessun $C in più",
      c.check_job(JOB) is False and sent.count("$C") == n0 and not c.checking)
fin = []
c.job_finished.connect(lambda ok, msg: fin.append((ok, msg)))
c.stream_job(JOB)
check("lavoro chiesto mentre la scheda è in prova: non parte (prima deve uscire)", fin and fin[-1][0] is False and
      not c.job_active and "prova" in fin[-1][1], fin[-1:])
c.stale_check_exit = False
until(lambda: not c.sim.check_mode and c.last_status.get("state") == "Idle", 8)
pos0 = list(c.sim.pos)

# ================================================================== risposte perse in verifica
done = []
c.check_finished.connect(lambda r: done.append(r))
c.sim.drop_check_after = 60
t0 = time.time()
c.check_job(JOB)
check("verifica con risposte perse: si chiude da sola in pochi secondi", until(lambda: done, 15) and time.time() - t0 < 12,
      f"{time.time() - t0:.1f} s")
r = done[-1] or []
check("…con la spiegazione «la scheda ha smesso di rispondere»", any(e[2] == "NO_RISPOSTA" for e in r), r[-1:])
check("…la comunicazione passa al buffer prudente", c.rx_buffer == RX_BUFFER and c.check_stalled)
check("…la scheda esce dalla modalità di prova", until(lambda: not c.sim.check_mode and c.last_status.get("state") == "Idle", 8))
check("…e la testa non si è mossa", c.sim.pos == pos0, (c.sim.pos, pos0))
c.sim.drop_check_after = None

# ================================================================== G55 sconosciuto
c.sim.no_g55 = True
done.clear()
c.check_job(JOB)
check("scheda senza G55: la verifica segnala error:20 sulla riga G55 e se lo ricorda",
      until(lambda: done, 10) and any(e[2] == 20 and e[1] == "G55" for e in done[-1]) and c.no_g55, done[-1][:2] if done else None)
c.disconnect_port()

doc = Document()
r1 = RectShape(20, 10)
r1.apply(QTransform.fromTranslate(30, 40))
doc.add(r1)
prof = MachineProfile()
std = gcode.generate(doc, prof, gcode.JobOptions(start_from="absolute"))
nog = gcode.generate(doc, prof, gcode.JobOptions(start_from="absolute", no_g55=True, g54_offset=(5.0, 7.0)))
check("lavoro normale: G10 L2 P2 + G55 come prima", "G55" in std.lines and "G10 L2 P2 X0 Y0" in std.lines)
check("senza G55: niente G55 né G10, si lavora in G54", "G55" not in nog.lines and not any(l.startswith("G10") for l in nog.lines)
      and "G54" in nog.lines)
import re
def first_xy(lines):
    for l in lines:
        m = re.match(r"^G[01] X(-?[\d.]+) Y(-?[\d.]+)", l)
        if m:
            return float(m.group(1)), float(m.group(2))
a, b = first_xy(std.lines), first_xy(nog.lines)
check("senza G55: coordinate spostate dell'offset G54 della scheda (stesso punto sul piano)",
      abs((a[0] - b[0]) - 5.0) < 1e-3 and abs((a[1] - b[1]) - 7.0) < 1e-3, (a, b))
check("anteprima nello stesso posto del piano", std.bounds == nog.bounds and
      abs(nog.out_to_bed[0] - std.out_to_bed[0] - 5.0) < 1e-9)
acm = machines.preset_profile("Acmer S1 (2,5W / 3,5W / 6W)")
check("profilo pronto Acmer S1: senza G55", acm.no_g55 is True)
mt = material_test.build(material_test.TestSpec(x0=10, y0=10, cols=3, rows=3, cell=5, gap=2), acm)
check("test materiale su Acmer: G54, niente G55", "G55" not in mt.lines and "G54" in mt.lines)

# ================================================================== finestra principale: rifà il lavoro senza G55
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui.dialogs import CheckResultDialog
w = MainWindow()
w.editor.doc.add(RectShape(20, 10))
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings)
w.profile.negative_space = False
w.ctl.sim.no_g55 = True
w.profile.no_g55 = False
started = []
orig_run = w._run
w._run = lambda lines, plate=None: started.append(list(lines))
w.ctl.homed = True
job = w.build_job()
w._pending_start = job  # come «Verifica e avvia»
w.laser.start_progress("check")
w.ctl.check_job(job.lines)
check("Verifica e avvia su scheda senza G55: FreeLaserCut rifà il lavoro senza G55, lo verifica e lo avvia",
      until(lambda: started, 20) and w.profile.no_g55 and "G55" not in started[0], started[0][:8] if started else None)
check("la scelta resta nel profilo della macchina", MachineProfile.load(w.profile.path()).no_g55 is True)
d = CheckResultDialog([(-1, "", "NO_RISPOSTA", "La scheda ha smesso di rispondere")], 100, w)
check("finestra dell'esito: «la scheda ha smesso di rispondere»", "smesso di rispondere" in d.findChildren(type(d.layout().itemAt(0).widget()))[0].text())
w.ctl.disconnect_port()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
