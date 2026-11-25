# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Distanze fisse (0.23.0, in prova): una forma «che segue» tiene la distanza da una forma «di riferimento».

Il legame vive nella forma che segue (`Shape.ties`), così annulla, piani, copie e file lo trattano come il resto della
forma. Qui solo funzioni pure, sugli ingombri sul piano (`Shape.bounds()`, gli stessi di Allinea e Distanza esatta).

Un legame è un dizionario:
- X o Y: {"ref": id, "axis": "x"|"y", "er": bordo del riferimento, "es": bordo di chi segue, "side": +1|-1, "d": mm}
  con i bordi "min" / "center" / "max"; vale  bordo(S) = bordo(R) + side · d  lungo l'asse.
- punto-punto: {"ref": id, "axis": "p", "er": [bx, by], "es": [bx, by], "d": mm, "u": [ux, uy]}
  (uno dei 9 punti dell'ingombro per parte); vale  punto(S) = punto(R) + d · u, con u lungo 1 fissato alla creazione.
- "on": False solo se il legame è spento (non guida, resta salvato).

Regole (progetto in freeburn/coda-0.23.0.md): un legame per asse per ogni forma che segue (punto-punto occupa X e Y),
niente giri, chi segue si sposta e basta (mai forma, misure, rotazione), una forma bloccata non si sposta. Un legame
il cui riferimento non è fra le forme di primo livello del piano (eliminato, raggruppato, su un altro piano) dorme:
non guida e non si disegna, e si risveglia se il riferimento torna (Annulla, Separa).
"""
import math

EDGES = ("min", "center", "max")
AXES = ("x", "y", "p")
D_MAX = 5000.0
EPS = 1e-9


# ------------------------------------------------------------------ geometria degli ingombri
def _span(r, axis):
    return (r.left(), r.right()) if axis == "x" else (r.top(), r.bottom())


def edge(r, axis, e):
    lo, hi = _span(r, axis)
    return lo if e == "min" else hi if e == "max" else (lo + hi) / 2.0


def point(r, pair):
    return edge(r, "x", pair[0]), edge(r, "y", pair[1])


# ------------------------------------------------------------------ dati puliti (anche da file rovinati o di terzi)
def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _pair(v):
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(e in EDGES for e in v):
        return [v[0], v[1]]
    return None


def clean_one(t):
    """Un legame valido (copia) oppure None."""
    if not isinstance(t, dict) or not isinstance(t.get("ref"), str) or not t["ref"]:
        return None
    axis = t.get("axis")
    d = _num(t.get("d"))
    if axis not in AXES or d is None or d < 0:
        return None
    d = min(d, D_MAX)
    out = {"ref": t["ref"], "axis": axis, "d": d}
    if axis == "p":
        er, es, u = _pair(t.get("er")), _pair(t.get("es")), t.get("u")
        if er is None or es is None or not isinstance(u, (list, tuple)) or len(u) != 2:
            return None
        ux, uy = _num(u[0]), _num(u[1])
        n = math.hypot(ux or 0.0, uy or 0.0) if ux is not None and uy is not None else 0.0
        if n < EPS:
            return None
        out.update(er=er, es=es, u=[ux / n, uy / n])
    else:
        if t.get("er") not in EDGES or t.get("es") not in EDGES or t.get("side") not in (1, -1):
            return None
        out.update(er=t["er"], es=t["es"], side=int(t["side"]))
    if t.get("on") is False:
        out["on"] = False
    return out


def clean(ties):
    """Lista di legami validi; scarta il resto (i file vecchi non hanno la chiave: lista vuota)."""
    if not isinstance(ties, list):
        return []
    return [c for c in (clean_one(t) for t in ties) if c is not None]


def uses(t):
    """Assi occupati da un legame."""
    return ("x", "y") if t["axis"] == "p" else (t["axis"],)


# ------------------------------------------------------------------ creazione
def make_xy(ref_id, rr, rs, axis, er, es, d=None, side=None):
    """Legame lungo X o Y che tiene la posizione attuale (d e lato dalla misura di adesso) se non sono dati."""
    diff = edge(rs, axis, es) - edge(rr, axis, er)
    if side is None:
        side = 1 if diff >= -EPS else -1
    if d is None:
        d = abs(diff)
    return clean_one({"ref": ref_id, "axis": axis, "er": er, "es": es, "side": side, "d": d})


def make_p(ref_id, rr, rs, er, es):
    """Legame da punto a punto che tiene la posizione attuale. None se i due punti coincidono (nessuna direzione)."""
    (x0, y0), (x1, y1) = point(rr, er), point(rs, es)
    d = math.hypot(x1 - x0, y1 - y0)
    if d < 1e-6:
        return None
    return clean_one({"ref": ref_id, "axis": "p", "er": er, "es": es, "d": d, "u": [(x1 - x0) / d, (y1 - y0) / d]})


# ------------------------------------------------------------------ misura e spostamento
def measure(t, rr, rs):
    """Distanza attuale con la definizione del legame (per X/Y con il segno del lato: negativa = dall'altra parte)."""
    if t["axis"] == "p":
        (x0, y0), (x1, y1) = point(rr, t["er"]), point(rs, t["es"])
        return (x1 - x0) * t["u"][0] + (y1 - y0) * t["u"][1]
    return (edge(rs, t["axis"], t["es"]) - edge(rr, t["axis"], t["er"])) * t["side"]


def shift(t, rr, rs):
    """(dx, dy) che porta l'ingombro rs a rispettare il legame."""
    if t["axis"] == "p":
        (x0, y0), (x1, y1) = point(rr, t["er"]), point(rs, t["es"])
        return x0 + t["d"] * t["u"][0] - x1, y0 + t["d"] * t["u"][1] - y1
    delta = edge(rr, t["axis"], t["er"]) + t["side"] * t["d"] - edge(rs, t["axis"], t["es"])
    return (delta, 0.0) if t["axis"] == "x" else (0.0, delta)


def ends(t, rr, rs):
    """Due punti per disegnare la quota: (punto sul riferimento, punto su chi segue)."""
    if t["axis"] == "p":
        return point(rr, t["er"]), point(rs, t["es"])
    if t["axis"] == "x":
        y = (max(rr.top(), rs.top()) + min(rr.bottom(), rs.bottom())) / 2.0  # a metà della parte in comune
        if max(rr.top(), rs.top()) > min(rr.bottom(), rs.bottom()):  # non si sovrappongono: a metà fra i centri
            y = (rr.center().y() + rs.center().y()) / 2.0
        return (edge(rr, "x", t["er"]), y), (edge(rs, "x", t["es"]), y)
    x = (max(rr.left(), rs.left()) + min(rr.right(), rs.right())) / 2.0
    if max(rr.left(), rs.left()) > min(rr.right(), rs.right()):
        x = (rr.center().x() + rs.center().x()) / 2.0
    return (x, edge(rr, "y", t["er"])), (x, edge(rs, "y", t["es"]))


# ------------------------------------------------------------------ grafo dei legami di un piano
def active(shapes):
    """{id di chi segue: [(legame, id del riferimento)]} per i legami accesi con il riferimento presente fra le forme
    di primo livello. Per ogni asse vale il primo legame (un file di terzi con due legami sullo stesso asse non
    fa saltare niente)."""
    ids = {s.id for s in shapes}
    out = {}
    for s in shapes:
        busy = set()
        for t in getattr(s, "ties", None) or ():
            if t.get("on") is False or t["ref"] not in ids or t["ref"] == s.id:
                continue
            ax = uses(t)
            if busy.intersection(ax):
                continue
            busy.update(ax)
            out.setdefault(s.id, []).append(t)
    return out


def order(shapes):
    """(ordine di calcolo, ids nei giri). Prima i riferimenti, poi chi li segue (A→B→C: B prima di C)."""
    act = active(shapes)
    deps = {sid: {t["ref"] for t in ts} for sid, ts in act.items()}
    done, out, cyc = set(), [], set()
    state = {}

    def visit(n, stack):
        st = state.get(n)
        if st == 2:
            return
        if st == 1:  # giro
            cyc.update(stack[stack.index(n):])
            return
        state[n] = 1
        stack.append(n)
        for r in sorted(deps.get(n, ())):
            visit(r, stack)
        stack.pop()
        state[n] = 2
        if n in deps and n not in done:
            done.add(n)
            out.append(n)

    for s in shapes:
        if s.id in deps:
            visit(s.id, [])
    return [n for n in out if n not in cyc], cyc


def ancestors(shapes, sid):
    """Riferimenti da cui dipende sid, anche di seguito (A→B→C: per C sono B e A)."""
    act = active(shapes)
    seen, todo = set(), [sid]
    while todo:
        n = todo.pop()
        for t in act.get(n, ()):
            if t["ref"] not in seen:
                seen.add(t["ref"])
                todo.append(t["ref"])
    return seen


def check_new(shapes, follower, ref, axis):
    """Motivo per cui il legame non si può aggiungere ("" = si può). follower e ref sono forme di primo livello."""
    if follower is ref or follower.id == ref.id:
        return "same"
    if follower.locked:
        return "locked"
    if follower.id in ancestors(shapes, ref.id) or follower.id == ref.id:
        return "cycle"
    want = ("x", "y") if axis == "p" else (axis,)
    for t in active(shapes).get(follower.id, ()):
        if set(uses(t)).intersection(want):
            return "busy"
    return ""


def add(follower, t):
    """Aggiunge il legame togliendo quelli spenti o addormentati sugli stessi assi (il nuovo prende il loro posto)."""
    want = set(uses(t))
    keep = [o for o in (getattr(follower, "ties", None) or ()) if not want.intersection(uses(o))]
    follower.ties = keep + [t]


def solve(shapes, translate):
    """Sposta chi segue, in ordine, perché tutti i legami del piano siano rispettati.
    translate(shape, dx, dy) applica lo spostamento. -> (ids spostati, ids bloccati che non rispettano, ids nei giri)."""
    by = {s.id: s for s in shapes}
    act = active(shapes)
    seq, cyc = order(shapes)
    moved, stuck = [], []
    for sid in seq:
        s = by[sid]
        dx = dy = 0.0
        rs = s.bounds()
        for t in act[sid]:
            a, b = shift(t, by[t["ref"]].bounds(), rs)
            dx += a
            dy += b
        if abs(dx) < 1e-7 and abs(dy) < 1e-7:
            continue
        if s.locked:
            stuck.append(sid)
            continue
        translate(s, dx, dy)
        moved.append(sid)
    return moved, stuck, sorted(cyc)


# ------------------------------------------------------------------ piano ruotato (rotazioni di 90°, niente specchi)
def _axis_map(lin):
    """lin = (m11, m12, m21, m22) di QTransform: x' = m11 x + m21 y, y' = m12 x + m22 y.
    -> {asse vecchio: (asse nuovo, segno)}"""
    m11, m12, m21, m22 = lin
    ax = ("x", 1 if m11 > 0 else -1) if abs(m11) > 0.5 else ("y", 1 if m12 > 0 else -1)
    ay = ("y", 1 if m22 > 0 else -1) if abs(m22) > 0.5 else ("x", 1 if m21 > 0 else -1)
    return {"x": ax, "y": ay}


_FLIP = {"min": "max", "max": "min", "center": "center"}


def map_one(t, lin):
    """Lo stesso legame visto dopo una rotazione del piano (lin = parte lineare). Per X/Y: l'asse può scambiarsi e,
    se il verso si capovolge, min/max e lato si capovolgono con lui."""
    m = _axis_map(lin)
    t = dict(t)
    if t["axis"] == "p":
        m11, m12, m21, m22 = lin
        ux, uy = t["u"]
        t["u"] = [m11 * ux + m21 * uy, m12 * ux + m22 * uy]

        def mp(pair):
            new = {}
            for old, e in zip(("x", "y"), pair):
                na, sg = m[old]
                new[na] = e if sg > 0 else _FLIP[e]
            return [new["x"], new["y"]]

        t["er"], t["es"] = mp(t["er"]), mp(t["es"])
        return t
    na, sg = m[t["axis"]]
    t["axis"] = na
    if sg < 0:
        t["er"], t["es"], t["side"] = _FLIP[t["er"]], _FLIP[t["es"]], -t["side"]
    return t


def lin_of(tf):
    return tf.m11(), tf.m12(), tf.m21(), tf.m22()


def map_shape_tree(shape, tf):
    """Legami della forma e di quelle che contiene (anche addormentati nei gruppi) dopo la rotazione del piano."""
    lin = lin_of(tf)
    if getattr(shape, "ties", None):
        shape.ties = [map_one(t, lin) for t in shape.ties]
    for ch in getattr(shape, "children", None) or ():
        map_shape_tree(ch, tf)


def map_dict_tree(d, tf):
    """Come map_shape_tree, sul dizionario di una forma (per il file)."""
    lin = lin_of(tf)
    if d.get("ties"):
        d["ties"] = [map_one(t, lin) for t in d["ties"]]
    for ch in (d.get("p") or {}).get("children") or ():
        if isinstance(ch, dict):
            map_dict_tree(ch, tf)
