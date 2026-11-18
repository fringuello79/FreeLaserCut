# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6: ingranaggio a denti diritti con profilo a evolvente, con i parametri dei programmi di disegno meccanico.

Tutte le misure sono in **mm veri** (sul piano), con il centro nell'origine e Y in su:
- `teeth` numero dei denti, `module` modulo m (grandezza del dente: diametro primitivo = m · denti, diametro esterno
  = m · (denti + 2), passo = π · m); due ruote ingranano se hanno lo stesso modulo e lo stesso angolo di pressione;
- `pa` angolo di pressione in gradi (14,5 / 20 / 25; 20 è lo standard);
- `backlash` gioco: di quanto si assottiglia ogni dente sul diametro primitivo (mm); per una coppia metà su ciascuna;
- `fillet` raggio di raccordo al piede del dente (mm, None = 0,38 · m, il valore delle norme);
- `hole` diametro del foro centrale (mm, 0 = senza foro, None = un quarto del diametro primitivo);
- `flat` foro a D: distanza dal centro al lato piatto (mm, 0 = foro tondo);
- `key_w`, `key_h` cava per la linguetta: larghezza e profondità oltre il foro (mm, 0 = senza);
- `spokes` alleggerimenti: numero di finestre fra mozzo e corona (0 = ruota piena, da 3 a 8).

Testa del dente = 1 · m, piede = 1,25 · m (gioco al fondo 0,25 · m), come nelle norme. Sotto il cerchio di base il
fianco scende radiale fino al piede (con pochi denti non si simula il sottotaglio).
`profile()` dà gli anelli (esterno antiorario, fori orari) e `info()` le misure da mostrare.
"""
import math

import pyclipper

PRESSURE_ANGLES = (14.5, 20.0, 25.0)
MIN_TEETH, MAX_TEETH = 6, 200
SPOKES = (0, 3, 4, 5, 6, 8)
_S = 10000.0  # pyclipper lavora con interi: 1/10000 di mm


def defaults():
    return {"pa": 20.0, "backlash": 0.0, "fillet": None, "hole": None, "flat": 0.0, "key_w": 0.0, "key_h": 0.0,
            "spokes": 0}


def clean(opts):
    """Opzioni lette da un file o arrivate dall'interfaccia: solo le chiavi note, numeri finiti nei limiti.
    None resta None (ingranaggio della versione precedente, con il suo disegno)."""
    if opts is None:
        return None
    if not isinstance(opts, dict):
        return {}
    out = {}

    def num(k, lo, hi, allow_none=False):
        if k not in opts:
            return
        v = opts[k]
        if v is None and allow_none:
            out[k] = None
            return
        try:
            v = float(v)
        except (TypeError, ValueError):
            return
        if math.isfinite(v):
            out[k] = min(max(v, lo), hi)

    num("pa", 10.0, 35.0)
    num("backlash", 0.0, 50.0)
    num("fillet", 0.0, 100.0, True)
    num("hole", 0.0, 10000.0, True)
    num("flat", 0.0, 10000.0)
    num("key_w", 0.0, 10000.0)
    num("key_h", 0.0, 10000.0)
    if "spokes" in opts:
        try:
            n = int(opts["spokes"])
        except (TypeError, ValueError):
            n = 0
        out["spokes"] = n if n in SPOKES else 0
    return out


def _get(opts, k):
    d = defaults()
    v = (opts or {}).get(k, d[k])
    return d[k] if v is None and d[k] is not None else v


def inv(a):
    return math.tan(a) - a


def radii(teeth, module, pa=20.0):
    """-> (primitivo, base, esterno, piede) come raggi in mm."""
    r = module * teeth / 2.0
    rb = r * math.cos(math.radians(pa))
    ra = r + module
    rf = max(r - 1.25 * module, r * 0.1)
    return r, rb, ra, rf


def info(teeth, module, opts=None):
    """Misure da mostrare (mm)."""
    pa = float(_get(opts, "pa"))
    r, rb, ra, rf = radii(teeth, module, pa)
    return {"module": module, "pitch_d": 2 * r, "outer_d": 2 * ra, "root_d": 2 * rf, "base_d": 2 * rb,
            "pitch": math.pi * module, "hole": hole_diameter(teeth, module, opts)}


def hole_diameter(teeth, module, opts=None):
    h = (opts or {}).get("hole")
    if h is None:
        h = round(module * teeth / 4.0, 1)  # un quarto del diametro primitivo
    return max(0.0, float(h))


def _ints(ring):
    return [(int(round(x * _S)), int(round(y * _S))) for x, y in ring]


def _floats(paths):
    return [[(x / _S, y / _S) for x, y in p] for p in paths if len(p) >= 3]


def _offset(paths, d, arc_tol):
    co = pyclipper.PyclipperOffset(2.0, max(arc_tol, 1e-4) * _S)
    co.AddPaths(paths, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    return co.Execute(d * _S)


def _bool(a, b, op):
    pc = pyclipper.Pyclipper()
    pc.AddPaths(a, pyclipper.PT_SUBJECT, True)
    if b:
        pc.AddPaths(b, pyclipper.PT_CLIP, True)
    return pc.Execute(op, pyclipper.PFT_NONZERO, pyclipper.PFT_NONZERO)


def _arc(r, a0, a1, step):
    n = max(1, int(math.ceil(abs(a1 - a0) / step)))
    return [(r * math.cos(a0 + (a1 - a0) * k / n), r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def outline(teeth, module, pa=20.0, backlash=0.0, tol=0.01):
    """Contorno dei denti, senza raccordi (anello antiorario, mm)."""
    z = int(teeth)
    r, rb, ra, rf = radii(z, module, pa)
    alpha = math.radians(pa)
    s = max(math.pi * module / 2.0 - backlash, math.pi * module / 2.0 * 0.2)  # spessore del dente sul primitivo
    psi = s / (2.0 * r)

    def theta(rho):  # mezzo spessore angolare del dente al raggio rho (rho >= rb)
        return psi + inv(alpha) - inv(math.acos(min(1.0, rb / rho)))

    top = ra
    if theta(ra) < 0:  # dente a punta: la testa si ferma dove i fianchi si incontrano
        lo, hi = max(rb, rf), ra
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if theta(mid) > 0 else (lo, mid)
        top = lo
    start = max(rb, rf)
    n = 16
    flank = [start + (top - start) * (1 - math.cos(math.pi / 2 * k / n)) for k in range(n + 1)]  # più fitto in alto
    th_root = theta(start)
    step = max(tol / max(ra, 1e-9), 0.002) * 4
    pitch = 2 * math.pi / z
    th_root = min(th_root, pitch * 0.49)
    pts = []
    for i in range(z):
        c = i * pitch
        if rb > rf:  # sotto il cerchio di base: fianco radiale fino al piede
            pts.append((rf * math.cos(c - th_root), rf * math.sin(c - th_root)))
        for rho in flank:
            a = c - min(theta(rho), pitch * 0.49)
            pts.append((rho * math.cos(a), rho * math.sin(a)))
        ta = max(theta(top), 0.0)
        pts += _arc(top, c - ta, c + ta, step)[1:-1]
        for rho in reversed(flank):
            a = c + min(theta(rho), pitch * 0.49)
            pts.append((rho * math.cos(a), rho * math.sin(a)))
        if rb > rf:
            pts.append((rf * math.cos(c + th_root), rf * math.sin(c + th_root)))
        pts += _arc(rf, c + th_root, c + pitch - th_root, step)[1:-1]  # fondo fra due denti
    return pts


def _hole_paths(teeth, module, opts, arc_tol):
    d = hole_diameter(teeth, module, opts)
    if d <= 0:
        return [], 0.0
    rh = d / 2.0
    n = max(24, int(2 * math.pi * rh / max(arc_tol * 8, 0.05)))
    circle = _ints([(rh * math.cos(2 * math.pi * k / n), rh * math.sin(2 * math.pi * k / n)) for k in range(n)])
    paths = [circle]
    reach = rh
    flat = float(_get(opts, "flat") or 0.0)
    if 0 < flat < rh:  # foro a D: tolto il segmento oltre il lato piatto (in alto)
        box = _ints([(-rh - 1, -rh - 1), (rh + 1, -rh - 1), (rh + 1, flat), (-rh - 1, flat)])
        paths = _bool(paths, [box], pyclipper.CT_INTERSECTION) or paths
    kw, kh = float(_get(opts, "key_w") or 0.0), float(_get(opts, "key_h") or 0.0)
    if kw > 0 and kh > 0:  # cava per la linguetta, in alto (dalla parte opposta al lato piatto se c'è)
        kw = min(kw, 2 * rh * 0.95)
        ky = -1 if 0 < flat < rh else 1
        y0, y1 = 0.0, ky * (rh + kh)
        rect = _ints([(-kw / 2, min(y0, y1)), (kw / 2, min(y0, y1)), (kw / 2, max(y0, y1)), (-kw / 2, max(y0, y1))])
        paths = _bool(paths, [rect], pyclipper.CT_UNION) or paths
        reach = max(reach, rh + kh)
    return paths, reach


def profile(teeth, module, opts=None, tol=0.01):
    """Anelli dell'ingranaggio in mm, centro nell'origine: [contorno esterno (antiorario)] + fori (orari).
    -> [[(x, y), ...], ...]."""
    z = max(MIN_TEETH, min(MAX_TEETH, int(round(teeth))))
    m = max(float(module), 1e-3)
    opts = opts or {}
    pa = float(_get(opts, "pa"))
    backlash = float(_get(opts, "backlash") or 0.0)
    r, rb, ra, rf = radii(z, m, pa)
    outer = [_ints(outline(z, m, pa, backlash, tol))]
    # raccordo al piede: chiusura (allarga e poi stringe dello stesso raggio) che arrotonda solo gli angoli concavi.
    # Mai più largo di metà del vano fra due denti, che altrimenti si riempirebbe
    f = opts.get("fillet")
    f = 0.38 * m if f is None else float(f)
    gap = 2 * rf * math.sin(max(math.pi / z - (math.pi * m / 2) / (2 * r) - inv(math.radians(pa)), 0.01))
    f = min(f, gap * 0.45, 0.6 * m)
    if f > 1e-4:
        got = _offset(_offset(outer, f, tol), -f, tol)
        if got:
            outer = [max(got, key=lambda p: abs(pyclipper.Area(p)))]
    holes, reach = _hole_paths(z, m, opts, tol)
    body = outer
    if holes:
        body = _bool(outer, holes, pyclipper.CT_DIFFERENCE) or outer
    k = int(_get(opts, "spokes") or 0)
    if k >= 3:
        r_out = rf - 2.0 * m  # corona
        r_in = max(reach + 1.5 * m, rf * 0.28)  # mozzo
        if r_out - r_in > 2.0 * m:
            sw = max(1.5 * m, r_out * 0.12)  # larghezza delle razze
            rc = min(m, (r_out - r_in) * 0.2)  # raggio degli angoli delle finestre
            wins = []
            step = 2 * math.pi / k
            for i in range(k):
                a0, a1 = i * step, (i + 1) * step
                n = max(8, int((a1 - a0) * r_out / max(tol * 10, 0.2)))
                ring = [(r_out * math.cos(a0 + (a1 - a0) * j / n), r_out * math.sin(a0 + (a1 - a0) * j / n)) for j in range(n + 1)]
                ring += [(r_in * math.cos(a1 - (a1 - a0) * j / n), r_in * math.sin(a1 - (a1 - a0) * j / n)) for j in range(n + 1)]
                win = _offset(_offset([_ints(ring)], -(sw / 2 + rc), tol), rc, tol)
                wins += win
            if wins:
                body = _bool(body, wins, pyclipper.CT_DIFFERENCE) or body
    rings = sorted(_floats(body), key=lambda rg: -abs(_area_of(rg)))
    out = []
    for i, ring in enumerate(rings):  # il più grande è il contorno (antiorario), gli altri sono fori (orari)
        ccw = _area_of(ring) > 0
        out.append(ring if ccw == (i == 0) else ring[::-1])
    return out


def _area_of(ring):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1])) / 2.0
