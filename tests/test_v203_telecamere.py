# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.20.3, segnalazione di Ale (15/11) provando la 0.20.2 con una telecamera sola, quella della testa:
«mi dà in automatico come telecamera del piano quella che in realtà è della testa e non me la fa cambiare; mi dice che
è già calibrata e non mi fa fare una nuova calibrazione».
- le telecamere si scelgono sempre, fra tutte quelle collegate: quella già usata dall'altro compito passa di qua
  (prima la scelta veniva rifiutata, e con una telecamera sola quella della testa non si poteva scegliere);
- la telecamera scelta per la testa non viene più presa da sola per il piano, e si riapre all'avvio anche con
  «Nessuna telecamera» sul piano (prima il suo elenco restava vuoto);
- «Calibra» si può sempre premere, anche con una calibrazione già fatta: se manca qualcosa lo dice;
- una calibrazione nuova non viene più scartata senza chiedere."""
import os
import sys
import tempfile
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import time

import numpy as np
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

app = QApplication([])
ASK = {"n": 0, "text": "", "answer": QMessageBox.Yes}


def _question(*a, **k):
    ASK["n"] += 1
    ASK["text"] = a[2] if len(a) > 2 else ""
    return ASK["answer"]


QMessageBox.question = staticmethod(_question)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

import freelasercut.camera_panel as cp  # noqa: E402
import freelasercut.head_camera_ui as hcu  # noqa: E402
from freelasercut import camera as camera_mod  # noqa: E402
from freelasercut import head_camera as hc  # noqa: E402
from freelasercut import head_grid as hg  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.i18n import tr  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def spin(sec=0.2):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        time.sleep(0.01)


def until(fn, sec=10.0):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        if fn():
            return True
        time.sleep(0.02)
    return False


LOG = []  # ("apri" | "chiudi", indice): la stessa telecamera non deve mai essere aperta due volte


class FakeSrc:
    def __init__(self, idx, size=(1920, 1080)):
        self.index, self.mode, self.black, self.size = idx, "dshow", False, size
        self.closed = False
        self.autofocus = ""
        LOG.append(("apri", idx))

    def get(self, after=0, timeout=0):
        return np.full((self.size[1], self.size[0], 3), 120, np.uint8)

    def frames(self, n=3, after=0):
        return [self.get() for _ in range(n)]

    def close(self):
        self.closed = True
        LOG.append(("chiudi", self.index))


def fake_cs(idx, *a, **k):
    return FakeSrc(idx, k.get("size") or (1920, 1080))


def never_twice():
    """Nel registro delle aperture nessuna telecamera è stata aperta mentre era già aperta."""
    is_open = set()
    for what, idx in LOG:
        if what == "apri":
            if idx in is_open:
                return False
            is_open.add(idx)
        else:
            is_open.discard(idx)
    return True


cp.CameraSource = fake_cs
hcu.CameraSource = fake_cs
THUMB = np.zeros((90, 160, 3), np.uint8)
ONE = [(0, "USB Camera  ·  1920×1080", (1920, 1080), THUMB)]
TWO = ONE + [(1, "HD Webcam  ·  1280×720", (1280, 720), THUMB)]
FOUND = {"cams": ONE, "calls": 0}


def fake_list(max_index=6, skip=()):
    FOUND["calls"] += 1
    return [c for c in FOUND["cams"] if c[0] not in skip]


cp.list_cameras = fake_list
camera_mod.usb_camera_names = lambda: {}

w = MainWindow()
w.show()
panel, card = w.camera, w.camera.head
until(lambda: not panel._searching and FOUND["calls"] >= 1, 8)
spin(0.5)

# ================================================================ 1. una telecamera sola, mai scelto niente
check("una telecamera sola, nessuna scelta fatta: finisce sul piano da sola (come prima)", panel.bed_index() == 0
      and card.index() is None, (panel.bed_index(), card.index()))
i0 = card.combo.findData(0)
check("…ma nell'elenco della testa c'è, si può scegliere, e si vede che ora è la camera del piano",
      i0 > 0 and card.combo.model().item(i0).isEnabled() and tr("ora camera del piano") in card.combo.itemText(i0),
      card.combo.itemText(i0) if i0 > 0 else "")
check("il riquadro della testa dice qual è la camera del piano; la scheda Camera dice qual è quella della testa",
      "USB Camera" in card.bed_line.text() and tr("nessuna") in panel.head_line.text()
      and tr("Scegli o calibra…") in panel.head_line.text(), (card.bed_line.text(), panel.head_line.text()))
check("nel riquadro della testa c'è ⟳ per cercare di nuovo le telecamere", card.btn_search.text() == "⟳")
card.combo.setCurrentIndex(i0)
card._chosen(i0)
spin(0.2)
check("scelta come camera della testa: passa alla testa e il piano resta senza telecamera",
      card.index() == 0 and panel.bed_index() is None and panel.combo.currentData() is None,
      (card.index(), panel.bed_index()))
check("…prima si chiude sul piano e poi si apre sulla testa (mai aperta due volte)", never_twice()
      and LOG[-2:] == [("chiudi", 0), ("apri", 0)], LOG[-4:])
check("…e la scelta resta: testa = camera 0, piano = nessuna", w.qs.value("head_camera_choice") in (0, "0")
      and w.qs.value("camera_choice") == "none")
check("la scheda Camera ora nomina la camera della testa", "USB Camera" in panel.head_line.text(), panel.head_line.text())

# ---- al prossimo avvio (stesse scelte salvate, niente aperto)
card.close_src()
panel.combo.blockSignals(True)
panel.combo.clear()
panel.combo.blockSignals(False)
calls = FOUND["calls"]
panel.search()  # come all'avvio: non «a mano»
ok = until(lambda: FOUND["calls"] > calls and not panel._searching and card.index() == 0, 8)
check("al riavvio, con «Nessuna telecamera» sul piano: le telecamere si cercano lo stesso e quella della testa si riapre "
      "(prima il suo elenco restava vuoto)", ok and panel.bed_index() is None and card.combo.findData(0) > 0,
      (FOUND["calls"] - calls, card.index(), panel.bed_index()))

# ---- lo stato che lascia la 0.20.2: testa scelta = camera 0, piano mai scelto (la prendeva lui)
card.close_src()
w.qs.setValue("camera_choice", "")
w.qs.setValue("head_camera_choice", 0)
panel.combo.blockSignals(True)
panel.combo.clear()
panel.combo.blockSignals(False)
panel.on_found(list(ONE))
spin(0.3)
check("testa già scelta e piano mai scelto: la telecamera della testa non viene più presa da sola per il piano",
      card.index() == 0 and panel.bed_index() is None and never_twice(), (card.index(), panel.bed_index()))
w.qs.setValue("camera_choice", "none")
w.qs.setValue("head_camera_choice", "none")
card.release()
panel.combo.blockSignals(True)
panel.combo.clear()
panel.combo.blockSignals(False)
calls = FOUND["calls"]
panel.search()
spin(0.5)
check("nessuna telecamera voluta né sul piano né sulla testa: all'avvio non se ne accende nessuna (come prima)",
      FOUND["calls"] == calls and not panel._searching)

# ================================================================ 2. due telecamere
FOUND["cams"] = TWO
w.qs.setValue("camera_choice", 0)
w.qs.setValue("head_camera_choice", 1)
panel.on_found(list(TWO))
spin(0.3)
check("due telecamere: 0 sul piano, 1 sulla testa", panel.bed_index() == 0 and card.index() == 1)
j1 = panel.combo.findData(1)
check("nell'elenco del piano quella della testa si riconosce e si può scegliere", j1 > 0
      and panel.combo.model().item(j1).isEnabled() and tr("ora camera della testa") in panel.combo.itemText(j1))
panel.combo.setCurrentIndex(j1)  # la persona sceglie per il piano la telecamera della testa
panel._remember_choice(j1)
spin(0.2)
check("scelta per il piano la telecamera della testa: passa al piano, la testa resta senza (e lo ricorda)",
      panel.bed_index() == 1 and card.index() is None and card.combo.currentData() is None
      and w.qs.value("head_camera_choice") == "none" and never_twice(), (panel.bed_index(), card.index()))
check("…e nell'elenco del piano non c'è più scritto «ora camera della testa»",
      tr("ora camera della testa") not in panel.combo.itemText(panel.combo.currentIndex()), panel.combo.currentText())
i1 = card.combo.findData(1)
check("…mentre in quello della testa la 1 è segnata «ora camera del piano»",
      tr("ora camera del piano") in card.combo.itemText(i1) and tr("ora camera del piano") not in
      card.combo.itemText(card.combo.findData(0)))
k0 = card.combo.findData(0)
card.combo.setCurrentIndex(k0)
card._chosen(k0)
spin(0.2)
check("l'altra telecamera sulla testa: ognuna al suo posto (piano 1, testa 0)", panel.bed_index() == 1 and card.index() == 0
      and never_twice())
card.combo.setCurrentIndex(i1)
card._chosen(i1)
spin(0.2)
check("scambio dalla testa: prendo quella del piano → testa 1, piano senza", card.index() == 1 and panel.bed_index() is None
      and never_twice(), (card.index(), panel.bed_index()))
j0 = panel.combo.findData(0)
panel.combo.setCurrentIndex(j0)
panel._remember_choice(j0)
spin(0.2)
check("…e do al piano l'altra: piano 0, testa 1", panel.bed_index() == 0 and card.index() == 1 and never_twice())
# scelta salvata per la testa ma non aperta: se la persona la dà al piano, la testa non se la riprende
card.close_src()
w.qs.setValue("head_camera_choice", 0)
panel._remember_choice(panel.combo.currentIndex())
check("camera salvata per la testa (non aperta) scelta a mano per il piano: la testa la dimentica",
      w.qs.value("head_camera_choice") == "none")
panel.on_found(list(TWO))
spin(0.3)
check("nuova ricerca: il piano tiene la sua, la testa non apre niente da sola", panel.bed_index() == 0 and card.index() is None
      and never_twice())

# la stessa telecamera salvata per tutti e due i compiti (numeri cambiati, scelte fatte con versioni diverse)
w.qs.setValue("head_camera_choice", 0)  # il piano ha aperta la 0
panel.on_found(list(TWO))
spin(0.3)
check("telecamera aperta sul piano e salvata anche per la testa: la testa non la apre una seconda volta da sola",
      panel.bed_index() == 0 and card.index() is None and never_twice(), (panel.bed_index(), card.index()))
panel.combo.setCurrentIndex(0)  # all'avvio: niente aperto, tutte e due le scelte salvate sulla 0
spin(0.1)
panel.combo.blockSignals(True)
panel.combo.clear()
panel.combo.blockSignals(False)
w.qs.setValue("camera_choice", 0)
w.qs.setValue("head_camera_choice", 0)
panel.on_found(list(TWO))
spin(0.3)
check("all'avvio con la stessa telecamera salvata per piano e testa: va alla testa, il piano resta senza (mai due volte)",
      card.index() == 0 and panel.bed_index() is None and never_twice(), (panel.bed_index(), card.index()))
card.release()
w.qs.setValue("camera_choice", 0)
panel.on_found(list(TWO))
spin(0.3)

# ================================================================ 3. «Calibra» si può sempre premere
check("senza camera della testa: «Calibra…» acceso (prima spento senza spiegare)", card.btn_cal.isEnabled()
      and not card.btn_view.isEnabled())
r = card.open_window(calibrate=True)
check("…premuto senza camera: dice di scegliere prima la telecamera", r is None and card.note.isVisibleTo(card)
      and tr("Scegli prima qui sopra quale telecamera è quella della testa.") == card.note.text(), card.note.text())
i1 = card.combo.findData(1)
card.combo.setCurrentIndex(i1)
card._chosen(i1)
spin(0.2)
check("scelta la telecamera: la riga del messaggio sparisce", not card.note.isVisibleTo(card) and card.index() == 1)
card.model = hc.HeadModel(hc.natural_matrix(0.1, 0, False), (4.0, 33.0), hc.HEAD_SIZE)
card._check_model_size()
card.update_state()
check("già calibrata: lo dice, e il pulsante diventa «Calibra di nuovo…», sempre acceso",
      card.ready() and "✓" in card.state.text() and card.btn_cal.text() == tr("Calibra di nuovo…") and card.btn_cal.isEnabled(),
      (card.state.text()[:40], card.btn_cal.text()))
win = card.open_window()
spin(0.2)
check("nella vista della testa: «Rifai la calibrazione completa…» acceso anche con il laser scollegato",
      win is not None and win.b_cal.isEnabled() and tr("Rifai la calibrazione completa…") in win.b_cal.text())
check("…e la vista dice perché gli altri comandi sono spenti (laser non connesso)",
      not win.b_laser.isEnabled() and tr("Connetti il laser per usare i comandi della camera della testa.") == win.info.text(),
      win.info.text())
r = win.start_calibration()
check("premuto con il laser scollegato: dice di connetterlo (niente parte, la calibrazione di prima resta)",
      r is None and card.cal is None and card.model is not None and "connetti il laser" in card.note.text().lower(),
      card.note.text())

# con il laser connesso (simulatore) e una calibrazione già fatta: la finestrella della calibrazione si apre
w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.connected, 10)
w.ctl.home()
until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 40)
spin(0.5)
seen = {"dlg": 0}
orig_exec = hcu.HeadCalDialog.exec


def _exec(self):
    seen["dlg"] += 1
    return QDialog.Rejected


hcu.HeadCalDialog.exec = _exec
card.update_state()
r = win.start_calibration()
check("laser connesso e camera già calibrata: la nuova calibrazione parte (si apre la sua finestrella)",
      seen["dlg"] == 1 and r is None and card.model is not None and card.btn_cal.isEnabled(), seen)
hcu.HeadCalDialog.exec = orig_exec
win.close()
w.ctl.disconnect_port()
until(lambda: not w.ctl.connected, 5)
spin(0.3)

# ---- camera del piano: stessi pulsanti che spiegano
panel.update_state()
check("camera del piano: «Calibra automaticamente» e i punti a mano si possono premere anche senza laser",
      panel.btn_cal.isEnabled() and panel.btn_manual.isEnabled())
panel.cal_text.setText("")
panel.calibrate()
check("…premuto senza laser: dice di connettere la macchina", "Connetti la macchina" in panel.cal_text.text()
      and panel.autocam is None, panel.cal_text.text())
panel.combo.setCurrentIndex(0)
spin(0.1)
panel.cal_text.setText("")
panel.manual_points()
check("…premuto senza telecamera del piano: dice di sceglierla", "telecamera che guarda il piano" in panel.cal_text.text(),
      panel.cal_text.text())

# ================================================================ 4. calibrazione nuova: decide sempre la persona
class _Sig:
    def __init__(self, fn):
        self.fn = fn

    def emit(self, text):
        self.fn(text)


class _Cal:
    """Solo quello che serve a HeadGridCalibration._compare_old."""

    def __init__(self, answer):
        self.old_model = "vecchia"
        self.report = {"obs_ctl": object()}
        self._go = threading.Event()
        self._cancel = threading.Event()
        self._choice = None
        self.asked = []
        self.need_choice = _Sig(lambda text: (self.asked.append(text), hg.HeadGridCalibration.choose(self, answer)))


class _M:
    frame_size = (1280, 720)


orig_err = hg.model_errors_px
new_model = _M()
_Cal.old_model = _M()


def errors(model, obs, _new=new_model):
    return np.full(20, ERR["new"] if model is _new else ERR["old"])


hg.model_errors_px = errors
ERR = {"new": 2.0, "old": 0.5}
c1 = _Cal(True)
c1.old_model = _M()
m, msg = hg.HeadGridCalibration._compare_old(c1, new_model, "riuscita")
check("calibrazione nuova meno precisa di quella di prima: non viene più scartata da sola, lo chiede",
      len(c1.asked) == 1 and "meno precisa" in c1.asked[0] and "Tengo quella nuova?" in c1.asked[0], c1.asked)
check("…risposta «sì» (camera spostata): si tiene quella nuova", m is new_model and msg == "riuscita")
c2 = _Cal(False)
c2.old_model = _M()
m, msg = hg.HeadGridCalibration._compare_old(c2, new_model, "riuscita")
check("…risposta «no»: resta quella di prima, e lo dice", m is None and "Tengo la calibrazione di prima" in msg, msg)
ERR = {"new": 0.5, "old": 2.0}
c3 = _Cal(False)
c3.old_model = _M()
m, msg = hg.HeadGridCalibration._compare_old(c3, new_model, "riuscita")
check("calibrazione nuova più precisa: si tiene senza domande (come prima)", m is new_model and not c3.asked)
hg.model_errors_px = orig_err

card.shutdown()
code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(code)
