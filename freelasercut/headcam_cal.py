# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Telecamera sulla testa (0.19.6): calibrazione automatica sulla macchina e camera di testa simulata.

La calibrazione gira in un thread (come AutoCam) e parla con la macchina solo con spostamenti a laser spento e con
un segno inciso, piccolo (disco Ø 1,6 mm, solo tratti dritti, potenza scelta):
1. segno inciso nel punto P (dove è la testa);
2. il segno si trova: con una calibrazione precedente la camera ci va da sola e lo riconosce dalla differenza fra le
   foto prima e dopo; la prima volta la persona porta la camera sopra il segno e fa clic sul segno nel video;
3. scala grezza con spostamenti di 1 mm; 4. centratura sotto il mirino; 5. scala precisa con ± passo in X e Y;
6. offset O = P − M − A·(m − c) e verifica. Conti in core/headcam.py.
"""
import math
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal

from .camera import _FrameSource
from .core import headcam as H
from freelasercut.i18n import tr  # noqa: E402

MOVE_FEED = 3000.0
CENTER_TOL_PX = 1.5
VERIFY_TOL_PX = 2.5
RESID_MAX_MM = 0.08


class Cancelled(Exception):
    pass


# ======================================================================= camera USB della testa
class HeadCameraSource(_FrameSource):
    """Telecamera USB della testa: prima in MJPG 1280×720 (due camere sulla stessa USB non si soffocano), se così non
    dà immagini nel modo di sempre della camera del piano (camera.open_capture)."""

    def __init__(self, index, size=(1280, 720)):
        from . import camera as camera_mod

        self.index = index
        self.black = False
        self.mode = "mjpg-720"
        cap, frame = None, None
        try:
            cap = cv2.VideoCapture(index, camera_mod._backend())
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
                end = time.time() + 2.0
                while time.time() < end:
                    ok, f = cap.read()
                    if ok and f is not None and not camera_mod.is_black(f):
                        frame = f
                        break
        except Exception as exc:  # noqa: BLE001
            camera_mod.cam_log(f"camera di testa {index} · MJPG: {exc}")
        if frame is None:
            if cap is not None:
                cap.release()
            cap, self.mode, frame, self.black = camera_mod.open_capture(index, warm=1.0)
        if cap is None:
            raise RuntimeError(tr("camera {0} non disponibile", index))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap = cap
        camera_mod.cam_log(f"camera di testa {index}: {self.mode}, "
                           f"{'nessun fotogramma' if frame is None else f'{frame.shape[1]}×{frame.shape[0]}'}")
        super().__init__()
        if frame is not None:
            with self._lock:
                self._frame, self._t = frame, time.time()
                self.size = (frame.shape[1], frame.shape[0])

    def _grab(self):
        ok, f = self.cap.read()
        return f if ok else None

    def close(self):
        super().close()
        time.sleep(0.1)
        self.cap.release()


# ======================================================================= camera di testa simulata
class SimHeadCamera(_FrameSource):
    """Camera virtuale montata sulla testa del simulatore: vede il materiale sotto M + O con la scala, la rotazione
    e lo specchio dati, con le venature del legno, il rumore e i segni incisi (sim.burn_marks). Facoltativa una
    tavola chiara (angoli in coordinate macchina) su un fondo a nido d'ape scuro. Serve alle prove."""

    def __init__(self, sim, offset=(0.0, 35.0), scale=0.05, angle=0.0, mirror=False, size=(640, 360), board=None,
                 seed=3, beam=0.25):
        self.index = "simulata (testa)"
        self.black = False
        self.sim = sim
        self.offset = np.asarray(offset, float)
        R = np.array([[math.cos(math.radians(angle)), -math.sin(math.radians(angle))],
                      [math.sin(math.radians(angle)), math.cos(math.radians(angle))]])
        self.A = scale * R @ (np.diag([1.0, -1.0]) if mirror else np.eye(2))
        self.size = (int(size[0]), int(size[1]))
        self.board = None if board is None else np.asarray(board, float)
        self.beam = beam
        self.rng = np.random.default_rng(seed)
        w, h = self.size
        uu, vv = np.meshgrid(np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64))
        self._du = uu - (w - 1) / 2.0
        self._dv = vv - (h - 1) / 2.0
        super().__init__()

    def true_cal(self):
        return H.HeadCal(self.A.copy(), self.offset.copy(), self.size)

    def _grab(self):
        time.sleep(1 / 25)
        sim = self.sim
        if sim is None or not sim.is_open:
            return None
        mx, my = sim.pos[0], sim.pos[1]
        ox, oy = mx + self.offset[0], my + self.offset[1]
        X = ox + self.A[0, 0] * self._du + self.A[0, 1] * self._dv
        Y = oy + self.A[1, 0] * self._du + self.A[1, 1] * self._dv
        img = 182.0 + 14.0 * np.sin(0.9 * X + 0.35 * np.sin(0.21 * Y)) + 6.0 * np.sin(2.7 * X + 1.3 * Y)
        if self.board is not None:  # fuori dalla tavola: griglia a nido d'ape scura
            inside = _inside(self.board, X, Y)
            honey = 55.0 + 25.0 * ((np.sin(X * 1.1) * np.sin(Y * 1.1)) > 0.3)
            img = np.where(inside, img, honey)
        img = img.astype(np.float32)
        Ai = np.linalg.inv(self.A)
        c = np.array([(self.size[0] - 1) / 2.0, (self.size[1] - 1) / 2.0])
        rad = max(1, int(round(self.beam / math.sqrt(abs(np.linalg.det(self.A))))))
        span = 1.2 * max(self.size) * math.sqrt(abs(np.linalg.det(self.A)))
        for p in list(sim.burn_marks):
            if abs(p[0] - ox) > span or abs(p[1] - oy) > span:
                continue
            u, v = c + Ai @ (np.array(p) - np.array([ox, oy]))
            if -rad <= u < self.size[0] + rad and -rad <= v < self.size[1] + rad:
                cv2.circle(img, (int(round(u)), int(round(v))), rad, 40.0, -1, cv2.LINE_AA)
        img = cv2.GaussianBlur(img, (0, 0), 0.8)
        img = img * self.rng.uniform(0.97, 1.03) + self.rng.normal(0, 2.0, img.shape)
        g = np.clip(img, 0, 255).astype(np.uint8)
        return cv2.merge([g, g, g])


def _inside(poly, X, Y):
    """Punti (X, Y) dentro il quadrilatero convesso `poly` (4×2)."""
    sign = None
    out = np.ones_like(X, dtype=bool)
    for i in range(4):
        a, b = poly[i], poly[(i + 1) % 4]
        cross = (b[0] - a[0]) * (Y - a[1]) - (b[1] - a[1]) * (X - a[0])
        s = np.sign((b[0] - a[0]) * (poly[(i + 2) % 4][1] - a[1]) - (b[1] - a[1]) * (poly[(i + 2) % 4][0] - a[0]))
        sign = s
        out &= cross * sign >= 0
    return out


# ======================================================================= calibrazione
class HeadCamCalibration(QObject):
    progress = Signal(str)
    need_click = Signal(str)  # la persona porta la camera sul segno e ci fa clic nel video (poi click() o cancel())
    marked = Signal(object)  # pixel del segno trovato, per disegnarlo sul video
    finished = Signal(object, str)  # HeadCal | None, messaggio

    def __init__(self, ctl, cam, profile, prior=None, power=H.MARK_POWER):
        super().__init__()
        self.ctl, self.cam, self.profile = ctl, cam, profile
        self.prior = prior
        self.power = float(min(100.0, max(1.0, power)))
        self._cancel = threading.Event()
        self._go = threading.Event()
        self._click = None
        self.mark_at = None  # dove è stato inciso il segno (macchina)
        self.log = []  # passi e misure: vanno nel rapporto per l'assistenza
        self.thread = None

    # ---- comandi dalla finestra
    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def cancel(self):
        self._cancel.set()
        self._go.set()

    def click(self, px):
        self._click = (float(px[0]), float(px[1]))
        self._go.set()

    # ---- macchina
    def _check(self):
        if self._cancel.is_set():
            raise Cancelled()
        if not self.ctl.connected:
            raise RuntimeError(tr("macchina disconnessa"))
        if self.ctl.last_status.get("state") == "Alarm":
            raise RuntimeError(tr("la macchina è in allarme: sblocca o fai l'homing e riprova"))

    def _wait_idle(self, timeout=60):
        time.sleep(0.25)
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
            time.sleep(0.04)
        raise RuntimeError(tr("la macchina non ha finito il movimento in tempo"))

    def head(self):
        m = self.ctl.last_status.get("MPos") or [0.0, 0.0]
        return np.array([float(m[0]), float(m[1])])

    def _in_bed(self, mpt):
        bx, by = self.profile.to_bed(float(mpt[0]), float(mpt[1]))
        return -0.01 <= bx <= self.profile.bed_x + 0.01 and -0.01 <= by <= self.profile.bed_y + 0.01

    def _goto(self, mpt):
        if not self._in_bed(mpt):
            raise RuntimeError(tr("lo spostamento uscirebbe dall'area di lavoro: sposta la testa verso il centro e "
                                  "riprova"))
        self.ctl.goto_machine(float(mpt[0]), float(mpt[1]), MOVE_FEED)
        self._wait_idle()

    def _frames(self, n=2):
        time.sleep(0.15)
        fs = self.cam.frames(n, after=time.time() + 0.1)
        if len(fs) < 1:
            raise RuntimeError(tr("la camera della testa non sta inviando immagini"))
        return fs

    def _burn_mark(self):
        wx, wy = self.ctl.wco
        p = self.head()
        s = self.power / 100.0 * float(self.profile.s_max)
        job = H.mark_gcode(p[0] - wx, p[1] - wy, s)
        done, result = threading.Event(), {}

        def on_done(ok, msg):
            result.update(ok=ok, msg=msg)
            done.set()

        self.ctl.job_finished.connect(on_done)
        try:
            self.ctl.stream_job(job)
            while not done.wait(0.1):
                if self._cancel.is_set():
                    self._safe_off()
                    raise Cancelled()
        finally:
            try:
                self.ctl.job_finished.disconnect(on_done)
            except (RuntimeError, TypeError):
                pass
        if not result.get("ok"):
            raise RuntimeError(result.get("msg") or tr("incisione del segno interrotta"))
        self._wait_idle()
        return p

    def _safe_off(self):
        try:
            if self.ctl.connected:
                self.ctl.send_line("M5 S0")
        except Exception:  # noqa: BLE001
            from . import diag as _diag

            _diag.ignored("camera di testa: laser spento")

    def _say(self, text):
        self.log.append(text)
        self.progress.emit(text)

    # ---- trovare il segno
    def _find(self, near, radius, ref_area=None):
        if ref_area:  # la finestra deve essere molto più grande del segno, altrimenti non si vede lo sfondo
            radius = max(radius, 2.5 * math.sqrt(ref_area / math.pi))
        frames = self._frames(2)
        pt, area = H.detect_mark(H._avg(frames), near, radius, ref_area)
        return (None if pt is None else np.array(pt)), area

    # ---- procedura
    def _run(self):
        try:
            cal, msg = self._calibrate()
            self.finished.emit(cal, msg)
        except Cancelled:
            self._safe_off()
            self.finished.emit(None, tr("Calibrazione annullata"))
        except Exception as exc:  # noqa: BLE001
            self._safe_off()
            self.log.append(f"errore: {exc}")
            self.finished.emit(None, tr("Calibrazione interrotta: {0}", exc))

    def _calibrate(self):
        self._check()
        self._wait_idle()
        size = None
        f0 = self._frames(1)[0]
        size = (f0.shape[1], f0.shape[0])
        w, h = size
        c = np.array([(w - 1) / 2.0, (h - 1) / 2.0])
        prior = self.prior if (self.prior is not None and tuple(self.prior.size) == size) else None
        M0 = self.head()
        before = view = None
        if prior is not None:  # la camera sa già dove guardare: foto del punto prima del segno
            view = prior.head_for_crosshair(M0)
            if self._in_bed(view):
                self._say(tr("Guardo il punto prima di incidere il segno…"))
                self._goto(view)
                before = self._frames(3)
                self._goto(M0)
            else:
                prior = None
        self._say(tr("Incido il segno (disco di {0:.1f} mm al {1:.0f}%)…", 2 * H.MARK_R, self.power))
        P = self._burn_mark()
        self.mark_at = P
        self.log.append(f"segno in P = {P[0]:.3f}, {P[1]:.3f} (macchina)")
        m = area = None
        if prior is not None:
            self._goto(view)
            after = self._frames(3)
            pt, _a = H.detect_new_mark(before, after, near=c)
            if pt is not None:  # la differenza dice dov'è; forma e area si misurano sul segno intero
                pt2, area = H.detect_mark(H._avg(after), pt, 0.25 * min(w, h))
                m = None if pt2 is None else np.array(pt2)
            if m is not None:
                self.log.append(f"segno trovato da solo (differenza) in {m[0]:.1f}, {m[1]:.1f} (area {area} px)")
        if m is None:
            self._go.clear()
            self._click = None
            self.need_click.emit(tr("Porta la camera sopra il segno con le frecce (o il joystick), poi fai clic sul "
                                    "segno nel video."))
            self._go.wait()
            if self._cancel.is_set() or self._click is None:
                raise Cancelled()
            self._wait_idle()
            pt, area = self._find(self._click, 0.25 * min(w, h))
            if pt is None:
                raise RuntimeError(tr("non vedo un segno scuro dove hai fatto clic: avvicina il segno al centro del "
                                      "video, controlla la messa a fuoco della camera e riprova"))
            m = pt
            self.log.append(f"segno indicato con il clic, trovato in {m[0]:.1f}, {m[1]:.1f} (area {area} px)")
        self.marked.emit(tuple(m))
        Mh = self.head()
        # 3) scala grezza: 1 mm in X e in Y (se il segno si sposta troppo poco, 3 mm)
        A = None
        for step in (1.0, 3.0):
            shifts, moves = [], []
            for d in ((step, 0.0), (0.0, step)):
                self._goto(Mh + d)
                pt, _a = self._find(m, 0.45 * min(w, h), area)
                self._goto(Mh)
                if pt is None:
                    break
                shifts.append(pt - m)
                moves.append(d)
            if len(shifts) == 2 and min(np.hypot(*s) for s in shifts) >= 3.0:
                A, _r = H.fit_A(moves, shifts)
                if A is not None:
                    break
        if A is None:
            raise RuntimeError(tr("spostando la testa il segno non si sposta nel video come dovrebbe: controlla che "
                                  "la camera sia fissata bene alla testa e a fuoco"))
        self.log.append(f"scala grezza {math.sqrt(abs(np.linalg.det(A))):.4f} mm/pixel")
        # 4) centratura sotto il mirino
        Mc, m = self._center(Mh, m, A, c, area, w, h)
        # 5) scala precisa: ± passo in X e in Y attorno al centro
        scale = math.sqrt(abs(np.linalg.det(A)))
        step = float(min(8.0, max(0.5, 0.3 * min(w, h) * scale)))
        Ai = np.linalg.inv(A)
        moves, shifts = [], []
        for d in ((step, 0), (-step, 0), (0, step), (0, -step)):
            d = np.array(d, float)
            self._goto(Mc + d)
            pred = m - Ai @ d
            pt, _a = self._find(pred, 0.15 * min(w, h), area)
            if pt is None:
                raise RuntimeError(tr("ho perso il segno nel video durante la misura della scala"))
            moves.append(d)
            shifts.append(pt - m)
        self._goto(Mc)
        A, resid = H.fit_A(moves, shifts)
        self.log.append(f"scala precisa {math.sqrt(abs(np.linalg.det(A))):.5f} mm/pixel, passo {step:.2f} mm, "
                        f"scarto {resid:.4f} mm")
        if A is None or resid > RESID_MAX_MM:
            raise RuntimeError(tr("le misure della scala non tornano (scarto {0:.3f} mm): la camera si muove rispetto "
                                  "alla testa?", resid if A is not None else float('nan')))
        # 6) centratura fine con la scala precisa, offset e verifica
        Mc, m = self._center(Mc, m, A, c, area, w, h)
        O = H.offset_from_mark(P, Mc, m, A, size)
        cal = H.new_cal(A, O, size, resid)
        why = cal.problem()
        if why:
            raise RuntimeError(why)
        self._goto(cal.head_for_crosshair(P))
        pt, _a = self._find(c, 0.1 * min(w, h), area)
        err = float(np.hypot(*(pt - c))) if pt is not None else float("inf")
        self.log.append(f"verifica: segno a {err:.2f} pixel dal mirino; offset {O[0]:.3f}, {O[1]:.3f} mm")
        if err > VERIFY_TOL_PX:
            raise RuntimeError(tr("verifica non riuscita: portando il mirino sul segno resta a {0:.1f} pixel dal "
                                  "centro", err))
        cal.extra = {"verify_px": round(err, 2), "step_mm": round(step, 3)}
        return cal, tr("Camera della testa calibrata: mirino a {0:.2f} mm in X e {1:.2f} mm in Y dal laser, "
                       "{2:.3f} mm per pixel, verifica a {3:.1f} pixel dal centro.", O[0], O[1], cal.scale, err)

    def _center(self, M, m, A, c, area, w, h):
        """Sposta la testa finché il segno è sotto il mirino. -> (posizione della testa, pixel del segno)."""
        for _ in range(5):
            if np.hypot(*(m - c)) <= CENTER_TOL_PX:
                break
            M = M + A @ (m - c)  # il punto che si vede in m va sotto il mirino
            self._goto(M)
            pt, _a = self._find(c, 0.2 * min(w, h), area)
            if pt is None:
                raise RuntimeError(tr("ho perso il segno nel video mentre lo portavo sotto il mirino"))
            m = pt
        return M, m
