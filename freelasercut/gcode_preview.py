# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Lettura di un file G-code per anteprima, ingombro e stima del tempo.

Interpreta G0/G1/G2/G3, G90/G91, G20/G21, M3/M4/M5, S, F.
Non esegue nulla: serve solo a mostrare cosa farà la macchina.
"""
import math
import re
from array import array

import numpy as np

_WORD = re.compile(r"([A-Za-z])\s*([-+]?\d*\.?\d+)")
# righe di scansione delle foto, il caso di gran lunga più frequente: "X12.3 S45", "G1 X0.1 S119 F3000"
_FAST = re.compile(r"(?:G([01]) )?X([-+]?\d*\.?\d+)(?: S([-+]?\d*\.?\d+))?(?: F([-+]?\d*\.?\d+))?")
MAX_SEGMENTS = 600_000


class Preview:
    """Risultato della lettura. I tratti stanno in array numpy compatti (un milione di tratti ≈ 56 MB invece
    di qualche centinaio con le tuple Python): le foto generano facilmente milioni di movimenti."""

    def __init__(self):
        self.cut = np.zeros((0, 5))  # (x1, y1, x2, y2, potenza) — eventualmente diradati, solo per disegnare
        self.travel = np.zeros((0, 4))  # (x1, y1, x2, y2)
        self.min_x = self.min_y = math.inf
        self.max_x = self.max_y = -math.inf
        self.cut_len = 0.0
        self.travel_len = 0.0
        self.seconds = 0.0
        self.lines = 0
        self.max_power = 0.0
        self.decimated = False
        self.segs = np.zeros((0, 7))  # tutti i movimenti in ordine: (x0, y0, x1, y1, potenza S, brucia 0/1, feed mm/min)
        self.seg_times = np.zeros(0)  # durata di ogni movimento (s), stessa lunghezza di segs

    @property
    def has_bounds(self):
        return self.min_x <= self.max_x

    @property
    def width(self):
        return self.max_x - self.min_x if self.has_bounds else 0.0

    @property
    def height(self):
        return self.max_y - self.min_y if self.has_bounds else 0.0

    def _grow(self, x, y):
        self.min_x = min(self.min_x, x)
        self.max_x = max(self.max_x, x)
        self.min_y = min(self.min_y, y)
        self.max_y = max(self.max_y, y)

    def shift(self, dx, dy):
        """Sposta tutta l'anteprima (es. da coordinate di uscita a coordinate piano)."""
        if not (dx or dy):
            return
        for a, cols in ((self.segs, (0, 2)), (self.cut, (0, 2)), (self.travel, (0, 2))):
            if len(a):
                a[:, cols[0]] += dx
                a[:, cols[1]] += dx
                a[:, cols[0] + 1] += dy
                a[:, cols[1] + 1] += dy
        if self.has_bounds:
            self.min_x += dx
            self.max_x += dx
            self.min_y += dy
            self.max_y += dy


def shifted(pv, dx, dy):
    """Copia dell'anteprima spostata: l'originale (usato anche dal piano) resta com'è."""
    import copy

    q = copy.copy(pv)
    q.segs, q.cut, q.travel = pv.segs.copy(), pv.cut.copy(), pv.travel.copy()
    q.shift(dx, dy)
    return q


def parse(lines, travel_rate=6000.0, profile=None):
    """profile: MachineProfile (accelerazioni, velocità massime, $11) per una stima dei tempi realistica."""
    if profile is not None:
        ax, ay = profile.accel_x, profile.accel_y
        rx, ry = profile.max_rate_x, profile.max_rate_y
        jd = profile.junction_dev
    else:
        ax = ay = 1000.0
        rx = ry = travel_rate
        jd = 0.01
    seg = array("d")  # 7 valori per movimento, vedi Preview.segs
    pv = Preview()
    x = y = 0.0
    absolute = True
    scale = 1.0
    feed = 1000.0
    power = 0.0
    laser_on = False
    motion = 0
    n_lines = 0
    max_power = 0.0
    fast = _FAST.fullmatch
    for raw in lines:
        m = fast(raw)
        if m is not None:  # corsia veloce: stesso risultato del caso generale, senza dizionari né regex multiple
            n_lines += 1
            g, xs, ss, fs = m.groups()
            if g is not None:
                motion = int(g)
            if ss is not None:
                power = float(ss)
                if power > max_power:
                    max_power = power
            if fs is not None:
                feed = float(fs) * scale
            nx = float(xs) * scale
            if not absolute:
                nx += x
            d = abs(nx - x)
            if d > 1e-9:
                burning = laser_on and power > 0 and motion != 0
                seg.extend((x, y, nx, y, power if burning else 0.0, 1.0 if burning else 0.0,
                            (feed if feed > 1.0 else 1.0) if motion != 0 else 0.0))
            x = nx
            continue
        line = raw.split(";")[0]
        if "(" in line:
            line = re.sub(r"\(.*?\)", "", line)
        line = line.strip().upper()
        if not line or line.startswith("$") or line.startswith("%"):
            continue
        n_lines += 1
        words = _WORD.findall(line)
        vals = {}
        for letter, num in words:
            v = float(num)
            if letter == "G":
                gg = round(v, 1)
                if gg in (0, 1, 2, 3):
                    motion = int(gg)
                elif gg == 90:
                    absolute = True
                elif gg == 91:
                    absolute = False
                elif gg == 20:
                    scale = 25.4
                elif gg == 21:
                    scale = 1.0
            elif letter == "M":
                mm = int(v)
                if mm in (3, 4):
                    laser_on = True
                elif mm == 5:
                    laser_on = False
            elif letter == "S":
                power = v
                if v > max_power:
                    max_power = v
            elif letter == "F":
                feed = v * scale
            else:
                vals[letter] = v
        if not any(k in vals for k in "XYIJR"):
            continue
        nx = vals.get("X", x / scale if absolute else 0.0) * scale
        ny = vals.get("Y", y / scale if absolute else 0.0) * scale
        if not absolute:
            nx += x
            ny += y
        burning = laser_on and power > 0 and motion != 0
        if motion in (2, 3) and ("I" in vals or "J" in vals or "R" in vals):
            pts = _arc(x, y, nx, ny, vals, scale, motion == 2)
        else:
            pts = [(nx, ny)]
        px, py = x, y
        fv = (feed if feed > 1.0 else 1.0) if motion != 0 else 0.0
        for qx, qy in pts:
            if math.hypot(qx - px, qy - py) > 1e-9:
                seg.extend((px, py, qx, qy, power if burning else 0.0, 1.0 if burning else 0.0, fv))
            px, py = qx, qy
        x, y = nx, ny
    pv.lines = n_lines
    pv.max_power = max_power
    S = np.frombuffer(seg, dtype=np.float64).reshape(-1, 7).copy() if len(seg) else np.zeros((0, 7))
    del seg
    pv.segs = S
    if len(S):
        dx = S[:, 2] - S[:, 0]
        dy = S[:, 3] - S[:, 1]
        L = np.hypot(dx, dy)
        burn = S[:, 5] > 0
        pv.cut_len = float(L[burn].sum())
        pv.travel_len = float(L[~burn].sum())
        if burn.any():
            B = S[burn]
            pv.min_x = float(min(B[:, 0].min(), B[:, 2].min()))
            pv.max_x = float(max(B[:, 0].max(), B[:, 2].max()))
            pv.min_y = float(min(B[:, 1].min(), B[:, 3].min()))
            pv.max_y = float(max(B[:, 1].max(), B[:, 3].max()))
        # feed dei movimenti per la stima: i rapidi usano la velocità massima, gli altri il loro F
        rapid = S[:, 6] == 0
        feed_col = np.where(rapid, 1.0, S[:, 6])
        times = []
        pv.seconds = plan_time_arrays(dx, dy, L, feed_col, rapid, ax, ay, rx, ry, jd, times)
        pv.seg_times = times[0] if times else np.zeros(len(S))
        del dx, dy, L, feed_col, rapid, times
        cut = S[burn][:, :5]
        trav = S[~burn][:, :4]
        if len(cut) > MAX_SEGMENTS:
            cut = cut[::math.ceil(len(cut) / MAX_SEGMENTS)]
            pv.decimated = True
        if len(trav) > MAX_SEGMENTS // 4:
            trav = trav[::math.ceil(len(trav) / (MAX_SEGMENTS // 4))]
            pv.decimated = True
        pv.cut, pv.travel = cut, trav
    return pv


BIG = 60_000  # oltre questi movimenti l'anteprima si disegna come immagine, non tratto per tratto


def rasterize(segs, px_per_mm=8.0, max_px=2400, max_samples=12_000_000, s_max=None):
    """Tratti accesi -> immagini per disegnare anteprime enormi (foto) senza milioni di linee.

    Ritorna (potenza 0..1 float32, indice del tratto int32 con -1 dove non brucia, (x0, y0, w, h) in mm:
    il rettangolo del piano coperto dall'immagine)
    oppure None. La riga 0 delle immagini è in alto (Y massima). L'indice serve al cursore del tempo:
    si mostrano i pixel con indice <= k."""
    S = np.asarray(segs)
    if len(S) == 0:
        return None
    idx = np.nonzero(S[:, 5] > 0)[0]
    if not len(idx):
        return None
    B = S[idx]
    x0 = float(min(B[:, 0].min(), B[:, 2].min()))
    x1 = float(max(B[:, 0].max(), B[:, 2].max()))
    y0 = float(min(B[:, 1].min(), B[:, 3].min()))
    y1 = float(max(B[:, 1].max(), B[:, 3].max()))
    W, H = max(x1 - x0, 1e-3), max(y1 - y0, 1e-3)
    L = np.hypot(B[:, 2] - B[:, 0], B[:, 3] - B[:, 1])
    # risoluzione: quella chiesta, ma senza superare max_px né troppi campioni (2 per pixel lungo i tratti)
    ppm = max(min(px_per_mm, max_px / max(W, H), max_samples / (2.0 * max(float(L.sum()), 1e-6))), 0.5)
    nx, ny = int(math.ceil(W * ppm)) + 1, int(math.ceil(H * ppm)) + 1
    step = 0.5 / ppm
    n = np.maximum(np.ceil(L / step).astype(np.int64), 1) + 1
    rep = np.repeat(np.arange(len(B)), n)
    start = np.repeat(np.cumsum(n) - n, n)
    t = (np.arange(len(rep)) - start) / np.repeat(n - 1, n).clip(1)
    px = np.rint((B[rep, 0] + (B[rep, 2] - B[rep, 0]) * t - x0) * ppm).astype(np.int64).clip(0, nx - 1)
    py = np.rint((y1 - (B[rep, 1] + (B[rep, 3] - B[rep, 1]) * t)) * ppm).astype(np.int64).clip(0, ny - 1)
    flat = py * nx + px
    smax = float(s_max) if s_max else max(float(B[:, 4].max()), 1e-9)
    power = np.zeros(nx * ny, np.float32)
    index = np.full(nx * ny, -1, np.int32)
    power[flat] = (B[rep, 4] / smax).astype(np.float32)  # con più tratti sullo stesso pixel vince l'ultimo
    index[flat] = idx[rep].astype(np.int32)
    # rettangolo coperto esattamente dai pixel (ogni pixel è largo 1/ppm ed è centrato sul suo punto)
    h = 0.5 / ppm
    return power.reshape(ny, nx).clip(0, 1), index.reshape(ny, nx), (x0 - h, y1 + h - ny / ppm, nx / ppm, ny / ppm)


def plan_time_arrays(dx, dy, L, feed, rapid, ax, ay, rx, ry, jd, per_move=None):
    """Come plan_time (stesso modello e stessi numeri), ma con numpy dove si può: con le foto i movimenti
    sono milioni. Restano in Python solo le due passate sequenziali sulle velocità di ingresso."""
    keep = L > 1e-9
    if not keep.all():
        dx, dy, L, feed, rapid = dx[keep], dy[keep], L[keep], feed[keep], rapid[keep]
    m = len(L)
    if m == 0:
        return 0.0
    inf = np.inf
    cx, cy = np.abs(dx) / L, np.abs(dy) / L
    with np.errstate(divide="ignore", invalid="ignore"):
        acc = np.minimum(np.where(cx > 1e-9, ax / cx, inf), np.where(cy > 1e-9, ay / cy, inf))
        rate = np.minimum(np.where(cx > 1e-9, rx / cx, inf), np.where(cy > 1e-9, ry / cy, inf))
    vmax = np.where(rapid, rate, np.minimum(feed, rate)) / 60.0
    ux, uy = dx / L, dy / L
    ventry = np.zeros(m)
    if m > 1:
        cos_t = -(ux[:-1] * ux[1:] + uy[:-1] * uy[1:])
        with np.errstate(divide="ignore", invalid="ignore"):
            sd2 = np.sqrt(0.5 * (1.0 - cos_t))
            vj = np.sqrt(np.minimum(acc[:-1], acc[1:]) * jd * sd2 / (1.0 - sd2))
        vj = np.where(cos_t > 0.999999, 0.0, np.where(cos_t < -0.999999, inf, vj))
        ventry[1:] = np.minimum(np.minimum(vj, vmax[1:]), vmax[:-1])
    ve = ventry.tolist()
    two_al = (2.0 * acc * L).tolist()
    sqrt = math.sqrt
    nxt = 0.0  # alla fine si ferma
    for i in range(m - 1, -1, -1):
        lim = sqrt(nxt * nxt + two_al[i])
        if ve[i] > lim:
            ve[i] = lim
        nxt = ve[i]
    for i in range(m - 1):
        lim = sqrt(ve[i] * ve[i] + two_al[i])
        if ve[i + 1] > lim:
            ve[i + 1] = lim
    v0 = np.asarray(ve)
    v1 = np.append(v0[1:], 0.0)
    da = (vmax * vmax - v0 * v0) / (2.0 * acc)
    dd = (vmax * vmax - v1 * v1) / (2.0 * acc)
    cruise = da + dd <= L
    with np.errstate(invalid="ignore", divide="ignore"):
        t_c = (vmax - v0) / acc + (vmax - v1) / acc + (L - da - dd) / vmax
        peak = np.maximum(np.maximum(np.sqrt(np.maximum((2.0 * acc * L + v0 * v0 + v1 * v1) / 2.0, 0.0)), v0), v1)
        t_p = (peak - v0) / acc + (peak - v1) / acc
    dt = np.where(cruise, t_c, t_p)
    if per_move is not None:
        per_move.append(dt)  # un solo array numpy (niente milioni di float Python)
    return float(dt.sum())


def plan_time(moves, ax, ay, rx, ry, jd, per_move=None):
    """Tempo come lo pianifica GRBL: accelerazione per asse, velocità agli spigoli da junction
    deviation ($11), passata indietro + avanti sulle velocità di ingresso, profili trapezoidali."""
    inf = float("inf")
    L, vmax, acc, ux, uy = [], [], [], [], []
    for dx, dy, l, feed, rapid in moves:
        if l <= 1e-9:
            continue
        cx, cy = abs(dx) / l, abs(dy) / l
        a = min(ax / cx if cx > 1e-9 else inf, ay / cy if cy > 1e-9 else inf)
        rate = min(rx / cx if cx > 1e-9 else inf, ry / cy if cy > 1e-9 else inf)
        v = (rate if rapid else min(feed, rate)) / 60.0
        L.append(l)
        vmax.append(v)
        acc.append(a)
        ux.append(dx / l)
        uy.append(dy / l)
    m = len(L)
    if m == 0:
        return 0.0
    ventry = [0.0] * m
    for i in range(1, m):
        cos_t = -(ux[i - 1] * ux[i] + uy[i - 1] * uy[i])
        if cos_t > 0.999999:
            vj = 0.0  # inversione: si ferma
        elif cos_t < -0.999999:
            vj = inf  # dritto
        else:
            sd2 = math.sqrt(0.5 * (1.0 - cos_t))
            vj = math.sqrt(min(acc[i - 1], acc[i]) * jd * sd2 / (1.0 - sd2))
        ventry[i] = min(vj, vmax[i], vmax[i - 1])
    nxt = 0.0  # alla fine si ferma
    for i in range(m - 1, -1, -1):
        lim = math.sqrt(nxt * nxt + 2.0 * acc[i] * L[i])
        if ventry[i] > lim:
            ventry[i] = lim
        nxt = ventry[i]
    for i in range(m - 1):
        lim = math.sqrt(ventry[i] * ventry[i] + 2.0 * acc[i] * L[i])
        if ventry[i + 1] > lim:
            ventry[i + 1] = lim
    t = 0.0
    for i in range(m):
        v0 = ventry[i]
        v1 = ventry[i + 1] if i + 1 < m else 0.0
        vm, a, l = vmax[i], acc[i], L[i]
        da = (vm * vm - v0 * v0) / (2.0 * a)
        dd = (vm * vm - v1 * v1) / (2.0 * a)
        if da + dd <= l:
            dt = (vm - v0) / a + (vm - v1) / a + (l - da - dd) / vm
        else:
            peak = max(math.sqrt(max((2.0 * a * l + v0 * v0 + v1 * v1) / 2.0, 0.0)), v0, v1)
            dt = (peak - v0) / a + (peak - v1) / a
        t += dt
        if per_move is not None:
            per_move.append(dt)
    return t


def _arc(x0, y0, x1, y1, vals, scale, clockwise):
    if "R" in vals:
        r = vals["R"] * scale
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d == 0 or abs(r) < d / 2:
            return [(x1, y1)]
        h = math.sqrt(max(r * r - d * d / 4, 0))
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        sign = -1 if (clockwise ^ (r < 0)) else 1
        cx = mx - sign * h * dy / d
        cy = my + sign * h * dx / d
    else:
        cx = x0 + vals.get("I", 0) * scale
        cy = y0 + vals.get("J", 0) * scale
    r = math.hypot(x0 - cx, y0 - cy)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if clockwise and sweep >= 0:
        sweep -= 2 * math.pi
    elif not clockwise and sweep <= 0:
        sweep += 2 * math.pi
    n = max(int(abs(sweep) * r / 0.5), 4)
    n = min(n, 720)
    return [(cx + r * math.cos(a0 + sweep * i / n), cy + r * math.sin(a0 + sweep * i / n)) for i in range(1, n)] + [
        (x1, y1)
    ]


def fmt_time(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h} h {m:02d} min" if h else (f"{m} min {s:02d} s" if m else f"{s} s")
