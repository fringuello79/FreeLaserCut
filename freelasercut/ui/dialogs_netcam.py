# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.18.1: telecamera di rete. I Creality Falcon A1 Pro, A1C e T1 mandano la foto del piano dalla rete (porta 8080,
/media/getCapturePhoto), sia con il cavo USB (il laser è 192.168.10.1) sia in Wi-Fi. Va bene anche l'indirizzo di
qualsiasi foto (http) o flusso video (rtsp)."""
import threading

import cv2
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton,
                               QVBoxLayout)

from .. import camera as cam
from freelasercut.i18n import tr  # noqa: E402


def guide_html():
    return tr(
        "<b>Telecamera di rete.</b> Alcuni laser mandano la foto del piano dalla rete invece che come webcam USB: "
        "per esempio i <b>Creality Falcon A1 Pro, A1C e T1</b>. Con il cavo USB il laser ha l'indirizzo "
        "<i>192.168.10.1</i>; in Wi-Fi l'indirizzo si legge sul display del laser (impostazioni → WLAN).<br>"
        "Basta scrivere l'indirizzo: FreeLaserCut aggiunge da solo <i>:8080/media/getCapturePhoto</i>. Va bene anche "
        "l'indirizzo completo di una foto (http://…) o di un flusso video (rtsp://…).<br>"
        "Il <b>Falcon A1 10W</b> non serve qui: la sua telecamera è USB e si sceglie nell'elenco.")


def _qimg(bgr):
    h, w = bgr.shape[:2]
    return QImage(bgr.data, w, h, bgr.strides[0], QImage.Format_BGR888).copy()


class NetCameraDialog(QDialog):
    _done = Signal(str, object, str)
    _heard = Signal(object)

    def __init__(self, parent=None, laser_port=None, known=()):
        super().__init__(parent)
        self.url = ""
        self.image = None
        self._busy = False
        self.setWindowTitle(tr("Telecamera di rete"))
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        g = QLabel(guide_html())
        g.setWordWrap(True)
        g.setTextFormat(Qt.RichText)
        v.addWidget(g)
        h = QHBoxLayout()
        self.addr = QLineEdit()
        self.addr.setPlaceholderText("192.168.10.1")
        first = next(iter(known), None) or (cam.auto_net_candidates(laser_port)[-1] if laser_port else "")
        self.addr.setText(first or cam.USB_NET_HOST)
        h.addWidget(self.addr, 1)
        self.b_test = QPushButton(tr("Prova"))
        self.b_test.clicked.connect(self.test)
        h.addWidget(self.b_test)
        v.addLayout(h)
        h2 = QHBoxLayout()
        self.b_usb = QPushButton(tr("Cavo USB (192.168.10.1)"))
        self.b_usb.clicked.connect(lambda: (self.addr.setText(cam.USB_NET_HOST), self.test()))
        h2.addWidget(self.b_usb)
        self.b_find = QPushButton(tr("Cerca in Wi-Fi"))
        self.b_find.setToolTip(tr("Ascolta per 5 secondi gli annunci dei laser Creality sulla rete di casa. "
                                  "Windows può chiedere il permesso del firewall: rispondi «Consenti»."))
        self.b_find.clicked.connect(self.find)
        h2.addWidget(self.b_find)
        h2.addStretch(1)
        v.addLayout(h2)
        if known:
            v.addWidget(QLabel(tr("Indirizzi usati")))
            self.list = QListWidget()
            self.list.setMaximumHeight(90)
            for u in known:
                self.list.addItem(u)
            self.list.itemClicked.connect(lambda it: self.addr.setText(it.text()))
            v.addWidget(self.list)
        self.result = QLabel(tr("Scrivi l'indirizzo e premi «Prova»."))
        self.result.setWordWrap(True)
        v.addWidget(self.result)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(200)
        v.addWidget(self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.b_ok = bb.button(QDialogButtonBox.Ok)
        self.b_ok.setText(tr("Usa questa telecamera"))
        self.b_ok.setEnabled(False)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._done.connect(self._on_done)
        self._heard.connect(self._on_heard)

    # ---------------------------------------------------------------- prova
    def test(self):
        if self._busy:
            return  # una richiesta alla volta: il server della macchina si blocca con due richieste insieme
        text = self.addr.text().strip()
        if not text:
            return
        self._busy = True
        self.b_test.setEnabled(False)
        self.b_ok.setEnabled(False)
        self.result.setText(tr("Chiedo una foto a {0}… (può volerci qualche secondo)", cam.net_url(text)))

        def work():
            try:
                url, img, why = cam.probe_net(text)
            except Exception as exc:  # noqa: BLE001
                url, img, why = cam.net_url(text), None, str(exc)
            self._done.emit(url, img, why)

        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, url, img, why):
        self._busy = False
        self.b_test.setEnabled(True)
        if img is None:
            self.url, self.image = "", None
            self.preview.clear()
            self.result.setText(tr("✗ Nessuna foto da {0}. {1}", url, why))
            return
        self.url, self.image = url, img
        h, w = img.shape[:2]
        note = tr(" L'immagine è nera: chiudi bene il coperchio e accendi la luce.") if cam.is_black(img) else ""
        self.result.setText(tr("✓ Foto ricevuta: {0} × {1} pixel.", w, h) + note)
        pw = max(self.preview.width() - 8, 320)
        self.preview.setPixmap(QPixmap.fromImage(_qimg(cv2.resize(img, (pw, int(h * pw / w))))))
        self.b_ok.setEnabled(True)

    # ---------------------------------------------------------------- annunci in Wi-Fi
    def find(self):
        self.b_find.setEnabled(False)
        self.result.setText(tr("Ascolto gli annunci dei laser in Wi-Fi per 5 secondi…"))
        threading.Thread(target=lambda: self._heard.emit(cam.discover_udp(5.0)), daemon=True).start()

    def _on_heard(self, found):
        self.b_find.setEnabled(True)
        if not found:
            self.result.setText(tr("Nessun laser ha risposto. Leggi l'indirizzo sul display del laser "
                                   "(impostazioni → WLAN) e scrivilo qui."))
            return
        self.addr.setText(found[0])
        self.test()
