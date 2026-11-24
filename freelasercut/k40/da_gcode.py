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

    def __init__(self, trasforma=None, scheda="M2", correggi=True, senza_giri=True, salto_veloce_mm=SALTO_VELOCE_MM,
                 dentro=None, x=0.0, y=0.0):
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
            if sc.in_lavoro and sc.laser and not (abilitato and s > 0):
                sc._laser(False)  # M5 o S0 da soli: «U» subito, senza aspettare il prossimo movimento
            return
        tx, ty = self.trasforma(nx, ny)
        lungo = math.hypot(nx - self.x, ny - self.y)
        if modo == 0:
            if sc.in_lavoro and lungo < self.salto:
                sc.vai(tx, ty, sc.v, laser=False)  # salto corto: resto nel lavoro, a laser spento
            else:
                sc.veloce(tx, ty)
        else:
            v = max(0.5, min(f / 60.0, 500.0))
            if not acceso and sc.in_lavoro and v != sc.v and lungo < self.salto:
                v = sc.v  # tratto spento e corto: cambiare velocità vorrebbe dire uscire dal lavoro e rientrare
            sc.vai(tx, ty, v, laser=acceso)
        self.x, self.y = nx, ny

    # ------------------------------------------------------------ uscita
    @property
    def acceso(self):
        """Un tratto acceso è a metà (comandi già preparati che finiscono con il laser acceso)."""
        return self.sc.in_lavoro and self.sc.laser

    def sospesi(self):
        """Byte preparati che non si possono ancora mandare (dopo l'ultimo punto sicuro)."""
        return len(self.sc._buf) - (self.sc._sicuro if self.sc.in_lavoro else len(self.sc._buf))

    def in_lavoro(self):
        return self.sc.in_lavoro

    def chiudi(self):
        """Fine: spegne (se serve) e chiude il lavoro aperto. Poi pronti() dà tutto."""
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


def traduci(righe, trasforma=None, scheda="M2", correggi=True, senza_giri=True, salto_veloce_mm=SALTO_VELOCE_MM):
    """righe di G-code -> (pezzi, avvisi). Tutto in una volta (le prove e il salvataggio); vedi Traduttore."""
    t = Traduttore(trasforma, scheda, correggi, senza_giri, salto_veloce_mm)
    for riga in righe:
        try:
            t.riga(riga)
        except ErroreRiga as ex:
            raise ValueError(f"riga {t.n}: {ex}") from None
    t.chiudi()
    return t.sc.pezzi, []
