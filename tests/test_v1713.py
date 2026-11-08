# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.13: raccordo anche su un angolo solo.

- Rettangolo: «Ogni angolo a parte» nelle Proprietà, un raggio per ogni angolo (0 = spigolo vivo).
- Qualsiasi forma: strumento Nodi, tasto A su un nodo = arrotonda quello spigolo (tra due tratti dritti).
"""
import math
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
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath, QTransform
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

import freelasercut
from freelasercut.core import nodes as N
from freelasercut.core.document import PathShape, RectShape, shape_from_dict
from freelasercut.updater import parse_version

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def spin(n=5):
    for _ in range(n):
        app.processEvents()


check("versione 0.17.13 o successiva", parse_version(freelasercut.__version__) >= (0, 17, 13), freelasercut.__version__)

# ---------------------------------------------------------------- rettangolo, un raggio per angolo
r = RectShape(40, 20, radii=[0, 6, 0, 0])  # solo ↗
p = r.local_path()
inside = lambda x, y: p.contains(QPointF(x, y))  # noqa: E731
check("solo l'angolo in alto a destra arrotondato (sul piano Y va verso l'alto)",
      not inside(39.7, 19.7) and inside(0.3, 19.7) and inside(39.7, 0.3) and inside(0.3, 0.3))
area = sum(1 for i in range(400) for j in range(200) if inside(i / 10 + 0.05, j / 10 + 0.05)) / 100
want = 40 * 20 - (36 - math.pi * 9)
check("area giusta: tolto solo un quarto di spigolo di raggio 6", abs(area - want) < 1.0, (area, want))
check("ingombro invariato", p.boundingRect().width() == 40 and p.boundingRect().height() == 20)
check("raggi più grandi della metà del lato corto: limitati", RectShape(40, 20, radii=[50, 0, 0, 0]).corner_radii()[0] == 10)
old = RectShape(30, 20, 4)
q = QPainterPath()
from PySide6.QtCore import QRectF

q.addRoundedRect(QRectF(0, 0, 30, 20), 4, 4)
check("senza raggi per angolo: stesso tracciato di prima (progetti già salvati uguali)",
      old.radii is None and old.local_path() == q)
d = r.to_dict()
r2 = shape_from_dict(d)
check("salvato e riaperto: i quattro raggi restano", r2.radii == [0, 6, 0, 0] and d["p"]["radii"] == [0, 6, 0, 0], d["p"])
d_old = RectShape(10, 10, 2).to_dict()
check("progetti di prima (senza «radii»): tutti gli angoli uguali", "radii" not in d_old["p"]
      and shape_from_dict(d_old).radii is None)

# ---------------------------------------------------------------- nelle Proprietà
from freelasercut.ui.main_window import MainWindow

w = MainWindow()
w.show()
ed = w.editor
rect = RectShape(40, 20, 3.0, layer=1)
rect.apply(QTransform.fromTranslate(50, 50))
ed.add([rect], "x")
ed.select([rect])
spin()
pp = w.props
check("Proprietà del rettangolo: «Ogni angolo a parte» spento di partenza", hasattr(pp, "corner_each")
      and not pp.corner_each.isChecked())
pp.corner_each.setChecked(True)
spin()
cur = ed.doc.shapes[-1]
check("acceso: quattro raggi uguali al raggio di prima", cur.radii == [3.0, 3.0, 3.0, 3.0], cur.radii)
pp = w.props
pp.corner_spins[0].setValue(0.0)  # ↖ vivo
spin()
pp = w.props
pp.corner_spins[3].setValue(0.0)  # ↙ vivo
spin()
cur = ed.doc.shapes[-1]
check("due angoli vivi e due arrotondati", cur.radii == [0.0, 3.0, 3.0, 0.0], cur.radii)
ed.undo()
spin()
check("annulla: torna il raggio dell'angolo di prima", ed.doc.shapes[-1].radii == [3.0, 3.0, 3.0, 0.0] or
      ed.doc.shapes[-1].radii == [0.0, 3.0, 3.0, 3.0], ed.doc.shapes[-1].radii)

# ---------------------------------------------------------------- strumento Nodi, tasto A
sq = N.from_path(RectShape(20, 20).local_path())[0]
n0 = len(sq.nodes)
why = N.fillet(sq, 2, 5.0)
path = N.to_path([sq])
check("raccordo su un nodo: lo spigolo diventa due nodi con un arco", why == "" and len(sq.nodes) == n0 + 1, why)
# l'arco: tutti i suoi punti a 5 mm dal centro del raccordo
corner = None
for i, j in sq.segments():
    if sq.is_curve(i, j):
        corner = sq.bezier(i, j)
pts = [N.bez_point(*corner, t / 10) for t in range(11)] if corner else []
ctr = None
if corner:
    # il centro sta a 5 mm dai due punti di tangenza, verso l'interno
    a, b = corner[0], corner[3]
    ctr = (min(a[0], b[0]) if a[0] != b[0] else a[0], min(a[1], b[1]) if a[1] != b[1] else a[1])
    cands = [(a[0], b[1]), (b[0], a[1])]
    ctr = min(cands, key=lambda c: abs(math.dist(c, pts[5]) - 5))
devs = [abs(math.dist(ctr, q) - 5) for q in pts] if ctr else [9]
check("…ed è un vero arco di cerchio di raggio 5 (errore < 0,01 mm)", max(devs) < 0.01, max(devs))
check("…e gli altri tre spigoli restano vivi", sum(1 for i, j in sq.segments() if sq.is_curve(i, j)) == 1)
line = N.SubPath([N.Node(0, 0), N.Node(10, 0), N.Node(20, 0)], closed=False)
check("lati allineati: nessuno spigolo da arrotondare (lo dice)", N.fillet(line, 1, 3) != "")
check("estremo di un tracciato aperto: lo dice", N.fillet(N.SubPath([N.Node(0, 0), N.Node(10, 0), N.Node(10, 10)]), 0, 3)
      != "")
big = N.from_path(RectShape(10, 10).local_path())[0]
N.fillet(big, 1, 50)
check("raggio troppo grande: limitato a metà dei lati (niente lati che si incrociano)",
      N.to_path([big]).boundingRect().width() <= 10.0001)

# nella finestra: rettangolo → strumento Nodi → A sull'angolo
rect2 = RectShape(30, 30, layer=1)
ed.add([rect2], "y")
ed.select([rect2])
spin()
w.canvas.set_tool("nodes")
spin()
tool = w.canvas.tool
before = len(ed.doc.shapes)
ok = tool.fillet_node(0, 1, 4.0)
spin()
cur = ed.doc.shapes[-1]
check("Nodi, tasto A: la forma diventa tracciato con un angolo arrotondato", ok and isinstance(cur, PathShape)
      and sum(1 for i, j in N.from_path(cur.path())[0].segments() if N.from_path(cur.path())[0].is_curve(i, j)) == 1
      and len(ed.doc.shapes) == before)
ed.undo()
spin()
check("…annulla: torna il rettangolo", isinstance(ed.doc.shapes[-1], RectShape))
check("il raggio usato si ricorda per la volta dopo", w.canvas.tool_options.get("fillet_radius") == 4.0)

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
