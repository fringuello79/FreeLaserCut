# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.16.3: schede ESP32 che restano mute dopo l'apertura della porta (visto con il chip USB CH9102 e
grblHAL): se in 2,5 secondi la scheda non ha mai risposto, FreeLaserCut le manda un reset morbido (Ctrl+X), una volta
sola, come il pulsante di reset sulla scheda; poi richiede $I e $$. Niente in Wi-Fi e con il simulatore."""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QCoreApplication

app = QCoreApplication([])
from freelasercut import grbl
from freelasercut.grbl import SIM_PORT, GrblController
from freelasercut.sim import SimSerial

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info)


def until(fn, t=8.0):
    end = time.time() + t
    while time.time() < end and not fn():
        app.processEvents()
        time.sleep(0.02)
    return fn()


class FakeSer:
    def __init__(self):
        self.sent = []

    def write(self, data):
        self.sent.append(bytes(data))
        return len(data)

    def close(self):
        pass


def muted(port):
    c = GrblController()
    c._ser = FakeSer()
    c.port = port
    msgs = []
    c.message.connect(msgs.append)
    return c, msgs


# ---------------------------------------------------------------- la regola
t0 = time.time()
c, msgs = muted("COM5")
c.status_time, c.last_reply = 0.0, 0.0
check("scheda muta dopo la connessione: reset morbido (Ctrl+X) e messaggio", c._wake_if_silent(t0)
      and b"\x18" in c._ser.sent and any("reset" in m for m in msgs), (c._ser.sent, msgs))
time.sleep(1.7)
check("…poi richiede di nuovo $I e $$", b"$I\n" in c._ser.sent and b"$$\n" in c._ser.sent, c._ser.sent)
c2, _ = muted("COM5")
c2.status_time = time.time()
check("la scheda ha già risposto: nessun reset", not c2._wake_if_silent(t0) and b"\x18" not in c2._ser.sent)
c3, _ = muted("COM5")
c3.status_time, c3.last_reply = 0.0, time.time()
check("ha risposto «ok» (senza stato): nessun reset", not c3._wake_if_silent(t0))
for port in (SIM_PORT, "tcp://192.168.1.110:8080"):
    c4, _ = muted(port)
    c4.status_time, c4.last_reply = 0.0, 0.0
    check(f"{'simulatore' if port == SIM_PORT else 'Wi-Fi'}: nessun reset", not c4._wake_if_silent(t0)
          and b"\x18" not in c4._ser.sent)


# ---------------------------------------------------------------- scheda vera simulata: muta finché non riceve Ctrl+X
class MuteUntilReset(SimSerial):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.awake = False
        self.resets = 0

    def write(self, data):
        if not self.awake:
            if 0x18 in bytes(data):
                self.awake = True
                self.resets += 1
                return super().write(b"\x18")
            return len(data)  # come la scheda bloccata: niente risposte
        if 0x18 in bytes(data):
            self.resets += 1
        return super().write(data)


boards = []


class FakeSerialModule:
    @staticmethod
    def Serial(*a, **k):
        b = MuteUntilReset()
        boards.append(b)
        return b


orig = grbl.serial
grbl.serial = FakeSerialModule
ctl = GrblController()
info = []
ctl.info_ready.connect(info.append)
ok = ctl.connect_port("COM9", 250000)
check("collegata a 250000 baud (scheda muta all'apertura)", ok and boards)
woke = until(lambda: ctl.status_time > 0 and info, 8.0)
check("dopo il reset la scheda risponde: stato e $I arrivano da soli", woke and boards[0].awake, (ctl.status_time, info[:1]))
time.sleep(3.0)
check("un reset solo", boards[0].resets == 1, boards[0].resets)
ctl.disconnect_port()

# scheda normale (risponde subito): nessun reset
boards.clear()


class Normal(SimSerial):
    resets = 0

    def write(self, data):
        if 0x18 in bytes(data):
            Normal.resets += 1
        return super().write(data)


class NormalModule:
    @staticmethod
    def Serial(*a, **k):
        return Normal()


grbl.serial = NormalModule
ctl2 = GrblController()
ctl2.connect_port("COM9", 115200)
until(lambda: ctl2.status_time > 0, 5.0)
time.sleep(3.0)
check("scheda che risponde subito: nessun reset (come prima)", Normal.resets == 0 and ctl2.status_time > 0)
ctl2.disconnect_port()
grbl.serial = orig

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
os._exit(code)
