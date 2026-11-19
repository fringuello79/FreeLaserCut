# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.7: SVG con tracciati senza disegno (`<path/>` senza «d»), segnalato il 19/11/2026 con «Albero Kinder.svg»:
«Non riesco a importare …: object of type 'NoneType' has no len()». La libreria degli SVG si fermava su quell'elemento
e non si importava niente del file.

A  tracciato senza «d» (chiuso con /> o con </path>, con prefisso svg:, più d'uno, dentro un gruppo): il resto del
   file si importa, il tracciato vuoto è saltato;
B  SVG sani: byte identici (clean_svg_bytes non tocca niente), stesso risultato di prima;
C  casi da non rovinare: «d» con spazi, attributi che contengono la lettera d (id, data-d, stroke-dasharray),
   «>» o apostrofi dentro un attributo, elementi che iniziano per «path» (pathEffect);
D  importazione da file (percorso) e .svgz;
E  rettangoli e cerchi con trasformazione speculare o inclinata (nello stesso file) al posto e nella misura giusti.
Uso: python tests/test_v207_svg_vuoti.py
"""
import gzip
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from freelasercut.core import io_formats  # noqa: E402
from freelasercut.core.document import Document  # noqa: E402

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("  OK  " if cond else "  KO  ") + name, info if not cond else "")


HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:svg="http://www.w3.org/2000/svg" '
        'width="100mm" height="100mm" viewBox="0 0 100 100">')


def svg(body):
    return (HEAD + body + "</svg>").encode()


RECT = '<rect x="10" y="10" width="30" height="20" stroke="black" fill="none"/>'


def imp(data):
    doc = Document()
    try:
        shapes = io_formats.import_svg(data, doc)
    except Exception as e:  # noqa: BLE001
        return None, repr(e)
    return [l for s in shapes for l, _ in s.leaves()], ""


def size(leaves):
    r = leaves[0].scene_rect() if hasattr(leaves[0], "scene_rect") else None
    return r


# --- A: tracciati senza disegno -----------------------------------------------------------------
for nome, corpo in [
    ("<path/> senza d", '<path/>' + RECT),
    ("<path …/> con attributi senza d", '<path id="a" fill="#000" stroke-width="2"/>' + RECT),
    ("<path></path> senza d", '<path id="b" fill="red"></path>' + RECT),
    ("<svg:path/> con prefisso", '<svg:path fill="red"/>' + RECT),
    ("due tracciati senza d", '<path/><path id="c"/>' + RECT),
    ("dentro un gruppo", '<g transform="translate(5,5)"><path/></g>' + RECT),
    ("su più righe", '<path\n   id="x"\n   style="fill:none"\n />' + RECT),
]:
    leaves, err = imp(svg(corpo))
    check(f"A {nome}: si importa il resto (1 forma)", leaves is not None and len(leaves) == 1, err or leaves)

# prima della correzione la libreria si fermava: lo si verifica direttamente, così la prova sa che il caso è vero
import io  # noqa: E402
import svgelements as se  # noqa: E402
try:
    se.SVG.parse(io.BytesIO(svg('<path/>' + RECT)), ppi=96.0, reify=True)
    grezzo = "nessun errore"
except TypeError as e:
    grezzo = str(e)
check("A la libreria da sola si ferma su <path/> (il caso esiste davvero)", "NoneType" in grezzo, grezzo)

# --- B: SVG sani non toccati ------------------------------------------------------------------------
sani = [
    svg(RECT),
    svg('<path d="M10 10 L50 10 L50 40 Z" stroke="black" fill="none"/>'),
    svg('<path d = "M10 10 L50 50"/>'),
    svg("<path d='M10 10 L50 50'/>"),
    svg('<path\n d="M10 10 L50 50"/>'),
]
for i, b in enumerate(sani):
    out, n = io_formats.clean_svg_bytes(b)
    check(f"B SVG sano {i + 1}: byte identici", out is b and n == 0)
leaves, err = imp(sani[1])
check("B tracciato normale importato", leaves is not None and len(leaves) == 1, err)

# --- C: casi da non rovinare ------------------------------------------------------------------------
out, n = io_formats.clean_svg_bytes(svg('<path id="d1" data-d="x" stroke-dasharray="1 2" d="M0 0 L9 9"/>'))
check("C attributi con la lettera d + d vero: non toccato", n == 0)
out, n = io_formats.clean_svg_bytes(svg('<path id="d1" data-d="x" stroke-dasharray="1 2"/>'))
check("C attributi con la lettera d ma senza d: sistemato", n == 1 and b'd=""' in out)
b = svg('<path inkscape:label="a&gt;b > c" xmlns:inkscape="x"/>' + RECT)
out, n = io_formats.clean_svg_bytes(b)
check("C «>» dentro un attributo: elemento non toccato (XML non rovinato)", n == 0 and out is b)
out, n = io_formats.clean_svg_bytes(svg('<path inkscape:label="l\'albero" xmlns:inkscape="x"/>' + RECT))
check("C apostrofo dentro un attributo: sistemato", n == 1)
leaves, err = imp(out)
check("C apostrofo: il file si importa", leaves is not None and len(leaves) == 1, err)
b = svg('<defs><pathEffect effect="spiro"/></defs>' + RECT)
out, n = io_formats.clean_svg_bytes(b)
check("C elemento «pathEffect»: non toccato", n == 0 and out is b)

# --- E: forme con trasformazioni speculari (stesso file di xTool Creative Space) -----------------------
def boxes(data):
    doc = Document()
    shapes = io_formats.import_svg(data, doc)
    out = []
    for s in shapes:
        for l, t in s.leaves():
            q = l.path()
            r = (t.map(q) if t is not None else q).boundingRect()
            out.append((round(r.left(), 2), round(-r.bottom(), 2), round(r.width(), 2), round(r.height(), 2)))
    return sorted(out)


ref = '<rect x="0" y="0" width="1" height="1"/>'  # riferimento in alto a sinistra: le distanze si misurano da qui
b = boxes(svg(ref + '<rect transform="matrix(-1,1.22465e-16,0,1,60,10)" x="0" y="0" width="40" height="5"/>'))
check("E rettangolo specchiato «matrix(-1,…)»: 40 × 5 mm, da x 20 a 60, y 10", b[-1][2:] == (40.0, 5.0)
      and abs((b[-1][0] - b[0][0]) - 20) < 0.01 and abs((b[-1][1] - b[0][1]) - 10) < 0.01, b)
b = boxes(svg(ref + '<circle transform="matrix(-0.01,1.22465e-18,0,0.01,80,50) scale(100)" cx="10" cy="10" r="10"/>'))
check("E cerchio specchiato con «scale(100)»: diametro 20 mm, da x 60 a 80", abs(b[-1][2] - 20) < 0.05
      and abs(b[-1][3] - 20) < 0.05 and abs((b[-1][0] - b[0][0]) - 60) < 0.05, b)
b = boxes(svg(ref + '<rect transform="matrix(0.000634,1,1,-0.000634,30,40)" x="0" y="0" width="11" height="3"/>'))
check("E rettangolo ruotato e specchiato: 3 × 11 mm", abs(b[-1][2] - 3) < 0.05 and abs(b[-1][3] - 11) < 0.05, b)
b = boxes(svg(ref + '<g transform="matrix(-1.93717e-15,-1,1,-1.93717e-15,50,50)"><path d="M0 0 L10 0"/></g>'))
check("E tracciato in un gruppo ruotato: la linea va verso l'alto (10 mm in verticale)",
      abs(b[-1][3] - 10) < 0.05 and b[-1][2] < 0.05, b)
b = boxes(svg(ref + '<rect x="30" y="20" width="10" height="4"/>'))
check("E rettangolo senza trasformazioni: invariato", b[-1][2:] == (10.0, 4.0)
      and abs((b[-1][0] - b[0][0]) - 30) < 0.01, b)

# --- D: da file e .svgz -----------------------------------------------------------------------------
d = tempfile.mkdtemp()
p1 = os.path.join(d, "Albero Kinder.svg")
with open(p1, "wb") as fh:
    fh.write(svg('<path/>' + RECT))
leaves, err = imp(p1)
check("D da file con nome con spazi: si importa", leaves is not None and len(leaves) == 1, err)
p2 = os.path.join(d, "prova.svgz")
with open(p2, "wb") as fh:
    fh.write(gzip.compress(svg('<path/>' + RECT)))
leaves, err = imp(p2)
check("D .svgz: si importa", leaves is not None and len(leaves) == 1, err)

ok = sum(results)
print(f"\n{ok}/{len(results)} controlli superati")
sys.exit(0 if ok == len(results) else 1)
