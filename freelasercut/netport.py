# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Collegamento al laser via Wi-Fi o cavo di rete.

Molte schede recenti (FluidNC, grblHAL, ESP3D su ESP32) accettano il G-code anche da un collegamento TCP
«telnet» sulla rete di casa, di solito sulla porta 23, con lo stesso protocollo GRBL del cavo USB: righe con
«ok»/«error», «?» per lo stato e i comandi immediati (0x18, 0x21, 0x7E). Qui c'è un oggetto che si usa come
la porta seriale (write / readline / close), così il resto di FreeLaserCut non cambia.

Le porte di rete si scrivono «tcp://indirizzo:porta», per esempio «tcp://192.168.1.50:23».
"""
import re
import select
import socket
import threading
import time

DEFAULT_PORT = 23
PREFIX = "tcp://"
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-.]*[A-Za-z0-9])?$")
IAC = 0xFF


def parse_address(text):
    """«192.168.1.50», «192.168.1.50:23», «tcp://laser.local:8888» → ("192.168.1.50", 23); testo non valido → None."""
    t = str(text or "").strip()
    if t.lower().startswith(PREFIX):
        t = t[len(PREFIX):]
    t = t.strip().strip("/")
    if not t or " " in t:
        return None
    host, port = t, DEFAULT_PORT
    if t.count(":") == 1:
        host, p = t.split(":")
        if not p.isdigit():
            return None
        port = int(p)
    if not (0 < port < 65536) or not _HOST_RE.match(host):
        return None
    return host, port


def make_port(host, port=DEFAULT_PORT):
    return f"{PREFIX}{host}:{int(port)}"


def is_net(port):
    return isinstance(port, str) and port.lower().startswith(PREFIX)


def label(port):
    a = parse_address(port)
    return f"Wi-Fi  {a[0]}:{a[1]}" if a else str(port)


WRITE_TIMEOUT = 2.0  # una rete Wi-Fi lenta può fermare una scrittura per un istante; oltre, il collegamento è perso
# (non di più: finché una scrittura aspetta, anche Pausa e Stop aspettano dietro di lei)


class NetSerial:
    """Collegamento TCP che si comporta come serial.Serial (timeout di lettura 0,1 s)."""

    def __init__(self, host, port=DEFAULT_PORT, connect_timeout=4.0, timeout=0.1):
        self.host, self.port = host, int(port)
        self.timeout = timeout
        self.sock = socket.create_connection((host, self.port), timeout=connect_timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # i comandi immediati partono subito
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
        self.sock.settimeout(WRITE_TIMEOUT)  # vale per le scritture; la lettura aspetta con select (vedi readline)
        self._buf = bytearray()
        self._lock = threading.Lock()
        self.is_open = True

    @classmethod
    def from_port(cls, port, **kw):
        a = parse_address(port)
        if not a:
            raise ValueError(f"indirizzo non valido: {port}")
        return cls(a[0], a[1], **kw)

    def _strip_telnet(self, data):
        """Toglie le negoziazioni telnet (IAC …) che alcune schede mandano all'inizio."""
        if IAC not in data:
            return data
        out = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b == IAC and i + 1 < len(data):
                cmd = data[i + 1]
                if cmd == IAC:
                    out.append(IAC)
                    i += 2
                elif cmd in (251, 252, 253, 254):  # WILL WONT DO DONT + opzione
                    i += 3
                else:
                    i += 2
                continue
            out.append(b)
            i += 1
        return bytes(out)

    def write(self, data):
        if not self.is_open:
            raise OSError("collegamento chiuso")
        with self._lock:
            self.sock.sendall(bytes(data))
        return len(data)

    def readline(self):
        end = time.time() + self.timeout
        while True:
            i = self._buf.find(b"\n")
            if i >= 0:
                line = bytes(self._buf[:i + 1])
                del self._buf[:i + 1]
                return line
            if not self.is_open:
                raise OSError("collegamento chiuso")
            left = end - time.time()
            if left <= 0:
                return b""
            try:
                # attesa con select: il timeout del socket resta quello lungo, così una scrittura del lavoro (sendall,
                # dall'altro filo) non scade per colpa della lettura che aspetta 0,1 s
                ready, _, _ = select.select([self.sock], [], [], max(0.01, left))
                if not ready:
                    return b""
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return b""
            except OSError:
                self.is_open = False
                raise
            if not chunk:
                self.is_open = False
                raise OSError("la scheda ha chiuso il collegamento")
            self._buf += self._strip_telnet(chunk)

    def reset_input_buffer(self):
        self._buf.clear()

    def close(self):
        self.is_open = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


# ------------------------------------------------------------------ indirizzi ricordati (QSettings)
def saved(qs):
    v = qs.value("net_ports", []) if qs is not None else []
    if isinstance(v, str):
        v = [v] if v else []
    return [p for p in (v or []) if is_net(p) and parse_address(p)]


def remember(qs, port):
    lst = [p for p in saved(qs) if p != port]
    qs.setValue("net_ports", [port] + lst[:7])


def forget(qs, port):
    qs.setValue("net_ports", [p for p in saved(qs) if p != port])
