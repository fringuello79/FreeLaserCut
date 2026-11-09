# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.17: dopo le forbici i pezzi che si toccano restano agganciati (una forma sola, anelli chiusi);
«Unisci estremi» corretto per i pezzi orientati al contrario (inizio-inizio, inizio-fine).

Casi del documento «forbici-taglia-eccedenze» (parte 0.17.17).
"""
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
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath, QTransform
from PySide6.QtWidgets import QApplication

app = QApplication([])
import freelasercut
from freelasercut.core import nodes, ops
from freelasercut.core.document import EllipseShape, PathShape, RectShape
from freelasercut.updater import parse_version
from freelasercut.ui.main_window import MainWindow

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


check("versione 0.17.17 o successiva", parse_version(freelasercut.__version__) >= (0, 17, 17), freelasercut.__version__)


# ---------------------------------------------------------------- «Unisci estremi»: le quattro orientazioni
def sub(*pts, curve=False):
    """Sottotracciato aperto; con curve=True il primo tratto è un arco di Bézier (per vedere che le curve restano)."""
    sp = nodes.SubPath([nodes.Node(*p) for p in pts], False)
    if curve:
        a, b = sp.nodes[0], sp.nodes[1]
        a.cout = (a.x + (b.x - a.x) / 3, a.y + 8)
        b.cin = (a.x + 2 * (b.x - a.x) / 3, a.y + 8)
    return sp


def length(subs):
    return nodes.to_path(subs).length()


def on(subs_new, subs_old, n=80):
    """Distanza massima dei punti del nuovo tracciato dal vecchio (0 = nessun salto inventato)."""
    pn = nodes.to_path(subs_new)
    worst = 0.0
    for k in range(n + 1):
        q = pn.pointAtPercent(k / n)
        d = min(nodes.nearest_on_segment(sp, i, j, (q.x(), q.y()))[1] for sp in subs_old for i, j in sp.segments())
        worst = max(worst, d)
    return worst


A = ((0, 0), (40, 0))
B = ((40, 0), (40, 30))
cases = {"fine-inizio": (A, B), "fine-fine": (A, B[::-1]), "inizio-fine": (A[::-1], B[::-1]),
         "inizio-inizio": (A[::-1], B)}
for name, (pa, pb) in cases.items():
    old = [sub(*pa, curve=True), sub(*pb)]
    ref = [s.copy() for s in old]
    L0 = length(ref)
    res = nodes.join_endpoints(old, 1e-4)
    ok = len(res) == 1 and abs(length(res) - L0) < 1e-6 and on(res, ref) < 1e-6
    check(f"Unisci estremi, {name}: un pezzo solo, stessa lunghezza, nessun salto, curve intatte", ok,
          (len(res), length(res), L0))
sq = [sub((0, 0), (10, 0)), sub((10, 10), (10, 0)), sub((10, 10), (0, 10)), sub((0, 0), (0, 10))]
res = nodes.join_endpoints([s.copy() for s in sq], 1e-4)
check("quattro lati orientati a caso: un anello chiuso di 40 mm", len(res) == 1 and res[0].closed
      and abs(length(res) - 40) < 1e-6)
p_ = QPainterPath()
for s_ in sq:
    p_.moveTo(*s_.nodes[0].pt())
    p_.lineTo(*s_.nodes[1].pt())
shp, joined = ops.auto_join([PathShape(p_)], 0.05)
check("comando Unisci estremi sui quattro lati: forma chiusa", joined == 3 and len(nodes.from_path(shp.path())) == 1
      and nodes.from_path(shp.path())[0].closed)

# ---------------------------------------------------------------- forbici: pezzi agganciati
w = MainWindow()
ed, cv = w.editor, w.canvas
cv.set_tool("trim")
tool = cv.tool


def mk(shape, x, y):
    b = shape.bounds()
    shape.apply(QTransform.fromTranslate(x - b.left(), y - b.top()))
    return shape


def fresh(*shapes):
    ed.doc.shapes.clear()
    ed.selection = []
    ed.add(list(shapes))
    ed.select([])
    return [x.id for x in shapes]


def by_id(i):
    return next((x for x in ed.doc.shapes if x.id == i), None)


class _Ev:
    def button(self):
        return Qt.LeftButton

    def buttons(self):
        return Qt.NoButton

    def modifiers(self):
        return Qt.NoModifier


def cut(x, y):
    tool.press(_Ev(), QPointF(x, y))


# contorno unito di un rettangolo e di un cerchio: tagliate le due parti interne resta UNA forma chiusa
R0, C0 = mk(RectShape(60, 40), 0, 0), mk(EllipseShape(40, 40), 40, 10)
ref = nodes.from_path(R0.path()) + nodes.from_path(C0.path())
ir, ic = fresh(R0, C0)
before = ed.doc.snapshot()
n0 = len(ed.undo_stack)
cut(60, 25)  # lato destro del rettangolo, dentro il cerchio
mid_shapes = len(ed.doc.shapes)
cut(40, 30)  # arco sinistro del cerchio, dentro il rettangolo
shapes = list(ed.doc.shapes)
one = shapes[0] if len(shapes) == 1 else None
subs_ = nodes.from_path(one.path()) if one else []
check("rettangolo + cerchio: dopo il primo taglio ancora due forme (il cerchio è chiuso, niente da agganciare)",
      mid_shapes == 2)
check("…dopo il secondo una forma sola, un anello chiuso", one is not None and len(subs_) == 1 and subs_[0].closed,
      (len(shapes), [s.closed for s in subs_]))
inside = [(10, 20), (70, 30), (50, 20)]  # solo rettangolo, solo cerchio, tutti e due
outside = [(70, 2), (45, 45), (90, 30)]
fill_ok = one is not None and all(one.path().contains(QPointF(*q)) for q in inside) and not any(
    one.path().contains(QPointF(*q)) for q in outside)
check("si riempie come un pezzo unico: dentro il contorno sì, fuori no", fill_ok)
check("il contorno è fatto solo di linee che c'erano (nessun salto)", one is not None and on(subs_, ref) < 1e-6)
check("tiene l'id e il livello della forma tagliata per ultima", one is not None and one.id == ic and one.layer == C0.layer)
check("un passo per ogni clic", len(ed.undo_stack) == n0 + 2)
b0 = one.bounds()
one.apply(QTransform.fromTranslate(15, 0))
check("spostandolo si sposta tutto il contorno, non resta niente indietro", len(ed.doc.shapes) == 1
      and abs(ed.doc.shapes[0].bounds().left() - b0.left() - 15) < 1e-9)
ed.undo()
ed.undo()
check("due Annulla: tornano rettangolo e cerchio come prima", ed.doc.snapshot() == before)

# lente di due cerchi: tolte le due parti interne resta il contorno esterno chiuso
i1, i2 = fresh(mk(EllipseShape(40, 40), 0, 0), mk(EllipseShape(40, 40), 25, 0))
cut(40, 20)
cut(25, 20)
sh = list(ed.doc.shapes)
check("due cerchi sovrapposti: contorno esterno unico e chiuso", len(sh) == 1
      and len(nodes.from_path(sh[0].path())) == 1 and nodes.from_path(sh[0].path())[0].closed)

# livelli diversi, forme bloccate e lontane non si agganciano
R1, C1 = mk(RectShape(60, 40), 0, 0), mk(EllipseShape(40, 40), 40, 10)
C1.layer = 2
ir, ic = fresh(R1, C1)
cut(60, 25)
cut(40, 30)
check("su livelli diversi restano due forme (ognuna con il suo livello)", len(ed.doc.shapes) == 2
      and {s.layer for s in ed.doc.shapes} == {R1.layer, 2})
R2, C2 = mk(RectShape(60, 40), 0, 0), mk(EllipseShape(40, 40), 40, 10)
ir, ic = fresh(R2, C2)
cut(60, 25)
by_id(ir).locked = True
cut(40, 30)
check("una forma bloccata non viene assorbita", len(ed.doc.shapes) == 2 and by_id(ir) is not None and by_id(ir).locked)
pa = QPainterPath()
pa.moveTo(0, 0)
pa.lineTo(100, 0)
pb = QPainterPath()
pb.moveTo(30, -20)
pb.lineTo(30, 20)
far = QPainterPath()
far.moveTo(200, 200)
far.lineTo(250, 200)
ih, iv, ifar = fresh(PathShape(pa), PathShape(pb), PathShape(far))
cut(10, 0)
check("le forme che non toccano restano fuori", by_id(ifar) is not None and len(ed.doc.shapes) == 3)

# testo: le lettere chiuse non si agganciano a niente (nessun estremo)
check("strumento Forbici sempre presente nel menu Strumenti", w.tool_actions["trim"] in
      [a for m in w.menuBar().actions() if m.menu() for a in m.menu().actions()])

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
