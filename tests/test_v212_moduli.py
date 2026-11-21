# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: moduli aggiuntivi (`freelasercut/moduli.py`) e programma senza comandi per macchine non GRBL.

Moduli finti in una cartella temporanea: uno buono e uno per ogni modo di essere sbagliato. Il programma deve caricare
solo quello buono e continuare come se gli altri non ci fossero.

Uso: python tests/test_v212_moduli.py [classica|banco]
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="flc_test_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(TMP, "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_LANG"] = "en"
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
MODS = os.path.join(TMP, "moduli-di-prova")
os.environ["FLC_MODULI_DIR"] = os.path.join(TMP, "non-esiste")

from PySide6.QtWidgets import QApplication  # noqa: E402

from freelasercut import __version__, diag, i18n, moduli  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info else ""), flush=True)


def make(name, manifest=None, code=None, raw=None):
    d = os.path.join(MODS, name)
    os.makedirs(d)
    if raw is not None:
        with open(os.path.join(d, "modulo.json"), "w", encoding="utf-8") as fh:
            fh.write(raw)
    elif manifest is not None:
        base = {"id": name, "nome": "Modulo " + name, "versione": "1.0", "api": moduli.API, "flc_min": "0.21.2"}
        base.update(manifest)
        with open(os.path.join(d, "modulo.json"), "w", encoding="utf-8") as fh:
            json.dump(base, fh)
    if code is not None:
        with open(os.path.join(d, "__init__.py"), "w", encoding="utf-8") as fh:
            fh.write(code)
    return d


GOOD = '''
from freelasercut.i18n import tr
from . import aiuto
calls = []
def registra(api):
    api.add_translations({"en": {"Saluta dal modulo": "Hello from the module", "Salva": "NON DEVE VINCERE"},
                          "fr": {"Saluta dal modulo": "Bonjour du module"}})
    api.add_action("mod_saluta", tr("Saluta dal modulo"), lambda: calls.append(aiuto.VALORE), icon="export",
                   tip=tr("Saluta dal modulo"), menu="file", after="export", help=("Saluto", "Scheda del saluto"))
    api.add_action("mod_rotto", "Comando che sbaglia", lambda: 1 / 0, menu="file", after="mod_saluta")
'''
os.makedirs(MODS)
make("buono", {}, GOOD)
with open(os.path.join(MODS, "buono", "aiuto.py"), "w", encoding="utf-8") as fh:
    fh.write("VALORE = 42\n")
make("senza_json", None, "def registra(api):\n    raise SystemExit('non deve partire')\n")
make("json_rotto", None, "def registra(api):\n    pass\n", raw="{ questo non è json")
make("altro_nome", {"id": "diverso"}, "def registra(api):\n    pass\n")
make("api_vecchia", {"api": 0}, "def registra(api):\n    pass\n")
make("troppo_nuovo", {"flc_min": "99.0.0"}, "def registra(api):\n    pass\n")
make("troppo_vecchio", {"flc_min": "0.1.0", "flc_max": "0.20.0"}, "def registra(api):\n    pass\n")
make("senza_init", {})
make("non_si_importa", {}, "def registra(api:\n")
make("a_meta", {}, "def registra(api):\n    api.add_action('mod_a_meta', 'A metà', lambda: None)\n    raise RuntimeError('guasto')\n")
make("prepotente", {}, "def registra(api):\n    api.add_action('save', 'Salva (finto)', lambda: None)\n")
make("_nascosto", {}, "def registra(api):\n    raise SystemExit('non deve partire')\n")

app = QApplication([])
i18n.set_language("en")
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

# ------------------------------------------------------------ senza cartella dei moduli: tutto come prima
print("--- senza moduli")
w0 = MainWindow()
check("cartella «moduli» assente: nessun modulo, nessuna riga nel rapporto, la cartella non viene creata",
      moduli.LOADED == [] and moduli.summary() == "" and not os.path.exists(os.environ["FLC_MODULI_DIR"])
      and "Moduli aggiuntivi" not in diag.summary_text(win=w0))
check("cartella predefinita: «moduli» dentro la cartella dei dati di FreeLaserCut",
      (os.environ.pop("FLC_MODULI_DIR"), moduli.folder())[1] == os.path.join(TMP, "FreeLaserCut", "moduli"))
n_acts, save_text = len(w0.acts), w0.acts["save"].text()
check("0.21.2: nel programma non ci sono più comandi per macchine non GRBL",
      not ({"export_xs", "export_m2", "m2_link"} & set(w0.acts)) and not ({"export_xs", "export_m2", "m2_link"} & set(help_texts.HELP)))
w0.editor.dirty = False
w0.close()

# ------------------------------------------------------------ con i moduli finti
print("--- moduli finti")
os.environ["FLC_MODULI_DIR"] = MODS
w = MainWindow()
by = {i.id: i for i in moduli.LOADED}
check("trovati tutti, tranne la cartella che comincia con «_»", set(by) == {
    "buono", "senza_json", "json_rotto", "altro_nome", "api_vecchia", "troppo_nuovo", "troppo_vecchio", "senza_init",
    "non_si_importa", "a_meta", "prepotente"}, sorted(by))
check("caricato solo quello buono", [i.id for i in moduli.LOADED if i.loaded] == ["buono"],
      [(i.id, i.error) for i in moduli.LOADED if i.loaded])
why = {k: v.error for k, v in by.items()}
check("modulo.json mancante o rovinato: non si carica e dice perché",
      "manca modulo.json" in why["senza_json"] and "rovinato" in why["json_rotto"], (why["senza_json"], why["json_rotto"]))
check("identificativo diverso dalla cartella, interfaccia di un'altra versione, __init__.py mancante",
      "identificativo" in why["altro_nome"] and "interfaccia" in why["api_vecchia"] and "__init__" in why["senza_init"])
check("versione di FreeLaserCut non adatta (troppo vecchia o oltre il massimo provato)",
      "99.0.0" in why["troppo_nuovo"] and "0.20.0" in why["troppo_vecchio"], __version__)
check("errore mentre si importa o dentro registra(): resta del modulo, il programma parte",
      "SyntaxError" in why["non_si_importa"] and "guasto" in why["a_meta"] and w.isVisible() is False and w.acts)
check("un modulo fermato a metà non lascia comandi", "mod_a_meta" not in w.acts
      and not [k for k in sys.modules if k.startswith(("flc_modulo_a_meta", "flc_modulo_non_si_importa"))])
check("un modulo non può prendere il posto di un comando che c'è già",
      "c'è già" in why["prepotente"] and w.acts["save"].text() == save_text and w.acts["save"] in w.m_file.actions())
check("comandi del programma: solo i due del modulo buono in più", len(w.acts) == n_acts + 2, (n_acts, len(w.acts)))

acts = w.m_file.actions()
a = w.acts.get("mod_saluta")
check("comando del modulo nel menu File subito dopo «Esporta SVG», poi il secondo",
      a in acts and acts.index(a) == acts.index(w.acts["export"]) + 1 and acts.index(w.acts["mod_rotto"]) == acts.index(a) + 1)
check("testo tradotto dal modulo e scheda d'aiuto", a.text() == "Hello from the module" and help_texts.HELP["mod_saluta"][1] == "Scheda del saluto",
      a.text())
check("le traduzioni di un modulo non cambiano quelle del programma", i18n.tr("Salva") == "Save")
i18n.set_language("fr")
check("…e restano quando si cambia lingua", i18n.tr("Saluta dal modulo") == "Bonjour du module" and i18n.tr("Salva") != "NON DEVE VINCERE")
i18n.set_language("en")
a.trigger()
good = sys.modules["flc_modulo_buono"]
check("il comando gira e usa i file del suo pacchetto", good.calls == [42])
w.acts["mod_rotto"].trigger()
check("errore dentro un comando: resta del modulo, lo dice nella barra, il programma continua",
      "ZeroDivisionError" in by["buono"].error and "ZeroDivisionError" in w.statusBar().currentMessage()
      and (a.trigger(), good.calls)[1] == [42, 42], w.statusBar().currentMessage())
line = moduli.summary()
check("riga per i rapporti: caricati e non caricati con il motivo", line.startswith("Moduli aggiuntivi: ") and "buono 1.0" in line
      and "senza_json (non caricato: manca modulo.json)" in line and line in diag.summary_text(win=w), line)

# ------------------------------------------------------------ quando i moduli sono spenti
print("--- spenti")
check("versione del Microsoft Store: moduli spenti; installatore e sorgente: accesi",
      not moduli.enabled(r"C:\Program Files\WindowsApps\FreeLaserCut_1.0\python\pythonw.exe")
      and moduli.enabled(r"C:\Users\x\AppData\Local\Programs\FreeLaserCut\python\pythonw.exe") and moduli.enabled())
os.environ["FLC_NO_MODULI"] = "1"
check("FLC_NO_MODULI=1: non si carica niente", not moduli.enabled() and moduli.load_all(w) == [] and len(w.acts) == n_acts + 2)
del os.environ["FLC_NO_MODULI"]

# ------------------------------------------------------------ niente codice per macchine non GRBL nel pacchetto pubblico
print("--- pacchetto pubblico")
tracked = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True,
                         text=True).stdout.split("\n")
files = [f for f in tracked if f and os.path.isfile(os.path.join(ROOT, f))] or [os.path.relpath(os.path.join(r, f), ROOT) for r, _d, fs in os.walk(ROOT)
                                      for f in fs if ".git" + os.sep not in r]
names = [f for f in files if any(x in f.lower() for x in ("xtool", "m2link", "m2_finta"))]
check("nessun file con quei nomi nel repository", not names, names)
hits = []
for f in files:
    if not f.endswith((".py", ".json", ".md", ".html", ".nsi", ".txt", ".yml")) or f.endswith("test_v212_moduli.py"):
        continue
    try:
        text = open(os.path.join(ROOT, f), encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    if any(x in text for x in ("xTool Studio", "xTool M2", "xtool_m2", "xtool_xs", "m2_link_dialog", "M2Link")):
        hits.append(f)
check("nessun testo che ne parla nei file del programma, del sito e della documentazione", not hits, hits)

w.editor.dirty = False
ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
