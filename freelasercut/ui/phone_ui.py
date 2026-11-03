# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Laser → Controllo dal telefono: accende la pagina per il telefono, mostra il codice QR e la mini guida."""
import io
import time

import cv2
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout)

from .. import phone
from ..camera import SIM_CAMERA
from ..i18n import tr
from ..theme import css


class PhoneControl(QObject):
    """Ponte fra il server (thread suo) e l'interfaccia: i comandi arrivano come segnali nel thread principale."""
    pause_requested = Signal()
    stop_requested = Signal()
    photo_received = Signal(bytes)
    changed = Signal()

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.ctl = win.ctl
        self.server = None
        self.snapshot = {"title": tr("Avvio…")}
        self.job_t0 = None
        self.ctl.job_progress.connect(self._progress)
        self.pause_requested.connect(self._do_pause)
        self.stop_requested.connect(self._do_stop)
        self.photo_received.connect(self._do_photo)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)

    # ---------------------------------------------------------------- acceso / spento
    @property
    def running(self):
        return self.server is not None and self.server.running

    def start(self):
        if self.running:
            return True
        self.server = phone.PhoneServer(lambda: self.snapshot, self._frame, self._pause, self._stop, self._photo,
                                        token=self.server.token if self.server else None)
        self.server.start()
        self.refresh()
        self.timer.start()
        self.changed.emit()
        return True

    def stop(self):
        if self.server is not None:
            self.server.close()
        self.timer.stop()
        self.changed.emit()

    def new_code(self):
        if self.server is not None:
            self.server.new_token()
        self.changed.emit()

    def urls(self):
        return self.server.urls() if self.running else []

    # ---------------------------------------------------------------- stato (thread principale)
    def _progress(self, done, total):
        if done == 0 or self.job_t0 is None:
            self.job_t0 = time.time()

    def paused(self):
        lp = getattr(self.win, "laser", None)
        b = getattr(lp, "b_pause", None)
        return bool(b is not None and b.isChecked()) or str(self.ctl.last_status.get("state", "")).startswith("Hold")

    def refresh(self):
        ctl = self.ctl
        st = str(ctl.last_status.get("state", "") or "")
        active = bool(ctl.job_active)
        done, total = int(getattr(ctl, "_job_done", 0)), int(getattr(ctl, "_job_total", 0))
        fire = getattr(getattr(self.win, "fire", None), "state", "")
        paused = active and self.paused()
        alarm = fire == "allarme" or st.startswith("Alarm")
        if fire == "allarme":
            title = tr("Guardia fiamme: lavoro fermato")
        elif not ctl.connected:
            title = tr("Macchina non connessa")
        elif active:
            title = tr("In pausa") if paused else tr("Lavoro in corso")
        elif st.startswith("Alarm"):
            title = tr("Allarme della macchina")
        else:
            title = tr("Pronta")
        src = getattr(getattr(self.win, "camera", None), "src", None)
        cam = src is not None and getattr(src, "index", None) != SIM_CAMERA
        elapsed = time.time() - self.job_t0 if active and self.job_t0 else 0.0
        left = elapsed * (total - done) / done if active and done > 20 and total else None
        detail = tr("Stato della scheda: {0}", st) if ctl.connected and st else ""
        if active and fire == "attiva":
            detail += ("  ·  " if detail else "") + tr("guardia fiamme attiva")
        self.snapshot = {"title": title, "detail": detail, "state": st, "connected": bool(ctl.connected),
                         "job_active": active, "paused": paused, "done": done if active else 0,
                         "total": total if active else 0, "elapsed": elapsed, "left": left, "alarm": alarm,
                         "camera": bool(cam), "fire": fire or ""}

    # ---------------------------------------------------------------- chiamate dal thread del server
    def _frame(self):
        src = getattr(getattr(self.win, "camera", None), "src", None)
        if src is None or getattr(src, "index", None) == SIM_CAMERA:
            return None
        f = src.get(after=0, timeout=0.5)
        if f is None:
            return None
        h, w = f.shape[:2]
        if w > 800:
            f = cv2.resize(f, (800, int(h * 800 / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else None

    def _pause(self):
        s = self.snapshot
        if not s.get("job_active"):
            return False, tr("Nessun lavoro in corso.")
        if s.get("paused"):
            return True, tr("Il lavoro è già in pausa. Per riprendere usa il PC.")
        self.pause_requested.emit()
        return True, tr("Pausa richiesta.")

    def _stop(self):
        if not self.snapshot.get("job_active"):
            return False, tr("Nessun lavoro in corso.")
        self.stop_requested.emit()
        return True, tr("Lavoro fermato, laser spento.")

    def _photo(self, data):
        self.photo_received.emit(bytes(data))
        return tr("Foto arrivata sul PC: il risultato è nel Test materiale.")

    # ---------------------------------------------------------------- esecuzione (thread principale)
    def _do_pause(self):
        if self.ctl.job_active and not self.paused():
            b = getattr(getattr(self.win, "laser", None), "b_pause", None)
            if b is not None:
                b.setChecked(True)
            else:
                self.ctl.feed_hold()
            self._log("pausa dal telefono")

    def _do_stop(self):
        if self.ctl.job_active:
            self.ctl.stop_job()
            self._log("stop dal telefono")
            self.win.statusBar().showMessage(tr("Lavoro fermato dal telefono"), 15000)

    def _do_photo(self, data):
        self._log(f"foto del test dal telefono ({len(data) // 1024} kB)")
        self.win.photo_from_phone(data)

    def _log(self, text):
        log = getattr(self.win, "comm_log", None)
        if log is not None:
            log.add("#", text)


def qr_pixmap(text, scale=6):
    import segno

    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=3, dark="#000000", light="#FFFFFF")
    pm = QPixmap()
    pm.loadFromData(buf.getvalue(), "PNG")
    return pm


def guide_html():
    return tr(
        "<b>Come si usa</b><ol>"
        "<li>Il telefono deve essere collegato allo <b>stesso Wi-Fi</b> del PC (non con i dati mobili).</li>"
        "<li>Spunta <i>Attiva il controllo dal telefono</i>. La prima volta Windows può chiedere se consentire "
        "l'accesso alla rete a FreeLaserCut (Python): scegli <b>Reti private</b> e premi Consenti.</li>"
        "<li>Inquadra il codice QR con la fotocamera del telefono e apri il link. Puoi aggiungere la pagina alla "
        "schermata Home per ritrovarla.</li>"
        "<li>Dal telefono vedi l'avanzamento e la camera, puoi mettere in <b>pausa</b> o <b>fermare</b> il lavoro "
        "e inviare la <b>foto del test materiale</b>. Avviare o riprendere si fa solo dal PC, davanti alla macchina.</li>"
        "</ol>"
        "<p>Il collegamento resta dentro la rete di casa e si spegne quando chiudi FreeLaserCut. Il codice "
        "nell'indirizzo è casuale: se l'hai dato a qualcuno, premi <i>Cambia codice</i> e il vecchio link smette di "
        "funzionare. Se il telefono non apre la pagina: controlla il Wi-Fi, che la rete sia impostata come "
        "<i>privata</i> in Windows e che il firewall non blocchi FreeLaserCut.</p>")


class PhoneDialog(QDialog):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle(tr("Controllo dal telefono"))
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        self.chk = QCheckBox(tr("Attiva il controllo dal telefono (fino alla chiusura di FreeLaserCut)"))
        self.chk.setChecked(ctrl.running)
        self.chk.toggled.connect(self._toggle)
        v.addWidget(self.chk)
        h = QHBoxLayout()
        self.qr = QLabel()
        self.qr.setFixedSize(230, 230)
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setStyleSheet(css("background:#0B0F17; border:1px solid #2A3550; border-radius:8px;"))
        h.addWidget(self.qr)
        right = QVBoxLayout()
        self.url = QLabel()
        self.url.setWordWrap(True)
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.addWidget(self.url)
        self.b_copy = QPushButton(tr("Copia l'indirizzo"))
        self.b_copy.clicked.connect(self._copy)
        self.b_code = QPushButton(tr("Cambia codice"))
        self.b_code.setToolTip(tr("Il vecchio indirizzo smette di funzionare"))
        self.b_code.clicked.connect(self._new_code)
        right.addWidget(self.b_copy)
        right.addWidget(self.b_code)
        self.seen = QLabel()
        self.seen.setWordWrap(True)
        right.addWidget(self.seen)
        right.addStretch(1)
        h.addLayout(right, 1)
        v.addLayout(h)
        g = QLabel(guide_html())
        g.setWordWrap(True)
        g.setTextFormat(Qt.RichText)
        v.addWidget(g)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        ctrl.changed.connect(self.update_view)
        self.t = QTimer(self)
        self.t.timeout.connect(self._seen)
        self.t.start(1000)
        self.update_view()

    def _toggle(self, on):
        if on:
            try:
                self.ctrl.start()
            except OSError as ex:
                self.chk.blockSignals(True)
                self.chk.setChecked(False)
                self.chk.blockSignals(False)
                QMessageBox.warning(self, tr("Controllo dal telefono"), tr("Non riesco ad aprire la pagina: {0}", ex))
        else:
            self.ctrl.stop()
        self.update_view()

    def _copy(self):
        u = self.ctrl.urls()
        if u:
            QGuiApplication.clipboard().setText(u[0])

    def _new_code(self):
        self.ctrl.new_code()

    def update_view(self):
        urls = self.ctrl.urls()
        on = bool(urls)
        self.b_copy.setEnabled(on)
        self.b_code.setEnabled(on)
        if on:
            self.qr.setPixmap(qr_pixmap(urls[0]).scaled(220, 220, Qt.KeepAspectRatio, Qt.FastTransformation))
            txt = tr("Indirizzo per il telefono:") + f"<br><b>{urls[0]}</b>"
            if len(urls) > 1:
                txt += "<br><small>" + tr("Altri indirizzi di questo PC:") + "<br>" + "<br>".join(urls[1:]) + "</small>"
            self.url.setText(txt)
        else:
            self.qr.clear()
            self.qr.setText(tr("Spento"))
            self.url.setText(tr("Spunta la casella qui sopra per accendere la pagina per il telefono."))
        self._seen()

    def _seen(self):
        srv = self.ctrl.server
        if not self.ctrl.running or srv is None or not srv.last_seen:
            self.seen.setText("")
            return
        t = max(srv.last_seen.values())
        self.seen.setText(tr("Telefoni collegati: {0} · ultimo contatto {1}", len(srv.last_seen),
                             time.strftime("%H:%M:%S", time.localtime(t))))
