# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.3 (Ale): rotativo, spunta «Inverti il senso di rotazione» (motore montato al contrario).

Solo nel programma, nessuna impostazione della scheda. Con la spunta l'asse del rotativo (Y o Z) si specchia attorno
all'ancoraggio del disegno; la X, le potenze e le velocità restano uguali. Seguono la spunta: lavoro, contorno, frecce
(anche «Continuo»), joystick, «Prova: un giro», rapporto all'assistenza. Spunta spenta = G-code di prima, identico.

A. generatore (senza finestra), B. finestra e simulatore.
Uso: python tests/test_v233_rotativo_inverti.py [classica|banco]
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
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
for k in ("FLC_NO_DIALOGS", "FLC_NO_FIRST_RUN", "FLC_NO_UPDATE"):
    os.environ[k] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import diag  # noqa: E402
from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import Document, EllipseShape, ImageShape, RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui import dialogs_rotary, jogpad  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402

UI = os.environ["FLC_UI"]
dialogs_rotary.ask = lambda *a, **k: 0  # «Sì, è sul rotativo», «Sì, ha girato»
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + f"[{UI}] " + name + (f"  [{info}]" if info != "" and not cond else ""),
          flush=True)


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def until(fn, t=15.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        spin(0.02)
    return bool(fn())


WORD = re.compile(r"([A-Z])(-?\d+(?:\.\d+)?)")


def words(line):
    return dict((k, float(v)) for k, v in WORD.findall(line.split(";")[0]))


def specchiate(a, b, asse):
    """Righe una per una: stesso testo a meno del valore dell'asse del rotativo; quello somma sempre allo stesso numero
    (2 × ancoraggio). -> (vero/falso, somma, primo problema)."""
    if len(a) != len(b):
        return False, None, ("righe", len(a), len(b))
    somma = None
    for la, lb in zip(a, b):
        wa, wb = words(la), words(lb)
        if set(wa) != set(wb) or re.sub(asse + r"-?[\d.]+", "", la) != re.sub(asse + r"-?[\d.]+", "", lb):
            return False, somma, (la, lb)
        if asse in wa and not la.startswith(("G92", ";")):
            s = wa[asse] + wb[asse]
            if somma is None:
                somma = s
            elif abs(s - somma) > 0.0025:
                return False, somma, (la, lb, s)
    return somma is not None, somma, None


# ================================================================== A. generatore
print("--- A. generatore")
prof = MachineProfile()
prof.z_motor = True
doc = Document()
r = RectShape(30, 20)
r.apply(QTransform.fromTranslate(40, 40))
doc.add(r)
e = EllipseShape(20, 12)
e.apply(QTransform.fromTranslate(90, 50))
e.layer = 1
doc.add(e)
doc.layer(1).mode, doc.layer(1).interval = "fill", 0.2
doc.images["g"] = Image.fromarray((np.indices((40, 60)).sum(0) % 7 * 36).astype(np.uint8))
im = ImageShape("g", 15, 10, layer=2)
im.apply(QTransform.fromTranslate(130, 40))
doc.add(im)
doc.layer(2).mode, doc.layer(2).dither, doc.layer(2).dpi = "image", "floyd", 127
ROT = {"kind": "chuck", "mm_per_rev": 80.0, "roller_d": 25.0, "object_d": 70.0}


def gen(rot, start="current"):
    o = gcode.JobOptions(start_from=start, current_pos=(100.0, 100.0), rotary=rot)
    return gcode.generate(doc, prof, o)


for asse, start in (("Y", "current"), ("Y", "absolute"), ("Z", "current")):
    base = dict(ROT, axis=asse)
    j0, jf, ji = gen(dict(base)), gen(dict(base, invert=False)), gen(dict(base, invert=True))
    check(f"rotativo su {asse}, partenza {start}: spunta spenta = G-code di prima, identico", j0.lines == jf.lines)
    ok, somma, why = specchiate(jf.lines, ji.lines, asse)
    check(f"…spunta accesa: stesse righe, X, potenze e velocità uguali; solo {asse} specchiata attorno all'ancoraggio",
          ok and ji.rotary_k == -jf.rotary_k and ji.rotary_ref == jf.rotary_ref, (why, somma))
    check(f"…stesso tempo stimato e stessi tratti", abs(ji.seconds - jf.seconds) < 1e-6
          and [(s.cut_mm, s.lines) for s in ji.layers] == [(s.cut_mm, s.lines) for s in jf.layers])
    check(f"…l'avviso del rotativo dice «senso di rotazione invertito»",
          any("invertito" in w for w in ji.warnings) and not any("invertito" in w for w in jf.warnings), ji.warnings)
flat = gen(None)
check("rotativo spento: G-code del piano, la spunta non c'entra", flat.lines == gen(None).lines
      and not any("invertito" in w for w in flat.warnings))
check("fattore del rotativo: con la spunta negativo, stesso valore", gcode.rotary_scale(dict(ROT, invert=True))
      == -gcode.rotary_scale(ROT) and gcode.rotary_scale(dict(ROT, invert=False)) == gcode.rotary_scale(ROT))

# ================================================================== B. finestra e simulatore
print("--- B. finestra e simulatore")
win = mw.MainWindow()
win.show()
ctl = win.ctl
ctl.connect_port(SIM_PORT)
check("collegato al simulatore", until(lambda: ctl.board_settings.get(130) is not None))
ctl.sim.speedup = 30
ctl.home()
until(lambda: ctl.homed and ctl.last_status.get("state") == "Idle", 20)
spin(1.0)
r2 = RectShape(30, 20)
r2.apply(QTransform.fromTranslate(60, 60))
win.editor.add([r2])
lp = win.laser
lp.start_from.setCurrentIndex(lp.start_from.findData("current"))
win.goto_bed(150, 150)
until(lambda: ctl.last_status.get("state") == "Idle", 20)
spin(0.5)
sent = []
_send = ctl.send_line
ctl.send_line = lambda line, *a, **k: (sent.append(line), _send(line, *a, **k))[1]


def imposta(on=True, asse="Y", inverti=False):
    d = dialogs_rotary.RotaryDialog(win)
    d.on.setChecked(on)
    d.kind.setCurrentIndex(d.kind.findData("chuck"))
    d.axis.setCurrentIndex(d.axis.findData(asse))
    d.mm_rev.setValue(80.0)
    d.obj.setValue(70.0)
    d.invert.setChecked(inverti)
    txt = d.info.text()
    d.accept()
    win.update_rotary_state()
    return txt


def ultime(pref="$J"):
    return [ln for ln in sent if ln.startswith(pref)]


d = dialogs_rotary.RotaryDialog(win)
check("finestra del rotativo: la casella c'è, spenta all'inizio, con il suggerimento", not d.invert.isChecked()
      and "specchiata" in d.invert.toolTip())
d.reject()
txt = imposta(True, "Y", True)
check("accesa e salvata: resta nelle preferenze, l'informazione lo dice",
      win.qs.value("rotary_invert") in (True, "true") and "invertito" in txt and win.rotary_settings()["invert"], txt)
d = dialogs_rotary.RotaryDialog(win)
check("riaprendo la finestra la casella è ancora accesa", d.invert.isChecked())
d.reject()
check("controllore: senso invertito sull'asse Y del rotativo", ctl.rotary_sign == -1.0 and ctl.rotary_y
      and not ctl.rotary_z)
win.job = win.build_job(show=False)
check("rapporto all'assistenza: «senso invertito sì»", "senso invertito sì" in diag.job_text(win),
      [ln for ln in diag.job_text(win).splitlines() if "Rotativo" in ln])

# --- frecce
del sent[:]
ctl.jog(0.0, 10.0, 1500)
ctl.jog(5.0, 0.0, 1500)
spin(0.2)
j = ultime()
check("freccia su di 10 mm con il senso invertito: la Y della macchina va al contrario (−10), la X no",
      len(j) == 2 and "Y-10.000" in j[0] and "X5.000" in j[1], j)
imposta(True, "Y", False)
del sent[:]
ctl.jog(0.0, 10.0, 1500)
spin(0.2)
check("…spunta spenta: come prima (+10)", ultime() and "Y10.000" in ultime()[0], ultime())
imposta(False, "Y", True)
del sent[:]
ctl.jog(0.0, 10.0, 1500)
spin(0.2)
check("…rotativo spento (spunta rimasta accesa): frecce del piano come prima", ultime() and "Y10.000" in ultime()[0]
      and ctl.rotary_sign == 1.0, ultime())
until(lambda: ctl.last_status.get("state") == "Idle", 20)

# --- contorno
frames = {}
for inv in (False, True):
    imposta(True, "Y", inv)
    win.goto_bed(150, 150)
    until(lambda: ctl.last_status.get("state") == "Idle", 20)
    spin(0.3)
    job = win.build_job(show=False)
    del sent[:]
    win.frame_job("box")
    until(lambda: ctl.last_status.get("state") == "Idle" and len(ultime()) >= 4, 30)
    spin(0.3)
    frames[inv] = (job, [ln for ln in ultime() if "G53" in ln])
(jf, ff), (ji, fi) = frames[False], frames[True]
ok, somma, why = specchiate(ff, fi, "Y")
check("contorno con il senso invertito: stessi angoli in X, Y specchiata attorno all'ancoraggio", ok, (why, ff[:3], fi[:3]))
ok, somma, why = specchiate([ln for ln in jf.lines if not ln.startswith(";")],
                            [ln for ln in ji.lines if not ln.startswith(";")], "Y")
check("lavoro dalla finestra: stesse righe, Y specchiata", ok, why)

# --- «Prova: un giro»
imposta(True, "Y", True)
until(lambda: ctl.last_status.get("state") == "Idle", 20)
del sent[:]
d = dialogs_rotary.RotaryDialog(win)
d.test_rev()
spin(0.3)
d.reject()
check("«Prova: un giro» sulla Y con il senso invertito: un giro intero, nel verso del disegno (−80)",
      ultime() and "Y-80.000" in ultime()[0], ultime())
until(lambda: ctl.last_status.get("state") == "Idle", 30)

# --- joystick
win.goto_bed(150, 100)
until(lambda: ctl.last_status.get("state") == "Idle", 20)
spin(0.5)


def joystick(vy, secondi=0.8):
    until(lambda: win.canvas.head_pos() is not None, 5)
    j = jogpad.JoyJog(ctl, lambda: win.profile, win.canvas.head_pos, lambda: 1500.0)
    del sent[:]
    j.start()
    j.set_vector(0.0, vy)
    end = time.time() + secondi
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)
    j.stop()
    until(lambda: ctl.last_status.get("state") == "Idle", 20)
    spin(0.3)
    ys = [words(ln).get("Y", 0.0) for ln in ultime() if "G91" in ln]
    return ys


ys_inv = joystick(1.0)
imposta(True, "Y", False)
win.goto_bed(150, 100)
until(lambda: ctl.last_status.get("state") == "Idle", 20)
spin(0.5)
ys_dir = joystick(1.0)
check("joystick in su: pezzetti con la Y al contrario rispetto alla spunta spenta",
      ys_inv and ys_dir and all(y < 0 for y in ys_inv) and all(y > 0 for y in ys_dir), (ys_inv[:3], ys_dir[:3]))
check("…e non si ferma a scatti (stessi pezzetti, circa, con e senza spunta: il controllo sulla testa la segue)",
      len(ys_inv) >= 0.7 * len(ys_dir) and len(ys_inv) >= 8, (len(ys_inv), len(ys_dir)))

# --- «Continuo»
pad = win.move.pad if hasattr(win, "move") and hasattr(win.move, "pad") else None
if pad is not None:
    cont = {}
    for inv in (False, True):
        imposta(True, "Y", inv)
        win.goto_bed(150, 100)
        until(lambda: ctl.last_status.get("state") == "Idle", 20)
        spin(0.5)
        pad.cont.setChecked(True)
        del sent[:]
        pad.jog_press(0, 1)
        spin(0.2)
        pad.jog_release()
        until(lambda: ctl.last_status.get("state") == "Idle", 20)
        cont[inv] = [ln for ln in ultime() if "G53" in ln]
    pad.cont.setChecked(False)
    a, b = (words(cont[False][0]).get("Y") if cont[False] else None), (words(cont[True][0]).get("Y") if cont[True] else None)
    hy = float(ctl.last_status.get("MPos", [0, 0])[1]) if ctl.last_status.get("MPos") else None
    check("«Continuo» in su con il senso invertito: va verso il bordo opposto (Y della macchina dall'altra parte)",
          a is not None and b is not None and abs(a - b) > 100, (a, b))

# --- rotativo sulla Z
win.profile.z_motor = True
imposta(True, "Z", True)
check("sulla Z con il senso invertito: segno nel controllore, frecce della Y libere", ctl.rotary_z
      and ctl.rotary_sign == -1.0 and not ctl.rotary_y)
del sent[:]
ctl.jog(0.0, 10.0, 1500)
ctl.jog_z(80.0, 300, force=True)
spin(0.2)
j = ultime()
check("…la Y (frecce) non cambia verso, la «Prova: un giro» della Z sì (−80)", len(j) == 2 and "Y10.000" in j[0]
      and "Z-80.000" in j[1], j)
imposta(False, "Y", False)
until(lambda: ctl.last_status.get("state") == "Idle", 20)
ctl.disconnect_port()
win.close()

print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(0 if all(results) else 1)
