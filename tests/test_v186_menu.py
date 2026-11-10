# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.6: menu del tasto destro sul piano nell'interfaccia classica (suggerimento di un utente). Nel Banco resta il
menu radiale.

Casi: clic destro nel vuoto (menu del piano); su un oggetto non selezionato (lo seleziona); su uno di più selezionati
(la selezione resta); Raggruppa / Separa / Blocca / Sblocca solo quando servono; i comandi sono le stesse azioni dei
menu (stesse scorciatoie) e funzionano; Incolla mette gli oggetti dove si è fatto clic; trascinando col destro niente
menu; con lo strumento Linea il destro chiude il tracciato come prima; nel Banco nessun menu a tendina.
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
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []
BANCO = os.environ["FLC_UI"] == "banco"


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas
cv.set_tool("select")
opened = []
cv.context_requested.connect(lambda v, g: opened.append(v))


def rect(x, y, wd=30, h=20):
    s = RectShape(wd, h)
    s.apply(QTransform.fromTranslate(x, y))
    return s


def right(bed_from, bed_to=None):
    """Clic destro vero sul piano (pressione e rilascio), anche trascinando."""
    a = cv.to_view(QPointF(*bed_from))
    b = cv.to_view(QPointF(*(bed_to or bed_from)))
    vp = cv.viewport()
    for kind, pt, btns in ((QEvent.MouseButtonPress, a, Qt.RightButton), (QEvent.MouseButtonRelease, b, Qt.NoButton)):
        g = QPointF(vp.mapToGlobal(pt.toPoint()))
        QApplication.sendEvent(vp, QMouseEvent(kind, pt, g, Qt.RightButton, btns, Qt.NoModifier))
    app.processEvents()


def menu_keys():
    m = getattr(w, "_ctx_menu", None)
    if m is None:
        return None
    names = {id(v): k for k, v in w.acts.items()}
    return ["-" if a_.isSeparator() else names.get(id(a_), "?") for a_ in m.actions()]


def close_menu():
    m = getattr(w, "_ctx_menu", None)
    if m is not None:
        m.close()
    w._ctx_menu = None
    opened.clear()
    app.processEvents()


r1, r2, r3 = rect(40, 40), rect(100, 40), rect(160, 40)
ed.add([r1, r2, r3], select=False)
ed.select([])
app.processEvents()

if BANCO:
    right((300, 250))
    check("Banco: nessun menu a tendina (resta il menu radiale)", menu_keys() is None and not opened
          and getattr(w.banco, "radial", None) is not None)
    check("Banco: la funzione del menu classico non apre niente", w.open_context_menu(QPointF(10, 10), cv.mapToGlobal(cv.rect().center())) is None)
else:
    # ---- nel vuoto
    right((300, 250))
    k = menu_keys()
    check("clic destro nel vuoto: menu del piano", k == ["paste", "paste_in_place", "-", "undo", "redo", "-", "select_all",
                                                         "-", "import", "-", "fit"] and w._ctx_menu.isVisible(), k)
    check("…le voci sono le azioni dei menu, con le loro scorciatoie",
          w._ctx_menu.actions()[0] is w.acts["paste"] and w.acts["paste"].shortcut().toString() == "Ctrl+V")
    close_menu()
    # ---- su un oggetto non selezionato
    right((40, 50))  # bordo sinistro di r1
    k = menu_keys()
    check("clic destro su un oggetto non selezionato: lo seleziona", ed.selection == [r1], [s.id for s in ed.selection])
    check("…menu dell'oggetto: taglia, copia, incolla, duplica, elimina, rifletti, davanti/dietro, blocca…",
          k == ["cut", "copy", "paste", "duplicate", "delete", "-", "flip_h", "flip_v", "front", "back", "-", "lock", "-",
                "to_path", "offset", "-", "fit_sel"], k)
    close_menu()
    # ---- su uno di più selezionati
    ed.select([r1, r2, r3])
    right((100, 50))
    k = menu_keys()
    check("clic destro su uno di tre selezionati: la selezione resta, compare Raggruppa (non Separa)",
          ed.selection == [r1, r2, r3] and "group" in k and "ungroup" not in k, k)
    w.acts["group"].trigger()
    app.processEvents()
    close_menu()
    g = ed.selection[0]
    right((40, 50))
    k = menu_keys()
    check("Raggruppa dal menu funziona; sul gruppo compare Separa (non Raggruppa)", len(ed.doc.shapes) == 1 and g.kind == "group"
          and "ungroup" in k and "group" not in k, k)
    w.acts["ungroup"].trigger()
    app.processEvents()
    close_menu()
    a1, a2, a3 = ed.doc.shapes
    # ---- copia e incolla dove si è fatto clic
    ed.select([])
    right((40, 50))
    w.acts["copy"].trigger()
    close_menu()
    right((300, 200))
    check("clic nel vuoto lontano dalla selezione: la toglie", ed.selection == [] and menu_keys()[0] == "paste")
    w.acts["paste"].trigger()
    app.processEvents()
    close_menu()
    new = [s for s in ed.doc.shapes if s not in (a1, a2, a3)]
    c = new[0].bounds().center() if new else QPointF(0, 0)
    check("Incolla dal menu: l'oggetto arriva dove si è fatto clic", len(new) == 1 and abs(c.x() - 300) < 1 and abs(c.y() - 200) < 1,
          (c.x(), c.y()))
    # ---- blocca / sblocca
    ed.select([a2])
    right((100, 50))
    w.acts["lock"].trigger()
    app.processEvents()
    close_menu()
    ed.select([a2])
    k = w.context_menu_keys()
    check("oggetto bloccato: nel menu c'è Sblocca e non Blocca", a2.locked and "unlock" in k and "lock" not in k, k)
    ed.lock(False)
    # ---- elimina
    ed.select([])
    n = len(ed.doc.shapes)
    right((160, 50))
    w.acts["delete"].trigger()
    app.processEvents()
    close_menu()
    check("Elimina dal menu toglie l'oggetto sotto il mouse; Ctrl+Z lo riporta", len(ed.doc.shapes) == n - 1 and a3 not in ed.doc.shapes)
    ed.undo()
    # ---- trascinare col destro, altri strumenti
    ed.select([])
    right((300, 250), (330, 270))
    check("trascinando col tasto destro: nessun menu", menu_keys() is None and not opened)
    cv.set_tool("nodes")
    right((300, 250))
    check("strumento Nodi: il menu c'è", menu_keys() is not None)
    close_menu()
    cv.set_tool("line")
    tool = cv.tool
    n = len(ed.doc.shapes)

    def left(bed):
        v = cv.to_view(QPointF(*bed))
        vp = cv.viewport()
        for kind, btns in ((QEvent.MouseButtonPress, Qt.LeftButton), (QEvent.MouseButtonRelease, Qt.NoButton)):
            QApplication.sendEvent(vp, QMouseEvent(kind, v, QPointF(vp.mapToGlobal(v.toPoint())), Qt.LeftButton, btns, Qt.NoModifier))
        app.processEvents()

    left((250, 150))
    left((280, 170))
    right((300, 150))
    check("strumento Linea: il tasto destro chiude il tracciato come prima, senza menu",
          menu_keys() is None and not opened and len(ed.doc.shapes) == n + 1, (menu_keys(), len(ed.doc.shapes), n))
    cv.set_tool("select")

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
