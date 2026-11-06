# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.8: Ottimizza lo spazio (nesting) e modelli di laser pronti."""
import sys, os, time, math, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pyclipper
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QPointF, QSettings
from freelasercut.ui import style
from freelasercut.theme import QSS
app = QApplication([]); app.setStyle("Fusion"); style.load_fonts()
app.setStyleSheet(QSS + style.QSS_EXTRA)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
from freelasercut.core import nesting, geom
from freelasercut.core.document import RectShape, EllipseShape, TextShape
from freelasercut import machines

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.005)

def rect(x, y, w, h): return [geom.Poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)]
def circle(cx, cy, r, n=48): return [geom.Poly([(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)], True)]
def moved(polys, tf): return [[(q.x(), q.y()) for q in (tf.map(QPointF(x, y)) for x, y in p.pts)] for p in polys]
S = 1000
def too_close(a, b, gap):
    po = pyclipper.PyclipperOffset()
    for P in a: po.AddPath([(int(x * S), int(y * S)) for x, y in P], pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    A = po.Execute((gap - 0.05) * S)
    pc = pyclipper.Pyclipper(); pc.AddPaths(A, pyclipper.PT_SUBJECT, True)
    for P in b: pc.AddPath([(int(x * S), int(y * S)) for x, y in P], pyclipper.PT_CLIP, True)
    return bool(pc.Execute(pyclipper.CT_INTERSECTION))

# ------------------------------------------------------------------ motore
parts = [nesting.make_part(i, rect(300 + 7 * i, 50 * i, 50, 30)) for i in range(16)]
t0 = time.time()
r = nesting.nest(parts, rect(0, 0, 200, 200), spacing=2.0, margin=1.0, rotations="90")
dt = time.time() - t0
check("16 rettangoli 50×30 in un pannello 200×200: tutti sistemati", len(r.placements) == 16 and not r.unplaced, f"{dt:.2f} s")
pl = {k: moved(parts[k].polys, tf) for k, tf in r.placements.items()}
bad = sum(too_close(pl[a], pl[b], 2.0) for a in pl for b in pl if a < b)
check("nessun pezzo a meno di 2 mm da un altro", bad == 0, f"{bad} coppie")
xs = [x for P in pl.values() for Q in P for x, _ in Q]; ys = [y for P in pl.values() for Q in P for _, y in Q]
check("tutti dentro il pannello, a 1 mm dal bordo", min(xs) >= 0.99 and min(ys) >= 0.99 and max(xs) <= 199.01 and max(ys) <= 199.01,
      f"{min(xs):.2f}…{max(xs):.2f} × {min(ys):.2f}…{max(ys):.2f}")
check("resa del materiale calcolata", 0.5 < r.efficiency <= 1.0, f"{r.efficiency * 100:.0f}% su {r.used_w:.0f}×{r.used_h:.0f} mm")
check("pezzi compattati verso l'origine", r.used_w * r.used_h < 200 * 200 * 0.95)

big = [nesting.make_part(i, rect(0, 0, 90, 90)) for i in range(6)]
r = nesting.nest(big, rect(0, 0, 200, 200), spacing=2.0, margin=0.0)
check("pezzi in più del materiale: segnalati e lasciati fuori", len(r.placements) == 4 and len(r.unplaced) == 2,
      f"{len(r.placements)} messi, {len(r.unplaced)} fuori")

sheet = circle(100, 100, 100, 96)
small = [nesting.make_part(i, circle(0, 0, 15)) for i in range(12)]
r = nesting.nest(small, sheet, spacing=1.0, margin=1.0)
inside = all(math.hypot(x - 100, y - 100) <= 100.01 for k, tf in r.placements.items() for P in moved(small[k].polys, tf) for x, y in P)
check("materiale rotondo (avanzo irregolare): i pezzi restano dentro", len(r.placements) >= 10 and inside, f"{len(r.placements)} messi")

obst = rect(0, 0, 120, 200)
parts = [nesting.make_part(i, rect(0, 0, 30, 30)) for i in range(4)]
r = nesting.nest(parts, rect(0, 0, 200, 200), obstacles=obst, spacing=2.0, margin=0.0)
xs = [x for k, tf in r.placements.items() for P in moved(parts[k].polys, tf) for x, _ in P]
check("le forme ferme sul piano vengono evitate", len(r.placements) == 4 and min(xs) >= 121.9, f"x minima {min(xs):.1f}")

parts = [nesting.make_part(i, rect(10 * i, 0, 60, 20)) for i in range(3)]
r = nesting.nest(parts, rect(0, 0, 300, 300), rotations="none")
check("rotazioni «nessuna»: l'orientamento non cambia", all(abs(tf.m12()) < 1e-9 and abs(tf.m11() - 1) < 1e-9 for tf in r.placements.values()))

L = [geom.Poly([(0, 0), (80, 0), (80, 20), (20, 20), (20, 80), (0, 80)], True)]
r1 = nesting.nest([nesting.make_part(i, L) for i in range(6)], rect(0, 0, 400, 400), rotations="none")
r2 = nesting.nest([nesting.make_part(i, L) for i in range(6)], rect(0, 0, 400, 400), rotations="90")
check("con le rotazioni le sagome a L si incastrano meglio", r2.used_w * r2.used_h < r1.used_w * r1.used_h,
      f"{r1.used_w * r1.used_h / 100:.0f} → {r2.used_w * r2.used_h / 100:.0f} cm²")

ring = EllipseShape(100, 100); ring.apply(__import__("PySide6.QtGui", fromlist=["QTransform"]).QTransform.fromTranslate(200, 200))
txt = RectShape(40, 10); txt.apply(__import__("PySide6.QtGui", fromlist=["QTransform"]).QTransform.fromTranslate(230, 245))
other = RectShape(30, 30); other.apply(__import__("PySide6.QtGui", fromlist=["QTransform"]).QTransform.fromTranslate(400, 400))
groups = nesting.clusters([(s, nesting.shape_polys(s)) for s in (ring, txt, other)])
check("un'incisione dentro il suo contorno resta unita al contorno", sorted(len(g) for g in groups) == [1, 2])
d0 = txt.bounds().center() - ring.bounds().center()
res = nesting.nest_shapes([ring, txt, other], rect(0, 0, 450, 440))
nesting.apply(res)
d1 = txt.bounds().center() - ring.bounds().center()
other2 = RectShape(30, 30); other2.apply(__import__("PySide6.QtGui", fromlist=["QTransform"]).QTransform.fromTranslate(410, 410))
check("copie sovrapposte (duplicati) restano pezzi separati", len(nesting.clusters([(s, nesting.shape_polys(s)) for s in (other, other2)])) == 2)
check("…e dopo il nesting è ancora nello stesso punto del contorno", abs(math.hypot(d1.x(), d1.y()) - math.hypot(d0.x(), d0.y())) < 0.01)

# ------------------------------------------------------------------ modelli di laser
names = machines.catalog_names()
check("catalogo dei laser più diffusi", len(names) >= 18 and any("Ortur" in n for n in names) and any("xTool" in n for n in names)
      and any("Sculpfun" in n for n in names) and any("Atomstack" in n for n in names) and any("Creality" in n for n in names),
      f"{len(names)} modelli")
p = machines.preset_profile("xTool D1 Pro")
check("profilo pronto: area di lavoro del modello", (p.bed_x, p.bed_y) == (430, 390) and p.name == "xTool D1 Pro")
check("profilo generico per qualsiasi GRBL", machines.preset_profile(machines.GENERIC).bed_x == 400)
ident = machines.identify(["Grbl 1.1h ['$' for help]", "[MSG:ORTUR LASER MASTER 3]"], [], {130: 400, 131: 400, 30: 1000, 32: 1})
check("Ortur riconosciuto dal banner e dall'area: modello del catalogo", ident.model == "Ortur Laser Master 3 (10W)", ident.model)
bp = machines.base_profile(ident)
check("…e il profilo parte dai suoi valori di targa", bp.optical_power == "10 W" and bp.bed_x == 400)

# ------------------------------------------------------------------ nel programma
os.environ["FLC_UI"] = "classica"
from freelasercut.ui.dialogs_machine import use_preset
from freelasercut.settings_store import app_settings

qs = app_settings()
old_prof = qs.value("profile_path", "")
pp = use_preset(qs, "Sculpfun S30 / S30 Pro / S30 Pro Max")
check("scegliere un modello crea il profilo e lo rende attivo", pp is not None and os.path.exists(qs.value("profile_path"))
      and pp.bed_x == 410)
from freelasercut.ui.main_window import MainWindow
w = MainWindow(); w.resize(1440, 900); w.show(); spin(0.5)
check("all'avvio si usa il modello scelto", w.profile.name.startswith("Sculpfun") and (w.canvas.bed_x, w.canvas.bed_y) == (410, 400))
check("comando nel menu Disponi con Alt+N", "nest" in w.acts and w.acts["nest"].shortcut().toString() == "Alt+N"
      and any(a is w.acts["nest"] for m in w.menuBar().actions() if m.menu() for a in m.menu().actions()))
ed = w.editor
shapes = []
for i in range(10):
    s = RectShape(60, 40); s.apply(__import__("PySide6.QtGui", fromlist=["QTransform"]).QTransform.fromTranslate(15 * i, 10 * i)); shapes.append(s)
ed.add(shapes, select=False); spin()
before = [s.bounds() for s in shapes]
from freelasercut.ui.dialogs_nest import NestDialog
for k_ in ("nest_multi", "nest_common"):  # preferenze lasciate da altre prove
    w.qs.setValue(k_, False)
dlg = NestDialog(w)
check("senza selezione: tutti i pezzi del progetto", len(dlg.parts) == 10)
res = dlg.run(); spin(0.1)
after = [s.bounds() for s in shapes]
ov = sum(after[a].adjusted(-0.9, -0.9, 0.9, 0.9).intersects(after[b]) for a in range(10) for b in range(a + 1, 10))
check("Disponi: 10 pezzi sistemati senza sovrapposizioni", len(res.placements) == 10 and ov == 0, dlg.result.text()[:80])
check("il risultato dice resa e materiale usato", "%" in dlg.result.text() and "mm" in dlg.result.text())
ids = [s.id for s in shapes]
w.acts["undo"].trigger(); spin(0.1)
shapes = [ed.doc.find(i) for i in ids]
check("Ctrl+Z riporta tutto com'era", all(s is not None and abs(s.bounds().x() - b.x()) < 1e-6 and abs(s.bounds().y() - b.y()) < 1e-6
                                          for s, b in zip(shapes, before)))
sheet = RectShape(150, 100); sheet.layer = 30
sheet.apply(__import__("PySide6.QtGui", fromlist=["QTransform"]).QTransform.fromTranslate(250, 250))
ed.add([sheet], select=False); spin()
ed.select(shapes[:4] + [sheet]); spin()
dlg = NestDialog(w)
check("contorno sul livello T1 selezionato = il materiale", dlg.area.currentData() == "sheet" and len(dlg.parts) == 4)
res = dlg.run(); spin(0.1)
sb = sheet.bounds()
check("i pezzi vanno dentro il materiale disegnato", len(res.placements) == 4 and all(sb.contains(s.bounds()) for s in shapes[:4]))
check("il contorno del materiale non si sposta", abs(sheet.bounds().x() - 250) < 1e-6)
dlg.close()
qs.remove("profile_path")
from freelasercut.ui.banco import ChoiceDialog
cd = ChoiceDialog()
check("prima installazione: la scelta iniziale chiede anche il modello di laser", cd.machine is not None and cd.machine.count() >= 19)
cd.machine.setCurrentText("Two Trees TS2"); cd.accept()
check("…e lo salva come profilo attivo", "Two_Trees_TS2" in qs.value("profile_path", ""))
qs.setValue("profile_path", old_prof)
w.close(); spin(0.2)

print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
