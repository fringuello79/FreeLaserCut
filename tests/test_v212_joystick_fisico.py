# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: joystick fisico (Logitech G13 di Ale, pad, joystick USB). Una prova per ogni riga della valutazione di
sicurezza (`freeburn/coda-0.21.2.md`, voce 1) e per le decisioni di Ale del 21/11 (solo dopo l'homing, da riaccendere a
ogni avvio, pulsanti senza laser, al massimo la «Velocità jog» e mai oltre 6000 mm/min).

Controller finto (`gamepad.FakeBackend`) sul simulatore: il G13 vero si prova sul PC del laser.
Uso: python tests/test_v212_joystick_fisico.py [classica|banco]
"""
import ast
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

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import gamepad  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui import joystick_fisico as jf  # noqa: E402
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


G13 = gamepad.Device("Logitech G13 Joystick", "030000006d040000", 0, 2, 22)
PAD = gamepad.Device("Xbox Controller", "03000000xbox", 1, 6, 11)
fake = gamepad.FakeBackend([G13])
gamepad.set_backend(fake)

w = MainWindow()
w.show()
spin(0.2)
pj, box = w.move.pjoy, w.move.pjoy_box
state = {"allowed": True}
pj.allowed = lambda: state["allowed"]
jogs = []
_send = w.ctl.send_line


def spy_send(line, *a, **k):  # i pezzetti del joystick non vanno nella console (line_sent): si guarda cosa parte
    if str(line).startswith("$J="):
        jogs.append((time.time(), str(line)))
    return _send(line, *a, **k)


w.ctl.send_line = spy_send


def jog_since(t0):
    return [ln for ts, ln in jogs if ts >= t0]


def push(x=0.0, y=0.0, buttons=(), dev=G13):
    fake.set(dev, x, y, buttons)


def head():
    p = w.canvas.head_pos()
    return None if p is None else (round(p.x(), 2), round(p.y(), 2))


print("--- comandi ammessi e codice")
src = open(jf.__file__, encoding="utf-8").read()
tree = ast.parse(src)
calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
check("8/9 il modulo non manda niente alla scheda da solo: niente ctl.jog, send_line, fire, frame_path",
      not ({"jog", "send_line", "fire", "frame_path", "realtime"} & calls), calls & {"jog", "send_line", "fire"})
check("8 nessun comando dei pulsanti accende il laser", set(jf.COMMANDS) == {
    "stop", "home", "goto0", "step_up", "step_down", "slow", "z_up", "z_down", "frame"}
      and not ({"glow", "dot", "pointer", "fire", "start", "frame_laser"} & set(jf.COMMANDS)))
pj.qs.setValue("pjoy_map", '{"0": "glow", "1": "start", "2": "stop", "x": "home", "300": "home"}')
check("8 un elenco salvato con comandi del laser (file vecchio o rovinato): restano solo quelli ammessi",
      pj.mapping() == {2: "stop"}, pj.mapping())
check("14 all'avvio è spento e nessun controller scelto", not pj.enabled and pj.device is None and not box.on.isEnabled())

print("--- scelta del controller")
pj.refresh()
check("elenco dal lettore", [d.name for d in pj.devices] == ["Logitech G13 Joystick"])
pj.choose(G13)
check("13 scelto: si ricorda per nome e GUID", pj.qs.value("pjoy_device") == G13.key() and box.on.isEnabled())

print("--- 6 homing")
w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.board_settings.get(130) is not None, 8)
w.ctl.sim.speedup = 4
w.profile.homing = True
push(0, 0)
check("6 macchina con l'homing non fatto: non si accende e dice perché", not pj.enable() and "homing" in pj.reason, pj.reason)
w.ctl.home()
check("homing", until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 15))
spin(0.4)
w.goto_bed(200, 200)
until(lambda: head() is not None and abs(head()[0] - 200) < 0.2, 10)
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
spin(0.3)

print("--- 1 deriva e taratura")
push(0.16, 0)
check("1 levetta a riposo fuori dalla zona morta (16% > 15%): non si accende", not pj.enable() and "centro" in pj.reason,
      pj.reason)
push(0.10, -0.05)
check("…a 10% si accende e tara il centro lì", pj.enable() and pj.center == (0.10, -0.05), pj.center)
t0 = time.time()
for x in (0.05, 0.10, 0.14, 0.20):  # 0.20 - 0.10 di centro = 0.10 dal centro tarato: ancora nella zona morta
    push(x, -0.05)
    spin(0.25)
check("1 deriva lenta intorno al centro tarato: la testa non si muove", not jog_since(t0), jog_since(t0)[:2])

print("--- 2 si arma solo dal centro")
pj.disable()
push(0.10, -0.05)
pj.enable()
push(1.0, -0.05)
t0 = time.time()
spin(0.6)
check("2 levetta spinta subito dopo l'accensione: si arma solo dopo 0,3 s al centro (qui niente movimento)", not pj.armed or
      jog_since(t0), (pj.armed, len(jog_since(t0))))
pj.disable()
push(0.10, -0.05)
pj.enable()
spin(0.1)
push(1.0, -0.05)
t0 = time.time()
spin(0.5)
check("2 spinta dopo 0,1 s al centro: niente movimento, chiede il centro", not jog_since(t0) and not pj.armed
      and "centro" in pj.reason, (len(jog_since(t0)), pj.reason))
push(0.10, -0.05)
check("…dopo 0,3 s al centro è armata", until(lambda: pj.armed, 2))

print("--- 11 verso e velocità")
x0 = head()[0]
push(1.10, -0.05)  # tutta a destra
t0 = time.time()
until(lambda: head()[0] > x0 + 5, 4)
push(0.10, -0.05)
spin(0.6)
check("11 levetta a destra: la testa va a destra sul piano", head()[0] > x0 + 3, (x0, head()))
check("…e i pezzetti partono dal joystick fisico (la spia li vede)", len(jog_since(t0)) >= 3, len(jog_since(t0)))
y0 = head()[1]
push(0.10, -1.05)  # SDL: su = -1
until(lambda: head()[1] > y0 + 5, 4)
push(0.10, -0.05)
spin(0.6)
check("11 levetta su: la testa va su sul piano", head()[1] > y0 + 3, (y0, head()))
w.move.feed.setValue(12000)
fs = [float(m.group(1)) for ln in jog_since(t0) for m in [re.search(r"F(\d+(?:\.\d+)?)", ln)] if m]
check("7 velocità mai oltre la «Velocità jog» (3000 qui)", fs and max(fs) <= 3000.5, max(fs) if fs else None)
t1 = time.time()
push(1.10, -0.05)
spin(0.8)
push(0.10, -0.05)
spin(0.5)
fs = [float(m.group(1)) for ln in jog_since(t1) for m in [re.search(r"F(\d+(?:\.\d+)?)", ln)] if m]
check("7 «Velocità jog» a 12000: la levetta resta a 6000 al massimo", fs and max(fs) <= 6000.5, max(fs) if fs else None)
w.move.feed.setValue(3000)
check("7 «piano» dimezza", (setattr(pj, "slow", True), pj.feed())[1] == 1500.0 and (setattr(pj, "slow", False),
                                                                                      pj.feed())[1] == 3000.0)
pj.qs.setValue("pjoy_invert_y", "true")
check("11 «Inverti su e giù»", pj.vector([0.10, -1.05])[1] < 0)
pj.qs.setValue("pjoy_invert_y", "false")
check("curva morbida: a metà corsa meno di metà velocità", 0 < pj.vector([0.10 + 0.5, -0.05])[0] < 0.5 * (0.5 / 0.85) + 0.01)

print("--- 3 FreeLaserCut non in primo piano, finestra di dialogo")
state["allowed"] = False
push(1.10, -0.05)
t0 = time.time()
spin(0.6)
check("3 programma non in primo piano + levetta spinta: zero movimento", not jog_since(t0) and not pj.armed, pj.reason)
state["allowed"] = True
spin(0.5)
check("…tornato in primo piano con la levetta ancora spinta: niente, aspetta il centro", not jog_since(t0) and not pj.armed)
push(0.10, -0.05)
until(lambda: pj.armed, 2)
d = QDialog(w)
d.setModal(True)
d.open()
spin(0.1)
check("3 con una finestra di dialogo aperta la regola di serie dice «no»", pj._allowed_default() is False)
d.close()

print("--- 10 un solo padrone")
w.move.pad.pad.pressed = True
push(1.10, -0.05)
t0 = time.time()
spin(0.5)
check("10 joystick sullo schermo premuto: la levetta vera non muove", not any("F" in ln for ln in jog_since(t0))
      and not pj.joy.active and not pj.armed)
w.move.pad.pad.pressed = False
push(0.10, -0.05)
until(lambda: pj.armed, 2)
w.kb_jog(1, 0)
push(1.10, -0.05)
t0 = time.time()
spin(0.2)
check("10 subito dopo un jog dalla tastiera: la levetta aspetta", not pj.joy.active and not pj.armed)
push(0.10, -0.05)
until(lambda: pj.armed, 2)

print("--- 9 lavoro, allarme")
until(lambda: w.ctl.last_status.get("state") == "Idle", 5)
w.ctl.sim.state = "Alarm"
until(lambda: w.ctl.last_status.get("state") == "Alarm", 3)
push(1.10, -0.05)
t0 = time.time()
spin(0.5)
check("9 in allarme: zero movimento, e sotto la casella il motivo", not jog_since(t0) and not pj.joy.active
      and "pronta" in pj.reason, pj.reason)
w.ctl.sim.state = "Idle"
until(lambda: w.ctl.last_status.get("state") == "Idle", 3)
push(0.10, -0.05)
until(lambda: pj.armed, 2)
real = type(w.ctl).job_active
type(w.ctl).job_active = property(lambda self: True)
try:
    push(1.10, -0.05)
    t0 = time.time()
    spin(0.5)
    check("9 durante un lavoro: zero movimento, e il motivo", not jog_since(t0) and not pj.joy.active
          and "pronta" in pj.reason, pj.reason)
finally:
    type(w.ctl).job_active = real
push(0.10, -0.05)
until(lambda: pj.armed, 2)

print("--- 4 guardiano e scollegamento")
push(1.10, -0.05)
until(lambda: pj.joy.active, 2)
fake.frozen = True
check("4 lettura bloccata con la levetta spinta: entro mezzo secondo la testa si ferma", until(lambda: not pj.joy.active, 0.5)
      and not pj.armed, pj.reason)
fake.frozen = False
push(0.10, -0.05)
until(lambda: pj.armed, 2)
push(1.10, -0.05)
until(lambda: pj.joy.active, 2)
fake.devs = []
check("4 controller scollegato: fermo, spento, «Nessuno»", until(lambda: not pj.enabled, 1) and not pj.joy.active
      and pj.device is None and "scollegato" in pj.reason.lower(), pj.reason)
fake.devs = [G13]
push(0, 0)

print("--- 12 pulsanti")
pj.set_mapping({0: "home", 1: "goto0", 2: "stop", 3: "step_up", 4: "step_down", 5: "slow", 6: "frame"})
pj.refresh()
pj.choose(G13)
push(0, 0)
pj.enable()
until(lambda: pj.armed, 2)
called = []
pj.actions = dict(pj.actions, home=lambda: called.append("home"), goto0=lambda: called.append("goto0"),
                  frame=lambda: called.append("frame"))
push(0, 0, buttons=(0,))
spin(0.4)
push(0, 0)
spin(0.1)
check("12 Homing con una pressione breve: niente", "home" not in called)
push(0, 0, buttons=(0,))
spin(1.25)
push(0, 0)
spin(0.1)
check("12 Homing tenendo premuto 1 s: una volta sola", called.count("home") == 1, called)
push(0, 0, buttons=(1,))
spin(1.25)
push(0, 0)
spin(0.1)
check("12 «Vai a X0 Y0» tenendo premuto 1 s", called.count("goto0") == 1, called)
st0 = w.move.step()
push(0, 0, buttons=(3,))
spin(0.1)
push(0, 0)
spin(0.1)
check("passo più grande", w.move.step() > st0, (st0, w.move.step()))
push(0, 0, buttons=(4,))
spin(0.1)
push(0, 0)
spin(0.1)
check("passo più piccolo", w.move.step() == st0)
push(0, 0, buttons=(5,))
spin(0.1)
check("«piano» mentre è premuto", pj.slow and pj.feed() == w.move.feed.value() / 2)
push(0, 0)
spin(0.1)
check("…e lasciato torna normale", not pj.slow)
push(0, 0, buttons=(6,))
spin(0.1)
push(0, 0)
spin(0.1)
check("Contorno dal pulsante", called.count("frame") == 1)
stops = []
pj.actions["stop"] = lambda: stops.append(pj.joy.active)  # com'era la levetta quando parte lo Stop del programma
until(lambda: pj.armed, 2)
push(1.10, 0, buttons=())
until(lambda: pj.joy.active, 2)
push(1.10, 0, buttons=(2,))  # Stop premuto con la levetta ancora spinta
spin(0.15)
push(0, 0)
check("Stop con la levetta spinta: prima ferma la levetta, poi lo Stop del programma, poi la spegne",
      stops == [False] and not pj.enabled and not pj.joy.active, stops)
src_mw = open(os.path.join(ROOT, "freelasercut", "ui", "main_window.py"), encoding="utf-8").read()
check("il Contorno dal controller è sempre a laser spento", 'frame=lambda: self.frame_job("box", laser_off=True)' in src_mw
      and 'and not laser_off else 0.0' in src_mw)

print("--- 17 asse Z")
zs = []
pj.actions = dict(pj.actions, z_up=lambda: zs.append(1))
pj.set_mapping({7: "z_up"})
pj.enable()
until(lambda: pj.armed, 2)
for _ in range(3):
    push(0, 0, buttons=(7,))
    spin(0.25)
check("17 Z a passi: un passo per pressione, anche tenendo premuto", zs == [1], zs)
push(0, 0)
pj.disable()

print("--- 13 e 14 riavvio")
fake.devs = [PAD]
from freelasercut.ui.joystick_fisico import PhysicalJoystick  # noqa: E402

pj2 = PhysicalJoystick(w.ctl, pj.qs, lambda: w.profile, w.canvas.head_pos, lambda: 3000, {}, backend=fake)
pj2.refresh()
check("13 il controller ricordato non c'è, ce n'è un altro: resta «Nessuno»", pj2.device is None and pj2.devices == [PAD])
fake.devs = [PAD, G13]
pj3 = PhysicalJoystick(w.ctl, pj.qs, lambda: w.profile, w.canvas.head_pos, lambda: 3000, {}, backend=fake)
pj3.refresh()
check("14 riavvio con il controller ricordato collegato: è proposto ma spento", pj3.device == G13 and not pj3.enabled)

print("--- 15 libreria che manca")
gamepad.set_backend(None, "pygame-ce non disponibile (prova)")
pj4 = PhysicalJoystick(w.ctl, pj.qs, lambda: w.profile, w.canvas.head_pos, lambda: 3000, {})
pj4.refresh()
check("15 senza la libreria: nessun controller, il motivo, niente errori", pj4.devices == [] and not pj4.available()
      and "pygame-ce" in pj4.reason and not pj4.enable())
fake.fail = True
gamepad.set_backend(fake)
pj4.refresh()
check("15 lettore che dà errore: il motivo, il programma continua", pj4.devices == [] and "non letti" in pj4.reason, pj4.reason)
fake.fail = False

print("--- lettore vero (pygame-ce, se c'è)")
try:
    import importlib.util as _iu

    has_pg = _iu.find_spec("pygame") is not None
except (ImportError, ValueError):
    has_pg = False
if has_pg:
    try:
        real = gamepad.PygameBackend()
        devs = real.devices()
        check("pygame-ce si carica senza finestre né suoni e dà l'elenco dei controller (anche vuoto)",
              isinstance(devs, list) and os.environ.get("SDL_VIDEODRIVER") == "dummy", (len(devs), os.environ.get("SDL_VIDEODRIVER")))
    except gamepad.GamepadError as exc:
        check("pygame-ce si carica senza finestre né suoni", False, exc)
else:
    print("(pygame-ce non installato qui: la prova con la libreria vera si fa sulle macchine di GitHub)")

print("--- installatori e licenze")
sys.path.insert(0, os.path.join(ROOT, "build"))
import prepara_installer as _pi  # noqa: E402

check("pygame-ce negli installatori (Windows, e per Linux e Mac che prendono lo stesso elenco)",
      "pygame-ce==2.5.8" in _pi.PACKAGES, [p for p in _pi.PACKAGES if "pygame" in p])
check("guida, esempi e prove di pygame-ce tolti in tutti e tre gli installatori", all(
    "TRIM_PYGAME" in open(os.path.join(ROOT, "build", f), encoding="utf-8").read().split("import", 1)[1]
    and 'os.path.join(site, "pygame", d)' in open(os.path.join(ROOT, "build", f), encoding="utf-8").read()
    for f in ("prepara_installer.py", "prepara_appimage.py", "prepara_mac.py")) and "examples" in _pi.TRIM_PYGAME)
req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
check("nel requisiti dal sorgente, ma non per Python ancora senza ruote", 'pygame-ce>=2.5; python_version < "3.15"' in req)
lic = open(os.path.join(ROOT, "LICENZE-TERZE-PARTI.md"), encoding="utf-8").read()
lic_dir = os.path.join(ROOT, "licenze-terze-parti")
check("licenza LGPL 2.1 e componenti di pygame-ce elencati", "pygame-ce" in lic
      and os.path.getsize(os.path.join(lic_dir, "pygame-ce-LGPL-2.1.txt")) > 20000
      and "SDL2" in open(os.path.join(lic_dir, "pygame-ce-terze-parti.txt"), encoding="utf-8").read())

print("--- interfaccia")
w.move.pjoy.choose(None)
box.sync()
check("sotto «Togli origine» nella scheda Movimento: tendina, «Attivo», impostazioni", box.combo.itemText(0) == "Nessuno"
      and not box.on.isEnabled())
dlg = jf.PhysicalJoystickDialog(pj, w)
check("finestra delle impostazioni: zona morta, verso, comandi dei pulsanti senza comandi del laser",
      set(dlg.boxes) == set(jf.COMMANDS) and dlg.dead.value() == 15.0)
dlg.boxes["stop"].setCurrentIndex(dlg.boxes["stop"].findData(4))
dlg.boxes["home"].setCurrentIndex(dlg.boxes["home"].findData(4))  # stesso pulsante: vale il primo
dlg.apply()
check("…«Applica» salva, un pulsante per un comando solo (lo Z resta dov'era)", pj.mapping() == {4: "stop", 7: "z_up"},
      pj.mapping())
w.ctl.disconnect_port()
w.editor.dirty = False

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
