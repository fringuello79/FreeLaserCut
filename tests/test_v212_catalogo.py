# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: voci nuove del catalogo dei laser.

A. VEVOR A7 5W (foto di un utente: è la Atomstack A5 Pro venduta da VEVOR); B. Sculpfun iCube Ultra Dual, diodo da 12 W e
modulo infrarosso da 1,2 W a 1064 nm (domanda di un utente): due voci, area prudente 135 × 135 con 150 × 135 dichiarata,
famiglia per il riconoscimento, note con l'avvertenza sul raggio che non si vede, accelerazione 500 per la stima dei
tempi; C. tabella dei materiali Sculpfun «iCube Ultra Engraving Parameter» (interlinea 0,05 mm); D. traduzioni.
Uso: python tests/test_v212_catalogo.py
"""
import json
import os
import sys
import tempfile

os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from freelasercut import i18n, machines  # noqa: E402
from freelasercut.core import materials as mats  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info else ""), flush=True)


VEVOR = "VEVOR A7 5W"
D12, DIR = "Sculpfun iCube Ultra Dual 12W", "Sculpfun iCube Ultra Dual 1.2W IR"
ULTRA = "Sculpfun iCube Ultra 12W"
names = machines.catalog_names()
cat = {c[0]: c for c in machines.CATALOG}
check("le tre voci nuove nel catalogo, senza doppioni, generico in fondo", all(n in names for n in (VEVOR, D12, DIR))
      and len(names) == len(set(names)) == len(machines.CATALOG) + 1 and names[-1] == machines.GENERIC, len(machines.CATALOG))

# ====================================================================== A. VEVOR A7
print("--- A. VEVOR A7")
p = machines.preset_profile(VEVOR)
check("VEVOR A7: 410 × 400 mm, 10.000 mm/min, 5–6 W, spot 0,08 × 0,08", cat[VEVOR] == (VEVOR, "VEVOR", 410, 400, "5–6 W", 10000)
      and (p.bed_x, p.bed_y, p.spot_x_mm, p.spot_y_mm) == (410, 400, 0.08, 0.08), (cat[VEVOR], p.spot_x_mm))
a5 = cat["Atomstack A5 Pro"]
check("…gli stessi valori dell'Atomstack A5 Pro (è la stessa macchina)", (a5[2], a5[3], a5[5]) == (410, 400, 10000)
      and machines.SPOTS["Atomstack A5 Pro"] == machines.SPOTS[VEVOR])
n = machines.NOTES.get(VEVOR, "")
check("nota: A5 Pro, le altre misure vendute con lo stesso nome, «Leggi dalla macchina», pulsante d'emergenza",
      all(k in n for k in ("Atomstack A5 Pro", "380 × 400", "400 × 400", "«Leggi dalla macchina»", "emergenza")), n)
check("fonte dichiarata", machines.SOURCES.get(VEVOR, "").startswith("https://www.bestbuy.com/"), machines.SOURCES.get(VEVOR))

# ====================================================================== B. iCube Ultra Dual
print("--- B. iCube Ultra Dual")
p12, pir = machines.preset_profile(D12), machines.preset_profile(DIR)
check("Dual 12W: 135 × 135 per prudenza (dichiarata 150 × 135), 12 W, spot 0,08, 10.000 mm/min",
      cat[D12] == (D12, "Sculpfun", 135, 135, "12 W", 10000) and machines.AREA_NOTE[D12] == (150, 135)
      and (p12.spot_x_mm, p12.spot_y_mm) == (0.08, 0.08), cat[D12])
check("Dual 1.2W IR: stessa area, «1,2 W (infrarosso)», spot 0,03", cat[DIR] == (DIR, "Sculpfun", 135, 135, "1,2 W (infrarosso)", 10000)
      and machines.AREA_NOTE[DIR] == (150, 135) and (pir.spot_x_mm, pir.spot_y_mm) == (0.03, 0.03), cat[DIR])
check("accelerazione 500 nelle tre iCube Ultra (dalla tabella Sculpfun, per la stima dei tempi)",
      all(machines.ACCEL.get(m) == 500.0 for m in (ULTRA, D12, DIR)) and (pir.accel_x, pir.accel_y) == (500.0, 500.0))
check("la iCube Ultra normale resta 150 × 150", cat[ULTRA][2:4] == (150, 150) and ULTRA not in machines.AREA_NOTE)
check("fonti: pagina ufficiale Sculpfun", all(machines.SOURCES.get(m, "").startswith("https://eu.sculpfun.com/") for m in (D12, DIR)))
nd, nir, nu = machines.NOTES.get(D12, ""), machines.NOTES.get(DIR, ""), machines.NOTES.get(ULTRA, "")
check("nota della Dual: modulo montato, 150 × 135 anche col finecorsa del modulo IR, cavo USB, chiavetta, configurazione guidata",
      all(k in nd for k in ("modulo montato", "150 × 135", "finecorsa", "USB", "chiavetta", "configurazione guidata")), nd)
check("nota dell'infrarosso: 1064 nm che non si vede, sportello ($safe=1), occhiali per 1064 nm, niente taglio",
      all(k in nir for k in ("raggio a 1064 nm non si vede", "$safe=1", "occhiali che riportano 1064 nm", "niente taglio"))
      and "1064" not in nd, nir[-300:])
check("nota della iCube Ultra normale: rimanda alle voci Dual", "iCube Ultra Dual" in nu and "Bluetooth" in nu, nu)
check("famiglia per il riconoscimento", machines.ICUBE_DUAL in machines.FAMILIES and machines.ICUBE_DUAL == (D12, DIR))


def ident(bx, by):
    return machines.identify(banner=["Grbl 1.1f ['$' for help]"], info=["[MSG:SCULPFUN]"], settings={130: str(bx), 131: str(by)})


for bx, by in ((150, 135), (135, 150)):
    i = ident(bx, by)
    check(f"scheda Sculpfun {bx} × {by}: Dual 12W, l'IR fra i candidati e il messaggio sul modulo che non si legge",
          i.model == D12 and i.candidates == [D12, DIR] and any("non si legge" in t for _k, t in i.notes), (i.model, i.candidates))
i = ident(150, 150)
check("scheda Sculpfun 150 × 150: resta la iCube Ultra 12W", i.model == ULTRA, i.model)
i = ident(150, 130)
check("scheda Sculpfun 150 × 130: restano i C1", not i.model and set(i.candidates) == {"Sculpfun C1 3W", "Sculpfun C1 6W"},
      (i.model, i.candidates))

# ====================================================================== C. materiali
print("--- C. tabella dei materiali")
ir, d12, u12 = mats.official(DIR), mats.official(D12), mats.official(ULTRA)
check("infrarosso: 7 incisioni, nessun taglio", len(ir) == 7 and all(m.operation == mats._E for m in ir))
check("12 W: 11 incisioni e 3 tagli, uguali per la Dual e la normale (stesso diodo)",
      len(d12) == 14 and sum(m.operation == mats._C for m in d12) == 3
      and [(m.name, m.operation, m.power, m.speed) for m in d12] == [(m.name, m.operation, m.power, m.speed) for m in u12])
check("interlinea 0,05 mm, fonte «Tabella Sculpfun iCube Ultra», modello giusto",
      all(m.interval == 0.05 and m.source == "Tabella Sculpfun iCube Ultra" for m in ir + d12)
      and all(m.machine == DIR for m in ir) and all(m.machine == ULTRA for m in u12))
row = {(m.name, m.operation, m.thickness): (m.power, m.speed) for m in ir + d12}
check("alcuni valori della tabella: acciaio inox IR 100%/5000, ottone IR 100%/1000, compensato 3 mm 100%/420",
      next(m for m in ir if m.name == "Acciaio inox").speed == 5000 and next(m for m in ir if m.name == "Ottone").speed == 1000
      and row[("Compensato di tiglio", mats._C, 3.0)] == (100.0, 420.0))
e1 = mats.official("Sculpfun E1 12W")
check("la serie E1 non cambia: interlinea 0,1 e la sua fonte", e1 and all(m.interval == 0.1 and m.source == "Tabella Sculpfun E1" for m in e1))

# ====================================================================== D. traduzioni
print("--- D. traduzioni")
keys = [machines.NOTES[VEVOR], machines.NOTES[D12], machines.NOTES[DIR]]
missing = []
i18n.set_language("it")
raw = {}
for lang in ("en", "es", "fr", "pt"):
    catl = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    for src in catl:
        if "VEVOR A7 da 5 W" in src or "Sculpfun iCube Ultra Dual: scegli" in src or "Infrarosso: il raggio a 1064" in src \
                or "Hai la Dual o hai montato" in src:
            raw.setdefault(lang, []).append(src)
check("le note nuove ci sono nelle 4 lingue", all(len(raw.get(lang, [])) == 4 for lang in ("en", "es", "fr", "pt")),
      {k: len(v) for k, v in raw.items()})

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
