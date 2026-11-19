# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.9 (universalcinema-boop, GitHub, 19/11/2026): deformare un disegno con 4 punti o con 16 punti.

- **Prospettiva (4 punti)**: i quattro angoli dell'ingombro si spostano dove si vuole; il disegno segue con una
  trasformazione proiettiva (omografia): le rette restano rette, le parallele possono convergere. Serve per
  adattare un disegno a una superficie vista di sbieco o a un pezzo non squadrato.
- **Griglia (16 punti)**: una griglia 4 × 4 di punti di controllo sopra l'ingombro; il disegno segue una superficie
  di Bézier bicubica (prodotto di Bernstein). Con la griglia regolare è l'identità esatta; spostando i punti il
  disegno si piega in modo morbido (bandiere, scritte su una tazza vista di lato, onde).

Il risultato è sempre un tracciato (le curve si appiattiscono finemente e si rimappano punto per punto): fuori dalla
prospettiva una retta diventa una curva, quindi le Bézier originali non si possono tenere.

Unità: mm sul piano come si vede, dopo tutte le trasformazioni della forma (Shape.path()). Niente Qt nel calcolo
(solo per leggere e scrivere i QPainterPath alla fine).

Invarianti: con i punti al loro posto il risultato coincide con il disegno di partenza (entro la tolleranza di
appiattimento); un quadrilatero intrecciato o schiacciato (area quasi zero, punti in fila) si rifiuta prima di
deformare; i sottopercorsi chiusi restano chiusi.
"""
import math

import numpy as np

FLAT_TOL = 0.02  # mm: tolleranza dell'appiattimento delle curve per il risultato
PREVIEW_TOL = 0.25  # mm: per l'anteprima mentre si trascina
MIN_AREA_RATIO = 0.01  # il quadrilatero deve avere almeno l'1% dell'area dell'ingombro di partenza


# ------------------------------------------------------------------ punti di controllo
def corners(box):
    """I 4 angoli di un ingombro (x0, y0, x1, y1): in basso a sinistra, in basso a destra, in alto a destra, in
    alto a sinistra (in senso antiorario sul piano, con y verso l'alto)."""
    x0, y0, x1, y1 = _norm(box)
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def grid(box, n=4):
    """n × n punti regolari sull'ingombro, per righe dal basso: grid[r][c] = (x, y)."""
    x0, y0, x1, y1 = _norm(box)
    return [[(x0 + (x1 - x0) * c / (n - 1), y0 + (y1 - y0) * r / (n - 1)) for c in range(n)] for r in range(n)]


def _norm(box):
    x0, y0, x1, y1 = (float(v) for v in box)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


# ------------------------------------------------------------------ prospettiva
def homography(src, dst):
    """Matrice 3×3 che porta i 4 punti src nei 4 punti dst. ValueError se non esiste (punti in fila)."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    try:
        h = np.linalg.solve(np.array(A, float), np.array(b, float))
    except np.linalg.LinAlgError as exc:
        raise ValueError("punti degeneri") from exc
    H = np.append(h, 1.0).reshape(3, 3)
    if not np.all(np.isfinite(H)):
        raise ValueError("punti degeneri")
    return H


def quad_problem(quad, ref_area):
    """Perché questo quadrilatero non si può usare (codice), o None. "cross": i lati si incrociano o un angolo è
    rientrante (la prospettiva capovolgerebbe una parte del disegno); "flat": troppo schiacciato."""
    pts = [tuple(map(float, p)) for p in quad]
    if any(not (math.isfinite(x) and math.isfinite(y)) for x, y in pts):
        return "flat"
    area = 0.0
    signs = set()
    for i in range(4):
        (ax, ay), (bx, by), (cx, cy) = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        area += ax * by - bx * ay
        cr = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        scale = math.hypot(bx - ax, by - ay) * math.hypot(cx - bx, cy - by)
        if scale < 1e-12 or abs(cr) <= 1e-9 * scale:
            return "flat"  # due punti uguali o tre in fila: la prospettiva non esiste
        signs.add(cr > 0)
    area = abs(area) / 2.0
    if area < MIN_AREA_RATIO * max(ref_area, 1e-9):
        return "flat"
    if len(signs) != 1:
        return "cross"
    return None


def perspective_fn(box, quad):
    """Funzione (N×2) -> (N×2) che porta l'ingombro nel quadrilatero (4 angoli nell'ordine di corners)."""
    H = homography(corners(box), quad)

    def f(pts):
        P = np.asarray(pts, float).reshape(-1, 2)
        q = np.c_[P, np.ones(len(P))] @ H.T
        with np.errstate(divide="ignore", invalid="ignore"):
            return q[:, :2] / q[:, 2:3]
    return f


# ------------------------------------------------------------------ griglia di Bézier
def _bern3(t):
    t = np.clip(t, 0.0, 1.0)
    s = 1.0 - t
    return np.stack([s ** 3, 3 * s * s * t, 3 * s * t * t, t ** 3], axis=-1)


def grid_fn(box, ctrl):
    """Funzione (N×2) -> (N×2): superficie di Bézier bicubica con i 16 punti ctrl[r][c] (righe dal basso).
    Dentro l'ingombro di partenza è la superficie; un punto fuori (non succede con l'ingombro della selezione, ma
    può succedere per arrotondamento) prosegue con la pendenza del bordo invece di schiacciarsi sul bordo."""
    x0, y0, x1, y1 = _norm(box)
    w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    C = np.asarray(ctrl, float).reshape(4, 4, 2)

    def f(pts):
        P = np.asarray(pts, float).reshape(-1, 2)
        u = (P[:, 0] - x0) / w
        v = (P[:, 1] - y0) / h
        uc, vc = np.clip(u, 0, 1), np.clip(v, 0, 1)
        Bu, Bv = _bern3(uc), _bern3(vc)  # N×4
        out = np.einsum("nr,nc,rcd->nd", Bv, Bu, C)
        # sporgenze: si prosegue con la pendenza del bordo (derivata della superficie al bordo)
        du, dv = u - uc, v - vc
        if np.any(du) or np.any(dv):
            eps = 1e-4
            Bu2 = _bern3(np.clip(uc + eps, 0, 1))
            Bv2 = _bern3(np.clip(vc + eps, 0, 1))
            Bu1 = _bern3(np.clip(uc - eps, 0, 1))
            Bv1 = _bern3(np.clip(vc - eps, 0, 1))
            gu = (np.einsum("nr,nc,rcd->nd", Bv, Bu2, C) - np.einsum("nr,nc,rcd->nd", Bv, Bu1, C))
            gv = (np.einsum("nr,nc,rcd->nd", Bv2, Bu, C) - np.einsum("nr,nc,rcd->nd", Bv1, Bu, C))
            su = np.clip(uc + eps, 0, 1) - np.clip(uc - eps, 0, 1)
            sv = np.clip(vc + eps, 0, 1) - np.clip(vc - eps, 0, 1)
            out += gu / np.maximum(su, 1e-12)[:, None] * du[:, None] + gv / np.maximum(sv, 1e-12)[:, None] * dv[:, None]
        return out
    return f


def grid_problem(ctrl):
    """None se la griglia è usabile; "flat" se un punto non è un numero o tutti i punti sono quasi nello stesso posto."""
    C = np.asarray(ctrl, float).reshape(-1, 2)
    if not np.all(np.isfinite(C)):
        return "flat"
    span = C.max(0) - C.min(0)
    if span.min() < 1e-6:
        return "flat"
    return None


# ------------------------------------------------------------------ tracciati
def polylines(qpath, tol=FLAT_TOL, step=None):
    """QPainterPath -> [(N×2 array, chiuso?)] appiattito; step: lunghezza massima di un tratto (mm), None = libero."""
    from . import geom

    out = []
    for poly in geom.flatten(qpath, tol):
        pts = np.asarray(poly.pts, float)
        if len(pts) < 2:
            continue
        closed = bool(poly.closed)
        if closed:  # il lato che chiude va trattato come gli altri (si piega anche lui)
            pts = np.vstack([pts, pts[:1]])
        if step:
            pts = densify(pts, step)
        out.append((pts, closed))
    return out


def densify(pts, step):
    """Aggiunge punti sui tratti più lunghi di step (le rette si piegano solo dove ci sono punti)."""
    pts = np.asarray(pts, float)
    res = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        L = float(np.hypot(*(b - a)))
        n = int(math.ceil(L / step)) if L > step else 1
        for k in range(1, n + 1):
            res.append(a + (b - a) * (k / n))
    return np.asarray(res)


def apply(qpath, fn, tol=FLAT_TOL, step=None):
    """Il tracciato deformato (QPainterPath). fn: (N×2) -> (N×2)."""
    from PySide6.QtGui import QPainterPath

    out = QPainterPath()
    for pts, closed in polylines(qpath, tol, step):
        q = fn(pts)
        if not np.all(np.isfinite(q)):
            continue
        out.moveTo(float(q[0, 0]), float(q[0, 1]))
        last = len(q) - 1 if closed and np.allclose(q[0], q[-1]) else len(q)
        for x, y in q[1:last]:
            out.lineTo(float(x), float(y))
        if closed:
            out.closeSubpath()
    return out


def grid_step(box):
    """Passo dei punti aggiunti per la griglia: 1/200 del lato più lungo, fra 0,1 e 2 mm."""
    x0, y0, x1, y1 = _norm(box)
    return min(2.0, max(0.1, max(x1 - x0, y1 - y0) / 200.0))
