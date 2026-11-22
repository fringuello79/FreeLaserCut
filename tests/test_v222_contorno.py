# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.2: dal messaggio di maurodani76 su GitHub.

Partenza «Posizione attuale della testa» con un pallino diverso da quello in alto a sinistra: dopo il Contorno la testa
restava sul primo angolo del giro e il lavoro, che segue la testa, si spostava di mezzo ingombro a ogni contorno. Ora,
finito il giro, la testa torna da dove è partita (a laser spento). Con le altre partenze non cambia niente."""
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core.document import EllipseShape, RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def until(fn, t=10.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        spin(0.02)
    return bool(fn())


w = MainWindow()
w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.board_settings.get(130) is not None)
w.ctl.sim.speedup = 20
w.ctl.home()
until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 15)
spin(0.2)
r = RectShape(40, 20)
r.apply(QTransform.fromTranslate(10, 10))
e = EllipseShape(16, 16)
e.apply(QTransform.fromTranslate(60, 6))
w.editor.add([r, e])
lp = w.laser
lp.fire_pct.setValue(1.0)
sent = []
_send = w.ctl.send_line


def send(line, *a, **k):
    sent.append(line)
    return _send(line, *a, **k)


w.ctl.send_line = send


def idle():
    return w.ctl.last_status.get("state") == "Idle"


def head():
    p = w.canvas.head_pos()
    return (round(p.x(), 2), round(p.y(), 2))


def mpos():
    m = w.ctl.last_status.get("MPos")
    return (round(m[0], 2), round(m[1], 2))


def bounds():
    b = w.build_job().bounds
    return tuple(round(v, 2) for v in (b.left(), b.top(), b.right(), b.bottom()))


def set_mode(mode, anchor):
    lp.start_from.setCurrentIndex(lp.start_from.findData(mode))
    lp.anchor.setValue(anchor)
    spin(0.05)


def park(x=200.0, y=200.0):
    w.goto_bed(x, y)
    spin(0.15)
    settle()


def settle(t=40.0):
    """Ferma davvero: «Idle» e stessa posizione per 0,4 s di fila (fra un jog e l'altro la scheda passa da «Idle»)."""
    end = time.time() + t
    last, since = None, time.time()
    while time.time() < end:
        spin(0.05)
        now = (w.ctl.last_status.get("state"), tuple(w.ctl.last_status.get("MPos") or ()))
        if now != last or now[0] != "Idle":
            last, since = now, time.time()
        elif time.time() - since >= 0.4:
            return True
    return False


def frame(kind):
    del sent[:]
    w.frame_job(kind)
    spin(0.15)
    settle()
    return list(sent)


def xy(line):
    m = dict(re.findall(r"([XY])(-?[\d.]+)", line))
    return (round(float(m["X"]), 2), round(float(m["Y"]), 2)) if "X" in m and "Y" in m else None



# ================================================================ 1. partenza dalla testa: i 9 pallini
for kind in ("box", "box_laser", "hull", "hull_laser"):
    still, same_bounds, same_lines, last_is_start, off_before_back = [], [], [], [], []
    for anchor in range(9):
        set_mode("current", anchor)
        park()
        h0, m0, b0 = head(), mpos(), bounds()
        l1 = frame(kind)
        h1, b1 = head(), bounds()
        l2 = frame(kind)
        h2, b2 = head(), bounds()
        still.append(h0 == h1 == h2)
        same_bounds.append(b0 == b1 == b2)
        same_lines.append(l1 == l2 and len(l1) >= 5)
        last_is_start.append(xy(l1[-1]) == m0)
        if kind.endswith("_laser"):
            i_off = max(i for i, ln in enumerate(l1) if ln.startswith("M5"))
            lit = [ln for ln in l1[i_off + 1:] if re.search(r"S[1-9]", ln) or ln.startswith("M3")]
            off_before_back.append(i_off == len(l1) - 2 and not lit and "S0" in l1[-1] or l1[-1].startswith("G53 G0"))
    what = {"box": "rettangolo, laser spento", "box_laser": "rettangolo, con il puntino", "hull": "convesso, laser spento",
            "hull_laser": "convesso, con il puntino"}[kind]
    check(f"{what}: con tutti e 9 i pallini la testa torna dov'era", all(still), still)
    check(f"{what}: l'ingombro del lavoro non si sposta dopo uno e due contorni", all(same_bounds), same_bounds)
    check(f"{what}: il secondo contorno manda le stesse righe del primo", all(same_lines), same_lines)
    check(f"{what}: l'ultima riga porta la testa al punto di partenza (coordinate macchina)", all(last_is_start),
          last_is_start)
    if kind.endswith("_laser"):
        check(f"{what}: il laser si spegne prima del ritorno, che è a laser spento", all(off_before_back),
              off_before_back)

# ================================================================ 2. il caso della segnalazione, con i numeri
set_mode("current", 4)
check("il pallino scelto dalla prova è quello centrale", lp.anchor.value == 4 and w.job_options().anchor == 4)
park(200, 200)
b0 = bounds()
frame("box")
check("pallino centrale, testa a 200, 200: dopo il contorno la testa è a 200, 200 (prima 180, 190)", head() == (200.0, 200.0),
      head())
check("…e il lavoro resta centrato sulla testa", bounds() == b0 and abs((b0[0] + b0[2]) / 2 - 200) < 0.01
      and abs((b0[1] + b0[3]) / 2 - 200) < 0.01, (b0, bounds()))

# ================================================================ 3. ripetizioni del contorno
if hasattr(lp, "frame_repeat"):
    lp.frame_repeat.setValue(3)
elif hasattr(lp, "a_frame_repeat"):
    lp.a_frame_repeat.setChecked(True)
n_rep = lp.frame_repeats()
set_mode("current", 8)
park()
h0 = head()
lines = frame("box")
check(f"contorno ripetuto ({n_rep} giri): un solo ritorno, alla fine", head() == h0
      and len(lines) == 5 + 4 * (n_rep - 1) + 1, (n_rep, len(lines), head()))
if hasattr(lp, "frame_repeat"):
    lp.frame_repeat.setValue(1)
elif hasattr(lp, "a_frame_repeat"):
    lp.a_frame_repeat.setChecked(False)

# ================================================================ 4. le altre partenze: righe come prima
for mode, label in (("absolute", "coordinate assolute"), ("origin", "origine utente")):
    if lp.start_from.findData(mode) < 0:
        continue
    set_mode(mode, 4)
    park(150, 150)
    for kind in ("box", "box_laser"):
        lines = frame(kind)
        moves = [ln for ln in lines if xy(ln)]
        check(f"{label}, {kind}: nessun ritorno (il giro finisce sul primo angolo, come prima)",
              len(moves) == 5 and xy(moves[-1]) == xy(moves[0]) and (kind == "box" or lines[-1].startswith("M5")),
              lines[-2:])

# ================================================================ 5. rotativo (asse Y) acceso
w.qs.setValue("rotary_on", True)
w.update_rotary_state()
set_mode("current", 4)
park()
h0, b0 = head(), bounds()
frame("box")
check("rotativo acceso: dopo il contorno la testa torna dov'era e il lavoro non si sposta", head() == h0
      and bounds() == b0, (h0, head()))
w.qs.setValue("rotary_on", False)
w.update_rotary_state()

# ================================================================ 5b. asse X invertito: piano e macchina non coincidono
inv0 = w.profile.invert_x
w.profile.invert_x = not inv0
set_mode("current", 4)
park(120, 90)
h0, m0, b0 = head(), mpos(), bounds()
lines = frame("box")
check("asse X invertito: piano e macchina hanno numeri diversi (la prova vale)", h0 != m0, (h0, m0))
check("asse X invertito: il ritorno è nelle coordinate della macchina e la testa torna dov'era",
      xy(lines[-1]) == m0 and head() == h0 and bounds() == b0, (xy(lines[-1]), m0, head(), h0))
w.profile.invert_x = inv0
park()

# ================================================================ 6. frame_path da solo
del sent[:]
w.ctl.frame_path([(10, 10), (20, 10), (10, 10)], 3000)
check("frame_path senza punto di ritorno: le righe di sempre", len(sent) == 3 and all(s.startswith("$J=G53") for s in sent),
      sent)
settle()
del sent[:]
w.ctl.frame_path([(10, 10), (20, 10), (10, 10)], 3000, back=(33.5, 44.25))
check("frame_path con il ritorno, laser spento: un jog in più verso quel punto", len(sent) == 4
      and xy(sent[-1]) == (33.5, 44.25) and sent[-1].startswith("$J=G53"), sent)
settle()
del sent[:]
w.ctl.frame_path([(10, 10), (20, 10), (10, 10)], 3000, 1.0, 1000.0, back=(33.5, 44.25))
check("frame_path con il ritorno, puntino acceso: M5 S0 e poi il ritorno veloce a laser spento",
      sent[-2] == "M5 S0" and sent[-1] == "G53 G0 X33.500 Y44.250", sent[-2:])
settle()
del sent[:]
w.ctl.frame_path([(10, 10), (20, 10), (10, 10)], 3000, 1.0, 1000.0, travel_feed=1500, back=(33.5, 44.25))
check("…con gli spostamenti a vuoto più lenti: ritorno G1 S0 a quella velocità",
      sent[-2] == "M5 S0" and sent[-1] == "G53 G1 X33.500 Y44.250 S0 F1500", sent[-2:])
settle()

w.ctl.send_line = _send
w.ctl.disconnect_port()
w.editor.dirty = False
ok = sum(results)
print(f"\n{ok}/{len(results)} superati", flush=True)
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
