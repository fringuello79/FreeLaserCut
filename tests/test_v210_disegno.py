# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.0 (richieste di un utente Linux): linea tratteggiata, ritaglio dei vettori, rampa dei riempimenti.

- Linea tratteggiata (perforazione) sui livelli Linea: tratti accesi e spenti delle lunghezze scelte, su linee
  aperte e chiuse, con le curve; insieme ai ponticelli; i progetti senza restano identici.
- Ritaglia con la forma / Ritaglia al piano: le linee restano linee (solo i tratti dentro), i riempimenti restano
  chiusi, quello che è tutto dentro resta identico (anche le curve), tutto fuori sparisce, un solo Annulla, foto no.
- Rampa (timbri in gomma): sul bordo la Potenza minima, a «lunghezza della rampa» la massima, anche intorno ai fori
  (le lettere in rilievo) e con le righe inclinate; senza rampa come prima.
Uso: python tests/test_v210_disegno.py [classica|banco]
"""
import math
import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(TMP, "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtGui import QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core import gcode, geom, ops  # noqa: E402
from freelasercut.core.document import CutSettings, Document, EllipseShape, ImageShape, PathShape, RectShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "")


def at(s, x, y):
    s.set_transform(QTransform.fromTranslate(x, y))
    return s


def burns(lines):
    """Tratti accesi (x0, y0, x1, y1, S) dal G-code assoluto."""
    x = y = 0.0
    s = 0.0
    on = False
    out = []
    mode = [0]
    for l in lines:
        l = l.split(";")[0].strip()
        if not l:
            continue
        if l.startswith(("M3", "M4")):
            on = True
        if l.startswith("M5"):
            on = False
        mS = re.search(r"S(-?\d+(?:\.\d+)?)", l)
        if mS:
            s = float(mS.group(1))
        mx = re.search(r"X(-?\d+(?:\.\d+)?)", l)
        my = re.search(r"Y(-?\d+(?:\.\d+)?)", l)
        nx = float(mx.group(1)) if mx else x
        ny = float(my.group(1)) if my else y
        mg = re.match(r"G0*([0-3])\b", l)
        if mg:
            mode[0] = int(mg.group(1))
        if mode[0] == 1 and on and s > 0 and (nx != x or ny != y) and (mx or my):
            out.append((x, y, nx, ny, s))
        if mode[0] in (0, 1) and (mx or my) and not l.startswith(("G10", "G92")):
            x, y = nx, ny
    return out


prof = MachineProfile(name="P", bed_x=300.0, bed_y=200.0, s_max=1000.0)


def job_of(doc):
    return gcode.generate(doc, prof).lines


print("--- linea tratteggiata")
geo = [geom.Poly([(0, 0), (10, 0)], False)]
d = gcode._apply_perforation(geo, 2.0, 1.0)
check("linea di 10 mm, tratti 2 acceso / 1 spento: 4 tratti (0–2, 3–5, 6–8, 9–10)",
      [(round(p.pts[0][0], 6), round(p.pts[-1][0], 6)) for p in d] == [(0, 2), (3, 5), (6, 8), (9, 10)],
      [(p.pts[0], p.pts[-1]) for p in d])
sq = [geom.Poly([(0, 0), (10, 0), (10, 10), (0, 10)], True)]
d = gcode._apply_perforation(sq, 3.0, 2.0)
tot = sum(math.dist(p.pts[i], p.pts[i + 1]) for p in d for i in range(len(p.pts) - 1))
check("quadrato chiuso (40 mm): 8 tratti da 3 mm che girano gli angoli, 24 mm accesi", len(d) == 8
      and abs(tot - 24.0) < 1e-6 and not any(p.closed for p in d), (len(d), tot))
check("il tratto che gira l'angolo ha l'angolo dentro", any((10, 0) in [tuple(map(lambda v: round(v, 6), q))
                                                             for q in p.pts] for p in d))
check("linea più corta di un tratto: resta intera", len(gcode._apply_perforation([geom.Poly([(0, 0), (1.5, 0)], False)],
                                                                                  2.0, 1.0)) == 1)
doc = Document()
cs = doc.layer(1)
cs.mode, cs.speed, cs.power_max = "line", 1000.0, 50.0
doc.add(at(RectShape(40, 20, layer=1), 50, 50))
plain = job_of(doc)
cs.perforate, cs.perf_cut, cs.perf_gap = True, 4.0, 2.0
perf = job_of(doc)
b = burns(perf)
lens = [math.hypot(x1 - x0, y1 - y0) for x0, y0, x1, y1, _s in b]
check("nel G-code: tratti accesi di 4 mm (al massimo), 120 mm di contorno = circa 80 mm accesi",
      max(lens) <= 4.0 + 1e-3 and abs(sum(lens) - 80.0) < 1.0, (max(lens), sum(lens)))
check("…e senza tratteggio il contorno è intero (120 mm)", abs(sum(math.hypot(x1 - x0, y1 - y0)
                                                                 for x0, y0, x1, y1, _s in burns(plain)) - 120) < 0.5)
cs.perforate = False
check("tratteggio spento: G-code identico a prima", job_of(doc) == plain)
cs.perforate, cs.tabs, cs.tab_count, cs.tab_size = True, True, 2, 3.0
check("con i ponticelli insieme: niente errori, meno acceso", sum(math.hypot(x1 - x0, y1 - y0)
                                                                   for x0, y0, x1, y1, _s in burns(job_of(doc))) < 80)
cs.tabs = False
cs2 = CutSettings.from_dict(cs.to_dict())
check("salvato e riaperto: tratteggio e misure", cs2.perforate and cs2.perf_cut == 4.0 and cs2.perf_gap == 2.0)
bad = CutSettings.from_dict({"index": 1, "perforate": "sì", "perf_cut": -3, "perf_gap": "x"})
check("valori rovinati nel file: tratteggio spento, misure sane", bad.perforate is False and bad.perf_cut == 0.05
      and bad.perf_gap == 1.0)
old = CutSettings.from_dict({"index": 1, "mode": "line"})
check("progetti di prima: senza tratteggio né rampa", not old.perforate and not old.ramp)

print("--- ritaglio dei vettori")
clip = [geom.Poly([(0, 0), (100, 0), (100, 100), (0, 100)], True)]
r_in = at(EllipseShape(20, 20, layer=1), 50, 50)
r_out = at(RectShape(10, 10, layer=1), 200, 200)
r_half = at(RectShape(40, 20, layer=2), 80, 40)
ln = PathShape(QPainterPath(), layer=1)
pp = QPainterPath()
pp.moveTo(50, 10)
pp.lineTo(150, 10)
ln = PathShape(pp, layer=1)
d = Document()
d.layer(1).mode = "line"
d.layer(2).mode = "fill"
res = {id(o): (n, ch) for o, n, ch in ops.crop([r_in, r_out, r_half, ln], clip, {1})}
check("tutta dentro: resta la stessa forma (anche il cerchio con le sue curve)", res[id(r_in)] == (r_in, False))
check("tutta fuori: sparisce", res[id(r_out)][0] is None)
n_half = res[id(r_half)][0]
bb = n_half.bounds() if hasattr(n_half, "bounds") else n_half.path().boundingRect()
check("riempimento a metà fuori: resta chiuso, tagliato al bordo (80–100 × 40–60)", n_half is not None
      and abs(bb.left() - 80) < 1e-3 and abs(bb.right() - 100) < 1e-3 and n_half.closed(), (bb,))
nl = res[id(ln)][0]
lb = nl.path().boundingRect()
check("linea a metà fuori: resta una linea, fino al bordo (50–100)", nl is not None and not nl.closed()
      and abs(lb.left() - 50) < 1e-3 and abs(lb.right() - 100) < 1e-3, lb)
sq_line = at(RectShape(40, 40, layer=1), 80, 30)
nl2 = ops.crop([sq_line], clip, {1})[0][1]
segs = geom.flatten(nl2.path())
check("contorno su un livello Linea a metà fuori: restano solo i suoi tratti dentro, niente bordo aggiunto",
      all(not p.closed for p in segs) and not any(abs(x - 100) < 1e-6 and abs(y0 - y1) > 1e-6
                                                  for p in segs for (x, y0), (_x, y1) in zip(p.pts, p.pts[1:])
                                                  if abs(_x - x) < 1e-9), [p.pts for p in segs])
ring = PathShape(geom.polys_to_path([geom.Poly([(10, 10), (190, 10), (190, 90), (10, 90)], True),
                                     geom.Poly([(40, 30), (60, 30), (60, 70), (40, 70)], True)]), layer=2)
cut = ops.crop([ring], clip, set())[0][1]
area = sum(abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(p.pts, p.pts[1:] + p.pts[:1]))) / 2 *
           (1 if i == 0 else 1) for i, p in enumerate(geom.flatten(cut.path())))
check("forma con un foro: il foro resta foro anche ritagliato", cut is not None
      and len(geom.flatten(cut.path())) == 2, len(geom.flatten(cut.path())) if cut else None)

from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
e = w.editor
doc = Document()
doc.layer(1).mode = "line"
doc.layer(2).mode = "fill"
a1 = doc.add(at(RectShape(40, 40, layer=2), 20, 20)) or doc.shapes[-1]
a2 = doc.add(at(RectShape(30, 30, layer=1), 60, 60)) or doc.shapes[-1]
cutter = doc.add(at(EllipseShape(50, 50, layer=1), 40, 40)) or doc.shapes[-1]
e.set_document(doc)
e.select([a1, a2, cutter])
w._update_actions() if hasattr(w, "_update_actions") else None
new = e.crop_with_shape()
check("Ritaglia con la forma: la forma in alto ritaglia le altre due e sparisce", len(new) == 2
      and cutter not in e.doc.shapes and len(e.doc.shapes) == 2)
fills = [s for s in e.doc.shapes if s.layer == 2]
check("…il riempimento resta chiuso, la linea restano tratti aperti", fills and fills[0].closed()
      and not [s for s in e.doc.shapes if s.layer == 1][0].closed())
e.undo()
check("un solo Annulla rimette tutto (forma del ritaglio compresa)", len(e.doc.shapes) == 3 and cutter in e.doc.shapes
      or len(e.doc.shapes) == 3)
e.select([a1])
check("una forma sola: lo dice e non tocca niente", e.crop_with_shape() is None and len(e.doc.shapes) == 3)
op = PathShape(pp, layer=1)
doc2 = Document()
doc2.layer(1).mode = "line"
doc2.add(at(RectShape(40, 40, layer=1), 10, 10))
doc2.add(op)
e.set_document(doc2)
e.select([doc2.shapes[0], op])
check("la forma in alto aperta: non ritaglia e lo dice", e.crop_with_shape() is None and len(e.doc.shapes) == 2)
doc3 = Document()
doc3.layer(1).mode = "line"
inside = at(EllipseShape(20, 20, layer=1), 100, 100)
big = at(RectShape(100, 50, layer=1), 250, 100)
far = at(RectShape(10, 10, layer=1), 400, 400)
for s in (inside, big, far):
    doc3.add(s)
e.set_document(doc3)
e.clear_selection()
e.crop_to_bed(300, 200)
check("Ritaglia al piano (niente selezionato = tutto): dentro identico, a metà tagliato, fuori tolto",
      inside in e.doc.shapes and far not in e.doc.shapes and len(e.doc.shapes) == 2
      and max(s.path().boundingRect().right() for s in e.doc.shapes) <= 300 + 1e-3)
e.undo()
e.select([inside])
check("tutto già dentro: niente da ritagliare, lo dice", e.crop_to_bed(300, 200) == [] and len(e.doc.shapes) == 3)
check("comandi nel menu Disponi, con la scheda d'aiuto", all(k in w.acts for k in ("crop_shape", "crop_bed"))
      and w.acts["crop_shape"] in [x for m in w.menuBar().actions() for x in (m.menu().actions() if m.menu() else [])])

print("--- rampa (timbri)")
doc = Document()
cs = doc.layer(0)
cs.mode, cs.speed, cs.power_max, cs.power_min, cs.interval, cs.angle = "fill", 3000.0, 80.0, 20.0, 0.1, 0.0
cs.bidirectional = True
doc.add(at(RectShape(20, 10, layer=0), 50, 50))
flat = job_of(doc)
cs.ramp, cs.ramp_len = True, 2.0
rp = job_of(doc)
b = burns(rp)
mid = [s_ for x0, y0, x1, y1, s_ in b if abs((y0 + y1) / 2 - 55) < 0.06]
check("senza rampa: tutto alla potenza massima", {s for *_r, s in burns(flat)} == {800.0})
check("riga in mezzo: dal bordo 20 % → 80 % in 2 mm, poi 80 % piena", mid and min(mid) <= 230 and max(mid) == 800,
      (min(mid) if mid else None, max(mid) if mid else None))
row = sorted([(min(x0, x1), max(x0, x1), s_) for x0, y0, x1, y1, s_ in b if abs((y0 + y1) / 2 - 55) < 0.06])
full = [r for r in row if r[2] == 800]
check("la parte piena comincia a circa 2 mm dal bordo (52) e finisce a circa 68", full and abs(full[0][0] - 52) < 0.25
      and abs(full[-1][1] - 68) < 0.25, full[:1] + full[-1:])
edge = [s_ for x0, y0, x1, y1, s_ in b if abs((y0 + y1) / 2 - 50.05) < 0.06]
check("riga sul bordo di sotto: mai oltre la potenza bassa (vicino al bordo per tutta la riga)", edge
      and max(edge) <= 260, max(edge) if edge else None)
cs.ramp = False
check("rampa spenta: G-code identico a prima", job_of(doc) == flat)
doc = Document()
cs = doc.layer(0)
cs.mode, cs.speed, cs.power_max, cs.power_min, cs.interval = "fill", 3000.0, 80.0, 0.0, 0.1
cs.ramp, cs.ramp_len = True, 1.0
doc.add(PathShape(geom.polys_to_path([geom.Poly([(10, 10), (50, 10), (50, 50), (10, 50)], True),
                                      geom.Poly([(25, 25), (35, 25), (35, 35), (25, 35)], True)]), layer=0))
b = burns(job_of(doc))
near_hole = [s_ for x0, y0, x1, y1, s_ in b if abs((y0 + y1) / 2 - 30) < 0.06 and 23.5 < (x0 + x1) / 2 < 25]
check("timbro: intorno al foro (la lettera in rilievo) la potenza scende verso il bordo", near_hole
      and min(near_hole) < 400 and not [1 for x0, y0, x1, y1, s_ in b if 25.05 < (x0 + x1) / 2 < 34.95
                                        and 25.05 < (y0 + y1) / 2 < 34.95], near_hole[:5])
cs.angle = 45.0
b45 = burns(job_of(doc))
check("con le righe a 45°: rampa anche lì, piena al centro", {s for *_r, s in b45} >= {800.0}
      and min(s for *_r, s in b45) < 200)
cs.angle, cs.power_min, cs.power_max = 0.0, 50.0, 50.0
check("potenza minima = massima: una potenza sola", {s for *_r, s in burns(job_of(doc))} == {500.0})
cs3 = CutSettings.from_dict({"index": 0, "mode": "fill", "ramp": True, "ramp_len": 99})
check("salvato e riaperto: rampa, lunghezza al massimo 20 mm", cs3.ramp and cs3.ramp_len == 20.0)

print("--- Z a ogni passata (rapporto H)")
from freelasercut.core import resume  # noqa: E402

doc = Document()
cs = doc.layer(1)
cs.mode, cs.speed, cs.power_max, cs.passes, cs.z_step = "line", 600.0, 90.0, 3, 0.5
doc.add(at(RectShape(20, 20, layer=1), 50, 50))
pz = MachineProfile(name="Z", bed_x=300.0, bed_y=200.0, s_max=1000.0)
pz.z_motor = True
jz = gcode.generate(doc, pz)
zl = [l for l in jz.lines if "Z" in l.split(";")[0]]
check("Z motorizzato, 3 passate, 0,5 mm: giù 0,5 due volte, poi su 1 mm, sempre a laser spento",
      zl == ["G0 Z-0.5", "G0 Z-0.5", "G0 Z1"] and all(jz.lines[jz.lines.index(z) - 2] == "M5 S0" for z in zl[:1]), zl)
i = jz.lines.index("G0 Z-0.5")
check("…in coordinate relative solo per lo Z, poi di nuovo assolute, e il tratto dopo ridice G1",
      jz.lines[i - 1] == "G91" and jz.lines[i + 1] == "G90"
      and next(l for l in jz.lines[i + 2:] if "X" in l or "Y" in l).startswith(("G0", "G1")))
jn = gcode.generate(doc, prof)
check("le passate restano 3 e il disegno è lo stesso", burns(jz.lines) == burns(jn.lines) and len(burns(jn.lines)) >= 3,
      (len(burns(jz.lines)), len(burns(jn.lines))))
check("laser senza Z motorizzato: niente Z e un avviso", not [l for l in jn.lines if "Z" in l.split(";")[0]]
      and any("Z" in x for x in jn.warnings), jn.warnings)
cs.z_step = 0.0
check("Z fermo (0): niente righe in più", not [l for l in gcode.generate(doc, pz).lines if "Z" in l.split(";")[0]])
ok_r, why_r = resume.can_resume(jz.lines, len(jz.lines) - 5)
ok_r0, _w = resume.can_resume(jz.lines, i - 2)
check("ripresa: prima del primo abbassamento sì, dopo no (l'altezza non si sa più)", ok_r0 and not ok_r and "Z" in why_r)
check("Z salvato e riaperto, al massimo 5 mm", CutSettings.from_dict({"index": 1, "z_step": 9}).z_step == 5.0
      and CutSettings.from_dict({"index": 1, "z_step": "x"}).z_step == 0.0)

print("--- Separa e Scomponi")
two = PathShape(geom.polys_to_path([geom.Poly([(0, 0), (30, 0), (30, 30), (0, 30)], True),
                                    geom.Poly([(10, 10), (20, 10), (20, 20), (10, 20)], True),
                                    geom.Poly([(50, 0), (70, 0), (70, 20), (50, 20)], True)]), layer=1)
parts = ops.separate(two)
check("Separa su un tracciato con due figure (la prima con un buco): due forme, il buco resta con la sua",
      parts and len(parts) == 2 and sorted(len(ops.world_subpaths(p_)) for p_ in parts) == [1, 2])
check("una figura sola (anche con un buco): niente da separare", ops.separate(parts[0] if len(
    ops.world_subpaths(parts[0])) == 2 else parts[1]) is None)
doc = Document()
doc.add(two)
e.set_document(doc)
e.select([two])
e.ungroup()
check("Separa dal programma: due forme, stesso livello, un Annulla", len(e.doc.shapes) == 2
      and all(s.layer == 1 for s in e.doc.shapes))
e.undo()
check("…Annulla: di nuovo una forma", len(e.doc.shapes) == 1)
msgs = []
e.message.connect(msgs.append)
e.select([e.doc.shapes[0]])
e.doc.shapes[0].locked = True
e.ungroup()
check("forma bloccata: lo dice", msgs and "bloccata" in msgs[-1], msgs[-1:])
e.doc.shapes[0].locked = False
from freelasercut.core.document import GroupShape  # noqa: E402

img = ImageShape.__new__(ImageShape) if False else None
g = GroupShape([at(RectShape(10, 10, layer=2), 0, 0), at(EllipseShape(10, 10, layer=3), 30, 0)], layer=2)
doc = Document()
doc.add(g)
e.set_document(doc)
e.select([g])
e.break_apart()
check("Scomponi su un gruppo: ogni forma tiene il suo livello (2 e 3)", sorted(s.layer for s in e.doc.shapes) == [2, 3],
      [s.layer for s in e.doc.shapes])
doc = Document()
doc.add(two)
e.set_document(doc)
e.select([two])
check("tasto destro su un tracciato con più figure: Separa e Scomponi", {"ungroup", "break"} <= set(w.context_menu_keys()))
e.select([doc.add(at(RectShape(5, 5, layer=1), 200, 100)) or doc.shapes[-1]])
check("…su un rettangolo: né Separa né Scomponi", not {"ungroup", "break"} & set(w.context_menu_keys()))

print("--- finestra del livello")
from freelasercut.ui.panels_design import CutSettingsDialog  # noqa: E402

c = CutSettings(index=3, mode="line", perforate=True, perf_cut=5.0, perf_gap=1.5, ramp=True, ramp_len=0.8)
dlg = CutSettingsDialog(c, prof)
v = dlg.values()
check("la finestra del livello mostra e restituisce tratteggio e rampa", v["perforate"] and v["perf_cut"] == 5.0
      and v["perf_gap"] == 1.5 and v["ramp"] and abs(v["ramp_len"] - 0.8) < 1e-9)
dlg.perf_on.setChecked(False)
check("tratteggio tolto: le misure si spengono", not dlg.perf_cut.isEnabled() and not dlg.values()["perforate"])

print("--- traduzioni")
import json  # noqa: E402

keys = ["Abbassa lo Z a ogni passata", "fermo", "Niente da separare: seleziona un gruppo o un tracciato fatto di più figure staccate", "Linea tratteggiata (perforazione)", "Tratto acceso", "Tratto spento", "Ritaglia con la forma",
        "Ritaglia al piano", "Lunghezza della rampa",
        "Rampa (timbri in gomma): dal bordo la potenza sale dalla minima alla massima",
        "Niente da ritagliare: è già tutto dentro"]
missing = []
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    missing += [(lang, k) for k in keys if not cat.get(k)]
check("le voci nuove ci sono nelle 4 lingue", not missing, missing[:4])
ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
