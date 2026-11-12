# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Elaborazione immagini per l'incisione raster.

Il campionamento avviene direttamente alla risoluzione di uscita (righe del laser),
seguendo qualunque trasformazione dell'immagine (ruotata, specchiata, scalata):
il dithering lavora sui "punti" che il laser farà davvero, non sui pixel originali.

Valori: 0 = bianco (niente laser) ... 1 = nero (potenza massima).
"""
import math

import cv2
import numpy as np

try:
    from numba import njit
except ImportError:  # pragma: no cover
    njit = None

KERNELS = {
    # (dx, dy, peso), divisore
    "floyd": ([(1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)], 16.0),
    "jarvis": ([(1, 0, 7), (2, 0, 5), (-2, 1, 3), (-1, 1, 5), (0, 1, 7), (1, 1, 5), (2, 1, 3),
                (-2, 2, 1), (-1, 2, 3), (0, 2, 5), (1, 2, 3), (2, 2, 1)], 48.0),
    "stucki": ([(1, 0, 8), (2, 0, 4), (-2, 1, 2), (-1, 1, 4), (0, 1, 8), (1, 1, 4), (2, 1, 2),
                (-2, 2, 1), (-1, 2, 2), (0, 2, 4), (1, 2, 2), (2, 2, 1)], 42.0),
    "atkinson": ([(1, 0, 1), (2, 0, 1), (-1, 1, 1), (0, 1, 1), (1, 1, 1), (0, 2, 1)], 8.0),
}

_BAYER8 = np.array([
    [0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]], dtype=np.float32) / 64.0 + 1 / 128.0

# piccole variazioni di soglia per un futuro retino stocastico (riserva: oggi nessun metodo le usa)
_JITTER = (0.1621, 0.2402, 0.1504, 0.1309, 0.1582, 0.2285, 0.166, 0.1387, 0.1387, 0.127, 0.4707,
           0.4629, 0.4355, 0.0566, 0.2246, 0.166, 0.209, 0.209, 0.1816, 0.1309, 0.127)


def _diffuse_py(img, kx, ky, kw, div):
    h, w = img.shape
    out = np.zeros((h, w), np.uint8)
    buf = img.astype(np.float64).copy()
    n = len(kx)
    for y in range(h):
        rev = y % 2 == 1  # serpentina: meno "vermi" nel dithering
        rng = range(w - 1, -1, -1) if rev else range(w)
        for x in rng:
            old = buf[y, x]
            new = 1.0 if old >= 0.5 else 0.0
            out[y, x] = 1 if new > 0 else 0
            err = (old - new) / div
            for k in range(n):
                xx = x - kx[k] if rev else x + kx[k]
                yy = y + ky[k]
                if 0 <= xx < w and yy < h:
                    buf[yy, xx] += err * kw[k]
    return out


_diffuse = njit(cache=True)(_diffuse_py) if njit is not None else _diffuse_py


def adjust(dark, brightness=0.0, contrast=0.0, gamma=1.0, negative=False):
    """dark: array 0..1 (1 = nero). Luminosità/contrasto -100..100, gamma 0.2..5."""
    d = dark.astype(np.float32)
    if negative:
        d = 1.0 - d
    if brightness:
        d = d - brightness / 200.0  # più luminoso = meno scuro
    if contrast:
        c = (100.0 + contrast) / 100.0
        d = (d - 0.5) * c * c + 0.5 if contrast > 0 else (d - 0.5) * c + 0.5
    d = np.clip(d, 0.0, 1.0)
    if gamma and abs(gamma - 1.0) > 1e-3:
        d = 1.0 - np.power(1.0 - d, 1.0 / gamma)
    return np.clip(d, 0.0, 1.0)


def dither(dark, method, cell_px=6.0, angle=45.0, dot_size=100.0):
    """dark 0..1 -> per 'grayscale' potenza 0..1; altrimenti 0/1 (punto acceso).
    dot_size (0.19.0): solo per le mezzetinte, dimensione del punto in % (100 = l'area del punto segue lo scuro)."""
    if method == "grayscale":
        return dark.astype(np.float32)
    if method == "threshold":
        return (dark >= 0.5).astype(np.float32)
    if method == "bayer":
        h, w = dark.shape
        tile = np.tile(_BAYER8, (h // 8 + 1, w // 8 + 1))[:h, :w]
        return (dark > tile).astype(np.float32)
    if method == "halftone":
        return _halftone(dark, cell_px, angle, dot_size)
    kern, div = KERNELS.get(method, KERNELS["floyd"])
    kx = np.array([k[0] for k in kern], np.int64)
    ky = np.array([k[1] for k in kern], np.int64)
    kw = np.array([k[2] for k in kern], np.float64)
    # nel buffer: 1 = bianco, così la soglia funziona come per la luminosità
    lum = 1.0 - dark.astype(np.float64)
    out = _diffuse(lum, kx, ky, kw, div)
    return (1 - out).astype(np.float32)


def _halftone(dark, cell, angle, dot_size=100.0):
    """Retino a punti tondi: l'area del punto è proporzionale allo scuro medio della cella. dot_size (%) ingrandisce
    o rimpicciolisce tutti i punti lasciando ferma la distanza fra loro (vedi core/halftone)."""
    from .halftone import clamp_size

    h, w = dark.shape
    cell = max(cell, 2.0)
    blur = cv2.GaussianBlur(dark.astype(np.float32), (0, 0), cell / 2.5)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = math.radians(angle)
    u = xx * math.cos(a) + yy * math.sin(a)
    v = -xx * math.sin(a) + yy * math.cos(a)
    du = (u / cell) - np.floor(u / cell) - 0.5
    dv = (v / cell) - np.floor(v / cell) - 0.5
    dist = np.sqrt(du * du + dv * dv)  # 0 al centro della cella, ~0.707 agli angoli
    radius = np.sqrt(np.clip(blur, 0, 1) / math.pi)  # area = scuro
    size = clamp_size(dot_size) / 100.0
    if size != 1.0:
        radius = radius * np.float32(size)
    return (dist <= radius).astype(np.float32)


def to_dark(pil_image):
    """PIL -> scuro 0..1 (trasparente = bianco)."""
    img = pil_image
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        arr = np.asarray(img).astype(np.float32) / 255.0
        lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
        alpha = arr[..., 3]
        lum = lum * alpha + (1.0 - alpha)
    else:
        lum = np.asarray(img.convert("L")).astype(np.float32) / 255.0
    return 1.0 - lum


def sample_to_grid(dark, shape_tf_inv, shape_w, shape_h, x0, y0, nx, ny, step):
    """Campiona l'immagine sulla griglia del laser.

    Griglia: colonna j -> x = x0 + j*step; riga i -> y = y0 + i*step (mm, Y su, coordinate piano).
    shape_tf_inv: QTransform piano -> locale immagine (0..w, 0..h, Y su)."""
    H, W = dark.shape
    jj, ii = np.meshgrid(np.arange(nx, dtype=np.float64), np.arange(ny, dtype=np.float64))
    bx = x0 + jj * step
    by = y0 + ii * step
    t = shape_tf_inv
    lx = t.m11() * bx + t.m21() * by + t.m31()
    ly = t.m12() * bx + t.m22() * by + t.m32()
    px = (lx / shape_w) * W - 0.5
    py = (1.0 - ly / shape_h) * H - 0.5
    out = cv2.remap(dark.astype(np.float32), px.astype(np.float32), py.astype(np.float32),
                    cv2.INTER_AREA if step * W / shape_w < 1 else cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
    inside = (lx >= 0) & (lx <= shape_w) & (ly >= 0) & (ly <= shape_h)
    out[~inside] = 0.0
    return out


def warmup():
    """Compila in anticipo il dithering (prima volta: ~1 s), così il primo lavoro non attende."""
    dither(np.random.rand(8, 8).astype(np.float32), "floyd")
