# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Disponi → Ottimizza lo spazio: i pezzi si sistemano sul materiale sprecandone il meno possibile."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ..core import geom, nesting
from ..core.document import ImageShape
from .editor import TOOL_LAYER
from freelasercut.i18n import tr  # noqa: E402


def _spin(lo, hi, val, suffix=" mm", dec=1):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    s.setSuffix(suffix)
    return s


def sheet_shape(editor):
    """La forma chiusa selezionata sul livello T1 (il contorno del materiale), se c'è."""
    for s in editor.selection:
        if s.layer == TOOL_LAYER and not isinstance(s, ImageShape) and s.closed():
            return s
    return None


def pieces(editor, sheet=None):
    """Pezzi da disporre: la selezione (senza il materiale), altrimenti tutte le forme visibili e non bloccate."""
    src = editor.selection if editor.selection else editor.doc.shapes
    return [s for s in src if s is not sheet and not s.locked and not s.hidden and s.layer != TOOL_LAYER]


class NestDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.ed = main.editor
        qs = main.qs
        self.setWindowTitle(tr("Ottimizza lo spazio"))
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        intro = QLabel(tr("Sistema i pezzi sul materiale sprecandone il meno possibile: usa la sagoma vera di ogni pezzo "
                          "(non il rettangolo che lo contiene), li ruota se lo permetti e li compatta verso l'origine. "
                          "Si annulla con Ctrl+Z."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.sheet = sheet_shape(self.ed)
        self.parts = pieces(self.ed, self.sheet)
        self.what = QLabel()
        self.what.setWordWrap(True)
        self.what.setObjectName("muted")
        v.addWidget(self.what)
        f = QFormLayout()
        self.area = QComboBox()
        self.area.addItem(tr("Piano di lavoro intero"), "bed")
        if self.sheet is not None:
            self.area.addItem(tr("Forma selezionata sul livello T1 (il materiale)"), "sheet")
        self.area.addItem(tr("Rettangolo su misura"), "custom")
        self.area.setToolTip(tr("Disegna il contorno del pannello (anche un avanzo irregolare) sul livello T1, selezionalo "
                                "insieme ai pezzi e i pezzi andranno lì dentro"))
        f.addRow(tr("Materiale"), self.area)
        self.custom = QWidget()
        cl = QHBoxLayout(self.custom)
        cl.setContentsMargins(0, 0, 0, 0)
        p = main.profile
        self.cx, self.cy = _spin(-5000, 5000, 0.0), _spin(-5000, 5000, 0.0)
        self.cw, self.ch = _spin(1, 5000, min(300.0, p.bed_x)), _spin(1, 5000, min(200.0, p.bed_y))
        for lab, w in (("X", self.cx), ("Y", self.cy), (tr("L"), self.cw), (tr("A"), self.ch)):
            cl.addWidget(QLabel(lab))
            cl.addWidget(w)
        f.addRow("", self.custom)
        self.gap = _spin(0, 50, float(qs.value("nest_gap", 2.0)))
        self.gap.setToolTip(tr("Spazio libero tra un pezzo e l'altro: almeno lo spessore del taglio più un po' di sicurezza"))
        f.addRow(tr("Distanza tra i pezzi"), self.gap)
        self.margin = _spin(0, 50, float(qs.value("nest_margin", 1.0)))
        self.margin.setToolTip(tr("Spazio lasciato libero lungo il bordo del materiale"))
        f.addRow(tr("Margine dal bordo"), self.margin)
        self.rot = QComboBox()
        for code, label in (("none", tr("Nessuna (orientamento invariato)")), ("180", tr("Solo capovolti (180°)")),
                            ("90", tr("Di 90° in 90°")), ("45", tr("Di 45° in 45°")), ("15", tr("Di 15° in 15° (più lento)"))):
            self.rot.addItem(label, code)
        self.rot.setCurrentIndex(max(0, self.rot.findData(qs.value("nest_rot", "90"))))
        self.rot.setToolTip(tr("Con le venature del legno o le foto conviene «Nessuna» o «Solo capovolti»"))
        f.addRow(tr("Rotazioni"), self.rot)
        self.prec = QComboBox()
        self.prec.addItem(tr("Normale"), "normal")
        self.prec.addItem(tr("Alta (più lenta)"), "high")
        f.addRow(tr("Precisione"), self.prec)
        v.addLayout(f)
        self.keep = QCheckBox(tr("Tieni insieme le forme che stanno una dentro l'altra"))
        self.keep.setChecked(qs.value("nest_keep", "true") in (True, "true"))
        self.keep.setToolTip(tr("Così un'incisione resta dentro il suo contorno di taglio anche se non sono raggruppati"))
        v.addWidget(self.keep)
        self.holes = QCheckBox(tr("Usa anche i fori interni dei pezzi (solo se sono tagliati da parte a parte)"))
        self.holes.setChecked(False)
        v.addWidget(self.holes)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.RichText)
        v.addWidget(self.result)
        bb = QHBoxLayout()
        bb.addStretch(1)
        self.b_close = QPushButton(tr("Chiudi"))
        self.b_close.clicked.connect(self.accept)
        self.b_run = QPushButton(tr("Disponi"))
        self.b_run.setObjectName("primary")
        self.b_run.setDefault(True)
        self.b_run.clicked.connect(self.run)
        bb.addWidget(self.b_close)
        bb.addWidget(self.b_run)
        v.addLayout(bb)
        self.area.currentIndexChanged.connect(self._area_changed)
        if self.sheet is not None:
            self.area.setCurrentIndex(self.area.findData("sheet"))
        self._area_changed()
        self._describe()

    def _describe(self):
        n = len(self.parts)
        if not n:
            self.what.setText(tr("Non ci sono pezzi da disporre (le forme bloccate, nascoste o sul livello T1 restano ferme)."))
            self.b_run.setEnabled(False)
        elif self.ed.selection:
            self.what.setText(tr("Pezzi: le {0} forme selezionate. Le altre forme sul piano restano ferme e vengono evitate.", n))
        else:
            self.what.setText(tr("Pezzi: tutte le {0} forme del progetto (nessuna selezione). Le forme bloccate restano ferme "
                                 "e vengono evitate.", n))

    def _area_changed(self, *_):
        self.custom.setVisible(self.area.currentData() == "custom")

    def area_polys(self):
        mode = self.area.currentData()
        if mode == "sheet" and self.sheet is not None:
            return geom.flatten(self.sheet.path(), 0.1)
        if mode == "custom":
            x, y, w, h = self.cx.value(), self.cy.value(), self.cw.value(), self.ch.value()
        else:
            x, y, w, h = 0.0, 0.0, self.main.profile.bed_x, self.main.profile.bed_y
        return [geom.Poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], True)]

    def run(self):
        qs = self.main.qs
        qs.setValue("nest_gap", self.gap.value())
        qs.setValue("nest_margin", self.margin.value())
        qs.setValue("nest_rot", self.rot.currentData())
        qs.setValue("nest_keep", self.keep.isChecked())
        moving = set(self.parts)
        obstacles = [s for s in self.ed.doc.shapes if s not in moving and s is not self.sheet and not s.hidden
                     and s.layer != TOOL_LAYER]
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        self.result.setText(tr("Calcolo in corso…"))
        QApplication.processEvents()
        try:
            res = nesting.nest_shapes(self.parts, self.area_polys(), obstacles, keep_touching=self.keep.isChecked(),
                                      spacing=self.gap.value(), margin=self.margin.value(),
                                      rotations=self.rot.currentData(), fill_holes=not self.holes.isChecked(),
                                      precision=self.prec.currentData(),
                                      tick=lambda: (QApplication.processEvents(), False)[1])
        finally:
            QGuiApplication.restoreOverrideCursor()
        if res.placements:
            self.ed.run(tr("Ottimizza lo spazio"), nesting.apply, res)
        placed = [s for g in res.placements for s in g]
        left = [s for g in res.unplaced for s in g]
        self.ed.select(left if left else placed)
        msg = tr("<b>Pezzi sistemati: {0}</b> · materiale usato {1:.0f} × {2:.0f} mm · utilizzo {3:.0f}%",
                 len(res.placements), res.used_w, res.used_h, res.efficiency * 100)
        if res.unplaced:
            msg += "<br>" + tr("<span style='color:#E5484D'>Pezzi che non entrano: {0}. Restano dove erano e sono "
                               "selezionati.</span>", len(res.unplaced))
        self.result.setText(msg)
        self.main.statusBar().showMessage(self.result.text().replace("<b>", "").replace("</b>", "").split("<br>")[0], 8000)
        self.last = res
        return res
