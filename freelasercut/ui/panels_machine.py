# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Pannelli macchina: Laser (lavoro, verifica, contorno, override, fire, aria) e Movimento (jog, origini, posizioni)."""
import json
import os
import time

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QProgressBar, QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget,
)

from ..grbl import POINTER_MAX, POINTER_WARN
from ..theme import C, css
from . import style
from .widgets import AnchorPicker, NumField, row, section
from freelasercut.i18n import tr  # noqa: E402
from .. import units

START_MODES = [("absolute", tr("Coordinate assolute")), ("current", tr("Posizione attuale della testa")),
               ("origin", tr("Origine utente"))]


def _btn(text, icon=None, obj=None, tip=None, checkable=False):
    b = QPushButton(text)
    if icon:
        b.setIcon(style.icon(icon, "#FFFFFF" if obj in ("primary", "danger") else None))
    if obj:
        b.setObjectName(obj)
    if tip:
        b.setToolTip(tip)
    b.setCheckable(checkable)
    return b


class LaserPanel(QWidget):
    """Tutto ciò che serve per lanciare un lavoro in sicurezza."""

    start_requested = Signal()
    verify_requested = Signal()
    frame_requested = Signal(str)  # box | hull | box_laser | hull_laser
    preview_requested = Signal()
    save_requested = Signal()
    run_file_requested = Signal()

    def __init__(self, ctl, settings: QSettings):
        super().__init__()
        self.ctl = ctl
        self.qs = settings
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 6)
        v.setSpacing(5)
        self.state = QLabel(tr("Macchina non connessa"))
        self.state.setWordWrap(True)
        self.state.setStyleSheet(f"color:{C['muted']}; font-weight:600;")
        v.addWidget(self.state)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.hide()
        v.addWidget(self.progress)
        self.eta = QLabel("")
        self.eta.setObjectName("muted")
        self.eta.hide()
        v.addWidget(self.eta)
        g = QGridLayout()
        g.setSpacing(6)
        self.b_start = _btn(tr("Avvia"), "play", "primary", tr("Prepara, verifica e avvia il lavoro (F5)"))
        self.b_pause = _btn(tr("Pausa"), "pause", tip=tr("Pausa / riprendi (la testa si ferma subito)"), checkable=True)
        self.b_stop = _btn(tr("Stop"), "stop", "danger", "Arresto: laser spento, buffer svuotato")
        self.b_frame = _btn(tr("Contorno"), "frame")
        fm = QMenu(self.b_frame)
        fm.addAction(tr("Rettangolo di ingombro, laser spento")).triggered.connect(lambda: self.frame_requested.emit("box"))
        fm.addAction(tr("Contorno stretto, laser spento")).triggered.connect(lambda: self.frame_requested.emit("hull"))
        fm.addSeparator()
        fm.addAction(style.icon("fire"), tr("Rettangolo con il puntino")).triggered.connect(lambda: self.frame_requested.emit("box_laser"))
        fm.addAction(style.icon("fire"), tr("Contorno stretto con il puntino")).triggered.connect(
            lambda: self.frame_requested.emit("hull_laser"))
        fm.addSeparator()
        self.a_frame_laser = fm.addAction(tr("Il pulsante Contorno usa sempre il puntino"))
        self.a_frame_laser.setCheckable(True)
        self.a_frame_laser.setChecked(self.qs.value("frame_laser", "true") in (True, "true"))
        self.a_frame_laser.toggled.connect(lambda x: (self.qs.setValue("frame_laser", x), self._frame_tip()))
        self.a_frame_repeat = fm.addAction(tr("Ripeti il giro 3 volte (Stop per interrompere)"))
        self.a_frame_repeat.setCheckable(True)
        self.a_frame_repeat.setChecked(self.qs.value("frame_repeat", "false") in (True, "true"))
        self.a_frame_repeat.toggled.connect(lambda x: self.qs.setValue("frame_repeat", x))
        fm.addSeparator()
        fm.addAction(style.icon("settings"), tr("Regola il puntino…")).triggered.connect(self.pointer_setup)
        self.b_frame.clicked.connect(lambda: self.frame_requested.emit("box_laser" if self.a_frame_laser.isChecked() else "box"))
        self.b_frame_more = QToolButton()
        self.b_frame_more.setIcon(style.icon("chevron_down", size=14))
        self.b_frame_more.setMenu(fm)
        self.b_frame_more.setPopupMode(QToolButton.InstantPopup)
        self.b_verify = _btn(tr("Verifica"), "verify", tip=tr("La scheda controlla tutto il G-code senza muoversi né accendere il laser"))
        self.b_preview = _btn(tr("Anteprima"), "preview", tip=tr("Simulazione del lavoro e resa realistica sul legno"))
        self.b_save = _btn(tr("Salva G-code"), "gcode")
        self.b_run = _btn(tr("Esegui file…"), "open", tip=tr("Invia un file G-code già pronto"))
        self.b_save.hide()
        self.b_run.hide()
        self.b_more = QToolButton()
        self.b_more.setText(tr("Altro"))
        self.b_more.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.b_more.setPopupMode(QToolButton.InstantPopup)
        mm = QMenu(self.b_more)
        mm.addAction(style.icon("gcode"), tr("Salva il G-code…"), self.b_save.click)
        mm.addAction(style.icon("open"), tr("Esegui un file G-code…"), self.b_run.click)
        self.b_more.setMenu(mm)
        self.b_start.setMinimumHeight(30)
        g.addWidget(self.b_start, 0, 0, 1, 2)
        g.addWidget(self.b_pause, 0, 2)
        g.addWidget(self.b_stop, 0, 3)
        fr = QHBoxLayout()
        fr.setSpacing(0)
        fr.addWidget(self.b_frame, 1)
        fr.addWidget(self.b_frame_more)
        g.addLayout(fr, 1, 0, 1, 2)
        g.addWidget(self.b_preview, 1, 2)
        g.addWidget(self.b_verify, 1, 3)
        self.b_more.setToolTip(tr("Salva il G-code, esegui un file G-code"))
        g.addWidget(self.b_more, 1, 4)
        g.addWidget(QWidget(), 0, 4)
        v.addLayout(g)
        self.b_start.clicked.connect(self.start_requested)
        self.b_verify.clicked.connect(self.verify_requested)
        self.b_preview.clicked.connect(self.preview_requested)
        self.b_save.clicked.connect(self.save_requested)
        self.b_run.clicked.connect(self.run_file_requested)
        self.b_pause.toggled.connect(self._pause)
        self.b_stop.clicked.connect(self.ctl.stop_job)

        v.addWidget(section(tr("Posizionamento")))
        self.start_from = QComboBox()
        for k, lab in START_MODES:
            self.start_from.addItem(lab, k)
        self.start_from.setCurrentIndex(max(0, self.start_from.findData(self.qs.value("start_from", "absolute"))))
        self.anchor = AnchorPicker(int(self.qs.value("job_anchor", 0)))
        self.anchor.changed.connect(lambda a: self.qs.setValue("job_anchor", a))
        self.start_from.currentIndexChanged.connect(self._start_changed)
        self.b_goto_anchor = _btn(tr("Porta la testa qui"), "position",
                                  tip=tr("La testa va (a laser spento) sul punto del disegno indicato dai 9 pallini: "
                                         "un angolo, il centro di un lato o il centro. Utile per vedere sul materiale "
                                         "dove cadrà quel punto del lavoro."))
        v.addWidget(row(QLabel(tr("Partenza")), self.start_from, self.anchor))
        v.addWidget(row(self.b_goto_anchor))
        self.only_sel = QCheckBox(tr("Solo gli oggetti selezionati"))
        self.finish_origin = QCheckBox(tr("A fine lavoro torna al punto di partenza"))
        self.finish_origin.setChecked(self.qs.value("finish_origin", "true") == "true")
        self.finish_origin.toggled.connect(lambda x: self.qs.setValue("finish_origin", "true" if x else "false"))
        self.optimize = QCheckBox(tr("Ottimizza i percorsi (fori prima, meno trasferimenti)"))
        self.optimize.setChecked(self.qs.value("optimize", "true") == "true")
        self.optimize.toggled.connect(lambda x: self.qs.setValue("optimize", "true" if x else "false"))
        self.verify_first = QCheckBox(tr("Verifica il G-code con la scheda prima di partire"))
        self.verify_first.setChecked(self.qs.value("verify_first", "true") == "true")
        self.verify_first.toggled.connect(lambda x: self.qs.setValue("verify_first", "true" if x else "false"))
        for w in (self.only_sel, self.finish_origin, self.optimize, self.verify_first):
            v.addWidget(w)
        # assi invertiti: valgono per la macchina (si salvano nel suo profilo), la finestra principale li collega
        self.inv_x = QCheckBox(tr("Inverti l'asse X (destra ↔ sinistra)"))
        self.inv_y = QCheckBox(tr("Inverti l'asse Y (avanti ↔ indietro)"))
        for w, ax in ((self.inv_x, "X"), (self.inv_y, "Y")):
            w.setToolTip(tr("Spunta se, premendo le frecce di movimento, la testa va dalla parte opposta sull'asse {0} "
                            "(origine della macchina dall'altra parte o motore montato al contrario). Cambiano jog, "
                            "posizione della testa e coordinate del lavoro; il disegno resta come lo vedi.", ax))
            v.addWidget(w)
        self._start_changed()

        v.addWidget(section(tr("Durante il lavoro")))
        self.ov_speed, self.ov_speed_l = self._ov_slider(tr("Velocità"), "feed")
        self.ov_power, self.ov_power_l = self._ov_slider(tr("Potenza"), "power")
        v.addWidget(row(QLabel(tr("Velocità")), self.ov_speed, self.ov_speed_l, stretch=False))
        v.addWidget(row(QLabel(tr("Potenza ")), self.ov_power, self.ov_power_l, stretch=False))
        b_reset = _btn(tr("Ripristina 100%"))
        b_reset.clicked.connect(self._reset_ov)
        v.addWidget(row(b_reset))

        v.addWidget(section(tr("Puntino e aria")))
        self.b_fire = _btn(tr("Puntino (tieni premuto)"), "fire", tip=tr("Accende il laser alla potenza del puntino finché tieni "
                           "premuto (si spegne da solo dopo 20 s). Usalo per centrare il pezzo."))
        self.fire_pct = QDoubleSpinBox()
        self.fire_pct.setRange(0.1, POINTER_MAX)
        self.fire_pct.setSingleStep(0.1)
        self.fire_pct.setDecimals(1)
        self.fire_pct.setSuffix(" %")
        try:
            saved = float(self.qs.value("fire_pct", 1.0))
        except (TypeError, ValueError):
            saved = 1.0
        # oltre il 5% serve una conferma: alla riapertura del programma si riparte al massimo dal 5%
        self.fire_pct.setValue(min(saved, POINTER_WARN))
        self.fire_pct.setToolTip(tr("Potenza del puntino: la stessa per il pulsante Puntino e per il contorno con il puntino.\n"
                                 "Contorno → Regola il puntino… ti aiuta a trovarla."))
        self._fire_ok = self.fire_pct.value()  # ultimo valore accettato (per l'avviso oltre il 5%)
        self.fire_pct.valueChanged.connect(self._fire_pct_changed)
        self._fire_style()
        self.b_fire.pressed.connect(lambda: self.fire_changed(True))
        self.b_fire.released.connect(lambda: self.fire_changed(False))
        self.b_air = _btn(tr("Aria"), "air", tip=tr("Air assist acceso/spento"), checkable=True)
        self.b_air.toggled.connect(self.ctl.air)
        v.addWidget(row(self.b_fire, self.fire_pct, self.b_air))
        warn = QLabel(tr("Laser di classe 4: occhiali protettivi per 450 nm anche per il puntatore."))
        warn.setWordWrap(True)
        warn.setObjectName("muted")
        v.addWidget(warn)
        v.addWidget(section(tr("Stima del lavoro")))
        self.summary = QLabel("—")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        v.addWidget(self.summary)
        v.addStretch(1)
        self.s_max = 1000.0
        self._t0 = 0.0
        self._frame_tip()
        ctl.job_progress.connect(self._progress)
        ctl.job_finished.connect(self._finished)
        ctl.check_progress.connect(self._check_progress)
        ctl.status_changed.connect(self._status)
        self.set_connected(False)

    def _ov_slider(self, label, kind):
        sl = QSlider(Qt.Horizontal)
        sl.setRange(10, 200)
        sl.setValue(100)
        sl.setFixedWidth(170)
        lab = QLabel("100%")
        lab.setFont(style.mono_font(9))
        lab.setFixedWidth(42)
        sl.valueChanged.connect(lambda x: lab.setText(f"{x}%"))
        sl.sliderReleased.connect(lambda: self._override(kind, sl.value()))
        sl.setToolTip(OVERRIDE_TIP[kind]())
        return sl, lab

    def _override(self, kind, pct):
        """Manda l'override alla scheda e, sopra il 100%, dice se la scheda può davvero salire (0.17.2)."""
        self.ctl.set_override(kind, pct)
        w = self.window()
        note = override_note(kind, pct, getattr(getattr(w, "job", None), "layers", ()), getattr(w, "profile", None))
        if note and hasattr(w, "statusBar"):
            w.statusBar().showMessage(note, 12000)

    def _reset_ov(self):
        for sl, kind in ((self.ov_speed, "feed"), (self.ov_power, "power")):
            sl.setValue(100)
            self.ctl.set_override(kind, 100)

    def _start_changed(self):
        k = self.start_from.currentData()
        self.qs.setValue("start_from", k)
        self.anchor.setEnabled(True)  # in coordinate assolute serve solo a «Porta la testa qui»
        self.anchor.setToolTip(tr("Punto del lavoro che va sulla testa / sull'origine") if k != "absolute"
                               else tr("In coordinate assolute il lavoro sta dove lo vedi sul piano: il pallino "
                                       "indica solo il punto per «Porta la testa qui»"))

    def _frame_tip(self):
        if self.a_frame_laser.isChecked():
            self.b_frame.setToolTip(tr("La testa percorre il rettangolo del lavoro con il puntino acceso ({0:g}%): vedi sul materiale dove passerà il laser", self.fire_pct.value()))
        else:
            self.b_frame.setToolTip(tr("La testa percorre il rettangolo del lavoro a laser spento"))

    def frame_repeats(self):
        return 3 if self.a_frame_repeat.isChecked() else 1

    def _fire_pct_changed(self, x):
        if x > POINTER_WARN >= self._fire_ok and not confirm_high_pointer(self, x):
            self.fire_pct.blockSignals(True)
            self.fire_pct.setValue(POINTER_WARN)
            self.fire_pct.blockSignals(False)
            x = POINTER_WARN
        self._fire_ok = x
        self.qs.setValue("fire_pct", x)
        self._fire_style()
        self._frame_tip()

    def _fire_style(self):
        high = self.fire_pct.value() > POINTER_WARN
        self.fire_pct.setStyleSheet(css("QDoubleSpinBox { color: #FFB020; font-weight: 700; }") if high else "")
        self.fire_pct.setToolTip(
            (tr("Attenzione: sopra il 5% il puntino può segnare o bruciare il materiale.") + "\n" if high else "")
            + tr("Potenza del puntino: la stessa per il pulsante Puntino e per il contorno con il puntino.\n"
                 "Contorno → Regola il puntino… ti aiuta a trovarla."))

    def pointer_setup(self):
        if not self.ctl.connected:
            QMessageBox.information(self, tr("Puntino"), tr("Connetti la macchina per regolare il puntino."))
            return
        dlg = PointerDialog(self.ctl, self.fire_pct.value(), self.s_max, self)
        if dlg.exec() == QDialog.Accepted:
            self.fire_pct.setValue(dlg.pct)

    def fire_changed(self, on):
        if on and not self.ctl.connected:
            return
        self.ctl.fire(on, self.fire_pct.value(), s_max=self.s_max)

    def _pause(self, paused):
        if paused:
            self.ctl.feed_hold()
            self.b_pause.setText(tr("Riprendi"))
            self.b_pause.setIcon(style.icon("play"))
        else:
            self.ctl.resume()
            self.b_pause.setText(tr("Pausa"))
            self.b_pause.setIcon(style.icon("pause"))

    def set_connected(self, ok):
        for b in (self.b_start, self.b_frame, self.b_frame_more, self.b_verify, self.b_fire, self.b_air, self.b_run,
                  self.b_goto_anchor):
            b.setEnabled(ok)
        self.update_running()
        if not ok:
            self.state.setText(tr("Laser non connesso: scegli la porta qui sopra e premi Connetti (Ctrl+K). "
                               "Intanto puoi disegnare, vedere l'anteprima e salvare il G-code."))
            self.state.setStyleSheet(f"color:{C['muted']}; font-weight:600;")

    def update_running(self):
        busy = self.ctl.job_active or self.ctl.checking
        ok = self.ctl.connected
        self.b_pause.setEnabled(ok and self.ctl.job_active)
        self.b_stop.setEnabled(ok and busy)
        for b in (self.b_start, self.b_frame, self.b_frame_more, self.b_verify, self.b_run, self.b_fire):
            b.setEnabled(ok and not busy)
        for w in (self.ov_speed, self.ov_power):
            w.setEnabled(ok)

    def _status(self, st):
        s = st.get("state", "")
        ov = st.get("ov")
        if ov and not self.ov_speed.isSliderDown():
            self.ov_speed.blockSignals(True)
            self.ov_speed.setValue(ov[0])
            self.ov_speed_l.setText(f"{ov[0]}%")
            self.ov_speed.blockSignals(False)
            self.ov_power.blockSignals(True)
            self.ov_power.setValue(ov[2])
            self.ov_power_l.setText(f"{ov[2]}%")
            self.ov_power.blockSignals(False)
        names = {"Idle": (tr("Pronta"), C["success"]), "Run": (tr("In lavoro"), C["accent_hi"]), "Hold": (tr("In pausa"), C["warn"]),
                 "Jog": (tr("In movimento"), C["accent_hi"]), "Alarm": (tr("In allarme: sblocca o fai l'homing"), C["danger"]),
                 "Home": (tr("Homing in corso"), C["accent_hi"]), "Check": (tr("Verifica in corso"), C["warn"]),
                 "Door": (tr("Porta aperta"), C["warn"])}
        txt, col = names.get(s, (s, C["muted"]))
        self.state.setText(f"● {txt}")
        self.state.setStyleSheet(f"color:{col}; font-weight:600;")

    def start_progress(self, kind):
        self._t0 = time.time()
        self.progress.setValue(0)
        self.progress.show()
        self.eta.show()
        self.eta.setText(tr("Verifica del G-code nella scheda…") if kind == "check" else tr("Avvio…"))
        self.update_running()

    def _check_progress(self, done, total):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self.eta.setText(tr("Verifica: {0}/{1} righe controllate", done, total))

    def _progress(self, done, total):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        if done:
            el = time.time() - self._t0
            rest = el / done * (total - done)
            self.eta.setText(tr("{0}/{1} righe · trascorso {2} · restante ~{3}", done, total, _hms(el), _hms(rest)))
        self.update_running()

    def _finished(self, ok, msg):
        self.eta.setText(msg)
        self.b_pause.blockSignals(True)
        self.b_pause.setChecked(False)
        self.b_pause.setText(tr("Pausa"))
        self.b_pause.setIcon(style.icon("pause"))
        self.b_pause.blockSignals(False)
        self.update_running()

    def show_job(self, job, profile):
        if job is None:
            self.summary.setText("—")
            return
        if job.bounds is None:
            self.summary.setText(tr("Niente da incidere"))
            return
        b = job.bounds
        notes = list(job.warnings) + [choppy_text(c) for c in job.choppy(self.ctl.stream_baud(profile.baud))]
        w = "".join(f"<br><span style='color:{C['danger'] if 'esce' in x else C['warn']}'>⚠ {x}</span>" for x in notes)
        layers = " · ".join(f"{s.name}: {s.cut_mm / 1000:.2f} m" for s in job.layers)
        self.summary.setText(tr("Tempo stimato <b>{0}</b> · {1} righe G-code<br>Ingombro {2:.1f} × {3:.1f} mm, da X{4:.1f} Y{5:.1f}<br><span style='color:{6}'>{7}</span>{8}", _hms(job.seconds), len(job.lines), b.width(), b.height(), b.left(), b.top(), C['muted'], layers, w))


OVERRIDE_TIP = {
    "feed": lambda: tr("Cambia la velocità del lavoro in corso, dal 10% al 200%. Sotto il 100% funziona sempre; sopra, "
                       "la scheda non supera la velocità massima degli assi ($110/$111) e sui tratti corti (foto, testi "
                       "piccoli) le accelerazioni ($120/$121) la tengono comunque più bassa."),
    "power": lambda: tr("Cambia la potenza del lavoro in corso, dal 10% al 200%. Sotto il 100% funziona sempre; sopra, "
                        "la scheda non supera la sua potenza massima ($30): un livello già al 100% non può salire."),
}


def override_note(kind, pct, layers, profile):
    """Sopra il 100%: spiega perché la scheda non può salire tanto quanto chiesto (GRBL limita gli override a
    $110/$111 per la velocità e a $30 per la potenza). '' se non c'è niente da dire."""
    if pct <= 100 or profile is None:
        return ""
    layers = [l for l in layers or () if getattr(l, "speed", 0) > 0]
    if not layers:
        return ""
    if kind == "power":
        top = max(l.power for l in layers)
        if top <= 0 or top * pct / 100.0 <= 100.0:
            return ""
        if top >= 100:
            return tr("Potenza: il lavoro è già al 100%, il massimo della scheda ($30 = {0:g}): sopra il 100% non può "
                      "salire.", profile.s_max)
        return tr("Potenza: il livello più forte è al {0:g}%, quindi la scheda sale al massimo del {1:.0f}% ($30 = {2:g} "
                  "è il suo tetto).", top, 10000.0 / top, profile.s_max)
    vmax = min(profile.max_rate_x, profile.max_rate_y)
    fast = max(l.speed for l in layers)
    if fast <= 0 or fast * pct / 100.0 <= vmax:
        return tr("Velocità: sui tratti corti (foto, testi piccoli) le accelerazioni della scheda ($120/$121) possono "
                  "tenere la testa più lenta di quanto chiesto.") if any(l.mode == "image" for l in layers) else ""
    return tr("Velocità: la scheda non va oltre {0:g} mm/min ($110/$111): il livello a {1:g} mm/min sale al massimo del "
              "{2:.0f}%.", vmax, fast, max(100.0, vmax * 100.0 / fast))


def choppy_text(c):
    """Avviso per un livello di foto che a quella velocità può andare a scatti (GcodeJob.choppy)."""
    label, speed, vmax, k = c
    return tr("{0}: foto con punti molto fitti, a {1:g} mm/min la porta non manda i comandi abbastanza in fretta "
              "(circa {2:g} mm/min al massimo): la testa può andare a scatti", label, speed, round(vmax, -2))


def _hms(sec):
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class MovePanel(QWidget):
    goto_bed = Signal(float, float)

    def __init__(self, ctl, settings: QSettings, get_profile, get_head):
        super().__init__()
        self.ctl = ctl
        self.qs = settings
        self.get_profile = get_profile
        self.get_head = get_head
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 6)
        v.setSpacing(5)
        grid = QGridLayout()
        grid.setSpacing(5)
        arrows = [("arrow_ul", -1, 1), ("arrow_up", 0, 1), ("arrow_ur", 1, 1), ("arrow_left", -1, 0), None,
                  ("arrow_right", 1, 0), ("arrow_dl", -1, -1), ("arrow_down", 0, -1), ("arrow_dr", 1, -1)]
        self.jog_buttons = []
        for i, a in enumerate(arrows):
            r, c = divmod(i, 3)
            b = QToolButton()
            b.setFixedSize(52, 44)
            if a is None:
                b.setIcon(style.icon("origin", C["accent_hi"], 22))
                b.setToolTip(tr("Vai all'origine di lavoro (X0 Y0)"))
                b.clicked.connect(lambda: self.ctl.go_to_origin(self.feed.value()))
            else:
                name, dx, dy = a
                b.setIcon(style.icon(name, size=22))
                b.pressed.connect(lambda dx=dx, dy=dy: self._jog_press(dx, dy))
                b.released.connect(self._jog_release)
            b.setIconSize(b.size() * 0.45)
            grid.addWidget(b, r, c)
            self.jog_buttons.append(b)
        top = QHBoxLayout()
        top.addLayout(grid)
        side = QVBoxLayout()
        self.b_home = _btn(tr("Homing"), "home", tip=tr("Ciclo di homing ($H)"))
        self.b_home.clicked.connect(self.ctl.home)
        self.b_unlock = _btn(tr("Sblocca"), "unlock", tip=tr("Sblocca dopo un allarme ($X)"))
        self.b_unlock.clicked.connect(self.ctl.unlock)
        self.b_origin = _btn(tr("Origine qui"), "origin", tip=tr("La posizione attuale diventa l'origine utente (X0 Y0)"))
        self.b_origin.clicked.connect(self.ctl.set_work_origin)
        self.b_clear = _btn(tr("Togli origine"), "x", tip=tr("Origine utente = origine macchina"))
        self.b_clear.clicked.connect(lambda: self.ctl.send_line("G10 L2 P1 X0 Y0"))
        for b in (self.b_home, self.b_unlock, self.b_origin, self.b_clear):
            side.addWidget(b)
        side.addStretch(1)
        top.addLayout(side)
        v.addLayout(top)
        # 0.17.12: asse Z motorizzato e autofocus (si vede solo se il profilo ha l'asse Z)
        self.z_box = QWidget()
        zr = QHBoxLayout(self.z_box)
        zr.setContentsMargins(0, 0, 0, 0)
        zr.addWidget(QLabel("Z"))
        self.b_zup = QToolButton()
        self.b_zup.setText("▲")
        self.b_zup.setToolTip(tr("Asse Z: su del passo scelto"))
        self.b_zdown = QToolButton()
        self.b_zdown.setText("▼")
        self.b_zdown.setToolTip(tr("Asse Z: giù del passo scelto"))
        self.b_zup.clicked.connect(lambda: self._jog_z(+1))
        self.b_zdown.clicked.connect(lambda: self._jog_z(-1))
        self.b_af = _btn(tr("Autofocus"), "verify", tip=tr("Autofocus con la sonda: la testa tocca il materiale e si "
                                                           "porta alla distanza di fuoco (Laser → Asse Z e autofocus)"))
        self.b_af.clicked.connect(self._autofocus)
        for w in (self.b_zup, self.b_zdown, self.b_af):
            zr.addWidget(w)
        zr.addStretch(1)
        v.addWidget(self.z_box)
        self.z_box.setVisible(bool(getattr(self.get_profile(), "z_motor", False)))
        self.ctl.status_changed.connect(self._z_visible)
        seg = QHBoxLayout()
        seg.setSpacing(4)
        self.steps = []
        saved = float(self.qs.value("jog_step", 10))
        for s in (0.1, 1, 10, 50, 100):
            b = QToolButton()
            b.setText(f"{s:g}")
            b.setCheckable(True)
            b.setChecked(abs(s - saved) < 1e-9)
            b.setMinimumWidth(40)
            b.clicked.connect(lambda _=False, s=s, b=b: self._step(s, b))
            seg.addWidget(b)
            self.steps.append((s, b))
        if not any(b.isChecked() for _, b in self.steps):
            self.steps[2][1].setChecked(True)
        self.cont = QCheckBox(tr("Continuo"))
        self.cont.setToolTip(tr("Tieni premuta una freccia: la testa si muove finché non la rilasci"))
        self.cont.setChecked(self.qs.value("jog_cont", "false") == "true")
        self.cont.toggled.connect(lambda x: self.qs.setValue("jog_cont", "true" if x else "false"))
        seg.addWidget(self.cont)
        seg.addStretch(1)
        v.addWidget(QLabel(tr("Passo (mm)")))
        v.addLayout(seg)
        self.feed = units.SpeedSpin(100, 36000, 3000, 500)
        self.feed.setValue(float(self.qs.value("jog_feed", 3000)))
        self.feed.valueChanged.connect(lambda x: self.qs.setValue("jog_feed", x))
        v.addWidget(row(QLabel(tr("Velocità jog")), self.feed))
        v.addWidget(section(tr("Vai a")))
        self.gx = NumField(0, 2, 1, "", 74, 0)
        self.gy = NumField(0, 2, 1, "", 74, 0)
        b_go = _btn(tr("Vai"), "position")
        b_go.clicked.connect(lambda: self.goto_bed.emit(self.gx.value(), self.gy.value()))
        v.addWidget(row(QLabel("X"), self.gx, QLabel("Y"), self.gy, b_go))
        v.addWidget(section(tr("Posizioni salvate")))
        self.saved = QListWidget()
        self.saved.setFixedHeight(110)
        self.saved.itemDoubleClicked.connect(self._go_saved)
        v.addWidget(self.saved)
        b_add = _btn(tr("Salva qui"), "plus")
        b_add.clicked.connect(self._add_saved)
        b_go2 = _btn(tr("Vai"), "position")
        b_go2.clicked.connect(lambda: self._go_saved(self.saved.currentItem()))
        b_del = _btn(tr("Elimina"), "delete")
        b_del.clicked.connect(self._del_saved)
        v.addWidget(row(b_add, b_go2, b_del))
        hint = QLabel(tr("Sulla tela: frecce = jog del passo scelto quando nessun oggetto è selezionato · "
                      "doppio clic con lo strumento «Posiziona laser» porta la testa lì."))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        v.addWidget(hint)
        v.addStretch(1)
        self._load_saved()
        self.set_connected(False)

    def step(self):
        for s, b in self.steps:
            if b.isChecked():
                return s
        return 10.0

    def _step(self, s, btn):
        for _, b in self.steps:
            b.setChecked(b is btn)
        self.qs.setValue("jog_step", s)

    def _jog_press(self, dx, dy):
        if not self.ctl.connected:
            return
        if self.cont.isChecked():
            # con i soft limits GRBL rifiuta un jog oltre l'area: punto esattamente al bordo del piano
            prof = self.get_profile()
            head = self.get_head()
            if head is None:
                return
            import math

            L = math.hypot(dx, dy)
            ux, uy = dx / L, dy / L
            margin = 0.5
            t = float("inf")
            for p, u, hi in ((head.x(), ux, prof.bed_x), (head.y(), uy, prof.bed_y)):
                if u > 0:
                    t = min(t, (hi - margin - p) / u)
                elif u < 0:
                    t = min(t, (p - margin) / -u)
            if t <= 0 or t == float("inf"):
                return
            mx, my = prof.to_machine(head.x() + ux * t, head.y() + uy * t)
            self._cont = True
            self.ctl.goto_machine(mx, my, self.feed.value())
        else:
            self._cont = False
            s = self.step()
            self.ctl.jog(dx * s, dy * s, self.feed.value())

    def _jog_release(self):
        if getattr(self, "_cont", False):
            self.ctl.jog_cancel()
            self._cont = False

    def set_connected(self, ok):
        for w in self.jog_buttons + [self.b_home, self.b_unlock, self.b_origin, self.b_clear, self.b_zup,
                                     self.b_zdown, self.b_af]:
            w.setEnabled(ok)

    def _z_visible(self, *_):
        p = self.get_profile()
        z = bool(getattr(p, "z_motor", False))
        if self.z_box.isHidden() == z:
            self.z_box.setVisible(z)
        af = bool(getattr(p, "af_probe", False))
        if self.b_af.isHidden() == af:
            self.b_af.setVisible(af)

    def _jog_z(self, sign):
        if not self.ctl.connected:
            return
        rate = 300.0
        try:
            rate = float(self.ctl.board_settings.get(112, rate))
        except (TypeError, ValueError):
            pass
        self.ctl.jog_z(sign * min(self.step(), 10.0), min(rate, 1000.0))

    def _autofocus(self):
        p = self.get_profile()
        self.ctl.autofocus(p.af_distance, p.af_travel, p.af_feed, p.af_slow, p.af_toward_minus)

    # posizioni salvate
    def _load_saved(self):
        self.saved.clear()
        try:
            data = json.loads(self.qs.value("saved_positions", "[]"))
        except ValueError:
            data = []
        for d in data:
            it = QListWidgetItem(f"{d['name']}   X{d['x']:.1f} Y{d['y']:.1f}")
            it.setData(Qt.UserRole, d)
            self.saved.addItem(it)

    def _store(self):
        data = [self.saved.item(i).data(Qt.UserRole) for i in range(self.saved.count())]
        self.qs.setValue("saved_positions", json.dumps(data))

    def _add_saved(self):
        p = self.get_head()
        if p is None:
            return
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, tr("Salva posizione"), tr("Nome della posizione:"), text=tr("Posizione {0}", self.saved.count() + 1))
        if not ok:
            return
        d = {"name": name or tr("Posizione"), "x": p.x(), "y": p.y()}
        it = QListWidgetItem(f"{d['name']}   X{d['x']:.1f} Y{d['y']:.1f}")
        it.setData(Qt.UserRole, d)
        self.saved.addItem(it)
        self._store()

    def _go_saved(self, it):
        if it is None:
            return
        d = it.data(Qt.UserRole)
        self.goto_bed.emit(d["x"], d["y"])

    def _del_saved(self):
        r = self.saved.currentRow()
        if r >= 0:
            self.saved.takeItem(r)
            self._store()


def confirm_high_pointer(parent, pct):
    """Avviso quando il puntino supera il 5%: oltre quella soglia non è più solo una luce di riferimento."""
    if os.environ.get("FLC_NO_DIALOGS"):
        return True
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(tr("Puntino oltre il 5%"))
    box.setTextFormat(Qt.RichText)
    box.setText(tr(
        "<b>Stai portando il puntino al {0:g}% della potenza del laser.</b><br><br>"
        "Fino al 5% il puntino serve solo a vedere dove si trova la testa. Più in alto il raggio <b>segna, brucia e "
        "può incendiare</b> legno, carta, cartone e tessuti anche in pochi secondi, e la luce riflessa è più "
        "pericolosa per gli occhi.<br><br>"
        "• Occhiali protettivi per 450 nm per tutti i presenti.<br>"
        "• Tieni premuto solo il tempo che serve: si spegne comunque da solo dopo 20 secondi.<br>"
        "• Punta su uno scarto o su una zona che verrà incisa, mai sul pezzo finito.<br>"
        "• Anche il <i>Contorno con il puntino</i> userà questa potenza e potrebbe lasciare il segno del "
        "rettangolo.<br><br>"
        "Vuoi davvero usare il {0:g}%?", pct))
    yes = box.addButton(tr("Sì, uso il {0:g}%", pct), QMessageBox.AcceptRole)
    box.addButton(tr("No, resto al 5%"), QMessageBox.RejectRole)
    box.setDefaultButton(box.buttons()[-1])
    box.exec()
    return box.clickedButton() is yes


class PointerDialog(QDialog):
    """Trova la potenza del puntino: il B1 non ha un puntatore rosso, il puntino è il laser blu al minimo."""

    def __init__(self, ctl, pct, s_max, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Regola il puntino"))
        self.ctl, self.s_max = ctl, s_max
        self.pct = max(0.1, min(POINTER_MAX, pct))
        self.on = False
        self.setMinimumWidth(440)
        self.auto_off = QTimer(self)
        self.auto_off.setSingleShot(True)
        self.auto_off.setInterval(19500)  # la scheda lo spegne a 20 s: il pulsante si allinea
        self.auto_off.timeout.connect(lambda: self.b_on.setChecked(False))
        v = QVBoxLayout(self)
        txt = QLabel(
            tr("Molti laser a diodo non hanno un puntatore rosso: il puntino è il laser blu a potenza minima. Sotto "
            "una certa potenza il diodo resta spento, sopra comincia a segnare il materiale (oltre il 5% FreeLaserCut "
            "chiede conferma).<br><br>"
            "1. Indossa gli <b>occhiali per 450 nm</b>.<br>"
            "2. Metti sotto la testa uno scarto di legno o di cartone.<br>"
            "3. Premi <b>Accendi</b> e alza con <b>+</b> finché vedi bene il puntino. Se lascia un segno, abbassa."))
        txt.setWordWrap(True)
        txt.setTextFormat(Qt.RichText)
        v.addWidget(txt)
        self.val = QLabel("")
        self.val.setAlignment(Qt.AlignCenter)
        self.val.setStyleSheet("font-size: 26pt; font-weight: 700;")
        self.val.setFont(style.mono_font(26))
        minus = _btn("−")
        plus = _btn("+")
        minus.setAutoRepeat(True)
        plus.setAutoRepeat(True)
        minus.clicked.connect(lambda: self._step(-0.1))
        plus.clicked.connect(lambda: self._step(0.1))
        v.addWidget(row(minus, self.val, plus))
        self.b_on = _btn(tr("Accendi"), "fire", "primary", checkable=True)
        self.b_on.toggled.connect(self._toggle)
        v.addWidget(self.b_on)
        note = QLabel(tr("Si spegne da solo dopo 20 secondi e quando chiudi questa finestra."))
        note.setObjectName("muted")
        note.setWordWrap(True)
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Usa questo valore"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._show()

    def _show(self):
        self.val.setText(f"{self.pct:.1f} %")

    def _step(self, d):
        new = round(max(0.1, min(POINTER_MAX, self.pct + d)), 1)
        if new > POINTER_WARN >= self.pct:
            was_on = self.on
            if was_on:  # durante la domanda il laser resta spento
                self.b_on.setChecked(False)
            if not confirm_high_pointer(self, new):
                return
        self.pct = new
        self._show()
        if self.on:
            self.ctl.fire(True, self.pct, s_max=self.s_max)
            self.auto_off.start()

    def _toggle(self, on):
        self.on = on
        if on:
            self.auto_off.start()
        else:
            self.auto_off.stop()
        self.b_on.setText(tr("Spegni") if on else tr("Accendi"))
        self.ctl.fire(on, self.pct, s_max=self.s_max)

    def done(self, r):
        if self.on:
            self.ctl.fire(False)
            self.on = False
        super().done(r)
