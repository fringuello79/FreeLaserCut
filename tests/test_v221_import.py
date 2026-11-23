# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.22.1: due domande arrivate da GitHub.

1. Un DXF perdeva il livello di taglio che lo stesso disegno in SVG aveva: del DXF si leggeva solo il colore RGB scritto
   sulla linea, mentre quasi tutti i programmi usano i colori numerati di AutoCAD (1 rosso, 5 blu…) o il colore del
   layer DXF («DaLayer»). Ora si leggono tutti e tre, come gli altri programmi.
2. Gli SVG senza unità di misura (misure in pixel): Illustrator li scrive a 72 punti per pollice, il vecchio Inkscape a
   90, gli altri a 96. Prima si leggevano sempre a 96 (un file di Illustrator veniva più piccolo del 25%, e gli
   incastri non tornavano). Ora il programma lo capisce da solo e nelle preferenze si può scegliere."""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = sys.argv[1] if len(sys.argv) > 1 else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ezdxf  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from freelasercut.core import io_formats  # noqa: E402
from freelasercut.core.document import Document  # noqa: E402

results = []
UI = os.environ["FLC_UI"]
D = tempfile.mkdtemp()


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info)


def leaves(shapes):
    out = []
    for s in shapes:
        out += [leaf for leaf, _ in s.leaves()]
    return out


def layers_by_size(shapes):
    """{larghezza arrotondata: livello} delle forme importate."""
    return {round(leaf.bounds().width(), 1): leaf.layer for leaf in leaves(shapes)}


RED = io_formats.nearest_layer((255, 0, 0))
BLUE = io_formats.nearest_layer((0, 0, 255))
BLACK = io_formats.nearest_layer((0, 0, 0))
check("i livelli di riferimento sono diversi (nero, rosso, blu)", len({RED, BLUE, BLACK}) == 3, (BLACK, RED, BLUE))


def square(msp, x, size, **attribs):
    msp.add_lwpolyline([(x, 0), (x + size, 0), (x + size, size), (x, size)], close=True, dxfattribs=attribs)


# ================================================================ 1. DXF: i colori
dwg = ezdxf.new("R2010")
dwg.header["$INSUNITS"] = 4
dwg.layers.add("TAGLIO", color=1)
dwg.layers.add("INCISIONE", color=7)
dwg.layers.add("BLU_SPENTO", color=5).off()  # layer spento: il colore si scrive negativo
msp = dwg.modelspace()
square(msp, 0, 10, color=1)  # rosso numerato
square(msp, 20, 11, layer="TAGLIO")  # DaLayer (rosso)
square(msp, 40, 12, color=7)  # bianco/nero
square(msp, 60, 13, layer="INCISIONE")  # DaLayer bianco/nero
sq = msp.add_lwpolyline([(80, 0), (94, 0), (94, 14), (80, 14)], close=True)
sq.rgb = (230, 0, 0)  # colore RGB vero sulla linea (come prima)
square(msp, 100, 15, layer="BLU_SPENTO")
blk = dwg.blocks.new("PEZZO")
blk.add_lwpolyline([(0, 0), (16, 0), (16, 16), (0, 16)], close=True, dxfattribs={"color": 0})  # DaBlocco
msp.add_blockref("PEZZO", (120, 0), dxfattribs={"color": 5})
blk2 = dwg.blocks.new("PEZZO2")
blk2.add_lwpolyline([(0, 0), (17, 0), (17, 17), (0, 17)], close=True)  # DaLayer dentro il blocco: layer "0"
msp.add_blockref("PEZZO2", (140, 0), dxfattribs={"layer": "TAGLIO"})
square(msp, 160, 18, layer="NON_DICHIARATO")
path = os.path.join(D, "colori.dxf")
dwg.saveas(path)
got = layers_by_size(io_formats.import_dxf(path, Document()))
check("DXF: rosso numerato (1) → livello rosso", got.get(10.0) == RED, got.get(10.0))
check("DXF: «DaLayer» su un layer rosso → livello rosso (prima finiva nel primo livello)", got.get(11.0) == RED,
      got.get(11.0))
check("DXF: bianco/nero (7) → primo livello, come prima", got.get(12.0) == BLACK, got.get(12.0))
check("DXF: «DaLayer» su un layer bianco/nero → primo livello", got.get(13.0) == BLACK, got.get(13.0))
check("DXF: colore RGB sulla linea → letto come prima", got.get(14.0) == RED, got.get(14.0))
check("DXF: layer spento (colore negativo) → il suo colore (blu)", got.get(15.0) == BLUE, got.get(15.0))
check("DXF: «DaBlocco» in un blocco inserito in blu → blu", got.get(16.0) == BLUE, got.get(16.0))
check("DXF: blocco con linee del layer «0» inserito sul layer rosso → il colore del layer «0» (nero)",
      got.get(17.0) == BLACK, got.get(17.0))
check("DXF: layer non dichiarato → primo livello, nessun errore", got.get(18.0) == BLACK, got.get(18.0))
check("DXF: tutte le forme importate", len(got) == 9, sorted(got))

# lo stesso disegno in SVG e in DXF: stessi livelli
svg = os.path.join(D, "taglio.svg")
open(svg, "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="40mm" viewBox="0 0 100 40">'
                     '<rect x="0" y="0" width="30" height="30" fill="none" stroke="#000000"/>'
                     '<rect x="40" y="0" width="20" height="20" fill="none" stroke="#FF0000"/></svg>')
dwg = ezdxf.new("R2010")
dwg.header["$INSUNITS"] = 4
dwg.layers.add("CUT", color=1)
msp = dwg.modelspace()
square(msp, 0, 30, layer="0")
square(msp, 40, 20, layer="CUT")
dxf = os.path.join(D, "taglio.dxf")
dwg.saveas(dxf)
ls, ld = layers_by_size(io_formats.import_svg(svg, Document())), layers_by_size(io_formats.import_dxf(dxf, Document()))
check("stesso disegno in SVG e in DXF (taglio rosso con un layer DXF): stessi livelli", ls == ld and ls[20.0] == RED,
      (ls, ld))

# 0.22.3: un DXF R12 scritto come quello di un utente (23/11, file da un programma di un'altra marca): solo POLYLINE
# chiuse con il colore numerato sulla linea, la tabella dei layer con le stesse due voci ripetute per ogni linea e
# maniglie doppie. La 0.21.1 lo metteva tutto nel primo livello; deve dare rosso e blu come l'SVG
def r12_poly(x, size, color, layer, handle):
    pts = [(x, 0), (x + size, 0), (x + size, size), (x, size)]
    out = ["0", "POLYLINE", "5", handle, "8", layer, "62", str(color), "66", "1", "10", "0", "20", "0", "30", "0",
           "70", "1"]
    for px, py in pts:
        out += ["0", "VERTEX", "5", handle, "8", layer, "10", str(px), "20", str(py), "30", "0"]
    return out + ["0", "SEQEND", "5", handle, "8", layer]


r12 = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$INSUNITS", "70", "4", "0", "ENDSEC",
       "0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", "6"]
for name, col in (("Layer_2", 1), ("Layer_1", 5)) * 3:  # voci ripetute, come nel file vero
    r12 += ["0", "LAYER", "2", name, "70", "0", "62", str(col), "6", "CONTINUOUS"]
r12 += ["0", "ENDTAB", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
r12 += r12_poly(0, 21, 1, "Layer_2", "7E") + r12_poly(30, 22, 5, "Layer_1", "7E") + r12_poly(60, 23, 5, "Layer_1", "7F")
r12 += ["0", "ENDSEC", "0", "EOF"]
p12 = os.path.join(D, "r12_ripetuto.dxf")
with open(p12, "w", newline="\r\n") as fh:
    fh.write("\n".join(r12) + "\n")
try:
    got = layers_by_size(io_formats.import_dxf(p12, Document()))
except Exception as ex:  # noqa: BLE001
    got = {"errore": repr(ex)}
check("DXF R12 con layer ripetuti e maniglie doppie: la linea rossa sul livello rosso", got.get(21.0) == RED, got)
check("…e le due blu sul livello blu", got.get(22.0) == BLUE and got.get(23.0) == BLUE, got)
check("…tutte e tre importate, misure giuste", sorted(got) == [21.0, 22.0, 23.0], sorted(got))

# ================================================================ 2. SVG: punti per pollice
RECT = '<rect x="0" y="0" width="{w}" height="{w}" fill="none" stroke="#000"/>'


def svg_file(name, head, w):
    p = os.path.join(D, name)
    open(p, "w", encoding="utf-8").write(head + RECT.format(w=w) + "</svg>")
    return p


def width_mm(p, ppi=0):
    io_formats.SVG_PPI = ppi
    io_formats.LAST_NOTE = ""
    sh = io_formats.import_svg(p, Document())
    return round(leaves(sh)[0].bounds().width(), 2), io_formats.LAST_NOTE


AI = ('<?xml version="1.0" encoding="utf-8"?>\n<!-- Generator: Adobe Illustrator 27.0.0, SVG Export Plug-In . '
      'SVG Version: 6.00 Build 0)  -->\n<svg version="1.1" xmlns="http://www.w3.org/2000/svg" x="0px" y="0px" '
      'viewBox="0 0 283.46 283.46" style="enable-background:new 0 0 283.46 283.46;" xml:space="preserve">')
p_ai = svg_file("illustrator.svg", AI, 141.732)  # 50 mm a 72 dpi
w, note = width_mm(p_ai)
check("Illustrator senza unità: 50 mm giusti (prima 37,5)", abs(w - 50.0) < 0.05, w)
check("…e lo dice dopo l'importazione", "Illustrator" in note and "72" in note, note)
AI_PX = AI.replace('x="0px" y="0px"', 'x="0px" y="0px" width="283.46px" height="283.46px"')
w, _n = width_mm(svg_file("illustrator_px.svg", AI_PX, 141.732))
check("Illustrator con larghezza in «px»: 50 mm", abs(w - 50.0) < 0.05, w)
AI_MM = AI.replace('x="0px" y="0px"', 'width="100mm" height="100mm"').replace("283.46 283.46", "100 100")
w, note = width_mm(svg_file("illustrator_mm.svg", AI_MM, 50))
check("Illustrator in mm: 50 mm e nessun avviso (le unità bastano)", abs(w - 50.0) < 0.05 and not note, (w, note))
p_plain = svg_file("normale.svg", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">', 188.976)
w, note = width_mm(p_plain)
check("SVG senza unità di un altro programma: 96 dpi come prima (50 mm), nessun avviso", abs(w - 50.0) < 0.05
      and not note, (w, note))
INK48 = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
         'inkscape:version="0.48.4 r9939" width="400" height="400">')
w, note = width_mm(svg_file("inkscape048.svg", INK48, 177.165))
check("vecchio Inkscape (0.48) senza unità: 90 dpi (50 mm)", abs(w - 50.0) < 0.05 and "90" in note, (w, note))
INK1 = INK48.replace("0.48.4 r9939", "1.2.2 (b0a8486541, 2022-12-01)").replace('width="400" height="400"',
                                                                                'width="100mm" height="100mm" '
                                                                                'viewBox="0 0 100 100"')
w, note = width_mm(svg_file("inkscape1.svg", INK1, 50))
check("Inkscape 1.x in mm: 50 mm, nessun avviso", abs(w - 50.0) < 0.05 and not note, (w, note))
INK092 = INK48.replace("0.48.4 r9939", "0.92.4 (5da689c313, 2019-01-14)")
w, note = width_mm(svg_file("inkscape092.svg", INK092, 188.976))
check("Inkscape 0.92 senza unità: 96 dpi", abs(w - 50.0) < 0.05 and not note, (w, note))

# scelta nelle preferenze
w, note = width_mm(p_plain, 72)
check("preferenza 72 dpi: anche un SVG qualsiasi senza unità si legge a 72", abs(w - 188.976 * 25.4 / 72) < 0.05
      and not note, w)
w, note = width_mm(p_ai, 96)
check("preferenza 96 dpi: anche Illustrator a 96 (come prima), nessun avviso", abs(w - 37.5) < 0.05 and not note,
      (w, note))
w, note = width_mm(svg_file("illustrator_mm2.svg", AI_MM, 50), 72)
check("preferenza 72 dpi: un SVG in mm resta giusto", abs(w - 50.0) < 0.05, w)
check("svg_ppi: larghezza in pollici o in punti = misura certa",
      io_formats.svg_ppi(b'<svg width="2in" height="3in" viewBox="0 0 10 10">', 72)[0] == 96.0
      and io_formats.svg_ppi(b'<svg width="144pt" height="72pt">', 72)[0] == 96.0)
check("svg_ppi: solo una delle due misure in mm = non certa", io_formats.svg_ppi(
    b'<svg width="100mm" height="400" viewBox="0 0 10 10">', 72)[0] == 72.0)
io_formats.SVG_PPI = 0

# ================================================================ 3. nel programma
from freelasercut.ui.dialogs_prefs import PreferencesDialog  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
dlg = PreferencesDialog(w)
box = getattr(dlg, "svg_ppi_box", None)
check("preferenze: la scelta c'è, «Da solo» all'inizio", box is not None and box.currentData() == 0
      and box.count() == 4, box and [box.itemText(i) for i in range(box.count())])
box.setCurrentIndex(box.findData(72))
check("…scelto 72: vale subito e resta salvato", io_formats.SVG_PPI == 72 and int(w.qs.value("svg_ppi")) == 72)
dlg.filter("Illustrator")
check("…si trova cercando «Illustrator» (le altre righe spariscono)", not box.parentWidget().isHidden()
      and any(wid.isHidden() for _k, wid, _t in dlg._rows))
box.setCurrentIndex(box.findData(0))
check("…di nuovo «Da solo»", io_formats.SVG_PPI == 0 and int(w.qs.value("svg_ppi")) == 0)
dlg.close()
w.qs.setValue("svg_ppi", 90)
w2 = MainWindow()
check("all'avvio si legge la scelta salvata", io_formats.SVG_PPI == 90, io_formats.SVG_PPI)
w2.qs.setValue("svg_ppi", 0)
io_formats.SVG_PPI = 0
w2.editor.dirty = False
w2.close()
w.import_files([p_ai])
check("importando il file di Illustrator la barra in basso dice com'è stato letto",
      "72" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
check("…e il pezzo è di 50 mm", any(abs(leaf.bounds().width() - 50.0) < 0.05 for leaf in leaves(w.editor.doc.shapes)))
w.editor.dirty = False
w.close()

ok = sum(results)
print(f"\n{ok}/{len(results)} superati")
sys.exit(0 if ok == len(results) else 1)
