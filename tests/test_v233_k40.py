# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.3 (Evoluzione2 con la sua K40, 25/11/2026 sera).

A. Joystick: «segue la direzione ma va tutto a scatti con spostamenti di pochi mm». Ogni pezzetto era uno spostamento
   veloce a sé (partenza, frenata, attesa). Ora i pezzetti del joystick (marcati «;JOY») diventano un lavoro a laser
   spento che si allunga mentre arrivano, chiuso al rilascio, dopo un silenzio, a un cambio di direzione o di velocità.
B. Lo stesso dalla finestra, con il joystick vero (JoyJog) e il controllore collegato alla K40 finta.
C. «Finita l'incisione la testa non torna all'inizio anche se è abilitato»: il ritorno vale di nuovo anche sulla K40.
D. Scala di grigi sulla K40: diventa da sola un retino (prima il lavoro non partiva).
E. File di prova degli impulsi (per misurare quanto è corto l'impulso più breve che il tubo segue).
"""
import os
import re
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
from freelasercut.core.document import Document, ImageShape, RectShape  # noqa: E402
from freelasercut.k40 import da_gcode, ponte as P  # noqa: E402
from freelasercut.k40.codici import codice  # noqa: E402
from freelasercut.k40.scrittore import DATI  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

K = 0.05
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def until(fn, t=10.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.005)
    return bool(fn())


class Cliente:
    def __init__(self, **kw):
        self.b = SchedaFinta(scala=K, veloce_mm_s=40.0)
        self.p = P.K40Serial(self.b, registra=True, scala_tempo=K, **kw)
        time.sleep(0.1)
        self.cmd("$X")
        self.cmd("$H", 30)
        self.fermo()

    def cmd(self, riga, t=20.0):
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
                return r.decode().strip()
        return ""

    def mpos(self):
        m = re.search(r"MPos:(-?[\d.]+),(-?[\d.]+)", self.stato())
        return (float(m.group(1)), float(m.group(2))) if m else None

    def fermo(self, t=30.0):
        return until(lambda: self.stato().startswith("<Idle"), t)

    def vai(self, x, y):
        self.cmd(f"$J=G53 G21 X{x} Y{y} F6000")
        self.fermo()

    def stessa_posizione(self):
        m = self.mpos()
        return m is not None and abs(m[0] * MIL - self.b.x) <= 1.5 and abs(m[1] * MIL - self.b.y) <= 1.5

    def chiudi(self):
        self.p.close()


def joy(c, dx, dy, n, f=3000):
    return [c.cmd(f"$J=G91 G21 X{dx:.3f} Y{dy:.3f} F{f} ;JOY") for _ in range(n)]


# ====================================================================== A. joystick nel ponte
print("--- A. joystick nel ponte")
c = Cliente()
c.vai(100, 100)
s1e, s1p = c.b.comandi.count("S1E"), c.b.comandi.count("S1P")
t0 = time.time()
esiti = joy(c, 2, 0, 40)
dt = time.time() - t0
durante = c.stato()
c.p.write(b"\x85")
check("A 40 pezzetti del joystick: tutti «ok», stato «Jog» mentre va", set(esiti) == {"ok"} and "<Jog" in durante,
      (set(esiti), durante))
check("A …un lavoro solo a laser spento (S1E), nessuno spostamento veloce fra un pezzetto e l'altro (prima: 40 S1P)",
      c.fermo() and c.b.comandi.count("S1E") - s1e == 1 and c.b.comandi.count("S1P") == s1p,
      (c.b.comandi.count("S1E") - s1e, c.b.comandi.count("S1P") - s1p))
check("A …alla velocità chiesta (50 mm/s) e l'«ok» al passo della testa (non tutto subito)",
      ("I" + codice("M2", 50.0) in "".join(c.b.comandi)) or codice("M2", 50.0) in c.b.comandi
      and dt >= 0.6 * 72 / 50 * K, (round(dt, 3), c.b.comandi[-6:]))
check("A …fermato con 0x85: posizione del ponte = posizione della scheda, avanti in X e Y ferma",
      c.stessa_posizione() and c.b.x > round(150 * MIL) and abs(c.b.y - round(100 * MIL)) <= 1,
      (c.mpos(), c.b.x / MIL, c.b.y / MIL))
check("A …nessun colpo, nessun pericolo, nessun «I» con la testa in moto", not c.b.colpi and not c.b.pericoli
      and c.b.interrotti == 0, (c.b.colpi[:2], c.b.pericoli[:2], c.b.interrotti))
check("A …dentro il lavoro solo pacchetti pieni (la «F» di riempimento lo chiuderebbe)",
      not any("riempimento" in p for p in c.b.pericoli))

c.vai(100, 100)
s1e = c.b.comandi.count("S1E")
joy(c, 2, 0, 10)
joy(c, -2, 0, 10)
joy(c, 0, 2, 10)
c.p.write(b"\x85")
c.fermo()
check("A inversione e cambio di direzione: il lavoro si chiude e si riapre (niente inversioni a velocità piena)",
      c.b.comandi.count("S1E") - s1e == 3 and not c.b.colpi, (c.b.comandi.count("S1E") - s1e, c.b.colpi[:2]))
check("A …posizione giusta alla fine", c.stessa_posizione(), (c.mpos(), c.b.x / MIL, c.b.y / MIL))

c.vai(100, 100)
joy(c, 0.7, 0.7, 12)
x1, y1 = c.b.x, c.b.y
c.fermo()
check("A in diagonale: si ferma da solo dopo un silenzio (senza 0x85), testa ferma e posizione giusta",
      c.b.comandi[-1] == "FNSE" and c.stessa_posizione() and c.b.x > round(100 * MIL) and c.b.y > round(100 * MIL),
      (c.b.comandi[-3:], c.mpos()))

c.vai(100, 100)
joy(c, 3, 0, 5, f=12000)
c.p.write(b"\x85")
c.fermo()
check("A velocità del joystick al massimo 50 mm/s (nel lavoro a linee la scheda non frena)",
      codice("M2", P.JOY_V_MAX) in c.b.comandi and codice("M2", 200.0) not in c.b.comandi, c.b.comandi[-6:])

c.vai(100, 100)
joy(c, 2, 0, 5)
c.p.write(b"!")
chiuso_subito = c.p._sc is None
check("A «!» durante il joystick lo ferma subito, come le frecce (non resta in pausa)",
      chiuso_subito and c.fermo() and c.stessa_posizione() and "Hold" not in c.stato(), (chiuso_subito, c.stato()))
joy(c, 2, 0, 3)
s1p = c.b.comandi.count("S1P")
r = c.cmd("$J=G91 G21 X-10 F3000")
check("A una freccia dopo il joystick: uno spostamento veloce, dopo che il joystick ha finito",
      r == "ok" and c.fermo() and c.b.comandi.count("S1P") - s1p == 1 and c.stessa_posizione(),
      (r, c.b.comandi.count("S1P") - s1p, c.mpos()))
joy(c, 2, 0, 3)
for riga in ["G90 G21", "M4 S0", "G1 X50 Y50 F600 S0", "G1 X60 S1000", "M5 S0"]:
    c.cmd(riga)
check("A un lavoro dopo il joystick parte dalla posizione vera e brucia dove deve",
      c.fermo() and c.b.accesi and abs(c.b.accesi[-1][2] - round(60 * MIL)) <= 1 and not c.b.pericoli,
      (c.b.accesi[-1:], c.b.pericoli[:2]))
c.vai(290, 100)
e = joy(c, 4, 0, 5)
check("A oltre il bordo: «error:15» e nessun movimento fuori dal piano", "error:15" in e and not c.b.pericoli, e)
c.p.write(b"\x85")
c.fermo()
c.vai(100, 100)
joy(c, 2, 0, 5)
c.p.write(b"\x18")
check("A reset durante il joystick: «I» alla scheda, allarme (la posizione non è più sicura)",
      until(lambda: "I" in c.b.comandi[-2:], 3) and "Alarm" in c.stato() and c.p._sc is None,
      (c.b.comandi[-3:], c.stato()))
c.cmd("$X")
c.cmd("$H", 30)
c.fermo()
s1e = c.b.comandi.count("S1E")
joy(c, 2, 2, 5)
c.p.write(b"\x85")
check("A …dopo la casa il joystick riparte con un lavoro nuovo, dalla posizione vera",
      c.fermo() and c.b.comandi.count("S1E") - s1e == 1 and c.stessa_posizione() and not c.b.pericoli,
      (c.b.comandi.count("S1E") - s1e, c.mpos(), c.b.pericoli[:2]))
c.chiudi()

os.environ["FLC_K40_JOY"] = "0"
c = Cliente()
c.vai(100, 100)
s1p, s1e = c.b.comandi.count("S1P"), c.b.comandi.count("S1E")
joy(c, 2, 0, 5)
c.fermo()
check("A FLC_K40_JOY=0: come prima (uno spostamento veloce per pezzetto, nessun lavoro)",
      c.b.comandi.count("S1P") - s1p == 5 and c.b.comandi.count("S1E") == s1e,
      (c.b.comandi.count("S1P") - s1p, c.b.comandi.count("S1E") - s1e))
del os.environ["FLC_K40_JOY"]
r = c.cmd("$J=G91 G21 X5 F3000")
check("A le frecce senza «;JOY» restano come prima", r == "ok" and c.fermo() and c.stessa_posizione())
c.chiudi()

# ====================================================================== B. dalla finestra
print("--- B. dalla finestra, con il joystick vero")
from freelasercut.grbl import K40_PORT  # noqa: E402
from freelasercut.ui import jogpad  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

win = MainWindow()
fb = SchedaFinta(scala=K)
ctl = win.ctl
ctl.k40_links = lambda: [fb]
ctl.k40_time_scale = K
ctl.connect_port(K40_PORT)
check("B collegata la K40 finta", until(lambda: ctl.connected and ctl.board_settings.get(130) is not None, 10))
sent = []
_send = ctl.send_line
ctl.send_line = lambda line, *a, **k: (sent.append(line), _send(line, *a, **k))[1]
ctl.home()
check("B casa", until(lambda: (app.processEvents() or True) and ctl.homed and ctl.last_status.get("state") == "Idle",
                      20))
ctl.send_line("$J=G53 G21 X100 Y100 F6000")
until(lambda: (app.processEvents() or True) and ctl.last_status.get("state") == "Idle" and abs(fb.x - 3937) <= 2, 20)
until(lambda: (app.processEvents() or True) and win.canvas.head_pos() is not None
      and abs(win.canvas.head_pos().x() - 100.0) < 0.1, 10)  # la testa sul piano è quella vera
j = jogpad.JoyJog(ctl, lambda: win.profile, win.canvas.head_pos, lambda: 3000.0)
s1e, s1p = fb.comandi.count("S1E"), fb.comandi.count("S1P")


def tieni(vx, vy, secondi):
    j.set_vector(vx, vy)
    end = time.time() + secondi
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


check("B joystick avviato", j.start())
tieni(1.0, 0.0, 1.0)
j.stop()
until(lambda: (app.processEvents() or True) and ctl.last_status.get("state") == "Idle", 10)
mossi = (fb.x - 3937) / MIL
check("B tenuto a destra 1 s: un lavoro solo, nessuno spostamento veloce, la testa va avanti (circa 50 mm)",
      fb.comandi.count("S1E") - s1e == 1 and fb.comandi.count("S1P") == s1p and 25 <= mossi <= 60,
      (fb.comandi.count("S1E") - s1e, fb.comandi.count("S1P") - s1p, round(mossi, 1)))
check("B …i pezzetti arrivano marcati «;JOY» (solo sulla K40)", any(ln.endswith(";JOY") for ln in sent))
check("B …nessun colpo e nessun pericolo", not fb.colpi and not fb.pericoli, (fb.colpi[:2], fb.pericoli[:2]))
s1e = fb.comandi.count("S1E")
until(lambda: (app.processEvents() or True) and abs(win.canvas.head_pos().x() - fb.x / MIL) < 0.1, 10)
check("B di nuovo", j.start())
tieni(1.0, 0.0, 0.5)
tieni(0.0, 1.0, 0.5)
j.stop()
until(lambda: (app.processEvents() or True) and ctl.last_status.get("state") == "Idle", 10)
check("B destra e poi su: due lavori (la direzione cambia di 90°), nessun colpo",
      fb.comandi.count("S1E") - s1e == 2 and not fb.colpi, (fb.comandi.count("S1E") - s1e, fb.colpi[:2]))

# ====================================================================== C. ritorno a fine lavoro
print("--- C. ritorno a fine lavoro")
r = RectShape(20, 10)
r.apply(QTransform.fromTranslate(60, 120))
win.editor.add([r])
lp = win.laser
lp.start_from.setCurrentIndex(lp.start_from.findData("absolute"))
lp.verify_first.setChecked(False)
lp.finish_origin.setChecked(True)
job = win.build_job(show=False)
check("C K40 con «torna al punto di partenza»: il lavoro finisce con il ritorno vicino a casa",
      job is not None and job.lines[-3:-1] == ["G0 X10 Y10", "G54"] or "G0 X10 Y10" in job.lines[-4:],
      job.lines[-5:] if job else None)
n = len(fb.accesi)
win.start_job()
check("C …mandato alla K40 finta: brucia e poi torna a 10 mm da casa",
      until(lambda: (app.processEvents() or True) and len(fb.accesi) > n and ctl.last_status.get("state") == "Idle"
            and not ctl.job_active, 40) and abs(fb.x - round(10 * MIL)) <= 2 and abs(fb.y - round(10 * MIL)) <= 2,
      (fb.x / MIL, fb.y / MIL))
check("C …nessun pericolo", not fb.pericoli, fb.pericoli[:2])
lp.finish_origin.setChecked(False)
job = win.build_job(show=False)
check("C senza il ritorno: il lavoro resta dov'è", job is not None and "G0 X10 Y10" not in job.lines[-4:])
ctl.disconnect_port()
win.close()

# ====================================================================== D. scala di grigi sulla K40
print("--- D. scala di grigi sulla K40")


def foto(dither, profile):
    doc = Document()
    doc.images["g"] = Image.fromarray(np.tile(np.linspace(255, 0, 200), (100, 1)).astype(np.uint8))
    im = ImageShape("g", 40, 20, layer=0)
    im.apply(QTransform.fromTranslate(100, 100))
    doc.add(im)
    cs = doc.layer(0)
    cs.mode, cs.dither, cs.dpi = "image", dither, 127
    return gcode.generate(doc, profile, gcode.JobOptions(start_from="absolute", no_g55=True))


jg, js = foto("grayscale", MachineProfile.k40()), foto("stucki", MachineProfile.k40())
check("D grigio sulla K40: si prepara, uguale al retino Stucki, e lo dice", not jg.refused and jg.lines == js.lines
      and any("Stucki" in w for w in jg.warnings), (jg.refused, [w for w in jg.warnings if "grigi" in w]))
jo = foto("grayscale", MachineProfile())
check("D le altre macchine: scala di grigi vera, come sempre", not jo.refused and jo.lines != js.lines
      and not any("Stucki" in w for w in jo.warnings))

# ====================================================================== E. file di prova degli impulsi
print("--- E. file di prova degli impulsi")
sys.path.insert(0, os.path.join(ROOT, "tools", "k40"))
import k40_prova_impulsi as kpi  # noqa: E402

righe = [ln.split(";")[0].strip() for ln in kpi.genera()]
righe = [ln for ln in righe if ln]
pz, _ = da_gcode.traduci(righe)
f = SchedaFinta(scala=1e-7)
f._testo = b"".join(p[1] for p in pz if p[0] == DATI).decode("ascii")
f._leggi()
f.chiudi()
lunghi = sorted({max(abs(a[2] - a[0]), abs(a[3] - a[1])) for a in f.accesi})
check("E impulsi esatti da 1, 2, 3, 4, 6, 8, 12, 16 passi", lunghi == list(kpi.IMPULSI), lunghi)
check("E nessun pericolo, nessun colpo, dentro il piano, alla fine vicino a casa", not f.pericoli and not f.colpi
      and abs(f.x - round(10 * MIL)) <= 1 and abs(f.y - round(10 * MIL)) <= 1, (f.pericoli[:2], f.x, f.y))
vel = sorted({round(v) for v in f.accesi_v})
check("E velocità dei tre gruppi: 25, 50, 100 mm/s", vel == [25, 50, 100], vel)

n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
