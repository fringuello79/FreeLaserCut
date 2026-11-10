# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.7: «Lucciola» (idea di Deborah): un pulsante sotto il Puntino che lascia il laser acceso al minimo.

Regole provate:
1 tetto di potenza dai watt ottici del profilo: mai oltre il 2%, più basso per i laser più potenti;
2 il tetto non si supera né dal campo né alla scheda (valore S mandato);
3 da acceso: «LASER ACCESO · m:ss», rosso che lampeggia, avviso sotto; avviso con conferma alla prima accensione;
4 si spegne da solo dopo 5 minuti; il tempo riparte se la testa si muove;
5 si spegne (senza mandare comandi in mezzo) quando parte un lavoro o una verifica, con il Puntino rilasciato, in
  allarme, scollegando, chiudendo il programma.
"""
import json
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import grbl  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT, glow_limits, optical_watts  # noqa: E402
from freelasercut.ui import panels_machine  # noqa: E402
from freelasercut.ui.dialogs import CheckResultDialog  # noqa: E402

CheckResultDialog.exec = lambda self: 0  # l'esito della verifica non deve fermare la prova

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def spin(sec):
    until(lambda: False, sec)


# ================================================================== tetto di potenza
check("watt ottici letti dal profilo", optical_watts("10 W") == 10 and optical_watts("44–48 W (4 diodi, 450–460 nm)") == 48
      and optical_watts("5,5W") == 5.5 and optical_watts("500 mW") == 0.5 and optical_watts("") is None
      and optical_watts("diodo 450 nm") is None and optical_watts("20-22 W") == 22)
check("tetto: 2% fino a 5 W, 1,5% fino a 10 W, 1% fino a 20 W, 0,5% oltre, 1% se la potenza non si sa",
      [glow_limits(t)[0] for t in ("3 W", "5 W", "5.5 W", "10 W", "12 W", "20 W", "22 W", "40 W", "44–48 W", "")]
      == [2.0, 2.0, 1.5, 1.5, 1.0, 1.0, 0.5, 0.5, 0.5, 1.0])
allw = [0.2, 1, 2.5, 5, 7, 10, 15, 20, 30, 40, 60, 100, 1000]
check("mai oltre il 2%, e il valore di partenza sta sempre sotto il tetto",
      all(glow_limits(f"{x} W")[0] <= 2.0 and 0.1 <= glow_limits(f"{x} W")[1] < glow_limits(f"{x} W")[0] for x in allw))
check("più il laser è potente, più il tetto scende (mai il contrario)",
      all(glow_limits(f"{a} W")[0] >= glow_limits(f"{b} W")[0] for a, b in zip(allw, allw[1:])))

# ================================================================== finestra
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
lp, ctl = w.laser, w.ctl
asked = []
real_confirm = panels_machine.confirm_glow
panels_machine.confirm_glow = lambda parent, pct: (asked.append(pct), answer[0])[1]
answer = [True]
w.profile.optical_power = "44–48 W (4 diodi, 450–460 nm)"
w.on_profile(w.profile)
check("pulsante «Lucciola (resta accesa)» sotto il Puntino, con il suo campo", lp.b_glow.text() == "Lucciola (resta accesa)"
      and lp.b_glow.isCheckable() and "Deborah" in lp.b_glow.toolTip())
check("laser da 48 W: tetto 0,5%, partenza 0,3%", lp.glow_pct.maximum() == 0.5 and abs(lp.glow_pct.value() - 0.3) < 1e-9,
      (lp.glow_pct.maximum(), lp.glow_pct.value()))
lp.glow_pct.setValue(2.0)
check("dal campo non si supera il tetto", lp.glow_pct.value() == 0.5)
lp.glow_pct.setValue(0.3)
lp.b_glow.click()
check("scollegato: non si accende", not lp.b_glow.isChecked() and not lp._glow_on and not asked)

ctl.connect_port(SIM_PORT)
ctl.sim.speedup = 50
until(lambda: ctl.board_settings and ctl.last_status.get("state") == "Idle")
sent = []
ctl.line_sent.connect(lambda l: sent.append(l))


def s_values():
    return [float(m.group(1)) for l in sent for m in [re.match(r"^M3 S([\d.]+)$", l)] if m]


answer[0] = False
lp.b_glow.click()
spin(0.3)
check("avviso rifiutato: resta spento e alla scheda non arriva niente", asked == [0.3] and not lp.b_glow.isChecked()
      and not ctl.fire_active and not s_values(), (asked, sent))
answer[0] = True
lp.b_glow.click()
until(lambda: ctl.fire_active and s_values(), 3)
s_max = w.profile.s_max
check("avviso accettato: laser acceso allo 0,3% (S = 0,3% del massimo)", ctl.fire_active and lp.b_glow.isChecked()
      and s_values() == [round(0.3 / 100 * s_max, 1)], (s_values(), s_max))
spin(0.4)
m = re.match(r"^LASER ACCESO · (\d):(\d\d)$", lp.b_glow.text())
check("da acceso il pulsante dice «LASER ACCESO» con il conto alla rovescia da 5 minuti",
      bool(m) and 295 <= int(m.group(1)) * 60 + int(m.group(2)) <= 300, lp.b_glow.text())
check("…è rosso, con l'alone, e sotto c'è l'avviso (occhiali, resta vicino)",
      "#" in lp.b_glow.styleSheet() and "ffffff" in lp.b_glow.styleSheet() and lp.b_glow.graphicsEffect() is not None
      and not lp.glow_note.isHidden() and "Occhiali" in lp.glow_note.text(), lp.b_glow.styleSheet()[:80])
looks = set()
t0 = time.time()
while time.time() - t0 < 1.3:
    app.processEvents()
    looks.add((lp.b_glow.styleSheet(), lp.b_glow.graphicsEffect().blurRadius()))
    time.sleep(0.02)
check("…e lampeggia (due rossi, alone che si allarga e si stringe)", len(looks) == 2, len(looks))
lp.glow_pct.setValue(0.5)
until(lambda: len(s_values()) == 2, 3)
lp.glow_pct.setValue(9.0)
spin(0.3)
check("potenza cambiata da acceso: vale subito, sempre sotto il tetto",
      s_values()[1:] == [round(0.5 / 100 * s_max, 1)] and max(s_values()) <= 0.5 / 100 * s_max + 1e-6, s_values())
check("il tetto vale anche per la scheda: una richiesta più alta viene tagliata",
      ctl.fire(True, 15.0, max_pct=lp.glow_cap, timeout_s=5, s_max=s_max) and until(lambda: len(s_values()) == 3, 3)
      and s_values()[-1] == round(0.5 / 100 * s_max, 1), s_values())
# ---- il tempo riparte se la testa si muove
lp._glow_deadline = time.time() + 20
ctl.jog(5.0, 0.0, 3000)
until(lambda: lp.glow_seconds_left() > 290, 5)
check("la testa si muove: il conto alla rovescia riparte da 5 minuti", lp.glow_seconds_left() > 290 and lp._glow_on,
      lp.glow_seconds_left())
until(lambda: ctl.last_status.get("state") == "Idle" and not ctl.busy, 10)
spin(0.6)
# ---- spegnimento da solo
sent.clear()
lp._glow_deadline = time.time() + 1.2
t0 = time.time()
check("tempo scaduto: si spegne da solo e manda M5", until(lambda: not lp._glow_on, 4) and time.time() - t0 >= 1.0
      and until(lambda: "M5 S0" in sent, 2) and not ctl.fire_active, (sent, time.time() - t0))
check("…il pulsante torna «Lucciola», grigio, senza avviso", lp.b_glow.text() == "Lucciola (resta accesa)"
      and not lp.b_glow.isChecked() and lp.b_glow.styleSheet() == "" and lp.b_glow.graphicsEffect() is None
      and lp.glow_note.isHidden())
# ---- spento a mano
n_asked = len(asked)
lp.b_glow.click()
until(lambda: ctl.fire_active, 3)
check("seconda accensione nella stessa sessione: l'avviso non si ripete", lp._glow_on and len(asked) == n_asked)
sent.clear()
lp.b_glow.click()
check("clic sul pulsante acceso: si spegne subito", until(lambda: "M5 S0" in sent, 2) and not lp._glow_on and not ctl.fire_active)
# ---- puntino
lp.b_glow.click()
until(lambda: ctl.fire_active, 3)
lp.fire_changed(True)
lp.fire_changed(False)
check("Puntino premuto e rilasciato mentre è accesa: si spegne anche la Lucciola", until(lambda: not lp._glow_on, 2)
      and not lp.b_glow.isChecked())
until(lambda: not ctl.busy, 3)
# ---- lavoro
rr = RectShape(20, 10)
rr.apply(QTransform.fromTranslate(30, 40))
w.editor.add([rr], "rettangolo")
ctl.homed = True
lp.b_glow.click()
until(lambda: ctl.fire_active, 3)
until(lambda: not ctl.busy, 3)
sent.clear()
job = w.build_job(show=False)
fin = []
ctl.job_finished.connect(lambda ok, msg: fin.append(ok))
w._run(job.lines)
check("parte un lavoro: la Lucciola si spegne prima (un solo M5, niente comandi in mezzo al lavoro)",
      until(lambda: not lp._glow_on, 3) and sent.count("M5 S0") == 1 and not lp.b_glow.isEnabled(), sent)
until(lambda: fin, 30)
spin(0.5)
check("…il lavoro finisce bene e durante il lavoro non si può accendere", fin == [True] and sent.count("M5 S0") == 1
      and not [l for l in sent if l.startswith("M3 S")], (fin, sent))
w.laser.update_running()
# ---- verifica
until(lambda: ctl.last_status.get("state") == "Idle" and not ctl.busy, 10)
lp.b_glow.click()
until(lambda: ctl.fire_active, 3)
until(lambda: not ctl.busy, 3)
done = []
ctl.check_finished.connect(lambda r: done.append(r))
sent.clear()
ctl.check_job(job.lines)
check("parte una verifica: prima M5, poi $C", until(lambda: "$C" in sent, 3) and sent.index("M5 S0") < sent.index("$C")
      and until(lambda: not lp._glow_on, 3), sent[:4])
until(lambda: done, 20)
until(lambda: ctl.last_status.get("state") == "Idle" and not ctl.busy, 10)
w.laser.update_running()
# ---- allarme
lp.b_glow.click()
until(lambda: ctl.fire_active, 3)
until(lambda: not ctl.busy, 3)
sent.clear()
ctl.last_status = dict(ctl.last_status, state="Alarm")
lp._glow_tick()
check("allarme: si spegne senza mandare comandi alla scheda bloccata", not lp._glow_on and sent == [], sent)
ctl.fire(False)
until(lambda: ctl.last_status.get("state") == "Idle" and not ctl.busy, 5)
# ---- profilo con un laser diverso
lp.glow_pct.setValue(0.5)
w.profile.optical_power = "10 W"
w.on_profile(w.profile)
check("laser da 10 W: tetto 1,5%; il valore scelto prima resta se è sotto il tetto",
      lp.glow_pct.maximum() == 1.5 and lp.glow_pct.value() == 0.5)
lp.glow_pct.setValue(1.5)
lp.b_glow.click()
until(lambda: ctl.fire_active, 3)
w.profile.optical_power = "40 W"
w.on_profile(w.profile)
check("profilo cambiato con un laser più potente mentre è accesa: si spegne e il valore torna sotto il tetto nuovo",
      not lp._glow_on and lp.glow_pct.maximum() == 0.5 and lp.glow_pct.value() <= 0.5, (lp._glow_on, lp.glow_pct.value()))
# ---- scollegando e chiudendo
until(lambda: not ctl.busy, 3)
lp.b_glow.click()
until(lambda: ctl.fire_active, 3)
ctl.disconnect_port()
check("cavo staccato: si spegne e il pulsante non resta rosso", until(lambda: not lp._glow_on, 2) and not ctl.fire_active
      and not lp.b_glow.isEnabled())
ctl.connect_port(SIM_PORT)
ctl.sim.speedup = 50
until(lambda: ctl.board_settings and ctl.last_status.get("state") == "Idle")
lp.b_glow.click()
until(lambda: ctl.fire_active, 3)
until(lambda: not ctl.busy, 3)
sent.clear()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
check("chiudendo il programma si spegne", not lp._glow_on and not ctl.fire_active)
panels_machine.confirm_glow = real_confirm

# ================================================================== traduzioni
src = open(os.path.join(ROOT, "freelasercut", "ui", "panels_machine.py"), encoding="utf-8").read()
keys = set()
for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', src):
    k = "".join(json.loads(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
    if any(x in k for x in ("Lucciola", "LASER ACCESO", "Il laser è acceso", "Stai per lasciare", "Deborah")):
        keys.add(k)
check("testi della Lucciola trovati nel codice", len(keys) >= 7, len(keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k for k in keys if not loc.get(k)]
    bad = [k for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    check(f"traduzioni {lang}: tutti i testi, con gli stessi segnaposto", not miss and not bad, (miss[:2], bad[:2]))
    check(f"traduzioni {lang}: Deborah è nominata nel suggerimento",
          any("Deborah" in loc.get(k, "") for k in keys if "Deborah" in k))

code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
