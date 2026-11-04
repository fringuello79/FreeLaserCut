# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.13.0: segni del piano più chiari, modalità esperto, configurazione guidata della macchina.
- le scritte accanto ai segni (testa e punto di partenza) solo con «Mostra i nomi sotto i comandi»;
- passando con il mouse su un segno compare la spiegazione (non durante il lavoro, non in modalità esperto);
- modalità esperto: niente nomi, scritte, spiegazioni e suggerimenti; gli avvisi di sicurezza restano;
- configurazione guidata: modello, angolo dello 0, prova delle frecce → verso degli assi."""
import sys, os, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.grbl import SIM_PORT
from freelasercut.core.document import RectShape
from freelasercut.profile import MachineProfile
from freelasercut import machines as _machines
machines_names = _machines.catalog_names()

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents(); time.sleep(0.01)
    return fn()

# ------------------------------------------------------------------ angolo dello 0 → verso degli assi
ci = MachineProfile.corner_inversion
check("angolo dello 0 → assi (coordinate positive): davanti sx normale, dietro sx Y, davanti dx X, dietro dx entrambi",
      (ci("fl"), ci("bl"), ci("fr"), ci("br")) == ((False, False), (False, True), (True, False), (True, True)))
check("con le coordinate negative (GRBL classico) il verso si rovescia", ci("br", True) == (False, False) and
      ci("fl", True) == (True, True))
for c in ("fl", "bl", "fr", "br"):
    for neg in (False, True):
        p = MachineProfile()
        p.invert_x, p.invert_y = ci(c, neg)
        p.negative_space = neg
        bx, by = p.to_bed(0, 0)
        exp = (p.bed_x if "r" in c[1:] else 0.0, p.bed_y if c[0] == "b" else 0.0)
        if (abs(bx - exp[0]) > 1e-6 or abs(by - exp[1]) > 1e-6) or p.corner_now() != c:
            check(f"angolo {c} (negative={neg}): lo 0 della macchina cade in quell'angolo del piano", False, (bx, by, exp))
            break
else:
    check("per ogni angolo, la testa a 0,0 compare proprio in quell'angolo del piano (anche in coordinate negative)", True)

from freelasercut.ui.main_window import MainWindow
w = MainWindow()
cv = w.canvas
# ------------------------------------------------------------------ livello di aiuto: tre voci, una sola attiva
lv = {k: w.acts[k] for k in ("help_beginner", "help_normal", "help_expert")}
check("livello di aiuto: tre voci, di partenza «Normale»", [a.isChecked() for a in lv.values()] == [False, True, False])
check("le tre voci sono sempre attivabili (niente voci grigie)", all(a.isEnabled() for a in lv.values()))
lv["help_beginner"].trigger()
check("scegliendo «Principiante» le altre si tolgono da sole", [a.isChecked() for a in lv.values()] == [True, False, False])
lv["help_expert"].trigger()
check("scegliendo «Esperto» si toglie «Principiante»", [a.isChecked() for a in lv.values()] == [False, False, True])
lv["help_expert"].trigger()
check("cliccando di nuovo la voce attiva resta attiva (una sempre scelta)", lv["help_expert"].isChecked())
check("Livello di aiuto sia in Impostazioni sia in Aiuto (lo stesso sottomenu)",
      w.m_help_level.menuAction() in w.m_settings.actions() and any(
          w.m_help_level.menuAction() in m.menu().actions() for m in w.menuBar().actions() if m.menu() and
          w.acts["help_mode"] in m.menu().actions()))
# ------------------------------------------------------------------ scritte dei segni
cv.set_head(100, 100)
cv.set_anchor_marker(150, 120, "punto scelto del disegno")
w.set_help_level("normale")
check("normale: niente scritta accanto al rombo né sotto la testa", not cv._anchor.show_label and cv._head.label == "")
w.set_help_level("principiante")
check("principiante: scritta accanto al rombo e «testa del laser» sotto il cerchio",
      cv._anchor.show_label and cv._head.label == "testa del laser")
w.set_help_level("normale")
check("si spengono insieme ai nomi dei comandi", not cv._anchor.show_label and cv._head.label == "")
# ------------------------------------------------------------------ spiegazione al passaggio del mouse
w.show(); w.resize(1300, 850); app.processEvents()
hp = QPointF(cv.mapFromScene(cv._head.pos()))
ap = QPointF(cv.mapFromScene(cv._anchor.pos()))
cv._update_marker_hint(hp + QPointF(3, 2))
check("mouse sulla testa: spiegazione «Testa del laser» (anche nel livello normale)",
      cv.marker_hint_shown() == "head" and cv._hint.title == "Testa del laser")
cv._update_marker_hint(ap)
check("mouse sul rombo: spiegazione del punto di partenza, con il punto scelto",
      cv.marker_hint_shown() == "anchor" and "Adesso: punto scelto del disegno." in cv._hint.body, cv._hint.body[:60])
cv._update_marker_hint(hp + QPointF(80, 80))
check("lontano dai segni: la spiegazione sparisce", cv.marker_hint_shown() is None)
w.ctl._job_active = True
cv._update_marker_hint(hp)
check("durante il lavoro: nessuna spiegazione", cv.marker_hint_shown() is None)
w.ctl._job_active = False
# ------------------------------------------------------------------ esperto
w.set_help_level("esperto")
check("esperto: nomi sotto i comandi spenti e niente scritte sui segni", cv._head.label == "" and not cv._anchor.show_label)
cv._update_marker_hint(hp)
check("esperto: nessuna spiegazione sui segni", cv.marker_hint_shown() is None)
w.banner.hide()
w.show_banner("prova suggerimento", "info", [], hint=True)
check("esperto: i suggerimenti (es. «Fai l'homing») non compaiono", not w.banner.isVisible())
w.show_banner("prova allarme", "alarm", [])
check("esperto: gli avvisi veri compaiono sempre", w.banner.isVisible())
w.banner.hide()
w.set_help_level("normale")
w.show_banner("prova suggerimento", "info", [], hint=True)
check("normale: i suggerimenti compaiono", w.banner.isVisible())
w.banner.hide()
check("configurazione guidata nel menu Impostazioni", w.acts["setup_wizard"] in w.m_settings.actions())
# chi aggiorna dalla 0.12: le vecchie scelte diventano un livello
w.qs.remove("help_level"); w.qs.setValue("cmd_labels", True)
a1 = w.help_level()
w.qs.setValue("cmd_labels", False); w.qs.setValue("expert_mode", True)
a2 = w.help_level()
w.qs.setValue("expert_mode", False)
check("aggiornando: nomi accesi → principiante, esperto → esperto, altrimenti normale",
      (a1, a2, w.help_level()) == ("principiante", "esperto", "normale"))
w.set_help_level("normale")
# ------------------------------------------------------------------ configurazione guidata (senza laser)
from freelasercut.ui.dialogs_setup import SetupWizard
d = SetupWizard(w)
check("configurazione guidata: 4 passi, modello attuale già scelto", d.stack.count() == 4 and
      d._same_model(), (d.model.currentText(), w.profile.model, w.profile.name))
# profilo che non viene dal catalogo (es. riconosciuto dalla scheda): resta quello, Avanti non lo sostituisce
saved = (w.profile.model, w.profile.name)
w.profile.model, w.profile.name = "Scheda riconosciuta XYZ", "Il mio laser"
d2 = SetupWizard(w)
check("profilo fuori catalogo: in cima «Il profilo attuale: Il mio laser», già scelto",
      d2.model.currentText() == "Il profilo attuale: Il mio laser" and d2._same_model())
d2.go(3)
check("…e il riepilogo parla di quel profilo, non del primo modello del catalogo", "Il mio laser" in d2.summary.text())
d2.reject()
w.profile.model, w.profile.name = saved
d.go(1); d.picker.choose("bl"); d.go(2)
check("senza laser collegato la prova delle frecce si rimanda (frecce nascoste)", not d.arrows_box.isVisibleTo(d))
d.go(3)
check("ultimo passo: i tre livelli, con quello attuale già scelto", d.help_level_choice() == "normale")
d.levels["esperto"].setChecked(True)
d.levels["principiante"].setChecked(True)
check("i tre livelli si escludono: uno solo scelto", d.help_level_choice() == "principiante" and
      not d.levels["esperto"].isChecked())
d.accept()
p = w.profile
check("dietro a sinistra → asse Y invertito, angolo salvato, assi da provare",
      (p.invert_x, p.invert_y, p.origin_corner, p.axes_tested) == (False, True, "bl", False))
check("le spunte del pannello Laser seguono", w.laser.inv_y.isChecked() and not w.laser.inv_x.isChecked())
check("configurazione segnata come fatta", w.qs.value("setup_wizard_done") in (True, "true"))
check("livello principiante come scelto (nomi accesi)", w.acts["help_beginner"].isChecked() and
      w.help_level() == "principiante")
q = MachineProfile.load(p.path())
check("salvato nel profilo della macchina", (q.invert_y, q.origin_corner) == (True, "bl"))
# dopo l'homing: coordinate negative scoperte → verso ricalcolato (angolo detto, assi non provati)
w.on_homed(True, True)
check("homing con coordinate negative: lo 0 resta dietro a sinistra, il verso si ricalcola da solo",
      (p.invert_x, p.invert_y) == ci("bl", True) and p.corner_now() == "bl")
w.on_homed(True, False)
p.negative_space = None
# ------------------------------------------------------------------ prova delle frecce con il simulatore
w.ctl.connect_port(SIM_PORT)
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings and w.canvas.head_pos() is not None)
until(lambda: w.ctl.last_status.get("state") == "Idle")
d0 = SetupWizard(w)
d0.go(1); d0.picker.choose("fl"); d0.go(2)
x0 = w.ctl.last_status.get("MPos", [0, 0])[0]
d0.jog("left")
check("freccia verso il bordo rifiutata dalla scheda (fuori area): non vale come prova e lo spiega",
      until(lambda: "rifiutato" in d0.arrows_lab.text(), 4) and not d0.tested[0], (x0, d0.arrows_lab.text()[:70]))
w.ctl.last_status["state"] = "Alarm"
d0.jog("right")
check("macchina in allarme: le frecce non partono, compare «Homing» con la spiegazione",
      "allarme" in d0.arrows_lab.text() and d0.b_home.isVisibleTo(d0) and not d0.tested[0])
w.ctl.last_status["state"] = "Idle"
d0.reject()
until(lambda: w.ctl.last_status.get("state") == "Idle", 3)
d = SetupWizard(w)
d.go(1); d.picker.choose("fl"); d.go(2)
check("con il laser collegato compaiono le frecce", d.arrows_box.isVisibleTo(d))
sent = []
w.ctl.line_sent.connect(lambda l: sent.append(l))
d.jog("right"); d.jog("up")
check("le frecce muovono la testa a laser spento, di 10 mm", until(lambda: len(sent) >= 2, 3) and
      all(l.startswith("$J=G91") for l in sent) and "X10.000" in sent[0] and "Y10.000" in sent[1], sent)
d.fix(1)
sent.clear(); d.jog("up")
check("«correggi» rovescia subito l'asse: la stessa freccia manda la testa dall'altra parte",
      until(lambda: sent, 3) and "Y-10.000" in sent[0], sent)
d.go(3)
check("riepilogo: assi provati", "provati con le frecce" in d.summary.text(), d.summary.text())
d.levels["normale"].setChecked(True)
d.accept()
p = w.profile
check("le frecce hanno l'ultima parola: Y invertito, assi provati, e lo 0 risulta «dietro a sinistra»",
      (p.invert_x, p.invert_y, p.tested_x, p.tested_y) == (False, True, True, True) and p.corner_now() == "bl")
check("jog del programma con il verso corretto", w.ctl.axis_sign == (1.0, -1.0))
w.on_homed(True, True)
check("assi già provati: l'homing non li cambia più", (p.invert_x, p.invert_y) == (False, True))
d = SetupWizard(w)
d.go(2); d.jog("left")
d.reject()
check("«Annulla»: il verso dei jog torna com'era", w.ctl.axis_sign == (1.0, -1.0))
# spunta a mano: l'angolo segue
w.profile.negative_space = None
w.set_axis_inverted("y", False)
check("spunta «Inverti Y» tolta a mano: lo 0 torna davanti e l'asse resta deciso", w.profile.corner_now()[0] == "f" and
      w.profile.tested_y)
# ---- regressioni trovate dalla revisione: assi provati in parte, «Non lo so», angolo che restava indietro
def fresh(**kw):
    p = w.profile
    p.invert_x = p.invert_y = False
    p.tested_x = p.tested_y = p.axes_tested = False
    p.origin_corner, p.negative_space = "", None
    for k, v in kw.items():
        setattr(p, k, v)
    w._sync_axes()
    return p
p = fresh()
d = SetupWizard(w); d.go(1); d.picker.choose("br"); d.go(2); d.jog("right"); d.fix(0); d.go(3); d.accept()
check("macchina con lo 0 dietro a destra, solo X provato e corretto: X normale, Y dall'angolo",
      (p.invert_x, p.invert_y, p.tested_x, p.tested_y) == (False, True, True, False), (p.invert_x, p.invert_y))
w.on_homed(True, True)
check("dopo l'homing (coordinate negative) si ricalcola solo Y; X provato resta com'è",
      (p.invert_x, p.invert_y) == (False, ci("br", True)[1]), (p.invert_x, p.invert_y))
p = fresh()
d = SetupWizard(w); d.go(1); d._dont_know(); d.go(2); d.go(3); d.accept()
check("«Non lo so» senza prove: niente angolo salvato, assi come prima", (p.origin_corner, p.invert_x, p.invert_y) ==
      ("", False, False))
w.on_homed(True, True)
check("…e l'homing con coordinate negative non li capovolge (come nella 0.12)", (p.invert_x, p.invert_y) == (False, False))
p = fresh()
d = SetupWizard(w); d.go(1); d.go(2); d.go(3); d.accept()
check("configurazione fatta con Avanti senza toccare niente: assi come prima, nessun angolo dato per vero",
      (p.origin_corner, p.invert_x, p.invert_y) == ("", False, False))
p = fresh(tested_x=True, tested_y=True)
w.on_homed(True, True)
check("assi provati, poi homing con coordinate negative: l'angolo mostrato si aggiorna (dietro a destra)",
      p.corner_now() == "br" and (p.invert_x, p.invert_y) == (False, False))
d = SetupWizard(w)
check("rifacendo la configurazione l'angolo proposto è quello vero", d.picker.corner == "br")
d.go(1); d.go(2); d.go(3); d.accept()
check("…e Fine senza toccare niente non rovina gli assi", (p.invert_x, p.invert_y, p.tested_x, p.tested_y) ==
      (False, False, True, True))
import json as _json
pp = os.path.join(tempfile.mkdtemp(), "vecchio.json")
_json.dump({"name": "vecchio", "axes_tested": True, "invert_y": True}, open(pp, "w"))
q = MachineProfile.load(pp)
check("profilo salvato dalla 0.13.0 con «assi provati»: tutti e due restano provati", q.tested_x and q.tested_y)
_json.dump({"name": "vecchio2", "axes_tested": False, "origin_corner": "fl"}, open(pp, "w"))
q = MachineProfile.load(pp)
check("profilo della 0.13.0 senza prove: l'angolo salvato in automatico non vale (l'homing non capovolge gli assi)",
      q.origin_corner == "" and not q.tested_x)
# un'altra macchina scelta nella configurazione: non eredita gli assi di quella attuale
p = fresh(invert_y=True, tested_y=True)
d = SetupWizard(w)
other = [n for n in machines_names if n != w.profile.model and "Longer" not in n][0]
d.model.setCurrentText(other); d.go(1); d.go(2); d.go(3); d.accept()
check("configurazione per un altro modello: niente Y invertito né assi «provati» presi dalla macchina di prima",
      w.profile.model == other and not w.profile.invert_y and not w.profile.tested_y, (w.profile.model, w.profile.invert_y))
# homing durante la configurazione: Fine non rimette il verso di prima
p = fresh(origin_corner="br")
p.invert_x, p.invert_y = MachineProfile.corner_inversion("br", None)
w._sync_axes()
d = SetupWizard(w); d.go(1); d.go(2)
w.on_homed(True, True)   # homing premuto dalla configurazione: coordinate negative → assi ricalcolati
d.go(3); d.accept()
check("homing fatto durante la configurazione: Fine tiene il verso ricalcolato, non quello di prima",
      (w.profile.invert_x, w.profile.invert_y) == MachineProfile.corner_inversion("br", True), (w.profile.invert_x, w.profile.invert_y))
fresh()
w.ctl.disconnect_port()
# ------------------------------------------------------------------ macchina senza homing: promemoria
w.ctl.connect_port(SIM_PORT)
until(lambda: w.ctl.board_settings)
until(lambda: False, 3.0)  # lascio passare il promemoria automatico dopo la connessione
w.profile.homing = False   # come una scheda con $22=0
w.banner.hide()
w._after_connect()
check("senza homing: promemoria con l'angolo dello 0 invece di «Fai l'homing»",
      w.banner.isVisible() and "angolo dello 0" in w.banner_text.text(), w.banner_text.text()[:80])
w.ctl.disconnect_port()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
app.processEvents()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
