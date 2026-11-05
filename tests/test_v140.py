# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.14.0: «Schizzo del soggetto (sfondo tolto)» in Prepara foto; Strumenti → Scultura 3D da modello
(a strati e a incastro, modelli .stl/.obj o inclusi, anteprima 3D fatta in casa, pezzi sui fogli)."""
import sys, os, time, math, struct, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import cv2
from PIL import Image
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
app = QApplication([])
WARN = []
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
from freelasercut.core import photo, photo_fx, sculpt as S, render3d as R

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)


# ================================================================== schizzo del soggetto
check("«Schizzo del soggetto (sfondo tolto)» tra gli effetti, dopo il ritratto a matita; gli altri ci sono tutti",
      list(photo_fx.EFFECTS)[1:4] == ["pencil", "drawing", "sketch"] and len(photo_fx.EFFECTS) == 12)
rng = np.random.default_rng(4)
H, W = 600, 800
bg = np.zeros((H, W, 3), np.uint8)
bg[:] = (120, 150, 190)  # sfondo azzurrino con un po' di grana
bg = np.clip(bg + rng.normal(0, 6, bg.shape), 0, 255).astype(np.uint8)
cv2.rectangle(bg, (0, 470), (W, H), (90, 70, 50), -1)  # pavimento
scene = bg.copy()
cv2.ellipse(scene, (400, 330), (150, 210), 0, 0, 360, (215, 170, 95), -1)  # «animale» color miele
body = np.zeros((H, W), np.uint8); cv2.ellipse(body, (400, 330), (150, 210), 0, 0, 360, 1, -1)
ramp = (0.45 + 0.6 * np.arange(W) / W)[None, :, None]  # luce da destra: ombreggiato a sinistra
scene = np.where(body[..., None] > 0, np.clip(scene * ramp, 0, 255), scene).astype(np.uint8)
cv2.circle(scene, (350, 270), 14, (20, 15, 10), -1)  # occhi e naso
cv2.circle(scene, (450, 270), 14, (20, 15, 10), -1)
cv2.circle(scene, (400, 340), 18, (25, 20, 15), -1)
for k in range(60):  # pelo
    y = int(rng.integers(160, 520)); x = int(rng.integers(280, 520))
    cv2.line(scene, (x, y), (x + 6, y + 14), (190, 145, 80), 2)
gray = cv2.cvtColor(scene, cv2.COLOR_RGB2GRAY).astype(np.float32)
photo_fx._MASK_CACHE.clear()
m = photo_fx.subject_mask(scene)
inside = np.zeros((H, W), np.uint8); cv2.ellipse(inside, (400, 330), (140, 200), 0, 0, 360, 1, -1)
check("trova il soggetto in primo piano (dentro sì, angoli e pavimento no)",
      m is not None and m[inside > 0].mean() > 0.9 and m[:60, :60].mean() < 0.05 and m[560:, 700:].mean() < 0.05,
      None if m is None else (round(float(m[inside > 0].mean()), 3), round(float(m[:60, :60].mean()), 3)))
out, sc = photo_fx.apply(gray, "sketch", 80.0, 0.5, 0.5, 0, rgb=scene)
check("sfondo tolto: angoli e pavimento bianchi (niente da incidere)", out[:80, :80].min() >= 250 and out[560:, 650:].min() >= 250,
      (float(out[:80, :80].min()), float(out[560:, 650:].min())))
check("il soggetto è disegnato: chiaroscuro (lato in ombra più scuro), occhi e naso scuri",
      (out[inside > 0] < 240).mean() > 0.1 and out[265:275, 345:355].mean() < 90 and
      out[300:360, 270:320].mean() < out[300:360, 480:530].mean() - 8,
      (round(float((out[inside > 0] < 240).mean()), 3), round(float(out[265:275, 345:355].mean()))))
dr = photo_fx.apply(gray, "drawing", 80.0, 0.5, 0.5)[0]
check("più chiaro del «Ritratto a matita» (che resta com'era)", out.mean() > dr.mean() + 20, (round(out.mean()), round(dr.mean())))
photo_fx._MASK_CACHE.clear()
out2 = photo_fx.apply(gray, "sketch", 80.0, 0.5, 0.5, 0, rgb=scene)[0]
check("sempre lo stesso risultato (anteprima e incisione uguali)", np.array_equal(out, out2))
white = photo_fx.apply(np.full((300, 400), 255.0, np.float32), "sketch", 40.0, 1.0, 1.0)[0]
check("foto bianca: niente da incidere", (white < 250).mean() == 0.0)
flat = photo_fx.apply(np.full((300, 400), 128.0, np.float32), "sketch", 40.0, 0.5, 0.5)[0]
check("foto tutta grigia o in bianco e nero (senza colori): nessun errore", flat.shape == (300, 400) and np.isfinite(flat).all())
pil = Image.fromarray(scene)
p_img = photo.process(pil, photo.PhotoSettings(effect="sketch", width_mm=80.0))
check("in «Prepara foto» usa i colori della foto per trovare il soggetto", np.asarray(p_img)[:60, :60].min() >= 250
      and p_img.size == (W, H))
big = cv2.resize(scene, (6000, 4500), interpolation=cv2.INTER_LINEAR)
t = time.time(); bo, bsc = photo_fx.apply(cv2.cvtColor(big, cv2.COLOR_RGB2GRAY).astype(np.float32), "sketch", 100.0, 0.5,
                                          0.5, 0, rgb=big); dt = time.time() - t
check("foto da 27 megapixel: pochi secondi", dt < 8 and bo.shape[1] <= 1402, (round(dt, 2), bo.shape))

# ================================================================== modelli 3D
for k in S.BUILTINS:
    mm = S.prepared(S.builtin(k), "z", 100.0)
    lo, hi = mm.bounds()
    if not (abs(hi[2] - 100) < 1e-6 and abs(lo[2]) < 1e-6 and abs(lo[0] + hi[0]) < 1e-6):
        check(f"modello incluso {k}: alto 100 mm, base a 0, centrato", False, (lo, hi))
check("modelli inclusi (cuore, stella, sfera, vaso, ciambella): alti come chiesto, base a 0, centrati",
      len(S.BUILTINS) == 5)
D = tempfile.mkdtemp()
heart = S.builtin("heart")
V, F = heart.vertices, heart.faces
P = V[F].astype(np.float32)
with open(os.path.join(D, "b.stl"), "wb") as fh:
    fh.write(b"\0" * 80 + struct.pack("<I", len(F)))
    for tri in P:
        fh.write(struct.pack("<3f", 0, 0, 0) + tri.tobytes() + b"\0\0")
with open(os.path.join(D, "a.stl"), "w") as fh:
    fh.write("solid prova\n")
    for tri in P:
        fh.write(" facet normal 0 0 0\n  outer loop\n" + "".join(f"   vertex {x} {y} {z}\n" for x, y, z in tri) +
                 "  endloop\n endfacet\n")
    fh.write("endsolid prova\n")
with open(os.path.join(D, "q.obj"), "w") as fh:  # cubo con facce quadrate e indici negativi
    for x, y, z in [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]:
        fh.write(f"v {x * 40} {y * 40} {z * 40}\n")
    for f_ in ["1 4 3 2", "5 6 7 8", "1 2 6 5", "2 3 7 6", "3 4 8 7", "4 1 5 8"]:
        fh.write("f " + " ".join(str(int(i) - 9) for i in f_.split()) + "\n")
vb, va = S.load(os.path.join(D, "b.stl")), S.load(os.path.join(D, "a.stl"))
cube = S.load(os.path.join(D, "q.obj"))
check("STL binario e di testo: stesso modello (vertici ripetuti uniti)", abs(vb.volume() - heart.volume()) < 1.0
      and abs(va.volume() - heart.volume()) < 1.0 and len(vb.vertices) == len(heart.vertices),
      (round(vb.volume()), round(heart.volume())))
check("OBJ con facce quadrate e indici negativi: cubo di 40 mm", abs(cube.volume() - 64000) < 1 and len(cube.faces) == 12)
bad = []
for name, data in (("vuoto.stl", b""), ("rotto.stl", b"solid x\nvertex 1 2\n"), ("rotto.obj", b"v 1 2 3\nf 1 2 9\n"),
                   ("testo.obj", b"ciao"), ("x.ply", b"ply")):
    fp = os.path.join(D, name); open(fp, "wb").write(data)
    try:
        S.load(fp); bad.append(name)
    except ValueError:
        pass
check("file rovinati o di altri formati: errore chiaro, niente blocchi", not bad, bad)
try:
    S.prepared(S.Mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float), np.array([[0, 1, 2]])), "z", 100)
    flat_ok = False
except ValueError:
    flat_ok = True
check("modello piatto in verticale: chiede un altro asse", flat_ok)
fp = os.path.join(D, "coda.stl")  # STL binario con due byte in più alla fine e «solid» nell'intestazione
open(fp, "wb").write(b"solid esportato".ljust(80, b" ") + open(os.path.join(D, "b.stl"), "rb").read()[80:] + b"\0\0")
check("STL binario con byte in più alla fine (e «solid» nell'intestazione): si apre", len(S.load(fp).faces) == len(heart.faces))
fp = os.path.join(D, "avanzi.obj")
open(fp, "w").write("v 0 0 0\nv 10 0 0\nv 0 10 0\nv 0 0 10\nv 500 500 500\nf 1 3 2\nf 1 2 4\nf 2 3 4\nf 1 4 3\n")
check("OBJ con vertici non usati: non cambiano le misure", np.allclose(S.load(fp).bounds()[1], [10, 10, 10]))
sp = S.builtin("sphere")
two = S.prepared(S.Mesh(np.vstack([sp.vertices, sp.vertices + [0.4, 0, 0]]),
                        np.vstack([sp.faces, sp.faces + len(sp.vertices)])), "z", 100.0)
isl2 = S.islands(S.section(two, 2, 50.0))
check("modello fatto di due corpi sovrapposti: la sezione resta piena (nessun vuoto dove si toccano)",
      len(isl2) == 1 and len(isl2[0].rings) == 1, [len(i.rings) for i in isl2])
ms0 = S.prepared(sp, "z", 100.0)
holed = S.Mesh(ms0.vertices, ms0.faces[np.arange(len(ms0.faces)) != len(ms0.faces) // 2])
Lh, L0 = S.layered(holed, 3.0), S.layered(ms0, 3.0)
check("modello con un buco (non chiuso): nessuna fetta persa e un avviso",
      len(Lh.pieces) == len(L0.pieces) and Lh.warnings and not L0.warnings, (len(Lh.pieces), len(L0.pieces)))
inv = S.layered(S.Mesh(ms0.vertices, ms0.faces[:, ::-1]), 3.0)
check("modello con i triangoli girati al contrario: stesse fette",
      abs(sum(p.island.area() for p in inv.pieces) - sum(p.island.area() for p in L0.pieces)) < 1)
cy = S.prepared(cube, "y", 100.0)
check("asse verticale Y (OBJ): il modello si raddrizza", abs(cy.bounds()[1][2] - 100) < 1e-6)

# ================================================================== a strati
bad_vol, worst = [], 0
for k in S.BUILTINS:
    mm = S.prepared(S.builtin(k), "z", 100.0)
    L = S.layered(mm, 1.0)
    est = sum(p.island.area() for p in L.pieces) * 1.0
    err = abs(est - mm.volume()) / mm.volume()
    worst = max(worst, err)
    if err > 0.02:
        bad_vol.append((k, round(err, 3)))
check("strati: il volume delle fette è quello del modello (entro il 2%)", not bad_vol, (bad_vol, round(worst, 4)))
mh = S.prepared(S.builtin("heart"), "z", 120.0)
L = S.layered(mh, 3.0)
names = [p.name for p in L.pieces]
check("strati di 3 mm su 120 mm: 39-40 fette (la punta più sottile di un millimetro quadro non si taglia), nomi diversi",
      39 <= len({p.plane for p in L.pieces}) <= 40 and len(set(names)) == len(names),
      len({p.plane for p in L.pieces}))


def inside_island(isl, u, v):
    n = 0
    for r in isl.rings:
        n += cv2.pointPolygonTest(np.asarray(r, np.float32), (float(u), float(v)), False) >= 0
    return n % 2 == 1


check("il nome di ogni fetta sta dentro la fetta", all(inside_island(p.island, p.label[0], p.label[1]) for p in L.pieces))
gd = [p for p in L.pieces if p.guides]
check("dove la fetta sopra è più piccola è inciso dove appoggiarla, dentro la fetta",
      len(gd) >= 20 and np.mean([inside_island(p.island, *np.asarray(g).mean(0)) for p in gd for g in p.guides]) > 0.9)
try:
    S.layered(mh, 0.2); thin = False
except ValueError:
    thin = True
check("spessore troppo piccolo: errore chiaro", thin)

# ================================================================== a incastro
ms = S.prepared(S.builtin("sphere"), "z", 120.0)
nx, ny = S.auto_counts(ms, 3.0)
I = S.interlocking(ms, 3.0, nx, ny, 0.1)
xs_ = [p for p in I.pieces if p.kind == "x"]
ys_ = [p for p in I.pieces if p.kind == "y"]
check("sfera a incastro: sagome X e Y, nessun avviso", len(xs_) == nx and len(ys_) == ny and not I.warnings,
      (nx, ny, len(xs_), len(ys_), I.warnings))
over, gaps, n_pairs = 0, 0, 0
for A in xs_:
    for B in ys_:
        za = S._intervals(A.island, 0, B.plane)
        zb = S._intervals(B.island, 0, A.plane)
        if not za or not zb:
            continue
        n_pairs += 1
        for z in np.linspace(-5, 125, 400):
            ina = inside_island(A.island, B.plane, z)
            inb = inside_island(B.island, A.plane, z)
            over += ina and inb
check("dove due sagome si incrociano non c'è mai legno doppio (si montano davvero)", n_pairs > 10 and over == 0,
      (n_pairs, over))
slot_ok = True
for A in xs_:
    for B in ys_:
        ia = S._intervals(A.island, 0, B.plane - 1.4)  # dentro la fessura (larga 3,1 mm)
        ib = S._intervals(A.island, 0, B.plane + 1.4)
        full = S._intervals(A.island, 0, B.plane + 3.0)
        if full and ia and max(v1 for _, v1 in ia) > max(v1 for _, v1 in full) - 1e-6:
            slot_ok = False
check("fessure delle X aperte dall'alto, larghe spessore + gioco", slot_ok)


def crossings_ok(I):
    """In ogni incrocio, su tutto lo spessore delle due sagome: mai legno doppio, e la X tutta sotto la Y (la Y
    scende dall'alto sulle X già messe)."""
    t = I.thickness
    lo_, hi_ = I.mesh.bounds()
    zz = np.linspace(lo_[2] - 1, hi_[2] + 1, 240)
    bad = 0
    for A in [p for p in I.pieces if p.kind == "x"]:
        for B in [p for p in I.pieces if p.kind == "y"]:
            za = [z for z in zz for du in (-t / 2 + 0.05, 0, t / 2 - 0.05) if inside_island(A.island, B.plane + du, z)]
            zb = [z for z in zz for dv in (-t / 2 + 0.05, 0, t / 2 - 0.05) if inside_island(B.island, A.plane + dv, z)]
            bad += bool(za and zb and max(za) >= min(zb))
    return bad


bad_cross = {}
for nm, up, cnt in (("heart", "y", (7, 7)), ("heart", "x", (5, 5)), ("torus", "x", None), ("star", "z", None)):
    mm_ = S.prepared(S.builtin(nm), up, 120.0)
    bad_cross[nm + up] = crossings_ok(S.interlocking(mm_, 3.0, *(cnt or S.auto_counts(mm_, 3.0))))
check("incroci controllati su tutto lo spessore (anche dove le sagome si toccano appena): si montano sempre",
      not any(bad_cross.values()), bad_cross)
check("ordine di montaggio: prima tutte le X, poi le Y", [p.kind for p in sorted(I.pieces, key=lambda p: p.order)] ==
      ["x"] * len(xs_) + ["y"] * len(ys_))
try:
    S.interlocking(ms, 3.0, 40, 40); close = False
except ValueError:
    close = True
check("sagome troppo vicine per lo spessore: errore chiaro", close)
tor = S.prepared(S.builtin("torus"), "z", 60.0)
It = S.interlocking(tor, 3.0, *S.auto_counts(tor, 3.0))
check("ciambella: le sagome con il buco diventano due pezzi ciascuna", len(It.pieces) > sum(S.auto_counts(tor, 3.0)))

# ================================================================== anteprima 3D
scn = R.sculpture_scene(L)
cam = R.fit_camera(scn)
t = time.time(); img = R.render(scn, cam, 480, 360, ss=2); dt = time.time() - t
wood = (img[..., 0].astype(int) - img[..., 2] > 40).mean()  # legno e bordi bruciati (marroni), non il pavimento
check("anteprima della scultura: immagine vera con il legno, in meno di 3 secondi",
      img.shape == (360, 480, 3) and wood > 0.1 and dt < 3, (round(float(wood), 3), round(dt, 2)))
check("stessa vista, stessa immagine", np.array_equal(img, R.render(scn, cam, 480, 360, ss=2)))
cam2 = R.fit_camera(scn, yaw=60.0)
check("girando la vista l'immagine cambia", (np.abs(R.render(scn, cam2, 240, 180, 1).astype(int) -
                                              R.render(scn, cam, 240, 180, 1).astype(int)) > 20).mean() > 0.05)
mimg = R.render(R.mesh_scene(mh), R.fit_camera(R.mesh_scene(mh)), 240, 180, 1)
check("anteprima del modello (superficie liscia)", (np.abs(mimg.astype(int) - [190, 185, 178]).sum(2) < 100).mean() > 0.05)
part = R.sculpture_scene(L, upto=10, lift=(9, 50.0))
check("montaggio: solo i pezzi già messi, l'ultimo che arriva dall'alto",
      sum(len(r) for rings, *_ in part.caps for r in rings[:1]) > 0 and len(part.caps) == 20)

# ================================================================== finestra e progetto
from freelasercut.ui import dialogs_sculpt as DS
dlg = DS.SculptDialog(None, (450.0, 440.0))
check("finestra: cuore a strati di partenza, pezzi e anteprima", dlg.sculpture is not None and len(dlg.sculpture.pieces) > 30
      and not dlg.viewer.render_image(320, 240, 1).isNull())
check("con gli strati le opzioni delle sagome sono nascoste", not dlg.counts_box.isVisibleTo(dlg))
dlg.style.setCurrentIndex(dlg.style.findData("interlocking")); dlg._rebuild()
check("a incastro: compaiono sagome e gioco delle fessure", dlg.counts_box.isVisibleTo(dlg) and dlg.fit.isVisibleTo(dlg)
      and all(p.kind in ("x", "y") for p in dlg.sculpture.pieces))
for k, _lab in DS.VIEWS:
    dlg._set_view(k)
    if dlg.viewer.render_image(160, 120, 1).isNull():
        check(f"vista {k}", False)
check("tre viste: modello, scultura, montaggio", [k for k, _ in DS.VIEWS] == ["model", "sculpture", "assembly"])
dlg._set_view("assembly")
dlg.slider.setValue(0)
dlg._toggle_play()
for _ in range(14):
    dlg._anim_tick()
check("«Monta»: i pezzi arrivano uno dopo l'altro", dlg.slider.value() >= 2, dlg.slider.value())
dlg._toggle_play()
check("apre un file .stl", dlg.load_file(os.path.join(D, "b.stl")) and dlg.model.currentData() == "file"
      and dlg.sculpture is not None)
dlg.height_mm.setValue(80.0)
dlg.accept()
check("«Crea i pezzi» subito dopo una modifica: usa le misure nuove", abs(dlg.sculpture.size()[2] - 80.0) < 1e-6)
WARN.clear()
dlg._later()
dlg.reject()
check("chiusa con Esc subito dopo una modifica: niente calcoli rimasti in sospeso",
      not dlg._timer.isActive() and not dlg._anim.isActive())
check("file rovinato nella finestra: avviso, resta il modello di prima", not dlg.load_file(os.path.join(D, "rotto.stl"))
      and WARN and dlg.sculpture is not None)

from freelasercut.ui.main_window import MainWindow
from freelasercut.core.document import GroupShape, PathShape, TextShape
w = MainWindow()
tools_menu = [m.menu() for m in w.menuBar().actions() if m.menu() and w.acts["code"] in m.menu().actions()][0]
check("Strumenti → Scultura 3D da modello… con l'aiuto", w.acts["sculpt"] in tools_menu.actions()
      and "sculpt" in __import__("freelasercut.ui.help_texts", fromlist=["HELP"]).HELP)
orig = DS.SculptDialog.exec
DS.SculptDialog.exec = lambda self: QDialog.Accepted
t = time.time()
groups = w.sculpt_dialog()
dt = time.time() - t
doc = w.editor.doc
cuts = {k.layer for g in groups for k in g.children if isinstance(k, PathShape) and not k.local_path().isEmpty()}
check("crea un gruppo per pezzo: taglio, segni e nome", groups and all(isinstance(g, GroupShape) for g in groups)
      and all(any(isinstance(k, TextShape) for k in g.children) for g in groups), (len(groups or []), round(dt, 1)))
lay = {c.name: c for c in doc.used_layers()}
check("livelli: «Scultura: segni» poi «Scultura: taglio» (per ultimo), in modalità Linea",
      "Scultura: taglio" in lay and "Scultura: segni" in lay and lay["Scultura: taglio"].mode == "line"
      and doc.used_layers()[-1] is lay["Scultura: taglio"] and doc.used_layers()[-2] is lay["Scultura: segni"])
outside = []
for g in groups:
    b = g.bounds()
    k = max(0, int(round(b.left() // (w.profile.bed_x + 20.0))))
    x0 = k * (w.profile.bed_x + 20.0)
    if b.left() < x0 - 0.01 or b.right() > x0 + w.profile.bed_x + 0.01 or b.top() < -0.01 or b.bottom() > w.profile.bed_y + 0.01:
        outside.append(g._sculpt_name if hasattr(g, "_sculpt_name") else "?")
check("tutti i pezzi sistemati dentro i fogli", not outside, outside[:5])
w.editor.undo()
check("Annulla: la scultura sparisce, anche i nomi dei livelli", not any(isinstance(s, GroupShape) for s in w.editor.doc.shapes)
      and not any(c.name.startswith("Scultura") for c in w.editor.doc.layers.values() if hasattr(c, "name")))
DS.SculptDialog.exec = orig
banco_src = open(os.path.join(ROOT, "freelasercut", "ui", "banco.py"), encoding="utf-8").read()
check("nel Banco: pulsante Scultura accanto a Puzzle", '"puzzle", "sculpt"' in banco_src)

print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
