# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Libreria materiali per il Longer B1 40W.

Valori di partenza dalle tabelle ufficiali Longer per il B1 40W (agosto 2023),
convertiti nel formato di FreeLaserCut: potenza in %, velocità in mm/min, passate,
sfocatura consigliata (spostamento del fuoco, si fa a mano: la lente è fissa).
Sono un punto di partenza: legno e lotti diversi cambiano. Con il "Test materiale"
si affinano e si salvano come voci proprie.
"""
import json
import os
from dataclasses import asdict, dataclass, field

from ..profile import config_dir


@dataclass
class Material:
    name: str
    operation: str  # incisione | taglio
    thickness: float = 0.0  # mm (0 = superficie)
    power: float = 30.0  # %
    speed: float = 1000.0  # mm/min
    passes: int = 1
    defocus: float = 0.0  # mm
    mode: str = "fill"  # fill | line | image
    interval: float = 0.1
    note: str = ""
    source: str = "Longer B1 40W"
    machine: str = "Longer B1 40W"

    def key(self):
        return (self.name.lower(), self.operation, round(self.thickness, 2))

    def label(self):
        t = f" {self.thickness:g} mm" if self.thickness else ""
        return f"{self.operation.capitalize()}{t}"

    def summary(self):
        from .. import units

        s = f"{self.power:g}% · {units.fmt(self.speed)} · {self.passes}×"
        if self.defocus:
            s += f" · sfocatura {self.defocus:g} mm"
        return s


_E, _C = "incisione", "taglio"
# nome, operazione, spessore, potenza, velocità, passate, sfocatura, nota
_LONGER_B1_40W = [
    ("Bambù", _E, 0, 50, 10000, 1, 0, ""),
    ("Cartone", _E, 0, 40, 10000, 1, 0, ""),
    ("Legno duro", _E, 0, 40, 10000, 1, 0, ""),
    ("Gomma (per timbri)", _E, 0, 70, 5000, 1, 0, ""),
    ("Ceramica", _E, 0, 80, 4000, 1, 0, ""),
    ("Pino", _E, 0, 50, 10000, 1, 0, ""),
    ("Pelle / cuoio", _E, 0, 30, 10000, 1, 0, ""),
    ("Denim (jeans)", _E, 0, 30, 10000, 1, 0, ""),
    ("Carta kraft", _E, 0, 10, 6000, 1, 0, ""),
    ("Specchio", _E, 0, 60, 10000, 1, 0, "Sul retro verniciato"),
    ("Schiuma ad alta densità", _E, 0, 15, 10000, 1, 0, ""),
    ("Metallo verniciato a polvere (nero)", _E, 0, 100, 300, 1, 0, "Lento: rimuove la vernice"),
    ("Ciottolo / pietra", _E, 0, 60, 5000, 1, 0, ""),
    ("Tiglio (basswood)", _E, 0, 30, 10000, 1, 0, ""),
    ("Alluminio anodizzato colorato", _E, 0, 60, 6000, 1, 0, "Testato su viola/rosa"),
    ("Acciaio inox", _E, 0, 80, 10000, 1, 0, "Marcatura superficiale"),
    ("Vetro (verniciato blu)", _E, 0, 50, 3000, 1, 0, "Il vetro trasparente va verniciato: il blu 450 nm lo attraversa"),
    ("Acrilico nero", _E, 0, 30, 10000, 1, 0, ""),
    ("Acrilico traslucido (arancio)", _E, 0, 25, 2500, 1, 0, "Acrilico trasparente o bianco: non assorbe il blu"),
    ("Piastra rame per PCB", _E, 0, 90, 5000, 1, 0, ""),
    ("MDF", _E, 0, 35, 10000, 1, 0, ""),
    ("Cartone", _C, 3, 100, 6000, 1, 0, ""),
    ("Acrilico (nero/colorato)", _C, 3, 100, 500, 1, 0, ""),
    ("Acrilico (nero/colorato)", _C, 10, 100, 130, 2, 0, ""),
    ("Acrilico (nero/colorato)", _C, 15, 100, 100, 2, 10, ""),
    ("Acrilico (nero/colorato)", _C, 50, 100, 300, 22, 10, "Molte passate: controlla la temperatura"),
    ("Tessuto non tessuto (TNT)", _C, 0.18, 100, 6000, 1, 0, ""),
    ("Pino", _C, 15, 100, 150, 1, 2, ""),
    ("Pino", _C, 20, 100, 200, 1, 2, ""),
    ("Pino", _C, 30, 100, 100, 3, 10, ""),
    ("Pelle / cuoio", _C, 0.5, 100, 7000, 1, 0, ""),
    ("Paulonia", _C, 15, 100, 350, 1, 2.5, ""),
    ("Paulonia", _C, 20, 100, 300, 1, 2.5, ""),
    ("Paulonia", _C, 25, 100, 200, 1, 10, ""),
    ("Denim (jeans)", _C, 0.5, 100, 3500, 1, 0, ""),
    ("Carta kraft", _C, 0.1, 100, 18000, 1, 0, ""),
    ("Tiglio (basswood)", _C, 2, 100, 1800, 1, 0, ""),
    ("Tiglio (basswood)", _C, 3, 100, 1400, 1, 0, ""),
    ("Tiglio (basswood)", _C, 5, 100, 900, 1, 0, ""),
    ("Tiglio (basswood)", _C, 6, 100, 600, 1, 0, ""),
    ("Tiglio (basswood)", _C, 8, 100, 270, 1, 2.5, ""),
    ("Tiglio (basswood)", _C, 9.5, 100, 450, 1, 2.5, ""),
    ("Tiglio (basswood)", _C, 15, 100, 150, 1, 2.5, ""),
    ("Tiglio (basswood)", _C, 20, 100, 100, 1, 10, ""),
    ("Tiglio (basswood)", _C, 40, 100, 300, 20, 10, "Molte passate: sorveglia sempre"),
    ("Legno duro", _C, 11, 100, 250, 1, 2.5, ""),
    ("Acciaio inox (lamina)", _C, 0.05, 100, 3000, 1, 0, ""),
    ("Acciaio inox (lamina)", _C, 0.1, 100, 500, 1, 0, ""),
    ("Acciaio inox (lamina)", _C, 0.15, 100, 100, 1, 0, ""),
    ("MDF", _C, 5, 100, 700, 1, 2.5, ""),
    ("MDF", _C, 12, 100, 500, 5, 2.5, ""),
]


def builtin():
    out = []
    for name, op, th, pw, sp, ps, df, note in _LONGER_B1_40W:
        out.append(Material(name, op, th, pw, sp, ps, df, "fill" if op == _E else "line", 0.1, note))
    return out


def user_path():
    return os.path.join(config_dir(), "materials.json")


def load_user():
    try:
        with open(user_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return [Material(**{k: v for k, v in d.items() if k in Material.__dataclass_fields__}) for d in data]
    except (OSError, ValueError, TypeError):
        return []


def save_user(items):
    with open(user_path(), "w", encoding="utf-8") as fh:
        json.dump([asdict(m) for m in items], fh, indent=1, ensure_ascii=False)


MIN_SPEED = 100.0  # mm/min: sotto, invece di rallentare ancora, la stima aggiunge passate


def scaled(m: Material, ratio):
    """Stima di partenza per un laser di potenza diversa dal B1 40W della tabella (0.19.2).

    ratio = potenza ottica del laser dell'utente / potenza ottica del B1 40W. L'idea è tenere uguale l'energia per
    millimetro: si alza la potenza in percentuale; arrivati al 100% si rallenta; sotto MIN_SPEED si aggiungono
    passate. È una stima (fuoco, punto e materiale contano quanto la potenza): va verificata con il test materiale.
    Con ratio assente o vicino a 1 la voce resta com'è."""
    if not ratio or ratio <= 0 or abs(ratio - 1.0) < 0.03:
        return m
    from dataclasses import replace

    pct = m.power / ratio
    speed, passes = float(m.speed), int(m.passes)
    if pct > 100.0:
        speed *= 100.0 / pct
        pct = 100.0
        if speed < MIN_SPEED:
            passes = max(passes, int(-(-passes * MIN_SPEED // speed)))
            speed = MIN_SPEED
    return replace(m, power=float(max(1, round(pct))), speed=_round2(speed), passes=passes)


def _round2(v):
    """Due cifre significative: una stima non ha senso scritta al millimetro al minuto."""
    if v <= 0:
        return v
    import math

    k = 10 ** (int(math.floor(math.log10(v))) - 1)
    return float(round(v / k) * k)


def library(ratio=None):
    """Voci dell'utente (prima, hanno la precedenza) + tabella Longer.
    ratio: vedi scaled(); vale solo per le voci della tabella, quelle dell'utente restano come le ha salvate."""
    user = load_user()
    keys = {m.key() for m in user}
    return user + [scaled(m, ratio) for m in builtin() if m.key() not in keys]


def apply_to_layer(m: Material, cs):
    cs.mode = m.mode if cs.mode != "image" or m.mode == "image" else "image"
    cs.speed = m.speed
    cs.power_max = m.power
    cs.passes = m.passes
    cs.air = True
    if cs.mode in ("fill", "offset_fill"):
        cs.interval = m.interval
    cs.burn_curve = ""  # un altro materiale: la curva imparata del precedente non vale più
    if not cs.name:
        cs.name = f"{m.name} · {m.label()}"
