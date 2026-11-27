# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.5: ritaglio della foto con una forma, due casi che non andavano (27/11/2026).

1. Rapporto FLC-20261127-1355-3536 (Daniel Z., 0.23.4): «Non ritaglia la foto… rimane tutto». La foto era già
   ritagliata (angoli tondi messi da Prepara foto con una forma); selezionando il gruppo e un cerchio nuovo,
   «Ritaglia la foto con la forma» sommava la sagoma di prima e il cerchio: la foto restava com'era e nasceva un
   gruppo dentro un gruppo. Ora vale solo la forma nuova: il ritaglio di prima si scioglie (la sagoma di Prepara foto
   sparisce, una sagoma disegnata dalla persona torna sul suo livello).
2. Ale: con una foto e una forma selezionate, «Ritaglia con la forma» (il comando dei disegni) non faceva niente.
   Ora, con una foto e una forma sola, fa il ritaglio della foto.

Prove: (A) il caso del rapporto, con Annulla, Ripeti e «Togli il ritaglio»; (B) sagoma disegnata dalla persona;
(C) ritagliare di nuovo il gruppo da solo (come prima); (D) «Ritaglia con la forma» con una foto, e con i disegni come
prima; (E) difetti rimessi apposta.
Uso: python tests/test_v235_ritaglio_foto.py [classica|banco]
"""
import math
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
for _k in ("FLC_NO_DIALOGS", "FLC_NO_FIRST_RUN", "FLC_NO_UPDATE"):
    os.environ[_k] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtGui import QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
for _n in ("question", "information", "warning"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: QMessageBox.Yes))

from freelasercut.core import ops, photo_clip  # noqa: E402
from freelasercut.core.document import EllipseShape, GroupShape, ImageShape, PathShape, RectShape  # noqa: E402
from freelasercut.ui.editor import TOOL_LAYER  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402


def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.005)


def at(shape, x, y):
    shape.apply(QTransform.fromTranslate(x, y))
    return shape


w = MainWindow()
w._confirm_discard = lambda: True
w.resize(1400, 900)
w.show()
spin(0.4)
ed = w.editor
msgs = []
ed.message.connect(msgs.append)
IW, IH = 70.0, 88.0
CIRC = math.pi * 15 * 15 / (IW * IH)  # parte della foto dentro un cerchio di 30 mm tutto sopra la foto


def nuova_foto():
    """Progetto nuovo con una foto 70 × 88 mm in (5, 5)."""
    ed.dirty = False
    w.file_new()
    spin(0.1)
    g = np.tile(np.linspace(30, 220, 280, dtype=np.uint8), (352, 1))
    ed.doc.images["foto"] = Image.fromarray(g)
    img = at(ImageShape("foto", IW, IH), 5, 5)
    ed.run("foto", lambda: ed.doc.add(img))
    return img


def foto_di(shape):
    return [leaf for leaf, _ in shape.leaves() if isinstance(leaf, ImageShape)][0]


def copertura(img):
    return photo_clip.coverage(img.clip, img.w, img.h) if img.clip else 1.0


def prepara_foto_con_forma(img):
    """Come Prepara foto con una forma: sagoma ad angoli tondi messa dal programma (ruolo «clip:1:form»)."""
    pp = QPainterPath()
    pp.addRoundedRect(5, 5, IW, IH, 12, 12)
    ps = PathShape(pp, layer=1)
    ps.role = ops.CLIP_OUTLINE + "1" + ops.FORM_OUTLINE

    def do():
        ed.doc.add(ps)
        ed.clip_into_group([img, ps], img, [(ps, ps.tf)], photo_clip.pieces_from([(ps, ps.tf)], img.tf))
    ed.run("Prepara foto", do)
    return ed.doc.shapes[0]


def cerchio():
    c = at(EllipseShape(30, 30, layer=1), 25, 50)
    ed.run("cerchio", lambda: ed.doc.add(c))
    return c


def figli(g):
    return [type(c).__name__ for c in g.children]


# ====================================================================== A. il caso del rapporto 3536
print("--- A. foto già ritagliata da Prepara foto + un cerchio nuovo")
img = nuova_foto()
g0 = prepara_foto_con_forma(img)
c0 = copertura(img)
check("A partenza: gruppo «foto ritagliata» con la sagoma ad angoli tondi (quasi tutta la foto)",
      ops.is_clip_group(g0) and 0.95 < c0 < 1.0 and len(g0.children) == 2, (c0, figli(g0)))
c = cerchio()
ed.select([g0, c])
spin()
check("A il comando è acceso con il gruppo e il cerchio selezionati", w.acts["photo_clip"].isEnabled())
w.acts["photo_clip"].trigger()
spin(0.1)
top = ed.doc.shapes
g1 = top[0] if top else None
img1 = foto_di(g1) if g1 is not None else None
c1 = copertura(img1) if img1 is not None else -1
check("A resta solo la parte dentro il cerchio (prima: «rimane tutto»)", abs(c1 - CIRC) < 0.01, (round(c1, 3), round(CIRC, 3)))
check("A un solo gruppo «foto ritagliata» sul piano, con la foto e il cerchio (prima: un gruppo dentro un gruppo)",
      len(top) == 1 and ops.is_clip_group(g1) and sorted(figli(g1)) == ["EllipseShape", "ImageShape"], figli(g1) if g1 else top)
check("A la sagoma di Prepara foto non c'è più (l'ha sostituita il cerchio)",
      not any(ops.is_form_outline(leaf) for s in top for leaf, _ in s.leaves()))
check("A il cerchio è la sagoma: livello strumenti (mai inciso), ricorda il livello di prima",
      c.layer == TOOL_LAYER and ops.outline_layer(c) == 1, (c.layer, c.role))
m = photo_clip.pixel_mask(img1.clip, img1.w, img1.h, 280, 352)
check("A dentro il cerchio la foto c'è, negli angoli no", bool(m[352 - int((60 - 5) / IH * 352), int((40 - 5) / IW * 280)])
      and not m[3, 3] and not m[348, 276] and not m[176, 5])
qi = w.canvas.image_preview(img1, ed.doc.layer(img1.layer))
alpha = np.frombuffer(qi.convertToFormat(qi.Format.Format_RGBA8888).constBits(), np.uint8).reshape(
    qi.height(), qi.bytesPerLine())[:, :qi.width() * 4].reshape(qi.height(), qi.width(), 4)[..., 3]
check("A sul piano la foto si vede solo dentro il cerchio (trasparente fuori)", abs((alpha > 0).mean() - CIRC) < 0.02,
      round(float((alpha > 0).mean()), 3))
check("A la selezione è il gruppo nuovo", ed.selection == [g1])
ed.undo()
spin()
img_u = foto_di(ed.doc.shapes[0])
check("A Annulla: torna la foto con gli angoli tondi e il cerchio a parte", len(ed.doc.shapes) == 2
      and abs(copertura(img_u) - c0) < 1e-6 and any(ops.is_form_outline(leaf) for leaf, _ in ed.doc.shapes[0].leaves()),
      (len(ed.doc.shapes), copertura(img_u)))
ed.redo()
spin()
g1 = ed.doc.shapes[0]
img1 = foto_di(g1)
check("A Ripeti: di nuovo solo il cerchio", len(ed.doc.shapes) == 1 and abs(copertura(img1) - CIRC) < 0.01)
ed.select([g1])
w.acts["photo_unclip"].trigger()
spin()
el = [s for s in ed.doc.shapes if isinstance(s, EllipseShape)]
check("A «Togli il ritaglio»: foto intera e cerchio di nuovo sul suo livello", foto_di(ed.doc.shapes[0]).clip is None
      and len(el) == 1 and el[0].layer == 1 and not el[0].role, [(type(s).__name__, s.layer) for s in ed.doc.shapes])

# ====================================================================== B. sagoma disegnata dalla persona
print("--- B. foto ritagliata con una forma disegnata + un cerchio nuovo")
img = nuova_foto()
r = at(RectShape(50, 60, layer=2), 15, 15)
ed.run("rettangolo", lambda: ed.doc.add(r))
ed.select([img, r])
w.acts["photo_clip"].trigger()
spin()
gb = ed.doc.shapes[0]
cb = copertura(foto_di(gb))
check("B primo ritaglio con il rettangolo (come sempre)", ops.is_clip_group(gb) and abs(cb - 50 * 60 / (IW * IH)) < 0.01, cb)
c = cerchio()
ed.select([gb, c])
w.acts["photo_clip"].trigger()
spin()
gruppi = [s for s in ed.doc.shapes if ops.is_clip_group(s)]
rett = [s for s in ed.doc.shapes if isinstance(s, RectShape)]
check("B vale il cerchio nuovo", len(gruppi) == 1 and abs(copertura(foto_di(gruppi[0])) - CIRC) < 0.01,
      [copertura(foto_di(x)) for x in gruppi])
check("B il rettangolo di prima non si perde: torna sul piano, sul suo livello, fuori dal gruppo",
      len(rett) == 1 and rett[0].layer == 2 and not rett[0].role and sorted(figli(gruppi[0])) == ["EllipseShape", "ImageShape"],
      [(type(s).__name__, s.layer, s.role) for s in ed.doc.shapes])
check("B …e sta dov'era (15, 15, 50 × 60)", rett and abs(rett[0].bounds().left() - 15) < 1e-6
      and abs(rett[0].bounds().width() - 50) < 1e-6)

# ====================================================================== C. ritagliare di nuovo il gruppo da solo
print("--- C. il gruppo da solo, dopo aver cambiato la sagoma (come prima)")
g = gruppi[0]
sag = [k for k in g.children if isinstance(k, EllipseShape)][0]
ed.run("stringi", lambda: sag.apply(QTransform.fromTranslate(-40, -65) * QTransform.fromScale(0.5, 0.5)
                                    * QTransform.fromTranslate(40, 65)))
ed.select([g])
w.acts["photo_clip"].trigger()
spin()
check("C ritaglia di nuovo con la sagoma com'è ora (cerchio di 15 mm): un quarto di prima",
      ed.doc.shapes.count(g) == 1 and abs(copertura(foto_di(g)) - CIRC / 4) < 0.005, copertura(foto_di(g)))
check("C il gruppo resta quello, con la foto e la sagoma", sorted(figli(g)) == ["EllipseShape", "ImageShape"])

# ====================================================================== D. «Ritaglia con la forma»
print("--- D. «Ritaglia con la forma» (il comando dei disegni)")
img = nuova_foto()
c = cerchio()
ed.select([img, c])
spin()
del msgs[:]
check("D con una foto e una forma il comando è acceso", w.acts["crop_shape"].isEnabled())
w.acts["crop_shape"].trigger()
spin()
gd = ed.doc.shapes[0] if ed.doc.shapes else None
check("D una foto e un cerchio: ritaglia la foto (prima non succedeva niente)", len(ed.doc.shapes) == 1
      and ops.is_clip_group(gd) and abs(copertura(foto_di(gd)) - CIRC) < 0.01, (len(ed.doc.shapes), msgs))
check("D …e si annulla con un solo Annulla, con il nome giusto", ed.undo_label() == "Ritaglia la foto con la forma",
      ed.undo_label())
img = nuova_foto()
g0 = prepara_foto_con_forma(img)
c = cerchio()
ed.select([g0, c])
w.acts["crop_shape"].trigger()
spin()
check("D foto già ritagliata e un cerchio: come al punto A", len(ed.doc.shapes) == 1
      and abs(copertura(foto_di(ed.doc.shapes[0])) - CIRC) < 0.01)
# i disegni: come prima
ed.dirty = False
w.file_new()
spin(0.1)
a = at(RectShape(40, 40, layer=0), 0, 0)
b = at(RectShape(40, 40, layer=1), 60, 0)
cut = at(RectShape(60, 20, layer=2), 20, 10)
ed.run("disegni", lambda: [ed.doc.add(x) for x in (a, b, cut)])
ed.select([a, b, cut])
w.acts["crop_shape"].trigger()
spin()
bb = [s.bounds() for s in ed.doc.shapes]
# sui livelli Linea restano solo i tratti dentro la forma: conta che tutto stia dentro (20..80 × 10..30)
check("D due disegni e la forma sopra: i disegni ritagliati, la forma sparisce (come prima)", len(ed.doc.shapes) == 2
      and cut not in ed.doc.shapes and all(abs(x.height() - 20) < 1e-3 and x.left() > 20 - 1e-3 and x.right() < 80 + 1e-3
                                           and x.top() > 10 - 1e-3 and x.bottom() < 30 + 1e-3 for x in bb),
      [(round(x.left(), 2), round(x.right(), 2), round(x.height(), 2)) for x in bb])
img = nuova_foto()
a = at(RectShape(40, 40, layer=0), 0, 0)
cut = at(RectShape(30, 30, layer=2), 20, 20)
ed.run("misto", lambda: [ed.doc.add(x) for x in (a, cut)])
ed.select([img, a, cut])
w.acts["crop_shape"].trigger()
spin()
fot = [s for s in ed.doc.shapes if isinstance(s, ImageShape)]
check("D una foto, un disegno e la forma: il disegno ritagliato, la foto non si tocca (come prima)",
      len(fot) == 1 and fot[0].clip is None and len(ed.doc.shapes) == 2, [type(s).__name__ for s in ed.doc.shapes])
img = nuova_foto()
ed.select([img])
del msgs[:]
w.editor.crop_with_shape()
check("D una foto da sola: non fa niente e lo dice", len(ed.doc.shapes) == 1 and img.clip is None and msgs, msgs)

# ====================================================================== E. difetti rimessi apposta
print("--- E. difetti rimessi apposta")
vero = ops.is_clip_group
img = nuova_foto()
g0 = prepara_foto_con_forma(img)
c = cerchio()
ed.select([g0, c])
ops.is_clip_group = lambda s: False  # come nella 0.23.4: la sagoma di prima conta insieme alla nuova
try:
    ed.clip_photo()
finally:
    ops.is_clip_group = vero
spin()
cop = copertura(foto_di(ed.doc.shapes[0]))
check("E come nella 0.23.4 (sagoma vecchia sommata alla nuova): «rimane tutto», la prova A lo vede",
      abs(cop - CIRC) > 0.5 and isinstance(ed.doc.shapes[0].children[0], GroupShape), cop)
from freelasercut.ui.editor import Editor  # noqa: E402

vero_clip = Editor.clip_photo
img = nuova_foto()
c = cerchio()
ed.select([img, c])
Editor.clip_photo = lambda self: False
try:
    ed.crop_with_shape()
finally:
    Editor.clip_photo = vero_clip
check("E senza il passaggio al ritaglio della foto: «Ritaglia con la forma» non fa niente, la prova D lo vede",
      len(ed.doc.shapes) == 2 and img.clip is None)
ed.crop_with_shape()
check("E rimesso a posto: ritaglia", len(ed.doc.shapes) == 1 and abs(copertura(foto_di(ed.doc.shapes[0])) - CIRC) < 0.01)

ed.dirty = False
w.close()
spin(0.2)
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
