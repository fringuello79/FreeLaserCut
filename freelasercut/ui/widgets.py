# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Componenti riutilizzabili: campo numerico con calcoli e unità, ancoraggio a 9 punti, sezioni."""
import ast
import math
import operator
import re

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from ..theme import C
from . import style
from freelasercut.i18n import tr  # noqa: E402

_UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, '"': 25.4, "pt": 25.4 / 72.0}
_FUNCS = {"sqrt": math.sqrt, "sin": lambda d: math.sin(math.radians(d)), "cos": lambda d: math.cos(math.radians(d)),
          "tan": lambda d: math.tan(math.radians(d)), "abs": abs, "round": round, "min": min, "max": max}
_CONST = {"pi": math.pi, "e": math.e}
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Mod: operator.mod}


def _ev(node):
    if isinstance(node, ast.Expression):
        return _ev(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_ev(node.left), _ev(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_ev(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONST:
        return _CONST[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return float(_FUNCS[node.func.id](*[_ev(a) for a in node.args]))
    raise ValueError(tr("espressione non valida"))


def evaluate(text, current=None):
    """'120/3' -> 40 · '2in' -> 50.8 · '+5' / '*2' / '/4' agiscono sul valore attuale · '10cm + 5' -> 105."""
    t = text.strip().replace(",", ".")
    if not t:
        raise ValueError("vuoto")
    if current is not None and t[0] in "+*/" and len(t) > 1:
        t = f"({current}){t}"
    # unità in fondo a tutta l'espressione: "1/2in" = mezzo pollice
    m = re.match(r'^(.*?)\s*(mm|cm|m|in|"|pt)$', t)
    if m and not re.search(r'(mm|cm|in|pt|")', m.group(1)) and not re.search(r'\dm\b', m.group(1)):
        return _ev(ast.parse(f"({m.group(1)})*{_UNITS[m.group(2)]}", mode="eval"))
    # unità sui singoli numeri: 10cm + 5 -> (10*10) + 5
    t = re.sub(r"(\d+(?:\.\d*)?|\.\d+)\s*(mm|cm|m|in|\"|pt)\b|(\d+(?:\.\d*)?)\s*\"",
               lambda m: f"({m.group(1) or m.group(3)}*{_UNITS[m.group(2) or chr(34)]})", t)
    return _ev(ast.parse(t, mode="eval"))


class NumField(QLineEdit):
    """Campo numerico: accetta calcoli e unità, Invio applica, Esc ripristina, rotella/frecce cambiano il valore."""

    committed = Signal(float)

    def __init__(self, value=0.0, decimals=2, step=1.0, suffix="", width=78, minimum=None, maximum=None):
        super().__init__()
        self.setObjectName("num")
        self.decimals = decimals
        self.step = step
        self.suffix = suffix
        self.minimum, self.maximum = minimum, maximum
        self._value = float(value)
        self.setFixedWidth(width)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setToolTip(tr("Accetta calcoli e unità: 120/3 · 2in · 5cm · +10 · *2 · /3"))
        self.editingFinished.connect(self._commit)
        self._show()

    def value(self):
        return self._value

    def setValue(self, v, emit=False):
        self._value = float(v)
        if not self.hasFocus():
            self._show()
        if emit:
            self.committed.emit(self._value)

    def _show(self):
        self.setText(f"{self._value:.{self.decimals}f}" + self.suffix)

    def _clamp(self, v):
        if self.minimum is not None:
            v = max(self.minimum, v)
        if self.maximum is not None:
            v = min(self.maximum, v)
        return v

    def _commit(self):
        txt = self.text().replace(self.suffix, "") if self.suffix else self.text()
        try:
            v = self._clamp(evaluate(txt, self._value))
        except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
            self._show()
            return
        changed = abs(v - self._value) > 1e-12
        self._value = v
        self._show()
        if changed:
            self.committed.emit(v)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._show()
            self.clearFocus()
            return
        if e.key() in (Qt.Key_Up, Qt.Key_Down):
            k = self.step * (10 if e.modifiers() & Qt.ShiftModifier else 0.1 if e.modifiers() & Qt.ControlModifier else 1)
            self._value = self._clamp(self._value + (k if e.key() == Qt.Key_Up else -k))
            self._show()
            self.committed.emit(self._value)
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        if not self.hasFocus():
            e.ignore()
            return
        k = self.step * (1 if e.angleDelta().y() > 0 else -1)
        self._value = self._clamp(self._value + k)
        self._show()
        self.committed.emit(self._value)


class AnchorPicker(QWidget):
    """Griglia 3×3 per scegliere il punto di riferimento (0 = basso-sinistra ... 8 = alto-destra)."""

    changed = Signal(int)

    def __init__(self, value=0, cell=9, gap=3):  # nella barra numerica: cell=5, gap=2 (alta quanto i campi)
        super().__init__()
        self.value = value
        self.cell, self.gap = cell, gap
        s = 3 * cell + 2 * gap + 2
        self.setFixedSize(s, s)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("Punto di riferimento"))

    def setValue(self, v):
        self.value = v
        self.update()

    def _rect(self, i):
        col, row = i % 3, i // 3
        x = 1 + col * (self.cell + self.gap)
        y = 1 + (2 - row) * (self.cell + self.gap)
        return QRectF(x, y, self.cell, self.cell)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i in range(9):
            r = self._rect(i)
            on = i == self.value
            p.setPen(QPen(QColor(C["accent_hi"] if on else C["border"]), 1))
            p.setBrush(QColor(C["accent"] if on else C["bg"]))
            p.drawRoundedRect(r, 2, 2)

    def mousePressEvent(self, e):
        for i in range(9):
            if self._rect(i).adjusted(-2, -2, 2, 2).contains(e.position()):
                self.value = i
                self.update()
                self.changed.emit(i)
                return


class Swatch(QToolButton):
    def __init__(self, color, label="", tooltip=""):
        super().__init__()
        self.color = color
        self.label = label
        self.current = False
        self.used = False
        self.setFixedSize(26, 22)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(QPen(QColor("#FFFFFF" if self.current else (C["accent_hi"] if self.underMouse() else C["border"])),
                      2 if self.current else 1))
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(r, 4, 4)
        if self.label:
            p.setPen(QColor("#FFFFFF"))
            p.setFont(style.ui_font(7, style.QFont.Weight.DemiBold))
            p.drawText(r, Qt.AlignCenter, self.label)
        if self.used:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QPointF(r.right() - 4, r.top() + 4), 2, 2)


class SqueezeRow(QFrame):
    """Riga orizzontale che, quando lo spazio non basta, nasconde i pezzi facoltativi invece di uscire dal pannello
    (0.19.2: la riga di connessione del pannello Laser era più larga del pannello e veniva tagliata a destra,
    insieme a tutto quello che c'era sotto)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._optional = []

    def set_optional(self, widgets):
        """I pezzi che possono sparire, dal primo che si toglie all'ultimo."""
        self._optional = list(widgets)

    def _fixed_width(self):
        lay = self.layout()
        if lay is None:
            return 0
        m = lay.contentsMargins()
        ws = [lay.itemAt(i).widget() for i in range(lay.count())]
        fixed = [w for w in ws if w is not None and w not in self._optional]
        return m.left() + m.right() + sum(w.minimumSizeHint().width() if w.minimumWidth() == 0 else w.minimumWidth()
                                           for w in fixed) + lay.spacing() * max(0, len(fixed) - 1)

    def minimumSizeHint(self):
        h = super().minimumSizeHint().height()
        return QSize(self._fixed_width(), h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        lay = self.layout()
        if lay is None:
            return
        need = self._fixed_width()
        for w in reversed(self._optional):  # l'ultimo dell'elenco è quello che resta più a lungo
            add = w.sizeHint().width() + lay.spacing()
            show = need + add <= self.width()
            w.setVisible(show)
            if show:
                need += add


def shrinkable(root, cap=74):
    """Campi numerici e menu a tendina possono stringersi: il pannello si adatta alla larghezza dello schermo."""
    from PySide6.QtWidgets import QAbstractSpinBox, QComboBox

    for w in root.findChildren(QAbstractSpinBox) + root.findChildren(QComboBox):
        if w.minimumWidth() == 0:
            w.setMinimumWidth(min(w.minimumSizeHint().width(), cap))


def section(title):
    """Intestazione di sezione per i pannelli."""
    lab = QLabel(title.upper())
    lab.setStyleSheet(f"color:{C['muted']}; font-size:7.5pt; font-weight:700; letter-spacing:0.6px; padding-top:4px;")
    return lab


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{C['border']}; background:{C['border']}; max-height:1px;")
    return f


def row(*widgets, stretch=True, spacing=6):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(spacing)
    for x in widgets:
        if isinstance(x, str):
            lab = QLabel(x)
            lab.setObjectName("muted")
            h.addWidget(lab)
        else:
            h.addWidget(x)
    if stretch:
        h.addStretch(1)
    return w


# ================================================================ mezzetinte: le misure dei punti (0.19.0)
def halftone_size_tip():
    return tr("Solo con il metodo «Mezzetinte (retino)»: ingrandisce o rimpicciolisce tutti i punti lasciando ferma la "
              "distanza fra loro (la cella). 100% = il punto è grande quanto è scura la foto in quel posto. Più di "
              "100% = punti più grossi, incisione più scura; meno di 100% = punti più piccoli e staccati, incisione "
              "più chiara.")


def halftone_note(cell_mm, size_pct, dpi):
    """Le misure dei punti del retino, in parole, con gli avvisi quando servono (testo con il grassetto)."""
    from ..core import halftone

    d = halftone.dots(cell_mm, size_pct, dpi)
    text = tr("Punti del retino: il più grande {0:.2f} mm (nero pieno), il più piccolo {1:.2f} mm (zone chiare). "
              "Righe a {2:.2f} mm.", d["big"], d["small"], d["step"])
    if d["merged"]:
        text += " " + tr("Nel nero pieno i punti si fondono: nessun bianco fra loro.")
    if d["clamped"]:
        text += "<br>⚠ " + tr("La cella è più stretta di due righe: viene usata una cella di {0:.2f} mm. Aumenta la "
                              "cella o la risoluzione.", d["cell"])
    elif d["fine"]:
        text += "<br>⚠ " + tr("Nelle zone chiare i punti sarebbero più fini di una riga: lì il laser fa puntini singoli "
                              "e irregolari. Per averli tondi anche nei chiari aumenta la cella, la dimensione del punto "
                              "o la risoluzione.")
    return text
