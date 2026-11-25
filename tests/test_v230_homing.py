# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.0: l'angolo dello 0 scelto non si perde più (rapporto FLC-20261125-1014-BCAB di Sengir, Creality
Falcon A1 10W, 0.22.9: «l'homing per il programma continua ad essere solo nell'angolo sinistro ma davanti e devo
invertire sempre i comandi davanti/dietro»).

Che cosa succedeva fino alla 0.22.9, nella configurazione guidata:
- bastava premere una freccia perché l'asse risultasse «provato», anche senza guardare dove andava la testa e anche
  se la scheda si riavviava a metà spostamento (il Falcon A1 lo fa: 6 riavvii in 30 secondi nel registro del rapporto);
- con «Fine», se angolo scelto e frecce non andavano d'accordo, vinceva in silenzio la prova delle frecce e l'angolo
  scelto diventava quello delle frecce: da lì in poi il contrasto non si vedeva più e lo 0 restava davanti per sempre.
Ora: la freccia vale solo con «Sì, è andata lì» / «No, è andata al contrario»; allarme o riavvio durante lo
spostamento non valgono; con il contrasto, alla fine si chiede, e di partenza vale l'angolo scelto.
Uso: python tests/test_v230_homing.py [banco]
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
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui.dialogs_setup import SetupWizard  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


def spin(t=0.05):
    end = time.time() + t
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


RAW = {'0': '10', '1': '250', '3': '4', '10': '3', '20': '0', '21': '1', '22': '1', '23': '3', '27': '5.000',
       '100': '80.000', '101': '80.000', '110': '36000.000', '111': '36000.000', '120': '1000.000', '121': '1000.000',
       '130': '381.000', '131': '305.000'}


def sengir(**kw):
    """Il profilo del rapporto BCAB (0.22.9), com'era salvato: lo 0 davanti a sinistra, Y «provato» e non invertito.
    Sul Falcon A1 l'homing porta la testa dietro a sinistra e Y cresce verso il davanti: lo 0 giusto è «bl»."""
    d = dict(name="Creality Falcon A1 10W", model="Creality Falcon A1 10W", bed_x=381.0, bed_y=305.0,
             negative_space=False, hard_limits=True, homing=True, invert_x=False, invert_y=False, origin_corner="fl",
             tested_x=True, tested_y=True, axes_tested=True, raw_settings=dict(RAW))
    d.update(kw)
    return MachineProfile(**d)


w = MainWindow()
w.resize(1500, 950)
w.show()
spin(0.4)
jogs = []
real_jog = w.ctl.jog
w.ctl.jog = lambda dx=0.0, dy=0.0, feed=3000, tag=None: jogs.append((dx, dy))  # niente laser: si registra e basta


def wizard(prof, ask=None):
    prof.save()
    w.set_active_profile(prof)
    d = SetupWizard(w)
    d._can_jog = lambda: True  # come collegato al Falcon vero
    if ask is not None:
        d._ask_conflict = ask
    return d


def machine_dy(d):
    """Lo spostamento Y chiesto alla macchina dall'ultima freccia (con il verso della prova)."""
    dx, dy = jogs[-1]
    return dy * w.ctl.axis_sign[1]


# ====================================================================== 1. la freccia vale solo con la risposta
print("--- 1. prova delle frecce con la risposta")
d = wizard(sengir())
check("la finestra si apre sull'angolo salvato (davanti a sinistra, quello del rapporto)", d.picker.corner == "fl")
d.go(1)
d.picker.choose("bl")
check("scelto «dietro a sinistra»: Y segue l'angolo, invertito e da provare", d.inv[1] is True and d.tested[1] is False)
d.go(2)
check("all'inizio le risposte non si vedono", not d.confirm_box.isVisibleTo(d))
del jogs[:]
d.jog("down")
check("«↓ verso di te» parte: sul Falcon è Y+ (verso il davanti)", jogs and machine_dy(d) > 0, (jogs, w.ctl.axis_sign))
check("…ma non è ancora una prova: compaiono «Sì» e «No»", d.tested[1] is False and d.confirm_box.isVisibleTo(d)
      and "verso di te" in d.arrows_lab.text(), d.arrows_lab.text())
d._confirm(True)
check("«Sì, è andata lì»: Y provato, invertito; le risposte spariscono", d.tested[1] is True and d.inv[1] is True
      and not d.confirm_box.isVisibleTo(d))
d.go(5)
check("riepilogo senza avvisi: lo 0 è dietro a sinistra", "dietro a sinistra" in d.summary.text()
      and "Attenzione" not in d.summary.text(), d.summary.text()[:160])
d.accept()
p = w.profile
check("salvato: lo 0 dietro a sinistra, Y invertito e provato, nessun contrasto",
      (p.origin_corner, p.invert_y, p.tested_y) == ("bl", True, True) and p.corner_conflict() is None,
      (p.origin_corner, p.invert_y, p.tested_y))
check("…«casa» e pallino in alto a sinistra, «su» manda la testa verso il fondo (Y−)",
      p.home_corner() == (0.0, 305.0) and p.to_machine_delta(0, 10) == (0.0, -10.0))
d = wizard(w.profile)
check("riaperta: si apre su «dietro a sinistra»", d.picker.corner == "bl" and "Attenzione" not in d.corner_lab.text())
d.reject()

d = wizard(sengir())
d.go(1)
d.picker.choose("bl")
d.go(2)
d.jog("up")
d._confirm(False)
check("«No, è andata al contrario» = «correggi»: Y rovesciato e provato", d.inv[1] is False and d.tested[1] is True
      and not d.confirm_box.isVisibleTo(d) and "Corretto" in d.arrows_lab.text())
d.reject()

d = wizard(sengir())
d.go(1)
d.picker.choose("bl")
d.go(2)
d.jog("down")
d.go(3)
check("freccia senza risposta e si va avanti: non vale come prova", d.tested[1] is False and d._pending is None)
d.go(2)
check("…tornando indietro le risposte non ci sono più", not d.confirm_box.isVisibleTo(d))
d.reject()

d = wizard(sengir())
d.go(1)
d.picker.choose("bl")
d.go(2)
d.jog("down")
d.fix(1)
check("«correggi» con una freccia in attesa: chiude la domanda", d._pending is None and not d.confirm_box.isVisibleTo(d)
      and d.tested[1] is True)
d.reject()

# ====================================================================== 2. allarme o riavvio a metà spostamento
print("--- 2. scheda che si ferma durante lo spostamento")
for label, fire in (("riavvio della scheda (banner a metà jog, come nel registro BCAB)", lambda: w.ctl.board_rebooted.emit()),
                    ("allarme", lambda: w.ctl.alarm_raised.emit(3, "Reset durante il movimento"))):
    d = wizard(sengir())
    d.go(1)
    d.picker.choose("bl")
    d.go(2)
    d.jog("down")
    fire()
    spin(0.05)
    check(label + ": non vale come prova, lo spiega e propone l'homing",
          d.tested[1] is False and d._pending is None and not d.confirm_box.isVisibleTo(d)
          and "non vale come prova" in d.arrows_lab.text() and d.b_home.isVisibleTo(d), d.arrows_lab.text()[:90])
    d._confirm(True)
    check("…una risposta arrivata dopo non conta", d.tested[1] is False)
    d.reject()
d = wizard(sengir())
d.go(1)
d.picker.choose("bl")
d.go(2)
d.jog("down")
d._confirm(True)
w.ctl.board_rebooted.emit()
spin(0.05)
check("riavvio dopo una risposta già data: la prova resta", d.tested[1] is True)
d.reject()
d = wizard(sengir())
d.reject()
try:
    w.ctl.board_rebooted.emit()
    w.ctl.alarm_raised.emit(3, "x")
    spin(0.05)
    check("finestra chiusa: i segnali della scheda non la toccano più (scollegati)", True)
except Exception as e:  # noqa: BLE001
    check("finestra chiusa: i segnali della scheda non la toccano più (scollegati)", False, repr(e))

# ====================================================================== 3. angolo e frecce in contrasto: si chiede
print("--- 3. contrasto alla fine")
asked = []


def ask_default(c, a):
    asked.append((c, a))
    return "corner"


d = wizard(sengir(), ask_default)
d.go(1)
d.picker.choose("bl")
d.go(2)
d.jog("up")
d._confirm(False)  # risposta sbagliata (o la testa fermata dal finecorsa): Y normale, «provato»
d.go(5)
check("riepilogo: lo dice e avvisa che alla fine si chiede", "Attenzione" in d.summary.text()
      and "ti chiedo" in d.summary.text(), d.summary.text()[-160:])
d.accept()
p = w.profile
check("con Fine la domanda arriva, con i due angoli", asked == [("bl", "fl")], asked)
check("risposta «come ho scelto»: vale l'angolo, Y lo segue e torna da provare (prima vinceva la freccia)",
      (p.origin_corner, p.invert_y, p.tested_y) == ("bl", True, False) and p.corner_conflict() is None,
      (p.origin_corner, p.invert_y, p.tested_y))

d = wizard(sengir(), lambda c, a: "arrows")
d.go(1)
d.picker.choose("bl")
d.go(2)
d.jog("up")
d._confirm(False)
d.go(5)
d.accept()
p = w.profile
check("risposta «come dicono le frecce»: vale la prova, angolo coerente con gli assi",
      (p.origin_corner, p.invert_y, p.tested_y) == ("fl", False, True) and p.corner_conflict() is None)

# angolo già salvato «dietro a sinistra» e non ritoccato: un «No» sbagliato non lo cancella più in silenzio
del asked[:]
d = wizard(sengir(origin_corner="bl", invert_y=True), ask_default)
check("profilo coerente dietro a sinistra: si apre lì, senza contrasto", d.picker.corner == "bl" and not d._conflict)
d.go(1)
d.go(2)
d.jog("down")
d._confirm(False)
d.go(5)
check("angolo non ritoccato ma già scelto: il contrasto si vede lo stesso", "Attenzione" in d.summary.text())
d.accept()
p = w.profile
check("…e alla fine si chiede: vale l'angolo", asked == [("bl", "fl")] and (p.origin_corner, p.invert_y) == ("bl", True),
      (asked, p.origin_corner, p.invert_y))

# niente contrasto: nessuna domanda
del asked[:]
d = wizard(sengir(origin_corner="bl", invert_y=True), ask_default)
d.go(5)
d.accept()
check("angolo e assi d'accordo: nessuna domanda, niente cambia", not asked
      and (w.profile.origin_corner, w.profile.invert_y, w.profile.tested_y) == ("bl", True, True))

# coordinate non ancora note (niente homing): come prima, nessuna domanda e gli assi provati restano
del asked[:]
d = wizard(sengir(negative_space=None), ask_default)
d.go(1)
d.picker.choose("bl")
d.go(2)
d.jog("up")
d._confirm(False)
d.go(5)
d.accept()
p = w.profile
check("senza homing (coordinate non note): nessuna domanda, l'angolo scelto e la prova restano",
      not asked and (p.origin_corner, p.invert_y, p.tested_y) == ("bl", False, True), (asked, p.origin_corner, p.invert_y))

# «Non lo so»: nessun angolo, nessuna domanda
del asked[:]
d = wizard(sengir(origin_corner=""), ask_default)
d.go(1)
d._dont_know()
d.go(5)
d.accept()
check("«Non lo so»: nessuna domanda e nessun angolo salvato", not asked and w.profile.origin_corner == "")

# ====================================================================== 4. la domanda vera (finestra)
print("--- 4. la finestra della domanda")
del os.environ["FLC_NO_DIALOGS"]
try:
    w.set_active_profile(sengir())
    d = SetupWizard(w)
    seen = {}

    def click(which):
        box = app.activeModalWidget()
        if not isinstance(box, QMessageBox):
            QTimer.singleShot(30, lambda: click(which))
            return
        seen["text"] = box.text()
        seen["buttons"] = [b.text() for b in box.buttons()]
        box.buttons()[which].click() if which is not None else box.reject()

    QTimer.singleShot(50, lambda: click(1))
    r = d._ask_conflict("bl", "fl")
    check("la domanda nomina i due angoli e chiede dove va la testa con l'homing",
          "dietro a sinistra" in seen.get("text", "") and "davanti a sinistra" in seen.get("text", "")
          and "homing" in seen.get("text", ""), seen)
    check("…due risposte: come ho scelto / come dicono le frecce", len(seen.get("buttons", [])) == 2
          and any("come ho scelto" in t for t in seen["buttons"])
          and any("come dicono le frecce" in t for t in seen["buttons"]), seen.get("buttons"))
    btns = seen["buttons"]
    want = "arrows" if "frecce" in btns[1] else "corner"
    check("…cliccata la risposta, la restituisce", r == want, (r, btns))
    QTimer.singleShot(50, lambda: click(None))
    r = d._ask_conflict("bl", "fl")
    check("…chiusa senza scegliere: vale l'angolo scelto", r == "corner", r)
    d.reject()
finally:
    os.environ["FLC_NO_DIALOGS"] = "1"

# ====================================================================== 5. traduzioni
print("--- 5. traduzioni")
NEW = ["Sì, è andata lì", "No, è andata al contrario",
       "Hai premuto {0}: la testa è andata da quella parte? Rispondi qui sotto.",
       "Bene: {0} è giusto. Prova anche l'altro asse, poi «Avanti».",
       "La scheda si è fermata durante lo spostamento (allarme o riavvio): la testa non ha fatto il passo intero, quindi "
       "non vale come prova. Su alcune macchine succede quando la testa tocca un finecorsa: fai l'<b>Homing</b>, poi "
       "usa la freccia che la allontana dall'angolo.",
       "Dov'è lo 0?",
       "Hai scelto lo 0 <b>{0}</b>, ma la prova delle frecce lo mette <b>{1}</b>.<br>Dove va la testa quando fai "
       "l'homing?",
       "{0} (come ho scelto)", "{0} (come dicono le frecce)",
       "<b>Attenzione:</b> hai scelto lo 0 {0}, ma con la prova delle frecce risulta {1}. Se con l'homing la testa va "
       "{0}, torna indietro e rifai la prova delle frecce; con «Fine» ti chiedo quale dei due vale."]
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", lang + ".json"), encoding="utf-8") as fh:
        cat = json.load(fh)
    missing = [k for k in NEW if not cat.get(k)]
    check(f"testi nuovi tradotti in {lang}", not missing, missing)
    bad = [k for k in NEW if cat.get(k) and sorted(set(__import__("re").findall(r"\{\d\}", k)))
           != sorted(set(__import__("re").findall(r"\{\d\}", cat[k])))]
    check(f"…con gli stessi segnaposto {{0}} {{1}} ({lang})", not bad, bad)

w.ctl.jog = real_jog
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
ok = sum(results)
print(f"\n{ok}/{len(results)} verifiche superate")
sys.exit(0 if ok == len(results) else 1)
