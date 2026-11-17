# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6: progetto per xTool Studio (`.xs`) per la xTool M2 — `core/xtool_xs.py`.

La M2 non è GRBL e lavora solo con xTool Studio: FreeLaserCut scrive un progetto con disegno e parametri, da aprire
là. Il formato è stato ricavato da due progetti salvati da xTool Studio 1.10.15 (17/11/2026).
Casi: struttura dello zip e dei JSON (gli stessi nomi di campo dei progetti veri); posizioni in mm con l'asse Y
girato (basso-sinistra del piano = basso-sinistra della M2); un collegamento per livello con il tipo giusto (linea,
taglio, riempimento, foto) e i valori nelle unità di xTool Studio (mm/s, %, passate, righe per cm, ponticelli);
buchi che restano buchi con il riempimento «nonzero»; curve conservate; foto dritta com'è e foto ruotata ridisegnata
dritta con il contenuto al posto giusto; sagoma del ritaglio; livelli spenti, strumenti e nascosti lasciati fuori;
oggetti fuori dall'area contati; laser 10/20/40 W; il file si scrive solo a contenuto pronto.
Uso: python tests/test_v206_xtool_xs.py
"""
import io
import json
import math
import os
import re
import sys
import tempfile
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtGui import QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core import photo_clip, xtool_xs as xs  # noqa: E402
from freelasercut.core.document import (  # noqa: E402
    Document, EllipseShape, GroupShape, ImageShape, PathShape, RectShape, SpecialShape,
)

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "")


def near(a, b, tol=1e-3):
    return abs(a - b) <= tol


def put(doc, s, x, y, rot=0.0):
    s.set_transform(QTransform().rotate(rot) * QTransform.fromTranslate(x, y))
    doc.add(s)
    return s


def make():
    doc = Document()
    c = doc.layer(1); c.mode = "line"; c.power_max = 30; c.speed = 1500; c.passes = 1
    rect = put(doc, RectShape(50, 30, layer=1), 20, 20)
    c = doc.layer(2); c.mode = "line"; c.power_max = 80; c.speed = 300; c.passes = 3; c.tabs = True
    c.tab_count = 3; c.tab_size = 0.6; c.kerf = 0.08
    circle = put(doc, EllipseShape(40, 40, layer=2), 100, 20)
    c = doc.layer(3); c.mode = "fill"; c.power_max = 23; c.speed = 6000; c.interval = 0.125; c.angle = 45
    c.crosshatch = True
    ring_p = QPainterPath()
    ring_p.addEllipse(QRectF(0, 0, 40, 40))
    ring_p.addEllipse(QRectF(10, 10, 20, 20))
    ring = put(doc, PathShape(ring_p, layer=3), 20, 110)
    c = doc.layer(4); c.mode = "image"; c.power_max = 40; c.speed = 4800; c.dpi = 300
    arr = np.full((300, 400), 200, np.uint8)
    arr[:60, :120] = 0  # l'angolo in alto a sinistra della foto è nero
    doc.images["g"] = Image.fromarray(arr)
    straight = put(doc, ImageShape("g", 60, 45, layer=4), 220, 110)
    turned = put(doc, ImageShape("g", 60, 45, layer=4), 320, 200, rot=30)
    return doc, rect, circle, ring, straight, turned


def load(files, suffix):
    name = next(n for n in files if n.endswith(suffix))
    v = files[name]
    return v if not isinstance(v, bytes) else json.loads(v.decode("utf-8"))


doc, rect, circle, ring, straight, turned = make()
files, rep = xs.build(doc, name="Prova", app_version="0.20.6")
disp = load(files, "displays-0.json")["displays"]
proj, prof, dev = files["project.json"], files["profiles.json"]["profiles"], load(files, "device-JS002-1.json")
canvas_id = proj["activeCanvasId"]
mode = dev["processing"][canvas_id]["modes"]["LASER_PLANE"]

print("--- struttura")
check("file del progetto: meta, project, profiles, tela, oggetti, due dispositivi, anteprima, .format = v2",
      {"meta/persistence-meta.json", "project.json", "profiles.json", f"canvases/{canvas_id}.json",
       f"canvases/{canvas_id}/displays-0.json", "devices/device-default.json", "devices/device-JS002-1.json",
       "resources/project-cover.png", "resources/project-cover.png.meta.json", ".format"} <= set(files)
      and files[".format"] == b"v2" and files["meta/persistence-meta.json"]["protocol"] == "xcs-workspace-v2")
check("macchina: JS002 «M2», laser da 10 W, modo LASER_PLANE", dev["deviceCode"] == "JS002" and dev["extName"] == "M2"
      and dev["power"] == [10] and proj["activeDeviceId"] == "JS002-1"
      and dev["processing"][canvas_id]["activeMode"] == "LASER_PLANE")
check("il progetto dice chi l'ha scritto (FreeLaserCut) e per quale versione del formato",
      proj["versionInfo"]["ua"] == "FreeLaserCut/0.20.6" and proj["versionInfo"]["appVersion"] == xs.APP_VERSION
      and proj["projectName"] == "Prova")
# gli stessi campi dei progetti veri (elenchi presi dai file di xTool Studio 1.10.15)
PATH_KEYS = {"alpha", "angle", "customData", "dPath", "effects", "enableTransform", "fill", "fillColor", "fillRule",
             "graphicX", "graphicY", "groupTag", "groupTags", "height", "id", "isClosePath", "isCompoundPath",
             "isFill", "layerColor", "layerTag", "lineColor", "localSkew", "lockRatio", "lockState",
             "minCanvasVersion", "name", "offsetX", "offsetY", "originColor", "pathCornerData", "pivot", "points",
             "resourceOrigin", "rootComponentId", "scale", "skew", "stroke", "transform", "type", "visible",
             "visibleState", "width", "x", "y", "zOrder"}
BITMAP_KEYS = {"alpha", "angle", "autoStrength", "brightness", "colorInverted", "colorInvertedFillTransparent",
               "colorInvertedTransparentColor", "contrast", "currentUrl", "customData", "dpi", "effects",
               "enableTransform", "fill", "filterAttrsMap", "filterList", "filterList_V2", "format", "grayValue",
               "groupTag", "groupTags", "height", "id", "isClosePath", "isFill", "isGray", "layerColor", "layerTag",
               "localSkew", "lockRatio", "lockState", "mask", "minCanvasVersion", "modifyData", "name", "offsetX",
               "offsetY", "opacity", "originAutoAdjust", "originColor", "originHeight", "originWidth", "pivot",
               "resourceOrigin", "resourcePath", "rootComponentId", "saturation", "scale", "sharpness", "skew",
               "stroke",
               "temperature", "tone", "transform", "type", "visible", "visibleState", "warpLocalOffset", "width",
               "x", "y", "zOrder"}
check("ogni tracciato ha esattamente i campi di un PATH di xTool Studio",
      all(set(d) == PATH_KEYS for d in disp if d["type"] == "PATH"))
check("ogni foto ha esattamente i campi di un BITMAP di xTool Studio",
      all(set(d) == BITMAP_KEYS for d in disp if d["type"] == "BITMAP"))
check("identificativi tutti diversi e conteggio degli oggetti giusto", len({d["id"] for d in disp}) == len(disp) == 5
      and files[f"canvases/{canvas_id}.json"]["chunkLayout"]["displayCount"] == 5)
check("tutto il progetto è JSON valido", all(isinstance(v, bytes) or json.loads(json.dumps(v)) == v for v in files.values()))

print("--- posizioni")
P = [d for d in disp if d["type"] == "PATH"]
B = [d for d in disp if d["type"] == "BITMAP"]
r = P[0]
check("rettangolo a 20, 20 dal basso a sinistra: sulla tela a x 20, y 320 − 20 − 30 = 270, 50 × 30 mm",
      near(r["x"], 20) and near(r["y"], 270) and near(r["width"], 50) and near(r["height"], 30)
      and r["transform"] == [1, 0, 0, 1, 0, 0], (r["x"], r["y"]))
nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", r["dPath"])]
check("il contorno è scritto in mm della tela (matrice identità)", near(min(nums[0::2]), 20) and near(max(nums[0::2]), 70)
      and near(min(nums[1::2]), 270) and near(max(nums[1::2]), 300) and r["dPath"].endswith("Z"))
c = P[1]
check("cerchio: curve conservate (C), chiuso, 40 × 40 al posto giusto", "C" in c["dPath"] and c["isClosePath"]
      and near(c["x"], 100) and near(c["y"], 260) and near(c["width"], 40, 0.01))
check("colore del livello di FreeLaserCut come livello di xTool Studio", r["layerTag"] == "#2e7cf6"
      and files[f"canvases/{canvas_id}.json"]["layerData"]["#2e7cf6"]["name"] == "#2E7CF6"
      and len(files[f"canvases/{canvas_id}.json"]["layerData"]) == 4)

print("--- riempimento con buchi")
g = P[2]
subs = [s for s in re.split(r"(?=M)", g["dPath"]) if s]


def area_of(d):
    pts = [(float(a), float(b)) for a, b in re.findall(r"(-?\d+\.?\d*) (-?\d+\.?\d*)", d)]
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))


check("anello: due sottotracciati, composto, pieno, regola nonzero", len(subs) == 2 and g["isCompoundPath"] and g["isFill"]
      and g["fill"]["visible"] and not g["stroke"]["visible"] and g["fillRule"] == "nonzero")
check("il buco gira al contrario del contorno (con nonzero resta vuoto)", area_of(subs[0]) * area_of(subs[1]) < 0)
same = QPainterPath()
same.addEllipse(QRectF(0, 0, 40, 40))
inner = QPainterPath()
inner.addEllipse(QRectF(10, 10, 20, 20))
same.addPath(inner.toReversed())
d2 = Document()
d2.layer(3).mode = "fill"
put(d2, PathShape(same, layer=3), 0, 0)
f2, _ = xs.build(d2)
s2 = [s for s in re.split(r"(?=M)", load(f2, "displays-0.json")["displays"][0]["dPath"]) if s]
d3 = Document()
d3.layer(3).mode = "fill"
both = QPainterPath()
both.addEllipse(QRectF(0, 0, 40, 40))
both.addPath(inner)
put(d3, PathShape(both, layer=3), 0, 0)
s3 = [s for s in re.split(r"(?=M)", load(xs.build(d3)[0], "displays-0.json")["displays"][0]["dPath"]) if s]
check("…qualunque verso avessero nel disegno", area_of(s2[0]) * area_of(s2[1]) < 0 and area_of(s3[0]) * area_of(s3[1]) < 0)
two = QPainterPath()
two.addRect(QRectF(0, 0, 10, 10))
two.addRect(QRectF(20, 0, 10, 10))
d4 = Document()
d4.layer(3).mode = "fill"
put(d4, PathShape(two, layer=3), 0, 0)
s4 = [s for s in re.split(r"(?=M)", load(xs.build(d4)[0], "displays-0.json")["displays"][0]["dPath"]) if s]
check("due figure affiancate: stesso verso (tutte e due piene)", area_of(s4[0]) * area_of(s4[1]) > 0)

print("--- lavorazioni")
active = [b for b in mode["bindings"] if "shadowOf" not in b]
by_kind = {prof[b["baseProfileId"]]["processingType"]: b for b in active}
val = {k: mode["patches"][b["patchIds"][0]]["overrides"] for k, b in by_kind.items()}
check("quattro profili di partenza, uno per tipo, tutti elencati nel dispositivo",
      sorted(p["processingType"] for p in prof.values()) == sorted([xs.LINE, xs.FILL, xs.CUT, xs.PHOTO])
      and sorted(mode["profileRefs"]) == sorted(prof))
check("un collegamento per livello, con il tipo giusto e i suoi oggetti", len(active) == 4
      and by_kind[xs.LINE]["displayIds"] == [P[0]["id"]] and by_kind[xs.CUT]["displayIds"] == [P[1]["id"]]
      and by_kind[xs.FILL]["displayIds"] == [P[2]["id"]] and by_kind[xs.PHOTO]["displayIds"] == [b["id"] for b in B])
check("linea: 30 %, 1500 mm/min = 25 mm/s, 1 passata", val[xs.LINE]["power"] == 30 and val[xs.LINE]["speed"] == 25
      and val[xs.LINE]["repeat"] == 1 and val[xs.LINE]["laser"] == "laser_blue_10W")
check("taglio (3 passate): 80 %, 300 mm/min = 5 mm/s, ponticelli 3 da 0,6 mm, compensazione 0,08",
      val[xs.CUT]["power"] == 80 and val[xs.CUT]["speed"] == 5 and val[xs.CUT]["repeat"] == 3
      and val[xs.CUT]["enableBreakPoint"] and val[xs.CUT]["breakPointCount"] == 3
      and val[xs.CUT]["breakPointSize"] == 0.6 and val[xs.CUT]["enableKerf"] and val[xs.CUT]["kerfDistance"] == 0.08)
check("riempimento: passo 0,125 mm = 80 righe/cm = 203,2 dpi, angolo 45, incrociato, 100 mm/s",
      val[xs.FILL]["density"] == 80 and val[xs.FILL]["dpiX"] == 203.2 and val[xs.FILL]["scanAngle"] == 45
      and val[xs.FILL]["crossAngle"] is True and val[xs.FILL]["speed"] == 100 and val[xs.FILL]["power"] == 23)
check("foto: 300 dpi = 118,11 righe/cm, 80 mm/s, 40 %", val[xs.PHOTO]["dpiX"] == 300
      and near(val[xs.PHOTO]["density"], 118.11, 0.01) and val[xs.PHOTO]["speed"] == 80 and val[xs.PHOTO]["power"] == 40)
check("ogni valore scritto è un parametro che xTool Studio ha per quel tipo (nessun nome inventato)",
      all(set(v) == set(xs._base_values(k, "laser_blue_10W")) for k, v in val.items()))
shadows = [b for b in mode["bindings"] if "shadowOf" in b]
check("per i disegni restano pronti gli altri due tipi (come fa xTool Studio), per le foto no", len(shadows) == 6
      and all(b["displayIds"] == [] and b["shadowOf"] in {a["bindingId"] for a in active} for b in shadows)
      and not any(b["shadowOf"] == by_kind[xs.PHOTO]["bindingId"] for b in shadows))
check("linea senza passate in più, ponticelli o compensazione = «Incisione Linea»; scelta esplicita rispettata",
      xs.kind_of(doc.layer(1)) == xs.LINE and xs.kind_of(doc.layer(1), cut_layers={1}) == xs.CUT
      and xs.kind_of(doc.layer(2), cut_layers=set()) == xs.LINE)
slow = Document()
slow.layer(1).speed = 12
slow.layer(1).power_max = 0
put(slow, RectShape(5, 5, layer=1), 0, 0)
sm = load(xs.build(slow)[0], "device-JS002-1.json")
sv = list(list(sm["processing"].values())[0]["modes"]["LASER_PLANE"]["patches"].values())[0]["overrides"]
check("valori sotto il minimo portati al minimo (1 mm/s, 1 %)", sv["speed"] == 1 and sv["power"] == 1)

print("--- foto")
s = B[0]
png = Image.open(io.BytesIO(files[s["resourcePath"]]))
check("foto dritta: stessi pixel, al suo posto (220, 320 − 110 − 45), 60 × 45 mm, 0,15 mm per pixel",
      png.size == (400, 300) and near(s["x"], 220) and near(s["y"], 165) and near(s["width"], 60)
      and near(s["height"], 45) and s["transform"] == [0.15, 0, 0, 0.15, 220, 165] and near(s["dpi"]["dpiX"], 169.333, 0.01))
check("…con l'alto della foto in alto (angolo nero in alto a sinistra)", png.getpixel((5, 5)) == 0
      and png.getpixel((395, 295)) == 200)
import hashlib  # noqa: E402

sha = hashlib.sha256(files[s["resourcePath"]]).hexdigest()
check("il nome del file è l'impronta sha256 del contenuto, come in xTool Studio, con la sua scheda",
      s["resourcePath"] == f"resources/{sha}.png" and files[s["resourcePath"] + ".meta.json"]["ref"] == s["resourcePath"]
      and s["customData"]["from"]["xtool_trace_id"] == "sha256:" + sha)
t = B[1]
tb = turned.bounds()
check("foto ruotata di 30°: ridisegnata dritta nel suo ingombro (stessa posizione e misura del piano)",
      near(t["x"], tb.left(), 0.2) and near(t["y"], 320 - tb.bottom(), 0.2) and near(t["width"], tb.width(), 0.3)
      and near(t["height"], tb.height(), 0.3) and t["transform"][1] == 0 and t["transform"][2] == 0, (t["x"], t["y"], tb))
tp = Image.open(io.BytesIO(files[t["resourcePath"]])).convert("RGBA")
k = t["transform"][0]


def px_at(local):  # punto della foto (mm locali) -> pixel della foto ridisegnata
    w_ = turned.tf.map(QPointF(*local))
    return tp.getpixel((int((w_.x() - t["x"]) / k), int((320 - w_.y() - t["y"]) / k)))


dark, light = px_at((5, 42)), px_at((50, 10))  # vicino all'angolo nero (in alto a sinistra) e nella parte chiara
check("…con il contenuto al posto giusto (l'angolo nero dov'è nel piano) e bianco fuori (non inciso)",
      dark[0] < 20 and light[0] > 180 and tp.getpixel((0, 0)) == (255, 255, 255, 255) and near(k, 0.15, 1e-3)
      and "A" not in Image.open(io.BytesIO(files[t["resourcePath"]])).getbands(),
      (dark, light))
clip_doc = Document()
clip_doc.layer(4).mode = "image"
clip_doc.images["g"] = doc.images["g"]
ci = put(clip_doc, ImageShape("g", 60, 45, layer=4), 0, 0)
ci.clip = [[[[10, 10], [50, 10], [50, 35], [10, 35]]]]
cf, _ = xs.build(clip_doc)
cd = load(cf, "displays-0.json")["displays"][0]
cp = Image.open(io.BytesIO(cf[cd["resourcePath"]])).convert("RGBA")
check("foto ritagliata con una forma: fuori dalla sagoma bianco (non inciso), dentro la foto",
      cp.getpixel((200, 150))[:3] == (200, 200, 200) and cp.getpixel((5, 5))[:3] == (255, 255, 255))

print("--- che cosa resta fuori")
d5 = Document()
put(d5, RectShape(10, 10, layer=1), 5, 5)
off = put(d5, RectShape(10, 10, layer=2), 30, 5)
d5.layer(2).output = False
tool = put(d5, RectShape(10, 10, layer=30), 60, 5)
hid = put(d5, RectShape(10, 10, layer=1), 90, 5)
hid.hidden = True
out_r = put(d5, RectShape(10, 10, layer=1), 500, 5)
grp = GroupShape([RectShape(4, 4, layer=1), SpecialShape("star", 6, 6, layer=1)], layer=1)
grp.set_transform(QTransform.fromTranslate(120, 50))
d5.add(grp)
f5, r5 = xs.build(d5)
n5 = load(f5, "displays-0.json")["displays"]
check("livello che non esce, livello strumenti e forme nascoste non entrano nel progetto", len(n5) == 4
      and len(r5["skipped"]) == 2 and r5["layers"] == [(1, xs.LINE, 4)])
check("oggetto fuori dall'area della M2 (426 × 320): scritto ma segnalato", r5["outside"] == 1)
check("le forme di un gruppo diventano oggetti separati, al posto giusto",
      any(near(d["x"], 120) and near(d["y"], 320 - 54) for d in n5))
for w_ in (20, 40):
    fw = xs.build(d5, laser_w=w_)[0]
    dv = load(fw, "device-JS002-1.json")
    lv = list(list(dv["processing"].values())[0]["modes"]["LASER_PLANE"]["patches"].values())[0]["overrides"]["laser"]
    check(f"modulo da {w_} W", dv["power"] == [w_] and lv == f"laser_blue_{w_}W")
try:
    xs.build(d5, laser_w=15)
    check("potenza del modulo sconosciuta rifiutata", False)
except ValueError:
    check("potenza del modulo sconosciuta rifiutata", True)
empty = xs.build(Document())[0]
check("piano vuoto: progetto valido senza oggetti", load(empty, "displays-0.json")["displays"] == [])

print("--- file")
path = os.path.join(TMP, "prova.xs")
rep2 = xs.export_xs(doc, path, name="Prova")
z = zipfile.ZipFile(path)
names = z.namelist()
check("zip integro, con project.json leggibile e .format in fondo", z.testzip() is None and names[-1] == ".format"
      and json.loads(z.read("project.json"))["projectName"] == "Prova" and rep2["layers"] == rep["layers"])
bad = os.path.join(TMP, "non-toccare.xs")
open(bad, "wb").write(b"vecchio")
try:
    xs.export_xs(doc, bad, laser_w=15)
except ValueError:
    pass
check("se la preparazione fallisce il file che c'era non viene toccato", open(bad, "rb").read() == b"vecchio")
_ = (photo_clip, math, circle, ring, straight, rect, off, tool, out_r)

print("--- comando nel programma")
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
from PySide6.QtWidgets import QMessageBox  # noqa: E402

QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui.dialogs_xtool import XToolExportDialog  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
check("comando nel menu File, accanto a Esporta SVG, con la sua scheda di aiuto",
      w.acts["export_xs"] in w.m_file.actions() and "export_xs" in help_texts.HELP
      and w.m_file.actions().index(w.acts["export_xs"]) == w.m_file.actions().index(w.acts["export"]) + 1)
w.editor.set_document(doc)
out_ui = os.path.join(TMP, "dal-programma.xs")
rep_ui = w.file_export_xs(path=out_ui)
zu = zipfile.ZipFile(out_ui)
du = json.loads(zu.read(next(n for n in zu.namelist() if n.endswith("displays-0.json"))))["displays"]
check("dal programma: tutto il piano nel progetto, con la versione di FreeLaserCut", rep_ui and len(du) == 5
      and json.loads(zu.read("project.json"))["versionInfo"]["ua"].startswith("FreeLaserCut/0."))
w.editor.select([rect])
rep_sel = w.file_export_xs(path=os.path.join(TMP, "selezione.xs"))
check("con una selezione si esporta solo quella", rep_sel["layers"] == [(1, xs.LINE, 1)])
w.editor.select([])
w.editor.set_document(Document())
check("piano vuoto: non scrive niente e lo dice", w.file_export_xs(path=os.path.join(TMP, "vuoto.xs")) is None
      and not os.path.exists(os.path.join(TMP, "vuoto.xs")))
w.editor.set_document(doc)
check("cartella che non esiste: avviso, nessun errore", w.file_export_xs(path=os.path.join(TMP, "no", "x.xs")) is None)
dlg = XToolExportDialog(doc, [doc.layer(i) for i in (1, 2, 3, 4)], 20)
check("finestra: modulo 10 / 20 / 40 W (ricordato), i soli livelli Linea da segnare come tagli, già proposti",
      [dlg.laser.itemData(i) for i in range(dlg.laser.count())] == [10, 20, 40] and dlg.laser_w() == 20
      and set(dlg.cuts) == {1, 2} and dlg.cut_layers() == {2})
dlg.cuts[1].setChecked(True)
dlg.cuts[2].setChecked(False)
rep_cut = w.file_export_xs(path=os.path.join(TMP, "tagli.xs"), laser_w=dlg.laser_w(), cut_layers=dlg.cut_layers())
check("la scelta dei tagli e del modulo arriva nel progetto", (1, xs.CUT, 1) in rep_cut["layers"]
      and (2, xs.LINE, 1) in rep_cut["layers"]
      and json.loads(zipfile.ZipFile(os.path.join(TMP, "tagli.xs")).read("devices/device-JS002-1.json"))["power"] == [20])
dlg.close()

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
