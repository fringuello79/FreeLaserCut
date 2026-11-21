# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: calibrazione della camera quando la scheda si riavvia da sola (rapporti E933 del 17/11 e 44A1 del 20/11,
Giovanni Lieta, Creality Falcon 2 Pro: a metà del primo spostamento arriva il banner «Grbl 1.1f», la testa si ferma, la
posizione è persa e la calibrazione andava avanti come se la testa fosse arrivata).

A. il controllore distingue i riavvii chiesti (apertura della porta, Ctrl+X) da quelli da soli, li conta, toglie
   l'homing e lo scrive nel registro; B. la calibrazione si ferma subito con un messaggio chiaro e non manda più
   movimenti; C. inizio e fine della calibrazione (e il perché) nel registro della comunicazione; D. quando il puntino
   non basta, la richiesta del cartone spiega che i lampi erano il primo metodo.
Uso: python tests/test_v212_calibrazione.py
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from freelasercut import diag  # noqa: E402
from freelasercut.camera import AutoCam, SimCamera  # noqa: E402
from freelasercut.grbl import SIM_PORT, GrblController  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info else ""), flush=True)


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def until(fn, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        spin(0.02)
    return bool(fn())


def connect():
    c = GrblController()
    log = diag.CommLog(c)
    c.connect_port(SIM_PORT)
    until(lambda: c.board_settings.get(130) is not None, 8)
    spin(0.3)
    return c, log


def log_text(log):
    return "\n".join(t for _ts, kind, t in log.lines if kind == "#")


# ====================================================================== A. riavvii chiesti e no
print("--- A. riavvio chiesto o da solo")
c, log = connect()
reb = []
c.board_rebooted.connect(lambda: reb.append(time.time()))
check("il banner dell'apertura della porta non conta come riavvio", c.reboots == 0 and not reb)
c.home()
check("homing", until(lambda: c.homed and c.last_status.get("state") == "Idle", 15))
c.soft_reset()
spin(0.6)
check("il reset chiesto da FreeLaserCut (Ctrl+X) nemmeno", c.reboots == 0 and not reb)
c._reset_asked_t = 0.0  # lontano nel tempo
c.home()
until(lambda: c.homed and c.last_status.get("state") == "Idle", 15)
c.sim.reboot()
check("riavvio da solo: contato e segnalato", until(lambda: c.reboots == 1 and reb, 3), (c.reboots, reb))
check("…l'homing non vale più (la posizione è persa)", not c.homed)
check("…e il registro della comunicazione lo dice", "si è riavviata da sola" in log_text(log), log_text(log)[-200:])
c.disconnect_port()
spin(0.3)


# ====================================================================== B e C. calibrazione con il riavvio
def calibrate(c, method, on_ask=None, reboot_when=None, timeout=120):
    cam = SimCamera(c.sim, occlude=True)
    spin(0.5)
    prof = MachineProfile()
    prof.negative_space = False
    ac = AutoCam(c, cam, prof, grid_n=5, method=method)
    res, asks = {}, []
    ac.need_user.connect(lambda m: (asks.append(m), (on_ask or (lambda a: a.continue_()))(ac)))
    ac.finished.connect(lambda m, msg: res.update(model=m, msg=msg, t=time.time()))
    sent = []
    c.line_sent.connect(lambda l: sent.append((time.time(), l)))
    ac.start()
    fired = None
    t = time.time()
    while "msg" not in res and time.time() - t < timeout:
        if reboot_when is not None and fired is None and reboot_when(c):
            fired = time.time()
            c.sim.reboot()
        spin(0.02)
    cam.close()
    return ac, res, asks, sent, fired


print("--- B. la calibrazione si ferma")
c, log = connect()
c.home()
until(lambda: c.homed and c.last_status.get("state") == "Idle", 15)
c._reset_asked_t = 0.0
c.sim.speedup = 3
ac, res, asks, sent, fired = calibrate(c, "auto", reboot_when=lambda c: c.last_status.get("state") in ("Jog", "Run"))
msg = res.get("msg", "")
check("riavvio durante il primo spostamento: la calibrazione si ferma", fired is not None and res and res["model"] is None,
      msg)
check("…con il messaggio chiaro (riavvio, cavo USB senza hub, alimentazione, homing)",
      "riavviata da sola" in msg and "USB" in msg and "hub" in msg and "homing" in msg, msg)
check("…entro un paio di secondi, non dopo il giro intero", res and res["t"] - fired < 3.0, res and res["t"] - fired)
moves = [line for ts, line in sent if fired and ts > fired + 0.05 and line.split(" ")[0].upper() in
         ("G0", "G1", "$J=G53", "$J=G91", "$J=G21", "$H") or (fired and ts > fired + 0.05 and line.startswith("$J"))]
check("…e dopo il riavvio non manda più movimenti (solo lo spegnimento del laser)", not moves and
      any(line == "M5 S0" for ts, line in sent if fired and ts > fired), moves[:4])
text = log_text(log)
check("C. nel registro: inizio, riavvio e fine con il motivo",
      "calibrazione della camera: inizio" in text and "si è riavviata da sola" in text
      and "calibrazione della camera: interrotta" in text and "riavviata da sola durante il movimento" in text, text[-400:])
c.disconnect_port()
spin(0.3)

# ====================================================================== D. dal puntino al cartone
print("--- D. passaggio al cartone")
c, log = connect()
c.home()
until(lambda: c.homed and c.last_status.get("state") == "Idle", 15)
c.sim.speedup = 40
ac, res, asks, sent, fired = calibrate(c, "auto", on_ask=lambda a: a.cancel())
check("testa che copre il puntino: si passa al bersaglio inciso e la richiesta del cartone spiega perché",
      asks and "primo metodo" in asks[0] and "secondo metodo" in asks[0] and "cartone" in asks[0], asks[:1])
check("annullata lì: messaggio e riga nel registro", res.get("msg") == "Calibrazione annullata"
      and "puntino non visto" in log_text(log) and "calibrazione della camera: annullata" in log_text(log),
      (res.get("msg"), log_text(log)[-300:]))
ac, res, asks, sent, fired = calibrate(c, "target", on_ask=lambda a: a.cancel())
check("metodo «bersaglio inciso» scelto apposta: la richiesta del cartone resta quella di sempre",
      asks and "primo metodo" not in asks[0] and "cartone" in asks[0], asks[:1])
c.disconnect_port()

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
