# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Geometria di base. Unità: millimetri, asse Y verso l'alto (come la macchina).

Le forme si descrivono con QPainterPath (curve di Bézier). Per il laser si
"appiattiscono" in polilinee con una tolleranza esplicita (default 0,01 mm),
così la qualità non dipende dallo zoom come accadrebbe con Qt.
"""
import math

import pyclipper
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QTransform

FLATTEN_TOL = 0.01  # mm
CLIP_SCALE = 10000.0  # Clipper lavora in interi: 0,1 µm di risoluzione


class Poly:
    """Polilinea: lista di punti (x, y) + chiusa/aperta."""

    __slots__ = ("pts", "closed")

    def __init__(self, pts, closed):
        self.pts = pts
        self.closed = closed

    def length(self):
        n = len(self.pts)
        s = sum(math.dist(self.pts[i], self.pts[i + 1]) for i in range(n - 1))
        if self.closed and n > 2:
            s += math.dist(self.pts[-1], self.pts[0])
        return s

    def bounds(self):
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        return min(xs), min(ys), max(xs), max(ys)

    def area(self):
        if not self.closed or len(self.pts) < 3:
            return 0.0
        a = 0.0
        p = self.pts
        for i in range(len(p)):
            x1, y1 = p[i]
            x2, y2 = p[(i + 1) % len(p)]
            a += x1 * y2 - x2 * y1
        return a / 2.0

    def reversed(self):
        return Poly(self.pts[::-1], self.closed)

    def __repr__(self):
        return f"Poly({len(self.pts)} pt, {'chiusa' if self.closed else 'aperta'})"


# ----------------------------------------------------------------- appiattimento
def _flatten_cubic(p0, p1, p2, p3, tol, out, depth=0):
    # distanza dei punti di controllo dalla corda: se piccola, la curva è "dritta"
    dx, dy = p3[0] - p0[0], p3[1] - p0[1]
    d2 = abs((p1[0] - p3[0]) * dy - (p1[1] - p3[1]) * dx)
    d3 = abs((p2[0] - p3[0]) * dy - (p2[1] - p3[1]) * dx)
    if depth > 16 or (d2 + d3) ** 2 <= tol * tol * 4 * (dx * dx + dy * dy) or (dx == 0 and dy == 0 and depth > 4):
        out.append(p3)
        return
    p01 = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    p12 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    p23 = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)
    p012 = ((p01[0] + p12[0]) / 2, (p01[1] + p12[1]) / 2)
    p123 = ((p12[0] + p23[0]) / 2, (p12[1] + p23[1]) / 2)
    mid = ((p012[0] + p123[0]) / 2, (p012[1] + p123[1]) / 2)
    _flatten_cubic(p0, p01, p012, mid, tol, out, depth + 1)
    _flatten_cubic(mid, p123, p23, p3, tol, out, depth + 1)


def flatten(path: QPainterPath, tol=FLATTEN_TOL, closed_hint=None):
    """QPainterPath -> [Poly]. Un sottopercorso è chiuso se finisce dove inizia."""
    polys = []
    cur = []
    n = path.elementCount()
    i = 0
    while i < n:
        e = path.elementAt(i)
        t = e.type
        if t == QPainterPath.ElementType.MoveToElement:
            if len(cur) > 1:
                polys.append(cur)
            cur = [(e.x, e.y)]
            i += 1
        elif t == QPainterPath.ElementType.LineToElement:
            cur.append((e.x, e.y))
            i += 1
        elif t == QPainterPath.ElementType.CurveToElement:
            c1 = (e.x, e.y)
            e2 = path.elementAt(i + 1)
            e3 = path.elementAt(i + 2)
            p0 = cur[-1] if cur else c1
            _flatten_cubic(p0, c1, (e2.x, e2.y), (e3.x, e3.y), tol, cur)
            i += 3
        else:
            i += 1
    if len(cur) > 1:
        polys.append(cur)
    out = []
    for pts in polys:
        clean = [pts[0]]
        for p in pts[1:]:
            if math.dist(p, clean[-1]) > 1e-6:
                clean.append(p)
        if len(clean) < 2:
            continue
        closed = math.dist(clean[0], clean[-1]) < 1e-4 and len(clean) > 2
        if closed:
            clean = clean[:-1]
        if closed_hint is True and len(clean) > 2:
            closed = True
        out.append(Poly(clean, closed))
    return out


def polys_to_path(polys):
    p = QPainterPath()
    for poly in polys:
        if not poly.pts:
            continue
        p.moveTo(*poly.pts[0])
        for pt in poly.pts[1:]:
            p.lineTo(*pt)
        if poly.closed:
            p.closeSubpath()
    return p


# ----------------------------------------------------------------- Clipper
def _to_clip(polys):
    return [[(int(round(x * CLIP_SCALE)), int(round(y * CLIP_SCALE))) for x, y in p.pts] for p in polys if len(p.pts) >= 3]


def _from_clip(paths, closed=True):
    return [Poly([(x / CLIP_SCALE, y / CLIP_SCALE) for x, y in path], closed) for path in paths if len(path) >= 2]


def offset(polys, delta, join="round", arc_tol=0.01):
    """Offset di contorni chiusi (delta > 0 = verso fuori). Le polilinee aperte diventano contorni di spessore 2·delta."""
    co = pyclipper.PyclipperOffset(2.0, arc_tol * CLIP_SCALE)
    jt = {"round": pyclipper.JT_ROUND, "miter": pyclipper.JT_MITER, "square": pyclipper.JT_SQUARE}[join]
    closed = [p for p in polys if p.closed]
    opened = [p for p in polys if not p.closed]
    if closed:
        co.AddPaths(_to_clip(closed), jt, pyclipper.ET_CLOSEDPOLYGON)
    for p in opened:
        path = [(int(round(x * CLIP_SCALE)), int(round(y * CLIP_SCALE))) for x, y in p.pts]
        if len(path) >= 2:
            co.AddPath(path, jt, pyclipper.ET_OPENROUND)
    return _from_clip(co.Execute(delta * CLIP_SCALE))


def boolean(subject, clip, op):
    """op: 'union' | 'difference' | 'intersection' | 'xor' su contorni chiusi (regola nonzero)."""
    pc = pyclipper.Pyclipper()
    s = _to_clip([p for p in subject if p.closed])
    c = _to_clip([p for p in clip if p.closed])
    if s:
        pc.AddPaths(s, pyclipper.PT_SUBJECT, True)
    if c:
        pc.AddPaths(c, pyclipper.PT_CLIP, True)
    ct = {"union": pyclipper.CT_UNION, "difference": pyclipper.CT_DIFFERENCE,
          "intersection": pyclipper.CT_INTERSECTION, "xor": pyclipper.CT_XOR}[op]
    if not s:
        return []
    res = pc.Execute(ct, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
    return _from_clip(res)


def union_all(polys):
    return boolean(polys, [], "union") if polys else []


def point_in_poly(pt, pts):
    x, y = pt
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def contains(outer: Poly, inner: Poly):
    """True se inner sta dentro outer (test su più punti, tollerante)."""
    if not outer.closed or len(outer.pts) < 3:
        return False
    ox0, oy0, ox1, oy1 = outer.bounds()
    ix0, iy0, ix1, iy1 = inner.bounds()
    if ix0 < ox0 or iy0 < oy0 or ix1 > ox1 or iy1 > oy1:
        return False
    step = max(1, len(inner.pts) // 8)
    probes = inner.pts[::step]
    hits = sum(point_in_poly(p, outer.pts) for p in probes)
    return hits >= max(1, int(len(probes) * 0.75))


# ----------------------------------------------------------------- utilità
def path_bounds(path: QPainterPath):
    r = path.boundingRect()
    return r


def transform_from_list(v):
    return QTransform(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8])


def transform_to_list(t: QTransform):
    return [t.m11(), t.m12(), t.m13(), t.m21(), t.m22(), t.m23(), t.m31(), t.m32(), t.m33()]


def rect_anchor(r: QRectF, anchor):
    """anchor: 0..8 come un tastierino (0 = basso-sinistra ... 8 = alto-destra) in coordinate Y-su."""
    col = anchor % 3
    row = anchor // 3
    x = r.left() + r.width() * col / 2.0
    y = r.top() + r.height() * row / 2.0  # top() è il minimo Y nel nostro sistema Y-su
    return QPointF(x, y)
