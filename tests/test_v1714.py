# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.14 (da un utente con un Acmer P3): modelli Acmer P3 nel catalogo e profili dei produttori.

- Catalogo: Acmer P3 24W, 48W, 2W IR e 2-in-1, con i dati dei profili ufficiali Acmer (area, scansione) e della
  pagina del prodotto (velocità, spot).
- Laser → Importa un profilo macchina legge anche il file .lbdev che i produttori mettono sulla microSD.
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
ASKED = []
QMessageBox.question = staticmethod(lambda *a, **k: (ASKED.append(a[2] if len(a) > 2 else ""), QMessageBox.Yes)[1])
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: (WARN.append(a[2] if len(a) > 2 else ""), QMessageBox.Ok)[1])

import freelasercut
from freelasercut import machines, profile_share
from freelasercut.updater import parse_version

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


check("versione 0.17.14 o successiva", parse_version(freelasercut.__version__) >= (0, 17, 14), freelasercut.__version__)

# ---------------------------------------------------------------- catalogo
names = machines.catalog_names()
check("Acmer P3 nel catalogo: 24W, 48W, 2W IR, 2-in-1", all(n in names for n in (
    "Acmer P3 24W", "Acmer P3 48W", "Acmer P3 2W IR", "Acmer P3 2-in-1 (diodo + IR)")))
p24, p48 = machines.preset_profile("Acmer P3 24W"), machines.preset_profile("Acmer P3 48W")
check("aree dei profili ufficiali: 24W 400 × 400, 48W 400 × 390", (p24.bed_x, p24.bed_y, p48.bed_x, p48.bed_y)
      == (400, 400, 400, 390))
check("velocità 800 mm/s e spot della pagina ufficiale", p24.max_rate_x == 48000 and (p24.spot_x_mm, p24.spot_y_mm)
      == (0.06, 0.08) and (p48.spot_x_mm, p48.spot_y_mm) == (0.08, 0.10))
check("correzione della scansione già impostata (valori Acmer, sfasamento intero)", p24.scan_offsets[0] == [6000.0, 0.14]
      and abs(p24.scan_offset(30000) - 0.16) < 1e-9)
check("fonti dichiarate per ogni modello", all(n in machines.SOURCES for n in machines.SCAN))
i = machines.identify(banner=["Grbl 1.1h"], info=["[MSG:FW:ACMER]"], settings={130: "400", 131: "390"})
check("riconoscimento: scheda Acmer con 400 × 390 → P3 48W o 2-in-1 da scegliere", i.vendor == "Acmer" and set(i.candidates)
      == {"Acmer P3 48W", "Acmer P3 2-in-1 (diodo + IR)"}, (i.vendor, i.model, i.candidates))

# ---------------------------------------------------------------- file del produttore (.lbdev)
dev = {"DeviceList": [{"DisplayName": "Laser di prova 24W", "Name": "GRBL", "ProfilePath": "GRBL", "Type": "Serial",
                       "Width": 400, "Height": 390, "MirrorX": False, "MirrorY": False,
                       "ReverseIntervalCompensation": True,
                       "ReverseIntervals": [{"LineShift": 0.07, "Speed": 100, "StartAdjust": 0},
                                            {"LineShift": 0.08, "Speed": 200, "StartAdjust": 0}],
                       "Settings": {"AlignH": 0, "AlignV": 2, "BaudRate": 115200, "S_Scale": 1000,
                                    "Sim_MaxSpeedX": 500, "Sim_MaxSpeedY": 400, "Sim_MaxAccelX": 3000,
                                    "Sim_MaxAccelY": 3000, "EnableZ": False, "AirAssistM7": False,
                                    "StartGCode": "M3 S1000", "camera": [1, 2, 3]}}]}
d = tempfile.mkdtemp()
path = os.path.join(d, "Laser di prova 24W.lbdev")
json.dump(dev, open(path, "w", encoding="utf-8"), indent=4)
p = profile_share.read_any(path)
check("file del produttore: nome, area, porta, potenza", (p.name, p.bed_x, p.bed_y, p.baud, p.s_max)
      == ("Laser di prova 24W", 400, 390, 115200, 1000), (p.name, p.bed_x, p.bed_y, p.baud, p.s_max))
check("…origine davanti a sinistra", p.origin_corner == "fl", p.origin_corner)
check("…correzione della scansione: mm/s → mm/min, metà → sfasamento intero",
      p.scan_offsets == [[6000.0, 0.14], [12000.0, 0.16]], p.scan_offsets)
check("…stime di velocità e accelerazioni", (p.max_rate_x, p.max_rate_y, p.accel_x) == (30000, 24000, 3000))
check("…segnato «dal file del produttore»", p.source == profile_share.MAKER)
check("…i comandi G-code del file non entrano nel profilo (sicurezza)", "M3" not in json.dumps(p.__dict__))
bad = json.loads(json.dumps(dev))
bad["DeviceList"][0]["Name"] = "Ruida"
bad["DeviceList"][0]["ProfilePath"] = "Ruida"
json.dump(bad, open(path, "w", encoding="utf-8"))
try:
    profile_share.read_any(path)
    msg = ""
except ValueError as ex:
    msg = str(ex)
check("macchina non GRBL: rifiutata con il motivo", "GRBL" in msg, msg)
bad = json.loads(json.dumps(dev))
bad["DeviceList"][0]["Width"] = 99999
json.dump(bad, open(path, "w", encoding="utf-8"))
try:
    profile_share.read_any(path)
    msg = ""
except ValueError as ex:
    msg = str(ex)
check("area assurda: rifiutata", msg != "", msg)
open(path, "w").write("non è json")
try:
    profile_share.read_any(path)
    msg = ""
except ValueError as ex:
    msg = str(ex)
check("file rovinato: messaggio chiaro", "non si legge" in msg, msg)

# nella finestra: Laser → Importa un profilo macchina con il file del produttore
json.dump(dev, open(path, "w", encoding="utf-8"))
from freelasercut.ui.main_window import MainWindow

w = MainWindow()
got = w.import_profile(path=path)
check("Importa un profilo macchina: il file del produttore diventa il profilo attivo", got is not None
      and w.profile.name == "Laser di prova 24W" and w.profile.bed_y == 390 and not WARN, WARN)
check("…con la spiegazione giusta (dal produttore, prova delle frecce)", ASKED and "produttore" in ASKED[-1]
      and "frecce" in ASKED[-1], ASKED[-1:])

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
