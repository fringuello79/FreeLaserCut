# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10: foto veloci (segnalazione #2: anteprima lentissima e programma bloccato dopo la chiusura),
«Prepara foto» (regolazioni, sfondo, forma, metodo con l'anteprima dei punti), foto -> linee e riempimenti,
prova foto. Misura anche i tempi: una foto non deve più bloccare il programma."""
import sys, os, time, tempfile, hashlib
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import cv2
from PIL import Image
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog, QGraphicsPixmapItem
from PySide6.QtCore import QPointF
from freelasercut.ui import style
from freelasercut.theme import QSS
app = QApplication([]); app.setStyle("Fusion"); style.load_fonts(); app.setFont(style.ui_font(9.5))
app.setStyleSheet(QSS + style.QSS_EXTRA)
ASK = {"n": 0, "answer": QMessageBox.Yes}
def _question(*a, **k):
    ASK["n"] += 1
    return ASK["answer"]
QMessageBox.question = staticmethod(_question)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import gcode_preview
from freelasercut.core import gcode, io_formats, photo
from freelasercut.core.document import Document, ImageShape, RectShape, EllipseShape
from freelasercut.profile import MachineProfile
from freelasercut.ui import dialogs as dialogs_mod
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui.dialogs_photo import PhotoDialog

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.005)

TMP = tempfile.mkdtemp()
def phone_photo(W=4000, H=3000):
    """Foto «da telefono»: niente risoluzione dichiarata, grana, sfumature, sfondo uniforme e un soggetto."""
    rng = np.random.default_rng(7)
    y, x = np.mgrid[0:H, 0:W]
    img = np.zeros((H, W, 3), np.float32); img[:] = (180, 205, 230)
    face = ((x - W / 2) / (W * 0.22)) ** 2 + ((y - H / 2) / (H * 0.38)) ** 2 <= 1
    shade = 60 + 120 * (x - W * 0.28) / (W * 0.44)
    for c in range(3):
        img[..., c] = np.where(face, shade, img[..., c])
    img += rng.normal(0, 10, (H, W, 1))
    p = os.path.join(TMP, f"foto_{W}x{H}.jpg")
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").save(p, quality=88)
    return p

w = MainWindow(); w.resize(1600, 980); w.show(); spin(0.5)
ed, cv, doc = w.editor, w.canvas, lambda: w.editor.doc

# ================================================================== segnalazione #2: foto e anteprima
print("Foto da telefono (4000 × 3000, senza risoluzione dichiarata)")
w.import_files([phone_photo()]); spin(0.2)
img = ed.doc.shapes[-1]
check("la foto arriva a 100 mm di lato lungo, non grande quanto il piano", isinstance(img, ImageShape) and abs(max(img.w, img.h) - 100) < 0.5,
      f"{img.w:.1f} × {img.h:.1f} mm")
check("livello in modalità Immagine", ed.doc.layer(img.layer).mode == "image")
calls = {"n": 0}
_orig_parse = gcode_preview.parse
def counting_parse(*a, **k):
    calls["n"] += 1
    return _orig_parse(*a, **k)
gcode_preview.parse = counting_parse
times = {}
def fake_exec(self):
    t = time.time(); self.show(); spin(0.05); times["show"] = time.time() - t
    times["raster"] = self._rast is not None
    self.slider.setValue(self.slider.maximum() // 2); spin(0.05)
    times["seek_ok"] = self._rast is None or self._rast["k"] == self.slider.maximum() // 2
    t = time.time(); self.r_real.setChecked(True); spin(0.05); times["real"] = time.time() - t
    t = time.time(); self.close(); spin(0.05); times["close"] = time.time() - t
    return 0
dialogs_mod.PreviewDialog.exec = fake_exec
t0 = time.time(); w.preview_job(); t_prev = time.time() - t0
gcode_preview.parse = _orig_parse
check("anteprima: il G-code si legge una volta sola", calls["n"] == 1, f"{calls['n']} letture")
check("anteprima della foto in meno di 25 s (prima: minuti)", t_prev < 25, f"{t_prev:.1f} s, {len(w.job.lines)} righe")
check("finestra Anteprima: percorsi come immagine, apertura rapida", times.get("raster") and times.get("show", 99) < 3, f"{times.get('show', 0):.2f} s")
check("finestra Anteprima: il cursore del tempo funziona", times.get("seek_ok"))
check("finestra Anteprima: resa realistica e chiusura rapide", times.get("real", 99) < 5 and times.get("close", 99) < 1,
      f"{times.get('real', 0):.2f} s / {times.get('close', 0):.3f} s")
check("chiusa l'anteprima, il piano non resta arancione (segnalazione utente)", len(cv._preview_items) == 0)
cv.set_preview(w.job_preview, w.job.out_to_bed); spin(0.1)  # come all'avvio del lavoro
check("sul piano l'anteprima della foto è un'immagine (niente milioni di linee)",
      len(cv._preview_items) == 1 and isinstance(cv._preview_items[0], QGraphicsPixmapItem))
t0 = time.time()
for _ in range(3):
    cv.viewport().repaint(); app.processEvents()
t_rep = (time.time() - t0) / 3
check("dopo l'anteprima il piano si ridisegna subito (prima: secondi a ogni ridisegno)", t_rep < 0.5, f"{t_rep * 1000:.0f} ms")
pv = w.job_preview
check("anteprima compatta in memoria (array numpy)", isinstance(pv.segs, np.ndarray) and pv.segs.dtype == np.float64 and pv.segs.shape[1] == 7)
br = cv._preview_items[0].sceneBoundingRect()
check("immagine dell'anteprima al posto giusto sul piano", abs(br.left() - pv.min_x) < 1.5 and abs(-br.top() - pv.max_y) < 1.5,
      f"{br.left():.1f},{-br.top():.1f} vs {pv.min_x:.1f},{pv.max_y:.1f}")
ed.select([img]); ed.delete(); spin(0.2)
check("eliminata la foto, l'anteprima sparisce", len(cv._preview_items) == 0)

# ------------------------------------------------------------------ G-code invariato per i lavori vettoriali
prof = MachineProfile.load_default()
d2 = Document()
for cls, args in ((RectShape, (40, 30)), (EllipseShape, (25, 25)), (RectShape, (10, 60))):
    d2.shapes.append(cls(*args))
d2.layer(1).mode = "line"
d3 = Document(); r = RectShape(50, 40); r.layer = 2; d3.shapes.append(r); d3.layer(2).mode = "fill"
e = EllipseShape(30, 20); e.layer = 2; d3.shapes.append(e)
h_line = hashlib.md5("\n".join(gcode.generate(d2, prof, gcode.JobOptions()).lines).encode()).hexdigest()
h_fill = hashlib.md5("\n".join(gcode.generate(d3, prof, gcode.JobOptions()).lines).encode()).hexdigest()
check("G-code delle linee identico alla 0.9", h_line == "5cffa50b69026574f06587ef908cd1bb", h_line)
check("G-code dei riempimenti identico alla 0.9", h_fill == "f5ee11e54c34bf8b48b97d7e0392a045", h_fill)

# ------------------------------------------------------------------ foto enormi: conferma prima di preparare il lavoro
big = ImageShape(None, 400, 300); ed.doc.images["big"] = Image.new("L", (40, 30), 128); big.image_id = "big"; big.layer = 5
ed.add([big]); ed.doc.layer(5).mode = "image"; spin(0.1)
ASK["n"], ASK["answer"] = 0, QMessageBox.No
job = w.build_job()
check("foto enorme (12 milioni di punti): chiede prima di preparare il lavoro", ASK["n"] == 1 and job is None, f"{w._photo_dots() / 1e6:.1f} M punti")
ASK["answer"] = QMessageBox.Yes
ed.select([big]); ed.delete(); spin(0.1)
check("senza foto enormi non chiede nulla", w._photo_dots() < 1 and ASK["n"] == 1)

# ================================================================== Prepara foto
print("Prepara foto")
w.import_files([phone_photo(1600, 1200)]); spin(0.2)
img = ed.doc.shapes[-1]; ed.select([img]); spin(0.1)
src = img.image_id
check("comando Prepara foto attivo con una foto selezionata", w.acts["photo"].isEnabled())
c0 = img.tf.map(QPointF(img.w / 2, img.h / 2))
orig_exec = PhotoDialog.exec
seen = {}
def run_dialog(setup):
    def ex(self):
        self.show(); spin(0.2)
        setup(self)
        self._timer.stop(); self._refresh(); spin(0.05)
        seen["dlg"] = self
        return QDialog.Accepted
    PhotoDialog.exec = ex
    w.photo_dialog(); spin(0.2)
    PhotoDialog.exec = orig_exec
def setup1(d):
    d.bg.setChecked(True); d.auto.setChecked(True); d.sharp.setValue(40); d.mask.setCurrentIndex(d.mask.findData("oval"))
    d.fade.setValue(15); d._set_crop((0.1, 0.05, 0.9, 0.95)); d.width_mm.setValue(80.0)
    d.preset.setCurrentIndex(d.preset.findData("wood_light"))
    d.real.setChecked(True)
    seen["preview"] = d.v_res.qimg is not None
    d._accept()
run_dialog(setup1)
d = seen["dlg"]
check("anteprima dei punti veri nella finestra", seen.get("preview") and d.v_res.qimg is not None and d.v_res.note != "")
check("foto preparata: immagine nuova, originale conservato", img.image_id != src and img.source_id == src and src in ed.doc.images)
prep = ed.doc.images[img.image_id]
check("immagine preparata in scala di grigi, ritagliata", prep.mode == "L" and prep.size == (1280, 1080), prep.size)
pa = np.asarray(prep)
check("sfondo tolto e ovale: angoli bianchi", pa[0, 0] == 255 and pa[-1, -1] == 255 and pa[540, 640] < 200, (pa[0, 0], pa[540, 640]))
check("larghezza scelta e proporzioni del ritaglio", abs(img.w - 80) < 0.01 and abs(img.h - 80 * 1080 / 1280) < 0.01, f"{img.w:.1f} × {img.h:.1f}")
c1 = img.tf.map(QPointF(img.w / 2, img.h / 2))
check("la foto resta centrata dov'era", abs(c1.x() - c0.x()) < 0.01 and abs(c1.y() - c0.y()) < 0.01)
cs = ed.doc.layer(img.layer)
check("preset legno chiaro: metodo e gamma", cs.dither == "jarvis" and abs(img.gamma - 1.3) < 1e-6 and img.contrast == 10)
check("impostazioni salvate sulla foto", img.photo and img.photo["mask"] == "oval" and img.photo["bg_remove"])
job = w.build_job(); spin(0.1)
check("la foto preparata si incide", job is not None and len(job.lines) > 1000 and job.bounds is not None, f"{len(job.lines) if job else 0} righe")
p = os.path.join(TMP, "prova.flcut"); ed.doc.save(p)
d2 = Document.load(p); im2 = [s for s in d2.shapes if isinstance(s, ImageShape)][0]
check("salvato e riaperto: originale e impostazioni ci sono", im2.source_id in d2.images and im2.image_id in d2.images and im2.photo["mask"] == "oval")
def setup2(dd):
    seen["crop"] = dd.crop; seen["mask"] = dd.mask.currentData(); seen["w"] = dd.width_mm.value()
    dd.reject_now = True
    dd._accept()
run_dialog(setup2)
check("riaprendo: riparte dall'originale con le impostazioni di prima", seen["crop"] == (0.1, 0.05, 0.9, 0.95) and seen["mask"] == "oval"
      and abs(seen["w"] - 80) < 0.1)
check("riapplicare senza modifiche non cambia la foto", ed.doc.images[img.image_id].size == (1280, 1080))
ed.undo(); ed.undo(); spin(0.1)
check("Annulla: torna la foto originale", img.image_id == src or [s for s in ed.doc.shapes if isinstance(s, ImageShape)][0].image_id == src)
img = [s for s in ed.doc.shapes if isinstance(s, ImageShape)][0]; ed.select([img]); spin(0.1)

# rotazione + specchio
def setup3(dd):
    dd._rot(90); dd.flip.setChecked(True); dd._accept()
run_dialog(setup3)
img = [s for s in ed.doc.shapes if isinstance(s, ImageShape)][0]
pr = ed.doc.images[img.image_id]
check("rotazione di 90°: foto in verticale", pr.size == (1200, 1600) and img.h > img.w, pr.size)
ed.undo(); spin(0.1)

# ------------------------------------------------------------------ foto -> linee e riempimenti
img = [s for s in ed.doc.shapes if isinstance(s, ImageShape)][0]; ed.select([img]); spin(0.1)
n_before = len(ed.doc.shapes)
def setup4(dd):
    dd.tabs.setCurrentIndex(1); dd.tones.setValue(3); dd.v_outline.setChecked(True); dd.v_edges.setChecked(True)
    dd.bg.setChecked(True)
    seen["vec_paths"] = len(dd.v_res.paths) if hasattr(dd, "v_res") else 0
    dd._timer.stop(); dd._refresh()
    seen["vec_paths"] = len(dd.v_res.paths)
    dd._accept()
run_dialog(setup4)
from freelasercut.core.document import PathShape
paths = [s for s in ed.doc.shapes if isinstance(s, PathShape)]
modes = sorted(ed.doc.layer(s.layer).mode for s in paths)
check("anteprima vettoriale nella finestra", seen.get("vec_paths", 0) >= 3, seen.get("vec_paths"))
check("foto -> riempimenti e linee su livelli separati", modes.count("fill") >= 2 and modes.count("line") >= 1 and
      len({s.layer for s in paths}) == len(paths), modes)
check("la foto viene sostituita (Tieni la foto spento)", not any(isinstance(s, ImageShape) for s in ed.doc.shapes))
fills = sorted((s for s in paths if ed.doc.layer(s.layer).mode == "fill"), key=lambda s: ed.doc.layer(s.layer).power_max)
check("fasce più scure con più potenza", len(fills) >= 2 and ed.doc.layer(fills[0].layer).power_max < ed.doc.layer(fills[-1].layer).power_max)
bb = paths[0].bounds()
for s in paths[1:]:
    bb = bb.united(s.bounds())
check("i tracciati stanno dove era la foto", abs(bb.center().x() - c0.x()) < 15 and abs(bb.center().y() - c0.y()) < 15,
      f"{bb.center().x():.0f},{bb.center().y():.0f} vs {c0.x():.0f},{c0.y():.0f}")
job = w.build_job()
check("linee e riempimenti si incidono", job is not None and len(job.lines) > 100)
ed.undo(); spin(0.1)
check("Annulla: torna la foto, spariscono i tracciati", any(isinstance(s, ImageShape) for s in ed.doc.shapes) and
      not any(isinstance(s, PathShape) for s in ed.doc.shapes))

# ------------------------------------------------------------------ prova foto
img = [s for s in ed.doc.shapes if isinstance(s, ImageShape)][0]; ed.select([img]); spin(0.1)
def setup5(dd):
    dd._make_test()
run_dialog(setup5)
tiles = [s for s in ed.doc.shapes if isinstance(s, ImageShape) and s is not img]
check("prova foto: 4 quadrati su 4 livelli con metodi diversi", len(tiles) == 4 and
      len({ed.doc.layer(s.layer).dither for s in tiles}) == 4 and all(ed.doc.layer(s.layer).mode == "image" for s in tiles),
      [ed.doc.layer(s.layer).dither for s in tiles])
check("prova foto: quadrati di 30 mm accanto alla foto", all(abs(s.w - 30) < 0.01 for s in tiles) and
      min(s.bounds().left() for s in tiles) > img.bounds().right())
ed.undo(); spin(0.1)

# ------------------------------------------------------------------ Banco
check("Prepara foto nella guida «?»", "photo" in __import__("freelasercut.ui.help_texts", fromlist=["x"]).HELP)
w.close(); spin(0.2)
print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
