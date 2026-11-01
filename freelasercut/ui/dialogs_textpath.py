# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Strumenti → Testo su tracciato: il testo segue una linea o il contorno di una forma qualsiasi."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QMessageBox, QSlider,
    QVBoxLayout,
)

from ..core.document import GroupShape, ImageShape, PathShape, TextPathShape, TextShape
from freelasercut.i18n import tr  # noqa: E402


def _elements(path):
    return PathShape(path).params()["elements"]


def make_text_path(text, guide):
    """Nuova forma «testo su tracciato» dai parametri del testo e dalla geometria (sul piano) della guida."""
    d = text.params()
    for k in ("arc",):
        d.pop(k, None)
    t = d.pop("text")
    fam = d.pop("family")
    size = d.pop("size")
    d["align"] = "center"
    s = TextPathShape(t, fam, size, layer=text.layer, curve=_elements(guide.path()), start=0.5, offset=0.0, **d)
    return s


class TextPathDialog(QDialog):
    def __init__(self, main, shape):
        super().__init__(main)
        self.main, self.ed, self.s = main, main.editor, shape
        self.setWindowTitle(tr("Testo su tracciato"))
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.start = QSlider(Qt.Horizontal)
        self.start.setRange(0, 1000)
        self.start.setValue(int(round(shape.start * 1000)))
        f.addRow(tr("Posizione sulla curva"), self.start)
        self.align = QComboBox()
        for code, label in (("left", tr("Il testo parte da lì")), ("center", tr("Il testo è centrato lì")),
                            ("right", tr("Il testo finisce lì"))):
            self.align.addItem(label, code)
        self.align.setCurrentIndex(max(0, self.align.findData(shape.align)))
        f.addRow(tr("Allineamento"), self.align)
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-200, 200)
        self.offset.setDecimals(1)
        self.offset.setSuffix(" mm")
        self.offset.setValue(shape.offset)
        self.offset.setToolTip(tr("Distanza fra la curva e la linea di base del testo (negativa = dall'altra parte)"))
        f.addRow(tr("Distanza dalla curva"), self.offset)
        self.reverse = QCheckBox(tr("Percorri la curva al contrario (testo dall'altro lato)"))
        self.reverse.setChecked(shape.reverse)
        f.addRow("", self.reverse)
        v.addLayout(f)
        hint = QLabel(tr("Il testo resta modificabile (doppio clic o pannello Proprietà). La curva originale resta dov'è: "
                         "spostala sul livello T1 se non va incisa."))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        v.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.ed.begin(tr("Testo su tracciato"))
        self.start.valueChanged.connect(self._live)
        self.align.currentIndexChanged.connect(self._live)
        self.offset.valueChanged.connect(self._live)
        self.reverse.toggled.connect(self._live)

    def _live(self, *_):
        s = self.s
        s.start = self.start.value() / 1000.0
        s.align = self.align.currentData()
        s.offset = self.offset.value()
        s.reverse = self.reverse.isChecked()
        s.invalidate()
        self.ed.preview_changed()

    def accept(self):
        self._live()
        self.ed.commit()
        super().accept()

    def reject(self):
        self.ed.cancel()
        super().reject()


def run_text_path(main):
    ed = main.editor
    sel = ed.selection
    if len(sel) == 1 and isinstance(sel[0], TextPathShape):
        return TextPathDialog(main, sel[0]).exec()
    texts = [s for s in sel if isinstance(s, TextShape) and not isinstance(s, TextPathShape)]
    guides = [s for s in sel if not isinstance(s, (TextShape, ImageShape, GroupShape))]
    if len(texts) != 1 or len(guides) != 1:
        QMessageBox.information(main, tr("Testo su tracciato"),
                                tr("Seleziona un testo e una linea (o una forma): il testo ne seguirà la curva."))
        return None
    new = make_text_path(texts[0], guides[0])
    ed.replace([texts[0]], [new], tr("Testo su tracciato"))
    dlg = TextPathDialog(main, new)
    if dlg.exec() != QDialog.Accepted:
        ed.undo()  # annullata subito: torna il testo di prima
        return None
    return new
