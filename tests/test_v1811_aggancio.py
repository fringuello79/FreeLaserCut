# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.11: aggancio mentre si sposta un oggetto. Da una segnalazione su un forum: «l'aggancio "angolo" non avviene
fra angolo ed angolo, ma fra l'angolo dell'oggetto vicino ed il punto in cui ho selezionato col mouse il
trascinamento. Manca l'effetto "magnetico" che affianca due elementi geometrici ai loro angoli/mezzerie».

Prima si agganciava il punto del mouse. Ora si agganciano i punti dell'oggetto che si sposta.

Casi provati (calcolo da solo, poi trascinamenti veri con lo strumento Selezione, Classica e Banco):
1 punto su punto: angolo su angolo, mezzeria su mezzeria, centro su centro, nodo su nodo e angolo su nodo; fra due
  bersagli vince il più vicino; fuori dal raggio niente;
2 lato su lato: il bordo resta appoggiato mentre l'oggetto scorre; centro su centro su un asse; forme lontane ignorate;
3 griglia: sulla griglia va l'angolo dell'oggetto, non il punto del mouse; gli oggetti vincono sulla griglia;
4 il punto in cui si prende l'oggetto non conta più; più oggetti selezionati si spostano insieme; Alt sospende;
  «Aggancio oggetti» spento; Maiusc tiene l'asse; un solo Annulla; il clic senza trascinare non sposta;
5 disegni fitti: resta veloce.
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core import snapping  # noqa: E402
from freelasercut.core.document import PathShape, RectShape  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []
EPS = 1e-6


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def near(a, b, eps=EPS):
    return abs(a - b) <= eps


# ================================================================== 1. il calcolo, da solo
A_BOX = (100.0, 100.0, 160.0, 140.0)  # la forma ferma: 60 × 40
T = np.array(snapping.box_points(*A_BOX), float)
K = list(snapping.BOX_KINDS)
B_BOX = (300.0, 300.0, 330.0, 320.0)  # quella che si sposta: 30 × 20
R = 4.0


def go(dx, dy, box=B_BOX, nodes=(), targets=T, kinds=K, boxes=(A_BOX,), radius=R, grid=None):
    return snapping.move(box, list(nodes), dx, dy, targets, kinds, list(boxes), radius, grid)


def placed(r, box=B_BOX):
    return box[0] + r.dx, box[1] + r.dy, box[2] + r.dx, box[3] + r.dy


r = go(160 - 300 + 2.5, 100 - 300 - 1.5)  # l'angolo in basso a sinistra di B a 2,9 mm dall'angolo di A
check("angolo su angolo: l'angolo di chi si sposta finisce esattamente sull'angolo dell'altro",
      r.how == "punto" and r.label == "angolo" and near(placed(r)[0], 160) and near(placed(r)[1], 100)
      and r.hint == (160.0, 100.0), (r.dx, r.dy, r.how, r.label))
r = go(160 - 300 + 1.0, 120 - 310 + 2.0)  # mezzeria del lato sinistro di B vicino alla mezzeria del lato destro di A
check("mezzeria su mezzeria: i due pezzi restano affiancati e centrati", r.how == "punto" and r.label == "metà"
      and near(placed(r)[0], 160) and near((placed(r)[1] + placed(r)[3]) / 2, 120), (placed(r), r.label))
r = go(130 - 315 - 1.2, 120 - 310 + 0.8)
check("centro su centro: uno dentro l'altro, concentrici", r.how == "punto" and r.label == "centro"
      and near((placed(r)[0] + placed(r)[2]) / 2, 130) and near((placed(r)[1] + placed(r)[3]) / 2, 120), placed(r))
two = np.vstack([T, [[163.0, 100.0]]])
r = go(160 - 300 + 2.2, 100 - 300, targets=two, kinds=K + ["nodo"])  # l'angolo di B a 2,2 da un bersaglio e 0,8 dall'altro
check("due bersagli a tiro: vince il più vicino", r.label == "nodo" and near(placed(r)[0], 163), (placed(r), r.label))
r = go(160 - 300 + 3.0, 100 - 300 + 3.0)  # a 4,24 mm: appena fuori dal raggio di 4 mm, ma i lati no
check("angolo appena fuori dal raggio: nessun aggancio di punto", r.how != "punto", r.how)
r = go(160 - 300 + 9.0, 100 - 300 + 55.0)
check("lontano da tutto: lo spostamento resta quello del mouse", r.how is None and (r.dx, r.dy) == (160 - 300 + 9.0, -145.0)
      and r.hint is None, (r.dx, r.dy, r.how))
quad_nodes = [(300.0, 300.0), (350.0, 310.0), (330.0, 340.0), (305.0, 325.0)]  # un quadrilatero: vertici non sull'ingombro
r = go(100 - 350 + 1.5, 140 - 310 - 1.0, box=(300.0, 300.0, 350.0, 340.0), nodes=quad_nodes)
check("nodo su angolo: il vertice della forma che si sposta finisce sull'angolo dell'altra",
      r.how == "punto" and near(350 + r.dx, 100) and near(310 + r.dy, 140), (r.dx, r.dy))
r = go(120 - 300 + 1.0, 111 - 300 - 1.0, targets=np.vstack([T, [[120.0, 111.0]]]), kinds=K + ["nodo"])
check("angolo su nodo: l'angolo finisce sul nodo dell'altra forma", r.label == "nodo" and near(placed(r)[0], 120)
      and near(placed(r)[1], 111), placed(r))

r = go(160 - 300 + 1.6, 100 - 300 + 15.5)  # bordo sinistro di B a 1,6 dal bordo destro di A; in verticale sfalsato
check("lato su lato: il bordo si appoggia al bordo, e in verticale l'oggetto resta dove lo porta il mouse",
      r.how == "lato" and r.label == "lato" and near(placed(r)[0], 160) and near(placed(r)[1], 115.5), (placed(r), r.how))
ys = [placed(go(160 - 300 + 1.6, 100 - 300 + dy_))[0] for dy_ in (6.0, 7.5, 13.0, 14.5, 26.0)]
check("…e resta appoggiato mentre scorre lungo il lato", all(near(v, 160) for v in ys), ys)
r = go(130 - 315 + 3.0, 140 - 300 + 3.9)  # sotto A a 3,9 dal suo bordo, centro a 3 dalla verticale: nessun punto entro 4 mm
check("sotto l'altro, nessun punto a tiro: bordo su bordo su un asse, centro su centro sull'altro", r.how == "lato"
      and near((placed(r)[0] + placed(r)[2]) / 2, 130) and near(placed(r)[1], 140), (placed(r), r.label, r.how))
r = go(130 - 315 + 2.0, 140 - 300 + 9.0)  # lo stesso, ma staccato di 9 mm: non è più una forma vicina
check("…staccato più del raggio non si allinea più", r.how is None, r.how)
r = go(160 - 300 + 1.6, 100 - 300 + 200.0)
check("una forma lontana non allinea i bordi (niente strappi verso oggetti dall'altra parte del piano)",
      r.how is None and near(r.dx, -138.4), (r.dx, r.how))
r = go(160 - 300 + 1.6, 100 - 300 + 6.0, radius=0.0)
check("raggio zero: nessun aggancio", r.how is None)

r = go(12.3, 7.4, box=(300.0, 300.0, 330.0, 320.0), targets=None, kinds=[], boxes=(), grid=5.0)
check("griglia: va sulla griglia l'angolo dell'oggetto (parte da 300;300, il mouse chiede +12,3 +7,4 → +10 +5)",
      r.how == "griglia" and near(r.dx, 10) and near(r.dy, 5) and r.label == "griglia", (r.dx, r.dy))
r = go(12.3, 7.4, box=(301.3, 300.0, 333.5, 320.0), targets=None, kinds=[], boxes=(), grid=5.0)
check("griglia con un oggetto fuori passo: ci va il bordo più vicino (qui il destro)",
      near((333.5 + r.dx) % 5, 0, 1e-9) or near((333.5 + r.dx) % 5, 5, 1e-9), r.dx)
r = go(13.9, 7.4, box=(301.3, 300.0, 333.5, 320.0), targets=None, kinds=[], boxes=(), grid=5.0)
check("…o il sinistro, quando è lui il più vicino a una riga della griglia",
      near(301.3 + r.dx, 315.0) and near(r.dx, 13.7), r.dx)
r = go(160 - 300 + 1.6, 100 - 300 + 6.2, grid=5.0)
check("lato e griglia insieme: il bordo sull'oggetto, l'altro asse sulla griglia",
      r.how == "lato" and near(placed(r)[0], 160) and near(placed(r)[1] % 5, 0, 1e-9), placed(r))
r = go(160 - 300 + 2.5, 100 - 300 - 1.5, grid=5.0)
check("gli oggetti vincono sulla griglia", r.how == "punto" and near(placed(r)[0], 160) and near(placed(r)[1], 100))
inner = [(308.0, 306.0)]  # un nodo dentro l'ingombro, lontano dai suoi 9 punti
one = np.array([[120.0, 111.0]])
r1 = go(120 - 308 + 0.3, 111 - 306, nodes=inner, targets=one, kinds=["nodo"], boxes=())
many = inner + [(309.0 + (i % 20) * 0.1, 307.0 + (i // 20) * 0.01) for i in range(snapping.MAX_NODES)]
r2 = go(120 - 308 + 0.3, 111 - 306, nodes=many, targets=one, kinds=["nodo"], boxes=())
check("selezione con troppi nodi: si usano solo i punti dell'ingombro (con pochi nodi lo stesso nodo aggancia)",
      r1.how == "punto" and near(308 + r1.dx, 120) and r2.how is None, (r1.how, r2.how))
rng = np.random.default_rng(7)
big_t = rng.uniform(0, 400, (20000, 2))
big_n = [tuple(v) for v in rng.uniform(300, 330, (1200, 2))]
t0 = time.perf_counter()
for k in range(20):
    snapping.move(B_BOX, big_n, -150.0 + k, -150.0, big_t, ["nodo"] * 20000, [A_BOX] * 300, R, None)
ms = (time.perf_counter() - t0) / 20 * 1000
check("disegno fitto (20000 punti attorno, 1200 nodi che si spostano): meno di 60 ms a movimento", ms < 60, round(ms, 1))

# ================================================================== 2. trascinamenti veri
w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas
cv.set_tool("select")
tool = cv.tool
cv.snap_objects, cv.snap_grid = True, False
RAD = cv.px(9)
U = max(RAD * 2.5, 5.0)  # un'unità ben più grande del raggio: i casi non si pestano i piedi a nessuno zoom


def mk(shape, x, y):
    b = shape.bounds()
    shape.apply(QTransform.fromTranslate(x - b.left(), y - b.top()))
    return shape


def fresh(*shapes):
    ed.doc.shapes.clear()
    ed.selection = []
    ed.add(list(shapes), select=False)
    app.processEvents()
    return list(shapes)


def _ev(kind, p, mods, down):
    v = cv.bed_to_view_tf().map(p)
    return QMouseEvent(kind, v, cv.viewport().mapToGlobal(v.toPoint()), Qt.LeftButton,
                       Qt.LeftButton if down else Qt.NoButton, mods)


def grab_point(s, fx, fy):
    """Un punto del bordo inferiore/superiore della forma, a una frazione fx della larghezza (fy = 0 o 1): è lì che
    il mouse la prende. Apposta lontano dagli angoli."""
    b = s.bounds()
    return QPointF(b.left() + fx * b.width(), b.top() + fy * b.height())


def drag(s, to_left, to_top, fx=0.37, fy=0.0, mods=Qt.NoModifier, select=True, release=True, grab=None):
    """Trascina s prendendola nel punto (fx, fy) in modo che il mouse chieda di portare il suo ingombro con l'angolo
    (left, top) in (to_left, to_top). -> lo spostamento chiesto dal mouse."""
    if select:
        ed.select([s])
        app.processEvents()
    b = ed.selection_bounds()
    g = grab if grab is not None else grab_point(s, fx, fy)
    dx, dy = to_left - b.left(), to_top - b.top()
    tool.press(_ev(QEvent.MouseButtonPress, g, Qt.NoModifier, True), g)
    assert tool.mode == "move", f"la presa in {g} non sposta ({tool.mode}): è finita su una maniglia o nel vuoto"
    for k in (0.5, 1.0):
        q = QPointF(g.x() + dx * k, g.y() + dy * k)
        tool.move(_ev(QEvent.MouseMove, q, mods, True), q)
    if release:
        tool.release(_ev(QEvent.MouseButtonRelease, q, Qt.NoModifier, False), q)
        app.processEvents()
    return dx, dy


def scene():
    a = mk(RectShape(12 * U, 8 * U), 100, 100)
    b = mk(RectShape(6 * U, 3 * U), 100 + 30 * U, 100 + 20 * U)  # alto 3U: nessun suo punto cade su una mezzeria di a
    return fresh(a, b)


A, B = scene()
ab = A.bounds()
drag(B, ab.right() + 0.6 * RAD, ab.top() - 0.5 * RAD, release=False)
hint = cv.snap_hint
tool.release(_ev(QEvent.MouseButtonRelease, QPointF(0, 0), Qt.NoModifier, False), QPointF(0, 0))
app.processEvents()
bb = B.bounds()
check("trascinando un rettangolo vicino a un altro: angolo su angolo, esatto (i due lati combaciano)",
      near(bb.left(), ab.right()) and near(bb.top(), ab.top()), (bb.left() - ab.right(), bb.top() - ab.top()))
check("…e durante il trascinamento il segno giallo è sull'angolo, con la scritta «angolo»",
      hint is not None and hint[1] == "angolo" and near(hint[0].x(), ab.right()) and near(hint[0].y(), ab.top()), hint)
outs = []
for fx, fy in ((0.12, 0.0), (0.62, 1.0), (0.88, 1.0), (0.31, 0.0)):
    A, B = scene()
    drag(B, A.bounds().right() - 0.5 * RAD, A.bounds().top() + 0.6 * RAD, fx=fx, fy=fy)
    outs.append((round(B.bounds().left() - A.bounds().right(), 6), round(B.bounds().top() - A.bounds().top(), 6)))
check("il punto in cui si prende l'oggetto non conta: da quattro prese diverse, sempre angolo su angolo",
      outs == [(0.0, 0.0)] * 4, outs)
A, B = scene()
ab = A.bounds()
drag(B, ab.right() + 0.5 * RAD, ab.center().y() - 1.5 * U + 0.4 * RAD)
bb = B.bounds()
check("mezzeria su mezzeria: affiancati e centrati", near(bb.left(), ab.right()) and near(bb.center().y(), ab.center().y()),
      (bb.left() - ab.right(), bb.center().y() - ab.center().y()))
A, B = scene()
ab = A.bounds()
want_top = ab.top() + 2 * U  # i punti di B a 2U, 3,5U e 5U da sopra: lontani più del raggio da 0, 4U e 8U di A
drag(B, ab.right() + 0.5 * RAD, want_top, release=False)
hint = cv.snap_hint
tool.release(_ev(QEvent.MouseButtonRelease, QPointF(0, 0), Qt.NoModifier, False), QPointF(0, 0))
bb = B.bounds()
check("lato su lato: il bordo si appoggia al bordo dell'altro, l'altezza resta quella scelta con il mouse",
      near(bb.left(), ab.right()) and near(bb.top(), want_top) and hint is not None and hint[1] == "lato",
      (bb.left() - ab.right(), bb.top() - want_top, hint))
A, B = scene()
ab = A.bounds()
dx, dy = drag(B, ab.right() + 2.0 * RAD, ab.top() + U)
check("fuori dal raggio: l'oggetto va dove lo porta il mouse", near(B.bounds().left(), ab.right() + 2.0 * RAD)
      and near(B.bounds().top(), ab.top() + U), B.bounds())
A, B = scene()
ab = A.bounds()
drag(B, ab.right() + 0.6 * RAD, ab.top() - 0.5 * RAD, mods=Qt.AltModifier)
check("con Alt l'aggancio è sospeso", near(B.bounds().left(), ab.right() + 0.6 * RAD) and near(B.bounds().top(), ab.top() - 0.5 * RAD)
      and cv.snap_hint is None)
A, B = scene()
ab = A.bounds()
cv.snap_objects = False
drag(B, ab.right() + 0.6 * RAD, ab.top() - 0.5 * RAD)
cv.snap_objects = True
check("con «Aggancio oggetti» spento non si aggancia", near(B.bounds().left(), ab.right() + 0.6 * RAD)
      and near(B.bounds().top(), ab.top() - 0.5 * RAD))

# nodi
qp = QPainterPath()
qp.moveTo(0, 0)
qp.lineTo(10 * U, 2 * U)
qp.lineTo(6 * U, 8 * U)
qp.lineTo(1 * U, 5 * U)
qp.closeSubpath()
A = mk(RectShape(12 * U, 8 * U), 100, 100)
Q = mk(PathShape(qp), 100 + 30 * U, 100 + 20 * U)
fresh(A, Q)
ab, q0 = A.bounds(), Q.bounds()
# il vertice a destra del quadrilatero (10U; 2U dentro il suo ingombro) vicino all'angolo in alto a sinistra… di A
ed.select([Q])
app.processEvents()
on_edge = next(q for q in (Q.path().pointAtPercent(k * 0.0617 % 1.0) for k in range(1, 60))
               if cv.hit_shape(q) is Q and tool._hit_handle(cv.bed_to_view_tf().map(q), cv.bed_to_view_tf()) is None)
drag(Q, ab.left() - 10 * U - 0.5 * RAD, ab.bottom() - 2 * U + 0.4 * RAD, grab=on_edge, select=False)
vx = [Q.path().elementAt(i) for i in range(Q.path().elementCount())]
hit = min(((e.x - ab.left()) ** 2 + (e.y - ab.bottom()) ** 2) ** 0.5 for e in vx)
check("nodo su angolo: il vertice del tracciato che si sposta finisce esattamente sull'angolo dell'altra forma",
      hit < EPS, hit)
A = mk(RectShape(4 * U, 3 * U), 100 + 40 * U, 100)
Q = mk(PathShape(qp), 100, 100 + 20 * U)
fresh(Q, A)
node = max((Q.path().elementAt(i) for i in range(Q.path().elementCount())), key=lambda e: e.x)  # il vertice a destra
drag(A, node.x + 0.5 * RAD, node.y - 0.5 * RAD, release=False)
hint = cv.snap_hint
tool.release(_ev(QEvent.MouseButtonRelease, QPointF(0, 0), Qt.NoModifier, False), QPointF(0, 0))
check("angolo su nodo: l'angolo del rettangolo finisce sul vertice del tracciato, con la scritta «nodo»",
      near(A.bounds().left(), node.x) and near(A.bounds().top(), node.y) and hint is not None and hint[1] == "nodo",
      (A.bounds().left() - node.x, A.bounds().top() - node.y, hint))

# più oggetti insieme
A = mk(RectShape(12 * U, 8 * U), 100, 100)
B = mk(RectShape(6 * U, 4 * U), 100 + 30 * U, 100 + 20 * U)
C = mk(RectShape(3 * U, 3 * U), 100 + 37 * U, 100 + 21 * U)
fresh(A, B, C)
ed.select([B, C])
app.processEvents()
gap = (C.bounds().left() - B.bounds().left(), C.bounds().top() - B.bounds().top())
n0 = len(ed.undo_stack)
drag(B, A.bounds().right() + 0.6 * RAD, A.bounds().top() + 0.5 * RAD, select=False)
check("due oggetti selezionati: si spostano insieme, e si aggancia l'angolo dell'ingombro di tutti e due",
      near(B.bounds().left(), A.bounds().right()) and near(B.bounds().top(), A.bounds().top())
      and near(C.bounds().left() - B.bounds().left(), gap[0]) and near(C.bounds().top() - B.bounds().top(), gap[1]),
      (B.bounds().left() - A.bounds().right(), gap))
check("…in un solo passo da annullare", len(ed.undo_stack) == n0 + 1)
ed.undo()
lefts = sorted(s.bounds().left() for s in ed.doc.shapes)
check("Annulla rimette tutti e due dov'erano", len(lefts) == 3 and near(lefts[1], 100 + 30 * U) and near(lefts[2], 100 + 37 * U),
      lefts)

A = mk(RectShape(12 * U, 8 * U), 100, 100)
B = mk(RectShape(6 * U, 3 * U), 100 + 30 * U, 100 + U + 0.4 * RAD)  # sulla fascia di A, più a destra: il suo angolo
fresh(A, B)                                                          # in basso passerà a 0,4 raggi dalla mezzeria di A
ab = A.bounds()
top0 = B.bounds().top()
drag(B, ab.right() + 0.6 * RAD, top0 + 0.9 * U, mods=Qt.ShiftModifier)
check("con Maiusc lo spostamento resta su un asse solo (qui l'orizzontale), e su quell'asse si aggancia",
      near(B.bounds().top(), top0) and near(B.bounds().left(), ab.right()), (B.bounds().top() - top0, B.bounds().left() - ab.right()))
A, B = scene()
ab = A.bounds()
left0, top0 = B.bounds().left(), B.bounds().top()
drag(B, left0 - 3 * U, ab.bottom() + 0.5 * RAD, mods=Qt.ShiftModifier)  # soprattutto in verticale, verso il bordo di A
check("…e con Maiusc in verticale l'oggetto non si sposta di lato",
      near(B.bounds().left(), left0) and near(B.bounds().top(), ab.bottom() + 0.5 * RAD),
      (B.bounds().left() - left0, B.bounds().top() - ab.bottom()))
A, B = scene()
left0, top0 = B.bounds().left(), B.bounds().top()
drag(B, left0 + 0.5 * RAD, top0 + 0.3 * RAD)
check("uno spostamento piccolo resta piccolo: l'oggetto non si aggancia al posto da cui è partito",
      near(B.bounds().left(), left0 + 0.5 * RAD) and near(B.bounds().top(), top0 + 0.3 * RAD),
      (B.bounds().left() - left0, B.bounds().top() - top0))
A, B = scene()
ed.select([B])
g = grab_point(B, 0.37, 0.0)
left0 = B.bounds().left()
n0 = len(ed.undo_stack)
tool.press(_ev(QEvent.MouseButtonPress, g, Qt.NoModifier, True), g)
q = cv.to_bed(cv.bed_to_view_tf().map(g) + QPointF(2, 0))
tool.move(_ev(QEvent.MouseMove, q, Qt.NoModifier, True), q)
tool.release(_ev(QEvent.MouseButtonRelease, q, Qt.NoModifier, False), q)
check("un clic con due pixel di tremolio non sposta niente e non entra nella cronologia",
      near(B.bounds().left(), left0) and len(ed.undo_stack) == n0)

# griglia
cv.snap_objects, cv.snap_grid = False, True
app.processEvents()
G = cv.grid_step
B = mk(RectShape(24 * G, 16 * G), 20 * G, 12 * G)
fresh(B)
drag(B, 20 * G + 2.3 * G, 12 * G + 1.4 * G, fx=0.37, fy=0.0)
bb = B.bounds()
check("griglia: un oggetto che era sulla griglia ci resta (prima andava sulla griglia il punto del mouse, e l'oggetto no)",
      near(bb.left(), 22 * G) and near(bb.top(), 13 * G) and cv.grid_step == G, (bb.left() / G, bb.top() / G))
cv.snap_objects = True
A = mk(RectShape(24 * G, 16 * G), 10 * G + 0.37 * G, 10 * G + 0.21 * G)  # fuori passo
B = mk(RectShape(16 * G, 12 * G), 50 * G, 40 * G)
fresh(A, B)
ab = A.bounds()
drag(B, ab.right() + 0.5 * cv.px(9), ab.top() + 0.4 * cv.px(9))
check("oggetti e griglia accesi insieme: vince l'angolo dell'oggetto vicino",
      near(B.bounds().left(), ab.right()) and near(B.bounds().top(), ab.top()), (B.bounds().left() - ab.right(),))
cv.snap_grid = False

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
