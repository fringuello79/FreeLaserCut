# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.21.1: angolo dello 0 e verso degli assi che non si contraddicono più (rapporto FLC-20261119-2231-2E95 di
Sengir, Creality Falcon A1 10W, e prima FLC-20261114-0845-C6B6), più la freccia «Continuo» che non resta muta
(Giuseppe su GitHub, Discussion #5).

Il caso del rapporto: nella configurazione guidata lo 0 scelto era «dietro a sinistra» (dove il Falcon A1 fa l'homing),
ma l'asse Y risultava «provato» e non invertito: vinceva in silenzio la prova delle frecce, quindi lo 0, il pallino
verde e il ritorno a fine lavoro finivano davanti a sinistra e la freccia «su» mandava la testa verso il davanti.
Uso: python tests/test_v211_falcon.py [banco]
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import machines  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


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


RAW = {'0': '10', '1': '250', '3': '4', '10': '3', '20': '0', '21': '1', '22': '1', '23': '3', '27': '5.000',
       '100': '80.000', '101': '80.000', '110': '36000.000', '111': '36000.000', '120': '1000.000', '121': '1000.000',
       '130': '381.000', '131': '305.000'}


def roberto():
    """Il profilo del rapporto 2E95, com'era salvato."""
    return MachineProfile(name="Creality Falcon A1 10W", model="Creality Falcon A1 10W", bed_x=381.0, bed_y=305.0,
                          accel_x=1000.0, accel_y=1000.0, negative_space=False, hard_limits=True, homing=True,
                          invert_x=False, invert_y=False, origin_corner="bl", tested_x=True, tested_y=True,
                          axes_tested=True, raw_settings=dict(RAW))


# ====================================================================== 1. il profilo
print("--- 1. profilo")
p = roberto()
check("profilo del rapporto: prima lo 0 risultava davanti a sinistra e «su» mandava la testa verso il davanti",
      p.corner_now() == "fl" and p.home_corner() == (0.0, 0.0) and p.to_machine_delta(0, 10) == (0.0, 10.0))
check("…ora il contrasto si vede: angolo scelto «dietro a sinistra»", p.corner_conflict() == "bl", p.corner_conflict())
q = MachineProfile(origin_corner="bl", invert_y=True, negative_space=False)
check("angolo e assi d'accordo: nessun contrasto", q.corner_conflict() is None)
q = MachineProfile(origin_corner="bl", invert_y=False, negative_space=None, tested_y=True)
check("coordinate non ancora note (niente homing): non si giudica", q.corner_conflict() is None)
check("nessun angolo scelto, o angolo rovinato nel file: non si giudica",
      MachineProfile(origin_corner="", negative_space=False).corner_conflict() is None
      and MachineProfile(origin_corner="xx", negative_space=False).corner_conflict() is None)
q = MachineProfile(origin_corner="bl", invert_x=True, invert_y=False, negative_space=True)
check("coordinate negative: angolo e assi d'accordo come prima (nessun falso allarme)", q.corner_now() == "bl"
      and q.corner_conflict() is None, q.corner_now())
p = roberto()
ch = p.follow_corner("bl")
check("«la testa va dietro a sinistra»: Y invertito e di nuovo «da provare», X resta provato, angolo dietro a sinistra",
      ch and (p.invert_x, p.invert_y, p.tested_x, p.tested_y, p.axes_tested, p.origin_corner)
      == (False, True, True, False, False, "bl") and p.corner_conflict() is None)
check("…ora 0, pallino e «casa» sono dietro a sinistra e «su» manda la testa verso il fondo",
      p.home_corner() == (0.0, 305.0) and p.home_point() == (10.0, 295.0) and p.to_machine_delta(0, 10) == (0.0, -10.0))
check("…il punto (0, 305) del piano è lo 0 della macchina, dove l'homing lascia la testa",
      p.to_machine(0.0, 305.0) == (0.0, 0.0) and p.to_bed(0.0, 0.0) == (0.0, 305.0))
p = roberto()
check("«la testa va davanti a sinistra»: assi come sono, cambia solo l'angolo scelto",
      p.follow_corner("fl") and (p.invert_x, p.invert_y, p.tested_x, p.tested_y, p.origin_corner)
      == (False, False, True, True, "fl") and p.corner_conflict() is None)
p = roberto()
p.follow_corner("bl")
check("rifarlo una seconda volta non cambia niente", p.follow_corner("bl") is False)
p = roberto()
p.follow_corner("bl")
p2 = MachineProfile.load(p.save())
check("salvato e riletto: resta coerente", p2.corner_now() == "bl" and p2.corner_conflict() is None
      and (p2.invert_y, p2.tested_y) == (True, False))

# ====================================================================== 2. catalogo
print("--- 2. catalogo")
f = machines.preset_profile("Creality Falcon A1 10W")
check("Falcon A1 dal catalogo: lo 0 dietro a sinistra, Y invertito, assi da provare",
      (f.origin_corner, f.invert_x, f.invert_y, f.tested_x, f.tested_y) == ("bl", False, True, False, False)
      and f.corner_now() == "bl")
f.negative_space = False
check("…dopo l'homing (coordinate positive) resta dietro a sinistra, senza contrasti",
      f.recompute_untested_axes() is False and f.corner_now() == "bl" and f.corner_conflict() is None)
check("…«casa» dietro a sinistra e «su» verso il fondo", f.home_corner() == (0.0, 305.0) and f.to_machine_delta(0, 10)
      == (0.0, -10.0))
o = machines.preset_profile("Creality Falcon A1 Pro 20W")
check("gli altri modelli restano come prima (Falcon A1 Pro: nessun angolo dal catalogo)",
      (o.origin_corner, o.invert_x, o.invert_y) == ("", False, False))
check("…e anche un modello qualsiasi", (machines.preset_profile("Two Trees TTS-10 Pro").origin_corner,
                                         machines.preset_profile("Two Trees TTS-10 Pro").invert_y) == ("", False))
info = ["[VER:1.1f.20220810:]", "[OPT:VcHL,127,65536]", "[software versions: CV40-MASTER-Release V1.0.6 20250306-1455]"]
ident = machines.identify((), info, dict(RAW))
bp = machines.build_profile(ident, dict(RAW), info)
check("riconosciuto dalla scheda (CV40, 381 × 305): profilo Falcon A1 con lo 0 dietro a sinistra",
      ident.model == "Creality Falcon A1 10W" and bp.origin_corner == "bl" and bp.invert_y and not bp.tested_y,
      (ident.model, bp.origin_corner, bp.invert_y))
bp.keep_user_orientation(roberto())
check("…«Riconosci e adatta» sopra il profilo vecchio di Sengir: la prova vecchia resta, e il contrasto si vede ancora "
      "(lo risolve l'avviso)", bp.tested_y and not bp.invert_y and bp.corner_conflict() == "bl")

# ====================================================================== 3. finestra principale: avviso e correzione
print("--- 3. avviso nella finestra principale")
from freelasercut.ui.dialogs_setup import SetupWizard  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1500, 950)
w.show()
spin(0.4)
rp = roberto()
rp.save()
w.set_active_profile(rp)
spin(0.1)
check("profilo di Sengir in uso: pallino verde davanti a sinistra (com'era)", w.canvas.machine_zero == (0.0, 0.0),
      w.canvas.machine_zero)
w.ctl.port = "COM3"  # come collegato al laser vero (l'avviso non c'è con il simulatore)
try:
    shown = w._corner_check()
    btns = [w.banner_buttons.itemAt(i).widget() for i in range(w.banner_buttons.count())]
    btns = [b for b in btns if b is not None and hasattr(b, "text")]
    texts = [b.text() for b in btns]
    check("avviso: dice il contrasto e chiede dove va la testa con l'homing", shown and w.banner.isVisibleTo(w)
          and "dietro a sinistra" in w.banner_text.text() and "davanti a sinistra" in w.banner_text.text()
          and "homing" in w.banner_text.text() and w._banner_kind == "warn", w.banner_text.text()[:120])
    check("…tre risposte: dietro a sinistra, davanti a sinistra, configurazione guidata",
          texts[:3] == ["Dietro a sinistra", "Davanti a sinistra", "Configurazione guidata"], texts)
    btns[0].click()
    spin(0.1)
    p = w.profile
    check("risposta «Dietro a sinistra»: Y invertito, da provare, angolo coerente", (p.invert_y, p.tested_y, p.origin_corner)
          == (True, False, "bl") and p.corner_conflict() is None and not w.banner.isVisibleTo(w))
    check("…il pallino verde va in alto a sinistra, i comandi alla scheda seguono", w.canvas.machine_zero == (0.0, 305.0)
          and w.ctl.axis_sign == (1.0, -1.0), (w.canvas.machine_zero, w.ctl.axis_sign))
    p2 = MachineProfile.load(p.path())
    check("…ed è salvato nel file del profilo", (p2.invert_y, p2.tested_y, p2.origin_corner) == (True, False, "bl"))
    check("…messaggio con il consiglio della prova delle frecce", "frecce" in w.statusBar().currentMessage())
    check("profilo ora coerente: l'avviso non torna", w._corner_check() is False)
    # una volta sola per lo stesso contrasto, anche se si chiude senza rispondere
    rp = roberto()
    rp.save()
    w.set_active_profile(rp)
    w.qs.setValue("corner_conflict_asked", "")
    check("di nuovo il profilo vecchio: l'avviso torna", w._corner_check() is True)
    w.banner.hide()
    btns = [w.banner_buttons.itemAt(i).widget() for i in range(w.banner_buttons.count())]
    btns = [b for b in btns if b is not None and hasattr(b, "text")]
    btns[1].click()  # «Davanti a sinistra»: tiene gli assi
    spin(0.1)
    p = w.profile
    check("risposta «Davanti a sinistra»: assi come prima, angolo scelto aggiornato, niente contrasto",
          (p.invert_y, p.tested_y, p.origin_corner) == (False, True, "fl") and p.corner_conflict() is None)
    rp = roberto()
    rp.save()
    w.set_active_profile(rp)
    check("stesso contrasto già chiesto: non lo richiede a ogni collegamento", w._corner_check() is False)
    w.qs.setValue("corner_conflict_asked", "")
    check("…chiuso senza rispondere: non torna lo stesso", w._corner_check() is True and (w.banner.hide() or True)
          and w._corner_check() is False)
    w.qs.setValue("corner_conflict_asked", "")
    w.ctl.port = SIM_PORT
    check("con il simulatore nessun avviso (non è la macchina vera)", w._corner_check() is False)
finally:
    w.ctl.port = None

# ====================================================================== 4. configurazione guidata
print("--- 4. configurazione guidata")
rp = roberto()
rp.save()
w.set_active_profile(rp)
d = SetupWizard(w)
check("si apre sull'angolo scelto (dietro a sinistra), non su quello degli assi", d.picker.corner == "bl", d.picker.corner)
check("…e dice il contrasto", "avevi scelto" in d.corner_lab.text() and "dietro a sinistra" in d.corner_lab.text()
      and "davanti a sinistra" in d.corner_lab.text(), d.corner_lab.text()[:100])
d.go(1)
d._next()
check("Avanti senza scegliere: resta lì e chiede di scegliere", d.stack.currentIndex() == 1
      and "Scegli un angolo" in d.corner_lab.text())
d.picker.choose("bl")
d._next()
check("scelto dietro a sinistra: si va avanti", d.stack.currentIndex() == 2)
d.go(4)
check("riepilogo: lo 0 è dietro a sinistra, senza avvisi", "dietro a sinistra" in d.summary.text()
      and "Attenzione" not in d.summary.text(), d.summary.text()[:150])
d.accept()
p = w.profile
check("dopo Fine: Y invertito e da provare, angolo coerente", (p.invert_y, p.tested_y, p.origin_corner) == (True, False, "bl")
      and p.corner_conflict() is None)
d = SetupWizard(w)
check("riaperta: angolo dietro a sinistra e nessun contrasto", d.picker.corner == "bl" and "Attenzione" not in d.corner_lab.text())
d.go(1)
d._next()
check("…e Avanti va avanti senza chiedere niente", d.stack.currentIndex() == 2)
d.reject()
rp = roberto()
rp.save()
w.set_active_profile(rp)
d = SetupWizard(w)
d.go(1)
d._dont_know()
d._next()
check("«Non lo so» vale come risposta: si va avanti", d.stack.currentIndex() == 2)
d.reject()
# frecce che contraddicono l'angolo scelto: il riepilogo lo dice e il profilo resta coerente
rp = roberto()
rp.save()
w.set_active_profile(rp)
d = SetupWizard(w)
d.go(1)
d.picker.choose("bl")
d.go(2)
d.fix(1)  # «correggi» su avanti/dietro: Y torna normale
d.go(4)
check("riepilogo: l'angolo scelto e le frecce non vanno d'accordo, lo dice", "Attenzione" in d.summary.text()
      and "frecce" in d.summary.text(), d.summary.text()[-200:])
d.accept()
p = w.profile
check("…con Fine vale la prova delle frecce, e angolo e assi restano coerenti",
      (p.invert_y, p.tested_y, p.origin_corner) == (False, True, "fl") and p.corner_conflict() is None,
      (p.invert_y, p.tested_y, p.origin_corner))

# ---- simulatore con il profilo del Falcon: la prova delle frecce non si fa
rp = roberto()
rp.follow_corner("bl")
rp.save()
w.set_active_profile(rp)
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 1
until(lambda: w.ctl.board_settings, 8)
spin(0.6)
w.set_active_profile(rp)  # il collegamento al simulatore non tocca il profilo del laser vero
# l'avviso parte da solo dopo il collegamento (qui il simulatore fa finta di essere il laser vero)
bad = roberto()
bad.save()
w.set_active_profile(bad)
w.qs.setValue("corner_conflict_asked", "")
w.banner.hide()
w.ctl.port = "COM3"
try:
    w._after_connect()
    check("dopo il collegamento l'avviso compare da solo (prima di «Fai l'homing»)", w.banner.isVisibleTo(w)
          and w._banner_kind == "warn" and "homing" in w.banner_text.text() and "dice due cose" in w.banner_text.text(),
          w.banner_text.text()[:80])
    w.banner.hide()
    w.qs.setValue("corner_conflict_asked", "")
    w.on_homed(True, False)
    check("…e anche dopo un homing", w.banner.isVisibleTo(w) and "dice due cose" in w.banner_text.text())
finally:
    w.ctl.port = SIM_PORT
w.banner.hide()
w.set_active_profile(rp)
d = SetupWizard(w)
d.go(1)
d.picker.choose("bl")
d.go(2)
sim_prof = MachineProfile(name="Simulatore", model="Simulatore")
check("il profilo «Simulatore» sul simulatore: la prova delle frecce resta (è la sua macchina)",
      (lambda: (w.set_active_profile(sim_prof), SetupWizard(w)._sim_other())[1])() is False)
w.set_active_profile(rp)
d = SetupWizard(w)
d.go(1)
d.picker.choose("bl")
d.go(2)
check("simulatore e profilo del Falcon: le frecce non ci sono e la finestra spiega perché",
      not d.arrows_box.isVisibleTo(d) and "simulatore" in d.arrows_intro.text() and not d._can_jog(),
      d.arrows_intro.text()[:80])
sent = []
w.ctl.line_sent.connect(sent.append)
d.jog("down")
check("…e anche premendo una freccia non parte niente e non vale come prova", not sent and not d.tested[1])
d.reject()

# ---- prova delle frecce dall'angolo dell'homing (simulatore con il suo profilo: coordinate positive, homing a 0,0)
w.set_active_profile(MachineProfile())
spin(0.1)
w.ctl.home()
check("homing sul simulatore", until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 15),
      w.ctl.last_status.get("state"))
spin(0.5)
mp = w.ctl.last_status.get("MPos")
check("…la testa è a 0,0 (l'angolo dell'homing)", mp is not None and abs(mp[0]) < 0.01 and abs(mp[1]) < 0.01, mp)
d = SetupWizard(w)
d.go(1)
d.picker.choose("fl")
d.go(2)
check("all'inizio della prova dice da quali frecce cominciare (quelle che allontanano dall'angolo)",
      "angolo dell'homing" in d.arrows_lab.text() and "destra →" in d.arrows_lab.text()
      and "↑ verso il fondo" in d.arrows_lab.text() and "sinistra" not in d.arrows_lab.text().split("cominciare")[-1]
      .replace("destra", ""), d.arrows_lab.text())
del sent[:]
d.jog("left")
spin(0.3)
check("freccia verso il finecorsa (sinistra, dall'angolo): non parte e non vale come prova",
      not any(s.startswith("$J") for s in sent) and not d.tested[0] and "finecorsa" in d.arrows_lab.text(), sent)
d.jog("down")
spin(0.3)
check("…anche verso il davanti (giù)", not any(s.startswith("$J") for s in sent) and not d.tested[1])
d.jog("right")
spin(0.2)
check("la freccia che allontana parte e vale come prova", any(s.startswith("$J") and "X10.000" in s for s in sent)
      and d.tested[0], sent)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
spin(0.4)
del sent[:]
d.jog("left")
spin(0.2)
check("lontano dall'angolo la sinistra torna a funzionare", any(s.startswith("$J") and "X-10.000" in s for s in sent), sent)
d.reject()
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)

# ====================================================================== 5. freccia «Continuo» (Giuseppe)
print("--- 5. freccia «Continuo»")
pad = w.move.pad
pad.set_mode("arrows")
pad.cont.setChecked(True)
w.goto_bed(0.2, 100)
until(lambda: w.canvas.head_pos() is not None and abs(w.canvas.head_pos().x() - 0.2) < 0.05, 10)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
spin(0.4)
del sent[:]
pad.jog_press(-1, 0)
spin(0.2)
pad.jog_release()
check("testa sul bordo sinistro, «Continuo», sinistra: non parte niente ma lo dice (prima: niente e basta)",
      not any(s.startswith("$J") for s in sent) and "bordo sinistro" in pad.readout.text(), (sent, pad.readout.text()))
del sent[:]
pad.jog_press(-1, 1)
spin(0.3)
pad.jog_release()
spin(0.1)
gl = [s for s in sent if s.startswith("$J=G53")]
check("diagonale su-sinistra dal bordo sinistro: va su lungo il bordo (prima: ferma)", gl and pad.readout.text() == "", gl)
if gl:
    import re as _re
    xs = float(_re.search(r"X(-?[\d.]+)", gl[0]).group(1))
    mx0 = w.profile.to_machine(0.2, 100)[0]
    check("…senza muoversi in X", abs(xs - mx0) < 0.1, (xs, mx0))
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
w.goto_bed(200, 200)
until(lambda: w.canvas.head_pos() is not None and abs(w.canvas.head_pos().x() - 200) < 0.1, 10)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
spin(0.3)
del sent[:]
x_before = w.ctl.sim.pos[0]
pad.jog_press(-1, 0)
spin(0.4)
pad.jog_release()
spin(0.3)
check("a metà piano la sinistra con «Continuo» va (e si ferma al rilascio)", any(s.startswith("$J=G53") for s in sent)
      and w.ctl.sim.pos[0] < x_before - 1, (sent, x_before, w.ctl.sim.pos[0]))
real_head = pad.get_head
pad.get_head = lambda: None
try:
    del sent[:]
    pad.jog_press(1, 0)
    spin(0.1)
    check("posizione della testa non ancora nota: lo dice", not sent and "non ancora nota" in pad.readout.text(),
          (sent, pad.readout.text()))
finally:
    pad.get_head = real_head
pad.cont.setChecked(False)
pad.jog_press(1, 0)
check("a passi: il messaggio sparisce", pad.readout.text() == "")
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)

w.ctl.disconnect_port()
spin(0.3)
w.editor.dirty = False
w.close()
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
