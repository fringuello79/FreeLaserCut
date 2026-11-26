# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.23.3, domanda di un utente («esiste il comando per scalare tutto il progetto di una percentuale?») e richiesta di
Ale (26/11): casella della scala in percentuale nella barra delle misure, discreta, subito dopo L 🔒 A.
- si scrive un numero e Invio: la selezione si scala in modo uniforme attorno al punto del quadratino a 9 punti, un
  solo passo di Annulla «Scala», poi la casella torna a «100 %» (anche se il cursore resta dentro: uscendo non deve
  scalare una seconda volta);
- 0 e negativi non valgono, oltre 10 000 % si ferma a 10 000 %; frecce della tastiera e rotella non fanno niente;
- stesso risultato di L con il lucchetto chiuso e lo stesso fattore (raggi, testi, gruppi: la stessa strada);
- anche in L e A si può scrivere «150%»; negli altri campi (per esempio la potenza, con « %» come unità) il simbolo
  resta un errore come prima;
- la barra: Classica sta ancora a 1366 px e non allarga la finestra; Banco: fino a R tutto come prima."""
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
import math  # noqa: E402
import time  # noqa: E402

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QFontMetricsF, QKeyEvent, QTransform, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core import ops  # noqa: E402
from freelasercut.core.document import GroupShape, RectShape  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui import main_window as M  # noqa: E402
from freelasercut.ui import style  # noqa: E402
from freelasercut.ui.widgets import NumField, evaluate  # noqa: E402

app.setStyle("Fusion")
style.load_fonts()
app.setFont(style.ui_font(9))
app.setStyleSheet(M.QSS.replace("'Segoe UI', 'Inter'", f"'{style.UI_FONT}', 'Segoe UI'") + style.QSS_EXTRA)

BANCO = os.environ["FLC_UI"] == "banco"
TAG = "[banco] " if BANCO else "[classica] "
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(f"  {'OK ' if cond else 'KO '} {TAG}{name} {info}", flush=True)


def spin(sec=0.05):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.005)


def close(a, b, eps=1e-6):
    return abs(a - b) <= eps


w = M.MainWindow()
w.resize(1500, 900)
w.show()
spin(0.4)
ed = w.editor
nb = w.numeric
P = nb.fpct


def write(field, text, focus_out=False):
    """Scrive nella casella come una persona: testo, Invio (il cursore resta dentro); se focus_out, poi esce."""
    field.setFocus()
    spin(0.02)
    field.selectAll()
    field.setText(text)
    QApplication.sendEvent(field, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    QApplication.sendEvent(field, QKeyEvent(QEvent.KeyRelease, Qt.Key_Return, Qt.NoModifier))
    spin(0.05)
    if focus_out:
        w.canvas.setFocus()
        spin(0.05)


def bounds():
    b = ed.selection_bounds()
    return b.left(), b.top(), b.width(), b.height()


def fresh(*shapes):
    """Piano vuoto con queste forme, selezionate, cronologia azzerata."""
    ed.select(list(ed.doc.shapes))
    for x in list(ed.doc.shapes):
        x.locked = False
    if ed.doc.shapes:
        ed.select(list(ed.doc.shapes))
        ed.delete()
    ed.add(list(shapes), "prova")
    ed.select(list(shapes))
    ed.undo_stack.clear()
    ed.redo_stack.clear()
    spin(0.05)


def rect(wd, ht, x, y, rot=0.0):
    r = RectShape(wd, ht)
    t = QTransform()
    t.translate(x, y)
    if rot:
        t.rotate(rot)
    r.set_transform(t)
    return r


# ---------------------------------------------------------------- 1. la casella: dove, com'è
order = [nb.widgetForAction(a) for a in nb.actions()]
order = [x for x in order if x is not None]
i_h, i_p, i_r = order.index(nb.fh), order.index(P), order.index(nb.frad)
between = order[i_h + 1:i_p]
check("subito dopo A (niente in mezzo) e prima di R", between == [] and i_h < i_p < i_r,
      [type(x).__name__ for x in between])
check("stretta: la più stretta della barra, meno di 2/3 di L", P.width() < nb.fw.width() * 2 / 3
      and P.width() <= min(f.width() for f in (nb.fx, nb.fy, nb.fw, nb.fh, nb.frad, nb.fr)), (P.width(), nb.fw.width()))
check("alta come le altre, senza freccette", P.height() == nb.fw.height() and not getattr(P, "_arrows", False),
      (P.height(), nb.fw.height()))
check("«100 %» si legge intero", P.text() == "100 %" and P.text_room() >= QFontMetricsF(P.font()).horizontalAdvance("888 %"),
      (P.text(), P.text_room()))
check("suggerimento e scheda della guida", "percentuale" in P.toolTip() and P.property("help_key") == "num:scale"
      and "num:scale" in help_texts.HELP and help_texts.HELP["num:scale"][0].startswith("Scala"))

# ---------------------------------------------------------------- 2. accesa / spenta
ed.select([])
spin(0.05)
check("senza selezione: spenta e a 100", not P.isEnabled() and P.value() == 100.0)
lk = rect(30, 20, 10, 10)
fresh(lk)
lk.locked = True
ed.select([lk])
spin(0.05)
check("solo forme bloccate: spenta", not P.isEnabled())
lk.locked = False

# ---------------------------------------------------------------- 3. il caso di tutti i giorni
r = rect(120, 110, 250, 148)
fresh(r)
nb.anchor.setValue(4)
x0, y0, w0, h0 = bounds()
cx, cy = x0 + w0 / 2, y0 + h0 / 2
write(P, "150")
x1, y1, w1, h1 = bounds()
check("150 → una volta e mezza in larghezza e in altezza", close(w1, w0 * 1.5) and close(h1, h0 * 1.5), (w1, h1))
check("…il centro (punto scelto) resta fermo", close(x1 + w1 / 2, cx) and close(y1 + h1 / 2, cy))
check("…un solo passo di Annulla, «Scala»", len(ed.undo_stack) == 1 and ed.undo_stack[-1][0] == "Scala",
      [e[0] for e in ed.undo_stack])
check("…la casella torna a «100 %» anche con il cursore ancora dentro", P.text() == "100 %" and P.value() == 100.0
      and P.hasFocus(), (P.text(), P.value(), P.hasFocus()))
w.canvas.setFocus()
spin(0.05)
check("…uscendo dalla casella non scala una seconda volta", close(bounds()[2], w1) and len(ed.undo_stack) == 1)
ed.undo()
spin(0.05)
check("Annulla: misure e posizione di prima, esatte", all(close(a, b) for a, b in zip(bounds(), (x0, y0, w0, h0))))
ed.redo()
spin(0.05)
check("Ripeti: di nuovo una volta e mezza", close(bounds()[2], w0 * 1.5))

# ---------------------------------------------------------------- 4. altri valori e scritture
cases = [("50", 0.5), ("150%", 1.5), ("+10%", 1.1), ("-10%", 0.9), ("*2", 2.0), ("120/2", 0.6), ("+10", 1.1),
         ("250 %", 2.5), ("4.00/3.00*100", 4 / 3), ("4,00/3,00*100", 4 / 3), ("3/4*100", 0.75)]
bad = []
for text, k in cases:
    fresh(rect(40, 30, 100, 100))
    b0 = bounds()
    write(P, text, focus_out=True)
    b1 = bounds()
    if not (close(b1[2], b0[2] * k) and close(b1[3], b0[3] * k) and len(ed.undo_stack) == 1 and P.text() == "100 %"):
        bad.append((text, b1[2] / b0[2], len(ed.undo_stack), P.text()))
check("50, 150%, +10%, -10%, *2, 120/2, +10, «250 %» e le formule degli spessori (4.00/3.00*100 per passare da 3 "
      "a 4 mm, anche con la virgola): il fattore giusto, un passo, di nuovo 100", not bad, bad)

nothing = []
for text in ("100", "0", "-5", "abc", "", "0%"):
    fresh(rect(40, 30, 100, 100))
    b0 = bounds()
    write(P, text, focus_out=True)
    if bounds() != b0 or ed.undo_stack or P.text() != "100 %":
        nothing.append((text, bounds(), len(ed.undo_stack), P.text()))
check("100, 0, -5, testo sbagliato, vuoto, 0%: nessun cambiamento, nessun passo di Annulla, di nuovo 100", not nothing,
      nothing)

fresh(rect(10, 5, 100, 100))
b0 = bounds()
write(P, "1000000", focus_out=True)
check("oltre il massimo: si ferma a 10 000 % (×100)", close(bounds()[2], b0[2] * 100, 1e-5), bounds()[2] / b0[2])
fresh(rect(100, 50, 100, 100))
b0 = bounds()
write(P, "0.5", focus_out=True)
check("sotto l'1 %: si ferma all'1 %", close(bounds()[2], b0[2] * 0.01), bounds()[2] / b0[2])

# ---------------------------------------------------------------- 5. punto di riferimento, rotazione, più forme
fresh(rect(60, 40, 50, 70))
nb.anchor.setValue(0)  # basso a sinistra
x0, y0, w0, h0 = bounds()
write(P, "200", focus_out=True)
x1, y1, w1, h1 = bounds()
check("punto in basso a sinistra: quell'angolo resta fermo", close(x1, x0) and close(y1, y0) and close(w1, 2 * w0))
nb.anchor.setValue(8)  # alto a destra
x0, y0, w0, h0 = bounds()
write(P, "50", focus_out=True)
x1, y1, w1, h1 = bounds()
check("punto in alto a destra: quell'angolo resta fermo", close(x1 + w1, x0 + w0) and close(y1 + h1, y0 + h0)
      and close(w1, w0 / 2))
nb.anchor.setValue(4)

fresh(rect(80, 20, 150, 150, rot=30))
b0 = bounds()
write(P, "175", focus_out=True)
b1 = bounds()
check("forma ruotata: ingombro × 1,75 e proporzioni uguali", close(b1[2], b0[2] * 1.75, 1e-5)
      and close(b1[3], b0[3] * 1.75, 1e-5) and close(b1[2] / b1[3], b0[2] / b0[3], 1e-9))

a, b, c = rect(20, 20, 10, 10), rect(30, 10, 100, 40), rect(15, 25, 60, 120)
g = GroupShape([rect(10, 10, 200, 200), rect(5, 5, 220, 210)])
fresh(a, b, c, g)
w.acts["select_all"].trigger()
spin(0.05)
b0 = bounds()
centers0 = [s.bounds().center() for s in (a, b, c)]
write(P, "200", focus_out=True)
b1 = bounds()
centers1 = [s.bounds().center() for s in (a, b, c)]
d0 = math.dist((centers0[0].x(), centers0[0].y()), (centers0[1].x(), centers0[1].y()))
d1 = math.dist((centers1[0].x(), centers1[0].y()), (centers1[1].x(), centers1[1].y()))
check("Ctrl+A con più forme e un gruppo: tutto × 2, distanze fra le forme × 2, un passo",
      close(b1[2], 2 * b0[2], 1e-5) and close(b1[3], 2 * b0[3], 1e-5) and close(d1, 2 * d0, 1e-5)
      and len(ed.undo_stack) == 1, (b1[2] / b0[2], d1 / d0, len(ed.undo_stack)))
check("…il gruppo resta un gruppo", isinstance(ed.doc.shapes[-1], GroupShape) and len(ed.doc.shapes) == 4)

# ---------------------------------------------------------------- 6. stessa strada di L con il lucchetto chiuso
def snapshot(shapes):
    out = []
    for s in shapes:
        t = s.tf
        out.append((round(t.m11(), 9), round(t.m12(), 9), round(t.m21(), 9), round(t.m22(), 9), round(t.dx(), 9),
                    round(t.dy(), 9), round(getattr(s, "radius", 0.0), 9)))
    return out


rr = rect(50, 30, 120, 80)
rr.radius = 6.0
pg = rect(20, 40, 40, 60, rot=15)
fresh(rr, pg)
nb.lock.setChecked(True)
write(P, "130")  # solo Invio: con L, uscendo dalla casella, il numero arrotondato a 2 decimali vale come un secondo
via_pct = snapshot([rr, pg])  # passo minuscolo (comportamento di sempre di L, non di questa casella)
ed.undo()
spin(0.05)
rr, pg = ed.doc.shapes  # dopo Annulla le forme sono oggetti nuovi: si rileggono dal progetto
ed.select([rr, pg])
spin(0.05)
write(nb.fw, "*1.3")
via_l = snapshot([rr, pg])
w.canvas.setFocus()
spin(0.05)
check("stesso risultato di L «*1.3» con il lucchetto chiuso (trasformazioni e raggio)", via_pct == via_l,
      (via_pct, via_l))
check("…raggio degli angoli sempre in mm veri: per la casella del raggio resta 6 mm",
      close(nb.shown_radius(rr), 6.0, 1e-6), nb.shown_radius(rr))
nb.lock.setChecked(False)
ed.undo()
spin(0.05)
rr = ed.doc.shapes[0]
ed.select([rr])
spin(0.05)
b0 = bounds()
write(P, "200", focus_out=True)
check("con il lucchetto aperto la percentuale resta uniforme", close(bounds()[2], 2 * b0[2]) and close(bounds()[3], 2 * b0[3]))
nb.lock.setChecked(True)

# ---------------------------------------------------------------- 7. tastiera e rotella non scalano
fresh(rect(40, 30, 100, 100))
b0 = bounds()
P.setFocus()
spin(0.02)
for key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Up):
    QApplication.sendEvent(P, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
    QApplication.sendEvent(P, QKeyEvent(QEvent.KeyPress, key, Qt.ShiftModifier))
pos = QPointF(P.width() / 2, P.height() / 2)
QApplication.sendEvent(P, QWheelEvent(pos, P.mapToGlobal(pos), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                                      Qt.NoModifier, Qt.NoScrollPhase, False))
spin(0.05)
w.canvas.setFocus()
spin(0.05)
check("frecce della tastiera e rotella: nessun cambiamento", bounds() == b0 and not ed.undo_stack and P.text() == "100 %")

# ---------------------------------------------------------------- 8. percentuale anche in L e A, non altrove
fresh(rect(80, 40, 100, 100))
nb.lock.setChecked(True)
b0 = bounds()
write(nb.fw, "150%", focus_out=True)
check("L «150%» = una volta e mezza (con il lucchetto anche l'altezza)", close(bounds()[2], 1.5 * b0[2])
      and close(bounds()[3], 1.5 * b0[3]))
nb.lock.setChecked(False)
b0 = bounds()
write(nb.fh, "50%", focus_out=True)
check("A «50%» con il lucchetto aperto = metà altezza, larghezza uguale", close(bounds()[3], 0.5 * b0[3])
      and close(bounds()[2], b0[2]))
nb.lock.setChecked(True)
b0 = bounds()
write(nb.fx, "50%", focus_out=True)
check("X «50%» non vale (resta un errore come prima)", bounds() == b0)
pw = NumField(80.0, 0, 1.0, " %", 60, 0)
pw.show()
write(pw, "50%")
check("campo potenza (unità « %») «50%»: come prima non vale (resta 80), non diventa il 50 % di 80",
      pw.value() == 80.0, pw.value())
write(pw, "50 %")
check("…e «50 %» vale 50 come prima", pw.value() == 50.0, pw.value())
pw2 = NumField(80.0, 0, 1.0, "", 60, 0)
pw2.show()
write(pw2, "50%")
check("campo senza unità «50%»: errore come prima, il valore non cambia", pw2.value() == 80.0, pw2.value())
pw.hide()
pw2.hide()

ok_eval = (close(evaluate("150%", 80, True), 120) and close(evaluate("+10%", 50, True), 55)
           and close(evaluate("-10%", 50, True), 45) and close(evaluate("10%3"), 1.0)
           and close(evaluate("120/3", 7, True), 40))
try:
    evaluate("50%", 80)
    ok_old = False
except (ValueError, SyntaxError):
    ok_old = True
check("calcoli: «150%», «+10%», «-10%» sul valore attuale; «10%3» resta il resto; senza percentuale come prima",
      ok_eval and ok_old)

# ---------------------------------------------------------------- 9. la barra
fresh(rect(120, 110, 250, 148))
spin(0.2)
if not BANCO:
    check("Classica: la barra sta a 1366 px", nb.sizeHint().width() <= 1366, nb.sizeHint().width())
    w.resize(1100, 800)
    spin(0.3)
    check("Classica, finestra stretta: X, Y, L, A, %, R e rotazione visibili, la finestra non si allarga",
          all(f.isVisible() for f in (nb.fx, nb.fy, nb.fw, nb.fh, P, nb.frad, nb.fr)) and w.width() <= 1100, w.width())
else:
    vis = {}
    for wd, ht in ((1366, 768), (1600, 900), (1920, 1080)):
        w.resize(wd, ht)
        spin(0.5)
        vis[wd] = [n for n, f in (("X", nb.fx), ("Y", nb.fy), ("L", nb.fw), ("A", nb.fh), ("%", P), ("R", nb.frad))
                   if f.isVisible()]
    check("Banco a 1366, 1600 e 1920 px: X, Y, L, A, % e R sempre visibili (fuori dal menu «»»)",
          all(v == ["X", "Y", "L", "A", "%", "R"] for v in vis.values()), vis)
    ext = nb.findChild(QToolButton, "qt_toolbar_ext_button")
    check("Banco a 1920 px: tutta la barra visibile, niente menu «»»", ext is None or not ext.isVisible())

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(code)
