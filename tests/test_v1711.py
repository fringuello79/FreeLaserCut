# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.11: aggiornamento dal programma più robusto.

Con la 0.17.10 «Scarica e installa» faceva comparire la finestra di scaricamento e la chiudeva subito senza dire
niente: lo scaricamento non riusciva, ma chiudendo la finestra QProgressDialog emette da sola «canceled», e
l'errore veniva preso per un annullamento e taciuto. Ora l'errore si vede (e finisce nel registro), e gli errori
passeggeri di GitHub (502/503/504, collegamento caduto a metà) si riprovano da soli."""
import hashlib
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

import freelasercut
from freelasercut import updater

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


check("versione 0.17.11 o successiva", updater.parse_version(freelasercut.__version__) >= (0, 17, 11),
      freelasercut.__version__)

PAYLOAD = os.urandom(700_000)
NAME = "FreeLaserCut-0.99.0-Setup.exe"
SUMS = f"{hashlib.sha256(PAYLOAD).hexdigest()}  {NAME}\n".encode()
plan = {}   # percorso → elenco di risposte da dare in ordine: codice HTTP, "cut" (si interrompe a metà) o "ok"
hits = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        hits[self.path] = hits.get(self.path, 0) + 1
        todo = plan.get(self.path, [])
        what = todo.pop(0) if todo else "ok"
        body = SUMS if self.path.endswith(".txt") else PAYLOAD
        if isinstance(what, int):
            self.send_response(what)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if what == "cut":
            self.wfile.write(body[: len(body) // 3])
            self.wfile.flush()
            self.close_connection = True
            return
        self.wfile.write(body)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"


def rel(tag):
    return updater.Release("0.99.0", "v0.99.0", "x", "", "", f"{base}/{tag}/{NAME}", NAME, len(PAYLOAD),
                           f"{base}/{tag}/SHA256SUMS.txt")


waits = []
nowait = waits.append
d = tempfile.mkdtemp()

plan.update({"/a/SHA256SUMS.txt": [504, 504], f"/a/{NAME}": [503]})
p = updater.download(rel("a"), dest_dir=d, wait=nowait)
check("GitHub risponde 504 e 503 per qualche secondo: riprova da solo e scarica",
      open(p, "rb").read() == PAYLOAD and hits["/a/SHA256SUMS.txt"] == 3 and hits[f"/a/{NAME}"] == 2, hits)
check("…aspettando un po' tra un tentativo e l'altro", waits[:2] == [2, 5], waits)

plan.update({f"/b/{NAME}": ["cut"]})
p = updater.download(rel("b"), dest_dir=d, wait=nowait)
check("collegamento caduto a metà: ricomincia e il file è integro (SHA-256)", open(p, "rb").read() == PAYLOAD
      and hits[f"/b/{NAME}"] == 2, hits)

plan.update({"/c/SHA256SUMS.txt": [504, 504, 504, 504]})
try:
    updater.download(rel("c"), dest_dir=d, wait=nowait)
    msg = ""
except updater.UpdateError as exc:
    msg = str(exc)
check("GitHub che continua a non rispondere: messaggio chiaro, con il sito", "non risponde" in msg and "504" in msg
      and "sito" in msg and hits["/c/SHA256SUMS.txt"] == updater.RETRIES, msg)

plan.update({f"/e/{NAME}": [404]})
try:
    updater.download(rel("e"), dest_dir=d, wait=nowait)
    msg = ""
except updater.UpdateError as exc:
    msg = str(exc)
check("file che non c'è (404): nessun tentativo inutile", hits[f"/e/{NAME}"] == 1 and msg, msg)
check("nessun pezzo di file lasciato in giro", not [f for f in os.listdir(d) if f.endswith(".part")], os.listdir(d))

# ---------------------------------------------------------------- la finestra
from freelasercut.profile import config_dir
from freelasercut.ui.main_window import MainWindow

w = MainWindow()
um = w.updates
um.release = rel("f")
um.mode = "installer"
shown = []
um._error = lambda title, m: shown.append(m)
plan.update({"/f/SHA256SUMS.txt": [500, 500, 500]})
updater.RETRY_WAIT = (0, 0)
um.install(um.release)
import time

end = time.time() + 15
while time.time() < end and not shown:
    app.processEvents()
    time.sleep(0.02)
check("scaricamento non riuscito: la finestra si chiude e l'errore SI VEDE (prima spariva senza dire niente)",
      shown and "non risponde" in shown[-1] and um._dlg is None, shown)
log = open(os.path.join(config_dir(), "flc.log"), encoding="utf-8").read()
check("…e l'errore finisce nel registro (quindi anche nel rapporto per l'assistenza)",
      "Errore aggiornamento" in log and "500" in log, log[-300:])

shown.clear()
um._cancel = True
um._on_downloaded(None, "Scaricamento annullato.")
check("annullato dalla persona: nessun messaggio d'errore", not shown)

srv.shutdown()
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
