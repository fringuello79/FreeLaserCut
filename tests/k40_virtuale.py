# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""K40 virtuale (strumento per Ale, rudimentale): apre FreeLaserCut con una K40 finta collegabile, e accanto una
finestrina che mostra il piano 300 × 200 mm, la testa e i tratti «bruciati».

Avvio (con FreeLaserCut chiuso):  python tests\\k40_virtuale.py        (tempo vero)
                                   python tests\\k40_virtuale.py 5      (5 volte più veloce)
Nella tendina delle porte: «K40 VIRTUALE (scheda finta)» → Connetti. Il profilo diventa quello della K40: per tornare
al proprio laser, «Laser in uso». La scheda finta è quella delle prove (tests/k40_scheda_finta.py): riceve i pacchetti
come la vera e segna i «pericoli» (laser acceso senza dati, D fuori dal lavoro, testa fuori dal piano).
Non tocca USB e non serve la macchina.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

VEL = 1.0
if len(sys.argv) > 1:
    try:
        VEL = max(0.1, float(sys.argv[1].replace(",", ".")))
    except ValueError:
        pass
    del sys.argv[1]

from k40_scheda_finta import MIL, SchedaFinta  # noqa: E402
from freelasercut import grbl  # noqa: E402
from freelasercut.ui import main_window as mw  # noqa: E402

STATO = {"scheda": None}


def _collegamenti():
    s = SchedaFinta(scala=1.0 / VEL)
    STATO["scheda"] = s
    return [s]


grbl.GrblController.k40_links = staticmethod(_collegamenti)
grbl.GrblController.k40_time_scale = 1.0 / VEL
mw.MainWindow._k40_ports = lambda self: [(grbl.K40_PORT, "K40 VIRTUALE (scheda finta)", True)]


def _vista():
    from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QPainter, QPen
    from PySide6.QtWidgets import QWidget

    class Vista(QWidget):
        W, H = 300.0, 200.0

        def __init__(self):
            super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint)
            self.setWindowTitle("K40 virtuale")
            self.resize(720, 560)
            self.scia = []
            self._s = None
            t = QTimer(self)
            t.timeout.connect(self._tick)
            t.start(40)

        def _tick(self):
            s = STATO["scheda"]
            if s is not self._s:
                self._s, self.scia = s, []
            if s is not None:
                with s.lock:
                    p = (s.x / MIL, s.y / MIL)
                if not self.scia or self.scia[-1] != p:
                    self.scia.append(p)
                    del self.scia[:-4000]
            self.update()

        def paintEvent(self, _ev):
            g = QPainter(self)
            g.setRenderHint(QPainter.Antialiasing)
            g.fillRect(self.rect(), QColor("#11151d"))
            m, top = 16, 110
            k = min((self.width() - 2 * m) / self.W, (self.height() - top - m) / self.H)
            ox, oy = m, top

            def P(x, y):
                return QPointF(ox + x * k, oy + y * k)
            g.fillRect(QRectF(ox, oy, self.W * k, self.H * k), QColor("#c9a46a"))  # «compensato»
            g.setPen(QPen(QColor(0, 0, 0, 40), 1))
            for x in range(0, 301, 10):
                g.drawLine(P(x, 0), P(x, self.H))
            for y in range(0, 201, 10):
                g.drawLine(P(0, y), P(self.W, y))
            s = self._s
            g.setPen(QColor("#e6e9ef"))
            g.setFont(QFont("Consolas", 10))
            if s is None:
                g.drawText(m, 24, "Nessuna K40 collegata: in FreeLaserCut scegli «K40 VIRTUALE» e Connetti")
                return
            with s.lock:
                accesi = list(s.accesi)
                x, y = s.x / MIL, s.y / MIL
                info = (s.lavoro, s.laser, s.pausa, s.pacchetti, s.persi, list(s.pericoli))
            lavoro, laser, pausa, pk, persi, pericoli = info
            g.setPen(QPen(QColor(120, 160, 255, 110), 1, Qt.DashLine))  # spostamenti (scia della testa)
            for a, b in zip(self.scia, self.scia[1:]):
                g.drawLine(P(*a), P(*b))
            g.setPen(QPen(QColor("#2a1608"), max(1.5, 0.25 * k)))  # tratti bruciati
            for x0, y0, x1, y1 in accesi:
                g.drawLine(P(x0 / MIL, y0 / MIL), P(x1 / MIL, y1 / MIL))
            c = QColor("#ff3b30") if laser and lavoro and not pausa else QColor("#3dd68c")
            g.setPen(QPen(c, 2))
            hp = P(x, y)
            g.drawEllipse(hp, 6, 6)
            g.drawLine(hp + QPointF(-10, 0), hp + QPointF(10, 0))
            g.drawLine(hp + QPointF(0, -10), hp + QPointF(0, 10))
            g.setPen(QColor("#e6e9ef"))
            g.drawText(m, 22, f"testa X {x:6.1f}  Y {y:6.1f} mm    velocità simulata ×{VEL:g}")
            g.drawText(m, 42, f"lavoro {'aperto' if lavoro else 'chiuso'} · laser {'ACCESO' if laser else 'spento'}"
                              f"{' · PAUSA' if pausa else ''} · pacchetti {pk} (persi {persi}) · tratti {len(accesi)}")
            g.setPen(QColor("#ff6b5e") if pericoli else QColor("#3dd68c"))
            g.drawText(m, 62, f"pericoli: {len(pericoli)}" + (f" — ultimo: {pericoli[-1][:80]}" if pericoli else " (nessuno)"))
            g.setPen(QColor("#8a93a6"))
            g.drawText(m, 82, "casa = angolo in alto a sinistra · tratteggio blu = spostamenti · scuro = bruciato")

        def mouseDoubleClickEvent(self, _ev):
            s = self._s
            if s is not None:
                with s.lock:
                    s.accesi.clear()
            self.scia = []

    return Vista()


_main = mw.main


def _main_con_vista(app=None, splash=None):
    from PySide6.QtWidgets import QApplication

    a = app or QApplication.instance() or QApplication(sys.argv)
    a._k40_vista = _vista()
    a._k40_vista.show()
    return _main(a, splash)


mw.main = _main_con_vista

if __name__ == "__main__":
    from freelasercut.__main__ import boot

    boot()
