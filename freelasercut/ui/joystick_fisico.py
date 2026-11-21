# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""0.21.2: joystick fisico (richiesta di Ale: il suo Logitech G13 sul PC del laser; vanno anche pad Xbox e PlayStation,
joystick USB e Arduino che si presenta come joystick).

La levetta vera dà solo il vettore a un `JoyJog` (lo stesso motore del joystick sullo schermo): nessuna strada nuova
verso la scheda. Questo modulo non chiama mai `ctl.jog`, `send_line` o `fire`: lo controlla una prova.

Regole (valutazione di sicurezza in `freeburn/coda-0.21.2.md`, voce 1; decisioni di Ale del 21/11 alle 14:26):
1. zona morta larga (15%, regolabile) e taratura del centro all'accensione: se a riposo la levetta sta fuori dalla
   zona morta, non si accende e lo dice;
2. si arma solo dopo aver visto la levetta al centro per 0,3 s, all'accensione e dopo ogni arresto;
3. si ignora se FreeLaserCut non è in primo piano o se c'è una finestra di dialogo aperta;
4. guardiano: senza una lettura fresca da 150 ms il vettore va a zero e la testa si ferma; controller scollegato =
   arresto e «Nessuno»;
6. sulle macchine con l'homing funziona solo dopo l'homing;
7. velocità al massimo la «Velocità jog», mai oltre 6000 mm/min; «piano» la dimezza;
8. nessun pulsante accende il laser (né Puntino, né Lucciola, né Avvia);
10. un solo padrone: il joystick sullo schermo, le frecce e la tastiera vincono, la levetta si riarma dopo il centro;
12. Homing e «Vai a X0 Y0» solo tenendo premuto 1 s;
13. si ricorda il controller per nome e GUID, ma se all'avvio non c'è resta «Nessuno»: mai un altro al suo posto;
14. va riacceso a ogni avvio di FreeLaserCut;
15. ogni errore della libreria spegne la funzione con un messaggio, mai un blocco;
17. asse Z solo a passi.
"""
import json
import math
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from .. import gamepad
from ..i18n import tr
from .jogpad import JoyJog

SPEED_CAP = 6000.0  # mm/min, decisione di Ale
DEAD_DEFAULT = 0.15
ARM_S = 0.30  # levetta al centro per tanto, prima di muovere
WATCHDOG_S = 0.15  # senza letture fresche da tanto: fermo
HOLD_S = 1.0  # Homing e «Vai a X0 Y0»: pulsante tenuto premuto per tanto
POLL_MS = 20
USER_JOG_S = 0.30  # dopo un jog di frecce, tastiera o joystick sullo schermo la levetta aspetta il centro

# comandi che si possono dare ai pulsanti (decisione 3 di Ale). Nessuno accende il laser: niente Puntino, Lucciola,
# Avvia, Contorno con il laser acceso. «Contorno» è il percorso a laser spento.
COMMANDS = ("stop", "home", "goto0", "step_up", "step_down", "slow", "z_up", "z_down", "frame")
HOLD_COMMANDS = ("home", "goto0")


def command_label(cmd):
    return {
        "stop": tr("Stop"),
        "home": tr("Homing (tieni premuto 1 s)"),
        "goto0": tr("Vai a X0 Y0 (tieni premuto 1 s)"),
        "step_up": tr("Passo più grande"),
        "step_down": tr("Passo più piccolo"),
        "slow": tr("Piano (metà velocità, tieni premuto)"),
        "z_up": tr("Asse Z su di un passo"),
        "z_down": tr("Asse Z giù di un passo"),
        "frame": tr("Contorno (a laser spento)"),
    }.get(cmd, cmd)


class PhysicalJoystick(QObject):
    """Il controller scelto nella scheda Movimento. Si accende con `enable()`, si spegne con `disable()`."""

    changed = Signal()  # stato, motivo o elenco dei controller cambiati: la scheda Movimento si ridisegna

    def __init__(self, ctl, qs, get_profile, get_head, get_feed, actions, parent=None, clock=None, backend=None,
                 user_busy=None, allowed=None):
        super().__init__(parent)
        self.ctl, self.qs, self.get_profile = ctl, qs, get_profile
        self.get_feed_user = get_feed
        self.actions = actions  # {comando: funzione}
        self.clock = clock or time.monotonic
        self._backend = backend
        self.user_busy = user_busy or (lambda: False)  # True: frecce, tastiera o joystick sullo schermo in uso
        self.allowed = allowed or self._allowed_default
        self.joy = JoyJog(ctl, get_profile, get_head, self.feed, self, clock=self.clock)
        self.devices = []
        self.device = None
        self.enabled = False
        self.armed = False
        self.reason = ""
        self.slow = False
        self.center = (0.0, 0.0)
        self.vec = (0.0, 0.0)
        self._centered_since = None
        self._last_t = None
        self._buttons = []
        self._pressed_at = {}
        self._fired = set()
        self._t = QTimer(self)
        self._t.setInterval(POLL_MS)
        self._t.timeout.connect(self.tick)

    # ------------------------------------------------------------------ impostazioni
    def dead(self):
        try:
            v = float(self.qs.value("pjoy_dead", DEAD_DEFAULT))
        except (TypeError, ValueError):
            v = DEAD_DEFAULT
        return min(0.40, max(0.05, v)) if v == v else DEAD_DEFAULT

    def invert_y(self):
        return str(self.qs.value("pjoy_invert_y", "false")).lower() == "true"

    def mapping(self):
        """{indice del pulsante: comando}, solo comandi ammessi (un file vecchio o rovinato non porta altro)."""
        try:
            raw = json.loads(self.qs.value("pjoy_map", "{}") or "{}")
        except (TypeError, ValueError):
            raw = {}
        out = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                try:
                    b = int(k)
                except (TypeError, ValueError):
                    continue
                if v in COMMANDS and 0 <= b < 128:
                    out[b] = v
        return out

    def set_mapping(self, mapping):
        clean = {str(int(b)): c for b, c in mapping.items() if c in COMMANDS}
        self.qs.setValue("pjoy_map", json.dumps(clean, sort_keys=True))

    def feed(self):
        """Velocità massima della levetta: «Velocità jog», mai oltre 6000 mm/min; «piano» la dimezza."""
        try:
            v = float(self.get_feed_user())
        except (TypeError, ValueError):
            v = 1000.0
        v = min(max(v, 10.0), SPEED_CAP)
        return v / 2.0 if self.slow else v

    # ------------------------------------------------------------------ controller
    def backend(self):
        return self._backend if self._backend is not None else gamepad.backend()

    def available(self):
        return self.backend() is not None

    def refresh(self):
        """Rifà l'elenco. Il controller ricordato si propone solo se c'è lui (nome e GUID): mai un altro al suo posto."""
        b = self.backend()
        if b is None:
            self.devices = []
            self._set_reason(tr("Joystick fisico non disponibile: {0}", gamepad.error() or "?"))
            self.changed.emit()
            return []
        try:
            self.devices = b.devices()
        except gamepad.GamepadError as ex:
            self.devices = []
            self._set_reason(tr("Controller non letti: {0}", ex))
        keep = self.device.key() if self.device is not None else self.qs.value("pjoy_device", "")
        self.device = next((d for d in self.devices if d.key() == keep), None)
        if self.device is None and self.enabled:
            self.disable(tr("Controller scollegato"))
        self.changed.emit()
        return self.devices

    def choose(self, dev):
        """dev = Device o None («Nessuno»). Cambiando controller il joystick fisico si spegne."""
        if self.enabled:
            self.disable()
        self.device = dev
        self.qs.setValue("pjoy_device", dev.key() if dev is not None else "")
        self.changed.emit()

    # ------------------------------------------------------------------ accensione
    def _set_reason(self, text):
        self.reason = text

    def homing_needed(self):
        p = self.get_profile()
        return bool(getattr(p, "homing", False)) and not getattr(self.ctl, "homed", False)

    def enable(self):
        """Accende la levetta. False, con il motivo in `reason`, se non si può."""
        if self.device is None:
            self._set_reason(tr("Scegli prima il controller"))
            self.changed.emit()
            return False
        if self.homing_needed():
            self._set_reason(tr("Fai prima l'homing: senza, FreeLaserCut non sa dov'è la testa"))
            self.changed.emit()
            return False
        try:
            r = self.backend().read(self.device)
        except (gamepad.GamepadError, AttributeError) as ex:
            self._set_reason(tr("Controller non leggibile: {0}", ex))
            self.changed.emit()
            return False
        x, y = (r.axes + [0.0, 0.0])[:2]
        if math.hypot(x, y) > self.dead():
            self._set_reason(tr("Lascia la levetta al centro, poi accendi"))
            self.changed.emit()
            return False
        self.center = (x, y)  # taratura: la levetta vecchia che non torna proprio a zero
        self.enabled = True
        self.armed = False
        self._centered_since = None
        self._last_t = r.t
        self._buttons = list(r.buttons)
        self._pressed_at.clear()
        self._fired.clear()
        self._set_reason(tr("Attivo: muovi la levetta"))
        self._t.start()
        self.changed.emit()
        return True

    def disable(self, reason=""):
        was = self.enabled
        self.enabled = False
        self.armed = False
        self._t.stop()
        self._stop_motion()
        self.slow = False
        self._set_reason(reason or tr("Spento"))
        if was or reason:
            self.changed.emit()
        return was

    def _stop_motion(self):
        self.vec = (0.0, 0.0)
        self.joy.set_vector(0.0, 0.0)
        if self.joy.active:
            self.joy.stop()

    def _disarm(self, reason):
        if self.armed or self.joy.active:
            self._stop_motion()
            self._set_reason(reason)
            self.changed.emit()
        self.armed = False
        self._centered_since = None

    # ------------------------------------------------------------------ lettura
    @staticmethod
    def _allowed_default():
        app = QGuiApplication.instance()
        if app is None or app.applicationState() != Qt.ApplicationActive:
            return False
        return QApplication.activeModalWidget() is None

    def vector(self, axes):
        """Vettore per il JoyJog: centro tolto, zona morta, curva morbida, «su» della levetta = su del piano."""
        x, y = (list(axes) + [0.0, 0.0])[:2]
        x -= self.center[0]
        y -= self.center[1]
        y = -y if not self.invert_y() else y  # SDL: su = -1
        m = math.hypot(x, y)
        dz = self.dead()
        if m <= dz:
            return (0.0, 0.0)
        k = min(1.0, (m - dz) / (1.0 - dz)) ** 1.6 / m  # curva morbida: piano vicino al centro
        return (x * k, y * k)

    def tick(self):
        if not self.enabled:
            return
        now = self.clock()
        try:
            r = self.backend().read(self.device)
        except (gamepad.GamepadError, AttributeError):
            self.disable(tr("Controller scollegato o non leggibile: fermato"))
            self.device = None
            self.refresh()
            return
        if self._last_t is not None and r.t <= self._last_t:
            if now - self._last_t > WATCHDOG_S:  # stessa lettura da troppo: lettura bloccata
                self._disarm(tr("Il controller non risponde: fermato"))
            return
        self._last_t = r.t
        self._buttons_tick(r.buttons, now)
        if not self.enabled:
            return  # un pulsante (Stop) l'ha spento
        if self.homing_needed():
            self.disable(tr("Fai prima l'homing: la posizione della testa non è più sicura"))
            return
        v = self.vector(r.axes)
        if not self.allowed():
            self._disarm(tr("FreeLaserCut non è in primo piano: levetta ignorata"))
            return
        if self.user_busy():
            self._disarm(tr("In uso le frecce o il joystick sullo schermo: levetta ignorata"))
            return
        if not self.joy.can_move():
            self._disarm(tr("Macchina non pronta: levetta ignorata"))
            return
        if not self.armed:
            if v == (0.0, 0.0):
                if self._centered_since is None:
                    self._centered_since = now
                if now - self._centered_since >= ARM_S:
                    self.armed = True
                    self._set_reason(tr("Attivo: muovi la levetta"))
                    self.changed.emit()
            else:
                self._centered_since = None
                if self.reason != tr("Riporta la levetta al centro"):
                    self._set_reason(tr("Riporta la levetta al centro"))
                    self.changed.emit()
            return
        self.vec = v
        if v == (0.0, 0.0):
            if self.joy.active:
                self.joy.stop()
            return
        self.joy.set_vector(*v)
        if not self.joy.active and not self.joy.start():
            self._disarm(self.joy.stop_reason or tr("La testa non si può muovere"))

    def _buttons_tick(self, buttons, now):
        mp = self.mapping()
        for b, cmd in mp.items():
            down = b < len(buttons) and bool(buttons[b])
            was = b < len(self._buttons) and bool(self._buttons[b])
            if cmd == "slow":
                self.slow = down
                continue
            if down and not was:
                self._pressed_at[b] = now
                self._fired.discard(b)
                if cmd not in HOLD_COMMANDS:
                    self._run(cmd)
            elif down and cmd in HOLD_COMMANDS and b not in self._fired and now - self._pressed_at.get(b, now) >= HOLD_S:
                self._fired.add(b)
                self._run(cmd)
            elif not down:
                self._pressed_at.pop(b, None)
                self._fired.discard(b)
        self._buttons = list(buttons)

    def _run(self, cmd):
        if cmd == "stop":
            self._stop_motion()
            fn = self.actions.get("stop")
            if fn:
                fn()
            self.disable(tr("Stop dal controller"))
            return
        if cmd not in COMMANDS or not self.allowed():
            return
        if cmd == "home" and (self.ctl.job_active or getattr(self.ctl, "checking", False) or not self.ctl.connected):
            return
        if cmd in ("goto0", "frame", "z_up", "z_down") and not self.joy.can_move():
            return
        self._stop_motion()
        self.armed = False
        self._centered_since = None
        fn = self.actions.get(cmd)
        if fn:
            fn()


# ====================================================================== interfaccia
from PySide6.QtWidgets import (  # noqa: E402
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QToolButton,
    QVBoxLayout, QWidget,
)


class _DeviceCombo(QComboBox):
    """La tendina dei controller: l'elenco (e la libreria) si caricano solo quando la si apre."""

    def __init__(self, pj):
        super().__init__()
        self.pj = pj
        self.setToolTip(tr("Il controller con cui muovere la testa (Logitech G13 in modalità joystick, pad Xbox o "
                           "PlayStation, joystick USB). L'elenco si aggiorna aprendo la tendina."))
        self.currentIndexChanged.connect(self._picked)
        self.fill()

    def fill(self):
        self.blockSignals(True)
        self.clear()
        self.addItem(tr("Nessuno"), None)
        devs = list(self.pj.devices)
        if self.pj.device is not None and all(d.key() != self.pj.device.key() for d in devs):
            devs.insert(0, self.pj.device)
        for d in devs:
            self.addItem(d.name, d)
            if self.pj.device is not None and d.key() == self.pj.device.key():
                self.setCurrentIndex(self.count() - 1)
        self.blockSignals(False)

    def showPopup(self):
        self.pj.refresh()
        self.fill()
        super().showPopup()

    def _picked(self, i):
        self.pj.choose(self.itemData(i))


class PhysicalJoystickBox(QWidget):
    """Nella scheda Movimento, sotto «Togli origine»: tendina, «Attivo» e impostazioni."""

    def __init__(self, pj, parent=None):
        super().__init__(parent)
        self.pj = pj
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(3)
        v.addWidget(QLabel(tr("Joystick fisico")))
        self.combo = _DeviceCombo(pj)
        self.combo.setMaximumWidth(170)
        v.addWidget(self.combo)
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        self.on = QCheckBox(tr("Attivo"))
        self.on.setToolTip(tr("Accende la levetta vera. Va riacceso a ogni avvio di FreeLaserCut. Sulle macchine con "
                              "l'homing funziona solo dopo l'homing; la testa va al massimo alla «Velocità jog» (mai "
                              "oltre 6000 mm/min). Nessun pulsante del controller accende il laser."))
        self.on.toggled.connect(self._toggled)
        self.cfg = QToolButton()
        self.cfg.setText("…")
        self.cfg.setToolTip(tr("Zona morta, verso della levetta e comandi dei pulsanti"))
        self.cfg.clicked.connect(self.settings)
        h.addWidget(self.on)
        h.addWidget(self.cfg)
        h.addStretch(1)
        v.addLayout(h)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        self.status.setMaximumWidth(170)
        v.addWidget(self.status)
        pj.changed.connect(self.sync)
        self.sync()

    def _toggled(self, on):
        if on and not self.pj.enabled:
            if not self.pj.enable():
                self.on.blockSignals(True)
                self.on.setChecked(False)
                self.on.blockSignals(False)
        elif not on and self.pj.enabled:
            self.pj.disable()
        self.sync()

    def sync(self):
        self.on.blockSignals(True)
        self.on.setChecked(self.pj.enabled)
        self.on.setEnabled(self.pj.device is not None)
        self.on.blockSignals(False)
        if self.combo.itemData(self.combo.currentIndex()) is not self.pj.device:
            self.combo.fill()
        self.status.setText(self.pj.reason if self.pj.device is not None or self.pj.reason else "")

    def settings(self):
        d = PhysicalJoystickDialog(self.pj, self)
        d.exec()
        self.sync()


class PhysicalJoystickDialog(QDialog):
    def __init__(self, pj, parent=None):
        super().__init__(parent)
        self.pj = pj
        self.setWindowTitle(tr("Joystick fisico"))
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.dead = QDoubleSpinBox()
        self.dead.setRange(5.0, 40.0)
        self.dead.setDecimals(0)
        self.dead.setSuffix(" %")
        self.dead.setValue(pj.dead() * 100.0)
        self.dead.setToolTip(tr("Quanto si può spostare la levetta senza che la testa si muova: più grande per i "
                                "controller vecchi che non tornano bene al centro"))
        f.addRow(tr("Zona morta"), self.dead)
        self.inv = QCheckBox(tr("Inverti su e giù della levetta"))
        self.inv.setChecked(pj.invert_y())
        f.addRow("", self.inv)
        v.addLayout(f)
        v.addWidget(QLabel(tr("Comandi dei pulsanti (nessuno accende il laser):")))
        n = max(pj.device.buttons if pj.device is not None else 0, 16)
        cur = {c: b for b, c in pj.mapping().items()}
        g = QFormLayout()
        self.boxes = {}
        for cmd in COMMANDS:
            cb = QComboBox()
            cb.addItem("—", None)
            for b in range(n):
                cb.addItem(tr("Pulsante {0}", b + 1), b)
            if cmd in cur:
                cb.setCurrentIndex(cb.findData(cur[cmd]))
            self.boxes[cmd] = cb
            g.addRow(command_label(cmd), cb)
        v.addLayout(g)
        self.live = QLabel("")
        self.live.setObjectName("muted")
        v.addWidget(self.live)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("Applica"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("Annulla"))
        bb.accepted.connect(self.apply)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._t = QTimer(self)
        self._t.setInterval(100)
        self._t.timeout.connect(self._live)
        self._t.start()

    def _live(self):
        """Quali pulsanti sono premuti adesso: per sapere il numero da scegliere."""
        if self.pj.device is None or self.pj.backend() is None:
            self.live.setText(tr("Scegli prima il controller nella scheda Movimento"))
            return
        try:
            r = self.pj.backend().read(self.pj.device)
        except gamepad.GamepadError:
            self.live.setText(tr("Controller non leggibile"))
            return
        down = [str(i + 1) for i, b in enumerate(r.buttons) if b]
        self.live.setText(tr("Premuti adesso: {0}", ", ".join(down) if down else "—"))

    def apply(self):
        self.pj.qs.setValue("pjoy_dead", self.dead.value() / 100.0)
        self.pj.qs.setValue("pjoy_invert_y", "true" if self.inv.isChecked() else "false")
        used, mp = set(), {}
        for cmd, cb in self.boxes.items():
            b = cb.currentData()
            if b is not None and b not in used:
                used.add(b)
                mp[b] = cmd
        self.pj.set_mapping(mp)
        self.accept()
