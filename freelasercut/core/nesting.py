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
def _place_all(order, parts, angles, free, obst, cell, gap_r, margin_r, tick=None, skip_full=False):
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
    free_cells = float((body < 0.5).sum()) if skip_full else 0.0
    failed = set()  # forme identiche a una che non è entrata: non entrano nemmeno loro (il foglio si riempie soltanto)
    for idx in order:
        part = parts[idx]
        best = None
        sig = getattr(part, "sig", None) if skip_full else None
        if skip_full and (float(part.masks[angles[0]][0].sum()) > free_cells or (sig is not None and sig in failed)):
            unplaced.append(idx)
            if tick is not None and tick():
                raise InterruptedError
            continue
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
            if sig is not None:
                failed.add(sig)
        else:
            _, ang, i, j, h, w = best
            m = part.masks[ang][0].astype(np.float32)
            body[i:i + h, j:j + w] = np.maximum(body[i:i + h, j:j + w], m)
            items[i:i + h, j:j + w] = np.maximum(items[i:i + h, j:j + w], m)
            items_p[i + gap_r:i + gap_r + h, j + gap_r:j + gap_r + w] = items[i:i + h, j:j + w]
            ex, ey = max(ex, j + w), max(ey, i + h)
            placed[idx] = (ang, i, j)
            free_cells -= float(m.sum())
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


# ------------------------------------------------------------------ più pannelli
def nest_sheets(shapes, area_polys, obstacle_shapes=(), max_sheets=20, sheet_gap=20.0, keep_touching=True, **kw):
    """Come nest_shapes, ma i pezzi che non entrano vanno su altri pannelli uguali, affiancati a destra del primo.
    Ritorna (risultati, spostamenti_x): un Result per pannello usato e lo spostamento in X di ciascun pannello."""
    x0, _, x1, _ = _bounds(area_polys)
    pitch = (x1 - x0) + sheet_gap
    remaining = list(shapes)
    results, shifts = [], []
    for k in range(max_sheets):
        if not remaining:
            break
        dx = k * pitch
        area = [geom.Poly([(x + dx, y) for x, y in p.pts], p.closed) for p in area_polys]
        res = nest_shapes(remaining, area, obstacle_shapes if k == 0 else (), keep_touching=keep_touching, **kw)
        if not res.placements:
            break
        results.append(res)
        shifts.append(dx)
        placed = {s for g in res.placements for s in g}
        remaining = [s for s in remaining if s not in placed]
    return results, shifts


def nest_pieces(shapes, sheet_w, sheet_h, spacing=2.0, margin=1.0, angles=(0, 90), sheet_gap=20.0, tick=None):
    """Tanti pezzi singoli su fogli rettangolari uguali, affiancati a destra (come nest_sheets, ma svelto anche con
    centinaia di pezzi): ogni pezzo si prepara una volta sola, i pezzi più grandi del foglio si saltano subito, su un
    foglio ormai pieno non si provano i pezzi che non ci starebbero comunque.
    tick(frazione, fogli fatti, pezzi sistemati, pezzi) -> True per annullare (InterruptedError).
    Ritorna (Result per foglio, spostamenti in X dei fogli, forme rimaste fuori)."""
    cell = min(2.0, max(0.2, math.sqrt(sheet_w * sheet_h / 300000.0)))
    gap_r = int(math.ceil(spacing / cell)) + (1 if spacing > 0 else 0)
    margin_r = int(math.ceil(margin / cell)) if margin > 0 else 0
    W = int(math.ceil(sheet_w / cell)) + 1
    H = int(math.ceil(sheet_h / cell)) + 1
    sheet = [geom.Poly([(0.0, 0.0), (sheet_w, 0.0), (sheet_w, sheet_h), (0.0, sheet_h)], True)]
    free = _raster(sheet, 0.0, 0.0, cell, W, H, fill_holes=False, stroke=0)
    obst = np.zeros((H, W), np.uint8)
    total = len(shapes)

    def report(frac, sheets, done):
        if tick is not None and tick(min(1.0, frac), sheets, done, total):
            raise InterruptedError

    parts, left = [], []
    for n, s in enumerate(shapes):
        p = make_part((s,), shape_polys(s))
        if p is None:
            left.append(s)
        else:
            _prepare(p, angles, cell, gap_r, True)
            m0 = p.masks[angles[0]][0]
            p.sig = (m0.shape, hash(m0.tobytes()))  # pezzi uguali (fette di un oggetto estruso) si riconoscono
            fits = any(p.masks[a][0].shape[0] <= H - 2 * margin_r and p.masks[a][0].shape[1] <= W - 2 * margin_r
                       for a in angles)
            (parts if fits else left).append(p if fits else s)
        report(0.25 * (n + 1) / max(total, 1), 0, 0)
    pitch = sheet_w + sheet_gap
    results, shifts = [], []
    remaining = list(range(len(parts)))
    done = 0
    while remaining:
        k = len(results)
        order = sorted(remaining, key=lambda i: -parts[i].area_mm2)
        tried = [0]

        def step():
            tried[0] += 1
            report(0.25 + 0.75 * (done + tried[0] / len(order) * 0.5) / max(len(parts), 1), k, done)
            return False

        placed, unplaced, (ex, ey), area = _place_all(order, parts, angles, free, obst, cell, gap_r, margin_r,
                                                      tick=step, skip_full=True)
        if not placed:
            break
        tfs = {parts[i].key: _transform(parts[i], ang, k * pitch + j * cell, r * cell)
               for i, (ang, r, j) in placed.items()}
        results.append(Result(tfs, [], ex * cell, ey * cell, area, cell))
        shifts.append(k * pitch)
        done += len(placed)
        remaining = unplaced
        report(0.25 + 0.75 * done / max(len(parts), 1), k + 1, done)
    left += [parts[i].key[0] for i in remaining]
    return results, shifts, left


# ------------------------------------------------------------------ linee di taglio comuni
def _slide(a_pts, a_edges, b_pts, b_edges, axis):
    """Quanto può scorrere A verso il basso dell'asse (0 = X, 1 = Y) prima di toccare B. inf = mai."""
    best = math.inf
    o = 1 - axis
    for pts, edges, sign in ((a_pts, b_edges, 1.0), (b_pts, a_edges, -1.0)):
        if not len(pts) or not len(edges):
            continue
        p1, p2 = edges[:, 0, :], edges[:, 1, :]
        lo = np.minimum(p1[:, o], p2[:, o])
        hi = np.maximum(p1[:, o], p2[:, o])
        d = p2[:, o] - p1[:, o]
        valid = np.abs(d) > 1e-12
        po = pts[:, o][:, None]
        inside = (po >= lo[None, :] - 1e-9) & (po <= hi[None, :] + 1e-9) & valid[None, :]
        with np.errstate(divide="ignore", invalid="ignore"):
            hit = p1[:, axis][None, :] + (po - p1[:, o][None, :]) * (p2[:, axis] - p1[:, axis])[None, :] / d[None, :]
        t = (pts[:, axis][:, None] - hit) * sign  # A scende verso -asse: distanza fino al bordo di B sotto
        t = np.where(inside & (t >= -1e-6), t, np.inf)
        best = min(best, float(t.min()) if t.size else math.inf)
    return max(best, 0.0)


def _arr(polys):
    pts, edges = [], []
    for p in polys:
        q = p.pts
        if len(q) < 2:
            continue
        pts.extend(q)
        n = len(q)
        for i in range(n if p.closed else n - 1):
            edges.append((q[i], q[(i + 1) % n]))
    return np.asarray(pts, float).reshape(-1, 2), np.asarray(edges, float).reshape(-1, 2, 2)


def compact(parts, static, passes=3):
    """parts: [[Poly]] già sistemati; static: [Poly] (bordo del materiale, ostacoli). Fa scivolare ogni pezzo
    verso sinistra e verso il basso finché tocca davvero qualcosa: le linee vicine diventano coincidenti.
    Ritorna gli spostamenti [(dx, dy)] di ogni pezzo."""
    arrs = [list(_arr(p)) for p in parts]
    st = _arr(static)
    moves = [[0.0, 0.0] for _ in parts]
    for _ in range(passes):
        moved = False
        for i in range(len(parts)):
            for axis in (0, 1):
                a_pts, a_edges = arrs[i]
                if not len(a_pts):
                    continue
                d = _slide(a_pts, a_edges, st[0], st[1], axis)
                for j in range(len(parts)):
                    if j != i and len(arrs[j][0]):
                        d = min(d, _slide(a_pts, a_edges, arrs[j][0], arrs[j][1], axis))
                if 1e-6 < d < math.inf:
                    a_pts = a_pts.copy()
                    a_edges = a_edges.copy()
                    a_pts[:, axis] -= d
                    a_edges[:, :, axis] -= d
                    arrs[i] = [a_pts, a_edges]
                    moves[i][axis] -= d
                    moved = True
        if not moved:
            break
    return [tuple(m) for m in moves]


def merge_common_lines(polys, tol=0.05):
    """Contorni di taglio -> polilinee senza tratti percorsi due volte (i lati in comune fra pezzi vicini si
    tagliano una volta sola). Ritorna (polilinee, mm risparmiati)."""
    segs = []
    for p in polys:
        q = p.pts
        n = len(q)
        for i in range(n if p.closed else n - 1):
            a, b = q[i], q[(i + 1) % n]
            if math.dist(a, b) > 1e-9:
                segs.append((a, b))
    keep = [[(0.0, 1.0)] for _ in segs]  # intervalli rimasti di ogni segmento
    saved = 0.0
    cell = 5.0
    grid = {}
    for i, (a, b) in enumerate(segs):
        for gx in range(int(min(a[0], b[0]) // cell), int(max(a[0], b[0]) // cell) + 1):
            for gy in range(int(min(a[1], b[1]) // cell), int(max(a[1], b[1]) // cell) + 1):
                grid.setdefault((gx, gy), []).append(i)
    seen = set()
    for idx in grid.values():
        for ii in range(len(idx)):
            for jj in range(ii + 1, len(idx)):
                i, j = idx[ii], idx[jj]
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                (a1, a2), (b1, b2) = segs[i], segs[j]
                L = math.dist(a1, a2)
                ux, uy = (a2[0] - a1[0]) / L, (a2[1] - a1[1]) / L

                def dist_line(p):
                    return abs((p[0] - a1[0]) * uy - (p[1] - a1[1]) * ux)
                if dist_line(b1) > tol or dist_line(b2) > tol:
                    continue
                # j sulla stessa retta di i: tolgo da j la parte che si sovrappone a i
                tb1 = ((b1[0] - a1[0]) * ux + (b1[1] - a1[1]) * uy)
                tb2 = ((b2[0] - a1[0]) * ux + (b2[1] - a1[1]) * uy)
                lo, hi = max(0.0, min(tb1, tb2)), min(L, max(tb1, tb2))
                if hi - lo <= tol:
                    continue
                Lb = abs(tb2 - tb1)
                # intervallo sovrapposto nella parametrizzazione di j
                s_lo, s_hi = sorted(((lo - tb1) / (tb2 - tb1), (hi - tb1) / (tb2 - tb1)))
                new = []
                for u0, u1 in keep[j]:
                    if u1 <= s_lo or u0 >= s_hi:
                        new.append((u0, u1))
                        continue
                    saved += (min(u1, s_hi) - max(u0, s_lo)) * Lb
                    if u0 < s_lo:
                        new.append((u0, s_lo))
                    if u1 > s_hi:
                        new.append((s_hi, u1))
                keep[j] = new
    pieces = []
    for (a, b), ivs in zip(segs, keep):
        for u0, u1 in ivs:
            if (u1 - u0) * math.dist(a, b) > 1e-6:
                pieces.append(((a[0] + (b[0] - a[0]) * u0, a[1] + (b[1] - a[1]) * u0),
                               (a[0] + (b[0] - a[0]) * u1, a[1] + (b[1] - a[1]) * u1)))
    return _chain(pieces, tol), saved


def _chain(pieces, tol):
    """Segmenti -> polilinee unendo gli estremi che coincidono."""
    def key(p):
        return (round(p[0] / tol), round(p[1] / tol))

    ends = {}
    for i, (a, b) in enumerate(pieces):
        ends.setdefault(key(a), []).append((i, 0))
        ends.setdefault(key(b), []).append((i, 1))
    used = [False] * len(pieces)
    out = []
    for i in range(len(pieces)):
        if used[i]:
            continue
        used[i] = True
        line = [pieces[i][0], pieces[i][1]]
        for direction in (1, 0):  # prolungo dalla fine, poi dall'inizio
            while True:
                tip = line[-1] if direction else line[0]
                nxt = None
                for j, end in ends.get(key(tip), []):
                    if not used[j]:
                        nxt = (j, end)
                        break
                if nxt is None:
                    break
                j, end = nxt
                used[j] = True
                other = pieces[j][1 - end]
                if direction:
                    line.append(other)
                else:
                    line.insert(0, other)
        closed = len(line) > 3 and math.dist(line[0], line[-1]) <= tol
        if closed:
            line = line[:-1]
        out.append(geom.Poly(line, closed))
    return out
