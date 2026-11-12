# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Telecamera del piano: ricerca automatica, acquisizione e calibrazione "AutoCam".

AutoCam, in due varianti, scelte in automatico:
  A) Puntino laser: la testa visita una griglia di punti e in ognuno accende il
     laser all'1–3% per un istante; la camera misura il puntino (differenza
     acceso/spento). Non incide nulla.
  B) Bersaglio inciso (ripiego se il puntino non si vede): la macchina incide
     piccoli cerchi su un cartone; la camera li trova confrontando la foto
     prima/dopo. La testa viene "cancellata" dalle foto facendo la mediana di
     più scatti con la testa in punti diversi, e la stessa tecnica dà la stima
     iniziale di dove guardare.
"""
import math
import os
import sys
import threading
import time
from freelasercut.i18n import tr  # noqa: E402

os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")  # niente messaggi mentre si sondano le porte camera
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")
# Media Foundation apre molto più in fretta alcune telecamere senza le trasformazioni hardware
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")
import cv2  # noqa: E402
import numpy as np
from PySide6.QtCore import QObject, Signal

from . import camera_calib as cc
from .profile import config_dir

SIM_CAMERA = -1
PHONE_CAMERA = "telefono"  # 0.19.0: non una telecamera ma la foto del piano mandata dal telefono
CAMERA_FILE = "camera.json"


def camera_file():
    return os.path.join(config_dir(), CAMERA_FILE)


def _backend():
    return cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY


# ----------------------------------------------------------------------- 0.18.1: modi di lettura
# Una stessa telecamera USB si può leggere in più modi. Su Windows DirectShow (il modo di sempre) dà un'immagine
# nera con alcune telecamere che mandano solo il formato NV12 ad alta risoluzione, per esempio la «Creality Falcon
# Camera» nel coperchio del Falcon A1 (2592 × 1944). Media Foundation (MSMF) invece le legge. FreeLaserCut prova i
# modi uno dopo l'altro e tiene il primo che dà un'immagine non nera; il modo buono si ricorda per la volta dopo.
_MODES_WIN = (
    ("dshow", "CAP_DSHOW", (1920, 1080), None),
    ("msmf", "CAP_MSMF", None, None),
    ("msmf-1080", "CAP_MSMF", (1920, 1080), None),
    ("dshow-mjpg", "CAP_DSHOW", (1920, 1080), "MJPG"),
    ("dshow-nativa", "CAP_DSHOW", None, None),
)
_MODES_OTHER = (
    ("any", "CAP_ANY", (1920, 1080), None),
    ("any-nativa", "CAP_ANY", None, None),
)
MODES_FILE = "camera_modi.json"
CAMERA_LOG = []  # ultime righe sulle telecamere: entrano nel rapporto per l'assistenza
LAST_PROBE = {}  # {indice: {"mode", "black", "size", "mean"}} dell'ultima ricerca
NAMES = {}  # {indice: nome} delle telecamere USB, quando il sistema lo dice


def cam_log(text):
    CAMERA_LOG.append(time.strftime("%H:%M:%S ") + str(text))
    del CAMERA_LOG[:-120]


def modes():
    return _MODES_WIN if sys.platform == "win32" else _MODES_OTHER


def frame_stats(frame):
    """(media, chiaro) della luminosità, 0–255: «chiaro» è il valore sotto cui sta il 99% dei punti."""
    if frame is None or frame.size == 0:
        return 0.0, 0.0
    g = frame[::8, ::8]
    if g.ndim == 3:
        g = g.mean(axis=2)
    return float(g.mean()), float(np.percentile(g, 99))


def is_black(frame):
    """Immagine nera (o quasi), oppure tutta di un colore (formato letto male: verde o grigio uniforme): niente di
    utile, di solito perché la telecamera non è letta nel modo giusto."""
    mean, bright = frame_stats(frame)
    if bright < 24 or mean < 5:
        return True
    g = frame[::8, ::8].reshape(-1, frame.shape[2] if frame.ndim == 3 else 1)
    return float(g.std(axis=0).max()) < 2.0


def _modes_path():
    return os.path.join(config_dir(), MODES_FILE)


_modes_lock = threading.Lock()


def name_valid(index, mode):
    """I nomi vengono da Media Foundation: valgono per quell'indice solo se la telecamera è letta con MSMF
    (DirectShow può numerare le telecamere in un altro ordine, per esempio con una telecamera virtuale)."""
    return bool(NAMES.get(index)) and (sys.platform != "win32" or str(mode or "").startswith("msmf"))


def _mode_key(index, mode=None):
    return f"nome:{NAMES[index]}" if name_valid(index, mode or "msmf") else f"#{index}"


def _read_modes():
    import json

    try:
        with open(_modes_path(), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def remembered_mode(index):
    data = _read_modes()
    if NAMES.get(index) and data.get(f"nome:{NAMES[index]}"):
        return data[f"nome:{NAMES[index]}"]
    return data.get(f"#{index}")


def remember_mode(index, mode):
    import json

    with _modes_lock:
        try:
            data = _read_modes()
            key = _mode_key(index, mode)
            if data.get(key) != mode:
                data[key] = mode
                tmp = _modes_path() + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=1, ensure_ascii=False)
                os.replace(tmp, _modes_path())
        except OSError:
            pass


def _ordered_modes(index, first=None):
    all_ = list(modes())
    pref = first or remembered_mode(index)
    name = (NAMES.get(index) or "").lower()
    if pref is None and ("falcon" in name or "creality" in name) and sys.platform == "win32":
        pref = "msmf"  # la telecamera del Falcon A1: con DirectShow arriva nera
    if pref:
        all_.sort(key=lambda m: m[0] != pref)
    return all_


def open_capture(index, warm=2.5, first=None, only_first=False):
    """Apre la telecamera nel primo modo che dà un'immagine non nera.
    Restituisce (cap, modo, fotogramma, nera) oppure (None, None, None, True) se non si apre in nessun modo.
    Se tutti i modi danno nero, tiene quello con l'immagine più chiara (può essere davvero buio)."""
    best = None  # (luminosità, cap, modo, fotogramma)
    tried = _ordered_modes(index, first)
    if only_first:
        tried = tried[:1]
    for name, api_name, size, fourcc in tried:
        api = getattr(cv2, api_name, cv2.CAP_ANY)
        t0 = time.time()
        try:
            cap = cv2.VideoCapture(index, api)
        except Exception as exc:  # noqa: BLE001
            cam_log(f"camera {index} · {name}: errore all'apertura {exc}")
            continue
        if not cap.isOpened():
            cap.release()
            cam_log(f"camera {index} · {name}: non si apre")
            continue
        if fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        if size:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        frame, reads, end = None, 0, time.time() + warm
        while True:  # l'esposizione automatica può dare i primi fotogrammi scuri: aspetto un poco
            ok, f = cap.read()
            reads += 1
            if ok and f is not None:
                frame = f
                if not is_black(f) and reads >= 3:
                    break
            if time.time() > end and reads >= 3:
                break
        mean, bright = frame_stats(frame)
        shape = "nessun fotogramma" if frame is None else f"{frame.shape[1]}×{frame.shape[0]}"
        black = frame is None or is_black(frame)
        cam_log(f"camera {index} · {name}: {shape}, luminosità media {mean:.0f}, chiaro {bright:.0f}"
                f"{' (NERA)' if black else ''}, {reads} letture in {time.time() - t0:.1f} s")
        if frame is not None and not black:
            if best is not None:
                best[1].release()
            remember_mode(index, name)
            return cap, name, frame, False
        if frame is not None and (best is None or bright > best[0]):
            if best is not None:
                best[1].release()
            best = (bright, cap, name, frame)
        else:
            cap.release()
    if best is None:
        return None, None, None, True
    return best[1], best[2], best[3], True


def list_cameras(max_index=6, skip=()):
    """[(indice, etichetta, (w, h), miniatura_bgr)] delle camere che danno immagini.
    `skip`: indici già aperti da FreeLaserCut (non vanno riaperti)."""
    found = []
    for i in range(max_index):
        if i in skip:
            continue
        cap, mode, frame, black = open_capture(i, warm=1.5)
        if cap is None:
            continue
        cap.release()
        if frame is None:
            continue
        h, w = frame.shape[:2]
        LAST_PROBE[i] = {"mode": mode, "black": black, "size": (w, h), "mean": frame_stats(frame)[0]}
        found.append((i, camera_label(i, w, h, black, mode), (w, h), cv2.resize(frame, (160, 90))))
    return found


def camera_label(index, w, h, black=False, mode=None):
    name = NAMES.get(index) if name_valid(index, mode or (LAST_PROBE.get(index) or {}).get("mode")) else None
    text = (f"{name}  ·  {w}×{h}" if name else tr("Camera {0}  ·  {1}×{2}", index, w, h))
    return text + (tr("  ·  immagine nera") if black else "")


def _mf_names():
    """Windows: nomi delle telecamere da Media Foundation (MFEnumDeviceSources), nello stesso ordine degli indici
    di OpenCV con CAP_MSMF. Solo ctypes: niente librerie in più nell'installatore."""
    import ctypes
    import uuid
    from ctypes import POINTER, byref, c_uint32, c_void_p, c_wchar_p

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16),
                    ("d4", ctypes.c_ubyte * 8)]

    def guid(text):
        u = uuid.UUID(text)
        g = GUID(u.fields[0], u.fields[1], u.fields[2])
        g.d4[:] = list(u.bytes[8:])
        return g

    def method(obj, idx, *args, argtypes=()):
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtbl[idx])
        return fn(obj, *args)

    SOURCE_TYPE = guid("c60ac5fe-252a-478f-a0ef-bc8fa5f7cad3")  # MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE
    VIDCAP = guid("8ac3587a-4ae7-42d8-99e0-0a6013eef90f")  # ..._SOURCE_TYPE_VIDCAP_GUID
    FRIENDLY = guid("60d0e559-52f8-4fa2-bbce-acdb34a8ec01")  # MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME
    ole32 = ctypes.windll.ole32
    mfplat = ctypes.windll.mfplat
    mf = ctypes.windll.mf
    ole32.CoInitializeEx(None, 0)
    mfplat.MFStartup(0x20070, 1)  # MF_VERSION, MFSTARTUP_LITE
    attrs = c_void_p()
    if mfplat.MFCreateAttributes(byref(attrs), 1) != 0:
        raise OSError("MFCreateAttributes")
    names = {}
    try:
        # IMFAttributes::SetGUID = 24, GetAllocatedString = 13, IUnknown::Release = 2
        method(attrs, 24, byref(SOURCE_TYPE), byref(VIDCAP), argtypes=(POINTER(GUID), POINTER(GUID)))
        arr, count = POINTER(c_void_p)(), c_uint32(0)
        if mf.MFEnumDeviceSources(attrs, byref(arr), byref(count)) != 0:
            raise OSError("MFEnumDeviceSources")
        for i in range(count.value):
            act = c_void_p(arr[i])
            s, n = c_wchar_p(), c_uint32(0)
            try:
                method(act, 13, byref(FRIENDLY), byref(s), byref(n),
                       argtypes=(POINTER(GUID), POINTER(c_wchar_p), POINTER(c_uint32)))
                names[i] = s.value or ""
                ole32.CoTaskMemFree(s)
            except OSError:
                names[i] = ""
            method(act, 2)
        ole32.CoTaskMemFree(arr)
    finally:
        method(attrs, 2)
    return {i: n for i, n in names.items() if n}


def usb_camera_names():
    """{indice: nome} delle telecamere USB secondo il sistema (su Windows Media Foundation, lo stesso ordine di
    OpenCV con MSMF). Serve per le etichette e per riconoscere la telecamera del Falcon A1; se non si può: {}."""
    try:
        if sys.platform == "win32":
            names = _mf_names()
        else:
            from PySide6.QtMultimedia import QMediaDevices

            names = {i: d.description() for i, d in enumerate(QMediaDevices.videoInputs())}
    except Exception as exc:  # noqa: BLE001
        cam_log(f"nomi delle telecamere non disponibili: {exc}")
        return {}
    if names:
        cam_log("telecamere del sistema: " + "; ".join(f"{i}={n}" for i, n in names.items()))
    return names


def preferred_camera(indices):
    """Fra le telecamere trovate, quella del laser: per nome (letta con MSMF) oppure, se il sistema dice che c'è
    una telecamera del Falcon, quella con la sua risoluzione (2592 × 1944)."""
    def is_laser(n):
        n = (n or "").lower()
        return "falcon" in n or "laser" in n or "creality" in n

    for i in indices:
        if is_laser(NAMES.get(i)) and name_valid(i, (LAST_PROBE.get(i) or {}).get("mode") or remembered_mode(i)):
            return i
    if any(is_laser(n) for n in NAMES.values()):
        for i in indices:
            if tuple((LAST_PROBE.get(i) or {}).get("size") or ()) == (2592, 1944):
                return i
    return None


# ----------------------------------------------------------------------- 0.18.1: telecamere di rete
NET_PATH = "/media/getCapturePhoto"  # Creality Falcon A1 Pro, A1C, T1 (server della macchina sulla porta 8080)
NET_PORT = 8080
USB_NET_HOST = "192.168.10.1"  # i Falcon A1 Pro/A1C con il cavo USB: rete «RNDIS», il laser è 192.168.10.1


def net_url(text):
    """Indirizzo scritto dalla persona → URL dell'immagine: «192.168.1.50» diventa
    «http://192.168.1.50:8080/media/getCapturePhoto»; gli URL completi (http, https, rtsp) restano come sono."""
    t = (text or "").strip()
    if not t:
        return ""
    if t.startswith("tcp://"):
        t = t[6:].split(":")[0]
    low = t.lower()
    if low.startswith(("http://", "https://", "rtsp://")):
        rest = t.split("://", 1)[1]
        return t if "/" in rest or low.startswith("rtsp://") else t.rstrip("/") + NET_PATH
    host = t.split("/")[0]
    path = t[len(host):] or NET_PATH
    if ":" not in host:
        host = f"{host}:{NET_PORT}"
    return f"http://{host}{path}"


def is_net(index):
    return isinstance(index, str) and index.lower().startswith(("http://", "https://", "rtsp://"))


def _opener():
    import urllib.request

    return urllib.request.build_opener(urllib.request.ProxyHandler({}))  # macchina in casa: mai il proxy


_host_locks = {}
_host_locks_guard = threading.Lock()


def _host_lock(url):
    """Una richiesta alla volta per ogni macchina, da qualsiasi parte del programma (telecamera aperta, prova
    nella finestra, ricerca): il server del Falcon si blocca per secondi con due richieste insieme."""
    import urllib.parse

    key = (urllib.parse.urlsplit(url).hostname or url).lower()
    with _host_locks_guard:
        return _host_locks.setdefault(key, threading.Lock())


def safe_url(url):
    """L'indirizzo senza nome utente e password (per il registro e il rapporto)."""
    import re

    return re.sub(r"//[^/@\s]*@", "//", str(url))


def _decode(body, ctype=""):
    if not body:
        return None
    if not (body[:2] == b"\xff\xd8" or body[:4] == b"\x89PNG" or (ctype or "").lower().startswith("image/")):
        return None
    img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    return img


def fetch_snapshot(url, timeout=12.0, method=None):
    """Una foto dalla telecamera di rete. Prima GET (come LightBurn e gli altri programmi); se il server non
    risponde con un'immagine, POST con le dimensioni in JSON (come il programma di Creality).
    Restituisce (immagine | None, metodo usato | None, spiegazione)."""
    import json
    import urllib.error
    import urllib.request

    with _host_lock(url):
        return _fetch(url, timeout, method)


def _fetch(url, timeout, method):
    import json
    import urllib.error
    import urllib.request

    op = _opener()
    tries = [method] if method else ["GET", "POST"]
    whys = []
    for m in tries:
        try:
            if m == "POST":
                body = json.dumps({"width": 1600, "height": 1200, "exposureValue": -1}).encode()
                req = urllib.request.Request(url, data=body, method="POST",
                                             headers={"Content-Type": "application/json",
                                                      "User-Agent": "FreeLaserCut"})
            else:
                req = urllib.request.Request(url, headers={"User-Agent": "FreeLaserCut"})
            t0 = time.time()
            with op.open(req, timeout=timeout) as r:
                data = r.read(40_000_000)
                ctype = r.headers.get("Content-Type", "")
            img = _decode(data, ctype)
            if img is not None:
                return img, m, f"{m} {img.shape[1]}×{img.shape[0]} in {time.time() - t0:.1f} s"
            whys.append(tr("{0}: risponde ma non con un'immagine ({1}, {2} byte)", m, ctype or "?", len(data)))
        except urllib.error.HTTPError as exc:
            whys.append(tr("{0}: errore {1} del server", m, exc.code))
        except Exception as exc:  # noqa: BLE001  (tempo scaduto, rete irraggiungibile, indirizzo sbagliato)
            whys.append(tr("{0}: {1}", m, getattr(exc, "reason", exc)))
            break  # macchina irraggiungibile o tempo scaduto: inutile chiedere di nuovo subito
    return None, None, " · ".join(whys)


def port_open(host, port=NET_PORT, timeout=0.8):
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def device_info(host, timeout=3.0):
    """Nome del modello dalla macchina (Falcon A1 Pro e simili: /system/basicInfo), oppure ""."""
    import json

    try:
        hp = host if ":" in host else f"{host}:{NET_PORT}"
        with _host_lock(f"http://{hp}/"), _opener().open(f"http://{hp}/system/basicInfo", timeout=timeout) as r:
            d = json.loads(r.read(200_000).decode("utf-8", "replace"))
        p = d.get("payload") or {}
        return str(p.get("model") or "")
    except Exception:  # noqa: BLE001
        return ""


def discover_udp(seconds=4.0, port=12345):
    """I Falcon in Wi-Fi annunciano il loro indirizzo sulla rete di casa (UDP 12345, JSON con «ip» e «port»).
    Restituisce gli indirizzi «ip:porta» sentiti. Windows può chiedere il permesso del firewall."""
    import json
    import socket

    found = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", port))
        s.settimeout(0.3)
        end = time.time() + seconds
        while time.time() < end:
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                continue
            try:
                d = json.loads(data.decode("utf-8", "replace"))
                ip, pt = d.get("ip") or addr[0], d.get("port") or NET_PORT
            except (ValueError, AttributeError):
                continue
            item = f"{ip}:{pt}"
            if item not in found:
                found.append(item)
                cam_log(f"annuncio in rete: {item} ({d.get('devName', '')})")
    except OSError as exc:
        cam_log(f"ricerca in rete non possibile: {exc}")
    finally:
        s.close()
    return found


# ======================================================================= sorgenti
class _FrameSource:
    """Base: un thread legge di continuo e tiene l'ultimo fotogramma con il suo orario."""

    def __init__(self):
        self._lock = threading.Condition()
        self._frame = None
        self._t = 0.0
        self._running = True
        self.size = (0, 0)
        threading.Thread(target=self._loop, daemon=True).start()

    def _grab(self):  # pragma: no cover - implementato dalle sottoclassi
        raise NotImplementedError

    def _loop(self):
        while self._running:
            f = self._grab()
            if f is None:
                time.sleep(0.05)
                continue
            with self._lock:
                self._frame = f
                self._t = time.time()
                self.size = (f.shape[1], f.shape[0])
                self._lock.notify_all()

    def get(self, after=0.0, timeout=4.0):
        end = time.time() + timeout
        with self._lock:
            while self._running and (self._frame is None or self._t <= after):
                left = end - time.time()
                if left <= 0:
                    return None
                self._lock.wait(left)
            return None if self._frame is None else self._frame.copy()

    def frames(self, n=3, after=0.0):
        out, t = [], after
        while len(out) < n:
            f = self.get(after=t)
            if f is None:
                break
            out.append(f)
            with self._lock:
                t = self._t
        return out

    def close(self):
        self._running = False
        with self._lock:
            self._lock.notify_all()


class PhonePhoto:
    """La «telecamera» che è una foto mandata dal telefono (0.19.0): un'immagine ferma, finché non ne arriva
    un'altra. Ha la stessa faccia delle altre sorgenti (index, size, get, close) ma nessun thread."""

    index = PHONE_CAMERA
    black = False
    mode = "foto"

    def __init__(self):
        self._frame = None
        self.size = (0, 0)
        self.time = 0.0

    def set(self, frame):
        self._frame = frame
        self.size = (frame.shape[1], frame.shape[0])
        self.time = time.time()

    def get(self, after=0.0, timeout=0.0):
        return None if self._frame is None else self._frame.copy()

    def close(self):
        pass


class CameraSource(_FrameSource):
    """Telecamera USB, letta nel primo modo che non dà un'immagine nera (vedi open_capture)."""

    def __init__(self, index, width=1920, height=1080):
        self.index = index
        self.black = False
        probe = LAST_PROBE.get(index)
        if probe and probe.get("mode"):  # la ricerca (in un thread a parte) ha già provato i modi: niente attese qui
            warm = 0.5 if probe.get("black") else 1.0  # già vista nera: inutile aspettare l'esposizione
            self.cap, self.mode, frame, self.black = open_capture(index, warm=warm, first=probe["mode"],
                                                                  only_first=True)
        else:
            self.cap, self.mode, frame, self.black = open_capture(index, warm=1.0, only_first=True)
        if self.cap is None:
            raise RuntimeError(tr("camera {0} non disponibile", index))
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._dark_since = time.time() - 2.0 if self.black else None  # aperta nera: resta «nera» da subito
        self._checked = 0.0
        super().__init__()
        if frame is not None:
            with self._lock:
                self._frame, self._t = frame, time.time()
                self.size = (frame.shape[1], frame.shape[0])

    def _grab(self):
        ok, f = self.cap.read()
        if not ok:
            return None
        now = time.time()
        if now - self._checked > 1.0:  # ogni secondo: l'immagine è diventata nera (o è tornata)?
            self._checked = now
            dark = is_black(f)
            if dark and self._dark_since is None:
                self._dark_since = now
            elif not dark:
                self._dark_since = None
            self.black = dark and now - self._dark_since >= 2.0
        return f

    def close(self):
        super().close()
        time.sleep(0.1)
        self.cap.release()


class NetCamera(_FrameSource):
    """Telecamera di rete: una foto alla volta da un indirizzo http (Falcon A1 Pro, A1C, T1: porta 8080,
    /media/getCapturePhoto) o un flusso rtsp. Il server della macchina è lento (circa 1 s a foto) e si blocca se
    riceve due richieste insieme o una richiesta interrotta: una sola richiesta alla volta, attesa lunga, e durante
    il lavoro (quando la macchina non manda foto) resta l'ultima immagine buona."""

    def __init__(self, url, interval=1.0, timeout=12.0):
        self.index = url
        self.url = url
        self.interval = interval
        self.timeout = timeout
        self.method = None
        self.black = False
        self.error = ""
        self.fails = 0
        self._last = 0.0
        self._cap = None
        self._rtsp = url.lower().startswith("rtsp://")
        super().__init__()

    def _grab(self):
        if self._rtsp:
            if self._cap is None:  # aperto qui, nel thread di lettura: un indirizzo sbagliato non blocca la finestra
                self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                if not self._cap.isOpened():
                    self.error = tr("flusso video non disponibile: {0}", safe_url(self.url))
                    self._cap.release()
                    self._cap = None
                    time.sleep(3.0)
                    return None
            ok, f = self._cap.read()
            return f if ok else None
        wait = self.interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        if not self._running:
            return None
        self._last = time.time()
        img, m, why = fetch_snapshot(self.url, self.timeout, self.method)
        if img is None:
            self.fails += 1
            self.error = why
            if self.fails in (1, 5) or self.fails % 30 == 0:
                cam_log(f"rete {safe_url(self.url)}: nessuna foto ({why}), tentativo {self.fails}")
            if self.method and self.fails >= 3:
                self.method = None  # riprovo anche l'altro modo di chiedere la foto
            time.sleep(min(5.0, 0.5 * self.fails))
            return None
        if self.method != m or self.fails:
            cam_log(f"rete {safe_url(self.url)}: {why}")
        self.method, self.fails, self.error = m, 0, ""
        self.black = is_black(img)
        return img

    def get(self, after=0.0, timeout=4.0):
        # una foto dalla rete arriva in 1–3 secondi: chi aspetta una foto nuova (calibrazione) aspetta di più
        return super().get(after, timeout if after <= 0 else max(timeout, self.timeout + self.interval + 2))

    def close(self):
        super().close()
        if self._cap is not None:
            time.sleep(0.1)
            self._cap.release()


def probe_net(text, timeout=12.0):
    """Prova un indirizzo: (url, immagine | None, spiegazione). Prima controlla che la porta risponda, per non
    aspettare 12 secondi un indirizzo sbagliato."""
    url = net_url(text)
    if not url:
        return "", None, tr("Indirizzo vuoto")
    if url.lower().startswith("rtsp://"):
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        ok, f = cap.read() if cap.isOpened() else (False, None)
        cap.release()
        return url, (f if ok else None), ("rtsp" if ok else tr("Il flusso video non risponde"))
    import urllib.parse

    u = urllib.parse.urlsplit(url)
    host, port = u.hostname or "", u.port or (443 if u.scheme == "https" else 80)
    if not port_open(host, port, 2.0):
        cam_log(f"rete {safe_url(url)}: porta {port} chiusa o macchina irraggiungibile")
        return url, None, tr("Nessuna risposta da {0} sulla porta {1}: controlla l'indirizzo e che la macchina sia "
                             "accesa e collegata.", host, port)
    img, m, why = fetch_snapshot(url, timeout)
    cam_log(f"prova rete {safe_url(url)}: {why}")
    return url, img, why


def auto_net_candidates(laser_port=None):
    """Indirizzi da provare da soli: il Falcon col cavo USB (192.168.10.1) e la macchina collegata in Wi-Fi."""
    out = [USB_NET_HOST]
    if isinstance(laser_port, str) and laser_port.startswith("tcp://"):
        h = laser_port[6:].split(":")[0]
        if h and h not in out:
            out.append(h)
    return out


class SimCamera(_FrameSource):
    """Camera virtuale che inquadra il simulatore con prospettiva e lente "fish-eye" note.
    Serve a provare (e collaudare) AutoCam senza hardware."""

    PPM = 2.0
    W, H = 1280, 720

    def __init__(self, sim, occlude=False, k=0.10, seed=1, view=1.0, gantry=False):
        """view > 1: camera montata bassa, vede solo la parte centrale del piano."""
        self.index = SIM_CAMERA
        self.gantry = gantry
        self.sim = sim
        self.occlude = occlude
        self.k = k
        self.rng = np.random.default_rng(seed)
        bx, by = float(sim.settings[130]), float(sim.settings[131])
        self.bed = (bx, by)
        self.tw, self.th = int(bx * self.PPM), int(by * self.PPM)
        src = np.float32([[0, self.th], [self.tw, self.th], [self.tw, 0], [0, 0]])  # (0,0) (X,0) (X,Y) (0,Y)
        dst = np.float32([[250, 690], [1040, 676], [935, 88], [322, 104]])
        dst = (dst - np.float32([640, 390])) * view + np.float32([640, 390])
        self.Hpx = cv2.getPerspectiveTransform(src, dst)
        self.c = np.array([self.W / 2, self.H / 2])
        self.f = math.hypot(self.W / 2, self.H / 2)
        jj, ii = np.meshgrid(np.arange(self.W, dtype=np.float32), np.arange(self.H, dtype=np.float32))
        xd, yd = (jj - self.c[0]) / self.f, (ii - self.c[1]) / self.f
        g = 1 + self.k * (xd * xd + yd * yd)
        ux, uy = self.c[0] + xd * g * self.f, self.c[1] + yd * g * self.f
        # da pixel camera "senza lente" a pixel della vista dall'alto
        pts = np.stack([ux.ravel(), uy.ravel()], axis=1).reshape(-1, 1, 2).astype(np.float64)
        top = cv2.perspectiveTransform(pts, np.linalg.inv(self.Hpx)).reshape(self.H, self.W, 2)
        self.mx = top[..., 0].astype(np.float32)
        self.my = top[..., 1].astype(np.float32)
        base = np.full((self.th, self.tw, 3), (176, 196, 214), np.uint8)  # cartone chiaro (BGR)
        for y in range(0, self.th, 18):
            cv2.line(base, (0, y), (self.tw, y + 6), (168, 188, 206), 1)
        self.material = base
        self._marks_done = 0
        super().__init__()

    def _top(self, x, y):
        return int(round(x * self.PPM)), int(round(self.th - y * self.PPM))

    def true_img(self, bed_pts):
        """Posizione vera in pixel di punti del piano (per misurare l'errore nei test)."""
        bed_pts = np.atleast_2d(np.asarray(bed_pts, float))
        top = np.stack([bed_pts[:, 0] * self.PPM, self.th - bed_pts[:, 1] * self.PPM], axis=1)
        u = cv2.perspectiveTransform(top.reshape(-1, 1, 2), self.Hpx).reshape(-1, 2)
        xu = (u - self.c) / self.f
        xd = xu.copy()
        for _ in range(30):
            xd = xu / (1 + self.k * (xd ** 2).sum(axis=1, keepdims=True))
        return self.c + xd * self.f

    def _grab(self):
        time.sleep(1 / 15)
        sim = self.sim
        if not sim.is_open:
            return None
        marks = sim.burn_marks
        while self._marks_done < len(marks):
            x, y = sim.to_bed(*marks[self._marks_done])
            cv2.circle(self.material, self._top(x, y), int(0.45 * self.PPM) + 1, (52, 58, 66), -1, cv2.LINE_AA)
            self._marks_done += 1
        img = self.material.copy()
        x, y = sim.to_bed(sim.pos[0], sim.pos[1])
        firing = sim.state == "Run" and sim.power > 0
        # testa: il corpo sta più in alto del piano, quindi dalla camera appare spostato
        off = 0 if self.occlude else 38
        hx0, hy0 = self._top(x - 22, y + off + 30)
        hx1, hy1 = self._top(x + 22, y + off - 18)
        if firing:
            cx, cy = self._top(x, y)
            glow = np.zeros_like(img)
            cv2.circle(glow, (cx, cy), 9, (255, 190, 90), -1, cv2.LINE_AA)
            glow = cv2.GaussianBlur(glow, (0, 0), 3)
            img = cv2.add(img, glow)
            cv2.circle(img, (cx, cy), 2, (255, 240, 220), -1, cv2.LINE_AA)
        if self.gantry:  # trave dell'asse X: attraversa tutto il piano e si muove con la testa
            gx0, gy0 = self._top(-20, y + off + 14)
            gx1, gy1 = self._top(self.bed[0] + 20, y + off - 10)
            cv2.rectangle(img, (gx0, gy0), (gx1, gy1), (70, 66, 60), -1)
        cv2.rectangle(img, (hx0, hy0), (hx1, hy1), (40, 38, 36), -1)
        cam = cv2.remap(img, self.mx, self.my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(30, 30, 30))
        gain = self.rng.uniform(0.97, 1.03)
        noise = self.rng.normal(0, 2.0, cam.shape)
        return np.clip(cam.astype(np.float32) * gain + noise, 0, 255).astype(np.uint8)


# ======================================================================= AutoCam
class CalibrationCancelled(Exception):
    pass


class AutoCam(QObject):
    progress = Signal(int, int, str)  # passo, totale, testo
    detected = Signal(object)  # lista di (u, v) trovati finora, per disegnarli sull'anteprima
    need_user = Signal(str)  # serve un'azione dell'utente (poi continue_() o cancel())
    finished = Signal(object, str)  # CameraModel | None, messaggio
    photo_ready = Signal(object)  # 0.17.5, metodo "photo": foto dei dischi incisi per metterli a mano

    def __init__(self, ctl, cam, profile, grid_n=5, method="auto"):
        super().__init__()
        self.ctl = ctl
        self.cam = cam
        self.profile = profile
        self.grid_n = grid_n
        self.method = method
        self._cancel = threading.Event()
        self._go = threading.Event()
        self._ok_user = False
        self.used_method = None
        self.visible = None
        self.target_grid = None
        # 0.17.5: per la correzione a mano dei dischi incisi
        self.last_photo = None  # foto finale (testa parcheggiata) del bersaglio inciso
        self.park = None  # dove è stata parcheggiata la testa
        self.park_hint = None  # parcheggio già noto (dalla calibrazione salvata): niente giro per cercarlo
        self.guess = {}  # {indice del disco: (u, v)} trovati da soli, anche quelli scartati

    # ---- controllo dall'interfaccia
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self._cancel.set()
        self._go.set()

    def continue_(self):
        self._ok_user = True
        self._go.set()

    # ---- utilità
    def _check(self):
        if self._cancel.is_set():
            raise CalibrationCancelled()
        if not self.ctl.connected:
            raise RuntimeError(tr("macchina disconnessa"))
        if self.ctl.last_status.get("state") == "Alarm":
            raise RuntimeError(tr("la macchina è in allarme: sblocca o fai l'homing e riprova"))

    def _wait_idle(self, timeout=60):
        time.sleep(0.3)
        end = time.time() + timeout
        seen, stable = 0.0, 0
        while time.time() < end:
            self._check()
            st = self.ctl.last_status.get("state")
            if not self.ctl.busy and st == "Idle" and self.ctl.status_time > seen:
                seen = self.ctl.status_time
                stable += 1
                if stable >= 2:
                    return
            elif st != "Idle":
                stable = 0
            time.sleep(0.05)
        raise RuntimeError(tr("la macchina non ha finito il movimento in tempo"))

    def _wait_state(self, states, timeout=4):
        end = time.time() + timeout
        while time.time() < end:
            self._check()
            if self.ctl.last_status.get("state") in states:
                return True
            time.sleep(0.02)
        return False

    def _ask(self, text):
        self._go.clear()
        self._ok_user = False
        self.need_user.emit(text)
        self._go.wait()
        if self._cancel.is_set() or not self._ok_user:
            raise CalibrationCancelled()

    def _s(self, pct):
        return pct / 100.0 * self.profile.s_max

    # ---- procedura
    def _run(self):
        if self.method == "photo":  # 0.17.5: solo la foto dei dischi già incisi, per metterli a mano
            try:
                self._check()
                park = tuple(self.park_hint) if self.park_hint else self._park()[0]
                self.progress.emit(0, 1, tr("Sposto la testa fuori dall'inquadratura e faccio la foto…"))
                self._goto_bed(*park)
                self._wait_idle()
                self.park = park
                self.last_photo = cc._avg(self.cam.frames(3, after=time.time() + 0.3))
                self.target_grid = [g[:2] for g in cc.seq_grid(self.profile.bed_x, self.profile.bed_y)]
                self.photo_ready.emit(self)
                self.finished.emit(None, "")
            except CalibrationCancelled:
                self.finished.emit(None, tr("Annullato"))
            except Exception as exc:  # noqa: BLE001
                self.finished.emit(None, tr("Foto non riuscita: {0}", exc))
            return
        try:
            model, msg = self._calibrate()
            self.finished.emit(model, msg)
        except CalibrationCancelled:
            self._safe_off()
            self.finished.emit(None, "Calibrazione annullata")
        except Exception as exc:  # noqa: BLE001
            self._safe_off()
            self.finished.emit(None, f"Calibrazione interrotta: {exc}")

    def _safe_off(self):
        try:
            if self.ctl.connected:
                self.ctl.send_line("M5 S0")
        except Exception:  # noqa: BLE001
            pass

    def _calibrate(self):
        bx, by = self.profile.bed_x, self.profile.bed_y
        grid = cc.calibration_grid(bx, by, self.grid_n)
        size = self.cam.size
        if self.method in ("auto", "spot"):
            pairs = self._spot_method(grid)
            if pairs is not None and len(pairs) >= 9:
                model = cc.fit_with_validation([p[0] for p in pairs], [p[1] for p in pairs], (bx, by), self.cam.size)
                if model.rms_mm <= 1.5 or self.method == "spot":
                    self.used_method = "puntino laser"
                    return model, self._result_text(model, len(pairs), len(grid))
            if self.method == "spot":
                return None, tr("Il puntino laser non è stato visto abbastanza: prova il metodo con bersaglio inciso")
        pairs = self._sequential_method()
        tot = len(self.target_grid or grid)
        if len(pairs) < 9:
            return None, (tr("Trovati solo {0} cerchi su {1}: controlla che il cartone sia nella zona inquadrata e ben illuminato", len(pairs), tot))
        model = cc.fit_with_validation([p[0] for p in pairs], [p[1] for p in pairs], (bx, by), self.cam.size or size)
        if self.visible is not None:
            # oltre l'ultimo cerchio la correzione vale ancora per poco
            vis = cc.limit_to_points(model, [p[0] for p in pairs], bx, by)
            if vis is not None:
                self.visible = vis
        self.used_method = "bersaglio inciso"
        return model, self._result_text(model, len(pairs), tot)

    def _result_text(self, model, found, total):
        txt = (f"Calibrazione riuscita ({self.used_method}): {found}/{total} punti, "
               f"precisione ±{model.rms_mm:.2f} mm (peggiore {model.max_mm:.2f} mm)")
        vis = getattr(self, "visible", None)
        if vis is not None:
            bx, by = self.profile.bed_x, self.profile.bed_y
            x, y, w, h = vis
            cover = min(1.0, (w * h) / (bx * by))
            if cover < 0.93:
                k = max(bx / max(w, 1), by / max(h, 1))
                txt += (tr("\nLa camera vede circa {0:.0f} × {1:.0f} mm (da X{2:.0f} Y{3:.0f}), il {4:.0f}% del piano: fuori da questa zona la foto non c'è. Per vederlo tutto, alzala di circa ×{5:.1f} (altezza attuale × ", w, h, x, y, cover * 100, k) + f"{k:.1f}" + tr(") oppure usa un obiettivo più grandangolare."))
        return txt

    # ---- A) puntino laser
    def _fire_spot(self, pct):
        s = self._s(pct)
        for line in (f"M3 S{s:.0f}", "G91 G1 X0.3 F30", "G1 Y0.3", "G1 X-0.3", "G1 Y-0.3", "G90 M5 S0"):
            self.ctl.send_line(line)

    def _goto_bed(self, x, y):
        mx, my = self.profile.to_machine(x, y)
        self.ctl.goto_machine(mx, my, 6000)

    def _spot_at(self, x, y, pct):
        self._goto_bed(x, y)
        self._wait_idle()
        off = self.cam.frames(3, after=time.time() + 0.15)
        self._fire_spot(pct)
        if not self._wait_state(("Run",), timeout=4):
            self._wait_idle()
            return None
        on = self.cam.frames(3, after=time.time() + 0.3)
        self._wait_idle()
        if len(off) < 2 or len(on) < 2:
            raise RuntimeError(tr("la camera non sta inviando immagini"))
        pt, _peak = cc.detect_spot(off, on)
        return pt

    def _spot_method(self, grid):
        total = len(grid)
        found = []
        pct = 1.0
        self.progress.emit(0, total, tr("Cerco il puntino laser all'1%…"))
        first = self._spot_at(*grid[0], pct)
        if first is None:
            pct = 3.0
            self.progress.emit(0, total, tr("Non lo vedo: riprovo al 3%…"))
            first = self._spot_at(*grid[0], pct)
        if first is None:
            self.progress.emit(0, total, tr("Il puntino non è visibile: passo al bersaglio inciso"))
            return None
        found.append((grid[0], first))
        self.detected.emit([p[1] for p in found])
        misses = 0
        for i, (x, y) in enumerate(grid[1:], start=1):
            self._check()
            self.progress.emit(i, total, tr("Punto {0} di {1}  ·  X{2:.0f} Y{3:.0f}", i + 1, total, x, y))
            pt = self._spot_at(x, y, pct)
            if pt is None:
                misses += 1
                if misses > total * 0.3:
                    self.progress.emit(i, total, tr("Troppi punti non visti: passo al bersaglio inciso"))
                    return None
                continue
            found.append(((x, y), pt))
            self.detected.emit([p[1] for p in found])
        self.progress.emit(total, total, "Calcolo lente e prospettiva…")
        return found

    # ---- B) bersaglio inciso
    def _head_views(self, corners):
        """Scatti con la testa in punti diversi: mediana = piano senza testa; differenze = dove sta la testa."""
        shots = []
        for x, y in corners:
            self._check()
            self._goto_bed(x, y)
            self._wait_idle()
            shots.append(cc._avg(self.cam.frames(3, after=time.time() + 0.15)))
        stack = np.stack(shots)
        background = np.median(stack, axis=0)
        heads = []
        for s in shots:
            d = cv2.cvtColor(np.abs(s - background).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
            d = cv2.GaussianBlur(d, (0, 0), 3)
            peak = float(d.max())
            mask = (d >= peak * 0.5).astype(np.uint8)
            n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
            k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) if n > 1 else None
            heads.append(tuple(cents[k]) if k else None)
        return background, heads

    # ---- B) bersaglio inciso, un disco alla volta
    def _park(self):
        """Posizione di parcheggio: quella in cui testa e trave coprono meno l'inquadratura.
        Si sceglie fra angoli e metà dei lati confrontando le foto con la mediana."""
        bx, by = self.profile.bed_x, self.profile.bed_y
        m = 15.0  # non troppo vicino ai bordi: alcune schede hanno una corsa reale un po' più corta del piano
        cands = [(m, m), (bx - m, m), (bx / 2, m), (m, by - m), (bx - m, by - m), (bx / 2, by - m),
                 (m, by / 2), (bx - m, by / 2)]
        shots = []
        for i, (x, y) in enumerate(cands):
            self._check()
            self.progress.emit(i, len(cands), tr("Cerco dove parcheggiare la testa fuori dall'inquadratura…"))
            self._goto_bed(x, y)
            self._wait_idle()
            shots.append(cc._avg(self.cam.frames(3, after=time.time() + 0.2)))
        bg = np.median(np.stack(shots), axis=0)
        cover = [float((cv2.cvtColor(np.clip(np.abs(sh - bg), 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY) > 25).mean())
                 for sh in shots]
        k = int(np.argmin(cover))
        return cands[k], cover[k]

    def _burn_disc(self, x, y):
        wx, wy = self.ctl.wco
        mx, my = self.profile.to_machine(x, y)
        ux, uy = mx - wx, my - wy
        s = self._s(40)
        job = ["G90 G21", "M4 S0"]
        for r in (2.0, 1.5, 1.0, 0.5):  # disco pieno Ø 4 mm
            job += [f"G0 X{ux + r:.3f} Y{uy:.3f}", f"G1 F1000 S{s:.0f}", f"G2 X{ux + r:.3f} Y{uy:.3f} I{-r:.3f} J0", "S0"]
        job += ["M5 S0"]
        done = threading.Event()
        result = {}

        def on_done(ok, msg):
            result.update(ok=ok, msg=msg)
            done.set()

        self.ctl.job_finished.connect(on_done)
        try:
            self.ctl.stream_job(job)
            while not done.wait(0.1):
                self._check()
        finally:
            try:
                self.ctl.job_finished.disconnect(on_done)
            except (RuntimeError, TypeError):
                pass
        if not result.get("ok"):
            raise RuntimeError(result.get("msg", "incisione interrotta"))
        self._wait_idle()

    def _sequential_method(self, n=6):
        """Incide un disco alla volta su una griglia n×n di tutto il piano e dopo ognuno fotografa con la testa
        parcheggiata sempre nello stesso punto: la sola differenza fra due foto è il disco nuovo, quindi ogni
        disco si riconosce senza ambiguità. Funziona anche se la camera vede solo una parte del piano o se
        trave e testa coprono l'inquadratura."""
        bx, by = self.profile.bed_x, self.profile.bed_y
        self._ask(tr("Metti sul piano un cartone o un compensato chiaro, ben piatto e a fuoco, il più grande possibile.\nFreeLaserCut inciderà fino a {0} dischi (Ø 4 mm, 40%) uno alla volta e dopo ognuno farà una foto con la testa parcheggiata: i dischi fuori dall'inquadratura vengono semplicemente ignorati.\n\nOcchiali protettivi indossati e aspirazione accesa?", n * n))
        park, cover = self._park()
        self.park = park
        grid = [g[:2] for g in cc.seq_grid(bx, by, n)]  # stesso ordine di prima (serpentina dallo zero)
        self.target_grid = grid
        self.guess = {}
        self._goto_bed(*park)
        self._wait_idle()
        prev = cc._avg(self.cam.frames(3, after=time.time() + 0.25))
        H_img, W_img = prev.shape[:2]
        pairs = []
        for i, (x, y) in enumerate(grid):
            self._check()
            self.progress.emit(i, len(grid), tr("Disco {0} di {1}  ·  X{2:.0f} Y{3:.0f}  ·  visti finora {4}", i + 1, len(grid), x, y, len(pairs)))
            self._burn_disc(x, y)
            self._goto_bed(*park)
            self._wait_idle()
            cur = cc._avg(self.cam.frames(3, after=time.time() + 0.25))
            blobs = cc.find_dark_blobs([prev], [cur], min_area=6)
            prev = cur
            if not blobs:
                continue
            blobs.sort(key=lambda b: -b[2])
            u, v, strength = blobs[0]
            # un solo disco nuovo: la macchia più forte deve staccarsi bene dalle altre (luce che cambia, polvere)
            if len(blobs) > 1 and blobs[1][2] > 0.5 * strength:
                continue
            if not (3 < u < W_img - 3 and 3 < v < H_img - 3):
                continue
            self.guess[i] = (u, v)
            pairs.append(((x, y), (u, v)))
            self.detected.emit([p[1] for p in pairs])
        if len(pairs) >= 6:  # scarto le associazioni sbagliate (riflessi, polvere): devono stare su una prospettiva
            bp = np.float32([p[0] for p in pairs])
            ip = np.float32([p[1] for p in pairs])
            _H, inl = cv2.findHomography(bp, ip, cv2.RANSAC, 0.025 * math.hypot(W_img, H_img))
            if inl is not None:
                pairs = [p for p, k in zip(pairs, inl.ravel()) if k]
                keep = {p[0] for p in pairs}
                self.guess = {i: uv for i, uv in self.guess.items() if grid[i] in keep}
        self.last_photo = prev  # foto finale, testa parcheggiata: serve per correggere i punti a mano
        self.visible = (0.0, 0.0, bx, by)  # attiva il calcolo della zona vista in _calibrate
        self.progress.emit(len(grid), len(grid), "Calcolo lente e prospettiva…")
        return pairs

    def _scan_view(self, n=5):
        """La testa visita una griglia n×n: dove la camera la vede si stima l'inquadratura
        (omografia grezza) e si scopre quale parte del piano è davvero visibile."""
        bx, by = self.profile.bed_x, self.profile.bed_y
        m = 15.0
        xs = np.linspace(m, bx - m, n)
        ys = np.linspace(m, by - m, n)
        pts = []
        for j, y in enumerate(ys):
            pts += [(float(x), float(y)) for x in (xs if j % 2 == 0 else xs[::-1])]
        shots = []
        for i, (x, y) in enumerate(pts):
            self._check()
            self.progress.emit(i, len(pts) + 4, tr("Guardo dove la camera vede la testa: {0} di {1}", i + 1, len(pts)))
            self._goto_bed(x, y)
            self._wait_idle()
            shots.append(cc._avg(self.cam.frames(3, after=time.time() + 0.15)))
        stack = np.stack(shots)
        bg = np.median(stack, axis=0)
        H_img, W_img = bg.shape[:2]
        heads = []
        for s in shots:
            d = cv2.cvtColor(np.clip(np.abs(s - bg), 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
            d = cv2.GaussianBlur(d, (0, 0), 3)
            peak = float(d.max())
            if peak < 18:  # niente di diverso: la testa è fuori inquadratura
                heads.append(None)
                continue
            mask = (d >= peak * 0.5).astype(np.uint8)
            k, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
            if k <= 1:
                heads.append(None)
                continue
            j = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            x0, y0, w0, h0, area = stats[j]
            edge = x0 <= 2 or y0 <= 2 or x0 + w0 >= W_img - 3 or y0 + h0 >= H_img - 3
            heads.append(None if edge or area < 0.0004 * W_img * H_img else tuple(cents[j]))
        return pts, shots, bg, heads

    def _visible_grid(self, H, frame_size, n):
        """Griglia di bersagli dentro la parte di piano che la camera vede (stima dall'omografia grezza)."""
        bx, by = self.profile.bed_x, self.profile.bed_y
        W_img, H_img = frame_size
        ins = 0.06
        img_poly = np.float32([[W_img * ins, H_img * ins], [W_img * (1 - ins), H_img * ins],
                               [W_img * (1 - ins), H_img * (1 - ins)], [W_img * ins, H_img * (1 - ins)]])
        bed_poly = cv2.perspectiveTransform(img_poly.reshape(-1, 1, 2), np.linalg.inv(H)).reshape(-1, 2)
        m = 12.0
        x0, x1 = max(m, bed_poly[:, 0].min()), min(bx - m, bed_poly[:, 0].max())
        y0, y1 = max(m, bed_poly[:, 1].min()), min(by - m, bed_poly[:, 1].max())
        poly = bed_poly.astype(np.float32).reshape(-1, 1, 2)
        for nn in (n, n + 1, n + 2):
            xs = np.linspace(x0, x1, nn)
            ys = np.linspace(y0, y1, nn)
            grid = []
            for j, y in enumerate(ys):
                for x in (xs if j % 2 == 0 else xs[::-1]):
                    if cv2.pointPolygonTest(poly, (float(x), float(y)), True) >= 3.0:
                        grid.append((float(x), float(y)))
            if len(grid) >= 16:
                break
        vis_w, vis_h = max(0.0, x1 - x0 + 2 * m), max(0.0, y1 - y0 + 2 * m)
        return grid, (x0 - m, y0 - m, vis_w, vis_h)

    def _target_method(self, grid):
        n = self.grid_n
        self._ask(tr("Metti sul piano un foglio di cartone o compensato chiaro, ben piatto e a fuoco, nella zona "
                  "inquadrata dalla camera.\nPrima la testa farà un giro del piano a laser spento per capire cosa "
                  "vede la camera, poi inciderà piccoli dischi (Ø 4 mm) al 40% di potenza solo dove la camera "
                  "arriva.\n\nOcchiali protettivi indossati e aspirazione accesa?"))
        pts, shots, bg, heads = self._scan_view(5)
        seen = [(p, h) for p, h in zip(pts, heads) if h is not None]
        if len(seen) < 4:
            raise RuntimeError(tr("la camera vede la testa solo in {0} punti su {1}: alzala o orientala verso il centro del piano e riprova", len(seen), len(pts)))
        Hc, inl = cv2.findHomography(np.float32([p for p, _ in seen]), np.float32([h for _, h in seen]), cv2.RANSAC,
                                     0.05 * math.hypot(*bg.shape[1::-1]))
        if Hc is None:
            raise RuntimeError(tr("non riesco a capire l'inquadratura: la camera vede il piano?"))
        size = (bg.shape[1], bg.shape[0])
        grid, vis = self._visible_grid(Hc, size, n)
        self.visible = vis
        if len(grid) < 9:
            raise RuntimeError(tr("la parte di piano vista dalla camera è troppo piccola: alzala o allarga l'inquadratura"))
        total = len(grid) + 3
        # piano "senza testa": mediana degli scatti agli angoli e al centro del giro
        idx = sorted({0, 4, len(pts) - 1, len(pts) - 5, len(pts) // 2})
        before = np.median(np.stack([shots[i] for i in idx]), axis=0)
        bed_corners = [pts[i] for i in idx]
        coarse = Hc
        self.progress.emit(len(pts), len(pts) + total, tr("Incido {0} cerchi nella zona vista dalla camera…", len(grid)))
        wx, wy = self.ctl.wco
        job = ["G90 G21", "M4 S0"]
        s = self._s(40)
        for (x, y) in grid:
            mx, my = self.profile.to_machine(x, y)
            ux, uy = mx - wx, my - wy  # coordinate di lavoro del G-code
            # disco pieno Ø 4 mm: ben visibile anche su cartone scuro o con la camera lontana
            for r in (2.0, 1.5, 1.0, 0.5):
                job += [f"G0 X{ux + r:.3f} Y{uy:.3f}", f"G1 F1000 S{s:.0f}",
                        f"G2 X{ux + r:.3f} Y{uy:.3f} I{-r:.3f} J0", "S0"]
        job += ["M5 S0"]
        done = threading.Event()
        result = {}

        def on_done(ok, msg):
            result["ok"] = ok
            result["msg"] = msg
            done.set()

        self.ctl.job_finished.connect(on_done)
        try:
            self.ctl.stream_job(job)
            while not done.wait(0.2):
                self._check()
        finally:
            try:
                self.ctl.job_finished.disconnect(on_done)
            except (RuntimeError, TypeError):
                pass
        if not result.get("ok"):
            raise RuntimeError(result.get("msg", "incisione interrotta"))
        self._wait_idle()
        self.progress.emit(len(grid) + 2, total, tr("Foto del bersaglio inciso…"))
        after, _ = self._head_views(bed_corners)
        expected = cv2.perspectiveTransform(np.float32(grid).reshape(-1, 1, 2), coarse).reshape(-1, 2)
        sp = float(np.median(np.linalg.norm(np.diff(expected, axis=0), axis=1)))
        blobs = cc.find_dark_blobs([before], [after])
        found_img = cc.match_grid(blobs, expected, grid, max(sp, 20))
        pairs = [(g, p) for g, p in zip(grid, found_img) if p is not None]
        self.target_grid = grid
        self.detected.emit([p[1] for p in pairs])
        self.progress.emit(total, total, "Calcolo lente e prospettiva…")
        return pairs
