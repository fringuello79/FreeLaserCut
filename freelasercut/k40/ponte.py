# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.22.6, funzione in prova: la K40 (scheda M2 Nano) come se fosse una scheda GRBL.

K40Serial ha gli stessi metodi della porta seriale (write, readline, reset_input_buffer, flush, close, is_open):
GrblController le parla GRBL e non sa che dietro c'è una K40. Il ponte traduce (k40.da_gcode.Traduttore) e manda i
pacchetti alla scheda con un filo solo («alimentatore»).

Regole di sicurezza (vedi freeburn/ordine-lavoro-0.22.6.md § 2.2):
- mai un tratto acceso lasciato a metà: alla scheda arrivano solo comandi fino a un punto con il laser spento; un tratto
  acceso parte quando è arrivata la riga che lo spegne. Se il programma tace per 1 s con un tratto acceso in sospeso,
  il ponte lo chiude da solo (U + FNSE);
- il laser si accende solo dentro un movimento del lavoro (G1 con S > 0 e M3/M4): mai da fermo (G4, M3 senza movimento,
  puntino);
- reset (Ctrl+X), chiusura della porta, filo che muore o errore del cavo: prima di tutto il comando «I» (ferma),
  mandato quando la scheda prende pacchetti e ripetuto finché non è confermato; dopo uno stop niente di quello che era
  in preparazione parte più;
- la scheda non ha mai in memoria più di qualche centimetro di lavoro (pacchetti corti): pausa e arresto non aspettano
  la fine di una retta lunga.

Che cosa capisce (GRBL ridotto): vedi COMANDI qui sotto.
Limite noto: un blocco del PC a metà di un tratto acceso già partito non si può escludere (vale per ogni programma che
guida questa scheda).
"""
import collections
import re
import threading
import time

from .da_gcode import ErroreRiga, Traduttore
from .scrittore import (ATTENDI_FERMA, ATTENDI_FINE, DATI, MIL_PER_MM, Scrittore, durata_veloce, pacchetti,
                        pacchetti_a_parole)

OK, OCCUPATA, ERRORE_CRC, FINITO, FINITO_M3 = 206, 238, 207, 236, 204
SALUTO = "\r\nGrbl 1.1f ['$' for help]\r\n[MSG:'$H'|'$X' to unlock]\r\n"
VERSIONE = "[VER:1.1f.K40:]\r\n[OPT:V,15,128]\r\n"
PIANO = (300.0, 200.0)  # mm, dall'angolo di casa (dietro a sinistra): X verso destra, Y verso il davanti
FRENO = 2000  # byte pronti e non ancora mandati oltre i quali l'«ok» aspetta
TETTO_SOSPESO = 4 * 1024 * 1024
# 0.22.7: una freccia è UNO spostamento veloce (fluido, come la casa). Solo «Continuo» (freccia fino al bordo, fermata
# con 0x85) va a pezzi, così al rilascio la testa si ferma entro un pezzo. Con la 0.22.6 erano pezzetti da 2 mm
# ognuno con la sua fermata: frecce, contorno e joystick andavano a scatti sulla K40 di Evo.
PEZZETTO_FRECCE = 10.0  # mm, solo per «Continuo»
BORDO_CONTINUO = 1.0  # mm: una freccia che arriva a meno di così dal bordo del piano è «Continuo»
DIARIO_BYTE = 300  # byte di ogni lavoro (e delle prime frecce) scritti nel diario

# Tabella dei comandi (documento di chiusura). emulato | ok (senza effetto) | errore
COMANDI = {
    "?": "emulato: stato con la posizione dell'ultimo pezzo finito",
    "!": "emulato: pacchetto PN (pausa) durante un lavoro; durante le frecce le ferma; da fermo niente",
    "~": "emulato: secondo PN (ripresa)",
    "Ctrl+X": "emulato: I, code svuotate; in movimento allarme 3 (posizione persa: serve $H); da fermo la posizione resta",
    "0x85": "emulato: nessun altro pezzetto delle frecce",
    "0x90-0x9D": "ok: ignorati (velocità e potenza le decide la scheda e la manopola)",
    "$H": "emulato: IPP, posizione 0,0",
    "$X": "emulato: toglie l'allarme, la posizione resta non nota",
    "$$ $I $G $# $N": "finti, minimi",
    "$n=v": "ok: ricordato, la scheda non ha impostazioni",
    "$C": "emulato: si traduce tutto, alla scheda niente",
    "$J=": "emulato: spostamento veloce a laser spento (fino al bordo: a pezzi); F ignorata",
    "G0 G1 X Y F S": "emulati (F in mm/min, S > 0 = laser acceso)",
    "G20 G21 G90 G91 G53 G54": "emulati",
    "G92 G92.1 G10 L2/L20 P1": "emulati (spostamento delle coordinate)",
    "G55-G59, G10 P2+": "error:20",
    "G2 G3": "error:20",
    "G4 G17 G40 G49 G80 G94 M7 M8 M9": "ok: senza effetto (mai il laser acceso da fermo)",
    "altri G": "error:20",
    "M3 M4 M5": "emulati (abilitano/spengono, il laser si accende solo muovendosi)",
    "M2 M30": "emulati: fine del lavoro",
    "fuori dal piano": "error:15",
    "senza posizione (dopo reset o $X)": "error:9",
}

_JOG = re.compile(r"([XYZF])\s*([-+]?(?:\d+\.?\d*|\.\d+))")


class _Fermato(Exception):
    pass


class K40Serial:
    """La «porta seriale» della K40. link: collegamento grezzo (studio.lihuiyu: WinDriver o LibUsb, o la scheda finta
    delle prove) con apri, inizia, scrivi(p32), stato(), chiudi."""

    def __init__(self, link, scheda="M2", diario=None, orologio=None, attesa=None, scala_tempo=1.0, piano=PIANO,
                 quiete=1.0, registra=False):
        self.link = link
        self.scheda = scheda
        self.diario = diario
        self.orologio = orologio or time.monotonic
        self.attesa = attesa or time.sleep
        self.k = float(scala_tempo)  # le prove automatiche accorciano le attese della scheda
        self.q = float(quiete)  # …e, a parte, i tempi di silenzio dopo cui il ponte chiude da solo
        self.registro = [] if registra else None  # prove: i comandi mandati alla scheda, pezzo per pezzo
        self.piano = piano
        self.is_open = True
        self._cv = threading.Condition()  # (lucchetto rientrante) stato, code e traduttore si toccano solo con questo
        self._link_lock = threading.Lock()  # un pacchetto alla volta sul collegamento
        self._out = bytearray()
        self._linea = bytearray()
        self._rx = collections.deque()
        self._coda = collections.deque()  # pezzi per l'alimentatore
        self._urgente = collections.deque()  # PN (pausa e ripresa): fra un pacchetto e l'altro
        self._in_volo = None  # il pezzo che l'alimentatore sta eseguendo
        self._byte_in_volo = 0
        self._gen = 0  # cambia a ogni stop: il pezzo in corso si interrompe e quello in preparazione si butta
        self._stop_chiesti = self._stop_fatti = 0  # «I» da far arrivare alla scheda (lo fa l'alimentatore)
        self.stato = "Alarm"  # come una scheda con l'homing acceso appena accesa: la posizione non si sa
        self.pos = [0.0, 0.0]  # mm, ultimo pezzo finito
        self.pos_nota = False
        self._dest = None  # dove sarà la testa finite le frecce in coda (le frecce si sommano)
        self.hold = False
        self.check = False
        self.impostazioni = {130: "300.000", 131: "200.000", 30: "1000", 32: "1", 22: "1", 20: "1", 23: "0",
                             110: "6000.000", 111: "6000.000"}
        self.errori_crc = 0
        self.guasto = None
        self.t = None  # Traduttore del lavoro in corso
        self._salvato = None  # quello vero, durante la verifica
        self._g54 = [0.0, 0.0]  # spostamento di G54: resta anche dopo un reset, come in GRBL
        self._risincronizza = False  # dopo frecce e casa la posizione del traduttore va ripresa da quella vera
        self._ultima_riga = self.orologio()
        self._conta = {"pezzi": 0, "byte": 0, "veloci": 0}  # per il diario: un riassunto a fine lavoro, non ogni pezzo
        self._inizio = bytearray()  # 0.22.7: i primi byte del lavoro in corso, per il diario
        self._frecce_scritte = 0
        self._annulli = 0  # 0.22.7: cresce a ogni 0x85 / «!» sulle frecce: una freccia in attesa non parte più
        link.apri()
        try:
            link.inizia()
        except Exception:
            try:
                link.chiudi()
            except Exception:  # noqa: BLE001
                pass
            raise
        self._diario("apertura", collegamento=getattr(link, "nome", type(link).__name__), scheda=scheda)
        self._emetti(SALUTO)
        self._fili = [threading.Thread(target=self._processore, daemon=True, name="k40-righe"),
                      threading.Thread(target=self._alimentatore, daemon=True, name="k40-scheda")]
        for f in self._fili:
            f.start()

    # ================================================================ la «porta»
    def write(self, data):
        for b in bytes(data):
            if b == ord("?"):
                self._emetti(self._stato_testo())
            elif b == 0x18:
                self._reset()
            elif b == 0x85:
                self._ferma_frecce()
            elif b == ord("!"):
                self._pausa(True)
            elif b == ord("~"):
                self._pausa(False)
            elif b >= 0x80:
                pass
            elif b in (10, 13):
                if self._linea:
                    riga = self._linea.decode("ascii", "replace").strip()
                    self._linea.clear()
                    with self._cv:
                        self._rx.append(riga)
                        self._cv.notify_all()
            else:
                self._linea.append(b)
        return len(data)

    def readline(self):
        with self._cv:
            if b"\n" not in self._out:
                self._cv.wait(timeout=0.1)
            i = self._out.find(b"\n")
            if i < 0:
                return b""
            r = bytes(self._out[:i + 1])
            del self._out[:i + 1]
            return r

    def reset_input_buffer(self):
        with self._cv:
            self._out.clear()

    def flush(self):
        pass

    def close(self):
        if not self.is_open:
            return
        with self._cv:
            self._butta_tutto()
            self.is_open = False
            self._cv.notify_all()
        alim = self._fili[1]
        if alim is not threading.current_thread():
            alim.join(10.0 * self.k + 2.0)  # l'alimentatore manda «I» e poi esce
        with self._cv:
            manca = self._stop_fatti != self._stop_chiesti
        if manca:  # l'alimentatore non ce l'ha fatta (fermo sul cavo): ultimo tentativo da qui
            self._ferma_scheda(massimo=2.0)
        if self._fili[0] is not threading.current_thread():
            self._fili[0].join(2.0)
        self._diario("chiusura", errori_crc=self.errori_crc)
        try:
            self.link.chiudi()
        except Exception:  # noqa: BLE001
            pass

    # ================================================================ stato e risposte
    def _emetti(self, testo):
        with self._cv:
            self._out += testo.encode("ascii", "replace")
            self._cv.notify_all()

    def _tipo_in_volo(self):
        return self._in_volo[0] if self._in_volo is not None else None

    def _solo_frecce(self):
        """In coda e in corso ci sono solo frecce (e almeno una)."""
        tipi = [p[0] for p in self._coda] + ([self._tipo_in_volo()] if self._in_volo is not None else [])
        return bool(tipi) and all(t == "freccia" for t in tipi)

    def _lavoro_aperto(self):
        """C'è un lavoro: aperto nel traduttore, in coda o in corso (le frecce e la casa non sono un lavoro)."""
        if self.check:
            return False
        if self.t is not None and self.t.in_lavoro():
            return True
        tipi = [p[0] for p in self._coda] + [self._tipo_in_volo()]
        return any(t in (DATI, ATTENDI_FINE, ATTENDI_FERMA) for t in tipi)

    def _fermo_del_tutto(self):
        return not (self._coda or self._in_volo is not None or self._lavoro_aperto())

    def _stato_testo(self):
        with self._cv:
            st = self.stato
            if st not in ("Alarm", "Check", "Home"):
                if self.hold:
                    st = "Hold:0"
                elif self._solo_frecce():
                    st = "Jog"
                elif not self._fermo_del_tutto():
                    st = "Run"
                else:
                    st = "Idle"
            x, y = self.pos
            g = self.t.offset if self.t is not None else tuple(self._g54)
        return f"<{st}|MPos:{x:.3f},{y:.3f},0.000|FS:0,0|WCO:{g[0]:.3f},{g[1]:.3f},0.000>\r\n"

    def _diario(self, cosa, **dati):
        if self.diario is not None:
            try:
                self.diario.scrivi("ponte", cosa=cosa, **dati)
            except Exception:  # noqa: BLE001 — il diario è un aiuto, non deve fermare niente
                pass

    def dentro(self, x, y):
        e = 1e-6
        return -e <= x <= self.piano[0] + e and -e <= y <= self.piano[1] + e

    def _nuovo_traduttore(self):
        def tr_(x, y):
            return round(x * MIL_PER_MM), round(y * MIL_PER_MM)
        old = self.t
        t = Traduttore(tr_, self.scheda, dentro=self.dentro, x=self.pos[0], y=self.pos[1])
        t.g54 = list(self._g54)
        if old is not None:  # spostamenti delle coordinate e modi restano (come in GRBL)
            t.g92, t.g54 = list(old.g92), list(old.g54)
            t.assoluto, t.pollici, t.f = old.assoluto, old.pollici, old.f
        return t

    # ================================================================ tempo reale
    def _butta_tutto(self):
        """(con il lucchetto) Stop: niente di quello che è in coda o in preparazione parte più, e alla scheda va «I»."""
        vero = self._salvato if self.check else self.t
        if vero is not None:
            self._g54 = list(vero.g54)
        self._coda.clear()
        self._rx.clear()
        self._urgente.clear()
        self._gen += 1
        self._stop_chiesti += 1
        self.hold = False
        self.check = False
        self.t = self._salvato = None
        self._dest = None
        self._risincronizza = True

    def _reset(self):
        with self._cv:
            fermo = self._fermo_del_tutto()
            self._butta_tutto()
            if fermo and self.pos_nota:
                self.stato = "Idle"  # da fermo la posizione resta buona, come in GRBL
            else:
                self.stato = "Alarm"
                self.pos_nota = False
            perso = not fermo
            self._cv.notify_all()
        self._diario("reset", in_movimento=perso)
        self._emetti(("ALARM:3\r\n" if perso else "") + SALUTO)

    def _guasto(self, perche):
        self.guasto = perche
        self._diario("errore", errore=perche)
        with self._cv:
            self._butta_tutto()
            self.stato = "Alarm"
            self.pos_nota = False
            self._cv.notify_all()
        self._emetti("ALARM:3\r\n[MSG:K40: " + re.sub(r"[\r\n\]]", " ", perche)[:80] + "]\r\n")

    def _togli_frecce(self):
        """(con il lucchetto) Le frecce in coda non partono; quella in corso (al massimo 2 mm) finisce."""
        self._coda.clear()
        self._dest = (self._in_volo[1], self._in_volo[2]) if self._tipo_in_volo() == "freccia" else None
        self._annulli += 1
        self._cv.notify_all()

    def _ferma_frecce(self):
        with self._cv:
            if self._solo_frecce():
                self._togli_frecce()

    def _pausa(self, on):
        with self._cv:
            if on:
                if self.hold:
                    return
                if not self._lavoro_aperto():
                    if self._solo_frecce():  # «!» durante le frecce le ferma, come in GRBL; alla scheda niente
                        self._togli_frecce()
                    return
            elif not self.hold:
                return
            self.hold = on
            self._urgente.append(b"PN")
            self._cv.notify_all()
        self._diario("pausa" if on else "ripresa")

    # ================================================================ righe
    def _processore(self):
        while self.is_open:
            with self._cv:
                if not self._rx:
                    self._cv.wait(timeout=min(0.05, 0.1 * self.q) + 0.005)
                riga = self._rx.popleft() if self._rx else None
            if riga is None:
                self._a_riposo()
                continue
            try:
                self._esegui(riga)
            except Exception as ex:  # noqa: BLE001 — una riga che rompe il ponte: ferma tutto
                self._guasto(f"{type(ex).__name__}: {ex}")
            # il silenzio si conta da quando la riga ha avuto risposta (il freno può tenerla ferma a lungo: senza
            # questo il lavoro verrebbe chiuso e riaperto a ogni attesa)
            self._ultima_riga = self.orologio()

    def _a_riposo(self):
        """Niente righe da un po': chiude il tratto acceso in sospeso (1 s) o il lavoro aperto (0,5 s)."""
        with self._cv:
            t = self.t
            if t is None or not t.in_lavoro() or self.check or self._rx:
                return
            quiete = self.orologio() - self._ultima_riga
            acceso = t.acceso
            if quiete < (1.0 if acceso else 0.5) * self.q:
                return
            sospesi = t.sospesi()
            t.chiudi()
            self._coda.extend(t.pronti())
            self._cv.notify_all()
        if acceso:
            self._diario("chiuso_da_solo", byte=sospesi)

    def _ok(self):
        self._emetti("ok\r\n")

    def _err(self, n):
        self._emetti(f"error:{n}\r\n")

    def _esegui(self, riga):
        up = riga.upper().replace(" ", "")
        if up.startswith("$"):
            return self._dollaro(riga.strip(), up)
        with self._cv:
            gen = self._gen
            if self.stato == "Alarm":
                return self._err(9)
            if self.check:
                return self._verifica(riga)
            if not self.pos_nota:
                return self._err(9)
            if self._risincronizza:
                # le frecce (o la casa) mandate prima finiscono, poi il lavoro parte da dove è la testa davvero
                while self.is_open and gen == self._gen and (self._coda or self._in_volo is not None):
                    self._cv.wait(timeout=0.05)
                if gen != self._gen or not self.is_open:
                    return None  # fermati nel frattempo: la riga è persa, come dopo un reset
                self._risincronizza = False
                self.t = self._nuovo_traduttore()
            if self.t is None:
                self.t = self._nuovo_traduttore()
            t = self.t
            try:
                t.riga(riga)
            except ErroreRiga as ex:
                codice = ex.codice
            else:
                codice = None
                if t.sospesi() > TETTO_SOSPESO:
                    t.chiudi()
                    codice = 11
                elif t.finito:
                    t.chiudi()
                    t.finito = False
                # riga, pezzi pronti e coda in un colpo solo: uno stop arriva prima (e la riga non c'è più) o dopo
                # (e la coda viene svuotata), mai a metà
                self._coda.extend(t.pronti())
                self._cv.notify_all()
        if codice is not None:
            self._diario("riga_rifiutata", codice=codice)
            return self._err(codice)
        self._freno(gen)
        if gen == self._gen:  # dopo uno stop niente «ok» in ritardo: sfaserebbe le risposte di chi manda
            self._ok()

    def _freno(self, gen):
        with self._cv:
            while self.is_open and gen == self._gen and self._byte_in_coda() >= FRENO:
                self._cv.wait(timeout=0.05)

    def _byte_in_coda(self):
        return self._byte_in_volo + sum(len(p[1]) for p in self._coda if p[0] == DATI)

    def _verifica(self, riga):
        if self.t is None:
            self.t = self._nuovo_traduttore()
        try:
            self.t.riga(riga)
        except ErroreRiga as ex:
            return self._err(ex.codice)
        self.t.pronti()  # in verifica non parte niente
        self._ok()

    def _dollaro(self, riga, up):
        if up == "$H":
            return self._casa()
        if up == "$X":
            with self._cv:
                if self.stato == "Alarm":
                    self.stato = "Idle"
            self._emetti("[MSG:Caution: Unlocked]\r\n")
            return self._ok()
        if up == "$$":
            self._emetti("".join(f"${k}={v}\r\n" for k, v in sorted(self.impostazioni.items())))
            return self._ok()
        if up == "$I":
            self._emetti(VERSIONE)
            return self._ok()
        if up == "$G":
            self._emetti("[GC:G0 G54 G17 G21 G90 G94 M5 M9 T0 F0 S0]\r\n")
            return self._ok()
        if up == "$#":
            with self._cv:
                t = self.t
                g54 = t.g54 if t is not None else self._g54
                g92 = t.g92 if t is not None else (0.0, 0.0)
            self._emetti(f"[G54:{g54[0]:.3f},{g54[1]:.3f},0.000]\r\n[G92:{g92[0]:.3f},{g92[1]:.3f},0.000]\r\n"
                         "[TLO:0.000]\r\n")
            return self._ok()
        if up == "$N":
            self._emetti("$N0=\r\n$N1=\r\n")
            return self._ok()
        if up == "$C":
            return self._modo_verifica()
        if up.startswith("$J="):
            return self._freccia(up[3:])
        m = re.match(r"^\$(\d+)=(.*)$", up)
        if m:
            self.impostazioni[int(m.group(1))] = m.group(2)
            return self._ok()
        return self._err(3)

    def _modo_verifica(self):
        with self._cv:
            if not self.check:
                if not self._fermo_del_tutto():
                    return self._err(8)
                self.check = True
                self.stato = "Check"
                self._salvato = self.t
                self.t = self._nuovo_traduttore()
                msg = "[MSG:Enabled]\r\n"
            else:
                self.check = False
                self.stato = "Idle" if self.pos_nota else "Alarm"
                self.t, self._salvato = self._salvato, None
                msg = "[MSG:Disabled]\r\n"
        self._emetti(msg)
        self._ok()

    # ================================================================ casa e frecce
    def _casa(self):
        with self._cv:
            if self.check:
                return self._err(8)
            gen = self._gen
            self.stato = "Home"
            self._risincronizza = True
            self._dest = None
            self._coda.append(("casa",))
            self._cv.notify_all()
            while self.is_open and gen == self._gen and (self._coda or self._in_volo is not None):
                self._cv.wait(timeout=0.05)
            if gen != self._gen or not self.is_open:
                return None  # fermata (reset, errore del cavo): lo stato l'ha già messo chi ha fermato
            self.stato = "Idle"
        self._ok()

    def _freccia(self, testo):
        with self._cv:
            if self.stato == "Alarm" or not self.pos_nota:
                return self._err(9)
            if self.check or self.stato == "Home" or self._lavoro_aperto():
                return self._err(8)
            vals = dict((k, float(v)) for k, v in _JOG.findall(testo))
            if "X" not in vals and "Y" not in vals:
                return self._err(16)
            # 0.22.7: una freccia aspetta che quelle prima siano partite (al massimo una in corso, nessuna in coda). Con
            # la 0.22.6 l'«ok» arrivava subito: il joystick mandava pezzetti a raffica, la coda andava molto avanti alla
            # testa e la direzione nuova arrivava solo a coda finita (rapporto C71A)
            gen, annulli = self._gen, self._annulli
            while self.is_open and gen == self._gen and any(p[0] == "freccia" for p in self._coda):
                self._cv.wait(timeout=0.02)
            if gen != self._gen or not self.is_open:
                return None
            if annulli != self._annulli:  # fermate (0x85 o «!») mentre aspettava: non parte
                return self._ok()
            if self.stato == "Alarm" or not self.pos_nota:
                return self._err(9)
            u = 25.4 if "G20" in testo else 1.0
            occupato = bool(self._coda) or self._in_volo is not None
            x0, y0 = self._dest if (occupato and self._dest is not None) else self.pos  # le frecce si sommano
            off = self.t.offset if self.t is not None else tuple(self._g54)
            if "G91" in testo:
                x, y = x0 + vals.get("X", 0.0) * u, y0 + vals.get("Y", 0.0) * u
            elif "G53" in testo:
                x, y = vals.get("X", x0 / u) * u, vals.get("Y", y0 / u) * u
            else:
                x = vals["X"] * u + off[0] if "X" in vals else x0
                y = vals["Y"] * u + off[1] if "Y" in vals else y0
            if not self.dentro(x, y):
                return self._err(15)
            lungo = ((x - x0) ** 2 + (y - y0) ** 2) ** 0.5
            if self._continuo(x0, y0, x, y) and lungo > PEZZETTO_FRECCE:
                n = int(lungo // PEZZETTO_FRECCE) + (1 if lungo % PEZZETTO_FRECCE > 1e-9 else 0)
            else:
                n = 1  # uno spostamento solo: fluido, come la casa
            self._coda.extend(("freccia", x0 + (x - x0) * i / n, y0 + (y - y0) * i / n) for i in range(1, n + 1))
            self._dest = (x, y)
            self._risincronizza = True
            self._cv.notify_all()
        self._ok()

    def _continuo(self, x0, y0, x, y):
        """La freccia va fino al bordo del piano su un asse che si muove: è «Continuo» (si ferma con 0x85)."""
        b = BORDO_CONTINUO
        for a, c, lim in ((x0, x, self.piano[0]), (y0, y, self.piano[1])):
            if abs(c - a) > 1e-6 and (c <= b or c >= lim - b):
                return True
        return False

    # ================================================================ alimentatore (l'unico filo che parla alla scheda)
    def _alimentatore(self):
        while True:
            with self._cv:
                while (self._stop_fatti == self._stop_chiesti and self.is_open and not self._urgente
                       and (self.hold or not self._coda)):
                    self._cv.wait(timeout=0.05)
                stop = self._stop_chiesti if self._stop_fatti != self._stop_chiesti else None
                cmd = pezzo = None
                if stop is None:
                    if not self.is_open:
                        return
                    if self._urgente:
                        cmd = self._urgente.popleft()
                    else:
                        pezzo = self._coda.popleft()
                        self._in_volo = pezzo
                        self._byte_in_volo = len(pezzo[1]) if pezzo[0] == DATI else 0
                gen = self._gen
            if stop is not None:
                self._ferma_scheda()  # prima di tutto
                with self._cv:
                    self._stop_fatti = stop
                    self._cv.notify_all()
                continue
            try:
                if cmd is not None:
                    self._manda_pn(cmd, gen)
                else:
                    self._fai(pezzo, gen)
            except _Fermato:
                pass
            except Exception as ex:  # noqa: BLE001 — cavo staccato, scheda che rifiuta: ferma tutto
                self._guasto(f"{type(ex).__name__}: {ex}")
            finally:
                with self._cv:
                    if pezzo is not None:
                        self._in_volo = None
                        self._byte_in_volo = 0
                    self._cv.notify_all()

    def _fermo(self, gen):
        if gen != self._gen or not self.is_open:
            raise _Fermato

    def _leggi_stato(self):
        with self._link_lock:
            data, _raw = self.link.stato()
        return data[1] if len(data) > 1 else None

    def _ferma_scheda(self, massimo=60.0):
        """«I» alla scheda, in modo che arrivi: si aspetta che la scheda prenda pacchetti («occupata» vuol dire che non
        li prende), si manda e si rilegge; con un errore di controllo si rimanda. Se resta occupata a lungo si manda lo
        stesso ogni 10 s, e si continua a provare."""
        p = pacchetti(b"I")[0]
        t0 = self.orologio()
        fine = t0 + massimo * self.k
        mandati, ok = 0, False
        try:
            while not ok:
                giro = min(self.orologio() + 10.0 * self.k, fine)
                s = self._leggi_stato()
                while s in (OCCUPATA, None) and self.orologio() < giro:
                    self.attesa(0.01 * self.k)
                    s = self._leggi_stato()
                libera = s not in (OCCUPATA, None)
                with self._link_lock:
                    self.link.scrivi(p)
                mandati += 1
                t1 = self.orologio()
                s = self._leggi_stato()
                while s in (OCCUPATA, None) and self.orologio() - t1 < 1.0 * self.k:
                    self.attesa(0.01 * self.k)
                    s = self._leggi_stato()
                ok = libera and s != ERRORE_CRC
                if self.orologio() >= fine:
                    break
        except Exception as ex:  # noqa: BLE001 — cavo staccato: non c'è altro da fare
            self._diario("errore", dove="stop", errore=f"{type(ex).__name__}: {ex}")
        self._diario("stop", mandati=mandati, confermato=ok, s=round(self.orologio() - t0, 3))
        return ok

    def _aspetta_libera(self, gen, massimo=120.0, obbligo=True):
        """Aspetta che la scheda non sia più «occupata» (cioè che prenda un pacchetto, o che abbia digerito quello
        appena mandato). -> lo stato letto. In pausa il tempo non conta; massimo None = finché serve."""
        t0 = self.orologio()
        while True:
            s = self._leggi_stato()
            if s not in (OCCUPATA, None):
                return s
            self._fermo(gen)
            if self.hold and obbligo:
                t0 = self.orologio()
            if massimo is not None and self.orologio() - t0 > massimo * self.k:
                if not obbligo:
                    return s
                raise IOError("la scheda resta occupata" if s == OCCUPATA else "la scheda non risponde")
            self.attesa(0.02 * self.k)

    def _manda_pacchetto(self, p, gen):
        for _ in range(8):
            self._aspetta_libera(gen)
            with self._link_lock:
                self._fermo(gen)  # con il collegamento in mano: dopo uno stop non parte più niente
                self.link.scrivi(p)
            # la conferma: finché è «occupata» lo sta ancora prendendo; poi «errore di controllo» = da rimandare
            if self._aspetta_libera(gen) != ERRORE_CRC:
                return
            self.errori_crc += 1
        raise IOError("la scheda rifiuta i pacchetti (errore di controllo ripetuto)")

    def _manda_pn(self, cmd, gen):
        """Pausa o ripresa: un pacchetto a parte. Se la scheda non conferma in fretta non è un guasto."""
        for p in pacchetti(cmd):
            for _ in range(8):
                self._aspetta_libera(gen, massimo=None)  # finché la scheda non prende pacchetti (come MeerK40t)
                with self._link_lock:
                    self._fermo(gen)
                    self.link.scrivi(p)
                if self._aspetta_libera(gen, massimo=5.0, obbligo=False) != ERRORE_CRC:
                    break
                self.errori_crc += 1
        self._diario("comando", dati=cmd.decode())

    def _svuota_urgenti(self, gen):
        while True:
            with self._cv:
                u = self._urgente.popleft() if self._urgente else None
            if u is None:
                return
            self._manda_pn(u, gen)

    def _manda(self, cmd, gen):
        sicuro = True
        for p, sicuro_dopo in pacchetti_a_parole(cmd):
            if sicuro:  # fra un comando e l'altro: qui può entrare la pausa
                self._svuota_urgenti(gen)
                while self.hold:  # in pausa non si manda altro (come MeerK40t): la ripresa trova sempre posto
                    self._fermo(gen)
                    self._svuota_urgenti(gen)
                    self.attesa(0.02 * self.k)
            sicuro = sicuro_dopo
            self._manda_pacchetto(p, gen)
            with self._cv:
                self._byte_in_volo = max(0, self._byte_in_volo - 30)
                self._cv.notify_all()

    def _fai(self, pezzo, gen):
        tipo = pezzo[0]
        t0 = self.orologio()
        if tipo == DATI:
            self._manda(pezzo[1], gen)
            if self.registro is not None:
                self.registro.append(pezzo[1])
            self._conta["pezzi"] += 1
            self._conta["byte"] += len(pezzo[1])
            if len(self._inizio) < DIARIO_BYTE:
                self._inizio += pezzo[1][:DIARIO_BYTE - len(self._inizio)]
        elif tipo == ATTENDI_FINE:
            prevista = float(pezzo[1]) if len(pezzo) > 1 else 0.0
            visti = self._attendi_fine(prevista * 3 + 15.0, gen)
            self._diario("fine", prevista=round(prevista, 3), s=round(self.orologio() - t0, 3), stati=visti[:20],
                         dati=self._inizio.decode("ascii", "replace"), **self._conta)
            self._conta = {"pezzi": 0, "byte": 0, "veloci": 0}
            self._inizio = bytearray()
        elif tipo == ATTENDI_FERMA:
            stima = float(pezzo[1]) if len(pezzo) > 1 else 2.0
            visti = self._attendi_ferma(1.0, max(30.0, 3 * stima), gen, minimo=stima)
            self._conta["veloci"] += 1
            if self._conta["veloci"] <= 5:  # i primi di ogni lavoro: bastano per capire come risponde la scheda
                self._diario("ferma", s=round(self.orologio() - t0, 3), stati=visti[:20])
        elif tipo == "pos":
            with self._cv:
                self.pos = [pezzo[1] / MIL_PER_MM, pezzo[2] / MIL_PER_MM]
        elif tipo == "casa":
            stima = durata_veloce((abs(self.pos[0]) + abs(self.pos[1])) * MIL_PER_MM)
            self._manda(b"IPP", gen)
            visti = self._attendi_ferma(1.0, max(60.0, 3 * stima), gen, minimo=max(2.0, stima))
            with self._cv:
                self._fermo(gen)
                self.pos, self.pos_nota, self._dest = [0.0, 0.0], True, None
            self._diario("casa", s=round(self.orologio() - t0, 3), stati=visti[:20])
        elif tipo == "freccia":
            sc = Scrittore(self.scheda)
            sc.x, sc.y = round(self.pos[0] * MIL_PER_MM), round(self.pos[1] * MIL_PER_MM)
            sc.veloce(round(pezzo[1] * MIL_PER_MM), round(pezzo[2] * MIL_PER_MM))
            dati, stima, visti = b"", 0.0, []
            for pz in sc.fine():
                if pz[0] == DATI:
                    dati += pz[1]
                    self._manda(pz[1], gen)
                elif pz[0] == ATTENDI_FERMA:
                    # 0.22.7: la M2 dice «pronta» anche mentre la testa va: si aspetta almeno il tempo stimato, poi
                    # «pronta» ferma per 0,3 s. Un «I» mandato prima fermerebbe la testa a metà
                    stima = float(pz[1]) if len(pz) > 1 else 0.5
                    visti = self._attendi_ferma(0.3, max(10.0, 3 * stima), gen, minimo=stima)
            with self._cv:
                self.pos = [pezzo[1], pezzo[2]]
            if self._frecce_scritte < 5:  # le prime: bastano per capire come risponde la scheda
                self._frecce_scritte += 1
                self._diario("freccia", dati=dati.decode("ascii", "replace")[:DIARIO_BYTE], stima=round(stima, 3),
                             s=round(self.orologio() - t0, 3), stati=visti[:20])

    def _attendi_fine(self, massimo, gen):
        t0 = self.orologio()
        visti, ultimo = [], None
        prima = t0
        while self.orologio() - t0 < massimo * self.k:
            self._fermo(gen)
            self._svuota_urgenti(gen)
            ora = self.orologio()
            if self.hold:  # il tempo della pausa non conta
                t0 += ora - prima
            prima = ora
            s = self._leggi_stato()
            if s != ultimo:
                visti.append((round(self.orologio() - t0, 3), s))
                ultimo = s
            if s in (FINITO, FINITO_M3):
                return visti
            self.attesa(0.02 * self.k)
        raise IOError("la scheda non ha finito il lavoro nel tempo previsto")

    def _attendi_ferma(self, stabile, massimo, gen, minimo=2.0):
        """Come lo studio (Scheda.aspetta_casa): la M2 dopo «S1P» e «IPP» non dice «finito», torna solo «pronta».
        Fine = «pronta» ferma per `stabile` secondi e almeno `minimo` secondi dall'invio (0.22.7: sempre, anche se
        «occupata» si è vista)."""
        t0 = self.orologio()
        visti, ultimo, t_pronta = [], None, None
        prima = t0
        while self.orologio() - t0 < massimo * self.k:
            self._fermo(gen)
            self._svuota_urgenti(gen)
            adesso = self.orologio()
            if self.hold:
                t0 += adesso - prima
            prima = adesso
            s = self._leggi_stato()
            ora = self.orologio() - t0
            if s != ultimo:
                visti.append((round(ora, 3), s))
                ultimo = s
                t_pronta = ora if s == OK else None
            if s in (FINITO, FINITO_M3):
                return visti
            # 0.22.7: il tempo minimo vale sempre (la M2 vera può dire «pronta» con la testa ancora in moto)
            if s == OK and t_pronta is not None and ora - t_pronta >= stabile * self.k and ora >= minimo * self.k:
                return visti
            self.attesa(0.02 * self.k)
        raise IOError("la testa non si ferma (nessuna risposta «pronta» dalla scheda)")
