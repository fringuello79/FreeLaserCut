# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.7: SVG con contorno e riempimento, riempimenti in toni di grigio (richiesta di France_o, 18/11/2026:
«con MeerK40t ogni figura di Inkscape ha contorno e riempimento con un nero diverso, e il laser cambia potenza»).

A  importazione SVG: una figura chiusa con contorno e riempimento grigio diventa due forme (il contorno sul livello
   del suo colore, il riempimento su C00 con il suo grigio); trasparenze che schiariscono; linee aperte, riempimenti
   colorati, colori dei livelli e loghi tutti neri come prima; «Potenza dal grigio» accesa su C00 solo se serve e
   solo se C00 è in Riempimento;
B  G-code: ogni tono con la sua potenza (nero = massima, bianco = non si incide, in mezzo in proporzione con la
   minima), dove le forme si coprono conta quella sopra, i fori restano vuoti; senza l'opzione o senza grigi il
   G-code è identico a prima;
C  salvataggio: grigio della forma e opzione del livello restano; valori rovinati ignorati;
D  interfaccia: la casella nelle impostazioni del livello; l'anteprima riempita mostra i toni;
T  testi nuovi tradotti in tutte le lingue.
Uso: python tests/test_v207_svg_grigi.py [classica|banco]
"""
import json
import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core import gcode, io_formats  # noqa: E402
from freelasercut.core.document import CutSettings, Document, RectShape, gray_power, shape_from_dict  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402

UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "")


def svg(body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
            + body + "</svg>").encode()


def imp(body, doc=None):
    doc = doc or Document()
    shapes = io_formats.import_svg(svg(body), doc)
    leaves = [l for s in shapes for l, _ in s.leaves()]
    return doc, shapes, leaves


def area(polys):
    """Area della zona (i contorni di Clipper hanno i fori nel verso opposto: l'area con il segno li toglie)."""
    return abs(sum(p.area() for p in polys))


print("--- A. importazione")
doc, _s, lv = imp('<rect x="10" y="10" width="30" height="30" fill="#808080" stroke="#E5484D" stroke-width="0.5"/>')
check("contorno rosso + riempimento grigio: due forme", len(lv) == 2, [(l.layer, l.gray) for l in lv])
check("…il contorno sul livello rosso (C02), senza grigio", lv[0].layer == 2 and lv[0].gray is None)
check("…il riempimento su C00 con il suo grigio (128)", lv[1].layer == 0 and lv[1].gray == 128)
check("…stessa sagoma", abs(lv[0].bounds().width() - lv[1].bounds().width()) < 1e-6)
check("…e su C00 si accende «Potenza dal grigio»", doc.layer(0).gray_power is True)

_d, _s, lv = imp('<rect x="10" y="10" width="30" height="30" fill="#404040" stroke="#000" stroke-width="0.5"/>')
check("contorno nero + riempimento grigio: il contorno va su C01 (Linea), non sul livello del riempimento",
      [(l.layer, l.gray) for l in lv] == [(1, None), (0, 64)], [(l.layer, l.gray) for l in lv])

d0, _s, lv = imp('<rect x="10" y="10" width="30" height="30" fill="#000" stroke="#000" stroke-width="0.5"/>')
check("logo tutto nero (contorno e riempimento neri): una forma sola su C00, come prima",
      [(l.layer, l.gray) for l in lv] == [(0, None)], [(l.layer, l.gray) for l in lv])
check("…e C00 resta com'era", d0.layer(0).gray_power is False)

_d, _s, lv = imp('<rect x="10" y="10" width="30" height="30" fill="#ff0000" stroke="#2E7CF6"/>')
check("riempimento colorato: come prima, una forma sul colore del contorno", [(l.layer, l.gray) for l in lv] == [(1, None)])

_d, _s, lv = imp('<rect x="10" y="10" width="30" height="30" fill="#7C8A99"/><rect x="50" y="10" width="9" height="9" '
                 'fill="#495057"/>')
check("riempimento con il colore esatto di un livello (SVG di FreeLaserCut o LightBurn): come prima",
      [(l.layer, l.gray) for l in lv] == [(9, None), (29, None)], [(l.layer, l.gray) for l in lv])

_d, _s, lv = imp('<path d="M0 90 L10 100" stroke="#E5484D"/>')
check("linea aperta (riempimento nero di partenza dell'SVG): una linea sola, nessun grigio",
      [(l.layer, l.gray) for l in lv] == [(2, None)])

_d, _s, lv = imp('<rect x="10" y="10" width="30" height="30" fill="#000" fill-opacity="0.5"/>'
                 '<g opacity="0.5"><rect x="50" y="10" width="9" height="9" fill="#000"/></g>')
check("trasparenza del riempimento e del gruppo: nero al 50% = grigio 127-128", all(127 <= l.gray <= 128 for l in lv),
      [l.gray for l in lv])

dd = Document()
dd.layer(0).mode = "line"
imp('<rect x="10" y="10" width="30" height="30" fill="#808080"/>', dd)
check("C00 messo in Linea dall'utente: la scelta non si tocca", dd.layer(0).gray_power is False and dd.layer(0).mode == "line")

d1, _s, lv = imp('<rect x="10" y="10" width="30" height="30" fill="#000"/>')
check("solo nero pieno: C00 senza «Potenza dal grigio» (si incide come sempre)", d1.layer(0).gray_power is False
      and lv[0].layer == 0)
d2, _s, lv = imp('<rect x="10" y="10" width="30" height="30" fill="#fff" stroke="#E5484D"/>')
check("riempimento bianco: l'opzione si accende, così il bianco non si incide a piena potenza",
      d2.layer(0).gray_power is True and gray_power(d2.layer(0), lv[1].gray) == 0.0)

print("--- B. G-code")
cs = CutSettings(index=0, mode="fill", power_max=40.0, power_min=10.0, gray_power=True)
check("potenza: nero = massima, bianco = 0, grigio in proporzione fra minima e massima",
      gray_power(cs, 0) == 40.0 and gray_power(cs, 255) == 0.0 and abs(gray_power(cs, 127.5) - 25.0) < 1e-9
      and gray_power(cs, None) == 40.0)

body = ('<rect x="10" y="10" width="30" height="30" fill="#808080"/>'   # grande, grigio, sotto
        '<rect x="20" y="20" width="10" height="10" fill="#000"/>'       # piccolo, nero, sopra
        '<rect x="50" y="10" width="30" height="30" fill="#404040"/>'
        '<path d="M60 60 h20 v20 h-20 z M65 65 h10 v10 h-10 z" fill="#c0c0c0" fill-rule="evenodd"/>')  # con foro
doc, shapes, lv = imp(body)
doc.shapes.extend(shapes)
cs0 = doc.layer(0)
cs0.power_max, cs0.power_min = 40.0, 10.0
items = [(l, t) for s in doc.shapes for l, t in s.leaves()]
groups = dict(gcode._gray_fill_groups(items, cs0))
pw = {g: round(gray_power(cs0, g), 2) for g in (0, 128, 64, 192)}
check("quattro toni, quattro potenze", sorted(groups) == sorted(pw.values()), (sorted(groups), pw))
check("il quadrato nero sopra brucia pieno (100 mm²)", abs(area(groups[pw[0]]) - 100) < 0.5, area(groups[pw[0]]))
check("…e copre il grigio sotto: il grigio brucia solo la cornice (900 − 100 mm²)",
      abs(area(groups[pw[128]]) - 800) < 0.5, area(groups[pw[128]]))
check("il foro della forma resta vuoto (400 − 100 mm²)", abs(area(groups[pw[192]]) - 300) < 0.5, area(groups[pw[192]]))

prof = MachineProfile()
job = gcode.generate(doc, prof)
svals = {round(float(v) / prof.s_max * 100, 2) for v in re.findall(r"\bS(\d+(?:\.\d+)?)", "\n".join(job.lines))}
check("nel G-code ci sono proprio quelle potenze", set(pw.values()) <= svals, (sorted(svals), pw))
st = next(s for s in job.layers if s.index == 0)
check("le statistiche del livello dicono 4 toni", st.tones == 4, st.tones)

# senza l'opzione: identico a un documento senza grigi
def lines_of(doc_):
    return [l for l in gcode.generate(doc_, prof).lines if not l.startswith(";")]


cs0.gray_power = False
off = lines_of(doc)
plain = Document()
plain.layers[0] = CutSettings.from_dict(cs0.to_dict())
for s in shapes:
    c = s.clone(new_id=False)
    for leaf, _t in c.leaves():
        leaf.gray = None
    plain.shapes.append(c)
check("opzione spenta: G-code identico a quello delle stesse forme senza grigio", off == lines_of(plain))
cs0.gray_power = True
plain.layers[0].gray_power = True
check("opzione accesa ma nessuna forma con un grigio: G-code identico a prima", lines_of(plain) == off)

dw, shw, _lv = imp('<rect x="10" y="10" width="30" height="30" fill="#ffffff"/>')
dw.shapes.extend(shw)
dw.layer(0).gray_power = True
jw = gcode.generate(dw, prof)
check("una forma bianca non si incide", not any(re.search(r"\bS[1-9]", l) for l in jw.lines), jw.lines[-12:])

mix = Document()
mix.layer(0).gray_power = True
r1 = RectShape(20, 20, layer=0)
r2 = RectShape(20, 20, layer=0)
r2.gray = 128
r2.apply(gcode.QTransform.fromTranslate(40, 0))
mix.shapes += [r1, r2]
gm = dict(gcode._gray_fill_groups([(l, t) for s in mix.shapes for l, t in s.leaves()], mix.layer(0)))
check("forma disegnata qui (senza grigio) accanto a una grigia: potenza massima per lei",
      mix.layer(0).power_max in gm and len(gm) == 2, sorted(gm))

print("--- C. salvataggio")
leaf = next(l for l in lv if l.gray == 64)
d = leaf.to_dict()
check("il grigio si salva solo se c'è", d.get("gray") == 64 and "gray" not in RectShape(5, 5).to_dict())
check("…e si rilegge", shape_from_dict(d).gray == 64)
for bad in ("64", -10, 300.7, True, float("nan"), None):
    d["gray"] = bad
    g = shape_from_dict(d).gray
    exp = {"64": None, -10: 0, 300.7: 255, True: None, None: None}.get(bad) if not (isinstance(bad, float) and bad != bad) else None
    check(f"grigio rovinato ({bad!r}) → {exp!r}", g == exp, g)
cd = CutSettings(index=0, mode="fill", gray_power=True).to_dict()
check("l'opzione del livello si salva e si rilegge", CutSettings.from_dict(cd).gray_power is True)
cd["gray_power"] = "sì"
check("…un valore rovinato la spegne", CutSettings.from_dict(cd).gray_power is False)
check("file di prima (senza l'opzione): spenta", CutSettings.from_dict({"index": 0, "mode": "fill"}).gray_power is False)

print("--- D. interfaccia")
from freelasercut.ui.panels_design import CutSettingsDialog  # noqa: E402

dlg = CutSettingsDialog(CutSettings(index=0, mode="fill", gray_power=True), prof)
check("nelle impostazioni del livello c'è la casella, accesa se l'opzione è accesa", dlg.gray_power.isChecked())
dlg.gray_power.setChecked(False)
check("…e spegnendola il livello la perde", dlg.values()["gray_power"] is False)

from freelasercut.ui import fill_preview  # noqa: E402

entries = [(l, t.map(l.local_path())) for s in doc.shapes for l, t in s.leaves()]
tones = fill_preview.tones(entries, doc.layers)
check("anteprima riempita: un tono per forma che si vede, con il suo grigio", sorted(g for g, _p in tones) == [0, 64, 128, 192],
      sorted(g for g, _p in tones))
doc.layers[0].gray_power = False
check("…senza l'opzione niente toni (il livello si colora come sempre)", fill_preview.tones(entries, doc.layers) == [])
doc.layers[0].gray_power = True

from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.editor.doc.layer(0).gray_power = True
w.editor.add(shapes, "prova")
fi = w.canvas.fill_item if hasattr(w.canvas, "fill_item") else None
if fi is not None:
    w.canvas.filled_view = True
    fi.rebuild()
    fi.ensure()
    check("sulla tela la vista riempita calcola i toni", len(fi.tones) == 4, len(fi.tones))
else:
    check("sulla tela c'è la zona riempita", False, "fill_item non trovato")

print("--- T. traduzioni")
keys = ("Potenza dal grigio delle forme (nero = massima, bianco = minima)",
        "Per i disegni SVG con riempimenti grigi: ogni forma si incide con la potenza del suo grigio, fra la Potenza "
        "minima e la massima. Il bianco non si incide. Le forme senza grigio usano la Potenza massima.")
missing = []
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    missing += [(lang, k[:30]) for k in keys if not cat.get(k) or cat[k] == k]
check("le voci nuove ci sono nelle 4 lingue", not missing, missing)

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.stdout.flush()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _uscita import esci  # noqa: E402

esci(0 if ok == len(results) else 1)
