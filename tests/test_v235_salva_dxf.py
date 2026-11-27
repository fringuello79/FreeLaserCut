# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Versione 0.23.5 (Modesto, 27/11/2026): File → Esporta DXF.

Il disegno si salva anche in DXF (R2010, millimetri, coordinate del piano con la Y verso l'alto), un layer DXF per
livello con il colore vero, polilinee per i tratti dritti e spline esatte per le curve; le foto si saltano e si contano.

Prove: (A) il file: unità, layer e colori, rettangolo chiuso con le coordinate giuste, linea aperta, ellisse esatta,
forme miste in un solo tratto, gruppi, testo, forme ruotate, nomi dei layer con caratteri vietati o doppi, foto
saltate, controllo del file con la libreria; (B) andata e ritorno: esporta e reimporta, stesse misure e stessi livelli;
(C) il comando: voce nel menu File dopo «Esporta SVG», nome proposto, selezione, estensione aggiunta, solo foto,
cartella che non esiste, Esporta SVG come prima; (D) scheda della guida e traduzioni; (E) difetti rimessi apposta.
Uso: python tests/test_v235_salva_dxf.py [classica|banco]
"""
import json
import math
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
for _k in ("FLC_NO_DIALOGS", "FLC_NO_FIRST_RUN", "FLC_NO_UPDATE"):
    os.environ[_k] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UI = os.environ["FLC_UI"]
results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + f"[{UI}] " + name, info if not cond else "", flush=True)


from PySide6.QtGui import QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

app = QApplication([])
avvisi = []
for _n in ("question", "information", "warning"):
    setattr(QMessageBox, _n, staticmethod(lambda *a, _n=_n, **k: avvisi.append(_n) or QMessageBox.Discard))

import ezdxf  # noqa: E402
import ezdxf.bbox  # noqa: E402
from PIL import Image  # noqa: E402

from freelasercut.core import io_formats  # noqa: E402
from freelasercut.core.document import (LAYER_COLORS, Document, EllipseShape, GroupShape, ImageShape,  # noqa: E402
                                        PathShape, RectShape, TextShape)
from freelasercut.i18n import LANGUAGES, SOURCE  # noqa: E402


def spin(t=0.05):
    e = time.time() + t
    while time.time() < e:
        app.processEvents()
        time.sleep(0.005)


def at(shape, x, y):
    shape.apply(QTransform.fromTranslate(x, y))
    return shape


def export(shapes, doc, name):
    p = os.path.join(TMP, name)
    n = io_formats.export_dxf(shapes, doc, p)
    return p, n, ezdxf.readfile(p)


def ents(dwg, layer=None):
    return [e for e in dwg.modelspace() if layer is None or e.dxf.layer == layer]


def rect_ok(e, x0, y0, x1, y1):
    """Polilinea chiusa con i 4 angoli giusti (in qualsiasi ordine), tolleranza un millesimo di mm."""
    if e.dxftype() != "LWPOLYLINE" or not e.closed:
        return False
    pts = sorted((round(x, 3), round(y, 3)) for x, y in e.get_points("xy"))
    return pts == sorted([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def ellipse_err(e, cx, cy, a, b):
    """Scarto massimo (in mm, circa) dei punti della spline dall'ellisse vera."""
    pts = list(e.construction_tool().approximate(400))
    return max(abs(math.hypot((p.x - cx) / a, (p.y - cy) / b) - 1.0) * max(a, b) for p in pts)


# ====================================================================== A. il file
print("--- A. il file DXF")
d = Document()
d.layer(2).name = "Taglio"
r = at(RectShape(30, 20, layer=0), 10, 15)
el = at(EllipseShape(40, 20, layer=2), 100, 50)
ln = QPainterPath()
ln.moveTo(5, 5)
ln.lineTo(60, 5)
ln.lineTo(60, 80)
line = PathShape(ln, layer=1)
p, (n_ent, n_img), dwg = export([r, el, line], d, "base.dxf")
check("A unità: millimetri ($INSUNITS 4)", dwg.header.get("$INSUNITS") == 4, dwg.header.get("$INSUNITS"))
check("A versione R2010 (colori veri letti da tutti i programmi moderni)", dwg.dxfversion == "AC1024", dwg.dxfversion)
nomi = {lay.dxf.name for lay in dwg.layers}
check("A un layer per livello: «C00», «C01» e il nome dato dall'utente «C02 Taglio»",
      {"C00", "C01", "C02 Taglio"} <= nomi, nomi)
colori = {lay.dxf.name: lay.rgb for lay in dwg.layers if lay.dxf.name.startswith("C")}
attesi = {k: io_formats._hex_to_rgb(LAYER_COLORS[i]) for k, i in (("C00", 0), ("C01", 1), ("C02 Taglio", 2))}
check("A ogni layer ha il colore vero del suo livello", all(colori.get(k) == v for k, v in attesi.items()), colori)
check("A e anche un colore numerato (per i programmi vecchi), mai il 7 bianco/nero",
      all(1 <= lay.dxf.color <= 255 and lay.dxf.color != 7 for lay in dwg.layers if lay.dxf.name.startswith("C")))
check("A le linee prendono il colore dal layer («DaLayer»)", all(e.dxf.get("color", 256) == 256 for e in ents(dwg)))
check("A tre forme → tre tratti", n_ent == 3 and len(ents(dwg)) == 3 and n_img == 0, (n_ent, len(ents(dwg))))
c00 = ents(dwg, "C00")
check("A rettangolo: una polilinea chiusa con gli angoli alle coordinate del piano (10,15)-(40,35)",
      len(c00) == 1 and rect_ok(c00[0], 10, 15, 40, 35), [list(e.get_points("xy")) for e in c00])
c01 = ents(dwg, "C01")
check("A linea aperta: polilinea aperta, 3 punti, nello stesso ordine",
      len(c01) == 1 and not c01[0].closed and [tuple(round(v, 3) for v in q) for q in c01[0].get_points("xy")]
      == [(5, 5), (60, 5), (60, 80)])
c02 = ents(dwg, "C02 Taglio")
err = ellipse_err(c02[0], 120, 60, 20, 10) if len(c02) == 1 and c02[0].dxftype() == "SPLINE" else 99
check("A ellisse: una sola spline, scarto dalla curva vera sotto 0,02 mm (non spezzettata)", err < 0.02, err)
sp = c02[0].construction_tool() if c02 else None
check("A la spline dell'ellisse si chiude su se stessa",
      sp is not None and sp.point(0).isclose(sp.point(sp.max_t), abs_tol=1e-6))
aud = dwg.audit()
check("A controllo del file con la libreria DXF: nessun errore", not aud.has_errors, [str(x) for x in aud.errors][:3])

# forme miste, gruppi, testo, rotazioni
rr = at(RectShape(20, 10, radius=3, layer=3), 0, 0)
g = GroupShape([at(RectShape(5, 5, layer=4), 200, 200), at(RectShape(6, 6, layer=5), 210, 200)])
t = at(TextShape("Ab", size=10, layer=6), 50, 100)
rot = at(RectShape(10, 10, layer=7), 0, 0)
rot.apply(QTransform().rotate(45))
p2, (n2, _), dwg2 = export([rr, g, t, rot], d, "misto.dxf")
c03 = ents(dwg2, "C03")
check("A rettangolo arrotondato (lati dritti e curve): un solo tratto, una spline", len(c03) == 1
      and c03[0].dxftype() == "SPLINE", [e.dxftype() for e in c03])
bb = ezdxf.bbox.extents(c03) if c03 else None
check("A …con le misure giuste (20 × 10)", bb is not None and abs(bb.size.x - 20) < 1e-3 and abs(bb.size.y - 10) < 1e-3,
      bb.size if bb else None)
check("A gruppo: ogni figlio sul layer del suo livello", len(ents(dwg2, "C04")) == 1 and len(ents(dwg2, "C05")) == 1)
c06 = ents(dwg2, "C06")
tb = t.bounds()
eb = ezdxf.bbox.extents(c06) if c06 else None
check("A testo: esportato come contorni delle lettere, stesso ingombro sul piano", c06 and eb is not None
      and abs(eb.extmin.x - tb.left()) < 0.05 and abs(eb.extmax.x - tb.right()) < 0.05
      and abs(eb.extmin.y - tb.top()) < 0.05 and abs(eb.extmax.y - tb.bottom()) < 0.05,
      (eb, tb) if eb else None)
c07 = ents(dwg2, "C07")
pts = [tuple(round(v, 3) for v in q) for q in c07[0].get_points("xy")] if c07 else []
check("A quadrato ruotato di 45°: gli angoli ruotati, non il quadrato dritto",
      len(pts) == 4 and any(abs(x) < 1e-3 and abs(y - 10 * math.sqrt(2)) < 1e-3 for x, y in pts), pts)

# nomi dei layer
d.layer(8).name = 'a/b:c*"d"'
d.layer(9).name = 'a_b_c__d_'
p3, _, dwg3 = export([at(RectShape(5, 5, layer=8), 0, 0), at(RectShape(5, 5, layer=9), 10, 0)], d, "nomi.dxf")
nomi3 = sorted(lay.dxf.name for lay in dwg3.layers if lay.dxf.name.startswith("C"))
check("A nomi con caratteri vietati nel DXF: sostituiti, il file si apre", nomi3 == ["C08 a_b_c__d_", "C09 a_b_c__d_"]
      or (len(nomi3) == 2 and all(not set('/:*"') & set(n) for n in nomi3)), nomi3)
d.layer(10).name = "C11"
d.layer(11).name = ""
p4, _, dwg4 = export([at(RectShape(5, 5, layer=10), 0, 0), at(RectShape(5, 5, layer=11), 10, 0)], d, "doppi.dxf")
check("A due livelli con lo stesso nome DXF: restano due layer distinti",
      len({e.dxf.layer for e in ents(dwg4)}) == 2, [e.dxf.layer for e in ents(dwg4)])

# foto
d.images["foto"] = Image.new("L", (20, 20), 128)
ph = at(ImageShape("foto", 30, 30), 0, 0)
p5, (n5, i5), dwg5 = export([ph, at(RectShape(5, 5, layer=0), 0, 0)], d, "foto.dxf")
check("A foto: saltata e contata, le altre forme ci sono", i5 == 1 and n5 == 1 and len(ents(dwg5)) == 1, (n5, i5))

# ====================================================================== B. andata e ritorno
print("--- B. esporta e reimporta")
d6 = Document()
back = io_formats.import_dxf(p, d6)
kids = back[0].children if back and isinstance(back[0], GroupShape) else back
check("B tornano tre forme", len(kids) == 3, len(kids))
check("B ognuna sul suo livello (0, 1, 2)", sorted(k.layer for k in kids) == [0, 1, 2], [k.layer for k in kids])
orig = {0: r.bounds(), 1: line.bounds(), 2: el.bounds()}
tutto = io_formats.geom.rect_union(orig.values())
ok = True
for k in kids:
    a, b = k.bounds(), orig[k.layer]
    # l'importazione sposta tutto a partire da (0,0): si confrontano misure e posizioni relative
    if (abs(a.width() - b.width()) > 1e-3 or abs(a.height() - b.height()) > 1e-3
            or abs(a.left() - (b.left() - tutto.left())) > 1e-3 or abs(a.top() - (b.top() - tutto.top())) > 1e-3):
        ok = False
check("B stesse misure e stesse posizioni relative (al millesimo di mm)", ok)
p7, _, _ = export(kids, d6, "ritorno.dxf")
back2 = io_formats.import_dxf(p7, Document())
kids2 = back2[0].children if back2 and isinstance(back2[0], GroupShape) else back2
check("B una seconda andata e ritorno non cambia niente", [round(k.bounds().width(), 3) for k in kids2]
      == [round(k.bounds().width(), 3) for k in kids])

# ====================================================================== C. il comando
print("--- C. il comando nel programma")
from freelasercut.ui.main_window import MainWindow  # noqa: E402

w = MainWindow()
w.show()
spin(0.3)
acts = w.m_file.actions()
check("C voce «Esporta DXF…» nel menu File, subito dopo «Esporta SVG…»",
      "export_dxf" in w.acts and acts.index(w.acts["export_dxf"]) == acts.index(w.acts["export"]) + 1)
check("C la voce ha la scheda della guida", getattr(w.acts["export_dxf"], "help_key", "export_dxf") == "export_dxf")
ed = w.editor
ed.doc.name = "Pippo"
a1 = at(RectShape(10, 10, layer=0), 0, 0)
a2 = at(RectShape(10, 10, layer=1), 50, 0)
ed.doc.add(a1)
ed.doc.add(a2)
ed.changed.emit()
chiesti = []
dest = os.path.join(TMP, "dal_menu")
QFileDialog.getSaveFileName = staticmethod(lambda _p, _t, start, *_a, **_k: (chiesti.append(os.path.basename(start))
                                                                             or dest, ""))
ed.select([])
w.acts["export_dxf"].trigger()
spin()
check("C propone il nome del progetto «Pippo.dxf»", chiesti[-1:] == ["Pippo.dxf"], chiesti)
check("C senza estensione scritta: aggiunge «.dxf»", os.path.exists(dest + ".dxf"))
check("C niente selezionato: esporta tutto il disegno", len(ents(ezdxf.readfile(dest + ".dxf"))) == 2)
ed.select([a2])
w.file_export_dxf(path=os.path.join(TMP, "sel.dxf"))
check("C con una selezione: solo le forme selezionate", [e.dxf.layer for e in ents(ezdxf.readfile(
    os.path.join(TMP, "sel.dxf")))] == ["C01"])
ed.doc.images["f"] = Image.new("L", (10, 10), 0)
f = ImageShape("f", 20, 20)
ed.doc.add(f)
ed.select([f])
del avvisi[:]
w.file_export_dxf(path=os.path.join(TMP, "solofoto.dxf"))
check("C solo foto selezionate: avviso e nessun file", avvisi == ["information"]
      and not os.path.exists(os.path.join(TMP, "solofoto.dxf")), avvisi)
ed.select([f, a1])
w.file_export_dxf(path=os.path.join(TMP, "misto2.dxf"))
check("C foto e forme: file scritto e messaggio che le foto sono saltate", os.path.exists(os.path.join(TMP, "misto2.dxf"))
      and "1" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
del avvisi[:]
w.file_export_dxf(path=os.path.join(TMP, "non", "esiste", "x.dxf"))
check("C cartella che non esiste: avviso, il programma non si ferma", avvisi == ["warning"], avvisi)
ed.select([])
del chiesti[:]
svg = os.path.join(TMP, "come_prima.svg")
QFileDialog.getSaveFileName = staticmethod(lambda _p, _t, start, *_a, **_k: (chiesti.append(os.path.basename(start))
                                                                             or svg, ""))
w.file_export()
check("C «Esporta SVG» come prima: nome «Pippo.svg» e file scritto", chiesti == ["Pippo.svg"] and os.path.exists(svg),
      chiesti)
ed.dirty = False
w.file_export_dxf(path=os.path.join(TMP, "pulito.dxf"))
check("C esportare non segna il progetto come modificato né tocca il disegno",
      not ed.dirty and len(ed.doc.shapes) == 3 and a1.bounds().width() == 10)

# ====================================================================== D. guida e traduzioni
print("--- D. guida e traduzioni")
from freelasercut.i18n import tr  # noqa: E402
from freelasercut.ui import help_texts  # noqa: E402

check("D scheda della guida «export_dxf»", "export_dxf" in help_texts.HELP and "DWG" in help_texts.HELP["export_dxf"][1])
check("D nessun programma commerciale nominato nella scheda di Esporta SVG",
      "Illustrator" not in help_texts.HELP["export"][1])
testi = ["Esporta DXF…", "Esporta DXF", "DXF (*.dxf)", help_texts.HELP["export_dxf"][1], help_texts.HELP["export"][1],
         "Salva il disegno come DXF, da aprire nei programmi CAD: un layer per ogni livello",
         "Il DXF contiene solo linee e forme, non le foto. Per salvare le foto usa «Esporta SVG».",
         "Esportato: {0} · le foto non vanno nel DXF ({1} saltate)"]
mancano = []
for lang in [l for l in LANGUAGES if l != SOURCE]:
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", lang + ".json"), encoding="utf-8"))
    mancano += [(lang, s[:30]) for s in testi if not cat.get(s) or cat[s].count("{") != s.count("{")]
check("D tutti i testi nuovi tradotti in tutte le lingue del programma", not mancano, mancano[:4])
check("D tr() restituisce il testo", tr("Esporta DXF") == "Esporta DXF")

# ====================================================================== E. difetti rimessi apposta
print("--- E. difetti rimessi apposta")
vero_sub = io_formats._qpath_subpaths
vero_nome = io_formats._dxf_layer_name


def senza_chiusura(qp):
    out = vero_sub(qp)
    return [(s, segs[:-1] if len(segs) > 1 else segs) for s, segs in out]


io_formats._qpath_subpaths = senza_chiusura
_, _, dm = export([r], d, "rotto1.dxf")
io_formats._qpath_subpaths = vero_sub
check("E se si perdesse l'ultimo lato, la prova del rettangolo chiuso lo vedrebbe",
      not rect_ok(ents(dm)[0], 10, 15, 40, 35))
io_formats._dxf_layer_name = lambda doc, idx: "0"
_, _, dm2 = export([r, el], d, "rotto2.dxf")
io_formats._dxf_layer_name = vero_nome
check("E anche se tutti i livelli avessero lo stesso nome DXF, la protezione dei nomi doppi li tiene separati",
      len({e.dxf.layer for e in ents(dm2)}) == 2, [e.dxf.layer for e in ents(dm2)])
vero_rgb = io_formats._hex_to_rgb
io_formats._hex_to_rgb = lambda h: (0, 0, 0)
_, _, dm5 = export([r, el], d, "rotto5.dxf")
io_formats._hex_to_rgb = vero_rgb
check("E se i layer perdessero il colore del livello, la prova dei colori lo vedrebbe",
      any(lay.rgb != vero_rgb(LAYER_COLORS[2]) for lay in dm5.layers if lay.dxf.name == "C02 Taglio"))


def capovolto(qp):
    return vero_sub(QTransform.fromScale(1, -1).map(qp))


io_formats._qpath_subpaths = capovolto
_, _, dm3 = export([r], d, "rotto3.dxf")
io_formats._qpath_subpaths = vero_sub
check("E con la Y capovolta (disegno a specchio), la prova delle coordinate lo vedrebbe",
      not rect_ok(ents(dm3)[0], 10, 15, 40, 35))
_, _, dm4 = export([el], d, "ok_dopo.dxf")
check("E rimesso tutto a posto: l'ellisse torna esatta", ellipse_err(ents(dm4)[0], 120, 60, 20, 10) < 0.02)

ed.dirty = False
w.close()
spin(0.2)
n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} superati")
sys.exit(0 if n_ok == len(results) else 1)
