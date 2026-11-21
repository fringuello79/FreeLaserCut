# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: freccia «Continuo» e joystick quando il piano del profilo è più grande della corsa della scheda (rapporto 3802
di giuseppe.grassano77, 0.21.1: profilo 600 × 400, scheda 450 × 440 con i limiti software accesi; «Continuo» chiedeva
X599,5, la scheda rispondeva error:15 a ogni clic e sotto le frecce non compariva niente).

A. il rettangolo raggiungibile (profilo ∩ corsa della scheda) con coordinate positive e negative, assi invertiti, piano
   ruotato; B. «Continuo» e joystick si fermano al bordo vero, senza error:15; C. rifiuto della scheda: messaggio sotto
   le frecce e «Usa le misure della macchina»; D. avviso al collegamento, una volta; E. coordinate negative (GRBL
   classico); F. il simulatore ha la corsa del profilo attivo.
Uso: python tests/test_v212_continuo.py [classica|banco]
"""
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui import jogpad  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info else ""), flush=True)


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


def near(a, b, tol=0.05):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def big_profile(**kw):
    p = MachineProfile(name="Generico 600", model="Generico 600")
    p.bed_x, p.bed_y = 600.0, 400.0
    p.homing = True
    for k, v in kw.items():
        setattr(p, k, v)
    return p


# ====================================================================== A. rettangolo raggiungibile
print("--- A. dove la testa può andare")
p = big_profile(negative_space=False)
check("coordinate positive: il piano finisce dove finisce la corsa della scheda", near(p.reach_box((450, 440)), (0, 0, 450, 400)))
p.invert_x = True
check("…X invertita: la parte raggiungibile è dall'altra parte", near(p.reach_box((450, 440)), (150, 0, 600, 400)))
p = big_profile(negative_space=True)
check("coordinate negative (-corsa..0): come la scheda vera", near(p.reach_box((450, 440)), (150, 0, 600, 400)))
p = big_profile()
check("verso delle coordinate non ancora noto: resta il piano del profilo", near(p.reach_box((450, 440)), (0, 0, 600, 400)))
check("…ma se lo sa il controllore (homing fatto) si usa quello", near(p.reach_box((450, 440), negative=False), (0, 0, 450, 400)))
check("senza limiti software: il piano del profilo", near(big_profile(negative_space=False).reach_box(None), (0, 0, 600, 400)))
check("scheda più grande del profilo: il piano del profilo", near(big_profile(negative_space=False).reach_box((800, 800)), (0, 0, 600, 400)))
r = big_profile(negative_space=False, view_rot=1)
r.bed_x, r.bed_y = 400.0, 600.0
box = r.reach_box((450, 440))
check("piano ruotato: il lato lungo che si vede in verticale si accorcia", near((box[2] - box[0], box[3] - box[1]), (400, 450)), box)
check("profilo più grande della scheda: lo dice (e con misure uguali no)", big_profile().board_smaller((450, 440)) == (450, 440)
      and big_profile().board_smaller((600, 400)) is None and big_profile().board_smaller(None) is None)

# ====================================================================== B. simulatore 450 × 440, profilo 600 × 400
print("--- B. «Continuo» e joystick al bordo vero")
w = MainWindow()
w.show()
refused = []
w.ctl.error_raised.connect(lambda code, text, line: refused.append((code, line)))
sent = []
w.ctl.line_sent.connect(sent.append)
w.set_active_profile(big_profile())
w.ctl.sim_travel = (450.0, 440.0)  # la scheda di Giuseppe
w.ctl.connect_port(SIM_PORT)
w.ctl.sim_travel = None
w.ctl.sim.speedup = 4
check("collegata al simulatore con la corsa 450 × 440", until(lambda: w.ctl.board_settings.get(130) is not None, 8)
      and w.ctl.soft_limits() == (450.0, 440.0), w.ctl.soft_limits())
spin(0.4)
check("D. al collegamento: avviso con le due misure e «Usa le misure della macchina»", w.banner.isVisibleTo(w)
      and "600 × 400" in w.banner_text.text() and "450 × 440" in w.banner_text.text(), w.banner_text.text()[:100])
w.banner.hide()
w.ctl.home()
check("homing", until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 15))
spin(0.4)
pad = w.move.pad
pad.set_mode("arrows")
pad.cont.setChecked(True)
w.goto_bed(200, 200)
until(lambda: w.canvas.head_pos() is not None and abs(w.canvas.head_pos().x() - 200) < 0.1, 10)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
spin(0.3)
del sent[:], refused[:]
pad.jog_press(1, 0)
until(lambda: w.ctl.sim.pos[0] > 449.0, 8)
spin(0.3)
pad.jog_release()
spin(0.3)
gl = [s for s in sent if s.startswith("$J=G53")]
xs = float(re.search(r"X(-?[\d.]+)", gl[0]).group(1)) if gl else None
check("«Continuo» a destra: punta a 449,5 (corsa della scheda), non a 599,5 (profilo)", xs is not None and abs(xs - 449.5) < 0.01, gl)
check("…la scheda non lo rifiuta e la testa ci arriva", not refused and abs(w.ctl.sim.pos[0] - 449.5) < 0.2, (refused, w.ctl.sim.pos))
del sent[:], refused[:]
pad.jog_press(1, 0)
spin(0.3)
pad.jog_release()
check("…già lì: non manda niente e dice che è al bordo", not [s for s in sent if s.startswith("$J")] and "bordo destro"
      in pad.readout.text(), (sent, pad.readout.text()))
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
w.goto_bed(200, 200)
until(lambda: abs(w.ctl.sim.pos[0] - 200) < 0.1, 10)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
spin(0.3)
del sent[:], refused[:]
pad.jog_press(1, 1)
until(lambda: w.ctl.sim.pos[1] > 399.0 or w.ctl.sim.pos[0] > 449.0, 8)
spin(0.3)
pad.jog_release()
spin(0.3)
check("in diagonale verso l'angolo: nessun rifiuto", not refused, refused)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
w.goto_bed(400, 200)
until(lambda: abs(w.ctl.sim.pos[0] - 400) < 0.1, 10)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
spin(0.3)
del refused[:]
joy = pad.joy
joy.set_vector(1.0, 0.0)
joy.start()
until(lambda: w.ctl.sim.pos[0] > 449.0, 6)
spin(0.6)
joy.stop()
spin(0.3)
check("joystick verso destra: si ferma a mezzo millimetro dalla corsa della scheda, senza rifiuti",
      not refused and 448.9 < w.ctl.sim.pos[0] <= 449.51, (refused, w.ctl.sim.pos))
check("reach_box della croce: profilo ∩ scheda", near(jogpad.reach_box(w.ctl, w.profile), (0, 0, 450, 400)))

# ====================================================================== C. la scheda rifiuta comunque
print("--- C. rifiuto della scheda")
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
w.goto_bed(200, 200)
until(lambda: abs(w.ctl.sim.pos[0] - 200) < 0.1, 10)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
spin(0.3)
w.ctl.board_settings[130] = "500.000"  # FreeLaserCut crede 500, la scheda accetta 450
del refused[:]
pad.jog_press(1, 0)
until(lambda: refused, 3)
spin(0.2)
pad.jog_release()
spin(0.2)
check("error:15 da un jog della croce: il motivo sotto le frecce, con le misure", refused and refused[0][0] == 15
      and pad.refusal.isVisibleTo(pad) and "600 × 400" in pad.refusal_lab.text() and "500 × 440" in pad.refusal_lab.text(),
      (refused, pad.refusal_lab.text()))
check("…con il pulsante «Usa le misure della macchina»", pad.b_fix.isVisibleTo(pad))
pad.b_fix.click()
spin(0.2)
check("il pulsante mette nel profilo la corsa letta dalla scheda e il messaggio sparisce",
      (w.profile.bed_x, w.profile.bed_y) == (500.0, 440.0) and not pad.refusal.isVisibleTo(pad) and
      (w.canvas.bed_x, w.canvas.bed_y) == (500.0, 440.0), (w.profile.bed_x, w.profile.bed_y))
w.ctl.board_settings[130] = "600.000"
w.set_active_profile(big_profile(negative_space=False))
del refused[:]
pad.jog_press(1, 0)
until(lambda: refused, 3)
spin(0.2)
pad.jog_release()
check("rifiuto con il profilo non più grande della scheda: messaggio generico, senza pulsante",
      refused and "uscirebbe dall'area" in pad.readout.text() and not pad.refusal.isVisibleTo(pad), pad.readout.text())
w.ctl.board_settings[130] = "450.000"
del refused[:]
pad._arrow_note("")
pad._jog_sent = time.monotonic() - 10  # l'ultimo jog della croce è di 10 s fa
w.ctl.error_raised.emit(15, "", "G1 X10 F100")
w.ctl.error_raised.emit(15, "", "$J=G91 X10 F100")
spin(0.1)
check("errori non dei jog o di jog vecchi: la croce non dice niente", not pad.refusal.isVisibleTo(pad))

# ---- avviso al collegamento
print("--- D. avviso al collegamento")
w.set_active_profile(big_profile())
w.banner.hide()
w._check_board_travel()
check("«Ignora» lo ricorda per questa macchina e queste misure", w.banner.isVisibleTo(w) and
      (w.banner_buttons.itemAt(1).widget().click(), not w.banner.isVisibleTo(w) and not w._check_board_travel())[1])
w.qs.setValue("travel_dismissed", "")
w._check_board_travel()
w.banner_buttons.itemAt(0).widget().click()
spin(0.1)
check("«Usa le misure della macchina» dall'avviso: piano 450 × 440 e avviso chiuso",
      (w.profile.bed_x, w.profile.bed_y) == (450.0, 440.0) and not w.banner.isVisibleTo(w), (w.profile.bed_x, w.profile.bed_y))
check("con il profilo uguale alla scheda nessun avviso", not w._check_board_travel())
w.ctl.disconnect_port()
spin(0.3)

# ====================================================================== E. coordinate negative (GRBL classico)
print("--- E. coordinate negative")
os.environ["FLC_SIM_NEGATIVE"] = "1"
w.set_active_profile(big_profile(tested_x=True))
w.banner.hide()
w.ctl.sim_travel = (450.0, 440.0)
w.ctl.connect_port(SIM_PORT)
w.ctl.sim_travel = None
os.environ.pop("FLC_SIM_NEGATIVE")
w.ctl.sim.speedup = 4
until(lambda: w.ctl.board_settings.get(130) is not None, 8)
w.ctl.home()
check("homing con coordinate negative", until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 15)
      and w.ctl.negative_space)
spin(0.4)
w.banner.hide()
box = jogpad.reach_box(w.ctl, w.profile)
check("parte raggiungibile del piano: 150..600 (le coordinate vanno da -corsa a 0: manca la parte vicina allo 0)", near(box, (150, 0, 600, 400)), box)
w.goto_bed(300, 200)
until(lambda: w.canvas.head_pos() is not None and abs(w.canvas.head_pos().x() - 300) < 0.2, 10)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
spin(0.3)
for dx, edge in ((-1, 150.5), (1, 599.5)):
    del refused[:]
    pad.jog_press(dx, 0)
    until(lambda: w.canvas.head_pos() is not None and abs(w.canvas.head_pos().x() - edge) < 0.3, 10)
    spin(0.3)
    pad.jog_release()
    spin(0.3)
    hx = w.canvas.head_pos().x()
    check(f"«Continuo» {'a sinistra' if dx < 0 else 'a destra'}: arriva a {edge:g} sul piano senza rifiuti",
          not refused and abs(hx - edge) < 0.3, (refused, hx))
    until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
w.ctl.disconnect_port()
spin(0.3)

# ====================================================================== F. il simulatore segue il profilo
print("--- F. simulatore con la corsa del profilo")
small = MachineProfile(name="Piccolo", model="Piccolo")
small.bed_x, small.bed_y = 300.0, 200.0
w.set_active_profile(small)
w.port_combo.setCurrentIndex(w.port_combo.findData(SIM_PORT))
w.toggle_connection(quiet=True)
check("collegando dal programma, il simulatore ha la corsa del profilo (300 × 200)",
      until(lambda: w.ctl.board_settings.get(130) is not None, 8) and w.ctl.soft_limits() == (300.0, 200.0), w.ctl.soft_limits())
check("…e quindi nessun avviso di misure diverse", not w.banner.isVisibleTo(w) or "corsa che la scheda accetta"
      not in w.banner_text.text())
check("…e la volta dopo non resta attaccata a un collegamento diretto", w.ctl.sim_travel is None)
w.ctl.disconnect_port()

w.editor.dirty = False
ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
