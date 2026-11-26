# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.3: dopo «Copia» il processo finiva con un errore di segmentazione all'uscita.

Gli appunti di Qt prendono il QMimeData creato in Python e lo cancellano solo nei distruttori statici di Qt, dopo la
fine dell'interprete (giro completo delle prove: test_v230_distanze_fisse 72/72 e poi codice -11). Ora le forme copiate
si tolgono dagli appunti a fine processo (atexit). Ogni caso gira in un processo a parte e si guarda il codice d'uscita.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info != "" and not cond else ""), flush=True)


PROVA = r'''
import os, sys, tempfile
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
sys.path.insert(0, ROOT)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from freelasercut.core.document import Document, RectShape
from freelasercut.ui.editor import Editor, MIME
ed = Editor(Document())
r = RectShape(5, 5)
ed.doc.add(r)
ed.select([r])
modo = sys.argv[1]
if modo in ("copia", "incolla", "taglia", "due"):
    (ed.cut if modo == "taglia" else ed.copy)()
if modo == "incolla":
    ed.paste()
if modo == "due":
    ed.copy()
if modo == "altro":  # appunti di un altro programma: a fine processo non si toccano
    QGuiApplication.clipboard().setText("testo di un altro programma")
md = QGuiApplication.clipboard().mimeData()
print("ha_forme" if md is not None and md.hasFormat(MIME) else "senza_forme")
'''.replace("ROOT", repr(ROOT))


def gira(modo):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    env["APPDATA"] = env["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
    p = subprocess.run([sys.executable, "-c", PROVA, modo], capture_output=True, text=True, timeout=120, env=env)
    return p.returncode, p.stdout.strip()


for modo, nome in (("niente", "senza copiare"), ("copia", "Copia"), ("incolla", "Copia e Incolla"),
                   ("taglia", "Taglia"), ("due", "due Copia di seguito")):
    rc, out = gira(modo)
    check(f"{nome}: il processo finisce senza errore (codice 0)", rc == 0, (rc, out))
rc, out = gira("copia")
check("…e mentre il programma è aperto le forme sono negli appunti (Copia funziona come prima)",
      rc == 0 and out == "ha_forme", (rc, out))
rc, out = gira("altro")
check("appunti di un altro programma: nessun errore e non sono forme di FreeLaserCut", rc == 0 and out == "senza_forme",
      (rc, out))

print(f"\n{sum(results)}/{len(results)} superati")
sys.exit(0 if all(results) else 1)
