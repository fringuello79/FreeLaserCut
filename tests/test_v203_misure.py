# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.20.3, segnalazione di Ale (15/11): nelle caselle X, Y, L, A della barra delle misure, da quando ci sono
le freccette (0.19.6), la prima cifra di un numero a tre cifre usciva tagliata a sinistra («310.33 mm»).
Ora ogni casella è larga quanto serve al numero più lungo che ci si aspetta, con il carattere vero del programma:
- Classica: quattro cifre intere (o tre con il segno); il posto lo cede la scritta del tipo di forma, in fondo;
- Banco: tre cifre intere, e la barra non diventa più larga di prima (etichette e separatori più stretti)."""
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
import time

import numpy as np
from PySide6.QtGui import QFont, QFontMetricsF, QImage, QTransform
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core.document import RectShape
from freelasercut.ui import main_window as M
from freelasercut.ui import style
from freelasercut.ui.widgets import NumField

# lo stile vero del programma (come in main): carattere, misure e margini delle caselle vengono da qui
app.setStyle("Fusion")
style.load_fonts()
app.setFont(style.ui_font(9))
app.setStyleSheet(M.QSS.replace("'Segoe UI', 'Inter'", f"'{style.UI_FONT}', 'Segoe UI'") + style.QSS_EXTRA)

results = []
UI = os.environ["FLC_UI"]
BANCO = UI == "banco"


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def spin(sec=0.1):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def ink(f, text):
    """(prima colonna, larghezza) di quello che si vede del testo dentro la casella (senza la zona delle freccette)."""
    old = f.text()
    f.setText(text)
    spin(0.03)
    im = f.grab().toImage().convertToFormat(QImage.Format_Grayscale8)
    a = np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())[:, :im.width()].astype(int)
    cols = np.nonzero((np.abs(a - int(np.median(a))) > 40)[3:-3, 2:f.width() - f.ARROW_W - 3].any(axis=0))[0]
    f.setText(old)
    return (int(cols.min()) + 2, int(cols.max() - cols.min() + 1)) if len(cols) else (0, 0)


w = M.MainWindow()
w.resize(1500, 900)
w.show()
spin(0.4)
r = RectShape(120, 110)
r.set_transform(QTransform.fromTranslate(250, 148))
w.editor.add([r], "x")
w.editor.select([r])
spin(0.3)
nb = w.numeric
F = {"X": nb.fx, "Y": nb.fy, "L": nb.fw, "A": nb.fh, "R": nb.frad, "rotazione": nb.fr}
BASE = {"X": 76, "Y": 76, "L": 76, "A": 76, "R": 66, "rotazione": 58}  # larghezze fino alla 0.20.2

# riferimento: la stessa casella, larghissima (lì il testo si vede sicuramente intero)
ref = NumField(0.0, 2, 1.0, " mm", 260)
ref.setObjectName("numbar")
ref.setFixedHeight(nb.FIELD_H)
ref.enable_arrows(None)
ref.show()
spin(0.1)


def whole(f, text):
    """Il testo si vede intero? Stessa larghezza d'inchiostro della casella di riferimento, e non parte dal bordo."""
    a, b = ink(f, text), ink(ref, text)
    if b[1] <= 10:  # ambiente che non disegna il testo (server senza schermo): vale il conto con le misure del carattere
        return room(f, text)
    return abs(a[1] - b[1]) <= 1 and a[0] >= 3 and room(f, text)


def room(f, text):
    return f.text_room() >= QFontMetricsF(f.font()).horizontalAdvance(text)


# ---------------------------------------------------------------- il difetto segnalato
cases = ["310.33 mm", "999.99 mm", "120.00 mm", "888.88 mm"]
check("tre cifre («310.33 mm») intere in X, Y, L e A: la prima cifra non è più tagliata",
      all(whole(F[k], t) and room(F[k], t) for k in "XYLA" for t in cases),
      [(k, t, ink(F[k], t), ink(ref, t)) for k in "XYLA" for t in cases if not whole(F[k], t)][:3])
fx = F["X"]
kept, kept_w = fx._fit_samples, fx.width()
fx._fit_samples = ()
fx.setFixedWidth(BASE["X"])  # la casella com'era: 76 px, con le freccette dentro
spin(0.1)
was = whole(fx, "310.33 mm")
info_old = (ink(fx, "310.33 mm"), ink(ref, "310.33 mm"))
fx.fit_text(*kept)
spin(0.1)
check("…con la casella di prima (76 px con le freccette) «310.33 mm» usciva tagliato: la prova riconosce il difetto",
      not was and fx.width() == kept_w and whole(fx, "310.33 mm"), info_old)
check("raggio a due cifre («10.00 mm») e angolo con il segno («-135.00°», «-180.00°») interi",
      whole(F["R"], "10.00 mm") and all(room(F["rotazione"], t) for t in ("-135.00°", "-180.00°", "360.00°")))
if not BANCO:
    check("Classica: anche quattro cifre («1000.00 mm»), tre con il segno («-310.33 mm») e raggio a tre cifre",
          all(whole(F[k], t) for k in "XYLA" for t in ("1000.00 mm", "9999.99 mm"))
          and all(whole(F[k], "-310.33 mm") for k in "XY") and whole(F["R"], "100.00 mm"))
check("nessuna casella più stretta di prima", all(F[k].width() >= BASE[k] for k in F), {k: F[k].width() for k in F})
check("allargate di poco (al massimo 20 px l'una)", all(F[k].width() - BASE[k] <= 20 for k in F),
      {k: F[k].width() - BASE[k] for k in F})
check("il testo non finisce sotto le freccette e le freccette funzionano ancora",
      all(f.textMargins().right() >= f.ARROW_W for f in F.values()) and F["L"]._arrow_at(
          __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(F["L"].width() - 3, 3)) == 1)
x0 = w.editor.selection_bounds().width()
F["L"].nudge(1)
spin(0.1)
check("un clic sulla freccetta cambia ancora la misura di 0,1 mm", abs(w.editor.selection_bounds().width() - x0 - 0.1) < 1e-6)

# ---------------------------------------------------------------- il carattere cambia: la casella lo segue
f = NumField(0.0, 2, 1.0, " mm", 76)
f.enable_arrows(None)
f.fit_text("8888.88 mm")
f.show()
spin(0.05)
w_norm = f.width()
big = QFont(f.font())
big.setPointSizeF(f.font().pointSizeF() * 1.5)
f.setFont(big)
spin(0.05)
check("carattere più grande (altro tema, altro sistema): la casella si allarga da sola e il numero resta intero",
      f.width() > w_norm and room(f, "1000.00 mm"), (w_norm, f.width()))
tiny = QFont(f.font())
tiny.setPointSizeF(4.0)
f.setFont(tiny)
spin(0.05)
check("carattere piccolissimo: mai più stretta della sua misura di partenza", f.width() == 76, f.width())
g = NumField(0.0, 2, 1.0, " mm", 76)
check("le caselle delle altre finestre (senza misura chiesta) restano come sono", g.width() == 76)

# ---------------------------------------------------------------- la barra
hint = nb.sizeHint().width()
if not BANCO:
    check("Classica: la barra delle misure sta nella finestra a 1500 e a 1366 px", hint <= 1366, hint)
    w.resize(1100, 800)
    spin(0.3)
    acts = [nb.widgetForAction(a) for a in nb.actions()]
    vis = [x for x in acts if x is not None and x.isVisible()]
    check("finestra stretta: il posto lo cede la scritta del tipo di forma (in fondo), le caselle restano intere",
          all(F[k].isVisible() and F[k].width() >= BASE[k] for k in F) and nb.layer_combo.isVisible(),
          (nb.info.isVisible(), nb.info.width()))
    check("…e la finestra non si allarga per fare posto alla barra", w.width() <= 1100, w.width())
else:
    def through_r():
        """Posto che serve fino alla casella R compresa (quello che decide cosa finisce nel menu «»»)."""
        tot = 0
        for a in nb.actions():
            x = nb.widgetForAction(a)
            if x is None:
                continue
            tot += x.sizeHint().width() if x.maximumWidth() > 5000 else x.width()
            if x is nb.frad:
                break
        return tot

    new_hint, new_r, new_css = hint, through_r(), nb.styleSheet()
    # la barra com'era nella 0.20.2, rifatta qui (così il confronto vale con qualsiasi carattere)
    nb.setStyleSheet("QToolBar { background: transparent; border: none; } QLabel#numlabel { color: #C3CEE3; }")
    for lab in nb.findChildren(QLabel):
        if lab.objectName() == "numlabel":
            lab.setIndent(-1)
    keep = {k: (F[k]._fit_samples, F[k].width()) for k in F}
    for k in F:
        F[k]._fit_samples = ()
        F[k].setFixedWidth(BASE[k])
    spin(0.3)
    old_hint, old_r = nb.sizeHint().width(), through_r()
    nb.setStyleSheet(new_css)
    for k in F:
        F[k]._fit_samples = keep[k][0]
    nb.set_compact(True)
    spin(0.3)
    check("Banco: rimessa com'è ora, le caselle tornano alla misura giusta", all(F[k].width() == keep[k][1] for k in F),
          {k: F[k].width() for k in F})
    check("Banco: la barra non è più larga di quella della 0.20.2 (niente in più nel menu «»»)",
          new_hint <= old_hint and nb.sizeHint().width() == new_hint, (new_hint, old_hint))
    check("Banco: fino alla casella R serve lo stesso posto di prima (o meno)", new_r <= old_r, (new_r, old_r))
    labs = [x for x in nb.findChildren(QLabel) if x.objectName() == "numlabel" and x.text() in ("X", "Y", "L", "A", "R")]
    check("Banco: le lettere X, Y, L, A, R restano staccate dalle caselle (almeno 5 px in più del testo)",
          len(labs) == 5 and all(x.sizeHint().width() >= QFontMetricsF(x.font()).horizontalAdvance(x.text()) + 5
                                 for x in labs), [x.sizeHint().width() for x in labs])

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(code)
