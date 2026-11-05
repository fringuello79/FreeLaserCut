# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.12.6: foto dei progetti .lbrn2.
- «Prepara foto» mostra la foto come appare sul piano (prima, con alcune XForm, compariva specchiata);
- sul piano non cambia nulla: ogni pixel resta esattamente dov'era;
- i tracciati con maniglie incomplete (solo c0y o solo c1y) non bloccano più l'apertura (errore «c0x»)."""
import sys, os, io, base64, math, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication
app = QApplication([])
from freelasercut.core import lbrn
from freelasercut.core.document import ImageShape, bake_mirror

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)

# foto 4×2 con 8 colori tutti diversi: si può seguire ogni pixel
W, H = 4, 2
COL = [(i * 30, 255 - i * 30, (i * 77) % 256) for i in range(W * H)]
im = Image.new("RGB", (W, H)); im.putdata(COL)
buf = io.BytesIO(); im.save(buf, "PNG")
DATA = base64.b64encode(buf.getvalue()).decode()

def bed_map(pix, w, h, tf):
    """colore -> punto sul piano del centro del pixel (riga 0 in alto, a y = h)."""
    pix = pix.convert("RGB")
    out = {}
    for j in range(pix.height):
        for i in range(pix.width):
            p = tf.map(QPointF((i + 0.5) / pix.width * w, h - (j + 0.5) / pix.height * h))
            out[pix.getpixel((i, j))] = (round(p.x(), 6), round(p.y(), 6))
    return out

def project(xform, extra=""):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<LightBurnProject AppVersion="2.1.04" FormatVersion="1">
  <CutSetting_Img type="Image"><index Value="0"/><name Value="C00"/><maxPower Value="40"/><speed Value="100"/></CutSetting_Img>
  <Shape Type="Bitmap" CutIndex="0" W="40" H="20" Data="{DATA}"><XForm>{xform}</XForm></Shape>
  {extra}
</LightBurnProject>"""

def load(xml):
    fp = os.path.join(tempfile.mkdtemp(), "prova.lbrn2")
    open(fp, "w", encoding="utf-8").write(xml)
    return lbrn.load(fp)

def straight_pixels(pix, tf, w, h):
    """I pixel guardati come in «Prepara foto» (riga 0 in alto, colonna 0 a sinistra) sono nel verso del piano?"""
    m = bed_map(pix, w, h, tf)
    a, b, c = m[pix.convert("RGB").getpixel((0, 0))], m[pix.convert("RGB").getpixel((1, 0))], \
        m[pix.convert("RGB").getpixel((0, 1))]
    # a destra della colonna 0 e sopra la riga 1, una volta tolta l'eventuale rotazione: basta il verso (determinante)
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = a[0] - c[0], a[1] - c[1]
    return ux * vy - uy * vx > 0

cases = {"1 0 0 -1 50 60": "tipica dei progetti .lbrn2", "1 0 0 1 50 60": "Y senza ribaltamento",
         "-1 0 0 1 50 60": "specchiata in orizzontale", "-1 0 0 -1 50 60": "ruotata di 180°",
         "0 1 -1 0 50 60": "ruotata di 90°", "0 1 1 0 50 60": "ruotata e specchiata",
         "2 0 0 1.5 50 60": "ingrandita, Y senza ribaltamento"}
for xf, name in cases.items():
    doc, _ = load(project(xf))
    s = [x for x in doc.shapes if isinstance(x, ImageShape)][0]
    a, b, c, d, e, f = (float(v) for v in xf.split())
    old_tf = QTransform(1, 0, 0, -1, -20, 10) * QTransform(a, b, c, d, e, f)   # com'era fino alla 0.12.5
    before = bed_map(im, 40, 20, old_tf)
    after = bed_map(doc.images[s.image_id], s.w, s.h, s.tf)
    check(f"XForm {name}: sul piano ogni pixel resta dov'era", before == after)
    check(f"XForm {name}: «Prepara foto» la mostra nel verso del piano (niente specchio)",
          s.tf.determinant() > 0 and straight_pixels(doc.images[s.image_id], s.tf, s.w, s.h))

doc, _ = load(project("1 0 0 -1 50 60"))
s = [x for x in doc.shapes if isinstance(x, ImageShape)][0]
check("XForm tipica: i pixel non vengono toccati", list(doc.images[s.image_id].convert("RGB").getdata()) == COL)

# bake_mirror su una foto dritta: niente da fare
p2, t2 = bake_mirror(im, 40, 20, QTransform())
check("foto senza specchio: bake_mirror non cambia nulla", p2 is im and t2 == QTransform())

# maniglie incomplete: prima KeyError 'c0x' («Impossibile aprire il file: 'c0x'»)
v = lbrn.parse_verts("V0 0c0y5c1x3V10 0c1y2V10 10c0x1V0 10")
check("vertici con maniglie incomplete: letti senza errori, maniglie ignorate", len(v) == 4 and
      all(c0 is None and c1 is None for _, c0, c1 in v))
path = """<Shape Type="Path" CutIndex="1"><XForm>1 0 0 1 0 0</XForm>
  <VertList>V0 0c0y5c1x3V10 0c1y2V10 10c0x1V0 10</VertList><PrimList>LineClosed</PrimList></Shape>"""
try:
    doc3, _ = load(project("1 0 0 -1 50 60", path))
    ok = len(doc3.shapes) == 2
except Exception as ex:  # noqa: BLE001
    ok, doc3 = False, ex
check("progetto con quel tracciato: si apre (foto + tracciato)", ok, "" if ok else repr(doc3))

# progetto salvato con la 0.12.5 (specchio nella trasformazione): raddrizzata all'apertura di «Prepara foto»
from freelasercut.ui.main_window import MainWindow
w = MainWindow()
doc = w.editor.doc
doc.images["vecchia"] = im.copy()
img = ImageShape("vecchia", 40, 20, 0)
img.set_transform(QTransform(1, 0, 0, -1, -20, 10) * QTransform(1, 0, 0, 1, 50, 60))
doc.add(img)
before = bed_map(im, 40, 20, img.tf)
w._unmirror_photo(img)
check("foto con specchio già nel progetto: raddrizzata, sul piano identica",
      img.tf.determinant() > 0 and bed_map(doc.images[img.image_id], img.w, img.h, img.tf) == before)
check("la vecchia immagine resta nel documento (Annulla torna indietro senza perdite)", "vecchia" in doc.images)
w.editor.undo()
s = [x for x in w.editor.doc.shapes if isinstance(x, ImageShape)][0]
check("Annulla: torna esattamente com'era", s.image_id == "vecchia" and s.tf.determinant() < 0)
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
