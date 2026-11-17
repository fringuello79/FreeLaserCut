# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.5: gli scatti sui PC lenti e il Wi-Fi delle schede Makerbase (rapporti del 16/11/2026).

Rapporto FLC-20261116-0746-D046 (Acmer P2, Windows 10, processore del 2012, 424 forme importate da LightBurn):
«continua a scattare nello spostare oggetti» anche con la 0.20.4. Nel registro: finestra ferma 0,9 s nel pannello
delle proprietà (perimetro, area e nodi della selezione, calcolati appiattendo le curve punto per punto). Misurato
qui su un disegno simile (432 tracciati, 186.000 elementi): pannello di tutta la selezione 0,8 s, istantanea per
Annulla 0,18 s all'inizio e alla fine di ogni trascinamento, punti dell'aggancio 0,3 s al primo movimento.
Rapporti FLC-20261116-1442-E34D e -1539-DBAF (due MKS DLC32): la procedura Wi-Fi diceva «la scheda non ha provato a
collegarsi», ma sulle MKS il tentativo è muto (firmware Makerbase: mks_StartSTA) e se la rete non si trova la rete
propria riparte subito.

Matrice dei casi:
A  misure della selezione (ops.info): stessi conteggi di prima (aperte, chiuse, nodi) su tracciati di ogni tipo
   (linee, curve, quadratiche, chiusi e aperti, sottopercorsi, degeneri, gruppi trasformati, rettangoli arrotondati,
   ellissi, testo); perimetro e area uguali al vero (spezzata finissima) entro lo 0,05%; molto più veloce;
B  elementi dei tracciati ricordati: stesso risultato della lettura uno a uno, lista esterna sempre nuova,
   istantanee uguali, Annulla e Ripeti giusti, memoria limitata, percorsi diversi mai confusi;
C  punti dell'aggancio: stessi punti, stessi tipi, stesso ordine del metodo di prima (forme nascoste, escluse, foto,
   tracciati oltre 4000 elementi), e si ricalcolano solo quando cambia il disegno;
D  aggancio mentre si sposta: senza troppe coppie risultato identico a prima; con troppe coppie solo l'ingombro;
E  misura dei movimenti col mouse premuto e dei disegni durante i movimenti: contati, nel rapporto per l'assistenza;
F  Wi-Fi Makerbase: rete che la scheda non trova (rete propria subito, modalità ancora STA) = «Il laser non trova la
   rete»; scheda che non tiene la modalità = «non ha provato» come prima; password sbagliata (tentativo lungo) =
   «non è entrato»; riuscito senza messaggi = pronto; Mecpow con «$wifi» e Longer non cambiano;
G  testi nuovi tradotti in tutte le lingue, con gli stessi segnaposto.
Uso: python tests/test_v205_scatti_wifi.py [classica|banco]
"""
import ast
import json
import math
import os
import random
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_PROVA_RETE"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent, QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import diag, perfstats  # noqa: E402
from freelasercut import wifi_setup as ws  # noqa: E402
from freelasercut.core import document as docmod, geom, ops, snapping  # noqa: E402
from freelasercut.core.document import (  # noqa: E402
    EllipseShape, GroupShape, ImageShape, PathShape, PolygonShape, RectShape, TextShape,
)
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.sim import SimSerial  # noqa: E402
from freelasercut.ui import dialogs_wifi as dw  # noqa: E402

results = []
hidden = []
sys.excepthook = lambda *a: hidden.append(a[1])
TAG = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


rng = random.Random(5)


def rnd_path(n=30, span=100.0):
    p = QPainterPath()
    p.moveTo(rng.uniform(0, span), rng.uniform(0, span))
    for _ in range(rng.randint(0, n)):
        k = rng.random()
        if k < 0.4:
            p.lineTo(rng.uniform(0, span), rng.uniform(0, span))
        elif k < 0.8:
            p.cubicTo(*(rng.uniform(0, span) for _ in range(6)))
        elif k < 0.9:
            p.quadTo(*(rng.uniform(0, span) for _ in range(4)))
        else:
            p.closeSubpath()
            p.moveTo(rng.uniform(0, span), rng.uniform(0, span))
    if rng.random() < 0.5:
        p.closeSubpath()
    return PathShape(p)


def blob(cx, cy, r, n):
    """Una macchia chiusa fatta di n curve (come un tracciato di una foto vettorializzata)."""
    p = QPainterPath()
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        rr = r * (0.6 + 0.4 * rng.random())
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    p.moveTo(*pts[0])
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        p.cubicTo(a[0] + (b[0] - a[0]) / 3 + rng.uniform(-0.3, 0.3), a[1] + (b[1] - a[1]) / 3,
                  a[0] + 2 * (b[0] - a[0]) / 3, a[1] + 2 * (b[1] - a[1]) / 3 + rng.uniform(-0.3, 0.3), *b)
    p.closeSubpath()
    return p


def truth(shapes):
    """Perimetro e area «veri»: tracciati appiattiti finissimi, ogni lato contato (anche quello che torna indietro)."""
    per = area = 0.0
    for s in shapes:
        for leaf, tf in s.leaves():
            if isinstance(leaf, ImageShape):
                continue
            for p in geom.flatten(tf.map(leaf.local_path()), 0.0005):
                pts = p.pts + ([p.pts[0]] if p.closed else [])
                per += sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
                if p.closed:
                    area += abs(p.area())
    return per, area


# ================================================================== A. misure della selezione
shapes = [rnd_path() for _ in range(160)]
shapes += [RectShape(30, 20), RectShape(30, 20, radius=4), RectShape(40, 10, radii=[0, 3, 5, 1]), EllipseShape(40, 20),
           EllipseShape(5, 5), PolygonShape(12, 10, sides=6), PolygonShape(12, 12, sides=5, star=0.5),
           TextShape("Ciao mondo"), TextShape("Natale 2026")]
for s in shapes[:50]:
    s.apply(QTransform().rotate(rng.uniform(0, 90)).scale(rng.uniform(0.5, 2), rng.choice((1, -1))))
g = GroupShape([rnd_path(), rnd_path(), RectShape(5, 5), EllipseShape(4, 9)])
g.apply(QTransform().rotate(30).scale(2, 1.5))
shapes.append(g)
same_counts, bad_tot, worst_p = 0, [], 0.0
for s in shapes:
    a, b = ops.info_slow([s]), ops.info([s])
    if all(a[k] == b[k] for k in ("open", "closed", "nodes")):
        same_counts += 1
    else:
        bad_tot.append((s.kind, a, b))
    tp, ta = truth([s])
    if tp > 1e-6:
        worst_p = max(worst_p, abs(b["perimeter"] - tp) / tp)
check("A1 aperte, chiuse e nodi uguali al metodo di prima su %d forme di ogni tipo" % len(shapes),
      same_counts == len(shapes), bad_tot[:2])
check("A2 perimetro uguale al vero (spezzata finissima) entro lo 0,05%, anche su curve con anse strette",
      worst_p < 5e-4, worst_p)
for name, s in (("rettangolo arrotondato", RectShape(30, 20, radius=4)), ("ellisse", EllipseShape(40, 20)),
                ("testo", TextShape("Ciao mondo")), ("gruppo ruotato e scalato", g)):
    a, (tp, ta) = ops.info([s]), truth([s])
    check(f"A3 {name}: area uguale al vero entro lo 0,05%", abs(a["area"] - ta) <= 5e-4 * max(ta, 1.0),
          (a["area"], ta))
# casi in cui prima i conti sbagliavano
z = QPainterPath()
z.moveTo(5, 5)
z.cubicTo(20, 0, 20, 20, 5, 5)
loop = ops.info([PathShape(z)])
tt = np.linspace(0, 1, 200001)
bx = (1 - tt) ** 3 * 5 + 3 * (1 - tt) ** 2 * tt * 20 + 3 * (1 - tt) * tt ** 2 * 20 + tt ** 3 * 5
by = (1 - tt) ** 3 * 5 + 3 * (1 - tt) ** 2 * tt * 0 + 3 * (1 - tt) * tt ** 2 * 20 + tt ** 3 * 5
l_ref = float(np.hypot(np.diff(bx), np.diff(by)).sum())
a_ref = abs(float((bx[:-1] * by[1:] - bx[1:] * by[:-1]).sum()) / 2)
check("A4 una sola curva che si chiude su sé stessa: chiusa, con la sua lunghezza e la sua area (prima 0)",
      loop["closed"] == 1 and abs(loop["perimeter"] - l_ref) < 1e-4 * l_ref and abs(loop["area"] - a_ref) < 1e-3,
      (loop, l_ref, a_ref))
z = QPainterPath()
z.moveTo(0, 0)
z.lineTo(10, 0)
z.closeSubpath()
back = ops.info([PathShape(z)])
check("A5 un tratto che va e torna: lungo il doppio (il laser lo percorre due volte), area 0",
      abs(back["perimeter"] - 20.0) < 1e-9 and back["area"] == 0.0 and back["closed"] == 1, back)
z = QPainterPath()
z.moveTo(3, 3)
empty = ops.info([PathShape(z), PathShape(QPainterPath())])
check("A6 tracciato vuoto o con solo l'inizio: niente misure, il nodo dell'inizio contato come prima",
      empty == ops.info_slow([PathShape(z), PathShape(QPainterPath())]), (empty, ops.info_slow([PathShape(z)])))
check("A7 nessuna forma: tutto a zero", ops.info([]) == {"perimeter": 0.0, "area": 0.0, "open": 0, "closed": 0, "nodes": 0})
heavy = []
for k in range(24):
    ox, oy = 10 + (k % 4) * 105, 10 + (k // 4) * 70
    for j in range(16):
        heavy.append(PathShape(blob(ox + 20 + rng.uniform(0, 40), oy + 15 + rng.uniform(0, 40), rng.uniform(2, 12), 150), layer=1))
    heavy.append(PathShape(blob(ox + 50, oy + 33, 45, 60), layer=2))
    heavy.append(PathShape(blob(ox + 50, oy + 55, 8, 120), layer=3))
t0 = time.perf_counter()
slow = ops.info_slow(heavy)
t_slow = time.perf_counter() - t0
t0 = time.perf_counter()
fast = ops.info(heavy)
t_fast = time.perf_counter() - t0
tp, ta = truth(heavy[:18])
part = ops.info(heavy[:18])
check("A8 disegno come quello del rapporto (432 tracciati, 186.000 elementi): stessi conteggi; area entro lo 0,01%; "
      "perimetro uguale al vero entro lo 0,01% (la spezzata a 0,02 mm di prima, su curve così piccole e mosse, "
      "ne perdeva lo 0,4%)", all(slow[k] == fast[k] for k in ("open", "closed", "nodes"))
      and abs(slow["area"] - fast["area"]) < 1e-4 * slow["area"] and abs(part["perimeter"] - tp) < 1e-4 * tp
      and abs(part["area"] - ta) < 1e-4 * ta, (slow, fast, part, tp, ta))
check("A9 …almeno 5 volte più veloce", t_fast * 5 < t_slow, (round(t_slow, 3), round(t_fast, 3)))

# ================================================================== B. elementi dei tracciati ricordati
docmod._ELEMENTS_CACHE.clear()
docmod._ELEMENTS_CACHE_N[0] = 0
pth = heavy[0].qpath
e1 = docmod.path_elements(pth)
e2 = docmod.path_elements(pth)
check("B1 stesso risultato della lettura uno a uno", e1 == docmod._path_elements_slow(pth) and e1 == e2)
check("B2 la lista restituita è sempre nuova (chi la allunga non tocca le altre); il percorso letto una volta sola",
      e1 is not e2 and len(docmod._ELEMENTS_CACHE) == 1)
e1.append([1, 0.0, 0.0])
check("B3 …e una lista modificata da fuori non cambia quelle che vengono dopo", docmod.path_elements(pth) == e2)
moved = QPainterPath(pth)
moved.translate(0.001, 0)
check("B4 un percorso spostato di un millesimo è un altro percorso (mai confusi)",
      docmod.path_elements(moved) != e2 and docmod.path_elements(moved) == docmod._path_elements_slow(moved))
small = QPainterPath()
small.moveTo(0, 0)
small.lineTo(1, 1)
check("B5 tracciati corti: letti come prima, non ricordati", docmod.path_elements(small) == [[0, 0.0, 0.0], [1, 1.0, 1.0]]
      and len(docmod._ELEMENTS_CACHE) == 2)
old_max = docmod._ELEMENTS_CACHE_MAX
docmod._ELEMENTS_CACHE_MAX = 2000
for s in heavy[:30]:
    docmod.path_elements(s.qpath)
check("B6 memoria limitata: oltre il massimo si ricomincia da capo", docmod._ELEMENTS_CACHE_N[0] <= 2000
      and sum(len(v) for v in docmod._ELEMENTS_CACHE.values()) == docmod._ELEMENTS_CACHE_N[0])
docmod._ELEMENTS_CACHE_MAX = old_max
t, x, y = docmod.path_arrays(pth)
ref = np.asarray(docmod._path_elements_slow(pth), float)
check("B7 elementi come matrici numpy: uguali a quelli letti uno a uno (anche tracciati corti e vuoti)",
      np.array_equal(t, ref[:, 0]) and np.array_equal(x, ref[:, 1]) and np.array_equal(y, ref[:, 2])
      and docmod.path_arrays(small)[0].tolist() == [0, 1] and len(docmod.path_arrays(QPainterPath())[0]) == 0)

# ================================================================== la finestra
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1366, 740)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas
vp = cv.viewport()


def snap_points_old(cv_, exclude_ids):
    """Il metodo fino alla 0.20.4 (elemento per elemento), per il confronto."""
    pts, kinds = [], []
    for s in cv_.editor.doc.shapes:
        if s.id in exclude_ids or s.hidden:
            continue
        b = s.bounds()
        for xx, yy, k in ((b.left(), b.top(), "angolo"), (b.right(), b.top(), "angolo"), (b.left(), b.bottom(), "angolo"),
                          (b.right(), b.bottom(), "angolo"), (b.center().x(), b.center().y(), "centro"),
                          (b.center().x(), b.top(), "metà"), (b.center().x(), b.bottom(), "metà"),
                          (b.left(), b.center().y(), "metà"), (b.right(), b.center().y(), "metà")):
            pts.append((xx, yy))
            kinds.append(k)
        if isinstance(s, ImageShape):
            continue
        path = s.path()
        n = path.elementCount()
        if n > 4000:
            continue
        for i in range(n):
            e = path.elementAt(i)
            if e.type in (QPainterPath.ElementType.MoveToElement, QPainterPath.ElementType.LineToElement):
                pts.append((e.x, e.y))
                kinds.append("nodo")
            elif e.type == QPainterPath.ElementType.CurveToElement and i + 2 < n:
                e3 = path.elementAt(i + 2)
                pts.append((e3.x, e3.y))
                kinds.append("nodo")
    return (np.array(pts, float) if pts else np.zeros((0, 2))), kinds


# ================================================================== C. punti dell'aggancio
big = QPainterPath()
big.moveTo(0, 0)
for i in range(1500):
    big.cubicTo(i * 0.1, 3, i * 0.1 + 0.05, -3, i * 0.1 + 0.1, 0)
mix = [RectShape(20, 10), EllipseShape(8, 8), TextShape("Abc"), rnd_path(), PathShape(big), g.clone(), rnd_path()]
mix[3].hidden = True
ed.clear_selection()
ed.doc.shapes.clear()
ed.add(mix, select=False)
app.processEvents()
ok_all = True
for ex in (frozenset(), frozenset([mix[0].id]), frozenset([mix[5].id, mix[6].id])):
    cv._snap_cache = None
    a_new, k_new = cv._snap_points(ex)
    a_old, k_old = snap_points_old(cv, ex)
    ok_all = ok_all and a_new.shape == a_old.shape and np.array_equal(a_new, a_old) and k_new == k_old
check("C1 stessi punti, tipi e ordine del metodo di prima (nascoste, escluse, gruppi, testo, tracciato oltre 4000 "
      "elementi)", ok_all, (a_new.shape, a_old.shape))
cv._snap_cache = None
r1 = cv._snap_points(frozenset())
r2 = cv._snap_points(frozenset())
check("C2 ricordati finché il disegno non cambia", r1[0] is r2[0])
mix[0].apply(QTransform.fromTranslate(5, 0))
ed.changed.emit()
app.processEvents()
r3 = cv._snap_points(frozenset())
check("C3 cambia il disegno: si rifanno, con il punto nuovo", r3[0] is not r1[0]
      and np.array_equal(r3[0], snap_points_old(cv, frozenset())[0]))

# ================================================================== D. aggancio mentre si sposta
box = (10.0, 10.0, 30.0, 20.0)
nodes = [(10 + i * 0.1, 10.0) for i in range(200)]
targets = np.array([(40 + i * 0.01, 10.3) for i in range(800)] + [(30.4, 25.0)], float)
kinds = ["nodo"] * len(targets)
boxes = [(40, 10, 48, 11)]
old_pairs = snapping.MAX_PAIRS
snapping.MAX_PAIRS = 10 ** 12
ref_r = snapping.move(box, nodes, 9.9, 0.0, targets, kinds, boxes, 1.0)
snapping.MAX_PAIRS = old_pairs
new_r = snapping.move(box, nodes, 9.9, 0.0, targets, kinds, boxes, 1.0)
check("D1 poche coppie: risultato identico a prima (anche quale nodo si aggancia)",
      (len(nodes) + 9) * len(targets) <= snapping.MAX_PAIRS and ref_r.how == "punto"
      and (ref_r.dx, ref_r.dy, ref_r.how, ref_r.hint) == (new_r.dx, new_r.dy, new_r.how, new_r.hint),
      ((ref_r.dx, ref_r.dy, ref_r.how), (new_r.dx, new_r.dy, new_r.how)))
nodes_d = [(10 + i * 0.02, 10.0) for i in range(1000)]
dense = np.array([(40 + i * 0.001, 10 + (i % 7) * 0.001) for i in range(5000)], float)
snapping.MAX_PAIRS = 10 ** 12
t0 = time.perf_counter()
full = snapping.move(box, nodes_d, 9.95, 0.0, dense, ["nodo"] * 5000, boxes, 1.0)
t_full = time.perf_counter() - t0
snapping.MAX_PAIRS = old_pairs
t0 = time.perf_counter()
cut = snapping.move(box, nodes_d, 9.95, 0.0, dense, ["nodo"] * 5000, boxes, 1.0)
t_cut = time.perf_counter() - t0
check("D2 troppe coppie (1009 punti × 5000 vicini): si agganciano solo i 9 punti dell'ingombro, e si aggancia lo "
      "stesso", cut.how == "punto" and (cut.dx, cut.dy) != (9.95, 0.0), (cut.how, cut.dx, cut.dy))
check("D3 …molto più in fretta", t_cut * 3 < t_full, (round(t_full, 4), round(t_cut, 4)))
far = snapping.move(box, nodes_d, 0.0, 50.0, dense, ["nodo"] * 5000, boxes, 1.0)
check("D4 lontano da tutto: niente aggancio", far.how is None and (far.dx, far.dy) == (0.0, 50.0))

# ================================================================== E. movimenti misurati
ed.clear_selection()
ed.doc.shapes.clear()
ed.add(heavy[:72], select=False)
app.processEvents()
cv.fit_rect(ed.doc.bounds())
app.processEvents()
perfstats.reset()


def ev(kind, x_, y_, btn=Qt.NoButton, btns=Qt.NoButton):
    p = QPointF(x_, y_)
    app.sendEvent(vp, QMouseEvent(kind, p, vp.mapToGlobal(p), btn, btns, Qt.NoModifier))


orn = heavy[:18]
ed.select(orn)
app.processEvents()
c = cv.to_view(orn[16].bounds().center())
ev(QMouseEvent.Type.MouseMove, c.x() - 3, c.y())
check("E1 passare con il mouse senza tasti non conta", perfstats.DRAG["moves"] == 0)
t0 = time.perf_counter()
ev(QMouseEvent.Type.MouseButtonPress, c.x(), c.y(), Qt.LeftButton, Qt.LeftButton)
for i in range(1, 21):
    ev(QMouseEvent.Type.MouseMove, c.x() + i * 2, c.y() + i, Qt.NoButton, Qt.LeftButton)
    app.processEvents()
ev(QMouseEvent.Type.MouseButtonRelease, c.x() + 40, c.y() + 20, Qt.LeftButton, Qt.NoButton)
app.processEvents()
d = perfstats.DRAG
check("E2 trascinando: 20 movimenti contati, con il tempo dell'aggancio", d["moves"] == 20 and d["snap_sum"] > 0
      and d["max"] >= d["max_snap"] and d["sum"] > 0, dict(d))
check("E3 …e la selezione si è spostata davvero (una sola voce di Annulla)",
      ed.undo_stack and abs(orn[0].bounds().left() - heavy[0].bounds().left()) < 1e-9)
perfstats.note_move(0.25, 0.2)
perfstats.note_paint(0.15)
txt = perfstats.text()
check("E4 nel rapporto: quanti movimenti, quanti lenti, il più lento e di chi la colpa (aggancio), disegni del piano",
      "Movimenti col mouse premuto: 21" in txt and "oltre 0,10 s: 1" in txt and "il più lento 0,25 s (aggancio 0,20 s)"
      in txt and "disegni del piano durante i movimenti: " in txt, txt)
sys_txt = diag.env_text(w)
check("E5 la riga c'è nel riassunto tecnico del rapporto per l'assistenza", "Movimenti col mouse premuto" in sys_txt,
      sys_txt[-300:])
perfstats.reset()
check("E6 senza movimenti la riga non c'è", perfstats.text() == "")
ed.undo()
app.processEvents()

# ================================================================== F. Wi-Fi delle Makerbase


class Pc:
    """Il Wi-Fi del PC, finto (risponde come nmcli)."""

    def __init__(self):
        self.sys = ws.System(run=self.run, platform="linux")
        self.sys.local_ip = lambda: "127.0.0.9"

    def run(self, args, timeout=12, input_text=None):
        a = list(args)
        if a[:5] == ["nmcli", "-t", "-f", "TYPE,STATE", "dev"]:
            return 0, "wifi:connected\nethernet:connected\n"
        if "list" in a:
            return 0, "yes:CasaMia:80:2437 MHz:WPA2\nno:Vicino:30:2462 MHz:WPA2"
        return 0, ""


ctl = w.ctl
type(ctl).WAKE_AFTER_S = 3600
sent = []
ctl.line_sent.connect(sent.append)


def usb(kind, **wifi):
    if ctl.connected:
        ctl.disconnect_port()
        until(lambda: not ctl.connected, 3)
    SimSerial.preset = None
    ctl.connect_port(SIM_PORT)
    ctl.sim.speedup = 50
    wf_ = ctl.sim.wifi_board(kind, **wifi)
    until(lambda: ctl.last_status.get("state") == "Idle" and ctl.board_info and ctl.board_settings, 20)
    app.processEvents()
    sent.clear()
    return wf_


def wizard():
    d_ = dw.WifiWizard(w, system=Pc().sys)
    d_.start()
    return d_


def to_state(d_, *states, t=40.0):
    until(lambda: d_.state in states, t)
    return d_.state in states


def run_net(d_, ssid="CasaMia", pwd="passwordgiusta"):
    if d_.state == "B":
        d_.press("net")
    to_state(d_, "net")
    until(lambda: d_.list.count() > 0, 20)
    d_.ssid.setText(ssid)
    d_.pwd.setText(pwd)
    d_.press("write")
    return time.time()


def plain(d_):
    return re.sub(r"<[^>]+>", "", d_.title.text() + " " + d_.body.text())


check("F0 riconoscimento: le MKS sono «Makerbase senza interruttore», il Mecpow THMG e le Longer no",
      ws.is_mks_like(["[VER:1.1h.2023102303:]", "[MSG:Using machine:MKS DLC32]"])
      and not ws.has_wifi_switch(["[MSG:Using machine:MKS DLC32]"]) and ws.has_wifi_switch(["[PRODUCER:THMG LS WIFI V1.1]"]))

# F1: la rete non si vede (come DBAF: modalità già STA, rete propria subito, nessun messaggio)
wf = usb("mks", silent=True, mode="STA", ap="MECPOW_SIM", nets={"CasaMia": "passwordgiusta"})
d1 = wizard()
to_state(d1, "B")
run_net(d1, ssid="Casa5G")
ok1 = to_state(d1, "not_found", "not_tried", "failed", "ok", "unknown")
after = sent[sent.index("[ESP444]RESTART"):] if "[ESP444]RESTART" in sent else []
check("F1 MKS che non trova la rete: dopo la rete propria chiede la modalità («[ESP110]») e dice «Il laser non trova "
      "la rete»", ok1 and d1.state == "not_found" and "[ESP110]" in after and wf["boots"] == 1,
      (d1.state, after[:6]))
body = plain(d1)
check("F2 …con le cause giuste in testa (5 GHz, nome scritto diverso, segnale) e non «la scheda non ha provato»",
      "Casa5G" in body and "5 GHz" in body and "maiuscole" in body and "debole" in body
      and "non ha provato" not in body, body[:300])
check("F3 …il registro della prova viene salvato (stato finale)", "not_found" in dw.END_STATES)
d1.close()

# F4: scheda che al riavvio torna sempre alla sua rete (modalità non tenuta)
wf = usb("mks", silent=True, keeps_mode=False, nets={"CasaMia": "passwordgiusta"})
d2 = wizard()
to_state(d2, "B")
run_net(d2)
ok2 = to_state(d2, "not_found", "not_tried", "failed", "ok", "unknown")
check("F4 MKS che non tiene «rete di casa» ([ESP110] = AP dopo il riavvio): «La scheda non ha provato a "
      "collegarsi», come prima", ok2 and d2.state == "not_tried", d2.state)
d2.close()

# F5: password sbagliata: il tentativo dura (sulla scheda vera fino a 20 s) e poi rete propria
wf = usb("mks", silent=True, delay=0.8, nets={"CasaMia": "passwordgiusta"})
d3 = wizard()
to_state(d3, "B")
run_net(d3, pwd="sbagliata123")
ok3 = to_state(d3, "not_found", "not_tried", "failed", "ok", "unknown", t=60)
check("F5 MKS con la password sbagliata (rete propria dopo un tentativo lungo): «Il laser non è entrato nella rete»",
      ok3 and d3.state == "failed", d3.state)
d3.close()

# F6: riuscito senza messaggi di collegamento: servizi partiti -> chiede l'indirizzo
import socket  # noqa: E402
import threading  # noqa: E402


class Board(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self.start()

    def run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(c,), daemon=True).start()

    def serve(self, c):
        buf = b""
        try:
            while True:
                data = c.recv(1024)
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip().replace(b"?", b"")
                    if line.upper() == b"$I":
                        c.sendall(b"[VER:1.1h.2023102303:]\r\n[MSG:Using machine:MKS DLC32]\r\nok\r\n")
                    else:
                        c.sendall(b"ok\r\n")
        except OSError:
            return


L = Board()
wf = usb("mks", silent=True, nets={"CasaMia": "passwordgiusta"}, join_ip="127.0.0.1", telnet=L.port)
d4 = wizard()
to_state(d4, "B")
run_net(d4)
ok4 = to_state(d4, "ok", "not_found", "not_tried", "failed", "unknown", "no_port")
check("F6 MKS che entra in rete senza dirlo (solo «TELNET Started»): «Collegamento Wi-Fi pronto»",
      ok4 and d4.state == "ok" and d4.result == f"tcp://127.0.0.1:{L.port}", (d4.state, d4.result))
d4.close()

# F7: Mecpow THMG (con l'interruttore) che non tiene la modalità: invariato, nessuna domanda in più
wf = usb("thmg", nets={"CasaMia": "passwordgiusta"}, join_ip="127.0.0.1", telnet=L.port, reject=("$wifi",))
d5 = wizard()
to_state(d5, "B")
run_net(d5)
ok5 = to_state(d5, "not_tried", "not_found", "failed", "ok")
after5 = sent[sent.index("[ESP444]RESTART"):] if "[ESP444]RESTART" in sent else []
check("F7 Mecpow THMG: «non ha provato» come nella 0.19.1, senza chiedere la modalità dopo",
      ok5 and d5.state == "not_tried" and "[ESP110]" not in after5, (d5.state, after5[:5]))
d5.close()
if ctl.connected:
    ctl.disconnect_port()
    until(lambda: not ctl.connected, 3)

# ================================================================== G. traduzioni
keys = set()
srcf = open(os.path.join(ROOT, "freelasercut", "ui", "dialogs_wifi.py"), encoding="utf-8").read()
for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', srcf):
    try:
        k = "".join(ast.literal_eval(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
    except (SyntaxError, ValueError):
        continue
    if any(t_ in k for t_ in ("non trova la rete", "ha tenuto nome e password", "non è scritto proprio uguale")):
        keys.add(k)
check("G1 testi nuovi trovati nel codice (3)", len(keys) == 3, sorted(k[:40] for k in keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k[:40] for k in keys if not loc.get(k)]
    bad = [k[:40] for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    check(f"G2 traduzioni {lang}: tutti i testi, con gli stessi segnaposto", not miss and not bad, (miss, bad))

check("nessun errore nascosto nei comandi dell'interfaccia", not hidden, [repr(e)[:160] for e in hidden[:3]])
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati ({TAG})")

from _uscita import esci  # noqa: E402

esci(code_)
