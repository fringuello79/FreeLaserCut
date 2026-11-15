# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.20.3, richieste di Ale (15/11):
- cambiando carattere, mentre scorri l'elenco il testo selezionato si vede sul piano con il carattere su cui sei;
  cambia davvero (un passo solo, annullabile) soltanto quando scegli;
- spaziatura delle lettere (orizzontale) e delle righe (verticale): c'erano già, ma quella delle lettere faceva
  saltare il testo uscendo da 0 con i caratteri a linea singola e spostava i testi centrati o a destra. I testi
  salvati prima con una spaziatura restano identici."""
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
import json
import time

from PySide6.QtGui import QPainterPath, QTransform
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core import text as T
from freelasercut.core.document import Document, TextPathShape, TextShape, shape_from_dict

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def spin(sec=0.05):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def same(a, b, tol=1e-6):
    return a.elementCount() == b.elementCount() and all(
        abs(a.elementAt(i).x - b.elementAt(i).x) < tol and abs(a.elementAt(i).y - b.elementAt(i).y) < tol
        for i in range(a.elementCount()))


from freelasercut.ui import style  # noqa: E402

style.load_fonts()  # come all'avvio: i caratteri che FreeLaserCut porta con sé
_fams = T.system_families()
# Un carattere di sistema, se c'è: sui server Windows senza schermo l'elenco può essere vuoto (visto su GitHub il
# 15/11); allora le prove si fanno con i caratteri a linea singola, che ci sono sempre.
SYS = next((f for f in ("DejaVu Sans", "Arial", "Liberation Sans", "Segoe UI") if f in _fams), _fams[0] if _fams else None)
FONTS = list(T.SINGLE_LINE_FONTS) + ([SYS] if SYS else []) + (["Inter"] if "Inter" in _fams and SYS != "Inter" else [])
ALT = SYS or "timesi"  # secondo carattere per le prove dell'elenco

# ================================================================ A. spaziatura delle lettere (conti)
jump, lin, anchor, one = [], [], [], []
for fam in FONTS:
    for txt in ("Ciao mondo", "AV To", "Wi-Fi 12"):
        n = len(txt) if not T.is_single_line(fam) else sum(1 for ch in txt if ch in T._hershey(fam)[0].all_glyphs)
        for align in ("left", "center", "right"):
            r0 = T.text_path(txt, fam, 10, align=align).boundingRect()
            re = T.text_path(txt, fam, 10, align=align, letter_spacing=1e-6).boundingRect()
            if abs(re.width() - r0.width()) > 1e-3 or abs(re.left() - r0.left()) > 1e-3:
                jump.append((fam, txt, align, round(re.width() - r0.width(), 2)))
            for s in (2.0, -0.5, 0.3):
                rs = T.text_path(txt, fam, 10, align=align, letter_spacing=s).boundingRect()
                if abs(rs.width() - (r0.width() + s * (n - 1))) > 0.02:
                    lin.append((fam, txt, align, s, round(rs.width() - r0.width() - s * (n - 1), 3)))
                fixed = {"left": (rs.left(), r0.left()), "right": (rs.right(), r0.right()),
                         "center": (rs.center().x(), r0.center().x())}[align]
                if abs(fixed[0] - fixed[1]) > 0.02:
                    anchor.append((fam, txt, align, s, round(fixed[0] - fixed[1], 3)))
    for align in ("left", "center", "right"):
        if not same(T.text_path("H", fam, 10, align=align), T.text_path("H", fam, 10, align=align, letter_spacing=4.0)):
            one.append((fam, align))
check("uscendo da 0 il testo non salta (15 caratteri a linea singola" + (" e uno di sistema)" if SYS else ")"), not jump,
      jump[:3])
check("la riga si allunga esattamente di spaziatura × (lettere − 1), anche con valori negativi", not lin, lin[:3])
check("il lato dell'allineamento resta fermo: sinistra, centro, destra", not anchor, anchor[:3])
check("una lettera sola: la spaziatura non la sposta", not one, one[:3])
p2 = T.text_path("AB\nCD", "futural", 10, letter_spacing=1.5, line_spacing=1.0)
p3 = T.text_path("AB\nCD", "futural", 10, letter_spacing=1.5, line_spacing=2.0)
check("spaziatura delle righe: 1 = una volta e mezza l'altezza, 2 = il doppio (la prima riga non si muove)",
      abs((p2.boundingRect().height() - 10) - 15.0) < 0.3 and abs((p3.boundingRect().height() - 10) - 30.0) < 0.3
      and abs(p2.boundingRect().bottom() - p3.boundingRect().bottom()) < 1e-6,
      (round(p2.boundingRect().height(), 2), round(p3.boundingRect().height(), 2)))
check("lettere che il carattere non ha: saltate come prima, senza errori",
      T.text_path("a€b", "futural", 10, letter_spacing=1.0).boundingRect().width() > 0)

# ---------------------------------------------------------------- testi salvati prima: identici
old_d = {"kind": "text", "p": {"text": "Ciao mondo", "family": "scripts", "size": 10, "align": "center", "letter_spacing": 0.8}}
t_old = shape_from_dict(old_d)
t_new = TextShape("Ciao mondo", "scripts", 10, align="center", letter_spacing=0.8)
legacy = T.text_path("Ciao mondo", "scripts", 10, align="center", letter_spacing=0.8, legacy_spacing=True)
check("testo salvato prima con una spaziatura: resta com'era (stesso tracciato)", t_old.spacing_legacy
      and same(t_old.local_path(), legacy) and not same(t_old.local_path(), t_new.local_path()))
check("testo nuovo: spaziatura corretta, e nel file c'è scritto", not t_new.spacing_legacy and t_new.params()["lsv"] == 2
      and t_old.params()["lsv"] == 1)
check("copia, annulla e riapri di un testo vecchio: resta vecchio; di uno nuovo: resta nuovo",
      shape_from_dict(t_old.to_dict()).spacing_legacy and not shape_from_dict(t_new.to_dict()).spacing_legacy
      and same(shape_from_dict(json.loads(json.dumps(t_old.to_dict()))).local_path(), legacy))
z = TextShape("Ciao", "futural", 10)
check("senza spaziatura il file resta com'era (nessun campo in più) e il tracciato è quello di sempre",
      "lsv" not in z.params() and same(shape_from_dict({"kind": "text", "p": {"text": "Ciao", "family": "futural", "size": 10}})
                                       .local_path(), z.local_path()))
t_old.letter_spacing = 0.0
at0 = QPainterPath(t_old.local_path())
t_old.invalidate()
t_old.letter_spacing = 0.8
t_old.invalidate()
check("testo vecchio riportato a 0 e poi di nuovo spaziato: da lì usa la spaziatura corretta (a 0 sono uguali)",
      not t_old.spacing_legacy and same(t_old.local_path(), t_new.local_path())
      and same(at0, T.text_path("Ciao mondo", "scripts", 10, align="center")))
tp = TextPathShape("Ciao mondo", "futural", 8, letter_spacing=1.0,
                   curve=[["M", 0, 0], ["L", 120, 0]] if False else [])
arc0 = TextShape("Ciao mondo", "futural", 8, arc=90).local_path().boundingRect().width()
arc1 = TextShape("Ciao mondo", "futural", 8, arc=90, letter_spacing=1.0).local_path().boundingRect().width()
check("testo curvo e testo su tracciato con la spaziatura: nessun errore, il testo curvo si allarga",
      arc1 > arc0 and tp.local_path() is not None and tp.params().get("lsv") == 2)

# ================================================================ B. pannello: anteprima del carattere e spaziature
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.show()
ed = w.editor
doc = ed.doc
ts = TextShape("Prova FLC", "futural", 12, layer=1)
ts.set_transform(QTransform.fromTranslate(40, 60))
ed.add([ts], "x")
ed.select([ts])
spin(0.2)
props = w.props
fam = props.font_combo
n_undo = len(ed.undo_stack)
orig_path = QPainterPath(ts.path())
live = []
ed.live.connect(lambda: live.append(ts.family))
i_script = fam.findData("scripts")
i_sys = fam.findData(ALT)
check("nel pannello: carattere, spaziatura lettere (mm) e spaziatura righe (×)", fam is not None and i_script > 0 and i_sys > 0
      and props.letter_spin.suffix().strip() == "mm" and props.line_spin.suffix().strip() == "×")
fam.highlighted.emit(i_script)
check("elenco chiuso: passare su una voce non tocca il testo", ts.family == "futural" and not live)
fam.showPopup()
spin()
fam.highlighted.emit(i_script)
spin()
check("elenco aperto, mouse (o frecce) su un carattere: il testo vero sul piano si vede con quel carattere",
      ts.family == "scripts" and live and not same(ts.path(), orig_path))
fam.highlighted.emit(i_sys)
spin()
check("…e segue il mouse da un carattere all'altro", ts.family == ALT and live[-1] == ALT)
header = next(k for k in range(fam.count()) if not fam.itemData(k))
fam.highlighted.emit(header)
check("le intestazioni dell'elenco non sono caratteri: l'anteprima resta sull'ultimo", ts.family == ALT)
check("l'anteprima non entra nella cronologia (niente passi di Annulla)", len(ed.undo_stack) == n_undo)
fam.hidePopup()
spin()
check("elenco chiuso senza scegliere (Esc, clic fuori): il testo torna com'era", ts.family == "futural" and same(ts.path(), orig_path)
      and len(ed.undo_stack) == n_undo and fam.currentData() == "futural")

fam.showPopup()
spin()
fam.highlighted.emit(i_script)
fam.hidePopup()  # come fa Qt quando fai clic su una voce: prima chiude, poi cambia la voce
fam.setCurrentIndex(i_script)
spin(0.2)
ts = ed.selection[0]
check("clic su un carattere: cambia davvero, con un passo solo", ts.family == "scripts" and len(ed.undo_stack) == n_undo + 1)
ed.undo()
spin(0.2)
ts = ed.selection[0] if ed.selection else doc.shapes[-1]
check("Annulla: torna il carattere di prima (non quello dell'anteprima)", ts.family == "futural")
ed.redo()
spin(0.2)
ed.select([doc.shapes[-1]])
spin(0.2)
ts = ed.selection[0]
fam = w.props.font_combo
fam.showPopup()
fam.highlighted.emit(fam.findData("gothiceng"))
check("anteprima su un testo già cambiato", ts.family == "gothiceng")
ed.select([])  # il pannello si rifà con l'elenco ancora aperto (selezione cambiata da un altro comando)
spin(0.3)
check("pannello rifatto con l'elenco aperto: il testo non resta con il carattere dell'anteprima", ts.family == "scripts")

ed.select([doc.shapes[-1]])
spin(0.2)
ts = ed.selection[0]
props = w.props
x_left = ts.path().boundingRect().left()
w0 = ts.path().boundingRect().width()
n0 = len(ed.undo_stack)
props.letter_spin.setValue(1.5)
spin(0.2)
ts = ed.selection[0]
check("spaziatura lettere dal pannello: il testo si allarga di 1,5 mm per lettera, il lato sinistro resta fermo",
      abs(ts.letter_spacing - 1.5) < 1e-9 and abs(ts.path().boundingRect().width() - (w0 + 1.5 * (len("Prova FLC") - 1))) < 0.05
      and abs(ts.path().boundingRect().left() - x_left) < 0.02 and not ts.spacing_legacy,
      round(ts.path().boundingRect().width() - w0, 2))
ed.undo()
spin(0.2)
check("Annulla la spaziatura", abs(ed.selection[0].letter_spacing) < 1e-9 if ed.selection else abs(doc.shapes[-1].letter_spacing) < 1e-9)
ed.select([doc.shapes[-1]])
spin(0.2)
ts = ed.selection[0]
ed.modify(ts, "x", text="Prova\nFLC")
spin(0.2)
ed.select([doc.shapes[-1]])
spin(0.2)
ts = ed.selection[0]
h1 = ts.path().boundingRect().height()
w.props.line_spin.setValue(2.0)
spin(0.2)
ts = ed.selection[0]
check("spaziatura righe dal pannello: da 1 a 2 le righe si allontanano di una volta e mezza l'altezza (18 mm)",
      abs(ts.line_spacing - 2.0) < 1e-9 and abs(ts.path().boundingRect().height() - h1 - 18.0) < 0.3,
      round(ts.path().boundingRect().height() - h1, 2))
path = os.path.join(tempfile.mkdtemp(), "testo.flc")
ed.modify(ts, "x", letter_spacing=0.6)
doc.save(path)
t2 = [s for s in Document.load(path).shapes if isinstance(s, TextShape)][-1]
ts = [s for s in doc.shapes if isinstance(s, TextShape)][-1]
check("salva e riapri: spaziature e tracciato identici", abs(t2.letter_spacing - 0.6) < 1e-9 and abs(t2.line_spacing - 2.0) < 1e-9
      and not t2.spacing_legacy and same(t2.path(), ts.path()))

# ---- con il mouse vero sull'elenco aperto (l'ordine degli eventi è quello di Qt, non quello supposto dalla prova)
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

ed.select([doc.shapes[-1]])
spin(0.2)
ts = ed.selection[0]
start_family = ts.family
fam = w.props.font_combo
n1 = len(ed.undo_stack)
fam.showPopup()
spin(0.2)
view = fam.view()
target = fam.findData("timesr")
idx = fam.model().index(target, 0)
view.scrollTo(idx)
spin(0.1)
c = view.visualRect(idx).center()
QTest.mouseMove(view.viewport(), c + QPoint(2, 0))
QTest.mouseMove(view.viewport(), c)
spin(0.2)
under = fam.itemData(view.indexAt(c).row())  # la voce che sta davvero sotto il mouse (l'elenco può essere scorso)
check("mouse vero sopra una voce dell'elenco aperto: il testo sul piano prende quel carattere, senza passi di Annulla",
      under and under != start_family and ts.family == under and len(ed.undo_stack) == n1, (under, ts.family))
QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, c)
spin(0.3)
ts = ed.selection[0] if ed.selection else doc.shapes[-1]
check("clic vero sulla voce: carattere cambiato con un passo solo", ts.family == under and len(ed.undo_stack) == n1 + 1,
      (ts.family, len(ed.undo_stack) - n1))
ed.undo()
spin(0.2)
check("…e Annulla riporta il carattere di partenza", [s for s in doc.shapes if isinstance(s, TextShape)][-1].family == start_family)
ed.select([doc.shapes[-1]])
spin(0.2)
ts = ed.selection[0]
fam = w.props.font_combo
fam.showPopup()
spin(0.2)
view = fam.view()
idx = fam.model().index(fam.findData("gothiceng"), 0)
view.scrollTo(idx)
spin(0.1)
c = view.visualRect(idx).center()
QTest.mouseMove(view.viewport(), c + QPoint(2, 0))
QTest.mouseMove(view.viewport(), c)
spin(0.2)
under = fam.itemData(view.indexAt(c).row())
seen_family = ts.family
view.window().hide()  # come quando Qt chiude l'elenco da sé (clic fuori dall'elenco): non passa da hidePopup
spin(0.3)
check("elenco chiuso da Qt con un clic fuori: anteprima vista e poi tolta, niente nella cronologia",
      under and seen_family == under != start_family and ts.family == start_family and len(ed.undo_stack) == n1,
      (seen_family, ts.family))
fam.showPopup()
spin(0.2)
fam.highlighted.emit(fam.findData("cursive"))
seen_family = ts.family
QTest.keyClick(fam.view(), Qt.Key_Escape)
spin(0.3)
if fam.view().isVisible():  # senza schermo il tasto può non arrivare all'elenco: allora lo chiude la prova
    fam.hidePopup()
    spin(0.1)
check("Esc con l'elenco aperto: il testo torna com'era", seen_family == "cursive" and ts.family == start_family
      and len(ed.undo_stack) == n1 and not fam.view().isVisible(), (seen_family, ts.family))

# strumento Testo senza un testo selezionato: l'elenco non ha niente da mostrare sul piano e non deve dare errori
ed.select([])
w.tool_actions["text"].trigger()
spin(0.3)
fam = w.props.font_combo
ok = True
try:
    fam.showPopup()
    fam.highlighted.emit(fam.findData("scripts"))
    fam.hidePopup()
    spin()
except Exception as ex:  # noqa: BLE001
    ok = repr(ex)
check("strumento Testo senza testo selezionato: l'elenco si scorre senza errori", ok is True, ok)

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(code)
