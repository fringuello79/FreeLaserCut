# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.13.3: effetti per le foto in «Prepara foto» (matita, carboncino, china, fumetto, incisione a linee,
linee ondulate, puntinismo, posterizza, rilievo)."""
import sys, os, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import cv2
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
app = QApplication([])
from freelasercut.core import photo, photo_fx
from freelasercut.core.document import CutSettings, ImageShape

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)

# foto di prova: sfumatura, cerchio scuro, scritta, rumore leggero
rng = np.random.default_rng(1)
W, H = 1200, 800
base = np.tile(np.linspace(40, 230, W, dtype=np.float32), (H, 1))
im = Image.fromarray(np.clip(base + rng.normal(0, 6, (H, W)), 0, 255).astype(np.uint8), "L")
d = ImageDraw.Draw(im)
d.ellipse((300, 200, 700, 600), fill=25)
d.rectangle((800, 300, 1100, 500), fill=200)
FX = [k for k in photo_fx.EFFECTS if k != "none"]
check("effetti disponibili (9 della 0.13.3, il ritratto a matita e lo schizzo del soggetto)", len(FX) == 11, FX)

# ------------------------------------------------------------------ ogni effetto: forma, valori, bianco resta bianco
g = np.asarray(im, np.float32)
white = np.full((300, 400), 255.0, np.float32)
bad = []
for k in FX:
    out, sc = photo_fx.apply(g, k, 120.0, 0.5, 0.5, 0)
    w_out, _ = photo_fx.apply(white, k, 40.0, 1.0, 1.0, 0)
    if out.dtype != np.float32 or out.min() < 0 or out.max() > 255 or out.shape != g.shape or sc != 1.0:
        bad.append((k, "uscita", out.dtype, out.shape, sc))
    if (w_out < 250).mean() > 0.001:
        bad.append((k, "bianco inciso", float((w_out < 250).mean())))
    if (out < 160).mean() < 0.001:  # matita, china e rilievo segnano solo i bordi: bastano tratti presenti
        bad.append((k, "nessun tratto", float((out < 128).mean())))
check("ogni effetto: immagine valida, il bianco resta bianco (lo sfondo non si incide), i tratti ci sono", not bad, bad)
bw = [k for k in ("ink", "lines", "waves") if set(np.unique(photo_fx.apply(g, k, 120.0)[0])) - {0.0, 255.0}]
check("china e linee: solo bianco e nero (si incidono veloci, senza retinatura)", not bw, bw)
# ------------------------------------------------------------------ misure in millimetri, non in pixel
def line_period_px(out):
    col = out[:, 150] < 128  # zona scura a sinistra: righe ben visibili
    starts = np.nonzero(col[1:] & ~col[:-1])[0]
    return float(np.median(np.diff(starts))) if len(starts) > 3 else 0.0
p_big = line_period_px(photo_fx.apply(g, "lines", 120.0, 0.5, 0.5)[0]) / (W / 120.0)
small = cv2.resize(g, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
p_small = line_period_px(photo_fx.apply(small, "lines", 120.0, 0.5, 0.5)[0]) / (W / 2 / 120.0)
check("incisione a linee: il passo delle righe è in mm, uguale sull'anteprima ridotta e sulla foto vera",
      p_big > 0 and abs(p_big - p_small) < 0.15, (round(p_big, 3), round(p_small, 3)))
p_fine = line_period_px(photo_fx.apply(g, "lines", 120.0, 0.5, 1.0)[0]) / (W / 120.0)
check("cursore «Righe fitte»: più alto, righe più vicine", 0 < p_fine < p_big, (round(p_fine, 2), round(p_big, 2)))
d_lo = (photo_fx.apply(g, "stipple", 120.0, 0.1, 0.5)[0] < 128).mean()
d_hi = (photo_fx.apply(g, "stipple", 120.0, 0.9, 0.5)[0] < 128).mean()
check("puntinismo: «Intensità» più alta, più punti", d_hi > d_lo * 1.2, (round(d_lo, 3), round(d_hi, 3)))
v0 = photo_fx.apply(g, "lines", 120.0, 0.5, 0.5, 0)[0]
v90 = photo_fx.apply(g, "lines", 120.0, 0.5, 0.5, 90)[0]
check("direzione delle righe: orizzontali e verticali diverse", (v0 != v90).mean() > 0.2)
# ------------------------------------------------------------------ foto grandi: veloci, calcolate alla risoluzione utile
huge = np.asarray(Image.fromarray(np.asarray(im)).resize((6000, 4000)), np.float32)
slow = []
for k in FX:
    t = time.time()
    out, sc = photo_fx.apply(huge, k, 100.0, 0.5, 0.5)
    dt = time.time() - t
    if dt > 6.0 or out.shape[1] > 100 * photo_fx.WORK_PX_PER_MM + 2:
        slow.append((k, round(dt, 1), out.shape))
check("foto da 24 megapixel larga 10 cm: ogni effetto in pochi secondi, alla risoluzione che serve al laser", not slow, slow)
# ------------------------------------------------------------------ dentro «Prepara foto»: sfondo e forma restano bianchi
st = photo.PhotoSettings(effect="pencil", width_mm=120.0, mask="oval")
p_img = photo.process(im, st)
a = np.asarray(p_img)
check("effetto con la forma ovale: gli angoli restano bianchi", a[0:20, 0:20].min() >= 250 and a.shape == (H, W))
st2 = photo.PhotoSettings(effect="cartoon", width_mm=50.0)
p2 = photo.process(Image.fromarray(np.asarray(huge).astype(np.uint8)), st2)
check("foto molto definita: l'effetto si calcola più piccolo, le proporzioni restano",
      p2.width <= 50 * photo_fx.WORK_PX_PER_MM + 2 and abs(p2.width / p2.height - 1.5) < 0.01, p2.size)
rt = photo.PhotoSettings.from_dict(photo.PhotoSettings(effect="waves", effect_angle=45, effect_strength=70,
                                                       effect_detail=20, width_mm=80).to_dict())
check("le scelte dell'effetto si salvano nel progetto e si ritrovano", (rt.effect, rt.effect_angle, rt.effect_strength,
      rt.effect_detail, rt.width_mm) == ("waves", 45, 70.0, 20.0, 80.0))
check("effetto sconosciuto (progetto di una versione futura): nessun effetto, niente errori",
      photo.PhotoSettings.from_dict({"effect": "acquerello", "effect_angle": 33}).effect == "none")
check("solo la larghezza non conta come modifica della foto", photo.PhotoSettings(width_mm=50).is_identity() and
      not photo.PhotoSettings(effect="ink").is_identity())
check("progetti di prima (senza effetto): si aprono come prima", photo.PhotoSettings.from_dict({"sharpen": 20}).effect == "none")
# ------------------------------------------------------------------ finestra
from freelasercut.ui.dialogs_photo import PhotoDialog
shape = ImageShape("x", 120, 80)
dlg = PhotoDialog(shape, im.convert("RGB"), CutSettings(index=0), (120.0, 80.0))
check("Prepara foto: menu «Effetto» con gli effetti, di partenza «Nessuno», cursori nascosti",
      dlg.effect.count() == len(photo_fx.EFFECTS) and dlg.effect.currentData() == "none" and not dlg.fx_strength.isVisibleTo(dlg))
dlg.effect.setCurrentIndex(dlg.effect.findData("lines"))
check("scegliendo «Incisione a linee»: compaiono intensità, «Righe fitte» e la direzione",
      dlg.fx_strength.isVisibleTo(dlg) and dlg.fx_detail_name.text() == "Righe fitte" and dlg.fx_angle.isVisibleTo(dlg))
dlg.effect.setCurrentIndex(dlg.effect.findData("pencil"))
check("con la matita la direzione delle righe sparisce", not dlg.fx_angle.isVisibleTo(dlg))
st = dlg.settings()
check("le impostazioni portano effetto e larghezza (per le misure in mm)", st.effect == "pencil" and st.width_mm == 120.0)
err = None
for k in FX:
    dlg.effect.setCurrentIndex(dlg.effect.findData(k))
    try:
        dlg._refresh()
    except Exception as ex:  # noqa: BLE001
        err = (k, repr(ex))
        break
check("anteprima della finestra con ogni effetto: nessun errore", err is None and "Errore" not in dlg.info.text(), err)
dlg.effect.setCurrentIndex(0)
check("«Nessuno»: la larghezza non entra nelle impostazioni (nessun ricalcolo inutile della foto)",
      dlg.settings().width_mm == 0.0)
shape.photo = photo.PhotoSettings(effect="stipple", effect_strength=80).to_dict()
dlg2 = PhotoDialog(shape, im.convert("RGB"), CutSettings(index=0), (120.0, 80.0))
check("riaprendo «Prepara foto» l'effetto scelto c'è ancora", dlg2.effect.currentData() == "stipple" and
      dlg2.fx_strength.value() == 80)
# ------------------------------------------------------------------ dal programma: applica, vettoriale, prova foto
from PySide6.QtWidgets import QDialog, QMessageBox
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui import dialogs_photo
w = MainWindow()
ed = w.editor
def spin(t):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.01)
fp = os.path.join(tempfile.mkdtemp(), "foto.png"); im.convert("RGB").save(fp)
w.import_files([fp]); spin(0.2)
img = [x for x in ed.doc.shapes if isinstance(x, ImageShape)][0]
ed.select([img]); spin(0.1)
src = img.image_id
orig_exec = dialogs_photo.PhotoDialog.exec
def run_dialog(setup):
    def ex(self):
        setup(self)
        self._timer.stop(); self._refresh()
        return QDialog.Accepted
    dialogs_photo.PhotoDialog.exec = ex
    w.photo_dialog(); spin(0.2)
    dialogs_photo.PhotoDialog.exec = orig_exec
def s_lines(d):
    d.effect.setCurrentIndex(d.effect.findData("lines")); d.fx_angle.setCurrentIndex(d.fx_angle.findData(45))
    d.width_mm.setValue(60.0); d._accept()
run_dialog(s_lines)
img = [x for x in ed.doc.shapes if isinstance(x, ImageShape)][0]
prep = np.asarray(ed.doc.images[img.image_id])
check("Applica con «Incisione a linee»: foto nuova in bianco e nero, originale conservato, larghezza 60 mm",
      img.source_id == src and set(np.unique(prep)) <= {0, 255} and abs(img.w * abs(img.tf.m11()) - 60) < 0.1
      and img.photo["effect"] == "lines" and img.photo["effect_angle"] == 45, (img.photo or {}).get("effect"))
job = w.build_job(); spin(0.1)
check("…e si incide", job is not None and len(job.lines) > 200, len(job.lines) if job else None)
def s_reopen(d):
    seen["fx"] = (d.effect.currentData(), d.fx_angle.currentData())
    d.effect.setCurrentIndex(0); d._accept()
seen = {}
run_dialog(s_reopen)
img = [x for x in ed.doc.shapes if isinstance(x, ImageShape)][0]
check("riaprendo c'è l'effetto; scegliendo «Nessuno» torna la foto senza effetto", seen["fx"] == ("lines", 45) and
      (img.image_id == src or len(np.unique(np.asarray(ed.doc.images[img.image_id]))) > 2))
def s_vec(d):
    d.effect.setCurrentIndex(d.effect.findData("ink")); d.tabs.setCurrentIndex(1); d.tones.setValue(1); d._accept()
n0 = len(ed.doc.shapes)
run_dialog(s_vec)
check("China + «Linee e riempimento»: diventa vettoriale senza errori", len(ed.doc.shapes) > n0, (n0, len(ed.doc.shapes)))
w.import_files([fp]); spin(0.2)
img = [x for x in ed.doc.shapes if isinstance(x, ImageShape)]
if img:
    ed.select([img[-1]]); spin(0.1)
    def s_test(d):
        d.effect.setCurrentIndex(d.effect.findData("pencil")); d._make_test()
    n1 = len(ed.doc.shapes)
    run_dialog(s_test)
    check("Prova foto (4 metodi) con la matita: i 4 quadrati si creano", len(ed.doc.shapes) >= n1 + 4, (n1, len(ed.doc.shapes)))
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
