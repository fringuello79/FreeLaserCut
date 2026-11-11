# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.18.12 (da un commento sotto un video: «ho il Longer Ray5 con laser da 40 W, ma non lo trovo
nell'elenco delle macchine»): Longer Ray5 40W nel catalogo.

Dati dall'annuncio ufficiale Longer (longer3d.com, letto l'11/11/2026): area 385 × 385 mm, modulo da 40 W, spot
0,10 × 0,15 mm, 24.000 mm/min. È una macchina diversa dai Ray5 da 5, 10 e 20 W (400 × 400 e 400 × 365, 10.000 mm/min)
e dal B1 40W (450 × 440): le loro voci non devono cambiare.
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from freelasercut import machines
from freelasercut.grbl import optical_watts

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


R40 = "Longer Ray5 40W"
names = machines.catalog_names()
check("Longer Ray5 40W nel catalogo, sceglibile", R40 in names)
check("nomi del catalogo senza doppioni; 58 modelli più il generico", len(names) == len(set(names))
      and len(machines.CATALOG) == 58 and len(names) == 59, (len(machines.CATALOG), len(names)))
longer = [n for n in names if n.startswith("Longer")]
check("nell'elenco sta con gli altri Longer, dopo il Ray5 20W",
      names.index(R40) == names.index("Longer Ray5 20W") + 1 and names[0] == "Longer B1 40W", longer)
p = machines.preset_profile(R40)
check("area di lavoro 385 × 385 mm", (p.bed_x, p.bed_y) == (385.0, 385.0), (p.bed_x, p.bed_y))
check("velocità massima 24.000 mm/min sui due assi", (p.max_rate_x, p.max_rate_y) == (24000.0, 24000.0))
check("spot 0,10 × 0,15 mm", (p.spot_x_mm, p.spot_y_mm) == (0.10, 0.15), (p.spot_x_mm, p.spot_y_mm))
check("potenza «40 W» (40 watt per i limiti che dipendono dalla potenza, come la Lucciola)",
      p.optical_power == "40 W" and optical_watts(p.optical_power) == 40.0, p.optical_power)
check("nome e modello del profilo, valori «di targa»", p.name == R40 and p.model == R40 and bool(p.source))
check("fonte ufficiale Longer dichiarata", machines.SOURCES.get(R40, "").startswith("https://www.longer3d.com/")
      and "ray5-40w" in machines.SOURCES[R40])
check("area non ridotta per prudenza (i due lati dichiarati sono uguali), niente correzione della scansione né G55 tolto",
      R40 not in machines.AREA_NOTE and not p.scan_offsets and not p.no_g55)
others = {n: (machines.preset_profile(n).bed_x, machines.preset_profile(n).bed_y, machines.preset_profile(n).max_rate_x)
          for n in ("Longer Ray5 5W", "Longer Ray5 10W", "Longer Ray5 20W", "Longer B1 40W", "Longer Ray5 Mini")}
check("gli altri Longer restano com'erano", others == {
    "Longer Ray5 5W": (400.0, 400.0, 10000.0), "Longer Ray5 10W": (400.0, 400.0, 10000.0),
    "Longer Ray5 20W": (365.0, 365.0, 10000.0), "Longer B1 40W": (450.0, 440.0, others["Longer B1 40W"][2]),
    "Longer Ray5 Mini": (130.0, 130.0, 12000.0)}, others)
i = machines.identify(banner=["Grbl 1.1f ['$' for help]"], info=["[VER:LGT V1.0.0]"], settings={130: "450", 131: "440"})
check("una scheda Longer con l'area del B1 resta riconosciuta come B1 40W", i.model == "Longer B1 40W", (i.vendor, i.model))
i = machines.identify(banner=["Grbl 1.1f ['$' for help]"], info=["[VER:LGT V1.0.0]"], settings={130: "385", 131: "385"})
check("una scheda Longer 385 × 385 non viene presa per un B1", i.vendor == "Longer" and i.model != "Longer B1 40W",
      (i.vendor, i.model))

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(code_)
