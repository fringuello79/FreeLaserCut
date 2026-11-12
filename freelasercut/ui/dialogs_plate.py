# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Foto del piano dal telefono: si indicano i 4 angoli dell'area di lavoro e la foto si raddrizza (0.19.0)."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QDialog, QGraphicsEllipseItem, QGraphicsItem, QGraphicsPolygonItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from .. import plate_photo
from ..theme import C
from .dialogs_campoints import _PhotoView, _qimage
from freelasercut.i18n import tr  # noqa: E402

REASONS = {
    "few": lambda: tr("Servono 4 punti: uno per ogni angolo dell'area di lavoro."),
    "close": lambda: tr("Due punti sono quasi nello stesso posto: togline uno e rimettilo sull'angolo giusto."),
    "flat": lambda: tr("I punti sono quasi in fila: devono essere i 4 angoli dell'area di lavoro."),
    "crossed": lambda: tr("Così i 4 punti non fanno un quadrilatero: togli l'ultimo e rimettilo sull'angolo che manca."),
}


class PlateCornersDialog(QDialog):
    """photo: la foto (BGR); bed: (larghezza, altezza) dell'area di lavoro in mm.
    Dopo exec() accettato: corners() = i 4 angoli nella foto, nell'ordine (0, Ymax), (Xmax, Ymax), (Xmax, 0), (0, 0)."""

    def __init__(self, photo, bed, parent=None):
        super().__init__(parent)
        self.photo, self.bed = photo, bed
        self.pts = []  # i clic, nell'ordine in cui sono stati fatti
        self.turns = 0  # quarti di giro: da che lato della macchina è stata fatta la foto
        self.setWindowTitle(tr("Foto dal telefono: i 4 angoli dell'area di lavoro"))
        self.resize(980, 720)
        v = QVBoxLayout(self)
        how = QLabel(tr("<b>Clicca sui 4 angoli dell'area di lavoro</b>, in qualsiasi ordine. La foto verrà "
                        "raddrizzata e messa sotto il piano. Rotellina: ingrandisci; tasto destro trascinando: sposta."))
        how.setWordWrap(True)
        how.setTextFormat(Qt.RichText)
        v.addWidget(how)
        self.scene = QGraphicsScene(self)
        self.pix = self.scene.addPixmap(QPixmap.fromImage(_qimage(photo)))
        self.view = _PhotoView(self.scene)
        self.view.clicked.connect(self.add)
        v.addWidget(self.view, 1)
        self.poly = QGraphicsPolygonItem()
        self.poly.setPen(QPen(QColor(C["accent_hi"]), 0))
        self.poly.setBrush(QBrush(QColor(74, 146, 255, 40)))
        self.scene.addItem(self.poly)
        self.marks = []
        self.info = QLabel()
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        row = QHBoxLayout()
        self.b_undo = QPushButton(tr("Togli l'ultimo punto"))
        self.b_undo.clicked.connect(lambda: self.undo())
        self.b_turn = QPushButton(tr("Gira l'origine di un quarto di giro"))
        self.b_turn.setToolTip(tr("Se la foto è fatta da un lato della macchina, l'angolo X0 Y0 non è quello in basso a "
                                  "sinistra nella foto: premi finché la scritta «X0 Y0» è sull'angolo giusto."))
        self.b_turn.clicked.connect(lambda: self.rotate())
        self.b_cancel = QPushButton(tr("Annulla"))
        self.b_cancel.clicked.connect(self.reject)
        self.b_ok = QPushButton(tr("Usa questa foto"))
        self.b_ok.setObjectName("primary")
        self.b_ok.clicked.connect(self.accept)
        row.addWidget(self.b_undo)
        row.addWidget(self.b_turn)
        row.addStretch(1)
        row.addWidget(self.b_cancel)
        row.addWidget(self.b_ok)
        v.addLayout(row)
        self.refresh()

    # ------------------------------------------------------------------ punti
    def add(self, u, v):
        h, w = self.photo.shape[:2]
        if len(self.pts) >= 4 or not (0 <= u <= w and 0 <= v <= h):
            return False
        self.pts.append((float(u), float(v)))
        self.refresh()
        return True

    def undo(self):
        if self.pts:
            self.pts.pop()
            self.refresh()

    def rotate(self):
        self.turns = (self.turns + 1) % 4
        self.refresh()

    def problem(self):
        h, w = self.photo.shape[:2]
        return plate_photo.check_corners(self.pts, (w, h))

    def corners(self):
        """I 4 angoli nell'ordine che serve per raddrizzare; None se i punti non vanno bene."""
        if self.problem() is not None:
            return None
        return plate_photo.rotate(plate_photo.order_corners(self.pts), self.turns)

    def refresh(self):
        for m in self.marks:
            self.scene.removeItem(m)
        self.marks = []
        h, w = self.photo.shape[:2]
        r = max(6.0, max(w, h) / 160.0)
        c = self.corners()
        names = ("X0 Ymax", "Xmax Ymax", "Xmax Y0", "X0 Y0")
        for i, (x, y) in enumerate(c if c is not None else self.pts):
            dot = QGraphicsEllipseItem(x - r, y - r, 2 * r, 2 * r)
            dot.setPen(QPen(QColor("#FFFFFF"), 0))
            dot.setBrush(QBrush(QColor(C["success"] if c is not None and i == 3 else C["accent_hi"])))
            self.scene.addItem(dot)
            self.marks.append(dot)
            if c is not None:
                lab = QGraphicsSimpleTextItem(names[i])
                lab.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
                f = QFont()
                f.setBold(True)
                lab.setFont(f)
                lab.setBrush(QBrush(QColor("#FFFFFF")))
                lab.setPos(x + r, y + r)
                self.scene.addItem(lab)
                self.marks.append(lab)
        self.poly.setPolygon(QPolygonF([QPointF(x, y) for x, y in c]) if c is not None else QPolygonF())
        why = self.problem()
        n = len(self.pts)
        if n < 4:
            self.info.setText(tr("Punti messi: {0} su 4.", n))
        elif why is not None:
            self.info.setText("⚠ " + REASONS[why]())
        else:
            self.info.setText(tr("Controlla che «X0 Y0» (il punto verde) sia sull'angolo dell'origine della macchina: "
                                 "se non lo è, premi «Gira l'origine». Poi «Usa questa foto»."))
        self.b_undo.setEnabled(n > 0)
        self.b_turn.setEnabled(c is not None)
        self.b_ok.setEnabled(c is not None)

    def showEvent(self, e):
        super().showEvent(e)
        self.view.fitInView(self.pix, Qt.KeepAspectRatio)
