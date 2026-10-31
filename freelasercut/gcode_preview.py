# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Lettura di un file G-code per anteprima, ingombro e stima del tempo.

Interpreta G0/G1/G2/G3, G90/G91, G20/G21, M3/M4/M5, S, F.
Non esegue nulla: serve solo a mostrare cosa farà la macchina.
"""
import math
import re

_WORD = re.compile(r"([A-Za-z])\s*([-+]?\d*\.?\d+)")
MAX_SEGMENTS = 600_000


class Preview:
    def __init__(self):
        self.cut = []  # (x1, y1, x2, y2, power)
        self.travel = []  # (x1, y1, x2, y2)
        self.min_x = self.min_y = math.inf
        self.max_x = self.max_y = -math.inf
        self.cut_len = 0.0
        self.travel_len = 0.0
        self.seconds = 0.0
        self.lines = 0
        self.max_power = 0.0
        self.decimated = False
        self.segs = []  # tutti i movimenti in ordine: (x0, y0, x1, y1, potenza S, brucia 0/1, feed mm/min)
        self.seg_times = None  # durata di ogni movimento (s), stessa lunghezza di segs

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
    moves = []  # (dx, dy, lunghezza, feed mm/min, rapido?)
    pv = Preview()
    x = y = 0.0
    absolute = True
    scale = 1.0
    feed = 1000.0
    power = 0.0
    laser_on = False
    motion = 0
    for raw in lines:
        line = raw.split(";")[0]
        line = re.sub(r"\(.*?\)", "", line).strip().upper()
        if not line or line.startswith("$") or line.startswith("%"):
            continue
        pv.lines += 1
        words = _WORD.findall(line)
        vals = {}
        for letter, num in words:
            v = float(num)
            if letter == "G":
                g = round(v, 1)
                if g in (0, 1, 2, 3):
                    motion = int(g)
                elif g == 90:
                    absolute = True
                elif g == 91:
                    absolute = False
                elif g == 20:
                    scale = 25.4
                elif g == 21:
                    scale = 1.0
            elif letter == "M":
                m = int(v)
                if m in (3, 4):
                    laser_on = True
                elif m == 5:
                    laser_on = False
            elif letter == "S":
                power = v
                pv.max_power = max(pv.max_power, v)
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
        for qx, qy in pts:
            d = math.hypot(qx - px, qy - py)
            if d > 1e-9:
                moves.append((qx - px, qy - py, d, max(feed, 1.0), motion == 0))
                pv.segs.append((px, py, qx, qy, power if burning else 0.0, 1 if burning else 0,
                                max(feed, 1.0) if motion != 0 else 0.0))
            if burning:
                pv.cut.append((px, py, qx, qy, power))
                pv.cut_len += d
                pv._grow(px, py)
                pv._grow(qx, qy)
            else:
                pv.travel.append((px, py, qx, qy))
                pv.travel_len += d
            px, py = qx, qy
        x, y = nx, ny
    times = []
    pv.seconds = plan_time(moves, ax, ay, rx, ry, jd, times)
    pv.seg_times = times
    if len(pv.cut) > MAX_SEGMENTS:
        step = math.ceil(len(pv.cut) / MAX_SEGMENTS)
        pv.cut = pv.cut[::step]
        pv.decimated = True
    if len(pv.travel) > MAX_SEGMENTS // 4:
        step = math.ceil(len(pv.travel) / (MAX_SEGMENTS // 4))
        pv.travel = pv.travel[::step]
        pv.decimated = True
    return pv


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
