# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Dal movimento ai comandi della scheda K40 (Lihuiyu, M2 Nano e sorelle).

Coordinate della scheda: in passi (1 passo = 1/1000 di pollice), origine nell'angolo di casa, X verso destra,
Y verso il davanti (in giù sul piano visto dall'alto).

Il risultato è una lista di pezzi, da mandare in ordine:
- ("dati", bytes): comandi per la scheda, in pacchetti da 30 byte;
- ("attendi_fine",): aspettare che la scheda dica «finito» (dopo la fine di un lavoro, «FNSE»);
- ("attendi_ferma",): aspettare che la testa sia ferma (dopo uno spostamento veloce o il ritorno a casa).
Un nuovo spostamento veloce comincia con «I», che cancella quello che la scheda ha ancora in memoria: per questo prima
si aspetta sempre.

Lettere (fonti in RICONOSCIMENTI-TECNICI.md):
- versi: B destra, T sinistra, R avanti, L indietro; M diagonale nei versi dichiarati;
- D laser acceso, U spento (solo dentro un lavoro);
- lavoro: codice di velocità + «N» + versi + «S1E» … «FNSE»;
- spostamento veloce: «I» + versi e distanze + «S1P»; casa: «IPP».
"""

MIL_PER_MM = 1000.0 / 25.4

DATI, ATTENDI_FINE, ATTENDI_FERMA = "dati", "attendi_fine", "attendi_ferma"


def distanza(mil):
    """Distanza in passi -> lettere della scheda («z» = 255, «a»…«y» = 1…25, «|a»… = 26…51, poi tre cifre)."""
    mil = int(mil)
    if mil < 0:
        raise ValueError("distanza negativa")
    out = "z" * (mil // 255)
    r = mil % 255
    if r == 0:
        return out
    if r < 26:
        return out + chr(96 + r)
    if r < 52:
        return out + "|" + chr(96 + r - 25)
    return out + "%03d" % r


def passi_retta(dx, dy):
    """Una retta da (0, 0) a (dx, dy) in passi -> tratti (sx, sy, n): n passi uguali, ognuno dritto (uno dei due
    a zero) o in diagonale. La testa non si allontana mai più di mezzo passo dalla retta vera."""
    ax, ay = abs(dx), abs(dy)
    sx = 1 if dx > 0 else -1 if dx < 0 else 0
    sy = 1 if dy > 0 else -1 if dy < 0 else 0
    out = []

    def add(px, py):
        if out and out[-1][0] == px and out[-1][1] == py:
            out[-1][2] += 1
        else:
            out.append([px, py, 1])

    if ax >= ay:
        err = 2 * ay - ax
        for _ in range(ax):
            if err > 0:
                add(sx, sy)
                err += 2 * (ay - ax)
            else:
                add(sx, 0)
                err += 2 * ay
    else:
        err = 2 * ax - ay
        for _ in range(ay):
            if err > 0:
                add(sx, sy)
                err += 2 * (ax - ay)
            else:
                add(0, sy)
                err += 2 * ax
    return [tuple(t) for t in out]


class Scrittore:
    """Prepara i pezzi per la scheda. Le posizioni sono in passi, assolute."""

    def __init__(self, scheda="M2", correggi=True, senza_giri=True):
        from .codici import SCHEDE

        if scheda not in SCHEDE:
            raise ValueError(f"scheda sconosciuta: {scheda}")
        self.scheda, self.correggi, self.senza_giri = scheda, correggi, senza_giri
        self.pezzi = []
        self._buf = bytearray()
        self.x = self.y = 0
        self.in_lavoro = False
        self.v = None
        self.laser = False
        self._vx = self._vy = 0  # versi dichiarati nel lavoro (+1/−1)
        # 0.22.6 (ponte): fin dove i comandi del lavoro in corso si possono già mandare senza lasciare il laser acceso
        # a metà (dopo «U», dopo l'entrata nel lavoro, dopo un tratto spento) e dove è la testa lì
        self._sicuro = 0
        self._sicuro_xy = (0, 0)
        self._durata = 0.0  # secondi previsti del lavoro in corso
        self.durate = []  # secondi previsti di ogni lavoro chiuso, in ordine

    def _segna_sicuro(self):
        if not self.laser:
            self._sicuro = len(self._buf)
            self._sicuro_xy = (self.x, self.y)

    # ------------------------------------------------------------ uscita
    def _scrivi(self, b):
        self._buf += b if isinstance(b, (bytes, bytearray)) else b.encode("ascii")

    def _chiudi_pezzo(self, attesa=None):
        if self._buf:
            self.pezzi.append((DATI, bytes(self._buf)))
            self._buf = bytearray()
        self._sicuro = 0
        if attesa:
            self.pezzi.append((attesa,))

    def fine(self):
        """Chiude tutto: -> lista dei pezzi."""
        self.fine_lavoro()
        self._chiudi_pezzo()
        return self.pezzi

    # ------------------------------------------------------------ lavori
    def _versi(self, vx, vy):
        return (b"T" if vx < 0 else b"B") + (b"L" if vy < 0 else b"R")

    def inizia_lavoro(self, v, vx=1, vy=1):
        """Entra nel lavoro alla velocità v (mm/s). Se si è già dentro a un'altra velocità, chiude e riapre."""
        from .codici import codice

        if self.in_lavoro and self.v == v:
            return
        self.fine_lavoro()
        self._scrivi(codice(self.scheda, v, correggi=self.correggi, senza_giri=self.senza_giri))
        self._vx, self._vy = (1 if vx >= 0 else -1), (1 if vy >= 0 else -1)
        self._scrivi(b"N" + self._versi(self._vx, self._vy) + b"S1E")
        self.in_lavoro, self.v, self.laser = True, v, False
        self._durata = 0.0
        self._segna_sicuro()

    def fine_lavoro(self):
        if not self.in_lavoro:
            return
        self._scrivi(b"FNSE")
        self.in_lavoro, self.v, self.laser = False, None, False
        self.durate.append(self._durata)
        self._chiudi_pezzo(ATTENDI_FINE)

    def _laser(self, on):
        if on != self.laser:
            self._scrivi(b"D" if on else b"U")
            self.laser = on
            self._segna_sicuro()

    def vai(self, x, y, v, laser=False):
        """Va a (x, y) in linea retta alla velocità v (mm/s), con il laser acceso o spento."""
        x, y = int(x), int(y)
        dx, dy = x - self.x, y - self.y
        if dx == 0 and dy == 0:
            return
        self.inizia_lavoro(v, dx, dy)
        self._laser(bool(laser))
        for sx, sy, n in passi_retta(dx, dy):
            if sx and sy:
                if sx != self._vx:
                    self._scrivi(b"T" if sx < 0 else b"B")
                    self._vx = sx
                if sy != self._vy:
                    self._scrivi(b"L" if sy < 0 else b"R")
                    self._vy = sy
                self._scrivi(b"M" + distanza(n).encode())
            elif sx:
                self._scrivi((b"T" if sx < 0 else b"B") + distanza(n).encode())
                self._vx = sx
            else:
                self._scrivi((b"L" if sy < 0 else b"R") + distanza(n).encode())
                self._vy = sy
        self.x, self.y = x, y
        self._durata += (dx * dx + dy * dy) ** 0.5 / MIL_PER_MM / max(float(v), 0.1)
        self._segna_sicuro()

    # ------------------------------------------------------------ fuori dal lavoro
    def veloce(self, x, y):
        """Spostamento veloce (laser spento, velocità della scheda) fino a (x, y)."""
        x, y = int(x), int(y)
        if (x, y) == (self.x, self.y):
            return
        self.fine_lavoro()
        self._chiudi_pezzo()
        dx, dy = x - self.x, y - self.y
        self._scrivi(b"I")
        if dx:
            self._scrivi((b"B" if dx > 0 else b"T") + distanza(abs(dx)).encode())
        if dy:
            self._scrivi((b"R" if dy > 0 else b"L") + distanza(abs(dy)).encode())
        self._scrivi(b"S1P")
        self._chiudi_pezzo(ATTENDI_FERMA)
        self.x, self.y = x, y

    def casa(self):
        """Ritorno a casa (finecorsa)."""
        self.fine_lavoro()
        self._chiudi_pezzo()
        self._scrivi(b"IPP")
        self._chiudi_pezzo(ATTENDI_FERMA)
        self.x = self.y = 0


# ---------------------------------------------------------------- pacchetti
def crc8(dati):
    c = 0
    for byte in dati:
        for _ in range(8):
            misto = (c ^ byte) & 1
            c >>= 1
            if misto:
                c ^= 0x8C
            byte >>= 1
    return c


def pacchetti(dati):
    """Comandi -> pacchetti da 32 byte (0x00, 30 byte di comandi, CRC). Solo l'ultimo si riempie di «F», che a lavoro
    chiuso non fa niente."""
    out = []
    for i in range(0, max(len(dati), 1), 30):
        corpo = bytes(dati[i:i + 30])
        corpo += b"F" * (30 - len(corpo))
        out.append(b"\x00" + corpo + bytes([crc8(corpo)]))
    return out


PASSI_PER_PACCHETTO = 765  # 3 «z»: circa 2 cm di movimento del lavoro per pacchetto (vedi pacchetti_a_parole)


def _passi(parola):
    """Passi di un comando di direzione («Bzz|c» = 255 + 255 + 28); 0 per gli altri comandi."""
    if parola[:1] not in (b"B", b"T", b"L", b"R", b"M"):
        return 0
    k = 1
    while parola[k:k + 1] == b"z":
        k += 1
    n = (k - 1) * 255
    r = parola[k:]
    if not r:
        return n
    if r[:1] == b"|":
        return n + r[1] - 96 + 25
    if r[:1].isdigit():
        return n + int(r[:3])
    return n + r[0] - 96


def _parole(dati):
    """Comandi -> pezzi che non si devono dividere (uno spostamento veloce intero, l'entrata nel lavoro, una direzione
    con la sua distanza, D, U, FNSE…). Dentro un lavoro una distanza lunga diventa più comandi uguali di seguito
    («Bzzzzz» = «Bzzz» + «Bzz»: stessa direzione, stessa strada), così nessun comando supera un pacchetto."""
    d = bytes(dati)
    n, i, out = len(d), 0, []
    while i < n:
        c = d[i:i + 1]
        if d.startswith(b"IPP", i):
            j = i + 3
        elif c == b"I":
            k = d.find(b"S1P", i)
            j = k + 3 if k >= 0 else i + 1
        elif c in (b"C", b"V"):
            k = d.find(b"S1E", i)
            j = k + 3 if k >= 0 else n
        elif d.startswith(b"FNSE", i):
            j = i + 4
        elif c in (b"B", b"T", b"L", b"R", b"M"):
            k = i + 1
            while k < n and d[k:k + 1] == b"z":  # le «z» in testa valgono 255 passi l'una
                k += 1
            j = k
            if j < n:
                e = d[j:j + 1]
                if b"a" <= e <= b"y":
                    j += 1
                elif e == b"|":
                    j += 2
                elif e.isdigit():
                    j += 3
            j = min(j, n)
            nz, resto = k - i - 1, d[k:j]
            while nz > 3:  # a pezzi di 3 «z», ripetendo la lettera
                out.append(c + b"zzz")
                nz -= 3
            out.append(c + b"z" * nz + resto)
            i = j
            continue
        else:
            j = i + 1
        out.append(d[i:min(j, n)])
        i = min(j, n)
    return out


def pacchetti_a_parole(dati, max_passi=PASSI_PER_PACCHETTO):
    """0.22.6 (ponte): come pacchetti(), ma ogni pacchetto finisce alla fine di un comando (riempito con «F», che non fa
    niente) e porta al massimo circa max_passi di movimento del lavoro. Così fra un pacchetto e l'altro si può infilare
    la pausa («PN») senza spezzare un comando, e la scheda non ha mai in memoria più di qualche centimetro di lavoro:
    pausa e arresto non devono aspettare la fine di una retta lunga.
    -> [(pacchetto, sicuro_dopo)]: sicuro_dopo è False solo dentro uno spostamento veloce più lungo di un pacchetto
    («I…S1P», che non si può dividere)."""
    out, cur, passi = [], b"", 0

    def chiudi(corpo, sicuro):
        corpo = corpo + b"F" * (30 - len(corpo))
        out.append((b"\x00" + corpo + bytes([crc8(corpo)]), sicuro))

    for w in _parole(dati):
        pw = _passi(w)
        if cur and (len(cur) + len(w) > 30 or (pw and passi + pw > max_passi)):
            chiudi(cur, True)
            cur, passi = b"", 0
        while len(w) > 30:
            chiudi(w[:30], False)
            w = w[30:]
        cur += w
        passi += pw
    if cur or not out:
        chiudi(cur, True)
    return out
