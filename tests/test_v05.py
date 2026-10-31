# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""FreeLaserCut 0.5: barra numerica, livelli modificabili in tabella (e crash della spunta Inc.), guida "?",
riconoscimento della macchina, anteprima adattata e zoomabile."""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["APPDATA"] = tempfile.mkdtemp()
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox, QStyleOptionViewItem  # noqa: E402

from freelasercut.theme import QSS  # noqa: E402
from freelasercut.ui import style  # noqa: E402

app = QApplication([])
app.setStyle("Fusion")
style.load_fonts()
app.setStyleSheet(QSS + style.QSS_EXTRA)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import machines  # noqa: E402
from freelasercut.core.document import RectShape  # noqa: E402
from freelasercut.sim import SimSerial  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

R = []


def check(n, ok, info=""):
    R.append(bool(ok))
    print(("  OK  " if ok else "  KO  ") + n, info)


def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.005)


w = MainWindow()
w.resize(1600, 980)
w.show()
ed = w.editor
spin(0.6)
r = RectShape(40, 30, layer=1)
ed.add(r)
r2 = RectShape(20, 20, layer=2)
ed.add(r2)
spin()

# ---------------------------------------------------------------- crash spunta "Inc."
lp = w.layers
it = lp.tree.topLevelItem(0)
idx = it.data(0, Qt.UserRole)
for k in range(6):  # togli e rimetti la spunta più volte, come col mouse
    it = lp.tree.topLevelItem(0)
    it.setCheckState(5, Qt.Unchecked if k % 2 == 0 else Qt.Checked)
    spin(0.05)
check("spunta Inc. tolta e rimessa 6 volte senza crash", ed.doc.layers[idx].output is True)
it = lp.tree.topLevelItem(0)
it.setCheckState(5, Qt.Unchecked)
spin()
check("spunta Inc. tolta: livello non inciso, annullabile", ed.doc.layers[idx].output is False and "Incidi" in ed.undo_label())
ed.undo()
spin()
check("annulla riporta Inc.", ed.doc.layers[idx].output is True)

# ---------------------------------------------------------------- modifica in linea
lp._apply(idx, {"name": "Taglio 3 mm"})
spin()
check("rinomina dal pannello", ed.doc.layers[idx].name == "Taglio 3 mm" and lp.tree.topLevelItem(0).text(0) == "Taglio 3 mm")
it = lp.tree.topLevelItem(0)
mi = lp.tree.indexFromItem(it, 2)
deleg = lp.tree.itemDelegate()
ed_w = deleg.createEditor(lp.tree.viewport(), QStyleOptionViewItem(), mi)
ok_editor = ed_w is not None and hasattr(ed_w, "setValue")
if ok_editor:
    deleg.setEditorData(ed_w, mi)
    ed_w.setValue(4321)
    deleg.setModelData(ed_w, lp.tree.model(), mi)
    spin(0.1)
check("velocità modificata direttamente nella tabella", ok_editor and abs(ed.doc.layers[idx].speed - 4321) < 1e-6,
      f"{ed.doc.layers[idx].speed:g}")
lp._apply(idx, {"mode": "fill", "power_max": 37.5, "passes": 3})
spin()
cs = ed.doc.layers[idx]
check("modalità, potenza e passate dal pannello", (cs.mode, cs.power_max, cs.passes) == ("fill", 37.5, 3))
lp._solo(idx)
spin()
others = [c for c in ed.doc.used_layers() if c.index != idx and c.index != 30]
check("incidi solo questo livello", cs.output and others and not any(c.output for c in others))

# ---------------------------------------------------------------- barra numerica
nb = w.numeric
ed.select([r])
spin()
check("barra numerica: unità mm nei campi", nb.fw.text().endswith(" mm") and nb.fx.text().endswith(" mm"), nb.fw.text())
check("barra numerica: campi bassi e lucchetto piccolo", nb.fw.height() <= 20 and nb.lock.width() <= 20,
      f"campo {nb.fw.height()} px, lucchetto {nb.lock.width()} px")
nb.fw.setText("80")
nb.fw._commit()
spin()
check("larghezza scritta con il suffisso mm", abs(ed.selection_bounds().width() - 80) < 0.01)
i5 = nb.layer_combo.findData(5)
nb.layer_combo.setCurrentIndex(i5)
nb._layer_picked(i5)
spin()
check("livello cambiato dalla barra numerica", ed.selection[0].layer == 5)
nb._center_on_bed()
spin()
b = ed.selection_bounds()
check("centra sul piano", abs(b.center().x() - w.profile.bed_x / 2) < 0.01 and abs(b.center().y() - w.profile.bed_y / 2) < 0.01)

# ---------------------------------------------------------------- guida "?"
hm = w.help
w.acts["help_mode"].setChecked(True)
spin()
check("guida attiva dal pulsante ?", hm.active)
d = hm._action(w.acts["frame"])
check("descrizione di un comando con opzioni", d[0] == "Contorno" and len(d[2]) == 3 and d[3], d[3])
d = hm._widget(nb.fw, nb.fw.property("help_key"))
check("descrizione di un campo della barra", d[0].startswith("Larghezza") and d[4].endswith("mm"))
combo = QComboBox()
combo.addItems(["Uno", "Due", "Tre"])
combo.setItemData(1, "seconda voce", Qt.ToolTipRole)
d = hm._widget(combo, None)
check("tendina: elenco delle opzioni", [o[0] for o in d[2]] == ["Uno", "Due", "Tre"] and d[2][1][1] == "seconda voce")
hv = lp.tree.header()
x = hv.sectionViewportPosition(5) + 4
d = hm._header(hv, hv.mapToGlobal(QPoint(x, 4)))
check("colonna Inc. descritta", d is not None and d[0] == "Incidi", d[0] if d else "")
spin()
before = ed.doc.layers[idx].output
vp = lp.tree.viewport()
r0 = lp.tree.visualRect(lp.tree.indexFromItem(lp.tree.topLevelItem(0), 5))
pt = QPointF(r0.center())
consumed = hm.eventFilter(vp, QMouseEvent(QEvent.MouseButtonPress, pt, QPointF(vp.mapToGlobal(r0.center())),
                                          Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
spin()
check("in modalità guida i clic non eseguono", consumed and ed.doc.layers[idx].output == before)
hm.set_active(False)
spin()
check("guida spenta, azione sincronizzata", not w.acts["help_mode"].isChecked())
missing = [k for k in w.acts if help_texts.lookup(k) is None]
check("ogni comando ha la sua scheda", not missing, str(missing))
check("ogni strumento ha la sua scheda", all(help_texts.lookup(f"tool:{n}") for n in w.tool_actions))

# ---------------------------------------------------------------- riconoscimento macchina
res = machines.probe("SIM", bauds=(115200,), opener=lambda p, b: SimSerial(), settle=0.3)
ident = machines.identify(res["banner"], res["info"], res["settings"], None, res["baud"])
check("sonda sul simulatore: Longer B1 riconosciuto", ident.model == "Longer B1 40W" and ident.confidence == "alta",
      ident.summary())
p = machines.build_profile(ident, res["settings"], res["info"], "Laser di prova")
check("profilo costruito dalla scheda", p.name == "Laser di prova" and p.rx_buffer == 256 and p.vendor_fw.startswith("LGT"))
p.save()
w.set_active_profile(p)
spin()
check("profilo attivo ricordato", w.qs.value("profile_path") == p.path() and w.profile.name == "Laser di prova")
from freelasercut.ui.dialogs_machine import MachineWizard  # noqa: E402

wz = MachineWizard(w)
sim_row = wz.table.rowCount() - 1
wz.table.selectRow(sim_row)
wz.run_probe()
t_end = time.time() + 20
while wz.ident is None and time.time() < t_end:
    spin(0.1)
check("procedura guidata: riconosce il simulatore", wz.ident is not None and wz.name.text() == "Longer B1 40W",
      wz.name.text())
wz.close()

# ---------------------------------------------------------------- anteprima
from freelasercut import gcode_preview  # noqa: E402
from freelasercut.ui.dialogs import PreviewDialog  # noqa: E402

lines = ["G21 G90", "M4", "G0 X100 Y100", "G1 X160 Y100 S500 F1200", "G1 X160 Y140", "G1 X100 Y140", "M5"]
pv = gcode_preview.parse(lines)
dlg = PreviewDialog(pv, None, w.profile, (w.profile.bed_x, w.profile.bed_y), w)
dlg.show()
spin(0.3)
scr = w.screen().availableGeometry()
check("anteprima grande quanto lo schermo", dlg.width() >= scr.width() * 0.85, f"{dlg.width()}×{dlg.height()}")
vr = dlg.view.mapToScene(dlg.view.viewport().rect()).boundingRect()
check("anteprima adattata al lavoro", vr.width() < 200 and vr.contains(dlg.view.fit_rect.center()), f"{vr.width():.0f} mm visibili")
s0 = dlg.view.transform().m11()
dlg.view.zoom(1.5)
check("zoom con la rotella", abs(dlg.view.transform().m11() / s0 - 1.5) < 0.01 and not dlg.view.auto_fit)
vp_pt = QPoint(dlg.view.viewport().width() // 4, dlg.view.viewport().height() // 4)
p_before = dlg.view.mapToScene(vp_pt)
dlg.view.zoom(1.6, vp_pt)
p_after = dlg.view.mapToScene(vp_pt)
check("lo zoom resta sotto il cursore", abs(p_before.x() - p_after.x()) < 1.0 and abs(p_before.y() - p_after.y()) < 1.0,
      f"spostamento {abs(p_before.x() - p_after.x()):.2f}, {abs(p_before.y() - p_after.y()):.2f} mm")
dlg.view.fit()
check("adatta di nuovo", abs(dlg.view.transform().m11() - s0) < 1e-6)
dlg.close()

print(f"\n{sum(R)}/{len(R)} superati")
sys.exit(0 if all(R) else 1)
