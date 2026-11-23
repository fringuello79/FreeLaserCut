# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.4: Atomstack X30 Pro / S30 Pro / A30 Pro nel catalogo e nel riconoscimento (rapporto del 23/11/2026:
«Manca l'Atomstack a30 pro, x30 pro», la macchina collegata veniva chiamata «Laser GRBL 400×400»).

Dati: pagina ufficiale Atomstack (33 W, spot 0,08 × 0,1 mm, 400 × 400) e due X30 Pro veri (rapporti del 18/11 e del
23/11/2026). Le loro schede non scrivono la marca: a $I rispondono «[VER:1.1h.2022070601:]» e «[OPT:VZ,15,128]», con
area 400 × 400 e velocità massima 6000 mm/min. Con versione, opzioni e area insieme il riconoscimento propone l'X30 Pro
e lascia fra i candidati X20 Pro e X40 Pro; l'affidabilità resta «media» perché la marca non l'ha detta la scheda.

Casi: la voce nuova e le altre com'erano; le righe vere dei due rapporti; ogni indizio tolto uno alla volta (altra
versione, altre opzioni, altra area); scheda che scrive la marca; profilo costruito dalla macchina; traduzioni;
difetti rimessi apposta.
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
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


X30 = "Atomstack X30 Pro / S30 Pro / A30 Pro"
X20 = "Atomstack X20 Pro / S20 Pro / A20 Pro"
X40 = "Atomstack X40 Pro / S40 Pro / A40 Pro"
names = machines.catalog_names()

# ------------------------------------------------------------------ la voce nuova
check("X30 Pro / S30 Pro / A30 Pro nel catalogo, sceglibile, senza doppioni", X30 in names and len(names) == len(set(names))
      and len(names) == len(machines.CATALOG) + 1 and names[-1] == machines.GENERIC)
check("nell'elenco sta fra l'X20 Pro e l'X40 Pro", names.index(X20) + 1 == names.index(X30) == names.index(X40) - 1,
      names[names.index(X20):names.index(X20) + 3])
row = next(c for c in machines.CATALOG if c[0] == X30)
check("voce: Atomstack, 400 × 400 mm, «33 W», 6000 mm/min (letta dalle schede vere)",
      row == (X30, "Atomstack", 400, 400, "33 W", 6000), row)
check("le voci vicine restano com'erano", next(c for c in machines.CATALOG if c[0] == X20) == (X20, "Atomstack", 400, 400, "20 W", 20000)
      and next(c for c in machines.CATALOG if c[0] == X40) == (X40, "Atomstack", 400, 400, "40 W", 20000))
p = machines.preset_profile(X30)
check("profilo pronto: area, 33 W ottici, velocità 6000, spot 0,08 × 0,10, porta 115200, aria M8",
      (p.bed_x, p.bed_y) == (400.0, 400.0) and optical_watts(p.optical_power) == 33 and p.max_rate_x == 6000.0
      and (p.spot_x_mm, p.spot_y_mm) == (0.08, 0.10) and p.baud == 115200 and p.air_on == "M8" and p.name == X30,
      (p.bed_x, p.optical_power, p.max_rate_x, p.spot_x_mm, p.baud, p.air_on))
check("fonte: pagina ufficiale Atomstack", machines.SOURCES.get(X30, "").startswith("https://atomstack.com/products/"))
note = machines.NOTES.get(X30, "")
check("nota: tre nomi per lo stesso modello, marca non scritta dalla scheda, 6000 mm/min letti da macchine vere",
      all(k in note for k in ("S30 Pro", "A30 Pro", "non scrive la marca", "6000 mm/min", "due macchine vere")), note)

# ------------------------------------------------------------------ riconoscimento: le righe vere dei rapporti
INFO = ["[VER:1.1h.2022070601:]", "[OPT:VZ,15,128]"]
SET = {"0": "10", "1": "25", "20": "0", "21": "1", "22": "1", "23": "3", "30": "1000.000", "31": "0.000", "32": "1",
       "100": "80.000", "101": "80.000", "110": "6000.000", "111": "6000.000", "120": "1000.000", "121": "1000.000",
       "130": "400.000", "131": "400.000", "132": "200.000", "133": "300.000", "134": "300.000", "135": "300.000"}


def ident(info=INFO, bx=400, by=400, banner=("Grbl 1.1h ['$' for help]",)):
    st = dict(SET)
    st["130"], st["131"] = f"{bx:.3f}", f"{by:.3f}"
    return machines.identify(banner=list(banner), info=list(info), settings=st)


i = ident()
check("rapporto del 23/11 (USB): riconosciuto X30 Pro, marca Atomstack", i.vendor == "Atomstack" and i.model == X30, (i.vendor, i.model))
check("…con X20 Pro e X40 Pro fra i candidati e l'X30 Pro per primo", i.candidates == [X30, X20, X40], i.candidates)
check("…affidabilità «media», mai «alta»: la marca non l'ha detta la scheda", i.confidence == "media", i.confidence)
n0 = next((t for lv, t in i.notes if "X30 Pro" in t), "")
check("…e una nota che lo dice: versione del firmware, modulo da confermare, le altre due voci",
      all(k in n0 for k in ("versione del firmware", "non scrive la marca", "33 W", "X20 Pro", "X40 Pro")), n0)
check("il nome proposto è quello del modello, non più «Laser GRBL 400×400»", i.name() == X30)
i2 = ident(banner=())
check("senza il messaggio di avvio (collegamento in Wi-Fi, rapporto del 18/11): riconosciuto lo stesso",
      i2.model == X30 and i2.confidence == "media", (i2.model, i2.confidence))
st2 = dict(SET)
st2["120"] = st2["121"] = "1500.000"
i3 = machines.identify(info=INFO, settings=st2)
check("l'accelerazione diversa fra le due macchine vere (1000 e 1500) non cambia il riconoscimento", i3.model == X30)
prof = machines.build_profile(i, SET, INFO)
check("profilo costruito dalla macchina: nome X30 Pro, 33 W, valori letti dalla scheda (400 × 400, 6000, 1000)",
      prof.name == X30 and optical_watts(prof.optical_power) == 33 and (prof.bed_x, prof.bed_y) == (400.0, 400.0)
      and prof.max_rate_x == 6000.0 and prof.accel_x == 1000.0 and prof.rx_buffer == 128,
      (prof.name, prof.optical_power, prof.bed_x, prof.max_rate_x, prof.accel_x, prof.rx_buffer))

# ------------------------------------------------------------------ un indizio alla volta in meno: niente X30 da solo
i = ident(info=["[VER:1.1h.20190825:]", "[OPT:VZ,15,128]"])
check("altra versione del firmware: nessuna marca, nessun modello scelto; l'X30 Pro è solo fra i candidati",
      i.vendor == "" and i.model == "" and X30 in i.candidates and len(i.candidates) > 3, (i.vendor, i.model, i.candidates))
i = ident(info=["[VER:1.1h.2022070601:]", "[OPT:V,15,128]"])
check("stessa versione ma altre opzioni: nessun modello scelto", i.vendor == "" and i.model == "", (i.vendor, i.model))
i = ident(info=["[VER:1.1h.2022070601:]"])
check("senza la riga delle opzioni: nessun modello scelto", i.model == "")
i = ident(bx=410, by=400)
check("stessa versione ma area 410 × 400: nessun modello scelto", i.vendor == "" and i.model != X30, (i.vendor, i.model))
i = ident(bx=400, by=850)
check("stessa versione con il telaio lungo (400 × 850): nessun modello scelto", i.model != X30)
i = ident(bx=401.5, by=399)
check("area scritta un po' diversa (401,5 × 399): riconosciuto", i.model == X30)
i = ident(info=["[VER:1.1h.2022070601:ATOMSTACK]", "[OPT:VZ,15,128]"])
check("scheda che scrive la marca: strada di sempre, i tre modelli da 400 × 400 fra cui scegliere, nessuno scelto da solo",
      i.vendor == "Atomstack" and i.model == "" and set(i.candidates) == {X20, X30, X40}, (i.model, i.candidates))
i = ident(info=["[VER:1.1h.2022070601:]", "[OPT:VZ,15,128]", "[MSG:FW:LGT V1.2.3|MB:LS_ESP32]"], bx=450, by=440)
check("un Longer B1 resta un Longer B1", i.vendor == "Longer" and i.model == "Longer B1 40W", (i.vendor, i.model))
i = ident(info=["[VER:1.1h.2022070601:ORTUR]", "[OPT:VZ,15,128]"])
check("un'altra marca scritta dalla scheda vince sulla versione", i.vendor == "Ortur" and i.model != X30, (i.vendor, i.model))
b = machines.base_profile(machines.identify(settings={"130": "400", "131": "400"}))
check("solo l'area 400 × 400, senza altro: nessun valore dell'X30 Pro attaccato per sbaglio", b.model != X30, b.model)

# ------------------------------------------------------------------ traduzioni
for lang in ("en", "es", "fr", "pt"):
    d = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    t, t2 = d.get(note, ""), d.get(next(k for k in d if k.startswith("Atomstack X30 Pro riconosciuto")), "")
    check(f"nota del modello e nota del riconoscimento tradotte in «{lang}», con i numeri giusti",
          bool(t) and t != note and "6000 mm/min" in t and "S30 Pro" in t and bool(t2) and "33 W" in t2 and "{0}" in t2,
          (t[:60], t2[:60]))

# ------------------------------------------------------------------ difetti rimessi apposta
caught = []
orig = machines._ATOM_VER
import re  # noqa: E402

machines._ATOM_VER = re.compile(r"\[VER:1\.1H\.")  # 1. qualsiasi GRBL 1.1h scambiato per un Atomstack
caught.append(ident(info=["[VER:1.1h.20190825:]", "[OPT:VZ,15,128]"]).model == X30)
machines._ATOM_VER = orig
orig = machines._ATOM_OPT
machines._ATOM_OPT = re.compile(r"")  # 2. le opzioni non si guardano più
caught.append(ident(info=["[VER:1.1h.2022070601:]", "[OPT:V,15,128]"]).model == X30)
machines._ATOM_OPT = orig
orig = machines.ATOM_400
machines.ATOM_400 = (X20, X30, X40)  # 3. proposto il modello sbagliato (20 W invece di 33)
caught.append(ident().model != X30)
machines.ATOM_400 = orig
cat = machines.CATALOG
machines.CATALOG = tuple(c for c in cat if c[0] != X30)  # 4. voce tolta dal catalogo
caught.append(X30 not in machines.catalog_names())
machines.CATALOG = tuple((c[0], c[1], c[2], c[3], "20 W", c[5]) if c[0] == X30 else c for c in cat)  # 5. potenza sbagliata
caught.append(optical_watts(machines.preset_profile(X30).optical_power) != 33)
machines.CATALOG = cat
check("cinque difetti rimessi apposta (versione troppo larga, opzioni ignorate, modello sbagliato proposto, voce "
      "tolta, potenza sbagliata): tutti visti", all(caught) and len(caught) == 5, caught)
check("…e tolti i difetti torna tutto giusto", ident().model == X30 and ident(info=["[VER:1.1h.20190825:]", "[OPT:VZ,15,128]"]).model == "")

print(f"\n{sum(results)}/{len(results)} controlli superati")
sys.exit(0 if all(results) else 1)
