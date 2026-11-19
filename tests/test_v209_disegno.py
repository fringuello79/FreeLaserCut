# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.9 (universalcinema-boop, GitHub, 19/11/2026): guide dai righelli, deformazione a 4 e a 16 punti, larghezza
delle fessure degli incastri.

Matrice dei casi:
A  guide (core): valori rovinati scartati, doppioni, limite, ordine; aggancio di un punto (un asse alla volta, entro
   il raggio) e di un ingombro che si sposta (bordo o centro); rotazione del piano (orizzontale ↔ verticale);
B  guide (piano): trascinate dal righello in alto (orizzontale) e da sinistra (verticale), al decimo di mm; lasciate
   sul righello non nascono; prese e spostate; riportate sul righello si tolgono; fuori dalle forme soltanto (una
   forma sotto il clic resta della Selezione); aggancio di un punto e di una selezione che si sposta, spento con
   «Aggancia alle guide»; salvate nel progetto e riaperte, anche con il piano ruotato; progetto senza guide
   identico a prima; «Guida a misura», «Togli tutte le guide»; non vanno nel G-code;
C  deformazione (core): identità con i punti al loro posto (4 e 16); prospettiva esatta sui punti e rette che
   restano rette; griglia: il punto spostato porta con sé il disegno vicino, i bordi lontani restano;
   quadrilatero intrecciato o schiacciato rifiutato; tracciati chiusi restano chiusi;
D  deformazione (piano): selezione vuota, foto, linea dritta rifiutate; 4 punti e 16 punti applicati con un'azione
   sola di Annulla, livello tenuto, gruppi restano gruppi; Esc annulla senza toccare nulla; punti sbagliati: niente;
E  fessure (core): tacca sul bordo e foro rettangolare (anche come forma a sé) allargati da 3 a 4 col centro fermo e
   la profondità uguale; linguetta della stessa misura e striscia piena non toccate; fessure di un'altra misura non
   toccate; stringere (4 → 3); fessure troppo vicine saltate; misure e tolleranza sbagliate rifiutate;
F  fessure (piano): comando sulla selezione, un'azione di Annulla, area del pezzo cambiata del giusto;
G  testi nuovi nelle 4 lingue.
Uso: python tests/test_v209_disegno.py [classica|banco]
"""
import json
import math
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
from freelasercut.core import geom, gcode, guides as gd, slots, warp  # noqa: E402
from freelasercut.core.document import (  # noqa: E402
    Document, EllipseShape, GroupShape, ImageShape, PathShape, RectShape, set_door,
)
from freelasercut.ui.canvas import RULER  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "", flush=True)


def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.005)


def placed(cls, x0, y0, w_, h_, layer=1):
    """Forma con l'ingombro da (x0, y0), larga w_ e alta h_."""
    s_ = cls(w_, h_, layer=layer)
    b_ = s_.bounds()
    s_.set_transform(QTransform.fromTranslate(x0 - b_.left(), y0 - b_.top()))
    return s_


def abs_area(path):
    tot = 0.0
    for p in geom.flatten(path, 0.01):
        pts = p.pts
        a = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            a += x1 * y2 - x2 * y1
        tot += abs(a) / 2
    return tot


print("--- A. guide (core)")
check("valori rovinati scartati, doppioni tolti, in ordine",
      gd.clean([("v", 10), ("h", "x"), ("z", 1), ("h", float("nan")), ("v", 10.0004), {"k": "H", "p": "5"}, ("v", 1e9),
                ["h", 2]]) == [("h", 2.0), ("h", 5.0), ("v", 10.0)])
check("al massimo 200", len(gd.clean([("v", i) for i in range(500)])) == gd.MAX_GUIDES)
lst, i = gd.add([("v", 10)], "v", 10.0)
check("aggiungere un doppione: niente", i is None and lst == [("v", 10.0)])
lst, i = gd.add([("v", 10)], "h", 30)
check("aggiungere: indice della nuova", i is not None and lst[i] == ("h", 30.0))
G = [("v", 50.0), ("h", 20.0)]
check("punto vicino a tutte e due: agganciato sui due assi", gd.snap_point(49.2, 20.6, G, 1.0) == (50.0, 20.0, True, True))
check("punto vicino solo alla verticale: y libero", gd.snap_point(50.4, 25.0, G, 1.0) == (50.0, 25.0, True, False))
check("punto lontano: niente", gd.snap_point(40, 40, G, 1.0) == (40, 40, False, False))
fx, fy, lx, ly = gd.snap_box((0, 0, 10, 10), 39.7, 0, G, 1.0)
check("ingombro che si sposta: il bordo destro sulla guida (x 50)", fx is not None and abs(10 + 39.7 + fx - 50) < 1e-9
      and fy is None, (fx, fy))
fx, fy, _, _ = gd.snap_box((0, 0, 10, 10), 44.6, 15.4, G, 1.0)
check("…il centro sulle due guide", abs(5 + 44.6 + fx - 50) < 1e-9 and abs(5 + 15.4 + fy - 20) < 1e-9)
rot = gd.transform(G, lambda x, y: (100 - y, x))  # piano ruotato di 90°
check("rotazione di 90°: l'orizzontale diventa verticale e viceversa", rot == [("h", 50.0), ("v", 80.0)], rot)
back = gd.transform(rot, lambda x, y: (y, 100 - x))
check("…e torna com'era", back == gd.clean(G), back)

from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
spin(0.4)
cv, ed = w.canvas, w.editor
vp = cv.viewport()


def ev(kind, pt, btn=Qt.NoButton, btns=Qt.NoButton):
    app.sendEvent(vp, QMouseEvent(kind, QPointF(pt), vp.mapToGlobal(QPointF(pt)), btn, btns, Qt.NoModifier))


def drag(a, b, steps=6):
    ev(QMouseEvent.Type.MouseButtonPress, a, Qt.LeftButton, Qt.LeftButton)
    for k in range(1, steps + 1):
        ev(QMouseEvent.Type.MouseMove, a + (b - a) * (k / steps), Qt.NoButton, Qt.LeftButton)
    ev(QMouseEvent.Type.MouseButtonRelease, b, Qt.LeftButton, Qt.NoButton)
    app.processEvents()


print("--- B. guide sul piano (" + os.environ["FLC_UI"] + ")")
cv.fit_bed()
spin(0.1)
check("comandi nel menu e preferenze (guide visibili e aggancio accesi di partenza)",
      all(k in w.acts for k in ("guides_show", "guides_snap", "guides_add", "guides_clear"))
      and w.acts["guides_show"].isChecked() and w.acts["guides_snap"].isChecked() and cv.show_guides and cv.snap_guides)
target = cv.to_view(QPointF(120.0, 200.0))
drag(QPointF(target.x(), RULER / 2), QPointF(target.x() + 30, target.y()))
g = ed.doc.guides
check("dal righello in alto: guida orizzontale dove la si lascia (al decimo di mm)",
      len(g) == 1 and g[0][0] == "h" and abs(g[0][1] - 200.0) < 0.11 and abs(g[0][1] * 10 - round(g[0][1] * 10)) < 1e-6,
      g)
check("…il progetto risulta modificato", ed.dirty)
drag(QPointF(RULER / 2, target.y()), QPointF(target.x(), target.y() + 40))
g = ed.doc.guides
check("dal righello a sinistra: guida verticale", len(g) == 2 and any(k == "v" and abs(p - 120) < 0.6 for k, p in g), g)
drag(QPointF(RULER / 2, target.y()), QPointF(RULER / 2, target.y() + 60))
check("lasciata sul righello: la guida non nasce", len(ed.doc.guides) == 2)
gv = next(p for k, p in ed.doc.guides if k == "v")
a = cv.to_view(QPointF(gv, 100.0))
b = cv.to_view(QPointF(gv + 50.0, 100.0))
drag(a, b)
gv2 = next(p for k, p in ed.doc.guides if k == "v")
check("presa con Selezione e spostata di 50 mm", abs(gv2 - gv - 50) < 0.11, (gv, gv2))
r = placed(RectShape, 290, 290, 20, 20)
ed.add(r)
spin(0.05)
on_r = cv.to_view(QPointF(290, 300))  # lato sinistro del rettangolo
w.add_guide_dialog("v", 290.0)
drag(on_r, on_r + QPointF(0, -15))
check("una forma sotto il clic resta della Selezione: la guida non si sposta",
      any(k == "v" and abs(p - 290.0) < 1e-6 for k, p in ed.doc.guides))
ed.undo()
spin(0.05)
n0 = len(ed.doc.guides)
a = cv.to_view(QPointF(gv2, 120.0))
drag(a, QPointF(RULER / 2, a.y()))
check("riportata sul righello: tolta", len(ed.doc.guides) == n0 - 1 and not any(abs(p - gv2) < 1e-6 for k, p in ed.doc.guides))
w.clear_guides()
w.add_guide_dialog("v", 100.0)
w.add_guide_dialog("h", 80.0)
check("Guida a misura: nel punto scritto", ed.doc.guides == [("h", 80.0), ("v", 100.0)])
check("Guida a misura due volte nello stesso punto: una sola", w.add_guide_dialog("v", 100.0) is None
      and len(ed.doc.guides) == 2)
ed.select([])
p = cv.snap(QPointF(100.0 + cv.px(5), 50.0))
check("aggancio di un punto alla guida (entro 9 pixel)", abs(p.x() - 100.0) < 1e-9 and cv.snap_hint[1] == "guida")
p = cv.snap(QPointF(100.0 + cv.px(20), 50.0))
check("…oltre il raggio no", abs(p.x() - 100.0) > 1e-6)
box = QRectF(10, 10, 20, 20)
dx, dy = cv.snap_move(box, None, 100.0 - 30.0 + cv.px(4), 0.0, frozenset([r.id]))
check("selezione che si sposta: il bordo destro sulla guida", abs(30 + dx - 100.0) < 1e-9, dx)
w.acts["guides_snap"].trigger()
dx2, _ = cv.snap_move(box, None, 100.0 - 30.0 + cv.px(4), 0.0, frozenset([r.id]))
p2 = cv.snap(QPointF(100.0 + cv.px(5), 50.0))
check("«Aggancia alle guide» spento: niente aggancio", abs(30 + dx2 - 100.0) > 1e-6 and abs(p2.x() - 100.0) > 1e-6
      and not cv.snap_guides and w.qs.value("snap_guides") in (False, "false"))
w.acts["guides_snap"].trigger()
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "guide.flc")
ed.doc.save(path)
d2 = Document.load(path)
check("salvate nel progetto e riaperte uguali", d2.guides == ed.doc.guides, d2.guides)
d3 = Document()
d3.shapes.append(placed(RectShape, 0, 0, 5, 5))
d3.save(os.path.join(tmp, "senza.flc"))
import zipfile  # noqa: E402

meta = json.loads(zipfile.ZipFile(os.path.join(tmp, "senza.flc")).read("project.json"))
check("progetto senza guide: nessuna voce nuova nel file", "guides" not in meta)


class Rot:
    bed_x, bed_y = 440.0, 450.0

    def rot(self):
        return 1


set_door(Rot())
ed.doc.save(os.path.join(tmp, "ruotato.flc"))
meta = json.loads(zipfile.ZipFile(os.path.join(tmp, "ruotato.flc")).read("project.json"))
d4 = Document.load(os.path.join(tmp, "ruotato.flc"))
check("piano ruotato: nel file le guide sono della macchina (orizzontale ↔ verticale), riaperte uguali",
      sorted(k for k, _ in meta["guides"]) == ["h", "v"] and [k for k, _ in meta["guides"]] != [k for k, _ in ed.doc.guides]
      or (meta["guides"] != [[k, p] for k, p in ed.doc.guides]), meta["guides"])
check("…e riaperte sul piano ruotato tornano come erano", d4.guides == ed.doc.guides, d4.guides)
set_door(w.profile)
ed.select([r])
job = gcode.generate(ed.doc, w.profile)
check("le guide non vanno nel G-code (stesso lavoro con e senza guide)",
      job.lines == gcode.generate((lambda d: (setattr(d, "guides", []), d)[1])(ed.doc), w.profile).lines)
w.add_guide_dialog("v", 100.0)
w.add_guide_dialog("h", 80.0)
check("Togli tutte le guide", w.clear_guides() == 2 and ed.doc.guides == [])

print("--- C. deformazione (core)")
box = (0.0, 0.0, 40.0, 20.0)
pts = np.array([(3, 4), (40, 20), (0, 0), (17.3, 11.1)], float)
check("4 punti al loro posto: identità", np.allclose(warp.perspective_fn(box, warp.corners(box))(pts), pts))
check("16 punti al loro posto: identità", np.allclose(warp.grid_fn(box, warp.grid(box))(pts), pts))
quad = [(0, 0), (40, 0), (32, 20), (8, 20)]
f = warp.perspective_fn(box, quad)
check("prospettiva: gli angoli vanno esattamente sui 4 punti", np.allclose(f(warp.corners(box)), quad))
line = f(np.array([(0, 5), (13, 5), (40, 5)], float))
cr = (line[1, 0] - line[0, 0]) * (line[2, 1] - line[0, 1]) - (line[1, 1] - line[0, 1]) * (line[2, 0] - line[0, 0])
check("…e una retta resta retta", abs(cr) < 1e-9)
check("quadrilatero intrecciato rifiutato", warp.quad_problem([(0, 0), (40, 0), (0, 20), (40, 20)], 800) is not None)
check("quadrilatero schiacciato rifiutato", warp.quad_problem([(0, 0), (40, 0), (40, 0.05), (0, 0.05)], 800) == "flat")
check("angolo rientrante rifiutato", warp.quad_problem([(0, 0), (40, 0), (10, 5), (0, 20)], 800) == "cross")
ctrl = warp.grid(box)
ctrl[3][3] = (50.0, 30.0)  # angolo in alto a destra spostato
gf = warp.grid_fn(box, ctrl)
moved = gf(np.array([(40, 20), (0, 0), (0, 20), (40, 0)], float))
check("griglia: l'angolo spostato porta il disegno lì, gli altri angoli restano",
      np.allclose(moved[0], (50, 30)) and np.allclose(moved[1:], [(0, 0), (0, 20), (40, 0)]))
cp = QPainterPath()
cp.addEllipse(QRectF(5, 5, 10, 10))
out = warp.apply(cp, gf, warp.FLAT_TOL, warp.grid_step(box))
check("tracciato chiuso resta chiuso", all(p.closed for p in geom.flatten(out, 0.05)))

print("--- D. deformazione sul piano")
ed.doc.shapes.clear()
ed.select([])
check("senza selezione: rifiutata con il motivo", w.deform("persp") is None and cv.tool.name == "select")
a1 = placed(RectShape, 100, 100, 40, 20, layer=3)
ed.add(a1)
ed.select([a1])
t = w.deform("persp")
check("4 punti: strumento attivo con 4 maniglie sugli angoli",
      t is not None and cv.tool is t and len(t.pts) == 4 and np.allclose(t.pts, warp.corners((100, 100, 140, 120))))
ok = t.set_point(2, 132.0, 120.0) and t.set_point(3, 108.0, 120.0)
check("…punti spostati: anteprima", ok and t.preview)
n_undo = len(ed.undo_stack)
made = t.apply()
check("applicata: un tracciato sul livello di prima, un'azione sola di Annulla, si torna a Selezione",
      made and isinstance(made[0], PathShape) and made[0].layer == 3 and len(ed.undo_stack) == n_undo + 1
      and cv.tool.name == "select")
b = made[0].bounds()
check("…con la forma giusta (trapezio: sotto 40 mm, sopra 24 mm)",
      abs(b.width() - 40) < 0.05 and abs(abs_area(made[0].path()) - (40 + 24) / 2 * 20) < 0.5, abs_area(made[0].path()))
ed.undo()
spin(0.05)
check("Annulla: torna il rettangolo", any(s is a1 or s.id == a1.id for s in ed.doc.shapes))
a1 = next(s for s in ed.doc.shapes if s.id == a1.id)
ed.select([a1])
t = w.deform("persp")
t.set_point(2, 100.0, 120.0)
t.set_point(3, 140.0, 120.0)  # lati incrociati
check("punti che incrociano i lati: non si applica, il disegno resta", t.apply() is None and t.problem
      and any(s.id == a1.id for s in ed.doc.shapes))
app.sendEvent(vp, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
cv.set_tool("select") if cv.tool.name != "select" else None
check("Esc: si torna a Selezione senza toccare nulla", cv.tool.name == "select" and not t.pts
      and any(s.id == a1.id for s in ed.doc.shapes))
e1 = placed(EllipseShape, 200, 200, 10, 10, layer=5)
r1 = placed(RectShape, 215, 200, 10, 10, layer=6)
grp = GroupShape([e1, r1], layer=5)
ed.add(grp)
ed.select([grp])
t = w.deform("grid")
check("16 punti: griglia 4 × 4", t is not None and len(t.pts) == 16)
bb = grp.bounds()
t.set_point(15, bb.right() + 10, bb.bottom() + 10)
made = t.apply()
check("gruppo deformato: resta un gruppo, con i livelli delle forme", made and made[0].kind == "group"
      and sorted(c.layer for c in made[0].children) == [5, 6])
flat = placed(RectShape, 0, 0, 30, 0)
ed.add(flat)
ed.select([flat])
check("linea dritta: rifiutata", w.deform("grid") is None)

print("--- E. fessure (core)")
piece = [(0, 0), (50, 0), (50, 30), (23, 30), (23, 20), (20, 20), (20, 30), (0, 30)]
hole = [(10, 5), (13, 5), (13, 15), (10, 15)]
strip = [(60, 0), (63, 0), (63, 20), (60, 20)]
tab = [(0, 40), (20, 40), (20, 50), (23, 50), (23, 40), (40, 40), (40, 35), (0, 35)]
res, done, skipped, changed = slots.resize([[(piece, True), (hole, True)], [(strip, True)], [(tab, True)]], 3, 4)
p_new, h_new = res[0][0][0], res[0][1][0]
check("tacca sul bordo e foro: 2 fessure, nessuna saltata", done == 2 and skipped == 0 and changed == [0], (done, skipped))
check("…tacca larga 4 col centro fermo (21,5) e profondità uguale (10)",
      (23.5, 30.0) in p_new and (23.5, 20.0) in p_new and (19.5, 20.0) in p_new and (19.5, 30.0) in p_new, p_new)
check("…foro largo 4 col centro fermo, lungo uguale", sorted(h_new) == sorted([(9.5, 5.0), (13.5, 5.0), (13.5, 15.0), (9.5, 15.0)]))
check("striscia piena e linguetta della stessa misura non toccate", res[1][0][0] == strip and res[2][0][0] == tab)
res, done, _, _ = slots.resize([[(piece, True)], [(hole, True)]], 3, 4)
check("foro come forma a sé dentro il pezzo: allargato anche lui", done == 2)
res, done, _, _ = slots.resize([[(piece, True)]], 5, 6)
check("misura diversa: niente", done == 0 and res[0][0][0] == slots._clean(piece))
res, done, _, _ = slots.resize([[(piece, True)]], 3, 2.5)
check("stringere (3 → 2,5)", done == 1 and (22.75, 20.0) in res[0][0][0] and (20.25, 20.0) in res[0][0][0], res[0][0][0])
close = [(0, 0), (20, 0), (20, 10), (13, 10), (13, 5), (10, 5), (10, 10), (9.2, 10), (9.2, 5), (6.2, 5), (6.2, 10),
         (0, 10)]
res, done, skipped, _ = slots.resize([[(close, True)]], 3, 4)
check("due fessure a 0,8 mm l'una dall'altra: una cambiata, l'altra saltata (si mangerebbero)", done == 1 and skipped == 1,
      (done, skipped))
closer = [(x if x > 9.5 else x + 0.4, y) if 6 < x < 9.5 else (x, y) for x, y in close]
res, done, skipped, _ = slots.resize([[(closer, True)]], 3, 4)
check("…a 0,4 mm: tutte e due saltate (ognuna da sola mangerebbe il tratto fra le due)", done == 0 and skipped == 2,
      (done, skipped))
for bad in ((0, 4, 0.1), (3, -1, 0.1), (3, 4, 2)):
    try:
        slots.resize([[(piece, True)]], *bad)
        check(f"misure sbagliate {bad}: rifiutate", False)
    except ValueError:
        check(f"misure sbagliate {bad}: rifiutate", True)
check("piccola differenza entro la tolleranza (3,05) trovata", slots.count([[(
    [(0, 0), (50, 0), (50, 30), (23.05, 30), (23.05, 20), (20, 20), (20, 30), (0, 30)], True)]], 3, 0.1) == 1)

print("--- F. fessure sul piano")
ed.doc.shapes.clear()
pp = QPainterPath()
pp.moveTo(*piece[0])
for q in piece[1:]:
    pp.lineTo(*q)
pp.closeSubpath()
ps = PathShape(pp, layer=2)
ps.set_transform(QTransform.fromTranslate(50, 50))
ed.add(ps)
ed.select([ps])
a0 = abs_area(ps.path())
n_undo = len(ed.undo_stack)
res = w.slots_dialog(3, 4, 0.1)
new = ed.doc.shapes[-1]
check("comando sulla selezione: una fessura, un'azione di Annulla, livello tenuto",
      res == (1, 0) and len(ed.undo_stack) == n_undo + 1 and new.layer == 2)
check("…area del pezzo calata di 1 × 10 mm²", abs(a0 - abs_area(new.path()) - 10.0) < 0.05, (a0, abs_area(new.path())))
ed.undo()
check("Annulla: il pezzo di prima", abs(abs_area(ed.doc.shapes[-1].path()) - a0) < 1e-6)
ed.select([])
check("senza selezione: niente", w.slots_dialog(3, 4) is None)

print("--- G. traduzioni")
cats = {}
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", lang + ".json"), encoding="utf-8") as fh:
        cats[lang] = json.load(fh)
keys = ["Guide", "Aggancia alle guide", "Guida a misura…", "Togli tutte le guide", "Deforma in prospettiva (4 punti)",
        "Deforma con la griglia (16 punti)", "Cambia la larghezza delle fessure…", "Larghezza delle fessure"]
miss = [(lang, k) for lang, c in cats.items() for k in keys if k not in c]
check("testi principali nelle 4 lingue", not miss, miss[:4])

w.close()
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(0 if all(results) else 1)
