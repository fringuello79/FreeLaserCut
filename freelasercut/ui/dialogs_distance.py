# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Disponi → Distanza esatta (0.17.16): un oggetto a una distanza scritta in mm da un altro, come in un programma CAD.

Progetto e casi provati nel documento «distanze-parametriche». In breve: ingombri come in «Allinea»; si sposta solo
l'oggetto non fermo e solo lungo l'asse scelto; il lato si decide dalle posizioni all'apertura; anteprima dal vivo
con un solo passo nella cronologia all'OK, nessuno con Annulla.
"""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
                               QVBoxLayout)

from ..core import ops
from freelasercut.i18n import tr  # noqa: E402

MAX_D = 5000.0


def _edge_labels(axis):
    if axis == "x":
        return (("min", tr("Bordo sinistro")), ("center", tr("Centro")), ("max", tr("Bordo destro")))
    return (("min", tr("Bordo in basso")), ("center", tr("Centro")), ("max", tr("Bordo in alto")))


class DistanceDialog(QDialog):
    def __init__(self, main, first, second):
        super().__init__(main)
        self.main, self.ed = main, main.editor
        self.pair = [first, second]  # in ordine di selezione
        self.orig = [s.bounds() for s in self.pair]  # ingombri all'apertura: tutto si calcola da qui
        self.applied = [(0.0, 0.0), (0.0, 0.0)]  # traslazione già data a ciascuno durante l'anteprima
        self._user_d = False
        self._setting = False
        self.setWindowTitle(tr("Distanza esatta"))
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        f = QFormLayout()

        def name(i):
            b = self.orig[i]
            return tr("{0}° selezionato: {1} {2:.1f} × {3:.1f} mm", i + 1, self.pair[i].describe(), b.width(), b.height())

        self.fixed = QComboBox()
        for i in (0, 1):
            self.fixed.addItem(name(i), i)
        locked = [i for i in (0, 1) if self.pair[i].locked]
        self.fixed.setCurrentIndex(locked[0] if locked else 0)  # bloccato = fermo; altrimenti il primo selezionato
        self.fixed.setEnabled(not locked)
        f.addRow(tr("Resta fermo"), self.fixed)
        self.lbl_moving = QLabel("")
        f.addRow(tr("Si sposta"), self.lbl_moving)
        self.axis = QComboBox()
        self.axis.addItem(tr("Orizzontale (lungo X)"), "x")
        self.axis.addItem(tr("Verticale (lungo Y)"), "y")
        f.addRow(tr("Direzione"), self.axis)
        self.mode = QComboBox()
        self.mode.addItem(tr("Spazio vuoto fra i due"), "gap")
        self.mode.addItem(tr("Fra i centri"), "center")
        self.mode.addItem(tr("Fra i bordi scelti"), "edges")
        f.addRow(tr("Misura"), self.mode)
        self.ef = QComboBox()
        self.em = QComboBox()
        self.lbl_ef = QLabel(tr("Dell'oggetto fermo"))
        self.lbl_em = QLabel(tr("Dell'oggetto che si sposta"))
        f.addRow(self.lbl_ef, self.ef)
        f.addRow(self.lbl_em, self.em)
        self.dist = QDoubleSpinBox()
        self.dist.setRange(0.0, MAX_D)
        self.dist.setDecimals(2)
        self.dist.setSingleStep(0.5)
        self.dist.setSuffix(" mm")
        f.addRow(tr("Distanza"), self.dist)
        self.flip = QCheckBox(tr("Dall'altra parte"))
        self.flip.setToolTip(tr("Porta l'oggetto dall'altro lato di quello fermo"))
        f.addRow("", self.flip)
        v.addLayout(f)
        self.lbl_now = QLabel("")
        self.lbl_now.setObjectName("muted")
        v.addWidget(self.lbl_now)
        self.lbl_warn = QLabel(tr("Attenzione: l'oggetto che si sposta esce dall'area di lavoro."))
        self.lbl_warn.setStyleSheet("color:#d9822b;")
        self.lbl_warn.setWordWrap(True)
        v.addWidget(self.lbl_warn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._fill_edges()
        self.ed.begin(tr("Distanza esatta"))  # prima di qualsiasi spostamento
        self.axis.currentIndexChanged.connect(self._fill_edges)  # prima i bordi del nuovo asse, poi il ricalcolo
        for c in (self.fixed, self.axis, self.mode, self.ef, self.em):
            c.currentIndexChanged.connect(self._changed)
        self.flip.toggled.connect(self._changed)
        self.dist.valueChanged.connect(self._dist_edited)
        self._changed()

    # ------------------------------------------------------------------ modello
    def roles(self):
        """(indice del fermo, indice di chi si sposta)."""
        f = self.fixed.currentData()
        return f, 1 - f

    def side(self):
        f, m = self.roles()
        s = ops.gap_side(self.orig[f], self.orig[m], self.axis.currentData())
        return -s if self.flip.isChecked() else s

    def params(self):
        return (self.axis.currentData(), self.mode.currentData(), self.side(), self.ef.currentData() or "min",
                self.em.currentData() or "min")

    def current_distance(self):
        """Distanza all'apertura con le scelte attuali."""
        f, m = self.roles()
        axis, mode, side, ef, em = self.params()
        return ops.measure_distance(self.orig[f], self.orig[m], axis, mode, side, ef, em)

    def target_shift(self):
        f, m = self.roles()
        axis, mode, side, ef, em = self.params()
        return ops.distance_shift(self.orig[f], self.orig[m], axis, mode, side, self.dist.value(), ef, em)

    def moved_bounds(self):
        f, m = self.roles()
        dx, dy = self.target_shift()
        return self.orig[m].translated(dx, dy)

    # ------------------------------------------------------------------ finestra
    def _fill_edges(self, *_):
        axis = self.axis.currentData()
        for c, default in ((self.ef, "max"), (self.em, "min")):
            keep = c.currentData() or default
            c.blockSignals(True)
            c.clear()
            for k, lab in _edge_labels(axis):
                c.addItem(lab, k)
            c.setCurrentIndex(max(0, c.findData(keep)))
            c.blockSignals(False)

    def _dist_edited(self, *_):
        if not self._setting:
            self._user_d = True
        self._live()

    def _changed(self, *_):
        manual = self.mode.currentData() == "edges"
        for w in (self.ef, self.em, self.lbl_ef, self.lbl_em):
            w.setVisible(manual)
        f, m = self.roles()
        self.lbl_moving.setText(self.fixed.itemText(m))
        now = self.current_distance()
        self.lbl_now.setText(tr("Prima della modifica: {0:.2f} mm", now) if now >= 0 else
                             tr("Prima della modifica gli oggetti si sovrappongono ({0:.2f} mm).", now))
        if not self._user_d:  # finché non si scrive un valore, la distanza parte da quella attuale
            self._setting = True
            self.dist.setValue(min(MAX_D, max(0.0, round(now, 2))))
            self._setting = False
        self._live()

    def _live(self):
        f, m = self.roles()
        want = [(0.0, 0.0), (0.0, 0.0)]
        want[m] = self.target_shift()
        for i in (0, 1):
            dx, dy = want[i][0] - self.applied[i][0], want[i][1] - self.applied[i][1]
            if abs(dx) > 1e-12 or abs(dy) > 1e-12:
                self.pair[i].apply(QTransform.fromTranslate(dx, dy))
            self.applied[i] = want[i]
        p = getattr(self.main, "profile", None)
        area = QRectF(0, 0, p.bed_x, p.bed_y) if p is not None else None
        out = area is not None and not area.adjusted(-1e-6, -1e-6, 1e-6, 1e-6).contains(self.moved_bounds())
        self.lbl_warn.setVisible(out)
        self.ed.preview_changed()

    def accept(self):
        self._live()
        self.ed.commit()
        super().accept()

    def reject(self):
        self.ed.cancel()
        super().reject()


def make_distance_dialog(main):
    """La finestra pronta, oppure None con il motivo nella barra di stato (servono due oggetti, uno almeno sbloccato)."""
    sel = list(main.editor.selection)
    if len(sel) != 2:
        main.editor.message.emit(tr("Seleziona due oggetti: quello che resta fermo e quello da spostare (un gruppo "
                                    "conta come uno)"))
        return None
    if all(s.locked for s in sel):
        main.editor.message.emit(tr("Tutti e due gli oggetti sono bloccati: sbloccane uno per spostarlo"))
        return None
    return DistanceDialog(main, sel[0], sel[1])
