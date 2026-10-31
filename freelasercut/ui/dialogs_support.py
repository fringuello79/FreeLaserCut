# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Sostieni FreeLaserCut: contributo volontario allo sviluppo (GitHub Sponsors). Si apre solo su richiesta."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import DONATE_PAYPAL_URL, DONATE_URL, PROJECT_URL
from freelasercut.i18n import tr  # noqa: E402


class SupportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Sostieni FreeLaserCut"))
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        intro = QLabel(tr(
            "<b>FreeLaserCut è libero e completo, per tutti.</b><br>"
            "È un progetto in continua evoluzione, sviluppato nel tempo libero da fringuello79. "
            "Se ti è utile, puoi contribuire allo sviluppo con una donazione volontaria, di qualsiasi importo. "
            "Non sblocca niente e non è richiesta: è solo un grazie."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        how = QLabel(tr("Puoi donare con GitHub Sponsors (una volta sola o ogni mese) oppure con PayPal. "
                        "Si apre il sito ufficiale: il programma non vede né salva i tuoi dati di pagamento. "
                        "Anche una stella al progetto su GitHub aiuta a farlo conoscere."))
        how.setWordWrap(True)
        how.setObjectName("muted")
        lay.addWidget(how)
        btns = QHBoxLayout()
        b_star = QPushButton(tr("Pagina del progetto"))
        b_star.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL)))
        btns.addWidget(b_star)
        btns.addStretch(1)
        b_paypal = QPushButton("PayPal")
        b_paypal.setToolTip(tr("Dona con PayPal"))
        b_paypal.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATE_PAYPAL_URL)))
        btns.addWidget(b_paypal)
        b_open = QPushButton(tr("♥ Diventa sponsor"))
        b_open.setObjectName("primary")
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
        b_close = QPushButton(tr("Chiudi"))
        b_close.clicked.connect(self.accept)
        btns.addWidget(b_open)
        btns.addWidget(b_close)
        lay.addLayout(btns)
