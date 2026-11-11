# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Aiuto di test_v189_uscita: un programma con un filo che non finisce mai (o nessuno), che chiude con
app.finish_exit. Argomenti: cartella del registro, «appeso» oppure «pulito», codice d'uscita."""
import os
import sys
import threading
import time

os.environ["APPDATA"] = sys.argv[1]
os.environ["XDG_CONFIG_HOME"] = sys.argv[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from freelasercut import app as flc_app  # noqa: E402

flc_app._install_crash_log()
print("registro", flc_app._FAULT_FH.name, flush=True)


def filo_che_non_finisce():
    time.sleep(120)


if sys.argv[2] == "appeso":
    threading.Thread(target=filo_che_non_finisce, name="filo-appeso").start()  # non «daemon»: terrebbe vivo il processo
    time.sleep(0.2)
flc_app.finish_exit(int(sys.argv[3]), grace=1.0)
print("NON DEVO ARRIVARE QUI", flush=True)
