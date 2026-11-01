# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Testo -> tracciati in mm (Y su).

Due famiglie di caratteri:
  - font di sistema (TrueType/OpenType): contorni chiusi, si riempiono o si tagliano;
  - font a linea singola (Hershey): tratti aperti, si incidono con una sola passata
    di linea, ideali per scritte piccole, numerazioni, targhette.

La dimensione è l'altezza delle MAIUSCOLE in mm: scrivi 10 e la "H" è alta 10 mm.
"""
import math
from functools import lru_cache

from PySide6.QtCore import QPointF
from PySide6.QtGui import QFont, QFontMetricsF, QPainterPath, QTransform

try:
    from HersheyFonts import HersheyFonts
except ImportError:  # pragma: no cover
    HersheyFonts = None

REF = 100.0  # dimensione di riferimento per costruire i contorni

# nome interno -> nome mostrato
SINGLE_LINE_FONTS = {
    "futural": "FLC Linea · Sans",
    "futuram": "FLC Linea · Sans doppio",
    "rowmans": "FLC Linea · Roman",
    "rowmand": "FLC Linea · Roman doppio",
    "rowmant": "FLC Linea · Roman triplo",
    "timesr": "FLC Linea · Times",
    "timesi": "FLC Linea · Times corsivo",
    "timesrb": "FLC Linea · Times grassetto",
    "scripts": "FLC Linea · Corsivo",
    "scriptc": "FLC Linea · Corsivo elegante",
    "cursive": "FLC Linea · Calligrafico",
    "gothiceng": "FLC Linea · Gotico",
    "gothicita": "FLC Linea · Gotico italiano",
    "greek": "FLC Linea · Greco",
    "cyrillic": "FLC Linea · Cirillico",
}
SINGLE_LINE_BY_LABEL = {v: k for k, v in SINGLE_LINE_FONTS.items()}
SINGLE_LINE_BY_LABEL.update({v.replace("FLC Linea", "Freeburn Linea"): k for k, v in SINGLE_LINE_FONTS.items()})


def is_single_line(family):
    return family in SINGLE_LINE_FONTS or family in SINGLE_LINE_BY_LABEL


def _hershey_key(family):
    return family if family in SINGLE_LINE_FONTS else SINGLE_LINE_BY_LABEL.get(family)


@lru_cache(maxsize=32)
def _hershey(key):
    h = HersheyFonts()
    h.load_default_font(key)
    h.normalize_rendering(10.0)
    segs = list(h.lines_for_text("H"))
    ys = [p[1] for s in segs for p in s]
    base, cap = min(ys), max(ys) - min(ys)
    return h, base, cap


def _hershey_line(key, text, size):
    """Una riga di testo Hershey -> (QPainterPath aperto, larghezza) con baseline a y=0."""
    h, base, cap = _hershey(key)
    k = size / cap
    path = QPainterPath()
    last = None
    max_x = 0.0
    for (x1, y1), (x2, y2) in h.lines_for_text(text):
        a = (x1 * k, (y1 - base) * k)
        b = (x2 * k, (y2 - base) * k)
        if last is None or math.dist(last, a) > 1e-6:
            path.moveTo(*a)
        path.lineTo(*b)
        last = b
        max_x = max(max_x, a[0], b[0])
    # larghezza "tipografica": aggiungo l'avanzamento di uno spazio stimato
    return path, max_x


def _system_line(font, text, size, letter_mm):
    f = QFont(font)
    f.setPointSizeF(REF)
    probe = QPainterPath()
    probe.addText(QPointF(0, 0), f, "H")
    cap_ref = probe.boundingRect().height() or REF * 0.7
    k = size / cap_ref
    if letter_mm:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_mm / k)
    p = QPainterPath()
    p.addText(QPointF(0, 0), f, text)
    width = QFontMetricsF(f).horizontalAdvance(text) * k
    # Qt: Y verso il basso -> ribalto e scalo in mm
    t = QTransform.fromScale(k, -k)
    return t.map(p), width


def text_path(text, family="Arial", size=10.0, bold=False, italic=False, align="left",
              letter_spacing=0.0, line_spacing=1.0, upper=False):
    """Testo multilinea -> QPainterPath in mm. Baseline della prima riga a y=0.

    align: left | center | right   ·   letter_spacing: mm extra fra le lettere
    line_spacing: 1.0 = interlinea normale (1,5 × altezza maiuscole)."""
    if upper:
        text = text.upper()
    lines = text.split("\n") if text else [""]
    key = _hershey_key(family)
    font = None
    if key is None:
        font = QFont(family)
        font.setBold(bold)
        font.setItalic(italic)
    advance = size * 1.5 * line_spacing
    out = QPainterPath()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if key is not None and HersheyFonts is not None:
            p, w = _hershey_line(key, line, size)
            if letter_spacing:
                p, w = _spaced_hershey(key, line, size, letter_spacing)
            if italic:
                p = QTransform(1, 0, 0.2, 1, 0, 0).map(p)  # obliquo
        else:
            p, w = _system_line(font, line, size, letter_spacing)
        dx = {"left": 0.0, "center": -w / 2.0, "right": -w}.get(align, 0.0)
        p.translate(dx, -i * advance)
        out.addPath(p)
    return out


def _spaced_hershey(key, line, size, spacing):
    p = QPainterPath()
    x = 0.0
    for ch in line:
        g, w = _hershey_line(key, ch, size)
        if ch == " ":
            w = size * 0.5
        g.translate(x, 0)
        p.addPath(g)
        x += w + spacing + size * 0.12
    return p, x


def bend_path(path, arc_deg, gap=0.0):
    """Curva il testo su un arco di cerchio. arc_deg: ampiezza dell'arco occupato dal testo
    (positivo = a ponte, lettere sopra il cerchio; negativo = a sorriso, lettere sotto; 360 = cerchio intero).
    Il centro orizzontale del testo resta fermo, le lettere restano dritte rispetto al raggio."""
    if not arc_deg or path.isEmpty():
        return path
    from . import geom

    b = path.boundingRect()
    width = max(b.width(), 1e-6)
    theta = math.radians(arc_deg)
    R = (width + (gap if abs(arc_deg) > 300 else 0.0)) / theta  # raggio sulla linea di base (negativo = sorriso)
    cx = b.center().x()
    polys = geom.flatten(path, 0.01)
    out = []
    step = max(0.05, min(0.5, abs(R) * 0.01))
    for pl in polys:
        pts = list(pl.pts)
        if pl.closed and pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        dense = []
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            n = max(1, int(math.dist((x1, y1), (x2, y2)) / step))
            for k in range(n):
                t = k / n
                dense.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
        if pts:
            dense.append(pts[-1])
        warped = []
        for x, y in dense:
            a = (x - cx) / R
            r = R + y
            warped.append((cx + r * math.sin(a), r * math.cos(a) - R))
        if pl.closed and len(warped) > 1:
            warped = warped[:-1]
        out.append(geom.Poly(warped, pl.closed))
    return geom.polys_to_path(out)


def bend_radius(path, arc_deg):
    """Raggio (mm, sulla linea di base) che corrisponde all'arco scelto."""
    if not arc_deg or path.isEmpty():
        return 0.0
    return path.boundingRect().width() / math.radians(arc_deg)


def system_families():
    from PySide6.QtGui import QFontDatabase

    fams = [f for f in QFontDatabase.families() if not QFontDatabase.isPrivateFamily(f)]
    return sorted(set(fams), key=str.lower)


def follow_path(path, curve, start=0.5, align="center", offset=0.0, reverse=False):
    """Fa seguire al testo (baseline y=0, da x=0) una curva qualsiasi.
    start: punto della curva (0…1 della lunghezza) a cui si aggancia il testo; align: left | center | right
    (quale punto del testo va lì); offset: distanza dalla curva in mm (+ verso sinistra rispetto al verso di
    percorrenza, cioè «sopra» se la curva va da sinistra a destra); reverse: percorre la curva al contrario."""
    from . import geom

    if path.isEmpty() or curve.isEmpty():
        return path
    cpolys = [p for p in geom.flatten(curve, 0.02) if len(p.pts) >= 2]
    if not cpolys:
        return path
    cp = max(cpolys, key=lambda p: p.length())
    pts = list(cp.pts)
    if cp.closed:
        pts.append(pts[0])
    if reverse:
        pts.reverse()
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + math.dist(pts[i - 1], pts[i]))
    total = cum[-1]
    if total <= 1e-9:
        return path
    b = path.boundingRect()
    width = max(b.right(), 0.0)
    s0 = start * total - {"left": 0.0, "center": width / 2.0, "right": width}.get(align, width / 2.0)
    import bisect

    def at(s):
        if cp.closed:
            s %= total
        if s <= 0:
            i = 1
        elif s >= total:
            i = len(pts) - 1
        else:
            i = max(1, bisect.bisect_left(cum, s))
        (x1, y1), (x2, y2) = pts[i - 1], pts[i]
        seg = max(cum[i] - cum[i - 1], 1e-12)
        t = (s - cum[i - 1]) / seg
        tx, ty = (x2 - x1) / seg, (y2 - y1) / seg
        return x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, tx, ty

    step = max(0.05, min(0.4, (b.height() or 5.0) / 25.0))
    out = []
    for pl in geom.flatten(path, 0.01):
        src = list(pl.pts)
        if pl.closed and src and src[0] != src[-1]:
            src.append(src[0])
        dense = []
        for i in range(len(src) - 1):
            (x1, y1), (x2, y2) = src[i], src[i + 1]
            n = max(1, int(math.dist((x1, y1), (x2, y2)) / step))
            for k in range(n):
                t = k / n
                dense.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
        if src:
            dense.append(src[-1])
        warped = []
        for x, y in dense:
            px, py, tx, ty = at(s0 + x)
            d = y + offset
            warped.append((px - ty * d, py + tx * d))
        if pl.closed and len(warped) > 1:
            warped = warped[:-1]
        out.append(geom.Poly(warped, pl.closed))
    return geom.polys_to_path(out)
