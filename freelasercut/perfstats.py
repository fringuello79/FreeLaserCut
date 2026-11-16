# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.5: quanto costano i movimenti del mouse con un tasto premuto (trascinare forme, nodi, il rettangolo di
selezione) e i disegni del piano mentre ci si muove.

Il controllo dei rallentamenti (app._hang_step) conta solo le fermate della finestra oltre 0,7 s. Il rapporto
FLC-20261116-0746-D046 («scatta nello spostare oggetti», PC lento) non ne aveva nessuna durante i trascinamenti: gli
scatti erano tanti e brevi, e nel rapporto non si vedevano. Qui si misura ogni movimento e ogni disegno del piano
durante i movimenti; il rapporto per l'assistenza dice quanti sono stati lenti, il più lento e di chi era la colpa
(aggancio agli oggetti, strumento, disegno). Niente Qt: lo riempie ui/canvas.py e lo legge diag.py.
"""
SLOW_S = 0.1  # un movimento o un disegno più lento di così si sente come uno scatto

DRAG = {}


def reset():
    DRAG.clear()
    DRAG.update(moves=0, slow=0, max=0.0, max_snap=0.0, snap_max=0.0, snap_sum=0.0, sum=0.0,
                paints=0, paint_slow=0, paint_max=0.0, paint_sum=0.0)


reset()


def note_move(secs, snap_secs=0.0):
    """Un movimento del mouse con un tasto premuto: secs = tempo per gestirlo, snap_secs = di cui per l'aggancio."""
    d = DRAG
    d["moves"] += 1
    d["sum"] += secs
    d["snap_sum"] += snap_secs
    d["snap_max"] = max(d["snap_max"], snap_secs)
    if secs > SLOW_S:
        d["slow"] += 1
    if secs > d["max"]:
        d["max"], d["max_snap"] = secs, snap_secs


def note_paint(secs):
    """Un disegno del piano mentre ci si muove (trascinamento, spostamento della vista, rotella)."""
    d = DRAG
    d["paints"] += 1
    d["paint_sum"] += secs
    if secs > SLOW_S:
        d["paint_slow"] += 1
    d["paint_max"] = max(d["paint_max"], secs)


def _s(x):
    return f"{x:.2f}".replace(".", ",") + " s"


def text():
    """Una riga per il rapporto, vuota se non ci si è mai mossi con un tasto premuto."""
    d = DRAG
    if not d["moves"] and not d["paints"]:
        return ""
    line = f"Movimenti col mouse premuto: {d['moves']} · oltre {_s(SLOW_S)}: {d['slow']}"
    if d["moves"]:
        line += f" · il più lento {_s(d['max'])}"
        if d["max_snap"] >= 0.005:
            line += f" (aggancio {_s(d['max_snap'])})"
        line += f" · media {_s(d['sum'] / d['moves'])} (aggancio {_s(d['snap_sum'] / d['moves'])})"
    if d["paints"]:
        line += (f" · disegni del piano durante i movimenti: {d['paints']}, oltre {_s(SLOW_S)}: {d['paint_slow']},"
                 f" il più lento {_s(d['paint_max'])}, media {_s(d['paint_sum'] / d['paints'])}")
    return line
