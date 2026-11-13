# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Generatore di G-code per GRBL in modalità laser.

Da documento + profilo macchina a righe G-code, con:
  - modalità di livello: linea, riempimento (scansione), riempimento offset, immagine;
  - ottimizzazione percorsi: fori interni prima dei contorni, vicino-più-vicino,
    punto di partenza migliore sulle forme chiuse, verso migliore sulle linee aperte;
  - overscan che non esce MAI dall'area di lavoro (niente allarmi da finecorsa);
  - partenza: coordinate assolute / posizione attuale / origine utente, con ancoraggio a 9 punti;
  - aria per livello (M8/M9), passate, ponticelli (tab), compensazione del kerf.
"""
import math
import time
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform

from . import burn_curve, geom, imaging
from .document import Document, ImageShape
from freelasercut.i18n import tr  # noqa: E402

ANCHOR_NAMES = ["basso-sinistra", "basso-centro", "basso-destra", "centro-sinistra", "centro",
                "centro-destra", "alto-sinistra", "alto-centro", "alto-destra"]


def flip_preview(pv, fx, fy):
    """Ribalta un'anteprima letta dal G-code sugli assi invertiti (piano = -uscita + offset su quell'asse)."""
    if pv is None or not (fx or fy):
        return pv
    import numpy as np

    for arr, xs, ys in ((pv.segs, (0, 2), (1, 3)), (pv.cut, (0, 2), (1, 3)), (pv.travel, (0, 2), (1, 3))):
        if arr is None or not len(arr):
            continue
        if fx:
            arr[:, list(xs)] = -arr[:, list(xs)]
        if fy:
            arr[:, list(ys)] = -arr[:, list(ys)]
    if fx:
        pv.min_x, pv.max_x = -pv.max_x, -pv.min_x
    if fy:
        pv.min_y, pv.max_y = -pv.max_y, -pv.min_y
    return pv


def orient_job_preview(job, profile, out_at):
    """Con un asse invertito l'anteprima va ribaltata e l'offset è l'uscita del punto 0 del piano su quell'asse."""
    fx, fy = bool(getattr(profile, "invert_x", False)), bool(getattr(profile, "invert_y", False))
    if not (fx or fy) or job.preview is None:
        return
    flip_preview(job.preview, fx, fy)
    o0 = out_at(0.0, 0.0)
    ox, oy = job.out_to_bed
    job.out_to_bed = (o0[0] if fx else ox, o0[1] if fy else oy)


TOOL_LAYER = 30  # come ui.editor.TOOL_LAYER: da qui in su sono livelli strumenti


@dataclass
class JobOptions:
    start_from: str = "absolute"  # absolute | current | origin
    anchor: int = 0  # 0..8 per current / origin
    current_pos: tuple = (0.0, 0.0)  # posizione della testa, coordinate piano (per "current")
    work_origin: tuple = (0.0, 0.0)  # origine utente, coordinate piano (per "origin")
    laser_cmd: str = "M4"
    finish: str = "origin"  # origin | stay
    optimize: bool = True
    inner_first: bool = True
    only_ids: object = None  # set di id: solo la selezione
    raster_gap_g1: float = 8.0  # mm: buchi più corti in riempimento/immagine si percorrono con G1 S0
    gray_levels: int = 64
    set_g55: bool = True  # azzera G55 (sistema "assoluto" di FreeLaserCut) se non già fatto
    no_g55: bool = False  # scheda senza G55: coordinate assolute in G54, togliendo l'offset G54 attuale
    g54_offset: tuple = (0.0, 0.0)  # offset G54 della scheda (WCO) quando no_g55
    name: str = ""
    rotary: object = None  # dict: kind (roller | chuck), mm_per_rev, roller_d, object_d — None = piano normale
    # 0.17.2: foto con punti molto fitti e velocità alta: unisce i punti vicini in tratti più lunghi (meno comandi),
    # solo nei livelli dove la porta non ce la farebbe (vedi stream_vmax)
    compact_raster: bool = False


@dataclass
class LayerStats:
    index: int
    name: str
    mode: str
    items: int = 0
    cut_mm: float = 0.0
    lines: int = 0
    speed: float = 0.0  # mm/min del livello (limitata al massimo della macchina)
    power: float = 0.0  # potenza massima del livello, %


# ======================================================================= flusso dei comandi (0.17.2)
# Con le foto ogni cambio di potenza lungo la riga è un comando G-code. Se i comandi sono più corti di quanto la porta
# riesce a mandarne in un secondo, la scheda svuota la coda e la testa va a scatti (segnalato a 10000 mm/min con il
# dithering). La stima è prudente ma semplice: byte al secondo della porta (10 bit per byte, il 90% utile, meno i
# rapporti di stato) diviso i byte di un comando, per la lunghezza dei comandi nelle righe più fitte della foto.
STREAM_BYTES = 13  # byte di un comando tipico di una foto a toni di grigio («X118.3 S512.5» + a capo)
STREAM_BYTES_DOTS = 10  # con il dithering la potenza è una sola: comandi più corti («X118.3 S0»)
STREAM_MIN_CMDS = 8  # righe con meno comandi non contano (bordi, righe quasi vuote)
COMPACT_MAX = 6  # al massimo 6 punti uniti in un gruppo


def stream_vmax(seg_mm, baud, bytes_per_cmd=STREAM_BYTES):
    """Velocità (mm/min) oltre la quale una porta a 'baud' non manda abbastanza in fretta comandi lunghi seg_mm."""
    if not seg_mm or seg_mm <= 0 or not baud or baud <= 0:
        return math.inf
    cmds_s = max(baud / 10.0 * 0.9 - 300.0, 100.0) / max(float(bytes_per_cmd), 4.0)
    return cmds_s * seg_mm * 60.0


def _dense_seg(lines):
    """Lunghezza (mm) dei comandi nelle righe fitte di una foto: la mediana fra le righe con almeno
    STREAM_MIN_CMDS comandi. 0 = nessuna riga fitta (nessun problema di flusso)."""
    ls = []
    for _y, segs in lines:
        if len(segs) < STREAM_MIN_CMDS // 2:
            continue
        cmds = len(segs) + sum(1 for a, b in zip(segs, segs[1:]) if abs(b[0] - a[1]) > 1e-9)
        if cmds < STREAM_MIN_CMDS:
            continue
        ext = abs(max(segs[-1][1], segs[0][0]) - min(segs[-1][1], segs[0][0]))
        if ext > 0:
            ls.append(ext / cmds)
    return float(np.percentile(ls, 50)) if ls else 0.0


def _block_mean(a, k, axis):
    """Media di k punti vicini lungo axis (l'ultimo gruppo può essere più corto)."""
    a = np.asarray(a, dtype=float)
    t = a if axis == 1 else a.T
    h, w = t.shape
    m = -(-w // k)
    pad = np.zeros((h, m * k))
    pad[:, :w] = t
    cnt = np.full(m, float(k))
    if w % k:
        cnt[-1] = w % k
    out = pad.reshape(h, m, k).sum(axis=2) / cnt[None, :]
    return out if axis == 1 else out.T


def _compact_rows(a, k, right_first, lead=0):
    """_compact su righe già allineate al gruppo: a (h, w) → stesse dimensioni. lead: punti finti (spenti) all'inizio."""
    h, w = a.shape
    m = -(-w // k)
    pad = np.zeros((h, m * k), dtype=float)
    pad[:, :w] = a
    blk = pad.reshape(h, m, k)
    c = (blk > 0).sum(axis=2)
    pval = np.where(c > 0, blk.sum(axis=2) / np.maximum(c, 1), 0.0)
    right = (np.arange(m) % 2 == 0) == right_first
    if w % k:
        right[-1] = False  # l'ultimo gruppo è incompleto: a sinistra, così non esce dalla foto
    if lead:
        right[0] = True  # il primo gruppo comincia con punti finti: a destra, sui punti veri
    start = np.where(right[None, :], k - c, 0)
    idx = np.arange(k)[None, None, :]
    mask = (idx >= start[..., None]) & (idx < (start + c)[..., None])
    return np.where(mask, pval[..., None], 0.0).reshape(h, m * k)[:, :w]


def _compact(power, k, axis=1):
    """Unisce i punti vicini lungo la riga (axis = verso di scansione): ogni gruppo di k punti diventa un tratto solo,
    lungo quanto i punti accesi del gruppo e con la loro potenza media (stessa quantità di bruciato, quindi stessi
    toni). I gruppi si attaccano a coppie (uno a destra, il successivo a sinistra), così due gruppi vicini fanno un
    tratto unico. L'inizio dei gruppi cambia da una riga all'altra (sempre uguale per la stessa foto), altrimenti si
    vedrebbero righe verticali. Meno comandi per riga; si perdono solo i dettagli più fini di k punti lungo la riga."""
    k = int(k)
    if k <= 1:
        return power
    a = np.asarray(power, dtype=float)
    a = a if axis == 1 else a.T
    h, w = a.shape
    shifts = np.random.default_rng(1729).integers(0, 2 * k, size=h)
    out = np.zeros_like(a)
    for sh in range(2 * k):
        rows = np.nonzero(shifts == sh)[0]
        if not len(rows):
            continue
        o = sh % k
        part = np.zeros((len(rows), w + o))
        part[:, o:] = a[rows]
        out[rows] = _compact_rows(part, k, sh < k, o)[:, o:]
    return out if axis == 1 else out.T


def compact_factor(seg_mm, step_mm, speed, baud, bytes_per_cmd=STREAM_BYTES, spread=False):
    """Quanti punti unire perché i comandi bastino alla velocità data (1 = non serve).
    spread: dithering rifatto su punti più lunghi (i comandi si allungano di circa k volte); altrimenti i punti si
    uniscono in tratti lunghi almeno k punti."""
    vmax = stream_vmax(seg_mm, baud, bytes_per_cmd)
    if speed <= vmax * 1.05 or step_mm <= 0:
        return 1
    ratio = speed * 1.15 / vmax
    k = math.ceil(ratio) if spread else max(math.ceil(ratio), math.ceil(seg_mm * ratio / step_mm))
    return int(max(2, min(COMPACT_MAX, k)))


def compact_spreads(dither):
    """Con questi metodi la compattazione rifà il dithering su punti più lunghi (vedi _image_lines)."""
    return dither not in ("grayscale", "halftone", "threshold")


@dataclass
class GcodeJob:
    lines: list = field(default_factory=list)
    bounds: object = None  # QRectF in coordinate piano (dove brucerà davvero, overscan incluso)
    out_to_bed: tuple = (0.0, 0.0)  # piano = uscita + offset (per l'anteprima)
    motion_bounds: object = None  # dove passa la testa (trasferimenti e overscan inclusi)
    warnings: list = field(default_factory=list)
    layers: list = field(default_factory=list)
    seconds: float = 0.0
    gen_ms: float = 0.0
    rotary_k: float = 1.0  # rotativo: Y macchina = riferimento + (Y piano - riferimento) × k
    rotary_ref: tuple = (0.0, 0.0)  # punto di riferimento sul piano (ancoraggio del disegno)
    preview: object = None  # gcode_preview.Preview delle righe generate (coordinate di uscita)
    # 0.17.2: per ogni livello Immagine {index, label, speed, seg (mm), bytes, compact (punti uniti, 1 = no)}
    stream: list = field(default_factory=list)

    def choppy(self, baud):
        """[(livello, velocità, velocità massima per la porta, punti uniti)] dove la testa può andare a scatti.
        baud None (Wi-Fi, simulatore): nessuna stima."""
        out = []
        if not baud:
            return out
        for st in self.stream:
            vmax = stream_vmax(st.get("seg", 0.0), baud, st.get("bytes", STREAM_BYTES))
            if st.get("speed", 0.0) > vmax * 1.05:
                out.append((st.get("label", ""), st["speed"], vmax, st.get("compact", 1)))
        return out

    @property
    def compacted(self):
        return any(st.get("compact", 1) > 1 for st in self.stream)


def rotary_scale(r):
    """Fattore dell'asse Y per il rotativo. A rulli conta il diametro del rullo (l'oggetto ruota alla stessa
    velocità di superficie); a mandrino conta il diametro dell'oggetto."""
    if not r:
        return 1.0
    d = float(r.get("roller_d", 0) if r.get("kind", "roller") == "roller" else r.get("object_d", 0))
    mm = float(r.get("mm_per_rev", 0))
    if d <= 0 or mm <= 0:
        return 1.0
    return mm / (math.pi * d)


def _fmt(v):
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class _Writer:
    """Scrive G-code compatto (omette coordinate, F e S che non cambiano) e misura
    sia dove il laser brucia sia dove la testa passa (overscan e trasferimenti inclusi)."""

    def __init__(self, out_map, s_max):
        self.lines = []
        self.map = out_map
        self.s_max = s_max
        self.x = self.y = None  # ultima posizione in coordinate di USCITA
        self.pb = None  # ultima posizione in coordinate PIANO
        self.f = None
        self.s = None
        self.mode = None
        self.rot_k = 1.0  # rotativo: la F si corregge perché la velocità sulla superficie resti quella scelta
        self.cut = 0.0
        self.scan_offset = None  # f(velocità) -> sfasamento mm fra andata e ritorno (None = nessuna correzione)
        self.burn = [math.inf, math.inf, -math.inf, -math.inf]
        self.motion = [math.inf, math.inf, -math.inf, -math.inf]

    @staticmethod
    def _grow(box, x, y):
        box[0] = min(box[0], x)
        box[1] = min(box[1], y)
        box[2] = max(box[2], x)
        box[3] = max(box[3], y)

    def raw(self, text):
        self.lines.append(text)

    def _xy(self, ox, oy):
        parts = []
        if self.x is None or abs(ox - self.x) >= 1e-4:
            parts.append("X" + _fmt(ox))
        if self.y is None or abs(oy - self.y) >= 1e-4:
            parts.append("Y" + _fmt(oy))
        return parts

    def rapid(self, bx, by):
        ox, oy = self.map(bx, by)
        xy = self._xy(ox, oy)
        if not xy:
            return
        self.lines.append("G0 " + " ".join(xy))
        self.mode = 0
        self.x, self.y = ox, oy
        self._grow(self.motion, bx, by)
        self.pb = (bx, by)

    def feed(self, bx, by, power_pct, speed):
        # chiamata milioni di volte per le foto: stesso risultato della versione "leggibile", con meno passaggi
        ox, oy = self.map(bx, by)
        x, y = self.x, self.y
        parts = [] if self.mode == 1 else ["G1"]
        if x is None or abs(ox - x) >= 1e-4:
            parts.append("X" + _fmt(ox))
        if y is None or abs(oy - y) >= 1e-4:
            parts.append("Y" + _fmt(oy))
        if len(parts) == (0 if self.mode == 1 else 1):
            return  # nessun movimento
        s = round((power_pct if power_pct > 0.0 else 0.0) / 100.0 * self.s_max, 1)
        if s != self.s:
            parts.append("S" + _fmt(s))
            self.s = s
        if self.rot_k != 1.0 and self.pb is not None and x is not None:
            ld = math.dist(self.pb, (bx, by))
            if ld > 1e-9:
                speed = round(speed * math.dist((x, y), (ox, oy)) / ld)
        if speed != self.f:
            parts.append("F" + _fmt(speed))
            self.f = speed
        self.lines.append(" ".join(parts))
        pb = self.pb
        if s > 0 and pb is not None:
            self.cut += math.dist(pb, (bx, by))
            b = self.burn
            for px, py in (pb, (bx, by)):
                if px < b[0]:
                    b[0] = px
                if py < b[1]:
                    b[1] = py
                if px > b[2]:
                    b[2] = px
                if py > b[3]:
                    b[3] = py
        m = self.motion
        if bx < m[0]:
            m[0] = bx
        if by < m[1]:
            m[1] = by
        if bx > m[2]:
            m[2] = bx
        if by > m[3]:
            m[3] = by
        self.mode = 1
        self.x, self.y = ox, oy
        self.pb = (bx, by)

    def track(self, bx, by):  # compatibilità: la posizione è già tracciata da rapid/feed
        pass


# ======================================================================= raccolta
def _collect(doc, opts):
    """{indice_livello: [(leaf, tf)]} solo forme visibili (e selezionate, se richiesto)."""
    out = {}
    for s in doc.shapes:
        if s.hidden:
            continue
        if opts.only_ids is not None and s.id not in opts.only_ids:
            continue
        for leaf, tf in s.leaves():
            if leaf.hidden:
                continue
            out.setdefault(leaf.layer, []).append((leaf, tf))
    return out


def _polys_of(items, tol=geom.FLATTEN_TOL):
    polys = []
    for k, (leaf, tf) in enumerate(items):
        if isinstance(leaf, ImageShape):
            continue
        if not k & 31:
            _tick()
        polys.extend(geom.flatten(tf.map(leaf.local_path()), tol))
    return polys


def _depths(polys):
    """Profondità di annidamento di ogni contorno chiuso (0 = esterno).

    0.19.2: stesso risultato di prima, ma con aree e ingombri calcolati una volta sola; tolto il limite dei 3000
    contorni, oltre il quale la profondità era sempre 0 (fori trattati da contorni esterni: kerf dalla parte sbagliata)."""
    n = len(polys)
    depth = [0] * n
    if n < 2:
        return depth
    closed = np.array([p.closed for p in polys], bool)
    outer = np.nonzero(closed)[0]
    if not len(outer):
        return depth
    areas = np.array([abs(p.area()) for p in polys], float)
    box = np.array([p.bounds() for p in polys], float).reshape(n, 4)
    oa, ob = areas[outer], box[outer]
    for i, inner in enumerate(polys):
        if not i & 63:
            _tick()
        x0, y0, x1, y1 = box[i]
        m = (ob[:, 0] <= x0) & (ob[:, 1] <= y0) & (ob[:, 2] >= x1) & (ob[:, 3] >= y1)
        if closed[i]:
            m &= oa > areas[i]
        for j in outer[m]:
            j = int(j)
            if j != i and geom.contains(polys[j], inner):
                depth[i] += 1
    return depth


def _orient(polys):
    """Esterni antiorari, fori orari: serve a Clipper per kerf e offset corretti."""
    d = _depths(polys)
    out = []
    for p, k in zip(polys, d):
        if not p.closed:
            out.append(p)
            continue
        ccw = p.area() > 0
        want_ccw = k % 2 == 0
        out.append(p if ccw == want_ccw else p.reversed())
    return out


# ======================================================================= ottimizzazione
# ---------------------------------------------------------------- segni di vita durante i calcoli lunghi
# 0.19.2: chi prepara un lavoro (la finestra principale) può passare a generate() una funzione «tick» da chiamare
# spesso: tiene viva la finestra, mostra l'avanzamento e, se l'utente annulla, solleva un'eccezione che interrompe
# il calcolo. Senza tick (prove, comandi senza finestra) non cambia niente.
_TICK = None


def _tick():
    if _TICK is not None:
        _TICK()


def order_polys(polys, start=(0.0, 0.0), inner_first=True, optimize=True):
    """Ordina le polilinee riducendo i trasferimenti; i fori prima dei contorni che li contengono.

    0.19.2: aree e ingombri si calcolano una volta sola e il test «sta dentro» (geom.contains) si fa solo dove
    l'ingombro del contorno contiene quello dell'altro. Prima ogni tracciato veniva confrontato con tutti gli altri
    ricalcolando ogni volta l'area (2000 tracciati: 8 milioni di aree, circa 6 s) e oltre i 3000 tracciati i fori
    non venivano più messi prima dei contorni, senza avviso. L'ordine che esce è lo stesso di prima."""
    n = len(polys)
    if n == 0 or not optimize:
        return polys
    children = [[] for _ in range(n)]
    if inner_first:
        areas = np.array([abs(p.area()) for p in polys], float)
        box = np.array([p.bounds() for p in polys], float).reshape(n, 4)
        outer = np.array([j for j, p in enumerate(polys) if p.closed and len(p.pts) >= 3], int)
        if len(outer):
            oa, ob = areas[outer], box[outer]
            for i, inner in enumerate(polys):
                if not i & 63:
                    _tick()
                x0, y0, x1, y1 = box[i]
                near = outer[(oa > areas[i]) & (ob[:, 0] <= x0) & (ob[:, 1] <= y0) & (ob[:, 2] >= x1) & (ob[:, 3] >= y1)]
                for j in near:
                    j = int(j)
                    if j != i and geom.contains(polys[j], inner):
                        children[j].append(i)
    remaining_children = np.array([len(c) for c in children], int)
    parents = [[] for _ in range(n)]
    for j, cs in enumerate(children):
        for i in cs:
            parents[i].append(j)
    done = np.zeros(n, bool)
    # punto rappresentativo per la ricerca veloce: inizio o centro
    reps = np.array([[p.pts[0][0], p.pts[0][1]] if not p.closed else
                     [sum(q[0] for q in p.pts) / len(p.pts), sum(q[1] for q in p.pts) / len(p.pts)] for p in polys])
    ends = np.array([[p.pts[-1][0], p.pts[-1][1]] for p in polys])
    cur = np.array(start, float)
    out = []
    for step in range(n):
        if not step & 63:
            _tick()
        avail = (~done) & (remaining_children == 0)
        if not avail.any():
            avail = ~done
        idx = np.nonzero(avail)[0]
        d1 = np.hypot(reps[idx, 0] - cur[0], reps[idx, 1] - cur[1])
        d2 = np.hypot(ends[idx, 0] - cur[0], ends[idx, 1] - cur[1])
        dmin = np.minimum(d1, d2)
        k = int(idx[int(np.argmin(dmin))])
        p = polys[k]
        if p.closed:
            pts = np.array(p.pts)
            vi = int(np.argmin(np.hypot(pts[:, 0] - cur[0], pts[:, 1] - cur[1])))
            p = geom.Poly(p.pts[vi:] + p.pts[:vi], True)
            last = p.pts[0]
        else:
            if math.dist(p.pts[-1], tuple(cur)) < math.dist(p.pts[0], tuple(cur)):
                p = p.reversed()
            last = p.pts[-1]
        out.append(p)
        done[k] = True
        for par in parents[k]:
            remaining_children[par] -= 1
        cur = np.array(last, float)
    return out


# ======================================================================= modalità
def _apply_tabs(polys, size, count):
    out = []
    for p in polys:
        if not p.closed or count <= 0 or size <= 0:
            out.append(p)
            continue
        pts = p.pts + [p.pts[0]]
        seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        total = sum(seg)
        if total < count * size * 3:
            out.append(p)
            continue
        gaps = [(total * (k + 0.5) / count - size / 2, total * (k + 0.5) / count + size / 2) for k in range(count)]

        def at(dist):
            acc = 0.0
            for i, L in enumerate(seg):
                if acc + L >= dist:
                    t = (dist - acc) / L if L else 0
                    return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t), i
                acc += L
            return pts[-1], len(seg) - 1

        bounds = [0.0] + [g for gap in gaps for g in gap] + [total]
        for a, b in zip(bounds[0::2], bounds[1::2]):
            if b - a < 1e-3:
                continue
            pa, ia = at(a)
            pb, ib = at(b)
            part = [pa] + pts[ia + 1:ib + 1] + [pb]
            out.append(geom.Poly(part, False))
    return out


def _scanlines(polys, interval, angle):
    """Riempimento a scansione (pari-dispari). Ritorna [(y, [(xa, xb), ...])] nel sistema ruotato."""
    closed = [p for p in polys if p.closed and len(p.pts) >= 3]
    if not closed:
        return [], None
    a = math.radians(angle)
    ca, sa = math.cos(-a), math.sin(-a)
    edges = []
    for p in closed:
        pts = np.array(p.pts)
        rx = pts[:, 0] * ca - pts[:, 1] * sa
        ry = pts[:, 0] * sa + pts[:, 1] * ca
        x1, y1 = rx, ry
        x2, y2 = np.roll(rx, -1), np.roll(ry, -1)
        keep = np.abs(y2 - y1) > 1e-12
        edges.append(np.stack([x1[keep], y1[keep], x2[keep], y2[keep]], axis=1))
    E = np.concatenate(edges) if edges else np.zeros((0, 4))
    if not len(E):
        return [], None
    ymin_e = np.minimum(E[:, 1], E[:, 3])
    ymax_e = np.maximum(E[:, 1], E[:, 3])
    # righe a metà passo su una griglia globale: mai esattamente su un bordo, forme diverse allineate fra loro
    y0 = (math.ceil(ymin_e.min() / interval - 0.5) + 0.5) * interval
    y1 = ymax_e.max()
    order = np.argsort(ymin_e)
    E, ymin_e, ymax_e = E[order], ymin_e[order], ymax_e[order]
    lines = []
    y = y0
    while y < y1:
        hi = np.searchsorted(ymin_e, y, side="right")
        cand = slice(0, hi)
        m = ymax_e[cand] > y
        if m.any():
            e = E[cand][m]
            t = (y - e[:, 1]) / (e[:, 3] - e[:, 1])
            xs = np.sort(e[:, 0] + t * (e[:, 2] - e[:, 0]))
            segs = [(float(xs[i]), float(xs[i + 1])) for i in range(0, len(xs) - 1, 2) if xs[i + 1] - xs[i] > 1e-4]
            if segs:
                lines.append((y, segs))
        y += interval
    return lines, (math.cos(a), math.sin(a))


def _clamp_dir(px, py, dx, dy, dist, bed):
    """Allunga (px,py) di dist lungo (dx,dy) senza uscire dal piano."""
    if dist <= 0:
        return px, py
    tmax = dist
    bx, by = bed
    for p, d, lo, hi in ((px, dx, 0.0, bx), (py, dy, 0.0, by)):
        if d > 1e-12:
            tmax = min(tmax, (hi - p) / d)
        elif d < -1e-12:
            tmax = min(tmax, (lo - p) / d)
    tmax = max(0.0, tmax)
    return px + dx * tmax, py + dy * tmax


def _emit_scan(w, lines, rot, cs, bed, gap_g1, power_of=None, first_forward=True, scan_fix=True):
    """Emette righe di scansione: [(y, [(xa, xb, potenza%), ...])] nel sistema ruotato di 'rot'.
    first_forward=False: la prima riga va nel verso opposto a 'rot' (es. righe verticali che partono dall'alto).
    scan_fix=False: niente correzione avanti/indietro (è misurata lungo X: non vale per le righe verticali)."""
    cos_a, sin_a = rot
    # correzione della scansione avanti e indietro: ogni riga si sposta di metà sfasamento contro il proprio verso,
    # così andata e ritorno si incontrano (il laser si accende e si spegne con un piccolo ritardo)
    half = 0.0
    if cs.bidirectional and scan_fix and w.scan_offset is not None:
        half = 0.5 * float(w.scan_offset(cs.speed))
    shift = [0.0]

    if half:
        bx_, by_ = bed

        def back(x, y):
            x += shift[0]
            px, py = x * cos_a - y * sin_a, x * sin_a + y * cos_a
            return min(max(px, 0.0), bx_), min(max(py, 0.0), by_)
    else:
        def back(x, y):
            return x * cos_a - y * sin_a, x * sin_a + y * cos_a

    dxu, dyu = cos_a, sin_a  # direzione di scansione nel piano
    forward = bool(first_forward)
    for row_n, (y, segs) in enumerate(lines):
        if not row_n & 15:
            _tick()
        if not segs:
            continue
        if not forward:
            segs = [(b, a, p) for a, b, p in reversed(segs)]
        sgn = 1.0 if forward else -1.0
        ddx, ddy = dxu * sgn, dyu * sgn
        shift[0] = -sgn * half
        sx, sy = back(segs[0][0], y)
        ox, oy = _clamp_dir(sx, sy, -ddx, -ddy, cs.overscan, bed)
        w.rapid(ox, oy)
        w.track(ox, oy)
        w.feed(sx, sy, 0.0, cs.speed)
        w.track(sx, sy)
        for k, (xa, xb, pw) in enumerate(segs):
            ax, ay = back(xa, y)
            bxx, byy = back(xb, y)
            if k > 0:
                gap = abs(xa - segs[k - 1][1])
                if gap < 1e-9:
                    pass  # pixel attaccato al precedente: il movimento a S0 sarebbe lungo zero (feed non scrive nulla)
                elif gap <= gap_g1:
                    w.feed(ax, ay, 0.0, cs.speed)
                else:
                    ex, ey = _clamp_dir(*back(segs[k - 1][1], y), ddx, ddy, cs.overscan, bed)
                    w.feed(ex, ey, 0.0, cs.speed)
                    ox, oy = _clamp_dir(ax, ay, -ddx, -ddy, cs.overscan, bed)
                    w.rapid(ox, oy)
                    w.feed(ax, ay, 0.0, cs.speed)
                w.track(ax, ay)
            w.feed(bxx, byy, pw, cs.speed)
            w.track(bxx, byy)
        ex, ey = _clamp_dir(*back(segs[-1][1], y), ddx, ddy, cs.overscan, bed)
        w.feed(ex, ey, 0.0, cs.speed)
        w.track(ex, ey)
        if cs.bidirectional:
            forward = not forward


def _emit_polys(w, polys, cs):
    for k, p in enumerate(polys):
        if not k & 63:
            _tick()
        w.rapid(*p.pts[0])
        w.track(*p.pts[0])
        for q in p.pts[1:]:
            w.feed(q[0], q[1], cs.power_max, cs.speed)
            w.track(*q)
        if p.closed:
            w.feed(p.pts[0][0], p.pts[0][1], cs.power_max, cs.speed)
            w.track(*p.pts[0])


def _fill_clusters(polys, grouping):
    if grouping != "each":
        return [polys]
    closed = [p for p in polys if p.closed]
    d = _depths(closed)
    outers = [i for i, k in enumerate(d) if k % 2 == 0]
    clusters = {i: [closed[i]] for i in outers}
    for i, k in enumerate(d):
        if k % 2 == 1:
            # foro: va con l'esterno più piccolo che lo contiene
            best, best_a = None, math.inf
            for j in outers:
                if geom.contains(closed[j], closed[i]) and abs(closed[j].area()) < best_a:
                    best, best_a = j, abs(closed[j].area())
            if best is not None:
                clusters[best].append(closed[i])
    return list(clusters.values())


def _emit_fill(w, polys, cs, bed, opts, grouping):
    angles = [cs.angle] + ([cs.angle + 90.0] if cs.crosshatch else [])
    for ang in angles:
        clusters = _fill_clusters(polys, grouping)
        if grouping == "each" and len(clusters) > 1:
            # ordine dei gruppi: vicino-più-vicino a partire dalla posizione attuale
            start = w.pb or (0.0, 0.0)
            reps = [geom.Poly([((min(p.bounds()[0] for p in c) + max(p.bounds()[2] for p in c)) / 2,
                                (min(p.bounds()[1] for p in c) + max(p.bounds()[3] for p in c)) / 2)], False) for c in clusters]
            order = order_polys(reps, start, False, True)
            idx = [next(i for i, r in enumerate(reps) if r.pts[0] == o.pts[0]) for o in order]
            clusters = [clusters[i] for i in idx]
        for cluster in clusters:
            lines, rot = _scanlines(cluster, cs.interval, ang)
            lines = [(y, [(a, b, cs.power_max) for a, b in segs]) for y, segs in lines]
            if lines:
                _emit_scan(w, lines, rot, cs, bed, opts.raster_gap_g1)


def _best_grouping(w, polys, cs, bed, opts, profile):
    """Riempimento 'Automatico': prova entrambe le strategie e sceglie la più rapida (stima con le accelerazioni)."""
    closed = [p for p in polys if p.closed]
    if len(closed) < 2:
        return "together"
    from .. import gcode_preview

    best, best_t = "together", math.inf
    for g in ("together", "each"):
        tmp = _Writer(w.map, w.s_max)
        tmp.scan_offset = w.scan_offset
        tmp.x, tmp.y, tmp.pb, tmp.f, tmp.s, tmp.mode = w.x, w.y, w.pb, w.f, w.s, w.mode
        _emit_fill(tmp, polys, cs, bed, opts, g)
        t = gcode_preview.plan_time(_moves_of(tmp.lines, w.x, w.y), profile.accel_x, profile.accel_y,
                                    profile.max_rate_x, profile.max_rate_y, profile.junction_dev)
        if t < best_t:
            best, best_t = g, t
    return best


def _moves_of(lines, x0, y0):
    """Righe G0/G1 assolute -> movimenti per la stima dei tempi."""
    x = x0 or 0.0
    y = y0 or 0.0
    feed = 1000.0
    rapid = False
    out = []
    for l in lines:
        parts = l.split()
        if not parts:
            continue
        nx, ny = x, y
        for p in parts:
            c, v = p[0], p[1:]
            if c == "G":
                rapid = v == "0"
            elif c == "X":
                nx = float(v)
            elif c == "Y":
                ny = float(v)
            elif c == "F":
                feed = float(v)
        d = math.hypot(nx - x, ny - y)
        if d > 0:
            out.append((nx - x, ny - y, d, feed, rapid))
        x, y = nx, ny
    return out


def _runs(vals, origin, step, shrink):
    """Una riga (o colonna) di potenze -> tratti [(da, a, potenza%)]; i buchi spenti li percorre _emit_scan a S0."""
    nz = np.nonzero(vals > 0)[0]
    if not len(nz):
        return []
    segs = []
    j, end = nz[0], nz[-1]
    while j <= end:
        v = vals[j]
        k = j
        while k + 1 <= end and vals[k + 1] == v:
            k += 1
        a = origin + (j - 0.5) * step
        b = origin + (k + 0.5) * step
        if v > 0:
            if shrink and b - a > 2 * shrink + 0.02:
                a += shrink
                b -= shrink
            segs.append((a, b, float(v)))
        j = k + 1
    return segs


def _image_lines(leaf, tf, cs, s_levels, bed, compact=1):
    """Una forma immagine -> (righe [(y, [(xa, xb, potenza%), ...])], rotazione, verso della prima riga).

    cs.image_start sceglie da dove parte: «top» dall'alto (righe orizzontali, come sempre), «bottom» dal basso,
    «left» / «right» con righe verticali da sinistra / da destra, la prima riga dall'alto verso il basso.
    I punti incisi sono gli stessi: cambia solo l'ordine in cui la testa li percorre."""
    img = leaf._doc_image if hasattr(leaf, "_doc_image") else None
    if img is None:
        return [], (1.0, 0.0), True
    dark = imaging.to_dark(img)
    step = 25.4 / max(cs.dpi, 10.0)
    r = tf.map(leaf.local_path()).boundingRect()
    x0 = math.floor(r.left() / step) * step + step / 2
    y0 = math.floor(r.top() / step) * step + step / 2
    nx = max(1, int(math.ceil((r.right() - x0) / step)) + 1)
    ny = max(1, int(math.ceil((r.bottom() - y0) / step)) + 1)
    inv, ok = tf.inverted()
    if not ok:
        return [], (1.0, 0.0), True
    grid = imaging.sample_to_grid(dark, inv, leaf.w, leaf.h, x0, y0, nx, ny, step)
    grid = imaging.adjust(grid, leaf.brightness, leaf.contrast, leaf.gamma, cs.negative)
    cell_px = max(cs.halftone_cell / step, 2.0)
    start = getattr(cs, "image_start", "top")
    scan_axis = 0 if start in ("left", "right") else 1
    spread = compact > 1 and compact_spreads(cs.dither)
    if spread:  # 0.17.2: dithering su punti lunghi k lungo la riga (la diffusione dell'errore li mette dove servono)
        grid = _block_mean(grid, int(compact), scan_axis)
    vals = imaging.dither(grid[::-1].copy(), cs.dither, cell_px, cs.halftone_angle,
                          getattr(cs, "halftone_size", 100.0))[::-1]  # dithering dall'alto
    if spread:
        vals = np.repeat(vals, int(compact), axis=scan_axis)[:ny, :nx]
    pmin, pmax = cs.power_min, cs.power_max
    if cs.dither == "grayscale":
        q = np.round(vals * (s_levels - 1)) / (s_levels - 1)
        curve = burn_curve.get(getattr(cs, "burn_curve", ""))
        if curve is not None and curve.ok:  # materiale imparato: grigi = scurezze equidistanti sul legno vero
            power = np.where(q > 0, curve.tone_map(q, cs.speed, step, pmin, pmax, cs.passes), 0.0)
        else:
            power = np.where(q > 0, pmin + (pmax - pmin) * q, 0.0)
    else:
        power = np.where(vals > 0.5, pmax, 0.0)
    shrink = cs.dot_correction / 2.0 if cs.dither != "grayscale" else 0.0
    if compact > 1 and not spread:  # 0.17.2: toni di grigio, retino, soglia: punti vicini uniti in tratti
        power = _compact(power, int(compact), axis=scan_axis)
    lines = []
    if start in ("left", "right"):
        # righe verticali: nel sistema ruotato di 90° la riga è a v = −x e i tratti corrono lungo y
        cols = range(nx) if start == "left" else range(nx - 1, -1, -1)
        for j in cols:
            segs = _runs(power[:, j], y0, step, shrink)
            if segs:
                lines.append((-(x0 + j * step), segs))
        return lines, (0.0, 1.0), False
    rows = range(ny - 1, -1, -1) if start != "bottom" else range(ny)  # di partenza dall'alto verso il basso
    for i in rows:
        segs = _runs(power[i], x0, step, shrink)
        if segs:
            lines.append((y0 + i * step, segs))
    return lines, (1.0, 0.0), True


# ======================================================================= lavoro
def generate(doc: Document, profile, opts: JobOptions = None, tick=None) -> GcodeJob:
    """Prepara il lavoro. tick (facoltativo): funzione senza argomenti chiamata spesso durante il calcolo; può
    sollevare un'eccezione per interromperlo (Annulla). Vedi ui/busy.py."""
    global _TICK
    before, _TICK = _TICK, tick  # una preparazione dentro l'altra (rara) non perde il tick di quella esterna
    try:
        return _generate(doc, profile, opts)
    finally:
        _TICK = before


def _generate(doc: Document, profile, opts: JobOptions = None) -> GcodeJob:
    t0 = time.time()
    opts = opts or JobOptions()
    job = GcodeJob()
    bed = (profile.bed_x, profile.bed_y)
    by_layer = _collect(doc, opts)
    # 0.18.16: i livelli strumenti (T1, dal 30 in su: contorno del materiale, guide, numeri dei pannelli) non si
    # incidono mai. Prima finivano nel lavoro come un livello qualsiasi, e il contorno del materiale veniva tagliato
    layers = [cs for cs in doc.used_layers() if cs.output and cs.index in by_layer and cs.index < TOOL_LAYER]
    if not layers:
        job.warnings.append(tr("Niente da incidere: nessuna forma su livelli con uscita attiva"))
        return job
    # ingombro del disegno (per l'ancoraggio)
    drawn = QRectF()
    for cs in layers:
        for leaf, tf in by_layer[cs.index]:
            r = tf.map(leaf.local_path()).boundingRect()
            drawn = r if drawn.isNull() else drawn.united(r)
    anchor = geom.rect_anchor(drawn, opts.anchor)
    # posizionamento: piano -> uscita
    if opts.start_from == "absolute":
        place = (0.0, 0.0)
        off = tuple(opts.g54_offset) if opts.no_g55 else (0.0, 0.0)

        def out_map(bx, by):
            mx, my = profile.to_machine(bx, by)
            return mx - off[0], my - off[1]
        mx0, my0 = profile.to_machine(0.0, 0.0)
        job.out_to_bed = (-mx0 + off[0], -my0 + off[1])
    else:
        target = opts.current_pos if opts.start_from == "current" else opts.work_origin
        place = (target[0] - anchor.x(), target[1] - anchor.y())

        sx, sy = profile.axis_sign() if hasattr(profile, "axis_sign") else (1.0, 1.0)

        def out_map(bx, by):  # relative alla testa: con un asse invertito il verso si capovolge
            return sx * (bx - anchor.x()), sy * (by - anchor.y())
        job.out_to_bed = (target[0], target[1])

    # il disegno viene "spostato" sul piano di place: genero già in coordinate piano finali
    pl_tf = QTransform.fromTranslate(place[0], place[1])

    def placed_map(bx, by):
        return out_map(bx - place[0], by - place[1])

    rot_k = rotary_scale(opts.rotary)
    if rot_k != 1.0:  # rotativo: l'asse Y gira l'oggetto, si scala attorno all'ancoraggio del disegno
        ref = (anchor.x() + place[0], anchor.y() + place[1])
        _, ref_oy = placed_map(*ref)
        flat_map = placed_map

        def placed_map(bx, by):
            ox, oy = flat_map(bx, by)
            return ox, ref_oy + (oy - ref_oy) * rot_k
        job.rotary_k, job.rotary_ref = rot_k, ref
        job.warnings.append(tr("Rotativo attivo: asse Y × {0:.4f} (in anteprima il disegno resta com'è sul piano)", rot_k))
    w = _Writer(placed_map, profile.s_max)
    if getattr(profile, "scan_offsets", None):
        w.scan_offset = profile.scan_offset
    w.rot_k = rot_k
    title = opts.name or doc.name
    w.raw(f"; FreeLaserCut — {title}")
    w.raw(f"; macchina: {profile.name} · {profile.bed_x:g}×{profile.bed_y:g} mm · S max {profile.s_max:g}")
    w.raw(f"; partenza: {opts.start_from}" + ("" if opts.start_from == "absolute" else f" · ancoraggio {ANCHOR_NAMES[opts.anchor]}"))
    # 0.18.5: i comandi dell'aria sono quelli del profilo (M8, M7 o nessuno), non più M8/M9 fissi
    air_cmd_on, air_cmd_off = profile.air_cmds() if hasattr(profile, "air_cmds") else ("M8", "M9")
    w.raw("G90 G21")
    w.raw("M5 S0")
    if air_cmd_off:
        w.raw(air_cmd_off)
    if opts.start_from == "absolute" and opts.no_g55:
        w.raw("G54")  # la scheda non ha G55: coordinate già corrette per l'offset G54
    elif opts.start_from == "absolute":
        if opts.set_g55:
            w.raw("G10 L2 P2 X0 Y0")
        w.raw("G55")
    elif opts.start_from == "current":
        w.raw("G92 X0 Y0")
    else:
        w.raw("G54")
    w.raw(f"{opts.laser_cmd} S0")
    current_cmd = opts.laser_cmd
    cur = opts.current_pos if opts.start_from == "current" else (0.0, 0.0)
    air_on = False
    for cs in layers:
        _tick()
        items = [(leaf, tf * pl_tf) for leaf, tf in by_layer[cs.index]]
        st = LayerStats(cs.index, cs.label(), cs.mode, items=len(items),
                        speed=min(cs.speed, profile.max_rate_x, profile.max_rate_y), power=cs.power_max)
        cut_before = w.cut
        n_before = len(w.lines)
        if cs.speed > min(profile.max_rate_x, profile.max_rate_y):
            job.warnings.append(tr("{0}: velocità {1:g} oltre il massimo della macchina, verrà limitata", cs.label(), cs.speed))
        if cs.power_max <= 0:
            job.warnings.append(tr("{0}: potenza 0%, il livello non inciderà nulla", cs.label()))
        if cs.mode == "image" and cs.dither == "grayscale" and getattr(cs, "burn_curve", "") and \
                burn_curve.get(cs.burn_curve) is None:
            job.warnings.append(tr("{0}: il materiale imparato scelto non c'è (eliminato o su un altro computer), toni senza correzione",
                                   cs.label()))
        if cs.air != air_on:
            if air_cmd_on:
                w.raw(air_cmd_on if cs.air else air_cmd_off)
            air_on = cs.air
        w.raw(f"; livello {cs.label()} · {cs.mode} · {cs.speed:g} mm/min · {cs.power_max:g}% · {cs.passes}×")
        layer_cmd = "M3" if getattr(cs, "constant_power", False) else opts.laser_cmd
        if layer_cmd != current_cmd:
            w.raw(f"{layer_cmd} S0")
            w.s = 0.0
            current_cmd = layer_cmd
        if cs.mode == "image":
            imgs = [(l, t) for l, t in items if isinstance(l, ImageShape)]
            if len(imgs) < len(items):
                job.warnings.append(tr("{0}: in modalità Immagine le forme vettoriali vengono ignorate", cs.label()))
            segs_l, k_l = [], 1
            for leaf, tf in imgs:
                leaf._doc_image = doc.images.get(leaf.image_id)
                lines, rot, first = _image_lines(leaf, tf, cs, opts.gray_levels, bed)
                seg = _dense_seg(lines)
                if opts.compact_raster and seg > 0:
                    k = compact_factor(seg, 25.4 / max(cs.dpi, 10.0), st.speed, getattr(profile, "baud", 115200),
                                       STREAM_BYTES if cs.dither == "grayscale" else STREAM_BYTES_DOTS,
                                       compact_spreads(cs.dither))
                    if k > 1:
                        lines, rot, first = _image_lines(leaf, tf, cs, opts.gray_levels, bed, compact=k)
                        seg = _dense_seg(lines)
                        k_l = max(k_l, k)
                if seg > 0:
                    segs_l.append(seg)
                for _ in range(max(1, cs.passes)):
                    _emit_scan(w, lines, rot, cs, bed, opts.raster_gap_g1, first_forward=first,
                               scan_fix=rot == (1.0, 0.0))
            if segs_l:
                new_lines = w.lines[n_before:]
                nb = (sum(len(x) for x in new_lines) / len(new_lines) + 1.0) if new_lines else STREAM_BYTES
                job.stream.append({"index": cs.index, "label": cs.label(), "speed": st.speed, "seg": min(segs_l),
                                   "bytes": nb, "compact": k_l, "dither": cs.dither})
        else:
            if any(isinstance(l, ImageShape) for l, _ in items):
                job.warnings.append(tr("{0}: le foto su un livello che non è in modalità Immagine non vengono incise: "
                                       "mettile su un livello Immagine", cs.label()))
            polys = _polys_of(items)
            if cs.mode == "line":
                if cs.kerf:
                    closed = _orient([p for p in polys if p.closed])
                    polys = geom.offset(closed, cs.kerf / 2.0, "miter") + [p for p in polys if not p.closed]
                if cs.tabs:
                    polys = _apply_tabs(polys, cs.tab_size, cs.tab_count)
                for _ in range(max(1, cs.passes)):
                    ordered = order_polys(polys, cur, opts.inner_first, opts.optimize)
                    _emit_polys(w, ordered, cs)
                    if ordered:
                        last = ordered[-1]
                        cur = last.pts[0] if last.closed else last.pts[-1]
            elif cs.mode == "offset_fill":
                closed = _orient([p for p in polys if p.closed])
                rings = []
                k = 0
                layer = closed
                while layer and k < 2000:
                    rings.append(layer)
                    k += 1
                    layer = geom.offset(closed, -cs.interval * k, "round")
                flat = [p for ring in rings for p in ring]
                for _ in range(max(1, cs.passes)):
                    # anelli concentrici: il vicino-più-vicino li percorre già in sequenza
                    _emit_polys(w, order_polys(flat, cur, False, opts.optimize), cs)
            else:  # fill
                if any(not p.closed for p in polys):
                    job.warnings.append(tr("{0}: le linee aperte non si possono riempire e vengono ignorate", cs.label()))
                grouping = cs.fill_grouping
                if grouping == "auto":
                    grouping = _best_grouping(w, polys, cs, bed, opts, profile)
                for _ in range(max(1, cs.passes)):
                    _emit_fill(w, polys, cs, bed, opts, grouping)
        st.cut_mm = w.cut - cut_before
        st.lines = len(w.lines) - n_before
        job.layers.append(st)
    w.raw("M5 S0")
    if air_on and air_cmd_off:
        w.raw(air_cmd_off)
    if opts.finish == "origin":
        # destinazione in coordinate PIANO: casa (assoluto) o punto di ancoraggio (attuale/origine).
        # Con coordinate macchina negative "G0 X0 Y0" porterebbe la testa all'angolo opposto.
        if opts.start_from == "absolute":
            # vicino a casa ma a 10 mm dai finecorsa: arrivare esattamente su 0,0 può far scattare l'interruttore
            # (sul B1 è successo: allarme 1 a pochi mm dall'origine)
            w.rapid(min(10.0, bed[0]), min(10.0, bed[1]))
        else:
            target = opts.current_pos if opts.start_from == "current" else opts.work_origin
            w.rapid(target[0], target[1])
    if opts.start_from == "absolute":
        w.raw("G54")
    elif opts.start_from == "current":
        w.raw("G92.1")
    w.raw("; fine")
    job.lines = w.lines
    b, m = w.burn, w.motion
    if b[0] <= b[2]:
        job.bounds = QRectF(b[0], b[1], b[2] - b[0], b[3] - b[1])
    eps = 0.01
    if m[0] <= m[2] and (m[0] < -eps or m[1] < -eps or m[2] > bed[0] + eps or m[3] > bed[1] + eps):
        job.warnings.insert(0, tr("Il lavoro esce dall'area di lavoro: spostalo o cambia origine"))
    job.motion_bounds = QRectF(m[0], m[1], m[2] - m[0], m[3] - m[1]) if m[0] <= m[2] else None
    job.gen_ms = (time.time() - t0) * 1000
    from .. import gcode_preview

    job.preview = gcode_preview.parse(job.lines, profile=profile)  # riusata dall'interfaccia: una sola lettura
    orient_job_preview(job, profile, placed_map)
    job.seconds = job.preview.seconds
    return job
