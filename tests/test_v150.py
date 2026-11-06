# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.15.0: piani di lavoro. Più lavori nello stesso progetto, con la stessa macchina e gli stessi livelli:
mentre il laser incide un piano si prepara il successivo, con gli oggetti degli altri piani visibili in grigio.
- ogni piano ha le sue forme e la sua cronologia (annulla/ripeti);
- un solo file .flcut con tutti i piani; le versioni precedenti aprono il primo piano;
- si incide solo il piano attivo; quello in incisione ha ▶ e l'avanzamento sulla sua scheda;
- sposta su un altro piano, duplica, rinomina, elimina; Ctrl+PagSu / Ctrl+PagGiù per cambiare piano."""
import json
import os
import sys
import tempfile
import time
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
from freelasercut.core.document import Document, EllipseShape, ImageShape, RectShape, TextShape
from freelasercut.ui.editor import Editor

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def rect(x, y, w=20, h=10, layer=1):
    r = RectShape(w, h, layer=layer)
    r.apply(QTransform.fromTranslate(x, y))
    return r


# ================================================================== documento
d = Document()
check("progetto nuovo: un piano, «Piano 1», le forme sono quelle del piano attivo",
      len(d.plates) == 1 and d.plate_name(0) == "Piano 1" and d.shapes is d.plates[0].shapes)
d.add(rect(10, 10))
i = d.add_plate()
d.current = i
check("secondo piano vuoto, con i livelli in comune", d.shapes == [] and d.plate_name(1) == "Piano 2" and 1 in d.layers)
d.add(EllipseShape(30, 30, layer=4))
check("forme separate per piano; tutte e «altre» corrette", len(d.plates[0].shapes) == 1 and len(d.plates[1].shapes) == 1
      and len(d.all_shapes()) == 2 and d.other_shapes() == d.plates[0].shapes)
check("livelli usati: quelli di tutti i piani", d.used_layer_indices() == {1, 4})
check("lavoro e livelli del lavoro: solo il piano attivo", [c.index for c in d.used_layers()] == [4])

# ---- file
D = tempfile.mkdtemp()
d.images["foto1"] = Image.new("L", (8, 8), 128)
img = ImageShape("foto1", 20, 20, layer=0)
d.add(img)
d.plates[1].name = "Coperchio"
d.add_plate()
fp = os.path.join(D, "tre.flcut")
d.save(fp)
with zipfile.ZipFile(fp) as z:
    meta = json.loads(z.read("project.json"))
    names = z.namelist()
check("file: «shapes» è il primo piano (le versioni precedenti aprono quello), gli altri in «plates»",
      len(meta["shapes"]) == 1 and len(meta["plates"]) == 3 and "shapes" not in meta["plates"][0]
      and len(meta["plates"][1]["shapes"]) == 2 and meta["current"] == 1)
check("file: le foto di tutti i piani sono salvate", "images/foto1.png" in names)
d2 = Document.load(fp)
check("riaperto: tre piani con nomi, forme e piano attivo", len(d2.plates) == 3 and d2.current == 1
      and d2.plate_name(1) == "Coperchio" and d2.plate_name(2) == "Piano 3"
      and [len(p.shapes) for p in d2.plates] == [1, 2, 0] and "foto1" in d2.images
      and {s.id for s in d2.all_shapes()} == {s.id for s in d.all_shapes()})
one = Document()
one.add(rect(5, 5))
fp1 = os.path.join(D, "uno.flcut")
one.save(fp1)
with zipfile.ZipFile(fp1) as z:
    m1 = json.loads(z.read("project.json"))
check("progetto con un piano solo: file come prima (niente «plates»)", "plates" not in m1 and len(m1["shapes"]) == 1)
check("progetto di una versione precedente: si apre come Piano 1", len(Document.load(fp1).plates) == 1
      and len(Document.load(fp1).shapes) == 1)

# ================================================================== cronologia per piano
ed = Editor(Document())
a = rect(10, 10)
ed.add([a])
ed.add_plate()
b = rect(100, 100)
ed.add([b])
ed.add([rect(200, 100)])
check("nuovo piano: diventa attivo, cronologia sua", ed.doc.current == 1 and len(ed.undo_stack) == 2)
ed.undo()
check("annulla sul piano 2: tocca solo il piano 2", len(ed.doc.shapes) == 1 and len(ed.doc.plates[0].shapes) == 1)
ed.set_plate(0)
check("sul piano 1 la sua cronologia", len(ed.undo_stack) == 1 and ed.undo_label() == "Aggiungi" and not ed.selection)
cs = ed.doc.layer(1)
ed.run("Velocità", lambda: setattr(cs, "speed", 4321.0))
ed.set_plate(1)
ed.redo()
ed.undo()
check("annulla sul piano 2 non rimette i livelli cambiati sul piano 1", ed.doc.layer(1).speed == 4321.0
      and len(ed.doc.shapes) == 1, ed.doc.layer(1).speed)
ed.set_plate(0)
ed.undo()
check("annulla sul piano 1 rimette il suo livello", ed.doc.layer(1).speed != 4321.0)

# ---- sposta su un altro piano
ed = Editor(Document())
s1, s2, s3 = rect(10, 10), rect(50, 10), rect(90, 10)
ed.add([s1, s2, s3])
ed.add_plate()
ed.add([rect(10, 200)])
ed.set_plate(0)
ed.select([s1, s2])
n = ed.move_to_plate(ed.selection, 1)
check("sposta sul piano 2: spariscono da qui, compaiono là nella stessa posizione", n == 2 and ed.doc.shapes == [s3]
      and len(ed.doc.plates[1].shapes) == 3 and ed.doc.plates[1].shapes[-1].bounds() == s2.bounds())
ed.undo()
check("annulla: tornano sul piano 1 e spariscono dal piano 2", len(ed.doc.shapes) == 3
      and len(ed.doc.plates[1].shapes) == 1 and {s.id for s in ed.doc.shapes} == {s1.id, s2.id, s3.id})
ed.redo()
check("ripeti: di nuovo sul piano 2 (una volta sola)", len(ed.doc.shapes) == 1 and len(ed.doc.plates[1].shapes) == 3
      and len({s.id for s in ed.doc.plates[1].shapes}) == 3)
ed.set_plate(1)
ed.select(ed.doc.shapes[-1:])
ed.copy()
ed.set_plate(0)
pasted = ed.paste(in_place=True)
check("copia sul piano 2, incolla sul piano 1", len(pasted) == 1 and len(ed.doc.shapes) == 2)
k = ed.duplicate_plate(1)
check("duplica il piano: in fondo, stesse posizioni, oggetti nuovi", k == 2 and ed.doc.current == 2
      and ed.doc.plate_name(2) == "Piano 2 (copia)" and len(ed.doc.shapes) == 3
      and not {s.id for s in ed.doc.shapes} & {s.id for s in ed.doc.plates[1].shapes}
      and [s.bounds() for s in ed.doc.shapes] == [s.bounds() for s in ed.doc.plates[1].shapes])
ed.rename_plate(2, "Scatola")
ed.set_plate(1)
ed.remove_plate(0)
check("elimina il piano 1: resta attivo quello di prima, i nomi seguono", len(ed.doc.plates) == 2 and ed.doc.current == 0
      and ed.doc.plate_name(0) == "Piano 1" and ed.doc.plate_name(1) == "Scatola" and len(ed.doc.shapes) == 3)
check("non si elimina l'ultimo piano", not ed.remove_plate(0) or len(ed.doc.plates) == 1)

# ---- spostamenti e cronologie dei due piani sempre coerenti (niente doppioni, niente perdite)
def count(ed, sid):
    return sum(1 for s in ed.doc.all_shapes() for leaf, _ in s.leaves() if leaf.id == sid)


ed = Editor(Document())
A = rect(10, 10)
ed.add([A])
ed.add_plate()
ed.add([rect(100, 100)])  # il piano 2 ha già una sua cronologia
ed.set_plate(0)
ed.move_to_plate([A], 1)
ed.set_plate(1)
ed.add([rect(150, 150)])
ed.set_plate(0)
ed.undo()
ed.set_plate(1)
while ed.undo_stack:
    ed.undo()
check("annulla lo spostamento, poi annulla tutto sul piano di arrivo: l'oggetto c'è una volta sola", count(ed, A.id) == 1
      and A.id in {s.id for s in ed.doc.plates[0].shapes}, count(ed, A.id))
ed = Editor(Document())
A = rect(10, 10)
ed.add([A])
ed.add_plate()
ed.add([rect(100, 100)])
ed.set_plate(0)
ed.move_to_plate([A], 1)
ed.set_plate(1)
ed.undo()
ed.redo()
check("annulla/ripeti sul piano di arrivo dopo uno spostamento: l'oggetto arrivato non si perde", count(ed, A.id) == 1
      and A.id in {s.id for s in ed.doc.shapes})
ed.select(list(ed.doc.shapes))
ed.group()
ed.set_plate(0)
said = []
ed.message.connect(said.append)
ed.undo()
check("oggetto spostato e poi raggruppato di là: annulla lo spostamento non lo duplica, lo dice",
      count(ed, A.id) == 1 and not ed.undo_stack and said and "non si può più annullare" in said[-1], said[-1:])
ed = Editor(Document())
A = rect(10, 10)
ed.add([A])
ed.add_plate()
ed.set_plate(0)
ed.move_to_plate([A], 1)
ed.undo()
ed.remove_plate(1)
ed.redo()
check("ripeti lo spostamento verso un piano eliminato: l'oggetto resta sul piano di partenza", count(ed, A.id) == 1
      and len(ed.doc.shapes) == 1)
ed = Editor(Document())
A = rect(10, 10)
ed.add([A])
ed.add_plate()
ed.add_plate()
ed.set_plate(0)
ed.move_to_plate([A], 1)  # piano 1 -> piano 2
ed.set_plate(1)
ed.move_to_plate([A], 2)  # piano 2 -> piano 3
ed.remove_plate(1)  # il piano di passaggio sparisce
ed.set_plate(0)
ed.undo()
check("sposta 1→2→3, elimina il piano 2, annulla sul piano 1: l'oggetto resta uno solo (sul piano 3)",
      count(ed, A.id) == 1 and A.id in {s.id for s in ed.doc.plates[1].shapes})
ed = Editor(Document())
ed.add([rect(10, 10, layer=7)])
ed.add_plate()
ed.add([rect(50, 50, layer=7)])
cs7 = ed.doc.layer(7)
ed.run("Velocità", lambda: setattr(cs7, "speed", 300.0))
ed.set_plate(0)
ed.undo()
check("annulla sul piano 1 non toglie un livello usato dal piano 2 (con le sue impostazioni)", 7 in ed.doc.layers
      and ed.doc.layers[7].speed == 300.0)

# ---- copie di gruppi dentro gruppi: mai due forme con lo stesso id (incolla, duplica, serie, duplica il piano)
def all_ids(ed):
    out = []

    def walk(s):
        out.append(s.id)
        for c in getattr(s, "children", None) or ():
            walk(c)
    for p in ed.doc.plates:
        for s in p.shapes:
            walk(s)
    return out


ed = Editor(Document())
ed.add([rect(0, 0), rect(30, 0), rect(60, 0)])
ed.select(ed.doc.shapes[:2])
ed.group()
ed.select(list(ed.doc.shapes))
ed.group()  # gruppo con dentro un altro gruppo
ed.select(list(ed.doc.shapes))
ed.copy()
ed.paste(in_place=True)
ed.duplicate()
ed.select(ed.doc.shapes[:1])
ed.grid_array(2, 1, 5, 5)
ed.duplicate_plate(0)
for _ in range(3):
    for s in list(ed.doc.shapes):
        ed.select([s])
        ed.ungroup()
ids_all = all_ids(ed)
check("gruppi dentro gruppi copiati, duplicati, in serie e su un piano duplicato: ogni forma ha il suo id",
      len(ids_all) == len(set(ids_all)) and len(ids_all) > 20, (len(ids_all), len(set(ids_all))))
ed = Editor(Document())
A = rect(10, 10)
ed.add([A])
ed.add_plate()
ed.set_plate(0)
ed.move_to_plate([A], 1)
ed.set_plate(1)
ed.select(list(ed.doc.shapes))
ed.transform(QTransform.fromTranslate(40, 0))
ed.set_plate(0)
ed.undo()
ed.redo()
moved = ed.doc.plates[1].shapes
check("sposta, poi lo muovi sull'altro piano, annulla e ripeti lo spostamento: torna com'era diventato là",
      len(moved) == 1 and abs(moved[0].bounds().left() - 50) < 1e-6, moved[0].bounds().left() if moved else None)
ed = Editor(Document())
ed.add([rect(10, 10, layer=6)])
ed.add_plate()
ed.add([rect(20, 20, layer=6)])
ed.undo()  # sul piano 2: il livello 6 resta (lo usa il piano 1)
ed.doc.layers.pop(6)  # come se un altro passo l'avesse tolto
ed.redo()
ed.set_plate(0)
check("annulla/ripeti rimettono le impostazioni di un livello usato che mancava", 6 in ed.doc.layers)

# ---- foto e disegni: i livelli sono di tutti i piani
ed = Editor(Document())
ed.doc.images["f"] = Image.new("L", (8, 8), 100)
ed.add([ImageShape("f", 30, 30, layer=5)])
ed.add_plate()
t = TextShape("Ciao", size=8, layer=5)
ed.add([t])
check("una scritta sul livello di una foto di un altro piano va su un livello suo", t.layer != 5
      and ed.doc.layer(5).mode == "image", t.layer)

# ================================================================== finestra
from freelasercut.grbl import SIM_PORT
from freelasercut.ui.main_window import MainWindow

w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
bar = w.plate_bar
from PySide6.QtCore import QPointF

until(lambda: False, 0.3)


def on_corner():
    c = w.canvas.to_view(QPointF(0, w.canvas.bed_y))
    g = bar.geometry()
    return abs(g.left() - c.x()) <= 1.5 and abs(g.bottom() + 1 - c.y()) <= 2.5, (g.left(), g.bottom(), c.x(), c.y())


ok, info = on_corner()
check("linguetta «Piano 1» e + attaccate in alto a sinistra al bordo del piano", bar.isVisible() and bar.tabs.count() == 1
      and bar.tabs.tabText(0) == "Piano 1" and bar.add_btn.isVisible() and not bar.ghosts.isVisible() and ok, info)
w.canvas.zoom_by(1.6)
w.canvas.viewport().repaint()
until(lambda: False, 0.2)
from freelasercut.ui.canvas import RULER

g = bar.geometry()
c = w.canvas.to_view(QPointF(0, w.canvas.bed_y))
check("con lo zoom la linguetta segue il bordo (o resta in alto, sotto i righelli, se il bordo è fuori vista)",
      (on_corner()[0] if c.y() - g.height() >= RULER + 2 and c.x() >= RULER + 4 else g.top() >= RULER + 2
       and g.left() >= RULER + 4), (g.left(), g.top(), c.x(), c.y()))
w.canvas.fit_bed() if hasattr(w.canvas, "fit_bed") else None
w.canvas.viewport().repaint()
until(lambda: False, 0.2)
big = rect(20, 20, 120, 60, layer=1)
w.editor.doc.layer(1).mode = "fill"
w.editor.doc.layer(1).interval = 0.5
w.editor.add([big])
bar.add_btn.click()
app.processEvents()
check("+ attiva subito anche Ctrl+PagSu/PagGiù ed Elimina il piano", w.acts["plate_next"].isEnabled()
      and w.acts["plate_prev"].isEnabled() and w.acts["plate_delete"].isEnabled())
check("+: nuovo piano attivo, «Mostra gli altri piani» compare", bar.tabs.count() == 2 and bar.tabs.currentIndex() == 1
      and w.editor.doc.current == 1 and bar.ghosts.isVisible())
check("sulla tela solo gli oggetti del piano attivo", not w.canvas.items_by_id)
gp = w.canvas.ghost_path()
check("gli oggetti del piano 1 si vedono in grigio", gp is not None and gp.boundingRect() == big.bounds())
bar.ghosts.setChecked(False)
check("«Mostra gli altri piani» spento: niente grigio (e il menu segue)", w.canvas.ghost_path() is None
      and not w.acts["plate_ghosts"].isChecked())
w.acts["plate_ghosts"].trigger()
check("riacceso dal menu", w.canvas.ghost_path() is not None and bar.ghosts.isChecked())
w.acts["plate_prev"].trigger()
app.processEvents()
check("Ctrl+PagSu: torna al piano 1, la tela mostra i suoi oggetti", w.editor.doc.current == 0 and bar.tabs.currentIndex() == 0
      and big.id in w.canvas.items_by_id)
bar.tabs.setCurrentIndex(1)
check("clic sulla scheda: piano 2", w.editor.doc.current == 1)
w.acts["plate_next"].trigger()
check("Ctrl+PagGiù dall'ultimo: torna al primo", w.editor.doc.current == 0)
check("livelli liberi per gli strumenti: contano tutti i piani", 1 not in w._free_layers(3))

# ---- un lavoro vero (simulatore) sul piano 1, mentre si prepara il piano 2
QMessageBox.exec = lambda self: 0
QMessageBox.clickedButton = lambda self: next(b for b in self.buttons() if self.buttonRole(b) == QMessageBox.AcceptRole)
w.laser.verify_first.setChecked(False)
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 3
until(lambda: w.ctl.board_settings and w.ctl.last_status.get("state") in ("Idle", "Alarm"))
w.ctl.home()
until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 15)
plan1 = list(w.build_job(show=False).lines)
w.start_job()
check("lavoro avviato dal piano 1", until(lambda: w.ctl.job_active, 5) and w._job_plate == w.editor.doc.plates[0].uid)
sent = list(w.ctl.job_lines)
msgs = []
w.statusBar().messageChanged.connect(msgs.append)
bar.tabs.setCurrentIndex(1)
app.processEvents()
until(lambda: w.ctl.job_acked > 5, 10)
bar.refresh()
check("linguetta del piano in incisione: ▶ e avanzamento; il suggerimento dice cosa succede",
      bar.tabs.tabText(0).startswith("▶ Piano 1 ·") and bar.tabs.tabText(0).endswith("%")
      and "in incisione" in bar.tabs.tabToolTip(0) and any("Ora lavori su «Piano 2»" in m for m in msgs),
      (bar.tabs.tabText(0), bar.tabs.tabToolTip(0)))
lid = rect(30, 100, 50, 40)
w.editor.add([lid])
w.editor.add([rect(150, 100, 30, 30)])
w.editor.undo()
w.editor.select([lid])
w.editor.transform(QTransform.fromTranslate(5, 0))
check("durante il lavoro si disegna sul piano 2 (aggiungi, annulla, sposta)", len(w.editor.doc.shapes) == 1
      and w.ctl.job_active and abs(lid.bounds().left() - 35) < 1e-6)
items_before = list(w.canvas._preview_items)
w.build_job(show=True)
check("anteprima del piano 2 durante il lavoro: sulla tela resta il percorso del lavoro in corso",
      items_before and w.canvas._preview_items == items_before)
if UI == "banco":
    check("Banco: sul piano 2 la cabina lascia disegnare (strumenti in vista, Pausa/Stop restano)",
          not w.banco.locked() and w.banco.rail.isVisible() and w.banco.cockpit.bottom.isVisible()
          and not w.banco.cockpit.side.isVisible())
    bar.tabs.setCurrentIndex(0)
    app.processEvents()
    check("Banco: sul piano in incisione la cabina come prima", w.banco.locked() and not w.banco.rail.isVisible()
          and w.banco.cockpit.side.isVisible())
    bar.tabs.setCurrentIndex(1)
    app.processEvents()
told = []
QMessageBox.information = lambda *a, **k: told.append(a[2] if len(a) > 2 else "")
r = bar.delete(0)
w.ctl.sim.speedup = 300
check("il piano in incisione non si elimina (lo dice)", told and "in incisione" in told[0] and not r
      and len(w.editor.doc.plates) == 2)
ok = until(lambda: not w.ctl.job_active, 120)
from freelasercut.grbl import _clean_lines

check("il lavoro finisce e manda esattamente il piano 1 preparato prima (le modifiche al piano 2 non lo toccano)",
      ok and sent == list(w.ctl.job_lines) and len(sent) > 50 and sent == _clean_lines(plan1)[:len(sent)]
      and w.ctl.job_acked == len(sent), (len(sent), len(_clean_lines(plan1)), w.ctl.job_acked))
app.processEvents()
check("finito: niente più ▶", "▶" not in bar.tabs.tabText(0) and "in incisione" not in bar.tabs.tabToolTip(0))
job2 = w.build_job(show=False)
b2 = job2.bounds
check("il lavoro del piano 2 contiene solo il piano 2", abs(b2.width() - 50) < 0.6 and abs(b2.height() - 40) < 0.6,
      (b2.width(), b2.height()))
# con «Verifica e avvia» (la scheda controlla il lavoro, poi parte): il piano in incisione resta noto
w.laser.verify_first.setChecked(True)
w.ctl.sim.speedup = 1
w.start_job()
check("lavoro avviato dopo la verifica: ▶ sul piano giusto", until(lambda: w.ctl.job_active, 20)
      and w._job_plate == w.editor.doc.plates[1].uid, w._job_plate)
w.ctl.stop_job()
until(lambda: not w.ctl.job_active, 10)
w.ctl.disconnect_port()

# ---- gli strumenti lavorano sul piano attivo (e non toccano gli altri)
from PySide6.QtWidgets import QDialog

from freelasercut.core.document import GroupShape
from freelasercut.ui import dialogs_puzzle as DP, dialogs_sculpt as DS
from freelasercut.ui.dialogs_nest import NestDialog

ed = w.editor
ed.set_plate(0)
p1_before = json.dumps([s.to_dict() for s in ed.doc.plates[0].shapes], sort_keys=True)
used1 = ed.doc.used_layer_indices()
ed.add_plate()
for k in ("nest_multi", "nest_common"):
    w.qs.setValue(k, False)
parts = [rect(15 * i, 10 * i, 60, 40, layer=2) for i in range(6)]
ed.add(parts, select=False)
dlg = NestDialog(w)
res = dlg.run()
check("Ottimizza lo spazio sul piano 2: solo i suoi pezzi, il piano 1 non conta come ostacolo",
      len(dlg.parts) == 6 and len(res.placements) == 6)
dlg.close()
ed.doc.images["foto"] = Image.new("L", (80, 60), 120)
ph = ImageShape("foto", 100, 75, layer=0)
ph.apply(QTransform.fromTranslate(200, 250))
ed.doc.layer(0).mode = "image"
ed.add([ph])
ed.select([ph])
orig_px = DP.PuzzleDialog.exec
DP.PuzzleDialog.exec = lambda self: QDialog.Accepted
grp = w.puzzle_dialog()
DP.PuzzleDialog.exec = orig_px
cut = [k for k in (grp.children if isinstance(grp, GroupShape) else []) if not isinstance(k, ImageShape)]
check("Puzzle sul piano 2: resta sul piano 2, i tagli su un livello non usato da nessun piano",
      grp in ed.doc.shapes and cut and all(c.layer not in used1 for c in cut), [c.layer for c in cut])
orig_sx = DS.SculptDialog.exec


def small_exec(self):
    self.height_mm.setValue(40.0)
    self._rebuild()
    return QDialog.Accepted


DS.SculptDialog.exec = small_exec
n0 = len(ed.doc.shapes)
g = w.sculpt_dialog()
DS.SculptDialog.exec = orig_sx
check("Scultura sul piano 2: i pezzi vanno sul piano 2", g and len(ed.doc.shapes) > n0 and ed.doc.current == 2,
      (len(ed.doc.shapes), n0))
check("il piano 1 non è cambiato con tutti questi strumenti",
      json.dumps([s.to_dict() for s in ed.doc.plates[0].shapes], sort_keys=True) == p1_before)
while len(ed.doc.plates) > 2:
    ed.remove_plate(len(ed.doc.plates) - 1)
ed.set_plate(1)

# ---- livelli in comune: codici, import .lbrn2, numeri di serie, MCP, riavvio dopo G55, menu Sposta
from freelasercut.core import lbrn, variables

ed.set_plate(0)
ed.add([rect(5, 380, 20, 10, layer=1)])  # piano 1: taglio sul livello 1 (Linea)
ed.doc.layer(1).mode = "line"
ed.set_plate(1)
ed.current_layer = 1
li, setup = w._fill_layer()
check("codice QR sul piano 2: non trasforma in riempimento un livello usato dal piano 1", li != 1
      and li not in ed.doc.used_layer_indices(), li)
ed.doc.layer(1).speed = 777.0
LB = os.path.join(D, "imp.lbrn2")
with open(LB, "w", encoding="utf-8") as fh:
    fh.write("""<?xml version="1.0" encoding="UTF-8"?><LightBurnProject AppVersion="2.1" FormatVersion="1">
<CutSetting type="Scan"><index Value="1"/><name Value="C01"/><maxPower Value="35"/><speed Value="120"/></CutSetting>
<Shape Type="Rect" CutIndex="1" W="40" H="20" Cr="0"><XForm>1 0 0 1 100 50</XForm></Shape></LightBurnProject>""")
lbrn.import_shapes(LB, ed.doc)
check("importa un .lbrn2 sul piano 2: il livello usato dal piano 1 tiene le sue impostazioni",
      ed.doc.layer(1).speed == 777.0 and ed.doc.layer(1).mode == "line")
tv = TextShape("N{n}", size=8, layer=1)
tv.apply(QTransform.fromTranslate(300, 380))
ed.set_plate(0)
ed.add([tv])
variables.STATE.update(auto=True, serial=5)
w._job_is_external = False
uid1 = ed.doc.plates[0].uid
ed.set_plate(1)
w._advance_variables(uid1)
check("fine lavoro del piano 1 mentre si prepara il piano 2: i numeri di serie avanzano con il piano 1",
      variables.STATE["serial"] > 5, variables.STATE["serial"])
from freelasercut.remote import RemoteError, RemoteServer

rs = RemoteServer.__new__(RemoteServer)
rs.win = w
ed.add_plate()
ed.dirty = True
try:
    rs.c_new_project()
    refused = False
except RemoteError:
    refused = True
check("Claude (MCP) «nuovo progetto» con un piano vuoto attivo ma lavoro sugli altri: non butta via niente", refused
      and len(ed.doc.plates) == 3)
ed.remove_plate(2)
msgs2 = []
w.statusBar().messageChanged.connect(msgs2.append)
w._start_ctx = (uid1, ())
w._pending_start = None
w._reverify(True)
check("verifica con G55 da rifare dopo aver cambiato piano: il lavoro non riparte da solo, lo dice",
      w._pending_start is None and any("G55" in m for m in msgs2))
names = [a.text() for a in w.m_plate_move.actions() if a.text()]
check("menu «Sposta la selezione su un altro piano» aggiornato anche senza aprirlo (ricerca comandi del Banco)",
      "Piano 1" in names and "Su un piano nuovo" in names, names)

# ---- salva e riapri dalla finestra
w.editor.rename_plate(1, "Coperchio")
n_p1 = len(w.editor.doc.plates[0].shapes)
fp2 = os.path.join(D, "finestra.flcut")
w.editor.doc.save(fp2)
w.editor.dirty = False
w.file_open(fp2)
app.processEvents()
check("riaperto: due schede con i nomi, piano attivo come al salvataggio", bar.tabs.count() == 2
      and bar.tabs.tabText(1) == "Coperchio" and w.editor.doc.current == 1
      and len(w.editor.doc.plates[0].shapes) == n_p1 > 0)
w.file_new() if hasattr(w, "file_new") else None
app.processEvents()
check("nuovo progetto: di nuovo un piano solo", bar.tabs.count() == 1 and len(w.editor.doc.plates) == 1)
# il menu «Sposta la selezione su un altro piano»
w.editor.add([rect(1, 1)])
w.editor.select_all()
w.plate_bar.move_menu(w.m_plate_move)
acts = [a.text() for a in w.m_plate_move.actions() if a.text()]
check("menu Sposta: con un piano solo propone «Su un piano nuovo»", acts == ["Su un piano nuovo"], acts)
w.m_plate_move.actions()[-1].trigger()
check("«Su un piano nuovo»: crea il piano 2, ci sposta gli oggetti e ci va", len(w.editor.doc.plates) == 2
      and w.editor.doc.current == 1 and len(w.editor.doc.shapes) == 1 and not w.editor.doc.plates[0].shapes)

# ---- scorciatoie, rotella, tante linguette, piano scuro, autosalvataggio, MCP
from collections import defaultdict

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QAction, QWheelEvent

sc = defaultdict(list)
for a in w.findChildren(QAction):
    for k in a.shortcuts():
        if not k.isEmpty():
            sc[k.toString()].append(a.text())
dups = {k: v for k, v in sc.items() if len(v) > 1}
check("nessuna scorciatoia doppia (Ctrl+Maiusc+N nuovo piano; Ctrl+Alt+N resta alla forma con misure esatte)",
      not dups and w.acts["plate_new"].shortcut().toString() == "Ctrl+Shift+N", dups)
cur = w.editor.doc.current
ev = QWheelEvent(QPointF(5, 5), QPointF(bar.tabs.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                 Qt.NoModifier, Qt.NoScrollPhase, False)
QApplication.sendEvent(bar.tabs, ev)
check("rotella sopra le linguette: il piano non cambia", w.editor.doc.current == cur)
for k in range(12):
    w.editor.add_plate()
    w.editor.rename_plate(w.editor.doc.current, f"Piano con un nome lungo {k}")
w.canvas.viewport().repaint()
until(lambda: False, 0.3)
vpw = w.canvas.viewport().width()
check("14 piani con nomi lunghi: le linguette restano dentro la vista (con le frecce)", bar.geometry().right() <= vpw
      and bar.geometry().left() >= 0, (bar.geometry().left(), bar.geometry().right(), vpw))
from freelasercut.ui.canvas import BED_DARK

w.canvas.light_bed = False
w.canvas.viewport().repaint()
until(lambda: False, 0.3)
check("piano scuro: le linguette prendono i colori del piano scuro", BED_DARK["bed"].lower() in bar.styleSheet().lower())
w.canvas.light_bed = True
w.canvas.viewport().repaint()
until(lambda: False, 0.2)
from freelasercut.profile import config_dir

w.editor.dirty = True
w.autosave()
ad = Document.load(os.path.join(config_dir(), "autosave.flcut"))
check("autosalvataggio: tutti i piani", len(ad.plates) == len(w.editor.doc.plates) == 14
      and ad.plate_name(13) == "Piano con un nome lungo 11")
from freelasercut.remote import RemoteServer

rs = RemoteServer.__new__(RemoteServer)
rs.win = w
st = rs.c_status()
check("collegamento con Claude (MCP): lo stato dice il piano attivo e l'elenco dei piani",
      st["plate"] == w.editor.doc.plate_name(w.editor.doc.current) and len(st["plates"]) == 14)
# ---- con il mouse vero sulle linguette: clic, doppio clic (rinomina), tasto destro (menu)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog, QMenu

while len(w.editor.doc.plates) > 2:
    w.editor.remove_plate(len(w.editor.doc.plates) - 1)
w.editor.set_plate(1)
app.processEvents()
QTest.mouseClick(bar.tabs, Qt.LeftButton, Qt.NoModifier, bar.tabs.tabRect(0).center())
app.processEvents()
check("clic sulla prima linguetta: piano 1", w.editor.doc.current == 0)
orig_gt = QInputDialog.getText
QInputDialog.getText = staticmethod(lambda *a, **k: ("Fondo", True))
QTest.mouseDClick(bar.tabs, Qt.LeftButton, Qt.NoModifier, bar.tabs.tabRect(1).center())
app.processEvents()
QInputDialog.getText = orig_gt
check("doppio clic su una linguetta: rinomina", w.editor.doc.plate_name(1) == "Fondo" and bar.tabs.tabText(1) == "Fondo")
shown = []
orig_popup = QMenu.popup
QMenu.popup = lambda self, *a: shown.append([x.text() for x in self.actions() if x.text()])
w.editor.select(list(w.editor.doc.shapes))
bar.tabs.customContextMenuRequested.emit(bar.tabs.tabRect(1).center())
QMenu.popup = orig_popup
check("tasto destro su un'altra linguetta: sposta qui la selezione, rinomina, duplica, elimina, nuovo",
      shown and shown[0][0].startswith("Sposta qui gli oggetti selezionati") and "Duplica il piano" in shown[0]
      and "Elimina il piano…" in shown[0] and "Nuovo piano di lavoro" in shown[0], shown)
QTest.mouseClick(bar.add_btn, Qt.LeftButton)
check("clic su +: nuovo piano", len(w.editor.doc.plates) == 3 and w.editor.doc.current == 2)

# ---- vista d'insieme: tutti i piani affiancati, in ordine
ov = w.plate_overview
w.editor.add([rect(100, 100, 80, 50)])
w.editor.select(list(w.editor.doc.shapes))
check("vista d'insieme: pulsante accanto alle linguette (con più piani)", bar.overview.isVisible()
      and w.acts["plate_overview"].isEnabled())
w.acts["plate_overview"].trigger()
app.processEvents()
rs3 = [ov.plate_rect(i) for i in range(3)]
check("si apre: i 3 piani affiancati in ordine, tutti dentro la vista, senza selezione rimasta",
      ov.isVisible() and bar.overview.isChecked() and rs3[0].right() < rs3[1].left() and rs3[1].right() < rs3[2].left()
      and all(QRectF(ov.rect()).contains(r) for r in rs3) and not w.editor.selection,
      [(round(r.left()), round(r.right())) for r in rs3])
k0 = ov._k
QApplication.sendEvent(ov, QWheelEvent(rs3[1].center(), QPointF(ov.mapToGlobal(rs3[1].center().toPoint())), QPoint(0, 0),
                                       QPoint(0, 120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
check("rotella: zoom nella vista d'insieme", ov._k > k0)
QTest.mouseDClick(ov, Qt.LeftButton, Qt.NoModifier, QPoint(3, ov.height() - 3))
check("doppio clic sul vuoto: di nuovo tutti in vista", abs(ov._k - k0) < 1e-9)
QTest.mouseClick(ov, Qt.LeftButton, Qt.NoModifier, ov.plate_rect(0).center().toPoint())
app.processEvents()
check("clic su un piano: si apre quello per modificarlo e la vista d'insieme si chiude", w.editor.doc.current == 0
      and not ov.isVisible() and not bar.overview.isChecked() and not w.acts["plate_overview"].isChecked())
bar.overview.click()
app.processEvents()
QTest.keyClick(ov, Qt.Key_Escape)
check("Esc chiude la vista d'insieme", not ov.isVisible() and not bar.overview.isChecked())
img = ov.grab()
check("la vista d'insieme si disegna senza errori", not img.isNull())

# ---- vista d'insieme: i tasti di modifica non toccano la tela sotto; doppio clic; piani aggiunti; un piano solo
from PySide6.QtGui import QKeyEvent

w.editor.set_plate(0)
w.editor.add([rect(30, 30, 40, 40)])
n_here = len(w.editor.doc.shapes)
bar.overview.click()
app.processEvents()
QTest.keyClick(ov, Qt.Key_A, Qt.ControlModifier)
QTest.keyClick(ov, Qt.Key_Delete)
QTest.keyClick(ov, Qt.Key_Left)
check("vista d'insieme aperta: Ctrl+A, Canc e frecce non toccano gli oggetti nascosti", not w.editor.selection
      and len(w.editor.doc.shapes) == n_here and ov.isVisible())
so = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Space, Qt.ControlModifier)
so.setAccepted(False)
ov.event(so)
sd = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Delete, Qt.NoModifier)
sd.setAccepted(False)
ov.event(sd)
check("…mentre Pausa (Ctrl+Spazio), Stop e gli altri comandi del laser restano attivi", not so.isAccepted()
      and sd.isAccepted())
w.editor.add_plate()
w.editor.set_plate(0)
ov.repaint()
check("piano aggiunto con la vista aperta: si ridispone e tutti restano in vista",
      all(QRectF(ov.rect()).contains(ov.plate_rect(i)) for i in range(len(w.editor.doc.plates))))
c0 = ov.plate_rect(0).center().toPoint()
QTest.mouseDClick(ov, Qt.LeftButton, Qt.NoModifier, c0)
QTest.mouseClick(w.canvas.viewport(), Qt.LeftButton, Qt.NoModifier, c0)  # il secondo clic di un doppio clic
app.processEvents()
check("doppio clic su un piano: si apre, e il secondo clic non seleziona niente sotto", not ov.isVisible()
      and w.editor.doc.current == 0 and not w.editor.selection)
while len(w.editor.doc.plates) > 2:
    w.editor.remove_plate(len(w.editor.doc.plates) - 1)
bar.overview.click()
w.editor.remove_plate(1)
QTest.keyClick(ov, Qt.Key_Escape)
check("rimasto un piano solo: la vista d'insieme si chiude e il comando si spegne", not ov.isVisible()
      and not w.acts["plate_overview"].isEnabled() and not bar.overview.isVisible())
w.editor.add_plate()

# ---- progetti enormi (foto vettorializzate): il grigio degli altri piani e la vista d'insieme restano veloci
from PySide6.QtGui import QPainterPath

from freelasercut.core.document import PathShape

hp = QPainterPath()
for k_ in range(120000):
    hp.lineTo(200 + (k_ % 400) * 0.5, 100 + (k_ // 400) * 0.6)
w.editor.set_plate(0)
w.editor.add([PathShape(hp, 2)])
w.editor.set_plate(1)
gp = w.canvas.ghost_path()
check("grigio di un piano con 120.000 punti: semplificato per disegnarlo in fretta", gp is not None
      and gp.elementCount() <= 80000, gp.elementCount() if gp is not None else None)
t0 = time.time()
for _ in range(3):
    w.canvas.translate(5, 0)
    w.canvas.viewport().repaint()
check("spostando la vista sul piano 2 non si rallenta", (time.time() - t0) / 3 < 1.0, round((time.time() - t0) / 3, 3))
bar.overview.click()
app.processEvents()
ov.repaint()
keys = {u: v[0] for u, v in ov._pix.items()}
t0 = time.time()
for _ in range(5):
    ov.repaint()
check("vista d'insieme: i piani disegnati una volta e riusati (avanzamento e spostamenti veloci)",
      {u: v[0] for u, v in ov._pix.items()} == keys and (time.time() - t0) / 5 < 0.2, round((time.time() - t0) / 5, 3))
QTest.keyClick(ov, Qt.Key_Escape)
w.editor.dirty = False
w.close()

print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.stdout.flush()
os._exit(0 if all(results) else 1)  # il simulatore della scheda gira in un altro thread: uscita senza attese
