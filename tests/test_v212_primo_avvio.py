# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: primo avvio (rapporto E698, solboricua, MacBook Pro M1, 0.21.1: «Segmentation fault» durante la pulizia della
memoria di Python mentre nasceva la finestra principale, subito dopo la finestra della prima scelta, aperta con
`ChoiceDialog().exec()` senza tenerla in una variabile).

Correzione: la finestra iniziale si tiene in vita e si distrugge del tutto prima di andare avanti
(`run_startup_dialog`); la finestra principale si costruisce con la pulizia automatica della memoria sospesa e una
raccolta sola alla fine (`build_main_window`); le porte del sistema del Mac in fondo all'elenco, segnate.
Il crollo vero si vede solo su un Mac ARM: lì (mac.yml) questa prova gira 20 volte di fila (FLC_PRIMO_AVVIO_GIRI).
Uso: python tests/test_v212_primo_avvio.py [classica|banco]
"""
import gc
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
UI = "banco" if "banco" in sys.argv else "classica"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import shiboken6  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import machines  # noqa: E402
from freelasercut.ui import banco, panels_design  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info else ""), flush=True)


ROUNDS = max(1, int(os.environ.get("FLC_PRIMO_AVVIO_GIRI", "2") or 2))
print(f"--- primo avvio, {ROUNDS} giri ({UI})")
gc_during = []
real_init = panels_design.PaletteBar.__init__


def spy_init(self, *a, **k):  # la barra dove è crollato sul Mac: con la pulizia della memoria attiva?
    gc_during.append(gc.isenabled())
    gc.collect()  # una raccolta forzata proprio lì, dove sul Mac arrivava quella automatica
    real_init(self, *a, **k)


panels_design.PaletteBar.__init__ = spy_init
dead, alive_after, gc_after, wins = [], [], [], []
for k in range(ROUNDS):
    os.environ.pop("FLC_UI", None)
    banco.settings().remove("ui_mode")
    check_choice = banco.needs_choice()
    dlg = banco.ChoiceDialog()
    want = UI if k % 2 == 0 else ("classica" if UI == "banco" else "banco")
    QTimer.singleShot(80, lambda d=dlg, m=want: d._start(m))
    mw.run_startup_dialog(dlg)
    dead.append(not shiboken6.isValid(dlg))
    del dlg
    w = mw.build_main_window()
    gc_after.append(gc.isenabled())
    alive_after.append(w.ui_mode == want and w.acts.get("save") is not None)
    w.show()
    app.processEvents()
    w.editor.dirty = False
    w.close()
    w.deleteLater()
    app.processEvents()
    wins.append(check_choice)
check("la scelta iniziale serve davvero (impostazioni vuote)", all(wins))
check("la finestra della scelta è distrutta del tutto prima della finestra principale", all(dead), dead)
check("la finestra principale nasce con la scelta fatta, a ogni giro", all(alive_after), alive_after)
check("mentre si costruiscono le barre la pulizia automatica della memoria è sospesa", gc_during and not any(gc_during),
      gc_during[:4])
check("…e dopo è di nuovo attiva", all(gc_after))
panels_design.PaletteBar.__init__ = real_init


class Boom(Exception):
    pass


def boom():
    raise Boom()


try:
    mw.build_main_window(boom)
except Boom:
    pass
check("se la finestra principale non nasce, la pulizia della memoria torna attiva lo stesso", gc.isenabled())
gc.disable()
mw.build_main_window(lambda: None)
check("…e se era spenta da prima resta come l'aveva lasciata chi chiama", not gc.isenabled())
gc.enable()
import inspect  # noqa: E402
import re  # noqa: E402

src = inspect.getsource(mw.main)
check("in main() nessuna finestra senza genitore aperta con «…Dialog().exec()», e la finestra principale nasce da "
      "build_main_window", not re.search(r"Dialog\(\)\.exec\(", src) and "build_main_window()" in src
      and "run_startup_dialog(" in src)

print("--- porte del Mac (stesso rapporto)")


class P:
    def __init__(self, device, desc="n/a", vid=None, pid=None):
        self.device, self.description, self.vid, self.pid, self.hwid, self.manufacturer = device, desc, vid, pid, "", ""


mac = [P("/dev/cu.Bluetooth-Incoming-Port"), P("/dev/cu.debug-console"), P("/dev/cu.AirPodsPro"),
       P("/dev/cu.usbserial-14130", "USB Serial", 0x1A86, 0x7523), P("/dev/cu.wlan-debug"),
       P("/dev/cu.usbmodem1101"), P("/dev/cu.JBL-Flip5")]  # scheda USB senza chip noto; cassa Bluetooth
real_platform = sys.platform
sys.platform = "darwin"
try:
    ports = machines.describe_ports(mac, extra=[])
finally:
    sys.platform = real_platform
names = [p.device for p in ports]
check("la scheda laser (CH340) è la prima", names[0] == "/dev/cu.usbserial-14130", names)
check("poi le altre porte USB, anche senza chip riconosciuto", names[1] == "/dev/cu.usbmodem1101"
      and not ports[1].system, names)
check("Bluetooth, cuffie, casse e console di debug: in fondo e segnate «non è un laser»",
      all(p.system and "non è un laser" in p.label() for p in ports[2:]) and len(ports) == 7
      and "/dev/cu.JBL-Flip5" in names[2:], [(p.device, p.system) for p in ports])
check("…e mai proposte come probabile laser", not any(p.likely for p in ports[2:]))
check("su Windows e Linux le porte normali non cambiano", not machines.system_port("COM3", platform="win32")
      and not machines.system_port("/dev/ttyUSB0", platform="linux") and not machines.system_port("/dev/ttyS0", platform="linux")
      and not machines.system_port("/dev/cu.usbmodem1101", platform="darwin"))

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
