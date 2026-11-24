# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Studia la macchina: schede Ruida (RDC644x e sorelle), riscritto da capo.

Ogni byte si «rimescola» prima di partire: si scambiano il bit più alto e il più basso, si fa lo XOR con una chiave che
dipende dalla scheda (0x88 quasi sempre; 0x11 e 0x38 per alcune) e si aggiunge 1. In rete (UDP) la scheda ascolta
sulla porta 50200 e risponde sulla 40200; ogni pacchetto comincia con due byte, la somma dei byte rimescolati.
La scheda conferma con 0xCC (errore 0xCD). Sull'USB (chip FTDI, porta seriale a 115200) non c'è la conferma né la
somma: per sapere se risponde si legge la memoria.
I numeri viaggiano a gruppi di 7 bit: il bit alto di ogni byte è libero, perché segna l'inizio di un comando.

Lo studio manda solo: il saluto (0xCE), la lettura della memoria (DA 00 + indirizzo), lo spostamento rapido senza luce
(D9 10 02 + X + Y) e lo stop (D8 01). Nessun comando di taglio, di potenza, di avvio lavoro o di scrittura in memoria:
controlla() rifiuta tutto il resto prima che parta.

Attenzione scoperta studiando: lo stesso pacchetto mandato con la chiave sbagliata, per la scheda, diventa un altro
comando. Il saluto (un byte) con una chiave sbagliata diventa 0x57, 0x66 o 0xFF: niente di pericoloso. La lettura
della memoria invece può diventare un comando di taglio (con le chiavi 0x11 e 0x38 scambiate, 0x00 diventa 0xA8):
per questo la memoria si legge solo con la chiave che ha risposto al saluto (o, sull'USB, con 0x88).
"""
import socket
import time

from . import SicurezzaError, esadecimale, impronta

CHIAVI = (0x88, 0x11, 0x38)
PORTA_SCHEDA, PORTA_RISPOSTE = 50200, 40200
ACK, ERR, NAK, ENQ = 0xCC, 0xCD, 0xCF, 0xCE
OPZIONE_SENZA_LUCE = 0x02

# indirizzi noti (lettura): nome -> indirizzo
MEMORIA = {
    "scheda": 0x057E,
    "piano_x": 0x0026,
    "piano_y": 0x0036,
    "stato": 0x0400,
    "lavori_salvati": 0x0405,
    "x": 0x0421,
    "y": 0x0431,
    "z": 0x0441,
    "u": 0x0451,
}
SCHEDE_NOTE = {0x65106510: "RDC6442S"}
# lettura estesa: zone dove stanno le impostazioni della macchina, lo stato e i dati della scheda
ZONE_ESTESE = ((0x0000, 0x0080), (0x0400, 0x0460), (0x0500, 0x0580))

# 0.22.6: il numero di un'impostazione (quello delle fonti) e i due byte che viaggiano sul cavo non sono la stessa cosa.
# Sul cavo ogni byte porta 7 bit: numero = (primo << 7) | secondo. Fino a 0x7F coincidono (piano_x 0x26 = 00 26), poi no:
# il modello della scheda è l'impostazione 0x2FE e sul cavo è 05 7E; lo stato è la 0x200 (04 00). MEMORIA e ZONE_ESTESE
# qui sopra sono scritti «come sul cavo»; le zone coprono le impostazioni 0x000-0x07F, 0x200-0x25F e 0x280-0x2FF.
def sul_cavo(numero):
    """Numero dell'impostazione -> indirizzo come va sul cavo (due byte da 7 bit)."""
    if not 0 <= numero < 0x4000:
        raise ValueError("impostazione non valida")
    return ((numero >> 7) << 8) | (numero & 0x7F)


def numero_impostazione(cavo):
    """Indirizzo come sul cavo -> numero dell'impostazione."""
    hi, lo = cavo >> 8, cavo & 0xFF
    if not (0 <= hi < 0x80 and lo < 0x80):
        raise ValueError("indirizzo non valido")
    return (hi << 7) | lo


# Impostazioni conosciute dalle fonti che stanno FUORI dalle zone: velocità e accelerazioni di lavoro, ritorno a casa,
# ritardi, contatori. R4 le legge una per una (sola lettura), così il primo rapporto di una macchina le porta tutte.
IMPOSTAZIONI_NOTE = (
    0x080, 0x090, 0x0A0, 0x0B0, 0x0C0, 0x0C1, 0x0C2, 0x0C3, 0x0C4, 0x0C5, 0x0C6, 0x0C7, 0x0C8, 0x0C9, 0x0CA, 0x0CB,
    0x0CC, 0x0CD, 0x0CE, 0x0CF, 0x0D0, 0x0D8, 0x0D9, 0x0DA, 0x0E7, 0x100, 0x101, 0x102, 0x103, 0x104, 0x105, 0x107,
    0x108, 0x109, 0x10A, 0x10B, 0x10C, 0x10D, 0x10E, 0x10F, 0x115, 0x116, 0x117, 0x119, 0x11A, 0x11B, 0x11C, 0x11F,
    0x121, 0x122, 0x124, 0x125, 0x126, 0x128, 0x129, 0x12A, 0x12B, 0x12C, 0x12D, 0x12E, 0x131, 0x132, 0x134, 0x135,
    0x137, 0x138, 0x139, 0x13B, 0x13D, 0x13F, 0x140, 0x141, 0x142, 0x143, 0x144, 0x145, 0x146, 0x147, 0x148, 0x149,
    0x14A, 0x14B, 0x14C, 0x14D, 0x14E, 0x14F, 0x150, 0x151, 0x152, 0x153, 0x154, 0x155, 0x156, 0x157, 0x158, 0x159,
    0x15A, 0x15B, 0x15C, 0x15D, 0x15E, 0x15F, 0x160, 0x161, 0x162, 0x163, 0x164, 0x165, 0x166, 0x169, 0x16A, 0x16B,
    0x16C, 0x16D, 0x16E, 0x170, 0x171, 0x172, 0x173, 0x174, 0x175, 0x176, 0x177, 0x178, 0x179, 0x17A, 0x17B, 0x17C,
    0x17D, 0x17E, 0x17F, 0x180, 0x188, 0x189, 0x18A, 0x18B, 0x18C, 0x18D, 0x18F, 0x190, 0x191, 0x192, 0x193, 0x194,
    0x195, 0x196, 0x197, 0x198, 0x199, 0x19A, 0x19B, 0x19C, 0x19D, 0x19E, 0x19F, 0x1A0, 0x1A1, 0x1A2, 0x1A3, 0x1A4,
    0x1A5, 0x1A6, 0x1A7, 0x1AC, 0x1AD, 0x1AE, 0x1AF, 0x1B1, 0x1B2, 0x260, 0x313, 0x31C, 0x320, 0x321, 0x33B, 0x340,
    0x591, 0x5C0,
)


# ---------------------------------------------------------------- rimescolamento e numeri
def rimescola(b, chiave=0x88):
    alto, basso = b & 0x80, b & 0x01
    b = (b & 0x7E) | (basso << 7) | (alto >> 7)
    return ((b ^ chiave) + 1) & 0xFF


def districa(b, chiave=0x88):
    b = ((b - 1) & 0xFF) ^ chiave
    alto, basso = b & 0x80, b & 0x01
    return (b & 0x7E) | (basso << 7) | (alto >> 7)


def rimescola_tutto(data, chiave):
    return bytes(rimescola(b, chiave) for b in data)


def districa_tutto(data, chiave):
    return bytes(districa(b, chiave) for b in data)


def busta_udp(comandi, chiave=0x88):
    dati = rimescola_tutto(comandi, chiave)
    s = sum(dati) & 0xFFFF
    return bytes([s >> 8, s & 0xFF]) + dati


def numero(v, n=5):
    v = int(v)
    if v < 0:
        v &= (1 << (7 * n)) - 1
    return bytes((v >> (7 * (n - 1 - i))) & 0x7F for i in range(n))


def da_numero(data, segno=False):
    v = 0
    for b in data:
        v = (v << 7) | (b & 0x7F)
    bits = 7 * len(data)
    if segno and v >> (bits - 1):
        v -= 1 << bits
    return v


# ---------------------------------------------------------------- i soli comandi dello studio
def cmd_saluto():
    return bytes([ENQ])


def cmd_leggi(indirizzo):
    """Lettura di un indirizzo: i due byte dell'indirizzo, come ogni parametro, stanno sotto 0x80."""
    hi, lo = indirizzo >> 8, indirizzo & 0xFF
    if not (0 <= hi < 0x80 and lo < 0x80):
        raise ValueError("indirizzo non valido")
    return bytes([0xDA, 0x00, hi, lo])


def cmd_rapido(x_mm, y_mm):
    """Spostamento rapido assoluto, senza luce e senza toccare l'origine."""
    return bytes([0xD9, 0x10, OPZIONE_SENZA_LUCE]) + numero(round(x_mm * 1000)) + numero(round(y_mm * 1000))


def cmd_stop():
    return b"\xD8\x01"


def controlla(cmd):
    """Solo i quattro comandi dello studio, nella forma giusta. Se no SicurezzaError, e non parte niente."""
    c = bytes(cmd)
    if c in (bytes([ENQ]), b"\xD8\x01"):
        return c
    if len(c) == 4 and c[:2] == b"\xDA\x00" and max(c[2:]) < 0x80:
        return c
    if len(c) == 13 and c[:3] == bytes([0xD9, 0x10, OPZIONE_SENZA_LUCE]) and max(c[3:]) < 0x80:
        return c
    raise SicurezzaError(f"comando non permesso: {esadecimale(c[:16])}")


def leggi_risposta(data, indirizzo=None):
    """Risposta alla lettura (già districata): DA 01 indirizzo(2) valore(5) [valore(5)] -> dict o None."""
    d = bytes(data)
    i = d.find(b"\xDA\x01")
    if i < 0 or len(d) < i + 9:
        return None
    d = d[i:]
    addr = (d[2] << 8) | d[3]
    if indirizzo is not None and addr != indirizzo:
        return None
    out = {"indirizzo": "%04X" % addr, "grezzo": esadecimale(d[4:14]), "valore": da_numero(d[4:9]),
           "con_segno": da_numero(d[4:9], True)}
    if len(d) >= 14:
        out["valore2"] = da_numero(d[9:14])
    return out


# ---------------------------------------------------------------- collegamenti
class Rete:
    """UDP: si ascolta sulla 40200 e si manda dalla stessa porta (la scheda risponde lì)."""

    nome = "rete"
    somma = True

    def __init__(self, ip, porta=PORTA_SCHEDA, ascolto=PORTA_RISPOSTE, attesa=0.4):
        self.ip, self.porta, self.ascolto, self.attesa = ip, porta, ascolto, attesa
        self.sock = None

    def apri(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(("", self.ascolto))
        except OSError as ex:
            s.close()
            raise OSError(f"la porta {self.ascolto} del computer è occupata: chiudi l'altro programma del laser "
                          f"({ex.__class__.__name__})") from None
        s.settimeout(self.attesa)
        self.sock = s
        return self

    def chiudi(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def manda(self, wire):
        self.sock.sendto(wire, (self.ip, self.porta))

    def ricevi(self, attesa=None):
        """-> elenco dei pacchetti arrivati entro l'attesa (vuoto se niente)."""
        out = []
        self.sock.settimeout(attesa or self.attesa)
        try:
            while True:
                data, _addr = self.sock.recvfrom(2048)
                out.append(data)
                self.sock.settimeout(0.05)
        except (socket.timeout, OSError):
            pass
        return out


class Usb:
    """Porta seriale del chip FTDI (0403:6001) a 115200."""

    nome = "usb"
    somma = False

    def __init__(self, porta=None, apri_seriale=None, attesa=0.4):
        self.porta = porta
        self._apri_seriale = apri_seriale
        self.attesa = attesa
        self.ser = None

    @staticmethod
    def porte_ftdi():
        try:
            from serial.tools import list_ports

            return [p.device for p in list_ports.comports() if (p.vid, p.pid) == (0x0403, 0x6001)]
        except Exception:  # noqa: BLE001
            return []

    def apri(self):
        if self._apri_seriale is not None:
            self.ser = self._apri_seriale()
            return self
        import serial

        porta = self.porta or (self.porte_ftdi() or [None])[0]
        if porta is None:
            raise OSError("nessuna porta USB con il chip FTDI della scheda")
        self.ser = serial.Serial(porta, 115200, timeout=self.attesa, rtscts=True, dsrdtr=True)
        return self

    def chiudi(self):
        if self.ser is not None:
            try:
                self.ser.close()
            finally:
                self.ser = None

    def manda(self, wire):
        self.ser.write(wire)

    def ricevi(self, attesa=None):
        t_end = time.monotonic() + (attesa or self.attesa)
        buf = b""
        while time.monotonic() < t_end:
            chunk = self.ser.read(64)
            if chunk:
                buf += chunk
                t_end = max(t_end, time.monotonic() + 0.05)
            elif buf:
                break
        return [buf] if buf else []


class Scheda:
    """Tutto quello che parte verso la scheda passa da qui: controlla(), rimescolamento con la chiave, collegamento."""

    def __init__(self, link, chiave=0x88, traccia=None):
        self.link = link
        self.chiave = chiave
        self.traccia = traccia
        self.mandati = []

    def apri(self):
        self.link.apri()
        return self

    def chiudi(self):
        self.link.chiudi()

    def manda(self, cmd, chiave=None):
        chiave = self.chiave if chiave is None else chiave
        c = controlla(cmd)
        wire = busta_udp(c, chiave) if self.link.somma else rimescola_tutto(c, chiave)
        self.mandati.append((c, chiave))
        if self.traccia:
            self.traccia(c, chiave, wire)
        self.link.manda(wire)

    def scambia(self, cmd, chiave=None, attesa=None):
        """Manda e raccoglie le risposte: -> [(grezzo, districato con la chiave)]."""
        chiave = self.chiave if chiave is None else chiave
        self.manda(cmd, chiave)
        return [(r, districa_tutto(r, chiave)) for r in self.link.ricevi(attesa)]

    def leggi(self, indirizzo):
        risp = self.scambia(cmd_leggi(indirizzo))
        for grezzo, chiaro in risp:
            got = leggi_risposta(chiaro, indirizzo)
            if got is not None:
                return got, risp
        if self.link.somma and any(chiaro[:1] == bytes([ACK]) for _g, chiaro in risp):
            more = [(r, districa_tutto(r, self.chiave)) for r in self.link.ricevi()]  # i dati dopo la conferma
            for grezzo, chiaro in more:
                got = leggi_risposta(chiaro, indirizzo)
                if got is not None:
                    return got, risp + more
            risp = risp + more
        return None, risp


# ---------------------------------------------------------------- le prove
PROVE = ("R1", "R2", "R3", "R4")
MUOVE = {"R3"}
PASSO_PROVA_MM = 10.0


def _descrivi(risp):
    return [{"grezzo": esadecimale(g[:32]), "districato": esadecimale(c[:32])} for g, c in risp[:6]]


def prova_r1(diario, link, chiavi=None):
    """Saluto con ogni chiave; quella che risponde con la conferma è la chiave della scheda."""
    sch = Scheda(link)
    try:
        sch.apri()
    except Exception as ex:  # noqa: BLE001
        diario.risultato("R1", "non collegata", collegamento=link.nome, errore=str(ex))
        return None
    try:
        prove, trovata = [], None
        for k in (chiavi or CHIAVI):
            risp = sch.scambia(cmd_saluto(), k)
            ack = any(c[:1] == bytes([ACK]) for _g, c in risp)
            prove.append({"chiave": "%02X" % k, "risposte": _descrivi(risp), "conferma": ack})
            if ack:
                trovata = k
                break
        diario.risultato("R1", "ok" if trovata is not None else "nessuna conferma", collegamento=link.nome,
                         chiave=None if trovata is None else "%02X" % trovata, tentativi=prove)
        return trovata
    finally:
        sch.chiudi()


def prova_r2(diario, link, chiave=None):
    """Lettura della memoria nota (solo lettura). La chiave: quella del saluto; se manca, 0x88."""
    if chiave is None:
        chiave = prova_r1(diario, link) if link.somma else None
        chiave = 0x88 if chiave is None else chiave
    sch = Scheda(link, chiave)
    try:
        sch.apri()
    except Exception as ex:  # noqa: BLE001
        diario.risultato("R2", "non collegata", collegamento=link.nome, errore=str(ex))
        return None
    try:
        valori, grezzi = {}, {}
        for nome, addr in MEMORIA.items():
            got, risp = sch.leggi(addr)
            valori[nome] = got
            if got is None:
                grezzi[nome] = _descrivi(risp)
        sc = valori.get("scheda")
        info = {}
        if sc:
            info["modello"] = SCHEDE_NOTE.get(sc["valore"], "non in elenco")
            info["impronta"] = impronta(sc["valore"], (valori.get("piano_x") or {}).get("valore"), (valori.get("piano_y") or {}).get("valore"))
        for k in ("piano_x", "piano_y"):
            if valori.get(k):
                info[k + "_mm"] = round(valori[k]["valore"] / 1000.0, 3)
        for k in ("x", "y", "z", "u"):
            if valori.get(k):
                info["pos_" + k + "_mm"] = round(valori[k]["con_segno"] / 1000.0, 3)
        letti = sum(1 for v in valori.values() if v)
        diario.risultato("R2", "ok" if letti else "nessuna risposta", collegamento=link.nome, chiave="%02X" % chiave,
                         letti=letti, valori=valori, senza_risposta=grezzi, **info)
        return valori
    finally:
        sch.chiudi()


def prova_r3(diario, link, chiave=None, ferma=None, attesa=time.sleep):
    """Spostamento rapido di 10 mm in X e ritorno, senza luce; posizione letta prima, dopo e al ritorno."""
    chiave = 0x88 if chiave is None else chiave
    sch = Scheda(link, chiave)
    try:
        sch.apri()
    except Exception as ex:  # noqa: BLE001
        diario.risultato("R3", "non collegata", collegamento=link.nome, errore=str(ex))
        return None
    try:
        def pos():
            x, _r = sch.leggi(MEMORIA["x"])
            y, _r = sch.leggi(MEMORIA["y"])
            return (None if x is None else x["con_segno"] / 1000.0, None if y is None else y["con_segno"] / 1000.0)

        bx, _r = sch.leggi(MEMORIA["piano_x"])
        p0 = pos()
        if None in p0:
            diario.risultato("R3", "posizione non letta: non mi muovo", collegamento=link.nome, chiave="%02X" % chiave)
            return None
        lim = bx["valore"] / 1000.0 if bx and bx["valore"] > 0 else None
        dx = PASSO_PROVA_MM if lim is None or p0[0] + PASSO_PROVA_MM <= lim else -PASSO_PROVA_MM
        if p0[0] + dx < 0:
            diario.risultato("R3", "nessuno spazio per 10 mm: non mi muovo", posizione=p0, piano_x=lim)
            return None
        passi = []
        for target in ((p0[0] + dx, p0[1]), p0):
            if ferma is not None and ferma():
                sch.manda(cmd_stop())
                raise InterruptedError
            t0 = time.monotonic()
            risp = sch.scambia(cmd_rapido(*target))
            fine, seq = None, []
            while time.monotonic() - t0 < 15:
                if ferma is not None and ferma():
                    sch.manda(cmd_stop())
                    raise InterruptedError
                p = pos()
                seq.append((round(time.monotonic() - t0, 2),) + p)
                if p[0] is not None and abs(p[0] - target[0]) < 0.05:
                    fine = time.monotonic() - t0
                    break
                attesa(0.1)
            passi.append({"verso": "andata" if target != p0 else "ritorno", "dx_mm": dx,
                          "risposte": _descrivi(risp), "arrivata_in_s": None if fine is None else round(fine, 3),
                          "posizioni": seq[:30]})
        ok = all(p["arrivata_in_s"] is not None for p in passi)
        diario.risultato("R3", "ok" if ok else "non arrivata", collegamento=link.nome, chiave="%02X" % chiave,
                         partenza=p0, passi=passi)
        return passi
    finally:
        sch.chiudi()


def prova_r4(diario, link, chiave=None, ferma=None, avanzamento=None):
    """Lettura estesa (sola lettura) delle zone di memoria della macchina e, dalla 0.22.6, delle impostazioni note
    fuori dalle zone. Nel diario gli indirizzi restano scritti come sul cavo (vedi numero_impostazione)."""
    chiave = 0x88 if chiave is None else chiave
    sch = Scheda(link, chiave)
    try:
        sch.apri()
    except Exception as ex:  # noqa: BLE001
        diario.risultato("R4", "non collegata", collegamento=link.nome, errore=str(ex))
        return None
    try:
        letti, vuoti = {}, 0
        tutti = [a for lo, hi in ZONE_ESTESE for a in range(lo, hi)]
        zona = set(tutti)
        fuori = [a for a in map(sul_cavo, IMPOSTAZIONI_NOTE) if a not in zona]  # 0.22.6
        tutti += fuori
        for i, addr in enumerate(tutti):
            if ferma is not None and ferma():
                break
            got, _r = sch.leggi(addr)
            if got is None:
                vuoti += 1
            else:
                letti["%04X" % addr] = [got["valore"], got.get("valore2")]
            if avanzamento:
                avanzamento(i + 1, len(tutti))
        diario.risultato("R4", "ok" if letti else "nessuna risposta", collegamento=link.nome, chiave="%02X" % chiave,
                         letti=letti, senza_risposta=vuoti, totale=len(tutti), fuori_zona=len(fuori))
        return letti
    finally:
        sch.chiudi()


def ferma_subito(link, chiave=0x88):
    try:
        sch = Scheda(link, chiave).apri()
        sch.manda(cmd_stop())
        sch.chiudi()
        return True
    except Exception:  # noqa: BLE001
        return False
