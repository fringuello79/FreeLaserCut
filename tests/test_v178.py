# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.8: ricevitore dei rapporti del progetto attivo, pulsante «Invia» nella finestra del rapporto."""
import io
import json
import os
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

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
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

import freelasercut
from freelasercut import support

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


from freelasercut.updater import parse_version

check("versione 0.17.8 o successiva", parse_version(freelasercut.__version__) >= (0, 17, 8), freelasercut.__version__)
u = support.SUPPORT_URL
check("indirizzo del ricevitore: app web di Google in https che finisce con /exec",
      u.startswith("https://script.google.com/macros/s/") and u.endswith("/exec"), u)
check("nessuna password né chiave nell'indirizzo", "?" not in u and "key=" not in u.lower())
check("Invia disponibile", support.can_send())

# l'invio va proprio a quell'indirizzo, come testo semplice (niente preflight) e legge la risposta
seen = []


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(req, timeout=60):
    seen.append(req)
    return Resp(json.dumps({"ok": True, "codice": "FLC-PROVA"}).encode())


zp = os.path.join(tempfile.mkdtemp(), "r.zip")
open(zp, "wb").write(b"PK\x05\x06" + b"\0" * 18)
ok, res = support.send(zp, "FLC-PROVA", {"oggetto": "prova"}, "", "riassunto", opener=opener)
req = seen[-1] if seen else None
check("invio al ricevitore del progetto", ok and req is not None and req.full_url == u, res)
check("invio con POST in testo semplice", req is not None and req.get_method() == "POST"
      and "text/plain" in (req.get_header("Content-type") or ""))
body = json.loads(req.data.decode()) if req is not None else {}
check("nel pacchetto codice, versione e rapporto", body.get("codice") == "FLC-PROVA"
      and body.get("versione") == freelasercut.__version__ and body.get("zip"), list(body))

# Google risponde al POST con un rinvio (302) a una pagina da leggere con GET: urllib lo segue così


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(302)
        self.send_header("Location", "/echo")
        self.end_headers()

    def do_GET(self):
        b = json.dumps({"ok": True, "codice": "FLC-302"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
local = f"http://127.0.0.1:{srv.server_port}/exec"


def follow(req, timeout=60):
    r2 = urllib.request.Request(local, data=req.data, headers=dict(req.header_items()), method="POST")
    return urllib.request.urlopen(r2, timeout=timeout)


ok2, res2 = support.send(zp, "FLC-302", None, "", "", opener=follow)
check("risposta di Google dopo il rinvio letta correttamente", ok2 and res2 == "FLC-302", res2)
srv.shutdown()

# l'ultimo errore dei registri va nel riassunto: serve al ricevitore per raggruppare i rapporti uguali
from freelasercut import diag

cfg = tempfile.mkdtemp()
with open(os.path.join(cfg, "flc.log"), "w", encoding="utf-8") as fh:
    fh.write("avvio\nTraceback (most recent call last):\n  File x\nValueError: could not convert string to float: '12,5'\nfine\n")
err = diag.last_error_text(cfg)
check("ultimo errore del programma letto dai registri", err.startswith("ValueError: could not convert"), err)
check("nessun errore: riga vuota", diag.last_error_text(tempfile.mkdtemp()) == "")

from freelasercut.ui.main_window import MainWindow
from freelasercut.ui.dialogs_report import ReportDialog

w = MainWindow()
d = ReportDialog(w)
check("finestra del rapporto: pulsante Invia presente", not d.b_send.isHidden())
check("…ma spento finché non si dà il consenso", not d.b_send.isEnabled())
d.consent.setChecked(True)
check("…acceso con il consenso", d.b_send.isEnabled())
d.close()

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
os._exit(code_)
