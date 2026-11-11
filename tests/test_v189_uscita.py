# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.9: finestra chiusa = programma chiuso. Installando la 0.18.8 l'installatore si è fermato su «FreeLaserCut è
aperto»: in Gestione attività c'era un processo di FreeLaserCut rimasto vivo senza finestra.

1 i timer del collegamento con la scheda (puntino, Lucciola, risveglio…) non tengono più in vita il processo;
2 alla chiusura `app.finish_exit` aspetta al massimo qualche secondo i fili ancora al lavoro, scrive nel registro chi
  non finiva e che cosa faceva, e chiude comunque il processo con il codice giusto.
"""
import os
import re
import subprocess
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
from PySide6.QtCore import QCoreApplication  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication([])
from freelasercut.grbl import SIM_PORT, GrblController  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


# ================================================================== timer
src = open(os.path.join(ROOT, "freelasercut", "grbl.py"), encoding="utf-8").read()
check("nel collegamento con la scheda nessun timer può più trattenere il processo",
      len(re.findall(r"threading\.Timer\(", src)) == 1 and "t.daemon = True" in src, re.findall(r".*threading\.Timer\(.*", src))
c = GrblController()
c.connect_port(SIM_PORT)
c.sim.speedup = 50
until(lambda: c.board_settings and c.last_status.get("state") == "Idle")
c.fire(True, 0.5, max_pct=0.5, timeout_s=300, s_max=1000)
check("timer della Lucciola (5 minuti): non tiene vivo il programma", c._fire_timer is not None and c._fire_timer.daemon)
c.fire_extend(300)
check("…nemmeno dopo che il tempo è ripartito", c._fire_timer.daemon and c._fire_timer.is_alive())
c.fire(False)
c.disconnect_port()

# ================================================================== chiusura
helper = os.path.join(ROOT, "tests", "_uscita_appesa.py")


def run(mode, code):
    d = tempfile.mkdtemp()
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, helper, d, mode, str(code)], capture_output=True, text=True, timeout=30)
        rc, out = r.returncode, r.stdout
    except subprocess.TimeoutExpired:
        rc, out = None, ""
    m = re.search(r"^registro (.+)$", out, re.M)
    log = open(m.group(1), encoding="utf-8").read() if m and os.path.exists(m.group(1)) else ""
    return rc, time.time() - t0, out, log


rc, dt, out, log = run("pulito", 0)
check("chiusura normale: il processo finisce subito, codice 0, niente nel registro",
      rc == 0 and "NON DEVO" not in out and "=== chiusura" not in log, (rc, round(dt, 1), log[-200:]))
rc, dt, out, log = run("appeso", 3)
check("un filo che non finisce mai: il processo si chiude lo stesso in pochi secondi (prima restava aperto)",
      rc == 3 and dt < 20 and "NON DEVO" not in out, (rc, round(dt, 1)))
check("…il registro dice chi non finiva", "=== chiusura" in log and "filo-appeso" in log, log[-400:])
check("…e che cosa stava facendo", "filo_che_non_finisce" in log, log[-600:])
mw = open(os.path.join(ROOT, "freelasercut", "ui", "main_window.py"), encoding="utf-8").read()
check("il programma vero chiude così (dopo aver salvato le preferenze)",
      re.search(r"code = app\.exec\(\)\s+try:.*?win\.qs\.sync\(\).*?finish_exit\(code\)", mw, re.S) is not None)

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
