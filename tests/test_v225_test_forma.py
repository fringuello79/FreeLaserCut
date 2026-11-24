# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.5: Test materiale con la forma scelta o con un pezzo di foto (richiesta di Stefano Modena).

«Per le immagini prendo una porzione dove ci sono più scale di grigio e faccio un material test su quel punto: così
capisco quali sono i parametri ottimali.» Ora nella finestra del test, alla voce «Nei quadrati»:
- Quadrati pieni (come prima, identico);
- Forma selezionata sul piano: in ogni quadrato la forma rimpicciolita, riempita o seguita;
- Pezzo della foto selezionata: in ogni quadrato lo stesso pezzo di foto, con le impostazioni del suo livello
  (risoluzione, retino) e la potenza e la velocità del quadrato. Il pezzo si sceglie sulla miniatura; «Zona con più
  grigi» lo trova da solo.

Uso: python tests/test_v225_test_forma.py [classica|banco]
"""
import json
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
for _n in ("question", "information", "warning"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, **k: QMessageBox.Yes))

from freelasercut import gcode_preview  # noqa: E402
from freelasercut.core import geom, material_test as M  # noqa: E402
from freelasercut.core.document import CutSettings, ImageShape, RectShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402


def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.005)


prof = MachineProfile()

# ====================================================================== A. la zona con più grigi
a = np.full((300, 400), 255, np.uint8)
a[0:120, 250:400] = np.tile(np.linspace(0, 255, 150).astype(np.uint8), (120, 1))  # sfumatura in alto a destra
a[200:300, 0:150] = 0  # nero pieno in basso a sinistra
dark = 1 - a.astype(np.float32) / 255
x0, y0, x1, y1 = M.best_gray_region(dark, 0.35)
check("A trova la sfumatura (in alto a destra), non il bianco e non il nero pieno",
      x0 >= 0.55 and y1 <= 0.55, (x0, y0, x1, y1))
check("A zona quadrata, grande quanto chiesto (35 % del lato corto)",
      abs((x1 - x0) * 400 - (y1 - y0) * 300) < 6 and abs((y1 - y0) * 300 - 105) < 6, (x0, y0, x1, y1))
check("A foto tutta uguale: una zona valida, senza errori", all(0 <= v <= 1 for v in M.best_gray_region(np.zeros((50, 80)))))

# ====================================================================== B. il G-code
sq = M.build(M.TestSpec(rows=3, cols=3), prof)
sq2 = M.build(M.TestSpec(rows=3, cols=3, content=None), prof)
import hashlib  # noqa: E402


def impronta(**kw):
    return hashlib.md5("\n".join(M.build(M.TestSpec(**kw), prof).lines).encode()).hexdigest()[:12]


# impronte calcolate sulla 0.22.4, prima di questa modifica
check("B quadrati pieni: G-code identico a quello della 0.22.4 (riempimento, linea, riferimenti con titolo e cornice)",
      sq.lines == sq2.lines and impronta(rows=3, cols=3) == "286993726518"
      and impronta(rows=2, cols=4, mode="line") == "7b202c2131ce"
      and impronta(rows=3, cols=3, markers=True, title="Prova", border=True, passes=2) == "aaffc0df2903")
tri = [geom.Poly([(100, 100), (160, 100), (130, 152)], True)]  # triangolo grande, da qualche parte sul piano
spec = M.TestSpec(rows=3, cols=3, cell=10, content=M.CellContent(kind="shape", polys=tri))
js = M.build(spec, prof)
pv = gcode_preview.parse(js.lines, profile=prof)
check("B forma: nessun avviso, il lavoro si fa", not js.warnings and len(js.lines) > 100, js.warnings)
bb = js.bounds
check("B forma: rimpicciolita nei quadrati, il test resta grande come con i quadrati",
      abs(bb.width() - sq.bounds.width()) < 1.5 and abs(bb.height() - sq.bounds.height()) < 1.5,
      (bb.width(), sq.bounds.width()))
check("B forma: incide meno dei quadrati pieni (un triangolo è metà quadrato)", 0.3 < js.layers[0].cut_mm / sq.layers[0].cut_mm < 0.7,
      js.layers[0].cut_mm / sq.layers[0].cut_mm)
lin = M.build(M.TestSpec(rows=2, cols=2, mode="line", content=M.CellContent(kind="shape", polys=tri)), prof)
check("B forma in modalità Linea: segue il contorno", not lin.warnings and lin.layers[0].cut_mm > 0)
open_only = [geom.Poly([(0, 0), (10, 5)], False)]
jo = M.build(M.TestSpec(rows=2, cols=2, content=M.CellContent(kind="shape", polys=open_only)), prof)
check("B solo una linea aperta in Riempimento: niente da riempire, nessun errore", jo.layers[0].cut_mm == 0 or not jo.warnings)
img = Image.fromarray(a, "L")
cs = CutSettings(mode="image", dpi=254, dither="grayscale", power_min=0, power_max=80)
c = M.CellContent(kind="image", image=img.crop((250, 0, 400, 120)), w=37.5, h=30, cs=cs)
ji = M.build(M.TestSpec(rows=3, cols=3, cell=10, content=c), prof)
check("B foto: incisa in ogni quadrato, come immagine", not ji.warnings and ji.layers[0].mode == "image"
      and ji.layers[0].cut_mm > 0, ji.warnings)
import re  # noqa: E402

pw = [float(m.group(1)) for l in ji.lines if "X" in l and not l.startswith(";")
      for m in [re.search(r"S([\d.]+)", l)] if m]
check("B foto: potenze diverse (i grigi), mai sopra la potenza più alta del test", pw and max(pw) <= prof.s_max * 1.0
      and len({round(v) for v in pw}) > 10, (len(pw), max(pw) if pw else None))
c_neg = M.CellContent(kind="image", image=img.crop((250, 0, 400, 120)), w=37.5, h=30,
                      cs=CutSettings(mode="image", dpi=254, dither="floyd", power_max=80))
jn = M.build(M.TestSpec(rows=2, cols=2, cell=10, content=c_neg), prof)
check("B foto con il retino del livello (Floyd): punti accesi/spenti", not jn.warnings and jn.layers[0].cut_mm > 0)
jb = M.build(M.TestSpec(rows=2, cols=2, content=M.CellContent(kind="image", image=None)), prof)
check("B foto mancante: avviso chiaro e quadrati pieni al suo posto", jb.warnings and "Foto" in jb.warnings[0], jb.warnings)
check("B riferimenti per la foto del test: solo con i quadrati pieni",
      M.layout(M.TestSpec(markers=True, content=c)).marks == [] and M.layout(M.TestSpec(markers=True)).marks)

# ====================================================================== C. la finestra
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.show()
spin(0.2)
ed = w.editor
p = os.path.join(TMP, "foto.png")
Image.fromarray(a, "L").save(p)
w.import_files([p])
spin(0.3)
foto = [s for s in ed.doc.shapes if isinstance(s, ImageShape)][0]
r = RectShape(30, 20)
ed.add([r])
spin(0.05)
dlg = w.material_test()
spin(0.1)
check("C nella finestra la voce «Nei quadrati», di partenza «Quadrati pieni»", dlg.content.currentData() == "square"
      and not dlg.zone_box.isVisible() and dlg.spec().content is None)
ed.select([])
dlg.content.setCurrentIndex(dlg.content.findData("shape"))
spin(0.05)
check("C niente selezionato: torna a «Quadrati pieni» e lo dice", dlg.content.currentData() == "square"
      and "Seleziona prima" in dlg.info.text(), dlg.info.text())
ed.select([r])
dlg.content.setCurrentIndex(dlg.content.findData("shape"))
spin(0.05)
s = dlg.spec()
check("C forma selezionata: presa dal piano (il rettangolo, 4 lati)", dlg.content.currentData() == "shape"
      and s.content is not None and s.content.kind == "shape" and len(s.content.polys[0].pts) >= 4)
check("C anteprima dello schema: la forma disegnata nei quadrati", dlg.grid.outline is not None and dlg.grid.thumb is None)
j = dlg.build()
check("C il lavoro si costruisce", not j.warnings and len(j.lines) > 50, j.warnings)
ed.select([foto])
dlg.content.setCurrentIndex(dlg.content.findData("image"))
spin(0.05)
check("C foto selezionata: «Pezzo della foto», la miniatura e la zona si vedono", dlg.content.currentData() == "image"
      and dlg.zone_box.isVisible() and dlg.zone.thumb is not None)
zx0, zy0, zx1, zy1 = dlg.zone.zone
check("C zona scelta da sola dove ci sono più grigi (in alto a destra)", zx0 > 0.5 and zy1 < 0.6, dlg.zone.zone)
check("C con la foto il tipo è deciso dal livello della foto (Tipo e interlinea spenti)",
      not dlg.mode.isEnabled() and not dlg.interval.isEnabled() and not dlg.markers.isEnabled())
s = dlg.spec()
check("C il pezzo ha le misure giuste in mm (35 % del lato corto della foto)",
      s.content.kind == "image" and abs(s.content.h - foto.h * 0.35) < foto.h * 0.03, (s.content.w, s.content.h, foto.h))
dlg.zone.zone_at(0.2, 0.8)
s2 = dlg.spec()
check("C clic sulla miniatura: la zona si sposta lì", dlg.zone.zone[0] < 0.4 and dlg.zone.zone[3] > 0.6, dlg.zone.zone)
dlg.zone_size.setValue(60)
check("C «Grandezza»: zona più grande", abs((dlg.zone.zone[3] - dlg.zone.zone[1]) - 0.6) < 0.02, dlg.zone.zone)
dlg.auto_zone()
check("C «Zona con più grigi»: torna sulla sfumatura", dlg.zone.zone[0] > 0.3, dlg.zone.zone)
j = dlg.build()
check("C il lavoro con la foto si costruisce e incide", not j.warnings and j.layers[0].mode == "image", j.warnings)
dlg.remember_spec()
saved = json.loads(str(w.qs.value("material_test_last")))
check("C l'ultimo test si ricorda senza la foto dentro (solo la griglia)", "content" not in saved or saved["content"] is None)
check("C la foto per leggere il test si legge come prima", dlg.photo_spec() is not None)
dlg.content.setCurrentIndex(dlg.content.findData("square"))
spin(0.05)
check("C di nuovo «Quadrati pieni»: come prima", dlg.spec().content is None and dlg.mode.isEnabled()
      and dlg.grid.thumb is None and dlg.grid.outline is None)

# ====================================================================== D. testi tradotti
import ast  # noqa: E402

testi = set()
for f in ("freelasercut/ui/dialogs_materials.py", "freelasercut/core/material_test.py"):
    for node in ast.walk(ast.parse(open(os.path.join(ROOT, f), encoding="utf-8").read())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr" and node.args \
                and isinstance(node.args[0], ast.Constant):
            testi.add(node.args[0].value)
mancano = {}
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    m = [t for t in testi if not cat.get(t)]
    if m:
        mancano[lang] = m
check("D testi del test materiale tradotti in inglese, spagnolo, francese e portoghese", not mancano, mancano)

# ====================================================================== E. difetti rimessi apposta
caught = []
orig = M._fit
ok_w = M.build(M.TestSpec(rows=3, cols=3, labels=False, content=M.CellContent(kind="shape", polys=tri)), prof)
M._fit = lambda rect, cx, cy, size: orig(rect, 20, 20, size)  # 1. tutte le forme nello stesso posto
jf = M.build(M.TestSpec(rows=3, cols=3, labels=False, content=M.CellContent(kind="shape", polys=tri)), prof)
caught.append(jf.bounds.width() < ok_w.bounds.width() - 5)
M._fit = orig
orig_b = M.best_gray_region
M.best_gray_region = lambda d, frac=0.35, n=12: (0.0, 0.0, frac, frac)  # 2. zona sempre in alto a sinistra
dlg.auto_zone()
caught.append(dlg.zone.zone[0] < 0.3)
M.best_gray_region = orig_b
orig_ok = M.content_ok
M.content_ok = lambda c: ""  # 3. foto mancante non controllata
try:
    jx = M.build(M.TestSpec(rows=2, cols=2, content=M.CellContent(kind="image", image=None)), prof)
    caught.append(not jx.warnings)  # senza il controllo l'avviso sparisce: la prova B lo vede
except Exception:  # noqa: BLE001
    caught.append(True)
M.content_ok = orig_ok
check("E tre difetti rimessi apposta (forme sovrapposte, zona sbagliata, foto mancante): tutti visti", all(caught), caught)

w.close()
print(f"\n{sum(results)}/{len(results)} prove superate")
os._exit(0 if all(results) else 1)
