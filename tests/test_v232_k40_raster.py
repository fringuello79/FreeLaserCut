# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.2 (Evoluzione2, 25/11/2026, K40 con la M2 Nano): le foto sbattevano a ogni fine riga.

Causa: nel lavoro «normale» la scheda non rallenta quando il verso si inverte. Le foto (e i riempimenti) ora vanno nel
modo raster della scheda (codice «V…G» con il passo fra le righe): a ogni inversione la scheda si ferma, gira e scende
di una riga da sola. Il traduttore riconosce le righe nel G-code, tiene da parte le prime tre, prova a secco e solo
se tutto va entra nel modo raster; quello che non è una riga (tratto acceso fuori riga, altra velocità, salto di righe
grande, bordo vicino) fa uscire e continuare come prima.

Prove: (A) comandi e codici di velocità (uguali a quelli di MeerK40t con la velocità corretta); (B) foto e riempimenti
di FreeLaserCut sulla scheda finta: stessi punti bruciati del lavoro normale, nessuna inversione a piena velocità;
(C) casi in cui il modo raster non si usa; (D) 300 G-code a caso; (E) il ponte con la scheda finta, anche con stop;
(F) silenzio a metà delle righe tenute da parte; (G) passo fra le righe.
Uso: python tests/test_v232_k40_raster.py
"""
import math
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
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from k40_scheda_finta import SchedaFinta  # noqa: E402

from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import Document, EllipseShape, ImageShape, RectShape  # noqa: E402
from freelasercut.k40 import da_gcode  # noqa: E402
from freelasercut.k40.codici import codice  # noqa: E402
from freelasercut.k40.ponte import K40Serial  # noqa: E402
from freelasercut.k40.scrittore import DATI, MIL_PER_MM, Scrittore  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def simula(righe, raster):
    """Traduce e fa eseguire tutto alla scheda finta (senza ponte). -> scheda finta, byte."""
    pezzi, _ = da_gcode.traduci(righe, raster=raster)
    dati = b"".join(p[1] for p in pezzi if p[0] == DATI)
    f = SchedaFinta(scala=1e-7)
    f._testo = dati.decode("ascii")
    f._leggi()
    f.chiudi()
    return f, dati


def lavoro(build):
    doc = Document()
    build(doc)
    return gcode.generate(doc, MachineProfile.k40(), gcode.JobOptions(start_from="absolute", no_g55=True)).lines


def occhio(doc, x=59.7, y=105.0, w=86.5, h=86.5, dpi=254.0, dither="stucki", bidir=True, overscan=None):
    """Come la foto di Evo: un occhio (anello scuro, centro chiaro, pupilla), righe di lunghezza molto diversa."""
    yy, xx = np.mgrid[0:300, 0:300]
    r = np.hypot(xx - 150.0, (yy - 150.0) / 0.55)
    a = np.full((300, 300), 255, np.uint8)
    m = r < 142
    a[m] = (np.clip(np.abs(r[m] - 70) / 70, 0, 1) * 230).astype(np.uint8)
    a[np.hypot(xx - 150, yy - 150) < 22] = 0
    doc.images["o"] = Image.fromarray(a)
    im = ImageShape("o", w, h, layer=0)
    im.apply(QTransform.fromTranslate(x, y))
    doc.add(im)
    cs = doc.layer(0)
    cs.mode, cs.dither, cs.dpi, cs.speed, cs.bidirectional = "image", dither, dpi, 3500, bidir
    if overscan is not None:
        cs.overscan = overscan


def bruciati(f):
    """Tratti bruciati con la loro velocità (mm/s, a meno dell'1 %: i codici raster e normali arrotondano diverso)."""
    return sorted(zip(f.accesi, f.accesi_v))


def uguali(fn, fr):
    a, b = bruciati(fn), bruciati(fr)
    return (len(a) == len(b) and all(sa == sb and abs(va - vb) <= 0.01 * max(va, vb) + 0.1
                                     for (sa, va), (sb, vb) in zip(a, b)) and (fn.x, fn.y) == (fr.x, fr.y))


def stessa_cosa(nome, righe, raster_atteso=True):
    fn, dn = simula(righe, False)
    fr, dr = simula(righe, True)
    uguale = uguali(fn, fr)
    check(f"{nome}: stessi punti bruciati del lavoro normale e stessa posizione finale", uguale and fr.accesi,
          (len(fn.accesi), len(fr.accesi), (fn.x, fn.y), (fr.x, fr.y)))
    check(f"{nome}: nessun pericolo (laser mai acceso nelle inversioni, sempre dentro il piano)",
          not fr.pericoli, fr.pericoli[:3])
    if raster_atteso:
        check(f"{nome}: modo raster usato, nessuna inversione a piena velocità (prima: {len(fn.colpi)})",
              fr.lavori_raster >= 1 and not fr.colpi and fn.colpi, (fr.lavori_raster, len(fr.colpi), len(fn.colpi)))
    return fn, fr


# ====================================================================== A. comandi
print("--- A. comandi")
sc = Scrittore("M2")
sc.x, sc.y = 1000, 2000
sc.inizia_raster(58.333, 3, 1, 1)
check("A entrata: «I» + codice raster + «N», prima il verso delle righe e poi quello orizzontale, «S1E»",
      bytes(sc._buf) == b"IV2170092G003NRBS1E", bytes(sc._buf))
# codici raster: gli stessi che dà la formula di MeerK40t con la velocità corretta (11148), calcolati a parte
attesi = {(58.333, 3): "V2170092G003", (58.333, 10): "V2170092G010", (100, 4): "V2242402G004",
          (200, 10): "V2281203G010", (20, 7): "V1801781G007"}
check("A codici di velocità raster uguali a quelli di riferimento", all(codice("M2", v, passo_raster=p) == c
                                                                      for (v, p), c in attesi.items()),
      {k: codice("M2", k[0], passo_raster=k[1]) for k in attesi})
del sc._buf[:]
sc.raster_x(1100, True)
sc.raster_x(1150, False)
sc.raster_x(1120, True)  # inversione con il primo tratto acceso
check("A righe: «D» e «B100», «U» e «B|y», poi l'inversione con il primo tratto acceso: «T» da sola, «D», «T» e la "
      "strada (30 = «|e»)", bytes(sc._buf) == b"DB100UB|yTDT|e", bytes(sc._buf))
check("A …e la scheda è scesa di una riga (3 passi)", (sc.x, sc.y) == (1120, 2003), (sc.x, sc.y))
del sc._buf[:]
sc.raster_x(1200, False)
check("A inversione con il laser acceso prima: «U» poi la lettera nuova", bytes(sc._buf).startswith(b"UB"),
      bytes(sc._buf))
del sc._buf[:]
sc.raster_diagonale(2)
check("A diagonale a laser spento nel verso della riga e delle righe", bytes(sc._buf) == b"Mb"
      and (sc.x, sc.y) == (1202, 2008), (bytes(sc._buf), sc.x, sc.y))
sc.fine_lavoro()
check("A fine del lavoro raster: FNSE, attesa della fine e niente più passo", sc.pezzi[-2][1].endswith(b"FNSE")
      and sc.pezzi[-1][0] == "attendi_fine" and sc.passo == 0, sc.pezzi[-2:])

# ====================================================================== B. foto e riempimenti
print("--- B. foto e riempimenti di FreeLaserCut")
fn, fr = stessa_cosa("occhio come quello di Evo (86 mm, stucki, 254 dpi)", lavoro(lambda d: occhio(d)))
check("B …un lavoro raster solo, senza spostamenti veloci a metà", fr.lavori_raster == 1
      and fr.comandi.count("S1P") <= fn.comandi.count("S1P"), (fr.lavori_raster, fr.comandi.count("S1P")))
stessa_cosa("occhio a 100 dpi (passo intero di 10 passi)", lavoro(lambda d: occhio(d, dpi=100.0)))
stessa_cosa("occhio a 127 dpi", lavoro(lambda d: occhio(d, dpi=127.0, w=40, h=40)))
stessa_cosa("occhio senza rincorsa (overscan 0)", lavoro(lambda d: occhio(d, overscan=0.0, w=40, h=40)))


def riempimento(d, incrociato=False):
    e = EllipseShape(40, 25)
    e.apply(QTransform.fromTranslate(150, 100))
    e.layer = 0
    d.add(e)
    cs = d.layer(0)
    cs.mode, cs.speed, cs.interval, cs.crosshatch = "fill", 6000, 0.1, incrociato


stessa_cosa("riempimento di un'ellisse a 100 mm/s", lavoro(riempimento))


def foto_e_taglio(d):
    occhio(d, w=40, h=40)
    r = RectShape(50, 30)
    r.apply(QTransform.fromTranslate(150, 120))
    r.layer = 1
    d.add(r)
    cs = d.layer(1)
    cs.mode, cs.speed = "line", 600


fn, fr = stessa_cosa("foto e poi un taglio", lavoro(foto_e_taglio))
check("B …il taglio resta un lavoro normale (dopo quello raster)", fr.lavori_raster == 1
      and fr.comandi.count("S1E") == fn.comandi.count("S1E"), (fr.comandi.count("S1E"), fn.comandi.count("S1E")))

# ====================================================================== C. quando il modo raster non si usa
print("--- C. casi senza modo raster")
fn, fr = stessa_cosa("foto in un verso solo (unidirezionale)", lavoro(lambda d: occhio(d, bidir=False, w=30, h=20)),
                     raster_atteso=False)
# 0.23.4 (rapporto 0FFD): ora anche le righe in un verso solo vanno nel modo raster (codice «V…G»
# con due «G» come MeerK40t), così la scheda non fa il giro a ogni riga; le prove sono in test_v234_k40_righe_un_verso.py
check("C …0.23.4: anche in un verso solo un lavoro raster, nessun lavoro con il giro della scheda",
      fr.lavori_raster == 1 and fr.lavori_con_giro == 0 and fn.lavori_con_giro > 10,
      (fr.lavori_raster, fr.lavori_con_giro, fn.lavori_con_giro))
fn, fr = stessa_cosa("foto attaccata al bordo sinistro", lavoro(lambda d: occhio(d, x=1.0, overscan=0.5, w=40, h=40)),
                     raster_atteso=False)
vicini = [s for s in fr.accesi_raster if min(s[0], s[2]) < 5.0 * MIL_PER_MM - 1]
check("C …a meno di 5 mm dal bordo niente modo raster (la rampa della scheda potrebbe uscire); più in là sì",
      fr.lavori_raster >= 1 and fr.accesi_raster and not vicini, (fr.lavori_raster, len(vicini)))


# casi costruiti apposta: dopo tre righe normali (si entra nel modo raster)…
TESTA = ["G90 G21", "M4 S0", "G0 X100 Y50", "G1 X102 S0 F3500", "X110 S1000", "X112 S0", "G0 Y50.254", "G1 X110",
         "X102 S1000", "X100 S0", "G0 Y50.508", "G1 X102", "X110 S1000", "X112 S0", "G0 Y50.762", "G1 X110",
         "X102 S1000", "X100 S0"]
CODA = ["M5 S0", "G0 X10 Y10"]
casi_apposta = {
    # …una riga più vicina del passo (8 passi dopo la riga a 1999, il passo è 9): la scheda non può scendere di meno
    "riga più vicina del passo della scheda": ["G0 Y50.978", "G1 X102", "X110 S1000", "X112 S0"],
    # …il verso si inverte senza cambio di riga (avanti e indietro sulla stessa riga)
    "inversione sulla stessa riga": ["G1 X104 S0", "X108 S1000", "X100 S0"],
    # …una riga accesa a un'altra velocità
    "riga a un'altra velocità": ["G0 Y51.016", "G1 X102 F1200", "X110 S1000", "X112 S0"],
    # …un tratto acceso in diagonale
    "tratto acceso obliquo": ["G0 Y51.016", "G1 X102", "X110 Y52 S1000", "X112 S0"],
    # …un salto di 5 righe vuote (più dei 15 passi che si fanno in diagonale)
    "salto di molte righe": ["G0 Y52.286", "G1 X102", "X110 S1000", "X112 S0"],
}
for nome, pezzo in casi_apposta.items():
    fn, fr = stessa_cosa(nome, TESTA + pezzo + CODA, raster_atteso=False)
    check(f"{nome}: prima nel modo raster, poi fuori", fr.lavori_raster >= 1 and fr.comandi.count("S1E") >= 2,
          (fr.lavori_raster, fr.comandi.count("S1E")))

# ====================================================================== D. G-code a caso
print("--- D. 300 G-code a caso")


def caso(rng):
    L = ["G90 G21", "M4 S0"]
    pitch = rng.choice([0.1, 0.254, 0.127, 0.0846, 0.2, 0.3, 0.5, 0.05, 0.0254 * rng.randint(1, 12)])
    x0, y, F = rng.uniform(0, 250), rng.uniform(5, 150), rng.choice([600, 1800, 3500, 6000, 12000])
    L += [f"G0 X{x0:.3f} Y{y:.3f}", f"G1 X{x0:.3f} F{F}"]
    x, d = x0, 1
    for _row in range(rng.randint(1, 25)):
        for _k in range(rng.randint(1, 12)):
            if rng.random() < 0.08:
                x = min(max(x + d * rng.uniform(1, 20), 0), 300)
                L += [f"G0 X{x:.3f}", f"G1 F{F}"]
                continue
            x = min(max(x + d * rng.uniform(0.05, 6), 0), 300)
            s = rng.choice([0, 1000])
            L.append(f"G1 X{x:.3f} S{s}" if rng.random() < 0.5 else f"X{x:.3f} S{s}")
        r = rng.random()
        if r < 0.06:
            L += ["M5 S0", "M4 S0"]
        elif r < 0.09:
            L.append(f"G1 X{x:.3f} F{rng.choice([F, 1200])}")
        elif r < 0.11:
            y += pitch
            L.append(f"G1 Y{y:.3f} S1000")
        rows = 1 if rng.random() < 0.8 else rng.randint(2, 6)
        if rng.random() < 0.1:
            rows = -1
        y = min(max(y + pitch * rows, 0), 199)
        if rng.random() < 0.7:
            if rng.random() < 0.5:
                L.append(f"G0 Y{y:.3f}")
            else:
                x = min(max(x + rng.uniform(-15, 15), 0), 300)
                L.append(f"G0 X{x:.3f} Y{y:.3f}")
        else:
            L.append(f"G1 Y{y:.3f} S0")
        if rng.random() < 0.85:
            d = -d
    return L + ["M5 S0", "G0 X10 Y10"]


rng = random.Random(20261125)
diversi, con_raster, colpi_prima, colpi_dopo = [], 0, 0, 0
for i in range(300):
    L = caso(rng)
    fn, _dn = simula(L, False)
    fr, _dr = simula(L, True)
    con_raster += fr.lavori_raster > 0
    colpi_prima += len(fn.colpi)
    colpi_dopo += len(fr.colpi)
    if not uguali(fn, fr) or fr.pericoli:
        diversi.append(i)
check("D stessi punti bruciati e stessa fine in tutti i 300, nessun pericolo", not diversi, diversi[:5])
check("D il modo raster entra in buona parte dei casi e toglie inversioni a piena velocità",
      con_raster > 120 and colpi_dopo < colpi_prima * 0.8, (con_raster, colpi_prima, colpi_dopo))

# ====================================================================== E. il ponte
print("--- E. il ponte con la scheda finta")
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


c = Cliente()
c.cmd("$X")
c.cmd("$H")
c.fermo()
righe = [r for r in lavoro(lambda d: occhio(d, w=30, h=20, dpi=127.0)) if r.split(";")[0].strip()]
righe = [r.split(";")[0].strip() for r in righe]
esiti = [c.cmd(r) for r in righe]
check("E foto mandata al ponte riga per riga: tutte «ok»", all(e == "ok" for e in esiti),
      [e for e in esiti if e != "ok"][:3])
check("E …la scheda finisce e torna ferma", c.fermo(60))
atteso, _d = simula(righe, True)
check("E …la scheda ha bruciato gli stessi punti della traduzione diretta", sorted(c.b.accesi) == sorted(atteso.accesi),
      (len(c.b.accesi), len(atteso.accesi)))
check("E …in modo raster, nessuna inversione a piena velocità, nessun pericolo", c.b.lavori_raster >= 1
      and not c.b.colpi and not c.b.pericoli, (c.b.lavori_raster, len(c.b.colpi), c.b.pericoli[:2]))
# stop a metà di una foto
c2 = Cliente()
c2.cmd("$X")
c2.cmd("$H")
c2.fermo()
for r in righe[:len(righe) // 2]:
    c2.cmd(r)
c2.p.write(b"\x18")
check("E stop a metà della foto: alla scheda arriva «I» e nessun pericolo", until(lambda: "I" in c2.b.comandi[-3:], 5)
      and not c2.b.pericoli, (c2.b.comandi[-3:], c2.b.pericoli[:2]))
c.p.close()
c2.p.close()
os.environ["FLC_K40_RASTER"] = "0"  # per le prove sulla macchina vera: il modo raster si può spegnere
c3 = Cliente()
c3.cmd("$X")
c3.cmd("$H")
c3.fermo()
for r in righe:
    c3.cmd(r)
c3.fermo(60)
check("E FLC_K40_RASTER=0: come la 0.23.1 (nessun lavoro raster, stessi punti bruciati)", c3.b.lavori_raster == 0
      and sorted(c3.b.accesi) == sorted(atteso.accesi), (c3.b.lavori_raster, len(c3.b.accesi)))
del os.environ["FLC_K40_RASTER"]
c3.p.close()

# ====================================================================== F. silenzio
print("--- F. silenzio a metà delle righe tenute da parte")
riga_sola = ["G90 G21", "M4 S0", "G0 X100 Y100", "G1 X102 S0 F3500", "X110 S1000", "X112 S0", "G0 Y100.254",
             "G1 X110", "X104 S1000"]
t = da_gcode.Traduttore(raster=True, piano=(300.0, 200.0))
for r in riga_sola:
    t.riga(r)
check("F righe tenute da parte: «nel lavoro» per il ponte (che dopo un silenzio chiude)", t.in_lavoro()
      and t.sospesi() > 0)
t.chiudi()
con = b"".join(p[1] for p in t.pronti() if p[0] == DATI)
t2 = da_gcode.Traduttore(raster=False, piano=(300.0, 200.0))
for r in riga_sola:
    t2.riga(r)
t2.chiudi()
senza = b"".join(p[1] for p in t2.pronti() if p[0] == DATI)
check("F …chiudendo si manda esattamente quello del lavoro normale", con == senza, (con[:60], senza[:60]))

# ====================================================================== G. passo fra le righe
print("--- G. passo fra le righe")
pd = da_gcode.Traduttore._passo_da
check("G 0,254 mm (10 passi, quasi intero) → 9 (il passo che manca in diagonale)", pd(0.254) == 9)
check("G 0,1 mm (3,94 passi) → 3", pd(0.1) == 3)
check("G 0,2 mm (7,87 passi) → 7", pd(0.2) == 7)
check("G 0,0254 mm (1 passo) → 1", pd(0.0254) == 1)
check("G 0,01 mm (meno di un passo) → 0: niente modo raster", pd(0.01) == 0)

# ====================================================================== H. velocità alte (0.23.2, Ale 21:59)
print("--- H. velocità alte: 250 mm/s")


def flusso(righe, raster=True):
    t = da_gcode.Traduttore(raster=raster, piano=(300.0, 200.0))
    for r in righe:
        t.riga(r)
    t.chiudi()
    return b"".join(p[1] for p in t.pronti() if p[0] == DATI)


linee = ["G90 G21", "M4 S0", "G0 X50 Y50", "G1 X120 Y50 S1000 F15000", "X120 Y90", "X50 Y90", "M5 S0"]
f = flusso(linee)
check("H linee a 250 mm/s: la scheda le riceve a 240, il massimo del modo a linee (MeerK40t non va oltre)",
      ("I" + codice("M2", 240.0)).encode() in f and codice("M2", 250.0).encode() not in f, f[:40])
zig = ["G90 G21", "M4 S0", "G0 X40 Y40", "G1 X42 S0 F15000"]
for i in range(12):
    y = 40 + i * 0.1
    a, b = (42, 98) if i % 2 == 0 else (98, 42)
    zig += [f"G1 X{a} Y{y:.3f} S0", f"G1 X{(a + b) / 2:g} S1000", f"G1 X{b} S0"]
f = flusso(zig)
check("H foto a 250 mm/s: modo raster a 250 (il codice di MeerK40t con la correzione di velocità)",
      ("I" + codice("M2", 250.0, passo_raster=3)).encode() in f and b"S1E" in f, f[:40])
check("H …e lo stesso codice raster di MeerK40t, letto da MeerK40t: V2291473G003",
      codice("M2", 250.0, passo_raster=3) == "V2291473G003", codice("M2", 250.0, passo_raster=3))
k = MachineProfile.k40()
check("H profilo K40: velocità massima 15 000 mm/min (250 mm/s)", k.max_rate_x == k.max_rate_y == 15000.0,
      (k.max_rate_x, k.max_rate_y))

n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
