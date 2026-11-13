# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.19.2: Acmer P2 (10, 20 e 33 W) nel catalogo, chiesto da un utente con un rapporto all'assistenza.

Dati dalle fonti ufficiali Acmer (lette il 13/11/2026):
- profilo «ACMER P2.lbdev» della cartella «TF Card Data» del P2 (linkata da acmerlaser.com/pages/download): area
  420 (X) × 400 (Y) mm, 115200 baud, scala S 1000, accelerazione 3000 mm/s², aria assistita comandata con M7, niente
  correzione della scansione;
- pagina del prodotto: versioni da 10, 20 e 33 W, fino a 30.000 mm/min, spot 0,06 × 0,08 mm (10 W) e 0,08 × 0,10 mm
  (20 e 33 W), 420 × 800 mm con il kit di estensione.

Casi: le tre voci (area, velocità, accelerazione, potenza, spot, porta, aria, fonte, nota); niente che non è
dichiarato (area ridotta, scansione, G55); le altre voci com'erano (aria M8); riconoscimento di una scheda Acmer con
420 × 400, con le aree delle P3, senza marca, con il kit di estensione, con X e Y scambiati; profilo costruito dalla
scheda; file .lbdev con gli stessi valori; conteggio del catalogo; traduzioni della nota.
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

from freelasercut import machines, profile_share
from freelasercut.grbl import optical_watts

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


P2 = ("Acmer P2 10W", "Acmer P2 20W", "Acmer P2 33W")
P3 = ("Acmer P3 24W", "Acmer P3 48W", "Acmer P3 2W IR", "Acmer P3 2-in-1 (diodo + IR)")
names = machines.catalog_names()
check("1 le tre Acmer P2 sono nel catalogo, sceglibili, senza doppioni: 64 modelli più il generico",
      all(n in names for n in P2) and len(machines.CATALOG) >= 64 and len(names) == len(machines.CATALOG) + 1 == len(set(names)),
      len(machines.CATALOG))
check("1 …nell'elenco stanno insieme, prima delle P3, e si trovano cercando «P2»",
      [names.index(n) for n in P2] == list(range(names.index(P2[0]), names.index(P2[0]) + 3))
      and names.index(P2[2]) + 1 == names.index("Acmer P3 2-in-1 (diodo + IR)") and [n for n in names if "P2" in n] == list(P2),
      [n for n in names if "Acmer" in n])
pr = {n: machines.preset_profile(n) for n in P2}
check("2 area 420 × 400 mm con X sul lato lungo (profilo ufficiale: Width 420, Height 400)",
      all((p.bed_x, p.bed_y) == (420.0, 400.0) for p in pr.values()), [(p.bed_x, p.bed_y) for p in pr.values()])
check("2 velocità massima 30.000 mm/min (pagina ufficiale) e accelerazione 3000 mm/s² (profilo ufficiale)",
      all((p.max_rate_x, p.max_rate_y, p.accel_x, p.accel_y) == (30000.0, 30000.0, 3000.0, 3000.0) for p in pr.values()),
      [(p.max_rate_x, p.accel_x) for p in pr.values()])
check("3 potenza per versione: 10, 20 e 33 W",
      [(pr[n].optical_power, optical_watts(pr[n].optical_power)) for n in P2] == [("10 W", 10.0), ("20 W", 20.0), ("33 W", 33.0)],
      [pr[n].optical_power for n in P2])
check("3 spot dichiarato: 0,06 × 0,08 mm il 10 W; 0,08 × 0,10 mm il 20 W e il 33 W",
      [(pr[n].spot_x_mm, pr[n].spot_y_mm) for n in P2] == [(0.06, 0.08), (0.08, 0.10), (0.08, 0.10)]
      and all(n in machines.SPOTS for n in P2), [(pr[n].spot_x_mm, pr[n].spot_y_mm) for n in P2])
check("4 porta a 115200 baud e scala di potenza S 1000, come nel profilo ufficiale",
      all(p.baud == 115200 and p.s_max == 1000.0 for p in pr.values()) and not any(n in machines.BAUD for n in P2))
check("4 aria assistita accesa con M7 e spenta con M9 (profilo ufficiale: AirAssistM7)",
      all((p.air_on, p.air_off) == ("M7", "M9") for p in pr.values()) and all(machines.AIR_ON.get(n) == "M7" for n in P2),
      [(p.air_on, p.air_off) for p in pr.values()])
others = [n for n in names[:-1] if n not in P2]
check("4 …le altre voci del catalogo restano con M8 (P3, S1, Longer B1 e tutte le altre)",
      all(machines.preset_profile(n).air_on == "M8" for n in others) and set(machines.AIR_ON) == set(P2)
      and machines.preset_profile(names[-1]).air_on == "M8",
      [n for n in others if machines.preset_profile(n).air_on != "M8"])
check("5 niente che Acmer non dichiara: area non ridotta, nessuna correzione della scansione, G55 non tolto",
      not any(n in machines.AREA_NOTE or n in machines.SCAN or n in machines.NO_G55 for n in P2)
      and all(not p.scan_offsets and not p.no_g55 for p in pr.values()))
check("6 fonte ufficiale Acmer dichiarata; nome, modello e valori «di targa»",
      all(machines.SOURCES.get(n, "").startswith("https://acmerlaser.com/products/") and "p2" in machines.SOURCES[n] for n in P2)
      and all(pr[n].name == n and pr[n].model == n and bool(pr[n].source) for n in P2))
note = machines.NOTES.get(P2[0], "")
check("6 la nota dice: aria con M7, kit di estensione 420 × 800 e «Leggi dalla macchina»; è la stessa per le tre",
      "M7" in note and "420 × 800" in note and "Leggi dalla macchina" in note and "profilo ufficiale" in note
      and all(machines.NOTES.get(n) == note for n in P2), note)
check("6 …la nota delle P3 è rimasta la sua", all("CoreXY" in machines.NOTES[n] and "M7" not in machines.NOTES[n] for n in P3))

# ------------------------------------------------------------------ riconoscimento
acmer = dict(banner=["Grbl 1.1h ['$' for help]"], info=["[VER:1.1h.20230317:]", "[MSG:FW:ACMER]"])
i = machines.identify(settings={130: "420.000", 131: "400.000", 30: "1000", 32: "1", 22: "1"}, **acmer)
texts = " | ".join(t for _k, t in i.notes)
check("7 scheda Acmer con l'area 420 × 400: proposte le tre P2 da scegliere (la potenza non si legge dalla scheda)",
      i.vendor == "Acmer" and not i.model and list(i.candidates) == list(P2) and all(n in texts for n in P2),
      (i.vendor, i.model, i.candidates, texts))
i = machines.identify(settings={130: "400", 131: "390"}, **acmer)
check("8 scheda Acmer con 400 × 390: ancora P3 48W o 2-in-1, come prima",
      set(i.candidates) == {"Acmer P3 48W", "Acmer P3 2-in-1 (diodo + IR)"} and not i.model, (i.model, i.candidates))
i = machines.identify(settings={130: "400", 131: "400"}, **acmer)
check("8 scheda Acmer con 400 × 400: ancora P3 24W o 2W IR, nessuna P2",
      set(i.candidates) == {"Acmer P3 24W", "Acmer P3 2W IR"} and not i.model, (i.model, i.candidates))
i = machines.identify(settings={130: "130", 131: "130"}, **acmer)
check("8 scheda Acmer con 130 × 130: ancora l'S1", i.model == "Acmer S1 (2,5W / 3,5W / 6W)", (i.model, i.candidates))
i = machines.identify(banner=["Grbl 1.1h"], info=["[VER:1.1h.2024:]"], settings={130: "420", 131: "400"})
check("9 scheda senza marca con 420 × 400: le tre P2 fra i candidati, nessun modello scelto da solo",
      not i.vendor and not i.model and set(P2) <= set(i.candidates), (i.vendor, i.model, i.candidates))
i = machines.identify(settings={130: "400", 131: "420"}, **acmer)
check("9 scheda Acmer con X e Y scambiati (400 × 420): riconosciuta lo stesso come P2",
      list(i.candidates) == list(P2), (i.model, i.candidates))
ext = {130: "420.000", 131: "800.000", 30: "1000", 32: "1", 22: "1", 110: "30000.000", 111: "24000.000"}
i = machines.identify(settings=ext, **acmer)
q = machines.build_profile(i, ext, acmer["info"])
check("10 P2 con il kit di estensione (420 × 800): non viene presa per una P2 standard, e il profilo tiene l'area letta",
      i.vendor == "Acmer" and not i.model and not i.candidates and (q.bed_x, q.bed_y) == (420.0, 800.0),
      (i.model, i.candidates, q.bed_x, q.bed_y))
board = {130: "420.000", 131: "400.000", 30: "1000", 32: "1", 22: "1", 110: "30000.000", 111: "24000.000",
         120: "2500.000", 121: "2500.000"}
i = machines.identify(settings=board, **acmer)
i.model = P2[1]  # la persona sceglie «20W» fra i candidati
q = machines.build_profile(i, board, acmer["info"])
check("11 scelto il modello, il profilo costruito dalla scheda tiene i valori letti (area, velocità X e Y, accelerazione)",
      (q.bed_x, q.bed_y, q.max_rate_x, q.max_rate_y, q.accel_x) == (420.0, 400.0, 30000.0, 24000.0, 2500.0),
      (q.bed_x, q.bed_y, q.max_rate_x, q.max_rate_y, q.accel_x))
check("11 …e dal modello prende potenza, spot e aria con M7",
      (q.optical_power, q.spot_x_mm, q.spot_y_mm, q.air_on, q.air_off) == ("20 W", 0.08, 0.10, "M7", "M9"),
      (q.optical_power, q.spot_x_mm, q.spot_y_mm, q.air_on, q.air_off))

# ------------------------------------------------------------------ file del produttore (.lbdev) con gli stessi valori
dev = {"DeviceList": [{"DisplayName": "ACMER P2 ", "Name": "GRBL", "Type": "Serial", "Width": 420, "Height": 400,
                       "HomeOnStartup": False, "MirrorX": False, "MirrorY": False, "ReverseIntervalCompensation": False,
                       "Settings": {"AirAssistM7": True, "BaudRate": 115200, "S_Scale": 1000, "EnableZ": False,
                                    "Sim_MaxAccelX": 3000, "Sim_MaxAccelY": 3000, "Sim_MaxSpeedX": 500,
                                    "Sim_MaxSpeedY": 400, "StartGCode": "", "EndGCode": ""}}]}
path = os.path.join(tempfile.mkdtemp(), "ACMER P2.lbdev")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(dev, fh, indent=4)
f = profile_share.read_any(path)
check("12 un file .lbdev con i valori del profilo ufficiale si importa: 420 × 400, 115200, S 1000, aria M7, niente scansione",
      (f.name, f.bed_x, f.bed_y, f.baud, f.s_max, f.air_on, f.accel_x) == ("ACMER P2", 420, 400, 115200, 1000, "M7", 3000)
      and not f.scan_offsets, (f.name, f.bed_x, f.bed_y, f.baud, f.s_max, f.air_on, f.scan_offsets))
check("12 …e dà gli stessi valori della voce del catalogo (area, porta, scala, aria, accelerazione)",
      all((f.bed_x, f.bed_y, f.baud, f.s_max, f.air_on, f.accel_x) == (p.bed_x, p.bed_y, p.baud, p.s_max, p.air_on, p.accel_x)
          for p in pr.values()))

# ------------------------------------------------------------------ traduzioni
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    t = loc.get(note, "")
    check(f"traduzione {lang} della nota: c'è, con M7 e le due aree", bool(t) and t != note and "M7" in t
          and "420 × 400" in t and "420 × 800" in t, t[:80])

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(code_)
