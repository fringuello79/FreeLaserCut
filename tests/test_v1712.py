# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.12 (da un utente): Schizzo del soggetto, pennello di nuovo veloce e zoom sulla foto originale.

- Le pennellate finite si disegnano una volta sola: a ogni movimento del mouse si ridisegna solo quella in corso
  (prima tutte, pezzo per pezzo: più pennellate, più lento).
- Una pennellata è un solo tracciato: colore uniforme anche dove ripassa su sé stessa.
- Foto originale con lo zoom (rotella, pulsanti, tasto destro per spostarsi) e cerchio del pennello sotto il mouse.
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QTransform, QWheelEvent
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

import freelasercut
from freelasercut.core import photo
from freelasercut.updater import parse_version
from freelasercut.ui.dialogs_photo import PhotoDialog, _View

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def mouse(v, kind, pos, btn=Qt.LeftButton):
    buttons = Qt.NoButton if kind == QMouseEvent.Type.MouseButtonRelease else btn
    if kind == QMouseEvent.Type.MouseMove and btn == Qt.NoButton:
        buttons = Qt.NoButton
    e = QMouseEvent(kind, pos, pos, btn if kind != QMouseEvent.Type.MouseMove else Qt.NoButton, buttons, Qt.NoModifier)
    {QMouseEvent.Type.MouseButtonPress: v.mousePressEvent, QMouseEvent.Type.MouseMove: v.mouseMoveEvent,
     QMouseEvent.Type.MouseButtonRelease: v.mouseReleaseEvent,
     QMouseEvent.Type.MouseButtonDblClick: v.mouseDoubleClickEvent}[kind](e)


def at(v, fx, fy):
    t = v._target()
    return QPointF(t.left() + fx * t.width(), t.top() + fy * t.height())


check("versione 0.17.12 o successiva", parse_version(freelasercut.__version__) >= (0, 17, 12), freelasercut.__version__)

# ---------------------------------------------------------------- velocità del pennello
v = _View("prova", croppable=True, zoomable=True)
v.resize(650, 700)
v.show()
app.processEvents()
a = np.full((825, 1100, 3), 200, np.uint8)
v.qimg = QImage(a.data, 1100, 825, 3 * 1100, QImage.Format_RGB888).copy()
rng = np.random.default_rng(2)
v.hints = {"rect": None, "keep": [], "remove": [], "auto": False}
for i in range(60):
    xs = [float(x) for x in np.clip(np.cumsum(rng.normal(0, 0.01, 120)) + rng.random() * 0.8, 0, 1).round(4)]
    v.hints["remove" if i % 2 else "keep"].append([0.02, xs, i, 0])
v.hint_mode = "remove"
calls = []
real_stroke = _View.__dict__["_stroke"]
_View._stroke = staticmethod(lambda *a: (calls.append(1), real_stroke.__func__(*a)))
v.repaint()
first = len(calls)
calls.clear()
mouse(v, QMouseEvent.Type.MouseButtonPress, at(v, 0.3, 0.3))
v.repaint()
calls.clear()
for k in range(10):
    mouse(v, QMouseEvent.Type.MouseMove, at(v, 0.3 + 0.02 * k, 0.32), Qt.LeftButton)
    v.repaint()
during = len(calls)
mouse(v, QMouseEvent.Type.MouseButtonRelease, at(v, 0.5, 0.32))
check("prima volta: tutte le pennellate disegnate (60)", first == 60, first)
check("mentre si passa il pennello si ridisegna solo la pennellata in corso (10 movimenti → 10, non 600)",
      during == 10, during)
calls.clear()
v.repaint()
v.repaint()
check("finita la pennellata: disegnate una volta, poi riusate", len(calls) == 61, len(calls))
_View._stroke = real_stroke

# colore uniforme dove la pennellata ripassa su sé stessa
w2 = _View("colore", croppable=True)
w2.resize(400, 400)
w2.show()
w2.qimg = QImage(a.data, 1100, 825, 3 * 1100, QImage.Format_RGB888).copy()
w2.hints = {"rect": None, "keep": [], "remove": [[0.02, [0.2, 0.5, 0.8, 0.5, 0.5, 0.2, 0.5, 0.8], 0, 0]], "auto": False}
app.processEvents()
img = w2.grab().toImage()
t = w2._target()
cross = img.pixelColor(int(t.left() + 0.5 * t.width()), int(t.top() + 0.5 * t.height()))
single = img.pixelColor(int(t.left() + 0.3 * t.width()), int(t.top() + 0.5 * t.height()))
check("colore uniforme dove la pennellata ripassa (niente punti più scuri)",
      single.name() != "#c8c8c8" and abs(cross.red() - single.red()) <= 3 and abs(cross.green() - single.green()) <= 3,
      (cross.name(), single.name()))

# ---------------------------------------------------------------- zoom sulla foto originale
v.hint_mode = None
v.hints = None
v.set_zoom(1.0)
c0 = at(v, 0.5, 0.5)
v.wheelEvent(QWheelEvent(c0, c0, QPoint(0, 0), QPoint(0, 360), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
check("rotella sulla foto originale: ingrandisce", v.zoom > 1.9, v.zoom)
f_before = v._frac(c0)
mouse(v, QMouseEvent.Type.MouseButtonPress, c0, Qt.RightButton)
mouse(v, QMouseEvent.Type.MouseMove, c0 + QPointF(80, 0), Qt.RightButton)
mouse(v, QMouseEvent.Type.MouseButtonRelease, c0 + QPointF(80, 0), Qt.RightButton)
f_after = v._frac(c0)
check("tasto destro trascinato: ci si sposta nella foto ingrandita", f_after[0] < f_before[0] - 0.02, (f_before, f_after))
check("…e il ritaglio non cambia", v.crop is None or tuple(v.crop) == (0.0, 0.0, 1.0, 1.0), v.crop)
# pennellata a zoom: va nel punto giusto della foto
v.hint_mode = "keep"
v.hints = None
p = at(v, 0.6, 0.55)
mouse(v, QMouseEvent.Type.MouseButtonPress, p)
mouse(v, QMouseEvent.Type.MouseButtonRelease, p)
xs = v.hints["keep"][0][1]
check("pennellata con lo zoom: nel punto giusto della foto", abs(xs[0] - 0.6) < 0.01 and abs(xs[1] - 0.55) < 0.01, xs)
# ritaglio a zoom
v.hint_mode = None
got = []
v.crop_changed.connect(got.append)
mouse(v, QMouseEvent.Type.MouseButtonPress, at(v, 0.45, 0.45))
mouse(v, QMouseEvent.Type.MouseMove, at(v, 0.6, 0.6), Qt.LeftButton)
mouse(v, QMouseEvent.Type.MouseButtonRelease, at(v, 0.6, 0.6))
check("ritaglio con lo zoom: nelle frazioni giuste della foto", got and abs(got[-1][0] - 0.45) < 0.01
      and abs(got[-1][2] - 0.6) < 0.01, got)
mouse(v, QMouseEvent.Type.MouseButtonDblClick, c0, Qt.RightButton)
check("doppio clic col tasto destro: torna a tutta la foto", abs(v.zoom - 1.0) < 1e-6, v.zoom)

# cerchio del pennello
v.hint_mode = "remove"
v.brush = 0.03
mouse(v, QMouseEvent.Type.MouseMove, at(v, 0.5, 0.5), Qt.NoButton)
img = v.grab().toImage()
t = v._target()
rad = 0.03 * (t.width() ** 2 + t.height() ** 2) ** 0.5
edge = img.pixelColor(int(t.left() + 0.5 * t.width() + rad), int(t.top() + 0.5 * t.height()))
inside = img.pixelColor(int(t.left() + 0.5 * t.width() + rad / 2), int(t.top() + 0.5 * t.height()))
check("cerchio del pennello sotto il mouse, grande come il pennello", v._hover is not None
      and edge.name() != inside.name(), (edge.name(), inside.name()))

# ---------------------------------------------------------------- nella finestra Prepara foto
from freelasercut.core.document import ImageShape
from freelasercut.ui.main_window import MainWindow

w = MainWindow()
doc = w.editor.doc
pil = Image.fromarray(np.full((600, 800, 3), 128, np.uint8))
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
check("Prepara foto: la foto originale ha lo zoom", pd.v_orig.zoomable and pd.v_orig.croppable)
pd.zo_in.click()
z1 = pd.v_orig.zoom
pd.zo_fit.click()
check("pulsanti «Zoom originale»: + ingrandisce, «Tutta la foto» torna indietro", z1 > 1.4 and abs(pd.v_orig.zoom - 1) < 1e-6,
      (z1, pd.v_orig.zoom))
check("…e non toccano lo zoom dell'anteprima a destra", abs(pd.v_res.zoom - 1) < 1e-6)
pd.subj_tools["remove"].setChecked(True)
check("pennello di partenza grande come prima (0,018)", abs(pd.v_orig.brush - 0.018) < 1e-9, pd.v_orig.brush)
pd.subj_brush.setValue(1)
check("pennello più fine possibile: metà di prima, utile con lo zoom", abs(pd.v_orig.brush - 0.003) < 1e-9, pd.v_orig.brush)
pd.close()

# ---------------------------------------------------------------- autofocus con sonda
import time

from freelasercut import autofocus as af
from freelasercut.grbl import SIM_PORT, GrblController
from freelasercut.profile import MachineProfile

L = af.lines(8, 30, 200, 40)
check("autofocus: laser spento, discesa con la sonda, secondo tocco lento, risalita di 8 mm, di nuovo G90",
      L == ["M5", "G91 G21", "G38.2 Z-30.000 F200", "G0 Z2.000", "G38.2 Z-3.000 F40", "G0 Z8.000", "G90"], L)
L2 = af.lines(8, 30, 200, 40, toward_minus=False)
check("…con il verso al contrario i segni si invertono", L2[2].startswith("G38.2 Z30") and L2[5] == "G0 Z-8.000", L2)
check("stato della sonda dal report: toccata, finecorsa Z, libera",
      (af.pin_state("P"), af.pin_state("XZ"), af.pin_state(None)) == ("touch", "zlimit", "free"))


def until(fn, t=10.0):
    end = time.time() + t
    while time.time() < end and not fn():
        app.processEvents()
        time.sleep(0.02)
    return fn()


c = GrblController()
res = []
c.autofocus_done.connect(lambda ok, m, z: res.append((ok, m, z)))
c.connect_port(SIM_PORT)
until(lambda: c.last_status.get("state") == "Idle")
sim = c.sim
sim.surface_z = -20.0
until(lambda: c.last_status.get("pins") is None, 3)
check("autofocus: parte", c.autofocus(8, 30, 200, 40) is True)
until(lambda: res)
check("…tocca il materiale e si ferma 8 mm sopra", res and res[-1][0] and abs(res[-1][2] + 20) < 1e-6
      and abs(sim.pos[2] + 12) < 1e-6, (res, sim.pos))
check("…e la scheda torna in coordinate assolute (G90)", sim.absolute)

res.clear()
sim.surface_z = -100.0
c.autofocus(8, 30, 200, 40)
until(lambda: res)
check("nessun tocco entro la corsa: si ferma da sola e lo spiega", res and not res[-1][0] and "corsa massima" in res[-1][1],
      res)
until(lambda: sim.absolute and c.last_status.get("state") == "Alarm", 3)
check("…la scheda resta ferma in allarme, tornata in G90 (niente righe dell'autofocus rimaste)",
      sim.absolute and not c.busy and not c.autofocusing, (sim.absolute, c.busy))
c.unlock()
until(lambda: c.last_status.get("state") == "Idle", 3)

res.clear()
sim.pos[2] = -100.0  # testa appoggiata sul materiale: la sonda risulta già toccata
until(lambda: c.last_status.get("pins") == "P", 3)
ok = c.autofocus(8, 30, 200, 40)
check("sonda già toccata: non parte e suggerisce $6", ok is False and res and "$6" in res[-1][1], res)
sim.pos[2] = 0.0

res.clear()
sim.surface_z = -20.0
sim.probe_wiring = "zlimit"  # come Giuseppe: sonda sul finecorsa Z (IO34)
sim.settings[21] = "1"
until(lambda: c.last_status.get("pins") is None, 3)
c.autofocus(8, 30, 200, 40)
until(lambda: res)
check("sonda sul finecorsa Z con i limiti hardware: allarme 1 spiegato («collegata al finecorsa Z»)",
      res and not res[-1][0] and "finecorsa Z" in res[-1][1], res)
check("…e nel report la scheda la vede come finecorsa Z: la finestra lo dice",
      until(lambda: c.last_status.get("pins") == "Z", 3) and "IO22" in af.pin_text(c.last_status.get("pins")),
      c.last_status.get("pins"))
c.disconnect_port()
c2 = GrblController()
res2 = []
c2.autofocus_done.connect(lambda ok, m, z: res2.append((ok, m, z)))
c2.connect_port(SIM_PORT)
until(lambda: c2.last_status.get("state") == "Idle")
c2.sim.probe_supported = False
c2.sim.surface_z = -20.0
until(lambda: c2.last_status.get("pins") is None, 3)
c2.autofocus(8, 30, 200, 40)
until(lambda: res2)
check("firmware senza G38.2: lo dice chiaramente", res2 and not res2[-1][0] and "G38.2" in res2[-1][1], res2)
until(lambda: c2.sim.absolute and not c2.busy, 3)
check("…e la scheda torna in G90", c2.sim.absolute)
c2.disconnect_port()

# profilo e finestra
prof = MachineProfile(name="Prova Z")
prof.z_motor, prof.af_probe, prof.af_distance = True, True, 8.0
from dataclasses import asdict

check("profilo: i campi dell'autofocus ci sono (8 mm di partenza)", asdict(MachineProfile())["af_distance"] == 8.0
      and "af_toward_minus" in asdict(prof))
from freelasercut.ui.dialogs_autofocus import AutofocusDialog

w.profile.z_motor = False
w.profile.af_probe = False
w.move._z_visible()
check("pannello Movimento: senza asse Z la riga Z non c'è", w.move.z_box.isHidden())
dlg = AutofocusDialog(w)
dlg.z_motor.setChecked(True)
dlg.probe.setChecked(True)
dlg.distance.setValue(8.0)
dlg.save()
dlg.close()
w.move._z_visible()
check("Laser → Asse Z e autofocus: salvati nel profilo, e nel pannello Movimento compaiono Z e Autofocus",
      w.profile.z_motor and w.profile.af_probe and abs(w.profile.af_distance - 8) < 1e-9
      and not w.move.z_box.isHidden() and not w.move.b_af.isHidden())
check("menu Laser: «Asse Z e autofocus…»", "autofocus" in w.acts)

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
