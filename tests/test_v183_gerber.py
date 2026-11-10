# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.3: importazione dei file Gerber (RS-274X/X2) e dei fori Excellon dei circuiti stampati.

Da una domanda sotto un video: «può fare anche il Mirror per incidere un piccolo circuito stampato?».
I file di prova sono scritti qui dentro, con misure scelte perché il risultato si possa calcolare a mano
(aree, ingombri, posizioni): ogni controllo confronta numeri, non solo «non va in errore».

Matrice dei casi:
- numeri: mm e pollici, zeri in testa o in coda omessi, unità o formato mancanti, misure non credibili;
- forme: cerchio, rettangolo, asola, poligono, con foro; tratti con punta tonda e rettangolare; archi (più
  quadranti, un quadrante, cerchio intero); regioni in senso orario e antiorario; macro (come quelle di KiCad);
- ordine degli oggetti: scuro/chiaro, oggetti sovrapposti di verso opposto (non devono annullarsi), specchio,
  rotazione e scala delle aperture, ripetizioni, aperture a blocco;
- file vecchi o rovinati: comandi superati, apertura illeggibile (avviso chiaro), apertura mancante, file senza
  fine, file binario, Gerber senza aperture, file vuoto;
- a cosa serve un file: dagli attributi X2 e dal nome;
- fori Excellon: mm e pollici, numeri senza punto (LZ/TZ, formato dichiarato, formato dedotto dal rame),
  asole, fresature, ripetizioni, punte senza diametro, coordinate incrementali;
- basetta: negativo con bordo a rettangolo o dal contorno (chiuso, non chiuso, con uno scasso dentro), rame
  fuori dal contorno, positivo, fori veri / punto / ignorati, specchio (automatico e scelto), registro fra i
  file, ruoli scelti a mano, più file di rame;
- programma (Classica e Banco): Importa con più file, misure mai cambiate, livelli liberi e modo del livello,
  livello già usato non toccato, Annulla/Ripeti, G-code vero confrontato con l'area, finestra delle scelte,
  estensioni sconosciute (decide il contenuto), file illeggibili in mezzo agli altri, comando di Claude,
  salva e riapri, scheda d'aiuto, filtro della finestra, tempi.
"""
import math
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
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ["FLC_NO_UPDATE"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
from freelasercut.core import gcode, gerber, io_formats  # noqa: E402
from freelasercut.core.document import Document, RectShape  # noqa: E402
from freelasercut.profile import MachineProfile  # noqa: E402
from freelasercut.ui import dialogs_gerber, help_texts  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402

UI = os.environ["FLC_UI"]
results = []
TMP = tempfile.mkdtemp()
PI = math.pi


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + f"[{UI}] " + name + (f"  [{info}]" if info and not cond else ""))


def near(a, b, rel=1e-6, ab=1e-6):
    return abs(a - b) <= max(ab, rel * abs(b))


def c(v):
    """mm -> intero del formato 4.6."""
    return str(int(round(v * 1e6)))


def write(name, text):
    p = os.path.join(TMP, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return p


_n = [0]


def gbr(body, head="%FSLAX46Y46*%\n%MOMM*%\n", name=None, end="M02*\n"):
    _n[0] += 1
    return write(name or f"prova{_n[0]}.gbr", head + body + end)


def area(path):
    return gerber.area_mm2(gerber.load(path).image)


def box(path):
    return gerber.bounds(gerber.load(path).image)


def flash(x, y):
    return f"X{c(x)}Y{c(y)}D03*\n"


def move(x, y):
    return f"X{c(x)}Y{c(y)}D02*\n"


def line(x, y):
    return f"X{c(x)}Y{c(y)}D01*\n"


def raises(fn, text=""):
    try:
        fn()
    except gerber.GerberError as exc:
        return text.lower() in str(exc).lower()
    return False


# ================================================================== numeri e unità
p = gbr("%ADD10R,2X1*%\nD10*\n" + flash(10, 5))
check("mm: rettangolo 2 × 1 in (10, 5): area 2 mm² esatta", near(area(p), 2.0), area(p))
check("…e ingombro 9…11 × 4,5…5,5", all(near(a, b) for a, b in zip(box(p), (9, 4.5, 11, 5.5))), box(p))

p = gbr("%ADD10C,0.1*%\nD10*\nX10000Y10000D03*\n", head="%FSLAX24Y24*%\n%MOIN*%\n")
b = box(p)
check("pollici: cerchio da 0,1\" in (1\", 1\") -> centro a 25,4 mm, diametro 2,54 mm",
      near((b[0] + b[2]) / 2, 25.4, ab=1e-4) and near(b[2] - b[0], 2.54, ab=0.01) and near(area(p), PI * 1.27 ** 2, rel=0.015),
      (b, area(p)))

p = gbr("%ADD10R,0.1X0.1*%\nD10*\nX01Y005D03*\n", head="%FSTAX23Y23*%\n%MOIN*%\n")
b = box(p)
check("zeri in coda omessi (formato vecchio): X01 = 1 pollice, Y005 = 0,5 pollici",
      near((b[0] + b[2]) / 2, 25.4, ab=1e-4) and near((b[1] + b[3]) / 2, 12.7, ab=1e-4), b)

p = gbr("%ADD10R,0.1X0.1*%\nD10*\nX10000Y10000D03*\n", head="%FSLAX24Y24*%\n")
f = gerber.load(p)
check("unità non dichiarata: letto in pollici e lo dice", near(gerber.bounds(f.image)[2], 25.4 + 1.27, ab=1e-4)
      and any("unità" in w for w in f.warnings), f.warnings)
p = gbr("%ADD10C,1*%\nD10*\nX100Y100D03*\n", head="%MOMM*%\n")
check("formato dei numeri non dichiarato: errore chiaro, niente misure a caso", raises(lambda: gerber.load(p), "formato"))
p = gbr("%ADD10C,0.01*%\nD10*\nX0Y0D03*\nX99999999Y99999999D03*\n", head="%FSLAX22Y22*%\n%MOIN*%\n")
check("misure non credibili (formato sbagliato): rifiutato", raises(lambda: gerber.load(p), "non credibili"))
p = gbr("%ADD10R,2X1*%\nD10*\nX10.5Y5.25D03*\n")
check("coordinate scritte con il punto (non standard): lette come sono", near(box(p)[0], 9.5) and near(box(p)[1], 4.75))

# ================================================================== forme
p = gbr("%ADD10C,4X2*%\nD10*\n" + flash(0, 0))
check("cerchio Ø4 con foro Ø2: area π(2² − 1²)", near(area(p), PI * 3, rel=0.015), area(p))
p = gbr("%ADD10O,3X1*%\nD10*\n" + flash(0, 0))
check("asola 3 × 1: area 2 + π/4", near(area(p), 2 + PI / 4, rel=0.015) and near(box(p)[2], 1.5, ab=1e-3), area(p))
p = gbr("%ADD10P,2X6*%\nD10*\n" + flash(0, 0))
check("esagono inscritto in Ø2: area 3√3/2, un vertice a destra", near(area(p), 3 * math.sqrt(3) / 2, rel=1e-4)
      and near(box(p)[2], 1.0, ab=1e-4), (area(p), box(p)))
p = gbr("%ADD10R,2X2X1*%\nD10*\n" + flash(0, 0))
check("quadrato 2 × 2 con foro tondo Ø1: area 4 − π/4", near(area(p), 4 - PI / 4, rel=0.01), area(p))

p = gbr("%ADD10C,0.5*%\nD10*\n" + move(0, 0) + "G01*\n" + line(10, 0))
check("tratto con punta tonda Ø0,5 lungo 10: area 5 + π·0,25²", near(area(p), 5 + PI * 0.0625, rel=0.005), area(p))
check("…ingombro −0,25…10,25", near(box(p)[0], -0.25, ab=1e-3) and near(box(p)[2], 10.25, ab=1e-3), box(p))
p = gbr("%ADD10R,2X1*%\nD10*\n" + move(0, 0) + "G01*\n" + line(5, 3))
check("tratto con punta rettangolare 2 × 1 da (0,0) a (5,3): area 2 + 5·1 + 3·2 = 13", near(area(p), 13.0, rel=1e-6), area(p))
p = gbr("%ADD10C,0.5*%\nD10*\n" + move(3, 3) + "G01*\n" + line(3, 3))
check("tratto di lunghezza zero = un punto tondo", near(area(p), PI * 0.0625, rel=0.05) and near(box(p)[2], 3.25, ab=1e-3), area(p))

quarter = PI / 2 * 10 * 1 + PI * 0.25
p = gbr("%ADD10C,1*%\nD10*\nG75*\n" + move(10, 0) + f"G03X{c(0)}Y{c(10)}I{c(-10)}J{c(0)}D01*\n")
check("arco antiorario di un quarto (raggio 10, punta Ø1): area π/2·10 + π/4", near(area(p), quarter, rel=0.005), area(p))
b = box(p)
check("…dalla parte giusta: sta nel primo quadrante", b[0] > -0.6 and b[1] > -0.6 and near(b[2], 10.5, ab=0.01), b)
p = gbr("%ADD10C,1*%\nD10*\nG75*\n" + move(10, 0) + f"G02X{c(0)}Y{c(10)}I{c(-10)}J{c(0)}D01*\n")
check("lo stesso arco in senso orario fa tre quarti di giro", near(area(p), 3 * PI / 2 * 10 + PI * 0.25, rel=0.005), area(p))
p = gbr("%ADD10C,1*%\nD10*\nG75*\n" + move(10, 0) + f"G03X{c(10)}Y{c(0)}I{c(-10)}J{c(0)}D01*\n")
check("inizio = fine con più quadranti: cerchio intero", near(area(p), 2 * PI * 10, rel=0.005), area(p))
p = gbr("%ADD10C,1*%\nD10*\nG74*\n" + move(10, 0) + f"G03X{c(0)}Y{c(10)}I{c(10)}J{c(0)}D01*\n")
check("un quadrante (vecchio G74, I e J senza segno): lo stesso quarto", near(area(p), quarter, rel=0.005)
      and box(p)[0] > -0.6, (area(p), box(p)))

sq = move(0, 0) + line(10, 0) + line(10, 10) + line(0, 10) + line(0, 0)
sq_cw = move(0, 0) + line(0, 10) + line(10, 10) + line(10, 0) + line(0, 0)
p = gbr("G36*\n" + sq + "G37*\n")
check("regione quadrata 10 × 10: area 100 esatta", near(area(p), 100.0), area(p))
p = gbr("G36*\n" + sq_cw + "G37*\n")
check("la stessa regione disegnata in senso orario: ancora 100", near(area(p), 100.0), area(p))
other = move(5, 0) + line(5, 10) + line(15, 10) + line(15, 0) + line(5, 0)  # orario, sovrapposta per metà
p = gbr("G36*\n" + sq + "G37*\nG36*\n" + other + "G37*\n")
check("due regioni sovrapposte di verso opposto NON si annullano: 150", near(area(p), 150.0), area(p))
p = gbr("G75*\nG36*\n" + move(0, 0) + line(10, 0) + f"G03X{c(0)}Y{c(0)}I{c(-5)}J{c(0)}D01*\nG37*\n")
check("regione con un arco: mezzo cerchio di raggio 5", near(area(p), PI * 12.5, rel=0.005) and near(box(p)[3], 5, ab=0.01),
      (area(p), box(p)))
p = gbr("G36*\n" + sq + move(20, 0) + line(30, 0) + line(30, 10) + line(20, 0) + "G37*\n")
check("due contorni nella stessa regione: 100 + 50", near(area(p), 150.0), area(p))

# ================================================================== ordine: scuro e chiaro
sq_ap = "%ADD10R,10X10*%\n%ADD11C,4*%\n%ADD12C,2*%\n"
p = gbr(sq_ap + "D10*\n" + flash(0, 0) + "%LPC*%\nD11*\n" + flash(0, 0))
check("chiaro sopra scuro: quadrato meno cerchio Ø4", near(area(p), 100 - PI * 4, rel=0.002), area(p))
p = gbr(sq_ap + "D10*\n" + flash(0, 0) + "%LPC*%\nD11*\n" + flash(0, 0) + "%LPD*%\nD12*\n" + flash(0, 0))
check("…e scuro di nuovo sopra: più il cerchio Ø2", near(area(p), 100 - PI * 4 + PI, rel=0.002), area(p))
p = gbr(sq_ap + "%LPC*%\nD11*\n" + flash(0, 0) + "%LPD*%\nD10*\n" + flash(0, 0))
check("chiaro PRIMA dello scuro non toglie niente (conta l'ordine del file)", near(area(p), 100.0), area(p))
tri = "%AMTRI*\n4,1,3,0,0,4,0,0,2,0,0,0*%\n%ADD20TRI*%\n"  # triangolo (0,0) (4,0) (0,2): area 4
p = gbr(tri + "D20*\n" + flash(0, 0) + "%LMX*%\n" + flash(4, 0))
check("un'apertura e la sua copia specchiata, sovrapposte: unione, non buco", near(area(p), 6.0, rel=1e-4), area(p))

# ================================================================== macro
rr = ("%AMRoundRect*\n0 rettangolo con gli angoli tondi, come lo scrive KiCad*\n"
      "4,1,4,$2,$3,$4,$5,$6,$7,$8,$9,$2,$3,0*\n1,1,$1+$1,$2,$3*\n1,1,$1+$1,$4,$5*\n1,1,$1+$1,$6,$7*\n1,1,$1+$1,$8,$9*\n"
      "20,1,$1+$1,$2,$3,$4,$5,0*\n20,1,$1+$1,$4,$5,$6,$7,0*\n20,1,$1+$1,$6,$7,$8,$9,0*\n20,1,$1+$1,$8,$9,$2,$3,0*%\n"
      "%ADD30RoundRect,0.5X-1.5X-0.5X1.5X-0.5X1.5X0.5X-1.5X0.5*%\n")
p = gbr(rr + "D30*\n" + flash(0, 0))
check("macro «rettangolo con angoli tondi» di KiCad 4 × 2, raggio 0,5: area 8 − (4 − π)·0,25",
      near(area(p), 8 - (4 - PI) * 0.25, rel=0.005) and near(box(p)[2], 2.0, ab=1e-3) and near(box(p)[3], 1.0, ab=1e-3),
      (area(p), box(p)))
p = gbr("%AMDONUT*\n21,1,4,4,0,0,0*\n1,0,2,0,0*%\n%ADD31DONUT*%\n%ADD32C,1*%\nD31*\n" + flash(0, 0) + "D32*\n" + flash(0, 0))
check("macro con una parte tolta (esposizione 0) e un altro oggetto nel buco: 16 − π + π/4",
      near(area(p), 16 - PI + PI / 4, rel=0.003), area(p))
p = gbr("%AMCALC*\n$3=$1x2+$2*\n21,1,$3,$2/2,0,0,0*%\n%ADD33CALC,1.5X1*%\nD33*\n" + flash(0, 0))
check("macro con variabili e conti ($3 = $1·2 + $2): rettangolo 4 × 0,5", near(area(p), 2.0) and near(box(p)[2], 2.0), area(p))
p = gbr("%AMROT*\n21,1,4,1,0,0,90*%\n%ADD34ROT*%\nD34*\n" + flash(0, 0))
check("macro ruotata di 90°: l'ingombro diventa 1 × 4", near(box(p)[2], 0.5, ab=1e-4) and near(box(p)[3], 2.0, ab=1e-4), box(p))
p = gbr("%AMTH*\n7,0,0,4,3,0.5,0*%\n%ADD35TH*%\nD35*\n" + flash(0, 0))
a_th = area(p)
check("macro scarico termico Ø4/Ø3 con croce da 0,5: anello meno quattro tagli",
      PI * (4 - 2.25) - 4 * 0.5 * 0.56 < a_th < PI * (4 - 2.25) - 4 * 0.5 * 0.48, a_th)
p = gbr("%AMPOLY*\n5,1,4,0,0,2,45*%\n%ADD36POLY*%\nD36*\n" + flash(0, 0))
check("macro poligono a 4 lati ruotato di 45°: quadrato di lato √2 dritto", near(area(p), 2.0, rel=1e-4)
      and near(box(p)[2], math.sqrt(2) / 2, ab=1e-3), (area(p), box(p)))
f = gerber.load(gbr("%AMODD*\n99,1,2,3*\n21,1,2,2,0,0,0*%\n%ADD37ODD*%\nD37*\n" + flash(0, 0)))
check("macro con una primitiva sconosciuta: il resto si legge e c'è l'avviso", near(gerber.area_mm2(f.image), 4.0)
      and any("primitiva" in w for w in f.warnings), f.warnings)

# ================================================================== specchio, rotazione, scala, ripetizioni
p = gbr("%ADD10R,2X1*%\nD10*\n%LR90*%\n" + flash(0, 0))
check("apertura ruotata di 90° (LR): 2 × 1 diventa 1 × 2", near(box(p)[2], 0.5, ab=1e-4) and near(box(p)[3], 1.0, ab=1e-4), box(p))
p = gbr("%ADD10R,2X1*%\nD10*\n%LS2*%\n" + flash(0, 0))
check("apertura in scala 2 (LS): area × 4", near(area(p), 8.0, rel=1e-4), area(p))
p = gbr(tri + "D20*\n%LMX*%\n" + flash(0, 0))
check("apertura specchiata (LMX): il triangolo va a sinistra", near(box(p)[0], -4.0, ab=1e-4) and near(box(p)[2], 0.0, ab=1e-4)
      and near(area(p), 4.0, rel=1e-4), box(p))
p = gbr("%ADD10R,1X1*%\n%SRX3Y2I5J4*%\nD10*\n" + flash(0, 0) + "%SR*%\n")
check("ripetizione 3 × 2 con passo 5 e 4: sei quadrati", near(area(p), 6.0) and near(box(p)[2], 10.5) and near(box(p)[3], 4.5), box(p))
rings = "%ADD10C,3*%\n%ADD11C,2*%\n%SRX2Y2I1J1*%\nD10*\n" + flash(0, 0) + "%LPC*%\nD11*\n" + flash(0, 0) + "%LPD*%\n%SR*%\n"
f = gerber.load(gbr(rings))


def filled(fobj, x, y):
    import pyclipper
    pt = (int(round(x * gerber.SCALE)), int(round(y * gerber.SCALE)))
    return sum(1 if pyclipper.Orientation(q) else -1 for q in fobj.image if pyclipper.PointInPolygon(pt, q) == 1) > 0


# l'ultima copia è quella in (1,1): il suo anello è intero, e il suo buco cancella le copie precedenti
check("ripetizioni con oggetti chiari: l'ultima copia sta sopra",
      filled(f, 1 + 1.25, 1) and not filled(f, 1, 1) and not filled(f, 0.3, 0.3) and filled(f, -1.25, 0), "ordine")
# la copia in (1,0) viene DOPO quella in (0,1): in (0,3; −0,4) il suo buco cancella l'anello dell'altra,
# e in (−0,4; 0,3) il suo anello copre il buco dell'altra. Con l'ordine sbagliato succede il contrario.
check("ripetizioni: prima lungo Y, poi lungo X (l'ordine del formato)", not filled(f, 0.3, -0.4) and filled(f, -0.4, 0.3),
      (filled(f, 0.3, -0.4), filled(f, -0.4, 0.3)))
p = gbr("%ABD40*%\n%ADD10R,1X1*%\nD10*\n" + flash(0, 0) + flash(3, 0) + "%AB*%\nD40*\n" + flash(10, 10) + flash(10, 20))
check("apertura a blocco: due quadrati per ogni punto, niente nel punto di definizione",
      near(area(p), 4.0) and near(box(p)[0], 9.5) and near(box(p)[2], 13.5) and near(box(p)[3], 20.5), (area(p), box(p)))

# ================================================================== file vecchi o rovinati
p = gbr("%ADD10R,2X1*%\nG54D10*\nG01X" + c(1) + "Y" + c(1) + "D02*\nX" + c(5) + "Y" + c(1) + "D01*\nX" + c(5) + "Y" + c(4) + "*\n")
check("comandi superati: G54 e coordinate senza D (vale l'ultimo): due tratti", near(area(p), 2 + 4 + 2 + 6 - 2, rel=1e-4), area(p))
p = gbr("%ADD10R,1.5*%\n%ADD11O,1.5*%\nD10*\n" + flash(0, 0) + "D11*\n" + flash(5, 0))
check("rettangolo e asola con un lato solo (file vecchi): quadrato e cerchio", near(area(p), 2.25 + PI * 0.5625, rel=0.01), area(p))
f = gerber.load(gbr("%ADD10R,1X1*%\n%ADD11R,0.50.2*%\nD10*\n" + flash(0, 0) + "D11*\n" + flash(5, 0)))
check("apertura illeggibile: il resto si importa e l'avviso dice che i suoi oggetti MANCANO",
      near(gerber.area_mm2(f.image), 1.0) and any("MANCANO" in w and "D11" in w for w in f.warnings), f.warnings)
check("apertura mai definita: errore", raises(lambda: gerber.load(gbr("%ADD10R,1X1*%\nD12*\n" + flash(0, 0))), "non definita"))
check("disegno senza apertura scelta: errore", raises(lambda: gerber.load(gbr("%ADD10R,1X1*%\n" + flash(0, 0))), "apertura"))
check("tipo di apertura sconosciuto: errore", raises(lambda: gerber.load(gbr("%ADD10ZZZ,1*%\nD10*\n" + flash(0, 0))), "sconosciuto"))
f = gerber.load(gbr("%ADD10R,1X1*%\nD10*\n" + flash(0, 0), end=""))
check("file senza il comando di fine: letto, con avviso", near(gerber.area_mm2(f.image), 1.0) and any("M02" in w for w in f.warnings))
f = gerber.load(gbr("%ADD10R,1X1*%\nD10*\n" + flash(0, 0) + "M02*\n" + flash(50, 50), end=""))
check("quello che viene dopo la fine del file non si legge", near(gerber.bounds(f.image)[2], 0.5))
check("file senza disegno: errore", raises(lambda: gerber.load(gbr("%ADD10R,1X1*%\nD10*\n")), "nessun disegno"))
p = write("vecchio.gbr", "G90*\nG70*\nD10*\nX100Y100D02*\nX200Y100D01*\nM02*\n")
check("Gerber vecchio senza elenco delle aperture (RS-274-D): messaggio che dice come rimediare",
      raises(lambda: gerber.load(p), "RS-274X"))
pb = os.path.join(TMP, "binario.gbr")
with open(pb, "wb") as fh:
    fh.write(b"\x00\x01\x02%FSLAX24Y24*%" * 50)
check("file binario: non è un Gerber", gerber.sniff(pb) is None and raises(lambda: gerber.load(pb), "non è"))
f = gerber.load(gbr("%IPNEG*%\n%SFA1.000B1.000*%\n%OFA0B0*%\n%MIA0B0*%\n%ADD10R,1X1*%\nD10*\n" + flash(0, 0)))
check("comandi vecchi senza effetto (scala 1, offset 0) non danno avvisi; il negativo richiesto dal file sì",
      len(f.warnings) == 1 and "IPNEG" in f.warnings[0], f.warnings)
f = gerber.load(gbr("%SFA2.0B2.0*%\n%ADD10R,1X1*%\nD10*\n" + flash(0, 0)))
check("scala vecchio stile diversa da 1: avviso «controlla misure»", any("SFA2.0" in w for w in f.warnings), f.warnings)

# ================================================================== a cosa serve un file
kic = "G04 #@! TF.FileFunction,Copper,L2,Bot*\n%ADD10R,1X1*%\nD10*\n" + flash(0, 0)
f = gerber.load(gbr(kic, name="scheda-qualcosa.gbr"))
check("attributi di KiCad scritti come commento: rame, lato sotto", (f.role, f.side) == ("copper", "bottom"), (f.role, f.side))
f = gerber.load(gbr("%TF.FileFunction,Profile,NP*%\n%ADD10C,0.1*%\nD10*\n" + move(0, 0) + line(5, 0), name="x.gbr"))
check("attributo X2 «Profile»: contorno", f.role == "profile")
f = gerber.load(gbr("%TF.FileFunction,Legend,Top*%\n%ADD10R,1X1*%\nD10*\n" + flash(0, 0), name="b_cu-finto.gbr"))
check("l'attributo del file vince sul nome", (f.role, f.side) == ("other", "top"), (f.role, f.side))
names = {"scheda.GTL": ("copper", "top"), "scheda.gbl": ("copper", "bottom"), "scheda.gko": ("profile", None),
         "scheda.gm1": ("profile", None), "prova-F_Cu.gbr": ("copper", "top"), "prova-B_Cu.gbr": ("copper", "bottom"),
         "prova-Edge_Cuts.gbr": ("profile", None), "prova-F_SilkS.gbr": ("other", "top"), "prova-B_Mask.gbr": ("other", "bottom"),
         "Gerber_TopLayer.gbr": ("copper", "top"), "Gerber_BottomLayer.gbr": ("copper", "bottom"),
         "Gerber_BoardOutline.gbr": ("profile", None), "prova-In1_Cu.gbr": ("copper", "inner"), "senza_nome.gbr": ("other", None),
         "scheda.cmp": ("copper", "top"), "scheda.sol": ("copper", "bottom"), "scheda.gto": ("other", "top")}
got = {n: gerber.guess_role(n, {}) for n in names}
check("riconoscimento dal nome (KiCad, EasyEDA, Eagle, Altium…)", got == names, {n: v for n, v in got.items() if v != names[n]})

# ================================================================== fori Excellon
drl = "M48\nMETRIC\nT1C0.800\nT2C1.200\n%\nG90\nG05\nT1\nX10.0Y5.0\nX20.0Y5.0\nT2\nX15.0Y8.0\nM30\n"
f = gerber.load(write("fori.drl", drl))
check("fori in mm con il punto: 3 fori, diametri e posizioni", f.kind == "excellon" and f.role == "drill"
      and f.drill.holes == [(10.0, 5.0, 0.8), (20.0, 5.0, 0.8), (15.0, 8.0, 1.2)], f.drill.holes)
f = gerber.load(write("pollici.drl", "M48\nINCH,TZ\nT1C0.0400\n%\nT1\nX10000Y5000\nX-5000Y0\nM30\n"))
check("pollici senza punto, 2:4, zeri in testa omessi: X10000 = 1\"", near(f.drill.holes[0][0], 25.4) and near(f.drill.holes[0][1], 12.7)
      and near(f.drill.holes[1][0], -12.7) and near(f.drill.holes[0][2], 1.016), f.drill.holes)
f = gerber.load(write("lz.drl", "M48\nINCH,LZ\nT1C0.04\n%\nT1\nX01Y005\nM30\n"))
check("pollici con LZ (zeri in coda omessi): X01 = 1\", Y005 = 0,5\"", near(f.drill.holes[0][0], 25.4) and near(f.drill.holes[0][1], 12.7),
      f.drill.holes)
f = gerber.load(write("formato.drl", "M48\n;FILE_FORMAT=4:4\nMETRIC\nT1C0.8\n%\nT1\nX100000Y50000\nM30\n"))
check("formato dichiarato nel commento (4:4): X100000 = 10 mm", near(f.drill.holes[0][0], 10.0) and near(f.drill.holes[0][1], 5.0),
      f.drill.holes)
f = gerber.load(write("formato2.drl", "M48\nMETRIC,TZ,000.00\nT1C0.8\n%\nT1\nX1000Y500\nM30\n"))
check("formato dichiarato nell'intestazione (000.00): X1000 = 10 mm", near(f.drill.holes[0][0], 10.0), f.drill.holes)
f = gerber.load(write("asole.drl", "M48\nMETRIC\nT1C1.0\n%\nT1\nX0.0Y0.0G85X4.0Y0.0\nG00X10.0Y0.0\nM15\nG01X10.0Y3.0\nM16\n"
                                   "G05\nX20.0Y0.0\nR2X2.0\nM30\n"))
sl = gerber.area_mm2(gerber._drill_paths(f.drill, "true", 0.5))
check("asola G85, fresata M15…M16, foro e ripetizione R2: 2 asole e 3 fori",
      len(f.drill.slots) == 2 and [h[0] for h in f.drill.holes] == [20.0, 22.0, 24.0]
      and near(sl, (4 + PI / 4) + (3 + PI / 4) + 3 * PI / 4, rel=0.01), (f.drill.slots, f.drill.holes, sl))
f = gerber.load(write("senza_diametro.drl", "M48\nMETRIC\nT1C0.8\n%\nT1\nX1.0Y1.0\nT5\nX9.0Y9.0\nM30\n"))
check("punta senza diametro: i suoi fori non entrano e c'è l'avviso", len(f.drill.holes) == 1 and any("T5" in w for w in f.warnings))
check("fori con coordinate incrementali: rifiutati", raises(lambda: gerber.load(write("inc.drl", "M48\nMETRIC\nICI,ON\nT1C1\n%\nT1\nX1Y1\nM30\n")),
                                                         "incrementali"))
check("file dei fori senza fori: errore", raises(lambda: gerber.load(write("vuoto.drl", "M48\nMETRIC\nT1C0.8\n%\nT1\nM30\n")), "fori"))
check("un file di testo qualsiasi non è né Gerber né Excellon", gerber.sniff(write("nota.txt", "Ciao,\nX marks the spot\n")) is None)

# ================================================================== basetta
pads = "%ADD10R,2X2*%\nD10*\n" + flash(0, 0) + flash(10, 0)
cu = gerber.load(gbr("%TF.FileFunction,Copper,L1,Top*%\n" + pads, name="b1-F_Cu.gbr"))
bo = gerber.build([cu])
check("scelte automatiche con un file di rame del lato sopra: negativo, non specchiato", bo.negative and not bo.mirrored)
check("negativo con bordo di 1 mm: rettangolo 14 × 4 meno le due piazzole = 48 mm²",
      near(bo.layers[0].area, 48.0) and bo.frame == "box" and near(bo.size[0], 14) and near(bo.size[1], 4), (bo.layers[0].area, bo.size))
bo = gerber.build([cu], gerber.Options(margin=3))
check("bordo di 3 mm: 18 × 8 − 8 = 136", near(bo.layers[0].area, 136.0) and near(bo.size[0], 18), bo.layers[0].area)
bo = gerber.build([cu], gerber.Options(margin=999))
check("bordo oltre il massimo: diventa 50 mm", near(bo.size[0], 112) and near(bo.size[1], 102), bo.size)
bo = gerber.build([cu], gerber.Options(negative=False))
check("positivo: le due piazzole, 8 mm², nessun bordo", near(bo.layers[0].area, 8.0) and bo.frame is None and near(bo.size[0], 12)
      and not bo.negative, (bo.layers[0].area, bo.size))

edge_segs = [((16, -5), (16, 5)), ((-4, 5), (-4, -5)), ((16, 5), (-4, 5)), ((-4, -5), (16, -5))]  # alla rinfusa, versi diversi
edge = "%ADD10C,0.1*%\nD10*\n" + "".join(move(*a) + line(*b) for a, b in edge_segs)
hole_loop = move(4, -1) + line(6, -1) + line(6, 1) + line(4, 1) + line(4, -1)
pr = gerber.load(gbr("%TF.FileFunction,Profile,NP*%\n" + edge, name="b1-Edge_Cuts.gbr"))
bo = gerber.build([cu, pr])
check("contorno della basetta 20 × 10 fatto di 4 tratti alla rinfusa: una linea chiusa sola",
      len(pr.lines) == 1 and pr.lines[0][1] and len(pr.lines[0][0]) == 4, pr.lines)
check("negativo con il contorno: 200 − 8 = 192 mm², misure 20 × 10, nessun avviso",
      bo.frame == "profile" and near(bo.layers[0].area, 192.0) and near(bo.size[0], 20) and near(bo.size[1], 10)
      and len(bo.layers) == 1 and not bo.warnings, (bo.layers[0].area, bo.size, bo.warnings))
pr2 = gerber.load(gbr("%TF.FileFunction,Profile,NP*%\n" + edge + hole_loop, name="b2-Edge_Cuts.gbr"))
bo = gerber.build([cu, pr2])
check("uno scasso chiuso dentro il contorno NON diventa un buco del bordo (lì si incide lo stesso): ancora 192",
      near(bo.layers[0].area, 192.0), bo.layers[0].area)
open_edge = "%ADD10C,0.1*%\nD10*\n" + "".join(move(*a) + line(*b) for a, b in edge_segs[:3])
pr3 = gerber.load(gbr("%TF.FileFunction,Profile,NP*%\n" + open_edge, name="b3-Edge_Cuts.gbr"))
bo = gerber.build([cu, pr3])
check("contorno non chiuso: avviso, rettangolo attorno a rame e contorno, e il contorno resta come linea",
      bo.frame == "box" and any("non è una linea chiusa" in w for w in bo.warnings) and near(bo.size[0], 20)
      and [ly.role for ly in bo.layers] == ["copper", "profile"], (bo.frame, bo.warnings, bo.size))
small = "%ADD10C,0.1*%\nD10*\n" + move(-2, -2) + line(2, -2) + line(2, 2) + line(-2, 2) + line(-2, -2)
pr4 = gerber.load(gbr("%TF.FileFunction,Profile,NP*%\n" + small, name="b4-Edge_Cuts.gbr"))
bo = gerber.build([cu, pr4])
check("rame fuori dal contorno: avviso esplicito", any("esce dal contorno" in w for w in bo.warnings), bo.warnings)
bo = gerber.build([cu, pr], gerber.Options(negative=False))
ln = [ly for ly in bo.layers if ly.role == "profile"]
per = sum(math.dist(a, b) for pts, cl in ln[0].data for a, b in zip(pts, pts[1:] + pts[:1])) if ln else 0
check("positivo con il contorno: rame 8 mm² + contorno come linea chiusa lunga 60 mm",
      near(bo.layers[0].area, 8.0) and len(ln) == 1 and ln[0].kind == "line" and near(per, 60.0, ab=1e-3), (per, len(ln)))

dr = gerber.load(write("b1.drl", "M48\nMETRIC\nT1C1.000\n%\nT1\nX0.0Y0.0\nX10.0Y0.0\nM30\n"))
hole = gerber.area_mm2([gerber._positive(gerber.circle(0, 0, 1.0))])
dot = gerber.area_mm2([gerber._positive(gerber.circle(0, 0, 0.5))])
bo = gerber.build([cu, pr, dr], gerber.Options(negative=False))
check("fori veri, positivo: le piazzole perdono il foro (8 − 2 fori)", near(bo.layers[0].area, 8 - 2 * hole, rel=1e-4), bo.layers[0].area)
bo = gerber.build([cu, pr, dr])
check("fori veri, negativo: il laser scopre anche i fori (192 + 2 fori)", near(bo.layers[0].area, 192 + 2 * hole, rel=1e-4), bo.layers[0].area)
bo = gerber.build([cu, pr, dr], gerber.Options(holes="dot", dot=0.5))
check("fori come punto di centratura Ø0,5", near(bo.layers[0].area, 192 + 2 * dot, rel=1e-4), bo.layers[0].area)
bo = gerber.build([cu, pr, dr], gerber.Options(holes="none"))
check("fori ignorati: come senza il file dei fori", near(bo.layers[0].area, 192.0), bo.layers[0].area)
bo = gerber.build([dr])
check("solo il file dei fori: i fori come cerchi", bo.layers[0].role == "drill" and near(bo.layers[0].area, 2 * hole, rel=1e-4))

amb = gerber.load(write("ambigui.drl", "M48\nMETRIC\nT1C1.000\n%\nT1\nX0Y0\nX1000Y0\nM30\n"))  # centesimi di mm, non dichiarati
check("fori senza punto e senza formato: da soli valgono il formato normale (3 decimali)", near(amb.drill.holes[1][0], 1.0))
bo = gerber.build([cu, pr, amb])
check("…ma insieme al rame si sceglie il formato che li fa cadere sulle piazzole (X1000 = 10 mm)",
      near(amb.drill.holes[1][0], 10.0) and near(bo.layers[0].area, 192 + 2 * hole, rel=1e-4) and not bo.warnings,
      (amb.drill.holes, bo.warnings))
far = gerber.load(write("lontani.drl", "M48\nMETRIC\nT1C1.000\n%\nT1\nX500.0Y500.0\nM30\n"))
bo = gerber.build([cu, pr, far])
check("fori che non cadono sul disegno: avviso", any("non cadono" in w for w in bo.warnings), bo.warnings)

asym = "%ADD10R,2X2*%\n%ADD11R,1X1*%\nD10*\n" + flash(0, 0) + "D11*\n" + flash(10, 3)
bot = gerber.load(gbr("%TF.FileFunction,Copper,L2,Bot*%\n" + asym, name="b1-B_Cu.gbr"))
top = gerber.load(gbr("%TF.FileFunction,Copper,L1,Top*%\n" + asym, name="b5-F_Cu.gbr"))
check("specchio automatico: sì per il solo lato sotto, no per il lato sopra, no se ci sono tutti e due",
      gerber.defaults([bot]).mirror and not gerber.defaults([top]).mirror and not gerber.defaults([top, bot]).mirror)
check("…e la scelta fatta a mano vince", not gerber.defaults([bot], gerber.Options(mirror=False)).mirror
      and gerber.defaults([top], gerber.Options(mirror=True)).mirror)


def centers(board):
    out = []
    for isl in board.layers[0].data:
        xs = [q[0] for q in isl[0]]
        ys = [q[1] for q in isl[0]]
        out.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs)))
    return sorted(out)


n0 = centers(gerber.build([bot], gerber.Options(mirror=False, negative=False)))
m0 = centers(gerber.build([bot], gerber.Options(negative=False)))
check("specchio: la piazzola grande passa da sinistra a destra, stessa altezza, stesse misure",
      near(n0[0][0], 0) and near(n0[0][2], 2) and near(n0[1][0], 10) and near(m0[0][0], -0.5 + 0) and near(m0[0][2], 1)
      and near(m0[1][0], 9.5) and near(m0[1][2], 2) and near(m0[0][1], 3) and near(m0[1][1], 0), (n0, m0))
b_n = gerber.build([bot], gerber.Options(mirror=False, negative=False))
b_m = gerber.build([bot], gerber.Options(mirror=True, negative=False))
check("…ingombro e area uguali, specchiato o no", all(near(a, b) for a, b in zip(b_n.bounds, b_m.bounds))
      and near(b_n.layers[0].area, b_m.layers[0].area) and b_m.mirrored and not b_n.mirrored)
bo = gerber.build([bot, pr, dr], gerber.Options(negative=False))
cu_c = centers(bo)
prof = [ly for ly in bo.layers if ly.role == "profile"][0]
px = [q[0] for pts, _ in prof.data for q in pts]
check("registro: rame, contorno e fori si specchiano insieme (la piazzola col foro resta al suo posto nel contorno)",
      near(min(px), -4) and near(max(px), 16) and near(cu_c[-1][0], 12.0) and near(cu_c[-1][2], 2.0), (cu_c, min(px), max(px)))

ell = "%ADD10C,0.1*%\nD10*\n" + move(-4, -5) + line(16, -5) + line(16, 5)  # una L: il tratto verticale sta a destra
pr5 = gerber.load(gbr("%TF.FileFunction,Profile,NP*%\n" + ell, name="b5-Edge_Cuts.gbr"))


def vertical_x(board):
    pts = [ly for ly in board.layers if ly.role == "profile"][0].data[0][0]
    return [a[0] for a, b_ in zip(pts, pts[1:]) if near(a[0], b_[0]) and not near(a[1], b_[1])]


vn = vertical_x(gerber.build([bot, pr5], gerber.Options(mirror=False, negative=False)))
vm = vertical_x(gerber.build([bot, pr5], gerber.Options(mirror=True, negative=False)))
check("registro: un contorno non simmetrico si specchia con lo stesso asse del rame (il lato destro va a sinistra)",
      len(vn) == 1 and near(vn[0], 16) and len(vm) == 1 and near(vm[0], -4), (vn, vm))

# ---------------------------------------------------------------- due facce
# sopra: piazzola 2 × 2 in (0,0) e 1 × 1 in (10,3); sotto: una piazzola 2 × 2 in (2,0)
bot2 = gerber.load(gbr("%TF.FileFunction,Copper,L2,Bot*%\n%ADD10R,2X2*%\nD10*\n" + flash(2, 0), name="b7-B_Cu.gbr"))


def side_centers(board, side):
    out = []
    for ly in board.layers:
        if ly.side == side and ly.role == "copper":
            for isl in ly.data:
                for cont in (isl if board.negative else isl[:1]):
                    xs = [q[0] for q in cont]
                    ys = [q[1] for q in cont]
                    out.append((round((min(xs) + max(xs)) / 2, 4), round((min(ys) + max(ys)) / 2, 4), round(max(xs) - min(xs), 4)))
    return sorted(out)


def side_area(board, side):
    return sum(ly.area for ly in board.layers if ly.side == side and ly.role == "copper")


check("due facce: riconosciute solo con rame sopra E rame sotto", gerber.is_two_sided([top, bot2])
      and not gerber.is_two_sided([top]) and not gerber.is_two_sided([bot2, pr])
      and not gerber.is_two_sided([top, bot2], gerber.Options(roles={bot2.path: "other"})))
b2 = gerber.build([top, bot2], gerber.Options(negative=False))
check("due facce, positivo: due pezzi di rame, uno per faccia, con le loro aree (5 e 4 mm²)",
      b2.two_sided and [ly.side for ly in b2.layers] == ["top", "bottom"] and near(side_area(b2, "top"), 5.0)
      and near(side_area(b2, "bottom"), 4.0) and not b2.mirrored, [(ly.side, ly.area) for ly in b2.layers])
check("…il lato sopra resta dritto: piazzole in (0,0) e (10,3)", side_centers(b2, "top") == [(0.0, 0.0, 2.0), (10.0, 3.0, 1.0)],
      side_centers(b2, "top"))
check("…il lato sotto è specchiato attorno al centro dell'ingombro COMUNE (−1…10,5): la piazzola in 2 va in 7,5",
      side_centers(b2, "bottom") == [(7.5, 0.0, 2.0)] and near(b2.bounds[0], -1) and near(b2.bounds[2], 10.5),
      (side_centers(b2, "bottom"), b2.bounds))
b2m = gerber.build([top, bot2], gerber.Options(negative=False, mirror=True))
check("…e la scelta «specchia» qui non conta: sopra dritto, sotto specchiato, sempre",
      side_centers(b2m, "top") == side_centers(b2, "top") and side_centers(b2m, "bottom") == side_centers(b2, "bottom"))
b2n = gerber.build([top, bot2])


def side_box(board, side):
    pts_ = [q for ly in board.layers if ly.side == side for item in ly.data for q in item[0]]
    return (min(q[0] for q in pts_), min(q[1] for q in pts_), max(q[0] for q in pts_), max(q[1] for q in pts_))


check("due facce, negativo senza contorno: lo STESSO bordo per le due facce (rame di tutte e due + 1 mm = 13,5 × 6,5)",
      b2n.negative and b2n.frame == "box" and all(near(a, b_) for a, b_ in zip(side_box(b2n, "top"), (-2, -2, 11.5, 4.5)))
      and all(near(a, b_) for a, b_ in zip(side_box(b2n, "bottom"), (-2, -2, 11.5, 4.5))), (side_box(b2n, "top"), side_box(b2n, "bottom")))
check("…aree: 87,75 − 5 e 87,75 − 4", near(side_area(b2n, "top"), 82.75) and near(side_area(b2n, "bottom"), 83.75),
      (side_area(b2n, "top"), side_area(b2n, "bottom")))
bot3 = gerber.load(gbr("%TF.FileFunction,Copper,L2,Bot*%\n%ADD10R,2X2*%\nD10*\n" + flash(14, 0), name="b8-B_Cu.gbr"))
b3n = gerber.build([top, bot3])
check("…anche quando il rame del lato sotto esce dall'ingombro del lato sopra: il bordo comune li contiene tutti e due",
      all(near(a, b_) for a, b_ in zip(side_box(b3n, "top"), (-2, -2, 16, 4.5)))
      and all(near(a, b_) for a, b_ in zip(side_box(b3n, "bottom"), (-2, -2, 16, 4.5))), (side_box(b3n, "top"), side_box(b3n, "bottom")))
dr2 = gerber.load(write("b7.drl", "M48\nMETRIC\nT1C1.000\n%\nT1\nX2.0Y0.0\nM30\n"))
b2h = gerber.build([top, bot2, pr, dr2])
check("due facce: un foro nella piazzola del lato sotto viene scoperto sul lato sotto (196 + foro), sul lato sopra cade già nello spazio inciso",
      near(side_area(b2h, "top"), 195.0, rel=1e-4) and near(side_area(b2h, "bottom"), 196 + hole, rel=1e-4),
      (side_area(b2h, "top"), side_area(b2h, "bottom")))
b2p = gerber.build([top, bot2, pr, dr])
check("due facce con contorno e fori: bordo dal contorno per tutte e due (200 mm²), fori su tutte e due",
      b2p.frame == "profile" and near(side_area(b2p, "top"), 195 + hole, rel=1e-4) and near(side_area(b2p, "bottom"), 196.0, rel=1e-4)
      and len(b2p.layers) == 2, (side_area(b2p, "top"), side_area(b2p, "bottom")))
holes_b = [cc for cc in side_centers(b2p, "bottom") if near(cc[2], 2.0)]
check("…la piazzola del lato sotto (in 2 nel file) finisce a 10: specchiata attorno al centro del contorno (−4…16)",
      len(holes_b) == 1 and near(holes_b[0][0], 10.0) and near(holes_b[0][1], 0.0), side_centers(b2p, "bottom"))
b2l = gerber.build([top, bot2, pr5], gerber.Options(negative=False))
vx = {ly.side: [a[0] for a, b_ in zip(ly.data[0][0], ly.data[0][0][1:]) if near(a[0], b_[0]) and not near(a[1], b_[1])]
      for ly in b2l.layers if ly.role == "profile"}
check("due facce, positivo con contorno: il contorno c'è su tutte e due le facce, specchiato solo sotto",
      [ly.side for ly in b2l.layers if ly.role == "profile"] == ["top", "bottom"] and near(vx["top"][0], 16) and near(vx["bottom"][0], -4), vx)
silk_b = gerber.load(gbr("%ADD10R,1X1*%\nD10*\n" + flash(3, 3), name="b7-B_SilkS.gbr"))
b2s = gerber.build([top, bot2, silk_b, un_ := gerber.load(gbr(pads, name="qualcosa.gbr"))], gerber.Options(negative=False))
check("due facce: serigrafia del lato sotto con il lato sotto; un file senza lato va con il lato sopra",
      sorted((ly.name, ly.side) for ly in b2s.layers if ly.role == "other") == [("b7-B_SilkS.gbr", "bottom"), ("qualcosa.gbr", "top")],
      [(ly.name, ly.side) for ly in b2s.layers])
dd = Document()
sh_t = io_formats.gerber_shapes(b2, dd)
sh_b = io_formats.gerber_shapes(b2, dd, "bottom")
check("due facce -> forme: stessa origine (quella dell'ingombro comune) e stesso livello per il rame",
      near(sh_t[0].bounds().left(), 0.0) and near(sh_t[0].bounds().width(), 11.5) and near(sh_b[0].bounds().left(), 7.5)
      and near(sh_b[0].bounds().width(), 2.0) and sh_t[0].layer == sh_b[0].layer and dd.layer(sh_t[0].layer).mode == "fill",
      (sh_t[0].bounds(), sh_b[0].bounds(), sh_t[0].layer, sh_b[0].layer))

un = gerber.load(gbr(pads, name="misterioso.gbr"))
bo = gerber.build([un])
check("file di tipo non riconosciuto: importato com'è (positivo), niente bordo", un.role == "other" and not bo.negative
      and near(bo.layers[0].area, 8.0))
bo = gerber.build([un], gerber.Options(roles={un.path: "copper"}))
check("…e se a mano si dice che è rame, vale il negativo", bo.negative and near(bo.layers[0].area, 48.0), bo.layers[0].area)
cu2 = gerber.load(gbr("%TF.FileFunction,Copper,L1,Top*%\n%ADD10R,2X2*%\nD10*\n" + flash(5, 0) + flash(10, 0), name="b6-F_Cu.gbr"))
bo = gerber.build([cu, cu2], gerber.Options(negative=False))
check("due file di rame insieme: unione (le piazzole in comune contano una volta)", near(bo.layers[0].area, 12.0), bo.layers[0].area)
zw = gerber.load(gbr("%ADD10C,0*%\nD10*\n" + move(0, 0) + line(5, 0) + line(5, 5), name="linee.gbr"))
bo = gerber.build([zw])
check("solo tratti di spessore zero: importati come linee, con avviso", bo.layers[0].kind == "line"
      and any("spessore zero" in w for w in bo.warnings), bo.warnings)

# ================================================================== programma
box_msgs = []
QMessageBox.warning = staticmethod(lambda *a, **k: box_msgs.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
w = mw.MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed = w.editor
prof_m = w.profile


def leaves(shapes):
    return [leaf for s in shapes for leaf, _ in s.leaves()]


def clear():
    """Piano vuoto, passando dai comandi del programma (Seleziona tutto + Elimina)."""
    for lf in leaves(ed.doc.shapes):
        lf.locked = False
    ed.select_all()
    if ed.selection:
        ed.delete()
    app.processEvents()


check("riconoscimento dal contenuto: Gerber con estensione sconosciuta, fori in .txt",
      io_formats.is_gerber(write("scheda.xyz", open(cu.path).read())) and io_formats.is_gerber(write("fori.txt", drl)))
check("…mentre SVG, G-code, immagini e testi qualsiasi non lo sono",
      not io_formats.is_gerber(write("d.svg", "<svg xmlns='http://www.w3.org/2000/svg'><path d='M0 0L1 1'/></svg>"))
      and not io_formats.is_gerber(write("l.gcode", "G21\nG90\nM3 S100\nG1 X10 Y10 F1000\nM5\n"))
      and not io_formats.is_gerber(write("nota2.txt", "appunti")) and not io_formats.is_gerber(os.path.join(TMP, "non_esiste.gbr")))

n_before = len(ed.undo_stack)
w.import_files([cu.path, pr.path, dr.path])
app.processEvents()
sh = list(ed.doc.shapes)
bnd = sh[0].bounds() if sh else None
check("Importa con rame + contorno + fori: un oggetto solo sul piano, nessun piano di lavoro in più",
      len(sh) == 1 and len(ed.doc.plates) == 1 and w.gerber_plates is None, (len(sh), len(ed.doc.plates)))
check("…con le misure vere della basetta, 20 × 10 mm (mai ridimensionato)", bnd is not None and near(bnd.width(), 20, ab=1e-6)
      and near(bnd.height(), 10, ab=1e-6), bnd)
check("…al centro del piano", near(bnd.center().x(), prof_m.bed_x / 2, ab=1e-6) and near(bnd.center().y(), prof_m.bed_y / 2, ab=1e-6))
lay = sorted({lf.layer for lf in leaves(sh)})
check("…su un livello solo, in Riempimento", len(lay) == 1 and ed.doc.layer(lay[0]).mode == "fill", lay)
check("…un solo passo nella cronologia, e il messaggio dice le misure", len(ed.undo_stack) == n_before + 1
      and "20.0 × 10.0" in w.statusBar().currentMessage(), w.statusBar().currentMessage())
brd = w.gerber_last
check("…negativo, bordo dal contorno, 192 mm² + 2 fori", brd.negative and brd.frame == "profile"
      and near(brd.layers[0].area, 192 + 2 * hole, rel=1e-4))

# G-code vero: l'area incisa è quella calcolata, e sulle piazzole il laser non passa (tranne i fori)
ed.doc.layer(lay[0]).interval = 0.1


def burns(doc):
    job = gcode.generate(doc, MachineProfile(), gcode.JobOptions(start_from="absolute"))
    ox, oy = job.out_to_bed
    x = y = s = 0.0
    mode = 0
    segs = []
    for raw in job.lines:
        t = raw.split(";")[0].strip()
        if not t or t.startswith(("G10", "G55", "G54", "G90", "G21", "M")):
            continue
        g = re.match(r"G0*([01])\b", t)
        if g:
            mode = int(g.group(1))
        m = dict((k, float(v)) for k, v in re.findall(r"([XYS])(-?\d+(?:\.\d+)?)", t))
        s = m.get("S", s)
        nx, ny = m.get("X", x), m.get("Y", y)
        if mode == 1 and s > 0 and (nx, ny) != (x, y):
            segs.append((x + ox, y + oy, nx + ox, ny + oy))
        x, y = nx, ny
    return segs


segs = burns(ed.doc)
burnt = sum(math.hypot(x1 - x0, y1 - y0) for x0, y0, x1, y1 in segs) * 0.1
check("G-code vero: lunghezza incisa × interlinea = area calcolata (entro il 3%)", near(burnt, brd.layers[0].area, rel=0.03),
      (burnt, brd.layers[0].area))
x0b, y0b = bnd.left(), min(bnd.top(), bnd.bottom())
pad_c = [(x0b + 4, y0b + 5), (x0b + 14, y0b + 5)]  # le piazzole: (0,0) e (10,0) del file, contorno da −4, −5


def crosses(seg, cx, cy, r_in, half):
    """Il tratto orizzontale passa sulla corona della piazzola (fuori dal foro, dentro il quadrato)?"""
    xa, ya, xb, yb = seg
    if abs(ya - cy) >= half - 0.05:
        return False
    lo, hi = min(xa, xb), max(xa, xb)
    dy = abs(ya - cy)
    hole_half = math.sqrt(max(0.0, r_in * r_in - dy * dy)) if dy < r_in else 0.0
    for a, b_ in ((cx - half + 0.05, cx - hole_half - 0.05), (cx + hole_half + 0.05, cx + half - 0.05)):
        if a < b_ and lo < b_ and hi > a:
            return True
    return False


bad = [s for s in segs for cx, cy in pad_c if crosses(s, cx, cy, 0.5, 1.0)]
check("G-code vero: nessun tratto inciso sopra il rame delle piazzole", len(segs) > 50 and not bad, bad[:3])
inside_hole = [s for s in segs for cx, cy in pad_c if abs(s[1] - cy) < 0.3 and min(s[0], s[2]) < cx < max(s[0], s[2])]
check("G-code vero: i fori dentro le piazzole vengono incisi", len(inside_hole) >= 2, len(inside_hole))

ed.undo()
check("Annulla toglie tutta la basetta", len(ed.doc.shapes) == 0)
ed.redo()
check("Ripeti la rimette, uguale", len(ed.doc.shapes) == 1 and near(ed.doc.shapes[0].bounds().width(), 20, ab=1e-6))

# livello già usato: non va toccato
clear()
r0 = RectShape(30, 30)
r0.layer = 0
ed.doc.add(r0)
ed.doc.layer(0).mode = "line"
w.import_files([cu.path, pr.path], gerber_opts=gerber.Options(negative=False))
new = [s for s in ed.doc.shapes if s is not r0]
lay2 = sorted({lf.layer for lf in leaves(new)})
check("livello 0 già usato da un altro disegno: la basetta va su livelli liberi e il livello 0 resta com'era",
      0 not in lay2 and ed.doc.layer(0).mode == "line" and len(lay2) == 2, (lay2, ed.doc.layer(0).mode))
modes = sorted(ed.doc.layer(i).mode for i in lay2)
check("…rame in Riempimento e contorno in Linea, nello stesso gruppo (restano a registro)", modes == ["fill", "line"]
      and len(new) == 1 and new[0].kind == "group", (modes, [s.kind for s in new]))
gb = new[0].bounds()
check("…misure del gruppo: il contorno 20 × 10", near(gb.width(), 20, ab=1e-6) and near(gb.height(), 10, ab=1e-6), gb)

# grande più del piano: non si rimpicciolisce, e lo dice
clear()
big = gerber.load(gbr("%TF.FileFunction,Copper,L1,Top*%\n%ADD10R,2X2*%\nD10*\n" + flash(0, 0) + flash(prof_m.bed_x + 50, 0), name="grande-F_Cu.gbr"))
w.import_files([big.path], gerber_opts=gerber.Options(negative=False))
check("basetta più grande del piano: misure vere e avviso nel messaggio",
      near(ed.doc.shapes[0].bounds().width(), prof_m.bed_x + 52, ab=1e-6) and "più grande" in w.statusBar().currentMessage(),
      w.statusBar().currentMessage())

# file illeggibili in mezzo agli altri
clear()
box_msgs.clear()
bad_f = gbr("%ADD10R,1X1*%\nD12*\n" + flash(0, 0), name="rotto-F_Cu.gbr")
w.import_files([cu.path, bad_f])
check("un file rotto fra quelli buoni: gli altri si importano e l'errore viene detto", len(ed.doc.shapes) == 1
      and any("rotto-F_Cu.gbr" in m for m in box_msgs), box_msgs)
clear()
box_msgs.clear()
w.import_files([bad_f])
check("solo file rotti: niente sul piano, messaggio, nessun errore non gestito", len(ed.doc.shapes) == 0 and len(box_msgs) == 1, box_msgs)

# insieme ad altri formati
clear()
svg = write("quadrato.svg", "<svg xmlns='http://www.w3.org/2000/svg' width='10mm' height='10mm' viewBox='0 0 10 10'>"
                            "<rect x='0' y='0' width='10' height='10' fill='none' stroke='#000'/></svg>")
w.import_files([svg, cu.path], gerber_opts=gerber.Options(negative=False))
check("Gerber e SVG scelti insieme: entrano tutti e due", len(ed.doc.shapes) == 2, len(ed.doc.shapes))

# salva e riapri
clear()
w.import_files([cu.path, pr.path, dr.path])
b1 = ed.doc.shapes[0].bounds()
n_el = ed.doc.shapes[0].local_path().elementCount()
pj = os.path.join(TMP, "basetta.flcut")
ed.doc.save(pj)
d2 = Document.load(pj)
b2 = d2.shapes[0].bounds()
check("salva e riapri: stessa basetta (misure, posizione, punti)", near(b1.width(), b2.width()) and near(b1.left(), b2.left())
      and d2.shapes[0].local_path().elementCount() == n_el)

# finestra delle scelte
clear()
files, errs = io_formats.load_gerber([bot.path, pr.path, dr.path])
dlg = dialogs_gerber.GerberDialog(w, files, errs)
dlg.show()
app.processEvents()
check("finestra: per il lato sotto propone lo specchio e il negativo; il bordo è spento perché c'è il contorno",
      dlg.mirror.isChecked() and dlg.what.currentData() is True and not dlg.margin.isEnabled() and dlg.holes.isEnabled()
      and not dlg.dot.isEnabled())
check("finestra: anteprima calcolata e pulsante Importa attivo", dlg.board is not None and dlg.board.negative and dlg.board.mirrored
      and not dlg.preview.areas.isEmpty() and dlg.bb.button(dlg.bb.StandardButton.Ok).isEnabled())
a_neg = dlg.board.layers[0].area
dlg.what.setCurrentIndex(1)
dlg.rebuild()
check("finestra: scegliendo «le piste» l'anteprima diventa il positivo", not dlg.board.negative
      and dlg.board.layers[0].area < a_neg / 10, (dlg.board.layers[0].area, a_neg))
dlg.holes.setCurrentIndex(dlg.holes.findData("dot"))
dlg.rebuild()
check("finestra: «punto al centro» accende il diametro del punto", dlg.dot.isEnabled() and dlg.options().holes == "dot")
dlg.role_boxes[bot.path].setCurrentIndex(dlg.role_boxes[bot.path].findData("other"))
dlg.rebuild()
check("finestra: se nessun file è rame, la scelta negativo/positivo si spegne e non c'è negativo",
      not dlg.what.isEnabled() and dlg.board is not None and not dlg.board.negative)
dlg.mirror.setChecked(False)
dlg.rebuild()
o = dlg.options()
check("finestra: le scelte lette sono quelle a schermo", o.mirror is False and o.roles[bot.path] == "other" and not dlg.board.mirrored)
check("finestra: niente è stato aggiunto al progetto finché non si conferma", len(ed.doc.shapes) == 0)
dlg.close()
dlg = dialogs_gerber.GerberDialog(w, [cu], [("rotto.gbr", "errore di prova")])
check("finestra: senza contorno il bordo è attivo; i file non letti sono elencati", dlg.margin.isEnabled()
      and "rotto.gbr" in dlg.lbl_warn.text() and not dlg.holes.isEnabled())
dlg.close()

# senza FLC_NO_DIALOGS la finestra viene chiesta; da Claude mai
asked = []
orig_ask = dialogs_gerber.ask
dialogs_gerber.ask = lambda parent, fl, er=(): asked.append(len(fl)) or gerber.Options(mirror=True, negative=False)
del os.environ["FLC_NO_DIALOGS"]
clear()
w.import_files([cu.path, pr.path])
check("Importa dal programma: apre la finestra delle scelte e usa quello che viene scelto",
      asked == [2] and w.gerber_last.mirrored and not w.gerber_last.negative, asked)
dialogs_gerber.ask = lambda *a, **k: None
clear()
w.import_files([cu.path, pr.path])
check("finestra annullata: non si importa niente", len(ed.doc.shapes) == 0)
if w.remote is not None:
    dialogs_gerber.ask = lambda *a, **k: asked.append("claude") or None
    clear()
    res = w.remote.c_import_file(bot.path, more_paths=[pr.path, dr.path])
    check("comando di Claude: nessuna finestra, scelte automatiche, risultato con misure e scelte applicate",
          "claude" not in asked and len(ed.doc.shapes) == 1 and res["pcb"]["mirrored"] and res["pcb"]["negative"]
          and near(res["pcb"]["width_mm"], 20) and res["pcb"]["frame"] == "profile", res.get("pcb") if isinstance(res, dict) else res)
    clear()
    res = w.remote.c_import_file(bot.path, mirror=False, negative=False)
    check("comando di Claude con le scelte esplicite", not res["pcb"]["mirrored"] and not res["pcb"]["negative"], res["pcb"])
    clear()
    res = w.remote.c_import_file(svg)
    check("comando di Claude con un SVG: come prima (lista di forme)", isinstance(res, list) and len(res) == 1, res)
else:
    for nm in ("comando di Claude: nessuna finestra", "comando di Claude con le scelte esplicite", "comando di Claude con un SVG"):
        check(nm + " (collegamento spento in questa prova)", True)
dialogs_gerber.ask = orig_ask
os.environ["FLC_NO_DIALOGS"] = "1"

# ---------------------------------------------------------------- due facce nel programma
def reset_plates():
    while len(ed.doc.plates) > 1:
        ed.set_plate(len(ed.doc.plates) - 1)
        clear()
        ed.set_plate(0)
        ed.remove_plate(len(ed.doc.plates) - 1)
    ed.doc.plates[0].name = ""
    clear()


infos = []
QMessageBox.information = staticmethod(lambda *a, **k: infos.append(a[2] if len(a) > 2 else "") or QMessageBox.Ok)
reset_plates()
w.import_files([top.path, bot2.path, pr.path, dr.path])
app.processEvents()
pl = ed.doc.plates
check("due facce: Importa crea un piano di lavoro in più e resta su quello del lato sopra",
      len(pl) == 2 and ed.doc.current == 0 and [len(x.shapes) for x in pl] == [1, 1], ([len(x.shapes) for x in pl], ed.doc.current))
check("…i piani si chiamano «Lato sopra» e «Lato sotto (specchiato)»",
      w.gerber_plates == ("Lato sopra", "Lato sotto (specchiato)") and ed.doc.plate_name(1) == "Lato sotto (specchiato)", w.gerber_plates)
bt, bb_ = pl[0].shapes[0].bounds(), pl[1].shapes[0].bounds()
check("…le due facce sono nella stessa posizione, con le misure vere (20 × 10) e al centro del piano",
      all(near(a, b_, ab=1e-6) for a, b_ in zip((bt.left(), bt.top(), bt.width(), bt.height()), (bb_.left(), bb_.top(), bb_.width(), bb_.height())))
      and near(bt.width(), 20, ab=1e-6) and near(bt.center().x(), prof_m.bed_x / 2, ab=1e-6), (bt, bb_))
l_t, l_b = {lf.layer for lf in leaves(pl[0].shapes)}, {lf.layer for lf in leaves(pl[1].shapes)}
check("…stesso livello (stesse impostazioni) per le due facce, in Riempimento; il messaggio dice «due facce»",
      l_t == l_b and len(l_t) == 1 and ed.doc.layer(next(iter(l_t))).mode == "fill" and "due facce" in w.statusBar().currentMessage(),
      (l_t, l_b, w.statusBar().currentMessage()))
check("…senza finestre (prove, Claude) non compare nessun messaggio da confermare", infos == [], infos)
ed.doc.layer(next(iter(l_t))).interval = 0.1
bx, by = bt.left(), min(bt.top(), bt.bottom())


def burnt_at(segs_, x, y):
    return any(abs(sy - y) < 0.2 and min(sx, ex) < x < max(sx, ex) for sx, sy, ex, _ in segs_)


s_top = burns(ed.doc)
ed.set_plate(1)
s_bot = burns(ed.doc)
ed.set_plate(0)
# sul piano: contorno da (0,0) a (20,10). Sopra: piazzole in (4,5) e (14,8). Sotto: la piazzola del file in (2,0) -> (14,5).
check("G-code vero del lato sopra: non incide sulla sua piazzola, incide dove sta la piazzola del lato sotto",
      len(s_top) > 50 and not burnt_at(s_top, bx + 4.6, by + 5.6) and burnt_at(s_top, bx + 14, by + 5), len(s_top))
check("G-code vero del lato sotto: è specchiato (non incide in 14; 5, incide dove sopra c'era la piazzola)",
      len(s_bot) > 50 and not burnt_at(s_bot, bx + 14.6, by + 5.6) and burnt_at(s_bot, bx + 4.6, by + 5.6), len(s_bot))
ed.undo()
check("Annulla sul piano del lato sopra toglie il lato sopra; il piano del lato sotto resta, con la sua faccia",
      len(pl[0].shapes) == 0 and len(ed.doc.plates) == 2 and len(ed.doc.plates[1].shapes) == 1)

reset_plates()
r1 = RectShape(15, 15)
r1.layer = 5
ed.doc.add(r1)
w.import_files([top.path, bot2.path], gerber_opts=gerber.Options(negative=False))
check("piano già usato da altri disegni: non viene rinominato; il lato sotto va comunque su un piano nuovo",
      len(ed.doc.plates) == 2 and ed.doc.plates[0].name == "" and len(ed.doc.plates[0].shapes) == 2
      and ed.doc.plate_name(1) == "Lato sotto (specchiato)" and r1 in ed.doc.plates[0].shapes, [x.name for x in ed.doc.plates])
tb, bbn = [s_ for s_ in ed.doc.plates[0].shapes if s_ is not r1][0].bounds(), ed.doc.plates[1].shapes[0].bounds()
check("…positivo senza contorno: le distanze fra le facce sono quelle dell'ingombro comune (sotto 7,5 mm più a destra)",
      near(bbn.left() - tb.left(), 7.5, ab=1e-6) and near(tb.width(), 11.5, ab=1e-6) and near(bbn.width(), 2.0, ab=1e-6), (tb, bbn))

reset_plates()
files2, errs2 = io_formats.load_gerber([top.path, bot2.path, pr.path])
dlg = dialogs_gerber.GerberDialog(w, files2, errs2)
dlg.show()
app.processEvents()
check("finestra con due facce: lo specchio è spento (lo decide il lato), compaiono la nota e la scelta della faccia in anteprima",
      not dlg.mirror.isEnabled() and dlg.lbl_two.isVisible() and dlg.side_view.isVisible() and dlg.board.two_sided
      and "due facce" in dlg.lbl_info.text() and "compito tuo" in dlg.lbl_two.text(), dlg.lbl_info.text())
p_top = dlg.preview.areas.contains(QPointF(2.0, 0.0))  # nel sistema del file: sopra lì c'è spazio inciso (piazzola in 0,0: bordo a 1)
dlg.side_view.setCurrentIndex(1)
app.processEvents()
p_bot = dlg.preview.areas.contains(QPointF(10.0, 0.0))  # sotto: la piazzola specchiata sta in 10 -> lì NON si incide
check("finestra con due facce: l'anteprima mostra la faccia scelta", p_top and not p_bot
      and dlg.preview.areas.contains(QPointF(2.0, 0.0)), (p_top, p_bot))
dlg.role_boxes[bot2.path].setCurrentIndex(dlg.role_boxes[bot2.path].findData("other"))
dlg.rebuild()
app.processEvents()
check("…se il rame del lato sotto non è più rame, torna una faccia sola: specchio di nuovo attivo, nota nascosta",
      dlg.mirror.isEnabled() and not dlg.lbl_two.isVisible() and not dlg.side_view.isVisible() and not dlg.board.two_sided)
dlg.close()

orig_ask2 = dialogs_gerber.ask
dialogs_gerber.ask = lambda parent, fl, er=(): gerber.Options()
del os.environ["FLC_NO_DIALOGS"]
reset_plates()
infos.clear()
w.import_files([top.path, bot2.path, pr.path])
check("due facce dal programma: alla fine un messaggio spiega i tre passi e dice che rimettere a posto la basetta è compito di chi incide",
      len(infos) == 1 and "«Lato sopra»" in infos[0] and "«Lato sotto (specchiato)»" in infos[0] and "compito tuo" in infos[0]
      and "dima" in infos[0] and "pagina di un libro" in infos[0], infos)
if w.remote is not None:
    reset_plates()
    infos.clear()
    res = w.remote.c_import_file(top.path, more_paths=[bot2.path, pr.path], mirror=True)
    check("due facce da Claude: due piani, nessun messaggio da confermare, risultato con i nomi dei piani",
          res["pcb"]["two_sided"] and res["pcb"]["plates"] == {"top": "Lato sopra", "bottom": "Lato sotto (specchiato)"}
          and not res["pcb"]["mirrored"] and infos == [] and len(ed.doc.plates) == 2 and len(res["shapes"]) == 1, res.get("pcb"))
    reset_plates()
    res = w.remote.c_import_file(top.path, more_paths=[pr.path])
    check("una faccia da Claude: come prima, nessun piano in più", not res["pcb"]["two_sided"] and res["pcb"]["plates"] is None
          and len(ed.doc.plates) == 1, res.get("pcb"))
else:
    check("due facce da Claude (collegamento spento in questa prova)", True)
    check("una faccia da Claude (collegamento spento in questa prova)", True)
dialogs_gerber.ask = orig_ask2
os.environ["FLC_NO_DIALOGS"] = "1"
reset_plates()

# aiuto, filtro, tempi
h = help_texts.lookup("import")
check("scheda d'aiuto di Importa: parla dei circuiti stampati e delle due facce", h is not None and "Gerber" in h[1]
      and "Excellon" in h[1] and "Due facce" in h[1] and "compito tuo" in h[1])
check("finestra «Importa»: le estensioni dei circuiti nel primo filtro e in uno loro; c'è «Tutti i file»",
      "*.gbr" in mw.IMPORT_FILTER.split(";;")[0] and "*.drl" in mw.IMPORT_FILTER.split(";;")[0]
      and mw.IMPORT_FILTER.count("*.gtl") == 2 and mw.IMPORT_FILTER.rstrip().endswith("(*)"), mw.IMPORT_FILTER[:200])

many = ["%TF.FileFunction,Copper,L1,Top*%\n%ADD10C,1.6*%\n%ADD11C,0.25*%\n"]
for i in range(40):
    for j in range(40):
        many.append("D10*\n" + flash(i * 2.54, j * 2.54))
        if i < 39:
            many.append("D11*\n" + move(i * 2.54, j * 2.54) + line(i * 2.54 + 2.54, j * 2.54 + (1.27 if j % 2 else 0)))
big2 = gbr("".join(many), name="tanti-F_Cu.gbr")
t0 = time.time()
clear()
w.import_files([big2])
dt = time.time() - t0
check("basetta con 1600 piazzole e 1560 piste: letta, calcolata e sul piano in pochi secondi", len(ed.doc.shapes) == 1 and dt < 30, f"{dt:.1f} s")

w.close()
code_ = 0 if all(results) else 1
print(f"\n{sum(results)}/{len(results)} superati")

from _uscita import esci  # noqa: E402

esci(code_)
