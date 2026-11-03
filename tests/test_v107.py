# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10.7: la scelta della telecamera si ricorda. Con «Nessuna telecamera» FreeLaserCut non apre più
nessuna camera all'avvio né alla connessione (prima si accendeva sempre la webcam del PC)."""
import sys, os, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
from freelasercut import camera_panel

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()

probes, opened = [], []
THUMB = np.zeros((90, 160, 3), np.uint8)
def fake_list(max_index=6, skip=()):
    probes.append(1)
    return [(0, "Camera 0  ·  1280×720 (webcam del PC)", (1280, 720), THUMB),
            (2, "Camera 2  ·  1920×1080", (1920, 1080), THUMB)]
class FakeSource:
    def __init__(self, index, *a, **k):
        self.index = index; self.size = (1280, 720); opened.append(index)
    def get(self, after=0, timeout=0.1):
        return None
    def close(self):
        opened.append(("chiusa", self.index))
camera_panel.list_cameras = fake_list
camera_panel.CameraSource = FakeSource

from freelasercut.ui.main_window import MainWindow
w = MainWindow()
cam = w.camera
until(lambda: probes and not cam._searching)
check("prima volta (nessuna scelta salvata): cerca le telecamere", probes and cam.choice() is None)
i0 = cam.combo.findData(None)
cam.combo.setCurrentIndex(i0); cam.combo.activated.emit(i0)
check("scelta «Nessuna telecamera»: ricordata e camera chiusa", cam.choice() == "none" and cam.src is None
      and w.qs.value("camera_choice") == "none")
probes.clear(); opened.clear()
cam.search()                       # come all'avvio
w.ctl.connection_changed.emit(True, "x"); until(lambda: False, 0.6)   # come alla connessione della macchina
check("con «Nessuna» all'avvio e alla connessione non si apre nessuna camera (niente webcam accesa)",
      not probes and not opened and cam.src is None, f"{probes} {opened}")
check("si spiega perché la camera è spenta", "scelta tua" in cam.state.text(), cam.state.text())
w2 = MainWindow()                  # nuovo avvio con la stessa preferenza
until(lambda: False, 0.8)
check("nuovo avvio: la scelta resta e la webcam non si accende", w2.camera.choice() == "none" and w2.camera.src is None
      and not probes, f"{probes} {opened}")
cam.search(manual=True)
until(lambda: probes and not cam._searching)
check("⟳ cerca comunque, ma non accende niente da solo", probes and cam.src is None and cam.combo.count() == 3)
i2 = cam.combo.findData(2)
cam.combo.setCurrentIndex(i2); cam.combo.activated.emit(i2)
check("scelta della camera 2: aperta e ricordata", cam.src is not None and cam.src.index == 2 and cam.choice() == 2)
cam._close_src(); cam.combo.blockSignals(True); cam.combo.clear(); cam.combo.blockSignals(False)
probes.clear(); opened.clear()
cam.search()
until(lambda: probes and not cam._searching)
check("al riavvio si riapre la camera scelta (non la webcam del PC)", cam.src is not None and cam.src.index == 2
      and 0 not in opened, opened)
for x in (w, w2):
    x.editor.dirty = False
    x.qs.setValue("autosave_pending", False)
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
