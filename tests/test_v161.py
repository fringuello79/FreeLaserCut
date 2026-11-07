# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.16.1: velocità della porta seriale (baud) anche a mano.
- di partenza resta 115200 e «Riconosci la macchina» la trova da solo;
- Laser → Velocità della porta seriale… (o tasto destro su Connetti): si sceglie o si scrive, si prova sulla porta
  senza cambiare niente, si salva nel profilo e Connetti la usa;
- collegato ma la scheda non risponde: avviso con Riconosci e Velocità a mano."""
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
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import machines
from freelasercut.grbl import SIM_PORT
from freelasercut.profile import MachineProfile
from freelasercut.ui import dialogs_serial as DS

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


check("di partenza 115200 (quella standard di GRBL)", MachineProfile().baud == 115200 and DS.STANDARD == 115200)
check("valori scritti a mano: numeri da 1200 a 2000000, il resto no",
      DS.parse_baud("250000") == 250000 and DS.parse_baud(" 9600 ") == 9600 and DS.parse_baud("12") is None
      and DS.parse_baud("") is None and DS.parse_baud("3000000") is None)

from freelasercut.ui.main_window import MainWindow

w = MainWindow()
laser_menu = next(m.menu() for m in w.menuBar().actions() if m.menu() and w.acts["identify"] in m.menu().actions())
acts = laser_menu.actions()
check("Laser → Velocità della porta seriale…, subito dopo Riconosci la macchina",
      w.acts["serial_speed"] in acts and acts.index(w.acts["serial_speed"]) == acts.index(w.acts["identify"]) + 1)
check("tasto destro su Connetti: menu con Riconosci e Velocità", w.btn_connect.contextMenuPolicy() == Qt.CustomContextMenu)

dlg = DS.SerialSpeedDialog(w)
check("la finestra parte dalla velocità del profilo", dlg.speed.currentText() == "115200" and dlg.b_ok.isEnabled())
dlg.speed.setCurrentText("12")
check("valore non valido: non si salva e lo dice", not dlg.b_ok.isEnabled() and dlg.note.isVisibleTo(dlg))
dlg.b_std.click()
check("«Rimetti 115200»", dlg.speed.currentText() == "115200")

# prova sul simulatore: la scheda risponde
dlg.port.addItem("Simulatore", SIM_PORT)
dlg.port.setCurrentIndex(dlg.port.count() - 1)
dlg.speed.setCurrentText("250000")
txt = dlg.test(wait=True)
check("«Prova questa velocità»: la scheda risponde (simulatore)", "risponde" in txt and "250000" in txt, txt)
check("…e con il simulatore spiega che la velocità conta solo sulle porte USB", dlg.note.isVisibleTo(dlg))
check("provare non cambia il profilo", w.profile.baud == 115200)

# porta che non risponde
calls = []
orig_probe = machines.probe


def fake_probe(port, bauds=(), opener=None, **k):
    calls.append((port, tuple(bauds)))
    return None


machines.probe = fake_probe
dlg.port.addItem("COM99", "COM99")
dlg.port.setCurrentIndex(dlg.port.count() - 1)
txt = dlg.test(wait=True)
check("porta che non risponde: prova solo la velocità scelta e lo dice", calls == [("COM99", (250000,))]
      and "Nessuna risposta" in txt, (calls, txt))
machines.probe = orig_probe

# salva
dlg.accept()
check("«Salva nel profilo»: la velocità va nel profilo e nel suo file", w.profile.baud == 250000
      and '"baud": 250000' in open(w.profile.path(), encoding="utf-8").read())
got = []
w.ctl.connect_port = lambda port, baud=115200: got.append((port, baud)) or False
w.port_combo.addItem("COM99", "COM99")
w.port_combo.setCurrentIndex(w.port_combo.count() - 1)
w.toggle_connection()
check("Connetti usa la velocità salvata", got == [("COM99", 250000)], got)

# connesso: non si prova, si può salvare per la prossima volta
w.ctl._ser = object()
d2 = DS.SerialSpeedDialog(w)
d2.port.setCurrentIndex(d2.port.findData("COM99"))
check("laser connesso: «Prova» spento e spiegazione", not d2.b_test.isEnabled() and "disconnettilo" in d2.note.text())

# avviso se la scheda collegata non risponde
w.ctl.port = "COM99"
w.ctl.status_time = 0.0
w.ctl.last_reply = 0.0
w.banner.hide()
w._check_silent(time.time() - 6)
shown = not w.banner.isHidden()
check("collegato ma nessuna risposta: avviso con Riconosci e Velocità a mano", shown)
w.banner.hide()
w.ctl.status_time = time.time()
w._check_silent(time.time() - 6)
check("se la scheda risponde: nessun avviso", w.banner.isHidden())
w.ctl.port = SIM_PORT
w.ctl.status_time = 0.0
w._check_silent(time.time() - 6)
check("simulatore o Wi-Fi: nessun avviso (la velocità non conta)", w.banner.isHidden())
w.ctl._ser = None

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.TerminateProcess(k32.GetCurrentProcess(), code)
os._exit(code)
