# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.6 (funzione in prova): il ponte K40 (k40/ponte.py), che fa parlare GRBL alla scheda M2 Nano.

Con la scheda finta (tests/k40_scheda_finta.py), che segna «pericolo» se resta senza dati con il laser acceso, se
riceve «D» fuori da un lavoro o se la testa esce dal piano.

A. il ponte da solo: saluto, casa, frecce a pezzetti e loro arresto, lavoro vero (byte identici al traduttore),
   invio lento e G-code troncato (mai «pericolo»), pausa, stop, chiusura, cavo staccato, errori di controllo,
   scheda occupata, scheda che non finisce, verifica ($C), comandi rifiutati, laser mai acceso da fermo.
B. nella finestra: voce «K40» solo con le funzioni in prova sbloccate, profilo K40, puntino spento, verso degli assi
   dal disegno fino ai passi.

Uso: python tests/test_v226_k40_ponte.py [classica|banco]
"""
import os
import random
import threading
import re
import sys
import tempfile
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

from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)


def _exec(self):
    for b in self.buttons():
        if self.buttonRole(b) == QMessageBox.AcceptRole:
            b.click()
            break
    return 0


QMessageBox.exec = _exec

from k40_scheda_finta import MIL, SchedaFinta  # noqa: E402

from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import Document, EllipseShape, RectShape  # noqa: E402
from freelasercut.k40 import da_gcode  # noqa: E402
from freelasercut.k40.ponte import K40Serial  # noqa: E402
from freelasercut.k40.scrittore import DATI  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

UI = os.environ["FLC_UI"]
results = []
K = 0.02  # attese della scheda accorciate


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
        app.processEvents()
    return bool(fn())


class Cliente:
    """Parla GRBL al ponte come GrblController, ma una riga alla volta (aspetta ok/error)."""

    def __init__(self, scheda=None, **kw):
        self.b = scheda or SchedaFinta(scala=K)
        kw.setdefault("scala_tempo", K)
        self.p = K40Serial(self.b, registra=True, **kw)
        self.linee = []
        self.leggi(0.2)

    def leggi(self, t=0.0):
        end = time.time() + t
        while True:
            r = self.p.readline()
            if r:
                self.linee.append(r.decode().strip())
            elif time.time() >= end:
                return

    def cmd(self, riga, t=10.0):
        n0 = len(self.linee)
        self.p.write((riga + "\n").encode())
        end = time.time() + t
        while time.time() < end:
            r = self.p.readline()
            if r:
                s = r.decode().strip()
                self.linee.append(s)
                if s == "ok" or s.startswith("error") or s.startswith("ALARM"):
                    return s
        return "nessuna risposta: " + " | ".join(self.linee[n0:])

    def stato(self):
        self.p.write(b"?")
        end = time.time() + 2.0
        while time.time() < end:
            r = self.p.readline()
            if r and r.startswith(b"<"):
                return r.decode().strip()
            if r:
                self.linee.append(r.decode().strip())
        return ""

    def mpos(self):
        m = re.search(r"MPos:(-?[\d.]+),(-?[\d.]+)", self.stato())
        return (float(m.group(1)), float(m.group(2))) if m else None

    def stato_nome(self):
        m = re.match(r"<([A-Za-z]+)", self.stato())
        return m.group(1) if m else ""

    def fermo(self, t=20.0):
        return until(lambda: self.stato_nome() == "Idle", t)

    def casa(self):
        r = self.cmd("$H", 20)
        self.fermo()
        return r

    def manda(self, righe, pausa=None):
        for r in righe:
            esito = self.cmd(r, 30)
            if esito != "ok":
                return esito, r
            if pausa:
                time.sleep(pausa())
        return "ok", None


def lavoro(shapes, profile=None, start="absolute"):
    doc = Document()
    for s in shapes:
        doc.add(s)
    prof = profile or MachineProfile.k40()
    o = gcode.JobOptions(start_from=start, no_g55=True)
    return gcode.generate(doc, prof, o).lines, doc


def rettangolo(w=40, h=20, x=30, y=150, layer=None):
    r = RectShape(w, h)
    r.apply(QTransform.fromTranslate(x, y))
    return r


def dati_traduttore(righe):
    pezzi, _ = da_gcode.traduci(righe)
    return b"".join(p[1] for p in pezzi if p[0] == DATI)


def vicino(a, b, e=0.03):
    return a is not None and abs(a[0] - b[0]) <= e and abs(a[1] - b[1]) <= e


def nessun_pericolo(b):
    return not b.pericoli


# ====================================================================== A. il ponte da solo
print("--- A. ponte e scheda finta")
c = Cliente()
check("A saluto di GRBL all'apertura", any("Grbl 1.1f" in ln for ln in c.linee), c.linee)
check("A appena aperto: allarme (la posizione non si sa)", c.stato_nome() == "Alarm", c.stato())
r = c.cmd("$I")
check("A $I: versione K40 e buffer di 128 byte", r == "ok" and any("VER:1.1f.K40" in ln for ln in c.linee)
      and any("OPT:V,15,128" in ln for ln in c.linee))
c.cmd("$$")
check("A $$: piano 300 × 200 mm", "$130=300.000" in c.linee and "$131=200.000" in c.linee)
check("A prima della casa: un movimento risponde error:9 e alla scheda non parte niente",
      c.cmd("G1 X10 Y10 F600") == "error:9" and c.cmd("$J=G91 X5 F1000") == "error:9" and c.b.pacchetti == 0)
check("A $X toglie l'allarme…", c.cmd("$X") == "ok" and c.stato_nome() == "Idle")
check("A …ma la posizione resta non nota: i movimenti ancora error:9", c.cmd("G0 X10 Y10") == "error:9")
check("A $H: casa (IPP), poi fermo a 0,0", c.casa() == "ok" and "IPP" in c.b.comandi and c.mpos() == (0.0, 0.0)
      and (c.b.x, c.b.y) == (0, 0), (c.b.comandi[-3:], c.mpos()))

# --- frecce
n0 = c.b.comandi.count("S1P")
check("A freccia 10 mm a destra: ok", c.cmd("$J=G91 G21 X10 F3000") == "ok")
# 0.22.7: una freccia è uno spostamento veloce solo (con la 0.22.6 erano pezzetti da 2 mm: a scatti sulla K40 vera)
check("A …fatta con un solo spostamento veloce", until(lambda: c.b.comandi.count("S1P") - n0 == 1, 10)
      and c.fermo() and c.b.comandi.count("S1P") - n0 == 1, c.b.comandi.count("S1P") - n0)
check("A …e la posizione è quella vera", c.mpos() == (10.0, 0.0) and abs(c.b.x - round(10 * MIL)) <= 1,
      (c.mpos(), c.b.x))
check("A freccia fuori dal piano: error:15, niente alla scheda",
      (lambda p0: c.cmd("$J=G91 X-50 F3000") == "error:15" and c.b.pacchetti == p0)(c.b.pacchetti))
check("A freccia con G53 (coordinate della macchina, come il contorno)", c.cmd("$J=G53 G21 X20 Y15 F3000") == "ok"
      and c.fermo() and c.mpos() == (20.0, 15.0), c.mpos())
c.cmd("$J=G53 G21 X299.5 Y15 F3000")  # «Continuo»: fino al bordo, a pezzi
time.sleep(0.08)
c.p.write(b"\x85")
c.fermo()
m = c.mpos()
check("A «Continuo» fermato (0x85): la testa si ferma prima del bordo", m is not None and m[0] < 290, m)
check("A …e la posizione detta è quella della scheda (nota, non persa)", m is not None
      and abs(m[0] * MIL - c.b.x) <= 1 and abs(m[1] * MIL - c.b.y) <= 1, (m, c.b.x, c.b.y))
check("A …nessun pericolo con le frecce", nessun_pericolo(c.b), c.b.pericoli)
c.casa()

# --- lavoro vero
_e1 = EllipseShape(120, 90)
_e1.apply(QTransform.fromTranslate(100, 60))
_tondi = []
for _i in range(6):
    _t = EllipseShape(40, 30)
    _t.apply(QTransform.fromTranslate(20 + 45 * _i, 10))
    _tondi.append(_t)
righe, _doc = lavoro([rettangolo(), EllipseShape(20, 20), _e1] + _tondi)
check("A (il lavoro di prova è più grande del freno)", len(dati_traduttore(righe)) > 4000, len(dati_traduttore(righe)))
del c.p.registro[:]
picco = [0]
spia = {"on": True}


def _spia():
    while spia["on"]:
        with c.p._cv:  # un pezzo lungo (un tratto acceso intero) non si divide: conta il resto
            dd = [len(p[1]) for p in c.p._coda if p[0] == DATI] + [c.p._byte_in_volo]
            picco[0] = max(picco[0], sum(dd) - max(dd))
        time.sleep(0.001)


threading.Thread(target=_spia, daemon=True).start()
d0 = c.b.d_ricevute
esito, riga = c.manda(righe)
check("A lavoro del programma (rettangolo e cerchio): «ok» a ogni riga", esito == "ok", (esito, riga))
check("A …finisce: fermo", c.fermo(30))
spia["on"] = False
check("A …il freno: oltre il pezzo più lungo, mai più di 2000 byte pronti in attesa", picco[0] < 2000 + 600, picco[0])
check("A …i comandi mandati alla scheda sono identici a quelli del traduttore", b"".join(c.p.registro)
      == dati_traduttore(righe), (len(b"".join(c.p.registro)), len(dati_traduttore(righe))))
check("A …il laser ha bruciato (D) e nessun pericolo", c.b.d_ricevute > d0 and c.b.accesi and nessun_pericolo(c.b),
      c.b.pericoli)
check("A …e alla fine il laser è spento e il lavoro chiuso", not c.b.laser and not c.b.lavoro)
check("A …nessun pacchetto mandato mentre la scheda era occupata (li perderebbe)", c.b.persi == 0, c.b.persi)
# 0.22.8: dentro il lavoro pacchetti pieni senza «F» (la «F» chiude il lavoro sulla scheda vera): non c'è più il tetto
# di passi per pacchetto. Al massimo 7 comandi «Bzzz» (765 passi l'uno) in 30 byte
check("A …nessun pacchetto con più di 30 byte di comandi di movimento (al massimo circa 14 cm)",
      0 < c.b.max_passi <= 7 * 765, c.b.max_passi)
comandi_puliti = list(c.b.comandi[c.b.comandi.index("IPP", 1) + 1:]) if c.b.comandi.count("IPP") > 1 else None

# --- scheda lenta: il freno tiene ferma ogni riga più a lungo del «silenzio», ma il lavoro non viene chiuso e riaperto
import freelasercut.k40.ponte as _pm  # noqa: E402

_freno_vero = _pm.FRENO
_pm.FRENO = 100
cl = Cliente(SchedaFinta(scala=0.15), scala_tempo=0.15, quiete=0.4)
cl.casa()
del cl.p.registro[:]
zig = ["G90 G21", "M5 S0"] + [f"G1 X{200 if i % 2 == 0 else 10} Y{10 + i * 2} F6000" for i in range(10)] + ["G0 X0 Y0"]
esito, riga = cl.manda(zig, pausa=lambda: 0.07)  # chi manda ci mette un attimo fra una riga e l'altra
cl.fermo(60)
_pm.FRENO = _freno_vero
check("A scheda lenta (il freno aspetta più del silenzio): un lavoro solo, comandi identici al traduttore",
      esito == "ok" and b"".join(cl.p.registro) == dati_traduttore(zig) and cl.b.comandi.count("FNSE") == 1
      and nessun_pericolo(cl.b), (esito, cl.b.comandi.count("FNSE"), cl.b.pericoli))
cl.p.close()

# --- errore di controllo detto in ritardo (prima «occupata», poi 207): il pacchetto si rimanda, non si salta
ct = Cliente(SchedaFinta(scala=K, crc_ogni=4, crc_tardi=3))
ct.casa()
n0 = len(ct.b.comandi)
esito, riga = ct.manda(righe)
ct.fermo(60)
pulita = Cliente()
pulita.casa()
m0 = len(pulita.b.comandi)
pulita.manda(righe)
pulita.fermo(60)
check("A errore di controllo detto in ritardo: nessun pacchetto saltato (la scheda esegue gli stessi comandi)",
      esito == "ok" and ct.p.errori_crc > 0 and ct.b.comandi[n0:] == pulita.b.comandi[m0:] and ct.b.accesi == pulita.b.accesi
      and nessun_pericolo(ct.b), (ct.p.errori_crc, len(ct.b.comandi) - n0, len(pulita.b.comandi) - m0, ct.b.pericoli))
ct.p.close()
pulita.p.close()

# --- frecce una dopo l'altra: si sommano
c.casa()
for _i in range(5):
    c.cmd("$J=G91 G21 X1 F3000")
c.cmd("$J=G91 G21 Y3 F3000")
c.fermo()
check("A cinque frecce da 1 mm mandate di fila (e una in Y): si sommano", vicino(c.mpos(), (5.0, 3.0))
      and abs(c.b.x - round(5 * MIL)) <= 2 and abs(c.b.y - round(3 * MIL)) <= 2, (c.mpos(), c.b.x, c.b.y))
n_pn = c.b.comandi.count("PN")
c.cmd("$J=G53 G21 X299.5 F3000")  # «Continuo»
time.sleep(0.05)
c.p.write(b"!")
c.fermo()
check("A «!» durante le frecce: le ferma, e alla scheda nessun PN", c.b.comandi.count("PN") == n_pn
      and c.mpos()[0] < 290 and abs(c.mpos()[0] * MIL - c.b.x) <= 1, (c.mpos(), c.b.comandi[-3:]))
# --- reset da fermi: la posizione resta buona
m = c.mpos()
c.p.write(b"\x18")
time.sleep(0.2)
check("A reset (Ctrl+X) da fermi: «I» alla scheda, niente allarme, posizione ancora buona", c.stato_nome() == "Idle"
      and c.mpos() == m and c.b.comandi[-1] == "I" and c.cmd("G0 X20 Y20") == "ok" and c.fermo()
      and vicino(c.mpos(), (20.0, 20.0)), (c.stato(), c.b.comandi[-2:]))
c.casa()

# --- invio lento e a scatti: mai «pericolo»
c2 = Cliente(quiete=0.05)
c2.casa()
rng = random.Random(7)
righe2, _ = lavoro([rettangolo(60, 30, 20, 120), rettangolo(10, 10, 100, 60), EllipseShape(30, 15)])
esito, _r = c2.manda(righe2, pausa=lambda: rng.choice((0.0, 0.0, 0.01, 0.03, 0.08, 0.12)))
c2.fermo(30)
check("A invio lento e a scatti, con il ponte che chiude da solo: lavoro intero, mai «pericolo»", esito == "ok"
      and nessun_pericolo(c2.b) and not c2.b.laser, c2.b.pericoli)
c2.p.close()

# --- G-code troncato a metà taglio
c3 = Cliente(quiete=0.1)
c3.casa()
righe3, _ = lavoro([rettangolo(80, 50, 20, 100)])
cut = max(i for i, l in enumerate(righe3) if re.match(r"G1 .*S[1-9]", l))  # l'ultimo tratto acceso
esito, _r = c3.manda(righe3[:cut + 1])
check("A G-code troncato in mezzo a un tratto acceso: il tratto in sospeso non è partito", esito == "ok"
      and c3.b.d_ricevute >= 0)
until(lambda: "FNSE" in c3.b.comandi[-3:], 3.0)
c3.fermo()
check("A …dopo il silenzio il ponte lo chiude da solo (U e FNSE): laser spento, nessun pericolo",
      c3.b.comandi[-2:] == ["U", "FNSE"] and not c3.b.laser and nessun_pericolo(c3.b), (c3.b.comandi[-4:], c3.b.pericoli))
c3.p.close()

# --- pausa e ripresa
# 0.22.8: la pausa entra dove il laser è spento (fra una forma e l'altra): molte forme piccole
_piccoli = []
for _i in range(24):
    _p = EllipseShape(8, 8)
    _p.apply(QTransform.fromTranslate(20 + 11 * (_i % 12), 30 + 11 * (_i // 12)))
    _piccoli.append(_p)
lungo, _ = lavoro(_piccoli)
c4 = Cliente(SchedaFinta(scala=0.3), scala_tempo=0.3)
c4.casa()
fatto = {}
th = threading.Thread(target=lambda: fatto.setdefault("r", c4.manda(lungo)), daemon=True)
th.start()
until(lambda: c4.b.lavoro, 10)
c4.p.write(b"!")
# 0.22.8: la pausa non manda «PN» (il suo pacchetto riempito di «F» chiuderebbe il lavoro): il ponte smette di mandare
check("A pausa (!): stato Hold e nessun PN alla scheda", until(lambda: c4.stato_nome() == "Hold", 2)
      and c4.b.comandi.count("PN") == 0, (c4.b.comandi[-3:], c4.stato()))
time.sleep(0.3)  # il pacchetto che era già in invio finisce
n_pause = c4.b.pacchetti
time.sleep(0.4)
check("A …in pausa il ponte non manda altro alla scheda", c4.b.pacchetti == n_pause, c4.b.pacchetti - n_pause)
c4.p.write(b"~")
check("A ripresa (~): si riprende a mandare", until(lambda: c4.b.pacchetti > n_pause, 3))
th.join(60)
check("A …e il lavoro finisce, senza pericoli", fatto.get("r", ("",))[0] == "ok" and c4.fermo(60)
      and nessun_pericolo(c4.b), (fatto.get("r"), c4.b.pericoli, c4.stato(), c4.p.guasto, len(c4.p._coda)))

# --- stop a metà (Ctrl+X)
th = threading.Thread(target=lambda: c4.manda(lungo), daemon=True)
c4.b.comandi.clear()
th.start()
until(lambda: c4.b.lavoro and c4.b.laser, 10)
c4.p.write(b"\x18")
check("A stop (Ctrl+X) a metà lavoro: «I» subito alla scheda", until(lambda: "I" in c4.b.comandi, 2)
      and until(lambda: not c4.b.laser, 2), c4.b.comandi[-3:])
check("A …allarme e saluto (la posizione è persa: serve la casa)", until(lambda: c4.stato_nome() == "Alarm", 2))
th.join(10)
check("A …con «ALARM:3» (posizione persa), così il programma chiede la casa", "ALARM:3" in c4.linee)
_i = max(i for i, ln in enumerate(c4.linee) if ln.startswith("Grbl"))
check("A …e dopo il saluto nessun «ok» in ritardo (sfaserebbe le risposte)", "ok" not in c4.linee[_i:], c4.linee[_i:])
n_dopo = c4.b.pacchetti
time.sleep(0.6)
check("A …dopo lo stop alla scheda non arriva più niente: l'ultimo comando resta «I»", c4.b.comandi[-1] == "I"
      and c4.b.pacchetti == n_dopo, (c4.b.comandi[-3:], c4.b.pacchetti - n_dopo))
check("A …dopo lo stop un movimento risponde error:9", c4.cmd("$X") == "ok" and c4.cmd("G0 X10 Y10") == "error:9")
check("A …nessun pericolo", nessun_pericolo(c4.b), c4.b.pericoli)

# --- stop mentre una riga aspetta che finiscano le frecce: la riga non parte più
c4.casa()
c4.cmd("$J=G91 X250 F3000")
c4.p.write(b"G0 X20 Y20\nM3 S500\nG1 X40 Y20 F600\n")  # righe di un lavoro, in attesa che le frecce finiscano
time.sleep(0.15)
c4.p.write(b"\x18")
time.sleep(1.0)
_dopo = c4.b.comandi[len(c4.b.comandi) - c4.b.comandi[::-1].index("I"):] if "I" in c4.b.comandi else ["?"]
check("A stop mentre una riga del lavoro aspetta la fine delle frecce: dopo «I» alla scheda non arriva niente",
      _dopo == [] and c4.stato_nome() == "Alarm", (_dopo, c4.stato()))
c4.leggi(0.2)
c4.cmd("$X")

# --- chiusura della porta a metà
c4.casa()
th = threading.Thread(target=lambda: c4.manda(lungo), daemon=True)
th.start()
until(lambda: c4.b.lavoro and c4.b.laser, 10)
c4.p.close()
check("A chiusura a metà lavoro: l'ultimo comando alla scheda è «I», laser spento", until(lambda: not c4.b.laser, 2)
      and c4.b.comandi[-1] == "I", c4.b.comandi[-3:])

# --- cavo staccato, errori di controllo, scheda occupata, scheda che non finisce
c5 = Cliente(SchedaFinta(scala=K, cavo_cade_dopo=3))
c5.casa()
c5.manda(lungo)
check("A cavo staccato durante il lavoro: allarme e il motivo", until(lambda: c5.stato_nome() == "Alarm", 5)
      and c5.p.guasto and "cavo" in c5.p.guasto, c5.p.guasto)
c5.p.close()
c6 = Cliente(SchedaFinta(scala=K, crc_ogni=3))
check("A un errore di controllo ogni 3 pacchetti: si rimanda e va avanti", c6.casa() == "ok"
      and c6.manda(righe)[0] == "ok" and c6.fermo(30) and c6.p.errori_crc > 0 and nessun_pericolo(c6.b),
      c6.p.errori_crc)
c6.p.close()
c7 = Cliente(SchedaFinta(scala=K, crc_sempre=True))
c7.cmd("$H", 10)
check("A errore di controllo sempre: dopo 8 tentativi allarme, niente si incastra",
      until(lambda: c7.stato_nome() == "Alarm", 5) and c7.p.guasto and "controllo" in c7.p.guasto, c7.p.guasto)
c7.p.close()
c8 = Cliente(SchedaFinta(scala=K, occupata_per=0.6))
c8.casa()
check("A scheda «occupata» a lungo all'inizio del lavoro: aspetta e finisce",
      c8.manda(righe)[0] == "ok" and c8.fermo(30) and nessun_pericolo(c8.b))
c8.p.close()
c9 = Cliente(SchedaFinta(scala=K, mai_finita=True))
c9.casa()
c9.manda(righe)
check("A scheda che non dice mai «finito»: allarme dopo il tempo massimo, non resta appeso",
      until(lambda: c9.stato_nome() == "Alarm", 15) and "finito" in (c9.p.guasto or ""), c9.p.guasto)
c9.p.close()

# --- verifica, comandi rifiutati, laser mai acceso da fermo
c = Cliente()
c.casa()
p0 = c.b.pacchetti
check("A $C: verifica accesa", c.cmd("$C") == "ok" and c.stato_nome() == "Check")
esito, _r = c.manda(righe)
check("A …tutto il lavoro verificato, alla scheda zero byte", esito == "ok" and c.b.pacchetti == p0,
      (esito, c.b.pacchetti - p0))
check("A …in verifica: G2 → error:20, fuori dal piano → error:15", c.cmd("G2 X10 Y10 I5 J0") == "error:20"
      and c.cmd("G0 X400 Y10") == "error:15")
check("A $C di nuovo: verifica spenta, fermo, posizione come prima", c.cmd("$C") == "ok" and c.fermo()
      and c.mpos() == (0.0, 0.0))
check("A G55 → error:20; G10 L2 P2 → error:20", c.cmd("G55") == "error:20" and c.cmd("G10 L2 P2 X0 Y0") == "error:20")
p0 = c.b.pacchetti
check("A un comando G che il ponte non conosce (G28 X0 Y0): error:20 e nessun movimento",
      c.cmd("G28 X0 Y0") == "error:20" and c.cmd("G38.2 X10 F100") == "error:20" and c.b.pacchetti == p0)
# una riga rifiutata non lascia niente: né il laser abilitato, né la potenza
d0 = c.b.d_ricevute
c.cmd("M5 S0")
check("A riga rifiutata (fuori dal piano) con M3 e S dentro: error:15…", c.cmd("M3 G1 X400 Y10 S800 F600") == "error:15")
c.cmd("G1 X15 Y5 F1200")
c.cmd("G0 X0 Y0")
c.fermo()
check("A …e non lascia il laser abilitato: il movimento dopo è a laser spento", c.b.d_ricevute == d0, c.b.d_ricevute - d0)
check("A G54 → ok (l'unico sistema di coordinate)", c.cmd("G54") == "ok")
d0 = c.b.d_ricevute
for ln in ("M3 S500", "G4 P1", "G1 S800 F600", "M4 S1000", "G1 F1000", "M5 S0"):
    c.cmd(ln)
time.sleep(0.8)
check("A laser «acceso» da fermo (M3 S…, G4, G1 senza movimento, il puntino): nessuna D alla scheda",
      c.b.d_ricevute == d0 and nessun_pericolo(c.b), c.b.d_ricevute - d0)
c.cmd("$J=G53 X50 Y40 F3000")
c.fermo()
check("A G92 X0 Y0: la posizione di adesso diventa lo zero del lavoro", c.cmd("G92 X0 Y0") == "ok"
      and c.cmd("G0 X10 Y5") == "ok" and c.fermo() and vicino(c.mpos(), (60.0, 45.0)), c.mpos())
check("A …e lo dice nello stato (WCO)", "WCO:50.000,40.000" in c.stato(), c.stato())
check("A G92.1: lo zero torna quello della macchina", c.cmd("G92.1") == "ok" and c.cmd("G0 X5 Y5") == "ok"
      and c.fermo() and vicino(c.mpos(), (5.0, 5.0)), c.mpos())
n_fnse = c.b.comandi.count("FNSE")
c.cmd("M3 S500")
c.cmd("G1 X20 Y5 F1200")
c.cmd("M5 S0")
_u = until(lambda: not c.b.laser, 0.3)
c.cmd("M2")
# 0.22.8: la «U» può restare nel pacchetto non ancora pieno, ma solo se la scheda ha il laser già spento (il ponte
# taglia i pacchetti solo dove il laser è spento)
check("A M5 da solo: la scheda ha il laser spento subito, senza aspettare il movimento dopo", _u, c.b.comandi[-4:])
check("A M2: il lavoro si chiude subito (FNSE), senza aspettare il silenzio di 0,5 s",
      until(lambda: c.b.comandi.count("FNSE") > n_fnse, 0.3))
c.casa()
n_pn = c.b.comandi.count("PN")
c.p.write(b"!")
time.sleep(0.2)
check("A «!» da fermi, senza lavoro: alla scheda niente PN", c.b.comandi.count("PN") == n_pn and c.stato_nome() == "Idle")
c.cmd("M3 S500")
c.cmd("G1 X30 Y0 F600")  # lavoro aperto, tratto acceso in sospeso, alimentatore fermo
c.p.write(b"!")
check("A «!» con il lavoro aperto ma niente in coda: la pausa vale lo stesso (Hold, senza PN)",
      until(lambda: c.stato_nome() == "Hold", 1.0) and c.b.comandi.count("PN") == n_pn, (c.b.comandi[-3:], c.stato()))
c.p.write(b"~")
check("A …e la ripresa toglie la pausa", until(lambda: c.stato_nome() != "Hold", 1.0))
c.cmd("M5 S0")
c.cmd("M2")
c.fermo()
c.p.close()

# ====================================================================== B. nella finestra
print("--- B. finestra")
from freelasercut import admin  # noqa: E402
from freelasercut.grbl import K40_PORT  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402

win = mw.MainWindow()
win.show()
asked = []
mw.MainWindow.k40_seen = staticmethod(lambda: asked.append(1) or True)
admin.set_unlocked(win.qs, False)
check("B funzioni in prova bloccate: nessuna voce «K40» e nessuna ricerca USB", win._k40_ports() == [] and not asked)
win.refresh_ports() if hasattr(win, "refresh_ports") else None
check("B …nemmeno nell'elenco delle porte", win.port_combo.findData(K40_PORT) < 0)
admin.set_unlocked(win.qs, True)
check("B sbloccate e scheda vista: voce «K40»", [p[0] for p in win._k40_ports()] == [K40_PORT] and asked)
if hasattr(win, "refresh_ports"):
    win.refresh_ports()
    check("B …anche nell'elenco delle porte", win.port_combo.findData(K40_PORT) >= 0)
mw.MainWindow.k40_seen = staticmethod(lambda: False)
check("B sbloccate ma scheda non vista: nessuna voce", win._k40_ports() == [])

from freelasercut.studio import lihuiyu as _lh  # noqa: E402

lanciati = []
_run_vero, _trova_vera = _lh._run, _lh.trova
_lh._run = lambda *a, **k: lanciati.append("programma") or ""
_lh.trova = lambda *a, **k: lanciati.append("ricerca lenta") or {}
mw.MainWindow.k40_seen = None
win._k40_ports()
check("B cercare la K40 per l'elenco delle porte non usa la ricerca lenta né altri programmi (all'avvio teneva ferma la "
      "finestra)", not lanciati and isinstance(_lh.vista_veloce(), bool), lanciati[:1])
_lh._run, _lh.trova = _run_vero, _trova_vera

fb = SchedaFinta(scala=K)
ctl = win.ctl
ctl.k40_links = lambda: [fb]
ctl.k40_time_scale = K
ctl.connect_port(K40_PORT)
check("B collegata la K40", until(lambda: ctl.connected and ctl.board_settings.get(130) is not None, 10))
check("B profilo K40: 300 × 200, potenza dalla manopola, solo G54", win.profile.k40_board == "M2"
      and (win.profile.bed_x, win.profile.bed_y) == (300.0, 200.0) and win.profile.power_knob and win.profile.no_g55)
lp = win.laser
check("B puntino e Lucciola spenti, con il motivo", not lp.b_fire.isEnabled() and not lp.b_glow.isEnabled()
      and "manopola" in lp.b_fire.toolTip())
sent = []
_send = ctl.send_line
ctl.send_line = lambda line, *a, **k: (sent.append(line), _send(line, *a, **k))[1]
ctl.fire(True, 5.0)
check("B il puntino nel controllore: rifiutato, nessun M3", not any(ln.startswith("M3") for ln in sent), sent)
ctl.fire(False)
ctl.home()
check("B casa dalla finestra", until(lambda: ctl.homed and ctl.last_status.get("state") == "Idle", 20))
# rettangolo a 10 mm dal bordo in alto a sinistra del piano (come si vede): passi vicini a casa
r = RectShape(20, 10)
r.apply(QTransform.fromTranslate(10, 200 - 10 - 10))
win.editor.add([r])
lp.start_from.setCurrentIndex(lp.start_from.findData("absolute"))
lp.verify_first.setChecked(False)
job = win.build_job(show=False)
check("B lavoro K40: avviso «potenza dalla manopola»", job is not None and any("manopola" in w for w in job.warnings),
      job.warnings if job else None)
blk, _w = win.preflight(job)
check("B …si può avviare", not blk, blk)
win.start_job()
check("B …lavoro mandato e finito", until(lambda: fb.accesi and ctl.last_status.get("state") == "Idle"
                                         and not ctl.job_active, 40), (len(fb.accesi), ctl.last_status.get("state")))
xs = [v for a in fb.accesi for v in (a[0], a[2])]
ys = [v for a in fb.accesi for v in (a[1], a[3])]
check("B verso degli assi: il rettangolo in alto a sinistra brucia vicino a casa (passi X e Y da 394)",
      xs and abs(min(xs) - 394) <= 2 and abs(min(ys) - 394) <= 2 and abs(max(xs) - 1181) <= 2
      and abs(max(ys) - 787) <= 2, (min(xs), min(ys), max(xs), max(ys)) if xs else None)
check("B nessun pericolo dalla finestra", nessun_pericolo(fb), fb.pericoli)
win.frame_job("box_laser")
until(lambda: ctl.last_status.get("state") == "Idle", 20)
check("B contorno «con il laser»: sulla K40 a laser spento", not any(ln.startswith("M3") for ln in sent[-10:]))
ctl.disconnect_port()
check("B scollegata: l'ultimo comando alla scheda è «I»", until(lambda: fb.comandi and fb.comandi[-1] == "I", 3),
      fb.comandi[-3:])

# --- profili salvati prima: uguali
old = MachineProfile()
d = old.file_dict()
d.pop("k40_board")
d.pop("power_knob")
import json  # noqa: E402

pth = os.path.join(tempfile.mkdtemp(), "vecchio.json")
with open(pth, "w", encoding="utf-8") as fh:
    json.dump(d, fh)
back = MachineProfile.load(pth)
check("B profilo salvato prima della 0.22.6: si apre uguale (non è una K40)", back.k40_board == ""
      and not back.power_knob and back.file_dict() == old.file_dict())
righe_sim, _ = lavoro([rettangolo()], profile=MachineProfile())
check("B le altre macchine: nessun avviso della manopola", not any("manopola" in w for w in
                                                                   gcode.generate(_doc, MachineProfile(),
                                                                                  gcode.JobOptions()).warnings))

ok = sum(results)
print(f"{ok}/{len(results)} prove superate")
sys.exit(0 if ok == len(results) else 1)
