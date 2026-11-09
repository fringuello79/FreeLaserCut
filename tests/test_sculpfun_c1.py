# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.18 (da un utente, rapporto FLC-20261109-1514-7E5C): Sculpfun C1 3W e 6W nel catalogo.

Dati dalle pagine ufficiali Sculpfun: area 150 × 130 mm senza dire quale lato è X (qui 130 × 130 per prudenza,
area dichiarata in AREA_NOTE), spot 0,04 mm (3W) e 0,06 mm (6W).
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

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


C3, C6 = "Sculpfun C1 3W", "Sculpfun C1 6W"
names = machines.catalog_names()
check("Sculpfun C1 3W e 6W nel catalogo, sceglibili", C3 in names and C6 in names)
check("nomi del catalogo senza doppioni", len(names) == len(set(names)))
p3, p6 = machines.preset_profile(C3), machines.preset_profile(C6)
check("area 130 × 130 per prudenza (X non dichiarato)", (p3.bed_x, p3.bed_y, p6.bed_x, p6.bed_y) == (130, 130, 130, 130),
      (p3.bed_x, p3.bed_y))
check("area dichiarata 150 × 130 in AREA_NOTE e spiegata nelle note", machines.AREA_NOTE.get(C3) == (150, 130)
      and "150" in machines.NOTES.get(C3, "") and "130" in machines.NOTES.get(C6, ""))
check("spot ufficiali: 3W 0,04 mm, 6W 0,06 mm", (p3.spot_x_mm, p3.spot_y_mm, p6.spot_x_mm, p6.spot_y_mm)
      == (0.04, 0.04, 0.06, 0.06))
check("potenza e velocità", p3.optical_power == "3 W" and p6.optical_power == "6 W" and p3.max_rate_x == 10000)
check("fonti ufficiali dichiarate", all(machines.SOURCES.get(n, "").startswith("https://") and "sculpfun.com"
                                        in machines.SOURCES[n] for n in (C3, C6)))
check("niente correzione della scansione né G55 tolto", not p3.scan_offsets and not p3.no_g55)

# riconoscimento dalla scheda: Sculpfun con l'area vera 150 × 130 (o 130 × 150) → i due C1 da scegliere
for bx, by in ((150, 130), (130, 150)):
    i = machines.identify(banner=["Grbl 1.1f ['$' for help]"], info=["[MSG:SCULPFUN]"], settings={130: str(bx), 131: str(by)})
    check(f"riconoscimento: scheda Sculpfun {bx} × {by} → C1 3W o 6W", i.vendor == "Sculpfun" and set(i.candidates)
          == {C3, C6}, (i.vendor, i.model, i.candidates))
# l'iCube Ultra (150 × 150) resta riconosciuto da solo
i = machines.identify(banner=["Grbl 1.1f"], info=["[MSG:SCULPFUN]"], settings={130: "150", 131: "150"})
check("riconoscimento: Sculpfun 150 × 150 resta l'iCube Ultra", i.model == "Sculpfun iCube Ultra 12W",
      (i.vendor, i.model, i.candidates))

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(code_)
