# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.19.0, due richieste di Ale.

D. Linguette dei piani di lavoro: la scritta del piano attivo («Piano 1») era troppo chiara. Causa: il tema del
   programma dà un colore a tutte le linguette e un foglio di stile vince sul colore dato alla singola linguetta; sul
   piano chiaro usciva una scritta chiara su bianco. Ora i colori sono scritti nel foglio di stile delle linguette:
   piano attivo scuro e in grassetto (bianco sul piano scuro), gli altri in un grigio leggibile ma diverso.
E. Doppio clic su uno strumento che disegna forme o linee = strumento bloccato: dopo ogni forma resta attivo, finché
   non si preme Esc o si sceglie un altro strumento. Con il clic singolo resta tutto com'è.

Casi D: piano chiaro e scuro; piano attivo e altri; si guarda il colore vero disegnato sullo schermo.
Casi E: un clic; due clic di fila; due clic lenti; strumenti che non si bloccano; più forme di seguito; Esc; un
altro strumento; lo stesso strumento cliccato ancora; la linea; il doppio clic vero sul pulsante; il cartellino.
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
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from freelasercut.ui import plates  # noqa: E402
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

# ================================================================== D. scritte delle linguette
bar = w.plate_bar
bar.new_plate()
bar.new_plate()
ed.set_plate(0)
app.processEvents()


def lum(c):
    return 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()


def ink(i, light):
    """Il colore della scritta della linguetta i com'è disegnata: il punto più scuro (piano chiaro) o più chiaro."""
    bar._style_key = None
    bar._restyle()
    bar.refresh()
    app.processEvents()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QImage, QPainter, QRegion
    from PySide6.QtWidgets import QWidget

    from freelasercut.ui.canvas import BED_DARK, BED_LIGHT

    img = QImage(bar.tabs.size(), QImage.Format_ARGB32)
    img.fill(QColor((BED_LIGHT if light else BED_DARK)["out"]))  # lo sfondo vero dietro le linguette (sono trasparenti)
    q = QPainter(img)
    bar.tabs.render(q, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    q.end()
    r = bar.tabs.tabRect(i).adjusted(6, 3, -6, -3)
    vals = [lum(img.pixelColor(x, y)) for x in range(r.left(), r.right()) for y in range(r.top(), r.bottom())]
    return min(vals) if light else max(vals)


for light in (True, False):
    cv.light_bed = light
    name = "chiaro" if light else "scuro"
    a, o1, o2 = ink(0, light), ink(1, light), ink(2, light)
    if light:
        check(f"piano {name}: la scritta del piano attivo è scura, ben leggibile sul bianco (prima era chiara)", a < 70, a)
        check(f"piano {name}: le scritte degli altri piani restano leggibili, ma di un colore diverso",
              o1 < 140 and o2 < 140 and o1 - a >= 30 and o2 - a >= 30, (a, o1, o2))
    else:
        check(f"piano {name}: la scritta del piano attivo è bianca piena", a > 235, a)
        check(f"piano {name}: le scritte degli altri piani restano leggibili, ma di un colore diverso",
              o1 > 140 and o2 > 140 and a - o1 >= 25 and a - o2 >= 25, (a, o1, o2))
    ed.set_plate(1)
    app.processEvents()
    a1, back0 = ink(1, light), ink(0, light)
    check(f"piano {name}: cambiando piano, la scritta forte passa alla linguetta nuova",
          (a1 < 70 and back0 - a1 >= 30) if light else (a1 > 235 and a1 - back0 >= 25), (a1, back0))
    ed.set_plate(0)
    app.processEvents()
css = bar.styleSheet()
cur, other = plates.TAB_TEXT[False]
check("i colori sono scritti nel foglio di stile delle linguette (lì il tema non li copre più), attivo e altri diversi",
      f"color: {other};" in css and f"color: {cur};" in css and cur != other and plates.TAB_TEXT[True][0] != plates.TAB_TEXT[True][1], css[:300])
cv.light_bed = True
bar._style_key = None
bar._restyle()

# ================================================================== E. doppio clic = strumento bloccato
locks = []
cv.tool_lock_changed.connect(locks.append)


def drag(a, b):
    """Disegna trascinando da a a b (mm sul piano)."""
    va, vb = cv.to_view(QPointF(*a)), cv.to_view(QPointF(*b))
    for kind, pt, btn, btns in ((QEvent.MouseButtonPress, va, Qt.LeftButton, Qt.LeftButton),
                                (QEvent.MouseMove, vb, Qt.NoButton, Qt.LeftButton),
                                (QEvent.MouseButtonRelease, vb, Qt.LeftButton, Qt.NoButton)):
        QApplication.sendEvent(vp, QMouseEvent(kind, pt, QPointF(vp.mapToGlobal(pt.toPoint())), btn, btns, Qt.AltModifier))
    app.processEvents()


def click(a):
    v = cv.to_view(QPointF(*a))
    for kind, btns in ((QEvent.MouseButtonPress, Qt.LeftButton), (QEvent.MouseButtonRelease, Qt.NoButton)):
        QApplication.sendEvent(vp, QMouseEvent(kind, v, QPointF(vp.mapToGlobal(v.toPoint())), Qt.LeftButton, btns, Qt.AltModifier))
    app.processEvents()


def key(k):
    QApplication.sendEvent(cv, QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))
    app.processEvents()


def slow():
    """Fa passare (per finta) più del tempo di un doppio clic dall'ultima scelta."""
    w._tool_pick = (w._tool_pick[0], w._tool_pick[1] - 5.0) + tuple(w._tool_pick[2:])


def n_shapes():
    return len(ed.doc.shapes)


n0 = n_shapes()
w._pick_tool("rect")
check("un clic su Rettangolo: lo strumento è attivo, non bloccato", cv.tool is cv.tools["rect"] and cv.tool_lock is None)
drag((50, 50), (90, 80))
check("…disegnato il rettangolo si torna a Selezione, come sempre", n_shapes() == n0 + 1 and cv.tool is cv.tools["select"])
slow()
w._pick_tool("rect")
w._pick_tool("rect")
check("due clic di fila su Rettangolo (doppio clic): lo strumento è bloccato, e la barra lo dice",
      cv.tool is cv.tools["rect"] and cv.tool_lock == "rect" and locks[-1:] == ["rect"]
      and "bloccato" in w.statusBar().currentMessage().lower(), (cv.tool_lock, w.statusBar().currentMessage()))
check("…e il pulsante dello strumento resta acceso", w.tool_actions["rect"].isChecked())
for k in range(3):
    drag((100 + 50 * k, 50), (130 + 50 * k, 80))
check("…tre rettangoli di seguito senza ricliccare lo strumento", n_shapes() == n0 + 4 and cv.tool is cv.tools["rect"]
      and cv.tool_lock == "rect", (n_shapes() - n0, cv.tool.name))
img = vp.grab().toImage()
cur_v = cv.to_view(cv.cursor_bed)
blue = sum(1 for x in range(int(cur_v.x()) + 14, int(cur_v.x()) + 60) for y in range(int(cur_v.y()) + 16, int(cur_v.y()) + 33)
           if 0 <= x < img.width() and 0 <= y < img.height() and img.pixelColor(x, y).blue() > 200 and img.pixelColor(x, y).red() < 120)
check("…accanto al cursore c'è il cartellino «bloccato · Esc per finire»", blue > 40, blue)
key(Qt.Key_Escape)
check("Esc: il blocco finisce e si torna a Selezione", cv.tool_lock is None and cv.tool is cv.tools["select"] and locks[-1] == "")
slow()
w._pick_tool("ellipse")
w._pick_tool("ellipse")
check("blocco su Ellisse…", cv.tool_lock == "ellipse")
slow()
w._pick_tool("ellipse")
check("…un altro clic sullo stesso strumento non lo sblocca", cv.tool_lock == "ellipse" and cv.tool is cv.tools["ellipse"])
slow()
w._pick_tool("rect")
check("…scegliere un altro strumento sì: Rettangolo attivo, niente più blocco", cv.tool_lock is None and cv.tool is cv.tools["rect"])
drag((50, 120), (80, 150))
check("…e disegnata una forma si torna a Selezione", cv.tool is cv.tools["select"])
slow()
w._pick_tool("star")
slow()
w._pick_tool("star")
check("due clic lenti (non un doppio clic) non bloccano", cv.tool_lock is None and cv.tool is cv.tools["star"])
slow()
w._pick_tool("rect")
drag((300, 50), (330, 80))
w._pick_tool("rect")
check("scegliere lo strumento, disegnare subito e risceglierlo non è un doppio clic (in mezzo c'è un disegno)",
      cv.tool_lock is None and cv.tool is cv.tools["rect"], cv.tool_lock)
slow()
w._pick_tool("rect")
w._pick_tool("ellipse")
check("due clic di fila su due strumenti diversi non bloccano niente (vale il secondo, senza blocco)",
      cv.tool_lock is None and cv.tool is cv.tools["ellipse"], cv.tool_lock)
for name in ("select", "nodes", "text", "measure", "trim", "position"):
    slow()
    w._pick_tool(name)
    w._pick_tool(name)
    check(f"«{name}» non è uno strumento che disegna forme: il doppio clic non blocca niente",
          cv.tool_lock is None and cv.tool is cv.tools[name], cv.tool_lock)
for name in ("line", "rect", "ellipse", "polygon", "star", "special"):
    slow()
    w._pick_tool(name)
    w._pick_tool(name)
    okl = cv.tool_lock == name
    key(Qt.Key_Escape)
    check(f"«{name}» si blocca con il doppio clic e si sblocca con Esc", okl and cv.tool_lock is None, cv.tool_lock)
# la linea
slow()
w._pick_tool("line")
w._pick_tool("line")
n1 = n_shapes()
for k in range(2):
    click((200, 150 + 30 * k))
    click((260, 160 + 30 * k))
    key(Qt.Key_Return)
check("linea bloccata: due linee di seguito (clic, clic, Invio) senza ricliccare lo strumento",
      n_shapes() == n1 + 2 and cv.tool is cv.tools["line"] and cv.tool_lock == "line", (n_shapes() - n1, cv.tool.name))
click((300, 150))
click((340, 170))
key(Qt.Key_Escape)
check("Esc a metà di una linea: la linea si chiude com'era, il blocco finisce, si torna a Selezione",
      cv.tool_lock is None and cv.tool is cv.tools["select"] and n_shapes() == n1 + 3, (n_shapes() - n1, cv.tool.name))
# il nesting manuale e gli altri comandi che cambiano strumento tolgono il blocco
slow()
w._pick_tool("rect")
w._pick_tool("rect")
cv.set_tool("select")
check("qualsiasi comando che cambia strumento toglie il blocco", cv.tool_lock is None)
# il doppio clic vero sul pulsante
btn = next((b for b in w.findChildren(QAbstractButton) if b.isVisible() and getattr(b, "defaultAction", lambda: None)()
            is w.tool_actions["rect"]), None)
if btn is not None:
    slow()
    QTest.mouseClick(btn, Qt.LeftButton)
    one = (cv.tool is cv.tools["rect"], cv.tool_lock)
    c = QPointF(btn.rect().center())  # il secondo clic di un doppio clic arriva al pulsante così
    for kind, btns in ((QEvent.MouseButtonDblClick, Qt.LeftButton), (QEvent.MouseButtonRelease, Qt.NoButton)):
        QApplication.sendEvent(btn, QMouseEvent(kind, c, QPointF(btn.mapToGlobal(c.toPoint())), Qt.LeftButton, btns, Qt.NoModifier))
    app.processEvents()
    check("pulsante vero dello strumento: un clic lo sceglie, il doppio clic lo blocca", one == (True, None) and cv.tool_lock == "rect",
          (one, cv.tool_lock))
    key(Qt.Key_Escape)
else:
    check("(pulsante dello strumento non trovato in questa interfaccia)", os.environ["FLC_UI"] != "classica")
for lang in ("en", "es", "fr", "pt"):
    with open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8") as fh:
        loc = json.load(fh)
    check(f"traduzioni {lang}: i due testi nuovi", loc.get("bloccato · Esc per finire") and any(
        k.startswith("Strumento bloccato: disegna quante forme vuoi") for k in loc))

w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
