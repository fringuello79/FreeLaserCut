# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.2: calibrazione completa della camera della testa, una volta per tutte (freeburn/mosaico-preciso.md, parte 1,
con le correzioni di freeburn/mosaico-revisione.md).

Una sola cosa da fare per la persona: mettere un cartone (o compensato sottile) di circa 15 × 10 cm sotto il laser.
Poi FreeLaserCut:
1. incide un puntino di prova, lo trova con la camera e lo segue spostando la testa (scala, rotazione, specchio e
   distanza fra laser e camera, a grandi linee: head_camera.HeadCalibration);
2. controlla la luce e che il cartone copra la zona della griglia, prima di sprecarlo;
3. dalla grandezza e dal contrasto del puntino sceglie potenza, misura dei puntini e passo della griglia per QUESTA
   camera (almeno 25 pixel fra i puntini, puntino di almeno 8 pixel);
4. incide la griglia (righe sfalsate, tre puntini grandi in tre angoli), circa un minuto o due;
5. fotografa la griglia in punti diversi dell'immagine, sempre arrivando dalla stessa direzione e a macchina ferma,
   controlla che la camera tenga l'inquadratura (messa a fuoco o inquadratura automatica), misura il gioco della
   macchina e torna alla prima posizione per vedere se ha perso passi;
6. riconosce i puntini dalla posizione nello schema (non dall'aspetto), dal centro verso i bordi, con la lente
   ricalcolata a ogni passo;
7. calcola lente (due coefficienti e centro vero), inclinazione, scala, rotazione, specchio e distanza laser–camera,
   tenendo da parte un puntino su cinque solo per il controllo;
8. dice quanto è buona (in pixel e in mm per quella camera) e, se è da rifare, perché. Una calibrazione da rifare
   non sostituisce quella vecchia; se quella vecchia è migliore sui punti di controllo resta quella.

Le funzioni di calcolo sono senza interfaccia e senza macchina, così le prove le controllano numericamente.
"""
import math
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import Signal

from . import camera_calib as cc
from . import head_camera as hc
from .camera import CalibrationCancelled
from .i18n import tr

CARD_MM = (150.0, 100.0)  # cartone della calibrazione (circa 15 × 10 cm)
GRID_MAX = (120.0, 70.0)  # la griglia sta nel cartone con 15 mm di margine
MIN_PX_PER_MM = 4.0  # sotto: camera troppo grossolana per la calibrazione completa
MIN_PITCH_PX = 25.0
MIN_DOT_PX = 8.0
BIG = 2.2  # i tre puntini grandi: 2,2 volte quelli piccoli
GOOD_P95_PX = 1.5  # buona: il 95% dei punti di controllo entro 1,5 pixel…
GOOD_MAX_PX = 3.0  # …e nessuno oltre 3 pixel
MIN_SEEN = 0.8  # ogni foto deve riconoscere almeno l'80% dei puntini che dovrebbe vedere
STABLE_WAIT = 10.0  # s fra le due foto del controllo dell'inquadratura
APPROACH = 1.5  # mm: ogni foto si raggiunge da (−1,5; −1,5) mm, sempre dalla stessa parte (gioco delle cinghie)


# ======================================================================= schema della griglia
class GridPlan:
    """Puntini da incidere, in mm rispetto al centro della griglia G (piano come si vede)."""

    def __init__(self, pitch, dot, nx, ny, hole=()):
        self.pitch = float(pitch)
        self.dot = float(dot)
        self.big = self.dot * BIG
        self.nx, self.ny = int(nx), int(ny)
        dy = self.pitch * math.sqrt(3) / 2  # righe sfalsate di mezzo passo: tutti i vicini alla stessa distanza
        pts, ids, big = [], [], []
        for j in range(self.ny):
            n = self.nx if j % 2 == 0 else self.nx - 1
            x0 = -(self.nx - 1) * self.pitch / 2 + (0 if j % 2 == 0 else self.pitch / 2)
            y = (j - (self.ny - 1) / 2) * dy
            for i in range(n):
                pts.append((x0 + i * self.pitch, y))
                ids.append((j, i))
                big.append((j, i) in ((0, 0), (0, self.nx - 1), (self.ny - 1, 0)))
        pts = np.array(pts, float)
        keep = np.ones(len(pts), bool)
        for hx, hy, hr in hole:  # niente puntini vicino ai puntini di prova (stanno al centro)
            keep &= np.hypot(pts[:, 0] - hx, pts[:, 1] - hy) > hr
        keep |= np.array(big)  # i tre grandi restano sempre
        self.pts = pts[keep]
        self.ids = [ids[i] for i in range(len(ids)) if keep[i]]
        self.is_big = np.array([big[i] for i in range(len(big)) if keep[i]], bool)
        # un puntino su cinque solo per il controllo (mai i grandi): sparsi su tutta la griglia
        self.control = np.array([(not b) and (3 * j + 2 * i) % 5 == 0 for (j, i), b in zip(self.ids, self.is_big)],
                                bool)
        self.size = (float(np.ptp(self.pts[:, 0])) + self.big, float(np.ptp(self.pts[:, 1])) + self.big)

    def __len__(self):
        return len(self.pts)

    def rings(self, big):
        """Raggi dei cerchi concentrici che riempiono un puntino (mm)."""
        r = (self.big if big else self.dot) / 2 - 0.15
        out = []
        while r >= 0.1:
            out.append(round(r, 3))
            r -= 0.2
        return out or [0.1]

    def gcode(self, origin_work, s_value, feed=hc.MARK_FEED):
        """Righe per incidere la griglia con il centro in origin_work (coordinate di lavoro, mm, già nel verso della
        macchina: to_work trasforma (dx, dy) del piano in spostamenti di lavoro). Ogni puntino si raggiunge sempre
        dalla stessa parte; laser spento fra un puntino e l'altro."""
        ux0, uy0, to_work = origin_work
        lines = ["G90 G21", "M4 S0"]
        order = sorted(range(len(self.pts)), key=lambda k: (self.ids[k][0],
                                                             self.ids[k][1] if self.ids[k][0] % 2 == 0
                                                             else -self.ids[k][1]))
        for k in order:
            dx, dy = to_work(*self.pts[k])
            ux, uy = ux0 + dx, uy0 + dy
            rings = self.rings(self.is_big[k])
            r0 = rings[0]
            lines.append(f"G0 X{ux + r0 - 0.8:.3f} Y{uy - 0.8:.3f}")
            for r in rings:
                lines += [f"G0 X{ux + r:.3f} Y{uy:.3f}", f"G1 F{feed:.0f} S{s_value:.0f}",
                          f"G2 X{ux + r:.3f} Y{uy:.3f} I{-r:.3f} J0", "S0"]
            lines += [f"G0 X{ux:.3f} Y{uy:.3f}", f"G1 X{ux + 0.05:.3f} S{s_value:.0f}", "S0"]
        lines.append("M5 S0")
        return lines

    def seconds(self, feed=hc.MARK_FEED, rapid=3000.0):
        burn = sum(2 * math.pi * r for k in range(len(self.pts)) for r in self.rings(self.is_big[k]))
        travel = len(self.pts) * (self.pitch + 2.0)
        return burn / feed * 60 + travel / rapid * 60 + len(self.pts) * 0.4


def plan_grid(mm_per_px, view_mm, spread=1.0, hole_r=0.0):
    """Schema della griglia per questa camera. -> (GridPlan, None) oppure (None, perché).
    mm_per_px: scala misurata col puntino di prova; view_mm: zona inquadrata; spread: quanto il materiale allarga il
    puntino (diametro visto / diametro inciso)."""
    if not mm_per_px or mm_per_px <= 0 or not math.isfinite(mm_per_px):
        return None, tr("scala della camera sconosciuta")
    if 1.0 / mm_per_px < MIN_PX_PER_MM:
        return None, tr("la camera è troppo lontana o ha troppo pochi pixel ({0:.1f} pixel per mm, ne servono almeno "
                        "{1:.0f}) per la calibrazione completa", 1.0 / mm_per_px, MIN_PX_PER_MM)
    spread = float(min(max(spread, 0.7), 2.5))
    dot = float(min(max(14 * mm_per_px, 1.2), 2.5))
    if dot * spread / mm_per_px < MIN_DOT_PX:
        dot = min(2.5, MIN_DOT_PX * mm_per_px / spread)
    pitch = max(6 * dot * spread, MIN_PITCH_PX * mm_per_px, 4.0)
    pitch = math.ceil(pitch * 2) / 2
    ex = min(view_mm[0] * 0.9, GRID_MAX[0])
    ey = min(view_mm[1] * 0.9, GRID_MAX[1])
    nx = int(ex // pitch) + 1
    ny = int(ey // (pitch * math.sqrt(3) / 2)) + 1
    if ny % 2 == 0:
        ny -= 1
    if nx < 4 or ny < 3:
        return None, tr("la camera inquadra una zona troppo piccola per la griglia")
    hole = [(0.0, 0.0, max(0.8 * pitch, hole_r + 0.6 * pitch))]
    return GridPlan(pitch, dot, nx, ny, hole), None


def photo_offsets(plan, view_mm):
    """Dove mettere il centro della griglia nell'immagine (frazioni di metà immagine, x verso destra e y verso il
    basso dell'immagine) perché, foto dopo foto, i puntini passino su tutta l'immagine: centro e quattro angoli, più i
    quattro lati se la griglia è piccola rispetto all'inquadratura."""
    gx = min(1.0, plan.size[0] / max(view_mm[0], 1e-6))
    gy = min(1.0, plan.size[1] / max(view_mm[1], 1e-6))
    qx = float(min(max(1 - gx, 0.3), 0.7))
    qy = float(min(max(1 - gy, 0.3), 0.7))
    out = [(0.0, 0.0), (qx, qy), (-qx, qy), (-qx, -qy), (qx, -qy)]
    if gx < 0.7 or gy < 0.7:
        out += [(qx, 0.0), (-qx, 0.0), (0.0, qy), (0.0, -qy)]
    return out


# ======================================================================= immagini
frame_ok = hc.frame_ok  # 0.20.2: sta in head_camera (la usa anche la ricerca del puntino)


def light_spot(frame):
    """C'è una luce forte sul materiale (puntino rosso, lucciola, laser acceso)? -> True/False."""
    f = np.asarray(frame)
    if f.ndim != 3:
        return False
    top = f.max(axis=2)
    hot = (top >= 252).astype(np.uint8)
    if hot.mean() > 0.2:  # immagine bruciata da una luce ambiente: lo dice il controllo della luce, non questo
        return False
    n, lab, st, _ce = cv2.connectedComponentsWithStats(hot, 8)
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if not 30 <= area <= 0.005 * hot.size or area < 0.45 * w * h:
            continue  # troppo piccola, troppo grande o non tonda: zone chiare del materiale, non un puntino di luce
        pad = int(max(w, h))
        y0, y1 = max(0, y - pad), min(top.shape[0], y + h + pad)
        x0, x1 = max(0, x - pad), min(top.shape[1], x + w + pad)
        ring = top[y0:y1, x0:x1][lab[y0:y1, x0:x1] != i]
        if ring.size and float(np.median(ring)) < 200:  # si stacca dal fondo: è una luce
            return True
    return False


def light_check(frames, center=None, exclude_r=0):
    """La luce sul cartone va bene per riconoscere i puntini? -> (True, "") oppure (False, cosa fare)."""
    f0 = np.asarray(frames[0])
    g = hc.gray(f0)
    h, w = g.shape
    keep = np.ones_like(g, bool)
    if center is not None and exclude_r:
        yy, xx = np.ogrid[:h, :w]
        keep = (xx - center[0]) ** 2 + (yy - center[1]) ** 2 > exclude_r ** 2
    vals = g[keep]
    med = float(np.median(vals))
    if med < 45:
        return False, tr("l'immagine è troppo scura: accendi una luce sopra il piano (o apri il coperchio) e riprova")
    if float((vals >= 250).mean()) > 0.03 or med > 238:
        return False, tr("l'immagine è troppo chiara o ci sono riflessi: sposta la luce di lato o usa un cartone non "
                         "lucido")
    if len(frames) > 1:
        d = hc.gray(frames[1]) - g
        noise = float(np.std(d[keep])) / math.sqrt(2)
        if noise > 7.0:
            return False, tr("c'è poca luce (immagine con molto rumore): accendi una luce sopra il piano")
    return True, ""


def detect_dots(frame, r_px, polarity=1, pitch_px=None, occluded=None):
    """Puntini nell'immagine. Soglia adattata alla luce di ogni zona, centro al decimo di pixel sulla macchia intera.
    -> array (n, 5): u, v, area (pixel), rotondità (0–1), forza."""
    g = hc.gray(frame)
    h, w = g.shape
    r = max(2.0, float(r_px))
    ks = int(2 * round(1.6 * r * BIG / 2) + 3)  # chiude anche i puntini grandi
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ks, ks))
    gs = cv2.GaussianBlur(g, (0, 0), 0.8)
    if polarity >= 0:  # puntini più scuri del fondo (il caso normale)
        bg = cv2.morphologyEx(gs, cv2.MORPH_CLOSE, ker)
        diff = bg - gs
    else:
        bg = cv2.morphologyEx(gs, cv2.MORPH_OPEN, ker)
        diff = gs - bg
    diff = np.clip(diff, 0, None)
    med = float(np.median(diff))
    mad = float(np.median(np.abs(diff - med))) * 1.4826
    floor = max(6.0, med + 6 * mad)
    span = int(max(3 * r, 1.5 * (pitch_px or 6 * r)))
    span += 1 - span % 2
    peak = cv2.dilate(diff, cv2.getStructuringElement(cv2.MORPH_RECT, (span, span)))
    thr = np.maximum(floor, 0.42 * peak)
    mask = (diff > thr).astype(np.uint8)
    n, lab, st, _ce = cv2.connectedComponentsWithStats(mask, 8)
    a0 = math.pi * r * r
    out = []
    for i in range(1, n):
        x, y, ww, hh, area = st[i]
        if area < 0.25 * a0 or area > 9.0 * a0:
            continue
        if x <= 1 or y <= 1 or x + ww >= w - 1 or y + hh >= h - 1:
            continue  # tagliato dal bordo: il centro sarebbe sbagliato
        x0, y0 = max(0, x - 2), max(0, y - 2)
        x1, y1 = min(w, x + ww + 2), min(h, y + hh + 2)
        sub = (lab[y0:y1, x0:x1] == i)
        sub = cv2.dilate(sub.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        wt = diff[y0:y1, x0:x1] * sub
        tot = float(wt.sum())
        if tot <= 0:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        cu, cv_ = float((xx * wt).sum() / tot), float((yy * wt).sum() / tot)
        cxx = float(((xx - cu) ** 2 * wt).sum() / tot)
        cyy = float(((yy - cv_) ** 2 * wt).sum() / tot)
        cxy = float(((xx - cu) * (yy - cv_) * wt).sum() / tot)
        ev = np.linalg.eigvalsh(np.array([[cxx, cxy], [cxy, cyy]]))
        roundness = float(math.sqrt(max(ev[0], 0) / max(ev[1], 1e-9)))
        if roundness < 0.45:
            continue  # una riga, una venatura, una bruciatura storta
        out.append((cu, cv_, float(area), roundness, float(peak[int(cv_), int(cu)])))
    arr = np.array(out, float).reshape(-1, 5)
    if occluded and len(arr):
        keep = np.ones(len(arr), bool)
        for x0, y0, x1, y1 in occluded:
            keep &= ~((arr[:, 0] >= x0) & (arr[:, 0] < x1) & (arr[:, 1] >= y0) & (arr[:, 1] < y1))
        arr = arr[keep]
    return arr


def match_dots(pred, dets, tol):
    """Ogni puntino previsto con la macchia più vicina, solo se sono l'una la più vicina dell'altro e la seconda
    macchia è lontana (niente scambi fra puntini vicini). -> {indice del puntino: indice della macchia}."""
    out = {}
    if not len(dets) or not len(pred):
        return out
    ok = np.isfinite(pred).all(axis=1)
    idx = np.nonzero(ok)[0]
    if not len(idx):
        return out
    P = pred[idx]
    D = np.hypot(P[:, None, 0] - dets[None, :, 0], P[:, None, 1] - dets[None, :, 1])
    near_det = D.argmin(axis=1)
    near_pred = D.argmin(axis=0)
    for a, i in enumerate(idx):
        j = int(near_det[a])
        d = D[a, j]
        if d > tol or near_pred[j] != a:
            continue
        row = np.sort(D[a])
        if len(row) > 1 and row[1] < max(2.0 * d, 1.5 * tol):
            continue  # due macchie vicine al punto previsto: non so quale
        out[int(i)] = j
    return out


def nn_spacing(pts):
    """Distanza mediana fra ogni punto e il suo vicino più vicino."""
    p = np.asarray(pts, float).reshape(-1, 2)
    if len(p) < 3:
        return None
    D = np.hypot(p[:, None, 0] - p[None, :, 0], p[:, None, 1] - p[None, :, 1])
    np.fill_diagonal(D, np.inf)
    return float(np.median(D.min(axis=1)))


def find_occluded(frames, block=32, keep_pts=()):
    """Zone dell'immagine che non cambiano muovendo la testa ma hanno qualcosa dentro (ugello, tubo dell'aria, cavi):
    sono pezzi della macchina, non materiale. -> [(x0, y0, x1, y1)] in pixel."""
    if len(frames) < 4:
        return []
    G = np.stack([hc.gray(f) for f in frames])
    _n, h, w = G.shape
    std_t = G.std(axis=0)
    gx = cv2.Sobel(G[0], cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(G[0], cv2.CV_32F, 0, 1)
    grad = np.hypot(gx, gy)
    mean0 = G.mean(axis=0)
    rects = []
    for y in range(0, h, block):
        for x in range(0, w, block):
            st = float(std_t[y:y + block, x:x + block].mean())
            gr = float(grad[y:y + block, x:x + block].mean())
            dark = float(mean0[y:y + block, x:x + block].mean())
            if st < 2.5 and (gr > 6.0 or dark < 25):
                rects.append([x, y, min(w, x + block), min(h, y + block)])
    if not rects:
        return []
    kp = np.asarray(keep_pts, float).reshape(-1, 2)
    good = []
    for r in rects:  # dove si sono visti puntini non è coperto
        if len(kp) and np.any((kp[:, 0] >= r[0]) & (kp[:, 0] < r[2]) & (kp[:, 1] >= r[1]) & (kp[:, 1] < r[3])):
            continue
        good.append(r)
    # una zona isolata grande un blocco è rumore; due o più blocchi vicini sono un pezzo della macchina
    out = []
    for r in good:
        neigh = sum(1 for s in good if s is not r and abs(s[0] - r[0]) <= block and abs(s[1] - r[1]) <= block)
        if neigh >= 1:
            out.append(tuple(float(v) for v in r))
    return out


# ======================================================================= calcolo
KINDS = ("affine", "k1", "lens", "full")
_FREE = {"affine": ("A", "t"), "k1": ("A", "t", "k1"), "lens": ("A", "t", "k1", "k2", "q"),
         "full": ("A", "t", "k1", "k2", "q", "g")}
_SIZES = {"A": 4, "t": 2, "k1": 1, "k2": 1, "q": 2, "g": 2}


def _rel(par, x):
    """Come HeadModel._rel, su coordinate normalizzate x e senza spessore."""
    A, t, g, k1, k2, q = par["A"], par["t"], par["g"], par["k1"], par["k2"], par["q"]
    d = x - q
    r2 = (d ** 2).sum(axis=1, keepdims=True)
    u = q + d * (1 + k1 * r2 + k2 * r2 * r2)
    wv = 1.0 + u @ g
    return (u @ A.T + t) / np.where(np.abs(wv) > 1e-6, wv, 1e-6)[:, None]


def _unpack(vec, kind, base):
    par = {k: np.array(v, float).copy() if np.ndim(v) else float(v) for k, v in base.items()}
    i = 0
    for name in _FREE[kind]:
        n = _SIZES[name]
        val = vec[i:i + n]
        par[name] = val.reshape(2, 2).copy() if name == "A" else (float(val[0]) if n == 1 else val.copy())
        i += n
    return par


def _pack(par, kind):
    out = []
    for name in _FREE[kind]:
        v = par[name]
        out += list(np.ravel(v)) if np.ndim(v) else [float(v)]
    return np.array(out, float)


def model_params(model):
    return {"A": model.A.copy(), "t": model.t.copy(), "g": model.g.copy(), "k1": float(model.k1),
            "k2": float(model.k2), "q": model.q.copy()}


def params_model(par, frame_size):
    m = hc.HeadModel(None, None, frame_size, k=par["k1"], A=par["A"], t=par["t"], g=par["g"], k2=par["k2"],
                     q=par["q"])
    return m


def params_ok(par, frame_size):
    """Parametri che danno un modello valido (lente, inclinazione e centro credibili, conti che tornano)."""
    try:
        m = params_model(par, frame_size)
        w, h = frame_size
        corners = np.array([[0, 0], [w, 0], [0, h], [w, h], [w / 2, h / 2]], float)
        back = m.bed_to_img(np.zeros(2), m.img_to_bed(np.zeros(2), corners))
        return bool(np.all(np.isfinite(back)) and float(np.abs(back - corners).max()) < 0.5)
    except (ValueError, np.linalg.LinAlgError):
        return False


def fit(obs, frame_size, start, kind, iters=80):
    """Minimi quadrati (Levenberg–Marquardt) di P = L + X(p) sui puntini osservati.
    obs: dict con P (pixel n×2), L (testa n×2), X (piano n×2). start: parametri di partenza. -> (parametri, rms px)."""
    c = np.array([frame_size[0] / 2.0, frame_size[1] / 2.0])
    f = math.hypot(*frame_size) / 2.0
    x = (np.asarray(obs["P"], float) - c) / f
    target = np.asarray(obs["X"], float) - np.asarray(obs["L"], float)
    base = {k: (np.array(v, float) if np.ndim(v) else float(v)) for k, v in start.items()}
    for name in ("g", "q"):
        if name not in _FREE[kind]:
            base[name] = np.zeros(2)
    for name in ("k1", "k2"):
        if name not in _FREE[kind]:
            base[name] = 0.0
    scale = math.sqrt(abs(np.linalg.det(base["A"]))) / f  # mm per pixel: residui in pixel

    def res(vec):
        r = (_rel(_unpack(vec, kind, base), x) - target) / scale
        return r.ravel()

    v = _pack(base, kind)
    r0 = res(v)
    cost = float(r0 @ r0)
    lam = 1e-3
    for _ in range(iters):
        J = np.empty((len(r0), len(v)))
        for j in range(len(v)):
            e = 1e-6 * max(1.0, abs(v[j]))
            dv = v.copy()
            dv[j] += e
            J[:, j] = (res(dv) - r0) / e
        JtJ = J.T @ J
        g_ = J.T @ r0
        improved = False
        for _try in range(10):
            try:
                step = np.linalg.solve(JtJ + lam * np.diag(np.diag(JtJ) + 1e-12), -g_)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            nv = v + step
            nr = res(nv)
            if np.all(np.isfinite(nr)):
                nc = float(nr @ nr)
                if nc < cost:
                    v, r0, cost = nv, nr, nc
                    lam = max(lam / 3, 1e-9)
                    improved = True
                    break
            lam *= 10
        if not improved or float(np.abs(step).max() if improved else 0) < 1e-12:
            break
    par = _unpack(v, kind, base)
    return par, math.sqrt(cost / max(1, len(r0) // 2))


def errors_px(par, obs, frame_size):
    """Distanza (pixel) fra dove il modello mette ogni puntino e dove è stato inciso."""
    c = np.array([frame_size[0] / 2.0, frame_size[1] / 2.0])
    f = math.hypot(*frame_size) / 2.0
    x = (np.asarray(obs["P"], float) - c) / f
    X = _rel(par, x) + np.asarray(obs["L"], float)
    scale = math.sqrt(abs(np.linalg.det(par["A"]))) / f
    e = np.hypot(*(X - np.asarray(obs["X"], float)).T) / scale
    return e, scale


def model_errors_px(model, obs):
    """Come errors_px, per un modello qualsiasi (anche una calibrazione vecchia)."""
    X = model.img_to_bed(np.zeros(2), obs["P"]) + np.asarray(obs["L"], float)
    e = np.hypot(*(X - np.asarray(obs["X"], float)).T) / max(model.mm_per_px(), 1e-9)
    return np.where(np.isfinite(e), e, 1e3)


def choose_kind(fits):
    """Il modello più semplice che va quasi come il migliore sui punti di controllo (un modello più libero si
    adatterebbe anche agli errori). fits: {kind: (parametri, errori di controllo)}. -> kind."""
    score = {k: float(np.sqrt(np.mean(e ** 2))) for k, (_p, e) in fits.items() if len(e)}
    if not score:
        return None
    best = min(score.values())
    for k in KINDS:
        if k in score and score[k] <= best * 1.1 + 0.03:
            return k
    return min(score, key=score.get)


def camera_nadir(model, height):
    """Punto del piano sotto la camera (mm dal laser), dalla prospettiva e dall'altezza misurata. Se i conti non
    tornano (camera quasi dritta: la prospettiva non basta), il punto sotto il centro della lente. -> (N, inclinazione
    in gradi o None)."""
    fall = model._rel([model.c + model.q * model.f])[0]
    try:
        phi = float(height) / (model.mm_per_px() * model.f)  # distanza focale in unità normalizzate
        H = np.vstack([np.hstack([model.A, model.t.reshape(2, 1)]), np.hstack([model.g, [1.0]])])
        G = np.linalg.inv(H)  # piano → immagine (senza lente)
        S = np.diag([-1.0, 1.0, 1.0]) if model.mirrored() else np.eye(3)
        Kinv = np.linalg.inv(np.array([[phi, 0, model.q[0]], [0, phi, model.q[1]], [0, 0, 1.0]]))
        B = S @ Kinv @ G
        lam = (np.linalg.norm(B[:, 0]) + np.linalg.norm(B[:, 1])) / 2
        r1, r2, tv = B[:, 0] / lam, B[:, 1] / lam, B[:, 2] / lam
        if abs(np.linalg.norm(r1) - 1) > 0.05 or abs(np.linalg.norm(r2) - 1) > 0.05 or abs(r1 @ r2) > 0.06:
            return fall, None
        if tv[2] < 0:
            r1, r2, tv = -r1, -r2, -tv
        R = np.column_stack([r1, r2, np.cross(r1, r2)])
        C = -R.T @ tv
        if abs(abs(C[2]) - height) > 0.2 * height:
            return fall, None
        tilt = math.degrees(math.acos(min(1.0, abs(R[2, 2]))))
        return np.array([C[0], C[1]]), tilt
    except (np.linalg.LinAlgError, ValueError, ZeroDivisionError):
        return fall, None


def flat_trouble(points_bed, errs, plan_size):
    """Gli errori grandi stanno tutti in una zona sola del cartone? (cartone imbarcato) -> True/False."""
    e = np.asarray(errs, float)
    if len(e) < 10:
        return False
    worst = np.asarray(points_bed, float)[e >= np.percentile(e, 90)]
    if len(worst) < 3:
        return False
    spread = float(np.hypot(*np.ptp(worst, axis=0)))
    return spread < 0.4 * math.hypot(*plan_size) and float(np.median(e)) < 0.5 * float(np.percentile(e, 90))


# ======================================================================= calibrazione completa (thread)
class HeadGridCalibration(hc.HeadCalibration):
    """Calibrazione completa (vedi in cima al file). Stessa uscita della calibrazione col puntino:
    finished(HeadModel | None, testo); in più report (dict) con tutti i numeri della verifica."""

    need_height = Signal(str)  # camera che forse non sale con il laser: «metti uno spessore sotto il cartone»
    need_choice = Signal(str)  # nuova e vecchia calibrazione quasi uguali: sceglie la persona

    def __init__(self, ctl, cam, profile, power_pct=hc.DEFAULT_POWER, camera_name="", camera_index=None, guess=None,
                 moves=True, old_model=None, cal_thickness=3.0, ask_confirm=True, wait_stable=STABLE_WAIT):
        super().__init__(ctl, cam, profile, power_pct, camera_name, camera_index, guess=guess, ask_confirm=ask_confirm)
        self.moves = moves  # True sì, False no, None non so (risposta alla domanda iniziale)
        self.old_model = old_model
        self.cal_thickness = float(cal_thickness or 0.0)
        self.wait_stable = float(wait_stable)
        self.report = {}
        self.plan = None
        self.grid_center = None
        self._height = None
        self._choice = None

    # ---- risposte della persona
    def height_answer(self, mm):
        """Spessore (mm) messo sotto il cartone, oppure None (non lo faccio)."""
        self._height = None if mm is None else float(mm)
        self._ok_user = True
        self._go.set()

    def choose(self, new):
        self._choice = bool(new)
        self._ok_user = True
        self._go.set()

    # ---- movimenti e foto
    def _photo_at(self, L, opposite=False, n=3):
        """La testa in L arrivando sempre da (−1,5; −1,5) mm (o dalla parte opposta), poi foto a macchina ferma, con
        il laser spento e fotogrammi controllati. -> (testa raggiunta, foto media)."""
        self._check()
        s = -1.0 if opposite else 1.0
        bx, by = self.profile.bed_x, self.profile.bed_y
        ax = min(max(L[0] - s * APPROACH, 0.0), bx)
        ay = min(max(L[1] - s * APPROACH, 0.0), by)
        self._go_to(ax, ay)
        Lr = self._go_to(*L)
        self.ctl.send_line("M5 S0")
        for attempt in range(3):
            frames = self._shot(n)
            bad = [frame_ok(f) for f in frames]
            frames = [f for f, (ok, _w) in zip(frames, bad) if ok]
            if not frames:
                if attempt == 2:
                    raise RuntimeError(tr("la camera della testa manda immagini rovinate ({0}): due camere sulla stessa "
                                          "porta USB? Collegala a un'altra porta", bad[0][1]))
                continue
            avg = cc._avg(frames).astype(np.uint8)
            if light_spot(avg):
                if attempt == 2:
                    raise RuntimeError(tr("c'è una luce forte sul materiale durante le foto (puntino rosso o Lucciola "
                                          "accesi?): spegnila e riprova"))
                self.ctl.send_line("M5 S0")
                time.sleep(0.5)
                continue
            return Lr, avg
        raise RuntimeError(tr("nessuna foto buona dalla camera della testa"))

    def _bed_job(self, lines, seconds, text):
        done = threading.Event()
        result = {}

        def on_done(ok, msg):
            result.update(ok=ok, msg=msg)
            done.set()

        self.ctl.job_finished.connect(on_done)
        t0 = time.time()
        try:
            self.ctl.stream_job(lines)
            last = 0.0
            while not done.wait(0.1):
                self._check()
                now = time.time()
                if now - last >= 1.0:
                    last = now
                    left = max(0, int(round(seconds - (now - t0))))
                    self.progress.emit(4, 9, text + " " + tr("(mancano circa {0})", _mmss(left)))
        except BaseException:
            # annullata, scollegata o in allarme a metà: la griglia si ferma davvero (non solo il thread), laser spento
            if not done.is_set() and self.ctl.connected:
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

    def _work_origin(self, P):
        """Centro della griglia in coordinate di lavoro e conversione piano → lavoro degli spostamenti."""
        wx, wy = self.ctl.wco
        mx, my = self.profile.to_machine(*P)

        def to_work(dx, dy):
            return self.profile.to_machine_delta(dx, dy)

        return (mx - wx, my - wy, to_work)

    # ---- procedura
    def _calibrate(self):
        rep = self.report
        t_start = time.time()
        # 1. puntino di prova: scala, rotazione, specchio, distanza laser–camera a grandi linee
        st = self._find_dot()
        size, c = st["size"], np.array([st["size"][0] / 2.0, st["size"][1] / 2.0])
        M, O = st["M"], st["O"]
        prov = hc.HeadModel(M, O, size)
        mmpx = prov.mm_per_px()
        L0 = np.asarray(self.mark_bed, float)
        rep.update(mm_per_px=mmpx, provisional=prov)
        # 2. luce sul cartone (camera sopra il puntino di prova)
        self.progress.emit(2, 9, tr("Controllo la luce sul cartone…"))
        Lc = self._go_to(*prov.head_for_camera(L0))
        frames = []
        for _try in range(3):  # solo fotogrammi buoni: uno rovinato sembrerebbe «rumore»
            frames += [f for f in self._shot(2) if frame_ok(f)[0]]
            if len(frames) >= 2:
                break
        if not frames:
            raise RuntimeError(tr("nessuna foto buona dalla camera della testa"))
        pk = prov.bed_to_img(Lc, [L0])[0]
        ok, why = light_check(frames, pk, 3 * self._mark_r + 6)
        if not ok:
            raise RuntimeError(why)
        # 3. il puntino di prova: si vede abbastanza? quanto si allarga?
        frame = cc._avg(frames).astype(np.uint8)
        q = hc.refine_dark(frame, pk, radius=self._mark_r)
        pk = np.asarray(q if q is not None else pk, float)
        power = self.power_pct
        contrast, r_px = dot_contrast(frame, pk, self._mark_r)
        tries = [(power, contrast)]
        cap = max(power, min(80.0, power * 3))
        k_extra = 0
        while contrast < 6.0 and power < cap - 1e-6 and k_extra < 2:
            k_extra += 1
            power = min(cap, power * 1.6)
            self.progress.emit(2, 9, tr("Il puntino si vede poco: ne incido un altro al {0:.0f}%…", power))
            P2 = L0 + np.array([3.5 * (1 if k_extra == 1 else -1), 0.0])
            self._go_to(*P2)
            old = self.power_pct
            self.power_pct = power
            try:
                self._burn_mark(P2)
            finally:
                self.power_pct = old
            Lc = self._go_to(*prov.head_for_camera(P2))
            fr = cc._avg([f for f in self._shot(3) if frame_ok(f)[0]] or self._shot(2)).astype(np.uint8)
            p2 = prov.bed_to_img(Lc, [P2])[0]
            q2 = hc.refine_dark(fr, p2, radius=self._mark_r)
            if q2 is None:
                contrast, r2 = 0.0, r_px
            else:
                contrast, r2 = dot_contrast(fr, q2, self._mark_r)
            tries.append((power, contrast))
            if contrast >= 6.0:
                r_px = r2
        rep["test_dots"] = tries
        if contrast < 6.0:
            raise RuntimeError(tr("i puntini si vedono troppo poco su questo materiale anche al {0:.0f}%: usa un "
                                  "cartone più chiaro o un compensato chiaro", power))
        spread = (2 * r_px * mmpx) / 1.6  # il puntino di prova è largo 1,6 mm
        grid_power = power * (0.7 if spread > 2.0 else 1.0)  # bruciato e allargato: la griglia più delicata
        rep.update(spread=spread, grid_power=grid_power)
        # 4. schema della griglia per questa camera
        view = prov.view_mm()
        plan, why = plan_grid(mmpx, view, spread, hole_r=3.5 if k_extra else 0.0)
        if plan is None:
            raise RuntimeError(why)
        self.plan = plan
        G = L0
        self.grid_center = tuple(G)
        offs = photo_offsets(plan, view)
        heads = []
        for qx, qy in offs:
            p = c + np.array([qx * size[0] / 2, qy * size[1] / 2])
            heads.append(G - prov._rel([p])[0])
        bx, by = self.profile.bed_x, self.profile.bed_y

        def inside(Lh):
            return APPROACH <= Lh[0] <= bx - APPROACH and APPROACH <= Lh[1] <= by - APPROACH

        usable = [i for i, Lh in enumerate(heads) if inside(Lh)]
        if 0 not in usable or len(usable) < 4:
            raise RuntimeError(tr("da qui la camera non riesce a fotografare la griglia in tutte le zone "
                                  "dell'immagine (troppo vicino al bordo del piano): metti il cartone più verso il "
                                  "centro del piano e riprova"))
        rep["positions"] = len(usable)
        # 5. il cartone copre la zona della griglia? (prima di inciderla)
        self.progress.emit(3, 9, tr("Controllo che il cartone copra la zona della griglia…"))
        ref = _patch_stats(frame, pk, int(4 * self._mark_r + 20), exclude=self._mark_r * 2.5)
        hx, hy = plan.size[0] / 2, plan.size[1] / 2
        for cx_, cy_ in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)):
            Pc = G + [cx_, cy_]
            target = prov.head_for_camera(Pc)
            if not (0 <= target[0] <= bx and 0 <= target[1] <= by):
                continue
            Lq = self._go_to(*target)
            fq = cc._avg([f for f in self._shot(3) if frame_ok(f)[0]] or self._shot(2)).astype(np.uint8)
            pq = prov.bed_to_img(Lq, [Pc])[0]
            if not np.all(np.isfinite(pq)):
                continue
            s = _patch_stats(fq, pq, int(4 * self._mark_r + 20))
            if s is None or ref is None:
                continue
            if abs(s[0] - ref[0]) > 0.35 * max(ref[0], 30) or s[1] > 3 * ref[1] + 15:
                raise RuntimeError(tr("il cartone non copre tutta la zona della griglia (circa {0:.0f} × {1:.0f} mm "
                                      "attorno al puntino): mettilo centrato sotto il laser, o usane uno più "
                                      "grande, e riprova", plan.size[0] + 10, plan.size[1] + 10))
        # 6. incisione della griglia
        secs = plan.seconds()
        rep.update(grid_dots=len(plan), pitch=plan.pitch, dot=plan.dot, grid_seconds=secs)
        self.progress.emit(4, 9, tr("Incido la griglia: {0} puntini al {1:.0f}%…", len(plan), grid_power))
        self._go_to(*G)
        lines = plan.gcode(self._work_origin(G), self._s(grid_power))
        self._bed_job(lines, secs, tr("Incido la griglia…"))
        self.ctl.send_line("M5 S0")
        # 7. foto: centro (due volte, a 10 s), dalla parte opposta (gioco), le altre zone, di nuovo il centro
        self.progress.emit(5, 9, tr("Fotografo la griglia…"))
        shots = []
        L_a, f_a = self._photo_at(heads[0])
        shots.append((L_a, f_a, "first"))
        self.progress.emit(5, 9, tr("Controllo che la camera tenga l'inquadratura ({0:.0f} s)…", self.wait_stable))
        end = time.time() + self.wait_stable
        while time.time() < end:
            self._check()
            time.sleep(0.1)
        L_b, f_b = self._photo_at(heads[0])
        shots.append((L_b, f_b, "stable"))
        L_o, f_o = self._photo_at(heads[0], opposite=True)
        shots.append((L_o, f_o, "opposite"))
        for k, i in enumerate(usable[1:]):
            self.progress.emit(5, 9, tr("Fotografo la griglia ({0} di {1})…", k + 2, len(usable)))
            Li, fi = self._photo_at(heads[i])
            shots.append((Li, fi, "zone"))
        L_z, f_z = self._photo_at(heads[0])
        shots.append((L_z, f_z, "last"))
        rep["photos"] = len(shots)
        # 8. riconoscimento, calcolo, verifica
        self.progress.emit(6, 9, tr("Riconosco i puntini…"))
        model, msg = self._solve(shots, prov, size)
        if model is None:
            return None, msg
        # 9. camera che forse non sale e scende con il laser: seconda altezza
        if self.moves is not True:
            model, extra = self._second_height(model, heads[0], shots[0])
            msg += ("\n" + extra) if extra else ""
        model.power_pct = grid_power
        model.camera_name = self.camera_name
        model.camera_index = self.camera_index
        model.camera_mode = str(getattr(self.cam, "mode", "") or "")
        model.autofocus = str(getattr(self.cam, "autofocus", "") or "")
        # 10. quella vecchia è migliore?
        model, msg = self._compare_old(model, msg)
        rep["seconds"] = time.time() - t_start
        self.progress.emit(9, 9, tr("Fatto"))
        return model, msg

    def _p(self, i, n, text):
        """La prima fase (puntino di prova) dentro la barra della calibrazione completa: passi 0–2 di 9."""
        self.progress.emit(min(2, int(i * 2 / max(n, 1))), 9, text)

    def _find_dot(self):
        """Fase 1 (la calibrazione col puntino fino alla misura di scala e rotazione)."""
        self.progress.emit(0, 9, tr("Guardo il materiale (laser spento)…"))
        st = self._calibrate_dot(quick=True)
        return st

    def _solve(self, shots, prov, size):
        rep = self.report
        plan = self.plan
        G = np.asarray(self.grid_center, float)
        X_all = G + plan.pts
        r_px = max(MIN_DOT_PX / 2, plan.dot / 2 / prov.mm_per_px() * rep.get("spread", 1.0))
        pitch_px = plan.pitch / prov.mm_per_px()
        frames = [f for _L, f, _k in shots]
        dets = [detect_dots(f, r_px, 1, pitch_px) for f in frames]
        par = model_params(prov)
        kinds_by_stage = (("affine", 0.4), ("k1", 0.62), ("lens", 0.85), ("full", 1.05))
        matches = [{} for _ in shots]
        tol = 0.3 * pitch_px
        half_diag = math.hypot(*size) / 2
        cimg = np.array([size[0] / 2.0, size[1] / 2.0])
        for kind, reach in kinds_by_stage:
            mdl = params_model(par, size)
            for s, (L, _f, _k) in enumerate(shots):
                pred = mdl.bed_to_img(L, X_all)
                far = np.hypot(*(pred - cimg).T) > reach * half_diag
                pred = pred.copy()
                pred[far] = np.nan
                matches[s] = match_dots(pred, dets[s], tol)
            obs = _obs(shots, matches, dets, X_all, ~plan.control)
            if len(obs["P"]) < 12:
                return None, tr("Calibrazione da rifare: riconosco troppo pochi puntini ({0}). Controlla la luce e che "
                                "il cartone sia fermo e a fuoco.", len(obs["P"]))
            new_par, _rms = fit(obs, size, par, kind)
            if params_ok(new_par, size):  # un modello più libero che diverge (pochi punti) non si usa
                par = new_par
            tol = 0.25 * pitch_px
        # conteggio: ogni foto deve riconoscere almeno l'80% dei puntini che dovrebbe vedere
        mdl = params_model(par, size)
        margin = 2.5 * r_px * BIG
        seen = []
        keep_shot = []
        for s, (L, _f, _k) in enumerate(shots):
            pred = mdl.bed_to_img(L, X_all)
            ok = np.isfinite(pred).all(axis=1) & (pred[:, 0] > margin) & (pred[:, 0] < size[0] - margin) \
                & (pred[:, 1] > margin) & (pred[:, 1] < size[1] - margin)
            matches[s] = match_dots(pred, dets[s], 0.25 * pitch_px)
            frac = sum(1 for i in matches[s] if ok[i]) / max(1, int(ok.sum()))
            seen.append(round(frac, 3))
            keep_shot.append(frac >= MIN_SEEN)
        rep["seen"] = seen
        # zone coperte da pezzi della macchina (si escludono anche dal conteggio)
        pts_seen = np.array([dets[s][j, :2] for s in range(len(shots)) for j in matches[s].values()]).reshape(-1, 2)
        occl = find_occluded([frames[s] for s, (_L, _f, k) in enumerate(shots) if k in ("first", "zone")], 32,
                             pts_seen)
        rep["occluded"] = occl
        if occl:
            for s, (L, _f, _k) in enumerate(shots):
                if keep_shot[s]:
                    continue
                pred = mdl.bed_to_img(L, X_all)
                ok = np.isfinite(pred).all(axis=1) & (pred[:, 0] > margin) & (pred[:, 0] < size[0] - margin) \
                    & (pred[:, 1] > margin) & (pred[:, 1] < size[1] - margin)
                tmp = hc.HeadModel(np.eye(2), (0, 0), size)
                tmp.occluded = occl
                ok &= ~tmp.is_occluded(np.where(np.isfinite(pred), pred, -1))
                frac = sum(1 for i in matches[s] if ok[i]) / max(1, int(ok.sum()))
                seen[s] = round(frac, 3)
                keep_shot[s] = frac >= MIN_SEEN
        kinds = [k for _L, _f, k in shots]
        if not keep_shot[0] or not keep_shot[kinds.index("last")]:
            return None, tr("Calibrazione da rifare: nella foto al centro manca più di un puntino su cinque (poca luce, "
                            "riflessi o puntini troppo chiari). Accendi una luce sopra il piano e riprova.")
        zones_ok = sum(1 for s, k in enumerate(kinds) if k == "zone" and keep_shot[s])
        if zones_ok < 3:
            return None, tr("Calibrazione da rifare: in troppe foto mancano puntini (poca luce, cartone che non copre "
                            "la zona o pezzi della macchina davanti alla camera).")
        # inquadratura ferma (messa a fuoco o inquadratura automatica) e passi persi
        a, b = kinds.index("first"), kinds.index("stable")
        shift, ratio = _compare_shots(dets[a], matches[a], dets[b], matches[b])
        rep["stable_shift_px"], rep["stable_scale"] = shift, ratio
        if shift is None or shift > 0.6 or abs(ratio - 1) > 0.002:
            return None, tr("Calibrazione da rifare: la camera ha cambiato inquadratura da sola mentre la testa era "
                            "ferma (messa a fuoco o inquadratura automatica). Spegni la messa a fuoco automatica e "
                            "l'inquadratura automatica dal programma della camera, oppure usa un'altra camera.")
        z = kinds.index("last")
        shift_z, _r = _compare_shots(dets[a], matches[a], dets[z], matches[z])
        mmpx = mdl.mm_per_px()
        rep["return_shift_mm"] = None if shift_z is None else shift_z * mmpx
        if shift_z is None or shift_z * mmpx > max(0.08, 1.2 * mmpx):
            return None, tr("Calibrazione da rifare: tornando al primo punto l'immagine non è più la stessa (spostata "
                            "di {0:.2f} mm). La macchina ha perso passi o la camera si è mossa: controlla che il "
                            "supporto sia ben stretto e che la testa scorra libera.",
                            0.0 if shift_z is None else shift_z * mmpx)
        o = kinds.index("opposite")
        bl = _backlash(mdl, shots[a][0], dets[a], matches[a], shots[o][0], dets[o], matches[o], X_all)
        rep["backlash"] = bl
        # calcolo finale: i quattro modelli, punti di controllo esclusi; vince il più semplice che va come il migliore
        use = [s for s in range(len(shots)) if keep_shot[s] and kinds[s] not in ("stable", "opposite", "last")]
        obs_fit = _obs([shots[s] for s in use], [matches[s] for s in use], [dets[s] for s in use], X_all,
                       ~plan.control)
        obs_ctl = _obs([shots[s] for s in use], [matches[s] for s in use], [dets[s] for s in use], X_all,
                       plan.control)
        if len(obs_ctl["P"]) < 6:
            return None, tr("Calibrazione da rifare: troppo pochi punti di controllo riconosciuti ({0}).",
                            len(obs_ctl["P"]))
        fits = {}
        start = par
        for kind in KINDS:
            p_k, _ = fit(obs_fit, size, start, kind)
            e_fit, _s = errors_px(p_k, obs_fit, size)
            bad = e_fit > max(3.0, 4 * float(np.median(e_fit)))  # riconoscimenti sbagliati: fuori, poi di nuovo
            if bad.any() and (~bad).sum() >= 12:
                o2 = {k: np.asarray(v)[~bad] for k, v in obs_fit.items()}
                p_k, _ = fit(o2, size, p_k, kind)
            if not params_ok(p_k, size):
                continue  # valori impossibili: questo modello non si considera
            e_ctl, _s = errors_px(p_k, obs_ctl, size)
            fits[kind] = (p_k, e_ctl)
            start = p_k
        kind = choose_kind(fits)
        if kind is None:
            return None, tr("Calibrazione da rifare: i puntini non danno un modello della camera credibile. Controlla "
                            "che il cartone sia piatto e fermo.")
        par, e_ctl = fits[kind]
        model = params_model(par, size)
        e_fit, _s = errors_px(par, obs_fit, size)
        mmpx = model.mm_per_px()
        qd = {"model": kind, "n_fit": int(len(obs_fit["P"])), "n_ctrl": int(len(e_ctl)),
              "rms_px": float(np.sqrt(np.mean(e_ctl ** 2))), "p95_px": float(np.percentile(e_ctl, 95)),
              "max_px": float(e_ctl.max()), "max_mm": float(e_ctl.max() * mmpx),
              "p95_mm": float(np.percentile(e_ctl, 95) * mmpx), "fit_rms_px": float(np.sqrt(np.mean(e_fit ** 2))),
              "by_kind": {k: float(np.sqrt(np.mean(e ** 2))) for k, (_p, e) in fits.items()}}
        model.quality = qd
        model.rms_px = qd["rms_px"]
        model.rms_mm = qd["rms_px"] * mmpx
        model.backlash = bl
        model.occluded = occl
        model.method = "grid"
        model.moves_with_head = True if self.moves is True else None
        model.cal_thickness = self.cal_thickness
        rep["quality"] = qd
        rep["obs_ctl"] = obs_ctl
        good = qd["p95_px"] <= GOOD_P95_PX and qd["max_px"] <= GOOD_MAX_PX
        rep["good"] = good
        if not good:
            why = ""
            if flat_trouble(obs_ctl["X"], e_ctl, plan.size):
                why = " " + tr("Gli errori grandi sono tutti in una zona: il cartone non è piatto. Fermalo con dei pesi "
                               "(fuori dalla griglia) o usa un compensato sottile.")
            return None, tr("Calibrazione da rifare: errore massimo {0:.2f} mm ({1:.1f} pixel) sui punti di controllo, "
                            "troppo per questa camera.", qd["max_mm"], qd["max_px"]) + why + "\n" + \
                tr("La calibrazione di prima resta com'era.")
        msg = tr("Calibrazione completa riuscita: {0}", model.describe())
        msg += "\n" + tr("Verifica su {0} punti di controllo (non usati per il calcolo): errore massimo {1:.2f} mm "
                         "({2:.1f} pixel), il 95% entro {3:.2f} mm.", qd["n_ctrl"], qd["max_mm"], qd["max_px"],
                         qd["p95_mm"])
        if bl is not None and max(abs(bl[0]), abs(bl[1])) >= 0.05:
            msg += "\n" + tr("Gioco della macchina: {0:.2f} mm in X, {1:.2f} mm in Y (arrivando da parti opposte): è "
                             "della macchina, non della camera.", abs(bl[0]), abs(bl[1]))
        if occl:
            msg += "\n" + tr("Una parte dell'immagine è coperta da pezzi della macchina: non la uso per le foto.")
        return model, msg

    def _second_height(self, model, L_center, first_shot):
        """Camera che forse non sale e scende con il laser (domanda iniziale: No / Non so): stesse foto con il
        cartone sollevato di uno spessore noto. -> (modello, testo)."""
        rep = self.report
        self._height = None
        self._go.clear()
        self._ok_user = False
        self.need_height.emit(tr("Ultimo passo: solleva il cartone con uno spessore che conosci (per esempio un "
                                 "compensato di 3–6 mm sotto il cartone, misurato col calibro), senza toccare la "
                                 "camera, e rimetti a fuoco il laser come fai di solito prima di un lavoro. Poi scrivi "
                                 "di quanti mm l'hai sollevato."))
        self._go.wait()
        if self._cancel.is_set():
            raise CalibrationCancelled()
        T = self._height
        if not T or T < 1.5:
            model.moves_with_head = None
            return model, tr("Seconda altezza non misurata: se la camera non sale e scende con il laser, con materiali "
                             "di spessore diverso la posizione può sbagliare di qualche decimo di mm.")
        plan = self.plan
        mmpx = model.mm_per_px()
        r_px = max(MIN_DOT_PX / 2, plan.dot / 2 / mmpx * rep.get("spread", 1.0))
        L2, f2 = self._photo_at(L_center)
        d1 = detect_dots(first_shot[1], r_px, 1, plan.pitch / mmpx)
        d2 = detect_dots(f2, r_px, 1, plan.pitch / mmpx)
        # grandezza della griglia sul piano secondo il modello (che vale per il cartone della calibrazione): con il
        # cartone sollevato e la camera ferma la griglia sembra più grande di D / (D − T). Il cartone può essersi
        # spostato: conta solo la grandezza, non la posizione
        G = np.asarray(self.grid_center, float)
        s1 = _scale_vs_plan(model, first_shot[0], d1, plan, G)
        s2 = _scale_vs_plan(model, L2, d2, plan, G)
        if not s1 or not s2:
            model.moves_with_head = None
            return model, tr("Seconda altezza: non vedo la griglia sul cartone sollevato; spessore non misurato.")
        r = s2 / s1
        rep["height_ratio"] = r
        if abs(r - 1) < 0.004:
            model.moves_with_head = True
            return model, tr("La camera sale e scende con il laser: lo spessore del materiale non conta.")
        if r < 1:
            model.moves_with_head = None
            return model, tr("Seconda altezza: la griglia si vede più piccola, non più grande (il cartone è stato "
                             "abbassato?). Spessore non misurato.")
        D = T * r / (r - 1)
        if not 15.0 <= D <= 600.0:
            model.moves_with_head = None
            return model, tr("Seconda altezza: misura non credibile (camera a {0:.0f} mm dal cartone). Spessore non "
                             "misurato.", D)
        model.moves_with_head = False
        model.height_mm = float(D)
        N, tilt = camera_nadir(model, D)
        model.nadir = np.asarray(N, float)
        rep["height_mm"], rep["tilt_deg"] = D, tilt
        txt = tr("La camera non sale con il laser: è a circa {0:.0f} mm dal cartone. Per i lavori scrivi lo spessore "
                 "del materiale nella vista della testa.", D)
        return model, txt

    def _compare_old(self, model, msg):
        old = self.old_model
        obs = self.report.get("obs_ctl")
        if old is None or obs is None or tuple(old.frame_size) != tuple(model.frame_size):
            return model, msg
        e_old = model_errors_px(old, obs)
        e_new = model_errors_px(model, obs)
        p_old, p_new = float(np.percentile(e_old, 95)), float(np.percentile(e_new, 95))
        self.report["old_p95_px"], self.report["new_p95_px"] = p_old, p_new
        # revisione D3: si tiene quella con l'errore più piccolo sugli stessi punti di controllo; se sono vicine
        # (entro il 15% o 0,1 pixel) sceglie la persona
        close = abs(p_new - p_old) <= max(0.15 * min(p_new, p_old), 0.1)
        if not close and p_new < p_old:
            return model, msg
        # 0.20.3 (Ale, 15/11): decide sempre la persona. Prima una calibrazione nuova «peggiore» veniva scartata senza
        # chiedere: ma chi l'ha rifatta di solito ha un motivo (camera spostata, messa a fuoco cambiata) che i numeri
        # sugli stessi punti non vedono.
        if not close:
            ask = tr("La calibrazione nuova ({0:.1f} pixel) risulta meno precisa di quella che c'è già ({1:.1f} pixel "
                     "sugli stessi punti di controllo). Se hai spostato o rimesso a fuoco la camera tieni quella "
                     "nuova.\n\nTengo quella nuova?", p_new, p_old)
        else:
            ask = tr("La calibrazione nuova e quella di prima sono quasi uguali sui punti di controllo "
                     "(nuova {0:.1f} pixel, prima {1:.1f} pixel). Tengo quella nuova?", p_new, p_old)
        self._choice = None
        self._go.clear()
        self._ok_user = False
        self.need_choice.emit(ask)
        self._go.wait()
        if self._cancel.is_set() or self._choice is None:
            raise CalibrationCancelled()
        if not self._choice:
            return None, tr("Tengo la calibrazione di prima.")
        return model, msg


def _mmss(s):
    s = int(max(0, s))
    return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"


def _obs(shots, matches, dets, X_all, which):
    P, L, X, ids = [], [], [], []
    for (Ls, _f, _k), m, d in zip(shots, matches, dets):
        for i, j in m.items():
            if which[i]:
                P.append(d[j, :2])
                L.append(Ls)
                X.append(X_all[i])
                ids.append(i)
    return {"P": np.array(P, float).reshape(-1, 2), "L": np.array(L, float).reshape(-1, 2),
            "X": np.array(X, float).reshape(-1, 2), "ids": np.array(ids, int)}


def _compare_shots(da, ma, db, mb):
    """Stesso puntino in due foto con la testa nello stesso punto: spostamento mediano (pixel) e rapporto di scala."""
    common = sorted(set(ma) & set(mb))
    if len(common) < 6:
        return None, 1.0
    A = np.array([da[ma[i], :2] for i in common])
    B = np.array([db[mb[i], :2] for i in common])
    shift = float(np.median(np.hypot(*(B - A).T)))
    ca, cb = A.mean(axis=0), B.mean(axis=0)
    sa = float(np.sqrt(((A - ca) ** 2).sum(axis=1).mean()))
    sb = float(np.sqrt(((B - cb) ** 2).sum(axis=1).mean()))
    return shift, (sb / sa if sa > 0 else 1.0)


def _backlash(model, La, da, ma, Lb, db, mb, X_all):
    """Differenza (mm sul piano) fra la stessa posizione raggiunta da due parti opposte."""
    common = sorted(set(ma) & set(mb))
    if len(common) < 6:
        return None
    A = model.img_to_bed(La, np.array([da[ma[i], :2] for i in common]))
    B = model.img_to_bed(Lb, np.array([db[mb[i], :2] for i in common]))
    d = np.median(B - A, axis=0)  # stesso puntino: dove sembra spostato = quanto la testa non è dove dice
    return (float(d[0]), float(d[1]))


def _scale_vs_plan(model, L, dets, plan, G):
    """Grandezza della griglia vista (mm sul piano secondo il modello) rispetto a quella incisa: 1 = uguale. Prima
    si toglie lo spostamento del cartone (anche di un passo intero: alla grandezza non importa). -> rapporto o None."""
    X_all = G + plan.pts
    pred = model.bed_to_img(L, X_all)
    ok = np.isfinite(pred).all(axis=1)
    if not len(dets) or ok.sum() < 6:
        return None
    pp = plan.pitch / max(model.mm_per_px(), 1e-9)
    Dm = np.hypot(pred[ok][:, None, 0] - dets[None, :, 0], pred[ok][:, None, 1] - dets[None, :, 1])
    j = Dm.argmin(axis=1)
    shift = np.median(dets[j, :2] - pred[ok], axis=0)
    m = match_dots(pred + shift, dets, 0.3 * pp)
    if len(m) < 6:
        return None
    idx = np.array(list(m.keys()))
    B = model.img_to_bed(L, dets[np.array([m[i] for i in idx]), :2])
    P = X_all[idx]
    Bc, Pc = B - B.mean(axis=0), P - P.mean(axis=0)
    den = float((Pc ** 2).sum())
    return math.sqrt(float((Bc ** 2).sum()) / den) if den > 0 else None


def _central(dets, model, frac=0.6):
    if not len(dets):
        return np.zeros((0, 2))
    c = model.c
    keep = np.hypot(*(dets[:, :2] - c).T) < frac * min(model.frame_size) / 2
    small = dets[:, 2] < 2.0 * np.median(dets[:, 2])
    return dets[keep & small, :2]


def _patch_stats(frame, p, half, exclude=0.0):
    """Luminosità mediana e variazione attorno a p (escluso il cerchio centrale). -> (mediana, deviazione) o None."""
    g = hc.gray(frame)
    h, w = g.shape
    u, v = int(round(p[0])), int(round(p[1]))
    x0, x1, y0, y1 = max(0, u - half), min(w, u + half), max(0, v - half), min(h, v + half)
    if x1 - x0 < 10 or y1 - y0 < 10:
        return None
    sub = g[y0:y1, x0:x1]
    if exclude:
        yy, xx = np.mgrid[y0:y1, x0:x1]
        sub = sub[(xx - p[0]) ** 2 + (yy - p[1]) ** 2 > exclude ** 2]
    return float(np.median(sub)), float(np.std(sub))


def dot_contrast(frame, p, r):
    """Quanto il puntino si stacca dal fondo (in multipli del rumore del materiale) e il suo raggio (pixel)."""
    g = cv2.GaussianBlur(hc.gray(frame), (0, 0), 0.8)
    h, w = g.shape
    R = int(max(8, 3 * r + 6))
    u, v = int(round(p[0])), int(round(p[1]))
    x0, x1, y0, y1 = max(0, u - R), min(w, u + R + 1), max(0, v - R), min(h, v + R + 1)
    sub = g[y0:y1, x0:x1]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d2 = (xx - p[0]) ** 2 + (yy - p[1]) ** 2
    ring = sub[d2 > (1.8 * r + 3) ** 2]
    core = sub[d2 <= max(1.0, 0.5 * r) ** 2]
    if ring.size < 20 or core.size == 0:
        return 0.0, r
    bg = float(np.median(ring))
    noise = max(1.5, float(np.std(ring)))
    dark = bg - float(np.median(core))
    area = float(((bg - sub) > 0.5 * max(dark, 1)).sum() * (d2 <= (2 * r + 3) ** 2).mean())
    rr = math.sqrt(max(((bg - sub)[d2 <= (2 * r + 3) ** 2] > 0.5 * max(dark, 1)).sum(), 1) / math.pi)
    del area
    return (dark / noise if dark > 0 else 0.0), float(rr)


# ======================================================================= camera vera (per le prove)
def camera_model(size, mm_per_px, angle=0.0, mirror=False, offset=(0.0, 35.0), tilt=0.0, tilt_dir=0.0, k1=0.0,
                 k2=0.0, q=(0.0, 0.0), height=60.0):
    """Il modello esatto di una camera a foro stenopeico (con lente) alta height mm sul materiale, inclinata di tilt
    gradi verso tilt_dir (gradi sul piano), che con la testa ferma guarda al centro dell'immagine il punto offset
    (mm dal laser). Serve al simulatore e alle prove: è la «verità» con cui confrontare la calibrazione."""
    w, h = size
    f = math.hypot(w, h) / 2.0
    phi = height / (mm_per_px * f)
    a = math.radians(angle)
    ex = np.array([math.cos(a), math.sin(a), 0.0])
    ey = np.array([math.sin(a), -math.cos(a), 0.0])
    ez = np.array([0.0, 0.0, -1.0])
    if tilt:
        ax = np.array([-math.sin(math.radians(tilt_dir)), math.cos(math.radians(tilt_dir)), 0.0])
        K_ = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
        th = math.radians(tilt)
        Rt = np.eye(3) + math.sin(th) * K_ + (1 - math.cos(th)) * K_ @ K_
        ex, ey, ez = Rt @ ex, Rt @ ey, Rt @ ez
    R = np.vstack([ex, ey, ez])  # mondo → camera
    s = -height / ez[2]
    Cxy = np.asarray(offset, float) - s * ez[:2]
    C = np.array([Cxy[0], Cxy[1], height])
    S = np.diag([1.0, -1.0 if mirror else 1.0, 1.0])  # specchio come head_camera.natural_matrix (verso v)
    K = np.array([[phi, 0, q[0]], [0, phi, q[1]], [0, 0, 1.0]])
    G = K @ S @ np.column_stack([R[:, 0], R[:, 1], -R @ C])
    H = np.linalg.inv(G)
    H = H / H[2, 2]
    m = hc.HeadModel(None, None, size, k=k1, A=H[:2, :2], t=H[:2, 2], g=H[2, :2], k2=k2, q=q)
    m.height_mm, m.nadir = float(height), Cxy.copy()
    return m


# ======================================================================= controllo rapido (10 s)
class HeadCheckJob(hc.HeadCalibration):
    """«Controlla la calibrazione» (revisione D4). Laser spento: la testa si sposta di misure note (un terzo
    dell'inquadratura) e l'immagine deve spostarsi di quanto prevede il modello: si vede se la camera è stata girata,
    se è cambiata la scala (camera più alta o più bassa, lente girata) o la lente. Con dot=True in più incide un
    puntino su uno scarto e lo guarda con la camera: si vede anche se è cambiata la distanza fra laser e camera (camera
    urtata o spostata nel supporto), che gli spostamenti da soli non possono vedere.
    finished(dict | None, testo)."""

    def __init__(self, ctl, cam, profile, model, dot=False, power_pct=None):
        super().__init__(ctl, cam, profile, power_pct or model.power_pct or hc.DEFAULT_POWER, ask_confirm=False)
        self.model = model
        self.dot = bool(dot)

    def _run(self):
        try:
            self._check()
            self.ctl.send_line("M5 S0")
            m = self.model
            L0 = self._head()
            res = {"errors_px": [], "ok": True}
            msgs = []
            f0 = cc._avg(self._shot(2)).astype(np.uint8)
            c = m.c
            half = int(min(m.frame_size) // 8)
            tpl = hc.patch(f0, c, half)
            n = 3 + (3 if self.dot else 0)
            if tpl is None or float(tpl.std()) < 4.0:
                if not self.dot:
                    self.finished.emit(None, tr("Qui il materiale è troppo liscio per il controllo: porta la camera su "
                                                "legno o cartone con un po' di venatura e riprova."))
                    return
                msgs.append(tr("Materiale liscio: controllo solo con il puntino."))
            else:
                P = m.img_to_bed(L0, [c])[0]  # il punto del piano che si sta seguendo
                s = 0.33 * min(m.view_mm())
                L = L0
                for i, (dx, dy) in enumerate(((s, 0.0), (0.0, s), (-s, -s))):
                    self._check()
                    self.progress.emit(i, n, tr("Controllo la calibrazione…"))
                    dx, dy = self._inside(L, dx, dy)
                    L = self._go_to(L[0] + dx, L[1] + dy)
                    pred = m.bed_to_img(L, [P])[0]
                    if not np.all(np.isfinite(pred)):
                        continue
                    f = cc._avg(self._shot(2)).astype(np.uint8)
                    p, score = hc.track(f, tpl, pred, 60)
                    if p is None or score < 0.6:
                        continue
                    res["errors_px"].append(float(np.hypot(*(np.asarray(p) - pred))))
                L0 = self._go_to(*L0)
                if len(res["errors_px"]) < 2:
                    self.finished.emit(None, tr("Non riesco a seguire il materiale spostando la testa: controlla la "
                                                "luce e riprova."))
                    return
                worst = max(res["errors_px"])
                res["max_px"], res["max_mm"] = worst, worst * m.mm_per_px()
                res["ok"] = worst <= 2.5
            if self.dot:  # il puntino: dove lo incide il laser e dove lo vede la camera
                self.progress.emit(3, n, tr("Foto prima del puntino…"))
                Lc = self._go_to(*m.head_for_camera(L0))
                before = self._shot(3)
                self._go_to(*L0)
                self.progress.emit(4, n, tr("Incido il puntino al {0:.0f}%…", self.power_pct))
                self._burn_mark(L0)
                self.ctl.send_line("M5 S0")
                Lc = self._go_to(*m.head_for_camera(L0))
                after = self._shot(3)
                self.progress.emit(5, n, tr("Cerco il puntino…"))
                pk = hc.find_new_mark(before, after)
                if pk is None:
                    res["ok"] = False
                    res["dot_px"] = None
                    msgs.append(tr("Il puntino non si vede vicino al mirino: la camera si è spostata parecchio, oppure "
                                   "il puntino è troppo debole (aumenta la potenza). Rifai la calibrazione completa se "
                                   "il puntino c'è."))
                else:
                    q = hc.refine_dark(cc._avg(after).astype(np.uint8), pk, radius=10)
                    pk = np.asarray(q if q is not None else pk, float)
                    pred = m.bed_to_img(Lc, [L0])[0]
                    e = float(np.hypot(*(pk - pred)))
                    res["dot_px"], res["dot_mm"] = e, e * m.mm_per_px()
                    res["ok"] = res["ok"] and e <= 3.0
            self.progress.emit(n, n, tr("Fatto"))
            worst_mm = max(res.get("max_mm") or 0.0, res.get("dot_mm") or 0.0)
            worst_px = max(res.get("max_px") or 0.0, res.get("dot_px") or 0.0)
            if res["ok"]:
                head = tr("Calibrazione ancora buona: l'immagine si sposta come previsto (scarto massimo {0:.2f} mm, "
                          "{1:.1f} pixel).", worst_mm, worst_px)
                if self.dot:
                    head += " " + tr("Il puntino è dove la camera lo aspetta.")
            else:
                head = tr("La calibrazione non torna più (scarto {0:.2f} mm, {1:.1f} pixel): la camera o il supporto si "
                          "sono mossi. Rifai la calibrazione completa.", worst_mm, worst_px)
            self.finished.emit(res, "\n".join([head] + msgs))
        except CalibrationCancelled:
            self._safe_off()
            self.finished.emit(None, tr("Controllo annullato"))
        except Exception as exc:  # noqa: BLE001
            self._safe_off()
            self.finished.emit(None, tr("Controllo interrotto: {0}", exc))


# ======================================================================= camera del piano aiutata (parte 2)
# freeburn/mosaico-preciso.md, parte 2, con le correzioni F1–F7 di mosaico-revisione.md. Una sola funzione, da usare
# con il materiale già sul piano: la camera della testa (calibrata) guarda alcuni punti del materiale, ognuno si
# ritrova nella foto della camera del piano e dallo spostamento si ricava una correzione della foto del piano. Così si
# correggono insieme il piccolo errore della lente fra i dischi della calibrazione, lo spessore del materiale (con la
# camera in alto un materiale più alto si vede spostato verso l'esterno: è una scala attorno al punto sotto la camera,
# cioè una correzione affine) e la camera sul coperchio che si è spostata aprendolo. Mai in silenzio: solo con almeno
# 4 punti coerenti, con il numero prima e dopo; un materiale non piano non si corregge.
BED_PPM = 4.0  # pixel per mm del confronto


def bed_align_points(zone, model, profile, n=3):
    """Punti del piano da guardare con la camera della testa: una griglia n × n nella zona (x0, y0, x1, y1), solo dove
    la testa ci arriva."""
    x0, y0, x1, y1 = zone
    vw, vh = model.view_mm()
    mx, my = min(vw, (x1 - x0) / 2) * 0.5, min(vh, (y1 - y0) / 2) * 0.5
    out = []
    for y in np.linspace(y0 + my, y1 - my, n):
        for x in np.linspace(x0 + mx, x1 - mx, n):
            L = model.head_for_camera((x, y))
            if 0 <= L[0] <= profile.bed_x and 0 <= L[1] <= profile.bed_y:
                out.append((float(x), float(y)))
    return out


def head_patch(frame, model, head, P, half_mm, ppm=BED_PPM):
    """La zona attorno a P vista dalla camera della testa, raddrizzata in mm come la foto del piano (riga 0 = Y più
    alto). -> immagine grigia o None se la camera non la vede tutta."""
    n = int(round(2 * half_mm * ppm))
    jj, ii = np.meshgrid(np.arange(n), np.arange(n))
    X = np.stack([P[0] - half_mm + (jj.ravel() + 0.5) / ppm, P[1] + half_mm - (ii.ravel() + 0.5) / ppm], axis=1)
    px = model.bed_to_img(head, X)
    w, h = model.frame_size
    ok = np.isfinite(px).all(axis=1) & (px[:, 0] >= 0) & (px[:, 0] <= w - 1) & (px[:, 1] >= 0) & (px[:, 1] <= h - 1)
    if model.occluded:
        ok &= ~model.is_occluded(np.where(np.isfinite(px), px, -1))
    if ok.mean() < 0.98:
        return None
    mx = px[:, 0].reshape(n, n).astype(np.float32)
    my = px[:, 1].reshape(n, n).astype(np.float32)
    return cv2.remap(hc.gray(frame), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def find_in_bed(top_gray, bed_y, P, patch, search_mm=12.0, ppm=BED_PPM):
    """Dove la foto del piano mostra il pezzo di materiale che la camera della testa vede in P. -> (d in mm, somiglianza)
    con d = (posizione nella foto del piano) − P, oppure (None, perché)."""
    if patch is None:
        return None, tr("la camera della testa non vede tutta la zona")
    if float(patch.std()) < 5.0:
        return None, tr("materiale liscio, niente da riconoscere")
    n = patch.shape[0]
    R = int(round(search_mm * ppm))
    c0 = int(round((P[0]) * ppm - n / 2)) - R
    r0 = int(round((bed_y - P[1]) * ppm - n / 2)) - R
    H, W = top_gray.shape
    if r0 < 0 or c0 < 0 or r0 + n + 2 * R > H or c0 + n + 2 * R > W:
        return None, tr("troppo vicino al bordo della foto del piano")
    area = top_gray[r0:r0 + n + 2 * R, c0:c0 + n + 2 * R].astype(np.float32)
    if float(area.std()) < 5.0:
        return None, tr("la camera del piano qui non vede niente")
    res = cv2.matchTemplate(area, patch.astype(np.float32), cv2.TM_CCOEFF_NORMED)
    _mn, best, _ml, (bx, by) = cv2.minMaxLoc(res)
    mask = np.ones_like(res, bool)
    k = int(max(2, ppm))
    mask[max(0, by - k):by + k + 1, max(0, bx - k):bx + k + 1] = False
    second = float(res[mask].max()) if mask.any() else -1.0
    if best < 0.45 or best - second < 0.06:
        return None, tr("confronto incerto ({0:.2f})", best)
    if bx in (0, res.shape[1] - 1) or by in (0, res.shape[0] - 1):
        return None, tr("spostamento oltre {0:.0f} mm", search_mm)

    def sub(a, b, c_):
        d = a - 2 * b + c_
        return 0.0 if abs(d) < 1e-9 else 0.5 * (a - c_) / d

    dx = (bx - R + sub(res[by, bx - 1], res[by, bx], res[by, bx + 1])) / ppm
    dy = -(by - R + sub(res[by - 1, bx], res[by, bx], res[by + 1, bx])) / ppm
    return np.array([dx, dy]), float(best)


def fit_bed_correction(points, ds, tol=0.8, attempted=None):
    """Correzione affine d(P) = A·P + b dagli spostamenti misurati, senza i punti che non tornano.
    attempted: quanti punti si sono guardati (riconosciuti e no). -> dict (A, b, inliers, before_mm, after_mm)
    oppure (None, perché)."""
    P = np.asarray(points, float).reshape(-1, 2)
    D = np.asarray(ds, float).reshape(-1, 2)
    if len(P) < 4:
        return None, tr("servono almeno 4 punti con qualcosa da riconoscere (ne ho {0})", len(P))
    if attempted and len(P) < 0.6 * attempted:
        # pochi punti riconosciuti non bastano a dire che la correzione vale su tutto il piano
        return None, tr("riconosco solo {0} punti su {1}: troppo pochi per correggere tutto il piano (materiale "
                        "liscio, non piano o camera del piano che vede poco)", len(P), attempted)
    keep = np.ones(len(P), bool)
    for _ in range(4):
        if keep.sum() < 4:
            break
        X = np.hstack([P[keep], np.ones((keep.sum(), 1))])
        sol, *_ = np.linalg.lstsq(X, D[keep], rcond=None)
        pred = np.hstack([P, np.ones((len(P), 1))]) @ sol
        res = np.hypot(*(D - pred).T)
        lim = max(tol, 3 * float(np.median(res[keep])))
        new = res <= lim
        if (new == keep).all():
            break
        keep = new
    # un punto solo che non torna è una zona più alta o più bassa (si dice dove); di più è un materiale imbarcato
    if keep.sum() < 4 or keep.sum() < 0.6 * len(P) or (~keep).sum() > max(1, int(0.15 * len(P))):
        return None, tr("i punti non tornano con una correzione sola: il materiale non è piano o ha altezze diverse")
    X = np.hstack([P[keep], np.ones((keep.sum(), 1))])
    sol, *_ = np.linalg.lstsq(X, D[keep], rcond=None)
    res = np.hypot(*(D[keep] - X @ sol).T)
    if float(res.max()) > 1.0:
        return None, tr("i punti non tornano con una correzione sola (scarto {0:.1f} mm): il materiale non è piano o "
                        "ha altezze diverse", float(res.max()))
    A = sol[:2].T
    b = sol[2]
    return {"A": A, "b": b, "inliers": int(keep.sum()), "points": int(len(P)),
            "before_mm": float(np.hypot(*D[keep].T).max()), "after_mm": float(res.max()),
            "outliers": [tuple(map(float, p)) for p in P[~keep]]}, None


def apply_bed_correction(top, corr, bed_y, ppm):
    """La foto del piano corretta: nel punto P mostra quello che la foto aveva in P + d(P)."""
    if corr is None:
        return top
    A, b = np.asarray(corr["A"], float), np.asarray(corr["b"], float)
    M = np.eye(2) + A  # P → sorgente (mm)
    # pixel: col = x·ppm, riga = (bed_y − y)·ppm
    S = np.array([[ppm, 0, 0], [0, -ppm, bed_y * ppm], [0, 0, 1]])
    T = np.vstack([np.hstack([M, b.reshape(2, 1)]), [0, 0, 1]])
    W = S @ T @ np.linalg.inv(S)
    return cv2.warpAffine(top, W[:2], (top.shape[1], top.shape[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(34, 26, 15))


class BedAlignJob(hc.AutoCam):
    """«Allinea con la camera della testa» (thread). La testa va fuori dall'inquadratura della camera del piano per la
    foto del piano, poi la camera della testa guarda i punti. Laser sempre spento.
    finished(dict con la correzione | None, testo)."""

    def __init__(self, ctl, head_cam, profile, head_model, bed_cam, bed_model, park=None, zone=None):
        super().__init__(ctl, head_cam, profile, grid_n=1, method="bedalign")
        self.head_model = head_model
        self.bed_cam = bed_cam
        self.bed_model = bed_model
        self.park_at = park
        self.zone = zone
        self.found = []

    def _goto(self, x, y):
        x, y = hc.clamp_to_bed(self.profile, x, y)
        ax, ay = hc.clamp_to_bed(self.profile, x - APPROACH, y - APPROACH)
        for tx, ty in ((ax, ay), (x, y)):
            mx, my = self.profile.to_machine(tx, ty)
            self.ctl.goto_machine(mx, my, 6000)
        self._wait_idle()
        return hc.head_on_bed(self.ctl, self.profile)

    def _run(self):
        try:
            self._check()
            self.ctl.send_line("M5 S0")
            bx, by = self.profile.bed_x, self.profile.bed_y
            zone = self.zone
            if zone is None:
                v = getattr(self.bed_model, "valid", None)
                zone = (v[0], v[1], v[0] + v[2], v[1] + v[3]) if v else (0.0, 0.0, bx, by)
            pts = bed_align_points(zone, self.head_model, self.profile)
            if len(pts) < 4:
                self.finished.emit(None, tr("La camera della testa non arriva ad abbastanza punti del piano."))
                return
            park = self.park_at or (15.0, 15.0)
            self.progress.emit(0, len(pts) + 1, tr("Testa fuori dall'inquadratura, foto della camera del piano…"))
            self._goto(*park)
            frames = self.bed_cam.frames(3, after=time.time() + 0.3)
            if not frames:
                self.finished.emit(None, tr("La camera del piano non sta inviando immagini."))
                return
            top = self.bed_model.rectify(cc._avg(frames).astype(np.uint8), BED_PPM)
            top_gray = hc.gray(top)
            half = min(self.head_model.view_mm()) * 0.38
            ok_pts, ds, why = [], [], []
            for i, P in enumerate(pts):
                self._check()
                self.progress.emit(i + 1, len(pts) + 1, tr("La camera della testa guarda il punto {0} di {1}…", i + 1,
                                                           len(pts)))
                L = self._goto(*self.head_model.head_for_camera(P))
                f = cc._avg(self.cam.frames(2, after=time.time() + 0.25)).astype(np.uint8)
                patch = head_patch(f, self.head_model, L, P, half)
                d, info = find_in_bed(top_gray, by, P, patch)
                self.found.append((P, d, info))
                if d is None:
                    why.append(info)
                    continue
                ok_pts.append(P)
                ds.append(d)
            self._goto(*park)
            corr, reason = fit_bed_correction(ok_pts, ds, attempted=len(pts))
            self.progress.emit(len(pts) + 1, len(pts) + 1, tr("Fatto"))
            if corr is None:
                self.finished.emit(None, tr("Foto del piano non corretta: {0}.", reason))
                return
            msg = tr("Foto della camera del piano allineata con la camera della testa: entro {0:.1f} mm su {1} punti "
                     "(prima sbagliava fino a {2:.1f} mm). Vale per il materiale che c'è adesso sul piano.",
                     corr["after_mm"], corr["inliers"], corr["before_mm"])
            for x, y in corr["outliers"]:  # revisione F3: un punto che non torna si dice, non si nasconde
                msg += "\n" + tr("Il punto X {0:.0f} Y {1:.0f} non torna con gli altri (lì il materiale è più alto o più "
                                 "basso?): in quella zona la foto può sbagliare.", x, y)
            self.finished.emit(corr, msg)
        except CalibrationCancelled:
            self.finished.emit(None, tr("Allineamento annullato"))
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(None, tr("Allineamento interrotto: {0}", exc))
