# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.2: raggio degli angoli nella barra in alto (accanto a L e A) e raggio anche per poligoni e stelle.

Matrice dei casi nel documento «aggiornamento-0.18.2» (filone «raggio nella barra»):
1 rettangolo dalla barra = dal pannello, oltre il massimo → massimo, mm veri dopo il ridimensionamento;
2 quattro angoli dalla barra; 3 più forme insieme, un passo, Annulla/Ripeti; 4 poligono e stella: 0 = come prima,
archi di cerchio di raggio r tangenti ai lati, limite senza sovrapposizioni, ridimensionamento non uniforme;
5 salva/riapri; 6 campo spento senza forme col raggio; 7 barra e pannello allineati; 8 aiuto, Banco.
"""
import math
import os
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
from PySide6.QtGui import QPainterPath, QTransform
from PySide6.QtWidgets import QApplication

app = QApplication([])
from freelasercut.core import nodes
from freelasercut.core.document import (Document, EllipseShape, GroupShape, PolygonShape, RectShape, TextShape,
                                        shape_from_dict)
from freelasercut.ui import help_texts
from freelasercut.ui.main_window import MainWindow

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def mk(shape, x, y):
    b = shape.bounds()
    shape.apply(QTransform.fromTranslate(x - b.left(), y - b.top()))
    return shape


def same_path(a, b, tol=1e-9):
    ea = [(a.elementAt(i).x, a.elementAt(i).y) for i in range(a.elementCount())]
    eb = [(b.elementAt(i).x, b.elementAt(i).y) for i in range(b.elementCount())]
    return len(ea) == len(eb) and all(math.dist(p, q) <= tol for p, q in zip(ea, eb))


def circ(a, m, b):
    """Raggio del cerchio per tre punti."""
    ax, ay = a
    bx, by = m
    cx, cy = b
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return math.inf
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return math.dist((ux, uy), a)


def arcs(shape):
    """[(raggio del cerchio per inizio, metà e fine, inizio, fine)] per ogni arco del tracciato sul piano."""
    out = []
    for sp in nodes.from_path(shape.path()):
        for i, j in sp.segments():
            if sp.is_curve(i, j):
                bz = sp.bezier(i, j)
                out.append((circ(bz[0], nodes.bez_point(*bz, 0.5), bz[3]), bz[0], bz[3]))
    return out


def dist_line(p, a, b):
    return abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])) / math.dist(a, b)


w = MainWindow()
ed, bar = w.editor, w.numeric


def fresh(*shapes):
    ed.doc.shapes.clear()
    ed.selection = []
    ed.add(list(shapes))
    return list(shapes)


# ---------------------------------------------------------------- 4. geometria di poligoni e stelle
hexa0 = PolygonShape(40, 40, 6)
ref0 = QPainterPath(hexa0.path())
hexa0.radius = 0.0
check("poligono con raggio 0: forma identica a prima", same_path(hexa0.path(), ref0))
hexa = PolygonShape(40, 40, 6)
hexa.radius = 4.0
hexa.invalidate()
ac = arcs(hexa)
corners = hexa._points()
check("esagono con raggio 4: sei archi di cerchio di raggio 4 mm", len(ac) == 6 and all(abs(r - 4) < 4e-3 for r, _a, _b
                                                                                           in ac), [round(r, 4) for r, _a, _b in ac])
sides = [(corners[k], corners[(k + 1) % 6]) for k in range(6)]
tang = all(min(dist_line(a, *s) for s in sides) < 1e-9 and min(dist_line(b, *s) for s in sides) < 1e-9 for _r, a, b in ac)
check("…tangenti ai lati (inizio e fine di ogni arco sui lati del poligono)", tang)
check("massimo dell'esagono = metà lato × tan(60°)", abs(hexa.max_radius() - 10 * math.tan(math.radians(60))) < 1e-9,
      hexa.max_radius())
star = PolygonShape(60, 60, 5, 0.5)
star.radius = 1.5
star.invalidate()
check("stella: archi anche nei vertici rientranti (10 archi di raggio 1,5)", len(arcs(star)) == 10
      and all(abs(r - 1.5) < 2e-3 for r, _a, _b in arcs(star)))
big = PolygonShape(40, 40, 6)
big.radius = 500.0
big.invalidate()
from freelasercut.core import trim  # noqa: E402

doc_ = Document()
doc_.shapes.append(big)
check("raggio enorme: limitato vertice per vertice, il contorno non si incrocia mai", trim.Trimmer(doc_, big).cuts == [[]]
      and big.path().boundingRect().width() <= 40 + 1e-9)
sq = PolygonShape(20, 20, 6)
sq.apply(QTransform.fromScale(3, 1))
sq.radius = 2.0
sq.invalidate()
check("esagono ridimensionato 3:1: archi sempre di cerchio da 2 mm sul piano", all(abs(r - 2) < 3e-3 for r, _a, _b in
                                                                                   arcs(sq)), [round(r, 4) for r, _a, _b in arcs(sq)])

# ---------------------------------------------------------------- 5. salva e riapri
d = star.to_dict()
s2 = shape_from_dict(d)
check("salva/riapri: raggio del poligono conservato", isinstance(s2, PolygonShape) and s2.radius == 1.5
      and same_path(s2.path(), star.path()))
d0 = PolygonShape(30, 30, 6).to_dict()
check("senza raggio il file del poligono resta come prima (niente «radius»)", "radius" not in d0["p"]
      and shape_from_dict(d0).radius == 0)

# ---------------------------------------------------------------- 1. rettangolo dalla barra
R, = fresh(mk(RectShape(60, 40), 0, 0))
ed.select([R])
bar.refresh()
check("barra: campo R acceso con un rettangolo, pulsante dei 4 angoli anche", bar.frad.isEnabled()
      and bar.btn_corners.isEnabled())
n0 = len(ed.undo_stack)
bar.frad.setValue(6, emit=True)
R = ed.doc.shapes[0]
Rp = mk(RectShape(60, 40), 0, 0)
Rp.radius = 6
check("R = 6 dalla barra: forma identica a quella del pannello, un passo", R.radius == 6 and R.radii is None
      and same_path(R.path(), Rp.path()) and len(ed.undo_stack) == n0 + 1)
bar.frad.setValue(99, emit=True)
check("oltre il massimo diventa il massimo (metà del lato corto, 20 mm)", ed.doc.shapes[0].radius == 20
      and abs(bar.frad.value() - 20) < 1e-9)
ed.undo()
R = ed.doc.shapes[0]
R.apply(QTransform.fromScale(2, 1))
ed.select([R])
bar.frad.setValue(30, emit=True)
check("rettangolo allargato dopo il disegno: massimo in mm veri (ora 20, il lato corto è 40)",
      ed.doc.shapes[0].radius == 20)

# ---------------------------------------------------------------- 2. quattro angoli dalla barra
R, = fresh(mk(RectShape(60, 40), 0, 0))
ed.select([R])
bar.open_corners()
pop = bar.corners
pop.each.setChecked(True)
R = ed.doc.shapes[0]
check("«Ogni angolo a parte» dalla barra: quattro raggi uguali al raggio di prima", R.radii == [0.0] * 4)
pop.spins[0].setValue(10)
R = ed.doc.shapes[0]
check("↖ = 10: solo quell'angolo arrotondato", R.corner_radii() == [10.0, 0.0, 0.0, 0.0])
pop.spins[2].setValue(55)
R = ed.doc.shapes[0]
check("↘ oltre il massimo: limitato a 20", R.corner_radii() == [10.0, 0.0, 20.0, 0.0], R.corner_radii())
bar.refresh()
check("campo R mostra il più grande e lo dice nel suggerimento", abs(bar.frad.value() - 20) < 1e-9
      and "diversi" in bar.frad.toolTip())
pop.each.setChecked(False)
R = ed.doc.shapes[0]
check("tornare a un raggio solo: il più grande per tutti", R.radii is None and R.radius == 20)
pop.hide()

# ---------------------------------------------------------------- 3. più forme insieme
R, P, S = fresh(mk(RectShape(60, 40), 0, 0), mk(PolygonShape(40, 40, 6), 80, 0), mk(PolygonShape(60, 60, 5, 0.5), 140, 0))
ed.select([R, P, S])
bar.refresh()
check("rettangolo + poligoni: R acceso, 4 angoli spento (non sono tutti rettangoli)", bar.frad.isEnabled()
      and not bar.btn_corners.isEnabled())
n0 = len(ed.undo_stack)
before = ed.doc.snapshot()
bar.frad.setValue(8, emit=True)
R, P, S = ed.doc.shapes
check("R = 8 a tutte in un passo, ognuna al suo massimo", len(ed.undo_stack) == n0 + 1 and R.radius == 8 and P.radius == 8
      and S.radius == round(S.max_radius(), 2), (R.radius, P.radius, S.radius))
ed.undo()
und = ed.doc.snapshot() == before
ed.redo()
check("Annulla e Ripeti", und and ed.doc.shapes[1].radius == 8)

# ---------------------------------------------------------------- 6. forme senza raggio
C, T, L = fresh(mk(EllipseShape(30, 30), 0, 0), mk(TextShape("A", size=10), 50, 0), mk(RectShape(10, 10), 90, 0))
G = GroupShape([mk(RectShape(5, 5), 0, 50)])
ed.add([G])
for sel, why in (([C], "cerchio"), ([T], "testo"), ([G], "gruppo")):
    ed.select(sel)
    bar.refresh()
    check(f"campo R spento con un {why}", not bar.frad.isEnabled())
L.locked = True
ed.select([L])
bar.refresh()
check("campo R spento con un rettangolo bloccato", not bar.frad.isEnabled())
L.locked = False
ed.select([C, L])
bar.refresh()
check("cerchio + rettangolo: R acceso, vale solo per il rettangolo", bar.frad.isEnabled())
bar.frad.setValue(2, emit=True)
check("…e il cerchio non cambia", ed.doc.shapes[2].radius == 2 and isinstance(ed.doc.shapes[0], EllipseShape))
ed.select([])
bar.refresh()
check("senza selezione: campo spento", not bar.frad.isEnabled())

# ---------------------------------------------------------------- 7. barra e pannello allineati
R, = fresh(mk(RectShape(60, 40), 0, 0))
ed.select([R])
app.processEvents()
props = getattr(w, "props", None) or getattr(w, "properties", None)
spins = getattr(props, "radius_spins", None) if props is not None else None
bar.frad.setValue(7, emit=True)
app.processEvents()
spins = getattr(props, "radius_spins", None) if props is not None else None
check("barra → pannello: il pannello Proprietà mostra 7", spins and abs(spins[0].value() - 7) < 1e-9,
      spins[0].value() if spins else None)
if spins:
    spins[0].setValue(3)
    app.processEvents()
    bar.refresh()
check("pannello → barra: la barra mostra 3", abs(bar.frad.value() - 3) < 1e-9, bar.frad.value())
P, = fresh(mk(PolygonShape(40, 40, 6), 0, 0))
ed.select([P])
app.processEvents()
spins = getattr(props, "radius_spins", None) if props is not None else None
check("pannello Proprietà del poligono: c'è il raggio degli angoli", spins and len(spins) == 1)
if spins:
    spins[0].setValue(5)
check("…e cambia il poligono (un passo, mm veri)", ed.doc.shapes[0].radius == 5)

# ---------------------------------------------------------------- 8. aiuto
check("schede d'aiuto del campo R e del pulsante dei 4 angoli", help_texts.lookup("num:radius") is not None
      and help_texts.lookup("num:corners") is not None)

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
