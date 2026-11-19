# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.9 (universalcinema-boop, GitHub, 19/11/2026): guide orizzontali e verticali tirate fuori dai righelli.

Una guida è una retta del piano come si vede: ("h", y) orizzontale, ("v", x) verticale, in mm. Non si incide, non
entra nel G-code e non è una forma: sta nel progetto (Document.guides) e serve ad allineare e ad agganciare.
Niente Qt qui: le funzioni lavorano su numeri e si provano da sole.

Invarianti: ogni guida ha un tipo "h" o "v" e una posizione finita; mai due guide uguali (entro GUIDE_EPS);
al massimo MAX_GUIDES. Nel file le guide sono nelle coordinate della macchina (come le forme, 0.19.3): con il piano
ruotato una guida orizzontale sullo schermo è verticale per la macchina, e torna orizzontale riaprendo il file.
"""
import math

H, V = "h", "v"
MAX_GUIDES = 200
GUIDE_EPS = 0.001  # mm: due guide più vicine di così sono la stessa
LIMIT = 100000.0  # mm: una guida oltre è un valore rovinato


def clean(guides):
    """Lista pulita: solo voci valide, arrotondate al millesimo, senza doppioni, al massimo MAX_GUIDES, in ordine.
    Accetta liste, tuple o dizionari {"k": "h", "p": 12.5} (file scritti a mano o rovinati)."""
    out = []
    for g in guides or ():
        try:
            if isinstance(g, dict):
                k, p = g.get("k"), g.get("p")
            else:
                k, p = g[0], g[1]
            k = str(k).lower()
            p = float(p)
        except (TypeError, ValueError, IndexError, KeyError, AttributeError):
            continue
        if k not in (H, V) or not math.isfinite(p) or abs(p) > LIMIT:
            continue
        p = round(p, 3) + 0.0
        if any(k == k2 and abs(p - p2) < GUIDE_EPS for k2, p2 in out):
            continue
        out.append((k, p))
        if len(out) >= MAX_GUIDES:
            break
    out.sort(key=lambda g: (g[0], g[1]))
    return out


def add(guides, kind, pos):
    """-> (lista nuova, indice della guida aggiunta) o (lista com'era, None) se non va (doppione, piena, valore)."""
    before = clean(guides)
    after = clean(before + [(kind, pos)])
    if len(after) == len(before):
        return before, None
    p = round(float(pos), 3) + 0.0
    return after, next(i for i, g in enumerate(after) if g[0] == kind and abs(g[1] - p) < GUIDE_EPS)


def transform(guides, mapfn):
    """Le guide portate in un altro sistema: mapfn(x, y) -> (x', y') affine senza deformazioni (rotazioni di 90° e
    traslazioni: piano ↔ macchina). Una guida che dopo non è né orizzontale né verticale si perde (non succede con
    le rotazioni del piano)."""
    out = []
    for k, p in clean(guides):
        a = mapfn(0.0, p) if k == H else mapfn(p, 0.0)
        b = mapfn(1.0, p) if k == H else mapfn(p, 1.0)
        dx, dy = b[0] - a[0], b[1] - a[1]
        if abs(dy) < 1e-9 and abs(dx) > 1e-9:
            out.append((H, a[1]))
        elif abs(dx) < 1e-9 and abs(dy) > 1e-9:
            out.append((V, a[0]))
    return clean(out)


def distance(guide, x, y):
    k, p = guide
    return abs(y - p) if k == H else abs(x - p)


def nearest(guides, x, y, radius):
    """Indice della guida più vicina al punto entro radius (mm), o None."""
    best, idx = None, None
    for i, g in enumerate(guides or ()):
        d = distance(g, x, y)
        if d <= radius and (best is None or d < best):
            best, idx = d, i
    return idx


def snap_point(x, y, guides, radius):
    """Un punto agganciato alle guide vicine, un asse alla volta. -> (x', y', guida su x?, guida su y?)."""
    gx = min((p for k, p in guides or () if k == V and abs(x - p) <= radius), key=lambda p: abs(x - p), default=None)
    gy = min((p for k, p in guides or () if k == H and abs(y - p) <= radius), key=lambda p: abs(y - p), default=None)
    return (x if gx is None else gx, y if gy is None else gy, gx is not None, gy is not None)


def snap_box(box, dx, dy, guides, radius):
    """Spostando un ingombro (x0, y0, x1, y1) di (dx, dy): bordo o centro che finisce vicino a una guida ci si
    appoggia. -> (correzione x o None, correzione y o None, x della guida o None, y della guida o None)."""
    x0, y0, x1, y1 = min(box[0], box[2]), min(box[1], box[3]), max(box[0], box[2]), max(box[1], box[3])
    xs = (x0 + dx, x1 + dx, (x0 + x1) / 2.0 + dx)
    ys = (y0 + dy, y1 + dy, (y0 + y1) / 2.0 + dy)
    fx = fy = lx = ly = None
    for k, p in guides or ():
        vals = xs if k == V else ys
        for v in vals:
            gap = p - v
            if abs(gap) <= radius:
                if k == V and (fx is None or abs(gap) < abs(fx)):
                    fx, lx = gap, p
                elif k == H and (fy is None or abs(gap) < abs(fy)):
                    fy, ly = gap, p
    return fx, fy, lx, ly
