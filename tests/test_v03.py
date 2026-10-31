# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""v0.3: libreria materiali, test materiale, vettorizzazione, testo variabile, testo curvo."""
import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtGui import QGuiApplication, QTransform  # noqa: E402

app = QGuiApplication([])
from freelasercut.core import geom, material_test as mtest, materials as mats, ops, text as tm, trace, variables  # noqa: E402
from freelasercut.core.document import CutSettings, Document, TextShape  # noqa: E402
from freelasercut.grbl import SIM_PORT, GrblController  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

R = []


def check(name, ok, info=""):
    R.append(bool(ok))
    print(("  OK  " if ok else "  KO  ") + name, info)


def spin(sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


# ------------------------------------------------------------ libreria
lib = mats.library()
check("libreria Longer B1 40W caricata", len(lib) >= 50, f"{len(lib)} voci")
tig = [m for m in lib if m.name.startswith("Tiglio") and m.operation == "taglio" and m.thickness == 3][0]
check("Tiglio 3 mm: 100% a 1400 mm/min", tig.power == 100 and tig.speed == 1400)
cs = CutSettings(index=1, mode="fill")
mats.apply_to_layer(tig, cs)
check("applica al livello: modalità, potenza, velocità, aria", cs.mode == "line" and cs.speed == 1400 and cs.power_max == 100 and cs.air)
mine = mats.Material("Tiglio (basswood)", "taglio", 3, 92, 1500, 1, 0, "line", 0.1, "provato", "Personale")
mats.save_user([mine])
again = [m for m in mats.library() if m.key() == mine.key()]
check("voce personale sostituisce quella Longer", len(again) == 1 and again[0].power == 92)

# ------------------------------------------------------------ test materiale
for negative in (False, True):
    tag = " [coord. negative]" if negative else ""
    prof = MachineProfile()
    prof.negative_space = negative
    spec = mtest.TestSpec(rows=3, cols=3, cell=6, gap=2, x0=30, y0=40, title="Prova", border=True)
    job = mtest.build(spec, prof)
    os.environ["FLC_SIM_NEGATIVE"] = "1" if negative else "0"
    c = GrblController()
    res = {}
    c.job_finished.connect(lambda ok, m: res.update(ok=ok))
    c.error_raised.connect(lambda code, t, l: res.setdefault("err", []).append((code, l)))
    c.connect_port(SIM_PORT)
    spin(2.0)
    c.sim.speedup = 60
    c.home()
    spin(1.0 if not negative else 8)
    c.sim.burn_marks.clear()
    c.stream_job(job.lines)
    t = time.time()
    while "ok" not in res and time.time() - t < 240:
        spin(0.05)
    marks = np.array([c.sim.to_bed(x, y) for x, y in c.sim.burn_marks]) if c.sim.burn_marks else np.zeros((0, 2))
    c.disconnect_port()
    spin(0.2)
    b = job.bounds
    inside = len(marks) and marks[:, 0].min() >= b.left() - 0.05 and marks[:, 0].max() <= b.right() + 0.05
    check("test materiale eseguito sul simulatore" + tag, res.get("ok") and not res.get("err") and inside,
          f"{len(job.lines)} righe · {job.seconds:.0f} s · ingombro {b.width():.1f}×{b.height():.1f} mm")
# ordine: dal quadrato più leggero
prof = MachineProfile()
job = mtest.build(mtest.TestSpec(rows=3, cols=3, labels=False), prof)
import re  # noqa: E402

burn = [float(m.group(1)) for l in job.lines if l.startswith(("G1", "X")) for m in [re.search(r"S([\d.]+)", l)] if m and float(m.group(1)) > 0]
first_s = burn[0]
check("prima cella incisa = la più leggera (10%)", abs(first_s - 0.10 * prof.s_max) < 1, f"S{first_s:g}")

# ------------------------------------------------------------ vettorizzazione
img = np.full((300, 300), 255, np.uint8)
cv2.circle(img, (150, 150), 100, 0, -1)
cv2.circle(img, (150, 150), 40, 255, -1)
dark = 1 - img.astype(np.float32) / 255
path, info = trace.trace(dark, 30, 30, "outline")
area = sum(abs(p.area()) * (1 if i == 0 else -1) for i, p in enumerate(sorted(geom.flatten(path, 0.01), key=lambda p: -abs(p.area()))))
expect = math.pi * (10 ** 2 - 4 ** 2)
check("contorno: anello Ø20/Ø8 mm, area corretta", abs(area - expect) / expect < 0.02 and info["curves"] == 2,
      f"{area:.1f} mm² (atteso {expect:.1f}) · {info['nodes']} nodi")
b = path.boundingRect()
check("contorno: posizione e misura", abs(b.width() - 20) < 0.2 and abs(b.center().x() - 15) < 0.1 and abs(b.center().y() - 15) < 0.1,
      f"{b.width():.2f} mm")
img = np.full((200, 400), 255, np.uint8)
cv2.line(img, (40, 100), (360, 100), 0, 14)
path, info = trace.trace(1 - img.astype(np.float32) / 255, 40, 20, "centerline")
polys = geom.flatten(path, 0.01)
L = sum(p.length() for p in polys)
ys = [y for p in polys for _, y in p.pts]
check("linea centrale: un tratto spesso diventa una linea sola nel mezzo",
      len(polys) == 1 and abs(L - 32) < 1.5 and max(abs(y - 10) for y in ys) < 0.15, f"{len(polys)} linea, {L:.1f} mm")

# ------------------------------------------------------------ testo variabile
variables.from_dict({"serial": 41, "step": 1, "pad": 3})
t = TextShape("Lotto {N} · {N:5} · {ANNO} · {sconosciuto}", "futural", 5)
check("segnaposto", t.shown_text() == f"Lotto 041 · 00041 · {time.strftime('%Y')} · {{sconosciuto}}", t.shown_text())
csvp = os.path.join(tempfile.mkdtemp(), "n.csv")
with open(csvp, "w", encoding="utf-8") as fh:
    fh.write("Nome;Ruolo\nAnna;Capitano\nLuca;Portiere\n")
variables.load_csv(csvp)
t2 = TextShape("{Nome} ({ruolo}) #{N}", "futural", 5)
copies = ops.grid_array([t2], 2, 2, 3, 3)
shown = [t2.shown_text()] + [x.shown_text() for x in copies]
check("serie a griglia numerata e CSV a rotazione", shown == ["Anna (Capitano) #041", "Luca (Portiere) #042",
                                                           "Anna (Capitano) #043", "Luca (Portiere) #044"], str(shown))
variables.advance(4)
check("avanzamento dopo il lavoro", t2.shown_text() == "Anna (Capitano) #045", t2.shown_text())
doc = Document()
doc.add(t2)
for cp in copies:
    doc.add(cp)
fp = os.path.join(tempfile.mkdtemp(), "v.flcut")
doc.save(fp)
variables.from_dict(None)
d2 = Document.load(fp)
offs = sorted(s.var_offset for s in d2.shapes)
check("progetto: variabili e copie salvate", variables.STATE["serial"] == 45 and len(variables.STATE["rows"]) == 2 and offs == [0, 1, 2, 3])

# ------------------------------------------------------------ testo curvo
plain = tm.text_path("ARCO DI PROVA", "futural", 5)
w = plain.boundingRect().width()
for arc in (90, -120):
    bent = tm.bend_path(plain, arc)
    R_ = tm.bend_radius(plain, arc)
    # i punti della linea di base (y≈0) stanno sul cerchio di raggio R centrato in (cx, -R)
    cx = plain.boundingRect().center().x()
    pts = [p for pl in geom.flatten(bent, 0.01) for p in pl.pts]
    dist = [math.hypot(x - cx, y + R_) for x, y in pts]
    check(f"testo curvo {arc:+d}°: lettere tra raggio R e R+altezza", min(dist) >= abs(R_) - (5.1 if R_ < 0 else 0.1)
          and max(dist) <= abs(R_) + (5.1 if R_ > 0 else 0.1), f"R={R_:.1f} mm")
ts = TextShape("TUTTO INTORNO · ", "futural", 4, arc=360)
bb = ts.path().boundingRect()
check("testo a cerchio intero (360°)", abs(bb.width() - bb.height()) < 1.0, f"{bb.width():.1f}×{bb.height():.1f} mm")

print(f"\n{sum(R)}/{len(R)} superati")
sys.exit(0 if all(R) else 1)
