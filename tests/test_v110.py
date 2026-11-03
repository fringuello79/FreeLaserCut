# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.11.0: guardia fiamme (spenta di partenza), taratura da foto del test materiale (riferimenti agli
angoli, lettura della foto anche storta o specchiata) e controllo dal telefono (pagina sulla rete di casa:
avanzamento, camera, Pausa, Stop, invio della foto del test; niente avvio né ripresa)."""
import sys, os, time, tempfile, json, glob, urllib.request, urllib.error
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import cv2
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
warned = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
from freelasercut import fire_guard as fg, phone, diag
from freelasercut.core import material_test as mt, test_photo as tp
from freelasercut.profile import MachineProfile
from freelasercut import gcode_preview
from freelasercut.grbl import SIM_PORT

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()

# ================================================================== guardia fiamme: riconoscimento
rng = np.random.default_rng(3)
def bed(dot=True, lamp=False):
    img = np.full((480, 640, 3), (70, 95, 120), np.uint8)
    img = cv2.add(img, rng.integers(0, 20, img.shape, dtype=np.uint8))
    if dot:  # puntino del laser con un po' di brace
        cv2.circle(img, (300, 240), 4, (200, 220, 255), -1)
        cv2.circle(img, (300, 240), 2, (255, 255, 255), -1)
    if lamp:  # lampada calda sempre presente nell'inquadratura
        cv2.rectangle(img, (560, 20), (600, 50), (60, 170, 255), -1)
    return img
def flame(img, r=30, at=(320, 220)):
    img = img.copy()
    cv2.ellipse(img, at, (r // 2, r), 0, 0, 360, (0, 140, 255), -1)
    cv2.ellipse(img, (at[0], at[1] + r // 3), (r // 4, r // 2), 0, 0, 360, (150, 240, 255), -1)
    return img

d = fg.FlameDetector("media")
alarms = [d.update(bed())["alarm"] for _ in range(40)]
check("legno con il puntino del laser per 40 fotogrammi: nessun allarme", not any(alarms))
d = fg.FlameDetector("media")
for _ in range(8):
    d.update(bed())
seq = [d.update(flame(bed()))["alarm"] for _ in range(4)]
check("fiamma che resta: allarme al terzo fotogramma di fila", seq == [False, False, True, True], seq)
d = fg.FlameDetector("media")
for _ in range(8):
    d.update(bed())
flash = [d.update(flame(bed()) if i == 3 else bed())["alarm"] for i in range(10)]
check("una scintilla di un solo fotogramma non ferma il lavoro", not any(flash))
small = flame(bed(), r=20)
hi, lo = fg.FlameDetector("alta"), fg.FlameDetector("bassa")
for _ in range(8):
    hi.update(bed()); lo.update(bed())
a_hi = [hi.update(small)["alarm"] for _ in range(4)]
a_lo = [lo.update(small)["alarm"] for _ in range(4)]
check("fiammella piccola: la vede la sensibilità alta, non la bassa", a_hi[-1] and not a_lo[-1],
      f"{fg.hot_fraction(small) * 100:.3f}%")
d = fg.FlameDetector("media")
lamp_seq = [d.update(bed(lamp=True))["alarm"] for _ in range(30)]
check("lampada calda sempre in vista: imparata all'inizio, nessun allarme", not any(lamp_seq),
      f"soglia {d.threshold() * 100:.2f}%")
seq = [d.update(flame(bed(lamp=True), r=40))["alarm"] for _ in range(4)]
check("…ma una fiamma vera in più scatta lo stesso", seq[-1])
d = fg.FlameDetector("media")
big = [d.update(flame(bed(), r=60))["alarm"] for _ in range(4)]
check("fiamma già grande dal primo fotogramma: non viene presa per «normale»", big[-1])
check("sensibilità sconosciuta: si usa la media", fg.FlameDetector("boh").sensitivity == "media")

# ================================================================== taratura da foto: test con i riferimenti
prof = MachineProfile()
base = mt.TestSpec()
check("test senza riferimenti: G-code uguale a prima (opzione spenta di partenza)",
      base.markers is False and mt.build(base, prof).lines == mt.build(mt.TestSpec(markers=False), prof).lines)
line = mt.TestSpec(mode="line", markers=True)
check("test di taglio: i riferimenti non si incidono", mt.build(line, prof).lines == mt.build(mt.TestSpec(mode="line"), prof).lines)
spec = mt.TestSpec(markers=True, title="Tiglio")
job = mt.build(spec, prof)
L = mt.layout(spec)
check("test con riferimenti: quattro riferimenti incisi, dentro il piano", [l.name for l in job.layers] == ["celle", "riferimenti"]
      and job.layers[1].items == 4 and not job.warnings, [(l.name, l.items) for l in job.layers])
xa, ya, xb, yb = L.outer
b = job.bounds
check("i riferimenti stanno agli angoli, fuori dalla griglia e dalle etichette",
      abs(b.left() - xa) < 0.2 and abs(b.right() - xb) < 0.2 and L.gx0 - L.lab - 3 >= xa + mt.MARK and
      L.y0c - 4 >= ya + mt.MARK, f"{L.outer} griglia {L.gx0:.1f},{L.gy0:.1f}")
check("riferimenti: quattro disegni diversi (6 × 6 quadretti con bordo pieno)",
      len({str(mt.marker_bits(i)) for i in range(4)}) == 4 and all(all(mt.marker_bits(0)[0]) for _ in [0]))
mp_, ms_ = mt.marker_settings(spec)
check("riferimenti incisi scuri ma non col quadrato più bruciato", mp_ <= spec.p_max and ms_ >= spec.s_min and
      (mp_, ms_) != (spec.p_max, spec.s_min), (mp_, ms_))

# foto sintetica: incisione simulata dal G-code vero (energia → scuro), poi prospettiva e specchio
pv = gcode_preview.parse(job.lines, profile=prof)
B = pv.segs[pv.segs[:, 5] > 0]
k = 8.0
W, H = int(160 * k), int(140 * k)
energy = np.zeros((H, W))
for x0, y0, x1, y1, s, _, f in B:
    e = (s / prof.s_max * 100) / max(f, 1)
    cv2.line(energy, (int(x0 * k), int(H - y0 * k)), (int(x1 * k), int(H - y1 * k)), float(e), max(1, int(0.1 * k) + 1))
dk = 1 - np.exp(-energy * 350)
wood, burnt = np.array([150, 190, 225.]), np.array([30, 40, 55.])
flat = np.clip(wood * (1 - dk[..., None]) + burnt * dk[..., None] + rng.normal(0, 4, (H, W, 3)), 0, 255).astype(np.uint8)
P = cv2.getPerspectiveTransform(np.float32([[0, 0], [W, 0], [W, H], [0, H]]),
                                np.float32([[60, 30], [W - 10, 90], [W - 90, H - 20], [20, H - 60]]))
persp = cv2.warpPerspective(flat, P, (W, H), borderValue=(90, 90, 90))
# scuro atteso per ogni quadrato (stesso modello, energia del quadrato)
powers = mt._steps(spec.p_min, spec.p_max, spec.rows)
speeds = mt._steps(spec.s_min, spec.s_max, spec.cols)
r_ref = tp.analyze(flat, spec)
check("foto dritta: quattro riferimenti trovati", r_ref.found == [0, 1, 2, 3] and not r_ref.mirrored)
mono = all(r_ref.dark[r, c] <= r_ref.dark[r + 1, c] + 0.02 for r in range(spec.rows - 1) for c in range(spec.cols)) and \
    all(r_ref.dark[r, c] + 0.02 >= r_ref.dark[r, c + 1] for r in range(spec.rows) for c in range(spec.cols - 1))
check("più potenza = più scuro, più velocità = più chiaro", mono, np.round(r_ref.dark, 2).tolist())
r_p = tp.analyze(persp, spec)
r_m = tp.analyze(cv2.flip(persp, 1), spec)
check("foto storta in prospettiva: stessi valori (±0,03)", np.abs(r_p.dark - r_ref.dark).max() < 0.03,
      f"{np.abs(r_p.dark - r_ref.dark).max():.3f}")
check("foto specchiata (selfie): riconosciuta e corretta", r_m.mirrored and np.abs(r_m.dark - r_ref.dark).max() < 0.03)
small_photo = cv2.resize(persp, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
check("foto più piccola (≈ 5 pixel per mm): si legge ancora", np.abs(tp.analyze(small_photo, spec).dark - r_ref.dark).max() < 0.05)
hide = persp.copy()
_, mx3, my3 = L.marks[3]
quad = np.float32([[[(mx3 - 1) * k, H - (my3 - 1) * k]], [[(mx3 + mt.MARK + 1) * k, H - (my3 + mt.MARK + 1) * k]]])
(qa, qb) = cv2.perspectiveTransform(quad, P).reshape(2, 2)
cv2.rectangle(hide, (int(min(qa[0], qb[0])), int(min(qa[1], qb[1]))), (int(max(qa[0], qb[0])), int(max(qa[1], qb[1]))),
              (150, 190, 225), -1)
try:
    r_h = tp.analyze(hide, spec)
    ok3 = len(r_h.found) == 3 and np.abs(r_h.dark - r_ref.dark).max() < 0.04
except tp.PhotoError as ex:
    ok3 = False
check("un riferimento coperto: bastano gli altri tre", ok3)
sc = r_ref.best("scura")
li = r_ref.best("leggera")
fo = r_ref.best("foto")
dmax = r_ref.dark.max()
check("proposta «incisione scura»: quasi il massimo del nero con meno energia possibile",
      sc and r_ref.dark[sc.cell] >= 0.9 * dmax and all(
          powers[r] / speeds[c] >= powers[sc.cell[0]] / speeds[sc.cell[1]] - 1e-12
          for r in range(spec.rows) for c in range(spec.cols) if r_ref.dark[r, c] >= 0.9 * dmax), sc and (sc.power, sc.speed))
check("proposta «incisione leggera»: tono a metà", li and 0.25 * dmax <= r_ref.dark[li.cell] <= 0.7 * dmax,
      li and r_ref.dark[li.cell])
check("proposta «foto»: potenza minima < massima, alla stessa velocità", fo and fo.power_min < fo.power and
      fo.speed in [round(s) for s in speeds], fo and (fo.power_min, fo.power, fo.speed))
try:
    tp.analyze(np.full((600, 800, 3), 180, np.uint8), spec)
    err = ""
except tp.PhotoError as ex:
    err = str(ex)
check("foto senza riferimenti: messaggio chiaro con i consigli", "riferimenti" in err and "dall'alto" in err, err[:80])
try:
    tp.analyze(flat, mt.TestSpec(markers=False))
    err = ""
except tp.PhotoError as ex:
    err = str(ex)
check("griglia senza riferimenti: spiega come incidere il test giusto", "Riferimenti per leggere la foto" in err)

# ================================================================== finestra principale
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui import dialogs_testphoto
w = MainWindow()
laser_menu = [m for m in w.menuBar().actions() if m.menu() and w.acts["material_test"] in m.menu().actions()][0].menu()
check("Laser → Guardia fiamme e Controllo dal telefono", w.acts["fire_guard"] in laser_menu.actions() and
      w.acts["phone"] in laser_menu.actions())
check("guardia fiamme spenta di partenza", w.fire.enabled() is False)
check("controllo dal telefono spento di partenza", w.phone.running is False)

# --- test materiale: riferimenti, ricordo della griglia, lettura della foto
mtd = w.material_test()
check("Test materiale: casella «Riferimenti per leggere la foto» (spenta di partenza)", not mtd.markers.isChecked()
      and mtd.markers.isEnabled() and mtd.b_photo.isEnabled())
mtd.mode.setCurrentIndex(1)
check("con il test di taglio la lettura della foto non c'è", not mtd.markers.isEnabled() and not mtd.b_photo.isEnabled())
mtd.mode.setCurrentIndex(0)
mtd.title.setText("Tiglio")
mtd.markers.setChecked(True)
seen = []
w._test_job_action = lambda kind, job, name: seen.append((kind, job))
mtd._emit("save")
mtd.p_max.setValue(60)  # cambiato dopo aver inciso: per leggere la foto vale la griglia incisa
check("la griglia incisa si ricorda (per leggere la foto più tardi)", mtd.photo_spec() == spec, mtd.photo_spec())
res = mtd.analyze_image(persp)
check("foto letta: la finestra torna alla griglia incisa e mostra il risultato", res is not None and
      mtd.p_max.value() == spec.p_max and isinstance(getattr(mtd, "_photo_dlg", None), dialogs_testphoto.PhotoResultDialog))
rd = mtd._photo_dlg
check("risultato: un pulsante «Usa questo» per ogni proposta", set(rd.buttons) == {"scura", "leggera", "foto"}, list(rd.buttons))
rd.buttons["scura"].click()
check("«Usa questo»: il quadrato si sceglie nella griglia, pronto per la libreria",
      (mtd.pick_r.currentData(), mtd.pick_c.currentData()) == sc.cell and mtd.b_lib.isEnabled())
warned.clear()
check("foto sbagliata: avviso, niente risultato", mtd.analyze_image(np.full((400, 400, 3), 200, np.uint8)) is None and warned)
check("guida «Come si fa?»: sei passaggi", dialogs_testphoto.guide_html().count("<li>") == 6)

# --- guardia fiamme con un lavoro vero sul simulatore
w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.connected and w.ctl.last_status.get("state") == "Idle")
w.ctl.sim.speedup = 1
long_job = ["G90 G21", "M4 S0"] + [f"G1 X{10 + (i % 2) * 200} Y{10 + i} S300 F600" for i in range(60)] + ["M5"]

class FakeCam:
    index = 0
    def __init__(self):
        self.frame, self._t = bed(), 0.0
    def get(self, after=0.0, timeout=0.0):
        return None if self._t <= after else self.frame.copy()
    def push(self, f):
        self.frame, self._t = f, self._t + 1.0

cam = FakeCam()
w.camera.src = cam
w.fire.timer.stop()
w.ctl.stream_job(long_job)
until(lambda: w.ctl.job_active)
for _ in range(10):
    cam.push(bed()); w.fire.tick()
check("guardia spenta: anche con una fiamma il lavoro continua", (cam.push(flame(bed())), w.fire.tick(), w.fire.tick())
      and w.fire.state == "spenta" and w.ctl.job_active)
w.fire.set_enabled(True)
for _ in range(10):
    cam.push(bed()); w.fire.tick()
check("guardia accesa durante il lavoro: sorveglia", w.fire.state == "attiva" and w.ctl.job_active and w.fire.running)
fired = []
w.fire.triggered.connect(lambda p: fired.append(p))
for _ in range(4):
    cam.push(flame(bed())); w.fire.tick()
stopped = until(lambda: not w.ctl.job_active, 5)
check("fiamma: lavoro fermato", stopped and w.fire.state == "allarme", f"{w.ctl.job_active} {w.fire.state}")
check("fiamma: foto salvata nella diagnostica", fired and fired[0] and os.path.isfile(fired[0]) and
      os.path.dirname(fired[0]) == diag.diag_dir(), fired)
check("fiamma: annotata nel registro della comunicazione", any("guardia fiamme" in l[2] for l in w.comm_log.lines))
w.camera.src = None
w.ctl.stream_job(long_job)
until(lambda: w.ctl.job_active)
w.fire.tick()
check("guardia accesa ma nessuna camera: il lavoro va, con l'avviso", w.fire.state == "senza-camera" and w.ctl.job_active)
w.ctl.stop_job()
until(lambda: not w.ctl.job_active, 5)
fd = w.fire_guard_dialog()
check("finestra Guardia fiamme: casella, sensibilità e avviso", fd.chk.isChecked() and fd.level.count() == 3)
fd.level.setCurrentIndex(fd.level.findData("alta"))
check("sensibilità scelta: si ricorda", w.fire.sensitivity() == "alta" and w.qs.value("fire_guard_level") == "alta")
fd.chk.setChecked(False)
check("si spegne dalla stessa casella", w.fire.enabled() is False)
fd.close()

# ================================================================== controllo dal telefono
check("indirizzi della rete locale soltanto", phone._is_local("192.168.1.20") and phone._is_local("10.0.0.5") and
      phone._is_local("127.0.0.1") and phone._is_local("::ffff:192.168.0.3") and not phone._is_local("8.8.8.8") and
      not phone._is_local("2a00:1450::1"))
pd = w.phone_dialog()
pd.chk.setChecked(True)
check("acceso dalla finestra: indirizzo con codice e QR", w.phone.running and w.phone.urls() and
      w.phone.server.token in w.phone.urls()[0] and pd.qr.pixmap() is not None and not pd.qr.pixmap().isNull())
base_url = f"http://127.0.0.1:{w.phone.server.port}/{w.phone.server.token}/"
def get(path, method="GET", data=None, headers=None):
    req = urllib.request.Request(base_url + path, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read(), dict(ex.headers)
def post(path, data=b"", ctype="text/plain"):
    out = {}
    import threading
    def run():
        out["r"] = get(path, "POST", data, {"X-FLC": "1", "Content-Type": ctype})
    t = threading.Thread(target=run); t.start()
    until(lambda: not t.is_alive(), 10)
    return out.get("r")

code, body, hdr = get("")
page = body.decode("utf-8")
check("pagina per il telefono: si apre, testi tradotti, niente segnaposto", code == 200 and "Pausa" in page and
      "{{" not in page and "[[" not in page and "Content-Security-Policy" in hdr, code)
check("pagina: nessun comando per avviare o riprendere", "avvia" not in page.lower().replace("avviarlo", "") and
      "riprendi" not in page.lower())
try:
    urllib.request.urlopen(base_url.replace(w.phone.server.token, "sbagliato") + "stato", timeout=5)
    bad = 200
except urllib.error.HTTPError as ex:
    bad = ex.code
check("codice sbagliato nell'indirizzo: 404", bad == 404, bad)
st = json.loads(get("stato")[1])
check("stato: macchina connessa, nessun lavoro", st["connected"] and not st["job_active"], st["title"])
code, body, _ = get("stop", "POST", b"")
check("comando senza l'intestazione della pagina: rifiutato", code == 403)
check("comando sconosciuto (es. avvio): non esiste", post("avvia")[0] == 404)
check("foto della camera: 404 senza camera", get("foto.jpg")[0] == 404)
w.camera.src = cam
cam.push(bed())
code, body, hdr = get("foto.jpg")
check("foto della camera: JPEG", code == 200 and body[:2] == b"\xff\xd8" and hdr.get("Content-Type") == "image/jpeg")
w.camera.src = None
w.ctl.stream_job(long_job)
until(lambda: w.ctl.job_active)
until(lambda: (w.phone.refresh(), w.phone.snapshot["job_active"])[1])
r = post("pausa")
check("Pausa dal telefono: il lavoro si ferma in pausa (pulsante Pausa del PC premuto)",
      r and json.loads(r[1])["ok"] and until(lambda: w.laser.b_pause.isChecked() and w.ctl.job_active, 5), r and r[1])
until(lambda: (w.phone.refresh(), w.phone.snapshot["paused"])[1], 5)
r = post("pausa")
check("dal telefono non si riprende", "PC" in json.loads(r[1])["msg"] and w.laser.b_pause.isChecked())
r = post("stop")
check("Stop dal telefono: lavoro fermato", json.loads(r[1])["ok"] and until(lambda: not w.ctl.job_active, 5))
check("registro: pausa e stop dal telefono annotati", any("stop dal telefono" in l[2] for l in w.comm_log.lines))
w.laser.b_pause.setChecked(False)
mtd2 = w.material_test()
mtd2._photo_dlg = None
ok, jpg = cv2.imencode(".jpg", persp, [cv2.IMWRITE_JPEG_QUALITY, 92])
r = post("foto-test", jpg.tobytes(), "image/jpeg")
check("foto del test dal telefono: arriva nel Test materiale e viene letta",
      r and json.loads(r[1])["ok"] and until(lambda: isinstance(getattr(mtd2, "_photo_dlg", None),
                                                                 dialogs_testphoto.PhotoResultDialog), 5))
check("foto vuota: rifiutata", post("foto-test", b"", "image/jpeg")[0] == 413)
old = w.phone.server.token
pd.b_code.click()
try:
    urllib.request.urlopen(f"http://127.0.0.1:{w.phone.server.port}/{old}/stato", timeout=5)
    gone = 200
except urllib.error.HTTPError as ex:
    gone = ex.code
check("«Cambia codice»: il vecchio indirizzo smette di funzionare", gone == 404 and w.phone.server.token != old)
port = w.phone.server.port
pd.chk.setChecked(False)
try:
    urllib.request.urlopen(f"http://127.0.0.1:{port}/{w.phone.server.token}/stato", timeout=2)
    off = False
except (urllib.error.URLError, OSError):
    off = True
check("spento dalla finestra: la pagina non risponde più", off and not w.phone.running)
pd.close()
w.ctl.disconnect_port()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
