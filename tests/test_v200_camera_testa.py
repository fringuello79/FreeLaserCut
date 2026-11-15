# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.0: camera della testa (telecamera fissata alla testa del laser).

Il dato: P = L + O + M · (p − c) (vedi freeburn/aggiornamento-0.20.0.md). Matrice dei casi:
1. modello: conti diretti e inversi con scala, rotazione 0/37/90/180°, specchio; file vecchio, rovinato, assente;
2. immagini: puntino nuovo, centro della macchia, inseguimento, angolo della tavola (anche ruotata) e caso senza angolo;
3. tavola: angolo del lato A→B e appoggio della selezione (rotazione e posizione numeriche, un solo Annulla);
4. mosaico: posizioni che coprono la zona, foto incollate nel posto giusto;
5. calibrazione sul simulatore: camera dritta, ruotata, capovolta e specchiata, puntino fuori dall'inquadratura (ricerca
   automatica), materiale senza trama (clic della persona), annulla (laser spento, niente salvato), disconnessa;
6. comandi: laser sul centro camera, camera sul laser, camera qui anche vicino al bordo, origine dal centro camera
   (anche con assi invertiti e piano ruotato), menu del tasto destro, segno sul piano;
7. scelta delle telecamere: piano e testa diverse, stessa camera rifiutata, «Nessuna»;
8. ricerca delle telecamere che non risponde; telecamera collegata dopo l'avvio;
9. traduzioni.
Con l'argomento «banco» si prova l'interfaccia Banco (parti 6–7 e una calibrazione).
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import camera, head_camera as hc  # noqa: E402
from freelasercut.grbl import SIM_PORT, GrblController  # noqa: E402
from freelasercut.i18n import tr  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []
hidden = []
sys.excepthook = lambda *a: (hidden.append(a[1]), sys.__excepthook__(*a))


def check(name, cond, info=""):
    results.append(bool(cond))
    extra = "" if cond or info is None or (isinstance(info, str) and not info) else f"  [{info}]"
    print(("OK  " if cond else "NO  ") + name + extra, flush=True)


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


rng = np.random.default_rng(7)

if not BANCO:
    # ================================================================== 1. modello
    head = np.array([120.0, 80.0])
    ok_all = True
    for ang in (0.0, 37.0, 90.0, 180.0):
        for mirror in (False, True):
            M = hc.natural_matrix(0.085, ang, mirror)
            m = hc.HeadModel(M, (4.0, 33.0), (1280, 720))
            px = rng.uniform(0, 1280, (50, 2))
            back = m.bed_to_img(head, m.img_to_bed(head, px))
            ok_all &= float(np.abs(back - px).max()) < 1e-6
            ok_all &= abs(m.mm_per_px() - 0.085) < 1e-9 and m.mirrored() == mirror
            ok_all &= abs((m.angle_deg() - ang + 180) % 360 - 180) < 1e-6
    check("modello: pixel → piano → pixel con rotazione 0/37/90/180° e specchio, scala e angolo letti giusti", ok_all)
    m = hc.HeadModel(hc.natural_matrix(0.1, 0, False), (4.0, 33.0), (1280, 720))
    check("il centro dell'immagine (mirino) è in L + O", np.allclose(m.img_to_bed(head, [m.c])[0], head + [4, 33])
          and np.allclose(m.center(head), head + [4, 33]))
    check("«porta la camera su P» = laser in P − O", np.allclose(m.head_for_camera((50, 60)), (46, 27)))
    vw, vh = m.view_mm()
    check("zona inquadrata: 1280 × 720 pixel a 0,1 mm = 128 × 72 mm", abs(vw - 128) < 1e-6 and abs(vh - 72) < 1e-6)
    up = m.img_to_bed(head, [m.c - [0, 100]])[0] - m.center(head)
    check("camera normale: in alto nell'immagine = verso Y+ sul piano", up[1] > 9.99 and abs(up[0]) < 1e-9, up)
    check("descrizione con mm per pixel, rotazione e scostamento", "0.100" in m.describe() and "+33.00" in m.describe())

    d = tempfile.mkdtemp()
    path = os.path.join(d, "hc.json")
    m.camera_name = "Innomaker-U20CAM-1080p-S1"
    m.save(path)
    m2 = hc.HeadModel.load(path)
    check("file: salvato e riletto uguale (matrice, scostamento, risoluzione, nome della camera)",
          m2 is not None and np.allclose(m2.M, m.M) and np.allclose(m2.offset, m.offset)
          and m2.frame_size == (1280, 720) and m2.camera_name == "Innomaker-U20CAM-1080p-S1")
    m3 = hc.HeadModel(hc.natural_matrix(0.08, 12), (30, 5), (1280, 720), k=-0.22)
    m3.save(path)
    m4 = hc.HeadModel.load(path)
    px = rng.uniform(0, [1280, 720], (200, 2))
    check("lente: salvata e riletta; pixel → piano → pixel uguale anche ai bordi dell'immagine",
          m4 is not None and abs(m4.k + 0.22) < 1e-12
          and float(np.abs(m4.bed_to_img(head, m4.img_to_bed(head, px)) - px).max()) < 1e-3)
    d0 = json.load(open(path))
    d0.pop("k")
    json.dump(d0, open(path, "w"))
    check("file senza la lente (calibrazioni di prima): letto con lente perfetta", hc.HeadModel.load(path).k == 0.0)
    dot = np.full((450, 800, 3), 90, np.uint8)
    q = np.array([700.0, 80.0])
    pd_ = hc.distort_px([q], np.array([400.0, 225.0]), math.hypot(800, 450) / 2, -0.22)[0]
    cv2.circle(dot, (int(round(pd_[0])), int(round(pd_[1]))), 4, (250, 250, 250), -1, cv2.LINE_AA)
    flat_m = hc.HeadModel(hc.natural_matrix(0.08), (0, 0), (800, 450), k=-0.22)
    und = hc.undistort_frame(dot, flat_m)
    g_ = cv2.cvtColor(und, cv2.COLOR_BGR2GRAY).astype(float) - 150  # solo il punto chiaro (il bordo è nero)
    g_[g_ < 0] = 0
    yy, xx = np.mgrid[0:450, 0:800]
    cen = ((xx * g_).sum() / g_.sum(), (yy * g_).sum() / g_.sum())
    check("foto «senza lente» per il mosaico: un punto vicino all'angolo torna dove deve (sotto 1 pixel)",
          math.hypot(cen[0] - q[0], cen[1] - q[1]) < 1.0, cen)
    far_px = m3.bed_to_img(head, [head + m3.offset + (5000, 5000)])
    check("punto lontanissimo con una lente a barile: nessuna posizione inventata nell'immagine (non si disegna)",
          not np.isfinite(far_px).any(), far_px)
    check("file assente: nessuna calibrazione, nessun errore", hc.HeadModel.load(os.path.join(d, "no.json")) is None)
    open(path, "w").write("{rovinato")
    check("file rovinato: nessuna calibrazione", hc.HeadModel.load(path) is None)
    json.dump({"M": [[0, 0], [0, 0]], "offset": [0, 0], "frame_size": [640, 480]}, open(path, "w"))
    check("matrice nulla nel file: rifiutata", hc.HeadModel.load(path) is None)
    json.dump({"M": [[0.1, 0], [0, -0.1]], "frame_size": [640, 480]}, open(path, "w"))
    check("file senza scostamento (vecchio o incompleto): rifiutato", hc.HeadModel.load(path) is None)
    json.dump({"M": [[0.1, 0], [0, -0.1]], "offset": [1, 2], "frame_size": [0, 480]}, open(path, "w"))
    check("risoluzione zero nel file: rifiutata", hc.HeadModel.load(path) is None)

    Mt = hc.natural_matrix(0.07, 23, True)
    pix = rng.uniform(-200, 200, (6, 2))
    Ms, rms = hc.solve_matrix(pix, pix @ Mt.T)
    check("dove è la camera: «a destra, 6 cm» = 60 mm in X; «in alto, 4 cm» = 40 mm in Y; diagonale = stessa distanza",
          hc.guess_from_direction("r", 6) == (60.0, 0.0) and hc.guess_from_direction("u", 4) == (0.0, 40.0)
          and hc.guess_from_direction("l", 2.5) == (-25.0, 0.0) and hc.guess_from_direction("d", 3) == (0.0, -30.0)
          and abs(math.hypot(*hc.guess_from_direction("ul", 10)) - 100) < 1e-3
          and hc.guess_from_direction("ul", 10)[0] < 0 < hc.guess_from_direction("ul", 10)[1])
    BED = (450.0, 440.0)
    st, _w = hc.calibration_start((5, 220), (60, 0), BED)
    check("camera 6 cm a destra e testa vicino allo 0: il puntino si incide più a destra (la camera deve poterci "
          "andare sopra)", st == (90.0, 220.0), st)
    st, _w = hc.calibration_start((440, 200), (-60, 0), BED)
    check("camera 6 cm a sinistra e testa vicino al bordo destro: il puntino si incide più a sinistra",
          st == (360.0, 200.0), st)
    st, _w = hc.calibration_start((200, 15), (0, 50), BED)
    st2, _w = hc.calibration_start((200, 435), (0, 50), BED)
    check("camera 5 cm in alto (verso il fondo): il puntino non nei primi 8 cm davanti, e lontano dal bordo in fondo",
          st == (200.0, 80.0) and st2 == (200.0, 410.0), (st, st2))
    st, _w = hc.calibration_start((300, 300), (-35, 35), BED)
    check("camera in diagonale, testa già in un punto buono: il puntino si incide lì", st == (300.0, 300.0), st)
    st, _w = hc.calibration_start((10, 10), None, BED)
    check("non sai dov'è la camera: il puntino si incide almeno 6 cm dentro il piano (la ricerca gira tutto intorno)",
          st == (60.0, 60.0), st)
    st, why = hc.calibration_start((100, 100), (210, 0), (200, 200))
    check("piano troppo piccolo per quella distanza: niente calibrazione e si dice perché", st is None and "lontana" in why,
          (st, why))
    check("«non lo so» o distanza zero: nessuna indicazione", hc.guess_from_direction("", 5) is None
          and hc.guess_from_direction("r", 0) is None and hc.guess_from_direction("x", 5) is None)
    check("minimi quadrati: matrice ritrovata esatta", Ms is not None and np.allclose(Ms, Mt) and rms < 1e-9)
    check("spostamenti tutti sulla stessa retta: niente matrice", hc.solve_matrix([(1, 0), (2, 0), (-3, 0)],
                                                                                 [(1, 1), (2, 2), (3, 3)])[0] is None)

    # ================================================================== 2. immagini
    base = (150 + 40 * cv2.GaussianBlur(rng.uniform(0, 1, (480, 640)).astype(np.float32), (0, 0), 4)).astype(np.uint8)
    before = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
    after = before.copy()
    cv2.circle(after, (412, 133), 9, (40, 44, 50), -1, cv2.LINE_AA)
    p = hc.find_new_mark([before, before], [after, after])
    check("puntino nuovo trovato con la differenza prima/dopo", p is not None and math.hypot(p[0] - 412, p[1] - 133) < 1.0, p)
    check("nessun cambiamento: nessun puntino", hc.find_new_mark([before], [before.copy()]) is None)
    two = after.copy()
    cv2.circle(two, (100, 300), 9, (40, 44, 50), -1, cv2.LINE_AA)
    check("due macchie uguali: non so quale sia (niente puntino invece di uno sbagliato)",
          hc.find_new_mark([before], [two]) is None)
    q = hc.refine_dark(after, (406, 128))
    check("centro della macchia da un punto vicino", q is not None and math.hypot(q[0] - 412, q[1] - 133) < 0.6, q)
    tpl = hc.patch(after, (412, 133))
    moved = np.roll(np.roll(after, 37, axis=1), -21, axis=0)
    t, score = hc.track(moved, tpl)
    check("inseguimento: il puntino spostato di (+37, −21) pixel ritrovato", t is not None and score > 0.9
          and math.hypot(t[0] - 449, t[1] - 112) < 0.5, (t, score))
    check("zona troppo vicina al bordo: niente modello da seguire", hc.patch(after, (5, 5)) is None)

    def board_img(angle, corner=(300, 260), size=(640, 480)):
        img = np.full((size[1], size[0]), 45, np.uint8)
        for y in range(0, size[1], 40):
            cv2.line(img, (0, y), (size[0], y), 20, 2)
        for x in range(0, size[0], 46):
            cv2.line(img, (x, 0), (x + 20, size[1]), 20, 2)
        a = math.radians(angle)
        u, n = np.array([math.cos(a), math.sin(a)]), np.array([math.sin(a), -math.cos(a)])
        c = np.array(corner, float)
        poly = np.array([c, c + u * 900, c + u * 900 + n * 900, c + n * 900], np.int32)
        cv2.fillPoly(img, [poly], 200)
        img = np.clip(img + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    errs = []
    for ang in (0, 9, -14, 33, 90):
        f = board_img(ang)
        cpt, _why = hc.find_corner(f, (320, 240), radius=150)
        errs.append(99 if cpt is None else math.hypot(cpt[0] - 300, cpt[1] - 260))
    check("angolo della tavola sul nido d'ape, tavola dritta, storta e girata (0°, 9°, −14°, 33°, 90°): errore sotto 1,5 pixel",
          max(errs) < 1.5, [round(e, 2) for e in errs])
    cross = np.full((480, 640), 45, np.uint8)
    cv2.line(cross, (0, 236), (640, 244), 220, 5)  # due linee dritte che si attraversano (guide, il segno del puntatore)
    cv2.line(cross, (316, 0), (324, 480), 220, 5)
    cpt, _why = hc.find_corner(cv2.cvtColor(cross, cv2.COLOR_GRAY2BGR), (320, 240), radius=150)
    check("due linee che si attraversano (una croce) non sono un angolo: i bordi di un angolo finiscono lì", cpt is None,
          cpt)
    flat = cv2.cvtColor(np.full((480, 640), 180, np.uint8), cv2.COLOR_GRAY2BGR)
    check("nessun bordo vicino al mirino: nessun angolo (si usa il mirino)", hc.find_corner(flat, (320, 240))[0] is None)
    edge = np.full((480, 640), 45, np.uint8)
    edge[:, 330:] = 200
    check("un bordo solo: nessun angolo", hc.find_corner(cv2.cvtColor(edge, cv2.COLOR_GRAY2BGR), (320, 240))[0] is None)

    # ================================================================== 3. tavola
    check("lato della tavola: angolo da A a B", abs(hc.board_angle((10, 10), (110, 10 + 100 * math.tan(math.radians(7))))
                                                  - 7) < 1e-9)
    check("angoli coincidenti: rifiutati", hc.board_angle((10, 10), (10.3, 10.2)) is None)
    A = hc.align_affine((20, 30, 60, 50), (100, 100), 30, margin=5)
    corner = A[:, :2] @ [20, 30] + A[:, 2]
    t = math.radians(30)
    want = np.array([100, 100]) + np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]]) @ [5, 5]
    side = A[:, :2] @ [60, 30] + A[:, 2] - corner
    check("appoggio: l'angolo in basso a sinistra va in A + margine lungo i lati, il lato in basso segue A→B",
          np.allclose(corner, want) and abs(math.degrees(math.atan2(side[1], side[0])) - 30) < 1e-9
          and abs(np.hypot(*side) - 40) < 1e-9)

    # ================================================================== 4. mosaico (conti)
    pts = hc.mosaic_positions((0, 0, 200, 150), (60, 40), overlap=0.3)
    xs, ys = sorted({round(p[0], 6) for p in pts}), sorted({round(p[1], 6) for p in pts})
    check("posizioni del mosaico: coprono la zona con sovrapposizione",
          xs[0] - 30 <= 0 + 1e-9 and xs[-1] + 30 >= 200 - 1e-9 and ys[0] - 20 <= 0 and ys[-1] + 20 >= 150
          and max(np.diff(xs)) <= 60 * 0.95 and max(np.diff(ys)) <= 40 * 0.95, (xs, ys))
    check("zona più piccola dell'inquadratura: una foto sola al centro",
          hc.mosaic_positions((10, 10, 30, 20), (60, 40)) == [(20.0, 15.0)])

# ================================================================== 5. calibrazione sul simulatore
c = GrblController()
c.connect_port(SIM_PORT)
spin(2.0)
c.home()
spin(1.5)
c.sim.speedup = 40
prof = MachineProfile()
prof.negative_space = c.sim.negative


sent = []
c.line_sent.connect(sent.append)


def laser_s(lines):
    """Le potenze (S) dei comandi che accendono il laser o lo lasciano acceso."""
    out = []
    for ln in lines:
        u = ln.upper()
        if "S" in u and not u.startswith("$") and "M5" not in u:
            for tok in u.split():
                if tok.startswith("S"):
                    try:
                        out.append(float(tok[1:]))
                    except ValueError:
                        pass
    return out


confirms = []


def honest(cal, cam):
    """La persona guarda il video: conferma il puntino trovato solo se è davvero quello inciso."""
    def answer(p):
        L = hc.head_on_bed(c, prof)
        t = cam.true.bed_to_img(L, [cal.mark_bed])[0]
        ok = bool(np.hypot(*(np.asarray(p) - t)) < 8)
        confirms.append(ok)
        cal.confirm(ok)
    return answer


def run_cal(cam, at, power=20.0, on_click=None, cancel_at=None, guess=None, on_confirm=None):
    mx, my = prof.to_machine(*at)
    c.goto_machine(mx, my, 6000)
    spin(1.0)
    sent.clear()
    cal = hc.HeadCalibration(c, cam, prof, power, guess=guess)
    cal.need_confirm.connect(on_confirm(cal) if on_confirm else honest(cal, cam))
    res = {}
    cal.finished.connect(lambda mm, msg: res.update(m=mm, msg=msg))
    if on_click is not None:
        cal.need_click.connect(lambda _t: on_click(cal))
    else:
        cal.need_click.connect(lambda _t: cal.cancel())
    if cancel_at is not None:
        cal.progress.connect(lambda i, _n, _t: cal.cancel() if i == cancel_at else None)
    cal.start()
    until(lambda: "msg" in res, 180)
    return res.get("m"), res.get("msg", "tempo scaduto"), cal


if not BANCO:
    cases = [((150, 200), dict(angle=0, mm_per_px=0.08, offset=(0, 35)), "camera dritta, 35 mm davanti, puntino fuori "
              "dall'inquadratura (ricerca automatica)"),
             ((250, 200), dict(angle=37, mm_per_px=0.11, offset=(-12, 28)), "camera ruotata di 37°, scala diversa"),
             ((330, 120), dict(angle=180, mirror=True, offset=(30, -5)), "camera capovolta e specchiata"),
             ((80, 330), dict(angle=-90, mm_per_px=0.05, offset=(8, 9)), "camera girata di −90°, puntino nell'inquadratura")]
    for k_, (at, kw, name) in enumerate(cases):
        cam = hc.SimHeadCamera(c.sim, profile=prof, **kw)
        spin(0.3)
        mdl, msg, cal = run_cal(cam, at, power=20.0 if k_ != 1 else 35.0)
        ss = laser_s(c.job_lines)
        want_s = (20.0 if k_ != 1 else 35.0) / 100 * prof.s_max
        check(f"…il puntino è inciso alla potenza scelta ({'20' if k_ != 1 else '35'}%, mai di più)",
              ss and abs(max(ss) - want_s) < 0.6, (max(ss) if ss else None, want_s))
        check("…e il laser si spegne alla fine (M5)", c.job_lines and c.job_lines[-1].upper().startswith("M5")
              and c.sim.power == 0, c.job_lines[-2:])
        if mdl is None:
            check("calibrazione: " + name, False, msg)
        else:
            eo = float(np.hypot(*(mdl.offset - cam.true.offset)))
            em = float(np.abs(mdl.M - cam.true.M).max())
            check("calibrazione: " + name + f" (scostamento ±{eo:.3f} mm)", eo < 0.1 and em < 0.002
                  and mdl.mirrored() == cam.true.mirrored() and abs(mdl.k) < 0.005, (eo, em, mdl.k, msg))
            L = hc.head_on_bed(c, prof)
            check("…alla fine il puntino inciso è sotto il mirino", np.hypot(*(mdl.center(L) - np.array(at))) < 0.1,
                  mdl.center(L))
        cam.close()

    # prova sul B1 vero (15/11): camera 60 mm a destra dell'ugello, fotogrammi in ritardo. Prima un cambiamento
    # dell'immagine era stato preso per il puntino; ora le foto si fanno a immagine ferma e il puntino si conferma
    for guess in (None, (55.0, 5.0)):
        cam = hc.SimHeadCamera(c.sim, profile=prof, offset=(60, 0), mm_per_px=0.079, angle=1.2, lag=0.6)
        spin(0.8)
        confirms.clear()
        mdl, msg, _cal = run_cal(cam, (100, 390) if guess is None else (300, 390), guess=guess)
        check("camera 60 mm a destra dell'ugello con fotogrammi in ritardo di 0,6 s" + (" e distanza indicativa 55, 5 mm"
              if guess else "") + ": calibrata giusta, puntino confermato dalla persona",
              mdl is not None and np.hypot(*(mdl.offset - cam.true.offset)) < 0.1 and confirms == [True], (msg, confirms))
        if guess:
            L0 = np.array(_cal.mark_bed)
            check("…con la distanza indicativa la prima foto «prima del puntino» è già con la camera sopra il punto "
                  "da incidere (testa spostata dalla parte opposta alla camera)",
                  np.hypot(*(np.array(_cal.before_at[0]) - (L0 - np.array(guess)))) < 0.05
                  and _cal.before_at[0][0] < L0[0], (_cal.before_at[:2], L0))
        cam.close()
    # lenti grandangolari (M12): a barile, molto a barile, a cuscino
    for k_true, at in ((-0.2, (60, 60)), (-0.35, (390, 60)), (0.12, (390, 210))):
        cam = hc.SimHeadCamera(c.sim, profile=prof, offset=(25, 10), mm_per_px=0.08, angle=15, k=k_true,
                               size=(800, 450))
        spin(0.5)
        mdl, msg, _cal = run_cal(cam, at, guess=(25, 10))
        ok = mdl is not None
        if ok:
            Lt = np.array([200.0, 200.0])
            pxs = np.column_stack([rng.uniform(0, 800, 300), rng.uniform(0, 450, 300)])
            err = float(np.linalg.norm(mdl.img_to_bed(Lt, pxs) - cam.true.img_to_bed(Lt, pxs), axis=1).max())
            plain = float(np.linalg.norm(hc.HeadModel(mdl.M, mdl.offset, mdl.frame_size).img_to_bed(Lt, pxs)
                                         - cam.true.img_to_bed(Lt, pxs), axis=1).max())
        check(f"lente {'a barile' if k_true < 0 else 'a cuscino'} ({k_true * 100:+.0f}% ai bordi): misurata e "
              "corretta, errore su tutta l'immagine sotto 0,3 mm (senza correzione: diversi mm)",
              ok and abs(mdl.k - k_true) < 0.03 and err < 0.3 and plain > 2.0
              and np.hypot(*(mdl.offset - cam.true.offset)) < 0.1, (msg, ok and (mdl.k, err, plain)))
        cam.close()

    # la persona dice «non è lui»: sposta la testa e fa clic sul puntino
    cam = hc.SimHeadCamera(c.sim, profile=prof, angle=-8, mm_per_px=0.08, offset=(20, 25))
    spin(0.3)
    said = []

    def no_then(cal):
        def answer(_p):
            said.append("no")
            cal.confirm(False)
        return answer

    def jog_and_click(cal):
        tgt = cam.true.head_for_camera(cal.mark_bed) + [-4.0, 2.0]
        mx, my = prof.to_machine(*tgt)
        c.goto_machine(mx, my, 3000)
        spin(1.5)
        L = hc.head_on_bed(c, prof)
        u, v = cam.true.bed_to_img(L, [cal.mark_bed])[0]
        said.append("clic")
        cal.click(u - 1.0, v + 2.0)

    mdl, msg, _cal = run_cal(cam, (120, 120), on_confirm=no_then, on_click=jog_and_click)
    check("«No, non è il puntino»: la persona lo indica con un clic e la calibrazione riesce",
          said == ["no", "clic"] and mdl is not None and np.hypot(*(mdl.offset - cam.true.offset)) < 0.1, (said, msg))
    cam.close()

    # materiale senza trama: la ricerca automatica non si può fare, il puntino lo indica la persona
    cam = hc.SimHeadCamera(c.sim, profile=prof, angle=12, mm_per_px=0.07, offset=(0, 40))
    cam.material[:] = 180
    spin(0.3)
    asked = []

    def user(cal):
        asked.append(1)
        L = hc.head_on_bed(c, prof)
        tgt = cam.true.head_for_camera(cal.mark_bed) + [3.0, -2.0]  # la persona porta il puntino nell'inquadratura
        mx, my = prof.to_machine(*tgt)
        c.goto_machine(mx, my, 3000)
        spin(1.5)
        L = hc.head_on_bed(c, prof)
        u, v = cam.true.bed_to_img(L, [cal.mark_bed])[0]
        cal.click(u + 2.0, v - 1.5)  # il clic non è mai preciso

    mdl, msg, _cal = run_cal(cam, (200, 300), on_click=user)
    check("materiale senza trama, puntino fuori dall'inquadratura: lo chiede, la persona fa clic, calibra lo stesso",
          asked and mdl is not None and np.hypot(*(mdl.offset - cam.true.offset)) < 0.1, msg)
    mdl, msg, _cal = run_cal(cam, (300, 300))
    check("…se invece la persona annulla: niente calibrazione e laser spento",
          mdl is None and "annullata" in msg.lower() and c.sim.power == 0, (msg, c.sim.power))
    check("…e all'annullamento parte comunque lo spegnimento del laser (M5 S0)", sent and sent[-1].upper() == "M5 S0",
          sent[-3:])
    cam.close()

    cam = hc.SimHeadCamera(c.sim, profile=prof)
    spin(0.3)
    n0 = len(c.sim.burn_marks)
    mdl, msg, _cal = run_cal(cam, (380, 60), cancel_at=0)
    check("annulla all'inizio: niente inciso, niente calibrazione", mdl is None and len(c.sim.burn_marks) == n0, msg)
    check("niente file salvato da una calibrazione annullata", not os.path.exists(hc.head_file()))
    cam.close()

# ================================================================== 6–8. interfaccia
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

c.disconnect_port()
spin(0.5)
w = MainWindow()
w.show()
spin(1.0)
card = w.camera.head
check("pannello Camera: riquadro «Camera della testa» con scelta, stato e pulsanti",
      card is not None and card.combo.count() >= 1 and not card.btn_view.isEnabled() and card.btn_cal.isEnabled())
# (0.20.3: «Calibra» si può sempre premere e dice che cosa manca: vedi test_v203_telecamere)
check("menu Laser → Vista della testa… e Impostazioni → Camera della testa…",
      w.acts["head_cam"] in w.m_laser.actions() and w.acts["head_cam_setup"] in w.m_settings.actions())
check("il riquadro della camera della testa non è più nel pannello Camera", w.camera.isAncestorOf(card) is False)
w.head_camera_window()
dlg_ = getattr(w, "_head_setup_dlg", None)
check("senza camera della testa scelta: la vista apre Impostazioni → Camera della testa e lo dice",
      dlg_ is not None and dlg_.isVisible() and dlg_.isAncestorOf(card) and "Impostazioni" in w.statusBar().currentMessage())
dlg_.close()

# 7. scelta delle telecamere (elenco finto: due telecamere USB)
fake = [(0, "Camera 0  ·  1920×1080", (1920, 1080), np.zeros((90, 160, 3), np.uint8)),
        (1, "Camera 1  ·  1920×1080", (1920, 1080), np.zeros((90, 160, 3), np.uint8))]


class FakeSrc:
    def __init__(self, idx, size=(1280, 720)):
        self.index, self.mode, self.black, self.size = idx, "dshow", False, size
        self.closed = False

    def get(self, after=0, timeout=0):
        return np.full((self.size[1], self.size[0], 3), 120, np.uint8)

    def frames(self, n=3, after=0):
        return [self.get() for _ in range(n)]

    def close(self):
        self.closed = True


opened = []
orig_cs = camera.CameraSource


def fake_cs(idx, *a, **k):
    opened.append((idx, k.get("size")))
    return FakeSrc(idx, k.get("size") or (1920, 1080))


import freelasercut.camera_panel as cp  # noqa: E402
import freelasercut.head_camera_ui as hcu  # noqa: E402

cp.CameraSource = fake_cs
hcu.CameraSource = fake_cs
panel = w.camera
w.qs.setValue("camera_choice", 0)
w.qs.setValue("head_camera_choice", 1)
panel.on_found(list(fake))
spin(0.3)
check("piano e testa: la camera 0 sul piano, la camera 1 sulla testa (aperta a 1280 × 720)",
      panel.bed_index() == 0 and card.index() == 1 and (1, hc.HEAD_SIZE) in opened, (panel.bed_index(), card.index(), opened))
i1 = card.combo.findData(0)
item = card.combo.model().item(i1)
# 0.20.3 (Ale, 15/11): le telecamere si scelgono sempre; quella già usata dall'altro compito passa di qua
check("nell'elenco della testa la camera del piano c'è, si riconosce e si può scegliere", i1 > 0 and item.isEnabled()
      and tr("ora camera del piano") in card.combo.itemText(i1))
j = panel.combo.findData(1)
check("nell'elenco del piano la camera della testa c'è, si riconosce e si può scegliere", j > 0
      and panel.combo.model().item(j).isEnabled() and tr("ora camera della testa") in panel.combo.itemText(j))
bed_src = panel.src
card.combo.setCurrentIndex(i1)
card._chosen(i1)
check("scelta per la testa la camera del piano: passa alla testa (sul piano si chiude: mai aperta due volte)",
      card.index() == 0 and panel.bed_index() is None and bed_src.closed, (card.index(), panel.bed_index()))
head_src = card.src
j0 = panel.combo.findData(0)
panel.combo.setCurrentIndex(j0)
check("e la camera della testa scelta per il piano: passa al piano (sulla testa si chiude)",
      panel.bed_index() == 0 and card.index() is None and head_src.closed, (panel.bed_index(), card.index()))
k = card.combo.findData(1)
card.combo.setCurrentIndex(k)
card._chosen(k)
check("la camera della testa riscelta: ricordata", w.qs.value("head_camera_choice") in (1, "1"))
card.combo.setCurrentIndex(0)
card._chosen(0)
check("«Nessuna camera sulla testa»: chiusa e ricordata", card.src is None and w.qs.value("head_camera_choice") == "none")
cp.CameraSource = orig_cs
hcu.CameraSource = orig_cs

# 8. ricerca bloccata e telecamera collegata dopo l'avvio
panel._searching = True
panel._search_t0 = time.time() - 60
panel.tick()
check("ricerca delle telecamere che non risponde: la scritta non resta per sempre e ⟳ torna a funzionare",
      not panel._searching and "⟳" in panel.state.text(), panel.state.text())
calls = []
orig_search = panel.search
panel.search = lambda manual=False: calls.append(manual)
panel._dev_seen, panel._dev_n, panel._dev_t, panel._dev_busy = 1, 2, 0.0, False
orig_count = camera.device_count
camera.device_count = lambda: 2
panel._watch_devices()
check("una telecamera in più nel sistema: la ricerca riparte da sola", calls == [True], calls)
panel._dev_t = 0.0
panel._watch_devices()
check("…una volta sola", calls == [True], calls)
spin(0.2)
camera.device_count = orig_count
panel.search = orig_search

# 6. comandi sul simulatore
w.ctl.connect_port(SIM_PORT)
spin(3.0)
w.ctl.home()
until(lambda: w.ctl.homed, 20)
spin(1.0)
w.ctl.sim.speedup = 40
cam = hc.SimHeadCamera(w.ctl.sim, profile=w.profile, angle=20, mm_per_px=0.09, offset=(5, 30),
                       board=[(100, 100), (300, 100 + 200 * math.tan(math.radians(6))),
                              (300 - 150 * math.sin(math.radians(6)), 100 + 200 * math.tan(math.radians(6)) + 150),
                              (100 - 150 * math.sin(math.radians(6)), 250)] if not BANCO else None)
card.set_source(cam)
spin(0.5)
check("camera della testa aperta ma non calibrata: si dice di calibrarla", "calibrata" in card.state.text().lower()
      and card.btn_cal.isEnabled() and card.btn_view.isEnabled(), card.state.text())
check("senza calibrazione i comandi che muovono la testa non partono", card.laser_to_camera() is None
      and "Calibra" in w.statusBar().currentMessage())
w.goto_bed(200, 175)  # sulla tavola chiara: sul nido d'ape scuro il puntino non si vedrebbe
until(lambda: hc.head_on_bed(w.ctl, w.profile) is not None and abs(hc.head_on_bed(w.ctl, w.profile)[0] - 200) < 0.01, 20)
spin(0.5)
win = card.open_window()
check("vista della testa: si apre", win is not None and win.isVisible())
from PySide6.QtWidgets import QDialog  # noqa: E402

dlg = hcu.HeadCalDialog(card, 20)
pad = dlg.pad
pad.set_direction("r")
pad.cm.setValue(6.0)
check("prima della calibrazione si chiede dov'è la camera: freccia → e 6 cm = 60 mm a destra; la frase dice che il "
      "puntino starà a sinistra", pad.guess() == (60.0, 0.0) and "a sinistra rispetto alla camera" in pad.text.text()
      and pad.buttons["r"].isChecked() and not pad.buttons[""].isChecked(), pad.text.text())
pad.set_direction("u")
pad.cm.setValue(4.0)
check("…freccia ↑ e 4 cm = 40 mm verso l'alto del piano; il puntino starà in basso",
      pad.guess() == (0.0, 40.0) and "in basso rispetto alla camera" in pad.text.text())
check("…la scelta si ricorda", w.qs.value("head_camera_where") == "u;4")
check("…e la finestrella dice dove va il cartone (0.20.2: calibrazione completa)", "Il cartone va" in dlg.where.text()
      and dlg.buttons.button(hcu.QDialogButtonBox.Ok).isEnabled(), dlg.where.text())
pad.set_direction("")
check("…● = non lo so: nessuna indicazione e distanza spenta", pad.guess() is None and not pad.cm.isEnabled()
      and w.qs.value("head_camera_where") == "")
dlg.close()
hcu.HeadCalDialog.exec = lambda self: QDialog.Accepted  # «Inizia» con quello che c'è nella finestrella
card.calibrate(25)
until(lambda: card.cal is None, 200)
mdl = card.model
check("calibrazione dalla finestra: riuscita, salvata, testo con i risultati", mdl is not None
      and os.path.exists(hc.head_file()) and np.hypot(*(mdl.offset - cam.true.offset)) < 0.1
      and "mm per pixel" in win.cal_text.text(), win.cal_text.text())
check("stato del riquadro: calibrata", "✓" in card.state.text())

# testa troppo vicina al bordo per quella camera: prima di incidere la testa va in un punto che la camera raggiunge
w.goto_bed(200, 8)
until(lambda: np.hypot(*(hc.head_on_bed(w.ctl, w.profile) - (200, 8))) < 0.05, 20)
spin(0.5)


def pick_up_3cm(self):
    self.pad.set_direction("u")
    self.pad.cm.setValue(3.0)
    return QDialog.Accepted


hcu.HeadCalDialog.exec = pick_up_3cm
saved_model = card.model
started = card.calibrate()
here = hc.head_on_bed(w.ctl, w.profile)
# 0.20.2: con la calibrazione completa il margine comprende la griglia e le sue foto (START_MARGIN + 60)
want_start = hc.calibration_start((200, 8), (0, 30), (w.profile.bed_x, w.profile.bed_y), margin=hc.START_MARGIN + 60)[0]
check("camera 3 cm in alto e testa a 8 mm dal bordo davanti: la testa va prima in un punto da cui la camera arriva a "
      "fotografare tutta la griglia, poi parte la calibrazione", started is not None and want_start[1] > 60
      and np.hypot(*(here - want_start)) < 0.05, (here, want_start))
card.cancel()
until(lambda: card.cal is None, 60)
check("…annullata subito: niente inciso e la calibrazione di prima resta", card.model is saved_model
      and w.ctl.sim.power == 0)
hcu.HeadCalDialog.exec = lambda self: QDialog.Accepted
spin(0.5)
L = card.head()
until(lambda: w.canvas.cam_center() is not None, 5)
cc_ = w.canvas.cam_center()
check("sul piano il segno della camera della testa è nel punto sotto il mirino", cc_ is not None
      and math.hypot(cc_.x() - mdl.center(L)[0], cc_.y() - mdl.center(L)[1]) < 0.05)


def at(p, t=15.0):
    return until(lambda: np.hypot(*(hc.head_on_bed(w.ctl, w.profile) - np.asarray(p))) < 0.01
                 and w.ctl.last_status.get("state") == "Idle", t)


card.laser_to_camera()
check("«Laser sul centro camera»: il laser va dove c'era il mirino", at(mdl.center(L)))
card.camera_to_laser()
check("«Camera sul punto del laser»: la testa torna dove il mirino guarda il punto del laser", at(L))
card.camera_to(200, 220)
check("«Camera qui»: il mirino sul punto chiesto", at(mdl.head_for_camera((200, 220))))
card.camera_to(440, 5)
check("camera vicino al bordo: la testa si ferma al bordo e si dice quanto manca",
      at(hc.clamp_to_bed(w.profile, *mdl.head_for_camera((440, 5)))) and "non arriva" in w.statusBar().currentMessage(),
      w.statusBar().currentMessage())
card.camera_to(200, 220)
at(mdl.head_for_camera((200, 220)))
line = card.origin_from_camera()
spin(1.0)
o = w.work_origin_on_bed()
check("«Origine qui (centro camera)»: l'origine utente è sul punto sotto il mirino", line and math.hypot(o[0] - 200, o[1] - 220) < 0.02, (line, o))
okc = True
for inv_x, inv_y, rot in ((True, False, 0), (False, True, 1), (True, True, 3)):
    p2 = MachineProfile()
    p2.invert_x, p2.invert_y = inv_x, inv_y
    p2.set_view_rot(rot)
    m0 = p2.to_machine(150, 120)
    dm = p2.to_machine_delta(*mdl.offset)
    okc &= np.allclose(p2.to_bed(m0[0] + dm[0], m0[1] + dm[1]), np.array([150, 120]) + mdl.offset, atol=1e-9)
check("origine dalla camera giusta anche con assi invertiti e piano ruotato (stesso conto dello scostamento)", okc)
w.ctl._job_active = True
hb = hc.head_on_bed(w.ctl, w.profile)
r_ = card.laser_to_camera()
msg_ = w.statusBar().currentMessage()
w.ctl._job_active = False
spin(0.6)
check("durante un lavoro i comandi della camera della testa non muovono la testa", r_ is None
      and np.hypot(*(hc.head_on_bed(w.ctl, w.profile) - hb)) < 1e-6 and "lavoro" in msg_,
      (r_, hc.head_on_bed(w.ctl, w.profile), hb, msg_))
keys = w.context_menu_keys(w.canvas.to_view(QPointF(250, 150)))
check("menu del tasto destro (Classica): «Porta il laser qui» e «Porta la camera della testa qui»",
      "laser_here" in keys and "head_camera_here" in keys and "head_laser_here" not in keys, keys)
w.canvas.cursor_bed = QPointF(250, 150)
w.head_here("camera")
check("…«Porta la camera della testa qui» dal menu", at(mdl.head_for_camera((250, 150))))
w.head_here("laser")
check("…«Porta il laser qui» dal menu", at((250, 150)))
win.tick()
check("vista: immagine, righello e mirino (nessun errore nel disegno)", win.view.frame is not None
      and win.view.model is not None and win.view.grab() is not None)
from PySide6.QtGui import QTransform  # noqa: E402

rect = RectShape(20.0, 20.0)
rect.set_transform(QTransform.fromTranslate(240.0, 140.0))
w.editor.add([rect])
spin(0.2)
win.tick()
check("vista: il disegno vicino alla zona inquadrata compare sul video", len(win.view.shapes) >= 1 or BANCO,
      len(win.view.shapes))
u, v = mdl.bed_to_img(hc.head_on_bed(w.ctl, w.profile), [(255, 152)])[0]
win._clicked(u, v)
check("clic sul video: quel punto va sotto il mirino", at(mdl.head_for_camera((255, 152))))

if not BANCO:
    # fase 2: tavola da due angoli (la tavola simulata ha l'angolo A in (100, 100) e il lato a 6°)
    A_true = np.array([100.0, 100.0])
    B_true = np.array([300.0, 100 + 200 * math.tan(math.radians(6))])
    card.camera_to(*(A_true + [3, 2]))
    at(mdl.head_for_camera(A_true + [3, 2]))
    spin(0.5)
    a = card.take_corner(0, auto=True)
    check("angolo A: trovato nell'immagine vicino al mirino (errore sotto 0,3 mm)",
          a is not None and np.hypot(*(np.array(a) - A_true)) < 0.3, a)
    card.camera_to(*(B_true + [-4, 3]))
    at(mdl.head_for_camera(B_true + [-4, 3]))
    spin(0.5)
    b = card.take_corner(1, auto=True)
    ang = card.board_angle()
    check("angolo B e lato A→B: inclinazione della tavola 6° (errore sotto 0,15°)", ang is not None and abs(ang - 6) < 0.15,
          ang)
    check("la tavola si vede sul piano (segni e lati)", w.canvas.board_shown())
    c_mid = (200, 200)
    card.camera_to(*c_mid)
    at(mdl.head_for_camera(c_mid))
    spin(0.5)
    a2 = card.take_corner(0, auto=True)
    check("in mezzo alla tavola (nessun angolo vicino): vale il mirino e si dice", a2 is not None
          and np.hypot(*(np.array(a2) - c_mid)) < 0.05 and "mirino" in w.statusBar().currentMessage())
    card.board[0] = tuple(a)
    w.editor.select([s for s in w.editor.doc.shapes][:1])
    sel = w.editor.selection
    if sel:
        before_b = w.editor.selection_bounds()
        A2 = card.align_selection(margin=5.0)
        s0 = sel[0]
        pts = [(q.x(), q.y()) for poly in s0.path().toSubpathPolygons() for q in poly]
        t = math.radians(ang)
        R = np.array([[math.cos(t), math.sin(t)], [-math.sin(t), math.cos(t)]])  # piano → riferimento della tavola
        loc = (np.array(pts) - np.array(a)) @ R.T
        check("«Appoggia la selezione sulla tavola»: ruotata come la tavola, angolo in A + 5 mm lungo i lati",
              A2 is not None and np.allclose(loc.min(axis=0), (5, 5), atol=1e-6)
              and np.allclose(loc.max(axis=0) - loc.min(axis=0), (20, 20), atol=1e-6), loc.min(axis=0))
        w.editor.undo()
        after_b = w.editor.selection_bounds() if w.editor.selection else sel[0].bounds()
        check("…con un solo Annulla torna com'era", abs(after_b.left() - before_b.left()) < 1e-6
              and abs(after_b.top() - before_b.top()) < 1e-6)
    else:
        check("«Appoggia la selezione sulla tavola»", False, "nessuna forma")
    card.clear_board()
    check("«Togli la tavola»: niente più segni", not w.canvas.board_shown() and card.board_angle() is None)

    # fase 3: foto a mosaico della zona attorno alla selezione
    w.editor.select([s for s in w.editor.doc.shapes][:1])
    shots = []
    job = card.take_mosaic("selection")
    check("foto a mosaico: parte (laser spento)", job is not None)
    until(lambda: card.job is None, 120)
    img = getattr(panel, "mosaic", None)
    pp = job.mosaic.ppm  # 0.20.2: 4 pixel per mm (prima 2)
    ok_m = img is not None and img.shape[:2] == (int(round(w.profile.bed_y * pp)), int(round(w.profile.bed_x * pp)))
    # confronto con il materiale vero della camera simulata, nella zona fotografata
    err = 99.0
    if ok_m:
        z = card.mosaic_zone("selection")
        x0, y0, x1, y1 = [int(v * pp) for v in z]
        H = int(round(w.profile.bed_y * pp))
        mine = cv2.cvtColor(img[H - y1:H - y0, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
        truth = cv2.resize(cam.material, (int(round(w.profile.bed_x * pp)), H), interpolation=cv2.INTER_AREA)
        truth = cv2.cvtColor(truth[H - y1:H - y0, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
        res = cv2.matchTemplate(mine[10:-10, 10:-10], truth, cv2.TM_CCOEFF_NORMED)
        _a, sc, _b, loc_ = cv2.minMaxLoc(res)
        err = math.hypot(loc_[0] - 10, loc_[1] - 10) / pp
    check("foto a mosaico sotto il piano: coincide con il materiale vero (spostamento sotto 0,5 mm)",
          ok_m and err < 0.5 and job.mosaic.count >= 1, (err, getattr(job, "skipped", None)))
    check("…e nessun puntino inciso durante la foto", w.ctl.sim.power == 0)

card.close_src()
spin(0.3)
check("camera della testa chiusa: il segno sul piano sparisce", w.canvas.cam_center() is None)
w.ctl.disconnect_port()
spin(0.5)
keys = w.context_menu_keys(w.canvas.to_view(QPointF(250, 150)))
check("macchina scollegata: nel menu del tasto destro niente voci della camera della testa",
      "laser_here" not in keys and "head_camera_here" not in keys, keys)

# ================================================================== 9. traduzioni
import ast  # noqa: E402

texts = set()
for f in ("head_camera.py", "head_camera_ui.py"):
    tree = ast.parse(open(os.path.join(ROOT, "freelasercut", f), encoding="utf-8").read())
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "tr" and n.args and isinstance(n.args[0], ast.Constant):
            texts.add(n.args[0].value)
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    miss = [t for t in texts if t not in cat]
    import re  # noqa: E402

    bad = [t for t in texts if t in cat and sorted(re.findall(r"\{\d[^}]*\}", t)) != sorted(re.findall(r"\{\d[^}]*\}", cat[t]))]
    check(f"traduzioni {lang}: tutti i testi della camera della testa, con gli stessi segnaposto", not miss and not bad,
          (miss[:3], bad[:3]))
check("nessun errore nascosto nei comandi dell'interfaccia", not hidden, hidden[:3])
w.editor.dirty = False
w.close()
print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(0 if all(results) else 1)
