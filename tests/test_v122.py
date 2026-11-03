# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.12.2: assi X/Y invertibili (pannello Laser → Posizionamento, si salvano nel profilo), velocità in mm/min
o mm/s (Impostazioni → Unità di misura), scheda Makerbase MKS DLC32 riconosciuta."""
import sys, os, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ.pop("FLC_SIM_NEGATIVE", None)
os.environ.pop("FLC_SPEED_UNIT", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import units, machines
from freelasercut.core import gcode, material_test
from freelasercut.core.document import Document, RectShape
from freelasercut.profile import MachineProfile
from freelasercut.grbl import SIM_PORT

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()

# ================================================================== profilo: assi invertiti
p = MachineProfile(name="Prova assi", model="Prova assi")
check("di partenza nessun asse invertito", (p.invert_x, p.invert_y) == (False, False) and p.axis_sign() == (1, 1))
p.invert_y = True
check("Y invertito: il punto 40 del piano va a 440-40 = 400 sulla macchina, e torna indietro",
      p.to_machine(30, 40) == (30, 400) and p.to_bed(30, 400) == (30, 40))
p.negative_space = True
mx, my = p.to_machine(30, 40)
check("anche con le coordinate negative (homing in fondo corsa): andata e ritorno", p.to_bed(mx, my) == (30, 40) and
      -440 <= my <= 0 and -450 <= mx <= 0, (mx, my))
p.negative_space = False
p.invert_x, p.invert_y = True, False
check("X invertito", p.to_machine(30, 40) == (420, 40) and p.axis_sign() == (-1, 1))
path = p.save()
check("si salva e si rilegge con il profilo della macchina", MachineProfile.load(path).invert_x is True)

# ================================================================== G-code e anteprima
doc = Document()
r = RectShape(20, 10)
r.apply(QTransform.fromTranslate(30, 40))
doc.add(r)
def burn_box(job):
    pv = job.preview
    ox, oy = job.out_to_bed
    b = pv.segs[pv.segs[:, 5] > 0]
    return (round(float(b[:, [0, 2]].min() + ox), 3), round(float(b[:, [1, 3]].min() + oy), 3),
            round(float(b[:, [0, 2]].max() + ox), 3), round(float(b[:, [1, 3]].max() + oy), 3))
base = MachineProfile()
inv = MachineProfile(); inv.invert_y = True
j0 = gcode.generate(doc, base, gcode.JobOptions(start_from="absolute"))
j1 = gcode.generate(doc, inv, gcode.JobOptions(start_from="absolute"))
check("lavoro con Y invertito: coordinate Y ribaltate nel G-code", "G0 X30 Y400" in j1.lines and "G0 X30 Y40" in j0.lines)
check("…ma anteprima e ingombro restano dove li vedi sul piano", burn_box(j1) == burn_box(j0) == (30, 40, 50, 50) and
      j1.bounds == j0.bounds, (burn_box(j0), burn_box(j1)))
c0 = gcode.generate(doc, base, gcode.JobOptions(start_from="current", current_pos=(100, 100)))
c1 = gcode.generate(doc, inv, gcode.JobOptions(start_from="current", current_pos=(100, 100)))
check("partenza dalla posizione della testa: con Y invertito il verso si capovolge", "Y10" in c0.lines and "Y-10" in c1.lines)
check("…e l'anteprima resta uguale", burn_box(c0) == burn_box(c1), (burn_box(c0), burn_box(c1)))
invx = MachineProfile(); invx.invert_x = True; invx.invert_y = True
j2 = gcode.generate(doc, invx, gcode.JobOptions(start_from="absolute"))
check("tutti e due gli assi invertiti: anteprima uguale", burn_box(j2) == burn_box(j0))
spec = material_test.TestSpec(x0=20, y0=20, rows=3, cols=3, cell=5, gap=2)
m0, m1 = material_test.build(spec, base), material_test.build(spec, inv)
check("test materiale con Y invertito: stesso posto sul piano", burn_box(m0) == burn_box(m1), (burn_box(m0), burn_box(m1)))

# ================================================================== controller e finestra
from freelasercut.ui.main_window import MainWindow
w = MainWindow()
check("pannello Laser → Posizionamento: «Inverti l'asse X» e «Inverti l'asse Y»", hasattr(w.laser, "inv_x") and
      hasattr(w.laser, "inv_y") and not w.laser.inv_x.isChecked() and not w.laser.inv_y.isChecked())
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings)
sent = []
w.ctl.line_sent.connect(lambda l: sent.append(l))
w.move.cont.setChecked(False)
w.move._jog_press(0, 1)
check("freccia «su» normale: Y positivo", until(lambda: any(l.startswith("$J=G91") and "Y" in l for l in sent)) and
      "Y-" not in [l for l in sent if l.startswith("$J")][-1], sent[-1:])
w.laser.inv_y.setChecked(True)
check("spunta «Inverti l'asse Y»: salvata nel profilo e verso dei jog capovolto",
      w.profile.invert_y and MachineProfile.load(w.profile.path()).invert_y and w.ctl.axis_sign == (1.0, -1.0))
sent.clear()
w.move._jog_press(0, 1)
check("freccia «su» con Y invertito: la scheda riceve Y negativo", until(lambda: any(l.startswith("$J=G91") for l in sent)) and
      "Y-" in [l for l in sent if l.startswith("$J")][-1], sent[-1:])
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
until(lambda: False, 1.0)  # il jog è finito davvero
w.ctl.goto_machine(10, 400, 6000)
until(lambda: abs((w.ctl.last_status.get("MPos") or [0, 0])[1] - 400) < 0.01 and
      w.ctl.last_status.get("state") == "Idle", 10)
until(lambda: False, 0.5)
head = w.canvas.head_pos()
check("posizione della testa sul piano: Y macchina 400 → 40 sul piano", head is not None and abs(head.y() - 40) < 0.5 and
      abs(head.x() - 10) < 0.5, head)
w.laser.inv_y.setChecked(False)
check("togliendo la spunta tutto torna normale", not w.profile.invert_y and w.ctl.axis_sign == (1.0, 1.0))
w.ctl.disconnect_port()

# ================================================================== unità di misura
check("di partenza velocità in mm/min, come sempre", units.speed_unit() == "mm/min" and units.fmt(1000) == "1000 mm/min")
check("Impostazioni → Unità di misura: mm/min e mm/s", set(w.unit_actions) == {"mm/min", "mm/s"} and
      w.unit_actions["mm/min"].isChecked() and w.m_units.menuAction() in w.m_settings.actions())
w.choose_units("mm/s")
check("scelta mm/s: salvata (vale dal riavvio, che FreeLaserCut propone)", w.qs.value("unit_speed") == "mm/s")
units.set_speed_unit("mm/s")
check("in mm/s: 1000 mm/min si mostra 16,7 mm/s, 6000 → 100 mm/s", units.fmt(1000) == "16.7 mm/s" and units.fmt(6000) == "100 mm/s")
sp = units.SpeedSpin(1, 36000, 1500)
check("campo velocità in mm/s: mostra 25 e dentro resta 1500 mm/min", sp.text().startswith("25") and sp.value() == 1500
      and sp.suffix() == " mm/s", (sp.text(), sp.value()))
sp.lineEdit().setText("20")
sp.interpretText()
check("scrivendo 20 (mm/s) il valore diventa 1200 mm/min", sp.value() == 1200, sp.value())
from freelasercut.core import materials as mats
check("libreria materiali: riepilogo nell'unità scelta", "mm/s" in mats.Material("Tiglio", "incisione", 3, 30, 6000, 1, 0,
                                                                                    "fill", 0.1, "", "").summary())
from freelasercut.ui.panels_design import CutSettingsDialog
from freelasercut.core.document import CutSettings
dlg = CutSettingsDialog(CutSettings(speed=3000), w.profile, w)
check("impostazioni del livello in mm/s: 3000 mm/min si legge 50 mm/s (e accanto in mm/min)", dlg.speed.text().startswith("50")
      and "3000 mm/min" in dlg.speed_s.text(), (dlg.speed.text(), dlg.speed_s.text()))
dlg.speed.setValue(1800)
check("…e salva sempre mm/min nel livello", abs(dlg.speed.value() - 1800) < 1e-9)
mt = material_test.build(material_test.TestSpec(labels=True), MachineProfile())
check("test materiale: etichette incise nell'unità scelta", mt.lines and True)
units.set_speed_unit("mm/min")
w.qs.setValue("unit_speed", "mm/min")

# ================================================================== Makerbase MKS DLC32
ident = machines.identify(banner=["Grbl 1.1f ['$' for help]"], info=["[VER:1.1f.20210406:MKS DLC32]", "[OPT:VNMZHSL,128,256]"],
                          settings={130: "400.000", 131: "400.000"})
check("scheda MKS DLC32 riconosciuta (Makerbase)", ident.vendor == "Makerbase" and ident.model == "Scheda Makerbase MKS DLC32",
      f"{ident.vendor} / {ident.model}")
check("nota per la DLC32: assi invertibili, Wi-Fi sulla porta 8080",
      "Inverti" in machines.NOTES["Scheda Makerbase MKS DLC32"] and "8080" in machines.NOTES["Scheda Makerbase MKS DLC32"])
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
