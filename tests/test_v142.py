# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.14.2: Scultura 3D senza blocchi con i modelli scomodi (un portachiavi basso e largo diventava una
scultura di metri e il programma restava fermo per decine di minuti).
- altezza di partenza presa dal modello, con la base che entra nel foglio;
- avvisi e conferma prima di creare una scultura enorme;
- calcoli e sistemazione dei pezzi con l'avanzamento e il pulsante Annulla;
- sistemazione sui fogli molto più svelta (pezzi preparati una volta, pezzi uguali riconosciuti)."""
import os
import struct
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import pyclipper
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication, QDialog, QProgressDialog

app = QApplication([])
from freelasercut.core import nesting, sculpt as S
from freelasercut.core.document import GroupShape, PathShape

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info)


# ================================================================== geometria più svelta, stessi risultati
rng = np.random.default_rng(3)
ring = np.c_[np.cos(np.linspace(0, 6.28, 5000)), np.sin(np.linspace(0, 6.28, 5000))] * 37.123 + rng.normal(0, 0.01, (5000, 2))
old = [(int(round(x * S.SCALE)), int(round(y * S.SCALE))) for x, y in ring]
check("conversione per pyclipper uguale a prima (punto per punto)", S._to_int(ring) == [list(p) for p in old])
check("area di un anello uguale a quella di pyclipper", abs(S._area(ring) - abs(pyclipper.Area(old)) / S.SCALE ** 2) < 0.01,
      round(S._area(ring), 4))
t = time.time()
for _ in range(50):
    S._to_int(ring)
check("conversione veloce (5000 punti, 50 volte)", time.time() - t < 0.5, round(time.time() - t, 3))

# ================================================================== modello basso e largo (come un portachiavi)
heart = S.builtin("heart")
flat = S.Mesh(heart.vertices * [1.0, 1.0, 0.04], heart.faces)  # 133 × 55 × 4,8: un portachiavi a forma di cuore
D = tempfile.mkdtemp()
fp = os.path.join(D, "portachiavi.stl")
P = flat.vertices[flat.faces].astype(np.float32)
with open(fp, "wb") as fh:
    fh.write(b"\0" * 80 + struct.pack("<I", len(P)))
    for tri in P:
        fh.write(struct.pack("<3f", 0, 0, 0) + tri.tobytes() + b"\0\0")

ticks = []
L = S.layered(S.prepared(heart, "z", 120.0), 3.0, tick=lambda f: ticks.append(f) or False)
check("calcolo a strati: avanzamento da 0 a 1", ticks and ticks[-1] <= 1.0 and ticks == sorted(ticks) and ticks[-1] > 0.9,
      (len(ticks), round(ticks[-1], 2)))
try:
    S.layered(S.prepared(heart, "z", 120.0), 3.0, tick=lambda f: f > 0.3)
    stop = False
except InterruptedError:
    stop = True
check("calcolo a strati: Annulla lo ferma", stop)
try:
    sp = S.prepared(S.builtin("sphere"), "z", 120.0)
    S.interlocking(sp, 3.0, 5, 5, tick=lambda f: True)
    stop = False
except InterruptedError:
    stop = True
check("calcolo a incastro: Annulla lo ferma", stop)

from freelasercut.ui import dialogs_sculpt as DS

dlg = DS.SculptDialog(None, (450.0, 440.0))
check("altezza minima 5 mm (un oggetto basso resta basso)", dlg.height_mm.minimum() == 5)
dlg.load_file(fp)
lo, hi = dlg.sculpture.mesh.bounds()
foot = max(hi[0] - lo[0], hi[1] - lo[1])
check("aprendo un file: altezza vera del modello, la base entra nel foglio", abs(dlg.height_mm.value() - 5.0) < 0.6
      and foot <= 0.9 * 440 + 1 and not dlg._risks(), (dlg.height_mm.value(), round(foot)))
dlg.height_mm.setValue(120.0)
dlg._rebuild()
risks = dlg._risks()
check("con 120 mm (base larga 3 metri): avvisi in rosso sotto le misure", len(risks) >= 2
      and "più grandi del foglio" in dlg.info.text() and "fogli" in risks[1], risks)
asked = []
DS.SculptDialog._confirm_big = lambda self, r: asked.append(r) or False
dlg.accept()
check("«Crea i pezzi» con la scultura enorme: chiede prima; «Torna alle misure» lascia aperta la finestra",
      asked and dlg.result() != QDialog.Accepted)
DS.SculptDialog._confirm_big = lambda self, r: True
dlg.accept()
check("«Crea comunque»: si va avanti", dlg.result() == QDialog.Accepted)
dlg2 = DS.SculptDialog(None, (450.0, 440.0))
dlg2.load_file(fp)
dlg2.up.setCurrentIndex(dlg2.up.findData("y"))
ext = flat.vertices.max(0) - flat.vertices.min(0)
want = max(5.0, min(ext[1], ext[1] * 0.9 * 440 / max(ext[0], ext[2])))
check("cambiando l'asse verticale di un file: l'altezza diventa quella vera su quell'asse (base nel foglio)",
      abs(dlg2.height_mm.value() - round(want, 1)) < 0.11, (dlg2.height_mm.value(), round(want, 1)))
orig_wc = QProgressDialog.wasCanceled
QProgressDialog.wasCanceled = lambda self: True
dlg2.height_mm.setValue(300.0)
dlg2._rebuild()
QProgressDialog.wasCanceled = orig_wc
check("calcolo annullato nella finestra: niente scultura, si dice cosa fare", dlg2.sculpture is None
      and "annullato" in dlg2.info.text() and not dlg2.ok_btn.isEnabled())
dlg2._rebuild()
check("dopo l'annullamento si può ricalcolare", dlg2.sculpture is not None and dlg2.ok_btn.isEnabled())
dlg2.reject()


# ================================================================== sistemazione sui fogli
def square(sz, x=0.0):
    p = QPainterPath()
    p.addRect(QRectF(x, 0, sz, sz * 0.6))
    return GroupShape([PathShape(p, 0)], layer=0)


shapes = [square(80) for _ in range(30)] + [square(30) for _ in range(40)] + [square(700)]
calls = []
t = time.time()
res, shifts, left = nesting.nest_pieces(shapes, 400.0, 300.0, spacing=2.5, margin=2.0,
                                        tick=lambda *a: calls.append(a) or False)
dt = time.time() - t
placed = [g for r in res for k in r.placements for g in k]
check("pezzi su più fogli: quello più grande del foglio resta fuori subito, gli altri tutti sistemati",
      len(placed) == 70 and left == [shapes[-1]], (len(placed), len(left), len(res), round(dt, 1)))
for r in res:
    nesting.apply(r)
bad = []
for k, dx in enumerate(shifts):
    on = [g for r in res[k:k + 1] for key in r.placements for g in key]
    rects = [g.bounds() for g in on]
    for a in rects:
        if a.left() < dx + 1.9 or a.right() > dx + 400 - 1.9 or a.top() < 1.9 or a.bottom() > 300 - 1.9:
            bad.append(("fuori", k))
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if rects[i].adjusted(-1.2, -1.2, 1.2, 1.2).intersects(rects[j]):
                bad.append(("sovrapposti", k))
check("dentro i fogli (margine 2 mm), mai sovrapposti, distanza fra i pezzi rispettata", not bad, bad[:3])
check("avanzamento continuo (tick) mentre lavora", len(calls) >= 70 and calls[-1][0] >= 0.99, (len(calls), calls[-1]))
try:
    nesting.nest_pieces([square(50) for _ in range(20)], 400.0, 300.0, tick=lambda f, *a: f > 0.5)
    stop = False
except InterruptedError:
    stop = True
check("Annulla durante la sistemazione la ferma", stop)
same = [square(120) for _ in range(60)]
t = time.time()
res2, sh2, left2 = nesting.nest_pieces(same, 400.0, 300.0, spacing=2.5, margin=2.0)
dt2 = time.time() - t
check("60 pezzi uguali (fette di un oggetto estruso): svelto", sum(len(r.placements) for r in res2) == 60 and dt2 < 10,
      (len(res2), round(dt2, 1)))

# ================================================================== tutto il percorso, come l'utente
from freelasercut.ui.main_window import MainWindow

w = MainWindow()


CANCEL = [False]


def big_exec(self):
    self.load_file(fp)
    self.height_mm.setValue(120.0)
    self._rebuild()
    if CANCEL[0]:  # Annulla premuto mentre sistema i pezzi (dopo la finestra)
        QProgressDialog.wasCanceled = lambda self: True
    return QDialog.Accepted


DS.SculptDialog.exec = big_exec
DS.SculptDialog._confirm_big = lambda self, r: True
names_before = {i: c.name for i, c in w.editor.doc.layers.items()}
CANCEL[0] = True
g = w.sculpt_dialog()
QProgressDialog.wasCanceled = orig_wc
CANCEL[0] = False
check("Annulla mentre sistema i pezzi: niente nel progetto, livelli come prima, lo dice",
      g is None and not w.editor.doc.shapes and {i: c.name for i, c in w.editor.doc.layers.items()} == names_before
      and "annullata" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
t = time.time()
g = w.sculpt_dialog()
dt = time.time() - t
msg = w.statusBar().currentMessage()
check("scultura enorme creata comunque in poco tempo, con i pezzi più grandi del foglio messi a destra",
      g and dt < 90 and "più grandi del foglio" in msg, (len(g or []), round(dt, 1), msg[:90]))

print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
