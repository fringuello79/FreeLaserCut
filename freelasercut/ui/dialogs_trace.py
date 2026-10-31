# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Vettorizza immagine: anteprima dal vivo dei tracciati sopra la foto."""
import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget,
)

from ..core import imaging, trace
from ..core.document import LAYER_COLORS
from ..theme import C
from . import style
from .widgets import section
from freelasercut.i18n import tr  # noqa: E402


class _View(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 420)
        self.qimg = None
        self.w = self.h = 1.0
        self.path = None
        self.show_img = True
        self.color = QColor("#FF3B30")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(C["bg"]))
        m = 14
        k = min((self.width() - 2 * m) / self.w, (self.height() - 2 * m) / self.h)
        ox = (self.width() - self.w * k) / 2
        oy = (self.height() - self.h * k) / 2
        target = QRectF(ox, oy, self.w * k, self.h * k)
        p.fillRect(target, QColor("white"))
        if self.qimg is not None and self.show_img:
            p.setOpacity(0.35)
            p.drawImage(target, self.qimg)
            p.setOpacity(1.0)
        if self.path is not None:
            tf = QTransform.fromScale(k, -k) * QTransform.fromTranslate(ox, oy + self.h * k)
            pen = QPen(self.color, 1.4)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setTransform(tf)
            p.drawPath(self.path)
        p.end()


class TraceDialog(QDialog):
    """`shape` è l'ImageShape, `pil` la sua immagine. values() -> (path locale, layer, tieni immagine)."""

    def __init__(self, shape, pil, current_layer=1, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Vettorizza immagine"))
        self.shape = shape
        dark = imaging.to_dark(pil)
        self.dark = imaging.adjust(dark, shape.brightness, shape.contrast, shape.gamma)
        self.auto_t = trace.otsu(self.dark)
        self.result = None
        h = QHBoxLayout(self)
        left = QVBoxLayout()
        h.addLayout(left, 0)
        left.addWidget(section(tr("Vettorizzazione")))
        f = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem(tr("Contorno delle zone scure"), "outline")
        self.mode.addItem(tr("Linea centrale dei tratti"), "centerline")
        self.mode.setToolTip(tr("Linea centrale: scritte a mano, firme e disegni a tratto diventano una linea sola, "
                             "incisa in una passata"))
        f.addRow(tr("Modo"), self.mode)
        self.auto = QCheckBox(tr("Automatica"))
        self.auto.setChecked(True)
        self.thr = self._slider(1, 99, int(self.auto_t * 100))
        self.thr_lab = QLabel("")
        trow = QHBoxLayout()
        trow.addWidget(self.thr, 1)
        trow.addWidget(self.thr_lab)
        trow.addWidget(self.auto)
        f.addRow(tr("Soglia"), trow)
        self.invert = QCheckBox(tr("Inverti (traccia le zone chiare)"))
        f.addRow("", self.invert)
        self.detail = self._slider(0, 100, 60)
        f.addRow(tr("Dettaglio"), self.detail)
        self.smooth = self._slider(0, 100, 50)
        f.addRow(tr("Morbidezza"), self.smooth)
        self.corner = self._slider(20, 120, 55)
        self.corner.setToolTip(tr("Sotto questo angolo di svolta un vertice resta uno spigolo vivo"))
        f.addRow(tr("Spigoli"), self.corner)
        self.speck = self._slider(0, 300, 30)
        self.speck_lab = QLabel("")
        sr = QHBoxLayout()
        sr.addWidget(self.speck, 1)
        sr.addWidget(self.speck_lab)
        f.addRow(tr("Ignora macchie"), sr)
        self.layer = QComboBox()
        for i, col in enumerate(LAYER_COLORS):
            self.layer.addItem(style.icon("rect", col, 14), f"C{i:02d}", i)
        self.layer.setCurrentIndex(max(0, min(current_layer, len(LAYER_COLORS) - 1)))
        f.addRow(tr("Livello"), self.layer)
        self.keep = QCheckBox(tr("Tieni l'immagine"))
        self.keep.setChecked(True)
        f.addRow("", self.keep)
        self.show_img = QCheckBox(tr("Mostra la foto sotto"))
        self.show_img.setChecked(True)
        f.addRow("", self.show_img)
        left.addLayout(f)
        self.info = QLabel("")
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        left.addWidget(self.info)
        left.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Crea i tracciati"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        left.addWidget(bb)
        self.view = _View()
        self.view.w, self.view.h = shape.w, shape.h
        g = np.clip((1.0 - self.dark) * 255, 0, 255).astype(np.uint8)
        self._g = np.ascontiguousarray(g)
        self.view.qimg = QImage(self._g.data, g.shape[1], g.shape[0], g.shape[1], QImage.Format_Grayscale8)
        h.addWidget(self.view, 1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(220)
        self.timer.timeout.connect(self._run)
        for w in (self.thr, self.detail, self.smooth, self.corner, self.speck):
            w.valueChanged.connect(self._later)
        self.thr.sliderPressed.connect(lambda: self.auto.setChecked(False))
        for w in (self.auto, self.invert):
            w.toggled.connect(self._later)
        self.mode.currentIndexChanged.connect(self._mode)
        self.layer.currentIndexChanged.connect(self._color)
        self.show_img.toggled.connect(lambda on: (setattr(self.view, "show_img", on), self.view.update()))
        self.resize(1080, 620)
        self._color()
        self._run()

    @staticmethod
    def _slider(lo, hi, val):
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def _mode(self):
        if self.mode.currentData() == "centerline":
            self.corner.setValue(70)
        self._later()

    def _color(self):
        self.view.color = QColor(LAYER_COLORS[self.layer.currentData()])
        self.view.update()

    def _later(self, *_):
        self.timer.start()

    def params(self):
        t = None if self.auto.isChecked() else self.thr.value() / 100.0
        return dict(mode=self.mode.currentData(), threshold=t, invert=self.invert.isChecked(),
                    detail=self.detail.value() / 100.0, smooth=self.smooth.value() / 100.0,
                    min_size_mm=self.speck.value() / 100.0, corner_deg=float(self.corner.value()))

    def _run(self):
        p = self.params()
        self.speck_lab.setText(tr("{0:.2f} mm", p['min_size_mm']))
        try:
            path, info = trace.trace(self.dark, self.shape.w, self.shape.h, **p)
        except Exception as ex:  # noqa: BLE001
            self.info.setText(tr("Errore: {0}", ex))
            return
        if self.auto.isChecked():
            self.thr.blockSignals(True)
            self.thr.setValue(int(round(info["threshold"] * 100)))
            self.thr.blockSignals(False)
        self.thr_lab.setText(f"{info['threshold'] * 100:.0f}%")
        self.result = path
        self.view.path = path
        self.view.update()
        self.info.setText(tr("{0} tracciati · {1} nodi", info['curves'], info['nodes']))

    def values(self):
        if self.timer.isActive():
            self.timer.stop()
            self._run()
        return self.result, self.layer.currentData(), self.keep.isChecked()
