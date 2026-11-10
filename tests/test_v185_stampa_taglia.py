# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.5: Stampa e taglia (funzione in prova, dietro il codice amministratore; richiesta su GitHub: «la funzione
print and cut sarebbe il top»).

Casi provati:
1 calcolo: rotazione + spostamento, con e senza scala, foglio capovolto, crocette vicine, punti uguali, scala assurda;
2 crocette: ruolo salvato nel progetto, centro giusto anche dopo le trasformazioni, progetti senza ruolo identici;
3 PDF: misure vere (riletto e misurato), solo i livelli con l'uscita spenta, immagine a colori, foglio orizzontale
  quando serve, disegno troppo grande rifiutato;
4 finestra: nascosta senza codice; crocette (un passo da annullare, rimesse senza doppioni, mai nel G-code);
5 simulatore: foglio «storto» di 3° e spostato, testa sulle due crocette, allineamento, G-code sul foglio vero;
6 rifiuti: senza homing, scollegato, fuori dal piano; puntino acceso e spento; traduzioni.
"""
import json
import math
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import hashlib  # noqa: E402

from PySide6.QtCore import QPointF, QSize  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from PIL import Image  # noqa: E402

from freelasercut import admin  # noqa: E402
from freelasercut.core import gcode, io_formats  # noqa: E402
from freelasercut.core import print_cut as pc  # noqa: E402
from freelasercut.core.document import Document, RectShape, shape_from_dict  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []
TMP = tempfile.mkdtemp()


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def sheet(angle_deg, dx, dy, k=1.0, about=(0.0, 0.0)):
    """Il foglio vero rispetto al disegno: scala k, rotazione attorno a `about`, poi spostamento."""
    a = math.radians(angle_deg)
    c, s = k * math.cos(a), k * math.sin(a)
    ax, ay = about
    return QTransform(c, s, -s, c, ax - c * ax + s * ay + dx, ay - s * ax - c * ay + dy)


def mp(tf, p):
    q = tf.map(QPointF(*p))
    return q.x(), q.y()


def near(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ================================================================== 1. calcolo
P1, P2 = (12.0, 148.0), (198.0, 22.0)
T = sheet(7.0, 31.5, -12.25)
tf, info = pc.fit(P1, P2, mp(T, P1), mp(T, P2), scale=False)
check("foglio ruotato di 7° e spostato: le due crocette vanno esattamente sui punti misurati",
      near(mp(tf, P1), mp(T, P1), 1e-9) and near(mp(tf, P2), mp(T, P2), 1e-9), info)
check("…e ogni altro punto del disegno segue il foglio", near(mp(tf, (77.0, 91.0)), mp(T, (77.0, 91.0)), 1e-9))
check("…angolo 7,00°, scala 1, nessun residuo", abs(info["angle"] - 7.0) < 1e-9 and abs(info["scale"] - 1) < 1e-12
      and info["residual"] < 1e-9, info)
T = sheet(-2.5, 5.0, 8.0, k=1.004)
tf, info = pc.fit(P1, P2, mp(T, P1), mp(T, P2), scale=True)
check("stampa più grande dello 0,4% con la correzione della scala: combacia tutto",
      near(mp(tf, P1), mp(T, P1), 1e-9) and near(mp(tf, (60.0, 60.0)), mp(T, (60.0, 60.0)), 1e-9)
      and abs(info["scale"] - 1.004) < 1e-9, info)
tf, info = pc.fit(P1, P2, mp(T, P1), mp(T, P2), scale=False)
L = math.dist(P1, P2)
mid = ((P1[0] + P2[0]) / 2, (P1[1] + P2[1]) / 2)
check("senza correzione: le misure restano quelle del disegno e l'errore si divide a metà fra le due crocette",
      abs(math.dist(mp(tf, P1), mp(tf, P2)) - L) < 1e-9 and abs(info["residual"] - L * 0.004 / 2) < 1e-6
      and near(mp(tf, mid), mp(T, mid), 1e-9), info)
T = sheet(180.0, 210.0, 170.0)
tf, info = pc.fit(P1, P2, mp(T, P1), mp(T, P2))
check("foglio capovolto (180°): allineato lo stesso", near(mp(tf, (50.0, 40.0)), mp(T, (50.0, 40.0)), 1e-6)
      and abs(abs(info["angle"]) - 180.0) < 1e-6, info)


def refused(*a, **k):
    try:
        pc.fit(*a, **k)
    except pc.PrintCutError as exc:
        return str(exc)
    return ""


check("crocette del disegno a meno di 30 mm: rifiutato", "vicine" in refused((0, 0), (20, 0), (0, 0), (20, 0)))
check("due punti uguali presi con la testa: rifiutato", "coincidono" in refused(P1, P2, (10, 10), (10, 10)))
T = sheet(1.0, 0, 0, k=1.05)
check("differenza del 5% (stampa non al 100%): rifiutato con la spiegazione",
      "100%" in refused(P1, P2, mp(T, P1), mp(T, P2)))

# ================================================================== 2. crocette
m1, m2 = pc.make_mark(1, 10.0, 90.0, 5), pc.make_mark(2, 110.0, 10.0, 5)
check("crocetta 1: due tratti e un cerchio; crocetta 2: un cerchio in più", len(m1.children) == 3 and len(m2.children) == 4
      and m1.role == "pc1" and m2.role == "pc2")
check("centro della crocetta", near(pc.mark_center(m1), (10.0, 90.0)) and near(m1.bounds().center().toTuple(), (10.0, 90.0)))
m1.apply(sheet(33.0, 4.0, 5.0, k=1.2))
check("…giusto anche dopo rotazione, scala e spostamento",
      near(pc.mark_center(m1), mp(sheet(33.0, 4.0, 5.0, k=1.2), (10.0, 90.0)), 1e-9))
d = m2.to_dict()
check("il ruolo si salva e si rilegge (anche nelle copie)", d.get("role") == "pc2" and shape_from_dict(d).role == "pc2"
      and m2.clone().role == "pc2")
check("le forme normali restano come prima (nessuna voce in più nel progetto)", "role" not in RectShape(5, 5).to_dict()
      and shape_from_dict(RectShape(5, 5).to_dict()).role == "")
doc = Document()
r = RectShape(60, 40)
r.apply(QTransform.fromTranslate(30, 30))
doc.add(r)
ly = pc.print_layer(doc, "Crocette")
for n, (x, y) in enumerate(pc.mark_positions(pc.design_bounds(doc)), 1):
    doc.add(pc.make_mark(n, x, y, ly))
path = os.path.join(TMP, "croci.flcut")
doc.save(path)
doc2 = Document.load(path)
a, b = pc.find_marks(doc2)
check("progetto salvato e riaperto: le crocette ci sono ancora, al loro posto, su un livello che non incide",
      a is not None and b is not None and near(pc.mark_center(a), (22.0, 78.0)) and near(pc.mark_center(b), (98.0, 22.0))
      and doc2.layer(a.layer).output is False, (a, b))
check("crocette fuori dal disegno, in alto a sinistra e in basso a destra",
      pc.mark_center(a)[0] < 30 and pc.mark_center(a)[1] > 70 and pc.mark_center(b)[0] > 90 and pc.mark_center(b)[1] < 30)
job = gcode.generate(doc, MachineProfile())
check("il G-code taglia solo il rettangolo: le crocette non si incidono",
      job.bounds is not None and near((job.bounds.left(), job.bounds.top(), job.bounds.right(), job.bounds.bottom()),
                                      (30, 30, 90, 70), 0.01), job.bounds)

# ================================================================== 3. PDF
from PySide6.QtPdf import QPdfDocument  # noqa: E402

red = os.path.join(TMP, "rosso.png")
two = Image.new("RGB", (300, 300), (220, 20, 30))  # 30 × 30 mm: metà in alto rossa, metà in basso blu
two.paste((20, 40, 220), (0, 150, 300, 300))
two.save(red, dpi=(254, 254))
gray = io_formats.import_image(red, doc)
check("importazione normale: la foto arriva in grigi (per l'incisione)", doc.images[gray[0].image_id].mode == "L")
col = pc.import_print_image(doc, red)[0]
col.apply(QTransform.fromTranslate(45, 35))
doc.add(col)
check("immagine da stampare: resta a colori, su un livello con l'uscita spenta",
      doc.images[col.image_id].mode == "RGBA" and doc.images[col.image_id].getpixel((150, 50))[:3] == (220, 20, 30)
      and doc.layer(col.layer).output is False and col.layer != r.layer)
pdf = os.path.join(TMP, "stampa.pdf")
info = pc.export_pdf(doc, pdf, "A4")
qd = QPdfDocument()
qd.load(pdf)
pt = qd.pagePointSize(0)
check("PDF: un foglio A4 verticale", qd.pageCount() == 1 and abs(pt.width() / 72 * 25.4 - 210) < 0.3
      and abs(pt.height() / 72 * 25.4 - 297) < 0.3 and not info["landscape"], (pt, info))
K = 8  # punti per mm nella rilettura
img = qd.render(0, QSize(210 * K, 297 * K))


def px(plane_xy):
    q = info["to_page"].map(QPointF(*plane_xy))
    return q.x(), q.y()


def dark_at(page_mm, rad=0.6):
    """C'è inchiostro nero entro rad mm dal punto?"""
    cx, cy = page_mm
    n = int(rad * K)
    for j in range(-n, n + 1):
        for i in range(-n, n + 1):
            c = img.pixelColor(int(cx * K) + i, int(cy * K) + j)
            if c.alpha() > 100 and c.red() < 90 and c.green() < 90 and c.blue() < 90:
                return True
    return False


def arm_end(page_mm, ux, uy):
    """Fin dove arriva il tratto della crocetta partendo dal centro (mm)."""
    cx, cy = page_mm
    t = 0.0
    while t < 12.0 and dark_at((cx + ux * (t + 0.25), cy + uy * (t + 0.25)), 0.2):
        t += 0.125
    return t


c1, c2 = px(pc.mark_center(pc.find_marks(doc)[0])), px(pc.mark_center(pc.find_marks(doc)[1]))
check("PDF: le due crocette sono dove devono essere", dark_at(c1) and dark_at(c2), (c1, c2))
arms = [arm_end(c1, 1, 0), arm_end(c1, -1, 0), arm_end(c1, 0, 1), arm_end(c1, 0, -1)]
check("PDF in misure vere: i bracci della crocetta sono lunghi 5 mm (riletti dal PDF)",
      all(abs(a_ - pc.MARK_ARM) < 0.4 for a_ in arms), arms)
drawn = math.dist(pc.mark_center(pc.find_marks(doc)[0]), pc.mark_center(pc.find_marks(doc)[1]))
check("PDF in misure vere: fra le crocette la stessa distanza del disegno", abs(math.dist(c1, c2) - drawn) < 1e-6
      and abs((c1[0] + c2[0]) / 2 - 105) < 0.5 and abs((c1[1] + c2[1]) / 2 - 148.5) < 0.5, (c1, c2, drawn))
ic = img.pixelColor(int(px((60, 58))[0] * K), int(px((60, 58))[1] * K))
check("PDF: l'immagine è stampata a colori", ic.red() > 180 and ic.green() < 80 and ic.blue() < 90,
      (ic.red(), ic.green(), ic.blue()))
check("PDF: la linea di taglio non viene stampata", not dark_at(px((30, 50)), 0.4) and not dark_at(px((60, 70)), 0.4))
top = px((45, 65))
below = px((45, 35))
check("PDF: l'immagine è dritta e al suo posto (non capovolta né spostata)",
      img.pixelColor(int((top[0] + 1) * K), int((top[1] + 1) * K)).red() > 180
      and img.pixelColor(int((below[0] + 1) * K), int((below[1] - 1) * K)).blue() > 180
      and img.pixelColor(int((below[0] + 1) * K), int((below[1] - 1) * K)).red() < 90
      and img.pixelColor(int((top[0] - 1.5) * K), int((top[1] - 1.5) * K)).alpha() < 50)
wide = Document()
rw = RectShape(250, 120)
wide.add(rw)
lw = pc.print_layer(wide, "Crocette")
for n, (x, y) in enumerate(pc.mark_positions(pc.design_bounds(wide)), 1):
    wide.add(pc.make_mark(n, x, y, lw))
iw = pc.export_pdf(wide, os.path.join(TMP, "largo.pdf"), "A4")
qd2 = QPdfDocument()
qd2.load(os.path.join(TMP, "largo.pdf"))
check("disegno largo: il foglio diventa orizzontale", iw["landscape"] and qd2.pagePointSize(0).width() > qd2.pagePointSize(0).height())
rw.apply(QTransform.fromScale(1.2, 1.9))
for m in pc.find_marks(wide):
    wide.remove([m])
for n, (x, y) in enumerate(pc.mark_positions(pc.design_bounds(wide)), 1):
    wide.add(pc.make_mark(n, x, y, lw))
try:
    pc.export_pdf(wide, os.path.join(TMP, "troppo.pdf"), "A4")
    msg = ""
except pc.PrintCutError as exc:
    msg = str(exc)
check("disegno più grande del foglio: rifiutato, e l'A3 lo accetta", "non entrano" in msg
      and pc.export_pdf(wide, os.path.join(TMP, "a3.pdf"), "A3")["width"] in (297.0, 420.0), msg)
empty = Document()
empty.add(RectShape(10, 10))
try:
    pc.export_pdf(empty, os.path.join(TMP, "no.pdf"))
    msg = ""
except pc.PrintCutError as exc:
    msg = str(exc)
check("PDF senza crocette: rifiutato", "crocette" in msg, msg)

# ================================================================== 4. finestra
admin._HASH = hashlib.sha256((admin._SALT + "prova").encode()).hexdigest()
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
ed = w.editor
check("senza codice: Stampa e taglia è nascosto e non si apre", not w.acts["print_cut"].isVisible()
      and w.print_cut_dialog() is None)
pal = getattr(getattr(w, "banco", None), "palette", None)
if pal is not None:
    check("Banco: senza codice la ricerca dei comandi non lo trova",
          w.acts["print_cut"] not in (pal.collect(), [a_ for a_, _p in pal.entries])[1])
check("con il codice: compare in Strumenti, insieme al Rilievo 3D", w.admin_dialog(code="prova") is True
      and w.acts["print_cut"].isVisible() and w.acts["relief"].isVisible())
if pal is not None:
    check("Banco: con il codice la ricerca lo trova",
          w.acts["print_cut"] in (pal.collect(), [a_ for a_, _p in pal.entries])[1])
dlg = w.print_cut_dialog()
check("la finestra si apre, e una seconda richiesta riporta la stessa", dlg is not None and w.print_cut_dialog() is dlg)
check("piano vuoto: niente crocette, con il motivo", dlg.add_marks() is False and "vuoto" in dlg.msg.text()
      and not dlg.b_pdf.isEnabled(), dlg.msg.text())
cut = RectShape(80, 50)
cut.apply(QTransform.fromTranslate(40, 40))
ed.add([cut], "taglio")
n_undo = len(ed.undo_stack)
made = dlg.add_marks()
m1, m2 = pc.find_marks(ed.doc)
check("crocette messe attorno al disegno, su un livello che non incide", made and m1 is not None and m2 is not None
      and near(pc.mark_center(m1), (32.0, 98.0)) and near(pc.mark_center(m2), (128.0, 32.0))
      and ed.doc.layer(m1.layer).output is False and ed.doc.layer(m1.layer).label() == "Crocette", dlg.msg.text())
check("…un solo passo nella cronologia; il PDF ora si può salvare", len(ed.undo_stack) == n_undo + 1 and dlg.b_pdf.isEnabled())
cut.apply(QTransform.fromTranslate(10, 0))
dlg.add_marks()
marks = [s for s in ed.doc.shapes if s.role]
check("rimesse dopo aver spostato il disegno: sempre due, attorno al disegno di adesso", len(marks) == 2
      and near(pc.mark_center(pc.find_marks(ed.doc)[0]), (42.0, 98.0)), [pc.mark_center(m) for m in marks])
ed.undo()
ed.undo()
check("Ctrl+Z due volte: le crocette spariscono", pc.find_marks(ed.doc) == (None, None) and len(ed.doc.shapes) == 1)
cut = ed.doc.shapes[0]
dlg.add_marks()
pi = dlg.add_image(red)
check("immagine da stampare dalla finestra: a colori, uscita spenta, un passo da annullare",
      pi is not None and ed.doc.images[pi.image_id].mode == "RGBA" and ed.doc.layer(pi.layer).output is False
      and pi in ed.doc.shapes, dlg.msg.text())
ed.undo()
check("…annullata", all(s.kind != "image" for s in ed.doc.shapes))
out = dlg.save_pdf(os.path.join(TMP, "finestra.pdf"))
check("PDF dalla finestra", out is not None and os.path.getsize(os.path.join(TMP, "finestra.pdf")) > 500, dlg.msg.text())

# ================================================================== 5. simulatore: foglio storto
check("scollegato: le crocette non si possono prendere", dlg.take(1) is False and not dlg.b_take[0].isEnabled()
      and dlg.pts == [None, None], dlg.msg.text())
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings and w.ctl.last_status.get("state") == "Idle")
w.profile.homing = True
w.ctl.homed = False
dlg.refresh()
check("senza homing: rifiutato con il motivo", dlg.take(1) is False and "homing" in dlg.msg.text(), dlg.msg.text())
w.ctl.home()
until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 20)
until(lambda: dlg.head() is not None, 5)


def head_to(target):
    for _ in range(4):
        h = dlg.head()
        dx, dy = target[0] - h[0], target[1] - h[1]
        if math.hypot(dx, dy) < 0.003:
            break
        w.ctl.jog(dx, dy, 6000)
        until(lambda: w.ctl.last_status.get("state") != "Idle", 1.0)
        until(lambda: w.ctl.last_status.get("state") == "Idle" and not w.ctl.busy, 15)
        until(lambda: False, 0.5)
    return dlg.head()


def the_cut():  # dopo un Ctrl+Z le forme del documento sono oggetti nuovi: la cerco ogni volta
    return next(s_ for s_ in ed.doc.shapes if s_.kind == "rect")


m1, m2 = pc.find_marks(ed.doc)
p1, p2 = pc.mark_center(m1), pc.mark_center(m2)
corners0 = [(40, 40), (120, 40), (120, 90), (40, 90)]
SHEET = sheet(3.0, 60.0, 35.0, about=p1)  # il foglio vero: storto di 3° e spostato
h1 = head_to(mp(SHEET, p1))
check("testa portata sulla crocetta 1 del foglio", near(h1, mp(SHEET, p1), 0.02), (h1, mp(SHEET, p1)))
h0 = dlg.head()
dlg.step.setCurrentIndex(1)
dlg.jog(1, 0)
until(lambda: abs(dlg.head()[0] - h0[0] - 1.0) < 0.02, 5)
check("frecce della finestra: 1 mm a destra", abs(dlg.head()[0] - h0[0] - 1.0) < 0.02 and abs(dlg.head()[1] - h0[1]) < 0.02,
      (h0, dlg.head()))
head_to(mp(SHEET, p1))
dlg.refresh()
check("crocetta 1 presa dalla posizione della testa", dlg.take(1) is True and near(dlg.pts[0], mp(SHEET, p1), 0.02)
      and not dlg.b_align.isEnabled(), dlg.msg.text())
dlg.b_dot.setChecked(True)
check("puntino acceso dalla finestra", until(lambda: w.ctl.fire_active, 3))
head_to(mp(SHEET, p2))
dlg.refresh()
check("crocetta 2 presa", dlg.take(2) is True and near(dlg.pts[1], mp(SHEET, p2), 0.02) and dlg.b_align.isEnabled())
i_cur = w.laser.start_from.findData("current")
if i_cur >= 0:
    w.laser.start_from.setCurrentIndex(i_cur)
n_undo = len(ed.undo_stack)
res = dlg.align()
check("allineamento: ruotato di 3,00°", bool(res) and abs(res["angle"] - 3.0) < 0.02, dlg.msg.text())
check("…il puntino si spegne da solo", until(lambda: not w.ctl.fire_active, 3) and not dlg.b_dot.isChecked())
got = [mp(the_cut().tf, c) for c in ((0, 0), (80, 0), (80, 50), (0, 50))]
want = [mp(SHEET, c) for c in corners0]
err = max(math.dist(g, t) for g, t in zip(got, want))
check("il rettangolo di taglio è sopra il foglio vero (entro 0,05 mm)", err < 0.05, f"{err:.3f} mm")
check("…un solo passo nella cronologia e partenza in coordinate assolute", len(ed.undo_stack) == n_undo + 1
      and w.laser.start_from.currentData() == "absolute")
job = w.build_job(show=False)
pts = []
x = y = None
for line in job.lines:
    mm_ = re.match(r"^(?:G1 )?(?=[XY])(?:X(-?[\d.]+))? ?(?:Y(-?[\d.]+))?", line) if not line.startswith("G0") else None
    g0 = re.match(r"^G0 (?:X(-?[\d.]+))? ?(?:Y(-?[\d.]+))?", line)
    for m_ in (mm_, g0):
        if m_ and (m_.group(1) or m_.group(2)):
            x = float(m_.group(1)) if m_.group(1) else x
            y = float(m_.group(2)) if m_.group(2) else y
            if m_ is mm_ and x is not None and y is not None:
                pts.append((x, y))


def seg_dist(p, a, b):
    ax, ay, bx, by = *a, *b
    t = max(0.0, min(1.0, ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
    return math.dist(p, (ax + t * (bx - ax), ay + t * (by - ay)))


far = max((min(seg_dist(p, want[i], want[(i + 1) % 4]) for i in range(4)) for p in pts), default=99)
check("G-code: tutti i punti di taglio stanno sul rettangolo del foglio vero (entro 0,05 mm)",
      len(pts) >= 4 and far < 0.05, (len(pts), f"{far:.3f}"))
check("G-code: le crocette e l'immagine non vengono incise",
      abs(job.bounds.width() - (max(c[0] for c in want) - min(c[0] for c in want))) < 0.1, job.bounds)
ed.undo()
check("Ctrl+Z: il disegno torna com'era", near(mp(the_cut().tf, (0, 0)), (40, 40), 1e-6))

# ---- secondo foglio, con stampa più grande dello 0,3%: di nuovo dalle crocette di adesso
m1, m2 = pc.find_marks(ed.doc)
p1, p2 = pc.mark_center(m1), pc.mark_center(m2)
S2 = sheet(-1.5, 20.0, 10.0, k=1.003, about=p1)
dlg.take(1, mp(S2, p1))
dlg.take(2, mp(S2, p2))
res = dlg.align()
got = [mp(the_cut().tf, c) for c in ((0, 0), (80, 0), (80, 50), (0, 50))]
want = [mp(S2, c) for c in corners0]
check("stampa più grande dello 0,3%: con la correzione il taglio segue la stampa", bool(res)
      and max(math.dist(g, t) for g, t in zip(got, want)) < 1e-6 and abs(res["scale"] - 1.003) < 1e-6, dlg.msg.text())
ed.undo()
before = mp(the_cut().tf, (0, 0))
far_off = sheet(0.0, 400.0, 300.0)
dlg.take(1, mp(far_off, p1))
dlg.take(2, mp(far_off, p2))
check("foglio che porterebbe il taglio fuori dal piano: rifiutato, il disegno non cambia", dlg.align() is False
      and "area di lavoro" in dlg.msg.text() and near(mp(the_cut().tf, (0, 0)), before), dlg.msg.text())
dlg.take(1, (50.0, 50.0))
dlg.take(2, (50.0, 50.0))
check("stesso punto per le due crocette: rifiutato", dlg.align() is False and "coincidono" in dlg.msg.text())
dlg.b_dot.setChecked(True)
until(lambda: w.ctl.fire_active, 3)
dlg.close()
check("chiudendo la finestra il puntino si spegne", until(lambda: not w.ctl.fire_active, 3))
w.ctl.disconnect_port()

# ================================================================== 6. traduzioni
srcs = [open(os.path.join(ROOT, "freelasercut", *p), encoding="utf-8").read()
        for p in (("core", "print_cut.py"), ("ui", "dialogs_printcut.py"))]
keys = set()
for src in srcs:
    for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', src):
        keys.add("".join(json.loads(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1))))
keys |= {"Stampa e taglia (in prova)…",
         "Funzioni in prova sbloccate: nel menu Strumenti trovi Rilievo 3D su tavola e Stampa e taglia"}
check("testi della funzione trovati nel codice", len(keys) > 40, len(keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k for k in keys if not loc.get(k)]
    bad = [k for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    check(f"traduzioni {lang}: tutti i testi, con gli stessi segnaposto", not miss and not bad, (miss[:3], bad[:3]))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
