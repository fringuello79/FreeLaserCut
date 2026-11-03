# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Laser → Guardia fiamme: durante il lavoro controlla la camera e, se vede una fiammata, ferma il lavoro
(laser e aria spenti), suona e mostra un avviso rosso. Spenta di partenza: la persona la attiva qui."""
import os
import time

import cv2
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QMessageBox, QVBoxLayout)

from .. import diag
from .. import fire_guard as fg
from ..camera import SIM_CAMERA
from ..i18n import tr
from ..theme import css

def level_names():
    return {"alta": tr("Alta (piccole fiamme)"), "media": tr("Media (consigliata)"),
            "bassa": tr("Bassa (molta brace o luci forti)")}


class FireGuard(QObject):
    triggered = Signal(str)  # percorso della foto salvata ("" se non salvata)
    state_changed = Signal(str)  # "spenta", "senza-camera", "attiva", "allarme"

    INTERVAL_MS = 300

    def __init__(self, win, qs):
        super().__init__(win)
        self.win = win
        self.qs = qs
        self.ctl = win.ctl
        self.det = fg.FlameDetector(self.sensitivity())
        self.running = False
        self.state = "spenta"
        self.last_t = 0.0
        self.last_info = None
        self.alarm_at = None
        self.ctl.job_progress.connect(self._progress)
        self.timer = QTimer(self)
        self.timer.setInterval(self.INTERVAL_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    # ---------------------------------------------------------------- impostazioni
    def enabled(self):
        v = self.qs.value("fire_guard", False)
        return v in (True, "true", "1", 1)

    def set_enabled(self, on):
        self.qs.setValue("fire_guard", bool(on))
        self.tick()

    def sensitivity(self):
        v = str(self.qs.value("fire_guard_level", "media"))
        return v if v in fg.LEVELS else "media"

    def set_sensitivity(self, level):
        if level in fg.LEVELS:
            self.qs.setValue("fire_guard_level", level)
            self.det.sensitivity = level

    def source(self):
        cam = getattr(self.win, "camera", None)
        src = getattr(cam, "src", None)
        if src is None or getattr(src, "index", None) == SIM_CAMERA and not os.environ.get("FLC_FIRE_SIM"):
            return None
        return src

    def _set_state(self, s):
        if s != self.state:
            self.state = s
            self.state_changed.emit(s)

    # ---------------------------------------------------------------- controllo
    def _progress(self, done, total):
        if done == 0:  # nuovo lavoro: l'allarme del lavoro precedente non conta più
            self.alarm_at = None
            self.running = False
            if self.state == "allarme":
                self._set_state("attiva" if self.enabled() else "spenta")

    def tick(self):
        active = bool(self.ctl.job_active)
        if self.alarm_at is not None:
            return  # già scattata per questo lavoro: resta in allarme finché non parte un altro lavoro
        if not self.enabled() or not active:
            if self.running:
                self.running = False
            self._set_state("spenta" if not self.enabled() else "attiva")
            return
        src = self.source()
        if src is None:
            if self.state != "senza-camera":
                self.win.statusBar().showMessage(tr("Guardia fiamme: nessuna camera scelta nel pannello Camera, "
                                                    "il lavoro non è sorvegliato."), 15000)
            self._set_state("senza-camera")
            return
        if not self.running:
            self.running = True
            self.det = fg.FlameDetector(self.sensitivity())
            self.last_t = 0.0
        self._set_state("attiva")
        frame = src.get(after=self.last_t, timeout=0.0)
        if frame is None:
            return
        self.last_t = getattr(src, "_t", time.time())
        self.feed(frame)

    def feed(self, frame):
        info = self.det.update(frame)
        self.last_info = info
        if info["alarm"] and self.alarm_at is None:
            self.alarm_at = time.time()
            self._fire(frame, info)
        return info

    def _fire(self, frame, info):
        try:
            self.ctl.stop_job()
        except Exception:  # noqa: BLE001
            pass
        self.running = False
        self._set_state("allarme")
        path = ""
        try:
            path = os.path.join(diag.diag_dir(), time.strftime("fiamma-%Y%m%d-%H%M%S.jpg"))
            if not cv2.imwrite(path, frame):
                path = ""
        except Exception:  # noqa: BLE001
            path = ""
        log = getattr(self.win, "comm_log", None)
        if log is not None:
            log.add("!", f"guardia fiamme: lavoro fermato (zona calda {info['fraction'] * 100:.2f}% "
                         f"soglia {info['threshold'] * 100:.2f}%)" + (f" foto {os.path.basename(path)}" if path else ""))
            try:
                log.save("fiamma")
            except Exception:  # noqa: BLE001
                pass
        self.triggered.emit(path)
        self._alarm_ui(path)

    def _alarm_ui(self, path):
        beeps = {"n": 0}
        t = QTimer(self)

        def beep():
            QApplication.beep()
            beeps["n"] += 1
            if beeps["n"] >= 8:
                t.stop()
                t.deleteLater()
        t.timeout.connect(beep)
        t.start(400)
        beep()
        if os.environ.get("FLC_NO_DIALOGS"):
            return
        box = QMessageBox(QMessageBox.Critical, tr("Guardia fiamme: lavoro fermato"),
                          tr("La camera ha visto una fiamma: il lavoro è stato fermato e il laser spento.\n\n"
                             "Controlla subito la macchina. Se c'è fuoco, coprilo o spegnilo; non lasciare la "
                             "macchina da sola.") + (("\n\n" + tr("Foto salvata: {0}", path)) if path else ""),
                          QMessageBox.Ok, self.win)
        box.setStyleSheet(css("QMessageBox { background:#3A1418; } QLabel { color:#FFD7DA; font-size:14px; }"))
        box.setModal(False)
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.show()
        self.win.statusBar().showMessage(tr("Guardia fiamme: lavoro fermato"), 30000)


class FireGuardDialog(QDialog):
    def __init__(self, guard, parent=None):
        super().__init__(parent)
        self.guard = guard
        self.setWindowTitle(tr("Guardia fiamme"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        intro = QLabel(tr(
            "Durante il lavoro FreeLaserCut guarda la camera del pannello Camera. Se vede una fiamma (una zona "
            "arancione e luminosa più grande del puntino del laser) per circa un secondo, ferma il lavoro, spegne "
            "il laser, suona e salva una foto nella cartella della diagnostica."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        warn = QLabel(tr(
            "È un aiuto in più, non una protezione certificata: non lasciare mai la macchina accesa da sola. "
            "Serve una camera che inquadri il piano (scelta nel pannello Camera) e una stanza illuminata in modo "
            "normale. Non funziona con il simulatore."))
        warn.setWordWrap(True)
        warn.setStyleSheet(css("color:#FFB4A8;"))
        lay.addWidget(warn)
        form = QFormLayout()
        self.chk = QCheckBox(tr("Attiva la guardia fiamme durante i lavori"))
        self.chk.setChecked(guard.enabled())
        self.chk.toggled.connect(guard.set_enabled)
        form.addRow(self.chk)
        self.level = QComboBox()
        for k, name in level_names().items():
            self.level.addItem(name, k)
        self.level.setCurrentIndex(self.level.findData(guard.sensitivity()))
        self.level.currentIndexChanged.connect(lambda *_: guard.set_sensitivity(self.level.currentData()))
        form.addRow(tr("Sensibilità"), self.level)
        lay.addLayout(form)
        self.view = QLabel()
        self.view.setMinimumSize(320, 200)
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setStyleSheet(css("background:#0B0F17; border:1px solid #2A3550;"))
        lay.addWidget(self.view)
        self.reading = QLabel()
        self.reading.setWordWrap(True)
        lay.addWidget(self.reading)
        tip = QLabel(tr("Prova: accendi un accendino o una candela davanti alla camera. Le zone che verrebbero "
                        "prese per fiamma si colorano di rosso. Se si colora qualcosa che non è una fiamma (una "
                        "lampada, un riflesso), scegli una sensibilità più bassa."))
        tip.setWordWrap(True)
        lay.addWidget(tip)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        src = self.guard.source()
        if src is None:
            self.view.setText(tr("Nessuna camera: sceglila nel pannello Camera."))
            self.reading.setText("")
            return
        frame = src.get(after=0, timeout=0.0)
        if frame is None:
            return
        frame = cv2.resize(frame, (fg.WIDTH, max(1, int(round(frame.shape[0] * fg.WIDTH / frame.shape[1])))))
        m = fg.hot_mask(frame)
        show = frame.copy()
        show[m > 0] = (40, 40, 255)
        frac = float((m > 0).mean())
        thr = fg.LEVELS[self.guard.sensitivity()]
        rgb = cv2.cvtColor(show, cv2.COLOR_BGR2RGB)
        img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888).copy()
        self.view.setPixmap(QPixmap.fromImage(img))
        self.reading.setText(tr("Zona che sembra fiamma: {0} % dell'immagine (con questa sensibilità scatta sopra "
                                "{1} %, se resta per circa un secondo).", f"{frac * 100:.2f}", f"{thr * 100:.2f}"))
