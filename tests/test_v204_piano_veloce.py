# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.4: il piano non «scatta» più con i disegni complessi (rapporti FLC-20261115-2256-E2B7 e -2257-60F1: SVG
importato, schermo grande, «scatta mentre lavoro»).

Prima ogni movimento del mouse ridisegnava tutte le forme, le zone riempite e il contorno della selezione. Ora le
forme e la selezione stanno in due «immagini pronte» (ui/canvas.py: PlaneLayer, _plane_pixmap, _selection_pixmap)
che si rifanno solo quando cambiano disegno, livelli, selezione o vista.

Matrice dei casi:
A  l'immagine pronta è uguale, pixel per pixel, al disegno diretto di prima: forme di ogni tipo, livelli (linea,
   riempimento, offset, nascosto, senza uscita, livello strumento), foto, foto del piano sotto, selezione singola;
B  dopo OGNI modifica il piano mostra il disegno nuovo (mai un'immagine vecchia): sposta, annulla, ripeti, elimina,
   aggiungi, livello che cambia modo / si nasconde, vista riempita, cambio di livello, raggruppa, separa, cambio
   di piano di lavoro, documento nuovo, zoom, spostamento della vista, finestra che cambia misura;
C  l'immagine pronta si usa davvero: passare con il mouse, disegnare il rettangolo di selezione, cambiare selezione
   non ridisegnano le forme (contatore dei disegni veri);
D  disegni pesanti: mentre si trascina / si sposta la vista / si usa la rotella si vede l'immagine di prima portata
   al posto giusto (conti sulla trasformazione), quella vera arriva da ferma e al rilascio; le fotografie della
   vista sono sempre vere; con un disegno leggero non c'è mai un'immagine provvisoria;
E  clic sulle forme di un gruppo: stesso risultato di prima (confronto con il metodo vecchio su una griglia di punti);
F  elementi dei tracciati letti in blocco = letti uno a uno; linee aperte riconosciute come prima;
G  tantissimi punti: contorni e selezione si vedono ancora; ingombro della selezione ricordato e sempre giusto;
H  l'immagine dell'intera finestra (rapporto per l'assistenza) mostra ancora le forme; interruttore di sicurezza.
Uso: python tests/test_v204_piano_veloce.py [classica|banco] [scala125]
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
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ.pop("FLC_NO_PLANE_CACHE", None)
if "scala125" in sys.argv:  # schermo al 125%, come quello dei rapporti
    os.environ["QT_SCALE_FACTOR"] = "1.25"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainterPath, QPainterPathStroker, QTransform, QWheelEvent
from PySide6.QtWidgets import QApplication

app = QApplication([])
from freelasercut.core import document as docmod
from freelasercut.core.document import (
    Document, EllipseShape, GroupShape, ImageShape, PathShape, PolygonShape, RectShape, TextShape,
)
from freelasercut.theme import C
from freelasercut.ui import canvas as cm
from freelasercut.ui import fill_preview
from freelasercut.ui.main_window import MainWindow

results = []
TAG = os.environ["FLC_UI"] + (" 125%" if "scala125" in sys.argv else "")


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas
vp = cv.viewport()
SLOW0, IDLE0 = cm.PLANE_SLOW_S, cm.PLANE_IDLE_MS
cm.PLANE_SLOW_S = 1e9  # di norma, in queste prove, nessuna immagine provvisoria (la parte D la accende apposta)


def at(s, x, y):
    b = s.bounds()
    s.apply(QTransform.fromTranslate(x - b.left(), y - b.top()))
    return s


def line(x0, y0, x1, y1, layer=1):
    p = QPainterPath()
    p.moveTo(x0, y0)
    p.lineTo(x1, y1)
    return PathShape(p, layer=layer)


def wave(x, y, layer=1, closed=False):
    p = QPainterPath()
    p.moveTo(x, y)
    p.cubicTo(x + 10, y + 30, x + 30, y - 30, x + 40, y)
    p.quadTo(x + 50, y + 20, x + 60, y)
    if closed:
        p.lineTo(x + 30, y - 25)
        p.closeSubpath()
    return PathShape(p, layer=layer)


def fresh(shapes, sel=()):
    ed.clear_selection()
    ed.doc.shapes.clear()
    ed.add(list(shapes), select=False)
    ed.select(list(sel))
    app.processEvents()


def grab():
    """Fotografia della vista (sempre l'immagine vera) come matrice h×w×4."""
    img = vp.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    a = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
    return a[:, :img.width()].astype(np.int16)


def screen():
    """Come grab(), ma prima la vista si ridisegna come sullo schermo (le immagini pronte restano quelle)."""
    vp.update()
    app.processEvents()
    return grab()


def direct():
    """Il piano disegnato come prima della 0.20.4 (forma per forma, niente immagini pronte)."""
    cv.plane_cache = False
    try:
        return grab()
    finally:
        cv.plane_cache = True


def diff(a, b):
    d = np.abs(a - b).max(axis=2)
    return int(d.max()), int((d > 4).sum())  # (differenza massima, pixel diversi di più di 4 su 255)


def same(name, tol=8, allow=3):
    """Schermo (con le immagini pronte) = disegno diretto, a meno di arrotondamenti: le forme passano da un foglio
    trasparente invece di andare dritte sul piano, e dove più strati trasparenti si sommano il conto può cambiare
    di poche unità su 255 in qualche pixel. Un'immagine vecchia o sbagliata dà centinaia di pixel molto diversi."""
    a, b = screen(), direct()
    mx, n = diff(a, b)
    check(f"{TAG}: {name}", mx <= tol and n <= allow, f"differenza massima {mx}, pixel diversi {n}")
    return a


def view_px(x, y):
    v = cv.bed_to_view_tf().map(QPointF(x, y))
    dpr = vp.devicePixelRatioF()
    return int(round(v.x() * dpr)), int(round(v.y() * dpr))


def near_color(img, x, y, color, r=2, tol=150):
    """Attorno al punto del piano (x, y) c'è un pixel del colore dato?"""
    px, py = view_px(x, y)
    c = QColor(color)
    box = img[max(py - r, 0):py + r + 1, max(px - r, 0):px + r + 1, :3]
    return bool((np.abs(box - np.array([c.red(), c.green(), c.blue()])).sum(axis=2) < tol).any())


def ev(kind, pos, btn=Qt.NoButton, btns=Qt.NoButton, mods=Qt.NoModifier):
    p = QPointF(*pos)
    app.sendEvent(vp, QMouseEvent(kind, p, vp.mapToGlobal(p), btn, btns, mods))


def wheel(pos, delta):
    p = QPointF(*pos)
    app.sendEvent(vp, QWheelEvent(p, vp.mapToGlobal(p), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                                  Qt.NoScrollPhase, False))


def vpt(x, y):
    v = cv.to_view(QPointF(x, y))
    return (v.x(), v.y())


def settle(ms):
    t = time.time()
    while time.time() - t < ms / 1000.0:
        app.processEvents()
        time.sleep(0.005)


def counts():
    return cv._plane.renders, cv._sel_layer.renders


settle(700)  # i pannelli della finestra si sistemano con un attimo di ritardo: la vista cambia misura
cv.fit_bed()
app.processEvents()
L = ed.doc.layers
BX, BY = cv.bed_x, cv.bed_y

# ============================================================== A. immagine pronta = disegno diretto
check(f"{TAG}: A0 le immagini pronte sono accese di serie", cv.plane_cache is True)
empty = same("A1 piano vuoto")
shapes = [at(RectShape(60, 40, layer=1), 20, 20), at(EllipseShape(50, 30, layer=2), 100, 20),
          at(PolygonShape(40, 40, 5, layer=3), 170, 20), wave(30, 120, layer=1), wave(120, 120, layer=4, closed=True),
          line(20, 180, 120, 180, layer=2), line(140, 160, 140, 230, layer=3),
          at(TextShape("Prova", size=14, layer=1), 180, 170)]
fresh(shapes)
img = same("A2 forme di ogni tipo (rettangolo, ellisse, poligono, curve, linee piatte, testo)")
check(f"{TAG}: A2b le forme ci sono davvero (non due immagini vuote uguali)", diff(img, empty)[1] > 200)
check(f"{TAG}: A2c il contorno del rettangolo ha il colore del suo livello",
      near_color(img, 50, 20, cm.layer_color(1)))
L[2].mode = "fill"
L[4].mode = "offset_fill"
ed.changed.emit()
img = same("A3 livelli Riempimento e Offset: zona colorata uguale")
px, py = view_px(125, 35)
check(f"{TAG}: A3b dentro l'ellisse riempita il piano è colorato", diff(img, empty)[0] > 0 and
      int(np.abs(img[py, px, :3] - empty[py, px, :3]).sum()) > 20)
L[3].show = False
ed.changed.emit()
img = same("A4 livello nascosto")
check(f"{TAG}: A4b le forme del livello nascosto non si vedono", not near_color(img, 140, 200, cm.layer_color(3)))
L[3].show = True
L[1].output = False
ed.changed.emit()
same("A5 livello senza uscita (contorno attenuato)")
L[1].output = True
tool_shape = at(RectShape(30, 30, layer=30), 250, 100)
shapes[0].hidden = True
fresh(shapes + [tool_shape])
img = same("A6 livello strumento (tratteggio) e forma nascosta")
check(f"{TAG}: A6b la forma nascosta non si vede", not near_color(img, 50, 20, cm.layer_color(1)))
shapes[0].hidden = False
# foto e foto del piano sotto le forme
ed.doc.images["foto"] = Image.fromarray((np.linspace(0, 255, 60 * 40).reshape(40, 60)).astype(np.uint8), "L")
photo = at(ImageShape("foto", 60, 40, layer=0), 260, 20)
fresh(shapes + [photo])
img = same("A7 foto sul piano")
px, py = view_px(275, 40)
check(f"{TAG}: A7b la foto si vede", int(np.abs(img[py, px, :3] - empty[py, px, :3]).sum()) > 30)
red = QImage(int(BX * 2), int(BY * 2), QImage.Format_RGB32)
red.fill(QColor(200, 30, 30))
cv.set_camera_image(red, 2, 1.0)
app.processEvents()
img = same("A8 foto della telecamera sotto il piano: le forme restano sopra")
check(f"{TAG}: A8b la foto della telecamera si vede accanto alle forme", near_color(img, 80, 90, "#C81E1E", r=1, tol=60))
check(f"{TAG}: A8c il contorno resta sopra la foto", near_color(img, 20, 40, cm.layer_color(1)))
cv.clear_camera()
L[2].mode = L[4].mode = "line"
fresh(shapes, [shapes[0]])
img = same("A9 una forma selezionata: contorno e alone uguali")
check(f"{TAG}: A9b il contorno della selezione ha il colore d'accento", near_color(img, 35, 20, C["accent_hi"]))
ed.select([shapes[3]])
app.processEvents()
same("A10 selezione di una curva aperta")
r = at(RectShape(50, 30, layer=1), 60, 250)
r.apply(QTransform().translate(85, 265).rotate(30).translate(-85, -265))
fresh(shapes + [r], [r])
same("A11 forma ruotata selezionata")
# due forme selezionate con gli aloni che si accavallano: l'alone resta uniforme (non più scuro dove sono due)
# cinque pixel dello schermo fra i due rettangoli: in mezzo i due aloni (3,5 pixel per parte) si accavallano
GAP = cv.px(5) / vp.devicePixelRatioF()
q1, q2 = at(RectShape(60, 40, layer=3), 40, 60), at(RectShape(60, 40, layer=3), 100 + GAP, 60)


def halo_strength(shapes_sel):
    """(alone più forte fra i due contorni, alone più forte a sinistra del primo alla stessa distanza): quanto il
    piano è colorato a 2–3 pixel dai contorni, lontano dalla linea piena."""
    img_, bg_ = screen(), None
    ed.clear_selection()
    bg_ = screen()
    ed.select(shapes_sel)
    app.processEvents()
    xa, py = view_px(100, 75)  # lato destro del primo rettangolo
    xl, _ = view_px(40, 75)  # lato sinistro del primo
    strength = lambda x: int(np.abs(img_[py, x, :3] - bg_[py, x, :3]).sum())
    # il pixel a 2 dal primo contorno (verso il secondo) sta tutto dentro i due aloni e fuori dalle linee piene;
    # quello a 3 dal lato sinistro sta tutto dentro un alone solo
    return strength(xa + 2), strength(xl - 3), img_


fresh([q1, q2], [q1, q2])
gap, left, img = halo_strength([q1, q2])
check(f"{TAG}: A12 due aloni accavallati: non più forti di un alone solo", 20 < left and gap <= left * 1.25,
      f"in mezzo {gap}, da solo {left}")
g2 = GroupShape([q1, q2], layer=3)
fresh([g2], [g2])
gap, left, img = halo_strength([g2])
check(f"{TAG}: A13 gruppo selezionato: alone uniforme anche fra le sue forme", 20 < left and gap <= left * 1.25,
      f"in mezzo {gap}, da solo {left}")
check(f"{TAG}: A13b e la linea piena del contorno su tutte e due", near_color(img, 55, 60, C["accent_hi"])
      and near_color(img, 150, 100, C["accent_hi"]))

# ============================================================== B. dopo ogni modifica il piano è quello nuovo
fresh(shapes, [shapes[0]])
ed.transform(QTransform.fromTranslate(15, 25), "Sposta")
img = same("B1 sposta: il disegno segue")
check(f"{TAG}: B1b la forma è nel posto nuovo", near_color(img, 50, 45, C["accent_hi"]) and
      not near_color(img, 21, 30, cm.layer_color(1), r=0, tol=40))
ed.undo()
same("B2 annulla")
ed.redo()
same("B3 ripeti")
ed.select([shapes[1]])
ed.delete()
same("B4 elimina")
extra = at(RectShape(25, 25, layer=5), 300, 200)
ed.add([extra])
same("B5 aggiungi")
L[5].mode = "fill"
ed.changed.emit()
same("B6 il livello passa a Riempimento")
L[5].mode = "line"
L[5].show = False  # senza avvisare l'editor: l'immagine pronta se ne deve accorgere da sola
img = same("B7 livello nascosto senza passare dall'editor")
check(f"{TAG}: B7b la forma del livello nascosto è sparita", not near_color(img, 300, 212, cm.layer_color(5)))
L[5].show = True
same("B8 livello mostrato di nuovo")
L[5].mode = "fill"  # anche questo senza avvisare l'editor
img = same("B8b modo del livello cambiato senza passare dall'editor")
px, py = view_px(312, 212)
check(f"{TAG}: B8c la zona riempita è comparsa", int(np.abs(img[py, px, :3] - np.array([255, 255, 255])).sum()) > 20)
L[5].mode = "line"
L[2].mode = "fill"
ed.changed.emit()
w._toggle_filled(False)
same("B9 vista riempita spenta")
w._toggle_filled(True)
same("B10 vista riempita accesa")
L[2].mode = "line"
ed.select([shapes[3]])
ed.set_layer(6)
same("B11 cambio di livello della forma")
ed.select([shapes[2], shapes[3]])
ed.group()
same("B12 raggruppa")
g = ed.selection[0]
check(f"{TAG}: B12b il gruppo c'è", isinstance(g, GroupShape))
ed.transform(QTransform.fromTranslate(-10, 30), "Sposta")
same("B13 gruppo spostato")
ed.ungroup()
same("B14 separa")
cv.zoom_by(1.7, QPointF(500, 400))
same("B15 zoom")
cv.translate_view(-140, 90)
vp.update()
same("B16 vista spostata")
cv.fit_bed()
same("B17 vista adattata al piano")
n_shapes = len(ed.doc.shapes)
ed.add_plate()
app.processEvents()
img = same("B18 piano di lavoro nuovo (vuoto)")
ed.add([at(EllipseShape(40, 40, layer=2), 50, 50)])
same("B19 forma sul secondo piano")
ed.set_plate(0)
app.processEvents()
same("B20 ritorno al primo piano")
check(f"{TAG}: B20b le forme del primo piano sono tornate", len(ed.doc.shapes) == n_shapes)
size0 = w.size()
w.resize(1180, 760)
settle(500)  # i pannelli si sistemano con un attimo di ritardo
same("B21 finestra più piccola")
w.resize(size0)
settle(500)
cv.fit_bed()
same("B22 finestra di nuovo grande")
ed.set_document(Document())
app.processEvents()
img = same("B23 documento nuovo")
check(f"{TAG}: B23b il documento nuovo è vuoto anche sullo schermo", cv._plane.rect.isEmpty()
      and not ed.doc.shapes, str(cv._plane.rect))
empty = img  # la vista può avere misure diverse da quelle dell'inizio (pannelli risistemati)
L = ed.doc.layers
# trascinamento vero con il mouse su un disegno leggero: a ogni passo lo schermo è quello giusto
a_, b_ = at(RectShape(60, 40, layer=1), 40, 40), at(EllipseShape(50, 50, layer=2), 150, 60)
fresh([a_, b_], [a_])
cv.set_tool("select")
p0 = vpt(40, 60)
ev(QEvent.MouseButtonPress, p0, Qt.LeftButton, Qt.LeftButton)
ok = True
for i in range(1, 5):
    ev(QEvent.MouseMove, (p0[0] + 12 * i, p0[1] - 7 * i), Qt.NoButton, Qt.LeftButton, Qt.AltModifier)
    app.processEvents()
    mx, n = diff(screen(), direct())
    ok = ok and mx <= 8 and n <= 3
check(f"{TAG}: B24 durante un trascinamento (disegno leggero) lo schermo è sempre quello vero", ok)
ev(QEvent.MouseButtonRelease, (p0[0] + 48, p0[1] - 28), Qt.LeftButton)
app.processEvents()
same("B25 dopo il rilascio")
check(f"{TAG}: B25b la forma si è spostata davvero", abs(a_.bounds().left() - 40) > 3)
ed.undo()
same("B26 annulla del trascinamento")

# ============================================================== C. l'immagine pronta si usa davvero
fresh([at(RectShape(60, 40, layer=1), 40, 40), at(EllipseShape(50, 50, layer=2), 150, 60), wave(60, 200)])
a_, b_ = ed.doc.shapes[0], ed.doc.shapes[1]
calls = {"shape": 0, "fill": 0}
_ps, _pf = cm.ShapeItem.paint_shape, cm.FillItem.paint_fill
cm.ShapeItem.paint_shape = lambda self, *a, **k: (calls.__setitem__("shape", calls["shape"] + 1), _ps(self, *a, **k))[1]
cm.FillItem.paint_fill = lambda self, *a, **k: (calls.__setitem__("fill", calls["fill"] + 1), _pf(self, *a, **k))[1]
screen()
c0, k0 = counts(), dict(calls)
cv.set_tool("select")
for i in range(12):
    ev(QEvent.MouseMove, (300 + i * 17, 200 + i * 11))
    app.processEvents()
check(f"{TAG}: C1 passare con il mouse (Selezione) non ridisegna le forme", counts() == c0 and calls == k0,
      f"{counts()} {c0} {calls}")
cv.set_tool("text")
for i in range(12):
    ev(QEvent.MouseMove, (310 + i * 13, 220 + i * 9))
    app.processEvents()
check(f"{TAG}: C2 passare con il mouse (Testo, ridisegno completo) non ridisegna le forme",
      counts() == c0 and calls == k0, f"{counts()} {c0} {calls}")
cv.set_tool("select")
app.processEvents()
c0, k0 = counts(), dict(calls)
o = vpt(-20, -20)
ev(QEvent.MouseButtonPress, o, Qt.LeftButton, Qt.LeftButton)
for i in range(1, 8):
    ev(QEvent.MouseMove, (o[0] + 30 * i, o[1] - 20 * i), Qt.NoButton, Qt.LeftButton)
    app.processEvents()
check(f"{TAG}: C3 il rettangolo di selezione non ridisegna le forme", counts() == c0 and calls == k0)
e_ = vpt(120, 100)
ev(QEvent.MouseButtonRelease, e_, Qt.LeftButton)
app.processEvents()
ed.select([a_])
screen()
c1 = counts()
check(f"{TAG}: C4 cambiare selezione ridisegna solo il contorno della selezione",
      c1[0] == c0[0] and c1[1] > c0[1] and calls == k0, f"{c0} {c1}")
ed.select([b_])
screen()
c2 = counts()
check(f"{TAG}: C5 un'altra selezione: di nuovo solo il contorno", c2[0] == c0[0] and c2[1] == c1[1] + 1)
screen()
screen()
check(f"{TAG}: C6 ridisegni ripetuti senza cambiamenti: nessun disegno vero", counts() == c2)
ed.transform(QTransform.fromTranslate(5, 5), "Sposta")
screen()
c3 = counts()
check(f"{TAG}: C7 una modifica ridisegna le forme una volta sola", c3[0] == c2[0] + 1, f"{c2} {c3}")
ed.clear_selection()
screen()
check(f"{TAG}: C8 senza selezione l'immagine del contorno si butta", cv._sel_layer.key is None)
cm.ShapeItem.paint_shape, cm.FillItem.paint_fill = _ps, _pf
its = list(cv.items_by_id.values())
check(f"{TAG}: C9 Qt non chiama più il disegno forma per forma",
      all(bool(it.flags() & cm.QGraphicsItem.ItemHasNoContents) for it in its)
      and bool(cv.fill_item.flags() & cm.QGraphicsItem.ItemHasNoContents))
# l'immagine pronta occupa solo la parte della vista con le forme
check(f"{TAG}: C10 l'immagine pronta copre solo la zona delle forme",
      0 < cv._plane.rect.width() * cv._plane.rect.height() < 0.6 * vp.width() * vp.height(), str(cv._plane.rect))

# ============================================================== D. disegni pesanti: immagine provvisoria
check(f"{TAG}: D0 senza schermo (prove automatiche) le immagini provvisorie sono spente", cv.plane_preview is False)
cv.plane_preview = True
cm.PLANE_SLOW_S = -1.0  # ogni disegno «costa troppo»: durante i movimenti si usa l'immagine di prima
cm.PLANE_IDLE_MS = (60, 60)
a_, b_ = at(RectShape(60, 40, layer=1), 40, 40), at(EllipseShape(50, 50, layer=2), 150, 60)
fresh([a_, b_], [a_])
cv.set_tool("select")
cv.fit_bed()
screen()
settle(120)
c0 = counts()
p0 = vpt(40, 60)
bed0 = cv.bed_to_view_tf()
corner_view = bed0.map(QPointF(40, 40))
ev(QEvent.MouseButtonPress, p0, Qt.LeftButton, Qt.LeftButton)
ev(QEvent.MouseMove, (p0[0] + 8, p0[1] + 2), Qt.NoButton, Qt.LeftButton, Qt.AltModifier)
ev(QEvent.MouseMove, (p0[0] + 40, p0[1] - 30), Qt.NoButton, Qt.LeftButton, Qt.AltModifier)
check(f"{TAG}: D1 mentre si trascina le forme non si ridisegnano", counts() == c0, f"{c0} {counts()}")
tf_plane = cv._plane_pixmap()
tf_sel = cv._selection_pixmap()
check(f"{TAG}: D2 trascinando, l'immagine delle forme resta dov'era (provvisoria)",
      tf_plane is not None and tf_plane.isIdentity() and counts() == c0)
want = cv.bed_to_view_tf().map(QPointF(a_.bounds().left(), a_.bounds().top()))
got = tf_sel.map(corner_view) if tf_sel is not None else QPointF(-1, -1)
check(f"{TAG}: D3 il contorno della selezione segue il mouse (spostato della stessa misura)",
      tf_sel is not None and abs(got.x() - want.x()) < 0.01 and abs(got.y() - want.y()) < 0.01
      and abs(a_.bounds().left() - 40) > 5, f"{got} {want}")
cv.plane_preview = False
img_d, img_s = direct(), grab()
cv.plane_preview = True
check(f"{TAG}: D4 senza immagini provvisorie (prove automatiche) la vista a metà trascinamento è quella vera",
      diff(img_s, img_d)[0] <= 8 and diff(img_s, img_d)[1] <= 3, str(diff(img_s, img_d)))
cv.touch_burst()
cv.refresh_live([a_])  # torna allo stato «sto trascinando», con le immagini vere appena fatte come base
c1 = counts()
ev(QEvent.MouseMove, (p0[0] + 44, p0[1] - 33), Qt.NoButton, Qt.LeftButton, Qt.AltModifier)
app.processEvents()
check(f"{TAG}: D5 il movimento dopo usa di nuovo l'immagine provvisoria", counts() == c1)
settle(260)
c2 = counts()
check(f"{TAG}: D6 da fermi (mouse ancora premuto) arriva l'immagine vera", c2[0] == c1[0] + 1 and c2[1] == c1[1] + 1
      and cv._plane_pixmap() is None, f"{c1} {c2}")
ev(QEvent.MouseMove, (p0[0] + 60, p0[1] - 40), Qt.NoButton, Qt.LeftButton, Qt.AltModifier)
app.processEvents()
c3 = counts()
ev(QEvent.MouseButtonRelease, (p0[0] + 60, p0[1] - 40), Qt.LeftButton)
app.processEvents()
c4 = counts()
check(f"{TAG}: D7 al rilascio l'immagine vera arriva subito, senza aspettare", c3 == c2 and c4[0] == c3[0] + 1,
      f"{c2} {c3} {c4}")
cm.PLANE_SLOW_S = 1e9
same("D8 dopo il rilascio lo schermo è quello vero")
cm.PLANE_SLOW_S = -1.0
# ruota e scala: stessa trasformazione per tutte le forme selezionate
ed.select([a_, b_])
screen()
settle(120)
before = {s.id: QTransform(s.tf) for s in (a_, b_)}
bed0 = cv.bed_to_view_tf()
pts0 = [QPointF(a_.bounds().left(), a_.bounds().top()), QPointF(b_.bounds().right(), b_.bounds().bottom())]
c = ed.selection_bounds().center()
T = QTransform.fromTranslate(-c.x(), -c.y()) * QTransform().rotate(25).scale(1.3, 0.8) * QTransform.fromTranslate(c.x(), c.y())
for s in (a_, b_):
    s.tf = before[s.id] * T
    s.invalidate()
cv.touch_burst()
cv.refresh_live([a_, b_])
tf_sel = cv._selection_pixmap()
ok = tf_sel is not None
for p in pts0:
    got, want = (tf_sel.map(bed0.map(p)) if ok else QPointF()), cv.bed_to_view_tf().map(T.map(p))
    ok = ok and abs(got.x() - want.x()) < 0.01 and abs(got.y() - want.y()) < 0.01
check(f"{TAG}: D9 ruota + scala: il contorno provvisorio va dove vanno le forme", ok)
# una sola delle due forme si muove ancora: niente trasformazione comune, contorno ridisegnato davvero
a_.tf = a_.tf * QTransform.fromTranslate(9, 0)
a_.invalidate()
cv.touch_burst()
cv.refresh_live([a_])
k = counts()[1]
check(f"{TAG}: D10 forme mosse in modo diverso: il contorno si ridisegna davvero",
      cv._selection_pixmap() is None and counts()[1] == k + 1)
# stessa posizione ma una delle due forme anche scalata: non è la stessa trasformazione
cv.end_burst()
vp.update()
app.processEvents()
settle(120)
keep = QTransform(a_.tf)
a_.tf = a_.tf * QTransform.fromScale(1.03, 1.0)
a_.invalidate()
cv.touch_burst()
cv.refresh_live([a_])
k = counts()[1]
check(f"{TAG}: D10b una forma scalata e l'altra no: il contorno si ridisegna davvero",
      cv._selection_pixmap() is None and counts()[1] == k + 1)
a_.tf = keep
a_.invalidate()
cv.refresh_live([a_])
# selezione diversa durante un movimento: contorno vero
cv.touch_burst()
ed.select([b_])
k = counts()[1]
check(f"{TAG}: D11 selezione cambiata: il contorno si ridisegna davvero",
      cv._selection_pixmap() is None and counts()[1] == k + 1)
# la sagoma cambia (come quando si trascina un nodo): il contorno provvisorio non basta, serve quello vero
pl = wave(60, 200)
ed.add([pl])
ed.select([pl])
vp.update()
app.processEvents()
settle(120)
np_ = QPainterPath(pl.qpath)
np_.lineTo(200, 260)
pl.set_path(np_)
cv.touch_burst()
ed.preview_changed()
k = counts()[1]
check(f"{TAG}: D11b sagoma cambiata (nodo trascinato): il contorno si ridisegna davvero",
      cv._selection_pixmap() is None and counts()[1] == k + 1)
ed.select([b_])
ed.doc.shapes.remove(pl)
cv.end_burst()
for s in (a_, b_):
    s.tf = before[s.id]
    s.invalidate()
ed.clear_selection()
ed.changed.emit()
screen()
settle(120)
# spostamento della vista con il tasto centrale
c0 = counts()
bed0 = cv.bed_to_view_tf()
m0 = (400.0, 300.0)
ev(QEvent.MouseButtonPress, m0, Qt.MiddleButton, Qt.MiddleButton)
ev(QEvent.MouseMove, (m0[0] + 70, m0[1] - 45), Qt.NoButton, Qt.MiddleButton)
app.processEvents()
tfp = cv._plane_pixmap()
P = QPointF(60, 70)
got, want = (tfp.map(bed0.map(P)) if tfp is not None else QPointF()), cv.bed_to_view_tf().map(P)
check(f"{TAG}: D12 spostando la vista l'immagine provvisoria segue (nessun disegno vero)",
      tfp is not None and counts() == c0 and abs(got.x() - want.x()) < 0.01 and abs(got.y() - want.y()) < 0.01
      and abs(want.x() - bed0.map(P).x() - 70) < 1.01)
ev(QEvent.MouseButtonRelease, (m0[0] + 70, m0[1] - 45), Qt.MiddleButton)
app.processEvents()
check(f"{TAG}: D13 rilasciato il tasto centrale arriva la vista vera", counts()[0] == c0[0] + 1
      and cv._plane_pixmap() is None)
# rotella
c0 = counts()
bed0 = cv.bed_to_view_tf()
wheel((500.0, 380.0), 120)
wheel((500.0, 380.0), 120)
app.processEvents()
tfp = cv._plane_pixmap()
got, want = (tfp.map(bed0.map(P)) if tfp is not None else QPointF()), cv.bed_to_view_tf().map(P)
check(f"{TAG}: D14 con la rotella l'immagine provvisoria si ingrandisce attorno al mouse",
      tfp is not None and counts() == c0 and abs(got.x() - want.x()) < 0.02 and abs(got.y() - want.y()) < 0.02
      and abs(tfp.m11() - 1.18 ** 2) < 0.01, f"{tfp}")
settle(260)
check(f"{TAG}: D15 finita la rotella arriva la vista vera", counts()[0] == c0[0] + 1 and cv._plane_pixmap() is None)
cm.PLANE_SLOW_S = 1e9
same("D16 e lo schermo è quello vero")
# una modifica non fatta con il mouse (nessun movimento in corso) non aspetta mai
cm.PLANE_SLOW_S = -1.0
cv.end_burst()
settle(50)
cv._burst = 0.0
c0 = counts()
ed.select([a_])
ed.transform(QTransform.fromTranslate(3, 3), "Sposta")
vp.update()
app.processEvents()
check(f"{TAG}: D17 una modifica da menu o da tastiera si vede subito (niente immagine provvisoria)",
      counts()[0] == c0[0] + 1 and cv._plane_pixmap() is None)
# freccia tenuta premuta (ripetizione dei tasti): vale come un trascinamento
from PySide6.QtGui import QKeyEvent

cv.end_burst()
settle(50)
cv._burst = 0.0
vp.update()
app.processEvents()
c0 = counts()
x0 = a_.bounds().left()
cv.setFocus()
app.sendEvent(cv, QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier, "", True))
check(f"{TAG}: D17b freccia tenuta premuta: la forma si sposta e il piano usa l'immagine provvisoria",
      abs(a_.bounds().left() - x0 - 1.0) < 1e-6 and cv._plane_pixmap() is not None and counts() == c0,
      f"{a_.bounds().left() - x0} {counts()} {c0}")
settle(260)
check(f"{TAG}: D17c lasciata la freccia arriva l'immagine vera", counts()[0] == c0[0] + 1 and cv._plane_pixmap() is None)
cv._burst = 0.0
app.sendEvent(cv, QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier, "", False))
check(f"{TAG}: D17d una pressione sola della freccia si vede subito", cv._plane_pixmap() is None)
# disegno leggero: mai immagini provvisorie
cm.PLANE_SLOW_S = 1e9
cv.touch_burst()
ed.transform(QTransform.fromTranslate(3, 3), "Sposta")
check(f"{TAG}: D18 con un disegno leggero non c'è mai un'immagine provvisoria", cv._plane_pixmap() is None
      and cv._selection_pixmap() is None)
cv.end_burst()
check(f"{TAG}: D19 soglie di serie sensate", 0.02 <= SLOW0 <= 0.1 and 80 <= IDLE0[0] <= 250 and IDLE0[1] <= 1500)
cm.PLANE_IDLE_MS = IDLE0
cv.plane_preview = False

# ============================================================== E. clic sulle forme di un gruppo
def hit_old(bed_pt, tol_px=6):
    """hit_shape com'era fino alla 0.20.3."""
    tol = cv.px(tol_px)
    doc = ed.doc
    for s in reversed(doc.shapes):
        if s.hidden:
            continue
        cs = doc.layers.get(s.layer)
        if cs is not None and not cs.show and not isinstance(s, GroupShape):
            continue
        b = s.bounds().adjusted(-tol, -tol, tol, tol)
        if not b.contains(bed_pt):
            continue
        path = s.path()
        if isinstance(s, ImageShape):
            return s
        filled = cv.filled_view and cs is not None and cs.mode in ("fill", "offset_fill")
        if (filled or isinstance(s, TextShape)) and path.contains(bed_pt):
            return s
        st = QPainterPathStroker()
        st.setWidth(2 * tol)
        if st.createStroke(path).contains(bed_pt):
            return s
    return None


random.seed(4)
kids = [at(RectShape(random.uniform(8, 30), random.uniform(8, 30), layer=1), random.uniform(10, 200),
           random.uniform(10, 200)) for _ in range(25)]
kids += [at(EllipseShape(20, 14, layer=2), 60 + 9 * i, 220) for i in range(8)]
inner = GroupShape([at(RectShape(30, 20, layer=1), 230, 30), wave(230, 90)], layer=1)
kids.append(inner)
grp = GroupShape(kids, layer=1)
lone = at(RectShape(40, 40, layer=3), 300, 150)
for mode in ("line", "fill"):
    ed.doc.layers[1].mode = mode
    fresh([lone, grp])
    grp.apply(QTransform().rotate(8))
    ed.changed.emit()
    app.processEvents()
    bad = 0
    n = 0
    for gx in range(0, 340, 4):
        for gy in range(0, 270, 5):
            p = QPointF(gx + 0.37, gy + 0.21)
            n += 1
            bad += cv.hit_shape(p) is not hit_old(p)
    check(f"{TAG}: E1 clic sulle forme (livello «{mode}»): {n} punti, stesso risultato di prima", bad == 0, f"{bad} diversi")
ed.doc.layers[1].mode = "line"
hits = sum(cv.hit_shape(QPointF(gx + 0.37, gy + 0.21)) is grp for gx in range(0, 340, 4) for gy in range(0, 270, 5))
check(f"{TAG}: E2 il gruppo si prende davvero in tanti punti (la prova non è vuota)", hits > 100, str(hits))
grp.tf = grp.tf * QTransform.fromTranslate(40, 0)  # forma cambiata senza avvisare il piano: si torna al metodo lento
grp.invalidate()
p = QPointF(grp.bounds().left(), grp.bounds().center().y())
check(f"{TAG}: E3 forma cambiata senza aggiornare il piano: il clic usa la forma di adesso",
      cv.hit_shape(p) is hit_old(p))
ed.changed.emit()

# ============================================================== F. tracciati letti in blocco, linee aperte
random.seed(7)


def rnd_path(n_el):
    p = QPainterPath()
    p.moveTo(random.uniform(-50, 50), random.uniform(-50, 50))
    while p.elementCount() < n_el:
        k = random.random()
        x, y = random.uniform(-500, 500), random.uniform(-500, 500)
        if k < 0.4:
            p.lineTo(x, y)
        elif k < 0.7:
            p.cubicTo(x, y, x + random.random(), y - 3, x * 0.5, y * 0.25)
        elif k < 0.8:
            p.quadTo(x, y, y, x)
        elif k < 0.9:
            p.closeSubpath()
        else:
            p.moveTo(x, y)
    return p


ok = True
sizes = [0, 1, 2, 5, 31, 32, 33, 40, 64, 200, 5000]
for n_el in sizes:
    p = rnd_path(n_el) if n_el else QPainterPath()
    fast, slow = docmod.path_elements(p), docmod._path_elements_slow(p)
    ok = ok and fast == slow and all(type(e) is list and type(e[0]) is int and type(e[1]) is float for e in fast)
check(f"{TAG}: F1 elementi dei tracciati letti in blocco = letti uno a uno ({len(sizes)} tracciati)", ok)
slow_calls = []
_slow = docmod._path_elements_slow
docmod._path_elements_slow = lambda p: (slow_calls.append(p.elementCount()), _slow(p))[1]
docmod.path_elements(rnd_path(400))
docmod.path_elements(rnd_path(10))
docmod._path_elements_slow = _slow
check(f"{TAG}: F1b i tracciati lunghi si leggono davvero in blocco, quelli corti uno a uno", slow_calls == [10],
      str(slow_calls))
bp = QPainterPath()
bp.moveTo(0, 0)
for i in range(700):
    bp.lineTo(i * 0.5, math.sin(i) * 7)
    bp.cubicTo(i * 0.5 + 0.1, 3, i * 0.5 + 0.2, -3, i * 0.5 + 0.3, math.cos(i))
bp.closeSubpath()
big = PathShape(bp)
d1 = big.to_dict()
check(f"{TAG}: F2 il tracciato salvato e riaperto è identico",
      docmod.shape_from_dict(d1).to_dict()["p"] == d1["p"] and len(d1["p"]["elements"]) == big.qpath.elementCount())
el = QPainterPath()
el.addEllipse(0, 0, 30, 20)
check(f"{TAG}: F3 ellisse (solo curve): lettura in blocco uguale a quella lenta",
      docmod.path_elements(el) == docmod._path_elements_slow(el))
cases = [QPainterPath(), el, rnd_path(60), rnd_path(300)]
o1 = QPainterPath()
o1.moveTo(0, 0)
o1.lineTo(10, 0)
o1.lineTo(10, 10)
cases.append(o1)  # aperto
o2 = QPainterPath(o1)
o2.closeSubpath()
cases.append(o2)  # chiuso
o3 = QPainterPath(o2)
o3.moveTo(30, 30)
o3.cubicTo(40, 40, 50, 20, 60, 30)
cases.append(o3)  # chiuso + curva aperta
o4 = QPainterPath()
o4.moveTo(0, 0)
o4.lineTo(10, 0)
o4.lineTo(10, 10)
o4.lineTo(0.0000004, 0)
cases.append(o4)  # quasi chiuso (meno di un milionesimo): conta come chiuso
o5 = QPainterPath()
o5.moveTo(0, 0)
o5.lineTo(10, 0)
o5.lineTo(10, 10)
o5.lineTo(0.00001, 0)
cases.append(o5)  # aperto di un centesimo di micron
o6 = QPainterPath(o2)
o6.moveTo(99, 99)
cases.append(o6)  # un punto isolato in coda
o7 = QPainterPath()
o7.moveTo(5, 5)
o7.cubicTo(20, 30, 40, -30, 5, 5)
cases.append(o7)  # curva che torna al punto di partenza
got = [fill_preview._has_open(p) for p in cases]
want = [fill_preview._has_open_slow(p) for p in cases]
check(f"{TAG}: F4 linee aperte riconosciute come prima ({len(cases)} casi)", got == want, f"{got} {want}")
check(f"{TAG}: F4b nei casi ci sono sia aperti sia chiusi", True in want and False in want)

# ============================================================== G. tantissimi punti
random.seed(11)
many = []
for i in range(330):
    cx, cy, rr = random.uniform(15, BX - 15), random.uniform(15, BY - 15), random.uniform(3, 9)
    p = QPainterPath()
    for k in range(25):
        a = 2 * math.pi * k / 24
        q = rr * (1 + 0.3 * math.sin(5 * a + i))
        if k == 0:
            p.moveTo(cx + q, cy)
        else:
            p.quadTo(cx + q * math.cos(a - 0.1) + 0.4, cy + q * math.sin(a - 0.1) + 0.4, cx + q * math.cos(a), cy + q * math.sin(a))
    p.closeSubpath()
    many.append(PathShape(p, layer=i % 3))
ed.doc.layer(0).mode = "fill"
fresh(many)
cv.fit_bed()
check(f"{TAG}: G1 il disegno di prova ha tantissimi punti", cv.many_points()
      and sum(it.points for it in cv.items_by_id.values()) > cm.MANY_POINTS)
img = same("G2 tantissimi punti: immagine pronta = disegno diretto")
s0 = many[1]
e0 = s0.path().elementAt(0)
check(f"{TAG}: G3 i contorni si vedono ancora (1 pixel)", near_color(img, e0.x, e0.y, cm.layer_color(1), r=1),
      str(img[view_px(e0.x, e0.y)[1] - 1:view_px(e0.x, e0.y)[1] + 2, view_px(e0.x, e0.y)[0] - 1:view_px(e0.x, e0.y)[0] + 2, :3].tolist()) + cm.layer_color(1))
f0 = many[0]
fc = f0.bounds().center()
px, py = view_px(fc.x(), fc.y())
check(f"{TAG}: G4 le zone riempite si vedono ancora", int(np.abs(img[py, px, :3] - empty[py, px, :3]).sum()) > 20)
ed.select(list(ed.doc.shapes))
img = screen()
check(f"{TAG}: G5 tutto selezionato: il contorno d'accento si vede", near_color(img, e0.x, e0.y, C["accent_hi"], r=1))
ed.group()
big_g = ed.selection[0]
img = screen()
e0 = big_g.path().elementAt(0)
check(f"{TAG}: G6 gruppo con tantissimi punti selezionato: contorno d'accento sul gruppo",
      isinstance(big_g, GroupShape) and near_color(img, e0.x, e0.y, C["accent_hi"], r=1))
t0 = time.perf_counter()
for i in range(10):
    ev(QEvent.MouseMove, (300 + i * 23, 250 + i * 13))
    app.processEvents()
dt = (time.perf_counter() - t0) / 10
check(f"{TAG}: G7 passare con il mouse su un gruppo di {len(many)} tracciati selezionato: meno di 100 ms a movimento",
      dt < 0.1, f"{dt * 1000:.0f} ms")
few = [at(RectShape(20, 20, layer=1), 10 + 25 * i, 10) for i in range(5)]
fresh(few)
check(f"{TAG}: G8 con poche forme niente «tantissimi punti» (contorni di 1,25 pixel come prima)", not cv.many_points())
# ingombro della selezione ricordato
ed.select([few[0], few[1]])
ok = cv.selection_bounds() == ed.selection_bounds()
ed.transform(QTransform.fromTranslate(7, 30), "Sposta")
ok = ok and cv.selection_bounds() == ed.selection_bounds()
ed.undo()
ok = ok and cv.selection_bounds() == ed.selection_bounds()
ed.select([few[3]])
ok = ok and cv.selection_bounds() == ed.selection_bounds()
few[3].tf = few[3].tf * QTransform.fromTranslate(0, 50)
few[3].invalidate()
cv.refresh_live([few[3]])
ok = ok and cv.selection_bounds() == ed.selection_bounds()
ed.clear_selection()
ok = ok and cv.selection_bounds() == ed.selection_bounds()
check(f"{TAG}: G9 l'ingombro ricordato della selezione è sempre quello vero (maniglie al posto giusto)", ok)
ed.select([few[0]])
b0 = cv.selection_bounds()
b0.setWidth(999)
check(f"{TAG}: G10 chi riceve l'ingombro non può rovinare quello ricordato",
      cv.selection_bounds() == ed.selection_bounds() and cv.selection_bounds().width() < 100)
# barra delle misure: con una forma la sua descrizione, con più forme il conto (senza descriverle una a una)
info = w.numeric.info
ed.select([few[0]])
app.processEvents()
one = info.text()
described = {"n": 0}
_d = RectShape.describe
RectShape.describe = lambda self: (described.__setitem__("n", described["n"] + 1), _d(self))[1]
ed.select(few[:3])
app.processEvents()
RectShape.describe = _d
check(f"{TAG}: G11 barra delle misure: una forma = la sua descrizione, tre forme = «3 oggetti»",
      one == few[0].describe() and "3" in info.text() and one != info.text(), f"{one!r} {info.text()!r}")
check(f"{TAG}: G11b con più forme selezionate non si descrive ogni forma", described["n"] == 0, str(described))

# ============================================================== H. finestra intera, interruttore di sicurezza
fresh([at(RectShape(120, 80, layer=2), 60, 60)])
cv.fit_bed()
app.processEvents()
shot = w.grab().toImage()
tl = vp.mapTo(w, QPoint(0, 0))
v = cv.to_view(QPointF(120, 60))
dpr = shot.devicePixelRatioF()
found = False
c = QColor(cm.layer_color(2))
for dy in range(-3, 4):
    q = shot.pixelColor(int(round((tl.x() + v.x()) * dpr)), int(round((tl.y() + v.y()) * dpr)) + dy)
    found = found or abs(q.red() - c.red()) + abs(q.green() - c.green()) + abs(q.blue() - c.blue()) < 90
check(f"{TAG}: H1 l'immagine dell'intera finestra (rapporto per l'assistenza) mostra le forme", found)
# la scena disegnata in un'immagine a parte (come fanno altre prove e chi esporta): le forme ci sono, al loro posto
from PySide6.QtGui import QPainter

for zoom in (1.0, 2.3):  # anche con la vista ingrandita: l'immagine pronta della vista non c'entra
    cv.fit_bed()
    cv.zoom_by(zoom, QPointF(300, 300))
    screen()
    out = QImage(400, 400, QImage.Format_ARGB32)
    out.fill(QColor("#ffffff"))
    q = QPainter(out)
    cv.scene().render(q, QRectF(0, 0, 400, 400), QRectF(0, -200, 200, 200))  # piano x 0..200, y 0..200 a 2 px/mm
    q.end()
    c = QColor(cm.layer_color(2))
    on = lambda x, y: any(abs(out.pixelColor(x + dx, y + dy).red() - c.red()) + abs(out.pixelColor(x + dx, y + dy).green() - c.green())
                          + abs(out.pixelColor(x + dx, y + dy).blue() - c.blue()) < 150 for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    # rettangolo 60..180 × 60..140: lato in basso a y=60 → riga 400-120; lato sinistro a x=60 → colonna 120
    check(f"{TAG}: H1b la scena disegnata in un'immagine a parte ha le forme al posto giusto (zoom {zoom})",
          on(240, 400 - 120) and on(120, 400 - 200) and not on(240, 400 - 200) and not on(40, 40))
cv.fit_bed()
cv.plane_cache = False
r0 = counts()
ed.select(list(ed.doc.shapes))
vp.update()
app.processEvents()
img_off = grab()
check(f"{TAG}: H2 interruttore di sicurezza: senza immagini pronte il piano si disegna come prima",
      counts() == r0 and near_color(img_off, 90, 60, C["accent_hi"]))
cv.plane_cache = True
img_on = screen()
check(f"{TAG}: H3 riaccese, stesso risultato", diff(img_on, img_off)[0] <= 8 and diff(img_on, img_off)[1] <= 3)

n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} prove superate")
sys.exit(0 if n_ok == len(results) else 1)
