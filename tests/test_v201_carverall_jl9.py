# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.20.1: Carverall JL9 (venduto anche come «X1 Pro») 20W nel catalogo.

Dati dalle fonti ufficiali Carverall (lette il 15/11/2026):
- pagina prodotto carverall.com/products/x1pro-laser-engraver: diodo 20 W a 455 nm, area 300 × 300 mm,
  15.000 mm/min, scheda GRBL a 32 bit, USB e Wi-Fi, spot non dichiarato;
- manuale «X1Pro_JL9 User Manual_EN» (cartella «User Manual» della pagina delle guide Carverall): chip USB CH340,
  area 300 × 300 e origine davanti a sinistra nella configurazione GRBL, homing automatico.

Casi: la voce nuova (area, potenza, velocità, spot e accelerazione generici, porta a 115200, aria M8, fonte, nota);
tutte le voci di prima identiche (lette dal file della versione precedente); nota tradotta nelle quattro lingue e con
i nomi dei comandi come nel programma; riconoscimento: scheda senza produttore 300 × 300 → JL9 fra i candidati, senza
sceglierlo da solo (c'è anche lo Swift); scheda Atomstack 300 × 300 → solo gli Swift; scheda senza produttore 300 × 300
con l'area scritta un po' diversa (301 × 299) → stessi candidati.
"""
import ast
import json
import os
import subprocess
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


JL9 = "Carverall JL9 (X1 Pro) 20W"
SWIFT = ("Atomstack Swift 7W", "Atomstack Swift 12W")
names = machines.catalog_names()

# ------------------------------------------------------------------ la voce nuova
check("Carverall JL9 nel catalogo, sceglibile, senza doppioni", JL9 in names and len(names) == len(set(names))
      and len(names) == len(machines.CATALOG) + 1 and names[-1] == machines.GENERIC, len(machines.CATALOG))
check("nell'elenco sta in ordine alfabetico (dopo Atomstack, prima di Comgrow)",
      names.index("Atomstack X40 Pro / S40 Pro / A40 Pro") < names.index(JL9) < names.index("Comgrow Z1"),
      names[names.index(JL9) - 1:names.index(JL9) + 2])
row = next(c for c in machines.CATALOG if c[0] == JL9)
check("voce del catalogo: produttore Carverall, 300 × 300 mm, «20 W», 15.000 mm/min (pagina ufficiale)",
      row == (JL9, "Carverall", 300, 300, "20 W", 15000), row)
p = machines.preset_profile(JL9)
check("profilo pronto: area 300 × 300 e velocità massima 15.000 mm/min su X e Y",
      (p.bed_x, p.bed_y, p.max_rate_x, p.max_rate_y) == (300.0, 300.0, 15000.0, 15000.0),
      (p.bed_x, p.bed_y, p.max_rate_x, p.max_rate_y))
check("potenza «20 W» letta come 20 W (stima dei materiali)", p.optical_power == "20 W"
      and optical_watts(p.optical_power) == 20.0, p.optical_power)
check("spot non dichiarato da Carverall: valore comune 0,08 × 0,10 mm (niente voce in SPOTS)",
      (p.spot_x_mm, p.spot_y_mm) == (0.08, 0.10) and JL9 not in machines.SPOTS, (p.spot_x_mm, p.spot_y_mm))
check("porta seriale 115200, aria M8, accelerazione generica 1500, niente correzione della scansione né G55 tolto",
      p.baud == 115200 and p.air_on == "M8" and (p.accel_x, p.accel_y) == (1500.0, 1500.0) and not p.scan_offsets
      and not p.no_g55 and JL9 not in machines.BAUD and JL9 not in machines.AIR_ON,
      (p.baud, p.air_on, p.accel_x, p.scan_offsets, p.no_g55))
check("nome, modello e valori «di targa»", p.name == JL9 and p.model == JL9 and bool(p.source))
check("area non ridotta per prudenza (è quadrata)", JL9 not in machines.AREA_NOTE)
check("fonte: pagina ufficiale Carverall del prodotto",
      machines.SOURCES.get(JL9) == "https://www.carverall.com/products/x1pro-laser-engraver", machines.SOURCES.get(JL9))
n = machines.NOTES.get(JL9, "")
check("nota: X1 Pro, CH340, area e origine dal manuale, CutLabX da chiudere, 15.000/20.000, «Leggi dalla macchina», "
      "Wi-Fi non provato, configurazione guidata",
      all(k in n for k in ("X1 Pro", "CH340", "300 × 300", "davanti a sinistra", "CutLabX", "15.000", "20.000",
                            "«Leggi dalla macchina»", "Wi-Fi", "non è provato", "configurazione guidata")), n)

# ------------------------------------------------------------------ le altre voci non cambiano
old_src = subprocess.run(["git", "-C", ROOT, "show", "v0.20.0:freelasercut/machines.py"], capture_output=True,
                         text=True).stdout
old = None
if old_src:
    for node in ast.parse(old_src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "CATALOG" for t in node.targets):
            old = ast.literal_eval(node.value)
if old is None:  # copia senza la storia di git: confronto con i valori noti di alcune voci
    check("(senza git) le voci vicine restano com'erano",
          next(c for c in machines.CATALOG if c[0] == SWIFT[0]) == (SWIFT[0], "Atomstack", 300, 300, "7 W", 10000))
else:
    check("tutte le voci di prima identiche e nello stesso ordine, più la JL9 in fondo",
          tuple(machines.CATALOG[:-1]) == tuple(old) and machines.CATALOG[-1][0] == JL9,
          (len(old), len(machines.CATALOG)))

# ------------------------------------------------------------------ traduzioni
for lang, word in (("en", "Read from machine"), ("es", "Leer de la máquina"), ("fr", "Lire depuis la machine"),
                   ("pt", "Ler da máquina")):
    d = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    t = d.get(n, "")
    check(f"nota tradotta in «{lang}», con il comando come nel programma ({word}) e i numeri giusti",
          bool(t) and t != n and word in t and "CH340" in t and "CutLabX" in t and "300 × 300" in t
          and ("15,000" in t or "15.000" in t or "15 000" in t), t[:80])

# ------------------------------------------------------------------ riconoscimento dalla scheda
def ident(vendor_info, bx, by):
    return machines.identify(banner=["Grbl 1.1h ['$' for help]"], info=vendor_info,
                             settings={"130": str(bx), "131": str(by), "30": "1000", "32": "1"})


i = ident(["[VER:1.1h.20250101:]", "[OPT:VL,35,254]"], 300, 300)
check("scheda senza produttore, 300 × 300: la JL9 è fra i candidati e non viene scelta da sola (c'è anche lo Swift)",
      i.model == "" and JL9 in i.candidates and set(SWIFT) <= set(i.candidates), (i.model, i.candidates))
i = ident(["[VER:1.1h.20250101:]", "[OPT:VL,35,254]"], 301, 299)
check("…anche con l'area scritta un po' diversa (301 × 299)", i.model == "" and JL9 in i.candidates, (i.model, i.candidates))
i = ident(["[VER:1.1h.20250101:ATOMSTACK]", "[OPT:VL,35,254]"], 300, 300)
check("scheda Atomstack 300 × 300: solo gli Swift, non la JL9", JL9 not in (i.candidates or [i.model])
      and (i.model in SWIFT or set(i.candidates) == set(SWIFT)), (i.model, i.candidates))
i = ident(["[VER:1.1h.20250101:]"], 410, 400)
check("scheda senza produttore con un'altra area: la JL9 non c'entra", JL9 not in i.candidates and i.model != JL9,
      (i.model, i.candidates))
b = machines.base_profile(machines.identify(settings={"130": "300", "131": "300"}))
check("profilo dal riconoscimento senza modello scelto: niente valori della JL9 attaccati per sbaglio",
      b.model != JL9, b.model)

print(f"\n{sum(results)}/{len(results)} controlli superati")
sys.exit(0 if all(results) else 1)
