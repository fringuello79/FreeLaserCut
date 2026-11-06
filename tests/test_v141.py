# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.14.1: anteprima 3D della Scultura con la scheda grafica (OpenGL di Qt), con l'anteprima fatta in casa
come riserva automatica.

La parte con la scheda grafica gira in un processo a parte con una finestra vera (su Linux dentro xvfb-run, se c'è;
su Windows con lo schermo normale). Se OpenGL non c'è, quelle prove vengono saltate e lo si scrive."""
import os
import shutil
import subprocess
import sys
import tempfile
import time

CHILD = os.environ.get("FLC_GL_CHILD") == "1"
if not CHILD:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
if not CHILD:  # impostazioni in un file a parte (su Windows altrimenti finirebbero nel registro vero)
    os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PySide6.QtWidgets import QApplication

app = QApplication([])
from freelasercut.core import render3d as R, sculpt as S
from PySide6.QtCore import QSettings


def settings():
    return QSettings(os.environ["FLC_SETTINGS_INI"], QSettings.IniFormat)

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info)


def arr(img):
    """QImage -> array (H, W, 3) uint8."""
    from PySide6.QtGui import QImage

    img = img.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    b = np.frombuffer(img.constBits(), np.uint8, count=img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    return b[:, :w * 3].reshape(h, w, 3).copy()


def wood_mask(a):
    """Legno e bordi bruciati (colori caldi e saturi); pavimento, ombra e sfondo sono grigi."""
    a = a.astype(np.float32)
    mx, mn = a.max(2), a.min(2)
    return ((mx - mn) / np.maximum(mx, 1.0) > 0.14) & (a[..., 0] > a[..., 2] + 6)


heart = S.prepared(S.builtin("heart"), "z", 120.0)
LH = S.layered(heart, 3.0)
sphere = S.prepared(S.builtin("sphere"), "z", 120.0)
IS = S.interlocking(sphere, 3.0, *S.auto_counts(sphere, 3.0))
torus = S.prepared(S.builtin("torus"), "z", 40.0)
LT = S.layered(torus, 3.0)
_st = S._star2d() * 40.0
star = S.prepared(S.Mesh(*S._loft([np.c_[_st, np.full(len(_st), z)] for z in (0.0, 12.0)])), "z", 12.0)  # stella in piedi
LS = S.layered(star, 3.0)


def gl_child():
    """Prove con la scheda grafica (processo con una finestra vera)."""
    from freelasercut.ui import viewer_gl as G
    from freelasercut.ui import dialogs_sculpt as DS

    ok, name = G.probe()
    if not ok:
        print("  SALTATO  scheda grafica non disponibile:", name)
        return 0
    check("la scheda grafica risponde e ha un nome", ok and name, name)
    v = G.GLViewer()
    v.resize(640, 480)
    v.move(30, 30)
    v.show()
    app.processEvents()
    v.set_data(heart, LH)
    t = time.time()
    a = arr(v.render_image(640, 480))
    dt = time.time() - t
    check("cuore a strati disegnato dalla scheda grafica", a.shape == (480, 640, 3) and wood_mask(a).mean() > 0.08,
          (round(float(wood_mask(a).mean()), 3), round(dt, 2)))
    b = arr(v.render_image(640, 480))
    check("stessa vista, stessa immagine", np.abs(a.astype(int) - b).mean() < 1.0)
    # Qt ricrea il contesto se l'anteprima passa in un'altra finestra: tutto si ricarica da solo
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    box = QWidget()
    QVBoxLayout(box).addWidget(v)
    box.resize(660, 500)
    box.show()
    for _ in range(5):
        app.processEvents()
    c2 = arr(v.render_image(640, 480))
    check("spostata in un'altra finestra (contesto nuovo): si ridisegna uguale", np.abs(c2.astype(int) - a).mean() < 2.0,
          round(float(np.abs(c2.astype(int) - a).mean()), 2))
    sw = R.render(R.sculpture_scene(LH), R.fit_camera(R.sculpture_scene(LH)), 640, 480, ss=1)
    ma, ms = wood_mask(a), wood_mask(sw)
    iou = (ma & ms).sum() / max((ma | ms).sum(), 1)
    check("stessa inquadratura dell'anteprima fatta in casa (la scultura occupa gli stessi punti)", iou > 0.85,
          round(float(iou), 3))
    times = []
    for k in range(8):
        v.yaw += 15
        t = time.time()
        c = arr(v.render_image(640, 480))
        times.append(time.time() - t)
    check("girando la vista l'immagine cambia", np.abs(c.astype(int) - a).mean() > 3)
    check("girare è veloce (anche con la scheda grafica emulata dal processore)", np.median(times) < 0.6,
          f"{np.median(times) * 1000:.0f} ms a vista")
    # ombra sul pavimento: punti grigi più scuri del pavimento
    v.yaw = -35.0
    a = arr(v.render_image(640, 480))
    g = a.astype(np.float32)
    grey = (g.max(2) - g.min(2) < 12)
    check("pavimento con l'ombra morbida della scultura", (grey & (g.mean(2) < 175) & (g.mean(2) > 60)).sum() > 2000,
          int((grey & (g.mean(2) < 175)).sum()))
    # facce con i fori (stencil pari-dispari): ciambella vista dall'alto, il buco resta vuoto
    v.set_data(torus, LT)
    v.yaw, v.pitch = 0.0, 85.0
    a = arr(v.render_image(640, 480))
    m = wood_mask(a)
    ys, xs = np.nonzero(m)
    cy, cx = int(np.median(ys)), int(np.median(xs))
    ring = m[cy - 3:cy + 4, :].any(0)
    check("ciambella dall'alto: legno intorno, il buco in mezzo vuoto", m.mean() > 0.05 and not m[cy - 3:cy + 4, cx - 3:cx + 4].any()
          and ring[:cx].any() and ring[cx:].any(), (round(float(m.mean()), 3), bool(m[cy, cx])))
    # facce concave: stella dall'alto, fra due punte non c'è legno
    v.set_data(star, LS)
    a = arr(v.render_image(640, 480))
    m = wood_mask(a)
    hull = __import__("cv2").convexHull(np.argwhere(m)[:, ::-1].astype(np.int32))
    hm = np.zeros(m.shape, np.uint8)
    __import__("cv2").fillPoly(hm, [hull], 1)
    check("stella dall'alto: le facce concave sono giuste (fra le punte niente legno)",
          m.sum() < 0.8 * hm.sum() and m.sum() > 0.3 * hm.sum(), (int(m.sum()), int(hm.sum())))
    # montaggio
    v.set_data(sphere, IS)
    v.yaw, v.pitch = -35.0, 22.0
    v.set_view("assembly")
    full = wood_mask(arr(v.render_image(480, 360))).sum()
    v.set_step(3)
    part = wood_mask(arr(v.render_image(480, 360))).sum()
    v.set_step(3, 60.0)
    up = arr(v.render_image(480, 360))
    check("montaggio: con meno pezzi si vede meno legno, il pezzo che arriva sta più in alto",
          part < full and wood_mask(up).sum() > part, (int(part), int(full), int(wood_mask(up).sum())))
    v.set_view("model")
    a = arr(v.render_image(480, 360))
    check("vista del modello (grigio, liscio)", (np.abs(a.astype(int) - a.mean(2, keepdims=True)).max(2) < 25).mean() > 0.9
          and (a.mean(2) < 200).mean() > 0.05)
    # modello enorme: copia alleggerita solo per l'anteprima
    import math

    n = 520  # circa 1,1 milioni di triangoli: più del limite dell'anteprima
    th = np.linspace(0, math.pi, n)[1:-1]
    ph = np.linspace(0, 2 * math.pi, 2 * n, endpoint=False)
    TH, PH = np.meshgrid(th, ph, indexing="ij")
    V = np.c_[(np.sin(TH) * np.cos(PH)).ravel(), (np.sin(TH) * np.sin(PH)).ravel(), np.cos(TH).ravel()]
    V = np.vstack([V, [0, 0, 1], [0, 0, -1]])
    rows, cols = n - 2, 2 * n
    I_, J_ = np.meshgrid(np.arange(rows - 1), np.arange(cols), indexing="ij")
    idx = lambda i, j: i * cols + (j % cols)  # noqa: E731
    a_, b_, c_, d_ = idx(I_, J_), idx(I_, J_ + 1), idx(I_ + 1, J_), idx(I_ + 1, J_ + 1)
    F = np.vstack([np.c_[a_.ravel(), c_.ravel(), d_.ravel()], np.c_[a_.ravel(), d_.ravel(), b_.ravel()]])
    j = np.arange(cols)
    F = np.vstack([F, np.c_[np.full(cols, len(V) - 2), idx(0, j + 1), idx(0, j)],
                   np.c_[np.full(cols, len(V) - 1), idx(rows - 1, j), idx(rows - 1, j + 1)]])
    big = S.prepared(S.Mesh(V * 50, F), "z", 120.0)
    v.set_data(big, None)
    t = time.time()
    a = arr(v.render_image(480, 360))
    t1 = time.time() - t
    t = time.time()
    v.yaw += 20
    arr(v.render_image(480, 360))
    t2 = time.time() - t
    check(f"modello da {len(F) // 1000} mila triangoli: si carica e si gira", (a.mean(2) < 200).mean() > 0.05 and t2 < 3,
          f"carica {t1:.1f} s, poi {t2 * 1000:.0f} ms a vista")
    v.set_data(None, None)
    v.render_image(64, 48)  # libera i buffer del modello grande
    del big, V, F
    import gc

    gc.collect()
    # finestra
    d = DS.SculptDialog(None, (400.0, 400.0))
    d.move(30, 30)
    d.show()
    t = time.time()
    while not getattr(d.viewer, "_painted_once", False) and time.time() - t < 10:
        app.processEvents()
    check("finestra: anteprima con OpenGL, scritto sotto con il nome", d.viewer.backend == "gpu" and d.gpu.isChecked()
          and name in d.backend_lbl.text(), d.backend_lbl.text())
    check("mentre la finestra è aperta la prova della scheda grafica resta segnata (contro i driver che chiudono)",
          str(settings().value("sculpt/gpu_trial")) == "1")
    d._toggle_play()
    k = 0
    while d._anim.isActive() and k < 2000:
        d._anim_tick()
        k += 1
    check("«Monta» arriva fino all'ultimo pezzo", d.slider.value() == d.slider.maximum(), (d.slider.value(), k))
    d.viewer.yaw = 77.0
    d.gpu.setChecked(False)
    app.processEvents()
    check("togliendo la spunta: anteprima semplice, stessa vista", d.viewer.backend == "software" and d.viewer.yaw == 77.0
          and d.viewer.sculpture is d.sculpture)
    check("la scelta si ricorda", str(settings().value("sculpt/gpu")) == "0")
    for _ in range(3):  # avanti e indietro: i buffer della vecchia anteprima si liberano ogni volta
        d.gpu.setChecked(True)
        app.processEvents()
        d.gpu.setChecked(False)
        app.processEvents()
    d.gpu.setChecked(True)
    for _ in range(10):
        app.processEvents()
    img = arr(d.viewer.render_image(320, 240))
    check("dopo vari cambi l'anteprima con OpenGL disegna ancora", d.viewer.backend == "gpu" and wood_mask(img).mean() > 0.03)
    d._gpu_failed("prova")
    app.processEvents()
    check("se la scheda grafica dà errore: si torna da soli all'anteprima semplice, con il motivo",
          d.viewer.backend == "software" and not d.gpu.isChecked() and "prova" in d.backend_lbl.text())
    d.reject()
    check("chiusa bene: la prova della scheda grafica si chiude", str(settings().value("sculpt/gpu_trial")) == "0")
    return 0 if all(results) else 1


if CHILD:
    rc = gl_child()
    print(f"\n{sum(results)}/{len(results)} verifiche superate")
    sys.exit(rc)

# ================================================================== senza scheda grafica (sempre)
parts = R.sculpture_parts(LH)
check("pezzi pronti da disegnare, in ordine di montaggio, ognuno con le sue due facce", len(parts) == len(LH.pieces)
      and all(len(c) == 2 and len(t) for t, c in parts))
bad = []
for (t, caps), pc in zip(parts, sorted(LH.pieces, key=lambda p: p.order)):
    (r0, n0), (r1, n1) = caps
    if not (n0[2] < 0 < n1[2] and abs(r1[0][0, 2] - r0[0][0, 2] - 3.0) < 1e-9):
        bad.append(pc.name)
check("strati: faccia sotto verso il basso, faccia sopra verso l'alto, a 3 mm l'una dall'altra", not bad, bad[:3])
pi = R.sculpture_parts(IS)
check("sagome: facce verso fuori ai due lati dello spessore",
      all(np.dot(c[0][1], c[1][1]) < 0 and abs(np.linalg.norm(c[0][1]) - 1) < 1e-9 for _t, c in pi))
check("pavimento sotto il pezzo più basso", abs(R.sculpture_ground(LH) - min(p.plane for p in LH.pieces)) < 1e-6)
sc = R.sculpture_scene(LH)
check("anteprima fatta in casa come prima", len(sc.caps) == 2 * len(LH.pieces) and
      R.render(sc, R.fit_camera(sc), 160, 120, ss=1).shape == (120, 160, 3))
big_tris = len(R.mesh_scene(heart, limit=7000).tris[0][0])
check("modello alleggerito al numero di triangoli chiesto", big_tris <= 7000 < len(heart.faces), big_tris)
from freelasercut.ui import dialogs_sculpt as DS
from freelasercut.ui import viewer_gl as G

okp, why = G.probe()
check("qui senza schermo vero: la scheda grafica non si usa e si sa perché", not okp and why, why)
os.environ["FLC_3D"] = "software"
check("FLC_3D=software obbliga l'anteprima semplice", G.probe(force=True) == (False, "FLC_3D=software"))
del os.environ["FLC_3D"]
G.probe(force=True)
d = DS.SculptDialog(None, (400.0, 400.0))
check("finestra senza scheda grafica: anteprima semplice, spunta spenta, scritto il motivo",
      d.viewer.backend == "software" and not d.gpu.isChecked() and "senza scheda grafica" in d.backend_lbl.text()
      and "offscreen" in d.backend_lbl.text(), d.backend_lbl.text())
d.gpu.setChecked(True)
check("rimettendo la spunta dove OpenGL non c'è: resta l'anteprima semplice e lo dice",
      d.viewer.backend == "software" and not d.gpu.isChecked() and "OpenGL non disponibile" in d.backend_lbl.text())
d.reject()
check("chiusa: niente timer rimasti accesi", not d._anim.isActive() and not d._timer.isActive())
qs = settings()
qs.setValue("sculpt/gpu", "1")
qs.setValue("sculpt/gpu_trial", "1")  # come se l'ultima volta il driver avesse chiuso il programma
qs.sync()
d = DS.SculptDialog(None, (400.0, 400.0))
qs = settings()
check("se l'ultima volta la scheda grafica ha chiuso il programma: si riparte senza, e lo si dice",
      str(qs.value("sculpt/gpu")) == "0" and "chiuso il programma" in d.backend_lbl.text()
      and str(qs.value("sculpt/gpu_trial")) == "0", d.backend_lbl.text())
d.reject()
qs.setValue("sculpt/gpu", "1")

# ================================================================== con la scheda grafica (processo a parte)
cmd = [sys.executable, os.path.abspath(__file__)]
env = dict(os.environ, FLC_GL_CHILD="1", PYTHONFAULTHANDLER="1",
           FLC_SETTINGS_INI=os.path.join(tempfile.mkdtemp(), "figlio.ini"))  # impostazioni pulite
run = True
if sys.platform.startswith("linux"):
    if shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1600x1000x24"] + cmd
        env["QT_QPA_PLATFORM"] = "xcb"
    else:
        run = False
        print("  SALTATO  prove con la scheda grafica: manca xvfb-run")
elif sys.platform == "win32":
    env["QT_QPA_PLATFORM"] = "windows"
else:
    env.pop("QT_QPA_PLATFORM", None)
if run:
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        out = r.stdout
    except subprocess.TimeoutExpired:
        out, r = "  KO  prove con la scheda grafica: troppo tempo\n", None
    for line in out.splitlines():
        if line.startswith("  OK  ") or line.startswith("  KO  "):
            results.append(line.startswith("  OK  "))
            print(line)
        elif line.startswith("  SALTATO"):
            print(line)
    said = any(l.startswith(("  OK  ", "  KO  ", "  SALTATO")) for l in out.splitlines())
    if r is not None and r.returncode != 0 and not said:
        # la finestra vera non si è nemmeno aperta (server senza grafica, librerie mancanti): non è un errore di
        # FreeLaserCut, le prove con la scheda grafica qui non si possono fare
        print("  SALTATO  prove con la scheda grafica: la finestra non si apre in questo ambiente (codice "
              f"{r.returncode}) {(r.stderr or '').strip()[-300:]}")
    elif r is not None and r.returncode != 0 and all(results):
        check("il processo con la scheda grafica finisce bene", False, (r.returncode, r.stderr[-1500:]))

print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
