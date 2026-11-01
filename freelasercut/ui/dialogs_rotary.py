# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Laser → Rotativo: accessorio a rulli o a mandrino collegato al posto del motore dell'asse Y."""
import math

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout,
)

from ..core import gcode
from freelasercut.i18n import tr  # noqa: E402


def _spin(lo, hi, val, dec=2, suffix=" mm"):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    s.setSuffix(suffix)
    return s


class RotaryDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        qs = main.qs
        self.setWindowTitle(tr("Rotativo"))
        self.setMinimumWidth(500)
        v = QVBoxLayout(self)
        intro = QLabel(tr("Per incidere bicchieri, borracce, bottiglie e cilindri: il rotativo si collega al posto del "
                          "motore dell'asse Y e gira l'oggetto. Disegna come su un foglio: l'altezza del disegno è la "
                          "parte di circonferenza da incidere. FreeLaserCut scala da solo l'asse Y e la velocità."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.on = QCheckBox(tr("Rotativo attivo"))
        self.on.setChecked(qs.value("rotary_on", "false") in (True, "true"))
        v.addWidget(self.on)
        f = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem(tr("A rulli (l'oggetto appoggia su due rulli)"), "roller")
        self.kind.addItem(tr("A mandrino (l'oggetto è stretto nelle griffe)"), "chuck")
        self.kind.setCurrentIndex(max(0, self.kind.findData(qs.value("rotary_kind", "roller"))))
        f.addRow(tr("Tipo"), self.kind)
        self.mm_rev = _spin(1, 10000, float(qs.value("rotary_mm_rev", 100.0)))
        self.mm_rev.setToolTip(tr("Quanti mm di asse Y deve comandare la scheda perché il rullo (o il mandrino) "
                                  "faccia un giro completo. Si trova con la prova qui sotto."))
        test = QPushButton(tr("Prova: un giro"))
        test.setToolTip(tr("Muove l'asse Y del valore indicato: il rullo (o il mandrino) deve fare esattamente un giro"))
        test.clicked.connect(self.test_rev)
        row = QHBoxLayout()
        row.addWidget(self.mm_rev, 1)
        row.addWidget(test)
        f.addRow(tr("Asse Y per un giro"), row)
        self.roller = _spin(1, 500, float(qs.value("rotary_roller_d", 25.0)))
        f.addRow(tr("Diametro del rullo"), self.roller)
        self.obj = _spin(1, 1000, float(qs.value("rotary_object_d", 70.0)))
        self.obj.setToolTip(tr("Misuralo col calibro nel punto da incidere"))
        f.addRow(tr("Diametro dell'oggetto"), self.obj)
        v.addLayout(f)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("muted")
        v.addWidget(self.info)
        warn = QLabel(tr("Prima di incidere: metti a fuoco sul punto più alto dell'oggetto, in «Partenza» scegli la "
                         "posizione attuale della testa e fai il contorno. Spegni il rotativo quando torni al piano normale."))
        warn.setWordWrap(True)
        v.addWidget(warn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for w in (self.mm_rev, self.roller, self.obj):
            w.valueChanged.connect(self.update_info)
        self.kind.currentIndexChanged.connect(self.update_info)
        self.on.toggled.connect(self.update_info)
        self.update_info()

    def settings(self):
        return {"kind": self.kind.currentData(), "mm_per_rev": self.mm_rev.value(), "roller_d": self.roller.value(),
                "object_d": self.obj.value()}

    def update_info(self, *_):
        roller = self.kind.currentData() == "roller"
        self.roller.setEnabled(roller)
        k = gcode.rotary_scale(self.settings())
        circ = math.pi * self.obj.value()
        self.info.setText(tr("Circonferenza dell'oggetto: {0:.1f} mm (altezza massima del disegno che fa il giro "
                             "completo) · asse Y × {1:.4f}", circ, k))

    def test_rev(self):
        ctl = self.main.ctl
        if not ctl.connected or ctl.job_active:
            self.info.setText(tr("Connetti la macchina per la prova."))
            return
        ctl.jog(0.0, self.mm_rev.value(), 1500)

    def accept(self):
        qs = self.main.qs
        s = self.settings()
        qs.setValue("rotary_on", self.on.isChecked())
        qs.setValue("rotary_kind", s["kind"])
        qs.setValue("rotary_mm_rev", s["mm_per_rev"])
        qs.setValue("rotary_roller_d", s["roller_d"])
        qs.setValue("rotary_object_d", s["object_d"])
        super().accept()
