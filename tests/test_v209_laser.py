# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.9 (Ale, 19/11/2026): più laser configurati insieme, ognuno con un nome scelto da chi li usa, e una tendina
per passare dall'uno all'altro.

Casi: nomi (vuoto, spazi, troppo lungo, solo simboli, già usato, uguale a meno di maiuscole e simboli, il proprio);
Rinomina che sposta il file (anche cambiando solo le maiuscole, senza perdere il file), con la porta ricordata che
segue il laser; laser nuovo copiato da quello in uso o da un modello; elenco con i file rovinati scartati e i nomi
doppi distinti; tolto dall'elenco; tendina nel pannello Laser (Classica e Officina del Banco) che passa al laser
scelto (piano, profilo attivo ricordato, porta di quel laser), ferma con un laser collegato, con l'ultimo laser
che non si toglie; laser in uso non ancora salvato (prima installazione).
Uso: python tests/test_v209_laser.py [classica|banco]
"""
import json
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import grbl, lasers  # noqa: E402
from freelasercut.profile import MachineProfile, config_dir  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "", flush=True)


def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.005)


PROF = os.path.join(config_dir(), "profiles")
FAKE = {"conn": False}
grbl.GrblController.connected = property(lambda self: FAKE["conn"])

print("--- nomi")
check("vuoto rifiutato", lasers.name_problem("") is not None)
check("solo spazi rifiutato", lasers.name_problem("   ") is not None)
check("solo simboli rifiutato (il file sarebbe «profilo»)", lasers.name_problem("***") is not None)
check("più di 60 caratteri rifiutato", lasers.name_problem("x" * 61) is not None and lasers.name_problem("x" * 60) is None)
check("spazi doppi e ai lati tolti", lasers.clean_name("  B1   garage ") == "B1 garage")
MachineProfile(name="B1 garage").save()
check("nome già usato rifiutato", lasers.name_problem("B1 garage") is not None)
check("…anche con maiuscole e simboli diversi (stesso file su Windows)", lasers.name_problem("b1_GARAGE") is not None)
own = lasers.path_for("B1 garage")
check("…ma non per il laser stesso (cambiare solo le maiuscole)", lasers.name_problem("B1 GARAGE", own_path=own) is None)
check("nome libero accettato", lasers.name_problem("Falcon ufficio") is None)
check("nome libero proposto: «B1 garage 2»", lasers.unique_name("B1 garage") == "B1 garage 2")
check("nome libero proposto: lo stesso se è libero", lasers.unique_name("Falcon ufficio") == "Falcon ufficio")

print("--- Rinomina")
p = MachineProfile.load(own)
p.bed_x = 321.0
p.save()
new_path, old_path = lasers.rename(p, "B1 del garage")
check("file nuovo scritto, vecchio tolto", os.path.exists(new_path) and not os.path.exists(old_path))
q = MachineProfile.load(new_path)
check("il file nuovo ha nome e impostazioni del laser", q.name == "B1 del garage" and q.bed_x == 321.0)
try:
    lasers.rename(q, "")
    check("nome vuoto: ValueError", False)
except ValueError as exc:
    check("nome vuoto: ValueError e il laser resta com'era", q.name == "B1 del garage" and os.path.exists(new_path), exc)
MachineProfile(name="Altro").save()
try:
    lasers.rename(q, "altro")
    check("nome di un altro laser: rifiutato", False)
except ValueError:
    check("nome di un altro laser: rifiutato, nessun file sovrascritto",
          MachineProfile.load(lasers.path_for("Altro")).name == "Altro" and q.name == "B1 del garage")
np2, op2 = lasers.rename(q, "B1 DEL GARAGE")
check("solo maiuscole cambiate: il file c'è ancora, con il nome nuovo",
      os.path.exists(np2) and MachineProfile.load(np2).name == "B1 DEL GARAGE"
      and len([f for f in os.listdir(PROF) if f.lower() == "b1_del_garage.json"]) == 1)
np3, _op3 = lasers.rename(q, "B1 DEL GARAGE!")
check("nome nuovo che va nello stesso file (simbolo in più): il file non si perde",
      np3 == np2 and os.path.exists(np3) and MachineProfile.load(np3).name == "B1 DEL GARAGE!")
lasers.rename(q, "B1 DEL GARAGE")
real_save = MachineProfile.save
MachineProfile.save = lambda self: (_ for _ in ()).throw(OSError("disco pieno"))
try:
    lasers.rename(q, "Nome che non si salva")
    check("errore di scrittura: OSError", False)
except OSError:
    check("errore di scrittura: nome di prima e file di prima intatti", q.name == "B1 DEL GARAGE" and os.path.exists(np2))
MachineProfile.save = real_save

print("--- elenco")
with open(os.path.join(PROF, "rovinato.json"), "w") as fh:
    fh.write("{ non è json")
with open(os.path.join(PROF, "copia_a_mano.json"), "w") as fh:
    json.dump(MachineProfile(name="Altro").file_dict(), fh)
names = [n for n, _ in lasers.saved()]
check("file rovinato scartato", not any("rovinato" in n for n in names), names)
check("nome doppio (file copiato a mano) distinto dal nome del file",
      "Altro" in names and "Altro (copia_a_mano.json)" in names, names)
os.remove(os.path.join(PROF, "copia_a_mano.json"))
os.remove(os.path.join(PROF, "rovinato.json"))

print("--- laser nuovo")
base = MachineProfile(name="Base")
base.bed_x, base.invert_x, base.tested_x, base.air_on = 380.0, True, True, "M7"
c = lasers.create("Secondo B1", like=base)
check("copia: stesse impostazioni (area, assi provati, aria), nome nuovo, salvato",
      c.name == "Secondo B1" and c.bed_x == 380.0 and c.invert_x and c.tested_x and c.air_on == "M7"
      and os.path.exists(c.path()) and base.name == "Base")
m = lasers.create("Falcon", model="Creality Falcon A1 Pro 20W")
check("da un modello: area del modello, nome scelto", m.name == "Falcon" and m.model == "Creality Falcon A1 Pro 20W"
      and (m.bed_x, m.bed_y) == (358.0, 268.0), (m.model, m.bed_x, m.bed_y))
g = lasers.create("Generico", model="modello che non esiste")
check("modello sconosciuto: laser GRBL generico", g.name == "Generico" and g.bed_x == 400.0)
try:
    lasers.create("falcon")
    check("nome già usato: rifiutato", False)
except ValueError:
    check("nome già usato: rifiutato", True)

print("--- porte e Togli")
from freelasercut.settings_store import app_settings  # noqa: E402

qs = app_settings()
lasers.remember_port(qs, m, "COM8")
check("porta ricordata per il laser", lasers.port_for(qs, m) == "COM8" and lasers.port_for(qs, c) == "")
old = m.path()
lasers.rename(m, "Falcon ufficio")
lasers.move_port(qs, old, m.path())
check("la porta segue il laser rinominato", lasers.port_for(qs, m) == "COM8" and qs.value("laser_port/falcon", "") == "")
check("Togli: file cancellato e porta dimenticata", lasers.remove(g.path(), qs) and not os.path.exists(g.path()))
check("Togli un file che non c'è: False", lasers.remove(g.path(), qs) is False)

# da qui l'interfaccia, partendo da una cartella dei profili pulita e senza profilo attivo (prima installazione)
for f in os.listdir(PROF):
    os.remove(os.path.join(PROF, f))
qs.remove("profile_path")
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
spin(0.3)
lp = w.laser_pick
print("--- tendina (" + os.environ["FLC_UI"] + ")")
check("tendina «Laser» in cima al pannello Laser, sopra la porta",
      w.laser.layout().indexOf(lp) == 0 and w.laser.layout().indexOf(w.connbar) == 1)
check("scheda d'aiuto della tendina", "laser_pick" in help_texts.HELP and lp.combo.property("help_key") == "laser_pick")
check("prima installazione: c'è il laser in uso anche se non salvato, tendina ferma (uno solo)",
      lp.combo.count() == 1 and lp.combo.currentText() == w.profile.name and not lp.combo.isEnabled())
w.rename_laser("Laser di casa")
check("Dai un nome: il laser in uso si salva con il nome nuovo e resta quello attivo",
      w.profile.name == "Laser di casa" and os.path.exists(w.profile.path())
      and w.qs.value("profile_path") == w.profile.path() and lp.combo.currentText() == "Laser di casa")
check("…il pannello Macchina mostra il nome nuovo", w.machine.profile_title.text() == "Laser di casa")
check("Dai un nome con un nome vuoto: non cambia nulla", w.rename_laser("  ") is None and w.profile.name == "Laser di casa")
before = w.profile.path()
falcon = w.add_laser("Falcon", model="Creality Falcon A1 Pro 20W")
spin(0.1)
check("Aggiungi da un modello: laser nuovo, in uso, piano del modello",
      falcon is not None and w.profile.name == "Falcon" and (w.canvas.bed_x, w.canvas.bed_y) == (358.0, 268.0))
check("…la tendina ora ne ha due ed è attiva", lp.combo.count() == 2 and lp.combo.isEnabled()
      and lp.combo.currentText() == "Falcon")
w.qs.setValue("laser_port/" + os.path.splitext(os.path.basename(before))[0].lower(), grbl.SIM_PORT)
i = lp.combo.findData(before)
lp.combo.setCurrentIndex(i)
lp.combo.activated.emit(i)
spin(0.1)
check("scelta dalla tendina: torna «Laser di casa» con il suo piano",
      w.profile.name == "Laser di casa" and (w.canvas.bed_x, w.canvas.bed_y) == (450.0, 440.0))
check("…ricordato come laser attivo al prossimo avvio", w.qs.value("profile_path") == before
      and w._load_active_profile().name == "Laser di casa")
check("…e la porta torna quella usata da quel laser", w.port_combo.currentData() == grbl.SIM_PORT)
FAKE["conn"] = True
lp.update_state()
check("laser collegato: tendina, Aggiungi e Togli fermi, Dai un nome sì",
      not lp.combo.isEnabled() and not lp.a_add.isEnabled() and not lp.a_remove.isEnabled() and lp.a_rename.isEnabled())
check("laser collegato: nessun cambio di laser anche chiamando la funzione",
      w.switch_laser(falcon.path()) is False and w.profile.name == "Laser di casa")
check("laser collegato: nessun laser aggiunto", w.add_laser("Terzo") is None and lp.combo.count() == 2)
FAKE["conn"] = False
lp.update_state()
check("Togli senza conferma: niente", w.remove_laser() is False and lp.combo.count() == 2)
check("Togli confermato: tolto, si passa all'altro", w.remove_laser(confirm=False) and w.profile.name == "Falcon"
      and lp.combo.count() == 1 and not os.path.exists(before))
check("l'ultimo laser rimasto non si toglie", w.remove_laser(confirm=False) is False and os.path.exists(w.profile.path()))
copia = w.add_laser("Falcon 2")
check("Aggiungi come copia del laser in uso", copia is not None and copia.model == "Creality Falcon A1 Pro 20W"
      and (copia.bed_x, copia.bed_y) == (358.0, 268.0) and lp.combo.count() == 2)
with open(falcon.path(), "w") as fh:
    fh.write("rovinato")
check("laser con il file rovinato nel frattempo: non si passa, resta quello in uso",
      w.switch_laser(falcon.path()) is False and w.profile.name == "Falcon 2")

print("--- traduzioni")
cats = {}
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", lang + ".json"), encoding="utf-8") as fh:
        cats[lang] = json.load(fh)
keys = ["Laser in uso: {0}", "Dai un nome a questo laser…", "Aggiungi un laser…", "Togli questo laser dall'elenco…",
        "Scrivi un nome per il laser.", "C'è già un laser che si chiama così (o quasi): scegli un altro nome.",
        help_texts.HELP["laser_pick"][1] if False else None]
keys = [k for k in keys if k]
check("testi principali nelle 4 lingue", all(k in c for c in cats.values() for k in keys),
      [k for k in keys for c in cats.values() if k not in c][:3])

w.close()
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(0 if all(results) else 1)
