# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""File Gerber (RS-274X, anche X2) e fori Excellon: i disegni dei circuiti stampati. (0.18.3)

Scritto da zero sul formato pubblico, senza librerie esterne oltre a Clipper (già usato dal programma).
Nessuna dipendenza da Qt: qui si lavora solo con numeri.

Unità e sistemi di riferimento (un solo punto di conversione: `_Reader._mm` e `_Drill._num`):
- nel file le coordinate sono interi con le cifre decimali dichiarate da %FS…% e l'unità da %MO…% (mm o pollici);
  qui dentro tutto diventa **millimetri veri**, asse Y verso l'alto come sul piano di FreeLaserCut;
- per i calcoli con Clipper i millimetri diventano interi a 0,1 µm (SCALE), come in core/geom.py;
- le curve diventano poligoni con una freccia massima di TOL mm.

Un file Gerber è una sequenza di oggetti «scuri» (aggiungono rame) o «chiari» (lo tolgono da quello disegnato
prima): l'immagine finale si ottiene applicandoli **nell'ordine del file**. Ogni oggetto viene portato al verso
positivo prima di unirlo agli altri, così due oggetti sovrapposti non si annullano mai.

`load(path)` legge un file; `build(files, opts)` mette insieme i file di una basetta (stessa origine per tutti)
e applica le scelte: specchio, negativo (spazio fra le piste), bordo, fori.
"""
import math
import os
import re

import pyclipper

from freelasercut.i18n import tr

SCALE = 10000.0  # interi di Clipper: 0,1 µm
TOL = 0.005  # mm: freccia massima fra arco e poligono
MAX_MM = 3000.0  # oltre queste misure il file è stato letto male (formato dei numeri sbagliato)
MIN_AREA = 1e-5  # mm²: briciole dei calcoli, invisibili al laser
JOIN_TOL = 0.01  # mm: due estremi del contorno della basetta più vicini di così sono lo stesso punto

ROLES = ("copper", "profile", "other", "drill")
GERBER_EXT = (".gbr", ".ger", ".gtl", ".gbl", ".gto", ".gbo", ".gts", ".gbs", ".gtp", ".gbp", ".gko", ".gm1", ".gml",
              ".g1", ".g2", ".g3", ".g4", ".gl1", ".gl2", ".gl3", ".gl4", ".gp1", ".gp2", ".cmp", ".sol", ".stc", ".sts",
              ".plc", ".pls", ".crc", ".crs", ".pho", ".art", ".top", ".bot", ".smt", ".smb", ".sst", ".ssb", ".spt",
              ".spb", ".oln", ".out")
DRILL_EXT = (".drl", ".xln", ".exc", ".drd", ".tap", ".ncd")

_NZ = pyclipper.PFT_NONZERO
_EO = pyclipper.PFT_EVENODD


class GerberError(ValueError):
    pass


# ============================================================================ geometria di base (mm, numeri veri)
def _steps(r, sweep=2 * math.pi, tol=TOL):
    """In quanti tratti dividere un arco di raggio r perché la freccia resti sotto tol."""
    if r <= tol:
        return max(4, int(math.ceil(abs(sweep) / (math.pi / 2))))
    da = 2 * math.acos(max(-1.0, 1.0 - tol / r))
    return max(1, int(math.ceil(abs(sweep) / da)))


def circle(cx, cy, d, tol=TOL):
    r = d / 2.0
    n = max(12, _steps(r, tol=tol))
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def rect(cx, cy, w, h):
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]


def obround(cx, cy, w, h, tol=TOL):
    if abs(w - h) < 1e-9:
        return circle(cx, cy, w, tol)
    r = min(w, h) / 2.0
    n = max(6, _steps(r, math.pi, tol))
    pts = []
    if w > h:
        k = (w - h) / 2.0
        pts += [(cx + k + r * math.cos(-math.pi / 2 + math.pi * i / n), cy + r * math.sin(-math.pi / 2 + math.pi * i / n))
                for i in range(n + 1)]
        pts += [(cx - k + r * math.cos(math.pi / 2 + math.pi * i / n), cy + r * math.sin(math.pi / 2 + math.pi * i / n))
                for i in range(n + 1)]
    else:
        k = (h - w) / 2.0
        pts += [(cx + r * math.cos(math.pi * i / n), cy + k + r * math.sin(math.pi * i / n)) for i in range(n + 1)]
        pts += [(cx + r * math.cos(math.pi + math.pi * i / n), cy - k + r * math.sin(math.pi + math.pi * i / n))
                for i in range(n + 1)]
    return pts


def regular(cx, cy, d, n, rot=0.0):
    n = max(3, int(round(n)))
    a0 = math.radians(rot)
    return [(cx + d / 2 * math.cos(a0 + 2 * math.pi * i / n), cy + d / 2 * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)]


def rotate(pts, deg):
    if not deg:
        return list(pts)
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(x * c - y * s, x * s + y * c) for x, y in pts]


def arc_points(s, e, c, cw, full_if_closed=True, tol=TOL):
    """Punti dell'arco da s a e attorno a c (s compreso, e compreso). Con s = e è il cerchio intero."""
    r = math.hypot(s[0] - c[0], s[1] - c[1])
    a0 = math.atan2(s[1] - c[1], s[0] - c[0])
    a1 = math.atan2(e[1] - c[1], e[0] - c[0])
    same = math.hypot(s[0] - e[0], s[1] - e[1]) < 1e-9
    if same:
        sweep = (2 * math.pi if full_if_closed else 0.0) * (-1 if cw else 1)
    elif cw:
        sweep = -((a0 - a1) % (2 * math.pi))
    else:
        sweep = (a1 - a0) % (2 * math.pi)
    if sweep == 0.0:
        return [s, e]
    n = max(2, _steps(r, sweep, tol))
    pts = [s]
    for i in range(1, n):
        a = a0 + sweep * i / n
        pts.append((c[0] + r * math.cos(a), c[1] + r * math.sin(a)))
    pts.append(e)
    return pts


# ============================================================================ Clipper (interi)
def _ip(pts):
    out = []
    last = None
    for x, y in pts:
        q = (int(round(x * SCALE)), int(round(y * SCALE)))
        if q != last:
            out.append(q)
            last = q
    return out


def _fp(path):
    return [(x / SCALE, y / SCALE) for x, y in path]


def _clip(op, subj, clip=(), fs=_NZ, fc=_NZ, tree=False):
    pc = pyclipper.Pyclipper()
    subj = [p for p in subj if len(p) >= 3]
    clip = [p for p in clip if len(p) >= 3]
    try:
        if not subj:
            raise pyclipper.ClipperException("vuoto")
        pc.AddPaths(subj, pyclipper.PT_SUBJECT, True)
    except pyclipper.ClipperException:
        return None if tree else []
    if clip:
        try:
            pc.AddPaths(clip, pyclipper.PT_CLIP, True)
        except pyclipper.ClipperException:
            pass
    return pc.Execute2(op, fs, fc) if tree else pc.Execute(op, fs, fc)


def union(paths, fill=_NZ):
    return _clip(pyclipper.CT_UNION, paths, (), fill, fill)


def difference(a, b, fa=_NZ, fb=_NZ):
    if not b:
        return union(a, fa)
    return _clip(pyclipper.CT_DIFFERENCE, a, b, fa, fb)


def intersection(a, b, fa=_NZ, fb=_NZ):
    if not a or not b:
        return []
    return _clip(pyclipper.CT_INTERSECTION, a, b, fa, fb)


def _positive(pts):
    """Un contorno semplice e convesso/primitivo, girato nel verso positivo."""
    p = _ip(pts)
    if len(p) >= 3 and not pyclipper.Orientation(p):
        p.reverse()
    return p


def _stroke(polylines, width):
    """Tratti con punta tonda di diametro width (interi) -> area."""
    co = pyclipper.PyclipperOffset(2.0, TOL * SCALE)
    n = 0
    for pl in polylines:
        if len(pl) >= 2:
            try:
                co.AddPath(pl, pyclipper.JT_ROUND, pyclipper.ET_OPENROUND)
                n += 1
            except pyclipper.ClipperException:
                pass
    return co.Execute(width / 2.0) if n else []


def _hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def area_mm2(paths):
    """Area (mm²) di un insieme di contorni già ordinati (esterni positivi, fori negativi)."""
    return sum(pyclipper.Area(p) for p in paths) / (SCALE * SCALE)


def bounds(paths):
    xs = [x for p in paths for x, _ in p]
    ys = [y for p in paths for _, y in p]
    if not xs:
        return None
    return min(xs) / SCALE, min(ys) / SCALE, max(xs) / SCALE, max(ys) / SCALE


def _islands(paths, fill=_NZ):
    """Contorni -> isole in mm: [[esterno, foro, foro…], …]; un'isola dentro un foro è un'isola a parte."""
    tree = _clip(pyclipper.CT_UNION, paths, (), fill, fill, tree=True)
    out = []
    if tree is None:
        return out

    def walk(node):
        for ch in node.Childs:
            if not ch.IsHole:
                isl = [ch.Contour] + [h.Contour for h in ch.Childs if h.IsHole]
                if abs(sum(pyclipper.Area(c) for c in isl)) / (SCALE * SCALE) >= MIN_AREA:
                    out.append([_fp(c) for c in isl])
                for h in ch.Childs:
                    walk(h)
            else:  # non dovrebbe capitare al primo livello
                walk(ch)

    walk(tree)
    return out


def _move(paths, dx, dy):
    return [[(x + dx, y + dy) for x, y in p] for p in paths]


def _transform(paths, mirror="N", rot=0.0, scale=1.0):
    """Specchio, poi rotazione, poi scala (l'ordine del formato Gerber) attorno all'origine dell'apertura."""
    if mirror == "N" and not rot and scale == 1.0:
        return paths
    sx = -1 if "X" in mirror else 1
    sy = -1 if "Y" in mirror else 1
    a = math.radians(rot)
    c, s = math.cos(a), math.sin(a)
    out = []
    for p in paths:
        q = []
        for x, y in p:
            x, y = x * sx, y * sy
            q.append((int(round((x * c - y * s) * scale)), int(round((x * s + y * c) * scale))))
        if sx * sy < 0:
            q.reverse()  # lo specchio su un asse solo cambia il verso: lo rimetto com'era
        out.append(q)
    return out


# ============================================================================ macro delle aperture
_TOK = re.compile(r"\s*(?:(\d*\.\d+|\d+\.?)|(\$\d+)|([+\-xX/()]))")


def _expr(text, var):
    """Espressione di una macro: numeri, $n, + - x /, parentesi. Niente eval."""
    toks = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _TOK.match(text, pos)
        if not m:
            raise GerberError(tr("macro di un'apertura non leggibile: {0}", text[:40]))
        toks.append(m.group(1) or m.group(2) or m.group(3))
        pos = m.end()
    i = 0

    def atom():
        nonlocal i
        if i >= len(toks):
            raise GerberError(tr("macro di un'apertura non leggibile: {0}", text[:40]))
        t = toks[i]
        i += 1
        if t == "(":
            v = add()
            if i < len(toks) and toks[i] == ")":
                i += 1
            return v
        if t == "-":
            return -atom()
        if t == "+":
            return atom()
        if t.startswith("$"):
            return float(var.get(int(t[1:]), 0.0))
        return float(t)

    def mul():
        nonlocal i
        v = atom()
        while i < len(toks) and toks[i] in "xX/":
            op = toks[i]
            i += 1
            w = atom()
            v = v * w if op in "xX" else (v / w if w else 0.0)
        return v

    def add():
        nonlocal i
        v = mul()
        while i < len(toks) and toks[i] in "+-":
            op = toks[i]
            i += 1
            w = mul()
            v = v + w if op == "+" else v - w
        return v

    return add() if toks else 0.0


def _macro_paths(blocks, params, u, warn):
    """Forma di un'apertura a macro: contorni interi, ordinati. u = mm per unità del file."""
    var = {i + 1: p for i, p in enumerate(params)}
    img = []
    for blk in blocks:
        blk = blk.strip()
        if not blk or re.match(r"0(?![\d.])", blk):  # primitiva 0 = commento
            continue
        m = re.match(r"\$(\d+)\s*=(.*)$", blk)
        if m:
            var[int(m.group(1))] = _expr(m.group(2), var)
            continue
        f = [_expr(t, var) for t in blk.split(",")]
        code = int(round(f[0]))
        f = f[1:]

        def g(k, default=0.0):
            return f[k] if k < len(f) else default

        shapes, exposure = [], 1
        if code == 1:  # cerchio
            exposure = g(0)
            shapes = [rotate(circle(g(2) * u, g(3) * u, g(1) * u), g(4))]
        elif code in (2, 20):  # linea da punto a punto, estremi squadrati
            exposure = g(0)
            w, sx, sy, ex, ey = g(1) * u, g(2) * u, g(3) * u, g(4) * u, g(5) * u
            ln = math.hypot(ex - sx, ey - sy)
            if ln > 0 and w > 0:
                nx, ny = -(ey - sy) / ln * w / 2, (ex - sx) / ln * w / 2
                shapes = [rotate([(sx + nx, sy + ny), (sx - nx, sy - ny), (ex - nx, ey - ny), (ex + nx, ey + ny)], g(6))]
        elif code == 21:  # rettangolo dal centro
            exposure = g(0)
            shapes = [rotate(rect(g(3) * u, g(4) * u, g(1) * u, g(2) * u), g(5))]
        elif code == 22:  # rettangolo dall'angolo in basso a sinistra (vecchio)
            exposure = g(0)
            w, h = g(1) * u, g(2) * u
            shapes = [rotate(rect(g(3) * u + w / 2, g(4) * u + h / 2, w, h), g(5))]
        elif code == 4:  # contorno libero
            exposure = g(0)
            n = int(round(g(1)))
            pts = [(g(2 + 2 * k) * u, g(3 + 2 * k) * u) for k in range(n + 1)]
            shapes = [rotate(pts, g(2 + 2 * (n + 1)))]
        elif code == 5:  # poligono regolare
            exposure = g(0)
            shapes = [rotate(regular(g(2) * u, g(3) * u, g(4) * u, g(1)), g(5))]
        elif code == 7:  # scarico termico: anello tagliato da una croce
            cx, cy, do, di, gap, rot = g(0) * u, g(1) * u, g(2) * u, g(3) * u, g(4) * u, g(5)
            ring = difference([_positive(circle(cx, cy, do))], [_positive(circle(cx, cy, di))]) if di < do else []
            cross = [_positive(rect(cx, cy, do * 1.1, gap)), _positive(rect(cx, cy, gap, do * 1.1))] if gap > 0 else []
            th = difference(ring, cross) if cross else ring
            th = [_ip(rotate(_fp(p), rot)) for p in th] if rot else th
            img = union(img + th)
            continue
        elif code == 6:  # mirino (vecchio): anelli e croce
            cx, cy, do, thick, gap, nmax, cth, clen, rot = (g(0) * u, g(1) * u, g(2) * u, g(3) * u, g(4) * u, int(g(5)),
                                                            g(6) * u, g(7) * u, g(8))
            parts = []
            d, k = do, 0
            while d > 0 and k < max(0, nmax) and thick > 0:
                inner = d - 2 * thick
                parts += difference([_positive(circle(cx, cy, d))], [_positive(circle(cx, cy, inner))] if inner > 0 else [])
                d = inner - 2 * gap
                k += 1
            if cth > 0 and clen > 0:
                parts += [_positive(rect(cx, cy, clen, cth)), _positive(rect(cx, cy, cth, clen))]
            parts = union(parts)
            parts = [_ip(rotate(_fp(p), rot)) for p in parts] if rot else parts
            img = union(img + parts)
            continue
        else:
            warn(tr("macro: primitiva {0} non riconosciuta, ignorata", code))
            continue
        solid = union([_ip(s) for s in shapes if len(s) >= 3])
        if not solid:
            continue
        img = union(img + solid) if int(round(exposure)) != 0 else difference(img, solid)
    return img


# ============================================================================ lettore Gerber
class _Aperture:
    __slots__ = ("kind", "paths", "d", "convex", "block")

    def __init__(self, kind, paths=None, d=0.0, convex=False, block=None):
        self.kind, self.paths, self.d, self.convex, self.block = kind, paths or [], d, convex, block


_WORD = re.compile(r"([GDMXYIJN])([+-]?[\d.]+)")


class _Reader:
    def __init__(self, text):
        self.text = text
        self.warnings = []
        self.attrs = {}
        self.u = None  # mm per unità del file
        self.fmt = None  # (interi X, decimali X, interi Y, decimali Y)
        self.zero = "L"
        self.ap = {}
        self.macros = {}
        self.cur = None
        self.x = self.y = 0.0
        self.interp = 1
        self.quad = None  # None = non dichiarato, "S" = un quadrante, "M" = più quadranti
        self.dark = True
        self.lm, self.lr, self.ls = "N", 0.0, 1.0
        self.region = False
        self.contour = []
        self.last_op = None
        self.ops = []  # ("poly", scuro, contorni) | ("stroke", scuro, diametro intero, polilinea intera)
        self.stack = []  # blocchi aperti (ripetizioni SR, aperture a blocco AB)
        self.zero_width = 0
        self.flashes = []  # centri delle piazzole (mm): servono a riconoscere il formato dei fori
        self.done = False

    # ---------------------------------------------------------------- avvisi e numeri
    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def unit(self):
        if self.u is None:
            self.u = 25.4
            self.warn(tr("il file non dichiara l'unità di misura: letto in pollici"))
        return self.u

    def _mm(self, s, axis):
        """Il solo punto che converte una coordinata del file in millimetri."""
        u = self.unit()
        if "." in s:
            return float(s) * u
        if self.fmt is None:
            raise GerberError(tr("il file non dichiara il formato dei numeri (%FS…%): non è un Gerber RS-274X"))
        ni, nd = (self.fmt[0], self.fmt[1]) if axis == "x" else (self.fmt[2], self.fmt[3])
        neg = s.startswith("-")
        digits = s.lstrip("+-")
        if self.zero == "T":  # zeri finali omessi: si completano a destra
            digits = digits.ljust(ni + nd, "0")
        v = int(digits or "0") / (10 ** nd)
        return (-v if neg else v) * u

    # ---------------------------------------------------------------- oggetti
    def emit(self, op):
        (self.stack[-1]["ops"] if self.stack else self.ops).append(op)

    def _ap(self):
        a = self.ap.get(self.cur)
        if a is None:
            raise GerberError(tr("il file usa un'apertura non definita (D{0})", self.cur))
        return a

    def flash(self, x, y):
        a = self._ap()
        self.flashes.append((x, y))
        dx, dy = int(round(x * SCALE)), int(round(y * SCALE))
        if a.kind == "B":
            for op in a.block:
                dark = op[1] if self.dark else not op[1]
                if op[0] == "poly":
                    self.emit(("poly", dark, _move(_transform(op[2], self.lm, self.lr, self.ls), dx, dy)))
                else:
                    pl = _move(_transform([op[3]], self.lm, self.lr, self.ls), dx, dy)[0]
                    self.emit(("stroke", dark, int(round(op[2] * self.ls)), pl))
            return
        if not a.paths:
            self.zero_width += 1
            return
        self.emit(("poly", self.dark, _move(_transform(a.paths, self.lm, self.lr, self.ls), dx, dy)))

    def draw(self, pts):
        """Tratto lungo la polilinea pts (mm) con l'apertura attuale."""
        a = self._ap()
        pl = _ip(pts)
        if a.kind == "C":
            w = int(round(a.d * self.ls * SCALE))
            self.emit(("stroke", self.dark, w, pl if len(pl) >= 2 else pl + pl))
            if w <= 0:
                self.zero_width += 1
            return
        if a.kind == "X":
            return
        if a.kind == "B" or not a.paths:
            self.warn(tr("tratti disegnati con un'apertura non adatta: ignorati"))
            return
        shape = _transform(a.paths, self.lm, self.lr, self.ls)
        if a.convex and len(shape) == 1:
            if len(pl) < 2:
                self.emit(("poly", self.dark, _move(shape, pl[0][0], pl[0][1])))
            for (x0, y0), (x1, y1) in zip(pl, pl[1:]):
                self.emit(("poly", self.dark, [_hull([(x + x0, y + y0) for x, y in shape[0]] + [(x + x1, y + y1) for x, y in shape[0]])]))
        else:
            self.warn(tr("tratti disegnati con un'apertura dalla forma complessa: resi solo agli estremi"))
            for x0, y0 in (pl[0], pl[-1]):
                self.emit(("poly", self.dark, _move(shape, x0, y0)))
        self.emit(("stroke", self.dark, 0, pl if len(pl) >= 2 else pl + pl))  # solo l'asse, per i contorni

    def close_contour(self):
        c = self.contour
        self.contour = []
        if len(c) >= 3:
            solid = union([_ip(c)])
            if solid:
                self.emit(("poly", self.dark, solid))

    # ---------------------------------------------------------------- archi
    def arc(self, s, e, i, j, cw):
        if self.quad == "M" or (self.quad is None and (i < 0 or j < 0)):
            return arc_points(s, e, (s[0] + i, s[1] + j), cw, True)
        best = None
        for si in (1, -1):
            for sj in (1, -1):
                c = (s[0] + si * abs(i), s[1] + sj * abs(j))
                r0 = math.hypot(s[0] - c[0], s[1] - c[1])
                r1 = math.hypot(e[0] - c[0], e[1] - c[1])
                a0 = math.atan2(s[1] - c[1], s[0] - c[0])
                a1 = math.atan2(e[1] - c[1], e[0] - c[0])
                sweep = ((a0 - a1) if cw else (a1 - a0)) % (2 * math.pi)
                if sweep <= math.pi / 2 + 1e-6:
                    err = abs(r0 - r1)
                    if best is None or err < best[0]:
                        best = (err, c)
        if best is None:
            if self.quad is None:
                return arc_points(s, e, (s[0] + i, s[1] + j), cw, True)
            self.warn(tr("un arco non è coerente con i suoi dati: reso come linea"))
            return [s, e]
        return arc_points(s, e, best[1], cw, False)

    # ---------------------------------------------------------------- comandi fra % %
    def extended(self, blocks):
        head = blocks[0]
        code = head[:2]
        if code == "FS":
            m = re.search(r"([LTD])?([AI])?.*?X(\d)(\d)Y(\d)(\d)", head[2:])
            if not m:
                raise GerberError(tr("formato dei numeri non leggibile: {0}", head))
            self.zero = "T" if m.group(1) == "T" else "L"
            if m.group(2) == "I":
                raise GerberError(tr("coordinate incrementali: formato vecchio non supportato"))
            self.fmt = tuple(int(m.group(k)) for k in (3, 4, 5, 6))
        elif code == "MO":
            self.u = 25.4 if "IN" in head else 1.0
        elif code == "AD":
            self.define(head)
        elif code == "AM":
            self.macros[head[2:].strip()] = blocks[1:]
        elif code == "LP":
            self.dark = not head[2:].startswith("C")
        elif code == "LM":
            self.lm = head[2:].strip().upper() or "N"
        elif code == "LR":
            self.lr = float(head[2:] or 0)
        elif code == "LS":
            self.ls = float(head[2:] or 1) or 1.0
        elif code == "SR":
            self.step_repeat(head)
        elif code == "AB":
            self.block(head)
        elif code in ("TF", "TA", "TO", "TD"):
            self.attribute(head)
        elif code == "IP":
            if "NEG" in head:
                self.warn(tr("il file chiede l'immagine in negativo (IPNEG): usa l'opzione della finestra"))
        elif code in ("MI", "SF", "OF", "AS", "IR"):
            vals = [float(v) for v in re.findall(r"[AB]([+-]?[\d.]+)", head)]
            neutral = 1.0 if code == "SF" else 0.0
            odd = any(abs(v - neutral) > 1e-9 for v in vals) if code != "AS" else "AYBX" in head
            if code == "IR":
                odd = bool(re.search(r"[1-9]", head))
            if odd:
                self.warn(tr("comando vecchio {0} non applicato: controlla misure e orientamento", head))
        elif code == "IF":
            self.warn(tr("il file ne richiama un altro ({0}): non viene letto", head[2:]))
        # IN, LN e il resto: senza effetto sul disegno

    def attribute(self, s):
        m = re.match(r"T[FAOD]\.?(\.?[A-Za-z_]\w*)?,?(.*)$", s)
        if s.startswith("TF") and m and m.group(1):
            self.attrs[m.group(1).lstrip(".")] = m.group(2)

    def define(self, head):
        m = re.match(r"ADD0*(\d+)\s*([^,]+?)\s*(?:,(.*))?$", head)  # i nomi delle macro possono avere spazi (file vecchi)
        if not m:
            raise GerberError(tr("definizione di un'apertura non leggibile: {0}", head[:40]))
        code, name = int(m.group(1)), m.group(2)
        u = self.unit()
        try:
            p = [float(v) for v in re.split(r"[xX]", m.group(3)) if v.strip()] if m.group(3) else []
        except ValueError:  # file rovinato: il resto si legge lo stesso, ma si dice chiaramente cosa manca
            self.warn(tr("apertura D{0} non leggibile ({1}): gli oggetti disegnati con lei MANCANO", code, head[:40]))
            self.ap[code] = _Aperture("X")
            return

        def hole(k, limit):
            if len(p) > k + 1 and p[k] > 0 and p[k + 1] > 0:  # foro rettangolare (vecchio)
                h = rect(0, 0, p[k] * u, p[k + 1] * u)
            elif len(p) > k and p[k] > 0:
                if p[k] * u >= limit:
                    self.warn(tr("un'apertura ha il foro più grande di lei: foro ignorato"))
                    return []
                h = circle(0, 0, p[k] * u)
            else:
                return []
            q = _positive(h)
            q.reverse()
            return [q]

        if name == "C" and p:
            d = p[0] * u
            self.ap[code] = _Aperture("C", ([_positive(circle(0, 0, d))] + hole(1, d)) if d > 0 else [], d, True)
        elif name in ("R", "O") and len(p) == 1 and name not in self.macros:  # un lato solo (file vecchi): quadrato o cerchio
            d = p[0] * u
            self.ap[code] = _Aperture(name, [_positive(rect(0, 0, d, d) if name == "R" else circle(0, 0, d))] if d > 0 else [],
                                      convex=True)
        elif name == "R" and len(p) >= 2:
            w, h = p[0] * u, p[1] * u
            self.ap[code] = _Aperture("R", ([_positive(rect(0, 0, w, h))] + hole(2, min(w, h))) if w > 0 and h > 0 else [],
                                      convex=len(p) < 3)
        elif name == "O" and len(p) >= 2:
            w, h = p[0] * u, p[1] * u
            self.ap[code] = _Aperture("O", ([_positive(obround(0, 0, w, h))] + hole(2, min(w, h))) if w > 0 and h > 0 else [],
                                      convex=len(p) < 3)
        elif name == "P" and len(p) >= 2:
            d = p[0] * u
            self.ap[code] = _Aperture("P", ([_positive(regular(0, 0, d, p[1], p[2] if len(p) > 2 else 0.0))]
                                            + hole(3, d * math.cos(math.pi / max(3, int(p[1]))))) if d > 0 else [],
                                      convex=len(p) < 4)
        elif name in self.macros:
            self.ap[code] = _Aperture("M", _macro_paths(self.macros[name], p, u, self.warn))
        else:
            raise GerberError(tr("apertura di tipo sconosciuto: {0}", name))

    def step_repeat(self, head):
        if self.stack and self.stack[-1]["kind"] == "SR":
            self.close_block()
        m = re.match(r"SR(?:X(\d+))?(?:Y(\d+))?(?:I([\d.]+))?(?:J([\d.]+))?$", head)
        if not m or head == "SR":
            return
        nx, ny = int(m.group(1) or 1), int(m.group(2) or 1)
        u = self.unit()
        if nx * ny > 1:
            self.stack.append({"kind": "SR", "ops": [], "nx": nx, "ny": ny, "dx": float(m.group(3) or 0) * u,
                               "dy": float(m.group(4) or 0) * u})

    def block(self, head):
        m = re.match(r"ABD0*(\d+)$", head)
        if m:
            self.stack.append({"kind": "AB", "ops": [], "code": int(m.group(1))})
        elif self.stack and self.stack[-1]["kind"] == "AB":
            self.close_block()

    def close_block(self):
        b = self.stack.pop()
        if b["kind"] == "AB":
            self.ap[b["code"]] = _Aperture("B", block=b["ops"])
            return
        for ix in range(b["nx"]):  # ordine del formato: prima lungo Y, poi lungo X (conta con gli oggetti chiari)
            for iy in range(b["ny"]):
                dx, dy = int(round(ix * b["dx"] * SCALE)), int(round(iy * b["dy"] * SCALE))
                for op in b["ops"]:
                    if op[0] == "poly":
                        self.emit(("poly", op[1], _move(op[2], dx, dy)))
                    else:
                        self.emit(("stroke", op[1], op[2], _move([op[3]], dx, dy)[0]))

    # ---------------------------------------------------------------- comandi normali
    def word(self, w):
        w = w.strip()
        if not w or self.done:
            return
        if w.startswith("G04") or w.startswith("G4 ") or w.startswith("G4#"):
            m = re.match(r"G0?4\s*#@!\s*(T[FAOD].*)$", w)  # attributi scritti come commento (KiCad, formato X1)
            if m:
                self.attribute(m.group(1).strip())
            return
        x = y = None
        i = j = 0.0
        d = None
        for letter, val in _WORD.findall(w):
            if letter == "G":
                g = int(float(val))
                if g in (1, 2, 3):
                    self.interp = g
                elif g == 36:
                    self.region, self.contour = True, []
                elif g == 37:
                    self.close_contour()
                    self.region = False
                elif g == 74:
                    self.quad = "S"
                elif g == 75:
                    self.quad = "M"
                elif g == 70:
                    self.u = 25.4
                elif g == 71:
                    self.u = 1.0
                elif g == 91:
                    raise GerberError(tr("coordinate incrementali: formato vecchio non supportato"))
            elif letter == "X":
                x = self._mm(val, "x")
            elif letter == "Y":
                y = self._mm(val, "y")
            elif letter == "I":
                i = self._mm(val, "x")
            elif letter == "J":
                j = self._mm(val, "y")
            elif letter == "D":
                d = int(float(val))
            elif letter == "M":
                if int(float(val)) in (0, 2):
                    if self.region:
                        self.close_contour()
                    self.done = True
                    return
        if d is not None and d >= 10:
            if d not in self.ap:
                raise GerberError(tr("il file usa un'apertura non definita (D{0})", d))
            self.cur = d
            return
        if d is None:
            if x is None and y is None:
                return
            d = self.last_op
            if d is None:
                return
        nx = self.x if x is None else x
        ny = self.y if y is None else y
        if d == 1:
            s, e = (self.x, self.y), (nx, ny)
            pts = [s, e] if self.interp == 1 else self.arc(s, e, i, j, self.interp == 2)
            if self.region:
                if not self.contour:
                    self.contour = [s]
                self.contour += pts[1:]
            else:
                if self.cur is None:
                    raise GerberError(tr("il file disegna senza aver scelto un'apertura"))
                self.draw(pts)
        elif d == 2:
            if self.region:
                self.close_contour()
        elif d == 3:
            if self.cur is None:
                raise GerberError(tr("il file disegna senza aver scelto un'apertura"))
            self.flash(nx, ny)
        self.x, self.y = nx, ny
        self.last_op = d

    # ---------------------------------------------------------------- lettura
    def run(self):
        # il testo fra due % è un comando «esteso» (anche più d'uno, vecchio stile); il resto sono comandi chiusi da *
        for k, part in enumerate(self.text.split("%")):
            if self.done:
                break
            part = part.replace("\n", "").replace("\r", "")
            if k % 2:
                blocks = [b.strip() for b in part.split("*") if b.strip()]
                if blocks and blocks[0].startswith("AM"):
                    self.extended(blocks)
                else:
                    for b in blocks:
                        self.extended([b])
            else:
                for w in part.split("*"):
                    self.word(w)
        if self.region:
            self.close_contour()
        while self.stack:
            self.close_block()
        if not self.done:
            self.warn(tr("il file non ha il comando di fine (M02): potrebbe essere incompleto"))


def render(ops):
    """Applica gli oggetti nell'ordine del file. Ritorna i contorni ordinati dell'immagine (interi)."""
    image = []
    polys, strokes = [], {}
    state = {"dark": None}

    def flush():
        nonlocal image, polys, strokes
        if not polys and not strokes:
            return
        batch = list(polys)
        for w, pls in strokes.items():
            batch += _stroke(pls, w)
        polys, strokes = [], {}
        if not batch:
            return
        if state["dark"]:
            image = union(image + batch)
        elif image:
            image = difference(image, union(batch))

    for op in ops:
        if op[1] != state["dark"]:
            flush()
            state["dark"] = op[1]
        if op[0] == "poly":
            polys += op[2]
        elif op[2] > 0:
            strokes.setdefault(op[2], []).append(op[3])
    flush()
    return image


def chain(polylines, tol=JOIN_TOL):
    """Unisce i tratti che si toccano agli estremi. Ritorna [(punti in mm, chiuso)]."""
    k = 1.0 / tol

    def key(p):
        return (int(round(p[0] * k)), int(round(p[1] * k)))

    segs = [list(p) for p in polylines if len(p) >= 2 and (len(p) > 2 or key(p[0]) != key(p[-1]))]
    ends = {}
    for idx, s in enumerate(segs):
        ends.setdefault(key(s[0]), []).append(idx)
        ends.setdefault(key(s[-1]), []).append(idx)
    used = [False] * len(segs)
    out = []

    def take(pt, me):
        cx, cy = key(pt)
        for ax in (0, -1, 1):
            for ay in (0, -1, 1):
                for j in ends.get((cx + ax, cy + ay), ()):
                    if not used[j] and j != me:
                        return j
        return None

    for idx, s in enumerate(segs):
        if used[idx]:
            continue
        used[idx] = True
        cur = list(s)
        for _ in range(2):  # prima in avanti, poi dall'altro capo
            while True:
                if len(cur) > 2 and math.dist(cur[0], cur[-1]) <= tol * 1.5:
                    break
                j = take(cur[-1], idx)
                if j is None:
                    break
                used[j] = True
                nxt = segs[j]
                if math.dist(nxt[-1], cur[-1]) < math.dist(nxt[0], cur[-1]):
                    nxt = nxt[::-1]
                cur += nxt[1:]
            cur.reverse()
        closed = len(cur) > 3 and math.dist(cur[0], cur[-1]) <= tol * 1.5
        if closed:
            cur = cur[:-1]
        out.append((cur, closed))
    return out


# ============================================================================ a cosa serve un file
_NAME_RULES = (
    (r"edge[._ ]?cuts|board[._ ]?outline|outline|profile|dimension|keep[._ -]?out|\.gko$|\.gm\d*$|\.gml$|\.oln$|\.out$",
     "profile", None),
    (r"f[._]cu\b|top[._ -]?(layer|copper)|copper[._ -]?top|front[._ -]?copper|\.gtl$|\.cmp$|\.top$|\.gl1$|\.g1$", "copper", "top"),
    (r"b[._]cu\b|bot(tom)?[._ -]?(layer|copper)|copper[._ -]?bot|back[._ -]?copper|\.gbl$|\.sol$|\.bot$", "copper", "bottom"),
    (r"in\d+[._]cu\b|inner|\.g[2-9]$|\.gl[2-9]$|\.gp\d$", "copper", "inner"),
    (r"f[._](silks?|mask|paste)|top[._ -]?(silk|overlay|solder|paste|mask)|\.gto$|\.gts$|\.gtp$|\.plc$|\.stc$|\.crc$|\.smt$|\.sst$|\.spt$",
     "other", "top"),
    (r"b[._](silks?|mask|paste)|bot(tom)?[._ -]?(silk|overlay|solder|paste|mask)|\.gbo$|\.gbs$|\.gbp$|\.pls$|\.sts$|\.crs$|\.smb$|\.ssb$|\.spb$",
     "other", "bottom"),
)


def guess_role(name, attrs):
    """(ruolo, lato) dagli attributi X2 del file, altrimenti dal nome. lato: "top" | "bottom" | "inner" | None."""
    ff = (attrs.get("FileFunction") or "").lower()
    if ff:
        parts = [p.strip() for p in ff.split(",")]
        side = "top" if "top" in parts else "bottom" if "bot" in parts else "inner" if "inr" in parts else None
        if parts[0] == "copper":
            return "copper", side
        if parts[0] == "profile":
            return "profile", None
        return "other", side
    low = name.lower()
    for rx, role, side in _NAME_RULES:
        if re.search(rx, low):
            return role, side
    return "other", None


# ============================================================================ fori Excellon
class _Drill:
    def __init__(self, text, dec=None):
        self.text = text
        self.u = None
        self.dec = dec  # cifre decimali quando i numeri non hanno il punto
        self.zero = "T"  # "T": zeri in testa omessi (numero normale); "L": zeri in coda omessi
        self.explicit = dec is not None
        self.implied = False  # il file contiene numeri senza punto decimale
        self.tools = {}
        self.holes = []  # (x, y, diametro) in mm
        self.slots = []  # (polilinea in mm, diametro)
        self.warnings = []

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def _num(self, s):
        """Il solo punto che converte una coordinata dei fori in millimetri."""
        if self.u is None:
            self.u = 25.4
            self.warn(tr("il file dei fori non dichiara l'unità di misura: letto in pollici"))
        if "." in s:
            return float(s) * self.u
        self.implied = True
        dec = self.dec if self.dec is not None else (4 if self.u == 25.4 else 3)
        neg = s.startswith("-")
        digits = s.lstrip("+-")
        if self.zero == "L":
            total = (2 if self.u == 25.4 else 3) + dec
            digits = digits.ljust(total, "0")
        v = int(digits or "0") / (10 ** dec)
        return (-v if neg else v) * self.u

    def run(self):
        x = y = 0.0
        tool = None
        down = None  # fresatura: None = il file non lo dice (si fresa), True dopo M15, False dopo M16/M17
        header = False
        for raw in self.text.replace("\r", "\n").split("\n"):
            line = raw.strip()
            if not line:
                continue
            up = line.upper()
            if up.startswith(";"):
                m = re.search(r"FILE_FORMAT\s*=\s*(\d)\s*:\s*(\d)", up)
                if m and not self.explicit:
                    self.dec, self.explicit = int(m.group(2)), True
                if "FORMAT" in up and "DECIMAL" in up and "SUPPRESS" not in up:
                    pass
                continue
            if up == "M48":
                header = True
                continue
            if up in ("%", "M95"):
                header = False
                continue
            if up.startswith(("METRIC", "INCH", "M71", "M72")):
                self.u = 1.0 if up.startswith(("METRIC", "M71")) else 25.4
                if ",LZ" in up:
                    self.zero = "L"
                elif ",TZ" in up:
                    self.zero = "T"
                m = re.search(r",(0+)\.(0+)", up)
                if m and not self.explicit:
                    self.dec, self.explicit = len(m.group(2)), True
                continue
            if up.startswith("ICI") and "ON" in up or up == "G91":
                raise GerberError(tr("file dei fori con coordinate incrementali: non supportato"))
            if up in ("M30", "M00"):
                break
            m = re.match(r"T0*(\d+)(?:[FSBHZ][\d.+-]*)*C([\d.]+)", up)
            if m:
                if self.u is None:
                    self.u = 25.4
                    self.warn(tr("il file dei fori non dichiara l'unità di misura: letto in pollici"))
                self.tools[int(m.group(1))] = float(m.group(2)) * self.u
                if not header:
                    tool = int(m.group(1))
                continue
            m = re.match(r"T0*(\d+)$", up)
            if m:
                tool = int(m.group(1))
                if tool and tool not in self.tools:
                    self.warn(tr("il file dei fori usa una punta senza diametro (T{0}): fori ignorati", tool))
                continue
            if header:
                continue
            if up in ("M15", "M16", "M17"):
                down = up == "M15"
                continue
            if up == "G05":
                down = None
                continue
            if "X" not in up and "Y" not in up:
                continue
            d = self.tools.get(tool)
            rep = re.match(r"R(\d+)", up)
            if "G85" in up:  # asola: X..Y..G85X..Y..
                a, b = up.split("G85", 1)
                x0, y0 = self._xy(a, x, y)
                x, y = self._xy(b, x0, y0)
                if d:
                    self.slots.append(([(x0, y0), (x, y)], d))
                continue
            g = re.match(r"G0?([0123])(?!\d)", up)
            if g:
                rest = up[g.end():]
                nx, ny = self._xy(rest, x, y)
                if g.group(1) in "123" and down is not False and d:
                    pts = [(x, y), (nx, ny)]
                    if g.group(1) != "1":
                        pts = self._arc((x, y), (nx, ny), rest, g.group(1) == "2")
                    self.slots.append((pts, d))
                x, y = nx, ny
                continue
            if rep:
                dx, dy = self._xy(up[rep.end():], 0.0, 0.0)
                for _ in range(int(rep.group(1))):
                    x, y = x + dx, y + dy
                    if d:
                        self.holes.append((x, y, d))
                continue
            x, y = self._xy(up, x, y)
            if d and not down:
                self.holes.append((x, y, d))
        return self

    def _arc(self, s, e, rest, cw):
        """Fresatura ad arco: centro da I/J (rispetto all'inizio) oppure dal raggio A (l'arco più corto)."""
        ij = dict(re.findall(r"([IJA])([+-]?[\d.]+)", rest))
        if "I" in ij or "J" in ij:
            c = (s[0] + (self._num(ij["I"]) if "I" in ij else 0.0), s[1] + (self._num(ij["J"]) if "J" in ij else 0.0))
        elif "A" in ij:
            r = self._num(ij["A"])
            ch = math.dist(s, e)
            if ch < 1e-9 or r < ch / 2:
                return [s, e]
            h = math.sqrt(max(0.0, r * r - ch * ch / 4))
            mx, my = (s[0] + e[0]) / 2, (s[1] + e[1]) / 2
            ux, uy = (e[0] - s[0]) / ch, (e[1] - s[1]) / ch
            k = 1 if cw else -1  # centro a destra del verso di marcia per l'orario
            c = (mx + k * uy * h, my - k * ux * h)
        else:
            return [s, e]
        return arc_points(s, e, c, cw, False)

    def _xy(self, s, x, y):
        for letter, val in re.findall(r"([XY])([+-]?[\d.]+)", s):
            if letter == "X":
                x = self._num(val)
            else:
                y = self._num(val)
        return x, y

    def bounds(self):
        xs = [h[0] for h in self.holes] + [p[0] for s in self.slots for p in s[0]]
        ys = [h[1] for h in self.holes] + [p[1] for s in self.slots for p in s[0]]
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None


# ============================================================================ un file letto
class GerberFile:
    """Un file della basetta, già letto. role: copper | profile | other | drill."""

    def __init__(self, path, kind):
        self.path = path
        self.name = os.path.basename(path)
        self.kind = kind  # "gerber" | "excellon"
        self.role = "other"
        self.side = None
        self.image = []  # contorni interi ordinati (solo Gerber)
        self.lines = []  # assi dei tratti uniti: [(punti mm, chiuso)]
        self.drill = None
        self.flashes = set()  # centri delle piazzole, arrotondati a 0,01 mm
        self.warnings = []
        self._text = ""

    def line_bounds(self):
        """Ingombro degli assi dei tratti (per il contorno: senza lo spessore della linea)."""
        pts = [p for ln, _ in self.lines for p in ln]
        return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)) if pts else None

    def bounds(self):
        """Ingombro in mm di quello che il file contiene (None se è vuoto)."""
        if self.kind == "excellon":
            b = self.drill.bounds()
            if b is None:
                return None
            r = max([h[2] for h in self.drill.holes] + [s[1] for s in self.drill.slots]) / 2
            return b[0] - r, b[1] - r, b[2] + r, b[3] + r
        b = bounds(self.image)
        pts = [p for ln, _ in self.lines for p in ln]
        if pts and (b is None or self.role == "profile"):
            lb = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
            b = lb if b is None else (min(b[0], lb[0]), min(b[1], lb[1]), max(b[2], lb[2]), max(b[3], lb[3]))
        return b


def _read_text(path, limit=None):
    with open(path, "rb") as fh:
        raw = fh.read() if limit is None else fh.read(limit)
    if b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace") if raw[:3] != b"\xef\xbb\xbf" else raw[3:].decode("utf-8", errors="replace")


def sniff_text(text):
    """"gerber" | "excellon" | None guardando il contenuto."""
    if not text:
        return None
    head = text[:200000]
    if re.search(r"%FS[LTD]?[AI]?.*?X\d\dY\d\d", head) or re.search(r"%ADD\d+", head):
        return "gerber"
    if re.search(r"^\s*M48\s*$", head, re.M) or (re.search(r"^\s*T\d+(?:[FS][\d.]+)*C[\d.]+", head, re.M)
                                                    and re.search(r"^\s*X[+-]?[\d.]+Y[+-]?[\d.]+\s*$", head, re.M)):
        return "excellon"
    return None


def sniff(path):
    """Guarda solo l'inizio del file (un file enorme di un altro tipo non viene letto tutto)."""
    try:
        return sniff_text(_read_text(path, 262144))
    except OSError:
        return None


def load(path):
    """Legge un file Gerber o Excellon. Solleva GerberError con un messaggio per l'utente."""
    text = _read_text(path)
    kind = sniff_text(text)
    if kind is None:
        if text and re.search(r"D0?[123]\*", text) and re.search(r"[XY]\d+", text):
            raise GerberError(tr("Gerber vecchio (RS-274-D) senza l'elenco delle aperture: esportalo di nuovo come RS-274X"))
        raise GerberError(tr("non è un file Gerber o Excellon"))
    f = GerberFile(path, kind)
    f._text = text
    if kind == "excellon":
        f.role = "drill"
        f.drill = _Drill(text).run()
        f.warnings = list(f.drill.warnings)
        if not f.drill.holes and not f.drill.slots:
            raise GerberError(tr("il file dei fori non contiene fori"))
    else:
        r = _Reader(text)
        r.run()
        f.image = render(r.ops)
        f.lines = chain([_fp(op[3]) for op in r.ops if op[0] == "stroke"])
        f.flashes = {(int(round(x * 100)), int(round(y * 100))) for x, y in r.flashes}
        f.role, f.side = guess_role(f.name, r.attrs)
        f.warnings = list(r.warnings)
        if not f.image and not f.lines:
            raise GerberError(tr("il file non contiene nessun disegno"))
    b = f.bounds() if kind == "gerber" else None
    if b is not None and (max(abs(v) for v in b) > 2 * MAX_MM or b[2] - b[0] > MAX_MM or b[3] - b[1] > MAX_MM):
        raise GerberError(tr("misure non credibili ({0:.0f} × {1:.0f} mm): il formato dei numeri del file non è giusto",
                             b[2] - b[0], b[3] - b[1]))
    return f


# ============================================================================ la basetta
class Options:
    """Scelte dell'importazione. None = decide `defaults` guardando i file."""

    def __init__(self, mirror=None, negative=None, margin=1.0, holes="true", dot=0.5, roles=None):
        self.mirror = mirror
        self.negative = negative
        self.margin = margin  # mm oltre il disegno, quando manca il contorno della basetta
        self.holes = holes  # "true" diametro vero | "dot" punto di centratura | "none"
        self.dot = dot  # mm
        self.roles = dict(roles or {})  # percorso -> ruolo scelto a mano


def role_of(f, opts):
    if f.kind == "excellon":
        return "drill"
    r = (opts.roles or {}).get(f.path, f.role)
    return r if r in ("copper", "profile", "other") else f.role


def defaults(files, opts=None):
    """Completa le scelte lasciate a None. Specchio: solo se c'è un lato sotto e nessun lato sopra.
    Negativo (si incide lo spazio fra le piste): se c'è almeno un file di rame."""
    o = Options() if opts is None else Options(opts.mirror, opts.negative, opts.margin, opts.holes, opts.dot, opts.roles)
    sides = {f.side for f in files if f.kind == "gerber"}
    if o.mirror is None:
        o.mirror = "bottom" in sides and "top" not in sides
    if o.negative is None:
        o.negative = any(role_of(f, o) == "copper" for f in files)
    o.margin = min(50.0, max(0.0, float(o.margin)))
    o.dot = min(5.0, max(0.05, float(o.dot)))
    if o.holes not in ("true", "dot", "none"):
        o.holes = "true"
    return o


class Layer:
    """Un pezzo del risultato: kind "area" (isole: [[esterno, fori…]…]) o "line" ([(punti, chiuso)…]), in mm."""

    def __init__(self, role, name, kind, data, area=0.0, side=None):
        self.role, self.name, self.kind, self.data, self.area = role, name, kind, data, area
        self.side = side  # solo nelle basette a due facce: "top" | "bottom"


class Board:
    def __init__(self):
        self.layers = []
        self.warnings = []
        self.bounds = None  # ingombro in mm di quello che viene importato (lo specchio non lo cambia)
        self.mirrored = False
        self.negative = False
        self.frame = None  # "profile" | "box" | None: da dove viene il bordo del negativo
        self.copper_area = 0.0
        self.frame_area = 0.0
        self.two_sided = False  # rame del lato sopra e del lato sotto insieme: due lavori, uno per faccia

    def side_layers(self, side=None):
        """I pezzi di una faccia ("top" | "bottom"); con una faccia sola, tutti."""
        return [ly for ly in self.layers if not self.two_sided or ly.side == side]

    @property
    def size(self):
        b = self.bounds
        return (b[2] - b[0], b[3] - b[1]) if b else (0.0, 0.0)


def _on_copper(paths, boxes, x, y):
    pt = (int(round(x * SCALE)), int(round(y * SCALE)))
    wind = 0
    for q, (x0, y0, x1, y1) in zip(paths, boxes):
        if x0 <= pt[0] <= x1 and y0 <= pt[1] <= y1 and pyclipper.PointInPolygon(pt, q) == 1:  # dentro, non sul bordo
            wind += 1 if pyclipper.Orientation(q) else -1
    return wind > 0


def _fit_drill(f, ref, copper, pads):
    """Fori con numeri senza punto e formato non dichiarato: il file da solo non dice quante cifre sono decimali.
    Scelgo il formato che mette più fori **al centro di una piazzola** (pads: i centri, a 0,01 mm), poi quello che ne
    mette di più sul rame; a parità resta il formato normale. Un formato che porta i fori fuori dal disegno è escluso."""
    d = f.drill
    if not d.implied or d.explicit or ref is None:
        return
    box = (ref[0] - 2.0, ref[1] - 2.0, ref[2] + 2.0, ref[3] + 2.0)
    boxes = [(min(x for x, _ in q), min(y for _, y in q), max(x for x, _ in q), max(y for _, y in q)) for q in copper]

    def on_pad(x, y):
        kx, ky = int(round(x * 100)), int(round(y * 100))
        return any((kx + ax, ky + ay) in pads for ax in (-1, 0, 1) for ay in (-1, 0, 1))

    def score(dr):
        b = dr.bounds()
        if b is None or b[0] < box[0] or b[1] < box[1] or b[2] > box[2] or b[3] > box[3]:
            return (-1, -1)
        pts = [(h[0], h[1]) for h in dr.holes] + [s[0][0] for s in dr.slots]
        pts = pts[::max(1, len(pts) // 60)]
        return (sum(1 for x, y in pts if on_pad(x, y)), sum(1 for x, y in pts if _on_copper(copper, boxes, x, y)))

    best, best_score = d, score(d)
    for dec in (3, 4, 2, 5, 6):
        t = _Drill(f._text, dec)
        try:
            t.run()
        except GerberError:
            continue
        sc = score(t)
        if sc > best_score:
            best, best_score = t, sc
    f.drill = best


def _union_bounds(bs):
    bs = [b for b in bs if b is not None]
    if not bs:
        return None
    return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)


def _drill_paths(d, mode, dot):
    out = []
    for x, y, dia in d.holes:
        out.append(_positive(circle(x, y, dot if mode == "dot" else dia)))
    for pts, dia in d.slots:
        w = dot if mode == "dot" else dia
        pl = _ip(pts)
        out += _stroke([pl], int(round(w * SCALE))) if len(pl) >= 2 else [_positive(circle(pts[0][0], pts[0][1], w))]
    return union(out)


def is_two_sided(files, opts=None):
    """Due facce: fra i file c'è rame del lato sopra E rame del lato sotto."""
    o = opts if opts is not None else Options()
    sides = {f.side for f in files if role_of(f, o) == "copper"}
    return "top" in sides and "bottom" in sides


def build(files, opts=None):
    """Mette insieme i file di una basetta. Tutti restano a registro: stessa origine, stesso specchio.

    Due facce (rame sopra e rame sotto insieme): il risultato ha i pezzi di tutte e due le facce, ognuno con il suo
    `side`. Bordo, fori e ingombro sono **in comune**; il lato sopra non è mai specchiato, il lato sotto lo è sempre,
    attorno alla linea verticale al centro dell'ingombro comune: girando la basetta da sinistra a destra e
    rimettendola nello stesso ingombro, le due facce combaciano. (La scelta «specchia» qui non conta.)"""
    o = defaults(files, opts)
    board = Board()
    board.negative = False
    coppers = [f for f in files if role_of(f, o) == "copper"]
    profiles = [f for f in files if role_of(f, o) == "profile"]
    others = [f for f in files if role_of(f, o) == "other"]
    drills = [f for f in files if f.kind == "excellon"]
    two = board.two_sided = is_two_sided(files, o)
    board.mirrored = bool(o.mirror) and not two
    for f in files:
        for w in f.warnings:
            board.warnings.append(f"{f.name}: {w}")

    ref = _union_bounds([f.bounds() for f in files if f.kind == "gerber"])
    cu_img = [p for f in (coppers or [g for g in files if g.kind == "gerber"]) for p in f.image]
    pads = set().union(*[f.flashes for f in files if f.kind == "gerber"]) if files else set()
    for f in drills:
        _fit_drill(f, ref, cu_img, pads)
        b = f.bounds()
        if ref is not None and b is not None and (b[0] < ref[0] - 2 or b[1] < ref[1] - 2 or b[2] > ref[2] + 2 or b[3] > ref[3] + 2):
            board.warnings.append(tr("{0}: i fori non cadono sul disegno: controlla unità e formato del file dei fori", f.name))

    holes = []
    if o.holes != "none":
        for f in drills:
            holes += _drill_paths(f.drill, o.holes, o.dot)
        holes = union(holes) if len(drills) > 1 else holes

    def side_of(f):
        return ("bottom" if f.side == "bottom" else "top") if two else None

    sides = ("top", "bottom") if two else (None,)
    layers = []
    if coppers:
        all_cu = union([p for f in coppers for p in f.image]) if len(coppers) > 1 else list(coppers[0].image)
        board.copper_area = area_mm2(all_cu)
        frame = []
        if o.negative:
            # Il bordo è il contorno più esterno, pieno: un contorno chiuso dentro un altro (uno scasso, una fresata)
            # NON diventa un buco. Se lo diventasse e fosse invece una basetta dentro un pannello, lì non si
            # inciderebbe niente e le piste resterebbero in corto; incidere dove il rame comunque non serve non fa danni.
            loops = [_positive(ln) for f in profiles for ln, closed in f.lines if closed and len(ln) >= 3]
            loops += [p for f in profiles for p in f.image if not f.lines]
            frame = union(loops) if loops else []
            if frame:
                board.frame = "profile"
            else:
                if profiles:
                    board.warnings.append(tr("il contorno della basetta non è una linea chiusa: uso un rettangolo attorno al disegno"))
                cb = bounds(all_cu)  # con due facce: il rame di tutte e due, così il bordo è lo stesso
                pb = _union_bounds([f.line_bounds() or f.bounds() for f in profiles])  # sull'asse dei tratti
                m = o.margin
                box = (cb[0] - m, cb[1] - m, cb[2] + m, cb[3] + m) if pb is None else _union_bounds([cb, pb])
                frame = [_positive([(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])])]
                board.frame = "box"
            board.frame_area = area_mm2(frame)
            board.negative = True
            if area_mm2(difference(all_cu, frame)) > 0.01:
                board.warnings.append(tr("una parte del rame esce dal contorno della basetta: lì non viene incisa"))
        for sd in sides:
            mine = [f for f in coppers if side_of(f) == sd]
            copper = union([p for f in mine for p in f.image]) if len(mine) > 1 else list(mine[0].image)
            real = difference(copper, holes) if holes else copper
            out = difference(frame, real) if o.negative else real
            name = mine[0].name if len(mine) == 1 else tr("Rame ({0} file)", len(mine))
            layers.append(Layer("copper", name, "area", _islands(out), area_mm2(out), sd))
    elif holes:
        layers.append(Layer("drill", drills[0].name, "area", _islands(holes), area_mm2(holes)))

    for f in others:
        if f.image:
            layers.append(Layer("other", f.name, "area", _islands(f.image), area_mm2(f.image), side_of(f)))
        else:
            board.warnings.append(tr("{0}: solo tratti di spessore zero, importati come linee", f.name))
            layers.append(Layer("other", f.name, "line", list(f.lines), side=side_of(f)))
    if not (o.negative and coppers and board.frame == "profile"):
        for f in profiles:
            for sd in sides:  # il contorno serve su tutte e due le facce
                if f.lines:
                    layers.append(Layer("profile", f.name, "line", list(f.lines), side=sd))
                elif f.image:
                    layers.append(Layer("profile", f.name, "area", _islands(f.image), area_mm2(f.image), sd))

    layers = [ly for ly in layers if ly.data]
    pts = [p for ly in layers for item in ly.data for p in item[0]]
    if not pts or (two and not all(any(ly.side == sd for ly in layers) for sd in sides)):
        raise GerberError(tr("i file non contengono nessun disegno"))
    board.bounds = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
    if board.bounds[2] - board.bounds[0] > MAX_MM or board.bounds[3] - board.bounds[1] > MAX_MM:
        raise GerberError(tr("misure non credibili ({0:.0f} × {1:.0f} mm): il formato dei numeri del file non è giusto",
                             board.bounds[2] - board.bounds[0], board.bounds[3] - board.bounds[1]))
    k = board.bounds[0] + board.bounds[2]  # un asse solo per tutti: quello dell'ingombro comune
    for ly in layers:
        if not (ly.side == "bottom" if two else o.mirror):
            continue
        if ly.kind == "area":
            ly.data = [[[(k - x, y) for x, y in c][::-1] for c in isl] for isl in ly.data]
        else:
            ly.data = [([(k - x, y) for x, y in pts], closed) for pts, closed in ly.data]
    board.layers = layers
    return board
