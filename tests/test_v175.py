# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.5: calibrazione della camera con i punti messi a mano.
Dopo il bersaglio inciso il riconoscimento automatico prendeva per dischi anche macchie fuori dal cartone e la
calibrazione veniva sbagliata. Ora si possono mettere i cerchietti sui dischi a mano: FreeLaserCut dice quale disco
cercare, aggancia il cerchietto al centro del disco, dopo i primi 4 trova gli altri e segnala il punto sospetto."""
import os
import sys
import tempfile
import time

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
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import camera_calib as cc
from freelasercut.camera import AutoCam, SimCamera
from freelasercut.sim import SimSerial
from freelasercut.ui.dialogs_campoints import USER, CameraPointsDialog

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def spin(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


# ---------------------------------------------------------------- foto simulata: 36 dischi + macchie estranee
sim = SimSerial()
cam = SimCamera(sim)
bx, by = cam.bed
grid = cc.seq_grid(bx, by)
check("griglia: 36 dischi, il primo vicino allo zero (riga 1, colonna 1), a serpentina",
      len(grid) == 36 and grid[0][2:] == (1, 1) and grid[5][2:] == (1, 6) and grid[6][2:] == (2, 6)
      and grid[0][0] < 20 and grid[0][1] < 20)
for x, y, _r, _c in grid:
    cv2.circle(cam.material, cam._top(x, y), int(2.0 * cam.PPM), (52, 58, 66), -1, cv2.LINE_AA)
rng = np.random.default_rng(7)
fakes = [(rng.uniform(30, bx - 30), rng.uniform(30, by - 30)) for _ in range(12)]
fakes = [f for f in fakes if min(np.hypot(f[0] - g[0], f[1] - g[1]) for g in grid) > 25][:6]
for x, y in fakes:  # macchie scure che non sono dischi (come quelle fuori dal cartone)
    cv2.circle(cam.material, cam._top(x, y), int(2.5 * cam.PPM), (40, 44, 50), -1, cv2.LINE_AA)
sim.pos = [-200.0, -200.0, 0.0] if hasattr(sim, "pos") else None
frames = []
for _ in range(3):
    f = cam._grab()
    if f is not None:
        frames.append(f)
photo = cc._avg(frames)
true = cam.true_img([g[:2] for g in grid])
fake_img = cam.true_img(fakes)
dark = cc.darkness(photo)
s = cc.snap_dark(dark, true[7][0] + 6, true[7][1] - 5, 25)
check("il cerchietto si aggancia al centro del disco (cliccato a 8 px)", s is not None and np.hypot(s[0] - true[7][0], s[1] - true[7][1]) < 1.5, s)
check("dove non c'è nessun disco non si aggancia a niente", cc.snap_dark(dark, 640, 20, 12) is None)

# riconoscimento automatico sbagliato: 4 dischi presi su macchie estranee
guess = {i: tuple(true[i]) for i in range(36)}
for k, i in enumerate((3, 14, 22, 33)):
    guess[i] = tuple(fake_img[k % len(fake_img)])
dlg = CameraPointsDialog(photo, grid, (bx, by), guess)
check("finestra: i punti trovati da soli sono arancioni, da controllare", all(k != USER for _, k in dlg.points.values())
      and len(dlg.points) == 36)
check("prima chiede gli angoli: n° 1 (zero), 6, 31 e 36", dlg.order[:4] == [0, 5, 30, 35], dlg.order[:4])
check("istruzione chiara: numero, riga, colonna, posizione sul piano",
      "n° 1" in dlg.guide.text() and "riga 1" in dlg.guide.text() and "colonna 1" in dlg.guide.text(), dlg.guide.text())
dlg.clear_auto()
check("«Togli i punti trovati da soli»: si riparte da zero", not dlg.points)
for _ in range(4):
    i = dlg.current
    dlg._clicked(true[i][0] + 5, true[i][1] - 4)
users = [i for i, (_, k) in dlg.points.items() if k == USER]
check("4 angoli messi (cliccando un po' storto): agganciati e poi tutti gli altri trovati da soli",
      sorted(users) == [0, 5, 30, 35] and len(dlg.points) == 36, (users, len(dlg.points)))
err = max(np.hypot(*(np.array(dlg.points[i][0]) - true[i])) for i in dlg.points)
bad = {i: round(float(np.hypot(*(np.array(dlg.points[i][0]) - true[i]))), 1) for i in dlg.points
       if np.hypot(*(np.array(dlg.points[i][0]) - true[i])) > 1.5}
check("tutti i cerchietti sul disco giusto (errore massimo sotto 1,5 px)", err < 1.5, f"{err:.2f} px {bad}")
check("nessun cerchietto sulle macchie estranee",
      all(min(np.hypot(*(np.array(uv) - f)) for f in fake_img) > 10 for uv, _ in dlg.points.values()))
model = dlg.compute()
pts = np.column_stack([rng.uniform(20, bx - 20, 200), rng.uniform(20, by - 20, 200)])
e = np.linalg.norm(model.img_to_bed(cam.true_img(pts)) - pts, axis=1) if model is not None else [99]
check("calibrazione con i punti a mano: precisa (errore vero sotto 0,6 mm)", model is not None and max(e) < 0.6,
      f"max {max(e):.2f} mm, rms dichiarato {model.rms_mm if model else 0:.2f}")
check("…e la finestra si chiude con «Calcola e usa»", dlg.result() == 1)

# un cerchietto sul disco sbagliato: la finestra lo segnala invece di calibrare male
dlg2 = CameraPointsDialog(photo, grid, (bx, by), {i: tuple(true[i]) for i in range(36)})
dlg2.points[20] = (tuple(fake_img[0]), USER)
dlg2.points[9] = (tuple(true[10]), USER)  # il disco accanto
m2 = dlg2.compute()
check("cerchietto messo sul disco sbagliato: niente calibrazione, il sospetto è indicato",
      m2 is None and dlg2.current in (20, 9) and "sbagliato" in dlg2.result_lbl.text(), (dlg2.current, dlg2.result_lbl.text()))
dlg2.remove(dlg2.current)
dlg2.remove(20 if dlg2.current != 20 else 9)
m3 = dlg2.compute()
check("tolti i due sbagliati (tasto destro): la calibrazione riesce", m3 is not None, dlg2.result_lbl.text())
dlg3 = CameraPointsDialog(photo, grid, (bx, by), {})
dlg3.skip()
check("«Questo disco non si vede»: passa al disco successivo da cercare", dlg3.current == 5 and 0 in dlg3.skipped)
check("con meno di 9 punti non si può calcolare", not dlg3.b_ok.isEnabled())
sim.close()

# ---------------------------------------------------------------- foto dalla macchina (simulatore) e pannello
from freelasercut.grbl import SIM_PORT, GrblController
from freelasercut.profile import MachineProfile

c = GrblController()
c.connect_port(SIM_PORT)
spin(2.0)
c.home()
spin(1.5)
c.sim.speedup = 40
cam2 = SimCamera(c.sim)
spin(0.5)
ac = AutoCam(c, cam2, MachineProfile(), method="photo")
ac.park_hint = (430.0, 425.0)
got, res = [], {}
ac.photo_ready.connect(got.append)
ac.finished.connect(lambda m, msg: res.update(msg=msg))
ac.start()
t = time.time()
while "msg" not in res and time.time() - t < 60:
    spin(0.1)
check("«Metti i punti a mano»: la testa va al parcheggio, la camera fa la foto (laser spento)",
      got and ac.last_photo is not None and ac.park == (430.0, 425.0) and len(ac.target_grid) == 36
      and not c.sim.burn_marks, res)

from freelasercut.ui.main_window import MainWindow

w = MainWindow()
panel = w.camera


class FakeAC:
    last_photo = photo
    guess = {i: tuple(true[i]) for i in range(36)}
    park = (430.0, 425.0)
    method = "photo"


def run_dialog(self):
    for i in list(self.points):
        if i in (3, 14):
            self.points[i] = (tuple(fake_img[0]), self.points[i][1])  # due presi sulle macchie
    self.remove(3)
    self.remove(14)
    self.compute()
    return self.result()


CameraPointsDialog.exec = run_dialog
m = panel.open_points(FakeAC())
from freelasercut.camera import camera_file
import json

saved = json.load(open(camera_file(), encoding="utf-8")) if os.path.exists(camera_file()) else {}
check("pannello Camera: calibrazione dai punti a mano salvata, con il parcheggio per la prossima volta",
      m is not None and saved.get("method") == "punti a mano" and saved.get("park") == [430.0, 425.0]
      and panel.model is not None, saved.get("method"))
check("pulsante «Metti i punti a mano sui dischi incisi…» nel pannello Camera", hasattr(panel, "btn_manual"))
c.disconnect_port()

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
os._exit(code)
