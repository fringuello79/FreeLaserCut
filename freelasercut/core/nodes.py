# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Modello a nodi per la modifica dei tracciati (stile CAD).

Un tracciato è una lista di SubPath; ogni SubPath è una lista di Node con maniglie
di Bézier opzionali (cin = maniglia entrante, cout = maniglia uscente).
Conversione bidirezionale con QPainterPath, più le operazioni del modificatore di nodi:
sposta nodo/maniglia, elimina, inserisci, angolo/morbido, spezza, raddrizza, unisci estremi.
"""
import math

from PySide6.QtGui import QPainterPath


class Node:
    __slots__ = ("x", "y", "cin", "cout", "smooth")

    def __init__(self, x, y, cin=None, cout=None, smooth=False):
        self.x, self.y = float(x), float(y)
        self.cin = cin  # (x, y) oppure None
        self.cout = cout
        self.smooth = smooth

    def pt(self):
        return (self.x, self.y)

    def copy(self):
        return Node(self.x, self.y, self.cin, self.cout, self.smooth)

    def move(self, dx, dy):
        self.x += dx
        self.y += dy
        if self.cin:
            self.cin = (self.cin[0] + dx, self.cin[1] + dy)
        if self.cout:
            self.cout = (self.cout[0] + dx, self.cout[1] + dy)


class SubPath:
    __slots__ = ("nodes", "closed")

    def __init__(self, nodes=None, closed=False):
        self.nodes = nodes or []
        self.closed = closed

    def copy(self):
        return SubPath([n.copy() for n in self.nodes], self.closed)

    def segments(self):
        """[(i, j)] coppie di indici dei nodi agli estremi di ogni segmento."""
        n = len(self.nodes)
        out = [(i, i + 1) for i in range(n - 1)]
        if self.closed and n > 1:
            out.append((n - 1, 0))
        return out

    def is_curve(self, i, j):
        return self.nodes[i].cout is not None or self.nodes[j].cin is not None

    def bezier(self, i, j):
        a, b = self.nodes[i], self.nodes[j]
        return a.pt(), a.cout or a.pt(), b.cin or b.pt(), b.pt()


# ------------------------------------------------------------------ conversioni
def from_path(path: QPainterPath, tol=1e-6):
    subs = []
    cur = None
    i = 0
    n = path.elementCount()
    while i < n:
        e = path.elementAt(i)
        t = e.type
        if t == QPainterPath.ElementType.MoveToElement:
            cur = SubPath([Node(e.x, e.y)])
            subs.append(cur)
            i += 1
        elif t == QPainterPath.ElementType.LineToElement:
            if cur is None:
                cur = SubPath([Node(e.x, e.y)])
                subs.append(cur)
            else:
                cur.nodes.append(Node(e.x, e.y))
            i += 1
        elif t == QPainterPath.ElementType.CurveToElement:
            c1 = (e.x, e.y)
            e2, e3 = path.elementAt(i + 1), path.elementAt(i + 2)
            if cur is None:
                cur = SubPath([Node(e.x, e.y)])
                subs.append(cur)
            cur.nodes[-1].cout = c1
            cur.nodes.append(Node(e3.x, e3.y, cin=(e2.x, e2.y)))
            i += 3
        else:
            i += 1
    for sp in subs:
        if len(sp.nodes) > 2:
            a, b = sp.nodes[0], sp.nodes[-1]
            if math.dist(a.pt(), b.pt()) < 1e-4:
                a.cin = b.cin
                sp.nodes.pop()
                sp.closed = True
    for sp in subs:
        for nd in sp.nodes:
            nd.smooth = _is_smooth(nd)
    return [sp for sp in subs if sp.nodes]


def _is_smooth(nd):
    if not nd.cin or not nd.cout:
        return False
    v1 = (nd.x - nd.cin[0], nd.y - nd.cin[1])
    v2 = (nd.cout[0] - nd.x, nd.cout[1] - nd.y)
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < 1e-9 or l2 < 1e-9:
        return False
    return abs((v1[0] * v2[1] - v1[1] * v2[0]) / (l1 * l2)) < 0.02 and (v1[0] * v2[0] + v1[1] * v2[1]) > 0


def to_path(subs):
    p = QPainterPath()
    for sp in subs:
        if not sp.nodes:
            continue
        p.moveTo(*sp.nodes[0].pt())
        for i, j in sp.segments():
            if sp.is_curve(i, j):
                _, c1, c2, e = sp.bezier(i, j)
                p.cubicTo(c1[0], c1[1], c2[0], c2[1], e[0], e[1])
            else:
                p.lineTo(*sp.nodes[j].pt())
        if sp.closed:
            p.closeSubpath()
    return p


# ------------------------------------------------------------------ geometria
def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def bez_point(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def nearest_on_segment(sp, i, j, pt, samples=48):
    """(t, distanza, punto) del punto del segmento più vicino a pt."""
    if not sp.is_curve(i, j):
        a, b = sp.nodes[i].pt(), sp.nodes[j].pt()
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / L2))
        q = (a[0] + dx * t, a[1] + dy * t)
        return t, math.dist(q, pt), q
    bz = sp.bezier(i, j)
    best = (0.0, math.inf, bz[0])
    for k in range(samples + 1):
        t = k / samples
        q = bez_point(*bz, t)
        d = math.dist(q, pt)
        if d < best[1]:
            best = (t, d, q)
    # affinamento locale
    t0 = best[0]
    step = 1.0 / samples
    for _ in range(20):
        step /= 2
        for t in (t0 - step, t0 + step):
            if 0 <= t <= 1:
                q = bez_point(*bz, t)
                d = math.dist(q, pt)
                if d < best[1]:
                    best = (t, d, q)
        t0 = best[0]
    return best


# ------------------------------------------------------------------ operazioni
def insert_node(sp, i, j, t):
    """Divide il segmento (i -> j) in t, con de Casteljau per le curve. Ritorna l'indice del nuovo nodo."""
    a, b = sp.nodes[i], sp.nodes[j]
    if sp.is_curve(i, j):
        p0, p1, p2, p3 = sp.bezier(i, j)
        p01, p12, p23 = _lerp(p0, p1, t), _lerp(p1, p2, t), _lerp(p2, p3, t)
        p012, p123 = _lerp(p01, p12, t), _lerp(p12, p23, t)
        mid = _lerp(p012, p123, t)
        a.cout = p01
        b.cin = p23
        new = Node(mid[0], mid[1], cin=p012, cout=p123, smooth=True)
    else:
        q = _lerp(a.pt(), b.pt(), t)
        new = Node(q[0], q[1])
    idx = j if j != 0 else len(sp.nodes)
    sp.nodes.insert(idx, new)
    return idx


def delete_node(subs, si, ni):
    sp = subs[si]
    sp.nodes.pop(ni)
    if len(sp.nodes) < 2 or (sp.closed and len(sp.nodes) < 2):
        subs.pop(si)
    elif sp.closed and len(sp.nodes) == 2 and not any(n.cin or n.cout for n in sp.nodes):
        sp.closed = False


def set_corner(nd):
    nd.smooth = False


def set_smooth(sp, ni):
    nd = sp.nodes[ni]
    n = len(sp.nodes)
    prev = sp.nodes[ni - 1] if (ni > 0 or sp.closed) else None
    nxt = sp.nodes[(ni + 1) % n] if (ni < n - 1 or sp.closed) else None
    # direzione tangente: dal nodo precedente al successivo
    pa = prev.pt() if prev else nd.pt()
    pb = nxt.pt() if nxt else nd.pt()
    tx, ty = pb[0] - pa[0], pb[1] - pa[1]
    L = math.hypot(tx, ty) or 1.0
    tx, ty = tx / L, ty / L
    lin = math.dist(nd.pt(), pa) / 3 if prev else 0
    lout = math.dist(nd.pt(), pb) / 3 if nxt else 0
    if nd.cin and prev:
        lin = math.dist(nd.cin, nd.pt()) or lin
    if nd.cout and nxt:
        lout = math.dist(nd.cout, nd.pt()) or lout
    nd.cin = (nd.x - tx * lin, nd.y - ty * lin) if prev else None
    nd.cout = (nd.x + tx * lout, nd.y + ty * lout) if nxt else None
    nd.smooth = True


def straighten(sp, i, j):
    sp.nodes[i].cout = None
    sp.nodes[j].cin = None
    sp.nodes[i].smooth = False
    sp.nodes[j].smooth = False


def curve_segment(sp, i, j):
    a, b = sp.nodes[i], sp.nodes[j]
    if a.cout is None:
        a.cout = _lerp(a.pt(), b.pt(), 1 / 3)
    if b.cin is None:
        b.cin = _lerp(a.pt(), b.pt(), 2 / 3)


def move_handle(nd, which, x, y):
    """Sposta una maniglia; se il nodo è morbido la maniglia opposta resta allineata."""
    if which == "in":
        nd.cin = (x, y)
        other = nd.cout
    else:
        nd.cout = (x, y)
        other = nd.cin
    if nd.smooth and other is not None:
        vx, vy = nd.x - x, nd.y - y
        L = math.hypot(vx, vy)
        lo = math.dist(other, nd.pt())
        if L > 1e-9:
            o = (nd.x + vx / L * lo, nd.y + vy / L * lo)
            if which == "in":
                nd.cout = o
            else:
                nd.cin = o


def break_at(subs, si, ni):
    """Spezza il tracciato nel nodo: un chiuso diventa aperto, un aperto diventa due."""
    sp = subs[si]
    nd = sp.nodes[ni]
    if sp.closed:
        nodes = sp.nodes[ni:] + sp.nodes[:ni]
        last = nd.copy()
        last.cout = None
        nodes[0] = nd.copy()
        nodes[0].cin = None
        nodes.append(last)
        last.smooth = nodes[0].smooth = False
        subs[si] = SubPath(nodes, False)
        return
    if ni == 0 or ni == len(sp.nodes) - 1:
        return
    a = SubPath([n.copy() for n in sp.nodes[:ni + 1]], False)
    b = SubPath([n.copy() for n in sp.nodes[ni:]], False)
    a.nodes[-1].cout = None
    b.nodes[0].cin = None
    subs[si:si + 1] = [a, b]


def reverse(sp):
    nodes = []
    for nd in reversed(sp.nodes):
        nodes.append(Node(nd.x, nd.y, cin=nd.cout, cout=nd.cin, smooth=nd.smooth))
    sp.nodes = nodes


def join_endpoints(subs, tol=0.05):
    """Unisce i sottopercorsi aperti con estremi coincidenti (entro tol). Chiude quelli che si richiudono."""
    changed = True
    while changed:
        changed = False
        opens = [k for k, s in enumerate(subs) if not s.closed and len(s.nodes) >= 2]
        for a in opens:
            sa = subs[a]
            if math.dist(sa.nodes[0].pt(), sa.nodes[-1].pt()) <= tol and len(sa.nodes) > 2:
                first, last = sa.nodes[0], sa.nodes.pop()
                first.cin = last.cin
                sa.closed = True
                changed = True
                break
            for b in opens:
                if a == b:
                    continue
                sb = subs[b]
                # (estremo di a, estremo di b, gira a, gira b): dopo i giri la fine di a e l'inizio di b sono il punto
                # in comune. 0.17.17: prima «inizio-fine» e «inizio-inizio» avevano i giri di b scambiati, e un pezzo si
                # perdeva o veniva attaccato dalla parte sbagliata (salto dritto)
                pairs = ((sa.nodes[-1], sb.nodes[0], False, False), (sa.nodes[-1], sb.nodes[-1], False, True),
                         (sa.nodes[0], sb.nodes[-1], True, True), (sa.nodes[0], sb.nodes[0], True, False))
                for na, nb, rev_a, rev_b in pairs:
                    if math.dist(na.pt(), nb.pt()) <= tol:
                        if rev_a:
                            reverse(sa)
                        if rev_b:
                            reverse(sb)
                        joint = sa.nodes[-1]
                        joint.cout = sb.nodes[0].cout
                        sa.nodes.extend(sb.nodes[1:])
                        subs.pop(b)
                        changed = True
                        break
                if changed:
                    break
            if changed:
                break
    return subs


def close_subpaths(subs, tol=0.5):
    n = 0
    for sp in subs:
        if not sp.closed and len(sp.nodes) > 2 and math.dist(sp.nodes[0].pt(), sp.nodes[-1].pt()) <= tol:
            last = sp.nodes.pop()
            sp.nodes[0].cin = last.cin
            sp.closed = True
            n += 1
        elif not sp.closed and len(sp.nodes) > 2 and tol >= 1e9:
            sp.closed = True
            n += 1
    return n


def corner_limit(pts):
    """0.18.2: raggio più grande che nessun vertice del poligono chiuso (punti in mm) deve limitare: per ogni vertice
    metà del lato più corto dei due che lo toccano, per tan(angolo/2)."""
    n = len(pts)
    best = math.inf
    for i in range(n):
        p, a, b = pts[i], pts[i - 1], pts[(i + 1) % n]
        la, lb = math.dist(p, a), math.dist(p, b)
        if la < 1e-9 or lb < 1e-9:
            continue
        cosang = max(-1.0, min(1.0, ((a[0] - p[0]) * (b[0] - p[0]) + (a[1] - p[1]) * (b[1] - p[1])) / (la * lb)))
        ang = math.acos(cosang)
        if 1e-6 < ang < math.pi - 1e-6:
            best = min(best, min(la, lb) / 2 * math.tan(ang / 2))
    return 0.0 if best == math.inf else best


def round_corners(pts, r):
    """0.18.2: poligono chiuso (punti in mm veri) con ogni vertice arrotondato da un arco di cerchio di raggio r,
    tangente ai due lati. Vertice per vertice il raccordo si limita a metà dei due lati *originali* (quindi due
    raccordi vicini non si sovrappongono mai); vale anche per i vertici rientranti (stelle). -> SubPath chiuso."""
    n = len(pts)
    out = []
    for i in range(n):
        p, a, b = pts[i], pts[i - 1], pts[(i + 1) % n]
        la, lb = math.dist(p, a), math.dist(p, b)
        if r <= 0 or la < 1e-9 or lb < 1e-9:
            out.append(Node(*p))
            continue
        u1 = ((a[0] - p[0]) / la, (a[1] - p[1]) / la)
        u2 = ((b[0] - p[0]) / lb, (b[1] - p[1]) / lb)
        ang = math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1])))
        if ang < 1e-6 or ang > math.pi - 1e-6:
            out.append(Node(*p))  # lati allineati: niente spigolo
            continue
        t = r / math.tan(ang / 2)
        rr = r
        lim = min(la, lb) / 2
        if t > lim:
            t = lim
            rr = t * math.tan(ang / 2)
        A = (p[0] + u1[0] * t, p[1] + u1[1] * t)
        B = (p[0] + u2[0] * t, p[1] + u2[1] * t)
        h = 4.0 / 3.0 * math.tan((math.pi - ang) / 4) * rr  # maniglie di Bézier di un arco di cerchio
        out.append(Node(A[0], A[1], cout=(A[0] - u1[0] * h, A[1] - u1[1] * h)))
        out.append(Node(B[0], B[1], cin=(B[0] - u2[0] * h, B[1] - u2[1] * h)))
    return SubPath(out, True)


def fillet(sp, ni, r):
    """0.17.13: raccordo (arrotonda) lo spigolo nel nodo ni con un arco di raggio r (mm).
    Solo tra due tratti dritti. Ritorna "" se fatto, altrimenti il motivo (in chiaro)."""
    from ..i18n import tr

    n = len(sp.nodes)
    if r <= 0:
        return tr("Il raggio deve essere più grande di zero.")
    if not sp.closed and (ni == 0 or ni == n - 1):
        return tr("Il primo e l'ultimo nodo di un tracciato aperto non sono spigoli.")
    pi, nj = (ni - 1) % n, (ni + 1) % n
    if sp.is_curve(pi, ni) or sp.is_curve(ni, nj):
        return tr("Si possono arrotondare solo gli spigoli tra due tratti dritti.")
    p = sp.nodes[ni].pt()
    a, b = sp.nodes[pi].pt(), sp.nodes[nj].pt()
    la, lb = math.dist(p, a), math.dist(p, b)
    if la < 1e-9 or lb < 1e-9:
        return tr("Lo spigolo ha un lato di lunghezza zero.")
    u1 = ((a[0] - p[0]) / la, (a[1] - p[1]) / la)
    u2 = ((b[0] - p[0]) / lb, (b[1] - p[1]) / lb)
    cosang = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
    ang = math.acos(cosang)  # angolo interno dello spigolo
    if ang < 1e-3 or ang > math.pi - 1e-3:
        return tr("Qui non c'è uno spigolo da arrotondare (i due lati sono allineati).")
    t = r / math.tan(ang / 2)  # distanza dallo spigolo dei due punti di tangenza
    # lati condivisi con altri spigoli: al massimo metà, così due raccordi vicini non si sovrappongono
    lim = min(la if (not sp.closed and pi == 0) else la / 2, lb if (not sp.closed and nj == n - 1) else lb / 2)
    if t > lim:
        t = lim
        r = t * math.tan(ang / 2)
    A = (p[0] + u1[0] * t, p[1] + u1[1] * t)
    B = (p[0] + u2[0] * t, p[1] + u2[1] * t)
    turn = math.pi - ang  # di quanto gira la direzione lungo l'arco
    h = 4.0 / 3.0 * math.tan(turn / 4) * r  # lunghezza delle maniglie di Bézier per un arco di cerchio
    na = Node(A[0], A[1], cout=(A[0] - u1[0] * h, A[1] - u1[1] * h))
    nb = Node(B[0], B[1], cin=(B[0] - u2[0] * h, B[1] - u2[1] * h))
    sp.nodes[ni:ni + 1] = [na, nb]
    return ""
