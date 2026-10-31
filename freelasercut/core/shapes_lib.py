# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Galleria di forme parametriche: frecce, cuore, ingranaggio, scudo, medaglia, targa, etichetta…

Ogni forma è disegnata in un riquadro 0..w × 0..h (mm, Y in su) e ha un parametro principale
(spessore, numero di denti, giri, angolo…). Restano modificabili finché non le converti in tracciato.
"""
import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QTransform
from freelasercut.i18n import tr  # noqa: E402

# chiave: (nome, etichetta del parametro, minimo, massimo, default, decimali)
SHAPES = {
    "arrow": (tr("Freccia"), tr("Punta"), 0.15, 0.85, 0.4, 2),
    "double_arrow": (tr("Freccia doppia"), tr("Punte"), 0.1, 0.45, 0.28, 2),
    "heart": (tr("Cuore"), tr("Rotondità"), 0.0, 1.0, 0.5, 2),
    "cross": (tr("Croce"), tr("Spessore"), 0.1, 0.9, 0.34, 2),
    "gear": (tr("Ingranaggio"), tr("Denti"), 6, 60, 16, 0),
    "spiral": (tr("Spirale"), tr("Giri"), 1, 20, 4, 1),
    "bubble": (tr("Fumetto"), tr("Coda"), 0.1, 0.4, 0.22, 2),
    "drop": (tr("Goccia"), tr("Punta"), 0.1, 0.9, 0.45, 2),
    "moon": (tr("Luna"), tr("Fase"), 0.1, 0.9, 0.55, 2),
    "cloud": (tr("Nuvola"), tr("Bolle"), 3, 9, 5, 0),
    "shield": (tr("Scudo"), tr("Punta"), 0.1, 0.6, 0.35, 2),
    "plaque": (tr("Targa"), tr("Angoli"), 0.02, 0.3, 0.12, 2),
    "ornament": (tr("Medaglia con anello"), tr("Anello"), 0.06, 0.3, 0.14, 2),
    "tag": (tr("Etichetta con foro"), tr("Foro"), 0.05, 0.4, 0.18, 2),
    "ring": (tr("Anello"), tr("Spessore"), 0.03, 0.48, 0.15, 2),
    "frame": (tr("Cornice"), tr("Bordo"), 0.02, 0.45, 0.1, 2),
    "sector": (tr("Settore"), "Angolo °", 10, 350, 90, 0),
    "arc": (tr("Arco aperto"), "Angolo °", 10, 359, 180, 0),
    "triangle": (tr("Triangolo"), tr("Vertice"), 0.0, 1.0, 0.5, 2),
    "rhombus": (tr("Rombo"), "—", 0, 1, 0, 0),
    "trapezoid": (tr("Trapezio"), tr("Lato alto"), 0.1, 1.0, 0.6, 2),
    "lightning": (tr("Fulmine"), "—", 0, 1, 0, 0),
}
OPEN_SHAPES = {"spiral", "arc"}


def default_param(key):
    return SHAPES[key][4]


def _poly(pts, close=True):
    p = QPainterPath()
    p.moveTo(QPointF(*pts[0]))
    for q in pts[1:]:
        p.lineTo(QPointF(*q))
    if close:
        p.closeSubpath()
    return p


def _circle(p, cx, cy, r):
    p.addEllipse(QPointF(cx, cy), r, r)


def _bool(a, b, op):
    """Booleana precisa (le curve sono appiattite a 0,0003 del riquadro, non grossolanamente come fa Qt)."""
    from . import geom

    return geom.polys_to_path(geom.boolean(geom.flatten(a, 0.0003), geom.flatten(b, 0.0003), op))


def unit_path(key, t):
    """Forma nel quadrato unitario 0..1 (Y in su)."""
    p = QPainterPath()
    if key == "arrow":
        hl = t
        return _poly([(0, 0.32), (1 - hl, 0.32), (1 - hl, 0), (1, 0.5), (1 - hl, 1), (1 - hl, 0.68), (0, 0.68)])
    if key == "double_arrow":
        hl = t
        return _poly([(0, 0.5), (hl, 0), (hl, 0.32), (1 - hl, 0.32), (1 - hl, 0), (1, 0.5), (1 - hl, 1), (1 - hl, 0.68),
                      (hl, 0.68), (hl, 1)])
    if key == "heart":
        k = 0.15 + 0.2 * t
        p.moveTo(0.5, 0.0)
        p.cubicTo(0.5 - k, 0.18, 0.0, 0.42, 0.0, 0.7)
        p.cubicTo(0.0, 0.92, 0.25, 1.02, 0.36, 0.98)
        p.cubicTo(0.45, 0.95, 0.5, 0.86, 0.5, 0.8)
        p.cubicTo(0.5, 0.86, 0.55, 0.95, 0.64, 0.98)
        p.cubicTo(0.75, 1.02, 1.0, 0.92, 1.0, 0.7)
        p.cubicTo(1.0, 0.42, 0.5 + k, 0.18, 0.5, 0.0)
        p.closeSubpath()
        return p
    if key == "cross":
        a, b = 0.5 - t / 2, 0.5 + t / 2
        return _poly([(a, 0), (b, 0), (b, a), (1, a), (1, b), (b, b), (b, 1), (a, 1), (a, b), (0, b), (0, a), (a, a)])
    if key == "gear":
        n = max(6, int(round(t)))
        ro, ri = 0.5, 0.5 * (1 - 1.6 / n - 0.06)
        pts = []
        for i in range(n):
            a0 = 2 * math.pi * i / n
            for da, r in ((-0.27, ri), (-0.17, ro), (0.17, ro), (0.27, ri)):
                a = a0 + da * 2 * math.pi / n
                pts.append((0.5 + r * math.cos(a), 0.5 + r * math.sin(a)))
        p = _poly(pts)
        _circle(p, 0.5, 0.5, ri * 0.35)
        return p
    if key == "spiral":
        turns = max(0.5, t)
        steps = int(60 * turns)
        p.moveTo(0.5, 0.5)
        for i in range(1, steps + 1):
            a = 2 * math.pi * turns * i / steps
            r = 0.5 * i / steps
            p.lineTo(0.5 + r * math.cos(a), 0.5 + r * math.sin(a))
        return p
    if key == "bubble":
        tail = t
        top = 1.0
        bot = tail
        r = 0.12
        p.moveTo(r, bot)
        p.lineTo(0.22, bot)
        p.lineTo(0.12, 0.0)
        p.lineTo(0.42, bot)
        p.lineTo(1 - r, bot)
        p.quadTo(1, bot, 1, bot + r)
        p.lineTo(1, top - r)
        p.quadTo(1, top, 1 - r, top)
        p.lineTo(r, top)
        p.quadTo(0, top, 0, top - r)
        p.lineTo(0, bot + r)
        p.quadTo(0, bot, r, bot)
        p.closeSubpath()
        return p
    if key == "drop":
        k = 0.55 * (1 - t)  # punta più o meno affilata
        p.moveTo(0.5, 1.0)
        p.cubicTo(0.5 + 0.1 + k * 0.3, 0.84, 1.0, 0.62, 1.0, 0.38)
        p.cubicTo(1.0, 0.17, 0.78, 0.0, 0.5, 0.0)
        p.cubicTo(0.22, 0.0, 0.0, 0.17, 0.0, 0.38)
        p.cubicTo(0.0, 0.62, 0.5 - 0.1 - k * 0.3, 0.84, 0.5, 1.0)
        p.closeSubpath()
        return p
    if key == "moon":
        a = QPainterPath()
        _circle(a, 0.5, 0.5, 0.5)
        b = QPainterPath()
        _circle(b, 0.5 + t * 0.6, 0.58, 0.47)
        return _bool(a, b, "difference")
    if key == "cloud":
        n = max(3, int(round(t)))
        base = QPainterPath()
        base.addRoundedRect(QRectF(0.08, 0.0, 0.84, 0.36), 0.18, 0.18)
        bubbles = QPainterPath()
        for i in range(n):
            x = 0.2 + 0.6 * i / (n - 1)
            r = 0.17 + 0.13 * math.sin(math.pi * i / (n - 1))
            _circle(bubbles, x, 0.3 + 0.12 * math.sin(math.pi * i / (n - 1)), r)
        return _bool(base, bubbles, "union")
    if key == "shield":
        k = 1 - t
        p.moveTo(0, 1)
        p.lineTo(1, 1)
        p.lineTo(1, k)
        p.cubicTo(1, k * 0.45, 0.75, 0.15, 0.5, 0)
        p.cubicTo(0.25, 0.15, 0, k * 0.45, 0, k)
        p.closeSubpath()
        return p
    if key == "plaque":
        r = t
        p.moveTo(r, 0)
        p.lineTo(1 - r, 0)
        p.arcTo(QRectF(1 - r, -r, 2 * r, 2 * r), 180, -90)
        p.lineTo(1, 1 - r)
        p.arcTo(QRectF(1 - r, 1 - r, 2 * r, 2 * r), 270, -90)
        p.lineTo(r, 1)
        p.arcTo(QRectF(-r, 1 - r, 2 * r, 2 * r), 0, -90)
        p.lineTo(0, r)
        p.arcTo(QRectF(-r, -r, 2 * r, 2 * r), 90, -90)
        p.closeSubpath()
        return p
    if key == "ornament":
        lr = t  # raggio dell'anello (in proporzione)
        R = 0.5 * (1 - lr * 1.2)
        body = QPainterPath()
        _circle(body, 0.5, R, R)
        tab = QPainterPath()
        tab.addRoundedRect(QRectF(0.5 - lr, 2 * R - lr * 0.6, 2 * lr, lr * 2.2), lr, lr)
        out = _bool(body, tab, "union")
        hole = QPainterPath()
        _circle(hole, 0.5, 2 * R + lr * 0.6, lr * 0.45)
        out.addPath(hole)
        return out
    if key == "tag":
        hr = t * 0.5
        p = _poly([(0, 0), (0.78, 0), (1, 0.5), (0.78, 1), (0, 1)])
        _circle(p, 0.8, 0.5, hr * 0.6 + 0.02)
        return p
    if key == "ring":
        p.addEllipse(QRectF(0, 0, 1, 1))
        p.addEllipse(QRectF(t, t, 1 - 2 * t, 1 - 2 * t))
        return p
    if key == "frame":
        p.addRect(QRectF(0, 0, 1, 1))
        p.addRect(QRectF(t, t, 1 - 2 * t, 1 - 2 * t))
        return p
    if key == "sector":
        p.moveTo(0.5, 0.5)
        p.arcTo(QRectF(0, 0, 1, 1), 90 - t / 2, t)
        p.closeSubpath()
        return QTransform(1, 0, 0, -1, 0, 1).map(p)  # Qt misura gli angoli con Y in giù
    if key == "arc":
        p.arcMoveTo(QRectF(0, 0, 1, 1), 90 + t / 2)
        p.arcTo(QRectF(0, 0, 1, 1), 90 + t / 2, -t)
        return QTransform(1, 0, 0, -1, 0, 1).map(p)
    if key == "triangle":
        return _poly([(0, 0), (1, 0), (t, 1)])
    if key == "rhombus":
        return _poly([(0.5, 0), (1, 0.5), (0.5, 1), (0, 0.5)])
    if key == "trapezoid":
        a = (1 - t) / 2
        return _poly([(0, 0), (1, 0), (1 - a, 1), (a, 1)])
    if key == "lightning":
        return _poly([(0.62, 1), (0.18, 0.44), (0.46, 0.44), (0.34, 0), (0.82, 0.58), (0.54, 0.58)])
    return _poly([(0, 0), (1, 0), (1, 1), (0, 1)])


def natural_aspect(key):
    """Larghezza / altezza "naturale" della forma (per il clic semplice e per Maiusc)."""
    nat = {"sector": None, "arc": None, "arrow": 2.0, "double_arrow": 2.4, "cloud": 1.6, "bubble": 1.4, "plaque": 1.6, "tag": 1.7, "heart": 1.05,
           "ornament": None, "trapezoid": 1.4, "frame": 1.4, "lightning": 0.65, "shield": 0.85, "drop": 0.78}
    a = nat.get(key, 1.0)
    if a is None:  # medaglia (cerchio + anello), settore, arco: proporzioni della forma vera
        b = unit_path(key, default_param(key)).boundingRect()
        a = b.width() / b.height()
    return a


def make(key, w, h, t):
    up = unit_path(key, t)
    b = up.boundingRect()
    sx = w / max(b.width(), 1e-9)
    sy = h / max(b.height(), 1e-9)
    return (QTransform.fromTranslate(-b.left(), -b.top()) * QTransform.fromScale(sx, sy)).map(up)
