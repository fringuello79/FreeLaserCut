# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Sculture 3D da tagliare al laser (senza interfaccia: si prova da sola).

Un modello 3D (.stl, .obj o uno dei modelli inclusi) diventa pezzi piatti di compensato o cartone:
- «a strati»: fette orizzontali dello spessore del materiale, da incollare una sull'altra; su ogni fetta si incide il
  contorno di quella sopra (dove appoggiarla) e il numero, che resta nascosto sotto la fetta successiva;
- «a incastro»: due serie di sagome verticali (lungo X e lungo Y) con le fessure, che si montano a griglia senza
  colla. Le sagome X hanno le fessure dall'alto, le Y dal basso: si mettono in piedi le X e si calano sopra le Y.

Tutte le misure in mm. Il modello si mette con la base a z = 0, centrato in x e y, alto quanto chiesto.
I pezzi sono poligoni (anelli chiusi: il primo è il contorno, gli altri i fori) nel piano della fetta, coordinate
(u, v): strati (x, y); sagome X (y, z); sagome Y (x, z).
"""
import math
import os
import struct
from dataclasses import dataclass, field

import numpy as np
import pyclipper

from freelasercut.i18n import tr  # noqa: E402

SCALE = 1000.0  # pyclipper lavora con interi: micrometri
MAX_TRIANGLES = 2_000_000
MAX_PIECES = 600


# ==================================================================== modello
@dataclass
class Mesh:
    vertices: np.ndarray  # (N, 3) float
    faces: np.ndarray     # (M, 3) int
    name: str = ""
    _cache: dict = field(default_factory=dict, repr=False, compare=False)  # triangoli già pronti per le sezioni

    def bounds(self):
        return self.vertices.min(0), self.vertices.max(0)

    def volume(self):
        """Volume (mm³) con il teorema della divergenza: giusto per i modelli chiusi."""
        P = self.vertices[self.faces]
        return float(abs(np.einsum("ij,ij->i", P[:, 0], np.cross(P[:, 1], P[:, 2])).sum()) / 6.0)

    def triangles(self):
        return self.vertices[self.faces]


def _clean(V, F, name=""):
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    if V.ndim != 2 or V.shape[1] != 3 or len(V) < 3 or F.ndim != 2 or F.shape[1] != 3 or len(F) < 1:
        raise ValueError(tr("Il file non contiene un modello 3D (servono almeno un triangolo)."))
    if len(F) > MAX_TRIANGLES:
        raise ValueError(tr("Il modello ha troppi triangoli ({0}): al massimo {1}.", len(F), MAX_TRIANGLES))
    if F.min() < 0 or F.max() >= len(V) or not np.isfinite(V).all():
        raise ValueError(tr("Il modello 3D è rovinato (vertici mancanti o non validi)."))
    # vertici uguali uniti (gli STL ripetono ogni vertice per ogni triangolo): le sezioni si chiudono bene
    span = float(np.ptp(V, axis=0).max()) or 1.0
    q = np.round(V / (span * 1e-7)).astype(np.int64)
    _u, idx, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    V, F = V[idx], inv.reshape(-1)[F]
    F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]  # triangoli schiacciati via
    if len(F) == 0:
        raise ValueError(tr("Il modello 3D è rovinato (vertici mancanti o non validi)."))
    used, F = np.unique(F, return_inverse=True)  # vertici non usati da nessun triangolo via: non cambiano le misure
    return Mesh(V[used], F.reshape(-1, 3), name)


def load_stl(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        head = data[:2048].lstrip().lower()
        text_like = head.startswith(b"solid") and b"facet" in head and b"vertex" in head
        # binario: misura giusta, o qualche byte in più alla fine (succede) se non sembra un STL di testo
        if n > 0 and (84 + 50 * n == len(data) or (84 + 50 * n < len(data) and not text_like)):
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                                count=n, offset=84)
            V = rec["v"].reshape(-1, 3).astype(np.float64)
            return _clean(V, np.arange(len(V)).reshape(-1, 3), os.path.basename(path))
    text = data.decode("latin-1", "replace")
    pts = []
    for line in text.splitlines():
        t = line.strip().split()
        if len(t) == 4 and t[0].lower() == "vertex":
            try:
                pts.append((float(t[1]), float(t[2]), float(t[3])))
            except ValueError:
                raise ValueError(tr("Il file STL è rovinato.")) from None
    if len(pts) < 3 or len(pts) % 3:
        raise ValueError(tr("Il file STL è rovinato."))
    V = np.array(pts)
    return _clean(V, np.arange(len(V)).reshape(-1, 3), os.path.basename(path))


def load_obj(path):
    V, F = [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            t = line.split()
            if not t:
                continue
            if t[0] == "v" and len(t) >= 4:
                try:
                    V.append((float(t[1]), float(t[2]), float(t[3])))
                except ValueError:
                    raise ValueError(tr("Il file OBJ è rovinato.")) from None
            elif t[0] == "f" and len(t) >= 4:
                idx = []
                for s in t[1:]:
                    try:
                        k = int(s.split("/")[0])
                    except ValueError:
                        raise ValueError(tr("Il file OBJ è rovinato.")) from None
                    idx.append(k - 1 if k > 0 else len(V) + k)  # indici negativi: dal fondo
                for a in range(1, len(idx) - 1):  # poligoni a ventaglio
                    F.append((idx[0], idx[a], idx[a + 1]))
    if not V or not F:
        raise ValueError(tr("Il file OBJ è rovinato."))
    return _clean(V, F, os.path.basename(path))


def load(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".stl":
        return load_stl(path)
    if ext == ".obj":
        return load_obj(path)
    raise ValueError(tr("Formato non supportato: servono file .stl o .obj."))


# ------------------------------------------------------------------ modelli inclusi (disegnati qui, nostri)
def _loft(rings):
    """Superficie chiusa da anelli con lo stesso numero di punti (in ordine), più i due tappi."""
    rings = [np.asarray(r, np.float64) for r in rings]
    n = len(rings[0])
    V = np.vstack(rings)
    F = []
    for k in range(len(rings) - 1):
        a, b = k * n, (k + 1) * n
        for i in range(n):
            j = (i + 1) % n
            F.append((a + i, b + i, b + j))
            F.append((a + i, b + j, a + j))
    caps = []
    for k in (0, len(rings) - 1):
        c = len(V)
        V = np.vstack([V, rings[k].mean(0)])
        caps.append([(c, k * n + i, k * n + (i + 1) % n) for i in range(n)])

    def signed(faces):
        P = V[np.asarray(faces)]
        return float(np.einsum("ij,ij->i", P[:, 0], np.cross(P[:, 1], P[:, 2])).sum())

    # tappi girati come i lati (così il modello è chiuso e coerente), poi tutto con le normali verso fuori
    best = None
    for f0 in (False, True):
        for f1 in (False, True):
            cand = F + [(a, c, b) if f0 else (a, b, c) for a, b, c in caps[0]] + \
                [(a, c, b) if f1 else (a, b, c) for a, b, c in caps[1]]
            vol = signed(cand)
            if best is None or abs(vol) > abs(best[0]):
                best = (vol, cand)
    F = np.array(best[1])
    if best[0] < 0:
        F = F[:, [0, 2, 1]]
    return V, F


def _puffy(outline_xz, depth, n_layers=24):
    """Forma «gonfia»: un contorno nel piano x-z spinto in y, sempre più piccolo verso i lati (come un cuscino)."""
    o = np.asarray(outline_xz, np.float64)
    c = o.mean(0)
    rings = []
    for t in np.linspace(-1.0, 1.0, n_layers):
        s = math.sqrt(max(0.0, 1.0 - t * t)) * 0.96 + 0.04
        q = c + (o - c) * s
        rings.append(np.column_stack([q[:, 0], np.full(len(q), t * depth / 2), q[:, 1]]))
    return _loft(rings)


def _heart2d(n=160):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    x = 16 * np.sin(t) ** 3
    z = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    return np.column_stack([x, z])[::-1]


def _star2d(points=5, r1=1.0, r2=0.45, n_per=12):
    out = []
    for k in range(points * 2):
        a0 = math.pi / 2 + k * math.pi / points
        a1 = math.pi / 2 + (k + 1) * math.pi / points
        ra, rb = (r1, r2) if k % 2 == 0 else (r2, r1)
        for s in np.linspace(0, 1, n_per, endpoint=False):
            a = a0 + (a1 - a0) * s
            r = ra + (rb - ra) * s
            out.append((r * math.cos(a), r * math.sin(a)))
    return np.array(out)


def builtin(name):
    """Modelli inclusi: disegnati qui con la matematica, nessun file di altri."""
    if name == "heart":
        V, F = _puffy(_heart2d() * 3.0, 40.0)
    elif name == "star":
        V, F = _puffy(_star2d() * 50.0, 30.0)
    elif name == "sphere":
        rings = []
        for t in -np.cos(np.linspace(0.03, math.pi - 0.03, 40)):  # fino quasi ai poli: alta quanto larga
            r = math.sqrt(max(0.0, 1 - t * t)) * 50
            a = np.linspace(0, 2 * np.pi, 64, endpoint=False)
            rings.append(np.column_stack([r * np.cos(a), r * np.sin(a), np.full(64, t * 50)]))
        V, F = _loft(rings)
    elif name == "vase":
        zs = np.linspace(0, 120, 48)
        prof = 22 + 14 * np.sin(zs / 120 * 2.6 * np.pi / 2 + 0.3) + 6 * np.exp(-((zs - 30) / 20) ** 2)
        a = np.linspace(0, 2 * np.pi, 64, endpoint=False)
        V, F = _loft([np.column_stack([r * np.cos(a), r * np.sin(a), np.full(64, z)]) for r, z in zip(prof, zs)])
    elif name == "torus":
        R, r = 40.0, 16.0
        n, m = 64, 32
        u = np.linspace(0, 2 * np.pi, n, endpoint=False)
        v = np.linspace(0, 2 * np.pi, m, endpoint=False)
        U, Vv = np.meshgrid(u, v, indexing="ij")
        P = np.stack([(R + r * np.cos(Vv)) * np.cos(U), (R + r * np.cos(Vv)) * np.sin(U), r * np.sin(Vv)], -1).reshape(-1, 3)
        F = []
        for i in range(n):
            for j in range(m):
                a, b = i * m + j, ((i + 1) % n) * m + j
                c, d = ((i + 1) % n) * m + (j + 1) % m, i * m + (j + 1) % m
                F += [(a, b, c), (a, c, d)]
        V, F = P, np.array(F)
    else:
        raise ValueError(tr("Modello sconosciuto: {0}", name))
    return _clean(V, F, BUILTINS[name])


BUILTINS = {"heart": tr("Cuore"), "star": tr("Stella"), "sphere": tr("Sfera"), "vase": tr("Vaso"),
            "torus": tr("Ciambella")}
UP_AXES = {"z": tr("Z (STL di solito)"), "y": tr("Y (OBJ di solito)"), "x": tr("X")}


def prepared(mesh, up="z", height=100.0):
    """Modello con l'asse scelto in verticale, base a z = 0, centrato, alto `height` mm."""
    V = mesh.vertices.copy()
    if up == "y":
        V = V[:, [0, 2, 1]] * np.array([1, -1, 1])  # y in su -> z in su (destrorso)
    elif up == "x":
        V = V[:, [1, 2, 0]]
    lo, hi = V.min(0), V.max(0)
    span = hi[2] - lo[2]
    if span <= 1e-9:
        raise ValueError(tr("Il modello è piatto in verticale: scegli un altro asse verticale."))
    k = height / span
    V = (V - np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])) * k
    return Mesh(V, mesh.faces.copy(), mesh.name)


# ==================================================================== sezioni
def _to_int(path):
    return [(int(round(x * SCALE)), int(round(y * SCALE))) for x, y in path]


def _from_int(path):
    return [(x / SCALE, y / SCALE) for x, y in path]


def _area(ring):
    return abs(pyclipper.Area(_to_int(ring))) / SCALE / SCALE


def _tri_index(mesh, axis):
    """Triangoli (una volta sola per modello) ordinati per la quota più bassa lungo `axis`: ogni sezione guarda
    solo quelli che possono toccare il piano (svelto anche con milioni di triangoli)."""
    c = mesh._cache
    if "P" not in c:
        P = mesh.vertices[mesh.faces]
        c["P"] = P
        c["N"] = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])  # verso fuori (triangoli in senso antiorario)
        c["span"] = float(np.ptp(mesh.vertices, axis=0).max()) or 1.0
    if axis not in c:
        lo = c["P"][:, :, axis].min(1)
        hi = c["P"][:, :, axis].max(1)
        order = np.argsort(lo, kind="stable")
        c[axis] = (order, lo[order], hi[order])
    return c[axis]


def section(mesh, axis, value, info=None):
    """Contorni della sezione del modello con il piano coord[axis] = value -> anelli 2D chiusi (coordinate del
    piano: le altre due, in ordine), girati in modo che il pieno stia sempre a sinistra (fori al contrario).
    info (dizionario): conta i bordi aperti richiusi ("gaps") e quelli persi ("lost")."""
    order, lo_s, hi_s = _tri_index(mesh, axis)
    span = mesh._cache["span"]
    v = value + span * 1.37e-7  # un soffio fuori dai vertici: niente casi di vertice sul piano
    k = int(np.searchsorted(lo_s, v))
    idx = order[:k][hi_s[:k] > v]
    if not len(idx):
        return []
    P = mesh._cache["P"][idx]
    N = mesh._cache["N"][idx]
    d = P[:, :, axis] - v
    s = d > 0
    cross = s.any(1) & ~s.all(1)
    P, d, s, N = P[cross], d[cross], s[cross], N[cross]
    if not len(P):
        return []
    keep = [k for k in range(3) if k != axis]
    segs = []
    for (i, j) in ((0, 1), (1, 2), (2, 0)):
        m = s[:, i] != s[:, j]
        t = d[:, i] / (d[:, i] - d[:, j] + 1e-300)
        pt = P[:, i] + (P[:, j] - P[:, i]) * t[:, None]
        segs.append((m, pt[:, keep]))
    # ogni triangolo attraversato ha esattamente due lati che passano il piano
    a = np.where(segs[0][0][:, None], segs[0][1], np.where(segs[1][0][:, None], segs[1][1], segs[2][1]))
    b = np.where(segs[2][0][:, None], segs[2][1], np.where(segs[1][0][:, None], segs[1][1], segs[0][1]))
    return _stitch(a, b, span, N[:, keep], info)


def _stitch(a, b, span, normals=None, info=None):
    """Segmenti (senza verso) -> anelli chiusi: gli estremi uguali si uniscono. Con le normali dei triangoli (nel
    piano) ogni anello viene girato con il pieno a sinistra: così due corpi che si sovrappongono (STL fatti di più
    parti) restano pieni anche dove si toccano. Bordi aperti (modelli non chiusi): i capi vicini si uniscono."""
    q = span * 1e-6
    ka = [tuple(x) for x in np.round(a / q).astype(np.int64)]
    kb = [tuple(x) for x in np.round(b / q).astype(np.int64)]
    adj, pos = {}, {}
    for i, (u, v) in enumerate(zip(ka, kb)):
        if u == v:
            continue
        adj.setdefault(u, []).append((v, i))
        adj.setdefault(v, []).append((u, i))
        pos.setdefault(u, a[i])
        pos.setdefault(v, b[i])
    used = set()
    loops, chains = [], []  # (punti, voto del verso)

    def vote(pts, seg_ids, closed):
        if normals is None:
            return 0.0
        p = np.asarray(pts)
        dv = (np.roll(p, -1, 0) - p) if closed else (p[1:] - p[:-1])
        n = normals[seg_ids]
        return float((dv[:, 0] * n[:, 1] - dv[:, 1] * n[:, 0]).sum())  # < 0: normale (fuori) a destra

    # prima dai capi delle catene aperte (pochi lati), così una catena non si spezza in due
    starts = [n for n, lst in adj.items() if len(lst) % 2] + list(adj)
    for start in starts:
        while True:
            first = next(((v, i) for v, i in adj[start] if i not in used), None)
            if first is None:
                break
            ring, seg_ids = [pos[start]], [first[1]]
            cur, (nxt_, i) = start, first
            used.add(i)
            closed = False
            while True:
                cur = nxt_
                if cur == start:
                    closed = True
                    break
                ring.append(pos[cur])
                step = next(((v, k) for v, k in adj[cur] if k not in used), None)
                if step is None:
                    break
                nxt_, k = step
                used.add(k)
                seg_ids.append(k)
            if closed:
                if len(ring) >= 3:
                    loops.append((np.array(ring), vote(ring, seg_ids, True)))
            elif len(ring) >= 2:
                chains.append((np.array(ring), vote(ring, seg_ids, False)))
    if chains:  # modello non chiuso: unisce i capi più vicini, poi chiude
        tol = max(span * 0.03, 0.5)
        gaps = lost = 0
        while chains:
            pts, vt = chains.pop()
            flipped = False
            while True:
                closing = math.dist(pts[-1], pts[0])
                best = None
                for j, (o, _ov) in enumerate(chains):
                    for rev in (False, True):
                        dd = math.dist(pts[-1], o[-1] if rev else o[0])
                        if best is None or dd < best[0]:
                            best = (dd, j, rev)
                if best is not None and best[0] <= tol and best[0] < closing:
                    o, ov = chains.pop(best[1])
                    pts = np.vstack([pts, o[::-1] if best[2] else o])
                    vt += -ov if best[2] else ov
                    gaps += 1
                    continue
                if closing <= tol or flipped:
                    break
                pts, vt, flipped = pts[::-1], -vt, True  # prova ad allungarla dall'altro capo
            if len(pts) >= 3 and math.dist(pts[-1], pts[0]) <= tol:
                loops.append((pts, vt))
                gaps += 1
            else:
                lost += 1
        if info is not None:
            info["gaps"] = info.get("gaps", 0) + gaps
            info["lost"] = info.get("lost", 0) + lost
    if normals is None:
        return [r for r, _v in loops]
    return [r[::-1] if v > 0 else r for r, v in loops]


@dataclass
class Island:
    """Un pezzo di una sezione: contorno e fori (anelli chiusi), coordinate del piano."""
    rings: list

    @property
    def outer(self):
        return self.rings[0]

    def area(self):
        return _area(self.rings[0]) - sum(_area(r) for r in self.rings[1:])


def islands(rings, min_area=1.0, oriented=True):
    """Anelli della sezione (girati con il pieno a sinistra: si sommano; oriented=False: pari-dispari) -> isole
    con i loro fori."""
    if not rings:
        return []
    pc = pyclipper.Pyclipper()
    for r in rings:
        if len(r) >= 3:
            try:
                pc.AddPath(_to_int(r), pyclipper.PT_SUBJECT, True)
            except pyclipper.ClipperException:
                continue
    try:
        fill = pyclipper.PFT_NONZERO if oriented else pyclipper.PFT_EVENODD
        tree = pc.Execute2(pyclipper.CT_UNION, fill, fill)
    except pyclipper.ClipperException:
        return []
    return _tree_islands(tree, min_area)


def _tree_islands(tree, min_area):
    out = []

    def walk(node):
        for ch in node.Childs:
            if not ch.IsHole:
                rings = [_from_int(ch.Contour)] + [_from_int(h.Contour) for h in ch.Childs]
                isl = Island([np.array(r) for r in rings])
                if isl.area() >= min_area:
                    out.append(isl)
                for h in ch.Childs:
                    walk(h)
    walk(tree)
    return out


def _difference(isl, rects, min_area):
    """Isola meno i rettangoli (fessure) -> isole risultanti."""
    pc = pyclipper.Pyclipper()
    try:
        pc.AddPaths([_to_int(r) for r in isl.rings], pyclipper.PT_SUBJECT, True)
        for r in rects:
            pc.AddPath(_to_int(r), pyclipper.PT_CLIP, True)
        tree = pc.Execute2(pyclipper.CT_DIFFERENCE, pyclipper.PFT_EVENODD, pyclipper.PFT_NONZERO)
    except pyclipper.ClipperException:
        return [isl]
    return _tree_islands(tree, min_area)


def _strip_spans(isl, at, half):
    """Tratti (v0, v1) occupati dall'isola nella striscia at - half <= u <= at + half: ogni parte connessa della
    striscia dà un tratto (dove passa l'altra sagoma conta tutto lo spessore, non solo la linea di mezzo)."""
    big = 1e5
    rect = [(at - half, -big), (at + half, -big), (at + half, big), (at - half, big)]
    pc = pyclipper.Pyclipper()
    try:
        pc.AddPaths([_to_int(r) for r in isl.rings], pyclipper.PT_SUBJECT, True)
        pc.AddPath(_to_int(rect), pyclipper.PT_CLIP, True)
        tree = pc.Execute2(pyclipper.CT_INTERSECTION, pyclipper.PFT_EVENODD, pyclipper.PFT_NONZERO)
    except pyclipper.ClipperException:
        return []
    spans = []

    def walk(node):
        for ch in node.Childs:
            if not ch.IsHole and len(ch.Contour) >= 3:
                vs = [p[1] / SCALE for p in ch.Contour]
                spans.append((min(vs), max(vs)))
            walk(ch)
    walk(tree)
    spans.sort()
    out = []
    for v0, v1 in spans:
        if out and v0 <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], v1))
        else:
            out.append((v0, v1))
    return out


def _intervals(isl, axis_u, at, extent=1e6):
    """Tratti (v0, v1) dell'isola lungo la retta u = at (axis_u: 0) o v = at (axis_u: 1)."""
    zs = []
    for r in isl.rings:
        a = np.asarray(r)
        b = np.roll(a, -1, axis=0)
        u0, u1 = a[:, axis_u], b[:, axis_u]
        m = (u0 > at) != (u1 > at)
        t = (at - u0[m]) / (u1[m] - u0[m])
        o = 1 - axis_u
        zs.extend(a[m, o] + (b[m, o] - a[m, o]) * t)
    zs = sorted(zs)
    return [(zs[k], zs[k + 1]) for k in range(0, len(zs) - 1, 2)]


# ==================================================================== pezzi
@dataclass
class Piece:
    name: str
    kind: str             # "layer" | "x" | "y"
    island: Island        # anelli nel piano (u, v)
    plane: float          # posizione del piano: z della base (strati) o x / y del centro (sagome)
    guides: list = field(default_factory=list)  # linee da incidere (anelli) nel piano del pezzo
    order: int = 0        # ordine di montaggio
    label: tuple = None   # (u, v, spazio libero in mm) dove scrivere il nome


@dataclass
class Sculpture:
    style: str
    thickness: float
    mesh: Mesh
    pieces: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def size(self):
        lo, hi = self.mesh.bounds()
        return hi - lo

    def area_mm2(self):
        return sum(p.island.area() for p in self.pieces)


def _letters(k):
    s = ""
    k += 1
    while k:
        k, r = divmod(k - 1, 26)
        s = chr(65 + r) + s
    return s


def layered(mesh, thickness=3.0, min_area=None):
    """Fette orizzontali: una ogni `thickness` mm, presa a metà dello strato."""
    t = float(thickness)
    if t < 0.5:
        raise ValueError(tr("Lo spessore del materiale deve essere almeno 0,5 mm."))
    lo, hi = mesh.bounds()
    n = max(1, int(round((hi[2] - lo[2]) / t)))
    if n > MAX_PIECES:
        raise ValueError(tr("Servirebbero {0} strati: al massimo {1}. Usa un materiale più spesso o una scultura "
                            "più bassa.", n, MAX_PIECES))
    min_area = min_area if min_area is not None else max(4.0, t * t)
    sc = Sculpture("layers", t, mesh)
    layers = []
    info = {}
    for i in range(n):
        z = lo[2] + (i + 0.5) * (hi[2] - lo[2]) / n
        layers.append(islands(section(mesh, 2, z, info), min_area))
    _open_warning(sc, info)
    order = 0
    for i, isls in enumerate(layers):
        isls = sorted(isls, key=lambda s: -s.area())
        above = layers[i + 1] if i + 1 < len(layers) else []
        for k, isl in enumerate(isls):
            name = f"{i + 1}" + (_letters(k) if len(isls) > 1 else "")
            guides = []
            for up in above:  # contorno della fetta sopra, solo la parte che sta su questa
                for r in _clip_rings(up.rings, isl.rings):
                    guides.append(r)
            pc = Piece(name, "layer", isl, lo[2] + i * t, guides, order)
            # il nome dove appoggia la fetta sopra: dopo l'incollaggio non si vede
            cover = _intersect(isl, above)
            spot = max((label_point(c) for c in cover), key=lambda q: q[1], default=None) if cover else None
            if spot is None or spot[1] < 1.5:
                spot = label_point(isl)
            pc.label = (spot[0][0], spot[0][1], spot[1])
            sc.pieces.append(pc)
            order += 1
    if not sc.pieces:
        raise ValueError(tr("Il modello non dà nessuna fetta: controlla l'asse verticale e le misure."))
    if len(sc.pieces) > MAX_PIECES:
        raise ValueError(tr("Troppi pezzi ({0}): al massimo {1}.", len(sc.pieces), MAX_PIECES))
    return sc


def _open_warning(sc, info):
    if info.get("lost"):
        sc.warnings.append(tr("Il modello ha dei buchi (non è chiuso): {0} contorni non si chiudono e sono stati "
                              "lasciati fuori. Controlla l'anteprima o ripara il modello.", info["lost"]))
    elif info.get("gaps"):
        sc.warnings.append(tr("Il modello ha dei piccoli buchi (non è chiuso): i contorni sono stati chiusi da soli. "
                              "Controlla l'anteprima."))


def _intersect(isl, others):
    """Parte dell'isola coperta dalle isole `others` -> isole."""
    if not others:
        return []
    pc = pyclipper.Pyclipper()
    pc.AddPaths([_to_int(r) for r in isl.rings], pyclipper.PT_SUBJECT, True)
    for o in others:
        pc.AddPaths([_to_int(r) for r in o.rings], pyclipper.PT_CLIP, True)
    try:
        tree = pc.Execute2(pyclipper.CT_INTERSECTION, pyclipper.PFT_EVENODD, pyclipper.PFT_EVENODD)
    except pyclipper.ClipperException:
        return []
    return _tree_islands(tree, 1.0)


def _clip_rings(rings, inside):
    """Contorni di `rings` (anelli chiusi) dentro la regione `inside` -> polilinee aperte da incidere."""
    pc = pyclipper.Pyclipper()
    for r in rings:
        p = _to_int(list(r) + [r[0]])
        pc.AddPath(p, pyclipper.PT_SUBJECT, False)
    pc.AddPaths([_to_int(r) for r in inside], pyclipper.PT_CLIP, True)
    try:
        tree = pc.Execute2(pyclipper.CT_INTERSECTION, pyclipper.PFT_NONZERO, pyclipper.PFT_EVENODD)
    except pyclipper.ClipperException:
        return []
    return [np.array(_from_int(p)) for p in pyclipper.OpenPathsFromPolyTree(tree) if len(p) >= 2]


def interlocking(mesh, thickness=3.0, nx=6, ny=6, slot_fit=0.0, min_area=None):
    """Sagome a incastro: nx sagome lungo X (piani x = costante) e ny lungo Y, con fessure larghe lo spessore più
    `slot_fit` (positivo = più larghe, per un incastro più morbido)."""
    t = float(thickness)
    if t < 0.5:
        raise ValueError(tr("Lo spessore del materiale deve essere almeno 0,5 mm."))
    nx, ny = int(nx), int(ny)
    if nx < 1 or ny < 1 or nx + ny > 120:
        raise ValueError(tr("Sagome per lato: da 1 a 60."))
    w = t + float(slot_fit)
    if w <= 0.1:
        raise ValueError(tr("Fessure troppo strette."))
    lo, hi = mesh.bounds()
    min_area = min_area if min_area is not None else max(9.0, 3 * t * t)
    xs = [lo[0] + (i + 0.5) * (hi[0] - lo[0]) / nx for i in range(nx)]
    ys = [lo[1] + (j + 0.5) * (hi[1] - lo[1]) / ny for j in range(ny)]
    if nx > 1 and (xs[1] - xs[0]) < 2.5 * t or ny > 1 and (ys[1] - ys[0]) < 2.5 * t:
        raise ValueError(tr("Sagome troppo vicine per questo spessore: diminuiscile o ingrandisci la scultura."))
    info = {}
    X = [(x, islands(section(mesh, 0, x, info), min_area)) for x in xs]  # (y, z)
    Y = [(y, islands(section(mesh, 1, y, info), min_area)) for y in ys]  # (x, z)
    slots_x = {(i, a): [] for i, (_x, isl) in enumerate(X) for a in range(len(isl))}
    slots_y = {(j, b): [] for j, (_y, isl) in enumerate(Y) for b in range(len(isl))}
    links_x = {k: 0 for k in slots_x}
    links_y = {k: 0 for k in slots_y}
    big = (hi[2] - lo[2]) + 10.0
    half = w / 2 + 0.05
    for i, (x, xis) in enumerate(X):
        for j, (y, yis) in enumerate(Y):
            for a, A in enumerate(xis):
                ia = _strip_spans(A, y, half)      # lungo z, dove passa la sagoma Y (tutto il suo spessore)
                if not ia:
                    continue
                for b, B in enumerate(yis):
                    ib = _strip_spans(B, x, half)  # lungo z, dove passa la sagoma X
                    for a0, a1 in ia:
                        for b0, b1 in ib:
                            o0, o1 = max(a0, b0), min(a1, b1)
                            if o1 - o0 <= 0.01:
                                continue
                            mid = (o0 + o1) / 2
                            # X: fessura dall'alto (da metà fino sopra la sagoma); Y: dal basso fino a metà. La Y
                            # scende dall'alto sulle X già messe: nel punto d'incrocio la X resta tutta sotto e la Y
                            # tutta sopra, anche dove si toccano appena (lì niente legno doppio).
                            slots_x[(i, a)].append(np.array([(y - w / 2, mid), (y + w / 2, mid),
                                                             (y + w / 2, a1 + big), (y - w / 2, a1 + big)]))
                            slots_y[(j, b)].append(np.array([(x - w / 2, b0 - big), (x + w / 2, b0 - big),
                                                             (x + w / 2, mid), (x - w / 2, mid)]))
                            if o1 - o0 >= 1.5 * t:  # appoggio abbastanza lungo: incastro vero
                                links_x[(i, a)] += 1
                                links_y[(j, b)] += 1
    sc = Sculpture("interlocking", t, mesh)
    _open_warning(sc, info)
    order = 0
    for prefix, series, slots, links in (("X", X, slots_x, links_x), ("Y", Y, slots_y, links_y)):
        for i, (c, isls) in enumerate(series):
            for a, isl in enumerate(isls):
                parts = _difference(isl, slots[(i, a)], min_area) if slots[(i, a)] else [isl]
                n_links = links[(i, a)]
                base = f"{prefix}{i + 1}" + (_letters(a) if len(isls) > 1 else "")
                if n_links == 0:
                    sc.warnings.append(tr("La sagoma {0} non si incastra con nessun'altra: è stata tolta.", base))
                    continue
                if len(parts) > 1:
                    sc.warnings.append(tr("La sagoma {0} con le fessure si divide in {1} parti: prova meno sagome o "
                                          "una scultura più grande.", base, len(parts)))
                for k, part in enumerate(sorted(parts, key=lambda s: -s.area())):
                    name = base + (f".{k + 1}" if len(parts) > 1 else "")
                    pc = Piece(name, prefix.lower(), part, c, [], order)
                    (lu, lv), room = label_point(part)
                    pc.label = (lu, lv, room)
                    sc.pieces.append(pc)
                    order += 1
    if not sc.pieces:
        raise ValueError(tr("Il modello non dà nessuna sagoma: controlla l'asse verticale e le misure."))
    if len(sc.pieces) > MAX_PIECES:
        raise ValueError(tr("Troppi pezzi ({0}): al massimo {1}.", len(sc.pieces), MAX_PIECES))
    return sc


def label_point(island, step=None):
    """Punto più lontano dai bordi dell'isola (per scriverci il numero) e la sua distanza dal bordo."""
    import cv2

    o = np.asarray(island.outer)
    lo, hi = o.min(0), o.max(0)
    span = float(max(hi - lo))
    step = step or max(0.25, span / 400.0)
    W = int((hi[0] - lo[0]) / step) + 3
    H = int((hi[1] - lo[1]) / step) + 3
    m = np.zeros((H, W), np.uint8)
    pts = [np.round((np.asarray(r) - lo) / step + 1).astype(np.int32) for r in island.rings]
    cv2.fillPoly(m, [pts[0]], 1)
    if len(pts) > 1:
        cv2.fillPoly(m, pts[1:], 0)
    d = cv2.distanceTransform(m, cv2.DIST_L2, 5)
    i, j = np.unravel_index(int(np.argmax(d)), d.shape)
    return (lo[0] + (j - 1) * step, lo[1] + (i - 1) * step), float(d[i, j]) * step


# ==================================================================== 3D per l'anteprima
def to_world(piece, u, v, w):
    """Coordinate del piano del pezzo (u, v) + spessore w -> mondo (x, y, z)."""
    if piece.kind == "layer":
        return np.stack([u, v, piece.plane + w], -1)
    if piece.kind == "x":
        return np.stack([piece.plane + w, u, v], -1)
    return np.stack([u, piece.plane + w, v], -1)


def piece_span(piece, t):
    """Spessore del pezzo nel suo asse: strati dalla base in su, sagome centrate sul piano."""
    return (0.0, t) if piece.kind == "layer" else (-t / 2, t / 2)


def auto_counts(mesh, thickness=3.0):
    """Quante sagome lungo X e lungo Y: circa una ogni 22 mm (mai più vicine di 3 spessori), da 1 a 12."""
    lo, hi = mesh.bounds()
    gap = max(22.0, 3.2 * thickness)
    return tuple(int(min(12, max(1, round((hi[k] - lo[k]) / gap)))) for k in (0, 1))
