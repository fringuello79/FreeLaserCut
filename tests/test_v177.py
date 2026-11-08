# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.7: rapporto per l'assistenza più completo e «Invia un rapporto all'assistenza» (al ricevitore del
progetto o con la mail già scritta), solo con il consenso all'informativa privacy; linguette dei piani più leggibili."""
import io
import json
import os
import sys
import tempfile
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PIL import Image
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QTransform
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
OPENED = []
QDesktopServices.openUrl = staticmethod(lambda u: OPENED.append(u.toString()) or True)

from freelasercut import diag, support
from freelasercut.core import photo
from freelasercut.core.document import ImageShape, RectShape

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


from freelasercut.ui.main_window import MainWindow

w = MainWindow()
w.show()
doc = w.editor.doc
r = RectShape(30, 20)
r.apply(QTransform.fromTranslate(50, 50))
w.editor.add([r], "rettangolo")
pil = Image.new("RGB", (64, 48), (120, 130, 140))
doc.images["a"] = pil
im = ImageShape("a", 40, 30, layer=2)
im.apply(QTransform.fromTranslate(120, 60))
im.photo = photo.PhotoSettings(effect="sketch", subject_hints={"rect": [0.1, 0.1, 0.9, 0.9], "keep": [],
                                                               "remove": [], "auto": False}).to_dict()
w.editor.add([im], "foto")
w.editor.select([im])
w.acts["select_all"].trigger() if "select_all" in w.acts else None
w.editor.select([im])
w.build_job()
w.acts["about"].trigger = None  # non apro finestre
if "zoom_fit" in w.acts:
    w.acts["zoom_fit"].trigger()

# ---------------------------------------------------------------- rapporto
code = diag.new_code()
check("codice del rapporto: FLC-AAAAMMGG-HHMM-xxxx", code.startswith("FLC-") and len(code) == 22, code)
user = {"oggetto": "si ferma", "facevi": "Avvia sulla foto", "aspettavi": "incisione completa", "successo": "si ferma a metà",
        "frequenza": "sempre"}
path = os.path.join(tempfile.mkdtemp(), "r.zip")
names = diag.make_report(path, w, w.comm_log, user=user, screenshot=b"\x89PNG finto", code=code)
z = zipfile.ZipFile(path)
txt = {n: z.read(n).decode("utf-8", errors="replace") for n in z.namelist() if not n.endswith(".png")}
check("descrizione della persona nel rapporto", "si ferma a metà" in txt.get("descrizione.txt", ""))
check("sistema: codice, separatore decimale, simulatore", code in txt["sistema.txt"] and "separatore decimale" in
      txt["sistema.txt"] and "Simulatore in uso: no" in txt["sistema.txt"])
check("ultimo lavoro: livelli e prime righe del G-code, non il disegno", "Livello" in txt.get("ultimo-lavoro.txt", "")
      and "Prime righe del G-code" in txt.get("ultimo-lavoro.txt", ""))
check("porte USB", "Porte seriali viste" in txt.get("porte.txt", ""))
check("azioni recenti dai menu", bool(txt.get("azioni-recenti.txt", "").strip()) or not w.crumbs, list(w.crumbs)[:3])
check("impostazioni di Prepara foto della foto selezionata (con gli aiuti del soggetto)",
      '"subject_hints"' in txt.get("foto-selezionata.txt", ""))
check("immagine della finestra solo se scelta", "finestra.png" in names)
path2 = os.path.join(tempfile.mkdtemp(), "r2.zip")
n2 = diag.make_report(path2, w, w.comm_log, user=user, code=code, photo=False)
check("…senza immagine e senza foto se non scelte", "finestra.png" not in n2 and "foto-selezionata.txt" not in n2)
home = os.path.expanduser("~")
check("nessun percorso della cartella utente", all(home not in t for t in txt.values()))

# ---------------------------------------------------------------- invio
REAL_URL = support.SUPPORT_URL
support.SUPPORT_URL = ""  # qui si prova il caso senza ricevitore
check("senza indirizzo di invio il pulsante Invia non c'è", not support.can_send())
mt = support.mailto(code, user, "riassunto")
check("mail già scritta: destinatario, oggetto con il codice, descrizione", mt.startswith("mailto:freelasercut@gmail.com?")
      and code in QUrl.fromPercentEncoding(mt.encode()) and "si ferma a metà" in QUrl.fromPercentEncoding(mt.encode()))
sent = []


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_open(req, timeout=0):
    sent.append(json.loads(req.data.decode("utf-8")))
    return FakeResp(json.dumps({"ok": True, "codice": sent[-1]["codice"]}).encode())


ok, info = support.send(path, code, user, "a@b.it", "riassunto", url="https://script.google.com/macros/s/X/exec",
                        opener=fake_open)
check("invio: arriva il rapporto con descrizione, contatto e .zip", ok and info == code and sent[-1]["app"] == "FreeLaserCut"
      and sent[-1]["contatto"] == "a@b.it" and "si ferma a metà" in sent[-1]["descrizione"] and len(sent[-1]["zip"]) > 100)
check("indirizzo non https: niente invio", support.send(path, code, url="http://x/exec")[0] is False)


def bad_open(req, timeout=0):
    return FakeResp(json.dumps({"ok": False, "errore": "troppi rapporti oggi"}).encode())


check("errore del ricevitore riportato", support.send(path, code, url="https://x/exec", opener=bad_open) ==
      (False, "troppi rapporti oggi"))

# ---------------------------------------------------------------- finestra
from freelasercut.ui import dialogs_report
from freelasercut.ui.dialogs_report import ReportDialog

d = ReportDialog(w)
check("finestra: senza consenso niente invio né email", not d.b_send.isEnabled() and not d.b_mail.isEnabled())
check("finestra: il pulsante Invia c'è solo con l'indirizzo del ricevitore", d.b_send.isHidden())
check("informativa nella finestra con il codice del rapporto e il collegamento",
      any(d.code in lab.text() and "privacy" in lab.text() for lab in d.findChildren(dialogs_report.QLabel)))
check("immagine della finestra non scelta di partenza", not d.with_shot.isChecked())
d.close()
support.SUPPORT_URL = "https://script.google.com/macros/s/X/exec"
dialogs_report.support.send = lambda p, c, u, ct, s: (sent.append({"zipfile": p, "user": u}) or (True, c))
d2 = ReportDialog(w)
d2.subject.setText("si ferma")
d2.happened.setPlainText("si ferma a metà")
d2.consent.setChecked(True)
check("con l'indirizzo e il consenso: Invia attivo", not d2.b_send.isHidden() and d2.b_send.isEnabled())
d2.send()
import time

end = time.time() + 5
while time.time() < end and "inviato" not in d2.status.text():
    app.processEvents()
    time.sleep(0.02)
check("rapporto inviato: codice mostrato", "inviato" in d2.status.text() and sent[-1]["user"]["successo"] == "si ferma a metà",
      d2.status.text())
d3 = ReportDialog(w)
d3.consent.setChecked(True)
import subprocess

subprocess.Popen = lambda *a, **k: None
p3 = d3.send_mail()
check("«Invia per email…»: mail già scritta e rapporto pronto da trascinare",
      OPENED and OPENED[-2 if len(OPENED) > 1 else -1].startswith("mailto:freelasercut@gmail.com") and os.path.exists(p3))
d3.close()
check("Aiuto → Invia un rapporto all'assistenza…", "send_report" in w.acts)

# ---------------------------------------------------------------- linguette dei piani
pb = getattr(w, "plate_bar", None)
if pb is not None:
    pb.refresh()
    col = pb.tabs.tabTextColor(w.editor.doc.current).name()
    check("linguetta del piano: scritta scura", col in ("#0b1220", "#ffffff"), col)

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
os._exit(code_)
