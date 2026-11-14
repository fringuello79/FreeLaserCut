# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Semplifica tracciati (0.19.6): ricostruisce un tracciato con meno nodi, curve lisce e tratti dritti, entro una
tolleranza in mm. Lo usano il comando «Semplifica tracciati…» e lo strumento Mano libera.

Metodo (scritto da zero dalla descrizione matematica degli algoritmi, nessun codice di terzi):
1. ogni sottopercorso si campiona nel sistema del piano: curve appiattite a 0,0025 mm, poi punti fitti (passo ≤ metà
   della tolleranza) anche lungo i tratti dritti;
2. gli spigoli si cercano sui vertici della semplificazione di Ramer–Douglas–Peucker (1972/1973): dove la direzione,
   misurata a metà dei tratti vicini, cambia più dell'angolo scelto, resta un angolo vivo;
3. fra due spigoli: se tutti i punti stanno entro la tolleranza dalla corda, un tratto dritto; altrimenti Bézier
   cubiche ai minimi quadrati con le tangenti agli estremi (P. J. Schneider, Graphics Gems, 1990), riparametrizzazione
   di Newton e divisione nel punto peggiore; ogni curva accettata è controllata nei due sensi (i punti dalla curva e
   la curva dai punti); rete di sicurezza: tratti dritti di Douglas–Peucker, che stanno sempre nella tolleranza;
4. «Solo tratti dritti»: solo la semplificazione di Douglas–Peucker.

Invarianti (documento freeburn/aggiornamento-0.19.6.md): scarto ≤ tolleranza nei due sensi, aperto/chiuso invariato,
estremi delle linee aperte e punto di partenza dei chiusi fermi, stesso numero e verso dei sottopercorsi, mai più nodi
di prima (altrimenti il sottopercorso resta identico), niente viene cancellato.
"""
import math
from dataclasses import dataclass

import numpy as np

from . import nodes as N
from .geom import FLATTEN_TOL, _flatten_cubic, flatten

TOL_MIN, TOL_MAX, TOL_DEFAULT = 0.01, 5.0, 0.1  # mm
ANGLE_MIN, ANGLE_MAX, ANGLE_DEFAULT = 5.0, 175.0, 40.0  # gradi
SAMPLE_ERR = 0.0025  # mm: errore dell'appiattimento delle curve dell'originale
MAX_SAMPLES = 1_500_000  # campioni per sottopercorso: oltre, il passo si allarga
_MAX_DEPTH = 40


def clamp_tol(t):
    try:
        t = float(t)
    except (TypeError, ValueError):
        return TOL_DEFAULT
    if not math.isfinite(t):
        return TOL_DEFAULT
    return min(TOL_MAX, max(TOL_MIN, t))


def clamp_angle(a):
    try:
        a = float(a)
    except (TypeError, ValueError):
        return ANGLE_DEFAULT
    if not math.isfinite(a):
        return ANGLE_DEFAULT
    return min(ANGLE_MAX, max(ANGLE_MIN, a))


@dataclass
class Stats:
    subpaths: int = 0  # sottopercorsi esaminati
    changed: int = 0  # sottopercorsi sostituiti
    nodes_before: int = 0
    nodes_after: int = 0
    max_err: float = 0.0  # mm, scarto massimo misurato sui sottopercorsi sostituiti
    gcode_before: int = 0  # tratti di G-code (alla tolleranza di uscita) prima e dopo
    gcode_after: int = 0
    shapes: int = 0  # tracciati toccati
    skipped: int = 0  # forme vettoriali non tracciato (rettangoli, testi…), lasciate come sono

    def add(self, o):
        for k in ("subpaths", "changed", "nodes_before", "nodes_after", "gcode_before", "gcode_after", "shapes",
                  "skipped"):
            setattr(self, k, getattr(self, k) + getattr(o, k))
        self.max_err = max(self.max_err, o.max_err)


# ====================================================================== campionamento
def _unit(v):
    n = math.hypot(v[0], v[1])
    return (v / n) if n > 1e-12 else None


def _sample(sp, step):
    """SubPath -> (punti (n, 2), è chiuso). I nodi dell'originale sono fra i punti, esatti."""
    nds = sp.nodes
    seq = [nds[0].pt()]
    for i, j in sp.segments():
        if sp.is_curve(i, j):
            _flatten_cubic(*sp.bezier(i, j), SAMPLE_ERR, seq)
        else:
            seq.append(nds[j].pt())
    T = np.asarray(seq, dtype=float)
    if len(T) > 1:  # via i punti doppi
        d = np.hypot(*np.diff(T, axis=0).T)
        T = np.vstack([T[:1], T[1:][d >= 1e-9]])
    if len(T) > 1:  # punti fitti anche lungo i tratti dritti: nessun buco più lungo del passo
        D = np.diff(T, axis=0)
        k = np.maximum(1, np.ceil(np.hypot(*D.T) / step)).astype(np.int64)
        seg = np.repeat(np.arange(len(D)), k)
        r = np.arange(int(k.sum())) - np.repeat(np.cumsum(k) - k, k)
        P = np.vstack([T[seg] + D[seg] * (r / k[seg])[:, None], T[-1:]])
    else:
        P = T
    closed = sp.closed
    if closed and len(P) > 1 and math.dist(P[0], P[-1]) < 1e-9:
        P = P[:-1]
    return P, closed


def _arclen(P):
    return np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))))


def _at(P, s, t):
    """Punto della spezzata P (lunghezze cumulate s) alla lunghezza t (limitata agli estremi)."""
    t = min(max(t, 0.0), s[-1])
    k = int(np.searchsorted(s, t, side="right")) - 1
    k = min(max(k, 0), len(P) - 2)
    L = s[k + 1] - s[k]
    f = 0.0 if L <= 1e-15 else (t - s[k]) / L
    return P[k] + (P[k + 1] - P[k]) * f


def _dist_seg(Q, A, B):
    """Distanze dei punti Q dal segmento AB."""
    AB = B - A
    L2 = float(AB @ AB)
    if L2 < 1e-24:
        return np.hypot(*(Q - A).T)
    t = np.clip(((Q - A) @ AB) / L2, 0.0, 1.0)
    return np.hypot(*(Q - (A + t[:, None] * AB)).T)


def _rdp(P, a, b, tol):
    """Indici tenuti da Ramer–Douglas–Peucker fra a e b compresi (P[a..b])."""
    keep = [a, b]
    stack = [(a, b)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        d = _dist_seg(P[i + 1:j], P[i], P[j])
        k = int(np.argmax(d))
        if d[k] > tol:
            m = i + 1 + k
            keep.append(m)
            stack.append((i, m))
            stack.append((m, j))
    return sorted(set(keep))


# ====================================================================== spigoli
def _corners(Pe, se, n, closed, tol, angle):
    """Pe = punti (per i chiusi con il primo ripetuto in fondo), se = lunghezze, n = punti veri.
    -> (vertici di Douglas–Peucker in 0..n-1, insieme degli spigoli)."""
    if closed:
        far = int(np.argmax(np.hypot(*(Pe[:n] - Pe[0]).T)))
        if far == 0:
            return [0], set()
        K = sorted(set(_rdp(Pe, 0, far, tol)) | set(_rdp(Pe, far, n, tol)))
        K = [k for k in K if k < n]
    else:
        K = _rdp(Pe, 0, n - 1, tol)
    L = se[-1]
    thr = math.radians(angle)
    corners = set()
    m = len(K)
    for q in range(m):
        k = K[q]
        if not closed and q in (0, m - 1):
            continue
        if closed and m < 3:
            break
        kp, kn = K[q - 1], K[(q + 1) % m]
        sk = se[k]
        back = (sk - se[kp]) if kp < k else (sk + L - se[kp])
        fwd = (se[kn] - sk) if kn > k else (se[kn] + L - sk)
        a = _at_c(Pe, se, sk - back / 2, closed)
        b = _at_c(Pe, se, sk + fwd / 2, closed)
        v1, v2 = Pe[k] - a, b - Pe[k]
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 < 1e-12 or n2 < 1e-12:
            continue
        c = max(-1.0, min(1.0, float(v1 @ v2) / (n1 * n2)))
        if math.acos(c) > thr:
            corners.add(k)
    return K, corners


def _at_c(Pe, se, t, closed):
    if closed:
        L = se[-1]
        if L > 0:
            t = t % L
    return _at(Pe, se, t)


# ====================================================================== Bézier ai minimi quadrati
def _bez(b, u):
    u = u[:, None]
    v = 1 - u
    return v ** 3 * b[0] + 3 * v * v * u * b[1] + 3 * v * u * u * b[2] + u ** 3 * b[3]


def _bez_d1(b, u):
    u = u[:, None]
    v = 1 - u
    return 3 * v * v * (b[1] - b[0]) + 6 * v * u * (b[2] - b[1]) + 3 * u * u * (b[3] - b[2])


def _bez_d2(b, u):
    u = u[:, None]
    return 6 * (1 - u) * (b[2] - 2 * b[1] + b[0]) + 6 * u * (b[3] - 2 * b[2] + b[1])


def _chord_params(Q):
    s = _arclen(Q)
    return s / s[-1] if s[-1] > 0 else np.linspace(0.0, 1.0, len(Q))


def _generate(Q, u, t1, t2):
    """Bézier con estremi Q[0], Q[-1] e tangenti t1 (uscente), t2 (entrante, verso l'interno) ai minimi quadrati."""
    p0, p3 = Q[0], Q[-1]
    v = 1 - u
    B0, B1, B2, B3 = v ** 3, 3 * v * v * u, 3 * v * u * u, u ** 3
    A1 = t1[None, :] * B1[:, None]
    A2 = t2[None, :] * B2[:, None]
    c00 = float(np.sum(A1 * A1))
    c01 = float(np.sum(A1 * A2))
    c11 = float(np.sum(A2 * A2))
    tmp = Q - (p0 * (B0 + B1)[:, None] + p3 * (B2 + B3)[:, None])
    x0 = float(np.sum(A1 * tmp))
    x1 = float(np.sum(A2 * tmp))
    det = c00 * c11 - c01 * c01
    seg = math.hypot(*(p3 - p0))
    al = ar = 0.0
    if abs(det) > 1e-18:
        al = (x0 * c11 - x1 * c01) / det
        ar = (c00 * x1 - c01 * x0) / det
    eps = 1e-6 * seg
    if al < eps or ar < eps or not (math.isfinite(al) and math.isfinite(ar)):
        al = ar = seg / 3.0
    return np.array([p0, p0 + t1 * al, p3 + t2 * ar, p3])


def _reparam(Q, b, u):
    """Un passo di Newton: per ogni punto il parametro della curva più vicino."""
    d = _bez(b, u) - Q
    d1 = _bez_d1(b, u)
    d2 = _bez_d2(b, u)
    num = np.sum(d * d1, axis=1)
    den = np.sum(d1 * d1 + d * d2, axis=1)
    ok = np.abs(den) > 1e-15
    nu = u.copy()
    nu[ok] = u[ok] - num[ok] / den[ok]
    nu = np.clip(nu, 0.0, 1.0)
    nu[0], nu[-1] = 0.0, 1.0
    if np.any(np.diff(nu) < 0):  # i parametri devono restare in ordine
        return u
    return nu


def _max_err(Q, b, u):
    d = np.hypot(*(_bez(b, u) - Q).T)
    k = int(np.argmax(d))
    return float(d[k]), k


def _bulge(b, Q, u, tol):
    """Distanza massima della curva dalla spezzata Q (punti della curva fra i parametri dei punti). Conservativa:
    si cerca il segmento più vicino in una finestra attorno al parametro; un valore troppo alto fa solo dividere."""
    m = len(Q)
    L = float(np.sum(np.hypot(*np.diff(Q, axis=0).T)))
    K = int(min(2000, max(24, 2 * L / tol + 16)))  # un punto della curva ogni mezza tolleranza
    t = np.linspace(0.0, 1.0, K)
    C = _bez(b, t)
    idx = np.clip(np.searchsorted(u, t), 1, m - 1)
    W = 24  # i parametri vengono da Newton: il segmento giusto è vicino
    A = Q[:-1]
    B = Q[1:]
    worst = 0.0
    for c0 in range(0, K, 512):
        cs = slice(c0, min(K, c0 + 512))
        Cc, ic = C[cs], idx[cs]
        lo = np.clip(ic - W, 0, m - 2)
        span = np.arange(2 * W + 1)
        segi = np.clip(lo[:, None] + span[None, :], 0, m - 2)
        a, bb = A[segi], B[segi]
        ab = bb - a
        L2 = np.sum(ab * ab, axis=2)
        L2 = np.where(L2 < 1e-24, 1.0, L2)
        tt = np.clip(np.sum((Cc[:, None, :] - a) * ab, axis=2) / L2, 0.0, 1.0)
        pr = a + tt[:, :, None] * ab
        d = np.min(np.hypot(Cc[:, None, 0] - pr[:, :, 0], Cc[:, None, 1] - pr[:, :, 1]), axis=1)
        worst = max(worst, float(np.max(d)))
        if worst > tol:
            break
    return worst


def _tangent_at(Q, s, k, w, back):
    """Tangente centrata nel punto k (verso l'indietro se back) misurata su una finestra di lunghezza w."""
    a = _at(Q, s, s[k] - w)
    b = _at(Q, s, s[k] + w)
    v = _unit(a - b) if back else _unit(b - a)
    if v is None:
        v = _unit(Q[max(k - 1, 0)] - Q[min(k + 1, len(Q) - 1)])
        if v is not None and not back:
            v = -v
    return v


def _lines(Q, tol, out, err):
    K = _rdp(Q, 0, len(Q) - 1, tol)
    for a, b in zip(K[:-1], K[1:]):
        if b > a + 1:
            err[0] = max(err[0], float(np.max(_dist_seg(Q[a + 1:b], Q[a], Q[b]))))
        out.append(("L", Q[b]))


def _fit(Q, t1, t2, tol, w, out, err, depth=0):
    m = len(Q)
    if m < 2:
        return
    dline = float(np.max(_dist_seg(Q, Q[0], Q[-1]))) if m > 2 else 0.0
    if dline <= tol:
        err[0] = max(err[0], dline)
        out.append(("L", Q[-1]))
        return
    if t1 is None or t2 is None or m <= 3 or depth > _MAX_DEPTH:
        _lines(Q, tol, out, err)
        return
    u = _chord_params(Q)
    b = _generate(Q, u, t1, t2)
    e, split = _max_err(Q, b, u)
    tries = 0
    while True:
        if e <= tol:
            g = _bulge(b, Q, u, tol)
            if g <= tol:
                err[0] = max(err[0], e, g)
                out.append(("C", b))
                return
            break
        if e > 4 * tol or tries >= 8:
            break
        u = _reparam(Q, b, u)
        b = _generate(Q, u, t1, t2)
        e, split = _max_err(Q, b, u)
        tries += 1
    split = min(max(split, 1), m - 2)
    s = _arclen(Q)
    win = min(w, 0.5 * min(s[split], s[-1] - s[split]))
    tc = _tangent_at(Q, s, split, max(win, 1e-9), back=True)
    if tc is None:
        _lines(Q, tol, out, err)
        return
    _fit(Q[:split + 1], t1, tc, tol, w, out, err, depth + 1)
    _fit(Q[split:], -tc, t2, tol, w, out, err, depth + 1)


# ====================================================================== un sottopercorso
def simplify_subpath(sp, tol=TOL_DEFAULT, angle=ANGLE_DEFAULT, lines_only=False):
    """SubPath -> (SubPath nuovo, scarto massimo) oppure (None, 0) se non si migliora o non si può."""
    tol, angle = clamp_tol(tol), clamp_angle(angle)
    if len(sp.nodes) < 2 or (sp.closed and len(sp.nodes) < 3):
        return None, 0.0
    step = max(min(tol * 0.5, 0.5), 0.002)
    approx = sum(math.dist(a.pt(), b.pt()) for a, b in zip(sp.nodes, sp.nodes[1:] + sp.nodes[:1]))
    if approx / step > MAX_SAMPLES:
        step = approx / MAX_SAMPLES
    P, closed = _sample(sp, step)
    n = len(P)
    if n < 2 or (closed and n < 3):
        return None, 0.0
    Pe = np.vstack([P, P[:1]]) if closed else P
    se = _arclen(Pe)
    if se[-1] < 1e-9:
        return None, 0.0
    K, corners = _corners(Pe, se, n, closed, tol, angle)
    out, err = [], [0.0]
    w = min(max(2 * tol, 4 * step), 1e9)
    if lines_only:
        if closed and len(K) < 2:
            return None, 0.0
        for a, b in zip(K, K[1:] + ([n] if closed else [])):
            _lines(Pe[a:b + 1], tol, out, err)
    else:
        brk = sorted(corners | ({0} if closed else {0, n - 1}))
        if closed and len(brk) == 1:  # un giro intero non sta in una curva sola: un secondo punto liscio di fronte
            far = int(np.argmax(np.hypot(*(P - P[brk[0]]).T)))
            if far == brk[0]:
                return None, 0.0
            brk = sorted({brk[0], far})
        ends = brk[1:] + ([n] if closed else [])
        for a, b in zip(brk, ends):
            Q = Pe[a:b + 1]
            if len(Q) < 2:
                continue
            sq = _arclen(Q)
            ww = min(w, 0.25 * sq[-1])
            # tangente all'inizio: da un lato sugli spigoli e sugli estremi, centrata sul punto di partenza liscio
            if a in corners or (not closed and a == 0) or ww <= 0:
                t1 = _unit(_at(Q, sq, ww) - Q[0]) if ww > 0 else None
            else:
                t1 = _unit(_at_c(Pe, se, se[a] + ww, True) - _at_c(Pe, se, se[a] - ww, True))
            bend = b % n if closed else b
            if bend in corners or (not closed and b == n - 1) or ww <= 0:
                t2 = _unit(_at(Q, sq, sq[-1] - ww) - Q[-1]) if ww > 0 else None
            else:
                t2 = _unit(_at_c(Pe, se, se[b] - ww, True) - _at_c(Pe, se, se[b] + ww, True))
            _fit(Q, t1, t2, tol, w, out, err)
    nodes_out = [N.Node(*P[0])]
    for kind, v in out:
        if kind == "C":
            nodes_out[-1].cout = (float(v[1][0]), float(v[1][1]))
            nodes_out.append(N.Node(float(v[3][0]), float(v[3][1]), cin=(float(v[2][0]), float(v[2][1]))))
        else:
            nodes_out.append(N.Node(float(v[0]), float(v[1])))
    if closed:
        last = nodes_out.pop()  # è il punto di partenza: la sua maniglia entrante va al primo nodo
        nodes_out[0].cin = last.cin
    else:  # estremi esatti (i calcoli in virgola mobile non li devono spostare)
        nodes_out[-1].x, nodes_out[-1].y = sp.nodes[-1].pt()
    nodes_out[0].x, nodes_out[0].y = sp.nodes[0].pt()
    for nd in nodes_out:
        nd.smooth = N._is_smooth(nd)
    if len(nodes_out) < 2 or (closed and len(nodes_out) < 2) or len(nodes_out) >= len(sp.nodes):
        return None, 0.0
    return N.SubPath(nodes_out, closed), err[0]


def gcode_segments(path):
    """Tratti di G-code che produrrebbe un QPainterPath alla tolleranza di uscita."""
    return sum(len(p.pts) - (0 if p.closed else 1) for p in flatten(path, FLATTEN_TOL))


def simplify_subpaths(subs, tol=TOL_DEFAULT, angle=ANGLE_DEFAULT, lines_only=False, stats=None):
    """-> lista nuova di SubPath (quelli che non migliorano restano gli stessi oggetti)."""
    st = stats if stats is not None else Stats()
    res = []
    for sp in subs:
        st.subpaths += 1
        st.nodes_before += len(sp.nodes)
        new, e = simplify_subpath(sp, tol, angle, lines_only)
        if new is None:
            res.append(sp)
            st.nodes_after += len(sp.nodes)
        else:
            res.append(new)
            st.changed += 1
            st.nodes_after += len(new.nodes)
            st.max_err = max(st.max_err, e)
    return res


def simplify_path(path, tol=TOL_DEFAULT, angle=ANGLE_DEFAULT, lines_only=False, stats=None):
    """QPainterPath (piano) -> (QPainterPath, Stats). Se nulla migliora restituisce una copia identica."""
    from PySide6.QtGui import QPainterPath

    st = stats if stats is not None else Stats()
    subs = N.from_path(path)
    before = Stats()
    new = simplify_subpaths(subs, tol, angle, lines_only, before)
    st.add(before)
    if not before.changed:
        return QPainterPath(path), st
    return N.to_path(new), st


# ====================================================================== forme
def targets(shapes):
    """Forme scelte -> ([(foglia PathShape, trasformazione completa)], forme vettoriali saltate)."""
    from .document import ImageShape, PathShape

    out, skipped = [], 0
    for s in shapes:
        if s.locked or s.role:
            continue
        for leaf, tf in s.leaves():
            if isinstance(leaf, PathShape) and not leaf.role:
                out.append((leaf, tf))
            elif not isinstance(leaf, ImageShape):
                skipped += 1
    return out, skipped


def plan(items, tol=TOL_DEFAULT, angle=ANGLE_DEFAULT, lines_only=False):
    """[(foglia, tf)] -> ([(foglia, nuovo percorso locale)], Stats). Solo le foglie che cambiano; il percorso è nelle
    coordinate locali della foglia (la sua trasformazione resta)."""
    st = Stats()
    res = []
    for leaf, tf in items:
        inv, ok = tf.inverted()
        world = tf.map(leaf.local_path())
        one = Stats()
        new_world, one = simplify_path(world, tol, angle, lines_only, one)
        gb = gcode_segments(world)
        st.gcode_before += gb
        if not one.changed or not ok:
            st.gcode_after += gb
            one.nodes_after = one.nodes_before
            one.changed = 0
            one.max_err = 0.0
            st.add(one)
            continue
        st.gcode_after += gcode_segments(new_world)
        one.shapes = 1
        st.add(one)
        res.append((leaf, inv.map(new_world)))
    return res, st
