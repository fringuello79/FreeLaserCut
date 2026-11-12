# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.0: il nesting manuale in una finestra sola (chiesto da Ale).

Prima c'erano due finestre che si coprivano («disegna l'area» e poi «Ottimizza lo spazio», questa in mezzo al piano e
bloccante). Ora:
1. una finestra sola, stretta e di lato: passo 1 «Area», passo 2 «Disponi i pezzi» nella stessa finestra;
2. poche scritte a vista: il resto dietro «Vedi istruzioni» e «Altre opzioni»;
3. «l'area non basta» si risolve nella stessa finestra («Ridisegna l'area» / «Cambia le opzioni»), senza avvisi a parte;
4. la spunta del laser pensa all'homing: lo propone con un avviso da confermare, lo fa, poi accende il laser al minimo;
   laser non collegato: lo dice e offre «Collega il laser»;
5. finché la finestra è aperta la vista si ingrandisce e si sposta ma i disegni non si toccano; il lato «macchina»
   (collegamento, homing, spostamenti) resta libero.

Il dato: un comando = (passo 1|2, pezzi, area, opzioni, esito dell'ultimo «Disponi»: mai fatto | riuscito | non basta)
× stato del laser (non collegato | collegato senza homing | homing in corso | pronto | macchina senza finecorsa).
"""
import ast
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
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QKeySequence, QMouseEvent, QPainterPath, QShortcutEvent, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QToolButton  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.grbl import SIM_PORT  # noqa: E402
from freelasercut.ui import nest_manual  # noqa: E402
from freelasercut.ui.dialogs_nest import NestDialog  # noqa: E402
from freelasercut.ui.editor import TOOL_LAYER  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas
vp = cv.viewport()
cv.fit_bed()
app.processEvents()
TRAP = [(40, 40), (200, 40), (170, 130), (70, 130)]
SMALL = [(40, 40), (110, 40), (75, 90)]
BIG = [(20, 20), (320, 20), (300, 200), (40, 200)]


def until(fn, t=10.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def mouse(target, pos, button=Qt.LeftButton, mods=Qt.NoModifier):
    """Un clic vero (premuto e rilasciato) su un oggetto della finestra: passa dai filtri come quello dell'utente."""
    pos = QPointF(pos)
    for kind, btns in ((QEvent.MouseButtonPress, button), (QEvent.MouseButtonRelease, Qt.NoButton)):
        QApplication.sendEvent(target, QMouseEvent(kind, pos, QPointF(target.mapToGlobal(pos.toPoint())), button, btns, mods))
    app.processEvents()


def click(bed, button=Qt.LeftButton):
    mouse(vp, cv.to_view(QPointF(*bed)), button, Qt.AltModifier)


def key(k, target=None, mods=Qt.NoModifier):
    QApplication.sendEvent(target or cv, QKeyEvent(QEvent.KeyPress, k, mods))
    app.processEvents()


def pieces(n, wd=20, h=12):
    out = []
    for i in range(n):
        s = RectShape(wd, h)
        s.apply(QTransform.fromTranslate(300 + (i % 4) * 30, 250 + (i // 4) * 25))
        out.append(s)
    ed.add(out, select=False)
    ed.select(out)
    return out


def pos(shapes):
    return [tuple(round(v, 3) for v in s.bounds().center().toTuple()) for s in shapes]


def inside(shape, poly, tol=0.05):
    area = QPainterPath()
    area.moveTo(*poly[0])
    for p in poly[1:]:
        area.lineTo(*p)
    area.closeSubpath()
    b = shape.bounds().adjusted(tol, tol, -tol, -tol)
    return all(area.contains(c) for c in (b.topLeft(), b.topRight(), b.bottomLeft(), b.bottomRight()))


def live():
    """I pezzi come sono adesso nel progetto (dopo un Ctrl+Z gli oggetti sono nuovi)."""
    return [s for s in ed.doc.shapes if s.layer != TOOL_LAYER]


def tool_shapes():
    return [s for s in ed.doc.shapes if s.layer == TOOL_LAYER]


def windows():
    """Le finestre a sé in vista (senza i suggerimenti e le tendine)."""
    return [x for x in app.topLevelWidgets() if x.isVisible() and x.windowType() in (Qt.Window, Qt.Dialog)]


def shown(x, panel):
    return x.isVisibleTo(panel)


def fresh(n=6, wd=20, h=12):
    ed.doc.shapes.clear()
    ed.selection = []
    out = pieces(n, wd, h)
    ed.undo_stack.clear()  # la cronologia parte da qui: conto solo i passi del comando
    ed.redo_stack.clear()
    return out


def tool_button(name):
    """Il pulsante della barra che sceglie uno strumento di disegno."""
    act = w.tool_actions.get(name)
    for b in w.findChildren(QToolButton):
        if act is not None and b.defaultAction() is act and b.isVisible():
            return b
    return None


# ================================================================== 0. progetto nuovo: annullare non lascia tracce
parts = fresh(3)
check("(progetto nuovo: il livello T1 non ha ancora le sue impostazioni)", TOOL_LAYER not in ed.doc.layers)
panel = w.nest_dialog(mode="manual")
for p in TRAP:
    panel.add_point(*p)
panel.finish()
panel.dlg.reject()
check("primo nesting manuale di un progetto, annullato al passo 2: nessun passo nella cronologia (il progetto è "
      "identico a prima)", len(ed.undo_stack) == 0 and not tool_shapes(), [e[0] for e in ed.undo_stack])

# ================================================================== A. una finestra sola, di lato, con poche scritte
parts = fresh()
before = pos(parts)
panel = w.nest_dialog(mode="manual")
check("si apre UNA finestra, «Nesting manuale», non bloccante", panel is not None and panel.isVisible()
      and not panel.isModal() and sorted(map(id, windows())) == sorted((id(w), id(panel)))
      and panel.windowTitle() == nest_manual.tr("Nesting manuale"), [x.windowTitle() for x in windows()])
check("è stretta (al massimo 400 punti) e sta di lato, a destra, fuori dal centro del piano",
      panel.width() <= 400 and panel.geometry().left() > w.geometry().center().x(), (panel.geometry(), w.geometry()))
check("passo 1 in vista, passo 2 no; i due passi sono scritti", panel.step == 1 and shown(panel.p1, panel)
      and not shown(panel.p2, panel) and not shown(panel.sum1, panel) and "1" in panel.head1.text()
      and "<b>" in panel.head1.text() and "2" in panel.head2.text() and "<b>" not in panel.head2.text())
labels = [lab.text() for lab in panel.p1.findChildren(type(panel.info)) if shown(lab, panel)]
check("a vista una riga sola di istruzioni: il resto è dietro «Vedi istruzioni»",
      not shown(panel.help, panel) and shown(panel.help_link, panel) and panel.help_link.plain == nest_manual.tr("Vedi istruzioni")
      and sum(len(re.sub(r"<[^>]+>", "", t)) for t in labels) < 220 and not any("Backspace" in t for t in labels),
      sum(len(t) for t in labels))
h0 = panel.height()
panel.help_link.linkActivated.emit("#")
app.processEvents()
check("clic su «Vedi istruzioni»: compaiono (togliere un punto, Invio, Backspace, Esc, vista, laser) e la finestra si "
      "allunga", shown(panel.help, panel) and all(t in panel.help.text() for t in ("Backspace", "Esc", "Invio"))
      and panel.height() > h0 and panel.help_link.plain == nest_manual.tr("Nascondi istruzioni"), (h0, panel.height()))
panel.toggle_help()
app.processEvents()
check("…e si richiudono: la finestra torna corta", not shown(panel.help, panel) and panel.height() == h0
      and panel.help_link.plain == nest_manual.tr("Vedi istruzioni"), (h0, panel.height()))
check("i pulsanti del passo 1: «Annulla» e «Chiudi l'area» (spento finché non ci sono 3 punti)",
      panel.b_cancel.text() == nest_manual.tr("Annulla") and panel.b_done.text() == nest_manual.tr("Chiudi l'area")
      and not panel.b_done.isEnabled())
for p in TRAP:
    click(p)
check("i clic sul piano mettono i punti (il passo 1 non blocca il disegno dell'area)", len(panel.tool.pts) == 4
      and panel.b_done.isEnabled() and "4" in panel.info.text(), panel.tool.pts)
mouse(panel.b_done, panel.b_done.rect().center())
dlg = panel.dlg
check("«Chiudi l'area»: la STESSA finestra passa al passo 2, nessun'altra finestra si apre",
      panel.isVisible() and panel.step == 2 and dlg is not None and sorted(map(id, windows())) == sorted((id(w), id(panel)))
      and not dlg.isWindow() and dlg.window() is panel and w._nest_panel is panel and w._nest_manual_dlg is dlg,
      [x.windowTitle() for x in windows()])
cm2 = [float(x) for x in re.findall(r"(\d+\.\d) cm²", panel.sum_text.text())]
check("il passo 1 resta in una riga: «Area: 4 punti · 117 cm²» e «Ridisegna»", not shown(panel.p1, panel)
      and shown(panel.sum1, panel) and "4" in panel.sum_text.text() and cm2 and abs(cm2[0] - 117.0) < 2.0
      and shown(panel.redraw_link, panel) and "<b>" in panel.head2.text() and "<b>" not in panel.head1.text(),
      panel.sum_text.text())
check("passo 2, in vista solo l'essenziale: pezzi, distanza, rotazioni, «Disponi»",
      all(shown(x, panel) for x in (dlg.what, dlg.gap, dlg.rot, dlg.b_run, dlg.b_close, dlg.more_link))
      and not any(shown(x, panel) for x in (dlg.margin, dlg.prec, dlg.keep, dlg.holes, dlg.common, dlg.keep_area,
                                            dlg.area, dlg.multi, dlg.custom, dlg.nofit))
      and dlg.b_close.text() == nest_manual.tr("Annulla") and dlg.b_run.text() == nest_manual.tr("Disponi")
      and "6" in dlg.what.text())
check("…e ci sta tutto dentro la finestra stretta (niente tagliato a destra)", dlg.width() <= panel.width()
      and dlg.b_run.mapTo(panel, dlg.b_run.rect().bottomRight()).x() <= panel.width(), (dlg.width(), panel.width()))
check("…senza la spiegazione lunga di «Ottimizza lo spazio»",
      not any(shown(lab, panel) and "sprecandone" in lab.text() for lab in dlg.findChildren(type(panel.info))))
h1 = panel.height()
mouse(dlg.more_link, QPoint(5, 5))
check("clic su «Altre opzioni»: margine, precisione, tieni insieme, fori, linee comuni, lascia l'area; la finestra si "
      "allunga", all(shown(x, panel) for x in (dlg.margin, dlg.prec, dlg.keep, dlg.holes, dlg.common, dlg.keep_area))
      and not shown(dlg.area, panel) and not shown(dlg.multi, panel) and panel.height() > h1
      and nest_manual.tr("Nascondi le altre opzioni") in dlg.more_link.text(), (h1, panel.height()))
check("le spunte lunghe vanno a capo (testo di fianco, che si clicca come quello di una spunta)",
      dlg.holes.text() == "" and dlg.holes.wrapped_label.wordWrap() and "fori" in dlg.holes.wrapped_label.text()
      and panel.width() <= 400)
was = dlg.holes.isChecked()
mouse(dlg.holes.wrapped_label, QPoint(5, 5))
check("…clic sul testo: la spunta cambia", dlg.holes.isChecked() != was)
dlg.holes.setChecked(was)
dlg.toggle_more()
app.processEvents()
check("…e si richiudono", not shown(dlg.margin, panel) and panel.height() == h1, (h1, panel.height()))

# ================================================================== B. Disponi, Fatto
u0 = len(ed.undo_stack)
mouse(dlg.b_run, dlg.b_run.rect().center())
check("«Disponi»: i pezzi entrano nell'area, la finestra resta aperta con l'esito", all(inside(s, TRAP) for s in parts)
      and panel.isVisible() and dlg.placed and "6" in dlg.result.text() and dlg.no_fit is None, dlg.result.text())
check("…i pulsanti diventano «Disponi di nuovo» e «Fatto» (quello in evidenza), «Ridisegna» sparisce",
      dlg.b_run.text() == nest_manual.tr("Disponi di nuovo") and dlg.b_close.text() == nest_manual.tr("Fatto")
      and dlg.b_close.objectName() == "primary" and dlg.b_run.objectName() != "primary"
      and not shown(panel.redraw_link, panel))
mouse(dlg.b_close, dlg.b_close.rect().center())
check("«Fatto»: la finestra si chiude, il comando è finito, l'area è sparita", not panel.isVisible()
      and w._nest_panel is None and not tool_shapes() and windows() == [w] and not panel.view_only.on)
check("…ed è un solo passo di Ctrl+Z", len(ed.undo_stack) == 1, len(ed.undo_stack))
ed.undo()
check("…che riporta i pezzi dov'erano", pos(live()) == before and not tool_shapes())

# Annulla e la X
parts = fresh()
before = pos(parts)
panel = w.nest_dialog(mode="manual")
for p in TRAP:
    panel.add_point(*p)
panel.finish()
mouse(panel.dlg.b_close, panel.dlg.b_close.rect().center())
check("passo 2, «Annulla» prima di disporre: finestra chiusa, niente spostato, nessun passo nella cronologia",
      not panel.isVisible() and w._nest_panel is None and pos(parts) == before and not tool_shapes()
      and len(ed.undo_stack) == 0 and ed.selection == parts, len(ed.undo_stack))
panel = w.nest_dialog(mode="manual")
for p in TRAP:
    panel.add_point(*p)
panel.finish()
panel.close()
app.processEvents()
check("passo 2, chiusa con la X prima di disporre: come «Annulla»", not panel.isVisible() and w._nest_panel is None
      and pos(parts) == before and not tool_shapes() and len(ed.undo_stack) == 0 and not panel.view_only.on)
panel = w.nest_dialog(mode="manual")
for p in TRAP:
    panel.add_point(*p)
panel.finish()
panel.dlg.run()
panel.close()
app.processEvents()
check("passo 2, chiusa con la X dopo aver disposto: come «Fatto» (i pezzi restano a posto, un passo solo)",
      w._nest_panel is None and all(inside(s, TRAP) for s in parts) and not tool_shapes() and len(ed.undo_stack) == 1)
ed.undo()
parts = live()
ed.select(parts)
panel = w.nest_dialog(mode="manual")
panel.add_point(50, 50)
panel.close()
app.processEvents()
check("passo 1, chiusa con la X: annullato, niente cambia", w._nest_panel is None and pos(parts) == before
      and not tool_shapes() and cv.tool is cv.tools["select"] and not panel.view_only.on)
got = []
panel = w.nest_dialog(mode="manual")
panel.done.connect(lambda d: got.append(d))
for p in TRAP:
    panel.add_point(*p)
panel.finish()
panel.dlg.run()
panel.dlg.accept()
check("la fine del comando viene segnalata una volta sola", len(got) == 1 and got[0] is not None, len(got))

# ================================================================== C. l'area non basta: tutto nella stessa finestra
parts = fresh(14, 40, 30)
before = pos(parts)
panel = w.nest_dialog(mode="manual")
for p in SMALL:
    panel.add_point(*p)
panel.finish()
dlg = panel.dlg
mouse(dlg.b_run, dlg.b_run.rect().center())
check("l'area non basta: lo dice nella stessa finestra (nessun avviso a parte), con i due pulsanti",
      panel.isVisible() and panel.step == 2 and sorted(map(id, windows())) == sorted((id(w), id(panel)))
      and shown(dlg.nofit, panel) and shown(dlg.b_redraw, panel) and shown(dlg.b_options, panel)
      and dlg.no_fit is not None and dlg.no_fit[1] == 14 and str(dlg.no_fit[0]) in dlg.result.text(), dlg.result.text())
check("…niente spostato, l'area è ancora lì, «Annulla» resta «Annulla»", pos(parts) == before and len(tool_shapes()) == 1
      and not dlg.placed and dlg.b_close.text() == nest_manual.tr("Annulla"))
check("la funzione con l'avviso a parte non c'è più", not hasattr(nest_manual, "ask_new_area")
      and not hasattr(dlg, "ask_new_area"))
mouse(dlg.b_options, dlg.b_options.rect().center())
check("«Cambia le opzioni»: i due pulsanti spariscono, si aprono le altre opzioni, il comando continua",
      not shown(dlg.nofit, panel) and shown(dlg.margin, panel) and panel.isVisible() and panel.step == 2
      and len(tool_shapes()) == 1)
mouse(dlg.b_run, dlg.b_run.rect().center())
check("…si riprova: se ancora non basta, di nuovo i due pulsanti", shown(dlg.nofit, panel) and pos(parts) == before)
tool_before = panel.tool
mouse(dlg.b_redraw, dlg.b_redraw.rect().center())
check("«Ridisegna l'area»: stessa finestra, di nuovo il passo 1, l'area vecchia sparisce, i pezzi sono gli stessi",
      panel.isVisible() and panel.step == 1 and w._nest_panel is panel and panel.dlg is None and not tool_shapes()
      and panel.parts == parts and shown(panel.p1, panel) and not shown(panel.sum1, panel) and not shown(panel.p2, panel)
      and sorted(map(id, windows())) == sorted((id(w), id(panel))))
check("…si disegna da capo (nessun punto, strumento dell'area attivo, niente nella cronologia)",
      panel.tool is not tool_before and panel.tool.pts == [] and cv.tool is panel.tool and not panel.b_done.isEnabled()
      and len(ed.undo_stack) == 0 and panel.view_only.on, len(ed.undo_stack))
for p in BIG:
    click(p)
check("i punti della nuova area si mettono con i clic", len(panel.tool.pts) == 4, panel.tool.pts)
key(Qt.Key_Return)
dlg2 = panel.dlg
check("Invio chiude la nuova area: di nuovo il passo 2, con una finestra di opzioni nuova", panel.step == 2
      and dlg2 is not None and dlg2 is not dlg and dlg2.manual is not dlg.manual and len(dlg2.parts) == 14)
dlg2.run()
check("nell'area grande entrano tutti", dlg2.placed and all(inside(s, BIG) for s in parts))
dlg2.accept()
check("tutto il comando (prima area, seconda area, pezzi) è un solo passo di Ctrl+Z", len(ed.undo_stack) == 1
      and not tool_shapes() and w._nest_panel is None, len(ed.undo_stack))
ed.undo()
check("…che riporta tutto com'era", pos(live()) == before and not tool_shapes())
parts = live()
ed.select(parts)
# «Ridisegna» dalla riga del passo 1
panel = w.nest_dialog(mode="manual")
for p in SMALL:
    panel.add_point(*p)
panel.finish()
panel.redraw_link.linkActivated.emit("#")
app.processEvents()
check("«Ridisegna» nella riga dell'area (prima di disporre): si torna al passo 1", panel.step == 1 and not tool_shapes()
      and panel.isVisible() and cv.tool is panel.tool)
for p in SMALL:
    panel.add_point(*p)
panel.finish()
ed.doc.remove(list(parts))  # i pezzi spariscono (non dovrebbe succedere: i disegni sono bloccati) e poi si ridisegna
panel.redraw()
app.processEvents()
check("se i pezzi non ci sono più, «Ridisegna» chiude il comando senza inciampare", not panel.isVisible()
      and w._nest_panel is None and not panel.view_only.on)
# la distanza conta: con 30 mm fra i pezzi non entrano, con 1 mm sì
parts = fresh(6)
panel = w.nest_dialog(mode="manual")
for p in TRAP:
    panel.add_point(*p)
panel.finish()
dlg = panel.dlg
dlg.gap.setValue(40.0)
dlg.run()
no1 = dlg.no_fit
dlg.change_options()
dlg.gap.setValue(1.0)
dlg.run()
check("«Cambia le opzioni» serve: con 40 mm di distanza non entrano, con 1 mm sì (stessa area, stessa finestra)",
      no1 is not None and dlg.no_fit is None and dlg.placed and all(inside(s, TRAP) for s in parts)
      and not shown(dlg.nofit, panel), (no1, dlg.no_fit))
dlg.accept()

# ================================================================== D. si guarda ma non si tocca
parts = fresh(3)
before = pos(parts)
ed.select([])
rect_btn = tool_button("rect")
free_ok = False
if rect_btn is not None:
    mouse(rect_btn, rect_btn.rect().center())
    free_ok = cv.tool is cv.tools["rect"]
    cv.set_tool("select")
check("(controllo: senza il nesting aperto il pulsante «Rettangolo» della barra sceglie lo strumento)", free_ok,
      rect_btn)
ed.select(parts)
panel = w.nest_dialog(mode="manual")
vo = panel.view_only
check("con la finestra aperta il filtro «si guarda ma non si tocca» è attivo", vo.on and vo.blocked == 0)
mouse(rect_btn, rect_btn.rect().center())
check("passo 1, clic su uno strumento della barra: non succede niente, e lo dice in basso",
      cv.tool is panel.tool and panel.isVisible() and vo.blocked == 1
      and "nesting" in w.statusBar().currentMessage().lower(), (cv.tool.name, w.statusBar().currentMessage()))
mouse(w.menuBar(), QPoint(20, 8))
check("…clic sulla barra dei menu: nessun menu si apre", vo.blocked == 2 and app.activePopupWidget() is None)
n_blocked = vo.blocked
key(Qt.Key_A)
check("…un tasto qualsiasi sul piano non arriva (i tasti del disegno dell'area sì)", vo.blocked == n_blocked + 1)
click((50, 50))
click((120, 50))
key(Qt.Key_Backspace)
check("…Backspace toglie l'ultimo punto, come prima", len(panel.tool.pts) == 1 and vo.blocked == n_blocked + 1)
click((120, 50))
click((90, 110))
z0 = cv.scale if not callable(getattr(cv, "scale", None)) else None
t0 = cv.to_view(QPointF(100, 100))
mouse(vp, QPointF(300, 300), Qt.MiddleButton)
check("…il tasto centrale (spostare la vista) passa", vo.blocked == n_blocked + 1 and len(panel.tool.pts) == 3)
w.acts["zoom_in"].trigger()
app.processEvents()
check("…ingrandire funziona", cv.to_view(QPointF(100, 100)) != t0 or z0 != getattr(cv, "scale", None))
cv.fit_bed()
check("le scorciatoie che cambiano i disegni sono ferme (Canc, Ctrl+Z, Ctrl+V, Ctrl+A), quelle della vista e della "
      "macchina no (Ctrl+0, Ctrl++, Ctrl+H)",
      all(vo.stops(w, QShortcutEvent(QKeySequence(k), 0)) for k in ("Del", "Ctrl+Z", "Ctrl+V", "Ctrl+A", "Ctrl+N"))
      and not any(vo.stops(w, QShortcutEvent(QKeySequence(k), 0)) for k in ("Ctrl+0", "Ctrl++", "Ctrl+-", "Ctrl+H")))
n_blocked = vo.blocked
QApplication.sendEvent(w, QShortcutEvent(QKeySequence("Ctrl+A"), 0))
check("…una scorciatoia ferma viene davvero fermata dal filtro", vo.blocked == n_blocked + 1)
press = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
check("il lato macchina resta libero: Connetti, porta, pannelli Laser e Sposta",
      not vo.stops(w.btn_connect, press) and not vo.stops(w.port_combo, press)
      and not any(vo.stops(c, press) for c in w.laser.findChildren(QToolButton)[:3] + w.move.findChildren(QToolButton)[:3])
      and not vo.stops(w.laser, press))
check("…le linguette dei piani e (interfaccia Classica) il pannello dei livelli no", vo.stops(w.plate_bar, press)
      and (w.banco is not None or (vo.stops(w.layers, press)
                                   and all(vo.stops(c, press) for c in w.layers.findChildren(QToolButton)[:3]))))
if w.banco is not None:
    check("interfaccia Banco: liberi l'Officina (pannelli della macchina), il pulsante che la apre, il collegamento e "
          "i comandi del lavoro; fermi la ricerca dei comandi, gli strumenti e i livelli sopra la tela",
          not vo.stops(w.banco.pill, press) and not vo.stops(w.banco.b_off, press) and not vo.stops(w.banco.officina, press)
          and not vo.stops(w.banco.cockpit.bottom, press) and vo.stops(w.banco.search, press) and vo.stops(rect_btn, press)
          and vo.stops(w.banco.island, press))
check("…la finestra del nesting e le sue parti sono sempre libere", not vo.stops(panel.b_done, press)
      and not vo.stops(panel.laser, press) and not vo.stops(panel, press))
panel.finish()
dlg = panel.dlg
check("passo 2: il filtro resta attivo", vo.on and panel.step == 2)
sel = list(ed.selection)
n_blocked = vo.blocked
click(parts[0].bounds().center().toTuple())
check("passo 2, clic su un pezzo nel piano: non si seleziona e non si sposta niente", ed.selection == sel
      and pos(parts) == before and vo.blocked == n_blocked + 1)
key(Qt.Key_Delete)
key(Qt.Key_Return)
check("…i tasti sul piano non arrivano (nemmeno Invio: l'area è già chiusa)", vo.blocked == n_blocked + 3
      and len(ed.doc.shapes) == 4 and panel.step == 2)
mouse(rect_btn, rect_btn.rect().center())
check("…gli strumenti della barra restano fermi", cv.tool is cv.tools["select"] and vo.blocked == n_blocked + 4)
t0 = cv.to_view(QPointF(100, 100))
mouse(vp, QPointF(300, 300), Qt.MiddleButton)
key(Qt.Key_Space)
check("…ma la vista si sposta (tasto centrale, Spazio) e si ingrandisce", vo.blocked == n_blocked + 4)
QApplication.sendEvent(cv, QKeyEvent(QEvent.KeyRelease, Qt.Key_Space, Qt.NoModifier))
mouse(dlg.b_run, dlg.b_run.rect().center())
check("…e «Disponi» nella finestra funziona", dlg.placed)
dlg.accept()
check("finito il comando il filtro è tolto", not vo.on)
ed.select([])
n_blocked = vo.blocked
mouse(rect_btn, rect_btn.rect().center())
check("…e la barra degli strumenti torna a rispondere", cv.tool is cv.tools["rect"] and vo.blocked == n_blocked)
cv.set_tool("select")

# un filtro che inciampa non blocca il programma
parts = fresh(3)
panel = w.nest_dialog(mode="manual")
vo = panel.view_only
real = vo.stops
vo.stops = lambda *a: 1 / 0
mouse(rect_btn, rect_btn.rect().center())
check("se il filtro inciampa lascia passare (non blocca tutto il programma)", vo.blocked == 0 and not panel.isVisible())
vo.stops = real
cv.set_tool("select")
app.processEvents()

# ================================================================== E. la spunta del laser e l'homing
parts = fresh(3)
w.qs.setValue("port", "")
panel = w.nest_dialog(mode="manual")
asked = []
panel.ask_homing = lambda: (asked.append(1), False)[1]
panel.laser.setChecked(True)
check("laser non collegato: la spunta non resta, lo dice e offre «Collega il laser»", not panel.laser.isChecked()
      and "collegato" in panel.info.text() and shown(panel.b_connect, panel) and not asked, panel.info.text())
mouse(panel.b_connect, panel.b_connect.rect().center())
check("«Collega il laser» senza una porta usata prima: dice di collegarlo dalla finestra principale",
      not w.ctl.connected and "Connetti" in panel.info.text() or "principale" in panel.info.text(), panel.info.text())
w.qs.setValue("port", SIM_PORT)
mouse(panel.b_connect, panel.b_connect.rect().center())
check("«Collega il laser» con la porta usata l'ultima volta: si collega e dice di rimettere la spunta",
      w.ctl.connected and w.ctl.port == SIM_PORT and not shown(panel.b_connect, panel) and "spunta" in panel.info.text(),
      panel.info.text())
w.ctl.sim.speedup = 50
until(lambda: w.ctl.board_settings and w.ctl.last_status.get("state") == "Idle")
w.profile.homing = True
w.ctl.homed = False
sent = []
w.ctl.line_sent.connect(lambda line: sent.append(line))
panel.laser.setChecked(True)
check("collegato ma senza homing: chiede conferma; con «Annulla» niente homing e la spunta resta spenta",
      asked == [1] and not panel.laser.isChecked() and "$H" not in sent and "homing" in panel.info.text()
      and not w.ctl.fire_active, (asked, sent, panel.info.text()))
panel.ask_homing = lambda: (asked.append(2), True)[1]
w.ctl.sim.speedup = 1  # l'homing dura un momento: guardo che cosa succede mentre va
panel.laser.setChecked(True)
check("con «OK»: parte l'homing; nel frattempo la spunta è segnata ma ferma, il laser è spento e lo dice",
      asked == [1, 2] and "$H" in sent and panel.laser.isChecked() and not panel.laser.isEnabled()
      and not w.ctl.fire_active and "Homing" in panel.info.text(), (asked, sent[-3:], panel.info.text()))
n_sent = len(sent)
panel.add_point(60, 70)
check("un punto messo durante l'homing: la testa non viene mandata da nessuna parte, la spunta resta",
      not [line for line in sent[n_sent:] if line.startswith("G53")] and panel.laser.isChecked()
      and "Homing" in panel.info.text(), sent[n_sent:])
w.ctl.sim.speedup = 50
ok = until(lambda: w.ctl.fire_active, 30)
s_vals = [float(m.group(1)) for line in sent for m in [re.match(r"^M3 S([\d.]+)$", line)] if m]
cap = w.laser.glow_cap / 100.0 * w.profile.s_max
check("finito l'homing il laser si accende da solo al minimo (entro il limite della Lucciola) e la spunta è attiva",
      ok and w.ctl.homed and w.laser._glow_on and panel.laser.isChecked() and panel.laser.isEnabled()
      and s_vals and max(s_vals) <= cap + 1e-6 and sent.index("$H") < max(i for i, x in enumerate(sent) if x.startswith("M3 S")),
      (s_vals, cap, panel.info.text()))
click((80, 90))
check("…e al punto successivo la testa ci va", until(lambda: abs(w.ctl.sim.pos[0] - w.profile.to_machine(80, 90)[0]) < 0.8
                                                    and abs(w.ctl.sim.pos[1] - w.profile.to_machine(80, 90)[1]) < 0.8, 15),
      w.ctl.sim.pos)
until(lambda: w.ctl.last_status.get("state") == "Idle" and not w.ctl.busy, 15)
panel.laser.setChecked(False)
check("tolta la spunta il laser si spegne", until(lambda: not w.ctl.fire_active, 3) and not w.laser._glow_on)
asked.clear()
panel.laser.setChecked(True)
check("con l'homing già fatto non chiede niente: accende subito", not asked and until(lambda: w.ctl.fire_active, 3)
      and panel.laser.isChecked())
panel.cancel()
check("annullando il laser si spegne", until(lambda: not w.ctl.fire_active, 3) and not w.laser._glow_on)

# homing che non riesce
ed.select(parts)
panel = w.nest_dialog(mode="manual")
panel.ask_homing = lambda: True
w.ctl.homed = False
w.ctl.sim.speedup = 1
panel.laser.setChecked(True)
w.ctl.alarm_raised.emit(9, "prova")
check("allarme durante l'homing: la spunta si spegne, torna usabile, e dice che l'homing non è riuscito",
      not panel.laser.isChecked() and panel.laser.isEnabled() and "9" in panel.info.text()
      and "non riuscito" in panel.info.text() and not w.ctl.fire_active, panel.info.text())
w.ctl.sim.speedup = 50
until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 30)
until(lambda: False, 0.3)
check("…e se poi l'homing finisce lo stesso, il laser NON si accende da solo", not w.ctl.fire_active
      and not panel.laser.isChecked())
w.ctl.homed = False
nest_manual.HOMING_WAIT_S = 0.05
w.ctl.sim.speedup = 1
panel.laser.setChecked(True)
until(lambda: not panel.laser.isChecked(), 3)
check("homing che non finisce in tempo: la spunta si spegne e lo dice", not panel.laser.isChecked()
      and panel.laser.isEnabled() and "in tempo" in panel.info.text(), panel.info.text())
nest_manual.HOMING_WAIT_S = 90.0
w.ctl.sim.speedup = 50
until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 30)
# chiusa durante l'homing
w.ctl.homed = False
w.ctl.sim.speedup = 1
panel.laser.setChecked(True)
panel.cancel()
w.ctl.sim.speedup = 50
until(lambda: w.ctl.homed and w.ctl.last_status.get("state") == "Idle", 30)
until(lambda: False, 0.3)
check("finestra annullata durante l'homing: a homing finito il laser resta spento", not w.ctl.fire_active
      and not w.laser._glow_on)
# macchina senza finecorsa: come prima, nessuna domanda
ed.select(parts)
panel = w.nest_dialog(mode="manual")
asked.clear()
panel.ask_homing = lambda: (asked.append(3), True)[1]
w.profile.homing = False
w.ctl.homed = False
n_sent = len(sent)
panel.laser.setChecked(True)
check("macchina senza finecorsa: nessuna domanda e nessun homing, il laser si accende come prima",
      not asked and "$H" not in sent[n_sent:] and until(lambda: w.ctl.fire_active, 3) and panel.laser.isChecked())
for p in TRAP:
    panel.add_point(*p)
until(lambda: w.ctl.last_status.get("state") == "Idle" and not w.ctl.busy, 20)
panel.finish()
check("chiusa l'area (passo 2): il laser si spegne e la spunta torna spenta",
      until(lambda: not w.ctl.fire_active, 3) and not w.laser._glow_on and not panel.laser.isChecked())
panel.dlg.redraw()
app.processEvents()
check("…e ridisegnando la spunta riparte spenta (il laser non si riaccende da solo)", panel.step == 1
      and not panel.laser.isChecked() and panel.laser.isEnabled() and not w.ctl.fire_active)
panel.cancel()
w.profile.homing = True
w.ctl.disconnect_port()
check("senza FLC_NO_DIALOGS la domanda dell'homing è un avviso con OK e Annulla (nelle prove risponde «no»)",
      nest_manual.NestAreaPanel.ask_homing(panel) is False)

# ================================================================== F. il nesting automatico resta com'era
parts = fresh(5)
auto = NestDialog(w)
auto.show()
app.processEvents()
check("nesting automatico: finestra a sé, con tutte le opzioni a vista e la spiegazione, come prima",
      auto.isWindow() and auto.manual is None and all(shown(x, auto) for x in (auto.area, auto.gap, auto.margin, auto.rot,
                                                                              auto.prec, auto.keep, auto.holes, auto.multi,
                                                                              auto.common))
      and not shown(auto.more_link, auto) and not shown(auto.nofit, auto) and not shown(auto.keep_area, auto)
      and auto.b_close.text() == nest_manual.tr("Chiudi") and auto.holes.text() != ""
      and any("sprecandone" in lab.text() and shown(lab, auto) for lab in auto.findChildren(type(auto.what))))
check("…e dispone come prima", auto.run() is not None and auto.b_close.text() == nest_manual.tr("Chiudi")
      and auto.b_run.text() == nest_manual.tr("Disponi"))
auto.accept()

# ================================================================== G. traduzioni
keys = set()
for name in ("nest_manual.py", "dialogs_nest.py"):
    src = open(os.path.join(ROOT, "freelasercut", "ui", name), encoding="utf-8").read()
    for m_ in re.finditer(r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', src):
        try:
            k = "".join(ast.literal_eval(part) for part in re.findall(r'"(?:[^"\\]|\\.)*"', m_.group(1)))
        except (SyntaxError, ValueError):
            continue
        if name == "nest_manual.py" or any(t in k for t in ("Ridisegna", "opzioni", "Disponi di nuovo", "Pezzi da sistemare")):
            keys.add(k)
check("testi della finestra del nesting manuale trovati nel codice", len(keys) >= 45
      and all(any(k.startswith(t) for k in keys) for t in ("Vedi istruzioni", "Altre opzioni", "Serve l'homing",
                                                           "Ridisegna l'area", "Cambia le opzioni")), len(keys))
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    miss = [k[:40] for k in keys if not loc.get(k)]
    bad = [k[:40] for k in keys if loc.get(k) and sorted(re.findall(r"\{\d", k)) != sorted(re.findall(r"\{\d", loc[k]))]
    tags = [k[:40] for k in keys if loc.get(k) and sorted(re.findall(r"</?b>|<br>", k)) != sorted(re.findall(r"</?b>|<br>", loc[k]))]
    check(f"traduzioni {lang}: tutti i testi, con gli stessi segnaposto e gli stessi grassetti", not miss and not bad
          and not tags, (miss[:3], bad[:3], tags[:3]))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
