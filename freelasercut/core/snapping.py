# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Aggancio mentre si SPOSTA una selezione (0.18.11, da una segnalazione: «l'aggancio non avviene fra angolo ed
angolo, ma fra l'angolo dell'oggetto vicino e il punto in cui ho preso l'oggetto col mouse»).

Prima si agganciava il punto del mouse: l'oggetto finiva spostato di quanto distava il mouse dal suo angolo.
Ora si agganciano i punti dell'oggetto che si sposta:
1 punto su punto: angoli, mezzerie dei lati, centro dell'ingombro e nodi della selezione contro angoli, mezzerie,
  centri e nodi delle altre forme. Vince la coppia più vicina, entro il raggio. Corregge tutti e due gli assi;
2 lato su lato, se nessun punto è a tiro: un bordo dell'ingombro contro un bordo dell'ingombro di una forma vicina
  (o centro contro centro), un asse alla volta. È quello che tiene due pezzi affiancati mentre uno scorre sull'altro;
3 griglia, per gli assi rimasti liberi: sulla griglia va un angolo dell'ingombro, non il punto del mouse.

Tutto in mm sul piano; niente Qt: lo usa ui/canvas.snap_move e si prova da solo.
"""
import numpy as np

BOX_KINDS = ("angolo", "angolo", "angolo", "angolo", "centro", "metà", "metà", "metà", "metà")
MAX_NODES = 1500  # oltre, della selezione si usano solo i 9 punti dell'ingombro (resta veloce anche con disegni fitti)


def box_points(x0, y0, x1, y1):
    """I 9 punti di un ingombro: 4 angoli, centro, mezzerie dei 4 lati (nell'ordine di BOX_KINDS)."""
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    return [(x0, y0), (x1, y0), (x0, y1), (x1, y1), (cx, cy), (cx, y0), (cx, y1), (x0, cy), (x1, cy)]


class MoveSnap:
    """Il risultato: lo spostamento corretto e che cosa mostrare. how = "punto" | "lato" | "griglia" | None."""

    __slots__ = ("dx", "dy", "hint", "label", "how")

    def __init__(self, dx, dy, hint=None, label="", how=None):
        self.dx, self.dy, self.hint, self.label, self.how = float(dx), float(dy), hint, label, how


def _norm(box):
    x0, y0, x1, y1 = box
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def move(box, nodes, dx, dy, targets, kinds, boxes, radius, grid=None):
    """box: ingombro (x0, y0, x1, y1) della selezione PRIMA dello spostamento; nodes: i suoi nodi [(x, y)…], prima
    dello spostamento; (dx, dy): lo spostamento chiesto dal mouse. targets (N×2) e kinds: punti delle altre forme;
    boxes: i loro ingombri [(x0, y0, x1, y1)…]; radius: raggio dell'aggancio in mm; grid: passo della griglia in mm,
    None se l'aggancio alla griglia è spento. -> MoveSnap."""
    x0, y0, x1, y1 = _norm(box)
    pts = box_points(x0, y0, x1, y1)
    if nodes is not None and 0 < len(nodes) <= MAX_NODES:
        pts = pts + [(float(x), float(y)) for x, y in nodes]
    src = np.asarray(pts, float)
    moved = src + (dx, dy)
    # ---- 1. punto su punto
    targets = np.asarray(targets, float).reshape(-1, 2) if targets is not None else np.zeros((0, 2))
    if len(targets) and radius > 0:
        lo, hi = moved.min(0) - radius, moved.max(0) + radius
        near = np.nonzero((targets[:, 0] >= lo[0]) & (targets[:, 0] <= hi[0])
                          & (targets[:, 1] >= lo[1]) & (targets[:, 1] <= hi[1]))[0]
        if len(near):
            t = targets[near]
            dist = np.hypot(moved[:, None, 0] - t[None, :, 0], moved[:, None, 1] - t[None, :, 1])
            i, j = np.unravel_index(int(np.argmin(dist)), dist.shape)  # a parità vince il primo: l'ingombro sui nodi
            if dist[i, j] <= radius:
                tx, ty = float(t[j, 0]), float(t[j, 1])
                return MoveSnap(tx - src[i, 0], ty - src[i, 1], (tx, ty), kinds[int(near[j])], "punto")
    # ---- 2. lato su lato (e centro su centro), un asse alla volta, solo con le forme vicine
    mx0, my0, mx1, my1 = x0 + dx, y0 + dy, x1 + dx, y1 + dy
    mcx, mcy = (mx0 + mx1) / 2.0, (my0 + my1) / 2.0
    best = {"x": None, "y": None}  # (scarto assoluto, correzione, coordinata della linea, etichetta)
    if radius > 0:
        for b in boxes or ():
            bx0, by0, bx1, by1 = _norm(b)
            if bx0 - radius > mx1 or bx1 + radius < mx0 or by0 - radius > my1 or by1 + radius < my0:
                continue  # lontana: allineare i bordi con una forma dall'altra parte del piano darebbe solo fastidio
            bcx, bcy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
            for axis, pairs in (("x", ((mx0, bx0, "lato"), (mx0, bx1, "lato"), (mx1, bx0, "lato"), (mx1, bx1, "lato"),
                                       (mcx, bcx, "centro"))),
                                ("y", ((my0, by0, "lato"), (my0, by1, "lato"), (my1, by0, "lato"), (my1, by1, "lato"),
                                       (mcy, bcy, "centro")))):
                for s, t_, label in pairs:
                    gap = abs(t_ - s)
                    if gap <= radius and (best[axis] is None or gap < best[axis][0] - 1e-12):
                        best[axis] = (gap, t_ - s, t_, label)
    out_dx, out_dy = dx, dy
    hint, label, how = None, "", None
    if best["x"] is not None:
        out_dx = dx + best["x"][1]
    if best["y"] is not None:
        out_dy = dy + best["y"][1]
    if best["x"] is not None or best["y"] is not None:
        how = "lato"
        hx = best["x"][2] if best["x"] is not None else mcx
        hy = best["y"][2] if best["y"] is not None else mcy
        hint = (hx, hy)
        label = (best["x"] or best["y"])[3] if (best["x"] is None or best["y"] is None) else (
            "lato" if "lato" in (best["x"][3], best["y"][3]) else "centro")
    # ---- 3. griglia, per gli assi rimasti liberi: ci va l'angolo dell'ingombro che le è più vicino
    if grid and grid > 0:
        gx = gy = None
        if best["x"] is None:
            fix = min((round((v + dx) / grid) * grid - (v + dx) for v in (x0, x1)), key=abs)
            out_dx, gx = dx + fix, fix
        if best["y"] is None:
            fix = min((round((v + dy) / grid) * grid - (v + dy) for v in (y0, y1)), key=abs)
            out_dy, gy = dy + fix, fix
        if how is None and (gx is not None or gy is not None):
            how, label = "griglia", "griglia"
            cx = min((x0 + out_dx, x1 + out_dx), key=lambda v: abs(round(v / grid) * grid - v))
            cy = min((y0 + out_dy, y1 + out_dy), key=lambda v: abs(round(v / grid) * grid - v))
            hint = (cx, cy)
    return MoveSnap(out_dx, out_dy, hint, label, how)
