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
    """Camera della testa calibrata. Tutte le coordinate del piano in mm (piano come si vede).

    0.20.2: modello generale, usato da tutti i comandi (un solo punto che converte pixel ↔ mm):

        x = (p − c) / f                                 pixel → coordinate normalizzate (f = metà diagonale)
        u = q + (x − q) · (1 + k1·r² + k2·r⁴),  r = |x − q|   lente (q = centro vero della lente)
        X = (A·u + t) / (1 + g·u)                        piano (mm dal laser): scala, rotazione, specchio,
                                                         inclinazione della camera (g, prospettiva)
        P = L + X                                        L = punto del laser sul piano

    e, solo per le camere che NON salgono e scendono con il laser, lo spessore del materiale (vedi thickness):
        X' = N + (X − N) · (D − Δ) / D                   N = punto sotto la camera, D = altezza della camera
                                                         sul cartone della calibrazione, Δ = spessore in più.

    Le calibrazioni della 0.20.0 (M, scostamento O, lente k) sono un caso particolare: A = M·f, t = O, g = 0,
    k1 = k, k2 = 0, q = 0. Si leggono e funzionano come prima."""

    def __init__(self, M=None, offset=None, frame_size=(1280, 720), rms_px=0.0, rms_mm=0.0, created="",
                 camera_name="", camera_index=None, power_pct=None, k=0.0, A=None, t=None, g=None, k2=0.0, q=None):
        self.frame_size = (int(frame_size[0]), int(frame_size[1]))
        if self.frame_size[0] <= 0 or self.frame_size[1] <= 0:
            raise ValueError("dimensione dell'immagine non valida")
        f = self.f
        legacy = A is None
        if legacy:  # modello della 0.20.0
            M = np.array(M, float).reshape(2, 2)
            if not np.all(np.isfinite(M)) or abs(np.linalg.det(M)) < 1e-12:
                raise ValueError("matrice della camera della testa non valida")
            offset = np.array(offset, float).reshape(2)
            A, t, g = M * f, offset, np.zeros(2)
        self.A = np.array(A, float).reshape(2, 2)
        self.t = np.array(t, float).reshape(2)
        self.g = np.zeros(2) if g is None else np.array(g, float).reshape(2)
        self.k1 = float(k or 0.0)
        self.k2 = float(k2 or 0.0)
        self.q = np.zeros(2) if q is None else np.array(q, float).reshape(2)
        for v in (self.A, self.t, self.g, self.q, np.array([self.k1, self.k2])):
            if not np.all(np.isfinite(v)):
                raise ValueError("valori della camera della testa non validi")
        if abs(np.linalg.det(self.A)) < 1e-12:
            raise ValueError("matrice della camera della testa non valida")
        if abs(self.k1) > 0.8 or abs(self.k2) > 0.8 or float(np.hypot(*self.q)) > 0.25 \
                or float(np.hypot(*self.g)) > 0.5:
            raise ValueError("coefficiente della lente non valido")
        self.rms_px = float(rms_px)
        self.rms_mm = float(rms_mm)
        self.created = created or time.strftime("%d/%m/%Y %H:%M")
        self.camera_name = str(camera_name or "")
        self.camera_index = camera_index
        self.power_pct = power_pct
        # 0.20.2: come è stata fatta e quanto è buona
        self.method = "dot" if legacy else "grid"
        self.quality = {}  # p95_px, max_px, rms_px, max_mm, n_ctrl, n_fit, model
        self.backlash = None  # (X, Y) mm: gioco della macchina misurato (solo informazione)
        self.camera_mode = ""  # modo di lettura (dshow-mjpg, msmf…): un altro modo può tagliare l'immagine diversa
        self.autofocus = ""  # "off" spenta da FreeLaserCut, "on" non spegnibile, "" non provato
        self.occluded = []  # [(x0, y0, x1, y1)] pixel coperti da pezzi della macchina (ugello, tubo dell'aria)
        # spessore: None = non si sa, True = la camera sale e scende con il laser (lo spessore non conta)
        self.moves_with_head = None
        self.height_mm = None  # D: altezza della camera sul cartone della calibrazione (camere fisse al carrello)
        self.nadir = None  # N: punto del piano sotto la camera (mm dal laser)
        self.cal_thickness = 0.0  # spessore del cartone della calibrazione (mm)
        self.thickness = None  # spessore del materiale adesso (mm, None = come la calibrazione)
        self._M = np.array(M, float).reshape(2, 2) if M is not None and self.method == "dot" else None
        self._O = np.array(offset, float).reshape(2) if offset is not None and self.method == "dot" else None
        self._refresh()

    def _refresh(self):
        """Valori derivati (centro del mirino, matrice locale): da rifare se cambia lo spessore."""
        self.offset = self._O.copy() if self._O is not None and not self.delta() else \
            self._rel([self.c])[0]
        if self._M is not None and not self.delta():
            self.M = self._M.copy()
        else:
            h = 0.5
            c = self.c
            dx = (self._rel([c + [h, 0]])[0] - self._rel([c - [h, 0]])[0]) / (2 * h)
            dy = (self._rel([c + [0, h]])[0] - self._rel([c - [0, h]])[0]) / (2 * h)
            self.M = np.array([dx, dy]).T
        if not np.all(np.isfinite(self.M)) or abs(np.linalg.det(self.M)) < 1e-12:
            raise ValueError("matrice della camera della testa non valida")
        self.Minv = np.linalg.inv(self.M)

    @property
    def k(self):  # nome della 0.20.0
        return self.k1

    @property
    def c(self):
        return np.array([self.frame_size[0] / 2.0, self.frame_size[1] / 2.0])

    @property
    def f(self):
        return math.hypot(*self.frame_size) / 2.0

    # ---- spessore del materiale
    def delta(self):
        """Spessore in più rispetto al cartone della calibrazione (mm), solo se conta (camera fissa al carrello)."""
        if self.moves_with_head is not False or not self.height_mm or self.thickness is None:
            return 0.0
        return float(self.thickness) - float(self.cal_thickness or 0.0)

    def set_thickness(self, mm):
        """Spessore del materiale adesso (mm, None = come la calibrazione). Fuori limite: il limite (mai in silenzio
        oltre l'altezza della camera)."""
        if mm is not None:
            mm = float(mm)
            if not math.isfinite(mm):
                mm = None
            elif self.height_mm:
                mm = min(max(mm, 0.0), float(self.cal_thickness or 0.0) + 0.8 * float(self.height_mm))
        self.thickness = mm
        self._refresh()
        return mm

    def _height_fix(self, X, inverse=False):
        d = self.delta()
        if not d:
            return X
        D = float(self.height_mm)
        N = np.zeros(2) if self.nadir is None else np.asarray(self.nadir, float)
        s = (D - d) / D
        return N + (X - N) * (1.0 / s if inverse else s)

    # ---- lente
    def undistort_n(self, x):
        """Coordinate normalizzate dell'immagine → «senza lente»."""
        x = np.atleast_2d(np.asarray(x, float))
        if not self.k1 and not self.k2:
            return x
        d = x - self.q
        r2 = (d ** 2).sum(axis=1, keepdims=True)
        return self.q + d * (1 + self.k1 * r2 + self.k2 * r2 * r2)

    def distort_n(self, u, iters=60):
        """Inversa di undistort_n. Punti che con questa lente non possono stare nell'immagine: NaN."""
        u = np.atleast_2d(np.asarray(u, float))
        if not self.k1 and not self.k2:
            return u
        x = u.copy()
        with np.errstate(all="ignore"):
            for _ in range(iters):
                d = x - self.q
                r2 = (d ** 2).sum(axis=1, keepdims=True)
                den = 1 + self.k1 * r2 + self.k2 * r2 * r2
                x = self.q + (u - self.q) / np.where(den > 0.2, den, np.nan)
            bad = ~np.isfinite(x).all(axis=1) | (np.hypot(*(self.undistort_n(x) - u).T) > 0.5 / self.f)
        x[bad] = np.nan
        return x

    def undistort(self, pts):
        """Pixel dell'immagine → pixel «senza lente» (dove sarebbero con una lente perfetta)."""
        p = np.atleast_2d(np.asarray(pts, float))
        return self.c + self.undistort_n((p - self.c) / self.f) * self.f

    def distort(self, pts):
        """Pixel «senza lente» → pixel dell'immagine."""
        p = np.atleast_2d(np.asarray(pts, float))
        return self.c + self.distort_n((p - self.c) / self.f) * self.f

    # ---- conti
    def _rel(self, pts):
        """Pixel → piano (mm) rispetto al laser."""
        x = (np.atleast_2d(np.asarray(pts, float)) - self.c) / self.f
        u = self.undistort_n(x)
        w = 1.0 + u @ self.g
        with np.errstate(all="ignore"):
            X = (u @ self.A.T + self.t) / np.where(w > 0.05, w, np.nan)[:, None]
        return self._height_fix(X)

    def _unrel(self, X):
        """Piano (mm rispetto al laser) → pixel; NaN per i punti che la camera non può vedere."""
        X = self._height_fix(np.atleast_2d(np.asarray(X, float)), inverse=True)
        if not self.g.any():
            u = (X - self.t) @ np.linalg.inv(self.A).T
        else:  # X·(1 + g·u) = A·u + t  →  (A − X·gᵀ)·u = X − t
            Ms = self.A[None, :, :] - X[:, :, None] * self.g[None, None, :]
            with np.errstate(all="ignore"):
                ok = np.abs(np.linalg.det(Ms)) > 1e-12
                u = np.full_like(X, np.nan)
                if ok.any():
                    u[ok] = np.linalg.solve(Ms[ok], (X - self.t)[ok][:, :, None])[:, :, 0]
                u[1.0 + u @ self.g <= 0.05] = np.nan
        return self.c + self.distort_n(u) * self.f

    def img_to_bed(self, head, pts):
        """Pixel → punti del piano (mm) con il laser in head."""
        return np.asarray(head, float) + self._rel(pts)

    def bed_to_img(self, head, pts):
        """Punti del piano (mm) → pixel con il laser in head."""
        return self._unrel(np.atleast_2d(np.asarray(pts, float)) - np.asarray(head, float))

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

    def tilt_deg(self):
        """Inclinazione della camera stimata dalla prospettiva (0 = guarda dritta in basso)."""
        if not self.g.any():
            return 0.0
        # g = variazione relativa della scala per unità normalizzata: con la camera inclinata di θ, g ≈ tan θ / φ,
        # φ = distanza focale in unità normalizzate. Senza φ si dà solo la variazione di scala ai bordi.
        return float(np.hypot(*self.g))

    def view_mm(self):
        """Larghezza e altezza (mm) della zona di piano inquadrata."""
        w, h = self.frame_size
        if self.method == "dot" and not self.k1:
            return (float(np.hypot(*(self.M @ [w, 0]))), float(np.hypot(*(self.M @ [0, h]))))
        a = self._rel([(0, h / 2), (w, h / 2), (w / 2, 0), (w / 2, h)])
        if not np.all(np.isfinite(a)):
            return (float(np.hypot(*(self.M @ [w, 0]))), float(np.hypot(*(self.M @ [0, h]))))
        return (float(np.hypot(*(a[1] - a[0]))), float(np.hypot(*(a[3] - a[2]))))

    def is_occluded(self, pts):
        p = np.atleast_2d(np.asarray(pts, float))
        out = np.zeros(len(p), bool)
        for x0, y0, x1, y1 in self.occluded:
            out |= (p[:, 0] >= x0) & (p[:, 0] < x1) & (p[:, 1] >= y0) & (p[:, 1] < y1)
        return out

    def describe(self):
        ox, oy = self.offset
        txt = tr("{0:.3f} mm per pixel · rotazione {1:.1f}° · scostamento dal laser X {2:+.2f} Y {3:+.2f} mm",
                 self.mm_per_px(), self.angle_deg(), ox, oy)
        if self.mirrored():
            txt += " · " + tr("immagine specchiata")
        if abs(self.k1) >= 0.005 or abs(self.k2) >= 0.005:
            txt += " · " + tr("lente corretta ({0:+.0f}% ai bordi)", (self.k1 + self.k2) * 100)
        if self.g.any() and self.tilt_deg() >= 0.002:
            txt += " · " + tr("inclinazione corretta")
        qd = self.quality or {}
        if qd.get("max_mm") is not None:
            txt += " · " + tr("errore massimo {0:.2f} mm", qd["max_mm"])
        return txt

    # ---- file
    def to_dict(self):
        d = {"version": 2 if self.method == "grid" else 1,
             # sempre anche i campi della 0.20.0: una versione vecchia legge il file (con la stima al centro)
             "M": self.M.tolist(), "offset": self.offset.tolist(), "frame_size": list(self.frame_size),
             "rms_px": self.rms_px, "rms_mm": self.rms_mm, "created": self.created,
             "camera_name": self.camera_name, "camera_index": self.camera_index, "power_pct": self.power_pct,
             "k": self.k1}
        if self.method == "grid":
            d.update({"A": self.A.tolist(), "t": self.t.tolist(), "g": self.g.tolist(), "k1": self.k1,
                      "k2": self.k2, "q": self.q.tolist(), "quality": dict(self.quality),
                      "backlash": None if self.backlash is None else list(self.backlash),
                      "camera_mode": self.camera_mode, "autofocus": self.autofocus,
                      "occluded": [list(map(float, r)) for r in self.occluded],
                      "moves_with_head": self.moves_with_head, "height_mm": self.height_mm,
                      "nadir": None if self.nadir is None else list(map(float, self.nadir)),
                      "cal_thickness": self.cal_thickness})
        return d

    @classmethod
    def from_dict(cls, d):
        if int(d.get("version", 1)) >= 2 and "A" in d:
            m = cls(None, None, d["frame_size"], d.get("rms_px", 0.0), d.get("rms_mm", 0.0), d.get("created", ""),
                    d.get("camera_name", ""), d.get("camera_index"), d.get("power_pct"), d.get("k1", 0.0),
                    A=d["A"], t=d["t"], g=d.get("g"), k2=d.get("k2", 0.0), q=d.get("q"))
            m.method = "grid"
            m.quality = dict(d.get("quality") or {})
            bl = d.get("backlash")
            m.backlash = None if bl is None else (float(bl[0]), float(bl[1]))
            m.camera_mode = str(d.get("camera_mode") or "")
            m.autofocus = str(d.get("autofocus") or "")
            m.occluded = [tuple(float(v) for v in r[:4]) for r in (d.get("occluded") or []) if len(r) >= 4]
            mw = d.get("moves_with_head")
            m.moves_with_head = mw if mw in (True, False) else None
            hm = d.get("height_mm")
            m.height_mm = float(hm) if hm and math.isfinite(float(hm)) and float(hm) > 0 else None
            nd = d.get("nadir")
            m.nadir = None if nd is None else np.array(nd, float).reshape(2)
            m.cal_thickness = float(d.get("cal_thickness") or 0.0)
            m._refresh()
            return m
        return cls(d["M"], d["offset"], d["frame_size"], d.get("rms_px", 0.0), d.get("rms_mm", 0.0),
                   d.get("created", ""), d.get("camera_name", ""), d.get("camera_index"), d.get("power_pct"),
                   d.get("k", 0.0))

    def copy(self):
        m = HeadModel.from_dict(self.to_dict())
        m.thickness = self.thickness
        m._refresh()
        return m

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
        except (OSError, ValueError, KeyError, TypeError, IndexError, np.linalg.LinAlgError):
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


def frame_ok(frame):
    """Fotogramma rovinato (due camere sulla stessa porta USB: righe ripetute, metà nera)? -> (True, "") o (False,
    perché). 0.20.2."""
    if frame is None:
        return False, tr("nessuna immagine")
    g = gray(frame)
    h = g.shape[0]
    rows = np.abs(np.diff(g[:, ::4], axis=0)).mean(axis=1)
    run = best = 0
    for s in rows < 0.05:
        run = run + 1 if s else 0
        best = max(best, run)
    if best > 0.12 * h:
        return False, tr("righe ripetute")
    top, bottom = float(g[: h // 2].mean()), float(g[h // 2:].mean())
    if min(top, bottom) < 6 and max(top, bottom) > 40:
        return False, tr("metà immagine nera")
    return True, ""


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
    piano).

    0.20.2 (mosaico preciso): ogni punto del piano viene dalla foto in cui è più vicino al centro dell'immagine (dove
    la calibrazione è migliore), con una sfumatura stretta nelle giunte: niente più media fra due foto sfasate (linee
    doppie). Ogni foto si incolla con il modello completo (lente e inclinazione). Dove c'è qualcosa da riconoscere la
    foto si aggiusta di al massimo 1 mm sulle vicine, solo se la posizione migliore è una sola (nido d'ape e carta a
    quadretti non ingannano); sul materiale liscio conta solo la calibrazione. Le zone coperte da pezzi della macchina
    non si usano; dove nessuna foto arriva si vede un tratteggio, mai un nero che sembri materiale."""

    BAND = 0.06  # larghezza della sfumatura nelle giunte (frazione di metà immagine)
    ALIGN_MM = 1.0  # aggiustamento massimo delle giunte

    def __init__(self, bed, ppm=4.0):
        self.bed = (float(bed[0]), float(bed[1]))
        self.ppm = float(ppm)
        self.W, self.H = int(round(self.bed[0] * ppm)), int(round(self.bed[1] * ppm))
        self.img = np.zeros((self.H, self.W, 3), np.float32)
        self.best = np.full((self.H, self.W), -np.inf, np.float32)
        self.count = 0
        self.shifts = []  # aggiustamenti fatti (mm)
        self.bad_seams = []  # giunte che non combaciano: (x, y) sul piano

    # ---- conti
    def to_px(self, X):
        X = np.atleast_2d(np.asarray(X, float))
        return np.stack([X[:, 0] * self.ppm, (self.bed[1] - X[:, 1]) * self.ppm], axis=1)

    def window(self, model, head):
        """Righe e colonne della foto del piano che la foto con il laser in head può coprire."""
        w, h = model.frame_size
        s = np.linspace(0, 1, 25)
        border = np.concatenate([np.stack([s * w, np.zeros_like(s)], 1), np.stack([s * w, np.full_like(s, h)], 1),
                                 np.stack([np.zeros_like(s), s * h], 1), np.stack([np.full_like(s, w), s * h], 1)])
        B = model.img_to_bed(head, border)
        B = B[np.isfinite(B).all(axis=1)]
        if not len(B):
            return None
        q = self.to_px(B)
        c0, c1 = int(max(0, math.floor(q[:, 0].min()) - 1)), int(min(self.W, math.ceil(q[:, 0].max()) + 1))
        r0, r1 = int(max(0, math.floor(q[:, 1].min()) - 1)), int(min(self.H, math.ceil(q[:, 1].max()) + 1))
        if c1 - c0 < 2 or r1 - r0 < 2:
            return None
        return r0, r1, c0, c1

    def _warp(self, frame, model, head, win):
        r0, r1, c0, c1 = win
        yy, xx = np.mgrid[r0:r1, c0:c1].astype(np.float64)
        X = np.stack([(xx.ravel() + 0.5) / self.ppm, self.bed[1] - (yy.ravel() + 0.5) / self.ppm], axis=1)
        P = model.bed_to_img(head, X)
        w, h = model.frame_size
        ok = np.isfinite(P).all(axis=1)
        ok &= (P[:, 0] >= 0) & (P[:, 0] <= w - 1) & (P[:, 1] >= 0) & (P[:, 1] <= h - 1)
        if model.occluded:
            ok &= ~model.is_occluded(np.where(np.isfinite(P), P, -1))
        Pc = np.where(ok[:, None], P, -1.0)
        mx = Pc[:, 0].reshape(r1 - r0, c1 - c0).astype(np.float32)
        my = Pc[:, 1].reshape(r1 - r0, c1 - c0).astype(np.float32)
        img = cv2.remap(np.asarray(frame).astype(np.float32), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                        borderValue=(0, 0, 0))
        du = np.abs(Pc[:, 0] - w / 2) / (w / 2)
        dv = np.abs(Pc[:, 1] - h / 2) / (h / 2)
        score = (1 - np.maximum(du, dv)).reshape(r1 - r0, c1 - c0).astype(np.float32)
        score[~ok.reshape(r1 - r0, c1 - c0)] = -np.inf
        return img, score

    def _align(self, img, score, win):
        """Piccolo spostamento (mm) della foto nuova che la fa combaciare con quelle già messe, oppure None."""
        r0, r1, c0, c1 = win
        have = np.isfinite(self.best[r0:r1, c0:c1]) & np.isfinite(score)
        if have.sum() < 400:
            return None, None
        ys, xs = np.nonzero(have)
        a0, a1, b0, b1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        R = int(math.ceil(self.ALIGN_MM * self.ppm)) + 1
        if a1 - a0 < 4 * R or b1 - b0 < 4 * R:
            return None, None
        old = cv2.cvtColor(self.img[r0:r1, c0:c1][a0:a1, b0:b1], cv2.COLOR_BGR2GRAY)
        new = cv2.cvtColor(img[a0:a1, b0:b1], cv2.COLOR_BGR2GRAY)
        m = have[a0:a1, b0:b1]
        if float(old[m].std()) < 6 or float(new[m].std()) < 6:
            return None, None  # materiale liscio: niente da riconoscere, vale la calibrazione
        tpl = new[R:-R, R:-R]
        if float(tpl.std()) < 6 or not m[R:-R, R:-R].all():
            # la parte in comune non è un rettangolo pieno: uso il rettangolo pieno più grande al centro
            return None, None
        res = cv2.matchTemplate(old, tpl, cv2.TM_CCOEFF_NORMED)
        _mn, best, _ml, (bx, by) = cv2.minMaxLoc(res)
        quality = float(res[R, R])  # senza spostamento
        mask = np.ones_like(res, bool)
        mask[max(0, by - 1):by + 2, max(0, bx - 1):bx + 2] = False
        second = float(res[mask].max()) if mask.any() else -1.0
        if best < 0.6 or best - second < 0.05 or bx in (0, res.shape[1] - 1) or by in (0, res.shape[0] - 1):
            return None, quality

        def sub(a, b, c_):
            d = a - 2 * b + c_
            return 0.0 if abs(d) < 1e-9 else 0.5 * (a - c_) / d

        dx = bx - R + sub(res[by, bx - 1], res[by, bx], res[by, bx + 1])
        dy = by - R + sub(res[by - 1, bx], res[by, bx], res[by + 1, bx])
        mm = np.array([dx / self.ppm, -dy / self.ppm])
        if float(np.hypot(*mm)) > self.ALIGN_MM or float(np.hypot(*mm)) < 0.5 / self.ppm:
            return None, quality
        return mm, best

    def add(self, frame, model, head, align=True):
        head = np.asarray(head, float)
        win = self.window(model, head)
        if win is None:
            return False
        img, score = self._warp(frame, model, head, win)
        if not np.isfinite(score).any():
            return False
        if align and self.count:
            mm, q = self._align(img, score, win)
            if mm is not None:  # il contenuto va spostato di mm: come se la testa fosse lì
                self.shifts.append((float(mm[0]), float(mm[1])))
                img, score = self._warp(frame, model, head + mm, win)
            elif q is not None and q < 0.4:
                r0, r1, c0, c1 = win
                self.bad_seams.append(((c0 + c1) / 2 / self.ppm, self.bed[1] - (r0 + r1) / 2 / self.ppm))
        r0, r1, c0, c1 = win
        best = self.best[r0:r1, c0:c1]
        cur = self.img[r0:r1, c0:c1]
        b = self.BAND
        take = score > best + b
        mix = np.isfinite(score) & ~take & (score >= best - b)
        cur[take] = img[take]
        if mix.any():
            tt = ((score[mix] - best[mix] + b) / (2 * b))[:, None]
            cur[mix] = cur[mix] * (1 - tt) + img[mix] * tt
        np.maximum(best, np.where(np.isfinite(score), score, -np.inf), out=best)
        self.count += 1
        return True

    def covered(self):
        return np.isfinite(self.best)

    def image(self, back=(46, 40, 34)):
        out = np.clip(self.img, 0, 255).astype(np.uint8)
        miss = ~np.isfinite(self.best)
        if miss.any():  # zona non fotografata: tratteggio, non un colore che sembri materiale
            yy, xx = np.mgrid[0:self.H, 0:self.W]
            stripe = ((xx + yy) // max(2, int(3 * self.ppm))) % 2 == 0
            hatch = np.empty((self.H, self.W, 3), np.uint8)
            hatch[:] = back
            hatch[stripe] = (70, 62, 54)
            out[miss] = hatch[miss]
        return out


# ======================================================================= camera simulata
class SimHeadCamera(_FrameSource):
    """Camera virtuale fissata alla testa del simulatore: vede un pezzo di materiale con una trama (come il legno o il
    cartone) attorno al punto L + O. Serve alle prove automatiche: modello vero noto (true_model)."""

    PPM = 8.0  # pixel per mm della trama del materiale

    def __init__(self, sim, offset=(0.0, 35.0), mm_per_px=0.08, angle=0.0, mirror=False, size=(640, 480), seed=3,
                 board=None, profile=None, lag=0.0, k=0.0, model=None, light=1.0, gradient=0.0, occlude=None,
                 spots=None, grain=0.0, moves=True, drift=None, corrupt_every=0, dot_r=0.3):
        self.index = "sim-testa"
        self.lag = float(lag)  # come le camere vere: fotogrammi che arrivano in ritardo (secondi)
        self._queue = []
        self.black = False
        self.mode = "sim"
        self.autofocus = ""
        self.sim = sim
        self.profile = profile
        self.w, self.h = size
        # 0.20.2: una camera vera qualsiasi (head_grid.camera_model: inclinata, lente a due coefficienti, centro
        # spostato, altezza); senza, la camera dritta della 0.20.0
        self.true = model if model is not None else HeadModel(natural_matrix(mm_per_px, angle, mirror), offset, size,
                                                              k=k)
        self.light = float(light)  # 1 = normale; 0,15 = buio
        self.gradient = float(gradient)  # luce non uniforme: da un lato all'altro dell'immagine ±gradient
        self.occlude = occlude or []  # [(x0, y0, x1, y1, grigio)] pezzi della macchina fissi nell'immagine
        self.moves = bool(moves)  # la camera sale e scende con il laser
        self.material_z = 0.0  # cartone sollevato (mm): conta solo se la camera non sale con il laser
        self.material_shift = np.zeros(2)  # cartone spostato sul piano (mm)
        self.drift = drift  # (dopo quanti secondi, scala): messa a fuoco automatica che cambia l'inquadratura
        self.corrupt_every = int(corrupt_every)  # un fotogramma rovinato ogni n
        self.dot_r = float(dot_r)  # mm: raggio della bruciatura di ogni punto inciso
        self._n_grab = 0
        self._t0 = time.time()
        self.slip = np.zeros(2)  # passi persi: la testa vera è spostata da dove dice la scheda (mm)
        self._R = None
        self._R_key = None
        self._und = None
        if model is None and k:  # pixel dell'immagine → pixel «senza lente», una volta sola
            yy, xx = np.mgrid[0:size[1], 0:size[0]].astype(np.float64)
            self._und = self.true.undistort(np.stack([xx.ravel(), yy.ravel()], axis=1))
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
        if grain:  # venatura del legno: righe scure lunghe e sottili
            yy = np.arange(th, dtype=np.float32)[:, None]
            xx = np.arange(tw, dtype=np.float32)[None, :]
            waves = np.sin(yy / (1.7 * self.PPM) + 0.8 * np.sin(xx / (31 * self.PPM))) ** 8
            base = np.clip(base.astype(np.float32) - grain * 60 * waves, 0, 255).astype(np.uint8)
        for (sx, sy, sr) in (spots or []):  # macchie sul materiale (non sono puntini: grandi o storte)
            cv2.ellipse(base, (int(sx * self.PPM), int(th - sy * self.PPM)),
                        (int(sr * self.PPM), int(sr * 0.45 * self.PPM)), 25, 0, 360, 70, -1, cv2.LINE_AA)
        self.material = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
        self._marks_done = 0
        super().__init__()

    def _rel_map(self):
        """Per ogni pixel, il punto del piano (mm dal laser): una volta sola per ogni altezza del cartone."""
        z = self.material_z if not self.moves else 0.0
        key = round(float(z), 4)
        if self._R is None or self._R_key != key:
            m = self.true
            if z:
                m = m.copy()
                m.moves_with_head = False
                m.cal_thickness = 0.0
                m.set_thickness(z)
            yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float64)
            self._R = m._rel(np.stack([xx.ravel(), yy.ravel()], axis=1))
            self._R_key = key
        return self._R

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
            x, y = x - self.material_shift[0], y - self.material_shift[1]  # sul cartone, che può essere spostato
            cv2.circle(self.material, (int(round(x * self.PPM)), int(round(th - y * self.PPM))),
                       max(1, int(round(self.dot_r * self.PPM))), (40, 44, 50), -1, cv2.LINE_AA)
            self._marks_done += 1
        L = self.head() + self.slip
        m = self.true
        k = self.PPM
        base = L + m.offset - m.M @ m.c
        A = np.array([[k * m.M[0, 0], k * m.M[0, 1], k * base[0]],
                      [-k * m.M[1, 0], -k * m.M[1, 1], k * (self.bed[1] - base[1])]])
        general = m.method == "grid" or self.material_z or self.material_shift.any()
        if general:
            R = self._rel_map()
            X = L + R - self.material_shift
            sx = (X[:, 0] * k).reshape(self.h, self.w).astype(np.float32)
            sy = (th - X[:, 1] * k).reshape(self.h, self.w).astype(np.float32)
            sx[~np.isfinite(sx)] = -10
            sy[~np.isfinite(sy)] = -10
            img = cv2.remap(self.material, sx, sy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                            borderValue=(20, 20, 20))
        elif self._und is None:
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
        img = img.astype(np.float32)
        if self.light != 1.0 or self.gradient:
            gx = np.linspace(-1, 1, self.w, dtype=np.float32)[None, :, None]
            img = img * self.light * (1 + self.gradient * gx)
        for x0, y0, x1, y1, val in self.occlude:
            img[int(y0):int(y1), int(x0):int(x1)] = val
            img[int(y0):int(y1):6, int(x0):int(x1)] = val * 0.5  # con un disegno: non è uniforme
        if self.drift is not None and time.time() - self._t0 > self.drift[0]:
            s = float(self.drift[1])
            Ad = cv2.getRotationMatrix2D((self.w / 2, self.h / 2), 0, s)
            img = cv2.warpAffine(img, Ad, (self.w, self.h), borderMode=cv2.BORDER_REPLICATE)
        noise = self.rng.normal(0, 1.5, img.shape) * (1.0 if self.light >= 0.5 else 4.0)
        out = np.clip(img + noise, 0, 255).astype(np.uint8)
        self._n_grab += 1
        if self.corrupt_every and self._n_grab % self.corrupt_every == 0:
            out[self.h // 3:] = out[self.h // 3]  # righe ripetute (USB senza banda)
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

    def _p(self, i, n, text):
        self.progress.emit(i, n, text)

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
        frames = []
        for _try in range(3):  # 0.20.2: senza i fotogrammi rovinati (USB senza banda), che sembrerebbero «macchie»
            got = self.cam.frames(n, after=time.time() + 0.05)
            if not got:
                break
            frames += [f for f in got if frame_ok(f)[0]]
            if len(frames) >= n:
                break
        if len(frames) < max(1, n - 1):
            raise RuntimeError(tr("la camera della testa non sta inviando immagini"))
        return frames[:n]

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
        except BaseException:
            if not done.is_set() and self.ctl.connected:  # 0.20.2: annullata a metà: il lavoro si ferma davvero
                try:
                    self.ctl.stop_job()
                except Exception:  # noqa: BLE001
                    pass
            raise
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
        return self._calibrate_dot()

    def _calibrate_dot(self, quick=False):
        """La calibrazione col puntino. quick=True (0.20.2, prima fase della calibrazione completa): si ferma dopo la
        misura di scala e rotazione e rende {M, O, size, Lk, pk, frame} invece del modello."""
        self._check()
        size = tuple(self.cam.size) if self.cam.size and self.cam.size[0] else None
        L0 = self._head()
        self.mark_bed = tuple(L0)
        self._p(0, 7, tr("Guardo il materiale (laser spento)…"))
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
            self._p(0, 7, tr("Foto del materiale prima del puntino ({0} di {1})…", i + 1, len(cands)))
            self.before_at.append(tuple(self._go_to(*(L0 - g))))
            befores.append(self._shot(3))
        self._go_to(*L0)
        self._p(1, 7, tr("Incido il puntino al {0:.0f}%…", self.power_pct))
        self._burn_mark(L0)
        self._check()
        pk = None
        for i, g in enumerate(cands):
            self._check()
            if i:
                self._p(2, 7, tr("Cerco il puntino ({0} di {1})…", i + 1, len(cands)))
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
            self._p(2, 7, tr("Il puntino non è nell'inquadratura"))
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
        self._p(3, 7, tr("Seguo il puntino spostando la testa…"))
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
        self._p(4, 7, tr("Porto il puntino al centro dell'immagine…"))
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
        self._p(5, 7, tr("Misuro scala e rotazione…"))
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
        if quick:
            O = np.asarray(self.mark_bed) - Lk - M @ (pk - c)
            return {"M": M, "O": O, "size": tuple(size), "Lk": Lk, "pk": pk, "rms_mm": rms_mm}
        # D) il puntino verso i bordi dell'immagine, un anello alla volta: misura la lente (i grandangoli stringono i
        # bordi). Dopo ogni anello lente e matrice si ricalcolano, così l'anello dopo si prevede bene anche con una
        # lente molto storta
        self._p(5, 7, tr("Misuro la lente verso i bordi dell'immagine…"))
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
        self._p(6, 7, tr("Porto il puntino sotto il mirino…"))
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
        self._p(7, 7, tr("Fatto"))
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

    def __init__(self, ctl, cam, profile, model, zone, ppm=4.0, overlap=0.3):
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
                # 0.20.2: sempre dalla stessa parte (gioco delle cinghie), poi foto a macchina ferma
                ax, ay = clamp_to_bed(self.profile, tx - 1.5, ty - 1.5)
                amx, amy = self.profile.to_machine(ax, ay)
                self.ctl.goto_machine(amx, amy, 6000)
                self.ctl.goto_machine(mx, my, 3000)
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
            if self.mosaic.bad_seams:
                msg += "\n" + tr("In {0} giunte le foto non combaciano: il materiale non è piatto o la calibrazione "
                                 "va controllata («Controlla» nella vista della testa).", len(self.mosaic.bad_seams))
            self.finished.emit(self.mosaic.image(), msg)
        except CalibrationCancelled:
            self.finished.emit(None, tr("Foto del piano annullata"))
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(None, tr("Foto del piano interrotta: {0}", exc))
