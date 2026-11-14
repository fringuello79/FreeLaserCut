# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Camera della testa (0.19.6): il riquadro sotto la camera del piano.

Video dal vivo raddrizzato come il piano, mirino al centro e righello in mm; calibrazione automatica con un segno
inciso (headcam_cal.py); «Porta il laser sul mirino», «Porta il mirino sul laser», «Origine al mirino», clic sul video
= quel punto va sotto il mirino; il mirino si vede anche sul piano. Tavola da 2 angoli (fase 2).
Dati salvati nel profilo della macchina (head_cam_name, head_cam_index, head_cam_cal). Conti in core/headcam.py.
"""
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..core import headcam as H
from ..theme import C
from freelasercut.i18n import tr  # noqa: E402

SIM_HEAD = "sim-testa"
VIDEO_MS = 100


def _qimage(bgr):
    rgb = np.ascontiguousarray(bgr[..., ::-1])
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


class VideoView(QWidget):
    """Il video raddrizzato con mirino, righello e segni; il clic dice il pixel del fotogramma ORIGINALE."""
    clicked = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(190)
        self.img = None
        self.raw_size = None
        self.k, self.flip = 0, False
        self.mm_px = None  # mm per pixel (calibrazione) per il righello
        self.marks = []  # pixel del fotogramma originale da cerchiare (il segno trovato)
        self.note = tr("Nessuna immagine")
        self.setCursor(Qt.CrossCursor)

    def set_frame(self, raw, k, flip, mm_px):
        self.raw_size = (raw.shape[1], raw.shape[0])
        self.k, self.flip, self.mm_px = k, flip, mm_px
        self.img = _qimage(H.orient_frame(raw, k, flip))
        self.update()

    def clear(self, note):
        self.img, self.note = None, note
        self.update()

    def _rect(self):
        if self.img is None:
            return QRectF()
        w, h = self.img.width(), self.img.height()
        s = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * s) / 2, (self.height() - h * s) / 2, w * s, h * s)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#080D18"))
        if self.img is None:
            p.setPen(QColor(C["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.note)
            return
        r = self._rect()
        p.drawImage(r, self.img)
        s = r.width() / self.img.width()
        cx, cy = r.center().x(), r.center().y()
        pen = QPen(QColor("#FF3B30"), 1.5)
        p.setPen(pen)
        for a, b in (((-30, 0), (-6, 0)), ((6, 0), (30, 0)), ((0, -30), (0, -6)), ((0, 6), (0, 30))):
            p.drawLine(QPointF(cx + a[0], cy + a[1]), QPointF(cx + b[0], cy + b[1]))
        p.drawEllipse(QPointF(cx, cy), 2, 2)
        for m in self.marks:
            u, v = H.raw_to_shown(m, self.raw_size, self.k, self.flip)
            p.setPen(QPen(QColor("#34C759"), 2))
            p.drawEllipse(QPointF(r.left() + u * s, r.top() + v * s), 9, 9)
        if self.mm_px:
            L = H.nice_ruler(self.mm_px, 0.25 * self.img.width())
            px = L / self.mm_px * s
            x0, y0 = r.left() + 10, r.bottom() - 12
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.drawLine(QPointF(x0, y0), QPointF(x0 + px, y0))
            p.drawLine(QPointF(x0, y0 - 4), QPointF(x0, y0 + 4))
            p.drawLine(QPointF(x0 + px, y0 - 4), QPointF(x0 + px, y0 + 4))
            p.drawText(QPointF(x0, y0 - 6), f"{L:g} mm")

    def mousePressEvent(self, e):
        if self.img is None or e.button() != Qt.LeftButton:
            return
        r = self._rect()
        if not r.contains(e.position()):
            return
        s = r.width() / self.img.width()
        su, sv = (e.position().x() - r.left()) / s, (e.position().y() - r.top()) / s
        u, v = H.shown_to_raw((su, sv), self.raw_size, self.k, self.flip)
        self.clicked.emit(u, v)


class HeadCamPanel(QWidget):
    """Il riquadro «Camera della testa» (dentro il pannello Camera)."""
    _found = Signal(object)

    def __init__(self, plate_panel):
        super().__init__()
        from ..app import card, muted

        self.plate = plate_panel
        self.win = plate_panel.win
        self.ctl = plate_panel.ctl
        self.src = None
        self.calib = None
        self.cams = []
        self.cal = H.HeadCal.from_dict(getattr(self.profile, "head_cam_cal", None) or {})
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        box, lay = card(tr("Camera della testa"))
        lay.addWidget(muted(tr("Una telecamera fissata accanto al laser: guarda il pezzo da vicino. Il mirino rosso è "
                               "il punto che la camera ha al centro.")))
        self.combo = QComboBox()
        self.combo.addItem(tr("Nessuna camera sulla testa"), None)
        self.combo.activated.connect(self._picked)
        crow = QHBoxLayout()
        crow.addWidget(self.combo, 1)
        self.b_search = QPushButton("⟳")
        self.b_search.setToolTip(tr("Cerca di nuovo le telecamere USB"))
        self.b_search.setFixedWidth(34)
        self.b_search.clicked.connect(self.search)
        crow.addWidget(self.b_search)
        lay.addLayout(crow)
        self._found.connect(lambda cams: self.set_cameras(cams, self._plate_index()))
        self.video = VideoView()
        self.video.clicked.connect(self._video_clicked)
        lay.addWidget(self.video)
        self.state = muted("")
        lay.addWidget(self.state)
        row = QHBoxLayout()
        self.b_cal = QPushButton(tr("◎  Calibra…"))
        self.b_cal.setObjectName("primary")
        self.b_cal.setToolTip(tr("Il laser incide un piccolo segno su uno scarto, la camera lo trova e misura da sola "
                                 "distanza dal laser, scala e verso dell'immagine"))
        self.b_cal.clicked.connect(self.calibrate)
        self.b_stop = QPushButton(tr("Annulla"))
        self.b_stop.setObjectName("danger")
        self.b_stop.clicked.connect(self.cancel_calibration)
        self.b_stop.hide()
        row.addWidget(self.b_cal, 1)
        row.addWidget(self.b_stop)
        lay.addLayout(row)
        g = QHBoxLayout()
        self.b_laser = QPushButton(tr("Laser sul mirino"))
        self.b_laser.setToolTip(tr("La testa si sposta: il laser va dove ora guarda il mirino"))
        self.b_laser.clicked.connect(self.laser_to_crosshair)
        self.b_cross = QPushButton(tr("Mirino sul laser"))
        self.b_cross.setToolTip(tr("La testa si sposta: il mirino va dove ora punta il laser"))
        self.b_cross.clicked.connect(self.crosshair_to_laser)
        g.addWidget(self.b_laser)
        g.addWidget(self.b_cross)
        lay.addLayout(g)
        g2 = QHBoxLayout()
        self.b_origin = QPushButton(tr("Origine al mirino"))
        self.b_origin.setToolTip(tr("Il punto sotto il mirino diventa l'origine utente (X0 Y0), senza muovere la testa"))
        self.b_origin.clicked.connect(self.origin_at_crosshair)
        self.b_board = QPushButton(tr("Tavola da 2 angoli…"))
        self.b_board.setToolTip(tr("Porta il mirino su due spigoli dello stesso lato della tavola: FreeLaserCut ne "
                                   "disegna il contorno sul livello strumenti e sa di quanto è storta"))
        self.b_board.clicked.connect(self.board_dialog)
        g2.addWidget(self.b_origin)
        g2.addWidget(self.b_board)
        lay.addLayout(g2)
        self.chk_bed = QCheckBox(tr("Mostra il mirino sul piano"))
        qs = getattr(self.win, "qs", None)
        self.chk_bed.setChecked(qs is None or qs.value("head_cam_cross", "true") in (True, "true"))
        self.chk_bed.toggled.connect(self._cross_toggled)
        lay.addWidget(self.chk_bed)
        self.cal_note = muted("")
        lay.addWidget(self.cal_note)
        v.addWidget(box)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(VIDEO_MS)
        self.ctl.status_changed.connect(lambda *_: self.update_cross())
        self.ctl.connection_changed.connect(lambda *_: self.update_state())
        self.update_state()

    # ---------------------------------------------------------------- dati
    @property
    def profile(self):
        return self.win.profile

    def wanted_index(self):
        """Il numero della camera della testa secondo il profilo: per nome se il sistema lo dice, se no il numero."""
        from .. import camera as camera_mod

        name = getattr(self.profile, "head_cam_name", "") or ""
        if name:
            for i, n in camera_mod.NAMES.items():
                if n == name:
                    return i
        idx = int(getattr(self.profile, "head_cam_index", -1))
        return idx if idx >= 0 else None

    def _save_profile(self):
        try:
            self.profile.save()
        except OSError as exc:
            self.state.setText(tr("Non riesco a salvare il profilo: {0}", exc))

    # ---------------------------------------------------------------- elenco e apertura
    def set_cameras(self, cams, plate_index):
        """Dalla ricerca della camera del piano: [(indice, etichetta, ...)] (senza quella del piano)."""
        self.cams = [c for c in cams if isinstance(c[0], int) and c[0] != plate_index]
        cur = self.src.index if self.src is not None else None
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(tr("Nessuna camera sulla testa"), None)
        for c in self.cams:
            self.combo.addItem(c[1], c[0])
        if isinstance(cur, int) and self.combo.findData(cur) < 0 and cur != plate_index:
            self.combo.addItem(tr("Camera {0} (aperta)", cur), cur)
        if self.ctl.sim is not None:
            self.combo.addItem(tr("Camera della testa simulata"), SIM_HEAD)
        want = cur if cur is not None else self.wanted_index()
        i = self.combo.findData(want) if want is not None else 0
        self.combo.setCurrentIndex(max(i, 0))
        self.combo.blockSignals(False)
        if self.src is None and i > 0:
            self._open(self.combo.currentData())

    def _plate_index(self):
        src = getattr(self.plate, "src", None)
        return getattr(src, "index", None) if src is not None else None

    def search(self):
        """Cerca le telecamere da sola (serve se la camera del piano è spenta e quindi non le cerca)."""
        import threading

        from .. import camera as camera_mod

        skip = set()
        for s in (self.src, getattr(self.plate, "src", None)):
            if s is not None and isinstance(getattr(s, "index", None), int):
                skip.add(s.index)

        def work():
            try:
                names = camera_mod.usb_camera_names()
                camera_mod.NAMES.update(names)
                cams = camera_mod.list_cameras(skip=skip)
            except Exception:  # noqa: BLE001
                cams = []
            self._found.emit(cams)

        threading.Thread(target=work, daemon=True).start()

    def _picked(self, _i):
        from .. import camera as camera_mod

        idx = self.combo.currentData()
        if idx == SIM_HEAD:
            self._open(idx)
            return
        self.profile.head_cam_index = -1 if idx is None else int(idx)
        self.profile.head_cam_name = "" if idx is None else camera_mod.NAMES.get(idx, "")
        self._save_profile()
        self._open(idx)

    def _open(self, idx):
        from ..headcam_cal import HeadCameraSource, SimHeadCamera

        if self.src is not None and getattr(self.src, "index", None) == idx:
            return
        self.close_src()
        if idx is None:
            self.update_state()
            return
        try:
            if idx == SIM_HEAD:
                self.src = SimHeadCamera(self.ctl.sim)
            else:
                self.src = HeadCameraSource(idx)
            self.plate.reserved = {idx} if isinstance(idx, int) else set()
        except Exception as exc:  # noqa: BLE001
            self.src = None
            self.state.setText(tr("Non riesco ad aprire la camera della testa: {0}", exc))
            return
        self.update_state()

    def close_src(self):
        if self.src is not None:
            self.src.close()
        self.src = None
        self.plate.reserved = set()

    # ---------------------------------------------------------------- stato
    def usable_cal(self):
        """La calibrazione, se vale per la camera aperta (stessa risoluzione)."""
        if self.cal is None or self.src is None:
            return None
        size = tuple(self.src.size) if self.src.size and self.src.size[0] else tuple(self.cal.size)
        return self.cal if tuple(self.cal.size) == size else None

    def head_machine(self):
        m = self.ctl.last_status.get("MPos") if self.ctl.connected else None
        return None if not m else np.array([float(m[0]), float(m[1])])

    def update_state(self):
        on = self.src is not None
        cal = self.usable_cal()
        ready = bool(self.ctl.connected) and self.calib is None
        self.b_cal.setEnabled(on and ready)
        for b in (self.b_laser, self.b_cross, self.b_origin, self.b_board):
            b.setEnabled(on and ready and cal is not None)
        if self.calib is not None:
            pass
        elif not on:
            self.state.setText(tr("Scegli la camera della testa dall'elenco."))
            self.video.clear(tr("Nessuna camera sulla testa"))
        elif self.cal is None:
            self.state.setText(tr("Da calibrare: metti uno scarto di cartone o legno sotto la testa e premi Calibra."))
        elif cal is None:
            self.state.setText(tr("La calibrazione è di un'altra risoluzione della camera: ricalibra."))
        else:
            self.state.setText(tr("Calibrata il {0}: mirino a {1:.2f}, {2:.2f} mm dal laser, {3:.3f} mm per pixel.",
                                  cal.when, cal.offset[0], cal.offset[1], cal.scale))
        self.cal_note.setText(tr("Se cambi molto lo spessore del pezzo la scala del video cambia: ricalibra. La "
                                 "distanza dal laser resta giusta se la camera guarda dritta in basso.")
                              if cal is not None else "")
        self.update_cross()

    def _bed_matrix(self):
        """Matrice che porta uno spostamento della macchina in uno spostamento sul piano mostrato."""
        p = self.profile
        a = np.array(p.from_machine_delta(1.0, 0.0), float)
        b = np.array(p.from_machine_delta(0.0, 1.0), float)
        return np.column_stack([a, b])

    def tick(self):
        if self.src is None or not self.isVisible():
            return
        f = self.src.get(after=0, timeout=0.0)
        if f is None:
            return
        cal = self.usable_cal()
        if cal is not None:
            k, flip = H.view_orientation(self._bed_matrix() @ cal.A)
            self.video.set_frame(f, k, flip, cal.scale)
        else:
            self.video.set_frame(f, 0, False, None)

    def update_cross(self):
        cv = getattr(self.win, "canvas", None)
        if cv is None or not hasattr(cv, "set_cam_cross"):
            return
        cal = self.usable_cal()
        M = self.head_machine()
        if cal is None or M is None or not self.chk_bed.isChecked():
            cv.set_cam_cross(None, None)
            return
        T = cal.crosshair(M)
        bx, by = self.profile.to_bed(float(T[0]), float(T[1]))
        cv.set_cam_cross(bx, by)

    def _cross_toggled(self, on):
        qs = getattr(self.win, "qs", None)
        if qs is not None:
            qs.setValue("head_cam_cross", "true" if on else "false")
        self.update_cross()

    # ---------------------------------------------------------------- spostamenti
    def _ready(self):
        if not self.ctl.connected:
            self.win.statusBar().showMessage(tr("Connetti la macchina per muovere la testa"), 4000)
            return False
        if self.ctl.job_active or self.ctl.checking or self.calib is not None:
            return False
        return True

    def move_head_machine(self, target, what):
        """Porta la testa al punto `target` (macchina). Fuori dal piano: niente (con il motivo). -> True se parte."""
        if not self._ready():
            return False
        bx, by = self.profile.to_bed(float(target[0]), float(target[1]))
        if not (-0.01 <= bx <= self.profile.bed_x + 0.01 and -0.01 <= by <= self.profile.bed_y + 0.01):
            self.win.statusBar().showMessage(tr("{0}: la testa dovrebbe andare fuori dall'area di lavoro ({1:.1f}, "
                                                "{2:.1f} mm). Niente spostamento.", what, bx, by), 8000)
            return False
        self.ctl.goto_machine(float(target[0]), float(target[1]), max(self.win.move.feed.value(), 3000))
        return True

    def laser_to_crosshair(self):
        cal, M = self.usable_cal(), self.head_machine()
        if cal is not None and M is not None:
            return self.move_head_machine(cal.crosshair(M), tr("Laser sul mirino"))
        return False

    def crosshair_to_laser(self):
        cal, M = self.usable_cal(), self.head_machine()
        if cal is not None and M is not None:
            return self.move_head_machine(cal.head_for_crosshair(M), tr("Mirino sul laser"))
        return False

    def crosshair_to_bed(self, x, y):
        """Il mirino va sul punto (x, y) del piano."""
        cal = self.usable_cal()
        if cal is None:
            self.win.statusBar().showMessage(tr("Calibra prima la camera della testa"), 4000)
            return False
        T = np.array(self.profile.to_machine(x, y), float)
        return self.move_head_machine(cal.head_for_crosshair(T), tr("Mirino qui"))

    def origin_at_crosshair(self):
        """Origine utente nel punto sotto il mirino, senza muovere la testa: la posizione di adesso vale −O."""
        cal = self.usable_cal()
        if cal is None or not self._ready():
            return False
        ox, oy = float(cal.offset[0]), float(cal.offset[1])
        self.ctl.send_line(f"G10 L20 P1 X{-ox:.3f} Y{-oy:.3f}")
        self.win.statusBar().showMessage(tr("Origine utente nel punto sotto il mirino"), 5000)
        return True

    def _video_clicked(self, u, v):
        if self.calib is not None:
            self.calib.click((u, v))
            return
        cal, M = self.usable_cal(), self.head_machine()
        if cal is None or M is None:
            return
        T = cal.px_to_machine(M, (u, v), self.src.size)
        self.move_head_machine(cal.head_for_crosshair(T), tr("Clic sul video"))

    # ---------------------------------------------------------------- calibrazione
    def calibrate(self):
        if self.src is None or not self._ready():
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Calibra la camera della testa"))
        lay = QVBoxLayout(dlg)
        t = QLabel(tr("1. Metti uno scarto di cartone o di legno sotto la testa, con il laser a fuoco.\n"
                      "2. Il laser incide un segno pieno di 1,6 mm dove è la testa adesso.\n"
                      "3. La camera trova il segno (la prima volta te lo chiede: porta la camera sopra il segno e "
                      "fai clic sul segno nel video) e la testa fa qualche piccolo spostamento.\n"
                      "Tieni gli occhiali di protezione: il laser si accende."))
        t.setWordWrap(True)
        lay.addWidget(t)
        f = QFormLayout()
        pw = QDoubleSpinBox()
        pw.setRange(1, 100)
        pw.setDecimals(0)
        pw.setSuffix(" %")
        qs = getattr(self.win, "qs", None)
        try:
            pw.setValue(float(qs.value("head_cam_power", H.MARK_POWER)) if qs is not None else H.MARK_POWER)
        except (TypeError, ValueError):
            pw.setValue(H.MARK_POWER)
        f.addRow(tr("Potenza del segno"), pw)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Incidi e calibra"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        self._cal_dialog = dlg
        if dlg.exec() == QDialog.Accepted:
            if qs is not None:
                qs.setValue("head_cam_power", pw.value())
            return self.start_calibration(pw.value())
        return None

    def start_calibration(self, power=H.MARK_POWER):
        from ..headcam_cal import HeadCamCalibration

        self.calib = HeadCamCalibration(self.ctl, self.src, self.profile, prior=self.usable_cal(), power=power)
        self.calib.progress.connect(self.state.setText)
        self.calib.need_click.connect(self._need_click)
        self.calib.marked.connect(lambda m: setattr(self.video, "marks", [m]))
        self.calib.finished.connect(self._finished)
        self.b_cal.hide()
        self.b_stop.show()
        self.update_state()
        self.state.setText(tr("Calibrazione in corso…"))
        self.calib.start()
        return self.calib

    def _need_click(self, text):
        self.state.setText(text)
        self.win.statusBar().showMessage(text, 15000)

    def cancel_calibration(self):
        if self.calib is not None:
            self.calib.cancel()

    def _finished(self, cal, msg):
        log = self.calib.log if self.calib is not None else []
        self.calib = None
        self.video.marks = []
        self.b_stop.hide()
        self.b_cal.show()
        if cal is not None:
            self.cal = cal
            self.profile.head_cam_cal = cal.to_dict()
            self._save_profile()
        self.update_state()
        self.state.setText(msg)
        try:
            from .. import camera as camera_mod

            for line in log:
                camera_mod.cam_log("camera di testa: " + line)
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------------- tavola da 2 angoli (fase 2)
    def crosshair_bed(self, auto=False):
        """Punto del piano sotto il mirino (con auto: lo spigolo trovato nell'immagine vicino al mirino, se è sicuro).
        -> ((x, y), nota) oppure (None, motivo)."""
        cal, M = self.usable_cal(), self.head_machine()
        if cal is None or M is None:
            return None, tr("serve la camera della testa calibrata e la macchina connessa")
        T = cal.crosshair(M)
        note = tr("mirino")
        if auto and self.src is not None:
            f = self.src.get(after=0, timeout=1.0)
            pt, conf = H.find_corner(f, cal.center(self.src.size), 0.25 * min(self.src.size))
            if pt is not None and conf >= 0.4:
                T = cal.px_to_machine(M, pt, self.src.size)
                note = tr("spigolo trovato nell'immagine (sicurezza {0:.0%})", conf)
            else:
                note = tr("spigolo non trovato con sicurezza: uso il mirino")
        return self.profile.to_bed(float(T[0]), float(T[1])), note

    def board_dialog(self):
        from .dialogs_board import BoardDialog

        dlg = BoardDialog(self)
        dlg.show()
        self._board_dlg = dlg
        return dlg

    def shutdown(self):
        if self.calib is not None:
            self.calib.cancel()
        self.timer.stop()
        self.close_src()
