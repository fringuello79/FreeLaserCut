# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Operazioni di modifica sulle forme (senza interfaccia, quindi collaudabili).

Convenzioni: coordinate piano in mm, Y verso l'alto. Le funzioni restituiscono
nuove forme oppure modificano le trasformazioni; la cronologia (annulla/ripeti)
la gestisce l'editor.
"""
import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QTransform

from . import geom, nodes
from .document import GroupShape, ImageShape, PathShape, Shape, TextShape


def union_bounds(shapes):
    r = QRectF()
    for s in shapes:
        b = s.bounds()
        r = b if r.isNull() else r.united(b)
    return r


def about(tf, cx, cy):
    """Trasformazione tf applicata attorno al punto (cx, cy)."""
    return QTransform.fromTranslate(-cx, -cy) * tf * QTransform.fromTranslate(cx, cy)


def transform_all(shapes, tf):
    for s in shapes:
        s.apply(tf)


# ------------------------------------------------------------------ conversioni
def to_path(shape):
    """Qualsiasi forma vettoriale -> PathShape con la geometria nel sistema del piano."""
    if isinstance(shape, (ImageShape, GroupShape)):
        return None
    p = PathShape(shape.path(), layer=shape.layer)
    return p


def world_subpaths(shape):
    return nodes.from_path(shape.path())


def from_subpaths(subs, layer):
    return PathShape(nodes.to_path(subs), layer=layer)


# ------------------------------------------------------------------ gruppi
def group(shapes):
    g = GroupShape([s for s in shapes], layer=shapes[0].layer if shapes else 1)
    return g


def ungroup(g: GroupShape):
    out = []
    for c in g.children:
        c.tf = c.tf * g.tf
        c.invalidate()
        out.append(c)
    return out


# ------------------------------------------------------------------ booleane
def closed_polys(shapes, tol=0.01):
    polys = []
    for s in shapes:
        for leaf, tf in s.leaves():
            if isinstance(leaf, ImageShape):
                continue
            polys += [p for p in geom.flatten(tf.map(leaf.local_path()), tol) if p.closed]
    return polys


def weld(shapes):
    polys = geom.union_all(closed_polys(shapes))
    return PathShape(geom.polys_to_path(polys), layer=shapes[0].layer) if polys else None


def boolean(a, b, op):
    """op: union | difference | intersection | xor  (difference = a meno b)."""
    res = geom.boolean(closed_polys([a]), closed_polys([b]), op)
    return PathShape(geom.polys_to_path(res), layer=a.layer) if res else None


def break_apart(shape):
    subs = world_subpaths(shape)
    if len(subs) <= 1:
        return None
    return [from_subpaths([sp], shape.layer) for sp in subs]


def close_paths(shapes, tol=0.5):
    out, closed = [], 0
    for s in shapes:
        subs = world_subpaths(s)
        k = nodes.close_subpaths(subs, tol)
        closed += k
        out.append(from_subpaths(subs, s.layer) if k else None)
    return out, closed


def auto_join(shapes, tol=0.05):
    subs = []
    for s in shapes:
        subs += world_subpaths(s)
    before = len(subs)
    nodes.join_endpoints(subs, tol)
    return from_subpaths(subs, shapes[0].layer), before - len(subs)


def reverse(shape):
    subs = world_subpaths(shape)
    for sp in subs:
        nodes.reverse(sp)
    return from_subpaths(subs, shape.layer)


def offset_shapes(shapes, distance, direction="out", corner="round", outer_only=False):
    """Contorno parallelo. direction: out | in | both. Ritorna [PathShape]."""
    polys = []
    for s in shapes:
        for leaf, tf in s.leaves():
            if not isinstance(leaf, ImageShape):
                polys += geom.flatten(tf.map(leaf.local_path()), 0.01)
    from .gcode import _depths, _orient

    if outer_only:
        d = _depths([p for p in polys if p.closed])
        closed = [p for p, k in zip([p for p in polys if p.closed], d) if k == 0]
        polys = closed + [p for p in polys if not p.closed]
    polys = _orient([p for p in polys if p.closed]) + [p for p in polys if not p.closed]
    layer = shapes[0].layer
    res = []
    if direction in ("out", "both"):
        r = geom.offset(polys, abs(distance), corner)
        if r:
            res.append(PathShape(geom.polys_to_path(r), layer=layer))
    if direction in ("in", "both"):
        r = geom.offset([p for p in polys if p.closed], -abs(distance), corner)
        if r:
            res.append(PathShape(geom.polys_to_path(r), layer=layer))
    return res


# ------------------------------------------------------------------ allinea / distribuisci
def align(shapes, kind, ref_rect=None):
    """kind: left | right | top | bottom | hcenter | vcenter | center. Riferimento: ref_rect o l'ingombro della selezione."""
    if len(shapes) < 1:
        return
    R = ref_rect or union_bounds(shapes)
    for s in shapes:
        b = s.bounds()
        dx = dy = 0.0
        if kind == "left":
            dx = R.left() - b.left()
        elif kind == "right":
            dx = R.right() - b.right()
        elif kind == "bottom":
            dy = R.top() - b.top()  # Y su: top() è il minimo
        elif kind == "top":
            dy = R.bottom() - b.bottom()
        elif kind in ("hcenter", "center"):
            dx = R.center().x() - b.center().x()
        if kind in ("vcenter", "center"):
            dy = R.center().y() - b.center().y()
        if dx or dy:
            s.apply(QTransform.fromTranslate(dx, dy))


def distribute(shapes, axis="h", mode="gap"):
    if len(shapes) < 3:
        return
    key = (lambda s: s.bounds().center().x()) if axis == "h" else (lambda s: s.bounds().center().y())
    ordered = sorted(shapes, key=key)
    if mode == "center":
        a, b = key(ordered[0]), key(ordered[-1])
        step = (b - a) / (len(ordered) - 1)
        for i, s in enumerate(ordered[1:-1], start=1):
            d = a + step * i - key(s)
            s.apply(QTransform.fromTranslate(d, 0) if axis == "h" else QTransform.fromTranslate(0, d))
        return
    size = (lambda r: r.width()) if axis == "h" else (lambda r: r.height())
    lo = (lambda r: r.left()) if axis == "h" else (lambda r: r.top())
    hi = (lambda r: r.right()) if axis == "h" else (lambda r: r.bottom())
    total = hi(ordered[-1].bounds()) - lo(ordered[0].bounds())
    occupied = sum(size(s.bounds()) for s in ordered)
    gap = (total - occupied) / (len(ordered) - 1)
    pos = hi(ordered[0].bounds()) + gap
    for s in ordered[1:-1]:
        d = pos - lo(s.bounds())
        s.apply(QTransform.fromTranslate(d, 0) if axis == "h" else QTransform.fromTranslate(0, d))
        pos += size(s.bounds()) + gap


def same_size(shapes, ref, which="w"):
    rb = ref.bounds()
    for s in shapes:
        if s is ref:
            continue
        b = s.bounds()
        if which == "w" and b.width() > 1e-9:
            k = rb.width() / b.width()
            s.apply(about(QTransform.fromScale(k, 1), b.center().x(), b.center().y()))
        elif which == "h" and b.height() > 1e-9:
            k = rb.height() / b.height()
            s.apply(about(QTransform.fromScale(1, k), b.center().x(), b.center().y()))


def move_to_anchor(shapes, anchor, target_rect):
    """Porta il punto di ancoraggio (0..8) della selezione sul punto omologo di target_rect (es. il piano)."""
    b = union_bounds(shapes)
    a = geom.rect_anchor(b, anchor)
    t = geom.rect_anchor(target_rect, anchor)
    transform_all(shapes, QTransform.fromTranslate(t.x() - a.x(), t.y() - a.y()))


def flip(shapes, horizontal=True):
    b = union_bounds(shapes)
    tf = QTransform.fromScale(-1, 1) if horizontal else QTransform.fromScale(1, -1)
    transform_all(shapes, about(tf, b.center().x(), b.center().y()))


def rotate(shapes, degrees, center=None):
    b = union_bounds(shapes)
    c = center or b.center()
    tf = QTransform()
    tf.rotate(degrees)
    transform_all(shapes, about(tf, c.x(), c.y()))


# ------------------------------------------------------------------ serie
def variable_texts(shape):
    """Testi variabili dentro una forma (anche nei gruppi)."""
    from .document import GroupShape, TextShape

    if isinstance(shape, TextShape):
        if shape.variable:
            yield shape
    elif isinstance(shape, GroupShape):
        for c in shape.children:
            yield from variable_texts(c)


def _number(cp, k):
    for t in variable_texts(cp):
        t.var_offset += k
        t.invalidate()
    if list(variable_texts(cp)):
        cp.invalidate()


def grid_array(shapes, cols, rows, dx, dy, spacing="gap", shift_rows=0.0, mirror_alt=False, number=True):
    """Copie in griglia. spacing: gap (spazio fra i bordi) | center (passo fra i centri). Ritorna le copie (originale escluso)."""
    b = union_bounds(shapes)
    sx = dx + (b.width() if spacing == "gap" else 0.0)
    sy = dy + (b.height() if spacing == "gap" else 0.0)
    out = []
    for r in range(rows):
        for c in range(cols):
            if r == 0 and c == 0:
                continue
            t = QTransform.fromTranslate(c * sx + (shift_rows if r % 2 else 0.0), r * sy)
            for s in shapes:
                cp = s.clone()
                if mirror_alt and (r + c) % 2 == 1:
                    cp.apply(about(QTransform.fromScale(-1, 1), b.center().x(), b.center().y()))
                cp.apply(t)
                if number:
                    _number(cp, r * cols + c)  # testo variabile: ogni copia ha il suo numero
                out.append(cp)
    return out


def circular_array(shapes, count, center, start=0.0, end=360.0, rotate_copies=True):
    b = union_bounds(shapes)
    full = abs((end - start) % 360.0) < 1e-6
    step = (end - start) / (count if full else max(count - 1, 1))
    out = []
    for k in range(1, count):
        ang = step * k
        tf = QTransform()
        tf.rotate(ang)
        for s in shapes:
            cp = s.clone()
            if rotate_copies:
                cp.apply(about(tf, center[0], center[1]))
            else:
                cx, cy = b.center().x(), b.center().y()
                r = math.radians(ang)
                vx, vy = cx - center[0], cy - center[1]
                nx = center[0] + vx * math.cos(r) - vy * math.sin(r)
                ny = center[1] + vx * math.sin(r) + vy * math.cos(r)
                cp.apply(QTransform.fromTranslate(nx - cx, ny - cy))
            _number(cp, k)
            out.append(cp)
    return out


def copy_along_path(shapes, path_shape, count, rotate_copies=True):
    """Distribuisce copie lungo un tracciato (in modo uniforme sulla lunghezza)."""
    polys = geom.flatten(path_shape.path(), 0.02)
    if not polys:
        return []
    pts = polys[0].pts + ([polys[0].pts[0]] if polys[0].closed else [])
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(seg)
    if total <= 0 or count < 1:
        return []
    b = union_bounds(shapes)
    cx, cy = b.center().x(), b.center().y()
    n = count if polys[0].closed else max(count - 1, 1)
    out = []
    for k in range(count):
        d = total * k / n
        acc = 0.0
        for i, L in enumerate(seg):
            if acc + L >= d or i == len(seg) - 1:
                t = (d - acc) / L if L else 0
                x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t
                y = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t
                ang = math.degrees(math.atan2(pts[i + 1][1] - pts[i][1], pts[i + 1][0] - pts[i][0]))
                break
            acc += L
        tf = QTransform.fromTranslate(-cx, -cy)
        if rotate_copies:
            r = QTransform()
            r.rotate(ang)
            tf = tf * r
        tf = tf * QTransform.fromTranslate(x, y)
        for s in shapes:
            cp = s.clone()
            cp.apply(tf)
            out.append(cp)
    return out


# ------------------------------------------------------------------ pulizia
def _signature(s):
    b = s.bounds()
    return (s.kind, s.layer, round(b.left(), 3), round(b.top(), 3), round(b.width(), 3), round(b.height(), 3),
            s.path().elementCount())


def find_duplicates(shapes):
    seen = {}
    dup = []
    for s in shapes:
        sig = _signature(s)
        if sig in seen:
            # confronto fine: stessi punti appiattiti
            a = geom.flatten(seen[sig].path(), 0.05)
            c = geom.flatten(s.path(), 0.05)
            if len(a) == len(c) and all(len(p.pts) == len(q.pts) and all(math.dist(u, v) < 1e-3 for u, v in zip(p.pts, q.pts))
                                        for p, q in zip(a, c)):
                dup.append(s)
                continue
        seen[sig] = s
    return dup


def contained_in(container, shapes):
    polys = [p for p in geom.flatten(container.path(), 0.05) if p.closed]
    out = []
    for s in shapes:
        if s is container:
            continue
        sp = geom.flatten(s.path(), 0.05)
        if sp and all(any(geom.contains(o, p) for o in polys) for p in sp):
            out.append(s)
    return out


def info(shapes):
    """Misure per la barra di stato: perimetro, area (forme chiuse), nodi, aperte/chiuse."""
    per = area = 0.0
    n_open = n_closed = n_nodes = 0
    for s in shapes:
        for leaf, tf in s.leaves():
            if isinstance(leaf, ImageShape):
                continue
            path = tf.map(leaf.local_path())
            for p in geom.flatten(path, 0.02):
                per += p.length()
                if p.closed:
                    n_closed += 1
                    area += abs(p.area())
                else:
                    n_open += 1
            n_nodes += sum(len(sp.nodes) for sp in nodes.from_path(path))
    return {"perimeter": per, "area": area, "open": n_open, "closed": n_closed, "nodes": n_nodes}
