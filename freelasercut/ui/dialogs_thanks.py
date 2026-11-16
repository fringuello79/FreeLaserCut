# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Aiuto → Ringraziamenti (0.20.5): la targa con i nomi di chi ha aiutato FreeLaserCut a migliorare.

Solo da leggere, e si apre solo da qui (deciso da Ale il 16/11/2026): niente progetto da incidere, e non compare da
sola dopo un aggiornamento. I nomi vengono da freelasercut/thanks.py, gli stessi della schermata di avvio; solo i
nomi, senza scrivere per che cosa. Aprendo la finestra i nomi compaiono uno dopo l'altro, come incisi.
"""
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QLinearGradient, QPainter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import thanks
from freelasercut.i18n import tr  # noqa: E402

TEXT = "#E8EEFF"
SOFT = "#C9D5F5"
MUTED = "#8C9CC4"
NAME_S = 1.1  # un nome si scopre in questo tempo
STEP_S = 0.14  # ogni nome parte dopo il precedente
FIRST_S = 0.25


def _font(px, weight=QFont.Normal):
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def flow(names, measure, width, gap=22.0):
    """I nomi a capo dentro `width`, mai spezzati. -> [(nome, riga, x)]"""
    out, row, x = [], 0, 0.0
    for n in names:
        w = measure(n)
        if x > 0 and x + w > width:
            row, x = row + 1, 0.0
        out.append((n, row, x))
        x += w + gap
    return out


class NamesView(QWidget):
    """I nomi, in righe, «incisi» uno dopo l'altro all'apertura (dopo restano fermi)."""

    PX = 17
    ROW_H = 30.0

    def __init__(self, names=None, animate=True, clock=time.monotonic):
        super().__init__()
        self.names = list(thanks.NAMES if names is None else names)
        self.animate = bool(animate)
        self._clock = clock
        self._t0 = clock()
        self._items = []
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self.setMinimumHeight(int(self.ROW_H))

    def font_(self):
        return _font(self.PX, QFont.DemiBold)

    def layout_items(self, width=None):
        fm = QFontMetricsF(self.font_())
        self._items = flow(self.names, fm.horizontalAdvance, max(60.0, float(self.width() if width is None else width)))
        return self._items

    def rows(self):
        return (max(r for _, r, _ in self._items) + 1) if self._items else 0

    def heightForWidth(self, w):
        fm = QFontMetricsF(self.font_())
        items = flow(self.names, fm.horizontalAdvance, max(60.0, float(w)))
        return int(((max(r for _, r, _ in items) + 1) if items else 1) * self.ROW_H)

    def hasHeightForWidth(self):
        return True

    def sizeHint(self):
        return QSize(520, self.heightForWidth(520))

    def duration(self):
        return FIRST_S + STEP_S * max(0, len(self.names) - 1) + NAME_S

    def restart(self):
        self._t0 = self._clock()
        if self.animate:
            self._timer.start()
        self.update()

    def progress(self, i, t=None):
        """Quanto è scoperto il nome numero i: 0 = non ancora, 1 = tutto."""
        if not self.animate:
            return 1.0
        t = self._clock() - self._t0 if t is None else t
        return min(1.0, max(0.0, (t - FIRST_S - i * STEP_S) / NAME_S))

    def _tick(self):
        if self._clock() - self._t0 > self.duration():
            self._timer.stop()
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self.restart()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.layout_items()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        f = self.font_()
        p.setFont(f)
        fm = QFontMetricsF(f)
        if not self._items:
            self.layout_items()
        cold, hot = QColor(TEXT), QColor("#FFB870")
        for i, (name, row, x) in enumerate(self._items):
            k = self.progress(i)
            if k <= 0:
                continue
            w = fm.horizontalAdvance(name)
            r = QRectF(x, row * self.ROW_H, w + 2, self.ROW_H)
            # scoperto da sinistra nel primo 60% del tempo, poi si raffredda dall'arancio al chiaro
            show = min(1.0, k / 0.6)
            cool = 0.0 if k < 0.6 else (k - 0.6) / 0.4
            col = QColor(int(hot.red() + (cold.red() - hot.red()) * cool),
                         int(hot.green() + (cold.green() - hot.green()) * cool),
                         int(hot.blue() + (cold.blue() - hot.blue()) * cool))
            p.save()
            p.setClipRect(QRectF(r.left() - 2, r.top(), (w + 4) * show, r.height()))
            p.setPen(col)
            p.drawText(r, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextDontClip, name)
            p.restore()
        p.end()


class ThanksDialog(QDialog):
    def __init__(self, parent=None, names=None, animate=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Ringraziamenti"))
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setObjectName("thanksDialog")
        if animate is None:
            animate = QGuiApplication.platformName() not in ("offscreen", "minimal")
        v = QVBoxLayout(self)
        v.setContentsMargins(40, 34, 40, 26)
        v.setSpacing(12)
        self.title = QLabel(tr("Grazie."))
        # la misura va scritta nel foglio di stile: quello del programma dà a tutte le scritte la sua
        self.title.setStyleSheet(f"color:{TEXT}; background:transparent; font-size:40px; font-weight:600;")
        v.addSpacing(10)
        v.addWidget(self.title)
        self.intro = QLabel(tr("FreeLaserCut migliora perché qualcuno lo prova, lo racconta e ci dice che cosa non va. "
                               "Questa versione è anche loro."))
        self.intro.setWordWrap(True)
        self.intro.setStyleSheet(f"color:{SOFT}; background:transparent; font-size:15px;")
        v.addWidget(self.intro)
        v.addSpacing(10)
        self.view = NamesView(names, animate)
        v.addWidget(self.view)
        v.addStretch(1)
        row = QHBoxLayout()
        self.note = QLabel(tr("Vuoi esserci anche tu? Scrivi il tuo nome quando mandi un rapporto all'assistenza."))
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{MUTED}; background:transparent; font-size:13px;")
        row.addWidget(self.note, 1)
        self.b_close = QPushButton(tr("Chiudi"))
        self.b_close.setObjectName("primary")
        self.b_close.setMinimumSize(110, 38)
        self.b_close.setDefault(True)
        self.b_close.clicked.connect(self.accept)
        row.addWidget(self.b_close, 0, Qt.AlignBottom)
        v.addLayout(row)
        self.resize(640, 460)
        self.setMinimumSize(460, 380)

    def names(self):
        return list(self.view.names)

    def paintEvent(self, _e):
        """Lo stesso fondo della schermata di avvio, con la riga d'accento sopra il titolo."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QLinearGradient(0, 0, self.width(), self.height())
        bg.setColorAt(0.0, QColor("#18285A"))
        bg.setColorAt(0.55, QColor("#0D1532"))
        bg.setColorAt(1.0, QColor("#22104A"))
        p.fillRect(self.rect(), bg)
        line = QLinearGradient(40, 0, 112, 0)
        line.setColorAt(0.0, QColor("#4FB4FF"))
        line.setColorAt(0.55, QColor("#8A6BFF"))
        line.setColorAt(1.0, QColor("#FF8A3D"))
        p.fillRect(QRectF(40, 30, 72, 2), line)
        p.end()
