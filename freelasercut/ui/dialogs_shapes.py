# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Crea una forma con misure esatte: tipo, larghezza, altezza, posizione del centro, parametro."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout,
)

from ..core import shapes_lib
from ..core.document import EllipseShape, PolygonShape, RectShape, SpecialShape
from . import style
from freelasercut.i18n import tr  # noqa: E402

BASIC = [("rect", tr("Rettangolo"), tr("Raggio angoli (mm)"), 0, 500, 0, 2), ("ellipse", tr("Ellisse / cerchio"), "—", 0, 1, 0, 0),
         ("polygon", tr("Poligono"), tr("Lati"), 3, 64, 6, 0), ("star", tr("Stella"), tr("Punte"), 3, 64, 5, 0)]


def _spin(lo, hi, val, dec=2, suffix=" mm"):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(dec)
    w.setValue(val)
    w.setSuffix(suffix)
    w.setKeyboardTracking(False)
    return w


class ExactShapeDialog(QDialog):
    def __init__(self, center, layer, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Crea forma con misure esatte"))
        self.layer = layer
        f = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.setMaxVisibleItems(30)
        for key, name, *_ in BASIC:
            self.kind.addItem(style.icon({"rect": "rect", "ellipse": "ellipse", "polygon": "polygon", "star": "star"}[key]),
                              name, ("basic", key))
        self.kind.insertSeparator(self.kind.count())
        from .panels_design import shape_icon

        for key, spec in shapes_lib.SHAPES.items():
            self.kind.addItem(shape_icon(key, 16), spec[0], ("special", key))
        f.addRow(tr("Forma"), self.kind)
        self.w = _spin(0.1, 2000, 50)
        self.h = _spin(0.1, 2000, 50)
        self.lock = QCheckBox(tr("Proporzioni naturali (altezza calcolata)"))
        f.addRow(tr("Larghezza"), self.w)
        f.addRow(tr("Altezza"), self.h)
        f.addRow("", self.lock)
        self.cx = _spin(-2000, 4000, center[0])
        self.cy = _spin(-2000, 4000, center[1])
        f.addRow(tr("Centro X"), self.cx)
        f.addRow(tr("Centro Y"), self.cy)
        self.plab = QLabel("")
        self.param = _spin(0, 1, 0, 2, "")
        f.addRow(self.plab, self.param)
        hint = QLabel(tr("I campi accettano anche i calcoli, per esempio 120/3. Il centro predefinito è quello del piano "
                      "(o della testa, se la macchina è connessa)."))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        f.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Crea"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.kind.currentIndexChanged.connect(self._kind)
        self.lock.toggled.connect(self._aspect)
        self.w.valueChanged.connect(self._aspect)
        self._kind()

    def _spec(self):
        kind, key = self.kind.currentData()
        if kind == "basic":
            b = next(b for b in BASIC if b[0] == key)
            return kind, key, b[2], b[3], b[4], b[5], b[6]
        s = shapes_lib.SHAPES[key]
        return kind, key, s[1], s[2], s[3], s[4], s[5]

    def _kind(self):
        kind, key, lab, lo, hi, val, dec = self._spec()
        show = lab != "—"
        self.plab.setText(lab.replace(" (mm)", "") if show else "")
        self.param.setVisible(show)
        self.plab.setVisible(show)
        self.param.setDecimals(dec)
        self.param.setRange(lo, hi)
        self.param.setValue(val)
        self.param.setSuffix(tr(" mm") if "mm" in lab else "")
        self.param.setSingleStep(1 if dec == 0 else 0.05)
        self.lock.setEnabled(kind == "special")
        self._aspect()

    def _aspect(self, *_):
        kind, key, *_r = self._spec()
        self.h.setEnabled(not (self.lock.isChecked() and kind == "special"))
        if kind == "special" and self.lock.isChecked():
            self.h.setValue(self.w.value() / shapes_lib.natural_aspect(key))

    def shape(self):
        kind, key, *_ = self._spec()
        w, h, t = self.w.value(), self.h.value(), self.param.value()
        if kind == "special":
            s = SpecialShape(key, w, h, t, layer=self.layer)
        elif key == "rect":
            s = RectShape(w, h, t, layer=self.layer)
        elif key == "ellipse":
            s = EllipseShape(w, h, layer=self.layer)
        elif key == "polygon":
            s = PolygonShape(w, h, int(t), 0.0, layer=self.layer)
        else:
            s = PolygonShape(w, h, int(t), 0.5, layer=self.layer)
        from PySide6.QtGui import QTransform

        b = s.path().boundingRect()
        s.apply(QTransform.fromTranslate(self.cx.value() - b.center().x(), self.cy.value() - b.center().y()))
        return s


# ======================================================================= fessure degli incastri (0.20.9)
def _shape_polys(shape):
    """[(punti, chiuso)] di una forma (tutte le sue parti), in mm sul piano."""
    from ..core import geom

    out = []
    for leaf, tf in shape.leaves():
        for poly in geom.flatten(tf.map(leaf.local_path()), 0.01):
            out.append(([tuple(p) for p in poly.pts], bool(poly.closed)))
    return out


def resize_slots(editor, shapes, old, new, tol=0.1):
    """Cambia le fessure delle forme e le sostituisce (un'azione sola di Annulla). -> (cambiate, saltate) o None se
    le misure non vanno."""
    from ..core import slots

    polys = [_shape_polys(s) for s in shapes]
    try:
        res, done, skipped, changed = slots.resize(polys, old, new, tol)
    except ValueError:
        editor.message.emit(tr("Misure non valide: servono due larghezze maggiori di zero e una tolleranza più "
                               "piccola di metà fessura"))
        return None
    if not done:
        return 0, skipped
    _replace_shapes(editor, shapes, res, changed, tr("Fessure da {0:g} a {1:g} mm", float(old), float(new)))
    return done, skipped


def _replace_shapes(editor, shapes, res, changed, label):
    """Sostituisce le forme cambiate con tracciati (un'azione sola di Annulla)."""
    from PySide6.QtGui import QPainterPath

    from ..core.document import PathShape

    old_shapes, made = [], []
    for si in changed:
        s = shapes[si]
        path = QPainterPath()
        for pts, closed in res[si]:
            if len(pts) < 2:
                continue
            path.moveTo(*pts[0])
            for p in pts[1:]:
                path.lineTo(*p)
            if closed:
                path.closeSubpath()
        layers = {leaf.layer for leaf, _ in s.leaves()}
        ps = PathShape(path, layer=s.layer if len(layers) != 1 else layers.pop())
        old_shapes.append(s)
        made.append(ps)
    editor.replace(old_shapes, made, label)


# ======================================================================= spessore del materiale (0.22.0)
def change_thickness(editor, shapes, old, new, tol=0.3):
    """Adatta fessure, tacche e linguette delle forme dallo spessore old a new (un'azione sola di Annulla).
    -> ({tipo: cambiate}, saltate) o None se le misure non vanno."""
    from ..core import slots

    polys = [_shape_polys(s) for s in shapes]
    try:
        res, done, skipped, changed = slots.change_thickness(polys, old, new, tol)
    except ValueError:
        editor.message.emit(tr("Misure non valide: servono due spessori maggiori di zero e una tolleranza più "
                               "piccola di metà spessore"))
        return None
    if changed:
        _replace_shapes(editor, shapes, res, changed,
                        tr("Incastri da {0:g} a {1:g} mm di spessore", float(old), float(new)))
    return done, len(skipped)


def thickness_text(cnt):
    """«22 fessure e fori, 32 tacche, 42 linguette» (solo le voci che ci sono)."""
    parts = []
    if cnt.get("fessura"):
        parts.append(tr("{0} fessure e fori", cnt["fessura"]))
    if cnt.get("tacca"):
        parts.append(tr("{0} tacche", cnt["tacca"]))
    if cnt.get("linguetta"):
        parts.append(tr("{0} linguette", cnt["linguetta"]))
    return ", ".join(parts) or tr("nessun incastro")


class ThicknessDialog(QDialog):
    """0.22.0: lo spessore per cui è disegnato il pezzo (trovato da solo), lo spessore nuovo; anteprima sul piano."""

    def __init__(self, win, shapes):
        from ..core import slots

        super().__init__(win)
        self.win, self.shapes = win, shapes
        self._polys = [_shape_polys(s) for s in shapes]
        self.found_list = slots.detect(self._polys)
        self.setWindowTitle(tr("Adatta gli incastri allo spessore"))
        v = QVBoxLayout(self)
        intro = QLabel(tr("Per usare il disegno con un materiale di spessore diverso. Cambiano insieme la larghezza "
                          "di fessure e fori, la profondità delle tacche e la lunghezza delle linguette; il gioco del "
                          "disegno resta (un foro da 3,9 per 4 mm diventa da 4,9 per 5 mm). Nei bordi a dita le punte "
                          "restano dove sono, quindi le misure esterne non cambiano."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.found = QLabel()
        self.found.setWordWrap(True)
        v.addWidget(self.found)
        f = QFormLayout()
        qs = getattr(win, "qs", None)
        try:
            last_new = float(qs.value("thick_new", 0) or 0) if qs is not None else 0.0
        except (TypeError, ValueError):
            last_new = 0.0
        guess = self.found_list[0][0] if self.found_list else 3.0
        self.old = _spin(0.5, 30, guess)
        self.new = _spin(0.5, 30, last_new if last_new > 0 and abs(last_new - guess) > 1e-9 else guess)
        self.tol = _spin(0.0, 2, 0.3)
        f.addRow(tr("Spessore del disegno"), self.old)
        f.addRow(tr("Spessore nuovo"), self.new)
        f.addRow(tr("Tolleranza"), self.tol)
        v.addLayout(f)
        self.result = QLabel()
        self.result.setObjectName("muted")
        self.result.setWordWrap(True)
        v.addWidget(self.result)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok = bb.button(QDialogButtonBox.Ok)
        v.addWidget(bb)
        if self.found_list:
            t, cnt = self.found_list[0]
            self.found.setText(tr("Il disegno sembra fatto per un materiale da <b>{0:g} mm</b>: {1}.", t,
                                  thickness_text(cnt)))
        else:
            self.found.setText(tr("Nel disegno non ho trovato incastri riconoscibili: scrivi tu lo spessore per cui "
                                  "è fatto."))
        for sp in (self.old, self.new, self.tol):
            sp.valueChanged.connect(self._update)
        self._update()

    def values(self):
        return self.old.value(), self.new.value(), self.tol.value()

    def _update(self, *_):
        from PySide6.QtGui import QPainterPath

        from ..core import slots

        old, new, tol = self.values()
        try:
            res, done, skipped, _ch = slots.change_thickness(self._polys, old, new, tol)
        except ValueError:
            self.result.setText(tr("La tolleranza deve essere più piccola di metà spessore"))
            self.ok.setEnabled(False)
            return
        n = sum(done.values())
        txt = tr("Cambiano: {0}.", thickness_text(done)) if n else tr("Nessun incastro da {0:g} mm (± {1:g}).", old, tol)
        if skipped:
            txt += " " + tr("{0} restano come sono (troppo vicini a un altro incastro o al bordo).", len(skipped))
        self.result.setText(txt)
        self.ok.setEnabled(n > 0 and abs(new - old) > 1e-9)
        paths = []
        for shape in res:
            p = QPainterPath()
            for pts, closed in shape:
                if len(pts) > 1:
                    p.moveTo(*pts[0])
                    for q in pts[1:]:
                        p.lineTo(*q)
                    if closed:
                        p.closeSubpath()
            paths.append(p)
        cv = getattr(self.win, "canvas", None)
        if cv is not None:
            cv.overlay_paths = paths if n else []
            cv.viewport().update()

    def accept(self):
        qs = getattr(self.win, "qs", None)
        if qs is not None:
            qs.setValue("thick_new", self.new.value())
        super().accept()


class SlotsDialog(QDialog):
    """Misura delle fessure di adesso, misura nuova, tolleranza; quante ne trova, con l'anteprima sul piano."""

    def __init__(self, win, shapes):
        super().__init__(win)
        self.win, self.shapes = win, shapes
        self._polys = [_shape_polys(s) for s in shapes]
        self.setWindowTitle(tr("Larghezza delle fessure"))
        v = QVBoxLayout(self)
        intro = QLabel(tr("Cambia solo le fessure di quella misura (tacche sul bordo e fori degli incastri): il centro "
                          "resta dov'è e la profondità non cambia. Le linguette della stessa misura non si toccano."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        f = QFormLayout()
        qs = getattr(win, "qs", None)

        def last(key, d):
            try:
                return float(qs.value(key, d)) if qs is not None else d
            except (TypeError, ValueError):
                return d
        self.old = _spin(0.1, 100, last("slots_old", 3.0))
        self.new = _spin(0.1, 100, last("slots_new", 4.0))
        self.tol = _spin(0.0, 5, 0.1)
        f.addRow(tr("Larghezza di adesso"), self.old)
        f.addRow(tr("Larghezza nuova"), self.new)
        f.addRow(tr("Tolleranza"), self.tol)
        v.addLayout(f)
        self.found = QLabel()
        self.found.setObjectName("muted")
        v.addWidget(self.found)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok = bb.button(QDialogButtonBox.Ok)
        v.addWidget(bb)
        for sp in (self.old, self.new, self.tol):
            sp.valueChanged.connect(self._update)
        self._update()

    def values(self):
        return self.old.value(), self.new.value(), self.tol.value()

    def _update(self, *_):
        from PySide6.QtGui import QPainterPath

        from ..core import slots

        old, new, tol = self.values()
        try:
            res, done, skipped, _ch = slots.resize(self._polys, old, new, tol)
        except ValueError:
            self.found.setText(tr("La tolleranza deve essere più piccola di metà fessura"))
            self.ok.setEnabled(False)
            return
        txt = tr("Fessure trovate: {0}", done + skipped)
        if skipped:
            txt += " · " + tr("{0} troppo vicine, restano come sono", skipped)
        self.found.setText(txt)
        self.ok.setEnabled(done > 0 and abs(new - old) > 1e-9)
        paths = []
        for shape in res:
            p = QPainterPath()
            for pts, closed in shape:
                if len(pts) > 1:
                    p.moveTo(*pts[0])
                    for q in pts[1:]:
                        p.lineTo(*q)
                    if closed:
                        p.closeSubpath()
            paths.append(p)
        cv = getattr(self.win, "canvas", None)
        if cv is not None:
            cv.overlay_paths = paths if done else []
            cv.viewport().update()

    def accept(self):
        qs = getattr(self.win, "qs", None)
        if qs is not None:
            qs.setValue("slots_old", self.old.value())
            qs.setValue("slots_new", self.new.value())
        super().accept()
