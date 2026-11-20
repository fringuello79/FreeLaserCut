# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.21.1: il grigio di una forma si sceglie dentro FreeLaserCut (France_o: «la tonalità di grigio non si può
selezionare da dentro FLC vero?»). Dalla 0.20.7 il grigio arrivava solo dai riempimenti dei file SVG; ora nel pannello
Proprietà c'è la riga «Grigio» (0% nero … 100% bianco) per le forme su un livello in Riempimento, anche su più forme
insieme, con il tono e la potenza che ne viene. Il primo grigio accende «Potenza dal grigio» sul livello.
Uso: python tests/test_v211_grigio.py [banco]
"""
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
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QSpinBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import Document, ImageShape, RectShape, gray_power  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


w = MainWindow()
w.resize(1500, 950)
w.show()
spin(0.3)
ed = w.editor
doc = Document()
doc.layer(0).mode = "fill"
doc.layer(0).power_max, doc.layer(0).power_min = 60.0, 20.0
doc.layer(1).mode = "line"
r1 = RectShape(20, 20, layer=0)
r2 = RectShape(20, 20, layer=0)
r2.set_transform(QTransform.fromTranslate(40, 0))
ln = RectShape(20, 20, layer=1)
ln.set_transform(QTransform.fromTranslate(80, 0))
doc.images["p"] = Image.fromarray(np.full((20, 20), 90, np.uint8))
im = ImageShape("p", 20, 20, layer=2)
im.set_transform(QTransform.fromTranslate(0, 60))
for s in (r1, r2, ln, im):
    doc.add(s)
ed.set_document(doc)

# ---- A. l'editor
check("forme a cui si dà il grigio: solo quelle su un livello in Riempimento (non linee, non foto)",
      ed.gray_targets([r1, r2, ln, im]) == [r1, r2])
check("all'inizio nessun grigio e «Potenza dal grigio» spenta", r1.gray is None and doc.layer(0).gray_power is False)
turned = ed.set_gray(128, [r1])
check("grigio 128 a una forma: dato, e «Potenza dal grigio» si accende sul livello", r1.gray == 128 and r2.gray is None
      and doc.layer(0).gray_power is True and turned == [0], (r1.gray, turned))
ed.undo()
r1 = ed.doc.shapes[0]
check("Annulla: tolti in un colpo solo il grigio e l'opzione del livello", r1.gray is None and ed.doc.layer(0).gray_power is False)
ed.redo()
r1, r2 = ed.doc.shapes[0], ed.doc.shapes[1]
check("Ripeti: di nuovo grigio e opzione", r1.gray == 128 and ed.doc.layer(0).gray_power is True)
check("valori fuori misura: limitati a 0–255, «nessuno» toglie il grigio",
      (ed.set_gray(400, [r2]), r2.gray)[1] == 255 and (ed.set_gray(-5, [r2]), r2.gray)[1] == 0
      and (ed.set_gray(None, [r2]), r2.gray)[1] is None)
check("su una linea o una foto non fa niente", ed.set_gray(50, [ed.doc.shapes[2], ed.doc.shapes[3]]) == []
      and ed.doc.shapes[2].gray is None)
ed.select([ed.doc.shapes[0], ed.doc.shapes[1]])
ed.group()
g = ed.selection[0]
check("dentro un gruppo: le forme del gruppo prendono il grigio", ed.gray_targets([g]) and ed.set_gray(64, [g]) == []
      and all(leaf.gray == 64 for leaf, _ in g.leaves()))
ed.ungroup()
r1, r2 = [s for s in ed.doc.shapes if isinstance(s, RectShape) and s.layer == 0]

# ---- B. G-code: la potenza segue il grigio scelto
ed.set_gray(0, [r1])
ed.set_gray(191, [r2])
prof = MachineProfile()
job = gcode.generate(ed.doc, prof)
svals = {round(float(v) / prof.s_max * 100, 1) for v in re.findall(r"\bS(\d+(?:\.\d+)?)", "\n".join(job.lines))}
want = {round(gray_power(ed.doc.layer(0), 0), 1), round(gray_power(ed.doc.layer(0), 191), 1)}
check("G-code: nero alla potenza massima (60%), il grigio 191 in proporzione", want <= svals and 60.0 in want,
      (sorted(svals), want))
ed.set_gray(255, [r2])
job = gcode.generate(ed.doc, prof)
st = next(s for s in job.layers if s.index == 0)
check("…e una forma bianca non si incide (un tono solo, quello nero)", st.tones == 1, st.tones)

# ---- C. il pannello Proprietà
props = w.props
ed.select([r1])
spin(0.1)
props.rebuild()
labels = [l.text() for l in props.host.findChildren(QLabel)]
sp = getattr(props, "gray_spin", None)
check("una forma sul livello in Riempimento: riga «Grigio» nel pannello", sp is not None and "Grigio" in labels
      and not sp.isHidden(), labels[:20])
check("…mostra il grigio della forma (nero = 0%) e la potenza", sp.value() == 0
      and any("potenza 60%" in t for t in labels), [t for t in labels if "potenza" in t])
sp.setValue(50)
spin(0.05)
check("cambiato a 50%: subito sulla forma (grigio 128)", r1.gray == 128, r1.gray)
labels = [l.text() for l in props.host.findChildren(QLabel)]
check("…la potenza scritta accanto segue (40%)", any("potenza 40%" in t for t in labels),
      [t for t in labels if "potenza" in t])
spin(0.9)  # il passo di Annulla si chiude dopo la pausa nella scrittura
n_undo = len(ed.undo_stack)
sp.setValue(60)
sp.setValue(70)
spin(0.9)
check("più scatti di fila: un solo passo di Annulla", len(ed.undo_stack) == n_undo + 1, len(ed.undo_stack) - n_undo)
ed.undo()
r1 = next(s for s in ed.doc.shapes if s.id == r1.id)
check("…e Annulla torna al 50%", r1.gray == 128, r1.gray)
ed.select([r1])
props.rebuild()
sp = props.gray_spin
sp.setValue(100)
spin(0.9)
labels = [l.text() for l in props.host.findChildren(QLabel)]
check("100%: bianco, «non si incide»", r1.gray == 255 and any("non si incide" in t for t in labels))
sp.setValue(-1)
spin(0.9)
check("«nessuno»: grigio tolto (Potenza massima)", r1.gray is None and sp.text().startswith("nessuno"), sp.text())
# più forme insieme, con grigi diversi
r1, r2 = [s for s in ed.doc.shapes if isinstance(s, RectShape) and s.layer == 0]
ed.set_gray(10, [r1])
ed.set_gray(200, [r2])
ed.select([r1, r2])
spin(0.1)
props.rebuild()
sp = props.gray_spin
check("due forme con grigi diversi: la riga c'è e dice «diversi»", sp is not None and sp.value() == -1
      and sp.text().startswith("diversi"), sp.text() if sp else None)
sp.setValue(30)
spin(0.9)
check("…un valore dato a tutte e due", r1.gray == r2.gray == 77, (r1.gray, r2.gray))
# forme dove la riga non deve esserci
props.gray_spin = None
ed.select([next(s for s in ed.doc.shapes if s.layer == 1)])
props.rebuild()
check("forma su un livello Linea: nessuna riga «Grigio»", props.gray_spin is None)
ed.select([next(s for s in ed.doc.shapes if isinstance(s, ImageShape))])
props.rebuild()
check("foto: nessuna riga «Grigio»", props.gray_spin is None)
sp_types = [type(x) for x in props.host.findChildren(QSpinBox)]
check("(il pannello resta quello di sempre)", isinstance(sp_types, list))

# ---- D. salvataggio
path = os.path.join(tempfile.mkdtemp(), "grigi.flcut")
r1, r2 = [s for s in ed.doc.shapes if isinstance(s, RectShape) and s.layer == 0]
ed.set_gray(140, [r1])
ed.doc.save(path)
d2 = Document.load(path)
gs = sorted(s.gray for s in d2.shapes if isinstance(s, RectShape) and s.layer == 0)
check("salvato e riaperto: grigi e «Potenza dal grigio» restano", gs == [77, 140] and d2.layer(0).gray_power is True, gs)

w.editor.dirty = False
w.close()
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
