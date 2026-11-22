# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.1: dal messaggio di Evoluzione2 (foto con l'effetto Matita: la testa va a scatti).

Nelle righe di una foto o di un riempimento un vuoto lungo si salta veloce (G0) con una rincorsa prima e dopo.
Prima il salto veloce si faceva per ogni vuoto oltre gap_g1 (8 mm): con le rincorse il tratto veloce restava di pochi
millimetri e, con rincorse oltre 4 mm, tornava indietro. Sulle foto con tanti puntini sparsi (Matita) la testa andava
avanti e indietro. Ora il salto veloce si fa solo se, tolte le due rincorse, resta lungo almeno gap_g1."""
import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PIL import Image
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication

app = QApplication([])

from freelasercut.core import gcode, photo
from freelasercut.core.document import Document, ImageShape, RectShape
from freelasercut.profile import MachineProfile

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


prof = MachineProfile()
prof.bed_x = prof.bed_y = 400.0
prof.max_rate_x = prof.max_rate_y = 30000
GAP_G1 = gcode.JobOptions().raster_gap_g1


def in_row_rapids(lines):
    """Salti veloci dentro le righe orizzontali, con il segno rispetto al verso della riga (negativo = indietro)."""
    x = y = 0.0
    d, first, out = 1, True, []
    for ln in lines:
        m = dict(re.findall(r"([XY])(-?[\d.]+)", ln))
        nx, ny = float(m.get("X", x)), float(m.get("Y", y))
        if abs(ny - y) > 1e-6:
            first = True
        elif ln.startswith("G0") and not first:
            out.append((nx - x) * d)
        if ln.startswith("G1") and abs(nx - x) > 1e-9 and abs(ny - y) < 1e-6:
            d, first = (1 if nx > x else -1), False
        x, y = nx, ny
    return out


def dots_doc(gaps_mm, overscan, dither="threshold", steady=False, w_mm=120.0):
    """Una foto bianca con righe di puntini neri separati dai vuoti dati (mm)."""
    px_mm = 10
    W, H = int(w_mm * px_mm), 40
    a = np.full((H, W), 255, np.uint8)
    x = 2.0
    while x < w_mm - 2:
        for g in gaps_mm:
            c = int(x * px_mm)
            if c + 3 >= W:
                break
            a[:, c:c + 3] = 0
            x += 0.3 + g
    doc = Document()
    doc.images["a"] = Image.fromarray(a)
    im = ImageShape("a", w_mm, H / px_mm, layer=0)
    im.apply(QTransform.fromTranslate(100, 100))
    doc.add(im)
    cs = doc.layer(0)
    cs.mode, cs.dither, cs.dpi, cs.speed, cs.power_max = "image", dither, 254, 3000, 60
    cs.overscan, cs.steady_travel = overscan, steady
    return doc


# ================================================================ 1. nessun salto veloce indietro o cortissimo
for ov in (2.5, 5.0, 8.0):
    j = gcode.generate(dots_doc((5.0, 9.0, 12.0, 15.0, 30.0), ov), prof)
    r = in_row_rapids(j.lines)
    check(f"rincorsa {ov} mm: nessun salto veloce all'indietro", all(v > 0 for v in r), [round(v, 2) for v in r if v <= 0][:5])
    check(f"rincorsa {ov} mm: ogni salto veloce lungo almeno {GAP_G1:g} mm", all(v >= GAP_G1 - 1e-3 for v in r),
          sorted(round(v, 2) for v in r)[:5])
    long_gap = 30.0 > GAP_G1 + 2 * ov
    check(f"rincorsa {ov} mm: i vuoti molto lunghi si saltano ancora veloci", (len(r) > 0) == long_gap, (len(r), long_gap))

# ================================================================ 2. vuoti fra 8 mm e 8 mm + rincorse: a laser spento lento
j = gcode.generate(dots_doc((10.0,), 2.5), prof)
check("vuoti da 10 mm con rincorsa 2,5: nessun salto veloce (prima uno da 5 mm per vuoto)", not in_row_rapids(j.lines))
j = gcode.generate(dots_doc((14.0,), 2.5), prof)
check("vuoti da 14 mm con rincorsa 2,5: salto veloce da 9 mm", in_row_rapids(j.lines)
      and all(abs(v - (14.0 - 5.0)) < 0.2 for v in in_row_rapids(j.lines)), in_row_rapids(j.lines)[:3])
j0 = gcode.generate(dots_doc((14.0,), 0.0), prof)
check("rincorsa 0: la regola di prima (vuoti oltre 8 mm veloci)", in_row_rapids(j0.lines)
      and all(abs(v - 14.0) < 0.2 for v in in_row_rapids(j0.lines)))
j1 = gcode.generate(dots_doc((6.0,), 0.0), prof)
check("rincorsa 0, vuoti da 6 mm: lenti come prima", not in_row_rapids(j1.lines))

# ================================================================ 3. «Velocità costante anche a laser spento»: come prima
js = gcode.generate(dots_doc((5.0, 12.0, 30.0), 5.0, steady=True), prof)
check("velocità costante: nessun salto veloce dentro le righe", not in_row_rapids(js.lines))

# ================================================================ 4. stessi tratti accesi: cambiano solo i vuoti
def lit(lines):
    """I tratti percorsi a laser acceso: (y, x da, x a), arrotondati al centesimo."""
    x = y = 0.0
    pw, mode, out = 0.0, "G0", []
    for ln in lines:
        if ln.startswith(("G0", "G1")):
            mode = ln[:2]
        m = dict(re.findall(r"([XYS])(-?[\d.]+)", ln))
        nx, ny = float(m.get("X", x)), float(m.get("Y", y))
        pw = float(m.get("S", pw))
        if mode == "G1" and pw > 0 and (nx, ny) != (x, y):
            out.append((round(y, 2), round(min(x, nx), 2), round(max(x, nx), 2)))
        x, y = nx, ny
    return sorted(out)


def burns(ov):
    j = gcode.generate(dots_doc((5.0, 9.0, 12.0, 30.0), ov), prof)
    return lit(j.lines), j


b0, j0 = burns(0.0)
for ov in (2.5, 5.0):
    b, j = burns(ov)
    check(f"rincorsa {ov}: gli stessi tratti accesi della rincorsa 0", len(b0) > 50 and b == b0
          and abs(j.layers[0].cut_mm - j0.layers[0].cut_mm) < 1e-6, (len(b), len(b0)))

# ================================================================ 5. riempimento: stessa regola
doc = Document()
for k in range(6):
    r = RectShape(2.0, 30.0)
    r.apply(QTransform.fromTranslate(10 + k * 11.0, 10))
    doc.add(r)
cs = doc.layer(0)
cs.mode, cs.speed, cs.power_max, cs.overscan, cs.interval = "fill", 3000, 50, 5.0, 0.2
jf = gcode.generate(doc, prof)
rf = in_row_rapids(jf.lines)
check("riempimento con rincorsa 5: nessun salto veloce indietro o sotto 8 mm", all(v >= GAP_G1 - 1e-3 for v in rf),
      sorted(round(v, 2) for v in rf)[:5])

# ================================================================ 6. la foto con l'effetto Matita
rng = np.random.default_rng(3)
H, W = 300, 240
yy, xx = np.mgrid[0:H, 0:W]
g = 170 + 40 * np.sin(xx / 20) * np.cos(yy / 27)
g = np.where(((xx - 120) / 75) ** 2 + ((yy - 140) / 100) ** 2 < 1, 150 + 30 * np.cos(xx / 13), g) + rng.normal(0, 6, g.shape)
out = photo.process(Image.fromarray(g.clip(0, 255).astype(np.uint8)), photo.PhotoSettings(effect="pencil", width_mm=40))
for ov in (2.5, 5.0):
    doc = Document()
    doc.images["a"] = out
    im = ImageShape("a", 40, 50, layer=0)
    im.apply(QTransform.fromTranslate(20, 20))
    doc.add(im)
    cs = doc.layer(0)
    cs.mode, cs.dither, cs.dpi, cs.speed, cs.power_max, cs.overscan = "image", "jarvis", 254, 3000, 60, ov
    r = in_row_rapids(gcode.generate(doc, prof).lines)
    check(f"Matita, Jarvis, rincorsa {ov}: nessun salto indietro né sotto 8 mm",
          all(v >= GAP_G1 - 1e-3 for v in r), (len(r), sorted(round(v, 2) for v in r)[:5]))

ok = sum(results)
print(f"\n{ok}/{len(results)} OK")
sys.exit(0 if ok == len(results) else 1)
