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

from . import camera as camera_mod
from . import plate_photo
from .camera import (
    PHONE_CAMERA, SIM_CAMERA, AutoCam, CameraSource, NetCamera, PhonePhoto, SimCamera, camera_file, is_net, list_cameras,
)
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
        self.phone_top = None  # 0.19.0: la foto dal telefono già raddrizzata sull'area di lavoro
        self.phone_corners = None
        self._plate_dlg = None
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
        # 0.18.1: telecamera di rete (Creality Falcon A1 Pro, A1C, T1, o qualsiasi indirizzo di una foto)
        self.btn_net = QToolButton()
        self.btn_net.setText("🌐")
        self.btn_net.setToolTip(tr("Telecamera di rete: per i laser che mandano la foto in rete (Creality Falcon "
                                   "A1 Pro, A1C, T1) o un indirizzo scritto a mano"))
        self.btn_net.clicked.connect(self.add_net_camera)
        row.addWidget(self.combo, 1)
        row.addWidget(self.btn_search)
        row.addWidget(self.btn_net)
        cl.addLayout(row)
        self.state = muted(tr("Cerco le telecamere…"))
        cl.addWidget(self.state)
        # 0.19.0: con «Foto del piano dal telefono» un collegamento discreto apre il codice QR del telefono
        self.phone_link = QLabel()
        self.phone_link.setTextFormat(Qt.RichText)
        self.phone_link.setText(f"<a href='#' style='color:{C['accent_hi']}'>" + tr("Apri il codice QR per il telefono")
                                + "</a>")
        self.phone_link.setCursor(Qt.PointingHandCursor)
        self.phone_link.linkActivated.connect(lambda *_: self.open_phone())
        self.phone_link.hide()
        cl.addWidget(self.phone_link)
        self.b_again = QPushButton(tr("Indica di nuovo i 4 angoli…"))
        self.b_again.clicked.connect(lambda: self.align_phone_photo())
        self.b_again.hide()
        cl.addWidget(self.b_again)
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
        # 0.19.0: la telecamera così com'è, senza calibrarla: per guardare il piano, non per posizionare
        self.method.addItem(tr("Mostra senza calibrazione"), "raw")
        self.method.setItemData(self.method.count() - 1,
                                tr("La telecamera si vede sotto il piano così com'è, senza calibrazione: utile per "
                                   "dare un'occhiata. Non è allineata al piano: non usarla per posizionare i pezzi."),
                                Qt.ToolTipRole)
        qs_ = getattr(window, "qs", None)
        if qs_ is not None and qs_.value("camera_raw", "false") in (True, "true"):
            self.method.setCurrentIndex(self.method.findData("raw"))
        self.method.currentIndexChanged.connect(self._method_changed)
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
        if is_net(str(v)):
            return str(v)
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _remember_choice(self, _i):
        qs = getattr(self.win, "qs", None)
        if qs is None:
            return
        idx = self.combo.currentData()
        if idx in (SIM_CAMERA, PHONE_CAMERA):
            return  # la camera simulata e la foto dal telefono non sono scelte da ricordare
        qs.setValue("camera_choice", "none" if idx is None else idx if is_net(idx) else int(idx))

    # ---------------------------------------------------------------- ricerca
    def search(self, manual=False):
        if self._searching or self.autocam is not None:
            return
        if not manual and self.choice() == "none" and self.ctl.sim is None:
            # «Nessuna telecamera» scelta dalla persona: all'avvio e alla connessione non apro nessuna camera
            # (cercarle accende per un attimo anche la webcam del PC). Il pulsante ⟳ cerca comunque.
            self.combo.blockSignals(True)
            keep_phone = self.is_phone()
            self.combo.clear()
            self.combo.addItem(tr("Nessuna telecamera"), None)
            self.combo.addItem(tr("📱 Foto del piano dal telefono"), PHONE_CAMERA)
            if keep_phone:
                self.combo.setCurrentIndex(1)
            self.combo.blockSignals(False)
            if keep_phone:
                self.update_state()
                return
            self._close_src()
            self.update_state()
            self.state.setText(tr("Telecamera spenta (scelta tua). Per usarne una premi ⟳ e sceglila."))
            return
        self._searching = True
        self.state.setText(tr("Cerco le telecamere…"))
        skip = set()
        if self.src is not None and isinstance(self.src.index, int) and self.src.index != SIM_CAMERA:
            if manual and getattr(self.src, "black", False):
                camera_mod.LAST_PROBE.pop(self.src.index, None)
                self._close_src()  # immagine nera: con ⟳ la riapro e provo di nuovo tutti i modi di lettura
            else:
                skip.add(self.src.index)
        laser_port = getattr(self.ctl, "port", None)
        open_net = self.src.index if self.src is not None and is_net(self.src.index) else None
        known = self.net_list()  # QSettings si legge qui, nel thread della finestra
        self.combo.setEnabled(False)  # niente scelte durante la ricerca: la stessa camera aperta due volte

        def work():
            try:
                names = camera_mod.usb_camera_names()
                camera_mod.NAMES.clear()
                camera_mod.NAMES.update(names)
            except Exception:  # noqa: BLE001
                pass
            try:
                cams = list_cameras(skip=skip)
            except Exception:  # noqa: BLE001
                cams = []
            try:
                cams = list(cams) + self._auto_net(laser_port, open_net, known)
            except Exception:  # noqa: BLE001
                pass
            self._found.emit(cams)

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- telecamere di rete
    def net_list(self):
        qs = getattr(self.win, "qs", None)
        v = qs.value("net_cameras") if qs is not None else None
        if isinstance(v, str):
            v = [v]
        return [u for u in (v or []) if is_net(u)]

    def _save_net(self, url):
        qs = getattr(self.win, "qs", None)
        if qs is None:
            return
        lst = [u for u in self.net_list() if u != url]
        qs.setValue("net_cameras", [url] + lst[:7])

    def _auto_net(self, laser_port, open_net, known=()):
        """Nel thread della ricerca: i Falcon col cavo USB (192.168.10.1) o in Wi-Fi rispondono sulla porta 8080?
        Le telecamere di rete già usate si mettono nell'elenco senza chiedere foto (il server è lento)."""
        out, seen = [], set()
        import urllib.parse

        open_host = urllib.parse.urlsplit(open_net).hostname if open_net else None
        for host in camera_mod.auto_net_candidates(laser_port):
            url = camera_mod.net_url(host)
            if host == open_host or not camera_mod.port_open(host):
                continue  # la telecamera di rete aperta ora non si interroga anche da qui
            model = camera_mod.device_info(host)
            _u, img, why = camera_mod.probe_net(url)
            camera_mod.cam_log(f"rete trovata {host}: {model or 'modello non detto'} · {why}")
            if img is not None:
                h, w = img.shape[:2]
                label = tr("{0} (rete {1})  ·  {2}×{3}", model or tr("Telecamera"), host, w, h)
                out.append((url, label, (w, h), cv2.resize(img, (160, 90))))
                seen.add(url)
        for url in known:
            if url not in seen and url != open_net:
                out.append((url, tr("Rete  ·  {0}", url), None, None))
        return out

    def add_net_camera(self):
        from .ui.dialogs_netcam import NetCameraDialog

        dlg = NetCameraDialog(self, getattr(self.ctl, "port", None), self.net_list())
        if dlg.exec() != QDialog.Accepted or not dlg.url:
            return
        url = dlg.url
        self._save_net(url)
        qs = getattr(self.win, "qs", None)
        if qs is not None:
            qs.setValue("camera_choice", url)
        i = self.combo.findData(url)
        if i < 0:
            thumb = dlg.image
            if thumb is not None:
                self.combo.addItem(QIcon(QPixmap.fromImage(to_qimage(cv2.resize(thumb, (160, 90))))),
                                   tr("Rete  ·  {0}", url), url)
            else:
                self.combo.addItem(tr("Rete  ·  {0}", url), url)
            i = self.combo.findData(url)
        self.combo.setCurrentIndex(i)

    def on_found(self, cams):
        self._searching = False
        self.combo.setEnabled(True)
        current = self.combo.currentData()
        if self.src is not None and self.src.index not in (SIM_CAMERA, PHONE_CAMERA):
            frame = self.src.get(after=0, timeout=0.5)
            if frame is not None:
                h, w = frame.shape[:2]
                label = (tr("Rete  ·  {0}", self.src.index) if is_net(self.src.index)
                         else camera_mod.camera_label(self.src.index, w, h, getattr(self.src, "black", False),
                                                      getattr(self.src, "mode", None)))
                cams = cams + [(self.src.index, label, (w, h), cv2.resize(frame, (160, 90)))]
            elif is_net(self.src.index):
                cams = cams + [(self.src.index, tr("Rete  ·  {0}", self.src.index), None, None)]
        usb = sorted([c for c in cams if isinstance(c[0], int)], key=lambda c: c[0])
        cams = usb + [c for c in cams if not isinstance(c[0], int)]
        if current == SIM_CAMERA and self.ctl.sim is None:
            current = None
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(tr("Nessuna telecamera"), None)
        for idx, label, size, thumb, *_ in cams:
            if thumb is None:
                self.combo.addItem(label, idx)
            else:
                self.combo.addItem(QIcon(QPixmap.fromImage(to_qimage(thumb))), label, idx)
        self.combo.addItem(tr("📱 Foto del piano dal telefono"), PHONE_CAMERA)
        if self.ctl.sim is not None:
            self.combo.addItem(tr("Camera simulata (per provare AutoCam)"), SIM_CAMERA)
        self.combo.blockSignals(False)
        want = current
        choice = self.choice()
        if want is None and isinstance(choice, int):
            want = choice  # l'ultima camera scelta dalla persona
        if want is None and is_net(choice):
            want = choice
        if want is None and choice is None and self.saved is not None:
            want = self.saved.get("camera_index")
        if want is None and choice != "none":
            real = [c[0] for c in cams if c[3] is not None]
            laser = camera_mod.preferred_camera([c for c in real if isinstance(c, int)])
            nets = [c for c in real if is_net(c)]
            if choice is None and laser is not None:
                want = laser  # 0.18.1: la telecamera del laser (per nome, per esempio «Creality Falcon Camera»)
            elif choice is None and nets:
                want = nets[0]  # la telecamera di rete del Falcon trovata da sola
            elif len(real) == 1 and choice is None:
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
        self.phone_top = self.phone_corners = None
        if idx is None:
            self.update_state()
            if self.chk_live.isChecked():
                self.chk_live.setChecked(False)
            return
        if idx == PHONE_CAMERA:  # la foto arriva dal telefono: niente da aprire e niente calibrazione AutoCam
            self.src = PhonePhoto()
            self.phone_top = self.phone_corners = None
            self.win.bed.clear_camera()
            self.chk_live.setChecked(False)
            self.update_state()
            return
        try:
            if idx == SIM_CAMERA:
                self.src = SimCamera(self.ctl.sim)
            elif is_net(idx):
                self.src = NetCamera(idx)
            else:
                self.src = CameraSource(idx)
        except Exception as exc:  # noqa: BLE001
            self.src = None
            self.state.setText(tr("Non riesco ad aprire la camera: {0}", exc))
            return
        if self.saved is not None and self.saved.get("camera_index") != idx:
            # su un altro PC la stessa camera può avere un numero diverso: se la risoluzione è quella della
            # calibrazione è (quasi certamente) lei, e la calibrazione resta valida finché la camera non si sposta
            # una telecamera di rete manda la prima foto dopo qualche secondo: qui non la aspetto (la finestra
            # resterebbe ferma); la calibrazione salvata vale solo se era proprio di questa telecamera
            f = self.src.get(after=0, timeout=2.0) if idx != SIM_CAMERA and not is_net(idx) else None
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
        elif self.chk_live.isChecked() and not self.can_show():
            self.chk_live.setChecked(False)  # 0.19.0: quello che c'era sotto il piano era di un'altra sorgente

    def _close_src(self):
        if self.src is not None:
            self.src.close()
        self.src = None

    # ---------------------------------------------------------------- senza calibrazione, foto dal telefono (0.19.0)
    def is_phone(self):
        return self.src is not None and getattr(self.src, "index", None) == PHONE_CAMERA

    def is_raw(self):
        return self.method.currentData() == "raw" and not self.is_phone()

    def can_show(self):
        """C'è qualcosa da mettere sotto il piano? Foto dal telefono allineata, telecamera senza calibrazione, oppure
        telecamera calibrata."""
        if self.src is None:
            return False
        if self.is_phone():
            return self.phone_top is not None
        return self.is_raw() or self.model is not None

    def bed_size(self):
        p = self.win.profile
        return (float(p.bed_x), float(p.bed_y))

    def _method_changed(self, *_):
        qs = getattr(self.win, "qs", None)
        if qs is not None:
            qs.setValue("camera_raw", self.method.currentData() == "raw")
        self.update_state()
        if self.chk_live.isChecked():
            if self.can_show():
                self.snapshot()
            else:  # tolto «senza calibrazione» e la telecamera non è calibrata: sotto il piano non resta niente
                self.chk_live.setChecked(False)

    def open_phone(self):
        """«Apri il codice QR per il telefono»: la finestra del controllo dal telefono (lì si accende la pagina)."""
        fn = getattr(self.win, "phone_dialog", None)
        return fn() if fn is not None else None

    def plate_photo(self, data):
        """Una foto del piano arrivata dal telefono. -> True se è una foto (e si passa ai 4 angoli)."""
        frame = plate_photo.decode(data)
        if frame is None:
            self.win.statusBar().showMessage(tr("Dal telefono è arrivato un file che non è una foto."), 8000)
            return False
        i = self.combo.findData(PHONE_CAMERA)
        if not self.is_phone() and i >= 0:
            self.combo.setCurrentIndex(i)  # chi manda la foto dal telefono vuole vederla: scelgo io la voce
        if not self.is_phone():
            return False
        self.src.set(frame)
        self.phone_top = self.phone_corners = None
        self.update_state()
        self.win.statusBar().showMessage(tr("Foto del piano arrivata dal telefono: indica i 4 angoli dell'area di "
                                            "lavoro."), 10000)
        if not os.environ.get("FLC_NO_DIALOGS"):
            self.align_phone_photo()
        return True

    def align_phone_photo(self, corners=None):
        """I 4 angoli dell'area di lavoro sulla foto del telefono: con una finestra, oppure dati (prove, comandi).
        -> True se la foto è stata raddrizzata e messa sotto il piano."""
        frame = self.src.get() if self.is_phone() else None
        if frame is None:
            return False
        if corners is None:
            from .ui.dialogs_plate import PlateCornersDialog

            dlg = self._plate_dlg = PlateCornersDialog(frame, self.bed_size(), self.win)
            ok = dlg.exec() == QDialog.Accepted
            corners = dlg.corners() if ok else None
            self._plate_dlg = None
        if corners is None or plate_photo.check_corners(corners, (frame.shape[1], frame.shape[0])) is not None:
            return False
        self.phone_corners = [tuple(c) for c in corners]
        self.phone_top = plate_photo.rectify(frame, self.phone_corners, self.bed_size(), PPM)
        self.update_state()
        if self.chk_live.isChecked():
            self.snapshot()
        else:
            self.chk_live.setChecked(True)
        return True

    def update_state(self):
        cam_ok = self.src is not None
        cal_ok = self.model is not None
        phone, raw = self.is_phone(), self.is_raw()
        self.chk_live.setEnabled(self.can_show())
        self.btn_shot.setEnabled(self.can_show() and not phone)
        self.btn_cal.setEnabled(cam_ok and self.ctl.connected and self.autocam is None and not phone and not raw)
        self.btn_manual.setEnabled(cam_ok and self.ctl.connected and self.autocam is None and not phone and not raw)
        self.method.setEnabled(not phone)
        self.phone_link.setVisible(phone)
        self.b_again.setVisible(phone and self.src.get() is not None)
        if phone:
            if self.phone_top is not None:
                self.state.setText(tr("Foto dal telefono delle {0}, allineata a mano sui 4 angoli: precisione "
                                      "indicativa.", time.strftime("%H:%M", time.localtime(self.src.time))))
                self.state.setStyleSheet(f"color:{C['success']};")
            elif self.src.get() is not None:
                self.state.setText(tr("Foto arrivata: indica i 4 angoli dell'area di lavoro per metterla sotto il piano."))
                self.state.setStyleSheet(f"color:{C['warn']};")
            else:
                self.state.setText(tr("Nessuna foto ancora. Apri sul telefono la pagina di FreeLaserCut e tocca «Foto "
                                      "del piano di lavoro»: fotografa il piano dall'alto, con tutta l'area dentro."))
                self.state.setStyleSheet(f"color:{C['warn']};")
            return
        if cam_ok and raw:
            self.state.setText(tr("Telecamera mostrata così com'è: NON è allineata al piano. Va bene per guardare, non "
                                  "per posizionare i pezzi: per quello serve la calibrazione."))
            self.state.setStyleSheet(f"color:{C['warn']};")
            return
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
    def _hint(self):
        """0.18.1: spiegazione quando la telecamera non dà un'immagine utile (nera, o la rete non risponde)."""
        src = self.src
        if src is None or self.autocam is not None or self.is_phone():
            return
        if isinstance(src, NetCamera) and src.error and src.get(after=0, timeout=0) is None:
            text = tr("La telecamera di rete non manda la foto: {0}. Durante un lavoro alcuni laser non mandano "
                      "foto; controlla anche che la macchina sia accesa e collegata.", src.error)
        elif getattr(src, "black", False):
            text = tr("L'immagine arriva nera. Se la telecamera è quella del laser: chiudi bene il coperchio (sui "
                      "Creality Falcon A1 la telecamera è nel coperchio), accendi la luce e premi ⟳, così "
                      "FreeLaserCut prova un altro modo di leggerla. Se è ancora nera, manda un rapporto da "
                      "Aiuto → Invia un rapporto all'assistenza.")
        else:
            if getattr(self, "_hinted", False):
                self._hinted = False
                self.update_state()
            return
        self._hinted = True
        if self.state.text() != text:
            self.state.setText(text)
            self.state.setStyleSheet(f"color:{C['warn']};")

    def tick(self):
        if self.src is None or not self.isVisible() and not self.chk_live.isChecked():
            return
        self._hint()
        frame = self.src.get(after=0, timeout=0.05)
        if frame is None:
            return
        if self.is_phone():  # una foto ferma: sotto il piano c'è già, qui serve solo l'anteprima
            if self.isVisible():
                self._show_preview(frame)
            return
        if (self.model is not None and not self.is_raw()
                and tuple(self.model.frame_size) != tuple(self.src.size)):
            self.state.setText(tr("La risoluzione della camera è cambiata: ricalibra"))
        if self.isVisible():
            self._show_preview(frame)
        if self.chk_live.isChecked() and self.can_show():
            self._show_on_bed(frame)

    def _show_preview(self, frame):
        view = frame.copy()
        for u, v in self.detected:
            cv2.circle(view, (int(u), int(v)), 10, (60, 220, 60), 2, cv2.LINE_AA)
        w = max(self.preview.width() - 8, 200)
        h = int(view.shape[0] * w / view.shape[1])
        self.preview.setPixmap(QPixmap.fromImage(to_qimage(cv2.resize(view, (w, h)))))

    def _show_on_bed(self, frame):
        if self.is_phone():
            top = self.phone_top  # raddrizzata sui 4 angoli indicati a mano
        elif self.is_raw():
            top = plate_photo.fit_raw(frame, self.bed_size(), PPM)  # così com'è, intera, non allineata
        else:
            top = self.model.rectify(frame, PPM)
        if top is not None:
            self.win.bed.set_camera_image(to_qimage(top), PPM, self.opacity.value() / 100)

    def snapshot(self):
        if not self.can_show():
            return
        if self.is_phone():
            self._show_on_bed(None)
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
