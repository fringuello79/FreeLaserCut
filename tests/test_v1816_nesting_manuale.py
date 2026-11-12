# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.16: nesting manuale (richiesta di Ale): i pezzi dentro un'area disegnata sul piano punto per punto, per
sfruttare un avanzo di forma irregolare (un trapezio di legno rimasto).

Casi: scelta automatico / manuale; clic = punto, clic su un punto = lo toglie, clic sul primo = chiude, Invio,
Backspace, Esc; area troppo piccola o che si incrocia; l'area diventa una forma del livello T1 (mai incisa); i pezzi
finiscono TUTTI dentro il trapezio; se non entrano non si sposta niente e si sceglie fra nuova area e annulla; con la
spunta il laser acceso al minimo va su ogni punto (simulatore), nei limiti della Lucciola; rifiuti senza laser, senza
homing, fuori dal piano; il nesting automatico resta com'era; traduzioni.
"""
import ast
import json
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui import nest_manual  # noqa: E402
from freelasercut.ui.editor import TOOL_LAYER  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


# ================================================================== calcoli
check("area di un trapezio", abs(nest_manual.polygon_area([(0, 0), (100, 0), (80, 50), (20, 50)]) - 4000) < 1e-9)
check("contorno che si incrocia: riconosciuto; trapezio e forma a L no",
      nest_manual.self_crossing([(0, 0), (50, 50), (50, 0), (0, 50)])
      and not nest_manual.self_crossing([(0, 0), (100, 0), (80, 50), (20, 50)])
      and not nest_manual.self_crossing([(0, 0), (60, 0), (60, 20), (20, 20), (20, 60), (0, 60)]))

w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas
vp = cv.viewport()


def click(bed):
    v = cv.to_view(QPointF(*bed))
    for kind, btns in ((QEvent.MouseButtonPress, Qt.LeftButton), (QEvent.MouseButtonRelease, Qt.NoButton)):
        QApplication.sendEvent(vp, QMouseEvent(kind, v, QPointF(vp.mapToGlobal(v.toPoint())), Qt.LeftButton, btns, Qt.AltModifier))
    app.processEvents()


def key(k):
    QApplication.sendEvent(cv, QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))
    app.processEvents()


def pieces(n, wd=20, h=12):
    out = []
    for i in range(n):
        s = RectShape(wd, h)
        s.apply(QTransform.fromTranslate(300 + (i % 4) * 30, 250 + (i // 4) * 25))
        out.append(s)
    ed.add(out, select=False)
    ed.select([])
    return out


def inside(shape, poly_pts, tol=0.05):
    """Tutta la forma sta dentro il poligono?"""
    area = QPainterPath()
    area.moveTo(*poly_pts[0])
    for p in poly_pts[1:]:
        area.lineTo(*p)
    area.closeSubpath()
    b = shape.bounds().adjusted(tol, tol, -tol, -tol)
    return all(area.contains(c) for c in (b.topLeft(), b.topRight(), b.bottomLeft(), b.bottomRight()))


TRAP = [(40, 40), (200, 40), (170, 130), (70, 130)]  # il trapezio avanzato

# ================================================================== scelta e disegno
parts = pieces(6)
orig = [s.bounds().center().toTuple() for s in parts]
check("senza domande (prove): la scelta è «automatico»", nest_manual.choose_mode(w) == "auto")
panel = w.nest_dialog(mode="manual")
check("nesting manuale: compare la finestrella con le istruzioni e la spunta del laser",
      panel is not None and panel.isVisible() and "bordo" in panel.findChildren(type(panel.info))[0].text()
      and not panel.laser.isChecked() and not panel.b_done.isEnabled() and cv.tool is panel.tool)
check("una seconda richiesta non ne apre un'altra", w.nest_dialog(mode="manual") is panel)
for p in TRAP[:3]:
    click(p)
check("tre clic: tre punti, e ora l'area si può chiudere", len(panel.tool.pts) == 3 and panel.b_done.isEnabled()
      and all(abs(a - b) < 0.3 for q, t in zip(panel.tool.pts, TRAP) for a, b in zip(q, t)), panel.tool.pts)
click((150, 180))  # punto sbagliato
check("quarto punto messo nel posto sbagliato", len(panel.tool.pts) == 4)
click((150, 180))
check("clic sullo stesso punto: lo toglie", len(panel.tool.pts) == 3 and "tolto" in panel.info.text(), panel.info.text())
click(TRAP[3])
check("…e si rimette dove serve", len(panel.tool.pts) == 4 and abs(panel.tool.pts[3][0] - 70) < 0.3)
click((300, 300))
key(Qt.Key_Backspace)
check("Backspace toglie l'ultimo punto", len(panel.tool.pts) == 4)
n_shapes = len(ed.doc.shapes)
n_undo = len(ed.undo_stack)
click(TRAP[0])  # clic sul primo punto: chiude
area = next((s for s in ed.doc.shapes if s.layer == TOOL_LAYER), None)
check("clic sul primo punto: l'area si chiude e diventa una forma del livello T1",
      area is not None and len(ed.doc.shapes) == n_shapes + 1 and area.closed() and not panel.isVisible()
      and abs(area.bounds().width() - 160) < 0.6 and abs(area.bounds().height() - 90) < 0.6, area and area.bounds())
check("…un solo passo nella cronologia, strumento di nuovo Selezione, area e pezzi selezionati",
      len(ed.undo_stack) == n_undo + 1 and cv.tool is cv.tools["select"] and area in ed.selection
      and all(s in ed.selection for s in parts))
job = gcode.generate(ed.doc, w.profile)
check("l'area non viene mai incisa (prima il livello T1 finiva nel lavoro come gli altri)",
      all(st.index != TOOL_LAYER for st in job.layers) and len(job.layers) == 1 and abs(job.bounds.width() - 110) < 0.01,
      ([st.index for st in job.layers], job.bounds))

# ================================================================== nesting dentro il trapezio
dlg = w._nest_manual_dlg
check("si apre «Ottimizza lo spazio» sull'area disegnata (non si cambia, niente altri pannelli)",
      dlg is not None and dlg.manual is area and dlg.area.currentData() == "sheet" and not dlg.area.isEnabled()
      and dlg.multi.isHidden() and len(dlg.parts) == 6)
res = dlg.run()
pts = [(e.x, e.y) for e in (area.path().elementAt(i) for i in range(area.path().elementCount() - 1))]
check("i 6 pezzi finiscono tutti dentro il trapezio", res is not None and all(inside(s, pts) for s in parts),
      [s.bounds().center().toTuple() for s in parts])
check("…senza sovrapporsi", not any(a.bounds().adjusted(0.05, 0.05, -0.05, -0.05).intersects(b.bounds())
                                    for i, a in enumerate(parts) for b in parts[i + 1:]))
ed.undo()
check("Ctrl+Z riporta i pezzi dov'erano", [s.bounds().center().toTuple() for s in ed.doc.shapes if s.layer != TOOL_LAYER][:6]
      == orig)

# ================================================================== l'area non basta
ed.doc.shapes.clear()
ed.selection = []
parts = pieces(14, 40, 30)  # 14 pezzi da 40 × 30: in un triangolino non entrano
panel = w.nest_dialog(mode="manual")
for p in ((40, 40), (110, 40), (75, 90)):
    click(p)
key(Qt.Key_Return)
dlg = w._nest_manual_dlg
before = [s.bounds().center().toTuple() for s in parts]
asked = []
dlg.ask_new_area = lambda left, total: (asked.append((left, total)), True)[1]
res = dlg.run()
check("area troppo piccola: avviso con quanti pezzi restano fuori", res is None and len(asked) == 1 and asked[0][1] == 14
      and asked[0][0] >= 1, asked)
check("…non si sposta niente", [s.bounds().center().toTuple() for s in parts] == before)
check("…scelta «nuova area»: l'area vecchia sparisce e si ridisegna con gli stessi pezzi", dlg.again
      and not [s for s in ed.doc.shapes if s.layer == TOOL_LAYER] and len(dlg.parts) == 14)
panel = w.nest_manual_start(dlg.parts)
for p in ((20, 20), (320, 20), (300, 200), (40, 200)):
    click(p)
check("pulsante «Chiudi l'area e continua»", panel.finish() is True)
dlg = w._nest_manual_dlg
asked.clear()
dlg.ask_new_area = lambda left, total: (asked.append((left, total)), False)[1]
res = dlg.run()
big = next(s for s in ed.doc.shapes if s.layer == TOOL_LAYER)
bp = [(e.x, e.y) for e in (big.path().elementAt(i) for i in range(big.path().elementCount() - 1))]
check("nell'area più grande entrano tutti e 14, senza altre domande", res is not None and not asked
      and all(inside(s, bp) for s in parts), asked)
# annulla
ed.doc.shapes.clear()
ed.selection = []
parts = pieces(14, 40, 30)
panel = w.nest_dialog(mode="manual")
for p in ((40, 40), (110, 40), (75, 90)):
    click(p)
panel.finish()
dlg = w._nest_manual_dlg
dlg.ask_new_area = lambda left, total: False
before = [s.bounds().center().toTuple() for s in parts]
dlg.run()
check("scelta «annulla»: niente spostato, l'area resta sul livello T1, nessun nuovo disegno",
      not dlg.again and [s.bounds().center().toTuple() for s in parts] == before
      and len([s for s in ed.doc.shapes if s.layer == TOOL_LAYER]) == 1 and getattr(w, "_nest_panel", None) is None)

# ================================================================== aree non valide, Esc
ed.doc.shapes.clear()
ed.selection = []
parts = pieces(3)
panel = w.nest_dialog(mode="manual")
click((50, 50))
click((90, 50))
key(Qt.Key_Return)
check("due punti soli: l'area non si chiude, con il motivo", panel.isVisible() and "3 punti" in panel.info.text(), panel.info.text())
click((90, 90))
click((50, 120))  # poi tolgo e faccio un «otto»
click((50, 120))
click((120, 60))
click((60, 100))
ok = panel.finish()
check("contorno che si incrocia: rifiutato con il consiglio", ok is False and "incrocia" in panel.info.text(), panel.info.text())
key(Qt.Key_Escape)
check("Esc: annullato, nessuna forma aggiunta, strumento Selezione", not panel.isVisible() and len(ed.doc.shapes) == 3
      and cv.tool is cv.tools["select"] and getattr(w, "_nest_panel", None) is None)
panel = w.nest_dialog(mode="manual")
click((50, 50))
cv.set_tool("rect")
check("scelto un altro strumento a metà: è un annullamento", not panel.isVisible() and getattr(w, "_nest_panel", None) is None
      and len(ed.doc.shapes) == 3)
cv.set_tool("select")

# ================================================================== laser sui punti
panel = w.nest_dialog(mode="manual")
panel.laser.setChecked(True)
check("laser non collegato: la spunta non resta, con il motivo", not panel.laser.isChecked() and "collegato" in panel.info.text(),
      panel.info.text())
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings and w.ctl.last_status.get("state") == "Idle")
w.profile.homing = True
w.ctl.homed = False
panel.laser.setChecked(True)
check("senza homing: la spunta non resta, con il motivo", not panel.laser.isChecked() and "homing" in panel.info.text(),
      panel.info.text())
w.ctl.home()
until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 20)
sent = []
w.ctl.line_sent.connect(lambda l: sent.append(l))
panel.laser.setChecked(True)
until(lambda: w.ctl.fire_active, 3)
s_vals = [float(m.group(1)) for l in sent for m in [re.match(r"^M3 S([\d.]+)$", l)] if m]
cap = w.laser.glow_cap / 100.0 * w.profile.s_max
check("con l'homing fatto: il laser si accende al minimo, entro il limite della Lucciola",
      panel.laser.isChecked() and w.ctl.fire_active and w.laser._glow_on and s_vals and max(s_vals) <= cap + 1e-6,
      (s_vals, cap))
click((60, 70))
check("punto messo: la testa ci va", until(lambda: abs(w.ctl.sim.pos[0] - w.profile.to_machine(60, 70)[0]) < 0.8
                                           and abs(w.ctl.sim.pos[1] - w.profile.to_machine(60, 70)[1]) < 0.8, 15),
      (w.ctl.sim.pos, w.profile.to_machine(60, 70)))
check("…con il laser sempre acceso al minimo (mai più forte)", w.ctl.fire_active
      and not [l for l in sent if re.match(r"^(M4|M3 S)", l) and l not in [f"M3 S{v:.1f}" for v in s_vals]], sent[-6:])
pos = list(w.ctl.sim.pos)
click((60, 70))
until(lambda: False, 0.5)
check("punto tolto: la testa resta dov'è", len(panel.tool.pts) == 0 and until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
      and abs(w.ctl.sim.pos[0] - pos[0]) < 0.01)
click((60, 85))
check("rimesso poco più in là: la testa va sul punto nuovo",
      until(lambda: abs(w.ctl.sim.pos[1] - w.profile.to_machine(60, 85)[1]) < 0.8 and w.ctl.sim.pos[1] != pos[1], 15), w.ctl.sim.pos)
n_sent = len(sent)
panel.add_point(w.profile.bed_x + 50, 60)
check("punto fuori dall'area di lavoro: il punto c'è ma la testa non ci va, e lo dice",
      len(sent) == n_sent and "fuori" in panel.info.text() and len(panel.tool.pts) == 2, panel.info.text())
panel.remove_point(1)
click((140, 85))
click((100, 140))
until(lambda: w.ctl.last_status.get("state") == "Idle" and not w.ctl.busy, 15)
panel.finish()
check("chiusa l'area: il laser si spegne", until(lambda: not w.ctl.fire_active, 3) and not w.laser._glow_on)
panel = w.nest_dialog(mode="manual")
panel.laser.setChecked(True)
until(lambda: w.ctl.fire_active, 3)
key(Qt.Key_Escape)
check("annullando con il laser acceso: si spegne", until(lambda: not w.ctl.fire_active, 3) and not w.laser._glow_on)
w.ctl.disconnect_port()

# ================================================================== il nesting automatico resta com'era
ed.doc.shapes.clear()
ed.selection = []
parts = pieces(5)
from freelasercut.ui.dialogs_nest import NestDialog  # noqa: E402

auto = NestDialog(w)
check("nesting automatico: come prima (piano intero, più pannelli disponibili, nessuna domanda)",
      auto.manual is None and auto.area.currentData() == "bed" and auto.area.isEnabled() and not auto.multi.isHidden()
      and auto.run() is not None)

# ================================================================== traduzioni
keys = set()
for name in ("nest_manual.py", "dialogs_nest.py", "main_window.py"):
    src = open(os.path.join(ROOT, "freelasercut", "ui", name), encoding="utf-8").read()
    for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', src):
        try:
            k = "".join(ast.literal_eval(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
        except (SyntaxError, ValueError):
            continue
        if name == "nest_manual.py" or "nesting" in k.lower() or "area disegnata" in k or "area che hai disegnato" in k:
            keys.add(k)
check("testi del nesting manuale trovati nel codice", len(keys) >= 35, len(keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k for k in keys if not loc.get(k)]
    bad = [k for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    check(f"traduzioni {lang}: tutti i testi, con gli stessi segnaposto", not miss and not bad, (miss[:3], bad[:3]))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
