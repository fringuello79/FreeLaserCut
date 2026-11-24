# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.6, dai rapporti del 24/11/2026 (scelte di Ale delle 09:14):

B (FLC-20261124-0851-DEB9) — anteprima di un lavoro molto grande (oltre gcode_preview.BIG movimenti, disegnata come
  immagine): «Mostra trasferimenti» non è più spenta. Di partenza resta tolta, una scritta discreta dice che può
  rallentare, e se la persona la accende i trasferimenti si vedono, seguendo il cursore del tempo.
C (FLC-20261123-1822-0573) — strumento Nodi: tasto destro su un nodo o su un tratto = i comandi che prima c'erano solo
  con le lettere (spezza, elimina, angolo, morbido, raccorda; inserisci, a metà, raddrizza, togli il tratto). Fanno
  esattamente quello che fa la lettera.

Uso: python tests/test_v226_rapporti.py [classica|banco]
"""
import copy
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

from freelasercut import gcode_preview  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402
from freelasercut.ui.dialogs import PreviewDialog  # noqa: E402

results = []
UI = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


win = mw.MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()

# ====================================================================== B. anteprima di un lavoro molto grande
print("--- B. trasferimenti nell'anteprima grande")


def big_job(n_rows):
    lines = ["G90 G21", "M4 S0"]
    for r in range(n_rows):  # riga per riga, con un trasferimento fra una e l'altra
        y = 10 + r * 0.1
        lines += [f"G0 X10 Y{y:.2f}", f"G1 X12 S500 F6000", "G1 X14 S0", f"G1 X16 S500", "G1 X18 S0"]
    return lines


lines_big = big_job(gcode_preview.BIG // 4 + 500)
pv = gcode_preview.parse(lines_big, profile=win.profile)
n_trav = sum(1 for s in pv.segs if not s[5])
check("B il lavoro di prova è oltre la soglia e ha trasferimenti", len(pv.segs) > gcode_preview.BIG and n_trav > 1000,
      (len(pv.segs), n_trav))


class FakeJob:
    lines = lines_big


dlg = PreviewDialog(pv, FakeJob(), win.profile, (win.profile.bed_x, win.profile.bed_y), None)
dlg.show()
app.processEvents()
check("B anteprima a immagine (come prima)", dlg._rast is not None)
check("B «Mostra trasferimenti» si può usare, di partenza tolta", dlg.travel.isEnabled() and not dlg.travel.isChecked())
check("B scritta discreta accanto: può rallentare", dlg.travel_note.isVisible()
      and "rallent" in dlg.travel_note.text() and "rallent" in dlg.travel.toolTip(), dlg.travel_note.text())
check("B finché non si accende, nessun trasferimento costruito (niente lavoro per il PC)", not dlg._rast_travel)
dlg.travel.setChecked(True)
app.processEvents()
vis = [it for _k, it in dlg._rast_travel if it.isVisible()]
check("B accesa: i trasferimenti ci sono e si vedono tutti a cursore in fondo", dlg._rast_travel and len(vis) == len(dlg._rast_travel),
      (len(dlg._rast_travel), len(vis)))
tot = sum(it.path().elementCount() for _k, it in dlg._rast_travel)
check("B ci sono proprio i trasferimenti del lavoro (uno per riga)", tot >= n_trav, (tot, n_trav))
half = dlg.slider.maximum() // 2
dlg.slider.setValue(half)
app.processEvents()
vis_half = [k for k, it in dlg._rast_travel if it.isVisible()]
check("B il cursore del tempo a metà: solo i trasferimenti fino a lì", vis_half and max(vis_half) < half
      and len(vis_half) < len(dlg._rast_travel), (len(vis_half), len(dlg._rast_travel)))
dlg.travel.setChecked(False)
app.processEvents()
check("B spenta di nuovo: spariscono", not any(it.isVisible() for _k, it in dlg._rast_travel))
dlg.r_real.setChecked(True)
dlg.travel.setChecked(True)
app.processEvents()
check("B resa realistica: niente trasferimenti sopra", not any(it.isVisible() for _k, it in dlg._rast_travel))
dlg.close()
small = big_job(40)
pv_s = gcode_preview.parse(small, profile=win.profile)
d2 = PreviewDialog(pv_s, FakeJob(), win.profile, (win.profile.bed_x, win.profile.bed_y), None)
check("B lavoro piccolo: come prima (spunta accesa, nessuna scritta, nessun blocco a immagine)",
      d2._rast is None and d2.travel.isChecked() and d2.travel.isEnabled() and not d2.travel_note.isVisible()
      and not d2._rast_travel and d2.travel_items)
d2.close()

# ====================================================================== C. tasto destro nello strumento Nodi
print("--- C. tasto destro nei Nodi")
ed, cv = win.editor, win.canvas
r = RectShape(40, 30, layer=1)
r.apply(QTransform.fromTranslate(50, 50))
ed.add([r], "prova")
ed.select([r])
cv.set_tool("nodes")
app.processEvents()
nt = cv.tools["nodes"]
check("C strumento Nodi attivo, con i nodi del rettangolo", cv.tool is nt and nt.items)


def node_view_pt(k=0, si=0, ni=0):
    tf = cv.bed_to_view_tf()
    return tf.map(QPointF(*nt.items[k].subs[si].nodes[ni].pt()))


def seg_view_pt(k=0, si=0):
    sp = nt.items[k].subs[si]
    a, b = sp.nodes[0].pt(), sp.nodes[1].pt()
    tf = cv.bed_to_view_tf()
    return tf.map(QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))


if UI == "banco":
    title, items = win.banco.radial_items(node_view_pt(0, 0, 1))
    check("C Banco, tasto destro su un nodo: il menu radiale ha i comandi del nodo",
          [a for _l, a in items][:5] == [win.acts[k] for k in ("node_break", "node_delete", "node_corner", "node_smooth",
                                                               "node_fillet")] and nt.sel == [(0, 0, 1)], (title, nt.sel))
    title, items = win.banco.radial_items(seg_view_pt())
    check("C Banco, tasto destro su un tratto: i comandi del tratto",
          [a for _l, a in items] == [win.acts[k] for k in ("node_insert", "node_mid", "node_straight", "node_cut_seg")]
          and nt.sel == [], title)
    title, items = win.banco.radial_items(QPointF(3, 3))
    check("C Banco, tasto destro nel vuoto: il menu di sempre", win.acts["node_break"] not in [a for _l, a in items])
    # il comando vale per il tratto del clic destro anche se intanto il mouse è passato sopra il menu
    win.banco.radial_items(seg_view_pt())
    n0 = len(nt.items[0].subs[0].nodes)
    nt.hover = nt.hover_seg = None  # come dopo un movimento del mouse lontano dal tratto
    win.acts["node_mid"].trigger()
    app.processEvents()
    check("C Banco, «Nodo a metà» dal menu: vale per il tratto del clic destro anche se il mouse si è spostato",
          len(nt.items[0].subs[0].nodes) == n0 + 1, (n0, len(nt.items[0].subs[0].nodes)))
    ed.undo()
    app.processEvents()
    nt._load()
if UI == "classica":
    keys = win.context_menu_keys(node_view_pt(0, 0, 1))
    check("C clic destro su un nodo: spezza, elimina, angolo, morbido, raccorda", all(
        k in keys for k in ("node_break", "node_delete", "node_corner", "node_smooth", "node_fillet"))
        and "node_insert" not in keys, keys)
    check("C …e il nodo cliccato diventa quello scelto", nt.sel == [(0, 0, 1)], nt.sel)
    keys = win.context_menu_keys(seg_view_pt())
    check("C clic destro su un tratto: inserisci, a metà, raddrizza, togli il tratto", all(
        k in keys for k in ("node_insert", "node_mid", "node_straight", "node_cut_seg")) and "node_break" not in keys,
        keys)
    keys = win.context_menu_keys(QPointF(3, 3))
    check("C clic destro nel vuoto: solo le voci di sempre", "node_break" not in keys and "node_insert" not in keys
          and "node_join" in keys, keys)
    m = win.open_context_menu(node_view_pt(0, 0, 2), cv.mapToGlobal(node_view_pt(0, 0, 2).toPoint()))
    texts = [a.text() for a in m.actions()]
    check("C il menu vero mostra «Spezza qui» con la lettera B", any(t.startswith("Spezza qui") and t.endswith("B")
                                                                      for t in texts), texts[:6])
    m.close()

# stessa strada della lettera: confronto con il tasto B su una copia identica
before = copy.deepcopy([[(n.pt(), n.cin, n.cout) for n in sp.nodes] for sp in nt.items[0].subs])
nt.context_target(node_view_pt(0, 0, 1))
closed0 = nt.items[0].subs[0].closed
ok = win._node_cmd(Qt.Key_B)
app.processEvents()
sub_after = nt.items[0].subs
check("C «Spezza qui»: il rettangolo chiuso diventa un tracciato aperto, nodi al loro posto", ok and closed0
      and not sub_after[0].closed, [s.closed for s in sub_after])
check("C …e resta aperto (prima il programma lo richiudeva subito: «non taglia»)", not nt.items[0].subs[0].closed
      and len(nt.items[0].subs[0].nodes) == len(before[0]) + 1)
nt.context_target(node_view_pt(0, 0, 2))
win._node_cmd(Qt.Key_B)
app.processEvents()
check("C un secondo «Spezza» su un altro nodo: due pezzi (poi «Separa» li divide in oggetti)",
      len(nt.items[0].subs) == 2 and not any(sp.closed for sp in nt.items[0].subs), [len(sp.nodes) for sp in nt.items[0].subs])
cv.set_tool("select")
cv.set_tool("nodes")
app.processEvents()
check("C …anche uscendo e rientrando nello strumento restano due pezzi aperti", len(nt.items[0].subs) == 2
      and not any(sp.closed for sp in nt.items[0].subs))
ed.undo()
ed.undo()
app.processEvents()
nt._load()
check("C Annulla: tutto come prima", [[(n.pt(), n.cin, n.cout) for n in sp.nodes] for sp in nt.items[0].subs] == before)
nt.context_target(seg_view_pt())
n0 = len(nt.items[0].subs[0].nodes)
win._node_cmd(Qt.Key_M)
app.processEvents()
check("C «Nodo a metà del tratto»: un nodo in più", len(nt.items[0].subs[0].nodes) == n0 + 1,
      (n0, len(nt.items[0].subs[0].nodes)))
ed.undo()
nt._load()
nt.context_target(node_view_pt(0, 0, 0))
n0 = len(nt.items[0].subs[0].nodes)
win._node_cmd(Qt.Key_D)
check("C «Elimina nodo»: un nodo in meno", len(nt.items[0].subs[0].nodes) == n0 - 1)
ed.undo()
nt._load()
nt.context_target(node_view_pt(0, 0, 2))  # prima un nodo scelto…
nt.context_target(seg_view_pt())  # …poi clic destro su un tratto e «Togli il tratto»
n0 = len(nt.items[0].subs[0].nodes)
win._node_cmd(Qt.Key_D)
app.processEvents()
check("C «Togli il tratto» con un nodo scelto prima: toglie il tratto, non il nodo",
      len(nt.items[0].subs[0].nodes) == n0 and not nt.items[0].subs[0].closed,
      (n0, len(nt.items[0].subs[0].nodes), nt.items[0].subs[0].closed))
ed.undo()
cv.set_tool("select")
check("C fuori dallo strumento Nodi il comando non fa niente e lo dice", win._node_cmd(Qt.Key_B) is False
      and "Nodi" in win.statusBar().currentMessage())
ed.dirty = False
win.close()
print(f"\n{sum(results)}/{len(results)} prove superate")
sys.exit(0 if all(results) else 1)
