# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.9 (universalcinema-boop, GitHub, 19/11/2026): cambiare la larghezza delle fessure degli incastri (per
esempio da 3 a 4 mm quando si passa a un compensato più spesso) senza ridisegnare il pezzo.

Che cos'è una fessura qui: un tratto dritto B lungo quanto la misura di adesso (entro la tolleranza), fra due pareti
A e C dritte, perpendicolari a B e opposte fra loro (una entra, l'altra esce), con lo spazio fra le pareti VUOTO, cioè
fuori dal materiale. Il materiale si decide con la regola pari-dispari su tutti i contorni chiusi della selezione:
così vale sia per una tacca sul bordo del pezzo sia per un foro rettangolare (anche se il foro è una forma a sé).
Una linguetta (sporgenza della stessa misura) ha lo spazio fra le pareti PIENO e non si tocca.

Come si allarga: le due pareti si spostano di metà della differenza ciascuna, lungo B, in versi opposti: il centro
della fessura resta dov'è, la profondità non cambia. Una fessura che, allargata, mangerebbe il tratto accanto (due
fessure troppo vicine, una parete che finirebbe oltre l'altra) non si cambia e si conta fra quelle saltate.

Tutto in mm sul piano; niente Qt nel calcolo.
"""
import math

ANGLE_TOL = 0.02  # |coseno| ammesso fra pareti e fondo (circa 1,1°)
MIN_WALL = 0.05  # mm: una parete più corta non è una parete
MIN_LEFT = 0.05  # mm: quanto deve restare del tratto accanto dopo lo spostamento


def _clean(pts):
    """Toglie i punti doppi e quelli in mezzo a un tratto dritto (chiuso)."""
    out = []
    for p in pts:
        if not out or math.dist(p, out[-1]) > 1e-6:
            out.append((float(p[0]), float(p[1])))
    if len(out) > 1 and math.dist(out[0], out[-1]) <= 1e-6:
        out.pop()
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            la, lb = math.dist(a, b), math.dist(b, c)
            if abs(cr) <= 1e-9 * max(la * lb, 1e-12) and (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) > 0:
                del out[i]
                changed = True
                break
    return out


def _inside(pt, poly):
    x, y = pt
    ins = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                ins = not ins
    return ins


def in_material(pt, all_polys):
    """Pari-dispari su tutti i contorni chiusi."""
    return sum(_inside(pt, p) for p in all_polys) % 2 == 1


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    return (dx / L, dy / L, L) if L > 0 else (0.0, 0.0, 0.0)


def find(poly, all_polys, width, tol):
    """Le fessure di un contorno chiuso già pulito. -> [(i, ux, uy)]: il fondo è il tratto poly[i] → poly[i+1],
    (ux, uy) il suo verso."""
    n = len(poly)
    out = []
    if n < 4:
        return out
    for i in range(n):
        p_prev, p0, p1, p_next = poly[i - 1], poly[i], poly[(i + 1) % n], poly[(i + 2) % n]
        ux, uy, Lb = _unit(p0, p1)
        if abs(Lb - width) > tol:
            continue
        ax, ay, La = _unit(p_prev, p0)  # parete che entra
        cx, cy, Lc = _unit(p1, p_next)  # parete che esce
        if La < MIN_WALL or Lc < MIN_WALL:
            continue
        if abs(ax * ux + ay * uy) > ANGLE_TOL or abs(cx * ux + cy * uy) > ANGLE_TOL:
            continue
        if ax * cx + ay * cy > -1 + ANGLE_TOL:  # le pareti devono andare in versi opposti
            continue
        depth = min(La, Lc) * 0.5
        mid = ((p0[0] + p1[0]) / 2 - ax * depth, (p0[1] + p1[1]) / 2 - ay * depth)
        if in_material(mid, all_polys):
            continue  # è una linguetta, non una fessura
        out.append((i, ux, uy))
    return out


def resize_poly(poly, all_polys, old, new, tol):
    """-> (punti nuovi, fessure cambiate, fessure saltate)."""
    pts = [list(p) for p in poly]
    n = len(pts)
    d = (float(new) - float(old)) / 2.0
    moved = set()
    groups = []
    done = skipped = 0
    for i, ux, uy in find(poly, all_polys, old, tol):
        a_out, a_in, c_in, c_out = (i - 1) % n, i, (i + 1) % n, (i + 2) % n
        group = {a_out, a_in, c_in, c_out}
        if group in groups:
            continue  # il lato opposto della stessa fessura (foro rettangolare): è già fatta
        if group & moved:
            skipped += 1
            continue
        trial = {k: list(pts[k]) for k in group}
        for k in (a_out, a_in):
            trial[k] = [pts[k][0] - ux * d, pts[k][1] - uy * d]
        for k in (c_in, c_out):
            trial[k] = [pts[k][0] + ux * d, pts[k][1] + uy * d]
        ok = math.dist(trial[a_in], trial[c_in]) > MIN_LEFT
        # i tratti accanto alle pareti (fuori dalla fessura) non devono sparire né rovesciarsi
        for k_wall, k_nb in ((a_out, (i - 2) % n), (c_out, (i + 3) % n)):
            if k_nb in group:
                continue
            ox, oy = pts[k_wall][0] - pts[k_nb][0], pts[k_wall][1] - pts[k_nb][1]
            nx, ny = trial[k_wall][0] - pts[k_nb][0], trial[k_wall][1] - pts[k_nb][1]
            if math.hypot(nx, ny) < MIN_LEFT or ox * nx + oy * ny <= 0:
                ok = False
        if not ok:
            skipped += 1
            continue
        for k, v in trial.items():
            pts[k] = v
        moved |= group
        groups.append(group)
        done += 1
    return [tuple(p) for p in pts], done, skipped


def resize(polys_by_shape, old, new, tol=0.1):
    """polys_by_shape: [[(punti, chiuso), …] per ogni forma]. -> (stessa struttura con i punti nuovi, cambiate,
    saltate, [indici delle forme cambiate]). ValueError se le misure non vanno."""
    old, new, tol = float(old), float(new), float(tol)
    if not (old > 0 and new > 0 and math.isfinite(old) and math.isfinite(new)):
        raise ValueError("misure")
    if not (0 <= tol < old / 2):
        raise ValueError("tolleranza")
    cleaned = [[(_clean(pts) if closed else [tuple(p) for p in pts], closed) for pts, closed in shape]
               for shape in polys_by_shape]
    material = [pts for shape in cleaned for pts, closed in shape if closed and len(pts) >= 3]
    out, total, skip, changed = [], 0, 0, []
    for si, shape in enumerate(cleaned):
        res, here = [], 0
        for pts, closed in shape:
            if closed and len(pts) >= 4:
                q, k, s = resize_poly(pts, material, old, new, tol)
                here += k
                skip += s
                res.append((q, True))
            else:
                res.append((pts, closed))
        out.append(res)
        total += here
        if here:
            changed.append(si)
    return out, total, skip, changed


def count(polys_by_shape, width, tol=0.1):
    """Quante fessure di quella misura ci sono."""
    cleaned = [[(_clean(pts), True) for pts, closed in shape if closed] for shape in polys_by_shape]
    material = [pts for shape in cleaned for pts, _ in shape if len(pts) >= 3]
    return sum(len(find(pts, material, float(width), float(tol))) for shape in cleaned for pts, _ in shape)
