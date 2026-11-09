# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.18.1 (da un utente con un Creality Falcon A1 10W: «vedo cam0 ma tutto nero»).

- Telecamere USB lette nel primo modo che non dà un'immagine nera (DirectShow, Media Foundation, …), con il modo
  buono ricordato; nomi veri delle telecamere; la «Creality Falcon Camera» scelta da sola.
- Telecamera di rete (Creality Falcon A1 Pro, A1C, T1: porta 8080, /media/getCapturePhoto), una richiesta alla volta.
- Spiegazione quando l'immagine è nera, e tutto nel rapporto per l'assistenza.
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

import freelasercut  # noqa: E402
from freelasercut import camera, machines  # noqa: E402
from freelasercut.updater import parse_version  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


check("versione 0.18.1 o successiva", parse_version(freelasercut.__version__) >= (0, 18, 1), freelasercut.__version__)

# ================================================================= telecamere USB finte
SCENE = np.full((1944, 2592, 3), 150, np.uint8)
cv2.rectangle(SCENE, (400, 300), (2200, 1600), (60, 90, 120), -1)
BLACK = np.zeros((1080, 1920, 3), np.uint8)
OPENED = []  # (indice, modo) di ogni apertura


class FakeCap:
    """0 = telecamera del Falcon A1: nera con DirectShow, buona con Media Foundation.
    1 = webcam del PC: buona sempre. 3 = telecamera davvero al buio. 4 = esposizione che parte scura."""

    def __init__(self, index, api):
        self.index, self.api = index, api
        self.reads = 0
        self.ok = index in (0, 1, 3, 4)
        OPENED.append((index, "msmf" if api == cv2.CAP_MSMF else "dshow" if api == cv2.CAP_DSHOW else api))

    def isOpened(self):
        return self.ok

    def set(self, *a):
        return True

    def read(self):
        self.reads += 1
        if self.index == 0:
            return True, (SCENE.copy() if self.api == cv2.CAP_MSMF else BLACK.copy())
        if self.index == 1:
            return True, SCENE[:1080, :1920].copy()
        if self.index == 3:
            return True, np.full((720, 1280, 3), 3, np.uint8)
        if self.index == 4:  # i primi fotogrammi sono scuri finché l'esposizione automatica non si regola
            return True, (np.full((720, 1280, 3), 2, np.uint8) if self.reads < 5 else SCENE[:720, :1280].copy())
        return False, None

    def release(self):
        self.ok = False


real_vc = cv2.VideoCapture
cv2.VideoCapture = FakeCap
camera.sys = types.SimpleNamespace(platform="win32")  # i modi di Windows (DirectShow, Media Foundation…)

check("modi di Windows: prima DirectShow (come sempre), poi Media Foundation", [m[0] for m in camera.modes()][:2]
      == ["dshow", "msmf"])
check("immagine nera riconosciuta, scena normale no", camera.is_black(BLACK) and not camera.is_black(SCENE))
DARK = np.full((100, 100, 3), 40, np.uint8)
cv2.putText(DARK, "A1", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 2, (70, 70, 70), 3)
check("…anche una stanza scura ma non nera non è «nera»", not camera.is_black(DARK))
check("…un'immagine tutta verde (formato letto male) non serve: si prova un altro modo",
      camera.is_black(np.full((100, 100, 3), (0, 135, 0), np.uint8)))

cap, mode, frame, black = camera.open_capture(0, warm=0.3)
check("Falcon A1: nero con DirectShow → si passa da solo a Media Foundation", mode == "msmf" and not black
      and frame.shape[:2] == (1944, 2592), (mode, black, OPENED))
check("…prima provato DirectShow, poi Media Foundation", OPENED[:2] == [(0, "dshow"), (0, "msmf")], OPENED)
check("…il modo buono si ricorda", camera.remembered_mode(0) == "msmf")
OPENED.clear()
cap, mode, frame, black = camera.open_capture(0, warm=0.3)
check("…la volta dopo si apre subito nel modo buono (niente DirectShow nero)", OPENED == [(0, "msmf")], OPENED)
cap, mode, frame, black = camera.open_capture(1, warm=0.3)
check("webcam del PC: resta DirectShow come prima", mode == "dshow" and not black)
cap, mode, frame, black = camera.open_capture(3, warm=0.2)
check("telecamera davvero al buio: si apre lo stesso, segnata come nera", cap is not None and black)
cap, mode, frame, black = camera.open_capture(4, warm=1.0)
check("esposizione che parte scura: si aspetta e l'immagine non è nera", not black and mode == "dshow", (mode, black))
check("telecamera che non c'è: nessuna apertura", camera.open_capture(2, warm=0.1)[0] is None)

# nomi: la telecamera del Falcon si riconosce dal nome e parte da Media Foundation
os.remove(camera._modes_path())
camera.NAMES.clear()
camera.NAMES.update({0: "Creality Falcon Camera", 1: "Integrated Webcam"})
OPENED.clear()
cap, mode, frame, black = camera.open_capture(0, warm=0.3)
check("«Creality Falcon Camera» per nome: si prova subito Media Foundation", OPENED[0] == (0, "msmf") and mode == "msmf",
      OPENED)
check("telecamera del laser preferita per nome", camera.preferred_camera([1, 0]) == 0)
check("modo ricordato per nome (vale anche se cambia il numero)", "nome:Creality Falcon Camera" in json.load(
    open(camera._modes_path(), encoding="utf-8")))
found = camera.list_cameras(max_index=5)
labels = {i: lab for i, lab, *_ in found}
check("ricerca: 4 telecamere, con i nomi veri", sorted(labels) == [0, 1, 3, 4] and labels[0].startswith(
    "Creality Falcon Camera") and "2592×1944" in labels[0], labels)
check("…il nome (di Media Foundation) non va a una telecamera letta con DirectShow (ordine diverso)",
      labels[1].startswith("Camera 1"), labels)
camera.NAMES.clear()
camera.NAMES.update({5: "Creality Falcon Camera"})  # nome a un indice che non corrisponde: si riconosce dalla risoluzione
check("telecamera del laser riconosciuta anche dalla risoluzione 2592 × 1944", camera.preferred_camera([1, 0, 3]) == 0)
camera.NAMES.clear()
camera.NAMES.update({0: "Creality Falcon Camera", 1: "Integrated Webcam"})
check("…la telecamera al buio è segnata «immagine nera»", "nera" in labels[3] and "nera" not in labels[0], labels)
check("…e la ricerca si ricorda come è andata", camera.LAST_PROBE[0]["mode"] == "msmf"
      and camera.LAST_PROBE[3]["black"])

src = camera.CameraSource(0)
time.sleep(0.2)
f = src.get(after=0, timeout=2)
check("CameraSource: Falcon A1 letto in Media Foundation, immagine vera", src.mode == "msmf" and f is not None
      and not src.black)
src.close()
OPENED.clear()
t0 = time.time()
src = camera.CameraSource(3)
elapsed = time.time() - t0
check("CameraSource al buio: segnata nera subito", src.black)
time.sleep(0.6)
check("…e resta «nera» anche dopo (niente spiegazione che va e viene)", src.black)
check("…e aperta subito nel modo già provato dalla ricerca (la finestra non resta ferma)", len(OPENED) == 1
      and elapsed < 1.2, (OPENED, elapsed))
src.close()
check("registro delle telecamere con i modi provati e la luminosità", any("(NERA)" in r for r in camera.CAMERA_LOG)
      and any("msmf" in r for r in camera.CAMERA_LOG))
cv2.VideoCapture = real_vc

# ================================================================= indirizzi di rete
check("indirizzo → URL del Falcon", camera.net_url("192.168.10.1") == "http://192.168.10.1:8080/media/getCapturePhoto")
check("…con la porta scritta", camera.net_url("10.0.0.5:9000") == "http://10.0.0.5:9000/media/getCapturePhoto")
check("…URL completo lasciato com'è", camera.net_url("http://a/b.jpg") == "http://a/b.jpg")
check("…rtsp lasciato com'è", camera.net_url("rtsp://10.0.0.5:8554") == "rtsp://10.0.0.5:8554")
check("…dalla porta Wi-Fi del laser", camera.net_url("tcp://192.168.1.40:23") ==
      "http://192.168.1.40:8080/media/getCapturePhoto")
check("candidati automatici: cavo USB e laser in Wi-Fi", camera.auto_net_candidates("tcp://192.168.1.40:23") ==
      ["192.168.10.1", "192.168.1.40"] and camera.auto_net_candidates("COM3") == ["192.168.10.1"])

# ================================================================= server finti al posto del laser
JPEG = cv2.imencode(".jpg", SCENE[::2, ::2])[1].tobytes()
STATS = {"in_corso": 0, "max": 0, "get": 0, "post": 0, "post_body": None}


class Falcon(BaseHTTPRequestHandler):
    mode = "get"  # get: foto con GET · post: solo POST · html: non manda immagini

    def log_message(self, *a):
        pass

    def _photo(self):
        STATS["in_corso"] += 1
        STATS["max"] = max(STATS["max"], STATS["in_corso"])
        time.sleep(0.15)  # il server del Falcon è lento
        STATS["in_corso"] -= 1
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(JPEG)))
        self.end_headers()
        self.wfile.write(JPEG)

    def do_GET(self):
        STATS["get"] += 1
        if self.path == "/system/basicInfo":
            body = json.dumps({"errorcode": 0, "payload": {"model": "Creality Falcon A1 Pro"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.mode == "get" and self.path == camera.NET_PATH:
            self._photo()
        elif self.mode == "html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>ciao</html>")
        else:
            self.send_response(405)
            self.end_headers()

    def do_POST(self):
        STATS["post"] += 1
        n = int(self.headers.get("Content-Length", 0))
        STATS["post_body"] = json.loads(self.rfile.read(n) or b"{}")
        if self.mode == "post" and self.path == camera.NET_PATH:
            self._photo()
        else:
            self.send_response(404)
            self.end_headers()


def server(mode):
    h = type("H" + mode, (Falcon,), {"mode": mode})
    s = ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"127.0.0.1:{s.server_address[1]}"


s_get, a_get = server("get")
s_post, a_post = server("post")
s_html, a_html = server("html")

url, img, why = camera.probe_net(a_get)
check("rete: foto con GET (come LightBurn)", img is not None and img.shape[:2] == (972, 1296) and why.startswith("GET"),
      why)
url, img, why = camera.probe_net(a_post)
check("rete: server che vuole POST → foto con POST e dimensioni in JSON", img is not None and why.startswith("POST")
      and STATS["post_body"] == {"width": 1600, "height": 1200, "exposureValue": -1}, (why, STATS["post_body"]))
url, img, why = camera.probe_net(a_html)
check("rete: risposta che non è un'immagine → spiegata", img is None and "non con un'immagine" in why, why)
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
closed = f"127.0.0.1:{sock.getsockname()[1]}"
sock.close()
t0 = time.time()
url, img, why = camera.probe_net(closed)
check("rete: indirizzo sbagliato → risposta in fretta, con il motivo", img is None and time.time() - t0 < 3
      and "Nessuna risposta" in why, (why, time.time() - t0))
check("modello letto dalla macchina (/system/basicInfo)", camera.device_info(a_post, 3.0) == "Creality Falcon A1 Pro")
check("…macchina che non lo dice: nessun nome, nessun errore", camera.device_info(closed, 1.0) == "")

STATS.update(get=0, max=0)
nc = camera.NetCamera(camera.net_url(a_get), interval=0.3)
f1 = nc.get(after=0, timeout=5)
t1 = time.time()
f2 = nc.get(after=t1, timeout=5)
check("NetCamera: foto una dopo l'altra", f1 is not None and f2 is not None and nc.method == "GET")
time.sleep(1.0)
check("…mai due richieste insieme (il server del Falcon si bloccherebbe)", STATS["max"] == 1, STATS["max"])
check("…non più di una foto ogni «intervallo»", STATS["get"] <= 1.6 / 0.3 + 1, STATS["get"])
STATS.update(max=0)
probes_ = [threading.Thread(target=camera.probe_net, args=(a_get,)) for _ in range(3)]
for t_ in probes_:
    t_.start()
for t_ in probes_:
    t_.join()
time.sleep(0.5)
check("…anche con la finestra «Prova» e la ricerca insieme alla telecamera aperta: una richiesta alla volta",
      STATS["max"] == 1, STATS["max"])
s_get.shutdown()
s_get.server_close()
time.sleep(0.8)
check("…se la macchina smette di mandare foto (lavoro in corso), resta l'ultima immagine",
      nc.get(after=0, timeout=0.5) is not None)
until(lambda: nc.error != "", 4)
check("…e l'errore è scritto", nc.error != "", nc.error)
nc.close()

# ================================================================= pannello Camera
from freelasercut import camera_panel  # noqa: E402

THUMB = np.full((90, 160, 3), 120, np.uint8)
probes, opened = [], []


def fake_list(max_index=6, skip=()):
    probes.append(1)
    return [(0, "Integrated Webcam  ·  1280×720", (1280, 720), THUMB),
            (1, "Creality Falcon Camera  ·  2592×1944", (2592, 1944), THUMB)]


class FakeSource:
    def __init__(self, index, *a, **k):
        self.index, self.size, self.black, self.mode = index, (2592, 1944), index == 9, "msmf"
        opened.append(index)

    def get(self, after=0, timeout=0.1):
        return SCENE[::4, ::4].copy()

    def close(self):
        opened.append(("chiusa", self.index))


class FakeNet(FakeSource):
    error = ""


camera_panel.list_cameras = fake_list
camera_panel.CameraSource = FakeSource
camera_panel.NetCamera = FakeNet
camera.usb_camera_names = lambda: {0: "Integrated Webcam", 1: "Creality Falcon Camera"}
camera.LAST_PROBE.clear()
camera.LAST_PROBE.update({0: {"mode": "msmf"}, 1: {"mode": "msmf"}})
NET = "http://192.168.10.1:8080/media/getCapturePhoto"
camera.port_open = lambda host, port=8080, timeout=0.8: host == "192.168.10.1"
camera.device_info = lambda host, timeout=3.0: "Creality Falcon A1 Pro"
camera.probe_net = lambda text, timeout=12.0: (camera.net_url(text), SCENE[::4, ::4].copy(), "GET 648×486")

from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
cam = w.camera
check("durante la ricerca l'elenco non si può cambiare", not cam.combo.isEnabled() or not cam._searching)
until(lambda: probes and not cam._searching and cam.src is not None, 8)
check("prima volta: scelta da sola la telecamera del laser (non la webcam del PC)", cam.src is not None
      and cam.src.index == 1, opened)
check("…e finita la ricerca l'elenco torna attivo", cam.combo.isEnabled())
check("nell'elenco anche il Falcon in rete trovato da solo, con il modello", any(
    cam.combo.itemData(i) == NET and "Falcon A1 Pro" in cam.combo.itemText(i) for i in range(cam.combo.count())),
    [cam.combo.itemText(i) for i in range(cam.combo.count())])
i = cam.combo.findData(NET)
cam.combo.setCurrentIndex(i)
cam.combo.activated.emit(i)
check("scelta la telecamera di rete: aperta e ricordata", isinstance(cam.src, FakeNet) and cam.choice() == NET
      and w.qs.value("camera_choice") == NET)
cam._close_src()
cam.saved = {"camera_index": 1, "frame_size": [2592, 1944]}
t0 = time.time()
cam.on_select(i)
check("telecamera di rete con una calibrazione di un'altra camera: la finestra non aspetta la foto",
      time.time() - t0 < 1.0 and cam.model is None, time.time() - t0)
cam.saved = None
cam._close_src()
probes.clear()
cam.search()
until(lambda: probes and not cam._searching and cam.src is not None, 8)
check("al riavvio si riapre la telecamera di rete scelta", cam.src is not None and cam.src.index == NET)
cam._save_net("http://10.0.0.9:8080/media/getCapturePhoto")
check("telecamere di rete usate: ricordate, la più recente prima", cam.net_list()[0].startswith("http://10.0.0.9"))

# immagine nera: spiegazione
cam._close_src()
cam.src = FakeSource(9)
cam._hint()
check("immagine nera: spiegazione con coperchio, luce e ⟳", "nera" in cam.state.text() and "coperchio"
      in cam.state.text(), cam.state.text())
cam.src.black = False
cam._hint()
check("…tornata buona: la spiegazione sparisce", "nera" not in cam.state.text(), cam.state.text())

# finestra «Telecamera di rete»
from freelasercut.ui.dialogs_netcam import NetCameraDialog  # noqa: E402

d = NetCameraDialog(None, "tcp://192.168.1.40:23", [])
check("finestra: propone l'indirizzo del laser in Wi-Fi", d.addr.text() == "192.168.1.40", d.addr.text())
d.addr.setText("192.168.10.1")
d.test()
until(lambda: d.url, 4)
check("finestra: «Prova» mostra la foto e abilita «Usa questa telecamera»", d.url == NET and d.b_ok.isEnabled()
      and d.image is not None, d.result.text())
d.close()

# rapporto per l'assistenza
from freelasercut import diag  # noqa: E402

cam.src = FakeSource(1)
txt = diag.cameras_log_text(w)
check("rapporto: telecamera aperta, modo, nomi e registro", "Telecamera aperta: 1" in txt and "msmf" in txt
      and "Creality Falcon Camera" in txt and "(NERA)" in txt, txt[:300])
check("rapporto: riga della telecamera nel riassunto", "Telecamera: 1" in diag.env_text(w))
cam._close_src()

# ================================================================= catalogo
p = machines.preset_profile("Creality Falcon A1 10W")
check("Falcon A1 10W: area 381 × 305 (X = 381, come risponde la scheda)", (p.bed_x, p.bed_y) == (381, 305))
i = machines.identify(banner=["Grbl 1.1f"], info=["[VER:1.1f.20220810:]",
                                                  "[software versions: CV40-MASTER-Release V1.0.6 20250306-1455]"],
                      settings={130: "381.000", 131: "305.000"})
check("Falcon A1 riconosciuto dalla scheda (CV40)", i.vendor == "Creality" and i.model == "Creality Falcon A1 10W",
      (i.vendor, i.model, i.candidates))
check("nota del Falcon A1 sulla telecamera nel coperchio", "coperchio" in machines.NOTES.get("Creality Falcon A1 10W", ""))

for x in (w,):
    x.editor.dirty = False
    x.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
