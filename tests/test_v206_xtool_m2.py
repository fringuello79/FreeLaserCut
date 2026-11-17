# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6, sperimentale: il lavoro scritto direttamente per la xTool M2 — `core/xtool_m2.py`.

Il linguaggio (G-code in chiaro con comandi suoi) è stato ricavato dai file che xTool Studio 1.10.15 scrive sul
computer per un nostro disegno di prova (17/11/2026). Le righe «di xTool Studio» citate qui sono prese da quei file.
Casi: intestazione, «WorkingInfo», aspiratore e coda; blocchi di linea e di taglio (M1001/M1002/M32, primo tratto con
S e F, numeri senza zeri in coda), passate, ponticelli fra «breakPointStart» e «breakPointEnd»; messa a fuoco in Z
dallo spessore; scostamento della testa per modulo e costruttore; riempimento a righe avanti e indietro con il gioco
che dipende dalla velocità, la corsa a laser spento ai lati (ridotta vicino ai bordi) e la Y che cammina; foto in
toni di grigio e a punti; le prime righe di una foto e due righe di un riempimento uguali a quelle di xTool Studio;
la cornice uguale alla sua; che cosa resta fuori; un lavoro che esce dall'area non si scrive; comando e finestra.
Uso: python tests/test_v206_xtool_m2.py
"""
import json
import math
import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core import xtool_m2 as m2  # noqa: E402
from freelasercut.core.document import (  # noqa: E402
    Document, EllipseShape, ImageShape, PathShape, RectShape,
)

results = []
RX = re.compile(r"G([01])(?:X(-?[\d.]+))?(?:Y(-?[\d.]+))?(?:Z(-?[\d.]+))?(?:S(\d+))?(?:F(\d+))?$")


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "")


def near(a, b, tol=1e-3):
    return abs(a - b) <= tol


def put(doc, s, x, y, rot=0.0):
    s.set_transform(QTransform().rotate(rot) * QTransform.fromTranslate(x, y))
    doc.add(s)
    return s


def blocks(lines):
    """[(testa del blocco, corpo)] dal testo del lavoro."""
    out, cur = [], None
    for l in lines:
        if l in ("# JS002 BITMAP HEAD", "# JS002 VECTOR HEAD"):
            cur = ([l], [])
            out.append(cur)
        elif l == "# JS002 END":
            cur = None
        elif cur is not None and l:
            (cur[0] if l[0] == "M" or l.startswith("# motion") or l.startswith("# blockConfig") else cur[1]).append(l)
    return out


def burnt(body):
    """Tratti incisi [(x0, y0, x1, y1, S)] di un corpo di blocco."""
    x = y = 0.0
    s = 0
    out = []
    for l in body:
        m = RX.match(l)
        if not m:
            continue
        g, gx, gy, _gz, gs, _gf = m.groups()
        if gs is not None:
            s = int(gs)
        nx = float(gx) if gx is not None else x
        ny = float(gy) if gy is not None else y
        if g == "1" and s > 0 and (nx, ny) != (x, y):
            out.append((x, y, nx, ny, s))
        x, y = nx, ny
    return out


def scanlines(body):
    """Corpo di un blocco a righe -> [{pre: [Y, Y], lines: [...]}] (una voce per riga di scansione)."""
    out = []
    for l in body:
        if re.fullmatch(r"G1Y-?[\d.]+(S0)?", l):
            if not out or out[-1]["lines"]:
                out.append({"pre": [], "lines": []})
            out[-1]["pre"].append(float(l[3:].replace("S0", "")))
        elif out and l.startswith("G1X"):
            out[-1]["lines"].append(l)
    return out


def nums(line):
    return [float(v) for v in re.findall(r"-?\d+\.?\d*", line)]


def make():
    doc = Document()
    c = doc.layer(1)
    c.mode, c.power_max, c.speed, c.passes = "line", 30, 1500, 1
    c = doc.layer(2)
    c.mode, c.power_max, c.speed, c.passes = "line", 80, 300, 3
    c.tabs, c.tab_count, c.tab_size = True, 3, 0.6
    c = doc.layer(3)
    c.mode, c.power_max, c.speed, c.interval = "fill", 23, 6000, 0.1
    c = doc.layer(4)
    c.mode, c.power_max, c.speed, c.dpi, c.dither = "image", 40, 4800, 254, "grayscale"
    rect = put(doc, RectShape(50, 30, layer=1), 20, 20)
    circle = put(doc, EllipseShape(40, 40, layer=2), 100, 20)
    ring = QPainterPath()
    ring.addEllipse(QRectF(0, 0, 40, 40))
    ring.addEllipse(QRectF(10, 10, 20, 20))
    ringshape = put(doc, PathShape(ring, layer=3), 20, 110)
    yy, xx = np.mgrid[0:150, 0:200]
    arr = (xx / 200 * 255).astype(np.uint8)  # da nero a sinistra a bianco a destra
    arr[:, 150:] = 255  # l'ultimo quarto bianco: niente da incidere
    doc.images["g"] = Image.fromarray(arr)
    photo = put(doc, ImageShape("g", 60, 45, layer=4), 220, 110)
    return doc, rect, circle, ringshape, photo


doc, rect, circle, ringshape, photo = make()
WHEN = 1794951646.0
lines, rep = m2.build(doc, laser_w=10, thickness=3.0, when=WHEN, app_version="0.20.6")
text = "\n".join(lines)
bl = blocks(lines)

print("--- intestazione e coda")
check("data, programma che l'ha scritto, area della M2, coordinate assolute",
      re.fullmatch(r"# date=\d{4}(_\d\d){5}", lines[0]) and lines[1] == "# version=FreeLaserCut 0.20.6"
      and lines[3] == '# gc={"size":{"w":426,"h":320}}' and lines[8:11] == ["G90", "G0 F3000", ""], lines[:11])
i = lines.index("# JS002 HEAD")
check("dopo «JS002 HEAD»: ritorno all'origine e i sei «WorkingInfo» (testa 10 W = 3, tipi, spessore, ingombro, "
      "potenza massima in %, velocità minima in mm/s)",
      lines[i + 1:i + 8] == ["G0 X0 Y0 U0 F7200", '# WorkingInfo={"head":3}', '# WorkingInfo={"proc_mode":[0,1,2,3]}',
                             '# WorkingInfo={"thickness":3.0}', '# WorkingInfo={"process_bbox":[20,165,280,300]}',
                             '# WorkingInfo={"max_power":80}', '# WorkingInfo={"min_speed":5}'], lines[i + 1:i + 8])
check("aspiratore e depuratori come li scrive xTool Studio, senza la riga del consumo dei filtri",
      lines[i + 8:i + 15] == list(m2.ACCESSORIES) and "M9043" not in text and 'G198 P70 "M9064 B3"' in text)
check("coda: fine del lavoro, testa su, ritorno all'origine",
      lines[-3:] == ["# JS002 END", "G1 Z0 F1200 S0", "G1 X0 Y0 U0 F18000"])
no_acc, _r = m2.build(doc, laser_w=10, accessories=False, when=WHEN)
check("senza accessori: nessun comando per aspiratore e depuratori", not any("M90" in l or "G198" in l for l in no_acc))
check("nessun comando GRBL per accendere o spegnere il laser", not re.search(r"^(M3|M4|M5)\b", text, re.M))

print("--- linee")
check("un blocco per livello, nell'ordine dei livelli: linea, taglio, riempimento, foto",
      [b[0][0].split()[2] for b in bl] == ["VECTOR", "VECTOR", "BITMAP", "BITMAP"]
      and [b[0][3] for b in bl] == ["M1002 S0P0", "M1002 S0P1", "M1002 S0P2", "M1002 S0P3"]
      and rep["layers"] == [(1, m2.LINE, 1), (2, m2.CUT, 1), (3, m2.FILL, 1), (4, m2.PHOTO, 1)])
k = lines.index("# JS002 VECTOR HEAD")
check("testa del blocco di linea come quella di xTool Studio (riga vuota prima, spazio in coda al commento)",
      lines[k - 1:k + 7] == ["", "# JS002 VECTOR HEAD", "# motion_start", "M1001 S1P0B30", "M1002 S0P0",
                             "M32 X1000Y1000", "", '# blockConfig={"powerFactor": 0.3, "isVector": true} '],
      lines[k - 1:k + 7])
body = bl[0][1]
corners = {(20.0, 260.2), (70.0, 260.2), (70.0, 290.2), (20.0, 290.2)}
pts = {(float(m.group(2)), float(m.group(3))) for m in map(RX.match, body) if m and m.group(2) and m.group(3)}
check("rettangolo 50 × 30 a 20,20 dal basso: Y girata sull'altezza della M2 e tolti i 9,8 mm della testa", pts == corners,
      pts)
check("si va all'inizio, si mette a fuoco (Z = 31,5 − 5,7 − 3), si riparte dall'inizio; S e F solo sul primo tratto",
      body[0] == body[2] and body[0].startswith("G0X") and body[1] == "G0Z22.800" and body[3].endswith("S300F1500")
      and all(re.fullmatch(r"G1X[\d.]+Y[\d.]+", l) for l in body[4:]) and len(body) == 7, body)
check("numeri senza zeri in coda (20, 260.2), come nei blocchi di linea di xTool Studio",
      {"G0X20Y260.2", "G1X70Y290.2", "G1X70Y260.2", "G1X20Y260.2"} <= set(body)
      and not re.search(r"\.\d*0(?=[XYSF]|$)", "".join(l for l in body if "Z" not in l)), body)
studio = ["G0X20Y260.2", "G1X70Y260.2S300F1500", "G1X70Y290.2", "G1X20Y290.2", "G1X20Y260.2"]
same = m2._vector_body([[([(20, 260.2), (70, 260.2), (70, 290.2), (20, 290.2), (20, 260.2)], True)]], 300, 1500, 1, 22.8)
check("lo stesso rettangolo percorso nello stesso verso: le righe di xTool Studio", same[2:] == studio
      and same[:2] == ["G0X20Y260.2", "G0Z22.800"], same)

print("--- tagli, passate, ponticelli")
head, body = bl[1]
check("taglio: M1001 con la lettera A e la potenza minima dei tagli (15 % → A150), M1002 P1",
      head[2:5] == ["M1001 S1P0A150", "M1002 S0P1", "M32 X1000Y1000"]
      and head[5] == '# blockConfig={"powerFactor": 0.8, "isVector": true} ', head)
g0_start = [l for l in body if l == body[0]]
check("3 passate: il tracciato riparte 3 volte dallo stesso punto", len(g0_start) == 4, len(g0_start))
n_start, n_end = body.count("# breakPointStart"), body.count("# breakPointEnd")
check("3 ponticelli per passata, ognuno fra «breakPointStart» e «breakPointEnd»", n_start == n_end == 9, (n_start, n_end))
ok_tab = True
gaps = []
for j, l in enumerate(body):
    if l == "# breakPointStart":
        e = body.index("# breakPointEnd", j)
        inner = body[j + 1:e]
        ok_tab &= inner[0].startswith("G0X") and inner[1].endswith("S0F300") and body[e + 1].startswith("G0X") \
            and body[e + 2].endswith("S800F300")
        p = [nums(q)[1:3] for q in inner]
        gaps.append(sum(math.dist(p[a], p[a + 1]) for a in range(len(p) - 1)))
check("nel ponticello il laser è spento (S0) e si va alla stessa velocità; dopo riparte a S800",
      ok_tab and all(near(g, 0.6, 0.02) for g in gaps), gaps[:3])
cut_len = sum(math.hypot(x1 - x0, y1 - y0) for x0, y0, x1, y1, _s in burnt(body))
check("lunghezza tagliata = 3 passate × (circonferenza − 3 ponticelli da 0,6 mm)",
      near(cut_len, 3 * (math.pi * 40 - 1.8), 0.6), cut_len)
parts = m2.split_tabs([(0, 0), (10, 0), (10, 10), (0, 10)], 1.0, 2)
check("ponticelli: pezzi accesi e spenti alternati, alle stesse distanze di FreeLaserCut per le macchine GRBL",
      [on for _p, on in parts] == [True, False, True, False, True] and parts[1][0] == [(9.5, 0.0), (10, 0), (10.0, 0.5)]
      and near(sum(math.dist(p[a], p[a + 1]) for p, on in parts if not on for a in range(len(p) - 1)), 2.0), parts)
check("contorno troppo corto per i ponticelli: resta intero",
      m2.split_tabs([(0, 0), (1, 0), (1, 1), (0, 1)], 1.0, 4) == [([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], True)])
as_line, r_line = m2.build(doc, laser_w=10, cut_layers={1}, when=WHEN)
bq = blocks(as_line)
check("quali livelli Linea sono tagli lo si può scegliere (come nel progetto per xTool Studio)",
      bq[0][0][2:4] == ["M1001 S1P0A150", "M1002 S0P1"] and bq[1][0][2:4] == ["M1001 S1P0B30", "M1002 S0P0"]
      and r_line["layers"][:2] == [(1, m2.CUT, 1), (2, m2.LINE, 1)])

print("--- messa a fuoco, moduli, scostamento della testa")
check("Z di lavoro = corsa (31,5) − 5,7 − spessore; mai sotto zero; corsa diversa se la macchina ne dichiara una",
      near(m2.focus_z(0), 25.8) and near(m2.focus_z(3), 22.8) and m2.focus_z(40) == 0.0
      and near(m2.focus_z(3, 30.0), 21.3) and "G0Z25.800" in "\n".join(m2.build(doc, when=WHEN)[0]))
l20, _r = m2.build(doc, laser_w=20, when=WHEN)
l40, r40 = m2.build(doc, laser_w=40, when=WHEN)
check("20 W: testa 2 nei blocchi e 4 nelle informazioni; 40 W: testa 3 e 5, potenza minima 2,5 % (B25)",
      "M1001 S2P0B30" in l20 and '# WorkingInfo={"head":4}' in l20 and "M1001 S3P0B25" in l40
      and "M1001 S3P0A150" in l40 and '# WorkingInfo={"head":5}' in l40)
p40 = {(float(m.group(2)), float(m.group(3))) for m in map(RX.match, blocks(l40)[0][1]) if m and m.group(2) and m.group(3)}
check("40 W: area 426 × 308 e scostamento 0,5 / 22,3 mm (rettangolo a 19,5 … 69,5 e 235,7 … 265,7)",
      r40["bed"] == (426.0, 308.0) and p40 == {(19.5, 235.7), (69.5, 235.7), (69.5, 265.7), (19.5, 265.7)}, p40)
lcos, _r = m2.build(doc, laser_w=10, maker="COS", when=WHEN)
pcos = {(float(m.group(2)), float(m.group(3))) for m in map(RX.match, blocks(lcos)[0][1]) if m and m.group(2) and m.group(3)}
check("modulo dell'altro costruttore («COS»): scostamento 0,5 / 3,3 mm",
      pcos == {(19.5, 266.7), (69.5, 266.7), (69.5, 296.7), (19.5, 296.7)}, pcos)
try:
    m2.build(doc, laser_w=15)
    bad = False
except ValueError:
    bad = True
check("modulo che non esiste: errore", bad)

print("--- gioco e corsa a laser spento")
check("gioco per velocità (10 W): 25 mm/s 0,025775, 80 mm/s 0,05932, 100 mm/s 0,0645; oltre 600 mm/s l'ultimo valore",
      near(m2.backlash(10, 25), 0.025775, 1e-6) and near(m2.backlash(10, 80), 0.05932, 1e-6)
      and near(m2.backlash(10, 100), 0.0645, 1e-6) and near(m2.backlash(10, 900), 0.1667, 1e-6)
      and m2.backlash(10, 0) == 0.0 and near(m2.backlash(40, 300), 0.08525, 1e-6) and near(m2.backlash(20, 75), 0.0463, 1e-6))
check("corsa a laser spento: 20 mm, meno se l'oggetto è più vicino di così a un lato dell'area",
      m2._overscan(100, 200, 426) == 20.0 and m2._overscan(5, 200, 426) == 5.0 and m2._overscan(100, 420, 426) == 6.0
      and m2._overscan(-1, 200, 426) == 0.0)
check("la Y cammina di 0,0001 mm per mm, vale 0 a X = 200, cambia verso al ritorno e non supera 0,02 mm",
      near(m2.y_walk(300, True), 0.01, 1e-9) and near(m2.y_walk(300, False), -0.01, 1e-9) and m2.y_walk(200, True) == 0.0
      and m2.y_walk(-50, True) == -0.02 and m2.y_walk(600, False) == -0.02)

print("--- riempimento")
head, body = bl[2]
check("testa del blocco a righe come quella di xTool Studio (M32 più alto, righe per mm, potenze da 0 a 230)",
      head == ["# JS002 BITMAP HEAD", "# motion_start", "M1001 S1P0B30", "M1002 S0P2", "M32 X2300Y2300",
               '# blockConfig={"powerFactor":0.23,"density":"10.00","power":[0,230],"bitmapMode":"grayscale"}'], head)
kb = lines.index("# JS002 BITMAP HEAD")
check("prima della testa una riga vuota, dopo due; poi velocità a laser spento, inizio, messa a fuoco",
      lines[kb - 1] == "" and lines[kb + 6:kb + 8] == ["", ""] and lines[kb + 8] == "G1F6000S0"
      and re.fullmatch(r"G0X-?\d+\.\d{3}Y\d+\.\d{3}", lines[kb + 9]) and lines[kb + 10] == "G0Z22.800", lines[kb + 6:kb + 11])
sc = scanlines(body)
check("anello alto 40 mm a passo 0,1: 400 righe, una avanti e una indietro", len(sc) == 400
      and all((nums(s["lines"][-1])[1] > nums(s["lines"][0])[1]) == (n % 2 == 0) for n, s in enumerate(sc)), len(sc))
check("a ogni riga la Y va 0,02 mm oltre e torna; solo sulla prima riga si ripete S0",
      all(near(s["pre"][0] - s["pre"][1], 0.02, 1e-6) for s in sc) and "G1Y" in body[3] and body[3].endswith("S0")
      and sum(1 for l in body if re.fullmatch(r"G1Y[\d.]+S0", l)) == 1)
check("numeri sempre con 3 decimali nei blocchi a righe", all(re.fullmatch(
    r"G1(X-?\d+\.\d{3})?(Y\d+\.\d{3})?(S\d+)?", l) for l in body[4:]))
b100 = m2.backlash(10, 100)
mid = sc[200]  # riga a metà: l'anello ha il buco, due tratti accesi
fwd = [nums(l) for l in mid["lines"]]
seg = sorted((min(x0, x1), max(x0, x1)) for x0, _y0, x1, _y1, _s in burnt(
    [f"G0X{fwd[0][1]:.3f}Y{mid['pre'][1]:.3f}"] + mid["lines"]))
check("a metà anello due tratti accesi (il buco resta buco), spostati del gioco nel verso della riga",
      len(seg) == 2 and near(seg[0][0], 20 + b100, 0.02) and near(seg[0][1], 30 + b100, 0.02)
      and near(seg[1][0], 50 + b100, 0.02) and near(seg[1][1], 60 + b100, 0.02), seg)
back = sc[201]
segb = sorted((min(x0, x1), max(x0, x1)) for x0, _y0, x1, _y1, _s in burnt(
    [f"G0X{nums(back['lines'][0])[1]:.3f}Y{back['pre'][1]:.3f}"] + back["lines"]))
check("la riga di ritorno è spostata dello stesso gioco dall'altra parte",
      near(segb[0][0], 20 - b100, 0.02) and near(segb[1][1], 60 - b100, 0.02), segb)
check("20 mm di corsa a laser spento prima e dopo (l'anello è a 20 mm dal bordo: tutti e 20)",
      near(fwd[0][1], 20 + b100 - 20, 0.002) and near(fwd[1][1], 20 + b100, 0.02) and near(fwd[-1][1], 60 + b100 + 20, 0.02)
      and mid["lines"][-1].endswith("S0"), (fwd[0], fwd[-1]))
check("righe dall'alto in basso, a 0,1 mm, dentro l'anello (Y macchina da 160,2 a 200,2)",
      all(sc[n + 2]["pre"][1] > sc[n]["pre"][1] for n in range(0, 396)) and 160.1 < sc[0]["pre"][1] < 160.4
      and 200.0 < sc[-1]["pre"][1] < 200.3 and near(sc[2]["pre"][1] - sc[0]["pre"][1], 0.2, 1e-6))
area = sum(abs(x1 - x0) for x0, _y0, x1, _y1, _s in burnt(body)) * 0.1
check("area incisa = area dell'anello (π·20² − π·10²)", near(area, math.pi * 300, 3.0), area)
doc_e = Document()
doc_e.layer(3).mode = "fill"
put(doc_e, RectShape(20, 10, layer=3), 5, 50)
le, _r = m2.build(doc_e, when=WHEN)
se = scanlines(blocks(le)[0][1])
check("oggetto a 5 mm dal bordo: la corsa a laser spento si accorcia a 5 mm",
      near(nums(se[2]["lines"][1])[1] - nums(se[2]["lines"][0])[1], 5.0, 0.002), se[2]["lines"][:3])
doc_a = Document()
ca = doc_a.layer(3)
ca.mode, ca.angle, ca.crosshatch = "offset_fill", 45.0, True
put(doc_a, RectShape(20, 10, layer=3), 50, 50)
_la, ra = m2.build(doc_a, when=WHEN)
check("riempimento a contorni, inclinato o incrociato: per ora righe orizzontali, e lo dice",
      set(ra["notes"]) == {"offset_fill", "fill_angle"} and blocks(_la)[0][0][3] == "M1002 S0P2", ra["notes"])

print("--- le stesse righe di xTool Studio")
# riga 250 e 251 del riempimento del disegno di prova (anello e ingranaggio), come le ha scritte xTool Studio
st_a = ["G1X0.064", "G1X20.065Y180.182", "G1X30.098Y180.183S230", "G1X50.031Y180.185S0", "G1X60.065Y180.186S230",
        "G1X80.064Y180.188S0", "G1X99.531Y180.190S230", "G1X110.598Y180.191S0", "G1X130.064Y180.193S230",
        "G1X150.064Y180.195S0"]
st_b = ["G1X149.936", "G1X129.936Y180.307", "G1X110.469Y180.309S230", "G1X99.402Y180.310S0", "G1X79.936Y180.312S230",
        "G1X59.936Y180.314S0", "G1X49.902Y180.315S230", "G1X29.969Y180.317S0", "G1X19.935Y180.318S230",
        "G1X-0.064Y180.320S0"]
seg_a = [(20.0, 30.0335, 230), (49.9665, 60.0005, 230), (79.9995, 99.4665, 230), (110.5335, 129.9995, 230)]
seg_b = [(19.9995, 30.0335, 230), (49.9665, 60.0005, 230), (80.0005, 99.4665, 230), (110.5335, 130.0005, 230)]
rows = [(180.0, [(100.0, 101.0, 230)]), (180.3, seg_b)]  # la seconda riga di un blocco è di ritorno
mine = scanlines(m2._raster_body(rows, 6000, 22.8, m2.backlash(10, 100), 20.0))


def same_lines(a, b, tol=0.0015):
    return len(a) == len(b) and all(re.sub(r"-?\d+\.\d+", "#", p) == re.sub(r"-?\d+\.\d+", "#", q)
                                    and all(near(u, v, tol) for u, v in zip(nums(p), nums(q))) for p, q in zip(a, b))


check("riempimento, riga di ritorno: le righe di xTool Studio (entro 1,5 millesimi)",
      near(mine[1]["pre"][0], 180.325, 0.0015) and near(mine[1]["pre"][1], 180.305, 0.0015)
      and same_lines(mine[1]["lines"], st_b), mine[1])
rows2 = [(170.0, [(100.0, 101.0, 230)]), (170.1, [(100.0, 101.0, 230)]), (180.2, seg_a)]  # la terza è di andata
mine2 = scanlines(m2._raster_body(rows2, 6000, 22.8, m2.backlash(10, 100), 20.0))
check("riempimento, riga di andata: le righe di xTool Studio (entro 1,5 millesimi)",
      near(mine2[2]["pre"][0], 180.2, 0.0015) and near(mine2[2]["pre"][1], 180.18, 0.0015)
      and same_lines(mine2[2]["lines"], st_a), mine2[2])
st_photo = ["G1F4800S0", "G0X200.059Y155.200", "G0Z22.800", "G1Y155.220S0", "G1Y155.200", "G1X220.059Y155.202",
            "G1X237.959Y155.204S400", "G1X238.059S379", "G1X238.159S301", "G1X238.259S280", "G1X238.559S279"]
row = [(155.2, [(220.0, 237.9, 400), (237.9, 238.0, 379), (238.0, 238.1, 301), (238.1, 238.2, 280),
                (238.2, 238.5, 279)])]
mine3 = m2._raster_body(row, 4800, 22.8, m2.backlash(10, 80), 20.0)
check("foto: le prime undici righe sono identiche a quelle di xTool Studio", mine3[:11] == st_photo, mine3[:12])
check("e la riga finisce con 20 mm a laser spento e la Y arrivata", mine3[11] == "G1X258.559Y155.206S0"
      and mine3[12] == "", mine3[11:])

print("--- foto")
head, body = bl[3]
check("foto in toni di grigio: blocco P3 con le potenze da 0 a 400 e il modo «grayscale»",
      head[3] == "M1002 S0P3" and head[5] ==
      '# blockConfig={"powerFactor":0.4,"density":"10.00","power":[0,400],"bitmapMode":"grayscale"}', head)
sp = scanlines(body)
check("foto alta 45 mm a 254 punti per pollice: 450 righe", len(sp) == 450, len(sp))
row0 = burnt([f"G0X{nums(sp[100]['lines'][0])[1]:.3f}Y{sp[100]['pre'][1]:.3f}"] + sp[100]["lines"])
levels = [s for *_xy, s in row0]
check("da nero a sinistra a chiaro a destra: potenze che calano da 400, mai oltre",
      levels[1] == 400 and max(levels) == 400 and all(a >= b for a, b in zip(levels[1:], levels[2:])) and levels[-1] < 140,
      (levels[:5], levels[-3:]))
right = max(max(x0, x1) for x0, _y0, x1, _y1, _s in row0)
check("il quarto bianco a destra non si percorre: la riga finisce dove finisce lo scuro (265 mm) più la corsa spenta",
      near(right, 265.0 + m2.backlash(10, 80), 0.25) and near(nums(sp[100]["lines"][-1])[1], right + 20.0, 0.002), right)
check("la foto parte dal suo bordo in alto (Y macchina 155,2) e arriva in fondo (200,2)",
      155.2 < sp[0]["pre"][1] < 155.3 and 200.1 < sp[-1]["pre"][1] < 200.25, (sp[0]["pre"], sp[-1]["pre"]))
doc.layer(4).power_min = 5
lmin, _r = m2.build(doc, when=WHEN)
check("potenza minima del livello: scritta nel commento del blocco e usata per i toni chiari",
      '"power":[50,400]' in "\n".join(lmin) and min(s for *_xy, s in burnt(blocks(lmin)[3][1])) >= 50)
doc.layer(4).power_min = 0
doc.layer(4).dither = "threshold"
lth, _r = m2.build(doc, when=WHEN)
check("soglia (preparata da FreeLaserCut): solo spento o piena potenza, modo «passthrough»",
      {s for *_xy, s in burnt(blocks(lth)[3][1])} == {400} and '"bitmapMode":"passthrough"' in "\n".join(lth))
doc.layer(4).dither = "jarvis"
check("retinatura che ha anche xTool Studio: il suo nome nel commento", '"bitmapMode":"Jarvis"' in "\n".join(m2.build(doc, when=WHEN)[0]))
doc.layer(4).dither = "grayscale"
doc.layer(4).image_start = "left"
_ls, rs = m2.build(doc, when=WHEN)
check("foto impostata per partire da sinistra: qui sempre dall'alto, e lo dice", rs["notes"] == ["image_start"]
      and doc.layer(4).image_start == "left")
doc.layer(4).image_start = "top"
doc.layer(4).passes = 2
check("2 passate di una foto: le righe si ripetono", len(scanlines(blocks(m2.build(doc, when=WHEN)[0])[3][1])) == 900)
doc.layer(4).passes = 1
doc2 = Document()
doc2.layer(4).mode = "image"
doc2.images["g"] = doc.images["g"]
put(doc2, ImageShape("g", 60, 45, layer=4), 220, 110)
put(doc2, ImageShape("g", 60, 45, layer=4), 120, 200, rot=30)
l2, r2 = m2.build(doc2, when=WHEN)
check("due foto sullo stesso livello: un blocco ciascuna (anche quella ruotata)",
      [b[0][3] for b in blocks(l2)] == ["M1002 S0P3", "M1002 S0P3"] and r2["layers"] == [(4, m2.PHOTO, 2)])

print("--- cornice")
st_frame = """
# JS002 HEAD
# WorkingInfo={"head":0}
# WorkingInfo={"proc_mode":[]}
# WorkingInfo={"thickness":3.0}
# WorkingInfo={"process_bbox":[20,51.029,371.9,300]}
# WorkingInfo={"max_power":0}
# WorkingInfo={"min_speed":80}


# JS002 VECTOR HEAD
# motion_start
M1001 S1P1B0
M1002 S0P0
M32 X1000Y1000

# blockConfig={"powerFactor": 0, "isVector": true}
G0X20Y51.029
G0Z0.000
G0X20Y51.029
G1X371.9Y51.029S0F4800
G1X371.9Y300
G1X20Y300
G1X20Y51.029
# JS002 END"""
st_frame = st_frame.replace('"isVector": true}', '"isVector": true} ')  # nel file c'è uno spazio in coda
fr0 = m2.frame((20, 51.029, 371.9, 300), 10, 3.0, offset=False)
check("cornice senza scostamento: riga per riga quella che xTool Studio scrive senza macchina",
      fr0 == st_frame.split("\n"), [(a, b) for a, b in zip(fr0, st_frame.split("\n")) if a != b])
fr1 = m2.frame((20, 51.029, 371.9, 300), 10, 3.0)
check("cornice per il laser a luce debole: stesso rettangolo con lo scostamento della testa tolto, potenza zero, "
      "testa alzata", "G0X20Y41.229" in fr1 and "G1X371.9Y290.2" in fr1 and "G0Z0.000" in fr1
      and '# WorkingInfo={"head":3}' in fr1 and not any(re.search(r"S[1-9]", l) for l in fr1 if l.startswith("G")))

print("--- che cosa resta fuori, che cosa non si scrive")
doc3, rect3, _c3, _r3, photo3 = make()
doc3.layer(2).output = False
hidden = put(doc3, RectShape(10, 10, layer=1), 200, 20)
hidden.hidden = True
tool = put(doc3, RectShape(300, 200, layer=30), 5, 5)
stray = put(doc3, RectShape(10, 10, layer=4), 300, 20)  # disegno su un livello Immagine
l3, r3 = m2.build(doc3, when=WHEN)
check("livello spento, forme nascoste, livelli strumenti e disegni su un livello Immagine restano fuori",
      [k for _i, k, _n in r3["layers"]] == [m2.LINE, m2.FILL, m2.PHOTO] and len(r3["skipped"]) == 3
      and "M1002 S0P1" not in l3, (r3["layers"], r3["skipped"]))
only, ro = m2.build(doc3, shapes=[rect3], when=WHEN)
check("si può scrivere solo una parte del disegno (la selezione)", ro["layers"] == [(1, m2.LINE, 1)]
      and len(blocks(only)) == 1 and '"proc_mode":[0]' in "\n".join(only))
out_path = os.path.join(TMP, "lavoro-M2.txt")
frame_path = os.path.join(TMP, "lavoro-M2-cornice.txt")
rw = m2.export_gcode(doc, out_path, frame_path=frame_path, laser_w=10, thickness=3.0, when=WHEN, app_version="0.20.6")
saved = open(out_path, encoding="utf-8").read()
check("il file: le stesse righe, a capo semplici, e la cornice accanto con l'ingombro del lavoro",
      saved == text + "\n" and "\r" not in saved and rw["lines"] == len(lines)
      and "G1X280Y290.2" in open(frame_path, encoding="utf-8").read(), rw["lines"])
far = put(doc, RectShape(50, 30, layer=1), 400, 20)  # esce a destra dall'area di 426 mm
open(out_path, "w").write("vecchio")
try:
    m2.export_gcode(doc, out_path, laser_w=10)
    raised = False
except m2.OutsideArea:
    raised = True
check("disegno che esce dall'area: il lavoro non si scrive e il file che c'era resta com'era",
      raised and open(out_path).read() == "vecchio" and m2.plan(doc)[1]["outside"] == 1)
doc.shapes.remove(far)
try:
    m2.build(Document())
    empty = False
except ValueError:
    empty = True
check("piano vuoto: errore, niente file", empty)
_ = (circle, ringshape, photo, photo3, tool, stray, json)

print("--- comando nel programma")
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
from PySide6.QtWidgets import QMessageBox  # noqa: E402

warned = []
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2]) or QMessageBox.Ok)
from freelasercut import i18n  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui.dialogs_xtool import XToolExportDialog  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
acts = w.m_file.actions()
check("comando nel menu File, subito dopo «Esporta per xTool Studio», con «sperimentale» nel nome e la scheda di aiuto",
      acts.index(w.acts["export_m2"]) == acts.index(w.acts["export_xs"]) + 1
      and "sperimentale" in w.acts["export_m2"].text() and "export_m2" in help_texts.HELP
      and "non" in help_texts.HELP["export_m2"][1])
w.editor.set_document(doc)
ui_path = os.path.join(TMP, "dal-programma-M2.txt")
rep_ui = w.file_export_m2(path=ui_path, laser_w=10, thickness=3.0)
ui_text = open(ui_path, encoding="utf-8").read()
check("dal programma: lavoro e cornice scritti, con la versione di FreeLaserCut e lo spessore",
      rep_ui and ui_text.splitlines()[1].startswith("# version=FreeLaserCut 0.")
      and '"thickness":3.0' in ui_text and os.path.exists(os.path.join(TMP, "dal-programma-M2-cornice.txt"))
      and "sperimental" not in ui_text and "in prova" in w.statusBar().currentMessage())
w.editor.select([rect])
rep_sel = w.file_export_m2(path=os.path.join(TMP, "selezione-M2.txt"), laser_w=10, thickness=0.0)
check("con una selezione si scrive solo quella", rep_sel["layers"] == [(1, m2.LINE, 1)])
w.editor.select([])
far = put(doc, RectShape(50, 30, layer=1), 400, 20)
gone = os.path.join(TMP, "fuori-M2.txt")
check("disegno fuori dall'area: avviso con le misure dell'area, nessun file",
      w.file_export_m2(path=gone, laser_w=10, thickness=0.0) is None and not os.path.exists(gone)
      and warned and "426" in warned[-1] and "320" in warned[-1], warned[-1:])
doc.shapes.remove(far)
w.editor.set_document(Document())
check("piano vuoto: non scrive niente e lo dice", w.file_export_m2(path=os.path.join(TMP, "vuoto-M2.txt")) is None
      and not os.path.exists(os.path.join(TMP, "vuoto-M2.txt")))
w.editor.set_document(doc)
n_warn = len(warned)
check("cartella che non esiste: avviso, nessun errore",
      w.file_export_m2(path=os.path.join(TMP, "no", "x.txt"), laser_w=10, thickness=0.0) is None and len(warned) == n_warn + 1)
dlg = XToolExportDialog(doc, [doc.layer(i) for i in (1, 2, 3, 4)], 20, job=True, thickness=4.5)
check("finestra del lavoro: dice che è in prova e che non viene inviato, chiede modulo, spessore e tagli",
      "sperimentale" in dlg.windowTitle() and dlg.laser_w() == 20 and near(dlg.thickness(), 4.5) and dlg.thick.isVisibleTo(dlg)
      and dlg.cut_layers() == {2} and near(dlg.thick.maximum(), 25.8))
dlg.close()
dlg2 = XToolExportDialog(doc, [doc.layer(1)], 10)
check("finestra del progetto per xTool Studio: resta com'era, senza lo spessore",
      "xTool Studio" in dlg2.windowTitle() and not dlg2.thick.isVisibleTo(dlg2))
dlg2.close()
missing = []
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    for key in ("Lavoro per xTool M2 (sperimentale)…", "Lavoro per xTool M2 (sperimentale)", "Spessore del materiale",
                "Salva il lavoro…", "G-code per xTool M2 (*.txt)"):
        if not cat.get(key) or (cat[key] == key and "xTool" not in key):
            missing.append((lang, key))
check("le voci nuove ci sono nelle 4 lingue", not missing, missing)
_ = i18n

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
