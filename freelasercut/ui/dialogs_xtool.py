# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6: scelte per il progetto da aprire in xTool Studio (xTool M2): modulo laser e quali livelli Linea sono tagli."""
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from ..core import xtool_xs
from ..i18n import tr


class XToolExportDialog(QDialog):
    def __init__(self, doc, layers, laser_w=10, parent=None):
        """layers: livelli che finiranno nel progetto (CutSettings), nell'ordine di lavoro."""
        super().__init__(parent)
        self.setWindowTitle(tr("Progetto per xTool Studio (xTool M2)"))
        v = QVBoxLayout(self)
        note = QLabel(tr("La xTool M2 lavora solo con xTool Studio: FreeLaserCut non la comanda. Qui prepari un "
                         "progetto con il disegno e con potenza, velocità e passate già impostate; poi lo apri in "
                         "xTool Studio, controlli e avvii il lavoro da lì.\nL'area della M2 è {0:g} × {1:g} mm: "
                         "l'angolo in basso a sinistra del piano resta l'angolo in basso a sinistra della macchina.",
                         xtool_xs.BED[0], xtool_xs.BED[1]))
        note.setWordWrap(True)
        v.addWidget(note)
        f = QFormLayout()
        self.laser = QComboBox()
        for w in xtool_xs.LASERS:
            self.laser.addItem(tr("{0} W", w), w)
        self.laser.setCurrentIndex(max(0, self.laser.findData(int(laser_w))))
        self.laser.setToolTip(tr("Il modulo laser montato sulla M2: xTool Studio lo scrive nel progetto"))
        f.addRow(tr("Modulo laser"), self.laser)
        v.addLayout(f)
        self.cuts = {}
        lines = [cs for cs in layers if cs.mode == "line"]
        if lines:
            lab = QLabel(tr("Livelli in modalità Linea: quali sono tagli? (in xTool Studio «Taglia», gli altri "
                            "«Incisione Linea»)"))
            lab.setWordWrap(True)
            v.addWidget(lab)
            for cs in lines:
                box = QCheckBox(tr("{0}: {1:g} %, {2:g} mm/min, {3} passate", cs.label(), cs.power_max, cs.speed,
                                   cs.passes))
                box.setChecked(xtool_xs.kind_of(cs) == xtool_xs.CUT)
                self.cuts[cs.index] = box
                v.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Salva il progetto…"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        _ = doc

    def laser_w(self):
        return int(self.laser.currentData())

    def cut_layers(self):
        return {i for i, b in self.cuts.items() if b.isChecked()}
