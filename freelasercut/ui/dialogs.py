# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Finestre di dialogo: anteprima/simulazione, offset, serie a griglia e circolare, esito verifica, ripresa."""
import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGraphicsPathItem,
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QListWidget, QPushButton, QRadioButton,
    QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from .. import gcode_preview
from ..core import render as renderer
from ..theme import C
from . import style
from .widgets import row, section
from freelasercut.i18n import tr  # noqa: E402


def _buttons(dlg, ok="OK"):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(ok)
    bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


def _dspin(lo, hi, val, dec=2, step=1.0, suffix=""):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(dec)
    w.setSingleStep(step)
    w.setValue(val)
    w.setSuffix(suffix)
    return w


class OffsetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Offset forme"))
        f = QFormLayout(self)
        self.dist = _dspin(0.01, 500, 2.0, 2, 0.5, " mm")
        f.addRow(tr("Distanza"), self.dist)
        self.direction = QComboBox()
        for k, lab in (("out", tr("Verso l'esterno")), ("in", tr("Verso l'interno")), ("both", tr("Entrambi"))):
            self.direction.addItem(lab, k)
        f.addRow(tr("Direzione"), self.direction)
        self.corner = QComboBox()
        for k, lab in (("round", tr("Arrotondati")), ("miter", tr("Vivi")), ("square", tr("Smussati"))):
            self.corner.addItem(lab, k)
        f.addRow(tr("Angoli"), self.corner)
        self.outer = QCheckBox(tr("Solo i contorni esterni (ignora i fori)"))
        f.addRow("", self.outer)
        self.keep = QCheckBox(tr("Mantieni l'originale"))
        self.keep.setChecked(True)
        f.addRow("", self.keep)
        f.addRow(_buttons(self, tr("Crea offset")))

    def values(self):
        return (self.dist.value(), self.direction.currentData(), self.corner.currentData(), self.keep.isChecked(),
                self.outer.isChecked())


class GridArrayDialog(QDialog):
    def __init__(self, sel_size, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Serie a griglia"))
        f = QFormLayout(self)
        self.cols = QSpinBox()
        self.cols.setRange(1, 500)
        self.cols.setValue(3)
        self.rows = QSpinBox()
        self.rows.setRange(1, 500)
        self.rows.setValue(2)
        f.addRow(tr("Colonne"), self.cols)
        f.addRow(tr("Righe"), self.rows)
        self.mode = QComboBox()
        self.mode.addItem(tr("Spazio fra i bordi"), "gap")
        self.mode.addItem(tr("Passo fra i centri"), "center")
        f.addRow(tr("Misura"), self.mode)
        self.dx = _dspin(-1000, 1000, 5.0, 2, 1, " mm")
        self.dy = _dspin(-1000, 1000, 5.0, 2, 1, " mm")
        f.addRow(tr("Orizzontale"), self.dx)
        f.addRow(tr("Verticale"), self.dy)
        self.shift = _dspin(-500, 500, 0.0, 2, 1, " mm")
        f.addRow(tr("Sfalsa righe dispari"), self.shift)
        self.mirror = QCheckBox(tr("Rifletti a scacchiera"))
        f.addRow("", self.mirror)
        self.group = QCheckBox(tr("Raggruppa il risultato"))
        f.addRow("", self.group)
        self.total = QLabel()
        self.total.setObjectName("muted")
        f.addRow("", self.total)
        w, h = sel_size

        def upd():
            g = self.mode.currentData() == "gap"
            tw = self.cols.value() * (w if g else 0) + (self.cols.value() - 1) * self.dx.value() + (0 if g else w)
            th = self.rows.value() * (h if g else 0) + (self.rows.value() - 1) * self.dy.value() + (0 if g else h)
            self.total.setText(tr("{0} copie · ingombro {1:.1f} × {2:.1f} mm", self.cols.value() * self.rows.value(), tw, th))
        for x in (self.cols, self.rows):
            x.valueChanged.connect(upd)
        for x in (self.dx, self.dy):
            x.valueChanged.connect(upd)
        self.mode.currentIndexChanged.connect(upd)
        upd()
        f.addRow(_buttons(self, tr("Crea")))

    def values(self):
        return (self.cols.value(), self.rows.value(), self.dx.value(), self.dy.value(), self.mode.currentData(),
                self.shift.value(), self.mirror.isChecked(), self.group.isChecked())


class CircularArrayDialog(QDialog):
    def __init__(self, center, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Serie circolare"))
        f = QFormLayout(self)
        self.count = QSpinBox()
        self.count.setRange(2, 1000)
        self.count.setValue(8)
        f.addRow(tr("Numero di copie (totale)"), self.count)
        self.cx = _dspin(-2000, 2000, center[0], 2, 1, " mm")
        self.cy = _dspin(-2000, 2000, center[1], 2, 1, " mm")
        f.addRow(tr("Centro X"), self.cx)
        f.addRow(tr("Centro Y"), self.cy)
        self.start = _dspin(-360, 360, 0, 1, 15, " °")
        self.end = _dspin(-360, 360, 360, 1, 15, " °")
        f.addRow(tr("Da"), self.start)
        f.addRow("A", self.end)
        self.rot = QCheckBox(tr("Ruota le copie seguendo il cerchio"))
        self.rot.setChecked(True)
        f.addRow("", self.rot)
        self.group = QCheckBox(tr("Raggruppa il risultato"))
        f.addRow("", self.group)
        f.addRow(_buttons(self, tr("Crea")))

    def values(self):
        return (self.count.value(), (self.cx.value(), self.cy.value()), self.start.value(), self.end.value(),
                self.rot.isChecked(), self.group.isChecked())


class CheckResultDialog(QDialog):
    """Esito della verifica: elenco delle righe rifiutate dalla scheda, con spiegazione."""

    def __init__(self, errors, total_lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Verifica del lavoro"))
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        if not errors:
            lab = QLabel(tr("<b style='color:{0}'>✓ Nessun errore.</b><br>La scheda ha controllato tutte le {1} righe del lavoro senza muoversi: il G-code è valido per la tua macchina.", C['success'], total_lines))
        else:
            lab = QLabel(tr("<b style='color:{0}'>✕ La scheda ha rifiutato {1} righe.</b><br>Il lavoro non è stato avviato. Righe rifiutate:", C['danger'], len(errors)))
            alarm = next((e for e in errors if isinstance(e[2], str)), None)
            if alarm is not None and alarm[2] == "NO_RISPOSTA":
                lab = QLabel(tr("<b style='color:{0}'>✕ La verifica si è fermata: la scheda ha smesso di rispondere.</b><br>"
                                "Il lavoro non è stato avviato. {1}", C['danger'], alarm[3]))
            elif alarm is not None:
                why = (tr("La riga porterebbe la testa fuori dalla corsa impostata nella scheda ($130/$131): "
                          "sposta il disegno o l'origine.") if alarm[2] == "ALARM:2" else "")
                lab = QLabel(tr("<b style='color:{0}'>✕ La verifica si è fermata: la scheda è andata in allarme alla riga {1}.</b><br>"
                                "Il lavoro non è stato avviato e le righe successive non sono state controllate. {2}<br>"
                                "Prima di continuare sblocca la macchina (o fai l'homing).", C['danger'], alarm[0] + 1, why))
        lab.setWordWrap(True)
        v.addWidget(lab)
        if errors:
            lst = QListWidget()
            for i, line, code, text in errors[:500]:
                if code == "NO_RISPOSTA":
                    lst.addItem(text)
                elif isinstance(code, str):  # allarme (es. "ALARM:2")
                    lst.addItem(tr("riga {0}:  {1}    →  {2} {3}", i + 1, line, code, text))
                else:
                    lst.addItem(tr("riga {0}:  {1}    →  error:{2} {3}", i + 1, line, code, text))
            lst.setFont(style.mono_font(9))
            v.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)


class ZoomView(QGraphicsView):
    """Vista dell'anteprima: si adatta da sola alla finestra finché non zoomi; rotella = zoom verso il cursore,
    trascina = sposta, doppio clic o tasto 0 = adatta di nuovo."""

    zoomed = None  # callback(fattore %) impostata dal dialogo

    def __init__(self):
        super().__init__()
        self.auto_fit = True
        self.fit_rect = None
        # ancoraggio fatto a mano in zoom(): AnchorUnderMouse di Qt usa l'ultimo movimento del mouse "visto"
        # dalla vista, che con la sola rotella può essere vecchio, e lo zoom scappava da un'altra parte
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)

    def fit(self):
        if self.fit_rect is None or self.viewport().width() < 10:
            return
        self.fitInView(self.fit_rect, Qt.KeepAspectRatio)
        self.auto_fit = True
        self._notify()

    def zoom(self, k, at=None):
        """Zoom di un fattore k tenendo fermo il punto 'at' della vista (pixel); None = centro della vista."""
        cur = self.transform().m11()
        lo = self._fit_scale() * 0.25
        k = max(lo / cur, min(k, 400.0 / cur))  # fra 1/4 della vista intera e 400 px per mm
        if at is None:
            at = self.viewport().rect().center()
        before = self.mapToScene(at)
        self.scale(k, k)
        # riporto sotto il cursore il punto della scena che c'era prima
        d = self.mapFromScene(before) - at
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + d.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + d.y())
        self.auto_fit = False
        self._notify()

    def _fit_scale(self):
        if self.fit_rect is None or self.fit_rect.width() <= 0:
            return 1.0
        vp = self.viewport().rect()
        return min(vp.width() / self.fit_rect.width(), vp.height() / self.fit_rect.height())

    def _notify(self):
        if self.zoomed is not None:
            self.zoomed(self.transform().m11() / max(self._fit_scale(), 1e-9) * 100)

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if d:
            self.zoom(1.0018 ** d, e.position().toPoint())
        e.accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.auto_fit:
            self.fit()

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_0, Qt.Key_Home):
            self.fit()
        elif e.key() in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom(1.25)
        elif e.key() == Qt.Key_Minus:
            self.zoom(0.8)
        else:
            super().keyPressEvent(e)


class PreviewDialog(QDialog):
    """Simulazione del lavoro: percorsi colorati per potenza, cursore temporale, resa realistica sul materiale."""

    def __init__(self, pv, job, profile, bed, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Anteprima del lavoro"))
        # grande quanto lo schermo (90%), centrata: il lavoro si adatta alla finestra
        from PySide6.QtGui import QGuiApplication

        scr = (parent.screen() if parent is not None else None) or QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            w, h = int(g.width() * 0.9), int(g.height() * 0.9)
            self.resize(w, h)
            self.move(g.left() + (g.width() - w) // 2, g.top() + (g.height() - h) // 2)
        else:
            self.resize(1180, 820)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.pv, self.job, self.profile = pv, job, profile
        self.bed = bed
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.r_lines = QRadioButton(tr("Percorsi"))
        self.r_real = QRadioButton(tr("Resa realistica"))
        self.r_lines.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.r_lines)
        grp.addButton(self.r_real)
        self.material = QComboBox()
        for m in renderer.MATERIALS:
            self.material.addItem(m.capitalize(), m)
        self.travel = QCheckBox(tr("Mostra trasferimenti"))
        self.travel.setChecked(True)
        top.addWidget(self.r_lines)
        top.addWidget(self.r_real)
        top.addWidget(QLabel(tr("Materiale")))
        top.addWidget(self.material)
        top.addWidget(self.travel)
        top.addStretch(1)
        self.zoom_lbl = QLabel("")
        self.zoom_lbl.setObjectName("muted")
        self.zoom_lbl.setToolTip(tr("Rotella = zoom verso il cursore · trascina = sposta · doppio clic o 0 = adatta"))
        top.addWidget(self.zoom_lbl)
        fit_btn = QPushButton(style.icon("fit"), tr("Adatta"))
        fit_btn.setToolTip(tr("Adatta il lavoro alla finestra (doppio clic sulla vista o tasto 0)"))
        top.addWidget(fit_btn)
        self.stats = QLabel()
        self.stats.setObjectName("muted")
        top.addWidget(self.stats)
        v.addLayout(top)
        self.view = ZoomView()
        self.view.zoomed = lambda pct: self.zoom_lbl.setText(tr("zoom {0:.0f}%", pct))
        fit_btn.clicked.connect(self.view.fit)
        self.view.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.view.setBackgroundBrush(QColor(C["bg"]))
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)
        v.addWidget(self.view, 1)
        bottom = QHBoxLayout()
        self.play = QPushButton()
        self.play.setIcon(style.icon("play"))
        self.play.setCheckable(True)
        self.play.toggled.connect(self._play)
        self.speed = QComboBox()
        for k in (1, 5, 20, 100, 500):
            self.speed.addItem(f"{k}×", k)
        self.speed.setCurrentIndex(2)
        self.slider = QSlider(Qt.Horizontal)
        n = len(pv.segs)
        self.slider.setRange(0, max(n, 1))
        self.slider.setValue(max(n, 1))
        self.slider.valueChanged.connect(self._seek)
        self.time = QLabel()
        self.time.setFont(style.mono_font(9.5))
        bottom.addWidget(self.play)
        bottom.addWidget(self.speed)
        bottom.addWidget(self.slider, 1)
        bottom.addWidget(self.time)
        v.addLayout(bottom)
        self.cum = np.cumsum(np.asarray(pv.seg_times, float)) if len(pv.seg_times) == n and n else np.zeros(n)
        self._build_paths()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._real_item = None
        self.r_real.toggled.connect(self._mode)
        self.material.currentIndexChanged.connect(lambda _: self._mode())
        self.travel.toggled.connect(lambda x: [it.setVisible(x and self.r_lines.isChecked()) for it in self.travel_items])
        total = pv.seconds
        self.stats.setText(tr("Totale {0} · inciso {1:.2f} m · trasferimenti {2:.2f} m", _fmt(total), pv.cut_len / 1000, pv.travel_len / 1000))
        self._seek(self.slider.value())
        QTimer.singleShot(0, self._fit)

    def _fit(self):
        b = self.pv
        r = QRectF(b.min_x, -b.max_y, max(b.width, 1), max(b.height, 1)) if b.has_bounds else QRectF(0, -self.bed[1], *self.bed)
        m = max(r.width(), r.height()) * 0.04 + 2  # margine proporzionale al lavoro
        self.view.fit_rect = r.adjusted(-m, -m, m, m)
        bed = QRectF(0, -self.bed[1], self.bed[0], self.bed[1])
        big = max(self.bed) * 0.5
        self.scene.setSceneRect(bed.united(r).adjusted(-big, -big, big, big))  # spazio per spostarsi liberamente
        self.view.fit()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._fit)  # a finestra mostrata le misure della vista sono quelle vere

    def _build_paths(self):
        """Percorsi in blocchi: il cursore mostra/nasconde blocchi interi (veloce anche con 1 milione di tratti)."""
        segs = self.pv.segs
        n = len(segs)
        self.chunk = max(1, n // 400)
        bed = QGraphicsPathItem()
        bp = QPainterPath()
        bp.addRect(QRectF(0, -self.bed[1], self.bed[0], self.bed[1]))
        bed.setPath(bp)
        pen = QPen(QColor(C["grid_major"]), 1)
        pen.setCosmetic(True)
        bed.setPen(pen)
        bed.setBrush(QColor(C["bed"]))
        self.scene.addItem(bed)
        s_max = max(self.profile.s_max, 1)
        self.cut_items, self.travel_items = [], []
        self._rast = None
        if n > gcode_preview.BIG:
            self._build_raster(s_max)
            n = 0  # nessun tratto vettoriale
        for k in range(0, n, self.chunk):
            cut = QPainterPath()
            trav = QPainterPath()
            last_c = last_t = None
            levels = {}
            for (x0, y0, x1, y1, pw, b, f) in segs[k:k + self.chunk]:
                if b:
                    lvl = min(int(pw / s_max * 8), 8)
                    p = levels.setdefault(lvl, QPainterPath())
                    p.moveTo(x0, -y0)
                    p.lineTo(x1, -y1)
                else:
                    if last_t != (x0, y0):
                        trav.moveTo(x0, -y0)
                    trav.lineTo(x1, -y1)
                    last_t = (x1, y1)
            items = []
            for lvl, p in levels.items():
                it = QGraphicsPathItem(p)
                col = QColor.fromHsvF(0.08, 0.85, 0.35 + 0.65 * lvl / 8)
                pen = QPen(col, 1.2)
                pen.setCosmetic(True)
                it.setPen(pen)
                self.scene.addItem(it)
                items.append(it)
            ti = QGraphicsPathItem(trav)
            pen = QPen(QColor(C["muted"]), 1, Qt.DashLine)
            pen.setCosmetic(True)
            ti.setPen(pen)
            ti.setOpacity(0.5)
            self.scene.addItem(ti)
            self.cut_items.append(items)
            self.travel_items.append(ti)
        self.head = self.scene.addEllipse(-4, -4, 8, 8, QPen(QColor("#FFFFFF"), 1.5), QColor(C["accent"]))
        self.head.setFlag(self.head.GraphicsItemFlag.ItemIgnoresTransformations)
        self.head.setZValue(100)

    def _build_raster(self, s_max):
        """Lavori enormi (foto): i percorsi diventano un'immagine; il cursore del tempo mostra i pixel
        bruciati fino al tratto scelto. Con milioni di tratti vettoriali la finestra si bloccava."""
        r = gcode_preview.rasterize(self.pv.segs, px_per_mm=8.0, max_px=2400, s_max=s_max)
        self.travel.setChecked(False)
        self.travel.setEnabled(False)
        self.travel.setToolTip(tr("Con lavori molto grandi (foto) i trasferimenti non si mostrano"))
        if r is None:
            return
        power, index, (x0, y0, w, h) = r
        v = (0.35 + 0.65 * power)[..., None] * np.float32([255, 142, 38])  # stessa tinta dei percorsi
        ny, nx = power.shape
        self._rast = {"rgb": v.astype(np.uint8), "index": index, "k": None, "nx": nx, "ny": ny}
        it = QGraphicsPixmapItem()
        it.setTransformationMode(Qt.SmoothTransformation)
        it.setScale(w / nx)
        it.setPos(x0, -(y0 + h))
        it.setZValue(5)
        self.scene.addItem(it)
        self._rast["item"] = it

    def _show_raster(self, k, visible):
        R = self._rast
        if R is None:
            return
        R["item"].setVisible(visible)
        if not visible or R["k"] == k:
            return
        R["k"] = k
        idx = R["index"]
        rgba = np.empty((R["ny"], R["nx"], 4), np.uint8)
        rgba[..., :3] = R["rgb"]
        rgba[..., 3] = np.where((idx >= 0) & (idx < k), 255, 0).astype(np.uint8)
        qi = QImage(rgba.data, R["nx"], R["ny"], 4 * R["nx"], QImage.Format_RGBA8888).copy()
        R["item"].setPixmap(QPixmap.fromImage(qi))

    def _seek(self, k):
        n = len(self.pv.segs)
        c_upto = k // self.chunk
        real = self.r_real.isChecked()
        self._show_raster(k, not real)
        for i, items in enumerate(self.cut_items):
            vis = i <= c_upto and not real
            for it in items:
                it.setVisible(vis)
            self.travel_items[i].setVisible(vis and self.travel.isChecked())
        if n and k > 0:
            s = self.pv.segs[min(k, n) - 1]
            self.head.setPos(s[2], -s[3])
            t = float(self.cum[min(k, n) - 1]) if len(self.cum) else 0.0
        else:
            t = 0.0
        self.time.setText(f"{_fmt(t)} / {_fmt(self.pv.seconds)}")
        if real and not self.play.isChecked():
            self._render_real(k)

    def _mode(self):
        if self.r_real.isChecked():
            self._render_real(self.slider.value())
        elif self._real_item is not None:
            self.scene.removeItem(self._real_item)
            self._real_item = None
        self._seek(self.slider.value())

    def _render_real(self, k):
        img, rect = renderer.render(self.pv, self.profile.s_max, self.material.currentData(), upto=k or None)
        if self._real_item is not None:
            self.scene.removeItem(self._real_item)
            self._real_item = None
        if img is None:
            return
        h, w, _ = img.shape
        qi = QImage(np.ascontiguousarray(img).data, w, h, 3 * w, QImage.Format_RGB888).copy()
        it = QGraphicsPixmapItem(QPixmap.fromImage(qi))
        it.setTransformationMode(Qt.SmoothTransformation)
        x0, y0, W, H = rect
        it.setScale(W / w)
        it.setPos(x0, -(y0 + H))
        it.setZValue(10)
        self.scene.addItem(it)
        self._real_item = it

    def _play(self, on):
        self.play.setIcon(style.icon("pause" if on else "play"))
        if on:
            if self.slider.value() >= self.slider.maximum():
                self.slider.setValue(0)
            self._t_play = time.time()
            self._sim_t = float(self.cum[self.slider.value() - 1]) if self.slider.value() > 0 and len(self.cum) else 0.0
            self._timer.start(33)
        else:
            self._timer.stop()
            if self.r_real.isChecked():
                self._render_real(self.slider.value())

    def _tick(self):
        now = time.time()
        self._sim_t += (now - self._t_play) * self.speed.currentData()
        self._t_play = now
        k = int(np.searchsorted(self.cum, self._sim_t)) if len(self.cum) else self.slider.maximum()
        if k >= self.slider.maximum():
            k = self.slider.maximum()
            self.play.setChecked(False)
        self.slider.setValue(k)


def _fmt(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
