# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.6: scelte per il progetto da aprire in xTool Studio (xTool M2): modulo laser e quali livelli Linea sono tagli.
La stessa finestra, con lo spessore del materiale in più, serve al lavoro scritto direttamente per la M2 (sperimentale)."""
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QVBoxLayout,
)

from ..core import xtool_m2, xtool_xs
from ..i18n import tr


class XToolExportDialog(QDialog):
    def __init__(self, doc, layers, laser_w=10, parent=None, job=False, thickness=3.0):
        """layers: livelli che finiranno nel progetto (CutSettings), nell'ordine di lavoro.
        job: la finestra del lavoro scritto direttamente per la M2 (sperimentale), con lo spessore del materiale."""
        super().__init__(parent)
        self.job = bool(job)
        v = QVBoxLayout(self)
        if self.job:
            self.setWindowTitle(tr("Lavoro per xTool M2 (sperimentale)"))
            note = QLabel(tr("Funzione in prova. FreeLaserCut scrive il lavoro nel linguaggio della xTool M2, ma non "
                             "lo manda alla macchina e nessuno l'ha ancora provato su una M2 vera: serve a chi ci "
                             "aiuta nelle prove. Per lavorare con la M2 usa «Esporta per xTool Studio (M2)».\n"
                             "Insieme al lavoro viene scritta la cornice, a potenza zero."))
        else:
            self.setWindowTitle(tr("Progetto per xTool Studio (xTool M2)"))
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
        self.thick = QDoubleSpinBox()
        self.thick.setRange(0.0, xtool_m2.Z_DISTANCE - xtool_m2.FOCUS_GAP)
        self.thick.setDecimals(1)
        self.thick.setSingleStep(0.5)
        self.thick.setSuffix(" mm")
        self.thick.setValue(min(max(float(thickness), 0.0), self.thick.maximum()))
        self.thick.setToolTip(tr("Lo spessore del materiale: la M2 mette a fuoco abbassando la testa di conseguenza"))
        if self.job:
            f.addRow(tr("Spessore del materiale"), self.thick)
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
        bb.button(QDialogButtonBox.Ok).setText(tr("Salva il lavoro…") if self.job else tr("Salva il progetto…"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        _ = doc

    def laser_w(self):
        return int(self.laser.currentData())

    def thickness(self):
        return float(self.thick.value())

    def cut_layers(self):
        return {i for i, b in self.cuts.items() if b.isChecked()}
