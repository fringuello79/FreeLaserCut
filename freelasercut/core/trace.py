# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Vettorizzazione delle immagini.

Due modi:
- contorno: i bordi delle zone scure diventano tracciati chiusi (per riempimenti e tagli);
- linea centrale: i tratti diventano una linea sola nel mezzo (scritte a mano, disegni a
  tratto, firme) — si incide in una passata invece di contornare due volte il tratto.

Le curve escono lisce (Bézier) ma gli spigoli veri restano spigoli: ogni vertice con
una svolta forte è un angolo, gli altri sono nodi morbidi.
"""
import math

import cv2
import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath

try:
    from numba import njit
except ImportError:  # pragma: no cover
    def njit(*a, **k):
        return (lambda f: f) if not a or not callable(a[0]) else a[0]


# ------------------------------------------------------------------ maschera
def otsu(dark):
    v = np.clip(dark * 255, 0, 255).astype(np.uint8)
    if int(v.max()) - int(v.min()) < 8:
        return 0.5
    t, _ = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t = float(t) / 255.0
    # Otsu con due soli livelli (disegno già in bianco e nero) mette la soglia su uno dei due: va nel mezzo
    lo, hi = float(v.min()) / 255.0, float(v.max()) / 255.0
    return min(max(t, lo + 0.1 * (hi - lo)), hi - 0.1 * (hi - lo)) if t <= lo + 1e-6 or t >= hi - 1e-6 else t


def prepare(dark, px_per_mm, target_px_mm=10.0, max_side=3000):
    """Ingrandisce le immagini piccole (bordi più lisci, sotto-pixel). Ritorna (img, fattore)."""
    h, w = dark.shape
    k = max(1.0, min(4.0, target_px_mm / max(px_per_mm, 1e-6)))
    k = min(k, max_side / max(h, w))
    k = max(k, min(1.0, max_side / max(h, w)))
    if abs(k - 1.0) < 0.05:
        return dark.astype(np.float32), 1.0
    out = cv2.resize(dark.astype(np.float32), (max(1, round(w * k)), max(1, round(h * k))),
                     interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA)
    return np.clip(out, 0, 1), k


def mask_of(dark, threshold=0.5, invert=False, despeckle_px=0):
    m = (dark > threshold) if not invert else (dark <= threshold)
    m = m.astype(np.uint8)
    if despeckle_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * despeckle_px + 1, 2 * despeckle_px + 1))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
    return m


# ------------------------------------------------------------------ contorni
def _smooth_closed(pts, sigma):
    if sigma <= 0 or len(pts) < 8:
        return pts
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    ext = np.concatenate([pts[-r:], pts, pts[:r]])
    x = np.convolve(ext[:, 0], k, "valid")
    y = np.convolve(ext[:, 1], k, "valid")
    return np.stack([x, y], 1)


def outlines(mask, tol_px=1.0, min_area_px=4.0, smooth_px=1.0):
    """Contorni chiusi (lista di array Nx2 in pixel). I fori sono contorni a sé (riempimento pari/dispari)."""
    cs, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in cs:
        if abs(cv2.contourArea(c)) < min_area_px:
            continue
        p = c.reshape(-1, 2).astype(np.float64)
        p = _smooth_closed(p, smooth_px)
        a = cv2.approxPolyDP(p.astype(np.float32).reshape(-1, 1, 2), tol_px, True).reshape(-1, 2).astype(np.float64)
        if len(a) >= 3:
            out.append(a)
    return out


# ------------------------------------------------------------------ linea centrale
@njit(cache=True)
def _thin(img):
    """Assottigliamento Zhang–Suen: img uint8 0/1, modificata sul posto."""
    h, w = img.shape
    changed = True
    marks = np.zeros_like(img)
    while changed:
        changed = False
        for step in range(2):
            n = 0
            for y in range(1, h - 1):
                for x in range(1, w - 1):
                    if img[y, x] == 0:
                        continue
                    p2 = img[y - 1, x]
                    p3 = img[y - 1, x + 1]
                    p4 = img[y, x + 1]
                    p5 = img[y + 1, x + 1]
                    p6 = img[y + 1, x]
                    p7 = img[y + 1, x - 1]
                    p8 = img[y, x - 1]
                    p9 = img[y - 1, x - 1]
                    b = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                    if b < 2 or b > 6:
                        continue
                    a = ((p2 == 0 and p3 == 1) + (p3 == 0 and p4 == 1) + (p4 == 0 and p5 == 1) + (p5 == 0 and p6 == 1)
                         + (p6 == 0 and p7 == 1) + (p7 == 0 and p8 == 1) + (p8 == 0 and p9 == 1) + (p9 == 0 and p2 == 1))
                    if a != 1:
                        continue
                    if step == 0:
                        if p2 * p4 * p6 != 0 or p4 * p6 * p8 != 0:
                            continue
                    else:
                        if p2 * p4 * p8 != 0 or p2 * p6 * p8 != 0:
                            continue
                    marks[y, x] = 1
                    n += 1
            if n:
                changed = True
                for y in range(1, h - 1):
                    for x in range(1, w - 1):
                        if marks[y, x]:
                            img[y, x] = 0
                            marks[y, x] = 0
    return img


_NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def skeleton(mask):
    m = np.pad(mask.astype(np.uint8), 1)
    _thin(m)
    return m[1:-1, 1:-1]


_RING = [(0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)]  # N, NE, E, SE, S, SW, W, NW


def _chains(sk):
    """Scheletro -> catene di pixel [(x, y)…], con il tipo degli estremi (1 = punta, 3 = incrocio, 0 = anello).

    I nodi si riconoscono dal numero di passaggi vuoto→pieno attorno al pixel (1 = punta,
    3 o più = incrocio): così gli "scalini" diagonali dello scheletro non diventano falsi incroci."""
    ys, xs = np.nonzero(sk)
    on = set(zip(xs.tolist(), ys.tolist()))
    if not on:
        return []

    def nbrs(p):
        x, y = p
        return [(x + dx, y + dy) for dx, dy in _RING if (x + dx, y + dy) in on]

    def kind(p):
        x, y = p
        ring = [(x + dx, y + dy) in on for dx, dy in _RING]
        t = sum(1 for i in range(8) if not ring[i] and ring[(i + 1) % 8])
        return t

    kinds = {p: kind(p) for p in on}
    nodes = {p for p, t in kinds.items() if t != 2}
    visited = set()
    out = []

    def step_order(cur, cands):
        return sorted(cands, key=lambda r: abs(r[0] - cur[0]) + abs(r[1] - cur[1]))

    def walk(start, first):
        ch = [start, first]
        visited.add(first)
        prev, cur = start, first
        while True:
            near_nodes = [r for r in nbrs(cur) if r in nodes and r != prev and (r != start or len(ch) > 3)]
            if near_nodes and cur not in nodes:
                ch.append(step_order(cur, near_nodes)[0])
                break
            cand = [r for r in nbrs(cur) if r not in visited and r not in nodes and r != prev]
            if not cand:
                break
            r = step_order(cur, cand)[0]
            visited.add(r)
            ch.append(r)
            prev, cur = cur, r
        return ch

    for n in sorted(nodes):
        visited.add(n)
        for q in nbrs(n):
            if q in visited or q in nodes:
                continue
            ch = walk(n, q)
            out.append((ch, kinds[ch[0]], kinds.get(ch[-1], 1) if ch[-1] in nodes else 1))
    # anelli senza nodi (una "o" chiusa)
    for p in sorted(on):
        if p in visited:
            continue
        visited.add(p)
        nb = [q for q in nbrs(p) if q not in visited]
        if not nb:
            continue
        ch = walk(p, nb[0])
        if max(abs(ch[-1][0] - p[0]), abs(ch[-1][1] - p[1])) <= 1 and len(ch) > 3:
            ch.append(p)
        out.append((ch, 0, 0))
    return out


def centerlines(mask, tol_px=1.0, min_len_px=4.0, smooth_px=1.0):
    """Linee centrali (lista di (array Nx2 in pixel, chiusa?))."""
    chains = _chains(skeleton(mask))
    out = []
    for ch, k0, k1 in chains:
        p = np.array(ch, np.float64)
        if len(p) < 2:
            continue
        length = float(np.sum(np.hypot(*np.diff(p, axis=0).T)))
        # le catene corte con una punta libera sono "baffi" dello scheletro (o puntini): via.
        # Quelle corte tra due incroci invece restano, altrimenti il disegno si spezza.
        if length < min_len_px and (k0 == 1 or k1 == 1 or (k0 == 0 and k1 == 0)):
            continue
        closed = len(ch) > 3 and ch[0] == ch[-1]
        if smooth_px > 0 and len(p) > 6:
            r = int(3 * smooth_px)
            k = np.exp(-0.5 * (np.arange(-r, r + 1) / smooth_px) ** 2)
            k /= k.sum()
            if closed:
                p = _smooth_closed(p[:-1], smooth_px)
            else:
                ext = np.concatenate([np.repeat(p[:1], r, 0), p, np.repeat(p[-1:], r, 0)])
                q = np.stack([np.convolve(ext[:, 0], k, "valid"), np.convolve(ext[:, 1], k, "valid")], 1)
                q[0], q[-1] = p[0], p[-1]  # gli estremi restano dove sono (si attaccano agli incroci)
                p = q
        a = cv2.approxPolyDP(p.astype(np.float32).reshape(-1, 1, 2), tol_px, closed).reshape(-1, 2).astype(np.float64)
        if len(a) >= 2:
            out.append((a, closed))
    return _join_chains(out, 1.5)


def _join_chains(items, gap):
    """Unisce le catene aperte che si toccano agli estremi (passano dritte attraverso gli incroci)."""
    opened = [list(map(tuple, a)) for a, c in items if not c]
    closed = [(a, True) for a, c in items if c]
    merged = True
    while merged:
        merged = False
        for i in range(len(opened)):
            for j in range(i + 1, len(opened)):
                a, b = opened[i], opened[j]
                for ra in (False, True):
                    for rb in (False, True):
                        aa = a[::-1] if ra else a
                        bb = b[::-1] if rb else b
                        if math.dist(aa[-1], bb[0]) <= gap and _straight(aa, bb):
                            opened[i] = aa + bb[1:]
                            del opened[j]
                            merged = True
                            break
                    if merged:
                        break
                if merged:
                    break
            if merged:
                break
    return closed + [(np.array(o), False) for o in opened]


def _straight(a, b):
    """Vero se passando da a a b la direzione cambia poco (< 35°)."""
    if len(a) < 2 or len(b) < 2:
        return True
    d1 = np.subtract(a[-1], a[-2])
    d2 = np.subtract(b[1], b[0])
    n1, n2 = np.hypot(*d1), np.hypot(*d2)
    if n1 < 1e-9 or n2 < 1e-9:
        return True
    return float(np.dot(d1, d2) / (n1 * n2)) > math.cos(math.radians(35))


# ------------------------------------------------------------------ curve
def _bezier_path(path, pts, closed, corner_deg):
    """Catmull-Rom -> Bézier, con gli angoli vivi dove la svolta supera corner_deg."""
    n = len(pts)
    if n < 2:
        return
    P = [QPointF(float(x), float(y)) for x, y in pts]
    cos_c = math.cos(math.radians(corner_deg))

    def corner(i):
        if not closed and (i == 0 or i == n - 1):
            return True
        a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        d1 = np.subtract(b, a)
        d2 = np.subtract(c, b)
        n1, n2 = np.hypot(*d1), np.hypot(*d2)
        if n1 < 1e-9 or n2 < 1e-9:
            return True
        return float(np.dot(d1, d2) / (n1 * n2)) < cos_c

    sharp = [corner(i) for i in range(n)]
    path.moveTo(P[0])
    segs = n if closed else n - 1
    for i in range(segs):
        i0, i1, i2, i3 = (i - 1) % n, i, (i + 1) % n, (i + 2) % n
        if not closed:
            i0, i3 = max(i - 1, 0), min(i + 2, n - 1)
        p0, p1, p2, p3 = P[i0], P[i1], P[i2], P[i3]
        if sharp[i1] and sharp[i2]:
            path.lineTo(p2)
            continue
        c1 = p1 if sharp[i1] else p1 + (p2 - p0) / 6.0
        c2 = p2 if sharp[i2] else p2 - (p3 - p1) / 6.0
        path.cubicTo(c1, c2, p2)
    if closed:
        path.closeSubpath()


def trace(dark, w_mm, h_mm, mode="outline", threshold=None, invert=False, detail=0.5, smooth=0.5,
          min_size_mm=0.3, corner_deg=55.0):
    """Immagine (scuro 0..1) -> QPainterPath in coordinate locali dell'immagine (mm, Y su).

    detail 0..1: quanto seguire i dettagli (tolleranza da 0,4 a 0,02 mm);
    smooth 0..1: quanto ammorbidire il bordo a pixel; min_size_mm: macchie e tratti più piccoli vengono ignorati.
    Ritorna (path, info) con info = dict(threshold, curves, nodes)."""
    H0, W0 = dark.shape
    px_mm = W0 / max(w_mm, 1e-6)
    img, k = prepare(dark, px_mm)
    H, W = img.shape
    pxmm = W / w_mm
    t = otsu(img) if threshold is None else threshold
    tol_mm = 0.4 * (1 - detail) + 0.02 * detail
    tol_px = max(0.25, tol_mm * pxmm)
    smooth_px = smooth * 0.08 * pxmm
    mask = mask_of(img, t, invert, despeckle_px=int(round(min_size_mm * 0.25 * pxmm)) if min_size_mm > 0 else 0)
    if mode == "centerline":
        items = centerlines(mask, tol_px, min_len_px=max(2.0, min_size_mm * 2 * pxmm), smooth_px=smooth_px)
    else:
        items = [(a, True) for a in outlines(mask, tol_px, min_area_px=(min_size_mm * pxmm) ** 2, smooth_px=smooth_px)]
    sx, sy = w_mm / W, h_mm / H
    path = QPainterPath()
    nodes = 0
    for pts, closed in items:
        mm = np.empty_like(pts)
        mm[:, 0] = (pts[:, 0] + 0.5) * sx
        mm[:, 1] = h_mm - (pts[:, 1] + 0.5) * sy
        if closed and len(mm) > 2 and np.hypot(*(mm[0] - mm[-1])) < 1e-6:
            mm = mm[:-1]
        _bezier_path(path, mm, closed, corner_deg)
        nodes += len(mm)
    return path, {"threshold": t, "curves": len(items), "nodes": nodes, "scale": k}
