# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Ottimizza lo spazio («nesting»): dispone pezzi e gruppi sul materiale sprecandone il meno possibile.

Metodo: ogni pezzo diventa una maschera raster (cella di qualche decimo di mm) con la sua sagoma vera, non il
rettangolo che la contiene. Per ogni pezzo, in ordine di grandezza, e per ogni rotazione ammessa, una sola
correlazione (OpenCV) dice in quali posizioni non tocca né i pezzi già messi né gli ostacoli, rispettando la
distanza chiesta. Tra le posizioni libere si sceglie quella che tiene più piccolo il rettangolo di materiale
usato, a partire dall'angolo dell'origine (in basso a sinistra, come la macchina). Si provano alcuni ordini
diversi e si tiene il risultato migliore.

Nessuna interfaccia: si collauda da solo (tests/test_v08.py).
"""
import math
from dataclasses import dataclass, field

import cv2
import numpy as np
import pyclipper
from PySide6.QtGui import QTransform

from . import geom

ROT_CHOICES = {"none": (0,), "180": (0, 180), "90": (0, 90, 180, 270), "45": tuple(range(0, 360, 45)),
               "15": tuple(range(0, 360, 15))}


@dataclass
class Part:
    key: object
    polys: list  # [geom.Poly] nel sistema del piano (mm)
    area_mm2: float = 0.0
    masks: dict = field(default_factory=dict)  # angolo -> (maschera, maschera dilatata, minx, miny)


@dataclass
class Result:
    placements: dict  # key -> QTransform da applicare (dopo quella esistente)
    unplaced: list
    used_w: float = 0.0  # mm, dal bordo del materiale verso destra
    used_h: float = 0.0
    parts_area: float = 0.0
    cell: float = 0.0

    @property
    def efficiency(self):
        a = self.used_w * self.used_h
        return 0.0 if a <= 0 else min(1.0, self.parts_area / a)


# ------------------------------------------------------------------ raster
def _raster(polys, ox, oy, cell, w, h, fill_holes=True, stroke=1):
    """Poligoni (mm) -> maschera uint8 h×w (riga 0 = y più bassa)."""
    img = np.zeros((h, w), np.uint8)
    closed, opened = [], []
    for p in polys:
        if len(p.pts) < 2:
            continue
        a = np.asarray(p.pts, np.float64)
        pix = np.round(np.column_stack(((a[:, 0] - ox) / cell, (a[:, 1] - oy) / cell)) * 16).astype(np.int32)
        (closed if p.closed and len(p.pts) >= 3 else opened).append(pix)
    if closed:
        cv2.fillPoly(img, closed, 1, lineType=cv2.LINE_8, shift=4)
        if stroke > 0:
            cv2.polylines(img, closed, True, 1, stroke, cv2.LINE_8, 4)  # anche i bordi sottili contano
    if opened and stroke > 0:
        cv2.polylines(img, opened, False, 1, stroke, cv2.LINE_8, 4)
    if fill_holes and img.any():
        cnts, _ = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, cnts, -1, 1, thickness=cv2.FILLED)
    return img


def _rotated(polys, angle, cx, cy):
    if angle % 360 == 0:
        return polys
    t = math.radians(angle)
    c, s = math.cos(t), math.sin(t)
    out = []
    for p in polys:
        out.append(geom.Poly([((x - cx) * c - (y - cy) * s, (x - cx) * s + (y - cy) * c) for x, y in p.pts], p.closed))
    return out


def _bounds(polys):
    xs = [x for p in polys for x, _ in p.pts]
    ys = [y for p in polys for _, y in p.pts]
    return min(xs), min(ys), max(xs), max(ys)


def _kernel(r):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)) if r > 0 else None


# ------------------------------------------------------------------ pezzi
def make_part(key, polys):
    polys = [p for p in polys if len(p.pts) >= 2]
    return Part(key, polys) if polys else None


def _prepare(part, angles, cell, gap_r, fill_holes):
    x0, y0, x1, y1 = _bounds(part.polys)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    kern = _kernel(gap_r)
    for ang in angles:
        rp = _rotated(part.polys, ang, cx, cy) if ang else [geom.Poly([(x - cx, y - cy) for x, y in p.pts], p.closed)
                                                            for p in part.polys]
        mx, my, Mx, My = _bounds(rp)
        w = max(1, int(math.ceil((Mx - mx) / cell)) + 1)
        h = max(1, int(math.ceil((My - my) / cell)) + 1)
        m = _raster(rp, mx, my, cell, w, h, fill_holes)
        if kern is not None:
            d = cv2.copyMakeBorder(m, gap_r, gap_r, gap_r, gap_r, cv2.BORDER_CONSTANT, value=0)
            d = cv2.dilate(d, kern)
        else:
            d = m.copy()
        part.masks[ang] = (m, d, mx, my, cx, cy)
    part.area_mm2 = float(part.masks[angles[0]][0].sum()) * cell * cell


def _transform(part, ang, x, y):
    """QTransform che porta il pezzo ruotato di ang con l'angolo minimo in (x, y)."""
    m, d, mx, my, cx, cy = part.masks[ang]
    rot = QTransform()
    rot.rotate(ang)
    return QTransform.fromTranslate(-cx, -cy) * rot * QTransform.fromTranslate(x - mx, y - my)


# ------------------------------------------------------------------ piazzamento
def _place_all(order, parts, angles, free, obst, cell, gap_r, margin_r, tick=None):
    """free: uint8 H×W (1 = materiale); obst: uint8 H×W (1 = ostacolo). Ritorna (piazzati, non piazzati, estensioni, area).

    Due griglie: «corpo» (fuori dal materiale, col margine dal bordo, + ostacoli + pezzi) che il pezzo non deve
    toccare, e «oggetti» (ostacoli + pezzi) che non deve toccare nemmeno con l'alone della distanza tra pezzi."""
    H, W = free.shape
    outside = (1 - free).astype(np.float32)
    if margin_r > 0:  # il bordo del materiale (anche quello esterno alla griglia) cresce verso l'interno
        r = margin_r
        outside = cv2.dilate(cv2.copyMakeBorder(outside, r, r, r, r, cv2.BORDER_CONSTANT, value=1.0), _kernel(r))[r:-r, r:-r]
    items = obst.astype(np.float32)
    body = np.maximum(outside, items)
    items_p = cv2.copyMakeBorder(items, gap_r, gap_r, gap_r, gap_r, cv2.BORDER_CONSTANT, value=0.0)
    ex = ey = 0
    placed, unplaced, area = {}, [], 0.0
    for idx in order:
        part = parts[idx]
        best = None
        for ang in angles:
            m, d, *_ = part.masks[ang]
            h, w = m.shape
            if h > H or w > W:
                continue
            hit = cv2.matchTemplate(body, m.astype(np.float32), cv2.TM_CCORR)
            if gap_r:
                halo = cv2.matchTemplate(items_p, d.astype(np.float32), cv2.TM_CCORR)
                hit = np.maximum(hit, halo)
            ok = hit < 0.5
            if not ok.any():
                continue
            rows = np.arange(ok.shape[0], dtype=np.float64)[:, None]
            cols = np.arange(ok.shape[1], dtype=np.float64)[None, :]
            score = np.maximum(ex, cols + w) * np.maximum(ey, rows + h) * 1e6 + rows * (W + 1) + cols
            score = np.where(ok, score, np.inf)
            k = int(np.argmin(score))
            i, j = divmod(k, ok.shape[1])
            if best is None or score[i, j] < best[0]:
                best = (score[i, j], ang, i, j, h, w)
        if best is None:
            unplaced.append(idx)
        else:
            _, ang, i, j, h, w = best
            m = part.masks[ang][0].astype(np.float32)
            body[i:i + h, j:j + w] = np.maximum(body[i:i + h, j:j + w], m)
            items[i:i + h, j:j + w] = np.maximum(items[i:i + h, j:j + w], m)
            items_p[i + gap_r:i + gap_r + h, j + gap_r:j + gap_r + w] = items[i:i + h, j:j + w]
            ex, ey = max(ex, j + w), max(ey, i + h)
            placed[idx] = (ang, i, j)
            area += part.area_mm2
        if tick is not None and tick():
            raise InterruptedError
    return placed, unplaced, (ex, ey), area


def nest(parts, area_polys, obstacles=(), spacing=2.0, margin=1.0, rotations="90", fill_holes=True,
         precision="normal", tries=3, tick=None):
    """parts: [Part]; area_polys: contorno del materiale (poligoni chiusi, mm); obstacles: [Poly] da evitare.
    Ritorna Result con una QTransform per ogni pezzo piazzato (chiave del pezzo)."""
    angles = ROT_CHOICES.get(rotations, (0,))
    ax0, ay0, ax1, ay1 = _bounds(area_polys)
    aw, ah = ax1 - ax0, ay1 - ay0
    cell = min(2.0, max(0.2, math.sqrt(aw * ah / (300000.0 if precision == "normal" else 1200000.0))))
    gap_r = int(math.ceil(spacing / cell)) + (1 if spacing > 0 else 0)
    margin_r = int(math.ceil(margin / cell)) if margin > 0 else 0
    W = int(math.ceil(aw / cell)) + 1
    H = int(math.ceil(ah / cell)) + 1
    free = _raster(area_polys, ax0, ay0, cell, W, H, fill_holes=False, stroke=0)
    obst = _raster(list(obstacles), ax0, ay0, cell, W, H, fill_holes=True) if obstacles else np.zeros((H, W), np.uint8)
    parts = [p for p in parts if p is not None]
    for p in parts:
        _prepare(p, angles, cell, gap_r, fill_holes)

    def dims(p):
        m = p.masks[angles[0]][0]
        return m.shape

    orders = [sorted(range(len(parts)), key=lambda k: -parts[k].area_mm2),
              sorted(range(len(parts)), key=lambda k: -max(dims(parts[k]))),
              sorted(range(len(parts)), key=lambda k: -dims(parts[k])[0] * 10000 - dims(parts[k])[1])][:max(1, tries)]
    best = None
    for order in orders:
        placed, unplaced, (ex, ey), area = _place_all(order, parts, angles, free, obst, cell, gap_r, margin_r, tick=tick)
        key = (len(unplaced), ex * ey)
        if best is None or key < best[0]:
            best = (key, placed, unplaced, ex, ey, area)
    _, placed, unplaced, ex, ey, area = best
    tfs = {}
    for idx, (ang, i, j) in placed.items():
        tfs[parts[idx].key] = _transform(parts[idx], ang, ax0 + j * cell, ay0 + i * cell)
    return Result(tfs, [parts[i].key for i in unplaced], ex * cell, ey * cell, area, cell)


# ------------------------------------------------------------------ aiuti per l'editor
def outer_region(polys):
    """Contorni chiusi -> regione piena (fori riempiti) come percorsi Clipper; i contorni aperti contano col
    loro rettangolo."""
    pc = pyclipper.Pyclipper()
    any_path = False
    for p in polys:
        if p.closed and len(p.pts) >= 3:
            pts = p.pts if p.area() >= 0 else p.pts[::-1]
        else:
            x0, y0, x1, y1 = p.bounds()
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        sc = [(int(x * 1000), int(y * 1000)) for x, y in pts]
        if len(set(sc)) >= 3:
            pc.AddPath(sc, pyclipper.PT_SUBJECT, True)
            any_path = True
    if not any_path:
        return []
    return pc.Execute(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)


def _area(paths):
    return sum(pyclipper.Area(p) for p in paths) / 1e6


def clusters(items):
    """items: [(chiave, polys)] -> gruppi di chiavi che stanno una dentro l'altra (si spostano insieme): per esempio
    un'incisione dentro il suo contorno di taglio. Le copie sovrapposte (stessa grandezza o solo in parte una
    sull'altra) restano pezzi separati, così il nesting le può distribuire."""
    n = len(items)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    regions = [outer_region(p) for _, p in items]
    areas = [abs(_area(r)) for r in regions]
    boxes = [_bounds(p) if p else None for _, p in items]
    for a in range(n):
        for b in range(a + 1, n):
            ba, bb = boxes[a], boxes[b]
            if ba is None or bb is None or ba[2] < bb[0] or bb[2] < ba[0] or ba[3] < bb[1] or bb[3] < ba[1]:
                continue
            if not regions[a] or not regions[b]:
                continue
            aa, ab = areas[a], areas[b]
            small, large = (b, a) if ab <= aa else (a, b)
            if areas[small] > 0.98 * areas[large]:  # copie della stessa forma: separate
                continue
            pc = pyclipper.Pyclipper()
            pc.AddPaths(regions[large], pyclipper.PT_SUBJECT, True)
            pc.AddPaths(regions[small], pyclipper.PT_CLIP, True)
            inter = pc.Execute(pyclipper.CT_INTERSECTION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
            if inter and _area(inter) >= 0.99 * areas[small]:  # una dentro l'altra
                parent[find(a)] = find(b)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(items[i][0])
    return list(groups.values())


def shape_polys(shape, tol=0.1):
    return geom.flatten(shape.path(), tol)


def nest_shapes(shapes, area_polys, obstacle_shapes=(), keep_touching=True, **kw):
    """Forme del documento -> Result con chiave = tupla delle forme che si spostano insieme.
    Le forme che si toccano o stanno una dentro l'altra restano unite (keep_touching)."""
    polys = {s: shape_polys(s) for s in shapes}
    items = [(s, polys[s]) for s in shapes if polys[s]]
    groups = clusters(items) if keep_touching else [[s] for s, _ in items]
    parts = [make_part(tuple(g), [p for s in g for p in polys[s]]) for g in groups]
    obstacles = [p for s in obstacle_shapes for p in shape_polys(s, 0.2)]
    return nest([p for p in parts if p is not None], area_polys, obstacles, **kw)


def apply(result):
    """Applica i piazzamenti alle forme (da chiamare dentro Editor.run, così si annulla con Ctrl+Z)."""
    for group, tf in result.placements.items():
        for s in group:
            s.apply(tf)
