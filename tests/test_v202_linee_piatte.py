# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.2: le linee perfettamente orizzontali o verticali (e i punti) non restano più fuori dalla selezione.

Prova sul progetto di Ale (15/11/2026, 818 forme): selezionando tutto col rettangolo e spostando, 40 linee restavano
ferme, tutte con larghezza o altezza 0. Causa: QRectF.contains / intersects dicono sempre di no per un riquadro senza
area e QRectF.united butta via i punti. Ora tutti i confronti passano da geom.rect_union / rect_overlaps / rect_inside.

Matrice dei casi:
1 funzioni dei riquadri: linee orizzontali, verticali, punti, coordinate negative, bordi che si toccano, riquadro
  vuoto, valori non finiti;
2 rettangolo di selezione «finestra» (da sinistra a destra) e «incrocio» (da destra a sinistra): linee piatte dentro,
  a cavallo del bordo, fuori; punto; forme normali; anche col trascinamento vero del mouse sul piano;
3 dopo la selezione: sposta, ruota, scala, duplica → si muove tutto (controllo numerico di ogni forma); annulla;
4 ingombro della selezione, del documento, del disegno di Stampa e taglia e del G-code con le linee piatte ai bordi;
5 Banco: trascinamento vero sul piano.
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
BANCO = os.environ["FLC_UI"] == "banco"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QPainterPath, QTransform  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core import geom, ops, print_cut  # noqa: E402
from freelasercut.core.document import PathShape, RectShape  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def line(x0, y0, x1, y1, layer=0):
    p = QPainterPath(QPointF(x0, y0))
    p.lineTo(QPointF(x1, y1))
    return PathShape(p, layer=layer)


def rect(x, y, w, h, layer=0):
    s = RectShape(w, h, layer=layer)
    b = s.bounds()
    s.apply(QTransform.fromTranslate(x - b.left(), y - b.top()))
    return s


def box(s):
    b = s.bounds()
    return (round(b.left(), 6), round(b.top(), 6), round(b.right(), 6), round(b.bottom(), 6))


if not BANCO:
    # ================================================================== 1. funzioni dei riquadri
    h = QRectF(10, 20, 30, 0)  # orizzontale
    v = QRectF(50, 5, 0, 40)  # verticale
    p = QRectF(-7, -3, 0, 0)  # punto
    big = QRectF(-10, -10, 100, 100)
    check("Qt da solo sbaglia (premessa della correzione): contains e intersects di una linea piatta dicono di no",
          not big.contains(h) and not big.intersects(v))
    check("dentro: linea orizzontale, verticale e punto dentro un rettangolo",
          geom.rect_inside(h, big) and geom.rect_inside(v, big) and geom.rect_inside(p, big))
    check("dentro: una linea piatta che esce dal rettangolo non è dentro",
          not geom.rect_inside(QRectF(80, 0, 30, 0), big) and not geom.rect_inside(QRectF(0, 85, 0, 10), big))
    check("si toccano: linea piatta a cavallo del bordo, sul bordo esatto, fuori",
          geom.rect_overlaps(QRectF(80, 0, 30, 0), big) and geom.rect_overlaps(QRectF(90, 0, 0, 5), big)
          and not geom.rect_overlaps(QRectF(91, 0, 0, 5), big))
    check("si toccano: due linee piatte che si incrociano (orizzontale e verticale)",
          geom.rect_overlaps(QRectF(0, 10, 20, 0), QRectF(10, 0, 0, 20))
          and not geom.rect_overlaps(QRectF(0, 10, 20, 0), QRectF(30, 0, 0, 20)))
    u = geom.rect_union([h, v, p])
    check("ingombro di linee piatte e di un punto: il punto non si perde",
          (u.left(), u.top(), u.right(), u.bottom()) == (-7, -3, 50, 45), (u.left(), u.top(), u.right(), u.bottom()))
    check("ingombro di nessun riquadro: vuoto (come prima)", geom.rect_union([]).isNull())
    check("ingombro di un riquadro solo: lo stesso", geom.rect_union([QRectF(1, 2, 3, 4)]) == QRectF(1, 2, 3, 4))
    check("riquadri con valori non finiti: ignorati, mai un ingombro rovinato",
          geom.rect_union([QRectF(float("nan"), 0, 1, 1), QRectF(1, 1, 2, 2)]) == QRectF(1, 1, 2, 2))
    check("rettangoli scritti al contrario (larghezza negativa): letti giusti",
          geom.rect_inside(QRectF(10, 10, -5, 0), QRectF(0, 0, 20, 20)))

# ================================================================== 2. selezione col rettangolo
w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas


def fresh():
    shapes = [
        rect(20, 20, 40, 30),  # 0 normale
        line(70, 25, 130, 25),  # 1 orizzontale
        line(140, 15, 140, 75),  # 2 verticale
        line(30, 60, 90, 120),  # 3 obliqua
        line(100, 90, 100, 90),  # 4 punto (lunghezza 0)
        line(150, 100, 250, 100),  # 5 orizzontale a cavallo del bordo del rettangolo di prova
        line(300, 10, 300, 40),  # 6 verticale fuori
    ]
    ed.doc.shapes.clear()
    ed.selection = []
    ed.add(shapes, select=False)
    ed.selection = []
    app.processEvents()
    return shapes


S = fresh()
win = QRectF(10, 10, 160, 120)  # tutto meno la 5 (a metà) e la 6 (fuori)
inside = cv.shapes_in_rect(win, crossing=False)
check("finestra: dentro la rettangolare, le linee piatte (orizzontale e verticale), l'obliqua e il punto",
      [S.index(s) for s in inside] == [0, 1, 2, 3, 4], [S.index(s) for s in inside])
cross = cv.shapes_in_rect(win, crossing=True)
check("incrocio: in più la linea orizzontale a cavallo del bordo; fuori quella lontana",
      [S.index(s) for s in cross] == [0, 1, 2, 3, 4, 5], [S.index(s) for s in cross])
allr = cv.shapes_in_rect(QRectF(-5, -5, 400, 200), crossing=False)
check("rettangolo attorno a tutto: tutte e 7 le forme (prima mancavano le linee piatte e il punto)", len(allr) == 7,
      len(allr))
check("incrocio su una linea piatta sola, toccata a metà", cv.shapes_in_rect(QRectF(95, 20, 10, 10), True) == [S[1]])
check("finestra stretta che contiene solo la linea verticale", cv.shapes_in_rect(QRectF(139, 10, 2, 70), False) == [S[2]])


def drag(a_bed, b_bed):
    """Trascinamento vero col mouse sul piano (rettangolo di selezione), da a a b in mm."""
    w.set_tool("select") if hasattr(w, "set_tool") else None
    vp = cv.viewport()
    a = cv.to_view(QPointF(*a_bed))
    b = cv.to_view(QPointF(*b_bed))
    a, b = QPoint(int(a.x()), int(a.y())), QPoint(int(b.x()), int(b.y()))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, a)
    for t in (0.25, 0.5, 0.75, 1.0):
        QTest.mouseMove(vp, QPoint(int(a.x() + (b.x() - a.x()) * t), int(a.y() + (b.y() - a.y()) * t)))
        app.processEvents()
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, b)
    app.processEvents()


cv.fit() if hasattr(cv, "fit") else None
app.processEvents()
S = fresh()
vis = cv.mapToScene(cv.viewport().rect()).boundingRect() if hasattr(cv, "mapToScene") else None
drag((-3, -3), (260, 140))
check("trascinamento vero col mouse attorno a tutto: selezionate anche le linee piatte e il punto",
      sorted(S.index(s) for s in ed.selection) == [0, 1, 2, 3, 4, 5], sorted(S.index(s) for s in ed.selection))

# ================================================================== 3. dopo la selezione si muove tutto
S = fresh()
ed.select(cv.shapes_in_rect(QRectF(-5, -5, 400, 200), crossing=False))
before = [box(s) for s in S]
ed.transform(QTransform.fromTranslate(10, -4), "Sposta", shapes=ed.editable())
after = [box(s) for s in S]
moved = all(abs(a[0] - b[0] - 10) < 1e-6 and abs(a[2] - b[2] - 10) < 1e-6 and abs(a[1] - b[1] + 4) < 1e-6
            for a, b in zip(after, before))
check("sposta di 10 mm in X e −4 in Y: tutte e 7 le forme spostate della stessa misura", moved,
      [(b, a) for a, b in zip(after, before) if not (abs(a[0] - b[0] - 10) < 1e-6)])
ed.undo()
app.processEvents()
check("annulla: tutte tornano al loro posto", [box(s) for s in ed.doc.shapes] == before)

S = fresh()
ed.select(cv.shapes_in_rect(QRectF(-5, -5, 400, 200), crossing=False))
bb = ed.selection_bounds()
c = bb.center()
rot = QTransform()
rot.rotate(90)
ed.transform(ops.about(rot, c.x(), c.y()), "Ruota", shapes=ed.editable())
hb = S[1].bounds()
vb = S[2].bounds()
check("ruota di 90°: la linea orizzontale diventa verticale e la verticale orizzontale",
      abs(hb.width()) < 1e-6 and abs(hb.height() - 60) < 1e-6 and abs(vb.height()) < 1e-6 and abs(vb.width() - 60) < 1e-6,
      (hb, vb))
nb = ed.selection_bounds()
check("ruota: l'ingombro della selezione gira attorno al suo centro (larghezza e altezza scambiate)",
      abs(nb.width() - bb.height()) < 1e-6 and abs(nb.height() - bb.width()) < 1e-6
      and abs(nb.center().x() - c.x()) < 1e-6 and abs(nb.center().y() - c.y()) < 1e-6)

S = fresh()
ed.select(cv.shapes_in_rect(QRectF(-5, -5, 400, 200), crossing=False))
bb = ed.selection_bounds()
ed.transform(ops.about(QTransform.fromScale(2, 2), bb.left(), bb.top()), "Scala", shapes=ed.editable())
check("scala al 200% dall'angolo: la linea orizzontale da 60 diventa 120 mm, il punto si sposta col disegno",
      abs(S[1].bounds().width() - 120) < 1e-6
      and abs(S[4].bounds().left() - (bb.left() + 2 * (100 - bb.left()))) < 1e-6)

S = fresh()
ed.select(cv.shapes_in_rect(QRectF(-5, -5, 400, 200), crossing=False))
n0 = len(ed.doc.shapes)
ed.duplicate()
app.processEvents()
check("duplica: si duplicano tutte e 7 (anche le linee piatte e il punto)", len(ed.doc.shapes) == n0 + 7,
      len(ed.doc.shapes) - n0)

# ================================================================== 4. ingombri
S = fresh()
db = ed.doc.bounds()
check("ingombro del documento: dalla linea verticale più a destra (X 300) al punto e alle linee più in alto",
      abs(db.right() - 300) < 1e-6 and abs(db.left() - 20) < 1e-6 and abs(db.bottom() - 120) < 1e-6, db)
ed.doc.shapes.clear()
ed.add([line(0, 0, 50, 0), line(80, 0, 80, 0)], select=False)
ub = ops.union_bounds(ed.doc.shapes)
check("ingombro di una linea orizzontale e di un punto più a destra: il punto conta", abs(ub.right() - 80) < 1e-6, ub)
db = print_cut.design_bounds(ed.doc)
check("Stampa e taglia: l'ingombro del disegno conta il punto e la linea piatta", abs(db.right() - 80) < 1e-6
      and abs(db.left()) < 1e-6, db)

from freelasercut.core import gcode  # noqa: E402

ed.doc.shapes.clear()
ed.doc.layer(0).output = True
ed.doc.layer(0).mode = "line"
ed.add([line(10, 10, 60, 10), line(70, 5, 70, 45)], select=False)
job = gcode.generate(ed.doc, w.profile, gcode.JobOptions())
text = "\n".join(job.lines) if hasattr(job, "lines") else str(getattr(job, "gcode", ""))
check("G-code di due linee piatte: escono tutte e due (X60 e Y45 nel testo)", "X60" in text and "Y45" in text,
      text[:300])

print(f"\n{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
