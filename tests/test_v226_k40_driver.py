# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.6: driver K40 (scheda M2 Nano), primo pezzo: codici di velocità, scrittore dei comandi, traduzione dal
G-code. Non ancora collegato all'interfaccia.

Le prove leggono i comandi prodotti con un lettore indipendente (qui sotto), che fa quello che farebbe la scheda:
posizione, laser, lavoro, velocità. Così si controlla che la testa vada dove dice il G-code, che il laser sia acceso
solo dove deve, e che la linea fatta a passi non si allontani dalla retta.

Uso: python tests/test_v226_k40_driver.py
"""
import math
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "", flush=True)


from freelasercut.k40 import codici as C  # noqa: E402
from freelasercut.k40 import da_gcode as G  # noqa: E402
from freelasercut.k40 import scrittore as S  # noqa: E402


# ====================================================================== lettore indipendente
def leggi_distanza(t, i):
    n = 0
    while i < len(t) and t[i] == "z":
        n += 255
        i += 1
    if i < len(t):
        c = t[i]
        if "a" <= c <= "y":
            return n + ord(c) - 96, i + 1
        if c == "|" and i + 1 < len(t):
            return n + ord(t[i + 1]) - 96 + 25, i + 2
        if c.isdigit():
            return n + int(t[i:i + 3]), i + 3
    return n, i


class Lettore:
    """Fa quello che farebbe la scheda con i comandi: posizione, laser, lavoro, velocità, tratti accesi."""

    def __init__(self):
        self.x = self.y = 0
        self.vx = self.vy = 1
        self.lavoro = False
        self.laser = False
        self.codice = None
        self.accesi = []  # (x0, y0, x1, y1, codice)
        self.punti = []  # tutte le posizioni toccate, in ordine
        self.errori = []
        self.veloci = 0

    def _passo(self, dx, dy, n):
        x0, y0 = self.x, self.y
        self.x += dx * n
        self.y += dy * n
        self.punti.append((self.x, self.y, self.laser and self.lavoro))
        if self.laser and self.lavoro:
            self.accesi.append((x0, y0, self.x, self.y, self.codice))

    def esegui(self, dati):
        t = dati.decode("ascii")
        i = 0
        while i < len(t):
            if t.startswith("CV", i) or (t[i] == "V" and not self.lavoro):
                m = re.match(r"C?V\d{7}(?:\d{9})?C?|V\d{7}G\d{3}", t[i:])
                if not m:
                    self.errori.append(f"codice illeggibile a {i}")
                    return
                self.codice = m.group(0)
                i += len(self.codice)
            elif t.startswith("S1E", i):
                self.lavoro = True
                i += 3
            elif t.startswith("FNSE", i):
                self.lavoro, self.laser = False, False
                i += 4
            elif t.startswith("S1P", i):
                i += 3
            elif t.startswith("IPP", i):
                self.x = self.y = 0
                i += 3
            elif t[i] == "I":
                self.veloci += 1
                i += 1
            elif t[i] == "N":
                i += 1
            elif t[i] in "DU":
                if not self.lavoro:
                    self.errori.append(f"{t[i]} fuori dal lavoro a {i}")
                self.laser = t[i] == "D"
                i += 1
            elif t[i] in "BTLRM":
                c = t[i]
                n, j = leggi_distanza(t, i + 1)
                if c == "B":
                    self.vx = 1
                elif c == "T":
                    self.vx = -1
                elif c == "R":
                    self.vy = 1
                elif c == "L":
                    self.vy = -1
                if n:
                    if c in "BT":
                        self._passo(self.vx, 0, n)
                    elif c in "RL":
                        self._passo(0, self.vy, n)
                    else:
                        self._passo(self.vx, self.vy, n)
                i = j
            elif t[i] == "F":
                i += 1
            else:
                self.errori.append(f"lettera sconosciuta {t[i]!r} a {i}")
                i += 1


def leggi(pezzi):
    lt = Lettore()
    for p in pezzi:
        if p[0] == S.DATI:
            lt.esegui(p[1])
    return lt


# ====================================================================== A. codici di velocità
check("A esempio della pagina tecnica: scheda M, 12,7 mm/s, codici originali → CV1410801 (valore 36176)",
      C.codice("M", 12.7, correggi=False, senza_giri=False) == "CV1410801")
c30 = C.codice("M2", 30, correggi=False, senza_giri=False)
c10 = C.codice("M2", 10, correggi=False, senza_giri=False)
check("A i codici mandati alla K40 di Evo (30 e 10 mm/s) a meno di 1 unità",
      c30[:2] == "CV" and abs(int(c30[2:8]) - 195235) <= 1 and c30[8:] == "2031000086"
      and abs(int(c10[2:8]) - 115192) <= 1 and c10[8:] == "1011002218", (c30, c10))
vv = C.velocita_vera("M2", c30)
check("A con i codici originali la scheda va al 92 %: 30 → 27,59 mm/s, come misurato da Evo (27,587)",
      abs(vv - 27.587) < 0.05, vv)
for v in (3, 10, 30, 60, 100, 200, 300):
    for con_c in (True, False):
        k = C.codice("M2", v, senza_giri=con_c)
        if abs(C.velocita_vera("M2", k) - v) > max(0.02 * v, 0.05):
            check(f"A velocità vera ≈ chiesta ({v} mm/s, C={con_c})", False, (k, C.velocita_vera("M2", k)))
check("A con la correzione la scheda va alla velocità chiesta (3–300 mm/s, con e senza «C»), entro il 2 %", True)
check("A «C» finale (senza giri) di partenza nei tagli, accelerazione 1", C.codice("M2", 30).endswith("C")
      and C.codice("M2", 30)[8] == "1")
check("A sotto i 7 mm/s la «C» c'è sempre sulla M2", C.codice("M2", 5, senza_giri=False).endswith("C"))
check("A raster: «V…G» senza «C», passo fra le righe", re.fullmatch(r"V\d{7}G003", C.codice("M2", 100, passo_raster=3))
      is not None)
check("A schede A, B, B1: niente «C» (non ci sono le formule)", not C.codice("B", 30).endswith("C"))
check("A fasce di accelerazione: 25,4 / 60 / 127 mm/s", [C.accelerazione(v) for v in (25, 26, 60, 61, 126, 128)]
      == [1, 2, 2, 3, 3, 4])
bad = 0
for v in (0, -5, float("nan"), 1e9):
    try:
        C.codice("M2", v)
    except ValueError:
        bad += 1
try:
    C.codice("X9", 10)
except ValueError:
    bad += 1
check("A velocità impossibili e schede sconosciute: rifiutate", bad == 5)

# ====================================================================== B. distanze e pacchetti
ok = all(leggi_distanza(S.distanza(n), 0) == (n, len(S.distanza(n))) for n in range(0, 3000))
check("B distanze da 0 a 3000 passi: scritte e rilette uguali", ok)
check("B forme note: 1 = a, 25 = y, 26 = |a, 51 = |z, 52 = 052, 255 = z, 256 = za",
      [S.distanza(n) for n in (1, 25, 26, 51, 52, 255, 256)] == ["a", "y", "|a", "|z", "052", "z", "za"])
pk = S.pacchetti(b"A" * 65)
check("B pacchetti da 32 byte, CRC giusto, solo l'ultimo riempito di F",
      len(pk) == 3 and all(len(p) == 32 and p[0] == 0 and S.crc8(p[1:31]) == p[31] for p in pk)
      and pk[0][1:31] == b"A" * 30 and pk[2][1:31] == b"AAAAA" + b"F" * 25)

# ====================================================================== C. rette a passi
random.seed(7)
peggio = 0.0
giusti = True
for _ in range(400):
    dx, dy = random.randint(-900, 900), random.randint(-900, 900)
    x = y = 0
    L = math.hypot(dx, dy)
    for sx, sy, n in S.passi_retta(dx, dy):
        for _k in range(n):
            x += sx
            y += sy
            if L:
                peggio = max(peggio, abs(dx * y - dy * x) / L)
    giusti &= (x, y) == (dx, dy)
check("C rette a passi: arrivano sempre al punto giusto (400 rette a caso)", giusti)
check("C …e non si allontanano più di un passo dalla retta vera", peggio <= 0.75, peggio)
check("C retta orizzontale: un solo tratto", S.passi_retta(500, 0) == [(1, 0, 500)])
check("C diagonale a 45°: un solo tratto diagonale", S.passi_retta(-300, 300) == [(-1, 1, 300)])

# ====================================================================== D. dal G-code
quadro = ["G21", "G90", "M4 S0", "G0 X10 Y10", "G1 X30 Y10 F600 S800", "G1 X30 Y25", "G1 X10 Y25", "G1 X10 Y10",
          "G0 X12 Y12", "G1 X20 Y12 S500", "M5", "G0 X0 Y0"]
pezzi, avvisi = G.traduci(quadro)
lt = leggi(pezzi)
mil = G.MIL_PER_MM
check("D quadrato: nessun errore di lettura, la testa torna a 0,0", not lt.errori and (lt.x, lt.y) == (0, 0), lt.errori)
lati = [(round(a), round(b), round(c), round(d)) for a, b, c, d, _k in lt.accesi]
lunghezza = sum(math.hypot(c - a, d - b) for a, b, c, d in lati) / mil
check("D quadrato: laser acceso solo sui 4 lati e sul tratto finale (40 + 30 + 8 mm)",
      abs(lunghezza - (20 + 15 + 20 + 15 + 8)) < 0.3, lunghezza)
check("D il laser si accende solo dentro un lavoro, si spegne prima del salto", all(p[2] is False for p in lt.punti
                                                                                  if (p[0], p[1]) == (0, 0)))
check("D velocità del lavoro: 600 mm/min = 10 mm/s", abs(C.velocita_vera("M2", lt.accesi[0][4]) - 10) < 0.1)
attese = [p[0] for p in pezzi if p[0] != S.DATI]
check("D dopo ogni spostamento veloce si aspetta che la testa sia ferma, dopo un lavoro che sia finito",
      attese == [S.ATTENDI_FERMA, S.ATTENDI_FINE, S.ATTENDI_FERMA], attese)
check("D ogni spostamento veloce comincia con «I» solo dopo un'attesa (non cancella niente di non finito)",
      all(pezzi[i - 1][0] != S.DATI for i, p in enumerate(pezzi) if p[0] == S.DATI and p[1].startswith(b"I") and i > 0))
check("D il salto corto (2,8 mm) resta dentro il lavoro: un solo lavoro in tutto", sum(
    p[1].count(b"S1E") for p in pezzi if p[0] == S.DATI) == 1)

# G91, pollici, M5 a metà, S0
rel = ["G21", "G91", "M3 S1000", "G1 X5 Y0 F1200 S1000", "G1 X0 Y5 S0", "G1 X-5 Y0 S1000", "M5", "G1 X0 Y-5 S1000",
       "G20", "G90", "G0 X1 Y1"]
lt = leggi(G.traduci(rel)[0])
on = sum(math.hypot(c - a, d - b) for a, b, c, d, _k in lt.accesi) / mil
check("D coordinate relative: acceso solo dove S > 0 e il laser è abilitato (5 + 5 mm)", abs(on - 10) < 0.1, on)
check("D pollici (G20): X1 Y1 = 25,4 mm", (lt.x, lt.y) == (1000, 1000), (lt.x, lt.y))
try:
    G.traduci(["G2 X1 Y1 I1 J0"])
    archi = False
except ValueError:
    archi = True
check("D archi G2/G3: rifiutati con un messaggio (FreeLaserCut non li scrive)", archi)
lt = leggi(G.traduci(["G0 X0 Y0 ; commento", "(nota) G1 X10 F600 S900 M4", "", "G1 X10 Y10 S900"])[0])
check("D commenti e righe vuote non disturbano", not lt.errori and (lt.x, lt.y) == (round(10 * mil), round(10 * mil)))

# raster: tante righe con tratti accesi e spenti
ras = ["G21", "G90", "M4 S0", "G0 X0 Y0"]
for r in range(20):
    yy = r * 0.1
    ras += [f"G1 X0 Y{yy:.1f} F6000 S0", f"G1 X5 Y{yy:.1f} S700", f"G1 X7 Y{yy:.1f} S0", f"G1 X12 Y{yy:.1f} S300",
            f"G1 X15 Y{yy:.1f} S0"]
pz = G.traduci(ras)[0]
lt = leggi(pz)
on = sum(math.hypot(c - a, d - b) for a, b, c, d, _k in lt.accesi) / mil
check("D raster di 20 righe: acceso 20 × (5 + 5) mm, nessun errore", not lt.errori and abs(on - 200) < 1, on)
check("D raster: un solo lavoro (nessuna uscita per i tratti spenti corti)",
      sum(p[1].count(b"S1E") for p in pz if p[0] == S.DATI) == 1)

# casa
sc = S.Scrittore()
sc.vai(1000, 500, 20, laser=True)
sc.casa()
sc.vai(10, 10, 20, laser=False)
pz = sc.fine()
lt = leggi(pz)
check("D casa: chiude il lavoro, «IPP», attesa, poi riparte da 0,0", (lt.x, lt.y) == (10, 10)
      and [p[0] for p in pz] == [S.DATI, S.ATTENDI_FINE, S.DATI, S.ATTENDI_FERMA, S.DATI, S.ATTENDI_FINE])

# ====================================================================== E. difetti rimessi apposta
caught = []
orig = S.passi_retta
S.passi_retta = lambda dx, dy: ([(1 if dx > 0 else -1, 1 if dy > 0 else -1, min(abs(dx), abs(dy)))] if dx and dy else []) + (
    [((1 if dx > 0 else -1) if abs(dx) > abs(dy) else 0, 0 if abs(dx) > abs(dy) else (1 if dy > 0 else -1),
      abs(abs(dx) - abs(dy)))] if abs(dx) != abs(dy) else [])  # 1. prima tutta la diagonale, poi il resto
x = y = 0
L = math.hypot(700, 200)
dev = 0.0
for sx, sy, n in S.passi_retta(700, 200):
    for _k in range(n):
        x += sx
        y += sy
        dev = max(dev, abs(700 * y - 200 * x) / L)
caught.append(dev > 0.75)
S.passi_retta = orig
orig_l = S.Scrittore._laser
S.Scrittore._laser = lambda self, on: None  # 2. il laser non si spegne mai
lt = leggi(G.traduci(["M4", "G1 X10 F600 S900", "G1 X10 Y10 S0", "G1 X20 Y10 S900"])[0])
on2 = sum(math.hypot(c - a, d - b) for a, b, c, d, _k in lt.accesi) / mil
caught.append(abs(on2 - 20) > 0.1 or not lt.accesi)
S.Scrittore._laser = orig_l
orig_v = S.Scrittore.veloce
S.Scrittore.veloce = lambda self, x, y: (self._scrivi(b"I" + b"B" + S.distanza(abs(x - self.x)).encode() + b"S1P"),
                                         setattr(self, "x", x), setattr(self, "y", y))  # 3. senza attesa e senza Y
pz = G.traduci(["G0 X10 Y10", "M4", "G1 X20 Y10 F600 S900", "G0 X0 Y30"])[0]
lt = leggi(pz)
caught.append((lt.x, lt.y) != (0, round(30 * mil)) or S.ATTENDI_FERMA not in [p[0] for p in pz])
S.Scrittore.veloce = orig_v
check("E tre difetti rimessi apposta (diagonale tutta prima, laser mai spento, spostamento veloce senza Y e senza "
      "attesa): tutti visti", all(caught), caught)

print(f"\n{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
