# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Collegamento Wi-Fi del laser (0.18.17): la logica, senza Qt.

Mette in rete una scheda con il Wi-Fi integrato (ESP32) usando solo i comandi testuali pubblici che la scheda accetta
come righe GRBL, dal cavo USB o dal collegamento di rete: quelli documentati per le schede Makerbase MKS DLC32
(«[ESP100]rete», «[ESP101]password», «[ESP110]STA», «[ESP111]», «[ESP444]RESTART») e per Grbl_ESP32 / FluidNC
(«$Sta/SSID=», «$Sta/Password=», «$Radio/Mode=STA», «$WiFi/Mode=STA»). Nessun codice di altri programmi: è il
protocollo della scheda. Non aggiorna il firmware.

Qui dentro:
- mascheramento della password in tutto quello che viene mostrato o scritto (console, registro, copie, rapporto);
- famiglie di schede: come si riconoscono e in che ordine si provano i comandi;
- lettura dei messaggi della scheda («Connected with…», «Cannot connect to…», rete propria);
- controlli su nome della rete e password prima di scrivere;
- rete del PC: reti visibili, rete attuale, cambio temporaneo di rete con la «guardia» che riporta indietro;
- «Trova il laser in rete»: solo la rete locale, porte 8080 e 23, solo chi risponde come GRBL.
"""
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

MASK = "********"
OWN_NET_IP = "192.168.4.1"  # l'indirizzo della scheda quando fa da sé la rete («rete propria»)
OWN_NET_NAMES = ("MKS_DLC", "FluidNC", "GRBL_ESP", "ESP32", "LONGER", "LASER")  # inizio dei nomi delle reti proprie note
OWN_NET_PASSWORD = "12345678"  # quella predefinita delle schede MKS (pubblica, stampata nelle guide)
PORTS = (8080, 23)  # telnet: MKS / Longer 8080, Grbl_ESP32 / FluidNC 23
GUEST_WORDS = ("guest", "ospiti", "ospite", "gast", "gäste", "invitados", "invités", "invites", "convidados")
SPECIAL = set("$;()[]")

# ============================================================================ password mai in chiaro
_NUM_SHORT = re.compile(r"^-?\d{1,7}(\.\d+)?$")  # un valore numerico di GRBL (una password ha almeno 8 caratteri)
_SECRET = (
    re.compile(r"^(\s*\[ESP10[16]\])(.+)$", re.I),  # password della rete (101) e della rete propria (106)
    re.compile(r"^(\s*\$ESP10[16]\s*=\s*)(.+)$", re.I),
    re.compile(r"^(\s*\$(?:Sta|AP)/Password\s*=\s*)(.+)$", re.I),
)
_SECRET_NUM = re.compile(r"^(\s*\$(5[24]|7[57])\s*=\s*)(.+)$")  # $52/$54 (MKS, Longer), $75/$77 (grblHAL)


def _passwordish(value):
    v = str(value).strip()
    return bool(v) and not _NUM_SHORT.match(v) and v != MASK


def mask_line(line):
    """La riga com'è, ma con la password sostituita da asterischi. Vale per i comandi mandati e per le risposte."""
    s = str(line)
    for rx in _SECRET:
        m = rx.match(s)
        if m:
            return m.group(1) + MASK
    m = _SECRET_NUM.match(s)
    if m and _passwordish(m.group(3)):
        return m.group(1) + MASK
    return s


def has_secret(line):
    return mask_line(line) != str(line)


def mask_settings(settings):
    """{numero: valore} con le password Wi-Fi mascherate (per le copie e per il rapporto)."""
    out = {}
    for k, v in (settings or {}).items():
        try:
            n = int(k)
        except (TypeError, ValueError):
            n = None
        out[k] = MASK if n in (52, 54, 75, 77) and _passwordish(v) else v
    return out


def wifi_numbers(settings):
    """I numeri delle impostazioni che riguardano il Wi-Fi in questa scheda: non si ripristinano mai da una copia
    (la password nella copia è mascherata, e cambiare rete per sbaglio staccherebbe il laser)."""
    s = {}
    for k, v in (settings or {}).items():
        try:
            s[int(k)] = str(v)
        except (TypeError, ValueError):
            pass
    out = set()
    if any(n in s and (not _NUM_SHORT.match(s[n].strip()) or s[n].strip() == "") for n in (51, 52, 53, 54)):
        out |= {50, 51, 52, 53, 54}
    if any(n in s and not _NUM_SHORT.match(s[n].strip()) and s[n].strip() for n in (74, 75, 76, 77)):
        out |= set(range(70, 80))
    return out


# ============================================================================ famiglie di schede
# Per ogni cosa da fare, i comandi da provare in ordine: il primo che la scheda accetta («ok») vale. Un comando
# rifiutato («error») non cambia niente nella scheda.
CMDS = {
    "esp": {  # Makerbase MKS DLC32, Longer (LGT), Grbl_ESP32: comandi fra parentesi quadre
        "ssid": ("[ESP100]{0}", "$53={0}", "$Sta/SSID={0}"),
        "password": ("[ESP101]{0}", "$54={0}", "$Sta/Password={0}"),
        "sta": ("[ESP110]STA", "$Radio/Mode=STA"),
        "off": ("[ESP110]OFF", "$Radio/Mode=OFF"),
        "restart": ("[ESP444]RESTART",),
        "switch": ("$wifi=1",),  # solo per le schede con l'interruttore «$wifi» (vedi has_wifi_switch)
        "port": 8080,
    },
    "named": {  # Grbl_ESP32 e FluidNC: impostazioni con il nome
        "ssid": ("$Sta/SSID={0}",),
        "password": ("$Sta/Password={0}",),
        "sta": ("$WiFi/Mode=STA", "$Radio/Mode=STA"),
        "off": ("$WiFi/Mode=Off", "$Radio/Mode=OFF"),
        "restart": ("$Bye", "[ESP444]RESTART"),
        "port": 23,
    },
    "numeric": {  # schede che mostrano solo $50…$54: come il firmware pubblico MKS (1 = si collega a una rete)
        "ssid": ("$53={0}",),
        "password": ("$54={0}",),
        "sta": ("[ESP110]STA", "$50=1"),
        "off": ("[ESP110]OFF", "$50=0"),
        "restart": ("[ESP444]RESTART",),
        "port": 8080,
    },
}
# Longer (firmware LGT): provato sul B1 di Ale il 12/11/2026: «[ESP110]» e «[ESP111]» rispondono, «[ESP110]STA» dà ok,
# «[ESP100]» non esiste (error:3): nome e password stanno in $53 e $54.
# 0.19.2, letto sullo stesso B1 il 13/11/2026 (nessun documento del produttore: la fonte sono le risposte di quella
# scheda): «[ESP110]STA» risponde ok ma NON accende il Wi-Fi. L'interruttore è «$50»: 0 = spento, 2 = rete di casa
# (gli altri valori non sono noti: non si scrivono). «$50=2» fa partire il collegamento subito, senza riavvio:
# «[MSG:Wifi Connecting...]», poi in 5 secondi «[MSG:Wifi Connected]» (l'indirizzo si chiede con «[ESP111]») oppure,
# dopo 40 secondi, «[MSG:Wifi Connection failed]»; l'«ok» arriva solo a collegamento finito. Al riavvio con «$50=2» la
# scheda riprova da sola; se fallisce scrive «[MSG:WiFi Off]» e rimette «$50=0». Con «$50=0» al riavvio scrive solo
# «[MSG:WiFi Off]»: è lì che la procedura manda «$50=2» (comando "radio").
LGT_ORDER = {"ssid": ("$53={0}", "[ESP100]{0}", "$Sta/SSID={0}"), "password": ("$54={0}", "[ESP101]{0}", "$Sta/Password={0}"),
             "sta": ("[ESP110]STA",), "off": ("[ESP110]OFF",), "radio": ("$50=2",)}
LGT_WAIT_K = 5.0 / 3.0  # le Longer provano a collegarsi per 40 secondi: l'attesa dei messaggi è 50 invece di 30


# Schede con l'interruttore «$wifi» (0.19.1). Provato il 12/11/2026 sul Mecpow di un utente, scheda «THMG LS WIFI
# V1.1», firmware V1.0.10 del 30/01/2026 (rapporti FLC-20261112-2153 e -2235): «[ESP100]», «[ESP101]» e «[ESP110]STA»
# rispondono ok e nome e password restano salvati, ma al riavvio la scheda riaccende la sua rete propria SENZA provare
# a collegarsi finché «$wifi» vale 0; con «$wifi=1» al riavvio entra nella rete di casa. Lì 0 = rete propria,
# 1 = rete di casa (il valore per «spento» non è noto: non si scrive). Non c'è un documento del produttore: la fonte
# sono le risposte di quella scheda. La scheda non scrive «Connected with…»: quando è in rete scrive
# «[MSG:TELNET Started 8080]» senza «Local access point…», e l'indirizzo si legge con «[ESP111]».
def has_wifi_switch(info_lines):
    """La scheda è di quelle con l'interruttore «$wifi»? (si capisce dal produttore scritto in $I)"""
    up = " ".join(str(l) for l in info_lines or ()).upper()
    return "THMG" in up


def parse_switch(lines):
    """Dalla risposta a «$wifi»: il numero, oppure None se la scheda non ha quella voce."""
    for l in lines or ():
        m = re.match(r"^\s*\$wifi\s*=\s*(\d+)\s*$", str(l), re.I)
        if m:
            return int(m.group(1))
    return None


def commands(family, what, lgt=False):
    """I comandi da provare, in ordine, per fare `what` ("ssid", "password", "sta", "off", "restart"; "radio" =
    accendere l'interruttore del Wi-Fi, che esiste solo sulle Longer: per le altre schede non c'è niente da mandare)."""
    table = CMDS.get(family) or {}
    if lgt and family == "esp" and what in LGT_ORDER:
        return LGT_ORDER[what]
    return table.get(what, ())


def default_port(family, info_text=""):
    up = str(info_text).upper()
    if "FLUIDNC" in up:
        return 23
    return (CMDS.get(family) or {}).get("port", 23)


def esp32_hints(info_lines, settings=None):
    """Ci sono indizi che la scheda sia una ESP32 (quindi con il Wi-Fi), anche se non accetta i comandi?"""
    up = " ".join(str(l) for l in info_lines or ()).upper()
    if any(t in up for t in ("ESP32", "FLUIDNC", "DLC32", "MKS", "WIFI", "LGT ", "LS_ESP", "THMG")):
        return True
    return bool(wifi_numbers(settings))


def is_lgt(info_lines):
    up = " ".join(str(l) for l in info_lines or ()).upper()
    return "LGT" in up or "LS_ESP32" in up


def is_mks_like(info_lines):
    up = " ".join(str(l) for l in info_lines or ()).upper()
    return any(t in up for t in ("LGT", "LS_ESP32", "MKS", "DLC32"))


_IP = re.compile(r"(?<![\d.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\d.])")


def find_ip(text):
    """Il primo indirizzo IPv4 valido nel testo, o None."""
    for m in _IP.finditer(str(text)):
        try:
            ipaddress.IPv4Address(m.group(1))
            return m.group(1)
        except ValueError:
            continue
    return None


def parse_mode(lines):
    """Dalle risposte a «[ESP110]» o «$Radio/Mode»: "STA", "AP", "OFF", "BT" o None."""
    for l in lines or ():
        m = re.search(r"(?:ESP110|Radio/Mode|WiFi/Mode)\s*=\s*([A-Za-z>]+)", str(l), re.I)
        v = (m.group(1) if m else str(l).strip()).upper()
        if v in ("STA", "AP", "BT"):
            return v
        if v in ("OFF", "NONE"):
            return "OFF"
        if v.startswith("STA>"):
            return "STA"
    return None


def board_state(mode, ip):
    """"off" spenta · "own" fa la sua rete (192.168.4.x) · "net" è in una rete · "idle" accesa ma non collegata."""
    if mode in ("OFF", "BT"):
        return "off"
    if ip and ip.startswith("192.168.4."):
        return "own"
    if mode == "AP":
        return "own"
    if ip and ip != "0.0.0.0":
        return "net"
    return "idle"


def parse_message(line):
    """Un messaggio della scheda sul Wi-Fi → (tipo, valore) oppure None.
    tipi: "connecting" (rete), "connected" (IP, vuoto se la scheda non lo dice), "failed" (rete), "own" (IP della rete
    propria), "services" (porta dei comandi), "nowifi" (Wi-Fi spento)."""
    s = str(line).strip()
    if s.startswith("[MSG:"):
        s = s[5:].rstrip("]").strip()
    low = s.lower()
    if low.startswith("connecting"):
        return "connecting", s[10:].strip(" :")
    if re.match(r"wi-?fi connecting", low):  # Longer (0.19.2): «Wifi Connecting...»
        return "connecting", ""
    if re.match(r"wi-?fi connected", low):  # Longer (0.19.2): «Wifi Connected», senza l'indirizzo
        return "connected", find_ip(s) or ""
    if low.startswith("client started"):  # Grbl_ESP32: sta per provare a entrare nella rete
        return "connecting", ""
    if low.startswith("telnet started"):  # i servizi di rete sono partiti: dice anche la porta dei comandi
        m = re.search(r"(\d{2,5})", s)
        return "services", m.group(1) if m else ""
    if low.startswith("connected with"):
        return "connected", find_ip(s) or ""
    if "ip=" in low and "status=connected" in low:  # FluidNC: Mode=STA:SSID=x:Status=Connected:IP=…
        return "connected", find_ip(s) or ""
    if low.startswith("cannot connect") or "connection failed" in low:  # «not connected» può voler dire «ci sto provando»
        return "failed", s.split(" to ", 1)[1].strip() if " to " in s else ""
    if "access point" in low and "started" in low or low.startswith("ap started"):
        return "own", find_ip(s) or OWN_NET_IP
    if low in ("no wifi", "wifi off", "no wifi."):
        return "nowifi", ""
    return None


def fails_to_off(line):
    """Il messaggio di collegamento fallito è quello delle Longer («Wifi Connection failed»)? Dopo quello la scheda
    non torna a una rete propria: lascia il Wi-Fi spento (0.19.2)."""
    s = str(line).strip()
    if s.startswith("[MSG:"):
        s = s[5:].rstrip("]").strip()
    return bool(re.match(r"wi-?fi connection failed", s.lower()))


# ============================================================================ controlli su rete e password
class Check:
    def __init__(self, code, block=False):
        self.code, self.block = code, block

    def __repr__(self):
        return f"Check({self.code!r}, block={self.block})"


def check_network(ssid, password, net=None, pc_ssid=None, family="esp", all_nets=()):
    """Avvisi e blocchi prima di scrivere. net: la rete scelta nell'elenco (Network) se c'è.
    -> [Check]; i codici: ssid_empty ssid_long pwd_short pwd_long enterprise semicolon (bloccano);
    band5 guest other_net wpa3 open special weak (avvisano)."""
    out = []
    ssid, password = str(ssid or ""), str(password or "")
    if not ssid.strip():
        out.append(Check("ssid_empty", True))
    if len(ssid.encode("utf-8")) > 32:
        out.append(Check("ssid_long", True))
    is_open = net is not None and net.security == "open"
    if net is not None and net.security == "enterprise":
        out.append(Check("enterprise", True))
    if password and len(password) < 8:
        out.append(Check("pwd_short", True))
    if not password and not is_open:
        out.append(Check("pwd_short", True))
    if len(password.encode("utf-8")) > 63:
        out.append(Check("pwd_long", True))
    if family == "numeric" and (set(ssid + password) & set(";(")):
        out.append(Check("semicolon", True))
    if net is not None:
        twin24 = any(n.ssid == net.ssid and n.band == "2.4" for n in all_nets)
        if net.band in ("5", "6") and not twin24:
            out.append(Check("band5"))
        if net.security == "wpa3":
            out.append(Check("wpa3"))
        if is_open:
            out.append(Check("open"))
        if net.signal is not None and net.signal < 35:
            out.append(Check("weak"))
    low = ssid.lower()
    if any(w in low for w in GUEST_WORDS):
        out.append(Check("guest"))
    if pc_ssid and ssid and ssid != pc_ssid:
        out.append(Check("other_net"))
    text = ssid + password
    if (set(text) & SPECIAL) or any(ord(c) > 126 for c in text) or ssid != ssid.strip() or password != password.strip() \
            or "  " in text:
        if not any(c.code == "semicolon" for c in out):
            out.append(Check("special"))
    return out


def likely_causes(ssid, password, net=None, all_nets=(), family="esp"):
    """Perché la scheda non è entrata nella rete: i codici delle cause, dalla più probabile."""
    codes = [c.code for c in check_network(ssid, password, net, None, family, all_nets)]
    out = [c for c in ("band5", "wpa3", "special", "weak", "guest") if c in codes]
    out.insert(1 if out[:1] == ["band5"] else 0, "wrong_password")
    if net is None:
        out.append("not_seen")  # la rete scritta a mano non è fra quelle che il PC vede
    return out


# ============================================================================ la rete del PC
class Network:
    def __init__(self, ssid, signal=None, band=None, security="wpa2", current=False):
        self.ssid, self.signal, self.band, self.security, self.current = ssid, signal, band, security, current

    def __repr__(self):
        return f"Network({self.ssid!r}, {self.signal}, {self.band}, {self.security}, cur={self.current})"


def _band(channel=None, mhz=None, text=""):
    m = re.search(r"(2[.,]4|5|6)\s*GHz", text, re.I)
    if m:
        return m.group(1).replace(",", ".")
    if mhz:
        return "2.4" if mhz < 3000 else "5" if mhz < 5925 else "6"
    if channel:
        return "2.4" if channel <= 14 else "5"
    return None


def _security(text):
    up = str(text).upper()
    if "ENTERPRISE" in up or "802.1X" in up or "AZIENDALE" in up or "EAP" in up:
        return "enterprise"
    if "WPA3" in up or "SAE" in up:
        return "wpa3" if "WPA2" not in up else "wpa2"
    if "OPEN" in up or "APERT" in up or up.strip() in ("", "--", "NONE", "OWE"):
        return "open"
    return "wpa2"


def parse_netsh_networks(text):
    """«netsh wlan show networks mode=bssid» → [Network]. Non dipende dalla lingua di Windows: conta la posizione
    delle righe (la seconda dopo «SSID n» è l'autenticazione) e i valori (xx% = segnale, numero = canale)."""
    nets, cur, lines_after, seen_signal = [], None, 0, False
    for raw in str(text).splitlines():
        line = raw.strip()
        m = re.match(r"^SSID\s+\d+\s*:\s?(.*)$", line)
        if m:
            cur = Network(m.group(1).strip(), None, None, "wpa2")
            nets.append(cur)
            lines_after, seen_signal = 0, False
            continue
        if cur is None or ":" not in line:
            continue
        lines_after += 1
        value = line.split(":", 1)[1].strip()
        if re.match(r"^BSSID\s+\d+", line):
            seen_signal = False
            continue
        if lines_after == 2:
            cur.security = _security(value)
        pct = re.match(r"^(\d{1,3})\s*%$", value)
        if pct:
            cur.signal = max(cur.signal or 0, int(pct.group(1)))
            seen_signal = True
            continue
        b = _band(text=value)
        if b and (cur.band is None or b == "2.4"):
            cur.band = b
        if seen_signal and re.match(r"^\d{1,3}$", value):
            b = _band(channel=int(value))
            if cur.band is None or b == "2.4":
                cur.band = b
            seen_signal = False
    return _merge([n for n in nets if n.ssid])


def parse_netsh_interface(text):
    """«netsh wlan show interfaces» → nome della rete a cui il PC è collegato, o None."""
    for raw in str(text).splitlines():
        m = re.match(r"^\s*SSID\s*:\s?(.*)$", raw)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def parse_nmcli(text):
    """«nmcli -t -f ACTIVE,SSID,SIGNAL,FREQ,SECURITY dev wifi list» → [Network]."""
    nets = []
    for raw in str(text).splitlines():
        parts = [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", raw.strip())]
        if len(parts) < 5 or not parts[1]:
            continue
        mhz = re.search(r"\d+", parts[3])
        sig = int(parts[2]) if parts[2].isdigit() else None
        nets.append(Network(parts[1], sig, _band(mhz=int(mhz.group()) if mhz else None), _security(parts[4]),
                            parts[0].lower() in ("yes", "sì", "si", "*")))
    return _merge(nets)


def _merge(nets):
    """Una riga per rete e banda (la stessa rete su 2,4 e su 5 GHz resta in due righe), con il segnale migliore."""
    best = {}
    for n in nets:
        k = (n.ssid, n.band)
        if k not in best or (n.signal or 0) > (best[k].signal or 0):
            n.current = n.current or (k in best and best[k].current)
            best[k] = n
        elif n.current:
            best[k].current = True
    return sorted(best.values(), key=lambda n: (not n.current, -(n.signal or 0), n.ssid.lower()))


def is_own_net(ssid):
    up = str(ssid or "").upper()
    return any(up.startswith(p.upper()) for p in OWN_NET_NAMES)


def _run(args, timeout=12, input_text=None):
    """Un comando del sistema. -> (codice, testo). Mai una finestra nera su Windows."""
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, input=input_text, **kw)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    out = r.stdout if isinstance(r.stdout, bytes) else (r.stdout or "").encode()
    for enc in ("utf-8", "cp850", "cp1252"):
        try:
            return r.returncode, out.decode(enc)
        except UnicodeDecodeError:
            continue
    return r.returncode, out.decode("utf-8", "replace")


def guard_path():
    from .profile import config_dir

    return os.path.join(config_dir(), "wifi-ritorno.json")


class System:
    """La rete del PC: reti visibili, rete attuale, cambio di rete. Windows (netsh) e Linux (nmcli).
    Nelle prove si sostituisce `run` con un finto."""

    def __init__(self, run=None, platform=None):
        self.run = run or _run
        self.platform = platform or sys.platform

    # ---- lettura
    def has_wifi(self):
        if self.platform == "win32":
            code, text = self.run(["netsh", "wlan", "show", "interfaces"])
            return code == 0 and re.search(r"^\s*\S.*:\s*\S", text, re.M) is not None and "GUID" in text.upper()
        code, text = self.run(["nmcli", "-t", "-f", "TYPE,STATE", "dev"])
        return code == 0 and any(l.startswith("wifi:") and "unavailable" not in l for l in text.splitlines())

    def current(self):
        """Il nome della rete Wi-Fi a cui il PC è collegato (None: col cavo di rete, o non collegato)."""
        if self.platform == "win32":
            code, text = self.run(["netsh", "wlan", "show", "interfaces"])
            return parse_netsh_interface(text) if code == 0 else None
        code, text = self.run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,FREQ,SECURITY", "dev", "wifi", "list", "--rescan", "no"])
        return next((n.ssid for n in parse_nmcli(text) if n.current), None) if code == 0 else None

    def scan(self):
        """[Network] visibili adesso; [] se il PC non ha il Wi-Fi o non lo dice."""
        if self.platform == "win32":
            code, text = self.run(["netsh", "wlan", "show", "networks", "mode=bssid"])
            nets = parse_netsh_networks(text) if code == 0 else []
            cur = self.current()
            for n in nets:
                n.current = n.ssid == cur
            return sorted(nets, key=lambda n: (not n.current, -(n.signal or 0), n.ssid.lower()))
        code, text = self.run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,FREQ,SECURITY", "dev", "wifi", "list"], 20)
        return parse_nmcli(text) if code == 0 else []

    def local_ip(self):
        """L'indirizzo del PC sulla rete locale (nessun pacchetto parte: serve solo a sapere quale scheda di rete)."""
        for target in ("192.168.4.1", "10.255.255.255"):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect((target, 9))
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                    return ip
            except OSError:
                pass
            finally:
                s.close()
        return None

    # ---- cambio di rete (strada senza cavo), con la guardia che riporta indietro
    def join(self, ssid, password):
        """Collega il PC alla rete `ssid` (quella del laser). -> True se il sistema ha accettato il comando.
        Prima scrive la guardia con la rete di adesso: `back()` (anche al prossimo avvio) riporta lì."""
        prev = self.current()
        self._guard_write({"back": prev, "temp": ssid, "t": int(time.time())})
        if self.platform == "win32":
            import tempfile
            from xml.sax.saxutils import escape

            auth = ("<authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX>"
                    f"</authEncryption><sharedKey><keyType>passPhrase</keyType><protected>false</protected>"
                    f"<keyMaterial>{escape(password)}</keyMaterial></sharedKey>") if password else \
                "<authentication>open</authentication><encryption>none</encryption><useOneX>false</useOneX></authEncryption>"
            xml = ('<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
                   f"<name>{escape(ssid)}</name><SSIDConfig><SSID><name>{escape(ssid)}</name></SSID></SSIDConfig>"
                   "<connectionType>ESS</connectionType><connectionMode>manual</connectionMode><MSM><security>"
                   f"<authEncryption>{auth}</security></MSM></WLANProfile>")
            fd, path = tempfile.mkstemp(suffix=".xml")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(xml)
                code, _ = self.run(["netsh", "wlan", "add", "profile", f"filename={path}", "user=current"])
            finally:
                try:
                    os.remove(path)  # dentro c'è la password della rete del laser: non resta sul disco
                except OSError:
                    pass
            if code != 0:
                return False
            code, _ = self.run(["netsh", "wlan", "connect", f"name={ssid}"])
            return code == 0
        args = ["nmcli", "dev", "wifi", "connect", ssid] + (["password", password] if password else [])
        code, _ = self.run(args, 40)
        return code == 0

    def back(self):
        """Riporta il PC alla rete di prima e cancella il profilo temporaneo. -> nome della rete a cui si torna
        (None se non c'era niente da fare). Si può chiamare più volte."""
        g = self._guard_read()
        if not g:
            return None
        temp, prev = g.get("temp"), g.get("back")
        if self.platform == "win32":
            if prev:
                self.run(["netsh", "wlan", "connect", f"name={prev}"])
            if temp and temp != prev:
                self.run(["netsh", "wlan", "delete", "profile", f"name={temp}"])
        else:
            if temp and temp != prev:
                self.run(["nmcli", "connection", "delete", "id", temp])
            if prev:
                self.run(["nmcli", "connection", "up", "id", prev], 40)
        self._guard_clear()
        return prev or ""

    def pending(self):
        """C'è un cambio di rete rimasto a metà (FreeLaserCut chiuso mentre il PC era sulla rete del laser)?"""
        return bool(self._guard_read())

    def _guard_write(self, data):
        try:
            with open(guard_path(), "w", encoding="utf-8") as fh:
                json.dump(data, fh)
        except OSError:
            pass

    def _guard_read(self):
        try:
            with open(guard_path(), encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else None
        except (OSError, ValueError):
            return None

    def _guard_clear(self):
        try:
            os.remove(guard_path())
        except OSError:
            pass


# ============================================================================ sottorete e «Trova il laser in rete»
def is_private(ip):
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return a.is_private and not a.is_loopback or (a.is_loopback and os.environ.get("FLC_PROVA_RETE") == "1")


def same_subnet(a, b):
    """Stessa rete locale (/24)? None se uno dei due indirizzi non si conosce."""
    try:
        return ipaddress.IPv4Address(a).packed[:3] == ipaddress.IPv4Address(b).packed[:3]
    except (ValueError, TypeError):
        return None


def subnet_hosts(ip):
    """Gli altri 253 indirizzi della stessa rete locale; [] se l'indirizzo non è di una rete locale."""
    if not ip or not is_private(ip):
        return []
    base = ip.rsplit(".", 1)[0]
    return [f"{base}.{i}" for i in range(1, 255) if f"{base}.{i}" != ip]


_GRBL_ANSWER = re.compile(rb"\[(?:VER|OPT)[^\r\n]*[\r\n]+(?:[^\r\n]*[\r\n]+)*?ok[\r\n]")


def probe(host, port, timeout=0.6, wait=2.5):
    """C'è un GRBL che risponde a quell'indirizzo? -> dict(host, port, ver, info) oppure None. Manda solo «$I»."""
    try:
        s = socket.create_connection((host, int(port)), timeout=timeout)
    except OSError:
        return None
    try:
        s.settimeout(0.3)
        s.sendall(b"\r\n$I\n")
        got, end, more = b"", time.time() + wait, True
        # 0.19.1: si legge finché non è arrivata la risposta a «$I» (righe fra quadre e poi «ok»). Prima ci si fermava
        # al primo «ok»: su una scheda vera è quello della riga vuota mandata per pulire, arriva per primo e da solo,
        # e la scheda non veniva riconosciuta («È in rete, ma non accetta i comandi» su un Mecpow che rispondeva)
        while not _GRBL_ANSWER.search(got) and len(got) < 4000:
            if time.time() >= end:
                # una risposta da GRBL è cominciata ma non è finita (rete lenta): le do ancora un po' di tempo, una volta
                if more and (b"[" in got or b"Grbl" in got):
                    more, end = False, time.time() + wait
                    continue
                break
            try:
                chunk = s.recv(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            got += chunk
    finally:
        try:
            s.close()
        except OSError:
            pass
    text = got.decode("utf-8", "replace")
    if not ("[VER" in text or "Grbl" in text or "FluidNC" in text or "[MSG:" in text):
        return None  # qualcosa risponde, ma non è un laser GRBL (una stampante, una telecamera…)
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith("[")]
    ver = next((l for l in lines if l.startswith("[VER")), "")
    return {"host": host, "port": int(port), "ver": ver, "info": lines}


def find_lasers(hosts, ports=None, max_s=10.0, workers=64, stop=None, skip=()):
    """Cerca i laser GRBL fra `hosts` (la rete locale del PC), sulle porte date. Connessioni brevi, in parallelo,
    al massimo `max_s` secondi. -> [dict(host, port, ver, info)] in ordine di indirizzo.
    skip (0.19.1): (indirizzo, porta) da non interrogare, cioè il collegamento attivo con il laser: la porta dei
    comandi accetta un collegamento solo e un secondo farebbe cadere quello buono."""
    hosts = [h for h in hosts if is_private(h)]  # mai fuori dalla rete locale
    ports = tuple(ports or PORTS)
    found, lock, t_end = [], threading.Lock(), time.time() + max_s
    skip = {(str(h), int(p)) for h, p in (s for s in skip if s)}
    jobs = [(h, p) for h in hosts for p in ports if (h, p) not in skip]
    it = iter(jobs)

    def work():
        while time.time() < t_end and not (stop is not None and stop.is_set()):
            with lock:
                job = next(it, None)
            if job is None:
                return
            r = probe(job[0], job[1])
            if r:
                with lock:
                    if not any(f["host"] == r["host"] for f in found):
                        found.append(r)

    threads = [threading.Thread(target=work, daemon=True) for _ in range(min(workers, max(1, len(jobs))))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.05, t_end - time.time() + 2.5))
    return sorted(found, key=lambda f: tuple(int(x) for x in f["host"].split(".")))


def pick_same(found, ver="", host=""):
    """Fra i laser trovati, quello «di prima»: stessa versione della scheda (se la si conosceva); senza un'identità
    nota si accetta solo se ce n'è uno solo. -> dict oppure None."""
    if ver:
        same = [f for f in found if f["ver"] == ver]
        return same[0] if len(same) == 1 else None
    return found[0] if len(found) == 1 else None
