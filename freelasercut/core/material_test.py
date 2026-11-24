# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Test materiale: griglia potenza × velocità con etichette, incisa dal quadrato più leggero al più pesante.

Ogni cella ha la sua potenza e velocità (non servono 30 livelli), le etichette sono
in carattere a linea singola (veloci), la cornice è opzionale. Il risultato è un
GcodeJob come quello del generatore normale: anteprima, contorno, verifica e avvio
funzionano allo stesso modo.
"""
import math
import time
from dataclasses import dataclass, replace
from types import SimpleNamespace

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
    markers: bool = False  # quattro riferimenti agli angoli per leggere la foto del test (solo riempimento)
    content: object = None  # 0.22.5: CellContent (forma o pezzo di foto in ogni quadrato); None = quadrati pieni


@dataclass
class CellContent:
    """0.22.5 (richiesta di Stefano Modena): in ogni quadrato del test, al posto del quadrato pieno, la forma scelta o
    un pezzo della foto, rimpicciolito per entrare nel quadrato. Per le foto: si sceglie la zona con più grigi, così un
    solo test dice quali potenza e velocità rendono meglio proprio quella foto.

    kind «shape»: polys = poligoni sul piano (mm), come sono disegnati; si riempiono (Riempimento) o si seguono (Linea).
    kind «image»: image = pezzo della foto (PIL), w × h in mm locali; lin = parte lineare della trasformazione della
    foto (m11, m12, m21, m22: rotazione e specchio restano), brightness/contrast/gamma della foto; cs = impostazioni
    del suo livello (risoluzione, retino, negativo…): del test cambiano solo potenza, velocità e passate."""
    kind: str = "shape"
    polys: list = None
    image: object = None
    w: float = 0.0
    h: float = 0.0
    lin: tuple = (1.0, 0.0, 0.0, 1.0)
    brightness: float = 0.0
    contrast: float = 0.0
    gamma: float = 1.0
    cs: object = None


def best_gray_region(dark, frac=0.35, n=12):
    """La zona quadrata (lato = frac del lato corto) con più toni di grigio diversi. dark: scuro 0..1 (righe dall'alto).
    -> (x0, y0, x1, y1) in frazioni della foto, origine in alto a sinistra. Punteggio: quanti dei 16 toni ci sono e
    quanto sono distribuiti (entropia), più lo scarto: un cielo uniforme o un nero pieno non vincono mai."""
    import numpy as np

    a = np.asarray(dark, dtype=np.float32)
    if a.ndim != 2 or a.size == 0:
        return (0.0, 0.0, 1.0, 1.0)
    H, W = a.shape
    k = max(1, int(max(H, W) / 240))
    if k > 1:
        a = a[: H - H % k or H, : W - W % k or W]
        a = a.reshape(a.shape[0] // k, k, a.shape[1] // k, k).mean(axis=(1, 3))
    h, w = a.shape
    side = max(2, int(round(min(h, w) * min(max(frac, 0.05), 1.0))))
    q = np.clip((a * 16).astype(np.int32), 0, 15)
    best, out = -1.0, (0, 0)
    ys = sorted({int(round(i * (h - side) / max(n - 1, 1))) for i in range(n)}) if h > side else [0]
    xs = sorted({int(round(i * (w - side) / max(n - 1, 1))) for i in range(n)}) if w > side else [0]
    for y in ys:
        for x in xs:
            win = q[y:y + side, x:x + side]
            hist = np.bincount(win.ravel(), minlength=16).astype(np.float64)
            pr = hist / max(hist.sum(), 1.0)
            ent = -float(np.sum(pr[pr > 0] * np.log2(pr[pr > 0])))  # 0..4
            score = ent + 2.0 * float(a[y:y + side, x:x + side].std())
            if score > best + 1e-9:
                best, out = score, (x, y)
    x, y = out
    return (x / w, y / h, min(1.0, (x + side) / w), min(1.0, (y + side) / h))


def _fit(rect, cx, cy, size):
    """QTransform che porta il rettangolo rect (piano) dentro il quadrato (cx, cy, lato size), centrato, senza
    deformarlo, con un margine piccolo (si vede dove finisce un quadrato e comincia l'altro)."""
    room = size * 0.96
    k = room / max(rect.width(), rect.height(), 1e-9)
    tx = cx + (size - rect.width() * k) / 2 - rect.left() * k
    ty = cy + (size - rect.height() * k) / 2 - rect.top() * k
    return QTransform(k, 0.0, 0.0, k, tx, ty)


def _cell_shape_polys(content, x, y, size):
    from PySide6.QtCore import QPointF

    pts = [pt for p in content.polys for pt in p.pts]
    xs, ys = [pt[0] for pt in pts], [pt[1] for pt in pts]
    r = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    tf = _fit(r, x, y, size)
    out = []
    for p in content.polys:
        q = [tf.map(QPointF(px, py)) for px, py in p.pts]
        out.append(geom.Poly([(v.x(), v.y()) for v in q], p.closed))
    return out


def _cell_image(content, x, y, size):
    """(leaf, tf) della foto rimpicciolita dentro il quadrato, orientata come sul piano."""
    from .document import ImageShape

    leaf = ImageShape(None, content.w, content.h)
    leaf._doc_image = content.image
    leaf.brightness, leaf.contrast, leaf.gamma = content.brightness, content.contrast, content.gamma
    m11, m12, m21, m22 = content.lin
    lin = QTransform(m11, m12, m21, m22, 0.0, 0.0)
    r = lin.map(leaf.photo_path()).boundingRect()
    return leaf, lin * _fit(r, x, y, size)


def content_ok(content):
    """La forma o la foto scelta si può usare? -> testo dell'errore, o "" se va bene."""
    if content is None:
        return ""
    if content.kind == "image":
        if content.image is None or content.w <= 0 or content.h <= 0:
            return tr("Foto non disponibile: selezionala di nuovo sul piano")
        return ""
    pts = [pt for p in (content.polys or []) for pt in p.pts]
    if len(pts) < 2:
        return tr("Forma vuota: selezionala di nuovo sul piano")
    xs, ys = [pt[0] for pt in pts], [pt[1] for pt in pts]
    if max(xs) - min(xs) < 1e-6 and max(ys) - min(ys) < 1e-6:
        return tr("Forma troppo piccola")
    return ""


MARK = 8.0  # lato di un riferimento (mm): 6 × 6 quadretti
MARK_GAP = 3.0  # spazio libero intorno ai riferimenti


def marker_bits(marker_id):
    """Quadretti (6 × 6, riga 0 in alto) del riferimento: True = da incidere. Riferimenti ArUco 4×4 della
    libreria OpenCV (licenza Apache-2.0), generati al momento: nessuna immagine copiata."""
    import cv2

    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    img = cv2.aruco.generateImageMarker(d, int(marker_id), 6, borderBits=1)
    return [[bool(img[i, j] == 0) for j in range(6)] for i in range(6)]


def layout(spec: TestSpec):
    """Posizioni (coordinate piano, mm) di griglia, etichette e riferimenti. Usato per incidere e per leggere la foto."""
    lab = 8.0 if spec.labels else 0.0
    pitch = spec.cell + spec.gap
    W = lab + spec.cols * pitch - spec.gap
    H = lab + spec.rows * pitch - spec.gap + (7.0 if spec.title else 0.0)
    use_marks = bool(spec.markers) and spec.mode == "fill" and spec.content is None
    if use_marks:
        x0c = spec.x0 + MARK + MARK_GAP + 3.0
        y0c = spec.y0 + MARK + MARK_GAP + 4.0
    else:
        x0c, y0c = spec.x0, spec.y0
    L = SimpleNamespace(lab=lab, pitch=pitch, W=W, H=H, x0c=x0c, y0c=y0c, gx0=x0c + lab, gy0=y0c + lab, marks=[],
                        outer=None)
    if use_marks:
        xa, ya = spec.x0, spec.y0
        xb = x0c + W + MARK_GAP + MARK
        yb = y0c + H + MARK_GAP + MARK
        L.outer = (xa, ya, xb, yb)
        # 0 in basso a sinistra, 1 in basso a destra, 2 in alto a destra, 3 in alto a sinistra
        L.marks = [(0, xa, ya), (1, xb - MARK, ya), (2, xb - MARK, yb - MARK), (3, xa, yb - MARK)]
    return L


def cell_rect(spec, L, r, c):
    """(x, y, lato) del quadrato riga r (potenza) colonna c (velocità)."""
    return (L.gx0 + c * L.pitch, L.gy0 + r * L.pitch, spec.cell)


def marker_corners(mx, my):
    """Angoli del riferimento nell'ordine di OpenCV (alto-sinistra, alto-destra, basso-destra, basso-sinistra)."""
    return [(mx, my + MARK), (mx + MARK, my + MARK), (mx + MARK, my), (mx, my)]


def marker_settings(spec):
    """Potenza e velocità dei riferimenti: un quadrato scuro ma non il più bruciato della griglia."""
    powers = _steps(spec.p_min, spec.p_max, spec.rows)
    speeds = _steps(spec.s_min, spec.s_max, spec.cols)
    cells = sorted((p / max(s, 1.0), p, s) for p in powers for s in speeds)
    _, p, s = cells[min(len(cells) - 1, int(round((len(cells) - 1) * 0.8)))]
    return p, s


def power_label(p):
    """0.20.6: potenza scritta sul test (rapporto FLC-20261118-0900-681F: con passi non interi usciva «33.3333%» e i
    numeri si sovrapponevano). Intera; un decimale solo sotto il 10 % quando serve (2.5%)."""
    v = round(float(p), 1) if p < 10 else round(float(p))
    return f"{v:g}%"


def speed_label(s_mm_min):
    """0.20.6: velocità scritta sul test, nell'unità scelta, senza decimali lunghi: intera, un decimale solo sotto
    10 mm/s («41.7» → «42», «1666.67» → «1667», «7.5» resta)."""
    from .. import units

    v = units.to_shown(float(s_mm_min))
    v = round(v, 1) if v < 10 else round(v)
    return f"{v:g}"


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
    L = layout(spec)
    outer = spec
    spec = replace(spec, x0=L.x0c, y0=L.y0c)  # con i riferimenti la griglia si sposta verso l'interno
    pitch, lab, gx0, gy0, W, H = L.pitch, L.lab, L.gx0, L.gy0, L.W, L.H

    off = tuple(getattr(profile, "wcs_offset", (0.0, 0.0))) if getattr(profile, "no_g55", False) else (0.0, 0.0)

    def mp(bx, by):
        mx, my = profile.to_machine(bx, by)
        return mx - off[0], my - off[1]

    w = _Writer(mp, profile.s_max)
    w.raw(f"; FreeLaserCut — test materiale {spec.rows}×{spec.cols}")
    w.raw("G90 G21")
    w.raw("M5 S0")
    if getattr(profile, "no_g55", False):
        w.raw("G54")  # scheda senza G55 (le coordinate tolgono l'offset G54, vedi mp)
    else:
        w.raw("G10 L2 P2 X0 Y0")
        w.raw("G55")
    air_cmd_on, air_cmd_off = profile.air_cmds() if hasattr(profile, "air_cmds") else ("M8", "M9")
    if air_cmd_on:
        w.raw(air_cmd_on)
    w.raw("M4 S0")
    cells = []
    for r, p in enumerate(powers):
        for c, s in enumerate(speeds):
            x = gx0 + c * pitch
            y = gy0 + r * pitch
            cells.append((p / max(s, 1.0), p, s, x, y))
    cells.sort()  # dal più leggero al più pesante: un problema si vede subito, sui primi quadrati
    cut0 = w.cut
    content = spec.content
    err = content_ok(content)
    if err:
        job.warnings.append(err)
        content = None
    for _, p, s, x, y in cells:
        cs = CutSettings(mode=spec.mode, speed=s, power_max=p, interval=spec.interval, overscan=2.0, bidirectional=True)
        if content is not None and content.kind == "image":
            # 0.22.5: pezzo della foto con le impostazioni del suo livello; del test solo potenza, velocità e passate
            from .gcode import _image_lines

            base = content.cs or CutSettings(mode="image")
            ratio = (base.power_min / base.power_max) if base.power_max > 0 else 0.0
            ci = replace(base, mode="image", speed=s, power_max=p, power_min=min(p, p * ratio), passes=1)
            leaf, tf = _cell_image(content, x, y, spec.cell)
            lines, rot, first = _image_lines(leaf, tf, ci, 64, bed)
            for _ in range(max(1, spec.passes)):
                _emit_scan(w, lines, rot, ci, bed, 6.0, first_forward=first, scan_fix=rot == (1.0, 0.0))
            continue
        if content is not None:
            polys = _cell_shape_polys(content, x, y, spec.cell)
        else:
            polys = [geom.Poly([(x, y), (x + spec.cell, y), (x + spec.cell, y + spec.cell), (x, y + spec.cell)], True)]
        for _ in range(max(1, spec.passes)):
            if spec.mode == "line":
                _emit_polys(w, polys, cs)
            else:
                lines, rot = _scanlines(polys, spec.interval, 0.0)
                if lines:  # una forma solo aperta (una linea) non ha niente da riempire
                    _emit_scan(w, [(yy, [(a, b, p) for a, b in segs]) for yy, segs in lines], rot, cs, bed, 6.0)
    kind = spec.mode if content is None or content.kind != "image" else "image"
    job.layers.append(LayerStats(0, "celle", kind, len(cells), w.cut - cut0, 0))
    if spec.labels:
        lc = CutSettings(mode="line", speed=spec.label_speed, power_max=spec.label_power)
        polys = []

        def put(txt, x, y, size=3.0, rot=0.0, align="center", room=None):
            p = textmod.text_path(txt, "futural", size, align=align)
            w_txt = p.boundingRect().width()
            if room and w_txt > room:  # 0.20.6: numero più largo della colonna: si rimpicciolisce, non si sovrappone
                size = max(1.2, size * room / w_txt)
                p = textmod.text_path(txt, "futural", size, align=align)
            tf = QTransform()
            tf.rotate(rot)
            tf = tf * QTransform.fromTranslate(x, y)
            polys.extend(geom.flatten(tf.map(p), 0.02))

        from .. import units

        # 0.20.6: tutte le velocità alla stessa grandezza, la più grande che entra nella colonna; se verrebbero
        # troppo piccole per leggerle, una sì e una no si scrivono su una seconda riga (doppio spazio)
        texts = [speed_label(s) for s in speeds]
        widest = max(textmod.text_path(t, "futural", 2.6, align="center").boundingRect().width() for t in texts)
        size = min(2.6, 2.6 * (pitch - 0.8) / max(widest, 1e-6))
        two_rows = size < 1.8 and len(texts) > 1
        if two_rows:
            size = max(1.2, min(2.6, 2.6 * (2 * pitch - 0.8) / max(widest, 1e-6)))
        right = gx0 + spec.cols * pitch - spec.gap
        for c, t in enumerate(texts):
            half = textmod.text_path(t, "futural", size, align="center").boundingRect().width() / 2
            cx = min(max(gx0 + c * pitch + spec.cell / 2, gx0 + half), right - half)  # mai fuori dal test
            put(t, cx, spec.y0 + (4.6 if two_rows and c % 2 else 1.0), size)
        for r, p in enumerate(powers):
            put(power_label(p), spec.x0 + 5.5, gy0 + r * pitch + spec.cell / 2 - 1.3, 2.6, 0, "right", room=7.0)
        put(units.speed_unit() + " →", gx0 + spec.cols * pitch - spec.gap, spec.y0 - 3.5, 2.2, 0, "right")
        if spec.title:
            put(spec.title, gx0, gy0 + spec.rows * pitch + 1.5, 3.5, 0, "left")
        from .gcode import order_polys

        _emit_polys(w, order_polys(polys, w.pb or (0, 0), False, True), lc)
    if L.marks:
        mp_, ms_ = marker_settings(outer)
        mc = CutSettings(mode="fill", speed=ms_, power_max=mp_, interval=spec.interval, overscan=2.0, bidirectional=True)
        q = MARK / 6.0
        polys = []
        for mid, mx, my in L.marks:
            bits = marker_bits(mid)
            for i in range(6):
                j = 0
                while j < 6:
                    if not bits[i][j]:
                        j += 1
                        continue
                    k = j
                    while k < 6 and bits[i][k]:
                        k += 1
                    y_top = my + MARK - i * q
                    polys.append(geom.Poly([(mx + j * q, y_top - q), (mx + k * q, y_top - q), (mx + k * q, y_top),
                                            (mx + j * q, y_top)], True))
                    j = k
        cut1 = w.cut
        for poly in polys:  # riga per riga: i pezzi di un riferimento si toccano soltanto
            lines, rot = _scanlines([poly], spec.interval, 0.0)
            _emit_scan(w, [(yy, [(a, b, mp_) for a, b in segs]) for yy, segs in lines], rot, mc, bed, 6.0)
        job.layers.append(LayerStats(1, "riferimenti", "fill", len(L.marks), w.cut - cut1, 0))
    if spec.border:
        bc = CutSettings(mode="line", speed=spec.border_speed, power_max=spec.border_power)
        m = 3.0
        if L.outer:
            xa, ya, xb, yb = L.outer
            b = geom.Poly([(xa - m, ya - m), (xb + m, ya - m), (xb + m, yb + m), (xa - m, yb + m)], True)
        else:
            b = geom.Poly([(spec.x0 - m, spec.y0 - m - 4), (spec.x0 + W + m, spec.y0 - m - 4),
                           (spec.x0 + W + m, spec.y0 + H + m), (spec.x0 - m, spec.y0 + H + m)], True)
        _emit_polys(w, [b], bc)
    w.raw("M5 S0")
    if air_cmd_off:
        w.raw(air_cmd_off)
    w.rapid(0.0, 0.0)
    w.raw("G54")
    job.lines = w.lines
    b, mv = w.burn, w.motion
    if b[0] <= b[2]:
        job.bounds = QRectF(b[0], b[1], b[2] - b[0], b[3] - b[1])
    if mv[0] < -0.01 or mv[1] < -0.01 or mv[2] > bed[0] + 0.01 or mv[3] > bed[1] + 0.01:
        job.warnings.append(tr("Il test esce dall'area di lavoro: cambia la posizione"))
    mx0, my0 = profile.to_machine(0.0, 0.0)
    job.out_to_bed = (-mx0 + off[0], -my0 + off[1])
    from .. import gcode_preview

    job.preview = gcode_preview.parse(job.lines, profile=profile)
    job.seconds = job.preview.seconds
    from .gcode import orient_job_preview

    orient_job_preview(job, profile, mp)
    job.gen_ms = (time.time() - t0) * 1000
    return job
