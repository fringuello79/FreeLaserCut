# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.3: immagini con lo sfondo trasparente (PNG), da una domanda arrivata da GitHub.

Prima: sulla tela la parte trasparente si vedeva bianca e copriva quello che c'era sotto, il clic la prendeva in tutto
il riquadro, e con Negativo (o luminosità e contrasto abbassati) lo sfondo trasparente diventava nero e si incideva.
Ora: sulla tela resta solo la parte che si vede, il clic sul trasparente passa a quello che c'è sotto, il trasparente
non si incide mai. Le immagini senza trasparenza e le regolazioni neutre danno lo stesso G-code di prima, al byte."""
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
import math  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core import gcode, imaging, io_formats, photo  # noqa: E402
from freelasercut.core.document import Document, GroupShape, ImageShape, RectShape, SpecialShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []
UI = os.environ["FLC_UI"]
D = tempfile.mkdtemp()


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def spin(sec):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


# ---------------------------------------------------------------- l'immagine di prova (asimmetrica)
# 120 × 80 pixel su 60 × 40 mm (2 pixel per mm). Riga 0 = in alto.
#   righe 0-39 (in alto), colonne 0-29: nero pieno; colonne 30-59: bianco pieno; colonne 60-69: nero che sfuma
#   (trasparenza da piena a quasi nulla); colonna 100, tutte le righe: linea nera sottile (1 pixel = 0,5 mm).
#   Tutto il resto: trasparente, con il colore nero (come lo scrivono molti programmi: il caso peggiore).
W, H, WMM, HMM = 120, 80, 60.0, 40.0


def test_rgba():
    a = np.zeros((H, W, 4), np.uint8)
    a[:40, 0:30] = (0, 0, 0, 255)
    a[:40, 30:60] = (255, 255, 255, 255)
    a[:40, 60:70, 3] = np.linspace(255, 26, 10).astype(np.uint8)[None, :]
    a[:, 100] = (0, 0, 0, 255)
    return a


RGBA = test_rgba()
ALPHA = RGBA[..., 3].astype(np.float32) / 255.0


def opaque_version():
    """La stessa immagine senza trasparenza (stessi colori): la parte che si vede deve incidersi uguale."""
    b = RGBA.copy()
    b[..., 3] = 255
    return Image.fromarray(b, "RGBA")


_N = [0]


def new_id():
    """Nome nuovo per ogni immagine di prova, come fa il programma (l'anteprima sulla tela si ricorda per nome)."""
    _N[0] += 1
    return f"p{_N[0]}"


def make_doc(img, tf=None, group_tf=None):
    doc = Document()
    iid = new_id()
    doc.images[iid] = img
    im = ImageShape(iid, WMM, HMM, layer=2)
    im.set_transform(tf if tf is not None else QTransform.fromTranslate(50, 50))
    doc.layer(2).mode = "image"
    if group_tf is not None:
        g = GroupShape([im])
        g.set_transform(group_tf)
        doc.add(g)
    else:
        doc.add(im)
    return doc, im


def set_layer(doc, dither="grayscale", negative=False, dpi=127.0):
    cs = doc.layer(2)
    cs.dither, cs.negative, cs.dpi = dither, negative, dpi
    return cs


def job_lines(doc):
    return gcode.generate(doc, MachineProfile(), gcode.JobOptions(start_from="absolute")).lines


def old_rule():
    """Il codice di prima (0.22.2): le regolazioni sullo scuro già fuso col bianco, senza guardare la trasparenza."""
    keep = imaging.adjust_alpha

    def old(dark, alpha, b=0.0, c=0.0, g=1.0, n=False):
        return imaging.adjust(dark, b, c, g, n)
    return keep, old


def lines_old(doc):
    keep, old = old_rule()
    imaging.adjust_alpha = old
    try:
        return job_lines(doc)
    finally:
        imaging.adjust_alpha = keep


def leaf_tf(doc):
    s = doc.shapes[0]
    return [(leaf, tf) for leaf, tf in s.leaves() if isinstance(leaf, ImageShape)][0]


def burned(doc):
    """Celle accese del lavoro: [(x, y, potenza %)] sul piano, dalle righe preparate per l'immagine."""
    leaf, tf = leaf_tf(doc)
    leaf._doc_image = doc.images[leaf.image_id]
    lines, _rot, _first = gcode._image_lines(leaf, tf, doc.layer(2), 256, None)
    step = 25.4 / doc.layer(2).dpi
    out = []
    for y, segs in lines:
        for xa, xb, p in segs:
            n = max(1, int(round((xb - xa) / step)))
            out += [(xa + (k + 0.5) * (xb - xa) / n, y, p) for k in range(n)]
    return out


def to_px(doc, x, y):
    """Punto del piano -> pixel dell'immagine (colonna, riga), stessa convenzione del programma."""
    leaf, tf = leaf_tf(doc)
    inv, _ok = tf.inverted()
    q = inv.map(QPointF(x, y))
    return q.x() / leaf.w * W, (1.0 - q.y() / leaf.h) * H


def px_to_bed(doc, c, r):
    leaf, tf = leaf_tf(doc)
    q = tf.map(QPointF(c / W * leaf.w, (1.0 - r / H) * leaf.h))
    return q.x(), q.y()


def in_transparent(doc, pts, margin_px):
    """Celle accese che cadono dove l'immagine è del tutto trasparente (anche a margin_px pixel di distanza)."""
    bad = []
    m = int(math.ceil(margin_px))
    for x, y, _p in pts:
        c, r = to_px(doc, x, y)
        ci, ri = int(math.floor(c)), int(math.floor(r))
        r0, r1, c0, c1 = max(0, ri - m), min(H, ri + m + 1), max(0, ci - m), min(W, ci + m + 1)
        if r0 >= r1 or c0 >= c1 or ALPHA[r0:r1, c0:c1].max() == 0:
            bad.append((round(x, 2), round(y, 2)))
    return bad


def cells_in(doc, pts, c0, c1, r0, r1):
    """Celle accese con il centro dentro il rettangolo di pixel [c0, c1) × [r0, r1)."""
    out = set()
    for x, y, p in pts:
        c, r = to_px(doc, x, y)
        if c0 <= c < c1 and r0 <= r < r1:
            out.add((round(x, 3), round(y, 3), round(p, 2)))
    return out


STEP_PX = (25.4 / 127.0) / (WMM / W)  # una cella del laser in pixel dell'immagine (0,4 a 127 dpi)
MARGIN = STEP_PX + 1.5  # una cella più il campionamento (interpolazione fra due pixel)
DITHERS = ("grayscale", "threshold", "floyd", "halftone")


def margin_for(cs, k=1.0):
    """Margine (pixel) oltre il quale una cella accesa conta come «nel trasparente». Con le mezzetinte il punto di
    una cella del retino nasce dal disegno e può allargarsi fino a mezza cella oltre il bordo (come vicino al bianco)."""
    m = MARGIN * k
    if cs.dither == "halftone":
        m += (cs.halftone_cell / 2.0) / (WMM / W) * k
    return m

# ================================================================ A. il modello: alpha_of e adjust_alpha
check("immagine in grigio (L): nessuna trasparenza", imaging.alpha_of(Image.new("L", (4, 4))) is None)
check("immagine a colori (RGB): nessuna trasparenza", imaging.alpha_of(Image.new("RGB", (4, 4))) is None)
check("RGBA tutta piena: nessuna trasparenza (resta tutto come prima)",
      imaging.alpha_of(Image.new("RGBA", (4, 4), (10, 20, 30, 255))) is None)
a = imaging.alpha_of(Image.fromarray(RGBA, "RGBA"))
check("RGBA con lo sfondo trasparente: trasparenza letta, 0 dove è trasparente, 1 dove è piena",
      a is not None and a.shape == (H, W) and a[60, 10] == 0 and a[10, 10] == 1.0 and 0 < a[10, 65] < 1, None if a is None
      else (a[60, 10], a[10, 10], a[10, 65]))
la = Image.fromarray(RGBA, "RGBA").convert("LA")
check("grigio con trasparenza (LA): letta", imaging.alpha_of(la) is not None and imaging.alpha_of(la)[60, 10] == 0)
rgb_pal = RGBA[..., :3].copy()
rgb_pal[RGBA[..., 3] == 0] = (255, 0, 255)  # il colore trasparente della tavolozza: uno solo, diverso dal disegno
pal = Image.fromarray(rgb_pal, "RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=16)
pal.info["transparency"] = pal.getpixel((10, 60))
check("tavolozza con un colore trasparente (P): letta",
      imaging.alpha_of(pal) is not None and imaging.alpha_of(pal)[60, 10] == 0)
d = np.array([[0.0, 1.0, 0.5, 0.3]], np.float32)
al = np.array([[0.0, 1.0, 1.0, 0.5]], np.float32)
rng = np.random.default_rng(7)
al_r = rng.random((64, 64)).astype(np.float32)
d_r = (rng.random((64, 64)) * al_r).astype(np.float32)  # scuro già moltiplicato per la trasparenza, valori qualsiasi
check("regolazioni neutre: esattamente come prima, al bit (anche con trasparenze e grigi qualsiasi)",
      np.array_equal(imaging.adjust_alpha(d_r, al_r), imaging.adjust(d_r))
      and np.array_equal(imaging.adjust_alpha(d_r, al_r, 0, 0, 1.0005, False), imaging.adjust(d_r, 0, 0, 1.0005)))
check("senza trasparenza: esattamente come prima, anche in negativo",
      np.array_equal(imaging.adjust_alpha(d, None, -30, 20, 1.4, True), imaging.adjust(d, -30, 20, 1.4, True)))
neg = imaging.adjust_alpha(d, al, negative=True)
check("in negativo il trasparente resta 0, il nero pieno diventa 0, il grigio pieno 0,5, il mezzo trasparente scuro "
      "si inverte e resta a metà", np.allclose(neg, [[0.0, 0.0, 0.5, 0.2]], atol=1e-6), neg.round(3).tolist())
dk = imaging.adjust_alpha(d, al, brightness=-50)
check("luminosità abbassata: il trasparente resta 0", dk[0, 0] == 0 and dk[0, 2] > 0.5, dk.round(3).tolist())
ct = imaging.adjust_alpha(d, al, contrast=-50)
check("contrasto abbassato: il trasparente resta 0 (prima diventava grigio)", ct[0, 0] == 0
      and imaging.adjust(d, contrast=-50)[0, 0] > 0, ct.round(3).tolist())
thin = np.zeros((2000, 1000), np.float32)
thin[:, 777] = 1.0
mk, f = imaging.alpha_hit_mask(thin)
check("maschera del clic ridotta (lato lungo al massimo 512) senza perdere una linea di 1 pixel",
      max(mk.shape) <= 512 and mk[:, 777 // f].all() and mk.sum() == mk.shape[0], (mk.shape, f))

# ================================================================ B. compatibilità: stesso G-code di prima
same_opaque = True
for dith in DITHERS:
    for neg_, br, ct_ in ((False, 0, 0), (True, 0, 0), (False, -40, 30), (True, 25, -35)):
        for img in (Image.fromarray(RGBA[..., 0], "L"), opaque_version()):
            doc, im = make_doc(img)
            set_layer(doc, dith, neg_)
            im.brightness, im.contrast = br, ct_
            if job_lines(doc) != lines_old(doc):
                same_opaque = False
                print("    diverso:", dith, neg_, br, ct_, img.mode)
check("immagine senza trasparenza (grigio e RGBA tutta piena): G-code identico a prima, con ogni retinatura, "
      "negativo, luminosità e contrasto", same_opaque)
same_neutral = True
for dith in DITHERS:
    doc, im = make_doc(Image.fromarray(RGBA, "RGBA"))
    set_layer(doc, dith, False)
    if job_lines(doc) != lines_old(doc):
        same_neutral = False
        print("    diverso:", dith)
check("PNG trasparente con le regolazioni neutre: G-code identico a prima, con ogni retinatura", same_neutral)

# ================================================================ C. incisione: il trasparente non si incide mai
CASES = (("negativo", True, 0, 0), ("luminosità −50", False, -50, 0), ("contrasto −50", False, 0, -50),
         ("negativo, luminosità −30 e contrasto −40", True, -30, -40))
for label, neg_, br, ct_ in CASES:
    worst = {}
    for dith in DITHERS:
        doc, im = make_doc(Image.fromarray(RGBA, "RGBA"))
        set_layer(doc, dith, neg_)
        im.brightness, im.contrast = br, ct_
        bad = in_transparent(doc, burned(doc), margin_for(doc.layer(2)))
        if bad:
            worst[dith] = (len(bad), bad[:2])
    check(f"{label}: nessuna cella accesa nel trasparente (scala di grigi, soglia, diffusione, mezzetinte)", not worst,
          worst)

# con il codice di prima il negativo incideva lo sfondo: la prova se ne accorge
doc, im = make_doc(Image.fromarray(RGBA, "RGBA"))
set_layer(doc, "threshold", True)
keep, old = old_rule()
imaging.adjust_alpha = old
try:
    before = in_transparent(doc, burned(doc), MARGIN)
finally:
    imaging.adjust_alpha = keep
check("(controllo della prova: con la regola di prima il negativo accendeva lo sfondo trasparente)", len(before) > 500,
      len(before))

# la parte che si vede si incide come la stessa immagine senza trasparenza
for label, neg_, br, ct_ in CASES:
    ok = True
    for dith in ("grayscale", "threshold"):
        docA, imA = make_doc(Image.fromarray(RGBA, "RGBA"))
        docB, imB = make_doc(opaque_version())
        for dd, ii in ((docA, imA), (docB, imB)):
            set_layer(dd, dith, neg_)
            ii.brightness, ii.contrast = br, ct_
        cA = cells_in(docA, burned(docA), 2, 58, 2, 38)  # parte piena, lontana dai bordi
        cB = cells_in(docB, burned(docB), 2, 58, 2, 38)
        if cA != cB or not cA and not cB and dith == "grayscale" and neg_:
            ok = False
            print("    diverso:", label, dith, len(cA), len(cB))
    check(f"{label}: la parte piena si incide come la stessa immagine senza trasparenza", ok)

doc, im = make_doc(Image.fromarray(RGBA, "RGBA"))
cs = set_layer(doc, "grayscale", False)
cs.power_min, cs.power_max = 0.0, 100.0
im.contrast = -1  # regolazione quasi neutra ma non neutra: passa dalla strada nuova
pts = burned(doc)
black = [p for x, y, p in pts if 4 <= to_px(doc, x, y)[0] < 26 and 4 <= to_px(doc, x, y)[1] < 36]
ramp = sorted((to_px(doc, x, y)[0], p) for x, y, p in pts if 60.5 <= to_px(doc, x, y)[0] < 69.5
              and 4 <= to_px(doc, x, y)[1] < 36)
check("bordo sfumato: la potenza scende dal nero pieno verso il trasparente, senza salti",
      black and ramp and max(p for _c, p in ramp) <= max(black) + 1e-6 and ramp[0][1] > ramp[-1][1] > 0
      and all(b[1] <= a_[1] + 1.0 for a_, b in zip(ramp, ramp[1:]) if b[0] > a_[0] + 0.5),
      (round(max(black), 1) if black else None, [round(p, 1) for _c, p in ramp[:: max(1, len(ramp) // 6)]]))

# il lavoro vero (righe di G-code): in negativo nessun tratto acceso nel trasparente
doc, im = make_doc(Image.fromarray(RGBA, "RGBA"))
set_layer(doc, "threshold", True)
job = gcode.generate(doc, MachineProfile(), gcode.JobOptions(start_from="absolute"))


def burn_points(job, step=0.05):
    x = y = s = 0.0
    on, mode, pts = False, "0", []
    ox, oy = job.out_to_bed
    for ln in job.lines:
        t = ln.split(";")[0].strip().upper()
        if not t:
            continue
        if t.startswith(("M3", "M4")):
            on = True
        if t.startswith("M5"):
            on = False
        g = re.match(r"G([01])\b", t)
        if g:
            mode = g.group(1)
        vals = {k: float(v) for k, v in re.findall(r"([XYS])(-?[\d.]+)", t)}
        s = vals.get("S", s)
        nx, ny = vals.get("X", x), vals.get("Y", y)
        if mode == "1" and on and s > 0 and (nx, ny) != (x, y):
            n = max(1, int(math.hypot(nx - x, ny - y) / step))
            pts += [(x + (nx - x) * k / n + ox, y + (ny - y) * k / n + oy, s) for k in range(n + 1)]
        x, y = nx, ny
    return pts


bp = burn_points(job)
check("lavoro intero in negativo: si incide la parte bianca piena e niente nel trasparente",
      len(bp) > 100 and not in_transparent(doc, bp, MARGIN + 1), (len(bp), in_transparent(doc, bp, MARGIN + 1)[:3]))

# ================================================================ D. trasformazioni, gruppo
TRANSFORMS = (
    ("scalata", QTransform.fromScale(2.0, 1.5) * QTransform.fromTranslate(30, 40), None),
    ("ruotata di 30°", QTransform().rotate(30) * QTransform.fromTranslate(120, 60), None),
    ("specchiata", QTransform.fromScale(-1, 1) * QTransform.fromTranslate(150, 50), None),
    ("in un gruppo spostato e ruotato", QTransform(), QTransform().rotate(-20) * QTransform.fromTranslate(80, 120)),
)
for label, tf, gtf in TRANSFORMS:
    worst = {}
    for dith in ("grayscale", "threshold", "halftone"):
        doc, im = make_doc(Image.fromarray(RGBA, "RGBA"), tf, gtf)
        set_layer(doc, dith, True)
        im.contrast = -30
        pts = burned(doc)
        bad = in_transparent(doc, pts, margin_for(doc.layer(2), 2.5))  # scalata o ruotata: una cella copre più pixel
        if bad or not pts:
            worst[dith] = (len(pts), len(bad), bad[:2])
    check(f"{label}, in negativo: nessuna cella accesa nel trasparente", not worst, worst)
# verso: il bianco pieno sta in alto a sinistra dell'immagine; in negativo si incide lì (anche specchiata)
for label, tf, gtf in TRANSFORMS:
    doc, im = make_doc(Image.fromarray(RGBA, "RGBA"), tf, gtf)
    set_layer(doc, "threshold", True)
    pts = burned(doc)
    cols = [to_px(doc, x, y)[0] for x, y, _p in pts]
    rows = [to_px(doc, x, y)[1] for x, y, _p in pts]
    check(f"{label}: in negativo si incide il bianco pieno (in alto, colonne 30-59), nel verso giusto",
          pts and 28 <= min(cols) and max(cols) <= 62 and max(rows) <= 41, (round(min(cols), 1), round(max(cols), 1),
                                                                            round(max(rows), 1)) if pts else 0)

# ================================================================ E. Prepara foto e vettorizzazione
dots, _k = photo.engrave_preview(Image.fromarray(RGBA, "RGBA"), WMM, HMM, 127.0, "threshold", negative=True)
dh, dw = dots.shape
yy, xx = np.nonzero(dots > 0.5)
alpha_small = cv2.resize(ALPHA, (dw, dh), interpolation=cv2.INTER_AREA)
check("Prepara foto, anteprima dei punti in negativo: nessun punto nel trasparente",
      len(yy) > 50 and alpha_small[yy, xx].min() > 0, (len(yy), float(alpha_small[yy, xx].min()) if len(yy) else None))
dots2, _k = photo.engrave_preview(Image.fromarray(RGBA[..., 0], "L"), WMM, HMM, 127.0, "threshold", negative=True)
keep_a, old_a = old_rule()
imaging.adjust_alpha = old_a
try:
    dots3, _k = photo.engrave_preview(Image.fromarray(RGBA[..., 0], "L"), WMM, HMM, 127.0, "threshold", negative=True)
finally:
    imaging.adjust_alpha = keep_a
check("…con un'immagine senza trasparenza come prima", np.array_equal(dots2, dots3))
from freelasercut.ui.dialogs_trace import TraceDialog  # noqa: E402

shp = ImageShape(new_id(), WMM, HMM)
shp.brightness = -50
td = TraceDialog(shp, Image.fromarray(RGBA, "RGBA"))
check("Vettorizza con la luminosità abbassata: il trasparente resta bianco (non diventa una zona da vettorizzare)",
      float(td.dark[60, 10]) == 0.0 and float(td.dark[10, 10]) > 0.9, (float(td.dark[60, 10]), float(td.dark[10, 10])))
td.close()

# ================================================================ F. formati e progetto salvato
fmt_ok = {}
src = Image.fromarray(RGBA, "RGBA")
p_png = os.path.join(D, "rgba.png")
src.save(p_png)
p_la = os.path.join(D, "la.png")
src.convert("LA").save(p_la)
p_pal = os.path.join(D, "pal.png")
pal.save(p_pal, transparency=pal.info["transparency"])
p16 = os.path.join(D, "rgba16.png")
bgra16 = cv2.cvtColor(RGBA, cv2.COLOR_RGBA2BGRA).astype(np.uint16) * 257
cv2.imwrite(p16, bgra16)
files = [("RGBA", p_png), ("LA", p_la), ("tavolozza", p_pal), ("16 bit con trasparenza", p16)]
try:
    p_webp = os.path.join(D, "rgba.webp")
    src.save(p_webp, lossless=True)
    files.append(("WebP", p_webp))
except Exception as ex:  # noqa: BLE001
    print("    WebP non disponibile:", ex)
for label, path in files:
    doc = Document()
    sh = io_formats.import_image(path, doc)
    img = doc.images[sh[0].image_id]
    al_ = imaging.alpha_of(img)
    fmt_ok[label] = al_ is not None and al_.shape == (H, W) and al_[60, 10] == 0 and al_[10, 10] > 0.99
check("importati con la trasparenza: " + ", ".join(fmt_ok), all(fmt_ok.values()), fmt_ok)
doc, im = make_doc(Image.fromarray(RGBA, "RGBA"))
set_layer(doc, "threshold", True)
pj = os.path.join(D, "progetto.flcut")
doc.save(pj)
doc2 = Document.load(pj)
lines_a = job_lines(doc)
lines_b = job_lines(doc2)
check("progetto salvato e riaperto: la trasparenza resta e il lavoro è lo stesso",
      imaging.alpha_of(doc2.images[im.image_id]) is not None and lines_a == lines_b)

# ================================================================ G. tela: si vede solo la parte che si vede
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1300, 900)
w.show()
spin(0.3)
ed, cv = w.editor, w.canvas
cv.dither_preview = False


def zoom_on(r, k=10.0):
    """10 pixel per mm, centrato sul riquadro r (nel Banco «adatta» lascia poco spazio per i pannelli)."""
    spin(0.8)  # nel Banco, dopo un cambio di progetto, la vista si adatta da sola poco dopo: si aspetta che finisca
    cv.resetTransform()
    cv.scale(k, k)
    c = r.center()
    cv.centerOn(QPointF(c.x(), -c.y()))
    spin(0.1)


def preview_arr(im, cs):
    qi = cv.image_preview(im, cs)
    if qi is None:
        return None
    if not qi.hasAlphaChannel():
        return None
    qi = qi.convertToFormat(qi.Format.Format_RGBA8888)
    return np.frombuffer(qi.constBits(), np.uint8).reshape(qi.height(), qi.width(), 4).copy()


doc, im = make_doc(Image.fromarray(RGBA, "RGBA"))
ed.set_document(doc)
cs = set_layer(doc, "threshold", False)
arr = preview_arr(im, cs)
check("anteprima sulla tela: trasparente dove l'immagine è trasparente, piena dove è piena, sfumata nel bordo",
      arr is not None and arr[60, 10, 3] == 0 and arr[60, 110, 3] == 0 and arr[10, 10, 3] == 255
      and arr[10, 45, 3] == 255 and 0 < arr[10, 65, 3] < 255 and arr[40, 100, 3] == 255,
      None if arr is None else (arr[60, 10, 3], arr[10, 10, 3], arr[10, 65, 3]))
check("…nel verso giusto: il nero in alto a sinistra, il bianco accanto",
      arr is not None and arr[10, 10, 0] < 30 and arr[10, 45, 0] > 225 and arr[70, 10, 3] == 0)
cs.negative = True
arr = preview_arr(im, cs)
check("…in negativo: il bianco pieno diventa nero, il trasparente resta trasparente",
      arr is not None and arr[10, 45, 0] < 30 and arr[10, 45, 3] == 255 and arr[60, 10, 3] == 0)
cs.negative = False
cv.dither_preview = True
for dith in ("threshold", "grayscale", "floyd"):
    cs = set_layer(doc, dith, True)
    arr = preview_arr(im, cs)
    hh, ww = (arr.shape[:2] if arr is not None else (1, 1))
    r_t, c_t = int(0.85 * hh), int(0.1 * ww)  # in basso a sinistra: trasparente
    r_w, c_w = int(0.25 * hh), int(0.375 * ww)  # bianco pieno (in negativo: punti accesi)
    check(f"anteprima dei punti veri ({dith}, negativo): il trasparente resta trasparente, il bianco pieno si accende",
          arr is not None and arr[r_t, c_t, 3] == 0 and arr[r_w, c_w, 3] == 255 and arr[r_w, c_w, 0] < 30,
          None if arr is None else (arr[r_t, c_t].tolist(), arr[r_w, c_w].tolist()))
cv.dither_preview = False
docg, img_ = make_doc(Image.fromarray(RGBA[..., 0], "L"))
ed.set_document(docg)
qi = cv.image_preview(img_, set_layer(docg, "threshold", False))
check("immagine senza trasparenza: sulla tela come prima (grigio pieno, senza canale di trasparenza)",
      not qi.hasAlphaChannel())
docg2, img2_ = make_doc(opaque_version())
ed.set_document(docg2)
qi = cv.image_preview(img2_, set_layer(docg2, "threshold", True))
check("…anche un PNG con il canale di trasparenza ma tutto pieno", not qi.hasAlphaChannel())

# un rettangolo sotto l'immagine si vede attraverso il trasparente; il clic sul trasparente lo prende
doc = Document()
iid = new_id()
doc.images[iid] = Image.fromarray(RGBA, "RGBA")
rect = RectShape(20, 20, layer=1)  # contorno da 20 × 20 mm
rect.set_transform(QTransform.fromTranslate(60, 52))
doc.add(rect)
im = ImageShape(iid, WMM, HMM, layer=2)
im.set_transform(QTransform.fromTranslate(50, 50))
doc.layer(2).mode = "image"
doc.add(im)  # l'immagine sta sopra il rettangolo
ed.set_document(doc)
ed.select([])
zoom_on(im.bounds())
tol = cv.px(6)
check("(controllo della prova: con questo zoom la tolleranza del clic è sotto i 2 mm)", tol < 2.0, round(tol, 3))
# rettangolo da (60, 52) a (80, 72) sul piano. Il bordo in basso (y = 52) passa nella metà bassa dell'immagine, che è
# trasparente; il bordo in alto (y = 72) passa nella metà alta, dove c'è il nero pieno
grab = cv.viewport().grab().toImage()
shot = os.path.join(D, "tela.png")
grab.save(shot)
vp = cv.to_view(QPointF(70, 52))
found = False
for dx in range(-3, 4):
    for dy in range(-3, 4):
        c = grab.pixelColor(int(vp.x()) + dx, int(vp.y()) + dy)
        found = found or (c.blue() - c.red() > 60)
check("sulla tela il contorno del rettangolo si vede attraverso la parte trasparente (prima era coperto di bianco)",
      found, shot)
hit_low = cv.hit_shape(QPointF(70, 52))
check("clic sul bordo del rettangolo, dove l'immagine sopra è trasparente: si prende il rettangolo", hit_low is rect,
      type(hit_low).__name__)
check("clic sul nero pieno dell'immagine: si prende l'immagine", cv.hit_shape(QPointF(55, 80)) is im)
check("clic sul trasparente lontano da tutto: niente", cv.hit_shape(QPointF(95, 55)) is None,
      type(cv.hit_shape(QPointF(95, 55))).__name__)
check("clic sulla linea sottile (mezzo millimetro) nella parte trasparente: si prende l'immagine",
      cv.hit_shape(QPointF(50 + 50.25, 55)) is im)
check("clic sulla parte sfumata del bordo: si prende l'immagine", cv.hit_shape(QPointF(50 + 32.5, 80)) is im)
ed.select([im])
spin(0.05)
check("immagine già selezionata: si prende da tutto il riquadro, anche sul trasparente (per trascinarla)",
      cv.hit_shape(QPointF(95, 55)) is im and cv.hit_shape(QPointF(70, 52)) is im)
ed.select([])
# ruotata e specchiata: il clic segue l'immagine
for label, tf in (("ruotata di 30°", QTransform().rotate(30) * QTransform.fromTranslate(120, 60)),
                  ("specchiata", QTransform.fromScale(-1, 1) * QTransform.fromTranslate(150, 50))):
    doc = Document()
    iid = new_id()
    doc.images[iid] = Image.fromarray(RGBA, "RGBA")
    imr = ImageShape(iid, WMM, HMM, layer=2)
    imr.set_transform(tf)
    doc.layer(2).mode = "image"
    doc.add(imr)
    ed.set_document(doc)
    ed.select([])
    zoom_on(imr.bounds())
    on_black = QPointF(*px_to_bed(doc, 10, 10))
    on_clear = QPointF(*px_to_bed(doc, 30, 65))
    check(f"{label}: clic sul nero pieno → l'immagine, sul trasparente → niente",
          cv.hit_shape(on_black) is imr and cv.hit_shape(on_clear) is None)
# immagine senza trasparenza: come prima, si prende in tutto il riquadro
doc = Document()
iid = new_id()
doc.images[iid] = Image.fromarray(RGBA[..., 0], "L")
imo = ImageShape(iid, WMM, HMM, layer=2)
imo.set_transform(QTransform.fromTranslate(50, 50))
doc.add(imo)
ed.set_document(doc)
ed.select([])
spin(0.1)
check("immagine senza trasparenza: si prende in tutto il riquadro, come prima", cv.hit_shape(QPointF(95, 55)) is imo)

# ritaglio con una forma: fuori dalla forma e nel trasparente non si incide
doc = Document()
iid = new_id()
doc.images[iid] = Image.fromarray(RGBA, "RGBA")
imc = ImageShape(iid, WMM, HMM, layer=2)
imc.set_transform(QTransform.fromTranslate(50, 50))
doc.layer(2).mode = "image"
doc.add(imc)
hs = SpecialShape("heart", 30, 30, layer=1)
hs.set_transform(QTransform.fromTranslate(60, 55))
doc.add(hs)
ed.set_document(doc)
ed.select([imc, hs])
spin(0.05)
ok_clip = ed.clip_photo()
set_layer(doc, "threshold", True)
pts = burned(doc) if ok_clip else []
check("foto ritagliata con una forma, in negativo: nessuna cella accesa nel trasparente",
      ok_clip and pts and not in_transparent(doc, pts, MARGIN), (ok_clip, len(pts)))

w.editor.dirty = False
w.close()

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.exit(0 if ok == len(results) else 1)
