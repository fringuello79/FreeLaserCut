# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Modifica → Semplifica tracciati (0.19.6): meno nodi, curve lisce e tratti dritti entro una tolleranza in mm.

Anteprima sul piano mentre si cambiano i valori, con nodi e tratti di G-code prima e dopo e lo scarto massimo
misurato; un solo passo nella cronologia all'OK, nessuno con Annulla (come «Distanza esatta»). Il calcolo è in
core/simplify.py; progetto e casi provati nel documento «aggiornamento-0.19.6».
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
                               QVBoxLayout)

from ..core import simplify as S
from freelasercut.i18n import tr  # noqa: E402

DELAY_MS = 150  # dopo l'ultima modifica di un valore, prima di ricalcolare l'anteprima


def _qs_float(qs, key, default, lo, hi):
    try:
        v = float(qs.value(key, default)) if qs is not None else default
    except (TypeError, ValueError):
        v = default
    return min(hi, max(lo, v))


class SimplifyDialog(QDialog):
    def __init__(self, main, items, skipped):
        super().__init__(main)
        self.main, self.ed = main, main.editor
        self.items = items  # [(foglia PathShape, trasformazione completa)]
        self.orig = [(leaf, QPainterPath(leaf.local_path())) for leaf, _ in items]  # per ripartire sempre da qui
        self.skipped = skipped
        self.stats = S.Stats()
        qs = getattr(main, "qs", None)
        self.setWindowTitle(tr("Semplifica tracciati"))
        self.setMinimumWidth(440)
        v = QVBoxLayout(self)
        intro = QLabel(tr("Ricostruisce i tracciati scelti con meno nodi: curve lisce e tratti dritti che non si "
                          "scostano dall'originale più della tolleranza. Utile su vettorizzazioni e DXF con tanti "
                          "segmenti piccoli."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        f = QFormLayout()
        self.tol = QDoubleSpinBox()
        self.tol.setRange(S.TOL_MIN, S.TOL_MAX)
        self.tol.setDecimals(2)
        self.tol.setSingleStep(0.01)
        self.tol.setSuffix(" mm")
        self.tol.setValue(_qs_float(qs, "simplify/tol", S.TOL_DEFAULT, S.TOL_MIN, S.TOL_MAX))
        self.tol.setToolTip(tr("Quanto il risultato può scostarsi dall'originale ({0:g}–{1:g} mm). Più è alta, meno "
                               "nodi e linee più morbide.", S.TOL_MIN, S.TOL_MAX))
        f.addRow(tr("Tolleranza"), self.tol)
        self.angle = QDoubleSpinBox()
        self.angle.setRange(S.ANGLE_MIN, S.ANGLE_MAX)
        self.angle.setDecimals(0)
        self.angle.setSingleStep(5)
        self.angle.setSuffix("°")
        self.angle.setValue(_qs_float(qs, "simplify/angle", S.ANGLE_DEFAULT, S.ANGLE_MIN, S.ANGLE_MAX))
        self.angle.setToolTip(tr("Dove la linea cambia direzione più di questo angolo resta uno spigolo vivo; sotto, "
                                 "la curva passa liscia."))
        f.addRow(tr("Spigoli vivi sopra"), self.angle)
        self.lines = QCheckBox(tr("Solo tratti dritti (meno righe di G-code)"))
        on = qs.value("simplify/lines_only", False) if qs is not None else False
        self.lines.setChecked(on in (True, "true", "1", 1))
        self.lines.setToolTip(tr("Niente curve: solo segmenti. Il file per la macchina diventa più corto; le curve "
                                 "strette restano a spezzata entro la tolleranza."))
        f.addRow("", self.lines)
        v.addLayout(f)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.note = QLabel(tr("{0} forme non sono tracciati (rettangoli, testi, codici…) e restano come sono: per "
                              "semplificarle usa prima Converti in tracciato.", skipped))
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.setVisible(skipped > 0)
        v.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(DELAY_MS)
        self.timer.timeout.connect(self._live)
        self.ed.begin(tr("Semplifica tracciati"))  # prima di qualsiasi modifica
        for w in (self.tol, self.angle):
            w.valueChanged.connect(lambda *_: self.timer.start())
        self.lines.toggled.connect(lambda *_: self.timer.start())
        self._live()

    def values(self):
        return S.clamp_tol(self.tol.value()), S.clamp_angle(self.angle.value()), self.lines.isChecked()

    def _live(self):
        self.timer.stop()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for leaf, p in self.orig:  # si riparte sempre dall'originale
                leaf.set_path(p)
            changes, st = S.plan(self.items, *self.values())
            self.ed.apply_simplified(changes)
        finally:
            QApplication.restoreOverrideCursor()
        st.skipped = self.skipped
        self.stats = st
        if not st.changed:
            self.info.setText(tr("Niente da semplificare con questi valori: i tracciati restano come sono."))
        else:
            self.info.setText(tr("Nodi: {0} → {1}", st.nodes_before, st.nodes_after) + "\n" +
                              tr("Tratti di G-code: {0} → {1}", st.gcode_before, st.gcode_after) + "\n" +
                              tr("Scarto massimo misurato: {0:.3f} mm", st.max_err) + "\n" +
                              tr("Tracciati cambiati: {0} di {1}", st.shapes, len(self.items)))
        self.ed.preview_changed()

    def accept(self):
        if self.timer.isActive():
            self._live()
        qs = getattr(self.main, "qs", None)
        if qs is not None:
            tol, angle, lines = self.values()
            qs.setValue("simplify/tol", tol)
            qs.setValue("simplify/angle", angle)
            qs.setValue("simplify/lines_only", lines)
        self.ed.commit()
        if self.stats.changed:
            self.ed.message.emit(tr("Semplificati {0} tracciati: nodi da {1} a {2}", self.stats.shapes,
                                    self.stats.nodes_before, self.stats.nodes_after))
        super().accept()

    def reject(self):
        self.timer.stop()
        self.ed.cancel()
        super().reject()


def make_simplify_dialog(main):
    """La finestra pronta, oppure None con il motivo nella barra di stato (serve almeno un tracciato sbloccato)."""
    items, skipped = S.targets(main.editor.editable())
    if not items:
        main.editor.message.emit(tr("Seleziona dei tracciati da semplificare (rettangoli e testi: prima Converti in "
                                    "tracciato)"))
        return None
    return SimplifyDialog(main, items, skipped)
