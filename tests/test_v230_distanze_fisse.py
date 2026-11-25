# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.0: distanze fisse fra due oggetti, che restano mentre si modificano le forme (Ale, 25/11/2026).

Progetto in freeburn/coda-0.23.0.md. Parte 1: calcolo e documento (core/ties.py, Shape.ties, Editor). Casi della
matrice: X, Y e punto-punto con il riferimento spostato, ridimensionato, ruotato, cambiato nei nodi; catene; giri,
secondo legame sullo stesso asse e forma bloccata rifiutati; chi segue non si trascina lungo l'asse legato; nuovo
valore; un solo passo di Annulla; eliminazione e Annulla; copie senza legami; salva e riapri; file vecchi e rovinati;
G-code uguale con e senza legami; piano ruotato; gruppi (legami addormentati e risvegliati).
"""
import math
import os
import random
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
for k in ("FLC_NO_DIALOGS", "FLC_NO_FIRST_RUN", "FLC_NO_UPDATE"):
    os.environ[k] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from freelasercut.core import ties  # noqa: E402
from freelasercut.core.document import (Document, EllipseShape, GroupShape, PathShape, RectShape,  # noqa: E402
                                        TextShape, shape_from_dict, _to_file, _from_file)
from freelasercut.ui.editor import Editor  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info != "" and not cond else ""))


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def rect(w, h, x, y):
    r = RectShape(w, h)
    r.set_transform(QTransform.fromTranslate(x, y))
    return r


def fresh(*shapes):
    ed = Editor(Document())
    for s in shapes:
        ed.doc.add(s)
    return ed


def move(ed, s, dx, dy, label="Sposta"):
    ed.begin(label)
    s.apply(QTransform.fromTranslate(dx, dy))
    ed.commit()


def gap_x(R, S):
    return S.bounds().left() - R.bounds().right()


def now(ed, *shapes):
    """Le forme di adesso: Annulla e Ripeti ricreano le forme dalla cronologia (stesso id, oggetto nuovo)."""
    out = [ed.doc.find(s.id) for s in shapes]
    return out[0] if len(out) == 1 else out


# ================================================================== 1. pure: misura e spostamento coerenti
random.seed(23)
worst = 0.0
for _ in range(300):
    rr = QRectF(random.uniform(-50, 50), random.uniform(-50, 50), random.uniform(1, 40), random.uniform(1, 40))
    rs = QRectF(random.uniform(-50, 50), random.uniform(-50, 50), random.uniform(1, 40), random.uniform(1, 40))
    for axis in ("x", "y"):
        for er in ties.EDGES:
            for es in ties.EDGES:
                t = ties.make_xy("r", rr, rs, axis, er, es)
                worst = max(worst, abs(ties.measure(t, rr, rs) - t["d"]))  # creato sulla posizione di adesso
                t2 = dict(t, d=t["d"] + 7.25)
                dx, dy = ties.shift(t2, rr, rs)
                worst = max(worst, abs(ties.measure(t2, rr, rs.translated(dx, dy)) - t2["d"]),
                            abs(dy if axis == "x" else dx))
    for er in [(a, b) for a in ties.EDGES for b in ties.EDGES][::2]:
        t = ties.make_p("r", rr, rs, list(er), ["center", "center"])
        if t is None:
            continue
        t2 = dict(t, d=t["d"] * 1.5 + 1)
        dx, dy = ties.shift(t2, rr, rs)
        p0, p1 = ties.point(rr, t2["er"]), ties.point(rs.translated(dx, dy), t2["es"])
        worst = max(worst, abs(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) - t2["d"]))
check("calcolo: 300 coppie a caso × assi × 9 coppie di bordi e punto-punto, distanza tenuta", worst < 1e-9, worst)

rr, rs = QRectF(0, 0, 10, 10), QRectF(30, 0, 10, 10)
t = ties.make_xy("r", rr, rs, "x", "max", "min")
check("legame dalla posizione: spazio 20 mm, lato +1", t["d"] == 20 and t["side"] == 1)
t = ties.make_xy("r", rs, rr, "x", "min", "max")
check("dall'altra parte: lato −1 e distanza positiva", t["d"] == 20 and t["side"] == -1)
check("punto-punto su punti coincidenti: rifiutato", ties.make_p("r", rr, rr, ["min", "min"], ["min", "min"]) is None)

# file rovinati o di terzi
bad = [None, 3, {}, {"ref": "", "axis": "x"}, {"ref": "a", "axis": "z", "d": 1},
       {"ref": "a", "axis": "x", "d": -1, "er": "min", "es": "min", "side": 1},
       {"ref": "a", "axis": "x", "d": "nan", "er": "min", "es": "min", "side": 1},
       {"ref": "a", "axis": "x", "d": 5, "er": "left", "es": "min", "side": 1},
       {"ref": "a", "axis": "x", "d": 5, "er": "min", "es": "min", "side": 2},
       {"ref": "a", "axis": "p", "d": 5, "er": ["min"], "es": ["min", "min"], "u": [1, 0]},
       {"ref": "a", "axis": "p", "d": 5, "er": ["min", "min"], "es": ["min", "min"], "u": [0, 0]}]
good = {"ref": "a", "axis": "p", "d": 9e9, "er": ["min", "max"], "es": ["center", "center"], "u": [3, 4]}
cl = ties.clean(bad + [good])
check("file rovinato: legami non validi scartati, distanza al massimo, direzione lunga 1",
      len(cl) == 1 and cl[0]["d"] == ties.D_MAX and near(cl[0]["u"][0], 0.6) and near(cl[0]["u"][1], 0.8))
check("chiave assente o non lista: nessun legame", ties.clean(None) == [] and ties.clean("x") == [])

# ================================================================== 2. riferimento spostato (X, Y, punto-punto)
R, S = rect(20, 10, 0, 0), rect(10, 10, 40, 0)
ed = fresh(R, S)
check("aggiungi distanza fissa X: un passo", ed.add_tie(S, R, ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min")) == ""
      and len(ed.undo_stack) == 1)
y0 = S.bounds().top()
move(ed, R, 13.5, 4)
check("X: R spostato → S segue lungo X, non lungo Y", near(gap_x(R, S), 20) and near(S.bounds().top(), y0))
check("X: un solo passo per spostamento e seguaci", len(ed.undo_stack) == 2)
ed.undo()
R, S = now(ed, R, S)
check("Annulla: R e S tornano insieme", near(R.bounds().left(), 0) and near(S.bounds().left(), 40))
ed.redo()
R, S = now(ed, R, S)
check("Ripeti: di nuovo insieme", near(R.bounds().left(), 13.5) and near(S.bounds().left(), 53.5))

R, S = rect(20, 10, 0, 0), rect(10, 10, 0, 30)
ed = fresh(R, S)
ed.add_tie(S, R, ties.make_xy(R.id, R.bounds(), S.bounds(), "y", "center", "min"))
move(ed, R, 5, -8)
check("Y: R spostato → S segue lungo Y", near(S.bounds().top() - R.bounds().center().y(), 25) and near(S.bounds().left(), 0))

R, S = rect(10, 10, 0, 0), rect(10, 10, 30, 40)
ed = fresh(R, S)
tp = ties.make_p(R.id, R.bounds(), S.bounds(), ["max", "max"], ["min", "min"])
ed.add_tie(S, R, tp)
move(ed, R, -3, 7)
p0, p1 = ties.point(R.bounds(), tp["er"]), ties.point(S.bounds(), tp["es"])
check("punto-punto: R spostato → S segue, stessa distanza e direzione",
      near(math.hypot(p1[0] - p0[0], p1[1] - p0[1]), tp["d"]) and near(p1[0] - p0[0], 20) and near(p1[1] - p0[1], 30))

# ================================================================== 3. riferimento ridimensionato, ruotato, nodi, testo
R, S = rect(20, 10, 0, 0), rect(10, 10, 40, 0)
ed = fresh(R, S)
ed.add_tie(S, R, ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min"))
ed.begin("Scala")
R.set_transform(QTransform.fromScale(2, 1) * QTransform.fromTranslate(0, 0))
ed.commit()
check("R ridimensionato dal bordo dell'aggancio: S segue", near(gap_x(R, S), 20) and near(R.bounds().right(), 40))
ed.begin("Scala")
R.set_transform(QTransform.fromScale(2, 1) * QTransform.fromTranslate(-15, 0))  # bordo destro fermo
ed.commit()
check("R ridimensionato dal bordo opposto: S non si muove", near(S.bounds().left(), 45) and near(gap_x(R, S), 20))
ed.begin("Ruota")
R.set_transform(QTransform().rotate(30) * QTransform.fromTranslate(0, 0))
ed.commit()
check("R ruotato 30°: S segue il nuovo ingombro", near(gap_x(R, S), 20))

P = PathShape()
from PySide6.QtGui import QPainterPath  # noqa: E402

pp = QPainterPath()
pp.moveTo(0, 0)
pp.lineTo(10, 0)
pp.lineTo(10, 10)
pp.closeSubpath()
P.set_path(pp)
S = rect(5, 5, 30, 0)
ed = fresh(P, S)
ed.add_tie(S, P, ties.make_xy(P.id, P.bounds(), S.bounds(), "x", "max", "min"))
pp2 = QPainterPath()
pp2.moveTo(0, 0)
pp2.lineTo(18, 0)
pp2.lineTo(10, 10)
pp2.closeSubpath()
ed.begin("Modifica nodi")
P.set_path(pp2)
ed.commit()
check("nodi di R modificati (bordo più in là): S segue", near(gap_x(P, S), 20))

T = TextShape("AB")
S = rect(5, 5, 200, 0)
ed = fresh(T, S)
ed.add_tie(S, T, ties.make_xy(T.id, T.bounds(), S.bounds(), "x", "max", "min"))
d0 = gap_x(T, S)
ed.begin("Testo")
T.text = "ABCDEF"
T.invalidate()
ed.commit()
check("testo cambiato (ingombro più largo): S segue", near(gap_x(T, S), d0, 1e-6) and T.bounds().width() > 0)

# ================================================================== 4. catene, giri, assi occupati, bloccati
A, B, C = rect(10, 10, 0, 0), rect(10, 10, 20, 0), rect(10, 10, 40, 0)
ed = fresh(C, B, A)  # ordine di disegno al contrario: il calcolo deve seguire la catena, non l'elenco
ed.add_tie(B, A, ties.make_xy(A.id, A.bounds(), B.bounds(), "x", "max", "min"))
ed.add_tie(C, B, ties.make_xy(B.id, B.bounds(), C.bounds(), "x", "max", "min"))
move(ed, A, 11, 0)
check("catena A→B→C: muovo A, B e C seguono in ordine", near(gap_x(A, B), 10) and near(gap_x(B, C), 10)
      and near(C.bounds().left(), 51))
why = ed.add_tie(A, C, ties.make_xy(C.id, C.bounds(), A.bounds(), "x", "min", "max"))
check("giro A→B→C→A: rifiutato", why == "cycle")
why = ed.add_tie(A, C, ties.make_xy(C.id, C.bounds(), A.bounds(), "y", "min", "min"))
check("giro anche su un altro asse: rifiutato (si sposterebbero a vicenda)", why == "cycle")
why = ed.add_tie(B, C, ties.make_xy(C.id, C.bounds(), B.bounds(), "x", "min", "min"))
check("giro corto B↔C: rifiutato", why == "cycle")
D = rect(10, 10, 0, 50)
ed.doc.add(D)
why = ed.add_tie(C, D, ties.make_xy(D.id, D.bounds(), C.bounds(), "x", "min", "min"))
check("secondo legame sullo stesso asse: rifiutato", why == "busy")
why = ed.add_tie(C, D, ties.make_p(D.id, D.bounds(), C.bounds(), ["min", "min"], ["min", "min"]))
check("punto-punto su una forma già legata in X: rifiutato", why == "busy")
why = ed.add_tie(C, D, ties.make_xy(D.id, D.bounds(), C.bounds(), "y", "min", "min"))
check("legame sull'altro asse (Y) da un altro riferimento: accettato", why == "")
move(ed, D, 0, 9)
check("C segue D in Y (tiene i 50 mm di quando è nato) e B in X",
      near(D.bounds().top() - C.bounds().top(), 50) and near(C.bounds().top(), 9) and near(gap_x(B, C), 10))
check("stessa forma: rifiutato", ed.add_tie(A, A, ties.make_xy(A.id, A.bounds(), A.bounds(), "x", "min", "min")) == "same")
L = rect(10, 10, 100, 100)
L.locked = True
ed.doc.add(L)
check("forma bloccata come chi segue: rifiutato",
      ed.add_tie(L, A, ties.make_xy(A.id, A.bounds(), L.bounds(), "x", "min", "min")) == "locked")
check("forma bloccata come riferimento: accettato",
      ed.add_tie(A, L, ties.make_xy(L.id, L.bounds(), A.bounds(), "y", "min", "min")) == "")
msgs = []
ed.message.connect(msgs.append)
B.locked = True
move(ed, A, 3, 0)
check("chi segue bloccato dopo: non si sposta e lo si dice", near(gap_x(A, B), 7) and any("bloccata" in m for m in msgs))
B.locked = False

# un file di terzi con un giro: niente salti, niente blocchi
X, Y = rect(10, 10, 0, 0), rect(10, 10, 30, 0)
X.ties = [ties.make_xy(Y.id, Y.bounds(), X.bounds(), "x", "min", "max")]
Y.ties = [ties.make_xy(X.id, X.bounds(), Y.bounds(), "x", "max", "min")]
ed = fresh(X, Y)
mv, st, cy = ed.solve_ties(final=True)
check("file con un giro: nessuno si sposta, il giro è riconosciuto", mv == [] and sorted(cy) == sorted([X.id, Y.id]))
X.ties.append(dict(X.ties[0], axis="x"))
check("file con due legami sullo stesso asse: vale il primo", len(ed.ties_of(X)) == 1)

# ================================================================== 5. chi segue non si trascina lungo l'asse legato
R, S = rect(10, 10, 0, 0), rect(10, 10, 30, 0)
ed = fresh(R, S)
ed.add_tie(S, R, ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min"))
msgs = []
ed.message.connect(msgs.append)
ed.select([S])
move(ed, S, 15, 6)
check("S spostato a mano: lungo X resta legato, lungo Y si sposta", near(gap_x(R, S), 20) and near(S.bounds().top(), 6))
check("…e lo si dice", any("distanza fissa" in m for m in msgs))
ed.select([R, S])
move(ed, S, 0, 0)
R.apply(QTransform.fromTranslate(0, 0))
ed.begin("Sposta")
for s in (R, S):
    s.apply(QTransform.fromTranslate(7, 0))
ed.commit()
check("R e S spostati insieme: si spostano tutti e due", near(R.bounds().left(), 7) and near(gap_x(R, S), 20))

# ================================================================== 6. nuovo valore, togliere, eliminare
R, S = rect(10, 10, 0, 0), rect(10, 10, 30, 0)
ed = fresh(R, S)
ed.add_tie(S, R, ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min"))
n0 = len(ed.undo_stack)
ed.set_tie_distance(S, 0, 12.5)
check("nuovo valore: S si sposta subito, un passo", near(gap_x(R, S), 12.5) and len(ed.undo_stack) == n0 + 1)
ed.set_tie_distance(S, 0, -4)
check("valore negativo: diventa 0", near(gap_x(R, S), 0))
ed.set_tie_distance(S, 0, 1e9)
check("valore enorme: diventa il massimo", near(S.ties[0]["d"], ties.D_MAX))
ed.undo()
ed.undo()
ed.undo()
R, S = now(ed, R, S)
check("Annulla tre volte: di nuovo 20 mm", near(gap_x(R, S), 20) and near(S.ties[0]["d"], 20))
ed.select([R])
ed.delete()
check("R eliminato: il legame dorme", ed.ties_of(S) == [] and len(S.ties) == 1)
s_left = S.bounds().left()
move(ed, S, 5, 0)
check("…e S si sposta liberamente", near(S.bounds().left(), s_left + 5))
ed.undo()
ed.undo()
S = now(ed, S)
Rb = ed.doc.find(R.id)
check("Annulla: R torna e il legame si risveglia", Rb is not None and len(ed.ties_of(ed.doc.find(S.id))) == 1)
S2 = ed.doc.find(S.id)
check("togli la distanza fissa: un passo", ed.remove_ties([S2]) == 1 and S2.ties == [])
ed.undo()
check("Annulla la rimette", len(ed.doc.find(S.id).ties) == 1)

# legame spento: resta salvato, non guida; riaccendendo si ricontrolla
R, S = rect(10, 10, 0, 0), rect(10, 10, 30, 0)
ed = fresh(R, S)
ed.add_tie(S, R, ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min"))
check("spegni: un passo", ed.set_tie_on(S, 0, False) == "" and S.ties[0].get("on") is False)
move(ed, R, 6, 0)
check("spento: S non segue", near(S.bounds().left(), 30) and ed.ties_of(S) == [])
dd = shape_from_dict(S.to_dict())
check("spento: si salva spento", dd.ties and dd.ties[0].get("on") is False)
check("spento: un altro legame sullo stesso asse prende il suo posto",
      ties.check_new(ed.doc.shapes, S, R, "x") == "")
ed.add_tie(R, S, ties.make_xy(S.id, S.bounds(), R.bounds(), "y", "min", "min"))
check("riaccendere quando farebbe un giro: rifiutato", ed.set_tie_on(S, 0, True) == "cycle" and S.ties[0].get("on") is False)
ed.remove_ties([R])
check("riaccendi: S torna alla distanza", ed.set_tie_on(S, 0, True) == "" and near(gap_x(R, S), 20))

# file rovinato aperto dal documento
dd = rect(5, 5, 0, 0).to_dict()
dd["ties"] = [{"ref": "x", "axis": "x"}, "rotto", {"ref": "a", "axis": "y", "d": 3, "er": "min", "es": "max", "side": -1}]
_got = shape_from_dict(dd).ties
check("file rovinato aperto: tenuto solo il legame valido", _got == [
    {"ref": "a", "axis": "y", "d": 3.0, "er": "min", "es": "max", "side": -1}], _got)

# ================================================================== 7. copie: niente legami
R, S = rect(10, 10, 0, 0), rect(10, 10, 30, 0)
ed = fresh(R, S)
ed.add_tie(S, R, ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min"))
ed.select([S])
ed.duplicate()
dup = ed.selection[0]
check("Duplica: la copia non ha legami", dup.id != S.id and dup.ties == [])
ed.select([S])
ed.copy()
ed.paste()
check("Copia/incolla: niente legami", all(s.ties == [] for s in ed.selection))
ed.select([S])
ed.grid_array(3, 1, 20, 0)
cop = [s for s in ed.doc.shapes if s.id not in (R.id, S.id) and s is not dup]
check("matrice: le copie non hanno legami", cop and all(not s.ties for s in cop if s.id != S.id))
k = ed.duplicate_plate(0)
P2 = ed.doc.plates[k].shapes
R2 = [x for x in P2 if abs(x.bounds().left()) < 1e-6 and abs(x.bounds().top()) < 1e-6][0]
S2 = [x for x in P2 if x.ties]
check("Duplica il piano: le distanze fisse passano alle copie, ricollegate fra loro",
      len(S2) == 1 and S2[0].ties[0]["ref"] == R2.id and S2[0].id != S.id)
move(ed, R2, 4, 0)
check("…e nel piano copiato guidano", near(gap_x(R2, S2[0]), 20))
ed.set_plate(0)
c = S.clone()
check("clone con id nuovo: niente legami; clone con lo stesso id: legami uguali",
      c.ties == [] and S.clone(new_id=False).ties == S.ties)

# ================================================================== 8. salva e riapri, file vecchi
R, S, Q = rect(10, 10, 0, 0), rect(10, 10, 30, 0), rect(10, 10, 0, 40)
ed = fresh(R, S, Q)
ed.add_tie(S, R, ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min"))
ed.add_tie(Q, R, ties.make_p(R.id, R.bounds(), Q.bounds(), ["min", "max"], ["min", "min"]))
fn = os.path.join(tempfile.mkdtemp(), "p.flcut")
ed.doc.save(fn)
doc2 = Document.load(fn)
S2, Q2 = doc2.find(S.id), doc2.find(Q.id)
check("salva e riapri: legami uguali", S2.ties == S.ties and Q2.ties == Q.ties)
ed2 = Editor(doc2)
move(ed2, doc2.find(R.id), 4, 4)
check("…e guidano ancora", near(gap_x(doc2.find(R.id), S2), 20))
d = R.to_dict()
check("forma senza legami: nel file nessuna chiave nuova (file uguale alle versioni prima)", "ties" not in d)
od = rect(5, 5, 0, 0).to_dict()
od.pop("ties", None)
old = shape_from_dict(od)
check("forma di un file vecchio: si apre senza legami", old.ties == [])

# ================================================================== 9. G-code uguale con e senza legami
try:
    from freelasercut.core import gcode
    from freelasercut.profile import MachineProfile

    R, S = rect(10, 10, 5, 5), rect(10, 10, 35, 5)
    ed = fresh(R, S)
    prof = MachineProfile()
    g1 = gcode.generate(ed.doc, prof)
    ed.add_tie(S, R, ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min"))
    g2 = gcode.generate(ed.doc, prof)
    txt = lambda g: "\n".join(map(str, g.lines))  # noqa: E731
    check("G-code identico con e senza la distanza fissa", txt(g1) == txt(g2))
except Exception as ex:  # noqa: BLE001
    check("G-code identico con e senza la distanza fissa", False, repr(ex))

# ================================================================== 10. piano ruotato
for k, tf in ((1, QTransform(0.0, 1.0, -1.0, 0.0, 300, 0.0)), (2, QTransform(-1.0, 0.0, 0.0, -1.0, 300, 200)),
              (3, QTransform(0.0, -1.0, 1.0, 0.0, 0.0, 200))):
    R, S, Q = rect(20, 10, 10, 10), rect(10, 10, 50, 15), rect(10, 10, 15, 60)
    for sh in (R, S, Q):
        sh._doc_images = None
    tx = ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min")
    tq = ties.make_p(R.id, R.bounds(), Q.bounds(), ["min", "max"], ["center", "min"])
    S.ties, Q.ties = [tx], [tq]
    ok = True
    for sh in (R, S, Q):
        sh.apply(tf)
        ties.map_shape_tree(sh, tf)
    ok &= near(ties.measure(S.ties[0], R.bounds(), S.bounds()), tx["d"])
    ok &= near(ties.measure(Q.ties[0], R.bounds(), Q.bounds()), tq["d"])
    ok &= all(near(ties.shift(sh.ties[0], R.bounds(), sh.bounds())[i], 0) for sh in (S, Q) for i in (0, 1))
    inv, _ = tf.inverted()
    dd = _to_file(S, inv)
    back = shape_from_dict(dd)
    R0 = rect(20, 10, 10, 10)
    ok &= back.ties[0] == tx and near(ties.measure(back.ties[0], R0.bounds(), back.bounds()), tx["d"])
    _from_file([back], tf)
    ok &= back.ties == S.ties
    check(f"piano ruotato ({90 * k}°): le distanze restano giuste dopo il giro e nel file", ok)

# ================================================================== 11. gruppi
R, S, O = rect(10, 10, 0, 0), rect(10, 10, 30, 0), rect(10, 10, 0, 50)
ed = fresh(R, S, O)
ed.add_tie(S, R, ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min"))
ed.select([R, O])
ed.group()
G = ed.selection[0]
check("R raggruppato: il legame di S dorme", isinstance(G, GroupShape) and ed.ties_of(S) == [] and len(S.ties) == 1)
move(ed, G, 9, 0)
check("…S non segue il gruppo", near(S.bounds().left(), 30))
ed.select([G])
ed.ungroup()
check("Separa: R torna di primo livello, il legame si risveglia e S raggiunge la distanza al primo cambio",
      len(ed.ties_of(S)) == 1 and near(gap_x(ed.doc.find(R.id), S), 20))
ed.select([S, O])
ed.group()
G2 = ed.selection[0]
g_left = G2.bounds().left()
move(ed, ed.doc.find(R.id), 5, 0)
check("S raggruppato: dorme (il gruppo non si muove da solo)", near(G2.bounds().left(), g_left))
fn = os.path.join(tempfile.mkdtemp(), "g.flcut")
ed.doc.save(fn)
dg = Document.load(fn)
check("legame dentro un gruppo: si salva e si riapre", [c for c in dg.find(G2.id).children if c.id == S.id][0].ties == S.ties)

# ================================================================== 12. velocità
shapes = [rect(5, 5, 7 * i, 0) for i in range(400)]
for a, b in zip(shapes, shapes[1:]):
    b.ties = [ties.make_xy(a.id, a.bounds(), b.bounds(), "x", "max", "min")]
ed = fresh(*shapes)
import time  # noqa: E402

t0 = time.perf_counter()
ed.begin("Sposta")
shapes[0].apply(QTransform.fromTranslate(3, 0))
ed.commit()
dt = time.perf_counter() - t0
check("catena di 400 forme: tutte seguono e in fretta", near(shapes[-1].bounds().left(), 7 * 399 + 3) and dt < 1.5,
      f"{dt:.2f} s")
plain = fresh(*[rect(5, 5, 7 * i, 0) for i in range(400)])
t0 = time.perf_counter()
for _ in range(50):
    plain.solve_ties()
check("senza legami: nessun costo (50 calcoli)", time.perf_counter() - t0 < 0.05)

print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(0 if all(results) else 1)
