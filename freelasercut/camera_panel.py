# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Pannello Camera: scelta della telecamera, foto sul piano, calibrazione AutoCam."""
import os
import threading
import time

import cv2
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QSlider,
    QToolButton, QVBoxLayout, QWidget,
)

from .camera import SIM_CAMERA, AutoCam, CameraSource, SimCamera, camera_file, list_cameras
from .camera_calib import CameraModel
from .theme import C, css
from freelasercut.i18n import tr  # noqa: E402

PPM = 2.0  # risoluzione della foto raddrizzata: 2 pixel per mm


def to_qimage(bgr):
    h, w = bgr.shape[:2]
    return QImage(bgr.data, w, h, bgr.strides[0], QImage.Format_BGR888).copy()


class CameraPanel(QWidget):
    _found = Signal(object)

    def __init__(self, ctl, window):
        super().__init__()
        from .app import card, muted  # import locale per evitare cicli

        self.ctl = ctl
        self.win = window
        self.src = None
        self.model = None
        self.saved = None  # dati della calibrazione salvata
        self.autocam = None
        self.detected = []
        self.cameras = []
        self._searching = False
        if os.path.exists(camera_file()):
            try:
                self.model, self.saved = CameraModel.load(camera_file())
            except (OSError, ValueError, KeyError, TypeError):
                self.model, self.saved = None, None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        # --- scelta camera
        cc_, cl = card(tr("Telecamera"))
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setIconSize(QSize(96, 54))
        self.combo.setMinimumHeight(62)
        self.combo.currentIndexChanged.connect(self.on_select)
        self.combo.activated.connect(self._remember_choice)  # solo le scelte fatte dalla persona
        self.btn_search = QToolButton()
        self.btn_search.setText("⟳")
        self.btn_search.setToolTip(tr("Cerca di nuovo le telecamere USB"))
        self.btn_search.clicked.connect(lambda: self.search(manual=True))
        row.addWidget(self.combo, 1)
        row.addWidget(self.btn_search)
        cl.addLayout(row)
        self.state = muted(tr("Cerco le telecamere…"))
        cl.addWidget(self.state)
        lay.addWidget(cc_)

        # --- foto sul piano
        fc, fl = card(tr("Foto sul piano"))
        self.chk_live = QCheckBox(tr("Mostra la foto sotto il piano di lavoro (aggiornata dal vivo)"))
        self.chk_live.toggled.connect(self.on_live)
        fl.addWidget(self.chk_live)
        orow = QHBoxLayout()
        orow.addWidget(muted(tr("Opacità")))
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.setValue(85)
        self.opacity.valueChanged.connect(lambda v: self.win.bed.set_camera_opacity(v / 100))
        orow.addWidget(self.opacity, 1)
        self.btn_shot = QPushButton(tr("Scatta ora"))
        self.btn_shot.clicked.connect(self.snapshot)
        orow.addWidget(self.btn_shot)
        fl.addLayout(orow)
        fl.addWidget(muted(tr("Con la foto attiva, fai doppio clic sul tuo pezzo: la testa va esattamente lì.")))
        lay.addWidget(fc)

        # --- calibrazione
        kc, kl = card(tr("Calibrazione AutoCam"))
        kl.addWidget(muted(tr("Un solo pulsante: la testa visita 25 punti del piano e accende il laser all'1% per un "
                           "istante, la camera misura i puntini e FreeLaserCut corregge lente e prospettiva. Se il "
                           "puntino non si vede, passa da sola al bersaglio inciso su cartone.")))
        mrow = QHBoxLayout()
        self.method = QComboBox()
        self.method.addItem(tr("Automatico (consigliato)"), "auto")
        self.method.addItem(tr("Solo puntino laser (non incide)"), "spot")
        self.method.addItem(tr("Solo bersaglio inciso su cartone"), "target")
        mrow.addWidget(self.method, 1)
        kl.addLayout(mrow)
        brow = QHBoxLayout()
        self.btn_cal = QPushButton(tr("◎  Calibra automaticamente"))
        self.btn_cal.setObjectName("primary")
        self.btn_cal.clicked.connect(self.calibrate)
        self.btn_cancel = QPushButton(tr("Annulla"))
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.clicked.connect(self.cancel_calibration)
        self.btn_cancel.hide()
        brow.addWidget(self.btn_cal, 1)
        brow.addWidget(self.btn_cancel)
        kl.addLayout(brow)
        # 0.17.5: se il riconoscimento dei dischi incisi sbaglia (macchie fuori dal cartone), i punti si mettono a mano
        self.btn_manual = QPushButton(tr("Metti i punti a mano sui dischi incisi…"))
        self.btn_manual.setToolTip(tr("Il cartone con i dischi della calibrazione deve essere ancora dove è stato inciso: "
                                      "la testa si sposta fuori dall'inquadratura, la camera fa una foto e tu metti i "
                                      "cerchietti sui dischi, uno alla volta, con FreeLaserCut che ti dice quale"))
        self.btn_manual.clicked.connect(self.manual_points)
        kl.addWidget(self.btn_manual)
        self.cal_bar = QProgressBar()
        self.cal_bar.hide()
        kl.addWidget(self.cal_bar)
        self.cal_text = muted("")
        kl.addWidget(self.cal_text)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(190)
        self.preview.setStyleSheet(css(f"background:#080D18; border:1px solid {C['border']}; border-radius:8px;"))
        kl.addWidget(self.preview)
        lay.addWidget(kc)
        lay.addStretch(1)

        self._found.connect(self.on_found)
        self._cal_after_home = False
        ctl.homed_changed.connect(self._on_homed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(450)
        ctl.connection_changed.connect(lambda ok, m: QTimer.singleShot(300, self.search))
        self.update_state()
        QTimer.singleShot(500, self.search)

    # ---------------------------------------------------------------- scelta ricordata
    def choice(self):
        """Scelta salvata: "none" (nessuna telecamera), un indice, oppure None (mai scelto)."""
        qs = getattr(self.win, "qs", None)
        v = qs.value("camera_choice") if qs is not None else None
        if v in (None, ""):
            return None
        if str(v) == "none":
            return "none"
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _remember_choice(self, _i):
        qs = getattr(self.win, "qs", None)
        if qs is None:
            return
        idx = self.combo.currentData()
        if idx == SIM_CAMERA:
            return  # la camera simulata non è una scelta da ricordare
        qs.setValue("camera_choice", "none" if idx is None else int(idx))

    # ---------------------------------------------------------------- ricerca
    def search(self, manual=False):
        if self._searching or self.autocam is not None:
            return
        if not manual and self.choice() == "none" and self.ctl.sim is None:
            # «Nessuna telecamera» scelta dalla persona: all'avvio e alla connessione non apro nessuna camera
            # (cercarle accende per un attimo anche la webcam del PC). Il pulsante ⟳ cerca comunque.
            self.combo.blockSignals(True)
            self.combo.clear()
            self.combo.addItem(tr("Nessuna telecamera"), None)
            self.combo.blockSignals(False)
            self._close_src()
            self.update_state()
            self.state.setText(tr("Telecamera spenta (scelta tua). Per usarne una premi ⟳ e sceglila."))
            return
        self._searching = True
        self.state.setText(tr("Cerco le telecamere…"))
        skip = set()
        if self.src is not None and self.src.index != SIM_CAMERA:
            skip.add(self.src.index)

        def work():
            try:
                cams = list_cameras(skip=skip)
            except Exception:  # noqa: BLE001
                cams = []
            self._found.emit(cams)

        threading.Thread(target=work, daemon=True).start()

    def on_found(self, cams):
        self._searching = False
        current = self.combo.currentData()
        if self.src is not None and self.src.index != SIM_CAMERA:
            frame = self.src.get(after=0, timeout=0.5)
            if frame is not None:
                h, w = frame.shape[:2]
                cams = sorted(cams + [(self.src.index, f"Camera {self.src.index}  ·  {w}×{h}", (w, h),
                                       cv2.resize(frame, (160, 90)))], key=lambda c: c[0])
        if current == SIM_CAMERA and self.ctl.sim is None:
            current = None
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(tr("Nessuna telecamera"), None)
        for idx, label, size, thumb in cams:
            self.combo.addItem(QIcon(QPixmap.fromImage(to_qimage(thumb))), label, idx)
        if self.ctl.sim is not None:
            self.combo.addItem(tr("Camera simulata (per provare AutoCam)"), SIM_CAMERA)
        self.combo.blockSignals(False)
        want = current
        choice = self.choice()
        if want is None and isinstance(choice, int):
            want = choice  # l'ultima camera scelta dalla persona
        if want is None and choice is None and self.saved is not None:
            want = self.saved.get("camera_index")
        if want is None and choice != "none":
            real = [c[0] for c in cams]
            if len(real) == 1 and choice is None:
                want = real[0]  # una sola camera e nessuna scelta fatta: la scelgo io
            elif self.ctl.sim is not None and not real:
                want = SIM_CAMERA
        i = self.combo.findData(want) if want is not None else -1
        self.combo.setCurrentIndex(max(i, 0))
        if i <= 0:
            self.on_select(self.combo.currentIndex())
        n = len(cams)
        if not n and self.ctl.sim is None:
            self.state.setText(tr("Nessuna telecamera trovata. Collegala alla USB e premi ⟳."))

    def on_select(self, _i):
        idx = self.combo.currentData()
        if self.src is not None and getattr(self.src, "index", None) == idx and idx != SIM_CAMERA:
            return
        self._close_src()
        if idx is None:
            self.update_state()
            return
        try:
            self.src = SimCamera(self.ctl.sim) if idx == SIM_CAMERA else CameraSource(idx)
        except Exception as exc:  # noqa: BLE001
            self.src = None
            self.state.setText(tr("Non riesco ad aprire la camera: {0}", exc))
            return
        if self.saved is not None and self.saved.get("camera_index") != idx:
            # su un altro PC la stessa camera può avere un numero diverso: se la risoluzione è quella della
            # calibrazione è (quasi certamente) lei, e la calibrazione resta valida finché la camera non si sposta
            f = self.src.get(after=0, timeout=2.0) if idx != SIM_CAMERA else None
            size = [f.shape[1], f.shape[0]] if f is not None else None
            if size is not None and list(self.saved.get("frame_size", [])) == size:
                if self.model is None:
                    self.model, self.saved = CameraModel.load(camera_file())
                self.saved["camera_index"] = idx
                try:
                    self.model.save(camera_file(), {k: v for k, v in self.saved.items()
                                                    if k in ("camera_index", "method")})
                except OSError:
                    pass
            else:
                self.model = None  # calibrazione di un'altra camera
        elif self.saved is not None and self.model is None:
            self.model, self.saved = CameraModel.load(camera_file())
        self.update_state()
        if self.model is not None:
            self.chk_live.setChecked(True)

    def _close_src(self):
        if self.src is not None:
            self.src.close()
        self.src = None

    def update_state(self):
        cam_ok = self.src is not None
        cal_ok = self.model is not None
        self.chk_live.setEnabled(cam_ok and cal_ok)
        self.btn_shot.setEnabled(cam_ok and cal_ok)
        self.btn_cal.setEnabled(cam_ok and self.ctl.connected and self.autocam is None)
        self.btn_manual.setEnabled(cam_ok and self.ctl.connected and self.autocam is None)
        if not cam_ok:
            self.state.setText(tr("Nessuna telecamera selezionata"))
        elif cal_ok:
            m = self.model
            how = (self.saved or {}).get("method", "")
            self.state.setText(tr("✓ Calibrata il {0} ({1})  ·  precisione ±{2:.2f} mm", m.created, how, m.rms_mm))
            self.state.setStyleSheet(f"color:{C['success']};")
        else:
            self.state.setText(tr("Camera pronta, non ancora calibrata: premi «Calibra automaticamente»"))
            self.state.setStyleSheet(f"color:{C['warn']};")
        if not self.ctl.connected and cam_ok and not cal_ok:
            self.cal_text.setText(tr("Connetti la macchina per calibrare."))

    # ---------------------------------------------------------------- immagini
    def tick(self):
        if self.src is None or not self.isVisible() and not self.chk_live.isChecked():
            return
        frame = self.src.get(after=0, timeout=0.05)
        if frame is None:
            return
        if self.model is not None and tuple(self.model.frame_size) != tuple(self.src.size):
            self.state.setText(tr("La risoluzione della camera è cambiata: ricalibra"))
        if self.isVisible():
            self._show_preview(frame)
        if self.chk_live.isChecked() and self.model is not None:
            self._show_on_bed(frame)

    def _show_preview(self, frame):
        view = frame.copy()
        for u, v in self.detected:
            cv2.circle(view, (int(u), int(v)), 10, (60, 220, 60), 2, cv2.LINE_AA)
        w = max(self.preview.width() - 8, 200)
        h = int(view.shape[0] * w / view.shape[1])
        self.preview.setPixmap(QPixmap.fromImage(to_qimage(cv2.resize(view, (w, h)))))

    def _show_on_bed(self, frame):
        top = self.model.rectify(frame, PPM)
        self.win.bed.set_camera_image(to_qimage(top), PPM, self.opacity.value() / 100)

    def snapshot(self):
        if self.src is None or self.model is None:
            return
        frame = self.src.get(after=time.time(), timeout=2)
        if frame is not None:
            self._show_on_bed(frame)

    def on_live(self, on):
        if not on:
            self.win.bed.clear_camera()
        else:
            self.snapshot()

    # ---------------------------------------------------------------- calibrazione
    def _ready_for_machine(self, after_home):
        """Controlli comuni prima di muovere la testa per la camera. after_home: cosa rifare dopo l'homing."""
        if self.src is None or not self.ctl.connected:
            return False
        if self.ctl.job_active:
            QMessageBox.warning(self, tr("AutoCam"), tr("C'è un lavoro in corso."))
            return False
        if not self.ctl.homed:
            ans = QMessageBox.question(
                self, tr("AutoCam"),
                tr("Prima serve l'homing: la calibrazione si basa sulle coordinate assolute della macchina.\n\n"
                "Faccio l'homing adesso? Al termine la calibrazione parte da sola."))
            if ans == QMessageBox.Yes:
                self._cal_after_home = after_home
                self.ctl.home()
            return False
        if self.ctl.last_status.get("state") == "Alarm":
            QMessageBox.warning(self, tr("AutoCam"), tr("La macchina è in allarme: sblocca o fai l'homing prima."))
            return False
        return True

    def manual_points(self):
        """0.17.5: foto dei dischi già incisi (testa parcheggiata) e punti messi a mano."""
        if not self._ready_for_machine(self.manual_points):
            return
        ans = QMessageBox.question(
            self, tr("Punti a mano"),
            tr("Il cartone con i dischi incisi dalla calibrazione deve essere ancora dove è stato inciso, e la camera "
               "non deve essersi spostata.\n\nLa testa si sposta fuori dall'inquadratura (laser spento), la camera fa "
               "una foto e poi metti tu i cerchietti sui dischi: FreeLaserCut ti dice quale cercare.\n\nProcedo?"))
        if ans != QMessageBox.Yes:
            return
        self._start_autocam("photo")

    def _start_autocam(self, method):
        self.detected = []
        self.autocam = AutoCam(self.ctl, self.src, self.win.profile, grid_n=5, method=method)
        park = (self.saved or {}).get("park")
        if method == "photo" and isinstance(park, (list, tuple)) and len(park) == 2:
            self.autocam.park_hint = tuple(float(v) for v in park)
        self.autocam.progress.connect(self.on_progress)
        self.autocam.detected.connect(self.on_detected)
        self.autocam.need_user.connect(self.on_need_user)
        self.autocam.photo_ready.connect(self.open_points)
        self.autocam.finished.connect(self.on_finished)
        self.chk_live.setChecked(False)
        self.btn_cal.setEnabled(False)
        self.btn_manual.setEnabled(False)
        self.btn_cancel.show()
        self.cal_bar.show()
        self.cal_bar.setValue(0)
        self.method.setEnabled(False)
        self.combo.setEnabled(False)
        self.autocam.start()

    def open_points(self, ac):
        """Finestra dei punti a mano sulla foto dei dischi (dopo la calibrazione o dalla foto nuova)."""
        from .camera_calib import seq_grid
        from .ui.dialogs_campoints import CameraPointsDialog

        if ac is None or ac.last_photo is None:
            return None
        p = self.win.profile
        dlg = CameraPointsDialog(ac.last_photo, seq_grid(p.bed_x, p.bed_y), (p.bed_x, p.bed_y), ac.guess, self)
        self._points_dlg = dlg
        ok = dlg.exec() == QDialog.Accepted and dlg.model is not None
        self._points_dlg = None
        if not ok:
            return None
        model = dlg.model
        extra = {"camera_index": self.combo.currentData(), "method": "punti a mano"}
        if ac.park is not None:
            extra["park"] = [float(v) for v in ac.park]
        model.save(camera_file(), extra)
        self.model, self.saved = CameraModel.load(camera_file())
        self.chk_live.setChecked(True)
        msg = tr("Calibrazione con i punti a mano: {0} punti, precisione ±{1:.2f} mm (peggiore {2:.2f} mm)",
                 model.n_points or len(dlg.pairs()), model.rms_mm, model.max_mm)
        self.cal_text.setText(msg)
        self.update_state()
        QMessageBox.information(self, tr("AutoCam"), msg + tr("\n\nLa foto del piano ora è raddrizzata e in scala 1:1."))
        return model

    def calibrate(self):
        if self.src is None or not self.ctl.connected:
            return
        if self.ctl.job_active:
            QMessageBox.warning(self, tr("AutoCam"), tr("C'è un lavoro in corso."))
            return
        st = self.ctl.last_status.get("state")
        if not self.ctl.homed:
            ans = QMessageBox.question(
                self, tr("AutoCam"),
                tr("Prima serve l'homing: la calibrazione si basa sulle coordinate assolute della macchina.\n\n"
                "Faccio l'homing adesso? Al termine la calibrazione parte da sola."))
            if ans == QMessageBox.Yes:
                self._cal_after_home = True
                self.ctl.home()
            return
        if st == "Alarm":
            QMessageBox.warning(self, tr("AutoCam"), tr("La macchina è in allarme: sblocca o fai l'homing prima."))
            return
        method = self.method.currentData()
        txt = (tr("La testa visiterà 25 punti del piano. In ogni punto il laser si accende "
               "all'1–3% per circa due secondi.\n") if method != "target" else
               tr("La testa farà prima un giro del piano a laser spento per capire quale zona vede la camera, "
               "poi inciderà piccoli cerchi su un cartone solo in quella zona.\n"))
        ans = QMessageBox.question(
            self, tr("Calibrazione AutoCam"),
            txt + tr("\nPrima di iniziare:\n•  non spostare la camera durante la calibrazione\n"
                  "•  luce della stanza stabile (niente sole diretto sul piano)\n"
                  "•  occhiali protettivi per 450 nm indossati\n\nIniziare?"))
        if ans != QMessageBox.Yes:
            return
        self._start_autocam(method)

    def _on_homed(self, homed, _negative):
        if homed and self._cal_after_home:
            then = self._cal_after_home
            self._cal_after_home = False
            QTimer.singleShot(500, then if callable(then) else self.calibrate)

    def cancel_calibration(self):
        if self.autocam is not None:
            self.autocam.cancel()

    def on_progress(self, i, total, text):
        self.cal_bar.setMaximum(max(total, 1))
        self.cal_bar.setValue(i)
        self.cal_text.setText(text)

    def on_detected(self, pts):
        self.detected = list(pts)

    def on_need_user(self, text):
        box = QMessageBox(self)
        box.setWindowTitle(tr("AutoCam"))
        box.setIcon(QMessageBox.Information)
        box.setText(text)
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.button(QMessageBox.Ok).setText(tr("Continua"))
        box.button(QMessageBox.Cancel).setText(tr("Annulla"))
        if box.exec() == QMessageBox.Ok:
            self.autocam.continue_()
        else:
            self.autocam.cancel()

    def on_finished(self, model, msg):
        ac = self.autocam
        self.autocam = None
        self.win.bed.clear_trail()  # via i segnini dei puntini di calibrazione
        self.btn_cancel.hide()
        self.method.setEnabled(True)
        self.combo.setEnabled(True)
        if ac is not None and ac.method == "photo":  # la finestra dei punti l'ha già aperta photo_ready
            self.cal_bar.hide()
            if msg:
                self.cal_text.setText(msg)
            self.update_state()
            return
        self.cal_text.setText(msg)
        can_fix = ac is not None and ac.last_photo is not None  # bersaglio inciso: i punti si possono correggere
        if model is not None:
            extra = {"camera_index": self.combo.currentData(), "method": ac.used_method}
            if ac.park is not None:
                extra["park"] = [float(v) for v in ac.park]
            model.save(camera_file(), extra)
            self.model, self.saved = CameraModel.load(camera_file())
            self.cal_bar.setValue(self.cal_bar.maximum())
            self.chk_live.setChecked(True)
            box = QMessageBox(self)
            box.setWindowTitle(tr("AutoCam"))
            box.setIcon(QMessageBox.Information)
            box.setText(msg + tr("\n\nLa foto del piano ora è raddrizzata e in scala 1:1."))
            fix = None
            if can_fix:
                box.setInformativeText(tr("Se sulla foto del piano qualcosa non torna (per esempio macchie fuori dal "
                                          "cartone prese per dischi), controlla e correggi i punti a mano."))
                fix = box.addButton(tr("Controlla i punti a mano…"), QMessageBox.ActionRole)
            box.addButton(QMessageBox.Ok)
            box.exec()
            if fix is not None and box.clickedButton() is fix:
                self.update_state()
                self.open_points(ac)
        else:
            self.cal_bar.hide()
            if can_fix and not ac._cancel.is_set() and QMessageBox.question(
                    self, tr("AutoCam"), msg + tr("\n\nI dischi sono stati incisi: vuoi mettere tu i punti sulla foto?"),
                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                self.update_state()
                self.open_points(ac)
        self.update_state()

    def shutdown(self):
        if self.autocam is not None:
            self.autocam.cancel()
        self.timer.stop()
        self._close_src()
