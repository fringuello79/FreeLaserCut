# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10.3 (note di un utente):
- suggerimenti dei comandi pronti e senza scatti (niente dissolvenza di Windows, compaiono dopo 350 ms);
- Ottimizza lo spazio (nesting) nella barra principale della finestra classica, accanto ad allinea e distribuisci;
- piano più reattivo: griglia, righelli e contorni delle forme non si ridisegnano da zero a ogni movimento del mouse.
  Il risultato deve essere identico, pixel per pixel, al disegno da zero in ogni situazione."""
import sys, os, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PIL import Image
from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QStyle
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
ERRORS = []
QMessageBox.critical = staticmethod(lambda *a, **k: (ERRORS.append(a[2] if len(a) > 2 else a), print("  !! errore:", a[2] if len(a) > 2 else a), QMessageBox.Ok)[-1])
from freelasercut.core.document import EllipseShape, RectShape, TextShape
from freelasercut.ui import main_window as mw
from freelasercut.ui import canvas as cvmod

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.005)

# ------------------------------------------------------------------ avvio vero: stile pronto e barra
holder = {}
def _later():
    for w in QApplication.topLevelWidgets():
        if isinstance(w, mw.MainWindow):
            holder["win"] = w
            app.exit(0)
tick = QTimer(); tick.timeout.connect(_later); tick.start(300)
argv0, sys.argv = sys.argv, ["freelasercut"]
try:
    mw.main(app, None)
except SystemExit:
    pass
tick.stop(); sys.argv = argv0
w = holder["win"]
check("suggerimenti: compaiono dopo 350 ms (prima 700)", app.style().styleHint(QStyle.SH_ToolTip_WakeUpDelay) == 350,
      app.style().styleHint(QStyle.SH_ToolTip_WakeUpDelay))
check("suggerimenti e menu senza dissolvenze né animazioni (niente «compare, sparisce, ricompare»)",
      not any(QApplication.isEffectEnabled(e) for e in (Qt.UI_AnimateTooltip, Qt.UI_FadeTooltip, Qt.UI_AnimateMenu,
                                                          Qt.UI_FadeMenu, Qt.UI_AnimateCombo)))
tb = next(t for t in w.findChildren(mw.QToolBar) if t.objectName() == "main")
acts = tb.actions()
check("nesting nella barra principale", w.acts["nest"] in acts)
check("... accanto a distribuisci e allinea", acts.index(w.acts["nest"]) == acts.index(w.acts["dist_v"]) + 1)
check("... con la sua icona e il suggerimento", not w.acts["nest"].icon().isNull() and "nesting" in w.acts["nest"].toolTip().lower(),
      w.acts["nest"].toolTip())

# ------------------------------------------------------------------ piano: identico al disegno da zero
w.resize(1500, 900); spin(0.3)
ed, cv = w.editor, w.canvas
a = np.zeros((400, 600, 3), np.uint8); a[..., 0] = np.linspace(0, 255, 600)[None, :]; a[..., 1] = 120
p = os.path.join(tempfile.mkdtemp(), "g.png"); Image.fromarray(a).save(p)
w.import_files([p]); spin(0.2)
shapes = []
for i in range(16):
    r = RectShape(10 + i % 5, 8) if i % 2 else EllipseShape(9, 9)
    r.tf.translate(150 + (i % 4) * 25, 60 + (i // 4) * 25); r.layer = 1 + i % 3
    shapes.append(r)
txt = TextShape("Prova 123"); txt.tf.translate(60, 200); shapes.append(txt)
ed.add(shapes); spin(0.2); cv.fit_bed(); spin(0.2)

def grab():
    cv.viewport().repaint()
    im = cv.viewport().grab().toImage().convertToFormat(cv.viewport().grab().toImage().Format.Format_RGB32)
    return np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())[:, :im.width() * 4].reshape(
        im.height(), im.width(), 4).copy()
def fresh():
    """Disegno da zero: memorie svuotate, percorsi ricalcolati."""
    cv._bg_cache = (None, None, None); cv._ruler_cache = (None, None)
    for it in cv.items_by_id.values():
        it._leaves = None
    return grab()
def same(name):
    g1 = grab(); g2 = fresh()
    n = int((g1 != g2).any(axis=2).sum()) if g1.shape == g2.shape else -1
    check(f"piano identico al disegno da zero: {name}", n == 0, f"{n} pixel diversi")

def move(x, y):
    ev = QMouseEvent(QEvent.MouseMove, QPointF(x, y), cv.viewport().mapToGlobal(QPointF(x, y)), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    cv.mouseMoveEvent(ev)
grab(); move(400, 300); same("mouse sul piano")
move(700, 450); same("mouse spostato (righelli seguono il cursore)")
ed.select(shapes[:4]); spin(0.05); same("con una selezione")
cv.zoom_by(2.5, QPointF(500, 400)); spin(0.05); same("dopo uno zoom")
cv.translate_view(-130, 70); spin(0.05); same("dopo uno spostamento della vista")
cv.light_bed = False; cv.viewport().update(); same("piano scuro")
cv.show_grid = False; cv.viewport().update(); same("griglia spenta")
cv.show_grid = True; cv.light_bed = True; cv.viewport().update()
cv.set_bed(300, 200); spin(0.05); same("piano di dimensioni diverse")
w.resize(1200, 800); spin(0.3); same("finestra ridimensionata")
cv.filled_view = False; cv.viewport().update(); same("vista senza riempimenti")
cv.filled_view = True
txt.text = "Cambiato!"; ed.changed.emit(); spin(0.1); same("testo modificato: il contorno si aggiorna")
ed.undo(); spin(0.1); same("dopo un annulla")

# mouse che passa con lo strumento Selezione: si ridisegnano solo i righelli, con lo stesso risultato
cv.fit_bed(); ed.select(shapes[:3]); spin(0.05); grab()
upd = []
orig_update = cv.viewport().update
class _Spy:
    pass
from PySide6.QtWidgets import QWidget
_vp_update = QWidget.update
def spy(self, *a):
    upd.append(a)
    return _vp_update(self, *a)
QWidget.update = spy
for k in range(6):
    move(250 + k * 40, 200 + k * 25)
QWidget.update = _vp_update
spin(0.05)
check("mouse che passa (Selezione): si aggiornano solo le strisce dei righelli",
      upd and all(len(a) == 4 and (a[3] <= cvmod.RULER + 1 or a[2] <= cvmod.RULER + 1) for a in upd), upd[:3])
def screen_canvas():
    """Quello che c'è davvero sullo schermo (memoria della finestra), non un ridisegno."""
    tl = cv.viewport().mapTo(w, cv.viewport().rect().topLeft())
    im = w.screen().grabWindow(w.winId(), tl.x(), tl.y(), cv.viewport().width(), cv.viewport().height()).toImage()
    im = im.convertToFormat(im.Format.Format_RGB32)
    return np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())[:, :im.width() * 4].reshape(
        im.height(), im.width(), 4).copy()
on_screen = screen_canvas()
cv.viewport().repaint(); spin(0.05)
full = screen_canvas()
n = int((on_screen != full).any(axis=2).sum()) if on_screen.shape == full.shape else -1
check("dopo il passaggio del mouse lo schermo è identico a un ridisegno completo", n == 0 and on_screen.std() > 0, f"{n} pixel diversi")
check("strumenti che disegnano col mouse (es. rettangolo) ridisegnano tutto", not cv.tools["rect"].static_hover()
      and cv.tools["select"].static_hover())

# aggancio alla griglia: il passo resta giusto anche quando lo sfondo viene dalla memoria
cv.snap_grid = True; cv.fit_bed(); spin(0.05); grab(); s1 = cv.grid_step
cv.zoom_by(8, QPointF(500, 400)); spin(0.05); grab(); s2 = cv.grid_step
move(300, 300); grab(); s3 = cv.grid_step
check("aggancio alla griglia: il passo segue lo zoom", s2 < s1 and s3 == s2, (s1, s2, s3))
cv.snap_grid = False

# ------------------------------------------------------------------ velocità del ridisegno
w.resize(1500, 900); cv.set_bed(450, 440); spin(0.3)
texts = []
for i in range(10):
    t = TextShape(f"Targhetta numero {i + 1}"); t.tf.translate(40, 300 + i * 12); texts.append(t)
ed.add(texts); ed.select([]); cv.fit_bed(); spin(0.2)
def avg(n=25):
    grab(); spin(0.05)
    t = time.perf_counter()
    for k in range(n):
        move(300 + k * 7, 300 + k * 3)  # il mouse che si muove sul piano, poi Qt ridisegna quello che serve
        app.processEvents()
    return (time.perf_counter() - t) / n
t_new = avg()
cls = type(cv)
cached_bg, cached_rul, cached_leaves = cls.drawBackground, cls._draw_rulers, cvmod.ShapeItem._leaf_paths
def old_rulers(self, p, tf):  # come prima: tacche e numeri ricalcolati ogni volta
    self._ruler_cache = (None, None)
    return cached_rul(self, p, tf)
def old_leaves(self):  # come prima: contorni rigenerati a ogni disegno
    self._leaves = None
    return cached_leaves(self)
sel_tool = type(cv.tools["select"])
cached_sh = sel_tool.static_hover
cls.drawBackground = lambda self, p, rect: self._paint_background(p, rect)
cls._draw_rulers = old_rulers
cvmod.ShapeItem._leaf_paths = old_leaves
sel_tool.static_hover = lambda self: False
t_old = avg()
cls.drawBackground, cls._draw_rulers, cvmod.ShapeItem._leaf_paths = cached_bg, cached_rul, cached_leaves
sel_tool.static_hover = cached_sh
check("ridisegno del piano più rapido mentre il mouse si muove", t_new < t_old * 0.7,
      f"{t_new * 1000:.1f} ms invece di {t_old * 1000:.1f} ms")

check("nessun errore imprevisto durante la prova", not ERRORS, ERRORS[:2])
w.close(); spin(0.2)
print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
