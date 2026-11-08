# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Laser → Asse Z e autofocus… (0.17.12): asse Z motorizzato, sonda e autofocus con G38.2."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QToolButton, QVBoxLayout)

from .. import autofocus
from freelasercut.i18n import tr  # noqa: E402


def _spin(lo, hi, val, dec=1, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    if suffix:
        s.setSuffix(" " + suffix)
    return s


class AutofocusDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.ctl = win.ctl
        p = win.profile
        self.setWindowTitle(tr("Asse Z e autofocus"))
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        intro = QLabel(tr("Con l'asse Z motorizzato e una sonda, FreeLaserCut mette a fuoco da solo: a laser spento la "
                          "testa scende piano finché la sonda tocca il materiale, lo ritocca lentamente e poi si "
                          "allontana della distanza di fuoco. La sonda va collegata all'ingresso «Probe» della scheda "
                          "(non a un finecorsa)."))
        intro.setWordWrap(True)
        v.addWidget(intro)
        f = QFormLayout()
        self.z_motor = QCheckBox(tr("La macchina ha l'asse Z motorizzato"))
        self.z_motor.setChecked(bool(p.z_motor))
        f.addRow(self.z_motor)
        self.probe = QCheckBox(tr("Ho una sonda per l'autofocus"))
        self.probe.setChecked(bool(p.af_probe))
        f.addRow(self.probe)
        self.distance = _spin(0.0, 100.0, float(p.af_distance), 2, "mm")
        self.distance.setToolTip(tr("Dopo il tocco la testa si allontana di tanto dal materiale: la distanza a cui il "
                                    "tuo laser è a fuoco"))
        f.addRow(tr("Distanza di fuoco"), self.distance)
        self.travel = _spin(1.0, 200.0, float(p.af_travel), 1, "mm")
        self.travel.setToolTip(tr("Se entro questa corsa la sonda non tocca niente, la scheda si ferma da sola"))
        f.addRow(tr("Corsa massima in cerca del materiale"), self.travel)
        self.feed = _spin(1.0, 3000.0, float(p.af_feed), 0, "mm/min")
        f.addRow(tr("Velocità di ricerca"), self.feed)
        self.slow = _spin(1.0, 1000.0, float(p.af_slow), 0, "mm/min")
        self.slow.setToolTip(tr("Secondo tocco, lento: è quello che decide la misura"))
        f.addRow(tr("Secondo tocco (lento)"), self.slow)
        self.direction = QComboBox()
        self.direction.addItem(tr("Z− (la testa scende verso il materiale)"), True)
        self.direction.addItem(tr("Z+ (macchine con il verso al contrario)"), False)
        self.direction.setCurrentIndex(0 if p.af_toward_minus else 1)
        f.addRow(tr("Verso il materiale"), self.direction)
        v.addLayout(f)
        zr = QHBoxLayout()
        zr.addWidget(QLabel(tr("Muovi Z")))
        self.z_step = QComboBox()
        for s in (0.1, 1.0, 5.0, 10.0):
            self.z_step.addItem(f"{s:g} mm", s)
        self.z_step.setCurrentIndex(1)
        self.b_up = QToolButton()
        self.b_up.setText(tr("▲ su"))
        self.b_down = QToolButton()
        self.b_down.setText(tr("▼ giù"))
        self.b_up.clicked.connect(lambda: self._jog(+1))
        self.b_down.clicked.connect(lambda: self._jog(-1))
        for w in (self.z_step, self.b_up, self.b_down):
            zr.addWidget(w)
        zr.addStretch(1)
        v.addLayout(zr)
        self.pin = QLabel()
        self.pin.setWordWrap(True)
        v.addWidget(self.pin)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        v.addWidget(self.result)
        br = QHBoxLayout()
        self.b_run = QPushButton(tr("Esegui l'autofocus"))
        self.b_run.setObjectName("primary")
        self.b_run.clicked.connect(self.run)
        b_save = QPushButton(tr("Salva nel profilo"))
        b_save.clicked.connect(self.save)
        b_close = QPushButton(tr("Chiudi"))
        b_close.clicked.connect(self.accept)
        br.addWidget(self.b_run)
        br.addStretch(1)
        br.addWidget(b_save)
        br.addWidget(b_close)
        v.addLayout(br)
        self.ctl.status_changed.connect(self._status)
        self.ctl.autofocus_done.connect(self._done)
        self.z_motor.toggled.connect(self._state)
        self.probe.toggled.connect(self._state)
        self._status(self.ctl.last_status)
        self._state()

    def _jog(self, sign):
        if not self.ctl.connected:
            return
        s = float(self.z_step.currentData())
        rate = 300.0
        try:
            rate = float(self.ctl.board_settings.get(112, rate))
        except (TypeError, ValueError):
            pass
        self.ctl.jog_z(sign * s, min(rate, 1000.0))

    def _state(self, *_):
        z = self.z_motor.isChecked()
        self.probe.setEnabled(z)
        on = z and self.probe.isChecked()
        for w in (self.distance, self.travel, self.feed, self.slow, self.direction):
            w.setEnabled(on)
        for w in (self.b_up, self.b_down, self.z_step):
            w.setEnabled(z and self.ctl.connected)
        self.b_run.setEnabled(on and self.ctl.connected and not self.ctl.autofocusing)

    def _status(self, st):
        if not self.ctl.connected:
            self.pin.setText(tr("Collega il laser per provare la sonda e l'autofocus."))
        else:
            self.pin.setText(autofocus.pin_text((st or {}).get("pins")))
        self._state()

    def values(self):
        return dict(z_motor=self.z_motor.isChecked(), af_probe=self.z_motor.isChecked() and self.probe.isChecked(),
                    af_distance=self.distance.value(), af_travel=self.travel.value(), af_feed=self.feed.value(),
                    af_slow=self.slow.value(), af_toward_minus=bool(self.direction.currentData()))

    def save(self):
        p = self.win.profile
        for k, val in self.values().items():
            setattr(p, k, val)
        sim = getattr(self.win, "_on_sim", False)
        if not sim:
            try:
                p.save()
            except OSError:
                pass
        self.result.setText(tr("Salvato nel profilo «{0}».", p.name))

    def run(self):
        self.save()
        p = self.win.profile
        self.result.setText(tr("Autofocus in corso: la testa scende piano verso il materiale…"))
        self.b_run.setEnabled(False)
        self.ctl.autofocus(p.af_distance, p.af_travel, p.af_feed, p.af_slow, p.af_toward_minus)

    def _done(self, ok, msg, z):
        self.result.setText(msg if ok or not msg else tr("Autofocus non riuscito: {0}", msg))
        self._state()

    def done(self, r):
        for sig, slot in ((self.ctl.status_changed, self._status), (self.ctl.autofocus_done, self._done)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().done(r)
