# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.0: mezzetinte (retino), «Dimensione del punto» (proposta di un utente, decisa con Ale).

Il retino aveva già la densità (la cella: distanza fra i punti) e l'angolo, ma solo nelle impostazioni del livello.
Mancava la dimensione del punto a parità di cella. Ora:
1. «Dimensione del punto» in % (50–150; 100 = come prima, l'area del punto segue lo scuro della foto);
2. le misure che ne dipendono (punto più grande, punto più piccolo, distanza fra le righe) sono scritte sotto e
   cambiano al cambiare di cella, dimensione e risoluzione, con un avviso quando i punti chiari sarebbero più fini di
   una riga o la cella più stretta di due righe;
3. cella, angolo e dimensione si regolano anche in «Prepara foto», guardando l'anteprima;
4. tutto finisce nel progetto, nell'anteprima del piano e nel G-code.

Il dato: (scuro della foto 0..1, cella in mm, angolo, dimensione in %, risoluzione) -> punti tondi su una griglia.
Il raggio del punto, in celle, è  dimensione/100 × √(scuro/π).
"""
import ast
import hashlib
import json
import math
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.core import gcode, halftone, imaging, photo  # noqa: E402
from freelasercut.core.document import CutSettings, Document, ImageShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui import widgets  # noqa: E402
from freelasercut.ui.dialogs_photo import PhotoDialog  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402
from freelasercut.ui.panels_design import CutSettingsDialog  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.005)


def old_halftone(dark, cell, angle):
    """Il retino com'era fino alla 0.18.17, riscritto qui: il 100% deve dare esattamente questo."""
    h, w = dark.shape
    cell = max(cell, 2.0)
    blur = cv2.GaussianBlur(dark.astype(np.float32), (0, 0), cell / 2.5)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = math.radians(angle)
    u = xx * math.cos(a) + yy * math.sin(a)
    v = -xx * math.sin(a) + yy * math.cos(a)
    du = (u / cell) - np.floor(u / cell) - 0.5
    dv = (v / cell) - np.floor(v / cell) - 0.5
    dist = np.sqrt(du * du + dv * dv)
    radius = np.sqrt(np.clip(blur, 0, 1) / math.pi)
    return (dist <= radius).astype(np.float32)


def flat(dark, n=400):
    return np.full((n, n), dark, np.float32)


def ht(dark_img, cell_px, size, angle=45.0):
    return imaging.dither(dark_img, "halftone", cell_px, angle, size)


def blobs(img):
    """Numero di punti staccati e loro aree (in punti del laser), senza quelli tagliati dal bordo."""
    n, lab, stats, _c = cv2.connectedComponentsWithStats((img > 0.5).astype(np.uint8), connectivity=4)
    h, w = img.shape
    areas = [int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n)
             if stats[i, cv2.CC_STAT_LEFT] > 0 and stats[i, cv2.CC_STAT_TOP] > 0
             and stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH] < w
             and stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] < h]
    return n - 1, areas


# ================================================================== 1. al 100% non cambia niente
rng = np.random.default_rng(3)
ramp = np.tile(np.linspace(0, 1, 300, dtype=np.float32), (200, 1)) * 0.9 + rng.random((200, 300), dtype=np.float32) * 0.1
same = all(np.array_equal(imaging.dither(ramp, "halftone", c, a), old_halftone(ramp, c, a))
           and np.array_equal(imaging.dither(ramp, "halftone", c, a, 100.0), old_halftone(ramp, c, a))
           for c, a in ((6.0, 45.0), (10.0, 0.0), (3.0, 30.0), (2.0, 90.0), (25.0, 15.0)))
check("al 100% (e senza dire niente) il retino è identico, punto per punto, a quello di prima", same)
check("gli altri metodi non guardano la dimensione del punto",
      all(np.array_equal(imaging.dither(ramp, m, 6.0, 45.0, 150.0), imaging.dither(ramp, m, 6.0, 45.0))
          for m in ("grayscale", "threshold", "bayer", "floyd", "jarvis")))

# ================================================================== 2. la dimensione ingrandisce i punti, non li sposta
cov = {s: float(ht(flat(0.3), 20.0, s).mean()) for s in (50, 75, 100, 125, 150)}
check("grigio uniforme: più dimensione = più scuro inciso (50 < 75 < 100 < 125 < 150)",
      cov[50] < cov[75] < cov[100] < cov[125] < cov[150], cov)
check("…e l'area cresce con il quadrato della dimensione (30% di scuro: 7,5% · 16,9% · 30% · 46,9%)",
      all(abs(cov[s] - 0.3 * (s / 100) ** 2) < 0.02 for s in (50, 75, 100, 125)), cov)
n60, a60 = blobs(ht(flat(0.2), 20.0, 60))
n100, a100 = blobs(ht(flat(0.2), 20.0, 100))
n120, a120 = blobs(ht(flat(0.2), 20.0, 120))
check("la distanza fra i punti non cambia: stesso numero di punti al 60%, al 100% e al 120%", n60 == n100 == n120
      and n100 >= 380, (n60, n100, n120))
exp = {s: 2 * halftone.radius(0.2, s) * 20.0 for s in (60, 100, 120)}  # diametro atteso in punti del laser
got = {60: 2 * math.sqrt(np.median(a60) / math.pi), 100: 2 * math.sqrt(np.median(a100) / math.pi),
       120: 2 * math.sqrt(np.median(a120) / math.pi)}
check("il diametro misurato dei punti è quello calcolato (raggio = dimensione × √(scuro/π) celle)",
      all(abs(got[s] - exp[s]) < 0.8 for s in exp), (got, exp))
check("…e raddoppiando la dimensione (60% → 120%) il diametro raddoppia", abs(got[120] / got[60] - 2.0) < 0.15,
      got[120] / got[60])
check("bianco: nessun punto a nessuna dimensione", all(ht(flat(0.0, 120), 12.0, s).sum() == 0 for s in (50, 100, 150)))
b100, b130, b150 = (float(ht(flat(1.0, 240), 20.0, s).mean()) for s in (100, 130, 150))
check("nero pieno: al 100% resta del bianco fra i punti (come prima), dal 130% i punti si fondono (tutto inciso)",
      0.88 < b100 < 0.95 and b130 == 1.0 and b150 == 1.0, (b100, b130, b150))
check("l'angolo continua a funzionare con una dimensione diversa (0° e 45° danno retini diversi, stessa copertura)",
      not np.array_equal(ht(flat(0.3), 20.0, 80, 0.0), ht(flat(0.3), 20.0, 80, 45.0))
      and abs(float(ht(flat(0.3), 20.0, 80, 0.0).mean()) - float(ht(flat(0.3), 20.0, 80, 45.0).mean())) < 0.04)

# ================================================================== 3. valori strani
check("dimensione sempre fra 50 e 150: fuori scala viene riportata dentro, la robaccia vale 100",
      [halftone.clamp_size(x) for x in (100, "120", 10, -5, 1000, None, "abc", float("nan"), float("inf"), 149.9)]
      == [100.0, 120.0, 50.0, 50.0, 150.0, 100.0, 100.0, 100.0, 100.0, 149.9])
check("…anche dentro il retino (un valore assurdo non fa inciampare l'incisione)",
      np.array_equal(ht(flat(0.3, 100), 10.0, None), ht(flat(0.3, 100), 10.0, 100))
      and np.array_equal(ht(flat(0.3, 100), 10.0, 9999), ht(flat(0.3, 100), 10.0, 150)))

# ================================================================== 4. le misure collegate
d = halftone.dots(1.0, 100, 254)
check("cella 1 mm, 100%, 254 dpi: righe a 0,10 mm, punto più grande 1,13 mm, più piccolo 0,25 mm, nessun avviso",
      abs(d["step"] - 0.1) < 1e-9 and abs(d["big"] - 1.128) < 0.002 and abs(d["small"] - 0.252) < 0.002
      and not d["fine"] and not d["merged"] and not d["clamped"] and d["cell"] == 1.0, d)
d2, d50, d150 = halftone.dots(2.0, 100, 254), halftone.dots(1.0, 50, 254), halftone.dots(1.0, 150, 254)
check("le misure seguono la cella: cella doppia = punti doppi", abs(d2["big"] - 2 * d["big"]) < 1e-9
      and abs(d2["small"] - 2 * d["small"]) < 1e-9)
check("le misure seguono la dimensione: al 50% punti dimezzati, al 150% il più piccolo è una volta e mezza",
      abs(d50["big"] - d["big"] / 2) < 1e-9 and abs(d50["small"] - d["small"] / 2) < 1e-9
      and abs(d150["small"] - 1.5 * d["small"]) < 1e-9)
check("…ma il punto più grande non supera la diagonale della cella (oltre, i punti si fondono)",
      d150["merged"] and abs(d150["big"] - math.sqrt(2.0)) < 1e-9 and halftone.dots(1.0, 130, 254)["merged"]
      and not halftone.dots(1.0, 120, 254)["merged"] and halftone.dots(1.0, 120, 254)["big"] < math.sqrt(2.0))
check("le misure seguono la risoluzione: a 127 dpi le righe sono a 0,20 mm",
      abs(halftone.dots(1.0, 100, 127)["step"] - 0.2) < 1e-9 and halftone.dots(1.0, 100, 127)["big"] == d["big"])
f1, f2, f3 = halftone.dots(0.3, 100, 254), halftone.dots(0.3, 150, 254), halftone.dots(0.3, 100, 508)
check("cella 0,3 mm a 254 dpi: i punti chiari (0,08 mm) sarebbero più fini di una riga → avviso; con il 150% o con "
      "508 dpi l'avviso sparisce", f1["fine"] and abs(f1["small"] - 0.0757) < 0.001 and not f2["fine"] and not f3["fine"],
      (f1, f2, f3))
c1 = halftone.dots(0.1, 100, 254)
check("cella più stretta di due righe: viene usata (e detta) quella di due righe", c1["clamped"]
      and abs(c1["cell"] - 0.2) < 1e-9 and not d["clamped"])
# l'avviso dice il vero: guardo i punti che escono in una zona chiara
light = flat(halftone.LIGHT, 300)
n_fine, a_fine = blobs(ht(light, 0.3 / 0.1, 100))
n_ok, a_ok = blobs(ht(light, 1.0 / 0.1, 100))
check("l'avviso «più fini di una riga» dice il vero: lì escono puntini da 1–2 punti del laser, e non in tutte le celle",
      a_fine and max(a_fine) <= 2 and n_fine < 0.8 * (300 / 3.0) ** 2, (n_fine, max(a_fine or [0])))
check("…mentre senza avviso ogni cella ha il suo punto tondo (più punti del laser ciascuno)",
      n_ok >= 0.95 * (300 / 10.0) ** 2 - 60 and np.median(a_ok) >= 4, (n_ok, np.median(a_ok)))
note = widgets.halftone_note(1.0, 100, 254)
check("le misure in parole: «il più grande 1.13 mm… il più piccolo 0.25 mm… righe a 0.10 mm», senza avvisi",
      all(t in note for t in ("1.13", "0.25", "0.10")) and "⚠" not in note, note)
check("…con l'avviso dei punti fini, della cella troppo stretta, e la nota dei punti fusi",
      "⚠" in widgets.halftone_note(0.3, 100, 254) and "una riga" in widgets.halftone_note(0.3, 100, 254)
      and "⚠" in widgets.halftone_note(0.1, 100, 254) and "0.20" in widgets.halftone_note(0.1, 100, 254)
      and "fondono" in widgets.halftone_note(1.0, 130, 254) and "fondono" not in note)

# ================================================================== 5. nel livello e nel progetto
cs = CutSettings(index=3)
check("un livello nuovo ha la dimensione al 100%", cs.halftone_size == 100.0)
cs.halftone_size = 130.0
check("la dimensione si salva e si rilegge con il livello", CutSettings.from_dict(cs.to_dict()).halftone_size == 130.0)
old = cs.to_dict()
del old["halftone_size"]
check("un progetto vecchio (senza la voce) si apre al 100%", CutSettings.from_dict(old).halftone_size == 100.0)
check("un valore rovinato nel file non fa inciampare: 100%; fuori scala: riportato dentro",
      CutSettings.from_dict(dict(old, halftone_size="x")).halftone_size == 100.0
      and CutSettings.from_dict(dict(old, halftone_size=None)).halftone_size == 100.0
      and CutSettings.from_dict(dict(old, halftone_size=900)).halftone_size == 150.0)


def photo_doc(size=None, cell=1.0, angle=45.0, dither="halftone"):
    doc = Document()
    yy, xx = np.mgrid[0:120, 0:160]
    pic = np.clip(255 - (xx * 1.4 + yy * 0.3), 0, 255).astype(np.uint8)
    doc.images["foto"] = Image.fromarray(pic, "L")
    s = ImageShape("foto", 40.0, 30.0, layer=4)
    doc.shapes.append(s)
    c = doc.layer(4)
    c.mode, c.dither, c.dpi, c.speed, c.power_max = "image", dither, 127.0, 3000.0, 40.0
    c.halftone_cell, c.halftone_angle = cell, angle
    if size is not None:
        c.halftone_size = size
    return doc


prof = MachineProfile.load_default()
path = os.path.join(tempfile.mkdtemp(), "retino.flc")
pd = photo_doc(130.0)
pd.save(path)
back = Document.load(path)
check("progetto salvato e riaperto: la dimensione del punto è quella", back.layer(4).halftone_size == 130.0
      and back.layer(4).halftone_cell == 1.0)


def job_hash(doc):
    return hashlib.md5("\n".join(gcode.generate(doc, prof, gcode.JobOptions()).lines).encode()).hexdigest()


def burn(doc):
    """Millimetri percorsi con il laser acceso."""
    job = gcode.generate(doc, prof, gcode.JobOptions())
    total, x = 0.0, None
    for line in job.lines:
        mx = re.search(r"X(-?[\d.]+)", line)
        s = re.search(r"S([\d.]+)", line)
        if mx:
            nx = float(mx.group(1))
            if x is not None and s and float(s.group(1)) > 0 and not line.startswith("G0"):
                total += abs(nx - x)  # il tratto che finisce qui è stato fatto con il laser acceso
            x = nx
    return total


real = imaging._halftone
imaging._halftone = lambda dark, cell, angle, dot_size=100.0: old_halftone(dark, cell, angle)
h_old = job_hash(photo_doc())
imaging._halftone = real
check("G-code al 100%: identico, riga per riga, a quello di prima", job_hash(photo_doc()) == h_old
      and job_hash(photo_doc(100.0)) == h_old)
b60, b100, b140 = burn(photo_doc(60.0)), burn(photo_doc(100.0)), burn(photo_doc(140.0))
check("G-code: la dimensione arriva all'incisione (60% incide meno, 140% incide di più)", b60 < 0.6 * b100 < b100 < b140
      and job_hash(photo_doc(60.0)) != h_old, (round(b60), round(b100), round(b140)))
check("…e per gli altri metodi il G-code non cambia",
      job_hash(photo_doc(140.0, dither="jarvis")) == job_hash(photo_doc(dither="jarvis")))

# ================================================================== 6. anteprima sul piano
w = MainWindow()
w.resize(1400, 900)
w.show()
spin(0.3)
ed, cv = w.editor, w.canvas
src = photo_doc()
ed.doc.images["foto"] = src.images["foto"]
img = ImageShape("foto", 40.0, 30.0, layer=4)
ed.add([img])
c4 = ed.doc.layer(4)
c4.mode, c4.dither, c4.dpi = "image", "halftone", 127.0
cv.dither_preview = True


def preview_bits():
    q = cv.image_preview(img, c4)
    q = q.toImage() if hasattr(q, "toImage") else q
    return hashlib.md5(bytes(q.constBits())).hexdigest() if q is not None else None


p100 = preview_bits()
c4.halftone_size = 140.0
p140 = preview_bits()
c4.halftone_size = 100.0
check("anteprima «come verrà incisa» sul piano: cambia con la dimensione del punto, e torna uguale al 100%",
      p100 is not None and p140 != p100 and preview_bits() == p100)
c4.halftone_cell = 2.0
pc = preview_bits()
c4.halftone_cell = 1.0
c4.halftone_angle = 0.0
pa = preview_bits()
c4.halftone_angle = 45.0
check("…e anche con la cella e con l'angolo (prima restava l'immagine vecchia)", pc != p100 and pa != p100
      and preview_bits() == p100)

# ================================================================== 7. impostazioni del livello
cs_img = CutSettings(index=0, mode="image", dither="floyd", dpi=254.0)
dl = CutSettingsDialog(cs_img, prof)
dl.show()
spin(0.1)
check("impostazioni del livello: «Retino: dimensione del punto» c'è, al 100%, grigia con un altro metodo, spiegata",
      dl.hsize.value() == 100 and not dl.hsize.isEnabled() and not dl.hsize_name.isEnabled()
      and "100%" in dl.hsize.toolTip() and dl.hsize.minimum() == 50 and dl.hsize.maximum() == 150
      and dl.hnote.isHidden())
dl.dither.setCurrentIndex(dl.dither.findData("halftone"))
check("con «Mezzetinte» si può cambiare, e sotto compaiono le misure dei punti", dl.hsize.isEnabled()
      and dl.hcell.isEnabled() and not dl.hnote.isHidden() and "1.13" in dl.hnote.text() and "0.25" in dl.hnote.text(),
      dl.hnote.text())
dl.hsize.setValue(50)
t50 = dl.hnote.text()
dl.hcell.setValue(2.0)
t2 = dl.hnote.text()
check("le misure cambiano al cambiare della dimensione (50% → 0.56 e 0.13 mm) e della cella (2 mm → 1.13 e 0.25 mm)",
      "0.56" in t50 and "0.13" in t50 and "1.13" in t2 and "0.25" in t2, (t50, t2))
dl.dpi.setValue(127)
check("…e della risoluzione (127 dpi → righe a 0.20 mm)", "0.20" in dl.hnote.text(), dl.hnote.text())
dl.dpi.setValue(254)
dl.hcell.setValue(0.3)
dl.hsize.setValue(100)
warn = dl.hnote.text()
dl.hsize.setValue(150)
check("cella piccola: compare l'avviso dei punti più fini di una riga; alzando la dimensione sparisce",
      "⚠" in warn and "⚠" not in dl.hnote.text(), (warn, dl.hnote.text()))
dl.hsize.setValue(120)
v = dl.values()
check("«Applica» porta la dimensione nel livello insieme a cella e angolo", v["halftone_size"] == 120
      and abs(v["halftone_cell"] - 0.3) < 1e-9 and v["halftone_angle"] == 45 and v["dither"] == "halftone")
dl.dither.setCurrentIndex(dl.dither.findData("jarvis"))
check("tornando a un altro metodo misure e avvisi spariscono", dl.hnote.isHidden() and not dl.hsize.isEnabled())
dl.close()
cs_h = CutSettings(index=0, mode="image", dither="halftone", halftone_size=135.0, halftone_cell=0.8)
dl = CutSettingsDialog(cs_h, prof)
check("la finestra si apre con i valori del livello", dl.hsize.value() == 135 and abs(dl.hcell.value() - 0.8) < 1e-9
      and dl.hsize.isEnabled())
dl.close()

# ================================================================== 8. «Prepara foto»
ed.select([img])
c4.dither, c4.halftone_cell, c4.halftone_angle, c4.halftone_size = "jarvis", 1.0, 45.0, 100.0
orig_exec = PhotoDialog.exec
seen = {}


def run_dialog(setup, accept=True):
    def ex(self):
        self.show()
        spin(0.2)
        setup(self)
        seen["dlg"] = self
        return QDialog.Accepted if accept else QDialog.Rejected
    PhotoDialog.exec = ex
    w.photo_dialog()
    spin(0.2)
    PhotoDialog.exec = orig_exec


def vis(dlg, wdg):
    return wdg.isVisibleTo(dlg)


def shot(dlg):
    dlg._timer.stop()
    dlg._refresh()
    spin(0.05)
    q = dlg.v_res.qimg
    return hashlib.md5(bytes(q.constBits())).hexdigest() if q is not None else None


def setup_other(dlg):
    seen["hidden"] = not any(vis(dlg, x) for x in (dlg.hcell, dlg.hangle, dlg.hsize, dlg.hnote))
    seen["lv_other"] = dlg.layer_values()
    dlg.dither.setCurrentIndex(dlg.dither.findData("halftone"))
    spin(0.05)
    seen["shown"] = all(vis(dlg, x) for x in (dlg.hcell, dlg.hangle, dlg.hsize, dlg.hnote))
    seen["start"] = (dlg.hcell.value(), dlg.hangle.value(), dlg.hsize.value())
    seen["note"] = dlg.hnote.text()
    s100 = shot(dlg)
    dlg.hsize.setValue(140)
    seen["note140"] = dlg.hnote.text()
    seen["timer"] = dlg._timer.isActive()
    s140 = shot(dlg)
    dlg.hcell.setValue(2.5)
    seen["note_cell"] = dlg.hnote.text()
    s_cell = shot(dlg)
    dlg.hangle.setValue(0)
    s_ang = shot(dlg)
    seen["shots"] = (s100, s140, s_cell, s_ang)
    seen["lv"] = dlg.layer_values()
    dlg._accept()


run_dialog(setup_other)
check("«Prepara foto», altro metodo: cella, angolo e dimensione non si vedono e il retino del livello non viene toccato",
      seen["hidden"] and not any(k.startswith("halftone") for k in seen["lv_other"]), seen["lv_other"])
check("…scelto «Mezzetinte» compaiono, con i valori del livello e le misure dei punti",
      seen["shown"] and seen["start"] == (1.0, 45, 100) and "1.13" in seen["note"], (seen["start"], seen["note"]))
check("…le misure cambiano con la dimensione e con la cella", seen["note140"] != seen["note"]
      and seen["note_cell"] != seen["note140"] and "0.35" in seen["note140"], seen["note140"])
check("…ogni ritocco aggiorna l'anteprima (dimensione, cella, angolo danno tre immagini diverse)",
      seen["timer"] and None not in seen["shots"] and len(set(seen["shots"])) == 4, seen["shots"])
check("…e con «OK» finiscono nel livello della foto", c4.dither == "halftone" and c4.halftone_size == 140.0
      and c4.halftone_cell == 2.5 and c4.halftone_angle == 0.0 and seen["lv"]["halftone_size"] == 140.0,
      (c4.dither, c4.halftone_size, c4.halftone_cell, c4.halftone_angle))
ed.undo()
c4 = ed.doc.layer(4)
check("…un solo Ctrl+Z riporta il livello com'era", c4.dither == "jarvis" and c4.halftone_size == 100.0
      and c4.halftone_cell == 1.0 and c4.halftone_angle == 45.0, (c4.dither, c4.halftone_size, c4.halftone_cell))
img = [s for s in ed.doc.shapes if isinstance(s, ImageShape)][0]
ed.select([img])
c4.dither, c4.halftone_size, c4.halftone_cell = "halftone", 120.0, 0.6


def setup_keep(dlg):
    seen["open"] = (dlg.hsize.value(), dlg.hcell.value(), vis(dlg, dlg.hsize))
    dlg.dither.setCurrentIndex(dlg.dither.findData("floyd"))
    spin(0.05)
    seen["hidden2"] = not vis(dlg, dlg.hsize) and not vis(dlg, dlg.hnote)
    dlg._accept()


run_dialog(setup_keep)
c4 = ed.doc.layer(4)
check("livello già a mezzetinte: la finestra si apre con i suoi valori; passando a un altro metodo il retino del "
      "livello resta quello (non si perde)", seen["open"] == (120, 0.6, True) and seen["hidden2"]
      and c4.dither == "floyd" and c4.halftone_size == 120.0 and c4.halftone_cell == 0.6, (seen["open"], c4.halftone_size))
check("anteprima dei punti veri: usa il retino scelto",
      not np.array_equal(photo.engrave_preview(src.images["foto"], 40, 30, 127, "halftone", halftone_size=60.0)[0],
                         photo.engrave_preview(src.images["foto"], 40, 30, 127, "halftone")[0])
      and np.array_equal(photo.engrave_preview(src.images["foto"], 40, 30, 127, "halftone", halftone_size=100.0)[0],
                         photo.engrave_preview(src.images["foto"], 40, 30, 127, "halftone")[0]))

# ================================================================== 9. traduzioni
keys = set()
for rel in (("ui", "widgets.py"), ("ui", "panels_design.py"), ("ui", "dialogs_photo.py")):
    srcf = open(os.path.join(ROOT, "freelasercut", *rel), encoding="utf-8").read()
    for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', srcf):
        try:
            k = "".join(ast.literal_eval(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
        except (SyntaxError, ValueError):
            continue
        if any(t in k for t in ("retino", "Retino", "Mezzetinte", "punti si fondono", "più fini di una riga",
                                "più stretta di due righe")):
            keys.add(k)
check("testi delle mezzetinte trovati nel codice", len(keys) >= 9
      and any(k.startswith("Retino: dimensione del punto") for k in keys), len(keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k[:40] for k in keys if not loc.get(k)]
    bad = [k[:40] for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    check(f"traduzioni {lang}: tutti i testi, con gli stessi segnaposto", not miss and not bad, (miss, bad))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
