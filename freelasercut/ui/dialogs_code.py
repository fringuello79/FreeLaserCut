# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Strumenti → Codice QR / a barre: crea o modifica un codice, con anteprima e dati variabili."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QVBoxLayout,
)

from ..core import codes, variables
from freelasercut.i18n import tr  # noqa: E402

EXAMPLES = {"qr": "https://", "code128": "FLC-{n:4}", "ean13": "800123456789", "ean8": "9638507",
            "upca": "03600029145", "code39": "FLC-{n:3}"}


class CodeDialog(QDialog):
    def __init__(self, parent=None, shape=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Modifica codice") if shape else tr("Codice QR o a barre"))
        self.setMinimumWidth(700)
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        f = QFormLayout()
        self.kind = QComboBox()
        for k, (name, _) in codes.KINDS.items():
            self.kind.addItem(name, k)
        f.addRow(tr("Tipo"), self.kind)
        self.data = QLineEdit()
        self.data.setToolTip(tr("Testo, indirizzo web o numero. Variabili: {n} numero progressivo ({n:4} = 0001), "
                                "{data}, {anno}, colonne del CSV (Strumenti → Testo variabile)."))
        f.addRow(tr("Contenuto"), self.data)
        self.w = QDoubleSpinBox()
        self.w.setRange(3, 1000)
        self.w.setSuffix(" mm")
        self.w.setDecimals(1)
        self.w.setToolTip(tr("Larghezza del simbolo, senza la zona di rispetto"))
        f.addRow(tr("Larghezza"), self.w)
        self.hgt = QDoubleSpinBox()
        self.hgt.setRange(0, 500)
        self.hgt.setSuffix(" mm")
        self.hgt.setDecimals(1)
        self.hgt.setSpecialValueText(tr("automatica"))
        f.addRow(tr("Altezza barre"), self.hgt)
        self.ecc = QComboBox()
        for code, label in (("L", tr("L · 7% (più compatto)")), ("M", tr("M · 15% (consigliata)")),
                            ("Q", tr("Q · 25%")), ("H", tr("H · 30% (resiste a graffi e logo)"))):
            self.ecc.addItem(label, code)
        f.addRow(tr("Correzione errori"), self.ecc)
        self.quiet = QSpinBox()
        self.quiet.setRange(0, 20)
        self.quiet.setSuffix(tr(" moduli"))
        self.quiet.setToolTip(tr("Margine vuoto attorno al codice: serve ai lettori. QR: almeno 2 (meglio 4); barre: 10"))
        f.addRow(tr("Zona di rispetto"), self.quiet)
        self.invert = QCheckBox(tr("In negativo (il laser schiarisce: anodizzato, ardesia, vernice scura)"))
        f.addRow("", self.invert)
        self.text = QCheckBox(tr("Mostra il numero sotto le barre"))
        f.addRow("", self.text)
        h.addLayout(f, 1)
        self.preview = QLabel()
        self.preview.setFixedSize(200, 200)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#FFFFFF; border-radius:8px;")
        h.addWidget(self.preview)
        v.addLayout(h)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("muted")
        v.addWidget(self.info)
        tip = QLabel(tr("Il codice va inciso in <b>riempimento</b>: FreeLaserCut lo mette da solo su un livello in "
                        "riempimento. Prova la lettura col telefono prima di incidere una serie."))
        tip.setWordWrap(True)
        tip.setObjectName("muted")
        v.addWidget(tip)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Applica") if shape else tr("Inserisci"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok_btn = bb.button(QDialogButtonBox.Ok)
        v.addWidget(bb)
        s = shape
        self.kind.setCurrentIndex(max(0, self.kind.findData(s.code if s else "qr")))
        self.data.setText(s.data if s else EXAMPLES["qr"])
        self.w.setValue(s.w if s else 25.0)
        self.hgt.setValue(s.h if s else 0.0)
        self.ecc.setCurrentIndex(max(0, self.ecc.findData(s.ecc if s else "M")))
        self.quiet.setValue(s.quiet if s else 2)
        self.invert.setChecked(bool(s.invert) if s else False)
        self.text.setChecked(bool(s.text) if s else True)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        for wdg in (self.data,):
            wdg.textChanged.connect(self.update_preview)
        for wdg in (self.w, self.hgt, self.quiet):
            wdg.valueChanged.connect(self.update_preview)
        for wdg in (self.ecc,):
            wdg.currentIndexChanged.connect(self.update_preview)
        for wdg in (self.invert, self.text):
            wdg.toggled.connect(self.update_preview)
        self._kind_changed(first=True)

    def _kind_changed(self, *_, first=False):
        k = self.kind.currentData()
        two_d = codes.KINDS[k][1]
        self.hgt.setEnabled(not two_d)
        self.text.setEnabled(not two_d)
        self.ecc.setEnabled(two_d)
        if not first:
            old = self.data.text()
            if not old or old in EXAMPLES.values():
                self.data.setText(EXAMPLES[k])
            self.quiet.setValue(2 if two_d else 10)
            self.w.setValue(25.0 if two_d else 45.0)
        self.update_preview()

    def values(self):
        return {"code": self.kind.currentData(), "data": self.data.text(), "w": self.w.value(), "h": self.hgt.value(),
                "ecc": self.ecc.currentData(), "quiet": self.quiet.value(), "invert": self.invert.isChecked(),
                "text": self.text.isChecked()}

    def update_preview(self, *_):
        v = self.values()
        shown = variables.expand(v["data"], 0)
        pm = QPixmap(200, 200)
        pm.fill(QColor("#FFFFFF"))
        try:
            path = codes.code_path(v["code"], shown, v["w"], v["h"] or None, v["ecc"], v["quiet"], v["invert"], v["text"])
            err = ""
        except codes.CodeError as exc:
            path, err = None, str(exc)
        if path is not None and not path.isEmpty():
            b = path.boundingRect()
            k = 184.0 / max(b.width(), b.height())
            tf = QTransform.fromTranslate(-b.center().x(), -b.center().y()) * QTransform.fromScale(k, -k) \
                * QTransform.fromTranslate(100, 100)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#5A3A1E"))  # colore del legno bruciato
            p.drawPath(tf.map(path))
            p.end()
        self.preview.setPixmap(pm)
        self.ok_btn.setEnabled(not err)
        if err:
            self.info.setText(f"<span style='color:#E5484D'>{err}</span>")
        else:
            b = path.boundingRect()
            extra = tr(" · prima copia: «{0}»", shown) if variables.has_vars(v["data"]) else ""
            self.info.setText(tr("Ingombro del disegno {0:.1f} × {1:.1f} mm{2}", b.width(), b.height(), extra))
