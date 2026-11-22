# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6: richieste del 17/11/2026 (coda in «freeburn/coda-0.20.6.md»).

A  foto ritagliata con una forma (Evoluzione2): per tutto il programma è solo la parte che si vede (ingombro,
   misure, maniglie, Allinea, aggancio del lavoro, Togli il ritaglio, salva e riapri, Annulla), stesso G-code;
   errore corretto: con «Posizione attuale» o «Origine utente» l'aggancio era calcolato sulla foto intera;
B  «Contorno da tagliare»: tracciato sul contorno della parte visibile, con scostamento, nel gruppo, sul livello
   giusto, che segue la foto, avviso se il taglio viene prima della foto, ritaglio di nuovo che non lo usa;
C  Prepara foto: la forma si vede sull'originale, il riquadro del ritaglio si sposta e si allarga con le maniglie
   (dentro la foto, mai troppo piccolo, Maiusc = proporzioni), la forma si toglie scegliendo Rettangolo;
D  ringraziamenti: la precisazione (chi aiuta con continuità o con un contributo importante) nel rapporto, nella
   targa, nell'informativa privacy, nel sito e nel README;
E  ingranaggio con i parametri veri: evolvente, modulo, angolo di pressione, gioco, raccordo, foro, foro a D, cava,
   alleggerimenti; due ruote dello stesso modulo ingranano; ingranaggi vecchi identici; pannello Proprietà;
F  testi nuovi tradotti in tutte le lingue.
Uso: python tests/test_v206_richieste.py [classica|banco]
"""
import json
import math
import os
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
import pyclipper  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDoubleSpinBox, QMessageBox, QPushButton  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.core import gcode, gears, geom, ops, photo, photo_clip, shapes_lib  # noqa: E402
from freelasercut.core.document import (  # noqa: E402
    Document, GroupShape, ImageShape, PathShape, RectShape, SpecialShape, shape_from_dict,
)
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui import dialogs_report, dialogs_thanks  # noqa: E402
from freelasercut.ui.dialogs_photo import PhotoDialog, _View  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

UI = os.environ["FLC_UI"]
results = []
hidden = []


def _hook(tp, ex, tb):
    hidden.append(ex)
    import traceback

    traceback.print_exception(tp, ex, tb)


sys.excepthook = _hook


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def spin(sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def near(a, b, tol=0.05):
    return abs(a - b) <= tol


def same_rect(r1, r2, tol=0.05):
    return all(near(a, b, tol) for a, b in ((r1.left(), r2.left()), (r1.top(), r2.top()),
                                            (r1.right(), r2.right()), (r1.bottom(), r2.bottom())))


def burn_points(job, step=0.05, shift=None):
    """Punti dove il laser è acceso (tratti G1 con S > 0), sul piano (o spostati di `shift`)."""
    x = y = s = 0.0
    on, mode, pts = False, "0", []
    ox, oy = job.out_to_bed if shift is None else shift
    for ln in job.lines:
        t = ln.split(";")[0].strip().upper()
        if not t:
            continue
        if t.startswith(("M3", "M4")):
            on = True
        if t.startswith("M5"):
            on = False
        g = re.match(r"G([01])\b", t)
        if g:
            mode = g.group(1)
        vals = {k: float(v) for k, v in re.findall(r"([XYS])(-?[\d.]+)", t)}
        s = vals.get("S", s)
        nx, ny = vals.get("X", x), vals.get("Y", y)
        if mode == "1" and on and s > 0 and (nx, ny) != (x, y):
            n = max(1, int(math.hypot(nx - x, ny - y) / step))
            pts += [(x + (nx - x) * k / n + ox, y + (ny - y) * k / n + oy) for k in range(n + 1)]
        x, y = nx, ny
    return np.array(pts) if pts else np.zeros((0, 2))


def world_path(s):
    from PySide6.QtGui import QPainterPath

    p = QPainterPath()
    for leaf, tf in s.leaves():
        p.addPath(tf.map(leaf.local_path()))
    return p


def hausdorff(pa, pb, tol=0.01):
    """Distanza di Hausdorff fra due contorni (mm), sui punti appiattiti."""
    def dense(path):  # punti ogni 0,02 mm lungo i contorni (i vertici da soli sono radi sui tratti dritti)
        out = []
        for p in geom.flatten(path, tol):
            pts = p.pts + ([p.pts[0]] if p.closed else [])
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 0.02))
                out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
        return np.array(out)
    a, b = dense(pa), dense(pb)
    if not len(a) or not len(b):
        return 99.0

    def one(u, v):
        best = 0.0
        for i in range(0, len(u), max(1, len(u) // 1500)):
            d = np.min(np.hypot(v[:, 0] - u[i, 0], v[:, 1] - u[i, 1]))
            best = max(best, float(d))
        return best
    return max(one(a, b), one(b, a))


def dists(pa, pb, tol=0.01):
    """Per ogni punto del contorno pa, la distanza dal contorno pb -> (minima, massima) in mm."""
    def dense(path):
        out = []
        for p in geom.flatten(path, tol):
            pts = p.pts + ([p.pts[0]] if p.closed else [])
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 0.02))
                out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
        return np.array(out)
    a, b = dense(pa), dense(pb)
    d = [float(np.min(np.hypot(b[:, 0] - a[i, 0], b[:, 1] - a[i, 1]))) for i in range(0, len(a), max(1, len(a) // 1500))]
    return min(d), max(d)


def area_of(path, tol=0.01):
    return abs(sum(p.area() for p in geom.flatten(path, tol) if p.closed))


w = MainWindow()
ed = w.editor
msgs = []
ed.message.connect(msgs.append)


def make_doc(photo_tf=None, heart_tf=None, heart=(20, 20)):
    doc = Document()
    doc.images["p"] = Image.fromarray(np.full((150, 200), 0, np.uint8))  # foto nera: dentro si incide tutto
    im = ImageShape("p", 40, 30, layer=2)
    im.set_transform(photo_tf or QTransform.fromTranslate(50, 50))
    doc.add(im)
    doc.layer(2).mode = "image"
    hs = SpecialShape("heart", heart[0], heart[1], layer=1)
    hs.set_transform(heart_tf or QTransform.fromTranslate(54, 53))  # in basso a sinistra nella foto (non al centro)
    doc.add(hs)
    ed.set_document(doc)
    ed.select([im, hs])
    spin(0.03)
    return doc, im, hs


def job_of(doc, start="absolute", anchor=0, pos=(0.0, 0.0), dpi=127.0):
    for cs in doc.layers.values():
        if cs.mode == "image":
            cs.dpi, cs.dither = dpi, "threshold"
    return gcode.generate(doc, MachineProfile(), gcode.JobOptions(start_from=start, anchor=anchor, current_pos=pos,
                                                                   work_origin=pos))


# ====================================================================== A. ingombro della foto ritagliata
print("--- A. foto ritagliata = solo la parte che si vede")
doc, im, hs = make_doc()
heart_b = hs.bounds()
full_b = im.bounds()
ed.clip_photo()
g = doc.shapes[0]
check("A ingombro della foto = quello del cuore (prima la foto intera 40 × 30)", same_rect(im.bounds(), heart_b),
      (im.bounds(), heart_b))
check("A ingombro del gruppo e della selezione = il cuore", same_rect(g.bounds(), heart_b)
      and same_rect(ed.selection_bounds(), heart_b))
check("A i pixel restano interi (photo_path = 40 × 30)", same_rect(im.tf.map(im.photo_path()).boundingRect(), full_b))
# cuore che esce dalla foto: conta solo la parte che si vede (sagoma ∩ foto)
doc, im, hs = make_doc(heart_tf=QTransform.fromTranslate(80, 60))  # esce a destra (foto fino a x = 90)
hb = hs.bounds()
ed.clip_photo()
vis = im.bounds()
check("A cuore che esce dalla foto: ingombro = solo la parte sopra la foto", near(vis.right(), 90.0, 0.02)
      and near(vis.left(), hb.left(), 0.05) and vis.width() < hb.width() - 5, (vis, hb))
# trasformazioni: foto ruotata e scalata, gruppo specchiato
ptf = QTransform.fromTranslate(-20, -15) * QTransform().rotate(30) * QTransform.fromScale(1.5, 1.2) * QTransform.fromTranslate(80, 90)
doc, im, hs = make_doc(photo_tf=ptf, heart_tf=QTransform.fromTranslate(70, 80))
hb = hs.bounds()
ed.clip_photo()
check("A foto ruotata e scalata: ingombro = il cuore", same_rect(im.bounds(), hb, 0.06), (im.bounds(), hb))
g = doc.shapes[0]
ed.select([g])
ed.transform(QTransform.fromTranslate(-100, 0) * QTransform(-1, 0, 0, 1, 0, 0) * QTransform.fromTranslate(200, 0))
hs_now = g.children[1]
check("A gruppo specchiato dopo il ritaglio: ingombro della foto = il cuore specchiato",
      same_rect(list(im.leaves(g.tf))[0][1].map(im.local_path()).boundingRect(),
                list(hs_now.leaves(g.tf))[0][1].map(hs_now.local_path()).boundingRect(), 0.06))
# misure dalla barra (L): si scala la parte che si vede
doc, im, hs = make_doc()
ed.clip_photo()
g = doc.shapes[0]
b0 = g.bounds()
k = 40.0 / b0.width()
ed.transform(QTransform.fromTranslate(-b0.left(), -b0.top()) * QTransform.fromScale(k, k)
             * QTransform.fromTranslate(b0.left(), b0.top()))
check("A larghezza portata a 40 mm: il cuore visibile è largo 40 (la foto intera di più)", near(g.bounds().width(), 40.0, 0.05)
      and list(im.leaves(g.tf))[0][1].map(im.photo_path()).boundingRect().width() > 60, g.bounds().width())
# Allinea a sinistra con un rettangolo: si allinea il bordo del cuore
doc, im, hs = make_doc()
ed.clip_photo()
g = doc.shapes[0]
r = RectShape(10, 10, layer=1)
r.set_transform(QTransform.fromTranslate(10, 10))
ed.add([r])
ed.select([g, r])
ed.align("left")
check("A Allinea a sinistra: il bordo del cuore va sul bordo del rettangolo (non quello della foto intera)",
      near(g.bounds().left(), 10.0, 0.05) and near(r.bounds().left(), 10.0, 0.05), g.bounds().left())
# Togli il ritaglio: torna la foto intera
doc, im, hs = make_doc()
ed.clip_photo()
ed.select([doc.shapes[0]])
ed.unclip_photo()
check("A Togli il ritaglio: l'ingombro torna quello della foto intera", same_rect(im.bounds(), full_b))
ed.undo()
im_u = [l for s in ed.doc.shapes for l, _ in s.leaves() if isinstance(l, ImageShape)][0]
check("A Annulla del «Togli il ritaglio»: di nuovo solo il cuore", same_rect(im_u.bounds(), heart_b, 0.06), im_u.bounds())
# salva e riapri
d = ed.doc.shapes[0].to_dict()
g2 = shape_from_dict(json.loads(json.dumps(d)))
im2 = [l for l, _ in g2.leaves() if isinstance(l, ImageShape)][0]
check("A salva e riapri: stesso ingombro", same_rect(g2.bounds(), heart_b, 0.06) and same_rect(im2.bounds(), heart_b, 0.06))
# foto non ritagliata: identica a prima
plain = ImageShape("p", 40, 30)
check("A foto non ritagliata: il contorno è il suo riquadro, come prima", plain.local_path() == plain.photo_path())
# sagoma che non copre la foto (file rovinato): resta la foto intera, niente ingombro vuoto
odd = ImageShape("p", 40, 30)
odd.clip = [[[[100, 100], [110, 100], [110, 110]]]]
check("A sagoma fuori dalla foto: ingombro della foto intera (mai vuoto)", same_rect(odd.bounds(), QRectF(0, 0, 40, 30)))

# ====================================================================== A2. G-code e aggancio
print("--- A2. G-code: stesso disegno, aggancio sulla parte visibile")
doc, im, hs = make_doc()
ed.clip_photo()
new_lines = job_of(doc).lines
orig_lp = ImageShape.local_path
ImageShape.local_path = ImageShape.photo_path  # com'era fino alla 0.20.5
for s in doc.all_shapes() if hasattr(doc, "all_shapes") else doc.shapes:
    for leaf, _ in s.leaves():
        leaf.invalidate()
old_lines = job_of(doc).lines
old_cur = burn_points(job_of(doc, "current", 4, (100.0, 100.0)), shift=(0.0, 0.0))
ImageShape.local_path = orig_lp
for s in doc.shapes:
    for leaf, _ in s.leaves():
        leaf.invalidate()
    s.invalidate()
check("A2 partenza assoluta: G-code identico riga per riga a quello della 0.20.5", new_lines == old_lines,
      (len(new_lines), len(old_lines)))
hb = hs.bounds()
step = 25.4 / 127.0
for anchor, name in ((4, "centro"), (0, "basso-sinistra"), (8, "alto-destra")):
    P = burn_points(job_of(doc, "current", anchor, (100.0, 100.0)), shift=(0.0, 0.0))
    ax = [hb.left(), hb.center().x(), hb.right()][anchor % 3]
    ay = [hb.top(), hb.center().y(), hb.bottom()][anchor // 3]
    # i punti incisi sono relativi alla testa: il punto d'aggancio del cuore deve essere sotto la testa (0, 0)
    ex = [P[:, 0].min(), (P[:, 0].min() + P[:, 0].max()) / 2, P[:, 0].max()][anchor % 3]
    ey = [P[:, 1].min(), (P[:, 1].min() + P[:, 1].max()) / 2, P[:, 1].max()][anchor // 3]
    check(f"A2 «Posizione attuale», aggancio {name}: il cuore è sotto la testa", len(P) > 100 and near(ex, 0.0, step)
          and near(ey, 0.0, step), (round(ex, 3), round(ey, 3)))
oc = ((old_cur[:, 0].min() + old_cur[:, 0].max()) / 2, (old_cur[:, 1].min() + old_cur[:, 1].max()) / 2)
check("A2 …prima (0.20.5) il cuore finiva spostato di qualche mm (era l'errore)", math.hypot(*oc) > 2.0,
      (round(oc[0], 2), round(oc[1], 2)))
P = burn_points(job_of(doc, "origin", 4, (60.0, 70.0)), shift=(0.0, 0.0))
check("A2 «Origine utente», al centro: il cuore è centrato sull'origine",
      near((P[:, 0].min() + P[:, 0].max()) / 2, 0.0, step) and near((P[:, 1].min() + P[:, 1].max()) / 2, 0.0, step))

# ====================================================================== B. Contorno da tagliare
print("--- B. Contorno da tagliare")
doc, im, hs = make_doc()
ed.clip_photo()
g = doc.shapes[0]
ed.select([g])
w._update_sel_actions()
check("B comando attivo sul gruppo ritagliato", w.acts["photo_cut_outline"].isEnabled())
ed.current_layer = 3
doc.layer(3).mode = "line"
made = ed.cut_outline(0.0)
check("B un tracciato, nel gruppo, sul livello attivo (3), marcato come contorno da tagliare",
      len(made) == 1 and made[0] in g.children and made[0].layer == 3 and made[0].role == ops.CUT_OUTLINE)
cut_w = list(made[0].leaves(g.tf))[0][1].map(made[0].local_path())
heart_w = list(hs.leaves(g.tf))[0][1].map(hs.local_path())
check("B scostamento 0: il contorno coincide con il cuore", hausdorff(cut_w, heart_w) < 0.05, round(hausdorff(cut_w, heart_w), 4))
check("B la sagoma del ritaglio resta sul livello strumenti", hs.layer == 30)
job = gcode.generate(doc, MachineProfile(), gcode.JobOptions(start_from="absolute"))
txt = "\n".join(job.lines)
vec = [ln for ln in job.lines if ln.startswith("G1") and "S" in ln]
check("B nel G-code c'è anche il taglio del contorno (non solo la foto)", len(job.lines) > 0 and
      any("livello" in ln.lower() and "3" in ln for ln in job.lines if ln.startswith(";")), [ln for ln in job.lines if ln.startswith(";")][:6])
ed.undo()
g = ed.doc.shapes[0]
check("B Annulla: il contorno sparisce", not any(getattr(c, "role", "") == ops.CUT_OUTLINE for c in g.children))
ed.select([g])
made = ed.cut_outline(0.1)
cut_w = list(made[0].leaves(g.tf))[0][1].map(made[0].local_path())
hs = g.children[1]
heart_w = list(hs.leaves(g.tf))[0][1].map(hs.local_path())
d = dists(cut_w, heart_w)
check("B scostamento 0,1 mm: ogni punto del contorno è a 0,1 mm dal cuore, fuori (sagoma salvata a 0,02 mm)", near(d[0], 0.1, 0.025)
      and near(d[1], 0.1, 0.02) and area_of(cut_w) > area_of(heart_w), (round(d[0], 4), round(d[1], 4)))
ed.undo()
g = ed.doc.shapes[0]
ed.select([g])
made = ed.cut_outline(-0.5)
cut_w = list(made[0].leaves(g.tf))[0][1].map(made[0].local_path())
check("B scostamento negativo: il contorno sta dentro (area minore)", area_of(cut_w) < area_of(heart_w) - 1)
# il contorno si sposta con la foto
ed.select([g])
ed.transform(QTransform().rotate(37) * QTransform.fromTranslate(30, 40))
cut_w = list(made[0].leaves(g.tf))[0][1].map(made[0].local_path())
vis_w = list(g.children[0].leaves(g.tf))[0][1].map(g.children[0].local_path())
d_in = dists(cut_w, vis_w)
check("B gruppo ruotato e spostato: il contorno resta mezzo millimetro dentro la foto ritagliata",
      near(d_in[0], 0.5, 0.03) and near(d_in[1], 0.5, 0.03), d_in)
# ritaglia di nuovo: la sagoma non cambia (non conta il contorno da tagliare)
clip_before = json.dumps(g.children[0].clip)
ed.select([g])
ed.clip_photo()
check("B ritagliando di nuovo il gruppo il contorno da tagliare non entra nella sagoma",
      json.dumps(ed.doc.shapes[0].children[0].clip) == clip_before)
# Togli il ritaglio: il contorno resta sul suo livello
ed.select([ed.doc.shapes[0]])
ed.unclip_photo()
cuts = [l for s in ed.doc.shapes for l, _ in s.leaves() if l.role == ops.CUT_OUTLINE]
check("B Togli il ritaglio: il contorno da tagliare resta, sul livello 3", len(cuts) == 1 and cuts[0].layer == 3)
# livello attivo di foto: va su un altro livello e lo dice
doc, im, hs = make_doc()
ed.clip_photo()
ed.current_layer = 2  # livello della foto (Immagine)
msgs.clear()
made = ed.cut_outline(0.0)
check("B livello attivo con la foto: il contorno va sul livello che aveva il cuore (1)",
      made and made[0].layer == 1 and doc.layer(1).mode != "image", made[0].layer if made else None)
# livello del taglio prima di quello della foto: avviso
doc, im, hs = make_doc()
ed.clip_photo()
doc.layer(2).priority, doc.layer(0).priority = 5, 0
ed.current_layer = 0
msgs.clear()
ed.cut_outline(0.0)
check("B il taglio verrebbe prima della foto: lo dice", any("prima di inciderla" in m for m in msgs), msgs[-1:] if msgs else "")
# niente di ritagliato selezionato
ed.select([])
msgs.clear()
check("B senza foto ritagliata: niente e un messaggio", ed.cut_outline(0.0) == [] and msgs)
# cuore che esce dalla foto: contorno sulla parte visibile
doc, im, hs = make_doc(heart_tf=QTransform.fromTranslate(80, 60))
ed.clip_photo()
ed.current_layer = 3
made = ed.cut_outline(0.0)
g = doc.shapes[0]
cb = list(made[0].leaves(g.tf))[0][1].map(made[0].local_path()).boundingRect()
check("B cuore che esce dalla foto: si taglia il contorno di quello che si vede", near(cb.right(), 90.0, 0.02))
# menu
names = []
for m in w.menuBar().findChildren(type(w.menuBar().actions()[0].menu())):
    names += list(m.actions())
check("B nel menu Disponi e con il suo aiuto", w.acts["photo_cut_outline"] in names)
from freelasercut.ui import help_texts  # noqa: E402

check("B scheda di aiuto del comando", "photo_cut_outline" in help_texts.HELP)
os.environ.pop("FLC_NO_DIALOGS", None)
from PySide6.QtWidgets import QInputDialog  # noqa: E402

asked = {}
orig_gd = QInputDialog.getDouble


def fake_gd(*a, **k):
    asked["v"] = a[3] if len(a) > 3 else None
    return 0.1, True


QInputDialog.getDouble = staticmethod(fake_gd)
doc, im, hs = make_doc()
ed.clip_photo()
ed.current_layer = 3
made = w.cut_outline_dialog()
made2 = None
ed.undo()
ed.select([ed.doc.shapes[0]])
made2 = w.cut_outline_dialog()
QInputDialog.getDouble = orig_gd
os.environ["FLC_NO_DIALOGS"] = "1"
check("B la finestra chiede lo scostamento e ricorda l'ultimo", made and made2 and asked.get("v") == 0.1)

# ====================================================================== C. Prepara foto
print("--- C. Prepara foto: forma sull'originale, riquadro che si sposta e si allarga")
v = _View("prova", croppable=True, zoomable=True)
v.resize(420, 340)
from PySide6.QtGui import QImage  # noqa: E402

qi = QImage(300, 200, QImage.Format_Grayscale8)
qi.fill(60)
v.qimg = qi
v.crop = (0.2, 0.2, 0.6, 0.7)
v.show()
spin(0.05)
r = v._crop_rect()
check("C la forma Rettangolo non disegna niente in più", v.form_outline(r) is None)
for m in photo.FORM_MASKS | {"oval", "rounded"}:
    v.form = m
    fo = v.form_outline(r)
    if fo is None:
        check(f"C forma {m} sull'originale", False)
        continue
    fb = fo.boundingRect()
    # la stessa forma che photo.shape_mask taglia, nel riquadro del ritaglio
    inside = r.adjusted(-0.6, -0.6, 0.6, 0.6).contains(fb)
    touches = near(fb.width(), r.width(), 1.0) or near(fb.height(), r.height(), 1.0)
    centered = near(fb.center().x(), r.center().x(), 1.0) and near(fb.center().y(), r.center().y(), 1.0)
    check(f"C forma «{m}» disegnata dentro il riquadro, la più grande che ci sta, al centro", inside and touches and centered)
v.form = "heart"
img = v.grab().toImage()
check("C con il cuore fuori dalla forma la foto originale si schiarisce (si vede che cosa resta)",
      QImage.pixelColor(img, int(r.left() + 3), int(r.top() + 3)).lightness()
      > QImage.pixelColor(img, int(r.center().x()), int(r.center().y())).lightness() + 20)
# maniglie
c = r.center()
check("C dentro il riquadro: si sposta", v.crop_part(c) == "move")
check("C sugli angoli e sui lati: si allarga", v.crop_part(r.topLeft()) == "lt" and v.crop_part(r.bottomRight()) == "rb"
      and v.crop_part(QPointF(r.right(), c.y())) == "r" and v.crop_part(QPointF(c.x(), r.top())) == "t")
check("C fuori dal riquadro: ritaglio nuovo", v.crop_part(QPointF(r.right() + 30, c.y())) is None)
v.crop = (0.0, 0.0, 1.0, 1.0)
check("C foto intera: dentro si disegna un ritaglio nuovo (come prima)", v.crop_part(v._crop_rect().center()) is None)
v.crop = (0.2, 0.2, 0.6, 0.7)
crop0 = tuple(v.crop)
mv = v.edit_crop("move", (0.4, 0.4), crop0, (0.5, 0.45))
check("C spostato: stessa misura, spostato di quanto il mouse", all(near(a, b, 1e-9) for a, b in
                                                                   zip(mv, (0.3, 0.25, 0.7, 0.75))))
mv = v.edit_crop("move", (0.4, 0.4), crop0, (1.5, -2.0))
check("C spostato oltre il bordo: resta dentro la foto, stessa misura", near(mv[2], 1.0, 1e-9) and near(mv[1], 0.0, 1e-9)
      and near(mv[2] - mv[0], 0.4, 1e-9) and near(mv[3] - mv[1], 0.5, 1e-9))
rs = v.edit_crop("rb", (0.6, 0.7), crop0, (0.8, 0.9))
check("C angolo in basso a destra tirato: si allarga, l'angolo opposto resta fermo", all(near(a, b, 1e-9) for a, b in
                                                                                         zip(rs, (0.2, 0.2, 0.8, 0.9))))
rs = v.edit_crop("l", (0.2, 0.5), crop0, (0.9, 0.5))
check("C lato tirato oltre l'altro: il riquadro non si rovescia e non va sotto il minimo",
      near(rs[2] - rs[0], v.MIN_CROP, 1e-9) and near(rs[2], 0.6, 1e-9))
rs = v.edit_crop("lt", (0.2, 0.2), crop0, (-3.0, -3.0))
check("C angolo oltre la foto: si ferma al bordo", near(rs[0], 0.0, 1e-9) and near(rs[1], 0.0, 1e-9))
asp0 = (crop0[2] - crop0[0]) * 300 / ((crop0[3] - crop0[1]) * 200)
rs = v.edit_crop("rb", (0.6, 0.7), crop0, (0.9, 0.75), keep_aspect=True)
asp = (rs[2] - rs[0]) * 300 / ((rs[3] - rs[1]) * 200)
check("C con Maiusc l'angolo tiene le proporzioni e l'angolo opposto", near(asp, asp0, 1e-6) and near(rs[0], 0.2, 1e-9)
      and near(rs[1], 0.2, 1e-9) and rs[2] <= 1.0 + 1e-9 and rs[3] <= 1.0 + 1e-9, (round(asp, 4), round(asp0, 4), rs))
rs = v.edit_crop("rb", (0.6, 0.7), crop0, (3.0, 3.0), keep_aspect=True)
asp = (rs[2] - rs[0]) * 300 / ((rs[3] - rs[1]) * 200)
check("C con Maiusc oltre la foto: proporzioni tenute e dentro la foto", near(asp, asp0, 1e-6) and rs[2] <= 1.0 + 1e-9
      and rs[3] <= 1.0 + 1e-9)
# trascinamento vero con il mouse
from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402


def mouse(kind, pos, btn=Qt.LeftButton, mods=Qt.NoModifier):
    ev = QMouseEvent(kind, QPointF(pos), QPointF(pos), btn, btn if kind != QEvent.MouseButtonRelease else Qt.NoButton, mods)
    {QEvent.MouseButtonPress: v.mousePressEvent, QEvent.MouseMove: v.mouseMoveEvent,
     QEvent.MouseButtonRelease: v.mouseReleaseEvent}[kind](ev)


got = []
v.crop_changed.connect(got.append)
r = v._crop_rect()
t = v._target()
mouse(QEvent.MouseButtonPress, r.center())
mouse(QEvent.MouseMove, r.center() + QPointF(t.width() * 0.1, 0))
mouse(QEvent.MouseButtonRelease, r.center() + QPointF(t.width() * 0.1, 0))
check("C trascinando dentro con il mouse il riquadro si sposta (e il ritaglio cambia una volta)",
      got and near(got[-1][0], 0.3, 0.01) and near(got[-1][2], 0.7, 0.01) and near(got[-1][1], 0.2, 0.01), got[-1:])
r = v._crop_rect()
mouse(QEvent.MouseButtonPress, r.bottomRight())
mouse(QEvent.MouseMove, r.bottomRight() + QPointF(t.width() * 0.1, t.height() * 0.1))
mouse(QEvent.MouseButtonRelease, r.bottomRight() + QPointF(t.width() * 0.1, t.height() * 0.1))
check("C tirando l'angolo con il mouse il riquadro si allarga", near(got[-1][2], 0.8, 0.01) and near(got[-1][3], 0.8, 0.01)
      and near(got[-1][0], 0.3, 0.01), got[-1:])
v.hint_mode = "keep"
check("C con il pennello del soggetto le maniglie non rubano il clic", v.crop_part(v._crop_rect().center()) is None)
v.hint_mode = None
v.close()
# finestra vera: la forma scelta passa all'originale e si toglie scegliendo Rettangolo
docp = Document()
src = Image.fromarray(np.full((200, 300), 40, np.uint8))
docp.images["a"] = src
sh = ImageShape("a", 60, 40, layer=2)
dlg = PhotoDialog(sh, src, docp.layer(2), (60, 40))
dlg.mask.setCurrentIndex(dlg.mask.findData("star"))
check("C nella finestra la forma scelta si vede sull'originale", dlg.v_orig.form == "star")
dlg._refresh()
dlg.mask.setCurrentIndex(dlg.mask.findData("none"))
dlg._refresh()
st = dlg.settings()
res = np.asarray(photo.process(src, st))
check("C scegliendo Rettangolo la forma si toglie subito (anteprima, originale e risultato)",
      dlg.v_orig.form == "none" and st.mask == "none" and res.max() < 60)
dlg.close()
# applicata, riaperta e tolta: sul piano torna la foto senza forma
doc = Document()
doc.images["a"] = Image.fromarray(np.full((200, 300), 40, np.uint8))
s = ImageShape("a", 60, 40, layer=2)
doc.add(s)
doc.layer(2).mode = "image"
ed.set_document(doc)
ed.select([s])


def run_dialog(mask):
    def ex(self):
        self.show()
        app.processEvents()
        self.mask.setCurrentIndex(self.mask.findData(mask))
        self._timer.stop()
        self._refresh()
        self._accept()
        return QDialog.Accepted
    orig = PhotoDialog.exec
    PhotoDialog.exec = ex
    w.photo_dialog()
    PhotoDialog.exec = orig
    spin(0.05)
    im_ = [l for x in ed.doc.shapes for l, _ in x.leaves() if isinstance(l, ImageShape)][0]
    ed.select([x for x in ed.doc.shapes])
    return np.asarray(ed.doc.images[im_.image_id])


a1 = run_dialog("heart")
a2 = run_dialog("none")
check("C cuore applicato, poi Rettangolo: sul piano la foto torna senza forma", a1[:5, :5].min() >= 250 and a2.max() <= 45)

# ====================================================================== D. ringraziamenti
print("--- D. ringraziamenti: dalla 0.20.6 chi aiuta in modo attivo e con regolarità, o con una donazione")
rep = dialogs_report.ReportDialog(w) if hasattr(dialogs_report, "ReportDialog") else None
if rep is not None:
    note = rep.thanks_note.text()
    check("D rapporto: la nota dice chi entra nell'elenco e non promette più che il nome comparirà",
          "in modo attivo e con regolarità" in note and "donazione" in note and "comparirà" not in note
          and "freelasercut@gmail.com" in note)
    check("D rapporto: il segnaposto non promette", "se vuoi comparire" not in rep.thanks_name.placeholderText())
    rep.close()
else:
    check("D finestra del rapporto trovata", False)
src_thanks = open(os.path.join(ROOT, "freelasercut", "ui", "dialogs_thanks.py"), encoding="utf-8").read()
check("D targa in Aiuto: stessa precisazione", "in modo attivo e con regolarità, o con una donazione" in src_thanks
      and "Vuoi esserci anche tu" not in src_thanks)
priv = open(os.path.join(ROOT, "docs", "privacy.html"), encoding="utf-8").read()
check("D informativa privacy (inglese e italiano): non per ogni rapporto, data aggiornata",
      "not for every report" in priv and "non per ogni rapporto" in priv and any(f"Last updated: {d} November 2026" in priv for d in range(18, 31))
      and "donation" in priv and "donazione" in priv)
site = open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8").read()
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("D sito e README: fino alla 0.20.6 chi ha lasciato un nome, poi chi aiuta con regolarità o con una donazione",
      "actively and regularly" in site and "in modo attivo e con regolarità" in site
      and "in modo attivo e con regolarità" in readme and "Fino alla versione 0.20.6" in readme
      and "Fino alla versione 0.20.6" in site and "Vuoi esserci anche tu" not in readme)

# ====================================================================== E. ingranaggio
print("--- E. ingranaggio con i parametri veri")


def rings_to_paths(rings):
    return [[(int(round(x * 1e4)), int(round(y * 1e4))) for x, y in r] for r in rings]


def area_rings(rings):
    return sum(pyclipper.Area(p) for p in rings_to_paths(rings)) / 1e8


def place(rings, dx, ang):
    c, s_ = math.cos(ang), math.sin(ang)
    return [[(x * c - y * s_ + dx, x * s_ + y * c) for x, y in r] for r in rings]


def overlap(a, b):
    pc = pyclipper.Pyclipper()
    pc.AddPaths(rings_to_paths(a), pyclipper.PT_SUBJECT, True)
    pc.AddPaths(rings_to_paths(b), pyclipper.PT_CLIP, True)
    got = pc.Execute(pyclipper.CT_INTERSECTION, pyclipper.PFT_EVENODD, pyclipper.PFT_EVENODD)
    return sum(abs(pyclipper.Area(p)) for p in got) / 1e8


ok_dims = True
for z, m in ((6, 1.0), (12, 2.0), (16, 1.5), (40, 0.8), (120, 0.5)):
    rings = gears.profile(z, m, {"hole": 0})
    rad = [math.hypot(x, y) for x, y in rings[0]]
    r_, rb, ra, rf = gears.radii(z, m)
    ok_dims = ok_dims and near(max(rad), ra, 0.01) and near(min(rad), rf, 0.02) and len(rings) == 1
    if not (near(max(rad), ra, 0.01) and near(min(rad), rf, 0.02)):
        print("    ", z, m, max(rad), ra, min(rad), rf)
check("E diametro esterno = m·(z+2), piede = m·(z−2,5), per pochi e tanti denti", ok_dims)
# spessore del dente sul diametro primitivo = π·m/2 − gioco
for bl in (0.0, 0.2):
    z, m = 20, 2.0
    rings = gears.profile(z, m, {"hole": 0, "backlash": bl, "fillet": 0})
    r_ = m * z / 2
    ang = np.linspace(-math.pi / z, math.pi / z, 4001)  # un passo, centrato sul dente 0
    import cv2  # noqa: E402

    poly = np.array(rings[0], np.float32)
    inside = np.array([cv2.pointPolygonTest(poly, (float(r_ * math.cos(a)), float(r_ * math.sin(a))), False) > 0
                       for a in ang])
    arc = inside.sum() * (ang[1] - ang[0]) * r_
    check(f"E spessore del dente sul primitivo = π·m/2 − gioco (gioco {bl} mm)", near(arc, math.pi * m / 2 - bl, 0.02),
          round(arc, 4))
# due ruote dello stesso modulo ingranano: all'interasse giusto non si toccano (con gioco), senza gioco appena
for z1, z2, pa in ((12, 20, 20.0), (16, 16, 14.5), (10, 30, 25.0)):
    m = 2.0
    g1 = gears.profile(z1, m, {"hole": 0, "pa": pa, "backlash": 0.1})
    g2 = gears.profile(z2, m, {"hole": 0, "pa": pa, "backlash": 0.1})
    a_ = m * (z1 + z2) / 2
    worst = 0.0
    for k in range(12):  # ruotano insieme: la seconda gira al contrario, con il rapporto dei denti
        t1 = k * (2 * math.pi / z1) / 12
        t2 = math.pi + math.pi / z2 - t1 * z1 / z2
        worst = max(worst, overlap(place(g1, 0, t1), place(g2, a_, t2)))
    loose = gears.profile(z2, m, {"hole": 0, "pa": pa})
    tight_gap = overlap(place(g1, 0, 0), place(loose, a_ - 0.4, math.pi + math.pi / z2))
    check(f"E {z1} e {z2} denti, {pa:g}°: all'interasse m·(z1+z2)/2 girano senza toccarsi; più vicine si toccano",
          worst < 0.01 and tight_gap > 0.05, (round(worst, 4), round(tight_gap, 3)))
# foro, foro a D, cava, alleggerimenti
rings = gears.profile(20, 2, {"hole": 8})
hole = [r for r in rings[1:]]
hr = [math.hypot(x, y) for x, y in hole[0]]
check("E foro di 8 mm al centro (anello orario)", len(rings) == 2 and near(max(hr), 4.0, 0.02) and near(min(hr), 4.0, 0.05)
      and gears._area_of(rings[1]) < 0 < gears._area_of(rings[0]))
rings = gears.profile(20, 2, {"hole": 8, "flat": 3})
ys = [y for x, y in rings[1]]
check("E foro a D: il lato piatto a 3 mm dal centro", near(max(ys), 3.0, 0.01) and near(min(ys), -4.0, 0.05))
rings = gears.profile(20, 2, {"hole": 8, "key_w": 2, "key_h": 1.5})
ys = [y for x, y in rings[1]]
xs_top = [x for x, y in rings[1] if y > 4.5]
check("E cava per linguetta 2 × 1,5 mm oltre il foro", near(max(ys), 5.5, 0.01) and near(max(xs_top) - min(xs_top), 2.0, 0.01))
full = area_rings(gears.profile(60, 1.5, {"hole": 10}))
for k in (3, 4, 5, 6, 8):
    rings = gears.profile(60, 1.5, {"hole": 10, "spokes": k})
    check(f"E {k} alleggerimenti: {k} finestre, ruota più leggera, denti uguali", len(rings) == 2 + k
          and area_rings(rings) < full * 0.8 and rings[0] == gears.profile(60, 1.5, {"hole": 10})[0])
rings = gears.profile(8, 1.0, {"spokes": 6})
check("E ruota piccola: gli alleggerimenti non ci stanno e non si fanno", len(rings) == 2)
check("E raccordo al piede automatico: il fondo è arrotondato (area diversa da senza raccordo)",
      abs(area_rings(gears.profile(20, 2, {"hole": 0})) - area_rings(gears.profile(20, 2, {"hole": 0, "fillet": 0}))) > 0.5)
big_f = gears.profile(12, 2, {"hole": 0, "fillet": 50})
check("E raccordo enorme: limitato, i vani fra i denti restano (12 denti)",
      min(math.hypot(x, y) for x, y in big_f[0]) < gears.radii(12, 2)[0] - 1.0)
check("E opzioni rovinate in un file: ripulite", gears.clean({"pa": "x", "spokes": 7, "hole": -3, "zz": 1, "fillet": None})
      == {"spokes": 0, "hole": 0.0, "fillet": None})
# forma del piano
gs = SpecialShape("gear", 36, 36, 16)
check("E un ingranaggio nuovo ha i denti veri (opzioni) e modulo 2 con 36 mm e 16 denti", gs.opts == {}
      and near(gs.gear_module(), 2.0, 1e-9) and same_rect(gs.bounds(), QRectF(0, 0, 36, 36), 0.02))
old = shape_from_dict({"kind": "special", "id": "x", "layer": 1, "tf": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                       "p": {"form": "gear", "w": 30, "h": 30, "param": 16}})
ref = shapes_lib.make("gear", 30, 30, 16)
check("E ingranaggio salvato fino alla 0.20.5: disegno identico (denti a trapezio)", old.opts is None
      and old.local_path() == ref)
gs.opts = {"hole": 6, "spokes": 0}
gs.invalidate()
d2 = shape_from_dict(json.loads(json.dumps(gs.to_dict())))
check("E salva e riapri: stesse opzioni e stesso disegno", d2.opts == gs.opts and d2.local_path() == gs.local_path())
gs.apply(QTransform.fromScale(2, 2))
hole_r = max(math.hypot(x - 36, y - 36) for x, y in
             [(gs.tf.map(QPointF(px, py)).x(), gs.tf.map(QPointF(px, py)).y())
              for px, py in [(e.x, e.y) for e in (gs.local_path().elementAt(i) for i in range(gs.local_path().elementCount()))]]
             if math.hypot(x - 36, y - 36) < 5)
check("E ingrandito con le maniglie: modulo doppio, il foro resta di 6 mm", near(gs.gear_module(), 4.0, 1e-9)
      and near(hole_r, 3.0, 0.02), (gs.gear_module(), round(hole_r, 3)))
# pannello Proprietà
doc = Document()
gp = SpecialShape("gear", 36, 36, 16, layer=1)
gp.set_transform(QTransform.fromTranslate(20, 20))
doc.add(gp)
ed.set_document(doc)
ed.select([gp])
spin(0.1)
w.props.rebuild()
spin(0.05)
spins = {s_.toolTip().split(":")[0][:30]: s_ for s_ in w.props.widget().findChildren(QDoubleSpinBox)}
mod = [s_ for s_ in w.props.widget().findChildren(QDoubleSpinBox) if s_.suffix() == " mm" and near(s_.value(), 2.0, 1e-6)
       and "modulo" in s_.toolTip()]
check("E Proprietà: campo Modulo con il valore vero", len(mod) == 1)
if mod:
    c0 = gp.bounds().center()
    mod[0].setValue(3.0)
    spin(0.05)
    gp_ = ed.doc.shapes[0]
    check("E Modulo 3: diametro esterno 54 mm, la ruota resta centrata dov'era", near(gp_.bounds().width(), 54.0, 0.02)
          and near(gp_.bounds().center().x(), c0.x(), 0.02) and near(gp_.bounds().center().y(), c0.y(), 0.02)
          and near(gp_.gear_module(), 3.0, 1e-6))
w.props.rebuild()
spin(0.05)
combos = w.props.widget().findChildren(QComboBox)
pa_c = [c_ for c_ in combos if c_.findData(14.5) >= 0]
sp_c = [c_ for c_ in combos if c_.findData(8) >= 0 and c_.findData(3) >= 0]
check("E Proprietà: angolo di pressione (14,5 / 20 / 25) e alleggerimenti", len(pa_c) == 1 and len(sp_c) == 1)
if pa_c and sp_c:
    pa_c[0].setCurrentIndex(pa_c[0].findData(25.0))
    spin(0.05)
    check("E cambiato l'angolo di pressione: salvato nelle opzioni, si annulla", ed.doc.shapes[0].opts.get("pa") == 25.0)
    ed.undo()
    check("E …Annulla", ed.doc.shapes[0].opts.get("pa", 20.0) == 20.0)
old_doc = Document()
old_doc.add(old)
ed.set_document(old_doc)
ed.select([old])
spin(0.05)
w.props.rebuild()
btn = [b for b in w.props.widget().findChildren(QPushButton) if "evolvente" in b.text()]
check("E ingranaggio vecchio: resta com'è e c'è il pulsante per i denti veri", len(btn) == 1)
if btn:
    btn[0].click()
    spin(0.05)
    check("E …premuto: denti veri, si annulla", ed.doc.shapes[0].opts == {})
    ed.undo()
    check("E …Annulla: di nuovo il disegno vecchio", ed.doc.shapes[0].opts is None)
check("E denti fino a 200 nello strumento e nelle Proprietà", shapes_lib.SHAPES["gear"][3] == 200)

# ====================================================================== F. traduzioni
print("--- F. traduzioni")
NEW = ["Contorno da tagliare…", "Contorno da tagliare", "Modulo", "Diametri", "Angolo di pressione", "Gioco",
       "Raccordo al piede", "Foro", "Foro a D", "Cava larghezza", "Cava profondità", "Alleggerimenti", "automatico",
       "Usa i denti veri (evolvente)", "nessuno (ruota piena)", "{0} finestre", "automatico ({0:g} mm)",
       "esterno {0:.2f} · primitivo {1:.2f} · piede {2:.2f} mm\npasso {3:.2f} mm",
       "facoltativo: nome o pseudonimo per l'elenco dei ringraziamenti",
       "Contorno da tagliare: seleziona una foto ritagliata con una forma",
       "Contorno da tagliare: con questo scostamento non resta nessun contorno",
       "Contorno da tagliare sul livello {0}: controlla che sia un taglio (modalità Linea, potenza e passate)",
       "Originale · trascina per ritagliare, poi sposta il riquadro o tira i bordi · rotella per lo zoom, tasto destro "
       "per spostarti"]
src_all = ""
for root_, _d, files in os.walk(os.path.join(ROOT, "freelasercut")):
    for fn in files:
        if fn.endswith(".py"):
            src_all += open(os.path.join(root_, fn), encoding="utf-8").read()
tr_calls = set()
for mt in re.finditer(r'tr\(((?:\s*"(?:[^"\\]|\\.)*"\s*)+)', src_all):
    tr_calls.add("".join(json.loads('"' + x + '"') for x in re.findall(r'"((?:[^"\\]|\\.)*)"', mt.group(1))))
missing_src = [s_ for s_ in NEW if s_ not in tr_calls]
check("F i testi nuovi sono davvero nel codice", not missing_src, missing_src)
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    new_all = [s_ for s_ in tr_calls if "0.20.6" not in s_]
    miss = [s_ for s_ in NEW if not cat.get(s_) or cat[s_] == s_]
    ph = [s_ for s_ in NEW if s_ in cat and sorted(re.findall(r"\{\d[^}]*\}", s_)) != sorted(re.findall(r"\{\d[^}]*\}", cat[s_]))]
    check(f"F {lang}: tradotti, con gli stessi segnaposto", not miss and not ph, str(miss + ph)[:300])
    _ = new_all

check("nessun errore nascosto durante le prove", not hidden, repr(hidden[:2]))
ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
