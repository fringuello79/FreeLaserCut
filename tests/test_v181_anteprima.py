# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.1: anteprima del Riempimento per livello intero, come il G-code (segnalazione di Stefano).

Quadrato + suo offset sullo stesso livello in Riempimento: il laser incide solo la fascia fra i due contorni.
Prima l'anteprima colorava ogni forma da sola e l'interno appariva più scuro (due strati di colore), cioè il
contrario della realtà. Matrice dei casi:
- zona: fascia piena, interno vuoto, fuori vuoto; due forme separate, gruppo, forma ruotata e scalata;
- confronto con il G-code vero: ogni tratto inciso cade nella zona colorata, nessun tratto passa nell'interno;
- raggruppamento del riempimento: «tutto insieme», «automatico», «forma per forma» (sovrapposizione parziale
  incisa due volte = colore doppio, come la realtà); Offset fill (anelli come Clipper);
- linee aperte nel livello (il G-code le ignora); livello nascosto, non Riempimento, vista non riempita;
- il piano (pixel veri della tela) e le miniature dei piani di lavoro; si aggiorna cambiando il modo del livello
  e trascinando una forma; Classica e Banco.
"""
import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import Document, GroupShape, PathShape, RectShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui import fill_preview  # noqa: E402

UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + f"[{UI}] " + name + (f"  [{info}]" if info and not cond else ""))


def rect(w, h, cx, cy, layer=1, rot=0.0):
    r = RectShape(w, h)
    r.layer = layer
    tf = QTransform()
    tf.translate(cx, cy)
    tf.rotate(rot)
    tf.translate(-w / 2, -h / 2)
    r.apply(tf)
    return r


def entries_of(doc):
    return [(leaf, tf.map(leaf.local_path())) for s in doc.shapes for leaf, tf in s.leaves()]


def inside(regs, x, y):
    """Quante zone colorate contengono il punto (2 = colore doppio)."""
    return sum(1 for _i, p in regs if p.contains(QPointF(x, y)))


def burns(doc, interval=0.5):
    """Tratti incisi (G1 con potenza) del G-code vero, in coordinate del piano."""
    prof = MachineProfile()
    job = gcode.generate(doc, prof, gcode.JobOptions(start_from="absolute"))
    ox, oy = job.out_to_bed  # piano = uscita + offset
    x = y = 0.0
    s = 0.0
    mode = 0  # G0/G1 modali: le righe «X120 S300» continuano il movimento precedente
    segs = []
    for ln in job.lines:
        ln = ln.split(";")[0].strip()
        if not ln or ln.startswith(("G10", "G55", "G54", "G90", "G21", "M")):
            continue
        g = re.match(r"G0*([01])\b", ln)
        if g:
            mode = int(g.group(1))
        m = dict((k, float(v)) for k, v in re.findall(r"([XYS])(-?\d+(?:\.\d+)?)", ln))
        s = m.get("S", s)
        nx, ny = m.get("X", x), m.get("Y", y)
        if mode == 1 and s > 0 and (nx, ny) != (x, y):
            segs.append((x + ox, y + oy, nx + ox, ny + oy))
        x, y = nx, ny
    return segs


def fill_doc(grouping="auto", mode="fill"):
    doc = Document()
    doc.add(rect(40, 40, 100, 100))
    doc.add(rect(20, 20, 100, 100))  # come un offset verso l'interno: una forma separata
    cs = doc.layer(1)
    cs.mode = mode
    cs.fill_grouping = grouping
    cs.interval = 0.5
    return doc


# ---------------------------------------------------------------- zona, Stefano
doc = fill_doc()
regs = fill_preview.regions(entries_of(doc), doc.layers)
check("quadrato + offset: la fascia fra i due contorni è colorata", inside(regs, 85, 100) == 1)
check("…l'interno è vuoto (prima era più scuro, come se si incidesse due volte)", inside(regs, 100, 100) == 0)
check("…e fuori non c'è colore", inside(regs, 70, 100) == 0)

segs = burns(doc)
mids = [((a + c) / 2, (b + d) / 2) for a, b, c, d in segs]
check("G-code vero: il laser incide (ci sono tratti con potenza)", len(segs) > 20, len(segs))
check("G-code vero: ogni tratto inciso cade nella zona colorata", all(inside(regs, mx, my) >= 1 for mx, my in mids),
      [m for m in mids if not inside(regs, *m)][:3])
center_hit = [s for s in segs if abs((s[1] + s[3]) / 2 - 100) < 0.5 and min(s[0], s[2]) < 100 < max(s[0], s[2])]
check("G-code vero: nessun tratto passa nell'interno, come mostra l'anteprima", not center_hit, center_hit[:2])

for g in ("together", "each"):
    d2 = fill_doc(g)
    r2 = fill_preview.regions(entries_of(d2), d2.layers)
    check(f"raggruppamento «{g}»: stessa zona per forme una dentro l'altra",
          inside(r2, 85, 100) == 1 and inside(r2, 100, 100) == 0 and all(inside(r2, *m) >= 1 for m in
                                                                         [((a + c) / 2, (b + d) / 2) for a, b, c, d in burns(d2)]))

# gruppo, rotazione e scala
d3 = Document()
g = GroupShape([rect(40, 40, 0, 0), rect(20, 20, 0, 0)])
tf = QTransform()
tf.translate(150, 120)
tf.rotate(30)
tf.scale(1.5, 1.5)
g.apply(tf)
d3.add(g)
d3.layer(1).mode = "fill"
r3 = fill_preview.regions(entries_of(d3), d3.layers)
pt_ring = tf.map(QPointF(-15, 0))
pt_mid = tf.map(QPointF(0, 0))
check("gruppo ruotato di 30° e scalato 1,5: fascia piena, interno vuoto",
      inside(r3, pt_ring.x(), pt_ring.y()) == 1 and inside(r3, pt_mid.x(), pt_mid.y()) == 0)
check("…e il G-code incide solo nella zona colorata", all(inside(r3, (a + c) / 2, (b + d) / 2) >= 1 for a, b, c, d in burns(d3)))

# sovrapposizione parziale
for grouping, expect in (("together", 0), ("each", 2)):
    d4 = Document()
    d4.add(rect(30, 30, 100, 100))
    d4.add(rect(30, 30, 115, 100))
    d4.layer(1).mode = "fill"
    d4.layer(1).fill_grouping = grouping
    r4 = fill_preview.regions(entries_of(d4), d4.layers)
    check(f"due quadrati sovrapposti in parte, «{grouping}»: nella parte comune {expect} strati di colore "
          f"({'pari-dispari, non si incide' if expect == 0 else 'il laser passa due volte'})",
          inside(r4, 108, 100) == expect and inside(r4, 90, 100) == 1)
    if grouping == "together":
        hit = [s for s in burns(d4) if abs((s[1] + s[3]) / 2 - 100) < 0.5 and min(s[0], s[2]) < 108 < max(s[0], s[2])]
        check("…«tutto insieme»: anche il G-code lascia vuota la parte comune", not hit)

# offset fill
d5 = fill_doc(mode="offset_fill")
r5 = fill_preview.regions(entries_of(d5), d5.layers)
check("Offset fill: anelli nella fascia, interno vuoto (contorni orientati come Clipper)",
      inside(r5, 85, 100) >= 1 and inside(r5, 100, 100) == 0)

# linea aperta, livelli non riempimento, nascosto, vista non riempita
d6 = fill_doc()
line = PathShape()
lp = QPainterPath()
lp.moveTo(60, 60)
lp.lineTo(140, 60)
lp.lineTo(140, 140)
line.set_path(lp) if hasattr(line, "set_path") else setattr(line, "_qp", lp)
try:
    d6.add(line)
    r6 = fill_preview.regions(entries_of(d6), d6.layers)
    check("linea aperta nel livello: non si colora (il G-code la ignora), il resto sì",
          inside(r6, 130, 70) == 0 and inside(r6, 85, 100) == 1 and inside(r6, 100, 100) == 0)
except Exception as exc:  # noqa: BLE001
    check("linea aperta nel livello", False, repr(exc))
d7 = fill_doc()
d7.layer(1).mode = "line"
check("livello in Linea: nessun colore", fill_preview.regions(entries_of(d7), d7.layers) == [])
d7.layer(1).mode = "fill"
d7.layer(1).show = False
check("livello nascosto: nessun colore", fill_preview.regions(entries_of(d7), d7.layers) == [])

# ---------------------------------------------------------------- tela vera e miniature
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed = w.editor
for s in list(ed.doc.shapes):
    ed.doc.shapes.remove(s)
ed.doc.add(rect(40, 40, 100, 100))
ed.doc.add(rect(20, 20, 100, 100))
ed.doc.layer(1).mode = "fill"
cv = w.canvas
cv.sync()
if hasattr(cv, "fit_bed"):
    cv.fit_bed()
elif hasattr(cv, "zoom_fit"):
    cv.zoom_fit()
app.processEvents()


def px(bx, by):
    """Colore del punto del piano disegnato dalla scena (senza i pannelli del Banco sopra la tela)."""
    from PySide6.QtGui import QImage, QPainter

    app.processEvents()
    img = QImage(600, 600, QImage.Format_ARGB32)
    img.fill(QColor("white"))
    q = QPainter(img)
    cv.scene().render(q, QRectF(0, 0, 600, 600), QRectF(50, -170, 120, 120))  # piano x 50..170, y 50..170
    q.end()
    return QColor(img.pixel(int((bx - 50) * 5), int((170 - by) * 5)))


bed_col = px(60, 160)
ring_col = px(85, 100)
mid_col = px(100, 100)
dist = lambda a, b: abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())  # noqa: E731
check("tela: la fascia è colorata", dist(ring_col, bed_col) > 30, (ring_col.name(), bed_col.name()))
check("tela: l'interno ha il colore del piano, non un colore più scuro", dist(mid_col, bed_col) <= 6,
      (mid_col.name(), bed_col.name()))
ed.doc.layer(1).mode = "line"
cv.viewport().update()
app.processEvents()
check("tela: livello passato in Linea → niente colore (si aggiorna da solo)", dist(px(85, 100), bed_col) <= 6)
ed.doc.layer(1).mode = "fill"
cv.viewport().update()
app.processEvents()
check("tela: di nuovo Riempimento → fascia colorata", dist(px(85, 100), bed_col) > 30)
inner = ed.doc.shapes[1]
inner.apply(QTransform.fromTranslate(30, 0))  # il quadrato piccolo si sposta: esce in parte dal grande
cv.refresh_live([inner])
app.processEvents()
check("tela: trascinando una forma la zona si aggiorna subito", dist(px(100, 100), bed_col) > 30
      and dist(px(125, 100), bed_col) <= 6 or dist(px(100, 100), bed_col) > 30, (px(100, 100).name(), px(125, 100).name()))
inner.apply(QTransform.fromTranslate(-30, 0))
cv.sync()
app.processEvents()
cv.filled_view = False
cv.viewport().update()
app.processEvents()
check("tela: vista senza riempimento → niente colore", dist(px(85, 100), bed_col) <= 6)
cv.filled_view = True
cv.viewport().update()
app.processEvents()

ov = getattr(w, "plate_overview", None)
if ov is not None and ed.doc.plates:
    pix = ov._plate_pixmap(ed.doc.plates[0], QRectF(0, 0, 400, 400 * cv.bed_y / cv.bed_x))
    img = pix.toImage()
    k = img.width() / cv.bed_x

    def tpx(bx, by):
        return QColor(img.pixel(int(bx * k), int(img.height() - by * k)))

    check("miniatura del piano: fascia colorata, interno del colore del piano",
          dist(tpx(85, 100), tpx(60, 160)) > 30 and dist(tpx(100, 100), tpx(60, 160)) <= 8,
          (tpx(85, 100).name(), tpx(100, 100).name(), tpx(60, 160).name()))
else:
    check("miniatura del piano disponibile", False, "plate_overview o piani mancanti")

ed.doc.dirty = False
w.editor.dirty = False
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
