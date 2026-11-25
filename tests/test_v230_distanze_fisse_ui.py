# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.0: distanze fisse, parte 2 — l'interfaccia (Classica e Banco con FLC_UI=banco).

Casi: comandi nascosti senza il codice delle funzioni in prova e visibili con il codice; «Distanza esatta» con
«Mantieni» crea la distanza fissa in un solo passo; avviso e OK spento se l'oggetto che si sposta è già legato su
quell'asse; «Mantieni» rifiutato se farebbe un giro; Misura da un angolo a un angolo di due oggetti → «Fissa questa
distanza» (X, Y, punto-punto) e niente pulsante se le estremità non sono su un oggetto o senza il codice; trascinando
il riferimento chi segue si sposta dal vivo; quota disegnata (verde), arancio se chi segue esce dall'area, nascosta
con «Distanze fisse» spento; doppio clic sulla quota: nuovo valore; tasto destro: menu con Cambia, Spegni, Togli;
«Togli le distanze fisse»; senza il codice le distanze di un progetto guidano lo stesso; G-code senza quote.
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
for k in ("FLC_NO_DIALOGS", "FLC_NO_FIRST_RUN", "FLC_NO_UPDATE"):
    os.environ[k] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from freelasercut import admin  # noqa: E402
from freelasercut.core import gcode, ties  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.ui import ties_ui  # noqa: E402
from freelasercut.ui.dialogs_distance import make_distance_dialog  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

BANCO = os.environ.get("FLC_UI") == "banco"
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info != "" and not cond else ""))


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def rect(w, h, x, y):
    r = RectShape(w, h)
    r.set_transform(QTransform.fromTranslate(x, y))
    return r


w = MainWindow()
w.resize(1400, 850)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas
msgs = []
ed.message.connect(msgs.append)


def reset(*shapes):
    ed.doc.shapes = []
    for s in shapes:
        ed.doc.add(s)
    ed.selection = []
    ed.changed.emit()
    app.processEvents()


def gap_x(R, S):
    return S.bounds().left() - R.bounds().right()


def paint():
    cv.viewport().update()
    app.processEvents()
    img = cv.viewport().grab().toImage()  # disegna davvero la tela (e con lei quote e strumenti)
    app.processEvents()
    return img


# ------------------------------------------------------------------ comandi nascosti senza codice
admin.set_unlocked(w.qs, False)
w._apply_admin()
check("senza codice: comandi delle distanze fisse nascosti",
      not w.acts["ties_clear"].isVisible() and not w.acts["ties_show"].isVisible() and not cv.ties_create)
R, S = rect(20, 10, 10, 10), rect(10, 10, 50, 10)
reset(R, S)
ed.select([R, S])
dlg = make_distance_dialog(w)
check("senza codice: niente «Mantieni» in Distanza esatta", dlg is not None and not dlg.keep_allowed)
dlg.reject()
admin.set_unlocked(w.qs, True)
w._apply_admin()
check("con il codice: comandi visibili, Misura propone la distanza fissa",
      w.acts["ties_clear"].isVisible() and w.acts["ties_show"].isVisible() and cv.ties_create)
check("«Togli le distanze fisse» nel menu Disponi/Allinea",
      any(w.acts["ties_clear"] in m.actions() for m in w.findChildren(type(w.m_view))))

# ------------------------------------------------------------------ Distanza esatta + Mantieni
reset(R, S)
ed.select([R, S])
n0 = len(ed.undo_stack)
dlg = make_distance_dialog(w)
dlg.dist.setValue(15)
dlg.keep.setChecked(True)
dlg.accept()
check("Distanza esatta + Mantieni: un passo, 15 mm, S segue R", len(ed.undo_stack) == n0 + 1 and near(gap_x(R, S), 15)
      and len(S.ties) == 1 and S.ties[0]["ref"] == R.id)
ed.begin("Sposta")
R.apply(QTransform.fromTranslate(8, 3))
ed.commit()
check("…R spostato: S tiene i 15 mm", near(gap_x(R, S), 15))
ed.undo()
ed.undo()
R2, S2 = ed.doc.find(R.id), ed.doc.find(S.id)
check("Annulla due volte: distanza e posizione di prima", near(S2.bounds().left(), 50) and S2.ties == [])
ed.redo()
S2 = ed.doc.find(S.id)
check("Ripeti: di nuovo la distanza fissa", len(S2.ties) == 1)

R, S = ed.doc.find(R.id), ed.doc.find(S.id)
ed.select([R, S])
dlg = make_distance_dialog(w)
dlg._changed()
check("S già legato in X: avviso e OK spento", dlg.lbl_tie.text() != "" and not dlg.ok_btn.isEnabled())
dlg.axis.setCurrentIndex(1)
check("…in Y si può", dlg.lbl_tie.text() == "" and dlg.ok_btn.isEnabled())
dlg.reject()
ed.select([S, R])  # al contrario: S fermo, R si sposta e lo vorrebbe seguire
dlg = make_distance_dialog(w)
dlg.keep.setChecked(True)
check("Mantieni che farebbe un giro: avviso e OK spento", "inseguirebbero" in dlg.lbl_tie.text() and not dlg.ok_btn.isEnabled())
dlg.keep.setChecked(False)
check("…senza Mantieni si può spostare", dlg.ok_btn.isEnabled())
dlg.reject()

# ------------------------------------------------------------------ Misura → Fissa questa distanza
A, B, C = rect(20, 20, 20, 20), rect(20, 20, 80, 20), rect(20, 20, 20, 90)
reset(A, B, C)
cv.set_tool("measure")
mt = cv.tools["measure"]
check("strumento Misura attivo", cv.tool is mt)
mt.a, mt.b = QPointF(40, 30), QPointF(80, 30)  # bordo destro di A (centro) → bordo sinistro di B (centro)
pr = mt.propose()
check("Misura da A a B in orizzontale: distanza fissa in X proposta", pr is not None and pr[2]["axis"] == "x"
      and pr[0] is A and pr[1] is B and near(pr[2]["d"], 40))
paint()
check("…pulsante «Fissa questa distanza» disegnato", mt.btn is not None)
ev = QMouseEvent(QEvent.MouseButtonPress, mt.btn.center(), mt.btn.center(), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
mt.press(ev, QPointF(0, 0))
check("clic sul pulsante: B segue A e la misura sparisce", len(B.ties) == 1 and mt.a is None and mt.prop is None)
mt.a, mt.b = QPointF(30, 40), QPointF(30, 90)  # in basso al centro di A → in alto al centro di C
pr = mt.propose()
check("Misura in verticale: distanza fissa in Y", pr is not None and pr[2]["axis"] == "y" and pr[1] is C)
mt.fix()
mt.a, mt.b = QPointF(40, 40), QPointF(80, 20)
pr = mt.propose()
check("Misura in diagonale fra due angoli: punto-punto", pr is not None and pr[2]["axis"] == "p")
check("…ma B è già legato in X: rifiutato con il motivo", mt.fix() == "busy" and "già una distanza fissa" in msgs[-1])
mt.a, mt.b = QPointF(5, 5), QPointF(80, 20)
check("un'estremità nel vuoto: nessun pulsante", mt.propose() is None)
paint()
check("…e niente pulsante disegnato", mt.btn is None)
cv.ties_create = False
mt.a, mt.b = QPointF(40, 30), QPointF(80, 30)
check("senza il codice: Misura non propone niente", mt.propose() is None)
cv.ties_create = True
mt.a = mt.b = mt.prop = None
cv.set_tool("select")

# ------------------------------------------------------------------ trascinamento dal vivo
st = cv.tools["select"]
ed.select([A])
st.orig = {A.id: (A, QTransform(A.tf))}
st._apply(QTransform.fromTranslate(12, 7))
check("trascinando A in diagonale: B segue in X (non in Y), C in Y (non in X), dal vivo",
      near(gap_x(A, B), 40) and near(B.bounds().top(), 20) and near(C.bounds().top(), 97) and near(C.bounds().left(), 20))
for s, tf0 in st.orig.values():
    s.set_transform(tf0)
cv.refresh_live([A])
check("…e tornano se il trascinamento torna indietro", near(B.bounds().left(), 80) and near(C.bounds().top(), 90))

# ------------------------------------------------------------------ quote sul piano
cv.fit_rect(ed.doc.bounds().adjusted(-20, -20, 20, 20), 10)
paint()
check("quote disegnate: due etichette", len(cv._tie_hits) == 2)
img = paint()
box = cv._tie_hits[0][0]
col = img.pixelColor(int(box.left()) + 1, int(box.center().y()))
check("quota verde (bordo dell'etichetta)", col.green() > col.red(), col.name())
w.acts["ties_show"].trigger()
paint()
check("Distanze fisse spento: niente quote", not cv.show_ties and cv._tie_hits == [])
w.acts["ties_show"].trigger()
paint()
check("riacceso: quote di nuovo", cv.show_ties and len(cv._tie_hits) == 2)
hb = [h for h in cv._tie_hits if h[1] == B.id][0]
h = ties_ui.hit(cv, hb[0].center())
check("clic sull'etichetta: trovata la quota giusta", h is not None and h[0] is B)
ties_ui.edit_value(cv, B, 0, 25)
check("nuovo valore dalla quota: B si sposta a 25 mm", near(gap_x(A, B), 25))
m = ties_ui.menu(cv, B, 0, None, run=False)
names = [a.text() for a in m.actions()]
check("tasto destro: Cambia, Spegni, Togli", len(names) == 3 and "Togli" in names[2])
m.actions()[1].trigger()
paint()
check("Spegni dal menu: quota grigia, B non segue", B.ties[0].get("on") is False and
      ed.ties_of(B) == [] and len(cv._tie_hits) == 2)
m = ties_ui.menu(cv, B, 0, None, run=False)
m.actions()[1].trigger()
check("Riaccendi dal menu", ed.ties_of(B) != [])
ed.begin("Sposta")
B.apply(QTransform.fromTranslate(0, 0))
ed.commit()
ed.begin("Sposta")
A.apply(QTransform.fromTranslate(1000, 0))  # chi segue finisce fuori dall'area
ed.commit()
img = paint()
hb = [h for h in cv._tie_hits if h[1] == B.id]
check("chi segue fuori dall'area: la quota c'è (arancio)", hb != [])
ed.undo()
A, B = ed.doc.find(A.id), ed.doc.find(B.id)

# ------------------------------------------------------------------ Togli le distanze fisse
ed.select([B, ed.doc.find(C.id)])
check("Togli le distanze fisse: due tolte", w.clear_ties() == 2 and not ed.doc.find(B.id).ties)
ed.select([A])
check("…su oggetti senza: lo dice", w.clear_ties() == 0 and "non hanno" in msgs[-1])

# ------------------------------------------------------------------ senza codice guidano lo stesso; G-code
R, S = rect(20, 10, 10, 10), rect(10, 10, 50, 10)
S.ties = [ties.make_xy(R.id, R.bounds(), S.bounds(), "x", "max", "min")]
reset(R, S)
admin.set_unlocked(w.qs, False)
w._apply_admin()
ed.begin("Sposta")
R.apply(QTransform.fromTranslate(5, 0))
ed.commit()
paint()
check("senza codice: la distanza di un progetto guida e si vede", near(gap_x(R, S), 20) and len(cv._tie_hits) == 1)
g1 = "\n".join(map(str, gcode.generate(ed.doc, w.profile).lines))
S.ties = []
g2 = "\n".join(map(str, gcode.generate(ed.doc, w.profile).lines))
check("G-code: le quote non escono (uguale senza legami)", g1 == g2 and g1 != "")
admin.set_unlocked(w.qs, True)
w._apply_admin()

if BANCO:
    check("Banco: «Togli le distanze fisse» nel menu Allinea",
          any(w.acts["ties_clear"] in mm.actions() for mm in w.findChildren(type(w.m_view))))

print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(0 if all(results) else 1)
