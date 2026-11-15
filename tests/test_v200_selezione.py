# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.0: selezione più visibile (rapporto FLC-20261114-1709-2449: «il tratteggio si vede male, io la metterei in
evidenza cambiandola di colore»).

Matrice dei casi:
1 forma selezionata: linea piena continua (nessun buco del vecchio tratteggio) del colore d'accento;
2 alone trasparente ai due lati della linea; 3 forma del livello blu (stesso colore dell'accento): l'alone la distingue;
4 forma non selezionata: niente alone; 5 deselezione: l'alone sparisce; 6 più forme: tutte evidenziate;
7 forma ruotata e in un gruppo; 8 oltre SEL_HALO_MAX forme: solo la linea piena; 9 tema chiaro e scuro; Banco.
"""
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
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QTransform
from PySide6.QtWidgets import QApplication

app = QApplication([])
from freelasercut.core.document import GroupShape, RectShape
from freelasercut.theme import C
from freelasercut.ui import canvas as cvmod
from freelasercut.ui.main_window import MainWindow

results = []


def check(name, cond, info=""):
    results.append(bool(cond))
    print(("OK  " if cond else "NO  ") + name + (f"  [{info}]" if info and not cond else ""))


w = MainWindow()
w.resize(1400, 900)
w.show()
app.processEvents()
ed, cv = w.editor, w.canvas
ACC = QColor(C["accent"])
ACC_HI = QColor(C["accent_hi"])


def mk(x, y, ww=60, hh=40, layer=0):
    s = RectShape(ww, hh, layer=layer)
    b = s.bounds()
    s.apply(QTransform.fromTranslate(x - b.left(), y - b.top()))
    return s


def fresh(shapes, sel=()):
    ed.doc.shapes.clear()
    ed.selection = []
    ed.add(list(shapes), select=False)
    ed.selection = list(sel)
    ed.selection_changed.emit()
    app.processEvents()


def frame():
    cv.viewport().update()
    app.processEvents()
    return cv.viewport().grab().toImage()


def dist(c, ref):
    return abs(c.red() - ref.red()) + abs(c.green() - ref.green()) + abs(c.blue() - ref.blue())


def bluish(c, base):
    """Il pixel è stato spinto verso l'accento rispetto allo sfondo."""
    return dist(c, ACC) < dist(base, ACC) - 25


def view_pt(x, y):
    v = cv.bed_to_view_tf().map(QPointF(x, y))
    dpr = cv.viewport().devicePixelRatioF()
    return int(round(v.x() * dpr)), int(round(v.y() * dpr))


def edge_samples(img, x0, x1, y, n=60, skip=()):
    """Pixel lungo il lato orizzontale y (mm) da x0 a x1, presi sulla linea (lontano dalle maniglie in skip)."""
    out = []
    for i in range(n):
        x = x0 + (x1 - x0) * (i + 0.5) / n
        if any(abs(x - k) < 5 for k in skip):
            continue
        px, py = view_pt(x, y)
        # la linea larga 2 px può cadere a cavallo di due righe: si prende la più vicina all'accento
        out.append(min((img.pixelColor(px, py + d) for d in (-1, 0, 1)), key=lambda c: dist(c, ACC_HI)))
    return out


def halo_px(img, x, y, off_px):
    px, py = view_pt(x, y)
    return img.pixelColor(px, py - off_px), img.pixelColor(px, py + off_px)


def run_checks(tag):
    # forma lontana dalle altre, al centro del piano
    a = mk(100, 100, 80, 50, layer=0)
    fresh([a])
    base = frame()
    bg_above, bg_below = halo_px(base, 120, 150, 2)
    fresh([a], [a])
    img = frame()
    line = edge_samples(img, 104, 176, 150, skip=(140,))
    on = [dist(c, ACC_HI) < 90 or dist(c, ACC) < 90 for c in line]
    check(f"{tag}: 1 linea della selezione continua (nessun buco del tratteggio)", all(on), f"{on.count(False)} buchi")
    up, dn = halo_px(img, 120, 150, 2)
    check(f"{tag}: 2 alone sopra e sotto la linea", bluish(up, bg_above) and bluish(dn, bg_below),
          f"{up.name()} {dn.name()} su {bg_above.name()}")
    far, far0 = halo_px(img, 120, 150, 9)[0], halo_px(base, 120, 150, 9)[0]
    check(f"{tag}: 2b l'alone resta stretto (a 9 px lo sfondo)", dist(far, far0) < 20, f"{far.name()} {far0.name()}")
    # 4/5 non selezionata e deselezione
    fresh([a])
    img2 = frame()
    up2, _ = halo_px(img2, 120, 150, 2)
    check(f"{tag}: 4-5 senza selezione niente alone", dist(up2, bg_above) < 15, up2.name())
    # 3 livello blu (stesso colore dell'accento)
    b = mk(100, 100, 80, 50, layer=1)
    fresh([b])
    plain = frame()
    pu, _ = halo_px(plain, 120, 150, 2)
    fresh([b], [b])
    sel = frame()
    su, _ = halo_px(sel, 120, 150, 2)
    check(f"{tag}: 3 forma del livello blu: selezionata si distingue", bluish(su, pu), f"{su.name()} vs {pu.name()}")
    # 6 più forme
    s1, s2 = mk(40, 40, 30, 20), mk(200, 60, 30, 20)
    fresh([s1, s2], [s1, s2])
    img = frame()
    ok = all(bluish(halo_px(img, x, y, 3)[0], bg_above) for x, y in ((55, 60), (215, 80)))
    check(f"{tag}: 6 due forme selezionate tutte e due evidenziate", ok)
    # 7 ruotata in un gruppo
    r = mk(100, 100, 80, 50)
    r.apply(QTransform().translate(140, 125).rotate(90).translate(-140, -125))
    g = GroupShape([r], layer=0)
    fresh([g], [g])
    img = frame()
    # ruotato di 90° attorno al centro (140,125): lato superiore ora a y = 125 + 40 = 165
    up, dn = halo_px(img, 128, 165, 2)
    check(f"{tag}: 7 gruppo con forma ruotata evidenziato al posto giusto",
          bluish(up, bg_above) or bluish(dn, bg_below), f"{up.name()} {dn.name()}")
    # 8 troppe forme: solo la linea
    many = [mk(10 + (i % 25) * 2.0, 250 + (i // 25) * 2.0, 1, 1) for i in range(cvmod.SEL_HALO_MAX + 5)]
    big = mk(100, 100, 80, 50)
    fresh(many + [big])
    up0, _ = halo_px(frame(), 120, 150, 3)
    fresh(many + [big], many + [big])
    img = frame()
    line = edge_samples(img, 104, 176, 150)
    bad = [c.name() for c in line if not (dist(c, ACC_HI) < 90 or dist(c, ACC) < 90)]
    up, _ = halo_px(img, 120, 150, 3)
    check(f"{tag}: 8 oltre {cvmod.SEL_HALO_MAX} forme la linea c'è", not bad, " ".join(bad[:5]))
    check(f"{tag}: 8b oltre {cvmod.SEL_HALO_MAX} forme niente alone", dist(up, up0) < 15, f"{up.name()} {up0.name()}")


ed.doc.shapes.clear()
cv.fit_bed()
app.processEvents()
run_checks("Tema " + os.environ.get("FLC_THEME", "predefinito") + " · " + os.environ["FLC_UI"])

n_ok = sum(results)
print(f"\n{n_ok}/{len(results)} prove superate")
sys.exit(0 if n_ok == len(results) else 1)
