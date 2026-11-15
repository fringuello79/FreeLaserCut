# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.20.3, da Evoluzione2: nello Schizzo del soggetto la ricerca automatica si può spegnere
(«Trova il soggetto da solo»). Spenta, il soggetto parte vuoto e resta solo quello dipinto con Tieni (anche solo una
parte); Togli cancella; il riquadro limita la zona; «Togli gli aiuti» torna alla partenza della casella scelta.
Accesa: tutto come prima, pixel per pixel."""
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
import json
import time

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QTransform
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core import photo, subject

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


# ---------------------------------------------------------------- scena: auto su ghiaino con il canestro dietro
H, W = 480, 640
rng = np.random.default_rng(4)
scene = np.zeros((H, W, 3), np.uint8)
scene[:] = (190, 200, 210)
scene[300:] = (165, 160, 150)
scene = np.clip(scene + rng.normal(0, 7, scene.shape), 0, 255).astype(np.uint8)
cv2.rectangle(scene, (470, 60), (482, 300), (60, 60, 60), -1)
cv2.rectangle(scene, (440, 40), (520, 100), (230, 230, 230), -1)
car = np.zeros((H, W), np.uint8)
cv2.rectangle(car, (120, 230), (500, 360), 1, -1)
cv2.rectangle(car, (200, 170), (420, 240), 1, -1)
scene[car > 0] = (85, 90, 100)
DIAG = (W * W + H * H) ** 0.5


def band(x0, y0, x1, y1, r):
    b = np.zeros((H, W), np.uint8)
    cv2.line(b, (x0, y0), (x1, y1), 1, max(1, int(round(r * DIAG * 2))))
    return b > 0


def grow(m, k=5):
    return cv2.dilate(m.astype(np.uint8), np.ones((k, k), np.uint8)) > 0


def keep_stroke(x0, y0, x1, y1, r=0.012, order=0, smart=0):
    return [r, [x0 / W, y0 / H, x1 / W, y1 / H], order, smart]


OFF = {"rect": None, "keep": [], "remove": [], "detect": False}


def off(**k):
    h = json.loads(json.dumps(OFF))
    h.update(k)
    return h


# ---------------------------------------------------------------- A. casella accesa = come prima
same = True
for h in (None, {"rect": [0.15, 0.3, 0.85, 0.85], "keep": [], "remove": [], "auto": True},
          {"rect": [0.15, 0.3, 0.85, 0.85], "keep": [], "remove": [], "auto": False},
          {"rect": None, "keep": [keep_stroke(300, 250, 380, 250)], "remove": [keep_stroke(250, 200, 300, 200, 0.01, 1, 1)]}):
    a = subject.subject_mask(scene, h)
    h2 = dict(h or {"rect": None, "keep": [], "remove": []})
    h2["detect"] = True
    subject._CACHE.clear()
    b = subject.subject_mask(scene, h2) if h is not None else subject.subject_mask(scene, None)
    same = same and ((a is None and b is None) or (a is not None and b is not None and np.array_equal(a, b)))
check("accesa (anche scritta «detect»: true): stessa maschera di prima, pixel per pixel", same)
check("aiuti di prima (senza il campo): ricerca accesa", subject.detect_on({"rect": [0, 0, 1, 1], "keep": [], "remove": []})
      and subject.detect_on(None) and not subject.detect_on(OFF))

# ---------------------------------------------------------------- B. spenta: si parte da vuoto
m0 = subject.subject_mask(scene, off())
check("spenta senza aiuti: gli aiuti contano (si salvano) ma non c'è niente di disegnato",
      subject.has_hints(off()) and not subject.painted(off()))
check("spenta senza aiuti: nessun soggetto (niente foto intera, niente ricerca)", m0 is not None and m0.max() == 0
      and subject.last["empty"])
st0 = photo.PhotoSettings(effect="sketch", width_mm=100.0, subject_hints=off())
out0 = np.asarray(photo.process(Image.fromarray(scene), st0))
check("spenta senza aiuti: lo schizzo è tutto carta bianca (non si incide niente)", out0.min() == 255, int(out0.min()))

b1 = band(300, 250, 380, 250, 0.012)
m1 = subject.subject_mask(scene, off(keep=[keep_stroke(300, 250, 380, 250)]))
check("spenta + un tratto Tieni preciso: resta esattamente il tratto", m1[b1].min() > 0.99 and m1[~grow(b1)].max() < 0.01
      and not subject.last["empty"], (round(float(m1[b1].mean()), 3), float(m1[~grow(b1)].max())))
check("…anche solo una parte del soggetto (l'auto non torna tutta)", m1[car > 0].mean() < 0.2, round(float(m1[car > 0].mean()), 3))

m2 = subject.subject_mask(scene, off(keep=[keep_stroke(250, 300, 330, 300, 0.008, 0, 1)]))
near = max(5, int(0.12 * (360 * 360 + 270 * 270) ** 0.5)) / 360 * W  # limite di «Segui i bordi» (in pixel della foto)
seed = band(250, 300, 330, 300, 0.008)
dist = cv2.distanceTransform((~seed).astype(np.uint8), cv2.DIST_L2, 5)
check("spenta + Tieni con «Segui i bordi»: si allarga alla parte attaccata dell'auto", m2[(car > 0) & (dist < near * 0.4)].mean() > 0.8,
      round(float(m2[(car > 0) & (dist < near * 0.4)].mean()), 3))
check("…solo vicino al pennello e mai sullo sfondo", m2[dist > near * 1.3].max() < 0.01 and m2[(car == 0) & ~grow(car, 9)].max() < 0.01,
      (float(m2[dist > near * 1.3].max()), float(m2[(car == 0) & ~grow(car, 9)].max())))

hole = band(330, 250, 345, 250, 0.01)
m3 = subject.subject_mask(scene, off(keep=[keep_stroke(300, 250, 380, 250)], remove=[keep_stroke(330, 250, 345, 250, 0.01, 1)]))
check("spenta + Tieni e poi Togli dentro: il buco c'è, il resto del tratto resta", m3[hole].max() < 0.01
      and m3[b1 & ~grow(hole, 9)].min() > 0.99)
m4 = subject.subject_mask(scene, off(keep=[keep_stroke(300, 250, 380, 250, 0.012, 1)], remove=[keep_stroke(330, 250, 345, 250, 0.01, 0)]))
check("l'ultima pennellata vince (Togli prima, Tieni dopo: resta)", m4[hole].min() > 0.99)

rect = [0.5, 0.3, 0.85, 0.85]
m5 = subject.subject_mask(scene, off(rect=rect))
check("spenta + Riquadro da solo: il riquadro limita e basta (soggetto vuoto)", m5.max() == 0 and subject.last["empty"])
m6 = subject.subject_mask(scene, off(rect=rect, keep=[keep_stroke(250, 250, 400, 250)]))
b6 = band(250, 250, 400, 250, 0.012)
inside = np.zeros((H, W), bool)
inside[int(0.3 * H) + 1:int(0.85 * H) - 1, int(0.5 * W) + 1:int(0.85 * W) - 1] = True
check("spenta + Riquadro + Tieni che esce: resta solo la parte dentro il riquadro",
      m6[b6 & inside].min() > 0.99 and m6[~inside & ~grow(inside.astype(np.uint8) * 0 + inside, 5)].max() < 0.01)

# ---------------------------------------------------------------- C. foto ritagliata e ruotata, salvataggio
h = off(keep=[keep_stroke(300, 250, 380, 250)])
crop = (0.3, 0.3, 0.8, 0.8)
hc = subject.hints_to_crop(h, crop)
hr = subject.rotate_hints(h, 1)
hm = subject.rotate_hints(h, 0)
check("ritaglio, rotazione e specchio tengono «detect»: false", hc["detect"] is False and hr["detect"] is False
      and hm["detect"] is False)
check("…anche senza nessuna pennellata", subject.hints_to_crop(off(), crop)["detect"] is False
      and subject.rotate_hints(off(), -1)["detect"] is False)
pil = Image.fromarray(scene)
stc = photo.PhotoSettings(effect="sketch", width_mm=100.0, crop=crop, subject_hints=h)
oc = np.asarray(photo.process(pil, stc))
ys, xs = np.nonzero(oc < 250)
cw, ch = (crop[2] - crop[0]) * W, (crop[3] - crop[1]) * H
exp = (np.array([300, 380]) - crop[0] * W) * oc.shape[1] / cw, (250 - crop[1] * H) * oc.shape[0] / ch
check("foto ritagliata: lo schizzo c'è solo dove hai dipinto", len(xs) > 0 and xs.min() >= exp[0][0] - 12 and xs.max() <= exp[0][1] + 12
      and abs(ys.mean() - exp[1]) < 12, (xs.min() if len(xs) else None, xs.max() if len(xs) else None, exp))
st_out = photo.PhotoSettings(effect="sketch", width_mm=100.0, crop=(0.0, 0.0, 0.3, 0.3), subject_hints=h)
o_out = np.asarray(photo.process(pil, st_out))
check("ritaglio che lascia fuori il tratto: niente da incidere e la finestra lo sa", o_out.min() == 255 and subject.last["empty"])
str_ = photo.PhotoSettings(effect="sketch", width_mm=100.0, rotate=90, subject_hints=hr)
orot = np.asarray(photo.process(pil, str_))
ys, xs = np.nonzero(orot < 250)
check("foto ruotata: il tratto gira con la foto (e lo schizzo non esce rovinato)",
      orot.shape == (W, H) and 0 < len(xs) < 0.05 * orot.size and abs(xs.mean() - (H - 1 - 250)) < 12
      and ys.min() >= 300 - 22 and ys.max() <= 380 + 22, (orot.shape, round(float(xs.mean()), 1) if len(xs) else None))
import warnings  # noqa: E402

with warnings.catch_warnings():
    warnings.simplefilter("error")  # prima un NaN rovinava tutto lo schizzo (foto girata di 90° o 270°)
    try:
        oks = [np.asarray(photo.process(pil, photo.PhotoSettings(effect="sketch", width_mm=100.0, rotate=r)))
               for r in (90, 270)]
        nan_ok = all(0.05 < (o < 250).mean() < 0.5 for o in oks)
    except RuntimeWarning:
        nan_ok = False
check("schizzo con la foto girata di 90° o 270°, ricerca accesa: niente valori rovinati (era tutto scuro)", nan_ok)
rt = photo.PhotoSettings.from_dict(json.loads(json.dumps(stc.to_dict())))
check("salva e riapri (impostazioni della foto): «detect»: false resta", rt.subject_hints["detect"] is False
      and rt.subject_hints["keep"] == h["keep"])

# ---------------------------------------------------------------- D. finestra Prepara foto
from freelasercut.core.document import Document, ImageShape
from freelasercut.ui.dialogs_photo import PhotoDialog
from freelasercut.ui.main_window import MainWindow

w = MainWindow()
doc = w.editor.doc
doc.images["a"] = pil
im = ImageShape("a", 100, 75, layer=2)
im.apply(QTransform.fromTranslate(40, 40))
w.editor.add([im], "x")
cs = doc.layer(2)
cs.mode = "image"
im.photo = photo.PhotoSettings(effect="sketch", width_mm=100.0).to_dict()
pd = PhotoDialog(im, pil, cs, (100, 75), w)
pd.resize(1300, 800)
pd.show()
app.processEvents()
v = pd.v_orig
t = v._target()


def drag(a, b, steps=6):
    def ev(kind, pos, btn):
        return QMouseEvent(kind, pos, pos, btn, btn if kind != QMouseEvent.Type.MouseButtonRelease else Qt.NoButton,
                           Qt.NoModifier)
    pa = QPointF(t.left() + a[0] * t.width(), t.top() + a[1] * t.height())
    v.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, pa, Qt.LeftButton))
    for i in range(1, steps + 1):
        f = (a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
        v.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, QPointF(t.left() + f[0] * t.width(), t.top() + f[1] * t.height()),
                            Qt.LeftButton))
    pb = QPointF(t.left() + b[0] * t.width(), t.top() + b[1] * t.height())
    v.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, pb, Qt.LeftButton))


check("«Trova il soggetto da solo» accesa di partenza; senza aiuti il risultato non ha avvisi",
      pd.subj_detect.isChecked() and pd.subj_auto.isEnabled() and (pd._refresh() or pd.v_res.message == ""))
pd.subj_detect.setChecked(False)
pd._refresh()
check("spenta: negli aiuti «detect»: false, «Cerca il soggetto nel riquadro» non serve più",
      pd.hints == OFF and pd.settings().subject_hints["detect"] is False and not pd.subj_auto.isEnabled())
check("spenta e niente dipinto: l'anteprima dice di dipingere con Tieni (non uno schizzo vuoto muto)",
      "Tieni" in pd.v_res.message and "Tieni" in pd.subj_note.text() and not pd.subj_clear.isEnabled(), pd.v_res.message)
grab = pd.v_res.grab()
check("…e l'avviso si vede sopra l'anteprima", not grab.isNull())
pd.subj_tools["keep"].setChecked(True)
drag((0.45, 0.52), (0.6, 0.52))
pd._refresh()
check("Tieni con il mouse: il tratto entra negli aiuti, la ricerca resta spenta",
      len(pd.hints["keep"]) == 1 and pd.hints["detect"] is False and pd.v_res.message == "" and pd.subj_clear.isEnabled())
va = v.veil
alpha = np.frombuffer(va.constBits(), np.uint8).reshape(va.height(), va.width(), 4)[..., 3]
check("velo rosso dappertutto tranne dove hai dipinto",
      alpha[int(0.52 * va.height()), int(0.52 * va.width())] < 20 and alpha[int(0.3 * va.height()), int(0.3 * va.width())] > 100
      and alpha[int(0.65 * va.height()), int(0.3 * va.width())] > 100)
pd.clear_hints()
pd._refresh()
check("«Togli gli aiuti» con la casella spenta: si riparte da vuoto (non dalla ricerca automatica)",
      pd.hints == OFF and not pd.subj_detect.isChecked() and "Tieni" in pd.v_res.message)
pd.subj_detect.setChecked(True)
pd._refresh()
check("riaccesa: aiuti vuoti = ricerca automatica come prima", pd.hints is None and pd.v_res.message == ""
      and pd.subj_auto.isEnabled())
pd.subj_detect.setChecked(False)
pd.subj_tools["rect"].setChecked(True)
drag((0.5, 0.3), (0.9, 0.9))
check("Riquadro con la casella spenta: limita la zona, la ricerca resta spenta",
      pd.hints["rect"] is not None and pd.hints["detect"] is False)
pd.subj_detect.setChecked(True)
check("riaccesa con un riquadro: il riquadro resta, la ricerca torna", pd.hints is not None and "detect" not in pd.hints
      and pd.hints["rect"] is not None)
pd.close()

pd2 = PhotoDialog(im, pil, cs, (100, 75), w)
im.photo = photo.PhotoSettings(effect="sketch", width_mm=100.0, subject_hints=off()).to_dict()
pd3 = PhotoDialog(im, pil, cs, (100, 75), w)
check("riaprendo la finestra: la casella torna com'era (accesa senza aiuti, spenta con «detect»: false)",
      pd2.subj_detect.isChecked() and not pd3.subj_detect.isChecked() and pd3.hints == OFF)
pd2.close()
pd3.close()

# ---------------------------------------------------------------- E. dal programma: applica, annulla, salva e riapri
im.photo = photo.PhotoSettings(effect="sketch", width_mm=100.0).to_dict()
w.editor.select([im])
spin(0.1)
orig_exec = PhotoDialog.exec


def run_dialog(setup, answer=QDialog.Accepted):
    def ex(self):
        self.show()
        spin(0.1)
        setup(self)
        self._timer.stop()
        self._refresh()
        if answer == QDialog.Accepted:
            self._accept()
        return answer
    PhotoDialog.exec = ex
    w.photo_dialog()
    spin(0.1)
    PhotoDialog.exec = orig_exec


def setup_off(d):
    d.subj_detect.setChecked(False)
    d.subj_tools["keep"].setChecked(True)
    global v, t
    v, t = d.v_orig, d.v_orig._target()
    drag((0.45, 0.52), (0.6, 0.52))


before = json.dumps(im.photo, sort_keys=True)
run_dialog(setup_off, QDialog.Rejected)
check("Annulla nella finestra: la foto non cambia", json.dumps(im.photo, sort_keys=True) == before)
run_dialog(setup_off)
cur = [s for s in doc.shapes if isinstance(s, ImageShape)][0]
hs = (cur.photo or {}).get("subject_hints") or {}
check("Applica: la foto preparata ricorda la ricerca spenta e il tratto", hs.get("detect") is False and len(hs.get("keep", [])) == 1)
proc = np.asarray(doc.images[cur.image_id].convert("L"))
check("…e la foto preparata ha lo schizzo solo nel tratto (il resto è carta)", (proc < 250).mean() < 0.08 and (proc < 250).any(),
      round(float((proc < 250).mean()), 3))
path = os.path.join(tempfile.mkdtemp(), "prova.flc")
doc.save(path)
d2 = Document.load(path)
im2 = [s for s in d2.shapes if isinstance(s, ImageShape)][0]
check("salva e riapri il progetto: la ricerca resta spenta", im2.photo["subject_hints"]["detect"] is False)
w.editor.undo()
cur = [s for s in doc.shapes if isinstance(s, ImageShape)][0]
check("Annulla: la foto torna senza aiuti", json.dumps(cur.photo, sort_keys=True) == before)
w.editor.redo()
cur = [s for s in doc.shapes if isinstance(s, ImageShape)][0]
check("Ripeti: la ricerca spenta torna", cur.photo["subject_hints"]["detect"] is False)

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(code)
