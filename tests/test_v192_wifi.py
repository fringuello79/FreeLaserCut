# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.2: il Wi-Fi delle schede Longer (firmware LGT) dopo la prova sul B1 vero del 13/11/2026.

Che cosa era successo: la procedura scriveva nome e password ($53, $54), mandava «[ESP110]STA» (la scheda rispondeva
ok) e riavviava; la scheda ripartiva con «[MSG:WiFi Off]» e dopo 30 secondi la finestra diceva «Non so se si è
collegata». Il laser entrava in rete solo scrivendo a mano «$50=2» in Console.

Il dato (fonte: solo le risposte di quella scheda, nessun documento del produttore): «$50» è l'interruttore del Wi-Fi
(0 = spento, 2 = rete di casa); «$50=2» fa partire subito il collegamento («Wifi Connecting...» → «Wifi Connected», senza
indirizzo, oppure dopo 40 secondi «Wifi Connection failed») e risponde ok solo alla fine; al riavvio con «$50=2» la
scheda riprova da sola e, se fallisce, scrive «WiFi Off» e rimette «$50=0».

Matrice: messaggi (P), scheda finta come quella vera (S), procedura (D): interruttore 0/2 × password giusta/sbagliata ×
la scheda parla / è muta / rifiuta «$50=2» × Longer / altre schede.
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
GOOD, BAD = "passwordgiusta", "passwordsbagliata"
INFO = b"[LGT V1.2.3]\r\n[VER:1.1.2023080801:]\r\n[OPT:VPH,63,256]\r\n[MSG:FW:LGT V1.2.3|MB:LS_ESP32-SIM]\r\n"


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
    """La porta dei comandi del laser «in rete»: risponde come GRBL a chi la prova dopo che la scheda è entrata."""

    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self.start()

    def run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(c,), daemon=True).start()

    def serve(self, c):
        buf = b""
        try:
            while True:
                data = c.recv(1024)
                if not data:
                    return
                buf += data.replace(b"?", b"")
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if line.upper() == b"$I":
                        c.sendall(INFO + b"ok\r\n")
                    else:
                        c.sendall(b"ok\r\n")
        except OSError:
            pass


# ================================================================== P. i messaggi delle Longer
check("P1 «Wifi Connecting...» = sta provando a collegarsi",
      ws.parse_message("[MSG:Wifi Connecting...]") == ("connecting", "")
      and ws.parse_message("[MSG:WiFi connecting]") == ("connecting", ""))
check("P2 «Wifi Connected» = collegata, senza indirizzo (va chiesto)",
      ws.parse_message("[MSG:Wifi Connected]") == ("connected", "") and ws.parse_message("Wifi Connected") == ("connected", ""))
check("P3 «Wifi Connection failed» = non riuscita, e dopo quello la scheda lascia il Wi-Fi spento",
      ws.parse_message("[MSG:Wifi Connection failed]") == ("failed", "") and ws.fails_to_off("[MSG:Wifi Connection failed]")
      and not ws.fails_to_off("[MSG:Cannot connect to CasaMia]") and not ws.fails_to_off("[MSG:Wifi Connected]")
      and not ws.fails_to_off(""))
check("P4 «WiFi Off» e «No Wifi» = Wi-Fi spento",
      ws.parse_message("[MSG:WiFi Off]") == ("nowifi", "") and ws.parse_message("[MSG:No Wifi]") == ("nowifi", ""))
check("P5 i messaggi delle altre schede si leggono come prima",
      ws.parse_message("[MSG:Connecting CasaMia]") == ("connecting", "CasaMia")
      and ws.parse_message("[MSG:Connected with 192.168.1.77]") == ("connected", "192.168.1.77")
      and ws.parse_message("[MSG:Cannot connect to CasaMia]") == ("failed", "CasaMia")
      and ws.parse_message("[MSG:Local access point MKS_DLC started, 192.168.4.1]") == ("own", "192.168.4.1")
      and ws.parse_message("[MSG:TELNET Started 8080]") == ("services", "8080")
      and ws.parse_message("[MSG:Mode=STA:SSID=x:Status=Not connected:IP=0.0.0.0:MAC=00]") is None
      and ws.parse_message("[MSG:HTTP Started]") is None)
check("P6 l'interruttore «$50=2» è un comando solo delle Longer; alle altre schede non si manda niente",
      ws.commands("esp", "radio", True) == ("$50=2",) and ws.commands("esp", "radio") == ()
      and ws.commands("named", "radio", True) == () and ws.commands("numeric", "radio", True) == ()
      and ws.commands("esp", "sta", True) == ("[ESP110]STA",))
check("P7 l'attesa per le Longer copre i 40 secondi del tentativo (50 secondi); le altre restano a 30",
      dw.WAIT_S == 30.0 and 45.0 <= dw.WAIT_S * ws.LGT_WAIT_K <= 60.0)
check("P8 «$50=2» non è una password (non va mascherato); «$54=…» sì",
      ws.mask_line("$50=2") == "$50=2" and ws.mask_line("$54=" + GOOD) == "$54=" + ws.MASK)

camera_panel.list_cameras = lambda max_index=6, skip=(): []
camera.usb_camera_names = lambda: {}
camera.USB_NET_HOST = "127.0.0.250"
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ctl, cam = w.ctl, w.camera
type(ctl).WAKE_AFTER_S = 3600
until(lambda: not cam._searching, 8)
sent, got = [], []
ctl.line_sent.connect(sent.append)
ctl.line_received.connect(got.append)


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
    got.clear()
    return wf


def wizard():
    d = dw.WifiWizard(w, system=Pc().sys)
    d.start()
    return d


def to_state(d, *states, t=40.0):
    until(lambda: d.state in states, t)
    return d.state in states


def run_net(d, pwd=GOOD, port=None):
    if d.state == "B":
        d.press("net")
    to_state(d, "net")
    until(lambda: d.list.count() > 0, 20)
    if port:  # schede che non dicono su che porta ascoltano: la si mette a mano, come in «Avanzate»
        d.port.setValue(port)
    d.ssid.setText(HOME_NET)
    d.pwd.setText(pwd)
    d.press("write")
    return time.time()


def wait_idle():
    return until(lambda: ctl.last_status.get("state") == "Idle", 10)


def ask(line, t=8.0):
    """Manda una riga alla scheda finta e aspetta la risposta (ok o error)."""
    n = len(got)
    ctl.send_line(line)
    until(lambda: any(s.strip() == "ok" or s.startswith("error") for s in got[n:]), t)
    return [s.strip() for s in got[n:]]


END = ("ok", "failed", "not_tried", "unknown", "no_port", "other_subnet", "mute", "D", "serial_lost")
L = Board()
REAL = dict(switch50=True, nets={HOME_NET: GOOD}, join_ip="127.0.0.1", telnet=L.port)

# ================================================================== S. la scheda finta si comporta come il B1 vero
wf = usb("lgt", **REAL)
check("S0 (scheda finta Longer: Wi-Fi spento, «$50=0», «No Wifi» nella risposta a $I)",
      str(ctl.board_settings.get(50)) == "0" and any("LGT" in s for s in ctl.board_info)
      and any("No Wifi" in s for s in ctl.board_info), (ctl.board_settings.get(50), ctl.board_info))
r1 = ask("[ESP110]")
ask("$53=" + HOME_NET)
ask("$54=" + GOOD)
r2 = ask("[ESP110]STA")
ask("[ESP444]RESTART")
off = until(lambda: any("WiFi Off" in s for s in got), 5)
r3 = ask("[ESP111]")
check("S1 «[ESP110]» dice NONE; «[ESP110]STA» risponde ok ma al riavvio la scheda dice «WiFi Off», resta a 0.0.0.0 e "
      "«$50» resta 0 (proprio il difetto visto sul vero)",
      "$ESP110=NONE" in r1 and r2[-1] == "ok" and off and "0.0.0.0" in r3 and wf["s50"] == "0"
      and not any("Connecting" in s for s in got), (r1, r2, r3, wf["s50"]))
got.clear()
r4 = ask("$50=2")
until(lambda: any("TELNET" in s for s in got), 3)
i_c, i_j, i_ok = (next((i for i, s in enumerate(got) if k in s), -1) for k in ("Wifi Connecting", "Wifi Connected", "ok"))
check("S2 «$50=2» fa partire subito il collegamento, senza riavvio: «Wifi Connecting...», «Wifi Connected», e l'ok solo "
      "dopo; poi i servizi; «[ESP111]» dà l'indirizzo",
      0 <= i_c < i_j < i_ok and wf["boots"] == 1 and any(f"TELNET Started {L.port}" in s for s in got)
      and "127.0.0.1" in ask("[ESP111]") and wf["s50"] == "2", (got, wf["boots"]))
ask("[ESP444]RESTART")
back = until(lambda: wf["ip"] == "127.0.0.1" and sum("Wifi Connected" in s for s in got) >= 2, 5)
check("S4 riaccesa con «$50=2» e la rete giusta torna in rete da sola", back and wf["s50"] == "2", (got[-6:], wf["s50"]))
wf = usb("lgt", **REAL)
ask("$53=" + HOME_NET)
ask("$54=" + BAD)
t0 = time.time()
r5 = ask("$50=2")
t_fail = time.time() - t0
keep = wf["s50"]
ask("[ESP444]RESTART")
off2 = until(lambda: any("WiFi Off" in s for s in got) and sum("Wifi Connection failed" in s for s in got) >= 2, 8)
check("S3 password sbagliata: «Wifi Connection failed» dopo l'attesa, «$50» resta 2; al riavvio riprova, fallisce, "
      "scrive «WiFi Off» e rimette «$50=0»",
      any("Wifi Connection failed" in s for s in r5) and r5[-1] == "ok" and t_fail >= 1.0 and keep == "2" and off2
      and wf["s50"] == "0" and str(ctl.sim.settings.get(50)) == "0" and wf["ip"] == "0.0.0.0",
      (r5, round(t_fail, 1), keep, wf["s50"]))


# ================================================================== D. la procedura
def radio_count(wf_):
    return sum(1 for s in wf_["log"] if s.replace(" ", "") == "$50=2")


def after_restart():
    """I comandi mandati dopo il riavvio, in ordine (senza le domande di stato)."""
    i = len(sent) - 1 - sent[::-1].index("[ESP444]RESTART") if "[ESP444]RESTART" in sent else -1
    return [s for s in sent[i + 1:] if s.startswith(("[ESP", "$5"))]


def procedure(wf_, pwd=GOOD, states=END, t=40.0, port=None):
    d_ = wizard()
    okb_ = to_state(d_, "B", "D", "C")
    t_ = run_net(d_, pwd, port) if d_.state == "B" else time.time()
    to_state(d_, *states, t=t)
    return d_, okb_, time.time() - t_


real_wait, dw.WAIT_S = dw.WAIT_S, 6.0  # attese accorciate: 6 secondi, per le Longer 10 (6 × 5/3)
wf = usb("lgt", **REAL)
d, okb, secs = procedure(wf)
log = [s for s in wf["log"] if s not in ("?", "$I", "$$", "$G", "$#", "[ESP110]", "[ESP111]") and not s.startswith("$J")]
check("D1 Longer con il Wi-Fi spento, password giusta: la procedura la riconosce (Longer, Wi-Fi spento)",
      okb and d.lgt and d.family == "esp" and d.mode == "OFF", (d.state, d.lgt, d.mode))
check("D1 …scrive nome, password, «[ESP110]STA», riavvia e, quando la scheda dice «WiFi Off», manda «$50=2» "
      "(una volta sola, dopo il riavvio)",
      log[:5] == ["$53=" + HOME_NET, "$54=" + GOOD, "[ESP110]STA", "[ESP444]RESTART", "$50=2"] and radio_count(wf) == 1
      and wf["boots"] == 1, log)
check("D1 …e arriva in fondo: «Collegamento Wi-Fi pronto» con l'indirizzo chiesto alla scheda",
      d.state == "ok" and d.result == f"tcp://127.0.0.1:{L.port}" and wf["s50"] == "2" and "[ESP111]" in sent[sent.index("$50=2"):],
      (d.state, d.result, d.body.text()[:120]))
check("D1 …subito, senza aspettare lo scadere dell'attesa: dopo il riavvio il primo comando è «$50=2», non la "
      "domanda dell'indirizzo che si fa allo scadere", after_restart()[:2] == ["$50=2", "[ESP111]"], after_restart())
check("D9 il passo resta nel registro («Wi-Fi guidato: radio») e la password non compare né nel registro né in console",
      "Wi-Fi guidato: radio" in w.comm_log.text() and GOOD not in w.comm_log.text()
      and not any(GOOD in s for s in sent) and any(s == "$54=" + ws.MASK for s in sent), [s for s in sent if "$5" in s])
d.close()

wf = usb("lgt", **REAL)
d, okb, secs = procedure(wf, BAD)
body = d.body.text()
check("D2 password sbagliata: l'esito è «Il laser non è entrato nella rete» (non «Non so se si è collegata»)",
      d.state == "failed" and radio_count(wf) == 1, (d.state, body[:100]))
check("D2 …con il testo delle Longer: Wi-Fi lasciato spento, niente «rete propria», e le cause in elenco",
      "Wi-Fi spento" in body and "rete propria" not in body and "192.168.4.1" not in body and "password" in body, body)
check("D2 …e arriva appena la scheda lo dice, non allo scadere (dopo «$50=2» nessuna domanda dell'indirizzo)",
      after_restart() == ["$50=2"], after_restart())
d.press("retry")
to_state(d, "net")
boots0 = wf["boots"]
d.ssid.setText(HOME_NET)
d.pwd.setText(GOOD)
d.press("write")
to_state(d, *END)
check("D3 «Correggi e riprova» con la password giusta: la scheda (che ha ancora «$50=2») riprova al riavvio ed entra; "
      "«$50=2» non serve una seconda volta",
      d.state == "ok" and d.result == f"tcp://127.0.0.1:{L.port}" and wf["boots"] == boots0 + 1 and radio_count(wf) == 1,
      (d.state, wf["boots"] - boots0, radio_count(wf)))
d.close()

wf = usb("lgt", s50="2", ssid="ReteVecchia", password="vecchiapassword", **REAL)
d, okb, secs = procedure(wf)
check("D4 scheda che ha già «$50=2» (cambio di rete): al riavvio prova da sola, la procedura riesce senza mandare «$50=2»",
      okb and d.state == "ok" and radio_count(wf) == 0 and wf["ssid"] == HOME_NET and wf["boots"] == 1,
      (d.state, radio_count(wf), wf["boots"]))
d.close()

wf = usb("lgt", s50="2", ssid="ReteVecchia", password="vecchiapassword", **REAL)
real_emit = ctl.sim._emit
ctl.sim._emit = lambda text: None if "TELNET Started" in text or "HTTP Started" in text else real_emit(text)
dw.WAIT_S = 30.0  # attesa di serie: se la procedura aspettasse lo scadere, qui non finirebbe in tempo
d, okb, secs = procedure(wf, t=20.0, port=L.port)
dw.WAIT_S = 6.0
check("D4 …anche se la scheda dice solo «Wifi Connected» (senza le righe dei servizi): l'indirizzo viene chiesto subito, "
      "senza aspettare i 50 secondi", d.state == "ok" and after_restart()[:1] == ["[ESP111]"] and radio_count(wf) == 0,
      (d.state, after_restart(), round(secs, 1)))
d.close()

wf = usb("lgt", reject=("$50=",), **REAL)
d, okb, secs = procedure(wf)
check("D5 la scheda rifiuta «$50=2»: la procedura non resta appesa e non insiste; dice «Non so se si è collegata»",
      d.state == "unknown" and radio_count(wf) == 1 and after_restart() == ["$50=2"], (d.state, radio_count(wf), after_restart()))
check("D8 …e la frase dice i secondi veri dell'attesa delle Longer (qui 10, cioè 6 × 5/3; di serie 50)",
      "10 secondi" in d.body.text() and "30 secondi" not in d.body.text() and abs(d.wait_s() - 10.0) < 0.01, d.body.text())
d.close()

wf = usb("lgt", fail_s=8.8, **REAL)
d, okb, secs = procedure(wf, BAD)
check("D8 il tentativo fallito dura più dell'attesa delle altre schede (qui 8,8 secondi contro 6; sul vero 40 contro "
      "30): per le Longer la procedura aspetta abbastanza (10; sul vero 50), contando da quando manda «$50=2», da "
      "sentire «Wifi Connection failed»",
      d.state == "failed" and after_restart() == ["$50=2"] and "Wi-Fi spento" in d.body.text(),
      (d.state, after_restart(), round(secs, 1)))
d.close()

dw.WAIT_S = 3.0  # per le schede mute si aspetta sempre lo scadere: qui 3 secondi (5 per le Longer)
wf = usb("lgt", messages=False, **REAL)
d = wizard()
to_state(d, "B")
run_net(d, GOOD, L.port)
until(lambda: radio_count(wf) >= 1, 30)
dw.WAIT_S = 30.0  # da qui l'attesa di serie: l'esito deve arrivare con l'ok di «$50=2», non allo scadere
to_state(d, *END, t=15.0)
dw.WAIT_S = 3.0
check("D6 scheda muta (non scrive nessun messaggio): allo scadere, con l'indirizzo a 0.0.0.0, la procedura prova "
      "«$50=2» prima di arrendersi; quando la scheda risponde ok le chiede l'indirizzo, e riesce",
      d.state == "ok" and radio_count(wf) == 1 and after_restart()[:2] == ["[ESP111]", "$50=2"] and d.result == f"tcp://127.0.0.1:{L.port}",
      (d.state, radio_count(wf), round(secs, 1)))
d.close()

wf = usb("lgt", messages=False, **dict(REAL, nets={HOME_NET: "unaltrapassword"}))
d, okb, secs = procedure(wf, t=60.0)
check("D6 …scheda muta che non entra: un tentativo solo con «$50=2», poi «Non so se si è collegata»",
      d.state == "unknown" and radio_count(wf) == 1, (d.state, radio_count(wf), round(secs, 1)))
d.close()
wf = usb("mks", nets={HOME_NET: GOOD}, join_ip="127.0.0.1", messages=False, ip="0.0.0.0")
wf["join_ip"] = "0.0.0.0"  # muta e senza indirizzo: per le altre schede niente «$50=2», si dice «Non so»
d, okb, secs = procedure(wf, t=30.0)
check("D7 scheda non Longer muta e senza indirizzo: «Non so se si è collegata» dopo l'attesa di sempre (frase con il "
      "numero giusto), senza «$50=2»",
      d.state == "unknown" and radio_count(wf) == 0 and "3 secondi" in d.body.text(), (d.state, d.body.text()))
d.close()
dw.WAIT_S = 6.0

for kind, extra in (("mks", {}), ("thmg", dict(telnet=L.port)), ("lgt", {})):
    wf = usb(kind, nets={HOME_NET: GOOD}, join_ip="127.0.0.1", **extra)
    d, okb, secs = procedure(wf, t=30.0, port=L.port)
    exp = 10.0 if kind == "lgt" else 6.0
    check(f"D7 scheda «{kind}»{' (la Longer finta di prima)' if kind == 'lgt' else ''}: riesce come prima e «$50=2» non "
          f"viene mai mandato; attesa {int(exp)} secondi",
          d.state == "ok" and radio_count(wf) == 0 and abs(d.wait_s() - exp) < 0.01, (d.state, radio_count(wf), d.wait_s()))
    d.close()
wf = usb("mks", nets={HOME_NET: GOOD}, join_ip="127.0.0.1")
d, okb, secs = procedure(wf, BAD, t=30.0)
check("D7 scheda non Longer, password sbagliata: il testo resta quello della «rete propria»",
      d.state == "failed" and "rete propria" in d.body.text() and "Wi-Fi spento" not in d.body.text(), d.body.text()[:160])
d.close()

wf = usb("lgt", **REAL)
d = wizard()
to_state(d, "B")
run_net(d)
until(lambda: radio_count(wf) >= 1, 10)
for _ in range(3):  # la scheda ripete «WiFi Off» (per esempio in risposta a un altro $I): non deve ripartire niente
    d._on_board_line("[MSG:WiFi Off]")
    d._on_board_line("[MSG:No Wifi]")
to_state(d, *END)
until(lambda: False, 2.0)
check("D1 «WiFi Off» ripetuto durante l'attesa: «$50=2» parte comunque una volta sola",
      d.state == "ok" and radio_count(wf) == 1, (d.state, radio_count(wf)))
d._on_board_line("[MSG:WiFi Off]")
until(lambda: False, 2.0)
check("D1 …e a procedura finita un «WiFi Off» non fa mandare niente", radio_count(wf) == 1, radio_count(wf))
d.close()
dw.WAIT_S = real_wait

# ================================================================== traduzioni
keys = set()
srcf = open(os.path.join(ROOT, "freelasercut", "ui", "dialogs_wifi.py"), encoding="utf-8").read()
for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', srcf):
    try:
        k = "".join(ast.literal_eval(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
    except (SyntaxError, ValueError):
        continue
    if "ha lasciato il Wi-Fi spento" in k or "non ha detto niente in" in k:
        keys.add(k)
check("testi nuovi trovati nel codice (2), quello dei secondi con il numero come segnaposto",
      len(keys) == 2 and any("{0} secondi" in k for k in keys), sorted(k[:50] for k in keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k[:40] for k in keys if not loc.get(k)]
    bad = [k[:40] for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    old = [k for k in loc if "in 30 secondi. Provo" in k]
    check(f"traduzioni {lang}: i due testi, con gli stessi segnaposto; tolto quello vecchio con «30» fisso",
          not miss and not bad and not old, (miss, bad, old))

check("nessun errore nascosto nei comandi dell'interfaccia", not hidden, [repr(e)[:120] for e in hidden[:3]])
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
