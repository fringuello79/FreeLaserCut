# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Zona riempita dei livelli Riempimento, nell'anteprima del piano e nelle miniature dei piani di lavoro (0.18.1).

Prima ogni forma si colorava da sola: un quadrato con il suo offset (due forme sullo stesso livello) mostrava
l'interno più scuro, come se lì si incidesse di più, mentre il laser incide solo la fascia fra i due contorni
(segnalazione di Stefano). Qui la zona si calcola come la calcola il G-code (core/gcode.py), per livello e non per
forma:
- Riempimento «tutto insieme» o «automatico»: tutti i contorni del livello insieme, regola pari-dispari;
- Riempimento «forma per forma»: ogni forma esterna con i suoi fori (gcode._fill_clusters), ciascuna pari-dispari:
  dove due gruppi si sovrappongono il laser passa due volte e il colore si somma, come nella realtà;
- Offset fill: contorni orientati come per Clipper (esterni pieni, fori vuoti), regola non-zero.
Le linee aperte non si riempiono (il G-code le ignora). Nel Riempimento «automatico» il programma sceglie al
momento del lavoro la strada più rapida: le due danno la stessa zona tranne quando forme diverse si sovrappongono
in parte; in quel caso l'anteprima mostra «tutto insieme».
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainterPath

from ..core import geom, gcode
from ..core.document import ImageShape

FILL_MODES = ("fill", "offset_fill")


def _poly_path(polys, rule):
    p = QPainterPath()
    p.setFillRule(rule)
    for poly in polys:
        if not poly.closed or len(poly.pts) < 3:
            continue
        p.moveTo(*poly.pts[0])
        for x, y in poly.pts[1:]:
            p.lineTo(x, y)
        p.closeSubpath()
    return p


def _closed_only(path):
    """Solo i sottopercorsi chiusi (le linee aperte il G-code non le riempie)."""
    polys = [p for p in geom.flatten(path, geom.FLATTEN_TOL) if p.closed]
    return polys


def regions(entries, layers):
    """entries: [(foglia, percorso già nel piano)] in ordine di disegno; layers: doc.layers.
    Ritorna [(indice del livello, QPainterPath)] da colorare (un percorso per livello, o per gruppo con
    «forma per forma»)."""
    by_layer = {}
    for leaf, mapped in entries:
        if leaf.hidden or isinstance(leaf, ImageShape) or leaf.layer >= 30:
            continue
        cs = layers.get(leaf.layer)
        if cs is None or not cs.show or cs.mode not in FILL_MODES:
            continue
        by_layer.setdefault(leaf.layer, []).append(mapped)
    out = []
    for idx, paths in by_layer.items():
        cs = layers[idx]
        if cs.mode == "offset_fill":
            polys = [p for m in paths for p in _closed_only(m)]
            out.append((idx, _poly_path(gcode._orient(polys), Qt.WindingFill)))
        elif cs.fill_grouping == "each":
            polys = [p for m in paths for p in _closed_only(m)]
            for cluster in gcode._fill_clusters(polys, "each"):
                out.append((idx, _poly_path(cluster, Qt.OddEvenFill)))
        else:  # «tutto insieme» o «automatico»
            if any(_has_open(m) for m in paths):
                out.append((idx, _poly_path([p for m in paths for p in _closed_only(m)], Qt.OddEvenFill)))
                continue
            p = QPainterPath()
            p.setFillRule(Qt.OddEvenFill)
            for m in paths:
                p.addPath(m)
            p.setFillRule(Qt.OddEvenFill)  # addPath può riportare la regola del percorso aggiunto
            out.append((idx, p))
    return out


def _has_open(path):
    """True se il percorso ha un sottopercorso aperto (linea, arco aperto)."""
    start = None
    last = None
    for i in range(path.elementCount()):
        e = path.elementAt(i)
        if e.type == QPainterPath.ElementType.MoveToElement:
            if start is not None and last is not None and (abs(last[0] - start[0]) > 1e-6 or abs(last[1] - start[1]) > 1e-6):
                return True
            start = (e.x, e.y)
        last = (e.x, e.y)
    return start is not None and last is not None and (abs(last[0] - start[0]) > 1e-6 or abs(last[1] - start[1]) > 1e-6)
