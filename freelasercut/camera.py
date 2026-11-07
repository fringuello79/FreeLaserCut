# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Telecamera del piano: ricerca automatica, acquisizione e calibrazione "AutoCam".

AutoCam, in due varianti, scelte in automatico:
  A) Puntino laser: la testa visita una griglia di punti e in ognuno accende il
     laser all'1–3% per un istante; la camera misura il puntino (differenza
     acceso/spento). Non incide nulla.
  B) Bersaglio inciso (ripiego se il puntino non si vede): la macchina incide
     piccoli cerchi su un cartone; la camera li trova confrontando la foto
     prima/dopo. La testa viene "cancellata" dalle foto facendo la mediana di
     più scatti con la testa in punti diversi, e la stessa tecnica dà la stima
     iniziale di dove guardare.
"""
import math
import os
import sys
import threading
import time
from freelasercut.i18n import tr  # noqa: E402

os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")  # niente messaggi mentre si sondano le porte camera
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")
import cv2  # noqa: E402
import numpy as np
from PySide6.QtCore import QObject, Signal

from . import camera_calib as cc
from .profile import config_dir

SIM_CAMERA = -1
CAMERA_FILE = "camera.json"


def camera_file():
    return os.path.join(config_dir(), CAMERA_FILE)


def _backend():
    return cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY


def list_cameras(max_index=6, skip=()):
    """[(indice, etichetta, (w, h), miniatura_bgr)] delle camere che danno immagini.
    `skip`: indici già aperti da FreeLaserCut (non vanno riaperti)."""
    found = []
    for i in range(max_index):
        if i in skip:
            continue
        cap = cv2.VideoCapture(i, _backend())
        if not cap.isOpened():
            cap.release()
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        frame = None
        for _ in range(8):
            ok, f = cap.read()
            if ok and f is not None:
                frame = f
        cap.release()
        if frame is None:
            continue
        h, w = frame.shape[:2]
        found.append((i, tr("Camera {0}  ·  {1}×{2}", i, w, h), (w, h), cv2.resize(frame, (160, 90))))
    return found


# ======================================================================= sorgenti
class _FrameSource:
    """Base: un thread legge di continuo e tiene l'ultimo fotogramma con il suo orario."""

    def __init__(self):
        self._lock = threading.Condition()
        self._frame = None
        self._t = 0.0
        self._running = True
        self.size = (0, 0)
        threading.Thread(target=self._loop, daemon=True).start()

    def _grab(self):  # pragma: no cover - implementato dalle sottoclassi
        raise NotImplementedError

    def _loop(self):
        while self._running:
            f = self._grab()
            if f is None:
                time.sleep(0.05)
                continue
            with self._lock:
                self._frame = f
                self._t = time.time()
                self.size = (f.shape[1], f.shape[0])
                self._lock.notify_all()

    def get(self, after=0.0, timeout=4.0):
        end = time.time() + timeout
        with self._lock:
            while self._running and (self._frame is None or self._t <= after):
                left = end - time.time()
                if left <= 0:
                    return None
                self._lock.wait(left)
            return None if self._frame is None else self._frame.copy()

    def frames(self, n=3, after=0.0):
        out, t = [], after
        while len(out) < n:
            f = self.get(after=t)
            if f is None:
                break
            out.append(f)
            with self._lock:
                t = self._t
        return out

    def close(self):
        self._running = False
        with self._lock:
            self._lock.notify_all()


class CameraSource(_FrameSource):
    def __init__(self, index, width=1920, height=1080):
        self.index = index
        self.cap = cv2.VideoCapture(index, _backend())
        if not self.cap.isOpened():
            raise RuntimeError(tr("camera {0} non disponibile", index))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        super().__init__()

    def _grab(self):
        ok, f = self.cap.read()
        return f if ok else None

    def close(self):
        super().close()
        time.sleep(0.1)
        self.cap.release()


class SimCamera(_FrameSource):
    """Camera virtuale che inquadra il simulatore con prospettiva e lente "fish-eye" note.
    Serve a provare (e collaudare) AutoCam senza hardware."""

    PPM = 2.0
    W, H = 1280, 720

    def __init__(self, sim, occlude=False, k=0.10, seed=1, view=1.0, gantry=False):
        """view > 1: camera montata bassa, vede solo la parte centrale del piano."""
        self.index = SIM_CAMERA
        self.gantry = gantry
        self.sim = sim
        self.occlude = occlude
        self.k = k
        self.rng = np.random.default_rng(seed)
        bx, by = float(sim.settings[130]), float(sim.settings[131])
        self.bed = (bx, by)
        self.tw, self.th = int(bx * self.PPM), int(by * self.PPM)
        src = np.float32([[0, self.th], [self.tw, self.th], [self.tw, 0], [0, 0]])  # (0,0) (X,0) (X,Y) (0,Y)
        dst = np.float32([[250, 690], [1040, 676], [935, 88], [322, 104]])
        dst = (dst - np.float32([640, 390])) * view + np.float32([640, 390])
        self.Hpx = cv2.getPerspectiveTransform(src, dst)
        self.c = np.array([self.W / 2, self.H / 2])
        self.f = math.hypot(self.W / 2, self.H / 2)
        jj, ii = np.meshgrid(np.arange(self.W, dtype=np.float32), np.arange(self.H, dtype=np.float32))
        xd, yd = (jj - self.c[0]) / self.f, (ii - self.c[1]) / self.f
        g = 1 + self.k * (xd * xd + yd * yd)
        ux, uy = self.c[0] + xd * g * self.f, self.c[1] + yd * g * self.f
        # da pixel camera "senza lente" a pixel della vista dall'alto
        pts = np.stack([ux.ravel(), uy.ravel()], axis=1).reshape(-1, 1, 2).astype(np.float64)
        top = cv2.perspectiveTransform(pts, np.linalg.inv(self.Hpx)).reshape(self.H, self.W, 2)
        self.mx = top[..., 0].astype(np.float32)
        self.my = top[..., 1].astype(np.float32)
        base = np.full((self.th, self.tw, 3), (176, 196, 214), np.uint8)  # cartone chiaro (BGR)
        for y in range(0, self.th, 18):
            cv2.line(base, (0, y), (self.tw, y + 6), (168, 188, 206), 1)
        self.material = base
        self._marks_done = 0
        super().__init__()

    def _top(self, x, y):
        return int(round(x * self.PPM)), int(round(self.th - y * self.PPM))

    def true_img(self, bed_pts):
        """Posizione vera in pixel di punti del piano (per misurare l'errore nei test)."""
        bed_pts = np.atleast_2d(np.asarray(bed_pts, float))
        top = np.stack([bed_pts[:, 0] * self.PPM, self.th - bed_pts[:, 1] * self.PPM], axis=1)
        u = cv2.perspectiveTransform(top.reshape(-1, 1, 2), self.Hpx).reshape(-1, 2)
        xu = (u - self.c) / self.f
        xd = xu.copy()
        for _ in range(30):
            xd = xu / (1 + self.k * (xd ** 2).sum(axis=1, keepdims=True))
        return self.c + xd * self.f

    def _grab(self):
        time.sleep(1 / 15)
        sim = self.sim
        if not sim.is_open:
            return None
        marks = sim.burn_marks
        while self._marks_done < len(marks):
            x, y = sim.to_bed(*marks[self._marks_done])
            cv2.circle(self.material, self._top(x, y), int(0.45 * self.PPM) + 1, (52, 58, 66), -1, cv2.LINE_AA)
            self._marks_done += 1
        img = self.material.copy()
        x, y = sim.to_bed(sim.pos[0], sim.pos[1])
        firing = sim.state == "Run" and sim.power > 0
        # testa: il corpo sta più in alto del piano, quindi dalla camera appare spostato
        off = 0 if self.occlude else 38
        hx0, hy0 = self._top(x - 22, y + off + 30)
        hx1, hy1 = self._top(x + 22, y + off - 18)
        if firing:
            cx, cy = self._top(x, y)
            glow = np.zeros_like(img)
            cv2.circle(glow, (cx, cy), 9, (255, 190, 90), -1, cv2.LINE_AA)
            glow = cv2.GaussianBlur(glow, (0, 0), 3)
            img = cv2.add(img, glow)
            cv2.circle(img, (cx, cy), 2, (255, 240, 220), -1, cv2.LINE_AA)
        if self.gantry:  # trave dell'asse X: attraversa tutto il piano e si muove con la testa
            gx0, gy0 = self._top(-20, y + off + 14)
            gx1, gy1 = self._top(self.bed[0] + 20, y + off - 10)
            cv2.rectangle(img, (gx0, gy0), (gx1, gy1), (70, 66, 60), -1)
        cv2.rectangle(img, (hx0, hy0), (hx1, hy1), (40, 38, 36), -1)
        cam = cv2.remap(img, self.mx, self.my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(30, 30, 30))
        gain = self.rng.uniform(0.97, 1.03)
        noise = self.rng.normal(0, 2.0, cam.shape)
        return np.clip(cam.astype(np.float32) * gain + noise, 0, 255).astype(np.uint8)


# ======================================================================= AutoCam
class CalibrationCancelled(Exception):
    pass


class AutoCam(QObject):
    progress = Signal(int, int, str)  # passo, totale, testo
    detected = Signal(object)  # lista di (u, v) trovati finora, per disegnarli sull'anteprima
    need_user = Signal(str)  # serve un'azione dell'utente (poi continue_() o cancel())
    finished = Signal(object, str)  # CameraModel | None, messaggio
    photo_ready = Signal(object)  # 0.17.5, metodo "photo": foto dei dischi incisi per metterli a mano

    def __init__(self, ctl, cam, profile, grid_n=5, method="auto"):
        super().__init__()
        self.ctl = ctl
        self.cam = cam
        self.profile = profile
        self.grid_n = grid_n
        self.method = method
        self._cancel = threading.Event()
        self._go = threading.Event()
        self._ok_user = False
        self.used_method = None
        self.visible = None
        self.target_grid = None
        # 0.17.5: per la correzione a mano dei dischi incisi
        self.last_photo = None  # foto finale (testa parcheggiata) del bersaglio inciso
        self.park = None  # dove è stata parcheggiata la testa
        self.park_hint = None  # parcheggio già noto (dalla calibrazione salvata): niente giro per cercarlo
        self.guess = {}  # {indice del disco: (u, v)} trovati da soli, anche quelli scartati

    # ---- controllo dall'interfaccia
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self._cancel.set()
        self._go.set()

    def continue_(self):
        self._ok_user = True
        self._go.set()

    # ---- utilità
    def _check(self):
        if self._cancel.is_set():
            raise CalibrationCancelled()
        if not self.ctl.connected:
            raise RuntimeError(tr("macchina disconnessa"))
        if self.ctl.last_status.get("state") == "Alarm":
            raise RuntimeError(tr("la macchina è in allarme: sblocca o fai l'homing e riprova"))

    def _wait_idle(self, timeout=60):
        time.sleep(0.3)
        end = time.time() + timeout
        seen, stable = 0.0, 0
        while time.time() < end:
            self._check()
            st = self.ctl.last_status.get("state")
            if not self.ctl.busy and st == "Idle" and self.ctl.status_time > seen:
                seen = self.ctl.status_time
                stable += 1
                if stable >= 2:
                    return
            elif st != "Idle":
                stable = 0
            time.sleep(0.05)
        raise RuntimeError(tr("la macchina non ha finito il movimento in tempo"))

    def _wait_state(self, states, timeout=4):
        end = time.time() + timeout
        while time.time() < end:
            self._check()
            if self.ctl.last_status.get("state") in states:
                return True
            time.sleep(0.02)
        return False

    def _ask(self, text):
        self._go.clear()
        self._ok_user = False
        self.need_user.emit(text)
        self._go.wait()
        if self._cancel.is_set() or not self._ok_user:
            raise CalibrationCancelled()

    def _s(self, pct):
        return pct / 100.0 * self.profile.s_max

    # ---- procedura
    def _run(self):
        if self.method == "photo":  # 0.17.5: solo la foto dei dischi già incisi, per metterli a mano
            try:
                self._check()
                park = tuple(self.park_hint) if self.park_hint else self._park()[0]
                self.progress.emit(0, 1, tr("Sposto la testa fuori dall'inquadratura e faccio la foto…"))
                self._goto_bed(*park)
                self._wait_idle()
                self.park = park
                self.last_photo = cc._avg(self.cam.frames(3, after=time.time() + 0.3))
                self.target_grid = [g[:2] for g in cc.seq_grid(self.profile.bed_x, self.profile.bed_y)]
                self.photo_ready.emit(self)
                self.finished.emit(None, "")
            except CalibrationCancelled:
                self.finished.emit(None, tr("Annullato"))
            except Exception as exc:  # noqa: BLE001
                self.finished.emit(None, tr("Foto non riuscita: {0}", exc))
            return
        try:
            model, msg = self._calibrate()
            self.finished.emit(model, msg)
        except CalibrationCancelled:
            self._safe_off()
            self.finished.emit(None, "Calibrazione annullata")
        except Exception as exc:  # noqa: BLE001
            self._safe_off()
            self.finished.emit(None, f"Calibrazione interrotta: {exc}")

    def _safe_off(self):
        try:
            if self.ctl.connected:
                self.ctl.send_line("M5 S0")
        except Exception:  # noqa: BLE001
            pass

    def _calibrate(self):
        bx, by = self.profile.bed_x, self.profile.bed_y
        grid = cc.calibration_grid(bx, by, self.grid_n)
        size = self.cam.size
        if self.method in ("auto", "spot"):
            pairs = self._spot_method(grid)
            if pairs is not None and len(pairs) >= 9:
                model = cc.fit_with_validation([p[0] for p in pairs], [p[1] for p in pairs], (bx, by), self.cam.size)
                if model.rms_mm <= 1.5 or self.method == "spot":
                    self.used_method = "puntino laser"
                    return model, self._result_text(model, len(pairs), len(grid))
            if self.method == "spot":
                return None, tr("Il puntino laser non è stato visto abbastanza: prova il metodo con bersaglio inciso")
        pairs = self._sequential_method()
        tot = len(self.target_grid or grid)
        if len(pairs) < 9:
            return None, (tr("Trovati solo {0} cerchi su {1}: controlla che il cartone sia nella zona inquadrata e ben illuminato", len(pairs), tot))
        model = cc.fit_with_validation([p[0] for p in pairs], [p[1] for p in pairs], (bx, by), self.cam.size or size)
        if self.visible is not None:
            # oltre l'ultimo cerchio la correzione vale ancora per poco
            vis = cc.limit_to_points(model, [p[0] for p in pairs], bx, by)
            if vis is not None:
                self.visible = vis
        self.used_method = "bersaglio inciso"
        return model, self._result_text(model, len(pairs), tot)

    def _result_text(self, model, found, total):
        txt = (f"Calibrazione riuscita ({self.used_method}): {found}/{total} punti, "
               f"precisione ±{model.rms_mm:.2f} mm (peggiore {model.max_mm:.2f} mm)")
        vis = getattr(self, "visible", None)
        if vis is not None:
            bx, by = self.profile.bed_x, self.profile.bed_y
            x, y, w, h = vis
            cover = min(1.0, (w * h) / (bx * by))
            if cover < 0.93:
                k = max(bx / max(w, 1), by / max(h, 1))
                txt += (tr("\nLa camera vede circa {0:.0f} × {1:.0f} mm (da X{2:.0f} Y{3:.0f}), il {4:.0f}% del piano: fuori da questa zona la foto non c'è. Per vederlo tutto, alzala di circa ×{5:.1f} (altezza attuale × ", w, h, x, y, cover * 100, k) + f"{k:.1f}" + tr(") oppure usa un obiettivo più grandangolare."))
        return txt

    # ---- A) puntino laser
    def _fire_spot(self, pct):
        s = self._s(pct)
        for line in (f"M3 S{s:.0f}", "G91 G1 X0.3 F30", "G1 Y0.3", "G1 X-0.3", "G1 Y-0.3", "G90 M5 S0"):
            self.ctl.send_line(line)

    def _goto_bed(self, x, y):
        mx, my = self.profile.to_machine(x, y)
        self.ctl.goto_machine(mx, my, 6000)

    def _spot_at(self, x, y, pct):
        self._goto_bed(x, y)
        self._wait_idle()
        off = self.cam.frames(3, after=time.time() + 0.15)
        self._fire_spot(pct)
        if not self._wait_state(("Run",), timeout=4):
            self._wait_idle()
            return None
        on = self.cam.frames(3, after=time.time() + 0.3)
        self._wait_idle()
        if len(off) < 2 or len(on) < 2:
            raise RuntimeError(tr("la camera non sta inviando immagini"))
        pt, _peak = cc.detect_spot(off, on)
        return pt

    def _spot_method(self, grid):
        total = len(grid)
        found = []
        pct = 1.0
        self.progress.emit(0, total, tr("Cerco il puntino laser all'1%…"))
        first = self._spot_at(*grid[0], pct)
        if first is None:
            pct = 3.0
            self.progress.emit(0, total, tr("Non lo vedo: riprovo al 3%…"))
            first = self._spot_at(*grid[0], pct)
        if first is None:
            self.progress.emit(0, total, tr("Il puntino non è visibile: passo al bersaglio inciso"))
            return None
        found.append((grid[0], first))
        self.detected.emit([p[1] for p in found])
        misses = 0
        for i, (x, y) in enumerate(grid[1:], start=1):
            self._check()
            self.progress.emit(i, total, tr("Punto {0} di {1}  ·  X{2:.0f} Y{3:.0f}", i + 1, total, x, y))
            pt = self._spot_at(x, y, pct)
            if pt is None:
                misses += 1
                if misses > total * 0.3:
                    self.progress.emit(i, total, tr("Troppi punti non visti: passo al bersaglio inciso"))
                    return None
                continue
            found.append(((x, y), pt))
            self.detected.emit([p[1] for p in found])
        self.progress.emit(total, total, "Calcolo lente e prospettiva…")
        return found

    # ---- B) bersaglio inciso
    def _head_views(self, corners):
        """Scatti con la testa in punti diversi: mediana = piano senza testa; differenze = dove sta la testa."""
        shots = []
        for x, y in corners:
            self._check()
            self._goto_bed(x, y)
            self._wait_idle()
            shots.append(cc._avg(self.cam.frames(3, after=time.time() + 0.15)))
        stack = np.stack(shots)
        background = np.median(stack, axis=0)
        heads = []
        for s in shots:
            d = cv2.cvtColor(np.abs(s - background).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
            d = cv2.GaussianBlur(d, (0, 0), 3)
            peak = float(d.max())
            mask = (d >= peak * 0.5).astype(np.uint8)
            n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
            k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) if n > 1 else None
            heads.append(tuple(cents[k]) if k else None)
        return background, heads

    # ---- B) bersaglio inciso, un disco alla volta
    def _park(self):
        """Posizione di parcheggio: quella in cui testa e trave coprono meno l'inquadratura.
        Si sceglie fra angoli e metà dei lati confrontando le foto con la mediana."""
        bx, by = self.profile.bed_x, self.profile.bed_y
        m = 15.0  # non troppo vicino ai bordi: alcune schede hanno una corsa reale un po' più corta del piano
        cands = [(m, m), (bx - m, m), (bx / 2, m), (m, by - m), (bx - m, by - m), (bx / 2, by - m),
                 (m, by / 2), (bx - m, by / 2)]
        shots = []
        for i, (x, y) in enumerate(cands):
            self._check()
            self.progress.emit(i, len(cands), tr("Cerco dove parcheggiare la testa fuori dall'inquadratura…"))
            self._goto_bed(x, y)
            self._wait_idle()
            shots.append(cc._avg(self.cam.frames(3, after=time.time() + 0.2)))
        bg = np.median(np.stack(shots), axis=0)
        cover = [float((cv2.cvtColor(np.clip(np.abs(sh - bg), 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY) > 25).mean())
                 for sh in shots]
        k = int(np.argmin(cover))
        return cands[k], cover[k]

    def _burn_disc(self, x, y):
        wx, wy = self.ctl.wco
        mx, my = self.profile.to_machine(x, y)
        ux, uy = mx - wx, my - wy
        s = self._s(40)
        job = ["G90 G21", "M4 S0"]
        for r in (2.0, 1.5, 1.0, 0.5):  # disco pieno Ø 4 mm
            job += [f"G0 X{ux + r:.3f} Y{uy:.3f}", f"G1 F1000 S{s:.0f}", f"G2 X{ux + r:.3f} Y{uy:.3f} I{-r:.3f} J0", "S0"]
        job += ["M5 S0"]
        done = threading.Event()
        result = {}

        def on_done(ok, msg):
            result.update(ok=ok, msg=msg)
            done.set()

        self.ctl.job_finished.connect(on_done)
        try:
            self.ctl.stream_job(job)
            while not done.wait(0.1):
                self._check()
        finally:
            try:
                self.ctl.job_finished.disconnect(on_done)
            except (RuntimeError, TypeError):
                pass
        if not result.get("ok"):
            raise RuntimeError(result.get("msg", "incisione interrotta"))
        self._wait_idle()

    def _sequential_method(self, n=6):
        """Incide un disco alla volta su una griglia n×n di tutto il piano e dopo ognuno fotografa con la testa
        parcheggiata sempre nello stesso punto: la sola differenza fra due foto è il disco nuovo, quindi ogni
        disco si riconosce senza ambiguità. Funziona anche se la camera vede solo una parte del piano o se
        trave e testa coprono l'inquadratura."""
        bx, by = self.profile.bed_x, self.profile.bed_y
        self._ask(tr("Metti sul piano un cartone o un compensato chiaro, ben piatto e a fuoco, il più grande possibile.\nFreeLaserCut inciderà fino a {0} dischi (Ø 4 mm, 40%) uno alla volta e dopo ognuno farà una foto con la testa parcheggiata: i dischi fuori dall'inquadratura vengono semplicemente ignorati.\n\nOcchiali protettivi indossati e aspirazione accesa?", n * n))
        park, cover = self._park()
        self.park = park
        grid = [g[:2] for g in cc.seq_grid(bx, by, n)]  # stesso ordine di prima (serpentina dallo zero)
        self.target_grid = grid
        self.guess = {}
        self._goto_bed(*park)
        self._wait_idle()
        prev = cc._avg(self.cam.frames(3, after=time.time() + 0.25))
        H_img, W_img = prev.shape[:2]
        pairs = []
        for i, (x, y) in enumerate(grid):
            self._check()
            self.progress.emit(i, len(grid), tr("Disco {0} di {1}  ·  X{2:.0f} Y{3:.0f}  ·  visti finora {4}", i + 1, len(grid), x, y, len(pairs)))
            self._burn_disc(x, y)
            self._goto_bed(*park)
            self._wait_idle()
            cur = cc._avg(self.cam.frames(3, after=time.time() + 0.25))
            blobs = cc.find_dark_blobs([prev], [cur], min_area=6)
            prev = cur
            if not blobs:
                continue
            blobs.sort(key=lambda b: -b[2])
            u, v, strength = blobs[0]
            # un solo disco nuovo: la macchia più forte deve staccarsi bene dalle altre (luce che cambia, polvere)
            if len(blobs) > 1 and blobs[1][2] > 0.5 * strength:
                continue
            if not (3 < u < W_img - 3 and 3 < v < H_img - 3):
                continue
            self.guess[i] = (u, v)
            pairs.append(((x, y), (u, v)))
            self.detected.emit([p[1] for p in pairs])
        if len(pairs) >= 6:  # scarto le associazioni sbagliate (riflessi, polvere): devono stare su una prospettiva
            bp = np.float32([p[0] for p in pairs])
            ip = np.float32([p[1] for p in pairs])
            _H, inl = cv2.findHomography(bp, ip, cv2.RANSAC, 0.025 * math.hypot(W_img, H_img))
            if inl is not None:
                pairs = [p for p, k in zip(pairs, inl.ravel()) if k]
                keep = {p[0] for p in pairs}
                self.guess = {i: uv for i, uv in self.guess.items() if grid[i] in keep}
        self.last_photo = prev  # foto finale, testa parcheggiata: serve per correggere i punti a mano
        self.visible = (0.0, 0.0, bx, by)  # attiva il calcolo della zona vista in _calibrate
        self.progress.emit(len(grid), len(grid), "Calcolo lente e prospettiva…")
        return pairs

    def _scan_view(self, n=5):
        """La testa visita una griglia n×n: dove la camera la vede si stima l'inquadratura
        (omografia grezza) e si scopre quale parte del piano è davvero visibile."""
        bx, by = self.profile.bed_x, self.profile.bed_y
        m = 15.0
        xs = np.linspace(m, bx - m, n)
        ys = np.linspace(m, by - m, n)
        pts = []
        for j, y in enumerate(ys):
            pts += [(float(x), float(y)) for x in (xs if j % 2 == 0 else xs[::-1])]
        shots = []
        for i, (x, y) in enumerate(pts):
            self._check()
            self.progress.emit(i, len(pts) + 4, tr("Guardo dove la camera vede la testa: {0} di {1}", i + 1, len(pts)))
            self._goto_bed(x, y)
            self._wait_idle()
            shots.append(cc._avg(self.cam.frames(3, after=time.time() + 0.15)))
        stack = np.stack(shots)
        bg = np.median(stack, axis=0)
        H_img, W_img = bg.shape[:2]
        heads = []
        for s in shots:
            d = cv2.cvtColor(np.clip(np.abs(s - bg), 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
            d = cv2.GaussianBlur(d, (0, 0), 3)
            peak = float(d.max())
            if peak < 18:  # niente di diverso: la testa è fuori inquadratura
                heads.append(None)
                continue
            mask = (d >= peak * 0.5).astype(np.uint8)
            k, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
            if k <= 1:
                heads.append(None)
                continue
            j = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            x0, y0, w0, h0, area = stats[j]
            edge = x0 <= 2 or y0 <= 2 or x0 + w0 >= W_img - 3 or y0 + h0 >= H_img - 3
            heads.append(None if edge or area < 0.0004 * W_img * H_img else tuple(cents[j]))
        return pts, shots, bg, heads

    def _visible_grid(self, H, frame_size, n):
        """Griglia di bersagli dentro la parte di piano che la camera vede (stima dall'omografia grezza)."""
        bx, by = self.profile.bed_x, self.profile.bed_y
        W_img, H_img = frame_size
        ins = 0.06
        img_poly = np.float32([[W_img * ins, H_img * ins], [W_img * (1 - ins), H_img * ins],
                               [W_img * (1 - ins), H_img * (1 - ins)], [W_img * ins, H_img * (1 - ins)]])
        bed_poly = cv2.perspectiveTransform(img_poly.reshape(-1, 1, 2), np.linalg.inv(H)).reshape(-1, 2)
        m = 12.0
        x0, x1 = max(m, bed_poly[:, 0].min()), min(bx - m, bed_poly[:, 0].max())
        y0, y1 = max(m, bed_poly[:, 1].min()), min(by - m, bed_poly[:, 1].max())
        poly = bed_poly.astype(np.float32).reshape(-1, 1, 2)
        for nn in (n, n + 1, n + 2):
            xs = np.linspace(x0, x1, nn)
            ys = np.linspace(y0, y1, nn)
            grid = []
            for j, y in enumerate(ys):
                for x in (xs if j % 2 == 0 else xs[::-1]):
                    if cv2.pointPolygonTest(poly, (float(x), float(y)), True) >= 3.0:
                        grid.append((float(x), float(y)))
            if len(grid) >= 16:
                break
        vis_w, vis_h = max(0.0, x1 - x0 + 2 * m), max(0.0, y1 - y0 + 2 * m)
        return grid, (x0 - m, y0 - m, vis_w, vis_h)

    def _target_method(self, grid):
        n = self.grid_n
        self._ask(tr("Metti sul piano un foglio di cartone o compensato chiaro, ben piatto e a fuoco, nella zona "
                  "inquadrata dalla camera.\nPrima la testa farà un giro del piano a laser spento per capire cosa "
                  "vede la camera, poi inciderà piccoli dischi (Ø 4 mm) al 40% di potenza solo dove la camera "
                  "arriva.\n\nOcchiali protettivi indossati e aspirazione accesa?"))
        pts, shots, bg, heads = self._scan_view(5)
        seen = [(p, h) for p, h in zip(pts, heads) if h is not None]
        if len(seen) < 4:
            raise RuntimeError(tr("la camera vede la testa solo in {0} punti su {1}: alzala o orientala verso il centro del piano e riprova", len(seen), len(pts)))
        Hc, inl = cv2.findHomography(np.float32([p for p, _ in seen]), np.float32([h for _, h in seen]), cv2.RANSAC,
                                     0.05 * math.hypot(*bg.shape[1::-1]))
        if Hc is None:
            raise RuntimeError(tr("non riesco a capire l'inquadratura: la camera vede il piano?"))
        size = (bg.shape[1], bg.shape[0])
        grid, vis = self._visible_grid(Hc, size, n)
        self.visible = vis
        if len(grid) < 9:
            raise RuntimeError(tr("la parte di piano vista dalla camera è troppo piccola: alzala o allarga l'inquadratura"))
        total = len(grid) + 3
        # piano "senza testa": mediana degli scatti agli angoli e al centro del giro
        idx = sorted({0, 4, len(pts) - 1, len(pts) - 5, len(pts) // 2})
        before = np.median(np.stack([shots[i] for i in idx]), axis=0)
        bed_corners = [pts[i] for i in idx]
        coarse = Hc
        self.progress.emit(len(pts), len(pts) + total, tr("Incido {0} cerchi nella zona vista dalla camera…", len(grid)))
        wx, wy = self.ctl.wco
        job = ["G90 G21", "M4 S0"]
        s = self._s(40)
        for (x, y) in grid:
            mx, my = self.profile.to_machine(x, y)
            ux, uy = mx - wx, my - wy  # coordinate di lavoro del G-code
            # disco pieno Ø 4 mm: ben visibile anche su cartone scuro o con la camera lontana
            for r in (2.0, 1.5, 1.0, 0.5):
                job += [f"G0 X{ux + r:.3f} Y{uy:.3f}", f"G1 F1000 S{s:.0f}",
                        f"G2 X{ux + r:.3f} Y{uy:.3f} I{-r:.3f} J0", "S0"]
        job += ["M5 S0"]
        done = threading.Event()
        result = {}

        def on_done(ok, msg):
            result["ok"] = ok
            result["msg"] = msg
            done.set()

        self.ctl.job_finished.connect(on_done)
        try:
            self.ctl.stream_job(job)
            while not done.wait(0.2):
                self._check()
        finally:
            try:
                self.ctl.job_finished.disconnect(on_done)
            except (RuntimeError, TypeError):
                pass
        if not result.get("ok"):
            raise RuntimeError(result.get("msg", "incisione interrotta"))
        self._wait_idle()
        self.progress.emit(len(grid) + 2, total, tr("Foto del bersaglio inciso…"))
        after, _ = self._head_views(bed_corners)
        expected = cv2.perspectiveTransform(np.float32(grid).reshape(-1, 1, 2), coarse).reshape(-1, 2)
        sp = float(np.median(np.linalg.norm(np.diff(expected, axis=0), axis=1)))
        blobs = cc.find_dark_blobs([before], [after])
        found_img = cc.match_grid(blobs, expected, grid, max(sp, 20))
        pairs = [(g, p) for g, p in zip(grid, found_img) if p is not None]
        self.target_grid = grid
        self.detected.emit([p[1] for p in pairs])
        self.progress.emit(total, total, "Calcolo lente e prospettiva…")
        return pairs
