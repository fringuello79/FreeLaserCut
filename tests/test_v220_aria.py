# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.22.0: nella configurazione guidata, il passo «L'aria (air assist)».

Chi non è pratico non sa se la sua scheda accende l'aria con M8 o con M7: due prove di due secondi a laser spento,
poi si dice con quale è partita. Qui: i comandi che partono davvero (e l'aria che si spegne sempre), i casi in cui
la prova non si fa, che cosa finisce nel profilo.
Uso: python tests/test_v220_aria.py [banco]
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_LANG"] = "it"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui import dialogs_setup as DS  # noqa: E402
from freelasercut.ui.dialogs_setup import SetupWizard  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def until(fn, t=5.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        spin(0.02)
    return bool(fn())


w = MainWindow()
sent = []  # le righe come arrivano alla scheda (simulatore), nell'ordine vero


def ascolta():
    sim, scrivi = w.ctl.sim, w.ctl.sim.write

    def write(data):
        for riga in bytes(data).decode("ascii", "replace").replace("\r", "\n").split("\n"):
            if riga.strip():
                sent.append(riga.strip().upper())
        return scrivi(data)

    sim.write = write


def aria():
    return [s for s in sent if s in ("M7", "M8", "M9")]


check("la prova dura due secondi", DS.AIR_TEST_MS == 2000)
DS.AIR_TEST_MS = 400  # nelle prove non si aspetta

# ---------------------------------------------------------------------- laser non collegato
print("--- non collegato")
d = SetupWizard(w)
check("6 passi: l'aria è il quinto, prima della fine", d.stack.count() == 6 and DS.AIR_PAGE == 4)
d.go(4)
check("«Passo 5 di 6»", d.step_lab.text() == "Passo 5 di 6", d.step_lab.text())
check("parte su «lascio com'è»", d.air_choice() == "keep")
check("senza laser: niente pulsanti di prova, lo dice e dice che cosa resta",
      d.air_box.isHidden() and "non è collegato" in d.air_intro.text() and "M8" in d.air_intro.text(), d.air_intro.text())
d.air_test(1)
spin(0.2)
check("…e una prova chiesta lo stesso non manda niente", not aria() and "non è pronto" in d.air_lab.text())
prima = (w.profile.air_on, w.profile.air_off, w.profile.air_chosen)
d.go(5)
check("riepilogo: lasciando com'è non si parla dell'aria", "Aria" not in d.summary.text())
d.accept()
check("«lascio com'è»: il profilo non cambia", (w.profile.air_on, w.profile.air_off, w.profile.air_chosen) == prima)

# ---------------------------------------------------------------------- collegato (simulatore)
print("--- collegato")
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 1
until(lambda: w.ctl.board_settings, 8)
spin(0.5)
ascolta()
sent.clear()
d = SetupWizard(w)
d.go(4)
check("collegato: i due pulsanti ci sono, il testo spiega che non serve saperlo",
      not d.air_box.isHidden() and "Non serve saperlo" in d.air_intro.text() and "0.4 secondi" in d.air_intro.text(),
      d.air_intro.text())
d.air_test(1)
until(lambda: "M8" in aria(), 2)
check("prova 1: parte M8 (dopo un M9 che spegne l'altra)", aria() == ["M9", "M8"] and "Prova 1" in d.air_lab.text(), aria())
until(lambda: aria().count("M9") == 2, 3)
check("…e dopo il tempo della prova l'aria si spegne da sola (M9)", aria() == ["M9", "M8", "M9"] and "aria spenta" in d.air_lab.text(), aria())
sent.clear()
d.air_test(2)
until(lambda: aria().count("M9") == 2, 3)
check("prova 2: M7, poi M9", aria() == ["M9", "M7", "M9"], aria())
sent.clear()
d.air_test(1)
d.air_test(2)
until(lambda: aria().count("M9") == 3, 3)
check("due prove una sull'altra: la prima si spegne prima che parta la seconda", aria() == ["M9", "M8", "M9", "M7", "M9"], aria())
sent.clear()
DS.AIR_TEST_MS = 6000  # prova lunga: se l'aria si spegne entro un secondo, non è stato il tempo della prova
d.air_test(1)
until(lambda: "M8" in aria(), 2)
d.go(3)
until(lambda: aria().count("M9") == 2, 1)
check("cambiando passo a prova in corso l'aria si spegne subito", aria() == ["M9", "M8", "M9"] and not d._air_timer.isActive(), aria())
d.go(4)
sent.clear()
d.air_test(2)
until(lambda: "M7" in aria(), 2)
d.reject()
until(lambda: aria().count("M9") == 2, 1)
check("chiudendo la finestra a prova in corso l'aria si spegne", aria() == ["M9", "M7", "M9"] and not d._air_timer.isActive(), aria())
d = SetupWizard(w)
d.go(4)
sent.clear()
d.air_test(1)
until(lambda: "M8" in aria(), 2)
d.go(5)
d.accept()
until(lambda: aria().count("M9") == 2, 1)
check("anche con «Fine» a prova in corso", aria() == ["M9", "M8", "M9"], aria())
DS.AIR_TEST_MS = 400
sent.clear()
w.ctl.error_raised.emit(20, "comando non supportato", "M7")
check("finestra chiusa: gli errori della scheda non la riguardano più", True)

# scheda che non conosce M7
d = SetupWizard(w)
d.go(4)
d.air_test(2)
until(lambda: "M7" in aria(), 2)
w.ctl.error_raised.emit(20, "comando non supportato", "M7")
check("la scheda non conosce il comando della prova 2: lo dice senza spaventare e indica la prova 1",
      "non è un guasto" in d.air_lab.text() and "prova 1" in d.air_lab.text() and not d._air_timer.isActive(), d.air_lab.text())
w.ctl.error_raised.emit(9, "bloccata", "M8")
check("altro rifiuto: dice l'errore", "errore 9" in d.air_lab.text(), d.air_lab.text())
testo = d.air_lab.text()
w.ctl.error_raised.emit(20, "x", "$J=G91 X10 F1500")
check("errori di altri comandi non toccano questo passo", d.air_lab.text() == testo)

# allarme e lavoro in corso
sent.clear()
stato = dict(w.ctl.last_status)
w.ctl.last_status["state"] = "Alarm"
d.air_test(1)
spin(0.2)
check("macchina in allarme: la prova non parte e dice come sbloccarla", not aria() and "homing" in d.air_lab.text(), aria())
w.ctl.last_status.clear()
w.ctl.last_status.update(stato)
w.ctl._job_active = True
d.air_test(1)
spin(0.2)
check("lavoro in corso: nessun comando", not aria(), aria())
w.ctl._job_active = False

# ---------------------------------------------------------------------- che cosa si salva
print("--- profilo")
d.air_radio["m7"].setChecked(True)
d.go(5)
check("riepilogo: «si accende con la prova 2 (M7)»", "prova 2 (M7)" in d.summary.text(), d.summary.text())
d.accept()
p = w.profile
check("scelta «prova 2»: nel profilo M7/M9, segnata come scelta a mano", p.air_cmds() == ("M7", "M9") and p.air_chosen)
check("…salvata nel file del profilo", MachineProfile.load(p.path()).air_cmds() == ("M7", "M9"))
r = RectShape(20, 10, layer=1)
w.editor.add([r], "prova")
w.editor.doc.layer(1).air = True


def comandi():
    job = gcode.generate(w.editor.doc, w.profile, gcode.JobOptions(start_from="absolute"))
    return [ln.split(";")[0].strip() for ln in job.lines]


g = comandi()
check("…e il G-code di un livello con l'aria usa M7", "M7" in g and "M8" not in g, [c for c in g if c.startswith("M")])
d = SetupWizard(w)
d.go(4)
check("riaprendo: dice com'è adesso (M7) e riparte da «lascio com'è»", "(M7)" in d.air_intro.text() and d.air_choice() == "keep")
d.air_radio["m8"].setChecked(True)
d.accept()
check("scelta «prova 1»: M8/M9", w.profile.air_cmds() == ("M8", "M9") and w.profile.air_chosen)
d = SetupWizard(w)
d.go(4)
d.air_radio["none"].setChecked(True)
d.go(5)
check("riepilogo: «nessun comando»", "nessun comando" in d.summary.text())
d.accept()
check("scelta «nessuna delle due»: nessun comando, ricordata", w.profile.air_cmds() == ("", "") and w.profile.air_chosen)
g = comandi()
check("…e nel G-code non c'è né M7 né M8", "M7" not in g and "M8" not in g)
d = SetupWizard(w)
d.go(4)
check("riaprendo con nessun comando: lo dice", "nessun comando" in d.air_intro.text(), d.air_intro.text())
d.reject()

# macchina con la ventola (M106)
w.profile.air_on, w.profile.air_off = "M106", "M107"
d = SetupWizard(w)
d.go(4)
check("macchina che usa M106: niente prove e niente domande", d.air_box.isHidden() and d.air_answers.isHidden()
      and "M106" in d.air_intro.text())
d.accept()
check("…e resta M106", w.profile.air_cmds() == ("M106", "M107"))

# simulatore con il profilo di un altro laser
altro = MachineProfile(name="Creality Falcon A1 10W", model="Creality Falcon A1 10W")
altro.save()
w.set_active_profile(altro)
d = SetupWizard(w)
d.go(4)
check("simulatore con il profilo di un altro laser: la prova qui non si fa", d._sim_other() and d.air_box.isHidden())
d.reject()

w.ctl.sim.write = type(w.ctl.sim).write.__get__(w.ctl.sim)
w.ctl.disconnect_port()
spin(0.3)
w.editor.dirty = False
w.close()
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
