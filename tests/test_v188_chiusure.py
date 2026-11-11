# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.8, da due rapporti di Ale (FLC-20261111-0100-6BC1 e FLC-20261111-0102-905B, 0.18.7).

1 Chiusura improvvisa («access violation») subito dopo aver mandato un rapporto: la finestra del rapporto era stata
  chiusa mentre l'invio era in corso; il filo dell'invio teneva l'ultimo riferimento alla finestra e, finendo,
  distruggeva i suoi oggetti di Qt da un filo che non è quello della finestra. Ora `ui.bg.run` li tiene vivi finché
  il filo è finito e li lascia andare dal filo della finestra. La prova guarda IN QUALE FILO muoiono gli oggetti.
2 «Si è piantato e poi chiuso» senza nessuna traccia nel registro: ora, se la finestra non risponde per più di
  8 secondi, flc_crash.log dice che cosa stava facendo il programma (e quando ha ripreso).
"""
import gc
import os
import sys
import tempfile
import threading
import time
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import app as flc_app  # noqa: E402
from freelasercut import support  # noqa: E402
from freelasercut.ui import bg  # noqa: E402

results = []
MAIN = threading.get_ident()


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


class Sig(QObject):
    done = Signal(object)


class Win(QDialog):
    def __init__(self):
        super().__init__()
        self.sig = Sig()  # senza genitore, come nella finestra del rapporto
        self.got = []
        self.sig.done.connect(self.got.append)


def scenario(start):
    """Una finestra avvia un lavoro di 0,4 s e viene chiusa e dimenticata subito. -> filo in cui muore."""
    died = []
    w = Win()
    weakref.finalize(w, lambda: died.append(threading.get_ident()))

    def work(win=w):
        time.sleep(0.4)
        win.sig.done.emit("fatto")
    t = start(work, w)
    del work
    w.close()
    del w
    gc.collect()
    until(lambda: not t.is_alive(), 5)
    t.join()
    until(lambda: died, 3)
    gc.collect()
    return died


plain = scenario(lambda work, w: (lambda t: (t.start(), t)[1])(threading.Thread(target=work, daemon=True)))
check("la prova vede il difetto: con un filo qualsiasi la finestra chiusa muore nel filo secondario",
      plain and plain[0] != MAIN, plain)
safe = scenario(lambda work, w: bg.run(work, w, w.sig))
check("con bg.run la finestra chiusa muore nel filo della finestra, a lavoro finito", safe == [MAIN], (safe, MAIN))
check("…e non resta niente in sospeso", until(lambda: bg.pending() == 0, 3), bg.pending())
w2 = Win()
t2 = bg.run(lambda win=w2: (time.sleep(0.2), win.sig.done.emit("ok")), w2, w2.sig)
check("finestra rimasta aperta: il risultato arriva come sempre", until(lambda: w2.got == ["ok"], 3), w2.got)

# ================================================================== la finestra del rapporto vera
import subprocess  # noqa: E402

env = dict(os.environ)
env["FLC_UI"] = os.environ["FLC_UI"]
out = subprocess.run([sys.executable, "-X", "faulthandler", os.path.join(ROOT, "tests", "_rapporto_chiuso.py"), "8"],
                     capture_output=True, text=True, timeout=180, env=env)
lines = (out.stdout or "").splitlines()
check("finestra del rapporto chiusa 8 volte durante l'invio: il programma resta aperto (con la 0.18.7 si chiudeva)",
      "FINE SENZA CRASH" in lines and sum(l.startswith("chiusa") for l in lines) == 8 and "Fatal" not in (out.stderr or ""),
      (lines[-3:], (out.stderr or "")[-300:]))
from freelasercut.ui.main_window import MainWindow  # noqa: E402

win = MainWindow()
src = {n: open(os.path.join(ROOT, "freelasercut", "ui", n), encoding="utf-8").read()
       for n in ("dialogs_report.py", "dialogs_machine.py", "dialogs_net.py", "dialogs_netcam.py", "dialogs_serial.py")}
check("le finestre che lavorano in secondo piano usano tutte bg.run",
      all("bg.run(" in s and "threading.Thread(target=work" not in s and "threading.Thread(target=lambda" not in s
          for s in src.values()), [n for n, s in src.items() if "bg.run(" not in s])

# ================================================================== la finestra che si pianta
flc_app._install_crash_log()
log = flc_app._FAULT_FH.name
flc_app.HANG_S = 1.5
check("sorveglianza dei blocchi avviata (una volta sola)", flc_app.start_hang_watch(app) is True
      and flc_app.start_hang_watch(app) is False)
until(lambda: False, 2.5)
check("finestra che risponde: nel registro nessun blocco", "=== blocco" not in open(log, encoding="utf-8").read())


def stuck_here_for_the_test():
    time.sleep(4.0)  # la finestra «piantata»: nessun evento per 4 secondi


stuck_here_for_the_test()
until(lambda: "=== ripresa" in open(log, encoding="utf-8").read(), 5)
text = open(log, encoding="utf-8").read()
check("finestra ferma per 4 s: il registro dice «blocco» e da quanti secondi", "=== blocco" in text and "non risponde da" in text)
check("…dice dov'era ferma (la funzione e la riga)", "stuck_here_for_the_test" in text, text[-600:])
check("…e quando ha ripreso", "=== ripresa" in text)
check("un blocco solo viene scritto una volta sola", text.count("=== blocco") == 1, text.count("=== blocco"))

win.editor.dirty = False
win.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
