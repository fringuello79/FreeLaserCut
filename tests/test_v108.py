# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10.8: progetti LightBurn (.lbrn2) aperti dritti.
- le foto non si aprono più specchiate in verticale (issue #3);
- i testi con il tracciato di riserva restano dove LightBurn li aveva messi (prima finivano lontani)."""
import sys, os, io, base64, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
app = QApplication([])
from freelasercut.core import lbrn
from freelasercut.core.document import ImageShape, TextShape

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)

# foto 4×2 pixel: riga in alto rossa, riga in basso blu
im = Image.new("RGB", (4, 2)); im.putdata([(255, 0, 0)] * 4 + [(0, 0, 255)] * 4)
buf = io.BytesIO(); im.save(buf, "PNG")
DATA = base64.b64encode(buf.getvalue()).decode()

def project(xform, text=""):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<LightBurnProject AppVersion="2.1.04" FormatVersion="1">
  <CutSetting_Img type="Image"><index Value="0"/><name Value="C00"/><maxPower Value="40"/><speed Value="100"/></CutSetting_Img>
  <Shape Type="Bitmap" CutIndex="0" W="40" H="20" Data="{DATA}"><XForm>{xform}</XForm></Shape>
  {text}
</LightBurnProject>"""

def load(xml):
    fp = os.path.join(tempfile.mkdtemp(), "prova.lbrn2")
    open(fp, "w", encoding="utf-8").write(xml)
    return lbrn.load(fp)[0]

def rows_y(doc):
    s = [x for x in doc.shapes if isinstance(x, ImageShape)][0]
    leaf, tf = list(s.leaves())[0]
    top_row = tf.map(QPointF(leaf.w / 2, leaf.h - 0.1))   # FreeLaserCut: la prima riga (rossa) sta a y = h
    bottom_row = tf.map(QPointF(leaf.w / 2, 0.1))
    return top_row.y(), bottom_row.y(), tf.map(leaf.local_path()).boundingRect()

# XForm tipica di LightBurn per le foto: Y ribaltata (1 0 0 -1)
red, blue, r = rows_y(load(project("1 0 0 -1 50 60")))
check("foto da LightBurn (XForm 1 0 0 −1): la riga in alto resta in alto, non più specchiata", red > blue, f"rossa y={red:.1f} blu y={blue:.1f}")
check("foto da LightBurn: stesso posto e stesse misure (centro 50,60, 40 × 20 mm)",
      abs(r.center().x() - 50) < 1e-6 and abs(r.center().y() - 60) < 1e-6 and abs(r.width() - 40) < 1e-6
      and abs(r.height() - 20) < 1e-6, f"{r.center().x():.1f},{r.center().y():.1f} {r.width():.1f}×{r.height():.1f}")
red2, blue2, r2 = rows_y(load(project("1 0 0 1 50 60")))
check("foto già ribaltata in LightBurn (XForm 1 0 0 1): resta ribaltata come in LightBurn", red2 < blue2)
red3, blue3, r3 = rows_y(load(project("0 1 -1 0 50 60")))
check("foto ruotata di 90° in LightBurn: ingombro ruotato (20 × 40 mm)", abs(r3.width() - 20) < 1e-6 and abs(r3.height() - 40) < 1e-6)
doc = load(project("1 0 0 -1 50 60"))
s = [x for x in doc.shapes if isinstance(x, ImageShape)][0]
pix = doc.images[s.image_id].convert("RGB")
check("i pixel della foto non vengono toccati: Prepara foto la mostra dritta", pix.getpixel((0, 0)) == (255, 0, 0)
      and pix.getpixel((0, 1)) == (0, 0, 255))

# testo con il tracciato di riserva: la sua XForm è completa, non relativa al testo
TXT = """<Shape Type="Text" CutIndex="1" Font="Arial,-1,4096,5,400,0,0,0,0,0" Str="CIAO" H="5" LS="0" LnS="0" Ah="1" Av="2" Weld="0" HasBackupPath="1">
    <BackupPath Type="Path" CutIndex="1"><XForm>1 0 0 1 352 115</XForm>
      <VertList>V-6 0c0x1c1x1V6 0c0x1c1x1V6 4c0x1c1x1V-6 4c0x1c1x1</VertList><PrimList>LineClosed</PrimList></BackupPath>
    <XForm>1 0 0 1 352 115</XForm></Shape>"""
doc = load(project("1 0 0 -1 50 60", TXT))
t = [x for x in doc.shapes if isinstance(x, TextShape)][0]
b = t.bounds()
check("testo con tracciato di riserva: al suo posto (centro 352, 117), non spostato due volte",
      abs(b.center().x() - 352) < 0.5 and abs(b.center().y() - 117) < 0.5, f"{b.center().x():.1f},{b.center().y():.1f}")
check("testo con tracciato di riserva: altezza come in LightBurn (4 mm)", abs(b.height() - 4) < 0.05, f"{b.height():.2f}")
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
