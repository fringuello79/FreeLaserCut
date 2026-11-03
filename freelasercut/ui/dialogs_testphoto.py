# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Test materiale → Leggi la foto del test: risultato (foto raddrizzata con la griglia) e mini guida."""
import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..core import material_test as mtest
from ..theme import css
from freelasercut.i18n import tr  # noqa: E402


def guide_html():
    return tr(
        "<h3>Taratura da foto del test: come si fa</h3>"
        "<ol>"
        "<li><b>Prepara il test.</b> In Test materiale scegli <i>Riempimento</i> e spunta <i>Riferimenti per leggere "
        "la foto</i>: agli angoli del test verranno incisi quattro quadratini a scacchiera che servono a "
        "FreeLaserCut per ritrovare la griglia nella foto.</li>"
        "<li><b>Incidi il test</b> su un pezzo dello stesso materiale che userai (Avvia il test). Non cambiare "
        "i valori della finestra dopo averlo inciso: servono per leggere la foto.</li>"
        "<li><b>Pulisci</b> la superficie con un panno asciutto o un pennello: il fumo depositato tra i quadrati "
        "falsa la misura.</li>"
        "<li><b>Fai la foto dall'alto</b>, il più dritta possibile, con tutto il test e i quattro quadratini "
        "dentro l'inquadratura. Luce uniforme (vicino a una finestra o con la luce della stanza), niente ombre "
        "del telefono e niente riflessi. Non serve il flash.</li>"
        "<li><b>Passa la foto a FreeLaserCut</b>: <i>Da un file</i> (foto copiata sul PC), <i>Dalla camera</i> "
        "(la camera del laser, se inquadra il test) oppure <i>Dal telefono</i> (Laser → Controllo dal telefono, "
        "pulsante «Invia la foto del test»).</li>"
        "<li><b>Controlla il risultato</b>: ogni quadrato mostra quanto è scuro. Scegli uno dei valori proposti "
        "con «Usa questo» e salvalo nella libreria materiali.</li>"
        "</ol>"
        "<p>La misura confronta ogni quadrato con il legno nudo tra i quadrati: vale per quel materiale e quella "
        "luce. È un aiuto per scegliere, l'ultima parola resta al tuo occhio.</p>")


class GuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Taratura da foto: come si fa"))
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        lab = QLabel(guide_html())
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.RichText)
        v.addWidget(lab)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


def overlay(res, spec):
    """Foto raddrizzata con i quadrati contornati e la percentuale di scuro (QPixmap)."""
    rgb = cv2.cvtColor(res.rectified, cv2.COLOR_BGR2RGB)
    img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888).copy()
    L = mtest.layout(spec)
    k = res.px_mm
    xa, yb = res.origin
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    f = QFont()
    f.setPixelSize(max(9, int(spec.cell * k * 0.28)))
    f.setBold(True)
    p.setFont(f)
    picks = {s.cell: s.kind for s in res.suggestions}
    colors = {"scura": QColor("#2E7CF6"), "leggera": QColor("#1F9D63"), "foto": QColor("#E2700B")}
    for r in range(spec.rows):
        for c in range(spec.cols):
            x, y, s = mtest.cell_rect(spec, L, r, c)
            u, v = (x - xa) * k, (yb - (y + s)) * k
            kind = picks.get((r, c))
            p.setPen(QPen(colors.get(kind, QColor(255, 255, 255, 170)), 3 if kind else 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(int(u), int(v), int(s * k), int(s * k))
            txt = f"{res.dark[r, c] * 100:.0f}"
            p.setPen(QColor(0, 0, 0, 200))
            p.drawText(int(u) + 4, int(v) + 4, int(s * k), int(s * k), Qt.AlignLeft | Qt.AlignTop, txt)
            p.setPen(QColor(255, 255, 255))
            p.drawText(int(u) + 3, int(v) + 3, int(s * k), int(s * k), Qt.AlignLeft | Qt.AlignTop, txt)
    p.end()
    return QPixmap.fromImage(img)


class PhotoResultDialog(QDialog):
    use = Signal(int, int)  # riga (potenza), colonna (velocità)

    def __init__(self, res, spec, parent=None):
        super().__init__(parent)
        self.res = res
        self.setWindowTitle(tr("Foto del test: risultato"))
        self.setMinimumSize(640, 520)
        v = QVBoxLayout(self)
        head = QLabel(tr("Riferimenti trovati: {0} su 4{1}. I numeri sono quanto è scuro ogni quadrato rispetto al "
                         "materiale nudo (0 = come il materiale, 100 = nero).", len(res.found),
                         tr(" (foto specchiata, corretta)") if res.mirrored else ""))
        head.setWordWrap(True)
        v.addWidget(head)
        if res.uneven > 0.18:
            w = QLabel(tr("Attenzione: il materiale nudo nella foto non è uniforme (ombre, riflessi o venature "
                          "forti). Il risultato è meno affidabile: rifai la foto con una luce più uniforme."))
            w.setWordWrap(True)
            w.setStyleSheet(css("color:#FFB4A8;"))
            v.addWidget(w)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        self.pic = QLabel()
        self.pic.setAlignment(Qt.AlignCenter)
        pm = overlay(res, spec)
        if pm.width() > 900:
            pm = pm.scaledToWidth(900, Qt.SmoothTransformation)
        self.pic.setPixmap(pm)
        sc.setWidget(self.pic)
        v.addWidget(sc, 1)
        self.buttons = {}
        if not res.suggestions:
            none = QLabel(tr("I quadrati sono quasi tutti come il materiale nudo: il test è troppo leggero, oppure la "
                             "foto non è buona. Prova con più potenza o meno velocità."))
            none.setWordWrap(True)
            v.addWidget(none)
        dots = {"scura": "#2E7CF6", "leggera": "#1F9D63", "foto": "#E2700B"}
        for s in res.suggestions:
            row = QHBoxLayout()
            if s.kind == "foto":
                val = tr("{0:g}–{1:g} % a {2:g} mm/min", s.power_min, s.power, s.speed)
            else:
                val = tr("{0:g} % a {1:g} mm/min", s.power, s.speed)
            lab = QLabel(f"<span style='color:{dots[s.kind]}'>■</span> <b>{s.title}</b>: {val}<br>"
                         f"<small>{s.text}</small>")
            lab.setWordWrap(True)
            row.addWidget(lab, 1)
            b = QPushButton(tr("Usa questo"))
            b.clicked.connect(lambda _=False, s=s: self._use(s))
            row.addWidget(b)
            self.buttons[s.kind] = b
            wrap = QWidget()
            wrap.setLayout(row)
            v.addWidget(wrap)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _use(self, s):
        self.use.emit(int(s.cell[0]), int(s.cell[1]))
        self.accept()


def decode_image(data):
    """Bytes di un JPEG/PNG → immagine BGR (o None)."""
    arr = np.frombuffer(data, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR) if arr.size else None
