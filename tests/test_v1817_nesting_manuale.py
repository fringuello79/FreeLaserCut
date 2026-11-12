# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.17: correzioni al nesting manuale chieste da Ale.

1. Si dispongono SOLO i pezzi selezionati prima di scegliere il comando (una foto di riferimento sotto, non
   selezionata, non si tocca). Senza selezione il comando non parte.
2. Finito il nesting il contorno dell'area sparisce (il comando ha finito il suo ciclo); resta sul livello T1 solo con
   la spunta «Lascia sul piano l'area disegnata…», spenta di regola.
3. Le forme che stanno sotto l'area o a cavallo del tracciato non contano: i pezzi selezionati vanno nell'area lo
   stesso.

Il dato: un comando = (pezzi selezionati all'inizio, altre forme sul piano, area disegnata, spunta) e finisce in uno di
questi modi: pezzi sistemati; l'area non basta + nuova area; l'area non basta + annulla; finestra chiusa senza
disporre; disegno annullato. In tutti i casi: gli altri oggetti non si muovono, e Ctrl+Z è un passo solo (o nessuno,
se non è cambiato niente).
"""
import ast
import json
import os
import re
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
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import ImageShape, RectShape  # noqa: E402
from freelasercut.ui import nest_manual  # noqa: E402
from freelasercut.ui.dialogs_nest import NestDialog  # noqa: E402
from freelasercut.ui.editor import TOOL_LAYER  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas
AREA = [(40, 40), (200, 40), (170, 130), (70, 130)]  # il trapezio avanzato


def rect(x, y, wd=20, h=12, cls=RectShape):
    s = cls(wd, h) if cls is RectShape else cls(None, wd, h)
    s.apply(QTransform.fromTranslate(x, y))
    return s


def pos(shapes):
    return [tuple(round(v, 3) for v in s.bounds().center().toTuple()) for s in shapes]


def inside(shape, poly=AREA, tol=0.05):
    area = QPainterPath()
    area.moveTo(*poly[0])
    for p in poly[1:]:
        area.lineTo(*p)
    area.closeSubpath()
    b = shape.bounds().adjusted(tol, tol, -tol, -tol)
    return all(area.contains(c) for c in (b.topLeft(), b.topRight(), b.bottomLeft(), b.bottomRight()))


def tool_shapes():
    return [s for s in ed.doc.shapes if s.layer == TOOL_LAYER]


def scene():
    """Sei pezzi fuori dall'area; sotto l'area una foto di riferimento e un rettangolo grande quanto l'area, uno a
    cavallo del tracciato, uno dentro: nessuno di questi quattro è selezionato."""
    ed.doc.shapes.clear()
    ed.selection = []
    ed.undo_stack.clear()
    ed.redo_stack.clear()
    parts = [rect(300 + (i % 3) * 30, 250 + (i // 3) * 25) for i in range(6)]
    photo = rect(20, 20, 220, 140, ImageShape)  # la foto di riferimento, sotto tutta l'area
    under = rect(30, 30, 190, 110)  # una forma che copre tutta l'area
    across = rect(50, 45, 140, 80)  # a cavallo del tracciato: da sola occupa quasi tutta l'area
    within = rect(100, 70, 30, 20)  # tutta dentro l'area
    others = [photo, under, across, within]
    ed.add(others + parts, select=False)
    ed.select([])
    return parts, others


def draw(points=AREA):
    """Disegna l'area con il comando vero e la chiude. -> la finestra «Ottimizza lo spazio» del nesting manuale."""
    panel = w.nest_dialog(mode="manual")
    if panel is None:
        return None
    for x, y in points:
        panel.add_point(x, y)
    return w._nest_manual_dlg if panel.finish() else None


# ================================================================== 1. solo i pezzi selezionati
parts, others = scene()
n0 = len(ed.doc.shapes)
check("senza niente di selezionato il nesting manuale non parte: nessuna finestrella, niente cambia",
      w.nest_dialog(mode="manual") is None and getattr(w, "_nest_panel", None) is None and len(ed.doc.shapes) == n0
      and cv.tool is cv.tools["select"])
check("…e la barra dice che cosa fare (selezionare prima i pezzi)", "seleziona prima" in w.statusBar().currentMessage().lower(),
      w.statusBar().currentMessage())
locked, hidden = rect(400, 100), rect(400, 130)
locked.locked, hidden.hidden = True, True
tool_s = rect(400, 160)
tool_s.layer = TOOL_LAYER
ed.add([locked, hidden, tool_s], select=False)
ed.select([locked, hidden, tool_s])
check("…lo stesso se sono selezionate solo forme bloccate, nascoste o del livello T1",
      nest_manual.selected_parts(ed) == [] and w.nest_dialog(mode="manual") is None)
ed.doc.remove([locked, hidden, tool_s])

chosen = parts[:4]
orig = {s.id: c for s, c in zip(chosen, pos(chosen))}
ed.select(chosen + [locked])
before_others, before_rest = pos(others), pos(parts[4:])
u0 = len(ed.undo_stack)
panel = w.nest_dialog(mode="manual")
check("con 4 pezzi selezionati parte, e i pezzi del comando sono quei 4 (non le forme bloccate)",
      panel is not None and panel.parts == chosen)
ed.select([parts[5]])  # la selezione cambia mentre si disegna: contano i pezzi scelti prima
for x, y in AREA:
    panel.add_point(x, y)
check("area chiusa", panel.finish() is True)
dlg = w._nest_manual_dlg
area = dlg.manual
check("«Ottimizza lo spazio» lavora sui 4 pezzi selezionati prima di scegliere il comando, anche se nel frattempo la "
      "selezione è cambiata", dlg.parts == chosen and dlg.sheet is area, [s.id for s in dlg.parts])
check("…lo dice («le 4 forme che avevi selezionato», il resto non conta)", "4" in dlg.what.text() and "non" in dlg.what.text()
      and "selezionat" in dlg.what.text(), dlg.what.text())
check("…con la spunta «Lascia sul piano l'area disegnata» visibile e spenta di regola",
      not dlg.keep_area.isHidden() and not dlg.keep_area.isChecked())
res = dlg.run()
check("i 4 pezzi selezionati finiscono tutti dentro l'area, anche se sotto c'è una forma che la copre tutta, una foto, "
      "una forma a cavallo del tracciato e una dentro", res is not None and all(inside(s) for s in chosen), pos(chosen))
check("…senza sovrapporsi fra loro", not any(a.bounds().adjusted(0.05, 0.05, -0.05, -0.05).intersects(b.bounds())
                                             for i, a in enumerate(chosen) for b in chosen[i + 1:]))
check("la foto di riferimento e le altre forme non selezionate restano esattamente dov'erano",
      pos(others) == before_others and pos(parts[4:]) == before_rest, (pos(others), before_others))

# ================================================================== 2. il contorno sparisce, un solo Ctrl+Z
check("a nesting fatto il contorno dell'area non è più sul piano", area not in ed.doc.shapes and not tool_shapes())
first = pos(chosen)
res2 = dlg.run()
check("la finestra è ancora aperta: «Disponi» di nuovo lavora sulla stessa area", res2 is not None
      and all(inside(s) for s in chosen) and not tool_shapes())
dlg.accept()
check("chiusa la finestra: tutto il comando è un solo passo nella cronologia", len(ed.undo_stack) == u0 + 1
      and ed.undo_label() == "Nesting manuale", (len(ed.undo_stack), u0, ed.undo_label()))
ed.undo()
now = {s.id: c for s in ed.doc.shapes if s.id in orig for c in pos([s])}
check("un solo Ctrl+Z riporta i pezzi dov'erano, senza far ricomparire il contorno",
      now == orig and not tool_shapes() and len(ed.undo_stack) == u0, (now, orig))
check("…e riseleziona i pezzi di prima", sorted(s.id for s in ed.selection) == sorted(p.id for p in chosen))
ed.redo()
back = [s for s in ed.doc.shapes if s.id in {p.id for p in chosen}]
check("Ripeti: di nuovo dentro l'area, sempre senza contorno", all(inside(s) for s in back) and not tool_shapes()
      and len(back) == 4)
job = gcode.generate(ed.doc, w.profile)
check("nel lavoro non c'è traccia dell'area", all(st.index != TOOL_LAYER for st in job.layers))

# ---- con la spunta: resta come riferimento
parts, others = scene()
ed.select(parts)
u0 = len(ed.undo_stack)
dlg = draw()
dlg.keep_area.setChecked(True)
dlg.run()
check("con la spunta il contorno resta sul livello T1 dopo il nesting", dlg.manual in ed.doc.shapes and len(tool_shapes()) == 1
      and all(inside(s) for s in parts))
dlg.accept()
check("…anche a finestra chiusa, sempre con un solo passo di Ctrl+Z", dlg.manual in ed.doc.shapes
      and len(ed.undo_stack) == u0 + 1)
check("…e non viene inciso", all(st.index != TOOL_LAYER for st in gcode.generate(ed.doc, w.profile).layers))
check("la scelta viene ricordata", w.qs.value("nest_keep_area") in (True, "true"))
ed.undo()
check("Ctrl+Z toglie insieme pezzi sistemati e contorno", not tool_shapes() and len(ed.undo_stack) == u0)
ed.select([s for s in ed.doc.shapes if s.layer != TOOL_LAYER and not isinstance(s, ImageShape)][-6:])
dlg = draw()
check("al nesting manuale successivo la spunta è come l'hai lasciata", dlg.keep_area.isChecked())
dlg.keep_area.setChecked(False)
dlg.run()
check("tolta la spunta: il contorno sparisce di nuovo", not tool_shapes())
dlg.keep_area.setChecked(True)
dlg.accept()
check("spunta rimessa prima di chiudere: il contorno torna sul piano (vale la scelta fatta alla chiusura)",
      len(tool_shapes()) == 1)
dlg2 = NestDialog(w)
check("nel nesting automatico la spunta non c'è", dlg2.keep_area.isHidden() and not dlg2.keep_area.isChecked())
w.qs.setValue("nest_keep_area", False)
ed.select([s for s in ed.doc.shapes if s.layer != TOOL_LAYER and not isinstance(s, ImageShape)][-6:])
dlg = draw()
dlg.keep_area.setChecked(True)
dlg.reject()
check("la spunta viene ricordata anche se si chiude senza disporre (e allora il contorno resta)",
      w.qs.value("nest_keep_area") in (True, "true") and dlg.manual in ed.doc.shapes)
w.qs.setValue("nest_keep_area", False)

# ================================================================== finali senza nesting
parts, others = scene()
ed.select(parts[:3])
u0 = len(ed.undo_stack)
before_all = pos(ed.doc.shapes)
dlg = draw()
check("(area disegnata: contorno sul piano mentre la finestra è aperta)", len(tool_shapes()) == 1)
dlg.reject()
check("finestra chiusa senza disporre: il contorno sparisce, niente si è mosso, nessun passo nella cronologia",
      not tool_shapes() and pos(ed.doc.shapes) == before_all and len(ed.undo_stack) == u0, len(ed.undo_stack) - u0)
check("…e la selezione è quella di prima del comando", ed.selection == parts[:3])

big = [rect(300 + i * 5, 300, 60, 50) for i in range(5)]  # 5 pezzi da 60 × 50: nel triangolino non entrano
ed.add(big, select=False)
ed.select(big)
u0 = len(ed.undo_stack)
before_all = pos(ed.doc.shapes)
dlg = draw([(40, 40), (110, 40), (75, 90)])
r = dlg.run()
dlg.reject()  # 0.19.0: la scelta si fa nella stessa finestra
check("l'area non basta + «Annulla»: niente spostato, contorno sparito, nessun passo nella cronologia",
      r is None and not dlg.again and not tool_shapes() and pos(ed.doc.shapes) == before_all and len(ed.undo_stack) == u0)
check("…i pezzi restano selezionati", ed.selection == big)
dlg = draw([(40, 40), (110, 40), (75, 90)])
r = dlg.run()
dlg.redraw()
check("l'area non basta + «Ridisegna l'area»: contorno sparito, nessun passo nella cronologia, stessi pezzi",
      r is None and dlg.again and not tool_shapes() and len(ed.undo_stack) == u0 and dlg.parts == big)
panel = w._nest_panel
check("la nuova area si disegna con gli stessi pezzi", panel is not None and panel.parts == big and panel.step == 1)
panel.cancel()
check("disegno annullato: niente cambia", not tool_shapes() and pos(ed.doc.shapes) == before_all and len(ed.undo_stack) == u0)
ed.doc.remove([big[0]])
ed.select(big)
dlg = draw([(20, 20), (420, 20), (420, 300), (20, 300)])
check("un pezzo eliminato nel frattempo non fa inciampare: restano gli altri", dlg is not None and dlg.parts == big[1:])
dlg.reject()

# ================================================================== 3. il nesting automatico evita ancora gli ostacoli
parts, others = scene()
from freelasercut.core.document import PathShape  # noqa: E402

trap = QPainterPath()
trap.moveTo(*AREA[0])
for q in AREA[1:]:
    trap.lineTo(*q)
trap.closeSubpath()
mat = PathShape(trap, layer=TOOL_LAYER)  # la stessa area, ma disegnata a mano sul livello T1 e usata in automatico
ed.add([mat], select=False)
ed.select([mat] + parts[:4])
before4, before_others = pos(parts[:4]), pos(others)
auto = NestDialog(w)
auto.run()
left = [s for s in parts[:4] if s in ed.selection]
check("nesting automatico invariato: le forme non selezionate sono ostacoli (nella stessa area, occupata da una forma "
      "a cavallo, i pezzi non entrano e restano dov'erano)", auto.manual is None and auto.area.currentData() == "sheet"
      and len(left) == 4 and pos(parts[:4]) == before4 and pos(others) == before_others, (len(left), pos(parts[:4])))
auto.accept()
check("…e la forma del materiale disegnata a mano resta sul piano (non è un'area del nesting manuale)", mat in ed.doc.shapes)
sheet = rect(250, 20, 150, 100)
sheet.layer = TOOL_LAYER
ed.add([sheet], select=False)
ed.select([sheet] + parts[:4])
auto = NestDialog(w)
auto.run()
auto.accept()
check("nesting automatico su una forma del livello T1 scelta da te: i pezzi ci entrano e la forma resta dov'è",
      sheet in ed.doc.shapes and all(sheet.bounds().contains(s.bounds().center()) for s in parts[:4]))

# ================================================================== storia riunita: casi limite
parts, others = scene()
ed.select(parts)
dlg = draw()
ed.undo_stack.clear()  # la cronologia è stata svuotata nel frattempo: il passo dell'area non c'è più
dlg.run()
dlg.accept()
check("se il passo dell'area non è più nella cronologia non si inciampa: i passi restano come sono",
      not tool_shapes() and all(inside(s) for s in parts) and len(ed.undo_stack) >= 1)
check("collapse_history: senza il passo di partenza non tocca niente", nest_manual.collapse_history(ed, ("x",), "y") is False)

# ================================================================== traduzioni dei testi nuovi
keys = set()
for name in ("nest_manual.py", "dialogs_nest.py", "main_window.py"):
    src = open(os.path.join(ROOT, "freelasercut", "ui", name), encoding="utf-8").read()
    for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', src):
        try:
            k = "".join(ast.literal_eval(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
        except (SyntaxError, ValueError):
            continue
        if any(t in k for t in ("seleziona prima", "Seleziona prima", "avevi selezionato", "Lascia sul piano l'area",
                                "il contorno dell'area sparisce", "selezionato prima")):
            keys.add(k)
check("i testi nuovi del nesting manuale sono nel codice (6)", len(keys) == 6, sorted(k[:40] for k in keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k[:40] for k in keys if not loc.get(k)]
    bad = [k[:40] for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    check(f"traduzioni {lang}: tutti i testi nuovi, con gli stessi segnaposto", not miss and not bad, (miss, bad))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
