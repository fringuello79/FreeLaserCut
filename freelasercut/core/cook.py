# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Free Laser Cook (0.20.6, funzione in prova, sbloccabile con il codice amministratore).

Il laser non è un fornello. Questo modulo trasforma una ricetta in passate sfocate e veloci sopra il cibo, più i
tocchi dello chef: aroma del legno, righe della griglia, firma. Tutto a testa alzata, alla stessa altezza.

Unità: mm, mm/min, % della potenza, W ottici, J/mm², °C. Coordinate del piano come si vede; (x0, y0) è l'angolo in
basso a sinistra del cibo.

Il conto. Per scaldare di ΔT uno strato spesso s il cibo deve ricevere, per lato,
    E = ρ · s · (c · ΔT + acqua_evaporata · 2260) / (assorbimento · rendimento)        [J/mm²]
con s = metà spessore se si gira, tutto lo spessore se no; per le ricette «di superficie» (pane, tataki) s è lo
strato che interessa e conta anche l'acqua che se ne va. Una passata lascia D = P / (v · d) J/mm² (P in W ottici,
v in mm/s, d = interlinea): si tiene bassa la dose della passata e si fanno più passate, perché il calore ha bisogno
di tempo per entrare e una dose alta in una volta sola brucia fuori e lascia crudo dentro.
Sono stime di partenza: decide il termometro a sonda.
"""
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field, fields, replace

from . import geom
from ..i18n import tr  # noqa: E402

KINDS = ("carne", "pollame", "pesce", "verdura", "pane", "formaggio", "dolce", "altro")
SEARS = ("none", "grill", "crosshatch")
WOODS = ("none", "ciliegio", "melo", "faggio", "quercia", "ulivo")
SHAPES = ("rect", "ellipse", "selection")

MIN_SPEED = 600.0  # mm/min: più piano di così la riga, anche sfocata, brucia
MAX_SPEED = 30000.0
MIN_POWER = 10.0  # %: sotto, molti diodi non sono stabili: si va più veloci invece
MAX_PASSES = 40  # per lato
POULTRY_T = 74.0  # °C al cuore: sotto, il pollame non si mangia
LATENT = 2260.0  # J/g: calore di evaporazione dell'acqua
OVERSCAN = 2.0  # mm
FILE_EXT = ".flcook"
SIGN_FONT = "futural"  # carattere a linea singola


def _sear(mode="none", power=100.0, speed=1800.0, spacing=8.0, angle=45.0, passes=1):
    return {"mode": mode, "power": power, "speed": speed, "spacing": spacing, "angle": angle, "passes": passes}


def _smoke(wood="none", laps=2, power=100.0, speed=900.0, margin=6.0):
    return {"wood": wood, "laps": laps, "power": power, "speed": speed, "margin": margin}


@dataclass
class Recipe:
    key: str = "ricetta"
    name: str = ""
    kind: str = "altro"
    note: str = ""
    # il cibo
    thickness: float = 3.0  # mm
    c: float = 3.5  # J/(g·K)
    density: float = 1.05  # g/cm³
    absorb: float = 0.85  # parte della luce a 450 nm che il cibo assorbe (0-1)
    efficiency: float = 0.45  # parte dell'energia assorbita che resta nel cibo (0-1)
    t_start: float = 20.0  # °C
    surface: bool = False  # ricetta di superficie: si scalda solo lo strato surface_mm
    surface_mm: float = 1.0
    evap: float = 0.0  # parte del peso dello strato che evapora (0-1)
    # la cottura
    doneness: list = field(default_factory=list)  # [(chiave, nome, °C)]
    default: str = ""
    dose_pass: float = 0.10  # J/mm² per passata
    speed: float = 12000.0  # mm/min preferita
    interval: float = 1.0  # mm fra le righe
    defocus_mm: float = 20.0  # di quanto alzare la testa dal fuoco
    alternate: bool = True  # passate a 0° e a 90° alternate
    flip: bool = True
    # i tocchi dello chef
    sear: dict = field(default_factory=_sear)
    signature: str = ""
    smoke: dict = field(default_factory=_smoke)
    builtin: bool = False
    tested: bool = False  # provata davvero su una macchina da chi l'ha scritta

    def label(self):
        return tr(self.name) if self.builtin else self.name

    def doneness_label(self, entry):
        return tr(entry[1]) if self.builtin else entry[1]

    def entry(self, key=None):
        """(chiave, nome, °C) del grado di cottura chiesto, o di quello predefinito."""
        for want in (key, self.default):
            for d in self.doneness:
                if d[0] == want:
                    return tuple(d)
        return tuple(self.doneness[0]) if self.doneness else ("", "", 60.0)

    def to_dict(self):
        d = asdict(self)
        d["doneness"] = [list(x) for x in self.doneness]
        return d


def _B(key, name, kind, note, thickness, c, density, absorb, doneness, default, **kw):
    return Recipe(key=key, name=name, kind=kind, note=note, thickness=thickness, c=c, density=density, absorb=absorb,
                  doneness=[tuple(d) for d in doneness], default=default, builtin=True, **kw)


def builtin():
    """Le ricette incluse: numeri di partenza calcolati con il conto qui sopra, da verificare col termometro."""
    grill = _sear("grill")
    return [
        _B("manzo_fettina", "Fettina di manzo", "carne",
           "La classica: fettina sottile, girata a metà cottura, righe della griglia alla fine.",
           3.0, 3.5, 1.05, 0.85, [("al_sangue", "Al sangue", 50.0), ("media", "Media", 60.0),
                                  ("ben_cotta", "Ben cotta", 70.0)], "media", sear=grill, signature="FLC"),
        _B("tataki_manzo", "Tataki di manzo", "carne",
           "Solo scottato fuori: dentro resta crudo. Serve carne adatta a essere mangiata cruda.",
           15.0, 3.5, 1.05, 0.85, [("scottato", "Scottato", 65.0)], "scottato", surface=True, surface_mm=1.5,
           evap=0.05, t_start=5.0),
        _B("pollo_fettina", "Petto di pollo a fettine sottili", "pollame",
           "Il pollo va mangiato solo ben cotto: 74 °C al cuore, misurati col termometro a sonda.",
           3.0, 3.5, 1.05, 0.60, [("ben_cotto", "Ben cotto", 76.0)], "ben_cotto", sear=grill),
        _B("tataki_salmone", "Tataki di salmone", "pesce",
           "Solo scottato fuori: dentro resta crudo. Serve pesce abbattuto, adatto a essere mangiato crudo.",
           15.0, 3.6, 1.08, 0.60, [("scottato", "Scottato", 60.0)], "scottato", surface=True, surface_mm=1.5,
           evap=0.05, t_start=5.0),
        _B("zucchina_fette", "Zucchina a fette", "verdura",
           "Fette per il lungo, asciugate bene: la parte chiara assorbe meno della buccia.",
           4.0, 3.9, 0.95, 0.65, [("croccante", "Croccante", 75.0), ("morbida", "Morbida", 90.0)], "croccante",
           sear=grill),
        _B("melanzana_fette", "Melanzana a fette", "verdura",
           "Polpa chiara e spugnosa: asciugala e non avere fretta. Griglia incrociata alla fine.",
           5.0, 3.9, 0.60, 0.60, [("morbida", "Morbida", 90.0)], "morbida", sear=_sear("crosshatch")),
        _B("peperone_falde", "Peperone a falde", "verdura",
           "Buccia verso l'alto: il rosso assorbe il blu meglio del giallo.",
           5.0, 3.9, 0.95, 0.80, [("croccante", "Croccante", 75.0), ("tenero", "Tenero", 90.0)], "croccante"),
        _B("patata_fette", "Patata a fette sottili", "verdura",
           "Chiara e piena d'acqua: è la più lenta di tutte. Fette da 2 mm, asciugate.",
           2.0, 3.6, 1.08, 0.50, [("cotta", "Cotta", 95.0)], "cotta"),
        _B("pane_tostato", "Pane tostato", "pane",
           "È una doratura: conta solo la superficie. Pane del giorno prima, più asciutto.",
           12.0, 2.7, 0.30, 0.55, [("chiaro", "Chiaro", 120.0), ("dorato", "Dorato", 150.0),
                                   ("scuro", "Scuro", 175.0)], "dorato", surface=True, surface_mm=1.0, evap=0.30,
           signature="FLC"),
        _B("formaggio_toast", "Formaggio sul toast", "formaggio",
           "Una fetta di formaggio che fila sopra il pane: non si gira. Il grasso cola, tienilo lontano dal bordo.",
           3.0, 2.9, 1.05, 0.50, [("fuso", "Fuso", 65.0)], "fuso", flip=False),
        _B("marshmallow", "Marshmallow", "dolce",
           "Quasi tutta aria: brucia in un attimo. Non allontanarti nemmeno per scherzo.",
           20.0, 2.0, 0.25, 0.45, [("dorato", "Dorato", 150.0)], "dorato", surface=True, surface_mm=0.6,
           evap=0.10, flip=False, dose_pass=0.05),
    ]


# ---------------------------------------------------------------------- ricette dell'utente, importa ed esporta
def user_path():
    from ..profile import config_dir

    return os.path.join(config_dir(), "cook_recipes.json")


def _num(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return min(max(v, lo), hi) if math.isfinite(v) else default


def clean(r):
    """La stessa ricetta con ogni valore nei limiti: un numero fuori scala si corregge, non si rifiuta."""
    sear = dict(r.sear) if isinstance(r.sear, dict) else {}
    d = _sear()
    sear = {"mode": sear.get("mode") if sear.get("mode") in SEARS else "none",
            "power": _num(sear.get("power"), 1.0, 100.0, d["power"]),
            "speed": _num(sear.get("speed"), 300.0, MAX_SPEED, d["speed"]),
            "spacing": _num(sear.get("spacing"), 3.0, 50.0, d["spacing"]),
            "angle": _num(sear.get("angle"), 0.0, 180.0, d["angle"]),
            "passes": int(_num(sear.get("passes"), 1, 5, 1))}
    smoke = dict(r.smoke) if isinstance(r.smoke, dict) else {}
    d = _smoke()
    smoke = {"wood": smoke.get("wood") if smoke.get("wood") in WOODS else "none",
             "laps": int(_num(smoke.get("laps"), 1, 10, d["laps"])),
             "power": _num(smoke.get("power"), 1.0, 100.0, d["power"]),
             "speed": _num(smoke.get("speed"), 300.0, MAX_SPEED, d["speed"]),
             "margin": _num(smoke.get("margin"), 3.0, 40.0, d["margin"])}
    done = []
    for row in r.doneness or []:
        try:
            k, lab, t = str(row[0]).strip(), str(row[1]).strip(), float(row[2])
        except (TypeError, ValueError, IndexError):
            continue
        if k and math.isfinite(t) and not any(k == x[0] for x in done):
            done.append((k, lab or k, min(max(t, 30.0), 250.0)))
    if not done:
        done = [("cotto", "Cotto", 65.0)]
    default = r.default if any(r.default == x[0] for x in done) else done[0][0]
    return replace(
        r, kind=r.kind if r.kind in KINDS else "altro", note=str(r.note or "")[:300],
        thickness=_num(r.thickness, 0.5, 60.0, 3.0), c=_num(r.c, 1.0, 5.0, 3.5),
        density=_num(r.density, 0.05, 2.0, 1.05), absorb=_num(r.absorb, 0.05, 1.0, 0.85),
        efficiency=_num(r.efficiency, 0.05, 1.0, 0.45), t_start=_num(r.t_start, -20.0, 40.0, 20.0),
        surface=bool(r.surface), surface_mm=_num(r.surface_mm, 0.2, 10.0, 1.0), evap=_num(r.evap, 0.0, 1.0, 0.0),
        doneness=done, default=default, dose_pass=_num(r.dose_pass, 0.01, 1.0, 0.10),
        speed=_num(r.speed, MIN_SPEED, MAX_SPEED, 12000.0), interval=_num(r.interval, 0.3, 5.0, 1.0),
        defocus_mm=_num(r.defocus_mm, 0.0, 100.0, 20.0), alternate=bool(r.alternate), flip=bool(r.flip),
        sear=sear, signature=clean_signature(r.signature), smoke=smoke, tested=bool(r.tested))


def clean_signature(text):
    """Firma: una riga, al massimo 16 caratteri, solo quelli che il carattere a linea singola sa scrivere."""
    t = "".join(ch for ch in str(text or "").replace("\n", " ") if 32 <= ord(ch) < 127)
    return " ".join(t.split())[:16].strip()


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")[:40] or "ricetta"


def from_dict(d):
    """Una voce di un file → Recipe dell'utente, valida. ValueError se non è una ricetta."""
    if not isinstance(d, dict):
        raise ValueError(tr("La ricetta non è leggibile."))
    name = " ".join(str(d.get("name") or "").split())[:60]
    if not name:
        raise ValueError(tr("La ricetta non ha un nome."))
    known = {f.name for f in fields(Recipe)}
    kw = {k: v for k, v in d.items() if k in known and k not in ("name", "key", "builtin")}
    try:
        r = Recipe(key=slug(name), name=name, builtin=False, **kw)
    except TypeError:
        raise ValueError(tr("La ricetta non è leggibile."))
    return clean(r)


def as_user(r):
    """Copia «dell'utente» di una ricetta: per quelle incluse nome, nota e gradi di cottura nella lingua scelta.
    La chiave di una ricetta dell'utente è sempre il suo nome (stesso nome = stessa ricetta)."""
    if not r.builtin:
        return r
    name = r.label()
    return replace(r, key=slug(name), name=name, note=tr(r.note) if r.note else "",
                   doneness=[(d[0], r.doneness_label(d), d[2]) for d in r.doneness], builtin=False)


def load_user(path=None):
    try:
        with open(path or user_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for d in data.get("recipes", []) if isinstance(data, dict) else []:
        try:
            out.append(from_dict(d))
        except ValueError:
            continue
    return out


def _dump(path, recipes):
    data = {"format": "flcook", "version": 1, "recipes": [as_user(r).to_dict() for r in recipes]}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def save_user(recipes, path=None):
    _dump(path or user_path(), [r for r in recipes if not r.builtin])


def library(path=None):
    """Le ricette dell'utente, poi quelle incluse."""
    return load_user(path) + builtin()


def find(key, is_builtin=None, path=None):
    for r in library(path):
        if r.key == key and (is_builtin is None or r.builtin == is_builtin):
            return r
    return None


def store(recipe, path=None):
    """Salva (o sostituisce, a parità di chiave) una ricetta fra quelle dell'utente. -> la ricetta salvata."""
    r = clean(replace(as_user(recipe), key=slug(recipe.label())))
    items = [x for x in load_user(path) if x.key != r.key]
    save_user([r] + items, path)
    return r


def remove(key, path=None):
    items = load_user(path)
    keep = [x for x in items if x.key != key]
    if len(keep) != len(items):
        save_user(keep, path)
    return len(items) - len(keep)


def export_recipes(path, recipes):
    _dump(path, recipes)


def import_recipes(path):
    """Legge un file .flcook. -> [Recipe] dell'utente (non ancora salvate). ValueError se il file non va bene."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as ex:
        raise ValueError(tr("Non riesco ad aprire il file: {0}", ex))
    except ValueError:
        raise ValueError(tr("Il file non è una raccolta di ricette di Free Laser Cook."))
    if not isinstance(data, dict) or data.get("format") != "flcook" or not isinstance(data.get("recipes"), list):
        raise ValueError(tr("Il file non è una raccolta di ricette di Free Laser Cook."))
    out = []
    for d in data["recipes"][:500]:
        try:
            out.append(from_dict(d))
        except ValueError:
            continue
    if not out:
        raise ValueError(tr("Nel file non ci sono ricette leggibili."))
    return out


# ---------------------------------------------------------------------- il conto
@dataclass
class Plan:
    recipe: Recipe = None
    entry: tuple = ("", "", 60.0)  # (chiave, nome, °C) del grado di cottura
    target: float = 60.0  # °C
    thickness: float = 3.0
    watts: float = 40.0
    polys: list = field(default_factory=list)  # contorno del cibo sul piano [geom.Poly]
    box: tuple = (0.0, 0.0, 0.0, 0.0)  # x0, y0, x1, y1
    area: float = 0.0  # mm²
    energy_side: float = 0.0  # J/mm² per lato
    passes: int = 0  # per lato
    sides: int = 1
    dose: float = 0.0  # J/mm² per passata, effettiva
    power: float = 0.0  # %
    speed: float = 0.0  # mm/min
    interval: float = 1.0
    defocus: float = 20.0
    phases: list = field(default_factory=list)  # [{kind, label, seconds, joule}] (le riempie build_job)
    pauses: int = 0
    seconds: float = 0.0
    joule: float = 0.0  # energia ottica mandata sul cibo e sul legno
    warnings: list = field(default_factory=list)
    blockers: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.blockers


def energy_side(recipe, target, thickness):
    """J/mm² che un lato deve ricevere perché lo strato arrivi a 'target' °C."""
    dt = max(1.0, float(target) - recipe.t_start)
    if recipe.surface:
        depth = min(float(thickness), recipe.surface_mm)
        heat = recipe.c * dt + recipe.evap * LATENT
    else:
        depth = float(thickness) / 2.0 if recipe.flip else float(thickness)
        heat = recipe.c * dt
    return recipe.density * 1e-3 * depth * heat / (recipe.absorb * recipe.efficiency)


FAST_INTERVAL = 2.0  # mm: a testa alzata la riga è larga 2-3 mm, le righe si toccano ancora
FAST_DOSE = 0.20  # J/mm²: tetto della dose per passata nella cottura rapida


def fast_values(recipe):
    """(dose per passata, interlinea) della cottura rapida: righe più larghe e una volta e mezza la dose, così il
    laser lavora a piena potenza. Il tempo lo decide la potenza media: energia totale / W ottici."""
    return (round(min(max(recipe.dose_pass, min(recipe.dose_pass * 1.5, FAST_DOSE)), 1.0), 3),
            max(recipe.interval, FAST_INTERVAL))


def shape_polys(shape, x0, y0, w, h):
    """Contorno del cibo: rettangolo o ellisse di w × h con l'angolo in basso a sinistra in (x0, y0)."""
    if shape == "ellipse":
        n = 72
        return [geom.Poly([(x0 + w / 2 + w / 2 * math.cos(2 * math.pi * k / n),
                            y0 + h / 2 + h / 2 * math.sin(2 * math.pi * k / n)) for k in range(n)], True)]
    return [geom.Poly([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)], True)]


def compute(recipe, watts, polys, doneness=None, target=None, thickness=None, passes=0, bed=(450.0, 440.0),
            vmax=None):
    """Ricetta + macchina + contorno del cibo → Plan (passate, potenza, velocità, avvisi). Non scrive G-code.

    target: °C scelti a mano (None = quelli del grado di cottura). passes: passate per lato a mano (0 = automatico).
    vmax: velocità massima della macchina (mm/min)."""
    recipe = clean(recipe)
    p = Plan(recipe=recipe, entry=recipe.entry(doneness), watts=float(watts or 0.0),
             thickness=_num(thickness, 0.5, 60.0, recipe.thickness), interval=recipe.interval,
             defocus=recipe.defocus_mm)
    p.target = _num(target, 30.0, 250.0, p.entry[2])
    p.polys = [q for q in (polys or []) if q.closed and len(q.pts) >= 3]
    p.sides = 2 if recipe.flip else 1
    if not p.polys:
        p.blockers.append(tr("Non c'è una forma chiusa da cuocere."))
        return p
    xs = [pt[0] for q in p.polys for pt in q.pts]
    ys = [pt[1] for q in p.polys for pt in q.pts]
    p.box = (min(xs), min(ys), max(xs), max(ys))
    p.area = _area(p.polys)
    if p.box[2] - p.box[0] < 5.0 or p.box[3] - p.box[1] < 5.0:
        p.blockers.append(tr("Il cibo è troppo piccolo: servono almeno 5 × 5 mm."))
    m = OVERSCAN + (recipe.smoke["margin"] if recipe.smoke["wood"] != "none" else 0.0)
    if p.box[0] < -1e-6 or p.box[1] < -1e-6 or p.box[2] > bed[0] + 1e-6 or p.box[3] > bed[1] + 1e-6:
        p.blockers.append(tr("Il cibo esce dall'area di lavoro ({0:g} × {1:g} mm): spostalo.", bed[0], bed[1]))
    elif recipe.smoke["wood"] != "none" and (p.box[0] < m or p.box[1] < m or p.box[2] > bed[0] - m
                                             or p.box[3] > bed[1] - m):
        p.blockers.append(tr("Il giro dell'aroma esce dall'area di lavoro: allontana il cibo dal bordo di "
                             "almeno {0:g} mm.", m))
    if p.watts <= 0:
        p.blockers.append(tr("Scrivi la potenza ottica del tuo laser."))
        return p
    top = min(MAX_SPEED, float(vmax)) if vmax else MAX_SPEED
    if top < MIN_SPEED:
        p.blockers.append(tr("La macchina è troppo lenta per cuocere senza bruciare."))
        return p

    p.energy_side = energy_side(recipe, p.target, p.thickness)
    auto = int(math.ceil(p.energy_side / recipe.dose_pass - 1e-9))
    n = int(passes) if passes and int(passes) > 0 else auto
    if n > MAX_PASSES:
        p.warnings.append(tr("Servirebbero {0} passate per lato: ne faccio {1}, con una dose più alta per passata. "
                             "Meglio una fetta più sottile.", n, MAX_PASSES))
        n = MAX_PASSES
    n = max(1, n)
    dose = p.energy_side / n
    speed = min(recipe.speed, top)
    pct = dose * p.interval * speed / 60.0 / p.watts * 100.0
    if pct > 100.0:  # il laser non basta a quella velocità: si rallenta
        speed = p.watts / (dose * p.interval) * 60.0
        pct = 100.0
        if speed < MIN_SPEED:  # nemmeno piano: più passate, ognuna con quello che il laser riesce a dare
            speed = MIN_SPEED
            dose = p.watts / (speed / 60.0 * p.interval)
            n = int(math.ceil(p.energy_side / dose - 1e-9))
            if n > MAX_PASSES:
                p.blockers.append(tr("Con {0:g} W questa cottura chiede troppe passate ({1} per lato): serve una "
                                     "fetta più sottile o un laser più potente.", p.watts, n))
                n = MAX_PASSES
            dose = p.energy_side / n
            pct = dose * p.interval * speed / 60.0 / p.watts * 100.0
    elif pct < MIN_POWER:  # potenza troppo bassa per essere stabile: più veloce, stessa dose
        speed = min(top, MIN_POWER / 100.0 * p.watts / (dose * p.interval) * 60.0)
        pct = dose * p.interval * speed / 60.0 / p.watts * 100.0
    p.passes, p.dose, p.speed, p.power = n, dose, float(round(speed)), min(100.0, max(1.0, pct))
    p.dose = p.power / 100.0 * p.watts / (p.speed / 60.0 * p.interval)  # quella vera, dopo gli arrotondamenti

    if passes and int(passes) > 0 and auto and abs(n - auto) / auto > 0.34:
        p.warnings.append(tr("Passate scelte a mano: {0} per lato, il conto ne darebbe {1}.", n, auto))
    if p.dose > 0.25:
        p.warnings.append(tr("Dose alta per passata ({0:.2f} J/mm²): rischia di bruciare fuori e restare crudo "
                             "dentro.", p.dose))
    if p.interval > 1.5 and 8.0 <= recipe.defocus_mm < 15.0:
        p.warnings.append(tr("Righe a {0:g} mm con la testa alzata di soli {1:g} mm: possono restare strisce. "
                             "Alzala ad almeno 15 mm.", p.interval, recipe.defocus_mm))
    if recipe.defocus_mm < 8.0:
        p.warnings.append(tr("Testa quasi a fuoco: così il laser incide, non cuoce. Alzala di almeno 15 mm."))
    if recipe.kind == "pollame":
        if p.target < POULTRY_T:
            p.blockers.append(tr("Il pollame va portato ad almeno {0:g} °C al cuore.", POULTRY_T))
        p.warnings.append(tr("Pollame: mangialo solo dopo aver misurato {0:g} °C al cuore con il termometro a "
                             "sonda, in più punti.", POULTRY_T))
    if recipe.surface and recipe.kind in ("carne", "pesce"):
        p.warnings.append(tr("Dentro resta crudo: usa solo carne o pesce adatti a essere mangiati crudi."))
    if not recipe.surface and p.thickness > 6.0:
        p.warnings.append(tr("Oltre 6 mm il calore non arriva al cuore prima che fuori si secchi: taglia più "
                             "sottile."))
    if recipe.smoke["wood"] != "none":
        p.warnings.append(tr("Aroma: solo legno massello non trattato, mai compensato o MDF (colle). È un profumo "
                             "leggero, non un'affumicatura vera, e il legno può prendere fuoco: resta lì."))
    return p


def _area(polys):
    """Area (mm²) della regola pari-dispari, sufficiente per forme senza sovrapposizioni."""
    a = 0.0
    for i, q in enumerate(polys):
        inside = sum(1 for j, o in enumerate(polys) if j != i and geom.contains(o, q))
        a += abs(q.area()) * (-1.0 if inside % 2 else 1.0)
    return max(a, 0.0)


# ---------------------------------------------------------------------- il G-code
def signature_polys(text, box):
    """Firma a linea singola, centrata nel riquadro del cibo: larga al massimo il 60%, alta al massimo il 30%."""
    from . import text as textmod

    text = clean_signature(text)
    if not text:
        return []
    path = textmod.text_path(text, SIGN_FONT, 10.0)
    polys = [q for q in geom.flatten(path, 0.05) if len(q.pts) >= 2]
    if not polys:
        return []
    xs = [pt[0] for q in polys for pt in q.pts]
    ys = [pt[1] for q in polys for pt in q.pts]
    tw, th = max(xs) - min(xs), max(ys) - min(ys)
    if tw < 1e-6 or th < 1e-6:
        return []
    bw, bh = box[2] - box[0], box[3] - box[1]
    k = min(bw * 0.6 / tw, bh * 0.3 / th)
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    mx, my = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    return [geom.Poly([(cx + (x - mx) * k, cy + (y - my) * k) for x, y in q.pts], q.closed) for q in polys]


def smoke_polys(box, margin):
    """Il giro dell'aroma: un rettangolo sul legno, a 'margin' mm dal cibo."""
    x0, y0, x1, y1 = box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin
    return [geom.Poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], True)]


def build_job(plan, profile):
    """Plan → GcodeJob. Ordine: [aroma] → lato A → pausa «gira» → [aroma] → lato B → griglia → firma.
    Riempie anche plan.phases, plan.seconds, plan.joule e plan.pauses."""
    from PySide6.QtCore import QRectF

    from .. import gcode_preview
    from .document import CutSettings, clean_pause_msg
    from .gcode import PAUSE_TAG, GcodeJob, LayerStats, _emit_polys, _emit_scan, _scanlines, _Writer, orient_job_preview

    t0 = time.time()
    r = plan.recipe
    job = GcodeJob()
    bed = (profile.bed_x, profile.bed_y)
    no_g55 = bool(getattr(profile, "no_g55", False))
    off = tuple(getattr(profile, "wcs_offset", (0.0, 0.0))) if no_g55 else (0.0, 0.0)

    def mp(bx, by):
        mx, my = profile.to_machine(bx, by)
        return mx - off[0], my - off[1]

    w = _Writer(mp, profile.s_max)
    if getattr(profile, "scan_offsets", None):
        w.scan_offset = profile.scan_offset
    w.raw(f"; FreeLaserCut — Free Laser Cook (in prova): {r.label()}, {r.doneness_label(plan.entry)} "
          f"{plan.target:g} °C, {plan.thickness:g} mm")
    w.raw(f"; {plan.passes} passate per lato × {plan.sides}, {plan.power:.0f}% a {plan.speed:g} mm/min, "
          f"interlinea {plan.interval:g} mm, {plan.dose:.3f} J/mm² per passata, testa alzata di {plan.defocus:g} mm")
    w.raw("G90 G21")
    w.raw("M5 S0")
    if no_g55:
        w.raw("G54")
    else:
        w.raw("G10 L2 P2 X0 Y0")
        w.raw("G55")
    air_off = profile.air_cmds()[1] if hasattr(profile, "air_cmds") else "M9"
    if air_off:
        w.raw(air_off)  # niente aria sul cibo: raffredda la superficie e ci soffia sopra la polvere del laboratorio
    w.raw("M4 S0")
    plan.phases, plan.pauses = [], 0
    job.pauses = []
    marks = []  # (kind, label, prima riga, mm bruciati prima, potenza %, velocità)

    def phase(kind, label, power, speed):
        marks.append([kind, label, len(w.lines), w.cut, power, speed])
        w.raw(f"; {label}")

    def pause(msg):
        msg = clean_pause_msg(msg)
        w.raw("M5 S0")
        w.s = 0.0
        w.raw(f"{PAUSE_TAG} {msg}")
        w.raw("M0")
        w.raw("M4 S0")
        job.pauses.append({"index": plan.pauses, "label": "cook", "msg": msg})
        plan.pauses += 1

    cook = CutSettings(mode="fill", speed=plan.speed, power_max=plan.power, interval=plan.interval,
                       overscan=OVERSCAN, bidirectional=True)
    smoke = r.smoke if r.smoke["wood"] != "none" else None

    def side(name):
        if smoke:
            cs = CutSettings(mode="line", speed=smoke["speed"], power_max=smoke["power"])
            phase("smoke", tr("aroma di {0}, lato {1}", wood_label(smoke["wood"]), name), smoke["power"], smoke["speed"])
            _emit_polys(w, smoke_polys(plan.box, smoke["margin"]) * smoke["laps"], cs)
        for k in range(1, plan.passes + 1):
            ang = 90.0 if (r.alternate and k % 2 == 0) else 0.0
            phase("cook", tr("lato {0}, passata {1} di {2}", name, k, plan.passes), plan.power, plan.speed)
            lines, rot = _scanlines(plan.polys, plan.interval, ang)
            lines = [(y, [(a, b, plan.power) for a, b in segs]) for y, segs in lines]
            if lines:
                _emit_scan(w, lines, rot, cook, bed, 6.0, scan_fix=(ang == 0.0))

    side("A")
    if plan.sides == 2:
        pause(tr("Gira il cibo, chef. Poi premi Riprendi."))
        side("B")
    if r.sear["mode"] != "none":
        s = r.sear
        cs = CutSettings(mode="fill", speed=s["speed"], power_max=s["power"], interval=s["spacing"],
                         overscan=OVERSCAN, bidirectional=True)
        for ang in [s["angle"]] + ([s["angle"] + 90.0] if s["mode"] == "crosshatch" else []):
            for k in range(s["passes"]):
                phase("sear", tr("righe della griglia a {0:g}°", ang % 180.0), s["power"], s["speed"])
                lines, rot = _scanlines(plan.polys, s["spacing"], ang)
                lines = [(y, [(a, b, s["power"]) for a, b in segs]) for y, segs in lines]
                if lines:
                    _emit_scan(w, lines, rot, cs, bed, 6.0, scan_fix=False)
    sign = signature_polys(r.signature, plan.box)
    if sign:
        s = r.sear
        cs = CutSettings(mode="line", speed=s["speed"], power_max=s["power"])
        phase("sign", tr("firma «{0}»", clean_signature(r.signature)), s["power"], s["speed"])
        _emit_polys(w, sign, cs)
    w.raw("M5 S0")
    w.rapid(0.0, 0.0)
    w.raw("G54")
    w.raw("; " + tr("Buon appetito. Misura la temperatura prima di assaggiare."))
    marks.append(["end", "", len(w.lines), w.cut, 0.0, 1.0])

    job.lines = w.lines
    b, mv = w.burn, w.motion
    if b[0] <= b[2]:
        job.bounds = QRectF(b[0], b[1], b[2] - b[0], b[3] - b[1])
    if mv[0] <= mv[2]:
        job.motion_bounds = QRectF(mv[0], mv[1], mv[2] - mv[0], mv[3] - mv[1])
    if mv[0] < -0.01 or mv[1] < -0.01 or mv[2] > bed[0] + 0.01 or mv[3] > bed[1] + 0.01:
        job.warnings.append(tr("La cottura esce dall'area di lavoro: cambia la posizione"))
    mx0, my0 = profile.to_machine(0.0, 0.0)
    job.out_to_bed = (-mx0 + off[0], -my0 + off[1])
    job.preview = gcode_preview.parse(job.lines, profile=profile)
    job.seconds = job.preview.seconds
    orient_job_preview(job, profile, mp)
    plan.joule = 0.0
    for a, nxt in zip(marks, marks[1:]):
        mm = nxt[3] - a[3]
        j = mm / (a[5] / 60.0) * plan.watts * a[4] / 100.0
        plan.joule += j
        plan.phases.append({"kind": a[0], "label": a[1], "mm": mm, "joule": j, "first": a[2], "last": nxt[2]})
    plan.seconds = job.seconds
    cook_mm = sum(ph["mm"] for ph in plan.phases if ph["kind"] == "cook")
    job.layers.append(LayerStats(0, tr("cottura"), "fill", plan.passes * plan.sides, cook_mm, 0, plan.speed, plan.power))
    job.gen_ms = (time.time() - t0) * 1000
    return job


def wood_label(key):
    return {"ciliegio": tr("ciliegio"), "melo": tr("melo"), "faggio": tr("faggio"), "quercia": tr("quercia"),
            "ulivo": tr("ulivo")}.get(key, tr("nessuno"))


def kind_label(key):
    return {"carne": tr("Carne"), "pollame": tr("Pollame"), "pesce": tr("Pesce"), "verdura": tr("Verdura"),
            "pane": tr("Pane"), "formaggio": tr("Formaggio"), "dolce": tr("Dolce")}.get(key, tr("Altro cibo"))


def mmss(sec):
    sec = int(round(sec))
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def chef_says(plan):
    """La battuta dello chef per questo piano (una riga, per sorridere)."""
    r = plan.recipe
    if not plan.ok:
        return tr("Lo chef incrocia le braccia: così non si cucina.")
    if r.kind == "pollame":
        return tr("Lo chef non scherza mai sul pollo. Termometro, sempre.")
    if r.kind == "carne" and not r.surface and plan.target >= 70.0:
        return tr("Ben cotta? Lo chef non giudica. (Giudica.)")
    if r.kind == "dolce":
        return tr("Lo chef consiglia: occhi sul marshmallow, non sul telefono.")
    if r.smoke["wood"] != "none":
        return tr("Profumo di {0}: lo chef approva, i vicini si incuriosiscono.", wood_label(r.smoke["wood"]))
    if plan.seconds > 1200:
        return tr("Una padella farebbe prima. Ma una padella non firma le fettine.")
    if r.kind == "verdura":
        return tr("Verdure al laser: la nonna non capirebbe, ma assaggerebbe.")
    return tr("Nessun fornello è stato maltrattato per questa ricetta.")
