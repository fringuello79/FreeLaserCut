# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Materiali imparati: la risposta del TUO materiale al laser, imparata dalle foto dei test.

Ogni quadrato di un test materiale letto da foto (taratura da foto) dà un campione:
energia per mm² depositata dal laser → quanto è diventato scuro rispetto al materiale nudo,
più il colore vero del quadrato. Da questi campioni FreeLaserCut ricava una curva che sale
sempre (più energia = mai più chiaro) e la usa per:

* prevedere il risultato (scuro e colore) di qualsiasi potenza e velocità su quel materiale;
* trovare la potenza per il tono che vuoi («dammi un marrone medio a 3000 mm/min»);
* correggere i toni delle foto in scala di grigi: i grigi della foto diventano scurezze
  equidistanti sul legno vero, invece di potenze equidistanti (il legno satura e i neri si impastano).

Ogni nuova foto si aggiunge alle precedenti: la curva si affina (le foto vecchie pesano un po' meno).
Energia = (potenza / 100) × passate / (velocità in mm/s) / interlinea in mm: è la stessa grandezza
che accumula l'anteprima realistica, quindi la curva serve anche lì.

Non usa Qt e non serve la macchina. Le curve stanno nel file curve_materiali.json della cartella
delle impostazioni; si possono esportare e importare (un file .json) per darle a qualcuno.
"""
import copy
import json
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass, field

import numpy as np

FILE_NAME = "curve_materiali.json"
FORMAT = "freelasercut-curve"
VERSION = 1
AGE_WEIGHT = 0.8  # peso di una foto rispetto alla successiva
MAX_PHOTOS = 12  # oltre, le foto più vecchie escono dalla curva
GRID = 48  # punti della curva salvata
E_FLOOR = 1e-6


def energy(power, speed, interval, passes=1):
    """Energia per mm² (potenza in %, velocità in mm/min, interlinea in mm)."""
    v = max(float(speed), 1e-3) / 60.0
    return max(float(power), 0.0) / 100.0 * max(int(passes), 1) / v / max(float(interval), 1e-4)


def power_for_energy(e, speed, interval, passes=1):
    v = max(float(speed), 1e-3) / 60.0
    return float(e) * max(float(interval), 1e-4) * v / max(int(passes), 1) * 100.0


def _pav(y, w):
    """Regressione isotonica (crescente) con pesi: pool adjacent violators."""
    vals, wts, cnt = [], [], []
    for yi, wi in zip(y, w):
        vals.append(float(yi))
        wts.append(float(wi))
        cnt.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            tw = wts[-2] + wts[-1]
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / tw
            c = cnt[-2] + cnt[-1]
            vals[-2:], wts[-2:], cnt[-2:] = [v], [tw], [c]
    out = []
    for v, c in zip(vals, cnt):
        out.extend([v] * c)
    return np.array(out)


@dataclass
class BurnCurve:
    name: str
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    machine: str = ""
    note: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    photos: int = 0  # foto usate (anche quelle uscite dalla curva)
    # campioni: [energia, scuro 0..1, numero della foto, r/nudo, g/nudo, b/nudo, potenza, velocità]
    samples: list = field(default_factory=list)
    bare: list = field(default_factory=lambda: [222.0, 190.0, 146.0])  # colore del materiale nudo (RGB)
    bare_photos: list = field(default_factory=list)  # [numero della foto, r, g, b]
    # curva calcolata (log10 energia → scuro) e rampa dei colori (scuro → colore / nudo)
    xs: list = field(default_factory=list)
    ys: list = field(default_factory=list)
    ramp_d: list = field(default_factory=list)
    ramp_c: list = field(default_factory=list)

    # ------------------------------------------------------------------ dati
    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        known = {k: v for k, v in dict(d).items() if k in cls.__dataclass_fields__}
        if not known.get("name"):
            raise ValueError("curva senza nome")
        c = cls(**known)
        c.samples = [[float(v) for v in s[:8]] for s in c.samples if isinstance(s, (list, tuple)) and len(s) >= 8
                     and all(math.isfinite(float(v)) for v in s[:8]) and float(s[0]) > 0]
        c.bare_photos = [[float(v) for v in b[:4]] for b in c.bare_photos if isinstance(b, (list, tuple)) and len(b) >= 4
                         and all(math.isfinite(float(v)) for v in b[:4])]
        c.bare = [float(v) for v in (list(c.bare) + [200.0] * 3)[:3]]
        c.fit()
        return c

    @property
    def ok(self):
        return len(self.xs) >= 2 and self.d_max > 0.02

    @property
    def d_max(self):
        return float(self.ys[-1]) if self.ys else 0.0

    @property
    def e_range(self):
        """Energie misurate (minima, massima)."""
        if not self.samples:
            return (0.0, 0.0)
        e = [s[0] for s in self.samples]
        return (min(e), max(e))

    def last_photo(self):
        return max([int(s[2]) for s in self.samples] + [int(b[0]) for b in self.bare_photos] + [-1])

    # ------------------------------------------------------------------ imparare
    def add_photo(self, samples, bare_rgb):
        """samples: [(energia, scuro, (r, g, b) del quadrato, potenza, velocità)] di una foto; bare_rgb del nudo."""
        n = self.last_photo() + 1
        br = [max(float(v), 1.0) for v in bare_rgb]
        for e, d, rgb, p, v in samples:
            if not (e > 0 and math.isfinite(e) and math.isfinite(d)):
                continue
            rel = [float(rgb[i]) / br[i] for i in range(3)]
            self.samples.append([float(e), float(min(max(d, 0.0), 1.0)), float(n), *rel, float(p), float(v)])
        self.bare_photos.append([float(n), *br])
        keep = n - MAX_PHOTOS + 1  # solo le ultime foto
        self.samples = [s for s in self.samples if s[2] >= keep]
        self.bare_photos = [b for b in self.bare_photos if b[0] >= keep]
        self.photos += 1
        self.updated = time.time()
        self.fit()
        return self

    def _weights(self, photo_ids):
        last = self.last_photo()
        return np.power(AGE_WEIGHT, last - np.asarray(photo_ids, float))

    def fit(self):
        """Ricalcola curva e colori dai campioni."""
        self.xs, self.ys, self.ramp_d, self.ramp_c = [], [], [], []
        if self.bare_photos:
            b = np.asarray(self.bare_photos, float)
            w = self._weights(b[:, 0])
            self.bare = [float(v) for v in (b[:, 1:4] * w[:, None]).sum(0) / w.sum()]
        if len(self.samples) < 3:
            return
        a = np.asarray(self.samples, float)
        a = a[np.argsort(a[:, 0], kind="stable")]
        x = np.log10(np.maximum(a[:, 0], E_FLOOR))
        w = self._weights(a[:, 2])
        y = _pav(a[:, 1], w)
        lo, hi = float(x[0]), float(x[-1])
        if hi - lo < 1e-3:
            return
        # curva liscia: media locale (gaussiana in log energia) dei valori già ordinati, poi di nuovo crescente
        gx = np.linspace(lo, hi, GRID)
        bw = max((hi - lo) / 14.0, 0.02)
        k = np.exp(-0.5 * ((gx[:, None] - x[None, :]) / bw) ** 2) * w[None, :]
        gy = (k * y[None, :]).sum(1) / np.maximum(k.sum(1), 1e-12)
        gy = np.maximum.accumulate(np.clip(gy, 0.0, 1.0))
        self.xs = [round(float(v), 5) for v in gx]
        self.ys = [round(float(v), 5) for v in gy]
        # colori: medie pesate per fasce di scuro (colore relativo al nudo: vale anche con un'altra luce)
        d = a[:, 1]
        rel = a[:, 3:6]
        edges = np.linspace(0.0, max(float(d.max()), 0.05), 11)
        rd, rc = [0.0], [[1.0, 1.0, 1.0]]
        for i in range(10):
            m = (d >= edges[i]) & (d <= edges[i + 1]) if i == 9 else (d >= edges[i]) & (d < edges[i + 1])
            if m.any() and float(d[m].mean()) > rd[-1] + 1e-3:
                ww = w[m]
                rd.append(float((d[m] * ww).sum() / ww.sum()))
                rc.append([float(v) for v in (rel[m] * ww[:, None]).sum(0) / ww.sum()])
        self.ramp_d = [round(v, 4) for v in rd]
        self.ramp_c = [[round(v, 4) for v in c] for c in rc]

    # ------------------------------------------------------------------ prevedere
    def dark(self, e):
        """Scuro previsto (0..1) per energia/e per mm² (numero o array)."""
        e_arr = np.asarray(e, float)
        if not self.ok:
            return np.zeros_like(e_arr) if e_arr.ndim else 0.0
        xs, ys = np.asarray(self.xs), np.asarray(self.ys)
        x = np.log10(np.maximum(e_arr, E_FLOOR))
        out = np.interp(x, xs, ys)
        # sotto la prima misura: verso zero, proporzionale all'energia
        e0 = 10.0 ** xs[0]
        low = e_arr < e0
        out = np.where(low, ys[0] * np.clip(e_arr / e0, 0.0, 1.0), out)
        out = np.where(e_arr <= 0, 0.0, out)
        return out if e_arr.ndim else float(out)

    def energy_for(self, d):
        """Energia che dà lo scuro d (il minimo che ci arriva). Oltre il massimo misurato: l'energia del massimo."""
        if not self.ok:
            return None
        xs, ys = np.asarray(self.xs), np.asarray(self.ys)
        d = float(d)
        if d <= 0:
            return 0.0
        e0 = 10.0 ** xs[0]
        if d <= ys[0]:
            return e0 * d / max(ys[0], 1e-9)
        if d >= ys[-1]:
            i = int(np.argmax(ys >= ys[-1] - 1e-6))
            return float(10.0 ** xs[i])
        # ys crescente (anche piatto): primo punto che supera d, interpolato col precedente
        i = int(np.argmax(ys >= d))
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        t = 0.0 if y1 - y0 < 1e-9 else (d - y0) / (y1 - y0)
        return float(10.0 ** (x0 + (x1 - x0) * t))

    def power_for(self, d, speed, interval, passes=1):
        e = self.energy_for(d)
        return None if e is None else power_for_energy(e, speed, interval, passes)

    def dark_at(self, power, speed, interval, passes=1):
        return self.dark(energy(power, speed, interval, passes))

    def color(self, d):
        """Colore previsto (RGB 0..255, array …×3) per lo scuro d (numero o array)."""
        d_arr = np.asarray(d, float)
        bare = np.asarray(self.bare, float)
        if len(self.ramp_d) < 2:
            # nessun colore misurato: dal nudo verso un marrone scuro, come l'anteprima generica
            burnt = np.array([52.0, 32.0, 20.0])
            t = np.clip(d_arr / max(self.d_max, 0.3), 0, 1)[..., None]
            return bare + (burnt - bare) * t
        rd = np.asarray(self.ramp_d)
        rc = np.asarray(self.ramp_c)
        dd = np.clip(d_arr, 0.0, float(rd[-1]))
        rel = np.stack([np.interp(dd, rd, rc[:, i]) for i in range(3)], axis=-1)
        return np.clip(rel * bare, 0, 255)

    # ------------------------------------------------------------------ usare
    def suggest(self, speed, interval, passes=1, p_cap=100.0):
        """Potenze consigliate a quella velocità: dict con start (il segno comincia), dark (quasi il massimo),
        mid (tono a metà) e, se il massimo non ci sta nel 100 %, la velocità più bassa che serve."""
        if not self.ok:
            return None
        dm = self.d_max
        out = {}
        for key, frac in (("start", 0.06), ("mid", 0.5), ("dark", 0.92)):
            out[key] = self.power_for(frac * dm, speed, interval, passes)
        out["slow"] = None
        if out["dark"] is not None and out["dark"] > p_cap:
            out["slow"] = float(speed) * p_cap / out["dark"]
        out["outside"] = any(v is not None and not self.measured(energy(v, speed, interval, passes))
                             for v in (out["start"], out["dark"]))
        for key in ("start", "mid", "dark"):
            if out[key] is not None:
                out[key] = round(min(max(out[key], 0.1), p_cap), 1)
        return out

    def tone_map(self, q, speed, interval, pmin, pmax, passes=1):
        """Grigi della foto (q 0..1, 1 = nero) → potenza %: scurezze equidistanti tra quella di pmin e di pmax."""
        q = np.asarray(q, float)
        lin = pmin + (pmax - pmin) * q
        if not self.ok or pmax <= pmin:
            return lin
        d_lo = self.dark_at(pmin, speed, interval, passes)
        # in cima la curva è quasi piatta: l'ultimo 3 % di scuro costerebbe moltissima potenza (bruciature profonde
        # nei neri pieni per una differenza che non si vede), quindi il nero si ferma al 97 % del massimo
        d_hi = min(self.dark_at(pmax, speed, interval, passes), 0.97 * self.d_max)
        if d_hi - d_lo < 0.02:
            return lin
        table_q = np.linspace(0.0, 1.0, 257)
        pw = [self.power_for(d_lo + (d_hi - d_lo) * t, speed, interval, passes) for t in table_q]
        pw = np.clip(np.maximum.accumulate(np.asarray(pw, float)), pmin, pmax)
        # il nero pieno prende la potenza minima che dà lo scuro della massima: oltre la saturazione del legno
        # più potenza non scurisce, brucia solo di più (e i quasi neri resterebbero staccati)
        pw[0] = pmin
        return np.interp(np.clip(q, 0, 1), table_q, pw)

    def measured(self, e, slack=0.15):
        """True se l'energia sta dentro i valori provati nei test (con un po' di margine): fuori è una stima."""
        lo, hi = self.e_range
        return lo * (1 - slack) <= float(e) <= hi * (1 + slack)

    def describe(self):
        lo, hi = self.e_range
        return {"photos": self.photos, "samples": len(self.samples), "d_max": self.d_max, "e_lo": lo, "e_hi": hi}


# ====================================================================== dalla foto del test
def samples_from_result(res, spec):
    """Risultato di test_photo.analyze + la griglia del test → (campioni, colore del nudo RGB)."""
    out = []
    cells = getattr(res, "cell_rgb", None)
    bare = getattr(res, "bare_rgb", None)
    if bare is None:
        bare = (200.0, 200.0, 200.0)
    for r, p in enumerate(res.powers):
        for c, v in enumerate(res.speeds):
            rgb = tuple(cells[r][c]) if cells is not None else bare
            out.append((energy(p, v, spec.interval, spec.passes), float(res.dark[r, c]), rgb, float(p), float(v)))
    return out, tuple(float(x) for x in bare)


# ====================================================================== archivio
def store_path():
    from ..profile import config_dir

    return os.path.join(config_dir(), FILE_NAME)


_cache = {"key": None, "path": None, "curves": [], "broken": False}


def _stamp(path):
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)


def load_all():
    """Copie delle curve salvate: chi le modifica non tocca quelle in uso finché non le salva."""
    path = store_path()
    try:
        key = _stamp(path)
    except OSError:
        _cache.update(key=None, path=path, curves=[], broken=False)
        return []
    if _cache["key"] != key or _cache["path"] != path:
        curves, broken = [], False
        try:
            with open(path, encoding="utf-8-sig") as fh:  # anche se salvato con il Blocco note (BOM)
                data = json.load(fh)
            if not isinstance(data, dict) or not isinstance(data.get("curves", []), list):
                raise ValueError("formato")
            for d in data.get("curves", []):
                try:
                    curves.append(BurnCurve.from_dict(d))
                except (TypeError, ValueError, KeyError, IndexError, AttributeError):
                    continue
        except (OSError, ValueError, UnicodeDecodeError):
            curves, broken = [], True
        _cache.update(key=key, path=path, curves=curves, broken=broken)
    return copy.deepcopy(_cache["curves"])


def _keep_broken(path):
    """Un archivio che non si riesce a leggere non si sovrascrive: si mette da parte con un altro nome."""
    if not _cache.get("broken") or not os.path.exists(path):
        return
    base = os.path.splitext(path)[0]
    dest = f"{base}.illeggibile-{time.strftime('%Y%m%d-%H%M%S')}.json"
    try:
        os.replace(path, dest)
    except OSError:
        pass
    _cache.update(broken=False)


def save_all(curves):
    path = store_path()
    load_all()
    _keep_broken(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"format": FORMAT, "version": VERSION, "curves": [c.to_dict() for c in curves]}, fh,
                  ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    _cache.update(key=None)


def get(uid):
    if not uid:
        return None
    for c in load_all():
        if c.uid == uid:
            return c
    return None


def put(curve):
    """Aggiunge o sostituisce (stesso uid)."""
    curves = [c for c in load_all() if c.uid != curve.uid]
    save_all([curve] + curves)


def remove(uid):
    save_all([c for c in load_all() if c.uid != uid])


def export_file(curve, path):
    """Un file da dare a qualcuno: la curva, senza dati della macchina oltre al nome del profilo."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"format": FORMAT, "version": VERSION, "curves": [curve.to_dict()]}, fh, ensure_ascii=False, indent=1)


def import_file(path):
    """Curve lette da un file esportato (nuovo uid se ce n'è già una uguale)."""
    with open(path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("non è un file di curve di FreeLaserCut")
    have = {c.uid for c in load_all()}
    out = []
    for d in data.get("curves", []) if isinstance(data.get("curves", []), list) else []:
        try:
            c = BurnCurve.from_dict(d)
        except (TypeError, ValueError, KeyError, IndexError, AttributeError):
            continue
        if c.uid in have:
            c.uid = uuid.uuid4().hex[:12]
        if not c.ok:
            continue
        out.append(c)
    return out
