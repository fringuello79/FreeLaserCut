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
import bisect
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


class _Material(list):
    """0.22.1: i contorni chiusi con il loro rettangolo d'ingombro, così il pari-dispari salta quelli lontani (sui
    disegni con centinaia di contorni la finestra degli incastri ci metteva decine di secondi ad aprirsi)."""

    def __init__(self, polys):
        super().__init__(polys)
        self.boxes = [_bbox(p) for p in self]


def in_material(pt, all_polys):
    """Pari-dispari su tutti i contorni chiusi."""
    boxes = getattr(all_polys, "boxes", None)
    if boxes is None:
        return sum(_inside(pt, p) for p in all_polys) % 2 == 1
    x, y = pt
    return sum(_inside(pt, p) for p, b in zip(all_polys, boxes) if b[0] <= x <= b[2] and b[1] <= y <= b[3]) % 2 == 1


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


# ======================================================================= spessore del materiale (0.22.0)
# Stefano Modena ed Evoluzione2 (21/11/2026): passando da un compensato a un altro di spessore diverso non basta
# allargare le fessure. Lo spessore del materiale compare in tre modi:
#   - FESSURE e FORI: larghi quanto lo spessore (o poco meno, per farli entrare stretti) → si allargano al centro;
#   - TACCHE sul bordo (scatole a dita, incastri sul bordo): profonde quanto lo spessore → si scavano di più;
#   - LINGUETTE: lunghe quanto lo spessore → si allungano.
# Il gioco del disegno resta: un foro da 3,9 per un compensato da 4 diventa da 4,9 per uno da 5.
# Tacche e linguette contano solo se stanno su un bordo dritto (prima e dopo, il contorno continua sulla stessa riga):
# così il lato lungo di un foro rettangolare non viene preso per una tacca. Prima si scavano le tacche, poi si
# allungano le linguette che non si sono già allungate da sole: in un bordo a dita le punte restano dove sono e le
# misure esterne della scatola non cambiano.

EDGE_TOL = 0.02  # |seno| ammesso fra i tratti del bordo e il fondo della tacca


def _same_line(a, b, u, tol):
    """I tratti a=(p, q) e b=(p, q) vanno nel verso u e stanno sulla stessa retta (entro tol mm)."""
    ux, uy = u
    for p, q in (a, b):
        vx, vy, L = _unit(p, q)
        if L < MIN_WALL or vx * ux + vy * uy < 1 - EDGE_TOL:
            return False
    # distanza del secondo tratto dalla retta del primo
    nx, ny = -uy, ux
    return abs((b[0][0] - a[0][0]) * nx + (b[0][1] - a[0][1]) * ny) <= max(tol, 0.05)


def features(poly, all_polys, thick, tol):
    """Le parti di un contorno chiuso già pulito legate allo spessore thick. -> [(tipo, i, ux, uy, ax, ay, misura)]
    con tipo «fessura» (fondo lungo circa thick, spazio vuoto), «tacca» (pareti lunghe circa thick, vuoto, su un bordo
    dritto) o «linguetta» (pareti lunghe circa thick, pieno, su un bordo dritto). i = indice del fondo (o della punta)
    poly[i] → poly[i+1]; (ux, uy) il suo verso, (ax, ay) il verso della parete che entra."""
    n = len(poly)
    out = []
    if n < 4:
        return out
    for i in range(n):
        p_prev, p0, p1, p_next = poly[i - 1], poly[i], poly[(i + 1) % n], poly[(i + 2) % n]
        ux, uy, Lb = _unit(p0, p1)
        ax, ay, La = _unit(p_prev, p0)
        cx, cy, Lc = _unit(p1, p_next)
        if Lb < MIN_WALL or La < MIN_WALL or Lc < MIN_WALL:
            continue
        if abs(ax * ux + ay * uy) > ANGLE_TOL or abs(cx * ux + cy * uy) > ANGLE_TOL:
            continue
        if ax * cx + ay * cy > -1 + ANGLE_TOL:
            continue
        depth = min(La, Lc) * 0.5
        mid = ((p0[0] + p1[0]) / 2 - ax * depth, (p0[1] + p1[1]) / 2 - ay * depth)
        full = in_material(mid, all_polys)
        if not full and abs(Lb - thick) <= tol:
            out.append(("fessura", i, ux, uy, ax, ay, Lb))
            continue
        if abs(La - thick) > tol or abs(Lc - thick) > tol:
            continue
        edge_in = (poly[i - 2], p_prev)
        edge_out = (p_next, poly[(i + 3) % n])
        if not _same_line(edge_in, edge_out, (ux, uy), tol):
            continue
        out.append(("linguetta" if full else "tacca", i, ux, uy, ax, ay, (La + Lc) / 2))
    return out


def _cleaned(polys_by_shape):
    cleaned = [[(_clean(pts) if closed else [tuple(p) for p in pts], closed) for pts, closed in shape]
               for shape in polys_by_shape]
    material = _Material(pts for shape in cleaned for pts, closed in shape if closed and len(pts) >= 3)
    return cleaned, material


def detect(polys_by_shape, lo=0.8, hi=12.0, tol=0.3, progress=None):
    """Lo spessore per cui è disegnato il pezzo. -> [(spessore, {"fessura": n, "tacca": n, "linguetta": n})], il più
    probabile per primo. Lo spessore vero si legge da tacche e linguette (sono lunghe quanto il materiale); le
    fessure contano anche se un po' più strette."""
    cleaned, material = _cleaned(polys_by_shape)
    n_shapes = max(len(cleaned), 1)
    found = []  # (tipo, misura)
    for s_i, shape in enumerate(cleaned):
        if progress is not None:  # 0.22.1: metà del lavoro è la misura, l'altra metà il conto per gli spessori trovati
            progress(0.5 * s_i / n_shapes)
        for pts, closed in shape:
            if not closed or len(pts) < 4:
                continue
            n = len(pts)
            for i in range(n):
                p_prev, p0, p1, p_next = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
                ux, uy, Lb = _unit(p0, p1)
                ax, ay, La = _unit(p_prev, p0)
                cx, cy, Lc = _unit(p1, p_next)
                if min(Lb, La, Lc) < MIN_WALL or abs(ax * ux + ay * uy) > ANGLE_TOL \
                        or abs(cx * ux + cy * uy) > ANGLE_TOL or ax * cx + ay * cy > -1 + ANGLE_TOL:
                    continue
                if abs(La - Lc) <= tol and lo <= La <= hi and _same_line((pts[i - 2], p_prev),
                                                                          (p_next, pts[(i + 3) % n]), (ux, uy), tol):
                    found.append(("bordo", (La + Lc) / 2))
                elif lo <= Lb <= hi:
                    depth = min(La, Lc) * 0.5
                    mid = ((p0[0] + p1[0]) / 2 - ax * depth, (p0[1] + p1[1]) / 2 - ay * depth)
                    if not in_material(mid, material) and min(La, Lc) > Lb:
                        found.append(("fessura", Lb))
    # gruppi di misure vicine, prima quelle del bordo (lo spessore vero)
    edge_vals = sorted(v for k, v in found if k == "bordo")
    vals = edge_vals or sorted(v for k, v in found)
    least = 1 if edge_vals else 2  # una linguetta basta a dire lo spessore; una fessura da sola no
    groups = []
    for v in vals:
        if groups and v - groups[-1][-1] <= tol / 2:
            groups[-1].append(v)
        else:
            groups.append([v])
    groups.sort(key=len, reverse=True)
    out = []
    top = groups[:3]
    for g_i, g in enumerate(top):
        t = round(sorted(g)[len(g) // 2], 2)
        if len(g) < least:
            continue
        cnt = {"fessura": 0, "tacca": 0, "linguetta": 0}
        for s_i, shape in enumerate(cleaned):
            if progress is not None:
                progress(0.5 + 0.5 * (g_i + s_i / n_shapes) / len(top))
            for pts, closed in shape:
                if closed and len(pts) >= 4:
                    _q, d, sk = change_poly(pts, material, t, t + 0.01, tol)
                    for k, v in d.items():
                        cnt[k] += v
                    for k, _p in sk:
                        cnt[k] += 1
        if sum(cnt.values()):
            out.append((t, cnt))
    if progress is not None:
        progress(1.0)
    return out


def _slide_base(pts, start, step, ax, ay, delta, moved):
    """Sposta di -a·delta il tratto dritto che parte da pts[start] e va (passo step) fino all'angolo del pezzo.
    -> {indice: punto nuovo} o None se non si può (angolo già spostato, lato parallelo alla base…)."""
    n = len(pts)
    idx, k = [start], start
    while True:
        k2 = (k + step) % n
        dx, dy, L = _unit(pts[k], pts[k2])
        if L > 0 and abs(dx * ax + dy * ay) <= ANGLE_TOL:  # ancora sulla linea della base
            idx.append(k2)
            k = k2
            if len(idx) > n - 3:
                return None
            continue
        break
    # l'angolo può essere già stato spostato dal bordo accanto (due bordi a dita che si incontrano): il lato
    # passa allora per i punti nuovi, e l'angolo finale è l'incrocio delle due basi spostate
    if len(idx) < 2 or any(j in moved for j in idx[:-1]):
        return None
    corner, side = idx[-1], (idx[-1] + step) % n
    bx, by, _Lb = _unit(pts[idx[0]], pts[idx[1]])
    sx, sy, Ls = _unit(pts[side], pts[corner])
    den = bx * sy - by * sx
    if Ls < MIN_WALL or abs(den) < 0.2:  # lato quasi parallelo alla base: l'angolo non si trova bene
        return None
    trial = {j: [pts[j][0] - ax * delta, pts[j][1] - ay * delta] for j in idx[:-1]}
    # intersezione della base spostata (punto q, verso b) con il lato (punto pts[side], verso s)
    q = trial[idx[0]]
    t = ((pts[side][0] - q[0]) * sy - (pts[side][1] - q[1]) * sx) / den
    c = [q[0] + bx * t, q[1] + by * t]
    # l'angolo nuovo deve restare sul lato, dalla parte giusta
    if (c[0] - pts[side][0]) * sx + (c[1] - pts[side][1]) * sy < MIN_LEFT:
        return None
    trial[corner] = c
    return trial


def change_poly(poly, all_polys, old, new, tol):
    """-> (punti nuovi, {tipo: cambiate}, [(tipo, punto) saltate])."""
    pts = [list(p) for p in poly]
    n = len(pts)
    delta = float(new) - float(old)
    feats = features(poly, all_polys, old, tol)
    done = {"fessura": 0, "tacca": 0, "linguetta": 0}
    skipped = []
    moved = set()
    groups = []

    def walls_ok(trial, idx):
        # nessun tratto del contorno deve sparire o rovesciarsi
        for k in idx:
            for j in ((k - 1) % n, (k + 1) % n):
                if j in idx:
                    a, b = (trial[k], trial[j])
                else:
                    a, b = (trial[k], pts[j])
                o = (pts[k][0] - pts[j][0], pts[k][1] - pts[j][1])
                m = (a[0] - b[0], a[1] - b[1])
                if math.hypot(*m) < MIN_LEFT or o[0] * m[0] + o[1] * m[1] <= 0:
                    return False
        return True

    # 1) fessure e fori: si allargano al centro (come resize_poly)
    for kind, i, ux, uy, ax, ay, _m in feats:
        if kind != "fessura":
            continue
        a_out, a_in, c_in, c_out = (i - 1) % n, i, (i + 1) % n, (i + 2) % n
        group = {a_out, a_in, c_in, c_out}
        if group in groups:
            continue
        mid = ((pts[a_in][0] + pts[c_in][0]) / 2, (pts[a_in][1] + pts[c_in][1]) / 2)
        if group & moved:
            skipped.append((kind, mid))
            continue
        d = delta / 2
        trial = {k: list(pts[k]) for k in group}
        for k in (a_out, a_in):
            trial[k] = [pts[k][0] - ux * d, pts[k][1] - uy * d]
        for k in (c_in, c_out):
            trial[k] = [pts[k][0] + ux * d, pts[k][1] + uy * d]
        if not walls_ok(trial, group):
            skipped.append((kind, mid))
            continue
        for k, v in trial.items():
            pts[k] = v
        moved |= group
        groups.append(group)
        done[kind] += 1
    # 2) tacche: il fondo scende lungo le pareti
    for kind, i, ux, uy, ax, ay, _m in feats:
        if kind != "tacca":
            continue
        a_in, c_in = i, (i + 1) % n
        mid = ((pts[a_in][0] + pts[c_in][0]) / 2, (pts[a_in][1] + pts[c_in][1]) / 2)
        if a_in in moved or c_in in moved:
            skipped.append((kind, mid))
            continue
        trial = {a_in: [pts[a_in][0] + ax * delta, pts[a_in][1] + ay * delta],
                 c_in: [pts[c_in][0] + ax * delta, pts[c_in][1] + ay * delta]}
        if not walls_ok(trial, {a_in, c_in}):
            skipped.append((kind, mid))
            continue
        for k, v in trial.items():
            pts[k] = v
        moved |= {a_in, c_in}
        done[kind] += 1
    # 3) linguette. In un bordo a dita la linea delle punte resta dov'è (le misure esterne non cambiano) e scende
    # solo la linea dei fondi: una linguetta fra due tacche già scavate è già lunga giusta; una linguetta in fondo
    # alla fila (tacca da un lato, angolo del pezzo dall'altro) si allunga facendo scendere anche il tratto fino
    # all'angolo. Una linguetta da sola (incastro a tenone in un foro) si allunga spostando la punta.
    for kind, i, ux, uy, ax, ay, _m in feats:
        if kind != "linguetta":
            continue
        b_left, t_left, t_right, b_right = (i - 1) % n, i, (i + 1) % n, (i + 2) % n
        mid = ((pts[t_left][0] + pts[t_right][0]) / 2, (pts[t_left][1] + pts[t_right][1]) / 2)
        if t_left in moved or t_right in moved:
            skipped.append((kind, mid))
            continue
        lm, rm = b_left in moved, b_right in moved
        if lm and rm:
            done[kind] += 1  # già allungata dalle tacche accanto
            continue
        if not lm and not rm:
            trial = {t_left: [pts[t_left][0] + ax * delta, pts[t_left][1] + ay * delta],
                     t_right: [pts[t_right][0] + ax * delta, pts[t_right][1] + ay * delta]}
        else:
            # il tratto di base dal lato senza tacca scende fino all'angolo del pezzo; l'angolo nuovo è dove la
            # base spostata incontra il lato dopo l'angolo (anche se il lato è obliquo, come un tetto)
            trial = _slide_base(pts, b_right if lm else b_left, 1 if lm else -1, ax, ay, delta, moved)
            if trial is None:
                skipped.append((kind, mid))
                continue
        if not walls_ok(trial, set(trial)):
            skipped.append((kind, mid))
            continue
        for k, v in trial.items():
            pts[k] = v
        moved |= set(trial)
        done[kind] += 1
    return [tuple(p) for p in pts], done, skipped


def change_thickness(polys_by_shape, old, new, tol=0.3):
    """Adatta fessure, tacche e linguette dallo spessore old allo spessore new. polys_by_shape come in resize().
    -> (stessa struttura con i punti nuovi, {tipo: cambiate}, [(tipo, punto) saltate], [indici delle forme
    cambiate]). ValueError se le misure non vanno."""
    old, new, tol = float(old), float(new), float(tol)
    if not (old > 0 and new > 0 and math.isfinite(old) and math.isfinite(new)):
        raise ValueError("misure")
    if not (0 <= tol < old / 2):
        raise ValueError("tolleranza")
    cleaned, material = _cleaned(polys_by_shape)
    # ogni contorno per conto suo, poi un controllo fra contorni: un contorno cambiato che ne tocca un altro (due fori
    # troppo vicini, un foro che arriva al bordo) torna com'era e i suoi incastri si contano fra quelli saltati
    items = []  # (forma, indice, punti di prima, punti nuovi, {tipo: n}, saltate)
    for si, shape in enumerate(cleaned):
        for ci, (pts, closed) in enumerate(shape):
            if closed and len(pts) >= 4:
                q, d, s = change_poly(pts, material, old, new, tol)
                items.append([si, ci, pts, q, d, s, closed])
            else:
                items.append([si, ci, pts, pts, {}, [], closed])
    boxes = [_bbox(it[3]) for it in items]
    order = sorted(range(len(items)), key=lambda k: boxes[k][0])  # per x minima: si scorre solo chi può toccarsi
    xs = [boxes[k][0] for k in order]

    def near(a_i):
        b = boxes[a_i]
        for k in order[:bisect.bisect_right(xs, b[2])]:
            if k != a_i and boxes[k][2] >= b[0] and _boxes_meet(b, boxes[k]):
                yield k

    def revert(a_i):
        it = items[a_i]
        q0 = it[2]
        n = len(q0)
        lost = []
        for k, v in it[4].items():
            lost += [(k, (sum(p[0] for p in q0) / n, sum(p[1] for p in q0) / n))] * v
        it[3], it[4], it[5] = q0, {}, it[5] + lost
        old_box = boxes[a_i]
        boxes[a_i] = _bbox(q0)
        return old_box

    todo = [k for k, it in enumerate(items) if sum(it[4].values())]
    while todo:
        reverted = []
        for a_i in todo:
            it = items[a_i]
            if not sum(it[4].values()):
                continue
            if any(_cross(it[3], it[6], items[k][3], items[k][6]) for k in near(a_i)):
                reverted.append((a_i, revert(a_i)))
        # un contorno tornato com'era può toccare un vicino ancora cambiato: si ricontrollano solo quelli
        todo = []
        for a_i, old_box in reverted:
            area = (min(old_box[0], boxes[a_i][0]), min(old_box[1], boxes[a_i][1]),
                    max(old_box[2], boxes[a_i][2]), max(old_box[3], boxes[a_i][3]))
            todo += [k for k, it in enumerate(items) if k != a_i and sum(it[4].values()) and k not in todo
                     and _boxes_meet(area, boxes[k])]
        if reverted:
            xs_order = sorted(range(len(items)), key=lambda k: boxes[k][0])
            order[:] = xs_order
            xs[:] = [boxes[k][0] for k in order]
    out = [[None] * len(shape) for shape in cleaned]
    total = {"fessura": 0, "tacca": 0, "linguetta": 0}
    skipped, changed = [], []
    for si, ci, _p0, q, d, s, closed in items:
        out[si][ci] = (q, closed)
        for k, v in d.items():
            total[k] += v
        skipped += s
        if sum(d.values()) and si not in changed:
            changed.append(si)
    return out, total, skipped, sorted(changed)


def _bbox(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys)) if pts else (0, 0, -1, -1)


def _boxes_meet(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _cross(p, p_closed, q, q_closed):
    """I due contorni si toccano o si incrociano?"""
    def segs(pts, closed):
        n = len(pts)
        return [(pts[i], pts[(i + 1) % n]) for i in range(n if closed else n - 1)]

    pb, qbox = _bbox(p), _bbox(q)
    if not _boxes_meet(pb, qbox):
        return False
    # 0.22.1: solo i lati che stanno nella zona in comune dei due ingombri
    zone = (max(pb[0], qbox[0]), max(pb[1], qbox[1]), min(pb[2], qbox[2]), min(pb[3], qbox[3]))
    sq, qb = [], []
    for a, b in segs(q, q_closed):
        cb = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        if _boxes_meet(cb, zone):
            sq.append((a, b))
            qb.append(cb)
    if not sq:
        return False
    for a, b in segs(p, p_closed):
        ab = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        if not _boxes_meet(ab, zone):
            continue
        for (c, d), cb in zip(sq, qb):
            if _boxes_meet(ab, cb) and _seg_meet(a, b, c, d):
                return True
    return False


def _seg_meet(a, b, c, d):
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1 != o2 and o3 != o4:
        return True

    def on(p, q, r):
        return min(p[0], q[0]) - 1e-12 <= r[0] <= max(p[0], q[0]) + 1e-12 and \
            min(p[1], q[1]) - 1e-12 <= r[1] <= max(p[1], q[1]) + 1e-12

    return (o1 == 0 and on(a, b, c)) or (o2 == 0 and on(a, b, d)) or (o3 == 0 and on(c, d, a)) or \
        (o4 == 0 and on(c, d, b))
