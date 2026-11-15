# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.0: camera della testa — una telecamera fissata alla testa del laser che guarda il piano dall'alto.

Un solo modello, usato da tutti i comandi (vedi freeburn/aggiornamento-0.20.0.md):

    P = L + O + M · (p − c)

L = punto del laser sul piano (mm, piano «come si vede»), p = pixel dell'immagine, c = centro dell'immagine (il
mirino), M = matrice 2×2 in mm per pixel (scala, rotazione, specchio), O = scostamento dal laser al punto del piano
che sta sotto il mirino. Vale per l'altezza del materiale a cui è stata fatta la calibrazione.

Qui ci sono: il modello e il suo file, la calibrazione automatica (puntino inciso e seguito nell'immagine), la tavola
presa da due angoli, la foto del piano a mosaico e una camera simulata per provare tutto senza hardware.
"""
import json
import math
import os
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import Signal

from . import camera_calib as cc
from .camera import AutoCam, CalibrationCancelled, _FrameSource
from .i18n import tr
from .profile import config_dir

HEAD_FILE = "head_camera.json"
HEAD_SIZE = (1280, 720)  # risoluzione chiesta alla camera della testa: meno banda USB con due camere
CENTER_TOL_PX = 1.5  # il puntino si considera «sotto il mirino» entro questa distanza
DEFAULT_POWER = 20.0  # % per incidere il puntino della calibrazione
MARK_FEED = 600.0


def head_file():
    return os.path.join(config_dir(), HEAD_FILE)


# ======================================================================= modello
class HeadModel:
    """Camera della testa calibrata. Tutte le coordinate del piano in mm (piano come si vede)."""

    def __init__(self, M, offset, frame_size, rms_px=0.0, rms_mm=0.0, created="", camera_name="",
                 camera_index=None, power_pct=None, k=0.0):
        self.M = np.array(M, float).reshape(2, 2)
        if not np.all(np.isfinite(self.M)) or abs(np.linalg.det(self.M)) < 1e-12:
            raise ValueError("matrice della camera della testa non valida")
        self.Minv = np.linalg.inv(self.M)
        self.offset = np.array(offset, float).reshape(2)
        if not np.all(np.isfinite(self.offset)):
            raise ValueError("scostamento non valido")
        self.frame_size = (int(frame_size[0]), int(frame_size[1]))
        if self.frame_size[0] <= 0 or self.frame_size[1] <= 0:
            raise ValueError("dimensione dell'immagine non valida")
        self.rms_px = float(rms_px)
        self.rms_mm = float(rms_mm)
        self.created = created or time.strftime("%d/%m/%Y %H:%M")
        self.camera_name = str(camera_name or "")
        self.camera_index = camera_index
        self.power_pct = power_pct
        # 0.20.0: lente (grandangolo M12): distorsione radiale, k per il raggio normalizzato a metà diagonale.
        # k < 0 = «a barile» (i bordi dell'immagine si stringono). 0 = nessuna correzione (file vecchi).
        self.k = float(k or 0.0)
        if not math.isfinite(self.k) or abs(self.k) > 0.8:
            raise ValueError("coefficiente della lente non valido")

    @property
    def c(self):
        return np.array([self.frame_size[0] / 2.0, self.frame_size[1] / 2.0])

    @property
    def f(self):
        return math.hypot(*self.frame_size) / 2.0

    def undistort(self, pts):
        """Pixel dell'immagine → pixel «senza lente» (dove sarebbero con una lente perfetta)."""
        return undistort_px(pts, self.c, self.f, self.k)

    def distort(self, pts):
        """Pixel «senza lente» → pixel dell'immagine."""
        return distort_px(pts, self.c, self.f, self.k)

    # ---- conti
    def img_to_bed(self, head, pts):
        """Pixel → punti del piano (mm) con il laser in head."""
        p = self.undistort(np.atleast_2d(np.asarray(pts, float)))
        return np.asarray(head, float) + self.offset + (p - self.c) @ self.M.T

    def bed_to_img(self, head, pts):
        """Punti del piano (mm) → pixel con il laser in head."""
        P = np.atleast_2d(np.asarray(pts, float))
        return self.distort(self.c + (P - np.asarray(head, float) - self.offset) @ self.Minv.T)

    def center(self, head):
        """Il punto del piano sotto il mirino con il laser in head."""
        return np.asarray(head, float) + self.offset

    def head_for_camera(self, point):
        """Dove deve andare il laser perché il punto stia sotto il mirino."""
        return np.asarray(point, float) - self.offset

    def mm_per_px(self):
        return math.sqrt(abs(float(np.linalg.det(self.M))))

    def mirrored(self):
        """Immagine specchiata rispetto a come si vede il piano dall'alto (u verso destra, v verso il basso; sul
        piano y verso l'alto): una camera normale ha det(M) < 0."""
        return float(np.linalg.det(self.M)) > 0

    def angle_deg(self):
        """Rotazione dell'immagine sul piano: direzione del bordo «destro» dell'immagine (asse u), 0° = asse X."""
        return math.degrees(math.atan2(self.M[1, 0], self.M[0, 0]))

    def view_mm(self):
        """Larghezza e altezza (mm) della zona di piano inquadrata."""
        w, h = self.frame_size
        return (float(np.hypot(*(self.M @ [w, 0]))), float(np.hypot(*(self.M @ [0, h]))))

    def describe(self):
        ox, oy = self.offset
        txt = tr("{0:.3f} mm per pixel · rotazione {1:.1f}° · scostamento dal laser X {2:+.2f} Y {3:+.2f} mm",
                 self.mm_per_px(), self.angle_deg(), ox, oy)
        if self.mirrored():
            txt += " · " + tr("immagine specchiata")
        if abs(self.k) >= 0.005:
            txt += " · " + tr("lente corretta ({0:+.0f}% ai bordi)", self.k * 100)
        return txt

    # ---- file
    def to_dict(self):
        return {"version": 1, "M": self.M.tolist(), "offset": self.offset.tolist(), "frame_size": list(self.frame_size),
                "rms_px": self.rms_px, "rms_mm": self.rms_mm, "created": self.created,
                "camera_name": self.camera_name, "camera_index": self.camera_index, "power_pct": self.power_pct,
                "k": self.k}

    @classmethod
    def from_dict(cls, d):
        return cls(d["M"], d["offset"], d["frame_size"], d.get("rms_px", 0.0), d.get("rms_mm", 0.0),
                   d.get("created", ""), d.get("camera_name", ""), d.get("camera_index"), d.get("power_pct"),
                   d.get("k", 0.0))

    def save(self, path=None):
        path = path or head_file()
        text = json.dumps(self.to_dict(), indent=1, ensure_ascii=False)  # prima il testo, poi il file
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path=None):
        """Il modello salvato, oppure None (file assente, vecchio o rovinato: mai un errore)."""
        path = path or head_file()
        try:
            with open(path, encoding="utf-8") as fh:
                return cls.from_dict(json.load(fh))
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return None


# Dove è montata la camera rispetto al laser, guardando il piano sullo schermo (destra = X+, su = Y+, cioè verso il
# fondo della macchina con il piano non ruotato). La persona sceglie una direzione e una distanza; FreeLaserCut ne fa
# lo scostamento indicativo da cui partire a cercare il puntino.
def undistort_px(pts, c, f, k):
    p = np.atleast_2d(np.asarray(pts, float))
    if not k:
        return p
    d = (p - c) / f
    return c + (p - c) * (1 + k * (d ** 2).sum(axis=1, keepdims=True))


def distort_px(pts, c, f, k, iters=40):
    """Inversa di undistort_px. I punti che con quella lente non possono stare nell'immagine (troppo lontani dal
    centro: la formula non ha soluzione) diventano NaN, così nessuno li disegna o li usa per sbaglio."""
    q = np.atleast_2d(np.asarray(pts, float))
    if not k:
        return q
    p = q.copy()
    with np.errstate(all="ignore"):
        for _ in range(iters):  # p tale che undistort(p) = q
            d = (p - c) / f
            den = 1 + k * (d ** 2).sum(axis=1, keepdims=True)
            p = c + (q - c) / np.where(den > 0.2, den, np.nan)
        back = undistort_px(p, c, f, k)
        bad = ~np.isfinite(p).all(axis=1) | (np.hypot(*(back - q).T) > 0.5)
    p[bad] = np.nan
    return p


def fit_lens(points, ref, deltas, c, f, kmax=0.5):
    """Coefficiente della lente che rende i movimenti del puntino nell'immagine proporzionali a quelli della testa.
    points: pixel del puntino; ref: pixel di riferimento; deltas: spostamenti sul piano (mm) corrispondenti.
    -> (k, M, rms) con il k migliore e (0, M0, rms0) senza correzione."""
    def solve(k):
        u = undistort_px(points, c, f, k) - undistort_px([ref], c, f, k)
        return solve_matrix(u, deltas)

    best = None
    grid = np.linspace(-kmax, kmax, 81)
    for k in grid:
        M, rms = solve(k)
        if M is not None and (best is None or rms < best[2]):
            best = (float(k), M, rms)
    if best is None:
        return None
    step = grid[1] - grid[0]
    for k in np.linspace(best[0] - step, best[0] + step, 41):
        M, rms = solve(k)
        if M is not None and rms < best[2]:
            best = (float(k), M, rms)
    return best


DIRECTIONS = {"r": (1, 0), "l": (-1, 0), "u": (0, 1), "d": (0, -1),
              "ur": (1, 1), "ul": (-1, 1), "dr": (1, -1), "dl": (-1, -1)}


def guess_from_direction(direction, cm):
    """("r", 6) → (60, 0) mm: la camera è 6 cm a destra del laser. None se la direzione non è nota o la distanza è 0."""
    v = DIRECTIONS.get(direction or "")
    if v is None or not cm or cm <= 0:
        return None
    n = math.hypot(*v)
    return (round(v[0] / n * cm * 10.0, 3), round(v[1] / n * cm * 10.0, 3))


START_MARGIN = 30.0  # mm dal bordo per la camera e per il laser, con la distanza indicativa (stima a occhio + passi)
START_UNKNOWN = 60.0  # mm dal bordo quando non si sa dov'è la camera: la ricerca gira tutto intorno


def calibration_start(head, guess, bed, margin=START_MARGIN, unknown=START_UNKNOWN):
    """Dove incidere il puntino della calibrazione perché la camera possa poi andarci sopra.

    Il puntino si incide con il laser in L0; per vederlo sotto il mirino la testa deve andare in L0 − O. Tutte e due
    le posizioni devono stare dentro il piano, con un margine per l'errore della stima e per i passi della misura.
    Con la camera 6 cm a destra del laser, quindi, il puntino non si può incidere nei primi 6 cm a sinistra del piano.
    Si sceglie il punto valido più vicino a dove è ora la testa.
    -> ((x, y), None) oppure (None, perché) se il piano è troppo piccolo per quella distanza."""
    bx, by = float(bed[0]), float(bed[1])
    g = np.zeros(2) if guess is None else np.asarray(guess, float).reshape(2)
    m = float(margin if guess is not None else unknown)
    for mm in (m, min(m, 10.0), 0.0):
        lo = np.maximum([mm, mm], g + mm)  # L0 ≥ mm e L0 − g ≥ mm
        hi = np.minimum([bx - mm, by - mm], np.array([bx, by]) + g - mm)  # L0 ≤ piano − mm e L0 − g ≤ piano − mm
        if np.all(lo <= hi):
            h = np.asarray(head if head is not None else ((lo + hi) / 2), float)
            p = np.clip(h, lo, hi)
            return (float(p[0]), float(p[1])), None
    return None, tr("la camera è troppo lontana dal laser per questo piano: in nessun punto il laser e la camera ci "
                    "arrivano tutti e due")


def natural_matrix(mm_per_px, angle_deg=0.0, mirror=False):
    """M di una camera che guarda dritta in basso: scala, rotazione e (se serve) specchio."""
    a = math.radians(angle_deg)
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    F = np.diag([1.0, -1.0]) if not mirror else np.diag([1.0, 1.0])
    return mm_per_px * R @ F


def solve_matrix(pix_deltas, bed_deltas):
    """M (2×2) tale che bed ≈ M · pix, ai minimi quadrati. -> (M, scarto quadratico medio in mm) o (None, None)."""
    A = np.asarray(pix_deltas, float).reshape(-1, 2)
    B = np.asarray(bed_deltas, float).reshape(-1, 2)
    if len(A) < 2 or np.linalg.matrix_rank(A, tol=1e-6) < 2:
        return None, None
    Mt, *_ = np.linalg.lstsq(A, B, rcond=None)
    M = Mt.T
    if abs(np.linalg.det(M)) < 1e-12:
        return None, None
    res = B - A @ M.T
    return M, float(np.sqrt((res ** 2).sum(axis=1).mean()))


# ======================================================================= immagini
def gray(frame):
    if frame is None:
        return None
    f = np.asarray(frame)
    if f.ndim == 3:
        f = cv2.cvtColor(f.astype(np.uint8) if f.dtype != np.uint8 else f, cv2.COLOR_BGR2GRAY)
    return f.astype(np.float32)


def find_new_mark(before_frames, after_frames, min_area=4):
    """Il puntino appena inciso: la macchia scura comparsa fra «prima» e «dopo». -> (u, v) o None.
    Se ci sono più macchie, vale la più forte solo se è chiaramente la più forte (altrimenti: non so)."""
    blobs = cc.find_dark_blobs(before_frames, after_frames, min_area=min_area)
    if not blobs:
        return None
    blobs.sort(key=lambda b: -b[2])
    if len(blobs) > 1 and blobs[1][2] > 0.5 * blobs[0][2]:
        return None
    return (blobs[0][0], blobs[0][1])


def refine_dark(frame, near, radius=12, search=None):
    """Centro della macchia scura più vicina a near: la macchia intera (componente connessa), non solo la parte che
    cade in una finestra, così il centro non si sposta se la finestra la taglia. -> (u, v) o None."""
    g = gray(frame)
    h, w = g.shape
    R = int(search or max(3 * radius, 40))
    u0, v0 = int(round(near[0])), int(round(near[1]))
    x0, x1 = max(0, u0 - R), min(w, u0 + R + 1)
    y0, y1 = max(0, v0 - R), min(h, v0 + R + 1)
    if x1 - x0 < 5 or y1 - y0 < 5:
        return None
    sub = cv2.GaussianBlur(g[y0:y1, x0:x1], (0, 0), 1.0)
    ring = np.concatenate([sub[0], sub[-1], sub[:, 0], sub[:, -1]])
    dark = np.clip(float(np.median(ring)) - sub, 0, None)
    cu, cv_ = u0 - x0, v0 - y0
    r = max(2, int(radius))
    core = dark[max(0, cv_ - r):cv_ + r + 1, max(0, cu - r):cu + r + 1]
    peak = float(core.max()) if core.size else 0.0
    if peak < 8:
        return None
    mask = (dark >= 0.4 * peak).astype(np.uint8)
    n, labels, _st, _ce = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return None
    ys, xs = np.nonzero(labels)
    k = labels[ys, xs][np.argmin((xs - cu) ** 2 + (ys - cv_) ** 2)]  # la macchia più vicina al punto dato
    sel = labels == k
    if sel[0].any() or sel[-1].any() or sel[:, 0].any() or sel[:, -1].any():
        return None  # tocca il bordo della finestra: non è un puntino (un bordo, un'ombra)
    wt = dark * sel
    yy, xx = np.mgrid[y0:y1, x0:x1]
    tot = float(wt.sum())
    return (float((xx * wt).sum() / tot), float((yy * wt).sum() / tot))


def patch(frame, p, half=24):
    """Immagine (grigi) attorno a p, per seguirla dopo uno spostamento. None se troppo vicino al bordo."""
    g = gray(frame)
    u, v = int(round(p[0])), int(round(p[1]))
    if u - half < 0 or v - half < 0 or u + half + 1 > g.shape[1] or v + half + 1 > g.shape[0]:
        return None
    return g[v - half:v + half + 1, u - half:u + half + 1].copy()


def track(frame, tpl, predicted=None, search=None):
    """Dove è finita la zona tpl in frame (centro, sub-pixel). -> ((u, v), somiglianza 0–1) o (None, 0)."""
    g = gray(frame)
    half = tpl.shape[0] // 2
    if predicted is None or search is None:
        x0, y0, x1, y1 = 0, 0, g.shape[1], g.shape[0]
    else:
        u, v = int(round(predicted[0])), int(round(predicted[1]))
        r = int(search) + half
        x0, y0 = max(0, u - r), max(0, v - r)
        x1, y1 = min(g.shape[1], u + r + 1), min(g.shape[0], v + r + 1)
    if x1 - x0 < tpl.shape[1] + 2 or y1 - y0 < tpl.shape[0] + 2:
        return None, 0.0
    res = cv2.matchTemplate(g[y0:y1, x0:x1], tpl, cv2.TM_CCOEFF_NORMED)
    _mn, score, _ml, (bx, by) = cv2.minMaxLoc(res)

    def sub(a, b, c_):
        d = a - 2 * b + c_
        return 0.0 if abs(d) < 1e-9 else 0.5 * (a - c_) / d

    dx = sub(res[by, bx - 1], res[by, bx], res[by, bx + 1]) if 0 < bx < res.shape[1] - 1 else 0.0
    dy = sub(res[by - 1, bx], res[by, bx], res[by + 1, bx]) if 0 < by < res.shape[0] - 1 else 0.0
    return (x0 + bx + dx + half, y0 + by + dy + half), float(score)


# ======================================================================= tavola da due angoli (fase 2)
def board_angle(a, b):
    """Direzione del lato A→B della tavola (gradi, 0 = asse X, antiorario). None se gli angoli coincidono."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if np.hypot(*(b - a)) < 1.0:
        return None
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def align_affine(bounds, a, angle_deg, margin=0.0):
    """Trasformazione (2×3) che ruota un riquadro (x0, y0, x1, y1) dell'angolo della tavola attorno al suo centro e
    mette il suo angolo in basso a sinistra (nel riferimento della tavola) in A + margine lungo i lati."""
    x0, y0, x1, y1 = bounds
    t = math.radians(angle_deg)
    R = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    cc_ = np.array([(x0 + x1) / 2, (y0 + y1) / 2])
    q0 = cc_ + R @ (np.array([x0, y0]) - cc_)  # il vecchio angolo in basso a sinistra, ruotato
    target = np.asarray(a, float) + R @ np.array([margin, margin])
    shift = target - q0
    tvec = cc_ - R @ cc_ + shift
    return np.hstack([R, tvec.reshape(2, 1)])


def find_corner(frame, near, radius=160):
    """Angolo della tavola vicino a near (pixel): due bordi rettilinei quasi perpendicolari, la loro intersezione.
    -> ((u, v), testo) oppure (None, perché)."""
    g = gray(frame)
    h, w = g.shape
    u0, v0 = int(round(near[0])), int(round(near[1]))
    x0, x1 = max(0, u0 - radius), min(w, u0 + radius)
    y0, y1 = max(0, v0 - radius), min(h, v0 + radius)
    roi = cv2.GaussianBlur(g[y0:y1, x0:x1], (0, 0), 2.0).astype(np.uint8)
    if roi.size == 0:
        return None, tr("fuori dall'immagine")
    edges = cv2.Canny(roi, 30, 90)
    span = min(roi.shape)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=max(15, span // 10), minLineLength=max(20.0, span * 0.2),
                            maxLineGap=12)
    if lines is None:
        return None, tr("nessun bordo dritto vicino al mirino")
    segs = [tuple(map(float, ln)) for ln in np.asarray(lines).reshape(-1, 4)]
    # raggruppo per direzione (modulo 180°) e tengo, per ogni direzione, la lunghezza totale
    def ang(s):
        return math.degrees(math.atan2(s[3] - s[1], s[2] - s[0])) % 180.0

    def length(s):
        return math.hypot(s[2] - s[0], s[3] - s[1])

    def ends_at(sg, X, tol=12.0):
        """X è a un capo del tratto (o poco oltre), non in mezzo: i bordi di un angolo finiscono lì, le linee dello
        sfondo (nido d'ape, guide) lo attraversano."""
        p0, p1 = np.array(sg[:2]), np.array(sg[2:])
        d = p1 - p0
        L = float(np.hypot(*d))
        if L < 1e-6:
            return False
        t = float((X - p0) @ d) / (L * L)
        e = X - p0
        side = abs(float(d[0] * e[1] - d[1] * e[0])) / L
        return side < tol and (-tol / L <= t <= tol / L or 1 - tol / L <= t <= 1 + tol / L)

    segs.sort(key=lambda s: -length(s))
    segs = segs[:60]
    best = None
    for i, s1 in enumerate(segs):
        for s2 in segs[i + 1:]:
            if abs((ang(s2) - ang(s1) + 90) % 180 - 90) < 55:
                continue
            d1 = np.array(s1[2:]) - np.array(s1[:2])
            d2 = np.array(s2[2:]) - np.array(s2[:2])
            A_ = np.array([d1, -d2]).T
            if abs(np.linalg.det(A_)) < 1e-9:
                continue
            t1, _t2 = np.linalg.solve(A_, np.array(s2[:2]) - np.array(s1[:2]))
            X = np.array(s1[:2]) + t1 * d1
            if not (ends_at(s1, X) and ends_at(s2, X)):
                continue
            score = length(s1) + length(s2)
            if best is None or score > best[0]:
                best = (score, s1, s2)
    if best is None:
        return None, tr("nessun angolo vicino al mirino: avvicinalo all'angolo della tavola")
    _score, first, second = best

    def line_fit(seed):
        """Retta che passa per tutti i tratti allineati al tratto seed (stessa direzione, vicini)."""
        a0 = ang(seed)
        n = np.array([-math.sin(math.radians(a0)), math.cos(math.radians(a0))])
        d0 = n @ np.array(seed[:2])
        pts = []
        for s in segs:
            if abs((ang(s) - a0 + 90) % 180 - 90) < 4 and abs(n @ np.array(s[:2]) - d0) < 4 \
                    and abs(n @ np.array(s[2:]) - d0) < 4:
                pts += [s[:2], s[2:]]
        pts = np.array(pts, np.float32)
        vx, vy, px, py = cv2.fitLine(pts, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        return np.array([px, py]), np.array([vx, vy])

    p1, d1 = line_fit(first)
    p2, d2 = line_fit(second)
    A = np.array([d1, -d2]).T
    if abs(np.linalg.det(A)) < 1e-6:
        return None, tr("bordi paralleli")
    t1, _t2 = np.linalg.solve(A, p2 - p1)
    corner = p1 + t1 * d1
    u, v = float(corner[0] + x0), float(corner[1] + y0)
    if not (x0 - 5 <= u <= x1 + 5 and y0 - 5 <= v <= y1 + 5):
        return None, tr("i bordi si incontrano lontano dal mirino")
    return (u, v), tr("angolo trovato")


# ======================================================================= foto a mosaico (fase 3)
def mosaic_positions(zone, view, overlap=0.3):
    """Punti del piano da mettere sotto il mirino per coprire zone (x0, y0, x1, y1) con foto di view (w, h) mm."""
    x0, y0, x1, y1 = zone
    sx = max(1.0, view[0] * (1 - overlap))
    sy = max(1.0, view[1] * (1 - overlap))
    nx = max(1, int(math.ceil((x1 - x0) / sx)) + (0 if (x1 - x0) <= view[0] else 0))
    ny = max(1, int(math.ceil((y1 - y0) / sy)))
    xs = [x0 + (x1 - x0) / 2] if (x1 - x0) <= view[0] * 0.9 else list(np.linspace(x0 + view[0] * 0.4,
                                                                                  x1 - view[0] * 0.4, max(nx, 2)))
    ys = [y0 + (y1 - y0) / 2] if (y1 - y0) <= view[1] * 0.9 else list(np.linspace(y0 + view[1] * 0.4,
                                                                                  y1 - view[1] * 0.4, max(ny, 2)))
    out = []
    for j, y in enumerate(ys):
        row = xs if j % 2 == 0 else xs[::-1]  # a serpentina: meno strada
        out += [(float(x), float(y)) for x in row]
    return out


_UNDIST_CACHE = {}


def undistort_frame(frame, model):
    """La foto «senza lente» (stessa misura), per incollarla con una trasformazione esatta. Senza lente: la stessa."""
    if not getattr(model, "k", 0.0):
        return frame
    h, w = frame.shape[:2]
    key = (w, h, round(model.k, 6))
    maps = _UNDIST_CACHE.get(key)
    if maps is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
        src = distort_px(np.stack([xx.ravel(), yy.ravel()], axis=1), model.c, model.f, model.k)
        src = np.where(np.isfinite(src), src, -1.0)  # fuori dalla lente: bordo
        maps = (src[:, 0].reshape(h, w).astype(np.float32), src[:, 1].reshape(h, w).astype(np.float32))
        _UNDIST_CACHE.clear()
        _UNDIST_CACHE[key] = maps
    return cv2.remap(frame, maps[0], maps[1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


class Mosaic:
    """Foto del piano fatta di tante foto della camera della testa (ppm pixel per mm, come la foto della camera del
    piano). Ogni foto si pesa di più al centro: le giunte non si vedono."""

    def __init__(self, bed, ppm=2.0):
        self.bed = (float(bed[0]), float(bed[1]))
        self.ppm = float(ppm)
        self.W, self.H = int(round(self.bed[0] * ppm)), int(round(self.bed[1] * ppm))
        self.acc = np.zeros((self.H, self.W, 3), np.float32)
        self.wsum = np.zeros((self.H, self.W), np.float32)
        self.count = 0

    def affine(self, model, head):
        """Pixel della camera → pixel della foto del piano (2×3)."""
        k = self.ppm
        base = np.asarray(head, float) + model.offset - model.M @ model.c
        A = np.array([[k * model.M[0, 0], k * model.M[0, 1], k * base[0]],
                      [-k * model.M[1, 0], -k * model.M[1, 1], k * (self.bed[1] - base[1])]])
        return A

    def add(self, frame, model, head, keep=0.8):
        frame = undistort_frame(frame, model)
        h, w = frame.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        wx = 1 - np.abs(xx - w / 2) / (w / 2 * keep)
        wy = 1 - np.abs(yy - h / 2) / (h / 2 * keep)
        weight = np.clip(np.minimum(wx, wy), 0, 1) ** 1.5
        A = self.affine(model, head)
        size = (self.W, self.H)
        img = cv2.warpAffine(frame.astype(np.float32), A, size, flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0))
        wt = cv2.warpAffine(weight, A, size, flags=cv2.INTER_LINEAR, borderValue=0)
        self.acc += img * wt[..., None]
        self.wsum += wt
        self.count += 1

    def image(self, back=(46, 40, 34)):
        out = np.empty_like(self.acc)
        out[:] = back
        ok = self.wsum > 1e-3
        out[ok] = self.acc[ok] / self.wsum[ok][:, None]
        return np.clip(out, 0, 255).astype(np.uint8)


# ======================================================================= camera simulata
class SimHeadCamera(_FrameSource):
    """Camera virtuale fissata alla testa del simulatore: vede un pezzo di materiale con una trama (come il legno o il
    cartone) attorno al punto L + O. Serve alle prove automatiche: modello vero noto (true_model)."""

    PPM = 8.0  # pixel per mm della trama del materiale

    def __init__(self, sim, offset=(0.0, 35.0), mm_per_px=0.08, angle=0.0, mirror=False, size=(640, 480), seed=3,
                 board=None, profile=None, lag=0.0, k=0.0):
        self.index = "sim-testa"
        self.lag = float(lag)  # come le camere vere: fotogrammi che arrivano in ritardo (secondi)
        self._queue = []
        self.black = False
        self.mode = "sim"
        self.sim = sim
        self.profile = profile
        self.w, self.h = size
        self.true = HeadModel(natural_matrix(mm_per_px, angle, mirror), offset, size, k=k)
        if k:  # pixel dell'immagine → pixel «senza lente», una volta sola
            yy, xx = np.mgrid[0:size[1], 0:size[0]].astype(np.float64)
            self._und = self.true.undistort(np.stack([xx.ravel(), yy.ravel()], axis=1))
        else:
            self._und = None
        self.rng = np.random.default_rng(seed)
        bx, by = float(sim.settings[130]), float(sim.settings[131])
        self.bed = (bx, by)
        tw, th = int(bx * self.PPM), int(by * self.PPM)
        small = self.rng.uniform(0, 1, (int(by * 1.2), int(bx * 1.2))).astype(np.float32)
        tex = cv2.resize(small, (tw, th), interpolation=cv2.INTER_CUBIC)
        tex = cv2.GaussianBlur(tex, (0, 0), 3)
        tex = (tex - tex.min()) / max(1e-6, float(tex.max() - tex.min()))
        base = (150 + 70 * tex).astype(np.uint8)
        if board is not None:  # nido d'ape scuro e, sopra, una tavola chiara: per l'angolo automatico
            base = (40 + 30 * tex).astype(np.uint8)
            hexes = base.copy()
            for y in range(0, th, int(5 * self.PPM)):
                cv2.line(hexes, (0, y), (tw, y), 15, 2)
            for x in range(0, tw, int(5 * self.PPM)):
                cv2.line(hexes, (x, 0), (x, th), 15, 2)
            base = hexes
            pts = np.array([[p[0] * self.PPM, th - p[1] * self.PPM] for p in board], np.int32)
            cv2.fillPoly(base, [pts], 205)
            base = np.where(cv2.fillPoly(np.zeros_like(base), [pts], 1) > 0,
                            (185 + 30 * tex).astype(np.uint8), base)
        self.material = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
        self._marks_done = 0
        super().__init__()

    def head(self):
        if self.profile is not None:
            m = self.sim.pos
            return np.array(self.profile.to_bed(m[0], m[1]), float)
        return np.array(self.sim.to_bed(self.sim.pos[0], self.sim.pos[1]), float)

    def _grab(self):
        time.sleep(1 / 20)
        sim = self.sim
        if not sim.is_open:
            return None
        th = self.material.shape[0]
        marks = sim.burn_marks
        while self._marks_done < len(marks):
            mx, my = marks[self._marks_done]
            if self.profile is not None:
                x, y = self.profile.to_bed(mx, my)
            else:
                x, y = sim.to_bed(mx, my)
            cv2.circle(self.material, (int(round(x * self.PPM)), int(round(th - y * self.PPM))),
                       int(0.3 * self.PPM), (40, 44, 50), -1, cv2.LINE_AA)
            self._marks_done += 1
        L = self.head()
        m = self.true
        k = self.PPM
        base = L + m.offset - m.M @ m.c
        A = np.array([[k * m.M[0, 0], k * m.M[0, 1], k * base[0]],
                      [-k * m.M[1, 0], -k * m.M[1, 1], k * (self.bed[1] - base[1])]])
        if self._und is None:
            img = cv2.warpAffine(self.material, A, (self.w, self.h), flags=cv2.WARP_INVERSE_MAP | cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(20, 20, 20))
        else:
            src = self._und @ A[:, :2].T + A[:, 2]
            img = cv2.remap(self.material, src[:, 0].reshape(self.h, self.w).astype(np.float32),
                            src[:, 1].reshape(self.h, self.w).astype(np.float32), cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=(20, 20, 20))
        if sim.state == "Run" and sim.power > 0:  # il punto del laser acceso, se è nell'inquadratura
            u, v = m.bed_to_img(L, [L])[0]
            if 0 <= u < self.w and 0 <= v < self.h:
                glow = np.zeros_like(img)
                cv2.circle(glow, (int(u), int(v)), 10, (255, 190, 90), -1, cv2.LINE_AA)
                img = cv2.add(img, cv2.GaussianBlur(glow, (0, 0), 3))
        noise = self.rng.normal(0, 1.5, img.shape)
        out = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        if self.lag <= 0:
            return out
        now = time.time()
        self._queue.append((now, out))
        while len(self._queue) > 1 and self._queue[1][0] <= now - self.lag:
            self._queue.pop(0)
        return self._queue[0][1]


# ======================================================================= lavori sulla macchina
def head_on_bed(ctl, profile):
    """Posizione del laser sul piano (mm) dall'ultimo stato della scheda, o None."""
    m = ctl.last_status.get("MPos")
    if not m:
        return None
    return np.array(profile.to_bed(m[0], m[1]), float)


def clamp_to_bed(profile, x, y):
    return (min(max(float(x), 0.0), float(profile.bed_x)), min(max(float(y), 0.0), float(profile.bed_y)))


class HeadCalibration(AutoCam):
    """Calibrazione automatica della camera della testa (thread). Usa i controlli di sicurezza di AutoCam
    (macchina connessa, niente allarme, annulla) e la stessa uscita: finished(HeadModel | None, testo)."""

    need_click = Signal(str)  # il puntino non è nell'inquadratura: la persona sposta la testa e fa clic sul puntino
    mark_seen = Signal(object)  # (u, v) del puntino nell'immagine, per disegnarlo
    # 0.20.0 (prova sul B1 del 15/11): il puntino trovato da solo si fa confermare dalla persona, che lo vede cerchiato
    # nel video. Sul vero una differenza fra due foto (fotogrammi in ritardo, luce) era stata presa per il puntino.
    need_confirm = Signal(object)  # (u, v): «è questo il puntino inciso?» → confirm(True/False)

    def __init__(self, ctl, cam, profile, power_pct=DEFAULT_POWER, camera_name="", camera_index=None, guess=None,
                 ask_confirm=True):
        super().__init__(ctl, cam, profile, grid_n=1, method="head")
        # dove si trova più o meno il centro della camera rispetto al laser (mm), se la persona lo sa: la ricerca del
        # puntino parte da lì
        self.guess = None if guess is None else np.asarray(guess, float).reshape(2)
        self.ask_confirm = ask_confirm
        self._confirmed = None
        self.before_at = []
        self.power_pct = float(min(max(power_pct, 1.0), 100.0))
        self.camera_name = camera_name
        self.camera_index = camera_index
        self._click = None
        self.mark_bed = None  # dove è stato inciso il puntino (mm)
        self._mark_r = 10.0  # raggio del puntino nell'immagine (pixel)

    def confirm(self, ok):
        """Risposta della persona a need_confirm."""
        self._confirmed = bool(ok)
        self._ok_user = True
        self._go.set()

    def click(self, u, v):
        """Clic della persona sul puntino nel video (quando è stato chiesto con need_click)."""
        self._click = (float(u), float(v))
        self._ok_user = True
        self._go.set()

    # ---- utilità
    def _head(self):
        self._wait_idle()
        L = head_on_bed(self.ctl, self.profile)
        if L is None:
            raise RuntimeError(tr("posizione della testa sconosciuta"))
        return L

    def _go_to(self, x, y):
        x, y = clamp_to_bed(self.profile, x, y)
        mx, my = self.profile.to_machine(x, y)
        self.ctl.goto_machine(mx, my, 3000)
        return self._head()

    def _shot(self, n=3, settle=4.0):
        """n foto con l'immagine ferma. Sul vero la camera può dare fotogrammi in ritardo dopo un movimento (code del
        driver): si aspetta che due fotogrammi di fila siano uguali prima di tenere quelli buoni."""
        end = time.time() + settle
        prev = self.cam.get(after=time.time() + 0.2)
        while prev is not None and time.time() < end:
            self._check()
            nxt = self.cam.get(after=time.time() + 0.15)
            if nxt is None:
                break
            a, b = gray(prev)[::4, ::4], gray(nxt)[::4, ::4]
            if a.shape == b.shape and float(np.abs(a - b).mean()) < 2.5:
                break
            prev = nxt
        frames = self.cam.frames(n, after=time.time() + 0.05)
        if len(frames) < max(1, n - 1):
            raise RuntimeError(tr("la camera della testa non sta inviando immagini"))
        return frames

    def _burn_mark(self, L):
        """Puntino pieno Ø 1,6 mm nel punto L (coordinate di lavoro come AutoCam._burn_disc)."""
        wx, wy = self.ctl.wco
        mx, my = self.profile.to_machine(*L)
        ux, uy = mx - wx, my - wy
        s = self._s(self.power_pct)
        job = ["G90 G21", "M4 S0"]
        for r in (0.8, 0.55, 0.3):
            job += [f"G0 X{ux + r:.3f} Y{uy:.3f}", f"G1 F{MARK_FEED:.0f} S{s:.0f}",
                    f"G2 X{ux + r:.3f} Y{uy:.3f} I{-r:.3f} J0", "S0"]
        job += [f"G0 X{ux:.3f} Y{uy:.3f}", f"G1 X{ux + 0.05:.3f} S{s:.0f}", "S0", f"G0 X{ux:.3f}", "M5 S0"]
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
            raise RuntimeError(result.get("msg", tr("incisione interrotta")))

    def _measure(self, tpl, predicted=None, search=None):
        """Dove è adesso il puntino: confronto con la sua immagine e conferma che lì c'è davvero una macchia scura
        (se il puntino è uscito dall'inquadratura il confronto troverebbe comunque «qualcosa»). -> ((u, v), foto)
        oppure (None, foto)."""
        f = cc._avg(self._shot(2)).astype(np.uint8)
        p, score = track(f, tpl, predicted, search)
        if p is None or score < 0.7:
            return None, f
        q = refine_dark(f, p, radius=self._mark_r)
        if q is None or math.hypot(q[0] - p[0], q[1] - p[1]) > max(3.0, self._mark_r * 0.5):
            return None, f
        return q, f

    # ---- procedura
    def _run(self):
        try:
            model, msg = self._calibrate()
            self.finished.emit(model, msg)
        except CalibrationCancelled:
            self._safe_off()
            self.finished.emit(None, tr("Calibrazione annullata"))
        except Exception as exc:  # noqa: BLE001
            self._safe_off()
            self.finished.emit(None, tr("Calibrazione interrotta: {0}", exc))

    def _texture_matrix(self, L0, size):
        """Scala, rotazione e specchio dal movimento della trama del materiale (laser spento), prima di incidere:
        servono per cercare il puntino se non è nell'inquadratura. -> M o None (materiale senza trama)."""
        c = np.array([size[0] / 2.0, size[1] / 2.0])
        half = int(min(size) // 6)
        f0 = cc._avg(self._shot(2)).astype(np.uint8)
        tpl = patch(f0, c, half)
        if tpl is None or float(tpl.std()) < 3.0:
            return None
        pairs = []
        for dx, dy in ((1, 0), (0, 1)):
            for step in (2.0, 6.0):
                ddx, ddy = self._inside(L0, dx * step, dy * step)
                Li = self._go_to(L0[0] + ddx, L0[1] + ddy)
                f = cc._avg(self._shot(2)).astype(np.uint8)
                p, score = track(f, tpl)
                if p is None or score < 0.6:
                    break
                d = np.array(p) - c
                if np.hypot(*d) >= 6.0 or step == 6.0:
                    pairs.append((d, L0 - Li))
                    break
        self._go_to(*L0)
        M, _ = solve_matrix([a for a, _b in pairs], [b for _a, b in pairs])
        return M

    def _candidates(self, L0, M, size, reach=90.0, cap=36):
        """Scostamenti g da provare (la testa va in L0 − g). Senza indicazioni il primo è 0 e poi in ordine di
        distanza; con la distanza indicativa (guess) si parte da lì."""
        start = self.guess if self.guess is not None else np.zeros(2)
        bx, by = self.profile.bed_x, self.profile.bed_y

        def inside(g):
            x, y = L0 - g
            return 0 <= x <= bx and 0 <= y <= by

        if M is None:
            out = [start] + ([np.zeros(2)] if self.guess is not None else [])
            return [g for g in out if inside(g)] or [np.zeros(2)]
        view = HeadModel(M, (0, 0), size).view_mm()
        step = max(5.0, 0.75 * min(view))
        n = int(reach // step)
        out = []
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                g = start + np.array([i * step, j * step])
                if inside(g):
                    out.append(g)
        out.sort(key=lambda g: float(np.hypot(*(g - start))))
        return out[:cap] or [np.zeros(2)]

    def _calibrate(self):
        self._check()
        size = tuple(self.cam.size) if self.cam.size and self.cam.size[0] else None
        L0 = self._head()
        self.mark_bed = tuple(L0)
        self.progress.emit(0, 7, tr("Guardo il materiale (laser spento)…"))
        first = self._shot(3)
        size = size or (first[0].shape[1], first[0].shape[0])
        c = np.array([size[0] / 2.0, size[1] / 2.0])
        M_tex = self._texture_matrix(L0, size)
        # con la distanza indicativa bastano le posizioni attorno a quella (stima a occhio: qualche cm): meno attesa
        cands = self._candidates(L0, M_tex, size, cap=9 if self.guess is not None else 36)
        befores = []
        self.before_at = []  # dove era la testa per ogni foto «prima» (deve essere L0 − g, anche per la prima)
        for i, g in enumerate(cands):
            self._check()
            # 0.20.0 (prova sul B1 del 15/11): la prima foto si faceva sempre con la testa in L0, anche quando la prima
            # posizione da guardare era un'altra (distanza indicativa): dopo il puntino la testa andava sul puntino,
            # non poteva confrontare le due foto e tornava indietro a cercarlo
            self.progress.emit(0, 7, tr("Foto del materiale prima del puntino ({0} di {1})…", i + 1, len(cands)))
            self.before_at.append(tuple(self._go_to(*(L0 - g))))
            befores.append(self._shot(3))
        self._go_to(*L0)
        self.progress.emit(1, 7, tr("Incido il puntino al {0:.0f}%…", self.power_pct))
        self._burn_mark(L0)
        self._check()
        pk = None
        for i, g in enumerate(cands):
            self._check()
            if i:
                self.progress.emit(2, 7, tr("Cerco il puntino ({0} di {1})…", i + 1, len(cands)))
            Lk = self._go_to(*(L0 - g))
            after = self._shot(3)
            pk = find_new_mark(befores[i], after)
            if pk is not None:
                frame_k = cc._avg(after).astype(np.uint8)
                q = refine_dark(frame_k, pk, radius=10)
                pk = q if q is not None else pk
                if self.ask_confirm and not self._ask_confirm(pk):
                    pk = None  # non era il puntino: lo indica la persona
                break
        if pk is None:
            self.progress.emit(2, 7, tr("Il puntino non è nell'inquadratura"))
            self._click = None
            self._go.clear()
            self._ok_user = False
            self.need_click.emit(tr("Non vedo il puntino inciso. Sposta la testa con le frecce (scheda Movimento) "
                                    "finché lo vedi nel video della camera della testa, poi fai clic sul puntino."))
            self._go.wait()
            if self._cancel.is_set() or self._click is None:
                raise CalibrationCancelled()
            Lk = self._head()
            frame_k = cc._avg(self._shot(3)).astype(np.uint8)
            q = refine_dark(frame_k, self._click, radius=14)
            pk = q if q is not None else self._click
        pk = np.asarray(pk, float)
        self.mark_seen.emit(tuple(pk))
        self._mark_r = self._mark_radius(frame_k, pk)
        half = int(max(24, 2.2 * self._mark_r))
        tpl = patch(frame_k, pk, half=half)
        # A) passi di 1 mm: una prima stima di scala e rotazione (il puntino non può uscire dall'inquadratura)
        self.progress.emit(3, 7, tr("Seguo il puntino spostando la testa…"))
        pairs = []
        M = None
        for dx, dy in ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)):
            self._check()
            if tpl is None:
                break
            dx, dy = self._inside(Lk, dx, dy)
            Li = self._go_to(Lk[0] + dx, Lk[1] + dy)
            pred = None if M is None else pk + np.linalg.inv(M) @ (Lk - Li)
            p, _f = self._measure(tpl, pred, None if pred is None else 30)
            if p is not None:
                pairs.append((np.array(p) - pk, Lk - Li))
                M, _ = solve_matrix([a for a, _b in pairs], [b for _a, b in pairs])
                if M is not None:
                    self.detected.emit([tuple(pk + a) for a, _b in pairs])
        if M is None:
            raise RuntimeError(tr("non riesco a seguire il puntino: il materiale deve stare fermo e ben illuminato"))
        # B) il puntino al centro dell'immagine: da lì i passi lunghi non lo fanno uscire
        self.progress.emit(4, 7, tr("Porto il puntino al centro dell'immagine…"))
        for _ in range(2):
            target = Lk + M @ (pk - c)
            tx, ty = clamp_to_bed(self.profile, *target)
            Li = self._go_to(tx, ty)
            pred = pk + np.linalg.inv(M) @ (Lk - Li)
            p, f = self._measure(tpl, pred, 40)
            if p is None:
                break
            Lk, pk = Li, np.asarray(p, float)
            t2 = patch(f, pk, half=half)
            tpl = t2 if t2 is not None else tpl
            if np.hypot(*(pk - c)) < 20:
                break
        # C) passi di 3 mm e poi più lunghi (precisione), sempre con il puntino previsto dentro l'immagine
        self.progress.emit(5, 7, tr("Misuro scala e rotazione…"))
        pairs = []
        Minv = np.linalg.inv(M)
        steps = [(3.0, 0.0), (0.0, 3.0), (-3.0, 0.0), (0.0, -3.0)]
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, -1)):
            st = self._long_step(pk, Minv, dx, dy, size)
            if st >= 4.0:
                steps.append((dx * st, dy * st))
        for dx, dy in steps:
            self._check()
            ddx, ddy = self._inside(Lk, dx, dy)
            pred = pk + Minv @ np.array([-ddx, -ddy])
            if not (half <= pred[0] <= size[0] - half and half <= pred[1] <= size[1] - half):
                continue
            Li = self._go_to(Lk[0] + ddx, Lk[1] + ddy)
            p, _f = self._measure(tpl, pred, 30)
            if p is None:
                continue
            pairs.append((np.array(p) - pk, Lk - Li))
            M2, _ = solve_matrix([a for a, _b in pairs], [b for _a, b in pairs])
            if M2 is not None:
                M, Minv = M2, np.linalg.inv(M2)
        M, rms_mm = solve_matrix([a for a, _b in pairs], [b for _a, b in pairs])
        if M is None or len(pairs) < 3:
            raise RuntimeError(tr("misure del puntino non coerenti"))
        # D) il puntino verso i bordi dell'immagine, un anello alla volta: misura la lente (i grandangoli stringono i
        # bordi). Dopo ogni anello lente e matrice si ricalcolano, così l'anello dopo si prevede bene anche con una
        # lente molto storta
        self.progress.emit(5, 7, tr("Misuro la lente verso i bordi dell'immagine…"))
        f_ = math.hypot(*size) / 2.0
        k = 0.0
        far = []
        kept = len(pairs)
        pts = [pk + a for a, _b in pairs]
        dls = [b for _a, b in pairs]
        for ring in (0.35, 0.55, 0.75):
            for fx, fy in ((1, 0), (-1, 0), (0, 1), (0, -1), (0.8, 0.8), (-0.8, 0.8), (0.8, -0.8), (-0.8, -0.8)):
                self._check()
                tu = c + np.array([fx * ring * size[0] / 2, fy * ring * size[1] / 2])  # dove lo voglio, senza lente
                pk_u = undistort_px([pk], c, f_, k)[0]
                d = -(M @ (tu - pk_u))  # spostamento della testa che lo porta lì
                if not (1.0 <= Lk[0] + d[0] <= self.profile.bed_x - 1
                        and 1.0 <= Lk[1] + d[1] <= self.profile.bed_y - 1):
                    continue
                t = distort_px([tu], c, f_, k)[0]  # dove lo vedrò nell'immagine
                if not (half <= t[0] <= size[0] - half and half <= t[1] <= size[1] - half):
                    continue
                Li = self._go_to(Lk[0] + d[0], Lk[1] + d[1])
                p, _f = self._measure(tpl, t, 40 + 60 * ring)
                # dopo il primo anello la previsione è buona: un punto lontano da lei è un riconoscimento sbagliato
                # (sul bordo dell'immagine il puntino è piccolo e storto) e rovinerebbe la misura della lente
                tol = 60.0 if not far else 12.0 + 0.04 * float(np.hypot(*(t - c)))
                if p is None or float(np.hypot(*(np.asarray(p) - t))) > tol:
                    continue
                far.append(p)
                pts.append(np.array(p))
                dls.append(Lk - Li)
            if len(far) >= 4:
                fit0 = solve_matrix(np.array(pts) - pk, dls)
                fit = fit_lens(pts, pk, dls, c, f_)
                # la correzione si tiene solo se migliora davvero (con una lente buona resta 0); un anello che non
                # torna non cancella quello che gli anelli prima hanno già misurato bene
                if fit is not None and fit0[0] is not None and fit[2] < 0.7 * fit0[1] and abs(fit[0]) >= 0.005:
                    k, M, rms_mm = fit
                    kept = len(pts)
                elif fit0[0] is not None and k == 0.0:
                    M, rms_mm = fit0
                    kept = len(pts)
        pk_u = undistort_px([pk], c, math.hypot(*size) / 2.0, k)[0]
        O = np.asarray(self.mark_bed) - Lk - M @ (pk_u - c)
        n_moves = kept
        # centro il puntino sotto il mirino e correggo lo scostamento
        self.progress.emit(6, 7, tr("Porto il puntino sotto il mirino…"))
        model = HeadModel(M, O, size, k=k)
        err = None
        for _ in range(4):
            self._check()
            target = model.head_for_camera(self.mark_bed)
            tx, ty = clamp_to_bed(self.profile, *target)
            if math.hypot(tx - target[0], ty - target[1]) > 0.05:
                break  # la testa non ci arriva (puntino vicino al bordo del piano): resta la stima dei passi
            L = self._go_to(tx, ty)
            pred = model.bed_to_img(L, [self.mark_bed])[0]
            p, _f = self._measure(tpl, pred, 25)
            if p is None:
                break
            self.mark_seen.emit(tuple(p))
            err = math.hypot(p[0] - c[0], p[1] - c[1])
            O = np.asarray(self.mark_bed) - L - M @ (model.undistort([p])[0] - c)
            model = HeadModel(M, O, size, k=k)
            if err <= CENTER_TOL_PX:
                break
        self.progress.emit(7, 7, tr("Fatto"))
        mm_px = model.mm_per_px()
        model.rms_mm = float(rms_mm or 0.0)
        model.rms_px = float(err if err is not None else (rms_mm or 0.0) / max(mm_px, 1e-9))
        model.camera_name = self.camera_name
        model.camera_index = self.camera_index
        model.power_pct = self.power_pct
        msg = tr("Camera della testa calibrata: {0}", model.describe())
        msg += "\n" + tr("Precisione: ±{0:.2f} mm sui {1} spostamenti", model.rms_mm, n_moves)
        if err is not None:
            msg += "\n" + (tr("Il puntino è sotto il mirino (a {0:.1f} pixel).", err) if err <= CENTER_TOL_PX * 2
                           else tr("Il puntino è vicino al mirino ({0:.1f} pixel): ricalibra in un punto più centrale "
                                   "del piano per una precisione migliore.", err))
        return model, msg

    @staticmethod
    def _mark_radius(frame, p):
        """Raggio (pixel) del puntino nell'immagine, per la finestra della sua immagine e per il suo centro."""
        g = gray(frame)
        u, v = int(round(p[0])), int(round(p[1]))
        R = 80
        x0, y0 = max(0, u - R), max(0, v - R)
        sub = cv2.GaussianBlur(g[y0:v + R + 1, x0:u + R + 1], (0, 0), 1.0)
        if sub.size == 0:
            return 10.0
        ring = np.concatenate([sub[0], sub[-1], sub[:, 0], sub[:, -1]])
        dark = np.clip(float(np.median(ring)) - sub, 0, None)
        peak = float(dark[min(v - y0, sub.shape[0] - 1), min(u - x0, sub.shape[1] - 1)])
        if peak < 8:
            return 10.0
        n, labels, stats, _ce = cv2.connectedComponentsWithStats((dark >= 0.4 * peak).astype(np.uint8), 8)
        k = labels[min(v - y0, sub.shape[0] - 1), min(u - x0, sub.shape[1] - 1)]
        if k == 0:
            return 10.0
        return float(min(60.0, max(4.0, math.sqrt(stats[k, cv2.CC_STAT_AREA] / math.pi))))

    def _ask_confirm(self, p):
        """«È questo il puntino inciso?» (cerchiato nel video). -> True / False; Annulla interrompe."""
        self.mark_seen.emit(tuple(p))
        self._confirmed = None
        self._go.clear()
        self._ok_user = False
        self.need_confirm.emit(tuple(p))
        self._go.wait()
        if self._cancel.is_set() or self._confirmed is None:
            raise CalibrationCancelled()
        return self._confirmed

    def _inside(self, L, dx, dy):
        """Lo spostamento (dx, dy) da L, girato dall'altra parte se uscirebbe dal piano."""
        bx, by = self.profile.bed_x, self.profile.bed_y
        if not 1.0 <= L[0] + dx <= bx - 1.0:
            dx = -dx
        if not 1.0 <= L[1] + dy <= by - 1.0:
            dy = -dy
        return dx, dy

    @staticmethod
    def _long_step(pk, Minv, dx, dy, size, cap=12.0, margin=60):
        """Il passo più lungo (mm, fino a cap) per cui il puntino resta dentro l'immagine con margin pixel."""
        best = 0.0
        for s in np.arange(4.0, cap + 0.01, 1.0):
            p = pk + Minv @ np.array([-dx * s, -dy * s])
            if margin <= p[0] <= size[0] - margin and margin <= p[1] <= size[1] - margin:
                best = s
            else:
                break
        return best


class HeadMosaicJob(AutoCam):
    """Foto del piano a mosaico con la camera della testa (thread). Laser sempre spento.
    finished(immagine BGR del piano | None, testo)."""

    def __init__(self, ctl, cam, profile, model, zone, ppm=2.0, overlap=0.3):
        super().__init__(ctl, cam, profile, grid_n=1, method="mosaic")
        self.model = model
        self.zone = zone
        self.ppm = ppm
        self.overlap = overlap
        self.mosaic = Mosaic((profile.bed_x, profile.bed_y), ppm)
        self.skipped = 0

    def positions(self):
        return mosaic_positions(self.zone, self.model.view_mm(), self.overlap)

    def _run(self):
        try:
            pts = self.positions()
            total = len(pts)
            for i, P in enumerate(pts):
                self._check()
                self.progress.emit(i, total, tr("Foto {0} di {1}", i + 1, total))
                target = self.model.head_for_camera(P)
                tx, ty = clamp_to_bed(self.profile, *target)
                mx, my = self.profile.to_machine(tx, ty)
                self.ctl.goto_machine(mx, my, 6000)
                self._wait_idle()
                L = head_on_bed(self.ctl, self.profile)
                frames = self.cam.frames(2, after=time.time() + 0.25)
                if not frames or L is None:
                    self.skipped += 1
                    continue
                self.mosaic.add(cc._avg(frames).astype(np.uint8), self.model, L)
            self.progress.emit(total, total, tr("Fatto"))
            msg = tr("Foto del piano fatta con {0} foto della camera della testa", self.mosaic.count)
            if self.skipped:
                msg += " · " + tr("{0} foto mancanti", self.skipped)
            self.finished.emit(self.mosaic.image(), msg)
        except CalibrationCancelled:
            self.finished.emit(None, tr("Foto del piano annullata"))
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(None, tr("Foto del piano interrotta: {0}", exc))
