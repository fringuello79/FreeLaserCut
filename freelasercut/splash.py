# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Schermata d'avvio: compare subito, mentre si caricano le librerie pesanti (numpy, OpenCV, numba)."""
import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QSplashScreen

from . import __author__, __version__
from freelasercut.i18n import tr  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
W, H = 560, 300


class Splash(QSplashScreen):
    def __init__(self, pixmap):
        # niente WindowStaysOnTopHint: coprirebbe la scelta dell'interfaccia e i messaggi d'errore
        super().__init__(pixmap)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._msg = tr("Avvio in corso…")

    def say(self, text):
        self._msg = text
        self.repaint()
        QGuiApplication.processEvents()

    def drawContents(self, p):
        p.setRenderHint(QPainter.TextAntialiasing)
        f = QFont("Segoe UI", 11)
        f.setPixelSize(15)
        p.setFont(f)
        p.setPen(QColor("#C9D5F5"))
        p.drawText(QRectF(0, 212, W, 26), Qt.AlignCenter, self._msg)


def _pixmap():
    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0
    pm = QPixmap(int(W * dpr), int(H * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    card = QPainterPath()
    card.addRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 18, 18)
    bg = QLinearGradient(0, 0, W, H)
    bg.setColorAt(0.0, QColor("#18285A"))
    bg.setColorAt(0.55, QColor("#0D1532"))
    bg.setColorAt(1.0, QColor("#22104A"))
    p.fillPath(card, bg)
    p.setPen(QPen(QColor(110, 155, 255, 110), 1.2))
    p.drawPath(card)
    logo = os.path.join(ASSETS, "logo_scritta.svg")
    r = QSvgRenderer(logo)
    if r.isValid():
        vb = r.viewBoxF()
        w = 470.0
        h = w * vb.height() / max(vb.width(), 1)
        r.render(p, QRectF((W - w) / 2, 52, w, h))
    # "raggio" in basso: una linea che sfuma dal blu all'arancio
    beam = QLinearGradient(60, 0, W - 60, 0)
    beam.setColorAt(0.0, QColor(79, 180, 255, 0))
    beam.setColorAt(0.35, QColor("#4FB4FF"))
    beam.setColorAt(0.7, QColor("#8A6BFF"))
    beam.setColorAt(1.0, QColor(255, 122, 46, 0))
    p.fillRect(QRectF(60, 250, W - 120, 2), beam)
    f = QFont("Segoe UI")
    f.setPixelSize(12)
    p.setFont(f)
    p.setPen(QColor("#8C9CC4"))
    p.drawText(QRectF(0, 262, W - 24, 22), Qt.AlignRight | Qt.AlignVCenter, tr("versione {0} · {1}", __version__, __author__))
    p.end()
    return pm


def show_splash():
    s = Splash(_pixmap())
    s.show()
    s.raise_()
    QGuiApplication.processEvents()
    return s
