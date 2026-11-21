# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: velocità a laser spento (domanda di Mauro C.; Ale: «su alcuni laser quel movimento veloce può creare
problemi di vibrazione, spostare il pezzo o sforzare il laser»).

a) Livelli Riempimento e Immagine, «Velocità costante anche a laser spento»: dentro il riempimento i vuoti di ogni
   lunghezza e il cambio di riga in G1 S0 alla velocità del livello; veloce solo l'arrivo alla prima riga.
b) Pannello Laser, «Spostamenti a vuoto più lenti» (nel profilo della macchina): tutti gli spostamenti a vuoto del lavoro
   e del Contorno in G1 S0 alla velocità scelta, mai G0 in X e Y.
Tutte e due spente di partenza: G-code identico bit per bit a quello della 0.21.1 (se c'è git).
Uso: python tests/test_v212_velocita.py [classica|banco]
"""
import os
import re
import subprocess
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import CutSettings, Document, EllipseShape, RectShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info else ""), flush=True)


def at(s, x, y):
    s.set_transform(QTransform.fromTranslate(x, y))
    return s


def moves(lines):
    """[(g, x0, y0, x1, y1, s, f)] di ogni spostamento in X/Y del G-code assoluto."""
    x = y = 0.0
    s = f = 0.0
    g = 0
    out = []
    for raw in lines:
        line = raw.split(";")[0].strip()
        if not line or line.startswith(("G10", "G92", "$")):
            continue
        mg = re.match(r"(?:G53\s+)?G0*([0-3])\b", line)
        if mg:
            g = int(mg.group(1))
        for k, var in (("S", "s"), ("F", "f")):
            m = re.search(k + r"(-?\d+(?:\.\d+)?)", line)
            if m:
                if var == "s":
                    s = float(m.group(1))
                else:
                    f = float(m.group(1))
        mx, my = re.search(r"X(-?\d+(?:\.\d+)?)", line), re.search(r"Y(-?\d+(?:\.\d+)?)", line)
        if (mx or my) and g in (0, 1):
            nx = float(mx.group(1)) if mx else x
            ny = float(my.group(1)) if my else y
            out.append((g, x, y, nx, ny, s, f))
            x, y = nx, ny
    return out


def fill_span(mv, speed=2000.0):
    """Indici della prima e dell'ultima riga accesa del riempimento (riconosciuto dalla sua velocità)."""
    lit = [i for i, m in enumerate(mv) if m[0] == 1 and m[5] > 0 and (speed is None or m[6] == speed)]
    return (lit[0], lit[-1]) if lit else (0, -1)


def make_doc(mode="fill"):
    doc = Document()
    cs = doc.layer(1)
    cs.mode, cs.speed, cs.power_max, cs.interval, cs.overscan = mode, 2000.0, 40.0, 1.0, 2.0
    doc.add(at(RectShape(20, 10, layer=1), 30, 30))  # due rettangoli sulla stessa fascia, vuoto di 40 mm fra loro
    doc.add(at(RectShape(20, 10, layer=1), 90, 30))
    doc.add(at(EllipseShape(12, 12, layer=1), 200, 140))  # una forma lontana
    lc = doc.layer(2)
    lc.mode, lc.speed, lc.power_max = "line", 800.0, 90.0
    doc.add(at(RectShape(15, 15, layer=2), 150, 30))
    return doc


prof = MachineProfile(name="P", bed_x=300.0, bed_y=200.0, s_max=1000.0)
prof.max_rate_x = prof.max_rate_y = 12000.0


def job(doc, p=prof, **kw):
    return gcode.generate(doc, p, gcode.JobOptions(**kw)).lines


# ====================================================================== spente: come la 0.21.1
print("--- spente")
check("di partenza tutte e due spente", CutSettings().steady_travel is False and MachineProfile().slow_travel is False
      and MachineProfile().travel_speed() is None)
base = job(make_doc())
mv = moves(base)
a, b = fill_span(mv)
check("spente: nel riempimento ci sono ancora gli spostamenti veloci (G0) fra i due rettangoli",
      any(m[0] == 0 for m in mv[a:b]))
script = r'''
import os, sys, json
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1]); sys.path.insert(1, sys.argv[2])
from PySide6.QtWidgets import QApplication
app = QApplication([])
import test_v212_velocita_doc as d
print(json.dumps(d.lines()))
'''
helper = os.path.join(tempfile.mkdtemp(), "test_v212_velocita_doc.py")
with open(helper, "w", encoding="utf-8") as fh:
    fh.write('''
from PySide6.QtGui import QTransform
from freelasercut.core import gcode
from freelasercut.core.document import Document, EllipseShape, RectShape
from freelasercut.profile import MachineProfile
def at(s, x, y):
    s.set_transform(QTransform.fromTranslate(x, y)); return s
def lines():
    out = []
    if True:
        doc = Document(); cs = doc.layer(1)
        cs.mode, cs.speed, cs.power_max, cs.interval, cs.overscan = "fill", 2000.0, 40.0, 1.0, 2.0
        doc.add(at(RectShape(20, 10, layer=1), 30, 30)); doc.add(at(RectShape(20, 10, layer=1), 90, 30))
        doc.add(at(EllipseShape(12, 12, layer=1), 200, 140))
        lc = doc.layer(2); lc.mode, lc.speed, lc.power_max = "line", 800.0, 90.0
        doc.add(at(RectShape(15, 15, layer=2), 150, 30))
        p = MachineProfile(name="P", bed_x=300.0, bed_y=200.0, s_max=1000.0); p.max_rate_x = p.max_rate_y = 12000.0
        for cmd in ("M4", "M3"):
            out.append(gcode.generate(doc, p, gcode.JobOptions(laser_cmd=cmd)).lines)
    return out
''')
old = None
try:
    tree = tempfile.mkdtemp()
    ok_git = subprocess.run(["git", "-C", ROOT, "worktree", "add", "-f", "--detach", tree, "v0.21.1"],
                            capture_output=True, text=True, timeout=120).returncode == 0
    if ok_git:
        r = subprocess.run([sys.executable, "-c", script, tree, os.path.dirname(helper)], capture_output=True,
                           text=True, timeout=300)
        import json

        old = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
        subprocess.run(["git", "-C", ROOT, "worktree", "remove", "--force", tree], capture_output=True, timeout=120)
except (OSError, subprocess.SubprocessError, ValueError):
    old = None
sys.path.insert(0, os.path.dirname(helper))
import test_v212_velocita_doc as same  # noqa: E402

now = same.lines()
if old is not None:
    check("caselle spente: G-code identico bit per bit alla 0.21.1 (riempimento e linee, M4 e M3)", now == old,
          [i for i, (x, y) in enumerate(zip(now, old)) if x != y])
else:
    print("(niente git o tag v0.21.1: confronto con la 0.21.1 saltato)")

# ====================================================================== a) livello
print("--- a) velocità costante nel riempimento")
for mode in ("fill", "image"):
    if mode == "image":
        continue  # le immagini vere sotto; qui le forme vettoriali in Riempimento
    doc = make_doc()
    doc.layer(1).steady_travel = True
    doc.layer(1).fill_grouping = "each"
    mv_each = moves(job(doc))
    ea, eb = fill_span(mv_each)
    check("«Forma per forma»: dentro il riempimento solo i salti fra una forma e l'altra restano veloci (3 forme, 2 salti)",
          sum(1 for m in mv_each[ea:eb] if m[0] == 0) == 2, [m for m in mv_each[ea:eb] if m[0] == 0])
    doc.layer(1).fill_grouping = "together"
    lines = job(doc)
    mv = moves(lines)
    a, b = fill_span(mv)
    inside = mv[a:b + 1]
    check("acceso: fra la prima e l'ultima riga del riempimento nessun G0", not any(m[0] == 0 for m in inside),
          [m for m in inside if m[0] == 0][:2])
    off = [m for m in inside if m[0] == 1 and m[5] == 0]
    check("…i tratti a laser spento sono G1 S0 alla velocità del livello (2000)", off and all(m[6] == 2000.0 for m in off),
          {m[6] for m in off})
    check("…l'arrivo al riempimento e lo spostamento verso il livello dopo restano veloci (G0)",
          mv[a - 1][0] == 0 or any(m[0] == 0 for m in mv[:a]) and any(m[0] == 0 for m in mv[b + 1:]))
    d0 = make_doc()
    d0.layer(1).fill_grouping = "together"
    burn_off = [(m[1:5]) for m in moves(job(d0)) if m[0] == 1 and m[5] > 0]
    burn_on = [(m[1:5]) for m in mv if m[0] == 1 and m[5] > 0]
    check("…stesse righe accese, stessa potenza", burn_off == burn_on)
    doc.layer(1).bidirectional = False
    mv2 = moves(job(doc))
    a2, b2 = fill_span(mv2)
    check("anche non bidirezionale (ritorno a inizio riga a laser spento, lento)", not any(m[0] == 0 for m in mv2[a2:b2]))
    doc.layer(1).bidirectional, doc.layer(1).crosshatch = True, True
    mv3 = moves(job(doc))
    check("con le passate incrociate: nessun G0 dentro ognuna delle due passate (solo fra l'una e l'altra)",
          sum(1 for m in mv3[fill_span(mv3)[0]:fill_span(mv3)[1]] if m[0] == 0) <= 4)
    for cmd in ("M3", "M4"):
        ls = job(doc, laser_cmd=cmd)
        check(f"{cmd}: tutti i tratti a laser spento hanno S0", all(m[5] == 0 for m in moves(ls) if m[0] == 1
                                                                       and m[5] < 1 and m[5] != 0) is True)

# immagine: due macchie su una foto, con un vuoto in mezzo
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from freelasercut.core.document import ImageShape  # noqa: E402

pix = np.full((40, 200), 255, np.uint8)
pix[5:35, 10:50] = 0
pix[5:35, 150:190] = 0
d = Document()
d.images["p"] = Image.fromarray(pix)
ci = d.layer(1)
ci.mode, ci.speed, ci.power_max, ci.dpi, ci.dither = "image", 3000.0, 30.0, 127.0, "threshold"
d.add(at(ImageShape("p", 40.0, 8.0, layer=1), 20, 20))
mv_img_off = moves(job(d))
ci.steady_travel = True
mv_img = moves(job(d))
ia, ib = fill_span(mv_img, None)
check("Immagine: con la casella accesa nessun G0 dentro la foto, i vuoti a 3000 mm/min",
      ia < ib and not any(m[0] == 0 for m in mv_img[ia:ib]) and all(m[6] == 3000.0 for m in mv_img[ia:ib] if m[5] == 0),
      [m for m in mv_img[ia:ib] if m[0] == 0][:2])
check("Immagine: spenta, i vuoti larghi restano veloci", any(m[0] == 0 for m in mv_img_off[fill_span(mv_img_off, None)[0]:fill_span(mv_img_off, None)[1]]))
c2 = CutSettings.from_dict({**CutSettings().to_dict(), "steady_travel": "sì"})
check("file rovinato: valore strano = spenta", c2.steady_travel is False)
c3 = CutSettings.from_dict({**CutSettings().to_dict(), "steady_travel": True})
check("salvata e riletta nel progetto", c3.steady_travel is True)

# ====================================================================== b) macchina
print("--- b) spostamenti a vuoto più lenti")
ps = MachineProfile(name="P", bed_x=300.0, bed_y=200.0, s_max=1000.0)
ps.max_rate_x = ps.max_rate_y = 12000.0
ps.slow_travel, ps.travel_feed = True, 2500.0
check("velocità scelta", ps.travel_speed() == 2500.0)
for v, want in ((50.0, 100.0), (50000.0, 12000.0), ("x", 3000.0), (float("nan"), 3000.0)):
    ps.travel_feed = v
    check(f"velocità {v!r} → {want:g} (fra 100 e la massima della macchina)", ps.travel_speed() == want, ps.travel_speed())
ps.travel_feed = 2500.0
for cmd in ("M4", "M3"):
    lines = job(make_doc(), p=ps, laser_cmd=cmd)
    mv = moves(lines)
    check(f"{cmd}: nessun G0 in X e Y in tutto il lavoro, anche andata all'inizio e ritorno a casa",
          not any(m[0] == 0 for m in mv) and not any(re.match(r"G0\s.*[XY]", ln) for ln in lines), [m for m in mv if m[0] == 0][:2])
    off = [m for m in mv if m[0] == 1 and m[5] == 0 and (m[1], m[2]) != (m[3], m[4])]
    fills = {doc_speed for doc_speed in (2000.0,)}
    check(f"{cmd}: ogni spostamento a laser spento ha S0 e va al massimo a 2500 mm/min (o alla velocità del riempimento)",
          off and all(m[6] <= 2500.0 or m[6] in fills for m in off), sorted({m[6] for m in off}))
burn_slow = [(m[1:5], m[5]) for m in moves(job(make_doc(), p=ps)) if m[0] == 1 and m[5] > 0]
burn_fast = [(m[1:5], m[5]) for m in moves(job(make_doc())) if m[0] == 1 and m[5] > 0]
check("stesse righe accese, stessa potenza", burn_slow == burn_fast)
j_fast, j_slow = gcode.generate(make_doc(), prof), gcode.generate(make_doc(), ps)
check("la stima del tempo se ne accorge: il lavoro dura di più", j_slow.seconds > j_fast.seconds,
      (round(j_fast.seconds), round(j_slow.seconds)))
ps.slow_travel = "true"
check("valore strano nel profilo = spenta", ps.travel_speed() is None)
ps.slow_travel = True

print("--- Contorno")
from freelasercut.grbl import GrblController  # noqa: E402

ctl = GrblController()
sent = []
ctl.send_line = sent.append
pts = [(10, 10), (60, 10), (60, 40), (10, 40), (10, 10)]
ctl.frame_path(pts, 6000, 0.0, 1000.0)
check("Contorno senza la casella: com'era (jog a 6000)", all("F6000" in s for s in sent) and len(sent) == 5)
del sent[:]
ctl.frame_path(pts, 6000, 0.0, 1000.0, travel_feed=2500.0)
check("Contorno con la casella: al massimo 2500 mm/min", all("F2500" in s for s in sent), sent[:2])
del sent[:]
ctl.frame_path(pts, 6000, 5.0, 1000.0, travel_feed=2500.0)
check("Contorno con il filo di laser: l'andata al primo punto è G1 S0, non G0", sent[0].startswith("G53 G1") and " S0 " in sent[0]
      + " " and not any(s.startswith("G53 G0") for s in sent), sent[:2])

# ====================================================================== interfaccia
print("--- interfaccia")
from freelasercut.ui.main_window import MainWindow  # noqa: E402
from freelasercut.ui.panels_design import CutSettingsDialog  # noqa: E402

w = MainWindow()
cs = w.editor.doc.layer(1)
dlg = CutSettingsDialog(cs, w.profile, w)
check("finestra del livello: la casella c'è nelle schede Riempimento e Immagine, spenta",
      not dlg.steady.isChecked() and not dlg.steady_i.isChecked())
dlg.mode.setCurrentIndex(dlg.mode.findData("fill"))
dlg.steady.setChecked(True)
check("…accesa in Riempimento passa nel livello", dlg.values()["steady_travel"] is True)
dlg.mode.setCurrentIndex(dlg.mode.findData("image"))
check("…in Immagine vale la sua casella", dlg.values()["steady_travel"] is False)
dlg.close()
lp = w.laser
check("pannello Laser: «Spostamenti a vuoto più lenti» spenta, velocità 3000 non modificabile",
      not lp.slow_travel.isChecked() and lp.travel_feed.value() == 3000.0 and not lp.travel_feed.isEnabled())
lp.travel_feed.setValue(2000.0)
lp.slow_travel.setChecked(True)
check("accesa: si salva nel profilo della macchina, velocità modificabile", w.profile.slow_travel is True
      and w.profile.travel_speed() == 2000.0 and lp.travel_feed.isEnabled())
lp.travel_feed.setValue(4000.0)
lp.travel_feed.editingFinished.emit()
check("cambio della velocità: nel profilo", w.profile.travel_feed == 4000.0)
other = MachineProfile(name="Altro", bed_x=200.0, bed_y=200.0)
w.set_active_profile(other)
check("cambiando macchina la casella segue il profilo nuovo (spenta)", not lp.slow_travel.isChecked())
w.editor.dirty = False

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
