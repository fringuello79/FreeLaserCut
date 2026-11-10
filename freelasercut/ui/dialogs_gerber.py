# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Importa → file Gerber di un circuito stampato (0.18.3): le scelte prima di mettere la basetta sul piano.

I file sono già stati letti (core/gerber.py): qui si decide solo come usarli. A ogni scelta la basetta viene
ricalcolata e l'anteprima mostra **in scuro quello che il laser incide**, così negativo e specchio si vedono
prima di importare. Nessuna modifica al progetto finché non si preme «Importa».
"""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import gerber
from freelasercut.i18n import tr  # noqa: E402


def role_labels():
    return (("copper", tr("Rame (piste e piazzole)")), ("profile", tr("Contorno della basetta")),
            ("other", tr("Serigrafia, maschera o altro")))


def side_label(side):
    return {"top": tr("lato sopra"), "bottom": tr("lato sotto"), "inner": tr("strato interno")}.get(side, "")


def two_sided_text(top_name, bottom_name):
    """Cosa fare dopo aver importato una basetta a due facce, e di chi è il compito di rimetterla a posto."""
    return tr("Le due facce sono pronte su due piani di lavoro, nella stessa posizione.\n\n"
              "1. Incidi il piano «{0}».\n"
              "2. Gira la basetta da sinistra a destra, come la pagina di un libro, e rimettila nello stesso ingombro.\n"
              "3. Passa al piano «{1}» e incidi.\n\n"
              "Rimettere la basetta esattamente al suo posto dopo averla girata, con una dima o con riferimenti tuoi, "
              "è compito tuo: FreeLaserCut tiene le due facce allineate fra loro sul piano, ma non può sapere dove "
              "appoggi la basetta. La precisione del risultato dipende da questo passaggio.", top_name, bottom_name)


def board_paths(board, side=None):
    """(aree, linee) come QPainterPath in mm, Y verso l'alto: quello che l'anteprima disegna.
    Con due facce, side = "top" (predefinito) o "bottom"."""
    areas, lines = QPainterPath(), QPainterPath()
    areas.setFillRule(Qt.OddEvenFill)
    for ly in board.side_layers(side or "top"):
        if ly.kind == "area":
            for isl in ly.data:
                for c in isl:
                    areas.moveTo(c[0][0], c[0][1])
                    for x, y in c[1:]:
                        areas.lineTo(x, y)
                    areas.closeSubpath()
        else:
            for pts, closed in ly.data:
                lines.moveTo(pts[0][0], pts[0][1])
                for x, y in pts[1:]:
                    lines.lineTo(x, y)
                if closed:
                    lines.closeSubpath()
    return areas, lines


class BoardPreview(QWidget):
    """In scuro quello che il laser incide, su fondo chiaro; il contorno (solo linea) in rosso."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(380, 300)
        self.board = None
        self.areas, self.lines = QPainterPath(), QPainterPath()

    def set_board(self, board, side=None):
        self.board = board
        self.areas, self.lines = board_paths(board, side) if board is not None else (QPainterPath(), QPainterPath())
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1B2130"))
        if self.board is None:
            return
        b = self.board.bounds
        w, h = max(b[2] - b[0], 1e-6), max(b[3] - b[1], 1e-6)
        k = min((self.width() - 24) / w, (self.height() - 24) / h)
        ox, oy = (self.width() - w * k) / 2, (self.height() - h * k) / 2
        p.setRenderHint(QPainter.Antialiasing, True)
        p.translate(ox, oy + h * k)
        p.scale(k, -k)
        p.translate(-b[0], -b[1])
        p.fillRect(QRectF(b[0], b[1], w, h), QColor("#D9B382"))  # la basetta ancora coperta
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#20242B"))
        p.drawPath(self.areas)
        pen = QPen(QColor("#E5484D"), 0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.lines)


class GerberDialog(QDialog):
    def __init__(self, parent, files, errors=()):
        super().__init__(parent)
        self.files = list(files)
        self.board = None
        self.setWindowTitle(tr("Importa un circuito stampato (Gerber)"))
        self.setMinimumWidth(860)
        base = gerber.defaults(self.files)
        h = QHBoxLayout(self)
        left = QVBoxLayout()
        h.addLayout(left, 1)

        self.table = QTableWidget(len(self.files), 2)
        self.table.setHorizontalHeaderLabels([tr("File"), tr("Cosa contiene")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.role_boxes = {}
        for row, f in enumerate(self.files):
            it = QTableWidgetItem(f.name)
            it.setFlags(Qt.ItemIsEnabled)
            it.setToolTip(f.path)
            self.table.setItem(row, 0, it)
            if f.kind == "excellon":
                n = len(f.drill.holes) + len(f.drill.slots)
                lab = QTableWidgetItem(tr("Fori ({0})", n))
                lab.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(row, 1, lab)
            else:
                cb = QComboBox()
                for key, text in role_labels():
                    extra = side_label(f.side) if key == f.role else ""
                    cb.addItem(text + (f" · {extra}" if extra else ""), key)
                cb.setCurrentIndex(max(0, cb.findData(f.role)))
                cb.currentIndexChanged.connect(self._changed)
                self.table.setCellWidget(row, 1, cb)
                self.role_boxes[f.path] = cb
        self.table.setMaximumHeight(min(260, 34 + 30 * len(self.files)))
        left.addWidget(self.table)

        form = QFormLayout()
        self.what = QComboBox()
        self.what.addItem(tr("Lo spazio fra le piste (vernice o toner da togliere)"), True)
        self.what.addItem(tr("Le piste (il rame che resta)"), False)
        self.what.setCurrentIndex(0 if base.negative else 1)
        self.what.setToolTip(tr("Metodo della vernice: il laser scopre il rame da togliere, poi l'acido lo corrode e la "
                                "vernice protegge le piste. Per il fotoresist negativo si incidono invece le piste."))
        form.addRow(tr("Il laser incide"), self.what)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0.0, 50.0)
        self.margin.setDecimals(1)
        self.margin.setSingleStep(0.5)
        self.margin.setSuffix(" mm")
        self.margin.setValue(base.margin)
        self.margin.setToolTip(tr("Quanto spazio incidere oltre il disegno, quando fra i file non c'è il contorno della basetta"))
        self.lbl_margin = QLabel(tr("Bordo oltre il disegno"))
        form.addRow(self.lbl_margin, self.margin)
        self.mirror = QCheckBox(tr("Specchia (lato sotto, quello delle saldature)"))
        self.mirror.setChecked(bool(base.mirror))
        self.mirror.setToolTip(tr("Il lato sotto si incide specchiato: i file lo descrivono visto da sopra, attraverso la basetta"))
        form.addRow("", self.mirror)
        self.holes = QComboBox()
        self.holes.addItem(tr("Con il loro diametro vero"), "true")
        self.holes.addItem(tr("Solo un punto al centro, per la punta"), "dot")
        self.holes.addItem(tr("Non segnarli"), "none")
        self.dot = QDoubleSpinBox()
        self.dot.setRange(0.05, 5.0)
        self.dot.setDecimals(2)
        self.dot.setSingleStep(0.1)
        self.dot.setSuffix(" mm")
        self.dot.setValue(base.dot)
        hb = QHBoxLayout()
        hb.addWidget(self.holes, 1)
        hb.addWidget(self.dot)
        self.lbl_holes = QLabel(tr("Fori"))
        form.addRow(self.lbl_holes, hb)
        left.addLayout(form)

        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        left.addWidget(self.lbl_info)
        self.lbl_two = QLabel(tr("Due facce: il lato sopra va sul piano di lavoro attuale, il lato sotto, specchiato, su un "
                                 "piano di lavoro nuovo nella stessa posizione. Rimettere la basetta al suo posto quando "
                                 "la giri, con o senza dima, è compito tuo."))
        self.lbl_two.setWordWrap(True)
        left.addWidget(self.lbl_two)
        self.lbl_warn = QLabel("")
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet("color:#d9822b;")
        self.lbl_warn.setTextFormat(Qt.PlainText)
        left.addWidget(self.lbl_warn)
        self.errors = [tr("{0}: non importato ({1})", n, e) for n, e in errors]
        left.addStretch(1)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText(tr("Importa"))
        self.bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        left.addWidget(self.bb)

        right = QVBoxLayout()
        h.addLayout(right, 1)
        cap = QLabel(tr("Anteprima: in scuro quello che il laser incide"))
        cap.setObjectName("muted")
        top_row = QHBoxLayout()
        top_row.addWidget(cap, 1)
        self.side_view = QComboBox()  # solo con due facce: quale faccia mostra l'anteprima
        self.side_view.addItem(tr("Lato sopra"), "top")
        self.side_view.addItem(tr("Lato sotto (specchiato)"), "bottom")
        top_row.addWidget(self.side_view)
        right.addLayout(top_row)
        self.preview = BoardPreview()
        right.addWidget(self.preview, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self.rebuild)
        self.side_view.currentIndexChanged.connect(self._show_side)
        for w in (self.what, self.holes):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.margin, self.dot):
            w.valueChanged.connect(self._changed)
        self.mirror.toggled.connect(self._changed)
        self.rebuild()

    # ------------------------------------------------------------------ modello
    def options(self):
        roles = {p: cb.currentData() for p, cb in self.role_boxes.items()}
        return gerber.Options(mirror=self.mirror.isChecked(), negative=bool(self.what.currentData()),
                              margin=self.margin.value(), holes=self.holes.currentData(), dot=self.dot.value(), roles=roles)

    def _changed(self, *_):
        self._timer.start()

    def _show_side(self, *_):
        self.preview.set_board(self.board, self.side_view.currentData())

    def rebuild(self):
        """Ricalcola la basetta con le scelte attuali; quello che non ha effetto si spegne e si vede."""
        self._timer.stop()
        o = self.options()
        has_copper = any(gerber.role_of(f, o) == "copper" for f in self.files)
        has_profile = any(gerber.role_of(f, o) == "profile" for f in self.files)
        has_drill = any(f.kind == "excellon" for f in self.files)
        self.what.setEnabled(has_copper)
        neg = has_copper and o.negative
        self.margin.setEnabled(neg and not has_profile)
        self.lbl_margin.setEnabled(neg and not has_profile)
        self.holes.setEnabled(has_drill)
        self.lbl_holes.setEnabled(has_drill)
        self.dot.setEnabled(has_drill and o.holes == "dot")
        two = gerber.is_two_sided(self.files, o)  # sopra dritto e sotto specchiato, sempre: la spunta non conta
        self.mirror.setEnabled(not two)
        self.lbl_two.setVisible(two)
        self.side_view.setVisible(two)
        o.negative = neg
        notes = list(self.errors)
        try:
            self.board = gerber.build(self.files, o)
        except gerber.GerberError as exc:
            self.board = None
            notes.append(str(exc))
        self.preview.set_board(self.board, self.side_view.currentData())
        self.bb.button(QDialogButtonBox.Ok).setEnabled(self.board is not None)
        if self.board is not None:
            w, h = self.board.size
            text = tr("Misure: {0:.2f} × {1:.2f} mm", w, h)
            if self.board.negative:
                text += " · " + (tr("bordo: il contorno della basetta") if self.board.frame == "profile"
                                 else tr("bordo: un rettangolo attorno al disegno"))
            if self.board.mirrored:
                text += " · " + tr("specchiato")
            if self.board.two_sided:
                text += " · " + tr("due facce")
            self.lbl_info.setText(text)
            notes += self.board.warnings
        else:
            self.lbl_info.setText("")
        self.lbl_warn.setText("\n".join(notes[:8]) + ("\n…" if len(notes) > 8 else ""))
        self.lbl_warn.setVisible(bool(notes))


def ask(parent, files, errors=()):
    """Apre la finestra. Ritorna le scelte (gerber.Options) oppure None se si annulla."""
    dlg = GerberDialog(parent, files, errors)
    if dlg.exec() != QDialog.Accepted:
        return None
    o = dlg.options()
    o.negative = bool(o.negative and any(gerber.role_of(f, o) == "copper" for f in files))
    return o
