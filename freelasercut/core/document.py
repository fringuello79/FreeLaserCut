# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Documento di FreeLaserCut: forme, livelli (impostazioni di taglio), immagini, salvataggio .flcut.

Ogni forma ha una geometria "locale" parametrica (rettangolo, ellisse, testo...) e una
trasformazione affine (sposta/scala/ruota/specchia). Così un rettangolo resta un
rettangolo modificabile (raggio degli angoli, dimensioni) finché non lo converti in tracciato.
"""
import base64
import copy
import io
import json
import math
import uuid
import zipfile
from dataclasses import asdict, dataclass, field

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QTransform

from . import geom, text as textmod, variables
from freelasercut.i18n import tr  # noqa: E402

FORMAT_VERSION = 1

# 30 colori di livello: distinti fra loro, leggibili su fondo scuro e su foto
LAYER_COLORS = [
    "#111111", "#2E7CF6", "#E5484D", "#30A46C", "#F5A524", "#8E6CF0", "#22B8CF", "#E54DB0",
    "#8A5A2B", "#7C8A99", "#F07A2E", "#0F7D7E", "#B8D435", "#6B4BD8", "#D6336C", "#1C7ED6",
    "#2F9E44", "#E8590C", "#5C940D", "#862E9C", "#C2255C", "#0B7285", "#A61E4D", "#364FC7",
    "#087F5B", "#D9480F", "#5F3DC4", "#1864AB", "#E67700", "#495057",
]
MODES = ("line", "fill", "offset_fill", "image")
MODE_LABELS = {"line": tr("Linea"), "fill": tr("Riempimento"), "offset_fill": tr("Riempimento offset"), "image": tr("Immagine")}
DITHERS = ("grayscale", "threshold", "floyd", "jarvis", "stucki", "atkinson", "bayer", "halftone")
DITHER_LABELS = {
    "grayscale": tr("Scala di grigi (potenza variabile)"), "threshold": tr("Soglia"), "floyd": "Floyd–Steinberg",
    "jarvis": tr("Jarvis"), "stucki": tr("Stucki"), "atkinson": tr("Atkinson"), "bayer": tr("Ordinato (Bayer)"),
    "halftone": tr("Mezzetinte (retino)"),
}
# punto di partenza delle immagini: chiave -> nome nella finestra
IMAGE_STARTS = {
    "top": tr("Dall'alto, righe orizzontali"),
    "bottom": tr("Dal basso, righe orizzontali"),
    "left": tr("Da sinistra, righe verticali"),
    "right": tr("Da destra, righe verticali"),
}


@dataclass
class CutSettings:
    index: int = 0
    name: str = ""
    mode: str = "line"
    speed: float = 1500.0  # mm/min
    power_max: float = 30.0  # %
    power_min: float = 0.0  # %
    passes: int = 1
    air: bool = True
    constant_power: bool = False  # M3 invece di M4
    output: bool = True
    show: bool = True
    priority: int = 0
    # linea
    kerf: float = 0.0  # mm: >0 verso fuori sui contorni esterni
    tabs: bool = False
    tab_size: float = 0.5  # mm di ponticello
    tab_count: int = 4
    # riempimento
    interval: float = 0.1  # mm fra le righe
    angle: float = 0.0  # gradi
    crosshatch: bool = False
    bidirectional: bool = True
    overscan: float = 2.5  # mm
    fill_grouping: str = "auto"  # auto | together | each
    # immagine
    dpi: float = 254.0
    dither: str = "grayscale"
    negative: bool = False
    dot_correction: float = 0.0  # mm
    halftone_cell: float = 1.0  # mm
    halftone_angle: float = 45.0
    halftone_size: float = 100.0  # % del diametro dei punti del retino (0.19.0): 100 = l'area segue lo scuro della foto
    image_start: str = "top"  # immagini: da dove parte (vedi IMAGE_STARTS)
    burn_curve: str = ""  # foto in scala di grigi: curva di un materiale imparato (core/burn_curve), "" = nessuna

    @property
    def color(self):
        return LAYER_COLORS[self.index % len(LAYER_COLORS)]

    def label(self):
        return self.name or f"C{self.index:02d}"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        cs = cls(**known)
        if not isinstance(cs.image_start, str) or cs.image_start not in IMAGE_STARTS:  # versione futura o file rovinato
            cs.image_start = "top"
        if not isinstance(cs.burn_curve, str):
            cs.burn_curve = ""
        from .halftone import clamp_size

        cs.halftone_size = clamp_size(cs.halftone_size)
        return cs


def default_layer(index):
    cs = CutSettings(index=index)
    if index == 0:
        cs.mode, cs.speed, cs.power_max = "fill", 3000.0, 25.0
    return cs


# ======================================================================= forme
class Shape:
    kind = "shape"

    def __init__(self, layer=1):
        self.id = uuid.uuid4().hex[:12]
        self.layer = layer
        self.tf = QTransform()
        self.locked = False
        self.hidden = False
        self.role = ""  # 0.18.5: compito speciale della forma («pc1» / «pc2» = crocette di Stampa e taglia)
        self._cache = None

    # geometria
    def local_path(self) -> QPainterPath:  # pragma: no cover - sottoclassi
        return QPainterPath()

    def invalidate(self):
        self._cache = None

    def _scale(self):
        """Quanto è stirata la forma dalla sua trasformazione (ridimensionata dopo il disegno): mm per unità.
        (0.17.15 nel rettangolo; 0.18.2 qui per tutte, la usa anche il poligono.)"""
        t = self.tf
        sx = math.hypot(t.m11(), t.m12()) or 1.0
        sy = math.hypot(t.m21(), t.m22()) or 1.0
        return sx, sy

    def path(self) -> QPainterPath:
        if self._cache is None:
            self._cache = self.tf.map(self.local_path())
        return self._cache

    def bounds(self) -> QRectF:
        return self.path().boundingRect()

    def closed(self):
        polys = geom.flatten(self.path(), 0.05)
        return bool(polys) and all(p.closed for p in polys)

    def set_transform(self, tf):
        self.tf = QTransform(tf)
        self.invalidate()

    def apply(self, tf):
        """Applica una trasformazione nel sistema del piano (dopo quella esistente)."""
        self.tf = self.tf * tf
        self.invalidate()

    def leaves(self, tf=None):
        """Forme elementari con la trasformazione completa (i gruppi si "aprono")."""
        yield self, (self.tf if tf is None else self.tf * tf)

    # serializzazione
    def params(self):
        return {}

    def to_dict(self):
        d = {"kind": self.kind, "id": self.id, "layer": self.layer, "tf": geom.transform_to_list(self.tf),
             "locked": self.locked, "hidden": self.hidden, "p": self.params()}
        if self.role:  # solo se c'è: i progetti senza restano identici
            d["role"] = self.role
        return d

    def _load_common(self, d):
        self.id = d.get("id", self.id)
        self.layer = d.get("layer", 1)
        self.tf = geom.transform_from_list(d["tf"]) if "tf" in d else QTransform()
        self.locked = d.get("locked", False)
        self.hidden = d.get("hidden", False)
        role = d.get("role", "")
        self.role = role if isinstance(role, str) else ""

    def clone(self, new_id=True):
        c = shape_from_dict(self.to_dict(), getattr(self, "_doc_images", None))
        if new_id:
            renew_ids(c)
        return c

    def describe(self):
        return self.kind


class RectShape(Shape):
    kind = "rect"
    CORNERS = ("tl", "tr", "br", "bl")  # ordine dei raggi: in alto a sinistra, in alto a destra, in basso a destra…
    K = 0.5522847498  # quarto di cerchio con una curva di Bézier

    def __init__(self, w=10.0, h=10.0, radius=0.0, layer=1, radii=None):
        super().__init__(layer)
        self.w, self.h, self.radius = float(w), float(h), float(radius)
        # 0.17.13: raggio di ogni angolo (come si vede sul piano: ↖ ↗ ↘ ↙); None = tutti uguali a «radius»
        self.radii = [float(v) for v in radii] if radii is not None and len(radii) == 4 else None

    def max_radius(self):
        """0.17.15: raggio massimo in mm, metà del lato più corto come si vede sul piano."""
        sx, sy = self._scale()
        return min(abs(self.w) * sx, abs(self.h) * sy) / 2

    def corner_radii(self):
        """[↖, ↗, ↘, ↙] in mm sul piano, già limitati alla metà del lato più corto."""
        lim = self.max_radius()
        vals = self.radii if self.radii is not None else [self.radius] * 4
        return [max(0.0, min(float(v), lim)) for v in vals]

    def local_path(self):
        # 0.17.15: i raggi sono in mm veri anche se il rettangolo è stato ridimensionato dopo il disegno (prima erano
        # nelle misure di quando era stato disegnato: il massimo restava quello vecchio e i valori non cambiavano)
        sx, sy = self._scale()
        p = QPainterPath()
        if self.radii is None:
            r = max(0.0, min(self.radius, self.max_radius()))
            if r > 0:
                p.addRoundedRect(QRectF(0, 0, self.w, self.h), r / sx, r / sy)
            else:
                p.addRect(QRectF(0, 0, self.w, self.h))
            return p
        tl, tr_, br, bl = self.corner_radii()
        x0, x1 = min(0.0, self.w), max(0.0, self.w)
        y0, y1 = min(0.0, self.h), max(0.0, self.h)  # sul piano Y va verso l'alto: y1 è il lato in alto
        k = self.K

        def corner(a, c, b, r):
            if r <= 0:
                p.lineTo(*c)
                return
            p.lineTo(*a)
            p.cubicTo(a[0] + k * (c[0] - a[0]), a[1] + k * (c[1] - a[1]),
                      b[0] + k * (c[0] - b[0]), b[1] + k * (c[1] - b[1]), b[0], b[1])

        # in coordinate locali un raggio di r mm è r/sx in orizzontale e r/sy in verticale
        p.moveTo(x0 + bl / sx, y0)
        corner((x1 - br / sx, y0), (x1, y0), (x1, y0 + br / sy), br)
        corner((x1, y1 - tr_ / sy), (x1, y1), (x1 - tr_ / sx, y1), tr_)
        corner((x0 + tl / sx, y1), (x0, y1), (x0, y1 - tl / sy), tl)
        corner((x0, y0 + bl / sy), (x0, y0), (x0 + bl / sx, y0), bl)
        p.closeSubpath()
        return p

    def params(self):
        d = {"w": self.w, "h": self.h, "radius": self.radius}
        if self.radii is not None:
            d["radii"] = list(self.radii)
        return d

    def describe(self):
        return tr("Rettangolo")


class EllipseShape(Shape):
    kind = "ellipse"

    def __init__(self, w=10.0, h=10.0, layer=1):
        super().__init__(layer)
        self.w, self.h = float(w), float(h)

    def local_path(self):
        p = QPainterPath()
        p.addEllipse(QRectF(0, 0, self.w, self.h))
        return p

    def params(self):
        return {"w": self.w, "h": self.h}

    def describe(self):
        return tr("Cerchio") if abs(self.w - self.h) < 1e-6 else tr("Ellisse")


class PolygonShape(Shape):
    kind = "polygon"

    def __init__(self, w=10.0, h=10.0, sides=6, star=0.0, layer=1, radius=0.0):
        super().__init__(layer)
        self.w, self.h = float(w), float(h)
        self.sides = int(sides)
        self.star = float(star)  # 0 = poligono; 0..0.95 = rientranza della stella
        self.radius = float(radius)  # 0.18.2: raggio degli angoli in mm veri sul piano (0 = spigoli vivi)

    def _points(self):
        n = max(3, self.sides)
        rx, ry = self.w / 2, self.h / 2
        pts = []
        count = n * 2 if self.star > 0 else n
        for i in range(count):
            a = math.pi / 2 + 2 * math.pi * i / count
            k = (1 - self.star) if (self.star > 0 and i % 2 == 1) else 1.0
            pts.append((rx + rx * k * math.cos(a), ry + ry * k * math.sin(a)))
        return pts

    def max_radius(self):
        """0.18.2: raggio più grande senza che nessun angolo venga limitato (mm sul piano)."""
        from . import nodes

        sx, sy = self._scale()
        return nodes.corner_limit([(x * sx, y * sy) for x, y in self._points()])

    def local_path(self):
        pts = self._points()
        if self.radius > 0:
            from . import nodes

            # gli archi si calcolano in mm veri (forma ridimensionata dopo il disegno) e si riportano in locale
            sx, sy = self._scale()
            sp = nodes.round_corners([(x * sx, y * sy) for x, y in pts], self.radius)
            back = lambda q: None if q is None else (q[0] / sx, q[1] / sy)  # noqa: E731
            for nd in sp.nodes:
                nd.x, nd.y = nd.x / sx, nd.y / sy
                nd.cin, nd.cout = back(nd.cin), back(nd.cout)
            return nodes.to_path([sp])
        p = QPainterPath()
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        p.closeSubpath()
        return p

    def params(self):
        d = {"w": self.w, "h": self.h, "sides": self.sides, "star": self.star}
        if self.radius > 0:  # senza raggio il file resta identico a prima
            d["radius"] = self.radius
        return d

    def describe(self):
        return f"Stella {self.sides} punte" if self.star > 0 else f"Poligono {self.sides} lati"


class PathShape(Shape):
    kind = "path"

    def __init__(self, path=None, layer=1):
        super().__init__(layer)
        self.qpath = QPainterPath(path) if path is not None else QPainterPath()

    def local_path(self):
        return QPainterPath(self.qpath)

    def set_path(self, path):
        self.qpath = QPainterPath(path)
        self.invalidate()

    def params(self):
        els = []
        for i in range(self.qpath.elementCount()):
            e = self.qpath.elementAt(i)
            els.append([int(e.type.value) if hasattr(e.type, "value") else int(e.type), e.x, e.y])
        return {"elements": els}

    @staticmethod
    def path_from_elements(els):
        p = QPainterPath()
        i = 0
        while i < len(els):
            t, x, y = els[i]
            if t == 0:
                p.moveTo(x, y)
                i += 1
            elif t == 1:
                p.lineTo(x, y)
                i += 1
            elif t == 2 and i + 2 < len(els):
                p.cubicTo(x, y, els[i + 1][1], els[i + 1][2], els[i + 2][1], els[i + 2][2])
                i += 3
            else:
                i += 1
        return p

    def describe(self):
        polys = geom.flatten(self.qpath, 0.1)
        if len(polys) == 1:
            return tr("Tracciato chiuso") if polys[0].closed else tr("Linea")
        return f"Tracciato ({len(polys)} parti)"


class TextShape(Shape):
    kind = "text"

    def __init__(self, text=tr("Testo"), family="Arial", size=10.0, layer=1, **kw):
        super().__init__(layer)
        self.text = text
        self.family = family
        self.size = float(size)
        self.bold = kw.get("bold", False)
        self.italic = kw.get("italic", False)
        self.align = kw.get("align", "left")
        self.letter_spacing = float(kw.get("letter_spacing", 0.0))
        self.line_spacing = float(kw.get("line_spacing", 1.0))
        self.upper = kw.get("upper", False)
        self.weld = kw.get("weld", False)
        self.arc = float(kw.get("arc", 0.0))  # gradi d'arco: 0 = dritto, + a ponte, - a sorriso
        self.var_offset = int(kw.get("var_offset", 0))  # copia n° (testo variabile)

    @property
    def single_line(self):
        return textmod.is_single_line(self.family)

    @property
    def variable(self):
        return variables.has_vars(self.text)

    def shown_text(self):
        return variables.expand(self.text, self.var_offset) if self.variable else self.text

    def local_path(self):
        p = textmod.text_path(self.shown_text(), self.family, self.size, self.bold, self.italic, self.align,
                              self.letter_spacing, self.line_spacing, self.upper)
        if self.weld and not self.single_line:
            polys = geom.union_all(geom.flatten(p, 0.02))
            p = geom.polys_to_path(polys)
        if self.arc:
            p = textmod.bend_path(p, self.arc, self.size * 0.8)
        return p

    def params(self):
        return {"text": self.text, "family": self.family, "size": self.size, "bold": self.bold,
                "italic": self.italic, "align": self.align, "letter_spacing": self.letter_spacing,
                "line_spacing": self.line_spacing, "upper": self.upper, "weld": self.weld, "arc": self.arc,
                "var_offset": self.var_offset}

    def describe(self):
        return tr("Testo variabile") if self.variable else tr("Testo")


class TextPathShape(TextShape):
    """Testo che segue una curva qualsiasi (copia della curva al momento della creazione)."""

    kind = "textpath"

    def __init__(self, text=tr("Testo"), family="Arial", size=10.0, layer=1, **kw):
        kw = dict(kw)
        self.curve = kw.pop("curve", [])  # elementi del percorso (formato di PathShape)
        self.start = float(kw.pop("start", 0.5))
        self.offset = float(kw.pop("offset", 0.0))
        self.reverse = bool(kw.pop("reverse", False))
        kw["arc"] = 0.0
        kw.setdefault("align", "center")
        super().__init__(text, family, size, layer, **kw)

    def curve_path(self):
        return PathShape.path_from_elements(self.curve)

    def local_path(self):
        p = textmod.text_path(self.shown_text(), self.family, self.size, self.bold, self.italic, "left",
                              self.letter_spacing, self.line_spacing, self.upper)
        if self.weld and not self.single_line:
            p = geom.polys_to_path(geom.union_all(geom.flatten(p, 0.02)))
        return textmod.follow_path(p, self.curve_path(), self.start, self.align, self.offset, self.reverse)

    def params(self):
        d = super().params()
        d.update({"curve": self.curve, "start": self.start, "offset": self.offset, "reverse": self.reverse})
        return d

    def describe(self):
        return tr("Testo su tracciato")


class ImageShape(Shape):
    """Immagine raster. Pixel conservati nel documento (doc.images), qui solo il riferimento."""

    kind = "image"

    def __init__(self, image_id=None, w=50.0, h=50.0, layer=0):
        super().__init__(layer)
        self.image_id = image_id
        self.w, self.h = float(w), float(h)
        self.brightness = 0.0  # -100..100
        self.contrast = 0.0  # -100..100
        self.gamma = 1.0
        self.source_id = None  # «Prepara foto»: immagine originale (image_id è quella preparata)
        self.photo = None  # «Prepara foto»: impostazioni usate (dict), per riaprire la finestra da dove eri

    def image_ids(self):
        return [i for i in (self.image_id, self.source_id) if i]

    def local_path(self):
        p = QPainterPath()
        p.addRect(QRectF(0, 0, self.w, self.h))
        return p

    def closed(self):
        return True

    def params(self):
        d = {"image_id": self.image_id, "w": self.w, "h": self.h, "brightness": self.brightness,
             "contrast": self.contrast, "gamma": self.gamma}
        if self.source_id:
            d["source_id"] = self.source_id
        if self.photo:
            d["photo"] = dict(self.photo)
        return d

    def describe(self):
        return tr("Immagine")


def bake_mirror(img, w, h, tf):
    """Se la trasformazione di una foto contiene uno specchio, lo sposta nei pixel.

    Sul piano non cambia nulla, ma i pixel restano nel verso in cui la foto si vede: così «Prepara foto»
    (che mostra i pixel) la presenta uguale al piano. -> (immagine, trasformazione), invariate se non serve.
    Lo specchio tolto è quello (verticale o orizzontale) che lascia la trasformazione più vicina a una foto dritta."""
    if img is None or tf.determinant() >= 0:
        return img, tf
    from PIL import Image

    fv = QTransform(1, 0, 0, -1, 0, h) * tf
    fh = QTransform(-1, 0, 0, 1, w, 0) * tf

    def straight(t):
        sx = math.hypot(t.m11(), t.m12()) or 1.0
        sy = math.hypot(t.m21(), t.m22()) or 1.0
        return t.m11() / sx + t.m22() / sy

    if straight(fh) > straight(fv) + 1e-9:
        return img.transpose(Image.FLIP_LEFT_RIGHT), fh
    return img.transpose(Image.FLIP_TOP_BOTTOM), fv


class SpecialShape(Shape):
    """Forma della galleria (freccia, cuore, ingranaggio, scudo…), parametrica."""

    kind = "special"

    def __init__(self, form="arrow", w=20.0, h=20.0, param=None, layer=1):
        super().__init__(layer)
        from . import shapes_lib

        self.form = form if form in shapes_lib.SHAPES else "arrow"
        self.w, self.h = float(w), float(h)
        self.param = float(shapes_lib.default_param(self.form) if param is None else param)

    def local_path(self):
        from . import shapes_lib

        return shapes_lib.make(self.form, self.w, self.h, self.param)

    def closed(self):
        from . import shapes_lib

        return self.form not in shapes_lib.OPEN_SHAPES

    def params(self):
        return {"form": self.form, "w": self.w, "h": self.h, "param": self.param}

    def describe(self):
        from . import shapes_lib

        return shapes_lib.SHAPES.get(self.form, ("Forma",))[0]


class CodeShape(Shape):
    """Codice QR o a barre, parametrico. I dati possono contenere variabili ({n}, {data}, colonne CSV):
    nelle serie ogni copia ha il suo codice."""

    kind = "code"

    def __init__(self, code="qr", data="https://", w=30.0, h=0.0, ecc="M", quiet=2, invert=False, text=True,
                 layer=1, var_offset=0):
        super().__init__(layer)
        self.code, self.data = code, data
        self.w, self.h = float(w), float(h)
        self.ecc, self.quiet = ecc, int(quiet)
        self.invert, self.text = bool(invert), bool(text)
        self.var_offset = int(var_offset)
        self.error = ""

    @property
    def variable(self):
        return variables.has_vars(self.data)

    def shown_data(self):
        return variables.expand(self.data, self.var_offset) if self.variable else self.data

    def local_path(self):
        from . import codes

        try:
            p = codes.code_path(self.code, self.shown_data(), self.w, self.h or None, self.ecc, self.quiet,
                                self.invert, self.text)
            self.error = ""
            return p
        except codes.CodeError as exc:
            self.error = str(exc)
            p = QPainterPath()  # segnaposto visibile: un riquadro barrato
            side = max(self.w, 5.0)
            hh = side if self.code == "qr" else max(self.h, 8.0)
            p.addRect(0, 0, side, hh)
            p.moveTo(0, 0)
            p.lineTo(side, hh)
            return p

    def closed(self):
        return True

    def params(self):
        return {"code": self.code, "data": self.data, "w": self.w, "h": self.h, "ecc": self.ecc, "quiet": self.quiet,
                "invert": self.invert, "text": self.text, "var_offset": self.var_offset}

    def describe(self):
        from . import codes

        return tr("Codice {0}", codes.KINDS.get(self.code, ("?",))[0])


class GroupShape(Shape):
    kind = "group"

    def __init__(self, children=None, layer=1):
        super().__init__(layer)
        self.children = list(children or [])

    def local_path(self):
        p = QPainterPath()
        for c in self.children:
            p.addPath(c.path())
        return p

    def invalidate(self):
        super().invalidate()

    def leaves(self, tf=None):
        full = self.tf if tf is None else self.tf * tf
        for c in self.children:
            yield from c.leaves(full)

    def params(self):
        return {"children": [c.to_dict() for c in self.children]}

    def describe(self):
        return f"Gruppo ({len(self.children)})"


_KINDS = {c.kind: c for c in (RectShape, EllipseShape, PolygonShape, PathShape, TextShape, ImageShape, GroupShape,
                               SpecialShape, CodeShape, TextPathShape)}


def shape_from_dict(d, images=None):
    kind = d["kind"]
    p = d.get("p", {})
    if kind == "rect":
        s = RectShape(p.get("w", 10), p.get("h", 10), p.get("radius", 0), radii=p.get("radii"))
    elif kind == "ellipse":
        s = EllipseShape(p.get("w", 10), p.get("h", 10))
    elif kind == "polygon":
        s = PolygonShape(p.get("w", 10), p.get("h", 10), p.get("sides", 6), p.get("star", 0), radius=p.get("radius", 0))
    elif kind == "path":
        s = PathShape(PathShape.path_from_elements(p.get("elements", [])))
    elif kind in ("text", "textpath"):
        q = dict(p)
        cls = TextPathShape if kind == "textpath" else TextShape
        s = cls(q.pop("text", ""), q.pop("family", "Arial"), q.pop("size", 10), **q)
    elif kind == "image":
        s = ImageShape(p.get("image_id"), p.get("w", 50), p.get("h", 50))
        s.brightness = p.get("brightness", 0.0)
        s.contrast = p.get("contrast", 0.0)
        s.gamma = p.get("gamma", 1.0)
        s.source_id = p.get("source_id")
        s.photo = p.get("photo")
    elif kind == "group":
        s = GroupShape([shape_from_dict(c, images) for c in p.get("children", [])])
    elif kind == "special":
        s = SpecialShape(p.get("form", "arrow"), p.get("w", 20), p.get("h", 20), p.get("param"))
    elif kind == "code":
        s = CodeShape(**{k: v for k, v in p.items() if k in ("code", "data", "w", "h", "ecc", "quiet", "invert", "text",
                                                               "var_offset")})
    else:
        raise ValueError(tr("tipo di forma sconosciuto: {0}", kind))
    s._load_common(d)
    return s


def renew_ids(shape):
    """Id nuovi alla forma e a tutto quello che contiene, gruppi dentro i gruppi compresi: una copia non deve mai
    avere lo stesso id dell'originale (separando i gruppi due forme diverse avrebbero lo stesso id)."""
    shape.id = uuid.uuid4().hex[:12]
    for ch in getattr(shape, "children", None) or ():
        renew_ids(ch)
    return shape


# ======================================================================= documento
class Plate:
    """Un piano di lavoro del progetto: le sue forme. Macchina, piano e livelli (impostazioni di taglio) sono in
    comune a tutti i piani; ogni piano è un lavoro a sé (si incide il piano attivo)."""

    def __init__(self, shapes=None, name=""):
        self.shapes = list(shapes or [])
        self.name = name  # vuoto = nome predefinito («Piano 2»)
        self.uid = uuid.uuid4().hex[:12]


class Document:
    def __init__(self):
        self.plates = [Plate()]
        self.current = 0  # piano attivo: quello che si vede, si modifica e si incide
        self.layers = {}  # indice colore -> CutSettings
        self.images = {}  # id -> PIL.Image (modalità L o RGBA)
        self.name = tr("Senza titolo")
        self.path = None

    # ---- piani di lavoro
    @property
    def shapes(self):
        """Le forme del piano attivo (tutto il programma lavora su queste)."""
        return self.plates[self.current].shapes

    @shapes.setter
    def shapes(self, value):
        self.plates[self.current].shapes = list(value)

    @property
    def plate(self):
        return self.plates[self.current]

    def plate_name(self, i):
        return self.plates[i].name or tr("Piano {0}", i + 1)

    def plate_index(self, uid):
        return next((i for i, p in enumerate(self.plates) if p.uid == uid), None)

    def add_plate(self, name=""):
        self.plates.append(Plate(name=name))
        return len(self.plates) - 1

    def remove_plate(self, i):
        """Toglie il piano i (con le sue forme). Il primo piano rimasto prende il posto di quello attivo se serve."""
        if len(self.plates) < 2 or not 0 <= i < len(self.plates):
            return False
        del self.plates[i]
        if self.current > i or self.current >= len(self.plates):
            self.current = max(0, self.current - 1)
        return True

    def all_shapes(self):
        return [s for p in self.plates for s in p.shapes]

    def other_shapes(self):
        """Le forme degli altri piani (si vedono in grigio come riferimento)."""
        return [s for i, p in enumerate(self.plates) if i != self.current for s in p.shapes]

    def used_layer_indices(self):
        """Livelli usati in qualsiasi piano (i livelli sono in comune: un livello «libero» non deve esserlo solo
        nel piano attivo)."""
        return {leaf.layer for s in self.all_shapes() for leaf, _ in s.leaves()}

    # ---- livelli
    def layer(self, index):
        if index not in self.layers:
            self.layers[index] = default_layer(index)
        return self.layers[index]

    def used_layers(self):
        used = sorted({leaf.layer for s in self.shapes if not s.hidden for leaf, _ in s.leaves()})
        for i in used:
            self.layer(i)
        return [self.layers[i] for i in sorted(used, key=lambda i: (self.layers[i].priority, i))]

    # ---- foto e disegni su livelli separati
    def keep_photos_apart(self, batch, tool_layer=30):
        """Foto e disegni (testi, forme) non possono stare sullo stesso livello: un livello in modalità Immagine
        incide solo le foto, gli altri solo i disegni, e il resto verrebbe saltato (un portachiavi con foto e
        scritta usciva con una sola delle due). Le forme di `batch` (appena aggiunte o spostate) che finirebbero
        insieme all'altro tipo vengono messe su un livello adatto. Chi resta: sul livello in modalità Immagine le
        foto, sugli altri i disegni. -> [(foglia, livello di prima, livello nuovo)]."""
        ids = {id(leaf) for s in batch for leaf, _ in s.leaves()}
        others = [leaf for s in self.all_shapes() for leaf, _ in s.leaves() if id(leaf) not in ids]
        mine = [leaf for s in batch for leaf, _ in s.leaves()]
        used = {leaf.layer for leaf in others} | {leaf.layer for leaf in mine}

        def kinds(index):
            imgs = any(isinstance(l, ImageShape) and l.layer == index for l in others)
            vecs = any(not isinstance(l, ImageShape) and l.layer == index for l in others)
            return imgs, vecs

        def free():
            for i in range(tool_layer):
                if i not in used:
                    used.add(i)
                    return i
            return None

        def new_layer():
            """Sempre un livello libero, con le impostazioni predefinite: mai uno già usato (potrebbe essere un
            taglio a piena potenza, o un livello che non esce), così niente viene inciso con impostazioni altrui."""
            i = free()
            if i is not None:
                self.layers[i] = default_layer(i)
            return i

        moved = []
        for index in sorted({leaf.layer for leaf in mine}):
            if index == tool_layer:
                continue
            imgs = [l for l in mine if l.layer == index and isinstance(l, ImageShape)]
            vecs = [l for l in mine if l.layer == index and not isinstance(l, ImageShape)]
            o_img, o_vec = kinds(index)
            cs = self.layer(index)
            if imgs and not vecs and not o_vec:
                cs.mode = "image"  # solo foto: il livello diventa (o resta) Immagine
                continue
            if vecs and not imgs and not o_img:
                if cs.mode == "image":  # livello Immagine rimasto senza foto: torna come gli altri
                    cs.mode = default_layer(index).mode if default_layer(index).mode != "image" else "line"
                continue
            # sul livello Immagine restano le foto (i disegni vanno su un livello nuovo); sugli altri i disegni
            group = vecs if cs.mode == "image" else imgs
            if not group:
                continue
            target = new_layer()
            if target is None:
                continue  # nessun livello libero: resta com'è (l'avviso del lavoro lo dirà)
            for leaf in group:
                leaf.layer = target
                leaf.invalidate()
                moved.append((leaf, index, target))
            if group is imgs:
                self.layer(target).mode = "image"
        for s in batch:  # il gruppo prende il livello del primo figlio, come quando si crea
            if isinstance(s, GroupShape) and s.children:
                s.layer = s.children[0].layer
        return moved

    # ---- forme
    def add(self, shape):
        self.shapes.append(shape)
        self.layer(shape.layer)
        return shape

    def remove(self, shapes):
        ids = {s.id for s in shapes}
        self.shapes = [s for s in self.shapes if s.id not in ids]

    def find(self, sid):
        for s in self.shapes:
            if s.id == sid:
                return s
        return None

    def bounds(self, shapes=None):
        shapes = self.shapes if shapes is None else shapes
        r = QRectF()
        for s in shapes:
            r = r.united(s.bounds()) if not r.isNull() else s.bounds()
        return r

    # ---- istantanee (annulla/ripeti)
    def snapshot(self):
        """Forme del piano attivo e livelli (che sono di tutti i piani)."""
        return {"shapes": [s.to_dict() for s in self.shapes],
                "layers": {str(k): v.to_dict() for k, v in self.layers.items()},
                "plate": self.plate.uid}

    def _plate_of(self, snap):
        i = self.plate_index(snap.get("plate"))
        return self.plates[self.current if i is None else i]

    def restore(self, snap):
        self._plate_of(snap).shapes = [shape_from_dict(d, self.images) for d in snap["shapes"]]
        self.layers = {int(k): CutSettings.from_dict(v) for k, v in snap["layers"].items()}

    def restore_step(self, target, other, skip=()):
        """Annulla/ripeti un passo: target è lo stato da rimettere, other quello da cui si parte. Le forme del suo
        piano tornano come in target; dei livelli cambiano solo quelli che il passo aveva cambiato (un livello
        modificato dopo, lavorando su un altro piano, resta com'è; quelli in skip non si toccano). -> livelli
        lasciati com'erano. Un passo «sposta sull'altro piano» toglie o
        rimette le forme anche nel piano di arrivo."""
        self._plate_of(target).shapes = [shape_from_dict(d, self.images) for d in target["shapes"]]
        lt, lo = target["layers"], other["layers"]
        for snap, put in ((other, False), (target, True)):
            mv = snap.get("moved")
            if not mv:
                continue
            ids = {d["id"] for d in mv["shapes"]}
            i = self.plate_index(mv["plate"])
            if i is not None:
                dest = self.plates[i]
                pos = {s.id: k for k, s in enumerate(dest.shapes) if s.id in ids}
                if not put and pos:
                    mv["_pos"] = pos  # dove stavano: ripetendo tornano lì (conta l'ordine di disegno e di taglio)
                    # e come erano diventate là (spostate, ruotate…): ripetendo tornano così
                    mv["_cur"] = [s.to_dict() for s in dest.shapes if s.id in ids]
                dest.shapes = [s for s in dest.shapes if s.id not in ids]
            else:  # piano di arrivo eliminato nel frattempo: le forme restano sul piano di partenza, non si perdono
                dest = self._plate_of(target)
            if put:
                here = {s.id for s in dest.shapes}
                src = mv.get("_cur") if i is not None and mv.get("_cur") else mv["shapes"]
                new = [shape_from_dict(d, self.images) for d in src if d["id"] not in here]
                where = mv.get("_pos", {}) if i is not None else {}
                for sh in sorted(new, key=lambda sh: where.get(sh.id, 1 << 30)):
                    dest.shapes.insert(min(where.get(sh.id, len(dest.shapes)), len(dest.shapes)), sh)
        used = None
        kept = set()
        for k in set(lt) | set(lo):
            if lt.get(k) == lo.get(k):
                continue
            now = self.layers.get(int(k))
            if k in skip or (now.to_dict() if now is not None else None) != lo.get(k):
                kept.add(k)  # cambiato dopo, lavorando su un altro piano: vale l'ultima modifica
                continue
            if k in lt:
                self.layers[int(k)] = CutSettings.from_dict(lt[k])
            else:  # livello nato con il passo: si toglie solo se nessun piano lo usa (i livelli sono di tutti)
                used = self.used_layer_indices() if used is None else used
                if int(k) not in used:
                    self.layers.pop(int(k), None)
        # mai la stessa forma su due piani: se una forma ripresa dalla cronologia vive già su un altro piano (vi è
        # stata spostata e il piano di passaggio è stato eliminato), vale quella dell'altro piano
        here = self._plate_of(target)
        elsewhere = set()
        for p in self.plates:
            if p is not here:
                elsewhere.update(leaf.id for sh in p.shapes for leaf, _ in sh.leaves())
                elsewhere.update(sh.id for sh in p.shapes)
        if elsewhere:
            here.shapes = [sh for sh in here.shapes
                           if sh.id not in elsewhere and not any(leaf.id in elsewhere for leaf, _ in sh.leaves())]
        for p in self.plates:  # ogni livello usato ha le sue impostazioni (anche se un altro piano lo aveva tolto)
            for sh in p.shapes:
                for leaf, _ in sh.leaves():
                    if leaf.layer not in self.layers:
                        d = lt.get(str(leaf.layer))
                        self.layers[leaf.layer] = CutSettings.from_dict(d) if d else default_layer(leaf.layer)
        return kept

    # ---- file
    def save(self, path):
        # "shapes" è il primo piano: le versioni precedenti di FreeLaserCut aprono quello; gli altri piani sono in
        # "plates" (il primo lì ha solo il nome)
        meta = {"format": "freelasercut", "version": FORMAT_VERSION, "name": self.name,
                "shapes": [s.to_dict() for s in self.plates[0].shapes],
                "layers": {str(k): v.to_dict() for k, v in self.layers.items()},
                "variables": variables.to_dict()}
        if len(self.plates) > 1 or self.plates[0].name:
            meta["plates"] = [{"name": p.name, **({"shapes": [s.to_dict() for s in p.shapes]} if i else {})}
                              for i, p in enumerate(self.plates)]
            meta["current"] = self.current
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("project.json", json.dumps(meta, indent=1))
            used = {i for s in self.all_shapes() for leaf, _ in s.leaves() if isinstance(leaf, ImageShape)
                    for i in leaf.image_ids()}
            for iid in used:
                img = self.images.get(iid)
                if img is None:
                    continue
                buf = io.BytesIO()
                img.save(buf, "PNG")
                z.writestr(f"images/{iid}.png", buf.getvalue())
        self.path = path

    @classmethod
    def load(cls, path):
        from PIL import Image

        doc = cls()
        with zipfile.ZipFile(path) as z:
            meta = json.loads(z.read("project.json"))
            for name in z.namelist():
                if name.startswith("images/") and name.endswith(".png"):
                    iid = name[7:-4]
                    doc.images[iid] = Image.open(io.BytesIO(z.read(name))).copy()
        doc.name = meta.get("name", "Progetto")
        variables.from_dict(meta.get("variables"))
        doc.restore({"shapes": meta.get("shapes", []), "layers": meta.get("layers", {})})
        plates = meta.get("plates")
        if isinstance(plates, list) and plates:
            doc.plates[0].name = str(plates[0].get("name") or "")
            for p in plates[1:]:
                doc.plates.append(Plate([shape_from_dict(d, doc.images) for d in p.get("shapes", [])],
                                        str(p.get("name") or "")))
            cur = meta.get("current", 0)
            doc.current = cur if isinstance(cur, int) and 0 <= cur < len(doc.plates) else 0
        doc.path = path
        return doc
