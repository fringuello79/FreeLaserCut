# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.1: il Wi-Fi dopo la prima prova su un laser vero (un Mecpow, scheda «THMG LS WIFI V1.1»; rapporti
FLC-20261112-2153 e FLC-20261112-2235 di un utente).

Che cosa era successo, e che cosa si prova qui:
1. Il laser, collegato via Wi-Fi, cadeva dopo 5 secondi: la ricerca della telecamera di rete apriva un secondo
   collegamento sull'indirizzo e la porta dei comandi (8080), e la scheda, che ne accetta uno solo, chiudeva quello
   buono. -> Su quell'indirizzo e quella porta non parte più niente (né ricerca, né telecamera di rete, né «Trova il
   laser in rete»).
2. «È in rete, ma non accetta i comandi» era falso: il controllo si fermava al primo «ok» (quello della riga vuota).
3. Il Mecpow accetta nome, password e «rete di casa» ma al riavvio decide l'interruttore «$wifi»: la procedura ora lo
   legge e scrive «$wifi=1»; in rete la scheda non dice «Connected with…» ma «TELNET Started 8080».
4. Esito nuovo «La scheda non ha provato a collegarsi» quando la rete propria riparte subito senza tentativo.

Il dato: scheda (interruttore sì/no, valore 0/1) × rete (giusta, sbagliata) × che cosa dice al riavvio (niente,
«Connecting», «TELNET Started», rete propria subito o dopo un tentativo) × collegamento del laser (USB, rete).
"""
import ast
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_PROVA_RETE"] = "1"  # gli indirizzi 127.0.0.x valgono come «rete locale»
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import camera, camera_panel, diag  # noqa: E402
from freelasercut import wifi_setup as ws  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.sim import SimSerial  # noqa: E402
from freelasercut.ui import dialogs_wifi as dw  # noqa: E402

results = []
hidden = []
sys.excepthook = lambda *a: hidden.append(a[1])
HOME_NET = "CasaMia"
INFO = b"[PRODUCER:THMG LS WIFI V1.1]\r\n[VER:1.1h.20260130:]\r\n[OPT:VPH,63,512]\r\n[MSG:Using machine:THMG LS WIFI V1.1]\r\n"


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


class Board(threading.Thread):
    """La porta dei comandi di una scheda vera, come si è comportata quella del Mecpow: un collegamento solo (se ne
    arriva un altro chiude quello di prima), «ok» subito a una riga vuota, la risposta a «$I» un attimo dopo."""

    def __init__(self, host="127.0.0.1", port=0, grbl=True):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((host, port))
        self.srv.listen(8)
        self.host, self.port = host, self.srv.getsockname()[1]
        self.grbl, self.alive = grbl, True
        self.cur, self.accepted, self.kicked, self.seen = None, 0, 0, []
        self.start()

    def run(self):
        while self.alive:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self.accepted += 1
            old, self.cur = self.cur, c
            if old is not None:  # un secondo collegamento: la scheda chiude il primo
                self.kicked += 1
                try:
                    old.shutdown(socket.SHUT_RDWR)
                    old.close()
                except OSError:
                    pass
            threading.Thread(target=self.serve, args=(c,), daemon=True).start()

    def serve(self, c):
        buf = b""
        try:
            while True:
                data = c.recv(1024)
                if not data:
                    break
                buf += data
                while b"\n" in buf or b"\r" in buf or b"?" in buf:
                    if buf[:1] == b"?":
                        buf = buf[1:]
                        c.sendall(b"<Idle|MPos:0.000,0.000,0.000|FS:0,0>\r\n")
                        continue
                    i = min(x for x in (buf.find(b"\n"), buf.find(b"\r")) if x >= 0) if (b"\n" in buf or b"\r" in buf) else -1
                    if i < 0:
                        break
                    line, buf = buf[:i].replace(b"?", b"").strip(), buf[i + 1:]
                    self.seen.append(line.decode("utf-8", "replace"))
                    if not self.grbl:
                        c.sendall(b"HTTP/1.0 400 Bad Request\r\n\r\n")
                        c.close()
                        return
                    if not line:
                        c.sendall(b"ok\r\n")
                    elif line.upper() == b"$I":
                        time.sleep(0.15)  # la risposta vera arriva dopo l'«ok» della riga vuota, in un altro pacchetto
                        c.sendall(INFO + b"ok\r\n")
                    elif line.upper() == b"$$":
                        c.sendall(b"$130=410.000\r\n$131=410.000\r\nok\r\n")
                    elif line[:3].upper() in (b"GET", b"POS"):
                        c.sendall(b"error:2\r\n")
                    else:
                        c.sendall(b"ok\r\n")
        except OSError:
            pass
        if self.cur is c:
            self.cur = None

    def close(self):
        self.alive = False
        try:
            self.srv.close()
        except OSError:
            pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ================================================================== 1. «È in rete, ma non accetta i comandi» era falso
B1 = Board()
t0 = time.time()
hit = ws.probe("127.0.0.1", B1.port)
check("una scheda che risponde «ok» alla riga vuota prima della risposta a «$I» viene riconosciuta lo stesso",
      hit is not None and hit["port"] == B1.port and hit["ver"].startswith("[VER:1.1h.20260130") and time.time() - t0 < 2.0,
      (hit, time.time() - t0))
check("…con dentro le righe della scheda (servono a riconoscere lo stesso laser un'altra volta)",
      hit is not None and any("THMG" in line for line in hit["info"]))
other = Board(grbl=False)
check("chi risponde ma non è un laser (una stampante, una telecamera) resta escluso; una porta chiusa pure",
      ws.probe("127.0.0.1", other.port) is None and ws.probe("127.0.0.1", free_port()) is None)
found = ws.find_lasers(ws.subnet_hosts("127.0.0.9"), (B1.port, other.port), max_s=6.0)
check("«Trova il laser in rete» trova quella scheda", [(f["host"], f["port"]) for f in found] == [("127.0.0.1", B1.port)],
      found)
n0 = B1.accepted
found = ws.find_lasers(ws.subnet_hosts("127.0.0.9"), (B1.port,), max_s=3.0, skip=[("127.0.0.1", B1.port), None])
check("…ma non interroga l'indirizzo a cui si è già collegati (il collegamento buono cadrebbe)",
      found == [] and B1.accepted == n0, (found, B1.accepted - n0))
other.close()

# ================================================================== 2. telecamere: mai sulla porta dei comandi del laser
check("senza collegamento di rete non c'è niente da proteggere", camera.laser_link() is None
      and not camera.is_laser_link("192.168.1.220:8080") and camera.set_laser_link("COM6") is None
      and camera.set_laser_link(None) is None and camera.set_laser_link("simulatore") is None)
check("indirizzi letti in tutte le forme",
      camera.endpoint("tcp://192.168.1.220:8080") == ("192.168.1.220", 8080)
      and camera.endpoint("http://192.168.1.220:8080/media/getCapturePhoto") == ("192.168.1.220", 8080)
      and camera.endpoint("192.168.1.220:23") == ("192.168.1.220", 23)
      and camera.endpoint("http://192.168.1.220/foto.jpg") == ("192.168.1.220", 80)
      and camera.endpoint("192.168.1.220", 8080) == ("192.168.1.220", 8080)
      and camera.endpoint("") is None and camera.endpoint("tcp://:99") is None)
link = camera.set_laser_link("tcp://192.168.1.220:8080")
check("laser collegato a 192.168.1.220:8080: quell'indirizzo con quella porta è riconosciuto in tutte le forme",
      link == ("192.168.1.220", 8080) and camera.is_laser_link("192.168.1.220", 8080)
      and camera.is_laser_link("192.168.1.220") and camera.is_laser_link("http://192.168.1.220:8080/media/getCapturePhoto")
      and camera.is_laser_link("192.168.1.220:8080"))
check("…un'altra porta dello stesso laser, o un altro indirizzo, no (lì una telecamera può esserci)",
      not camera.is_laser_link("192.168.1.220", 80) and not camera.is_laser_link("http://192.168.1.220/foto.jpg")
      and not camera.is_laser_link("192.168.1.221") and not camera.is_laser_link("192.168.10.1"))
check("ricerca da soli: se i comandi passano dalla 8080 il laser non è fra gli indirizzi dove cercare una telecamera",
      camera.auto_net_candidates("tcp://192.168.1.220:8080") == [camera.USB_NET_HOST]
      and camera.auto_net_candidates("tcp://192.168.1.50:23") == [camera.USB_NET_HOST, "192.168.1.50"]
      and camera.auto_net_candidates("COM6") == [camera.USB_NET_HOST] and camera.auto_net_candidates(None) == [camera.USB_NET_HOST])
camera.set_laser_link(f"tcp://127.0.0.1:{B1.port}")
n0, s0 = B1.accepted, len(B1.seen)
url = f"http://127.0.0.1:{B1.port}{camera.NET_PATH}"
r_open = camera.port_open("127.0.0.1", B1.port)
r_info = camera.device_info(f"127.0.0.1:{B1.port}")
r_probe = camera.probe_net(f"127.0.0.1:{B1.port}")
r_snap = camera.fetch_snapshot(url, 2.0)
time.sleep(0.2)
check("con il laser collegato lì, nessuna delle richieste delle telecamere parte davvero (porta, modello, prova, foto)",
      r_open is False and r_info == "" and r_probe[1] is None and r_snap[0] is None and B1.accepted == n0
      and len(B1.seen) == s0, (r_open, r_info, r_probe[2], B1.accepted - n0, B1.seen[s0:]))
check("…e chi prova quell'indirizzo a mano legge perché («è l'indirizzo dei comandi del laser»)",
      "comandi del laser" in r_probe[2] and "comandi del laser" in r_snap[2], (r_probe[2], r_snap[2]))
camera.set_laser_link(None)
check("scollegato il laser la protezione finisce (la porta torna interrogabile)", camera.port_open("127.0.0.1", B1.port)
      and until(lambda: B1.accepted == n0 + 1, 2))
time.sleep(0.2)

# --- il caso vero: FreeLaserCut collegato via rete, la ricerca delle telecamere parte da sola
SCENE = np.full((120, 160, 3), 150, np.uint8)
opened = []


class FakeNet:
    error = ""

    def __init__(self, index, *a, **k):
        self.index, self.size, self.black, self.mode = index, (160, 120), False, "rete"
        opened.append(index)

    def get(self, after=0, timeout=0.1):
        return SCENE.copy()

    def close(self):
        opened.append(("chiusa", self.index))


camera_panel.list_cameras = lambda max_index=6, skip=(): []
camera_panel.NetCamera = FakeNet
camera.usb_camera_names = lambda: {}
camera.USB_NET_HOST = "127.0.0.250"  # niente attese su un indirizzo che non c'è
real_net_port, camera.NET_PORT = camera.NET_PORT, B1.port  # come sul Mecpow: comandi e «telecamera» sulla stessa porta
real_defaults, camera.port_open.__defaults__ = camera.port_open.__defaults__, (B1.port, 0.8)

from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ctl, cam = w.ctl, w.camera
type(ctl).WAKE_AFTER_S = 3600
until(lambda: not cam._searching, 8)
B1.seen.clear()
k0 = B1.kicked
PORT = f"tcp://127.0.0.1:{B1.port}"
ok_conn = ctl.connect_port(PORT)
check("(FreeLaserCut si collega alla scheda via rete)", ok_conn and ctl.connected and ctl.port == PORT
      and camera.laser_link() == ("127.0.0.1", B1.port), (ok_conn, camera.laser_link()))
searched = until(lambda: cam._searching, 3)
until(lambda: not cam._searching, 10)
until(lambda: False, 2.5)
check("la ricerca delle telecamere è partita da sola al collegamento (come sul PC dell'utente)", searched)
check("…e il collegamento con il laser NON cade: nessun secondo collegamento sulla porta dei comandi",
      ctl.connected and B1.kicked == k0, (ctl.connected, B1.kicked - k0))
check("…alla scheda non arriva nessuna richiesta da telecamera (prima le arrivava «GET /media/getCapturePhoto»)",
      not [s for s in B1.seen if s[:3].upper() in ("GET", "POS") or "HTTP" in s.upper()], B1.seen[:8])
i = cam.combo.count()
cam.combo.addItem("Rete · prova", url)
cam.combo.setCurrentIndex(i)
app.processEvents()
check("scelta a mano una «telecamera di rete» che è l'indirizzo dei comandi: non viene aperta, e dice perché",
      cam.src is None and url not in opened and "comandi del laser" in cam.state.text() and ctl.connected
      and B1.kicked == k0, (cam.state.text(), opened))
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)
check("scollegato il laser, il modulo delle telecamere lo sa", camera.laser_link() is None)
until(lambda: not cam._searching, 8)
cam.combo.setCurrentIndex(0)
cam.combo.setCurrentIndex(cam.combo.findData(url))
app.processEvents()
check("(a laser scollegato quella telecamera di rete si può aprire)", isinstance(cam.src, FakeNet) and cam.src.index == url)
ctl.connect_port(PORT)
app.processEvents()
check("…ma se poi il laser si collega proprio a quell'indirizzo, la telecamera viene chiusa subito e lo dice",
      cam.src is None and ("chiusa", url) in opened and "comandi del laser" in cam.state.text() and ctl.connected,
      (cam.state.text(), opened))
until(lambda: not cam._searching, 8)
until(lambda: False, 1.5)
check("…e il collegamento resta su", ctl.connected and B1.kicked == k0, B1.kicked - k0)
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)
until(lambda: not cam._searching, 8)
camera.NET_PORT = real_net_port
camera.port_open.__defaults__ = real_defaults
cam.combo.setCurrentIndex(0)

# ================================================================== 3. schede con l'interruttore «$wifi» (Mecpow)
check("riconoscimento dal produttore scritto dalla scheda",
      ws.has_wifi_switch(["[PRODUCER:THMG LS WIFI V1.1]", "[VER:1.1h.20260130:]"])
      and not ws.has_wifi_switch(["[VER:1.1.2022100101:MKS DLC32]"]) and not ws.has_wifi_switch(["[MSG:FW:LGT V1.2.3|MB:LS_ESP32]"])
      and not ws.has_wifi_switch([]) and not ws.has_wifi_switch(None))
check("lettura di «$wifi»", ws.parse_switch(["$wifi=0"]) == 0 and ws.parse_switch(["$Wifi = 1 "]) == 1
      and ws.parse_switch(["error:3"]) is None and ws.parse_switch([]) is None and ws.parse_switch(["$wifi=abc"]) is None)
check("messaggi: «TELNET Started 8080» = servizi di rete partiti, con la porta; «Client started» = sta provando",
      ws.parse_message("[MSG:TELNET Started 8080]") == ("services", "8080")
      and ws.parse_message("[MSG:Client started]") == ("connecting", "")
      and ws.parse_message("[MSG:Local access point MECPOW_30957 started, 192.168.4.1]") == ("own", "192.168.4.1")
      and ws.parse_message("[MSG:HTTP Started]") is None)
check("il comando in più per quelle schede è «$wifi=1»; le altre famiglie non ce l'hanno",
      ws.commands("esp", "switch") == ("$wifi=1",) and ws.commands("named", "switch") == ()
      and ws.commands("numeric", "switch") == ())


class Pc:
    """Il Wi-Fi del PC, finto (risponde come nmcli)."""

    def __init__(self):
        self.sys = ws.System(run=self.run, platform="linux")
        self.sys.local_ip = lambda: "127.0.0.9"

    def run(self, args, timeout=12, input_text=None):
        a = list(args)
        if a[:5] == ["nmcli", "-t", "-f", "TYPE,STATE", "dev"]:
            return 0, "wifi:connected\nethernet:connected\n"
        if "list" in a:
            return 0, f"yes:{HOME_NET}:80:2437 MHz:WPA2\nno:Vicino:30:2462 MHz:WPA2"
        return 0, ""


sent = []
ctl.line_sent.connect(sent.append)


def usb(kind, **wifi):
    if ctl.connected:
        ctl.disconnect_port()
        until(lambda: not ctl.connected, 3)
    SimSerial.preset = None
    ctl.connect_port(SIM_PORT)
    ctl.sim.speedup = 50
    wf = ctl.sim.wifi_board(kind, **wifi)
    until(lambda: ctl.last_status.get("state") == "Idle" and ctl.board_info and ctl.board_settings, 20)
    app.processEvents()
    sent.clear()
    return wf


def wizard():
    d = dw.WifiWizard(w, system=Pc().sys)
    d.start()
    return d


def to_state(d, *states, t=40.0):
    until(lambda: d.state in states, t)
    return d.state in states


def run_net(d, pwd="passwordgiusta"):
    if d.state == "B":
        d.press("net")
    to_state(d, "net")
    until(lambda: d.list.count() > 0, 20)
    d.ssid.setText(HOME_NET)
    d.pwd.setText(pwd)
    d.press("write")
    return time.time()


def wifi_logs():
    return sorted(f for f in os.listdir(diag.diag_dir()) if f.endswith("-wifi.log"))


L = Board()  # il laser «in rete»: dove la scheda finta dice di essere entrata
wf = usb("thmg", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1", telnet=L.port)
check("(scheda finta come il Mecpow: fa la sua rete, «$wifi» vale 0, niente $50…$54)",
      wf["mode"] == "AP" and wf["switch"] == 0 and 50 not in ctl.board_settings
      and any("THMG" in s for s in ctl.board_info), ctl.board_info)
d = wizard()
okb = to_state(d, "B")
check("la procedura la riconosce come scheda con il Wi-Fi e le legge l'interruttore", okb and d.family == "esp"
      and d.switch == 0 and "$wifi" in sent and "192.168.4.1" in (d.ip or ""), (d.state, d.switch, sent))
t_write = run_net(d)
oko = to_state(d, "ok")
t_ok = time.time() - t_write
cmds = [s for s in sent if s.startswith(("[ESP", "$wifi"))]
check("scrive nome, password, «rete di casa» E «$wifi=1», poi riavvia (in quest'ordine)",
      [c.split("]")[0] + "]" if c.startswith("[") else c for c in cmds if c not in ("[ESP110]", "[ESP111]", "$wifi")][:5]
      == ["[ESP100]", "[ESP101]", "[ESP110]", "$wifi=1", "[ESP444]"] and wf["switch"] == 1 and wf["boots"] == 1, cmds)
check("la scheda entra in rete e la procedura arriva in fondo: «Collegamento Wi-Fi pronto»", oko and wf["mode"] == "STA"
      and d.result == f"tcp://127.0.0.1:{L.port}", (d.state, d.result, d.body.text()[:120]))
check("…senza aspettare i 30 secondi: appena vede «TELNET Started» chiede l'indirizzo (la scheda non dice "
      "«Connected with…»)", oko and t_ok < 20.0 and "[ESP111]" in sent[sent.index("[ESP444]RESTART"):], round(t_ok, 1))
check("…usando la porta che la scheda ha detto di aver aperto", d.port.value() == L.port, d.port.value())
check("la password non compare nelle righe mostrate", not any("passwordgiusta" in s for s in sent)
      and "passwordgiusta" not in w.comm_log.text())
d.close()

wf = usb("thmg", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1", telnet=L.port, crash=True)
d = wizard()
to_state(d, "B")
run_net(d)
check("la scheda che alla prima accensione in rete va in errore e riparte da sola (successo davvero): si arriva in "
      "fondo lo stesso", to_state(d, "ok") and wf["crash"] is False and d.result == f"tcp://127.0.0.1:{L.port}", d.state)
d.close()

wf = usb("thmg", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1", telnet=L.port, switch=1, mode="STA", ip="127.0.0.1")
d = wizard()
okb = to_state(d, "B", "ok")
check("scheda già con «$wifi=1»: l'interruttore viene letto (1) e riscritto uguale, nessun problema",
      okb and d.switch == 1, (d.state, d.switch))
d.close()

n_logs = len(wifi_logs())
time.sleep(1.1)
wf = usb("thmg", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1", telnet=L.port, reject=("$wifi",))
d = wizard()
to_state(d, "B")
check("(scheda che fa come il Mecpow ma non dice di avere l'interruttore: è il caso di una scheda sconosciuta)",
      d.switch is None and "$wifi" in sent)
run_net(d)
okn = to_state(d, "not_tried", "failed", "ok")
check("accetta tutto ma al riavvio riaccende subito la sua rete senza provare: esito «La scheda non ha provato a "
      "collegarsi», non «password sbagliata»", okn and d.state == "not_tried" and "$wifi=1" not in sent
      and wf["boots"] == 1, (d.state, d.title.text() if hasattr(d, "title") else ""))
body = re.sub(r"<[^>]+>", "", d.body.text())
check("…il testo dice che non è la password né il segnale, e di mandare un rapporto",
      "password" in body and "segnale" in body and "rapporto" in body and HOME_NET in body and d.has("retry"), body[:200])
check("…e il registro della prova viene salvato", len(wifi_logs()) == n_logs + 1 and "not_tried" in dw.END_STATES)
d.close()

wf = usb("thmg", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1", telnet=L.port, delay=1.6)
d = wizard()
to_state(d, "B")
run_net(d, pwd="passwordsbagliata")
okf = to_state(d, "failed", "not_tried", "ok", t=60)
check("con l'interruttore a 1 e la password sbagliata la scheda ci prova per un po' e poi torna alla sua rete: qui "
      "l'esito è «non è entrato nella rete», con le cause solite", okf and d.state == "failed" and wf["switch"] == 1,
      d.state)
d.close()

wf = usb("thmg", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1", telnet=L.port, reject=("$wifi=",))
d = wizard()
to_state(d, "B")
run_net(d)
check("se la scheda rifiuta «$wifi=1» non viene riavviata a metà: «il Wi-Fi si imposta dal laser»",
      to_state(d, "D") and wf["boots"] == 0 and wf["switch"] == 0, (d.state, wf["boots"]))
d.close()

wf = usb("mks", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1")
d = wizard()
to_state(d, "B")
d.port.setValue(L.port)
run_net(d)
okm = to_state(d, "ok", "failed", "not_tried")
check("una scheda Makerbase (senza interruttore): «$wifi» non viene né letto né scritto, e tutto va come prima",
      okm and d.state == "ok" and not [s for s in sent if s.lower().startswith("$wifi")] and d.switch is None,
      (d.state, [s for s in sent if "wifi" in s.lower()]))
d.close()
wf = usb("mks", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1")
d = wizard()
to_state(d, "B")
run_net(d, pwd="passwordsbagliata")
check("Makerbase con la password sbagliata: dice «Connecting…», quindi ha provato: l'esito resta «non è entrato "
      "nella rete» anche se la rete propria riparte in fretta", to_state(d, "failed", "not_tried") and d.state == "failed",
      d.state)
d.close()



def hush(*words):
    """Da qui la scheda finta non scrive più le righe che contengono una di quelle parole (schede che dicono meno)."""
    real = ctl.sim._emit
    ctl.sim._emit = lambda text: None if any(x in text for x in words) else real(text)


wf = usb("mks", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1")
hush("Cannot connect")
d = wizard()
to_state(d, "B")
run_net(d, pwd="passwordsbagliata")
check("scheda che dice «Connecting…» e poi solo «rete propria ripartita» (senza «Cannot connect»): ha provato, quindi "
      "l'esito è «non è entrato nella rete» anche se è stata svelta", to_state(d, "failed", "not_tried")
      and d.state == "failed", d.state)
d.close()
wf = usb("thmg", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1", telnet=L.port, reject=("$wifi",))
hush("Local access point")
real_wait, dw.WAIT_S = dw.WAIT_S, 5.0
d = wizard()
to_state(d, "B")
run_net(d)
oks = to_state(d, "failed", "not_tried", "other_subnet", "no_port", "ok", "unknown", t=40)
dw.WAIT_S = real_wait
check("scheda che fa partire i servizi sulla sua rete propria senza dirlo: l'indirizzo 192.168.4.1 non viene preso "
      "per «è entrata in rete»; alla fine l'esito è «non è entrato nella rete»", oks and d.state == "failed"
      and "[ESP111]" in sent, d.state)
d.close()

# «Trova il laser in rete» mentre si è collegati via rete: non deve interrogare il laser a cui si è collegati
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)
ctl.connect_port(PORT)
until(lambda: ctl.connected and not cam._searching, 8)
real_ports, ws.PORTS = ws.PORTS, (B1.port,)
k0, a0 = B1.kicked, B1.accepted
d = wizard()
d._find()
okf = to_state(d, "find_none", "ok", "find_many", t=30)
ws.PORTS = real_ports
check("«Trova il laser in rete» con il laser già collegato via rete: non tocca il suo indirizzo, il collegamento "
      "resta su", okf and ctl.connected and B1.kicked == k0 and B1.accepted == a0, (d.state, B1.kicked - k0, B1.accepted - a0))
d.close()
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)

# ================================================================== 4. la frase delle porte
closed = free_port()
wf = usb("thmg", nets={HOME_NET: "passwordgiusta"}, join_ip="127.0.0.1", telnet=closed)
d = wizard()
to_state(d, "B")
run_net(d)
okp = to_state(d, "no_port", "ok", t=60)
body = re.sub(r"<[^>]+>", "", d.body.text())
check("in rete ma nessuna porta risponde: le porte provate sono elencate una volta sola",
      okp and d.state == "no_port" and f"{closed} · 8080 · 23" in body and "né sulla porta" not in body, body[:200])
d.port.setValue(8080)
d._outcome_no_port("127.0.0.1")
body = re.sub(r"<[^>]+>", "", d.body.text())
check("…anche quando la porta scelta è la 8080 (prima usciva «né sulla 8080 né sulle porte 8080 e 23»)",
      "(8080 · 23)" in body and body.count("8080") == 1, body[:200])
d.close()
ctl.disconnect_port()

# ================================================================== 5. traduzioni
keys = set()
for rel in (("ui", "dialogs_wifi.py"), ("camera.py",), ("camera_panel.py",)):
    srcf = open(os.path.join(ROOT, "freelasercut", *rel), encoding="utf-8").read()
    for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', srcf):
        try:
            k = "".join(ast.literal_eval(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
        except (SyntaxError, ValueError):
            continue
        if any(t in k for t in ("non ha provato a collegarsi", "ha accettato nome e password", "porte provate",
                                "comandi del laser", "{0}, porta {1}: {2}.", "Telecamera di rete chiusa",
                                "Non apro questa telecamera")):
            keys.add(k)
check("testi nuovi trovati nel codice (7)", len(keys) == 7, sorted(k[:40] for k in keys))
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
