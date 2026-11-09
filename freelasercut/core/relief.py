# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Rilievo 3D su tavola (0.17.16, funzione in prova): scolpire la tavola intera a strati, a Z fissa.

Progetto con unità, invarianti e casi provati: documento di progetto «rilievo-3d-progetto».
In breve:
- mappa delle altezze H (0..1, 1 = superficie non incisa) da un'immagine in grigi o da un modello .stl/.obj;
- profondità voluta T = (1 − H)·Dmax (mm), con Dmax ≤ min(5 mm, spessore − 2 mm, profondità utile misurata);
- profondità dopo n passate D(n) = a·n^b, con a e b dal test di profondità (misure col calibro);
- passate per pixel N = ⌊n(T) + β⌋ (β soglia Bayer: sfuma i gradini senza spostare la profondità media);
- la passata k incide i pixel con N ≥ k (maschere annidate), righe alternate lungo X e lungo Y, stessa potenza.
"""
import json
import math
import os
import time

import numpy as np

from freelasercut.i18n import tr

MAX_DEPTH = 5.0  # mm: oltre, a Z fissa il punto è troppo fuori fuoco
THICK_MARGIN = 2.0  # mm lasciati sotto il punto più profondo (mai bucare la tavola)
TOLERANCE = 0.10  # test accettato se l'ultimo gradino è entro il 10% della profondità voluta
USEFUL_K = 0.25  # una passata che toglie meno del 25% della prima non conviene più
B_RANGE = (0.3, 1.2)
PRIOR = (0.15, 0.9)  # senza taratura: prudente (meno passate: si resta più in alto, non si buca)
MAX_STEPS = 5
STEP_W, STEP_H = 5.0, 4.0  # gradini del test (mm): larghi abbastanza per l'asta del calibro
_BAYER = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], float) + 0.5) / 16.0
JUDGMENTS = ("clean", "dark", "edges", "flames")


# ====================================================================== mappa delle altezze
def heightmap_from_image(gray, nx, ny, white_high=True):
    """Immagine in grigi (array 2D, 0..255 o 0..1) → H (ny × nx, 0..1). Riga 0 = lato in alto (dietro)."""
    import cv2

    g = np.asarray(gray, dtype=np.float64)
    if g.ndim == 3:
        g = g[..., :3].mean(axis=2)
    if g.size == 0:
        raise ValueError(tr("immagine vuota"))
    if g.max() > 1.0 + 1e-9:
        g = g / 255.0
    g = np.clip(g, 0.0, 1.0)
    h = cv2.resize(g.astype(np.float32), (int(nx), int(ny)), interpolation=cv2.INTER_AREA).astype(np.float64)
    return h if white_high else 1.0 - h


def _oriented(mesh, up):
    V = np.asarray(mesh.vertices, dtype=np.float64)
    if up == "y":
        V = V[:, [0, 2, 1]] * np.array([1, -1, 1])
    elif up == "x":
        V = V[:, [1, 2, 0]]
    return V


def mesh_aspect(mesh, up="z"):
    """(larghezza, profondità) del modello visto dall'alto, nelle sue unità."""
    V = _oriented(mesh, up)
    lo, hi = V.min(0), V.max(0)
    return float(hi[0] - lo[0]), float(hi[1] - lo[1])


def heightmap_from_mesh(mesh, nx, ny, up="z", background="bottom"):
    """Modello visto dall'alto (z-buffer, il punto più alto vince) → H (ny × nx, 0..1).
    background: «bottom» = fuori dal modello si scende al fondo (l'oggetto esce in rilievo); «surface» = non inciso."""
    V = _oriented(mesh, up)
    lo, hi = V.min(0), V.max(0)
    span = hi - lo
    if span[2] <= 1e-12:
        raise ValueError(tr("Il modello è piatto in verticale: scegli un altro asse verso l'alto."))
    if span[0] <= 1e-12 or span[1] <= 1e-12:
        raise ValueError(tr("Il modello visto dall'alto non ha area: scegli un altro asse verso l'alto."))
    nx, ny = int(nx), int(ny)
    u = (V[:, 0] - lo[0]) / span[0] * nx  # colonne (pixel), 0 a sinistra
    v = (hi[1] - V[:, 1]) / span[1] * ny  # righe, 0 in alto (dietro)
    z = (V[:, 2] - lo[2]) / span[2]
    zbuf = np.full((ny, nx), -np.inf)
    for f in np.asarray(mesh.faces, dtype=np.int64):
        (u0, u1, u2), (v0, v1, v2), (z0, z1, z2) = u[f], v[f], z[f]
        den = (v1 - v2) * (u0 - u2) + (u2 - u1) * (v0 - v2)
        if abs(den) < 1e-12:
            continue  # triangolo verticale visto dall'alto: non copre area
        c0, c1 = max(int(math.floor(min(u0, u1, u2))), 0), min(int(math.ceil(max(u0, u1, u2))), nx)
        r0, r1 = max(int(math.floor(min(v0, v1, v2))), 0), min(int(math.ceil(max(v0, v1, v2))), ny)
        if c0 >= c1 or r0 >= r1:
            continue
        pc, pr = np.meshgrid(np.arange(c0, c1) + 0.5, np.arange(r0, r1) + 0.5)
        w0 = ((v1 - v2) * (pc - u2) + (u2 - u1) * (pr - v2)) / den
        w1 = ((v2 - v0) * (pc - u2) + (u0 - u2) * (pr - v2)) / den
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not inside.any():
            continue
        zz = np.where(inside, w0 * z0 + w1 * z1 + w2 * z2, -np.inf)
        sub = zbuf[r0:r1, c0:c1]
        np.maximum(sub, zz, out=sub)
    empty = ~np.isfinite(zbuf)
    if empty.all():
        raise ValueError(tr("Il modello non copre nessun punto della griglia."))
    h = np.where(empty, 0.0 if background == "bottom" else 1.0, zbuf)
    return np.clip(h, 0.0, 1.0)


# ====================================================================== modello della profondità
class DepthModel:
    """Profondità dopo n passate: D(n) = a·n^b (mm)."""

    def __init__(self, a, b, calibrated=True):
        self.a, self.b, self.calibrated = float(a), float(b), bool(calibrated)

    @classmethod
    def prior(cls):
        return cls(*PRIOR, calibrated=False)

    def depth(self, n):
        n = np.maximum(np.asarray(n, dtype=np.float64), 0.0)
        return self.a * n ** self.b

    def passes(self, t):
        """Passate (continue) per arrivare alla profondità t."""
        t = np.maximum(np.asarray(t, dtype=np.float64), 0.0)
        return (t / self.a) ** (1.0 / self.b)

    def useful_depth(self):
        """Profondità oltre la quale una passata rende meno di USEFUL_K volte la prima (inf se b ≥ 1)."""
        if self.b >= 1.0:
            return math.inf
        n = (USEFUL_K / self.b) ** (1.0 / (self.b - 1.0))
        return float(self.depth(max(n, 1.0)))

    def to_dict(self):
        return {"a": self.a, "b": self.b}


def fit(d1, dn, n):
    """Taratura dalle misure col calibro: d1 = primo gradino (1 passata), dn = ultimo gradino (n passate).
    ValueError con il motivo se le misure non sono credibili."""
    d1, dn, n = float(d1), float(dn), int(n)
    if not (d1 > 0):
        raise ValueError(tr("La profondità del primo gradino deve essere più di zero."))
    if n <= 1:
        return DepthModel(d1, 1.0)
    if not (dn > 0):
        raise ValueError(tr("La profondità dell'ultimo gradino deve essere più di zero."))
    if dn < d1:
        raise ValueError(tr("L'ultimo gradino risulta meno profondo del primo: rifai la misura."))
    b = math.log(dn / d1) / math.log(n)
    if not (B_RANGE[0] <= b <= B_RANGE[1]):
        raise ValueError(tr("Le due misure non sono coerenti (la resa per passata risulta {0:.2f}): rifai il test o la "
                            "misura.", b))
    return DepthModel(d1, b)


def limits(dmax, thickness, model):
    """Profondità massima ammessa e i motivi dei limiti. -> (massimo, [motivi])."""
    reasons = []
    top = MAX_DEPTH
    reasons.append(tr("al massimo {0:g} mm a testa ferma", MAX_DEPTH))
    if thickness is not None and thickness > 0:
        t2 = thickness - THICK_MARGIN
        if t2 < top:
            top = max(t2, 0.0)
            reasons.append(tr("tavola da {0:g} mm: restano almeno {1:g} mm sotto", thickness, THICK_MARGIN))
    if model is not None and model.calibrated:
        u = model.useful_depth()
        if u < top:
            top = u
            reasons.append(tr("su questo materiale oltre {0:.1f} mm le passate rendono troppo poco", u))
    return top, reasons


def check_depth(dmax, thickness, model):
    """'' se la profondità è ammessa, altrimenti il motivo."""
    top, _ = limits(dmax, thickness, model)
    if dmax <= 0:
        return tr("La profondità deve essere più di zero.")
    if dmax > top + 1e-9:
        _, reasons = limits(dmax, thickness, model)
        return tr("Profondità {0:g} mm troppo grande: al massimo {1:.2f} mm ({2}).", dmax, top, "; ".join(reasons))
    return ""


# ====================================================================== passate
def target_depth(h, dmax):
    return (1.0 - np.clip(np.asarray(h, dtype=np.float64), 0.0, 1.0)) * float(dmax)


def pass_map(h, dmax, model, dither=True):
    """Passate per pixel (interi ≥ 0)."""
    n = model.passes(target_depth(h, dmax))
    if dither:
        ny, nx = n.shape
        beta = np.tile(_BAYER, (ny // 4 + 1, nx // 4 + 1))[:ny, :nx]
    else:
        beta = 0.5
    out = np.floor(n + beta).astype(np.int32)
    return np.maximum(out, 0)


def masks(nmap):
    """[maschera della passata 1, 2, …]: la k-esima = pixel con almeno k passate (annidate per costruzione)."""
    top = int(nmap.max()) if nmap.size else 0
    return [nmap >= k for k in range(1, top + 1)]


def predicted(nmap, model, pitch, spot_mm=0.1):
    """Profondità prevista (mm): D(N) sfocata con il punto laser (gaussiana con FWHM = spot)."""
    import cv2

    d = model.depth(nmap).astype(np.float32)
    sigma = max(float(spot_mm), 1e-3) / 2.355 / float(pitch)
    if sigma < 0.3:
        return d.astype(np.float64)
    k = int(2 * math.ceil(3 * sigma) + 1)
    return cv2.GaussianBlur(d, (k, k), sigma).astype(np.float64)


def shaded(depth, pitch):
    """Immagine (uint8) del rilievo previsto con la luce radente da in alto a sinistra."""
    z = -np.asarray(depth, dtype=np.float64)
    gy, gx = np.gradient(z, pitch)
    nz = 1.0 / np.sqrt(1.0 + gx * gx + gy * gy)
    lx, ly, lz = -0.55, 0.55, 0.63  # luce: da sinistra e da dietro, alta
    shade = (-gx * lx + gy * ly + lz) * nz
    base = 0.82 - 0.35 * (np.asarray(depth) / max(float(np.max(depth)), 1e-9))
    return np.clip(255 * (0.25 + 0.75 * shade) * base, 0, 255).astype(np.uint8)


# ====================================================================== test di profondità
def test_steps(total):
    """Passate dei gradini del test: 1 … total, crescenti in modo geometrico, al massimo MAX_STEPS."""
    total = max(1, int(total))
    if total == 1:
        return [1]
    k = min(MAX_STEPS, total)
    out = sorted({max(1, min(total, int(round(total ** (i / (k - 1)))))) for i in range(k)})
    if out[0] != 1:
        out.insert(0, 1)
    if out[-1] != total:
        out.append(total)
    return out


def test_map(steps, pitch):
    """Mappa delle passate del test: gradini affiancati da sinistra (il più leggero) a destra."""
    cw = max(1, int(round(STEP_W / pitch)))
    ch = max(1, int(round(STEP_H / pitch)))
    m = np.zeros((ch, cw * len(steps)), np.int32)
    for i, n in enumerate(steps):
        m[:, i * cw:(i + 1) * cw] = int(n)
    return m


def accept(dn, dmax):
    """(accettato?, errore relativo) dell'ultimo gradino rispetto alla profondità voluta."""
    err = (float(dn) - float(dmax)) / float(dmax)
    return abs(err) <= TOLERANCE + 1e-12, err


def after_judgment(judgment, power):
    """Dal giudizio a vista: (nuova potenza %, serve un nuovo test?, messaggio)."""
    if judgment == "flames":
        return round(power * 0.8, 1), True, tr("Fiamme: potenza ridotta del 20% e più passate. Rifai il test con "
                                               "l'aria accesa e la guardia fiamme.")
    if judgment == "dark":
        return round(power * 0.85, 1), True, tr("Fondo molto annerito: potenza ridotta del 15% e più passate. Rifai "
                                                "il test.")
    if judgment == "edges":
        return power, False, tr("Bordi bruciati: va bene per la profondità; se disturba, abbassa un po' la potenza e "
                                "rifai il test.")
    return power, False, ""


# ====================================================================== G-code
def build_job(nmap, pitch, x0, y0, power, speed, profile, alternate=True, title="", overscan=2.0, air=True):
    """Lavoro (GcodeJob) dalle passate per pixel. (x0, y0) = angolo in basso a sinistra sul piano (mm).
    Passata k: righe lungo X se k è dispari (o sempre, senza alternanza), lungo Y se è pari."""
    from PySide6.QtCore import QRectF

    from .document import CutSettings
    from .gcode import GcodeJob, LayerStats, _emit_scan, _Writer, orient_job_preview

    t0 = time.time()
    nmap = np.asarray(nmap, dtype=np.int32)
    ny, nx = nmap.shape
    p = float(pitch)
    job = GcodeJob()
    bed = (profile.bed_x, profile.bed_y)
    off = tuple(getattr(profile, "wcs_offset", (0.0, 0.0))) if getattr(profile, "no_g55", False) else (0.0, 0.0)

    def mp(bx, by):
        mx, my = profile.to_machine(bx, by)
        return mx - off[0], my - off[1]

    w = _Writer(mp, profile.s_max)
    if getattr(profile, "scan_offsets", None):
        w.scan_offset = profile.scan_offset
    w.raw(f"; FreeLaserCut — rilievo 3D{' ' + title if title else ''}: {int(nmap.max())} passate, "
          f"{p:g} mm, {power:g}%, {speed:g} mm/min")
    w.raw("G90 G21")
    w.raw("M5 S0")
    if getattr(profile, "no_g55", False):
        w.raw("G54")
    else:
        w.raw("G10 L2 P2 X0 Y0")
        w.raw("G55")
    if air:
        w.raw(getattr(profile, "air_on", "M8") or "M8")
    w.raw("M4 S0")
    cs = CutSettings(mode="fill", speed=speed, power_max=power, interval=p, overscan=overscan, bidirectional=True)
    cut0 = w.cut
    for k, m in enumerate(masks(nmap), start=1):
        w.raw(f"; passata {k}")
        along_y = alternate and k % 2 == 0
        lines = []
        if not along_y:
            for r in range(ny - 1, -1, -1):  # dal basso (davanti) verso l'alto
                segs = _runs(m[r])
                if segs:
                    y = y0 + (ny - r - 0.5) * p
                    lines.append((y, [(x0 + a * p, x0 + b * p, power) for a, b in segs]))
            if lines:
                _emit_scan(w, lines, (1.0, 0.0), cs, bed, 6.0)
        else:
            # righe verticali: nel sistema ruotato di 90° la coordinata di scansione è Y, quella della riga è −X
            for c in range(nx - 1, -1, -1):  # −X crescente = colonne da destra a sinistra
                col = m[::-1, c]  # dal basso verso l'alto
                segs = _runs(col)
                if segs:
                    yr = -(x0 + (c + 0.5) * p)
                    lines.append((yr, [(y0 + a * p, y0 + b * p, power) for a, b in segs]))
            if lines:
                _emit_scan(w, lines, (0.0, 1.0), cs, bed, 6.0)
    job.layers.append(LayerStats(0, tr("rilievo"), "fill", int(nmap.max()), w.cut - cut0, 0, speed, power))
    w.raw("M5 S0")
    if air:
        w.raw(getattr(profile, "air_off", "M9") or "M9")
    w.rapid(0.0, 0.0)
    w.raw("G54")
    job.lines = w.lines
    b, mv = w.burn, w.motion
    if b[0] <= b[2]:
        job.bounds = QRectF(b[0], b[1], b[2] - b[0], b[3] - b[1])
    if mv[0] <= mv[2]:
        job.motion_bounds = QRectF(mv[0], mv[1], mv[2] - mv[0], mv[3] - mv[1])
    if mv[0] < -0.01 or mv[1] < -0.01 or mv[2] > bed[0] + 0.01 or mv[3] > bed[1] + 0.01:
        job.warnings.append(tr("Il rilievo esce dall'area di lavoro: cambia la posizione"))
    mx0, my0 = profile.to_machine(0.0, 0.0)
    job.out_to_bed = (-mx0 + off[0], -my0 + off[1])
    from .. import gcode_preview

    job.preview = gcode_preview.parse(job.lines, profile=profile)
    job.seconds = job.preview.seconds
    orient_job_preview(job, profile, mp)
    job.gen_ms = (time.time() - t0) * 1000
    return job


def _runs(row):
    """[(inizio, fine)] dei tratti True di una riga (fine esclusa), in indici di pixel."""
    row = np.asarray(row, dtype=bool)
    if not row.any():
        return []
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return list(zip(starts.tolist(), ends.tolist()))


# ====================================================================== tarature salvate
def calib_key(profile_name, material, power, speed, interval):
    return f"{profile_name}|{material.strip().lower()}|{float(power):g}|{float(speed):g}|{float(interval):g}"


def _calib_path():
    from ..profile import config_dir

    return os.path.join(config_dir(), "relief_calib.json")


def load_calibrations(path=None):
    try:
        with open(path or _calib_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_calibration(key, model, d1, dn, n, judgment, path=None):
    data = load_calibrations(path)
    data[key] = {"a": model.a, "b": model.b, "d1": float(d1), "dn": float(dn), "n": int(n), "judgment": judgment,
                 "date": time.strftime("%Y-%m-%d %H:%M")}
    p = path or _calib_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    return data[key]


def find_calibration(key, path=None):
    """(DepthModel, dati salvati) della taratura con questa chiave, oppure (None, None)."""
    d = load_calibrations(path).get(key)
    if not isinstance(d, dict):
        return None, None
    try:
        m = DepthModel(float(d["a"]), float(d["b"]))
    except (KeyError, TypeError, ValueError):
        return None, None
    if not (m.a > 0 and B_RANGE[0] <= m.b <= B_RANGE[1]):
        return None, None
    return m, d
