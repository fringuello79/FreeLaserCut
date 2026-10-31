# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Piano di lavoro: griglia in mm, anteprima G-code, testa laser in tempo reale,
traccia di ciò che è stato inciso, zoom, doppio clic = vai qui."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QLabel,
)

from .theme import C
from freelasercut.i18n import tr  # noqa: E402

BURN = "#FF8A3D"


def _pen(color, width=1.0, style=Qt.SolidLine, alpha=255):
    col = QColor(color)
    col.setAlpha(alpha)
    p = QPen(col, width, style)
    p.setCosmetic(True)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


class BedView(QGraphicsView):
    """Coordinate scena: x = mm, y = -mm (origine in basso a sinistra, come la macchina)."""

    jog_requested = Signal(float, float)
    goto_requested = Signal(float, float)

    def __init__(self, bed_x=450.0, bed_y=440.0, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QColor(C["bg"]))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.step_provider = lambda: 10.0
        self._user_zoomed = False
        self._head = None
        self._trail_path = QPainterPath()
        self._trail_item = None
        self._last_burn = None
        self._preview_items = []
        self.cursor_label = QLabel(self)
        self.cursor_label.setStyleSheet(
            f"color: {C['muted']}; background: rgba(12,19,34,0.88); border: 1px solid {C['border']};"
            " border-radius: 6px; padding: 4px 8px;"
        )
        self.cursor_label.hide()
        self.hint_label = QLabel(tr("Doppio clic: porta la testa lì   ·   Frecce: jog   ·   Rotella: zoom   ·   Home: adatta"), self)
        self.hint_label.setStyleSheet(f"color: {C['muted']}; background: transparent; font-size: 9pt;")
        self.set_bed(bed_x, bed_y)

    # ---------------------------------------------------------------- disegno
    def set_bed(self, bed_x, bed_y):
        self.bed_x, self.bed_y = float(bed_x), float(bed_y)
        sc = self.scene()
        sc.clear()
        self._preview_items = []
        margin = 40
        sc.setSceneRect(QRectF(-margin, -self.bed_y - margin, self.bed_x + 2 * margin, self.bed_y + 2 * margin))
        bed = QGraphicsRectItem(0, -self.bed_y, self.bed_x, self.bed_y)
        bed.setBrush(QBrush(QColor(C["bed"])))
        bed.setPen(_pen(C["grid_major"], 1.5))
        bed.setZValue(-3)
        sc.addItem(bed)
        self._cam_item = None
        minor, major = QPainterPath(), QPainterPath()
        for i in range(10, int(self.bed_x), 10):
            p = major if i % 50 == 0 else minor
            p.moveTo(i, 0)
            p.lineTo(i, -self.bed_y)
        for j in range(10, int(self.bed_y), 10):
            p = major if j % 50 == 0 else minor
            p.moveTo(0, -j)
            p.lineTo(self.bed_x, -j)
        self._grid_items = []
        for path, col in ((minor, C["grid"]), (major, C["grid_major"])):
            it = QGraphicsPathItem(path)
            it.setPen(_pen(col, 1))
            sc.addItem(it)
            self._grid_items.append(it)
        font = QFont("Segoe UI", 8)
        for i in range(0, int(self.bed_x) + 1, 50):
            self._label(str(i), i, 0, font, below=True)
        for j in range(50, int(self.bed_y) + 1, 50):
            self._label(str(j), 0, -j, font, below=False)
        dim = QGraphicsSimpleTextItem(tr("Area di lavoro  ·  {0:g} × {1:g} mm", self.bed_x, self.bed_y))
        dim.setFont(QFont("Segoe UI", 9))
        dim.setBrush(QColor(C["muted"]))
        dim.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        dim.setPos(0, -self.bed_y - 24)
        sc.addItem(dim)
        o = QGraphicsEllipseItem(-4, -4, 8, 8)
        o.setBrush(QColor(C["success"]))
        o.setPen(_pen(C["success"]))
        o.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        o.setToolTip(tr("Origine macchina"))
        sc.addItem(o)
        self._trail_path = QPainterPath()
        self._trail_item = QGraphicsPathItem()
        self._trail_item.setPen(_pen(BURN, 2.2))
        self._trail_item.setZValue(50)
        sc.addItem(self._trail_item)
        self._last_burn = None
        self._head = _Head()
        sc.addItem(self._head)
        self._head.setVisible(False)
        self._fit()

    def _label(self, text, x, y, font, below):
        t = QGraphicsSimpleTextItem(text)
        t.setFont(font)
        t.setBrush(QColor(C["muted"]))
        t.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        t.setPos(x - (4 if below else 24), y + (5 if below else -7))
        self.scene().addItem(t)

    # ---------------------------------------------------------------- foto camera
    def set_camera_image(self, qimage, px_per_mm, opacity=0.85):
        """Foto raddrizzata (vista dall'alto, 1:1) disegnata sotto la griglia."""
        pix = QPixmap.fromImage(qimage)
        if self._cam_item is None:
            self._cam_item = QGraphicsPixmapItem()
            self._cam_item.setZValue(-2)
            self._cam_item.setTransformationMode(Qt.SmoothTransformation)
            self.scene().addItem(self._cam_item)
        self._cam_item.setPixmap(pix)
        self._cam_item.setScale(1.0 / px_per_mm)
        self._cam_item.setPos(0, -self.bed_y)
        self._cam_item.setOpacity(opacity)
        for it in self._grid_items:
            it.setOpacity(0.28)  # griglia discreta sopra la foto

    def set_camera_opacity(self, opacity):
        if self._cam_item is not None:
            self._cam_item.setOpacity(opacity)

    def clear_camera(self):
        if self._cam_item is not None:
            self.scene().removeItem(self._cam_item)
            self._cam_item = None
        for it in self._grid_items:
            it.setOpacity(1.0)

    # ---------------------------------------------------------------- anteprima
    def set_preview(self, pv, offset=(0.0, 0.0)):
        self.clear_preview()
        if pv is None or not pv.has_bounds and not pv.travel:
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
        t_item = QGraphicsPathItem(travel)
        t_item.setPen(_pen(C["muted"], 1, Qt.DashLine, alpha=90))
        c_item = QGraphicsPathItem(cut)
        c_item.setPen(_pen(C["accent_hi"], 1.4, alpha=230))
        items = [t_item, c_item]
        if pv.has_bounds:
            box = QGraphicsRectItem(pv.min_x, -pv.max_y, pv.width, pv.height)
            box.setPen(_pen(C["accent"], 1, Qt.DashLine, alpha=200))
            items.append(box)
        for it in items:
            it.setZValue(20)
            self.scene().addItem(it)
        self._preview_items = items
        self.set_preview_offset(offset)

    def set_preview_offset(self, offset):
        for it in self._preview_items:
            it.setPos(offset[0], -offset[1])

    def clear_preview(self):
        for it in self._preview_items:
            self.scene().removeItem(it)
        self._preview_items = []

    # ---------------------------------------------------------------- stato
    def set_head(self, x, y, state="Idle", power=0.0):
        if self._head is None:
            return
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

    def clear_trail(self):
        self._trail_path = QPainterPath()
        self._last_burn = None
        if self._trail_item:
            self._trail_item.setPath(self._trail_path)

    def hide_head(self):
        if self._head:
            self._head.setVisible(False)

    # ---------------------------------------------------------------- vista
    def _fit(self):
        r = QRectF(-34, -self.bed_y - 38, self.bed_x + 60, self.bed_y + 66)
        self.fitInView(r, Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._user_zoomed:
            self._fit()
        self.hint_label.adjustSize()
        self.hint_label.move(14, self.height() - self.hint_label.height() - 10)
        self.cursor_label.move(14, 12)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._user_zoomed:
            self._fit()

    def wheelEvent(self, event):
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        self.scale(factor, factor)
        self._user_zoomed = True

    def reset_zoom(self):
        self._user_zoomed = False
        self.resetTransform()
        self._fit()

    def leaveEvent(self, event):
        self.cursor_label.hide()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        p = self.mapToScene(event.position().toPoint())
        x, y = p.x(), -p.y()
        if 0 <= x <= self.bed_x and 0 <= y <= self.bed_y:
            self.cursor_label.setText(tr("X {0:7.1f}    Y {1:7.1f}  mm", x, y))
        else:
            self.cursor_label.setText(tr("fuori dall'area di lavoro"))
        self.cursor_label.adjustSize()
        self.cursor_label.show()
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        p = self.mapToScene(event.position().toPoint())
        x, y = p.x(), -p.y()
        if 0 <= x <= self.bed_x and 0 <= y <= self.bed_y:
            self.goto_requested.emit(round(x, 2), round(y, 2))

    def keyPressEvent(self, event):
        step = self.step_provider()
        moves = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, step), Qt.Key_Down: (0, -step)}
        if event.key() in moves and not event.isAutoRepeat():
            self.jog_requested.emit(*moves[event.key()])
            return
        if event.key() == Qt.Key_Home:
            self.reset_zoom()
            return
        super().keyPressEvent(event)


class _Head(QGraphicsItem):
    """Mirino della testa laser, dimensione fissa a schermo; arancione quando incide."""

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(100)
        self._active = False

    def set_active(self, active):
        if active != self._active:
            self._active = active
            self.update()

    def boundingRect(self):
        return QRectF(-17, -17, 34, 34)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(BURN) if self._active else QColor(C["accent_hi"])
        glow = QColor(color)
        glow.setAlpha(70)
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(0, 0), 14, 14)
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(0, 0), 7, 7)
        for a, b in (((-16, 0), (-10, 0)), ((10, 0), (16, 0)), ((0, -16), (0, -10)), ((0, 10), (0, 16))):
            painter.drawLine(QPointF(*a), QPointF(*b))
        painter.setBrush(color)
        painter.drawEllipse(QPointF(0, 0), 2, 2)
