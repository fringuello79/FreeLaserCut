# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.20.3, da Evoluzione2: ritaglio della foto a forma.
- Prepara foto → Forma: anche cerchio, cuore, stella, nuvola ed esagono (le stesse forme che si disegnano sul piano);
- «Ritaglia la foto con la forma»: la foto si vede e si incide solo dentro una forma chiusa del disegno; la forma resta
  come contorno sul livello strumenti, in un gruppo con la foto; «Togli il ritaglio» rimette tutto com'era;
- correzione: una foto ruotata in negativo (o con luminosità o contrasto) incideva gli angoli del riquadro che la
  contiene, fuori dalla foto."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import base64
import io
import json
import math
import re
import time

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core import gcode, geom, ops, photo, photo_clip, shapes_lib
from freelasercut.core.document import (Document, GroupShape, ImageShape, PathShape, PolygonShape, RectShape,
                                        SpecialShape, TextShape, shape_from_dict)
from freelasercut.profile import MachineProfile

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def spin(sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def burn_points(job, step=0.05):
    """Punti dove il laser è acceso (tratti G1 con S > 0), sul piano."""
    x = y = s = 0.0
    on, mode, pts = False, "0", []
    ox, oy = job.out_to_bed
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


def outside_dist(pts, shape):
    """Distanza massima (mm) dei punti fuori dal contorno chiuso della forma (0 = tutti dentro)."""
    worst = 0.0
    polys = [np.array(p.pts, np.float32) for leaf, tf in shape.leaves() for p in geom.flatten(tf.map(leaf.local_path()), 0.01)
             if p.closed]
    for x, y in pts[:: max(1, len(pts) // 20000)]:
        d = max(cv2.pointPolygonTest(c, (float(x), float(y)), True) for c in polys)
        worst = max(worst, -d)
    return worst


class _W:
    """Una forma con la sua trasformazione completa (anche dentro un gruppo), per outside_dist."""

    def __init__(self, s, tf):
        self.s, self.tf = s, tf

    def leaves(self):
        yield self.s, self.tf


def area(shape):
    return sum(abs(cv2.contourArea(np.array(p.pts, np.float32)))
               for leaf, tf in shape.leaves() for p in geom.flatten(tf.map(leaf.local_path()), 0.01) if p.closed)


def job_of(doc, dpi=127.0, negative=False, dither="threshold"):
    for i, cs in doc.layers.items():
        if cs.mode == "image":
            cs.dpi, cs.negative, cs.dither = dpi, negative, dither
    return gcode.generate(doc, MachineProfile(), gcode.JobOptions(start_from="absolute"))


# ================================================================ A. forme nuove in Prepara foto
gray = np.full((300, 300), 60, np.uint8)
ok_all = True
for m in photo.FORM_MASKS:
    for (h, w) in ((300, 300), (200, 400), (400, 200)):
        mk = photo.shape_mask(h, w, m, 0)
        ys, xs = np.nonzero(mk > 0.5)
        bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        nat = shapes_lib.natural_aspect(m) if m in ("heart", "cloud") else None
        fits = xs.min() >= 0 and ys.min() >= 0 and (bw >= w - 3 or bh >= h - 3)  # tocca due lati: la più grande che ci sta
        centered = abs((xs.min() + xs.max()) / 2 - (w - 1) / 2) < 3 and abs((ys.min() + ys.max()) / 2 - (h - 1) / 2) < 3
        prop = nat is None or abs(bw / bh - nat) < 0.06
        ok_all = ok_all and fits and centered and prop and 0.15 < mk.mean() < 0.85
        if not (fits and centered and prop):
            print("   ", m, (h, w), (bw, bh), nat)
check("cerchio, cuore, stella, nuvola, esagono: la più grande che sta nella foto, al centro, con le sue proporzioni "
      "(foto quadrata, larga e alta)", ok_all)
mk = photo.shape_mask(300, 300, "heart", 0)
check("cuore dritto (punta in basso, due gobbe in alto)", mk[290, 150] > 0.5 and mk[20, 150] < 0.5 and mk[60, 80] > 0.5)
mk = photo.shape_mask(300, 300, "star", 0)
check("stella con la punta in alto, come lo strumento Stella (5 punte, rientranza 0,5)", mk[15, 150] > 0.5 and mk[150, 150] > 0.5
      and mk[290, 150] < 0.5)
star = PolygonShape(100, 100, 5, 0.5)
sp = geom.flatten(star.local_path(), 0.01)[0].pts
fp = geom.flatten(photo.form_path("star", 100.0, 100.0), 0.01)[0].pts
fx = [p[0] for p in fp]
sx = [p[0] for p in sp]
check("…stessa sagoma della stella disegnata (stesse proporzioni)",
      abs((max(fx) - min(fx)) / (max(p[1] for p in fp) - min(p[1] for p in fp))
          - (max(sx) - min(sx)) / (max(p[1] for p in sp) - min(p[1] for p in sp))) < 1e-6)
src = Image.fromarray(np.full((240, 360), 40, np.uint8))
ok_fade = True
for m in photo.FORM_MASKS:
    for fade in (0.0, 100.0):
        out = np.asarray(photo.process(src, photo.PhotoSettings(mask=m, edge_fade=fade)))
        mk = photo.shape_mask(240, 360, m, 0)
        ok_fade = ok_fade and out[mk < 0.01].min() >= 250 and out[120, 180] < (120 if fade == 0 else 250)
        if fade == 100.0:
            ok_fade = ok_fade and out[mk > 0.99].max() > out[120, 180] + 40  # sfuma verso il bordo
        else:
            ok_fade = ok_fade and out[mk > 0.99].max() < 60  # senza sfumatura dentro c'è la foto com'è
check("bordi sfumati 0 e 100 con le forme nuove: fuori bianco, dentro la foto, sfumata verso il bordo", ok_fade)
for rot, flip in ((90, False), (0, True), (270, True)):
    out = np.asarray(photo.process(src, photo.PhotoSettings(mask="heart", rotate=rot, flip=flip)))
    mk = photo.shape_mask(out.shape[0], out.shape[1], "heart", 0)
    ok_rot = out.shape == ((360, 240) if rot % 180 else (240, 360)) and out[mk < 0.01].min() >= 250 and out[mk > 0.99].max() < 60
    check(f"cuore con la foto girata di {rot}° {'e specchiata ' if flip else ''}: il cuore resta dritto sul risultato", ok_rot)
check("impostazioni salvate: le forme nuove si rileggono, una sconosciuta torna Rettangolo",
      photo.PhotoSettings.from_dict({"mask": "cloud"}).mask == "cloud" and photo.PhotoSettings.from_dict({"mask": "boh"}).mask == "none")

# ================================================================ B. ritaglio con una forma del disegno (dati e G-code)
def make_doc(photo_tf=None, heart_tf=None):
    doc = Document()
    doc.images["p"] = Image.fromarray(np.full((150, 200), 0, np.uint8))  # foto tutta nera: dentro si incide tutto
    im = ImageShape("p", 40, 30, layer=2)
    im.set_transform(photo_tf or QTransform.fromTranslate(50, 50))
    doc.add(im)
    doc.layer(2).mode = "image"
    hs = SpecialShape("heart", 20, 20, layer=1)
    c = im.path().boundingRect().center()
    hs.set_transform(heart_tf or QTransform.fromTranslate(c.x() - 10, c.y() - 10))
    doc.add(hs)
    return doc, im, hs


from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
ed = w.editor
msgs = []
ed.message.connect(msgs.append)


def setup(photo_tf=None, heart_tf=None):
    doc, im, hs = make_doc(photo_tf, heart_tf)
    ed.set_document(doc)
    ed.select([im, hs])
    spin(0.05)
    return doc, im, hs


doc, im, hs = setup()
job0 = job_of(doc)
P0 = burn_points(job0)
w._update_sel_actions()
check("comando attivo con una foto e una forma selezionate", w.acts["photo_clip"].isEnabled() and not w.acts["photo_unclip"].isEnabled())
heart_area = area(hs)
ok = ed.clip_photo()
g = doc.shapes[0] if doc.shapes else None
check("Ritaglia: un gruppo con la foto (prima) e la forma, la forma sul livello strumenti",
      ok and len(doc.shapes) == 1 and ops.is_clip_group(g) and g.children[0] is im and g.children[1] is hs
      and hs.layer == 30 and hs.role == "clip:1" and im.clip)
job = job_of(doc)
P = burn_points(job)
step = 25.4 / 127.0
TOL = step * 0.5 + 0.01  # un punto inciso è largo un passo: il centro dentro, il bordo al massimo mezzo passo fuori
check("G-code: nessun punto acceso fuori dal cuore", len(P) > 100 and outside_dist(P, hs) <= TOL,
      round(outside_dist(P, hs), 3))


def burnt_len(P):
    """Lunghezza incisa riga per riga (tratti separati contati a parte)."""
    out = 0.0
    for y in np.unique(np.round(P[:, 1], 3)):
        q = np.sort(P[np.round(P[:, 1], 3) == y][:, 0])
        gaps = np.diff(q) > 0.3
        starts, ends = np.r_[q[0], q[1:][gaps]], np.r_[q[:-1][gaps], q[-1]]
        out += float((ends - starts).sum())
    return out


ratio = burnt_len(P) / burnt_len(P0)  # stesse righe del lavoro senza ritaglio (40 × 30 mm)
check("…e dentro si incide il cuore intero (area come quella del cuore)", abs(ratio * 40 * 30 / heart_area - 1) < 0.05,
      (round(ratio * 40 * 30, 1), round(heart_area, 1)))
check("il contorno sul livello strumenti non esce nel G-code", all(L.get("index", 0) != 30 for L in getattr(job, "layers", [])
                                                                    if isinstance(L, dict)) and job.lines and
      not any("C30" in ln for ln in job.lines if ln.startswith(";")))
jn = job_of(doc, negative=True)
Pn = burn_points(jn)
check("in negativo: niente fuori dal cuore (il bianco fuori non si accende)", len(Pn) == 0 or outside_dist(Pn, hs) <= TOL,
      (len(Pn), round(outside_dist(Pn, hs), 3) if len(Pn) else 0))
jg = job_of(doc, dither="grayscale")
check("in scala di grigi e con le mezzetinte: niente fuori dal cuore",
      outside_dist(burn_points(jg), hs) <= TOL and
      outside_dist(burn_points(job_of(doc, dither="halftone")), hs) <= TOL)
# punti uniti per le porte lente (0.17.2): né i tratti uniti né i punti lunghi scavalcano la sagoma
rngc = np.random.default_rng(3)
doc.images["p"] = Image.fromarray(rngc.integers(0, 255, (150, 200)).astype(np.uint8))
gtf = list(im.leaves(g.tf))[0][1]
htf = list(hs.leaves(g.tf))[0][1]
okc = True
for dith in ("grayscale", "threshold", "jarvis", "halftone"):
    csx = doc.layer(2)
    csx.dither, csx.dpi = dith, 127.0
    im._doc_image = doc.images["p"]
    for k in (1, 3, 6):
        lines, _rot, _first = gcode._image_lines(im, gtf, csx, 256, None, compact=k)
        pts = np.array([(x, y) for y, segs in lines for xa, xb, _p in segs for x in (xa, xb)])
        d = outside_dist(pts, _W(hs, htf)) if len(pts) else 9.0
        okc = okc and len(pts) > 20 and d <= TOL
        if d > TOL:
            print("    punti uniti", dith, k, round(d, 3))
check("punti uniti per le porte lente (×3, ×6), tutti i metodi: niente fuori dal cuore", okc)
doc.images["p"] = Image.fromarray(np.full((150, 200), 0, np.uint8))
# forma con un buco (anello): dentro il buco la foto non si incide
doc, im, hs = setup()
doc.remove([hs])
ring = SpecialShape("ring", 20, 20, param=0.25, layer=1)
ring.set_transform(QTransform.fromTranslate(60, 55))
doc.add(ring)
ed.select([im, ring])
ed.clip_photo()
P = burn_points(job_of(doc))
rr = np.hypot(P[:, 0] - 70, P[:, 1] - 65)
check("forma con un buco (anello): si incide solo la corona, il buco resta vuoto",
      len(P) > 100 and rr.min() >= 5.0 - TOL and rr.max() <= 10.0 + TOL, (round(float(rr.min()), 2), round(float(rr.max()), 2)))
doc, im, hs = setup()
ed.clip_photo()
g = doc.shapes[0]
im_rot = QTransform.fromTranslate(-20, -15) * QTransform().rotate(30) * QTransform.fromScale(1.5, 1.2) * QTransform.fromTranslate(80, 90)
for name, ptf in (("foto ruotata e scalata", im_rot),
                  ("foto specchiata", QTransform(-1, 0, 0, 1, 0, 0) * QTransform.fromTranslate(120, 60))):
    doc, im, hs = setup(ptf)
    ed.clip_photo()
    P = burn_points(job_of(doc))
    check(f"{name}: nessun punto fuori dal cuore", len(P) > 100 and outside_dist(P, hs) <= TOL,
          round(outside_dist(P, hs), 3))
doc, im, hs = setup(heart_tf=QTransform.fromTranslate(-10, -10) * QTransform().rotate(25) * QTransform.fromScale(1.3, 0.9)
                    * QTransform.fromTranslate(70, 65))
ed.clip_photo()
P = burn_points(job_of(doc))
check("cuore ruotato e scalato prima del ritaglio: nessun punto fuori", len(P) > 100 and outside_dist(P, hs) <= TOL,
      round(outside_dist(P, hs), 3))
g = doc.shapes[0]
ed.select([g])
ed.transform(QTransform.fromTranslate(-35, -25) * QTransform().rotate(-40) * QTransform.fromScale(0.8, 0.8)
             * QTransform.fromTranslate(150, 120))
hs_now = g.children[1]
P = burn_points(job_of(doc))
check("gruppo spostato, ruotato e scalato dopo il ritaglio: la foto resta dentro il cuore (che si è mosso con lei)",
      len(P) > 100 and outside_dist(P, _W(hs_now, list(hs_now.leaves(g.tf))[0][1])) <= TOL,
      round(outside_dist(P, _W(hs_now, list(hs_now.leaves(g.tf))[0][1])), 3))
ed.undo()
check("Annulla lo spostamento e poi il ritaglio: la foto torna intera", (ed.undo() or True) and doc.shapes[0].kind == "image"
      and doc.shapes[0].clip is None and doc.shapes[1].layer == 1 and not doc.shapes[1].role)
ed.redo()
check("Ripeti: di nuovo ritagliata", ops.is_clip_group(doc.shapes[0]) and doc.shapes[0].children[0].clip)

# ---- salva, riapri, copia, file vecchi
doc, im, hs = setup()
d_old = im.to_dict()
check("foto senza ritaglio: nel file niente di nuovo (i progetti di prima restano identici)", "clip" not in d_old["p"])
ed.clip_photo()
path = os.path.join(tempfile.mkdtemp(), "ritaglio.flc")
doc.save(path)
d2 = Document.load(path)
g2 = d2.shapes[0]
im2 = g2.children[0]
check("salva e riapri: gruppo, sagoma e livello della forma restano", ops.is_clip_group(g2) and im2.clip == im.clip
      and g2.children[1].layer == 30 and g2.children[1].role == "clip:1")
P1, P2 = burn_points(job_of(doc)), burn_points(job_of(d2))
check("…e il G-code è identico", len(P1) == len(P2) and np.allclose(P1, P2))
ed.select([doc.shapes[0]])
ed.duplicate()
dup = doc.shapes[-1]
check("Duplica: anche la copia è ritagliata", ops.is_clip_group(dup) and dup.children[0].clip == im.clip
      and dup.children[0] is not im)
bad = shape_from_dict({"kind": "image", "p": {"image_id": "p", "w": 10, "h": 10, "clip": [["x"], [[[1, 2], [3]]], "zz"]}})
bad2 = shape_from_dict({"kind": "image", "p": {"image_id": "p", "w": 10, "h": 10, "clip": [[[[0, 0], [5, 0], [5, 5]]]]}})
bad3 = shape_from_dict({"kind": "image", "p": {"image_id": "p", "w": 10, "h": 10, "clip": [[[[0, 0], [5, 5]]]]}})
check("file rovinato: una sagoma senza senso (o con meno di tre punti) si ignora, una buona si legge",
      bad.clip is None and bad3.clip is None and bad2.clip == [[[[0, 0], [5, 0], [5, 5]]]])

# ---- Togli il ritaglio, forma cancellata, ritaglia di nuovo
doc, im, hs = setup()
ed.clip_photo()
g = doc.shapes[0]
ed.select([g])
w._update_sel_actions()
check("sul gruppo ritagliato: «Togli il ritaglio» attivo (e anche «Ritaglia» per rifarlo)", w.acts["photo_unclip"].isEnabled()
      and w.acts["photo_clip"].isEnabled())
hs.w = 30.0  # la forma cambia (per esempio con i campi L/A del pannello)
hs.invalidate()
g.invalidate()
before = photo_clip.coverage(im.clip, im.w, im.h)
ed.clip_photo()
check("forma modificata e «Ritaglia» sul gruppo: la sagoma si rifà com'è ora (senza un gruppo in più)",
      photo_clip.coverage(im.clip, im.w, im.h) > before * 1.2 and len(doc.shapes) == 1 and ops.is_clip_group(doc.shapes[0])
      and doc.shapes[0].children == [im, hs], (round(before, 3), round(photo_clip.coverage(im.clip, im.w, im.h), 3)))
ed.unclip_photo()
check("Togli il ritaglio: foto intera, gruppo separato, la forma torna sul suo livello",
      im.clip is None and len(doc.shapes) == 2 and doc.shapes[0] is im and doc.shapes[1] is hs and hs.layer == 1 and not hs.role)
P = burn_points(job_of(doc))
xs = P[:, 0]
check("…e si incide di nuovo tutta la foto", abs(xs.max() - xs.min() - 40) < 0.5, round(xs.max() - xs.min(), 2))
ed.select([im, hs])
ed.clip_photo()
ed.select([doc.shapes[0]])
ed.ungroup()
ed.select([hs])
ed.delete()
P = burn_points(job_of(doc))
h_ref = make_doc()[2]  # il cuore com'era al momento del ritaglio (largo 30)
h_ref.w = 30.0
check("gruppo separato e forma cancellata: la foto resta ritagliata (si toglie con «Togli il ritaglio»)",
      len(doc.shapes) == 1 and im.clip and outside_dist(P, h_ref) <= TOL, round(outside_dist(P, h_ref), 3))
ed.select([im])
w._update_sel_actions()
check("…sulla foto da sola «Togli il ritaglio» è attivo", w.acts["photo_unclip"].isEnabled() and ed.unclip_photo() and im.clip is None)

# ---- selezioni che non vanno
for name, sel_fn, expect in (
        ("solo la foto", lambda d, i, h: [i], "seleziona una foto sola"),
        ("solo la forma", lambda d, i, h: [h], "seleziona una foto sola"),
        ("una linea aperta", lambda d, i, h: [i, d.add(PathShape(_line(), 1))], "chiusa"),
        ("forma lontana dalla foto", lambda d, i, h: [i, _far(d, h)], "non copre la foto"),
        ("due foto", lambda d, i, h: [i, h, _photo2(d)], "seleziona una foto sola")):
    from PySide6.QtGui import QPainterPath  # noqa: E402

    def _line():
        p = QPainterPath()
        p.moveTo(55, 55)
        p.lineTo(80, 70)
        return p

    def _far(d, h):
        h.set_transform(QTransform.fromTranslate(300, 300))
        return h

    def _photo2(d):
        i2 = ImageShape("p", 10, 10, layer=2)
        return d.add(i2)
    doc, im, hs = setup()
    sel = sel_fn(doc, im, hs)
    ed.select(sel)
    n0 = json.dumps(doc.snapshot()["shapes"])
    msgs.clear()
    ok = ed.clip_photo()
    check(f"{name}: non ritaglia e lo dice", not ok and msgs and expect in msgs[-1].lower()
          and json.dumps(doc.snapshot()["shapes"]) == n0, msgs[-1] if msgs else "")
doc, im, hs = setup()
txt = TextShape("AB", "Arial", 18, layer=1)
txt.set_transform(QTransform.fromTranslate(55, 55))
doc.add(txt)
doc.remove([hs])
ed.select([im, txt])
ok = ed.clip_photo()
P = burn_points(job_of(doc))
check("con un testo (lettere con i buchi): la foto solo dentro le lettere", ok and len(P) > 50 and outside_dist(P, txt) <= TOL)

# ================================================================ C. anteprima, esportazione, Prepara foto, menu
doc, im, hs = setup()
ed.clip_photo()
cv = w.canvas
qi = cv.image_preview(im, doc.layer(2))
arr = np.frombuffer(qi.constBits(), np.uint8).reshape(qi.height(), qi.width(), 4) if qi.hasAlphaChannel() else None
check("sul piano la foto si vede solo dentro la forma (fuori trasparente)", arr is not None and arr[2, 2, 3] == 0
      and arr[qi.height() // 2, qi.width() // 2, 3] == 255)
# il cuore sta fra 5 e 25 mm dal basso della foto (alta 30): punta in basso, incavo in alto al centro
row = lambda y_mm: int((1 - y_mm / 30.0) * qi.height())  # noqa: E731
check("…con il cuore nel verso giusto (punta in basso, incavo fra le due gobbe in alto)",
      arr is not None and arr[row(7.0), qi.width() // 2, 3] == 255 and arr[row(23.5), qi.width() // 2, 3] == 0
      and arr[row(23.0), int(qi.width() * 0.37), 3] == 255)
cs = doc.layer(2)
cs.dpi, cs.dither = 127.0, "threshold"
cv.dither_preview = True
qi2 = cv.image_preview(im, cs)
check("…anche nell'anteprima dei punti veri", qi2.hasAlphaChannel() and qi2.pixelColor(1, 1).alpha() == 0)
cv.dither_preview = False
svg = os.path.join(tempfile.mkdtemp(), "x.svg")
from freelasercut.core import io_formats  # noqa: E402

io_formats.export_svg(doc.shapes, doc, svg)
b64 = re.search(r"base64,([A-Za-z0-9+/=]+)", open(svg, encoding="utf-8").read()).group(1)
png = Image.open(io.BytesIO(base64.b64decode(b64)))
check("SVG esportato: la foto ha la trasparenza fuori dalla forma", png.mode == "RGBA" and png.getpixel((1, 1))[3] == 0
      and png.getpixel((png.width // 2, png.height // 2))[3] == 255)

from freelasercut.ui.dialogs_photo import PhotoDialog  # noqa: E402

ed.select([doc.shapes[0]])
w._update_sel_actions()
check("Prepara foto attivo sul gruppo ritagliato", w.acts["photo"].isEnabled())
g = doc.shapes[0]
ed.transform(QTransform.fromTranslate(20, 10))
hs_plane = list(hs.leaves(g.tf))[0][1].map(hs.local_path())
orig_exec = PhotoDialog.exec


def ex(self):
    self.show()
    spin(0.1)
    self._set_crop((0.1, 0.0, 0.7, 1.0))  # foto più stretta: cambiano le misure
    self.mask.setCurrentIndex(self.mask.findData("star"))
    self._timer.stop()
    self._refresh()
    seen["masks"] = [self.mask.itemData(i) for i in range(self.mask.count())]
    self._accept()
    return QDialog.Accepted


seen = {}
PhotoDialog.exec = ex
w.photo_dialog()
spin(0.1)
PhotoDialog.exec = orig_exec
check("nella tendina Forma tutte le forme, nell'ordine", seen.get("masks") == list(photo.MASKS), seen.get("masks"))
g = doc.shapes[0]
im = g.children[0]
hs = g.children[1]
moved = list(hs.leaves(g.tf))[0][1].map(hs.local_path())
check("Prepara foto sul gruppo: resta un gruppo ritagliato, la forma non si sposta",
      ops.is_clip_group(g) and im.clip and moved.boundingRect() == hs_plane.boundingRect() and im.photo and im.photo["mask"] == "star")
P = burn_points(job_of(doc))



check("…foto con misure nuove: nessun punto fuori dalla forma", len(P) > 50 and outside_dist(P, _W(hs, list(hs.leaves(g.tf))[0][1])) <= TOL,
      round(outside_dist(P, _W(hs, list(hs.leaves(g.tf))[0][1])), 3))

doc, im, hs = setup()
keys = w.context_menu_keys()
check("tasto destro con foto e forma: «Ritaglia la foto con la forma»", "photo_clip" in keys and "photo_unclip" not in keys)
ed.clip_photo()
ed.select([doc.shapes[0]])
keys = w.context_menu_keys()
check("tasto destro sul gruppo ritagliato: anche «Togli il ritaglio»", "photo_unclip" in keys)
names = []
for m in w.menuBar().findChildren(type(w.menuBar().actions()[0].menu())):
    names += [a for a in m.actions()]
check("nel menu Disponi", w.acts["photo_clip"] in names and w.acts["photo_unclip"] in names)
if UI == "banco" and getattr(w, "banco", None) is not None:
    title, items = w.banco.radial_items()
    check("Banco: «Foto intera» (toglie il ritaglio) nel menu radiale sul gruppo ritagliato", any(a is w.acts["photo_unclip"] for _l, a in items))
    ed.unclip_photo()
    ed.select([im, hs])
    title, items = w.banco.radial_items()
    check("Banco: «Ritaglia» nel menu radiale con foto e forma", any(a is w.acts["photo_clip"] for _l, a in items))

# ================================================================ D. correzione: foto ruotata in negativo
for neg, con, bri in ((True, 0, 0), (False, -50, 0), (False, 0, 40)):
    d = Document()
    d.images["a"] = Image.new("L", (100, 100), 128)
    s = ImageShape("a", 20, 20, layer=2)
    s.contrast, s.brightness = con, bri
    s.apply(QTransform.fromTranslate(-10, -10) * QTransform().rotate(45) * QTransform.fromTranslate(50, 50))
    d.add(s)
    d.layer(2).mode = "image"
    P = burn_points(job_of(d, dpi=100, negative=neg, dither="grayscale"))
    check(f"foto ruotata di 45° ({'negativo' if neg else 'contrasto -50' if con else 'luminosità +40'}): niente acceso "
          "fuori dalla foto (prima gli angoli del riquadro)", len(P) > 100 and outside_dist(P, s) <= 0.3, round(outside_dist(P, s), 3))

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(code)
