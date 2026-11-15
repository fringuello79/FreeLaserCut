# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.2: calibrazione completa della camera della testa (freeburn/mosaico-preciso.md e mosaico-revisione.md),
foto a mosaico precisa e richieste di Leone (vista raddrizzata, zoom, crocetta dal centro camera, foto tolta dal piano).

Matrice dei casi:
A. senza macchina (conti):
 1 modello: pixel → piano → pixel con lente a due coefficienti, centro spostato, inclinazione, specchio; file nuovo
   (con anche i campi della 0.20.0), file della 0.20.0, valori rovinati; spessore (formula = raggio vero, limiti,
   conta solo per le camere fisse al carrello);
 2 punto sotto la camera dalla prospettiva (anche specchiata);
 3 griglia: righe sfalsate, tre puntini grandi, un punto su cinque di controllo, foro al centro, G-code (sempre dalla
   stessa parte, mai sopra la potenza, laser spento alla fine), misure scelte per la camera, camera troppo grossolana;
 4 riconoscimento: centro al decimo di pixel con luce non uniforme e rumore; macchie, venature e bruciature storte
   scartate; puntini più chiari del fondo; abbinamento senza scambi;
 5 calcolo: ritrova la camera vera; con una camera semplice sceglie il modello semplice;
 6 fotogrammi rovinati, luce sul materiale, luce scarsa / troppa, pezzi della macchina nell'inquadratura;
 7 mosaico: posto giusto, giunte nette (niente linee doppie), aggiustamento solo dove c'è un riconoscimento unico,
   zone non fotografate a tratteggio, zone coperte escluse;
 8 vista: raddrizzata per tutti gli 8 modi di montare la camera; clic, zoom e spostamento con la stessa trasformazione.
B. calibrazione sul simulatore: camera inclinata con lente forte, capovolta e specchiata; pezzi della macchina
   davanti, fotogrammi rovinati, venatura, macchie e luce non uniforme; camera fissa al carrello (seconda altezza);
   «non so» con la camera che sale con il laser; messa a fuoco automatica che cambia l'inquadratura; passi persi;
   buio; cartone troppo piccolo; annulla durante la griglia; calibrazione vecchia migliore. Camera del piano aiutata
   (parte 2): correzione ritrovata, foto corretta uguale al vero, materiale non piano e liscio rifiutati.
C. interfaccia: calibrazione dal pulsante, stato, spessore solo per le camere fisse, «Controlla», camera urtata,
   Stampa e taglia dal centro camera, foto tolta dal piano (pulsante e menu), vista raddrizzata e zoom. Banco: C.
"""
import json
import math
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
BANCO = os.environ["FLC_UI"] == "banco"
PARTI = os.environ.get("FLC_PROVA_PARTI", "ABC")  # per i guasti messi apposta: solo alcune parti (A conti, B, C)
CASI = [c_ for c_ in os.environ.get("FLC_PROVA_CASI", "").split(",") if c_]  # e solo alcuni casi della parte B


def caso(name):
    return not CASI or name in CASI
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import head_camera as hc, head_grid as hg  # noqa: E402
from freelasercut.grbl import SIM_PORT, GrblController  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    extra = "" if cond or info is None or (isinstance(info, str) and not info) else f"  [{info}]"
    print(("OK  " if cond else "KO  ") + name + extra, flush=True)


def spin(t):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.01)


def until(fn, t=60.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.02)
    return fn()


rng = np.random.default_rng(11)
SIZE = (640, 480)
Z = np.zeros(2)


def true_err(m, truth, size=SIZE, n=600):
    px = rng.uniform([0, 0], size, (n, 2))
    e = np.hypot(*(m.img_to_bed(Z, px) - truth.img_to_bed(Z, px)).T)
    return float(np.nanmax(e))


if not BANCO and "A" in PARTI:
    # ================================================================== A1. modello
    t1 = hg.camera_model((1280, 720), 0.079, angle=8, offset=(5, 35), tilt=4, tilt_dir=30, k1=-0.18, k2=0.05,
                         q=(0.02, -0.015), height=60)
    px = rng.uniform([0, 0], (1280, 720), (300, 2))
    back = t1.bed_to_img(Z, t1.img_to_bed(Z, px))
    check("modello completo: pixel → piano → pixel con lente a due coefficienti, centro spostato e inclinazione",
          float(np.nanmax(np.abs(back - px))) < 1e-6)
    for ang in (0, 90, 180, 270):
        for mir in (False, True):
            mm_ = hg.camera_model(SIZE, 0.1, angle=ang, mirror=mir, offset=(0, 30), tilt=2, k1=-0.1)
            ok_ = abs((mm_.angle_deg() - ang + 180) % 360 - 180) < 1.0 and mm_.mirrored() == mir
            if not ok_:
                break
    check("…rotazione e specchio letti giusti anche con l'inclinazione (0/90/180/270°, specchiata o no)", ok_,
          (ang, mir, mm_.angle_deg(), mm_.mirrored()))
    d = tempfile.mkdtemp()
    path = os.path.join(d, "hc.json")
    t1.quality = {"max_mm": 0.03, "p95_px": 0.3}
    t1.occluded = [(0, 600, 200, 720)]
    t1.backlash = (0.12, -0.05)
    t1.camera_mode = "dshow-mjpg"
    t1.save(path)
    t2 = hc.HeadModel.load(path)
    check("file della calibrazione completa: salvato e riletto uguale (lente, inclinazione, qualità, zone coperte, "
          "gioco, modo di lettura)", t2 is not None and t2.method == "grid"
          and float(np.nanmax(np.abs(t2.img_to_bed(Z, px) - t1.img_to_bed(Z, px)))) < 1e-9
          and t2.quality["max_mm"] == 0.03 and t2.occluded == [(0.0, 600.0, 200.0, 720.0)]
          and t2.backlash == (0.12, -0.05) and t2.camera_mode == "dshow-mjpg")
    raw = json.load(open(path))
    check("…il file ha anche i campi della 0.20.0 (M, scostamento, k): una versione vecchia lo legge",
          all(k in raw for k in ("M", "offset", "k", "frame_size")) and raw["version"] == 2)
    old_d = {k: raw[k] for k in ("M", "offset", "frame_size", "k", "created")}
    old_d["version"] = 1
    json.dump(old_d, open(path, "w"))
    t3 = hc.HeadModel.load(path)
    check("file della 0.20.0: letto come calibrazione col puntino, conti di prima", t3 is not None
          and t3.method == "dot" and np.allclose(t3.M, raw["M"]) and np.allclose(t3.offset, raw["offset"]))
    for bad in ({"A": [[1, 0], [0, 1]], "t": [0, 0], "k1": 5.0}, {"A": [[0, 0], [0, 0]], "t": [0, 0]},
                {"A": [[1, 0], [0, float("nan")]], "t": [0, 0]}, {"A": [[1, 0], [0, 1]], "t": [0, 0], "g": [3, 0]}):
        json.dump(dict(raw, **bad), open(path, "w"))
        if hc.HeadModel.load(path) is not None:
            break
    else:
        bad = None
    check("valori rovinati (lente impossibile, matrice nulla, NaN, inclinazione impossibile): calibrazione rifiutata",
          bad is None, bad)
    # spessore
    t4 = t1.copy()
    t4.moves_with_head, t4.height_mm, t4.nadir, t4.cal_thickness = False, 60.0, t1.nadir.copy(), 0.0
    t4.set_thickness(10.0)
    X0 = t1.img_to_bed(Z, px[:20])
    C = np.array([*t1.nadir, 60.0])
    ray = C[:2] + (X0 - C[:2]) * (50.0 / 60.0)
    check("spessore (camera fissa al carrello): come il raggio vero dalla camera al materiale più alto",
          float(np.abs(t4.img_to_bed(Z, px[:20]) - ray).max()) < 1e-9)
    check("…e il conto inverso torna", float(np.nanmax(np.abs(t4.bed_to_img(Z, t4.img_to_bed(Z, px)) - px))) < 1e-6)
    t4.set_thickness(500)
    check("…spessore oltre l'80% dell'altezza della camera: si ferma al limite (mai oltre la camera)",
          abs(t4.thickness - 48.0) < 1e-9)
    t5 = t1.copy()
    t5.moves_with_head = True
    t5.height_mm = 60.0
    t5.set_thickness(10.0)
    check("camera che sale con il laser: lo spessore non cambia niente", t5.delta() == 0.0
          and float(np.abs(t5.img_to_bed(Z, px) - t1.img_to_bed(Z, px)).max()) < 1e-12)

    # ================================================================== A2. punto sotto la camera
    N, tilt = hg.camera_nadir(t1, 60.0)
    mm2 = hg.camera_model(SIZE, 0.16, angle=180, mirror=True, offset=(30, -5), tilt=3, tilt_dir=-60, height=80,
                          q=(0.06, -0.05))  # centro della lente ben spostato: l'ordine dei conti conta
    N2, tilt2 = hg.camera_nadir(mm2, 80.0)
    check("punto del piano sotto la camera dalla prospettiva e dall'altezza (anche camera capovolta e specchiata)",
          np.hypot(*(N - t1.nadir)) < 0.2 and abs(tilt - 4) < 0.2 and np.hypot(*(N2 - mm2.nadir)) < 0.2
          and abs(tilt2 - 3) < 0.2, (N, t1.nadir, tilt, N2, mm2.nadir, tilt2))

    # ================================================================== A3. griglia
    plan, why = hg.plan_grid(0.079, (100, 56), spread=1.25)
    pts = plan.pts
    D = np.hypot(pts[:, None, 0] - pts[None, :, 0], pts[:, None, 1] - pts[None, :, 1])
    np.fill_diagonal(D, np.inf)
    check("griglia per una camera come la U20CAM: puntini di almeno 8 pixel, passo di almeno 25 pixel e sei volte il "
          "puntino", plan is not None and plan.dot / 0.079 * 1.25 >= 8 and plan.pitch / 0.079 >= 25
          and plan.pitch >= 6 * plan.dot * 1.25 - 1e-9, (plan and (plan.dot, plan.pitch), why))
    check("…righe sfalsate: ogni puntino ha i vicini alla distanza del passo (nessuno più vicino)",
          abs(float(D.min()) - plan.pitch) < 1e-6)
    big = pts[plan.is_big]
    corners = {(round(float(np.sign(x))), round(float(np.sign(y)))) for x, y in big}
    check("…tre puntini grandi in tre angoli (il quarto no)", len(big) == 3 and len(corners) == 3)
    check("…un puntino su cinque solo per il controllo, mai i grandi", 0.15 < plan.control.mean() < 0.25
          and not (plan.control & plan.is_big).any(), plan.control.mean())
    check("…niente puntini vicino al centro (lì c'è il puntino di prova)", float(np.hypot(*pts.T).min()) > plan.pitch * 0.79)
    check("…la griglia sta nel cartone (circa 15 × 10 cm, 15 mm di margine)", plan.size[0] <= 125 and plan.size[1] <= 75,
          plan.size)
    lines = plan.gcode((100.0, 50.0, lambda dx, dy: (dx, dy)), 250.0)
    s_vals = [float(tok[1:]) for ln in lines for tok in ln.split() if tok.startswith("S")]
    check("G-code della griglia: mai oltre la potenza scelta, laser spento all'inizio e alla fine",
          max(s_vals) == 250.0 and lines[1] == "M4 S0" and lines[-1] == "M5 S0")
    starts = [i for i, ln in enumerate(lines) if ln.startswith("G0") and i + 1 < len(lines)
              and lines[i + 1].startswith("G0")]
    approach_ok = True
    for i in starts:
        a = [float(t[1:]) for t in lines[i].split()[1:]]
        b_ = [float(t[1:]) for t in lines[i + 1].split()[1:]]
        if len(a) == 2 and len(b_) == 2 and not (abs(b_[0] - a[0] - 0.8) < 1e-6 and abs(b_[1] - a[1] - 0.8) < 1e-6):
            if abs(b_[1] - a[1]) > 1e-6:  # i cerchi interni dello stesso puntino partono sulla stessa riga
                approach_ok = False
    n_appr = 0
    for i in range(len(lines) - 1):
        a = lines[i].split()
        b_ = lines[i + 1].split()
        if a[0] == "G0" and b_[0] == "G0" and len(a) == 3 and len(b_) == 3:
            dx = float(b_[1][1:]) - float(a[1][1:])
            dy = float(b_[2][1:]) - float(a[2][1:])
            n_appr += abs(dx - 0.8) < 1e-6 and abs(dy - 0.8) < 1e-6
    check("…ogni puntino si raggiunge dalla stessa parte (gioco delle cinghie uguale per tutti)", approach_ok
          and n_appr == len(plan), (n_appr, len(plan)))
    check("…tempo stimato dell'incisione: 1–3 minuti", 40 < plan.seconds() < 200, plan.seconds())
    check("camera troppo grossolana (meno di 4 pixel per mm): calibrazione completa rifiutata con il motivo",
          hg.plan_grid(0.3, (190, 140))[0] is None and "pixel per mm" in hg.plan_grid(0.3, (190, 140))[1])
    check("zona inquadrata troppo piccola: rifiutata", hg.plan_grid(0.02, (12, 9))[0] is None)

    # ================================================================== A4. riconoscimento
    W, H = 800, 600
    img = np.full((H, W), 180.0, np.float32)
    img *= np.linspace(0.55, 1.15, W)[None, :]  # luce non uniforme
    truth = []
    for j in range(5):
        for i in range(7):
            u, v = 80 + i * 100 + rng.uniform(-0.5, 0.5), 80 + j * 105 + rng.uniform(-0.5, 0.5)
            truth.append((u, v))
            rr = 6.0 if (i, j) != (0, 0) else 13.0
            yy, xx = np.ogrid[:H, :W]
            dd = np.sqrt((xx - u) ** 2 + (yy - v) ** 2)
            img = np.where(dd < rr + 1, img * (0.35 + 0.65 * np.clip(dd - rr + 0.5, 0, 1)), img)
    cv2.ellipse(img, (450, 300), (40, 5), 20, 0, 360, 70, -1)  # una bruciatura storta / venatura
    cv2.line(img, (0, 560), (800, 545), 60, 3)  # una riga del legno
    img = np.clip(img + rng.normal(0, 2.0, img.shape), 0, 255).astype(np.uint8)
    dets = hg.detect_dots(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), 6.0, 1, 100)
    tr_ = np.array(truth)
    Dm = np.hypot(dets[:, None, 0] - tr_[None, :, 0], dets[:, None, 1] - tr_[None, :, 1])
    near = Dm.min(axis=1)
    check("puntini con luce non uniforme e rumore: trovati tutti (anche quello grande), centro entro 0,15 pixel",
          len(dets) == len(truth) and float(near.max()) < 0.15, (len(dets), float(near.max()) if len(near) else None))
    check("…la bruciatura storta e la riga del legno non sono puntini", float(near.max()) < 1.0)
    inv = 255 - img
    d2 = hg.detect_dots(cv2.cvtColor(inv, cv2.COLOR_GRAY2BGR), 6.0, -1, 100)
    check("puntini più chiari del fondo (materiale scuro): trovati con il verso giusto", len(d2) >= len(truth) - 1,
          len(d2))
    pred = tr_ + 3.0
    m_ = hg.match_dots(pred, dets, 30.0)
    check("abbinamento: ogni puntino previsto con il suo", len(m_) == len(truth)
          and all(np.hypot(*(dets[j, :2] - tr_[i])) < 1 for i, j in m_.items()))
    two = np.array([[100.0, 100.0, 1, 1, 1], [104.0, 100.0, 1, 1, 1]])
    check("…due macchie vicine al punto previsto: nessuna scelta (niente scambi)",
          hg.match_dots(np.array([[102.0, 100.0]]), two, 10.0) == {})

    # ================================================================== A5. calcolo
    plan5, _w = hg.plan_grid(0.079, t1.view_mm(), 1.2)
    G = np.array([200.0, 200.0])
    Xall = G + plan5.pts
    P, Ls, Xs, ctl = [], [], [], []
    for qx, qy in hg.photo_offsets(plan5, t1.view_mm()):
        p = t1.c + np.array([qx * 640, qy * 360])
        Lh = G - t1._rel([p])[0]
        pr = t1.bed_to_img(Lh, Xall)
        ok = np.isfinite(pr).all(1) & (pr[:, 0] > 10) & (pr[:, 0] < 1270) & (pr[:, 1] > 10) & (pr[:, 1] < 710)
        for i in np.nonzero(ok)[0]:
            P.append(pr[i] + rng.normal(0, 0.15, 2))
            Ls.append(Lh)
            Xs.append(Xall[i])
            ctl.append(plan5.control[i])
    P, Ls, Xs, ctl = map(np.array, (P, Ls, Xs, ctl))
    of = {"P": P[~ctl], "L": Ls[~ctl], "X": Xs[~ctl]}
    oc = {"P": P[ctl], "L": Ls[ctl], "X": Xs[ctl]}
    start = hg.model_params(hc.HeadModel(t1.M * 1.02, t1.offset + [0.5, -0.3], (1280, 720)))
    fits = {}
    for kind in hg.KINDS:
        pk, _r = hg.fit(of, (1280, 720), start, kind)
        e, _s = hg.errors_px(pk, oc, (1280, 720))
        fits[kind] = (pk, e)
        start = pk
    kind = hg.choose_kind(fits)
    mf = hg.params_model(fits[kind][0], (1280, 720))
    check("calcolo: con lente e inclinazione vince il modello completo e ritrova la camera vera (entro 0,02 mm)",
          kind == "full" and true_err(mf, t1, (1280, 720)) < 0.02, (kind, true_err(mf, t1, (1280, 720))))
    simple = hc.HeadModel(hc.natural_matrix(0.08, 12), (3, 30), (1280, 720))
    P = []
    for i in range(len(Xs)):
        P.append(simple.bed_to_img(Ls[i], [Xs[i]])[0] + rng.normal(0, 0.15, 2))
    P = np.array(P)
    ok = np.isfinite(P).all(1) & (P[:, 0] > 5) & (P[:, 0] < 1275) & (P[:, 1] > 5) & (P[:, 1] < 715)
    of = {"P": P[ok & ~ctl], "L": Ls[ok & ~ctl], "X": Xs[ok & ~ctl]}
    oc = {"P": P[ok & ctl], "L": Ls[ok & ctl], "X": Xs[ok & ctl]}
    start = hg.model_params(hc.HeadModel(simple.M * 0.99, simple.offset + [0.3, 0.2], (1280, 720)))
    fits = {}
    for kind in hg.KINDS:
        pk, _r = hg.fit(of, (1280, 720), start, kind)
        fits[kind] = (pk, hg.errors_px(pk, oc, (1280, 720))[0])
        start = pk
    check("camera senza lente e dritta: si sceglie il modello semplice (uno più libero si adatterebbe agli errori)",
          hg.choose_kind(fits) == "affine", {k: float(np.sqrt(np.mean(e ** 2))) for k, (_p, e) in fits.items()})

    # ================================================================== A6. immagini
    good = np.full((480, 640, 3), 150, np.uint8)
    good = np.clip(good + rng.normal(0, 3, good.shape), 0, 255).astype(np.uint8)
    rep = good.copy()
    rep[160:] = rep[160]
    half = good.copy()
    half[240:] = 0
    check("fotogramma buono accettato; righe ripetute o metà nera rifiutati (due camere sulla stessa USB)",
          hg.frame_ok(good)[0] and not hg.frame_ok(rep)[0] and not hg.frame_ok(half)[0])
    spot = good.copy()
    cv2.circle(spot, (300, 200), 9, (255, 255, 255), -1)
    grad = (np.linspace(120, 300, 640)[None, :, None] * np.ones((480, 1, 3))).clip(0, 255).astype(np.uint8)
    sticker = np.full((480, 640, 3), 244, np.uint8)
    cv2.rectangle(sticker, (300, 200), (312, 212), (255, 255, 255), -1)  # etichetta bianca su un fondo chiaro
    check("luce forte sul materiale (puntino rosso, Lucciola): vista; una zona chiara della luce ambiente o un'etichetta "
          "bianca su un materiale chiaro no", hg.light_spot(spot) and not hg.light_spot(good)
          and not hg.light_spot(grad) and not hg.light_spot(sticker))
    dark = (good * 0.2).astype(np.uint8)
    bright = np.full_like(good, 252)
    noisy = [good, np.clip(good + rng.normal(0, 14, good.shape[:2])[..., None], 0, 255).astype(np.uint8)]
    check("luce: buona sì; buio, troppa luce e immagine con molto rumore no (prima di sprecare il cartone)",
          hg.light_check([good, good])[0] and not hg.light_check([dark])[0] and not hg.light_check([bright])[0]
          and not hg.light_check(noisy)[0])
    frames = []
    base = cv2.resize(rng.uniform(80, 200, (60, 80)).astype(np.float32), (640, 480))
    for k in range(5):
        f = np.roll(base, 37 * k, axis=1).copy()
        f[400:, 0:160] = 70
        f[400:480:6, 0:160] = 30  # ugello con un disegno, sempre nello stesso posto
        frames.append(cv2.cvtColor(f.astype(np.uint8), cv2.COLOR_GRAY2BGR))
    occ = hg.find_occluded(frames)
    covered = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in occ)
    inside = all(x0 >= 0 and x1 <= 192 and y0 >= 384 for x0, y0, x1, y1 in occ)
    check("pezzo della macchina fermo nell'inquadratura (muovendo la testa): trovato e solo lui", covered >= 0.6 * 160 * 80
          and inside, occ)
    flat = [cv2.cvtColor(np.full((480, 640), 160, np.uint8), cv2.COLOR_GRAY2BGR)] * 5
    check("…un cartone liscio, uguale in tutte le foto, non è un pezzo della macchina", hg.find_occluded(flat) == [])

    # ================================================================== A7. mosaico
    class FakeSim:
        settings = {130: 300.0, 131: 200.0}
        burn_marks = []
        is_open = True
        state = "Idle"
        power = 0
        pos = [0.0, 0.0, 0.0]

        def to_bed(self, x, y):
            return (x, y)

    fs = FakeSim()
    tm = hg.camera_model(SIZE, 0.12, angle=10, offset=(5, 30), tilt=2, k1=-0.15, k2=0.03, q=(0.01, 0.0))
    sim_cam = hc.SimHeadCamera(fs, model=tm, size=SIZE, seed=5)
    sim_cam.close()  # niente lettura in sottofondo: le foto le chiede la prova
    # righe dritte nel materiale: una giunta sbagliata le farebbe doppie
    th = sim_cam.material.shape[0]
    for x in range(100, 200, 7):
        cv2.line(sim_cam.material, (int(x * 8), 0), (int(x * 8), th), (30, 30, 30), 3)

    def shot(L):
        fs.pos = [L[0], L[1], 0.0]
        return sim_cam._grab()

    mos = hc.Mosaic((300, 200), 4.0)
    for P_ in hc.mosaic_positions((110, 60, 190, 140), tm.view_mm(), 0.3):
        L_ = tm.head_for_camera(P_)
        mos.add(shot(L_), tm, L_)
    out = mos.image()
    x0, y0, x1, y1 = 115, 65, 185, 135
    mine = cv2.cvtColor(out[int((200 - y1) * 4):int((200 - y0) * 4), int(x0 * 4):int(x1 * 4)],
                        cv2.COLOR_BGR2GRAY).astype(np.float32)
    ref = cv2.resize(sim_cam.material, (1200, 800), interpolation=cv2.INTER_AREA)
    ref = cv2.cvtColor(ref[int((200 - y1) * 4):int((200 - y0) * 4), int(x0 * 4):int(x1 * 4)],
                       cv2.COLOR_BGR2GRAY).astype(np.float32)
    res = cv2.matchTemplate(mine[8:-8, 8:-8], ref, cv2.TM_CCOEFF_NORMED)
    _a, sc, _b, loc = cv2.minMaxLoc(res)
    err_mm = math.hypot(loc[0] - 8, loc[1] - 8) / 4.0
    check("mosaico con lente e inclinazione: al posto giusto (sotto 0,3 mm) e uguale al materiale vero",
          err_mm < 0.3 and sc > 0.85, (err_mm, sc))
    # niente linee doppie: ogni riga del materiale resta un solo minimo per ogni riga di pixel
    prof_ = mine.mean(axis=0)
    cols = [int((x - x0) * 4) for x in range(119, 185, 7)]
    widths = []
    for cx in cols:
        seg = prof_[max(0, cx - 10):cx + 10]
        widths.append(int((seg < seg.min() + 0.5 * (np.median(prof_) - seg.min())).sum()))
    check("…giunte nette: le righe del materiale restano sottili anche dove si uniscono due foto (niente linee doppie)",
          max(widths) <= 6, widths)
    check("…le giunte si aggiustano al massimo di 1 mm", all(math.hypot(*s) <= 1.0 + 1e-9 for s in mos.shifts))
    # calibrazione un po' sbagliata (scala del 3%): le giunte si spostano, ma ogni riga resta una (niente media fra due
    # foto sfasate, che darebbe righe doppie o fuse)
    bad = tm.copy()
    bad.A = bad.A * 1.03
    bad._refresh()
    mo3 = hc.Mosaic((300, 200), 4.0)
    for P_ in hc.mosaic_positions((110, 60, 190, 140), tm.view_mm(), 0.3):
        L_ = tm.head_for_camera(P_)
        mo3.add(shot(L_), bad, L_, align=False)
    o3 = cv2.cvtColor(mo3.image()[int((200 - y1) * 4):int((200 - y0) * 4), int(x0 * 4):int(x1 * 4)],
                      cv2.COLOR_BGR2GRAY).astype(np.float32)
    per_row = []
    for row in range(0, o3.shape[0], 4):
        r_ = o3[row]
        dk = r_ < np.median(r_) - 0.5 * (np.median(r_) - r_.min())
        per_row.append(int(((~dk[:-1]) & dk[1:]).sum()))
    want_n = len(range(119, 185, 7))
    check("…con una calibrazione un po' sbagliata le righe restano una per una (niente righe doppie nelle giunte)",
          max(per_row) <= want_n and min(per_row) >= want_n - 1, (min(per_row), max(per_row), want_n))
    miss = out[int(10 * 4), int(10 * 4)]
    check("…zona non fotografata: tratteggio, non nero né il colore del materiale",
          not np.isfinite(mos.best[40, 40]) and tuple(int(v) for v in miss) in ((46, 40, 34), (70, 62, 54)))
    tm_occ = tm.copy()
    tm_occ.occluded = [(0, 380, 200, 480)]
    mo2 = hc.Mosaic((300, 200), 4.0)
    L_ = tm.head_for_camera((150, 100))
    mo2.add(shot(L_), tm_occ, L_)
    corner = tm.img_to_bed(L_, [(60, 440)])[0]
    rc = (int((200 - corner[1]) * 4), int(corner[0] * 4))
    check("…le zone coperte da pezzi della macchina non finiscono nel mosaico", not np.isfinite(mo2.best[rc]))

    # ================================================================== A8. vista
    from freelasercut.head_camera_ui import DIHEDRAL, HeadView, auto_orientation  # noqa: E402

    ok_all = True
    for k in range(8):
        for mir in (False, True):
            ang = [0, 90, 180, 270][k % 4] + (7 if k >= 4 else 0)
            m8 = hc.HeadModel(hc.natural_matrix(0.1, ang, mir), (0, 30), SIZE)
            Dv = auto_orientation(m8.M)
            J = m8.M @ np.linalg.inv(Dv)  # mm sul piano per pixel di schermo
            right, down = J[:, 0] / np.hypot(*J[:, 0]), J[:, 1] / np.hypot(*J[:, 1])
            ok_all &= right[0] > 0.9 and down[1] < -0.9
    check("vista raddrizzata: per tutti i modi di montare la camera, a destra X+ e in alto Y+ (come il piano)", ok_all)
    hv = HeadView()
    hv.resize(800, 500)
    hv.set_frame(np.zeros((480, 640, 3), np.uint8))
    hv.model = hc.HeadModel(hc.natural_matrix(0.1, 180, True), (0, 30), SIZE)
    worst = 0.0
    for man in DIHEDRAL:
        hv.manual = man
        for z in (1.0, 3.7):
            hv.zoom = z
            hv.pan = QPointF(13, -21) if z > 1 else QPointF(0, 0)
            for uv in ((10, 20), (320, 240), (600, 470)):
                q = hv.to_img(hv.at(*uv))
                if q is not None:
                    worst = max(worst, math.hypot(q[0] - uv[0], q[1] - uv[1]))
    check("vista: schermo ↔ immagine con la stessa trasformazione in tutti gli orientamenti, con zoom e spostamento",
          worst < 1e-9, worst)
    hv.manual = np.eye(2)
    hv.fit()
    pos = QPointF(600, 150)
    before = hv.to_img(pos)
    from PySide6.QtGui import QWheelEvent  # noqa: E402

    ev = QWheelEvent(pos, hv.mapToGlobal(pos.toPoint()), QPoint(0, 0), QPoint(0, 240), Qt.NoButton, Qt.NoModifier,
                     Qt.ScrollUpdate, False)
    hv.wheelEvent(ev)
    after = hv.to_img(pos)
    check("rotella: ingrandisce tenendo fermo il punto sotto il cursore", hv.zoom > 1.3
          and math.hypot(after[0] - before[0], after[1] - before[1]) < 1e-6, (hv.zoom, before, after))
    got = []
    hv.clicked.connect(lambda u, v: got.append((u, v)))
    from PySide6.QtTest import QTest  # noqa: E402

    QTest.mouseClick(hv, Qt.LeftButton, Qt.NoModifier, QPoint(500, 300))
    want = hv.to_img(QPointF(500, 300))
    check("clic sul video ingrandito: il pixel giusto dell'immagine vera", got and want is not None
          and math.hypot(got[0][0] - want[0], got[0][1] - want[1]) < 1.0, (got, want))
    QTest.mouseDClick(hv, Qt.LeftButton, Qt.NoModifier, QPoint(500, 300))
    check("doppio clic: tutta l'immagine", hv.zoom == 1.0 and hv.pan == QPointF(0, 0))

# ================================================================== B. calibrazione sul simulatore
c = GrblController()
c.connect_port(SIM_PORT)
spin(2.0)
c.home()
until(lambda: c.homed, 20)
spin(1.0)
c.sim.speedup = 60
prof = MachineProfile()
prof.negative_space = c.sim.negative
sent = []
c.line_sent.connect(sent.append)


open_cams = []


def run_cal(true, at=(200, 200), moves=True, height=None, old=None, choice=None, on_progress=None, cancel_on=None,
            **cam_kw):
    c.sim.burn_marks.clear()  # un cartone nuovo per ogni calibrazione
    while open_cams:  # la camera simulata della prova prima non resta accesa (rallenterebbe tutto)
        open_cams.pop().close()
    cam = hc.SimHeadCamera(c.sim, profile=prof, model=true, size=SIZE, dot_r=0.25,
                           moves=cam_kw.pop("cam_moves", True), **cam_kw)
    spin(0.3)
    mx, my = prof.to_machine(*at)
    c.goto_machine(mx, my, 6000)
    until(lambda: c.last_status.get("state") == "Idle", 20)
    spin(0.5)
    sent.clear()
    open_cams.append(cam)
    cal = hg.HeadGridCalibration(c, cam, prof, 25.0, guess=tuple(true.offset), moves=moves, old_model=old,
                                 wait_stable=1.0)

    def honest(p):
        L = hc.head_on_bed(c, prof)
        t_ = true.bed_to_img(L, [cal.mark_bed])[0]
        cal.confirm(bool(np.hypot(*(np.asarray(p) - t_)) < 8))
    cal.need_confirm.connect(honest)
    cal.need_click.connect(lambda _t: cal.cancel())

    def lift(_t):
        if height is None:
            cal.height_answer(None)
            return
        cam.material_z = height
        cam.material_shift = np.array([0.7, -0.4])
        cal.height_answer(height)
    cal.need_height.connect(lift)
    cal.need_choice.connect(lambda _t: cal.choose(choice if choice is not None else True))
    res = {}
    cal.finished.connect(lambda m, msg: res.update(m=m, msg=msg))

    def prog(i, n, t_):
        if on_progress:
            on_progress(cam, cal, t_)
        if cancel_on and cancel_on in t_ and not res.get("cancelled"):
            res["cancelled"] = True
            cal.cancel()
    cal.progress.connect(prog)
    cal.start()
    until(lambda: "msg" in res, 600)
    spin(0.5)
    return res.get("m"), res.get("msg", "tempo scaduto"), cal, cam


def grid_started():
    return any("G2" in ln for ln in c.job_lines) and len(c.job_lines) > 60


if not BANCO and "B" in PARTI:
    tB = hg.camera_model(SIZE, 0.16, angle=180, mirror=True, offset=(30, -5), tilt=3, tilt_dir=40, k1=-0.18, k2=0.05,
                         q=(0.012, -0.01), height=60)
    tC = hg.camera_model(SIZE, 0.16, angle=5, offset=(5, 35), tilt=2, tilt_dir=30, k1=-0.15, k2=0.03, q=(0.01, -0.01))
if not BANCO and "B" in PARTI and caso("capovolta"):
    m, msg, cal, cam = run_cal(tB)
    qd = cal.report.get("quality", {})
    check("calibrazione completa, camera capovolta e specchiata, inclinata, lente forte: riuscita",
          m is not None and m.method == "grid" and "riuscita" in msg, msg)
    check("…la camera vera ritrovata su tutta l'immagine (entro 0,1 mm, 0,6 pixel)",
          m is not None and true_err(m, tB) < 0.1, m is not None and true_err(m, tB))
    check("…verifica onesta sui punti di controllo (non usati per il calcolo), detta in mm e in pixel",
          qd.get("n_ctrl", 0) >= 8 and qd.get("max_px", 9) <= hg.GOOD_MAX_PX and "punti di controllo" in msg
          and "pixel" in msg, qd)
    check("…modello scelto: lente completa e inclinazione (servono davvero)", qd.get("model") == "full", qd.get("model"))
    s_all = [float(tok[1:]) for ln in c.job_lines for tok in ln.split() if tok.startswith("S")]
    check("…la griglia è incisa alla potenza scelta (mai di più) e finisce con il laser spento",
          s_all and max(s_all) <= 0.25 * prof.s_max + 1e-6 and c.job_lines[-1] == "M5 S0", max(s_all))
    check("…foto con il laser spento: dopo la griglia solo movimenti, nessuna potenza", c.sim.power == 0)
    rep = cal.report
    check("…inquadratura ferma, nessun passo perso, gioco misurato", rep["stable_shift_px"] < 0.3
          and rep["return_shift_mm"] < 0.05 and rep["backlash"] is not None, rep)

if not BANCO and "B" in PARTI and caso("difficile"):
    m, msg, cal, cam = run_cal(tC, occlude=[(0, 360, 180, 480, 90)], corrupt_every=5, grain=0.5, gradient=0.3,
                               spots=[(215, 205, 1.5), (190, 195, 2.5)])
    check("pezzo della macchina davanti, fotogrammi rovinati, venatura, macchie e luce non uniforme: riuscita",
          m is not None and true_err(m, tC) < 0.15, (msg, m is not None and true_err(m, tC)))
    check("…la zona coperta è trovata e salvata (il mosaico non la userà)", m is not None and m.occluded
          and all(r[1] >= 340 and r[0] < 200 for r in m.occluded) and "coperta" in msg, m is not None and m.occluded)

if not BANCO and "B" in PARTI and caso("carrello"):
    m, msg, cal, cam = run_cal(tC, moves=False, height=4.0, cam_moves=False)
    check("camera fissa al carrello: seconda altezza con il cartone sollevato di 4 mm (e spostato): altezza misurata",
          m is not None and m.moves_with_head is False and abs(m.height_mm - 60) < 3, (msg, m and m.height_mm))
    check("…punto sotto la camera ritrovato (per correggere lo spessore)", m is not None
          and np.hypot(*(m.nadir - tC.nadir)) < 0.5, m is not None and (m.nadir, tC.nadir))
    if m is not None:
        mt = m.copy()
        mt.set_thickness(m.cal_thickness + 10)
        tt = tC.copy()
        tt.moves_with_head, tt.cal_thickness, tt.height_mm = False, 0.0, 60.0
        tt.set_thickness(10)
        check("…con 10 mm di materiale in più le posizioni seguono la camera vera (entro 0,2 mm)", true_err(mt, tt) < 0.2,
              true_err(mt, tt))
if not BANCO and "B" in PARTI and caso("nonso"):
    m, msg, cal, cam = run_cal(tC, moves=None, height=4.0, cam_moves=True)
    check("«Non so» e la camera invece sale con il laser: lo capisce da sola (lo spessore non conta)",
          m is not None and m.moves_with_head is True and "sale e scende" in msg, msg)

if not BANCO and "B" in PARTI and caso("fuoco"):
    m, msg, cal, cam = run_cal(tC, on_progress=lambda cam_, cal_, t_: setattr(cam_, "drift", (
        time.time() - cam_._t0 + 0.3, 1.006)) if "tenga l'inquadratura" in t_ and cam_.drift is None else None)
    check("messa a fuoco automatica che cambia l'inquadratura a testa ferma: calibrazione da rifare, non salvata",
          m is None and "inquadratura" in msg and "messa a fuoco" in msg, msg)

if not BANCO and "B" in PARTI and caso("passi"):
    m, msg, cal, cam = run_cal(tC, on_progress=lambda cam_, cal_, t_: setattr(cam_, "slip", np.array([0.4, 0.0]))
                               if "(5 di 5)" in t_ else None)
    check("passi persi durante le foto: calibrazione da rifare, non salvata, con il motivo", m is None
          and "perso passi" in msg, msg)

if not BANCO and "B" in PARTI and caso("buio"):
    m, msg, cal, cam = run_cal(tC, light=0.15)
    check("buio: si ferma prima della griglia e dice di accendere una luce", m is None and "scura" in msg
          and not grid_started(), msg)

if not BANCO and "B" in PARTI and caso("cartone"):
    m, msg, cal, cam = run_cal(tC, board=[(175, 180), (225, 180), (225, 215), (175, 215)])
    check("cartone più piccolo della griglia: si ferma prima di inciderla e dice cosa fare", m is None
          and "non copre" in msg and not grid_started(), msg)

if not BANCO and "B" in PARTI and caso("annulla"):
    m, msg, cal, cam = run_cal(tC, cancel_on="Incido la griglia…")
    spin(1.0)
    check("annulla durante la griglia: il lavoro si ferma davvero, laser spento, niente salvato",
          m is None and "annullata" in msg.lower() and c.sim.power == 0 and not c.job_active, msg)
    if c.last_status.get("state") == "Alarm":
        c.home()
        until(lambda: c.homed and c.last_status.get("state") == "Idle", 30)
        spin(0.5)

if not BANCO and "B" in PARTI and caso("vecchia"):
    good_old = hg.camera_model(SIZE, 0.16, angle=5, offset=(5, 35), tilt=2, tilt_dir=30, k1=-0.15, k2=0.03,
                               q=(0.01, -0.01))
    m, msg, cal, cam = run_cal(tC, old=good_old, choice=False)
    check("calibrazione di prima quasi uguale sui punti di controllo: decide la persona; «no» = resta quella",
          m is None and "Tengo la calibrazione di prima" in msg,
          (msg, cal.report.get("old_p95_px"), cal.report.get("new_p95_px")))
    bad_old = hc.HeadModel(tC.M, tC.offset + [0.4, 0], SIZE)
    m, msg, cal, cam = run_cal(tC, old=bad_old)
    check("calibrazione di prima peggiore: si tiene quella nuova", m is not None and "riuscita" in msg,
          (msg, cal.report.get("old_p95_px")))

if not BANCO and "B" in PARTI and caso("piano"):
    # ---------------------------------------------------------------- B2. camera del piano aiutata (parte 2)
    c.sim.burn_marks.clear()
    while open_cams:
        open_cams.pop().close()
    camA = hc.SimHeadCamera(c.sim, profile=prof, model=tC, size=SIZE, seed=9)
    bxA, byA = prof.bed_x, prof.bed_y
    truth_top = cv2.resize(camA.material, (int(round(bxA * hg.BED_PPM)), int(round(byA * hg.BED_PPM))),
                           interpolation=cv2.INTER_AREA)
    Ae = np.array([[0.012, 0.004], [-0.003, 0.012]])  # come uno spessore di qualche mm visto dall'alto + rotazione
    be = np.array([-1.9, 2.4])
    S_ = np.array([[hg.BED_PPM, 0, 0], [0, -hg.BED_PPM, byA * hg.BED_PPM], [0, 0, 1]])
    T_ = np.vstack([np.hstack([np.eye(2) + Ae, be.reshape(2, 1)]), [0, 0, 1]])
    Wf = S_ @ T_ @ np.linalg.inv(S_)
    bed_top = cv2.warpAffine(truth_top, Wf[:2], (truth_top.shape[1], truth_top.shape[0]),
                             borderMode=cv2.BORDER_REPLICATE)

    class FakeBedCam:
        def __init__(self, img):
            self.img = img

        def frames(self, n, after=0):
            return [self.img.copy() for _ in range(n)]

    class FakeBedModel:
        valid = (60.0, 60.0, 280.0, 260.0)

        def rectify(self, frame, ppm):
            return frame

    def align(img):
        job = hg.BedAlignJob(c, camA, prof, tC, FakeBedCam(img), FakeBedModel(), park=(15.0, 15.0))
        out = {}
        job.finished.connect(lambda corr, msg: out.update(corr=corr, msg=msg))
        job.start()
        until(lambda: "msg" in out, 240)
        spin(0.3)
        return out.get("corr"), out.get("msg", "tempo scaduto"), job

    corr, msg, job = align(bed_top)
    ok_c = corr is not None
    check("camera del piano aiutata: la camera della testa ritrova i punti nella foto del piano e ne ricava la "
          "correzione (spostamento 1,9/2,4 mm, scala e rotazione)", ok_c and corr["inliers"] >= 6
          and np.abs(corr["A"] - Ae).max() < 0.002 and np.hypot(*(corr["b"] - be)) < 0.4, (msg, corr))
    if ok_c:
        fixed = hg.apply_bed_correction(bed_top, corr, byA, hg.BED_PPM)
        r0, r1, c0, c1 = int((byA - 250) * 4), int((byA - 90) * 4), int(90 * 4), int(250 * 4)
        a_ = cv2.cvtColor(fixed[r0:r1, c0:c1], cv2.COLOR_BGR2GRAY).astype(np.float32)
        b_ = cv2.cvtColor(truth_top[r0:r1, c0:c1], cv2.COLOR_BGR2GRAY).astype(np.float32)
        res_ = cv2.matchTemplate(a_[16:-16, 16:-16], b_, cv2.TM_CCOEFF_NORMED)
        _x, sc_, _y, loc_ = cv2.minMaxLoc(res_)
        check("…la foto corretta coincide con il materiale vero (sotto 0,3 mm)", math.hypot(loc_[0] - 16, loc_[1] - 16)
              / hg.BED_PPM < 0.3 and sc_ > 0.8, (loc_, sc_))
    check("…il risultato dice prima e dopo, in mm, e che vale per il materiale di adesso", ok_c and "prima sbagliava"
          in msg and "materiale" in msg, msg)
    check("…laser sempre spento", c.sim.power == 0)
    # una zona più alta: quel punto non torna con gli altri e si dice dove
    bump = bed_top.copy()
    yy0, xx0 = int((byA - 190) * 4), int(200 * 4)
    patch_ = bump[yy0 - 120:yy0 + 120, xx0 - 120:xx0 + 120].copy()
    bump[yy0 - 120 + 14:yy0 + 120 + 14, xx0 - 120 + 14:xx0 + 120 + 14] = patch_
    corr2, msg2, _j = align(bump)
    check("una zona più alta (un punto che non torna con gli altri): il punto si esclude e si dice dove",
          corr2 is not None and corr2["outliers"] and "non torna con gli altri" in msg2, msg2)
    # materiale imbarcato (piegato lungo X): lo spostamento cresce come il quadrato della distanza dal centro,
    # nessuna correzione sola va bene
    H_, W_ = bed_top.shape[:2]
    yy_, xx_ = np.mgrid[0:H_, 0:W_].astype(np.float32)
    cx_ = 200 * 4
    warp = cv2.remap(bed_top, xx_, yy_ + 3.0 * 4 * ((xx_ - cx_) / (100 * 4)) ** 2, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)
    corr4, msg4, _j = align(warp)
    check("materiale imbarcato (non piano): nessuna correzione e lo dice", corr4 is None
          and any(k_ in msg4 for k_ in ("non è piano", "non tornano", "troppo pochi", "almeno 4")), msg4)
    smooth = np.full_like(bed_top, 170)
    camA.material[:] = 170
    corr3, msg3, _j = align(smooth)
    check("materiale liscio (niente da riconoscere): nessuna correzione e lo dice", corr3 is None
          and "almeno 4 punti" in msg3, msg3)
    camA.close()

c.disconnect_port()
spin(0.5)

if "C" not in PARTI:
    print(f"\n{sum(results)}/{len(results)} prove superate")
    sys.exit(0 if all(results) else 1)

# ================================================================== C. interfaccia
from freelasercut import head_camera_ui as hcu  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
w.ctl.connect_port(SIM_PORT)
spin(3.0)
w.ctl.home()
until(lambda: w.ctl.homed, 20)
spin(1.0)
w.ctl.sim.speedup = 60
card = w.camera.head
w.ctl.sim.burn_marks.clear()
tU = hg.camera_model(SIZE, 0.15, angle=180, mirror=False, offset=(5, 32), tilt=2, tilt_dir=10, k1=-0.12, k2=0.02)
cam = hc.SimHeadCamera(w.ctl.sim, profile=w.profile, model=tU, size=SIZE, dot_r=0.25)
card.set_source(cam)
spin(0.5)
w.goto_bed(200, 200)
until(lambda: hc.head_on_bed(w.ctl, w.profile) is not None
      and np.hypot(*(hc.head_on_bed(w.ctl, w.profile) - (200, 200))) < 0.05, 20)
spin(0.5)
dlg = hcu.HeadCalDialog(card, 25)
check("finestra della calibrazione completa: la sola domanda nuova (la camera sale e scende con il laser?), «Sì» "
      "all'inizio, spessore del cartone solo per No / Non so", set(dlg.moves_btns) == {"yes", "no", "unknown"}
      and dlg.moves() is True and dlg.card_row.isHidden())
dlg.set_moves("no")
check("…«No»: compare lo spessore del cartone", not dlg.card_row.isHidden() and dlg.moves() is False)
check("…dice cosa serve (cartone di circa 15 × 10 cm) e quanto dura", "15 × 10" in "".join(
    lb.text() for lb in dlg.findChildren(hcu.QLabel)))
dlg.close()


def accept_yes(self):
    self.set_moves("yes")
    self.pad.set_direction("u")  # la camera è 3 cm verso il fondo rispetto al laser (come la camera simulata)
    self.pad.cm.setValue(3.2)
    return QDialog.Accepted


hcu.HeadCalDialog.exec = accept_yes
win = card.open_window()
card.calibrate(25, guess=tuple(tU.offset))
until(lambda: card.cal is None, 400)
mdl = card.model
check("calibrazione dal pulsante: riuscita e salvata, stato «✓ Calibrata»", mdl is not None and mdl.method == "grid"
      and os.path.exists(hc.head_file()) and "✓" in card.state.text(), (card.state.text(), win.cal_text.text()))
check("…camera che sale con il laser: niente spessore da scrivere", win.th_row.isHidden())
check("…precisione detta nel risultato", "errore massimo" in win.cal_text.text(), win.cal_text.text())
win.tick()
spin(0.3)
Dv = win.view.orientation()
J = mdl.M @ np.linalg.inv(Dv)
check("vista raddrizzata da sola dopo la calibrazione (camera montata capovolta): a destra X+, in alto Y+",
      J[0, 0] > 0 and J[1, 1] < 0 and win.chk_upright.isChecked(), J)
win.chk_upright.setChecked(False)
check("…«Raddrizza da sola» spento: l'immagine com'è e la scelta si ricorda",
      np.allclose(win.view.orientation(), np.eye(2)) and w.qs.value("head_view_auto") == "0")
win.chk_upright.setChecked(True)
win._flip("h")
check("…«Capovolgi in orizzontale» si aggiunge e si ricorda", not np.allclose(win.view.orientation(), Dv)
      and w.qs.value("head_view_manual") == "-1,0,0,1")
win._flip("h")
# clic sul video ingrandito: la camera va dove si è fatto clic
L0 = card.head()
win.view.zoom = 2.5
win.view.pan = QPointF(30, -10)
target_px = (450.0, 130.0)
P_want = mdl.img_to_bed(L0, [target_px])[0]
vpos = win.view.at(*target_px)
card.click_on_video(*win.view.to_img(vpos))
until(lambda: np.hypot(*(mdl.center(card.head()) - P_want)) < 0.05 and w.ctl.last_status.get("state") == "Idle", 20)
check("clic sul video ruotato e ingrandito: il punto cliccato va sotto il mirino",
      np.hypot(*(mdl.center(card.head()) - P_want)) < 0.05)
win.view.fit()
# controlla
job = card.check_calibration()
until(lambda: card.check is None, 60)
res = getattr(card, "last_check", None)
check("«Controlla»: calibrazione ancora buona (l'immagine si sposta come previsto)", res is not None and res["ok"],
      (res, win.cal_text.text()))
cam.true = tU.copy()
cam.true.A = cam.true.A * 1.02  # camera più bassa nel supporto: la scala cambia del 2%
cam.true._refresh()
cam._R = None
card.check_calibration()
until(lambda: card.check is None, 60)
res = getattr(card, "last_check", None)
check("…camera spostata nel supporto (scala cambiata del 2%): «rifai la calibrazione»", res is not None
      and not res["ok"] and "Rifai" in win.cal_text.text(), (res, win.cal_text.text()))
cam.true = tU.copy()
cam.true.t = cam.true.t + np.array([1.0, 0.0])  # camera urtata: guarda 1 mm più in là, scala uguale
cam.true._refresh()
cam._R = None
card.check_calibration()
until(lambda: card.check is None, 60)
res = getattr(card, "last_check", None)
check("…camera urtata di 1 mm: gli spostamenti da soli non lo vedono (lo dice la prova successiva)",
      res is not None and res["ok"], res)
card.check_calibration(dot=True, ask=False)
until(lambda: card.check is None, 90)
res = getattr(card, "last_check", None)
check("…«Con un puntino»: il puntino non è dove la camera lo aspetta → «rifai la calibrazione»",
      res is not None and not res["ok"] and res.get("dot_mm") is not None and 0.6 < res["dot_mm"] < 1.4,
      (res, win.cal_text.text()))
cam.true = tU
cam._R = None
card.check_calibration(dot=True, ask=False)
until(lambda: card.check is None, 90)
res = getattr(card, "last_check", None)
check("…con la camera a posto il puntino è sotto il mirino: calibrazione buona", res is not None and res["ok"]
      and res.get("dot_mm") is not None and res["dot_mm"] < 0.3, res)
check("…laser spento alla fine", w.ctl.sim.power == 0)
# Stampa e taglia dal centro camera
from freelasercut.ui.dialogs_printcut import PrintCutDialog  # noqa: E402

pcd = PrintCutDialog(w)
pcd.refresh()
check("Stampa e taglia: pulsante «Dal centro camera» con la camera della testa calibrata",
      not pcd.b_cam[0].isHidden() and pcd.camera_ready() is None)
from freelasercut.core import print_cut as pc  # noqa: E402

pcd.add_marks() if pc.find_marks(w.editor.doc)[0] is None else None
pcd.refresh()
before = card.head()
pcd.take_from_camera(1)
want = mdl.center(before)
check("…la crocetta 1 è il punto sotto il mirino (senza portare prima il laser sul centro camera)",
      pcd.pts[0] is not None and math.hypot(pcd.pts[0][0] - want[0], pcd.pts[0][1] - want[1]) < 1e-6
      and np.hypot(*(card.head() - before)) < 1e-6, (pcd.pts[0], want))
pcd.close()
# foto a mosaico e «Togli la foto dal piano»
w.editor.select([s for s in w.editor.doc.shapes][:1]) if w.editor.doc.shapes else None
card.board = [(180.0, 180.0), (220.0, 180.0)]
job = card.take_mosaic("board")
until(lambda: card.job is None, 200)
check("foto a mosaico: sotto il piano, a 4 pixel per mm", w.camera.mosaic is not None
      and w.camera.mosaic.shape[1] == int(round(w.profile.bed_x * 4)) and win.b_unmosaic.isEnabled())
win.b_unmosaic.click()
spin(0.2)
check("«Togli la foto dal piano»: tolta, il pulsante si spegne", w.camera.mosaic is None
      and getattr(w.bed, "_cam_item", None) is None and not win.b_unmosaic.isEnabled())
w.camera.show_mosaic(np.zeros((40, 40, 3), np.uint8), 4.0)
w.acts["clear_mosaic"].trigger()
check("…anche dal menu Visualizza", w.camera.mosaic is None and w.acts["clear_mosaic"] in w.m_view.actions())
# camera fissa al carrello: lo spessore si scrive nella vista
card.model.moves_with_head = False
card.model.height_mm = 60.0
card.model.nadir = card.model.offset + np.array([-5.0, 0.0])  # camera un po' inclinata: il mirino non è sotto di lei
win.thick.setValue(card.model.cal_thickness)
win.update_state()
check("camera fissa al carrello: nella vista compare lo spessore del materiale", not win.th_row.isHidden())
hd = card.head()
c_before = card.model.center(hd)
win.thick.setValue(card.model.cal_thickness + 6.0)
c_after = card.model.center(hd)
want_c = hd + card.model.nadir + (c_before - hd - card.model.nadir) * (54.0 / 60.0)
check("…6 mm di materiale in più: il punto sotto il mirino si sposta come vuole la geometria (tutti i comandi lo "
      "usano) e lo spessore si ricorda", np.hypot(*(c_after - want_c)) < 1e-6
      and abs(float(w.qs.value("head_camera_thickness")) - (card.model.cal_thickness + 6.0)) < 1e-9,
      (c_after, want_c))
# correzione della foto del piano: si vede solo quando c'è, si accende e si spegne per confrontare
check("senza correzione della foto del piano: la casella non c'è", w.camera.chk_align.isHidden())
w.camera.set_align({"A": np.zeros((2, 2)), "b": np.array([1.0, 0.0]), "inliers": 5, "points": 9, "before_mm": 1.0,
                    "after_mm": 0.1})
check("…con la correzione: casella «Correzione dalla camera della testa» accesa", not w.camera.chk_align.isHidden()
      and w.camera.chk_align.isChecked())
w.camera.set_align(None)
check("…tolta (per esempio rifacendo la calibrazione della camera del piano): la casella sparisce",
      w.camera.chk_align.isHidden() and w.camera.align is None)
card.close_src()
w.ctl.disconnect_port()
spin(0.5)

print(f"\n{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
