# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.19.6: tracciati puliti.

- Semplifica tracciati (core/simplify.py, Modifica → «Semplifica tracciati…»): meno nodi entro la tolleranza, misurata
  qui da un controllo indipendente (distanza punto-spezzata nei due sensi, a forza bruta); aperto/chiuso, estremi,
  punto di partenza, numero e verso dei sottopercorsi invariati; mai più nodi; gruppi e trasformazioni; finestra con
  anteprima, OK = un Annulla, Annulla = documento identico.
- Mano libera (strumento, tasto H): tratto levigato, chiuso se finisce sulla partenza, clic e tratti corti = niente,
  Esc e tasto destro annullano, aggancio del primo punto, un Annulla, blocco dello strumento.
- Allinea e Distribuisci sui nodi scelti con lo strumento Nodi; senza nodi scelti sulle forme come prima.
Uso: python tests/test_v196_tracciati.py [banco]
"""
import math
import os
import random
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
import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPainterPath, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

import freelasercut
from freelasercut.core import geom
from freelasercut.core import nodes as N
from freelasercut.core import simplify as S
from freelasercut.core.document import GroupShape, ImageShape, PathShape, RectShape, shape_from_dict
from freelasercut.updater import parse_version
from freelasercut.ui import help_texts
from freelasercut.ui.main_window import MainWindow

UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


# ================================================================ controllo indipendente dello scarto
def _polys(path, step=0.01):
    """Ogni sottopercorso: (punti fitti, uno ogni `step` mm, per le domande; spezzata vera, curve appiattite a
    0,001 mm, per le distanze)."""
    out = []
    for p in geom.flatten(path, 0.001):
        pts = np.array(p.pts, dtype=float)
        if p.closed:
            pts = np.vstack([pts, pts[:1]])
        seg = []
        for a, b in zip(pts[:-1], pts[1:]):
            k = max(1, int(math.ceil(math.hypot(*(b - a)) / step)))
            seg.append(a + (b - a) * (np.arange(k)[:, None] / k))
        seg.append(pts[-1:])
        out.append((np.vstack(seg), pts))
    return out


def _d_to_poly(Q, P):
    """Distanza di ogni punto Q dalla spezzata P (esatta, punto-segmento)."""
    A, B = P[:-1], P[1:]
    AB = B - A
    L2 = (AB * AB).sum(1)
    L2[L2 < 1e-24] = 1.0
    best = np.empty(len(Q))
    rows = max(1, 2_000_000 // max(1, len(A)))
    for i in range(0, len(Q), rows):
        q = Q[i:i + rows]
        t = np.clip(((q[:, None, :] - A) * AB).sum(2) / L2, 0, 1)
        dx = q[:, None, 0] - (A[:, 0] + t * AB[:, 0])
        dy = q[:, None, 1] - (A[:, 1] + t * AB[:, 1])
        best[i:i + rows] = np.sqrt((dx * dx + dy * dy).min(1))
    return best


def deviation(p1, p2):
    """Scarto nei due sensi fra due QPainterPath con gli stessi sottopercorsi (Hausdorff a forza bruta, il controllo
    è scritto qui, indipendente da core/simplify)."""
    a, b = _polys(p1), _polys(p2)
    if len(a) != len(b):
        return float("inf")
    return max(max(_d_to_poly(x[0], y[1]).max(), _d_to_poly(y[0], x[1]).max()) for x, y in zip(a, b))


def poly_path(pts, closed=True):
    p = QPainterPath()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if closed:
        p.closeSubpath()
    return p


def circle_pts(cx, cy, r, n, start=0.0):
    return [(cx + r * math.cos(start + a), cy + r * math.sin(start + a)) for a in np.linspace(0, 2 * math.pi, n + 1)[:-1]]


def densify(corners, per_side):
    out = []
    for a, b in zip(corners, corners[1:] + corners[:1]):
        for t in np.linspace(0, 1, per_side + 1)[:-1]:
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def subs_of(path):
    return N.from_path(path)


def n_nodes(path):
    return sum(len(sp.nodes) for sp in subs_of(path))


def signed_area(sp):
    """Area con segno del sottopercorso (curve comprese): il segno dice il verso."""
    pts = geom.flatten(N.to_path([sp]), 0.01)[0].pts
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


SLACK = 0.006  # errore di campionamento ammesso dal progetto (≤ 0,005 mm) più l'arrotondamento del controllo

check("versione 0.19.6 o successiva", parse_version(freelasercut.__version__) >= (0, 19, 6), freelasercut.__version__)

# ================================================================ limiti
check("tolleranza: sotto il minimo diventa 0,01 mm, sopra il massimo 5 mm",
      S.clamp_tol(0) == S.TOL_MIN == 0.01 and S.clamp_tol(-3) == 0.01 and S.clamp_tol(99) == S.TOL_MAX == 5.0)
check("tolleranza: valori non numerici o infiniti -> predefinita 0,1 mm",
      S.clamp_tol("x") == S.clamp_tol(float("nan")) == S.clamp_tol(float("inf")) == S.TOL_DEFAULT == 0.1)
check("angolo: limiti 5–175°, predefinito 40°", S.clamp_angle(0) == 5.0 and S.clamp_angle(400) == 175.0
      and S.clamp_angle(None) == S.ANGLE_DEFAULT == 40.0)

# ================================================================ geometrie
circ = poly_path(circle_pts(50, 50, 20, 720))
for tol in (0.01, 0.1, 1.0, 5.0):
    new, st = S.simplify_path(circ, tol)
    dev = deviation(circ, new)
    sp = subs_of(new)
    check(f"cerchio da 720 lati, tolleranza {tol:g}: molti meno nodi, scarto misurato ≤ tolleranza, resta chiuso",
          n_nodes(new) <= 16 and dev <= tol + SLACK and len(sp) == 1 and sp[0].closed,
          f"nodi {n_nodes(new)}, scarto {dev:.4f}")
    check(f"…tolleranza {tol:g}: lo scarto dichiarato è un limite vero (≥ misurato − 0,006) e ≤ tolleranza",
          st.max_err <= tol + 1e-9 and st.max_err >= dev - SLACK, f"{st.max_err:.4f} / {dev:.4f}")
new, st = S.simplify_path(circ, 0.1, lines_only=True)
sp = subs_of(new)[0]
check("solo tratti dritti: nessuna maniglia, scarto ≤ tolleranza, meno nodi",
      not any(sp.is_curve(i, j) for i, j in sp.segments()) and deviation(circ, new) <= 0.1 + SLACK
      and len(sp.nodes) < 720, len(sp.nodes))
check("solo tratti dritti: meno tratti di G-code dell'originale", S.gcode_segments(new) < S.gcode_segments(circ),
      (S.gcode_segments(new), S.gcode_segments(circ)))
rnd = random.Random(7)
noisy = poly_path([(x + rnd.uniform(-.05, .05), y + rnd.uniform(-.05, .05)) for x, y in circle_pts(0, 0, 15, 600)])
new, _ = S.simplify_path(noisy, 0.1)
check("cerchio con il tremolio di una vettorizzazione (±0,05 mm): scarto ≤ 0,1 mm e nodi ridotti",
      deviation(noisy, new) <= 0.1 + SLACK and n_nodes(new) < 60, n_nodes(new))
sq = poly_path(densify([(0, 0), (40, 0), (40, 40), (0, 40)], 100))
new, _ = S.simplify_path(sq, 0.1)
pp = [n.pt() for n in subs_of(new)[0].nodes]
check("quadrato fatto di 400 punti: restano i 4 spigoli esatti, dritti",
      len(pp) == 4 and all(min(math.dist(p, c) for p in pp) < 1e-9 for c in ((0, 0), (40, 0), (40, 40), (0, 40)))
      and not any(subs_of(new)[0].is_curve(i, j) for i, j in subs_of(new)[0].segments()), pp)
r4 = N.from_path(poly_path([(0, 0), (10, 0), (10, 5), (0, 5)]))[0]
check("rettangolo di 4 nodi: non migliora, resta identico (nessuna sostituzione)", S.simplify_subpath(r4, 0.1)[0] is None)
el = QPainterPath()
el.addEllipse(0, 0, 30, 20)
new, st = S.simplify_path(el, 0.1)
check("ellisse già fatta di curve: mai più nodi di prima e scarto ≤ tolleranza",
      n_nodes(new) <= n_nodes(el) and deviation(el, new) <= 0.1 + SLACK, (n_nodes(el), n_nodes(new)))
sine = [(x, 10 * math.sin(x / 10)) for x in np.linspace(0, 100, 1001)]
sp_in = N.from_path(poly_path(sine, False))[0]
new_sp, e = S.simplify_subpath(sp_in, 0.1)
check("linea aperta (sinusoide da 1001 punti): resta aperta, estremi esattamente fermi, verso uguale",
      new_sp is not None and not new_sp.closed and new_sp.nodes[0].pt() == sine[0] and new_sp.nodes[-1].pt() == sine[-1]
      and len(new_sp.nodes) < 20, None if new_sp is None else (new_sp.nodes[0].pt(), new_sp.nodes[-1].pt()))
check("…scarto ≤ tolleranza", deviation(poly_path(sine, False), N.to_path([new_sp])) <= 0.1 + SLACK)
c_off = circle_pts(0, 0, 10, 360, start=0.7)
new_sp, _ = S.simplify_subpath(N.from_path(poly_path(c_off))[0], 0.1)
check("chiuso: il punto di partenza resta lo stesso (il laser parte dove partiva)",
      new_sp is not None and new_sp.nodes[0].pt() == c_off[0], None if new_sp is None else new_sp.nodes[0].pt())
holes = QPainterPath()
holes.addPath(poly_path(circle_pts(0, 0, 30, 500)))
holes.addPath(poly_path(circle_pts(-10, 0, 5, 300)[::-1]))
holes.addPath(poly_path(densify([(5, -5), (15, -5), (15, 5), (5, 5)], 50)))
new, st = S.simplify_path(holes, 0.1)
a0, a1 = subs_of(holes), subs_of(new)
check("forma con due fori: stessi 3 sottopercorsi, tutti chiusi, nello stesso ordine e verso",
      len(a1) == 3 and all(s.closed for s in a1)
      and all(math.copysign(1, signed_area(x)) == math.copysign(1, signed_area(y)) for x, y in zip(a0, a1))
      and all(x.nodes[0].pt() == y.nodes[0].pt() for x, y in zip(a0, a1)), [len(s.nodes) for s in a1])
check("…scarto ≤ tolleranza su tutti e tre", deviation(holes, new) <= 0.1 + SLACK)
one = N.SubPath([N.Node(5, 5)])
zero = N.SubPath([N.Node(5, 5), N.Node(5, 5), N.Node(5, 5)])
two = N.SubPath([N.Node(0, 0), N.Node(10, 0)])
check("sottopercorsi degeneri (un punto, lunghezza zero, due nodi) restano com'erano",
      all(S.simplify_subpath(x, 0.1)[0] is None for x in (one, zero, two)))
hexa = poly_path(densify(circle_pts(0, 0, 20, 6), 60))
new40, _ = S.simplify_path(hexa, 0.1, 40)
new175, _ = S.simplify_path(hexa, 0.1, 175)
s40, s175 = subs_of(new40)[0], subs_of(new175)[0]
check("esagono (curve di 60°) con spigoli sopra 40°: 6 angoli vivi, lati dritti",
      len(s40.nodes) == 6 and not any(s40.is_curve(i, j) for i, j in s40.segments()), len(s40.nodes))
check("…con spigoli sopra 175°: gli spigoli non sono più cercati, ma lo scarto resta ≤ tolleranza e i nodi pochi",
      deviation(hexa, new175) <= 0.1 + SLACK and len(s175.nodes) < 40, len(s175.nodes))
# prove a caso: tratti morbidi e spezzati, aperti e chiusi, tolleranze diverse
bad = []
rnd = random.Random(2026)
for k in range(30):
    closed = k % 2 == 0
    n = rnd.randint(40, 400)
    tol = rnd.choice((0.02, 0.05, 0.1, 0.3, 1.0))
    x = y = ang = 0.0
    pts = []
    for i in range(n):
        ang += rnd.gauss(0, 0.25) if rnd.random() > 0.05 else rnd.uniform(-2, 2)
        step = rnd.uniform(0.1, 1.5)
        x += step * math.cos(ang)
        y += step * math.sin(ang)
        pts.append((x, y))
    path = poly_path(pts, closed)
    sp0 = N.from_path(path)
    new, st = S.simplify_path(path, tol, rnd.choice((20, 40, 90)), lines_only=(k % 5 == 0))
    sp1 = N.from_path(new)
    dev = deviation(path, new)
    ok = (dev <= tol + SLACK and len(sp1) == len(sp0) and all(a.closed == b.closed for a, b in zip(sp0, sp1))
          and all(len(b.nodes) <= len(a.nodes) for a, b in zip(sp0, sp1))
          and all(a.nodes[0].pt() == b.nodes[0].pt() for a, b in zip(sp0, sp1))
          and all(a.closed or a.nodes[-1].pt() == b.nodes[-1].pt() for a, b in zip(sp0, sp1)))
    if not ok:
        bad.append((k, tol, round(dev, 4)))
check("30 tratti a caso (aperti, chiusi, con spigoli, tolleranze 0,02–1 mm): tutte le invarianti", not bad, bad)
big = QPainterPath()
for k in range(200):
    big.addPath(poly_path(circle_pts(k * 3, 0, 5, 360)))
t0 = time.time()
new, st = S.simplify_path(big, 0.1)
dt = time.time() - t0
check("200 cerchi da 360 lati (72000 nodi): finito in meno di 15 s, nodi ÷ 50", dt < 15 and st.nodes_after * 50 <= 72000,
      f"{dt:.1f} s, {st.nodes_after} nodi")

# ================================================================ forme, gruppi, trasformazioni
p_rot = PathShape(poly_path(circle_pts(0, 0, 10, 400)), layer=3)
p_rot.set_transform(QTransform().rotate(30).scale(2.0, -1.5))  # ruotato, stirato, specchiato
before_world = p_rot.path()
items, skipped = S.targets([p_rot])
changes, st = S.plan(items, 0.1)
check("tracciato ruotato, stirato e specchiato: si semplifica", len(changes) == 1 and st.shapes == 1)
tf_before, id_before = QTransform(p_rot.tf), p_rot.id
for leaf, path in changes:
    leaf.set_path(path)
check("…scarto misurato sul piano (dopo la trasformazione) ≤ tolleranza", deviation(before_world, p_rot.path()) <= 0.1 + SLACK,
      deviation(before_world, p_rot.path()))
check("…la forma tiene trasformazione, id e livello", p_rot.tf == tf_before and p_rot.id == id_before and p_rot.layer == 3)
leaf_in = PathShape(poly_path(circle_pts(0, 0, 8, 300)), layer=1)
inner = GroupShape([leaf_in, RectShape(5, 5)])
inner.set_transform(QTransform().translate(20, 0).scale(1.5, 1.5))
outer = GroupShape([inner, PathShape(poly_path([(0, 0), (5, 0), (5, 5)], False))])
outer.set_transform(QTransform().rotate(-15))
items, skipped = S.targets([outer])
check("gruppo nel gruppo: i tracciati dentro si trovano, il rettangolo è contato fra i saltati",
      len(items) == 2 and skipped == 1 and items[0][0] is leaf_in, (len(items), skipped))
w_leaf = items[0][1].map(leaf_in.local_path())
changes, st = S.plan(items, 0.1)
check("…solo il tracciato che migliora cambia (la spezzata di 3 nodi no)", len(changes) == 1 and changes[0][0] is leaf_in)
locked = PathShape(poly_path(circle_pts(0, 0, 8, 300)))
locked.locked = True
mark = PathShape(poly_path(circle_pts(0, 0, 8, 300)))
mark.role = "pc1"
img = ImageShape()
items, skipped = S.targets([locked, mark, img])
check("bloccati, crocette di Stampa e taglia e immagini: non si toccano (e le immagini non contano)",
      items == [] and skipped == 0)

# ================================================================ nella finestra
w = MainWindow()
w.resize(1500, 950)
w.show()
spin(0.8)
cv, ed = w.canvas, w.editor
cv.snap_objects = False
cv.snap_grid = False
vp = cv.viewport()


def V(x, y):
    p = cv.to_view(QPointF(x, y))
    return QPoint(int(round(p.x())), int(round(p.y())))


def _send(t, p, btn, btns, mods):
    QApplication.sendEvent(vp, QMouseEvent(t, QPointF(p), QPointF(vp.mapToGlobal(p)), btn, btns, mods))


def stroke(bed_pts, mods=Qt.NoModifier, end=True):
    _send(QEvent.MouseButtonPress, V(*bed_pts[0]), Qt.LeftButton, Qt.LeftButton, mods)
    for q in bed_pts[1:]:
        _send(QEvent.MouseMove, V(*q), Qt.NoButton, Qt.LeftButton, mods)
    if end:
        _send(QEvent.MouseButtonRelease, V(*bed_pts[-1]), Qt.LeftButton, Qt.NoButton, mods)
    spin(0.03)


def key(k, mods=Qt.NoModifier):
    QTest.keyClick(vp, k, mods)
    spin(0.03)


def fresh(*shapes, tool="select"):
    if ed.doc.shapes:
        ed.select(list(ed.doc.shapes))
        ed.delete()
    if shapes:
        ed.add(list(shapes), "prova")
        ed.select(list(shapes))
    cv.set_tool(tool)
    spin(0.05)
    return cv.tool


# ---------------------------------------------------------------- comando e finestra
check("comando nel menu Modifica, con la sua icona e Ctrl+Alt+S", "simplify" in w.acts
      and w.acts["simplify"].shortcut().toString() == "Ctrl+Alt+S" and not w.acts["simplify"].icon().isNull())
others = [k for k, a in w.acts.items() if k != "simplify" and a.shortcut().toString() == "Ctrl+Alt+S"]
check("Ctrl+Alt+S non è di un altro comando", not others, others)
check("scheda della guida per il comando e per lo strumento Mano libera",
      help_texts.lookup("simplify") is not None and help_texts.lookup("tool:freehand") is not None)
fresh()
from freelasercut.ui.dialogs_simplify import SimplifyDialog, make_simplify_dialog  # noqa: E402

msgs = []
ed.message.connect(msgs.append)
check("senza selezione: niente finestra, il motivo nella barra di stato", make_simplify_dialog(w) is None and msgs)
fresh(RectShape(10, 10))
check("solo un rettangolo: niente finestra (prima va convertito in tracciato)", make_simplify_dialog(w) is None)
P1 = PathShape(poly_path(circle_pts(60, 60, 20, 720)), layer=1)
P2 = PathShape(poly_path(densify([(100, 20), (140, 20), (140, 50), (100, 50)], 80)), layer=2)
fresh(P1, P2, RectShape(8, 8))
keys = w.context_menu_keys()
check("tasto destro su una selezione con tracciati: c'è Semplifica tracciati", "simplify" in keys, keys)
snap0 = ed.doc.snapshot()
n_undo = len(ed.undo_stack)
dlg = make_simplify_dialog(w)
check("finestra aperta: anteprima già sul piano (meno nodi) prima dell'OK",
      isinstance(dlg, SimplifyDialog) and n_nodes(ed.doc.shapes[0].path()) < 720, n_nodes(ed.doc.shapes[0].path()))
st = dlg.stats
check("numeri della finestra: nodi, tratti di G-code, scarto, quanti cambiati",
      st.nodes_before == 720 + 320 and st.nodes_after == n_nodes(ed.doc.shapes[0].path()) + n_nodes(ed.doc.shapes[1].path())
      and str(st.nodes_before) in dlg.info.text() and str(st.gcode_after) in dlg.info.text() and st.shapes == 2,
      dlg.info.text())
check("il rettangolo è segnalato come lasciato com'è", dlg.note.isVisibleTo(dlg) and dlg.skipped == 1)
dlg.tol.setValue(1.0)
dlg._live()
n_after_1 = n_nodes(ed.doc.shapes[0].path())
dlg.tol.setValue(0.01)
dlg._live()
n_after_001 = n_nodes(ed.doc.shapes[0].path())
check("cambiando la tolleranza l'anteprima si rifà dall'originale (0,01 mm: più nodi che con 1 mm)",
      n_after_001 > n_after_1 and deviation(P1.path() if False else poly_path(circle_pts(60, 60, 20, 720)),
                                             ed.doc.shapes[0].path()) <= 0.01 + SLACK, (n_after_1, n_after_001))
dlg.tol.setValue(99)
check("la tolleranza nella finestra non va oltre 5 mm", abs(dlg.values()[0] - 5.0) < 1e-9)
dlg.reject()
check("Annulla: documento identico a prima e nessun passo nella cronologia",
      ed.doc.snapshot() == snap0 and len(ed.undo_stack) == n_undo)
ed.select(list(ed.doc.shapes))
dlg = make_simplify_dialog(w)
dlg.tol.setValue(0.2)
dlg.angle.setValue(50)
dlg.lines.setChecked(True)
dlg.accept()
check("OK: un solo passo «Semplifica tracciati»", len(ed.undo_stack) == n_undo + 1 and "Semplifica" in ed.undo_label(),
      ed.undo_label())
after = ed.doc.snapshot()
c0 = subs_of(ed.doc.shapes[0].path())[0]
check("…con «Solo tratti dritti» scelto: niente curve", not any(c0.is_curve(i, j) for i, j in c0.segments()))
ed.undo()
check("Annulla: tutto com'era", ed.doc.snapshot()["shapes"] == snap0["shapes"])
ed.redo()
check("Ripeti: di nuovo semplificati", ed.doc.snapshot()["shapes"] == after["shapes"])
ed.select(list(ed.doc.shapes))
dlg = make_simplify_dialog(w)
check("i valori scelti si ricordano alla volta dopo", abs(dlg.tol.value() - 0.2) < 1e-9 and dlg.angle.value() == 50
      and dlg.lines.isChecked())
n_undo2 = len(ed.undo_stack)
dlg.accept()
check("OK senza niente da cambiare (già semplificati): nessun passo in più", len(ed.undo_stack) == n_undo2)
s0 = ed.doc.shapes[0]
again = shape_from_dict(s0.to_dict())
check("salva e riapri: il tracciato semplificato è identico", again.to_dict()["p"] == s0.to_dict()["p"])
G = GroupShape([PathShape(poly_path(circle_pts(0, 0, 10, 500)))])
G.set_transform(QTransform().translate(150, 100))
fresh(G)
b0 = G.bounds()
st = ed.simplify(0.1, 40)
check("anche senza finestra (Editor.simplify): dentro un gruppo, un passo, l'ingombro del gruppo aggiornato",
      st is not None and st.changed == 1 and n_nodes(ed.doc.shapes[0].path()) < 500
      and abs(G.bounds().width() - b0.width()) < 0.25 and "Semplifica" in ed.undo_label(), st)
fresh(RectShape(5, 5))
check("tasto destro su un rettangolo: niente Semplifica tracciati", "simplify" not in w.context_menu_keys())

# ---------------------------------------------------------------- Mano libera
check("strumento Mano libera con il tasto H, fra gli strumenti", "freehand" in w.tool_actions
      and w.tool_actions["freehand"].shortcut().toString() == "H"
      and not any(a.shortcut().toString() == "H" for k, a in w.acts.items()))
fh = fresh(tool="freehand")
check("H sceglie lo strumento", True if cv.tool.name == "freehand" else False)
fresh()
w.activateWindow()
cv.setFocus()
spin()
QTest.keyClick(cv, Qt.Key_H)
spin()
check("…anche dalla tastiera", cv.tool.name == "freehand", cv.tool.name)
fh = cv.tool
ed.current_layer = 4
wave = [(40 + x, 80 + 8 * math.sin(x / 6)) for x in np.linspace(0, 60, 120)]
n_undo = len(ed.undo_stack)
stroke(wave)
shp = ed.doc.shapes[-1] if ed.doc.shapes else None
sp = subs_of(shp.path())[0] if shp is not None else None
check("un tratto aperto: un tracciato aperto, levigato (molti meno nodi dei punti), sul livello corrente",
      shp is not None and isinstance(shp, PathShape) and not sp.closed and len(sp.nodes) < 30 and shp.layer == 4,
      None if sp is None else (len(sp.nodes), sp.closed))
check("…un solo passo «Disegno a mano libera», e si torna a Selezione", len(ed.undo_stack) == n_undo + 1
      and ed.undo_label() == "Disegno a mano libera" and cv.tool.name == "select", (ed.undo_label(), cv.tool.name))
tol_px = S.clamp_tol(cv.px(fh.SMOOTH_PX))
raw = poly_path([(cv.to_bed(QPointF(V(*q))).x(), cv.to_bed(QPointF(V(*q))).y()) for q in wave], False)
check("…segue il tratto: scarto ≤ la levigatura (2,5 pixel dello schermo)", deviation(raw, shp.path()) <= tol_px + 0.05,
      (deviation(raw, shp.path()), tol_px))
ed.undo()
check("Annulla toglie il tratto", shp not in ed.doc.shapes)
cv.set_tool("freehand")
ring = circle_pts(100, 100, 25, 90) + [circle_pts(100, 100, 25, 90)[0]]
stroke([(x + 0.3, y) if i == len(ring) - 1 else (x, y) for i, (x, y) in enumerate(ring)])
sp = subs_of(ed.doc.shapes[-1].path())[0]
check("finire sul punto di partenza: forma chiusa", sp.closed, sp.closed)
n_shapes = len(ed.doc.shapes)
cv.set_tool("freehand")
stroke([(60, 60), (60.01, 60)])
check("un clic: niente", len(ed.doc.shapes) == n_shapes)
cv.set_tool("freehand")
fh = cv.tool
short = [(60 + cv.px(1.2) * i, 60) for i in range(3)]  # tre pixel scarsi
stroke(short)
check("un tratto di 3 pixel (sotto i 4): niente", len(ed.doc.shapes) == n_shapes)
check("…lo stesso nel calcolo: 3 pixel no, 6 pixel sì", fh.build([(0, 0), (cv.px(3), 0)]) is None
      and fh.build([(0, 0), (cv.px(6), 0)]) is not None)
cv.set_tool("freehand")
stroke(wave, end=False)
key(Qt.Key_Escape)
_send(QEvent.MouseButtonRelease, V(*wave[-1]), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
spin()
check("Esc durante il tratto: annullato, niente di nuovo, lo strumento resta", len(ed.doc.shapes) == n_shapes
      and cv.tool.name == "freehand")
stroke(wave[:60], end=False)
_send(QEvent.MouseButtonPress, V(*wave[59]), Qt.RightButton, Qt.LeftButton | Qt.RightButton, Qt.NoModifier)
_send(QEvent.MouseButtonRelease, V(*wave[59]), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
spin()
check("tasto destro durante il tratto: annullato", len(ed.doc.shapes) == n_shapes)
key(Qt.Key_Escape)
check("Esc senza tratto: torna a Selezione", cv.tool.name == "select")
R = RectShape(20, 20)
R.set_transform(QTransform().translate(150, 150))
fresh(R, tool="freehand")
cv.snap_objects = True
corner = (150.0, 150.0)
# partenza a 5 pixel dallo spigolo (l'aggancio prende entro 9 px): in pixel, così la prova non dipende dallo zoom
dx, dy = cv.px(4), cv.px(3)
start = (corner[0] + dx, corner[1] + dy)
path_pts = [start] + [(start[0] + k, start[1] + 10 * math.sin(k / 5)) for k in range(1, 40)]
stroke(path_pts)
fs = ed.doc.shapes[-1]
first = subs_of(fs.path())[0].nodes[0].pt()
check("il primo punto si aggancia allo spigolo vicino (aggancio agli oggetti acceso)", math.dist(first, corner) < 0.05,
      first)
cv.set_tool("freehand")
stroke(path_pts, Qt.AltModifier)
first = subs_of(ed.doc.shapes[-1].path())[0].nodes[0].pt()
check("…con Alt no: resta dove è partito il mouse (a circa 5 pixel dallo spigolo)",
      math.dist(first, corner) > cv.px(3.5) and math.dist(first, start) < cv.px(1.5), (first, cv.px(1)))
cv.snap_objects = False
fresh()
w._pick_tool("freehand")
w._pick_tool("freehand")
check("doppio clic sull'icona: lo strumento resta bloccato…", cv.tool_lock == "freehand")
stroke(wave)
stroke([(x, y + 30) for x, y in wave])
check("…e disegna più tratti di fila", len(ed.doc.shapes) == 2 and cv.tool.name == "freehand", len(ed.doc.shapes))
key(Qt.Key_Escape)
key(Qt.Key_Escape)
check("Esc lo sblocca", cv.tool_lock is None)

# ---------------------------------------------------------------- Allinea e Distribuisci sui nodi
def line(*pts, layer=1, closed=False):
    return PathShape(poly_path(list(pts), closed), layer=layer)


def pts_of(s):
    return [[n.pt() for n in sp.nodes] for sp in N.from_path(s.path())]


A = line((40, 40), (60, 50), (80, 45))
B = line((100, 60), (130, 70))
nt = fresh(A, B, tool="nodes")
nt.sel = [(0, 0, 0), (0, 0, 2), (1, 0, 1)]
n_undo = len(ed.undo_stack)
w.acts["align_left"].trigger()
spin()
pa, pb = pts_of(ed.doc.shapes[0])[0], pts_of(ed.doc.shapes[1])[0]
check("Allinea a sinistra con tre nodi scelti di due forme: x di tutti = la più piccola, y ferme",
      pa[0] == (40, 40) and pa[2] == (40, 45) and pb[1] == (40, 70), (pa, pb))
check("…gli altri nodi non si muovono", pa[1] == (60, 50) and pb[0] == (100, 60))
check("…un solo passo «Allinea nodi»; la scelta dei nodi resta", len(ed.undo_stack) == n_undo + 1
      and ed.undo_label() == "Allinea nodi" and len(nt.sel) == 3, (ed.undo_label(), nt.sel))
ed.undo()
spin()
check("Annulla: nodi al loro posto", pts_of(ed.doc.shapes[0])[0] == [(40, 40), (60, 50), (80, 45)])
# nodi scelti (40, 40) e (60, 50): ingombro x 40–60, y 40–50
cases = {"right": lambda p: p == [(60, 40), (60, 50)], "top": lambda p: p == [(40, 50), (60, 50)],
         "bottom": lambda p: p == [(40, 40), (60, 40)], "hcenter": lambda p: p == [(50, 40), (50, 50)],
         "vcenter": lambda p: p == [(40, 45), (60, 45)], "center": lambda p: p == [(50, 45), (50, 45)]}
for kind, ok in cases.items():
    nt = fresh(line((40, 40), (60, 50), (80, 45)), tool="nodes")
    nt.sel = [(0, 0, 0), (0, 0, 1)]
    w.acts[{"right": "align_right", "top": "align_top", "bottom": "align_bottom", "hcenter": "align_hcenter",
            "vcenter": "align_vcenter", "center": "align_center"}[kind]].trigger()
    spin()
    p = pts_of(ed.doc.shapes[0])[0]
    if kind == "center":  # due nodi uno dopo l'altro nello stesso punto diventano uno (come trascinandoli)
        check("Allinea nodi «center»: i due nodi nello stesso punto (50, 45) diventano uno, il terzo fermo",
              p == [(50, 45), (80, 45)], p)
        continue
    check(f"Allinea nodi «{kind}» con una forma sola (Y in su: alto = y più grande), il terzo nodo fermo",
          ok(p[:2]) and p[2] == (80, 45), p)
nt = fresh(line((0, 10), (7, 20), (12, 30), (30, 40)), tool="nodes")
nt.sel = [(0, 0, 3), (0, 0, 1), (0, 0, 0), (0, 0, 2)]
w.acts["dist_h"].trigger()
spin()
p = pts_of(ed.doc.shapes[0])[0]
check("strumento Nodi con una forma: Allinea e Distribuisci attivi", w.acts["align_left"].isEnabled()
      and w.acts["dist_h"].isEnabled())
check("Distribuisci in orizzontale 4 nodi: x a passi uguali, primo e ultimo fermi, y ferme",
      p == [(0, 10), (10, 20), (20, 30), (30, 40)] and ed.undo_label() == "Distribuisci nodi", p)
nt = fresh(line((0, 0), (5, 3), (10, 30)), tool="nodes")
nt.sel = [(0, 0, 0), (0, 0, 1), (0, 0, 2)]
w.acts["dist_vc"].trigger()
spin()
check("Distribuisci centri in verticale (per i nodi è lo stesso): y a passi uguali",
      [q[1] for q in pts_of(ed.doc.shapes[0])[0]] == [0, 15, 30], pts_of(ed.doc.shapes[0])[0])
nt = fresh(line((0, 0), (5, 3), (10, 30)), tool="nodes")
nt.sel = [(0, 0, 1)]
n_undo = len(ed.undo_stack)
before = pts_of(ed.doc.shapes[0])
w.acts["align_left"].trigger()
spin()
check("un nodo solo: niente si muove, niente in cronologia (e lo dice)", pts_of(ed.doc.shapes[0]) == before
      and len(ed.undo_stack) == n_undo)
nt.sel = [(0, 0, 0), (0, 0, 1)]
w.acts["dist_h"].trigger()
spin()
check("distribuire due nodi: niente (ne servono tre)", pts_of(ed.doc.shapes[0]) == before and len(ed.undo_stack) == n_undo)
cp = QPainterPath()
cp.moveTo(0, 0)
cp.cubicTo(5, 10, 15, 10, 20, 0)
cp.lineTo(30, 5)
nt = fresh(PathShape(cp), tool="nodes")
nt.sel = [(0, 0, 1), (0, 0, 2)]
w.acts["align_top"].trigger()
spin()
sp = N.from_path(ed.doc.shapes[0].path())[0]
check("la maniglia segue il suo nodo (stesso spostamento: +5 in y)", sp.nodes[1].pt() == (20, 5) and sp.nodes[2].pt() == (30, 5)
      and sp.nodes[1].cin is not None and abs(sp.nodes[1].cin[0] - 15) < 1e-9 and abs(sp.nodes[1].cin[1] - 15) < 1e-9,
      (sp.nodes[1].pt(), sp.nodes[1].cin))
Rr = RectShape(20, 10)
Rr.set_transform(QTransform().translate(50, 50).rotate(30))
nt = fresh(Rr, tool="nodes")
wp = [n.pt() for n in nt.items[0].subs[0].nodes]
nt.sel = [(0, 0, 0), (0, 0, 1)]
w.acts["align_left"].trigger()
spin()
np_ = pts_of(ed.doc.shapes[0])[0]
xmin = min(wp[0][0], wp[1][0])
check("rettangolo ruotato: diventa tracciato e i nodi si allineano sul piano (coordinate vere)",
      isinstance(ed.doc.shapes[0], PathShape) and abs(np_[0][0] - xmin) < 1e-6 and abs(np_[1][0] - xmin) < 1e-6
      and abs(np_[0][1] - wp[0][1]) < 1e-6, (wp, np_))
nt = fresh(line((0, 0), (10, 0)), line((0, 20), (10, 25)), tool="nodes")
nt.sel = [(0, 0, 0), (1, 0, 1)]
keys = w.context_menu_keys()
check("tasto destro nello strumento Nodi con due nodi scelti: Allinea e Distribuisci", "align_left" in keys
      and "dist_h" in keys and "node_join" in keys, keys)
nt.sel = [(0, 0, 0)]
check("…con un nodo solo no", "align_left" not in w.context_menu_keys())
S1, S2 = RectShape(10, 10), RectShape(10, 10)
S2.set_transform(QTransform().translate(30, 7))
fresh(RectShape(3, 3))
check("strumento Selezione con una forma: Allinea spento come prima", not w.acts["align_left"].isEnabled()
      and not w.acts["dist_h"].isEnabled())
fresh(S1, S2)
w.acts["align_bottom"].trigger()
spin()
check("con lo strumento Selezione Allinea lavora sulle forme come prima", abs(S1.bounds().top() - S2.bounds().top()) < 1e-9
      and isinstance(ed.doc.shapes[0], RectShape))
S1, S2 = RectShape(10, 10), RectShape(10, 10)
S2.set_transform(QTransform().translate(30, 7))
nt = fresh(S1, S2, tool="nodes")
nt.sel = []
w.acts["align_bottom"].trigger()
spin()
check("strumento Nodi senza nodi scelti: Allinea lavora sulle forme come prima",
      abs(ed.doc.shapes[0].bounds().top() - ed.doc.shapes[1].bounds().top()) < 1e-9)

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
