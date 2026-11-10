# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.3: selezione dopo il nesting (da un commento sotto il video: «dopo il nesting vedo gli oggetti come un oggetto
solo e non li modifico più uno per uno»).

Matrice dei casi nel documento «aggiornamento-0.18.3»:
1 clic su una forma di una selezione multipla = solo quella; 2 trascinando si spostano tutte; 3 sotto la soglia = clic;
4 Maiusc/Ctrl+clic come prima; 5 selezione singola, vuoto, forma non selezionata; 6 forme bloccate; 7 doppio clic;
8 fine nesting senza selezione (o solo i pezzi che non entrano); 9 linee di taglio comuni non ricordate, con avviso.
"""
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
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QTransform
from PySide6.QtWidgets import QApplication

app = QApplication([])
from freelasercut.core.document import EllipseShape, RectShape
from freelasercut.ui.dialogs_nest import NestDialog
from freelasercut.ui.main_window import MainWindow

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas
cv.set_tool("select")
tool = cv.tool


def mk(shape, x, y):
    b = shape.bounds()
    shape.apply(QTransform.fromTranslate(x - b.left(), y - b.top()))
    return shape


def fresh(*shapes):
    ed.doc.shapes.clear()
    ed.selection = []
    ed.add(list(shapes), select=False)
    app.processEvents()
    return list(shapes)


def edge(s):
    """Un punto del contorno della forma che il clic prende davvero: non sopra una maniglia del riquadro della
    selezione attuale (angoli, metà dei lati, rotazione), che hanno giustamente la precedenza, e non sopra un'altra
    forma."""
    tf = cv.bed_to_view_tf()
    path = s.path()
    for k in range(1, 40):
        q = path.pointAtPercent((k * 0.137) % 1.0)
        if cv.hit_shape(q) is s and (not ed.editable() or tool._hit_handle(tf.map(q), tf) is None):
            return q
    raise AssertionError("nessun punto libero sul contorno")


def _ev(kind, view, mods, down):
    return QMouseEvent(kind, view, cv.viewport().mapToGlobal(view.toPoint()), Qt.LeftButton,
                       Qt.LeftButton if down else Qt.NoButton, mods)


def click(p, mods=Qt.NoModifier, wobble=0):
    """Pressione e rilascio nel punto p (mm sul piano); wobble = pixel di tremolio della mano prima del rilascio."""
    v = cv.bed_to_view_tf().map(p)
    tool.press(_ev(QEvent.MouseButtonPress, v, mods, True), p)
    if wobble:
        v2 = v + QPointF(wobble, 0)
        tool.move(_ev(QEvent.MouseMove, v2, mods, True), cv.to_bed(v2))
    tool.release(_ev(QEvent.MouseButtonRelease, v, mods, False), p)
    app.processEvents()


def drag(p, px):
    v = cv.bed_to_view_tf().map(p)
    tool.press(_ev(QEvent.MouseButtonPress, v, Qt.NoModifier, True), p)
    for k in (px // 2, px):
        v2 = v + QPointF(k, 0)
        tool.move(_ev(QEvent.MouseMove, v2, Qt.AltModifier, True), cv.to_bed(v2))  # Alt = senza aggancio
    tool.release(_ev(QEvent.MouseButtonRelease, v2, Qt.NoModifier, False), cv.to_bed(v2))
    app.processEvents()


def xs(shapes):
    return [round(s.bounds().left(), 6) for s in shapes]


# ---------------------------------------------------------------- 1. clic su una della selezione multipla
A, B, C = fresh(mk(RectShape(40, 30), 20, 50), mk(RectShape(40, 30), 90, 50), mk(EllipseShape(30, 30), 160, 50))
ed.select([A, B, C])
n0, x0 = len(ed.undo_stack), xs([A, B, C])
click(edge(B))
check("tre selezionate, clic su una: resta selezionata solo quella", ed.selection == [B], len(ed.selection))
check("…senza spostare niente e senza passi nella cronologia", xs([A, B, C]) == x0 and len(ed.undo_stack) == n0)

# ---------------------------------------------------------------- 2. trascinando si spostano tutte
ed.select([A, B, C])
drag(edge(B), 40)
moved = [round(b - a, 6) for a, b in zip(x0, xs([A, B, C]))]
check("tre selezionate, trascino da una: si spostano tutte e tre insieme", moved[0] > 0.5 and len(set(moved)) == 1, moved)
check("…restano selezionate tutte, un solo passo «Sposta»", len(ed.selection) == 3 and len(ed.undo_stack) == n0 + 1
      and ed.undo_stack[-1][0] == "Sposta")
ed.undo()
A, B, C = ed.doc.shapes

# ---------------------------------------------------------------- 3. sotto la soglia è un clic
ed.select([A, B, C])
n0 = len(ed.undo_stack)
click(edge(A), wobble=2)
check("mano che trema di 2 pixel = clic: solo quella, niente spostamento", ed.selection == [A] and xs([A, B, C]) == x0
      and len(ed.undo_stack) == n0, (len(ed.selection), xs([A, B, C])))

ed.select([A, B, C])
bb = ed.selection_bounds()
click(QPointF(bb.left(), bb.center().y()))
check("clic su una maniglia del riquadro: la selezione resta com'è (le maniglie hanno la precedenza)",
      len(ed.selection) == 3 and xs([A, B, C]) == x0)

# ---------------------------------------------------------------- 4. Maiusc e Ctrl come prima
ed.select([A, B, C])
click(edge(B), Qt.ShiftModifier)
check("Maiusc+clic su una selezionata: la toglie dalla selezione", ed.selection == [A, C])
click(edge(B), Qt.ControlModifier)
check("Ctrl+clic su una non selezionata: la aggiunge", set(ed.selection) == {A, B, C} and len(ed.selection) == 3)

# ---------------------------------------------------------------- 5. casi semplici invariati
ed.select([A])
click(edge(A))
check("clic sull'unica selezionata: resta lei", ed.selection == [A])
click(edge(C))
check("clic su una non selezionata: solo lei", ed.selection == [C])
ed.select([A, B, C])
click(QPointF(300, 300))
check("clic nel vuoto: nessuna selezione", ed.selection == [])

# ---------------------------------------------------------------- 6. forme bloccate
for s in (A, B, C):
    s.locked = True
ed.select([A, B, C])
click(edge(C))
check("selezione di forme bloccate: il clic sceglie quella cliccata", ed.selection == [C])
for s in (A, B, C):
    s.locked = False

# ---------------------------------------------------------------- 7. doppio clic
ed.select([A, B, C])
click(edge(B))
v = cv.bed_to_view_tf().map(edge(B))
tool.double_click(_ev(QEvent.MouseButtonDblClick, v, Qt.NoModifier, True), edge(B))
app.processEvents()
check("doppio clic su una della selezione multipla: strumento Nodi su quella", cv.tool.name == "nodes" and ed.selection == [B])
cv.set_tool("select")
tool = cv.tool

# ---------------------------------------------------------------- 8. nesting
for k_ in ("nest_multi", "nest_common"):
    w.qs.setValue(k_, False)
shapes = fresh(*[mk(RectShape(40, 30), 20 + 70 * i, 50 + 40 * (i % 3)) for i in range(5)], mk(EllipseShape(30, 30), 300, 200))
dlg = NestDialog(w)
res = dlg.run()
dlg.accept()
app.processEvents()
check("nesting: sei pezzi sistemati, restano sei forme separate", len(res.placements) == 6 and len(ed.doc.shapes) == 6)
check("…e alla fine non è selezionato niente (prima erano selezionati tutti)", ed.selection == [])
click(edge(ed.doc.shapes[2]))
check("un clic su un pezzo dopo il nesting: selezionato solo lui", ed.selection == [ed.doc.shapes[2]])
ed.select(list(ed.doc.shapes))
click(edge(ed.doc.shapes[4]))
check("anche se li seleziono tutti a mano: un clic ne sceglie uno", ed.selection == [ed.doc.shapes[4]])
shapes = fresh(*[mk(RectShape(40, 30), 20 + 70 * i, 150) for i in range(5)])
dlg = NestDialog(w)
dlg.area.setCurrentIndex(dlg.area.findData("custom"))
dlg.cx.setValue(0)
dlg.cy.setValue(0)
dlg.cw.setValue(60)
dlg.ch.setValue(45)
dlg.run()
dlg.accept()
app.processEvents()
inside = [s for s in ed.doc.shapes if s.bounds().right() <= 60.001 and s.bounds().bottom() <= 45.001]
check("pezzi che non entrano: restano selezionati solo quelli", 0 < len(ed.selection) < 5
      and not any(s in inside for s in ed.selection) and len(ed.selection) + len(inside) == 5,
      (len(ed.selection), len(inside)))

# ---------------------------------------------------------------- 9. linee di taglio comuni
w.qs.setValue("nest_common", True)  # preferenza lasciata dalle versioni fino alla 0.18.2
shapes = fresh(*[mk(RectShape(40, 30), 20 + 70 * i, 150) for i in range(4)])
before = ed.doc.snapshot()
dlg = NestDialog(w)
check("«Linee di taglio comuni» parte spenta anche con la vecchia preferenza salvata", not dlg.common.isChecked())
dlg.common.setChecked(True)
dlg.run()
txt = dlg.result.text()
dlg.accept()
app.processEvents()
check("con le linee comuni i contorni diventano un tracciato unico, e il messaggio lo dice con Ctrl+Z",
      len(ed.doc.shapes) < 4 and "Ctrl+Z" in txt, (len(ed.doc.shapes), txt[-120:]))
ed.undo()
check("Ctrl+Z ridà i quattro pezzi separati", ed.doc.snapshot() == before and len(ed.doc.shapes) == 4)
dlg = NestDialog(w)
check("…e alla riapertura la spunta è di nuovo spenta (non si ricorda più)", not dlg.common.isChecked()
      and w.qs.value("nest_common") is None, w.qs.value("nest_common"))
dlg.close()

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
