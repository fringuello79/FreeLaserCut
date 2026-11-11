# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Aiuto di test_v188_chiusure: apre Aiuto → Invia un rapporto, preme Invia e chiude la finestra mentre l'invio (finto,
lento) è in corso, più volte. Con la 0.18.7 il programma si chiudeva di colpo: per questo gira in un processo a parte.
Alla fine stampa «FINE SENZA CRASH»."""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ.setdefault("FLC_UI", "classica")
os.environ["FLC_NO_DIALOGS"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer
app=QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import support
from freelasercut.ui.main_window import MainWindow
def slow(path, code, user, contact, summary):
    time.sleep(0.6)
    return True, code
support.send=slow; support.can_send=lambda: True
w=MainWindow(); w.show()
N=int(sys.argv[1]) if len(sys.argv)>1 else 6
def one(i):
    def later():
        d=w._report_dlg
        d.consent.setChecked(True); d.send()
        QTimer.singleShot(150, d.reject)
    QTimer.singleShot(50, later)
    w.send_report_dialog()
    print("chiusa", i, flush=True)
for i in range(N):
    one(i)
    t=time.time()
    while time.time()-t<1.2: app.processEvents(); time.sleep(0.005)
print("FINE SENZA CRASH", flush=True)
os._exit(0)
