# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.0: «Schizzo del soggetto» rifatto (segnalazione di un utente: volti poco riconoscibili, tratto troppo
«riempitivo», sfondo non sempre tolto: ombra sul ghiaino e canestro dietro un'auto).
- aiuti per il soggetto in Prepara foto: riquadro, pennello «tieni» e «togli» (GrabCut di OpenCV parte da lì);
- tratto nuovo a matita: grafite sfumata a tratti, contorni, scuri pieni, grana della carta.
Tutto dentro FreeLaserCut: niente modelli né dati scaricati."""
import json
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
import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QTransform
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
ANSWER = [QMessageBox.Yes]
QMessageBox.question = staticmethod(lambda *a, **k: ANSWER[0])  # noqa: E731
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)

from freelasercut.core import photo, photo_fx, subject

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


# ---------------------------------------------------------------- scena: «auto» grigia su ghiaino, con un palo dietro
H, W = 480, 640
rng = np.random.default_rng(4)
scene = np.zeros((H, W, 3), np.uint8)
scene[:] = (190, 200, 210)  # cielo
scene[300:] = (165, 160, 150)  # ghiaino
scene = np.clip(scene + rng.normal(0, 7, scene.shape), 0, 255).astype(np.uint8)
cv2.rectangle(scene, (470, 60), (482, 300), (60, 60, 60), -1)  # palo del canestro
cv2.rectangle(scene, (440, 40), (520, 100), (230, 230, 230), -1)  # tabellone
cv2.rectangle(scene, (440, 40), (520, 100), (40, 40, 40), 3)
car = np.zeros((H, W), np.uint8)
cv2.rectangle(car, (120, 230), (500, 360), 1, -1)
cv2.rectangle(car, (200, 170), (420, 240), 1, -1)
scene[car > 0] = (85, 90, 100)
for cx in (190, 430):
    cv2.circle(scene, (cx, 360), 45, (25, 25, 25), -1)
    cv2.circle(scene, (cx, 360), 25, (200, 200, 205), -1)
    cv2.circle(car, (cx, 360), 45, 1, -1)
cv2.ellipse(scene, (310, 410), (230, 22), 0, 0, 360, (95, 92, 88), -1)  # ombra sul ghiaino
gray = cv2.cvtColor(scene, cv2.COLOR_RGB2GRAY).astype(np.float32)
pole = np.zeros((H, W), bool)
pole[60:160, 470:482] = True
shadow = np.zeros((H, W), np.uint8)
cv2.ellipse(shadow, (310, 418), (200, 12), 0, 0, 360, 1, -1)
shadow = (shadow > 0) & (car == 0)

# ---------------------------------------------------------------- aiuti
check("aiuti: vuoti = nessun aiuto", not subject.has_hints(None) and not subject.has_hints({"rect": None, "keep": [],
                                                                                             "remove": []}))
h = {"rect": [0.1, 0.2, 0.5, 0.6], "keep": [[0.02, [0.3, 0.4, 0.35, 0.45]]], "remove": []}
hc = subject.hints_to_crop(h, (0.1, 0.2, 0.6, 0.7))
check("aiuti disegnati sulla foto intera, riportati sulla parte ritagliata", np.allclose(hc["rect"], [0, 0, 0.8, 0.8])
      and np.allclose(hc["keep"][0][1], [0.4, 0.4, 0.5, 0.5]) and hc["keep"][0][0] > 0.02, hc)
r4 = h
for _ in range(4):
    r4 = subject.rotate_hints(r4, 90)
check("quattro rotazioni di 90°: aiuti di nuovo dove erano", np.allclose(r4["rect"], h["rect"])
      and np.allclose(r4["keep"][0][1], h["keep"][0][1]))
check("specchio due volte: uguale", np.allclose(subject.rotate_hints(subject.rotate_hints(h, 0), 0)["keep"][0][1],
                                                 h["keep"][0][1]))

# ---------------------------------------------------------------- soggetto senza modello
subject._CACHE.clear()
rect = {"rect": [140 / W, 150 / H, 520 / W, 420 / H], "keep": [], "remove": []}
m1 = subject.subject_mask(scene, rect)
check("con il riquadro intorno all'auto: il palo dietro resta fuori", m1 is not None and m1[pole].mean() < 0.1
      and m1[car > 0].mean() > 0.85, None if m1 is None else (round(float(m1[pole].mean()), 2),
                                                             round(float(m1[car > 0].mean()), 2)))
rem = {"rect": rect["rect"], "keep": [], "remove": [[0.012, [200 / W, 418 / H, 310 / W, 420 / H, 420 / W, 418 / H]]]}
m2 = subject.subject_mask(scene, rem)
check("pennello «togli» sull'ombra: l'ombra sparisce", m2 is not None and m2[shadow].mean() < 0.2
      and m2[car > 0].mean() > 0.8, None if m2 is None else round(float(m2[shadow].mean()), 2))
keep = {"rect": None, "keep": [[0.01, [476 / W, 70 / H, 476 / W, 150 / H]]], "remove": []}
m3 = subject.subject_mask(scene, keep)
check("pennello «tieni» sul palo: il palo fa parte del soggetto", m3 is not None and m3[pole].mean() > 0.6,
      None if m3 is None else round(float(m3[pole].mean()), 2))
check("stessi aiuti, stessa maschera (anteprima e incisione uguali)",
      np.array_equal(subject.subject_mask(scene, rem), m2))

# ---------------------------------------------------------------- tratto nuovo
out = photo_fx.apply(gray, "sketch", 100.0, 0.5, 0.5, 0, rgb=scene, hints=rem)[0]
check("schizzo con gli aiuti: cielo, palo e ombra bianchi (niente da incidere)",
      out[:40, :40].min() >= 250 and out[pole].min() >= 240 and out[shadow].mean() > 245,
      (float(out[pole].min()), round(float(out[shadow].mean()), 1)))
inside = cv2.erode(car, np.ones((9, 9), np.uint8)) > 0
paper = float(np.percentile(out[inside], 80)) - float(np.percentile(out[inside], 20))
check("dentro il soggetto tratti di grafite con chiari e scuri (non un grigio «riempitivo»)", paper > 25, round(paper))
check("ruote (scuro pieno) più scure della carrozzeria", out[350:370, 150:160].mean() < out[250:300, 250:350].mean() - 30,
      (round(float(out[350:370, 150:160].mean())), round(float(out[250:300, 250:350].mean()))))
light = photo_fx.apply(gray, "sketch", 100.0, 0.1, 0.5, 0, rgb=scene, hints=rem)[0]
dark = photo_fx.apply(gray, "sketch", 100.0, 0.9, 0.5, 0, rgb=scene, hints=rem)[0]
check("Intensità: più alta = più scuro", dark[inside].mean() < light[inside].mean() - 10,
      (round(float(light[inside].mean())), round(float(dark[inside].mean()))))
pil = Image.fromarray(scene)
st = photo.PhotoSettings(effect="sketch", width_mm=100.0, subject_hints=rem)
check("Prepara foto: gli aiuti passano nel risultato vero", np.asarray(photo.process(pil, st))[shadow].mean() > 245)
st2 = photo.PhotoSettings.from_dict(json.loads(json.dumps(st.to_dict())))
check("aiuti salvati e riletti con il progetto", st2.subject_hints == rem)
check("file rovinato: aiuti sbagliati ignorati", photo.PhotoSettings.from_dict({"subject_hints": "x"}).subject_hints is None)
cropd = photo.PhotoSettings(effect="sketch", width_mm=50.0, subject_hints=rem, crop=(0.0, 0.0, 0.5, 1.0))
check("con il ritaglio gli aiuti restano sulla stessa parte della foto", photo.process(pil, cropd).size[0] == W // 2)


# ---------------------------------------------------------------- aiuti prevedibili (prove di un utente su foto vere)
tex = np.clip(rng.normal(128, 40, (300, 400, 3)), 0, 255).astype(np.uint8)  # foto «tutta uguale»: niente soggetto chiaro
tex = cv2.GaussianBlur(tex, (0, 0), 1.2)
subject._CACHE.clear()
auto = subject.subject_mask(tex, None)
check("foto senza un soggetto chiaro: nessuna maschera e la finestra lo può dire", auto is None and subject.last["auto_failed"])
box = {"rect": [0.6, 0.1, 0.9, 0.35], "keep": [], "remove": []}
mb = subject.subject_mask(tex, box)
yy, xx = np.mgrid[0:300, 0:400]
inbox = (xx >= 240) & (xx < 360) & (yy >= 30) & (yy < 105)
away = ~cv2.dilate(inbox.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
check("riquadro: fuori è sempre sfondo, anche quando dentro non si trova niente (resta il riquadro)",
      mb is not None and mb[away].max() < 0.05 and mb[inbox].mean() > 0.5,
      None if mb is None else (round(float(mb[away].max()), 2), round(float(mb[inbox].mean()), 2)))
rm = {"rect": None, "keep": [], "remove": [[0.03, [0.1, 0.5, 0.3, 0.5]]]}
mr = subject.subject_mask(tex, rm)
stroke = (np.abs(yy - 150) < 6) & (xx > 50) & (xx < 110)
far_r = ~cv2.dilate(stroke.astype(np.uint8), np.ones((120, 120), np.uint8)).astype(bool)
check("«togli» su una foto dove lo sfondo non si trovava: sparisce dove passi il pennello, il resto resta",
      mr is not None and mr[stroke].mean() < 0.1 and mr[far_r].mean() > 0.9,
      None if mr is None else (round(float(mr[stroke].mean()), 2), round(float(mr[far_r].mean()), 2)))
outr = photo_fx.apply(cv2.cvtColor(tex, cv2.COLOR_RGB2GRAY).astype(np.float32), "sketch", 60.0, 0.5, 0.5, 0, rgb=tex, hints=rm)[0]
check("…e nello schizzo quella parte è carta bianca", outr[stroke].min() >= 250)
base = subject.subject_mask(scene, rect)
k1 = {"rect": rect["rect"], "keep": [[0.02, [190 / W, 360 / H]]], "remove": []}
mk1 = subject.subject_mask(scene, k1)
check("«tieni» su una parte che c'è già (la ruota): non cambia niente altrove", mk1 is not None and
      np.abs(mk1 - base).mean() < 0.01, round(float(np.abs(mk1 - base).mean()), 4))
YY, XX = np.mgrid[0:H, 0:W]
far = (YY < 120) & (XX < 300)
k2 = {"rect": None, "keep": [[0.01, [476 / W, 70 / H, 476 / W, 150 / H]]], "remove": []}
mk2 = subject.subject_mask(scene, k2)
check("«tieni» aggiunge solo intorno al pennello (il cielo lontano resta sfondo)", mk2[pole].mean() > 0.6
      and mk2[far].mean() < 0.05, (round(float(mk2[pole].mean()), 2), round(float(mk2[far].mean()), 3)))

# ---------------------------------------------------------------- Prepara foto
from freelasercut.core.document import ImageShape
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
check("effetto Schizzo: compare il riquadro «Soggetto»", pd.subj_box.isVisibleTo(pd))
pd.effect.setCurrentIndex(pd.effect.findData("pencil"))
check("con un altro effetto il riquadro «Soggetto» sparisce", not pd.subj_box.isVisibleTo(pd))
pd.effect.setCurrentIndex(pd.effect.findData("sketch"))
pd.subj_tools["rect"].setChecked(True)
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


crop_before = pd.crop
drag((0.2, 0.3), (0.8, 0.88))
check("Riquadro: trascinando sulla foto si disegna il riquadro (il ritaglio non cambia)",
      pd.hints and np.allclose(pd.hints["rect"], [0.2, 0.3, 0.8, 0.88], atol=0.01) and pd.crop == crop_before, pd.hints)
pd.subj_tools["remove"].setChecked(True)
check("un solo strumento alla volta", not pd.subj_tools["rect"].isChecked())
drag((0.3, 0.87), (0.65, 0.87))
check("Togli: pennellata registrata", len(pd.hints["remove"]) == 1 and len(pd.hints["remove"][0][1]) >= 4)
st_d = pd.settings()
check("le impostazioni della foto portano gli aiuti", subject.has_hints(st_d.subject_hints))
pd._rot(90)
check("ruotando la foto gli aiuti girano con lei", np.allclose(pd.hints["rect"], subject.rotate_hints(st_d.subject_hints,
                                                                                                    90)["rect"]))
pd._rot(-90)
pd.clear_hints()
check("«Togli gli aiuti»", pd.hints is None and pd.settings().subject_hints is None and not pd.subj_clear.isEnabled())
pd.close()

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.TerminateProcess(k32.GetCurrentProcess(), code)
os._exit(code)
