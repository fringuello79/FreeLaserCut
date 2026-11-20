# FreeLaserCut — © 2026 fringuello79 — GPL-3.0-or-later
"""Comandi di movimento della testa (0.19.5), uguali nella scheda Movimento e in Stampa e taglia.

- Frecce: croce 3 × 3 con 8 frecce (passo scelto nella fila sotto, «Continuo» = finché tieni premuto) e al centro
  Puntino (tieni premuto) e Lucciola (resta accesa): sono gli stessi comandi della scheda Laser (stessa potenza,
  stessi avvisi, stesso spegnimento automatico).
- Joystick: manopola da trascinare, direzione libera e velocità proporzionale alla distanza dal centro fino alla
  «Velocità jog»; al rilascio la testa si ferma. Sulla scheda è il «jog a bassa latenza» di GRBL: pezzetti corti
  ($J=G91) mandati di continuo, al massimo MAX_Q in attesa, e al rilascio l'arresto del jog (0x85).
"""
import math
import time

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QGridLayout, QHBoxLayout, QLabel, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from ..theme import C
from . import style
from freelasercut.i18n import tr  # noqa: E402

STEPS = (0.1, 1, 10, 50, 100)
TAG = "joy"


# ======================================================================= joystick: la logica (senza finestra)
class JoyJog(QObject):
    """Movimento continuo dal joystick. set_vector(ux, uy): vettore nel cerchio unitario (y verso l'alto del piano,
    lunghezza 0…1).

    0.21.1 (leone2805 su GitHub e Ale: «il cambio di direzione non è immediato, anche qualche secondo»): GRBL risponde
    «ok» a un jog appena lo mette nella sua coda dei movimenti, non quando l'ha percorso. Fino alla 0.21.0 ogni 25 ms
    partiva un pezzetto da 60 ms se c'erano meno di 2 righe senza «ok»: quasi sempre, quindi ogni secondo arrivavano
    circa 2,4 secondi di movimento e la coda della scheda si riempiva (fino a 7 s di ritardo con i 127 posti del Falcon
    A1). Ora i pezzetti partono al ritmo del tempo vero: davanti alla testa resta solo il movimento di `lead()` secondi
    (un decimo di secondo, di più solo se l'accelerazione della macchina lo chiede per arrivare alla velocità), e in più
    si controlla dove è davvero la testa: se il movimento mandato è troppo avanti rispetto a lei, si aspetta."""
    DEAD = 0.08  # zona morta al centro
    SEG_T = 0.05  # durata di un pezzetto (s)
    MAX_Q = 2  # pezzetti al massimo senza «ok» della scheda
    TICK_MS = 20
    MARGIN = 0.5  # mm dal bordo dell'area
    LEAD_MIN = 0.10  # s di movimento al massimo davanti alla testa (di solito)
    LEAD_MAX = 0.40  # s: tetto anche per le macchine con accelerazione molto bassa
    POS_SLACK = 0.30  # s: ritardo della posizione letta (lo stato arriva ogni 0,2 s) per il controllo sulla testa
    SETTLE = 0.35  # s dopo la fine prevista: la posizione letta è quella vera e si riparte da lì

    def __init__(self, ctl, get_profile, get_head, get_feed, parent=None, clock=None):
        super().__init__(parent)
        self.ctl, self.get_profile, self.get_head, self.get_feed = ctl, get_profile, get_head, get_feed
        self.clock = clock or time.monotonic
        self.active = False
        self.vec = (0.0, 0.0)
        self.pos = None  # posizione pianificata sul piano (testa + pezzetti già mandati)
        self.sent = 0  # pezzetti mandati da quando è attivo
        self.plan_end = 0.0  # quando la scheda avrà finito i pezzetti mandati (stima, orologio self.clock)
        self.stop_reason = ""
        self._t = QTimer(self)
        self._t.setInterval(self.TICK_MS)
        self._t.timeout.connect(self.tick)
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._app_state)

    def _app_state(self, st):
        if st != Qt.ApplicationActive:
            self.stop(tr("FreeLaserCut non è più in primo piano"))

    def can_move(self):
        c = self.ctl
        return (bool(c.connected) and not c.job_active and not getattr(c, "checking", False)
                and c.last_status.get("state") not in ("Alarm", "Door", "Hold", "Sleep"))

    def start(self):
        if not self.can_move():
            self.stop_reason = tr("Macchina non pronta: collegala, sbloccala o aspetta la fine del lavoro")
            return False
        head = self.get_head()
        if head is None:
            self.stop_reason = tr("Posizione della testa non ancora nota")
            return False
        self.pos = (float(head.x()), float(head.y()))
        self.active = True
        self.sent = 0
        self.plan_end = self.clock()
        self.stop_reason = ""
        self._t.start()
        return True

    def set_vector(self, ux, uy):
        m = math.hypot(ux, uy)
        if m > 1.0:
            ux, uy = ux / m, uy / m
        self.vec = (float(ux), float(uy))

    def magnitude(self):
        return math.hypot(*self.vec)

    def speed(self):
        """Velocità chiesta (mm/min) per il vettore attuale: 0 nella zona morta."""
        m = self.magnitude()
        if m <= self.DEAD:
            return 0.0
        return (m - self.DEAD) / (1.0 - self.DEAD) * float(self.get_feed())

    def angle(self):
        return (math.degrees(math.atan2(self.vec[1], self.vec[0])) + 360.0) % 360.0

    def accel(self):
        """Accelerazione della macchina (mm/s²): la più bassa dei due assi, dal profilo ($120/$121)."""
        prof = self.get_profile()
        vals = []
        for k in ("accel_x", "accel_y"):
            try:
                v = float(getattr(prof, k, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0 and math.isfinite(v):
                vals.append(v)
        return min(vals) if vals else 500.0

    def lead(self, v=None):
        """Secondi di movimento da tenere davanti alla testa alla velocità v (mm/min). La scheda deve poter frenare
        entro il movimento che ha in coda: per arrivare a v servono almeno v²/(2a) mm, cioè v/(2a) secondi."""
        v = self.speed() if v is None else v
        need = 1.2 * (v / 60.0) / (2.0 * self.accel()) + self.SEG_T  # + un pezzetto: si manda a metà pezzetto
        return min(self.LEAD_MAX, max(self.LEAD_MIN, need))

    def _head(self):
        h = self.get_head()
        return None if h is None else (float(h.x()), float(h.y()))

    def tick(self):
        if not self.active:
            return
        if not self.can_move():
            self.stop(tr("Joystick fermato: la macchina non è più pronta"))
            return
        now = self.clock()
        idle_q = self.ctl.queued(TAG) == 0
        if idle_q and now > self.plan_end + self.SETTLE:
            head = self._head()  # tutto finito da un po': si riparte dalla posizione vera, non da quella stimata
            if head is not None:
                self.pos = head
        v = self.speed()
        if v <= 0 or self.ctl.queued(TAG) >= self.MAX_Q:
            return
        lead = self.lead(v)
        if self.plan_end - now > lead - self.SEG_T / 2:
            return  # davanti alla testa c'è già abbastanza movimento
        head = self._head()
        if head is not None and self.pos is not None:
            behind = math.dist(head, self.pos)  # quanto il movimento mandato è avanti rispetto alla testa vera
            if behind > v / 60.0 * (lead + self.POS_SLACK) + 1.0:
                return
        m = self.magnitude()
        seg = self.SEG_T
        d = v / 60.0 * seg
        dx, dy = self.vec[0] / m * d, self.vec[1] / m * d
        prof = self.get_profile()
        bx = float(getattr(prof, "bed_x", 0) or 0)
        by = float(getattr(prof, "bed_y", 0) or 0)
        x, y = self.pos
        nx, ny = self._limit(x, dx, bx), self._limit(y, dy, by)
        ddx, ddy = nx - x, ny - y
        dist = math.hypot(ddx, ddy)
        if dist < 0.005:
            return  # al bordo: fermo finché non cambi direzione
        self.ctl.jog(ddx, ddy, v, tag=TAG)
        self.pos = (nx, ny)
        self.plan_end = max(self.plan_end, now) + dist / (v / 60.0)
        self.sent += 1

    def _limit(self, p, d, size):
        """Nuova coordinata su un asse: si ferma a MARGIN dal bordo verso cui si va, e non si muove mai nel verso
        opposto a quello chiesto (con la testa già oltre il margine resta dov'è)."""
        if size <= 2 * self.MARGIN or d == 0:
            return p + d if size <= 2 * self.MARGIN else p
        if d > 0:
            return min(p + d, max(p, size - self.MARGIN))
        return max(p + d, min(p, self.MARGIN))

    def stop(self, reason=""):
        was = self.active
        self.active = False
        self._t.stop()
        self.vec = (0.0, 0.0)
        if reason:
            self.stop_reason = reason
        if was and self.ctl.connected:
            self.ctl.jog_cancel(tag=TAG)
        return was


# ======================================================================= joystick: il disegno
class JoystickPad(QWidget):
    """Cerchio con anello graduato e manopola. Tieni premuto e trascina; al rilascio la manopola torna al centro."""
    SIZE = 180

    def __init__(self, joy, on_change=None, parent=None):
        super().__init__(parent)
        self.joy = joy
        self.on_change = on_change
        self.knob = QPointF(0, 0)  # in unità del raggio utile, y verso l'alto
        self.pressed = False
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(tr("Joystick: tieni premuto e trascina. La testa va nella direzione della manopola, più "
                           "veloce più la allontani dal centro (fino alla «Velocità jog»); al rilascio si ferma. "
                           "Si ferma anche con Esc, se il mouse esce dalla finestra o se cambi programma."))

    def _geo(self):
        c = QPointF(self.width() / 2, self.height() / 2)
        r_out = min(self.width(), self.height()) / 2 - 6
        return c, r_out, r_out * 0.71  # centro, bordo, raggio utile della manopola

    def _set_from(self, pos):
        c, _, r = self._geo()
        x, y = (pos.x() - c.x()) / r, -(pos.y() - c.y()) / r
        m = math.hypot(x, y)
        if m > 1:
            x, y = x / m, y / m
        self.knob = QPointF(x, y)
        self.joy.set_vector(x, y)
        self.update()
        if self.on_change:
            self.on_change()

    def _release(self, reason=""):
        if not self.pressed and not self.joy.active:
            return
        self.pressed = False
        self.knob = QPointF(0, 0)
        self.joy.stop(reason)
        self.setCursor(Qt.OpenHandCursor)
        self.update()
        if self.on_change:
            self.on_change()

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton or not self.isEnabled():
            return
        self.setFocus()
        self.pressed = True
        self.setCursor(Qt.ClosedHandCursor)
        self._set_from(e.position())
        if not self.joy.start():
            self.pressed = False
            self.knob = QPointF(0, 0)
            self.joy.set_vector(0, 0)
            self.update()
            if self.on_change:
                self.on_change()

    def mouseMoveEvent(self, e):
        if self.pressed:
            self._set_from(e.position())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._release()

    def focusOutEvent(self, e):
        self._release(tr("Joystick fermato"))
        super().focusOutEvent(e)

    def hideEvent(self, e):
        self._release()
        super().hideEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._release(tr("Joystick fermato con Esc"))
            return
        super().keyPressEvent(e)

    def changeEvent(self, e):
        super().changeEvent(e)
        if not self.isEnabled():
            self._release()

    def paintEvent(self, _e):
        c, ro, r = self._geo()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        en = self.isEnabled()
        line = QColor(C["border"])
        p.setPen(QPen(line, 1))
        p.setBrush(QColor(C["panel2"]))
        p.drawEllipse(c, ro, ro)
        for a in range(0, 360, 15):  # anello graduato: tacche ogni 15°, più lunghe ogni 45°
            L = 9 if a % 45 == 0 else 4
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            p.setPen(QPen(QColor(C["muted"]), 1.2 if a % 45 == 0 else 1))
            p.drawLine(QPointF(c.x() + ca * ro, c.y() + sa * ro), QPointF(c.x() + ca * (ro - L), c.y() + sa * (ro - L)))
        p.setBrush(Qt.NoBrush)
        dash = QPen(line, 1, Qt.DashLine)
        p.setPen(dash)
        p.drawEllipse(c, r, r)
        p.drawEllipse(c, r * 0.56, r * 0.56)
        p.setPen(QPen(line, 1))
        p.drawEllipse(c, r * self.joy.DEAD + 3, r * self.joy.DEAD + 3)
        p.setPen(QColor(C["muted"]))
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
        p.setFont(f)
        for txt, x, y in (("Y+", c.x(), c.y() - ro + 20), ("Y−", c.x(), c.y() + ro - 12), ("X−", c.x() - ro + 18, c.y() + 4),
                          ("X+", c.x() + ro - 18, c.y() + 4)):
            p.drawText(QRectF(x - 14, y - 8, 28, 14), Qt.AlignCenter, txt)
        k = QPointF(c.x() + self.knob.x() * r, c.y() - self.knob.y() * r)
        if self.pressed:
            p.setPen(QPen(QColor(C["accent_hi"]), 2.5))
            p.drawLine(c, k)
        p.setPen(QPen(QColor(C["accent_hi"] if self.pressed else C["border"]), 1.5))
        p.setBrush(QColor(C["panel"]) if en else QColor(C["panel2"]))
        p.drawEllipse(k, 22, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["accent_hi"] if self.pressed else C["muted"]))
        p.drawEllipse(k, 5, 5)
        p.end()


# ======================================================================= il componente completo
class JogPad(QWidget):
    """Frecce o joystick, Puntino e Lucciola, passi e «Continuo». get_feed() = velocità del jog (mm/min)."""
    # senza margine interno: nei mezzi pulsanti stretti (25 px) il margine del tema schiaccerebbe l'icona
    _BTN_CSS = "QToolButton { padding: 0px; }"
    _GLOW_ON_CSS = "QToolButton { padding: 0px; background:#FFD43B; border:1px solid #B8860B; border-radius:6px; }"

    def __init__(self, ctl, settings, get_profile, get_head, get_feed, parent=None):
        super().__init__(parent)
        self.ctl, self.qs = ctl, settings
        self.get_profile, self.get_head, self.get_feed = get_profile, get_head, get_feed
        self.laser = None
        self._cont = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(5)
        # Puntino e Lucciola (si spostano fra le due pagine)
        self.b_dot = QToolButton()
        self.b_dot.setIcon(style.icon("dot", "#FF6B6B", 20))
        self.b_dot.setToolTip(tr("Puntino: tieni premuto per accendere il laser alla potenza del puntino (scheda Laser)"))
        self.b_dot.pressed.connect(lambda: self._dot(True))
        self.b_dot.released.connect(lambda: self._dot(False))
        self.b_glow = QToolButton()
        self.b_glow.setCheckable(True)
        self.b_glow.setIcon(style.icon("glow", "#FFD43B", 20, active="#3A2A00"))
        self.b_glow.clicked.connect(self._glow_clicked)
        self._glow_tip()
        # pagina 1: frecce
        self.stack = QStackedWidget()
        self.page_arrows = QWidget()
        grid = QGridLayout(self.page_arrows)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(5)
        arrows = [("arrow_ul", -1, 1), ("arrow_up", 0, 1), ("arrow_ur", 1, 1), ("arrow_left", -1, 0), None,
                  ("arrow_right", 1, 0), ("arrow_dl", -1, -1), ("arrow_down", 0, -1), ("arrow_dr", 1, -1)]
        self.jog_buttons = []
        for i, a in enumerate(arrows):
            r, c = divmod(i, 3)
            if a is None:
                self.center = QWidget()
                self.center.setFixedSize(52, 44)
                self.center_l = QHBoxLayout(self.center)
                self.center_l.setContentsMargins(0, 0, 0, 0)
                self.center_l.setSpacing(2)
                grid.addWidget(self.center, r, c)
                continue
            name, dx, dy = a
            b = QToolButton()
            b.setFixedSize(52, 44)
            b.setIcon(style.icon(name, size=22))
            b.setIconSize(b.size() * 0.45)
            b.pressed.connect(lambda dx=dx, dy=dy: self.jog_press(dx, dy))
            b.released.connect(self.jog_release)
            grid.addWidget(b, r, c)
            self.jog_buttons.append(b)
        self.stack.addWidget(self.page_arrows)
        # pagina 2: joystick
        self.page_joy = QWidget()
        jl = QVBoxLayout(self.page_joy)
        jl.setContentsMargins(0, 0, 0, 0)
        jl.setSpacing(4)
        self.joy = JoyJog(ctl, get_profile, get_head, get_feed, self)
        self.pad = JoystickPad(self.joy, self._readout)
        jl.addWidget(self.pad, 0, Qt.AlignHCenter)
        self.joy_row = QHBoxLayout()
        self.joy_row.setSpacing(6)
        self.joy_row.addStretch(1)
        self.joy_row.addStretch(1)
        jl.addLayout(self.joy_row)
        self.stack.addWidget(self.page_joy)
        v.addWidget(self.stack, 0, Qt.AlignLeft)
        # interruttore Frecce | Joystick e lettura
        mode = QHBoxLayout()
        mode.setSpacing(0)
        self.b_arrows = QToolButton()
        self.b_arrows.setText(tr("Frecce"))
        self.b_arrows.setIcon(style.icon("move", size=16))
        self.b_joy = QToolButton()
        self.b_joy.setText(tr("Joystick"))
        self.b_joy.setIcon(style.icon("joystick", size=16))
        self.mode_group = QButtonGroup(self)
        for b in (self.b_arrows, self.b_joy):
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setMinimumHeight(26)
            self.mode_group.addButton(b)
            mode.addWidget(b)
        self.b_arrows.setToolTip(tr("Frecce: la testa si sposta del passo scelto (o finché tieni premuto, con «Continuo»)"))
        self.b_joy.setToolTip(tr("Joystick: movimento continuo in qualsiasi direzione, finché tieni premuto"))
        self.readout = QLabel("")
        self.readout.setObjectName("muted")
        mode.addSpacing(10)
        mode.addWidget(self.readout, 1)
        v.addLayout(mode)
        # passi e Continuo
        self.steps_w = QWidget()
        sv = QVBoxLayout(self.steps_w)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(3)
        sv.addWidget(QLabel(tr("Passo (mm)")))
        seg = QHBoxLayout()
        seg.setSpacing(4)
        self.steps = []
        try:
            saved = float(self.qs.value("jog_step", 10))
        except (TypeError, ValueError):
            saved = 10.0
        for s in STEPS:
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
        sv.addLayout(seg)
        v.addWidget(self.steps_w)
        joy_mode = self.qs.value("jog_mode", "arrows") == "joystick"
        (self.b_joy if joy_mode else self.b_arrows).setChecked(True)
        self.mode_group.buttonClicked.connect(lambda b: self.set_mode("joystick" if b is self.b_joy else "arrows"))
        self.set_mode("joystick" if joy_mode else "arrows", save=False)
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(250)
        self._sync_timer.timeout.connect(self._sync)
        self._sync_timer.start()
        self.set_connected(False)

    # ---- modalità
    def mode(self):
        return "joystick" if self.stack.currentWidget() is self.page_joy else "arrows"

    def set_mode(self, m, save=True):
        joy = m == "joystick"
        self.joy.stop()
        for b in (self.b_dot, self.b_glow):
            b.setParent(None)
        if joy:
            for b in (self.b_dot, self.b_glow):
                b.setFixedSize(44, 30)
            self.joy_row.insertWidget(1, self.b_dot)
            self.joy_row.insertWidget(2, self.b_glow)
            self.stack.setCurrentWidget(self.page_joy)
        else:
            for b in (self.b_dot, self.b_glow):
                b.setFixedSize(25, 44)
            self.center_l.addWidget(self.b_dot)
            self.center_l.addWidget(self.b_glow)
            self.stack.setCurrentWidget(self.page_arrows)
        for b in (self.b_dot, self.b_glow):
            b.setIconSize(QSize(18, 18))
            b.show()
        self.b_dot.setStyleSheet(self._BTN_CSS)
        self._sync()
        self.steps_w.setVisible(not joy)
        (self.b_joy if joy else self.b_arrows).setChecked(True)
        if save:
            self.qs.setValue("jog_mode", "joystick" if joy else "arrows")
        self._readout()

    def _readout(self):
        if self.mode() != "joystick":
            self.readout.setText("")
            return
        if self.pad.pressed and self.joy.active:
            v = self.joy.speed()
            self.readout.setText(tr("Zona morta") if v <= 0 else tr("{0:.0f} mm/min · {1:.0f}°", v, self.joy.angle()))
        else:
            self.readout.setText(self.joy.stop_reason or tr("Fermo"))

    # ---- frecce
    def step(self):
        for s, b in self.steps:
            if b.isChecked():
                return s
        return 10.0

    def _step(self, s, btn):
        for _, b in self.steps:
            b.setChecked(b is btn)
        self.qs.setValue("jog_step", s)

    def set_step(self, s):
        for st, b in self.steps:
            if abs(st - s) < 1e-9:
                self._step(st, b)
                return True
        return False

    def jog_press(self, dx, dy):
        if not self.ctl.connected:
            return
        if self.cont.isChecked():
            # con i soft limits GRBL rifiuta un jog oltre l'area: punto esattamente al bordo del piano
            prof = self.get_profile()
            head = self.get_head()
            if head is None:
                self._arrow_note(tr("Posizione della testa non ancora nota: aspetta un attimo o fai l'homing"))
                return
            margin = 0.5
            hx, hy = float(head.x()), float(head.y())
            bx, by = float(prof.bed_x), float(prof.bed_y)
            # 0.21.1 (Giuseppe su GitHub, Discussion #5: «se imposto continuo il tasto di sinistra non funziona»): un asse
            # già sul bordo verso cui si va non blocca più tutta la freccia (in diagonale va avanti l'altro asse), e se
            # non si può andare da nessuna parte lo dice invece di non fare niente in silenzio
            ux = float(dx) if (dx < 0 and hx > margin) or (dx > 0 and hx < bx - margin) else 0.0
            uy = float(dy) if (dy < 0 and hy > margin) or (dy > 0 and hy < by - margin) else 0.0
            L = math.hypot(ux, uy)
            t = float("inf")
            if L > 0:
                ux, uy = ux / L, uy / L
                for p, u, hi in ((hx, ux, bx), (hy, uy, by)):
                    if u > 0:
                        t = min(t, (hi - margin - p) / u)
                    elif u < 0:
                        t = min(t, (p - margin) / -u)
            if L == 0 or t <= 0 or t == float("inf"):
                self._arrow_note(self._edge_text(dx, dy))
                return
            self._arrow_note("")
            mx, my = prof.to_machine(hx + ux * t, hy + uy * t)
            self._cont = True
            self.ctl.goto_machine(mx, my, self.get_feed())
        else:
            self._arrow_note("")
            self._cont = False
            s = self.step()
            self.ctl.jog(dx * s, dy * s, self.get_feed())

    @staticmethod
    def _edge_text(dx, dy):
        sides = []
        if dx < 0:
            sides.append(tr("sinistro"))
        elif dx > 0:
            sides.append(tr("destro"))
        if dy > 0:
            sides.append(tr("in alto"))
        elif dy < 0:
            sides.append(tr("in basso"))
        return tr("Già al bordo {0}: con «Continuo» non va più in là", " / ".join(sides))

    def _arrow_note(self, text):
        """0.21.1: un messaggio breve sotto le frecce (sparisce da solo dopo qualche secondo)."""
        if self.mode() == "joystick":
            return
        self.readout.setText(text)
        self.readout.setToolTip(text)
        if text:
            QTimer.singleShot(5000, lambda t=text: self.readout.text() == t and self.readout.setText(""))

    def jog_release(self):
        if self._cont:
            self.ctl.jog_cancel()
            self._cont = False

    # ---- Puntino e Lucciola: gli stessi della scheda Laser
    def attach_laser(self, laser):
        self.laser = laser
        laser.b_glow.toggled.connect(lambda _on: self._sync())
        self._sync()

    def _dot(self, on):
        if self.laser is not None:
            self.laser.fire_changed(on)

    def _glow_clicked(self, on):
        if self.laser is None:
            self.b_glow.setChecked(False)
            return
        if on:
            self.laser.glow_start_on()
        else:
            self.laser.glow_stop()
        self._sync()

    def _glow_tip(self, left=None):
        base = tr("Lucciola: clic per accendere il laser al minimo e lasciarlo acceso (potenza e avvisi nella scheda "
                  "Laser); clic di nuovo per spegnerlo")
        if left is not None:
            s = int(left + 0.999)
            base = tr("LASER ACCESO · {0}:{1:02d}", s // 60, s % 60) + "\n" + base
        self.b_glow.setToolTip(base)

    def glow_on(self):
        return bool(self.laser is not None and self.laser._glow_on)

    def _sync(self):
        lz = self.laser
        if lz is None:
            self.b_glow.setStyleSheet(self._BTN_CSS)
            return
        on = lz._glow_on
        if self.b_glow.isChecked() != on:
            self.b_glow.setChecked(on)
        self.b_glow.setStyleSheet(self._GLOW_ON_CSS if on else self._BTN_CSS)
        self._glow_tip(lz.glow_seconds_left() if on else None)
        self.b_dot.setEnabled(lz.b_fire.isEnabled())
        self.b_glow.setEnabled(lz.b_glow.isEnabled() or on)
        if self.mode() == "joystick" and not self.pad.pressed:
            self._readout()

    def set_connected(self, ok):
        for w in self.jog_buttons + [self.pad]:
            w.setEnabled(ok)
        if not ok:
            self.joy.stop()
        if self.laser is None:
            self.b_dot.setEnabled(ok)
            self.b_glow.setEnabled(ok)
        self._sync()
