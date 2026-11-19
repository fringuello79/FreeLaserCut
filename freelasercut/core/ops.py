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
    # 0.20.2: anche le linee piatte e i punti (QRectF.united buttava via i riquadri senza area)
    return geom.rect_union(s.bounds() for s in shapes)


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
    from .document import CodeShape, GroupShape, TextShape

    if isinstance(shape, (TextShape, CodeShape)):
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


def info_slow(shapes):
    """Le misure di info() calcolate come fino alla 0.20.4 (tracciati appiattiti punto per punto): restano per le
    prove, che le confrontano con quelle veloci."""
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


# Gauss-Legendre a 8 punti su quattro tratti di [0, 1]: lunghezza delle curve, precisa ben oltre il centesimo di mm anche
# con anse strette (l'area invece si calcola esatta, con la formula della cubica)
_GL_T, _GL_W = None, None


def _gauss():
    global _GL_T, _GL_W
    if _GL_T is None:
        import numpy as np

        t, w = np.polynomial.legendre.leggauss(8)
        k = 4
        _GL_T = np.concatenate([(j + (t + 1.0) / 2.0) / k for j in range(k)])
        _GL_W = np.tile(w / 2.0 / k, k)
    return _GL_T, _GL_W


def info(shapes):
    """Misure per la barra di stato e per il pannello: perimetro, area (forme chiuse), nodi, aperte/chiuse.
    0.20.5: tutti i tracciati insieme, con numpy (rapporto FLC-20261116-0746-D046: selezionare gli addobbi di un
    progetto con centinaia di tracciati fermava la finestra quasi un secondo su un PC lento, perché le curve si
    appiattivano punto per punto in Python). Stessi conti di prima: un sottopercorso è chiuso se finisce dove
    inizia; i nodi sono quelli dello strumento Nodi (il punto finale che coincide con l'inizio non si conta due volte);
    la lunghezza delle curve è quella vera invece che quella della spezzata a 0,02 mm (differenza di solito sotto lo
    0,01%, al massimo qualche decimillesimo con curve piene di cuspidi). Due casi dove prima i conti sbagliavano:
    un tratto che va e torna sugli stessi due punti (prima contato una volta sola) e una sola curva che si chiude su
    sé stessa (prima lunghezza 0)."""
    import numpy as np

    from .document import path_arrays

    ts, xs, ys = [], [], []
    for s in shapes:
        for leaf, tf in s.leaves():
            if isinstance(leaf, ImageShape):
                continue
            t, x, y = path_arrays(tf.map(leaf.local_path()))
            if len(t):
                if t[0] != 0:  # Qt comincia sempre con un inizio; per sicurezza un tracciato non continua il precedente
                    t, x, y = np.r_[np.int8(0), t], np.r_[x[0], x], np.r_[y[0], y]
                ts.append(t), xs.append(x), ys.append(y)
    out = {"perimeter": 0.0, "area": 0.0, "open": 0, "closed": 0, "nodes": 0}
    if not ts:
        return out
    t, x, y = np.concatenate(ts), np.concatenate(xs), np.concatenate(ys)
    n = len(t)
    sub = np.cumsum(t == 0) - 1  # a quale sottopercorso appartiene ogni elemento
    nsub = int(sub[-1]) + 1
    starts = np.flatnonzero(t == 0)
    # fine di ogni sottopercorso: l'ultimo elemento prima dell'inizio seguente
    ends = np.r_[starts[1:] - 1, n - 1]
    # ---- segmenti
    li = np.flatnonzero(t == 1)
    lx0, ly0 = x[li - 1], y[li - 1]
    llen = np.hypot(x[li] - lx0, y[li] - ly0)
    larea = (lx0 * y[li] - x[li] * ly0) / 2.0
    # ---- curve (elemento 2 = primo punto di controllo, poi due elementi 3: secondo controllo e punto finale)
    ci = np.flatnonzero(t == 2)
    ci = ci[ci + 2 < n]
    gt, gw = _gauss()
    if len(ci):
        x0, y0, x1, y1 = x[ci - 1], y[ci - 1], x[ci], y[ci]
        x2, y2, x3, y3 = x[ci + 1], y[ci + 1], x[ci + 2], y[ci + 2]
        u = gt[None, :]
        ax, bx, cx = 3 * (x1 - x0)[:, None], 3 * (x2 - x1)[:, None], 3 * (x3 - x2)[:, None]
        ay, by, cy = 3 * (y1 - y0)[:, None], 3 * (y2 - y1)[:, None], 3 * (y3 - y2)[:, None]
        v, uu, w2 = (1 - u) ** 2, 2 * (1 - u) * u, u ** 2
        clen = (np.hypot(ax * v + bx * uu + cx * w2, ay * v + by * uu + cy * w2) * gw).sum(1)  # |derivata|
        # area sotto la curva (∫ x dy − y dx / 2), esatta
        carea = (x0 * (6 * y1 + 3 * y2 + y3) + x1 * (-6 * y0 + 3 * y2 + 3 * y3) + x2 * (-3 * y0 - 3 * y1 + 6 * y3)
                 + x3 * (-y0 - 3 * y1 - 6 * y2)) / 20.0
    else:
        clen = carea = np.zeros(0)
    seg_sub = np.r_[sub[li], sub[ci]].astype(np.int64)
    seg_len = np.r_[llen, clen]
    seg_area = np.r_[larea, carea]
    seg_curve = np.r_[np.zeros(len(li), bool), np.ones(len(ci), bool)]
    nonzero = seg_len > 1e-6
    length = np.bincount(seg_sub, seg_len, nsub)
    sarea = np.bincount(seg_sub, seg_area, nsub)
    n_nz = np.bincount(seg_sub, nonzero, nsub)
    n_nz_curve = np.bincount(seg_sub, nonzero & seg_curve, nsub)
    nseg = np.bincount(seg_sub, None, nsub)
    fx, fy, ex, ey = x[starts], y[starts], x[ends], y[ends]
    same_end = np.hypot(ex - fx, ey - fy) < 1e-4
    keep = n_nz > 0  # come flatten: un sottopercorso senza almeno due punti distinti non c'è
    closed = keep & same_end & ((n_nz >= 2) | (n_nz_curve >= 1))
    # area del poligono chiuso: lato di chiusura dalla fine all'inizio (quasi nullo, la fine coincide con l'inizio)
    sarea = sarea + (ex * fy - fx * ey) / 2.0
    out["perimeter"] = float(length[keep].sum())
    out["area"] = float(np.abs(sarea[closed]).sum())
    out["closed"] = int(closed.sum())
    out["open"] = int((keep & ~closed).sum())
    nn = 1 + nseg  # nodi come lo strumento Nodi: l'inizio più un nodo per segmento o curva
    nn = np.where((nn > 2) & same_end, nn - 1, nn)
    out["nodes"] = int(nn.sum())
    return out


# ------------------------------------------------------------------ distanza esatta (0.17.16)
# Ingombro = Shape.bounds() come in «Allinea». Asse "x" o "y"; bordi "min" | "center" | "max" (in Y min = in basso).
def _span(r, axis):
    return (r.left(), r.right()) if axis == "x" else (r.top(), r.bottom())


def _edge(r, axis, e):
    lo, hi = _span(r, axis)
    return lo if e == "min" else hi if e == "max" else (lo + hi) / 2.0


def gap_side(fixed, moving, axis):
    """+1 se l'oggetto che si sposta sta dopo quello fermo lungo l'asse (centri; pari = +1), altrimenti −1."""
    return 1 if _edge(moving, axis, "center") >= _edge(fixed, axis, "center") - 1e-9 else -1


def _edges(mode, side, ef, em):
    """(bordo del fermo, bordo di chi si sposta) per il modo: gap = bordi affacciati, center = centri, edges = scelti."""
    if mode == "gap":
        return ("max", "min") if side > 0 else ("min", "max")
    if mode == "center":
        return "center", "center"
    return ef, em


def measure_distance(fixed, moving, axis, mode, side, ef="min", em="min"):
    """Distanza attuale (mm) con la stessa definizione usata per spostare: (bordo di M − bordo di F) · lato."""
    a, b = _edges(mode, side, ef, em)
    return (_edge(moving, axis, b) - _edge(fixed, axis, a)) * side


def distance_shift(fixed, moving, axis, mode, side, d, ef="min", em="min"):
    """Spostamento (dx, dy) che porta l'ingombro `moving` alla distanza d da `fixed`, solo lungo l'asse."""
    a, b = _edges(mode, side, ef, em)
    delta = _edge(fixed, axis, a) + side * float(d) - _edge(moving, axis, b)
    return (delta, 0.0) if axis == "x" else (0.0, delta)


# ------------------------------------------------------------------ 0.20.3: foto ritagliata con una forma
CLIP_ROLE = "clip"  # gruppo «foto ritagliata»: la foto e la sua sagoma
CLIP_OUTLINE = "clip:"  # sagoma dentro il gruppo: «clip:<livello di prima>» (Togli il ritaglio lo rimette)
CUT_OUTLINE = "cut-outline"  # 0.20.6: «Contorno da tagliare» dentro il gruppo (resta sul suo livello)


def clip_selection(shapes):
    """Foto e forme per «Ritaglia la foto con la forma». -> (foto, trasformazione completa della foto,
    [(forma, trasformazione completa)], problema ("" se va bene))."""
    from freelasercut.i18n import tr

    leaves = [(leaf, tf) for s in shapes for leaf, tf in s.leaves() if not leaf.hidden]
    imgs = [(leaf, tf) for leaf, tf in leaves if isinstance(leaf, ImageShape)]
    others = [(leaf, tf) for leaf, tf in leaves if not isinstance(leaf, ImageShape)]
    if len(shapes) == 1 and is_clip_group(shapes[0]):
        # 0.20.6: ritagliando di nuovo un gruppo già ritagliato conta solo la sagoma, non il «Contorno da tagliare»
        # (che può essere più largo, con lo scostamento) né altro aggiunto al gruppo
        outl = [(leaf, tf) for leaf, tf in others if outline_layer(leaf) is not None]
        others = outl or others
    if len(imgs) != 1 or not others:
        return None, None, [], tr("Ritaglia la foto con la forma: seleziona una foto sola e la forma chiusa che le sta "
                                  "sopra (cuore, stella, testo…)")
    if any(not leaf.closed() for leaf, _ in others):
        return None, None, [], tr("Ritaglia la foto con la forma: la forma deve essere chiusa (Modifica → Chiudi "
                                  "tracciati)")
    return imgs[0][0], imgs[0][1], others, ""


def is_clip_group(s):
    return isinstance(s, GroupShape) and s.role == CLIP_ROLE


def clipped_photos(shapes):
    """Foto ritagliate fra le forme (anche dentro i gruppi)."""
    return [leaf for s in shapes for leaf, _ in s.leaves() if isinstance(leaf, ImageShape) and leaf.clip]


def cut_outline_path(img, tf, distance=0.0):
    """0.20.6: «Contorno da tagliare» di una foto ritagliata: il contorno della parte che si vede (sagoma ∩ foto) sul
    piano, allargato (distance > 0) o ristretto (< 0) di `distance` mm con angoli tondi. -> QPainterPath (vuoto se
    non resta niente)."""
    from . import photo_clip

    polys = []
    for ring in photo_clip.visible_rings(img.clip, img.w, img.h):
        pts = [(q.x(), q.y()) for q in (tf.map(QPointF(x, y)) for x, y in ring)]
        polys.append(geom.Poly(pts, True))
    if not polys:
        return QPainterPath()
    if abs(distance) > 1e-9:
        from .gcode import _orient

        polys = geom.offset(_orient(polys), distance, "round") or []
    return geom.polys_to_path(polys)


def outline_layer(leaf):
    """Livello che la sagoma aveva prima del ritaglio (o None)."""
    r = leaf.role or ""
    if not r.startswith(CLIP_OUTLINE):
        return None
    try:  # 0.20.9: «clip:<livello>:form» = sagoma messa da Prepara foto con una forma (la si cambia con la forma)
        return int(r[len(CLIP_OUTLINE):].split(":")[0])
    except ValueError:
        return None


FORM_OUTLINE = ":form"


def is_form_outline(leaf):
    """0.20.9: la sagoma l'ha messa Prepara foto (la forma scelta lì), non la persona."""
    return (leaf.role or "").startswith(CLIP_OUTLINE) and (leaf.role or "").endswith(FORM_OUTLINE)
