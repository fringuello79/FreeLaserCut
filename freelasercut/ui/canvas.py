# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Tela di disegno di FreeLaserCut: il piano di lavoro con le forme, gli strumenti e gli aiuti visivi.

Sistemi di coordinate:
  - piano (mm, Y su): quello del documento e della macchina;
  - scena Qt: (x, -y), le forme stanno sotto un nodo "mondo" ribaltato;
  - vista (pixel): per maniglie, righelli, aggancio e tutto ciò che ha misura fissa a schermo.
"""
import math
import time

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from .. import gcode_preview
from ..core import geom, imaging, photo_clip
from .. import perfstats
from ..core.document import LAYER_COLORS, GroupShape, ImageShape, TextShape
from ..theme import C
from . import style
from freelasercut.i18n import tr  # noqa: E402

BURN = "#FF8A3D"
RULER = 20  # px
TOOL_LAYER_COLOR = "#8A9BBE"
# aspetto della selezione (pixel dello schermo): alone trasparente + linea piena
SEL_HALO_W, SEL_HALO_ALPHA, SEL_LINE_W = 7.0, 85, 2.0
SEL_HALO_MAX = 400  # oltre questo numero di forme selezionate solo la linea piena (il piano resta veloce)
# 0.20.4, immagine pronta del piano. Se ridisegnare forme o selezione costa più di PLANE_SLOW_S secondi, mentre si
# trascina, si sposta la vista o si usa la rotella si mostra l'immagine di prima (spostata o ingrandita) e quella
# vera si rifà appena ci si ferma: PLANE_IDLE_MS dopo l'ultimo movimento, di più se il disegno è molto pesante.
PLANE_SLOW_S = 0.045
PLANE_IDLE_MS = (130, 900)
PLANE_BURST_S = 0.35  # per quanto tempo dopo un movimento vale ancora «sto trascinando»
# Disegni con tantissimi punti (SVG complessi, foto vettorializzate): contorni larghi 1 pixel invece di 1,25 e zone
# riempite senza smussatura dei bordi (che restano sotto il contorno). Per chi disegna il piano è circa dieci volte
# meno lavoro e la differenza quasi non si vede. Stessa soglia degli altri piani in grigio (_paint_ghosts).
MANY_POINTS = 20000


class PlaneLayer:
    """Un'immagine pronta di una parte del piano (forme, oppure contorno della selezione), grande come la vista."""

    def __init__(self):
        self.pix = None
        self.rect = QRectF()  # la parte della vista che l'immagine riempie (fuori non c'è niente di buono)
        self.key = None  # di che cosa è l'immagine (vista + contenuto)
        self.bed_tf = None  # piano -> pixel della vista, al momento del disegno
        self.cost = 0.0  # secondi dell'ultimo disegno vero
        self.tfs = {}  # (selezione) trasformazione di ogni forma al momento del disegno
        self.geom_ver = None  # (selezione) geom_ver del piano al momento del disegno
        self.renders = 0  # quante volte è stata disegnata davvero (per le prove)

    def drop(self):
        self.key = self.bed_tf = None  # il foglio (pix) resta: si riusa al prossimo disegno
        self.rect = QRectF()
        self.tfs = {}


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
        self._rects = None
        self.points = 0
        # 0.20.4: Qt non chiama più paint() forma per forma: disegna tutto WorldItem (dall'immagine pronta del
        # piano, oppure chiamando paint_shape). Con migliaia di forme anche solo il giro delle chiamate pesava
        self.setFlag(QGraphicsItem.ItemHasNoContents, True)
        self.refresh()

    def refresh(self):
        self.prepareGeometryChange()
        self._path = self.fb_shape.path()
        self._bounds = self._path.boundingRect().adjusted(-1, -1, 1, 1)
        self._leaves = None  # i percorsi si ricalcolano al prossimo disegno
        self._rects = None
        self.points = self._path.elementCount()
        self.canvas.content_ver += 1  # l'immagine pronta del piano non vale più
        self.update()

    def _leaf_paths(self):
        """(foglia, trasformazione, percorso nel piano) calcolati una volta per modifica: ridisegnare il piano
        (a ogni movimento del mouse) non rigenera più i contorni, per esempio quelli dei testi."""
        if self._leaves is None:
            self._leaves = [(leaf, tf, tf.map(leaf.local_path())) for leaf, tf in self.fb_shape.leaves()]
        return self._leaves

    def _leaf_rects(self):
        """Ingombro di ogni foglia nel piano (stesso ordine di _leaf_paths): serve a saltare quello che non c'entra
        (fuori dalla vista, lontano dal mouse) senza guardare i percorsi."""
        if self._rects is None:
            self._rects = [m.controlPointRect() for _l, _t, m in self._leaf_paths()]
        return self._rects

    def boundingRect(self):
        return self._bounds

    def shape(self):  # area sensibile per Qt (tooltip, trascinamenti, collisioni)
        from PySide6.QtGui import QPainterPath

        p = QPainterPath()
        p.addRect(self._bounds)
        return p

    def paint(self, painter, option, widget=None):  # non chiamato da Qt (ItemHasNoContents): vedi WorldItem
        self.paint_shape(painter, None, self.canvas.many_points())

    def paint_shape(self, painter, visible=None, thin=False):
        """Disegna la forma. visible: la zona del piano che si vede (le foglie tutte fuori si saltano);
        thin: disegno con tantissimi punti, contorni di 1 pixel (vedi MANY_POINTS)."""
        cv = self.canvas
        doc = cv.editor.doc
        width = 1.0 if thin else 1.25
        rects = self._leaf_rects() if visible is not None else None
        for i, (leaf, tf, mapped) in enumerate(self._leaf_paths()):
            if leaf.hidden:
                continue
            if rects is not None and not geom.rect_overlaps(rects[i], visible):
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
            # 0.18.1: la zona riempita la disegna FillItem per livello intero (come il G-code), non la forma da sola
            painter.setBrush(Qt.NoBrush)
            if leaf.layer >= 30:
                painter.setPen(cpen(col, 1, Qt.DashLine, 200))
            else:
                alpha = 255 if (cs is None or cs.output) else 110
                painter.setPen(cpen(col, width, Qt.SolidLine, alpha))
            painter.drawPath(path)


class FillItem(QGraphicsItem):
    """Zona riempita dei livelli Riempimento, calcolata per livello come nel G-code (ui/fill_preview.py): un quadrato
    con il suo offset mostra piena la fascia fra i due contorni e vuoto l'interno. Sta sotto i contorni.
    Si ricalcola quando cambiano le forme (sync, trascinamenti) o le impostazioni dei livelli (modo, mostra,
    raggruppamento del riempimento) o la vista «riempita»: queste ultime si controllano a ogni disegno."""

    BIG = QRectF(-100000, -100000, 200000, 200000)  # non cambia mai: niente prepareGeometryChange nel disegno

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.regions = []
        self.tones = []  # 0.20.7: toni dei livelli con la potenza dal grigio [(grigio, percorso)]
        self._key = None
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.ItemHasNoContents, True)  # la disegna WorldItem, come le forme

    def rebuild(self):
        self._key = None
        self.update()

    def _layers_key(self):
        cv = self.canvas
        return (cv.filled_view, tuple(sorted((k, c.mode, c.show, c.fill_grouping, getattr(c, "gray_power", False))
                                             for k, c in cv.editor.doc.layers.items())))

    def ensure(self):
        """Ricalcola le zone se serve; ritorna le zone [(livello, percorso)]."""
        from . import fill_preview

        key = self._layers_key()
        if key != self._key:
            cv = self.canvas
            entries = []
            if cv.filled_view:
                for s in cv.editor.doc.shapes:
                    it = cv.items_by_id.get(s.id)
                    if it is not None:
                        entries += [(leaf, mapped) for leaf, _tf, mapped in it._leaf_paths()]
            self.regions = fill_preview.regions(entries, cv.editor.doc.layers) if entries else []
            self.tones = fill_preview.tones(entries, cv.editor.doc.layers) if entries else []
            self._key = key
        return self.regions

    def boundingRect(self):
        return self.BIG

    def paint(self, painter, option, widget=None):  # non chiamato da Qt (ItemHasNoContents): vedi WorldItem
        self.paint_fill(painter, None, self.canvas.many_points())

    def paint_fill(self, painter, visible=None, rough=False):
        layers = self.canvas.editor.doc.layers
        painter.setPen(Qt.NoPen)
        painter.save()
        if rough:  # tantissimi punti: bordi della zona non smussati (stanno sotto il contorno)
            painter.setRenderHint(QPainter.Antialiasing, False)
        last = None
        for idx, path in self.ensure():
            if visible is not None and not geom.rect_overlaps(path.controlPointRect(), visible):
                continue
            if idx != last:
                cs = layers.get(idx)
                fc = QColor(layer_color(idx))
                fc.setAlpha(70 if (cs is None or cs.output) else 30)
                painter.setBrush(fc)
                last = idx
            painter.drawPath(path)
        for gray, path in self.tones:  # 0.20.7: sopra la zona del livello, il grigio di ogni forma (più scuro = più potenza)
            if visible is not None and not geom.rect_overlaps(path.controlPointRect(), visible):
                continue
            painter.setBrush(QColor(gray, gray, gray, 170))
            painter.drawPath(path)
        painter.restore()


class WorldItem(QGraphicsItem):
    """Il «mondo» ribaltato (Y in su) che contiene le forme. Dalla 0.20.4 le disegna lui: di norma copia
    l'immagine pronta del piano (forme e zone riempite, vedi Canvas._plane_pixmap), così passare con il mouse,
    cambiare selezione o disegnare gli aiuti di uno strumento non ridisegna le forme. Su altre superfici (immagine
    dell'intera finestra) o con plane_cache spento le disegna una per una, come prima."""

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas

    def boundingRect(self):
        return FillItem.BIG

    def paint(self, painter, option, widget=None):
        cv = self.canvas
        if widget is not cv.viewport() or not cv._plane_pass:
            # un'altra superficie (la scena disegnata in un'immagine, la vista stampata) o immagini pronte spente
            cv.paint_shapes(painter, None)
            return
        cv.blit_layer(painter, cv._plane, cv._plane_pixmap())


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


CAM_CENTER = "#2ED3B7"  # 0.20.0: punto sotto il mirino della camera della testa
BOARD = "#F5B83D"  # 0.20.0: tavola presa da due angoli


class CamCenterItem(QGraphicsItem):
    """0.20.0: il punto del piano sotto il mirino della camera della testa (quadratino verde acqua con il mirino)."""

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(995)

    def boundingRect(self):
        return QRectF(-14, -14, 28, 28)

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(CAM_CENTER)
        p.setPen(QPen(QColor(0, 0, 0, 140), 3))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(-6, -6, 12, 12))
        p.setPen(QPen(col, 1.6))
        p.drawRect(QRectF(-6, -6, 12, 12))
        for a, b in (((-12, 0), (-6, 0)), ((6, 0), (12, 0)), ((0, -12), (0, -6)), ((0, 6), (0, 12))):
            p.drawLine(QPointF(*a), QPointF(*b))


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
    tool_lock_changed = Signal(str)  # 0.19.0: nome dello strumento bloccato, "" quando si sblocca
    LOCKABLE = ("line", "freehand", "rect", "ellipse", "polygon", "star", "special")  # gli strumenti che disegnano forme e linee
    status = Signal(str)
    zoom_changed = Signal(float)
    context_requested = Signal(object, object)  # tasto destro senza trascinare: punto nella vista, punto sullo schermo
    guides_edited = Signal()  # 0.20.9: guide aggiunte, spostate o tolte
    view_changed = Signal()  # zoom, spostamento, misure o colore del piano: le linguette dei piani si riposizionano

    def __init__(self, editor, bed=(450.0, 440.0), parent=None):
        super().__init__(parent)
        self.editor = editor
        self.bed_x, self.bed_y = bed
        # 0.19.3: dove sta «casa» (l'angolo dell'homing, lo 0 della macchina) sul piano come si vede: non sempre in
        # basso a sinistra (assi invertiti, piano ruotato). Con il piano ruotato anche il verso degli assi X e Y
        # della macchina. Li imposta la finestra principale.
        self.plane_rot = 0
        self.machine_zero = (0.0, 0.0)
        self.machine_axes = ((1.0, 0.0), (0.0, 1.0))
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
        # 0.20.4: immagine pronta del piano (forme e selezione), vedi _plane_pixmap. plane_cache = False (o la
        # variabile FLC_NO_PLANE_CACHE) torna al disegno diretto di prima, forma per forma a ogni ridisegno
        import os as _os

        self.plane_cache = not _os.environ.get("FLC_NO_PLANE_CACHE")
        self.content_ver = 0  # cresce a ogni modifica delle forme (ShapeItem.refresh, sync)
        self.geom_ver = 0  # cresce quando può essere cambiata la sagoma delle forme (sync), non per i soli spostamenti
        self._plane = PlaneLayer()
        self._sel_layer = PlaneLayer()
        self._plane_pass = False  # il ridisegno in corso usa le immagini pronte
        # immagini provvisorie durante i movimenti (vedi PLANE_SLOW_S). Senza schermo (prove automatiche, che
        # fotografano la vista subito dopo ogni azione) restano spente: lì il piano è sempre quello vero
        from PySide6.QtGui import QGuiApplication

        self.plane_preview = (QGuiApplication.platformName() != "offscreen"
                              and not _os.environ.get("FLC_NO_PLANE_PREVIEW"))
        self._burst = 0.0  # ultimo movimento di un trascinamento / spostamento della vista / rotella
        self._plane_timer = QTimer(self)
        self._plane_timer.setSingleShot(True)
        self._plane_timer.timeout.connect(self._plane_idle)
        self.world = WorldItem(self)
        self.world.setTransform(QTransform.fromScale(1, -1))
        self.scene().addItem(self.world)
        self.items_by_id = {}
        # opzioni di vista
        self.filled_view = True
        self.show_grid = True
        self.light_bed = True  # piano chiaro (come un foglio): i colori dei livelli si leggono meglio
        self.snap_grid = False
        self.snap_objects = True
        # 0.20.9: guide tirate fuori dai righelli (core/guides.py): si vedono, ci si aggancia
        self.show_guides = True
        self.snap_guides = True
        self.show_ties = True  # 0.23.0: quote delle distanze fisse (solo a schermo)
        self.ties_create = False  # 0.23.0: Misura propone «Fissa questa distanza» (funzioni in prova sbloccate)
        self._tie_hits = []
        self._guide_drag = None  # {"kind": "h"|"v", "index": int|None, "pos": mm, "out": bool}
        self.dither_preview = False
        self.show_ghosts = True  # gli oggetti degli altri piani di lavoro, in grigio
        self._ghost_cache = (None, None)
        self.grid_step = 10.0
        # elementi macchina / camera / anteprima (coordinate scena)
        self._cam_item = None
        self._head = HeadItem()
        self.scene().addItem(self._head)
        self._head.setVisible(False)
        self._anchor = AnchorItem()
        self.scene().addItem(self._anchor)
        self._anchor.setVisible(False)
        # 0.20.0: camera della testa (punto sotto il mirino) e tavola presa da due angoli
        self._cam_center = CamCenterItem()
        self.scene().addItem(self._cam_center)
        self._cam_center.setVisible(False)
        self._board_item = QGraphicsPathItem()
        bpen = QPen(QColor(BOARD), 1.6, Qt.DashLine)
        bpen.setCosmetic(True)
        self._board_item.setPen(bpen)
        self._board_item.setZValue(980)
        self.scene().addItem(self._board_item)
        self._board_item.setVisible(False)
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
        # 0.20.7 (Ale, 18/11): la scia dell'incisione si può spegnere (su lavori lunghi il tracciato che cresce a ogni
        # stato appesantiva il programma) e si ridisegna al massimo 4 volte al secondo invece che a ogni stato
        self.show_trail = True
        self._trail_dirty = False
        self._trail_timer = QTimer(self)
        self._trail_timer.setSingleShot(True)
        self._trail_timer.setInterval(250)
        self._trail_timer.timeout.connect(self._flush_trail)
        # 0.20.7: anteprima e scia del lavoro in corso nascoste quando si guarda un altro piano con «Mostra gli altri
        # piani» spento (prima si vedevano lo stesso)
        self._job_overlay = True
        self._preview_items = []
        self._img_cache = {}
        # sfondo (piano + griglia) e righelli: cambiano solo con zoom, spostamento, dimensioni e opzioni di vista,
        # non quando si muove il mouse; si disegnano una volta e poi si copiano (molto più veloce sui PC lenti)
        self._bg_cache = (None, None, None)  # (chiave, pixmap, passo griglia)
        self._ruler_cache = (None, None)
        # stato interazione
        self.cursor_bed = QPointF(0, 0)
        self.snap_hint = None  # (QPointF piano, etichetta)
        self.overlay_paths = []  # 0.20.5: tracciati provvisori (mm sul piano) di una finestra, es. anteprima dell'offset
        self.tool_lock = None  # 0.19.0: strumento di disegno bloccato con il doppio clic (resta attivo dopo ogni forma)
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

    def set_machine_marks(self, zero, axis_x, axis_y, rot=0):
        """Lo 0 della macchina sul piano e il verso dei suoi assi (per il pallino verde e, con il piano ruotato, per
        le due freccette X e Y)."""
        zero = (min(max(float(zero[0]), 0.0), self.bed_x), min(max(float(zero[1]), 0.0), self.bed_y))
        axes = []
        for du, dv in (axis_x, axis_y):  # le frecce vanno verso l'interno del piano
            inside = -1e-6 <= zero[0] + du * 1e-3 <= self.bed_x + 1e-6 and -1e-6 <= zero[1] + dv * 1e-3 <= self.bed_y + 1e-6
            axes.append((float(du), float(dv)) if inside else (-float(du), -float(dv)))
        new = (int(rot or 0) % 4, zero, tuple(axes))
        if new != (self.plane_rot, self.machine_zero, self.machine_axes):
            self.plane_rot, self.machine_zero, self.machine_axes = new
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
        self.content_ver += 1
        self.geom_ver += 1
        self._rebuild_fill()
        self._snap_cache = None
        self.viewport().update()

    def _rebuild_fill(self):
        it = getattr(self, "fill_item", None)
        if it is None:
            it = self.fill_item = FillItem(self)
            it.setParentItem(self.world)
        it.rebuild()

    def refresh_live(self, shapes):
        """Aggiornamento veloce durante i trascinamenti: le forme date sono state solo spostate, ruotate o scalate
        (è cambiata la loro trasformazione, non la sagoma). Se cambia la sagoma si passa da sync (editor.live)."""
        moved = self.editor.solve_ties()[0]  # 0.23.0: chi ha una distanza fissa segue dal vivo
        if moved:
            by = {s.id: s for s in self.editor.doc.shapes}
            shapes = list(shapes) + [by[i] for i in moved if i in by]
        for s in shapes:
            it = self.items_by_id.get(s.id)
            if it is not None:
                it.refresh()
        self._rebuild_fill()
        self.viewport().update()

    # ================================================================ immagini
    def image_preview(self, leaf, cs):
        img = self.editor.doc.images.get(leaf.image_id)
        if img is None:
            return None
        dith = self.dither_preview and cs is not None and cs.mode == "image"
        key = (leaf.image_id, round(leaf.brightness, 2), round(leaf.contrast, 2), round(leaf.gamma, 3),
               bool(cs and cs.negative), dith, cs.dither if dith else None, cs.dpi if dith else None,
               round(leaf.w, 2) if dith else None, round(leaf.h, 2) if dith else None,
               # 0.19.0: cambiando cella, angolo o dimensione del punto del retino l'anteprima va rifatta
               (cs.halftone_cell, cs.halftone_angle, cs.halftone_size) if dith and cs.dither == "halftone" else None,
               photo_clip.key(leaf))  # 0.20.3: foto ritagliata con una forma
        q = self._img_cache.get(key)
        if q is not None:
            return q
        dark = imaging.to_dark(img)
        # 0.22.3: le parti trasparenti non si disegnano (prima erano bianche e coprivano quello che c'è sotto).
        # Colore = il disegno regolato, trasparenza = quella dell'immagine: su fondo bianco si vede lo stesso scuro
        # che verrà inciso (scuro del disegno × trasparenza)
        alpha = imaging.alpha_of(img)
        neg = bool(cs and cs.negative)
        cover = None  # trasparenza da dare ai pixel (None = immagine piena, come prima)
        if dith:
            step = 25.4 / max(cs.dpi, 10)
            nx = max(2, min(int(leaf.w / step), 2400))
            ny = max(2, min(int(leaf.h / step), 2400))
            import cv2

            small = cv2.resize(dark, (nx, ny), interpolation=cv2.INTER_AREA)
            small_a = None if alpha is None else cv2.resize(alpha, (nx, ny), interpolation=cv2.INTER_AREA)
            small = imaging.adjust_alpha(small, small_a, leaf.brightness, leaf.contrast, leaf.gamma, cs.negative)
            vals = imaging.dither(small, cs.dither, max(cs.halftone_cell / step, 2), cs.halftone_angle,
                                  cs.halftone_size)
            if small_a is None:
                lum = (1.0 - vals) * 255
            elif cs.dither == "grayscale":  # potenza continua: colore del disegno, trasparenza dell'immagine
                lum = (1.0 - imaging.unpremultiply(vals, small_a)) * 255
                cover = small_a
            else:  # punti accesi pieni, il resto trasparente come l'immagine
                lum = (1.0 - vals) * 255
                cover = np.maximum(small_a, vals.astype(np.float32))
        elif alpha is None:
            dark = imaging.adjust(dark, leaf.brightness, leaf.contrast, leaf.gamma, neg)
            lum = (1.0 - dark) * 255
        else:
            dark = imaging.adjust(imaging.unpremultiply(dark, alpha), leaf.brightness, leaf.contrast, leaf.gamma, neg)
            lum = (1.0 - dark) * 255
            cover = alpha
        arr = np.ascontiguousarray(lum.astype(np.uint8))
        h, w = arr.shape
        if getattr(leaf, "clip", None):  # 0.20.3: fuori dalla sagoma la foto non si vede (né si incide)
            keep = photo_clip.pixel_mask(leaf.clip, leaf.w, leaf.h, w, h)
            cover = np.where(keep, 1.0 if cover is None else cover, 0.0)
        if cover is not None:
            rgba = np.empty((h, w, 4), np.uint8)
            rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = arr
            rgba[..., 3] = np.clip(np.rint(np.asarray(cover, np.float32) * 255), 0, 255).astype(np.uint8)
            qi = QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()
        else:
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

    def view_state(self):
        """0.19.6: zoom e posizione della vista (per ricordarli piano per piano)."""
        return (QTransform(self.transform()), self.horizontalScrollBar().value(), self.verticalScrollBar().value(),
                self._user_zoomed)

    def set_view_state(self, st):
        tf, h, v, user = st
        self.setTransform(tf)
        self.horizontalScrollBar().setValue(h)
        self.verticalScrollBar().setValue(v)
        self._user_zoomed = user
        self.zoom_changed.emit(self.scale_px())
        self.viewport().update()

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
        self.touch_burst()
        super().resizeEvent(e)
        if not self._user_zoomed:
            self.fit_bed()

    # ================================================================ strumenti
    def lock_tool(self, name):
        """Doppio clic su uno strumento di disegno (0.19.0): resta attivo dopo ogni forma, per disegnarne tante di
        seguito, finché non si preme Esc o si sceglie un altro strumento. -> True se lo strumento si può bloccare."""
        if name not in self.LOCKABLE or name not in self.tools:
            return False
        if self.tool is not self.tools[name]:
            self.set_tool(name)
        self.tool_lock = name
        self.tool_lock_changed.emit(name)
        self.viewport().update()
        return True

    def unlock_tool(self):
        if self.tool_lock is not None:
            self.tool_lock = None
            self.tool_lock_changed.emit("")
            self.viewport().update()

    def tool_done(self):
        """Uno strumento di disegno ha finito una forma: si torna a Selezione, a meno che sia bloccato."""
        if self.tool_lock is not None and self.tool is self.tools.get(self.tool_lock):
            self.viewport().update()
            return
        self.set_tool("select")

    def set_tool(self, name):
        if name not in self.tools:
            return
        if name != self.tool_lock:
            self.unlock_tool()  # scelto un altro strumento: il blocco finisce
        if self.tool is not None:
            self.tool.deactivate()
        self.tool = self.tools[name]
        self.tool.activate()
        self.viewport().setCursor(self.tool.cursor())
        self.tool_changed.emit(name)
        self.viewport().update()

    # ================================================================ aggancio
    def _snap_points(self, exclude_ids):
        """I punti a cui ci si aggancia (angoli, centri, mezzerie degli ingombri e nodi delle forme), tutti in una
        matrice, ricordati finché non cambia il disegno o l'insieme delle forme escluse. -> (matrice N×2, tipi).
        0.20.5: i nodi si leggono in blocco con numpy (path_arrays). Prima un elemento alla volta: il primo movimento
        di ogni trascinamento, con centinaia di tracciati, fermava la finestra per quasi un secondo sui PC lenti
        (rapporto FLC-20261116-0746-D046). Stessi punti, nello stesso ordine."""
        if self._snap_cache is not None and self._snap_cache[0] == exclude_ids:
            return self._snap_cache[1], self._snap_cache[2]
        from ..core.document import path_arrays

        chunks, kinds = [], []
        box_kinds = ["angolo"] * 4 + ["centro"] + ["metà"] * 4
        for s in self.editor.doc.shapes:
            if s.id in exclude_ids or s.hidden:
                continue
            b = s.bounds()
            cx, cy = b.center().x(), b.center().y()
            chunks.append(np.array(((b.left(), b.top()), (b.right(), b.top()), (b.left(), b.bottom()),
                                    (b.right(), b.bottom()), (cx, cy), (cx, b.top()), (cx, b.bottom()),
                                    (b.left(), cy), (b.right(), cy)), float))
            kinds += box_kinds
            if isinstance(s, ImageShape):
                continue
            path = s.path()
            n = path.elementCount()
            if n > 4000:
                continue
            t, x, y = path_arrays(path)
            # nodi: inizi e fine dei segmenti (elementi 0 e 1) e punto finale delle curve (due elementi dopo il 2)
            idx = np.flatnonzero(t <= 1)
            ci = np.flatnonzero(t == 2)
            ci = ci[ci + 2 < n] + 2
            if len(ci):
                idx = np.sort(np.r_[idx, ci])
            if len(idx):
                chunks.append(np.stack([x[idx], y[idx]], 1))
                kinds += ["nodo"] * len(idx)
        arr = np.concatenate(chunks) if chunks else np.zeros((0, 2))
        self._snap_cache = (exclude_ids, arr, kinds)
        return arr, kinds

    def snap(self, bed_pt, exclude_ids=frozenset(), force_grid=False):
        """Aggancia a nodi/centri/angoli delle altre forme (entro 9 px) o alla griglia."""
        self.snap_hint = None
        t0 = time.perf_counter()
        try:
            return self._snap(bed_pt, exclude_ids, force_grid)
        finally:
            self._snap_s = getattr(self, "_snap_s", 0.0) + time.perf_counter() - t0

    def _snap(self, bed_pt, exclude_ids, force_grid):
        if self.snap_objects:
            arr, kinds = self._snap_points(frozenset(exclude_ids))
            if len(arr):
                d = np.hypot(arr[:, 0] - bed_pt.x(), arr[:, 1] - bed_pt.y())
                k = int(np.argmin(d))
                if d[k] <= self.px(9):
                    p = QPointF(arr[k, 0], arr[k, 1])
                    self.snap_hint = (p, kinds[k])
                    return p
        gx_hit = gy_hit = False
        if self.snap_guides and self.show_guides and self.editor.doc.guides:  # 0.20.9: guide, un asse alla volta
            from ..core import guides as gd

            x, y, gx_hit, gy_hit = gd.snap_point(bed_pt.x(), bed_pt.y(), self.editor.doc.guides, self.px(9))
            if gx_hit or gy_hit:
                bed_pt = QPointF(x, y)
        if self.snap_grid or force_grid:
            g = self.grid_step
            p = QPointF(bed_pt.x() if gx_hit else round(bed_pt.x() / g) * g,
                        bed_pt.y() if gy_hit else round(bed_pt.y() / g) * g)
            self.snap_hint = (p, "guida" if (gx_hit or gy_hit) else "griglia")
            return p
        if gx_hit or gy_hit:
            self.snap_hint = (bed_pt, "guida")
        return bed_pt

    def snap_move(self, box, nodes, dx, dy, exclude_ids=frozenset()):
        """Aggancio mentre si sposta una selezione (0.18.11): si agganciano gli angoli, le mezzerie, il centro e i
        nodi della selezione (non il punto del mouse) a quelli delle altre forme; se nessun punto è a tiro, lato su
        lato con le forme vicine; poi la griglia. box = ingombro della selezione prima dello spostamento, nodes = i
        suoi nodi prima dello spostamento, (dx, dy) = spostamento chiesto dal mouse. -> (dx, dy) corretti."""
        t0 = time.perf_counter()
        try:
            return self._snap_move(box, nodes, dx, dy, exclude_ids)
        finally:
            self._snap_s = getattr(self, "_snap_s", 0.0) + time.perf_counter() - t0

    def _snap_move(self, box, nodes, dx, dy, exclude_ids):
        from ..core import snapping

        self.snap_hint = None
        exclude_ids = frozenset(exclude_ids)
        if self.snap_objects:
            arr, kinds = self._snap_points(exclude_ids)
            boxes = [(b.left(), b.top(), b.right(), b.bottom())
                     for b in (s.bounds() for s in self.editor.doc.shapes if s.id not in exclude_ids and not s.hidden)]
        else:
            arr, kinds, boxes = None, [], []
        r = snapping.move((box.left(), box.top(), box.right(), box.bottom()), nodes, dx, dy, arr, kinds, boxes,
                          self.px(9), self.grid_step if self.snap_grid else None)
        if r.hint is not None:
            self.snap_hint = (QPointF(*r.hint), r.label)
        out_dx, out_dy = r.dx, r.dy
        if r.how != "punto" and self.snap_guides and self.show_guides and self.editor.doc.guides:
            # 0.20.9: bordo o centro della selezione su una guida vicina; vince sul lato e sulla griglia di quell'asse
            from ..core import guides as gd

            fx, fy, lx, ly = gd.snap_box((box.left(), box.top(), box.right(), box.bottom()), dx, dy,
                                         self.editor.doc.guides, self.px(9))
            if fx is not None:
                out_dx = dx + fx
            if fy is not None:
                out_dy = dy + fy
            if fx is not None or fy is not None:
                c = box.center()
                self.snap_hint = (QPointF(lx if lx is not None else c.x() + out_dx,
                                          ly if ly is not None else c.y() + out_dy), "guida")
        return out_dx, out_dy

    # ================================================================ guide (0.20.9)
    def in_ruler(self, view_pt):
        """"h" sul righello in alto, "v" su quello a sinistra, None altrove (anche l'angolino «mm»)."""
        x, y = view_pt.x(), view_pt.y()
        if y < RULER and x >= RULER:
            return "h"
        if x < RULER and y >= RULER:
            return "v"
        return None

    def guide_at(self, view_pt, tol_px=4):
        """Indice della guida sotto il punto della vista (entro tol_px), o None."""
        from ..core import guides as gd

        if not self.show_guides or not self.editor.doc.guides:
            return None
        b = self.to_bed(view_pt)
        return gd.nearest(self.editor.doc.guides, b.x(), b.y(), self.px(tol_px))

    def _guide_value(self, view_pt, kind):
        b = self.to_bed(view_pt)
        v = b.y() if kind == "h" else b.x()
        if self.snap_grid:
            g = self.grid_step
            return round(v / g) * g
        step = 0.1 if self.scale_px() >= 2 else 1.0  # da vicino al decimo di mm, da lontano al mm
        return round(v / step) * step

    def guide_press(self, view_pt):
        """Clic sinistro: dal righello parte una guida nuova; su una guida (con Selezione, fuori dalle forme) la si
        prende per spostarla. -> True se il clic è delle guide."""
        kind = self.in_ruler(view_pt)
        if kind is not None:
            self._guide_drag = {"kind": kind, "index": None, "pos": self._guide_value(view_pt, kind), "out": False}
            self.show_guides = True
            self.viewport().setCursor(Qt.SplitVCursor if kind == "h" else Qt.SplitHCursor)
            self.viewport().update()
            return True
        if self.tool is not self.tools.get("select"):
            return False
        i = self.guide_at(view_pt)
        if i is None or self.hit_shape(self.to_bed(view_pt)) is not None:
            return False
        k, pos = self.editor.doc.guides[i]
        self._guide_drag = {"kind": k, "index": i, "pos": pos, "out": False}
        self.viewport().setCursor(Qt.SplitVCursor if k == "h" else Qt.SplitHCursor)
        return True

    def guide_move(self, view_pt):
        d = self._guide_drag
        d["pos"] = self._guide_value(view_pt, d["kind"])
        d["out"] = self.in_ruler(view_pt) is not None or view_pt.x() < RULER or view_pt.y() < RULER
        self.viewport().update()

    def guide_release(self, view_pt):
        """Lasciata sul piano: la guida va lì. Lasciata su un righello: una guida nuova non nasce, una vecchia si
        toglie. -> la lista delle guide dopo."""
        from ..core import guides as gd

        d, self._guide_drag = self._guide_drag, None
        self.viewport().setCursor(self.tool.cursor())
        doc = self.editor.doc
        out = self.in_ruler(view_pt) is not None or view_pt.x() < RULER or view_pt.y() < RULER
        old = list(doc.guides)
        lst = [g for i, g in enumerate(doc.guides) if i != d["index"]]
        if not out:
            lst, _ = gd.add(lst, d["kind"], self._guide_value(view_pt, d["kind"]))
        doc.guides = gd.clean(lst)
        if doc.guides != old:
            self.editor.dirty = True
            self.guides_edited.emit()
        self.viewport().update()
        return doc.guides

    def set_guides(self, lst):
        from ..core import guides as gd

        new = gd.clean(lst)
        if new != self.editor.doc.guides:
            self.editor.doc.guides = new
            self.editor.dirty = True
            self.guides_edited.emit()
        self.viewport().update()
        return new

    def _draw_guides(self, p, tf):
        doc = self.editor.doc
        d = self._guide_drag
        if not (self.show_guides and doc.guides) and d is None:
            return
        W, H = self.viewport().width(), self.viewport().height()
        col = "#15AABF"
        lines = [(g, i) for i, g in enumerate(doc.guides)] if self.show_guides else []
        p.setPen(cpen(col, 1.0, Qt.DashLine, 210))
        for (k, pos), i in lines:
            if d is not None and d["index"] == i:
                continue
            if k == "h":
                y = tf.map(QPointF(0, pos)).y()
                p.drawLine(QPointF(RULER, y), QPointF(W, y))
            else:
                x = tf.map(QPointF(pos, 0)).x()
                p.drawLine(QPointF(x, RULER), QPointF(x, H))
        if d is not None:
            p.setPen(cpen("#E8590C" if d["out"] else col, 1.4, Qt.SolidLine))
            p.setFont(style.ui_font(8))
            txt = tr("togli") if d["out"] and d["index"] is not None else ("" if d["out"] else f"{d['pos']:g} mm")
            if d["kind"] == "h":
                y = tf.map(QPointF(0, d["pos"])).y()
                p.drawLine(QPointF(RULER, y), QPointF(W, y))
                p.drawText(QPointF(RULER + 6, y - 4), txt)
            else:
                x = tf.map(QPointF(d["pos"], 0)).x()
                p.drawLine(QPointF(x, RULER), QPointF(x, H))
                p.drawText(QPointF(x + 4, RULER + 14), txt)

    # ================================================================ selezione a colpo
    def _image_hit_mask(self, image_id):
        """0.22.3: maschera ridotta delle parti visibili di un'immagine (None = nessuna parte trasparente), tenuta
        in memoria: il clic sulla tela si guarda a ogni movimento del mouse."""
        img = self.editor.doc.images.get(image_id)
        cache = getattr(self, "_hit_masks", None)
        if cache is None:
            cache = self._hit_masks = {}
        got = cache.get(image_id)
        if got is not None and got[0] is img:
            return got[1]
        alpha = imaging.alpha_of(img)
        mask = None if alpha is None else imaging.alpha_hit_mask(alpha)[0]
        if len(cache) > 32:
            cache.clear()
        cache[image_id] = (img, mask)
        return mask

    def _image_visible_near(self, s, bed_pt, tol):
        """C'è una parte visibile dell'immagine s entro tol (mm del piano) dal punto? Senza trasparenza sempre sì."""
        mask = self._image_hit_mask(s.image_id)
        if mask is None:
            return True
        inv, ok = s.tf.inverted()
        if not ok or s.w <= 0 or s.h <= 0:
            return True
        mh, mw = mask.shape
        xs, ys = [], []
        for dx in (-tol, tol):
            for dy in (-tol, tol):
                q = inv.map(QPointF(bed_pt.x() + dx, bed_pt.y() + dy))
                # stessa convenzione di imaging.sample_to_grid: locale 0..w, 0..h con la Y in su, riga 0 in alto
                xs.append(q.x() / s.w * mw)
                ys.append((1.0 - q.y() / s.h) * mh)
        c0, c1 = max(0, int(math.floor(min(xs)))), min(mw, int(math.ceil(max(xs))) + 1)
        r0, r1 = max(0, int(math.floor(min(ys)))), min(mh, int(math.ceil(max(ys))) + 1)
        if c0 >= c1 or r0 >= r1:
            return False
        return bool(mask[r0:r1, c0:c1].any())

    def hit_shape(self, bed_pt, tol_px=6):
        tol = self.px(tol_px)
        doc = self.editor.doc
        for s in reversed(doc.shapes):
            if s.hidden:
                continue
            cs = doc.layers.get(s.layer)
            if cs is not None and not cs.show and not isinstance(s, GroupShape):
                continue
            it = self.items_by_id.get(s.id)
            known = it is not None and it.fb_shape is s and it._path is s.path()  # ingombro e foglie già pronti
            b = (it._bounds.adjusted(1, 1, -1, -1) if known else s.bounds()).adjusted(-tol, -tol, tol, tol)
            if not b.contains(bed_pt):
                continue
            path = s.path()
            if isinstance(s, ImageShape):
                # 0.22.3: sulla parte trasparente il clic passa a quello che c'è sotto. Un'immagine già selezionata
                # si prende da tutto il riquadro, come prima (per trascinarla)
                if s in self.editor.selection or self._image_visible_near(s, bed_pt, tol):
                    return s
                continue
            if known and isinstance(s, GroupShape):
                # 0.20.4: di un gruppo si guardano solo le foglie vicine al punto (stesso risultato: le altre non
                # contengono il punto e il loro contorno è lontano). Un gruppo di migliaia di tracciati non si
                # ripassa più tutto a ogni movimento del mouse
                x, y = bed_pt.x(), bed_pt.y()
                near = QPainterPath()
                near.setFillRule(path.fillRule())
                reach = tol * 1.5  # le punte squadrate del contorno ingrossato arrivano a tol·√2 dagli estremi
                for (_l, _t, m), r in zip(it._leaf_paths(), it._leaf_rects()):
                    if r.left() - reach <= x <= r.right() + reach and r.top() - reach <= y <= r.bottom() + reach:
                        near.addPath(m)
                near.setFillRule(path.fillRule())
                if near.isEmpty():
                    continue
                path = near
            filled = self.filled_view and cs is not None and cs.mode in ("fill", "offset_fill")
            if (filled or isinstance(s, TextShape)) and path.contains(bed_pt):
                return s
            st = QPainterPathStroker()
            st.setWidth(2 * tol)
            if st.createStroke(path).contains(bed_pt):
                return s
        return None

    def shapes_in_rect(self, r, crossing):
        # 0.20.2: confronti fra riquadri come intervalli chiusi (geom.rect_*): QRectF.contains e intersects dicono
        # sempre di no per le linee perfettamente orizzontali o verticali (riquadro senza area), che restavano fuori
        out = []
        for s in self.editor.doc.shapes:
            if s.hidden:
                continue
            b = s.bounds()
            if geom.rect_inside(b, r):
                out.append(s)
            elif crossing and geom.rect_overlaps(b, r) and s.path().intersects(r):
                out.append(s)
        return out

    # ================================================================ eventi
    def wheelEvent(self, e):
        self.touch_burst()
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
        if e.button() == Qt.LeftButton and self.guide_press(e.position()):
            return
        if e.button() == Qt.RightButton and self.tool in (self.tools.get("select"), self.tools.get("nodes")):
            from . import ties_ui

            h = ties_ui.hit(self, e.position())  # 0.23.0: tasto destro sulla quota di una distanza fissa
            if h is not None:
                self._rpress = None
                ties_ui.menu(self, h[0], h[1], e.globalPosition().toPoint())
                self.viewport().update()
                return
        # lo strumento va guardato ADESSO: la Linea col tasto destro chiude il tracciato e passa a Selezione
        menu_ok = e.button() == Qt.RightButton and self.tool in (self.tools.get("select"), self.tools.get("nodes"))
        self._rpress = e.position() if menu_ok else None
        self.tool.press(e, self.to_bed(e.position()))
        self.viewport().update()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.NoButton:
            return self._mouse_move(e)
        # 0.20.5: con un tasto premuto ogni movimento si misura (perfstats: nel rapporto per l'assistenza)
        self._snap_s = 0.0
        t0 = time.perf_counter()
        try:
            self._mouse_move(e)
        finally:
            perfstats.note_move(time.perf_counter() - t0, self._snap_s)

    def paintEvent(self, e):
        burst = getattr(self, "_burst", 0.0)
        if not burst or time.monotonic() - burst >= PLANE_BURST_S:
            return super().paintEvent(e)
        t0 = time.perf_counter()  # 0.20.5: disegno durante un movimento (perfstats)
        try:
            return super().paintEvent(e)
        finally:
            perfstats.note_paint(time.perf_counter() - t0)

    def _mouse_move(self, e):
        bed = self.to_bed(e.position())
        self.cursor_bed = bed
        self.cursor_moved.emit(bed.x(), bed.y())
        if self._guide_drag is not None:
            self.guide_move(e.position())
            return
        self._update_marker_hint(e.position() if e.buttons() == Qt.NoButton and self._pan is None else None)
        if self._pan is not None or e.buttons() != Qt.NoButton:
            self.touch_burst()
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
        self.end_burst()  # ci si è fermati: il piano torna subito quello vero
        if self._guide_drag is not None and e.button() == Qt.LeftButton:
            self.guide_release(e.position())
            return
        if self._pan is not None and e.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan = None
            self.viewport().setCursor(Qt.OpenHandCursor if self._space else self.tool.cursor())
            return
        p0 = getattr(self, "_rpress", None)
        if e.button() == Qt.RightButton and p0 is not None:
            self._rpress = None
            # 0.18.6: clic destro (senza trascinare) con Selezione o Nodi = menu dei comandi. Con gli altri strumenti
            # il tasto destro resta loro (la Linea ci chiude il tracciato)
            if (e.position() - p0).manhattanLength() < 6:
                self.context_requested.emit(e.position(), e.globalPosition().toPoint())
                self.viewport().update()
                return
        self.tool.release(e, self.to_bed(e.position()))
        self.viewport().update()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            from . import ties_ui

            h = ties_ui.hit(self, e.position())  # 0.23.0: doppio clic sulla quota = nuovo valore
            if h is not None:
                ties_ui.edit_value(self, h[0], h[1])
                self.viewport().update()
                return
        self.tool.double_click(e, self.to_bed(e.position()))
        self.viewport().update()

    def event(self, e):
        from PySide6.QtCore import QEvent

        if e.type() == QEvent.Type.ShortcutOverride and self.tool.wants_key(e):
            # 0.19.2: Maiusc+Esc è lo Stop del lavoro: gli strumenti tengono per sé Esc (annulla il disegno in corso),
            # non Maiusc+Esc, altrimenti con il piano attivo lo Stop da tastiera non partirebbe mai
            if e.key() == Qt.Key_Escape and e.modifiers() == Qt.ShiftModifier:
                return super().event(e)
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
            return
        if e.key() == Qt.Key_Escape:
            self.unlock_tool()  # Esc toglie sempre il blocco; poi lo strumento fa quello che faceva (torna a Selezione)
        if e.isAutoRepeat():
            self.touch_burst()  # freccia tenuta premuta: come un trascinamento
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

    # ================================================================ disegno: immagine pronta del piano (0.20.4)
    def _plane_ok(self, p):
        """Questo ridisegno può usare le immagini pronte? Sì sulla vista (anche quando Qt la fotografa: grab);
        no su altre superfici, dove le forme si disegnano una per una."""
        return self.plane_cache and p.device() is self.viewport()

    def touch_burst(self):
        """Un movimento di un'azione continua (trascinamento, spostamento della vista, rotella, finestra che cambia
        misura): per un attimo il piano può mostrare l'immagine di prima, se quella vera costa troppo."""
        self._burst = time.monotonic()

    def end_burst(self):
        self._burst = 0.0
        if self._plane_timer.isActive():
            self._plane_timer.stop()
            self.viewport().update()

    def _plane_idle(self):
        self._burst = 0.0
        self.viewport().update()

    def flush_plane(self):
        """Disegna subito le immagini vere (per chi vuole il piano aggiornato adesso, senza aspettare)."""
        self._burst = 0.0
        self._plane_timer.stop()
        self.viewport().repaint()

    def _layers_look(self):
        """Tutto ciò che, nei livelli e nelle opzioni di vista, cambia l'aspetto delle forme senza passare da sync."""
        doc = self.editor.doc
        return (self.filled_view, self.dither_preview, id(doc), doc.current, len(doc.images),
                tuple(sorted((k, c.mode, c.show, c.output, c.fill_grouping, c.negative, c.dither, c.dpi,
                              c.halftone_cell, c.halftone_angle, c.halftone_size) for k, c in doc.layers.items())))

    def _stale_ok(self, layer):
        return (self.plane_preview and layer.key is not None and layer.cost > PLANE_SLOW_S
                and time.monotonic() - self._burst < PLANE_BURST_S)

    def _wait_idle(self, layer):
        lo, hi = PLANE_IDLE_MS
        ms = int(max(lo, min(hi, layer.cost * 2000)))
        if not self._plane_timer.isActive() or self._plane_timer.interval() < ms:
            self._plane_timer.setInterval(ms)
        self._plane_timer.start()

    def _layer_rect(self, bed_rect, margin_px):
        """La parte della vista (pixel interi) che contiene bed_rect più un margine; vuota se non si vede niente."""
        vp = self.viewport()
        if bed_rect is None:
            return QRectF()
        r = self.bed_to_view_tf().mapRect(bed_rect).adjusted(-margin_px, -margin_px, margin_px, margin_px)
        x0, y0 = max(0, math.floor(r.left())), max(0, math.floor(r.top()))
        x1, y1 = min(vp.width(), math.ceil(r.right())), min(vp.height(), math.ceil(r.bottom()))
        if x1 <= x0 or y1 <= y0:
            return QRectF()
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def _layer_pixmap(self, old=None):
        """Un foglio trasparente grande come la vista. Se old ha già le misure giuste si riusa così com'è (con
        quello che c'era sopra): si usa solo dentro il rettangolo che si prepara con _layer_clear."""
        vp = self.viewport()
        dpr = vp.devicePixelRatioF()
        w, h = max(1, round(vp.width() * dpr)), max(1, round(vp.height() * dpr))
        if old is not None and (old.width(), old.height()) == (w, h) and old.devicePixelRatioF() == dpr:
            return old
        pix = QPixmap(w, h)
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.transparent)  # serve anche a dare al foglio la trasparenza (senza, il fondo sarebbe nero)
        return pix

    @staticmethod
    def _layer_clear(q, rect):
        """Rende trasparente rect (un po' abbondante) e limita lì il disegno."""
        q.setCompositionMode(QPainter.CompositionMode_Source)
        q.fillRect(rect.adjusted(-2, -2, 2, 2), Qt.transparent)
        q.setCompositionMode(QPainter.CompositionMode_SourceOver)
        q.setClipRect(rect)

    def blit_layer(self, p, layer, tf):
        """Copia sul pittore p (della vista) l'immagine pronta di layer: così com'è (tf None) oppure, se è quella
        provvisoria, portata nella vista di adesso con tf."""
        if layer.pix is None or layer.rect.isEmpty():
            return
        p.save()
        p.setTransform(tf if tf is not None else QTransform())
        if tf is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)  # immagine provvisoria: conta la velocità
        p.setClipRect(layer.rect, Qt.IntersectClip)
        p.drawPixmap(0, 0, layer.pix)
        p.restore()

    def _visible_bed(self, margin_px=8):
        vp = self.viewport()
        r = self.mapToScene(vp.rect().adjusted(-margin_px, -margin_px, margin_px, margin_px)).boundingRect()
        return QRectF(r.left(), -r.bottom(), r.width(), r.height())

    def content_bounds(self):
        """Ingombro di tutte le forme del piano (ricordato finché non cambiano); None se non ce ne sono."""
        ver, b = getattr(self, "_cbounds", (None, None))
        if ver != self.content_ver:
            rects = [it._bounds for it in self.items_by_id.values() if it.isVisible()]
            b = geom.rect_union(rects) if rects else None
            self._cbounds = (self.content_ver, b)
        return b

    def paint_shapes(self, q, vis=None):
        """Zone riempite e forme, nell'ordine del documento, sul pittore q già messo nel sistema del piano.
        vis: la zona del piano che si vede (quello che è tutto fuori si salta); None = tutto."""
        many = self.many_points()
        self.fill_item.paint_fill(q, vis, many)
        for s in self.editor.doc.shapes:
            it = self.items_by_id.get(s.id)
            if it is not None and it.isVisible() and (vis is None or geom.rect_overlaps(it._bounds, vis)):
                it.paint_shape(q, vis, many)

    def _plane_pixmap(self):
        """Prepara l'immagine pronta delle forme e delle zone riempite (self._plane). -> la trasformazione con cui
        disegnarla, oppure None se è quella vera, da copiare così com'è (blit_layer).
        Si rifà solo quando cambiano le forme, i livelli o la vista: passare con il mouse, cambiare selezione,
        disegnare gli aiuti di uno strumento non la toccano. Se rifarla costa troppo e si sta trascinando o muovendo
        la vista, si usa quella di prima portata nella vista di adesso, e quella vera arriva appena ci si ferma."""
        L = self._plane
        bed_tf = self.bed_to_view_tf()
        key = (self._view_key(), self.content_ver, self._layers_look())
        if L.key == key:
            return None
        if self._stale_ok(L):
            self._wait_idle(L)
            return L.bed_tf.inverted()[0] * bed_tf
        t0 = time.perf_counter()
        rect = self._layer_rect(self.content_bounds(), 6)
        if not rect.isEmpty():
            L.pix = self._layer_pixmap(L.pix)
            q = QPainter(L.pix)
            self._layer_clear(q, rect)
            q.setRenderHints(self.renderHints())
            q.setTransform(bed_tf)
            self.paint_shapes(q, self._visible_bed())
            q.end()
        L.rect, L.key, L.bed_tf = rect, key, bed_tf
        L.cost = time.perf_counter() - t0
        L.renders += 1
        return None

    def many_points(self):
        """Il disegno ha tantissimi punti (vedi MANY_POINTS)? Contati una volta per modifica."""
        ver, many = getattr(self, "_many", (None, False))
        if ver != self.content_ver:
            n = 0
            for it in self.items_by_id.values():
                n += it.points
                if n > MANY_POINTS:
                    break
            many = n > MANY_POINTS
            self._many = (self.content_ver, many)
        return many

    def selection_bounds(self):
        """Ingombro della selezione, ricordato finché non cambiano le forme o la selezione (le maniglie lo chiedono
        a ogni ridisegno: con migliaia di forme ricalcolarlo ogni volta si sentiva)."""
        ed = self.editor
        key = (self.content_ver, tuple(s.id for s in ed.selection))
        ck, b = getattr(self, "_selb", (None, None))
        if ck != key:
            b = ed.selection_bounds()
            self._selb = (key, b)
        return QRectF(b)

    def _selection_look(self):
        return (C["accent"], C["accent_hi"], SEL_HALO_W, SEL_HALO_ALPHA, SEL_LINE_W)

    def _selection_tf(self, L, sel):
        """Di quanto si sono mosse, tutte insieme, le forme selezionate da quando il contorno è stato disegnato:
        la trasformazione nel piano, oppure None se non è la stessa per tutte (o la selezione è un'altra)."""
        if len(sel) != len(L.tfs):
            return None
        first = None
        for s in sel:
            t0 = L.tfs.get(s.id)
            if t0 is None:
                return None
            inv, ok = t0.inverted()
            if not ok:
                return None
            r = inv * s.tf
            if first is None:
                first = r
                scale = max(abs(r.m11()), abs(r.m12()), abs(r.m21()), abs(r.m22()), 1e-9)
            elif (max(abs(r.m11() - first.m11()), abs(r.m12() - first.m12()), abs(r.m21() - first.m21()),
                      abs(r.m22() - first.m22())) > 1e-7 * scale
                  or max(abs(r.dx() - first.dx()), abs(r.dy() - first.dy())) > 1e-6):
                return None
        return first

    def _selection_paths(self, sel, vis):
        """I contorni da evidenziare, foglia per foglia (un gruppo intero in un percorso solo è molto più lento da
        disegnare), solo quelli che si vedono. -> lista di percorsi nel piano."""
        out = []
        for s in sel:
            it = self.items_by_id.get(s.id)
            if it is None or it.fb_shape is not s or it._path is None:
                out.append(s.path())
                continue
            if not geom.rect_overlaps(it._bounds, vis):
                continue
            leaves = it._leaf_paths()
            if len(leaves) == 1:
                out.append(it._path)
                continue
            rects = it._leaf_rects()
            out += [m for (_l, _t, m), r in zip(leaves, rects) if geom.rect_overlaps(r, vis)]
        return out

    def _selection_pixmap(self):
        """Prepara l'immagine pronta del contorno della selezione (self._sel_layer: alone + linea piena).
        -> trasformazione come _plane_pixmap. Senza selezione l'immagine è vuota."""
        L = self._sel_layer
        sel = self.editor.selection
        if not sel:
            L.drop()
            return None
        bed_tf = self.bed_to_view_tf()
        ids = tuple(s.id for s in sel)
        key = (self._view_key(), self.content_ver, ids, self._selection_look())
        if L.key == key:
            return None
        if (self._stale_ok(L) and L.key is not None and L.key[2] == ids
                and L.key[3] == key[3] and L.geom_ver == self.geom_ver):
            moved = self._selection_tf(L, sel)
            if moved is not None:
                self._wait_idle(L)
                return L.bed_tf.inverted()[0] * moved * bed_tf
        t0 = time.perf_counter()
        rect = self._layer_rect(self.selection_bounds(), SEL_HALO_W + 4)
        if not rect.isEmpty():
            paths = self._selection_paths(sel, self._visible_bed(SEL_HALO_W + 4))
            pix = L.pix = self._layer_pixmap(L.pix)
            points = sum(self.items_by_id[s.id].points for s in sel if s.id in self.items_by_id)
            q = QPainter(pix)
            self._layer_clear(q, rect)
            q.setBrush(Qt.NoBrush)
            if points > MANY_POINTS:
                # tantissimi punti selezionati: niente alone, e la linea di 2 pixel fatta con quattro passate di
                # 1 pixel spostate di mezzo pixel (le linee fino a 1 pixel si disegnano molto più in fretta)
                q.setRenderHint(QPainter.Antialiasing)
                q.setPen(cpen(C["accent_hi"], 1.0, Qt.SolidLine))
                h = 0.5 / pix.devicePixelRatioF()  # mezzo pixel dello schermo (le penne «cosmetiche» contano quelli)
                for dx, dy in ((-h, -h), (h, -h), (-h, h), (h, h)):
                    q.setTransform(bed_tf * QTransform.fromTranslate(dx, dy))
                    for path in paths:
                        q.drawPath(path)
            else:
                if len(sel) <= SEL_HALO_MAX and len(paths) == 1:
                    q.setRenderHint(QPainter.Antialiasing)
                    q.setTransform(bed_tf)
                    q.setPen(cpen(C["accent"], SEL_HALO_W, Qt.SolidLine, SEL_HALO_ALPHA))
                    q.drawPath(paths[0])
                elif len(sel) <= SEL_HALO_MAX:
                    # più contorni: l'alone si disegna pieno su un foglio a parte e si posa trasparente, così dove
                    # due contorni si accavallano non diventa più scuro (come quando il gruppo era un percorso solo)
                    halo = self._halo_pix = self._layer_pixmap(getattr(self, "_halo_pix", None))
                    hq = QPainter(halo)
                    self._layer_clear(hq, rect)
                    hq.setRenderHint(QPainter.Antialiasing)
                    hq.setTransform(bed_tf)
                    hq.setBrush(Qt.NoBrush)
                    hq.setPen(cpen(C["accent"], SEL_HALO_W, Qt.SolidLine))
                    for path in paths:
                        hq.drawPath(path)
                    hq.end()
                    q.setOpacity(SEL_HALO_ALPHA / 255.0)
                    q.drawPixmap(0, 0, halo)
                    q.setOpacity(1.0)
                q.setRenderHint(QPainter.Antialiasing)
                q.setTransform(bed_tf)
                q.setPen(cpen(C["accent_hi"], SEL_LINE_W, Qt.SolidLine))
                for path in paths:
                    q.drawPath(path)
            q.end()
        L.rect, L.key, L.bed_tf = rect, key, bed_tf
        L.tfs = {s.id: QTransform(s.tf) for s in sel}
        L.geom_ver = self.geom_ver
        L.cost = time.perf_counter() - t0
        L.renders += 1
        return None

    def drawBackground(self, p, rect):
        vp = self.viewport()
        self._plane_pass = self._plane_ok(p)
        if p.device() is not vp:  # disegno su un'altra superficie (stampa, immagine): niente cache
            self._paint_background(p, rect)  # niente altri piani in grigio nelle immagini e nelle stampe
            return
        key = self._view_key() + (self.light_bed, self.show_grid, self.snap_grid, self.bed_x, self.bed_y)
        vk = key[:9] + (self.light_bed, self.bed_x, self.bed_y)
        if vk != getattr(self, "_last_vk", None):
            self._last_vk = vk
            QTimer.singleShot(0, self, self.view_changed.emit)  # non durante il disegno
        gp = self.ghost_path()  # gli altri piani in grigio sono nello sfondo già pronto: niente lavoro a ogni ridisegno
        key += (id(gp) if gp is not None else None, self.machine_zero)
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
            self._paint_ghosts(q, gp)
            q.end()
            self._bg_cache = (key, pix, self.grid_step)
        else:
            self.grid_step = step  # come se lo sfondo fosse stato ridisegnato (passo dell'aggancio alla griglia)
        p.save()
        p.resetTransform()
        p.drawPixmap(0, 0, pix)
        p.restore()

    # ================================================================ altri piani di lavoro (riferimento in grigio)
    def set_ghosts(self, on):
        self.show_ghosts = bool(on)
        self.viewport().update()

    def ghost_path(self):
        """Contorni degli oggetti degli altri piani (nel sistema del piano), ricalcolati solo quando cambiano."""
        doc = self.editor.doc
        if not self.show_ghosts or len(doc.plates) < 2:
            return None
        others = [s for s in doc.other_shapes() if not s.hidden]
        if not others:
            return None
        key = (doc.current, tuple((id(s), id(s.path())) for s in others))
        ck, path = self._ghost_cache
        if ck != key:
            path = QPainterPath()
            for s in others:
                path.addPath(s.path())
            if path.elementCount() > 60000:  # foto vettorializzate, serie enormi: per il grigio basta meno dettaglio
                polys = path.toSubpathPolygons()
                step = max(1, -(-sum(len(q) for q in polys) // 60000))
                light = QPainterPath()
                for q in polys:
                    pts = [q[j] for j in range(0, len(q), step)] + ([q[len(q) - 1]] if len(q) > 1 else [])
                    if len(pts) > 1:
                        light.moveTo(pts[0])
                        for pt in pts[1:]:
                            light.lineTo(pt)
                path = light
            self._ghost_cache = (key, path)
        return path

    def _paint_ghosts(self, p, path):
        if path is None:
            return
        p.save()
        p.setTransform(QTransform.fromScale(1, -1), True)
        small = path.elementCount() <= 20000
        p.setRenderHint(QPainter.Antialiasing, small)  # tanti punti: più veloce senza smussatura
        col = QColor(70, 80, 95, 95) if self.light_bed else QColor(220, 228, 240, 85)
        pen = QPen(col, 1.2 if small else 0)  # spessore 0 = linea di un pixel, la più veloce da disegnare
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
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
        # origine macchina: nell'angolo dell'homing (0.19.3; prima sempre in basso a sinistra)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["success"]))
        r = self.px(4)
        p.drawEllipse(QPointF(self.machine_zero[0], self.machine_zero[1]), r, r)

    # ================================================================ disegno: primo piano
    def drawForeground(self, p, rect):
        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.Antialiasing)
        tf = self.bed_to_view_tf()
        ed = self.editor
        # contorno selezione (0.20.0, da un rapporto del 14/11: «il tratteggio si vede male»): alone largo e
        # trasparente del colore d'accento sotto una linea piena, visibile anche sulle forme del livello blu
        if ed.selection and self._plane_pass:
            # 0.20.4: il contorno è un'immagine pronta, rifatta solo quando cambiano selezione, forme o vista
            self.blit_layer(p, self._sel_layer, self._selection_pixmap())
        elif not ed.selection:
            self._sel_layer.drop()
        else:
            p.setBrush(Qt.NoBrush)
            paths = []
            for s in ed.selection:
                it = self.items_by_id.get(s.id)
                path = it._path if it is not None and it.fb_shape is s and it._path is not None else s.path()
                paths.append(tf.map(path))
            if len(paths) <= SEL_HALO_MAX:
                p.setPen(cpen(C["accent"], SEL_HALO_W, Qt.SolidLine, SEL_HALO_ALPHA))
                for vp in paths:
                    p.drawPath(vp)
            p.setPen(cpen(C["accent_hi"], SEL_LINE_W, Qt.SolidLine))
            for vp in paths:
                p.drawPath(vp)
        if self.overlay_paths:  # 0.20.5: anteprima di una finestra aperta (non è nel documento, non si incide)
            p.setBrush(Qt.NoBrush)
            for pen in (cpen("#FFFFFF", 3.2, Qt.SolidLine, 150), cpen(C["accent_hi"], 1.6, Qt.DashLine)):
                p.setPen(pen)
                for path in self.overlay_paths:
                    p.drawPath(tf.map(path))
        from . import ties_ui

        ties_ui.draw(self, p, tf)  # 0.23.0: quote delle distanze fisse, sotto quello che disegna lo strumento
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
        if self.tool_lock is not None:  # un cartellino accanto al cursore dice che lo strumento è bloccato
            v = tf.map(self.cursor_bed)
            text = tr("bloccato · Esc per finire")
            p.setFont(style.ui_font(8))
            w = p.fontMetrics().horizontalAdvance(text) + 10
            box = QRectF(v.x() + 14, v.y() + 16, w, 17)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(47, 125, 246, 220))
            p.drawRoundedRect(box, 4, 4)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(box, Qt.AlignCenter, text)
        if self.plane_rot:
            self._draw_machine_axes(p, tf)
        self._draw_guides(p, tf)
        self._draw_rulers(p, tf)
        p.restore()

    def machine_axes_view(self, tf=None):
        """[(lettera, punto di partenza, punta)] in pixel della vista: le freccette degli assi della macchina."""
        tf = tf or self.bed_to_view_tf()
        z = tf.map(QPointF(self.machine_zero[0], self.machine_zero[1]))
        out = []
        for name, (du, dv) in zip(("X", "Y"), self.machine_axes):
            far = tf.map(QPointF(self.machine_zero[0] + du, self.machine_zero[1] + dv))
            d = far - z
            n = math.hypot(d.x(), d.y()) or 1.0
            out.append((name, z, QPointF(z.x() + d.x() / n * 34, z.y() + d.y() / n * 34)))
        return out

    def _draw_machine_axes(self, p, tf):
        """Piano ruotato: due freccette dallo 0 della macchina dicono dove vanno i suoi assi X e Y."""
        p.setFont(style.ui_font(8))
        for name, z, tip in self.machine_axes_view(tf):
            col = QColor("#D9480F" if name == "X" else "#1971C2")
            p.setPen(cpen(col.name(), 1.8))
            p.drawLine(z, tip)
            ux, uy = (tip.x() - z.x()) / 34.0, (tip.y() - z.y()) / 34.0
            for sgn in (1, -1):
                p.drawLine(tip, QPointF(tip.x() - 6 * ux + sgn * 4 * uy, tip.y() - 6 * uy - sgn * 4 * ux))
            p.setPen(col)
            p.drawText(QRectF(tip.x() + 9 * ux - 8, tip.y() + 9 * uy - 8, 16, 16), Qt.AlignCenter, name)

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
    def set_overlay(self, paths):
        """0.20.5: tracciati provvisori disegnati sopra il piano (QPainterPath in mm sul piano); [] li toglie.
        Servono alle finestre che mostrano il risultato prima di crearlo: il documento non viene toccato."""
        self.overlay_paths = list(paths or [])
        self.viewport().update()

    def set_head(self, x, y, state="Idle", power=0.0):
        self._head.setVisible(True)
        burning = state == "Run" and power > 0
        self._head.set_active(burning)
        new = QPointF(x, -y)
        if burning and self.show_trail:
            if self._last_burn is None:
                self._trail_path.moveTo(new)
            else:
                self._trail_path.lineTo(new)
            self._last_burn = new
            self._trail_dirty = True
            if not self._trail_timer.isActive():
                self._trail_timer.start()
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

    # ---------------------------------------------------------------- 0.20.0: camera della testa
    def set_cam_center(self, x, y):
        """Punto del piano sotto il mirino della camera della testa (None = nascosto)."""
        if x is None or y is None:
            if self._cam_center.isVisible():
                self._cam_center.setVisible(False)
            return
        self._cam_center.setPos(QPointF(x, -y))
        self._cam_center.setVisible(True)

    def cam_center(self):
        if not self._cam_center.isVisible():
            return None
        q = self._cam_center.pos()
        return QPointF(q.x(), -q.y())

    def set_board(self, a, b):
        """Tavola presa da due angoli: i segni in A e B e i due lati che partono da A (lungo AB e perpendicolare)."""
        path = QPainterPath()
        if a is None and b is None:
            self._board_item.setVisible(False)
            self._board_item.setPath(path)
            return
        for c in (a, b):
            if c is not None:
                path.addEllipse(QPointF(c[0], -c[1]), 2.0, 2.0)
        if a is not None and b is not None:
            dx, dy = b[0] - a[0], b[1] - a[1]
            d = math.hypot(dx, dy)
            if d >= 1.0:
                ux, uy = dx / d, dy / d
                L = d + 40.0
                path.moveTo(a[0], -a[1])
                path.lineTo(a[0] + ux * L, -(a[1] + uy * L))
                path.moveTo(a[0], -a[1])
                path.lineTo(a[0] - uy * L, -(a[1] + ux * L))
        self._board_item.setPath(path)
        self._board_item.setVisible(True)

    def board_shown(self):
        return self._board_item.isVisible()

    def clear_trail(self):
        self._trail_path = QPainterPath()
        self._last_burn = None
        self._trail_dirty = False
        self._trail_timer.stop()
        self._trail_item.setPath(self._trail_path)

    def _flush_trail(self):
        if self._trail_dirty:
            self._trail_dirty = False
            self._trail_item.setPath(self._trail_path)

    def set_trail_shown(self, on):
        """0.20.7: scia dell'incisione accesa o spenta. Spenta non si disegna e non si raccoglie (niente lavoro)."""
        self.show_trail = bool(on)
        if not self.show_trail:
            self.clear_trail()
        self._trail_item.setVisible(self.show_trail and self._job_overlay)

    def set_job_overlay(self, on):
        """0.20.7: anteprima e scia del lavoro visibili (False mentre si guarda un altro piano senza gli altri piani)."""
        self._job_overlay = bool(on)
        self._trail_item.setVisible(self.show_trail and self._job_overlay)
        for it in self._preview_items:
            it.setVisible(self._job_overlay)

    def job_overlay_shown(self):
        return self._job_overlay

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
            it.setVisible(self._job_overlay)
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
        it.setVisible(self._job_overlay)
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
