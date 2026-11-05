# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.13.4: profili macchina da condividere (.flcprofile), link al canale YouTube, nuovi modelli pronti."""
import sys, os, json, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
from freelasercut import profile_share, machines
from freelasercut.profile import MachineProfile

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)

D = tempfile.mkdtemp()
# ------------------------------------------------------------------ esporta / importa
p = MachineProfile(name="La mia DLC32", model="Scheda Makerbase MKS DLC32", bed_x=410, bed_y=400, invert_y=True,
                   tested_y=True, negative_space=True, origin_corner="bl", s_max=1000, air_on="M8",
                   raw_settings={"130": "410.000", "131": "400.000"}, scan_offsets=[[6000, 0.12]])
f = profile_share.export_profile(p, os.path.join(D, "dlc32" + profile_share.EXT))
doc = json.load(open(f, encoding="utf-8"))
check("esporta: file .flcprofile con formato e versione", doc["freelasercut_profile"] == 1 and "FreeLaserCut" in doc["exported_by"])
check("esporta: le prove fatte sulla propria macchina non vanno nel file",
      not any(k in doc["profile"] for k in ("tested_x", "tested_y", "negative_space", "origin_corner")))
q = profile_share.read_profile(f)
check("importa: area, assi, potenza, correzione della scansione come nel file",
      (q.bed_x, q.bed_y, q.invert_y, q.s_max, q.scan_offsets) == (410, 400, True, 1000, [[6000.0, 0.12]]))
check("importa: segnato «dalla comunità», assi da provare, coordinate da riscoprire",
      q.source == profile_share.COMMUNITY and not q.tested_y and q.negative_space is None and q.origin_corner == "")
def bad(change, label):
    d = json.loads(json.dumps(doc)); change(d["profile"])
    fp = os.path.join(D, label + profile_share.EXT); json.dump(d, open(fp, "w"))
    try:
        profile_share.read_profile(fp)
        return None
    except ValueError as ex:
        return str(ex)
r1 = bad(lambda pr: pr.update(air_on="M3 S1000"), "laser")
check("rifiutato: un profilo che come «aria» accenderebbe il laser (M3 S1000)", r1 and "aria" in r1, r1)
r2 = bad(lambda pr: pr.update(bed_x=99999), "area")
check("rifiutato: area di lavoro assurda (99999 mm)", r2 and "fuori dai limiti" in r2, r2)
r3 = bad(lambda pr: pr.update(max_rate_x="tanta"), "testo")
check("rifiutato: velocità che non è un numero", r3 is not None, r3)
r4 = bad(lambda pr: pr.update(s_min=2000, s_max=1000), "potenza")
check("rifiutato: potenza minima più alta della massima", r4 is not None, r4)
r5 = bad(lambda pr: pr.pop("bed_x"), "senza area")
check("rifiutato: profilo senza area di lavoro", r5 is not None, r5)
json.dump({"ciao": 1}, open(os.path.join(D, "altro.flcprofile"), "w"))
try:
    profile_share.read_profile(os.path.join(D, "altro.flcprofile")); r6 = None
except ValueError as ex:
    r6 = str(ex)
check("rifiutato: un file che non è un profilo", r6 and "non è un profilo" in r6, r6)
d = json.loads(json.dumps(doc)); d["profile"]["raw_settings"] = {"130": "410", "x": "1", "32": "M3 S1000", "100": "80"}
d["profile"]["name"] = "Nome\nlungo" + "x" * 300
fp = os.path.join(D, "pulito.flcprofile"); json.dump(d, open(fp, "w"))
q = profile_share.read_profile(fp)
check("valori di consultazione ripuliti (solo $n = numero), nome su una riga e non troppo lungo",
      q.raw_settings == {"130": "410", "100": "80"} and "\n" not in q.name and len(q.name) <= 120)

# ------------------------------------------------------------------ 8 modelli nuovi, controllati due volte
NEW = {"Mecpow X3 5W": (400, 400, 10000), "Mecpow X3 Pro 10W": (400, 400, 10000),
       "Mecpow X4 22W / X4 Pro 22W": (400, 400, 22000), "Mecpow X4 Pro 40W": (398, 398, 30000),
       "Mecpow X5 Pro 33W": (600, 600, 28000), "Longer Ray5 Mini": (130, 130, 12000),
       "Creality CR-Laser Falcon 5W": (400, 400, 10000), "Atomstack A70 Max": (800, 800, 24000)}
cat = {c[0]: c for c in machines.CATALOG}
check("catalogo: 48 modelli, gli 8 nuovi presenti e sceglibili", len(machines.CATALOG) == 48 and
      all(n in machines.catalog_names() for n in NEW), len(machines.CATALOG))
wrong = [n for n, (x, y, v) in NEW.items() if (cat[n][2], cat[n][3], cat[n][5]) != (x, y, v)]
check("area e velocità come verificate sulle pagine ufficiali (area ridotta al lato più corto dove serve)", not wrong, wrong)
unsafe = [n for n, (ax, ay) in machines.AREA_NOTE.items() if cat[n][2] > min(ax, ay) or cat[n][3] > min(ax, ay)]
check("area prudente: mai più grande del lato più corto dichiarato", not unsafe, unsafe)
OFFICIAL = ("mecpow.com", "longer.net", "crealityfalcon.com", "atomstack.com")
src = [n for n in NEW if not machines.SOURCES.get(n, "").startswith("https://") or
       not any(d in machines.SOURCES[n] for d in OFFICIAL)]
check("ogni modello nuovo ha la sua pagina ufficiale del produttore", not src, src)
notes = [n for n in machines.AREA_NOTE if "per prudenza" not in machines.NOTES.get(n, "")]
check("dove l'area è ridotta, la nota lo spiega (si vede scegliendo il modello)", not notes, notes)
pp = machines.preset_profile("Mecpow X4 Pro 40W")
check("profilo pronto: area, velocità, spot del produttore", (pp.bed_x, pp.bed_y, pp.max_rate_x, pp.spot_x_mm, pp.spot_y_mm)
      == (398.0, 398.0, 30000.0, 0.10, 0.15))
ident = machines.identify(["Grbl 1.1h ['$' for help]", "[MSG:MECPOW X5]"], [], {130: "600", 131: "600"})
check("scheda Mecpow con 600 × 600: riconosciuta come Mecpow X5 Pro 33W", ident.vendor == "Mecpow" and
      ident.model == "Mecpow X5 Pro 33W", (ident.vendor, ident.model, ident.candidates))

# ------------------------------------------------------------------ dal programma
from freelasercut.ui.main_window import MainWindow
w = MainWindow()
laser_menu = [m.menu() for m in w.menuBar().actions() if m.menu() and w.acts["identify"] in m.menu().actions()][0]
help_menu = [m.menu() for m in w.menuBar().actions() if m.menu() and w.acts["help_mode"] in m.menu().actions()][0]
check("menu Laser: Esporta e Importa il profilo; menu Aiuto: Video tutorial su YouTube",
      w.acts["profile_export"] in laser_menu.actions() and w.acts["profile_import"] in laser_menu.actions()
      and w.acts["youtube"] in help_menu.actions())
check("link al canale YouTube", w.YOUTUBE == "https://www.youtube.com/@FreeLaserCut")
out = w.export_profile(path=os.path.join(D, "attivo"))
check("Esporta dal programma: aggiunge l'estensione e salva il profilo attivo", out and out.endswith(".flcprofile")
      and profile_share.read_profile(out).bed_x == w.profile.bed_x)
imp = w.import_profile(path=f)
check("Importa dal programma: profilo salvato e attivo (con «Sì»)", imp is not None and w.profile.name == "La mia DLC32"
      and os.path.exists(imp.path()))
imp2 = w.import_profile(path=f)
check("importando di nuovo lo stesso profilo non sovrascrive: nome con (2)", imp2 is not None and imp2.name == "La mia DLC32 (2)")
WARN.clear()
check("Importa un file sbagliato: messaggio, nessun profilo cambiato",
      w.import_profile(path=os.path.join(D, "altro.flcprofile")) is None and WARN and w.profile.name == "La mia DLC32 (2)")
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
