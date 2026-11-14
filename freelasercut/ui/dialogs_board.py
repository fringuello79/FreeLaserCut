# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Tavola da 2 angoli (0.19.6, camera della testa, fase 2): il mirino su due spigoli dello stesso lato della tavola
e l'altra misura scritta a mano danno posizione, angolo e contorno della tavola. Il contorno va sul livello strumenti
(mai inciso); «Ruota la selezione come la tavola» gira il disegno dello stesso angolo. Conti in core/headcam.py."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from ..core import headcam as H
from ..core.document import PathShape
from .editor import TOOL_LAYER
from freelasercut.i18n import tr  # noqa: E402


class BoardDialog(QDialog):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.win = panel.win
        self.ed = self.win.editor
        self.pts = [None, None]
        self.board = None
        self.setWindowTitle(tr("Tavola da 2 angoli"))
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        v = QVBoxLayout(self)
        intro = QLabel(tr("Porta il mirino della camera sullo spigolo in basso a sinistra della tavola e premi "
                          "«Segna 1», poi sullo spigolo in basso a destra e premi «Segna 2». Scrivi quanto è "
                          "profonda la tavola. Va bene anche un altro lato: la tavola sta alla sinistra della "
                          "direzione da 1 a 2."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.auto = QCheckBox(tr("Trova lo spigolo da solo nell'immagine (se non è sicuro usa il mirino)"))
        v.addWidget(self.auto)
        f = QFormLayout()
        self.lab = [QLabel("—"), QLabel("—")]
        for i in (0, 1):
            row = QHBoxLayout()
            b = QPushButton(tr("Segna {0}", i + 1))
            b.clicked.connect(lambda _=False, k=i: self.mark(k))
            row.addWidget(b)
            row.addWidget(self.lab[i], 1)
            f.addRow(tr("Spigolo {0}", i + 1), row)
        self.height_mm = QDoubleSpinBox()
        self.height_mm.setRange(1.0, 2000.0)
        self.height_mm.setDecimals(1)
        self.height_mm.setSuffix(" mm")
        qs = getattr(self.win, "qs", None)
        try:
            self.height_mm.setValue(float(qs.value("board_height", 100.0)) if qs is not None else 100.0)
        except (TypeError, ValueError):
            self.height_mm.setValue(100.0)
        self.height_mm.valueChanged.connect(self._update)
        f.addRow(tr("Profondità della tavola"), self.height_mm)
        v.addLayout(f)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        v.addWidget(self.result)
        row = QHBoxLayout()
        self.b_draw = QPushButton(tr("Disegna il contorno"))
        self.b_draw.setToolTip(tr("Sul livello strumenti, che non si incide mai"))
        self.b_draw.clicked.connect(self.draw_outline)
        self.b_rot = QPushButton(tr("Ruota la selezione come la tavola"))
        self.b_rot.clicked.connect(self.rotate_selection)
        row.addWidget(self.b_draw)
        row.addWidget(self.b_rot)
        v.addLayout(row)
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.close)
        v.addWidget(close)
        self._update()

    def mark(self, i, point=None):
        """Segna lo spigolo i (0 o 1) dove guarda il mirino (o nel punto dato, per le prove)."""
        if point is None:
            point, note = self.panel.crosshair_bed(auto=self.auto.isChecked())
            if point is None:
                self.lab[i].setText(note)
                return False
        else:
            note = tr("mirino")
        self.pts[i] = (float(point[0]), float(point[1]))
        self.lab[i].setText(tr("X {0:.2f}  Y {1:.2f} mm · {2}", point[0], point[1], note))
        self._update()
        return True

    def _update(self, *_):
        qs = getattr(self.win, "qs", None)
        if qs is not None:
            qs.setValue("board_height", self.height_mm.value())
        self.board = None
        if None not in self.pts:
            self.board = H.board_from_corners(self.pts[0], self.pts[1], self.height_mm.value())
        if self.board is None:
            self.result.setText(tr("Segna i due spigoli (almeno 1 mm l'uno dall'altro).") if None not in self.pts
                                else "")
        else:
            self.result.setText(tr("Tavola {0:.1f} × {1:.1f} mm, storta di {2:+.2f}° rispetto all'asse X.",
                                   self.board["width"], self.board["height"], self.board["angle"]))
        self.b_draw.setEnabled(self.board is not None)
        self.b_rot.setEnabled(self.board is not None)

    def draw_outline(self):
        if self.board is None:
            return None
        p = QPainterPath()
        c = self.board["corners"]
        p.moveTo(*c[0])
        for q in c[1:]:
            p.lineTo(*q)
        p.closeSubpath()
        shape = PathShape(p, layer=TOOL_LAYER)
        self.ed.add([shape], tr("Contorno della tavola"))
        return shape

    def rotate_selection(self):
        if self.board is None:
            return False
        sel = [s for s in self.ed.editable() if s.layer != TOOL_LAYER]
        if not sel:
            self.result.setText(self.result.text().split("\n")[0] + "\n" + tr("Seleziona prima il disegno da ruotare."))
            return False
        self.ed.select(sel)
        self.ed.rotate(self.board["angle"])
        return True
