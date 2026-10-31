# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Test materiale: griglia potenza × velocità con etichette, incisa dal quadrato più leggero al più pesante.

Ogni cella ha la sua potenza e velocità (non servono 30 livelli), le etichette sono
in carattere a linea singola (veloci), la cornice è opzionale. Il risultato è un
GcodeJob come quello del generatore normale: anteprima, contorno, verifica e avvio
funzionano allo stesso modo.
"""
import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform

from . import geom, text as textmod
from .document import CutSettings
from .gcode import GcodeJob, LayerStats, _emit_polys, _emit_scan, _scanlines, _Writer
from freelasercut.i18n import tr  # noqa: E402


@dataclass
class TestSpec:
    mode: str = "fill"  # fill | line
    p_min: float = 10.0
    p_max: float = 100.0
    rows: int = 5  # potenze (righe)
    s_min: float = 1000.0
    s_max: float = 10000.0
    cols: int = 5  # velocità (colonne)
    cell: float = 10.0  # mm
    gap: float = 3.0  # mm
    interval: float = 0.1
    passes: int = 1
    x0: float = 20.0  # angolo basso-sinistra della griglia (coordinate piano)
    y0: float = 20.0
    labels: bool = True
    label_power: float = 25.0
    label_speed: float = 3000.0
    border: bool = False
    border_power: float = 100.0
    border_speed: float = 600.0
    title: str = ""


def _steps(a, b, n):
    if n <= 1:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def build(spec: TestSpec, profile):
    t0 = time.time()
    job = GcodeJob()
    bed = (profile.bed_x, profile.bed_y)
    powers = _steps(spec.p_min, spec.p_max, spec.rows)
    speeds = _steps(spec.s_min, spec.s_max, spec.cols)
    pitch = spec.cell + spec.gap
    lab = 8.0 if spec.labels else 0.0  # spazio per le etichette a sinistra e in basso
    gx0, gy0 = spec.x0 + lab, spec.y0 + lab
    W = lab + spec.cols * pitch - spec.gap
    H = lab + spec.rows * pitch - spec.gap + (7.0 if spec.title else 0.0)

    def mp(bx, by):
        return profile.to_machine(bx, by)

    w = _Writer(mp, profile.s_max)
    w.raw(f"; FreeLaserCut — test materiale {spec.rows}×{spec.cols}")
    w.raw("G90 G21")
    w.raw("M5 S0")
    w.raw("G10 L2 P2 X0 Y0")
    w.raw("G55")
    w.raw("M8")
    w.raw("M4 S0")
    cells = []
    for r, p in enumerate(powers):
        for c, s in enumerate(speeds):
            x = gx0 + c * pitch
            y = gy0 + r * pitch
            cells.append((p / max(s, 1.0), p, s, x, y))
    cells.sort()  # dal più leggero al più pesante: un problema si vede subito, sui primi quadrati
    cut0 = w.cut
    for _, p, s, x, y in cells:
        cs = CutSettings(mode=spec.mode, speed=s, power_max=p, interval=spec.interval, overscan=2.0, bidirectional=True)
        poly = geom.Poly([(x, y), (x + spec.cell, y), (x + spec.cell, y + spec.cell), (x, y + spec.cell)], True)
        for _ in range(max(1, spec.passes)):
            if spec.mode == "line":
                _emit_polys(w, [poly], cs)
            else:
                lines, rot = _scanlines([poly], spec.interval, 0.0)
                _emit_scan(w, [(yy, [(a, b, p) for a, b in segs]) for yy, segs in lines], rot, cs, bed, 6.0)
    job.layers.append(LayerStats(0, "celle", spec.mode, len(cells), w.cut - cut0, 0))
    if spec.labels:
        lc = CutSettings(mode="line", speed=spec.label_speed, power_max=spec.label_power)
        polys = []

        def put(txt, x, y, size=3.0, rot=0.0, align="center"):
            p = textmod.text_path(txt, "futural", size, align=align)
            tf = QTransform()
            tf.rotate(rot)
            tf = tf * QTransform.fromTranslate(x, y)
            polys.extend(geom.flatten(tf.map(p), 0.02))

        for c, s in enumerate(speeds):
            put(f"{s:g}", gx0 + c * pitch + spec.cell / 2, spec.y0 + 1.0, 2.6)
        for r, p in enumerate(powers):
            put(f"{p:g}%", spec.x0 + 5.5, gy0 + r * pitch + spec.cell / 2 - 1.3, 2.6, 0, "right")
        put("mm/min →", gx0 + spec.cols * pitch - spec.gap, spec.y0 - 3.5, 2.2, 0, "right")
        if spec.title:
            put(spec.title, gx0, gy0 + spec.rows * pitch + 1.5, 3.5, 0, "left")
        from .gcode import order_polys

        _emit_polys(w, order_polys(polys, w.pb or (0, 0), False, True), lc)
    if spec.border:
        bc = CutSettings(mode="line", speed=spec.border_speed, power_max=spec.border_power)
        m = 3.0
        b = geom.Poly([(spec.x0 - m, spec.y0 - m - 4), (spec.x0 + W + m, spec.y0 - m - 4),
                       (spec.x0 + W + m, spec.y0 + H + m), (spec.x0 - m, spec.y0 + H + m)], True)
        _emit_polys(w, [b], bc)
    w.raw("M5 S0")
    w.raw("M9")
    w.rapid(0.0, 0.0)
    w.raw("G54")
    job.lines = w.lines
    b, mv = w.burn, w.motion
    if b[0] <= b[2]:
        job.bounds = QRectF(b[0], b[1], b[2] - b[0], b[3] - b[1])
    if mv[0] < -0.01 or mv[1] < -0.01 or mv[2] > bed[0] + 0.01 or mv[3] > bed[1] + 0.01:
        job.warnings.append(tr("Il test esce dall'area di lavoro: cambia la posizione"))
    mx0, my0 = profile.to_machine(0.0, 0.0)
    job.out_to_bed = (-mx0, -my0)
    from .. import gcode_preview

    job.seconds = gcode_preview.parse(job.lines, profile=profile).seconds
    job.gen_ms = (time.time() - t0) * 1000
    return job
