# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.20.0: camera della testa nell'interfaccia.

- HeadCameraCard: il riquadro «Camera della testa» nel pannello Camera (scelta della telecamera, stato, pulsanti).
  Tiene la telecamera aperta e il modello (head_camera.HeadModel) e fa i comandi: laser sul centro camera, camera
  sul laser, camera o laser in un punto del piano, origine dal centro camera, tavola da due angoli, foto a mosaico.
- HeadCameraWindow: la vista dal vivo con mirino, righello in mm e disegno sovrapposto; un clic sul video porta lì
  il centro della camera.
Tutti i conti passano dal modello (P = L + O + M · (p − c)); le destinazioni restano dentro il piano."""
import math
import time

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from . import camera as camera_mod
from . import head_camera as hc
from .camera import CameraSource
from .i18n import tr
from .theme import C, css

CAM_COLOR = "#2ED3B7"  # centro della camera della testa: verde acqua (la testa è azzurra, il punto di partenza magenta)
BOARD_COLOR = "#F5B83D"


def to_qimage(bgr):
    h, w = bgr.shape[:2]
    return QImage(bgr.data, w, h, bgr.strides[0], QImage.Format_BGR888).copy()


# ======================================================================= riquadro nel pannello Camera
class HeadCameraCard(QWidget):
    changed = Signal()

    def __init__(self, panel):
        super().__init__()
        from .app import card, muted

        self.panel = panel
        self.ctl = panel.ctl
        self.win = panel.win
        self.src = None
        self.model = hc.HeadModel.load()
        self.model_ok = self.model is not None  # False se la risoluzione della camera aperta è diversa
        self.window = None
        self.cal = None
        self.job = None  # foto a mosaico in corso
        self.board = [None, None]  # angoli A e B della tavola (mm sul piano)
        self.last_msg = ""
        self.mark = None  # (u, v) del puntino durante la calibrazione
        self.waiting_click = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        box, bl = card(tr("Camera della testa"))
        self.combo = QComboBox()
        self.combo.setIconSize(QSize(96, 54))
        self.combo.setMinimumHeight(40)
        self.combo.addItem(tr("Nessuna camera sulla testa"), None)
        self.combo.activated.connect(self._chosen)
        bl.addWidget(self.combo)
        self.state = muted("")
        bl.addWidget(self.state)
        row = QHBoxLayout()
        self.btn_view = QPushButton(tr("Vista della testa…"))
        self.btn_view.setToolTip(tr("Video della camera della testa con mirino e righello: un clic sul video porta lì "
                                    "il centro della camera"))
        self.btn_view.clicked.connect(self.open_window)
        self.btn_cal = QPushButton(tr("Calibra…"))
        self.btn_cal.setToolTip(tr("Incide un puntino, lo segue spostando la testa e lo porta sotto il mirino: "
                                   "FreeLaserCut impara scala, rotazione e distanza fra laser e camera"))
        self.btn_cal.clicked.connect(lambda: self.open_window(calibrate=True))
        row.addWidget(self.btn_view, 1)
        row.addWidget(self.btn_cal)
        bl.addLayout(row)
        lay.addWidget(box)
        self.update_state()

    # ---------------------------------------------------------------- scelta della telecamera
    def choice(self):
        qs = getattr(self.win, "qs", None)
        v = qs.value("head_camera_choice") if qs is not None else None
        if v in (None, ""):
            return None
        if str(v) == "none":
            return "none"
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def saved_name(self):
        qs = getattr(self.win, "qs", None)
        return str(qs.value("head_camera_name", "") or "") if qs is not None else ""

    def index(self):
        """Indice della telecamera USB aperta come camera della testa, o None."""
        src = self.src
        return src.index if src is not None and isinstance(getattr(src, "index", None), int) else None

    def set_cameras(self, cams, bed_index):
        """Elenco delle telecamere dopo una ricerca (le stesse del pannello). La camera del piano non si sceglie."""
        usb = [c for c in cams if isinstance(c[0], int) and c[0] >= 0]
        if self.index() is not None and all(c[0] != self.index() for c in usb):
            frame = self.src.get(after=0, timeout=0.3)
            if frame is not None:
                h, w = frame.shape[:2]
                usb.append((self.index(), camera_mod.camera_label(self.index(), w, h, False, self.src.mode), (w, h),
                            cv2.resize(frame, (160, 90))))
            else:
                usb.append((self.index(), tr("Camera {0}", self.index()), None, None))
        usb.sort(key=lambda c: c[0])
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(tr("Nessuna camera sulla testa"), None)
        for idx, label, _size, thumb, *_ in usb:
            text = label + (("  ·  " + tr("camera del piano")) if idx == bed_index else "")
            if thumb is not None:
                self.combo.addItem(QIcon(QPixmap.fromImage(to_qimage(thumb))), text, idx)
            else:
                self.combo.addItem(text, idx)
            if idx == bed_index:  # la stessa telecamera non si apre due volte
                item = self.combo.model().item(self.combo.count() - 1)
                if item is not None:
                    item.setEnabled(False)
        self.combo.blockSignals(False)
        want = self.index()
        if want is None:
            ch = self.choice()
            name = self.saved_name()
            if name:  # 0.20.0: il numero può cambiare (altra porta USB): la ritrovo per nome, se il sistema lo dice
                for i, n in camera_mod.NAMES.items():
                    if n == name and camera_mod.name_valid(i, (camera_mod.LAST_PROBE.get(i) or {}).get("mode")):
                        ch = i
                        break
            want = ch if isinstance(ch, int) else None
        if want is not None and want == bed_index:
            want = None
        i = self.combo.findData(want) if want is not None else 0
        self.combo.setCurrentIndex(max(i, 0))
        if want is not None and i > 0 and self.index() != want:
            self._open(want)
        self.update_state()

    def _chosen(self, _i):
        idx = self.combo.currentData()
        qs = getattr(self.win, "qs", None)
        if idx is not None and idx == self.panel.bed_index():
            self.combo.setCurrentIndex(0)
            return
        if qs is not None:
            qs.setValue("head_camera_choice", "none" if idx is None else int(idx))
        if idx is None:
            self.close_src()
            self.panel.mark_head_camera()
        else:
            self._open(idx)
            if qs is not None and self.src is not None:
                self.panel.mark_head_camera()
                name = camera_mod.NAMES.get(idx, "")
                qs.setValue("head_camera_name", name if camera_mod.name_valid(idx, self.src.mode) else "")
        self.update_state()
        self.changed.emit()

    def _open(self, idx):
        if self.index() == idx:
            return True
        self.close_src()
        try:
            self.src = CameraSource(idx, size=hc.HEAD_SIZE, prefer="dshow-mjpg")
        except Exception as exc:  # noqa: BLE001
            self.src = None
            self.last_msg = tr("Non riesco ad aprire la camera della testa: {0}", exc)
            self.update_state()
            return False
        self._check_model_size()
        return True

    def set_source(self, src):
        """Una sorgente già pronta (prove automatiche: camera simulata)."""
        self.close_src()
        self.src = src
        self._check_model_size()
        self.update_state()

    def _check_model_size(self):
        size = tuple(getattr(self.src, "size", (0, 0)) or (0, 0))
        if self.src is not None and not size[0]:
            f = self.src.get(after=0, timeout=2.0)
            size = (f.shape[1], f.shape[0]) if f is not None else size
        self.model_ok = self.model is not None and (not size[0] or tuple(self.model.frame_size) == size)

    def close_src(self):
        if self.cal is not None:
            self.cal.cancel()
        if self.src is not None:
            self.src.close()
        self.src = None

    # ---------------------------------------------------------------- stato
    def ready(self):
        """Calibrata e utilizzabile per i comandi che muovono la testa."""
        return self.model is not None and self.model_ok

    def update_state(self):
        busy = self.cal is not None or self.job is not None
        if self.src is None and self.model is None:
            txt, col = tr("Fissata alla testa, guarda il piano da vicino: sceglila qui sopra e calibrala."), ""
        elif self.src is None:
            txt, col = tr("Calibrata, ma nessuna camera della testa aperta: sceglila qui sopra."), C["warn"]
        elif self.model is None:
            txt, col = tr("Camera pronta, non ancora calibrata: premi «Calibra…»."), C["warn"]
        elif not self.model_ok:
            txt, col = tr("La risoluzione della camera è cambiata: ricalibra."), C["warn"]
        else:
            txt, col = tr("✓ Calibrata il {0}  ·  {1}", self.model.created, self.model.describe()), C["success"]
        if self.last_msg and self.src is None:
            txt, col = self.last_msg, C["warn"]
        self.state.setText(txt)
        self.state.setStyleSheet(f"color:{col};" if col else "")
        self.btn_view.setEnabled(self.src is not None)
        self.btn_cal.setEnabled(self.src is not None and self.ctl.connected and not busy)
        if self.window is not None:
            self.window.update_state()
        self.update_marker()

    # ---------------------------------------------------------------- testa e segni sul piano
    def head(self):
        return hc.head_on_bed(self.ctl, self.win.profile) if self.ctl.connected else None

    def update_marker(self, head=None):
        bed = getattr(self.win, "bed", None)
        if bed is None or not hasattr(bed, "set_cam_center"):
            return
        head = head if head is not None else self.head()
        if self.ready() and self.src is not None and head is not None:
            x, y = self.model.center(head)
            bed.set_cam_center(float(x), float(y))
        else:
            bed.set_cam_center(None, None)

    # ---------------------------------------------------------------- comandi che muovono la testa
    def _can_move(self, need_model=True):
        if getattr(self.panel, "autocam", None) is not None:
            return tr("Attendi la fine della calibrazione AutoCam")
        if not self.ctl.connected:
            return tr("Connetti la macchina per muovere la testa")
        if self.ctl.job_active or self.ctl.checking:
            return tr("C'è un lavoro in corso")
        if self.cal is not None or self.job is not None:
            return tr("Attendi la fine della calibrazione o della foto")
        if need_model and not self.ready():
            return tr("Calibra prima la camera della testa")
        if self.head() is None:
            return tr("Posizione della testa sconosciuta")
        return None

    def _say(self, text, ms=6000):
        try:
            self.win.statusBar().showMessage(text, ms)
        except Exception:  # noqa: BLE001
            pass
        if self.window is not None:
            self.window.info.setText(text)
        return text

    def _go(self, target, what):
        """La testa (il laser) in target, dentro il piano. -> (x, y) raggiunto o None."""
        p = self.win.profile
        tx, ty = hc.clamp_to_bed(p, *target)
        mx, my = p.to_machine(tx, ty)
        self.ctl.goto_machine(mx, my, 3000)
        miss = math.hypot(tx - target[0], ty - target[1])
        if miss > 0.05:
            self._say(tr("{0}: fin lì la testa non arriva, si ferma al bordo (mancano {1:.1f} mm)", what, miss), 9000)
        else:
            self._say(tr("{0}: X {1:.2f}  Y {2:.2f} mm", what, tx, ty))
        return (tx, ty)

    def laser_to_camera(self):
        """Il laser va dove ora c'è il centro della camera (mirino)."""
        why = self._can_move()
        if why:
            return self._say(why) and None
        return self._go(self.model.center(self.head()), tr("Laser sul centro della camera"))

    def camera_to_laser(self):
        """La camera va a guardare il punto dove ora c'è il laser."""
        why = self._can_move()
        if why:
            return self._say(why) and None
        return self._go(self.model.head_for_camera(self.head()), tr("Camera sul punto del laser"))

    def camera_to(self, x, y):
        why = self._can_move()
        if why:
            return self._say(why) and None
        return self._go(self.model.head_for_camera((x, y)), tr("Camera qui"))

    def laser_to(self, x, y):
        why = self._can_move(need_model=False)
        if why:
            return self._say(why) and None
        return self._go((x, y), tr("Laser qui"))

    def camera_to_pixel(self, u, v):
        """Clic sul video: quel punto va sotto il mirino."""
        head = self.head()
        if not self.ready() or head is None:
            return self._say(self._can_move() or tr("Calibra prima la camera della testa")) and None
        P = self.model.img_to_bed(head, [(u, v)])[0]
        return self.camera_to(*P)

    def origin_from_camera(self):
        """L'origine utente (X0 Y0) dove ora c'è il centro della camera: G10 L20 con lo scostamento in coordinate
        macchina (vale con assi invertiti e piano ruotato)."""
        why = self._can_move()
        if why:
            return self._say(why) and None
        dmx, dmy = self.win.profile.to_machine_delta(*self.model.offset)
        line = f"G10 L20 P1 X{-dmx:.3f} Y{-dmy:.3f}"
        self.ctl.send_line(line)
        c = self.model.center(self.head())
        self._say(tr("Origine utente (X0 Y0) sul centro della camera: X {0:.2f}  Y {1:.2f} mm sul piano", c[0], c[1]))
        return line

    # ---------------------------------------------------------------- tavola da due angoli (fase 2)
    def take_corner(self, which, auto=True, frame=None):
        """Angolo della tavola (0 = A, 1 = B) dal centro della camera, oppure dall'angolo trovato vicino al mirino.
        -> (x, y) sul piano o None."""
        why = self._can_move()
        if why:
            return self._say(why) and None
        head = self.head()
        P = self.model.center(head)
        note = tr("dal mirino")
        if auto:
            frame = frame if frame is not None else (self.src.get(after=time.time(), timeout=2.0) if self.src else None)
            if frame is not None:
                found, why_not = hc.find_corner(frame, self.model.c, radius=int(min(self.model.frame_size) * 0.3))
                if found is not None:
                    P = self.model.img_to_bed(head, [found])[0]
                    note = tr("angolo trovato nell'immagine")
                else:
                    note = tr("dal mirino ({0})", why_not)
        self.board[which] = (float(P[0]), float(P[1]))
        self._show_board()
        self._say(tr("Angolo {0} della tavola: X {1:.2f}  Y {2:.2f} mm, {3}", "AB"[which], P[0], P[1], note), 9000)
        return self.board[which]

    def board_angle(self):
        if self.board[0] is None or self.board[1] is None:
            return None
        return hc.board_angle(*self.board)

    def _show_board(self):
        bed = getattr(self.win, "bed", None)
        if bed is not None and hasattr(bed, "set_board"):
            bed.set_board(self.board[0], self.board[1])
        if self.window is not None:
            self.window.update_state()

    def clear_board(self):
        self.board = [None, None]
        self._show_board()

    def align_selection(self, margin=0.0):
        """Ruota la selezione come il lato A→B della tavola e la appoggia in A (+ margine). Un solo Annulla."""
        ang = self.board_angle()
        ed = self.win.editor
        if ang is None:
            return self._say(tr("Prendi prima i due angoli della tavola (A e B, sullo stesso lato)")) and None
        sel = ed.editable()
        if not sel:
            return self._say(tr("Seleziona prima il disegno da mettere sulla tavola")) and None
        from .core import ops

        b = ops.union_bounds(sel)
        A = hc.align_affine((b.left(), b.top(), b.right(), b.bottom()), self.board[0], ang, margin)
        tf = QTransform(A[0, 0], A[1, 0], A[0, 1], A[1, 1], A[0, 2], A[1, 2])
        ed.transform(tf, tr("Allinea alla tavola"), shapes=sel)
        self._say(tr("Disegno appoggiato sulla tavola: ruotato di {0:.2f}°, angolo in A + {1:g} mm", ang, margin))
        return A

    # ---------------------------------------------------------------- calibrazione
    def calibrate(self, power=hc.DEFAULT_POWER, ask=True):
        why = self._can_move(need_model=False)
        if why:
            return self._say(why) and None
        if not self.ctl.homed:
            if ask and QMessageBox.question(self, tr("Camera della testa"),
                                            tr("Prima serve l'homing. Faccio l'homing adesso?")) == QMessageBox.Yes:
                self.ctl.home()
            return None
        if self.ctl.last_status.get("state") == "Alarm":
            return self._say(tr("La macchina è in allarme: sblocca o fai l'homing prima.")) and None
        if ask and QMessageBox.question(
                self, tr("Calibra la camera della testa"),
                tr("Metti sotto la testa un pezzo di cartone o legno da scarto, su una zona ancora pulita, e mettilo a "
                   "fuoco come per un lavoro.\n\nFreeLaserCut fa qualche foto a laser spento, incide un puntino di "
                   "circa 2 mm al {0:.0f}%, poi lo segue spostando la testa di pochi millimetri e lo porta sotto il "
                   "mirino.\n\n•  occhiali protettivi per 450 nm indossati\n•  il materiale non deve muoversi\n\n"
                   "Iniziare?", power)) != QMessageBox.Yes:
            return None
        name = camera_mod.NAMES.get(self.index(), "") if self.index() is not None else ""
        self.cal = hc.HeadCalibration(self.ctl, self.src, self.win.profile, power, name, self.index())
        self.cal.progress.connect(self._cal_progress)
        self.cal.need_click.connect(self._cal_need_click)
        self.cal.mark_seen.connect(self._cal_mark)
        self.cal.finished.connect(self._cal_finished)
        self.mark = None
        self.waiting_click = False
        self.update_state()
        self.cal.start()
        return self.cal

    def cancel(self):
        if self.cal is not None:
            self.cal.cancel()
        if self.job is not None:
            self.job.cancel()

    def _cal_progress(self, i, total, text):
        if self.window is not None:
            self.window.progress(i, total, text)

    def _cal_need_click(self, text):
        self.waiting_click = True
        self._say(text, 60000)
        if self.window is not None:
            self.window.ask_click(text)

    def _cal_mark(self, p):
        self.mark = tuple(p)

    def click_on_video(self, u, v):
        """Clic sul video: durante la calibrazione è il puntino; altrimenti il centro camera va lì."""
        if self.cal is not None and self.waiting_click:
            self.waiting_click = False
            self.cal.click(u, v)
            return "mark"
        if self.cal is not None or self.job is not None:
            return None
        self.camera_to_pixel(u, v)
        return "move"

    def _cal_finished(self, model, msg):
        self.cal = None
        self.waiting_click = False
        if model is not None:
            model.save()
            self.model, self.model_ok = model, True
        self.last_msg = ""
        self._say(msg.split("\n")[0], 12000)
        if self.window is not None:
            self.window.show_result(msg)
        self.update_state()

    # ---------------------------------------------------------------- foto del piano a mosaico (fase 3)
    def mosaic_zone(self, which):
        """Zona da fotografare: "bed" tutto il piano, "selection" attorno alla selezione (+10 mm), "board" la tavola
        presa con i due angoli. -> (x0, y0, x1, y1) o None."""
        p = self.win.profile
        if which == "selection":
            ed = self.win.editor
            if not ed.selection:
                return None
            b = ed.selection_bounds()
            z = (b.left() - 10, b.top() - 10, b.right() + 10, b.bottom() + 10)
        elif which == "board":
            if self.board[0] is None or self.board[1] is None:
                return None
            xs = [self.board[0][0], self.board[1][0]]
            ys = [self.board[0][1], self.board[1][1]]
            d = math.hypot(xs[1] - xs[0], ys[1] - ys[0])
            z = (min(xs) - 10, min(ys) - 10, max(xs) + 10, max(ys) + max(10.0, d * 0.6))
        else:
            z = (0.0, 0.0, float(p.bed_x), float(p.bed_y))
        z = (max(0.0, z[0]), max(0.0, z[1]), min(float(p.bed_x), z[2]), min(float(p.bed_y), z[3]))
        return z if z[2] - z[0] > 1 and z[3] - z[1] > 1 else None

    def take_mosaic(self, which="bed"):
        why = self._can_move()
        if why:
            return self._say(why) and None
        zone = self.mosaic_zone(which)
        if zone is None:
            return self._say(tr("Niente da fotografare: seleziona un disegno o prendi gli angoli della tavola")) and None
        self.job = hc.HeadMosaicJob(self.ctl, self.src, self.win.profile, self.model, zone)
        self.job.progress.connect(self._cal_progress)
        self.job.finished.connect(self._mosaic_finished)
        self.update_state()
        self.job.start()
        return self.job

    def _mosaic_finished(self, img, msg):
        self.job = None
        if img is not None:
            self.panel.show_mosaic(img, 2.0)
        self._say(msg, 12000)
        if self.window is not None:
            self.window.show_result(msg)
        self.update_state()

    # ---------------------------------------------------------------- finestra
    def open_window(self, calibrate=False):
        if self.src is None:
            return None
        if self.window is None:
            self.window = HeadCameraWindow(self)
        self.window.show()
        self.window.raise_()
        self.window.update_state()
        if calibrate:
            self.window.start_calibration()
        return self.window

    def shutdown(self):
        self.cancel()
        if self.window is not None:
            self.window.close()
        self.close_src()


# ======================================================================= vista dal vivo
class HeadView(QWidget):
    clicked = Signal(float, float)  # pixel dell'immagine

    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 270)
        self.setCursor(Qt.CrossCursor)
        self.frame = None
        self.img = None
        self.model = None
        self.head = None
        self.marks = []
        self.board = []
        self.shapes = []  # [[(u, v), ...], ...] disegno sovrapposto, già in pixel
        self.ask = False

    def set_frame(self, frame):
        self.frame = frame
        self.img = to_qimage(frame) if frame is not None else None
        self.update()

    def _rect(self):
        if self.img is None:
            return QRectF()
        w, h = self.img.width(), self.img.height()
        k = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * k) / 2, (self.height() - h * k) / 2, w * k, h * k)

    def to_img(self, pos):
        r = self._rect()
        if r.isEmpty() or not r.contains(pos):
            return None
        k = r.width() / self.img.width()
        return ((pos.x() - r.left()) / k, (pos.y() - r.top()) / k)

    def mousePressEvent(self, e):
        p = self.to_img(e.position())
        if p is not None and e.button() == Qt.LeftButton:
            self.clicked.emit(float(p[0]), float(p[1]))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#080D18"))
        if self.img is None:
            p.setPen(QColor(C["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, tr("Nessuna immagine dalla camera della testa"))
            return
        r = self._rect()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(r, self.img)
        p.setRenderHint(QPainter.Antialiasing)
        k = r.width() / self.img.width()

        def at(u, v):
            return QPointF(r.left() + u * k, r.top() + v * k)

        # disegno sovrapposto
        if self.shapes:
            p.setPen(QPen(QColor(255, 120, 60, 220), 1.4))
            for poly in self.shapes:
                for a, b in zip(poly, poly[1:]):
                    p.drawLine(at(*a), at(*b))
        # tavola
        if self.board:
            p.setPen(QPen(QColor(BOARD_COLOR), 2))
            for (u, v), name in self.board:
                p.drawEllipse(at(u, v), 7, 7)
                p.drawText(at(u, v) + QPointF(9, -9), name)
        for u, v in self.marks:
            p.setPen(QPen(QColor(60, 220, 60), 2))
            p.drawEllipse(at(u, v), 10, 10)
        # mirino
        cx, cy = r.center().x(), r.center().y()
        col = QColor(CAM_COLOR)
        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.drawLine(QPointF(cx + dx * 8, cy + dy * 8), QPointF(cx + dx * 40, cy + dy * 40))
        p.setPen(QPen(col, 1.5))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.drawLine(QPointF(cx + dx * 8, cy + dy * 8), QPointF(cx + dx * 40, cy + dy * 40))
        p.drawEllipse(QPointF(cx, cy), 3, 3)
        # righello: 10 mm (o 5 / 1 mm se la vista è piccola)
        if self.model is not None:
            mmpx = self.model.mm_per_px()
            for mm in (10.0, 5.0, 2.0, 1.0):
                if mm / mmpx * k < r.width() * 0.3:
                    break
            L = mm / mmpx * k
            x0, y0 = r.left() + 16, r.bottom() - 18
            p.setPen(QPen(QColor(0, 0, 0, 170), 5))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + L, y0))
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + L, y0))
            for t in (0.0, L):
                p.drawLine(QPointF(x0 + t, y0 - 5), QPointF(x0 + t, y0 + 5))
            p.drawText(QPointF(x0 + L + 8, y0 + 5), f"{mm:g} mm")
        if self.ask:
            p.setPen(QColor(C["warn"]))
            p.drawText(QRectF(r.left(), r.top() + 6, r.width(), 22), Qt.AlignHCenter,
                       tr("Fai clic sul puntino inciso"))


class HeadCameraWindow(QDialog):
    def __init__(self, card_):
        super().__init__(card_.win)
        from .app import card, muted

        self.card = card_
        self.setWindowTitle(tr("Camera della testa"))
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(820, 760)
        lay = QVBoxLayout(self)
        self.view = HeadView()
        self.view.clicked.connect(self._clicked)
        lay.addWidget(self.view, 1)
        self.info = muted("")
        lay.addWidget(self.info)

        # comandi della testa
        mc, ml = card(tr("Laser e camera"))
        g = QGridLayout()
        self.b_laser = QPushButton(tr("Laser sul centro camera"))
        self.b_laser.setToolTip(tr("Il laser va dove ora c'è il mirino della camera"))
        self.b_laser.clicked.connect(card_.laser_to_camera)
        self.b_cam = QPushButton(tr("Camera sul punto del laser"))
        self.b_cam.setToolTip(tr("La testa si sposta perché il mirino guardi il punto dove ora c'è il laser"))
        self.b_cam.clicked.connect(card_.camera_to_laser)
        self.b_origin = QPushButton(tr("Origine qui (centro camera)"))
        self.b_origin.setToolTip(tr("Il punto sotto il mirino diventa l'origine utente (X0 Y0): per riprendere un "
                                    "lavoro dallo stesso punto"))
        self.b_origin.clicked.connect(card_.origin_from_camera)
        self.chk_design = QCheckBox(tr("Mostra il disegno sul video"))
        self.chk_design.setChecked(True)
        g.addWidget(self.b_laser, 0, 0)
        g.addWidget(self.b_cam, 0, 1)
        g.addWidget(self.b_origin, 0, 2)
        g.addWidget(self.chk_design, 1, 0, 1, 3)
        ml.addLayout(g)
        ml.addWidget(muted(tr("Un clic sul video porta lì il centro della camera. Sul piano il quadratino verde acqua "
                              "è il punto sotto il mirino.")))
        lay.addWidget(mc)

        # calibrazione
        kc, kl = card(tr("Calibrazione"))
        row = QHBoxLayout()
        row.addWidget(muted(tr("Potenza del puntino")))
        self.power = QDoubleSpinBox()
        self.power.setRange(1.0, 100.0)
        self.power.setDecimals(0)
        self.power.setSuffix(" %")
        self.power.setValue(float((card_.model.power_pct if card_.model and card_.model.power_pct else None)
                                  or hc.DEFAULT_POWER))
        row.addWidget(self.power)
        self.b_cal = QPushButton(tr("◎  Calibra automaticamente"))
        self.b_cal.setObjectName("primary")
        self.b_cal.clicked.connect(self.start_calibration)
        self.b_stop = QPushButton(tr("Annulla"))
        self.b_stop.setObjectName("danger")
        self.b_stop.clicked.connect(card_.cancel)
        self.b_stop.hide()
        row.addWidget(self.b_cal, 1)
        row.addWidget(self.b_stop)
        kl.addLayout(row)
        self.bar = QProgressBar()
        self.bar.hide()
        kl.addWidget(self.bar)
        self.cal_text = muted("")
        kl.addWidget(self.cal_text)
        lay.addWidget(kc)

        # tavola (fase 2)
        tc, tl = card(tr("Tavola da due angoli"))
        tl.addWidget(muted(tr("Porta il mirino su un angolo della tavola (A), poi su un altro angolo dello stesso lato "
                              "(B): FreeLaserCut sa dov'è e quanto è storta, e ci appoggia il disegno.")))
        r2 = QHBoxLayout()
        self.b_a = QPushButton(tr("Angolo A qui"))
        self.b_a.clicked.connect(lambda: card_.take_corner(0, self.chk_auto.isChecked()))
        self.b_b = QPushButton(tr("Angolo B qui"))
        self.b_b.clicked.connect(lambda: card_.take_corner(1, self.chk_auto.isChecked()))
        self.chk_auto = QCheckBox(tr("Cerca l'angolo vicino al mirino"))
        self.chk_auto.setChecked(True)
        self.chk_auto.setToolTip(tr("FreeLaserCut cerca nell'immagine i due bordi della tavola e prende il punto in cui "
                                    "si incontrano; se non li trova usa il mirino"))
        r2.addWidget(self.b_a)
        r2.addWidget(self.b_b)
        r2.addWidget(self.chk_auto, 1)
        tl.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(muted(tr("Margine")))
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0.0, 200.0)
        self.margin.setDecimals(1)
        self.margin.setSuffix(" mm")
        self.margin.setValue(5.0)
        r3.addWidget(self.margin)
        self.b_align = QPushButton(tr("Appoggia la selezione sulla tavola"))
        self.b_align.clicked.connect(lambda: card_.align_selection(self.margin.value()))
        self.b_clear = QPushButton(tr("Togli la tavola"))
        self.b_clear.clicked.connect(card_.clear_board)
        r3.addWidget(self.b_align, 1)
        r3.addWidget(self.b_clear)
        tl.addLayout(r3)
        self.board_text = muted("")
        tl.addWidget(self.board_text)
        lay.addWidget(tc)

        # foto a mosaico (fase 3)
        pc, pl = card(tr("Foto del piano con la camera della testa"))
        r4 = QHBoxLayout()
        self.zone = QComboBox()
        self.zone.addItem(tr("Tutto il piano"), "bed")
        self.zone.addItem(tr("Attorno alla selezione"), "selection")
        self.zone.addItem(tr("La tavola"), "board")
        r4.addWidget(self.zone, 1)
        self.b_mosaic = QPushButton(tr("Fai la foto a mosaico"))
        self.b_mosaic.setToolTip(tr("La testa passa sopra la zona a laser spento e la camera fa una foto in ogni punto: "
                                    "le foto, unite, vanno sotto il piano in scala 1:1"))
        self.b_mosaic.clicked.connect(lambda: card_.take_mosaic(self.zone.currentData()))
        r4.addWidget(self.b_mosaic)
        pl.addLayout(r4)
        lay.addWidget(pc)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(120)
        self.update_state()

    # ---- stato
    def update_state(self):
        cd = self.card
        busy = cd.cal is not None or cd.job is not None
        ok = cd.ready() and cd.ctl.connected and not busy
        for b in (self.b_laser, self.b_cam, self.b_origin, self.b_a, self.b_b, self.b_mosaic):
            b.setEnabled(ok)
        self.b_align.setEnabled(cd.board_angle() is not None and not busy)
        self.b_clear.setEnabled(cd.board[0] is not None or cd.board[1] is not None)
        self.b_cal.setEnabled(cd.src is not None and cd.ctl.connected and not busy)
        self.power.setEnabled(not busy)
        self.b_stop.setVisible(busy)
        if not busy:
            self.bar.hide()
            self.view.ask = False
        ang = cd.board_angle()
        parts = []
        for i, c in enumerate(cd.board):
            if c is not None:
                parts.append(tr("{0}: X {1:.1f} Y {2:.1f}", "AB"[i], c[0], c[1]))
        if ang is not None:
            parts.append(tr("lato A→B a {0:.2f}°", ang))
        self.board_text.setText("  ·  ".join(parts) if parts else tr("Nessun angolo preso"))
        if cd.model is None:
            self.cal_text.setText(tr("Non ancora calibrata."))
        elif not busy and not self.cal_text.text():
            self.cal_text.setText(cd.model.describe())

    def progress(self, i, total, text):
        self.bar.show()
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(i)
        self.cal_text.setText(text)
        self.update_state()

    def ask_click(self, text):
        self.view.ask = True
        self.cal_text.setText(text)
        self.view.update()

    def show_result(self, msg):
        self.view.ask = False
        self.cal_text.setText(msg)
        self.update_state()

    def start_calibration(self):
        return self.card.calibrate(self.power.value())

    def _clicked(self, u, v):
        if self.card.click_on_video(u, v) == "mark":
            self.view.ask = False

    # ---- video
    def tick(self):
        cd = self.card
        if cd.src is None or not self.isVisible():
            return
        frame = cd.src.get(after=0, timeout=0.02)
        if frame is None:
            return
        head = cd.head()
        self.view.model = cd.model if cd.ready() else None
        self.view.marks = [cd.mark] if cd.mark is not None and cd.cal is not None else []
        self.view.board = []
        self.view.shapes = []
        if cd.ready() and head is not None:
            m = cd.model
            for i, c in enumerate(cd.board):
                if c is not None:
                    u, v = m.bed_to_img(head, [c])[0]
                    self.view.board.append(((u, v), "AB"[i]))
            if self.chk_design.isChecked():
                self.view.shapes = self._design(m, head)
            c = m.center(head)
            self.info.setText(tr("Centro camera: X {0:.2f}  Y {1:.2f} mm  ·  laser: X {2:.2f}  Y {3:.2f} mm",
                                 c[0], c[1], head[0], head[1]))
        self.view.set_frame(frame)

    def _design(self, m, head):
        """Il disegno (forme visibili vicino alla zona inquadrata) in pixel della camera."""
        doc = self.card.win.editor.doc
        vw, vh = m.view_mm()
        cx, cy = m.center(head)
        R = math.hypot(vw, vh) / 2 + 2
        out = []
        n = 0
        for s in doc.shapes:
            if getattr(s, "hidden", False):
                continue
            b = s.bounds()
            if b.right() < cx - R or b.left() > cx + R or b.bottom() < cy - R or b.top() > cy + R:
                continue
            for poly in s.path().toSubpathPolygons():
                pts = np.array([(q.x(), q.y()) for q in poly], float)
                if len(pts) < 2:
                    continue
                out.append([tuple(q) for q in m.bed_to_img(head, pts)])
                n += len(pts)
                if n > 20000:
                    return out
        return out

    def closeEvent(self, e):
        self.timer.stop()
        super().closeEvent(e)

    def showEvent(self, e):
        self.timer.start(120)
        super().showEvent(e)
