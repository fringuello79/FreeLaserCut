# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.4 (Evoluzione2, rapporto 0FFD, K40 con la M2 Nano): «movimento strano in Y» nel file degli impulsi.

Causa: ogni lavoro normale della scheda finisce con il suo «giro» (circa 4 mm oltre in X, 4 mm in Y e ritorno). Le righe
in un verso solo (file degli impulsi, riempimenti e foto con «Bidirezionale» spento) chiudevano un lavoro a ogni
ritorno: 72 giri nel file degli impulsi, uno per riga in un riempimento. Ora vanno nel modo raster della scheda con i
comandi di MeerK40t (codice «V…G{passo}G000»): la scheda scende di un passo alla fine della riga incisa, il ritorno a
laser spento corre sulla riga nuova, alla fine del ritorno la scheda non scende. Il lavoro resta uno.

Prove: (A) file degli impulsi e riempimenti in un verso: niente giri, stessi punti bruciati del lavoro normale, stessa
fine, nessun pericolo; (B) guasti messi apposta (laser acceso nel ritorno, cambio di riga nel ritorno, salto grande,
altra velocità, inversione sulla stessa riga, righe miste, bordo): si esce dal modo raster e i punti restano gli
stessi; (C) 300 G-code a caso in un verso solo; (D) il ponte con la scheda finta, anche FLC_K40_SENZA_GIRI=1 e
FLC_K40_RASTER=0; (E) le righe avanti e indietro restano come nella 0.23.3.
Uso: python tests/test_v234_k40_righe_un_verso.py
"""
import os
import random
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "tools", "k40"))
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
import k40_prova_impulsi  # noqa: E402
from k40_scheda_finta import SchedaFinta  # noqa: E402

from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import Document, EllipseShape, RectShape  # noqa: E402
from freelasercut.k40 import da_gcode  # noqa: E402
from freelasercut.k40.ponte import K40Serial  # noqa: E402
from freelasercut.k40.codici import codice  # noqa: E402
from freelasercut.k40.scrittore import DATI, Scrittore  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def simula(righe, raster=True, senza_giri=False):
    pezzi, _ = da_gcode.traduci(righe, raster=raster, senza_giri=senza_giri)
    dati = b"".join(p[1] for p in pezzi if p[0] == DATI)
    f = SchedaFinta(scala=1e-7)
    f._testo = dati.decode("ascii")
    f._leggi()
    f.chiudi()
    return f


def bruciati(f):
    return sorted(zip(f.accesi, f.accesi_v))


def uguali(fn, fr):
    a, b = bruciati(fn), bruciati(fr)
    return (len(a) == len(b) and all(sa == sb and abs(va - vb) <= 0.01 * max(va, vb) + 0.1
                                     for (sa, va), (sb, vb) in zip(a, b)) and (fn.x, fn.y) == (fr.x, fr.y))


def confronta(nome, righe, giri_max=None, raster_atteso=True, solo_punti=False):
    fn, fr = simula(righe, False), simula(righe, True)
    if solo_punti:  # velocità molto alte: il codice normale arrotonda di più (240 mm/s invece di 250), quello raster no
        ok = (sorted(fn.accesi) == sorted(fr.accesi) and (fn.x, fn.y) == (fr.x, fr.y)
              and min(fr.accesi_v) >= min(fn.accesi_v))
    else:
        ok = uguali(fn, fr)
    check(f"{nome}: stessi punti bruciati del lavoro normale e stessa posizione finale", ok and fr.accesi,
          (len(fn.accesi), len(fr.accesi), (fn.x, fn.y), (fr.x, fr.y)))
    check(f"{nome}: nessun pericolo, nessuna inversione a piena velocità in più ({len(fn.colpi)} nel lavoro normale)",
          not fr.pericoli and len(fr.colpi) <= len(fn.colpi) and (len(fr.colpi) == 0 or not raster_atteso),
          (fr.pericoli[:2], len(fr.colpi), len(fn.colpi)))
    if raster_atteso:
        check(f"{nome}: giri della scheda da {fn.lavori_con_giro} a {fr.lavori_con_giro}",
              fr.lavori_raster >= 1 and fn.lavori_con_giro > 0 and fr.lavori_con_giro <= (giri_max or 0),
              (fn.lavori_con_giro, fr.lavori_con_giro, fr.lavori_raster))
    return fn, fr


def lavoro(build):
    doc = Document()
    build(doc)
    return gcode.generate(doc, MachineProfile.k40(), gcode.JobOptions(start_from="absolute", no_g55=True)).lines


def riempimento(forma="rett", bidir=False, intervallo=0.2, vel=6000, x=60, y=60, w=30, h=20):
    def build(d):
        s = RectShape(w, h) if forma == "rett" else EllipseShape(w, h)
        s.apply(QTransform.fromTranslate(x, y))
        d.add(s)
        cs = d.layer(s.layer)
        cs.mode, cs.speed, cs.interval, cs.bidirectional = "fill", vel, intervallo, bidir
    return lavoro(build)


# ====================================================================== A. i casi di Evo
print("--- A. file degli impulsi e riempimenti in un verso solo")
imp = k40_prova_impulsi.genera()
fn, fr = confronta("file degli impulsi (72 righe in 24 strisce)", imp, giri_max=0)
check("A …una striscia = un lavoro raster (24), nessun giro", fr.lavori_raster == 24 and fr.lavori_con_giro == 0,
      (fr.lavori_raster, fr.lavori_con_giro))
check("A …gli impulsi restano lunghi uguali (6696 tratti accesi, come prima)", len(fr.accesi) == len(fn.accesi) == 6696,
      (len(fn.accesi), len(fr.accesi)))
for nome, args in {"rettangolo 30×20 a 100 mm/s, righe a 0,2 mm": dict(),
                   "rettangolo a 0,1 mm": dict(intervallo=0.1),
                   "ellisse 40×25 a 0,254 mm": dict(forma="ell", w=40, h=25, intervallo=0.254),
                   "rettangolo a 20 mm/s": dict(vel=1200),
                   "rettangolo a 250 mm/s": dict(vel=15000, intervallo=0.3)}.items():
    fn, fr = confronta(f"riempimento in un verso, {nome}", riempimento(**args), giri_max=0,
                       solo_punti="250" in nome)
    check(f"A …{nome}: un lavoro solo", fr.lavori_raster == 1 and fr.comandi.count("S1E") == 1,
          (fr.lavori_raster, fr.comandi.count("S1E")))
# tempo: il ritorno ora è alla velocità della riga (prima era uno spostamento veloce, ma con un giro per riga)
fn, fr = simula(riempimento(), False), simula(riempimento(), True)
print(f"    (tempo di movimento stimato: prima {fn.secondi:.1f} s + {fn.lavori_con_giro} giri, ora {fr.secondi:.1f} s)")
check("A …tempo di movimento ragionevole (meno del doppio di prima senza contare i giri)",
      fr.secondi < 2.0 * fn.secondi + 1, (fn.secondi, fr.secondi))
fn, fr = confronta("righe fitte a 0,05 mm (2 passi)", riempimento(intervallo=0.05, h=3), giri_max=0)
check("A …righe fitte: un lavoro raster solo", fr.lavori_raster == 1, fr.lavori_raster)
# i comandi: gli stessi di MeerK40t (raster «unidirectional»: due valori G, il primo a fine riga, poi 0)
check("A codice raster in un verso: «V…G003G000» (come la formula di MeerK40t, con il secondo G a 0)",
      codice("M2", 58.333, passo_raster=(3, 0)) == "V2170092G003G000" and codice("M2", 58.333, passo_raster=3)
      == "V2170092G003", codice("M2", 58.333, passo_raster=(3, 0)))
sc = Scrittore("M2")
sc.x, sc.y = 1000, 2000
sc.inizia_raster(58.333, 3, 1, 1, un_verso=True)
sc.raster_x(1100, True)
sc.raster_x(1000, False)
y1 = sc.y
sc.raster_x(1100, True)
check("A entrata «IV2170092G003G000NRBS1E»; giù di 3 a fine riga, fermo a fine ritorno", bytes(sc._buf).startswith(
      b"IV2170092G003G000NRBS1E") and y1 == 2003 and sc.y == 2003, (bytes(sc._buf)[:40], y1, sc.y))

# ====================================================================== B. guasti messi apposta
print("--- B. guasti messi apposta")
# tre righe da sinistra a destra, ritorno con G0 diagonale (come il file degli impulsi): si entra nel modo raster
TESTA = ["G90 G21", "M4 S0"]
for k in range(4):
    yy = 50 + 0.254 * k
    TESTA += [f"G0 X98 Y{yy:.3f}", "G1 X100 S0 F3000", "X110 S1000", "X112 S0"]
Y5 = 50 + 0.254 * 4
CODA = ["M5 S0", "G0 X10 Y10"]
guasti = {
    "laser acceso nel ritorno": [f"G0 Y{Y5:.3f}", "G1 X105 S0", "X100 S1000", "X98 S0"],
    "cambio di riga durante il ritorno": [f"G0 X104 Y{Y5:.3f}", f"G0 Y{Y5 + 0.254:.3f}", "G0 X98",
                                          "G1 X100 S0", "X110 S1000"],
    "salto di molte righe": [f"G0 X98 Y{Y5 + 2.0:.3f}", "G1 X100 S0", "X110 S1000", "X112 S0"],
    "riga a un'altra velocità": [f"G0 X98 Y{Y5:.3f}", "G1 X100 S0 F1200", "X110 S1000", "X112 S0"],
    "inversione sulla stessa riga dopo un tratto acceso": ["G1 X108 S1000", "X104 S0"],
    "riga incisa nel verso opposto (righe miste)": [f"G0 Y{Y5:.3f}", "G1 X110 S1000", "X100 S0"],
    "tratto acceso obliquo": [f"G0 X98 Y{Y5:.3f}", "G1 X100 S0", "X110 Y52 S1000", "X112 S0"],
    "ritorno che non arriva all'inizio della riga": [f"G0 X105 Y{Y5:.3f}", "G1 X106 S0", "X110 S1000"],
}
for nome, pezzo in guasti.items():
    fn, fr = confronta(nome, TESTA + pezzo + CODA, raster_atteso=False)
    check(f"{nome}: prima nel modo raster, poi fuori o avanti senza danni", fr.lavori_raster >= 1,
          (fr.lavori_raster, fr.comandi.count("S1E")))
fn, fr = confronta("riempimento attaccato al bordo sinistro (meno di 5 mm)", riempimento(x=1.0), raster_atteso=False)
check("B …a meno di 5 mm dal bordo niente modo raster", fr.lavori_raster == 0, fr.lavori_raster)
# il controllo interno: se il piano e la scheda non tornano, il traduttore si ferma invece di bruciare a caso
t = da_gcode.Traduttore(raster=True, piano=(300.0, 200.0))
vero = t._piano_righe_uni
t._piano_righe_uni = lambda r, m: (lambda p: (p[0] + [("diagonale", 1)], p[1]) if p and p[0] else p)(vero(r, m))
errore = False
try:
    for r in TESTA + [f"G0 X98 Y{Y5:.3f}", "G1 X100 S0", "X110 S1000"] + CODA:
        t.riga(r)
    t.chiudi()
except RuntimeError:
    errore = True
check("B piano sbagliato messo apposta: il controllo se ne accorge e si ferma (RuntimeError)", errore)

# ====================================================================== C. G-code a caso
print("--- C. 300 G-code a caso in un verso solo")


def caso(rng):
    L = ["G90 G21", "M4 S0"]
    pitch = rng.choice([0.1, 0.254, 0.127, 0.2, 0.3, 0.5, 0.0254 * rng.randint(2, 14)])
    run, verso = rng.uniform(0.5, 6), rng.choice([1, -1])
    x0 = rng.uniform(12, 220) if verso > 0 else rng.uniform(80, 288)  # righe dentro il piano (fino a 69 mm)
    y, F = rng.uniform(5, 150), rng.choice([600, 1800, 3500, 6000, 12000])
    for _row in range(rng.randint(1, 20)):
        xa = x0 + rng.uniform(-3, 3) * (rng.random() < 0.3)
        xr = xa - verso * run
        L += [f"G0 X{xr:.3f} Y{y:.3f}" if rng.random() < 0.7 else f"G1 X{xr:.3f} Y{y:.3f} S0",
              f"G1 X{xa:.3f} S0 F{F}"]
        x = xa
        for _k in range(rng.randint(1, 10)):
            x += verso * rng.uniform(0.05, 6)
            L.append(f"G1 X{x:.3f} S{rng.choice([0, 1000])}")
        L.append(f"G1 X{x + verso * run:.3f} S0")
        r = rng.random()
        if r < 0.05:
            L.append(f"G1 X{x - verso * 2:.3f} S1000")  # guasto: laser acceso indietro
        elif r < 0.08:
            L += ["M5 S0", "M4 S0"]
        elif r < 0.10:
            F = rng.choice([F, 1200])
        rows = 1 if rng.random() < 0.85 else rng.randint(2, 8)
        y = min(y + pitch * rows, 195)
    return L + ["M5 S0", "G0 X10 Y10"]


rng = random.Random(20261126)
diversi, con_raster, giri_prima, giri_dopo = [], 0, 0, 0
for i in range(300):
    L = caso(rng)
    fn, fr = simula(L, False), simula(L, True)
    con_raster += fr.lavori_raster > 0
    giri_prima += fn.lavori_con_giro
    giri_dopo += fr.lavori_con_giro
    if not uguali(fn, fr) or fr.pericoli or len(fr.colpi) > len(fn.colpi):
        diversi.append(i)
check("C stessi punti bruciati e stessa fine in tutti i 300, nessun pericolo né inversioni a piena velocità in più",
      not diversi, diversi[:5])
check("C il modo raster entra in buona parte dei casi e i giri calano molto", con_raster > 120
      and giri_dopo < giri_prima * 0.5, (con_raster, giri_prima, giri_dopo))

# ====================================================================== D. il ponte
print("--- D. il ponte con la scheda finta")
K = 0.02


def until(fn, t=10.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.005)
    return bool(fn())


class Cliente:
    def __init__(self):
        self.b = SchedaFinta(scala=K)
        self.p = K40Serial(self.b, registra=True, scala_tempo=K)
        self.leggi(0.2)
        self.cmd("$X")
        self.cmd("$H")
        self.fermo()

    def leggi(self, t=0.0):
        end = time.time() + t
        while self.p.readline() or time.time() < end:
            pass

    def cmd(self, riga, t=30.0):
        self.p.write((riga + "\n").encode())
        end = time.time() + t
        while time.time() < end:
            r = self.p.readline()
            if r:
                s = r.decode().strip()
                if s == "ok" or s.startswith("error") or s.startswith("ALARM"):
                    return s
        return "nessuna risposta"

    def stato(self):
        self.p.write(b"?")
        end = time.time() + 2.0
        while time.time() < end:
            r = self.p.readline()
            if r and r.startswith(b"<"):
                return r.decode()
        return ""

    def fermo(self, t=60.0):
        return until(lambda: self.stato().startswith("<Idle"), t)

    def manda(self, righe):
        esiti = [self.cmd(r) for r in righe]
        return all(e == "ok" for e in esiti) and self.fermo(60)


righe = [r.split(";")[0].strip() for r in riempimento(h=8) if r.split(";")[0].strip()]
atteso = simula(righe, True)
c = Cliente()
check("D riempimento in un verso mandato al ponte: tutte «ok» e la scheda torna ferma", c.manda(righe))
check("D …stessi punti della traduzione diretta, un lavoro raster, nessun giro, nessun pericolo",
      sorted(c.b.accesi) == sorted(atteso.accesi) and c.b.lavori_raster == 1 and c.b.lavori_con_giro == 0
      and not c.b.pericoli, (len(c.b.accesi), len(atteso.accesi), c.b.lavori_raster, c.b.lavori_con_giro))
c.p.close()
contorno = ["G90 G21", "M4 S0", "G0 X50 Y50", "G1 X100 S1000 F1800", "Y100", "X50", "Y50", "M5 S0", "G0 X10 Y10"]
c = Cliente()
c.manda(contorno)
check("D contorno di prova, di solito: lavoro con il giro (la «C» resta spenta)", c.b.lavori_con_giro >= 1,
      c.b.lavori_con_giro)
c.p.close()
os.environ["FLC_K40_SENZA_GIRI"] = "1"
c = Cliente()
ok = c.manda(contorno)
check("D FLC_K40_SENZA_GIRI=1: il contorno va con la «C» (nessun lavoro con il giro), stessi punti", ok
      and c.b.lavori_con_giro == 0 and len(c.b.accesi) == len(simula(contorno, True).accesi) and not c.b.pericoli,
      (c.b.lavori_con_giro, len(c.b.accesi)))
del os.environ["FLC_K40_SENZA_GIRI"]
c.p.close()
os.environ["FLC_K40_RASTER"] = "0"
c = Cliente()
c.manda(righe)
check("D FLC_K40_RASTER=0: come la 0.23.3 (nessun lavoro raster, un giro per riga, stessi punti)",
      c.b.lavori_raster == 0 and c.b.lavori_con_giro > 5 and sorted(c.b.accesi) == sorted(atteso.accesi),
      (c.b.lavori_raster, c.b.lavori_con_giro))
del os.environ["FLC_K40_RASTER"]
c.p.close()

# ====================================================================== E. avanti e indietro: come prima
print("--- E. righe avanti e indietro: come nella 0.23.3")
bi = riempimento(bidir=True)
fr = simula(bi, True)
check("E riempimento avanti e indietro: un lavoro raster, stesso passo di prima (2073 byte)",
      fr.lavori_raster == 1 and len(b"".join(p[1] for p in da_gcode.traduci(bi)[0] if p[0] == DATI)) == 2073,
      len(b"".join(p[1] for p in da_gcode.traduci(bi)[0] if p[0] == DATI)))
confronta("riempimento avanti e indietro", bi, raster_atteso=False)

n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
