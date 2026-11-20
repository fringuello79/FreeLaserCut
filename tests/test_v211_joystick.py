# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.21.1: joystick pronto e fedele (leone2805 su GitHub, Discussion #23, e Ale: «il cambio di direzione non è
immediato, anche qualche secondo»; «più fedeltà del movimento testa al movimento del joystick e anche prontezza»).

Causa: GRBL risponde «ok» a un jog appena lo mette in coda, non quando l'ha percorso. Fino alla 0.21.0 il joystick
mandava ogni 25 ms un pezzetto da 60 ms finché c'erano meno di 2 righe senza «ok», cioè quasi sempre: la coda della
scheda si riempiva e la testa restava indietro di tutta la coda (circa 1 s con 15 posti, 4 s con 63, 7 s con 127).

Parte A — modello di scheda a tempo finto (deterministico): coda dei movimenti da 15, 63 e 127 posti, «ok» appena il
jog entra in coda, posizione letta ogni 0,2 s come con lo stato di GRBL. Si misura quanto ci mette la testa a girare.
Parte B — simulatore di FreeLaserCut con i jog in coda come le schede vere (SimSerial.jog_planner), 127 posti, tempo vero.
Uso: python tests/test_v211_joystick.py [banco]
"""
import collections
import math
import os
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.ui import jogpad  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


# ====================================================================== A. scheda finta a tempo finto
class Prof:
    def __init__(self, bx=400.0, by=400.0, ax=1000.0, ay=1000.0):
        self.bed_x, self.bed_y, self.accel_x, self.accel_y = bx, by, ax, ay


class FakeBoard:
    """Scheda GRBL semplificata: coda dei movimenti da `slots` posti; una riga ha l'«ok» quando entra in coda; i
    movimenti si percorrono alla velocità chiesta (con accelerazione `acc`); la posizione si legge ogni 0,2 s."""

    def __init__(self, slots, start=(200.0, 200.0), acc=1000.0, poll=0.2):
        self.t = 0.0
        self.slots, self.acc, self.poll = slots, acc, poll
        self.rx = collections.deque()  # righe mandate, senza «ok» (la coda è piena)
        self.plan = collections.deque()  # [dx, dy, v mm/s] ancora da percorrere
        self.pos = list(start)  # posizione vera
        self.seen = list(start)  # posizione letta dall'ultimo stato
        self._next_poll = 0.0
        self.v = 0.0  # velocità attuale lungo il movimento in corso (mm/s)
        self.connected, self.job_active, self.checking = True, False, False
        self.last_status = {"state": "Idle"}
        self.lines = 0
        self.cancels = 0

    # --- quello che usa JoyJog
    def queued(self, tag):
        return len(self.rx)

    def jog(self, dx, dy, feed, tag=None):
        self.lines += 1
        self.rx.append([dx, dy, feed / 60.0])
        self._feed_planner()

    def jog_cancel(self, tag=None):
        self.cancels += 1
        self.plan.clear()
        self.v = 0.0

    def head(self):
        return QPointF(*self.seen)

    # --- il tempo che passa
    def _feed_planner(self):
        while self.rx and len(self.plan) < self.slots:
            self.plan.append(self.rx.popleft())

    def step(self, dt):
        self.t += dt
        left = dt
        while left > 1e-9 and self.plan:
            seg = self.plan[0]
            L = math.hypot(seg[0], seg[1])
            if L < 1e-9:
                self.plan.popleft()
                continue
            # accelerazione semplice: verso la velocità del pezzetto, e frenata se dopo la coda c'è il vuoto
            remaining = sum(math.hypot(s[0], s[1]) for s in self.plan)
            v_stop = math.sqrt(max(0.0, 2 * self.acc * remaining))
            target = min(seg[2], v_stop)
            if self.v < target:
                self.v = min(target, self.v + self.acc * left)
            else:
                self.v = max(target, self.v - self.acc * left)
            v = max(self.v, 1.0)
            ds = min(L, v * left)
            ux, uy = seg[0] / L, seg[1] / L
            self.pos[0] += ux * ds
            self.pos[1] += uy * ds
            seg[0] -= ux * ds
            seg[1] -= uy * ds
            left -= ds / v
            if ds >= L - 1e-9:
                self.plan.popleft()
                self._feed_planner()
        if not self.plan:
            self.v = 0.0
        self.last_status["state"] = "Jog" if self.plan else "Idle"
        if self.t >= self._next_poll:
            self.seen = list(self.pos)
            self._next_poll = self.t + self.poll


def make(slots, acc=1000.0, feed=3000.0, cls=None):
    b = FakeBoard(slots, acc=acc)
    prof = Prof(ax=acc, ay=acc)
    J = cls or jogpad.JoyJog
    j = J(b, lambda: prof, b.head, lambda: feed, clock=lambda: b.t)
    j._t.stop()
    return b, j


def run(b, j, secs, dt=0.005, tick=0.02, log=None):
    next_tick = b.t
    end = b.t + secs
    while b.t < end - 1e-9:
        if b.t >= next_tick - 1e-9:
            j.tick()
            next_tick += tick
        b.step(dt)
        if log is not None:
            log.append((b.t, tuple(b.pos)))


def turn_time(slots, acc=1000.0, feed=3000.0, new=(-1.0, 0.0), axis=0, sign=-1):
    """Tenuto a destra 2 s, poi la nuova direzione: secondi finché la testa vera si muove nella direzione nuova."""
    b, j = make(slots, acc, feed)
    j.start()
    j.set_vector(1.0, 0.0)
    run(b, j, 2.0)
    j.set_vector(*new)
    t0 = b.t
    log = []
    run(b, j, 10.0, log=log)
    prev = None
    for t, p in log:
        if prev is not None and (p[axis] - prev[axis]) * sign > 1e-4:
            return t - t0, b, j
        prev = p
    return float("inf"), b, j


print("--- A. scheda finta a tempo finto")
for slots in (15, 63, 127):
    tt, b, j = turn_time(slots)
    check(f"coda da {slots} posti: la testa gira entro 0,25 s (era fino a 7 s)", tt <= 0.25, round(tt, 3))
    check(f"…coda da {slots}: righe senza «ok» mai più di {jogpad.JoyJog.MAX_Q}", len(b.rx) <= jogpad.JoyJog.MAX_Q)

tt, b, j = turn_time(127, new=(0.0, 1.0), axis=1, sign=1)
check("da destra a su (90°): la testa sale entro 0,25 s", tt <= 0.25, round(tt, 3))

# fedeltà: a regime la testa va alla velocità chiesta, senza fermarsi fra un pezzetto e l'altro
for acc in (300.0, 1000.0, 3000.0):
    b, j = make(127, acc=acc)
    j.start()
    j.set_vector(1.0, 0.0)
    run(b, j, 1.0)
    x0, t0 = b.pos[0], b.t
    log = []
    run(b, j, 1.0, log=log)
    v_real = (b.pos[0] - x0) / (b.t - t0)
    stops = sum(1 for k in range(1, len(log)) if abs(log[k][1][0] - log[k - 1][1][0]) < 1e-6)
    check(f"accelerazione {acc:g} mm/s²: velocità vera ≥ 95% di quella chiesta (50 mm/s)", v_real >= 0.95 * 50.0,
          round(v_real, 2))
    check(f"…accelerazione {acc:g}: mai ferma mentre tieni il joystick", stops == 0, stops)
    check(f"…accelerazione {acc:g}: in coda al massimo il movimento di {jogpad.JoyJog.LEAD_MAX} s",
          sum(math.hypot(s[0], s[1]) for s in b.plan) <= 50.0 * (jogpad.JoyJog.LEAD_MAX + jogpad.JoyJog.SEG_T) + 0.01)

# velocità proporzionale: a metà corsa della manopola la testa va più piano, e lo fa davvero
b, j = make(63)
j.start()
j.set_vector(0.54, 0.0)
run(b, j, 1.0)
x0 = b.pos[0]
run(b, j, 1.0)
v_half = b.pos[0] - x0
expect = (0.54 - j.DEAD) / (1 - j.DEAD) * 50.0
check("manopola a metà: la testa va alla metà della velocità", abs(v_half - expect) <= 0.05 * expect, (v_half, expect))
j.set_vector(1.0, 0.0)
t0 = b.t
log = []
run(b, j, 1.0, log=log)
t_fast = next((t - t0 for k, (t, p) in enumerate(log[1:], 1) if (p[0] - log[k - 1][1][0]) / 0.005 > 0.9 * 50), 9)
check("…e spinta in fondo accelera subito (entro 0,25 s)", t_fast <= 0.25, round(t_fast, 3))

# rilascio: si ferma subito
b, j = make(127)
j.start()
j.set_vector(1.0, 0.0)
run(b, j, 1.5)
j.stop()
x_stop = b.pos[0]
run(b, j, 2.0)
check("rilascio: arresto del jog e la testa resta lì (meno di 1 mm dopo)", b.cancels == 1 and b.pos[0] - x_stop < 1.0,
      (b.cancels, b.pos[0] - x_stop))

# bordo: mai oltre il margine, anche tenendo a lungo
b, j = make(127)
b.pos = [395.0, 200.0]
b.seen = list(b.pos)
j.start()
j.set_vector(1.0, 0.0)
run(b, j, 3.0)
check("verso il bordo: si ferma a mezzo millimetro e non lo supera", 399.0 < b.pos[0] <= 400 - jogpad.JoyJog.MARGIN + 1e-6,
      b.pos[0])
j.set_vector(-1.0, 0.0)
run(b, j, 0.6)
check("…e torna indietro subito appena cambi direzione", b.pos[0] < 395.0, b.pos[0])

# zona morta: niente righe; dopo un po' la posizione stimata torna quella vera
b, j = make(15)
j.start()
j.set_vector(1.0, 0.0)
run(b, j, 0.5)
j.set_vector(0.02, 0.0)
n = b.lines
run(b, j, 1.0)
check("zona morta: nessuna riga in più", b.lines == n, b.lines - n)
check("…la posizione stimata torna quella vera", math.dist(j.pos, b.pos) < 0.05, (j.pos, b.pos))

# movimento perso (per esempio un jog rifiutato o fermato dalla scheda): la posizione stimata si riallinea da sola
b, j = make(63)
j.start()
j.set_vector(1.0, 0.0)
run(b, j, 1.0)
b.plan.clear()  # la scheda butta quello che aveva in coda
b.rx.clear()
j.set_vector(0.02, 0.0)
run(b, j, 1.0)
check("movimento perso dalla scheda: la posizione stimata torna quella vera", math.dist(j.pos, b.pos) < 0.05,
      (j.pos, b.pos))
x_lost = b.pos[0]
j.set_vector(1.0, 0.0)
run(b, j, 0.5)
check("…e ripartendo la testa va avanti subito (niente attesa per il movimento perso)", b.pos[0] - x_lost > 15,
      b.pos[0] - x_lost)

# scheda lenta (accelerazione bassissima): il ritardo resta piccolo e la coda non si gonfia
b, j = make(127, acc=50.0)
j.start()
j.set_vector(1.0, 0.0)
run(b, j, 3.0)
q = sum(math.hypot(s[0], s[1]) for s in b.plan)
# qui la scheda non arriva alla velocità chiesta: la stima a tempo va avanti, la frena il controllo sulla testa vera
check("accelerazione bassissima (50 mm/s²): la coda non si gonfia (al massimo quanto permette il controllo sulla testa)",
      q <= 50.0 * (jogpad.JoyJog.LEAD_MAX + jogpad.JoyJog.POS_SLACK) + 1.0, round(q, 2))
check("…lead() limitato a LEAD_MAX", abs(j.lead() - jogpad.JoyJog.LEAD_MAX) < 1e-9, j.lead())
check("lead(): almeno LEAD_MIN anche a velocità bassa", abs(make(15)[1].lead(60.0) - jogpad.JoyJog.LEAD_MIN) < 1e-9)
check("accelerazione assente o rovinata nel profilo: si usa 500 mm/s²",
      jogpad.JoyJog(FakeBoard(15), lambda: Prof(ax=float("nan"), ay=0), lambda: None, lambda: 3000).accel() == 500.0)

# ====================================================================== B. simulatore vero, 127 posti
print("--- B. simulatore (jog in coda come le schede vere, 127 posti)")
from freelasercut.sim import SimSerial  # noqa: E402

SimSerial.jog_planner = True
SimSerial.preset = staticmethod(lambda sim: setattr(sim, "planner_size", 127))
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.003)


def until(fn, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        spin(0.02)
    return bool(fn())


w = MainWindow()
w.resize(1500, 950)
w.show()
spin(0.4)
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 1
until(lambda: w.ctl.board_settings, 8)
spin(0.6)
sim = w.ctl.sim
check("simulatore con 127 posti e jog in coda", getattr(sim, "planner_size", 0) == 127 and SimSerial.jog_planner)
if w.ctl.last_status.get("state") == "Alarm":
    w.ctl.home()
    until(lambda: w.ctl.last_status.get("state") == "Idle", 10)
w.goto_bed(100, 100)
until(lambda: w.canvas.head_pos() is not None and abs(w.canvas.head_pos().x() - 100) < 0.2, 10)
until(lambda: w.ctl.last_status.get("state") == "Idle", 8)
joy = w.move.pad.joy
check("joystick: parte", joy.start(), joy.stop_reason)
joy.set_vector(1.0, 0.0)
spin(2.0)
x_r = sim.pos[0]
check("tenuto a destra 2 s: la testa è andata a destra", x_r > 120, x_r)
jog_q = sum(1 for blk in list(sim._planner) if len(blk) >= 5)
check("…nella coda della scheda pochi pezzetti (non 127)", jog_q <= 6, jog_q)
joy.set_vector(-1.0, 0.0)
t0 = time.time()
turned = None
prev = sim.pos[0]
while time.time() - t0 < 3.0:
    spin(0.005)
    x = sim.pos[0]
    if x < prev - 1e-3:
        turned = time.time() - t0
        break
    prev = x
check("cambio di direzione sul simulatore: la testa gira entro 0,35 s", turned is not None and turned <= 0.35, turned)
spin(0.8)
joy.stop()
spin(0.1)
x1 = sim.pos[0]
spin(0.8)
check("rilascio: la testa si ferma", abs(sim.pos[0] - x1) < 0.5 and not joy.active, (x1, sim.pos[0]))
check("…coda dei jog vuota", until(lambda: not any(len(blk) >= 5 for blk in list(sim._planner)), 3))
check("…e la macchina torna ferma", until(lambda: w.ctl.last_status.get("state") == "Idle", 3),
      w.ctl.last_status.get("state"))

w.ctl.disconnect_port()
spin(0.3)
SimSerial.jog_planner = False
SimSerial.preset = None
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
