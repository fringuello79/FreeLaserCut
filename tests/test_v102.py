# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10.2 (segnalazioni di un utente):
- chiusa l'anteprima, la foto non resta coperta dall'arancione del percorso;
- «Prepara foto»: zoom sull'anteprima dell'incisione (rotella, pulsanti, doppio clic, trascinamento),
  con la zona visibile ricalcolata a punti veri per confrontare bene i metodi di incisione."""
import sys, os, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from freelasercut.ui import style
from freelasercut.theme import QSS
app = QApplication([]); app.setStyle("Fusion"); style.load_fonts(); app.setFont(style.ui_font(9.5))
app.setStyleSheet(QSS + style.QSS_EXTRA)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.core.document import ImageShape, RectShape
from freelasercut.ui import dialogs as dialogs_mod
from freelasercut.ui.dialogs_photo import PhotoDialog
from freelasercut.ui.main_window import MainWindow

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.005)

TMP = tempfile.mkdtemp()
def phone_photo(W=4000, H=3000):
    rng = np.random.default_rng(3)
    y, x = np.mgrid[0:H, 0:W]
    img = np.zeros((H, W, 3), np.float32); img[:] = (190, 200, 215)
    face = ((x - W / 2) / (W * 0.25)) ** 2 + ((y - H / 2) / (H * 0.40)) ** 2 <= 1
    shade = 40 + 170 * (x - W * 0.25) / (W * 0.5)
    for c in range(3):
        img[..., c] = np.where(face, shade, img[..., c])
    img += rng.normal(0, 8, (H, W, 1))
    p = os.path.join(TMP, f"foto_{W}x{H}.jpg")
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").save(p, quality=88)
    return p

w = MainWindow(); w.resize(1500, 950); w.show(); spin(0.4)
ed, cv = w.editor, w.canvas
dialogs_mod.PreviewDialog.exec = lambda self: 0

# ------------------------------------------------------------------ anteprima: niente arancione dopo la chiusura
r = RectShape(40, 30); ed.add([r]); spin(0.1)
w.build_job(); spin(0.1)
check("lavoro preparato: il percorso si vede sul piano (serve per Avvia)", len(cv._preview_items) > 0)
w.preview_job(); spin(0.1)
check("chiusa l'anteprima di un disegno: niente percorso arancione sul piano", len(cv._preview_items) == 0)
ctl = w.ctl
ctl._job_active = True
w.preview_job(); spin(0.1)
check("durante un lavoro l'anteprima sul piano resta", len(cv._preview_items) > 0)
ctl._job_active = False
for s in list(ed.doc.shapes):
    ed.select([s]); ed.delete()
spin(0.1)

w.import_files([phone_photo()]); spin(0.3)
img = [s for s in ed.doc.shapes if isinstance(s, ImageShape)][0]
ed.select([img]); spin(0.1)
w._big_photo_ok = True
w.preview_job(); spin(0.2)
check("chiusa l'anteprima di una foto: la foto non resta arancione", len(cv._preview_items) == 0)
grab = cv.viewport().grab().toImage()
check("il piano si ridisegna senza l'immagine del percorso", not grab.isNull())

# ------------------------------------------------------------------ Prepara foto: zoom
original = ed.doc.images[img.source_id or img.image_id]
cs = ed.doc.layer(img.layer)
d = PhotoDialog(img, original, cs, (img.w, img.h), w)
d.resize(1300, 820); d.show(); spin(0.3)
d.dpi.setValue(318); d.dither.setCurrentIndex(d.dither.findData("jarvis")); d._timer.stop(); d._refresh(); spin(0.05)
v = d.v_res
ctx = d._res_ctx
check("anteprima ridotta per una foto da oltre un milione di punti", ctx is not None and ctx["k"] < 0.999, f"k={ctx and ctx['k']:.2f}")
check("all'inizio: tutta la foto, nessun dettaglio", abs(v.zoom - 1) < 1e-9 and v.detail is None)
check("la vista dell'originale (ritaglio) non fa zoom", not d.v_orig.zoomable and d.v_orig.croppable)

def wheel(view, steps, pos=None):
    pos = QPointF(pos) if pos is not None else QPointF(view.width() / 2, view.height() / 2)
    ev = QWheelEvent(pos, view.mapToGlobal(pos), QPoint(), QPoint(0, 120 * steps), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    view.wheelEvent(ev)
def mouse(view, kind, pos, button=Qt.LeftButton):
    pos = QPointF(*pos)
    t = {"press": QEvent.MouseButtonPress, "move": QEvent.MouseMove, "release": QEvent.MouseButtonRelease,
         "dbl": QEvent.MouseButtonDblClick}[kind]
    btns = Qt.NoButton if kind == "release" else button
    ev = QMouseEvent(t, pos, view.mapToGlobal(pos), button if kind != "move" else Qt.NoButton, btns, Qt.NoModifier)
    {"press": view.mousePressEvent, "move": view.mouseMoveEvent, "release": view.mouseReleaseEvent,
     "dbl": view.mouseDoubleClickEvent}[kind](ev)

wheel(v, 3); spin(0.05)
check("rotella: ingrandisce", 1.9 < v.zoom < 2.0, f"× {v.zoom:.2f}")
x0, y0, x1, y1 = v.visible_region()
check("si vede solo una parte della foto", (x1 - x0) < 0.6, f"{x1 - x0:.2f} × {y1 - y0:.2f}")
t0 = time.time()
spin(0.5)
check("zoom: la zona visibile si ricalcola a punti veri", v.detail is not None, v.note)
check("zoom: il ricalcolo è rapido", time.time() - t0 < 3)
if v.detail is not None:
    dimg, reg = v.detail
    step = 25.4 / 318
    nx_true = round(ctx["w_mm"] / step)
    dens = dimg.width() / (reg[2] - reg[0])
    check("zoom: dettaglio alla risoluzione vera del livello (318 dpi)", abs(dens - nx_true) / nx_true < 0.01,
          f"{dens:.0f} punti per riga intera, attesi {nx_true}")
    arr = np.frombuffer(dimg.constBits(), np.uint8).reshape(dimg.height(), dimg.bytesPerLine())[:, :dimg.width() * 3]
    cols = {tuple(c) for c in arr.reshape(-1, 3)[::97]}
    check("zoom: i punti sono punti (solo colore del materiale e del punto)", len(cols) <= 2, len(cols))
wheel(v, 6); spin(0.5)
g = v.grab().toImage()
cx, cy = g.width() // 2, g.height() // 2
patch = {g.pixel(cx + i, cy + j) for i in range(-25, 25) for j in range(-25, 25)}
check("ingrandita, la vista mostra punti netti (niente sfumature)", len(patch) <= 3, f"{len(patch)} colori, × {v.zoom:.1f}")

reg_before, c_before = v.detail[1] if v.detail else None, v.center
mouse(v, "press", (cx, cy)); mouse(v, "move", (cx - 120, cy)); mouse(v, "release", (cx - 120, cy)); spin(0.5)
check("trascinando si sposta la vista", v.center[0] > c_before[0] + 0.01, f"{c_before[0]:.3f} -> {v.center[0]:.3f}")
check("spostandosi, il dettaglio a punti veri segue", v.detail is not None and v.detail[1] != reg_before)

prev_bytes = bytes(v.detail[0].constBits()) if v.detail else b""
i_other = d.dither.findData("floyd")
d.dither.setCurrentIndex(i_other); d._timer.stop(); d._refresh(); spin(0.5)
check("cambiando metodo, lo zoom resta e il dettaglio si rifà con il nuovo metodo",
      v.zoom > 2 and v.detail is not None and bytes(v.detail[0].constBits()) != prev_bytes, d.dither.currentData())

z = v.zoom; d.z_out.click(); spin(0.05)
check("pulsante −", abs(v.zoom - z / 1.5) < 1e-6, f"{v.zoom:.2f}")
d.z_in.click(); spin(0.05)
check("pulsante +", abs(v.zoom - z) < 1e-6)
d.z_fit.click(); spin(0.5)
check("«Tutta la foto»: torna intera, senza dettaglio", abs(v.zoom - 1) < 1e-9 and v.detail is None and v.note == d._res_ctx["note"], v.note)
mouse(v, "dbl", (cx + 40, cy + 20)); spin(0.5)
check("doppio clic: ingrandisce lì", v.zoom == 4.0 and v.detail is not None)
mouse(v, "dbl", (cx, cy)); spin(0.3)
check("doppio clic di nuovo: tutta la foto", v.zoom == 1.0)
wheel(v, -5); spin(0.05)
check("non si riduce oltre la foto intera", v.zoom == 1.0)
wheel(v, 40); spin(0.05)
check("ingrandimento massimo limitato", v.zoom == v.ZMAX, f"× {v.zoom}")
d.z_fit.click(); spin(0.3)

d.real.setChecked(True); d._timer.stop(); d._refresh(); spin(0.05)
wheel(v, 4); spin(0.5)
check("resa «zona centrale 1:1»: lo zoom funziona e non serve ricalcolare", v.zoom > 2 and v.detail is None)
d.real.setChecked(False); d.z_fit.click()
d.tabs.setCurrentIndex(1); d._timer.stop(); d._refresh(); spin(0.05)
wheel(v, 4); spin(0.4)
g2 = v.grab().toImage()
check("linee e riempimenti: lo zoom funziona anche sui tracciati", v.zoom > 2 and v.detail is None and not g2.isNull() and bool(v.paths))
d.tabs.setCurrentIndex(0)
d.reject(); spin(0.1)

w.close(); spin(0.2)
print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
