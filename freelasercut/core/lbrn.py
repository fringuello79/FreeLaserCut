# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Apertura dei progetti LightBurn (.lbrn2, e .lbrn della versione 0.9) con le impostazioni dei livelli.

Il formato è XML: impostazioni di taglio (<CutSetting>) e forme (<Shape>) con una matrice
<XForm> "a b c d e f" (x' = a·x + c·y + e, y' = b·x + d·y + f), coordinate in mm con Y in su,
come in FreeLaserCut. I tracciati sono una lista di vertici con maniglie (VertList) e una lista di
primitive (PrimList: Lxx yy = linea, Bxx yy = Bézier). Forme uguali condividono la geometria
tramite VertID / PrimID: la geometria è scritta solo la prima volta.
"""
import base64
import io
import re
import xml.etree.ElementTree as ET

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath, QTransform

from .document import (
    CutSettings, Document, EllipseShape, bake_mirror, GroupShape, ImageShape, PathShape, PolygonShape, RectShape, TextShape,
    default_layer,
)
from freelasercut.i18n import tr  # noqa: E402

TOOL_LAYER = 30

_MODE = {"cut": "line", "scan": "fill", "offset fill": "offset_fill", "offsetfill": "offset_fill", "image": "image",
         "scan+cut": "fill"}
_DITHER = {"threshold": "threshold", "ordered": "bayer", "atkinson": "atkinson", "dither": "floyd", "floyd": "floyd",
           "stucki": "stucki", "jarvis": "jarvis", "newsprint": "halftone", "halftone": "halftone", "sketch": "jarvis",
           "grayscale": "grayscale", "passthrough": "grayscale"}


def _f(el, key, default=None):
    """Valore di <key Value="..."/> (o attributo) come float."""
    if el is None:
        return default
    c = el.find(key)
    v = c.get("Value") if c is not None else el.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _s(el, key, default=None):
    c = el.find(key)
    if c is not None and c.get("Value") is not None:
        return c.get("Value")
    return el.get(key, default)


def _xform(el):
    x = el.find("XForm")
    if x is None or not (x.text or "").strip():
        return QTransform()
    a, b, c, d, e, f = (float(v) for v in x.text.split()[:6])
    return QTransform(a, b, c, d, e, f)


# ------------------------------------------------------------------ impostazioni di taglio
def cut_setting(el):
    idx = int(_f(el, "index", 0))
    idx = TOOL_LAYER if idx >= 30 else idx
    cs = default_layer(idx)
    typ = (el.get("type") or "Cut").strip().lower()
    cs.mode = _MODE.get(typ, "line")
    name = _s(el, "name", "")
    cs.name = "" if re.fullmatch(r"C\d\d", name or "") else (name or "")
    sp = _f(el, "speed")
    if sp is not None:
        cs.speed = round(sp * 60.0, 1)  # LightBurn salva sempre mm/s
    cs.power_max = _f(el, "maxPower", cs.power_max)
    cs.power_min = _f(el, "minPower", 0.0 if cs.mode != "image" else cs.power_min)
    cs.passes = int(_f(el, "numPasses", 1))
    cs.priority = int(_f(el, "priority", idx))
    cs.output = _f(el, "doOutput", 1) != 0
    cs.show = _f(el, "hide", 0) == 0
    air = _f(el, "airAssist", None)
    if air is None:
        air = _f(el, "enableAir", None)
    if air is not None:
        cs.air = air != 0
    cs.constant_power = _f(el, "constantPower", 0) != 0 or _f(el, "useConstantPower", 0) != 0
    cs.interval = _f(el, "interval", cs.interval)
    dpi = _f(el, "dpi", None)
    if cs.mode == "image":
        cs.dpi = dpi if dpi else 25.4 / max(cs.interval, 1e-3)
    cs.angle = _f(el, "angle", _f(el, "scanAngle", 0.0))
    cs.crosshatch = _f(el, "crossHatch", 0) != 0
    cs.bidirectional = _f(el, "bidir", 1) != 0
    ov = _f(el, "overscanning", None)
    if ov is not None:  # LightBurn la esprime in % della velocità; qui è una distanza (poi limitata ai bordi)
        cs.overscan = 0.0 if ov <= 0 else 2.5
    cs.negative = _f(el, "negImage", 0) != 0
    cs.dot_correction = _f(el, "dotWidth", 0.0) or 0.0
    dm = (_s(el, "ditherMode", "") or "").lower()
    if dm:
        cs.dither = _DITHER.get(dm, cs.dither)
    cs.kerf = _f(el, "kerf", 0.0) or 0.0
    cs.tabs = _f(el, "enableTabs", 0) != 0 or _f(el, "tabsEnabled", 0) != 0
    ts = _f(el, "tabSize", None)
    if ts:
        cs.tab_size = ts
    tc = _f(el, "tabCount", None)
    if tc and cs.tabs:
        cs.tab_count = int(tc)
    return cs


# ------------------------------------------------------------------ tracciati
_VTOK = re.compile(r"(V|c0x|c0y|c1x|c1y)(-?[\d.]+(?:[eE][-+]?\d+)?)")


def parse_verts(text):
    """'V x y c0x.. c0y.. c1x.. c1y..' -> lista di (punto, c0 o None, c1 o None).
    c0 = maniglia in uscita, c1 = maniglia in entrata; 'c0x1' da solo = nessuna maniglia."""
    verts = []
    text = re.sub(r"V(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)", r"V\1 Y\2", text)
    for chunk in text.split("V")[1:]:
        m = re.match(r"\s*(-?[\d.eE+-]+)\s+Y(-?[\d.eE+-]+)(.*)", chunk, re.S)
        if not m:
            continue
        x, y, rest = float(m.group(1)), float(m.group(2)), m.group(3)
        vals = dict(re.findall(r"(c[01][xy])(-?[\d.]+(?:[eE][-+]?\d+)?)", rest))
        # una maniglia vale solo con tutte e due le coordinate (alcuni file hanno solo c0y o solo c1y)
        c0 = (float(vals["c0x"]), float(vals["c0y"])) if "c0x" in vals and "c0y" in vals else None
        c1 = (float(vals["c1x"]), float(vals["c1y"])) if "c1x" in vals and "c1y" in vals else None
        verts.append(((x, y), c0, c1))
    return verts


def parse_prims(text, n):
    text = (text or "").strip()
    if text in ("LineClosed", "LineOpen", "Line") or not text:
        prims = [("L", i, i + 1) for i in range(n - 1)]
        if text != "LineOpen" and n > 2:
            prims.append(("L", n - 1, 0))
        return prims
    return [(t, int(a), int(b)) for t, a, b in re.findall(r"([LB])(\d+)\s+(\d+)", text)]


def build_path(verts, prims):
    p = QPainterPath()
    cur = None
    start = None
    for t, a, b in prims:
        if a >= len(verts) or b >= len(verts):
            continue
        if cur != a:
            if start is not None and cur == start:
                p.closeSubpath()
            p.moveTo(QPointF(*verts[a][0]))
            start = a
        pa, c0, _ = verts[a]
        pb, _, c1 = verts[b]
        if t == "B" and (c0 is not None or c1 is not None):
            p.cubicTo(QPointF(*(c0 or pa)), QPointF(*(c1 or pb)), QPointF(*pb))
        else:
            p.lineTo(QPointF(*pb))
        cur = b
        if b == start:
            p.closeSubpath()
            cur = None
            start = None
    return p


# ------------------------------------------------------------------ forme
class _Ctx:
    def __init__(self, root, doc):
        self.doc = doc
        self.verts = {}
        self.prims = {}
        self.warnings = []
        for sh in root.iter("Shape"):  # geometria condivisa: raccolta prima
            vl, pl = sh.find("VertList"), sh.find("PrimList")
            if vl is not None and sh.get("VertID") is not None and (vl.text or "").strip():
                self.verts.setdefault(sh.get("VertID"), vl.text)
            if pl is not None and sh.get("PrimID") is not None and (pl.text or "").strip():
                self.prims.setdefault(sh.get("PrimID"), pl.text)


def _layer(el):
    i = int(float(el.get("CutIndex", "0")))
    return TOOL_LAYER if i >= 30 else i


def _path_of(el, ctx):
    vl, pl = el.find("VertList"), el.find("PrimList")
    vt = vl.text if vl is not None and (vl.text or "").strip() else ctx.verts.get(el.get("VertID"))
    pt = pl.text if pl is not None and (pl.text or "").strip() else ctx.prims.get(el.get("PrimID"))
    if vt is None:
        return _legacy_path(el)
    verts = parse_verts(vt)
    return build_path(verts, parse_prims(pt, len(verts)))


def _legacy_path(el):
    """Formato .lbrn (LightBurn 0.9): <V vx= vy= c0x= …/> e <P T="L|B" p0= p1=/>."""
    vs = el.findall("V")
    if not vs:
        return None
    verts = []
    for v in vs:
        def g(k):
            x = v.get(k)
            return float(x) if x is not None else None
        c0 = (g("c0x"), g("c0y")) if v.get("c0x") is not None and v.get("c0y") is not None else None
        c1 = (g("c1x"), g("c1y")) if v.get("c1x") is not None and v.get("c1y") is not None else None
        verts.append(((g("vx") or 0.0, g("vy") or 0.0), c0, c1))
    ps = el.findall("P")
    prims = [("B" if p.get("T") == "B" else "L", int(p.get("p0", 0)), int(p.get("p1", 0))) for p in ps]
    if not prims:
        prims = parse_prims("LineClosed", len(verts))
    return build_path(verts, prims)


def _centered(shape, w, h, tf):
    shape.set_transform(QTransform.fromTranslate(-w / 2.0, -h / 2.0) * tf)
    return shape


def shape_from(el, ctx):
    typ = (el.get("Type") or "").lower()
    tf = _xform(el)
    if typ == "group":
        kids = [s for c in (el.find("Children") or []) for s in [shape_from(c, ctx)] if s is not None]
        if not kids:
            return None
        g = GroupShape(kids, kids[0].layer)
        g.set_transform(tf)
        return g
    if typ == "rect":
        w, h = float(el.get("W", 10)), float(el.get("H", 10))
        return _centered(RectShape(w, h, float(el.get("Cr", 0) or 0), _layer(el)), w, h, tf)
    if typ == "ellipse":
        rx, ry = float(el.get("Rx", 5)), float(el.get("Ry", el.get("Rx", 5)))
        return _centered(EllipseShape(2 * rx, 2 * ry, _layer(el)), 2 * rx, 2 * ry, tf)
    if typ == "polygon":
        n = int(float(el.get("N", 6)))
        r = float(el.get("Ry", el.get("Rx", 10)))
        rx = float(el.get("Rx", r))
        return _centered(PolygonShape(2 * rx, 2 * r, n, 0.0, _layer(el)), 2 * rx, 2 * r, tf)
    if typ == "text":
        return _text(el, ctx, tf)
    if typ == "bitmap":
        return _bitmap(el, ctx, tf)
    if typ == "path":
        p = _path_of(el, ctx)
        if p is None or p.isEmpty():
            return None
        s = PathShape(p, _layer(el))
        s.set_transform(tf)
        return s
    ctx.warnings.append(tr("forma di tipo «{0}» non supportata: saltata", el.get('Type')))
    return None


def _text(el, ctx, tf):
    font = (el.get("Font") or "Arial").split(",")[0] or "Arial"
    size = float(el.get("H", 10))
    align = {"0": "left", "1": "center", "2": "right"}.get(el.get("Ah", "0"), "left")
    t = TextShape(el.get("Str", ""), font, size * 0.72, _layer(el), bold=el.get("Bold") == "1",
                  italic=el.get("Italic") == "1", align=align, weld=el.get("Weld") == "1",
                  letter_spacing=float(el.get("LS", 0) or 0) * size / 100.0,
                  line_spacing=1.0 + float(el.get("LnS", 0) or 0) / 100.0)
    t.set_transform(tf)
    # se c'è il tracciato di riserva (testo già impaginato da LightBurn), allineo il nostro a quello
    backup = el.find("BackupPath")
    if backup is not None:
        bp = _path_of(backup, ctx)
        if bp is not None and not bp.isEmpty():
            # il tracciato di riserva ha la sua XForm completa (di solito uguale a quella del testo, non relativa):
            # applicarle tutte e due spostava il testo lontano dal suo posto
            btf = _xform(backup) if backup.find("XForm") is not None else tf
            target = btf.map(bp).boundingRect()
            mine = t.path().boundingRect()
            if mine.height() > 1e-6 and target.height() > 1e-6:
                k = target.height() / mine.height()
                t.size *= k
                t.invalidate()
                mine = t.path().boundingRect()
                t.apply(QTransform.fromTranslate(target.center().x() - mine.center().x(),
                                                 target.center().y() - mine.center().y()))
    return t


def _bitmap(el, ctx, tf):
    from PIL import Image

    data = el.get("Data")
    if not data:
        d = el.find("Data")
        data = d.text if d is not None else None
    if not data:
        ctx.warnings.append(tr("immagine senza dati: saltata"))
        return None
    img = Image.open(io.BytesIO(base64.b64decode(data)))
    img.load()
    iid = f"lb{len(ctx.doc.images) + 1}_{abs(hash(data[:200])) % 10**8}"
    pix = img.convert("RGBA") if img.mode not in ("L", "RGBA") else img.copy()
    w, h = float(el.get("W", img.width / 10)), float(el.get("H", img.height / 10))
    s = ImageShape(iid, w, h, _layer(el))
    s.brightness = float(el.get("Brightness", 0) or 0)
    s.contrast = float(el.get("Contrast", 0) or 0)
    s.gamma = float(el.get("Gamma", 1) or 1)
    # In LightBurn la prima riga di pixel dell'immagine sta a y = −H/2 nelle coordinate della forma (come in un
    # sistema con Y in giù); in FreeLaserCut la prima riga sta in alto (y = h). Senza questo ribaltamento le foto
    # salvate da LightBurn (che di solito hanno XForm "1 0 0 −1 …") si aprivano specchiate in verticale.
    # Se alla fine resta uno specchio (es. XForm "1 0 0 1"), lo sposto nei pixel: sul piano è uguale, ma
    # «Prepara foto», che mostra i pixel, la fa vedere come sul piano invece che specchiata.
    pix, m = bake_mirror(pix, w, h, QTransform(1, 0, 0, -1, -w / 2.0, h / 2.0) * tf)
    ctx.doc.images[iid] = pix
    s.set_transform(m)
    return s


# ------------------------------------------------------------------ progetto
def load(path, apply_variables=True):
    """-> (Document, avvisi). Il documento ha forme, livelli e numerazione del progetto LightBurn."""
    with open(path, "rb") as fh:
        raw = fh.read()
    root = ET.fromstring(raw)
    if root.tag not in ("LightBurnProject",):
        raise ValueError(tr("non è un progetto LightBurn"))
    doc = Document()
    ctx = _Ctx(root, doc)
    img_cs = {}
    for el in root.findall("CutSetting"):
        cs = cut_setting(el)
        doc.layers[cs.index] = cs
    for el in root.findall("CutSetting_Img"):
        cs = cut_setting(el)
        cs.mode = "image"
        img_cs[cs.index] = cs
    for el in root.findall("Shape"):
        s = shape_from(el, ctx)
        if s is not None:
            doc.add(s)
    # In LightBurn lo stesso colore può avere sia disegni (CutSetting) sia foto (CutSetting_Img), con impostazioni
    # diverse. In FreeLaserCut un livello ha una sola modalità: le foto di quel colore vanno su un livello libero
    # con le impostazioni da immagine, i disegni restano dove sono con le loro (prima le foto vincevano e i
    # disegni di quel colore sparivano dal lavoro).
    leaves = [leaf for s in doc.shapes for leaf, _ in s.leaves()]
    used = {leaf.layer for leaf in leaves}
    for index in sorted(used):
        imgs = [l for l in leaves if l.layer == index and isinstance(l, ImageShape)]
        vecs = [l for l in leaves if l.layer == index and not isinstance(l, ImageShape)]
        if imgs and vecs and index != TOOL_LAYER:
            free = next((i for i in range(TOOL_LAYER) if i not in used), None)
            if free is None:
                ctx.warnings.append(tr("colore {0}: foto e disegni insieme e nessun livello libero per separarli", index))
                continue
            used.add(free)
            src = img_cs.get(index) or default_layer(free)
            cs = CutSettings(**{**src.to_dict(), "index": free})
            if re.fullmatch(r"C\d\d", cs.name or ""):
                cs.name = ""  # «C00» di LightBurn su un altro livello confonderebbe: nome automatico
            cs.mode = "image"
            doc.layers[free] = cs
            for leaf in imgs:
                leaf.layer = free
            ctx.warnings.append(tr("colore {0}: le foto sono sul livello {1}, i disegni restano sul loro", index, cs.label()))
        elif imgs and index in img_cs:
            doc.layers[index] = img_cs[index]
    for s in doc.shapes:
        if isinstance(s, GroupShape) and s.children:
            s.layer = s.children[0].layer
    for s in doc.shapes:  # livelli usati senza impostazioni: valori predefiniti
        for leaf, _ in s.leaves():
            if leaf.layer not in doc.layers:
                doc.layers[leaf.layer] = default_layer(leaf.layer)
            if isinstance(leaf, ImageShape):
                doc.layers[leaf.layer].mode = "image"
    vt = root.find("VariableText")
    if vt is not None and apply_variables:
        from . import variables

        variables.from_dict({"serial": int(_f(vt, "Current", 0) or 0) or int(_f(vt, "Start", 1) or 1),
                             "step": int(_f(vt, "Increment", 1) or 1), "auto": _f(vt, "AutoAdvance", 0) != 0})
    notes = root.find("Notes")
    doc.notes = notes.get("Notes", "") if notes is not None else ""
    import os

    doc.name = os.path.splitext(os.path.basename(path))[0]
    return doc, ctx.warnings


def import_shapes(path, doc):
    """Importa le forme in un documento esistente; i livelli non ancora usati prendono le impostazioni LightBurn."""
    src, warnings = load(path, apply_variables=False)
    used = {leaf.layer for s in doc.shapes for leaf, _ in s.leaves()}
    for idx, cs in src.layers.items():
        if idx not in used:
            doc.layers[idx] = cs
    doc.images.update(src.images)
    return list(src.shapes)
