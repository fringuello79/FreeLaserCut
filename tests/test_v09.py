# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.9: QR e codici a barre, testo su tracciato, rotativo, nesting su più pannelli e linee comuni,
preparazione della firma (NSIS, workflow, MSIX)."""
import sys, os, time, math, re, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cv2
import numpy as np
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from PySide6.QtGui import QTransform, QPainterPath
from PySide6.QtCore import QPointF
from freelasercut.ui import style
from freelasercut.theme import QSS
app = QApplication([]); app.setStyle("Fusion"); style.load_fonts()
app.setStyleSheet(QSS + style.QSS_EXTRA)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.core import codes, geom, gcode, nesting, text as textmod
from freelasercut.core.document import CodeShape, Document, PathShape, RectShape, TextPathShape, TextShape

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.005)

def raster(path, scale, pad=40, ss=8):
    polys = geom.flatten(path, 0.005)
    xs = [x for p in polys for x, _ in p.pts]; ys = [y for p in polys for _, y in p.pts]
    x0, y1 = min(xs), max(ys)
    W = int((max(xs) - x0) * scale * ss) + 2 * pad * ss; H = int((y1 - min(ys)) * scale * ss) + 2 * pad * ss
    mask = np.zeros((H, W), np.uint8)
    for p in polys:
        if not p.closed:
            continue
        c = np.round(np.array([[(x - x0) * scale * ss + pad * ss, (y1 - y) * scale * ss + pad * ss] for x, y in p.pts]) * 16).astype(np.int32)
        tmp = np.zeros((H, W), np.uint8); cv2.fillPoly(tmp, [c], 1, shift=4); mask ^= tmp
    img = np.where(mask > 0, 0, 255).astype(np.uint8)
    return cv2.resize(img, (W // ss, H // ss), interpolation=cv2.INTER_AREA)

# ------------------------------------------------------------------ codici
qr = cv2.QRCodeDetector()
url = "https://fringuello79.github.io/FreeLaserCut/"
val = qr.detectAndDecode(raster(codes.code_path("qr", url, 30, ecc="M", quiet=4), 8))[0]
check("QR: il disegno si rilegge", val == url, val)
val = qr.detectAndDecode(255 - raster(codes.code_path("qr", "FLC-0042", 20, quiet=4, invert=True), 8))[0]
check("QR in negativo (materiali che schiariscono): si rilegge", val == "FLC-0042", val)
bd = cv2.barcode.BarcodeDetector()
for kind, data, expect in (("ean13", "800123456789", "8001234567897"), ("upca", "03600029145", "036000291452"),
                           ("ean8", "9638507", "96385074")):
    mods, _ = codes.bars(kind, data)
    img = cv2.cvtColor(raster(codes.code_path(kind, data, len(mods) * 0.5, 30, quiet=10, text=True), 4), cv2.COLOR_GRAY2BGR)
    out = bd.detectAndDecodeWithType(img)
    check(f"{codes.KINDS[kind][0]}: si rilegge con la cifra di controllo", out[1] and out[1][0] == expect, str(out[1]))
for kind, data in (("code128", "FLC-0042"), ("code39", "FLC 42")):
    mods, _ = codes.bars(kind, data)
    p = codes.code_path(kind, data, len(mods) * 1.0, 20, quiet=0, text=False)
    img = raster(p, 4, pad=0)
    row = img[img.shape[0] // 2]
    got = "".join("1" if row[int(i * 4 + 2)] < 128 else "0" for i in range(len(mods)))
    check(f"{codes.KINDS[kind][0]}: le barre incise sono esattamente quelle del codice", got == mods)
try:
    codes.code_path("ean13", "12ab", 40); bad = False
except codes.CodeError:
    bad = True
check("dati non validi: errore chiaro, nessun crash", bad)
c = CodeShape("qr", "FLC-{n:4}", 20, layer=2)
check("codice con numero progressivo", c.variable and c.shown_data() == "FLC-0001", c.shown_data())
d = Document(); d.add(c); fn = os.path.join(tempfile.mkdtemp(), "c.flcut"); d.save(fn)
d2 = Document.load(fn)
check("il codice si salva e si riapre come codice modificabile", isinstance(d2.shapes[0], CodeShape) and d2.shapes[0].data == "FLC-{n:4}")

# ------------------------------------------------------------------ testo su tracciato
curve = QPainterPath(); curve.moveTo(0, 0); curve.cubicTo(40, 50, 80, -50, 120, 0)
straight = textmod.text_path("CURVA", "Arial", 8)
bent = textmod.follow_path(straight, curve, 0.5, "center", 0.0)
cpts = [pt for p in geom.flatten(curve, 0.05) for pt in p.pts]
far = max(min(math.dist(q, c) for c in cpts) for p in geom.flatten(bent, 0.05) for q in p.pts)
check("testo su tracciato: le lettere restano a ridosso della curva", far < 8 * 1.2, f"distanza massima {far:.1f} mm")
b = bent.boundingRect()
check("…e lo seguono per la lunghezza giusta (centrato)", 20 < b.center().x() < 100, f"centro x {b.center().x():.1f}")
off = textmod.follow_path(straight, curve, 0.5, "center", 5.0).boundingRect()
check("distanza dalla curva: il testo si allontana", abs(off.center().y() - b.center().y()) > 2)

# ------------------------------------------------------------------ rotativo
check("rotativo a rulli: scala Y = mm per giro / (π × diametro rullo)",
      abs(gcode.rotary_scale({"kind": "roller", "mm_per_rev": 80, "roller_d": 25}) - 80 / (math.pi * 25)) < 1e-9)
check("rotativo a mandrino: conta il diametro dell'oggetto",
      abs(gcode.rotary_scale({"kind": "chuck", "mm_per_rev": 360, "object_d": 70}) - 360 / (math.pi * 70)) < 1e-9)
doc = Document()
r = RectShape(20, 40, layer=1); r.apply(QTransform.fromTranslate(100, 100)); doc.add(r)
from freelasercut.profile import MachineProfile
prof = MachineProfile()
opt = gcode.JobOptions(start_from="current", current_pos=(100.0, 100.0), anchor=0)
flat = gcode.generate(doc, prof, opt)
from dataclasses import replace
rot = gcode.generate(doc, prof, replace(opt, rotary={"kind": "roller", "mm_per_rev": 50, "roller_d": 25}))
def ys(lines):
    return [float(m.group(1)) for l in lines for m in [re.search(r"Y(-?[\d.]+)", l)] if m]
k = 50 / (math.pi * 25)
sf, sr = max(ys(flat.lines)) - min(ys(flat.lines)), max(ys(rot.lines)) - min(ys(rot.lines))
check("G-code col rotativo: l'asse Y è scalato del fattore giusto", abs(sr / sf - k) < 0.01, f"{sr / sf:.4f} vs {k:.4f}")
def feeds(lines):
    return [float(m.group(1)) for l in lines if l.startswith(("G1", "X", "Y")) for m in [re.search(r"F([\d.]+)", l)] if m]
check("…e la velocità si corregge sui tratti in Y", any(abs(f - 1500 * k) < 2 for f in feeds(rot.lines)), str(sorted(set(feeds(rot.lines)))[:4]))

# ------------------------------------------------------------------ nesting: più pannelli e linee comuni
parts = [RectShape(60, 40, layer=2) for _ in range(10)]
for i, s in enumerate(parts):
    s.apply(QTransform.fromTranslate(300 + i * 4, 300 + i * 9))
area = [geom.Poly([(0, 0), (150, 0), (150, 100), (0, 100)], True)]
res, shifts = nesting.nest_sheets(parts, area, spacing=2, margin=1)
check("più pannelli: i pezzi che non entrano vanno sul pannello successivo",
      len(res) == 3 and sum(len(r.placements) for r in res) == 10 and shifts[1] > 150, f"{len(res)} pannelli")
sq = [[geom.Poly([(x, y), (x + 40, y), (x + 40, y + 30), (x, y + 30)], True)] for x, y in ((1.2, 0.7), (42.5, 1.4), (0.9, 32.2), (43.1, 31.6))]
moves = nesting.compact(sq, [geom.Poly([(0, 0), (200, 0), (200, 200), (0, 200)], True)])
placed = [[geom.Poly([(x + mx, y + my) for x, y in p.pts], True) for p in g] for g, (mx, my) in zip(sq, moves)]
merged, saved = nesting.merge_common_lines([p for g in placed for p in g])
total = sum(merged_p.length() for merged_p in merged)
check("pezzi accostati: i lati vicini diventano coincidenti e si tagliano una volta", abs(total - 420) < 0.5 and abs(saved - 140) < 0.5,
      f"{total:.1f} mm di taglio, {saved:.1f} risparmiati")

from freelasercut.ui.main_window import MainWindow
w = MainWindow(); w.resize(1440, 900); w.show(); spin(0.5)
for k_ in ("nest_multi", "nest_common", "rotary_on"):
    w.qs.setValue(k_, False)
ed = w.editor
r0 = RectShape(40, 25, layer=2); r0.apply(QTransform.fromTranslate(10, 10)); ed.add([r0]); ed.select([r0])
ed.grid_array(4, 3, 0, 0, spacing="gap"); spin()
ed.select(list(ed.doc.shapes))
saved = w.common_lines_cmd(); spin()
L = sum(p.length() for s in ed.doc.shapes for p in geom.flatten(s.path(), 0.01))
check("serie a griglia attaccata + «Unisci le linee comuni»: 1560 → 1015 mm", abs(L - 1015) < 0.5 and abs(saved - 545) < 0.5, f"{L:.0f} mm")
w.acts["undo"].trigger(); spin()
check("…e Ctrl+Z riporta i 12 rettangoli", len(ed.doc.shapes) == 12)
check("comandi nei menu: codice, testo su tracciato, rotativo, linee comuni",
      all(k in w.acts for k in ("code", "text_path", "rotary", "common_lines")))
# codice dal programma
from freelasercut.ui import dialogs_code
dialogs_code.CodeDialog.exec = lambda self: (self.data.setText("FLC-{n:3}"), QDialog.Accepted)[1]
cs = w.code_dialog(); spin()
check("Codice QR dal menu: inserito su un livello in riempimento", isinstance(cs, CodeShape) and ed.doc.layer(cs.layer).mode == "fill",
      ed.doc.layer(cs.layer).mode if cs else "")
ed.select([cs]); ed.grid_array(3, 1, 4, 4); spin()
check("serie di codici numerati", [s.shown_data() for s in ed.doc.shapes if isinstance(s, CodeShape)] == ["FLC-001", "FLC-002", "FLC-003"])
# testo su tracciato dal programma
g = PathShape(curve, layer=1); g.apply(QTransform.fromTranslate(50, 250))
t = TextShape("Ciao curva", "Arial", 6, layer=1); t.apply(QTransform.fromTranslate(60, 200))
ed.add([g, t]); ed.select([t, g]); spin()
from freelasercut.ui import dialogs_textpath
dialogs_textpath.TextPathDialog.exec = lambda self: (self.offset.setValue(1.5), self.accept(), QDialog.Accepted)[2]
tp = w.text_path_dialog(); spin()
check("Testo su tracciato dal menu: il testo diventa curvo e resta testo", isinstance(tp, TextPathShape) and tp.text == "Ciao curva"
      and abs(tp.offset - 1.5) < 1e-9 and tp in ed.doc.shapes)
# rotativo dal programma
w.qs.setValue("rotary_on", True); w.qs.setValue("rotary_kind", "roller"); w.qs.setValue("rotary_mm_rev", 50.0); w.qs.setValue("rotary_roller_d", 25.0)
w.update_rotary_state(); spin()
check("rotativo attivo: avviso nella barra di stato", w.sb_rotary.isVisible() and w.acts["rotary"].isChecked())
check("…e le opzioni del lavoro lo includono", w.job_options().rotary is not None)
w.qs.setValue("rotary_on", False); w.update_rotary_state(); spin()
check("rotativo spento: nessun effetto sul lavoro", w.job_options().rotary is None and not w.sb_rotary.isVisible())

# ------------------------------------------------------------------ firma e Store
nsi = open(os.path.join(ROOT, "build", "installer.nsi"), encoding="utf-8").read()
check("installatore: firma facoltativa di installatore e disinstallatore", "!finalize" in nsi and "!uninstfinalize" in nsi)
wf = open(os.path.join(ROOT, ".github", "workflows", "installatore.yml"), encoding="utf-8").read()
check("workflow GitHub per costruire l'installatore dal codice pubblico", "prepara_installer.py" in wf and "makensis" in wf)
import xml.dom.minidom
man = xml.dom.minidom.parse(os.path.join(ROOT, "build", "msix", "AppxManifest.xml"))
check("pacchetto MSIX per il Microsoft Store: manifesto valido", man.getElementsByTagName("Application")[0].getAttribute("Executable") == "python\\pythonw.exe")

w.close(); spin(0.2)
print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
