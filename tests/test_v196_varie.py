# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.19.6: piccole cose.

- DXF scritti male con valori numerici vuoti (codice 62 del colore, codice 10 di una coordinata): si importano con un
  avviso; un DXF sano resta identico byte per byte.
- Freccette nei campi X, Y, L, A, R e rotazione della barra numerica: clic = passo (0,1), Maiusc = ×10, tenendo
  premuto ripete, minimo rispettato, testo non sotto le freccette, passo nelle Preferenze, barra non più larga.
- Ogni piano di lavoro ricorda la sua vista; «Sposta la selezione su un altro piano» anche nel tasto destro.
- G-code salvato con il fine riga di Windows (CRLF) a scelta, nelle Preferenze.
Uso: python tests/test_v196_varie.py [banco]
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

import ezdxf

import freelasercut
from freelasercut.core import gcode, io_formats
from freelasercut.core.document import Document, RectShape
from freelasercut.updater import parse_version
from freelasercut.ui.main_window import MainWindow

UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


check("versione 0.19.6 o successiva", parse_version(freelasercut.__version__) >= (0, 19, 6), freelasercut.__version__)

# ================================================================ DXF con valori vuoti
tmpd = tempfile.mkdtemp()
good = os.path.join(tmpd, "sano.dxf")
d = ezdxf.new()
msp = d.modelspace()
msp.add_line((0, 0), (40, 0), dxfattribs={"color": 1})
msp.add_circle((20, 20), 10, dxfattribs={"color": 3})
d.saveas(good)
raw = open(good, "rb").read()
clean, n = io_formats.clean_dxf_bytes(raw)
check("DXF sano: la pulizia non tocca niente (identico byte per byte)", clean == raw and n == 0)
check("DXF sano: si importa come prima, senza avviso", len(io_formats.import_dxf(good, Document())) == 1
      and io_formats.LAST_NOTE == "")


def broken(name, edit):
    text = raw.decode("utf-8")
    text = edit(text)
    p = os.path.join(tmpd, name)
    open(p, "w", encoding="utf-8", newline="").write(text)
    return p


nl = "\r\n" if "\r\n" in raw.decode("utf-8") else "\n"


def blank_after(t, code, start_marker):
    """Svuota il primo valore del codice `code` dopo `start_marker` (la riga del valore resta, vuota)."""
    i = t.index(start_marker)
    tag = f"{nl}{code:>3}{nl}"
    j = t.index(tag, i) + len(tag)
    k = t.index(nl, j)
    return t[:j] + t[k:]


ent = f"{nl}ENTITIES{nl}"
for name, code, marker, what in (("colore-vuoto.dxf", 62, ent, "il colore della linea (62)"),
                                 ("intestazione-vuota.dxf", 62, "$INTERFERECOLOR", "un colore nell'intestazione (62)"),
                                 ("coordinata-vuota.dxf", 10, "AcDbLine", "una coordinata (10)")):
    bad = broken(name, lambda t, c=code, m=marker: blank_after(t, c, m))
    try:
        ezdxf.readfile(bad)
        plain_fails = False
    except ezdxf.DXFStructureError:
        plain_fails = True
    shapes = io_formats.import_dxf(bad, Document())
    leaves = [s for g in shapes for s, _ in g.leaves()]
    check(f"DXF con {what} vuoto: prima l'errore «Invalid tag», ora importato (linea e cerchio) con l'avviso",
          plain_fails and len(leaves) == 2 and "1 valori vuoti" in io_formats.LAST_NOTE,
          (plain_fails, len(leaves), io_formats.LAST_NOTE))
garbage = os.path.join(tmpd, "rotto.dxf")
open(garbage, "w").write("0\nSECTION\n2\nENTITIES\nquesto non è un dxf\n")
try:
    io_formats.import_dxf(garbage, Document())
    ok = True
except Exception as exc:  # noqa: BLE001
    ok = bool(str(exc))
check("file che non è un DXF: errore chiaro, nessun blocco", ok)

# ================================================================ G-code CRLF
p = os.path.join(tmpd, "lavoro.gcode")
gcode.write_file(p, ["G21", "G90", "M5"])
check("G-code di sempre: fine riga \\n", open(p, "rb").read() == b"G21\nG90\nM5\n")
gcode.write_file(p, ["G21", "G90", "M5"], crlf=True)
check("G-code con CRLF: fine riga \\r\\n, nessuna riga vuota in più", open(p, "rb").read() == b"G21\r\nG90\r\nM5\r\n")

# ================================================================ nella finestra
w = MainWindow()
w.resize(1500, 950)
w.show()
spin(0.8)
ed, cv = w.editor, w.canvas
check("G-code CRLF: nelle Preferenze, spento di partenza", "gcode_crlf" in w.acts and not w.acts["gcode_crlf"].isChecked())
w.acts["gcode_crlf"].trigger()
check("…la scelta si ricorda", w.acts["gcode_crlf"].isChecked() and w.qs.value("gcode_crlf") in (True, "true"))
w.acts["gcode_crlf"].trigger()
from freelasercut.ui.dialogs_prefs import PreferencesDialog  # noqa: E402

pd = PreferencesDialog(w)
texts = " ".join(t for _k, _w, t in pd._rows)
check("Preferenze: CRLF e passo delle freccette si trovano (anche con la ricerca)", "crlf" in texts
      and "freccette" in texts and pd.arrow_step_box.value() == 0.1, texts[-200:])

# ---- freccette nei campi
nb = w.numeric
fields = {"X": nb.fx, "Y": nb.fy, "L": nb.fw, "A": nb.fh, "R": nb.frad, "rotazione": nb.fr}
check("freccette in tutti e sei i campi della barra", all(getattr(f, "_arrows", False) for f in fields.values()))
check("…il testo non finisce sotto le freccette (margine a destra)", all(f.textMargins().right() >= f.ARROW_W
                                                                        for f in fields.values()))
check("…stessa altezza di prima (18 px)", all(f.height() == nb.FIELD_H for f in fields.values()))
from freelasercut.ui.widgets import NumField  # noqa: E402

plain = NumField()
check("i campi fuori dalla barra numerica (pannello Macchina) restano senza freccette", not getattr(plain, "_arrows", False)
      and not getattr(w.move.gx, "_arrows", False))
R = RectShape(20, 10)
ed.add([R], "prova")
ed.select([R])
spin(0.2)
f = nb.fw


def click_arrow(field, up=True, mods=Qt.NoModifier, hold=0.0):
    pt = QPointF(field.width() - 4, field.height() * (0.25 if up else 0.75))
    vp = field
    QApplication.sendEvent(vp, QMouseEvent(QEvent.MouseButtonPress, pt, vp.mapToGlobal(pt), Qt.LeftButton,
                                           Qt.LeftButton, mods))
    spin(hold or 0.02)
    QApplication.sendEvent(vp, QMouseEvent(QEvent.MouseButtonRelease, pt, vp.mapToGlobal(pt), Qt.LeftButton,
                                           Qt.NoButton, mods))
    spin(0.05)


w0 = ed.selection_bounds().width()
click_arrow(f, True)
check("clic sulla freccetta su della L: +0,1 mm sulla forma", abs(ed.selection_bounds().width() - (w0 + 0.1)) < 1e-6,
      ed.selection_bounds().width())
click_arrow(f, False)
check("…giù: −0,1 mm", abs(ed.selection_bounds().width() - w0) < 1e-6, ed.selection_bounds().width())
click_arrow(f, True, Qt.ShiftModifier)
check("…con Maiusc: +1 mm", abs(ed.selection_bounds().width() - (w0 + 1)) < 1e-6, ed.selection_bounds().width())
x0 = ed.selection_bounds().left()
click_arrow(nb.fx, True)
check("X: +0,1 mm (la forma si sposta)", abs(ed.selection_bounds().left() - (x0 + 0.1)) < 1e-6)
before = nb.fr.value()
click_arrow(nb.fr, True)
check("rotazione: +0,1°", abs(nb.fr.value() - (before + 0.1)) < 1e-9, nb.fr.value())
v0 = f.value()
click_arrow(f, True, hold=1.0)
check("tenendo premuto la freccetta ripete (più di 5 passi in un secondo)", f.value() - v0 > 0.5, f.value() - v0)
fmin = NumField(0.05, minimum=0.001)
fmin.resize(76, 18)
fmin.enable_arrows()
click_arrow(fmin, False)
click_arrow(fmin, False)
check("il minimo resta rispettato (L e A mai sotto 0,001)", abs(fmin.value() - 0.001) < 1e-12, fmin.value())
w.qs.setValue("num_arrow_step", 0.5)
w.qs.sync()
v0 = f.value()
click_arrow(f, True)
check("passo dalle Preferenze (0,5)", abs(f.value() - (v0 + 0.5)) < 1e-9, f.value() - v0)
w.qs.setValue("num_arrow_step", 0.1)
w.qs.sync()
n_undo = len(ed.undo_stack)
click_arrow(f, True)
check("ogni clic è un passo che si annulla", len(ed.undo_stack) == n_undo + 1)
f.setFocus()
f.setText("30")
click_arrow(f, True)
check("un numero scritto e non confermato vale come partenza (30 → 30,1)", abs(f.value() - 30.1) < 1e-9, f.value())
pos = QPointF(f.width() - 4, 4)
QApplication.sendEvent(f, QMouseEvent(QEvent.MouseMove, pos, f.mapToGlobal(pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
check("passando sopra la freccetta si accende (e il cursore diventa la freccia)", f._hover == 1
      and f.cursor().shape() == Qt.ArrowCursor)
check("la barra numerica sta nella finestra (non va a capo)", nb.sizeHint().width() <= w.width(), nb.sizeHint().width())

# ---- piani: vista e menu
ed.add_plate()
spin(0.2)
check("due piani", len(ed.doc.plates) == 2 and ed.doc.current == 1)
cv.zoom_by(3.0)
spin(0.1)
z1 = cv.scale_px()
h1 = cv.horizontalScrollBar().value()
ed.set_plate(0)
spin(0.1)
z0 = cv.scale_px()
cv.zoom_by(0.5)
spin(0.1)
z0b = cv.scale_px()
ed.set_plate(1)
spin(0.1)
check("tornando al piano 2 la vista è la sua (zoom e posizione)", abs(cv.scale_px() - z1) < 1e-9
      and cv.horizontalScrollBar().value() == h1, (cv.scale_px(), z1))
ed.set_plate(0)
spin(0.1)
check("…e il piano 1 la sua", abs(cv.scale_px() - z0b) < 1e-9, (cv.scale_px(), z0b))
S = RectShape(5, 5)
ed.add([S], "prova")
ed.select([S])
keys = w.context_menu_keys()
check("tasto destro con due piani: «Sposta su un altro piano»", "plate_move" in keys, keys)
if UI != "banco":
    vc = cv.to_view(S.bounds().center())  # tasto destro sopra la forma selezionata
    m = w.open_context_menu(vc, vc.toPoint())
    spin(0.1)
    sub = [a for a in m.actions() if a.text() == w.m_plate_move.title()]
    check("…è il sottomenu dei piani, con il piano 2", len(sub) == 1 and any("2" in a.text() for a in w.m_plate_move.actions()),
          [a.text() for a in w.m_plate_move.actions()])
    m.close()
ed.select([])
check("senza selezione: niente voce", "plate_move" not in w.context_menu_keys())

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
