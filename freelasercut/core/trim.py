# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Forbici (0.17.16): toglie il tratto di una linea compreso fra due intersezioni, come il «Taglia» dei CAD.

Progetto, invarianti e casi provati nel documento «forbici-taglia-eccedenze». In breve:
- geometria = sottotracciati di nodi (segmenti dritti o Bézier cubiche) in mm sul piano;
- parametro su un sottotracciato: u = k + t (k = indice del segmento, t in [0, 1]);
- punti di taglio = incroci e contatti con tutte le linee visibili (anche la stessa forma); prima stima sulle curve
  appiattite, poi rifinitura di Newton sulle curve vere; parti sovrapposte = solo gli estremi della parte comune;
- il resto si ricostruisce con de Casteljau: le curve rimaste sono quelle di prima, senza approssimazioni.
"""
import math

import numpy as np

from . import nodes
from .document import GroupShape, ImageShape

FLAT_TOL = 0.004  # mm: appiattimento per trovare gli incroci (poi Newton porta all'incrocio vero)
EPS_T = 1e-9
EPS_U = 1e-7
EPS_MM = 1e-7


# ------------------------------------------------------------------ segmenti
class Seg:
    __slots__ = ("si", "k", "pts", "curve", "ts", "poly", "box")

    def __init__(self, si, k, pts, curve):
        self.si, self.k, self.pts, self.curve = si, k, pts, curve
        ts, poly = _flatten(pts, curve)
        self.ts, self.poly = ts, poly
        lo, hi = poly.min(0), poly.max(0)
        self.box = (lo[0], lo[1], hi[0], hi[1])

    def at(self, t):
        if self.curve:
            return nodes.bez_point(*self.pts, t)
        p0, p3 = self.pts[0], self.pts[3]
        return (p0[0] + (p3[0] - p0[0]) * t, p0[1] + (p3[1] - p0[1]) * t)

    def d(self, t):
        p0, p1, p2, p3 = self.pts
        if not self.curve:
            return (p3[0] - p0[0], p3[1] - p0[1])
        u = 1 - t
        return tuple(3 * (u * u * (p1[i] - p0[i]) + 2 * u * t * (p2[i] - p1[i]) + t * t * (p3[i] - p2[i])) for i in (0, 1))


def _flatten(pts, curve):
    if not curve:
        return np.array([0.0, 1.0]), np.array([pts[0], pts[3]], dtype=float)
    out_t, out_p = [0.0], [pts[0]]

    def rec(p0, p1, p2, p3, t0, t1, depth):
        # piattezza: distanza dei punti di controllo dalla corda
        dx, dy = p3[0] - p0[0], p3[1] - p0[1]
        L = math.hypot(dx, dy)
        if L > 1e-12:
            d1 = abs((p1[0] - p0[0]) * dy - (p1[1] - p0[1]) * dx) / L
            d2 = abs((p2[0] - p0[0]) * dy - (p2[1] - p0[1]) * dx) / L
        else:
            d1, d2 = math.dist(p0, p1), math.dist(p0, p2)
        if max(d1, d2) * 0.75 <= FLAT_TOL or depth >= 14:
            out_t.append(t1)
            out_p.append(p3)
            return
        a, b = _split(p0, p1, p2, p3, 0.5)
        tm = (t0 + t1) / 2
        rec(*a, t0, tm, depth + 1)
        rec(*b, tm, t1, depth + 1)

    rec(*pts, 0.0, 1.0, 0)
    return np.array(out_t), np.array(out_p, dtype=float)


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _split(p0, p1, p2, p3, t):
    p01, p12, p23 = _lerp(p0, p1, t), _lerp(p1, p2, t), _lerp(p2, p3, t)
    p012, p123 = _lerp(p01, p12, t), _lerp(p12, p23, t)
    m = _lerp(p012, p123, t)
    return (p0, p01, p012, m), (m, p123, p23, p3)


def _part(seg, t1, t2):
    """Punti di controllo del pezzo [t1, t2] del segmento (curva esatta)."""
    if not seg.curve:
        a, b = seg.at(t1), seg.at(t2)
        return a, a, b, b
    left, _ = _split(*seg.pts, t2) if t2 < 1 else (seg.pts, None)
    if t1 <= 0:
        return left
    _, right = _split(*left, t1 / t2)
    return right


def segments(subs, si=None):
    out = []
    for i, sp in enumerate(subs):
        if si is not None and i != si:
            continue
        for k, (a, b) in enumerate(sp.segments()):
            out.append(Seg(i, k, sp.bezier(a, b), sp.is_curve(a, b)))
    return out


def nseg(sp):
    return len(sp.segments())


# ------------------------------------------------------------------ intersezioni
def _overlap(b1, b2, m=1e-6):
    return b1[0] <= b2[2] + m and b2[0] <= b1[2] + m and b1[1] <= b2[3] + m and b2[1] <= b1[3] + m


def _hits(A, B):
    """Incroci fra le spezzate di A e B. -> (punti [(tA, tB)], sovrapposizioni [(tA0, tA1)]) nel parametro dei segmenti."""
    P, Q = A.poly[:-1], B.poly[:-1]
    R, S = A.poly[1:] - P, B.poly[1:] - Q
    if len(P) == 0 or len(Q) == 0:
        return [], []
    Rx, Ry = R[:, 0][:, None], R[:, 1][:, None]
    Sx, Sy = S[:, 0][None, :], S[:, 1][None, :]
    qx, qy = Q[:, 0][None, :] - P[:, 0][:, None], Q[:, 1][None, :] - P[:, 1][:, None]
    den = Rx * Sy - Ry * Sx
    lr, ls = np.hypot(Rx, Ry), np.hypot(Sx, Sy)
    with np.errstate(divide="ignore", invalid="ignore"):
        ua = (qx * Sy - qy * Sx) / den
        ub = (qx * Ry - qy * Rx) / den
    par = np.abs(den) <= 1e-12 * np.maximum(lr * ls, 1e-30)
    # contatto anche se l'estremo è a meno di 1e-6 mm dalla linea (estremi agganciati, arrotondamenti)
    ea, eb = 1e-6 / np.maximum(lr, 1e-12), 1e-6 / np.maximum(ls, 1e-12)
    ok = (~par) & (ua >= -ea) & (ua <= 1 + ea) & (ub >= -eb) & (ub <= 1 + eb) & (lr > 1e-12) & (ls > 1e-12)
    pts = []
    tA0, tA1, tB0, tB1 = A.ts[:-1], A.ts[1:], B.ts[:-1], B.ts[1:]
    for i, j in zip(*np.nonzero(ok)):
        a = tA0[i] + min(max(ua[i, j], 0.0), 1.0) * (tA1[i] - tA0[i])
        b = tB0[j] + min(max(ub[i, j], 0.0), 1.0) * (tB1[j] - tB0[j])
        pts.append((a, b))
    ovl = []
    # parallele e sulla stessa retta: parte comune
    col = par & (np.abs(qx * Ry - qy * Rx) <= EPS_MM * np.maximum(lr, 1e-30)) & (lr > 1e-12)
    for i, j in zip(*np.nonzero(col)):
        r = R[i]
        L2 = r[0] * r[0] + r[1] * r[1]
        q0 = Q[j] - P[i]
        s0 = (q0[0] * r[0] + q0[1] * r[1]) / L2
        q1 = q0 + S[j]
        s1 = (q1[0] * r[0] + q1[1] * r[1]) / L2
        lo, hi = max(0.0, min(s0, s1)), min(1.0, max(s0, s1))
        if hi < lo - 1e-12:
            continue
        a0 = tA0[i] + lo * (tA1[i] - tA0[i])
        a1 = tA0[i] + hi * (tA1[i] - tA0[i])
        if (hi - lo) * math.sqrt(L2) > EPS_MM:
            ovl.append((a0, a1))
        else:
            # un punto solo: con B fuori dalla retta per l'altro estremo
            sb = 0.0 if math.hypot(*(q0)) <= math.hypot(*(q1)) else 1.0
            pts.append((a0, tB0[j] + sb * (tB1[j] - tB0[j])))
    return pts, ovl


def _newton(A, B, ta, tb):
    """Incrocio vero vicino alla stima (ta, tb); se non converge resta la stima."""
    x, y = ta, tb
    for _ in range(30):
        pa, pb = A.at(x), B.at(y)
        fx, fy = pa[0] - pb[0], pa[1] - pb[1]
        if abs(fx) + abs(fy) < 1e-12:
            break
        da, db = A.d(x), B.d(y)
        det = da[0] * -db[1] - da[1] * -db[0]
        if abs(det) < 1e-14:
            return ta, tb
        dx = (fx * -db[1] - fy * -db[0]) / det
        dy = (da[0] * fy - da[1] * fx) / det
        x, y = x - dx, y - dy
        if not (-0.05 <= x <= 1.05 and -0.05 <= y <= 1.05):
            return ta, tb
    if math.dist(A.at(x), B.at(y)) > 1e-8 or math.dist(A.at(x), A.at(ta)) > 0.05:
        return ta, tb
    return min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)


TOUCH = 1e-3  # mm: un estremo così vicino a una linea la tocca (contatto a T)


def _free_ends(segs):
    """Estremi dei sottotracciati aperti fra questi segmenti (primo e ultimo segmento di ogni sottotracciato)."""
    by = {}
    for g in segs:
        by.setdefault(g.si, []).append(g)
    out = []
    for gs in by.values():
        gs.sort(key=lambda g: g.k)
        first, last = gs[0], gs[-1]
        p0, p1 = first.pts[0], last.pts[3]
        if math.dist(p0, p1) > 1e-9:  # chiuso: niente estremi
            out += [p0, p1]
    return out


def _project(A, P):
    """(t, distanza) del punto della curva vera di A più vicino a P: campioni, poi Newton su (A(t) − P)·A'(t) = 0."""
    best_t, best_d = 0.0, math.inf
    for k in range(65):
        t = k / 64
        d = math.dist(A.at(t), P)
        if d < best_d:
            best_t, best_d = t, d
    t = best_t
    for _ in range(25):
        q, d1 = A.at(t), A.d(t)
        h = 1e-6
        d1b = A.d(min(1.0, t + h))
        f = (q[0] - P[0]) * d1[0] + (q[1] - P[1]) * d1[1]
        fp = d1[0] ** 2 + d1[1] ** 2 + ((q[0] - P[0]) * (d1b[0] - d1[0]) + (q[1] - P[1]) * (d1b[1] - d1[1])) / h
        if abs(fp) < 1e-15:
            break
        nt = min(1.0, max(0.0, t - f / fp))
        if abs(nt - t) < 1e-15:
            break
        t = nt
    d = math.dist(A.at(t), P)
    if d > best_d:
        return best_t, best_d
    return t, d


def _visible(doc, s):
    if s.hidden:
        return False
    cs = doc.layers.get(s.layer)
    return cs is None or cs.show or isinstance(s, GroupShape)


def cutter_subs(doc, region):
    """Sottotracciati di tutte le linee visibili che toccano la zona (rettangolo sul piano)."""
    out = []
    reg = region.adjusted(-1e-6, -1e-6, 1e-6, 1e-6)
    for s in doc.shapes:
        if not _visible(doc, s) or isinstance(s, ImageShape):
            continue
        if not s.bounds().adjusted(-1e-6, -1e-6, 1e-6, 1e-6).intersects(reg):  # anche linee dritte (ingombro senza area)
            continue
        for leaf, tf in s.leaves():
            if isinstance(leaf, (ImageShape, GroupShape)) or leaf.hidden:
                continue
            cs = doc.layers.get(leaf.layer)
            if cs is not None and not cs.show:
                continue
            path = tf.map(leaf.local_path())
            out.append((s, nodes.from_path(path)))
    return out


# ------------------------------------------------------------------ forbici
def target_ok(doc, s):
    """'' se la forma si può tagliare, altrimenti il motivo (codice breve)."""
    if s is None:
        return "none"
    if isinstance(s, GroupShape):
        return "group"
    if isinstance(s, ImageShape):
        return "image"
    if s.locked:
        return "locked"
    if not _visible(doc, s):
        return "hidden"
    return ""


class Trimmer:
    """Punti di taglio di una forma (bersaglio) rispetto a tutte le linee visibili del piano."""

    def __init__(self, doc, shape):
        self.shape = shape
        self.subs = nodes.from_path(shape.path())
        self.segs = segments(self.subs)
        self.cuts = [[] for _ in self.subs]  # per sottotracciato: u ordinati
        self._compute(doc)

    def _compute(self, doc):
        """Per ogni forma che taglia (la forma stessa compresa) incroci e parti in comune, tenuti separati: un incrocio
        che cade dentro la parte in comune con la *stessa* forma non conta (sono i vertici delle due spezzate), uno di
        un'altra forma sì."""
        mine = self.segs
        sources = [("self", mine)]
        for s, subs in cutter_subs(doc, self.shape.bounds()):
            if s is not self.shape:
                sources.append((s, segments(subs)))
        found = [[] for _ in self.subs]  # per sottotracciato: [(punti, intervalli)] per ogni forma che taglia
        for src, segs in sources:
            pts = [[] for _ in self.subs]
            ovl = [[] for _ in self.subs]
            # 0.17.17: estremi liberi che toccano la linea (contatto a T), misurati sulla curva vera: sulla curva
            # appiattita un estremo esattamente sul cerchio può restare qualche millesimo fuori e non «toccare»
            for P in _free_ends(segs):
                for A in mine:
                    bx = A.box
                    if not (bx[0] - TOUCH <= P[0] <= bx[2] + TOUCH and bx[1] - TOUCH <= P[1] <= bx[3] + TOUCH):
                        continue
                    t, d = _project(A, P)
                    if d <= TOUCH:
                        pts[A.si].append(A.k + t)
            for A in mine:
                n = nseg(self.subs[A.si])
                for B in segs:
                    if (src == "self" and B is A) or not _overlap(A.box, B.box):
                        continue
                    nb = src == "self" and B.si == A.si
                    hp, ho = _hits(A, B)
                    for ta, tb in hp:
                        if nb and ((B.k == (A.k + 1) % n and ta > 1 - 1e-6 and tb < 1e-6)
                                   or (A.k == (B.k + 1) % n and ta < 1e-6 and tb > 1 - 1e-6)):
                            continue  # il nodo che unisce due segmenti consecutivi non è un incrocio
                        ta, _ = _newton(A, B, ta, tb)
                        pts[A.si].append(A.k + ta)
                    for a0, a1 in ho:
                        ovl[A.si].append((A.k + a0, A.k + a1))
            for si in range(len(self.subs)):
                if pts[si] or ovl[si]:
                    found[si].append((pts[si], ovl[si]))
        for si, sp in enumerate(self.subs):
            cuts = []
            for pts, ovl in found[si]:
                cuts += self._from_source(sp, pts, ovl)
            self.cuts[si] = self._dedup(sp, cuts)

    def _from_source(self, sp, pts, ovl):
        n = nseg(sp)
        merged = []
        for a, b in sorted(ovl):
            if merged and a <= merged[-1][1] + EPS_U:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        if sp.closed and len(merged) > 1 and merged[0][0] <= EPS_U and merged[-1][1] >= n - EPS_U:
            first = merged.pop(0)  # la parte comune passa dal punto di partenza: un intervallo solo
            merged[-1][1] = n + first[1]
        if any(b - a >= n - EPS_U for a, b in merged):
            return []  # tutta la linea coincide con questa forma (doppione): nessun taglio da lei
        cuts = []
        for a, b in merged:
            cuts += [a % n, b % n] if sp.closed else [a, b]

        def inside(u):
            for a, b in merged:
                for off in ((0, n) if sp.closed else (0,)):
                    if a + EPS_U < u + off < b - EPS_U:
                        return True
            return False

        return cuts + [u for u in pts if not inside(u)]

    def _dedup(self, sp, cuts):
        n = nseg(sp)
        out = []
        for u in sorted((c % n if sp.closed else c) for c in cuts):
            if not sp.closed and (u <= EPS_U or u >= n - EPS_U):
                continue  # gli estremi di una linea aperta sono già confini
            if out and self._close(sp, out[-1], u):
                continue
            out.append(float(u))
        if sp.closed and len(out) > 1 and self._close(sp, out[0], out[-1]):
            out.pop()
        return out

    def _point(self, sp_i, u):
        sp = self.subs[sp_i]
        n = nseg(sp)
        k = min(int(math.floor(u)), n - 1)
        seg = [s for s in self.segs if s.si == sp_i and s.k == k][0]
        return seg.at(u - k)

    def _close(self, sp, u1, u2):
        si = self.subs.index(sp)
        return abs(u1 - u2) < EPS_U or math.dist(self._point(si, u1), self._point(si, u2)) < 1e-6

    # -------------------------------------------------------------- tratto sotto il mouse
    def piece(self, si, u, corners=False):
        """(lo, hi) del tratto che contiene u, con hi > lo (per i chiusi hi può superare n). corners = anche i nodi."""
        sp = self.subs[si]
        n = nseg(sp)
        cuts = list(self.cuts[si])
        if corners:  # Maiusc: ci si ferma anche ai nodi (angoli) della linea
            nodes_u = range(0, n) if sp.closed else range(1, n)
            cuts = sorted(set(cuts) | {float(k) for k in nodes_u})
        if not sp.closed:
            lo = max([c for c in cuts if c <= u], default=0.0)
            hi = min([c for c in cuts if c > u], default=float(n))
            return lo, hi
        if len(cuts) <= 1:
            return (cuts[0], cuts[0] + n) if cuts else (0.0, float(n))
        before = [c for c in cuts if c <= u]
        after = [c for c in cuts if c > u]
        lo = before[-1] if before else cuts[-1] - n
        hi = after[0] if after else cuts[0] + n
        return lo, hi

    def _extract(self, si, ua, ub):
        """Sottotracciato aperto da ua a ub (ub > ua; per i chiusi si gira oltre la fine)."""
        sp = self.subs[si]
        n = nseg(sp)
        segs = {s.k: s for s in self.segs if s.si == si}
        parts = []
        u = ua
        while u < ub - EPS_T:
            k = int(math.floor(u + EPS_T))
            nxt = min(k + 1.0, ub)
            kk = k % n if sp.closed else min(k, n - 1)
            t1, t2 = u - k, nxt - k
            if t2 - t1 > EPS_T:
                parts.append((segs[kk].curve, _part(segs[kk], t1, t2)))
            u = nxt
        if not parts:
            return None
        nd = [nodes.Node(*parts[0][1][0])]
        for curve, (q0, q1, q2, q3) in parts:
            if curve:
                nd[-1].cout = q1
            nd.append(nodes.Node(q3[0], q3[1], cin=q2 if curve else None))
        for x in nd:
            x.smooth = nodes._is_smooth(x)
        if sum(math.dist(a.pt(), b.pt()) for a, b in zip(nd, nd[1:])) < 1e-6 and not any(c for c, _ in parts):
            return None
        return nodes.SubPath(nd, False)

    def piece_subpath(self, si, lo, hi):
        return self._extract(si, lo, hi)

    def remaining(self, si, u, corners=False):
        """Sottotracciati della forma dopo aver tolto il tratto che contiene u."""
        sp = self.subs[si]
        n = nseg(sp)
        lo, hi = self.piece(si, u, corners)
        keep = []
        if sp.closed:
            if hi - lo < n - EPS_U:
                keep.append(self._extract(si, hi, lo + n))
        else:
            if lo > EPS_U:
                keep.append(self._extract(si, 0.0, lo))
            if hi < n - EPS_U:
                keep.append(self._extract(si, hi, float(n)))
        out = [s.copy() for i, s in enumerate(self.subs) if i != si]
        out[si:si] = [k for k in keep if k is not None]
        return out


# ------------------------------------------------------------------ aggancio dopo il taglio (0.17.17)
TOL_JOIN = 1e-4  # mm: estremi che coincidono (quelli creati dalle forbici coincidono a ~1e-12)


def _ends(subs):
    return [n.pt() for sp in subs if not sp.closed and len(sp.nodes) >= 2 for n in (sp.nodes[0], sp.nodes[-1])]


def connect(doc, shape):
    """Dopo un taglio: le forme dello stesso livello che si toccano con gli estremi (anche a catena) diventano una
    forma sola con `shape`; i pezzi si uniscono e gli anelli si chiudono. -> (forme da assorbire, sottotracciati uniti).
    Bloccate, nascoste, gruppi e immagini restano fuori (come per le forbici)."""
    subs = nodes.from_path(shape.path())
    ends = _ends(subs)
    pool = [s for s in doc.shapes if s is not shape and target_ok(doc, s) == "" and s.layer == shape.layer]
    taken = []
    grew = True
    while grew and ends:
        grew = False
        for s in list(pool):
            b = s.bounds().adjusted(-TOL_JOIN, -TOL_JOIN, TOL_JOIN, TOL_JOIN)
            if not any(b.contains(x, y) for x, y in ends):
                continue
            ss = nodes.from_path(s.path())
            se = _ends(ss)
            if any(math.dist(a, c) <= TOL_JOIN for a in ends for c in se):
                taken.append(s)
                pool.remove(s)
                subs += ss
                ends += se
                grew = True
    return taken, nodes.join_endpoints(subs, TOL_JOIN)


def nearest(doc, p, tol):
    """(forma, sottotracciato, u, distanza) della linea più vicina a p entro tol (mm), anche se non tagliabile."""
    best = None
    for s in reversed(doc.shapes):
        if not _visible(doc, s) or isinstance(s, ImageShape):
            continue
        if not s.bounds().adjusted(-tol, -tol, tol, tol).contains(p[0], p[1]):
            continue
        for si, sp in enumerate(nodes.from_path(s.path())):
            for k, (i, j) in enumerate(sp.segments()):
                t, d, _q = nodes.nearest_on_segment(sp, i, j, p)
                if d <= tol and (best is None or d < best[3] - 1e-9):
                    best = (s, si, k + t, d)
    return best
