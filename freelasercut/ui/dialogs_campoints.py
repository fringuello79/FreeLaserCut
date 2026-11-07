# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Calibrazione della camera con i punti messi a mano (0.17.5).

Dopo il bersaglio inciso (dischi da 4 mm su un cartone, a serpentina dallo zero) il riconoscimento automatico può
prendere per dischi anche macchie fuori dal cartone. Qui la persona vede la foto e mette i cerchietti sui dischi veri:
FreeLaserCut le dice quale disco cercare (numero, riga, colonna e posizione sul piano, con uno schema), aggancia il
cerchietto al centro del disco scuro più vicino e, dopo i primi quattro, trova da solo gli altri. Poi calcola la
calibrazione solo con quei punti."""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog, QGraphicsEllipseItem, QGraphicsItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .. import camera_calib as cc
from ..theme import C
from freelasercut.i18n import tr  # noqa: E402

USER, AUTO, FILL = "user", "auto", "fill"  # messo dalla persona, trovato dalla calibrazione, trovato dopo i primi 4
COLORS = {USER: "#2FBF71", AUTO: "#FF8A3D", FILL: "#FF8A3D"}


def _qimage(photo):
    img = np.ascontiguousarray(np.clip(photo, 0, 255).astype(np.uint8))
    h, w = img.shape[:2]
    return QImage(img.data, w, h, img.strides[0], QImage.Format_BGR888).copy()


class _Marker(QGraphicsEllipseItem):
    """Cerchietto numerato sulla foto: si trascina; al rilascio si aggancia al disco scuro più vicino."""

    def __init__(self, dlg, idx, r):
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.dlg, self.idx = dlg, idx
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(10)
        self.label = QGraphicsSimpleTextItem(str(idx + 1), self)
        f = QFont()
        f.setBold(True)
        f.setPointSizeF(9)
        self.label.setFont(f)
        self.label.setPos(r + 1, -r - 12)

    def style(self, kind, selected):
        col = QColor(COLORS[kind])
        pen = QPen(QColor("#E5484D") if selected else col, 3.0 if selected else 2.2)
        self.setPen(pen)
        fill = QColor(col)
        fill.setAlpha(45)
        self.setBrush(QBrush(fill))
        self.label.setBrush(QBrush(QColor("#FFFFFF")))
        self.label.setPen(QPen(QColor("#101521"), 0.6))

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.dlg.remove(self.idx)
            e.accept()
            return
        self.dlg.select(self.idx)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        p = self.pos()
        self.dlg.place(self.idx, p.x(), p.y())


class _PhotoView(QGraphicsView):
    clicked = Signal(float, float)

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._pan = None
        self.setToolTip(tr("Rotellina: ingrandisci · tasto centrale o destro trascinando: sposta la foto"))

    def wheelEvent(self, e):
        k = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale(k, k)

    def mousePressEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        if isinstance(item, (_Marker, QGraphicsSimpleTextItem)) and e.button() in (Qt.LeftButton, Qt.RightButton):
            super().mousePressEvent(e)
            return
        if e.button() in (Qt.MiddleButton, Qt.RightButton):
            self._pan = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.LeftButton:
            p = self.mapToScene(e.position().toPoint())
            self.clicked.emit(p.x(), p.y())
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan is not None:
            self._pan = None
            self.unsetCursor()
            return
        super().mouseReleaseEvent(e)


class _BedScheme(QWidget):
    """Schema del piano visto dall'alto, come in FreeLaserCut: zero davanti a sinistra. Un pallino per disco."""
    picked = Signal(int)

    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.setMinimumSize(240, 240)
        self.setToolTip(tr("Clicca un pallino per scegliere quale disco mettere sulla foto"))

    def _geom(self):
        bx, by = self.dlg.bed
        m = 28
        k = min((self.width() - 2 * m) / bx, (self.height() - 2 * m) / by)
        ox = (self.width() - bx * k) / 2
        oy = (self.height() + by * k) / 2
        return k, ox, oy

    def _pt(self, x, y):
        k, ox, oy = self._geom()
        return QPointF(ox + x * k, oy - y * k)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        bx, by = self.dlg.bed
        a, b = self._pt(0, by), self._pt(bx, 0)
        p.setPen(QPen(QColor(C["border"]), 1.2))
        p.setBrush(QColor(C["panel"]))
        p.drawRect(QRectF(a, b))
        p.setPen(QColor(C["muted"]))
        f = p.font()
        f.setPointSizeF(8)
        p.setFont(f)
        z = self._pt(0, 0)
        p.drawText(QRectF(z.x() - 26, z.y() + 2, 60, 16), Qt.AlignLeft, tr("0 (zero)"))
        p.drawText(QRectF(a.x(), b.y() + 2, b.x() - a.x(), 16), Qt.AlignHCenter, tr("davanti"))
        p.drawText(QRectF(a.x(), a.y() - 18, b.x() - a.x(), 16), Qt.AlignHCenter, tr("dietro"))
        p.setPen(QPen(QColor("#22C55E"), 2))
        p.setBrush(QColor("#22C55E"))
        p.drawEllipse(z, 3.5, 3.5)
        for i, g in enumerate(self.dlg.grid):
            c = self._pt(g[0], g[1])
            st = self.dlg.points.get(i)
            col = QColor(COLORS[st[1]]) if st else QColor(C["muted"])
            p.setPen(QPen(col, 1.5))
            p.setBrush(col if st else Qt.NoBrush)
            p.drawEllipse(c, 6, 6)
            if i == self.dlg.current:
                p.setPen(QPen(QColor("#E5484D"), 3))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, 11, 11)
        p.end()

    def mousePressEvent(self, e):
        best, bd = None, 1e9
        for i, g in enumerate(self.dlg.grid):
            c = self._pt(g[0], g[1])
            d = math.hypot(c.x() - e.position().x(), c.y() - e.position().y())
            if d < bd:
                best, bd = i, d
        if best is not None and bd < 18:
            self.picked.emit(best)


class CameraPointsDialog(QDialog):
    """photo: foto BGR del cartone con i dischi; grid: [(x, y, riga, colonna)] in ordine di incisione;
    guess: {indice: (u, v)} trovati da soli (possono essere sbagliati)."""

    def __init__(self, photo, grid, bed, guess=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Calibrazione camera: punti a mano"))
        self.photo = np.asarray(photo)
        self.grid = list(grid)
        self.bed = (float(bed[0]), float(bed[1]))
        self.frame_size = (self.photo.shape[1], self.photo.shape[0])
        self.dark = cc.darkness(self.photo)
        self.points = {i: (tuple(uv), AUTO) for i, uv in (guess or {}).items() if 0 <= i < len(self.grid)}
        self.markers = {}
        self.current = None
        self.model = None
        self.skipped = set()
        n = int(round(math.sqrt(len(self.grid))))
        self.n = n
        self.snap_r = 0.025 * max(self.frame_size)
        # ordine dei dischi da chiedere: i 4 angoli, poi gli angoli interni, poi il centro
        rc = {(g[2], g[3]): i for i, g in enumerate(self.grid)}
        order = []
        for k in range(0, n // 2):
            for r, c in ((1 + k, 1 + k), (1 + k, n - k), (n - k, n - k), (n - k, 1 + k)):
                if (r, c) in rc and rc[(r, c)] not in order:
                    order.append(rc[(r, c)])
        order += [i for i in range(len(self.grid)) if i not in order]
        self.order = order

        v = QVBoxLayout(self)
        self.guide = QLabel()
        self.guide.setWordWrap(True)
        self.guide.setTextFormat(Qt.RichText)
        v.addWidget(self.guide)
        h = QHBoxLayout()
        self.scene = QGraphicsScene(self)
        self.scene.addPixmap(QPixmap.fromImage(_qimage(self.photo)))
        self.view = _PhotoView(self.scene)
        self.view.setMinimumSize(720, 480)
        self.view.clicked.connect(self._clicked)
        h.addWidget(self.view, 1)
        side = QVBoxLayout()
        self.scheme = _BedScheme(self)
        self.scheme.picked.connect(self.select)
        side.addWidget(self.scheme)
        self.info = QLabel()
        self.info.setWordWrap(True)
        side.addWidget(self.info)
        legend = QLabel(tr("<span style='color:#2FBF71'>●</span> messo da te &nbsp; "
                           "<span style='color:#FF8A3D'>●</span> trovato da solo, da controllare &nbsp; "
                           "○ non ancora messo"))
        legend.setTextFormat(Qt.RichText)
        legend.setWordWrap(True)
        side.addWidget(legend)
        self.b_skip = QPushButton(tr("Questo disco non si vede"))
        self.b_skip.clicked.connect(self.skip)
        self.b_clear = QPushButton(tr("Togli i punti trovati da soli"))
        self.b_clear.clicked.connect(self.clear_auto)
        self.b_fill = QPushButton(tr("Trova gli altri dischi"))
        self.b_fill.setToolTip(tr("Dai dischi messi da te (almeno 4) FreeLaserCut stima dove sono gli altri e li aggancia"))
        self.b_fill.clicked.connect(self.fill)
        for b in (self.b_skip, self.b_clear, self.b_fill):
            side.addWidget(b)
        side.addStretch(1)
        self.result_lbl = QLabel()
        self.result_lbl.setWordWrap(True)
        side.addWidget(self.result_lbl)
        h.addLayout(side)
        v.addLayout(h, 1)
        bb = QHBoxLayout()
        bb.addStretch(1)
        self.b_cancel = QPushButton(tr("Annulla"))
        self.b_cancel.clicked.connect(self.reject)
        self.b_ok = QPushButton(tr("Calcola e usa la calibrazione"))
        self.b_ok.setObjectName("primary")
        self.b_ok.clicked.connect(self.compute)
        bb.addWidget(self.b_cancel)
        bb.addWidget(self.b_ok)
        v.addLayout(bb)
        self.resize(1180, 760)
        for i in self.points:
            self._marker(i)
        self._next()
        self.refresh()

    # ---------------------------------------------------------------- stato
    def user_count(self):
        return sum(1 for _, k in self.points.values() if k == USER)

    def _next(self):
        """Prossimo disco da chiedere: nell'ordine (angoli prima) il primo non messo da te e non saltato."""
        if self.user_count() >= 4 and any(k == FILL for _, k in self.points.values()):
            self.current = None
            return
        for i in self.order:
            if i not in self.skipped and self.points.get(i, (None, None))[1] != USER:
                self.current = i
                return
        self.current = None

    def select(self, idx):
        self.current = idx
        self.refresh()

    def _marker(self, idx):
        m = self.markers.get(idx)
        if m is None:
            m = _Marker(self, idx, 9)
            self.scene.addItem(m)
            self.markers[idx] = m
        uv, kind = self.points[idx]
        m.setPos(QPointF(*uv))
        return m

    def place(self, idx, u, v, snap=True):
        """Mette (o sposta) il cerchietto del disco idx in (u, v) della foto, agganciato al disco scuro vicino."""
        if snap:
            s = cc.snap_dark(self.dark, u, v, self.snap_r)
            if s is not None:
                u, v = s
        self.points[idx] = ((float(u), float(v)), USER)
        self.skipped.discard(idx)
        self._marker(idx)
        self.model = None
        if self.current == idx or self.current is None:
            self._next()
            if self.user_count() >= 4 and not any(k == FILL for _, k in self.points.values()):
                self.fill()
                return
        self.refresh()

    def remove(self, idx):
        self.points.pop(idx, None)
        m = self.markers.pop(idx, None)
        if m is not None:
            self.scene.removeItem(m)
        self.model = None
        self.current = idx
        self.refresh()

    def skip(self):
        if self.current is not None:
            self.skipped.add(self.current)
            if self.points.get(self.current, (None, None))[1] != USER:
                self.remove(self.current)
            self.current = None
        self._next()
        self.refresh()

    def clear_auto(self):
        for i in [i for i, (_, k) in self.points.items() if k != USER]:
            self.points.pop(i)
            m = self.markers.pop(i, None)
            if m is not None:
                self.scene.removeItem(m)
        self.model = None
        self._next()
        self.refresh()

    def fill(self):
        known = {i: uv for i, (uv, k) in self.points.items() if k == USER}
        if len(known) < 4:
            self.result_lbl.setText(tr("Metti prima almeno 4 dischi, possibilmente lontani fra loro (gli angoli)."))
            return 0
        for i in [i for i, (_, k) in self.points.items() if k != USER]:
            self.points.pop(i)
            m = self.markers.pop(i, None)
            if m is not None:
                self.scene.removeItem(m)
        found = cc.fill_from_anchors(self.dark, self.grid, known, self.frame_size)
        for i, uv in found.items():
            if i not in self.skipped:
                self.points[i] = (uv, FILL)
                self._marker(i)
        self.model = None
        self.current = None
        self.refresh()
        return len(found)

    def _clicked(self, u, v):
        if self.current is None:
            self.result_lbl.setText(tr("Scegli prima quale disco mettere: clicca il suo pallino nello schema a destra."))
            return
        self.place(self.current, u, v)

    # ---------------------------------------------------------------- testo
    def refresh(self):
        for i, m in self.markers.items():
            m.style(self.points[i][1], i == self.current)
        n_user = self.user_count()
        n_all = len(self.points)
        if self.current is not None:
            x, y, r, c = self.grid[self.current]
            where = []
            where.append(tr("davanti") if r == 1 else tr("dietro") if r == self.n else "")
            where.append(tr("a sinistra") if c == 1 else tr("a destra") if c == self.n else "")
            corner = " ".join(w for w in where if w)
            self.guide.setText(
                tr("<b>Metti il cerchietto n° {0}</b>: clicca sulla foto al centro di quel disco inciso.<br>"
                   "È il {0}° disco inciso: riga {1} contando dallo zero (davanti), colonna {2} da sinistra, sul piano "
                   "a X {3:.0f} Y {4:.0f} mm{5}. Il cerchietto si aggancia da solo al centro del disco.",
                   self.current + 1, r, c, x, y, (" · " + tr("angolo {0}", corner)) if corner else "")
                + "<br><span style='color:%s'>" % C["muted"]
                + tr("Se quel disco non si vede nella foto premi «Questo disco non si vede». Puoi scegliere un altro "
                     "disco cliccando il suo pallino nello schema.") + "</span>")
        elif n_user >= 4:
            self.guide.setText(tr("<b>Controlla i cerchietti arancioni</b>: devono stare sui dischi incisi. Trascina "
                                  "quelli fuori posto, tasto destro per toglierne uno. Poi premi «Calcola e usa la "
                                  "calibrazione»."))
        else:
            self.guide.setText(tr("Scegli un disco nello schema a destra e mettilo sulla foto."))
        self.info.setText(tr("Dischi messi da te: {0} · in tutto: {1} di {2} (ne servono almeno 9)", n_user, n_all,
                             len(self.grid)))
        self.b_fill.setEnabled(n_user >= 4)
        self.b_ok.setEnabled(n_all >= 9)
        self.b_skip.setEnabled(self.current is not None)
        self.b_clear.setEnabled(any(k != USER for _, k in self.points.values()))
        self.scheme.update()

    # ---------------------------------------------------------------- calcolo
    def pairs(self):
        return [(self.grid[i][:2], uv) for i, (uv, _k) in sorted(self.points.items())]

    def compute(self):
        pairs = self.pairs()
        if len(pairs) < 9:
            return None
        bp = [p[0] for p in pairs]
        try:
            model = cc.fit_with_validation(bp, [p[1] for p in pairs], self.bed, self.frame_size)
        except (ValueError, np.linalg.LinAlgError) as exc:
            self.result_lbl.setText(tr("Calcolo non riuscito: {0}", exc))
            return None
        cc.limit_to_points(model, bp, *self.bed)
        self.model = model
        if model.rms_mm > 1.5:
            # quasi sempre un cerchietto sul disco sbagliato: lo indico (il punto che si discosta di più)
            worst = self._worst()
            if worst is not None:
                self.current = worst
                self.refresh()
            self.result_lbl.setText(tr("Precisione ±{0:.2f} mm: troppo poca, probabilmente un cerchietto è sul disco "
                                   "sbagliato (in rosso il più sospetto). Correggilo e riprova.", model.rms_mm))
            self.model = None
            return None
        self.accept()
        return model

    def _worst(self, model=None):
        """Il cerchietto più sospetto: il più lontano dalla prospettiva che mettono d'accordo quasi tutti gli altri."""
        import cv2

        idx = sorted(self.points)
        if len(idx) < 5:
            return None
        G = np.float32([self.grid[i][:2] for i in idx])
        P = np.float32([self.points[i][0] for i in idx])
        H, _ = cv2.findHomography(G, P, cv2.RANSAC, 0.015 * math.hypot(*self.frame_size))
        if H is None:
            return None
        pred = cv2.perspectiveTransform(G.reshape(-1, 1, 2), H).reshape(-1, 2)
        err = np.linalg.norm(pred - P, axis=1)
        return idx[int(np.argmax(err))]

    def showEvent(self, e):
        super().showEvent(e)
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)
