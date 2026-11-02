# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.10.5: correzione della scansione avanti e indietro (tabella velocità → sfasamento nel profilo,
prova da incidere, finestra sotto Laser) e profilo pronto per l'Acmer S1 (130 × 130 mm)."""
import sys, os, time, tempfile, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ.setdefault("FLC_UI", "classica")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import machines
from freelasercut.core import gcode, scan_test
from freelasercut.core.document import Document, RectShape
from freelasercut.profile import MachineProfile

results = []
def check(name, cond, info=""):
    results.append(bool(cond)); print(("  OK  " if cond else "  KO  ") + name, info)

# ------------------------------------------------------------------ tabella del profilo
p = MachineProfile()
check("tabella vuota: nessuna correzione", p.scan_offsets == [] and p.scan_offset(6000) == 0.0)
p.scan_offsets = [[6000, 0.2]]
check("un solo valore: proporzionale alla velocità (il ritardo è un tempo)",
      abs(p.scan_offset(6000) - 0.2) < 1e-9 and abs(p.scan_offset(3000) - 0.1) < 1e-9 and abs(p.scan_offset(12000) - 0.4) < 1e-9)
p.scan_offsets = [[10000, 0.3], [2000, 0.05], ["x", 1], [0, 5]]
check("più valori: interpolazione lineare fra i punti, voci non valide ignorate",
      abs(p.scan_offset(6000) - 0.175) < 1e-9 and abs(p.scan_offset(1000) - 0.025) < 1e-9 and abs(p.scan_offset(20000) - 0.6) < 1e-9,
      f"{p.scan_offset(6000):.4f}")
path = p.save()
q = MachineProfile.load(path)
check("la tabella si salva e si rilegge con il profilo", q.scan_offsets == p.scan_offsets, q.scan_offsets)
old = {k: v for k, v in json.load(open(path, encoding="utf-8")).items() if k != "scan_offsets"}
json.dump(old, open(path, "w", encoding="utf-8"))
check("profili vecchi (senza tabella) si aprono come prima", MachineProfile.load(path).scan_offsets == [])

# ------------------------------------------------------------------ G-code
def job_for(prof, bidir=True, x=100.0, w=20.0, speed=6000.0):
    doc = Document()
    r = RectShape(w, 6)
    r.apply(QTransform.fromTranslate(x, 100))
    doc.add(r)
    cs = doc.layer(1)
    cs.mode, cs.interval, cs.overscan, cs.power_max, cs.speed, cs.bidirectional = "fill", 0.5, 3.0, 40, speed, bidir
    return gcode.generate(doc, prof, gcode.JobOptions(start_from="absolute"))

base = MachineProfile()
ref = job_for(base).lines
p0 = MachineProfile(); p0.scan_offsets = [[6000, 0.0]]
check("con sfasamento zero il G-code è identico, riga per riga", job_for(p0).lines == ref)
p2 = MachineProfile(); p2.scan_offsets = [[6000, 0.2]]
check("livello solo in andata (non bidirezionale): nessuna correzione", job_for(p2, bidir=False).lines == job_for(base, bidir=False).lines)
j2 = job_for(p2)
segs = j2.preview.segs
burn = segs[segs[:, 5] > 0]
fwd = burn[burn[:, 2] > burn[:, 0]]
rev = burn[burn[:, 2] < burn[:, 0]]
check("andata: ogni riga parte e finisce 0,1 mm prima (metà dello sfasamento)",
      len(fwd) and np.allclose(fwd[:, 0], 99.9, atol=1e-3) and np.allclose(fwd[:, 2], 119.9, atol=1e-3),
      f"{fwd[:1, [0, 2]].tolist()}")
check("ritorno: ogni riga si sposta di 0,1 mm dall'altra parte",
      len(rev) and np.allclose(rev[:, 0], 120.1, atol=1e-3) and np.allclose(rev[:, 2], 100.1, atol=1e-3),
      f"{rev[:1, [0, 2]].tolist()}")
check("la lunghezza incisa non cambia", np.allclose(np.abs(burn[:, 2] - burn[:, 0]), 20.0, atol=1e-3))
pf = MachineProfile(); pf.scan_offsets = [[3000, 0.1]]
jf = job_for(pf, speed=9000)
bf = jf.preview.segs[jf.preview.segs[:, 5] > 0]
check("la correzione segue la velocità del livello (9000 mm/min → 0,3 mm, 0,15 per lato)",
      np.allclose(bf[bf[:, 2] > bf[:, 0]][:, 0], 99.85, atol=1e-3))
je = job_for(p2, x=0.0, w=10.0)
me = je.preview.segs
check("sul bordo del piano la correzione non porta mai la testa fuori", me[:, [0, 2]].min() >= -1e-6 and not
      any("esce dall'area" in w for w in je.warnings), f"min x {me[:, [0, 2]].min():.3f}")

# ------------------------------------------------------------------ prova da incidere
spec = scan_test.ScanTestSpec(speeds=[3000, 6000, 10000], off_max=0.3, off_step=0.05)
check("correzioni provate: 0 … 0,30 a passi di 0,05", spec.offsets() == [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3], spec.offsets())
tj = scan_test.build(spec, MachineProfile())
check("prova: 3 velocità × 7 correzioni, dentro il piano", tj.layers[0].items == 21 and not tj.warnings and tj.lines,
      f"{tj.layers[0].items} {tj.warnings}")
S = tj.preview.segs
B = S[(S[:, 5] > 0) & (np.abs(S[:, 1] - S[:, 3]) < 1e-9)]
gx0, gy0, pitch = 20.0 + 12.0, 20.0 + 6.0, 7.0
ok_cols = []
for c, d in enumerate(spec.offsets()):
    x = gx0 + c * pitch
    row0 = B[(B[:, 1] >= gy0 - 0.01) & (B[:, 1] <= gy0 + 8.01) & (np.minimum(B[:, 0], B[:, 2]) > x - 1) & (np.maximum(B[:, 0], B[:, 2]) < x + 6)]
    f = row0[row0[:, 2] > row0[:, 0]]
    r = row0[row0[:, 2] < row0[:, 0]]
    ok_cols.append(len(f) and len(r) and np.allclose(f[:, 0], x - d / 2, atol=1e-3) and np.allclose(r[:, 2], x + d / 2, atol=1e-3))
check("prova: in ogni colonna andata e ritorno sono sfasati proprio della correzione scritta sotto", all(ok_cols), ok_cols)
check("prova: le etichette si incidono (25 %)", (S[S[:, 5] > 0][:, 4] == 250).any())
w_, h_ = scan_test.size(spec)
check("ingombro della prova (con etichette)", abs(w_ - (12 + 7 * 7 - 2)) < 1e-9 and abs(h_ - (6 + 3 * 10 - 2)) < 1e-9, (w_, h_))
acm = machines.preset_profile("Acmer S1 (2,5W / 3,5W / 6W)")
far = scan_test.build(scan_test.ScanTestSpec(x0=100, y0=100), acm)
check("prova fuori dal piano di un Acmer S1 (130 mm): avviso", far.warnings and "esce" in far.warnings[0])

# ------------------------------------------------------------------ Acmer S1
check("Acmer S1 nel catalogo dei modelli", "Acmer S1 (2,5W / 3,5W / 6W)" in machines.catalog_names())
check("Acmer S1: piano 130 × 130 mm, 10000 mm/min, spot 0,06 mm",
      (acm.bed_x, acm.bed_y, acm.max_rate_x, acm.spot_x_mm) == (130.0, 130.0, 10000.0, 0.06))
ident = machines.identify(banner=["Grbl 1.1h ['$' for help]"], info=["[VER:1.1h.20190825:ACMER S1]", "[OPT:V,15,128]"],
                          settings={130: "130.000", 131: "130.000", 30: "1000", 32: "1"})
check("scheda che si presenta come ACMER con corsa 130 × 130: riconosciuta come Acmer S1",
      ident.vendor == "Acmer" and "Acmer S1" in (ident.model or ""), f"{ident.vendor} / {ident.model}")

# ------------------------------------------------------------------ finestra
from freelasercut.ui.main_window import MainWindow
from freelasercut.ui import dialogs_scan
check("velocità scritte a mano", dialogs_scan.parse_speeds("3000, 6k;10000 abc 3000") == [3000.0, 6000.0, 10000.0])
w = MainWindow()
laser_menu = [m for m in w.menuBar().actions() if m.menu() and w.acts["material_test"] in m.menu().actions()][0].menu()
check("Laser → Correzione della scansione avanti e indietro, accanto al test materiale",
      w.acts["scan_offset"] in laser_menu.actions())
w.profile.scan_offsets = [[6000, 0.1], [20000, 0.37]]
d = w.scan_offset_dialog()
check("la finestra mostra la tabella del profilo", d.values() == [[6000.0, 0.1], [20000.0, 0.37]], d.values())
check("una scelta per ogni velocità della prova, già sul valore attuale", len(d.picks) == 3 and
      d.picks[1][1].currentData() == 0.1, [(s, cb.currentData()) for s, cb in d.picks])
d.picks[0][1].setCurrentIndex(2)  # 3000 → 0,05
d.picks[2][1].setCurrentIndex(5)  # 10000 → 0,2
d.use_picks()
check("«Usa questi valori»: la tabella si riempie e le altre righe restano", d.values() == [[3000.0, 0.05], [6000.0, 0.1], [10000.0, 0.2], [20000.0, 0.37]], d.values())
d.save()
saved = MachineProfile.load(w.profile.path())
check("«Salva nel profilo»: valori nel profilo attivo e nel file", w.profile.scan_offsets == d.values() and
      saved.scan_offsets == d.values(), saved.scan_offsets)
seen = []
w.preview_job = lambda job: seen.append(job)
d.b_prev.click()
check("Anteprima della prova dalla finestra principale", seen and seen[0].layers[0].items == 21)
check("la stessa finestra non si apre due volte", w.scan_offset_dialog() is d)
d.close()
app.processEvents()
w.editor.dirty = False
w.qs.setValue("autosave_pending", False)
w.close()
print(f"\n{sum(results)}/{len(results)} verifiche superate")
sys.exit(0 if all(results) else 1)
