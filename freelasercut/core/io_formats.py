# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Importazione ed esportazione: SVG, DXF, immagini raster; esportazione SVG.

Le forme importate tornano con l'ingombro che parte da (0,0): l'editor le posiziona
(centro della vista o posizione originale). I colori di linea/riempimento scelgono il
livello con il colore della tavolozza più vicino.
"""
import base64
import io
import math
import os
import uuid

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath, QTransform

from .document import LAYER_COLORS, GroupShape, ImageShape, PathShape
from freelasercut.i18n import tr  # noqa: E402

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")
VECTOR_EXT = (".svg", ".dxf")


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def nearest_layer(rgb):
    if rgb is None:
        return 0
    best, bd = 0, math.inf
    for i, h in enumerate(LAYER_COLORS):
        c = _hex_to_rgb(h)
        d = sum((a - b) ** 2 for a, b in zip(rgb, c))
        if d < bd:
            best, bd = i, d
    return best


def _normalize(shapes):
    """Sposta le forme in modo che l'ingombro complessivo parta da (0,0)."""
    r = QRectF()
    for s in shapes:
        b = s.bounds()
        r = b if r.isNull() else r.united(b)
    if r.isNull():
        return shapes
    t = QTransform.fromTranslate(-r.left(), -r.top())
    for s in shapes:
        s.apply(t)
    return shapes


# ======================================================================= SVG
def import_svg(path_or_bytes, doc):
    import svgelements as se

    src = path_or_bytes if isinstance(path_or_bytes, str) else io.BytesIO(path_or_bytes)
    svg = se.SVG.parse(src, ppi=96.0, reify=True)
    k = 25.4 / 96.0  # px -> mm
    shapes = []
    for el in svg.elements():
        if isinstance(el, se.Image):
            try:
                el.load(os.path.dirname(path_or_bytes) if isinstance(path_or_bytes, str) else None)
                img = el.image
            except Exception:  # noqa: BLE001
                img = None
            if img is None:
                continue
            iid = uuid.uuid4().hex[:12]
            doc.images[iid] = img.copy()
            try:
                x0, y0, x1, y1 = el.bbox()  # px, trasformazioni già applicate
            except Exception:  # noqa: BLE001
                x0, y0 = float(el.x or 0), float(el.y or 0)
                x1, y1 = x0 + float(el.width or img.width), y0 + float(el.height or img.height)
            s = ImageShape(iid, (x1 - x0) * k, (y1 - y0) * k, layer=0)
            s.set_transform(QTransform.fromTranslate(x0 * k, -y1 * k))
            shapes.append(s)
            continue
        if not isinstance(el, se.Shape):
            continue
        if isinstance(el, se.Shape) and el.values.get("visibility") == "hidden":
            continue
        try:
            p = se.Path(el)
        except Exception:  # noqa: BLE001
            continue
        if len(p) == 0:
            continue
        qp = _svgpath_to_qpath(p, k)
        if qp.isEmpty():
            continue
        color = None
        for attr in ("stroke", "fill"):
            c = getattr(el, attr, None)
            if c is not None and c.value is not None and getattr(c, "alpha", 255) > 0:
                color = (c.red, c.green, c.blue)
                break
        shapes.append(PathShape(qp, layer=nearest_layer(color)))
    shapes = _normalize(shapes)
    return [GroupShape(shapes)] if len(shapes) > 1 else shapes


def _svgpath_to_qpath(p, k):
    import svgelements as se

    qp = QPainterPath()

    def P(pt):
        return pt.x * k, -pt.y * k

    for seg in p:
        if isinstance(seg, se.Move):
            qp.moveTo(*P(seg.end))
        elif isinstance(seg, se.Close):
            qp.closeSubpath()
        elif isinstance(seg, se.Line):
            qp.lineTo(*P(seg.end))
        elif isinstance(seg, se.CubicBezier):
            qp.cubicTo(*P(seg.control1), *P(seg.control2), *P(seg.end))
        elif isinstance(seg, se.QuadraticBezier):
            qp.quadTo(*P(seg.control), *P(seg.end))
        elif isinstance(seg, se.Arc):
            for cub in seg.as_cubic_curves():
                qp.cubicTo(*P(cub.control1), *P(cub.control2), *P(cub.end))
        else:
            try:
                qp.lineTo(*P(seg.end))
            except Exception:  # noqa: BLE001
                pass
    return qp


# ======================================================================= DXF
_DXF_UNITS = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 8: 0.0000254, 9: 0.0254, 10: 914.4}


def import_dxf(path, doc):
    import ezdxf
    from ezdxf import path as dxfpath
    from ezdxf.path import Command

    dwg = ezdxf.readfile(path)
    k = _DXF_UNITS.get(dwg.header.get("$INSUNITS", 4), 1.0) or 1.0
    shapes = []
    msp = dwg.modelspace()
    for e in msp:
        try:
            if e.dxftype() in ("INSERT",):
                ents = list(e.virtual_entities())
            else:
                ents = [e]
            for ent in ents:
                try:
                    p = dxfpath.make_path(ent)
                except (TypeError, ValueError, AttributeError):
                    continue
                qp = QPainterPath()
                qp.moveTo(p.start.x * k, p.start.y * k)
                for cmd in p.commands():
                    if cmd.type == Command.MOVE_TO:
                        qp.moveTo(cmd.end.x * k, cmd.end.y * k)
                    elif cmd.type == Command.LINE_TO:
                        qp.lineTo(cmd.end.x * k, cmd.end.y * k)
                    elif cmd.type == Command.CURVE3_TO:
                        qp.quadTo(cmd.ctrl.x * k, cmd.ctrl.y * k, cmd.end.x * k, cmd.end.y * k)
                    elif cmd.type == Command.CURVE4_TO:
                        qp.cubicTo(cmd.ctrl1.x * k, cmd.ctrl1.y * k, cmd.ctrl2.x * k, cmd.ctrl2.y * k,
                                   cmd.end.x * k, cmd.end.y * k)
                if p.is_closed:
                    qp.closeSubpath()
                if qp.elementCount() > 1:
                    color = None
                    try:
                        if ent.dxf.hasattr("true_color"):
                            tc = ent.dxf.true_color
                            color = ((tc >> 16) & 255, (tc >> 8) & 255, tc & 255)
                    except Exception:  # noqa: BLE001
                        pass
                    shapes.append(PathShape(qp, layer=nearest_layer(color) if color else 0))
        except Exception:  # noqa: BLE001
            continue
    shapes = _normalize(shapes)
    return [GroupShape(shapes)] if len(shapes) > 1 else shapes


# ======================================================================= immagini
PHOTO_MM = 100.0  # lato lungo delle foto importate senza una risoluzione vera (si ridimensionano dopo)


def import_image(path_or_pil, doc, max_size=None, photo_mm=None):
    """photo_mm: le foto grandi senza risoluzione vera (fotocamere e telefoni dichiarano 72-96 dpi o nulla)
    arrivano con questo lato lungo invece che grandi quanto il piano: a 10 punti/mm una foto da 36 cm sono
    quasi 10 milioni di punti, ore di incisione e minuti solo per preparare il lavoro."""
    from PIL import Image

    img = Image.open(path_or_pil) if isinstance(path_or_pil, str) else path_or_pil
    img.load()
    dpi = img.info.get("dpi", (0, 0))[0] or 0
    no_dpi = not dpi or dpi <= 96
    if not dpi or dpi < 30:
        dpi = 254.0  # 10 pixel/mm se l'immagine non dichiara la risoluzione
    w = img.width / dpi * 25.4
    h = img.height / dpi * 25.4
    if photo_mm and no_dpi and max(img.width, img.height) >= 1200 and max(w, h) > photo_mm:
        f = photo_mm / max(w, h)
        w, h = w * f, h * f
    if max_size:
        mw, mh = max_size
        f = min(1.0, mw / w, mh / h)
        w, h = w * f, h * f
    keep = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("L")
    iid = uuid.uuid4().hex[:12]
    doc.images[iid] = keep
    return [ImageShape(iid, w, h, layer=0)]


def import_file(path, doc, max_size=None, photo_mm=None):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".svg":
        return import_svg(path, doc)
    if ext == ".dxf":
        return import_dxf(path, doc)
    if ext in IMAGE_EXT:
        return import_image(path, doc, max_size, photo_mm)
    raise ValueError(tr("formato non supportato: {0}", ext))


# ======================================================================= esportazione SVG
def export_svg(shapes, doc, path, bed=None):
    from .geom import flatten

    r = QRectF()
    for s in shapes:
        b = s.bounds()
        r = b if r.isNull() else r.united(b)
    if bed is not None:
        r = QRectF(0, 0, bed[0], bed[1])
    W, H = r.width(), r.height()
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'width="{W:.3f}mm" height="{H:.3f}mm" viewBox="0 0 {W:.3f} {H:.3f}">']

    def X(x):
        return x - r.left()

    def Y(y):
        return r.bottom() - y

    for s in shapes:
        for leaf, tf in s.leaves():
            color = LAYER_COLORS[leaf.layer % len(LAYER_COLORS)]
            if isinstance(leaf, ImageShape):
                img = doc.images.get(leaf.image_id)
                if img is None:
                    continue
                buf = io.BytesIO()
                img.save(buf, "PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                rect = tf.map(leaf.local_path()).boundingRect()
                out.append("<image x=\"{0:.3f}\" y=\"{1:.3f}\" width=\"{2:.3f}\" height=\"{3:.3f}\" preserveAspectRatio=\"none\" xlink:href=\"data:image/png;base64,{4}\"/>".format(X(rect.left()), Y(rect.bottom()), rect.width(), rect.height(), b64))
                continue
            qp = tf.map(leaf.local_path())
            d = []
            i = 0
            n = qp.elementCount()
            while i < n:
                e = qp.elementAt(i)
                t = e.type
                if t == QPainterPath.ElementType.MoveToElement:
                    d.append(f"M{X(e.x):.3f} {Y(e.y):.3f}")
                    i += 1
                elif t == QPainterPath.ElementType.LineToElement:
                    d.append(f"L{X(e.x):.3f} {Y(e.y):.3f}")
                    i += 1
                elif t == QPainterPath.ElementType.CurveToElement:
                    e2, e3 = qp.elementAt(i + 1), qp.elementAt(i + 2)
                    d.append(f"C{X(e.x):.3f} {Y(e.y):.3f} {X(e2.x):.3f} {Y(e2.y):.3f} {X(e3.x):.3f} {Y(e3.y):.3f}")
                    i += 3
                else:
                    i += 1
            out.append("<path d=\"{0}\" fill=\"none\" stroke=\"{1}\" stroke-width=\"0.1\"/>".format(" ".join(d), color))
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
