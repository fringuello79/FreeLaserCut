# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.19.5: strumento Nodi con più nodi selezionati e unione di due nodi.

- Si vedono i nodi di tutte le forme selezionate; Ctrl/Maiusc+clic aggiunge o toglie un nodo, il rettangolo sul vuoto
  prende i nodi dentro, Ctrl+A tutti, Esc toglie la scelta (di nuovo: torna a Selezione).
- Spostamento, elimina, angolo/morbido valgono per tutti i nodi selezionati; le maniglie solo con un nodo.
- 0.20.6: un estremo lasciato sopra l'estremo di un'altra linea (selezionata o no) le unisce in una; D su un tratto in
  mezzo a una linea lascia due linee separate.
- J fonde due estremi aperti in un punto a metà strada, Maiusc+J li collega con un tratto dritto; stessa linea = la
  chiude; due forme = una sola, sul livello del primo nodo selezionato; un solo Annulla per unione.
Uso: python tests/test_v195_nodi.py [banco]
"""
import math
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
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPainterPath, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

import freelasercut
from freelasercut.core import nodes as N
from freelasercut.core.document import GroupShape, PathShape, RectShape
from freelasercut.updater import parse_version
from freelasercut.ui.main_window import MainWindow

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def line(*pts, layer=1, closed=False):
    p = QPainterPath()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if closed:
        p.closeSubpath()
    return PathShape(p, layer=layer)


def pts_of(s):
    return [[n.pt() for n in sp.nodes] for sp in N.from_path(s.path())]


def close(a, b, tol=0.05):
    return math.dist(a, b) <= tol


check("versione 0.19.5 o successiva", parse_version(freelasercut.__version__) >= (0, 19, 5), freelasercut.__version__)

# ---------------------------------------------------------------- modello: join_two
subs = N.from_path(line((0, 0), (10, 0)).path()) + N.from_path(line((20, 0), (30, 0)).path())
why = N.join_two(subs, (0, 1), (1, 0), "merge")
check("modello: fondi due linee (fine-inizio) -> una linea di 3 nodi col punto a metà",
      why is None and len(subs) == 1 and len(subs[0].nodes) == 3 and close(subs[0].nodes[1].pt(), (15, 0)), (why, subs))
subs = N.from_path(line((0, 0), (10, 0)).path()) + N.from_path(line((20, 0), (30, 0)).path())
why = N.join_two(subs, (0, 0), (1, 1), "connect")
pp = [n.pt() for n in subs[0].nodes]
check("modello: collega inizio con fine (giri giusti), nodi fermi, 4 nodi",
      why is None and len(subs) == 1 and len(pp) == 4 and {pp[0], pp[-1]} == {(10.0, 0.0), (20.0, 0.0)}, pp)
check("modello: il tratto nuovo è dritto (nessuna maniglia)",
      not any(subs[0].is_curve(i, j) for i, j in subs[0].segments()))
for ea, eb in (((0, 0), (1, 0)), ((0, 1), (1, 1))):
    subs = N.from_path(line((0, 0), (10, 0)).path()) + N.from_path(line((10, 5), (30, 5)).path())
    why = N.join_two(subs, ea, eb, "connect")
    xs = [n.pt() for n in subs[0].nodes]
    seglen = sum(math.dist(xs[i], xs[i + 1]) for i in range(len(xs) - 1))
    check(f"modello: estremi {ea}/{eb}: nessun pezzo perso, nessun salto (lunghezza giusta)",
          why is None and len(xs) == 4 and abs(seglen - (10 + 20 + math.dist(xs[1], xs[2]))) < 1e-6
          and set(xs) == {(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (30.0, 5.0)}, xs)
subs = N.from_path(line((0, 0), (10, 0), (10, 10)).path())
check("modello: stessa linea di 3 nodi, fondi: no (resterebbero 2 nodi, non una forma)",
      N.join_two(subs, (0, 0), (0, 2), "merge") is not None and not subs[0].closed and len(subs[0].nodes) == 3)
subs = N.from_path(line((0, 0), (10, 0), (10, 10), (0, 10)).path())
N.join_two(subs, (0, 0), (0, 3), "merge")
check("modello: stessa linea di 4 nodi, fondi: chiusa con 3 nodi, il punto in comune a metà",
      subs[0].closed and len(subs[0].nodes) == 3 and close(subs[0].nodes[0].pt(), (0, 5)), [n.pt() for n in subs[0].nodes])
subs = N.from_path(line((0, 0), (10, 0), (10, 10)).path())
N.join_two(subs, (0, 2), (0, 0), "connect")
check("modello: stessa linea, collega: chiusa, nodi fermi", subs[0].closed and len(subs[0].nodes) == 3
      and [n.pt() for n in subs[0].nodes] == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)])
subs = N.from_path(line((0, 0), (10, 0)).path())
check("modello: linea di due nodi non si chiude (non resterebbe una forma)",
      N.join_two(subs, (0, 0), (0, 1), "merge") is not None and not subs[0].closed and len(subs[0].nodes) == 2)
subs = N.from_path(line((0, 0), (10, 0), (20, 0)).path()) + N.from_path(line((30, 0), (40, 0)).path())
check("modello: un nodo in mezzo non si unisce", N.join_two(subs, (0, 1), (1, 0)) is not None and len(subs) == 2)
subs = N.from_path(line((0, 0), (10, 0), (10, 10), closed=True).path()) + N.from_path(line((30, 0), (40, 0)).path())
check("modello: un nodo di una forma chiusa non si unisce", N.join_two(subs, (0, 0), (1, 0)) is not None and len(subs) == 2)
check("modello: lo stesso nodo due volte: no", N.join_two(subs, (1, 0), (1, 0)) is not None)

# ---------------------------------------------------------------- nella finestra
w = MainWindow()
w.resize(1500, 950)
w.show()
spin(0.8)
cv, ed = w.canvas, w.editor
cv.snap_objects = False
cv.snap_grid = False if hasattr(cv, "snap_grid") else None
vp = cv.viewport()


def V(x, y):
    p = cv.to_view(QPointF(x, y))
    return QPoint(int(round(p.x())), int(round(p.y())))


def _send(t, p, btn, btns, mods):
    QApplication.sendEvent(vp, QMouseEvent(t, QPointF(p), QPointF(vp.mapToGlobal(p)), btn, btns, mods))


def click(p, mods=Qt.NoModifier):
    _send(QEvent.MouseButtonPress, p, Qt.LeftButton, Qt.LeftButton, mods)
    spin(0.01)
    _send(QEvent.MouseButtonRelease, p, Qt.LeftButton, Qt.NoButton, mods)
    spin(0.02)


def drag(a, b, mods=Qt.NoModifier, steps=8):
    _send(QEvent.MouseButtonPress, a, Qt.LeftButton, Qt.LeftButton, mods)
    spin(0.01)
    for i in range(1, steps + 1):
        _send(QEvent.MouseMove, a + (b - a) * (i / steps), Qt.NoButton, Qt.LeftButton, mods)
        spin(0.01)
    _send(QEvent.MouseButtonRelease, b, Qt.LeftButton, Qt.NoButton, mods)
    spin(0.02)


def key(k, mods=Qt.NoModifier):
    QTest.keyClick(vp, k, mods)
    spin(0.03)


def fresh(*shapes):
    ed.select([s for s in ed.doc.shapes])
    ed.delete() if ed.doc.shapes else None
    ed.add(list(shapes), "prova")
    ed.select(list(shapes))
    cv.set_tool("nodes")
    spin(0.05)
    return cv.tool


# due linee aperte su livelli diversi
A = line((40, 40), (80, 40), layer=1)
B = line((100, 60), (140, 60), layer=2)
nt = fresh(A, B)
check("strumento Nodi: i nodi di tutte e due le forme", nt.name == "nodes" and len(nt.items) == 2
      and sum(len(sp.nodes) for it in nt.items for sp in it.subs) == 4)
check("compatibilità: target e subs sono quelli della prima forma", nt.target is A and len(nt.subs) == 1)
click(V(80, 40))
check("clic su un nodo: uno solo selezionato", nt.sel == [(0, 0, 1)], nt.sel)
click(V(100, 60), Qt.ControlModifier)
check("Ctrl+clic su un nodo dell'altra forma: due selezionati, l'ultimo è il principale",
      nt.sel == [(0, 0, 1), (1, 0, 0)] and nt.cur == 1 and nt.target is B, (nt.sel, nt.cur))
click(V(100, 60), Qt.ControlModifier)
check("Ctrl+clic di nuovo: lo toglie", nt.sel == [(0, 0, 1)], nt.sel)
click(V(100, 60), Qt.ShiftModifier)
check("Maiusc+clic: lo aggiunge", len(nt.sel) == 2)
key(Qt.Key_Escape)
check("Esc: toglie la selezione dei nodi e resta nello strumento Nodi", nt.sel == [] and cv.tool is nt)
key(Qt.Key_A, Qt.ControlModifier)
check("Ctrl+A: tutti i nodi (e non «seleziona tutto» delle forme)", len(nt.sel) == 4 and len(ed.selection) == 2)
click(V(200, 200))
check("clic sul vuoto: deseleziona", nt.sel == [])
drag(V(30, 30), V(90, 50))
check("rettangolo sul vuoto: i due nodi della prima linea", sorted(nt.sel) == [(0, 0, 0), (0, 0, 1)], nt.sel)
drag(V(95, 55), V(105, 65), Qt.ControlModifier)
check("Ctrl+rettangolo: aggiunge", len(nt.sel) == 3, nt.sel)
# spostamento di tutti i selezionati
n_undo = len(ed.undo_stack)
drag(V(80, 40), V(90, 30))
pa, pb = pts_of(ed.doc.shapes[0])[0], pts_of(ed.doc.shapes[1])[0]
check("trascinando un nodo selezionato si muovono tutti i selezionati, dello stesso spostamento",
      close(pa[0], (50, 30), 0.6) and close(pa[1], (90, 30), 0.6) and close(pb[0], (110, 50), 0.6) and close(pb[1], (140, 60), 0.01),
      (pa, pb))
check("…un solo passo di Annulla", len(ed.undo_stack) == n_undo + 1)
ed.undo()
spin(0.05)
check("Annulla: tornano tutti dove erano", pts_of(ed.doc.shapes[0])[0] == [(40.0, 40.0), (80.0, 40.0)]
      and pts_of(ed.doc.shapes[1])[0] == [(100.0, 60.0), (140.0, 60.0)])

# unione di due forme con J
A, B = ed.doc.shapes[0], ed.doc.shapes[1]
nt = fresh(line((40, 40), (80, 40), layer=1), line((100, 60), (140, 60), layer=2))
A, B = ed.doc.shapes
click(V(80, 40))
click(V(100, 60), Qt.ControlModifier)
n_undo = len(ed.undo_stack)
key(Qt.Key_J)
check("J su due estremi di due forme: resta una forma sola", len(ed.doc.shapes) == 1, len(ed.doc.shapes))
s = ed.doc.shapes[0]
pp = pts_of(s)
check("…sul livello del primo nodo selezionato", s.layer == 1, s.layer)
check("…3 nodi, quello in comune a metà strada", len(pp) == 1 and len(pp[0]) == 3 and close(pp[0][1], (90, 50)), pp)
check("…un solo passo di Annulla, chiamato «Unisci nodi», e la forma resta selezionata", len(ed.undo_stack) == n_undo + 1
      and ed.selection == [s] and ed.undo_stack[-1][0] == "Unisci nodi", ed.undo_stack[-1][0])
ed.undo()
spin(0.05)
check("Annulla: tornano le due forme com'erano, sui loro livelli", len(ed.doc.shapes) == 2
      and [x.layer for x in ed.doc.shapes] == [1, 2] and pts_of(ed.doc.shapes[1])[0] == [(100.0, 60.0), (140.0, 60.0)])
ed.redo()
spin(0.05)
check("Ripeti: di nuovo una forma sola", len(ed.doc.shapes) == 1)
# il primo selezionato decide il livello
nt = fresh(line((40, 40), (80, 40), layer=1), line((100, 60), (140, 60), layer=2))
click(V(100, 60))
click(V(80, 40), Qt.ControlModifier)
key(Qt.Key_J)
check("selezionando prima il nodo della forma sul livello 2: la forma unita è sul livello 2",
      len(ed.doc.shapes) == 1 and ed.doc.shapes[0].layer == 2, [x.layer for x in ed.doc.shapes])
# Maiusc+J: collega
nt = fresh(line((40, 40), (80, 40), layer=1), line((100, 60), (140, 60), layer=1))
click(V(80, 40))
click(V(100, 60), Qt.ControlModifier)
key(Qt.Key_J, Qt.ShiftModifier)
pp = pts_of(ed.doc.shapes[0])
check("Maiusc+J: collega con un tratto dritto, i nodi restano dove sono (4 nodi)",
      len(ed.doc.shapes) == 1 and len(pp[0]) == 4 and (80.0, 40.0) in pp[0] and (100.0, 60.0) in pp[0], pp)
# stessa linea: la chiude
nt = fresh(line((40, 40), (80, 40), (80, 80), layer=1))
click(V(40, 40))
click(V(80, 80), Qt.ControlModifier)
key(Qt.Key_J, Qt.ShiftModifier)
s = ed.doc.shapes[0]
check("Maiusc+J sui due estremi della stessa linea: la chiude", s.closed() and len(pts_of(s)[0]) == 3)
nt = fresh(line((40, 40), (80, 40), (80, 80), (40, 80), layer=1))
click(V(40, 40))
click(V(40, 80), Qt.ControlModifier)
key(Qt.Key_J)
s = ed.doc.shapes[0]
pp = pts_of(s)[0]
check("J sui due estremi della stessa linea: chiusa, un nodo in meno, il punto a metà", s.closed() and len(pp) == 3
      and any(close(q, (40, 60)) for q in pp), pp)
# casi che non si uniscono
nt = fresh(line((40, 40), (60, 40), (80, 40), layer=1), line((100, 60), (140, 60), layer=1))
click(V(60, 40))
click(V(100, 60), Qt.ControlModifier)
n_undo, n_sh = len(ed.undo_stack), len(ed.doc.shapes)
msgs = []
cv.status.connect(msgs.append)
key(Qt.Key_J)
check("J con un nodo in mezzo: non fa niente e lo dice", len(ed.doc.shapes) == n_sh and len(ed.undo_stack) == n_undo
      and msgs, msgs)
msgs.clear()
click(V(60, 40))
key(Qt.Key_J)
check("J con un nodo solo: non fa niente e lo dice", len(ed.undo_stack) == n_undo and msgs, msgs)
r = RectShape(30, 20, layer=1)
r.apply(QTransform.fromTranslate(40, 40))
nt = fresh(r, line((100, 60), (140, 60), layer=1))
click(V(40, 40))
click(V(100, 60), Qt.ControlModifier)
n_undo = len(ed.undo_stack)
key(Qt.Key_J)
check("J con un nodo di un rettangolo (chiuso): niente, il rettangolo resta rettangolo",
      len(ed.undo_stack) == n_undo and isinstance(ed.doc.shapes[0], RectShape))
# forme trasformate: le coordinate sul piano restano
rot = line((0, 0), (40, 0), layer=1)
rot.apply(QTransform().translate(60, 100).rotate(30).scale(1.5, 1.5))
end = pts_of(rot)[0][1]
nt = fresh(rot, line((150, 150), (170, 150), layer=1))
click(V(*end))
click(V(150, 150), Qt.ControlModifier)
key(Qt.Key_J, Qt.ShiftModifier)
pp = pts_of(ed.doc.shapes[0])[0]
check("forma ruotata e scalata: collegata senza spostarsi sul piano", len(ed.doc.shapes) == 1 and len(pp) == 4
      and any(close(q, end, 0.01) for q in pp) and any(close(q, (60, 100), 0.01) for q in pp), (pp, end))
# elimina, angolo/morbido su più nodi
nt = fresh(line((40, 40), (60, 40), (80, 40), (100, 40), (120, 40), layer=1))
click(V(60, 40))
click(V(80, 40), Qt.ControlModifier)
click(V(100, 40), Qt.ControlModifier)
n_undo = len(ed.undo_stack)
cv.tool.hover = None
key(Qt.Key_D)
pp = pts_of(ed.doc.shapes[0])[0]
check("D con tre nodi selezionati: li toglie tutti e tre, un solo Annulla", pp == [(40.0, 40.0), (120.0, 40.0)]
      and len(ed.undo_stack) == n_undo + 1, pp)
ed.undo()
spin(0.05)
nt = cv.tool
nt._load()
nt.select_all_nodes()
nt.hover = None
n_undo = len(ed.undo_stack)
key(Qt.Key_S)
sp0 = N.from_path(ed.doc.shapes[0].path())[0]
check("S su tutti i nodi: i nodi in mezzo diventano morbidi (con le maniglie), un solo passo di Annulla",
      len(ed.undo_stack) == n_undo + 1 and all(n.cin and n.cout for n in sp0.nodes[1:-1]), len(ed.undo_stack) - n_undo)
# una forma, un nodo: come prima
r2 = RectShape(30, 20, layer=1)
r2.apply(QTransform.fromTranslate(60, 60))
nt = fresh(r2)
check("una forma sola: un solo elemento, target è la forma", len(nt.items) == 1 and nt.target is r2)
x0, y0 = nt.subs[0].nodes[0].pt()
drag(V(x0, y0), V(x0 - 10, y0 - 10))
s = ed.doc.shapes[0]
check("un nodo solo trascinato: la forma diventa tracciato e il nodo si sposta (come prima)",
      isinstance(s, PathShape) and any(close(q, (x0 - 10, y0 - 10), 0.6) for q in pts_of(s)[0]))
check("…e solo lui si sposta", sum(1 for q in pts_of(s)[0] if close(q, (x0 - 10, y0 - 10), 0.6)) == 1)
ed.undo()
spin(0.05)
check("Annulla: torna il rettangolo", isinstance(ed.doc.shapes[0], RectShape))
pc = QPainterPath()
pc.moveTo(40, 120)
pc.cubicTo(60, 150, 90, 150, 110, 120)
cur = PathShape(pc, layer=1)
nt = fresh(cur)
nt.sel = [(0, 0, 0)]
tf = cv.bed_to_view_tf()
h_one = nt._hit(tf.map(QPointF(60, 150)), tf)
nt.sel = [(0, 0, 1), (0, 0, 0)]  # il nodo della maniglia è il principale: con due selezionati niente maniglie lo stesso
h_two = nt._hit(tf.map(QPointF(60, 150)), tf)
check("maniglia: si prende con un nodo selezionato, non con due", h_one is not None and h_one[0] == "out" and h_two is None,
      (h_one, h_two))
# il trascinamento di un estremo su un altro della stessa forma unisce ancora (comportamento di prima)
nt = fresh(line((40, 40), (80, 40), (80, 80), layer=1))
drag(V(80, 80), V(40, 40))
check("trascinare un estremo sull'altro chiude la linea (come prima)", ed.doc.shapes[0].closed())
# gruppi e immagini esclusi, Esc due volte torna a Selezione
g = GroupShape([line((10, 10), (20, 10))])
nt = fresh(g, line((100, 60), (140, 60), layer=1))
check("un gruppo selezionato non entra nello strumento Nodi", len(nt.items) == 1)
nt.sel = [(0, 0, 0)]
key(Qt.Key_Escape)
key(Qt.Key_Escape)
check("Esc due volte: torna allo strumento Selezione", cv.tool.name == "select")
# menu del tasto destro
cv.set_tool("nodes")
spin()
keys = w.context_menu_keys()
check("menu del tasto destro dello strumento Nodi: Unisci nodi e Collega nodi", "node_join" in keys and "node_connect" in keys,
      keys)
nt = fresh(line((40, 40), (80, 40), layer=1), line((100, 60), (140, 60), layer=1))
nt.sel = [(0, 0, 1), (1, 0, 0)]
w.acts["node_connect"].trigger()
spin()
check("…e la voce Collega nodi funziona", len(ed.doc.shapes) == 1 and len(pts_of(ed.doc.shapes[0])[0]) == 4)
check("Unisci estremi (Alt+J) resta com'era", w.acts["join"].shortcut().toString() == "Alt+J")
check("J non è una scorciatoia di un altro comando", not any(a.shortcut().toString() in ("J", "Shift+J")
                                                             for a in w.acts.values()))

# ---------------------------------------------------------------- 0.20.6 (rapporto FLC-20261117-1900-E1C9)
# un estremo lasciato sopra l'estremo di un'altra linea le unisce; tolto un tratto in mezzo con D restano due linee


def edit(first, *others):
    """Forme sul piano, solo la prima selezionata e in modifica a nodi."""
    cv.set_tool("select")
    for x in ed.doc.shapes:  # anche quelle nascoste o bloccate della prova prima
        x.hidden = x.locked = False
    ed.select([x for x in ed.doc.shapes])
    ed.delete() if ed.doc.shapes else None
    ed.add([first] + list(others), "prova")
    ed.select([first])
    cv.set_tool("nodes")
    spin(0.05)
    return cv.tool


def hover(x, y):
    _send(QEvent.MouseMove, V(x, y), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    spin(0.02)


nt = fresh(line((40, 40), (80, 40), layer=1), line((100, 60), (140, 60), layer=1))
n_undo = len(ed.undo_stack)
drag(V(80, 40), V(100, 60))
pp = pts_of(ed.doc.shapes[0])
check("0.20.6: estremo trascinato sull'estremo di un'altra linea in modifica: una linea sola di 3 nodi",
      len(ed.doc.shapes) == 1 and len(pp) == 1 and len(pp[0]) == 3 and close(pp[0][1], (100, 60), 0.01)
      and {pp[0][0], pp[0][2]} == {(40.0, 40.0), (140.0, 60.0)}, pp)
check("…con un solo Annulla, che rimette le due linee dov'erano", len(ed.undo_stack) == n_undo + 1)
ed.undo()
spin()
check("…Annulla: di nuovo due linee, la prima con l'estremo a 80,40", len(ed.doc.shapes) == 2
      and pts_of(ed.doc.shapes[0])[0][1] == (80.0, 40.0), [pts_of(x) for x in ed.doc.shapes])
a_, b_ = line((40, 40), (80, 40), layer=1), line((100, 60), (140, 60), layer=2)
nt = edit(a_, b_)
drag(V(80, 40), cv_pt := V(100, 60) + QPoint(3, 2))  # lasciato a 3 pixel dall'estremo, non proprio sopra
pp = pts_of(ed.doc.shapes[0])
check("0.20.6: anche se l'altra linea non è selezionata, e il nodo va esattamente sull'estremo",
      len(ed.doc.shapes) == 1 and len(pp[0]) == 3 and any(close(q, (100, 60), 1e-6) for q in pp[0]), pp)
check("…la linea unita resta sul livello di quella che si stava modificando, selezionata e ancora in modifica",
      ed.doc.shapes[0].layer == 1 and ed.selection == [ed.doc.shapes[0]] and len(cv.tool.items) == 1
      and cv.tool.items[0].shape is ed.doc.shapes[0])
nt = edit(line((40, 40), (80, 40), layer=1), line((100, 60), (120, 60), (140, 60), layer=1))
drag(V(80, 40), V(120, 60))
check("0.20.6: lasciato su un nodo in mezzo all'altra linea (non un estremo): restano due linee",
      len(ed.doc.shapes) == 2 and len(pts_of(ed.doc.shapes[0])[0]) == 2)
other = line((100, 60), (140, 60), layer=1)
other.locked = True
nt = edit(line((40, 40), (80, 40), layer=1), other)
drag(V(80, 40), V(100, 60))
check("0.20.6: l'altra linea è bloccata: non si unisce", len(ed.doc.shapes) == 2)
other = line((100, 60), (140, 60), layer=1)
other.hidden = True
nt = edit(line((40, 40), (80, 40), layer=1), other)
drag(V(80, 40), V(100, 60))
check("0.20.6: l'altra linea è nascosta: non si unisce", len(ed.doc.shapes) == 2)
nt = edit(line((40, 40), (80, 40), layer=1), RectShape(30, 20, layer=1))
ed.doc.shapes[1].set_transform(QTransform.fromTranslate(100, 60))
drag(V(80, 40), V(100, 60))
check("0.20.6: lasciato sull'angolo di una forma chiusa: non si unisce", len(ed.doc.shapes) == 2
      and isinstance(ed.doc.shapes[1], RectShape))
nt = edit(line((40, 40), (80, 40), (80, 80), (42, 60), layer=1))
drag(V(42, 60), V(40, 40))
sub = N.from_path(ed.doc.shapes[0].path())
check("0.20.6: chiudere una linea su sé stessa funziona come prima", len(ed.doc.shapes) == 1 and len(sub) == 1
      and sub[0].closed, [(x.closed, len(x.nodes)) for x in sub])
c_ = line((200, 40), (240, 40), layer=1)
nt = edit(line((40, 40), (80, 40), layer=1), line((100, 60), (140, 60), layer=1), c_)
drag(V(80, 40), V(100, 60))
check("0.20.6: le linee lontane non vengono toccate", len(ed.doc.shapes) == 2 and c_ in ed.doc.shapes
      and pts_of(c_) == [[(200.0, 40.0), (240.0, 40.0)]])

# D su un tratto in mezzo: due linee separate
nt = edit(line((40, 40), (60, 40), (80, 40), (100, 40), layer=3))
n_undo = len(ed.undo_stack)
hover(70, 40)
key(Qt.Key_D)
got = sorted(pts_of(x)[0] for x in ed.doc.shapes)
check("0.20.6: D su un tratto in mezzo a una linea: restano due linee separate (due forme)",
      len(ed.doc.shapes) == 2 and got == [[(40.0, 40.0), (60.0, 40.0)], [(80.0, 40.0), (100.0, 40.0)]], got)
check("…stesso livello, tutte e due selezionate e in modifica, un solo Annulla",
      all(x.layer == 3 for x in ed.doc.shapes) and set(ed.selection) == set(ed.doc.shapes)
      and len(cv.tool.items) == 2 and len(ed.undo_stack) == n_undo + 1)
cv.set_tool("select")
spin()
ed.select([])
click(V(50, 40))
check("…con Selezione un clic sul primo pezzo prende solo quello (prima si evidenziava tutta la linea)",
      len(ed.selection) == 1 and pts_of(ed.selection[0])[0] == [(40.0, 40.0), (60.0, 40.0)],
      [pts_of(x) for x in ed.selection])
ed.undo()
spin()
check("…Annulla: di nuovo una linea sola di 4 nodi", len(ed.doc.shapes) == 1 and len(pts_of(ed.doc.shapes[0])[0]) == 4)
nt = edit(line((40, 40), (60, 40), (80, 40), (100, 40), layer=1))
hover(50, 40)
key(Qt.Key_D)
check("0.20.6: D sul primo tratto: la linea si accorcia e resta una", len(ed.doc.shapes) == 1
      and pts_of(ed.doc.shapes[0]) == [[(60.0, 40.0), (80.0, 40.0), (100.0, 40.0)]], [pts_of(x) for x in ed.doc.shapes])
nt = edit(line((40, 40), (80, 40), (80, 80), (40, 80), layer=1, closed=True))
hover(60, 40)
key(Qt.Key_D)
sub = N.from_path(ed.doc.shapes[0].path())
check("0.20.6: D su un lato di una forma chiusa: la apre e resta una forma (come prima)", len(ed.doc.shapes) == 1
      and len(sub) == 1 and not sub[0].closed and len(sub[0].nodes) == 4, [(x.closed, len(x.nodes)) for x in sub])
# il caso del rapporto: due nodi inseriti su una linea, tolto il pezzo in mezzo
nt = edit(line((40, 40), (100, 40), layer=1))
hover(60, 40)
key(Qt.Key_I)
hover(80, 40)
key(Qt.Key_I)
hover(70, 40)
key(Qt.Key_D)
got = sorted((round(a[0]), round(b[0])) for a, b in (pts_of(x)[0] for x in ed.doc.shapes))
check("0.20.6: caso del rapporto (due nodi inseriti, D sul pezzo in mezzo): due linee, 40–60 e 80–100", got ==
      [(40, 60), (80, 100)], got)
cv.set_tool("select")
spin()

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
