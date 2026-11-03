# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Prova della scansione avanti e indietro: righe = velocità, colonne = correzioni da provare.

Con la scansione bidirezionale le righe incise andando a destra e quelle incise tornando a sinistra non
finiscono esattamente nello stesso punto (il laser si accende e si spegne con un piccolo ritardo, e la
cinghia ha un po' di gioco): i bordi verticali vengono "a pettine". In ogni rettangolo la correzione è
diversa: quello con i bordi più dritti dice il valore giusto per quella velocità.
Il risultato è un GcodeJob come quello del test materiale: anteprima, contorno, verifica e avvio uguali.
"""
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform

from . import geom, text as textmod
from .document import CutSettings
from .gcode import GcodeJob, LayerStats, _emit_polys, _emit_scan, _scanlines, _Writer, order_polys
from freelasercut.i18n import tr  # noqa: E402


@dataclass
class ScanTestSpec:
    speeds: list = field(default_factory=lambda: [3000.0, 6000.0, 10000.0])  # mm/min, una riga ciascuna
    off_max: float = 0.30  # correzioni da 0 a off_max (mm)
    off_step: float = 0.05
    power: float = 30.0  # %
    interval: float = 0.15  # mm
    cell_w: float = 5.0  # mm
    cell_h: float = 8.0
    gap: float = 2.0
    x0: float = 20.0  # angolo basso-sinistra (coordinate piano)
    y0: float = 20.0
    labels: bool = True
    label_power: float = 25.0
    label_speed: float = 3000.0

    def offsets(self):
        step = max(self.off_step, 0.005)
        n = int(round(max(self.off_max, 0.0) / step))
        return [round(i * step, 4) for i in range(min(n, 30) + 1)]


def build(spec: ScanTestSpec, profile):
    t0 = time.time()
    job = GcodeJob()
    bed = (profile.bed_x, profile.bed_y)
    speeds = [float(s) for s in spec.speeds if float(s) > 0][:10] or [6000.0]
    offs = spec.offsets()
    lab_x = 12.0 if spec.labels else 0.0  # velocità a sinistra
    lab_y = 6.0 if spec.labels else 0.0  # correzioni sotto
    gx0, gy0 = spec.x0 + lab_x, spec.y0 + lab_y
    px, py = spec.cell_w + spec.gap, spec.cell_h + spec.gap

    off = tuple(getattr(profile, "wcs_offset", (0.0, 0.0))) if getattr(profile, "no_g55", False) else (0.0, 0.0)

    def mp(bx, by):
        mx, my = profile.to_machine(bx, by)
        return mx - off[0], my - off[1]

    w = _Writer(mp, profile.s_max)
    w.raw(f"; FreeLaserCut — prova della scansione avanti e indietro {len(speeds)}×{len(offs)}")
    w.raw("G90 G21")
    w.raw("M5 S0")
    if getattr(profile, "no_g55", False):
        w.raw("G54")  # scheda senza G55 (le coordinate tolgono l'offset G54, vedi mp)
    else:
        w.raw("G10 L2 P2 X0 Y0")
        w.raw("G55")
    w.raw("M8")
    w.raw("M4 S0")
    cut0 = w.cut
    for r, s in enumerate(speeds):
        cs = CutSettings(mode="fill", speed=s, power_max=spec.power, interval=spec.interval, overscan=2.5,
                         bidirectional=True)
        for c, d in enumerate(offs):
            x, y = gx0 + c * px, gy0 + r * py
            w.scan_offset = (lambda _s, d=d: d)  # questo rettangolo prova la correzione d
            poly = geom.Poly([(x, y), (x + spec.cell_w, y), (x + spec.cell_w, y + spec.cell_h), (x, y + spec.cell_h)], True)
            lines, rot = _scanlines([poly], spec.interval, 0.0)
            _emit_scan(w, [(yy, [(a, b, spec.power) for a, b in segs]) for yy, segs in lines], rot, cs, bed, 6.0)
    w.scan_offset = None
    job.layers.append(LayerStats(0, "prova", "fill", len(speeds) * len(offs), w.cut - cut0, 0))
    if spec.labels:
        lc = CutSettings(mode="line", speed=spec.label_speed, power_max=spec.label_power)
        polys = []

        def put(txt, x, y, size=2.4, align="center"):
            p = textmod.text_path(txt, "futural", size, align=align)
            polys.extend(geom.flatten(QTransform.fromTranslate(x, y).map(p), 0.02))

        for c, d in enumerate(offs):
            put(f"{d:g}".replace("0.", "."), gx0 + c * px + spec.cell_w / 2, spec.y0 + 1.0, 2.0)
        for r, s in enumerate(speeds):
            put(f"{s / 1000:g}k", spec.x0 + lab_x - 2.0, gy0 + r * py + spec.cell_h / 2 - 1.0, 2.4, "right")
        _emit_polys(w, order_polys(polys, w.pb or (0, 0), False, True), lc)
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
    job.motion_bounds = QRectF(mv[0], mv[1], mv[2] - mv[0], mv[3] - mv[1]) if mv[0] <= mv[2] else None
    mx0, my0 = profile.to_machine(0.0, 0.0)
    job.out_to_bed = (-mx0 + off[0], -my0 + off[1])
    from .. import gcode_preview

    job.preview = gcode_preview.parse(job.lines, profile=profile)
    job.seconds = job.preview.seconds
    job.gen_ms = (time.time() - t0) * 1000
    return job


def size(spec: ScanTestSpec):
    """Ingombro (larghezza, altezza) in mm, etichette comprese."""
    n_s = len([s for s in spec.speeds if float(s) > 0][:10]) or 1
    n_o = len(spec.offsets())
    lab_x = 12.0 if spec.labels else 0.0
    lab_y = 6.0 if spec.labels else 0.0
    return lab_x + n_o * (spec.cell_w + spec.gap) - spec.gap, lab_y + n_s * (spec.cell_h + spec.gap) - spec.gap
