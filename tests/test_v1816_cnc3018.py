# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.18.16: una CNC 3018 con il laser al posto del mandrino nel catalogo (Genmitsu 3018-PRO).

Dati dalle fonti ufficiali SainSmart (lette l'11/11/2026):
- pagina prodotto della Genmitsu 3018-PRO: area 300 × 180 mm (Z 45), 1200 mm/min, niente finecorsa né homing;
- manuale del loro kit laser per 3018: 5,5 W a 445 nm, fuoco regolabile a mano, $32=1 per usare il laser (0 per il
  mandrino), e l'avviso che all'accensione o collegando l'USB il laser può accendersi per un attimo.
Lo spot non è dichiarato: resta quello comune.

Casi: la voce (area, velocità, potenza, fonte, nota con $32, finecorsa e avviso); 115200 baud come tutte; una scheda
GRBL senza marca con l'area 300 × 180 riconosciuta come questo modello, con gli avvisi di modalità laser spenta e
homing assente; il profilo costruito dalla scheda che tiene i valori letti; una scheda 300 × 180 di un'altra marca che
non viene presa per questa; gli altri Genmitsu com'erano; conteggio del catalogo; traduzioni della nota.
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

from freelasercut import machines
from freelasercut.grbl import optical_watts

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


N = "Genmitsu CNC 3018-PRO con modulo laser"
names = machines.catalog_names()
check("la CNC 3018 con modulo laser è nel catalogo, sceglibile; almeno 61 modelli più il generico, senza doppioni",
      N in names and len(machines.CATALOG) >= 61 and len(names) == len(machines.CATALOG) + 1 == len(set(names)),
      len(machines.CATALOG))
check("nell'elenco sta con gli altri Genmitsu e si trova cercando «3018»",
      names.index(N) + 1 == names.index("Genmitsu Jinsoku LC-40") and [n for n in names if "3018" in n] == [N])
p = machines.preset_profile(N)
check("area di lavoro 300 × 180 mm e velocità massima 1200 mm/min (pagina ufficiale)",
      (p.bed_x, p.bed_y, p.max_rate_x, p.max_rate_y) == (300.0, 180.0, 1200.0, 1200.0), (p.bed_x, p.bed_y, p.max_rate_x))
check("potenza «5,5 W» (manuale del kit laser)", p.optical_power == "5,5 W" and optical_watts(p.optical_power) == 5.5, p.optical_power)
check("porta seriale a 115200 baud come gli altri; spot non dichiarato: resta quello comune",
      p.baud == 115200 and N not in machines.BAUD and N not in machines.SPOTS and (p.spot_x_mm, p.spot_y_mm) == (0.08, 0.10))
check("fonte ufficiale SainSmart dichiarata; nome, modello e valori «di targa»",
      machines.SOURCES.get(N, "").startswith("https://www.sainsmart.com/products/") and "3018-pro" in machines.SOURCES[N]
      and p.name == N and p.model == N and bool(p.source))
note = machines.NOTES.get(N, "")
check("la nota dice: modalità laser da accendere ($32=1, e 0 per il mandrino), niente finecorsa, fuoco a mano",
      "$32=1" in note and "mandrino" in note and "finecorsa" in note and "fuoco" in note, note)
check("…l'avviso del manuale (il laser può accendersi per un attimo all'accensione) e che vale per le altre CNC 3018 GRBL",
      "accendersi per un attimo" in note and "occhiali" in note and "altre CNC 3018" in note and "Leggi dalla macchina" in note, note)
check("area non ridotta, niente correzione della scansione né G55 tolto",
      N not in machines.AREA_NOTE and not p.scan_offsets and not p.no_g55)

# ------------------------------------------------------------------ riconoscimento
board = dict(banner=["Grbl 1.1f ['$' for help]"], info=["[VER:1.1f.20170801:]", "[OPT:V,15,128]"],
             settings={22: "0", 30: "1000", 32: "0", 110: "1000.000", 111: "1000.000", 130: "300.000", 131: "180.000"})
i = machines.identify(**board)
texts = " | ".join(t for _k, t in i.notes)
check("una scheda GRBL senza marca con l'area 300 × 180 viene proposta come questo modello, dicendo di controllare",
      i.model == N and not i.vendor and "solo dall'area di lavoro" in texts, (i.vendor, i.model, texts))
check("…con l'avviso che la modalità laser è spenta ($32=0) e che non c'è homing",
      "$32=0" in texts and "Homing disattivato" in texts, texts)
q = machines.build_profile(i, board["settings"], board["info"])
check("…il profilo costruito dalla scheda tiene i valori letti (area, 1000 mm/min, modalità laser spenta) e la potenza del modello",
      (q.bed_x, q.bed_y, q.max_rate_x, q.laser_mode, q.optical_power) == (300.0, 180.0, 1000.0, False, "5,5 W"),
      (q.bed_x, q.bed_y, q.max_rate_x, q.laser_mode, q.optical_power))
i2 = machines.identify(banner=["Grbl 1.1h"], info=["[VER:1.1h.2024:]"], settings={130: "300", 131: "180", 32: "1", 22: "1"})
t2 = " | ".join(t for _k, t in i2.notes)
check("con la modalità laser accesa e l'homing attivo quegli avvisi non ci sono", i2.model == N and "$32=0" not in t2 and "Homing" not in t2, t2)
i3 = machines.identify(banner=["Grbl 1.1f"], info=["[VER:1.1f ATOMSTACK:]"], settings={130: "300", 131: "180"})
check("una scheda di un'altra marca con la stessa area non viene presa per la Genmitsu", i3.vendor == "Atomstack" and i3.model != N,
      (i3.vendor, i3.model))
i4 = machines.identify(banner=["Grbl 1.1f"], info=["[VER:1.1f.20170801:]"], settings={130: "400", 131: "300"})
check("una CNC più grande (400 × 300) non viene presa per la 3018", i4.model != N, i4.model)
others = {n: (machines.preset_profile(n).bed_x, machines.preset_profile(n).bed_y, machines.preset_profile(n).max_rate_x)
          for n in ("Genmitsu Jinsoku LC-40", "Genmitsu L8 20W", "Genmitsu L8 40W", "Genmitsu LE5040")}
check("gli altri Genmitsu restano com'erano", others == {
    "Genmitsu Jinsoku LC-40": (395.0, 365.0, 10200.0), "Genmitsu L8 20W": (400.0, 400.0, 40000.0),
    "Genmitsu L8 40W": (390.0, 390.0, 40000.0), "Genmitsu LE5040": (500.0, 400.0, 10000.0)}, others)

# ------------------------------------------------------------------ traduzioni
for lang in ("en", "es", "fr", "pt"):
    loc = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    t = loc.get(note, "")
    check(f"nota tradotta in {lang}, con $32=1, il nome SainSmart e il pulsante di quella lingua",
          "$32=1" in t and "CNC 3018" in t and "SainSmart" in t and loc["Leggi dalla macchina"] in t, t[:120])

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(code_)
