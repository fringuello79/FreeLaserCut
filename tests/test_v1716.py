# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.16: Rilievo 3D su tavola (funzione in prova, codice amministratore).

Casi del documento di progetto «rilievo-3d-progetto»: mappe, modello della profondità, limiti, strati annidati,
sfumatura, test di profondità con accettazione ±10%, G-code (dentro le maschere, X/Y alternate, simulatore),
tarature salvate, codice amministratore, finestra.
"""
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
import numpy as np
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
ASK = {"answer": QMessageBox.Yes}
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: ASK["answer"])

import freelasercut
from freelasercut import admin
from freelasercut.core import relief as R
from freelasercut.core import sculpt
from freelasercut.profile import MachineProfile
from freelasercut.updater import parse_version

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def raises(fn):
    try:
        fn()
    except ValueError as ex:
        return str(ex) or "errore"
    return ""


check("versione 0.17.16 o successiva", parse_version(freelasercut.__version__) >= (0, 17, 16), freelasercut.__version__)

# ---------------------------------------------------------------- mappe delle altezze
g = np.tile(np.linspace(0, 255, 50), (20, 1))  # sfumatura: nero a sinistra, bianco a destra
h = R.heightmap_from_image(g, 25, 10, white_high=True)
check("immagine: bianco in alto (H=1 a destra), nero in basso", h.shape == (10, 25) and h[0, -1] > 0.95 and h[0, 0] < 0.05)
hi = R.heightmap_from_image(g, 25, 10, white_high=False)
check("…e al contrario se il nero è in alto", np.allclose(hi, 1 - h))
pyr = sculpt.Mesh(np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [5, 5, 4]], float),
                  np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4], [0, 2, 1], [0, 3, 2]]))
hm = R.heightmap_from_mesh(pyr, 41, 41)
check("modello (piramide): cima al centro H=1, bordi H≈0", hm[20, 20] > 0.95 and hm[0, 0] < 0.08 and hm[40, 40] < 0.08,
      (hm[20, 20], hm[0, 0]))
exact = 1 - np.maximum(abs(np.arange(41) + 0.5 - 20.5)[None, :], abs(np.arange(41) + 0.5 - 20.5)[:, None]) / 20.5
check("…altezze giuste punto per punto (errore < 3%)", np.max(np.abs(hm - exact)) < 0.03, np.max(np.abs(hm - exact)))
tall = sculpt.Mesh(pyr.vertices[:, [0, 2, 1]] * np.array([1, 1, -1]) + np.array([0, 0, 10]), pyr.faces)
check("asse verso l'alto: lo stesso modello girato si legge con «Y verso l'alto»",
      np.max(np.abs(R.heightmap_from_mesh(tall, 41, 41, up="y") - hm)) < 0.06)
# asimmetrico: cima spostata verso destra e verso il fondo del piano (+X, +Y); uno specchio la sposterebbe altrove
asy = sculpt.Mesh(np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [8, 8, 4]], float), pyr.faces)
ha = R.heightmap_from_mesh(asy, 40, 40)
r_, c_ = np.unravel_index(np.argmax(ha), ha.shape)
check("niente specchio (Z in alto): cima a destra e verso il fondo (righe in alto)", c_ > 28 and r_ < 12, (r_, c_))
ya = sculpt.Mesh(asy.vertices[:, [0, 2, 1]] * np.array([1, 1, -1]), asy.faces)  # come lo salva un programma «Y in alto»
check("niente specchio (Y in alto): stesso risultato del modello originale",
      np.max(np.abs(R.heightmap_from_mesh(ya, 40, 40, up="y") - ha)) < 0.06)
xa = sculpt.Mesh(asy.vertices[:, [2, 0, 1]], asy.faces)  # X in alto
check("niente specchio (X in alto): stesso risultato del modello originale",
      np.max(np.abs(R.heightmap_from_mesh(xa, 40, 40, up="x") - ha)) < 0.06)
small = sculpt.Mesh(np.vstack([pyr.vertices, [[-10, -10, 0], [20, 20, 0]]]), pyr.faces)
hb = R.heightmap_from_mesh(small, 30, 30, background="bottom")
hs = R.heightmap_from_mesh(small, 30, 30, background="surface")
check("sfondo intorno al modello: al fondo (0) oppure non inciso (1)", hb[0, 0] == 0.0 and hs[0, 0] == 1.0)
flat = sculpt.Mesh(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float), np.array([[0, 1, 2]]))
check("modello piatto in verticale: errore chiaro", "piatto" in raises(lambda: R.heightmap_from_mesh(flat, 10, 10)))
sph = R.heightmap_from_mesh(sculpt.builtin("sphere"), 60, 60)
check("modello incluso (sfera): cupola, più alta al centro che a metà raggio", sph[30, 30] > sph[30, 45] > sph[30, 58])

# ---------------------------------------------------------------- modello della profondità e limiti
m = R.DepthModel(0.12, 0.85)
check("D(n) e passate inverse coerenti", abs(float(m.depth(m.passes(2.5))) - 2.5) < 1e-9)
f = R.fit(0.12, float(m.depth(30)), 30)
check("taratura: a e b ritrovati dalle due misure", abs(f.a - 0.12) < 1e-9 and abs(f.b - 0.85) < 1e-9, (f.a, f.b))
check("misure incoerenti: rifiutate (primo zero, ultimo meno profondo, resa assurda)",
      raises(lambda: R.fit(0, 1, 5)) and raises(lambda: R.fit(0.3, 0.2, 5)) and raises(lambda: R.fit(0.1, 50, 4)))
check("massimo 5 mm a testa ferma", R.check_depth(5.0, 50, m) == "" and R.check_depth(5.01, 50, m) != "")
check("tavola da 6 mm: al massimo 4 mm", R.check_depth(4.0, 6, m) == "" and "4.00" in R.check_depth(4.5, 6, m))
sat = R.DepthModel(0.2, 0.5)
u = sat.useful_depth()
check("profondità utile: oltre, una passata rende meno del 25% della prima", abs(u - 0.2 * 4 ** 0.5) < 1e-9
      and abs(float(sat.depth(4.01) - sat.depth(3.01)) - 0.25 * 0.2) < 0.01
      and R.check_depth(u + 0.05, 50, sat) != "", u)
check("senza taratura: il modello prudente non limita la profondità utile",
      R.limits(5, 50, R.DepthModel.prior())[0] == 5.0)

# ---------------------------------------------------------------- passate (strati)
nx = ny = 80
yy, xx = np.mgrid[0:ny, 0:nx]
H = 1 - np.maximum(abs(xx - (nx - 1) / 2) / (nx / 2), abs(yy - (ny - 1) / 2) / (ny / 2))
N0 = R.pass_map(H, 3.0, m, dither=False)
T = R.target_depth(H, 3.0)
nc = m.passes(T)
step = m.depth(np.floor(nc) + 1) - m.depth(np.floor(nc))
check("senza sfumatura: errore ≤ mezzo strato in ogni punto", np.all(np.abs(m.depth(N0) - T) <= 0.5 * step + 1e-9))
ms = R.masks(N0)
check("strati annidati: ogni strato dentro il precedente", all((ms[i + 1] <= ms[i]).all() for i in range(len(ms) - 1)))
check("numero di strati = passate per il punto più profondo", len(ms) == N0.max() == int(np.floor(float(m.passes(T.max())) + 0.5)),
      (len(ms), N0.max()))
const = R.pass_map(np.full((64, 64), 0.37), 3.0, m, dither=True)
want = float(m.passes(0.63 * 3.0))
check("con la sfumatura la media delle passate è quella voluta (entro l'1%)", abs(const.mean() - want) / want < 0.01,
      (const.mean(), want))
check("…e i bordi fra strati si sfumano (due valori vicini mescolati)", set(np.unique(const)) <= {int(want), int(want) + 1}
      and len(np.unique(const)) == 2)

# ---------------------------------------------------------------- test di profondità
check("gradini del test: da 1 alle passate del lavoro, al massimo 5", R.test_steps(44) == [1, 3, 7, 17, 44]
      and R.test_steps(1) == [1] and R.test_steps(3) == [1, 2, 3], R.test_steps(44))
tm = R.test_map([1, 3, 7], 0.1)
check("scala del test: gradini 5 × 4 mm da sinistra, passate crescenti", tm.shape == (40, 150) and tm[0, 0] == 1
      and tm[0, 149] == 7 and tm[0, 75] == 3)
check("accettazione ±10%", R.accept(2.15, 2.0)[0] and not R.accept(2.3, 2.0)[0] and R.accept(1.81, 2.0)[0])
p2, redo, _ = R.after_judgment("flames", 80)
p3, redo3, _ = R.after_judgment("dark", 80)
check("giudizio a vista: fiamme −20% e nuovo test, annerito −15% e nuovo test, pulito niente",
      (p2, redo, p3, redo3) == (64.0, True, 68.0, True) and R.after_judgment("clean", 80)[:2] == (80, False))

# ---------------------------------------------------------------- G-code
prof = MachineProfile()
pitch = 0.2
job = R.build_job(N0, pitch, 50, 60, 70, 3000, prof)


def lit_points(lines):
    """[(passata, x, y)] di punti lungo i tratti accesi (coordinate di uscita = piano col profilo di partenza)."""
    out, k, x, y, s, mode = [], 0, None, None, 0.0, 0
    for ln in lines:
        if ln.startswith("; passata"):
            k = int(ln.split()[-1])
            continue
        if ln.startswith(";"):
            continue
        g = re.match(r"G(\d+)", ln)
        if g:
            mode = int(g.group(1))
        mx, my, msx = re.search(r"X(-?[\d.]+)", ln), re.search(r"Y(-?[\d.]+)", ln), re.search(r"S([\d.]+)", ln)
        if msx:
            s = float(msx.group(1))
        nx_, ny_ = (float(mx.group(1)) if mx else x), (float(my.group(1)) if my else y)
        if mode == 1 and s > 0 and k and x is not None and (nx_, ny_) != (x, y):
            for t in np.linspace(0.05, 0.95, 10):
                out.append((k, x + (nx_ - x) * t, y + (ny_ - y) * t, nx_ != x))
        x, y = nx_, ny_
    return out


pts = lit_points(job.lines)
bad = sum(1 for k, px, py, _h in pts
          if not (0 <= int((px - 50) / pitch) < nx and 0 <= ny - 1 - int((py - 60) / pitch) < ny
                  and ms[k - 1][ny - 1 - int((py - 60) / pitch), int((px - 50) / pitch)]))
check("G-code: ogni tratto acceso è dentro la maschera della sua passata", pts and bad == 0, (len(pts), bad))
odd = {h_ for k, *_r, h_ in pts if k % 2 == 1}
even = {h_ for k, *_r, h_ in pts if k % 2 == 0}
check("passate dispari lungo X, pari lungo Y", odd == {True} and even == {False}, (odd, even))
svals = {float(v) for v in re.findall(r"S([\d.]+)", "\n".join(job.lines)) if float(v) > 0}
check("stessa potenza in tutte le passate (70% di S1000)", svals == {700.0}, svals)
check("laser spento alla fine e niente fuori dal piano", "M5 S0" in job.lines[-4:] and not job.warnings)
check("ingombro = rilievo (16 × 16 mm)", abs(job.bounds.width() - 16) < 0.01 and abs(job.bounds.height() - 16) < 0.01,
      job.bounds)
v = 3000 / 60.0
from freelasercut.ui.dialogs_relief import approx_seconds

est = approx_seconds(N0, pitch, 3000)
check("tempo stimato coerente con quello del G-code (±25%)", abs(est - job.seconds) / job.seconds < 0.25,
      (est, job.seconds))
one = R.build_job(N0, pitch, 50, 60, 70, 3000, prof, alternate=False)
check("senza alternanza: tutte le passate lungo X", {h_ for *_r, h_ in lit_points(one.lines)} == {True})
tj = R.build_job(R.test_map([1, 2], pitch), pitch, 10, 10, 70, 3000, prof)
lt = lit_points(tj.lines)
x2 = [px for k, px, py, _h in lt if k == 2]
c1 = len({round(py, 2) for k, px, py, _h in lt if k == 1})  # righe della passata 1 (lungo X)
check("test: la passata 2 incide solo il gradino che ne ha due", x2 and min(x2) >= 10 + 5 - pitch and max(x2) <= 20 + 1e-6
      and c1 == 20, (min(x2) if x2 else None, c1))

# nel simulatore: tutte le righe accettate, laser spento a fine lavoro
from freelasercut.grbl import SIM_PORT, GrblController

ctl = GrblController()
done = []
ctl.job_finished.connect(lambda ok, msg: done.append((ok, msg)))
errs = []
ctl.error_raised.connect(lambda c, t, l: errs.append((c, l)))
ctl.connect_port(SIM_PORT)
end = time.time() + 5
while time.time() < end and ctl.last_status.get("state") != "Idle":
    app.processEvents()
    time.sleep(0.02)
ctl.sim.speedup = 200.0
small_job = R.build_job(R.pass_map(H[::4, ::4], 1.0, R.DepthModel(0.2, 0.9), False), 0.5, 20, 20, 50, 3000, prof)
ctl.stream_job(small_job.lines)
end = time.time() + 60
while time.time() < end and not done:
    app.processEvents()
    time.sleep(0.02)
check("simulatore: lavoro completo senza errori, laser spento", done and done[-1][0] and not errs and not ctl.sim.laser,
      (done, errs[:3]))
ctl.disconnect_port()

# ---------------------------------------------------------------- tarature salvate
cp = os.path.join(tempfile.mkdtemp(), "c.json")
k1 = R.calib_key("B1", "MDF", 80, 3000, 0.1)
R.save_calibration(k1, R.DepthModel(0.11, 0.9), 0.11, 2.0, 25, "clean", path=cp)
mm, d = R.find_calibration(k1, path=cp)
check("taratura salvata e riletta per materiale e parametri", mm is not None and abs(mm.a - 0.11) < 1e-9 and d["n"] == 25)
check("…parametri diversi (potenza) = nessuna taratura", R.find_calibration(R.calib_key("B1", "MDF", 70, 3000, 0.1),
                                                                             path=cp)[0] is None)

# ---------------------------------------------------------------- codice amministratore e finestra
import hashlib
import math

src = open(os.path.join(ROOT, "freelasercut", "admin.py"), encoding="utf-8").read()
check("nel programma c'è solo l'impronta del codice (sha256), non il codice", re.search(r'_HASH = "[0-9a-f]{64}"', src)
      and not admin.check("prova"))
# il codice vero non sta in nessun file pubblico: la prova usa un codice finto con la sua impronta
admin._HASH = hashlib.sha256((admin._SALT + "prova").encode()).hexdigest()
check("codice amministratore: giusto (anche maiuscolo e con spazi), sbagliato no", admin.check("Prova")
      and admin.check(" prova ") and not admin.check("Prova2") and not admin.check(""))

from freelasercut.ui.main_window import MainWindow

w = MainWindow()
check("senza codice: il Rilievo 3D è nascosto e non si apre", not w.acts["relief"].isVisible() and w.relief_dialog() is None)
check("codice sbagliato: resta nascosto", w.admin_dialog(code="bob") is False and not w.acts["relief"].isVisible())
pal = getattr(getattr(w, "banco", None), "palette", None)
if pal is not None:
    check("Banco: senza codice la ricerca dei comandi non trova il Rilievo 3D",
          w.acts["relief"] not in (pal.collect(), [a for a, _p in pal.entries])[1])
check("codice giusto: compare in Strumenti", w.admin_dialog(code="Prova") is True and w.acts["relief"].isVisible())
if pal is not None:
    check("Banco: con il codice la ricerca lo trova", w.acts["relief"] in (pal.collect(), [a for a, _p in pal.entries])[1])
dlg = w.relief_dialog()
check("la finestra si apre", dlg is not None)
img = os.path.join(tempfile.mkdtemp(), "cupola.png")
from PIL import Image

r_ = np.hypot(*np.mgrid[-50:50, -50:50]) / 50.0
Image.fromarray((np.clip(1 - r_ ** 2, 0, 1) * 255).astype(np.uint8)).save(img)
dlg.open_file(img)
dlg.width.setValue(30)
dlg.depth.setValue(2.0)
dlg.thick.setValue(10)
dlg.interval.setValue(0.2)
app.processEvents()
check("senza test il rilievo non si avvia", not dlg.b_start.isEnabled() and not dlg.ready())
dlg.action.disconnect()  # niente anteprime del programma durante la prova
sent = []
dlg.action.connect(lambda kind, job: sent.append((kind, job)))
dlg._emit_job("start")
check("…neanche forzando il pulsante", not any(k == "start" for k, _j in sent))
dlg._emit_test("preview")
steps = dlg.test_n
check("test generato con le passate del lavoro", steps and steps[0] == 1 and steps[-1] == dlg.total_passes(), steps)
truth = R.DepthModel(0.09, 0.92)  # il «legno vero»: rende meno del previsto
dlg.d1.setValue(round(float(truth.depth(1)), 2))
dlg.dn.setValue(round(float(truth.depth(steps[-1])), 2))
ok1 = dlg.check_test()
check("ultimo gradino troppo poco profondo: non accettato, chiede di rifare il test con più passate",
      ok1 is False and not dlg.ready() and "rifai il test" in dlg.lbl_res.text(), dlg.lbl_res.text())
dlg._emit_test("preview")
steps2 = dlg.test_n
dlg.d1.setValue(round(float(truth.depth(1)), 2))
dlg.dn.setValue(round(float(truth.depth(steps2[-1])), 2))
ok2 = dlg.check_test()
check("secondo test con le passate corrette: accettato entro il 10%", ok2 and dlg.ready() and steps2[-1] > steps[-1],
      (steps, steps2, dlg.lbl_res.text()))
check("…e ora si può avviare", dlg.b_start.isEnabled())
dlg.power.setValue(dlg.power.value() - 5)
app.processEvents()
check("cambiando la potenza la taratura non vale più: test da rifare", not dlg.ready() and not dlg.b_start.isEnabled())
dlg.power.setValue(dlg.power.value() + 5)
app.processEvents()
check("tornando ai parametri del test: niente di automatico, il test va rifatto (sessione)", not dlg.ready())
ASK["answer"] = QMessageBox.No
dlg.skip.setChecked(True)
check("«Salta il test»: con «No» all'avviso resta da tarare", not dlg.skip.isChecked() and not dlg.ready())
ASK["answer"] = QMessageBox.Yes
dlg.skip.setChecked(True)
app.processEvents()
check("…con «Sì» si può avviare, segnato NON TARATO o con la taratura salvata", dlg.ready() and dlg.b_start.isEnabled())
dlg.depth.setValue(4.9)
dlg.thick.setValue(6)
app.processEvents()
check("profondità oltre lo spessore − 2 mm: rifiutata, niente avvio", not dlg.b_start.isEnabled() and "4.00" in
      dlg.summary.text(), dlg.summary.text())
dlg.close()


# ================================================================ Disponi → Distanza esatta (stessa versione)
import itertools
import random

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform
from freelasercut.core import ops
from freelasercut.core.document import GroupShape, RectShape, TextShape
from freelasercut.ui.dialogs_distance import make_distance_dialog

# funzioni pure: per ogni combinazione, spostare e poi misurare restituisce esattamente d
random.seed(7)
worst = 0.0
for _ in range(40):
    F = QRectF(random.uniform(-50, 50), random.uniform(-50, 50), random.uniform(1, 40), random.uniform(1, 40))
    M = QRectF(random.uniform(-50, 50), random.uniform(-50, 50), random.uniform(1, 40), random.uniform(1, 40))
    for axis, mode, side, ef, em in itertools.product("xy", ("gap", "center", "edges"), (1, -1),
                                                      ("min", "center", "max"), ("min", "center", "max")):
        d = random.uniform(0, 30)
        dx, dy = ops.distance_shift(F, M, axis, mode, side, d, ef, em)
        M2 = M.translated(dx, dy)
        worst = max(worst, abs(ops.measure_distance(F, M2, axis, mode, side, ef, em) - d),
                    abs(dy) if axis == "x" else abs(dx), abs(M2.width() - M.width()) + abs(M2.height() - M.height()))
check("calcolo: per tutti gli assi, modi, lati e bordi la distanza ottenuta è quella scritta, solo lungo l'asse",
      worst < 1e-9, worst)
A0, B0 = QRectF(50, 50, 40, 20), QRectF(120, 80, 30, 10)
check("lato: a destra +1, a sinistra −1, centri pari +1", ops.gap_side(A0, B0, "x") == 1
      and ops.gap_side(B0, A0, "x") == -1 and ops.gap_side(A0, QRectF(60, 0, 20, 5), "x") == 1)
check("spazio vuoto a destra: bordo sinistro dell'altro = bordo destro del fermo + d",
      ops.distance_shift(A0, B0, "x", "gap", 1, 10) == (-20.0, 0.0))


def mk(shape, x, y):
    b = shape.bounds()
    shape.apply(QTransform.fromTranslate(x - b.left(), y - b.top()))
    return shape


ed = w.editor
msgs = []
ed.message.connect(lambda t: msgs.append(t))
A, B = mk(RectShape(40, 20), 50, 50), mk(RectShape(30, 10), 120, 80)
ed.add([A, B])
ed.select([A])
w._update_sel_actions()
one_ok = not w.acts["distance"].isEnabled()
ed.select([A, B])
w._update_sel_actions()
check("comando attivo solo con due oggetti selezionati", one_ok and w.acts["distance"].isEnabled())
a0, b0 = A.bounds(), B.bounds()
before, n_hist = ed.doc.snapshot(), len(ed.undo_stack)
dlg = make_distance_dialog(w)
check("resta fermo il primo selezionato, si sposta l'ultimo", dlg.roles() == (0, 1) and dlg.pair == [A, B])
check("valore iniziale = spazio attuale (30 mm)", abs(dlg.dist.value() - 30) < 1e-9 and "30.00" in dlg.lbl_now.text(),
      (dlg.dist.value(), dlg.lbl_now.text()))
dlg.dist.setValue(10)
check("anteprima: spazio 10 mm a destra, stessa Y e stesse misure, il fermo non si muove",
      abs(B.bounds().left() - (a0.right() + 10)) < 1e-9 and abs(B.bounds().top() - b0.top()) < 1e-9
      and abs(B.bounds().width() - b0.width()) < 1e-9 and A.bounds() == a0, B.bounds())
dlg.flip.setChecked(True)
check("«Dall'altra parte»: a 10 mm a sinistra del fermo", abs(B.bounds().right() - (a0.left() - 10)) < 1e-9)
dlg.flip.setChecked(False)
dlg.axis.setCurrentIndex(dlg.axis.findData("y"))
check("cambio di direzione: X torna com'era, in verticale 10 mm sopra (resta il valore scritto)",
      abs(B.bounds().left() - b0.left()) < 1e-9 and abs(B.bounds().top() - (a0.bottom() + 10)) < 1e-9
      and dlg.dist.value() == 10, B.bounds())
dlg.mode.setCurrentIndex(dlg.mode.findData("center"))
check("fra i centri: centro a 10 mm sopra quello del fermo", abs(B.bounds().center().y() - (a0.center().y() + 10)) < 1e-9)
dlg.mode.setCurrentIndex(dlg.mode.findData("edges"))
dlg.ef.setCurrentIndex(dlg.ef.findData("min"))
dlg.em.setCurrentIndex(dlg.em.findData("min"))
dlg.dist.setValue(0)
check("bordi scelti in basso-in basso a 0 mm = allineati in basso", abs(B.bounds().top() - a0.top()) < 1e-9
      and not dlg.ef.isHidden())
for _i in range(3):  # avanti e indietro: il lato non «salta» con le posizioni dell'anteprima
    dlg.dist.setValue(4)
    dlg.dist.setValue(0)
check("il lato resta quello dell'apertura durante l'anteprima", abs(B.bounds().top() - a0.top()) < 1e-9 and dlg.side() == 1)
dlg.fixed.setCurrentIndex(1)
check("scambio: ora si sposta il primo e il secondo torna com'era", B.bounds() == b0 and A.bounds() != a0
      and abs(A.bounds().top() - b0.top()) < 1e-9, (A.bounds(), B.bounds()))
dlg.reject()
check("Annulla: documento identico e nessun passo nella cronologia", ed.doc.snapshot() == before
      and len(ed.undo_stack) == n_hist and ed.selection[0].bounds() == a0 and ed.selection[1].bounds() == b0)
A, B = ed.selection[0], ed.selection[1]  # dopo l'annulla le forme sono ricostruite dall'istantanea
dlg = make_distance_dialog(w)
dlg.dist.setValue(5)
dlg.accept()
gap = B.bounds().left() - A.bounds().right()
check("OK: spazio esatto 5 mm e un solo passo «Distanza esatta»", abs(gap - 5) < 1e-6 and len(ed.undo_stack) == n_hist + 1
      and ed.undo_stack[-1][0] == "Distanza esatta", (gap, len(ed.undo_stack) - n_hist))
ed.undo()
A, B = ed.doc.shapes[-2], ed.doc.shapes[-1]
und = abs(B.bounds().left() - b0.left()) < 1e-9
ed.redo()
A, B = ed.doc.shapes[-2], ed.doc.shapes[-1]
check("Annulla e Ripeti dalla cronologia", und and abs(B.bounds().left() - A.bounds().right() - 5) < 1e-6)

# oggetto a sinistra, sovrapposti, fuori dall'area
C = mk(RectShape(10, 10), 5, 52)
ed.add([C])
ed.select([A, C])
dlg = make_distance_dialog(w)
dlg.dist.setValue(3)
check("oggetto a sinistra: resta a sinistra (bordo destro 3 mm prima del fermo)",
      dlg.side() == -1 and abs(C.bounds().right() - (A.bounds().left() - 3)) < 1e-9)
dlg.reject()
C = ed.doc.shapes[-1]
D = mk(RectShape(10, 10), 80, 55)
ed.add([D])
ed.select([A, D])
dlg = make_distance_dialog(w)
check("sovrapposti: lo dice e la distanza parte da 0", dlg.dist.value() == 0 and "sovrappongono" in dlg.lbl_now.text(),
      dlg.lbl_now.text())
dlg.dist.setValue(4000)
out_on = not dlg.lbl_warn.isHidden()
dlg.dist.setValue(2)
check("avviso fuori dall'area di lavoro: compare e sparisce", out_on and dlg.lbl_warn.isHidden())
dlg.reject()

# bloccati e selezioni sbagliate
A, D = ed.doc.shapes[-4], ed.doc.shapes[-1]
A.locked = True
ed.select([D, A])
dlg = make_distance_dialog(w)
check("uno bloccato: resta fermo lui, anche se selezionato per ultimo", dlg.roles() == (1, 0) and not dlg.fixed.isEnabled())
dlg.reject()
A, D = ed.doc.shapes[-4], ed.doc.shapes[-1]
D.locked = True
A.locked = True
ed.select([A, D])
msgs.clear()
check("tutti e due bloccati: rifiutato con il motivo", make_distance_dialog(w) is None and msgs and "bloccati" in msgs[-1])
A.locked = D.locked = False
ed.select([A])
msgs.clear()
r1 = make_distance_dialog(w)
ed.select(list(ed.doc.shapes[-3:]))
check("uno o tre oggetti: rifiutato con il motivo", r1 is None and make_distance_dialog(w) is None and len(msgs) == 2)

# forme difficili: ruotata, gruppo, testo (ingombro dritto come in «Allinea»)
R_ = mk(RectShape(30, 8), 20, 120)
c_ = R_.bounds().center()
R_.apply(QTransform().translate(c_.x(), c_.y()).rotate(30).translate(-c_.x(), -c_.y()))
G_ = GroupShape([mk(RectShape(8, 8), 100, 120), mk(RectShape(5, 12), 112, 125)])
T_ = mk(TextShape("Ag", size=12), 150, 160)
ed.add([R_, G_, T_])
res = []
for fx, mv, axis in ((R_, G_, "x"), (G_, T_, "y"), (T_, R_, "x")):
    ed.select([fx, mv])
    dlg = make_distance_dialog(w)
    dlg.axis.setCurrentIndex(dlg.axis.findData(axis))
    dlg.dist.setValue(7.5)
    sd = dlg.side()
    dlg.accept()
    fx, mv = ed.selection[0], ed.selection[1]
    res.append(ops.measure_distance(fx.bounds(), mv.bounds(), axis, "gap", sd))
check("ruotata, gruppo e testo: spazio misurato esatto 7,5 mm", all(abs(x - 7.5) < 1e-6 for x in res), res)
if pal is not None:
    pal.collect()
    check("Banco: «Distanza esatta» nella ricerca dei comandi e nel menu Allinea", w.acts["distance"] in
          [a for a, _p in pal.entries])


# ================================================================ Forbici: taglia le eccedenze (stessa versione)
import time as _time

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath
from freelasercut.core import nodes, trim
from freelasercut.core.document import EllipseShape, ImageShape, PathShape

cv = w.canvas
tool = cv.tools["trim"]
cv.set_tool("trim")
check("strumento Forbici: tasto X, attivo sul piano", w.tool_actions["trim"].shortcut().toString() == "X"
      and cv.tool is tool)


def pline(*pts, closed=False):
    pp = QPainterPath()
    pp.moveTo(*pts[0])
    for q in pts[1:]:
        pp.lineTo(*q)
    if closed:
        pp.closeSubpath()
    return PathShape(pp)


def fresh(*shapes):
    ed.doc.shapes.clear()
    ed.selection = []
    ed.add(list(shapes))
    ed.select([])
    return [x.id for x in shapes]


def by_id(i):
    return next((x for x in ed.doc.shapes if x.id == i), None)


class _Ev:
    def __init__(self, shift=False):
        self.shift = shift

    def button(self):
        return Qt.LeftButton

    def buttons(self):
        return Qt.NoButton

    def modifiers(self):
        return Qt.ShiftModifier if self.shift else Qt.NoModifier


def cut(x, y, shift=False):
    tool.press(_Ev(shift), QPointF(x, y))


def dist_to(shape, pt):
    best = 1e9
    for sp in nodes.from_path(shape.path()):
        for i, j in sp.segments():
            best = min(best, nodes.nearest_on_segment(sp, i, j, pt)[1])
    return best


def ends(shape):
    return [(sp.nodes[0].pt(), sp.nodes[-1].pt()) for sp in nodes.from_path(shape.path()) if not sp.closed]


def all_on(new, old, n=60):
    pp = new.path()
    return max(dist_to(old, (pp.pointAtPercent(k / n).x(), pp.pointAtPercent(k / n).y())) for k in range(n + 1))


# 1. croce
ih, iv = fresh(pline((0, 50), (100, 50)), pline((30, 0), (30, 100)))
cut(10, 50)
cut(30, 10)
L_ = by_id(iv)  # 0.17.17: i due pezzi rimasti si toccano nell'incrocio = una forma sola (a L)
lsub = nodes.from_path(L_.path()) if L_ else []
check("croce: i due bracci tolti fino all'incrocio, i pezzi rimasti agganciati in una forma sola a L",
      by_id(ih) is None and L_ is not None and len(lsub) == 1 and abs(L_.path().length() - 120) < 1e-6
      and sorted([lsub[0].nodes[0].pt(), lsub[0].nodes[-1].pt()]) == [(30.0, 100.0), (100.0, 50.0)]
      and dist_to(L_, (30, 50)) < 1e-9, (len(lsub), L_.path().length() if L_ else None))
# 2. rettangolo attraversato da una linea
ir, il_ = fresh(mk(RectShape(50, 30), 0, 0), pline((-10, 15), (60, 15)))
cut(55, 15)
check("eccedenza della linea: finisce sul lato del rettangolo", abs(by_id(il_).path().length() - 60) < 1e-6)
cut(25, 30)
r_ = by_id(ir)
# 0.17.17: la U tocca con un estremo la linea già accorciata (in 50; 15) → un pezzo solo: U da 80 mm + linea da 60 mm
check("lato del rettangolo fra i due incroci (passando dagli angoli): resta la U aperta da 80 mm, agganciata alla linea",
      isinstance(r_, PathShape) and abs(r_.path().length() - 140) < 1e-6 and by_id(il_) is None
      and len(nodes.from_path(r_.path())) == 1 and dist_to(r_, (25, 30)) > 1, r_.path().length())
ir, = fresh(mk(RectShape(50, 30), 0, 0))[:1]
ed.add([pline((-10, 15), (60, 15))])
cut(25, 30, shift=True)
check("con Maiusc ci si ferma agli angoli: tolto solo il lato in alto (50 mm)", abs(by_id(ir).path().length() - 110) < 1e-6,
      by_id(ir).path().length())
# 3. due cerchi
i1, i2 = fresh(mk(EllipseShape(40, 40), 0, 0), mk(EllipseShape(40, 40), 25, 0))
c2 = by_id(i2)
cut(40, 20)
c1 = by_id(i1)
e1 = ends(c1)[0]
check("due cerchi: arco dentro l'altro tolto, estremi esattamente sull'altro cerchio",
      len(ends(c1)) == 1 and max(dist_to(c2, e1[0]), dist_to(c2, e1[1])) < 1e-6 and dist_to(c1, (40, 20)) > 1
      and abs(e1[0][0] - 32.5) < 1e-9, (e1, dist_to(c2, e1[0])))
# 4. nessun incrocio
i1, i2 = fresh(mk(EllipseShape(20, 20), 0, 0), pline((100, 0), (150, 0)))
cut(20, 10)
cut(120, 0)
check("nessun incrocio: cerchio e linea isolati si tolgono interi", by_id(i1) is None and by_id(i2) is None)
# 5. contatto a T
ir, _a, _b = fresh(mk(RectShape(50, 30), 0, 0), pline((20, 30), (20, 60)), pline((40, 30), (40, 60)))
cut(30, 30)
# 0.17.17: il rettangolo aperto resta agganciato alle due linee che lo toccavano (140 + 30 + 30 mm, una forma sola)
check("contatto a T: il lato si divide nei punti toccati (tolti 20 mm) e le due linee restano agganciate",
      abs(by_id(ir).path().length() - 200) < 1e-6 and len(ed.doc.shapes) == 1, by_id(ir).path().length())
# 6. auto-intersezione
iz, = fresh(pline((0, 0), (20, 20), (20, 0), (0, 20)))
L0 = by_id(iz).path().length()
cut(2, 2)
check("linea che si incrocia da sola: tolto il pezzo fino al proprio incrocio",
      abs(by_id(iz).path().length() - (L0 - math.hypot(10, 10))) < 1e-6, (L0, by_id(iz).path().length()))
# 7. lati in comune e doppioni
ia, ib = fresh(mk(RectShape(20, 20), 0, 0), mk(RectShape(20, 20), 10, 20))
cut(15, 20)
Ls = sorted(round(by_id(i).path().length(), 6) for i in (ia, ib))
check("lato in comune: tolta solo la parte comune (10 mm), sulla forma in primo piano come il clic di selezione",
      Ls == [70.0, 80.0] and abs(by_id(ib).path().length() - 70) < 1e-6, Ls)
id1, id2 = fresh(mk(EllipseShape(20, 20), 0, 0), mk(EllipseShape(20, 20), 0, 0))
cut(20, 10)
check("doppione identico: uno dei due sparisce intero, l'altro resta", (by_id(id1) is None) != (by_id(id2) is None))
id1, id2, id3 = fresh(mk(RectShape(20, 20), 0, 0), mk(RectShape(20, 20), 0, 0), pline((-5, 10), (25, 10)))
t_ = trim.Trimmer(ed.doc, by_id(id1))
check("doppione attraversato da una linea: gli incroci con la linea contano ancora", len(t_.cuts[0]) == 2, t_.cuts)
# 8. più sottotracciati
pp = QPainterPath()
pp.addRect(0, 0, 40, 40)
pp.addRect(10, 10, 20, 20)
iq, _l = fresh(PathShape(pp), pline((-5, 20), (45, 20)))
inner_before = [n.pt() for n in nodes.from_path(by_id(iq).path())[1].nodes]
cut(20, 0)
subs_after = nodes.from_path(by_id(iq).path())
inner_after = [sp for sp in subs_after if sp.closed]
check("più sottotracciati: cambia solo quello cliccato, l'anello interno resta uguale",
      len(inner_after) == 1 and [n.pt() for n in inner_after[0].nodes] == inner_before
      and abs(sum(QPainterPath(nodes.to_path([sp])).length() for sp in subs_after if not sp.closed) - 80) < 1e-6)
# 9. forme ruotate e testo
rr = mk(RectShape(40, 10), 0, 0)
cc = rr.bounds().center()
rr.apply(QTransform().translate(cc.x(), cc.y()).rotate(30).translate(-cc.x(), -cc.y()))
irr, _l = fresh(rr, pline((-20, 5), (60, 5)))
t_ = trim.Trimmer(ed.doc, by_id(irr))
pts_ = [t_._point(0, u) for u in t_.cuts[0]]
check("rettangolo ruotato: incroci esattamente sulla linea", len(pts_) == 2 and all(abs(q[1] - 5) < 1e-9 for q in pts_), pts_)
it, il2 = fresh(mk(TextShape("I", size=20), 0, 0), pline((-5, 5), (30, 5)))
tb = by_id(it).bounds()
yl = tb.center().y()
ed.doc.shapes[-1] = pline((tb.left() - 5, yl), (tb.right() + 5, yl))
ed.doc.shapes[-1].id = il2
t_ = trim.Trimmer(ed.doc, by_id(il2))
check("testo come forma che taglia: la linea è tagliata dai bordi della lettera", len(t_.cuts[0]) >= 2, t_.cuts)
cut(tb.left() - 3, yl)
check("…e la linea si accorcia fino alla lettera", abs(by_id(il2).path().length() - (tb.width() + 10 - 5)) < 0.05)
# 10. esclusi
ih, iv = fresh(pline((0, 50), (100, 50)), pline((30, 0), (30, 100)))
by_id(iv).hidden = True
check("forma nascosta: non taglia", trim.Trimmer(ed.doc, by_id(ih)).cuts == [[]])
by_id(iv).hidden = False
lay_v = by_id(iv).layer
ed.doc.layers[lay_v].show = False
check("livello spento: non taglia", trim.Trimmer(ed.doc, by_id(ih)).cuts == [[]])
ed.doc.layers[lay_v].show = True
by_id(ih).locked = True
msgs.clear()
cut(10, 50)
check("forma bloccata: non si taglia", abs(by_id(ih).path().length() - 100) < 1e-9)
by_id(ih).locked = False
g_ = GroupShape([pline((0, 80), (50, 80)), pline((10, 70), (10, 90))])
ig, = fresh(g_)
before_g = ed.doc.snapshot()
st = []
cv.status.connect(lambda t: st.append(t))
cut(40, 80)
check("gruppo: non si taglia e lo dice (separalo prima)", ed.doc.snapshot() == before_g and st and "gruppo" in st[-1].lower(),
      st[-1:])
ii, = fresh(ImageShape(None, 50, 50))
check("immagine: non è un bersaglio né una forma che taglia", trim.target_ok(ed.doc, by_id(ii)) == "image"
      and trim.cutter_subs(ed.doc, by_id(ii).bounds()) == [])
# 11. cronologia
ih, iv = fresh(pline((0, 50), (100, 50)), pline((30, 0), (30, 100)))
n0 = len(ed.undo_stack)
cut(10, 50)
one = len(ed.undo_stack) == n0 + 1 and ed.undo_stack[-1][0] == "Taglia eccedenza"
ed.undo()
und = abs(by_id(ih).path().length() - 100) < 1e-9
ed.redo()
check("un passo per clic, Annulla e Ripeti", one and und and abs(by_id(ih).path().length() - 70) < 1e-6)
# 12. tempi: linea vicino a un testo lungo
words = mk(TextShape("FreeLaserCut taglia le eccedenze", size=12), 0, 0)
wb = words.bounds()
il3, _w = fresh(pline((wb.left() - 5, wb.center().y()), (wb.right() + 5, wb.center().y())), words)
t0_ = _time.perf_counter()
tool._cache = {}
tool.trimmer(by_id(il3))
t1_ = _time.perf_counter()
tool.trimmer(by_id(il3))
t2_ = _time.perf_counter()
check("tempi: incroci con un testo di 32 lettere sotto il secondo, poi dalla memoria",
      t1_ - t0_ < 1.0 and t2_ - t1_ < 0.01, (round(t1_ - t0_, 3), round(t2_ - t1_, 5)))
cv.set_tool("select")

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
