# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.7, funzioni in prova: G-code «del piano», da adattare al laser configurato.

Serve ai programmi esterni (per esempio un ponte che riceve un lavoro preparato per un'altra macchina) che non
conoscono il laser collegato a FreeLaserCut. Il file si riconosce dalla riga «; FreeLaserCut-piano» fra le prime righe
e ha queste regole:
- X e Y in mm sul piano di FreeLaserCut com'è sullo schermo: origine in basso a sinistra, Y in su;
- solo G0 e G1 (assoluti), S da 0 a 1000 = potenza da 0 a 100 %, F in mm/min;
- facoltativa «; potenza-W=<n>»: i watt del laser per cui sono state pensate le potenze. Se il profilo dice i watt
  del laser collegato, la potenza si riporta in proporzione (stessa energia: 40 % di 10 W = 10 % di 40 W), mai oltre
  il 100 %;
- facoltativa «; nome=<testo>».

FreeLaserCut lo trasforma nelle coordinate della macchina con il profilo (assi invertiti, piano ruotato, origine) e
nel sistema «assoluto» dei suoi lavori (G55, o G54 senza G55), con M4 (potenza che segue la velocità). Velocità sopra
il massimo della macchina: si scende al massimo e la potenza si abbassa nella stessa proporzione (stessa energia per
mm). Spostamenti a laser spento fuori dal piano: portati sul bordo. Tratti accesi fuori dal piano: il lavoro non si fa.
"""
import re

from ..grbl import optical_watts

MARK = "; FreeLaserCut-piano"
_WORD = re.compile(r"([GXYSF])\s*(-?\d+(?:\.\d*)?|-?\.\d+)", re.I)
_WATT = re.compile(r";\s*potenza-W\s*=\s*([\d.,]+)", re.I)
_NAME = re.compile(r";\s*nome\s*=\s*(.+)", re.I)
EPS = 0.05  # mm di tolleranza sui bordi


class OutsideBed(ValueError):
    """Tratti accesi fuori dal piano: il lavoro non va fatto."""


def is_plane(lines, look=40):
    return any(str(x).strip().lower().startswith(MARK.lower()) for x in list(lines)[:look])


def meta(lines, look=60):
    w = name = None
    for x in list(lines)[:look]:
        m = _WATT.match(str(x).strip())
        if m:
            try:
                w = float(m.group(1).replace(",", "."))
            except ValueError:
                w = None
        m = _NAME.match(str(x).strip())
        if m:
            name = m.group(1).strip()
    return {"watts": w if w and w > 0 else None, "name": name}


def _f(v):
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def convert(lines, profile, no_g55=False, g54_offset=(0.0, 0.0), set_g55=True):
    """-> (righe per la macchina, resoconto). resoconto: watts_from, watts_to, ratio (fattore di potenza), capped
    (tratti rallentati), clamped (spostamenti portati sul bordo), moves, burn_mm, box (sul piano)."""
    info = meta(lines)
    w_to = optical_watts(getattr(profile, "optical_power", ""))
    ratio = 1.0
    if info["watts"] and w_to:
        ratio = info["watts"] / w_to
    s_max = float(getattr(profile, "s_max", 1000.0) or 1000.0)
    f_max = min(float(getattr(profile, "max_rate_x", 0) or 0), float(getattr(profile, "max_rate_y", 0) or 0)) or None
    bw, bh = float(profile.bed_x), float(profile.bed_y)
    rep = {"watts_from": info["watts"], "watts_to": w_to, "ratio": ratio, "capped": 0, "clamped": 0, "moves": 0,
           "burn_mm": 0.0, "box": None, "name": info["name"], "s_limited": 0}
    air_on, air_off = profile.air_cmds() if hasattr(profile, "air_cmds") else ("M8", "M9")
    _ = air_on
    out = [f"; FreeLaserCut — G-code del piano{(' — ' + info['name']) if info['name'] else ''}",
           f"; macchina: {profile.name} · {bw:g}×{bh:g} mm · S max {s_max:g} · potenza × {ratio:.3f}",
           "G90 G21", "M5 S0"]
    if air_off:
        out.append(air_off)
    if no_g55:
        out.append("G54")
    else:
        if set_g55:
            out.append("G10 L2 P2 X0 Y0")
        out.append("G55")
    out.append("M4 S0")
    ox, oy = (float(g54_offset[0]), float(g54_offset[1])) if no_g55 else (0.0, 0.0)
    g, x, y, s, f = 0, 0.0, 0.0, 0.0, None
    last_s = last_f = None
    box = [None, None, None, None]
    for raw in lines:
        line = str(raw).split(";", 1)[0].split("(", 1)[0].strip()
        if not line:
            continue
        words = {k.upper(): float(v) for k, v in _WORD.findall(line)}
        if not words:
            continue
        if "G" in words:
            gv = int(words["G"])
            if gv not in (0, 1):
                continue  # solo G0 e G1: G90/G21 li mette FreeLaserCut, il resto non si usa
            g = gv
        if "S" in words:
            s = max(0.0, min(1000.0, words["S"]))
        if "F" in words and words["F"] > 0:
            f = words["F"]
        if "X" not in words and "Y" not in words:
            continue
        nx, ny = words.get("X", x), words.get("Y", y)
        burning = g == 1 and s > 0 and (nx, ny) != (x, y)
        if burning:
            for px, py in ((x, y), (nx, ny)):
                if px < -EPS or py < -EPS or px > bw + EPS or py > bh + EPS:
                    raise OutsideBed((px, py))
            rep["burn_mm"] += ((nx - x) ** 2 + (ny - y) ** 2) ** 0.5
            for px, py in ((x, y), (nx, ny)):
                box = [px if box[0] is None else min(box[0], px), py if box[1] is None else min(box[1], py),
                       px if box[2] is None else max(box[2], px), py if box[3] is None else max(box[3], py)]
        cx, cy = min(max(nx, 0.0), bw), min(max(ny, 0.0), bh)
        if (cx, cy) != (nx, ny):
            rep["clamped"] += 1
        x, y = nx, ny
        mx, my = profile.to_machine(cx, cy)
        mx, my = mx - ox, my - oy
        rep["moves"] += 1
        if g == 0:
            out.append(f"G0 X{_f(mx)} Y{_f(my)}")
            continue
        feed, power = (f if f is not None else 1000.0), s * ratio
        if f_max and feed > f_max:
            power *= f_max / feed
            feed = f_max
            if burning:
                rep["capped"] += 1
        if power > 1000.0:
            power = 1000.0
            if burning:
                rep["s_limited"] += 1
        sv = round(power / 1000.0 * s_max, 1)
        parts = [f"G1 X{_f(mx)} Y{_f(my)}"]
        if sv != last_s:
            parts.append(f"S{sv:g}")
            last_s = sv
        if feed != last_f:
            parts.append(f"F{feed:g}")
            last_f = feed
        out.append(" ".join(parts))
    if hasattr(profile, "home_point"):
        hx, hy = profile.to_machine(*profile.home_point(10.0))
        out.append("M5 S0")
        out.append(f"G0 X{_f(hx - ox)} Y{_f(hy - oy)}")
    else:
        out.append("M5 S0")
    out.append("G54")
    if air_off:
        out.append(air_off)
    out.append("; fine")
    rep["box"] = tuple(box) if box[0] is not None else None
    if rep["box"] is None:
        raise ValueError("empty")
    return out, rep
