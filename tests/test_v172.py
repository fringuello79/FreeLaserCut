# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.17.2: dal messaggio di un utente.
- piano letto come 400 × 234500: un'area di lavoro non credibile ($130/$131) non diventa il piano; FreeLaserCut lo
  dice, rilegge una volta, non la usa per riconoscere il modello e non la rimanda alla scheda dai backup;
- oltre 10000 mm/min la testa va a scatti con le foto molto fitte: stima dei comandi che la porta riesce a mandare,
  avviso e, all'avvio, la scelta di compattare (punti vicini uniti in tratti più lunghi, stessi toni);
- override sopra il 100%: spiegazione dei limiti della scheda ($30, $110/$111);
- Mecpow X3S 7W e 12W nel catalogo (pagine ufficiali)."""
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PIL import Image
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import board_backup, machines
from freelasercut.core import gcode
from freelasercut.core.document import Document, ImageShape
from freelasercut.grbl import SIM_PORT, GrblController
from freelasercut.grbl_codes import bad_travel, travel_ok
from freelasercut.profile import MachineProfile

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def spin(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


# ================================================================ 1. area di lavoro credibile
check("valori credibili: 400.000 e 360", travel_ok("400.000") and travel_ok(360))
check("non credibili: 234500, 3500, 5, testo", not any(travel_ok(v) for v in ("234500", 3500, "5", "abc")))
check("$130=0 (corsa non impostata) non è un errore, $131=234500 sì",
      bad_travel({130: "0.000", 131: "234500"}) == [(131, "234500")])
base = MachineProfile()
base.bed_x, base.bed_y = 400.0, 400.0
p = MachineProfile.from_machine({130: "400.000", 131: "234500", 30: "1000"}, [], base=base)
check("profilo dalla scheda: $131=234500 non diventa il piano (resta 400)", p.bed_x == 400 and p.bed_y == 400, (p.bed_x, p.bed_y))
p2 = MachineProfile.from_machine({130: "360.000", 131: "360.000"}, [], base=MachineProfile())
check("valori buoni letti come prima (360 × 360)", (p2.bed_x, p2.bed_y) == (360, 360))
ident = machines.identify(("Grbl 1.1h ['$' for help]",), (), {130: "400.000", 131: "234500"})
check("riconoscimento: area non credibile ignorata, con avviso",
      ident.bed == (400.0, 0.0) and any("234500" in t for k, t in ident.notes if k == "warn"), (ident.bed, ident.notes))


class FakeSer:
    def __init__(self):
        self.sent = []

    def write(self, data):
        self.sent.append(bytes(data))
        return len(data)

    def close(self):
        pass


def ctl_fake():
    c = GrblController()
    c._ser = FakeSer()
    c.port = "COM3"
    c._backup_done = True
    return c


c = ctl_fake()
ev = {"ready": [], "suspect": [], "msg": []}
c.settings_ready.connect(lambda d: ev["ready"].append(d))
c.travel_suspect.connect(lambda b: ev["suspect"].append(b))
c.message.connect(lambda m: ev["msg"].append(m))
c.request_settings()
for line in ("$30=1000", "$130=400.000", "$131=234500", "ok"):
    c._dispatch(line)
check("prima lettura con $131=234500: niente impostazioni usate, messaggio", not ev["ready"] and not c.board_settings
      and any("234500" in m for m in ev["msg"]), ev)
spin(0.8)
check("…e rilegge $$ da sola", c._ser.sent.count(b"$$\n") == 2, c._ser.sent)
for line in ("$30=1000", "$130=400.000", "$131=234500", "ok"):
    c._dispatch(line)
check("seconda lettura uguale: avviso alla finestra, impostazioni passate (il profilo le filtra)",
      ev["suspect"] == [[(131, "234500")]] and len(ev["ready"]) == 1)
spin(0.6)
check("niente terza lettura automatica", c._ser.sent.count(b"$$\n") == 2)
c.request_settings()
for line in ("$30=1000", "$130=400.000", "$131=400.000", "ok"):
    c._dispatch(line)
check("valore corretto sulla scheda: letto, nessun avviso in più", len(ev["ready"]) == 2 and len(ev["suspect"]) == 1
      and not c._travel_retry and c.board_settings.get(131) == "400.000")
c2 = ctl_fake()
r2 = []
c2.settings_ready.connect(r2.append)
c2.request_settings()
for line in ("$130=400.000", "$131=400.000", "ok"):
    c2._dispatch(line)
check("scheda normale: una lettura sola, come prima", r2 and c2._ser.sent.count(b"$$\n") == 1)

saved = {30: "1000", 130: "400.000", 131: "234500"}
cur = {30: "800", 130: "400.000", 131: "400.000"}
check("ripristino del backup: $131=234500 non si rimanda mai, il resto sì",
      board_backup.restore_lines(cur, saved) == ["$30=1000"] and board_backup.not_restored(saved) == [(131, "234500")])

# ================================================================ 2. comandi al secondo e compattazione
check("stima: a 115200 baud, comandi da 0,2 mm → circa 12000 mm/min",
      11000 < gcode.stream_vmax(0.2, 115200, 10) < 13000, gcode.stream_vmax(0.2, 115200, 10))
check("stima: porta più veloce, velocità più alta", gcode.stream_vmax(0.2, 250000, 10) > 2 * gcode.stream_vmax(0.2, 115200, 10))
prof = MachineProfile()
prof.max_rate_x = prof.max_rate_y = 30000
rng = np.random.default_rng(1)
yy, xx = np.mgrid[0:400, 0:400]
photo = (128 + 100 * np.sin(xx / 25.0) * np.cos(yy / 31.0) + rng.normal(0, 20, xx.shape)).clip(0, 255).astype(np.uint8)


def photo_doc(dither, speed, dpi=254, start="top"):
    doc = Document()
    doc.images["a"] = Image.fromarray(photo)
    im = ImageShape("a", 50, 50, layer=0)
    im.apply(QTransform.fromTranslate(50, 50))
    doc.add(im)
    cs = doc.layer(0)
    cs.mode, cs.dither, cs.dpi, cs.speed, cs.power_max = "image", dither, dpi, speed, 80
    cs.image_start = start
    return doc


for dither in ("floyd", "grayscale", "bayer"):
    doc = photo_doc(dither, 12000)
    j = gcode.generate(doc, prof)
    jc = gcode.generate(doc, prof, gcode.JobOptions(compact_raster=True))
    ch, chc = j.choppy(115200), jc.choppy(115200)
    check(f"{dither} a 12000 mm/min, 254 dpi: avviso «a scatti»", ch and ch[0][2] < 12000, ch)
    check(f"{dither} compattato: meno righe, nessun avviso, stessi toni (bruciato ±2%)",
          len(jc.lines) < 0.7 * len(j.lines) and not chc and jc.compacted
          and abs(jc.layers[0].cut_mm - j.layers[0].cut_mm) < 0.02 * j.layers[0].cut_mm,
          (len(j.lines), len(jc.lines), chc, j.layers[0].cut_mm, jc.layers[0].cut_mm))
check("retino (punti già raggruppati): nessun avviso", not gcode.generate(photo_doc("halftone", 12000), prof).choppy(115200))
slow = photo_doc("floyd", 3000)
js = gcode.generate(slow, prof)
jsc = gcode.generate(slow, prof, gcode.JobOptions(compact_raster=True))
check("velocità bassa: nessun avviso e «compatta» non cambia nulla",
      not js.choppy(115200) and js.lines == jsc.lines and not jsc.compacted)
check("Wi-Fi o simulatore (baud None): nessuna stima", gcode.generate(photo_doc("floyd", 12000), prof).choppy(None) == [])
jl = gcode.generate(photo_doc("floyd", 12000, start="left"), prof, gcode.JobOptions(compact_raster=True))
check("righe verticali (partenza da sinistra): compattazione lungo la colonna", jl.compacted and not jl.choppy(115200))
b = np.zeros((6, 12))
b[:, ::2] = 70.0
cb = gcode._compact(b, 3, 1)
check("punti uniti: stessi punti accesi, stessa potenza, meno tratti",
      (cb > 0).sum() == (b > 0).sum() and set(np.unique(cb)) <= {0.0, 70.0}
      and sum((r[1:] != r[:-1]).sum() for r in cb) < sum((r[1:] != r[:-1]).sum() for r in b))
check("velocità oltre il massimo della macchina: la stima usa quella vera", gcode.generate(
    photo_doc("floyd", 50000), prof).stream[0]["speed"] == 30000)

ctl = GrblController()
check("porta: non collegata → velocità del profilo; simulatore → nessuna stima",
      ctl.stream_baud(250000) == 250000 and (ctl.connect_port(SIM_PORT) and ctl.stream_baud(115200) is None))
ctl.disconnect_port()

# ================================================================ 3. override sopra il 100%
from freelasercut.ui.panels_machine import OVERRIDE_TIP, override_note

L = gcode.LayerStats
pr = MachineProfile()
pr.s_max, pr.max_rate_x, pr.max_rate_y = 1000, 10000, 10000
check("potenza al 100%: sopra non sale, cita $30", "$30" in override_note("power", 150, [L(0, "a", "image", speed=8000, power=100)], pr))
check("potenza al 80% → al massimo 125%", "125%" in override_note("power", 150, [L(0, "a", "line", speed=800, power=80)], pr))
check("potenza al 50% con 150%: niente da dire", override_note("power", 150, [L(0, "a", "line", speed=800, power=50)], pr) == "")
check("velocità già al massimo ($110/$111): sopra non sale",
      "$110" in override_note("feed", 150, [L(0, "a", "image", speed=10000, power=60)], pr))
check("sotto il 100%: nessun avviso", override_note("feed", 80, [L(0, "a", "image", speed=10000, power=60)], pr) == "")
check("suggerimento dei cursori spiega i limiti", "$30" in OVERRIDE_TIP["power"]() and "$110" in OVERRIDE_TIP["feed"]())

# ================================================================ 4. Mecpow X3S
cat = {c[0]: c for c in machines.CATALOG}
check("Mecpow X3S 7W e 12W: 360 × 360, 10000 mm/min, potenze dichiarate",
      cat.get("Mecpow X3S 7W", ())[2:6] == (360, 360, "7 W", 10000)
      and cat.get("Mecpow X3S 12W", ())[2:6] == (360, 360, "12 W", 10000))
check("fonti: pagine ufficiali mecpow.com", all(machines.SOURCES.get(n, "").startswith("https://mecpow.com/products/")
                                                 for n in ("Mecpow X3S 7W", "Mecpow X3S 12W")))
check("spot dichiarati (0,05×0,07 e 0,06×0,08) e nota sull'estensione 360 × 730",
      machines.SPOTS["Mecpow X3S 7W"] == (0.05, 0.07) and machines.SPOTS["Mecpow X3S 12W"] == (0.06, 0.08)
      and "730" in machines.NOTES["Mecpow X3S 12W"])
pp = machines.preset_profile("Mecpow X3S 12W")
check("profilo pronto: piano 360 × 360", (pp.bed_x, pp.bed_y) == (360, 360), (pp.bed_x, pp.bed_y))

# ================================================================ 5. finestra
from freelasercut.ui.main_window import MainWindow

w = MainWindow()
w.show()
spin(0.3)
w._travel_suspect([(131, "234500")])
check("avviso sulla finestra con il valore e la strada per correggerlo",
      not w.banner.isHidden() and "234500" in w.banner_text.text(), w.banner_text.text())
w.banner.hide()
w.profile.max_rate_x = w.profile.max_rate_y = 30000
doc = w.editor.doc
doc.images["a"] = Image.fromarray(photo)
im = ImageShape("a", 50, 50, layer=0)
im.apply(QTransform.fromTranslate(50, 50))
doc.add(im)
cs = doc.layer(0)
cs.mode, cs.dither, cs.dpi, cs.speed, cs.power_max = "image", "floyd", 254, 12000, 80
job = w.build_job()
check("riepilogo del pannello Laser: avviso «a scatti»", "scatti" in w.laser.summary.text())
ran = []
w.preflight = lambda j: ([], [])
w._run = lambda lines, plate=None: ran.append(list(lines))
w.ctl.check_job = lambda lines: ran.append(list(lines)) or True
w.laser.verify_first.setChecked(False)
seen = []


def click(label):
    def ex(box):
        seen.append(box.text())
        for b in box.buttons():
            if b.text().startswith(label):
                b.click()
                return 0
        box.reject()
        return 0
    return ex


QMessageBox.exec = click("Compatta")
w.start_job()
check("avvio: spiegazione e scelta «Compatta»; si parte con il G-code compattato",
      seen and "Compatta" in seen[-1] and ran and len(ran[-1]) < 0.7 * len(job.lines) and w.job.compacted,
      (len(ran[-1]) if ran else None, len(job.lines)))
ran.clear()
w.build_job()
QMessageBox.exec = click("Avvia così")
w.start_job()
check("«Avvia così»: parte il lavoro di prima, con il consiglio su risoluzione e porta nel testo",
      ran and len(ran[-1]) == len(job.lines) and "risoluzione" in seen[-1])
ran.clear()
cs.speed = 3000
w.build_job()
QMessageBox.exec = click("Avvia")
w.start_job()
check("lavoro lento: nessuna scelta in più", ran and "Compatta" not in seen[-1])

w.job = gcode.generate(doc, w.profile)  # livello a 3000 mm/min, potenza 80%
w.statusBar().clearMessage()
w.ctl.set_override = lambda kind, pct: None
if w.banco is not None:
    w.laser.ov_power.setValue(100)
    w.banco.cockpit._ov("power", +10)
    w.banco.cockpit._ov("power", +10)
    w.banco.cockpit._ov("power", +10)
    check("Banco, pulsante «+» della potenza a 130%: dice fin dove la scheda può salire (125%)",
          "125%" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
else:
    w.laser._override("power", 130)
    check("cursore della potenza a 130%: dice fin dove la scheda può salire (125%)",
          "125%" in w.statusBar().currentMessage(), w.statusBar().currentMessage())

code = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(code)
