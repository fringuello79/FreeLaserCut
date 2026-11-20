# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.21.1: «Prepara foto» anche sulla foto ritagliata con una forma, da tutte le parti (France_o: «quando
ritagli una foto dal menù principale, poi non si può più entrare nel menù prepara foto»; Ale: «pensavo di averlo risolto
ma l'ho fatto solo da una parte»). La foto ritagliata è un gruppo (foto + sagoma): dalla 0.20.3 il comando del menu in
alto la riconosceva, il tasto destro e il pannello Proprietà no.
Uso: python tests/test_v211_foto.py [banco]
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
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core import ops  # noqa: E402
from freelasercut.core.document import Document, ImageShape, RectShape, SpecialShape  # noqa: E402
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
doc.images["p"] = Image.fromarray(np.full((150, 200), 90, np.uint8))
im = ImageShape("p", 40, 30, layer=2)
im.set_transform(QTransform.fromTranslate(50, 50))
doc.add(im)
doc.layer(2).mode = "image"
hs = SpecialShape("heart", 20, 20, layer=1)
c = im.path().boundingRect().center()
hs.set_transform(QTransform.fromTranslate(c.x() - 10, c.y() - 10))
doc.add(hs)
ed.set_document(doc)
ed.select([im, hs])
spin(0.05)
check("ritaglio della foto con la forma", ed.clip_photo())
g = doc.shapes[0]
check("…è un gruppo foto + sagoma", ops.is_clip_group(g))
ed.select([g])
spin(0.1)
w._update_sel_actions()
check("menu in alto: «Prepara foto» attivo (com'era dalla 0.20.3)", w.acts["photo"].isEnabled())
keys = w.context_menu_keys()
check("tasto destro sulla foto ritagliata: c'è «Prepara foto» (prima no)", "photo" in keys, keys[:10])
check("…e niente «Vettorizza» (vale solo sulla foto intera)", "trace" not in keys)
props = getattr(w, "props", None)
if props is not None:
    props.rebuild()
    spin(0.05)
    btns = [b for b in props.host.findChildren(QPushButton) if b.text() == "Prepara foto…" and b.isVisibleTo(props.host)]
    check("pannello Proprietà della foto ritagliata: c'è il pulsante «Prepara foto…» (prima no)", len(btns) == 1,
          len(btns))
    got = []
    props.photo_requested.disconnect(w.photo_dialog)  # la finestra vera è modale: qui basta sapere che viene chiesta
    props.photo_requested.connect(lambda: got.append(1))
    if btns:
        btns[0].click()
    check("…e apre Prepara foto come il menu in alto", got == [1])
# un gruppo qualsiasi non ha il pulsante, una foto intera ce l'ha come prima
r1, r2 = RectShape(10, 10), RectShape(10, 10)
r2.set_transform(QTransform.fromTranslate(150, 150))
r1.set_transform(QTransform.fromTranslate(130, 130))
ed.add([r1, r2], "prova")
ed.select([r1, r2])
ed.group()
gg = ed.selection[0]
ed.select([gg])
spin(0.05)
check("gruppo normale: nessun «Prepara foto» nel tasto destro", "photo" not in w.context_menu_keys())
if props is not None:
    props.rebuild()
    btns = [b for b in props.host.findChildren(QPushButton) if b.text() == "Prepara foto…" and b.isVisibleTo(props.host)]
    check("…né nel pannello Proprietà", not btns)
ed.select([g])
ed.unclip_photo()
foto = next(s for s in doc.shapes if isinstance(s, ImageShape))
ed.select([foto])
spin(0.05)
k2 = w.context_menu_keys()
check("foto intera: «Prepara foto» e «Vettorizza» nel tasto destro come prima", "photo" in k2 and "trace" in k2)

w.editor.dirty = False
w.close()
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
