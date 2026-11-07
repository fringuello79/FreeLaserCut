# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.6, dalle prove di un utente:
- il simulatore non tocca più il profilo della macchina vera (si era ritrovato area, scheda e accelerazioni finte);
- Schizzo del soggetto: Togli e Tieni precisi come una gomma (l'ultima pennellata vince), «Segui i bordi» per il
  comportamento di prima; il Riquadro tiene tutto quello che sta dentro, «Cerca il soggetto nel riquadro» per
  cercarlo da solo; velo rosso sulla foto originale sulle parti che spariscono."""
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
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core import photo, subject

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


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
YY, XX = np.mgrid[0:H, 0:W]

# ---------------------------------------------------------------- riquadro
rect = [0.15, 0.3, 0.85, 0.85]
m_box = subject.subject_mask(scene, {"rect": rect, "keep": [], "remove": [], "auto": False})
inside = (XX >= 0.15 * W + 1) & (XX < 0.85 * W - 1) & (YY >= 0.3 * H + 1) & (YY < 0.85 * H - 1)
check("Riquadro (di partenza): dentro resta tutto, fuori sparisce", m_box[inside].min() > 0.99 and m_box[~inside
      & ((XX < 0.15 * W - 2) | (XX > 0.85 * W + 2) | (YY < 0.3 * H - 2) | (YY > 0.85 * H + 2))].max() < 0.01)
m_auto = subject.subject_mask(scene, {"rect": rect, "keep": [], "remove": [], "auto": True})
check("«Cerca il soggetto nel riquadro»: dentro lo sfondo sparisce", m_auto[inside & (car == 0)].mean() < 0.5
      and m_auto[car > 0].mean() > 0.8, (round(float(m_auto[inside & (car == 0)].mean()), 2)))
m_old = subject.subject_mask(scene, {"rect": rect, "keep": [], "remove": []})
check("aiuti salvati prima della 0.17.6 (senza «auto»): come allora (cerca nel riquadro)", np.abs(m_old - m_auto).max() < 1e-6)

# ---------------------------------------------------------------- pennelli precisi
stroke = [0.012, [300 / W, 250 / H, 380 / W, 250 / H], 0, 0]  # Togli preciso sulla carrozzeria
m_rem = subject.subject_mask(scene, {"rect": rect, "keep": [], "remove": [stroke], "auto": False})
band = np.zeros((H, W), np.uint8)
cv2.line(band, (300, 250), (380, 250), 1, int(round(0.012 * (W * W + H * H) ** 0.5 * 2)))
grow = cv2.dilate(band, np.ones((5, 5), np.uint8)) > 0
check("Togli preciso: sparisce esattamente sotto il pennello", m_rem[band > 0].max() < 0.01)
check("…e nient'altro cambia (niente pezzi in più tolti)", np.abs(m_rem - m_box)[~grow].max() < 1e-6,
      float(np.abs(m_rem - m_box)[~grow].max()))
pole = np.zeros((H, W), bool)
pole[150:300, 470:482] = True
pp = [0.004, [476 / W, 220 / H, 476 / W, 232 / H]]
m_pp = subject.subject_mask(scene, {"rect": rect, "keep": [], "remove": [pp + [0, 0]], "auto": False})
m_ps = subject.subject_mask(scene, {"rect": rect, "keep": [], "remove": [pp + [0, 1]], "auto": False})
m_legacy = subject.subject_mask(scene, {"rect": rect, "keep": [], "remove": [pp], "auto": False})
check("con «Segui i bordi» la pennellata funziona come prima della 0.17.6 (e diversa da quella precisa)",
      np.abs(m_ps - m_legacy).max() < 1e-6 and np.abs(m_ps - m_pp).max() > 0.5)
keep_over = [0.006, [320 / W, 250 / H, 340 / W, 250 / H], 1, 0]
m_ord = subject.subject_mask(scene, {"rect": rect, "keep": [keep_over], "remove": [stroke], "auto": False})
check("l'ultima pennellata vince: Tieni dopo Togli riporta la parte", m_ord[250, 330] > 0.99 and m_ord[250, 370] < 0.01)
m_ord2 = subject.subject_mask(scene, {"rect": rect, "keep": [[0.006, keep_over[1], 0, 0]],
                                      "remove": [[stroke[0], stroke[1], 1, 0]], "auto": False})
check("…e Togli dopo Tieni la toglie", m_ord2[250, 330] < 0.01)
keep_out = [0.01, [0.05, 0.1, 0.1, 0.1], 0, 0]
m_out = subject.subject_mask(scene, {"rect": rect, "keep": [keep_out], "remove": [], "auto": False})
check("Tieni fuori dal riquadro: il riquadro vale (fuori è sfondo)", m_out[int(0.1 * H), int(0.07 * W)] < 0.01)
m_noq = subject.subject_mask(scene, {"rect": None, "keep": [], "remove": [stroke]})
check("senza riquadro: il soggetto si cerca da solo e il Togli preciso toglie solo lì", m_noq is not None
      and m_noq[band > 0].max() < 0.01)
hc = subject.hints_to_crop({"rect": rect, "keep": [], "remove": [stroke], "auto": True}, (0.1, 0.1, 0.9, 0.9))
hr = subject.rotate_hints({"rect": rect, "keep": [], "remove": [stroke], "auto": False}, 90)
check("ritaglio e rotazione tengono ordine, «Segui i bordi» e «auto»",
      hc["auto"] is True and hc["remove"][0][2:] == [0, 0] and hr["auto"] is False and hr["remove"][0][2:] == [0, 0])

# ---------------------------------------------------------------- Prepara foto
from freelasercut.core.document import ImageShape
from freelasercut.ui.dialogs_photo import PhotoDialog
from freelasercut.ui.main_window import MainWindow

w = MainWindow()
doc = w.editor.doc
pil = Image.fromarray(scene)
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


check("caselle «Segui i bordi» e «Cerca il soggetto nel riquadro», spente di partenza",
      not pd.subj_edges.isChecked() and not pd.subj_auto.isChecked())
pd._refresh()
check("velo rosso sulla foto originale (anche senza aiuti, sullo sfondo trovato da solo)", v.veil is not None)
pd.subj_tools["rect"].setChecked(True)
drag((0.15, 0.3), (0.85, 0.85))
check("Riquadro nuovo: «auto» spento", pd.hints["auto"] is False)
pd.subj_tools["remove"].setChecked(True)
drag((0.47, 0.52), (0.6, 0.52))
check("Togli: pennellata precisa, con il suo ordine", pd.hints["remove"][-1][2:] == [0, 0], pd.hints["remove"][-1])
pd.subj_edges.setChecked(True)
pd.subj_tools["keep"].setChecked(True)
drag((0.5, 0.52), (0.52, 0.52))
check("con «Segui i bordi» acceso la nuova pennellata lo segue", pd.hints["keep"][-1][2:] == [1, 1], pd.hints["keep"][-1])
pd.subj_auto.setChecked(True)
check("«Cerca il soggetto nel riquadro» va negli aiuti", pd.hints["auto"] is True and pd.settings().subject_hints["auto"])
pd._refresh()
va = v.veil
alpha = np.frombuffer(va.constBits(), np.uint8).reshape(va.height(), va.width(), 4)[..., 3] if va is not None else None
check("velo: fuori dal riquadro velato di rosso, sul soggetto no",
      alpha is not None and alpha[2, 2] > 100 and alpha[int(0.6 * va.height()), int(0.3 * va.width())] < 20)
pd.close()

# ---------------------------------------------------------------- simulatore e profilo della macchina vera
from freelasercut.grbl import SIM_PORT

p = w.profile
p.bed_x, p.bed_y, p.accel_x = 305.0, 365.0, 3000.0
sim_settings = {130: "450.000", 131: "440.000", 120: "500.000", 121: "500.000", 30: "1000.000", 51: "MKS_DLC"}
w.ctl.port = SIM_PORT
w.machine.on_settings(dict(sim_settings))
check("simulatore: le sue impostazioni finte non entrano nel profilo della macchina vera",
      (w.profile.bed_x, w.profile.bed_y, w.profile.accel_x) == (305, 365, 3000) and w.machine.table.rowCount() == 6)
w.profile.save()
neg = w.profile.negative_space
w.on_connection(True, "")  # collegato al simulatore
w.on_homed(True, not bool(neg))
from freelasercut.profile import MachineProfile

check("simulatore: l'homing non salva il profilo sul disco", MachineProfile.load(w.profile.path()).negative_space == neg)
w.ctl.port = None
w.on_connection(False, "")
check("staccando il simulatore torna il profilo salvato della macchina vera",
      w.profile.negative_space == neg and (w.profile.bed_x, w.profile.bed_y) == (305, 365))
w.ctl.port = "COM7"
w.machine.on_settings({130: "305.000", 131: "365.000", 120: "2500.000", 121: "2500.000"})
check("macchina vera: le impostazioni lette entrano nel profilo come prima", w.profile.accel_x == 2500)
w.ctl.port = None
from freelasercut import machines
from freelasercut.ui.dialogs_machine import MachineWizard

mw = MachineWizard(w)
mw._done(dict(baud=115200, banner=["Grbl 1.1h"], info=["[VER:1.1.2023080801:]", "[MSG:FW:LGT V1.2.3|MB:LS_ESP32-SIM]"],
              settings=dict(sim_settings)), machines.PortInfo(SIM_PORT, "Simulatore"))
check("Riconosci la macchina con il simulatore: il profilo si chiama «Simulatore» (mai sopra quello vero)",
      mw.name.text() == "Simulatore", mw.name.text())
mw.close()

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
os._exit(code)
