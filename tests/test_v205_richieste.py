# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.5, seconda parte: le richieste del 16/11/2026 (voci 4-11 del quadro in «aggiornamento-0.20.5»).

A  angoli del rettangolo raccordati verso l'interno (Stefano Modena): raggio negativo, unico o per angolo;
   area e perimetro veri, limite, forma ridimensionata/ruotata/specchiata, salva e riapri, barra R, riquadro dei
   quattro angoli, pannello Proprietà, strumento Rettangolo, progetti .lbrn, sequenze oltre il limite e ritorno;
B  elenco Livelli: la riga evidenziata segue il livello appena assegnato (tavolozza, tendina, gruppi, Annulla);
C  offset: anteprima sul piano mentre si cambiano i valori, documento e cronologia intatti, uguale al risultato;
D  strumento Forme (e Rettangolo, Poligono, Stella): le opzioni nelle Proprietà compaiono subito anche con qualcosa
   di selezionato; una selezione nuova riporta le proprietà della forma;
E  finestra «Camera della testa»: si ridimensiona, sta in uno schermo basso, i comandi restano raggiungibili,
   ricorda la misura, non nasce più grande dello schermo;
F  pulsante dello sfondo del piano accanto alle schede: camera → mosaico → bianco, sfondi mancanti saltati,
   il mosaico resta in memoria, il pulsante compare solo se serve;
G  Linux: librerie che Qt chiede al sistema lette dai file ELF, libgthread nell'AppImage, controllo che ferma la
   costruzione, messaggio d'avvio con la libreria che manca e il comando per installarla, prova su openSUSE;
H  ringraziamenti: un solo elenco di nomi, trama della schermata di avvio (righe di grandezze alternate, nomi in
   ordine, lo stesso nome mai due volte con la stessa grandezza, tempi, stato finale),
   ridisegno durante il caricamento, attesa minima solo con uno schermo vero, targa in Aiuto solo da leggere,
   campo facoltativo nel rapporto, README e sito con gli stessi nomi, informativa privacy;
I  testi nuovi tradotti in tutte le lingue.
Uso: python tests/test_v205_richieste.py [classica|banco]
"""
import importlib
import inspect
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = tempfile.mkdtemp()
os.environ["APPDATA"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ["FLC_SETTINGS_INI"] = os.path.join(tempfile.mkdtemp(), "prova.ini")
os.environ["FLC_UI"] = "banco" if "banco" in sys.argv else "classica"
os.environ["FLC_NO_DIALOGS"] = "1"
os.environ["FLC_NO_FIRST_RUN"] = "1"
os.environ.pop("FLC_SIM_NEGATIVE", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainterPath, QTransform  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QDoubleSpinBox, QMessageBox, QPushButton, QToolButton  # noqa: E402

app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
from freelasercut import diag, i18n, splash, support, thanks  # noqa: E402
from freelasercut import head_camera_ui as hu  # noqa: E402
from freelasercut import startup_guard as guard  # noqa: E402
from freelasercut.core import geom, ops, shapes_lib  # noqa: E402
from freelasercut.core.document import (  # noqa: E402
    EllipseShape, GroupShape, PathShape, PolygonShape, RectShape, SpecialShape, shape_from_dict,
)
from freelasercut.ui import dialogs as dialogs_mod  # noqa: E402
from freelasercut.ui import dialogs_report, dialogs_thanks  # noqa: E402
from freelasercut.ui.main_window import MainWindow  # noqa: E402

results = []
hidden = []

def _hook(tp, ex, tb):
    """Gli errori dentro gli eventi di Qt si contano (devono essere zero); se è la prova stessa a fermarsi si vede."""
    hidden.append(ex)
    import traceback

    traceback.print_exception(tp, ex, tb)


sys.excepthook = _hook
TAG = os.environ["FLC_UI"]


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "KO  ") + name + (f"  [{info}]" if info and not cond else ""), flush=True)


def spin(n=8):
    for _ in range(n):
        app.processEvents()


def until(fn, t=5.0):
    e = time.time() + t
    while time.time() < e and not fn():
        app.processEvents()
        time.sleep(0.01)
    return fn()


def area(s):
    return sum(abs(p.area()) for p in geom.flatten(s.path(), 0.0005) if p.closed)


def perimeter(s):
    tot = 0.0
    for p in geom.flatten(s.path(), 0.0005):
        pts = p.pts + ([p.pts[0]] if p.closed else [])
        tot += sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    return tot


def close(a, b, rel=5e-4, ab=1e-6):
    return abs(a - b) <= max(ab, rel * max(abs(a), abs(b)))


w = MainWindow()
w.resize(1400, 900)
w.show()
spin(20)
ed, cv = w.editor, w.canvas


def fresh(shapes=(), sel=None):
    ed.select([])
    if ed.doc.shapes:
        ed.run("svuota", ed.doc.remove, list(ed.doc.shapes))
    cv.set_tool("select")
    if shapes:
        ed.add(list(shapes), "prova")
    ed.select(list(shapes) if sel is None else list(sel))
    spin()


# ====================================================================== A. angoli verso l'interno
print("--- A. angoli verso l'interno")
W_, H_ = 40.0, 20.0
full = W_ * H_
r0 = RectShape(W_, H_, 0)
check("A raggio 0: il rettangolo di sempre", close(area(r0), full) and r0.local_path().elementCount() == 5)
old = QPainterPath()
old.addRoundedRect(QRectF(0, 0, W_, H_), 5, 5)
check("A raggio positivo: lo stesso tracciato di prima, elemento per elemento",
      RectShape(W_, H_, 5).local_path() == old)
for rad in (2.0, 5.0, 10.0):
    s = RectShape(W_, H_, -rad)
    check(f"A raggio -{rad:g}: area = rettangolo meno un cerchio intero",
          close(area(s), full - math.pi * rad * rad), f"{area(s):.3f}")
    check(f"A raggio -{rad:g}: perimetro = lati accorciati più quattro quarti di cerchio",
          close(perimeter(s), 2 * (W_ + H_) - 8 * rad + 2 * math.pi * rad), f"{perimeter(s):.3f}")
    b = s.bounds()
    check(f"A raggio -{rad:g}: l'ingombro resta quello del rettangolo",
          close(b.width(), W_) and close(b.height(), H_))
s = RectShape(W_, H_, -6)
arc_ok = True
for p in geom.flatten(s.path(), 0.0005):
    for x, y in p.pts:
        for cx, cy in ((0, 0), (W_, 0), (W_, H_), (0, H_)):
            d = math.hypot(x - cx, y - cy)
            if d < 6 - 0.01:  # nessun punto del contorno entra nel quarto di cerchio scavato attorno allo spigolo
                arc_ok = False
check("A lo spigolo è scavato: nessun punto del contorno a meno di r dallo spigolo", arc_ok)
check("A …e l'arco passa a r dallo spigolo, dentro la forma (punto a 45°)",
      s.path().contains(s.tf.map(geom.QPointF(6 * 0.72, 6 * 0.72)) if hasattr(geom, "QPointF") else
                        __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(6 * 0.72, 6 * 0.72))
      and not s.path().contains(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(6 * 0.69, 6 * 0.69)))
s = RectShape(W_, H_, -30)
check("A oltre il limite: vale la metà del lato più corto (10 mm)", s.corner_radii() == [-10.0] * 4
      and close(area(s), full - math.pi * 100))
s = RectShape(W_, H_, 0, radii=[5, 5, -5, -5])
check("A raggi diversi per angolo: due arrotondati sopra e due scavati sotto",
      close(area(s), full - 2 * (1 - math.pi / 4) * 25 - 2 * (math.pi / 4) * 25), f"{area(s):.3f}")
QP = __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF
check("A …in alto (Y grande) gli angoli sono pieni e tondi, in basso scavati",
      s.path().contains(QP(2.5, H_ - 2.5)) and not s.path().contains(QP(0.4, H_ - 0.4))
      and not s.path().contains(QP(2.5, 2.5)) and s.path().contains(QP(4.6, 4.6)))
s = RectShape(W_, H_, 0, radii=[0, -4, 0, 3])
check("A un angolo scavato, uno tondo, due vivi", close(area(s), full - math.pi / 4 * 16 - (1 - math.pi / 4) * 9))
for bad in (float("nan"), "x", None):
    check(f"A valore non valido ({bad!r}) = spigolo vivo", RectShape.clamp_radius(bad, 10) == 0.0)
# forma trasformata: il raggio resta in mm veri
s = RectShape(W_, H_, -4)
s.set_transform(QTransform().scale(2.0, 1.5))
check("A rettangolo ridimensionato: il raggio resta in mm sul piano (cerchio vero, non un'ellisse)",
      close(area(s), 80 * 30 - math.pi * 16), f"{area(s):.3f}")
check("A …e il limite è la metà del lato corto come si vede (15 mm)", close(s.max_radius(), 15.0))
s.radius = -99
s.invalidate()
check("A …oltre il limite dopo il ridimensionamento", s.corner_radii() == [-15.0] * 4
      and close(area(s), 80 * 30 - math.pi * 225))
s = RectShape(W_, H_, -5)
s.set_transform(QTransform().rotate(33).scale(-1, 1).translate(7, 3))
check("A ruotato e specchiato: stessa area", close(area(s), full - math.pi * 25))
g = GroupShape([RectShape(W_, H_, -5)], 1)
g.set_transform(QTransform().scale(3, 3))
check("A dentro un gruppo ingrandito: il disegno segue il gruppo", close(area(g), 9 * (full - math.pi * 25), 2e-3))
# salva e riapri
s = RectShape(W_, H_, -5)
d1 = s.to_dict()
s2 = shape_from_dict(json.loads(json.dumps(d1)))
check("A salva e riapri (raggio unico negativo)", isinstance(s2, RectShape) and s2.radius == -5 and close(area(s2), area(s)))
s = RectShape(W_, H_, 0, radii=[3, -3, 0, -6])
s2 = shape_from_dict(json.loads(json.dumps(s.to_dict())))
check("A salva e riapri (un raggio per angolo)", s2.radii == [3.0, -3.0, 0.0, -6.0] and close(area(s2), area(s)))
check("A il formato del progetto non cambia (stesse voci: una versione vecchia legge il valore e lo porta a 0)",
      set(RectShape(W_, H_, -5).params()) == {"w", "h", "radius"}
      and set(RectShape(W_, H_, 0, radii=[1, -1, 0, 0]).params()) == {"w", "h", "radius", "radii"})
# barra R
ra, rb = RectShape(W_, H_, 0), RectShape(30, 30, 2)
po = PolygonShape(30, 30, 6)
fresh([ra, rb, po])
w.numeric.set_radius(-5)
check("A barra R, valore negativo: i rettangoli scavati, il poligono resta a spigoli vivi",
      ra.radius == -5 and rb.radius == -5 and po.radius == 0 and close(area(ra), full - math.pi * 25))
check("A …il campo R mostra il valore", close(w.numeric.frad.value(), -5))
w.numeric.set_radius(-500)
check("A barra R oltre il limite: ognuno al suo massimo, negativo", ra.radius == -10 and rb.radius == -15)
w.numeric.set_radius(4)
check("A barra R di nuovo positivo: tutto come prima", ra.radius == 4 and po.radius == 4
      and ra.local_path() == RectShape(W_, H_, 4).local_path())
n_undo = len(ed.undo_stack)
w.numeric.set_radius(-3)
ed.undo()
check("A Annulla riporta il raggio di prima (un passo solo)", ed.doc.shapes[0].radius == 4 and len(ed.undo_stack) == n_undo)
ed.redo()
check("A Ripeti", ed.doc.shapes[0].radius == -3)
ra = RectShape(W_, H_, 0)
fresh([ra])
w.numeric.set_corners([5, 5, -5, -500])
check("A quattro angoli dalla barra: positivi e negativi, ognuno limitato", ra.radii == [5.0, 5.0, -5.0, -10.0])
check("A …R mostra il più grande in valore assoluto", close(w.numeric.frad.value(), -10))
w.numeric.set_corners(None)
check("A «Ogni angolo a parte» spento: resta il raggio più grande, col suo segno", ra.radii is None and ra.radius == -10)
w.numeric.corners.load(ra)
check("A riquadro dei quattro angoli: accetta valori negativi e mostra quelli della forma",
      all(sp.minimum() < 0 for sp in w.numeric.corners.spins) and [sp.value() for sp in w.numeric.corners.spins] == [-10.0] * 4)
# pannello Proprietà
ra = RectShape(W_, H_, 2)
fresh([ra])
sp = w.props.radius_spins
check("A Proprietà: i campi del raggio accettano valori negativi", len(sp) == 5 and all(x.minimum() < 0 for x in sp))
sp[0].setValue(-4)
check("A Proprietà: raggio -4", ra.radius == -4 and close(area(ra), full - math.pi * 16))
sp[0].setValue(-80)
check("A Proprietà oltre il limite: diventa -10 e il campo lo mostra", ra.radius == -10 and close(sp[0].value(), -10))
sp[0].setValue(-1)
check("A Proprietà: di nuovo sotto il limite", ra.radius == -1)
w.props.corner_each.setChecked(True)
check("A Proprietà, ogni angolo a parte: parte dal raggio che c'era", ra.radii == [-1.0] * 4)
sp[2].setValue(6)
sp[3].setValue(-7)
check("A Proprietà: un angolo tondo e uno scavato", ra.radii == [-1.0, 6.0, -7.0, -1.0])
w.props.corner_each.setChecked(False)
check("A Proprietà, ritorno al raggio unico: il più grande col suo segno", ra.radii is None and ra.radius == -7)
w.numeric.set_radius(-2)
spin()
check("A cambiando dalla barra, il campo delle Proprietà segue", close(w.props.radius_spins[0].value(), -2))
# strumento Rettangolo e file di altri programmi
fresh()
cv.tool_options["corner_radius"] = -3.0
made = cv.tools["rect"].make(QRectF(0, 0, 20, 10))
cv.tool_options["corner_radius"] = 0.0
check("A strumento Rettangolo con raggio negativo nelle opzioni", made.radius == -3 and close(area(made), 200 - math.pi * 9))
try:
    import xml.etree.ElementTree as ET

    from freelasercut.core import lbrn

    el = ET.fromstring('<Shape Type="Rect" CutIndex="0" W="40" H="20" Cr="-5"><XForm>1 0 0 1 50 50</XForm></Shape>')
    sh = lbrn.shape_from(el, {}) if "ctx" in inspect.signature(lbrn.shape_from).parameters else lbrn.shape_from(el)
    check("A progetto .lbrn2 con raggio negativo: angoli scavati", isinstance(sh, RectShape) and sh.radius == -5
          and close(area(sh), full - math.pi * 25))
except Exception as ex:  # noqa: BLE001
    check("A progetto .lbrn2 con raggio negativo: angoli scavati", False, repr(ex))
ra = RectShape(W_, H_, -5)
fresh([ra])
inf = ops.info([ra])
check("A misure della selezione (perimetro e area) giuste con gli angoli scavati",
      close(inf["area"], full - math.pi * 25, 1e-3) and close(inf["perimeter"], 2 * (W_ + H_) - 40 + 10 * math.pi, 1e-3))
off = ops.offset_shapes([ra], 1.0, "out", "round")
check("A l'offset di un rettangolo scavato si calcola", len(off) == 1 and off[0].bounds().width() > W_ + 1.9)

# ====================================================================== B. livello evidenziato
print("--- B. livello evidenziato")


def cur_layer():
    it = w.layers.tree.currentItem()
    return it.data(0, Qt.UserRole) if it is not None else None


a_, b_ = RectShape(20, 20, 0, layer=1), EllipseShape(20, 20, layer=2)
b_.set_transform(QTransform.fromTranslate(40, 0))
fresh([a_, b_], sel=[a_])
w.layers.show_layer(1)
check("B prima: evidenziato il livello 1", cur_layer() == 1)
w.palette.pick(2)
spin()
check("B dalla tavolozza: la forma va sul livello 2 e la riga evidenziata lo segue", a_.layer == 2 and cur_layer() == 2)
w.palette.pick(3)
spin()
check("B cambio idea, livello 3 (nuovo): la riga evidenziata è la 3, non la precedente", a_.layer == 3 and cur_layer() == 3)
i = w.numeric.layer_combo.findData(5)
w.numeric._layer_picked(i)
spin()
check("B dalla tendina Livello della barra: segue anche lì", a_.layer == 5 and cur_layer() == 5)
ed.undo()
spin()
check("B Annulla: la forma torna al livello di prima e l'elenco ha comunque una riga valida",
      ed.doc.shapes[0].layer == 3 and cur_layer() in (2, 3))
ed.select([])
before = cur_layer()
ed.set_layer(7)
spin()
check("B senza selezione: cambia solo il livello dei prossimi disegni (non ha ancora una riga)",
      ed.current_layer == 7 and cur_layer() == before)
ed.select([ed.doc.shapes[1]])
ed.set_layer(30)
spin()
check("B livello strumenti T1 (non è nell'elenco): nessun errore, la riga resta valida",
      ed.doc.shapes[1].layer == 30 and cur_layer() is not None)
g = GroupShape([RectShape(5, 5, 0, layer=1), RectShape(5, 5, 0, layer=1)], 1)
fresh([g])
ed.set_layer(4)
spin()
check("B gruppo: tutte le forme sul livello nuovo, riga evidenziata la 4",
      all(leaf.layer == 4 for leaf, _ in g.leaves()) and cur_layer() == 4)
check("B il segnale parte anche senza l'elenco aperto (nessun errore nascosto)", not hidden, repr(hidden[:1]))

# ====================================================================== C. anteprima dell'offset
print("--- C. anteprima dell'offset")
ra = RectShape(40, 20, 0)
ra.set_transform(QTransform.fromTranslate(100, 100))
fresh([ra])
n_shapes, n_undo = len(ed.doc.shapes), len(ed.undo_stack)
dlg = dialogs_mod.OffsetDialog(w, ed, cv)
dlg.dist.setValue(2.0)
dlg.update_preview()


def over_bounds():
    r = QRectF()
    for p in cv.overlay_paths:
        r = r.united(p.boundingRect())
    return r


ob = over_bounds()
check("C all'apertura l'anteprima è sul piano, 2 mm fuori dalla forma",
      len(cv.overlay_paths) == 1 and close(ob.width(), 44, 1e-3) and close(ob.height(), 24, 1e-3)
      and close(ob.left(), 98, 1e-3))
check("C il documento e la cronologia non sono toccati", len(ed.doc.shapes) == n_shapes and len(ed.undo_stack) == n_undo
      and not ed.dirty or len(ed.undo_stack) == n_undo)
dlg.dist.setValue(5.0)
check("C cambiando la distanza l'anteprima aspetta un attimo e poi si aggiorna da sola",
      dlg._timer.isActive() and until(lambda: close(over_bounds().width(), 50, 1e-3), 3.0))
dlg.direction.setCurrentIndex(dlg.direction.findData("in"))
dlg.update_preview()
check("C verso l'interno: più piccola della forma", close(over_bounds().width(), 30, 1e-3) and close(over_bounds().height(), 10, 1e-3))
dlg.direction.setCurrentIndex(dlg.direction.findData("both"))
dlg.update_preview()
check("C entrambi: due contorni", len(cv.overlay_paths) == 2)
dlg.direction.setCurrentIndex(dlg.direction.findData("in"))
dlg.dist.setValue(15.0)
dlg.update_preview()
check("C distanza che non lascia niente: nessuna anteprima e la finestra lo dice",
      cv.overlay_paths == [] and dlg.note.text() != "")
dlg.direction.setCurrentIndex(dlg.direction.findData("out"))
dlg.dist.setValue(3.0)
dlg.corner.setCurrentIndex(dlg.corner.findData("miter"))
prev = dlg.update_preview()
check("C angoli vivi: l'anteprima cambia", len(prev) == 1 and dlg.note.text() == ""
      and prev[0].path().elementCount() < 12)


def shot():
    cv.viewport().update()
    spin()
    img = cv.viewport().grab().toImage().convertToFormat(QImage.Format_RGB32)
    return np.frombuffer(bytes(img.constBits()), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4].copy()


cv.fit_rect(QRectF(80, 80, 80, 60))
spin()
with_ov = shot()
saved = list(cv.overlay_paths)
cv.set_overlay([])
without = shot()
cv.set_overlay(saved)
check("C l'anteprima si vede davvero sul piano (i pixel cambiano)", int((with_ov != without).sum()) > 200)
dlg.reject()
check("C Annulla: l'anteprima sparisce e non resta niente (né forme né passi)",
      cv.overlay_paths == [] and len(ed.doc.shapes) == n_shapes and len(ed.undo_stack) == n_undo)
dlg = dialogs_mod.OffsetDialog(w, ed, cv)
dlg.dist.setValue(4.0)
prev = dlg.update_preview()
pb = prev[0].path().boundingRect()
vals = dlg.values()
dlg.accept()
ed.offset(*[vals[0], vals[1], vals[2], vals[3], vals[4]])
made = [s for s in ed.doc.shapes if s is not ra]
check("C «Crea offset»: la forma creata è quella dell'anteprima, un passo solo, anteprima tolta",
      len(made) == 1 and close(made[0].bounds().width(), pb.width(), 1e-6) and close(made[0].bounds().left(), pb.left(), 1e-6)
      and len(ed.undo_stack) == n_undo + 1 and cv.overlay_paths == [])
ra = RectShape(40, 20, 0)
fresh([ra])
_exec = QDialog.exec
QDialog.exec = lambda self: (self.dist.setValue(1.5), self.update_preview(), self.accept(), QDialog.Accepted)[-1] \
    if isinstance(self, dialogs_mod.OffsetDialog) else _exec(self)
try:
    w.offset_dialog()
finally:
    QDialog.exec = _exec
check("C dal comando del programma: finestra con l'anteprima, poi la forma vera",
      len(ed.doc.shapes) == 2 and close(max(s.bounds().width() for s in ed.doc.shapes), 43, 1e-3) and cv.overlay_paths == [])
old_dlg = dialogs_mod.OffsetDialog(w)
check("C la finestra senza piano (uso di prima) funziona ancora", old_dlg.values()[0] > 0 and old_dlg.update_preview() == [])
old_dlg.reject()
fresh([])
dlg = dialogs_mod.OffsetDialog(w, ed, cv)
check("C senza forme adatte: nessuna anteprima, nessun errore", dlg.update_preview() == [] and cv.overlay_paths == [])
dlg.reject()

# ====================================================================== D. opzioni dello strumento subito
print("--- D. strumento Forme: elenco subito")
N_FORMS = len(shapes_lib.SHAPES)


def gallery():
    return [b for b in w.props.widget().findChildren(QToolButton) if b.isCheckable() and b.width() == 44 and not b.isHidden()]


fresh()
w.tool_actions["special"].trigger()
spin()
check("D senza selezione: scelto Forme, la galleria c'è (come prima)", len(gallery()) == N_FORMS)
ra = RectShape(40, 20, 3)
fresh([ra])
check("D con un rettangolo selezionato il pannello mostra il rettangolo", w.props.shape is ra and not gallery())
w.tool_actions["special"].trigger()
spin()
check("D scelto Forme con il rettangolo ancora selezionato: la galleria compare subito",
      len(gallery()) == N_FORMS and w.props.shape is None and ed.selection == [ra])
other = [k for k in shapes_lib.SHAPES if k != cv.tool_options.get("special", "arrow")][3]
next(b for b in gallery() if b.toolTip() == shapes_lib.SHAPES[other][0]).click()
spin()
check("D un clic nella galleria sceglie la forma da disegnare e non tocca il rettangolo selezionato",
      cv.tool_options["special"] == other and isinstance(ed.doc.shapes[0], RectShape) and ed.doc.shapes[0].radius == 3
      and len(gallery()) == N_FORMS)
w.tool_actions["select"].trigger()
spin()
check("D tornando a Selezione il pannello torna alle proprietà del rettangolo", w.props.shape is ra and not gallery())
w.tool_actions["special"].trigger()
spin()
e2 = EllipseShape(10, 10)
ed.add([e2], "prova")
spin()
check("D una selezione nuova (la forma appena disegnata) mostra le sue proprietà", w.props.shape is e2 and not gallery())
sp_shape = SpecialShape("heart" if "heart" in shapes_lib.SHAPES else other, 30, 30)
fresh([sp_shape])
form0 = sp_shape.form
check("D una forma della galleria selezionata mostra la sua galleria (per cambiarla)", w.props.shape is sp_shape and len(gallery()) == N_FORMS)
w.tool_actions["special"].trigger()
spin()
pick = [k for k in shapes_lib.SHAPES if k not in (form0, cv.tool_options["special"])][0]
next(b for b in gallery() if b.toolTip() == shapes_lib.SHAPES[pick][0]).click()
spin()
check("D …ma scelto di nuovo lo strumento Forme, la galleria sceglie la PROSSIMA forma e non cambia quella selezionata",
      ed.doc.shapes[0].form == form0 and cv.tool_options["special"] == pick)
ra, rb = RectShape(10, 10), RectShape(10, 10)
fresh([ra, rb])
w.tool_actions["special"].trigger()
spin()
check("D con più oggetti selezionati: la galleria, non «2 oggetti selezionati»", len(gallery()) == N_FORMS)
for name in ("rect", "polygon", "star"):
    fresh([RectShape(10, 10, 1)])
    w.tool_actions[name].trigger()
    spin()
    labels = [x.text() for x in w.props.widget().findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)]
    check(f"D strumento {name} con una forma selezionata: le opzioni dello strumento (lati, punte, raggio) subito",
          w.props.shape is None and any("poligono" in t.lower() or "polygon" in t.lower() for t in labels))
fresh([RectShape(10, 10, 1)])
w.tool_actions["line"].trigger()
spin()
check("D uno strumento senza opzioni (Linea) lascia le proprietà della selezione, come prima", w.props.shape is not None)
w.tool_actions["select"].trigger()
if TAG == "banco":
    fresh([RectShape(10, 10, 1)])
    w.tool_actions["special"].trigger()
    spin(20)
    check("D Banco: la scheda delle proprietà è visibile con la galleria", w.banco._props_visible() and len(gallery()) == N_FORMS)
    w.tool_actions["select"].trigger()

# ====================================================================== E. finestra «Camera della testa»
print("--- E. finestra Camera della testa")
FIT = hu.HeadCameraWindow.fit_size
check("E misura dentro uno schermo grande: quella chiesta", FIT((1060, 640), (1920, 1040)) == (1060, 640))
check("E schermo basso (1366 × 768 con la barra): la finestra ci sta tutta, bordi compresi",
      FIT((1060, 640), (1366, 728)) == (1060, 640) and FIT((1060, 900), (1366, 728)) == (1060, 664))
check("E schermo piccolo (1024 × 600): rimpicciolita, mai più dello schermo", FIT((1060, 640), (1024, 560)) == (1000, 496))
check("E mai sotto il minimo che lascia leggere i comandi", FIT((100, 100), (1920, 1080)) == (760, 330))
hw = hu.HeadCameraWindow(w.camera.head)
hw.show()
spin(20)
scr = hw.screen().availableGeometry()
check("E la finestra nasce dentro lo schermo", hw.width() <= scr.width() and hw.height() <= scr.height(),
      f"{hw.width()}x{hw.height()} su {scr.width()}x{scr.height()}")
check("E altezza minima bassa (prima quasi 900 pixel): sta anche in uno schermo di 600", hw.minimumHeight() <= 330
      and hw.minimumSizeHint().height() <= 330, f"{hw.minimumHeight()} {hw.minimumSizeHint().height()}")
check("E la vista del video si può rimpicciolire", hw.view.minimumWidth() <= 240 and hw.view.minimumHeight() <= 135)
check("E si può ingrandire a tutto schermo e tirare dall'angolo",
      bool(hw.windowFlags() & Qt.WindowMaximizeButtonHint) and hw.isSizeGripEnabled())
hw.resize(hw.MIN_W, hw.MIN_H)
spin(20)
check("E ridimensionata al minimo", (hw.width(), hw.height()) == (hw.MIN_W, hw.MIN_H))
btns = [hw.b_laser, hw.b_cam, hw.b_origin, hw.b_cal, hw.b_check, hw.b_check_dot, hw.b_a, hw.b_b, hw.b_align, hw.b_clear,
        hw.b_mosaic, hw.b_unmosaic, hw.b_align_bed, hw.zone, hw.margin, hw.thick, hw.chk_auto, hw.chk_design]
check("E tutti i comandi sono nella colonna che scorre", all(hw.side.widget().isAncestorOf(b) for b in btns))
sb = hw.side.verticalScrollBar()
check("E al minimo la colonna scorre (i comandi in basso si raggiungono)", sb.maximum() > 0, str(sb.maximum()))
hw.side.ensureWidgetVisible(hw.b_unmosaic)
spin()
top = hw.b_unmosaic.mapTo(hw.side.viewport(), hw.b_unmosaic.rect().topLeft()).y()
check("E l'ultimo pulsante («Togli la foto dal piano») arriva dentro la parte visibile",
      0 <= top <= hw.side.viewport().height() - hw.b_unmosaic.height() + 2, str(top))
check("E video e comandi affiancati: la vista è a sinistra della colonna",
      hw.view.mapTo(hw, hw.view.rect().topRight()).x() <= hw.side.x())
hw.resize(770, 500)
spin()
hw.close()
hw2 = hu.HeadCameraWindow(w.camera.head)
check("E la misura scelta si ricorda alla prossima apertura", (hw2.width(), hw2.height()) == (770, 500),
      f"{hw2.width()}x{hw2.height()}")
w.qs.setValue(hu.HeadCameraWindow.GEOM_KEY, "5000x4000")
hw3 = hu.HeadCameraWindow(w.camera.head)
check("E una misura salvata su uno schermo più grande non fa uscire la finestra dallo schermo",
      hw3.width() <= scr.width() and hw3.height() <= scr.height())
w.qs.setValue(hu.HeadCameraWindow.GEOM_KEY, "boh")
hw4 = hu.HeadCameraWindow(w.camera.head)
check("E una misura salvata rovinata non dà errori", hw4.width() >= hw4.MIN_W)
for x in (hw2, hw3, hw4):
    x.close()
w.qs.remove(hu.HeadCameraWindow.GEOM_KEY)

# ====================================================================== F. sfondo del piano
print("--- F. pulsante dello sfondo del piano")
cam, bar = w.camera, w.plate_bar
check("F senza foto da mostrare: solo il piano bianco, pulsante nascosto",
      cam.bg_modes() == ["none"] and cam.bg_mode() == "none" and bar.bg_btn.isHidden())
lay = bar.layout()
order = [lay.itemAt(i).widget() for i in range(lay.count())]
check("F il pulsante sta dopo le schede e prima di «+» e del simbolo dei livelli",
      order.index(bar.tabs) < order.index(bar.bg_btn) < order.index(bar.add_btn) < order.index(bar.ghosts))
mos = np.full((40, 60, 3), 90, np.uint8)
cam.show_mosaic(mos, 4.0)
spin()
check("F fatta la foto a mosaico: è lo sfondo, e il pulsante compare",
      cam.bg_modes() == ["mosaic", "none"] and cam.bg_mode() == "mosaic" and not bar.bg_btn.isHidden()
      and cv._cam_item is not None)
tip_m = bar.bg_btn.toolTip()
key_m = bar.bg_btn.icon().cacheKey()
bar.bg_btn.click()
spin()
check("F un clic: piano bianco, la foto a mosaico resta in memoria",
      cam.bg_mode() == "none" and cv._cam_item is None and cam.mosaic is not None)
check("F il suggerimento dice che cosa c'è e che cosa fa il clic, e l'icona cambia",
      bar.bg_btn.toolTip() != tip_m and bar.bg_names()["none"] in bar.bg_btn.toolTip()
      and bar.bg_names()["mosaic"] in bar.bg_btn.toolTip() and bar.bg_btn.icon().cacheKey() != key_m)
bar.bg_btn.click()
spin()
check("F altro clic: torna la foto a mosaico, alla sua scala",
      cam.bg_mode() == "mosaic" and cv._cam_item is not None and close(cv._cam_item.scale(), 0.25))
# camera del piano finta: «c'è qualcosa da mostrare» e lo scatto mette un'immagine sotto il piano
shots = []
cam.can_show = lambda: True
cam.snapshot = lambda: (shots.append(1), cv.set_camera_image(QImage(8, 8, QImage.Format_RGB32), 2.0))[0]
cam.update_state()
spin()
check("F con la camera del piano: tre sfondi, nell'ordine camera, mosaico, bianco",
      cam.bg_modes() == ["camera", "mosaic", "none"] and cam.chk_live.isEnabled())
seq = []
for _ in range(6):
    bar.bg_btn.click()
    spin()
    seq.append(cam.bg_mode())
check("F il giro: bianco → camera → mosaico → bianco…", seq == ["none", "camera", "mosaic", "none", "camera", "mosaic"], str(seq))
cam.set_bg_mode("camera")
spin()
check("F sulla camera: la foto dal vivo è accesa, il mosaico non si butta",
      cam.chk_live.isChecked() and cam.mosaic is not None and not cam.mosaic_on and close(cv._cam_item.scale(), 0.5))
cam.set_bg_mode("mosaic")
check("F sul mosaico: la foto dal vivo si spegne", not cam.chk_live.isChecked() and cam.mosaic_on)
cam.chk_live.setChecked(True)
spin()
check("F accendendo la foto dal vivo dalla scheda Camera il pulsante segue, e il mosaico resta per dopo",
      cam.bg_mode() == "camera" and cam.mosaic is not None and bar.bg_names()["camera"] in bar.bg_btn.toolTip())
cam.clear_mosaic()
spin()
check("F «Togli la foto dal piano» con la camera accesa: via il mosaico, resta la foto dal vivo",
      cam.bg_modes() == ["camera", "none"] and cam.bg_mode() == "camera" and cv._cam_item is not None)
check("F uno sfondo che non c'è non si può scegliere", cam.set_bg_mode("mosaic") == "camera" and cam.set_bg_mode("boh") == "camera")
cam.can_show = lambda: False
cam.chk_live.setChecked(False)
cam.update_state()
spin()
check("F tolta anche la camera: piano bianco e pulsante di nuovo nascosto",
      cam.bg_modes() == ["none"] and cv._cam_item is None and bar.bg_btn.isHidden())
del cam.can_show, cam.snapshot
check("F nessun errore nascosto", not hidden, repr(hidden[:1]))

# ====================================================================== G. Linux
print("--- G. Linux: librerie di sistema")
sys.path.insert(0, os.path.join(ROOT, "build"))
pa = importlib.import_module("prepara_appimage")


def fake_elf(path, needed):
    """Un file ELF a 64 bit minimo con le voci DT_NEEDED date (basta per il lettore)."""
    strtab = b"\0" + b"".join(n.encode() + b"\0" for n in needed)
    offs, o = [], 1
    for n in needed:
        offs.append(o)
        o += len(n) + 1
    ph = 64
    dyn_off = ph + 2 * 56
    dyn = b"".join(struct.pack("<qQ", 1, x) for x in offs) + struct.pack("<qQ", 5, 0x1000 + 0x300) + struct.pack("<qQ", 0, 0)
    data = bytearray(0x300 + len(strtab))
    data[0:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", data, 0x20, ph)
    struct.pack_into("<HH", data, 0x36, 56, 2)
    struct.pack_into("<IIQQQQQQ", data, ph, 1, 5, 0, 0x1000, 0x1000, len(data), len(data), 0x1000)
    struct.pack_into("<IIQQQQQQ", data, ph + 56, 2, 6, dyn_off, 0x1000 + dyn_off, 0, len(dyn), len(dyn), 8)
    data[dyn_off:dyn_off + len(dyn)] = dyn
    data[0x300:] = strtab
    with open(path, "wb") as fh:
        fh.write(bytes(data))


gd = tempfile.mkdtemp()
fake_elf(os.path.join(gd, "a.so"), ["libuno.so.1", "libc.so.6"])
check("G lettore dei file ELF: le librerie chieste, nell'ordine", pa.elf_needed(os.path.join(gd, "a.so")) == ["libuno.so.1", "libc.so.6"])
with open(os.path.join(gd, "testo.so"), "w") as fh:
    fh.write("non è una libreria")
with open(os.path.join(gd, "rotto.so"), "wb") as fh:
    fh.write(b"\x7fELF\x02\x01" + b"\xff" * 80)
check("G un file che non è ELF, uno rovinato, uno che non c'è: elenco vuoto, nessun errore",
      pa.elf_needed(os.path.join(gd, "testo.so")) == [] and pa.elf_needed(os.path.join(gd, "rotto.so")) == []
      and pa.elf_needed(os.path.join(gd, "manca.so")) == [])
ps = os.path.join(gd, "PySide6")
ql = os.path.join(ps, "Qt", "lib")
os.makedirs(ql)
os.makedirs(os.path.join(ps, "Qt", "plugins", "platforms"))
for m in pa.QT_MODULES:
    fake_elf(os.path.join(ql, f"libQt6{m}.so.6"), ["libc.so.6", "libstdc++.so.6"] + (["libQt6Core.so.6"] if m != "Core" else
                                                                                   ["libglib-2.0.so.0", "libgthread-2.0.so.0", "libicu.so.73"]))
fake_elf(os.path.join(ql, "libicu.so.73"), ["libc.so.6", "libQt6Core.so.6"])  # giro chiuso: non deve fermarsi lì
fake_elf(os.path.join(ps, "Qt", "plugins", "platforms", "libqxcb.so"), ["libQt6XcbQpa.so.6", "libxcb.so.1", "libxcb-cursor.so.0"])
out = pa.system_libs(pa.qt_roots(ps), [ql])
check("G librerie prese dal sistema: seguite a catena, quelle dentro l'AppImage non contano, i giri chiusi non bloccano",
      set(out) == {"libc.so.6", "libstdc++.so.6", "libglib-2.0.so.0", "libgthread-2.0.so.0", "libxcb.so.1", "libxcb-cursor.so.0"}
      and out["libgthread-2.0.so.0"] == "libQt6Core.so.6")
bad = pa.unexpected_system_libs(ps)
check("G senza libgthread e xcb-cursor nell'AppImage la costruzione le segnala (con chi le chiede)",
      len(bad) == 2 and any(x.startswith("libgthread-2.0.so.0 (chiesta da libQt6Core") for x in bad)
      and any(x.startswith("libxcb-cursor.so.0") for x in bad), str(bad))
fake_elf(os.path.join(ql, "libgthread-2.0.so.0"), ["libglib-2.0.so.0", "libc.so.6"])
fake_elf(os.path.join(ql, "libxcb-cursor.so.0"), ["libxcb.so.1", "libc.so.6"])
check("G con le due librerie accanto a Qt: niente da segnalare", pa.unexpected_system_libs(ps) == [])
fake_elf(os.path.join(ql, "libgthread-2.0.so.0"), ["libglib-2.0.so.0", "libnuova.so.9"])
check("G una libreria nuova chiesta da una di quelle aggiunte viene vista lo stesso",
      pa.unexpected_system_libs(ps) == ["libnuova.so.9 (chiesta da libgthread-2.0.so.0)"])
src_pa = open(os.path.join(ROOT, "build", "prepara_appimage.py"), encoding="utf-8").read()
check("G libgthread è fra le librerie messe nell'AppImage, non fra quelle date per scontate",
      pa.GLIB_EXTRA == ["libgthread-2.0.so.0"] and "libgthread-2.0.so.0" not in pa.SYSTEM_OK
      and not set(pa.XCB_EXTRA) & pa.SYSTEM_OK and "for name in XCB_EXTRA + GLIB_EXTRA:" in src_pa)
check("G il controllo ferma la costruzione (sys.exit) prima di impacchettare",
      src_pa.index("extra = unexpected_system_libs(pyside)") < src_pa.index('step("AppImage")')
      and re.search(r"if extra:\s+sys\.exit\(", src_pa) is not None)
if sys.platform.startswith("linux"):
    import PySide6

    real = os.path.dirname(PySide6.__file__)
    if os.path.isdir(os.path.join(real, "Qt", "lib")) and len(pa.qt_roots(real)) == len(pa.QT_MODULES) + 1:
        need = pa.elf_needed(os.path.join(real, "Qt", "lib", "libQt6Core.so.6"))
        check("G Qt vero: libQt6Core chiede davvero libgthread (il motivo del rapporto da openSUSE)",
              "libgthread-2.0.so.0" in need and "libc.so.6" in need)
        out = set(pa.system_libs(pa.qt_roots(real), [os.path.join(real, "Qt", "lib")]))
        extra = out - pa.SYSTEM_OK - set(pa.XCB_EXTRA) - set(pa.GLIB_EXTRA)
        check("G Qt vero: tutto quello che chiede al sistema è di base oppure viene messo nell'AppImage",
              not extra, str(sorted(extra)))
    else:
        print("    (Qt di sistema o incompleto: confronto con il Qt vero saltato)")
E_ = ImportError("libgthread-2.0.so.0: cannot open shared object file: No such file or directory")
check("G guardia d'avvio: riconosce la libreria che manca", guard.missing_library(E_) == "libgthread-2.0.so.0")
txt = guard.missing_library_text("libgthread-2.0.so.0")
check("G …e dice come installarla (zypper, apt, dnf, pacman), in inglese e in italiano",
      "sudo zypper install libgthread-2_0-0" in txt and "sudo apt install libglib2.0-0" in txt
      and "sudo dnf install glib2" in txt and "sudo pacman -S glib2" in txt
      and "A system library is missing" in txt and "Manca una libreria di sistema" in txt)
txt = guard.missing_library_text("libstrana.so.7")
check("G libreria non in tabella: come cercare il pacchetto che la contiene",
      "zypper search --provides libstrana.so.7" in txt and "apt-file search libstrana.so.7" in txt)
try:
    try:
        raise OSError("libEGL.so.1: cannot open shared object file: No such file or directory")
    except OSError as inner:
        raise RuntimeError("Qt non si carica") from inner
except RuntimeError as chained:
    check("G la libreria che manca si trova anche quando è la causa di un altro errore",
          guard.missing_library(chained) == "libEGL.so.1")
check("G un errore qualsiasi non viene scambiato per una libreria che manca",
      guard.missing_library(ImportError("No module named 'cv2'")) is None
      and guard.missing_library(ValueError("libx.so.1: cannot open shared object file")) is None
      and guard.missing_library(None) is None)
check("G finestra di sistema su Linux: kdialog, poi zenity, poi xmessage, altrimenti niente",
      guard.linux_dialog("t", which=lambda n: True)[0] == "kdialog"
      and guard.linux_dialog("t", which=lambda n: n != "kdialog")[0] == "zenity"
      and guard.linux_dialog("t", which=lambda n: n == "xmessage")[0] == "xmessage"
      and guard.linux_dialog("t", which=lambda n: False) is None)
code = ("import sys; sys.path.insert(0, %r)\nfrom freelasercut import startup_guard as g\ng.install()\n"
        "raise ImportError('libgthread-2.0.so.0: cannot open shared object file: No such file or directory')\n" % ROOT)
env = dict(os.environ, APPDATA=tempfile.mkdtemp(), FLC_NO_DIALOGS="1")
env["XDG_CONFIG_HOME"] = env["APPDATA"]
pr = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, encoding="utf-8",
                    errors="replace", env=env, timeout=120)
logs = ""
for d_, _, fs in os.walk(env["APPDATA"]):
    for f in fs:
        if f == guard.LOG:
            logs += open(os.path.join(d_, f), encoding="utf-8", errors="replace").read()
check("G avvio vero con la libreria che manca: il messaggio esce e resta scritto in flc.log con il comando",
      pr.returncode != 0 and "sudo zypper install libgthread-2_0-0" in pr.stderr
      and "sudo zypper install libgthread-2_0-0" in logs and "ImportError" in logs, pr.stderr[-300:])
wf = open(os.path.join(ROOT, ".github", "workflows", "installatore.yml"), encoding="utf-8").read()
m = re.search(r"image: opensuse/leap:16\.0\s+setup: (.*)", wf)
check("G prova dell'AppImage dentro openSUSE, senza installare il pacchetto di libgthread (deve portarla l'AppImage)",
      m is not None and "libgthread" not in m.group(1) and "libglib-2_0-0" in m.group(1))
check("G il sistema di costruzione ha il pacchetto da cui prendere libgthread", "libxcb-xkb1 libglib2.0-0 file" in wf)
lic = open(os.path.join(ROOT, "LICENZE-TERZE-PARTI.md"), encoding="utf-8").read()
check("G licenza della libreria aggiunta (GLib, LGPL 2.1)", "glib-LGPL-2.1.txt" in lic and "libgthread" in lic
      and os.path.getsize(os.path.join(ROOT, "licenze-terze-parti", "glib-LGPL-2.1.txt")) > 20000)

# ====================================================================== H. ringraziamenti
print("--- H. ringraziamenti")
N = len(thanks.NAMES)
check("H un solo elenco: 12 nomi, nessun doppione, «Roberto C.» senza cognome, Deborah",
      N == 12 and len(set(thanks.NAMES)) == N and "Roberto C." in thanks.NAMES and "Deborah" in thanks.NAMES
      and not any("cappellero" in n.lower() for n in thanks.NAMES) and thanks.NAMES[0] == "Stefano Modena")
it = thanks.endless()
seq = [next(it) for _ in range(N * 6)]
check("H i nomi a ripetizione: sempre nell'ordine dell'elenco, e finito l'elenco si ricomincia",
      tuple(seq) == thanks.NAMES * 6)
check("H elenco vuoto o con un nome solo: nessun errore", list(thanks.endless([])) == []
      and [x for x, _ in zip(thanks.endless(["Uno"]), range(3))] == ["Uno"] * 3)
rows = thanks.layout_rows(thanks.endless(), lambda t: 10.0 * len(t), 500.0, 9, lead="Grazie a")
flat = [t for row in rows for t, _, _ in row if t != "·"]
check("H trama: 9 righe, la prima comincia con «Grazie a», tre spazi e il primo nome",
      len(rows) == 9 and rows[0][0][0] == "Grazie a\u00a0\u00a0\u00a0Stefano Modena" and rows[0][0][1] == 0.0)
flat[0] = flat[0].split("\u00a0")[-1]
check("H trama: solo nomi interi, di seguito da una riga all'altra", flat == seq[:len(flat)] and len(flat) > N)
check("H trama: ogni riga va da un bordo all'altro (primo pezzo a sinistra, ultimo che finisce a destra)",
      all(r[0][1] == 0.0 and (len(r) == 1 or abs(r[-1][1] + r[-1][2] - 500.0) < 1e-6) for r in rows))
check("H trama: fra due nomi c'è sempre un «·» con lo stesso spazio ai due lati",
      all(r[i][0] == "·" and abs((r[i][1] - (r[i - 1][1] + r[i - 1][2])) - (r[i + 1][1] - (r[i][1] + r[i][2]))) < 1e-6
          for r in rows for i in range(1, len(r), 2)) and all(len(r) % 2 == 1 for r in rows))
check("H trama: nessuna riga più larga dello spazio", all(sum(x[2] for x in r) <= 500.0 + 1e-6 for r in rows))
long_rows = thanks.layout_rows(iter(["x" * 80, "corto"]), lambda t: 10.0 * len(t), 500.0, 3)
check("H un nome più largo della riga resta intero su una riga sua; finiti i nomi le righe restano vuote",
      [len(r) for r in long_rows] == [1, 1, 0])
two = thanks.layout_rows(thanks.endless(), [lambda t: 20.0 * len(t), lambda t: 8.0 * len(t)], 500.0, 2, gap=[12, 5])
check("H righe di grandezza diversa: in quella grande entrano meno nomi che in quella piccola, i nomi proseguono",
      len([x for x in two[0] if x[0] != "·"]) < len([x for x in two[1] if x[0] != "·"])
      and [x[0] for r in two for x in r if x[0] != "·"] == seq[:sum(len(r) // 2 + 1 for r in two)])
check("H stesso nome con la stessa grandezza: contato (i «·» non contano)",
      thanks.same_size_repeats([[("A", 0, 1), ("·", 1, 1), ("B", 2, 1)], [("A", 0, 1)], [("B", 0, 1)]], [20, 20, 24]) == 1
      and thanks.same_size_repeats([[("A", 0, 1)], [("A", 0, 1)]], [20, 22], min_diff=4) == 1
      and thanks.same_size_repeats([[("A", 0, 1)], [("A", 0, 1)]], [20, 24], min_diff=4) == 0)
check("H quanti nomi entrano in una riga: almeno uno, mai lo stesso due volte, «Grazie a» conta nella prima",
      thanks.row_count(["aa", "bb", "cc"], 0, lambda t: 10.0 * len(t), 1000.0) == 3
      and thanks.row_count(["aa", "bb", "cc"], 1, lambda t: 10.0 * len(t), 50.0, gap=2) == 1
      and thanks.row_count(["x" * 99], 0, lambda t: 10.0 * len(t), 50.0) == 1 and thanks.row_count([], 0, len, 50.0) == 0
      and thanks.row_count(["aa", "bb"], 0, lambda t: 10.0 * len(t), 60.0, lead="Grazie a", gap=2) == 1)
plan = thanks.plan_sizes(list("ABCDEFGHIJKL"), 9, (30, 27, 24, 21, 18, 16), lambda r, pos, px: max(1, 60 // px), 198, 24)
check("H scelta delle grandezze: 9 righe, la prima non troppo grande, righe vicine diverse, dentro lo spazio",
      plan is not None and len(plan) == 9 and plan[0] <= 24 and sum(plan) <= 198
      and all(abs(plan[i] - plan[i + 1]) >= 5 for i in range(8)), str(plan))
check("H scelta delle grandezze impossibile (una sola grandezza): lo dice invece di inventare",
      thanks.plan_sizes(list("ABC"), 9, (20,), lambda r, pos, px: 3, 198, 24) is None)
rr = splash.name_rows()
W_IN = splash.W - 2 * splash.SIDE
check("H schermata di avvio: 9 righe che vanno da un bordo all'altro con il carattere vero",
      len(rr) == splash.ROWS == 9 and all(r.items and abs(r.items[-1][1] + r.items[-1][2] - W_IN) < 0.5 for r in rr))
sizes_ = [r.px for r in rr]
check("H grandezze irregolari e alternate: almeno quattro grandezze, righe vicine sempre diverse, grandi e piccole",
      len(set(sizes_)) >= 4 and all(abs(sizes_[i] - sizes_[i + 1]) >= 5 for i in range(8))
      and max(sizes_) >= 27 and min(sizes_) <= 18, str(sizes_))
all_names = [n for r in rr for n in r.names()]
check("H i nomi sono nell'ordine dell'elenco, di seguito, e ricominciano dal primo",
      all_names == seq[:len(all_names)] and len(all_names) > N, str(all_names[:14]))
by_name = {}
for r in rr:
    for n in r.names():
        by_name.setdefault(n, []).append(r.px)
check("H lo stesso nome, quando ricompare, ha una grandezza diversa (almeno 4 pixel)",
      splash.repeats_same_size(rr) == 0 and all(abs(a - b) >= splash.SIZE_DIFF for v in by_name.values() for a, b in zip(v, v[1:]))
      and any(len(v) > 1 for v in by_name.values()), str(by_name))
check("H tutti i nomi dell'elenco compaiono almeno una volta, Deborah compresa", set(by_name) == set(thanks.NAMES))
check("H «Grazie a» ha la stessa grandezza del primo nome (è un pezzo solo con lui)",
      rr[0].items[0][0].endswith("\u00a0\u00a0\u00a0" + thanks.NAMES[0]) and rr[0].px <= splash.FIRST_MAX)
check("H le righe non si sovrappongono e non entrano nella fascia in basso (raggio, versione, messaggio)",
      all(rr[i].bottom <= rr[i + 1].top + 0.01 for i in range(8)) and rr[-1].bottom <= splash.BAND_TOP and rr[0].top >= 0)
check("H più una riga è grande più è tenue", all(a.alpha <= b.alpha for a in rr for b in rr if a.px > b.px))
for extra in (["Uno"], ["Uno", "Due"], list(thanks.NAMES) + ["Nuovo Nome", "altro-utente-42", "Z"]):
    r_ = splash.name_rows(extra)
    check(f"H con un elenco di {len(extra)} nomi la trama si fa lo stesso (righe dentro i margini e sopra la fascia)",
          len(r_) == 9 and r_[-1].bottom <= splash.BAND_TOP
          and all(not r.items or r.items[-1][1] + r.items[-1][2] <= W_IN + 0.5 or len(r.items) == 1 for r in r_))
check("H …e con più nomi di adesso un nome ripetuto ha ancora grandezze diverse",
      splash.repeats_same_size(splash.name_rows(list(thanks.NAMES) + ["Nuovo Nome", "altro-utente-42", "Z"])) == 0)
leads = {}
lang0 = i18n.language()
for lang in ("it", "en", "es", "fr", "pt"):
    i18n.set_language(lang)
    r = splash.name_rows()
    leads[lang] = r[0].items[0][0].split("\u00a0")[0]
    names_only = [n for row in r for n in row.names()]
    if not set(names_only) <= set(thanks.NAMES) or splash.repeats_same_size(r):
        leads[lang] = "NOMI CAMBIATI"
i18n.set_language(lang0)
check("H «Grazie a» nelle cinque lingue, senza due punti; i nomi non si traducono e cambiano sempre grandezza",
      leads == {"it": "Grazie a", "en": "Thanks to", "es": "Gracias a", "fr": "Merci à", "pt": "Obrigado a"}, str(leads))
check("H tempi: una riga in 1,6 s, righe sfalsate di 0,17 s, tutto in circa 3 secondi",
      splash.ROW_S == 1.6 and splash.STAGGER_S == 0.17 and 2.9 <= splash.ENGRAVE_S <= 3.2 and splash.MIN_SHOW_S == 3.0)
check("H avanzamento di una riga: 0 prima di partire, 1 alla fine, sfalsato",
      splash.row_progress(0.0, 0) == 0 and close(splash.row_progress(0.8, 0), 0.5) and splash.row_progress(1.6, 0) == 1
      and splash.row_progress(0.17 * 8, 8) == 0 and splash.row_progress(9.0, 8) == 1)
RR = splash.name_rows()


def arr(img):
    img = img.convertToFormat(QImage.Format_ARGB32)
    return np.frombuffer(bytes(img.constBits()), np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4].copy()


f0, f0b = arr(splash.render(0.0)), arr(splash.render(0.0, names=[]))
f1, f2, f4, f9 = (arr(splash.render(t)) for t in (1.0, 2.0, 4.0, 9.0))
check("H all'apertura (t = 0) non c'è ancora nessun nome", np.array_equal(f0, f0b))
def fronts(a):
    """Per ogni riga della trama, fin dove è arrivata l'incisione (ultima colonna diversa dalla schermata vuota)."""
    dif = (a.reshape(a.shape[0], -1, 4) != f0.reshape(f0.shape[0], -1, 4)).any(axis=2)
    out = []
    for row in RR:
        cols = np.nonzero(dif[int(row.top) + 4:int(row.bottom) - 4].any(axis=0))[0]
        out.append(int(cols.max()) if cols.size else -1)
    return out


f05, f15, f25 = (arr(splash.render(t)) for t in (0.5, 1.5, 2.5))
fr_ = [fronts(x) for x in (f05, f1, f15, f2, f25, f4)]
check("H l'incisione avanza con il tempo e non torna indietro, riga per riga",
      fr_[0][0] > 50 and all(fr_[k][i] <= fr_[k + 1][i] + 8 for k in range(5) for i in range(9))
      and all(fr_[k] != fr_[k + 1] for k in range(5)), str(fr_))
check("H le righe partono una dopo l'altra (a mezzo secondo le ultime non sono ancora cominciate) e alla fine ci sono tutte",
      fr_[0][-1] == -1 and fr_[0][0] > fr_[0][1] > fr_[0][2] and min(fr_[-1]) > splash.W * 0.8, str(fr_[0]) + str(fr_[-1]))
left, right = f1[:, :(splash.W // 3) * 4], f1[:, (splash.W * 2 // 3) * 4:]
check("H si incide da sinistra a destra: a metà della prima riga la destra è ancora vuota",
      (left[10:36] != f0[10:36, :(splash.W // 3) * 4]).any() and not (right[10:36] != f0[10:36, (splash.W * 2 // 3) * 4:]).any())
check("H finita l'incisione la schermata resta ferma (stato finale uguale a qualsiasi tempo dopo)", np.array_equal(f4, f9))
band = slice(249, 300)
check("H la fascia in basso non cambia mai", np.array_equal(f0[band], f4[band]) and np.array_equal(f0[band], f2[band]))
low = splash.Splash(splash._pixmap(1.0), min_show=0.0, clock=lambda: 2.0)
low._t0 = 0.0
low.rows[-1].top = splash.BAND_TOP - 9  # una riga messa apposta a cavallo della fascia in basso


def paint_low(t):
    low._clock = lambda: t
    img = QImage(splash.W, splash.H, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    q = __import__("PySide6.QtGui", fromlist=["QPainter"]).QPainter(img)
    q.drawPixmap(0, 0, splash._pixmap(1.0))
    low.drawContents(q)
    q.end()
    return arr(img)


l2, l9 = paint_low(2.0), paint_low(9.0)
check("H anche con una riga troppo in basso, nomi e alone non entrano mai nella fascia in basso",
      np.array_equal(l2[band], f0[band]) and np.array_equal(l9[band], f0[band]) and not np.array_equal(l9[200:249], f0[200:249]))
hot = lambda a: int(((a[..., 2::4].astype(int) > 200) & (a[..., 0::4].astype(int) < 190)).sum())  # noqa: E731
check("H durante l'incisione c'è il tratto caldo (arancio), alla fine non più",
      hot(f2[:250]) > hot(f0[:250]) + 30 and hot(f4[:250]) <= hot(f0[:250]) + 5, f"{hot(f0[:250])} {hot(f2[:250])} {hot(f4[:250])}")
fm = arr(splash.render(4.0, msg="Apro il piano di lavoro…"))
diff_rows = np.nonzero((fm != f4).any(axis=1))[0]
diff_cols = np.nonzero((fm != f4).any(axis=0))[0] // 4
check("H il messaggio dell'avvio sta in basso a sinistra, fuori dalla trama",
      diff_rows.size > 0 and diff_rows.min() >= 255 and diff_cols.max() < 330, f"{diff_rows.min() if diff_rows.size else None}")
check("H senza schermo vero non c'è attesa", splash.headless())


class Clock:
    def __init__(self, step=0.05):
        self.t, self.step = 100.0, step

    def __call__(self):
        self.t += self.step
        return self.t


sp_ = splash.Splash(splash._pixmap(1.0))
check("H nelle prove (senza schermo) l'attesa minima è zero", sp_.min_show == 0.0)
sp_.show()
t0 = time.time()
waited = sp_.wait_min()
check("H …e wait_min torna subito", time.time() - t0 < 0.3 and waited < 0.3)
n_meta = len(sys.meta_path)
sp_.install_pulse()
sp_.install_pulse()
check("H il cercatore che fa ridisegnare si installa una volta sola, in testa", len(sys.meta_path) == n_meta + 1
      and sys.meta_path[0] is sp_._hook)
hook = sp_._hook
sp_._last = -1.0
fr = sp_.frames
check("H il cercatore non trova mai niente (Python carica i moduli come sempre)…", hook.find_spec("colorsys") is None)
check("H …ma fa ridisegnare la schermata", sp_.frames == fr + 1)
fr = sp_.frames
hook.find_spec("x")
check("H non più di 40 ridisegni al secondo", sp_.frames == fr)
import colorsys  # noqa: E402,F401  (un modulo vero caricato con il cercatore installato)

check("H un modulo vero si carica normalmente con la schermata aperta", "colorsys" in sys.modules)
sp_._last = -1.0
fr = sp_.frames
th = threading.Thread(target=lambda: hook.find_spec("y"))
th.start()
th.join()
check("H da un altro thread non si ridisegna mai", sp_.frames == fr)
sp_._busy = True
sp_._last = -1.0
check("H mai un ridisegno dentro un altro ridisegno", sp_.pulse() is False)
sp_._busy = False
sp_.hide()
sp_._last = -1.0
check("H a schermata nascosta (scelta dell'interfaccia, errori) non si ridisegna", sp_.pulse() is False)
sp_.show()
sp_._t0 = sp_._clock() - 60
sp_._last = -1.0
sp_.pulse()
fr = sp_.frames
time.sleep(0.04)
check("H a incisione finita non si ridisegna più a ogni modulo", sp_.pulse() is False and sp_.frames == fr and sp_.engraved())
sp_.say("ciao")
check("H un messaggio nuovo ridisegna sempre", sp_.frames == fr + 1 and sp_._msg == "ciao")
sp_.pulse = lambda: (_ for _ in ()).throw(RuntimeError("guasto"))
check("H un errore nel ridisegno non ferma il caricamento: il cercatore si spegne da solo",
      hook.find_spec("z") is None and hook.splash is None)
del sp_.pulse
sp_.finish(w)
check("H alla fine il cercatore viene tolto", len(sys.meta_path) == n_meta and sp_._hook is None)
ck = Clock()
sp2 = splash.Splash(splash._pixmap(1.0), min_show=3.0, clock=ck)
sp2.show()
real0 = time.time()
waited = sp2.wait_min()
check("H con uno schermo vero la schermata resta fino alla fine dell'incisione (almeno 3 secondi dall'apertura)",
      sp2.elapsed() >= max(3.0, splash.ENGRAVE_S) and waited > 2.5 and sp2.frames > 5, f"{sp2.elapsed():.2f} {waited:.2f}")
check("H …con il tempo già passato non aspetta", sp2.wait_min() < 0.2)
sp2.hide()
ck3 = Clock()
sp3 = splash.Splash(splash._pixmap(1.0), min_show=3.0, clock=ck3)
check("H a schermata nascosta l'attesa non blocca niente", sp3.wait_min() < 0.2)
sp3.show()
_pn = sp3.paint_names
sp3.paint_names = lambda p, t: (time.sleep(splash.SLOW_FRAME_S + 0.03), _pn(p, t))[1]
sp3.repaint()
sp3.repaint()
check("H PC troppo lento per l'animazione: dopo due ridisegni lenti si passa allo stato finale e non si aspetta",
      sp3._final and sp3.engraved() and sp3.wait_min() < 0.2)
sp3.close()
check("H chiudendo la schermata (errore d'avvio) il cercatore non resta", sp3._hook is None)
sp4 = splash.Splash(splash._pixmap(1.0), names=[])
sp4.show()
sp4.repaint()
check("H senza nomi la schermata si disegna lo stesso", sp4.frames >= 1 and all(not r.items for r in sp4.rows))
sp4.close()
msrc = inspect.getsource(sys.modules["freelasercut.ui.main_window"].main)
check("H l'attesa si fa a finestra principale già costruita e prima di mostrarla (non tocca errori e scelta dell'interfaccia)",
      msrc.index("win = MainWindow()") < msrc.index("splash.wait_min()") < msrc.index("win.show()")
      and msrc.index("ChoiceDialog().exec()") < msrc.index("win = MainWindow()"))
bsrc = inspect.getsource(sys.modules["freelasercut.splash"].show_splash)
check("H la schermata con i nomi compare a ogni avvio (nessuna impostazione per spegnerla)",
      "install_pulse" in bsrc and "qs" not in bsrc and "QSettings" not in open(splash.__file__, encoding="utf-8").read())
# targa in Aiuto
check("H la targa non si apre da sola all'avvio", not hasattr(w, "_thanks_dlg"))
acts = w.m_help.actions()
check("H Aiuto → Ringraziamenti, dopo «Informazioni»", w.acts["thanks"] in acts
      and acts.index(w.acts["thanks"]) == acts.index(w.acts["about"]) + 1)
w.acts["thanks"].trigger()
td = w._thanks_dlg
check("H la targa mostra tutti e soli i nomi dell'elenco", td.names() == list(thanks.NAMES))
btn_texts = [b.text() for b in td.findChildren(QPushButton)]
check("H solo da leggere: un solo pulsante, «Chiudi» (niente targa da incidere)", btn_texts == [i18n.tr("Chiudi")], str(btn_texts))
td.resize(640, 460)
td.show()
spin()
items = td.view.layout_items()
fmw = __import__("PySide6.QtGui", fromlist=["QFontMetricsF"]).QFontMetricsF(td.view.font_())
check("H i nomi vanno a capo interi dentro la finestra", len(items) == N
      and all(x + fmw.horizontalAdvance(n) <= td.view.width() + 1 for n, _, x in items) and td.view.rows() >= 2)
check("H senza schermo i nomi sono subito tutti visibili", td.view.progress(N - 1) == 1.0)
nv = dialogs_thanks.NamesView(animate=True)
check("H con uno schermo vero compaiono uno dopo l'altro e poi restano",
      nv.progress(0, 0.0) == 0 and nv.progress(0, dialogs_thanks.FIRST_S + dialogs_thanks.NAME_S) == 1
      and nv.progress(3, dialogs_thanks.FIRST_S + 0.2) == 0 and nv.progress(N - 1, nv.duration() + 0.01) == 1
      and 0 < nv.progress(0, dialogs_thanks.FIRST_S + 0.5) < 1)
td.close()
# rapporto
rd = dialogs_report.ReportDialog(w)
check("H rapporto: campo facoltativo «Nome per i ringraziamenti», vuoto di partenza, con la nota su dove comparirà",
      rd.thanks_name.text() == "" and rd.thanks_name.maxLength() == 40 and support.SUPPORT_EMAIL in rd.thanks_note.text())
u = rd.user()
check("H campo vuoto: nel rapporto non c'è niente sui ringraziamenti",
      "grazie" not in u and "ringraziamenti" not in diag.user_text(u).lower()
      and "ringraziamenti" not in support.payload(b"x", "C", u)["descrizione"].lower()
      and "ringraziamenti" not in support.mailto("C", u).lower())
rd.thanks_name.setText("  Mario   R.  ")
u = rd.user()
check("H campo compilato: il nome (ripulito dagli spazi) entra nella descrizione", u.get("grazie") == "Mario R."
      and "Mario R." in diag.user_text(u) and "Mario R." in support.payload(b"x", "C", u)["descrizione"]
      and "Mario%20R." in support.mailto("C", u))
zp = rd.build(os.path.join(tempfile.mkdtemp(), "r.zip"))
with zipfile.ZipFile(zp) as z:
    desc = z.read("descrizione.txt").decode("utf-8")
check("H …e nel file del rapporto", "Mario R." in desc and "ringraziamenti" in desc.lower())
rd.reject()
# README, sito, privacy: gli stessi nomi
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
site = open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8").read()
priv = open(os.path.join(ROOT, "docs", "privacy.html"), encoding="utf-8").read()
m = re.search(r"## Ringraziamenti\n(.*?)\n## ", readme, re.S)
check("H README: la sezione Ringraziamenti ha tutti i nomi dell'elenco, nello stesso ordine",
      m is not None and ", ".join(thanks.NAMES) in m.group(1))
m = re.search(r'<p id="thanks-names"[^>]*>(.*?)</p>', site, re.S)
check("H sito: gli stessi nomi, tutti e soli", m is not None and [x.strip() for x in m.group(1).split("·")] == list(thanks.NAMES))
check("H informativa privacy: dice del nome facoltativo e che è l'unica cosa che può diventare pubblica (inglese e italiano)",
      "Name for the acknowledgements" in priv and "Nome per i ringraziamenti" in priv
      and "Nothing else from your report is published" in priv and "Nient'altro del tuo rapporto viene pubblicato" in priv
      and "16 November 2026" in priv)

# ====================================================================== I. traduzioni
print("--- I. traduzioni")
NEW = ["Grazie a", "Ringraziamenti", "Nome per i ringraziamenti", "Grazie.", "piano bianco", "Sfondo del piano: {0}",
       "Sfondo del piano: {0}. Clic: {1}", "foto della camera del piano", "foto a mosaico della camera della testa",
       "Un valore negativo raccorda l'angolo verso l'interno", "Con questi valori l'offset non produce forme",
       "Positivo: angoli arrotondati. Negativo: angoli raccordati verso l'interno. 0: spigoli vivi",
       "Rettangoli: un valore negativo raccorda gli angoli verso l'interno",
       "facoltativo: nome o pseudonimo, se vuoi comparire fra i ringraziamenti",
       "Vuoi esserci anche tu? Scrivi il tuo nome quando mandi un rapporto all'assistenza."]
for lang in ("en", "es", "fr", "pt"):
    cat = json.load(open(os.path.join(ROOT, "freelasercut", "locale", f"{lang}.json"), encoding="utf-8"))
    miss = [s for s in NEW if not cat.get(s) or cat[s] == s]
    ph = [s for s in NEW if s in cat and sorted(re.findall(r"\{\d\}", s)) != sorted(re.findall(r"\{\d\}", cat[s]))]
    check(f"I {lang}: i testi nuovi sono tradotti, con gli stessi segnaposto", not miss and not ph, str(miss + ph))

check("nessun errore nascosto durante le prove", not hidden, repr(hidden[:2]))
ok = sum(results)
print(f"\n{TAG}: {ok}/{len(results)}")
sys.exit(0 if ok == len(results) else 1)
