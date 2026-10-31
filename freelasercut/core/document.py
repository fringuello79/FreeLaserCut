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
        return cls(**known)


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
        self._cache = None

    # geometria
    def local_path(self) -> QPainterPath:  # pragma: no cover - sottoclassi
        return QPainterPath()

    def invalidate(self):
        self._cache = None

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
        return {"kind": self.kind, "id": self.id, "layer": self.layer, "tf": geom.transform_to_list(self.tf),
                "locked": self.locked, "hidden": self.hidden, "p": self.params()}

    def _load_common(self, d):
        self.id = d.get("id", self.id)
        self.layer = d.get("layer", 1)
        self.tf = geom.transform_from_list(d["tf"]) if "tf" in d else QTransform()
        self.locked = d.get("locked", False)
        self.hidden = d.get("hidden", False)

    def clone(self, new_id=True):
        c = shape_from_dict(self.to_dict(), getattr(self, "_doc_images", None))
        if new_id:
            c.id = uuid.uuid4().hex[:12]
        return c

    def describe(self):
        return self.kind


class RectShape(Shape):
    kind = "rect"

    def __init__(self, w=10.0, h=10.0, radius=0.0, layer=1):
        super().__init__(layer)
        self.w, self.h, self.radius = float(w), float(h), float(radius)

    def local_path(self):
        p = QPainterPath()
        r = max(0.0, min(self.radius, abs(self.w) / 2, abs(self.h) / 2))
        if r > 0:
            p.addRoundedRect(QRectF(0, 0, self.w, self.h), r, r)
        else:
            p.addRect(QRectF(0, 0, self.w, self.h))
        return p

    def params(self):
        return {"w": self.w, "h": self.h, "radius": self.radius}

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

    def __init__(self, w=10.0, h=10.0, sides=6, star=0.0, layer=1):
        super().__init__(layer)
        self.w, self.h = float(w), float(h)
        self.sides = int(sides)
        self.star = float(star)  # 0 = poligono; 0..0.95 = rientranza della stella

    def local_path(self):
        n = max(3, self.sides)
        rx, ry = self.w / 2, self.h / 2
        pts = []
        count = n * 2 if self.star > 0 else n
        for i in range(count):
            a = math.pi / 2 + 2 * math.pi * i / count
            k = (1 - self.star) if (self.star > 0 and i % 2 == 1) else 1.0
            pts.append((rx + rx * k * math.cos(a), ry + ry * k * math.sin(a)))
        p = QPainterPath()
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        p.closeSubpath()
        return p

    def params(self):
        return {"w": self.w, "h": self.h, "sides": self.sides, "star": self.star}

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

    def local_path(self):
        p = QPainterPath()
        p.addRect(QRectF(0, 0, self.w, self.h))
        return p

    def closed(self):
        return True

    def params(self):
        return {"image_id": self.image_id, "w": self.w, "h": self.h, "brightness": self.brightness,
                "contrast": self.contrast, "gamma": self.gamma}

    def describe(self):
        return tr("Immagine")


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
                               SpecialShape)}


def shape_from_dict(d, images=None):
    kind = d["kind"]
    p = d.get("p", {})
    if kind == "rect":
        s = RectShape(p.get("w", 10), p.get("h", 10), p.get("radius", 0))
    elif kind == "ellipse":
        s = EllipseShape(p.get("w", 10), p.get("h", 10))
    elif kind == "polygon":
        s = PolygonShape(p.get("w", 10), p.get("h", 10), p.get("sides", 6), p.get("star", 0))
    elif kind == "path":
        s = PathShape(PathShape.path_from_elements(p.get("elements", [])))
    elif kind == "text":
        q = dict(p)
        s = TextShape(q.pop("text", ""), q.pop("family", "Arial"), q.pop("size", 10), **q)
    elif kind == "image":
        s = ImageShape(p.get("image_id"), p.get("w", 50), p.get("h", 50))
        s.brightness = p.get("brightness", 0.0)
        s.contrast = p.get("contrast", 0.0)
        s.gamma = p.get("gamma", 1.0)
    elif kind == "group":
        s = GroupShape([shape_from_dict(c, images) for c in p.get("children", [])])
    elif kind == "special":
        s = SpecialShape(p.get("form", "arrow"), p.get("w", 20), p.get("h", 20), p.get("param"))
    else:
        raise ValueError(tr("tipo di forma sconosciuto: {0}", kind))
    s._load_common(d)
    return s


# ======================================================================= documento
class Document:
    def __init__(self):
        self.shapes = []
        self.layers = {}  # indice colore -> CutSettings
        self.images = {}  # id -> PIL.Image (modalità L o RGBA)
        self.name = tr("Senza titolo")
        self.path = None

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
        return {"shapes": [s.to_dict() for s in self.shapes],
                "layers": {str(k): v.to_dict() for k, v in self.layers.items()}}

    def restore(self, snap):
        self.shapes = [shape_from_dict(d, self.images) for d in snap["shapes"]]
        self.layers = {int(k): CutSettings.from_dict(v) for k, v in snap["layers"].items()}

    # ---- file
    def save(self, path):
        meta = {"format": "freelasercut", "version": FORMAT_VERSION, "name": self.name, **self.snapshot(),
                "variables": variables.to_dict()}
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("project.json", json.dumps(meta, indent=1))
            used = {leaf.image_id for s in self.shapes for leaf, _ in s.leaves() if isinstance(leaf, ImageShape)}
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
        doc.restore(meta)
        doc.path = path
        return doc
