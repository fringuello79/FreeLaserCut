# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Stampa e taglia (0.18.5, funzione in prova): tagliare con il laser attorno a qualcosa di già stampato.

Si stampa su carta il disegno con due crocette; il foglio si appoggia sul piano come capita; si porta la testa
(con il puntino) sul centro delle due crocette; da quei due punti si ricava dove sta il foglio, quanto è ruotato e,
se serve, di quanto la stampante ha sbagliato la scala; il disegno sul piano viene spostato sopra il foglio vero.

Regole:
- si STAMPA quello che il laser non fa: le forme sui livelli con l'uscita spenta (crocette comprese);
- si TAGLIA quello che ha l'uscita accesa, come sempre;
- le crocette sono gruppi con `role` «pc1» e «pc2»: la 1 ha un cerchio, la 2 due cerchi (si distinguono sul foglio);
- coordinate del piano: mm, Y verso l'alto.
"""
import math

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPainterPath, QPdfWriter, QPen, QTransform

from .document import GroupShape, ImageShape, PathShape
from freelasercut.i18n import tr  # noqa: E402

ROLE_1, ROLE_2 = "pc1", "pc2"
MARK_ARM = 5.0  # mm: metà della crocetta
MARK_R = 1.5  # mm: raggio del cerchio (crocetta 2: anche il doppio)
MARK_GAP = 8.0  # mm fra il disegno e il centro della crocetta
PRINT_MARGIN = 5.0  # mm che le stampanti di casa non stampano
LINE_MM = 0.25  # tratto di stampa
MAX_SCALE_ERR = 0.03  # oltre il 3% non è un errore della stampante: la stampa non è al 100% (o le crocette sono scambiate)
MIN_BASE = 30.0  # mm: crocette più vicine di così danno un angolo poco preciso
TOOL_LAYER = 30  # livelli strumenti (guide): né stampati né tagliati
PAGES = {"A4": (210.0, 297.0), "Letter": (215.9, 279.4), "A3": (297.0, 420.0)}


class PrintCutError(ValueError):
    pass


# ======================================================================= crocette
def _line(x0, y0, x1, y1):
    p = QPainterPath()
    p.moveTo(x0, y0)
    p.lineTo(x1, y1)
    return PathShape(p)


def _circle(r):
    p = QPainterPath()
    p.addEllipse(QPointF(0.0, 0.0), r, r)
    return PathShape(p)


def make_mark(number, x, y, layer):
    """Crocetta con il centro in (x, y): due tratti e un cerchio; la n° 2 ha un secondo cerchio più grande."""
    kids = [_line(-MARK_ARM, 0, MARK_ARM, 0), _line(0, -MARK_ARM, 0, MARK_ARM), _circle(MARK_R)]
    if number == 2:
        kids.append(_circle(MARK_R * 2))
    for k in kids:
        k.layer = layer
    g = GroupShape(kids, layer=layer)
    g.role = ROLE_1 if number == 1 else ROLE_2
    g.apply(QTransform.fromTranslate(x, y))
    return g


def find_marks(doc):
    """(crocetta 1, crocetta 2) del piano attivo; None dove manca. Se ce n'è più di una per tipo vale l'ultima."""
    m1 = m2 = None
    for s in doc.shapes:
        if s.role == ROLE_1:
            m1 = s
        elif s.role == ROLE_2:
            m2 = s
    return m1, m2


def mark_center(mark):
    """Centro della crocetta sul piano: l'origine locale del gruppo (resta giusta anche dopo rotazioni e scale)."""
    p = mark.tf.map(QPointF(0.0, 0.0))
    return p.x(), p.y()


def design_bounds(doc):
    """Ingombro di tutto quello che si vede sul piano, crocette e guide escluse."""
    r = QRectF()
    for s in doc.shapes:
        if s.hidden or s.role in (ROLE_1, ROLE_2):
            continue
        if all(leaf.layer >= TOOL_LAYER for leaf, _ in s.leaves()):
            continue
        b = s.bounds()
        r = b if r.isNull() else r.united(b)
    return r


def mark_positions(bounds):
    """Dove vanno le due crocette: fuori dal disegno, in alto a sinistra e in basso a destra (la diagonale è la
    distanza più lunga possibile: più sono lontane, più l'angolo è preciso)."""
    return ((bounds.left() - MARK_GAP, bounds.bottom() + MARK_GAP),  # Y verso l'alto: bottom() è il lato in alto
            (bounds.right() + MARK_GAP, bounds.top() - MARK_GAP))


def _free_layer(doc):
    used = doc.used_layer_indices() | set(doc.layers)
    for i in range(1, TOOL_LAYER):
        if i not in used:
            return i
    return None


def print_layer(doc, name, mode="line"):
    """Il livello (uscita spenta) con quel nome, creato se manca. -> indice, o None se i livelli sono finiti."""
    for i, cs in doc.layers.items():
        if cs.name == name and not cs.output and i < TOOL_LAYER:
            return i
    i = _free_layer(doc)
    if i is None:
        return None
    cs = doc.layer(i)
    cs.name, cs.mode, cs.output = name, mode, False
    return i


# ======================================================================= allineamento
def fit(p1, p2, q1, q2, scale=True):
    """Trasformazione del piano che porta le crocette del disegno (p1, p2) sui punti misurati con la testa (q1, q2).

    Rotazione + spostamento; con scale=True anche la scala (i due punti combaciano esattamente), altrimenti le
    misure restano quelle del disegno e l'errore si divide a metà fra le due crocette.
    -> (QTransform, info) con info = angolo in gradi, distanze, differenza di scala, residuo in mm."""
    dp = (p2[0] - p1[0], p2[1] - p1[1])
    dq = (q2[0] - q1[0], q2[1] - q1[1])
    lp, lq = math.hypot(*dp), math.hypot(*dq)
    if lp < MIN_BASE:
        raise PrintCutError(tr("Le due crocette del disegno sono troppo vicine ({0:.1f} mm): allontanale almeno a "
                               "{1:g} mm.", lp, MIN_BASE))
    if lq < 1e-6:
        raise PrintCutError(tr("I due punti presi con la testa coincidono: la testa non si è spostata fra la "
                               "crocetta 1 e la crocetta 2."))
    k = lq / lp
    if abs(k - 1.0) > MAX_SCALE_ERR:
        raise PrintCutError(tr(
            "Fra le crocette il disegno misura {0:.1f} mm, sul foglio la testa ne ha misurati {1:.1f} ({2:+.1f}%). "
            "È troppo per un errore della stampante: controlla di aver stampato al 100% («dimensioni reali», senza "
            "«adatta alla pagina») e di aver puntato le crocette giuste.", lp, lq, (k - 1.0) * 100.0))
    ang = math.atan2(dq[1], dq[0]) - math.atan2(dp[1], dp[0])
    ang = (ang + math.pi) % (2 * math.pi) - math.pi
    s = k if scale else 1.0
    a, b = s * math.cos(ang), s * math.sin(ang)
    pm = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
    qm = ((q1[0] + q2[0]) / 2.0, (q1[1] + q2[1]) / 2.0)
    # x' = a(x-pmx) - b(y-pmy) + qmx ;  y' = b(x-pmx) + a(y-pmy) + qmy
    tf = QTransform(a, b, -b, a, qm[0] - a * pm[0] + b * pm[1], qm[1] - b * pm[0] - a * pm[1])
    r1 = tf.map(QPointF(*p1))
    info = {"angle": math.degrees(ang), "drawn": lp, "measured": lq, "scale": k, "scaled": bool(scale),
            "residual": math.hypot(r1.x() - q1[0], r1.y() - q1[1]),
            "shift": (qm[0] - pm[0], qm[1] - pm[1])}
    return tf, info


def cut_bounds(doc, tf=None):
    """Ingombro di quello che verrà tagliato (livelli con l'uscita accesa), dopo tf se c'è."""
    r = QRectF()
    for s in doc.shapes:
        if s.hidden:
            continue
        for leaf, ltf in s.leaves():
            cs = doc.layer(leaf.layer)
            if leaf.hidden or not cs.output or leaf.layer >= TOOL_LAYER:
                continue
            b = (ltf if tf is None else ltf * tf).map(leaf.local_path()).boundingRect()
            r = b if r.isNull() else r.united(b)
    return r


def outside_bed(rect, bed, eps=0.01):
    return (not rect.isNull()) and (rect.left() < -eps or rect.top() < -eps or rect.right() > bed[0] + eps
                                    or rect.bottom() > bed[1] + eps)


# ======================================================================= stampa
def print_leaves(doc):
    """[(foglia, trasformazione)] da stampare: visibili, su livelli con l'uscita spenta, guide escluse."""
    out = []
    for s in doc.shapes:
        if s.hidden:
            continue
        for leaf, tf in s.leaves():
            if leaf.hidden or leaf.layer >= TOOL_LAYER:
                continue
            if not doc.layer(leaf.layer).output:
                out.append((leaf, tf))
    return out


def print_bounds(doc):
    r = QRectF()
    for leaf, tf in print_leaves(doc):
        b = tf.map(leaf.local_path()).boundingRect()
        r = b if r.isNull() else r.united(b)
    if not r.isNull():  # il tratto delle crocette
        r = r.adjusted(-LINE_MM, -LINE_MM, LINE_MM, LINE_MM)
    return r


def page_fit(bounds, page="A4"):
    """-> (larghezza, altezza del foglio in mm, orizzontale?) dove il disegno entra con i margini; None se non entra."""
    w, h = PAGES[page]
    need = (bounds.width() + 2 * PRINT_MARGIN, bounds.height() + 2 * PRINT_MARGIN)
    if need[0] <= w and need[1] <= h:
        return w, h, False
    if need[0] <= h and need[1] <= w:
        return h, w, True
    return None


def _qimage(pil):
    img = pil.convert("RGBA")
    return QImage(img.tobytes("raw", "RGBA"), img.width, img.height, 4 * img.width, QImage.Format_RGBA8888).copy()


def paint_print(painter, doc, to_page):
    """Disegna le cose da stampare. to_page: QTransform piano (mm, Y su) -> unità del painter."""
    base = painter.transform()
    in_mark = {id(l) for m in find_marks(doc) if m is not None for l, _ in m.leaves()}
    for leaf, tf in print_leaves(doc):
        if isinstance(leaf, ImageShape):
            img = doc.images.get(leaf.image_id)
            if img is None:
                continue
            painter.save()
            flip = QTransform(1, 0, 0, -1, 0, leaf.h)  # i pixel hanno Y verso il basso
            painter.setTransform(flip * tf * to_page * base)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawImage(QRectF(0, 0, leaf.w, leaf.h), _qimage(img))
            painter.restore()
            continue
        painter.save()
        painter.setTransform(to_page * base)
        pen = QPen(QColor(0, 0, 0))
        pen.setWidthF(LINE_MM)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        fill = doc.layer(leaf.layer).mode in ("fill", "offset_fill") and id(leaf) not in in_mark
        painter.setBrush(QColor(0, 0, 0) if fill else Qt.NoBrush)
        painter.drawPath(tf.map(leaf.local_path()))
        painter.restore()


def export_pdf(doc, path, page="A4", resolution=600):
    """Il PDF da stampare al 100%: disegno e crocette al centro del foglio, nelle misure vere.
    -> dict (page, landscape, width, height, offset = spostamento piano -> foglio). PrintCutError se non si può."""
    m1, m2 = find_marks(doc)
    if m1 is None or m2 is None:
        raise PrintCutError(tr("Mancano le due crocette: aggiungile prima di stampare."))
    b = print_bounds(doc)
    fitp = page_fit(b, page)
    if fitp is None:
        w, h = PAGES[page]
        raise PrintCutError(tr(
            "Disegno e crocette misurano {0:.0f} × {1:.0f} mm: non entrano in un foglio {2} ({3:.0f} × {4:.0f} mm "
            "meno {5:g} mm di margine per lato). Rimpicciolisci il disegno o scegli un foglio più grande.",
            b.width(), b.height(), page, w, h, PRINT_MARGIN))
    W, H, land = fitp
    pdf = QPdfWriter(path)
    pdf.setResolution(int(resolution))
    pdf.setPageLayout(QPageLayout(QPageSize(QSizeF(*PAGES[page]), QPageSize.Millimeter, page),
                                  QPageLayout.Landscape if land else QPageLayout.Portrait, QMarginsF(0, 0, 0, 0),
                                  QPageLayout.Millimeter))
    pdf.setTitle(doc.name or "FreeLaserCut")
    pdf.setCreator("FreeLaserCut")
    ox, oy = (W - b.width()) / 2.0, (H - b.height()) / 2.0
    # piano (Y su) -> foglio (Y giù): X = x - sinistra + ox ; Y = alto - y + oy
    to_page = QTransform(1, 0, 0, -1, ox - b.left(), oy + b.bottom())
    painter = QPainter(pdf)
    if not painter.isActive():
        raise PrintCutError(tr("Non riesco a scrivere il file {0}.", path))
    try:
        k = resolution / 25.4
        painter.scale(k, k)
        painter.setRenderHint(QPainter.Antialiasing, True)
        paint_print(painter, doc, to_page)
    finally:
        painter.end()
    return {"page": page, "landscape": land, "width": W, "height": H, "to_page": to_page}


def import_print_image(doc, path, max_size=(180.0, 250.0)):
    """Un'immagine da stampare A COLORI (l'importazione normale la porta in grigi, perché il laser incide solo
    quelli): la tengo a colori e la metto su un livello con l'uscita spenta. -> [ImageShape]"""
    from PIL import Image

    from . import io_formats

    shapes = io_formats.import_image(path, doc, max_size=max_size)
    img = Image.open(path)
    img.load()
    doc.images[shapes[0].image_id] = io_formats._upright_8bit(img).convert("RGBA")
    layer = print_layer(doc, tr("Stampa"), "image")
    if layer is None:
        raise PrintCutError(tr("Non ci sono più livelli liberi per la stampa."))
    shapes[0].layer = layer
    return shapes
