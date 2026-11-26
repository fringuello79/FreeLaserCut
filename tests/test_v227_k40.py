# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.7 (funzione in prova): la K40 collegata dopo la prima prova di Evo sulla macchina vera
(rapporto FLC-20261124-2055-C71A: lavori lentissimi con la figura sbagliata e posizione persa, frecce, contorno e
joystick a scatti).

A. codici dei lavori: «I» davanti e niente «C» dai 7 mm/s in su (come lo studio, che sulla K40 vera andava), velocità
   minima 7 mm/s.
B. il quadrato di Evo (35 × 35 a 610 mm/min) sulla scheda finta: byte, figura bruciata, tempo, posizione, nessun «I»
   con la testa in moto.
C. frecce: un passo = uno spostamento veloce solo; contorno = uno per angolo; «Continuo» a pezzi e fermato con 0x85;
   joystick: coda corta, la direzione nuova arriva subito; attese di almeno il tempo stimato (la M2 dice «pronta»
   anche con la testa in moto).
D. diario: i byte dei lavori e delle prime frecce.
E. finestra: con la K40 il lavoro finisce dov'è (niente ritorno automatico).
F. difetti rimessi apposta.

Uso: python tests/test_v227_k40.py [classica|banco]
"""
import os
import re
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

from k40_scheda_finta import MIL, SchedaFinta  # noqa: E402

import freelasercut.k40.ponte as P  # noqa: E402
import freelasercut.k40.scrittore as S  # noqa: E402
from freelasercut.k40 import codici as C  # noqa: E402
from freelasercut.k40 import da_gcode  # noqa: E402

UI = os.environ["FLC_UI"]
results = []
K = 0.02


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + f"[{UI}] " + name + (f"  [{info}]" if info != "" and not cond else ""),
          flush=True)


def until(fn, t=10.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.005)
    return bool(fn())


class Diario:
    def __init__(self):
        self.voci = []

    def scrivi(self, evento, **dati):
        self.voci.append(dict(dati, evento=evento))


class Cliente:
    def __init__(self, scheda=None, **kw):
        self.b = scheda or SchedaFinta(scala=K, veloce_mm_s=40.0)
        kw.setdefault("scala_tempo", K)
        self.d = Diario()
        self.p = P.K40Serial(self.b, registra=True, diario=self.d, **kw)
        self.linee = []
        time.sleep(0.1)

    def cmd(self, riga, t=20.0):
        self.p.write((riga + "\n").encode())
        end = time.time() + t
        while time.time() < end:
            r = self.p.readline()
            if r:
                s = r.decode().strip()
                self.linee.append(s)
                if s == "ok" or s.startswith("error") or s.startswith("ALARM"):
                    return s
        return "nessuna risposta"

    def stato(self):
        self.p.write(b"?")
        end = time.time() + 2.0
        while time.time() < end:
            r = self.p.readline()
            if r and r.startswith(b"<"):
                return r.decode().strip()
        return ""

    def mpos(self):
        m = re.search(r"MPos:(-?[\d.]+),(-?[\d.]+)", self.stato())
        return (float(m.group(1)), float(m.group(2))) if m else None

    def fermo(self, t=30.0):
        return until(lambda: self.stato().startswith("<Idle"), t)

    def casa(self):
        r = self.cmd("$H", 30)
        self.fermo()
        return r

    def chiudi(self):
        self.p.close()


QUADRATO = """G90 G21
M5 S0
M9
G54
M4 S0
M8
G0 X56.081 Y68.427
G1 X91.081 S500 F610
Y33.427
X56.081
Y68.427
M5 S0
M9
G54""".splitlines()


# ====================================================================== A. codici
print("--- A. codici")
dati = b"".join(p[1] for p in da_gcode.traduci(QUADRATO)[0] if p[0] == S.DATI)
lav = re.search(rb"I(CV\d+C?)N", dati)
check("A il lavoro entra con «I» + codice (come lo studio)", lav is not None, dati[:60])
check("A …e il codice non ha la «C» (610 mm/min)", lav is not None and not lav.group(1).endswith(b"C"), dati[:60])
check("A codice uguale a quello dello studio a meno della correzione (stessa forma: 18 caratteri, fascia 1)",
      lav is not None and len(lav.group(1)) == 18 and lav.group(1)[8:9] == b"1", lav.group(1) if lav else None)
lento = b"".join(p[1] for p in da_gcode.traduci(["G90", "G0 X10 Y10", "M4 S500", "G1 X20 F60", "M5"])[0]
                 if p[0] == S.DATI)
cl = re.search(rb"I(CV\d+C?)N", lento)
check("A sotto i 7 mm/s (60 mm/min) il lavoro va a 7 mm/s, senza «C»", cl is not None and not cl.group(1).endswith(b"C")
      and abs(C.velocita_vera("M2", cl.group(1).decode()) - 7.0) < 0.15, cl.group(1) if cl else None)
check("A lo spostamento veloce porta la sua attesa stimata (al minimo 0,4 s + strada a 35 mm/s)",
      any(p[0] == S.ATTENDI_FERMA and len(p) == 2 and p[1] > 0.4 for p in da_gcode.traduci(QUADRATO)[0]))
check("A i pacchetti non spezzano l'entrata nel lavoro («I» + codice + … + «S1E» nello stesso pacchetto)",
      any(b"ICV" in pk[1:31] and b"S1E" in pk[1:31] for pk, _ in S.pacchetti_a_parole(dati)))

# ====================================================================== B. il quadrato di Evo
print("--- B. il quadrato di Evo sulla scheda finta")
c = Cliente()
c.casa()
t0 = time.time()
for r in QUADRATO:
    if c.cmd(r) != "ok":
        check(f"B riga accettata: {r}", False)
c.fermo(60)
dur = (time.time() - t0) / K
seg = []
for a, b, cc, d in c.b.accesi:  # i tratti spezzati fra un pacchetto e l'altro si riuniscono
    if seg and seg[-1][2:] == (a, b) and (seg[-1][0] == cc or seg[-1][1] == d):
        seg[-1] = seg[-1][:2] + (cc, d)
    else:
        seg.append((a, b, cc, d))
seg = [(round(a / MIL, 1), round(b / MIL, 1), round(cc / MIL, 1), round(d / MIL, 1)) for a, b, cc, d in seg]
lati = {(56.1, 68.4, 91.1, 68.4), (91.1, 68.4, 91.1, 33.4), (91.1, 33.4, 56.1, 33.4), (56.1, 33.4, 56.1, 68.4)}
check("B bruciati esattamente i 4 lati del quadrato 35 × 35 (nell'ordine del G-code)",
      set(seg) == lati and len(seg) == 4,
      seg)
check("B la testa finisce dove il programma crede (posizione detta = posizione della scheda)",
      c.mpos() is not None and abs(c.mpos()[0] * MIL - c.b.x) <= 1 and abs(c.mpos()[1] * MIL - c.b.y) <= 1,
      (c.mpos(), c.b.x / MIL, c.b.y / MIL))
check("B nessun «I» con la testa in moto, nessun pacchetto perso, nessun pericolo",
      c.b.interrotti == 0 and c.b.persi == 0 and not c.b.pericoli, (c.b.interrotti, c.b.persi, c.b.pericoli))
check("B tempo del lavoro vicino a quello previsto a 10,17 mm/s (140 mm ≈ 14 s, più spostamento e attese)",
      14 <= dur <= 45, round(dur, 1))  # + 0,5 s veri (25 qui) di silenzio prima di chiudere il lavoro
fin = [v for v in c.d.voci if v.get("cosa") == "fine"]
check("D il diario scrive i byte del lavoro (con «I» e il codice)", fin and "ICV" in fin[-1].get("dati", ""),
      fin[-1] if fin else None)
c.chiudi()

# ====================================================================== B2. 0.22.8: pacchetti pieni dentro il lavoro
print("--- B2. pacchetti pieni dentro il lavoro (rapporto 03D4: la «F» di riempimento chiudeva il lavoro)")
from PySide6.QtGui import QTransform  # noqa: E402

from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import Document, EllipseShape  # noqa: E402
from freelasercut.profile import MachineProfile as _MP  # noqa: E402

_doc = Document()
_cer = EllipseShape(30.3, 30.3)
_cer.apply(QTransform.fromTranslate(93.0, 50.3))
_doc.add(_cer)
CERCHIO = gcode.generate(_doc, _MP.k40(), gcode.JobOptions(start_from="absolute", no_g55=True)).lines
dati_c = b"".join(p[1] for p in da_gcode.traduci(CERCHIO)[0] if p[0] == S.DATI)
pk, resto = S.pacchetti_flusso(dati_c)
dentro = []
lav = False
for p in pk:
    corpo = p[1:31]
    for k in range(len(corpo)):
        if corpo[k:k + 3] == b"S1E":
            lav = True
        if corpo[k:k + 4] == b"FNSE":
            lav = False
        if lav and corpo[k:k + 1] == b"F" and corpo[k:k + 4] != b"FNSE":
            dentro.append(corpo)
check("B2 nessuna «F» di riempimento dentro il lavoro (il cerchio di Evo, 131 tratti)", not dentro and resto == b"",
      (dentro[:1], resto[:20]))
pk2, resto2 = S.pacchetti_flusso(b"ICV1620661016001052NBRS1EDBzzzzz103Lzzzzz103Tzz")
spento = True
for p in pk2:
    for b in p[1:31]:
        spento = False if b == 0x44 else True if b == 0x55 else spento
check("B2 a lavoro aperto si manda solo fin dove il laser è spento, il resto aspetta",
      spento and resto2 and all(len(p) == 32 for p in pk2), (len(pk2), resto2))
c = Cliente()
c.casa()
for r in CERCHIO:
    c.cmd(r)
c.fermo(60)
cx, cy = (93.0 + 15.15), (200 - 50.3 - 15.15)
lontani = [((a / MIL - cx) ** 2 + (b / MIL - cy) ** 2) ** 0.5 for a, b, _c, _d in c.b.accesi]
check("B2 il cerchio sulla scheda finta: bruciato tutto sul cerchio (raggio 15,15 ± 0,3 mm), nessun pericolo",
      lontani and all(abs(r - 15.15) < 0.3 for r in lontani) and not c.b.pericoli and "F" not in c.b.comandi,
      (min(lontani or [0]), max(lontani or [0]), c.b.pericoli[:2]))
c.chiudi()

# ====================================================================== C. frecce
print("--- C. frecce, contorno, «Continuo», joystick")
c = Cliente()
c.casa()
n0 = c.b.comandi.count("S1P")
check("C passo 50: ok", c.cmd("$J=G91 G21 X50 F3000") == "ok")
check("C …un solo spostamento veloce, testa a 50 mm, nessun «I» in moto",
      c.fermo() and c.b.comandi.count("S1P") - n0 == 1
      and abs(c.b.x - round(50 * MIL)) <= 1 and c.b.interrotti == 0, (c.b.comandi.count("S1P") - n0, c.b.x / MIL))
fr = [v for v in c.d.voci if v.get("cosa") == "freccia"]
check("D il diario scrive i byte delle prime frecce", fr and fr[-1].get("dati", "").startswith("I")
      and fr[-1]["dati"].endswith("S1P"), fr[-1] if fr else None)
check("C …e aspetta almeno il tempo stimato (la M2 dice «pronta» anche mentre la testa va)",
      fr and fr[-1]["s"] >= fr[-1]["stima"] * K * 0.95, fr[-1] if fr else None)
n0 = c.b.comandi.count("S1P")
for x, y in ((60, 40), (95, 40), (95, 75), (60, 75), (60, 40)):
    c.cmd(f"$J=G53 G21 X{x} Y{y} F6000")
c.fermo()
check("C contorno (5 punti): 5 spostamenti veloci, uno per angolo, testa al punto di partenza",
      c.b.comandi.count("S1P") - n0 == 5 and abs(c.b.x - round(60 * MIL)) <= 1 and abs(c.b.y - round(40 * MIL)) <= 1
      and c.b.interrotti == 0, (c.b.comandi.count("S1P") - n0, c.b.x / MIL, c.b.y / MIL))
c.cmd("$J=G53 G21 X299.5 Y40 F3000")
time.sleep(0.12)
c.p.write(b"\x85")
c.fermo()
m = c.mpos()
check("C «Continuo» fino al bordo fermato con 0x85: la testa si ferma prima, posizione nota",
      m is not None and m[0] < 280 and abs(m[0] * MIL - c.b.x) <= 1 and c.b.interrotti == 0, (m, c.b.x / MIL))
# joystick: pezzetti corti mandati appena arriva l'«ok», poi cambio di direzione
c.cmd("$J=G53 G21 X150 Y100 F6000")
c.fermo()
coda_max = [0]
spia = {"on": True}


def _spia():
    while spia["on"]:
        with c.p._cv:
            coda_max[0] = max(coda_max[0], sum(1 for p in c.p._coda if p[0] == "freccia"))
        time.sleep(0.001)


threading.Thread(target=_spia, daemon=True).start()
for _ in range(15):
    c.cmd("$J=G91 G21 X2.5 F3000")
xa = c.b.x
for _ in range(3):
    c.cmd("$J=G91 G21 Y2.5 F3000")
c.fermo()
spia["on"] = False
check("C joystick: mai più di una freccia in coda (l'«ok» aspetta quelle prima)", coda_max[0] <= 1, coda_max[0])
check("C joystick: cambiando direzione, la Y arriva subito (al più un pezzetto di X dopo)",
      abs(c.b.x - round(187.5 * MIL)) <= 2 and abs(c.b.y - round(107.5 * MIL)) <= 2
      and (c.b.x - xa) <= round(2.5 * MIL) + 1, (c.b.x / MIL, c.b.y / MIL, (c.b.x - xa) / MIL))
check("C nessun pericolo, nessun «I» in moto in tutte le frecce", not c.b.pericoli and c.b.interrotti == 0,
      (c.b.pericoli, c.b.interrotti))
c.chiudi()

# ====================================================================== E. finestra
print("--- E. finestra")
from freelasercut.grbl import K40_PORT  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.laser.finish_origin.setChecked(True)
check("E laser normale con «torna all'origine»: il lavoro torna", w.job_options().finish == "origin")
w.on_profile(MachineProfile.k40())
check("E 0.23.3: con il profilo K40 il lavoro torna anche lui (Evo: «non torna all'inizio anche se è abilitato»)",
      w.job_options().finish == "origin")
w.laser.finish_origin.setChecked(False)
check("E …e se il ritorno è spento resta dov'è", w.job_options().finish == "stay")
w.laser.finish_origin.setChecked(True)
check("E (la porta K40 vale anche da sola)", K40_PORT == "K40")
w.close()

# ====================================================================== F. difetti rimessi apposta
print("--- F. difetti rimessi apposta")


def con_difetto(nome, fn):
    try:
        return fn()
    except Exception as ex:  # noqa: BLE001 — un difetto che rompe è comunque visto
        return f"eccezione {type(ex).__name__}"


visti = 0
# 1. senza la «I» davanti al codice
vero_inizia = S.Scrittore.inizia_lavoro


def _senza_i(self, v, vx=1, vy=1):
    vero_inizia(self, v, vx, vy)
    i = self._buf.rfind(b"ICV")
    if i >= 0:
        del self._buf[i:i + 1]


S.Scrittore.inizia_lavoro = _senza_i
d1 = b"".join(p[1] for p in da_gcode.traduci(QUADRATO)[0] if p[0] == S.DATI)
S.Scrittore.inizia_lavoro = vero_inizia
visti += re.search(rb"I(CV\d+C?)N", d1) is None
# 2. con la «C» come nella 0.22.6
d2 = b"".join(p[1] for p in da_gcode.traduci(QUADRATO, senza_giri=True)[0] if p[0] == S.DATI)
m2 = re.search(rb"I(CV\d+C?)N", d2)
visti += m2 is not None and m2.group(1).endswith(b"C")
# 3. attesa dopo lo spostamento veloce senza il tempo minimo
vero_af = P.K40Serial._attendi_ferma
P.K40Serial._attendi_ferma = lambda self, st, mx, gen, minimo=2.0: vero_af(self, st, mx, gen, minimo=0.0)
c = Cliente()
c.casa()
for x, y in ((60, 40), (200, 40), (200, 150), (60, 150)):
    c.cmd(f"$J=G53 G21 X{x} Y{y} F6000")
c.fermo()
P.K40Serial._attendi_ferma = vero_af
visti += c.b.interrotti > 0
c.chiudi()
# 4. l'«ok» delle frecce subito (senza aspettare quelle prima)
vero_cv_wait = None
c = Cliente()
c.casa()
c.cmd("$J=G53 G21 X150 Y100 F6000")
c.fermo()
_coda = [0]
_on = {"on": True}


def _spia2():
    while _on["on"]:
        with c.p._cv:
            _coda[0] = max(_coda[0], sum(1 for p in c.p._coda if p[0] == "freccia"))
        time.sleep(0.001)


threading.Thread(target=_spia2, daemon=True).start()
vero_freccia = P.K40Serial._freccia


def _freccia_subito(self, testo):  # come la 0.22.6: niente attesa delle frecce prima
    with self._cv:
        salvata = list(self._coda)
        self._coda.clear()
    try:
        return vero_freccia(self, testo)
    finally:
        with self._cv:
            nuove = list(self._coda)
            self._coda.clear()
            self._coda.extend(salvata + nuove)
            self._cv.notify_all()


P.K40Serial._freccia = _freccia_subito
for _ in range(15):
    c.cmd("$J=G91 G21 X2.5 F3000")
c.fermo()
P.K40Serial._freccia = vero_freccia
_on["on"] = False
visti += _coda[0] > 1
c.chiudi()
# 5. «Continuo» non riconosciuto (tutto in un pezzo): 0x85 non ferma
vero_cont = P.K40Serial._continuo
P.K40Serial._continuo = lambda self, *a: False
c = Cliente()
c.casa()
c.cmd("$J=G53 G21 X299.5 Y40 F3000")
time.sleep(0.12)
c.p.write(b"\x85")
c.fermo()
P.K40Serial._continuo = vero_cont
visti += c.b.x / MIL > 290
c.chiudi()
# 6. pacchetti riempiti di «F» dentro il lavoro (come la 0.22.6)
vero_flusso = P.pacchetti_flusso
P.pacchetti_flusso = lambda testo: ([pk for pk, _ in S.pacchetti_a_parole(testo)], b"")
c = Cliente()
c.casa()
for r in QUADRATO:
    c.cmd(r)
c.fermo(60)
P.pacchetti_flusso = vero_flusso
visti += any("riempimento" in x for x in c.b.pericoli)
c.chiudi()
check("F 6 difetti rimessi apposta (senza «I», con la «C», attesa senza tempo minimo, «ok» subito sulle frecce, "
      "«Continuo» in un pezzo, «F» dentro il lavoro): tutti visti", visti == 6, visti)

print()
print(f"{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
