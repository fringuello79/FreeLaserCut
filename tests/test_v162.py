# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.16.2: dal rapporto di un utente (Longer B1, scheda LGT su ESP32).
- homing interrotto da un allarme (6 = reset durante l'homing): la scheda si riavvia e si sblocca da sola, e
  FreeLaserCut prendeva la posizione di quel momento (-3,24) per lo zero: coordinate «negative», contorno e lavoro
  fuori dall'area (errore 15, allarme 2). Ora un homing con un allarme non vale;
- lavoro fermato da un allarme seguito dal riavvio della scheda: il messaggio dice l'allarme;
- foto del test dal telefono: la finestra con il codice QR si apre davanti."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
order = []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: order.append("messaggio") or QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.grbl import GrblController

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


class FakeSer:
    def __init__(self):
        self.sent = []

    def write(self, data):
        self.sent.append(bytes(data))
        return len(data)

    def close(self):
        pass


def controller():
    c = GrblController()
    c._ser = FakeSer()
    c.port = "COM3"
    c.board_settings = {}
    c._backup_done = True
    ev = {"homed": [], "end": []}
    c.homed_changed.connect(lambda h, neg: ev["homed"].append((h, neg)))
    c.job_finished.connect(lambda ok, msg: ev["end"].append((ok, msg)))
    return c, ev


def feed(c, *lines):
    for line in lines:
        c._dispatch(line)


# ---------------------------------------------------------------- il caso del rapporto (07/11, 08:27)
c, ev = controller()
c.home()
feed(c, "ALARM:6", "ok", "Grbl 1.1 ['$' for help]", "FW:LGT V1.2.3|MB:LS_ESP32", "[MSG:'$H'|'$X' to unlock]",
     "[MSG:Caution: Unlocked]", "<Idle|MPos:-3.240,-3.240,0.000|FS:0,0>", "<Idle|MPos:-3.240,-3.240,0.000|FS:0,0>")
check("homing interrotto dall'allarme 6 e scheda che si sblocca da sola: l'homing non vale",
      not c.homed and c.negative_space is None and not any(h for h, _ in ev["homed"]), (c.homed, c.negative_space, ev))

# ---------------------------------------------------------------- homing riuscito (stesso rapporto, 08:31:45)
c.home()
feed(c, "<Home|MPos:-5.000,-5.000,0.000|FS:2828,0>", "ok", "<Idle|MPos:0.000,0.000,0.000|FS:0,0>")
check("homing riuscito subito dopo: valido, coordinate positive (Longer B1)",
      c.homed and c.negative_space is False and ev["homed"][-1] == (True, False), ev["homed"])

# ---------------------------------------------------------------- GRBL classico: coordinate negative dopo l'homing
c2, ev2 = controller()
c2.home()
feed(c2, "ok", "<Idle|MPos:-1.500,-1.500,0.000|FS:0,0>")
check("GRBL classico (0 = fondo corsa): coordinate negative riconosciute come prima", c2.homed and c2.negative_space is True)

# ---------------------------------------------------------------- allarmi «homing fallito» e riavvio a metà
for code in (8, 9):
    c3, ev3 = controller()
    c3.home()
    feed(c3, f"ALARM:{code}", "ok", "<Idle|MPos:-3.000,-3.000,0.000|FS:0,0>")
    check(f"allarme {code} durante l'homing: non vale", not c3.homed and c3.negative_space is None)
c4, ev4 = controller()
c4.home()
feed(c4, "Grbl 1.1 ['$' for help]", "<Idle|MPos:-2.000,-2.000,0.000|FS:0,0>")
check("scheda riavviata durante l'homing (senza «ok»): non vale", not c4.homed and c4.negative_space is None)
c5, ev5 = controller()
c5.home()
feed(c5, "ok", "ALARM:1", "<Idle|MPos:-3.000,-3.000,0.000|FS:0,0>")
check("allarme fra l'«ok» dell'homing e il primo stato: non vale", not c5.homed and c5.negative_space is None)

# ---------------------------------------------------------------- lavoro fermato da un allarme con riavvio
c6, ev6 = controller()
c6._job_active = True
c6._job_total, c6._job_done = 8593, 3
feed(c6, "ALARM:2", "<Alarm|MPos:-3.240,-3.240,0.000|FS:0,0>", "Grbl 1.1 ['$' for help]")
check("lavoro fermato dall'allarme 2 e scheda riavviata: il messaggio dice l'allarme (non «si è riavviata»)",
      ev6["end"] and not ev6["end"][-1][0] and "allarme 2" in ev6["end"][-1][1].lower(), ev6["end"])
c7, ev7 = controller()
c7._job_active = True
c7._job_total, c7._job_done = 100, 3
feed(c7, "Grbl 1.1 ['$' for help]")
check("riavvio senza allarme (calo di tensione): messaggio di prima", ev7["end"] and "riavviata" in ev7["end"][-1][1])

# ---------------------------------------------------------------- foto del test dal telefono
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui.dialogs_materials import MaterialTestDialog

w = MainWindow()
orig = w.phone_dialog


def phone():
    order.append("codice QR")
    return orig()


w.phone_dialog = phone
mt = MaterialTestDialog(w.profile, parent=w)
order.clear()
d = mt.photo_from_phone()
check("foto dal telefono: prima la spiegazione, poi la finestra del codice QR (così resta davanti)",
      order == ["messaggio", "codice QR"] and d is not None, order)
d2 = w.phone_dialog()
check("riaperta: stessa finestra, riportata davanti", d2 is d)
d.close()

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
