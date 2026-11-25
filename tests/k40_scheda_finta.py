# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.22.6: scheda K40 (M2 Nano) finta per le prove del ponte. Riceve i pacchetti da 32 byte come la scheda vera (CRC
compreso), esegue i comandi con un tempo accorciato (`scala`) e tiene posizione, laser, lavoro, pausa e stati
(206 pronta, 238 occupata, 207 errore di controllo, 236 finito).

Come si teme per la scheda vera, un pacchetto mandato mentre dice «occupata» va perso (`persi`), anche «I».

Segna un «pericolo» quando:
- resta senza dati con il laser acceso (ha finito di eseguire, è nel lavoro, il laser è acceso e non è in pausa);
- riceve «D» fuori da un lavoro;
- la testa esce dal piano (0…300 × 0…200 mm).
Il lettore dei comandi è scritto da capo qui (non usa il codice del programma), come quello di test_v226_k40_driver.
"""
import re
import threading
import time

MIL = 1000.0 / 25.4


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


def velocita(codice):
    """mm/s di un codice di velocità: serve solo per il tempo che la scheda finta impiega."""
    from freelasercut.k40.codici import velocita_vera

    try:
        return min(max(velocita_vera("M2", codice), 0.5), 1000.0)
    except (ValueError, IndexError):
        return 10.0


class SchedaFinta:
    nome = "scheda finta"

    def __init__(self, scala=0.05, veloce_mm_s=150.0, piano=(300.0, 200.0), crc_ogni=0, crc_sempre=False,
                 occupata_per=0.0, mai_finita=False, cavo_cade_dopo=None, finestra=0.03, posti=3, crc_tardi=0):
        self.scala, self.veloce, self.piano = scala, veloce_mm_s, piano
        self.crc_ogni, self.crc_sempre = crc_ogni, crc_sempre
        self.occupata_per = occupata_per  # secondi (veri) di «occupata» dopo il primo pacchetto di un lavoro
        self.mai_finita = mai_finita
        self.cavo_cade_dopo = cavo_cade_dopo  # numero di pacchetti dopo cui il cavo «si stacca»
        self.finestra = finestra  # (non più usata: la memoria si conta a pacchetti)
        self.posti = posti  # pacchetti che la scheda tiene in memoria prima di dire «occupata»
        self.crc_tardi = crc_tardi  # dopo un pacchetto rovinato dice «occupata» per questo numero di letture, poi 207
        self._crc_attesa = 0
        self._pend = []  # per ogni pacchetto ricevuto: quando avrà finito di eseguirlo
        self.lock = threading.RLock()
        self.x = self.y = 0
        self.vx = self.vy = 1
        self.lavoro = False
        self.laser = False
        self.pausa = False
        self.t_pausa = 0.0
        self.v = 10.0
        self.fino = 0.0  # quando finisce di eseguire quello che ha ricevuto (tempo vero)
        self.finito = False
        self.occupata_fino = 0.0
        self._testo = ""
        self._mode = None  # "veloce" dopo I, "lavoro" dentro S1E…FNSE
        self._dx = self._dy = 0
        self._crc_err = False
        self.pacchetti = 0
        self.persi = 0  # pacchetti arrivati mentre la scheda era «occupata»: non li ha presi
        self.max_passi = 0  # il pacchetto con più strada dentro un lavoro (passi)
        self._passi_pkt = 0
        self.pericoli = []
        self.accesi = []  # tratti bruciati (x0, y0, x1, y1) in passi
        self.comandi = []  # parole lette, in ordine (per le prove)
        self.d_ricevute = 0
        self.interrotti = 0  # 0.22.7: «I» arrivati con la testa in moto
        # 0.23.2: modo raster («V…G…»): a ogni inversione del verso orizzontale la scheda scende di `passo` passi
        # (come l'emulatore di MeerK40t). Nel lavoro normale un'inversione sopra i 15 mm/s è un colpo (`colpi`)
        self._passo_codice = 0
        self.passo = 0
        self.colpi = []
        self.inversioni_raster = 0
        self.lavori_raster = 0
        self.accesi_raster = []  # i tratti bruciati dentro un lavoro raster
        self.accesi_v = []
        self.aperta = False
        self._guardia = threading.Thread(target=self._guarda, daemon=True)
        self._vivo = True
        self._guardia.start()

    # ---------------------------------------------------------------- collegamento (come WinDriver / LibUsb)
    def apri(self):
        self.aperta = True
        return self

    def inizia(self):
        return b""

    def versione(self):
        return b"\x00\x04"

    def chiudi(self):
        self.aperta = False
        self._vivo = False

    def scrivi(self, p32):
        with self.lock:
            if self.cavo_cade_dopo is not None and self.pacchetti >= self.cavo_cade_dopo:
                raise OSError("cavo staccato")
            self.pacchetti += 1
            if self._occupata(time.monotonic()):
                self.persi += 1
                return b""
            if len(p32) != 32 or p32[0] != 0:
                self.pericoli.append(f"pacchetto malformato {p32!r}")
                return b""
            corpo, crc = p32[1:31], p32[31]
            if self.crc_sempre or (self.crc_ogni and self.pacchetti % self.crc_ogni == 0) or crc8(corpo) != crc:
                self._crc_err = True
                self._crc_attesa = self.crc_tardi
                return b""
            if corpo.strip(b"F") != b"PN":  # pausa e ripresa non cambiano «finito»
                self.finito = False
            if corpo[:1] == b"I" and self._testo.strip("F"):
                self._testo = ""  # «I» interrompe anche un comando rimasto a metà
            self._testo += corpo.decode("ascii")
            self._passi_pkt = 0
            self._leggi()
            self.max_passi = max(self.max_passi, self._passi_pkt)
            if corpo.strip(b"F") != b"PN":  # la pausa non occupa memoria
                self._pend.append(self.fino)
        return b""

    def _occupata(self, now):
        """In pausa la scheda prende la ripresa (MeerK40t aspetta «pronta» anche per quella: se in pausa restasse
        «occupata» non riprenderebbe mai). Da confermare sulla K40 di Evo."""
        if self.pausa:
            return False
        self._pend = [e for e in self._pend if e > now]
        # 0.22.8: «occupata» solo finché ha ancora da eseguire: una scheda che ha finito tutto prende i pacchetti
        # (prima la scheda finta restava «occupata» a vuoto e, con i pacchetti pieni, finiva i dati con il laser acceso)
        return (now < self.occupata_fino and now < self.fino) or len(self._pend) >= self.posti

    def stato(self):
        with self.lock:
            now = time.monotonic()
            if self._crc_err and self._crc_attesa > 0:
                self._crc_attesa -= 1
                s = 238
            elif self._crc_err:
                self._crc_err = False
                s = 207
            elif self.pausa:
                s = 206
            elif self._occupata(now):
                s = 238
            elif self.finito and not self.mai_finita and self._resto(now) <= 0:
                s = 236
            else:
                s = 206
            return bytes([0, s, 0, 0, 0, 0]), {}

    # ---------------------------------------------------------------- tempo
    def _resto(self, now):
        if self.pausa:
            return self.fino - self.t_pausa
        return self.fino - now

    def _occupa(self, secondi):
        now = time.monotonic()
        base = max(self.fino, self.t_pausa if self.pausa else now)
        self.fino = base + secondi * self.scala

    def _guarda(self):
        while self._vivo:
            time.sleep(0.01)
            with self.lock:
                now = time.monotonic()
                if self.lavoro and self.laser and not self.pausa and now > self.fino + 0.25:
                    if not self.pericoli or not self.pericoli[-1].startswith("senza dati"):
                        self.pericoli.append(f"senza dati con il laser acceso a {self.x},{self.y}")

    # ---------------------------------------------------------------- lettura dei comandi
    def _muovi(self, dx, dy, n, v):
        x0, y0 = self.x, self.y
        self.x += dx * n
        self.y += dy * n
        if not (-1 <= self.x <= self.piano[0] * MIL + 1 and -1 <= self.y <= self.piano[1] * MIL + 1):
            self.pericoli.append(f"fuori dal piano: {self.x},{self.y}")
        if self.lavoro:
            self._passi_pkt += n
        if self.laser and self.lavoro:
            self.accesi.append((x0, y0, self.x, self.y))
            if self.passo:
                self.accesi_raster.append((x0, y0, self.x, self.y))
            self.accesi_v.append(round(self.v, 1))  # 0.23.2: velocità di ogni tratto bruciato
        self._occupa(((dx * n) ** 2 + (dy * n) ** 2) ** 0.5 / MIL / max(v, 0.1))

    @staticmethod
    def _distanza(t, i):
        """-> (passi, indice dopo) oppure (None, i) se il testo finisce a metà."""
        n = 0
        while i < len(t) and t[i] == "z":
            n += 255
            i += 1
        if i >= len(t):
            return None, i
        c = t[i]
        if "a" <= c <= "y":
            return n + ord(c) - 96, i + 1
        if c == "|":
            if i + 1 >= len(t):
                return None, i
            return n + ord(t[i + 1]) - 96 + 25, i + 2
        if c.isdigit():
            if i + 3 > len(t):
                return None, i
            if not t[i:i + 3].isdigit():
                return n, i
            return n + int(t[i:i + 3]), i + 3
        return (n if n else 0), i

    def _leggi(self):
        t = self._testo
        i = 0
        while i < len(t):
            c = t[i]
            resto = t[i:]
            if c == "F":
                if resto.startswith("FNSE"):
                    self.comandi.append("FNSE")
                    self.lavoro = self.laser = False
                    self.passo = 0
                    self._mode = None
                    self.finito = True
                    i += 4
                    continue
                if len(resto) < 4 and "FNSE".startswith(resto):
                    break  # forse un FNSE a cavallo di due pacchetti
                if self.lavoro:
                    # 0.22.8 (rapporto 03D4): sulla scheda vera una «F» di riempimento dentro il lavoro lo chiude:
                    # quello che arriva dopo è fuori dal lavoro. Qui si fa lo stesso, e si segna
                    self.pericoli.append("«F» di riempimento dentro il lavoro: lavoro chiuso a metà")
                    self.comandi.append("F")
                    self.lavoro = self.laser = False
                    self._mode = None
                    self.finito = True
                i += 1  # riempimento
                continue
            if c == "P":
                if resto.startswith("PN"):
                    self.comandi.append("PN")
                    now = time.monotonic()
                    if self.pausa:
                        self.fino += now - self.t_pausa
                        self._pend = [e + (now - self.t_pausa) for e in self._pend]
                        self.pausa = False
                    else:
                        self.pausa, self.t_pausa = True, now
                    i += 2
                    continue
                if len(resto) < 2:
                    break
                self.pericoli.append(f"P inattesa: {resto[:6]}")
                i += 1
                continue
            if c == "I":
                if resto.startswith("IPP"):
                    self.comandi.append("IPP")
                    d = (self.x ** 2 + self.y ** 2) ** 0.5
                    self.x = self.y = 0
                    self.lavoro = self.laser = False
                    self._occupa(d / MIL / self.veloce + 0.2)
                    i += 3
                    continue
                if len(resto) < 3 and "IPP".startswith(resto):
                    break
                self.comandi.append("I")
                # 0.22.7: «I» mentre la testa è ancora in moto la ferma a metà (la posizione vera non è più quella
                # che il programma crede): giusto solo per uno stop voluto. Le prove contano quante volte succede
                if time.monotonic() < self.fino - 0.005 and not self.pausa:
                    self.interrotti += 1
                # «I»: cancella quello che c'è in memoria e ferma; poi può seguire uno spostamento veloce
                self.lavoro = self.laser = False
                self.fino = min(self.fino, time.monotonic())
                self.pausa = False
                self._mode = "veloce"
                self._dx = self._dy = 0
                i += 1
                continue
            if c == "C" or (c == "V" and not self.lavoro):
                m = re.match(r"C?V\d{7}(?:\d{9})?C?(?=N)|V\d{7}G\d{3}", resto)
                if not m:
                    if "N" not in resto:
                        break
                    self.pericoli.append(f"codice illeggibile {resto[:20]}")
                    i += 1
                    continue
                self.v = velocita(m.group(0))
                g = re.search(r"G(\d{3})$", m.group(0))
                self._passo_codice = int(g.group(1)) if g and m.group(0).startswith("V") else 0
                self.comandi.append(m.group(0))
                i += len(m.group(0))
                continue
            if c == "N":
                i += 1
                continue
            if c == "S":
                if len(resto) < 3:
                    break
                if resto.startswith("S1E"):
                    self.lavoro, self._mode = True, "lavoro"
                    self.passo = self._passo_codice
                    self.lavori_raster += 1 if self.passo else 0
                    self.comandi.append("S1E")
                    if self.occupata_per:
                        self.occupata_fino = time.monotonic() + self.occupata_per
                elif resto.startswith("S1P"):
                    self.comandi.append("S1P")
                    if self._mode == "veloce":
                        dx, dy = self._dx, self._dy
                        self._muovi(1 if dx > 0 else -1, 0, abs(dx), self.veloce) if dx else None
                        self._muovi(0, 1 if dy > 0 else -1, abs(dy), self.veloce) if dy else None
                        self._occupa(0.05)
                    self._mode = None
                else:
                    self.pericoli.append(f"S inattesa {resto[:4]}")
                i += 3
                continue
            if c in "DU":
                if c == "D":
                    self.d_ricevute += 1
                    if not self.lavoro:
                        self.pericoli.append("D fuori da un lavoro")
                self.laser = c == "D" and self.lavoro
                self.comandi.append(c)
                i += 1
                continue
            if c in "BTLRM":
                n, j = self._distanza(t, i + 1)
                if n is None:
                    break
                if c in "BT" and self.lavoro and (1 if c == "B" else -1) != self.vx:
                    if self.passo:  # modo raster: la scheda scende di una riga, a laser spento
                        if self.laser:
                            self.pericoli.append(f"laser acceso nell'inversione raster a {self.x},{self.y}")
                        acceso, self.laser = self.laser, False
                        self.inversioni_raster += 1
                        self._muovi(0, self.vy, self.passo, self.v)
                        self.laser = acceso
                    elif self.v > 15.0:
                        self.colpi.append((self.x, self.y, round(self.v, 1)))
                if c == "B":
                    self.vx = 1
                elif c == "T":
                    self.vx = -1
                elif c == "R":
                    self.vy = 1
                elif c == "L":
                    self.vy = -1
                if n:
                    if self._mode == "veloce":
                        if c in "BT":
                            self._dx += self.vx * n
                        elif c in "LR":
                            self._dy += self.vy * n
                    elif self.lavoro:
                        if c == "M":
                            self._muovi(self.vx, self.vy, n, self.v)
                        elif c in "BT":
                            self._muovi(self.vx, 0, n, self.v)
                        else:
                            self._muovi(0, self.vy, n, self.v)
                    elif c != "M" or True:
                        pass
                i = j
                continue
            self.pericoli.append(f"lettera sconosciuta {c!r}")
            i += 1
        self._testo = t[i:]
