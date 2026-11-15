# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.2: pausa fra un livello e l'altro (girare il pezzo, pulire, cambiare materiale, mettere a fuoco).

Matrice dei casi:
1 dati: il livello tiene pausa, messaggio e parcheggio; file vecchi senza i campi; valori rovinati; messaggio con ";"
  o parentesi (romperebbero il G-code), troppo lungo, su più righe;
2 G-code: senza pause identico a prima (togliendo il blocco della pausa si ritrova lo stesso testo); con la pausa sul
  secondo livello: M5, aria spenta, commento col messaggio, M0, laser di nuovo pronto, aria riaccesa dal livello dopo;
  pausa sul primo livello ignorata (con avviso); parcheggio solo con le coordinate della macchina; due pause; avviso
  con il numero di pause; la stima del tempo non cambia;
3 invio diretto (simulatore): la macchina si ferma alla fine del livello prima, laser spento, M0 non arriva alla
  scheda, la finestra dice il messaggio; Riprendi → il lavoro finisce giusto e il secondo livello è inciso dopo;
  Annulla durante la pausa → lavoro fermo, laser spento; due pause di fila; un G-code di terzi con M0;
4 finestra delle impostazioni del livello (Classica e Banco): casella, messaggio, parcheggio; finestra della pausa.
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
BANCO = os.environ["FLC_UI"] == "banco"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
from freelasercut.core import gcode  # noqa: E402
from freelasercut.core.document import CutSettings, Document, RectShape, clean_pause_msg  # noqa: E402
from freelasercut.grbl import SIM_PORT, GrblController, _is_pause, _pause_messages  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def spin(t):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.01)


def until(fn, t=60.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.02)
    return fn()


def rect(x, y, w, h, layer):
    s = RectShape(w, h, layer=layer)
    b = s.bounds()
    s.apply(QTransform.fromTranslate(x - b.left(), y - b.top()))
    return s


def make_doc(pause=False, msg="", park=False, first=False, third=False):
    d = Document()
    for i in (1, 2, 3):
        cs = d.layer(i)
        cs.mode, cs.speed, cs.power_max, cs.output = "line", 3000.0, 20.0, True
        cs.air = i != 3
    d.layer(2).pause_before = pause
    d.layer(2).pause_msg = msg
    d.layer(2).pause_park = park
    d.layer(1).pause_before = first
    d.layer(3).pause_before = third
    d.add(rect(20, 20, 30, 20, 1))
    d.add(rect(80, 20, 30, 20, 2))
    d.add(rect(140, 20, 30, 20, 3))
    return d


prof = MachineProfile()

if not BANCO:
    # ================================================================== 1. dati
    cs = CutSettings(index=2, pause_before=True, pause_msg="Gira il pezzo", pause_park=True)
    back = CutSettings.from_dict(cs.to_dict())
    check("livello: pausa, messaggio e parcheggio salvati e riletti", back.pause_before and back.pause_park
          and back.pause_msg == "Gira il pezzo")
    old = cs.to_dict()
    for k in ("pause_before", "pause_msg", "pause_park"):
        old.pop(k)
    o = CutSettings.from_dict(old)
    check("livello da un file vecchio (senza i campi): nessuna pausa", not o.pause_before and o.pause_msg == ""
          and not o.pause_park)
    bad = CutSettings.from_dict(dict(cs.to_dict(), pause_before="sì", pause_park=1, pause_msg=42))
    check("valori rovinati nel file: nessuna pausa, nessun messaggio (mai un errore)", bad.pause_before is False
          and bad.pause_park is False and bad.pause_msg == "")
    check("messaggio con «;» e parentesi (commenti del G-code): resi innocui",
          clean_pause_msg("Gira (piano); poi ok") == "Gira [piano], poi ok")
    check("messaggio su più righe e lunghissimo: una riga, al massimo 80 caratteri",
          "\n" not in clean_pause_msg("a\nb\r\nc " + "x" * 200) and len(clean_pause_msg("x" * 200)) == 80)

    # ================================================================== 2. G-code
    opts = gcode.JobOptions()
    plain = gcode.generate(make_doc(), prof, opts)
    paused = gcode.generate(make_doc(True, "Gira il pezzo"), prof, opts)
    check("senza pause: nessun M0 e nessun commento di pausa", not any(_is_pause(l) for l in plain.lines)
          and not any(l.startswith(gcode.PAUSE_TAG) for l in plain.lines) and not plain.pauses)
    i = next(k for k, l in enumerate(paused.lines) if _is_pause(l))
    block = paused.lines[i - 3:i + 2]
    check("pausa sul secondo livello: M5 S0, aria spenta, messaggio, M0, laser pronto (M4 S0)",
          block[0] == "M5 S0" and block[1] == "M9" and block[2] == "; PAUSA FLC: Gira il pezzo" and block[3] == "M0"
          and block[4] == "M4 S0", block)
    nxt = paused.lines[i + 2:i + 4]
    check("…e il livello dopo riaccende l'aria (M8) prima di partire", nxt[0] == "M8" and "livello C02" in nxt[1], nxt)
    lay1_end = max(k for k, l in enumerate(paused.lines[:i]) if l.startswith("G1"))
    check("…la pausa arriva dopo l'ultimo movimento a laser acceso del primo livello",
          all(not l.startswith("G1") for l in paused.lines[lay1_end + 1:i]))
    stripped = [l for l in paused.lines[:i - 3] + paused.lines[i + 2:]]
    # senza il blocco della pausa: l'aria del livello 2 resta accesa dal livello 1 (nessun M8 in più)
    stripped = [l for k, l in enumerate(stripped) if not (l == "M8" and k == i - 3)]
    diffs = [(a, b) for a, b in zip(stripped, plain.lines) if a != b]
    check("togliendo il blocco della pausa si ritrova lo stesso G-code; unica differenza: il primo G1 dopo la pausa "
          "ridice la potenza (dopo «M4 S0» la scheda è a S0: senza, il livello non brucerebbe)",
          len(stripped) == len(plain.lines) and len(diffs) == 1 and diffs[0][0] == diffs[0][1] + " S200", diffs[:3])
    check("la stima del tempo non conta la pausa", abs(paused.seconds - plain.seconds) < 0.5,
          (paused.seconds, plain.seconds))
    check("avviso: una pausa, M0 nei file salvati, da provare a vuoto", paused.pauses and
          any("pause fra i livelli" in wn and "M0" in wn for wn in paused.warnings), paused.warnings)
    p0 = gcode.generate(make_doc(first=True), prof, opts)
    check("pausa sul primo livello: ignorata (il lavoro non è ancora partito), con avviso",
          not any(_is_pause(l) for l in p0.lines) and any("primo livello" in wn for wn in p0.warnings))
    pk = gcode.generate(make_doc(True, "", park=True), prof, opts)
    i = next(k for k, l in enumerate(pk.lines) if _is_pause(l))
    home = prof.home_point(10.0)
    check("parcheggio: prima di M0 la testa va vicino all'angolo dell'homing, a laser spento",
          pk.lines[i - 2].startswith("G0") and f"X{home[0]:g}" in pk.lines[i - 2].replace(".000", "")
          or pk.lines[i - 2].startswith("G0"), pk.lines[i - 3:i + 1])
    check("messaggio vuoto: «Pausa prima del livello C02»", any("Pausa prima del livello C02" in l for l in pk.lines))
    opts_c = gcode.JobOptions()
    opts_c.start_from = "current"
    pc = gcode.generate(make_doc(True, "", park=True), prof, opts_c)
    i = next(k for k, l in enumerate(pc.lines) if _is_pause(l))
    check("parcheggio con «posizione attuale»: la testa resta dov'è (non si sa dov'è l'angolo), con avviso",
          not pc.lines[i - 2].startswith("G0") and any("resta dov'è" in wn for wn in pc.warnings))
    two = gcode.generate(make_doc(True, "uno", third=True), prof, opts)
    check("due pause (livelli 2 e 3): due M0, ognuna col suo messaggio",
          sum(_is_pause(l) for l in two.lines) == 2 and len(two.pauses) == 2
          and two.pauses[1]["msg"] == "Pausa prima del livello C03")
    msgs = _pause_messages(two.lines)
    check("il messaggio di ogni M0 si ritrova anche dopo la pulizia delle righe (invio diretto)",
          sorted(msgs.values()) == ["Pausa prima del livello C03", "uno"], msgs)
    check("…un M0 senza il suo commento (di un altro programma) non prende il messaggio della pausa prima",
          _pause_messages(["; PAUSA FLC: uno", "M0", "G0 X1", "M0"]) == {0: "uno"},
          _pause_messages(["; PAUSA FLC: uno", "M0", "G0 X1", "M0"]))
    check("riconoscimento di M0: M0, M00, M1, «m0» sì; M03, M5, G0 X0 M0 no",
          _is_pause("M0") and _is_pause("M00") and _is_pause("M1") and _is_pause(" m0 ")
          and not _is_pause("M03") and not _is_pause("M5") and not _is_pause("G0 X0 M0"))

    # ================================================================== 3. invio diretto
    c = GrblController()
    c.connect_port(SIM_PORT)
    spin(2.0)
    c.home()
    until(lambda: c.homed, 20)
    spin(0.5)
    c.sim.speedup = 40
    sent = []
    c.line_sent.connect(sent.append)
    raw = []
    orig_write = c._write_raw

    def spy(b):
        raw.append(b)
        return orig_write(b)

    c._write_raw = spy
    paused_msgs = []
    c.user_pause.connect(paused_msgs.append)
    at_pause = []  # com'è la macchina nell'istante in cui il lavoro dice «pausa» (nel filo della lettura)
    from PySide6.QtCore import Qt  # noqa: E402

    c.user_pause.connect(lambda _m: at_pause.append((c.last_status.get("state"), len(c._inflight), c.sim.state,
                                                     c.sim.power)), Qt.DirectConnection)
    done = {}
    c.job_finished.connect(lambda ok, msg: done.update(ok=ok, msg=msg))
    job = gcode.generate(make_doc(True, "Gira il pezzo"), prof, opts)
    marks0 = len(c.sim.burn_marks)
    c.stream_job(job.lines)
    until(lambda: paused_msgs, 60)
    spin(0.6)
    check("invio diretto: il lavoro si ferma alla pausa con il messaggio", paused_msgs == ["Gira il pezzo"]
          and c.user_paused and c.job_active, (paused_msgs, c.user_paused))
    check("…macchina ferma e laser spento", c.last_status.get("state") == "Idle" and c.sim.power == 0)
    check("…già ferma nell'istante della pausa (nessuna riga in volo, simulatore fermo): la finestra non compare "
          "mentre la testa finisce il livello", at_pause and at_pause[0] == ("Idle", 0, "Idle", 0), at_pause)
    sent_txt = b"".join(raw).decode(errors="ignore")
    check("…M0 non è arrivato alla scheda (la pausa la gestisce FreeLaserCut, uguale su tutte le schede)",
          "\nM0\n" not in "\n" + sent_txt and "M0\n" not in sent_txt.split("M5 S0\n")[-1][:3])
    marks_l1 = len(c.sim.burn_marks)
    xs = [x for x, _y in c.sim.burn_marks[marks0:]]
    check("…inciso solo il primo livello (niente del secondo, che sta a X 80–110)", xs and max(xs) < 60, max(xs))
    spin(2.0)
    check("…e resta ferma finché nessuno riprende (niente righe nuove)", len(c.sim.burn_marks) == marks_l1
          and c.user_paused)
    check("Riprendi: riparte", c.resume_user_pause())
    until(lambda: "ok" in done, 90)
    xs = [x for x, _y in c.sim.burn_marks[marks_l1:]]
    check("…il lavoro finisce giusto e dopo la pausa si incidono il secondo e il terzo livello",
          done.get("ok") is True and xs and min(xs) > 70 and max(xs) > 160, (done, xs and (min(xs), max(xs))))
    check("…Riprendi a lavoro finito non fa niente", c.resume_user_pause() is False)

    # annulla durante la pausa
    done.clear()
    paused_msgs.clear()
    c.stream_job(job.lines)
    until(lambda: paused_msgs, 60)
    spin(0.3)
    c.stop_job()
    until(lambda: "ok" in done, 20)
    spin(1.0)
    check("Annulla durante la pausa: lavoro fermato, laser spento, niente più pausa",
          done.get("ok") is False and c.sim.power == 0 and not c.user_paused and not c.job_active)
    if c.last_status.get("state") == "Alarm":
        c.unlock()
        spin(0.5)

    # «Riprendi» della barra (feed hold / ripresa) durante la pausa: riprende la pausa
    done.clear()
    paused_msgs.clear()
    resumed = []
    c.user_resumed.connect(lambda: resumed.append(1))
    c.stream_job(job.lines)
    until(lambda: paused_msgs, 60)
    c.resume()
    until(lambda: "ok" in done, 90)
    check("«Riprendi» della barra durante la pausa: il lavoro riparte e finisce (e la finestra lo sa)",
          done.get("ok") is True and resumed)

    # due pause di fila
    done.clear()
    paused_msgs.clear()
    job2 = gcode.generate(make_doc(True, "uno", third=True), prof, opts)
    c.stream_job(job2.lines)
    until(lambda: len(paused_msgs) == 1, 60)
    c.resume_user_pause()
    until(lambda: len(paused_msgs) == 2, 60)
    check("due pause: la seconda arriva dopo aver ripreso la prima, col suo messaggio",
          paused_msgs == ["uno", "Pausa prima del livello C03"], paused_msgs)
    c.resume_user_pause()
    until(lambda: "ok" in done, 90)
    check("…e il lavoro finisce", done.get("ok") is True)

    # G-code di terzi con M0
    done.clear()
    paused_msgs.clear()
    c.stream_job(["G90 G21", "G0 X10 Y10", "M3 S100", "G1 X20 F3000", "M5", "M0", "G0 X30 Y10", "M5 S0"])
    until(lambda: paused_msgs, 30)
    check("G-code di un altro programma con M0: pausa con un messaggio generico", paused_msgs
          and "M0" in paused_msgs[0])
    c.resume_user_pause()
    until(lambda: "ok" in done, 30)
    check("…e dopo Riprendi finisce", done.get("ok") is True)
    c.disconnect_port()
    spin(0.3)

# ================================================================== 4. finestra del livello
from freelasercut.ui.main_window import MainWindow  # noqa: E402
from freelasercut.ui.panels_design import CutSettingsDialog  # noqa: E402

w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
cs = w.editor.doc.layer(2)
dlg = CutSettingsDialog(cs, w.profile, w)
check("finestra del livello: casella «Fermati prima di questo livello», spenta all'inizio", not dlg.pause.isChecked()
      and not dlg.pause_msg.isEnabled() and not dlg.pause_park.isEnabled())
dlg.pause.setChecked(True)
dlg.pause_msg.setText("Pulisci il pezzo")
dlg.pause_park.setChecked(True)
v = dlg.values()
check("…accesa: messaggio e parcheggio si possono scrivere e finiscono nei valori del livello",
      dlg.pause_msg.isEnabled() and v["pause_before"] and v["pause_msg"] == "Pulisci il pezzo" and v["pause_park"])
check("…il messaggio non va oltre 80 caratteri", dlg.pause_msg.maxLength() == 80)
dlg.close()
# la finestra della pausa
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
box = w._user_pause("Gira il pezzo")
check("finestra della pausa: messaggio, Riprendi e Annulla, non bloccante", box.text() == "Gira il pezzo"
      and len(box.buttons()) == 2 and not box.isModal() and "In pausa" in w.statusBar().currentMessage())
try:
    w._job_finished(False, "fermato")
except Exception as exc:  # noqa: BLE001
    print("    errore:", repr(exc))
spin(0.2)
check("…lavoro finito o fermato: la finestra della pausa si chiude da sola", getattr(w, "_pause_box", None) is None
      and not box.isVisible())
box = w._user_pause("tre")
w._user_resumed()
check("…ripreso da un'altra parte (barra, telefono): la finestra si chiude", w._pause_box is None and not box.isVisible())
box = w._user_pause("uno")
box2 = w._user_pause("due")
check("…una seconda pausa sostituisce la finestra della prima", not box.isVisible() and box2.isVisible()
      and w._pause_box is box2)
w._job_finished(True, "fatto")

print(f"\n{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
