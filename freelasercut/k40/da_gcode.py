# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Dal G-code che FreeLaserCut prepara per le macchine GRBL ai pezzi per la scheda K40.

Si leggono solo le parole che FreeLaserCut scrive: G0, G1, G90, G91, G20, G21, F, S, M3, M4, M5 (commenti e righe
vuote si saltano). La K40 non regola la potenza da programma (si regola con la manopola della macchina): ogni S > 0
con il laser abilitato (M3 o M4) vuol dire laser acceso, S0 o M5 spento.

trasforma(x_mm, y_mm) -> (x_passi, y_passi) porta le coordinate del G-code in quelle della scheda (origine a casa,
Y verso il davanti): la sceglie chi conosce il profilo della macchina.

0.22.6: Traduttore, la stessa cosa riga per riga (per il ponte, che riceve il lavoro una riga alla volta). pronti()
dà solo i comandi fino all'ultimo punto in cui il laser è spento: un tratto acceso parte solo quando è arrivata la riga
che lo spegne, così la scheda non resta mai senza dati con il raggio acceso. In più capisce G53 (coordinate della
macchina per una riga), G92/G92.1 e lo spostamento di G54 (G10 L2/L20 P1), che FreeLaserCut usa per «partenza dalla
testa» e «origine utente».
"""
import math
import re

from .scrittore import ATTENDI_FINE, DATI, MIL_PER_MM, Scrittore

_PAROLA = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
SALTO_VELOCE_MM = 8.0  # spostamenti più corti si fanno dentro il lavoro, a laser spento, senza uscire
# 0.22.7: niente lavori sotto i 7 mm/s finché i codici con la «C» (che servono sotto questa velocità) non sono provati
# sulla K40 vera: una velocità più bassa diventa 7 mm/s
V_MIN_LAVORO = 7.0  # mm/s

# 0.23.2 (Evoluzione2, foto sulla K40 che sbatte a ogni fine riga): righe delle foto nel modo raster della scheda.
RIGA_MAX = 40  # passi (circa 1 mm): un cambio di riga più grande non è il passo fra le righe di una foto
SALTO_RIGHE_MAX = 15  # passi in più del passo fra le righe che si fanno in diagonale dentro il lavoro raster
MARGINE_RASTER_MM = 5.0  # le righe raster stanno ad almeno questa distanza dai bordi sinistro e destro del piano
TENUTI_MAX = 60000  # movimenti tenuti da parte al massimo, mentre si capisce se sono righe
RIGHE_PER_ENTRARE = 2  # inversioni con cambio di riga viste prima di entrare nel modo raster


class _Mossa:
    """Un movimento del G-code già tradotto in passi. v = mm/s per G1, None per G0."""
    __slots__ = ("tx", "ty", "mx", "my", "v", "laser", "modo", "lungo")

    def __init__(self, tx, ty, mx, my, v, laser, modo, lungo):
        self.tx, self.ty, self.mx, self.my = tx, ty, mx, my
        self.v, self.laser, self.modo, self.lungo = v, laser, modo, lungo


class _Righe:
    """Stato del modo raster: dove è la testa davvero (x, y, passi), dove il G-code crede che sia (gx, gy), verso della
    riga (vx), cambio di riga ricevuto e non ancora fatto (pend: y voluta, o None)."""
    __slots__ = ("v", "passo", "vy", "x", "y", "gx", "gy", "vx", "pend", "gy_mm")

    def copia(self):
        r = _Righe()
        for k in self.__slots__:
            setattr(r, k, getattr(self, k))
        return r


def _parole(riga):
    riga = riga.split(";", 1)[0]
    riga = re.sub(r"\([^)]*\)", "", riga).upper()
    return [(m.group(1), float(m.group(2))) for m in _PAROLA.finditer(riga)]


class ErroreRiga(ValueError):
    """Riga che la K40 non può eseguire: codice d'errore GRBL (lo spiega grbl_codes) e motivo."""

    def __init__(self, codice, motivo):
        super().__init__(motivo)
        self.codice = codice


class Traduttore:
    """G-code -> pezzi per la scheda, una riga alla volta.

    trasforma(x_mm, y_mm) -> passi, come in traduci(); le coordinate qui sono quelle della macchina (dopo G92 e G54).
    dentro(x_mm, y_mm) -> False se il punto è fuori dal piano: la riga è rifiutata (ErroreRiga 15) e niente parte."""

    def __init__(self, trasforma=None, scheda="M2", correggi=True, senza_giri=False, salto_veloce_mm=SALTO_VELOCE_MM,
                 dentro=None, x=0.0, y=0.0, raster=True, piano=None):
        if trasforma is None:
            def trasforma(x, y):
                return round(x * MIL_PER_MM), round(y * MIL_PER_MM)
        self.trasforma, self.dentro, self.salto = trasforma, dentro, salto_veloce_mm
        self.sc = Scrittore(scheda, correggi=correggi, senza_giri=senza_giri)
        self.sc.x, self.sc.y = trasforma(x, y)
        self.sc._sicuro_xy = (self.sc.x, self.sc.y)
        self.x, self.y = float(x), float(y)  # coordinate della macchina, mm
        self.assoluto, self.pollici, self.modo = True, False, 0
        self.f, self.s, self.abilitato = 1000.0, 0.0, False
        self.g92 = [0.0, 0.0]
        self.g54 = [0.0, 0.0]
        self.n = 0
        self.finito = False  # M2 / M30
        # 0.23.2: righe delle foto nel modo raster della scheda (vedi _mossa)
        self.raster = bool(raster)
        self.piano = piano  # mm: per il margine dai bordi del modo raster (None = nessun controllo)
        self._g = (self.sc.x, self.sc.y)  # dove il G-code crede che sia la testa (passi)
        self._cand = None  # movimenti tenuti da parte finché non si capisce se sono righe di una foto
        self._cs = None  # quello che si sa delle righe tenute da parte (verso, cambi di riga, inversioni)
        self._ras = None  # stato del lavoro raster in corso
        self.diario_raster = []  # (cosa, dati): entrate e uscite dal modo raster, per il diario del ponte

    @property
    def offset(self):
        return (self.g54[0] + self.g92[0], self.g54[1] + self.g92[1])

    # codici G che il ponte capisce (× 10: G92.1 = 921). Gli altri sono rifiutati, come fa GRBL con quelli che non ha
    G_NOTI = frozenset((0, 10, 40, 100, 170, 200, 210, 400, 490, 530, 540, 800, 900, 910, 920, 921, 940))

    def riga(self, testo):
        """Una riga di G-code. ErroreRiga se la K40 non la può eseguire: in quel caso non cambia niente (né la
        posizione, né i modi, né quello che è già preparato)."""
        self.n += 1
        p = _parole(testo)
        if not p:
            return
        g = [int(round(v * 10)) for k, v in p if k == "G"]  # G92.1 -> 921, G21 -> 210
        if 20 in g or 30 in g:
            raise ErroreRiga(20, "archi G2/G3 non previsti per la K40")
        if any(c in (550, 560, 570, 580, 590) or (590 < c < 600) for c in g):
            raise ErroreRiga(20, "sistema di coordinate non disponibile sulla K40 (solo G54)")
        if any(c not in self.G_NOTI for c in g):
            raise ErroreRiga(20, "comando G non previsto per la K40")
        vals = {}
        for k, v in p:
            vals.setdefault(k, v)
        pollici = True if 200 in g else False if 210 in g else self.pollici
        u = 25.4 if pollici else 1.0
        if any(c in (100, 920, 921) for c in g):
            self._ferma_righe()  # 0.23.2: le coordinate cambiano: righe tenute da parte e lavoro raster si chiudono
        if 100 in g:  # G10
            if int(round(vals.get("P", 1))) != 1 or int(round(vals.get("L", 2))) not in (2, 20):
                raise ErroreRiga(20, "G10: sulla K40 solo G54 (P1)")
            l20 = int(round(vals.get("L", 2))) == 20
            for i, k in enumerate("XY"):
                if k in vals:
                    v = vals[k] * u
                    cur = (self.x, self.y)[i]
                    self.g54[i] = cur - self.g92[i] - v if l20 else v
            self.pollici = pollici
            return
        if 921 in g:  # G92.1
            self.g92 = [0.0, 0.0]
            self.pollici = pollici
            return
        if 920 in g:  # G92: la posizione di adesso diventa quella scritta
            for i, k in enumerate("XY"):
                if k in vals:
                    self.g92[i] = (self.x, self.y)[i] - self.g54[i] - vals[k] * u
            self.pollici = pollici
            return
        # tutto in variabili a parte: si scrive nello stato solo se la riga è buona
        modo, assoluto, abilitato, f, s, finito = self.modo, self.assoluto, self.abilitato, self.f, self.s, self.finito
        macchina = 530 in g
        nx, ny, muove = self.x, self.y, False
        ox, oy = (0.0, 0.0) if macchina else self.offset
        for c in g:
            if c in (0, 10):
                modo = c // 10
            elif c == 900:
                assoluto = True
            elif c == 910:
                assoluto = False
        for k, val in p:
            if k == "M":
                mm = int(round(val))
                if mm in (3, 4):
                    abilitato = True
                elif mm == 5:
                    abilitato = False
                elif mm in (2, 30):
                    finito = True
            elif k == "F":
                if val > 0:
                    f = val * u
            elif k == "S":
                s = val
            elif k in ("X", "Y"):
                v = val * u
                ass = assoluto or macchina
                if k == "X":
                    nx = v + ox if ass else nx + v
                else:
                    ny = v + oy if ass else ny + v
                muove = True
        if muove:
            if not (math.isfinite(nx) and math.isfinite(ny)):
                raise ErroreRiga(2, "coordinate non valide")
            if self.dentro is not None and not self.dentro(nx, ny):
                raise ErroreRiga(15, "fuori dal piano della K40")
        self.modo, self.assoluto, self.abilitato, self.f, self.s, self.finito = modo, assoluto, abilitato, f, s, finito
        self.pollici = pollici
        sc = self.sc
        acceso = modo == 1 and abilitato and s > 0
        if not muove:
            self._svuota_candidata()  # 0.23.2: una riga che non muove chiude le righe tenute da parte
            if sc.in_lavoro and sc.laser and not (abilitato and s > 0):
                sc._laser(False)  # M5 o S0 da soli: «U» subito, senza aspettare il prossimo movimento
            return
        tx, ty = self.trasforma(nx, ny)
        lungo = math.hypot(nx - self.x, ny - self.y)
        v = max(V_MIN_LAVORO, min(f / 60.0, 500.0)) if modo == 1 else None
        self._mossa(_Mossa(tx, ty, nx, ny, v, bool(acceso), modo, lungo))
        self.x, self.y = nx, ny

    # ------------------------------------------------------------ 0.23.2: righe delle foto in modo raster
    # Nel lavoro normale la scheda K40 non rallenta quando il verso si inverte: a ogni fine riga di una foto la testa
    # sbatte. Il modo raster della scheda fa da solo la fermata, l'inversione e la discesa di una riga.
    # Come si riconoscono le righe, senza sapere niente di chi ha scritto il G-code: tratti orizzontali (G1, stessa
    # velocità), poi un cambio di riga a laser spento (piccolo, ≤ RIGA_MAX), poi il verso che si inverte. I movimenti si
    # tengono da parte finché le righe non sono almeno tre (RIGHE_PER_ENTRARE inversioni); poi una prova a secco su
    # tutto quello che è tenuto: se va, si entra nel modo raster, altrimenti si fa tutto come prima (lavoro normale).
    # Nel modo raster ogni movimento passa da _piano_righe(): quello che non si può fare (tratto acceso fuori dalla
    # riga, altra velocità, salto di righe troppo grande, troppo vicino al bordo) fa uscire dal modo raster, e la testa
    # torna dove il G-code crede che sia prima di continuare come prima.
    def _mossa(self, m):
        if not self.raster:
            return self._normale(m)
        if self._ras is not None:
            piano = self._piano_righe(self._ras, m)
            if piano is not None:
                return self._esegui_righe(*piano)
            self._esci_raster("movimento fuori dalle righe")
        if self._cand is not None:
            self._cand.append(m)
            esito = self._valuta_candidata()
            if esito == "attendi":
                return None
            if esito == "entra":
                return None
            return self._svuota_candidata()
        if self._inizio_righe(m):
            self._cand = [m]
            self._valuta_candidata()  # prepara quello che si sa delle righe
            return None
        return self._normale(m)

    def _normale(self, m):
        """Il movimento come fino alla 0.23.1 (lavoro normale)."""
        sc = self.sc
        if m.modo == 0:
            if sc.in_lavoro and m.lungo < self.salto:
                sc.vai(m.tx, m.ty, sc.v, laser=False)  # salto corto: resto nel lavoro, a laser spento
            else:
                sc.veloce(m.tx, m.ty)
        else:
            v = m.v
            if not m.laser and sc.in_lavoro and v != sc.v and m.lungo < self.salto:
                v = sc.v  # tratto spento e corto: cambiare velocità vorrebbe dire uscire dal lavoro e rientrare
            sc.vai(m.tx, m.ty, v, laser=m.laser)
        self._g = (m.tx, m.ty)

    def _inizio_righe(self, m):
        """Un tratto orizzontale in G1 può essere l'inizio di una foto."""
        return (m.modo == 1 and m.ty == self._g[1] and m.tx != self._g[0] and m.v is not None
                and m.v >= V_MIN_LAVORO)

    def _svuota_candidata(self):
        """Le righe tenute da parte non erano una foto (o non si sa ancora e bisogna chiudere): tutto come prima."""
        cand, self._cand = self._cand, None
        for m in cand or ():
            self._normale(m)

    def _ferma_righe(self):
        self._svuota_candidata()
        if self._ras is not None:
            self._esci_raster("fine delle righe")

    def _valuta_candidata(self):
        """Dopo ogni movimento aggiunto alle righe tenute da parte -> "attendi", "entra" (fatto) o "no". Il controllo
        è a passi (solo l'ultimo movimento), la prova a secco una volta sola, quando le righe sono abbastanza."""
        cand = self._cand
        if len(cand) > TENUTI_MAX:
            return "no"
        m = cand[-1]
        if len(cand) == 1:
            self._cs = {"v": m.v, "vx": 1 if m.tx > self._g[0] else -1, "pend": False, "inv": 0, "dy_mm": None,
                        "dy_passi": 0, "px": m.tx, "py": m.ty, "my0": m.my}
            return "attendi"
        cs = self._cs
        if m.modo == 1 and m.v != cs["v"]:
            return "no"
        if m.ty != cs["py"]:
            if m.laser or abs(m.ty - cs["py"]) > RIGA_MAX:
                return "no"
            if cs["inv"] == 0:
                cs["dy_passi"] += m.ty - cs["py"]
                cs["dy_mm"] = abs(m.my - cs["my0"])
            cs["pend"] = True
        dx = m.tx - cs["px"]
        if dx:
            if (dx > 0) == (cs["vx"] > 0):
                if cs["pend"] and m.laser:
                    return "no"
            else:
                if not cs["pend"]:
                    return "no"
                cs["pend"], cs["vx"] = False, -cs["vx"]
                cs["inv"] += 1
        cs["px"], cs["py"] = m.tx, m.ty
        inversioni, v, dy_mm, dy_passi = cs["inv"], cs["v"], cs["dy_mm"], cs["dy_passi"]
        if inversioni < RIGHE_PER_ENTRARE:
            return "attendi"
        passo = self._passo_da(dy_mm)
        if passo < 1:
            return "no"
        r = _Righe()
        r.v, r.passo, r.vy = v, passo, (1 if dy_passi > 0 else -1)
        r.x, r.y = self.sc.x, self.sc.y
        r.gx, r.gy = self._g
        r.vx = 1 if cand[0].tx > self._g[0] else -1
        r.pend, r.gy_mm = None, None
        prova = r.copia()
        for m in cand:  # prova a secco: tutto quello che è tenuto deve andare nel modo raster
            piano = self._piano_righe(prova, m)
            if piano is None:
                return "no"
            prova = piano[1]
        # si entra: la testa è dove era prima delle righe tenute (niente è ancora partito)
        self._cand = None
        self.sc.inizia_raster(v, passo, r.vy, r.vx)
        self._ras = r
        self.diario_raster.append(("entra", {"v": round(v, 2), "passo": passo, "righe_tenute": len(cand)}))
        for m in cand:
            self._esegui_righe(*self._piano_righe(self._ras, m))
        return "entra"

    @staticmethod
    def _passo_da(dy_mm):
        """Passo fra le righe in passi della scheda, mai più lungo del cambio di riga più corto che arriverà: la scheda
        scende sempre di esattamente questo passo, e quello che manca per arrivare alla riga giusta si fa prima, in
        diagonale a laser spento. Così ogni riga cade esattamente dove la mette il lavoro normale (stesso
        arrotondamento al passo). Un passo quasi intero (es. 0,254 mm = 10 passi) diventa uno in meno: i numeri del
        G-code arrotondati a 0,001 mm a volte danno una riga un passo più corta."""
        if not dy_mm:
            return 0
        p = dy_mm * MIL_PER_MM
        k = int(round(p))
        if abs(p - k) <= 0.05:
            return k - 1 if k >= 2 else k
        return int(math.floor(p))

    def _dentro_passi(self, x, y, margine=0.0):
        if self.piano is None:
            return True
        k = MIL_PER_MM
        return (margine * k - 1e-6 <= x <= (self.piano[0] - margine) * k + 1e-6
                and -1e-6 <= y <= self.piano[1] * k + 1e-6)

    def _piano_righe(self, r, m):
        """-> (operazioni, nuovo stato) o None se nel modo raster non si può fare. Non tocca né r né la scheda."""
        if m.modo == 1 and m.v != r.v:
            return None
        pend = r.pend
        if m.ty != r.gy:  # cambio di riga: si fa all'inversione
            if m.laser:
                return None
            pend = m.ty
            bisogno = (pend - r.y) * r.vy
            if bisogno < r.passo or bisogno - r.passo > SALTO_RIGHE_MAX:
                return None  # un salto che non è il cambio di riga: fuori dal modo raster prima di muoversi
        n = r.copia()
        ops = []
        dx = m.tx - r.x
        if dx:
            sx = 1 if dx > 0 else -1
            if sx == r.vx:
                if pend is not None and m.laser:
                    return None
            else:
                if pend is None:
                    return None  # inversione senza cambio di riga: nel modo raster non c'è
                bisogno = (pend - r.y) * r.vy
                if bisogno < r.passo or bisogno - r.passo > SALTO_RIGHE_MAX:
                    return None
                extra = bisogno - r.passo
                if extra:
                    n.x += r.vx * extra
                    n.y += r.vy * extra
                    if not self._dentro_passi(n.x, n.y, MARGINE_RASTER_MM):
                        return None
                    ops.append(("diagonale", extra))
                n.y += r.vy * r.passo
                n.vx = sx
                pend = None
                if m.laser and n.x != r.gx:
                    # dopo la diagonale la testa è oltre la fine della riga: il primo tratto acceso deve partire da
                    # dove il G-code lo fa partire, quindi prima (a laser spento) si torna lì, già nel verso nuovo
                    if (r.gx - n.x) * sx <= 0 or not self._dentro_passi(r.gx, n.y, MARGINE_RASTER_MM):
                        return None
                    ops.append(("riga", r.gx, False))
                    n.x = r.gx
            if not self._dentro_passi(m.tx, n.y, MARGINE_RASTER_MM):
                return None
            ops.append(("riga", m.tx, m.laser))
            n.x = m.tx
        n.pend = pend
        n.gx, n.gy = m.tx, m.ty
        return ops, n

    def _esegui_righe(self, ops, nuovo):
        sc = self.sc
        for op in ops:
            if op[0] == "diagonale":
                sc.raster_diagonale(op[1])
            else:
                sc.raster_x(op[1], op[2])
        if (sc.x, sc.y) != (nuovo.x, nuovo.y):  # non deve succedere: meglio fermarsi che bruciare nel posto sbagliato
            raise RuntimeError(f"righe raster: posizione {sc.x},{sc.y} invece di {nuovo.x},{nuovo.y}")
        self._ras = nuovo
        self._g = (nuovo.gx, nuovo.gy)

    def _esci_raster(self, perche):
        """Fuori dal modo raster: si chiude il lavoro e, se serve, la testa va (a laser spento) dove il G-code crede
        che sia (cambio di riga ricevuto e non fatto, passo di differenza)."""
        r, self._ras = self._ras, None
        sc = self.sc
        if sc.in_lavoro:
            sc._laser(False)
        sc.fine_lavoro()
        if (sc.x, sc.y) != (r.gx, r.gy):
            sc.vai(r.gx, r.gy, r.v, laser=False)
        self._g = (r.gx, r.gy)
        self.diario_raster.append(("esce", {"perche": perche}))

    # ------------------------------------------------------------ uscita
    @property
    def acceso(self):
        """Un tratto acceso è a metà (comandi già preparati che finiscono con il laser acceso)."""
        return self.sc.in_lavoro and self.sc.laser

    def sospesi(self):
        """Byte preparati che non si possono ancora mandare (dopo l'ultimo punto sicuro), più una stima delle righe
        tenute da parte (0.23.2)."""
        tenuti = 8 * len(self._cand) if self._cand is not None else 0
        return len(self.sc._buf) - (self.sc._sicuro if self.sc.in_lavoro else len(self.sc._buf)) + tenuti

    def in_lavoro(self):
        # 0.23.2: anche con righe tenute da parte (dopo un silenzio il ponte chiude, e chiudi() le manda)
        return self.sc.in_lavoro or self._cand is not None

    def chiudi(self):
        """Fine: spegne (se serve) e chiude il lavoro aperto. Poi pronti() dà tutto."""
        self._ferma_righe()
        self.sc._laser(False) if self.sc.in_lavoro else None
        self.sc.fine_lavoro()
        self.sc._chiudi_pezzo()

    def pronti(self):
        """-> pezzi da mandare adesso, fino all'ultimo punto sicuro. Gli «attendi_fine» portano la durata prevista;
        alla fine un ("pos", x, y) con la posizione (passi) della testa quando quei pezzi sono finiti."""
        sc = self.sc
        out = []
        durate = iter(sc.durate)
        for pz in sc.pezzi:
            out.append((ATTENDI_FINE, next(durate, 0.0)) if pz[0] == ATTENDI_FINE else pz)
        sc.pezzi, sc.durate = [], []
        if sc.in_lavoro:
            if sc._sicuro > 0:
                out.append((DATI, bytes(sc._buf[:sc._sicuro])))
                del sc._buf[:sc._sicuro]
                sc._sicuro = 0
            pos = sc._sicuro_xy
        else:
            pos = (sc.x, sc.y)
        if out:
            out.append(("pos",) + tuple(pos))
        return out


def traduci(righe, trasforma=None, scheda="M2", correggi=True, senza_giri=False, salto_veloce_mm=SALTO_VELOCE_MM,
            raster=True, piano=(300.0, 200.0)):
    """righe di G-code -> (pezzi, avvisi). Tutto in una volta (le prove e il salvataggio); vedi Traduttore."""
    t = Traduttore(trasforma, scheda, correggi, senza_giri, salto_veloce_mm, raster=raster, piano=piano)
    for riga in righe:
        try:
            t.riga(riga)
        except ErroreRiga as ex:
            raise ValueError(f"riga {t.n}: {ex}") from None
    t.chiudi()
    return t.sc.pezzi, []
