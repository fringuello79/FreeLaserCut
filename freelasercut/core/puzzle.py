# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Generatore di puzzle (senza interfaccia: si prova da solo).

Una griglia di pezzi con le linee leggermente mosse; ogni lato interno ha un incastro (testa e collo) disegnato con
una curva liscia che passa per punti chiave, con piccole variazioni casuali: due puzzle con semi diversi non hanno
mai gli stessi pezzi. Misure in mm.

Dentro una forma (cuore, cerchio, qualsiasi contorno chiuso): i lati che uscirebbero dalla forma restano dritti, i
pezzi tagliati dal bordo troppo piccoli si uniscono al vicino. Risultato:
- cuts: tracciati da tagliare (il contorno e i lati interni, ognuno una volta sola)
- pieces: i pezzi come poligoni (per l'anteprima e i controlli)

Coordinate con Y in giù (come le righe di una foto): chi le mette sul piano le ribalta.
"""
import math
from dataclasses import dataclass, field

import numpy as np
import pyclipper

from freelasercut.i18n import tr  # noqa: E402

SCALE = 1000.0  # pyclipper lavora con interi: micrometri
COUNT_MIN, COUNT_MAX = 4, 1000
NECK_MIN_MM = 2.0  # sotto questo il collo dell'incastro si spezza facilmente nel compensato


@dataclass
class Puzzle:
    width: float
    height: float
    rows: int
    cols: int
    cuts: list = field(default_factory=list)      # [ [(x, y), ...], ... ] polilinee (aperte o chiuse)
    pieces: list = field(default_factory=list)    # [ [(x, y), ...], ... ] poligoni chiusi
    outline: list = field(default_factory=list)   # contorno esterno
    warnings: list = field(default_factory=list)
    neck_mm: float = 0.0                          # collo più stretto fra tutti gli incastri (mm)

    @property
    def piece_size(self):
        return min(self.width / self.cols, self.height / self.rows)


def grid_for(count, width, height):
    """Righe e colonne con pezzi il più possibile quadrati e un totale vicino a `count`."""
    best = None
    for rows in range(1, max(2, count) + 1):
        cols = max(1, round(count / rows))
        ratio = (width / cols) / (height / rows)
        score = abs(rows * cols - count) / count + abs(math.log(ratio)) * 0.6
        if best is None or score < best[0]:
            best = (score, rows, cols)
    return best[1], best[2]


def _catmull(points, n=10):
    """Curva liscia (Catmull-Rom centripeta) che passa per i punti."""
    P = np.asarray(points, float)
    P = np.vstack([P[0] * 2 - P[1], P, P[-1] * 2 - P[-2]])
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]

        def tj(ti, a, b):
            return ti + max(np.linalg.norm(b - a), 1e-9) ** 0.5
        t0 = 0.0
        t1 = tj(t0, p0, p1)
        t2 = tj(t1, p1, p2)
        t3 = tj(t2, p2, p3)
        for t in np.linspace(t1, t2, n, endpoint=False):
            a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
            a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
            b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
            out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    out.append(P[-2])
    return np.array(out)


def _tab_profile(rng, style=1.0, fit=1.0):
    """Lato con incastro da (0,0) a (1,0), testa verso +y. Punti chiave: spalla, collo, testa, collo, spalla.
    fit < 1: incastro più piccolo rispetto al lato (celle allungate: la testa non deve arrivare al lato opposto)."""
    c = 0.5 + rng.uniform(-0.05, 0.05)        # posizione della testa lungo il lato
    s = rng.uniform(0.92, 1.08) * style * fit  # grandezza della testa
    neck = 0.085 * s                           # metà larghezza del collo
    head = 0.14 * s                            # metà larghezza della testa
    tall = 0.25 * s                            # altezza della testa
    tilt = rng.uniform(-0.025, 0.025) * fit    # testa un po' storta, come i puzzle veri
    j = lambda a: rng.uniform(-a, a)
    keys = [(0.0, 0.0),
            (c - 0.25 * fit + j(0.02) * fit, j(0.012) * fit),
            (c - neck - 0.01 * fit, (0.025 + j(0.006)) * fit),
            (c - neck + tilt * 0.3, 0.10 * s),
            (c - head + tilt, 0.18 * s),
            (c + tilt, tall + j(0.01) * fit),
            (c + head + tilt, 0.18 * s),
            (c + neck + tilt * 0.3, 0.10 * s),
            (c + neck + 0.01 * fit, (0.025 + j(0.006)) * fit),
            (c + 0.25 * fit + j(0.02) * fit, j(0.012) * fit),
            (1.0, 0.0)]
    return _catmull(keys, 8), neck


def _place(profile, a, b, sign):
    """Porta il profilo unitario sul lato a→b; sign = ±1 sceglie da che parte sta la testa."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    L = np.linalg.norm(d)
    u = d / L
    n = np.array([-u[1], u[0]]) * sign
    return a + np.outer(profile[:, 0] * L, u) + np.outer(profile[:, 1] * L, n)


def _to_int(path):
    return [(int(round(x * SCALE)), int(round(y * SCALE))) for x, y in path]


def _from_int(path):
    return [(x / SCALE, y / SCALE) for x, y in path]


def _area(poly):
    return abs(pyclipper.Area(_to_int(poly))) / SCALE / SCALE


def generate(width, height, count=30, seed=1, shape=None, min_piece=8.0, tab_style=1.0, attempts=12):
    """width × height mm, circa `count` pezzi. shape: contorno chiuso [(x,y)...] dentro il rettangolo (o None).
    tab_style: grandezza degli incastri (0,85–1,15). Lo stesso seme dà sempre lo stesso puzzle.

    Dentro una forma, se un taglio passa troppo vicino al contorno un pezzo può restare attaccato all'altro solo per
    un filo: in quel caso si riprova con altre piccole variazioni (sempre le stesse per lo stesso seme)."""
    width, height = float(width), float(height)
    if not (width >= 5.0 and height >= 5.0):
        raise ValueError(tr("Il puzzle deve essere almeno 5 × 5 mm."))
    if shape is not None:
        shape = _clean_shape(shape, width, height)
    count = int(min(max(count, COUNT_MIN), COUNT_MAX))
    area = _area(shape) if shape is not None else width * height
    cap = max(COUNT_MIN, int(area / 9.0))  # pezzi di almeno 3 mm di lato
    capped = count > cap
    count = min(count, cap)
    if count > 300:  # tanti pezzi: ogni tentativo costa qualche secondo
        attempts = min(attempts, 4)
    best = None
    for k in range(max(1, attempts)):
        pz = _generate(width, height, count, seed * 7919 + k, shape, min_piece, tab_style)
        if capped:
            pz.warnings.append(tr("Al massimo {0} pezzi con queste misure (lato di almeno 3 mm).", cap))
        # il filo che conta è quello più sottile dei colli degli incastri (con pezzi minuscoli i colli stessi sono
        # sottili: lì la prova si adegua, altrimenti nessun tentativo andrebbe bene)
        thin = min(0.35, 0.3 * pz.neck_mm) if pz.neck_mm else 0.35
        bad = sum(1 for p in pz.pieces if not _solid([_to_int(p)], thin))
        if bad == 0:
            return pz
        if best is None or bad < best[0]:
            best = (bad, pz)
    best[1].warnings.append(tr("Un pezzo vicino al bordo della forma è unito al vicino da una parte molto sottile."))
    return best[1]


def _clean_shape(shape, width, height):
    """Contorno della forma come poligono semplice (un contorno che si incrocia, come una stella a cinque punte
    disegnata con una linea sola, diventa il suo bordo esterno). Forme troppo piccole o sottili: errore chiaro."""
    paths = pyclipper.SimplifyPolygon(_to_int(shape), pyclipper.PFT_NONZERO)
    paths = [p for p in paths if abs(pyclipper.Area(p)) > 0]
    if not paths:
        raise ValueError(tr("La forma è troppo piccola o troppo sottile per un puzzle."))
    best = _from_int(max(paths, key=lambda p: abs(pyclipper.Area(p))))
    if _area(best) < max(25.0, 0.02 * width * height):
        raise ValueError(tr("La forma è troppo piccola o troppo sottile per un puzzle."))
    return best


def _generate(width, height, count, seed, shape, min_piece, tab_style):
    rng = np.random.default_rng(seed)
    grid_count = count
    if shape is not None:  # la griglia copre il rettangolo: più celle, così dentro la forma i pezzi sono circa `count`
        grid_count = max(2, min(3 * COUNT_MAX, round(count * width * height / max(_area(shape), 1.0))))
    rows, cols = grid_for(grid_count, width, height)
    pz = Puzzle(width, height, rows, cols)
    cw, ch = width / cols, height / rows
    if min(cw, ch) < min_piece:
        pz.warnings.append(tr("Pezzi piccoli ({0:.1f} mm): nel legno meglio almeno {1:g} mm. Diminuisci i pezzi o "
                              "ingrandisci il puzzle.", min(cw, ch), min_piece))
    necks = []

    def tab(a, b, across):
        """across: larghezza della cella dalla parte della testa (celle allungate: incastro più piccolo)."""
        L = math.dist(a, b)
        prof, half = _tab_profile(rng, tab_style, min(1.0, 1.3 * across / max(L, 1e-9)))
        path = _place(prof, a, b, rng.choice((-1, 1)))
        return path, 2.0 * half * L
    # angoli della griglia, mossi un poco (quelli sul bordo restano sul bordo)
    X = np.tile(np.linspace(0, width, cols + 1), (rows + 1, 1))
    Y = np.tile(np.linspace(0, height, rows + 1)[:, None], (1, cols + 1))
    X[:, 1:-1] += rng.uniform(-0.09, 0.09, (rows + 1, cols - 1)) * cw
    Y[1:-1, :] += rng.uniform(-0.09, 0.09, (rows - 1, cols + 1)) * ch
    corner = lambda r, c: (X[r, c], Y[r, c])

    inner = None
    if shape is not None:
        pc = pyclipper.PyclipperOffset()
        pc.AddPath(_to_int(shape), pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        inner = pc.Execute(-0.08 * min(cw, ch) * SCALE)  # la testa dell'incastro deve stare tutta dentro la forma

    def inside_all(path):
        """La parte centrale del lato (collo e testa) è tutta dentro la forma? Gli estremi possono uscire."""
        if inner is None:
            return True
        n = len(path)
        ip = _to_int(path[n // 5: n - n // 5])
        return all(any(pyclipper.PointInPolygon(p, poly) == 1 for poly in inner) for p in ip[::2])

    # lati: orizzontali H[r][c] (fra angolo (r,c) e (r,c+1)), verticali V[r][c] (fra (r,c) e (r+1,c))
    H, V = {}, {}
    for r in range(rows + 1):
        for c in range(cols):
            a, b = corner(r, c), corner(r, c + 1)
            if shape is None and r in (0, rows):
                H[r, c] = np.array([a, b])
                continue
            path, nk = tab(a, b, ch)
            ok = inside_all(path)
            H[r, c] = path if ok else np.array([a, b])
            if ok:
                necks.append(nk)
    for r in range(rows):
        for c in range(cols + 1):
            a, b = corner(r, c), corner(r + 1, c)
            if shape is None and c in (0, cols):
                V[r, c] = np.array([a, b])
                continue
            path, nk = tab(a, b, cw)
            ok = inside_all(path)
            V[r, c] = path if ok else np.array([a, b])
            if ok:
                necks.append(nk)

    # pezzi: cella = sopra →, destra ↓, sotto ←, sinistra ↑
    cells = {}
    for r in range(rows):
        for c in range(cols):
            poly = np.vstack([H[r, c][:-1], V[r, c + 1][:-1], H[r + 1, c][::-1][:-1], V[r, c][::-1][:-1]])
            cells[r, c] = [_from_int(p) for p in _clip([poly.tolist()], shape)]
    nominal = cw * ch
    cell_area = {k: sum(_area(p) for p in v) for k, v in cells.items()}
    # nella forma: i pezzetti troppo piccoli si uniscono al vicino più grande (si toglie il lato in comune)
    removed = set()
    group = {k: {k} for k in cells}
    if shape is not None:
        def gsize(g):
            return sum(cell_area[k] for k in g)
        changed = True
        while changed:
            changed = False
            for k in sorted({min(g) for g in group.values() if gsize(g) > 0}, key=lambda k: gsize(group[k])):
                g = group[k]
                if gsize(g) >= 0.45 * nominal:
                    continue
                cand = set()
                for (r, c) in g:
                    for (dr, dc) in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        n = (r + dr, c + dc)
                        if n in cells and n not in g and gsize(group[n]) > 0:
                            cand.add(min(group[n]))
                best = None
                for n in sorted(cand, key=lambda n: -gsize(group[n])):
                    polys = [p for m in g | group[n] for p in cells[m]]
                    if _solid(_union(*polys)):  # mai due pezzi uniti solo per un angolo
                        best = n
                        break
                if best is None:
                    continue
                merged = g | group[best]
                for m in merged:
                    group[m] = merged
                # tolgo tutti i lati fra i due gruppi
                for (r, c) in g:
                    for (dr, dc, e) in ((-1, 0, ("H", r, c)), (1, 0, ("H", r + 1, c)), (0, -1, ("V", r, c)),
                                        (0, 1, ("V", r, c + 1))):
                        if (r + dr, c + dc) in group[best]:
                            removed.add(e)
                changed = True
                break
    # poligoni dei pezzi (unione delle celle del gruppo)
    seen = set()
    for k, g in group.items():
        gid = min(g)
        if gid in seen:
            continue
        seen.add(gid)
        polys = [p for m in g for p in cells[m]]
        if not polys:
            continue
        pc = pyclipper.Pyclipper()
        pc.AddPaths([_to_int(p) for p in polys], pyclipper.PT_SUBJECT, True)
        u = pc.Execute(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
        for p in u:
            if abs(pyclipper.Area(p)) / SCALE / SCALE > 0.5:
                pz.pieces.append(_from_int(p))
    # tagli: contorno + lati interni (non tolti), dentro la forma
    if shape is None:
        pz.outline = [(0, 0), (width, 0), (width, height), (0, height), (0, 0)]
    else:
        pz.outline = list(shape) + [shape[0]]
    pz.cuts.append(pz.outline)
    edges = [(("H", r, c), p) for (r, c), p in H.items() if shape is not None or r not in (0, rows)]
    edges += [(("V", r, c), p) for (r, c), p in V.items() if shape is not None or c not in (0, cols)]
    # i lati dritti (senza incastro) si tagliano solo dentro la forma ristretta di un soffio: quelli che corrono
    # sopra il contorno (forme con lati dritti sul bordo, come un quadrato o un esagono) non si tagliano due volte
    hair = _offset(shape, -0.02) if shape is not None else None
    for key, p in edges:
        if key in removed:
            continue
        straight = len(p) == 2
        for q in _clip_open(p.tolist(), shape, hair if straight else None):
            if len(q) >= 2 and sum(math.dist(q[m], q[m + 1]) for m in range(len(q) - 1)) > 0.2:
                pz.cuts.append(q)
    if shape is not None:
        _merge_fragments(pz, 0.4 * nominal)
    pz.neck_mm = min(necks) if necks else 0.0
    if necks and pz.neck_mm < NECK_MIN_MM:
        pz.warnings.append(tr("Il collo degli incastri più stretto è {0:.1f} mm: nel legno si può spezzare. Diminuisci "
                              "i pezzi o ingrandisci il puzzle.", pz.neck_mm))
    return pz


def _offset(poly, d):
    pc = pyclipper.PyclipperOffset()
    pc.AddPath(_to_int(poly), pyclipper.JT_MITER, pyclipper.ET_CLOSEDPOLYGON)
    return pc.Execute(d * SCALE)


def _union(*polys):
    pc = pyclipper.Pyclipper()
    for p in polys:
        pc.AddPath(_to_int(p), pyclipper.PT_SUBJECT, True)
    return [p for p in pc.Execute(pyclipper.CT_UNION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
            if abs(pyclipper.Area(p)) > 1]


def _solid(paths, width=0.35):
    """Un solo pezzo pieno: ristretto di `width` mm (circa la larghezza del taglio) resta intero: niente due metà
    unite da un filo."""
    if len(paths) != 1:
        return False
    pc = pyclipper.PyclipperOffset()
    pc.AddPaths(paths, pyclipper.JT_MITER, pyclipper.ET_CLOSEDPOLYGON)
    return len(pc.Execute(-width * SCALE)) == 1


def _merge_fragments(pz, min_area):
    """Pezzi rimasti troppo piccoli (es. il bordo della forma li spezza in due): si uniscono al vicino con cui hanno
    il lato in comune più lungo, e il taglio fra i due sparisce. L'unione deve restare un pezzo pieno: due parti
    unite solo da un filo nel legno si staccherebbero (o resterebbero attaccate per un punto)."""
    stuck = set()
    while True:
        areas = [_area(p) for p in pz.pieces]
        small = [i for i, a in enumerate(areas) if a < min_area and _key(pz.pieces[i]) not in stuck]
        if not small or len(pz.pieces) < 2:
            return
        i = min(small, key=lambda k: areas[k])
        grown = _offset(pz.pieces[i], 0.15)
        cands = []
        for k, q in enumerate(pz.pieces):
            if k == i:
                continue
            pc = pyclipper.Pyclipper()
            pc.AddPaths(grown, pyclipper.PT_SUBJECT, True)
            pc.AddPath(_to_int(q), pyclipper.PT_CLIP, True)
            inter = sum(abs(pyclipper.Area(p)) for p in pc.Execute(pyclipper.CT_INTERSECTION))
            if inter > 0:
                cands.append((inter, k))
        merged, best = None, None
        for inter, k in sorted(cands, reverse=True):
            u = _union(pz.pieces[i], pz.pieces[k])
            if _solid(u):
                merged, best = u[0], k
                break
        if merged is None:  # nessun vicino con cui formare un pezzo pieno: resta com'è
            stuck.add(_key(pz.pieces[i]))
            pz.warnings.append(tr("Un pezzo è rimasto più piccolo degli altri vicino al bordo della forma."))
            continue
        # il taglio in comune ora sta dentro il pezzo unito: lo tolgo (i bordi del pezzo restano)
        inside = _offset(_from_int(merged), -0.05)
        new_cuts = [pz.cuts[0]]
        for path in pz.cuts[1:]:
            pc = pyclipper.Pyclipper()
            pc.AddPath(_to_int(path), pyclipper.PT_SUBJECT, False)
            pc.AddPaths(inside, pyclipper.PT_CLIP, True)
            tree = pc.Execute2(pyclipper.CT_DIFFERENCE, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
            for q in pyclipper.OpenPathsFromPolyTree(tree):
                q = _from_int(q)
                if len(q) >= 2 and sum(math.dist(q[m], q[m + 1]) for m in range(len(q) - 1)) > 0.3:
                    new_cuts.append(q)
        pz.cuts = new_cuts
        pz.pieces = [p for k, p in enumerate(pz.pieces) if k not in (i, best)] + [_from_int(merged)]


def _key(poly):
    a = np.round(np.array(poly), 2)
    return (len(poly), float(a[:, 0].sum()), float(a[:, 1].sum()))


def _clip(polys, shape):
    if shape is None:
        return [_to_int(p) for p in polys]
    pc = pyclipper.Pyclipper()
    pc.AddPaths([_to_int(p) for p in polys], pyclipper.PT_SUBJECT, True)
    pc.AddPath(_to_int(shape), pyclipper.PT_CLIP, True)
    return pc.Execute(pyclipper.CT_INTERSECTION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)


def _clip_open(path, shape, clip_int=None):
    """La parte del tracciato aperto dentro la forma (o dentro clip_int, già in interi)."""
    if shape is None:
        return [path]
    pc = pyclipper.Pyclipper()
    pc.AddPath(_to_int(path), pyclipper.PT_SUBJECT, False)
    if clip_int is not None:
        pc.AddPaths(clip_int, pyclipper.PT_CLIP, True)
    else:
        pc.AddPath(_to_int(shape), pyclipper.PT_CLIP, True)
    tree = pc.Execute2(pyclipper.CT_INTERSECTION, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)
    return [_from_int(p) for p in pyclipper.OpenPathsFromPolyTree(tree)]


def heart(w, h, n=240):
    """Cuore (curva classica), adattato al rettangolo w × h."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    x = 16 * np.sin(t) ** 3
    y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
    x = (x - x.min()) / (x.max() - x.min()) * w
    y = (y - y.min()) / (y.max() - y.min()) * h
    return list(zip(x, y))


def ellipse(w, h, n=180):
    """Ovale (o cerchio, se w = h) che riempie il rettangolo w × h."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return list(zip(w / 2 + w / 2 * np.cos(t), h / 2 + h / 2 * np.sin(t)))


SHAPES = {"rect": tr("Rettangolo"), "heart": tr("Cuore"), "circle": tr("Cerchio"), "oval": tr("Ovale"),
          "selected": tr("La forma selezionata")}


def outline_for(kind, w, h):
    """Contorno della forma scelta nel rettangolo w × h (None = rettangolo)."""
    if kind == "heart":
        return heart(w, h)
    if kind == "circle":
        d = min(w, h)
        return [(x + (w - d) / 2, y + (h - d) / 2) for x, y in ellipse(d, d)]
    if kind == "oval":
        return ellipse(w, h)
    return None
