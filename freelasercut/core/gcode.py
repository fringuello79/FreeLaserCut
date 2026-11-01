# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Generatore di G-code per GRBL in modalità laser.

Da documento + profilo macchina a righe G-code, con:
  - modalità di livello: linea, riempimento (scansione), riempimento offset, immagine;
  - ottimizzazione percorsi: fori interni prima dei contorni, vicino-più-vicino,
    punto di partenza migliore sulle forme chiuse, verso migliore sulle linee aperte;
  - overscan che non esce MAI dall'area di lavoro (niente allarmi da finecorsa);
  - partenza: coordinate assolute / posizione attuale / origine utente, con ancoraggio a 9 punti;
  - aria per livello (M8/M9), passate, ponticelli (tab), compensazione del kerf.
"""
import math
import time
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform

from . import geom, imaging
from .document import Document, ImageShape
from freelasercut.i18n import tr  # noqa: E402

ANCHOR_NAMES = ["basso-sinistra", "basso-centro", "basso-destra", "centro-sinistra", "centro",
                "centro-destra", "alto-sinistra", "alto-centro", "alto-destra"]


@dataclass
class JobOptions:
    start_from: str = "absolute"  # absolute | current | origin
    anchor: int = 0  # 0..8 per current / origin
    current_pos: tuple = (0.0, 0.0)  # posizione della testa, coordinate piano (per "current")
    work_origin: tuple = (0.0, 0.0)  # origine utente, coordinate piano (per "origin")
    laser_cmd: str = "M4"
    finish: str = "origin"  # origin | stay
    optimize: bool = True
    inner_first: bool = True
    only_ids: object = None  # set di id: solo la selezione
    raster_gap_g1: float = 8.0  # mm: buchi più corti in riempimento/immagine si percorrono con G1 S0
    gray_levels: int = 64
    set_g55: bool = True  # azzera G55 (sistema "assoluto" di FreeLaserCut) se non già fatto
    name: str = ""
    rotary: object = None  # dict: kind (roller | chuck), mm_per_rev, roller_d, object_d — None = piano normale


@dataclass
class LayerStats:
    index: int
    name: str
    mode: str
    items: int = 0
    cut_mm: float = 0.0
    lines: int = 0


@dataclass
class GcodeJob:
    lines: list = field(default_factory=list)
    bounds: object = None  # QRectF in coordinate piano (dove brucerà davvero, overscan incluso)
    out_to_bed: tuple = (0.0, 0.0)  # piano = uscita + offset (per l'anteprima)
    motion_bounds: object = None  # dove passa la testa (trasferimenti e overscan inclusi)
    warnings: list = field(default_factory=list)
    layers: list = field(default_factory=list)
    seconds: float = 0.0
    gen_ms: float = 0.0
    rotary_k: float = 1.0  # rotativo: Y macchina = riferimento + (Y piano - riferimento) × k
    rotary_ref: tuple = (0.0, 0.0)  # punto di riferimento sul piano (ancoraggio del disegno)


def rotary_scale(r):
    """Fattore dell'asse Y per il rotativo. A rulli conta il diametro del rullo (l'oggetto ruota alla stessa
    velocità di superficie); a mandrino conta il diametro dell'oggetto."""
    if not r:
        return 1.0
    d = float(r.get("roller_d", 0) if r.get("kind", "roller") == "roller" else r.get("object_d", 0))
    mm = float(r.get("mm_per_rev", 0))
    if d <= 0 or mm <= 0:
        return 1.0
    return mm / (math.pi * d)


def _fmt(v):
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class _Writer:
    """Scrive G-code compatto (omette coordinate, F e S che non cambiano) e misura
    sia dove il laser brucia sia dove la testa passa (overscan e trasferimenti inclusi)."""

    def __init__(self, out_map, s_max):
        self.lines = []
        self.map = out_map
        self.s_max = s_max
        self.x = self.y = None  # ultima posizione in coordinate di USCITA
        self.pb = None  # ultima posizione in coordinate PIANO
        self.f = None
        self.s = None
        self.mode = None
        self.rot_k = 1.0  # rotativo: la F si corregge perché la velocità sulla superficie resti quella scelta
        self.cut = 0.0
        self.burn = [math.inf, math.inf, -math.inf, -math.inf]
        self.motion = [math.inf, math.inf, -math.inf, -math.inf]

    @staticmethod
    def _grow(box, x, y):
        box[0] = min(box[0], x)
        box[1] = min(box[1], y)
        box[2] = max(box[2], x)
        box[3] = max(box[3], y)

    def raw(self, text):
        self.lines.append(text)

    def _xy(self, ox, oy):
        parts = []
        if self.x is None or abs(ox - self.x) >= 1e-4:
            parts.append("X" + _fmt(ox))
        if self.y is None or abs(oy - self.y) >= 1e-4:
            parts.append("Y" + _fmt(oy))
        return parts

    def rapid(self, bx, by):
        ox, oy = self.map(bx, by)
        xy = self._xy(ox, oy)
        if not xy:
            return
        self.lines.append("G0 " + " ".join(xy))
        self.mode = 0
        self.x, self.y = ox, oy
        self._grow(self.motion, bx, by)
        self.pb = (bx, by)

    def feed(self, bx, by, power_pct, speed):
        ox, oy = self.map(bx, by)
        xy = self._xy(ox, oy)
        if not xy:
            return
        s = round(max(0.0, power_pct) / 100.0 * self.s_max, 1)
        parts = ([] if self.mode == 1 else ["G1"]) + xy
        if s != self.s:
            parts.append("S" + _fmt(s))
            self.s = s
        if self.rot_k != 1.0 and self.pb is not None and self.x is not None:
            ld = math.dist(self.pb, (bx, by))
            if ld > 1e-9:
                speed = round(speed * math.dist((self.x, self.y), (ox, oy)) / ld)
        if speed != self.f:
            parts.append("F" + _fmt(speed))
            self.f = speed
        self.lines.append(" ".join(parts))
        if s > 0 and self.pb is not None:
            self.cut += math.dist(self.pb, (bx, by))
            self._grow(self.burn, *self.pb)
            self._grow(self.burn, bx, by)
        self._grow(self.motion, bx, by)
        self.mode = 1
        self.x, self.y = ox, oy
        self.pb = (bx, by)

    def track(self, bx, by):  # compatibilità: la posizione è già tracciata da rapid/feed
        pass


# ======================================================================= raccolta
def _collect(doc, opts):
    """{indice_livello: [(leaf, tf)]} solo forme visibili (e selezionate, se richiesto)."""
    out = {}
    for s in doc.shapes:
        if s.hidden:
            continue
        if opts.only_ids is not None and s.id not in opts.only_ids:
            continue
        for leaf, tf in s.leaves():
            if leaf.hidden:
                continue
            out.setdefault(leaf.layer, []).append((leaf, tf))
    return out


def _polys_of(items, tol=geom.FLATTEN_TOL):
    polys = []
    for leaf, tf in items:
        if isinstance(leaf, ImageShape):
            continue
        polys.extend(geom.flatten(tf.map(leaf.local_path()), tol))
    return polys


def _depths(polys):
    """Profondità di annidamento di ogni contorno chiuso (0 = esterno)."""
    n = len(polys)
    depth = [0] * n
    if n > 3000:
        return depth
    boxes = [p.bounds() if p.closed else None for p in polys]
    for i, inner in enumerate(polys):
        bi = inner.bounds()
        for j, outer in enumerate(polys):
            if i == j or not outer.closed:
                continue
            bo = boxes[j]
            if bi[0] < bo[0] or bi[1] < bo[1] or bi[2] > bo[2] or bi[3] > bo[3]:
                continue
            if abs(outer.area()) <= abs(inner.area()) and inner.closed:
                continue
            if geom.contains(outer, inner):
                depth[i] += 1
    return depth


def _orient(polys):
    """Esterni antiorari, fori orari: serve a Clipper per kerf e offset corretti."""
    d = _depths(polys)
    out = []
    for p, k in zip(polys, d):
        if not p.closed:
            out.append(p)
            continue
        ccw = p.area() > 0
        want_ccw = k % 2 == 0
        out.append(p if ccw == want_ccw else p.reversed())
    return out


# ======================================================================= ottimizzazione
def order_polys(polys, start=(0.0, 0.0), inner_first=True, optimize=True):
    """Ordina le polilinee riducendo i trasferimenti; i fori prima dei contorni che li contengono."""
    n = len(polys)
    if n == 0 or not optimize:
        return polys
    children = [[] for _ in range(n)]
    if inner_first and n <= 3000:
        for i, inner in enumerate(polys):
            for j, outer in enumerate(polys):
                if i != j and outer.closed and abs(outer.area()) > abs(inner.area()) and geom.contains(outer, inner):
                    children[j].append(i)
    remaining_children = [len(c) for c in children]
    parents = [[] for _ in range(n)]
    for j, cs in enumerate(children):
        for i in cs:
            parents[i].append(j)
    done = np.zeros(n, bool)
    # punto rappresentativo per la ricerca veloce: inizio o centro
    reps = np.array([[p.pts[0][0], p.pts[0][1]] if not p.closed else
                     [sum(q[0] for q in p.pts) / len(p.pts), sum(q[1] for q in p.pts) / len(p.pts)] for p in polys])
    ends = np.array([[p.pts[-1][0], p.pts[-1][1]] for p in polys])
    cur = np.array(start, float)
    out = []
    for _ in range(n):
        avail = (~done) & (np.array(remaining_children) == 0)
        if not avail.any():
            avail = ~done
        idx = np.nonzero(avail)[0]
        d1 = np.hypot(reps[idx, 0] - cur[0], reps[idx, 1] - cur[1])
        d2 = np.hypot(ends[idx, 0] - cur[0], ends[idx, 1] - cur[1])
        dmin = np.minimum(d1, d2)
        k = int(idx[int(np.argmin(dmin))])
        p = polys[k]
        if p.closed:
            pts = np.array(p.pts)
            vi = int(np.argmin(np.hypot(pts[:, 0] - cur[0], pts[:, 1] - cur[1])))
            p = geom.Poly(p.pts[vi:] + p.pts[:vi], True)
            last = p.pts[0]
        else:
            if math.dist(p.pts[-1], tuple(cur)) < math.dist(p.pts[0], tuple(cur)):
                p = p.reversed()
            last = p.pts[-1]
        out.append(p)
        done[k] = True
        for par in parents[k]:
            remaining_children[par] -= 1
        cur = np.array(last, float)
    return out


# ======================================================================= modalità
def _apply_tabs(polys, size, count):
    out = []
    for p in polys:
        if not p.closed or count <= 0 or size <= 0:
            out.append(p)
            continue
        pts = p.pts + [p.pts[0]]
        seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        total = sum(seg)
        if total < count * size * 3:
            out.append(p)
            continue
        gaps = [(total * (k + 0.5) / count - size / 2, total * (k + 0.5) / count + size / 2) for k in range(count)]

        def at(dist):
            acc = 0.0
            for i, L in enumerate(seg):
                if acc + L >= dist:
                    t = (dist - acc) / L if L else 0
                    return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t), i
                acc += L
            return pts[-1], len(seg) - 1

        bounds = [0.0] + [g for gap in gaps for g in gap] + [total]
        for a, b in zip(bounds[0::2], bounds[1::2]):
            if b - a < 1e-3:
                continue
            pa, ia = at(a)
            pb, ib = at(b)
            part = [pa] + pts[ia + 1:ib + 1] + [pb]
            out.append(geom.Poly(part, False))
    return out


def _scanlines(polys, interval, angle):
    """Riempimento a scansione (pari-dispari). Ritorna [(y, [(xa, xb), ...])] nel sistema ruotato."""
    closed = [p for p in polys if p.closed and len(p.pts) >= 3]
    if not closed:
        return [], None
    a = math.radians(angle)
    ca, sa = math.cos(-a), math.sin(-a)
    edges = []
    for p in closed:
        pts = np.array(p.pts)
        rx = pts[:, 0] * ca - pts[:, 1] * sa
        ry = pts[:, 0] * sa + pts[:, 1] * ca
        x1, y1 = rx, ry
        x2, y2 = np.roll(rx, -1), np.roll(ry, -1)
        keep = np.abs(y2 - y1) > 1e-12
        edges.append(np.stack([x1[keep], y1[keep], x2[keep], y2[keep]], axis=1))
    E = np.concatenate(edges) if edges else np.zeros((0, 4))
    if not len(E):
        return [], None
    ymin_e = np.minimum(E[:, 1], E[:, 3])
    ymax_e = np.maximum(E[:, 1], E[:, 3])
    # righe a metà passo su una griglia globale: mai esattamente su un bordo, forme diverse allineate fra loro
    y0 = (math.ceil(ymin_e.min() / interval - 0.5) + 0.5) * interval
    y1 = ymax_e.max()
    order = np.argsort(ymin_e)
    E, ymin_e, ymax_e = E[order], ymin_e[order], ymax_e[order]
    lines = []
    y = y0
    while y < y1:
        hi = np.searchsorted(ymin_e, y, side="right")
        cand = slice(0, hi)
        m = ymax_e[cand] > y
        if m.any():
            e = E[cand][m]
            t = (y - e[:, 1]) / (e[:, 3] - e[:, 1])
            xs = np.sort(e[:, 0] + t * (e[:, 2] - e[:, 0]))
            segs = [(float(xs[i]), float(xs[i + 1])) for i in range(0, len(xs) - 1, 2) if xs[i + 1] - xs[i] > 1e-4]
            if segs:
                lines.append((y, segs))
        y += interval
    return lines, (math.cos(a), math.sin(a))


def _clamp_dir(px, py, dx, dy, dist, bed):
    """Allunga (px,py) di dist lungo (dx,dy) senza uscire dal piano."""
    if dist <= 0:
        return px, py
    tmax = dist
    bx, by = bed
    for p, d, lo, hi in ((px, dx, 0.0, bx), (py, dy, 0.0, by)):
        if d > 1e-12:
            tmax = min(tmax, (hi - p) / d)
        elif d < -1e-12:
            tmax = min(tmax, (lo - p) / d)
    tmax = max(0.0, tmax)
    return px + dx * tmax, py + dy * tmax


def _emit_scan(w, lines, rot, cs, bed, gap_g1, power_of=None):
    """Emette righe di scansione: [(y, [(xa, xb, potenza%), ...])] nel sistema ruotato di 'rot'."""
    cos_a, sin_a = rot

    def back(x, y):
        return x * cos_a - y * sin_a, x * sin_a + y * cos_a

    dxu, dyu = cos_a, sin_a  # direzione di scansione nel piano
    forward = True
    for y, segs in lines:
        if not segs:
            continue
        if not forward:
            segs = [(b, a, p) for a, b, p in reversed(segs)]
        sgn = 1.0 if forward else -1.0
        ddx, ddy = dxu * sgn, dyu * sgn
        sx, sy = back(segs[0][0], y)
        ox, oy = _clamp_dir(sx, sy, -ddx, -ddy, cs.overscan, bed)
        w.rapid(ox, oy)
        w.track(ox, oy)
        w.feed(sx, sy, 0.0, cs.speed)
        w.track(sx, sy)
        for k, (xa, xb, pw) in enumerate(segs):
            ax, ay = back(xa, y)
            bxx, byy = back(xb, y)
            if k > 0:
                gap = abs(xa - segs[k - 1][1])
                if gap <= gap_g1:
                    w.feed(ax, ay, 0.0, cs.speed)
                else:
                    ex, ey = _clamp_dir(*back(segs[k - 1][1], y), ddx, ddy, cs.overscan, bed)
                    w.feed(ex, ey, 0.0, cs.speed)
                    ox, oy = _clamp_dir(ax, ay, -ddx, -ddy, cs.overscan, bed)
                    w.rapid(ox, oy)
                    w.feed(ax, ay, 0.0, cs.speed)
                w.track(ax, ay)
            w.feed(bxx, byy, pw, cs.speed)
            w.track(bxx, byy)
        ex, ey = _clamp_dir(*back(segs[-1][1], y), ddx, ddy, cs.overscan, bed)
        w.feed(ex, ey, 0.0, cs.speed)
        w.track(ex, ey)
        if cs.bidirectional:
            forward = not forward


def _emit_polys(w, polys, cs):
    for p in polys:
        w.rapid(*p.pts[0])
        w.track(*p.pts[0])
        for q in p.pts[1:]:
            w.feed(q[0], q[1], cs.power_max, cs.speed)
            w.track(*q)
        if p.closed:
            w.feed(p.pts[0][0], p.pts[0][1], cs.power_max, cs.speed)
            w.track(*p.pts[0])


def _fill_clusters(polys, grouping):
    if grouping != "each":
        return [polys]
    closed = [p for p in polys if p.closed]
    d = _depths(closed)
    outers = [i for i, k in enumerate(d) if k % 2 == 0]
    clusters = {i: [closed[i]] for i in outers}
    for i, k in enumerate(d):
        if k % 2 == 1:
            # foro: va con l'esterno più piccolo che lo contiene
            best, best_a = None, math.inf
            for j in outers:
                if geom.contains(closed[j], closed[i]) and abs(closed[j].area()) < best_a:
                    best, best_a = j, abs(closed[j].area())
            if best is not None:
                clusters[best].append(closed[i])
    return list(clusters.values())


def _emit_fill(w, polys, cs, bed, opts, grouping):
    angles = [cs.angle] + ([cs.angle + 90.0] if cs.crosshatch else [])
    for ang in angles:
        clusters = _fill_clusters(polys, grouping)
        if grouping == "each" and len(clusters) > 1:
            # ordine dei gruppi: vicino-più-vicino a partire dalla posizione attuale
            start = w.pb or (0.0, 0.0)
            reps = [geom.Poly([((min(p.bounds()[0] for p in c) + max(p.bounds()[2] for p in c)) / 2,
                                (min(p.bounds()[1] for p in c) + max(p.bounds()[3] for p in c)) / 2)], False) for c in clusters]
            order = order_polys(reps, start, False, True)
            idx = [next(i for i, r in enumerate(reps) if r.pts[0] == o.pts[0]) for o in order]
            clusters = [clusters[i] for i in idx]
        for cluster in clusters:
            lines, rot = _scanlines(cluster, cs.interval, ang)
            lines = [(y, [(a, b, cs.power_max) for a, b in segs]) for y, segs in lines]
            if lines:
                _emit_scan(w, lines, rot, cs, bed, opts.raster_gap_g1)


def _best_grouping(w, polys, cs, bed, opts, profile):
    """Riempimento 'Automatico': prova entrambe le strategie e sceglie la più rapida (stima con le accelerazioni)."""
    closed = [p for p in polys if p.closed]
    if len(closed) < 2:
        return "together"
    from .. import gcode_preview

    best, best_t = "together", math.inf
    for g in ("together", "each"):
        tmp = _Writer(w.map, w.s_max)
        tmp.x, tmp.y, tmp.pb, tmp.f, tmp.s, tmp.mode = w.x, w.y, w.pb, w.f, w.s, w.mode
        _emit_fill(tmp, polys, cs, bed, opts, g)
        t = gcode_preview.plan_time(_moves_of(tmp.lines, w.x, w.y), profile.accel_x, profile.accel_y,
                                    profile.max_rate_x, profile.max_rate_y, profile.junction_dev)
        if t < best_t:
            best, best_t = g, t
    return best


def _moves_of(lines, x0, y0):
    """Righe G0/G1 assolute -> movimenti per la stima dei tempi."""
    x = x0 or 0.0
    y = y0 or 0.0
    feed = 1000.0
    rapid = False
    out = []
    for l in lines:
        parts = l.split()
        if not parts:
            continue
        nx, ny = x, y
        for p in parts:
            c, v = p[0], p[1:]
            if c == "G":
                rapid = v == "0"
            elif c == "X":
                nx = float(v)
            elif c == "Y":
                ny = float(v)
            elif c == "F":
                feed = float(v)
        d = math.hypot(nx - x, ny - y)
        if d > 0:
            out.append((nx - x, ny - y, d, feed, rapid))
        x, y = nx, ny
    return out


def _image_lines(leaf, tf, cs, s_levels, bed):
    """Una forma immagine -> righe di scansione [(y, [(xa, xb, potenza%), ...])], angolo 0."""
    img = leaf._doc_image if hasattr(leaf, "_doc_image") else None
    if img is None:
        return []
    dark = imaging.to_dark(img)
    step = 25.4 / max(cs.dpi, 10.0)
    r = tf.map(leaf.local_path()).boundingRect()
    x0 = math.floor(r.left() / step) * step + step / 2
    y0 = math.floor(r.top() / step) * step + step / 2
    nx = max(1, int(math.ceil((r.right() - x0) / step)) + 1)
    ny = max(1, int(math.ceil((r.bottom() - y0) / step)) + 1)
    inv, ok = tf.inverted()
    if not ok:
        return []
    grid = imaging.sample_to_grid(dark, inv, leaf.w, leaf.h, x0, y0, nx, ny, step)
    grid = imaging.adjust(grid, leaf.brightness, leaf.contrast, leaf.gamma, cs.negative)
    cell_px = max(cs.halftone_cell / step, 2.0)
    vals = imaging.dither(grid[::-1].copy(), cs.dither, cell_px, cs.halftone_angle)[::-1]  # dithering dall'alto
    pmin, pmax = cs.power_min, cs.power_max
    if cs.dither == "grayscale":
        q = np.round(vals * (s_levels - 1)) / (s_levels - 1)
        power = np.where(q > 0, pmin + (pmax - pmin) * q, 0.0)
    else:
        power = np.where(vals > 0.5, pmax, 0.0)
    lines = []
    shrink = cs.dot_correction / 2.0 if cs.dither != "grayscale" else 0.0
    for i in range(ny - 1, -1, -1):  # dall'alto verso il basso
        row = power[i]
        nz = np.nonzero(row > 0)[0]
        if not len(nz):
            continue
        y = y0 + i * step
        segs = []
        j = nz[0]
        end = nz[-1]
        while j <= end:
            v = row[j]
            k = j
            while k + 1 <= end and row[k + 1] == v:
                k += 1
            xa = x0 + (j - 0.5) * step
            xb = x0 + (k + 0.5) * step
            if v > 0:
                if shrink and xb - xa > 2 * shrink + 0.02:
                    xa += shrink
                    xb -= shrink
                segs.append((xa, xb, float(v)))
            j = k + 1
        # i tratti spenti fra quelli accesi vengono percorsi a S0 da _emit_scan
        if segs:
            lines.append((y, segs))
    return lines


# ======================================================================= lavoro
def generate(doc: Document, profile, opts: JobOptions = None) -> GcodeJob:
    t0 = time.time()
    opts = opts or JobOptions()
    job = GcodeJob()
    bed = (profile.bed_x, profile.bed_y)
    by_layer = _collect(doc, opts)
    layers = [cs for cs in doc.used_layers() if cs.output and cs.index in by_layer]
    if not layers:
        job.warnings.append(tr("Niente da incidere: nessuna forma su livelli con uscita attiva"))
        return job
    # ingombro del disegno (per l'ancoraggio)
    drawn = QRectF()
    for cs in layers:
        for leaf, tf in by_layer[cs.index]:
            r = tf.map(leaf.local_path()).boundingRect()
            drawn = r if drawn.isNull() else drawn.united(r)
    anchor = geom.rect_anchor(drawn, opts.anchor)
    # posizionamento: piano -> uscita
    if opts.start_from == "absolute":
        place = (0.0, 0.0)

        def out_map(bx, by):
            return profile.to_machine(bx, by)
        mx0, my0 = profile.to_machine(0.0, 0.0)
        job.out_to_bed = (-mx0, -my0)
    else:
        target = opts.current_pos if opts.start_from == "current" else opts.work_origin
        place = (target[0] - anchor.x(), target[1] - anchor.y())

        def out_map(bx, by):
            return bx - anchor.x(), by - anchor.y()
        job.out_to_bed = (target[0], target[1])

    # il disegno viene "spostato" sul piano di place: genero già in coordinate piano finali
    pl_tf = QTransform.fromTranslate(place[0], place[1])

    def placed_map(bx, by):
        return out_map(bx - place[0], by - place[1])

    rot_k = rotary_scale(opts.rotary)
    if rot_k != 1.0:  # rotativo: l'asse Y gira l'oggetto, si scala attorno all'ancoraggio del disegno
        ref = (anchor.x() + place[0], anchor.y() + place[1])
        _, ref_oy = placed_map(*ref)
        flat_map = placed_map

        def placed_map(bx, by):
            ox, oy = flat_map(bx, by)
            return ox, ref_oy + (oy - ref_oy) * rot_k
        job.rotary_k, job.rotary_ref = rot_k, ref
        job.warnings.append(tr("Rotativo attivo: asse Y × {0:.4f} (in anteprima il disegno resta com'è sul piano)", rot_k))
    w = _Writer(placed_map, profile.s_max)
    w.rot_k = rot_k
    title = opts.name or doc.name
    w.raw(f"; FreeLaserCut — {title}")
    w.raw(f"; macchina: {profile.name} · {profile.bed_x:g}×{profile.bed_y:g} mm · S max {profile.s_max:g}")
    w.raw(f"; partenza: {opts.start_from}" + ("" if opts.start_from == "absolute" else f" · ancoraggio {ANCHOR_NAMES[opts.anchor]}"))
    w.raw("G90 G21")
    w.raw("M5 S0")
    w.raw("M9")
    if opts.start_from == "absolute":
        if opts.set_g55:
            w.raw("G10 L2 P2 X0 Y0")
        w.raw("G55")
    elif opts.start_from == "current":
        w.raw("G92 X0 Y0")
    else:
        w.raw("G54")
    w.raw(f"{opts.laser_cmd} S0")
    current_cmd = opts.laser_cmd
    cur = opts.current_pos if opts.start_from == "current" else (0.0, 0.0)
    air_on = False
    for cs in layers:
        items = [(leaf, tf * pl_tf) for leaf, tf in by_layer[cs.index]]
        st = LayerStats(cs.index, cs.label(), cs.mode, items=len(items))
        cut_before = w.cut
        n_before = len(w.lines)
        if cs.speed > min(profile.max_rate_x, profile.max_rate_y):
            job.warnings.append(tr("{0}: velocità {1:g} oltre il massimo della macchina, verrà limitata", cs.label(), cs.speed))
        if cs.power_max <= 0:
            job.warnings.append(tr("{0}: potenza 0%, il livello non inciderà nulla", cs.label()))
        if cs.air != air_on:
            w.raw("M8" if cs.air else "M9")
            air_on = cs.air
        w.raw(f"; livello {cs.label()} · {cs.mode} · {cs.speed:g} mm/min · {cs.power_max:g}% · {cs.passes}×")
        layer_cmd = "M3" if getattr(cs, "constant_power", False) else opts.laser_cmd
        if layer_cmd != current_cmd:
            w.raw(f"{layer_cmd} S0")
            w.s = 0.0
            current_cmd = layer_cmd
        if cs.mode == "image":
            imgs = [(l, t) for l, t in items if isinstance(l, ImageShape)]
            if len(imgs) < len(items):
                job.warnings.append(tr("{0}: in modalità Immagine le forme vettoriali vengono ignorate", cs.label()))
            for leaf, tf in imgs:
                leaf._doc_image = doc.images.get(leaf.image_id)
                lines = _image_lines(leaf, tf, cs, opts.gray_levels, bed)
                for _ in range(max(1, cs.passes)):
                    _emit_scan(w, lines, (1.0, 0.0), cs, bed, opts.raster_gap_g1)
        else:
            polys = _polys_of(items)
            if cs.mode == "line":
                if cs.kerf:
                    closed = _orient([p for p in polys if p.closed])
                    polys = geom.offset(closed, cs.kerf / 2.0, "miter") + [p for p in polys if not p.closed]
                if cs.tabs:
                    polys = _apply_tabs(polys, cs.tab_size, cs.tab_count)
                for _ in range(max(1, cs.passes)):
                    ordered = order_polys(polys, cur, opts.inner_first, opts.optimize)
                    _emit_polys(w, ordered, cs)
                    if ordered:
                        last = ordered[-1]
                        cur = last.pts[0] if last.closed else last.pts[-1]
            elif cs.mode == "offset_fill":
                closed = _orient([p for p in polys if p.closed])
                rings = []
                k = 0
                layer = closed
                while layer and k < 2000:
                    rings.append(layer)
                    k += 1
                    layer = geom.offset(closed, -cs.interval * k, "round")
                flat = [p for ring in rings for p in ring]
                for _ in range(max(1, cs.passes)):
                    # anelli concentrici: il vicino-più-vicino li percorre già in sequenza
                    _emit_polys(w, order_polys(flat, cur, False, opts.optimize), cs)
            else:  # fill
                if any(not p.closed for p in polys):
                    job.warnings.append(tr("{0}: le linee aperte non si possono riempire e vengono ignorate", cs.label()))
                grouping = cs.fill_grouping
                if grouping == "auto":
                    grouping = _best_grouping(w, polys, cs, bed, opts, profile)
                for _ in range(max(1, cs.passes)):
                    _emit_fill(w, polys, cs, bed, opts, grouping)
        st.cut_mm = w.cut - cut_before
        st.lines = len(w.lines) - n_before
        job.layers.append(st)
    w.raw("M5 S0")
    if air_on:
        w.raw("M9")
    if opts.finish == "origin":
        # destinazione in coordinate PIANO: casa (assoluto) o punto di ancoraggio (attuale/origine).
        # Con coordinate macchina negative "G0 X0 Y0" porterebbe la testa all'angolo opposto.
        if opts.start_from == "absolute":
            # vicino a casa ma a 10 mm dai finecorsa: arrivare esattamente su 0,0 può far scattare l'interruttore
            # (sul B1 è successo: allarme 1 a pochi mm dall'origine)
            w.rapid(min(10.0, bed[0]), min(10.0, bed[1]))
        else:
            target = opts.current_pos if opts.start_from == "current" else opts.work_origin
            w.rapid(target[0], target[1])
    if opts.start_from == "absolute":
        w.raw("G54")
    elif opts.start_from == "current":
        w.raw("G92.1")
    w.raw("; fine")
    job.lines = w.lines
    b, m = w.burn, w.motion
    if b[0] <= b[2]:
        job.bounds = QRectF(b[0], b[1], b[2] - b[0], b[3] - b[1])
    eps = 0.01
    if m[0] <= m[2] and (m[0] < -eps or m[1] < -eps or m[2] > bed[0] + eps or m[3] > bed[1] + eps):
        job.warnings.insert(0, tr("Il lavoro esce dall'area di lavoro: spostalo o cambia origine"))
    job.motion_bounds = QRectF(m[0], m[1], m[2] - m[0], m[3] - m[1]) if m[0] <= m[2] else None
    job.gen_ms = (time.time() - t0) * 1000
    from .. import gcode_preview

    job.seconds = gcode_preview.parse(job.lines, profile=profile).seconds
    return job
