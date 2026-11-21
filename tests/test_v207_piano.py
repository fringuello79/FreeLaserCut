# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.7, funzione in prova: G-code «del piano» scritto da un programma esterno e adattato al laser del profilo
(`core/plane_gcode.py`, `MainWindow._plane_gcode`). Prima stava dentro la prova di un collegamento sperimentale, tolto dalla
versione pubblica.
Uso: python tests/test_v207_piano.py [classica|banco]
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core import plane_gcode  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "")


def near(a, b, tol=1e-3):
    return abs(a - b) <= tol


print("--- G-code del piano")
from freelasercut.profile import MachineProfile  # noqa: E402

p = MachineProfile(name="P", bed_x=300.0, bed_y=200.0, s_max=1000.0, optical_power="20 W", max_rate_x=6000.0,
                   max_rate_y=6000.0)
src = [plane_gcode.MARK, "; potenza-W=10", "; nome=prova", "G0 X10 Y20", "G1 X50 Y20 S800 F3000",
       "G1 X50 Y60 S500 F12000", "G0 X-15 Y60", "G1 X-14 Y60 S0", "M3 S1000", "G0 X10 Y20"]
out, rep = plane_gcode.convert(src, p)
check("riconosciuto dalla riga del segno", plane_gcode.is_plane(src) and not plane_gcode.is_plane(["G0 X0"]))
check("potenza riportata ai watt: 80 % per 10 W = 40 % su 20 W", "G1 X50 Y20 S400 F3000" in out and near(rep["ratio"], 0.5))
check("oltre la velocità massima: rallentato e potenza abbassata nella stessa proporzione (12000 → 6000, 50 % → 12,5 %)",
      "G1 X50 Y60 S125 F6000" in out and rep["capped"] == 1)
check("spostamenti spenti fuori dal piano portati sul bordo", "G0 X0 Y60" in out and rep["clamped"] == 2)
check("comandi diversi da G0/G1 nel file ignorati (M3 S1000)", not [x for x in out if x.startswith("M3")])
check("sistema assoluto e potenza che segue la velocità come i lavori di FreeLaserCut",
      out[2:8] == ["G90 G21", "M5 S0", "M9", "G10 L2 P2 X0 Y0", "G55", "M4 S0"] and out[-3:] == ["G54", "M9", "; fine"])
check("ingombro e nome", rep["box"] == (10.0, 20.0, 50.0, 60.0) and rep["name"] == "prova")
pr = MachineProfile(name="R", bed_x=300.0, bed_y=200.0, optical_power="10 W")
pr.invert_y = True
out2, _r = plane_gcode.convert(src, pr)
check("assi invertiti del profilo: Y della macchina = corsa − Y del piano", "G1 X50 Y180 S800 F3000" in out2)
out3, _r = plane_gcode.convert(src, pr, no_g55=True, g54_offset=(5.0, 7.0))
check("scheda senza G55: G54 e offset tolto", "G54" in out3[:8] and "G55" not in out3 and "G1 X45 Y173 S800 F3000" in out3)
try:
    plane_gcode.convert(src[:3] + ["G0 X10 Y10", "G1 X310 Y10 S100 F600"], p)
    ok = False
except plane_gcode.OutsideBed:
    ok = True
check("tratto acceso fuori dal piano: il lavoro non si fa", ok)
try:
    plane_gcode.convert(src[:3] + ["G0 X10 Y10", "G1 X20 Y10 S0 F600"], p)
    ok = False
except ValueError:
    ok = True
check("niente da incidere: errore", ok)
pw = MachineProfile(name="W", bed_x=300.0, bed_y=200.0, optical_power="")
out4, rep4 = plane_gcode.convert(src, pw)
check("profilo senza watt: potenze come nel file", "G1 X50 Y20 S800 F3000" in out4 and rep4["ratio"] == 1.0)
pk = MachineProfile(name="K", bed_x=300.0, bed_y=200.0, optical_power="5 W")
out5, rep5 = plane_gcode.convert(src, pk)
check("laser più debole: oltre il 100 % si ferma al 100 % e lo dice", "G1 X50 Y20 S1000 F3000" in out5 and rep5["s_limited"] == 1)
out6, _r = plane_gcode.convert([plane_gcode.MARK, "G0 X1 Y1", "G1 X2 Y1 S500"], pw)
check("G1 senza velocità: 1000 mm/min (GRBL non parte senza F)", "G1 X2 Y1 S500 F1000" in out6)

print("--- nel programma")
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
from PySide6.QtWidgets import QMessageBox  # noqa: E402

said = []
QMessageBox.warning = staticmethod(lambda *a, **k: said.append(a[2]) or QMessageBox.Ok)
QMessageBox.information = staticmethod(lambda *a, **k: said.append(a[2]) or QMessageBox.Ok)
from freelasercut import admin  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
gpath = os.path.join(TMP, "piano.gcode")
with open(gpath, "w", encoding="utf-8") as fh:
    fh.write("\n".join(src) + "\n")
said.clear()
w.run_gcode_file(gpath)
check("G-code del piano con le funzioni bloccate: non si usa e lo dice", said and "in prova" in said[-1]
      and w.canvas.preview is None if hasattr(w.canvas, "preview") else bool(said))
admin.set_unlocked(w.qs, True)
w._apply_admin()
lines_conv, note = w._plane_gcode(src, "piano.gcode")
check("G-code del piano sbloccato: adattato al profilo attivo, con la nota per la conferma", lines_conv is not None
      and "G55" in lines_conv and "Longer" in note or (lines_conv is not None and w.profile.name in note))
said.clear()
out_bad, _n = w._plane_gcode(src[:3] + ["G0 X10 Y10", "G1 X900 Y10 S100 F600"], "x.gcode")
check("fuori dal piano: avviso e nessun lavoro", out_bad is None and said and "esce dal piano" in said[-1])


print("--- traduzioni")
import json  # noqa: E402

missing = []
keys = ["G-code del piano, adattato a «{0}»."]
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    for key in keys:
        if not cat.get(key):
            missing.append((lang, key))
check("le voci ci sono nelle 4 lingue", not missing, missing[:6])

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
