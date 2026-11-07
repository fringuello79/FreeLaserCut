# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.3: dalle immagini di un utente su GitHub (grblHAL su ESP32 con chip USB CH9102).
- all'apertura della porta l'ESP32 restava in modalità di programmazione: muto anche dopo il Ctrl+X della 0.16.3,
  ripartiva solo con il pulsante. Ora, se resta muta, FreeLaserCut la riavvia dalle linee DTR/RTS della porta (come il
  pulsante, la sequenza «hard reset» dello strumento ufficiale delle ESP32), anche in «Riconosci la macchina»;
- il messaggio di avvio dell'ESP32 a un'altra velocità (caratteri illeggibili) diventa una riga che lo spiega;
- strumento Misura: linea e misura ben visibili anche sul piano chiaro."""
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication([])
from freelasercut import grbl, machines
from freelasercut.grbl import GrblController, _garbled
from freelasercut.sim import SimSerial

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def until(fn, t=12.0):
    end = time.time() + t
    while time.time() < end and not fn():
        app.processEvents()
        time.sleep(0.02)
    return fn()


BOOT_LOG = b"\xe0\x80\xf8\x00\xfe\xe0\x00\x80\xf8\x00\x80\xfe\xe0\xe0\x80\x80\xfe\x00\xf8\xf8\x80\xe0\r\n"


class EspInBootloader(SimSerial):
    """ESP32 rimasto in programmazione: non risponde a niente (nemmeno al Ctrl+X) finché non viene riavviato dal
    pulsante o dalle linee DTR/RTS (RTS acceso e poi spento con DTR spento)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        with self._cv:
            self._out.clear()  # niente banner: la scheda non sta girando GRBL
        self.awake = False
        self._dtr = True
        self._rts = True
        self.pulses = 0
        self.ctrl_x = 0

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, v):
        self._dtr = bool(v)

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, v):
        v = bool(v)
        if self._rts and not v and not self._dtr:  # fine dell'impulso di reset con il pin di avvio libero
            self.pulses += 1
            self.awake = True
            with self._cv:
                self._out.clear()
            self._emit(BOOT_LOG.decode("latin-1"))
            self._emit("\r\nGrblHAL 1.1f ['$' or '$HELP' for help]\r\n")
        self._rts = v

    def _emit(self, text):
        if isinstance(text, str) and text.startswith("\xe0"):
            with self._cv:
                self._out += BOOT_LOG
                self._cv.notify_all()
            return
        super()._emit(text)

    def write(self, data):
        if not self.awake:
            if 0x18 in bytes(data):
                self.ctrl_x += 1
            return len(data)
        return super().write(data)

    def readline(self):
        if not self.awake:
            time.sleep(0.05)
            return b""
        return super().readline()


check("righe illeggibili riconosciute, quelle vere no",
      _garbled(BOOT_LOG.decode(errors="replace").strip()) and not _garbled("GrblHAL 1.1f ['$' or '$HELP' for help]")
      and not _garbled("$130=400.000") and not _garbled("ok"))

# ---------------------------------------------------------------- collegamento: muta → Ctrl+X → riavvio dalle linee
boards = []


class Module:
    @staticmethod
    def Serial(*a, **k):
        b = EspInBootloader()
        boards.append(b)
        return b


orig = grbl.serial
grbl.serial = Module
ctl = GrblController()
console, info = [], []
ctl.line_received.connect(console.append)
ctl.info_ready.connect(info.append)
msgs = []
ctl.message.connect(msgs.append)
check("collegata a 250000 baud (ESP32 in programmazione)", ctl.connect_port("COM4", 250000) and boards)
woke = until(lambda: ctl.status_time > 0 and info, 14.0)
b = boards[0]
check("prima il Ctrl+X (non basta), poi il riavvio dalle linee: la scheda risponde da sola",
      woke and b.ctrl_x >= 1 and b.pulses == 1 and ctl.line_resets == 1, (woke, b.ctrl_x, b.pulses, msgs))
check("dopo il riavvio DTR e RTS restano spenti", not b.dtr and not b.rts)
check("il messaggio di avvio illeggibile diventa una riga che lo spiega",
      any("illeggibile" in l for l in console) and not any("�" in l for l in console), console[:4])
check("messaggi nella barra di stato: Ctrl+X e poi riavvio dalla porta USB",
      any("Ctrl+X" in m and "reset" in m for m in msgs) and any("porta USB" in m for m in msgs), msgs)
time.sleep(1.0)
check("un riavvio solo", b.pulses == 1)
ctl.disconnect_port()


class Normal(SimSerial):
    pulses = 0

    @property
    def rts(self):
        return False

    @rts.setter
    def rts(self, v):
        Normal.pulses += 1

    dtr = True


class NormalModule:
    @staticmethod
    def Serial(*a, **k):
        return Normal()


grbl.serial = NormalModule
ctl2 = GrblController()
ctl2.connect_port("COM9", 115200)
until(lambda: ctl2.status_time > 0, 5.0)
time.sleep(4.5)
check("scheda che risponde subito: nessun reset dalle linee", Normal.pulses == 0 and ctl2.line_resets == 0)
ctl2.disconnect_port()
grbl.serial = orig

c3 = GrblController()
c3._ser = object()  # porta senza linee DTR/RTS
c3.port = "COM5"
check("porta senza linee DTR/RTS: nessun errore, resta l'avviso della finestra", c3._line_reset() is False)

# ---------------------------------------------------------------- Riconosci la macchina
log = []
esp = []
r = machines.probe("COM4", bauds=(250000,), opener=lambda p, bd: esp.append(EspInBootloader()) or esp[-1], log=log.append)
check("Riconosci la macchina: ESP32 in programmazione riavviato dalle linee e letto",
      r is not None and r["baud"] == 250000 and r["settings"] and esp[0].pulses == 1, (r and r["baud"], log))
esp.clear()
r2 = machines.probe("COM4", bauds=(115200, 250000), opener=lambda p, bd: esp.append(EspInBootloader()) or esp[-1])
check("…un riavvio solo anche provando più velocità", r2 is not None and sum(e.pulses for e in esp) == 1)
r3 = machines.probe("COM9", bauds=(115200,), opener=lambda p, bd: SimSerial())
check("scheda normale: letta come prima", r3 is not None and r3["settings"])

# ---------------------------------------------------------------- strumento Misura
from freelasercut.ui import tools
from freelasercut.ui.main_window import MainWindow

w = MainWindow()
w.resize(1300, 850)
w.show()
until(lambda: False, 0.5)
cv = w.canvas
cv.set_tool("measure")
t = cv.tools["measure"] if hasattr(cv, "tools") else cv.tool
t.a, t.b = QPointF(50, 50), QPointF(150, 50)
img = QImage(400, 200, QImage.Format_ARGB32)
img.fill(QColor("#FFFFFF"))
p = QPainter(img)
from PySide6.QtGui import QTransform

t.draw(p, QTransform.fromScale(2, 2).translate(-25, -25))
p.end()
dark = sum(1 for x in range(0, 400, 2) for y in range(0, 200, 2) if QColor(img.pixel(x, y)).lightness() < 90)
orange = sum(1 for x in range(0, 400, 2) for y in range(0, 200, 2)
             if abs(QColor(img.pixel(x, y)).hue() - 22) < 12 and QColor(img.pixel(x, y)).saturation() > 150)
check("misura sul piano bianco: etichetta scura piena e linea arancio scuro", dark > 150 and orange > 40, (dark, orange))
check("colori: niente più giallo chiaro", tools.MEASURE_LINE.upper() != "#FFD43B")

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
os._exit(code)
