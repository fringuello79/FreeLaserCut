# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.22.0: «Adatta gli incastri allo spessore» (Stefano Modena ed Evoluzione2, 21-22/11/2026).

Pezzi disegnati qui (niente file degli utenti nel repository), con tutti i casi dei loro file: bordi a dita con le
estremità alte o basse, angoli in comune fra due bordi a dita, un bordo a dita obliquo (tetto) che finisce su un lato
dritto, linguette sole che entrano in fori stretti di 0,1 mm, fessure a croce dal bordo, curve che non si toccano.
Uso: python tests/test_v220_incastri.py [banco]
"""
import collections
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
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_LANG"] = "it"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtGui import QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core import slots  # noqa: E402
from freelasercut.core.document import EllipseShape, PathShape  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui.dialogs_shapes import ThicknessDialog, _shape_polys  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


T = 4.0  # spessore per cui sono disegnati i pezzi


def fingers(x0, y0, length, n, t, up, start_high):
    """Punti di un bordo a dita orizzontale da sinistra a destra (y in su): n tratti larghi uguali, alternati alto
    (y0) e basso (y0 - t se up, cioè la linea dei fondi sta dentro il pezzo)."""
    pts, w = [], length / n
    for k in range(n):
        high = (k % 2 == 0) == start_high
        y = y0 if high else (y0 - t if up else y0 + t)
        pts += [(x0 + k * w, y), (x0 + (k + 1) * w, y)]
    return pts


def panel_a(t=T):
    """Pannello 100 × 60 con il bordo alto a dita, estremità BASSE (come il pezzo di Evo: l'angolo scende)."""
    top = fingers(0, 60, 100, 5, t, True, False)  # basso-alto-basso-alto-basso
    return [(0, 0), (100, 0)] + list(reversed(top))[:0] + [(100, 60 - t)] + list(reversed(top))[1:-1] + [(0, 60 - t)]


def poly_path(pts, holes=()):
    p = QPainterPath()
    for ring in (pts,) + tuple(holes):
        p.moveTo(*ring[0])
        for q in ring[1:]:
            p.lineTo(*q)
        p.closeSubpath()
    return p


def rect(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


# --- i pezzi -----------------------------------------------------------------------------------------------------
# A: bordo alto a dita con le estremità basse; lato destro a dita con le estremità alte (angolo in comune)
A_top = [(0, 56), (20, 56), (20, 60), (40, 60), (40, 56), (60, 56), (60, 60), (80, 60), (80, 56), (100, 56)]
A = [(0, 0), (100, 0), (100, 10), (96, 10), (96, 20), (100, 20), (100, 30), (96, 30), (96, 40), (100, 40)] \
    + list(reversed(A_top))[0:0] + [(100, 56)] + list(reversed(A_top))[1:]
# B: bordo basso a dita con le estremità alte (punte agli angoli): le misure esterne restano
B = [(200, 0), (220, 0), (220, 4), (240, 4), (240, 0), (260, 0), (260, 4), (280, 4), (280, 0), (300, 0),
     (300, 60), (200, 60)]
# C: pannello con due linguette sole in basso (entrano nei fori di D) e una fessura a croce dal bordo alto
C = [(400, 0), (420, 0), (420, -4), (445, -4), (445, 0), (455, 0), (455, -4), (480, -4), (480, 0), (500, 0),
     (500, 60), (452, 60), (452, 30), (448, 30), (448, 60), (400, 60)]
# D: pannello con due fori 3,9 × 25 (gioco di 0,1 mm) e un cerchio decorativo
D = [(600, 0), (700, 0), (700, 60), (600, 60)]
D_holes = [rect(620, 28.05, 25, 3.9), rect(655, 28.05, 25, 3.9)]
# E: tetto obliquo a dita che finisce su un lato verticale (casetta): estremità bassa contro il lato
s2 = math.sqrt(0.5)


def roof():
    """Bordo a 45° da (0,0) verso l'alto a destra, 4 tratti da 20 mm, il primo basso; poi lato verticale."""
    ux, uy, nx, ny = s2, s2, -s2, s2  # lungo il tetto, verso fuori
    pts = []
    for k in range(4):
        off = 0 if k % 2 else -T  # basso = rientrato
        a = (k * 20 * ux + off * nx, k * 20 * uy + off * ny)
        b = ((k + 1) * 20 * ux + off * nx, (k + 1) * 20 * uy + off * ny)
        pts += [a, b]
    pts = [(800 + x, 100 + y) for x, y in pts]
    end = pts[-1]
    return [(800 + T * s2, 0), (end[0] + 40, 0), (end[0] + 40, end[1])] + list(reversed(pts))


E = roof()
E = E[:-1] + [(E[-1][0], E[-1][1])]


def shapes_now():
    out = []
    for pts, holes in ((A, ()), (B, ()), (C, ()), (D, D_holes), (E, ())):
        out.append(PathShape(poly_path(pts, holes), layer=0))
    deco = EllipseShape(20, 20, layer=0)
    deco.set_transform(QTransform.fromTranslate(640, 45))
    out.append(deco)
    return out


def measures(polys):
    """Tutte le misure «da incastro» (pareti e fondi fra due angoli retti) fra 1,5 e 9 mm, arrotondate."""
    cl, _m = slots._cleaned(polys)
    h = collections.Counter()
    for sh in cl:
        for pts, c in sh:
            if not c or len(pts) < 4:
                continue
            n = len(pts)
            for i in range(n):
                pp, p0, p1, pn = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
                ux, uy, Lb = slots._unit(p0, p1)
                ax, ay, La = slots._unit(pp, p0)
                cx, cy, Lc = slots._unit(p1, pn)
                if min(Lb, La, Lc) < 0.05 or abs(ax * ux + ay * uy) > 0.02 or abs(cx * ux + cy * uy) > 0.02 \
                        or ax * cx + ay * cy > -0.98:
                    continue
                for L in (La, Lb, Lc):
                    if 1.5 < L < 9:
                        h[round(L, 2)] += 1
    return h


def bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)


sh = shapes_now()
polys = [_shape_polys(s) for s in sh]

# ============================================================ il calcolo
print("--- calcolo")
det = slots.detect(polys)
check("trova lo spessore del disegno: 4 mm", det and det[0][0] == 4.0, det)
cnt = det[0][1] if det else {}
check("…e conta fessure e fori, tacche, linguette", cnt.get("fessura", 0) >= 3 and cnt.get("tacca", 0) >= 3
      and cnt.get("linguetta", 0) >= 4, cnt)
check("pezzo senza incastri: niente spessore", slots.detect([_shape_polys(EllipseShape(50, 30))]) == [])

res, done, skipped, changed = slots.change_thickness(polys, 4.0, 6.0)
before, after = measures(polys), measures(res)
check("da 4 a 6 mm: le misure da 4 diventano 6 e quelle da 3,9 diventano 5,9", before[4.0] and before[3.9]
      and after[6.0] == before[4.0] and after[5.9] == before[3.9] and not after[4.0] and not after[3.9],
      (dict(before), dict(after)))
check("…nessuna misura raddoppiata (8 mm) né rimasta a metà", not after[8.0] and not after[5.0], dict(after))
check("…nessun incastro saltato", not skipped, skipped)
check("…cambiano tutti e tre i tipi", done["fessura"] and done["tacca"] and done["linguetta"], done)


def ring(res_i, k=0):
    return res[res_i][k][0]


check("B (bordo a dita con le punte agli angoli): misure esterne uguali", bbox(ring(1)) == bbox(polys[1][0][0]),
      (bbox(ring(1)), bbox(polys[1][0][0])))
check("A (estremità basse): le punte restano a 60, i fondi e l'angolo scendono a 54",
      bbox(ring(0))[3] == 60 and min(p[1] for p in ring(0) if p[0] in (0, 100) and p[1] > 50) == 54,
      sorted(set(round(p[1], 2) for p in ring(0))))
check("A: il lato a dita a destra e quello in alto si incontrano in un angolo solo (niente gradini)",
      (100, 54) in [(round(x, 3), round(y, 3)) for x, y in ring(0)], ring(0))
bc = bbox(ring(2))
ys = sorted({round(y, 3) for x, y in ring(2) if y < 30})
check("C (due linguette vicine sul bordo, come un bordo a dita): punte ferme, la base sale, linguette lunghe 6",
      bc[1] == -4 and bc[3] == 60 and ys[:2] == [-4.0, 2.0], (bc, ys))
fess = sorted({round(x, 3) for x, y in ring(2) if 30 <= y <= 60 and 440 < x < 460})
check("C: la fessura a croce si allarga al centro (da 448–452 a 447–453), profonda uguale",
      fess == [447.0, 453.0] and any(round(y, 3) == 30 for x, y in ring(2) if 440 < x < 460), (fess,))
holes = [bbox(r[0]) for r in res[3][1:3]]
check("D: i fori da 3,9 diventano 5,9, sempre lunghi 25 e con lo stesso centro",
      all(round(h[3] - h[1], 3) == 5.9 and round(h[2] - h[0], 3) == 25 and round((h[1] + h[3]) / 2, 3) == 30
          for h in holes), holes)
check("D: il contorno esterno senza incastri non cambia", res[3][0][0] == polys[3][0][0] or
      bbox(res[3][0][0]) == bbox(polys[3][0][0]))
check("cerchio decorativo: non toccato", 5 not in changed and res[5] == polys[5])
eb, ea = bbox(polys[4][0][0]), bbox(ring(4))
check("E (tetto obliquo che finisce sul lato): cambia senza saltare niente e l'angolo resta sul lato verticale",
      4 in changed and round(ea[2], 3) == round(eb[2], 3), (eb, ea))

res3, done3, sk3, _c = slots.change_thickness(polys, 4.0, 3.0)
m3 = measures(res3)
check("da 4 a 3 mm (più sottile): 4 → 3 e 3,9 → 2,9", m3[3.0] == before[4.0] and m3[2.9] == before[3.9]
      and not m3[4.0], dict(m3))
again, d2, sk2, ch2 = slots.change_thickness(res, 6.0, 4.0)
check("andata e ritorno (4 → 6 → 4): si torna al disegno di partenza",
      all(math.dist(p, q) < 1e-6 for a, b in zip(again, polys) for (pa, _), (pb, _) in zip(a, b)
          for p, q in zip(slots._clean(pa), slots._clean(pb))), (d2, len(sk2)))
same, dz, _s, chz = slots.change_thickness(polys, 4.0, 4.0)
check("stesso spessore: niente cambia di posto", all(
    math.dist(p, q) < 1e-9 for a, b in zip(same, polys) for (pa, _), (pb, _) in zip(a, b)
    for p, q in zip(pa, slots._clean(pb)) if len(pa) == len(slots._clean(pb))))
bad = 0
for args in ((0, 4), (4, -1), (float("nan"), 4), (4, float("inf"))):
    try:
        slots.change_thickness(polys, *args)
    except ValueError:
        bad += 1
try:
    slots.change_thickness(polys, 4, 6, tol=2.5)
except ValueError:
    bad += 1
check("misure sbagliate o tolleranza oltre metà spessore: rifiutate", bad == 5)
# un incastro troppo vicino: due fori da 3,9 a 0,5 mm l'uno dall'altro, da allargare a 6
close = [[(rect(0, 0, 60, 40), True), (rect(10, 10, 25, 3.9), True), (rect(10, 14.4, 25, 3.9), True)]]
rc, dc, skc, _cc = slots.change_thickness(close, 4.0, 6.0)
check("fori troppo vicini per allargarli (si toccherebbero): restano come sono e vengono contati",
      dc["fessura"] == 0 and len(skc) == 2 and all(k == "fessura" for k, _p in skc) and rc[0][1][0] == close[0][1][0],
      (dc, skc))
far = [[(rect(0, 0, 60, 40), True), (rect(10, 10, 25, 3.9), True), (rect(10, 20, 25, 3.9), True)]]
rf, df, skf, _cf = slots.change_thickness(far, 4.0, 6.0)
check("…e con spazio a sufficienza si allargano tutti e due", df["fessura"] == 2 and not skf, (df, skf))
edge = [[(rect(0, 0, 60, 40), True), (rect(10, 0.5, 25, 3.9), True)]]
re_, de, ske, _ce = slots.change_thickness(edge, 4.0, 6.0)
check("foro che allargandosi uscirebbe dal bordo del pezzo: resta com'è", de["fessura"] == 0 and len(ske) == 1, (de, ske))

# casi in più (guasti messi apposta che prima sfuggivano)
# F: quadrato con due bordi a dita che finiscono tutti e due «bassi» nello stesso angolo (in alto a destra)
F = [(0, 0), (60, 0), (60, 10), (56, 10), (56, 20), (60, 20), (60, 30), (56, 30), (56, 56), (44, 56), (44, 60),
     (32, 60), (32, 56), (20, 56), (20, 60), (0, 60)]
rF, dF, skF, _c = slots.change_thickness([[(F, True)]], 4.0, 6.0)
qF = [(round(x, 3), round(y, 3)) for x, y in rF[0][0][0]]
check("due bordi a dita che finiscono bassi nello stesso angolo: l'angolo scende su tutti e due (54, 54)",
      (54.0, 54.0) in qF and not skF, (qF, skF))
# G: linguetta quadrata 4 × 4 (larga quanto lo spessore): si allunga, non si allarga
G = [(0, 0), (30, 0), (30, 40), (17, 40), (17, 44), (13, 44), (13, 40), (0, 40)]
rG, dG, skG, _c = slots.change_thickness([[(G, True)]], 4.0, 6.0)
bG = bbox(rG[0][0][0])
xsG = sorted({round(x, 3) for x, y in rG[0][0][0] if y > 41})
check("linguetta larga quanto lo spessore: si allunga a 6, resta larga 4", bG[3] == 46 and xsG == [13.0, 17.0]
      and dG["linguetta"] == 1 and not dG["fessura"], (bG, xsG, dG))
# il tetto: l'angolo nuovo resta sul lato verticale
xE = round(min(p[0] for p in polys[4][0][0]), 3)
check("E: l'angolo fra tetto e lato verticale resta sul lato (stessa x, più in basso)",
      sum(1 for p in ring(4) if round(p[0], 3) == xE) == 2 and round(min(p[0] for p in ring(4)), 3) == xE,
      [p for p in ring(4) if p[0] < xE + 3])
# tanti fori da 3,9 e poche linguette da 4: lo spessore è 4 (le linguette dicono lo spessore vero)
H = [[(rect(0, 0, 200, 100), True)] + [(rect(10 + 30 * k, 50, 25, 3.9), True) for k in range(6)],
     [([(300, 0), (340, 0), (340, -4), (360, -4), (360, 0), (400, 0), (400, 50), (300, 50)], True)]]
dH = slots.detect(H)
check("tanti fori stretti di 0,1 e una sola linguetta: lo spessore resta quello della linguetta (4)",
      dH and dH[0][0] == 4.0, dH)

# ============================================================ 0.22.1 più veloce, stessi risultati
print("--- velocità")
import random  # noqa: E402

rnd = random.Random(7)
plain = [[(rnd.uniform(0, 50), rnd.uniform(0, 50)) for _ in range(rnd.randint(3, 9))] for _ in range(40)]
mat = slots._Material(plain)
pts = [(rnd.uniform(-5, 55), rnd.uniform(-5, 55)) for _ in range(800)]
check("pari-dispari con gli ingombri: identico a quello su tutti i contorni",
      all(slots.in_material(p, mat) == slots.in_material(p, plain) for p in pts))
# molti pezzi: la misura e il cambio restano rapidi e uguali al conto pezzo per pezzo
base = panel_a()
grid = [[([(x + gx * 140.0, y + gy * 120.0) for x, y in base], True)] for gx in range(6) for gy in range(5)]
import time  # noqa: E402

t_0 = time.time()
det_many = slots.detect(grid)
res_many = slots.change_thickness(grid, det_many[0][0], 6.0)
dt = time.time() - t_0
one = slots.change_thickness([[(base, True)]], T, 6.0)
check("30 pannelli: stesso spessore trovato e 30 volte gli stessi incastri cambiati",
      det_many[0][0] == T and all(res_many[1][k] == 30 * one[1][k] for k in res_many[1]), (det_many[0], res_many[1], one[1]))
check("30 pannelli: misura e cambio in pochi secondi", dt < 8.0, round(dt, 2))


def reference(polys_by_shape, old, new, tol=0.3):
    """Il controllo fra contorni della 0.22.0, lento ma semplice: dal primo contorno che ne tocca un altro si torna
    com'era e si ricomincia da capo."""
    cleaned, material = slots._cleaned(polys_by_shape)
    items = []
    for si, shape in enumerate(cleaned):
        for ci, (pts_, closed) in enumerate(shape):
            if closed and len(pts_) >= 4:
                q, d_, s_ = slots.change_poly(pts_, material, old, new, tol)
                items.append([si, ci, pts_, q, d_, s_, closed])
            else:
                items.append([si, ci, pts_, pts_, {}, [], closed])
    while True:
        bad = None
        for a_i, it in enumerate(items):
            if sum(it[4].values()) and any(b_i != a_i and slots._cross(it[3], it[6], o[3], o[6])
                                           for b_i, o in enumerate(items)):
                bad = a_i
                break
        if bad is None:
            break
        it = items[bad]
        lost = sum(it[4].values())
        it[3], it[4], it[5] = it[2], {}, it[5] + [None] * lost
    return [[tuple(map(lambda v: round(v, 6), p_)) for p_ in it[3]] for it in items], sum(len(it[5]) for it in items)


def holes_panel(seed):
    """Un pannello con fori da T × 12 mm messi a caso: alcuni si toccano quando si allargano, a catena."""
    r = random.Random(seed)
    shape = [([(0, 0), (200, 0), (200, 120), (0, 120)], True)]
    x = 8.0
    while x < 185:
        y = r.uniform(8, 100)
        shape.append(([(x, y), (x, y + 12), (x + T, y + 12), (x + T, y)], True))
        x += T + r.choice([0.6, 0.8, 1.2, 3.0, 9.0])
    return [shape]


same = True
for seed in range(12):
    pb = holes_panel(seed)
    ref, ref_skip = reference(pb, T, 6.0)
    out_, tot_, sk_, _c = slots.change_thickness(pb, T, 6.0)
    got = [[tuple(map(lambda v: round(v, 6), p_)) for p_ in q] for shape in out_ for q, _cl in shape]
    if got != ref or len(sk_) != ref_skip:
        same = False
        print("    seme", seed, len(sk_), ref_skip)
check("fori vicini a caso (anche a catena): stessi fori allargati e stessi lasciati com'erano del controllo di prima",
      same)
prog = []
slots.detect(grid, progress=prog.append)
check("la misura dice a che punto è, dall'inizio alla fine", prog and prog[0] == 0.0 and prog[-1] == 1.0
      and prog == sorted(prog), (prog[:2], prog[-2:]))

# ============================================================ nel programma
print("--- finestra")
from PySide6.QtTest import QTest  # noqa: E402


def settle():
    QTest.qWait(500)


w = MainWindow()
acts = w.m_shape.actions() if hasattr(w, "m_shape") else []
a_thick, a_slots = w.acts.get("slots_thick"), w.acts.get("slots")
menu_acts = [a for m in w.menuBar().actions() if m.menu() for a in m.menu().actions()]
check("comando «Adatta gli incastri allo spessore…» subito dopo «Cambia la larghezza delle fessure…»",
      a_thick is not None and a_thick in menu_acts and menu_acts.index(a_thick) == menu_acts.index(a_slots) + 1)
check("scheda d'aiuto", help_texts.lookup("slots_thick"))
check("senza selezione: spento", not a_thick.isEnabled())
w.editor.add(shapes_now(), "prova")
w.editor.select(list(w.editor.doc.shapes))
check("con una selezione: acceso", a_thick.isEnabled())
dlg = ThicknessDialog(w, w.editor.editable())
check("la finestra dice lo spessore trovato e propone quello", "4 mm" in dlg.found.text() and dlg.old.value() == 4.0,
      dlg.found.text())
dlg.new.setValue(6.0)
settle()
check("anteprima sul piano e conteggio di quello che cambia", w.canvas.overlay_paths and "Cambiano" in dlg.result.text()
      and dlg.ok.isEnabled(), dlg.result.text())
dlg.new.setValue(4.0)
settle()
check("stesso spessore: «OK» spento", not dlg.ok.isEnabled())
dlg.tol.setValue(2.5)
settle()
check("tolleranza troppo grande: lo dice e «OK» spento", not dlg.ok.isEnabled() and "metà" in dlg.result.text())
dlg.reject()
w.canvas.overlay_paths = []

# 0.22.1 (Evoluzione2): frecce della tolleranza di 0,1 mm; un conto solo quando si clicca più volte; barra all'apertura
dlg = ThicknessDialog(w, w.editor.editable())
check("0.22.1 apertura: la misura dice a che punto è, fino alla fine", dlg.progress_steps
      and dlg.progress_steps[-1] == 1.0 and dlg.progress_steps == sorted(dlg.progress_steps), dlg.progress_steps[-3:])
check("0.22.1 tolleranza: le frecce vanno di 0,1 mm", abs(dlg.tol.singleStep() - 0.1) < 1e-9, dlg.tol.singleStep())
t0 = dlg.tol.value()
dlg.tol.stepBy(1)
check("0.22.1 …0,3 → 0,4", abs(dlg.tol.value() - (t0 + 0.1)) < 1e-9, dlg.tol.value())
dlg.tol.setValue(0.3)
settle()
n0 = dlg.updates
dlg.new.setValue(4.0)
dlg.new.stepBy(1)
dlg.new.stepBy(1)
check("0.22.1 mentre si clicca: «Calcolo l'anteprima…» e «OK» spento, nessun conto ancora", dlg.updates == n0
      and not dlg.ok.isEnabled() and "Calcolo" in dlg.result.text(), (dlg.updates - n0, dlg.result.text()))
settle()
check("0.22.1 da 4 a 6 con due clic: un conto solo, per il 6", dlg.updates == n0 + 1 and dlg.new.value() == 6.0
      and dlg.ok.isEnabled() and "Cambiano" in dlg.result.text(), (dlg.updates - n0, dlg.result.text()))
dlg.new.stepBy(-1)
dlg.accept()
check("0.22.1 OK premuto prima della fine del conto: prima il conto, poi si chiude con i valori giusti",
      dlg.new.value() == 5.0 and dlg.updates == n0 + 2 and "Cambiano" in dlg.result.text(),
      (dlg.updates - n0, dlg.result.text()))
w.canvas.overlay_paths = []
n_undo = len(w.editor.undo_stack)
out = w.thickness_dialog(4.0, 6.0)
check("applicato: incastri cambiati, un'azione sola di Annulla", out and sum(out[0].values()) > 0
      and len(w.editor.undo_stack) == n_undo + 1, out)
check("…messaggio con quello che è cambiato", "da 4 a 6" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
m_after = measures([_shape_polys(s) for s in w.editor.doc.shapes])
check("…le forme nel progetto hanno le misure nuove", m_after[6.0] and not m_after[4.0], dict(m_after))
w.editor.undo()
m_back = measures([_shape_polys(s) for s in w.editor.doc.shapes])
check("Annulla: tutto come prima", m_back[4.0] == before[4.0] and not m_back[6.0], dict(m_back))
w.editor.select([])
check("senza selezione il comando lo dice", w.thickness_dialog(4, 6) is None
      and "Seleziona" in w.statusBar().currentMessage())
w.editor.dirty = False
w.close()
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
