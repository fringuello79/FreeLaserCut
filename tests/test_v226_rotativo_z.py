# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.6 (giuseppegrassano77-coder, rapporti 8F98 e 1A5E): rotativo sul motore della Z.

La sua MKS DLC32 ha un interruttore a 4 poli: su «Rotary» il driver della Z muove il mandrino al posto del piano. Il
lavoro si prepara come con il rotativo sulla Y e solo alla fine la lettera Y diventa Z. Il programma non sa dov'è
l'interruttore: per questo prova del giro obbligatoria (prima un passo piccolo: se si muove il piano ci si ferma),
riga di conferma a ogni partenza, controllo dei passi della Z ($102) contro la taratura, conferma prima dell'homing,
autofocus e frecce della Z spenti.

Simulatore con le impostazioni del rotativo di Giuseppe: $102=255.05, $3=0, $132=300, $121=1000, $112=300.

Uso: python tests/test_v226_rotativo_z.py [classica|banco]
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
os.environ["FLC_NO_UPDATE"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
INFO, WARN, BOXES = [], [], []
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: INFO.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: WARN.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
GO = {"press": "go"}


def _exec(self):
    """La finestra «Avvio del lavoro»: si legge il testo e si preme il primo pulsante che avvia (o niente)."""
    BOXES.append(self.text())
    if GO["press"] == "go":
        for b in self.buttons():
            if self.buttonRole(b) == QMessageBox.AcceptRole:
                b.click()
                break
    return 0


QMessageBox.exec = _exec

from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import Document, RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui import dialogs_rotary  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402

UI = os.environ["FLC_UI"]
results = []
ASK = []  # risposte preparate per dialogs_rotary.ask (indice del pulsante); ogni domanda si segna
ASKED = []


def fake_ask(parent, title, text, buttons):
    ASKED.append(text)
    return ASK.pop(0) if ASK else 1


dialogs_rotary.ask = fake_ask


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + f"[{UI}] " + name + (f"  [{info}]" if info != "" and not cond else ""),
          flush=True)


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def until(fn, t=15.0):
    end = time.time() + t
    while time.time() < end:
        if fn():
            return True
        spin(0.02)
    return bool(fn())


MOVE = re.compile(r"^(G0|G1|G92)\b")
ROT_Y = {"kind": "chuck", "mm_per_rev": 80.0, "roller_d": 25.0, "object_d": 70.0}

# ================================================================== A. generatore (senza finestra)
print("--- A. generatore")
from freelasercut.profile import MachineProfile  # noqa: E402

prof = MachineProfile()
prof.z_motor = True
doc = Document()
r = RectShape(30, 20)
r.apply(QTransform.fromTranslate(40, 40))
doc.add(r)


def gen(rot, start="current", passes=1, z_step=0.0):
    cs = doc.layer(r.layer)
    cs.passes, cs.z_step = passes, z_step
    o = gcode.JobOptions(start_from=start, current_pos=(100.0, 100.0), rotary=rot)
    return gcode.generate(doc, prof, o)


jy = gen(dict(ROT_Y))
jy_axis = gen(dict(ROT_Y, axis="Y"))
jz = gen(dict(ROT_Y, axis="Z"))
check("rotativo sulla Y con o senza «axis» (impostazioni di prima): G-code identico", jy.lines == jy_axis.lines)
check("sulla Z: stesse righe del rotativo sulla Y, cambia solo la lettera", len(jz.lines) == len(jy.lines)
      and jz.lines == [gcode.y_to_z(l) for l in jy.lines])
moves_z = [l for l in jz.lines if MOVE.match(l)]
check("sulla Z: nessuna Y nei movimenti", moves_z and not any(re.search(r"\bY", l) for l in moves_z))
check("sulla Z: la Z si muove davvero (il giro)", sum(1 for l in moves_z if re.search(r"\bZ-?[\d.]", l)) >= 2)
check("sulla Z: «G92 X0 Z0» all'inizio (la posizione del mandrino di adesso è l'inizio del giro)",
      "G92 X0 Z0" in jz.lines and "G92 X0 Y0" not in jz.lines)
check("sulla Z: i commenti restano come sono", [l for l in jz.lines if l.startswith(";")]
      == [l for l in jy.lines if l.startswith(";")])
check("sulla Z: anteprima e tempo uguali al rotativo sulla Y", abs(jz.seconds - jy.seconds) < 1e-6
      and jz.rotary_axis == "Z" and jy.rotary_axis == "Y")
flat = gen(None)
check("rotativo spento: nessuna Z, come prima", flat.lines and not any(re.search(r"\bZ", l) for l in flat.lines
                                                                       if MOVE.match(l)) and flat.rotary_axis == "")
ja = gen(dict(ROT_Y, axis="Z"), start="absolute")
check("sulla Z con la partenza in coordinate assolute: niente lavoro, e lo dice", not ja.lines
      and any("Posizione attuale" in w for w in ja.warnings), ja.warnings)
jo = gen(dict(ROT_Y, axis="Z"), start="origin")
check("sulla Z con l'origine utente: niente lavoro", not jo.lines)
jzs = gen(dict(ROT_Y, axis="Z"), passes=3, z_step=0.5)
check("sulla Z con «Abbassa Z a ogni passata»: nessun G91 né passo della Z, e lo dice", jzs.lines
      and "G91" not in jzs.lines and any("non si abbassa" in w for w in jzs.warnings), jzs.warnings)
jys = gen(dict(ROT_Y), passes=3, z_step=0.5)
check("rotativo sulla Y con «Abbassa Z a ogni passata»: lo Z scende come prima", "G91" in jys.lines)
check("y_to_z: «G1 X10 Y-5.5 S300 F900» → «G1 X10 Z-5.5 S300 F900»",
      gcode.y_to_z("G1 X10 Y-5.5 S300 F900") == "G1 X10 Z-5.5 S300 F900")
doc.layer(r.layer).passes, doc.layer(r.layer).z_step = 1, 0.0

# ================================================================== B. finestra e simulatore
print("--- B. finestra, simulatore con le impostazioni del rotativo di Giuseppe")
win = mw.MainWindow()
win.show()
ctl = win.ctl
ctl.connect_port(SIM_PORT)
check("collegato al simulatore", until(lambda: ctl.board_settings.get(130) is not None))
sim = ctl.sim
sim.speedup = 30
GIUSEPPE = {102: "255.050", 3: "0", 132: "300.000", 121: "1000.000", 112: "300.000", 22: "1", 20: "0"}
for k, v in GIUSEPPE.items():
    sim.settings[k] = v
ctl.home()
until(lambda: ctl.homed and ctl.last_status.get("state") == "Idle", 20)
spin(2.0)
ctl.request_settings()
check("letti i valori del rotativo di Giuseppe", until(lambda: ctl.board_settings.get(102) == "255.050"),
      ctl.board_settings.get(102))
win.profile.z_motor = True
win.profile.af_probe = True
if hasattr(win, "move"):
    win.move._z_visible()
r2 = RectShape(30, 20)
r2.apply(QTransform.fromTranslate(60, 60))
win.editor.add([r2])
lp = win.laser
lp.start_from.setCurrentIndex(lp.start_from.findData("current"))
spin(0.1)
win.goto_bed(150, 150)
spin(0.2)
until(lambda: ctl.last_status.get("state") == "Idle", 20)
spin(0.5)

sent = []
_send = ctl.send_line


def spy(line, *a, **k):
    sent.append(line)
    return _send(line, *a, **k)


ctl.send_line = spy

# --- la finestra del rotativo
win.profile.z_motor = False
d = dialogs_rotary.RotaryDialog(win)
check("senza asse Z motorizzato la scelta «Z» non si può fare", not d.axis.model().item(1).isEnabled())
d.reject()
win.profile.z_motor = True
d = dialogs_rotary.RotaryDialog(win)
check("con l'asse Z motorizzato si può scegliere «Z»", d.axis.model().item(1).isEnabled())
d.on.setChecked(True)
d.kind.setCurrentIndex(d.kind.findData("chuck"))
d.axis.setCurrentIndex(d.axis.findData("Z"))
d.mm_rev.setValue(80.0)
d.obj.setValue(70.0)
check("la riga del giro dice «Asse Z per un giro»", "Z" in d.rev_label.text())
del ASKED[:]
ASK[:] = [1]  # «Annulla» alla domanda sull'interruttore
d.accept()
check("accendendolo sulla Z chiede dell'interruttore; con Annulla non si salva", ASKED and "Rotary" in ASKED[0]
      and win.qs.value("rotary_axis", "Y") != "Z" and not win.rotary_on_z())
del ASKED[:]
ASK[:] = [0]
d.accept()
win.update_rotary_state()
check("con «Sì, è sul rotativo» il rotativo è sulla Z", win.rotary_on_z() and ctl.rotary_z)
if hasattr(win, "sb_rotary"):
    check("barra di stato: «Rotativo sulla Z»", "Z" in win.sb_rotary.text(), win.sb_rotary.text())

# --- Z spenta
del sent[:]
ctl.jog_z(5.0, 300)
spin(0.2)
check("frecce della Z: con il rotativo sulla Z non parte niente", not any("Z" in l for l in sent), sent)
if hasattr(win, "move"):
    check("pannello: frecce Z e autofocus spenti", not win.move.b_zup.isEnabled() and not win.move.b_af.isEnabled())
af = {}
ctl.autofocus_done.connect(lambda ok, msg, z: af.setdefault("r", (ok, msg)))
ctl.autofocus(5.0, 20.0, 100.0, 20.0)
spin(0.2)
check("autofocus: rifiutato e lo dice", af.get("r") and not af["r"][0] and "rotativo" in af["r"][1].lower(), af)
check("autofocus: nessun G38 mandato", not any("G38" in l for l in sent))

# --- con un'altra partenza il lavoro non si prepara, e chi prova ad avviarlo legge il motivo vero
lp.start_from.setCurrentIndex(lp.start_from.findData("absolute"))
spin(0.1)
jr = win.build_job(show=False)
blk, _w = win.preflight(jr)
check("partenza in coordinate assolute: l'avvio dice di scegliere «Posizione attuale» (non «il lavoro è vuoto»)",
      jr is not None and not jr.lines and any("Posizione attuale" in b for b in blk)
      and not any("vuoto" in b for b in blk), blk)
lp.start_from.setCurrentIndex(lp.start_from.findData("current"))
spin(0.1)

# --- senza prova del giro non si parte
win.rotary_z_tested = False
job = win.build_job(show=False)
check("lavoro sulla Z preparato (partenza dalla testa)", job is not None and job.lines and job.rotary_axis == "Z")
blk, wrn = win.preflight(job)
check("senza «Prova: un giro» il lavoro non parte", any("prima fai «Prova: un giro»" in b for b in blk), blk)
del sent[:], WARN[:]
win.frame_job("box")
spin(0.3)
check("senza «Prova: un giro» nemmeno il contorno parte (muoverebbe la Z), e dice perché",
      not any(l.startswith("$J") for l in sent) and any("Prova: un giro" in t for t in WARN), (sent[:2], WARN))
win.qs.setValue("rotary_z_102", "255.050")  # anche con la taratura già salvata (da un'altra volta)…
blk, _ = win.preflight(job)
check("…la prova va fatta in questa connessione", any("prima fai «Prova: un giro»" in b for b in blk), blk)
win.qs.remove("rotary_z_102")

# --- prova: si è mosso il piano → ci si ferma dopo il passo piccolo
d = dialogs_rotary.RotaryDialog(win)
del sent[:]
ASK[:] = [1]
d.test_rev()
until(lambda: not ASK, 6.0)
spin(0.5)
zj = [l for l in sent if l.startswith("$J") and "Z" in l]
check("prova, «si è mosso il piano»: solo il passo piccolo e lento (2 mm), niente giro", len(zj) == 1
      and "Z2.000" in zj[0] and not getattr(win, "rotary_z_tested", False), zj)
m = re.search(r"F(\d+)", zj[0]) if zj else None
check("…e lento (al massimo 100 mm/min)", m and int(m.group(1)) <= 100, zj)
until(lambda: ctl.last_status.get("state") == "Idle", 15)
spin(0.5)

# --- prova riuscita
del sent[:]
ASK[:] = [0]
d.test_rev()
until(lambda: not ASK, 6.0)
spin(0.3)
zj = [l for l in sent if l.startswith("$J") and "Z" in l]
check("prova riuscita: passo piccolo, poi un giro (80 mm di Z)", len(zj) == 2 and "Z80.000" in zj[1], zj)
check("…con la velocità della Z della scheda ($112 = 300)", zj and "F300" in zj[-1], zj)
check("prova riuscita: segnata, con i passi della Z della taratura", getattr(win, "rotary_z_tested", False)
      and abs(float(win.qs.value("rotary_z_102")) - 255.05) < 1e-6, win.qs.value("rotary_z_102"))
d.reject()
until(lambda: ctl.last_status.get("state") == "Idle", 30)
spin(0.6)
blk, wrn = win.preflight(job)
check("dopo la prova il lavoro può partire", not blk, blk)
check("avviso: la Z della scheda va al massimo a 300 mm/min", any("$112" in w for w in wrn), wrn)
check("niente avviso dei limiti software ($20=0)", not any("$20=1" in w for w in wrn))
ctl.board_settings[20] = "1"
blk, wrn = win.preflight(job)
check("con $20=1: avviso dei limiti software", any("$20=1" in w for w in wrn), wrn)
ctl.board_settings[20] = "0"

# --- passi della Z cambiati dopo la taratura
ctl.board_settings[102] = "1600.000"
blk, _ = win.preflight(job)
check("$102 diverso dalla taratura (impostazioni normali ricaricate): il lavoro non parte", any("$102" in b for b in blk),
      blk)
ctl.board_settings[102] = "255.050"

# --- contorno: X e Z, la Y ferma, ritorno al punto di partenza
del sent[:]
m0 = list(ctl.last_status.get("MPos"))
win.frame_job("box")
spin(0.3)
until(lambda: ctl.last_status.get("state") == "Idle", 30)
spin(0.6)
fr = [l for l in sent if l.startswith("$J=G53")]
check("contorno: solo X e Z, nessuna Y", fr and all("Z" in l and "Y" not in l for l in fr), fr[:3])
zs = [float(re.search(r"Z(-?[\d.]+)", l).group(1)) for l in fr]
check("contorno: la Z gira davvero (giro diverso dal punto di partenza)", max(zs) - min(zs) > 1.0, zs)
check("contorno: alla fine torna al punto di partenza (X e Z)", fr and abs(zs[-1] - m0[2]) < 1e-3
      and abs(float(re.search(r"X(-?[\d.]+)", fr[-1]).group(1)) - m0[0]) < 1e-3, (fr[-1:], m0))
m1 = ctl.last_status.get("MPos")
check("contorno: la Y della macchina non si è mossa", abs(m1[1] - m0[1]) < 1e-3, (m0, m1))

# --- partenza: impostazioni rilette, riga dell'interruttore, lavoro intero
raw = []
_raw = ctl._write_raw


def raw_spy(data):
    raw.append(bytes(data))
    return _raw(data)


ctl._write_raw = raw_spy
del sent[:], BOXES[:]
done = {}
ctl.job_finished.connect(lambda ok, msg: done.setdefault("r", (ok, msg)))
lp.verify_first.setChecked(False)
win._rz_settings_t = 0.0
win.start_job()
check("alla partenza si rileggono le impostazioni della scheda ($$)", until(lambda: "$$" in sent, 3.0))
check("finestra di avvio: riga sull'interruttore su «Rotary»", until(lambda: BOXES, 6.0)
      and "Rotary" in BOXES[-1], BOXES[-1:])
check("il lavoro finisce, completo", until(lambda: "r" in done, 90.0) and done["r"][0], done.get("r"))
ctl._write_raw = _raw
body = [ln for d in raw for ln in d.decode("ascii", "replace").splitlines() if MOVE.match(ln)]
check("al simulatore: nessuna Y nei movimenti del lavoro", body and not any(re.search(r"\bY", l) for l in body),
      [l for l in body if re.search(r"\bY", l)][:4])
m2 = ctl.last_status.get("MPos")
check("finito il lavoro la Y della macchina è dove era", abs(m2[1] - m0[1]) < 1e-3, (m0, m2))
check("finito il lavoro il mandrino torna all'inizio del giro", abs(m2[2] - m0[2]) < 1e-2, (m0, m2))

# --- homing
del sent[:], ASKED[:]
ASK[:] = [1]
ctl.home()
spin(0.3)
check("homing con il rotativo sulla Z ($22=1): chiede prima; con Annulla non parte", ASKED and "$H" not in sent)
ASK[:] = [0]
ctl.home()
spin(0.3)
check("…con «Fai l'homing» parte", "$H" in sent)
until(lambda: ctl.last_status.get("state") == "Idle", 30)
saved22 = ctl.board_settings.pop(22, None)
del sent[:], ASKED[:]
ASK[:] = [1]
ctl.home()
spin(0.3)
check("homing con le impostazioni della scheda non ancora lette ($22 non si sa): chiede lo stesso", ASKED
      and "$H" not in sent)
ctl.board_settings[22] = "0"
del ASKED[:]
ctl.home()
spin(0.3)
check("homing con $22=0 (homing spento sulla scheda): nessuna domanda", not ASKED and "$H" in sent)
ctl.board_settings[22] = saved22 if saved22 is not None else "1"
until(lambda: ctl.last_status.get("state") == "Idle", 30)

# --- scollegamento: la prova va rifatta
win.on_connection(False, "")
check("dopo uno scollegamento la prova del giro va rifatta", not win.rotary_z_tested)
win.rotary_z_tested = True
win.profile.z_motor = True  # staccando il simulatore torna il profilo salvato: per la prova la Z resta motorizzata

# --- spegnendolo: «rimetti l'interruttore sul piano»
del INFO[:], ASKED[:]
d = dialogs_rotary.RotaryDialog(win)
d.on.setChecked(False)
d.accept()
win.update_rotary_state()
check("spegnendo il rotativo sulla Z: «rimetti l'interruttore sul piano»", any("sul piano" in t for t in INFO), INFO)
check("spento: Z di nuovo libera", not ctl.rotary_z and not win.rotary_on_z())
del sent[:], ASKED[:]
ctl.jog_z(1.0, 300)
ctl.home()
spin(0.3)
check("spento: frecce della Z e homing senza domande, come prima", any("Z1.000" in l for l in sent) and "$H" in sent
      and not ASKED, sent)
if hasattr(win, "move"):
    check("spento: pannello, frecce Z di nuovo accese", win.move.b_zup.isEnabled())
win.profile.z_motor = True
win.qs.setValue("rotary_on", True)
win.qs.setValue("rotary_axis", "Z")
win.update_rotary_state()
check("(rotativo di nuovo sulla Z)", ctl.rotary_z)
from freelasercut.profile import MachineProfile as _MP  # noqa: E402

other = _MP()
other.z_motor = False
win.on_profile(other)
check("cambiando laser con uno senza Z motorizzata: frecce della Z e autofocus tornano liberi da soli",
      not ctl.rotary_z and not win.rotary_on_z())
win.profile.z_motor = False
check("rotativo «Z» salvato ma profilo senza Z motorizzata: torna sulla Y", win.rotary_settings()["axis"] == "Y")
win.qs.setValue("rotary_on", False)

ok = sum(results)
print(f"{ok}/{len(results)} prove superate")
ctl.disconnect_port() if hasattr(ctl, "disconnect_port") else None
sys.exit(0 if ok == len(results) else 1)
