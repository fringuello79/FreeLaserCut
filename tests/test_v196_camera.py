# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.19.6: telecamera sulla testa del laser.

- Conti (core/headcam.py): calibrazione credibile o no, conversioni pixel ↔ macchina, scala ai minimi quadrati,
  offset dal segno, G-code del segno, segno trovato nell'immagine, video raddrizzato, tavola da 2 angoli, spigolo.
- Calibrazione sul simulatore con una camera di testa simulata (posizione, scala, rotazione e specchio veri noti):
  la prima volta con il clic sul segno, poi da sola; annullata; macchina staccata; testa sul bordo.
- Nella finestra: riquadro «Camera della testa», profilo salvato per nome, camera del piano che non la mostra,
  mirino sul piano, Laser sul mirino / Mirino sul laser / Origine al mirino, clic sul video, tasto destro, tavola.
Uso: python tests/test_v196_camera.py [banco]
"""
import json
import math
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
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import cv2
import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

import freelasercut
from freelasercut.core import headcam as H
from freelasercut.grbl import SIM_PORT, GrblController
from freelasercut.headcam_cal import HeadCamCalibration, SimHeadCamera
from freelasercut.profile import MachineProfile
from freelasercut.updater import parse_version

UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def until(cond, t=10.0):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


def rotA(scale, deg, mirror=False):
    a = math.radians(deg)
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return scale * R @ (np.diag([1.0, -1.0]) if mirror else np.eye(2))


check("versione 0.19.6 o successiva", parse_version(freelasercut.__version__) >= (0, 19, 6), freelasercut.__version__)

# ================================================================ conti
cal = H.HeadCal(rotA(0.05, 20), np.array([3.0, 35.0]), (1280, 720))
check("calibrazione credibile: nessun problema", cal.problem() is None)
check("da file e ritorno: identica", H.HeadCal.from_dict(json.loads(json.dumps(cal.to_dict()))).to_dict() == cal.to_dict())
for name, d in (("scala troppo piccola", {"A": rotA(0.0005, 0).tolist(), "offset": [0, 30]}),
                ("scala troppo grande", {"A": rotA(5.0, 0).tolist(), "offset": [0, 30]}),
                ("offset oltre 500 mm", {"A": rotA(0.05, 0).tolist(), "offset": [600, 0]}),
                ("matrice nulla", {"A": [[0, 0], [0, 0]], "offset": [0, 30]}),
                ("numeri non validi", {"A": [["x", 0], [0, 1]], "offset": [0, 30]}),
                ("valori infiniti", {"A": [[float("inf"), 0], [0, 0.05]], "offset": [0, 30]}),
                ("manca l'offset", {"A": rotA(0.05, 0).tolist()}), ("vuota", {}), ("non un dizionario", [1, 2])):
    check(f"calibrazione rifiutata: {name}", H.HeadCal.from_dict(d) is None)
M = np.array([120.0, 80.0])
rng = np.random.default_rng(5)
ok = True
for _ in range(50):
    px = rng.uniform([0, 0], [1280, 720])
    if np.abs(cal.machine_to_px(M, cal.px_to_machine(M, px)) - px).max() > 1e-9:
        ok = False
check("pixel → macchina → pixel: identico (50 punti)", ok)
check("il centro dell'immagine è il mirino: M + O", np.allclose(cal.px_to_machine(M, cal.center()), M + cal.offset))
check("testa per il mirino su T e mirino con la testa lì: inversi", np.allclose(cal.crosshair(cal.head_for_crosshair(M)), M))
A_true = rotA(0.04, -73, mirror=True)
moves = [(2, 0), (-2, 0), (0, 2), (0, -2), (1.5, 1)]
shifts = [-np.linalg.solve(A_true, np.array(d, float)) for d in moves]
A_fit, res = H.fit_A(moves, shifts)
check("scala ai minimi quadrati: ritrova A (anche specchiata e ruotata), scarto zero",
      A_fit is not None and np.allclose(A_fit, A_true, atol=1e-12) and res < 1e-9)
noisy = [s + rng.normal(0, 0.2, 2) for s in shifts]
A_n, res_n = H.fit_A(moves, noisy)
check("…con 0,2 pixel di rumore: errore sotto l'1% e scarto piccolo",
      np.abs(A_n - A_true).max() / 0.04 < 0.01 and res_n < 0.02, (np.abs(A_n - A_true).max() / 0.04, res_n))
check("spostamenti tutti nella stessa direzione: non basta (None)", H.fit_A([(1, 0), (2, 0)], [(-25, 0), (-50, 0)])[0] is None)
check("un solo spostamento: non basta", H.fit_A([(1, 0)], [(-25, 0)])[0] is None)
P = np.array([200.0, 150.0])
true_cal = H.HeadCal(A_true, np.array([4.0, 36.5]), (640, 360))
ok = True
for Mh in (np.array([196.0, 113.5]), np.array([193.2, 115.9]), np.array([197.5, 111.0])):  # segno al centro e fuori
    m = true_cal.machine_to_px(Mh, P)
    ok = ok and np.allclose(H.offset_from_mark(P, Mh, m, A_true, (640, 360)), [4.0, 36.5])
check("offset dal segno: P − M − A·(m − c) ritrova l'offset vero, con il segno al centro e lontano dal centro", ok)
g = H.mark_gcode(10.0, 20.0, 300)
mv = [ln for ln in g if ln.startswith(("G0", "G1"))]
xs = [float(t[1:]) for ln in mv for t in ln.split() if t.startswith("X")]
ys = [float(t[1:]) for ln in mv for t in ln.split() if t.startswith("Y")]
check("G-code del segno: solo tratti dritti (niente archi), laser in M4 e spento alla fine",
      not any(ln.startswith(("G2", "G3")) for ln in g) and "M4 S0" in g and g[-2] == "M5 S0" and g[-1].startswith("G0 X10.000"))
check("…disco di 1,6 mm centrato sul punto (estremi simmetrici)", abs((max(xs) + min(xs)) / 2 - 10) < 1e-9
      and abs((max(ys) + min(ys)) / 2 - 20) < 0.02 and abs(max(xs) - min(xs) - 1.6) < 1e-6, (min(xs), max(xs)))


def wood(w=640, h=360, seed=1):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = 180 + 14 * np.sin(0.05 * xx + 0.3 * np.sin(0.01 * yy)) + np.random.default_rng(seed).normal(0, 2, (h, w))
    return img


img = wood()
cv2.circle(img, (301, 187), 16, 40.0, -1, cv2.LINE_AA)
cv2.line(img, (50, 40), (600, 60), 120.0, 2)  # una venatura scura e lunga
frame = cv2.merge([np.clip(img, 0, 255).astype(np.uint8)] * 3)
pt, area = H.detect_mark(frame, (290, 180), 90)
check("segno trovato nell'immagine: centro entro 0,3 pixel", pt is not None and math.dist(pt, (301, 187)) < 0.3, pt)
pt2, _ = H.detect_mark(frame, (320, 50), 60)
check("una venatura lunga non è un segno", pt2 is None, pt2)
check("nessuna immagine: niente", H.detect_mark(None, (0, 0), 50)[0] is None)
before = cv2.merge([np.clip(wood(seed=4), 0, 255).astype(np.uint8)] * 3)
after = before.copy()
cv2.circle(after, (120, 250), 14, (40, 40, 40), -1, cv2.LINE_AA)
pt3, _ = H.detect_new_mark([before], [after])
check("segno nuovo dalla differenza prima/dopo", pt3 is not None and math.dist(pt3, (120, 250)) < 0.5, pt3)
check("…senza differenza: niente", H.detect_new_mark([before], [before.copy()])[0] is None)
bad = 0
for t in range(200):
    A = rotA(rng.uniform(0.01, 0.2), rng.uniform(0, 360), rng.random() < 0.5)
    k, flip = H.view_orientation(A)
    raw = (rng.integers(40, 900), rng.integers(30, 700))
    for _ in range(3):
        p0 = (int(rng.integers(0, raw[0])), int(rng.integers(0, raw[1])))
        im = np.zeros((raw[1], raw[0]), np.uint8)
        im[p0[1], p0[0]] = 255
        sh = H.orient_frame(im, k, flip)
        vv, uu = np.nonzero(sh)
        if H.raw_to_shown(p0, raw, k, flip) != (float(uu[0]), float(vv[0])):
            bad += 1
        if tuple(round(c) for c in H.shown_to_raw((uu[0], vv[0]), raw, k, flip)) != p0:
            bad += 1
    a, b, c = (np.array(H.shown_to_raw(q, raw, k, flip)) for q in ((5, 5), (6, 5), (5, 6)))
    dx, dy = A @ (b - a), A @ (c - a)
    if not (dx[0] > 0 and abs(math.atan2(dx[1], dx[0])) <= math.pi / 4 + 1e-9 and dy[1] < 0):
        bad += 1
check("video raddrizzato: 200 camere a caso, destra = +X e su = +Y, pixel avanti e indietro esatti", bad == 0, bad)
check("righello: misure tonde", H.nice_ruler(0.05, 100) == 5 and H.nice_ruler(0.01, 160) == 1 and H.nice_ruler(0.2, 50) == 10)
b = H.board_from_corners((10, 20), (310, 20), 100)
check("tavola da due spigoli in basso: 300 × 100 mm, dritta, sopra il lato", b is not None and abs(b["width"] - 300) < 1e-9
      and abs(b["angle"]) < 1e-9 and b["corners"][2] == (310.0, 120.0), b)
b2 = H.board_from_corners((0, 0), (100 * math.cos(math.radians(3)), 100 * math.sin(math.radians(3))), 50)
check("tavola storta di 3°: angolo e misure", abs(b2["angle"] - 3) < 1e-9 and abs(b2["width"] - 100) < 1e-9)
check("spigoli uguali o profondità nulla: niente tavola", H.board_from_corners((5, 5), (5.5, 5), 50) is None
      and H.board_from_corners((0, 0), (100, 0), 0) is None)
yy, xx = np.mgrid[0:360, 0:640]
bimg = np.where((xx >= 330) & (yy <= 170), 200, 60).astype(np.uint8)  # tavola chiara in alto a destra, angolo (330, 170)
cpt, conf = H.find_corner(cv2.merge([bimg] * 3), (320, 180), 90)
check("spigolo della tavola trovato nell'immagine entro 2 pixel", cpt is not None and math.dist(cpt, (330, 170)) < 2.0
      and conf > 0.4, (cpt, conf))
check("…su un'immagine uniforme: niente", H.find_corner(np.full((360, 640, 3), 120, np.uint8), (320, 180), 90)[0] is None)
d = MachineProfile().__dict__.copy()
check("profilo nuovo: nessuna camera della testa", d["head_cam_name"] == "" and d["head_cam_index"] == -1
      and d["head_cam_cal"] == {})
tmp = os.path.join(tempfile.mkdtemp(), "vecchio.json")
old = {k: v for k, v in MachineProfile().file_dict().items() if not k.startswith("head_cam")}
json.dump(old, open(tmp, "w"))
pl = MachineProfile.load(tmp)
check("profilo salvato prima della 0.19.6: si apre, nessuna camera della testa", pl.head_cam_name == "" and pl.head_cam_cal == {})

# ================================================================ calibrazione sul simulatore
c = GrblController()
c.connect_port(SIM_PORT)
until(lambda: c.connected and c.board_settings, 8)
c.sim.speedup = 4
c.home()
until(lambda: c.homed, 15)
spin(0.5)
prof = MachineProfile()


def mpos():
    return np.array(c.last_status["MPos"][:2], float)


def go(x, y):
    c.goto_machine(x, y, 6000)
    spin(0.3)
    until(lambda: c.last_status.get("state") == "Idle" and np.allclose(mpos(), (x, y), atol=1e-3), 20)
    spin(0.3)


def run_cal(cam, prior=None, click_err=(4, -3), power=30, cancel_at=None):
    cal_ = HeadCamCalibration(c, cam, prof, prior=prior, power=power)
    res = {}
    true = cam.true_cal() if hasattr(cam, "true_cal") else None

    def need(_msg):
        Mm = np.array(cal_.mark_at, float)  # il segno è dove era la testa quando è stato inciso
        tgt = true.head_for_crosshair(Mm) + np.array([1.2, -0.7])
        go(*tgt)
        px = true.machine_to_px(mpos(), Mm)
        cal_.click(px + np.array(click_err))

    cal_.need_click.connect(need)
    cal_.finished.connect(lambda r, msg: res.update(r=r, m=msg))
    if cancel_at:
        cal_.progress.connect(lambda t: cal_.cancel() if cancel_at in t else None)
    cal_.start()
    until(lambda: "m" in res, 240)
    return res.get("r"), res.get("m", "tempo scaduto"), cal_


for n, (label, kw) in enumerate((("camera dritta, 0,05 mm/pixel", dict(scale=0.05, angle=0)),
                                 ("camera ruotata di 95° e specchiata, 0,03 mm/pixel", dict(scale=0.03, angle=95, mirror=True)),
                                 ("camera ruotata di −170°, 0,12 mm/pixel", dict(scale=0.12, angle=-170)))):
    go(200 - 30 * n, 150)  # ogni prova incide in un punto nuovo
    cam = SimHeadCamera(c.sim, offset=(4.0, 36.5), **kw)
    spin(0.5)
    true = cam.true_cal()
    r, msg, run1 = run_cal(cam)
    e = np.inf if r is None else float(np.hypot(*(r.offset - true.offset)))
    check(f"calibrazione ({label}), la prima volta con il clic: offset entro 0,05 mm", e <= 0.05, f"{e:.4f} · {msg}")
    check("…scala, rotazione e specchio giusti (A entro l'1%) e verifica entro 2,5 pixel",
          r is not None and np.abs(r.A - true.A).max() / true.scale < 0.01 and r.extra.get("verify_px", 9) <= 2.5,
          None if r is None else (np.abs(r.A - true.A).max() / true.scale, r.extra))
    go(150 - 30 * n, 120)
    r2, msg2, run2 = run_cal(cam, prior=r)
    e2 = np.inf if r2 is None else float(np.hypot(*(r2.offset - true.offset)))
    check("…la seconda volta da sola (foto prima/dopo, nessun clic): offset entro 0,05 mm",
          e2 <= 0.05 and not any("clic" in ln for ln in run2.log), f"{e2:.4f} · {msg2}")
    cam.close()
go(250, 200)
cam = SimHeadCamera(c.sim, offset=(4.0, 36.5))
spin(0.3)
r, msg, run3 = run_cal(cam, cancel_at="Incido")
spin(0.5)
check("Annulla durante l'incisione: nessuna calibrazione, laser spento", r is None and "annullata" in msg
      and c.sim.power == 0, (msg, c.sim.power))
go(prof.bed_x - 1.0, 150)
r, msg, _ = run_cal(cam, prior=H.HeadCal(cam.true_cal().A, cam.true_cal().offset + np.array([5.0, 0]), cam.size))
check("testa sul bordo: lo spostamento uscirebbe dal piano, si ferma e lo dice", r is None and "area di lavoro" in msg, msg)


class Mute:
    size = (640, 360)

    def frames(self, n=2, after=0.0):
        return []

    def get(self, after=0.0, timeout=0.0):
        return None


go(250, 250)
r, msg, _ = run_cal(Mute())
check("camera che non manda immagini: si ferma e lo dice", r is None and "immagini" in msg, msg)
cam.close()
c.disconnect_port()
spin(0.5)
r, msg, _ = run_cal(SimHeadCamera(c.sim))
check("macchina staccata: niente calibrazione, lo dice", r is None and "disconnessa" in msg, msg)

# ================================================================ nella finestra
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1500, 950)
w.show()
spin(0.8)
cp = w.camera
hp = cp.head
check("riquadro «Camera della testa» nel pannello Camera, sotto la camera del piano", hp is not None
      and hp.parent() is not None and hp.combo.itemData(0) is None)
check("senza camera: comandi spenti e invito a sceglierla", not hp.b_cal.isEnabled() and not hp.b_laser.isEnabled()
      and "Scegli" in hp.state.text(), hp.state.text())
# camera del piano e camera della testa: il nome decide
from freelasercut import camera as camera_mod  # noqa: E402

camera_mod.NAMES.clear()
camera_mod.NAMES.update({0: "USB Camera piano", 1: "Innomaker-U20CAM-1080p-S1"})
w.profile.head_cam_name = "Innomaker-U20CAM-1080p-S1"
w.profile.head_cam_index = 0  # numero vecchio: conta il nome
check("camera della testa ritrovata per nome anche se il numero è cambiato", hp.wanted_index() == 1, hp.wanted_index())
fake = [(0, "USB Camera piano · 1920×1080", (1920, 1080), np.zeros((90, 160, 3), np.uint8)),
        (1, "Innomaker · 1920×1080", (1920, 1080), np.zeros((90, 160, 3), np.uint8))]
opened = []
hp._open = lambda idx: opened.append(idx)  # niente camere vere qui
cp.on_select = lambda *_: None
cp.on_found(fake)
plate_items = [cp.combo.itemData(i) for i in range(cp.combo.count())]
head_items = [hp.combo.itemData(i) for i in range(hp.combo.count())]
check("la camera della testa non compare nell'elenco della camera del piano", 1 not in plate_items and 0 in plate_items,
      plate_items)
check("…e compare nel suo riquadro, scelta da sola", 1 in head_items and hp.combo.currentData() == 1 and opened == [1],
      (head_items, opened))
del hp._open
camera_mod.NAMES.clear()
w.profile.head_cam_name, w.profile.head_cam_index = "", -1
# con il simulatore
w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.connected and w.ctl.board_settings, 8)
w.ctl.sim.speedup = 4
w.ctl.home()
until(lambda: w.ctl.homed, 15)
spin(0.5)
c = w.ctl
hp.set_cameras([], None)
from freelasercut.ui.headcam_panel import SIM_HEAD  # noqa: E402

check("con il simulatore c'è la camera della testa simulata", hp.combo.findData(SIM_HEAD) > 0)
hp.combo.setCurrentIndex(hp.combo.findData(SIM_HEAD))
hp._picked(0)
spin(0.5)
check("aperta: si può calibrare, ma i comandi del mirino aspettano la calibrazione",
      hp.src is not None and hp.b_cal.isEnabled() and not hp.b_laser.isEnabled() and "calibrare" in hp.state.text(),
      hp.state.text())
if UI == "banco":
    w.banco.officina_show("camera")  # nel Banco il pannello Camera si apre dall'Officina
    spin(0.3)
check("il video arriva nel riquadro (con il pannello in vista)", until(lambda: hp.video.img is not None, 3))
w.goto_bed(*prof.to_bed(300, 300))
until(lambda: c.last_status.get("state") == "Idle", 10)
spin(0.5)
true = hp.src.true_cal()
calib = hp.start_calibration(30)


def need_ui(_msg):
    Mm = np.array(calib.mark_at, float)
    tgt = true.head_for_crosshair(Mm) + np.array([0.8, 0.5])
    c.goto_machine(*tgt, 6000)
    until(lambda: np.allclose(np.array(c.last_status["MPos"][:2], float), tgt, atol=1e-3)
          and c.last_status.get("state") == "Idle", 15)
    spin(0.4)
    px = true.machine_to_px(np.array(c.last_status["MPos"][:2], float), Mm)
    hp.video.clicked.emit(float(px[0]) + 3, float(px[1]) - 2)  # il clic della persona sul video


calib.need_click.connect(need_ui)
check("durante la calibrazione: Annulla al posto di Calibra", hp.b_stop.isVisibleTo(hp) and not hp.b_cal.isVisibleTo(hp))
until(lambda: hp.calib is None, 240)
cal = hp.usable_cal()
e = np.inf if cal is None else float(np.hypot(*(cal.offset - true.offset)))
check("calibrazione dalla finestra: offset entro 0,05 mm, salvata nel profilo", e <= 0.05
      and w.profile.head_cam_cal.get("offset") is not None, f"{e} · {hp.state.text()}")
saved = json.load(open(w.profile.path(), encoding="utf-8"))
check("…anche nel file del profilo", H.HeadCal.from_dict(saved.get("head_cam_cal")) is not None)
check("…stato «Calibrata» e comandi del mirino accesi", "Calibrata" in hp.state.text() or "calibrata" in hp.state.text()
      and hp.b_laser.isEnabled(), hp.state.text())
hp.update_state()
check("…comandi accesi", hp.b_laser.isEnabled() and hp.b_cross.isEnabled() and hp.b_origin.isEnabled())
spin(0.5)
Mm = np.array(c.last_status["MPos"][:2], float)
cross = w.canvas.cam_cross_pos()
exp = prof.to_bed(*(Mm + cal.offset))
check("sul piano il mirino si vede dove guarda la camera", cross is not None and math.dist((cross.x(), cross.y()), exp) < 0.01,
      (cross, exp))
hp.chk_bed.setChecked(False)
check("…e si nasconde con la spunta", w.canvas.cam_cross_pos() is None)
hp.chk_bed.setChecked(True)
hp.laser_to_crosshair()
check("Laser sul mirino: la testa va di +offset", until(lambda: np.allclose(np.array(c.last_status["MPos"][:2], float),
                                                                          Mm + cal.offset, atol=1e-3)
                                                     and c.last_status.get("state") == "Idle", 15))
hp.crosshair_to_laser()
check("Mirino sul laser: torna di −offset", until(lambda: np.allclose(np.array(c.last_status["MPos"][:2], float), Mm, atol=1e-3)
                                                  and c.last_status.get("state") == "Idle", 15))
spin(0.3)
hp.origin_at_crosshair()
spin(0.6)
hp.laser_to_crosshair()
until(lambda: c.last_status.get("state") == "Idle" and np.allclose(np.array(c.last_status["MPos"][:2], float),
                                                                   Mm + cal.offset, atol=1e-3), 15)
spin(0.5)
wp = c.last_status.get("WPos", [9, 9])
check("Origine al mirino: il punto sotto il mirino è X0 Y0 (senza muovere la testa)", abs(wp[0]) < 0.01 and abs(wp[1]) < 0.01, wp)
c.send_line("G10 L20 P1 X0 Y0")
spin(0.3)
hp.crosshair_to_laser()
until(lambda: c.last_status.get("state") == "Idle", 10)
spin(0.4)
Mm = np.array(c.last_status["MPos"][:2], float)
size = hp.src.size
px = (size[0] * 0.8, size[1] * 0.3)
T = cal.px_to_machine(Mm, px, size)
hp._video_clicked(*px)
check("clic sul video: quel punto va sotto il mirino", until(lambda: np.allclose(np.array(c.last_status["MPos"][:2], float),
                                                                              cal.head_for_crosshair(T), atol=1e-3)
                                                          and c.last_status.get("state") == "Idle", 15))
msgs = []
w.statusBar().messageChanged.connect(lambda t: msgs.append(t))
far = np.array(prof.to_machine(prof.bed_x - 0.5, 5.0), float)
moved = hp.move_head_machine(far + np.array([30.0, 0.0]) if prof.to_bed(*(far + [30, 0]))[0] > prof.bed_x
                             else far - np.array([30.0, 0.0]), "prova")
check("spostamento fuori dal piano: rifiutato con il motivo (non tagliato al bordo)", moved is False
      and any("fuori dall'area" in m for m in msgs), msgs[-1:] if msgs else None)
keys = w.context_menu_keys(None)
check("tasto destro sul piano (macchina connessa): Porta il laser qui e Porta il mirino qui",
      "laser_here" in keys and "cam_here" in keys, keys)
w.canvas.cursor_bed = QPointF(150.0, 160.0)
w.acts["cam_here"].trigger()
Tm = np.array(prof.to_machine(150.0, 160.0), float)
check("…Porta il mirino qui: la testa va dove il mirino guarda quel punto",
      until(lambda: np.allclose(np.array(c.last_status["MPos"][:2], float), cal.head_for_crosshair(Tm), atol=1e-3), 15))
until(lambda: c.last_status.get("state") == "Idle", 10)
w.acts["laser_here"].trigger()
check("…Porta il laser qui", until(lambda: np.allclose(np.array(c.last_status["MPos"][:2], float), Tm, atol=1e-3), 15))
until(lambda: c.last_status.get("state") == "Idle", 10)
# tavola da 2 angoli
dlg = hp.board_dialog()
dlg.height_mm.setValue(120)
dlg.mark(0, (100.0, 50.0))
dlg.mark(1, (100.0 + 250 * math.cos(math.radians(2)), 50.0 + 250 * math.sin(math.radians(2))))
check("tavola: 250 × 120 mm, storta di 2°", dlg.board is not None and abs(dlg.board["width"] - 250) < 1e-6
      and abs(dlg.board["angle"] - 2) < 1e-6 and "250.0" in dlg.result.text(), dlg.result.text())
n0 = len(w.editor.doc.shapes)
outline = dlg.draw_outline()
from freelasercut.ui.editor import TOOL_LAYER  # noqa: E402

check("contorno della tavola sul livello strumenti (non si incide)", outline is not None and outline.layer == TOOL_LAYER
      and len(w.editor.doc.shapes) == n0 + 1)
from freelasercut.core.document import RectShape  # noqa: E402

R = RectShape(40, 20)
w.editor.add([R], "prova")
w.editor.select([R, outline])
dlg.rotate_selection()
check("Ruota la selezione come la tavola: il disegno gira di 2°, il contorno no",
      abs(math.degrees(math.atan2(R.tf.m12(), R.tf.m11())) - 2) < 1e-6 and outline.tf.isIdentity())
# spigolo trovato da solo: tavola chiara simulata
hp.src.close()
corner_m = np.array(prof.to_machine(120.0, 90.0), float)
board = np.array([corner_m, corner_m + [300, 0], corner_m + [300, 200], corner_m + [0, 200]])
hp.src = SimHeadCamera(c.sim, board=board)
spin(0.5)
ok_move = hp.crosshair_to_bed(121.5, 91.0)
Tb = cal.head_for_crosshair(np.array(prof.to_machine(121.5, 91.0), float))
check("il mirino va vicino allo spigolo della tavola", ok_move and until(
    lambda: np.allclose(np.array(c.last_status["MPos"][:2], float), Tb, atol=1e-3) and c.last_status.get("state") == "Idle", 20))
spin(0.6)
dlg.auto.setChecked(True)
dlg.mark(0)
p0 = dlg.pts[0]
check("«Trova lo spigolo da solo»: spigolo della tavola entro 0,2 mm (il mirino era a 1,8 mm)",
      p0 is not None and math.dist(p0, (120.0, 90.0)) < 0.2 and "trovato" in dlg.lab[0].text(), (p0, dlg.lab[0].text()))
dlg.close()
c.disconnect_port()
spin(0.5)
hp.update_state()
check("macchina staccata: comandi del mirino spenti", not hp.b_laser.isEnabled() and not hp.b_cal.isEnabled())

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
