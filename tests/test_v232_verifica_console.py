# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.2 (Evoluzione2, rapporto FLC-20261125-2020-5831): dopo «Stop» e «Avvia» con una foto la finestra
restava ferma per 29 secondi, due volte. «Avvia» fa prima la verifica ($C): le 27 000 righe e i loro «ok» finivano
una per una nella console (e nel registro), e la finestra non ce la faceva.

Ora le righe della verifica non vanno nella console, come quelle del lavoro: della verifica si vedono l'avanzamento,
gli errori e il risultato. I comandi scritti a mano e le loro risposte restano nella console come sempre.
Uso: python tests/test_v232_verifica_console.py
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.grbl import SIM_PORT, GrblController  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def until(fn, t=20.0):
    end = time.time() + t
    while time.time() < end and not fn():
        app.processEvents()
        time.sleep(0.005)
    return fn()


c = GrblController()
sent, recv, got, prog = [], [], {}, []
c.line_sent.connect(sent.append)
c.line_received.connect(recv.append)
c.check_finished.connect(lambda r: got.__setitem__("check", r))
c.check_progress.connect(lambda d, t: prog.append((d, t)))
c.connect_port(SIM_PORT)
c.sim.speedup = 50
until(lambda: c.board_settings.get(130) is not None)
c.send_line("$I")
until(lambda: any("VER" in r for r in recv))
check("un comando scritto a mano e la sua risposta vanno nella console come sempre", "$I" in sent
      and any("VER" in r for r in recv), (sent[-3:], recv[-3:]))
sent.clear()
recv.clear()
job = ["G90 G21", "M4 S0"] + [f"G1 X{10 + (i % 200) * 0.5:.1f} Y{20 + i // 200:.1f} S{(i % 2) * 1000} F3500"
                              for i in range(3000)] + ["M5 S0"]
c.check_job(job)
check("verifica di 3000 righe: finita, senza errori", until(lambda: "check" in got, 60) and not got["check"],
      got.get("check"))
fuori = [s for s in sent if s.startswith("G1") or s.startswith("M4")]
oks = [r for r in recv if r == "ok"]
check("le righe della verifica non vanno una per una nella console (prima: 3000 righe e 3000 «ok»)",
      not fuori and len(oks) < 10, (len(fuori), len(oks)))
check("…l'avanzamento della verifica c'è (una volta ogni 200 righe)", prog and prog[-1] == (len(job), len(job))
      and len(prog) <= len(job) // 200 + 2, prog[-2:])
check("…l'entrata e l'uscita dalla verifica ($C) restano nella console", sent.count("$C") == 2, sent)
c.disconnect_port()
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
