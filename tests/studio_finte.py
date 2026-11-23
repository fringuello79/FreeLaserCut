# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Schede finte per le prove di «Studia la macchina» (0.22.3): una M2 Nano e una Ruida che rispondono come quelle vere
(secondo lo studio), contano tutto quello che ricevono e possono sbagliare apposta.

Le schede finte decodificano da sole quello che arriva, con regole scritte qui e non prese dal programma: se il
programma manda un comando non permesso (accensione del laser, taglio, potenza…) lo segnano in `pericoli`."""
import re
import socket
import threading
import time


class Orologio:
    """Tempo finto: attesa() lo fa avanzare, così le prove lunghe durano millisecondi."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def attesa(self, dt):
        self.t += max(dt, 0.001)


def _crc_tabella(data):
    """CRC-8 «Maxim» (1-Wire) con la tabella: un'altra strada rispetto al programma, per controllarlo."""
    tab = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x8C if c & 1 else c >> 1
        tab.append(c)
    c = 0
    for b in data:
        c = tab[c ^ b]
    return c


def _mil(text):
    """Distanza scritta con le lettere della scheda -> millesimi di pollice."""
    n = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "z":
            n += 255
            i += 1
        elif ch == "|":
            n += 25 + ord(text[i + 1]) - 96
            i += 2
        elif ch.isdigit():
            n += int(text[i:i + 3])
            i += 3
        else:
            n += ord(ch) - 96
            i += 1
    return n


class LihuiyuFinta:
    """Collegamento finto verso una M2 Nano. fattore: velocità vera / velocità chiesta; extra: secondi di rincorsa
    per ogni spostamento."""

    nome = "scheda finta"
    BASI_M = (60416.0, 60416.0, 59904.0, 59392.0)

    def __init__(self, orologio, fattore=0.92, extra=0.35, crc_sbagliati=0, muta=False, sempre_occupata=False,
                 non_si_apre=False):
        self.clock = orologio
        self.fattore, self.extra = fattore, extra
        self.crc_sbagliati = crc_sbagliati
        self.muta, self.sempre_occupata, self.non_si_apre = muta, sempre_occupata, non_si_apre
        self.flusso = ""
        self.pacchetti = []
        self.crc_ko = 0
        self.pericoli = []
        self.comandi = []
        self.occupata_fino = 0.0
        self.ultimo = 206
        self.aperta = False
        self.x_mil = 0

    def apri(self):
        if self.non_si_apre:
            raise OSError("occupata da un altro programma")
        self.aperta = True
        return self

    def chiudi(self):
        self.aperta = False

    def inizia(self):
        return b""

    def versione(self):
        return b"\x30\x00"

    def scrivi(self, p32):
        assert self.aperta
        self.pacchetti.append(bytes(p32))
        if len(p32) != 32 or p32[0] != 0:
            self.pericoli.append(("pacchetto storto", p32))
            return b""
        corpo, crc = p32[1:31], p32[31]
        if self.crc_sbagliati > 0 or _crc_tabella(corpo) != crc:
            self.crc_sbagliati = max(0, self.crc_sbagliati - 1)
            self.crc_ko += 1
            self.ultimo = 207
            return b""
        self.ultimo = 206
        testo = corpo.decode("latin-1")
        if "D" in testo or "W" in testo or "AT" in testo:
            self.pericoli.append(("laser", testo))
        self.flusso += testo
        self._esegui()
        return b""

    def _esegui(self):
        while True:
            s = self.flusso.lstrip("F")
            m = re.match(r"IPP", s)
            if m:
                self.comandi.append(("casa",))
                self.x_mil = 0
                self.occupata_fino = self.clock() + 1.2
                self.flusso = s[m.end():]
                continue
            m = re.match(r"I([LRBT][a-z|0-9]+)+S1P", s)
            if m:
                self.comandi.append(("veloce", m.group(0)))
                self.occupata_fino = self.clock() + 0.5
                self.flusso = s[m.end():]
                continue
            m = re.match(r"ICV(\d{3})(\d{3})(\d)(\d{3})?(\d{6})?C?NBRS1E([BT])([a-z|0-9]+?)FNSE-", s)
            if m:
                val = int(m.group(1)) * 256 + int(m.group(2))
                g = int(m.group(3))
                t_ms = (val - self.BASI_M[g - 1]) / -12120.0  # ms per millesimo di pollice
                v = 25.4 / t_ms
                mil = _mil(m.group(7))
                mm = mil * 25.4 / 1000.0
                self.x_mil += mil if m.group(6) == "B" else -mil
                self.comandi.append(("velocita", round(v, 3), round(mm, 3), m.group(6)))
                self.occupata_fino = self.clock() + mm / (v * self.fattore) + self.extra
                self.flusso = s[m.end():]
                continue
            if re.fullmatch(r"I", s.rstrip("F")):
                self.comandi.append(("ferma",))
                self.occupata_fino = 0
                self.flusso = ""
            break
        self.flusso = self.flusso if self.flusso.strip("F") else ""

    def stato(self):
        if self.muta:
            return b"", {"lettura": ""}
        if self.ultimo == 207:
            s = 207
        elif self.sempre_occupata or self.clock() < self.occupata_fino:
            s = 238
        elif self.comandi and self.comandi[-1][0] in ("velocita", "casa") and not self.flusso:
            s = 236
        else:
            s = 206
        data = bytes([255, s, 0, 0, 0, 0])
        return data, {"lettura": data.hex(" ")}


# ---------------------------------------------------------------- Ruida
def _sw(b, k):
    hi, lo = b & 0x80, b & 1
    b = (b & 0x7E) | (lo << 7) | (hi >> 7)
    return ((b ^ k) + 1) & 0xFF


def _usw(b, k):
    b = ((b - 1) & 0xFF) ^ k
    hi, lo = b & 0x80, b & 1
    return (b & 0x7E) | (lo << 7) | (hi >> 7)


def _n35(v):
    v &= (1 << 35) - 1
    return bytes((v >> (7 * (4 - i))) & 0x7F for i in range(5))


def _from(data):
    v = 0
    for b in data:
        v = (v << 7) | b
    if v >> 34:
        v -= 1 << 35
    return v


PERICOLOSI = {0xA8, 0xA9, 0xAA, 0xAB, 0xC6, 0xC9, 0xCA, 0xD7, 0xE8}  # tagli, potenze, velocità, livelli, fine, file


class RuidaFinta:
    """Memoria e movimento di una Ruida. chiave: quella della scheda. Su `rete=True` ascolta UDP sul 127.0.0.1."""

    def __init__(self, chiave=0x88, rete=True, muta=False, x=120.0, y=80.0, piano=(600.0, 400.0), mm_s=200.0):
        self.chiave = chiave
        self.muta = muta
        self.mem = {0x057E: 0x65106510, 0x0026: int(piano[0] * 1000), 0x0036: int(piano[1] * 1000), 0x0400: 0,
                    0x0405: 3, 0x0421: int(x * 1000), 0x0431: int(y * 1000), 0x0441: 0, 0x0451: 0}
        for a in range(0x0000, 0x0010):
            self.mem.setdefault(a, a * 7)
        self.mm_s = mm_s
        self.moto = None  # (t0, x0, y0, x1, y1)
        self.ricevuti = []
        self.pericoli = []
        self.estranei = []
        self.risposte = 0
        self.sock = None
        if rete:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("127.0.0.1", 0))
            self.sock.settimeout(0.05)
            self.porta = self.sock.getsockname()[1]
            self._run = True
            self.th = threading.Thread(target=self._loop, daemon=True)
            self.th.start()

    def chiudi(self):
        if self.sock is not None:
            self._run = False
            self.th.join(1)
            self.sock.close()
            self.sock = None

    def _pos(self):
        if self.moto is None:
            return self.mem[0x0421], self.mem[0x0431]
        t0, x0, y0, x1, y1 = self.moto
        d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        f = 1.0 if d == 0 else min(1.0, (time.monotonic() - t0) * self.mm_s * 1000 / d)
        x, y = round(x0 + (x1 - x0) * f), round(y0 + (y1 - y0) * f)
        if f >= 1.0:
            self.moto = None
            self.mem[0x0421], self.mem[0x0431] = x, y
        return x, y

    def gestisci(self, wire, somma):
        """-> elenco di risposte (già rimescolate)."""
        if somma:
            if len(wire) < 3 or ((wire[0] << 8) | wire[1]) != (sum(wire[2:]) & 0xFFFF):
                self.estranei.append(("somma", wire))
                return [bytes([_sw(0xCD, self.chiave)])]
            wire = wire[2:]
        c = bytes(_usw(b, self.chiave) for b in wire)
        self.ricevuti.append(c)
        if c[0] in PERICOLOSI or c[:2] in (b"\xD8\x00", b"\xDA\x01") or (c[:2] == b"\xD9\x10" and c[2:3] != b"\x02"):
            self.pericoli.append(c)
        if self.muta:
            return []
        out = []
        ack = bytes([_sw(0xCC, self.chiave)])
        if c == b"\xCE":
            out.append(ack)
        elif len(c) == 4 and c[:2] == b"\xDA\x00":
            a = (c[2] << 8) | c[3]
            if a in (0x0421, 0x0431):
                x, y = self._pos()
                self.mem[0x0421 if a == 0x0421 else 0x0431] = x if a == 0x0421 else y
                if self.moto is not None:
                    pass
            if somma:
                out.append(ack)
            if a in self.mem:
                rep = b"\xDA\x01" + c[2:4] + _n35(self.mem[a]) + _n35(0)
                out.append(bytes(_sw(b, self.chiave) for b in rep))
        elif len(c) == 13 and c[:3] == b"\xD9\x10\x02":
            x0, y0 = self._pos()
            self.moto = (time.monotonic(), x0, y0, _from(c[3:8]), _from(c[8:13]))
            if somma:
                out.append(ack)
        elif c == b"\xD8\x01":
            self.moto = None
            if somma:
                out.append(ack)
        elif somma and len(c) == 1:
            self.estranei.append(("byte", c))  # un saluto con la chiave sbagliata: la scheda lo ignora
        return out

    def _loop(self):
        while self._run:
            try:
                data, addr = self.sock.recvfrom(2048)
            except (socket.timeout, OSError):
                continue
            for r in self.gestisci(data, True):
                self.risposte += 1
                self.sock.sendto(r, addr)


class SerialeFinta:
    """Porta seriale finta davanti a una RuidaFinta (USB: niente somma, niente conferme)."""

    def __init__(self, scheda):
        self.scheda = scheda
        self.buf = b""
        self.chiusa = False

    def write(self, data):
        self.buf += b"".join(self.scheda.gestisci(bytes(data), False))

    def read(self, n):
        out, self.buf = self.buf[:n], self.buf[n:]
        if not out:
            time.sleep(0.01)
        return out

    def close(self):
        self.chiusa = True
