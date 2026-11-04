# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Tela di disegno di FreeLaserCut: il piano di lavoro con le forme, gli strumenti e gli aiuti visivi.

Sistemi di coordinate:
  - piano (mm, Y su): quello del documento e della macchina;
  - scena Qt: (x, -y), le forme stanno sotto un nodo "mondo" ribaltato;
  - vista (pixel): per maniglie, righelli, aggancio e tutto ciò che ha misura fissa a schermo.
"""
import math

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from .. import gcode_preview
from ..core import geom, imaging
from ..core.document import LAYER_COLORS, GroupShape, ImageShape, TextShape
from ..theme import C
from . import style
from freelasercut.i18n import tr  # noqa: E402

BURN = "#FF8A3D"
RULER = 20  # px
TOOL_LAYER_COLOR = "#8A9BBE"


def _default_family():
    from PySide6.QtGui import QFontDatabase

    fams = set(QFontDatabase.families())
    for f in ("Arial", tr("Segoe UI"), "Inter", tr("DejaVu Sans"), tr("Liberation Sans")):
        if f in fams:
            return f
    return tr("Sans Serif")


BED_LIGHT = {"out": "#C9CED6", "bed": "#FFFFFF", "grid": "#ECEEF2", "grid_major": "#D3D8E0", "edge": "#5B6578"}
BED_DARK = {"out": C["bg"], "bed": C["bed"], "grid": C["grid"], "grid_major": C["grid_major"], "edge": C["grid_major"]}


def layer_color(i):
    return TOOL_LAYER_COLOR if i >= len(LAYER_COLORS) else LAYER_COLORS[i]


def cpen(color, width=1.0, style_=Qt.SolidLine, alpha=255):
    c = QColor(color)
    c.setAlpha(alpha)
    p = QPen(c, width, style_)
    p.setCosmetic(True)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


# ======================================================================= elementi grafici
class ShapeItem(QGraphicsItem):
    """Disegna una forma di primo livello (gruppi compresi) nel sistema del piano."""

    def __init__(self, canvas, shape):
        super().__init__()
        self.canvas = canvas
        self.fb_shape = shape  # NON "shape": è un metodo virtuale di QGraphicsItem che Qt chiama da solo
        self._path = None
        self._bounds = QRectF()
        self._leaves = None
        self.refresh()

    def refresh(self):
        self.prepareGeometryChange()
        self._path = self.fb_shape.path()
        self._bounds = self._path.boundingRect().adjusted(-1, -1, 1, 1)
        self._leaves = None  # i percorsi si ricalcolano al prossimo disegno
        self.update()

    def _leaf_paths(self):
        """(foglia, trasformazione, percorso nel piano) calcolati una volta per modifica: ridisegnare il piano
        (a ogni movimento del mouse) non rigenera più i contorni, per esempio quelli dei testi."""
        if self._leaves is None:
            self._leaves = [(leaf, tf, tf.map(leaf.local_path())) for leaf, tf in self.fb_shape.leaves()]
        return self._leaves

    def boundingRect(self):
        return self._bounds

    def shape(self):  # area sensibile per Qt (tooltip, trascinamenti, collisioni)
        from PySide6.QtGui import QPainterPath

        p = QPainterPath()
        p.addRect(self._bounds)
        return p

    def paint(self, painter, option, widget=None):
        cv = self.canvas
        doc = cv.editor.doc
        for leaf, tf, mapped in self._leaf_paths():
            if leaf.hidden:
                continue
            col = layer_color(leaf.layer)
            cs = doc.layers.get(leaf.layer)
            if cs is not None and not cs.show:
                continue
            if isinstance(leaf, ImageShape):
                img = cv.image_preview(leaf, cs)
                if img is not None:
                    painter.save()
                    flip = QTransform(1, 0, 0, -1, 0, leaf.h)
                    painter.setTransform(flip * tf * painter.transform())
                    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                    painter.drawImage(QRectF(0, 0, leaf.w, leaf.h), img)
                    painter.restore()
                painter.setPen(cpen(col, 1, Qt.DashLine, 160))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(mapped)
                continue
            path = mapped
            fill = cv.filled_view and cs is not None and cs.mode in ("fill", "offset_fill") and leaf.layer < 30
            if fill:
                fc = QColor(col)
                fc.setAlpha(70 if cs.output else 30)
                painter.setBrush(fc)
                if path.fillRule() != Qt.OddEvenFill:
                    path.setFillRule(Qt.OddEvenFill)
            else:
                painter.setBrush(Qt.NoBrush)
            if leaf.layer >= 30:
                painter.setPen(cpen(col, 1, Qt.DashLine, 200))
            else:
                alpha = 255 if (cs is None or cs.output) else 110
                painter.setPen(cpen(col, 1.25, Qt.SolidLine, alpha))
            painter.drawPath(path)


class HeadItem(QGraphicsItem):
    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(1000)
        self.active = False
        self.label = ""  # «testa del laser», solo con i nomi sotto i comandi

    def boundingRect(self):
        return QRectF(-70, -18, 140, 52)

    def set_label(self, text):
        if text != self.label:
            self.label = text
            self.update()

    def set_active(self, a):
        if a != self.active:
            self.active = a
            self.update()

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(BURN) if self.active else QColor(C["accent_hi"])
        glow = QColor(color)
        glow.setAlpha(70)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(0, 0), 14, 14)
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), 7, 7)
        for a, b in (((-16, 0), (-10, 0)), ((10, 0), (16, 0)), ((0, -16), (0, -10)), ((0, 10), (0, 16))):
            p.drawLine(QPointF(*a), QPointF(*b))
        p.setBrush(color)
        p.drawEllipse(QPointF(0, 0), 2, 2)
        if self.label:
            f = style.ui_font(7.5)
            f.setBold(True)
            p.setFont(f)
            r = QRectF(-70, 17, 140, 14)
            p.setPen(QColor(0, 0, 0, 150))
            p.drawText(r.translated(1, 1), Qt.AlignHCenter | Qt.AlignTop, self.label)
            p.setPen(color)
            p.drawText(r, Qt.AlignHCenter | Qt.AlignTop, self.label)


ANCHOR = "#FF3DB4"  # punto di partenza del lavoro: colore diverso dalla testa (che si muove con il laser)


class AnchorItem(QGraphicsItem):
    """Punto di partenza del lavoro: il punto scelto con i 9 pallini, nel posto in cui finirà sul piano.
    Rombo magenta con la scritta, per non confonderlo con la testa del laser (cerchio con il mirino)."""

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(990)
        self.label = ""
        self.show_label = False  # la scritta accanto al rombo solo con i nomi sotto i comandi

    def boundingRect(self):
        return QRectF(-14, -14, 190, 28)

    def set_label(self, text):
        self.label = text
        self.update()

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(ANCHOR)
        p.setPen(QPen(col, 2))
        p.setBrush(Qt.NoBrush)
        diamond = QPolygonF([QPointF(0, -9), QPointF(9, 0), QPointF(0, 9), QPointF(-9, 0)])
        p.drawPolygon(diamond)
        p.drawLine(QPointF(-4, 0), QPointF(4, 0))
        p.drawLine(QPointF(0, -4), QPointF(0, 4))
        if self.label and self.show_label:
            f = style.ui_font(7.5)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(0, 0, 0, 150))
            p.drawText(QPointF(14, 4), self.label)
            p.setPen(col)
            p.drawText(QPointF(13, 3), self.label)


class HintItem(QGraphicsItem):
    """Spiegazione di un segno del piano (testa, punto di partenza) quando ci passa sopra il mouse:
    riquadro semitrasparente, come i suggerimenti dei comandi. Coordinate in pixel dello schermo."""

    WIDTH = 270

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(1100)
        self.title, self.body, self.color = "", "", QColor(C["accent_hi"])
        self._rect = QRectF(0, 0, self.WIDTH, 40)

    def set_text(self, title, body, color):
        from PySide6.QtGui import QFontMetrics

        self.prepareGeometryChange()
        self.title, self.body, self.color = title, body, QColor(color)
        ft, fb = self._fonts()
        inner = self.WIDTH - 20
        ht = QFontMetrics(ft).boundingRect(0, 0, inner, 400, Qt.TextWordWrap, title).height()
        hb = QFontMetrics(fb).boundingRect(0, 0, inner, 600, Qt.TextWordWrap, body).height()
        self._th = ht
        self._rect = QRectF(0, 0, self.WIDTH, ht + hb + 22)
        self.update()

    @staticmethod
    def _fonts():
        ft = style.ui_font(8.5)
        ft.setBold(True)
        return ft, style.ui_font(8)

    def boundingRect(self):
        return self._rect.adjusted(-1, -1, 1, 1)

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 45), 1))
        p.setBrush(QColor(14, 18, 28, 196))
        p.drawRoundedRect(self._rect, 7, 7)
        ft, fb = self._fonts()
        inner = QRectF(10, 8, self.WIDTH - 20, self._th)
        p.setFont(ft)
        p.setPen(self.color)
        p.drawText(inner, Qt.TextWordWrap, self.title)
        p.setFont(fb)
        p.setPen(QColor(236, 240, 248))
        p.drawText(QRectF(10, 12 + self._th, self.WIDTH - 20, self._rect.height() - self._th - 14), Qt.TextWordWrap,
                   self.body)


# ======================================================================= tela
class Canvas(QGraphicsView):
    cursor_moved = Signal(float, float)
    goto_requested = Signal(float, float)  # coordinate piano
    jog_requested = Signal(float, float)  # frecce senza selezione: jog della testa
    edit_text = Signal(object)
    tool_changed = Signal(str)
    status = Signal(str)
    zoom_changed = Signal(float)

    def __init__(self, editor, bed=(450.0, 440.0), parent=None):
        super().__init__(parent)
        self.editor = editor
        self.bed_x, self.bed_y = bed
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)
        self.scene().setSceneRect(QRectF(-5000, -5000, 10000, 10000))
        self.world = QGraphicsPathItem()
        self.world.setPen(Qt.NoPen)
        self.world.setTransform(QTransform.fromScale(1, -1))
        self.scene().addItem(self.world)
        self.items_by_id = {}
        # opzioni di vista
        self.filled_view = True
        self.show_grid = True
        self.light_bed = True  # piano chiaro (come un foglio): i colori dei livelli si leggono meglio
        self.snap_grid = False
        self.snap_objects = True
        self.dither_preview = False
        self.grid_step = 10.0
        # elementi macchina / camera / anteprima (coordinate scena)
        self._cam_item = None
        self._head = HeadItem()
        self.scene().addItem(self._head)
        self._head.setVisible(False)
        self._anchor = AnchorItem()
        self.scene().addItem(self._anchor)
        self._anchor.setVisible(False)
        # scritte e spiegazioni dei segni: la finestra decide (nomi sotto i comandi, modalità esperto, lavoro in corso)
        self.marker_labels = False
        self.hints_allowed = lambda: True
        self._hint = HintItem()
        self.scene().addItem(self._hint)
        self._hint.setVisible(False)
        self._hint_for = None
        self._trail_path = QPainterPath()
        self._trail_item = QGraphicsPathItem()
        self._trail_item.setPen(cpen(BURN, 2.2))
        self._trail_item.setZValue(900)
        self.scene().addItem(self._trail_item)
        self._last_burn = None
        self._preview_items = []
        self._img_cache = {}
        # sfondo (piano + griglia) e righelli: cambiano solo con zoom, spostamento, dimensioni e opzioni di vista,
        # non quando si muove il mouse; si disegnano una volta e poi si copiano (molto più veloce sui PC lenti)
        self._bg_cache = (None, None, None)  # (chiave, pixmap, passo griglia)
        self._ruler_cache = (None, None)
        # stato interazione
        self.cursor_bed = QPointF(0, 0)
        self.snap_hint = None  # (QPointF piano, etichetta)
        self._snap_cache = None
        self._pan = None
        self._space = False
        self._user_zoomed = False
        from .tools import make_tools

        self.tools = make_tools(self)
        self.tool = self.tools["select"]
        self.tool_options = {"sides": 6, "star": False, "star_points": 5, "star_ratio": 0.5, "corner_radius": 0.0,
                             "special": "arrow", "special_param": {}}
        self.text_defaults = {"family": _default_family(), "size": 10.0, "bold": False, "italic": False, "align": "left",
                              "letter_spacing": 0.0, "line_spacing": 1.0, "upper": False, "weld": False, "arc": 0.0}
        editor.changed.connect(self.sync)
        editor.live.connect(self.sync)
        editor.selection_changed.connect(self.viewport().update)
        self.sync()
        QTimer.singleShot(0, self.fit_bed)

    # ================================================================ coordinate
    def scale_px(self):
        return self.transform().m11()

    def to_bed(self, view_pt):
        s = self.mapToScene(view_pt.toPoint() if hasattr(view_pt, "toPoint") else view_pt)
        return QPointF(s.x(), -s.y())

    def to_view(self, bed_pt):
        return self.mapFromScene(QPointF(bed_pt.x(), -bed_pt.y())).toPointF()

    def bed_to_view_tf(self):
        return QTransform.fromScale(1, -1) * self.viewportTransform()

    def px(self, n):
        """n pixel in mm alla zoom attuale."""
        return n / max(self.scale_px(), 1e-9)

    # ================================================================ sincronizzazione
    def set_bed(self, bx, by):
        self.bed_x, self.bed_y = float(bx), float(by)
        self.viewport().update()

    def sync(self):
        doc = self.editor.doc
        alive = set()
        for z, s in enumerate(doc.shapes):
            alive.add(s.id)
            it = self.items_by_id.get(s.id)
            if it is None or it.fb_shape is not s:
                if it is not None:
                    self.scene().removeItem(it)
                it = ShapeItem(self, s)
                it.setParentItem(self.world)
                self.items_by_id[s.id] = it
            else:
                it.refresh()
            it.setZValue(z)
        for sid in list(self.items_by_id):
            if sid not in alive:
                self.scene().removeItem(self.items_by_id.pop(sid))
        self._snap_cache = None
        self.viewport().update()

    def refresh_live(self, shapes):
        """Aggiornamento veloce durante i trascinamenti."""
        for s in shapes:
            it = self.items_by_id.get(s.id)
            if it is not None:
                it.refresh()
        self.viewport().update()

    # ================================================================ immagini
    def image_preview(self, leaf, cs):
        img = self.editor.doc.images.get(leaf.image_id)
        if img is None:
            return None
        dith = self.dither_preview and cs is not None and cs.mode == "image"
        key = (leaf.image_id, round(leaf.brightness, 2), round(leaf.contrast, 2), round(leaf.gamma, 3),
               bool(cs and cs.negative), dith, cs.dither if dith else None, cs.dpi if dith else None,
               round(leaf.w, 2) if dith else None, round(leaf.h, 2) if dith else None)
        q = self._img_cache.get(key)
        if q is not None:
            return q
        dark = imaging.to_dark(img)
        if dith:
            step = 25.4 / max(cs.dpi, 10)
            nx = max(2, min(int(leaf.w / step), 2400))
            ny = max(2, min(int(leaf.h / step), 2400))
            import cv2

            small = cv2.resize(dark, (nx, ny), interpolation=cv2.INTER_AREA)
            small = imaging.adjust(small, leaf.brightness, leaf.contrast, leaf.gamma, cs.negative)
            vals = imaging.dither(small, cs.dither, max(cs.halftone_cell / step, 2), cs.halftone_angle)
            lum = (1.0 - vals) * 255
        else:
            dark = imaging.adjust(dark, leaf.brightness, leaf.contrast, leaf.gamma, bool(cs and cs.negative))
            lum = (1.0 - dark) * 255
        arr = np.ascontiguousarray(lum.astype(np.uint8))
        h, w = arr.shape
        qi = QImage(arr.data, w, h, w, QImage.Format_Grayscale8).copy()
        if len(self._img_cache) > 24:
            self._img_cache.clear()
        self._img_cache[key] = qi
        return qi

    # ================================================================ vista
    def fit_rect(self, r, margin=40):
        if r.isNull() or r.width() <= 0 and r.height() <= 0:
            return
        il, it, ir, ib = getattr(self, "fit_insets", (0, 0, 0, 0))  # pannelli sovrapposti (interfaccia Banco)
        vw = max(self.viewport().width() - RULER - 2 * margin - il - ir, 50)
        vh = max(self.viewport().height() - RULER - 2 * margin - it - ib, 50)
        k = min(vw / max(r.width(), 1e-3), vh / max(r.height(), 1e-3))
        k = max(0.05, min(k, 400))
        self.resetTransform()
        self.scale(k, k)
        c = r.center()
        self.centerOn(QPointF(c.x(), -c.y()))
        # i righelli occupano spazio in alto a sinistra (e i pannelli del Banco ai lati): compenso
        self.translate_view(RULER / 2 + (il - ir) / 2, RULER / 2 + (it - ib) / 2)
        self.zoom_changed.emit(k)
        self.viewport().update()

    def translate_view(self, dx, dy):
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(int(h.value() - dx))
        v.setValue(int(v.value() - dy))

    def fit_bed(self):
        self._user_zoomed = False
        self.fit_rect(QRectF(0, 0, self.bed_x, self.bed_y), 30)

    def fit_selection(self):
        r = self.editor.selection_bounds()
        if not r.isNull():
            self.fit_rect(r.adjusted(-5, -5, 5, 5), 60)

    def zoom_by(self, factor, anchor_view=None):
        k = self.scale_px()
        factor = max(0.05 / k, min(factor, 400 / k))
        anchor_view = anchor_view or QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        before = self.mapToScene(anchor_view.toPoint())
        self.scale(factor, factor)
        after = self.mapToScene(anchor_view.toPoint())
        d = after - before
        self.translate_view(d.x() * self.scale_px(), d.y() * self.scale_px())
        self._user_zoomed = True
        self.zoom_changed.emit(self.scale_px())
        self.viewport().update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._user_zoomed:
            self.fit_bed()

    # ================================================================ strumenti
    def set_tool(self, name):
        if name not in self.tools:
            return
        if self.tool is not None:
            self.tool.deactivate()
        self.tool = self.tools[name]
        self.tool.activate()
        self.viewport().setCursor(self.tool.cursor())
        self.tool_changed.emit(name)
        self.viewport().update()

    # ================================================================ aggancio
    def _snap_points(self, exclude_ids):
        if self._snap_cache is not None and self._snap_cache[0] == exclude_ids:
            return self._snap_cache[1], self._snap_cache[2]
        pts, kinds = [], []
        for s in self.editor.doc.shapes:
            if s.id in exclude_ids or s.hidden:
                continue
            b = s.bounds()
            for x, y, k in ((b.left(), b.top(), "angolo"), (b.right(), b.top(), "angolo"), (b.left(), b.bottom(), "angolo"),
                            (b.right(), b.bottom(), "angolo"), (b.center().x(), b.center().y(), "centro"),
                            (b.center().x(), b.top(), "metà"), (b.center().x(), b.bottom(), "metà"),
                            (b.left(), b.center().y(), "metà"), (b.right(), b.center().y(), "metà")):
                pts.append((x, y))
                kinds.append(k)
            if isinstance(s, ImageShape):
                continue
            path = s.path()
            n = path.elementCount()
            if n > 4000:
                continue
            for i in range(n):
                e = path.elementAt(i)
                if e.type in (QPainterPath.ElementType.MoveToElement, QPainterPath.ElementType.LineToElement):
                    pts.append((e.x, e.y))
                    kinds.append("nodo")
                elif e.type == QPainterPath.ElementType.CurveToElement and i + 2 < n:
                    e3 = path.elementAt(i + 2)
                    pts.append((e3.x, e3.y))
                    kinds.append("nodo")
        arr = np.array(pts, float) if pts else np.zeros((0, 2))
        self._snap_cache = (exclude_ids, arr, kinds)
        return arr, kinds

    def snap(self, bed_pt, exclude_ids=frozenset(), force_grid=False):
        """Aggancia a nodi/centri/angoli delle altre forme (entro 9 px) o alla griglia."""
        self.snap_hint = None
        if self.snap_objects:
            arr, kinds = self._snap_points(frozenset(exclude_ids))
            if len(arr):
                d = np.hypot(arr[:, 0] - bed_pt.x(), arr[:, 1] - bed_pt.y())
                k = int(np.argmin(d))
                if d[k] <= self.px(9):
                    p = QPointF(arr[k, 0], arr[k, 1])
                    self.snap_hint = (p, kinds[k])
                    return p
        if self.snap_grid or force_grid:
            g = self.grid_step
            p = QPointF(round(bed_pt.x() / g) * g, round(bed_pt.y() / g) * g)
            self.snap_hint = (p, "griglia")
            return p
        return bed_pt

    # ================================================================ selezione a colpo
    def hit_shape(self, bed_pt, tol_px=6):
        tol = self.px(tol_px)
        doc = self.editor.doc
        for s in reversed(doc.shapes):
            if s.hidden:
                continue
            cs = doc.layers.get(s.layer)
            if cs is not None and not cs.show and not isinstance(s, GroupShape):
                continue
            b = s.bounds().adjusted(-tol, -tol, tol, tol)
            if not b.contains(bed_pt):
                continue
            path = s.path()
            if isinstance(s, ImageShape):
                return s
            filled = self.filled_view and cs is not None and cs.mode in ("fill", "offset_fill")
            if (filled or isinstance(s, TextShape)) and path.contains(bed_pt):
                return s
            st = QPainterPathStroker()
            st.setWidth(2 * tol)
            if st.createStroke(path).contains(bed_pt):
                return s
        return None

    def shapes_in_rect(self, r, crossing):
        out = []
        for s in self.editor.doc.shapes:
            if s.hidden:
                continue
            b = s.bounds()
            if crossing:
                if b.intersects(r) or r.contains(b):
                    if r.contains(b) or s.path().intersects(r):
                        out.append(s)
            elif r.contains(b):
                out.append(s)
        return out

    # ================================================================ eventi
    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if e.modifiers() & Qt.ShiftModifier:
            self.translate_view(e.angleDelta().y() / 2, 0)
            return
        if e.modifiers() & Qt.ControlModifier and not (e.modifiers() & Qt.AltModifier):
            self.translate_view(0, e.angleDelta().y() / 2)
            return
        self.zoom_by(1.18 ** steps, e.position())

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and self._space):
            self._pan = e.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        self.setFocus()
        self.tool.press(e, self.to_bed(e.position()))
        self.viewport().update()

    def mouseMoveEvent(self, e):
        bed = self.to_bed(e.position())
        self.cursor_bed = bed
        self.cursor_moved.emit(bed.x(), bed.y())
        self._update_marker_hint(e.position() if e.buttons() == Qt.NoButton and self._pan is None else None)
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.translate_view(d.x(), d.y())
            self._user_zoomed = True
            self.viewport().update()
            return
        had_hint = self.snap_hint is not None
        self.tool.move(e, bed)
        if e.buttons() == Qt.NoButton and not had_hint and self.snap_hint is None and self.tool.static_hover():
            # il mouse passa sul piano e lo strumento non disegna nulla che lo segua (Selezione senza tasti premuti):
            # cambiano solo i segni del cursore sui righelli, quindi ridisegno solo le due strisce
            self.update_rulers()
            return
        self.viewport().update()

    def update_rulers(self):
        vp = self.viewport()
        vp.update(0, 0, vp.width(), RULER + 1)
        vp.update(0, 0, RULER + 1, vp.height())

    def mouseReleaseEvent(self, e):
        if self._pan is not None and e.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan = None
            self.viewport().setCursor(Qt.OpenHandCursor if self._space else self.tool.cursor())
            return
        self.tool.release(e, self.to_bed(e.position()))
        self.viewport().update()

    def mouseDoubleClickEvent(self, e):
        self.tool.double_click(e, self.to_bed(e.position()))
        self.viewport().update()

    def event(self, e):
        from PySide6.QtCore import QEvent

        if e.type() == QEvent.Type.ShortcutOverride and self.tool.wants_key(e):
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
            return
        if self.tool.key(e):
            self.viewport().update()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = False
            self.viewport().setCursor(self.tool.cursor())
            return
        super().keyReleaseEvent(e)

    def leaveEvent(self, e):
        self.hide_marker_hint()
        self.snap_hint = None
        self.viewport().update()
        super().leaveEvent(e)

    # trascina file sulla tela
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths and hasattr(self.window(), "import_files"):
            self.window().import_files(paths, at=self.to_bed(e.position()))
            e.acceptProposedAction()

    # ================================================================ disegno: sfondo
    def _view_key(self):
        vp = self.viewport()
        t = self.viewportTransform()
        return (t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy(), vp.width(), vp.height(), vp.devicePixelRatioF())

    def drawBackground(self, p, rect):
        vp = self.viewport()
        if p.device() is not vp:  # disegno su un'altra superficie (stampa, immagine): niente cache
            self._paint_background(p, rect)
            return
        key = self._view_key() + (self.light_bed, self.show_grid, self.snap_grid, self.bed_x, self.bed_y)
        ck, pix, step = self._bg_cache
        if ck != key or pix is None:
            dpr = vp.devicePixelRatioF()
            pix = QPixmap(max(1, round(vp.width() * dpr)), max(1, round(vp.height() * dpr)))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.transparent)
            q = QPainter(pix)
            q.setRenderHints(self.renderHints())
            q.setTransform(self.viewportTransform())
            self._paint_background(q, self.mapToScene(vp.rect()).boundingRect())
            q.end()
            self._bg_cache = (key, pix, self.grid_step)
        else:
            self.grid_step = step  # come se lo sfondo fosse stato ridisegnato (passo dell'aggancio alla griglia)
        p.save()
        p.resetTransform()
        p.drawPixmap(0, 0, pix)
        p.restore()

    def _paint_background(self, p, rect):
        pal = BED_LIGHT if self.light_bed else BED_DARK
        p.fillRect(rect, QColor(pal["out"]))
        bed = QRectF(0, -self.bed_y, self.bed_x, self.bed_y)
        p.fillRect(bed, QColor(pal["bed"]))
        if self.show_grid:
            k = self.scale_px()
            vis = rect.intersected(bed)
            # passo adattivo: linee secondarie ad almeno 7 px, principali ogni 5 o 10
            minor = next((s for s in (0.5, 1, 2, 5, 10, 20, 50, 100) if s * k >= 7), 100)
            major = minor * (5 if minor in (1, 10, 100) else 2 if minor in (5, 50) else 5)
            self.grid_step = minor if self.snap_grid else self.grid_step
            for step, col in ((minor, pal["grid"]), (major, pal["grid_major"])):
                p.setPen(cpen(col, 1))
                x = math.ceil(vis.left() / step) * step
                lines = []
                while x <= vis.right():
                    lines.append(QLineF(x, vis.top(), x, vis.bottom()))
                    x += step
                y = math.ceil(vis.top() / step) * step
                while y <= vis.bottom():
                    lines.append(QLineF(vis.left(), y, vis.right(), y))
                    y += step
                if len(lines) < 4000:
                    p.drawLines(lines)
        p.setPen(cpen(pal["edge"], 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRect(bed)
        # origine macchina
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["success"]))
        r = self.px(4)
        p.drawEllipse(QPointF(0, 0), r, r)

    # ================================================================ disegno: primo piano
    def drawForeground(self, p, rect):
        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.Antialiasing)
        tf = self.bed_to_view_tf()
        ed = self.editor
        # contorno selezione (tratteggio animato fisso)
        if ed.selection:
            p.setPen(cpen(C["accent_hi"], 1.2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            for s in ed.selection:
                it = self.items_by_id.get(s.id)
                path = it._path if it is not None and it.fb_shape is s and it._path is not None else s.path()
                p.drawPath(tf.map(path))
        self.tool.draw(p, tf)
        if self.snap_hint is not None:
            pt, label = self.snap_hint
            v = tf.map(pt)
            p.setPen(cpen("#FFD43B", 1.6))
            p.setBrush(Qt.NoBrush)
            d = 6
            p.drawPolygon([QPointF(v.x(), v.y() - d), QPointF(v.x() + d, v.y()), QPointF(v.x(), v.y() + d), QPointF(v.x() - d, v.y())])
            p.setFont(style.ui_font(8))
            p.setPen(QColor("#FFD43B"))
            p.drawText(QPointF(v.x() + 9, v.y() - 8), label)
        self._draw_rulers(p, tf)
        p.restore()

    def _draw_rulers(self, p, tf):
        W, H = self.viewport().width(), self.viewport().height()
        band = QColor(C["panel"])
        p.fillRect(QRectF(0, 0, W, RULER), band)
        p.fillRect(QRectF(0, 0, RULER, H), band)
        p.setPen(cpen(C["border"], 1))
        p.drawLine(QPointF(0, RULER), QPointF(W, RULER))
        p.drawLine(QPointF(RULER, 0), QPointF(RULER, H))
        # tacche e numeri: si calcolano solo quando cambiano zoom, spostamento o dimensioni della vista
        key = self._view_key()
        if self._ruler_cache[0] != key:
            self._ruler_cache = (key, self._ruler_scale(tf, W, H))
        minor, major, hlabels, vlabels = self._ruler_cache[1]
        p.setPen(cpen(C["grid_major"], 1))
        p.drawLines(minor)
        p.setPen(cpen(C["muted"], 1))
        p.drawLines(major)
        p.setFont(style.mono_font(7.5))
        p.setPen(QColor(C["muted"]))
        for pt, st in hlabels:
            p.drawStaticText(pt, st)
        for vy, st in vlabels:
            p.save()
            p.translate(10, vy - 3)
            p.rotate(-90)
            p.drawStaticText(QPointF(0, -self._ruler_ascent), st)
            p.restore()
        self._paint_ruler_marks(p, tf, band)

    def _ruler_scale(self, tf, W, H):
        """Tacche (secondarie, principali) e numeri dei righelli per la vista attuale."""
        from PySide6.QtGui import QFontMetricsF, QStaticText

        k = self.scale_px()
        step = next((s for s in (1, 2, 5, 10, 20, 50, 100, 200, 500) if s * k >= 50), 500)
        sub = step / (5 if step in (5, 50, 500) else 10 if step in (1, 10, 100) else 4)
        f = style.mono_font(7.5)
        self._ruler_ascent = asc = QFontMetricsF(f).ascent()
        x0 = self.to_bed(QPointF(RULER, 0)).x()
        x1 = self.to_bed(QPointF(W, 0)).x()
        y_top = self.to_bed(QPointF(0, RULER)).y()
        y_bot = self.to_bed(QPointF(0, H)).y()
        minor, major, hl, vl = [], [], [], []

        def label(v):
            st = QStaticText(f"{v:g}")
            st.prepare(QTransform(), f)
            return st
        # orizzontale
        v = math.floor(x0 / sub) * sub
        while v <= x1:
            vx = tf.map(QPointF(v, 0)).x()
            big = abs(v / step - round(v / step)) < 1e-6
            (major if big else minor).append(QLineF(vx, RULER - (9 if big else 4), vx, RULER))
            if big:
                hl.append((QPointF(vx + 3, 10 - asc), label(v)))  # drawText usa la linea di base, drawStaticText l'angolo
            v += sub
        # verticale
        v = math.floor(y_bot / sub) * sub
        while v <= y_top:
            vy = tf.map(QPointF(0, v)).y()
            big = abs(v / step - round(v / step)) < 1e-6
            (major if big else minor).append(QLineF(RULER - (9 if big else 4), vy, RULER, vy))
            if big:
                vl.append((vy, label(v)))
            v += sub
        return minor, major, hl, vl

    def _paint_ruler_marks(self, p, tf, band):
        """Parte che cambia col mouse e la selezione: cursore e ingombro della selezione sui righelli."""
        # posizione del cursore sui righelli
        c = tf.map(self.cursor_bed)
        p.setPen(cpen(C["accent_hi"], 1))
        p.drawLine(QPointF(c.x(), 0), QPointF(c.x(), RULER))
        p.drawLine(QPointF(0, c.y()), QPointF(RULER, c.y()))
        # selezione sui righelli
        if self.editor.selection:
            b = self.editor.selection_bounds()
            a = tf.map(QPointF(b.left(), b.bottom()))
            z = tf.map(QPointF(b.right(), b.top()))
            sel = QColor(C["accent"])
            sel.setAlpha(70)
            p.fillRect(QRectF(a.x(), RULER - 4, z.x() - a.x(), 4), sel)
            p.fillRect(QRectF(RULER - 4, a.y(), 4, z.y() - a.y()), sel)
        p.fillRect(QRectF(0, 0, RULER, RULER), band)
        p.setPen(QColor(C["muted"]))
        p.setFont(style.ui_font(7))
        p.drawText(QRectF(0, 0, RULER, RULER), Qt.AlignCenter, "mm")

    # ================================================================ API macchina / camera (come il vecchio piano)
    def set_head(self, x, y, state="Idle", power=0.0):
        self._head.setVisible(True)
        burning = state == "Run" and power > 0
        self._head.set_active(burning)
        new = QPointF(x, -y)
        if burning:
            if self._last_burn is None:
                self._trail_path.moveTo(new)
            else:
                self._trail_path.lineTo(new)
            self._last_burn = new
            self._trail_item.setPath(self._trail_path)
        else:
            self._last_burn = None
        self._head.setPos(new)

    def set_anchor_marker(self, x, y, label=""):
        """Mostra il punto di partenza del lavoro (None = nascosto)."""
        if x is None:
            self._anchor.setVisible(False)
            return
        self._anchor.setPos(QPointF(x, -y))
        self._anchor.set_label(label)
        self._anchor.setVisible(True)

    def anchor_marker(self):
        if not self._anchor.isVisible():
            return None
        q = self._anchor.pos()
        return QPointF(q.x(), -q.y())

    # ---------------------------------------------------------------- scritte e spiegazioni dei segni
    def set_marker_labels(self, on):
        """Scritte accanto ai segni (testa, punto di partenza): solo con «Mostra i nomi sotto i comandi»."""
        self.marker_labels = bool(on)
        self._anchor.show_label = self.marker_labels
        self._anchor.update()
        self._head.set_label(tr("testa del laser") if self.marker_labels else "")

    def marker_under(self, vp):
        """Il segno sotto il punto vp (pixel della vista), o None. La testa vince sul punto di partenza."""
        for item, kind in ((self._head, "head"), (self._anchor, "anchor")):
            if item.isVisible():
                q = QPointF(self.mapFromScene(item.pos()))
                if abs(q.x() - vp.x()) <= 13 and abs(q.y() - vp.y()) <= 13:
                    return kind
        return None

    def marker_hint_text(self, kind):
        if kind == "head":
            return (tr("Testa del laser"), tr("Dove si trova adesso la testa, secondo la macchina. Si sposta solo quando "
                                             "si muove il laser: frecce, Contorno, Porta la testa qui, lavoro."), C["accent_hi"])
        body = tr("Il punto del lavoro scelto con i 9 pallini (pannello Laser, Posizionamento). Il lavoro, "
                  "cioè l'anteprima arancione, si appoggia qui. Non è la testa: per portarcela usa «Porta la testa qui».")
        if self._anchor.label:
            body += "\n" + tr("Adesso: {0}.", self._anchor.label)
        return tr("Punto di partenza del lavoro"), body, ANCHOR

    def _update_marker_hint(self, vp):
        kind = None
        if vp is not None:
            try:
                ok = self.hints_allowed()
            except Exception:  # noqa: BLE001
                ok = False
            kind = self.marker_under(vp) if ok else None
        if kind is None:
            self.hide_marker_hint()
            return
        if kind != self._hint_for:
            self._hint.set_text(*self.marker_hint_text(kind))
            self._hint_for = kind
        item = self._head if kind == "head" else self._anchor
        q = QPointF(self.mapFromScene(item.pos()))
        r = self._hint.boundingRect()
        vw, vh = self.viewport().width(), self.viewport().height()
        x = q.x() + 18 if q.x() + 18 + r.width() < vw else q.x() - 18 - r.width()
        y = q.y() + 18 if q.y() + 18 + r.height() < vh else q.y() - 18 - r.height()
        self._hint.setPos(self.mapToScene(int(max(0, x)), int(max(0, y))))
        self._hint.setVisible(True)

    def hide_marker_hint(self):
        if self._hint.isVisible():
            self._hint.setVisible(False)
        self._hint_for = None

    def marker_hint_shown(self):
        return self._hint_for if self._hint.isVisible() else None

    def head_pos(self):
        if not self._head.isVisible():
            return None
        p = self._head.pos()
        return QPointF(p.x(), -p.y())

    def clear_trail(self):
        self._trail_path = QPainterPath()
        self._last_burn = None
        self._trail_item.setPath(self._trail_path)

    def hide_head(self):
        self._head.setVisible(False)

    def set_camera_image(self, qimage, px_per_mm, opacity=0.85):
        pix = QPixmap.fromImage(qimage)
        if self._cam_item is None:
            self._cam_item = QGraphicsPixmapItem()
            self._cam_item.setZValue(-1000)
            self._cam_item.setTransformationMode(Qt.SmoothTransformation)
            self.scene().addItem(self._cam_item)
        self._cam_item.setPixmap(pix)
        self._cam_item.setScale(1.0 / px_per_mm)
        self._cam_item.setPos(0, -self.bed_y)
        self._cam_item.setOpacity(opacity)

    def set_camera_opacity(self, o):
        if self._cam_item is not None:
            self._cam_item.setOpacity(o)

    def clear_camera(self):
        if self._cam_item is not None:
            self.scene().removeItem(self._cam_item)
            self._cam_item = None

    def set_preview(self, pv, offset=(0.0, 0.0)):
        """Anteprima del G-code: tratti con laser acceso (blu), trasferimenti (tratteggio)."""
        self.clear_preview()
        if pv is None:
            return
        if len(pv.segs) > gcode_preview.BIG:
            self._set_preview_raster(pv, offset)
            return
        travel = QPainterPath()
        for x1, y1, x2, y2 in pv.travel:
            travel.moveTo(x1, -y1)
            travel.lineTo(x2, -y2)
        cut = QPainterPath()
        last = None
        for x1, y1, x2, y2, _p in pv.cut:
            if last != (x1, y1):
                cut.moveTo(x1, -y1)
            cut.lineTo(x2, -y2)
            last = (x2, y2)
        t = QGraphicsPathItem(travel)
        t.setPen(cpen(C["muted"], 1, Qt.DashLine, 90))
        c = QGraphicsPathItem(cut)
        c.setPen(cpen("#FF8A3D", 1.2, alpha=220))
        for it in (t, c):
            it.setZValue(800)
            self.scene().addItem(it)
        self._preview_items = [t, c]
        self.set_preview_offset(offset)

    def _set_preview_raster(self, pv, offset):
        """Lavori enormi (foto): l'anteprima è un'immagine. Centinaia di migliaia di tratti vettoriali
        rendevano lentissimo ogni ridisegno del piano, fino a sembrare bloccato."""
        r = gcode_preview.rasterize(pv.segs, px_per_mm=6.0, max_px=2400)
        if r is None:
            return
        power, _idx, (x0, y0, w, h) = r
        ny, nx = power.shape
        rgba = np.zeros((ny, nx, 4), np.uint8)
        col = QColor("#FF8A3D")
        on = power > 0
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = col.red(), col.green(), col.blue()
        rgba[..., 3] = np.where(on, (90 + 150 * power).astype(np.uint8), 0)
        qi = QImage(rgba.data, nx, ny, 4 * nx, QImage.Format_RGBA8888).copy()
        it = QGraphicsPixmapItem(QPixmap.fromImage(qi))
        it.setTransformationMode(Qt.SmoothTransformation)
        it.setScale(w / nx)
        it.setData(0, (x0, y0 + h))  # angolo in alto a sinistra in coordinate piano (prima dello spostamento)
        it.setZValue(800)
        self.scene().addItem(it)
        self._preview_items = [it]
        self.set_preview_offset(offset)

    def set_preview_offset(self, off):
        for it in self._preview_items:
            corner = it.data(0)
            if corner:  # immagine: la posizione è il suo angolo in alto a sinistra
                it.setPos(corner[0] + off[0], -(corner[1] + off[1]))
            else:
                it.setPos(off[0], -off[1])

    def clear_preview(self):
        self._anchor.setVisible(False)
        for it in self._preview_items:
            self.scene().removeItem(it)
        self._preview_items = []
