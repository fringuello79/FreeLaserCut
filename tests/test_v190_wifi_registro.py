# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.0: la procedura guidata del Wi-Fi lascia le prove.

La prima prova su un laser vero non è riuscita e non era rimasto niente da leggere. Ora ogni passo della procedura
scrive una riga nel registro della comunicazione e, quando la procedura arriva in fondo (riuscita o no), il registro
viene salvato nella cartella «diagnostica» (file «comunicazione-…-wifi.log»). La password non c'è mai.
"""
import os
import re
import sys
import tempfile
import time
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import diag  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui import dialogs_wifi as dw  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def wifi_files():
    return sorted(f for f in os.listdir(diag.diag_dir()) if f.endswith("-wifi.log"))


SECRET = "parolasegreta99"
w = MainWindow()
w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.board_settings and w.ctl.last_status.get("state") == "Idle")
wiz = dw.WifiWizard(w)
w.ctl.send_line(f"$54={SECRET}")
w.ctl.send_line(f"[ESP101]{SECRET}")
until(lambda: not w.ctl.busy, 5)
until(lambda: False, 0.3)
for st in ("A", "probe", "net", "write", "wait", "check"):
    wiz._set(st)
check("i passi intermedi vengono annotati nel registro, senza salvare niente",
      not wifi_files() and all(f"Wi-Fi guidato: {st}" in w.comm_log.text() for st in ("A", "write", "check")),
      wifi_files())
wiz._set("unknown")
files = wifi_files()
text = open(os.path.join(diag.diag_dir(), files[0]), encoding="utf-8").read() if files else ""
check("arrivata in fondo («non so se si è collegata»): il registro viene salvato in «diagnostica»",
      len(files) == 1 and wiz.log_file and os.path.basename(wiz.log_file) == files[0], files)
check("…con dentro i passi fatti e le righe scambiate con la scheda", "Wi-Fi guidato: write" in text
      and "Wi-Fi guidato: unknown" in text and "$54=" in text and "[ESP101]" in text, text[-400:])
check("…e mai la password", SECRET not in text and SECRET not in w.comm_log.text())
src = open(os.path.join(ROOT, "freelasercut", "ui", "dialogs_wifi.py"), encoding="utf-8").read()
used = set(re.findall(r'self\._set\("([A-Za-z0-9_]+)"\)', src))
check("i passi finali sono passi veri della procedura (nessun nome sbagliato)", set(dw.END_STATES) <= used
      and {"ok", "failed", "unknown", "find_none"} <= set(dw.END_STATES), sorted(set(dw.END_STATES) - used))
n = len(wifi_files())
time.sleep(1.1)  # i file hanno l'orario al secondo nel nome
wiz._set("ok")
check("anche quando riesce il registro viene salvato (serve per confrontare)", len(wifi_files()) == n + 1)
for st in sorted(used - set(dw.END_STATES)):
    wiz._set(st)
check("nessun altro passo salva un file", len(wifi_files()) == n + 1, wifi_files())
bare = types.SimpleNamespace(main=types.SimpleNamespace())
dw.WifiWizard._note(bare, "ok")
check("senza registro (finestra usata da sola) non si inciampa", not hasattr(bare, "log_file"))
w.ctl.disconnect_port()

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
