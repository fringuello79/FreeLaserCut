# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.5: comando dell'air assist a scelta (richiesta su GitHub: «un tasto di scelta per il comando M7 e M8»).

Il profilo aveva già `air_on` / `air_off` (e un profilo .lbdev con AirAssistM7 lo impostava), ma lavori, test e pulsante
Aria usavano sempre M8 / M9: con una scheda che vuole M7 l'aria non partiva.
Casi: profilo (M8, M7, nessuno, M106, valori non ammessi); G-code del lavoro, del test materiale, del test della
scansione e della ripresa; pulsante Aria sul simulatore; scelta nel pannello Macchina salvata nel profilo; traduzioni.
"""
import json
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
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.core import gcode, material_test, resume, scan_test  # noqa: E402
from freelasercut.core.document import Document, RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

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


def prof(on="M8", off="M9"):
    p = MachineProfile()
    p.air_on, p.air_off = on, off
    return p


def air_lines(lines):
    return [l for l in lines if l.split(" ")[0] in ("M7", "M8", "M9", "M106", "M107")]


# ================================================================== profilo
check("profilo nuovo: M8 accende, M9 spegne (come sempre)", MachineProfile().air_cmds() == ("M8", "M9"))
check("M7", prof("M7").air_cmds() == ("M7", "M9") and prof(" m7 ", "").air_cmds() == ("M7", "M9"))
check("nessun comando", prof("", "M9").air_cmds() == ("", "") and prof(None, None).air_cmds() == ("", ""))
check("M106 si spegne con M107", prof("M106", "M9x").air_cmds() == ("M106", "M107") and prof("M106", "M107").air_cmds() == ("M106", "M107"))
check("valori non ammessi (profilo scritto a mano) non arrivano alla scheda",
      prof("M3 S1000").air_cmds() == ("", "") and prof("M8", "$X").air_cmds() == ("M8", "M9"))

# ================================================================== G-code
doc = Document()
r = RectShape(20, 10)
r.apply(QTransform.fromTranslate(30, 40))
doc.add(r)
doc.layer(r.layer).air = True
std = gcode.generate(doc, prof())
m7 = gcode.generate(doc, prof("M7"))
none = gcode.generate(doc, prof(""))
check("lavoro con M8: come prima (M9 all'inizio, M8 sul livello, M9 alla fine)", air_lines(std.lines) == ["M9", "M8", "M9"],
      air_lines(std.lines))
check("lavoro con M7: M7 al posto di M8, mai M8", air_lines(m7.lines) == ["M9", "M7", "M9"], air_lines(m7.lines))
check("lavoro senza comando: nessun M7, M8 o M9", air_lines(none.lines) == [], air_lines(none.lines))
check("…e il resto del lavoro è identico", [l for l in m7.lines if l not in ("M7", "M9")] == [l for l in std.lines if l not in ("M8", "M9")]
      and [l for l in none.lines] == [l for l in std.lines if l not in ("M8", "M9")])
doc.layer(r.layer).air = False
off = gcode.generate(doc, prof("M7"))
check("livello con l'aria spenta: solo lo spegnimento iniziale", air_lines(off.lines) == ["M9"], air_lines(off.lines))
spec = material_test.TestSpec(x0=10, y0=10, cols=2, rows=2, cell=5, gap=2)
check("test materiale: M8 / M7 / niente secondo il profilo",
      air_lines(material_test.build(spec, prof()).lines) == ["M8", "M9"]
      and air_lines(material_test.build(spec, prof("M7")).lines) == ["M7", "M9"]
      and air_lines(material_test.build(spec, prof("")).lines) == [])
ss = scan_test.ScanTestSpec(speeds=[3000.0], off_max=0.1)
check("test della scansione: M8 / M7 / niente secondo il profilo",
      air_lines(scan_test.build(ss, prof()).lines) == ["M8", "M9"]
      and air_lines(scan_test.build(ss, prof("M7")).lines) == ["M7", "M9"]
      and air_lines(scan_test.build(ss, prof("")).lines) == [])

# ================================================================== ripresa
i7 = m7.lines.index("M7") + 3
i8 = std.lines.index("M8") + 3
check("ripresa di un lavoro con M7: riaccende con M7", "M7" in resume.resume_program(m7.lines, i7)[:8]
      and "M8" not in resume.resume_program(m7.lines, i7), resume.resume_program(m7.lines, i7)[:8])
check("ripresa di un lavoro con M8: come prima", "M8" in resume.resume_program(std.lines, i8)[:8])
check("ripresa di un lavoro senza comandi dell'aria: resta senza", air_lines(resume.resume_program(none.lines, i8 - 1)) == [],
      air_lines(resume.resume_program(none.lines, i8 - 1)))

# ================================================================== finestra e simulatore
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
combo = w.machine.air_cmd
check("pannello Macchina: scelta M8 / M7 / nessun comando, parte da M8",
      [combo.itemData(i) for i in range(combo.count())] == ["M8", "M7", ""] and combo.currentData() == "M8"
      and w.ctl.air_cmds == ("M8", "M9"))
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings and w.ctl.last_status.get("state") == "Idle")
sent, errs, msgs = [], [], []
w.ctl.line_sent.connect(lambda l: sent.append(l))
w.ctl.error_raised.connect(lambda *a: errs.append(a))
w.ctl.message.connect(lambda m: msgs.append(m))
w.laser.b_air.setChecked(True)
until(lambda: "M8" in sent, 3)
w.laser.b_air.setChecked(False)
until(lambda: "M9" in sent, 3)
check("pulsante Aria con M8: M8 e poi M9", sent == ["M8", "M9"], sent)
combo.setCurrentIndex(combo.findData("M7"))
w.machine.set_air(combo.currentData())
check("scelta M7: entra nel profilo, si salva e vale da subito", w.profile.air_cmds() == ("M7", "M9")
      and MachineProfile.load(w.profile.path()).air_on == "M7" and w.ctl.air_cmds == ("M7", "M9")
      and combo.currentData() == "M7")
sent.clear()
w.laser.b_air.setChecked(True)
until(lambda: "M7" in sent, 3)
w.laser.b_air.setChecked(False)
until(lambda: "M9" in sent, 3)
until(lambda: not w.ctl.busy, 3)
check("pulsante Aria con M7: M7 e poi M9, senza errori della scheda", sent == ["M7", "M9"] and not errs, (sent, errs))
rr = RectShape(20, 10)
rr.apply(QTransform.fromTranslate(30, 40))
w.editor.add([rr], "rettangolo")
w.editor.doc.layer(rr.layer).air = True
job = w.build_job(show=False)
check("lavoro dalla finestra: usa M7", air_lines(job.lines) == ["M9", "M7", "M9"], air_lines(job.lines))
p2 = MachineProfile.from_machine({30: "1000.000", 32: "1", 130: "400.000", 131: "400.000"}, [], base=w.profile)
check("«Leggi dalla macchina» non cambia la scelta", p2.air_cmds() == ("M7", "M9"))
w.machine.set_air("")
sent.clear()
msgs.clear()
w.laser.b_air.setChecked(True)
until(lambda: msgs, 2)
w.laser.b_air.setChecked(False)
until(lambda: False, 0.3)
check("nessun comando: il pulsante Aria non manda niente e lo spiega", sent == [] and any("a mano" in m for m in msgs)
      and w.profile.air_cmds() == ("", "") and combo.currentData() == "", (sent, msgs))
check("…e il lavoro non ha comandi dell'aria", air_lines(w.build_job(show=False).lines) == [])
w.machine.set_air("M8")
check("di nuovo M8: tutto come prima", air_lines(w.build_job(show=False).lines) == ["M9", "M8", "M9"]
      and MachineProfile.load(w.profile.path()).air_cmds() == ("M8", "M9"))
w.profile.air_on, w.profile.air_off = "M106", "M107"
w.machine.refresh_profile()
check("profilo importato con M106: compare nella scelta", combo.currentData() == "M106" and combo.count() == 4)
w.machine.set_air("M8")
w.ctl.disconnect_port()

# ================================================================== traduzioni
keys = ["Air assist", "M8 (il più comune)", "Nessun comando",
        "Il comando che accende l'aria nei lavori, nel test materiale e con il pulsante Aria. Se con M8 la tua pompa non "
        "parte, prova M7. «Nessun comando» se l'aria la accendi a mano o resta sempre accesa.",
        "Air assist: {0}, salvato nel profilo «{1}»",
        "Nel profilo della macchina l'aria è «nessun comando»: accendila a mano."]
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k for k in keys if not loc.get(k)]
    check(f"traduzioni {lang}: i testi nuovi ci sono", not miss, miss)

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
