# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.3: foto ritagliata con una forma del disegno («Ritaglia la foto con la forma»).

Il dato: `ImageShape.clip` = elenco di pezzi, ogni pezzo un elenco di anelli [[x, y], ...] in mm **locali della foto**
(0..w × 0..h, Y in su, prima della sua trasformazione). Dentro un pezzo vale la regola pari/dispari (i buchi di una
lettera o di una cornice), fra pezzi diversi l'unione. Così la sagoma segue la foto in ogni trasformazione (scala,
rotazione, specchio, gruppi, copia, annulla) senza conti a parte: sul piano è sempre `tf.map(locale)`.

Un solo punto per le conversioni: forme del piano → locale (`pieces_from`), maschera sulla griglia del laser
(`grid_mask`, coordinate del piano, per il G-code), maschera sui pixel della foto (`pixel_mask`, per l'anteprima e le
esportazioni). Fuori dalla sagoma la foto non si vede e **non si incide** (potenza zero, anche in negativo).
"""
import math

import cv2
import numpy as np
from PySide6.QtCore import QPointF

SHIFT = 8  # cv2.fillPoly con coordinate a 1/256 di pixel
MAX_POINTS = 20000  # punti di una sagoma (oltre si semplifica: un testo lungo resta leggero da salvare)


def sanitize(clip):
    """Sagoma letta da un file: solo anelli con almeno 3 punti numerici. -> pezzi o None."""
    if not isinstance(clip, (list, tuple)):
        return None
    out = []
    for piece in clip:
        if not isinstance(piece, (list, tuple)):
            continue
        rings = []
        for ring in piece:
            try:
                pts = [(float(p[0]), float(p[1])) for p in ring]
            except (TypeError, ValueError, IndexError):
                continue
            pts = [p for p in pts if math.isfinite(p[0]) and math.isfinite(p[1])]
            if len(pts) >= 3:
                rings.append([[round(x, 4), round(y, 4)] for x, y in pts])
        if rings:
            out.append(rings)
    return out or None


def pieces_from(leaves, image_tf, tol=0.02):
    """Forme del disegno [(foglia, trasformazione completa)] → pezzi nelle coordinate locali della foto.
    Solo i contorni chiusi; le forme aperte si ignorano (chi chiama lo dice prima). -> pezzi o None."""
    from . import geom

    inv, ok = image_tf.inverted()
    if not ok:
        return None
    pieces = []
    for leaf, tf in leaves:
        rings = []
        for poly in geom.flatten(tf.map(leaf.local_path()), tol):
            if not poly.closed or len(poly.pts) < 3:
                continue
            ring = []
            for x, y in poly.pts:
                q = inv.map(QPointF(x, y))
                ring.append([round(q.x(), 4), round(q.y(), 4)])
            rings.append(ring)
        if rings:
            pieces.append(rings)
    n = sum(len(r) for p in pieces for r in p)
    if n > MAX_POINTS:  # semplifica tenendo la forma (passo più largo)
        return pieces_from(leaves, image_tf, tol * 2.5)
    return pieces or None


def _odd(px, py, ring):
    """Pari/dispari esatto: per ogni punto (px, py) quante volte una semiretta verso destra attraversa l'anello."""
    x1, y1 = ring[:, 0], ring[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    out = np.zeros(len(px), bool)
    for a in range(0, len(px), 4000):  # a pezzi: punti × lati resta piccolo in memoria
        qx, qy = px[a:a + 4000, None], py[a:a + 4000, None]
        cross = (y1 > qy) != (y2 > qy)
        with np.errstate(divide="ignore", invalid="ignore"):
            xc = x1 + (qy - y1) * (x2 - x1) / (y2 - y1)
        out[a:a + 4000] = ((cross & (qx < xc)).sum(axis=1) % 2) == 1
    return out


def _fill(shape, pieces, to_px):
    """Pari/dispari dentro ogni pezzo, unione fra i pezzi. to_px: array (n, 2) mm → (n, 2) pixel (centri).
    Un pixel è dentro se il suo **centro** è dentro: cv2.fillPoly dà l'interno, vicino al bordo (dove può sbagliare di
    un pixel) il conto si rifà esatto. Così nessun punto inciso ha il centro fuori dalla sagoma."""
    h, w = shape
    out = np.zeros((h, w), np.uint8)
    band = np.zeros((h, w), np.uint8)
    k = float(1 << SHIFT)
    rings_px = []
    for piece in pieces:
        acc = np.zeros((h, w), np.uint8)
        rp = []
        for ring in piece:
            px = to_px(np.asarray(ring, np.float64))
            if not np.isfinite(px).all():
                continue
            pts = np.round(px * k).astype(np.int64).astype(np.int32)
            buf = np.zeros((h, w), np.uint8)
            cv2.fillPoly(buf, [pts], 1, cv2.LINE_8, SHIFT)
            cv2.polylines(band, [pts], True, 1, 3, cv2.LINE_8, SHIFT)
            acc ^= buf
            rp.append(px)
        out |= acc
        rings_px.append(rp)
    ys, xs = np.nonzero(band)
    if len(xs):
        fx, fy = xs.astype(np.float64), ys.astype(np.float64)
        exact = np.zeros(len(xs), bool)
        for rp in rings_px:
            par = np.zeros(len(xs), bool)
            for px in rp:
                par ^= _odd(fx, fy, px)
            exact |= par
        out[ys, xs] = exact
    return out.astype(bool)


def grid_mask(clip, tf, x0, y0, nx, ny, step):
    """Celle della griglia del laser (colonna j → x0 + j·step, riga i → y0 + i·step, mm sul piano) dentro la sagoma."""
    if not clip:
        return np.ones((ny, nx), bool)
    m = np.array([[tf.m11(), tf.m12()], [tf.m21(), tf.m22()]], np.float64)
    d = np.array([tf.m31(), tf.m32()], np.float64)

    def to_px(a):
        p = a @ m + d  # locale → piano
        return np.column_stack(((p[:, 0] - x0) / step, (p[:, 1] - y0) / step))
    return _fill((ny, nx), clip, to_px)


def pixel_mask(clip, w_mm, h_mm, W, H):
    """Pixel della foto (riga 0 in alto) dentro la sagoma."""
    if not clip:
        return np.ones((H, W), bool)

    def to_px(a):
        return np.column_stack((a[:, 0] / max(w_mm, 1e-9) * W - 0.5, (1.0 - a[:, 1] / max(h_mm, 1e-9)) * H - 0.5))
    return _fill((H, W), clip, to_px)


def coverage(clip, w_mm, h_mm, n=200):
    """Parte della foto (0..1) che resta dentro la sagoma."""
    if not clip:
        return 1.0
    k = n / max(w_mm, h_mm, 1e-9)
    W, H = max(2, int(round(w_mm * k))), max(2, int(round(h_mm * k)))
    return float(pixel_mask(clip, w_mm, h_mm, W, H).mean())


def map_local(clip, old_tf, new_tf):
    """La foto cambia trasformazione o misure ma la sagoma deve restare dove è sul piano (Prepara foto, specchio nei
    pixel): locale vecchio → piano → locale nuovo."""
    if not clip:
        return clip
    inv, ok = new_tf.inverted()
    if not ok:
        return clip
    t = old_tf * inv
    out = []
    for piece in clip:
        rings = []
        for ring in piece:
            r = []
            for x, y in ring:
                q = t.map(QPointF(x, y))
                r.append([round(q.x(), 4), round(q.y(), 4)])
            rings.append(r)
        out.append(rings)
    return out


def clipped_image(pil, leaf):
    """La foto con la trasparenza fuori dalla sagoma (esportazioni, istantanee): RGBA, o la foto com'è senza sagoma."""
    clip = getattr(leaf, "clip", None)
    if not clip or pil is None:
        return pil
    from PIL import Image

    rgba = np.array(pil.convert("RGBA"))
    H, W = rgba.shape[:2]
    keep = pixel_mask(clip, leaf.w, leaf.h, W, H)
    rgba[..., 3] = np.where(keep, rgba[..., 3], 0).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def key(leaf):
    """Impronta della sagoma (per le anteprime in memoria): calcolata una volta per ogni sagoma."""
    clip = getattr(leaf, "clip", None)
    if not clip:
        return None
    ref = getattr(leaf, "_clip_ref", None)
    if ref is not clip:
        import hashlib
        import json

        leaf._clip_ref = clip
        leaf._clip_hash = hashlib.md5(json.dumps(clip).encode()).hexdigest()
    return leaf._clip_hash
