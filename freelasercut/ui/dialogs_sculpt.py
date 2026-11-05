# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Strumenti → Scultura 3D: un modello 3D diventa pezzi da tagliare, a strati o a incastro, con l'anteprima 3D
(modello, scultura finita, montaggio passo per passo) e i pezzi sistemati sui fogli di materiale."""
import math
import os

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QTransform
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ..core import geom, nesting, render3d, sculpt as sc
from ..core.document import GroupShape, PathShape, RectShape, TextShape, default_layer
from freelasercut.i18n import tr  # noqa: E402

STYLES = {"layers": tr("A strati (da incollare)"), "interlocking": tr("A incastro (senza colla)")}
VIEWS = (("model", tr("Modello")), ("sculpture", tr("Scultura")), ("assembly", tr("Montaggio")))
LABEL_FONT = "futural"  # carattere a linea singola: i numeri si incidono veloci


# ==================================================================== visore 3D
class Viewer3D(QWidget):
    """Anteprima 3D: trascina per girare, rotella per avvicinare, doppio clic per tornare alla vista di partenza.
    Mentre si trascina la resa è più leggera; appena ci si ferma torna piena."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 330)
        self.setMouseTracking(False)
        self.setCursor(Qt.OpenHandCursor)
        self.mesh = None
        self.sculpture = None
        self.view = "sculpture"
        self.step = None     # montaggio: quanti pezzi sono già al loro posto
        self.lift = 0.0      # montaggio: altezza del pezzo che sta arrivando
        self.yaw, self.pitch, self.zoom = -35.0, 22.0, 1.0
        self._img = None
        self._key = None
        self._scenes = {}  # scene già pronte (girando la vista non si ricalcolano)
        self._drag = None
        self._fast = False
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(180)
        self._idle.timeout.connect(self._sharp)
        self.message = ""

    def set_data(self, mesh, sculpture):
        self.mesh, self.sculpture = mesh, sculpture
        self._scenes = {}
        self._key = None
        self.update()

    def set_view(self, view):
        self.view = view
        self._key = None
        self.update()

    def set_step(self, step, lift=0.0):
        self.step, self.lift = step, lift
        self._key = None
        self.update()

    def reset_camera(self):
        self.yaw, self.pitch, self.zoom = -35.0, 22.0, 1.0
        self._key = None
        self.update()

    def _cached(self, key, make):
        if key not in self._scenes:
            if len(self._scenes) > 6:
                for k in [k for k in self._scenes if k[0] == "assembly"]:
                    del self._scenes[k]
            self._scenes[key] = make()
        return self._scenes[key]

    def scene(self):
        if self.view == "model" or self.sculpture is None:
            if self.mesh is None:
                return None
            return self._cached(("model",), lambda: render3d.mesh_scene(self.mesh))
        full = self._cached(("sculpture",), lambda: render3d.sculpture_scene(self.sculpture))
        if self.view == "assembly":
            n = len(self.sculpture.pieces)
            k = n if self.step is None else max(0, min(n, self.step))
            if k >= n:
                return full
            if self.lift > 0:  # pezzo che sta arrivando: cambia a ogni fotogramma, non si tiene
                return render3d.sculpture_scene(self.sculpture, upto=k + 1, lift=(k, self.lift), highlight=k)
            return self._cached(("assembly", k), lambda: render3d.sculpture_scene(self.sculpture, upto=max(k, 0)))
        return full

    def render_image(self, w, h, ss=2):
        """Immagine (QImage) della vista attuale: si usa anche per le prove e per salvare l'anteprima."""
        scene = self.scene()
        if scene is None or (not scene.tris and not scene.caps):
            img = QImage(w, h, QImage.Format_RGB888)
            img.fill(QColor("#E6EAF0"))
            return img
        full = self.scene_full() if (self.view == "assembly" and self.sculpture) else scene
        cam = render3d.fit_camera(full, self.yaw, self.pitch)
        cam.dist /= max(self.zoom, 0.05)
        arr = render3d.render(scene, cam, w, h, ss=ss)
        return QImage(arr.tobytes(), w, h, 3 * w, QImage.Format_RGB888).copy()

    def scene_full(self):
        return self._cached(("sculpture",), lambda: render3d.sculpture_scene(self.sculpture))

    def _sharp(self):
        self._fast = False
        self._key = None
        self.update()

    def paintEvent(self, _ev):
        w, h = self.width(), self.height()
        key = (w, h, self.view, self.step, round(self.lift, 2), round(self.yaw, 1), round(self.pitch, 1),
               round(self.zoom, 3), id(self.sculpture), id(self.mesh), self._fast)
        if key != self._key:
            if self._fast:  # trascinando: mezza grandezza, senza antialiasing
                img = self.render_image(max(64, w // 2), max(48, h // 2), ss=1).scaled(w, h)
            else:
                img = self.render_image(w, h, ss=2 if w * h <= 700_000 else 1)
            self._img, self._key = img, key
        p = QPainter(self)
        if self._img is not None:
            p.drawImage(0, 0, self._img)
        p.setPen(QColor("#5A6478"))
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.drawText(QRectF(8, h - 22, w - 16, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("Trascina per girare · rotella per avvicinare · doppio clic: vista di partenza"))
        if self.message:
            p.drawText(QRectF(8, 6, w - 16, 18), Qt.AlignRight | Qt.AlignVCenter, self.message)
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        if self._drag is None:
            return
        d = ev.position() - self._drag
        self._drag = ev.position()
        self.yaw = (self.yaw + d.x() * 0.5) % 360.0
        self.pitch = max(-10.0, min(85.0, self.pitch + d.y() * 0.35))
        self._fast = True
        self._idle.start()
        self.update()

    def mouseReleaseEvent(self, _ev):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)
        self._idle.start()

    def wheelEvent(self, ev):
        k = 1.12 if ev.angleDelta().y() > 0 else 1 / 1.12
        self.zoom = max(0.4, min(4.0, self.zoom * k))
        self._fast = True
        self._idle.start()
        self.update()

    def mouseDoubleClickEvent(self, _ev):
        self.reset_camera()


# ==================================================================== finestra
class SculptDialog(QDialog):
    def __init__(self, parent=None, bed=(400.0, 400.0)):
        super().__init__(parent)
        self.setWindowTitle(tr("Scultura 3D da modello"))
        self.setMinimumSize(1060, 640)
        self.bed = bed
        self.file_mesh = None
        self.file_name = ""
        self.mesh = None          # modello preparato (asse verticale, misure)
        self.sculpture = None
        self.error = ""
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        left = QVBoxLayout()
        f = QFormLayout()
        self.model = QComboBox()
        for k, lab in sc.BUILTINS.items():
            self.model.addItem(lab, k)
        self.model.setToolTip(tr("Modelli di prova inclusi, oppure un tuo file .stl o .obj (pulsante «Apri modello…»). "
                                 "Usa solo modelli che hai il diritto di usare."))
        openb = QPushButton(tr("Apri modello…"))
        openb.clicked.connect(self._open)
        row = QHBoxLayout()
        row.addWidget(self.model, 1)
        row.addWidget(openb)
        f.addRow(tr("Modello"), row)
        self.up = QComboBox()
        for k, lab in sc.UP_AXES.items():
            self.up.addItem(lab, k)
        self.up.setToolTip(tr("Quale asse del file va in verticale: se il modello appare sdraiato, cambia questa voce."))
        f.addRow(tr("Verticale"), self.up)
        self.height_mm = self._spin(20, 1000, 120, 1, " mm", tr("Altezza della scultura finita"))
        f.addRow(tr("Altezza"), self.height_mm)
        self.style = QComboBox()
        for k, lab in STYLES.items():
            self.style.addItem(lab, k)
        self.style.setToolTip(tr("A strati: fette orizzontali da incollare una sull'altra, con inciso dove va la "
                                 "fetta sopra. A incastro: sagome verticali con le fessure, si montano senza colla."))
        f.addRow(tr("Stile"), self.style)
        self.thick = self._spin(0.5, 20, 3.0, 2, " mm", tr("Spessore vero del materiale: misuralo con il calibro "
                                                          "(un compensato «3 mm» spesso è 2,8–3,2 mm)"))
        f.addRow(tr("Spessore del materiale"), self.thick)
        self.nx = QSpinBox()
        self.ny = QSpinBox()
        for s_ in (self.nx, self.ny):
            s_.setRange(1, 60)
        self.nx.setToolTip(tr("Quante sagome lungo X (da sinistra a destra)"))
        self.ny.setToolTip(tr("Quante sagome lungo Y (dal davanti al dietro)"))
        self.auto = QPushButton(tr("Automatico"))
        self.auto.setToolTip(tr("Circa una sagoma ogni 22 mm"))
        self.auto.clicked.connect(self._auto_counts)
        self.counts_box = QWidget()
        r2 = QHBoxLayout(self.counts_box)
        r2.setContentsMargins(0, 0, 0, 0)
        r2.addWidget(QLabel("X"))
        r2.addWidget(self.nx)
        r2.addWidget(QLabel("Y"))
        r2.addWidget(self.ny)
        r2.addWidget(self.auto)
        self.counts_name = QLabel(tr("Sagome"))
        f.addRow(self.counts_name, self.counts_box)
        self.fit = self._spin(-0.5, 1.0, 0.0, 2, " mm", tr("Fessure più larghe (+) o più strette (−) dello spessore: "
                                                         "il laser porta via un po' di materiale, prova un pezzo e "
                                                         "correggi qui"))
        self.fit.setSingleStep(0.05)
        self.fit_name = QLabel(tr("Gioco delle fessure"))
        f.addRow(self.fit_name, self.fit)
        self.sheet_w = self._spin(50, 3000, bed[0], 0, " mm", tr("Larghezza del foglio di materiale"))
        self.sheet_h = self._spin(50, 3000, bed[1], 0, " mm", tr("Altezza del foglio di materiale"))
        r3 = QHBoxLayout()
        r3.addWidget(self.sheet_w)
        r3.addWidget(QLabel("×"))
        r3.addWidget(self.sheet_h)
        f.addRow(tr("Foglio"), r3)
        left.addLayout(f)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setMinimumWidth(330)
        left.addWidget(self.info)
        left.addStretch(1)
        tip = QLabel(tr("FreeLaserCut crea due livelli: i tagli (<b>Linea</b>, per ultimi) e i segni da incidere "
                        "leggeri: numeri dei pezzi e, negli strati, il contorno della fetta sopra. Imposta velocità e "
                        "potenza dei due livelli per il tuo materiale prima di avviare."))
        tip.setWordWrap(True)
        tip.setObjectName("muted")
        left.addWidget(tip)
        h.addLayout(left, 0)
        right = QVBoxLayout()
        tabs = QHBoxLayout()
        self.view_group = QButtonGroup(self)
        self.view_buttons = {}
        for k, lab in VIEWS:
            b = QPushButton(lab)
            b.setCheckable(True)
            self.view_group.addButton(b)
            self.view_buttons[k] = b
            b.clicked.connect(lambda _=False, k=k: self._set_view(k))
            tabs.addWidget(b)
        tabs.addStretch(1)
        right.addLayout(tabs)
        self.viewer = Viewer3D(self)
        right.addWidget(self.viewer, 1)
        play_row = QHBoxLayout()
        self.play = QPushButton(tr("▶ Monta"))
        self.play.setToolTip(tr("I pezzi arrivano uno alla volta, nell'ordine di montaggio"))
        self.play.clicked.connect(self._toggle_play)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.valueChanged.connect(self._slider_moved)
        self.step_lbl = QLabel("")
        self.step_lbl.setMinimumWidth(190)
        play_row.addWidget(self.play)
        play_row.addWidget(self.slider, 1)
        play_row.addWidget(self.step_lbl)
        self.play_row = QWidget()
        self.play_row.setLayout(play_row)
        right.addWidget(self.play_row)
        h.addLayout(right, 1)
        v.addLayout(h, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Crea i pezzi"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok_btn = bb.button(QDialogButtonBox.Ok)
        v.addWidget(bb)
        self._anim = QTimer(self)
        self._anim.setInterval(70)
        self._anim.timeout.connect(self._anim_tick)
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._rebuild)
        for w in (self.model, self.up, self.style):
            w.currentIndexChanged.connect(self._later)
        for w in (self.height_mm, self.thick, self.fit, self.nx, self.ny):
            w.valueChanged.connect(self._later)
        self.model.currentIndexChanged.connect(lambda *_: self._auto_counts(quiet=True))
        self.up.currentIndexChanged.connect(lambda *_: self._auto_counts(quiet=True))
        self.style.currentIndexChanged.connect(self._style_changed)
        self.view_buttons["sculpture"].setChecked(True)
        self.play_row.setVisible(False)
        self._style_changed()
        self._auto_counts(quiet=True)
        self._rebuild()

    @staticmethod
    def _spin(lo, hi, val, dec, suffix, tip):
        s_ = QDoubleSpinBox()
        s_.setRange(lo, hi)
        s_.setDecimals(dec)
        s_.setValue(val)
        s_.setSuffix(suffix)
        s_.setToolTip(tip)
        return s_

    # ---------------------------------------------------------------- valori
    def source_mesh(self):
        if self.model.currentData() == "file":
            return self.file_mesh
        return sc.builtin(self.model.currentData())

    def _style_changed(self, *_):
        inter = self.style.currentData() == "interlocking"
        for w in (self.counts_box, self.counts_name, self.fit, self.fit_name):
            w.setVisible(inter)

    def _auto_counts(self, quiet=False):
        try:
            m = sc.prepared(self.source_mesh(), self.up.currentData(), self.height_mm.value())
        except Exception:  # noqa: BLE001 - modello non valido: lo dice _rebuild
            return
        nx, ny = sc.auto_counts(m, self.thick.value())
        for s_, n in ((self.nx, nx), (self.ny, ny)):
            s_.blockSignals(True)
            s_.setValue(n)
            s_.blockSignals(False)
        if not quiet:
            self._later()

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Apri un modello 3D"), "", tr("Modelli 3D (*.stl *.obj)"))
        if path:
            self.load_file(path)

    def load_file(self, path):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.file_mesh = sc.load(path)
        except (OSError, ValueError) as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, tr("Scultura 3D"), tr("Non riesco ad aprire il modello: {0}", ex))
            return False
        QApplication.restoreOverrideCursor()
        self.file_name = os.path.basename(path)
        i = self.model.findData("file")
        if i < 0:
            self.model.addItem(self.file_name, "file")
            i = self.model.count() - 1
        else:
            self.model.setItemText(i, self.file_name)
        self.model.setCurrentIndex(i)
        self._auto_counts(quiet=True)
        self._rebuild()
        return True

    # ---------------------------------------------------------------- calcolo
    def _later(self, *_):
        self._timer.start()

    def _rebuild(self):
        self._timer.stop()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.error = ""
            self.mesh = sc.prepared(self.source_mesh(), self.up.currentData(), self.height_mm.value())
            if self.style.currentData() == "layers":
                self.sculpture = sc.layered(self.mesh, self.thick.value())
            else:
                self.sculpture = sc.interlocking(self.mesh, self.thick.value(), self.nx.value(), self.ny.value(),
                                                 self.fit.value())
        except (ValueError, MemoryError) as ex:
            self.sculpture = None
            self.error = str(ex)
        except Exception as ex:  # noqa: BLE001 - un modello strano non deve chiudere la finestra
            self.sculpture = None
            self.error = tr("Non riesco a calcolare la scultura con questo modello ({0}).", ex)
        finally:
            QApplication.restoreOverrideCursor()
        self.viewer.set_data(self.mesh, self.sculpture)
        n = len(self.sculpture.pieces) if self.sculpture else 0
        self.slider.blockSignals(True)
        self.slider.setRange(0, n)
        self.slider.setValue(n)
        self.slider.blockSignals(False)
        self._slider_moved(n)
        self._update_info()

    def _update_info(self):
        if self.sculpture is None:
            self.info.setText(f"<span style='color:#E5484D'>{self.error}</span>")
            self.ok_btn.setEnabled(False)
            return
        self.ok_btn.setEnabled(True)
        s = self.sculpture
        size = s.size()
        sheet = self.sheet_w.value() * self.sheet_h.value()
        sheets = max(1, math.ceil(s.area_mm2() * 1.35 / max(sheet, 1.0)))
        if sheets == 1:
            text = tr("<b>{0} pezzi</b> · scultura {1:.0f} × {2:.0f} × {3:.0f} mm<br>materiale: circa {4:.0f} cm² "
                      "(un foglio)", len(s.pieces), size[0], size[1], size[2], s.area_mm2() / 100.0)
        else:
            text = tr("<b>{0} pezzi</b> · scultura {1:.0f} × {2:.0f} × {3:.0f} mm<br>materiale: circa {4:.0f} cm² "
                      "(circa {5} fogli)", len(s.pieces), size[0], size[1], size[2], s.area_mm2() / 100.0, sheets)
        if s.warnings:
            text += "<br><span style='color:#E5484D'>" + "<br>".join(dict.fromkeys(s.warnings)) + "</span>"
        self.info.setText(text)

    # ---------------------------------------------------------------- viste
    def _set_view(self, k):
        if k != "assembly" and self._anim.isActive():  # il montaggio si ferma se si cambia vista
            self._toggle_play()
        self.view_buttons[k].setChecked(True)
        self.viewer.set_view(k)
        self.play_row.setVisible(k == "assembly")
        if k == "assembly":
            self._slider_moved(self.slider.value())

    def _slider_moved(self, val):
        n = len(self.sculpture.pieces) if self.sculpture else 0
        if self.sculpture is None:
            self.step_lbl.setText("")
            return
        pieces = sorted(self.sculpture.pieces, key=lambda p: p.order)
        if val <= 0:
            self.step_lbl.setText(tr("Pronti a montare"))
        else:
            self.step_lbl.setText(tr("Pezzo {0} di {1}: {2}", val, n, pieces[val - 1].name))
        if self.viewer.view == "assembly":
            self.viewer.set_step(val)

    def _toggle_play(self):
        if self._anim.isActive():
            self._anim.stop()
            self.play.setText(tr("▶ Monta"))
            return
        if self.slider.value() >= self.slider.maximum():
            self.slider.setValue(0)
        self._frame = 0
        self.play.setText(tr("■ Ferma"))
        self._set_view("assembly")
        self._anim.start()

    def _anim_tick(self):
        if self.sculpture is None:
            self._anim.stop()
            return
        k = self.slider.value()
        if k >= self.slider.maximum():
            self._anim.stop()
            self.play.setText(tr("▶ Monta"))
            self.viewer.set_step(k)
            return
        frames = 6
        self._frame += 1
        hgt = float(self.sculpture.size()[2]) * 0.5
        if self._frame < frames:
            self.viewer.set_step(k, hgt * (1 - self._frame / frames) ** 2 + 0.01)
        else:
            self._frame = 0
            self.slider.setValue(k + 1)

    def accept(self):
        """Si crea sempre la scultura delle impostazioni scritte (anche premendo Invio subito dopo una modifica)."""
        pending = self._timer.isActive()
        self._timer.stop()
        self._anim.stop()
        if pending or self.sculpture is None:
            self._rebuild()
        if self.sculpture is None:
            return
        super().accept()

    def done(self, r):
        """Chiusa in qualsiasi modo (anche Esc): niente calcoli o animazioni rimasti in sospeso."""
        self._timer.stop()
        self._anim.stop()
        self.viewer._idle.stop()
        super().done(r)

    def values(self):
        return dict(sheet=(self.sheet_w.value(), self.sheet_h.value()), style=self.style.currentData(),
                    thickness=self.thick.value())


# ==================================================================== nel progetto
def piece_shapes(piece, cut_layer, mark_layer):
    """Forme di un pezzo nel suo piano (u, v come x, y del piano): taglio, segni da incidere e nome."""
    path = QPainterPath()
    for r in piece.island.rings:
        r = np.asarray(r)
        path.moveTo(float(r[0, 0]), float(r[0, 1]))
        for x, y in r[1:]:
            path.lineTo(float(x), float(y))
        path.closeSubpath()
    out = [PathShape(path, cut_layer)]
    if piece.guides:
        g = QPainterPath()
        for line in piece.guides:
            line = np.asarray(line)
            g.moveTo(float(line[0, 0]), float(line[0, 1]))
            for x, y in line[1:]:
                g.lineTo(float(x), float(y))
        out.append(PathShape(g, mark_layer))
    if piece.label is not None and piece.label[2] >= 0.9:  # pezzi troppo sottili: niente numero (uscirebbe)
        u, v, room = piece.label
        size = max(1.5, min(6.0, room * 1.5 / max(1.0, len(piece.name) * 0.8)))
        t = TextShape(piece.name, LABEL_FONT, size, layer=mark_layer)
        b = t.bounds()
        t.apply(QTransform.fromTranslate(u - b.center().x(), v - b.center().y()))
        out.append(t)
    return out


def run_sculpt(win):
    from .editor import TOOL_LAYER

    dlg = SculptDialog(win, (win.profile.bed_x, win.profile.bed_y))
    try:
        if dlg.exec() != QDialog.Accepted or dlg.sculpture is None:
            return None
        s, val = dlg.sculpture, dlg.values()
    finally:
        dlg.deleteLater()  # il modello può essere grande: la finestra non resta in memoria
    doc = win.editor.doc
    free = win._free_layers(2)
    if len(free) < 2:
        QMessageBox.warning(win, tr("Scultura 3D"), tr("Servono due livelli liberi: liberane qualcuno e riprova."))
        return None
    mark_layer, cut_layer = free
    sw, sh = val["sheet"]
    area = [geom.Poly([(0.0, 0.0), (sw, 0.0), (sw, sh), (0.0, sh)], True)]
    groups = []
    for pc in sorted(s.pieces, key=lambda p: p.order):
        grp = GroupShape(piece_shapes(pc, cut_layer, mark_layer), layer=cut_layer)
        grp._sculpt_name = pc.name
        groups.append(grp)
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        results, shifts = nesting.nest_sheets(groups, area, (), max_sheets=len(groups), keep_touching=False,
                                              spacing=2.5, margin=2.0,
                                              rotations="90", tick=lambda: (QApplication.processEvents(), False)[1])
    finally:
        QApplication.restoreOverrideCursor()
    placed = {g for r in results for grp in r.placements for g in grp}
    left = [g for g in groups if g not in placed]
    win.editor.begin(tr("Scultura 3D"))
    try:
        for i in (cut_layer, mark_layer):
            doc.layers[i] = default_layer(i)
        cs_cut, cs_mark = doc.layer(cut_layer), doc.layer(mark_layer)
        cs_cut.mode, cs_cut.name = "line", tr("Scultura: taglio")
        cs_mark.mode, cs_mark.name = "line", tr("Scultura: segni")
        cs_mark.speed, cs_mark.power_max = 3000.0, 12.0  # segni leggeri: solo da vedere
        top = max([c.priority for c in doc.used_layers()] + [0])
        cs_mark.priority, cs_cut.priority = top + 1, top + 2  # prima i segni, poi i tagli
        for res in results:
            nesting.apply(res)
        x_end = (len(results) or 1) * (sw + 20.0)
        for k, g in enumerate(left):  # pezzi più grandi del foglio: a destra, da sistemare a mano
            b = g.bounds()
            g.apply(QTransform.fromTranslate(x_end - b.left() + k * 5.0, -b.top()))
        extra = []
        for k, dx in enumerate(shifts):
            if k:
                out = RectShape(sw, sh, layer=TOOL_LAYER)
                out.apply(QTransform.fromTranslate(dx, 0.0))
                extra.append(out)
            lab = TextShape(tr("Foglio {0}", k + 1), "Arial", max(4.0, min(10.0, sw / 30)), layer=TOOL_LAYER)
            lab.apply(QTransform.fromTranslate(dx, sh + 3))
            extra.append(lab)
        win.editor.add(groups + extra, tr("Scultura 3D"))
        win.editor.commit()
    except Exception:
        win.editor.cancel()
        raise
    msg = tr("Scultura: {0} pezzi su {1} fogli. Prima di avviare imposta i livelli «{2}» e «{3}» per il tuo materiale.",
             len(groups), max(1, len(results)), cs_mark.label(), cs_cut.label())
    if left:
        msg += " " + tr("{0} pezzi sono più grandi del foglio: sono a destra, da sistemare a mano.", len(left))
    win.statusBar().showMessage(msg, 15000)
    return groups
