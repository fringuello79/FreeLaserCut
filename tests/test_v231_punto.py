# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.1 (Evoluzione2, 25/11/2026): con una foto nel disegno, ogni clic sui 9 pallini del punto di partenza
faceva comparire per qualche secondo «Preparo il lavoro…». Il clic rifaceva tutto il lavoro solo per l'anteprima.

Con la partenza dal disegno («absolute») il punto scelto non cambia il lavoro: serve al rombo sul piano e a «Porta la
testa sul punto». Ora si sposta solo il rombo. Con la partenza dalla testa o dall'origine utente, con il rotativo e
quando cambia la partenza, il lavoro si rifà come prima (lì il punto sposta davvero il lavoro).
Uso: python tests/test_v231_punto.py [banco]
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
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QPainterPath  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.core.document import PathShape  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


w = MainWindow()
p = QPainterPath()
p.addRect(QRectF(40, 30, 60, 20))
w.editor.add([PathShape(p, layer=0)], "prova")
builds = []
real_build = w.build_job


def counting_build(*a, **k):
    builds.append(w.laser.start_from.currentData())
    return real_build(*a, **k)


w.build_job = counting_build


def settle():
    QTest.qWait(400)


def pick(i):
    w.laser.anchor.setValue(i)
    w.laser.anchor.changed.emit(i)


def set_start(mode):
    i = w.laser.start_from.findData(mode)
    w.laser.start_from.setCurrentIndex(i)


set_start("absolute")
settle()
builds.clear()
pick(8)
settle()
m = w.canvas.anchor_marker()
check("partenza dal disegno: un clic sui pallini non rifà il lavoro", builds == [], builds)
check("…il rombo va sul punto scelto (in alto a destra del disegno)", m is not None
      and abs(m.x() - 100) < 1e-6 and abs(m.y() - 50) < 1e-6, m)
pick(0)
pick(4)
settle()
m = w.canvas.anchor_marker()
check("due clic di fila: niente lavoro, il rombo segue l'ultimo (al centro)", builds == [] and m is not None
      and abs(m.x() - 70) < 1e-6 and abs(m.y() - 40) < 1e-6, (builds, m))
# la partenza cambiata e poi un pallino, prima che scatti il timer: il lavoro si rifà
set_start("origin")
pick(2)
settle()
check("partenza cambiata e subito un pallino: il lavoro si rifà (una volta)", builds == ["origin"], builds)
builds.clear()
pick(6)
settle()
check("partenza dall'origine utente: il pallino sposta il lavoro, si rifà come prima", builds == ["origin"], builds)
builds.clear()
set_start("absolute")
settle()
check("tornando alla partenza dal disegno il lavoro si rifà", builds == ["absolute"], builds)
builds.clear()
set_start("origin")
settle()
builds.clear()
set_start("absolute")
pick(3)
settle()
check("tornando alla partenza dal disegno e subito un pallino: il lavoro si rifà", builds == ["absolute"], builds)
builds.clear()
w.qs.setValue("rotary_on", "true")
pick(1)
settle()
check("con il rotativo (si scala attorno al punto scelto) il pallino rifà il lavoro", builds == ["absolute"], builds)
w.qs.setValue("rotary_on", "false")
w.editor.dirty = False
w.close()
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
