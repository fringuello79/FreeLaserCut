# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.0: due aggiunte alla telecamera chieste da Ale.

1. «Mostra senza calibrazione» (nella tendina della calibrazione, dopo Automatico / Solo puntino / Solo bersaglio): la
   telecamera si vede sotto il piano così com'è, intera e non deformata, con l'avviso che NON è allineata.
2. «Foto del piano dal telefono» (dove si sceglie la telecamera): la foto arriva dalla pagina del controllo dal
   telefono (collegamento discreto «Apri il codice QR per il telefono»), si indicano i 4 angoli dell'area di lavoro e
   la foto, raddrizzata, finisce sotto il piano.

Il dato: sorgente (nessuna | telecamera | foto dal telefono) × calibrazione (calibrata | no) × scelta (automatico,
puntino, bersaglio, senza calibrazione) × foto dal telefono (nessuna | arrivata | allineata).
"""
import ast
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import camera, camera_panel, phone, plate_photo  # noqa: E402
from freelasercut.camera import PHONE_CAMERA  # noqa: E402
from freelasercut.i18n import tr  # noqa: E402
from freelasercut.ui.dialogs_plate import PlateCornersDialog  # noqa: E402

results = []
hidden = []  # errori dentro i comandi dell'interfaccia: Qt li scrive e va avanti, qui li conto
sys.excepthook = lambda *a: hidden.append(a[1])


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


# ================================================================== 1. i conti (senza finestre)
BED = (400.0, 300.0)
frame = np.zeros((480, 640, 3), np.uint8)
frame[:, :320] = (0, 0, 255)  # metà sinistra rossa, metà destra blu
frame[:, 320:] = (255, 0, 0)
top = plate_photo.fit_raw(frame, BED, 2.0)
check("senza calibrazione: l'immagine è grande quanto il piano (2 punti per mm)", top.shape == (600, 800, 3), top.shape)
check("…intera e con le sue proporzioni (4:3 in un piano 4:3 lo riempie tutto)",
      tuple(top[300, 100]) == (0, 0, 255) and tuple(top[300, 700]) == (255, 0, 0) and tuple(top[5, 5]) == (0, 0, 255))
wide = plate_photo.fit_raw(np.full((90, 320, 3), 200, np.uint8), BED, 2.0)  # foto molto larga: bande sopra e sotto
check("…una foto più larga del piano non viene deformata: bande del colore del piano sopra e sotto, foto al centro",
      wide.shape == (600, 800, 3) and tuple(wide[2, 400]) == plate_photo.BACK and tuple(wide[597, 400]) == plate_photo.BACK
      and tuple(wide[300, 400]) == (200, 200, 200) and tuple(wide[300, 3]) == (200, 200, 200)
      and abs(int((wide[:, 400, 0] == 200).sum()) - 225) <= 2, int((wide[:, 400, 0] == 200).sum()))
tall = plate_photo.fit_raw(np.full((400, 100, 3), 90, np.uint8), BED, 2.0)
check("…e una più alta ha le bande ai lati", tuple(tall[300, 3]) == plate_photo.BACK and tuple(tall[300, 400]) == (90, 90, 90)
      and tuple(tall[3, 400]) == (90, 90, 90))

# una «foto» sintetica del piano visto di sbieco: so dove stanno i 4 angoli e un segno a (100, 50) mm
W, H = 1200, 900
true = [(260.0, 180.0), (980.0, 150.0), (1120.0, 800.0), (120.0, 760.0)]  # (0,Ymax), (Xmax,Ymax), (Xmax,0), (0,0)
flat = np.full((600, 800, 3), 235, np.uint8)  # il piano dall'alto, 2 punti per mm
cv2.rectangle(flat, (0, 0), (799, 599), (40, 40, 40), 6)
cv2.circle(flat, (200, 600 - 100), 14, (0, 0, 255), -1)  # segno rosso a X 100, Y 50
cv2.circle(flat, (700, 600 - 500), 14, (0, 160, 0), -1)  # segno verde a X 350, Y 250
M = cv2.getPerspectiveTransform(np.array([(0, 0), (800, 0), (800, 600), (0, 600)], np.float32), np.array(true, np.float32))
shot = cv2.warpPerspective(flat, M, (W, H), borderValue=(90, 110, 130))
for mix in ([0, 1, 2, 3], [2, 0, 3, 1], [3, 2, 1, 0], [1, 3, 0, 2]):
    got = plate_photo.order_corners([true[i] for i in mix])
    if got != true:
        break
check("i 4 angoli cliccati in un ordine qualsiasi vengono messi in ordine (alto-sx, alto-dx, basso-dx, basso-sx)",
      got == true, got)
skew = [(100.0, 480.0), (500.0, 100.0), (900.0, 500.0), (480.0, 820.0)]  # un rombo: l'angolo in alto a sinistra è il primo
check("…anche quando l'area nella foto è girata come un rombo",
      all(plate_photo.order_corners([skew[i] for i in mix]) == skew for mix in ([0, 1, 2, 3], [2, 3, 0, 1], [1, 0, 3, 2])),
      plate_photo.order_corners(skew))
check("controlli sui punti: meno di 4, due quasi uguali, in fila, incrociati (uno rientra)",
      plate_photo.check_corners(true[:3], (W, H)) == "few" and plate_photo.check_corners(true, (W, H)) is None
      and plate_photo.check_corners([true[0], (262.0, 181.0), true[2], true[3]], (W, H)) == "close"
      and plate_photo.check_corners([(100, 100), (500, 102), (900, 104), (1100, 105)], (W, H)) == "flat"
      and plate_photo.check_corners([(100, 100), (1000, 100), (500, 300), (550, 800)], (W, H)) in ("crossed", "close"),
      plate_photo.check_corners([(100, 100), (1000, 100), (500, 300), (550, 800)], (W, H)))
rect = plate_photo.rectify(shot, true, BED, 2.0)
check("raddrizzata: grande quanto il piano, e i segni tornano dove stanno davvero (X 100 Y 50 rosso, X 350 Y 250 verde)",
      rect.shape == (600, 800, 3) and rect[500, 200, 2] > 200 and rect[500, 200, 1] < 60
      and rect[100, 700, 1] > 120 and rect[100, 700, 2] < 60, (rect[500, 200], rect[100, 700]))
mm = plate_photo.to_bed(true, BED, [true[3], true[1], M_pt := cv2.perspectiveTransform(
    np.array([[[200.0, 500.0]]], np.float32), M)[0][0]])
check("un punto della foto -> millimetri sul piano: l'angolo dell'origine è (0, 0), quello opposto (400, 300), il "
      "segno rosso (100, 50)", abs(mm[0][0]) < 0.5 and abs(mm[0][1]) < 0.5 and abs(mm[1][0] - 400) < 0.5
      and abs(mm[1][1] - 300) < 0.5 and abs(mm[2][0] - 100) < 0.5 and abs(mm[2][1] - 50) < 0.5, mm)
turned = plate_photo.rotate(true, 1)
check("foto fatta da un lato: girando l'origine di un quarto cambia quale angolo è X0 Y0", turned == true[1:] + true[:1]
      and plate_photo.rotate(true, 4) == true and plate_photo.rotate(true, 5) == turned)
ok_, jpg = cv2.imencode(".jpg", shot)
dec = plate_photo.decode(jpg.tobytes())
check("i byte della foto diventano un'immagine; un file qualsiasi no", dec is not None and dec.shape == shot.shape
      and plate_photo.decode(b"non sono una foto") is None and plate_photo.decode(b"") is None)
big = plate_photo.decode(cv2.imencode(".jpg", np.zeros((3000, 5000, 3), np.uint8))[1].tobytes())
check("una foto enorme viene ridotta (lato lungo 2400)", big is not None and max(big.shape[:2]) == 2400, big.shape)

# ================================================================== 2. la finestra dei 4 angoli
dlg = PlateCornersDialog(shot, BED)
check("finestra dei 4 angoli: all'inizio niente da usare", not dlg.b_ok.isEnabled() and dlg.corners() is None
      and not dlg.b_undo.isEnabled() and "0" in dlg.info.text())
for i in (2, 0, 3):
    dlg.view.clicked.emit(*true[i])
check("tre clic: ancora no", len(dlg.pts) == 3 and not dlg.b_ok.isEnabled() and "3" in dlg.info.text())
dlg.add(*true[1])
check("quattro clic in ordine sparso: angoli riconosciuti, «Usa questa foto» attivo, X0 Y0 in basso a sinistra",
      dlg.b_ok.isEnabled() and dlg.corners() == true and dlg.b_turn.isEnabled()
      and any(getattr(m, "text", lambda: "")() == "X0 Y0" for m in dlg.marks))
check("un quinto clic non aggiunge niente", dlg.add(600, 400) is False and len(dlg.pts) == 4)
check("un clic fuori dalla foto non conta", PlateCornersDialog(shot, BED).add(-20, 50) is False)
dlg.rotate()
check("«Gira l'origine»: gli stessi 4 punti, ma X0 Y0 passa all'angolo accanto", dlg.corners() == true[1:] + true[:1])
for _ in range(3):
    dlg.rotate()
check("…quattro volte e torna com'era", dlg.corners() == true)
dlg.undo()
dlg.add(true[0][0] + 2, true[0][1] + 1)  # per sbaglio quasi sopra un altro punto
check("due punti quasi nello stesso posto: non si può usare, e dice perché", not dlg.b_ok.isEnabled()
      and dlg.corners() is None and "⚠" in dlg.info.text(), dlg.info.text())
dlg.undo()
check("«Togli l'ultimo punto» e si rimette", len(dlg.pts) == 3 and dlg.add(*true[1]) and dlg.corners() == true)

# ================================================================== 3. il pannello Camera
SCENE = np.full((480, 640, 3), 150, np.uint8)
cv2.rectangle(SCENE, (100, 80), (540, 400), (60, 90, 120), -1)
THUMB = cv2.resize(SCENE, (160, 90))
opened = []


class FakeSource:
    def __init__(self, index, *a, **k):
        self.index, self.size, self.black, self.mode = index, (640, 480), False, "msmf"
        opened.append(index)

    def get(self, after=0, timeout=0.1):
        return SCENE.copy()

    def close(self):
        opened.append(("chiusa", self.index))


camera_panel.list_cameras = lambda max_index=6, skip=(): [(0, "Webcam  ·  640×480", (640, 480), THUMB)]
camera_panel.CameraSource = FakeSource
camera.usb_camera_names = lambda: {0: "Webcam"}
camera.net_candidates = lambda *a, **k: []

from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
cam = w.camera
until(lambda: not cam._searching and cam.src is not None, 8)
shown = []
real_set, real_clear = w.bed.set_camera_image, w.bed.clear_camera
w.bed.set_camera_image = lambda q, ppm, op=0.85: (shown.append((q.width(), q.height(), ppm)), real_set(q, ppm, op))[1]
w.bed.clear_camera = lambda: (shown.append("via"), real_clear())[1]
items = [cam.method.itemText(i) for i in range(cam.method.count())]
check("tendina della calibrazione: Automatico, Solo puntino, Solo bersaglio e, in fondo, «Mostra senza calibrazione»",
      [cam.method.itemData(i) for i in range(cam.method.count())] == ["auto", "spot", "target", "raw"]
      and items[-1] == tr("Mostra senza calibrazione"), items)
check("telecamera non calibrata, scelta «Automatico»: la foto sotto il piano non si può accendere (come prima)",
      cam.src is not None and cam.model is None and not cam.chk_live.isEnabled() and not cam.can_show())
cam.method.setCurrentIndex(cam.method.findData("raw"))
check("«Mostra senza calibrazione»: ora si può accendere, anche senza calibrazione", cam.chk_live.isEnabled()
      and cam.is_raw() and cam.can_show())
check("…lo stato avvisa che NON è allineata al piano", "NON" in cam.state.text() and "allineata" in cam.state.text(),
      cam.state.text())
from freelasercut.grbl import SIM_PORT  # noqa: E402

w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.connected and not cam._searching and cam.src is not None and cam.src.index == 0, 8)
until(lambda: False, 0.5)
until(lambda: not cam._searching, 8)
raw_off = (cam.is_raw(), cam.btn_cal.isEnabled(), cam.btn_manual.isEnabled())
cam.method.setCurrentIndex(cam.method.findData("auto"))
auto_on = (cam.btn_cal.isEnabled(), cam.btn_manual.isEnabled())
cam.method.setCurrentIndex(cam.method.findData("raw"))
check("…con il laser collegato i pulsanti della calibrazione sono spenti con «senza calibrazione» (niente da "
      "calibrare) e accesi con le altre scelte", raw_off == (True, False, False) and auto_on == (True, True)
      and not cam.btn_cal.isEnabled(), (raw_off, auto_on, cam.src and cam.src.index))
w.ctl.disconnect_port()
until(lambda: False, 0.5)
until(lambda: not cam._searching and cam.src is not None and cam.src.index == 0, 8)
cam.chk_live.setChecked(True)
bw, bh = int(round(w.profile.bed_x * 2)), int(round(w.profile.bed_y * 2))
check("accesa: sotto il piano va un'immagine grande quanto l'area di lavoro", shown and shown[-1] == (bw, bh, 2.0)
      and w.canvas._cam_item is not None, (shown[-1:], (bw, bh)))
n = len(shown)
cam.tick()
check("…e si aggiorna dal vivo", len(shown) == n + 1 and shown[-1] == (bw, bh, 2.0))
check("la scelta viene ricordata", w.qs.value("camera_raw") in (True, "true"))
cam.method.setCurrentIndex(cam.method.findData("auto"))
check("tornando ad «Automatico» senza calibrazione: la foto sotto il piano si spegne e sparisce",
      not cam.chk_live.isChecked() and not cam.chk_live.isEnabled() and shown[-1] == "via"
      and w.canvas._cam_item is None and w.qs.value("camera_raw") in (False, "false"))
check("…e lo stato torna quello di prima («non ancora calibrata»)", "NON è allineata" not in cam.state.text())


class FakeModel:  # una calibrazione finta: «raddrizza» colorando tutto di verde
    frame_size, created, rms_mm = (640, 480), "oggi", 0.2

    def rectify(self, frame, ppm):
        out = np.zeros((bh, bw, 3), np.uint8)
        out[:] = (0, 255, 0)
        return out


def bed_pixel(x=None, y=None):
    img = w.canvas._cam_item.pixmap().toImage()
    c = img.pixelColor(img.width() // 2 if x is None else x, img.height() // 2 if y is None else y)
    return (c.red(), c.green(), c.blue())


cam.model, cam.saved = FakeModel(), {"method": "puntino", "camera_index": 0}
cam.update_state()
cam.chk_live.setChecked(True)
check("telecamera calibrata, «Automatico»: sotto il piano va la foto calibrata", bed_pixel() == (0, 255, 0), bed_pixel())
cam.method.setCurrentIndex(cam.method.findData("raw"))
check("telecamera calibrata ma scelta «senza calibrazione»: si vede così com'è (non quella calibrata), con l'avviso",
      cam.chk_live.isChecked() and bed_pixel() != (0, 255, 0) and "NON" in cam.state.text(), bed_pixel())
cam.method.setCurrentIndex(cam.method.findData("spot"))
check("…e tornando a un'altra scelta torna quella calibrata, e i pulsanti della calibrazione seguono il collegamento",
      cam.chk_live.isChecked() and bed_pixel() == (0, 255, 0) and "NON è allineata" not in cam.state.text()
      and cam.btn_cal.isEnabled() == bool(w.ctl.connected))
cam.chk_live.setChecked(False)
cam.model, cam.saved = None, None
cam.method.setCurrentIndex(cam.method.findData("auto"))
cam.update_state()

# ================================================================== 4. foto del piano dal telefono
texts = [cam.combo.itemText(i) for i in range(cam.combo.count())]
ip = cam.combo.findData(PHONE_CAMERA)
check("dove si sceglie la telecamera c'è «Foto del piano dal telefono»", ip > 0 and "telefono" in texts[ip], texts)
check("il collegamento del codice QR non si vede finché non si sceglie quella voce", cam.phone_link.isHidden())
cam.combo.setCurrentIndex(ip)
cam.combo.activated.emit(ip)
check("scelta la voce: nessuna telecamera aperta, c'è il collegamento discreto «Apri il codice QR per il telefono»",
      cam.is_phone() and not cam.phone_link.isHidden() and tr("Apri il codice QR per il telefono") in cam.phone_link.text()
      and ("chiusa", 0) in opened)
check("…lo stato dice che cosa fare, la foto sotto il piano non si può ancora accendere, la calibrazione è spenta",
      "telefono" in cam.state.text() and not cam.chk_live.isEnabled() and not cam.btn_cal.isEnabled()
      and not cam.method.isEnabled() and cam.b_again.isHidden(), cam.state.text())
check("…e non viene ricordata come telecamera (al prossimo avvio non resta una voce senza foto)",
      w.qs.value("camera_choice") != PHONE_CAMERA)
opened_dialogs = []
real_pd = w.phone_dialog
w.phone_dialog = lambda *a: (opened_dialogs.append(1), real_pd())[1]
cam.phone_link.linkActivated.emit("#")
pd = w._ph_dlg
check("clic sul collegamento: si apre la finestra del controllo dal telefono (con il codice QR), spenta finché non la "
      "accendi tu", opened_dialogs == [1] and pd is not None and pd.isVisible() and not w.phone.running)
pd.chk.setChecked(True)
check("accesa: il codice QR c'è", w.phone.running and pd.qr.pixmap() is not None and not pd.qr.pixmap().isNull())
base_url = f"http://127.0.0.1:{w.phone.server.port}/{w.phone.server.token}/"


def http(path, method="GET", data=None, headers=None):
    out = {}

    def run():
        req = urllib.request.Request(base_url + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                out["r"] = (r.status, r.read())
        except urllib.error.HTTPError as ex:
            out["r"] = (ex.code, ex.read())
    t = threading.Thread(target=run)
    t.start()
    until(lambda: not t.is_alive(), 12)
    return out.get("r")


code, body = http("")
page = body.decode("utf-8")
check("pagina del telefono: c'è «Foto del piano di lavoro», con la spiegazione, e resta quella del test materiale",
      code == 200 and tr("Foto del piano di lavoro") in page and "foto-piano" in page and "foto-test" in page
      and "[[" not in page and "4" in page)
code, body = http("foto-piano", "POST", jpg.tobytes(), {"Content-Type": "image/jpeg"})
check("senza l'intestazione dei comandi la foto non viene accettata", code == 403 and cam.src.get() is None, code)
code, body = http("foto-piano", "POST", b"", {"X-FLC": "1"})
check("una foto vuota non viene accettata", code == 413 and cam.src.get() is None, code)
code, body = http("foto-piano", "POST", jpg.tobytes(), {"X-FLC": "1", "Content-Type": "image/jpeg"})
until(lambda: cam.src.get() is not None, 5)
msg = json.loads(body.decode("utf-8")) if code == 200 else {}
check("foto mandata dal telefono: accettata, e il telefono legge che cosa fare sul PC", code == 200 and msg.get("ok")
      and "4" in msg.get("msg", ""), (code, msg))
check("…sul PC la foto è arrivata al pannello Camera, che chiede i 4 angoli", cam.src.get() is not None
      and cam.src.get().shape == shot.shape and "4 angoli" in cam.state.text() and not cam.chk_live.isEnabled()
      and not cam.b_again.isHidden(), cam.state.text())
check("…e la foto del piano non finisce nel Test materiale", getattr(w, "_mt_dlg", None) is None
      or not getattr(w._mt_dlg, "isVisible", lambda: False)())
check("angoli sbagliati (due quasi uguali): la foto non viene usata",
      cam.align_phone_photo([true[0], (true[0][0] + 1, true[0][1]), true[2], true[3]]) is False
      and cam.phone_top is None and not cam.chk_live.isEnabled())
shown.clear()
ok = cam.align_phone_photo(true)
check("indicati i 4 angoli: la foto raddrizzata va sotto il piano e la spunta si accende da sola",
      ok and cam.chk_live.isChecked() and cam.chk_live.isEnabled() and shown and shown[-1] == (bw, bh, 2.0)
      and w.canvas._cam_item is not None, shown[-2:])
px = (int(round(100 / BED[0] * bw)), bh - int(round(50 / BED[1] * bh)))
r_, g_, b_ = bed_pixel(*px)
check("…allineata: il segno rosso che sul piano vero sta a un quarto della larghezza e un sesto dell'altezza è lì",
      r_ > 180 and g_ < 90 and b_ < 90, (r_, g_, b_))
check("…lo stato dice che è una foto dal telefono allineata a mano, con precisione indicativa",
      "telefono" in cam.state.text() and "indicativa" in cam.state.text(), cam.state.text())
n = len(shown)
cam.tick()
check("una foto ferma non viene ridisegnata a ogni giro", len(shown) == n)
check("la foto dal telefono non viene rimandata al telefono come «camera» del PC", w.phone._frame() is None
      and (w.phone.refresh() or True) and w.phone.snapshot["camera"] is False)
cam.search(manual=True)
until(lambda: not cam._searching, 8)
check("cercando di nuovo le telecamere la foto dal telefono resta scelta e resta sotto il piano", cam.is_phone()
      and cam.phone_top is not None and cam.combo.currentData() == PHONE_CAMERA and cam.chk_live.isChecked()
      and sum(cam.combo.itemData(i) == PHONE_CAMERA for i in range(cam.combo.count())) == 1)
flat2 = flat.copy()
cv2.circle(flat2, (400, 300), 30, (255, 0, 255), -1)
shot2 = cv2.warpPerspective(flat2, M, (W, H), borderValue=(90, 110, 130))
code, body = http("foto-piano", "POST", cv2.imencode(".jpg", shot2)[1].tobytes(), {"X-FLC": "1"})
until(lambda: cam.phone_top is None, 5)
check("una seconda foto: sostituisce la prima e chiede di nuovo i 4 angoli (quelli vecchi non valgono più)",
      code == 200 and cam.phone_top is None and cam.phone_corners is None and "4 angoli" in cam.state.text())
cam.align_phone_photo(plate_photo.rotate(true, 2))
r_, g_, b_ = bed_pixel(bw - px[0], bh - px[1])
check("origine girata di mezzo giro (foto fatta da dietro): la foto sotto il piano è girata di conseguenza",
      r_ > 180 and g_ < 90 and b_ < 90, (r_, g_, b_))
code, body = http("foto-piano", "POST", b"questa non e una foto", {"X-FLC": "1"})
until(lambda: "non è una foto" in w.statusBar().currentMessage(), 5)
check("un file che non è una foto: lo dice e lascia tutto com'è", cam.phone_top is not None
      and "non è una foto" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
i0 = cam.combo.findData(0)
cam.combo.setCurrentIndex(i0)
check("tornando alla telecamera vera la foto dal telefono sparisce da sotto il piano e la tendina della calibrazione "
      "torna usabile", not cam.is_phone() and cam.phone_link.isHidden() and cam.b_again.isHidden()
      and cam.method.isEnabled() and not cam.chk_live.isChecked())
code, body = http("foto-piano", "POST", jpg.tobytes(), {"X-FLC": "1"})
until(lambda: cam.is_phone() and cam.src.get() is not None, 5)
check("foto mandata mentre è scelta un'altra telecamera: FreeLaserCut passa da solo a «Foto del piano dal telefono»",
      cam.is_phone() and cam.combo.currentData() == PHONE_CAMERA and cam.src.get() is not None)
srv = phone.PhoneServer(lambda: {}, None, None, None, lambda d: "x", port=18866)
srv.start()
old_base, base_url = base_url, f"http://127.0.0.1:{srv.port}/{srv.token}/"
code, body = http("foto-piano", "POST", jpg.tobytes(), {"X-FLC": "1"})
srv.close()
base_url = old_base
check("un server senza la funzione della foto del piano risponde «non trovato» (niente inciampi)", code == 404, code)
w.phone.stop()

# ================================================================== 5. traduzioni
keys = set()
for rel in (("camera_panel.py",), ("ui", "dialogs_plate.py"), ("phone.py",), ("ui", "phone_ui.py")):
    srcf = open(os.path.join(ROOT, "freelasercut", *rel), encoding="utf-8").read()
    for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', srcf):
        try:
            k = "".join(ast.literal_eval(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
        except (SyntaxError, ValueError):
            continue
        if rel[-1] == "dialogs_plate.py" or any(t in k for t in ("senza calibrazione", "così com'è", "dal telefono",
                                                                 "4 angoli", "piano di lavoro", "codice QR per")):
            keys.add(k)
check("testi nuovi della telecamera trovati nel codice", len(keys) >= 24, len(keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k[:40] for k in keys if not loc.get(k)]
    bad = [k[:40] for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    check(f"traduzioni {lang}: tutti i testi, con gli stessi segnaposto", not miss and not bad, (miss, bad))

check("nessun errore nascosto nei comandi dell'interfaccia", not hidden, [repr(e)[:120] for e in hidden[:3]])
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
