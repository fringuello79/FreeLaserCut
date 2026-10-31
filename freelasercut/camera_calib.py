# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Matematica della calibrazione camera di FreeLaserCut ("AutoCam").

Modello: piano del letto (mm) -> immagine (px) =
    omografia H (prospettiva)  +  correzione polinomiale cubica (distorsione della lente).
Un solo set di punti noti (puntini laser o puntini incisi) basta per stimare
entrambe le cose: niente scacchiere, niente pose multiple.
La precisione è stimata con la validazione "leave-one-out": ogni punto è
predetto da un modello che non lo ha visto.
"""
import json
import math
import time

import cv2
import numpy as np
from freelasercut.i18n import tr  # noqa: E402


def _basis(s, t, order):
    cols = [np.ones_like(s), s, t]
    if order >= 2:
        cols += [s * s, s * t, t * t]
    if order >= 3:
        cols += [s ** 3, s * s * t, s * t * t, t ** 3]
    return np.stack(cols, axis=1)


def _order_for(n):
    if n >= 16:
        return 3
    if n >= 9:
        return 2
    return 0


class CameraModel:
    def __init__(self, H, coef, order, center, scale, bed, frame_size, rms_mm=None, max_mm=None, n_points=0,
                 k=(0.0, 0.0)):
        self.k = tuple(float(v) for v in k)
        w, h = frame_size
        self.c = np.array([w / 2.0, h / 2.0])
        self.f = max(math.hypot(w / 2.0, h / 2.0), 1.0)
        self.H = np.asarray(H, dtype=float)
        self.coef = np.asarray(coef, dtype=float) if coef is not None else None  # (k, 2)
        self.order = int(order)
        self.center = np.asarray(center, dtype=float)
        self.scale = np.asarray(scale, dtype=float)
        self.bed = tuple(bed)
        self.frame_size = tuple(frame_size)  # (w, h)
        self.rms_mm = rms_mm
        self.max_mm = max_mm
        self.n_points = n_points
        self.created = time.strftime("%Y-%m-%d %H:%M")
        self._maps = {}
        self.H_inv = np.linalg.inv(self.H)
        self.valid = None  # (x, y, w, h) in mm: zona del piano calibrata e vista dalla camera (None = tutto)

    # ---------------------------------------------------------------- mappe
    def _corr(self, bed_pts):
        if self.coef is None or self.order == 0:
            return np.zeros_like(bed_pts)
        st = (bed_pts - self.center) / self.scale
        return _basis(st[:, 0], st[:, 1], self.order) @ self.coef

    def bed_to_img(self, bed_pts):
        bed_pts = np.atleast_2d(np.asarray(bed_pts, dtype=float))
        p = cv2.perspectiveTransform(bed_pts.reshape(-1, 1, 2), self.H).reshape(-1, 2)
        return _distort(p + self._corr(bed_pts), self.c, self.f, self.k)

    def img_to_bed(self, img_pts, iters=8):
        img_pts = _undistort(np.atleast_2d(np.asarray(img_pts, dtype=float)), self.c, self.f, self.k)
        b = cv2.perspectiveTransform(img_pts.reshape(-1, 1, 2), self.H_inv).reshape(-1, 2)
        for _ in range(iters):
            target = img_pts - self._corr(b)
            b = cv2.perspectiveTransform(target.reshape(-1, 1, 2), self.H_inv).reshape(-1, 2)
        return b

    def rectify(self, frame, px_per_mm=2.0):
        """Foto vista dall'alto, 1:1 col piano: riga 0 = Y massimo, colonna 0 = X 0."""
        key = (frame.shape[1], frame.shape[0], px_per_mm)
        if key not in self._maps:
            bx, by = self.bed
            w, h = int(round(bx * px_per_mm)), int(round(by * px_per_mm))
            jj, ii = np.meshgrid(np.arange(w), np.arange(h))
            xs = (jj + 0.5) / px_per_mm
            ys = by - (ii + 0.5) / px_per_mm
            pts = np.stack([xs.ravel(), ys.ravel()], axis=1)
            img = self.bed_to_img(pts)
            mx = img[:, 0].reshape(h, w).astype(np.float32)
            my = img[:, 1].reshape(h, w).astype(np.float32)
            if self.valid is not None:  # fuori dalla zona calibrata niente immagine (la correzione lì non vale)
                vx, vy, vw, vh = self.valid
                out = (xs < vx) | (xs > vx + vw) | (ys < vy) | (ys > vy + vh)
                mx[out] = -1
                my[out] = -1
            self._maps = {key: (mx, my)}
        mx, my = self._maps[key]
        return cv2.remap(frame, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(34, 26, 15))

    # ---------------------------------------------------------------- file
    def to_dict(self):
        return {
            "version": 1, "H": self.H.tolist(), "coef": None if self.coef is None else self.coef.tolist(),
            "order": self.order, "center": self.center.tolist(), "scale": self.scale.tolist(),
            "bed": list(self.bed), "frame_size": list(self.frame_size), "rms_mm": self.rms_mm,
            "max_mm": self.max_mm, "n_points": self.n_points, "created": self.created, "k": list(self.k),
            "valid": None if self.valid is None else [float(v) for v in self.valid],
        }

    @classmethod
    def from_dict(cls, d):
        m = cls(d["H"], d["coef"], d["order"], d["center"], d["scale"], d["bed"], d["frame_size"],
                d.get("rms_mm"), d.get("max_mm"), d.get("n_points", 0), d.get("k", (0.0, 0.0)))
        m.created = d.get("created", m.created)
        m.valid = tuple(d["valid"]) if d.get("valid") else None
        return m

    def save(self, path, extra=None):
        data = self.to_dict()
        data.update(extra or {})
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return cls.from_dict(d), d


def _undistort(p, c, f, k):
    """Pixel reale (con lente) -> pixel 'ideale' (senza lente). Modello radiale k1, k2."""
    if not any(k):
        return p
    x = (p - c) / f
    r2 = (x * x).sum(axis=1, keepdims=True)
    return c + x * (1 + k[0] * r2 + k[1] * r2 * r2) * f


def _distort(u, c, f, k, iters=25):
    """Inverso di _undistort (punto fisso)."""
    if not any(k):
        return u
    xu = (u - c) / f
    x = xu.copy()
    for _ in range(iters):
        r2 = (x * x).sum(axis=1, keepdims=True)
        x = xu / (1 + k[0] * r2 + k[1] * r2 * r2)
    return c + x * f


def _homography_residual(bed_pts, img_pts, c, f, k):
    u = _undistort(img_pts, c, f, k)
    H, _ = cv2.findHomography(bed_pts, u, 0)
    if H is None:
        return 1e18, None
    pred = cv2.perspectiveTransform(bed_pts.reshape(-1, 1, 2), H).reshape(-1, 2)
    return float(((pred - u) ** 2).sum()), H


def estimate_lens(bed_pts, img_pts, frame_size):
    """Stima k1, k2 della lente: cerca i valori per cui i punti tornano 'su un piano' (omografia perfetta)."""
    w, h = frame_size
    c = np.array([w / 2.0, h / 2.0])
    f = max(math.hypot(w / 2.0, h / 2.0), 1.0)
    best_k, best_e = (0.0, 0.0), _homography_residual(bed_pts, img_pts, c, f, (0.0, 0.0))[0]
    for k1 in np.linspace(-0.6, 0.6, 61):
        e = _homography_residual(bed_pts, img_pts, c, f, (k1, 0.0))[0]
        if e < best_e:
            best_k, best_e = (float(k1), 0.0), e
    step1, step2 = 0.02, 0.05
    use_k2 = len(bed_pts) >= 12
    for _ in range(40):
        improved = False
        cands = [(best_k[0] + d1, best_k[1] + d2) for d1 in (-step1, 0, step1)
                 for d2 in ((-step2, 0, step2) if use_k2 else (0,))]
        for kk in cands:
            e = _homography_residual(bed_pts, img_pts, c, f, kk)[0]
            if e < best_e - 1e-12:
                best_k, best_e, improved = kk, e, True
        if not improved:
            step1 /= 2
            step2 /= 2
            if step1 < 1e-5:
                break
    return best_k


def fit(bed_pts, img_pts, bed, frame_size, order=None, ridge=1e-4):
    bed_pts = np.asarray(bed_pts, dtype=float)
    img_pts = np.asarray(img_pts, dtype=float)
    n = len(bed_pts)
    if n < 4:
        raise ValueError(tr("servono almeno 4 punti"))
    k = estimate_lens(bed_pts, img_pts, frame_size) if n >= 8 else (0.0, 0.0)
    w, h = frame_size
    c = np.array([w / 2.0, h / 2.0])
    f = max(math.hypot(w / 2.0, h / 2.0), 1.0)
    img_pts = _undistort(img_pts, c, f, k)  # da qui in poi: pixel ideali
    order_pref = None if order is None else order
    bed_pts = np.asarray(bed_pts, dtype=float)
    img_pts = np.asarray(img_pts, dtype=float)
    n = len(bed_pts)
    if n < 4:
        raise ValueError(tr("servono almeno 4 punti"))
    H, _ = cv2.findHomography(bed_pts, img_pts, 0)
    if H is None:
        raise ValueError(tr("punti non validi (allineati?)"))
    order = (2 if n >= 16 else 0) if order_pref is None else min(order_pref, 2)
    center = bed_pts.mean(axis=0)
    scale = np.maximum(bed_pts.std(axis=0), 1.0)
    coef = None
    if order > 0:
        pred = cv2.perspectiveTransform(bed_pts.reshape(-1, 1, 2), H).reshape(-1, 2)
        resid = img_pts - pred
        st = (bed_pts - center) / scale
        A = _basis(st[:, 0], st[:, 1], order)
        coef = np.linalg.solve(A.T @ A + ridge * np.eye(A.shape[1]), A.T @ resid)
        # secondo giro: ristimo H sui punti "senza lente" per separare meglio le due cose
        corrected = img_pts - A @ coef
        H2, _ = cv2.findHomography(bed_pts, corrected, 0)
        if H2 is not None:
            H = H2
            pred = cv2.perspectiveTransform(bed_pts.reshape(-1, 1, 2), H).reshape(-1, 2)
            coef = np.linalg.solve(A.T @ A + ridge * np.eye(A.shape[1]), A.T @ (img_pts - pred))
    return CameraModel(H, coef, order, center, scale, bed, frame_size, n_points=n, k=k)


def fit_with_validation(bed_pts, img_pts, bed, frame_size):
    """Modello finale + errore leave-one-out in mm (rms, max)."""
    bed_pts = np.asarray(bed_pts, dtype=float)
    img_pts = np.asarray(img_pts, dtype=float)
    model = fit(bed_pts, img_pts, bed, frame_size)
    n = len(bed_pts)
    errs = []
    if n >= 6:
        for i in range(n):
            keep = np.arange(n) != i
            try:
                m = fit(bed_pts[keep], img_pts[keep], bed, frame_size, order=2 if n - 1 >= 16 else 0)
            except ValueError:
                continue
            p = m.img_to_bed(img_pts[i:i + 1])[0]
            errs.append(math.dist(p, bed_pts[i]))
    if errs:
        e = np.array(errs)
        model.rms_mm = float(np.sqrt((e ** 2).mean()))
        model.max_mm = float(e.max())
    else:
        p = model.img_to_bed(img_pts)
        e = np.linalg.norm(p - bed_pts, axis=1)
        model.rms_mm = float(np.sqrt((e ** 2).mean()))
        model.max_mm = float(e.max())
    return model


# --------------------------------------------------------------------- rilevamento
def _avg(frames):
    return np.mean(np.stack([f.astype(np.float32) for f in frames]), axis=0)


def detect_spot(off_frames, on_frames, min_peak=22.0):
    """Puntino laser: differenza (acceso - spento), pesata sul canale blu (450 nm).
    Ritorna ((u, v), forza) oppure (None, forza)."""
    off, on = _avg(off_frames), _avg(on_frames)
    d = on - off
    score = 0.6 * d[..., 0] + 0.2 * d[..., 1] + 0.2 * d[..., 2]
    score = cv2.GaussianBlur(np.clip(score, 0, None), (0, 0), 2.0)
    peak = float(score.max())
    if peak < min_peak:
        return None, peak
    mask = (score >= peak * 0.45).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best, best_sum = None, 0.0
    for k in range(1, n):
        s = float(score[labels == k].sum())
        if s > best_sum:
            best, best_sum = k, s
    if best is None:
        return None, peak
    ys, xs = np.nonzero(labels == best)
    w = score[ys, xs]
    return (float((xs * w).sum() / w.sum()), float((ys * w).sum() / w.sum())), peak


def find_dark_blobs(before_frames, after_frames, min_area=3):
    """Macchie comparse fra 'prima' e 'dopo' (scurimento): [(u, v, intensità)]."""
    before, after = _avg(before_frames), _avg(after_frames)
    dark = cv2.cvtColor(np.clip(before - after, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
    dark = cv2.GaussianBlur(dark, (0, 0), 1.2)
    ref = float(np.percentile(dark, 99.95))
    thr = max(15.0, 0.3 * ref)
    mask = (dark >= thr).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    blobs = []
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] < min_area:
            continue
        x, y, w, h = stats[k, :4]
        sub = labels[y:y + h, x:x + w] == k
        wt = dark[y:y + h, x:x + w] * sub
        tot = float(wt.sum())
        ys, xs = np.mgrid[y:y + h, x:x + w]
        blobs.append((float((xs * wt).sum() / tot), float((ys * wt).sum() / tot), tot))
    return blobs


def match_grid(blobs, expected_img, grid_bed, spacing_px):
    """Associa le macchie ai punti attesi. La stima iniziale può essere spostata
    (la testa sta più in alto del piano): lo spostamento si trova per 'voto', poi
    si affina con un'omografia e si ri-associa."""
    if not blobs:
        return [None] * len(expected_img)
    B = np.array([(b[0], b[1]) for b in blobs])
    E = np.asarray(expected_img, float)
    G = np.asarray(grid_bed, float)
    # 1) voto sullo spostamento globale
    diffs = (B[None, :, :] - E[:, None, :]).reshape(-1, 2)
    cell = max(spacing_px / 5.0, 3.0)
    keys = np.round(diffs / cell).astype(int)
    uniq, inv, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    best = np.argmax(counts)
    shift = diffs[inv.ravel() == best].mean(axis=0)
    pred = E + shift
    radius = spacing_px * 0.35
    result = [None] * len(E)
    for it in range(3):
        result = [None] * len(E)
        used = set()
        d = np.linalg.norm(B[None, :, :] - pred[:, None, :], axis=2)
        for i in np.argsort(d.min(axis=1)):
            j = int(np.argmin(d[i]))
            if d[i, j] <= radius and j not in used:
                used.add(j)
                result[i] = (float(B[j, 0]), float(B[j, 1]))
        ok = [i for i, r in enumerate(result) if r is not None]
        if len(ok) < 6:
            break
        Hm, _ = cv2.findHomography(G[ok], np.array([result[i] for i in ok]), cv2.RANSAC, spacing_px * 0.1)
        if Hm is None:
            break
        pred = cv2.perspectiveTransform(G.reshape(-1, 1, 2), Hm).reshape(-1, 2)
        radius = spacing_px * 0.25
    return result


def calibration_grid(bed_x, bed_y, n=5, margin=15.0):
    """Griglia n×n in coordinate macchina, ordinata a serpentina (meno strada)."""
    xs = np.linspace(margin, bed_x - margin, n)
    ys = np.linspace(margin, bed_y - margin, n)
    pts = []
    for j, y in enumerate(ys):
        row = xs if j % 2 == 0 else xs[::-1]
        pts += [(float(x), float(y)) for x in row]
    return pts
