# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.13.6: Puzzle da foto (Strumenti → Puzzle da foto…); l'installatore chiude da solo il collegamento con
Claude (server MCP) che teneva occupato python.exe durante gli aggiornamenti."""
import sys, os, re, time, math, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import cv2
from PIL import Image, ImageDraw
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
app = QApplication([])
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
from freelasercut.core import puzzle as P, gcode
from freelasercut.core.document import EllipseShape, GroupShape, ImageShape, PathShape, RectShape

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)


def regions(pz, px=8):
    """Quante parti separano davvero i tagli (contorno pieno, tagli larghi 2 punti)."""
    m = np.zeros((int(pz.height * px) + 4, int(pz.width * px) + 4), np.uint8)
    cv2.fillPoly(m, [np.round(np.array(pz.outline) * px).astype(np.int32)], 255)
    for c in pz.cuts:
        cv2.polylines(m, [np.round(np.array(c) * px).astype(np.int32)], False, 0, 2)
    n, _lab, st, _c = cv2.connectedComponentsWithStats(m, connectivity=4)
    return len([a for a in st[1:, 4] if a > px * px * 20])


def sound(pz, n):
    """Pezzi giusti: coprono tutto senza buchi né sovrapposizioni, i tagli li separano tutti, nessuno minuscolo o
    unito al vicino da un filo, numero vicino a quello chiesto."""
    areas = [P._area(p) for p in pz.pieces]
    nominal = (pz.width / pz.cols) * (pz.height / pz.rows)
    return (regions(pz) == len(pz.pieces) and abs(sum(areas) - P._area(pz.outline)) < 1.0
            and min(areas) > 0.35 * nominal and all(P._solid([P._to_int(p)]) for p in pz.pieces)
            and abs(len(pz.pieces) - n) <= max(3, 0.12 * n))


# ================================================================== generatore
a = P.generate(200, 150, 30, seed=7)
check("30 pezzi su 200 × 150 mm: 5 × 6, tutti giusti", (a.rows, a.cols) == (5, 6) and len(a.pieces) == 30 and sound(a, 30),
      (a.rows, a.cols, len(a.pieces)))
check("stesso seme, stesso puzzle (l'anteprima è quello che si taglia)", P.generate(200, 150, 30, seed=7).cuts == a.cuts)
check("«Rimescola» (altro seme): pezzi diversi", P.generate(200, 150, 30, seed=8).cuts != a.cuts)
check("un taglio per ogni lato interno, più il contorno (niente tagli doppi)",
      len(a.cuts) == 1 + a.rows * (a.cols - 1) + a.cols * (a.rows - 1), len(a.cuts))
check("ogni lato interno ha l'incastro (testa e collo)", all(len(c) > 20 for c in a.cuts[1:]))
check("collo degli incastri misurato: con 30 pezzi più di 3 mm", a.neck_mm > 3.0 and not a.warnings, round(a.neck_mm, 2))
bad = []
for seed in range(1, 5):
    for (w, h, n, k) in ((200, 150, 100, None), (300, 200, 300, None), (180, 160, 40, "heart"), (150, 150, 60, "heart"),
                         (200, 200, 80, "circle"), (250, 160, 70, "oval"), (120, 200, 25, "oval")):
        pz = P.generate(w, h, n, seed=seed, shape=P.outline_for(k, w, h) if k else None)
        if not sound(pz, n):
            bad.append((seed, w, h, n, k, len(pz.pieces)))
check("28 puzzle diversi (rettangoli fino a 300 pezzi, cuori, cerchi, ovali): tutti i pezzi giusti", not bad, bad[:3])
hz = P.generate(180, 160, 40, seed=5, shape=P.heart(180, 160))
lone = []
for c in hz.cuts[1:]:
    q = np.array(c)
    lone.append(any(cv2.pointPolygonTest(np.array(hz.outline, np.float32), (float(x), float(y)), True) > 0.5 for x, y in q))
check("cuore: tagli tutti dentro la forma, contorno a forma di cuore", all(lone)
      and abs(P._area(hz.outline) - P._area(P.heart(180, 160))) < 1.0)
retry = [P.generate(180, 160, 40, seed=sd, shape=P.heart(180, 160)) for sd in (6, 14)]
check("puzzle che richiedono un altro tentativo: stesse misure, pezzi giusti", all(abs(r.width - 180) < 1e-9 and sound(r, 40)
      for r in retry), [(r.width, len(r.pieces)) for r in retry])
sq = [(0, 0), (60, 0), (60, 60), (0, 60)]
psq = P.generate(60, 60, 30, seed=1, shape=sq)
o = np.array(psq.outline, np.float32)
on_edge = sum(math.dist(a_, b_) for c in psq.cuts[1:] for a_, b_ in zip(c[:-1], c[1:])
              if abs(cv2.pointPolygonTest(o, ((a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2), True)) < 0.05)
check("forma con i lati sul bordo (quadrato disegnato): il contorno non si taglia due volte", on_edge < 0.5 and sound(psq, 30),
      round(on_edge, 2))
star = [(50 + 45 * math.cos(math.radians(-90 + 144 * k)), 50 + 45 * math.sin(math.radians(-90 + 144 * k))) for k in range(5)]
pst = P.generate(100, 100, 25, seed=1, shape=star)
check("stella disegnata con una linea che si incrocia: ne prende il bordo esterno, pezzi giusti",
      regions(pst) == len(pst.pieces) and len(pst.outline) > 6, (regions(pst), len(pst.pieces)))
try:
    P.generate(100, 100, 30, seed=1, shape=[(0, 0), (50, 50), (100, 100)])
    deg = False
except ValueError:
    deg = True
check("forma senza area (punti in fila): errore chiaro, niente attese", deg)
plong = P.generate(1500, 20, 7, seed=1)
check("puzzle lungo e stretto (1500 × 20 mm): incastri proporzionati, pezzi giusti", sound(plong, 7))
p_cap = P.generate(20, 20, 1000, seed=1)
check("troppi pezzi per le misure: limitati a pezzi di almeno 3 mm, con avviso",
      len(p_cap.pieces) <= 45 and any("3 mm" in w_ for w_ in p_cap.warnings), (len(p_cap.pieces), p_cap.warnings[-1:]))
small = P.generate(150, 100, 400, seed=1)
check("pezzi troppo piccoli o colli sottili: avviso chiaro", small.warnings and any("mm" in w for w in small.warnings),
      small.warnings)
check("numero di pezzi tra 4 e 1000", len(P.generate(100, 100, 1, seed=1).pieces) >= 4 and P.COUNT_MAX == 1000)
t = time.time(); big = P.generate(300, 300, 300, seed=2, shape=P.outline_for("circle", 300, 300)); dt = time.time() - t
check("300 pezzi in un cerchio: pochi secondi", dt < 8 and sound(big, 300), round(dt, 2))
check("forme proposte: rettangolo, cuore, cerchio, ovale, forma selezionata",
      list(P.SHAPES) == ["rect", "heart", "circle", "oval", "selected"])

# ================================================================== finestra
from freelasercut.ui import dialogs_puzzle as DP
photo = Image.fromarray(np.tile(np.linspace(0, 255, 400, dtype=np.uint8), (300, 1)))
dlg = DP.PuzzleDialog(None, photo, (100.0, 75.0))
check("finestra: anteprima con la foto e i tagli, 30 pezzi di partenza",
      dlg.puzzle is not None and len(dlg.puzzle.pieces) == 30 and not dlg.preview.pixmap().isNull())
check("senza forma selezionata la voce «La forma selezionata» non c'è", dlg.shape.findData("selected") < 0)
dlg.w.setValue(200.0)
check("proporzioni della foto: cambiando la larghezza cambia anche l'altezza", abs(dlg.h.value() - 150.0) < 0.2, dlg.h.value())
before = dlg.puzzle.cuts
dlg._shuffle()
check("Rimescola: un altro puzzle", dlg.puzzle.cuts != before and dlg.seed == 2)
dlg.shape.setCurrentIndex(dlg.shape.findData("heart")); dlg._refresh()
check("forma a cuore nell'anteprima", abs(P._area(dlg.puzzle.outline) - P._area(P.heart(200, 150))) < 1.0
      and len(dlg.puzzle.pieces) > 20)
dlg.count.setValue(5000)
check("pezzi al massimo 1000", dlg.count.value() == 1000)
dlg.shape.setCurrentIndex(dlg.shape.findData("rect"))
dlg.count.setValue(30)
dlg.w.setValue(160.0)
dlg.accept()  # Invio subito dopo aver cambiato la misura: il puzzle è quello nuovo
check("«Crea il puzzle» subito dopo aver cambiato una misura: usa la misura nuova", abs(dlg.puzzle.width - 160.0) < 1e-6,
      dlg.puzzle.width)
dlg._no_photo()
check("«Senza foto»: solo i tagli", dlg.photo is None and not dlg.keep.isVisible())
sq = [(0, 0), (60, 0), (60, 60), (0, 60)]
dlg2 = DP.PuzzleDialog(None, None, (60.0, 60.0), sq)
check("con una forma selezionata: proposta per prima e misure prese dalla forma",
      dlg2.kind() == "selected" and not dlg2.w.isEnabled() and abs(P._area(dlg2.puzzle.outline) - 3600) < 0.01)
tiny = [(0, 0), (12, 0), (12, 9), (0, 9)]
dlg3 = DP.PuzzleDialog(None, None, (12.0, 9.0), tiny)
check("forma selezionata più piccola di 20 mm: il puzzle ha le sue misure vere", dlg3.size_mm() == (12, 9)
      and abs(dlg3.puzzle.width - 12) < 1e-9)
path = DP.cuts_path(a, 0, 0)
subs = path.toSubpathPolygons()
check("nel tracciato del taglio il contorno è l'ultimo (giusto anche con l'ottimizzazione dei percorsi spenta)",
      len(subs) == len(a.cuts) and subs[-1].isClosed() and abs(subs[-1].boundingRect().width() - 200) < 1e-6)
g = DP.fit_photo(photo, 100, 100, P.outline_for("circle", 100, 100))
arr = np.asarray(g)
check("foto adattata al puzzle: ritagliata al centro, bianca fuori dal cerchio (gli scarti non si incidono)",
      g.size == (300, 300) and arr[2, 2] == 255 and arr[-3, -3] == 255 and arr[150, 20] < 255)

# ================================================================== dal programma
from freelasercut.ui.main_window import MainWindow
w = MainWindow()
tools_menu = [m.menu() for m in w.menuBar().actions() if m.menu() and w.acts["code"] in m.menu().actions()][0]
check("Strumenti → Puzzle da foto… con l'aiuto", w.acts["puzzle"] in tools_menu.actions()
      and "puzzle" in __import__("freelasercut.ui.help_texts", fromlist=["HELP"]).HELP)
doc = w.editor.doc
doc.images["foto"] = photo.convert("L")
ph = ImageShape("foto", 100, 75, layer=0)
ph.apply(QTransform.fromTranslate(50, 60))
doc.layer(0).mode = "image"
doc.layer(0).dither = "jarvis"
w.editor.add([ph], "foto")
w.editor.select([ph])
orig_exec = DP.PuzzleDialog.exec
DP.PuzzleDialog.exec = lambda self: QDialog.Accepted
grp = w.puzzle_dialog()
kids = grp.children if isinstance(grp, GroupShape) else []
img = [k for k in kids if isinstance(k, ImageShape)]
cut = [k for k in kids if isinstance(k, PathShape)]
check("crea un gruppo: la foto e i tagli", len(img) == 1 and len(cut) == 1)
check("la foto resta sul suo livello Immagine (con il metodo scelto), al posto della foto di prima",
      img and img[0].layer == 0 and doc.layer(0).mode == "image" and doc.layer(0).dither == "jarvis"
      and ph not in doc.shapes and grp in doc.shapes)
b = grp.bounds()
check("stesso posto e stesse misure della foto", abs(b.left() - 50) < 0.01 and abs(b.top() - 60) < 0.01
      and abs(b.width() - 100) < 0.05 and abs(b.height() - 75) < 0.05, (b.left(), b.top(), b.width(), b.height()))
cs_cut = doc.layer(cut[0].layer) if cut else None
check("tagli su un livello Linea «Puzzle: taglio», messo per ultimo",
      cs_cut is not None and cs_cut.mode == "line" and cs_cut.name == "Puzzle: taglio"
      and doc.used_layers()[-1] is cs_cut)
job = gcode.generate(doc, w.profile, gcode.JobOptions(start_from="absolute"))
order = [l for l in job.lines if l.startswith("; livello")]
check("nel lavoro: prima la foto, poi il taglio", len(order) == 2 and "image" in order[0] and "line" in order[1], order)
# ultimo tratto inciso del taglio = contorno (i lati interni prima, il contorno per ultimo)
x, y, mode, s_on, last = None, None, "G0", 0.0, []
cut_part = job.lines[job.lines.index(order[1]):]
for l in cut_part:
    mg = re.match(r"G([01])\b", l)
    if mg:
        mode = "G" + mg.group(1)
    mx, my, ms = re.search(r"X(-?[\d.]+)", l), re.search(r"Y(-?[\d.]+)", l), re.search(r"S([\d.]+)", l)
    if ms:
        s_on = float(ms.group(1))
    nx = float(mx.group(1)) if mx else x
    ny = float(my.group(1)) if my else y
    if mode == "G1" and s_on > 0 and x is not None:
        last.append((nx, ny))
    x, y = nx, ny
tail = last[-4:]
on_border = all(min(abs(px - 50), abs(px - 150)) < 0.05 or min(abs(py - 60), abs(py - 135)) < 0.05 for px, py in tail)
check("il contorno si taglia per ultimo (il foglio non si sposta mentre si tagliano i pezzi)", on_border and len(last) > 50, tail)
job2 = gcode.generate(doc, w.profile, gcode.JobOptions(start_from="absolute", optimize=False, inner_first=False))


def burn_points(lines):
    x, y, mode, s_on, pts = None, None, "G0", 0.0, []
    for l in lines:
        mg = re.match(r"G([01])\b", l)
        if mg:
            mode = "G" + mg.group(1)
        mx, my, ms = re.search(r"X(-?[\d.]+)", l), re.search(r"Y(-?[\d.]+)", l), re.search(r"S([\d.]+)", l)
        if ms:
            s_on = float(ms.group(1))
        nx = float(mx.group(1)) if mx else x
        ny = float(my.group(1)) if my else y
        if mode == "G1" and s_on > 0 and x is not None:
            pts.append((nx, ny))
        x, y = nx, ny
    return pts


cut2 = job2.lines[job2.lines.index([l for l in job2.lines if l.startswith("; livello Puzzle")][0]):]
tail2 = burn_points(cut2)[-4:]
check("con «Ottimizza i percorsi» spento il contorno resta per ultimo",
      len(tail2) == 4 and all(min(abs(px - 50), abs(px - 150)) < 0.05 or min(abs(py - 60), abs(py - 135)) < 0.05
                              for px, py in tail2), tail2)
w.editor.undo()
check("Annulla: torna la foto di prima", ph.id in [s.id for s in doc.shapes] and not any(isinstance(s, GroupShape) for s in doc.shapes))
# foto + forma disegnata
doc2 = w.editor.doc
el = EllipseShape(80, 60, layer=1)
el.apply(QTransform.fromTranslate(200, 100))
ph2 = [s for s in doc2.shapes if isinstance(s, ImageShape)][0]
w.editor.add([el], "ellisse")
w.editor.select([ph2, el])
grp2 = w.puzzle_dialog()
b2 = grp2.bounds() if grp2 is not None else None
im2 = [k for k in grp2.children if isinstance(k, ImageShape)][0] if grp2 else None
pix = np.asarray(doc2.images[im2.image_id]) if im2 else None
check("foto + forma disegnata: il puzzle prende la forma (e il suo posto), la forma e la foto diventano il puzzle",
      grp2 is not None and abs(b2.left() - 200) < 0.1 and abs(b2.width() - 80) < 0.2
      and el not in doc2.shapes and ph2 not in doc2.shapes and pix[1, 1] == 255, b2)
w.editor.undo()
w.editor.select([])
grp3 = w.puzzle_dialog()
check("senza niente selezionato: puzzle solo di tagli (si sceglie la foto nella finestra)",
      grp3 is not None and all(isinstance(k, PathShape) for k in grp3.children))
w.editor.undo()
ph3 = [s for s in w.editor.doc.shapes if isinstance(s, ImageShape)][0]
# livello libero già usato prima (nome, priorità altissima, «non incidere»): il puzzle lo riparte da zero
free = w._free_layers(1)[0]
stale = w.editor.doc.layer(free)
stale.name, stale.priority, stale.output = "vecchio", 99, False
w.editor.select([ph3])
grp5 = w.puzzle_dialog()
c5 = w.editor.doc.layer([k for k in grp5.children if isinstance(k, PathShape)][0].layer)
check("livello del taglio ripartito da zero (nome, si incide, per ultimo)", c5.name == "Puzzle: taglio" and c5.output
      and w.editor.doc.used_layers()[-1] is c5 and c5.priority < 99)
w.editor.undo()
ph3 = [s for s in w.editor.doc.shapes if isinstance(s, ImageShape)][0]
WARN.clear()
gr = GroupShape([ph3.clone()])
w.editor.add([gr], "gruppo")
w.editor.select([gr])
n_before = len(w.editor.doc.shapes)
check("foto dentro un gruppo: avviso chiaro, niente cambia", w.puzzle_dialog() is None and WARN and "gruppo" in WARN[-1]
      and len(w.editor.doc.shapes) == n_before)
w.editor.undo()
rot = ph3.clone()
rot.apply(QTransform().rotate(30))
w.editor.add([rot], "ruotata")
w.editor.select([rot])
WARN.clear()
check("foto ruotata: avviso di rimetterla dritta, niente cambia", w.puzzle_dialog() is None and WARN and "ruotata" in WARN[-1])
w.editor.undo()
ph3 = [s for s in w.editor.doc.shapes if isinstance(s, ImageShape)][0]
w.editor.select([ph3])
DP.PuzzleDialog.exec = lambda self: (self._no_photo(), QDialog.Accepted)[1]
grp4 = w.puzzle_dialog()
check("foto selezionata ma «Senza foto»: la foto resta dov'era, si aggiungono solo i tagli",
      grp4 is not None and ph3 in w.editor.doc.shapes and all(isinstance(k, PathShape) for k in grp4.children))
DP.PuzzleDialog.exec = orig_exec
banco_src = open(os.path.join(ROOT, "freelasercut", "ui", "banco.py"), encoding="utf-8").read()
check("nel Banco: pulsante Puzzle accanto a Testo curvo", '"text_path", "puzzle"' in banco_src)

# ================================================================== installatore
nsi = open(os.path.join(ROOT, "build", "installer.nsi"), encoding="utf-8").read()
mac = nsi[nsi.index("!macro FLC_ASPETTA_CHIUSO"):]
fn = nsi[nsi.index("Function ${UN}FlcChiudiMcp"):nsi.index("FunctionEnd", nsi.index("Function ${UN}FlcChiudiMcp"))]
check("installatore: prima di controllare se FreeLaserCut è aperto chiude il collegamento con Claude, anche a ogni «Riprova»",
      mac.index("Call ${UN}FlcChiudiMcp") < mac.index("Call ${UN}FlcInUso") and "IDRETRY flc_chiudi_mcp" in mac)
check("…solo python.exe della cartella del programma che fa da server MCP (mai FreeLaserCut aperto, pythonw.exe)",
      "'python.exe'" in fn and "mcp_server" in fn and "server[\\\\/]main" in fn and "pythonw" not in fn.split("nsExec")[1]
      and "FLC_PYDIR" in fn)
check("…e se resta occupato, l'avviso dice di chiudere anche Claude", "chiudi anche Claude" in nsi)

print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
