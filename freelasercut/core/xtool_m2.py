# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6, SPERIMENTALE: il lavoro per la xTool M2 scritto direttamente da FreeLaserCut.

Solo per la xTool M2 (codice `JS002`): nessun'altra macchina usa questo linguaggio e nessun'altra parte di
FreeLaserCut lo usa. Non è mai stato provato su una M2 vera e FreeLaserCut non lo manda ancora alla macchina: per ora
serve a confrontare i nostri file con quelli di xTool Studio e a preparare le prove con chi la macchina ce l'ha.

Il linguaggio è G-code in chiaro. L'abbiamo ricavato leggendo i file che xTool Studio 1.10.15 scrive sul computer
quando si preme «Processo» su un nostro disegno di prova (17/11/2026), senza macchina collegata:
- millimetri, coordinate assolute (`G90`), origine in alto a sinistra, Y in giù; `F` in mm/min, `S` da 0 a 1000;
  nessun comando per accendere o spegnere il laser;
- in testa commenti con data, area e, dopo `# JS002 HEAD`, i `# WorkingInfo` (testa, tipi di lavoro, spessore,
  ingombro, potenza massima, velocità minima); poi i comandi per aspiratore e depuratori;
- ogni gruppo di oggetti ha il suo blocco: `M1001` (testa e potenza minima), `M1002` (tipo: 0 linea, 1 taglio,
  2 riempimento, 3 foto), `M32` (accelerazioni), un commento `# blockConfig`;
- la messa a fuoco è un movimento in Z (corsa della testa − 5,7 − spessore del materiale);
- la testa accesa non sta dove sta la tela: xTool Studio toglie uno scostamento che dipende dal modulo laser e da chi
  l'ha costruito (10 W: 9,8 mm in Y). Sulla macchina vera il costruttore del modulo si legge dalla macchina;
- linee e tagli: `G0` fino all'inizio, `G1` con `S` e `F` sul primo tratto; le passate ripetono il tracciato; i
  ponticelli sono tratti a `S0` fra `# breakPointStart` e `# breakPointEnd`;
- riempimenti e foto: righe orizzontali avanti e indietro, 20 mm di corsa a laser spento ai lati, righe spostate di
  un «gioco» che dipende dalla velocità (in un verso in più, nell'altro in meno), e un piccolo movimento in Y a ogni
  riga (0,02 mm in più e poi indietro, poi 0,0001 mm per mm di corsa).

I numeri delle tabelle qui sotto (scostamenti delle teste, gioco per velocità, potenze minime) sono quelli che
xTool Studio usa quando non conosce la macchina: una macchina tarata può averne di suoi.
"""
import copy
import json
import math
import time

from . import gcode, geom
from .document import ImageShape
from .xtool_xs import BITMAP_MODES, CUT, FILL, LASERS, LINE, PASSTHROUGH, PHOTO, TOOL_LAYER, kind_of

DEVICE_CODE = "JS002"
MAKERS = ("TO", "COS")  # costruttore del modulo laser: lo dice la macchina; senza macchina xTool Studio usa «TO»
# modulo e costruttore -> (scostamento x, scostamento y, larghezza, altezza dell'area) in mm
HEAD_PLANE = {
    (10, "TO"): (0.0, 9.8, 426.0, 320.0), (10, "COS"): (0.5, 3.3, 426.0, 320.0),
    (20, "TO"): (0.0, 9.8, 426.0, 320.0), (20, "COS"): (0.5, 3.3, 426.0, 320.0),
    (40, "TO"): (0.5, 22.3, 426.0, 308.0), (40, "COS"): (5.74, 0.0, 426.0, 312.0),
}
HEAD_M1001 = {10: 1, 20: 2, 40: 3}  # numero della testa in M1001
HEAD_INFO = {10: 3, 20: 4, 40: 5}  # numero della testa in «WorkingInfo»
TYPE_CODE = {LINE: 0, CUT: 1, FILL: 2, PHOTO: 3}  # M1002 P e «proc_mode»
# potenza minima (%) per modulo e tipo di lavoro: M1001 la porta moltiplicata per 10
CUTOFF = {10: {LINE: 3.0, FILL: 3.0, PHOTO: 3.0, CUT: 15.0}, 20: {LINE: 3.0, FILL: 3.0, PHOTO: 3.0, CUT: 15.0},
          40: {LINE: 2.5, FILL: 2.5, PHOTO: 2.5, CUT: 15.0}}
Z_DISTANCE = 31.5  # corsa della testa in Z (mm) quando la macchina non ne ha dichiarata una sua
FOCUS_GAP = 5.7  # mm da togliere alla corsa per avere il fuoco sul piano
# gioco fra le righe di andata e di ritorno, per velocità: (da mm/s, a mm/s, gioco all'inizio, gioco alla fine)
BACKLASH = {
    10: ((0, 50, 0.0, 0.05155), (50, 100, 0.05155, 0.0645), (100, 150, 0.0645, 0.08325), (150, 200, 0.08325, 0.09895),
         (200, 250, 0.09895, 0.11245), (250, 300, 0.11245, 0.11895), (300, 350, 0.11895, 0.1169),
         (350, 400, 0.1169, 0.12285), (400, 450, 0.12285, 0.1318), (450, 500, 0.1318, 0.14585),
         (500, 550, 0.14585, 0.15345), (550, 600, 0.15345, 0.1667)),
    20: ((0, 50, 0.0, 0.0483), (50, 100, 0.0483, 0.0443), (100, 150, 0.0443, 0.0617), (150, 200, 0.0617, 0.0691),
         (200, 250, 0.0691, 0.0777), (250, 300, 0.0777, 0.0906), (300, 350, 0.0906, 0.0972),
         (350, 400, 0.0972, 0.1387), (400, 450, 0.1387, 0.1636), (450, 500, 0.1636, 0.1625),
         (500, 550, 0.1625, 0.2019), (550, 600, 0.2019, 0.2172)),
    40: ((0, 50, 0.0, 0.0432), (50, 100, 0.0432, 0.05385), (100, 150, 0.05385, 0.0601), (150, 200, 0.0601, 0.0713),
         (200, 250, 0.0713, 0.084), (250, 300, 0.084, 0.08525), (300, 350, 0.08525, 0.0782),
         (350, 400, 0.0782, 0.087), (400, 450, 0.087, 0.08825), (450, 500, 0.08825, 0.10005),
         (500, 550, 0.10005, 0.1084), (550, 600, 0.1084, 0.1197)),
}
MAX_SPEED = 600.0  # mm/s
OVERSCAN = 20.0  # mm a laser spento prima e dopo ogni riga
OVER_Y = 0.02  # mm: a ogni riga la Y va oltre di tanto e torna
Y_SLOPE, Y_PIVOT, Y_LIMIT = 1e-4, 200.0, 0.02  # la Y che cammina lungo la riga: pendenza, X dove vale 0, limite
Y_EMIT = 0.0005  # mm: la Y si scrive solo sui tratti lungo i quali cambia almeno di tanto
GRAY_LEVELS = 256
FRAME_SPEED = 4800.0  # mm/min: velocità della cornice (80 mm/s)
# Aspiratore e depuratori: le marce che xTool Studio scrive quando non sa quali accessori ci sono. La riga del
# consumo dei filtri (M9043) non la scriviamo: i suoi numeri vengono da un servizio di xTool
ACCESSORIES = ('G198 P85 "M9401 D2 V500"', "M9064 B3", 'G198 P70 "M9064 B3"', 'G198 P78 "M9064 B3"', "M9039 C2",
               'G198 P69 "M9039 C2"', 'G198 P76 "M9039 V50"')
TAIL = ("# JS002 END", "G1 Z0 F1200 S0", "G1 X0 Y0 U0 F18000")


class OutsideArea(ValueError):
    """Il disegno esce dall'area della M2: il lavoro non si scrive."""


# ------------------------------------------------------------------ numeri
def _n(v):
    """Coordinate di linee e tagli: al più 3 decimali, senza zeri in coda (20, 260.2, 51.029)."""
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _f3(v):
    """Coordinate di riempimenti e foto: sempre 3 decimali (155.200)."""
    s = f"{v:.3f}"
    return "0.000" if s == "-0.000" else s


def _js(v):
    """Numero come lo scrive JSON: 20, 0.3, 51.029."""
    v = round(float(v), 3)
    return str(int(v)) if v == int(v) else repr(v)


def backlash(laser_w, speed_mm_s):
    """Gioco (mm) fra andata e ritorno alla velocità data: ogni riga si sposta di tanto, in un verso o nell'altro."""
    v = min(max(float(speed_mm_s), 0.0), MAX_SPEED)
    for a, b, ga, gb in BACKLASH[laser_w]:
        if v <= b:
            return ga + (gb - ga) * (v - a) / (b - a)
    return BACKLASH[laser_w][-1][3]


def focus_z(thickness, z_distance=Z_DISTANCE):
    """Z di lavoro: corsa della testa − 5,7 − spessore del materiale, mai sotto zero."""
    return max(float(z_distance) - FOCUS_GAP - max(float(thickness), 0.0), 0.0)


def y_walk(x, forward):
    """Di quanto la Y si scosta dalla riga alla X data: cresce andando, cala tornando, mai oltre 0,02 mm."""
    d = min(max(Y_SLOPE * (x - Y_PIVOT), -Y_LIMIT), Y_LIMIT)
    return d if forward else -d


# ------------------------------------------------------------------ comandi dei blocchi
def m1001(laser_w, kind, border=False):
    if border:
        return "M1001 S1P1B0"
    cut = CUTOFF[laser_w][kind]
    return f"M1001 S{HEAD_M1001[laser_w]}P0{'A' if kind == CUT else 'B'}{int(round(cut * 10))}"


def m1002(kind):
    return f"M1002 S0P{TYPE_CODE[kind]}"


def m32(kind):
    return "M32 X2300Y2300" if kind in (FILL, PHOTO) else "M32 X1000Y1000"


def _vector_head(laser_w, kind, power, border=False):
    return ["", "# JS002 VECTOR HEAD", "# motion_start", m1001(laser_w, kind, border), m1002(kind), m32(kind), "",
            f'# blockConfig={{"powerFactor": {_js(power / 1000.0)}, "isVector": true}} ']


def _raster_head(laser_w, kind, s_min, s_max, lines_per_mm, mode):
    cfg = (f'{{"powerFactor":{_js(s_max / 1000.0)},"density":"{lines_per_mm:.2f}","power":[{int(s_min)},{int(s_max)}],'
           f'"bitmapMode":{json.dumps(mode)}}}')
    return ["# JS002 BITMAP HEAD", "# motion_start", m1001(laser_w, kind), m1002(kind), m32(kind),
            f"# blockConfig={cfg}", "", ""]


# ------------------------------------------------------------------ linee e tagli
def split_tabs(pts, size, count):
    """Un contorno chiuso (lista di punti, senza ripetere il primo) -> [(punti, acceso)] con i ponticelli spenti.
    Stessi posti e stessa regola di FreeLaserCut per le macchine GRBL (ponticelli a distanze uguali, niente
    ponticelli se il contorno è troppo corto)."""
    ring = list(pts) + [pts[0]]
    if count <= 0 or size <= 0:
        return [(ring, True)]
    seg = [math.dist(ring[i], ring[i + 1]) for i in range(len(ring) - 1)]
    total = sum(seg)
    if total < count * size * 3:
        return [(ring, True)]
    cuts = []
    for k in range(count):
        mid = total * (k + 0.5) / count
        cuts += [mid - size / 2, mid + size / 2]
    marks = [0.0] + cuts + [total]
    out, acc, i, cur = [], 0.0, 0, [ring[0]]
    for j in range(1, len(marks)):
        target = marks[j]
        while i < len(seg) and acc + seg[i] < target - 1e-9:
            acc += seg[i]
            i += 1
            cur.append(ring[i])
        if i < len(seg):
            t = (target - acc) / seg[i] if seg[i] else 0.0
            p = (ring[i][0] + (ring[i + 1][0] - ring[i][0]) * t, ring[i][1] + (ring[i + 1][1] - ring[i][1]) * t)
        else:
            p = ring[-1]
        if math.dist(cur[-1], p) > 1e-9:
            cur.append(p)
        out.append((cur, j % 2 == 1))
        cur = [p]
    return out


def _vector_body(paths, s, f, passes, z, first=True):
    """paths: [[(punti in coordinate macchina, acceso)]] -> righe. Ogni tracciato si ripete per le passate."""
    out = []
    sf = f"S{int(s)}F{int(f)}"
    for parts in paths:
        start = parts[0][0][0]
        g0 = f"G0X{_n(start[0])}Y{_n(start[1])}"
        if first:
            out += [g0, f"G0Z{_f3(z)}"]
            first = False
        for _ in range(max(1, int(passes))):
            out.append(g0)
            for k, (pts, on) in enumerate(parts):
                if not on:
                    out += ["# breakPointStart", f"G0X{_n(pts[0][0])}Y{_n(pts[0][1])}"]
                elif k:
                    out += ["# breakPointEnd", f"G0X{_n(pts[0][0])}Y{_n(pts[0][1])}"]
                word = sf if on else f"S0F{int(f)}"
                for q, p in enumerate(pts[1:]):
                    out.append(f"G1X{_n(p[0])}Y{_n(p[1])}" + (word if q == 0 else ""))
    return out


# ------------------------------------------------------------------ riempimenti e foto
def _raster_body(rows, f, z, shift, over, passes=1):
    """rows: [(Y, [(xa, xb, S)])] dall'alto in basso, tratti da sinistra a destra, coordinate macchina.
    Le righe vanno una in avanti e una indietro; `shift` è il gioco, `over` la corsa a laser spento ai lati."""
    out = [f"G1F{int(f)}S0"]
    x = None
    n = 0
    for _ in range(max(1, int(passes))):
        for y, segs in rows:
            if not segs:
                continue
            fwd = n % 2 == 0
            d = shift if fwd else -shift
            if fwd:
                pts = [(a + d, b + d, s) for a, b, s in segs]
                x_in, x_out = pts[0][0] - over, pts[-1][1] + over
            else:
                pts = [(b + d, a + d, s) for a, b, s in reversed(segs)]
                x_in, x_out = pts[0][0] + over, pts[-1][1] - over
            y0 = y + y_walk(x_in, fwd)
            if n == 0:
                out += [f"G0X{_f3(x_in)}Y{_f3(y0)}", f"G0Z{_f3(z)}", f"G1Y{_f3(y0 + OVER_Y)}S0", f"G1Y{_f3(y0)}"]
            else:
                out += [f"G1Y{_f3(y0 + OVER_Y)}", f"G1Y{_f3(y0)}"]
                if _f3(x_in) != _f3(x):
                    out.append(f"G1X{_f3(x_in)}")
            x = x_in
            cur_s = 0

            def go(nx, s, always_y=False):
                nonlocal x, cur_s
                if _f3(nx) == _f3(x) and not always_y:
                    return  # tratto più corto di un millesimo: non si scrive
                line = f"G1X{_f3(nx)}"
                if always_y or abs(nx - x) * Y_SLOPE >= Y_EMIT:
                    line += f"Y{_f3(y + y_walk(nx, fwd))}"
                if s != cur_s:
                    line += f"S{int(s)}"
                    cur_s = s
                out.append(line)
                x = nx

            if over > 0:
                go(pts[0][0], 0, always_y=True)
            for a, b, s in pts:
                if _f3(a) != _f3(x):
                    go(a, 0)
                go(b, s)
            go(x_out, 0, always_y=True)
            n += 1
    return out + [""]


def _overscan(x0, x1, bed_w):
    """Corsa a laser spento: 20 mm, meno se l'oggetto è più vicino di così a un lato dell'area."""
    return max(0.0, min(OVERSCAN, x0, bed_w - x1))


# ------------------------------------------------------------------ il lavoro
def _header(when, version, bed_w, bed_h):
    t = time.localtime(when if when is not None else time.time())
    return [time.strftime("# date=%Y_%m_%d_%H_%M_%S", t), f"# version={version}", "# algorithmVersion=",
            f'# gc={{"size":{{"w":{_js(bed_w)},"h":{_js(bed_h)}}}}}', '# gc={"offset":{"x":0,"y":0}}',
            '# gc={"start":{"x":0,"y":0.0000}}', '# gc={"keys":["x","y"],"rm":1,"is3DMode":false}', "# timeConfig=",
            "G90", "G0 F3000", ""]


def _working_info(head, modes, thickness, bbox, max_s, min_f):
    box = "[" + ",".join(_js(v) for v in bbox) + "]"
    return [f'# WorkingInfo={{"head":{head}}}',
            '# WorkingInfo={"proc_mode":[' + ",".join(str(m) for m in sorted(modes)) + "]}",
            f'# WorkingInfo={{"thickness":{round(max(float(thickness), 0.0), 1):.1f}}}',
            f'# WorkingInfo={{"process_bbox":{box}}}',
            f'# WorkingInfo={{"max_power":{max(0, min(100, int(round(max_s / 10.0))))}}}',
            f'# WorkingInfo={{"min_speed":{max(0, int(round(min_f / 60.0)))}}}']


def _collect(doc, shapes, report):
    """{livello: [(foglia, trasformazione)]} con le stesse esclusioni del progetto per xTool Studio."""
    by_layer = {}
    for s in shapes:
        if s.hidden:
            continue
        for leaf, tf in s.leaves():
            if leaf.hidden:
                continue
            cs = doc.layer(leaf.layer)
            image = isinstance(leaf, ImageShape)
            if (leaf.layer >= TOOL_LAYER or not cs.output or image != (cs.mode == "image")
                    or (image and doc.images.get(leaf.image_id) is None)):
                report["skipped"].append((leaf.layer, leaf.kind))
                continue
            by_layer.setdefault(leaf.layer, []).append((leaf, tf))
    return by_layer


def plan(doc, shapes=None, laser_w=10, cut_layers=None, maker="TO"):
    """Il lavoro prima di diventare testo: -> (blocchi, resoconto).
    Un blocco è un dizionario: kind, layer, speed (mm/min), s_min, s_max, passes, box (ingombro sulla tela) e, per
    linee e tagli, `paths` [[(punti, acceso)]]; per riempimenti e foto `rows` [(Y, [(xa, xb, S)])], `step` (mm fra le
    righe), `mode` (nome del modo immagine). Le coordinate di tracciati e righe sono quelle della tela (origine in alto
    a sinistra, Y in giù), senza lo scostamento della testa."""
    if laser_w not in LASERS or (laser_w, maker) not in HEAD_PLANE:
        raise ValueError("laser_w")
    _ox, _oy, bw, bh = HEAD_PLANE[(laser_w, maker)]
    shapes = list(doc.shapes if shapes is None else shapes)
    report = {"layers": [], "skipped": [], "notes": [], "outside": 0, "bed": (bw, bh)}
    by_layer = _collect(doc, shapes, report)
    blocks = []
    cur = (0.0, bh)  # la testa parte dall'angolo in alto a sinistra

    def canvas(p):
        return p[0], bh - p[1]

    def note(text):
        if text not in report["notes"]:
            report["notes"].append(text)

    for cs in doc.used_layers():
        items = by_layer.get(cs.index)
        if not items:
            continue
        kind = kind_of(cs, cut_layers)
        speed = min(max(float(cs.speed), 60.0), MAX_SPEED * 60.0)
        s_max = int(round(min(max(cs.power_max, 0.0), 100.0) * 10))
        base = {"kind": kind, "layer": cs.index, "speed": speed, "s_min": 0, "s_max": s_max,
                "passes": max(1, int(cs.passes))}
        n0 = len(blocks)
        if kind == PHOTO:
            flat = copy.copy(cs)
            flat.image_start = "top"
            if cs.image_start != "top":
                note("image_start")
            step = 25.4 / max(cs.dpi, 10.0)
            for leaf, tf in items:
                leaf._doc_image = doc.images.get(leaf.image_id)
                lines, _rot, _first = gcode._image_lines(leaf, tf, flat, GRAY_LEVELS, (bw, bh))
                rows = [(bh - y, [(a, b, int(round(p * 10))) for a, b, p in segs]) for y, segs in lines]
                rows = [(y, [g for g in segs if g[2] > 0]) for y, segs in rows]
                rows = [r for r in rows if r[1]]
                if not rows:
                    continue
                r = tf.map(leaf.local_path()).boundingRect()
                s_min = int(round(cs.power_min * 10)) if cs.dither == "grayscale" else 0
                blocks.append({**base, "rows": rows, "step": step, "s_min": min(s_min, s_max),
                               "mode": BITMAP_MODES.get(cs.dither, PASSTHROUGH),
                               "box": (r.left(), bh - r.bottom(), r.right(), bh - r.top())})
        else:
            polys = gcode._polys_of(items)
            if not polys:
                continue
            xs = [p.bounds() for p in polys]
            box = (min(b[0] for b in xs), bh - max(b[3] for b in xs), max(b[2] for b in xs),
                   bh - min(b[1] for b in xs))
            if kind == FILL:
                if cs.mode == "offset_fill":
                    note("offset_fill")
                if abs(cs.angle) > 1e-9 or cs.crosshatch:
                    note("fill_angle")
                step = max(float(cs.interval), 0.01)
                lines, _rot = gcode._scanlines(polys, step, 0.0)
                rows = [(bh - y, [(a, b, s_max) for a, b in segs]) for y, segs in reversed(lines)]
                if rows:
                    blocks.append({**base, "rows": rows, "step": step, "mode": "grayscale", "box": box})
            else:
                if cs.kerf:
                    closed = gcode._orient([p for p in polys if p.closed])
                    polys = geom.offset(closed, cs.kerf / 2.0, "miter") + [p for p in polys if not p.closed]
                ordered = gcode.order_polys(polys, cur, True, True)
                paths = []
                for p in ordered:
                    if len(p.pts) < 2:
                        continue
                    if p.closed:
                        parts = split_tabs(p.pts, cs.tab_size, cs.tab_count) if cs.tabs else [(p.pts + [p.pts[0]], True)]
                    else:
                        parts = [(list(p.pts), True)]
                    paths.append([([canvas(q) for q in pts], on) for pts, on in parts])
                    cur = p.pts[0] if p.closed else p.pts[-1]
                if paths:
                    blocks.append({**base, "paths": paths, "box": box})
        if len(blocks) > n0:
            report["layers"].append((cs.index, kind, len(items)))
    for b in blocks:
        x0, y0, x1, y1 = b["box"]
        if x0 < -1e-6 or y0 < -1e-6 or x1 > bw + 1e-6 or y1 > bh + 1e-6:
            report["outside"] += 1
    return blocks, report


def build(doc, shapes=None, laser_w=10, thickness=0.0, cut_layers=None, maker="TO", z_distance=Z_DISTANCE,
          accessories=True, when=None, app_version=""):
    """-> (righe del lavoro, resoconto). Il piano di FreeLaserCut (origine in basso a sinistra, Y in su) va sull'area
    della M2 con lo stesso angolo in basso a sinistra, come nel progetto per xTool Studio.
    Se qualcosa esce dall'area solleva OutsideArea: un lavoro che esce non si scrive.
    resoconto: {"layers": [(livello, tipo, n. oggetti)], "skipped": [...], "notes": [...], "outside": 0,
    "bed": (larghezza, altezza), "box": ingombro sulla tela, "z": Z di lavoro}."""
    blocks, report = plan(doc, shapes, laser_w, cut_layers, maker)
    ox, oy, bw, bh = HEAD_PLANE[(laser_w, maker)]
    if report["outside"]:
        raise OutsideArea(report["outside"])
    if not blocks:
        raise ValueError("empty")
    z = focus_z(thickness, z_distance)
    box = (min(b["box"][0] for b in blocks), min(b["box"][1] for b in blocks), max(b["box"][2] for b in blocks),
           max(b["box"][3] for b in blocks))
    report.update(box=box, z=z)
    out = _header(when, f"FreeLaserCut {app_version}".strip(), bw, bh)
    out += ["# JS002 HEAD", "G0 X0 Y0 U0 F7200"]
    out += _working_info(HEAD_INFO[laser_w], {TYPE_CODE[b["kind"]] for b in blocks}, thickness, box,
                         max(b["s_max"] for b in blocks), min(b["speed"] for b in blocks))
    if accessories:
        out += list(ACCESSORIES)
    out.append("")
    for b in blocks:
        if "paths" in b:
            paths = [[([(x - ox, y - oy) for x, y in pts], on) for pts, on in parts] for parts in b["paths"]]
            out += _vector_head(laser_w, b["kind"], b["s_max"])
            out += _vector_body(paths, b["s_max"], b["speed"], b["passes"], z)
        else:
            rows = [(y - oy, [(a - ox, c - ox, s) for a, c, s in segs]) for y, segs in b["rows"]]
            if out[-1] != "":
                out.append("")
            out += _raster_head(laser_w, b["kind"], b["s_min"], b["s_max"], 1.0 / b["step"], b["mode"])
            out += _raster_body(rows, b["speed"], z, backlash(laser_w, b["speed"] / 60.0),
                                _overscan(b["box"][0], b["box"][2], bw), b["passes"])
    out += list(TAIL)
    return out, report


def frame(box, laser_w=10, thickness=0.0, maker="TO", speed=FRAME_SPEED, offset=True):
    """La cornice: il rettangolo dell'ingombro (sulla tela) percorso a potenza zero con la testa alzata (Z 0).
    `offset`: con il laser a luce debole il punto che si vede è quello che inciderà, quindi lo scostamento della
    testa si toglie come nel lavoro; xTool Studio senza macchina (mirino sulla telecamera) non lo toglie."""
    ox, oy = HEAD_PLANE[(laser_w, maker)][:2] if offset else (0.0, 0.0)
    x0, y0, x1, y1 = box
    ring = [(x0 - ox, y0 - oy), (x1 - ox, y0 - oy), (x1 - ox, y1 - oy), (x0 - ox, y1 - oy), (x0 - ox, y0 - oy)]
    out = ["", "# JS002 HEAD"] + _working_info(HEAD_INFO[laser_w] if offset else 0, (), thickness, box, 0, speed)
    out += ["", ""] + _vector_head(laser_w, LINE, 0, border=True)[1:]
    out += _vector_body([[(ring, True)]], 0, speed, 1, 0.0)
    return out + [TAIL[0]]


def export_gcode(doc, path, frame_path=None, **kw):
    """Scrive il lavoro (e, se chiesto, la cornice) solo dopo averlo preparato tutto. -> resoconto."""
    lines, report = build(doc, **kw)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    if frame_path:
        fr = frame(report["box"], kw.get("laser_w", 10), kw.get("thickness", 0.0), kw.get("maker", "TO"))
        with open(frame_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(fr) + "\n")
    report["lines"] = len(lines)
    return report
