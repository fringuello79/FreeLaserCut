# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Anteprima realistica: come apparirà la bruciatura sul materiale.

Ogni tratto deposita energia proporzionale a potenza / velocità (energia per mm).
L'energia si accumula sui pixel (passate sovrapposte e righe vicine si sommano),
si sfuma con la dimensione dello spot e diventa scurimento: 1 - exp(-k·E).
Non è una misura fisica esatta, ma mostra subito zone troppo cotte o troppo chiare,
differenze fra livelli e l'effetto di interlinea e velocità.
"""
import math

import cv2
import numpy as np

MATERIALS = {
    "betulla": ((222, 190, 146), (52, 32, 20), 30.0),
    "pioppo": ((232, 210, 170), (60, 38, 24), 30.0),
    "noce": ((150, 104, 68), (30, 18, 12), 26.0),
    "cartone": ((205, 170, 125), (40, 28, 20), 45.0),
    "pelle": ((150, 98, 60), (35, 20, 14), 35.0),
    "ardesia": ((60, 62, 66), (205, 205, 200), 25.0),  # su ardesia il laser schiarisce
    "anodizzato nero": ((30, 30, 34), (215, 215, 210), 20.0),
}


def render(pv, s_max=1000.0, material="betulla", px_per_mm=4.0, spot=0.15, upto=None, max_px=2400, grain=True):
    """Restituisce (immagine RGB uint8, rettangolo (x0, y0, w, h) in mm del piano)."""
    segs = pv.segs if upto is None else pv.segs[:upto]
    if len(segs) == 0:
        return None, None
    a = np.asarray(segs, dtype=np.float64)
    burn = a[a[:, 5] > 0]
    if not len(burn):
        return None, None
    x0 = min(a[:, 0].min(), a[:, 2].min())
    x1 = max(a[:, 0].max(), a[:, 2].max())
    y0 = min(a[:, 1].min(), a[:, 3].min())
    y1 = max(a[:, 1].max(), a[:, 3].max())
    if pv.has_bounds:
        x0, y0, x1, y1 = pv.min_x, pv.min_y, pv.max_x, pv.max_y
    pad = 2.0
    x0 -= pad
    y0 -= pad
    x1 += pad
    y1 += pad
    W, H = x1 - x0, y1 - y0
    ppm = min(px_per_mm, max_px / max(W, H, 1e-6))
    nx, ny = int(math.ceil(W * ppm)) + 1, int(math.ceil(H * ppm)) + 1
    E = np.zeros((ny, nx), np.float64)
    # campioni lungo i tratti, energia per mm = (S/Smax) / (v in mm/s)
    sx, sy, ex, ey = burn[:, 0], burn[:, 1], burn[:, 2], burn[:, 3]
    L = np.hypot(ex - sx, ey - sy)
    e = (burn[:, 4] / max(s_max, 1e-9)) / np.maximum(burn[:, 6] / 60.0, 1e-3)
    step = 0.5 / ppm
    n = np.maximum(np.ceil(L / step).astype(np.int64), 1)
    total = int(n.sum())
    if total > 30_000_000:  # file enormi: campionamento più rado
        k = total / 30_000_000
        n = np.maximum((n / k).astype(np.int64), 1)
        total = int(n.sum())
    idx = np.repeat(np.arange(len(burn)), n)
    start = np.cumsum(n) - n
    t = (np.arange(total) - np.repeat(start, n) + 0.5) / np.repeat(n, n)
    px = (sx[idx] + (ex[idx] - sx[idx]) * t - x0) * ppm
    py = (y1 - (sy[idx] + (ey[idx] - sy[idx]) * t)) * ppm
    w = (e[idx] * L[idx] / n[idx]) * ppm * ppm  # energia per area di pixel
    ix = np.clip(px.astype(np.int64), 0, nx - 1)
    iy = np.clip(py.astype(np.int64), 0, ny - 1)
    np.add.at(E, (iy, ix), w)
    sigma = max(spot * ppm / 2.0, 0.6)
    E = cv2.GaussianBlur(E, (0, 0), sigma)
    base, dark, k = MATERIALS.get(material, MATERIALS["betulla"])
    d = 1.0 - np.exp(-k * E)  # E = energia per mm² (indipendente dalla risoluzione)
    img = np.empty((ny, nx, 3), np.float64)
    for c in range(3):
        img[..., c] = base[c] + (dark[c] - base[c]) * d
    if grain and material in ("betulla", "pioppo", "noce"):
        yy = np.arange(ny)[:, None] / ppm
        xx = np.arange(nx)[None, :] / ppm
        g = 0.5 + 0.5 * np.sin(yy * 1.7 + 3.0 * np.sin(xx * 0.05) + 0.8 * np.sin(yy * 0.31))
        img *= (0.93 + 0.07 * g)[..., None]
    return np.clip(img, 0, 255).astype(np.uint8), (x0, y0, W, H)
