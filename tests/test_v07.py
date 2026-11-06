# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.7: interfaccia «Banco» (predefinita) e scelta Banco / Classica."""
import sys, os, time, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ.pop("FLC_UI", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication, QMessageBox, QToolBar
from PySide6.QtCore import Qt, QPointF, QPoint, QEvent, QSettings
from PySide6.QtGui import QMouseEvent, QGuiApplication
from freelasercut.ui import style
from freelasercut.theme import QSS
app = QApplication([]); app.setStyle("Fusion"); style.load_fonts(); app.setFont(style.ui_font(9.5))
app.setStyleSheet(QSS + style.QSS_EXTRA)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)
def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents(); time.sleep(0.005)

from freelasercut.ui import banco as B
from freelasercut.profile import migrate_qsettings
qs = migrate_qsettings()
qs.remove("ui_mode")

# --- scelta dell'interfaccia
check("primo avvio: serve la scelta dell'interfaccia", B.needs_choice(qs))
check("senza scelta l'interfaccia predefinita è il Banco", B.ui_mode(qs) == "banco")
d = B.ChoiceDialog()
check("la finestra di scelta spiega che si cambia da Impostazioni", "Impostazioni" in " ".join(
    l.text() for l in d.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)))
d._pick("classica"); d.accept()
check("scelta Classica salvata", B.ui_mode(qs) == "classica" and not B.needs_choice(qs))
d2 = B.ChoiceDialog(); d2.reject()  # variabile nuova: la prima finestra (di cui sopra si sono letti i figli) resta viva
check("chiusa con la X vale la scelta evidenziata (Banco, consigliata)", B.ui_mode(qs) == "banco")
os.environ["FLC_UI"] = "classica"
check("la variabile FLC_UI ha la precedenza", B.ui_mode(qs) == "classica" and not B.needs_choice(qs))
os.environ.pop("FLC_UI")
B.save_mode("banco", qs)

from freelasercut.ui.main_window import MainWindow
from freelasercut.core.document import RectShape
w = MainWindow(); w.resize(1440, 900); w.show(); spin(0.8)
bc, cv, ed = w.banco, w.canvas, w.editor
check("il Banco è attivo", bc is not None and w.ui_mode == "banco")
check("barra dei menu e barre classiche nascoste", not w.menuBar().isVisible() and
      all(not tb.isVisible() for tb in w.findChildren(QToolBar) if tb.parent() is w and tb is not w.numeric
          and tb.objectName() != "bcTopBar"))
check("pannelli laterali (dock) tolti dal piano", all(not d.isVisible() for d in w.docks.values()))

# --- tutti i comandi restano raggiungibili
leaves = []
def walk(m):
    for a in m.actions():
        if a.menu() is not None: walk(a.menu())
        elif not a.isSeparator() and a.text(): leaves.append(a)
for a in w.menuBar().actions():
    if a.menu() is not None: walk(a.menu())
win_acts = set(map(id, w.actions()))
check("ogni comando dei menu resta agganciato alla finestra (scorciatoie vive)",
      all(id(a) in win_acts for a in leaves), f"{len(leaves)} comandi")
bc.palette.collect()
pal = set(id(a) for a, _ in bc.palette.entries)
check("la ricerca comandi contiene tutti i comandi dei menu", all(id(a) in pal for a in leaves), f"{len(bc.palette.entries)} voci")
bc.palette._filter("offset")
first = bc.palette.list.item(0).data(Qt.UserRole) if bc.palette.list.count() else None
check("cerca «offset» → primo risultato Offset", first is w.acts["offset"])
bc.palette._filter("allinea sinistra")
check("ricerca a più parole, senza accenti", bc.palette.list.count() >= 1)
bc.palette._filter("proprieta")
check("«proprieta» trova anche «Proprietà»", bc.palette.list.count() >= 1)
before = w.acts["snap_grid"].isChecked()
bc.palette._filter("griglia")
for i in range(bc.palette.list.count()):
    if bc.palette.list.item(i).data(Qt.UserRole) is w.acts["snap_grid"]:
        bc.palette._run(bc.palette.list.item(i)); break
spin(0.1)
check("Invio sulla voce esegue il comando", w.acts["snap_grid"].isChecked() != before)
w.acts["snap_grid"].trigger(); spin()

# --- impostazioni
check("menu Impostazioni con Interfaccia, Lingua e secondo monitor",
      hasattr(w, "m_settings") and w.ui_actions["banco"].isChecked() and not w.ui_actions["classica"].isChecked()
      and hasattr(w, "act_second_screen"))
check("il pulsante ingranaggio apre le Impostazioni", bc.gear.menu() is w.m_settings)
w.choose_interface("classica")
check("cambio interfaccia: salvato per il prossimo avvio (senza riavviare se si risponde no)",
      B.ui_mode(qs) == "classica" and w.isVisible())
B.save_mode("banco", qs)

# --- piano libero tra i pannelli
tl = cv.to_view(QPointF(0, 0)); br = cv.to_view(QPointF(w.profile.bed_x, 0))
check("il piano è inquadrato tra gli strati e la colonna destra",
      tl.x() >= bc.rail.geometry().right() - 2 and br.x() <= bc.right.geometry().left() + 2,
      f"piano x {tl.x():.0f}…{br.x():.0f}, strati fino a {bc.rail.geometry().right()}, colonna da {bc.right.geometry().left()}")

# --- disegno: gli strati compaiono come schede
vp = cv.viewport()
def V(x, y):
    p = cv.to_view(QPointF(x, y)); return QPoint(int(round(p.x())), int(round(p.y())))
def send(t, p, btn, btns):
    QApplication.sendEvent(vp, QMouseEvent(t, QPointF(p), QPointF(vp.mapToGlobal(p)), btn, btns, Qt.NoModifier))
def drag(a, b):
    send(QEvent.MouseButtonPress, a, Qt.LeftButton, Qt.LeftButton); spin()
    for i in range(1, 9):
        send(QEvent.MouseMove, a + (b - a) * (i / 8), Qt.NoButton, Qt.LeftButton); spin(0.01)
    send(QEvent.MouseButtonRelease, b, Qt.LeftButton, Qt.NoButton); spin()
cv.snap_objects = False
w.tool_actions["rect"].trigger(); spin()
check("con uno strumento di disegno compaiono le proprietà", bc.props_card.isVisible())
drag(V(60, 60), V(140, 110)); spin(0.2)
r = ed.doc.shapes[-1] if ed.doc.shapes else None
check("rettangolo disegnato nel Banco", isinstance(r, RectShape))
layers = [cs for cs in ed.doc.used_layers()]
cards = [c for c in bc.rail.inner.findChildren(__import__("PySide6.QtWidgets", fromlist=["QFrame"]).QFrame)
         if c.objectName() in ("bcCard", "bcCardOn")]
check("una scheda per lo strato usato", len(layers) >= 1 and len(cards) >= 1, f"{len(cards)} schede")
cs = layers[0]
p0 = cs.power_max
bc.rail._apply(cs.index, {"power_max": 55.0}, "Potenza livello"); spin(0.15)
check("la potenza cambiata dalla scheda arriva allo strato", abs(ed.doc.layers[cs.index].power_max - 55.0) < 1e-6)
w.acts["undo"].trigger(); spin(0.15)
check("…e si annulla con Ctrl+Z", abs(ed.doc.layers[cs.index].power_max - p0) < 1e-6)
ed.select([r]); spin(0.15)
check("con una selezione compare la barra contestuale", bc.ctx.isVisible())

# --- menu radiale
t, items = bc.radial_items(V(100, 85))
check("tasto destro su una forma: 8 comandi sulla selezione", t and len(items) == 8 and all(a is not None for _, a in items))
m = bc.open_radial(V(100, 85), vp.mapToGlobal(V(100, 85))); spin()
check("il menu radiale si apre", m.isVisible()); m.close()
ed.select([]); spin()
t, items = bc.radial_items(V(300, 380))
check("tasto destro sul vuoto: comandi del piano", len(items) == 8 and items[0][1] is w.acts["paste"])

# --- percorso del lavoro
bc.flow.refresh(); spin()
from PySide6.QtWidgets import QPushButton
start = [b for b in bc.flow.findChildren(QPushButton) if b.objectName() == "bcStart"]
check("il pulsante di avvio, senza laser, propone di collegarlo", start and "Collega" in start[0].text(), start[0].text() if start else "")

# --- Officina: cassetto e secondo monitor
bc.officina_show("laser"); spin(0.1)
check("Officina come cassetto con 6 schede", bc.officina.isVisible() and bc.officina.tabs.count() == 6)
check("col cassetto aperto la colonna destra lascia spazio", not bc.right.isVisible() and cv.fit_insets[2] >= 446)
bc.toggle_officina(); spin(0.1)
check("Ctrl+Shift+W la richiude", not bc.officina.isVisible())
bc.officina.to_window(QGuiApplication.primaryScreen()); spin(0.1)
check("Officina come finestra a sé (secondo monitor)", bc.officina.window_mode and bc.officina.isWindow())
bc.officina.close(); spin(0.2)
check("chiusa la finestra, l'Officina torna nel cassetto", not bc.officina.window_mode and not bc.officina.isWindow())
bc.check_screens(); spin(0.1)
check("un solo monitor: l'Officina resta nel cassetto", not bc.officina.window_mode)
bc.officina.to_window(QGuiApplication.primaryScreen()); spin(0.1)
w.act_second_screen.setChecked(False); spin(0.2)
check("Impostazioni → Officina sul secondo monitor disattivato: torna nel cassetto", not bc.officina.window_mode)
w.act_second_screen.setChecked(True); spin(0.1)
w.show_panel(w.docks["camera"]); spin(0.1)
check("Visualizza → Camera apre la scheda Camera dell'Officina",
      bc.officina.isVisible() and bc.officina.tabs.currentIndex() == bc.officina.index["camera"])
bc.officina.hide_drawer(); spin()

# --- cabina durante l'incisione
w.ctl._job_active = True
w.ctl.job_progress.emit(10, 100); spin(0.1)
check("lavoro avviato: si entra nella cabina", bc.cockpit_on and not bc.island.isVisible() and not bc.rail.isVisible())
check("Pausa e Stop visibili", all(x.isVisible() for x in bc.cockpit.widgets))
press = QMouseEvent(QEvent.MouseButtonPress, QPointF(V(300, 300)), QPointF(vp.mapToGlobal(V(300, 300))),
                    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
n0 = len(ed.doc.shapes)
w.tool_actions["rect"].trigger(); drag(V(250, 250), V(300, 300))
check("durante il lavoro il piano non si modifica col mouse", len(ed.doc.shapes) == n0)
w.tool_actions["select"].trigger()
w.ctl._job_active = False
w.ctl.job_finished.emit(True, "fine"); spin(0.1)
check("lavoro finito: si torna al Banco", not bc.cockpit_on and bc.island.isVisible())

# --- chiusura
qs.remove("win_state_v5")
w.close(); spin(0.2)
check("chiusura pulita, la disposizione classica non viene toccata", qs.value("win_state_v5") is None)

print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
