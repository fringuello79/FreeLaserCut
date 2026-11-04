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
# ------------------------------------------------------------------ scritte dei segni
w.set_cmd_labels(False)
cv.set_head(100, 100)
cv.set_anchor_marker(150, 120, "punto scelto del disegno")
check("nomi spenti: niente scritta accanto al rombo né sotto la testa", not cv._anchor.show_label and cv._head.label == "")
w.set_cmd_labels(True)
check("«Mostra i nomi sotto i comandi»: scritta accanto al rombo e «testa del laser» sotto il cerchio",
      cv._anchor.show_label and cv._head.label == "testa del laser")
w.set_cmd_labels(False)
check("si spengono insieme ai nomi dei comandi", not cv._anchor.show_label and cv._head.label == "")
# ------------------------------------------------------------------ spiegazione al passaggio del mouse
w.show(); w.resize(1300, 850); app.processEvents()
cv.fit_bed() if hasattr(cv, "fit_bed") else None
app.processEvents()
hp = QPointF(cv.mapFromScene(cv._head.pos()))
ap = QPointF(cv.mapFromScene(cv._anchor.pos()))
cv._update_marker_hint(hp + QPointF(3, 2))
check("mouse sulla testa: spiegazione «Testa del laser»", cv.marker_hint_shown() == "head" and cv._hint.title == "Testa del laser")
cv._update_marker_hint(ap)
check("mouse sul rombo: spiegazione del punto di partenza, con il punto scelto",
      cv.marker_hint_shown() == "anchor" and "Adesso: punto scelto del disegno." in cv._hint.body, cv._hint.body[:60])
cv._update_marker_hint(hp + QPointF(80, 80))
check("lontano dai segni: la spiegazione sparisce", cv.marker_hint_shown() is None)
w.ctl._job_active = True
cv._update_marker_hint(hp)
check("durante il lavoro: nessuna spiegazione", cv.marker_hint_shown() is None)
w.ctl._job_active = False
# ------------------------------------------------------------------ modalità esperto
w.set_cmd_labels(True)
w.set_expert_mode(True)
check("modalità esperto: nomi sotto i comandi spenti e voce non attivabile",
      not w.acts["cmd_labels"].isChecked() and not w.acts["cmd_labels"].isEnabled() and cv._head.label == "")
w.set_cmd_labels(True)
check("modalità esperto: anche chiedendoli, i nomi restano spenti", not w.acts["cmd_labels"].isChecked())
cv._update_marker_hint(hp)
check("modalità esperto: nessuna spiegazione sui segni", cv.marker_hint_shown() is None)
w.banner.hide()
w.show_banner("prova suggerimento", "info", [], hint=True)
check("modalità esperto: i suggerimenti (es. «Fai l'homing») non compaiono", not w.banner.isVisible())
w.show_banner("prova allarme", "alarm", [])
check("modalità esperto: gli avvisi veri compaiono sempre", w.banner.isVisible())
w.banner.hide()
w.set_expert_mode(False)
check("modalità esperto spenta: «Mostra i nomi» di nuovo attivabile", w.acts["cmd_labels"].isEnabled())
w.show_banner("prova suggerimento", "info", [], hint=True)
check("senza modalità esperto i suggerimenti compaiono", w.banner.isVisible())
w.banner.hide()
check("le due voci sono nel menu Impostazioni", all(w.acts[k] in w.m_settings.actions() for k in ("setup_wizard", "expert_mode")))
# ------------------------------------------------------------------ configurazione guidata (senza laser)
from freelasercut.ui.dialogs_setup import SetupWizard
d = SetupWizard(w)
check("configurazione guidata: 4 passi, modello attuale già scelto", d.stack.count() == 4 and
      d.model.currentText() == w.profile.model)
d.go(1); d.picker.set_corner("bl"); d.go(2)
check("senza laser collegato la prova delle frecce si rimanda (frecce nascoste)", not d.arrows_box.isVisibleTo(d))
d.go(3)
d.c_expert.setChecked(True)
check("nomi e modalità esperto si escludono", not d.c_names.isChecked())
d.c_names.setChecked(True)
check("…in tutti e due i versi", not d.c_expert.isChecked())
d.accept()
p = w.profile
check("dietro a sinistra → asse Y invertito, angolo salvato, assi da provare",
      (p.invert_x, p.invert_y, p.origin_corner, p.axes_tested) == (False, True, "bl", False))
check("le spunte del pannello Laser seguono", w.laser.inv_y.isChecked() and not w.laser.inv_x.isChecked())
check("configurazione segnata come fatta", w.qs.value("setup_wizard_done") in (True, "true"))
check("nomi sotto i comandi accesi come scelto", w.acts["cmd_labels"].isChecked())
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
d = SetupWizard(w)
d.go(1); d.picker.set_corner("fl"); d.go(2)
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
d.c_names.setChecked(False); d.c_expert.setChecked(False)
d.accept()
p = w.profile
check("le frecce hanno l'ultima parola: Y invertito e lo 0 diventa «dietro a sinistra»",
      (p.invert_x, p.invert_y, p.axes_tested, p.origin_corner) == (False, True, True, "bl"))
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
check("spunta «Inverti Y» tolta a mano: lo 0 torna davanti", w.profile.origin_corner[0] == "f" and
      w.profile.axes_tested)
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
