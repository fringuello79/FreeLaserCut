# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.9: Atomstack Hurricane (CO2 da 55 W) nel catalogo (chiesto da Ale il 24/11/2026).

Dati dalle fonti ufficiali Atomstack (lette il 25/11/2026):
- pagina prodotto atomstack.com/products/atomstack-hurricane: tubo CO2 da 55 W a 10,6 µm;
- pagina «Product Support», PDF «Instructions for Using … Software on AtomStack Hurricane»: cavo USB, 460800 baud,
  origine del piano davanti a sinistra, fuoco a 8 mm;
- tabella dei parametri ufficiale: incisione fino a 24000 mm/min; area 500 × 300 mm e 600 mm/s dalla pagina prodotto
  e dalle recensioni.
L'homing porta la testa in fondo a sinistra (utenti); il segno delle coordinate dopo l'homing non è documentato, quindi
l'angolo non è fissato nel catalogo: lo ricava l'homing, come per gli altri.

Casi: voce nel catalogo, sceglibile, senza doppioni, accanto agli altri Atomstack; area, potenza, velocità, porta
seriale, fonte, nota; gli altri modelli non cambiano; una scheda Atomstack 500 × 300 la propone; traduzioni della nota.
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from freelasercut import machines  # noqa: E402
from freelasercut.grbl import optical_watts  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""))


HUR = "Atomstack Hurricane 55W CO2"
names = machines.catalog_names()
check("Atomstack Hurricane nel catalogo, sceglibile, senza doppioni", HUR in names and len(names) == len(set(names))
      and len(names) == len(machines.CATALOG) + 1, len(machines.CATALOG))
check("nell'elenco sta con gli altri Atomstack", names[names.index(HUR) - 1].startswith("Atomstack")
      and names[names.index(HUR) + 1].startswith("Atomstack"), names[names.index(HUR) - 1: names.index(HUR) + 2])
p = machines.preset_profile(HUR)
check("area di lavoro 500 × 300 mm (pagina ufficiale)", (p.bed_x, p.bed_y) == (500.0, 300.0), (p.bed_x, p.bed_y))
check("potenza «55 W (CO2)», letta come 55 W", p.optical_power == "55 W (CO2)" and optical_watts(p.optical_power) == 55.0,
      p.optical_power)
check("velocità massima 36000 mm/min (600 mm/s, pagina ufficiale)", (p.max_rate_x, p.max_rate_y) == (36000.0, 36000.0))
check("porta seriale a 460800 baud (istruzioni ufficiali), già nel profilo pronto", p.baud == 460800, p.baud)
check("angolo non fissato nel catalogo: lo ricava l'homing (il segno delle coordinate non è documentato)",
      HUR not in machines.CORNER and not p.origin_corner, p.origin_corner)
check("fonte ufficiale Atomstack; nome, modello e valori «di targa»",
      machines.SOURCES.get(HUR) == "https://atomstack.com/products/atomstack-hurricane" and p.name == HUR
      and p.model == HUR and bool(p.source))
note = machines.NOTES.get(HUR, "")
check("la nota dice: 460800, area, homing, fuoco a 8 mm, il Puntino non serve, valori non ancora provati",
      all(x in note for x in ("460800", "500 × 300", "fondo a sinistra", "8 mm", "Puntino", "Leggi dalla macchina",
                              "non sono ancora stati provati")), note)
check("area non ridotta, niente correzione della scansione né G55 tolto, aria con M8 (nessun dato diverso)",
      HUR not in machines.AREA_NOTE and not p.scan_offsets and not p.no_g55 and p.air_on == "M8")
a = machines.preset_profile("Atomstack A70 Max"), machines.preset_profile("Atomstack Swift 12W")
check("gli altri Atomstack restano com'erano", (a[0].bed_x, a[0].bed_y, a[0].max_rate_x, a[0].baud) ==
      (800.0, 800.0, 24000.0, 115200) and (a[1].bed_x, a[1].baud) == (300.0, 460800))

# una scheda Atomstack che dichiara 500 × 300: il riconoscimento propone la Hurricane
ident = machines.identify(banner=["Grbl 1.1h ['$' for help]"], info=["[VER:1.1h.ATOMSTACK HURRICANE:]", "[OPT:VZ,15,128]"],
                          settings={130: 500.0, 131: 300.0, 110: 36000.0, 111: 36000.0, 30: 1000.0}, baud=460800)
model, cands = ident.model, list(ident.candidates or [])
check("una scheda Atomstack 500 × 300 a 460800 baud: il riconoscimento propone la Hurricane",
      model == HUR or HUR in cands, (model, cands[:4]))

for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    tr_ = cat.get(note, "")
    check(f"nota tradotta ({lang}) con i numeri giusti", bool(tr_) and "460800" in tr_ and "500" in tr_ and "8 mm" in tr_)

ok = sum(results)
print(f"{ok}/{len(results)} prove superate")
sys.exit(0 if ok == len(results) else 1)
