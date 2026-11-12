# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.17: Impostazioni → Collegamento Wi-Fi del laser (procedura guidata). Specifica: freeburn/configuratore-wifi.

Il dato: (collegamento del momento, stato della macchina, tipo di scheda e stato del suo Wi-Fi, rete del PC) →
un caso (A già in Wi-Fi, B cavo e scheda con il Wi-Fi, C senza Wi-Fi, D comandi rifiutati, E scollegato) →
rete e password controllate → comandi della famiglia → riavvio → esito (ok, altra sottorete, nessuna porta, non
entrata, nessun messaggio, porta USB non tornata).

Una prova per ogni riga della matrice dei casi della specifica:
0 la logica senza Qt (password mascherata, famiglie, messaggi, controlli, rete del PC con netsh/nmcli finti, guardia
  del cambio di rete, sottorete, ricerca in rete con laser finti);
1 privacy: la password di prova non compare in console, registro, comando a distanza, copie, rapporto, preferenze;
2 pagina 0: ogni riga; 3 famiglie di schede; 4 pagina «rete»; 5 scrittura e riavvio; 6 esiti; 7 con e senza cavo;
8 uso quotidiano (indirizzo cambiato); 9 menu, finestra Wi-Fi di sempre, configurazione guidata, traduzioni.

Le schede sono finte (simulatore), come le reti del PC e i laser in rete (tutto su 127.0.0.x). Non provato qui:
un laser vero, netsh su un Windows vero, nmcli su un Linux con il Wi-Fi.
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
TMP = tempfile.mkdtemp(prefix="flc_wifi_")
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
INI = os.path.join(TMP, "prova.ini")
os.environ["FLC_SETTINGS_INI"] = INI
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
from freelasercut import admin, board_backup, netport  # noqa: E402
from freelasercut import wifi_setup as ws  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.sim import SimSerial  # noqa: E402
from freelasercut.ui import dialogs_wifi as dw  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []
SECRET = "Segretissima#42"  # la password di prova: alla fine non deve comparire da nessuna parte
HOME_NET = "CasaMia"


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


# tempi corti: le attese vere sono di 30, 20 e 10 secondi
dw.WAIT_S, dw.REOPEN_S, dw.USB_WAIT_S, dw.FIND_S, dw.REPLY_S = 6.0, 5.0, 2.0, 6.0, 4.0

# ================================================================== 0. la logica, senza Qt
M = ws.MASK
check("password mascherata nei comandi: [ESP101], $Sta/Password=, $54=, $52=, anche con spazi e maiuscole diverse",
      ws.mask_line(f"[ESP101]{SECRET}") == "[ESP101]" + M and ws.mask_line(f"[esp101]{SECRET}") == "[esp101]" + M
      and ws.mask_line(f"$Sta/Password={SECRET}") == "$Sta/Password=" + M and ws.mask_line(f"$54={SECRET}") == "$54=" + M
      and ws.mask_line("$52=12345678") == "$52=" + M and ws.mask_line(f"  $AP/Password = {SECRET}").endswith(M)
      and SECRET not in ws.mask_line(f"$ESP101={SECRET}"))
check("…e non in quello che non è una password: nome della rete, numeri di GRBL, comandi normali",
      ws.mask_line("[ESP100]CasaMia") == "[ESP100]CasaMia" and ws.mask_line("$53=CasaMia") == "$53=CasaMia"
      and ws.mask_line("$54=1000.000") == "$54=1000.000" and ws.mask_line("$130=450.000") == "$130=450.000"
      and ws.mask_line("G1 X10") == "G1 X10" and not ws.has_secret("$$") and ws.has_secret(f"[ESP101]{SECRET}"))
ms = ws.mask_settings({50: "2", 51: "MKS_DLC", 52: "12345678", 53: HOME_NET, 54: SECRET, 130: "450.000"})
check("nelle impostazioni lette ($$): mascherate $52 e $54, il resto com'è",
      ms == {50: "2", 51: "MKS_DLC", 52: M, 53: HOME_NET, 54: M, 130: "450.000"}, ms)
check("le impostazioni del Wi-Fi si riconoscono solo dove ci sono davvero (nomi di rete), non su una scheda normale",
      ws.wifi_numbers({50: "0", 51: "MKS_DLC", 52: "12345678", 53: "", 54: ""}) == {50, 51, 52, 53, 54}
      and ws.wifi_numbers({50: "1.000", 51: "3.000", 130: "400.000"}) == set() and ws.wifi_numbers({}) == set())
check("famiglie: Makerbase con i comandi fra quadre, Longer con la rete in $53/$54 (e mai $50), FluidNC con i nomi",
      ws.commands("esp", "ssid")[0] == "[ESP100]{0}" and ws.commands("esp", "ssid", lgt=True)[0] == "$53={0}"
      and ws.commands("esp", "password", lgt=True)[0] == "$54={0}" and ws.commands("esp", "sta", lgt=True) == ("[ESP110]STA",)
      and ws.commands("esp", "ssid", lgt=True)[1:] == ("[ESP100]{0}", "$Sta/SSID={0}")
      and not any("$50" in c for what in ("ssid", "password", "sta", "off", "restart") for c in ws.commands("esp", what, lgt=True))
      and ws.commands("named", "ssid") == ("$Sta/SSID={0}",) and "$Bye" in ws.commands("named", "restart")
      and ws.commands("numeric", "sta")[-1] == "$50=1" and ws.commands("boh", "ssid") == ())
check("porta suggerita: 8080 per Makerbase e Longer, 23 per FluidNC e Grbl_ESP32",
      ws.default_port("esp") == 8080 and ws.default_port("named") == 23 and ws.default_port("esp", "[VER:3.7 FluidNC]") == 23)
check("riconoscimento: Longer, schede tipo Makerbase, indizi di ESP32; «No Wifi» non vuol dire «senza Wi-Fi»",
      ws.is_lgt(["[MSG:FW:LGT V1.2.3|MB:LS_ESP32]"]) and not ws.is_lgt(["[VER:1.1h]"]) and ws.is_mks_like(["[MSG:Using machine:MKS DLC32]"])
      and ws.esp32_hints(["[MSG:FW:LGT V1.2.3|MB:LS_ESP32]", "[MSG:No Wifi]"]) and not ws.esp32_hints(["[VER:1.1h.20190830:]", "[OPT:V,15,128]"])
      and ws.esp32_hints([], {51: "MKS_DLC", 53: ""}))
check("stato della scheda da modalità e indirizzo (le risposte lette sul B1 vero: «$ESP110=STA», «0.0.0.0»)",
      ws.parse_mode(["$ESP110=STA"]) == "STA" and ws.parse_mode(["$Radio/Mode=None"]) == "OFF" and ws.parse_mode(["AP"]) == "AP"
      and ws.parse_mode(["boh"]) is None and ws.find_ip("0.0.0.0") == "0.0.0.0" and ws.find_ip("ip 999.1.1.1 x") is None
      and ws.board_state("STA", "0.0.0.0") == "idle" and ws.board_state("OFF", None) == "off"
      and ws.board_state("STA", "192.168.4.1") == "own" and ws.board_state("AP", None) == "own"
      and ws.board_state("STA", "192.168.1.110") == "net")
check("messaggi della scheda: in collegamento, collegata con l'indirizzo, non entrata, rete propria, Wi-Fi spento",
      ws.parse_message("[MSG:Connecting CasaMia]") == ("connecting", "CasaMia")
      and ws.parse_message("[MSG:Connected with 192.168.1.77]") == ("connected", "192.168.1.77")
      and ws.parse_message("[MSG:Cannot connect to CasaMia]") == ("failed", "CasaMia")
      and ws.parse_message("[MSG:Local access point MKS_DLC started, 192.168.4.1]") == ("own", "192.168.4.1")
      and ws.parse_message("[MSG: Mode=STA:SSID=x:Status=Connected:IP=10.0.0.5:MAC=0]") == ("connected", "10.0.0.5")
      and ws.parse_message("[MSG:No Wifi]") == ("nowifi", "") and ws.parse_message("[MSG:Caution: Unlocked]") is None)
check("…«non collegata» mentre ci sta ancora provando (FluidNC) non è un fallimento",
      ws.parse_message("[MSG: Mode=STA:SSID=x:Status=Not connected:IP=0.0.0.0:MAC=0]") is None)


def codes(ssid, pwd, net=None, pc=None, fam="esp", nets=()):
    return {c.code: c.block for c in ws.check_network(ssid, pwd, net, pc, fam, nets)}


N = ws.Network
check("nome della rete: 0 caratteri blocca, 1 e 32 vanno, 33 blocca",
      codes("", "12345678").get("ssid_empty") is True and "ssid_empty" not in codes("a", "12345678")
      and "ssid_long" not in codes("a" * 32, "12345678") and codes("a" * 33, "12345678").get("ssid_long") is True)
check("password: 7 caratteri blocca, 8 e 63 vanno, 64 blocca; vuota blocca (salvo rete aperta)",
      codes("Casa", "1234567").get("pwd_short") is True and "pwd_short" not in codes("Casa", "12345678")
      and "pwd_long" not in codes("Casa", "p" * 63) and codes("Casa", "p" * 64).get("pwd_long") is True
      and codes("Casa", "").get("pwd_short") is True and "pwd_short" not in codes("Bar", "", N("Bar", 80, "2.4", "open")))
check("rete aziendale (nome utente e password): blocca; rete aperta: avvisa; solo WPA3: avvisa",
      codes("Uff", "12345678", N("Uff", 80, "2.4", "enterprise")).get("enterprise") is True
      and codes("Bar", "", N("Bar", 80, "2.4", "open")).get("open") is False
      and codes("Casa", "12345678", N("Casa", 80, "2.4", "wpa3")).get("wpa3") is False)
n5, n24 = N("Casa", 70, "5", "wpa2"), N("Casa", 60, "2.4", "wpa2")
check("rete a 5 GHz: avvisa, ma non se la stessa rete c'è anche a 2,4 GHz",
      codes("Casa", "12345678", n5, nets=[n5]).get("band5") is False and "band5" not in codes("Casa", "12345678", n5, nets=[n5, n24])
      and "band5" not in codes("Casa", "12345678", n24, nets=[n5, n24]))
check("rete per gli ospiti riconosciuta nelle cinque lingue (avviso)",
      all(codes(s, "12345678").get("guest") is False for s in ("Casa-Guest", "Rete Ospiti", "FRITZ!Box Gastzugang",
                                                               "WiFi_Invitados", "Livebox-invités", "NOS-Convidados"))
      and "guest" not in codes("CasaMia", "12345678"))
check("rete diversa da quella del PC: avvisa; stessa rete o PC col cavo: no",
      codes("Altra", "12345678", pc="CasaMia").get("other_net") is False and "other_net" not in codes("CasaMia", "12345678", pc="CasaMia")
      and "other_net" not in codes("Altra", "12345678", pc=None))
check("spazi e caratteri particolari: avviso; con la famiglia a numeri «;» e «(» bloccano",
      codes("Casa Mia", "pass(word)1").get("special") is False and codes("Casà", "12345678").get("special") is False
      and "special" not in codes("CasaMia-2", "Abc_12345.x") and codes("Casa", "pass;word1", fam="numeric").get("semicolon") is True
      and codes("Ca(sa", "12345678", fam="numeric").get("semicolon") is True and "semicolon" not in codes("Casa", "pass;word1"))
check("segnale debole: avviso", codes("Casa", "12345678", N("Casa", 20, "2.4", "wpa2")).get("weak") is False)
check("cause probabili quando non entra, in ordine: 5 GHz prima, poi la password; rete scritta a mano non vista",
      ws.likely_causes("Casa", "12345678", n5, [n5])[:2] == ["band5", "wrong_password"]
      and ws.likely_causes("Casa", "12345678", n24, [n24])[0] == "wrong_password"
      and ws.likely_causes("Nascosta", "12345678")[-1] == "not_seen")

NETSH_EN = """
Interface name : Wi-Fi
There are 3 networks currently visible.

SSID 1 : CasaMia
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : aa:bb:cc:dd:ee:01
         Signal             : 82%
         Radio type         : 802.11n
         Channel            : 6
         Basic rates (Mbps) : 1 2 5.5 11
    BSSID 2                 : aa:bb:cc:dd:ee:02
         Signal             : 61%
         Radio type         : 802.11ac
         Channel            : 44

SSID 2 : MKS_DLC
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : 11:22:33:44:55:66
         Signal             : 95%
         Radio type         : 802.11n
         Channel            : 1

SSID 3 : Ufficio
    Network type            : Infrastructure
    Authentication          : WPA2-Enterprise
    Encryption              : CCMP
    BSSID 1                 : 11:22:33:44:55:77
         Signal             : 30%
         Radio type         : 802.11ac
         Channel            : 100
"""
NETSH_IT = """
Nome interfaccia : Wi-Fi
Attualmente sono visibili 2 reti.

SSID 1 : Rete di Casa
    Tipo di rete            : Infrastruttura
    Autenticazione          : WPA3-Personal
    Crittografia            : CCMP
    BSSID 1                 : aa:bb:cc:dd:ee:01
         Segnale            : 74%
         Tipo frequenza radio : 802.11ax
         Banda              : 5 GHz
         Canale             : 36
         Stazioni connesse  : 3

SSID 2 : Bar
    Tipo di rete            : Infrastruttura
    Autenticazione          : Aperta
    Crittografia            : Nessuna
    BSSID 1                 : aa:bb:cc:dd:ee:09
         Segnale            : 40%
         Tipo frequenza radio : 802.11n
         Banda              : 2,4 GHz
         Canale             : 11
"""
nets = ws.parse_netsh_networks(NETSH_EN)
by = {(n.ssid, n.band): n for n in nets}
check("reti viste da Windows (netsh, inglese): nome, segnale, banda dal canale, la stessa rete su 2,4 e 5 GHz in due righe",
      set(by) == {("CasaMia", "2.4"), ("MKS_DLC", "2.4"), ("Ufficio", "5")} or set(by) == {("CasaMia", "2.4"), ("CasaMia", "5"), ("MKS_DLC", "2.4"), ("Ufficio", "5")},
      sorted(by))
check("…con il tipo di protezione (rete aziendale riconosciuta) e il segnale migliore",
      by[("Ufficio", "5")].security == "enterprise" and by[("CasaMia", "2.4")].security == "wpa2" and by[("CasaMia", "2.4")].signal == 82, nets)
nets_it = {n.ssid: n for n in ws.parse_netsh_networks(NETSH_IT)}
check("reti viste da Windows in italiano (Windows 11 con la riga «Banda»): stessa lettura, senza dipendere dalla lingua",
      nets_it["Rete di Casa"].band == "5" and nets_it["Rete di Casa"].security == "wpa3" and nets_it["Rete di Casa"].signal == 74
      and nets_it["Bar"].band == "2.4" and nets_it["Bar"].security == "open", nets_it)
check("rete a cui è collegato il PC (netsh): il nome dopo «SSID», non quello dopo «BSSID»; PC col cavo: nessuna",
      ws.parse_netsh_interface("    Nome   : Wi-Fi\n    SSID   : Rete di Casa\n    BSSID  : aa:bb\n    Stato : connessa") == "Rete di Casa"
      and ws.parse_netsh_interface("Nessuna interfaccia wireless nel sistema.") is None)
nm = ws.parse_nmcli("yes:CasaMia:80:2437 MHz:WPA2\nno:CasaMia:70:5180 MHz:WPA2\nno:MKS_DLC:90:2412 MHz:WPA2\nno:Con\\:due punti:40:2462 MHz:WPA1 WPA2\nno::30:2412 MHz:--")
check("reti viste da Linux (nmcli): rete attuale, bande, nomi con i due punti, reti senza nome scartate",
      [(n.ssid, n.band, n.current) for n in nm] == [("CasaMia", "2.4", True), ("MKS_DLC", "2.4", False), ("CasaMia", "5", False),
                                                     ("Con:due punti", "2.4", False)], nm)
check("reti proprie dei laser riconosciute dal nome", ws.is_own_net("MKS_DLC") and ws.is_own_net("mks_dlc32") and ws.is_own_net("FluidNC")
      and not ws.is_own_net("CasaMia") and not ws.is_own_net(""))


class Pc:
    """Il Wi-Fi del PC, finto: risponde come nmcli (o netsh) e tiene conto di tutti i comandi ricevuti."""

    def __init__(self, cur=HOME_NET, nets=None, wifi=True, join_ok=True, platform="linux"):
        self.cur, self.wifi, self.join_ok, self.calls, self.files = cur, wifi, join_ok, [], []
        self.nets = nets if nets is not None else [(HOME_NET, 80, 2437, "WPA2"), ("MKS_DLC", 90, 2412, "WPA2"), ("Vicino", 30, 2462, "WPA2")]
        self.sys = ws.System(run=self.run, platform=platform)
        self.sys.local_ip = lambda: "127.0.0.9"

    def run(self, args, timeout=12, input_text=None):
        self.calls.append(list(args))
        a = list(args)
        if a[0] == "netsh":
            if a[1:4] == ["wlan", "show", "interfaces"]:
                return (0, f"    GUID : x\n    SSID   : {self.cur}\n    BSSID  : aa") if self.wifi else (1, "nessuna interfaccia")
            if a[1:4] == ["wlan", "show", "networks"]:
                return 0, "".join(f"SSID {i} : {n[0]}\n  T : I\n  A : WPA2-Personal\n  C : CCMP\n  BSSID 1 : x\n   S : {n[1]}%\n   R : n\n   Ch : 6\n"
                                  for i, n in enumerate(self.nets, 1))
            if a[1:4] == ["wlan", "add", "profile"]:
                p = a[4].split("=", 1)[1]
                self.files.append((p, open(p, encoding="utf-8").read()))
                return (0, "") if self.join_ok else (1, "no")
            if a[1:3] == ["wlan", "connect"]:
                name = a[3].split("=", 1)[1]
                if self.join_ok or name == HOME_NET:
                    self.cur = name
                    return 0, ""
                return 1, "no"
            return 0, ""
        if a[:5] == ["nmcli", "-t", "-f", "TYPE,STATE", "dev"]:
            return 0, ("wifi:connected\n" if self.wifi else "") + "ethernet:connected\n"
        if "list" in a:
            return 0, "\n".join(f"{'yes' if n[0] == self.cur else 'no'}:{n[0]}:{n[1]}:{n[2]} MHz:{n[3]}" for n in self.nets) if self.wifi else ""
        if a[:4] == ["nmcli", "dev", "wifi", "connect"]:
            if self.join_ok:
                self.cur = a[4]
                return 0, ""
            return 1, "Error: not authorized"
        if a[:3] == ["nmcli", "connection", "up"]:
            self.cur = a[4]
            return 0, ""
        return 0, ""


pc = Pc()
check("rete del PC (Linux): c'è il Wi-Fi, rete attuale, elenco con la rete del laser",
      pc.sys.has_wifi() and pc.sys.current() == HOME_NET and [n.ssid for n in pc.sys.scan()] == [HOME_NET, "MKS_DLC", "Vicino"])
check("PC col cavo di rete: niente Wi-Fi, nessuna rete", not Pc(wifi=False).sys.has_wifi() and Pc(wifi=False).sys.scan() == []
      and Pc(wifi=False).sys.current() is None)
check("prima di cambiare rete non c'è niente in sospeso", not pc.sys.pending() and pc.sys.back() is None)
ok = pc.sys.join("MKS_DLC", "12345678")
check("strada senza cavo: il PC passa alla rete del laser, e resta scritto dove tornare (la «guardia»)",
      ok and pc.cur == "MKS_DLC" and pc.sys.pending() and json.load(open(ws.guard_path()))["back"] == HOME_NET
      and ["nmcli", "dev", "wifi", "connect", "MKS_DLC", "password", "12345678"] in pc.calls)
check("un altro FreeLaserCut (un avvio dopo) vede il cambio rimasto a metà", ws.System(run=pc.run, platform="linux").pending())
back = pc.sys.back()
check("ritorno: il PC torna sulla rete di prima e il profilo temporaneo viene cancellato; non resta niente in sospeso",
      back == HOME_NET and pc.cur == HOME_NET and ["nmcli", "connection", "delete", "id", "MKS_DLC"] in pc.calls
      and not pc.sys.pending() and not os.path.exists(ws.guard_path()))
pcw = Pc(platform="win32")
okw = pcw.sys.join("MKS_DLC", "12345678")
check("lo stesso su Windows (netsh): profilo aggiunto, collegato, e il file con la password della rete del laser non resta",
      okw and pcw.cur == "MKS_DLC" and len(pcw.files) == 1 and "<keyMaterial>12345678</keyMaterial>" in pcw.files[0][1]
      and "<name>MKS_DLC</name>" in pcw.files[0][1] and not os.path.exists(pcw.files[0][0]))
pcw.sys.back()
check("…e al ritorno: ricollegato alla rete di casa, profilo temporaneo cancellato",
      pcw.cur == HOME_NET and ["netsh", "wlan", "delete", "profile", "name=MKS_DLC"] in pcw.calls and not pcw.sys.pending())
bad = Pc(join_ok=False)
check("se il sistema rifiuta il cambio di rete lo si sa (e la guardia c'è comunque, per sicurezza)",
      bad.sys.join("MKS_DLC", "12345678") is False and bad.cur == HOME_NET and bad.sys.pending())
bad.sys.back()
check("stessa rete locale: sì, no, non si sa", ws.same_subnet("192.168.1.110", "192.168.1.5") is True
      and ws.same_subnet("192.168.1.110", "192.168.0.5") is False and ws.same_subnet("192.168.1.110", None) is None)
os.environ.pop("FLC_PROVA_RETE")
asked, real_probe = [], ws.probe
ws.probe = lambda host, port, **k: asked.append(host)  # nessun collegamento vero: guardo solo a chi si rivolgerebbe
ws.find_lasers(["8.8.8.8", "192.168.1.5", "1.1.1.1", "10.0.0.7", "127.0.0.1"], (80,), max_s=1.0)
ws.probe = real_probe
check("la ricerca resta nella rete locale: 253 indirizzi della stessa rete, niente per un indirizzo pubblico o sconosciuto",
      len(ws.subnet_hosts("192.168.1.10")) == 253 and "192.168.1.10" not in ws.subnet_hosts("192.168.1.10")
      and ws.subnet_hosts("8.8.8.8") == [] and ws.subnet_hosts(None) == [] and ws.subnet_hosts("127.0.0.1") == [])
check("…e anche se le si passano indirizzi pubblici, la ricerca non si rivolge mai a loro",
      sorted(asked) == ["10.0.0.7", "192.168.1.5"], asked)
os.environ["FLC_PROVA_RETE"] = "1"


class Laser(threading.Thread):
    """Un laser finto in rete: un simulatore dietro una porta TCP (come il telnet della scheda)."""

    def __init__(self, host="127.0.0.1", port=0, kind="lgt", grbl=True, **wifi):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((host, port))
        self.srv.listen(8)
        self.host, self.port = host, self.srv.getsockname()[1]
        self.grbl, self.alive = grbl, True
        self.one = threading.Lock()
        self.sim = SimSerial()
        self.sim.speedup = 50
        self.w = self.sim.wifi_board(kind, **wifi) if kind else None
        self.start()

    def run(self):
        while self.alive:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(c,), daemon=True).start()

    def serve(self, c):
        with self.one:  # un collegamento alla volta, come il telnet della scheda: il successivo aspetta
            self._serve(c)

    def _serve(self, c):
        if not self.grbl:
            try:
                c.recv(100)
                c.sendall(b"HTTP/1.0 400 Bad Request\r\n\r\n")
            except OSError:
                pass
            c.close()
            return
        self.sim.reset_input_buffer()
        stop = threading.Event()

        def pump():
            while not stop.is_set():
                try:
                    line = self.sim.readline()
                except OSError:  # la scheda si è riavviata facendo cadere il collegamento
                    self.sim = SimSerial()
                    break
                if line:
                    try:
                        c.sendall(line)
                    except OSError:
                        break
            try:
                c.close()
            except OSError:
                pass
        th = threading.Thread(target=pump, daemon=True)
        th.start()
        try:
            while True:
                data = c.recv(1024)
                if not data:
                    break
                self.sim.write(data)
        except OSError:
            pass
        stop.set()
        th.join(2.0)

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


L1 = Laser()
other = Laser(grbl=False)
hit = ws.probe("127.0.0.1", L1.port)
check("un laser in rete si riconosce dalla risposta a «$I»", hit is not None and hit["port"] == L1.port and hit["ver"].startswith("[VER:"), hit)
check("un apparecchio che non è un laser (risponde altro) non viene preso; una porta chiusa nemmeno",
      ws.probe("127.0.0.1", other.port) is None and ws.probe("127.0.0.1", free_port()) is None)
t0 = time.time()
found = ws.find_lasers(ws.subnet_hosts("127.0.0.9"), (L1.port, other.port), max_s=6.0)
check("«Trova il laser in rete»: nella rete locale trova il laser e solo lui, in pochi secondi",
      [(f["host"], f["port"]) for f in found] == [("127.0.0.1", L1.port)] and time.time() - t0 < 7.5, (found, time.time() - t0))
check("lo stesso laser di prima: per versione della scheda; senza identità solo se ce n'è uno; mai a caso fra due uguali",
      ws.pick_same(found, hit["ver"]) is found[0] and ws.pick_same(found, "[VER:altro]") is None and ws.pick_same(found) is found[0]
      and ws.pick_same(found * 2) is None and ws.pick_same(found * 2, hit["ver"]) is None and ws.pick_same([]) is None)
other.close()

# ================================================================== finestra e simulatore
w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ctl = w.ctl
type(ctl).WAKE_AFTER_S = 3600  # niente «sveglia» con Ctrl+X a una scheda lenta a rispondere: qui disturberebbe le prove
sent = []
ctl.line_sent.connect(sent.append)


def usb(kind="lgt", **wifi):
    """Collega il simulatore come una scheda con il Wi-Fi collegata col cavo. -> lo stato della scheda finta."""
    if ctl.connected:
        ctl.disconnect_port()
        until(lambda: not ctl.connected, 3)
    SimSerial.preset = None
    ctl.connect_port(SIM_PORT)
    ctl.sim.speedup = 50
    wf = ctl.sim.wifi_board(kind, **wifi) if kind else None
    # come nel programma: dopo un secondo e mezzo dal collegamento partono da soli $I e $$
    until(lambda: ctl.last_status.get("state") == "Idle" and ctl.board_info and ctl.board_settings, 20)
    app.processEvents()
    return wf


def wizard(pc_=None):
    pc_ = pc_ or Pc()
    d = dw.WifiWizard(w, system=pc_.sys)
    d.pc = pc_
    d.start()
    return d


T_STATE = float(os.environ.get("FLC_PROVA_ATTESA", "40"))  # quanto aspettare una pagina (di solito arriva in un attimo)


def to_state(d, *states, t=T_STATE):
    until(lambda: d.state in states, t)
    return d.state in states


def run_net(d, ssid=HOME_NET, pwd="passwordgiusta", port=None):
    """Dalla pagina B alla scrittura: sceglie la rete, scrive la password, preme «Collega»."""
    if d.state == "B":
        d.press("net")
    to_state(d, "net")
    until(lambda: d.list.count() > 0, 20)
    d.ssid.setText(ssid)
    d.pwd.setText(pwd)
    if port:
        d.port.setValue(port)
    d.press("write")


# ================================================================== 1. privacy: la password non compare mai
wf = usb("lgt", nets={HOME_NET: SECRET}, join_ip="127.0.0.1")
console = w.console if hasattr(w, "console") else None
d = wizard()
to_state(d, "B")
run_net(d, pwd=SECRET, port=L1.port)
ok = to_state(d, "ok")
check("(giro completo con la password di prova: il laser entra in rete e risponde)", ok and wf["password"] == SECRET, (d.state, wf))
for typed in (f"[ESP101]{SECRET}", f"$54={SECRET}", "$G"):  # scritti a mano nella console
    w.console.input.setText(typed)
    w.console.send()
ctl.send_line("$$")
until(lambda: any("$$" in s for s in sent[-3:]), 3)
time.sleep(0.5)
app.processEvents()
check("la password è arrivata alla scheda (in chiaro, come deve), ma nei comandi mostrati è mascherata",
      f"$54={SECRET}" in wf["log"] and not any(SECRET in s for s in sent) and any(s == "$54=" + M for s in sent), sent[-8:])
texts = {}
for name, obj in (("console", getattr(w, "console", None)), ("console del pannello", getattr(getattr(w, "laser", None), "console", None))):
    if obj is not None and hasattr(obj, "log"):
        texts[name] = obj.log.toPlainText()
        if hasattr(obj, "history"):
            texts[name + " (memoria dei comandi)"] = "\n".join(obj.history)
texts["registro della comunicazione"] = w.comm_log.text() if hasattr(w, "comm_log") else ""
if getattr(w, "remote", None) is not None:  # quello che legge Claude con «console» (comando a distanza)
    texts["comando a distanza"] = "\n".join(l for _t, _d, l in w.remote.console)
from freelasercut import remote as remote_mod  # noqa: E402

rs = remote_mod.RemoteServer.__new__(remote_mod.RemoteServer)
import collections  # noqa: E402

rs.console = collections.deque(maxlen=200)
ctl.line_sent.connect(lambda l: rs._cons(">", l))
ctl.line_received.connect(lambda l: rs._cons("<", l))
ctl.send_line(f"$Sta/Password={SECRET}")
until(lambda: any("Sta/Password" in l for _t, _d, l in rs.console), 3)
texts["comando a distanza (righe viste da Claude)"] = "\n".join(l for _t, _d, l in rs.console)
for attr in ("recorder", "diag_rec", "comm", "comm_rec"):
    if hasattr(w, attr) and hasattr(getattr(w, attr), "text"):
        texts["registro (" + attr + ")"] = getattr(w, attr).text()
check("console, memoria dei comandi, registro della comunicazione e comando a distanza: hanno lo scambio, mascherato",
      M in texts["console"] and M in texts["registro della comunicazione"] and "console (memoria dei comandi)" in texts
      and "$Sta/Password=" + M in texts["comando a distanza (righe viste da Claude)"], {k: len(v) for k, v in texts.items()})
check("la password non è in nessuna console né nel registro della comunicazione", not any(SECRET in t for t in texts.values()),
      [k for k, v in texts.items() if SECRET in v])
check("un comando con la password scritto a mano non resta nella memoria della console (freccia su); gli altri sì",
      w.console.history == ["$G"], w.console.history)
bk = board_backup.to_text({53: HOME_NET, 54: SECRET, 52: "12345678", 130: "450.000"}, ["[VER:x]"], "Wi-Fi", "COM3")
check("le copie delle impostazioni della scheda hanno la password mascherata (anche quella della rete propria)",
      SECRET not in bk and "$54=" + M in bk and "$52=" + M in bk and "$53=CasaMia" in bk and "$130=450.000" in bk, bk)
folder = os.path.join(TMP, "copie")
os.makedirs(folder)
p1 = board_backup.save({53: HOME_NET, 54: SECRET, 130: "450.000"}, [], "Wi-Fi", "COM3", folder)
p2 = board_backup.save({53: HOME_NET, 54: SECRET, 130: "450.000"}, [], "Wi-Fi", "COM3", folder)
check("…sul disco: niente password, e a valori uguali non si fa una copia in più", SECRET not in open(p1, encoding="utf-8").read()
      and p1 == p2 and len(os.listdir(folder)) == 1)
saved_copy = board_backup.parse(open(p1, encoding="utf-8").read())
lines = board_backup.restore_lines({53: "AltraRete", 54: "altrapassword", 130: "400.000"}, saved_copy)
check("il ripristino da una copia non rimanda mai le impostazioni del Wi-Fi né un valore mascherato; il resto sì",
      lines == ["$130=450.000"], lines)
import io  # noqa: E402
import zipfile  # noqa: E402

from freelasercut import diag  # noqa: E402

rec = w.comm_log
rec.settings = {53: HOME_NET, 54: SECRET, 52: "12345678", 130: "450.000"}
with open(os.path.join(board_backup.backup_dir(), "scheda-20261101-101010.txt"), "w", encoding="utf-8") as fh:
    fh.write(f"{board_backup.HEADER}\n; 2026-11-01 10:10:10\n$53={HOME_NET}\n$54={SECRET}\n$130=450.000\n")  # una copia di prima della 0.18.17
zp = os.path.join(TMP, "rapporto.zip")
diag.make_report(zp, w, rec)
with zipfile.ZipFile(zp) as z:
    rep = {n: z.read(n).decode("utf-8", "replace") for n in z.namelist() if not n.lower().endswith(".png")}
rep_text = "\n".join(rep.values())
check("il rapporto per l'assistenza: le impostazioni della scheda ci sono, la password no",
      "$53=CasaMia" in rep.get("impostazioni-grbl.txt", "") and "$54=" + M in rep.get("impostazioni-grbl.txt", "")
      and SECRET not in rep_text, [n for n, t in rep.items() if SECRET in t] or sorted(rep))
check("…nemmeno quella rimasta in chiaro in una copia delle impostazioni fatta con una versione precedente",
      "scheda-20261101-101010.txt" in rep_text and SECRET not in rep_text and rep_text.count("$54=" + M) >= 2)
os.remove(os.path.join(board_backup.backup_dir(), "scheda-20261101-101010.txt"))
w.qs.sync()
ini_text = open(INI, encoding="utf-8", errors="replace").read() if os.path.exists(INI) else ""
check("nelle preferenze salvate c'è l'indirizzo del laser, non la password", SECRET not in ini_text and "net_ports" in ini_text, ini_text[-200:])
check("…e nella finestra della procedura il campo della password è stato svuotato", d.pwd.text() == "")
alltmp = []
for dp, _dn, fns in os.walk(TMP):
    for fn in fns:
        try:
            if SECRET in open(os.path.join(dp, fn), encoding="utf-8", errors="replace").read():
                alltmp.append(fn)
        except OSError:
            pass
check("in tutta la cartella dei dati di FreeLaserCut nessun file contiene la password", not alltmp, alltmp)
d.accept()
if os.environ.get("FLC_PROVA_SOLO_LOGICA"):  # prova delle prove: i guasti alla logica e alla privacy si vedono già qui
    print(f"\n{sum(results)}/{len(results)} superati")
    sys.stdout.flush()
    os._exit(0 if all(results) else 1)

# ================================================================== 2. pagina 0: che cosa c'è adesso
usb("lgt")
log0 = len(ctl.sim.wifi["log"])
ctl._job_active = True  # un lavoro sta girando
d = wizard()
ctl._job_active = False
check("lavoro in corso: si ferma e lo dice, senza mandare niente alla scheda", d.state == "busy" and d.has("close")
      and not [l for l in ctl.sim.wifi["log"][log0:] if l.startswith(("[", "$"))], ctl.sim.wifi["log"][log0:])
d.accept()
until(lambda: ctl.last_status.get("state") == "Idle", 3)
ctl.sim.state = "Alarm"
until(lambda: ctl.last_status.get("state") == "Alarm", 3)
d = wizard()
check("allarme: propone «Sblocca la macchina»", d.state == "alarm" and d.has("unlock"))
d.press("unlock")
check("…e dopo lo sblocco prosegue da solo fino al caso giusto", to_state(d, "B"), d.state)
d.accept()
usb(None)
admin.set_unlocked(w.qs, False)
d = wizard()
check("simulatore: spiega che serve un laser vero; la scheda finta non viene offerta", d.state == "sim" and not d.has("fake"))
d.accept()
admin.set_unlocked(w.qs, True)
d = wizard()
check("…con le funzioni in prova sbloccate c'è «Prova con una scheda finta», che porta al caso B",
      d.state == "sim" and d.has("fake") and (d.press("fake"), to_state(d, "B"))[1], d.state)
d.accept()
admin.set_unlocked(w.qs, False)
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)
d = wizard()
check("laser scollegato: la domanda «Hai il cavo USB a portata di mano?» con le tre strade",
      d.state == "E" and d.has("cable") and d.has("nocable") and d.has("find") and "cavo USB" in d.body.text())
d.accept()
wf = usb("none")
d = wizard()
check("scheda a 8 bit senza Wi-Fi: «si usa col cavo USB»", to_state(d, "C") and "cavo USB" in d.body.text() and not d.has("net"), d.state)
check("…e alla scheda sono arrivate solo due domande, nessuna impostazione",
      [l for l in wf["log"] if l.startswith(("[", "$")) and l not in ("$I", "$$")] == ["[ESP110]", "$Sta/SSID"], wf["log"])
d.accept()
wf = usb("locked")
d = wizard()
check("scheda con il Wi-Fi che rifiuta i comandi (schermo touch, app del produttore): lo dice e propone «Trova il laser in rete»",
      to_state(d, "D") and d.has("find") and "schermo" in d.body.text() and wf["boots"] == 0 and "MKS Laser Tool" not in d.body.text(), d.state)
d.accept()
wf = usb("lgt")
wf["mute"] = True  # da adesso la scheda non risponde più a niente
d = wizard()
check("scheda muta (non risponde): lo dice e propone di riprovare, senza concludere «niente Wi-Fi»",
      to_state(d, "mute") and d.has("retry"), d.state)
d.accept()
LA = Laser(kind="mks", mode="STA", ip="127.0.0.1", ssid=HOME_NET, password="passwordgiusta")
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)
ctl.connect_port(netport.make_port("127.0.0.1", LA.port))
until(lambda: ctl.connected and ctl.board_info, 20)
d = wizard()
check("già collegato via Wi-Fi: indirizzo, porta, scheda, «stessa rete: sì», e le scelte (prenota, cambia rete, spegni, chiudi)",
      d.state == "A" and "127.0.0.1" in d.body.text() and str(LA.port) in d.body.text() and "sì" in d.body.text()
      and all(d.has(k) for k in ("off", "change", "router", "close")), d.body.text())
d.press("router")
check("«Prenota l'indirizzo nel router»: compare la mini-guida", "DHCP" in d.body.text() and "127.0.0.1" in d.body.text())
d.press("change")
check("«Cambia rete»: serve il cavo o la rete propria (la stessa domanda del caso E)", d.state == "E" and d.has("cable") and d.has("nocable"))
d.accept()
d = wizard()
d.confirm = lambda text: False
d.press("off")
check("«Spegni il Wi-Fi della scheda» chiede conferma: con «no» non succede niente", d.state == "A" and LA.w["mode"] == "STA")
d.confirm = lambda text: True
d.press("off")
check("…con «sì» la scheda riceve lo spegnimento e il riavvio, e la finestra dice che ora serve il cavo",
      to_state(d, "off_done") and LA.w["mode"] == "OFF" and LA.w["boots"] == 1 and "cavo USB" in d.body.text(), (d.state, LA.w["mode"]))
d.accept()
ctl.disconnect_port()
LA.close()

# ================================================================== 3. famiglie di schede: giro completo col cavo
EXPECT = {
    "lgt": ["$53=CasaMia", "$54=passwordgiusta", "[ESP110]STA", "[ESP444]RESTART"],
    "mks": ["[ESP100]CasaMia", "[ESP101]passwordgiusta", "[ESP110]STA", "[ESP444]RESTART"],
    "grbl_esp32": ["[ESP100]CasaMia", "[ESP101]passwordgiusta", "[ESP110]STA", "[ESP444]RESTART"],
    "fluidnc": ["$Sta/SSID=CasaMia", "$Sta/Password=passwordgiusta", "$WiFi/Mode=STA", "$Bye"],
}
for kind, exp in EXPECT.items():
    wf = usb(kind, join_ip="127.0.0.1")
    info0 = list(ctl.board_info)
    d = wizard()
    okb = to_state(d, "B")
    fam, port0 = d.family, d.port.value()
    run_net(d, port=L1.port)
    okk = to_state(d, "ok")
    wrote = [l for l in wf["log"] if "=" in l or l.startswith("[ESP1") and "]" in l and l.split("]")[1] or l in ("$Bye", "[ESP444]RESTART")]
    wrote = [l for l in wrote if l not in ("[ESP110]", "[ESP111]")]
    check(f"scheda {kind}: riconosciuta, rete scritta con i suoi comandi, riavviata, entrata in rete, indirizzo provato e salvato",
          okb and okk and wrote == exp and wf["boots"] == 1 and d.result == netport.make_port("127.0.0.1", L1.port),
          (d.state, fam, wrote))
    check(f"…{kind}: famiglia «{'named' if kind == 'fluidnc' else 'esp'}», porta proposta {23 if kind == 'fluidnc' else 8080}",
          fam == ("named" if kind == "fluidnc" else "esp") and port0 == (23 if kind == "fluidnc" else 8080), (fam, port0))
    if kind == "lgt":
        check("…Longer: la scheda diceva «No Wifi» (= Wi-Fi spento, non «senza Wi-Fi»): caso B lo stesso; $50 mai scritto",
              okb and any("No Wifi" in l for l in info0) and not any(l.startswith("$50") for l in wf["log"]), (info0, wf["log"]))
    d.accept()
wf = usb("numeric", join_ip="127.0.0.1")
d = wizard()
okb = to_state(d, "B")
note = "collaudare" in d.body.text()
run_net(d, port=L1.port)
okp = to_state(d, "power")
check("scheda che ha solo $50…$54 (famiglia a numeri): rete in $53/$54, modalità con $50=1 dopo che «[ESP110]STA» è stato rifiutato",
      okb and d.family == "numeric" and note and okp and [l for l in wf["log"] if re.match(r"^\$5\d=", l)] ==
      ["$53=CasaMia", "$54=passwordgiusta", "$50=1"], (d.state, wf["log"]))
check("…non si riavvia da sola: la finestra chiede di spegnere e riaccendere, senza mandare altro", wf["boots"] == 0 and d.has("done"))
d.press("done")
ctl.sim._wifi_restart()  # la persona spegne e riaccende il laser
check("…dopo il riavvio a mano: entrata in rete e salvata", to_state(d, "ok"), d.state)
d.accept()

# ================================================================== 4. pagina «rete»
wf = usb("lgt", join_ip="127.0.0.1")
pc_ = Pc(nets=[(HOME_NET, 80, 5180, "WPA2"), (HOME_NET, 60, 2437, "WPA2"), ("MKS_DLC", 90, 2412, "WPA2"), ("Solo5", 70, 5200, "WPA2"),
               ("Ufficio", 50, 2437, "WPA2 802.1X"), ("Casa-Guest", 40, 2437, "WPA2"), ("Bar", 30, 2437, "--")])
d = wizard(pc_)
to_state(d, "B")
check("caso B con il Wi-Fi spento: lo dice e propone «Avanti: scegli la rete»", "spento" in d.body.text() and d.has("net"), d.body.text())
d.press("net")
until(lambda: d.list.count() > 0, 20)
items = [d.list.item(i).text() for i in range(d.list.count())]
check("elenco delle reti viste dal PC, con banda e segnale; la rete propria del laser non è fra le scelte",
      d.state == "net" and len(items) == 6 and not any("MKS_DLC" in t for t in items) and any("2,4 GHz" in t for t in items)
      and any("5 GHz" in t for t in items), items)
check("preselezionata la rete di questo PC (nella versione a 2,4 GHz), scritta anche nel campo del nome",
      d.ssid.text() == HOME_NET and d.list.currentItem() is not None and d.list.currentItem().data(0x0100).band == "2.4"
      and "questo PC" in d.list.currentItem().text(), (d.ssid.text(), d.list.currentItem() and d.list.currentItem().text()))
check("senza password il pulsante «Collega» è spento", not d._buttons["write"].isEnabled())
d.pwd.setText("1234567")
check("password di 7 caratteri: bloccata, con il motivo", not d._buttons["write"].isEnabled() and "8 caratteri" in d.warn.text(), d.warn.text())
d.pwd.setText("12345678")
check("password di 8 caratteri: si può proseguire, nessun avviso sulla rete di casa", d._buttons["write"].isEnabled() and d.warn.text() == "", d.warn.text())
check("il campo della password è nascosto; l'occhio la mostra", d.pwd.echoMode() == d.pwd.EchoMode.Password
      and (d.eye.setChecked(True), d.pwd.echoMode() == d.pwd.EchoMode.Normal)[1])
d.eye.setChecked(False)
for name, word, blocks in (("Solo5", "5 GHz", False), ("Ufficio", "aziendale", True), ("Casa-Guest", "ospiti", False), ("Bar", "aperta", False)):
    it = next(d.list.item(i) for i in range(d.list.count()) if d.list.item(i).text().startswith(name))
    d.list.setCurrentItem(it)
    d._pick_net(it)
    d.pwd.setText("" if name == "Bar" else "12345678")
    check(f"rete «{name}»: {'bloccata' if blocks else 'avviso'} ({word})", word in d.warn.text()
          and d._buttons["write"].isEnabled() == (not blocks) and "stessa rete" in d.warn.text(), d.warn.text())
d.ssid.setText("ReteNascosta")
d.pwd.setText("12345678")
check("nome scritto a mano (rete nascosta): si può, con l'avviso che non è la rete del PC", d._buttons["write"].isEnabled()
      and "stessa rete" in d.warn.text())
d.confirm = lambda text: False
n_log = len(wf["log"])
d.press("write")
check("rete diversa da quella del PC: chiede conferma; con «no» si resta sulla pagina e non si scrive niente",
      d.state == "net" and wf["log"][n_log:] == [], wf["log"][n_log:])
check("«Avanzate»: la porta è nascosta finché non si apre, ed è 8080 per questa scheda", d.port.isHidden() and d.port.value() == 8080
      and (d.adv.setChecked(True), not d.port.isHidden())[1])
d.accept()

# ================================================================== 5. scrittura e riavvio
wf = usb("lgt", reject=("$54",))
d = wizard()
to_state(d, "B")
run_net(d)
check("un comando rifiutato a metà (la password, in tutte le forme): caso D, e la scheda NON viene riavviata",
      to_state(d, "D") and wf["boots"] == 0 and "[ESP444]RESTART" not in wf["log"] and wf["mode"] == "OFF", (d.state, wf["log"]))
check("…per le schede Longer e Makerbase il testo ricorda lo strumento del produttore", "MKS Laser Tool" in d.body.text())
d.accept()
wf = usb("lgt", join_ip="127.0.0.1", drop=True)
d = wizard()
to_state(d, "B")
run_net(d, port=L1.port)
check("al riavvio la porta USB cade: la riapro da solo e la procedura arriva in fondo", to_state(d, "ok") and ctl.connected
      and ctl.port == SIM_PORT, d.state)
d.accept()
wf = usb("lgt", join_ip="127.0.0.1", drop=True)
d = wizard()
to_state(d, "B")
real_connect = ctl.connect_port
run_net(d, port=L1.port)
until(lambda: d.state == "wait", 30)
ctl.connect_port = lambda *a, **k: False  # la porta non torna
check("…se la porta non torna: lo spiega, chiede di spegnere e riaccendere il laser e propone «Trova il laser in rete»",
      to_state(d, "serial_lost") and d.has("find") and "riaccendi" in d.body.text(), d.state)
ctl.connect_port = real_connect
SimSerial.preset = None
d.accept()

for _ in range(3):  # scollega e ricollega di corsa, come «Usa il Wi-Fi adesso»
    ctl.disconnect_port()
    ctl.connect_port(SIM_PORT)
time.sleep(0.8)
readers = [t.name for t in threading.enumerate() if "_read_loop" in t.name]
pollers = [t.name for t in threading.enumerate() if "_poll_loop" in t.name]
check("scollegando e ricollegando di corsa resta un solo lettore della porta (prima ne restavano due, e le risposte "
      "si perdevano)", len(readers) == 1 and len(pollers) == 1, (readers, pollers))
ctl.disconnect_port()

# ================================================================== 6. esiti
wf = usb("lgt", join_ip="127.0.0.1")
netport.forget(w.qs, netport.make_port("127.0.0.1", L1.port))
d = wizard()
to_state(d, "B")
run_net(d, port=L1.port)
okk = to_state(d, "ok")
port = netport.make_port("127.0.0.1", L1.port)
check("esito buono: «Connected with…», stessa rete, la porta risponde → indirizzo salvato con il nome del profilo e la versione",
      okk and port in netport.saved(w.qs) and netport.info(w.qs, port)["name"] == w.profile.name
      and netport.info(w.qs, port)["ver"].startswith("[VER:") and all(d.has(k) for k in ("use", "router", "close")), d.state)
check("…l'etichetta dell'indirizzo porta il nome del profilo (per distinguere più laser)",
      netport.label(port, w.qs).endswith("— " + w.profile.name) and netport.label(port) == f"Wi-Fi  127.0.0.1:{L1.port}")
d.press("use")
check("«Usa il Wi-Fi adesso»: stacca il cavo (simulato), si collega all'indirizzo salvato e lo ricorda come porta",
      until(lambda: ctl.connected and ctl.port == port, 30) and w.qs.value("port") == port and not d.isVisible(), (ctl.port, d.state))
ctl.disconnect_port()
L2 = Laser(host="127.0.5.1", port=L1.port + 1 if L1.port < 65000 else 0)
wf = usb("lgt", join_ip="127.0.5.1")
d = wizard()
to_state(d, "B")
run_net(d, port=L2.port)
check("collegata ma in un'altra sottorete: avviso (ospiti, altro router, apparecchi separati) con «Cambia rete» e «Va bene così»",
      to_state(d, "other_subnet") and d.has("change") and d.has("keep") and "127.0.5.1" in d.body.text()
      and "127.0.0.9" in d.body.text(), d.state)
d.press("change")
check("…«Cambia rete» riporta alla scelta della rete", d.state == "net")
d.accept()
wf = usb("lgt", join_ip="127.0.5.1")
d = wizard()
to_state(d, "B")
run_net(d, port=L2.port)
to_state(d, "other_subnet")
d.press("keep")
check("…«Va bene così»: prova lo stesso l'indirizzo e, se risponde, lo salva", to_state(d, "ok")
      and d.result == netport.make_port("127.0.5.1", L2.port), d.state)
d.accept()
L2.close()
dead = free_port()
wf = usb("lgt", join_ip="127.0.0.1")
d = wizard()
to_state(d, "B")
run_net(d, port=dead)
check("collegata, ma nessuna porta risponde: dice quali ha provato, suggerisce la pagina della scheda e le «Avanzate»",
      to_state(d, "no_port") and str(dead) in d.body.text() and "8080" in d.body.text() and "http://127.0.0.1" in d.body.text()
      and d.has("retry") and d.result is None, d.state)
d.accept()
pc_ = Pc(nets=[(HOME_NET, 80, 5180, "WPA2"), ("MKS_DLC", 90, 2412, "WPA2")])
wf = usb("lgt", join_ip="127.0.0.1")
d = wizard(pc_)
to_state(d, "B")
run_net(d, pwd="passwordsbagliata", port=L1.port)
check("non entrata («Cannot connect», torna a 192.168.4.1): le cause in ordine, da quello che si sa (qui: rete a 5 GHz, poi la password)",
      to_state(d, "failed") and "192.168.4.1" in d.body.text() and d.body.text().index("5 GHz") < d.body.text().index("password")
      and d.has("retry") and wf["mode"] == "AP", (d.state, d.body.text()[-300:]))
d.press("retry")
check("…«Correggi e riprova» riporta alla rete, con il nome ancora scritto e la password da riscrivere",
      d.state == "net" and d.ssid.text() == HOME_NET and d.pwd.text() == "")
d.accept()
wf = usb("lgt", join_ip="127.0.0.1", messages=False)
d = wizard()
to_state(d, "B")
run_net(d, port=L1.port)
check("la scheda non dice niente: allo scadere del tempo le chiedo l'indirizzo («[ESP111]») e proseguo",
      to_state(d, "ok") and wf["log"].count("[ESP111]") >= 2, (d.state, wf["log"][-4:]))
d.accept()
wf = usb("numeric", join_ip="127.0.0.1", messages=False)
d = wizard()
to_state(d, "B")
run_net(d, port=L1.port)
to_state(d, "power")
d.press("done")
check("nessun messaggio e nessun modo di chiederlo: «non so se si è collegata», con «Trova il laser in rete» e «Riprova»",
      to_state(d, "unknown") and d.has("find") and d.has("retry"), d.state)
d.accept()

# ================================================================== 7. con il cavo (E1) e senza cavo (E2)
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)
ports_now = []
dw.list_serial_ports = lambda: [(p, p, False) for p in ports_now] + [(SIM_PORT, "sim", False)]


def fake_usb(port, baud=115200):
    SimSerial.preset = lambda sim: (setattr(SimSerial, "preset", None), sim.wifi_board("lgt"))
    return real_connect(SIM_PORT, baud)


ctl.connect_port = fake_usb
d = wizard()
d.press("cable")
check("«Sì, ho il cavo»: chiede di collegarlo e aspetta la porta nuova", d.state == "E1" and "Collega il cavo" in d.title.text())
ports_now.append("COM9")
check("la porta compare: mi collego da solo e arrivo al caso B", to_state(d, "B") and ctl.connected, d.state)
d.accept()
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)
ports_now.clear()
d = wizard()
d.press("cable")
check("la porta non compare: cause possibili (laser spento, cavo solo-ricarica, driver CH340/CP210x) e «Riprova»",
      to_state(d, "E1_none") and "CH340" in d.body.text() and "ricaricare" in d.body.text() and d.has("retry"), d.state)
d.accept()
dw.list_serial_ports = lambda: [("COM7", "COM7 — USB-SERIAL CH340", True), (SIM_PORT, "sim", False)]
d = wizard()
d.press("cable")
check("il cavo è già collegato: trova da solo la porta del laser, senza chiedere quale", to_state(d, "B"), d.state)
d.accept()
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)
ctl.connect_port = real_connect
SimSerial.preset = None
dw.list_serial_ports = lambda: [(SIM_PORT, "sim", False)]

d = wizard(Pc(wifi=False))
d.press("nocable")
check("senza cavo, ma il PC non ha il Wi-Fi (è in rete col cavo): si dice subito, con «Uso il cavo USB» e «Trova il laser in rete»",
      to_state(d, "E2_nowifi") and d.has("cable") and d.has("find"), d.state)
d.accept()
ws.PORTS = (free_port(),)
pc_ = Pc(nets=[(HOME_NET, 80, 2437, "WPA2")])
d = wizard(pc_)
d.press("nocable")
check("senza cavo e nessuna rete del laser in vista: prova «Trova il laser in rete»; se non c'è, «serve il cavo USB»",
      to_state(d, "find_none") and "serve il cavo USB" in d.body.text() and d.has("cable") and pc_.cur == HOME_NET, d.state)
d.accept()

AP = Laser(kind="mks", mode="AP", ip="192.168.4.1", join_ip="127.0.0.1")  # la scheda sulla sua rete propria
ws.OWN_NET_IP, ws.PORTS = "127.0.0.1", (AP.port,)
pc_ = Pc()
d = wizard(pc_)
d.port.setValue(AP.port)
d.press("nocable")
check("senza cavo: trovata la rete del laser, spiega che per un minuto il PC cambia rete e poi torna su «CasaMia»",
      to_state(d, "E2_pick") and d.has("join") and HOME_NET in d.body.text(), d.state)
d.press("join")
okn = to_state(d, "net")
check("il PC passa alla rete del laser (password predefinita), mi collego a 192.168.4.1 e riconosco la scheda",
      okn and pc_.cur == "MKS_DLC" and ["nmcli", "dev", "wifi", "connect", "MKS_DLC", "password", "12345678"] in pc_.calls
      and ctl.connected and netport.is_net(ctl.port) and d.family == "esp", (d.state, pc_.cur))
check("…le reti proposte sono quelle viste prima del cambio, con preselezionata quella di casa", d.ssid.text() == HOME_NET and d.list.count() >= 1)
d.pwd.setText("passwordgiusta")
d.press("write")
okk = to_state(d, "ok")
check("rete scritta dalla rete del laser, scheda riavviata, PC riportato sulla rete di casa, laser ritrovato in rete e salvato",
      okk and AP.w["ssid"] == HOME_NET and AP.w["boots"] == 1 and pc_.cur == HOME_NET and not pc_.sys.pending()
      and ["nmcli", "connection", "delete", "id", "MKS_DLC"] in pc_.calls and d.result == netport.make_port("127.0.0.1", AP.port),
      (d.state, pc_.cur, AP.w["ssid"]))
d.accept()
ctl.disconnect_port()
AP.w.update(mode="AP", ip="192.168.4.1", boots=0)
pc_ = Pc(join_ok=False)
d = wizard(pc_)
d.port.setValue(AP.port)
d.press("nocable")
to_state(d, "E2_pick")
d.press("join")
check("il sistema non lascia cambiare rete: istruzioni per farlo a mano e il pulsante «Fatto»",
      to_state(d, "E2_manual") and d.has("done") and "MKS_DLC" in d.body.text() and "12345678" in d.body.text(), d.state)
pc_.cur = "MKS_DLC"  # la persona si collega a mano
d.press("done")
check("…dopo «Fatto» prosegue come prima", to_state(d, "net") and ctl.connected, d.state)
d.reject()  # finestra chiusa a metà
check("finestra chiusa a metà mentre il PC è sulla rete del laser: il PC viene riportato sulla rete di casa",
      pc_.cur == HOME_NET and not pc_.sys.pending(), pc_.cur)
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)
ws.OWN_NET_IP = "127.0.0.77"  # sulla rete del laser non risponde nessuno
pc_ = Pc()
d = wizard(pc_)
d.press("nocable")
to_state(d, "E2_pick")
d.press("join")
check("la scheda non risponde sulla sua rete: il PC torna sulla rete di casa, e si propone il cavo",
      to_state(d, "E2_fail") and pc_.cur == HOME_NET and not pc_.sys.pending() and d.has("cable"), (d.state, pc_.cur))
d.accept()
pc_ = Pc()
pc_.sys.join("MKS_DLC", "12345678")  # FreeLaserCut chiuso di colpo con il PC sulla rete del laser…
d = wizard(pc_)
check("al prossimo avvio della procedura la «guardia» riporta il PC sulla rete di casa prima di tutto",
      pc_.cur == HOME_NET and not pc_.sys.pending(), pc_.cur)
d.accept()
pc_ = Pc()
pc_.sys.join("MKS_DLC", "12345678")
th = dw.restore_pc_network(pc_.sys)
th.join(10)
check("…e anche all'avvio di FreeLaserCut, senza aprire la procedura (e senza niente in sospeso non fa niente)",
      pc_.cur == HOME_NET and not pc_.sys.pending() and dw.restore_pc_network(pc_.sys) is None)
check("l'avvio del programma chiama la guardia prima di collegarsi", "restore_pc_network()" in open(os.path.join(
    ROOT, "freelasercut", "ui", "main_window.py"), encoding="utf-8").read().split("def _auto_connect")[1].split("def toggle_connection")[0])
ws.OWN_NET_IP = "192.168.4.1"

# ================================================================== 8. uso quotidiano: l'indirizzo è cambiato
ws.PORTS = (L1.port,)
ver = ws.probe("127.0.0.1", L1.port)["ver"]
old = netport.make_port("127.0.0.50", L1.port)  # dove stava ieri: oggi lì non c'è nessuno
for p in netport.saved(w.qs):
    netport.forget(w.qs, p)
netport.remember(w.qs, old)
netport.set_info(w.qs, old, "Laser del garage", ver)
w.qs.setValue("port", old)
w.refresh_ports()
real_local_ip = ws.System.local_ip
ws.System.local_ip = lambda self: "127.0.0.9"  # la «rete locale» di queste prove
w._auto_connect()
new = netport.make_port("127.0.0.1", L1.port)
check("all'avvio il laser non è più all'indirizzo salvato: lo ritrovo da solo nella rete, aggiorno l'indirizzo e mi collego",
      until(lambda: ctl.connected and ctl.port == new, 40) and w.qs.value("port") == new and netport.saved(w.qs) == [new]
      and netport.info(w.qs, new)["name"] == "Laser del garage", (ctl.port, netport.saved(w.qs)))
check("…e lo dico nella barra di stato", "ritrovato" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
ws.System.local_ip = real_local_ip
ctl.disconnect_port()
until(lambda: not ctl.connected, 3)
L3 = Laser(host="127.0.0.3", port=L1.port)  # un secondo laser uguale nella stessa rete
netport.forget(w.qs, new)
netport.remember(w.qs, old)
netport.set_info(w.qs, old, "Laser del garage", ver)
w.qs.setValue("port", old)
br = dw.refind(w, old, Pc().sys)
got = []
br.done.connect(got.append)
until(lambda: got, 40)
app.processEvents()
check("due laser uguali in rete: non ne scelgo uno a caso; l'indirizzo resta com'era e rimando alla procedura",
      len(got[0]) == 2 and not ctl.connected and w.qs.value("port") == old and "Collegamento Wi-Fi" in w.statusBar().currentMessage(),
      (got, w.statusBar().currentMessage()))
L3.close()
nog = Laser(grbl=False)
ws.PORTS = (nog.port,)
got.clear()
br = dw.refind(w, old, Pc().sys)
br.done.connect(got.append)
until(lambda: got, 40)
app.processEvents()
check("un apparecchio che non è un laser sulla stessa porta viene escluso; rete senza laser: il messaggio di sempre",
      got == [[]] and not ctl.connected and w.qs.value("port") == old, got)
nog.close()
pc_ = Pc()
pc_.sys.join("MKS_DLC", "12345678")
got.clear()
br = dw.refind(w, old, pc_.sys)
br.done.connect(got.append)
until(lambda: got, 40)
check("anche la ricerca all'avvio, se trova un cambio di rete rimasto a metà, riporta prima il PC sulla rete di casa",
      pc_.cur == HOME_NET and not pc_.sys.pending())

# ================================================================== 9. menu, finestra di sempre, configurazione guidata
acts = w.m_settings.actions()
check("Impostazioni → «Collegamento Wi-Fi del laser…», subito sotto «Configurazione guidata della macchina…»",
      acts.index(w.acts["wifi_wizard"]) == acts.index(w.acts["setup_wizard"]) + 1 and w.acts["wifi_wizard"].text().endswith("…"))
if os.environ["FLC_UI"] == "banco":
    from PySide6.QtWidgets import QToolButton

    gear = next((b for b in w.findChildren(QToolButton) if b.menu() is w.m_settings), None)
    check("nel Banco la rotella apre lo stesso menu: la voce c'è anche lì", gear is not None)
from freelasercut.ui import help_texts  # noqa: E402

card = getattr(help_texts, "HELP", None) or getattr(help_texts, "TEXTS", None) or next(
    v for v in vars(help_texts).values() if isinstance(v, dict) and "setup_wizard" in v)
check("la scheda d'aiuto della voce c'è e dice l'essenziale (2,4 GHz, stessa rete, 192.168.4.1, password non salvata)",
      "wifi_wizard" in card and all(t in card["wifi_wizard"][1] for t in ("2,4 GHz", "192.168.4.1", "non viene salvata", "router")))
dlg = w.wifi_wizard()
check("la voce apre la procedura (qui, a laser scollegato, sulla domanda del cavo)", isinstance(dlg, dw.WifiWizard) and dlg.state == "E")
dlg.accept()
from freelasercut.ui.dialogs_net import NetDialog  # noqa: E402

usb("lgt")
nd = NetDialog(w.qs, w)
check("finestra «Collegamento via Wi-Fi» di sempre: c'è «Configura il Wi-Fi della scheda…» e la porta proposta per Longer / Makerbase è 8080",
      not nd.b_wizard.isHidden() and nd.num.value() == 8080, nd.num.value())
check("…gli indirizzi usati portano il nome del profilo", nd.list.count() == 1 and "Laser del garage" in nd.list.item(0).text(),
      nd.list.item(0).text() if nd.list.count() else "")
usb("none")
w.profile.name = "Laser qualsiasi"
check("…per una scheda che non è Longer né Makerbase la porta proposta resta 23", NetDialog(w.qs, w).num.value() == 23)
from freelasercut.ui.dialogs_setup import SetupWizard  # noqa: E402

sw = SetupWizard(w)
check("configurazione guidata della macchina, ultima pagina: la riga sul Wi-Fi non c'è per una scheda senza Wi-Fi",
      sw.wifi_hint.isHidden())
sw.reject()
usb("lgt")
sw = SetupWizard(w)
check("…e c'è per una scheda con il Wi-Fi (ESP32)", not sw.wifi_hint.isHidden() and "Collegamento Wi-Fi del laser" in sw.wifi_hint.text())
sw.reject()
ctl.disconnect_port()

keys = set()
for name in ("ui/dialogs_wifi.py", "ui/dialogs_net.py", "ui/dialogs_setup.py", "ui/help_texts.py", "ui/main_window.py"):
    src = open(os.path.join(ROOT, "freelasercut", name), encoding="utf-8").read()
    for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', src):
        try:
            k = "".join(ast.literal_eval(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
        except (SyntaxError, ValueError):
            continue
        if name.endswith("dialogs_wifi.py") or any(t in k for t in ("Wi-Fi del laser", "Wi-Fi della scheda", "rete di casa")):
            keys.add(k)
check("testi della procedura trovati nel codice", len(keys) >= 120, len(keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k[:40] for k in keys if not loc.get(k)]
    badp = [k[:40] for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    check(f"traduzioni {lang}: tutti i testi, con gli stessi segnaposto", not miss and not badp, (len(miss), miss[:3], badp[:3]))

L1.close()
AP.close()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
