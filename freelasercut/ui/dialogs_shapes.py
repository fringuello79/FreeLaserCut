# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Crea una forma con misure esatte: tipo, larghezza, altezza, posizione del centro, parametro."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel

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
