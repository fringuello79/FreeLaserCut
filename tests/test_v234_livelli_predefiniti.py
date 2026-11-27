# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.4: livelli di partenza dei progetti nuovi (chiesto da Richmond; Ale, 26/11/2026).

Richmond: «blu contorno, rosso taglio: ogni volta che chiudo il programma non ci sono più». Fino alla 0.23.4 le
impostazioni dei livelli stavano solo nel file del progetto: un progetto nuovo (o un file importato) ripartiva sempre
dai valori di fabbrica. Ora *Laser → Usa questi livelli per i progetti nuovi* (anche dal tasto destro sulla tabella dei
livelli) li ricorda nelle preferenze; *Livelli dei progetti nuovi come di fabbrica* li dimentica.

Casi: senza scelta tutto come prima; si ricordano solo i livelli cambiati (non lo strumenti, non quelli di fabbrica);
progetto nuovo e file importato (SVG blu e rosso) partono con i livelli scelti; dopo aver chiuso e riaperto il
programma ci sono ancora; i progetti salvati tengono i loro livelli; una seconda scelta si aggiunge alla prima;
progetto ancora di fabbrica: messaggio e niente salvato; ritorno ai valori di fabbrica; preferenza rovinata; comandi
nel menu Laser, nel tasto destro della tabella e nella ricerca del Banco, con schede d'aiuto e traduzioni.
Difetti rimessi apposta: livello nuovo con i valori di fabbrica; preferenze non lette all'avvio.

Uso: python tests/test_v234_livelli_predefiniti.py [classica|banco]
"""
import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
for _k in ("FLC_NO_DIALOGS", "FLC_NO_FIRST_RUN", "FLC_NO_UPDATE"):
    os.environ[_k] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
for _n in ("question", "information", "warning"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: QMessageBox.Yes))

from freelasercut.core import document as D  # noqa: E402
from freelasercut.core import io_formats  # noqa: E402
from freelasercut.core.document import Document, RectShape  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402


def vals(cs):
    return (cs.mode, cs.speed, cs.power_max, cs.passes, cs.name)


FACT1 = vals(D.default_layer(1))
w = MainWindow()
w._confirm_discard = lambda: True
app.processEvents()
print("--- A. senza scelta: come prima")
check("all'inizio nessun livello ricordato e la preferenza non c'è", D.user_layers() == {}
      and w.qs.value(w.LAYER_DEFAULTS_KEY) is None)
w.file_new()
check("progetto nuovo: livelli di fabbrica (Linea, 1500 mm/min, 30 %)", vals(w.editor.doc.layer(1)) == FACT1
      and FACT1[:3] == ("line", 1500.0, 30.0), vals(w.editor.doc.layer(1)))
check("progetto ancora di fabbrica: «Usa questi livelli…» non salva niente", w.layers_as_default() == []
      and w.qs.value(w.LAYER_DEFAULTS_KEY) is None)

print("--- B. blu contorno, rosso taglio (il caso di Richmond)")
BLUE = io_formats.nearest_layer((0, 0, 255))
RED = io_formats.nearest_layer((255, 0, 0))
check("blu e rosso finiscono su due livelli diversi", BLUE != RED and 0 <= BLUE < 30 and 0 <= RED < 30, (BLUE, RED))
doc = w.editor.doc
for i, lay in ((BLUE, "c"), (RED, "t")):
    s = RectShape(20, 20)
    s.layer = i
    doc.add(s)
c = doc.layer(BLUE)
c.mode, c.speed, c.power_max, c.name = "line", 900.0, 12.0, "Contorno"
t = doc.layer(RED)
t.mode, t.speed, t.power_max, t.passes, t.name = "line", 300.0, 95.0, 3, "Taglio"
doc.layer(D.USER_LAYER_MAX).speed = 777.0  # livello strumenti: non si ricorda
saved = w.layers_as_default()
check("si ricordano i due livelli cambiati, non il livello strumenti", saved == sorted((BLUE, RED)), saved)
raw = json.loads(w.qs.value(w.LAYER_DEFAULTS_KEY))
check("…nelle preferenze, senza indice e senza livelli di fabbrica", sorted(raw) == sorted((str(BLUE), str(RED)))
      and all("index" not in d for d in raw.values()), sorted(raw))
check("i livelli di questo progetto non cambiano", vals(doc.layer(BLUE))[:3] == ("line", 900.0, 12.0))
w.file_new()
n = w.editor.doc
check("progetto nuovo: blu = contorno (900 mm/min, 12 %)", vals(n.layer(BLUE)) == ("line", 900.0, 12.0, 1, "Contorno"),
      vals(n.layer(BLUE)))
check("progetto nuovo: rosso = taglio (300 mm/min, 95 %, 3 passate)",
      vals(n.layer(RED)) == ("line", 300.0, 95.0, 3, "Taglio"), vals(n.layer(RED)))
other = next(i for i in range(1, 30) if i not in (BLUE, RED))
check("gli altri livelli restano di fabbrica", vals(n.layer(other)) == vals(D.default_layer(other)))
check("ogni progetto ha la sua copia (cambiarla non tocca i livelli ricordati)",
      (setattr(n.layer(BLUE), "speed", 1.0), D.default_layer(BLUE, user=True).speed == 900.0)[1])

svg = os.path.join(TMP, "richmond.svg")
open(svg, "w", encoding="utf-8").write(
    '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
    '<rect x="10" y="10" width="30" height="30" fill="none" stroke="#0000FF"/>'
    '<rect x="50" y="50" width="30" height="30" fill="none" stroke="#FF0000"/></svg>')
w.file_new()
w.import_files([svg])
app.processEvents()
used = {cs.index: vals(cs) for cs in w.editor.doc.used_layers()}
check("SVG importato (blu e rosso): i colori prendono i livelli ricordati",
      used.get(BLUE, ("",))[:3] == ("line", 900.0, 12.0) and used.get(RED, ("",))[:4] == ("line", 300.0, 95.0, 3), used)

print("--- C. chiuso e riaperto il programma")
w.close()
w2 = MainWindow()
w2._confirm_discard = lambda: True
app.processEvents()
w2.file_new()
check("dopo la riapertura i livelli ricordati ci sono ancora",
      vals(w2.editor.doc.layer(RED))[:4] == ("line", 300.0, 95.0, 3), vals(w2.editor.doc.layer(RED)))

print("--- D. progetti salvati")
old = Document()
r = RectShape(10, 10)
r.layer = RED
old.add(r)
oc = old.layer(RED)
oc.speed, oc.power_max = 2000.0, 40.0
p = os.path.join(TMP, "vecchio.fbrn")
old.save(p)
again = Document.load(p)
check("un progetto salvato tiene i suoi livelli (2000 mm/min, 40 %), non quelli ricordati",
      (again.layer(RED).speed, again.layer(RED).power_max) == (2000.0, 40.0), vals(again.layer(RED)))

print("--- E. aggiungere, tornare alla fabbrica")
d3 = w2.editor.doc
x = d3.layer(other)
x.mode, x.speed = "fill", 4000.0
w2.layers_as_default()
check("una seconda scelta si aggiunge alla prima (rosso e blu restano)",
      sorted(D.user_layers()) == sorted((BLUE, RED, other)), sorted(D.user_layers()))
check("fabbrica: «Livelli dei progetti nuovi come di fabbrica» dimentica tutto", w2.layers_factory() is True
      and D.user_layers() == {} and w2.qs.value(w2.LAYER_DEFAULTS_KEY) is None)
w2.file_new()
check("…e il progetto nuovo riparte dai valori di fabbrica", vals(w2.editor.doc.layer(RED)) == vals(D.default_layer(RED)))
check("ripetuto quando è già di fabbrica: dice che lo è già", w2.layers_factory() is False)

w2.qs.setValue(w2.LAYER_DEFAULTS_KEY, "{rovinato")
w2._load_layer_defaults()
ok1 = D.user_layers() == {}
w2.qs.setValue(w2.LAYER_DEFAULTS_KEY, json.dumps({"3": {"speed": "veloce?", "mode": 7}, "99": {"speed": 1.0},
                                                   "x": 1, "4": {"speed": 650.0}}))
w2._load_layer_defaults()
check("preferenza rovinata o di una versione futura: si salta quello che non si legge, il resto vale",
      ok1 and 99 not in D.user_layers() and D.default_layer(4, user=True).speed == 650.0, D.user_layers())
w2.layers_factory()

print("--- F. dove si trovano")
a1, a2 = w2.acts.get("layers_as_default"), w2.acts.get("layers_factory")
laser = [a for a in w2.menuBar().actions() if a.menu() is not None and "Laser" in a.text()]
check("nel menu Laser", a1 is not None and a2 is not None and laser and a1 in laser[0].menu().actions()
      and a2 in laser[0].menu().actions())
w2.file_new()
_rc = RectShape(10, 10)
_rc.layer = RED
w2.editor.doc.add(_rc)
w2.editor.doc.layer(RED).speed = 444.0
w2.layers.defaults_requested.emit()  # quello che fa la voce del tasto destro
check("dal tasto destro della tabella dei livelli: ricorda davvero i livelli",
      D.default_layer(RED, user=True).speed == 444.0, D.user_layers())
w2.layers_factory()
src = open(os.path.join(ROOT, "freelasercut", "ui", "panels_design.py"), encoding="utf-8").read()
check("…la voce è nel menu del tasto destro", 'tr("Usa questi livelli per i progetti nuovi"), self.defaults_requested.emit'
      in src)
if UI == "banco":
    w2.banco.palette.collect()
    names = [a.text() for a, _ in w2.banco.palette.entries]
    check("Banco: si trova con la ricerca dei comandi (Ctrl+F)", "Usa questi livelli per i progetti nuovi" in names)
from freelasercut.ui import help_texts  # noqa: E402

check("schede d'aiuto per i due comandi", bool(help_texts.lookup("layers_as_default"))
      and bool(help_texts.lookup("layers_factory")))
for lang, word in (("en", "Use these layers for new projects"), ("es", "Usar estas capas en los proyectos nuevos"),
                   ("fr", "Utiliser ces calques pour les nouveaux projets"), ("pt", "Usar estas camadas nos projetos novos")):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    check(f"tradotto ({lang})", cat.get("Usa questi livelli per i progetti nuovi") == word)

print("--- G. difetti rimessi apposta")
D.set_user_layers({str(RED): {"speed": 300.0, "power_max": 95.0}})
real_layer = Document.layer


def broken(self, index):  # come fino alla 0.23.4: livello nuovo sempre di fabbrica
    if index not in self.layers:
        self.layers[index] = D.default_layer(index)
    return self.layers[index]


Document.layer = broken
seen1 = Document().layer(RED).speed != 300.0
Document.layer = real_layer
check("difetto 1 (livello nuovo di fabbrica): la prova se ne accorge", seen1)
w2.qs.setValue(w2.LAYER_DEFAULTS_KEY, json.dumps({str(RED): {"speed": 300.0}}))
D.set_user_layers({})
real_load = MainWindow._load_layer_defaults
MainWindow._load_layer_defaults = lambda self: None
w3 = MainWindow()
seen2 = Document().layer(RED).speed != 300.0
MainWindow._load_layer_defaults = real_load
check("difetto 2 (preferenze non lette all'avvio): la prova se ne accorge", seen2)
w3.close()
w2.layers_factory()

ok = sum(results)
print(f"{ok}/{len(results)} prove superate")
sys.exit(0 if ok == len(results) else 1)
